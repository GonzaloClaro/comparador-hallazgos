"""La métrica de la extracción por campo (M15) sobre las mediciones reales.

Se exige:

1. Cada run de B2 que es fuente del GT del comparador se mide con su
   adjudicación, y cada hallazgo de su Etapa 3 se mide exactamente una vez.
2. Los errores de E3 por campo (salvo la clasificación, que se mide contra el
   Excel) son exactamente los ``campos_extraccion`` de las falsas alarmas del GT
   con origen en ese run: entre ellos, las 7 D6 de Gamma con Opus (la viñeta
   del ECAP copiada a cada relé) como error de la descripción, las 8 omisiones
   (D1) de Sonnet y el relé mal asignado (D3) de Zeta con los dos modelos. Las
   cifras por modelo quedan fijadas; la clasificación no se mide donde el Excel
   no usa la lista de la SEC (Epsilon).
3. La Etapa 1 no explica ningún error de B2. Para que no sea un cero vacío: las
   únicas filas del Excel fuera del mapa de la Etapa 1 son las de nombre de relé
   distinto (B1: 11 en Epsilon, 12 en Añañuca), y las páginas de cada hallazgo
   de E3 y de cada omisión caen en el rango de su paño.
4. El control de copia (Beta y Eta, E3 contra E2 sin la Etapa 4) da en B2
   220 de 220 con Opus y 41 de 41 con los dos modelos; Sonnet pierde un guion en
   un hallazgo de Beta desdoblado en dos paños (218 de 220). B0 y B1 quedan
   fijados (B0 con las filas transversales según la regla de hoy).
5. Las filas de los CSV no llevan texto de los informes ni citas del GT.
6. Contra el GT (una ronda posterior), lo que la adjudicación dijo de un campo
   vale solo si E3 extrajo lo mismo que en el run fuente: el run de B0 de San
   Pedro con Opus, medido como si fuera B3, no hereda las 3 D6 de E3 cuyo
   resultado calza por clave (E3 no copió ahí la viñeta entera) ni el
   «correcto» de las 2 D6 de la Etapa 4 (otra descripción).
"""

from __future__ import annotations

import json
from collections import Counter
from functools import cache

import pytest

from comparador.adjudicacion import nombre_corto
from comparador.evaluar_comparador import GtAplicable, gts_de
from comparador.metricas_extraccion import (
    CAMPOS,
    FUENTE_COPIA,
    MapaE1,
    Medicion,
    Veredicto,
    filas,
    medir_casos,
    medir_run_contra_gt,
)
from comparador.metricas_lote import cargar_rondas, casos_extraccion
from comparador.schemas import EstadoHallazgo, Hallazgo, ReporteInforme
from tests.golden.datos import MEDICIONES, plano, requiere_mediciones

pytestmark = [pytest.mark.golden, requiere_mediciones]

SONNET, OPUS, HAIKU = "claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"
B2 = "b2_adjudicado"
CONTEO = ("hallazgos_evaluados", "correctos", "errores", "errores_e1", "sin_referencia")
CAMPOS_COPIA = ("tupla", "descripcion", "accion_correctiva", "calificacion", "clasificacion",
                "omision", "de_mas")

# Suma de los 7 informes de B2 por modelo: (evaluados, correctos, errores de E3,
# errores de E1, sin referencia). Fijadas tras revisarlas contra el GT.
POR_MODELO_B2 = {
    (SONNET, "tupla"): (492, 491, 1, 0, 5),
    (SONNET, "descripcion"): (396, 389, 7, 0, 101),
    (SONNET, "accion_correctiva"): (386, 384, 2, 0, 111),
    (SONNET, "calificacion"): (388, 388, 0, 0, 109),
    (SONNET, "clasificacion"): (382, 364, 18, 0, 115),
    (SONNET, "polaridad"): (70, 70, 0, 0, 427),
    (SONNET, "omision"): (500, 492, 8, 0, 5),
    (SONNET, "de_mas"): (495, 492, 3, 0, 2),
    (OPUS, "tupla"): (508, 507, 1, 0, 0),
    (OPUS, "descripcion"): (404, 397, 7, 0, 104),
    (OPUS, "accion_correctiva"): (394, 394, 0, 0, 114),
    (OPUS, "calificacion"): (400, 400, 0, 0, 108),
    (OPUS, "clasificacion"): (394, 390, 4, 0, 114),
    (OPUS, "polaridad"): (68, 68, 0, 0, 440),
    (OPUS, "omision"): (508, 508, 0, 0, 0),
    (OPUS, "de_mas"): (508, 508, 0, 0, 0),
}

# Control de copia por run: (correctos, errores de E3, errores de E1, sin
# referencia) de cada campo de CAMPOS_COPIA. Fijadas tras revisarlas: en B0, Opus
# reescribe descripciones (25 en Beta, 18 en Eta) y Sonnet y Haiku sacan la
# tabla de Tiempos Teóricos de Eta como hallazgos de D1 (de más); en B2,
# Haiku asigna a otro relé 6 hallazgos de ES23 en Beta.
COPIA = {
    ("B0", SONNET, "Beta"): ((220, 0, 0, 0), (220, 0, 0, 0), (216, 4, 0, 0), (220, 0, 0, 0),
                               (219, 1, 0, 0), (220, 0, 0, 0), (220, 0, 0, 0)),
    ("B0", SONNET, "Eta"): ((41, 0, 0, 3), (40, 1, 0, 3), (40, 0, 0, 4), (40, 0, 0, 4),
                                 (40, 0, 0, 4), (41, 0, 0, 3), (41, 3, 0, 0)),
    ("B0", OPUS, "Beta"): ((220, 0, 0, 0), (195, 25, 0, 0), (195, 0, 0, 25), (195, 0, 0, 25),
                             (194, 1, 0, 25), (220, 0, 0, 0), (220, 0, 0, 0)),
    ("B0", OPUS, "Eta"): ((41, 0, 0, 0), (23, 18, 0, 0), (23, 0, 0, 18), (23, 0, 0, 18),
                               (23, 0, 0, 18), (41, 0, 0, 0), (41, 0, 0, 0)),
    ("B0", HAIKU, "Beta"): ((220, 0, 0, 0), (218, 2, 0, 0), (209, 9, 0, 2), (218, 0, 0, 2),
                              (206, 12, 0, 2), (220, 0, 0, 0), (220, 0, 0, 0)),
    ("B0", HAIKU, "Eta"): ((40, 0, 1, 7), (26, 15, 0, 7), (26, 0, 0, 22), (26, 0, 0, 22),
                                (23, 3, 0, 22), (41, 0, 0, 7), (41, 7, 0, 0)),
    ("B1", SONNET, "Beta"): ((220, 0, 0, 0), (218, 2, 0, 0), (218, 0, 0, 2), (218, 0, 0, 2),
                               (218, 0, 0, 2), (220, 0, 0, 0), (220, 0, 0, 0)),
    ("B1", SONNET, "Eta"): ((41, 0, 0, 0),) * 7,
    ("B1", OPUS, "Beta"): ((220, 0, 0, 0), (218, 2, 0, 0), (218, 0, 0, 2), (218, 0, 0, 2),
                             (218, 0, 0, 2), (220, 0, 0, 0), (220, 0, 0, 0)),
    ("B1", OPUS, "Eta"): ((41, 0, 0, 0),) * 7,
    ("B1", HAIKU, "Beta"): ((219, 0, 0, 0), (219, 0, 0, 0), (218, 1, 0, 0), (219, 0, 0, 0),
                              (219, 0, 0, 0), (219, 1, 0, 0), (219, 0, 0, 0)),
    ("B1", HAIKU, "Eta"): ((41, 0, 0, 0),) * 7,
    ("B2", SONNET, "Beta"): ((220, 0, 0, 0), (218, 2, 0, 0), (218, 0, 0, 2), (218, 0, 0, 2),
                               (218, 0, 0, 2), (220, 0, 0, 0), (220, 0, 0, 0)),
    ("B2", SONNET, "Eta"): ((41, 0, 0, 0),) * 7,
    ("B2", OPUS, "Beta"): ((220, 0, 0, 0),) * 7,
    ("B2", OPUS, "Eta"): ((41, 0, 0, 0),) * 7,
    ("B2", HAIKU, "Beta"): ((214, 6, 0, 0),) + ((220, 0, 0, 0),) * 6,
    ("B2", HAIKU, "Eta"): ((41, 0, 0, 0),) * 7,
}


@cache
def _gts() -> tuple[GtAplicable, ...]:
    return tuple(gts_de(MEDICIONES / "gt" / "comparador"))


@cache
def _mediciones() -> tuple[Medicion, ...]:
    return tuple(medir_casos(casos_extraccion(cargar_rondas(MEDICIONES)), list(_gts()),
                             mediciones=MEDICIONES))


def _de(fuente: str, ronda: str | None = None) -> list[Medicion]:
    return [m for m in _mediciones()
            if m.fuente == fuente and (ronda is None or m.caso.ronda == ronda)]


def _una(fuente: str, ronda: str, modelo: str, informe: str) -> Medicion:
    (m,) = [m for m in _de(fuente, ronda)
            if m.caso.modelo == modelo and plano(m.caso.informe) == plano(informe)]
    return m


def _errores(m: Medicion, campo: str) -> int:
    conteo = m.medida.conteo(campo)
    return conteo["errores"] + conteo["errores_e1"]


def test_cada_run_fuente_del_gt_se_mide_y_cada_hallazgo_una_vez() -> None:
    # Las fuentes base (B2). B3, que complementa el GT, se mide contra el GT.
    fuentes = sorted((f.modelo, f.run_id) for g in _gts() for f in g.gt.fuentes
                     if not f.complementa)
    medidos = _de(B2)
    assert len(fuentes) == 14
    assert sorted((m.caso.modelo, m.caso.run_dir.name) for m in medidos) == fuentes
    for m in medidos:
        e3 = json.loads((m.caso.run_dir / "etapa3_pdf_hallazgos.json").read_text("utf-8"))
        assert sorted(h.indice_e3 for h in m.medida.hallazgos) == list(range(len(e3)))


def test_los_errores_de_e3_son_los_campos_extraccion_del_gt() -> None:
    # Los orígenes de las fuentes base (B2), las que se miden aquí: lo que adjudica
    # una repetición de E4 (AG1, el D2 de Alfa con Sonnet) es de su reporte.
    esperado: Counter[tuple[str, str, str]] = Counter()
    for g in _gts():
        bases = {(f.ronda, f.run_id) for f in g.gt.fuentes if not f.complementa}
        for it in g.gt.items:
            for o in it.origenes:
                if (o.ronda, o.run_id) not in bases:
                    continue
                for fallo in it.campos_extraccion:
                    esperado[(o.modelo, nombre_corto(g.gt.informe), fallo.value)] += 1
    obtenido: Counter[tuple[str, str, str]] = Counter()
    for m in _de(B2):
        for campo in CAMPOS:
            if campo != "clasificacion" and (n := _errores(m, campo)):
                obtenido[(m.caso.modelo, m.caso.informe, campo)] += n
    assert obtenido == esperado
    por_modelo: Counter[tuple[str, str]] = Counter()
    for (modelo, _, campo), n in obtenido.items():
        por_modelo[(modelo, campo)] += n
    assert por_modelo == {
        (SONNET, "omision"): 8, (SONNET, "tupla"): 1, (SONNET, "de_mas"): 3,
        (SONNET, "descripcion"): 7, (SONNET, "accion_correctiva"): 2,
        (OPUS, "tupla"): 1, (OPUS, "descripcion"): 7,
    }


def test_cifras_por_modelo_en_b2() -> None:
    suma: dict[tuple[str, str], list[int]] = {}
    for m in _de(B2):
        for campo in CAMPOS:
            acumulado = suma.setdefault((m.caso.modelo, campo), [0] * len(CONTEO))
            for i, valor in enumerate(m.medida.conteo(campo)[k] for k in CONTEO):
                acumulado[i] += valor
    assert {k: tuple(v) for k, v in suma.items()} == POR_MODELO_B2
    # Epsilon: su Excel no usa la lista de la SEC, no hay referencia de clasificación.
    for modelo in (SONNET, OPUS):
        conteo = _una(B2, "B2", modelo, "Epsilon").medida.conteo("clasificacion")
        assert (conteo["hallazgos_evaluados"], conteo["sin_referencia"]) == (0, 20)


def test_las_7_d6_de_gamma_con_opus_son_error_de_e3_en_la_descripcion() -> None:
    m = _una(B2, "B2", OPUS, "Gamma")
    errores = [h for h in m.medida.hallazgos if h.veredictos["descripcion"] == Veredicto.ERROR]
    assert len(errores) == 7
    assert {h.referencia for h in errores} == {"D6"}
    assert m.medida.conteo("descripcion")["errores_e1"] == 0


def test_la_etapa1_no_explica_ningun_error_de_b2() -> None:
    assert sum(m.medida.conteo(c)["errores_e1"] for m in _de(B2) for c in CAMPOS) == 0

    fuera_del_mapa: Counter[tuple[str, str]] = Counter()
    for m in _de(B2):
        run = m.caso.run_dir
        mapa = MapaE1.del_run(run)
        reporte = ReporteInforme.model_validate_json(
            (run / "reporte_final.json").read_text("utf-8"))
        for r in reporte.resultados:
            x = r.hallazgo_excel
            if x is not None and r.estado != EstadoHallazgo.TRANSVERSAL and mapa.explica(
                    x.pano, x.rele):
                assert r.estado == EstadoHallazgo.EXTRA_EN_EXCEL
                fuera_del_mapa[(m.caso.modelo, m.caso.informe)] += 1
        e3 = [Hallazgo.model_validate(h) for h in json.loads(
            (run / "etapa3_pdf_hallazgos.json").read_text("utf-8"))]
        assert not [h for h in e3 if mapa.explica(h.pano, h.rele, h.evidencia.pagina_pdf)]
    assert fuera_del_mapa == {(SONNET, "Epsilon"): 11, (OPUS, "Epsilon"): 11,
                              (SONNET, "Añañuca"): 12, (OPUS, "Añañuca"): 12}
    # Las B1 son la grafía del relé en el Excel (invariante 19c): no son errores.
    b1 = Counter((o.modelo, nombre_corto(g.gt.informe)) for g in _gts() for it in g.gt.items
                 if it.subclase == "B1" and it.estado == EstadoHallazgo.EXTRA_EN_EXCEL
                 for o in it.origenes)
    assert b1 == fuera_del_mapa


def test_omisiones_y_hallazgos_de_mas_por_tupla() -> None:
    por_tupla = {(m.caso.modelo, m.caso.informe): m.medida.por_tupla() for m in _de(B2)}
    con_omision = {k: (v["omisiones"], v["tuplas_con_omision"])
                   for k, v in por_tupla.items() if v["omisiones"]}
    assert con_omision == {(SONNET, "Alfa"): (6, 3), (SONNET, "Gamma"): (2, 2)}
    con_de_mas = {k: (v["de_mas"], v["tuplas_con_de_mas"])
                  for k, v in por_tupla.items() if v["de_mas"]}
    assert con_de_mas == {(SONNET, "Alfa"): (3, 3)}


def _evaluados_correctos(m: Medicion, campo: str) -> tuple[int, int]:
    conteo = m.medida.conteo(campo)
    return conteo["hallazgos_evaluados"], conteo["correctos"]


@pytest.mark.parametrize("modelo,informe,n", [
    (OPUS, "Beta", 220), (OPUS, "Eta", 41), (SONNET, "Eta", 41)])
def test_control_de_copia_en_b2_completo(modelo: str, informe: str, n: int) -> None:
    m = _una(FUENTE_COPIA, "B2", modelo, informe)
    for campo in ("tupla", "descripcion", "accion_correctiva", "calificacion",
                  "clasificacion", "omision", "de_mas"):
        assert _evaluados_correctos(m, campo) == (n, n), campo
    assert m.medida.omisiones == []


def test_control_de_copia_sonnet_pierde_un_guion_en_beta() -> None:
    m = _una(FUENTE_COPIA, "B2", SONNET, "Beta")
    assert m.medida.conteo("descripcion") == {
        "hallazgos_evaluados": 220, "correctos": 218, "errores": 2, "errores_e1": 0,
        "sin_referencia": 0}
    # El par se presume por la tupla: los demás campos de esos dos no se juzgan.
    assert m.medida.conteo("calificacion")["sin_referencia"] == 2
    assert (m.medida.conteo("omision")["errores"], m.medida.conteo("de_mas")["errores"]) == (0, 0)


def test_control_de_copia_fijado_en_las_tres_rondas() -> None:
    obtenido = {(m.caso.ronda, m.caso.modelo, m.caso.informe): tuple(
        tuple(m.medida.conteo(c)[k] for k in CONTEO[1:]) for c in CAMPOS_COPIA)
        for m in _de(FUENTE_COPIA) if m.caso.ronda in ("B0", "B1", "B2")}
    assert obtenido == COPIA


def test_filas_sin_texto_de_los_informes_ni_citas_del_gt() -> None:
    por_campo, por_tupla = filas(list(_mediciones()))
    citas = {c.texto for g in _gts() for it in g.gt.items if it.lado_pdf
             for c in it.lado_pdf.citas}
    citas |= {c.texto for g in _gts() for it in g.gt.items if it.lado_excel
              for c in it.lado_excel.citas}
    assert len(citas) > 100
    valores = {str(v) for f in por_campo + por_tupla for v in f.values()}
    assert not [v for v in valores if len(v) > 40]
    assert not [c for c in citas for v in valores if v and v in c and len(v) > 12]


def test_contra_el_gt_no_se_hereda_lo_que_e3_ya_no_extrae_igual() -> None:
    """La B3 sintética de la revisión adversarial (copia del run de B0 de San
    Pedro con Opus): antes daba la descripción con 3 errores de E3 y 2 correctos
    heredados; ahora 0 evaluados y los 5 sin referencia."""
    (caso,) = [c for c in casos_extraccion(cargar_rondas(MEDICIONES))
               if (c.ronda, c.modelo) == ("B0", OPUS) and plano(c.informe) == plano("Gamma")]
    (gt,) = [g for g in _gts() if plano("Gamma") in plano(g.gt.informe)]
    medida = medir_run_contra_gt(caso.run_dir, gt.gt, modelo=OPUS, mediciones=MEDICIONES)
    por_referencia = Counter((h.referencia, h.veredictos["descripcion"])
                             for h in medida.hallazgos if h.referencia == "D6")
    assert por_referencia == {("D6", Veredicto.SIN_REFERENCIA): 5}
    assert medida.conteo("descripcion") == dict(zip(CONTEO, (0, 0, 0, 0, 90), strict=True))
    assert medida.conteo("accion_correctiva")["errores"] == 0
