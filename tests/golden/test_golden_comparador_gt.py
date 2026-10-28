"""El GT del comparador (M64) contra las mediciones reales de B2, B3 y AG1.

El GT (``mediciones/gt/comparador/<carpeta>.json``) se construye desde la
adjudicación de B2 y las que lo complementan, B3 y las repeticiones de E4 de AG1
(``comparador.gt_comparador``), y se evalúa sin el índice del resultado
(``comparador.evaluar_comparador``). Aquí se exige:

1. Cada run de B2 con Sonnet y con Opus reproduce su fila de
   ``docs/metricas/datos/comparador_adjudicado.csv`` (clases A-E y OK, alertas,
   precisión y cifras sin duplicados), con 0 resultados sin adjudicar dentro del
   universo y 0 posibles errores escondidos.
2. Los 3 errores reales del Excel salen «no mostrado» en los runs de B2
   exactamente en los modelos que declara la compuerta
   (``test_golden_errores_no_mostrados.ERRORES``), con la misma regla, y el GT
   los define igual. Las repeticiones de E4 se exigen en ese golden, sin xfail.
3. El GT armado solo con la adjudicación de Sonnet, buscado por clave en el run
   de Opus del mismo informe: 288 ítems encontrados una vez, 9 sin encontrar y 0
   ambiguos. La clave del PDF no lleva la clasificación (Sonnet y Opus la rotulan
   distinto: con ella serían 239 y 58) y la cita se compara sin puntuación (la
   capa de texto da «Criticidad menor • Se debe…»; E3, «… | Criticidad menor | •
   Se debe…»). La exploración previa (279/18/0) no hacía esto último.
4. Los GT guardados son exactamente los que se construyen hoy desde la
   adjudicación (sin conflictos de clase entre modelos) y validan contra sus
   fuentes.
5. Los ítems A que son el mismo error (``evaluar_comparador.mismo_error``) son
   solo los dos pares conocidos, y con ellos cada run de B2 pierde solo los A
   que de verdad no muestra.
6. B3 (Gamma con Opus) complementa el GT de B2: sus 3 «difiere» que el GT de
   B2 no adjudicaba quedan como C1 (P14) y el run no deja nada sin adjudicar.
7. Las 5 repeticiones de E4 de AG1 (``replay_e4/AG1/<run_id>``, el run_id de su
   origen de B2) complementan el GT: cada una queda sin nada sin adjudicar ni
   posibles escondidos, con sus cifras.
8. Las 5 de AG2 (la asignación global con la regla V2 de PD71) quedan
   adjudicadas igual, con sus cifras; solo Alfa con Opus es fuente del GT
   (un D6 de la Etapa 4, i137), los otros 4 runs los cubre el GT de antes.

Sin texto de los informes: solo conteos, estados y referencias.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from comparador.adjudicacion import buscar, cargar_alineada, nombre_corto
from comparador.evaluar_comparador import evaluar_run, gt_aplicable, gts_de, mismo_error, resumen
from comparador.gt_comparador import (
    adjudicaciones_por_informe,
    cargar_gt,
    construir_gt,
    hashes_del_run,
    nombre_archivo,
    serializar,
    validar_gt,
)
from comparador.persistence import cargar_json
from tests.golden.datos import MEDICIONES, ROOT, plano, requiere_mediciones
from tests.golden.test_golden_errores_no_mostrados import ERRORES, MODELOS, verificar_error

pytestmark = [pytest.mark.golden, requiere_mediciones]

GT_DIR = MEDICIONES / "gt" / "comparador"
CSV_ADJUDICADO = ROOT / "docs" / "metricas" / "datos" / "comparador_adjudicado.csv"
COLUMNAS = ("items_revisados", "alertas", "A", "B", "C", "D", "E", "OK", "precision_alertas",
            "A_sin_duplicados", "D_sin_duplicados")
SONNET, OPUS = "claude-sonnet-5-5", "claude-opus-5-5"


def _filas() -> list[dict[str, str]]:
    """Las filas de B2: sus adjudicaciones cubren todo su run. La de B3 solo
    adjudica lo que el GT de B2 no adjudicaba (test de B3, abajo)."""
    with CSV_ADJUDICADO.open(encoding="utf-8", newline="") as f:
        return [fila for fila in csv.DictReader(f) if fila["ronda"] == "B2"]


def _gt(informe_corto: str) -> Any:
    (ruta,) = [r for r in GT_DIR.glob("*.json") if plano(informe_corto) in plano(r.name)]
    return cargar_gt(ruta)


def _run(fila: dict[str, str]) -> Path:
    return MEDICIONES / fila["ronda"].lower() / "runs" / fila["run_id"]


@pytest.mark.parametrize("fila", _filas(), ids=lambda f: f"{f['modelo'][7:12]}-{f['informe']}")
def test_cada_run_de_b2_reproduce_su_fila_adjudicada(fila: dict[str, str]) -> None:
    datos = resumen(evaluar_run(_run(fila), _gt(fila["informe"])))
    obtenido = {
        "items_revisados": datos["adjudicados"], "alertas": datos["alertas"],
        **{c: datos[c] for c in ("A", "B", "C", "D", "E", "OK")},
        "precision_alertas": "" if datos["precision_alertas"] is None
        else datos["precision_alertas"],
        "A_sin_duplicados": datos["A_sin_duplicados"],
        "D_sin_duplicados": datos["D_sin_duplicados"],
    }
    assert {k: str(v) for k, v in obtenido.items()} == {k: fila[k] for k in COLUMNAS}
    assert (datos["sin_adjudicar"], datos["alertas_sin_adjudicar"]) == (0, 0)
    assert datos["posibles_escondidos"] == []


def test_fuera_de_universo_solo_los_coincide_no_muestreados_con_diferencia_de_forma() -> None:
    """Beta y Eta: la muestra más la regla de texto idéntico (D13) cubren
    todos los «coincide» salvo los 2 de Beta con Sonnet que difieren en un guion."""
    vistos = {}
    for fila in _filas():
        if fila["informe"] in ("Beta", "Eta"):
            datos = resumen(evaluar_run(_run(fila), _gt(fila["informe"])))
            vistos[(fila["modelo"], fila["informe"])] = (
                datos["adjudicados"], datos["ok_texto_identico"], datos["fuera_de_universo"])
    assert vistos == {
        (SONNET, "Beta"): (10, 208, 2), (OPUS, "Beta"): (10, 210, 0),
        (SONNET, "Eta"): (10, 31, 0), (OPUS, "Eta"): (10, 31, 0),
    }


@pytest.mark.parametrize("error", ERRORES, ids=lambda e: f"{e.subestacion}-{e.fila_excel}")
def test_los_errores_del_excel_salen_no_mostrados_donde_dice_la_compuerta(error: Any) -> None:
    gt = _gt(error.subestacion)
    (definido,) = [e for e in gt.errores_excel if e.fila_excel == error.fila_excel]
    assert (definido.pagina_pdf, definido.clasificacion_pdf, tuple(definido.campos),
            definido.contraparte_validada, set(definido.no_mostrado_en_b2)) == (
        error.pagina_pdf, error.clasificacion_pdf, error.campos, error.contraparte_validada,
        set(error.escondido_en_b2))
    # Los runs de B2: la compuerta define los casos por lo que B2 no mostró. Las
    # rondas posteriores y las repeticiones de E4 se exigen en ese golden.
    for f in (f for f in gt.fuentes if f.ronda == "B2"):
        assert f.modelo in MODELOS
        run = MEDICIONES / f.carpeta
        (estado,) = [e for e in evaluar_run(run, gt).errores_excel if e.id == definido.id]
        esperado = "no_mostrado" if f.modelo in error.escondido_en_b2 else "mostrado"
        assert estado.estado == esperado, (f.modelo, estado.motivos)
        # La misma regla que la compuerta, sobre el mismo reporte.
        reporte = cargar_json(run / "reporte_final.json")
        assert bool(verificar_error(reporte, error)) == (esperado == "no_mostrado")


def test_gt_de_sonnet_buscado_en_el_run_de_opus() -> None:
    cuenta: Counter[str] = Counter()
    for rutas in adjudicaciones_por_informe(MEDICIONES).values():
        (sonnet,) = [r for r in rutas if r.name.startswith("b2_sonnet")]
        (opus,) = [r for r in rutas if r.name.startswith("b2_opus")]
        gt = construir_gt(MEDICIONES, [sonnet], con_errores_excel=False)
        resultados = cargar_alineada(MEDICIONES, opus).resultados
        cuenta.update(buscar(g.claves(), resultados).estado for g in gt.items)
    assert dict(cuenta) == {"unico": 288, "ninguno": 9}


@pytest.mark.parametrize("informe", sorted(adjudicaciones_por_informe(MEDICIONES))
                         if MEDICIONES.is_dir() else [])
def test_el_gt_guardado_es_el_que_se_construye_y_valida(informe: str) -> None:
    rutas = adjudicaciones_por_informe(MEDICIONES)[informe]
    assert {p.name.split("_")[1] for p in rutas} == {"sonnet", "opus"}
    gt = construir_gt(MEDICIONES, rutas)          # un conflicto entre modelos fallaría aquí
    guardado = GT_DIR / nombre_archivo(informe)
    assert guardado.read_text(encoding="utf-8") == serializar(gt)
    assert validar_gt(gt, MEDICIONES) == []
    assert sum(len(i.origenes) for i in gt.items) == sum(
        len(cargar_alineada(MEDICIONES, r).adjudicacion.items) for r in rutas)


def test_los_a_que_son_el_mismo_error_no_cuentan_como_perdidos() -> None:
    """Gamma: el hallazgo que Opus deja como falta y Sonnet empareja con una
    fila ajena (A1, i066 e i031); Alfa: el que el Excel invierte, falta con
    Opus y «difiere» con Sonnet (A5, i068 e i121). Antes cada run contaba como
    perdido el ítem del otro modelo (B2 Opus Gamma: 1 en vez de 0).

    Añañuca, i050 (desde AG1): la fila 39 con la conclusión de coordinación de la
    pág. 20, el A3 que las repeticiones de E4 muestran y que ningún run de B2
    mostró (el error e1, CB08): los dos runs de B2 lo pierden."""
    pares = set()
    for ruta in sorted(GT_DIR.glob("*.json")):
        gt = cargar_gt(ruta)
        items_a = [g for g in gt.items if g.clase == "A"]
        pares |= {(nombre_corto(gt.informe), g.id, h.id) for g in items_a for h in items_a
                  if g.id < h.id and mismo_error(g, h)}
    # Alfa C3 y C4 (CB69): con el control de códigos (repetición CC, 2026-10-27) el
    # mismo A4 suma la acción (i138 e i139, junto a i017 e i024).
    assert pares == {("Gamma", "i031", "i066"), ("Alfa", "i068", "i121"),
                     ("Alfa", "i017", "i138"), ("Alfa", "i024", "i139")}
    perdidos = {(f["modelo"], f["informe"]): resumen(evaluar_run(_run(f), _gt(f["informe"])))[
        "a_perdidos"] for f in _filas()}
    assert {k: v for k, v in perdidos.items() if v} == {
        (SONNET, "Gamma"): ["i064", "i068"], (SONNET, "Alfa"): ["i130"],
        (OPUS, "Alfa"): ["i108"], (SONNET, "Añañuca"): ["i050"],
        (OPUS, "Añañuca"): ["i050"]}


def test_b3_complementa_el_gt_y_no_deja_nada_sin_adjudicar() -> None:
    """Gamma con Opus en B3: el GT de B2 adjudicaba 62 de sus 65 resultados.
    Los otros 3, los «difiere» de las filas 22, 25 y 28 del Excel (C1, C2 y C3,
    SEL 351R), que en B2 salieron «coincide» y son OK, se adjudicaron en
    b3_opus_Gamma.json como C1 que depende de P14: la fila del Excel junta la
    viñeta del ECAP de la tabla del paño con su fila «Cumplimiento NTSyCS»
    (variante «difiere» de CB17). Los OK de B2 no cambian."""
    gt = _gt("Gamma")
    (b3,) = [f for f in gt.fuentes if f.ronda == "B3"]
    assert (b3.modelo, b3.complementa, b3.universo.items, b3.universo.adjudicados_antes) == (
        OPUS, ["B2"], 3, 62)
    datos = resumen(evaluar_run(MEDICIONES / "b3" / "runs" / b3.run_id, gt))
    assert {c: datos[c] for c in ("A", "B", "C", "D", "E", "OK", "alertas", "sin_adjudicar",
                                  "precision_alertas", "A_sin_duplicados",
                                  "D_sin_duplicados")} == {
        "A": 11, "B": 0, "C": 25, "D": 11, "E": 0, "OK": 18, "alertas": 47, "sin_adjudicar": 0,
        "precision_alertas": 0.5, "A_sin_duplicados": 9, "D_sin_duplicados": 9}
    assert (datos["a_perdidos"], datos["posibles_escondidos"]) == ([], [])
    nuevos = [g for g in gt.items if any(o.run_id == b3.run_id for o in g.origenes)]
    filas = []
    for g in nuevos:
        assert g.lado_excel is not None and g.lado_pdf is not None
        filas.append((g.pano, g.estado.value, g.campos, g.subclase, g.depende_de,
                      g.etapa_causa, g.lado_excel.fila, g.lado_pdf.pagina))
    assert filas == [(pano, "difiere", ["descripcion"], "C1", ["P14"], None, fila, pagina)
                     for pano, fila, pagina in (("C1", 22, 7), ("C2", 25, 9), ("C3", 28, 11))]
    for fila in (22, 25, 28):
        (ok,) = [g for g in gt.items if g.estado.value == "coincide" and g.lado_excel
                 and g.lado_excel.fila == fila]
        assert (ok.clase, {o.modelo for o in ok.origenes}) == ("OK", {SONNET, OPUS})


# Por repetición de AG1: clases, alertas, precisión, a_perdidos y errores del
# Excel, contra el GT que complementan (adjudicación verificada contra la fuente).
CIFRAS_AG1 = {
    (SONNET, "Alfa"): ({"A": 14, "B": 0, "C": 19, "D": 13, "E": 0, "OK": 64}, 46, 0.5185,
                           ["i130"], {"e1": "mostrado", "e2": "no_mostrado"}),
    (OPUS, "Alfa"): ({"A": 15, "B": 0, "C": 18, "D": 4, "E": 1, "OK": 71}, 37, 0.7895, [],
                         {"e1": "mostrado", "e2": "mostrado"}),
    (SONNET, "Gamma"): ({"A": 9, "B": 0, "C": 23, "D": 10, "E": 0, "OK": 21}, 42, 0.4737,
                            ["i064", "i068"], {}),
    (SONNET, "Añañuca"): ({"A": 1, "B": 24, "C": 16, "D": 0, "E": 0, "OK": 5}, 41, 1.0, [],
                          {"e1": "mostrado"}),
    (OPUS, "Añañuca"): ({"A": 1, "B": 24, "C": 16, "D": 0, "E": 0, "OK": 5}, 41, 1.0, [],
                        {"e1": "mostrado"}),
}


def test_las_repeticiones_de_e4_de_ag1_complementan_el_gt_sin_dejar_nada_sin_adjudicar() -> None:
    """Cada repetición de AG1 es una fuente del GT de su informe con el run_id de
    su origen de B2 y su propia carpeta; su adjudicación cubre lo que el GT de
    antes no adjudicaba (Gamma: el de B2 y B3, porque AG1 se corrió después
    de B3). Alfa con Opus deja el único error escondido (E, i136): el falso
    «coincide» de la fila 69 en E7 (CB01, CB24)."""
    vistas = {}
    for ruta in sorted(GT_DIR.glob("*.json")):
        gt = cargar_gt(ruta)
        for f in (f for f in gt.fuentes if f.ronda == "AG1"):
            assert (f.carpeta, f.ronda_origen) == (f"replay_e4/AG1/{f.run_id}", "B2")
            assert f.run_id in {g.run_id for g in gt.fuentes if g.ronda == "B2"}
            assert f.complementa == (["B2", "B3"] if nombre_corto(gt.informe) == "Gamma"
                                     else ["B2"])
            datos = resumen(evaluar_run(MEDICIONES / f.carpeta, gt))
            assert (datos["sin_adjudicar"], datos["posibles_escondidos"],
                    datos["ok_texto_identico"]) == (0, [], 0)
            vistas[(f.modelo, nombre_corto(gt.informe))] = (
                {c: datos[c] for c in ("A", "B", "C", "D", "E", "OK")}, datos["alertas"],
                datos["precision_alertas"], datos["a_perdidos"],
                {e["id"]: e["estado"] for e in datos["errores_excel"]})
    assert vistas == CIFRAS_AG1
    (escondido,) = [g for ruta in sorted(GT_DIR.glob("*.json")) for g in cargar_gt(ruta).items
                    if g.clase == "E"]
    assert escondido.lado_excel is not None
    assert (escondido.id, escondido.pano, escondido.estado.value, escondido.lado_excel.fila,
            [(o.ronda, o.modelo) for o in escondido.origenes]) == (
        "i136", "E7", "coincide", 69, [("AG1", OPUS)])


# AG2 (2026-10-26): las mismas cifras que AG1 salvo Alfa con Opus. E7 (fila 69)
# pasa de «coincide» a «difiere» con emparejamiento dudoso, la D5 i069 (E 1 → 0); y
# el lote del juez de redacción que se volvió a pagar (E7 ya no entra) cambió un
# veredicto con la misma entrada: CT1A/SEL 351S, fila 76, de OK (i055) a D6 (i137,
# variación del juez, CB31). Los otros 4 runs salieron enteros de la caché de AG1.
CIFRAS_AG2 = {
    **CIFRAS_AG1,
    (OPUS, "Alfa"): ({"A": 15, "B": 0, "C": 18, "D": 6, "E": 0, "OK": 70}, 39, 0.7143, [],
                         {"e1": "mostrado", "e2": "mostrado"}),
}


def test_las_repeticiones_de_e4_de_ag2_quedan_adjudicadas() -> None:
    """Cada repetición de AG2 se evalúa contra el GT de su informe sin nada sin
    adjudicar ni posibles escondidos. Solo la de Alfa con Opus es fuente:
    complementa el GT de B2 y AG1 con el único resultado que no adjudicaba."""
    gts = gts_de(GT_DIR)
    vistas = {}
    for meta in sorted((MEDICIONES / "replay_e4" / "AG2").glob("*/metadata.json")):
        hashes = hashes_del_run(meta.parent)
        assert hashes is not None
        aplicable = gt_aplicable(gts, *hashes)
        assert aplicable is not None
        datos = resumen(evaluar_run(meta.parent, aplicable.gt))
        assert (datos["sin_adjudicar"], datos["posibles_escondidos"],
                datos["ok_texto_identico"]) == (0, [], 0)
        vistas[(datos["modelo"], nombre_corto(aplicable.gt.informe))] = (
            {c: datos[c] for c in ("A", "B", "C", "D", "E", "OK")}, datos["alertas"],
            datos["precision_alertas"], datos["a_perdidos"],
            {e["id"]: e["estado"] for e in datos["errores_excel"]})
    assert vistas == CIFRAS_AG2
    fuentes = [(nombre_corto(g.gt.informe), f) for g in gts for f in g.gt.fuentes
               if f.ronda == "AG2"]
    assert [(s, f.modelo, f.carpeta, f.ronda_origen, f.complementa, f.universo.items,
             f.universo.adjudicados_antes) for s, f in fuentes] == [
        ("Alfa", OPUS, "replay_e4/AG2/2026-10-17_01-46-55_claude-opus-5-5", "B2",
         ["B2", "AG1"], 1, 108)]
    (nuevo,) = [g for g in _gt("Alfa").items if any(o.ronda == "AG2" for o in g.origenes)]
    assert nuevo.lado_excel is not None and nuevo.lado_pdf is not None
    assert (nuevo.id, nuevo.pano, nuevo.estado.value, nuevo.campos, nuevo.subclase,
            nuevo.etapa_causa, nuevo.depende_de, nuevo.lado_excel.fila, nuevo.lado_pdf.pagina,
            [(o.ronda, o.modelo) for o in nuevo.origenes]) == (
        "i137", "CT1A", "difiere", ["descripcion"], "D6", "e4", [], 76, 30, [("AG2", OPUS)])
