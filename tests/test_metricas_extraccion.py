"""Tests de la métrica de la extracción por campo (M15), sin API y con datos sintéticos.

Dos referencias: la adjudicación (cada hallazgo de E3 en su resultado del
reporte, evaluado contra el GT del comparador) y el control de copia (E3 contra
E2 donde el Excel copia el PDF, sin pasar por la Etapa 4). Cada campo de cada
hallazgo sale correcto, error de la Etapa 3, error de la Etapa 1 o sin
referencia; lo sin referencia nunca cuenta como correcto. Textos inventados.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from comparador.evaluar_comparador import GtAplicable
from comparador.gt_comparador import GtInforme, serializar
from comparador.metricas_extraccion import (
    CAMPOS,
    CAMPOS_COPIA,
    COLUMNAS_POR_CAMPO,
    COLUMNAS_POR_TUPLA,
    FUENTE_COPIA,
    Caso,
    MapaE1,
    Medida,
    Veredicto,
    filas,
    medir_adjudicado,
    medir_casos,
    medir_copia,
    texto_copia,
)
from comparador.schemas import Hallazgo, PanoDescubierto, ReleDescubierto, ReporteInforme
from tests.test_adjudicacion import excel as _excel
from tests.test_adjudicacion import pdf as _pdf
from tests.test_adjudicacion import resultado
from tests.test_evaluar_comparador import OPUS, gt_de, item_gt
from tests.test_gt_comparador import reporte


def pdf(pagina: int = 7, **kw: Any) -> dict[str, Any]:
    """Hallazgo del PDF con una clasificación de la lista oficial de la SEC."""
    return _pdf(pagina, **{"clasificacion": "Otros", **kw})


def excel(fila: int = 20, **kw: Any) -> dict[str, Any]:
    return _excel(fila, **{"clasificacion": "Otros", **kw})


C, E, E1, S = (Veredicto.CORRECTO, Veredicto.ERROR, Veredicto.ERROR_E1,
               Veredicto.SIN_REFERENCIA)
_LETRA = {"C": C, "E": E, "1": E1, "S": S}


def veredictos(letras: str, campos: tuple[str, ...] = CAMPOS) -> dict[str, Veredicto]:
    """'CECCCSCC' → un veredicto por campo, en el orden de ``campos`` (C correcto,
    E error de E3, 1 error de E1, S sin referencia)."""
    assert len(letras) == len(campos)
    return {c: _LETRA[x] for c, x in zip(campos, letras, strict=True)}


def seccion(nombre: str, inicio: int, fin: int,
            *reles: tuple[str, list[str]]) -> PanoDescubierto:
    return PanoDescubierto(nombre=nombre, pagina_inicio=inicio, pagina_fin=fin, reles=[
        ReleDescubierto(nombre=r, evidencia_origen="tabla", sub_panos=subs) for r, subs in reles])


# C1 y C2 comparten páginas; C3 no: una página de C1 fuera del rango de C3.
MAPA = MapaE1.de([seccion("C1", 5, 20, ("REL 1", [])), seccion("C2", 5, 25, ("REL 2", [])),
                  seccion("C3", 30, 35, ("REL 3", []))])


def item(estado: str, subclase: str, *, fila: int | None = None, pagina: int | None = None,
         campos: tuple[str, ...] = (), etapa: str = "e4", campos_e3: tuple[str, ...] = (),
         pano: str = "C1", rele: str = "REL 1",
         contraparte_pdf: int | None = None) -> dict[str, Any]:
    clase = "OK" if subclase == "OK" else subclase[0]
    datos = item_gt("i1", estado, fila=fila, pagina=pagina, campos=campos, clase=clase,
                    subclase=subclase)
    datos.update(pano=pano, rele=rele)
    if clase == "D":
        datos.update(etapa_causa=etapa, campos_extraccion=list(campos_e3))
    if contraparte_pdf is not None:
        datos["origenes"][0]["contraparte_pdf"] = {"referencia": contraparte_pdf, "cita": "x"}
    return datos


def medir(resultados: list[dict[str, Any]], items: list[dict[str, Any]], *,
          coincide: str = "todos", mapa: MapaE1 = MAPA) -> Medida:
    rep = ReporteInforme.model_validate(reporte(resultados, OPUS))
    e3 = [r.hallazgo_pdf for r in rep.resultados if r.hallazgo_pdf is not None]
    return medir_adjudicado(rep, e3, gt_de(items, coincide=coincide), mapa, modelo=OPUS)


NO = "alfa uno: no cumple"
SI = "alfa uno: cumple"

# (resultado, ítem del GT, veredictos del hallazgo en el orden de CAMPOS:
#  tupla, descripcion, accion_correctiva, calificacion, clasificacion,
#  polaridad, omision, de_mas)
CASOS_HALLAZGO = {
    "coincide OK: todo correcto, el alias de la clasificación cuenta igual": (
        resultado("coincide", pdf(7, descripcion=NO, clasificacion="Coord. de Protecciones"),
                  excel(20, descripcion=NO, clasificacion="Ver. Coord. de Protecciones")),
        item("coincide", "OK", fila=20, pagina=7), "CCCCCCCC"),
    "A4: el Excel se equivoca en la calificación, E3 acertó": (
        resultado("difiere", pdf(7, descripcion="alfa uno", calificacion="Relevante"),
                  excel(20, descripcion="alfa uno"), campos=("calificacion",)),
        item("difiere", "A4", fila=20, pagina=7, campos=("calificacion",)), "CCCCCSCC"),
    "D con la calificación de E3: E3 falló": (
        resultado("difiere", pdf(7, descripcion="alfa uno", calificacion="Relevante"),
                  excel(20, descripcion="alfa uno"), campos=("calificacion",)),
        item("difiere", "D7", fila=20, pagina=7, campos=("calificacion",), etapa="e3",
             campos_e3=("calificacion",)), "CCCECSCC"),
    "falta en el Excel: sin referencia de texto ni de clasificación": (
        resultado("falta_en_excel", pdf(7, descripcion="alfa uno")),
        item("falta_en_excel", "A1", pagina=7), "CSSSSSCC"),
    "D6 de E3: error en la descripción, lo demás coincide con el Excel": (
        resultado("difiere", pdf(7, descripcion="alfa uno"), excel(20, descripcion="otra"),
                  campos=("descripcion",)),
        item("difiere", "D6", fila=20, pagina=7, campos=("descripcion",), etapa="e3",
             campos_e3=("descripcion",)), "CECCCSCC"),
    "D6 de E4: paráfrasis, E3 acertó": (
        resultado("difiere", pdf(7, descripcion="alfa uno"), excel(20, descripcion="otra"),
                  campos=("descripcion",)),
        item("difiere", "D6", fila=20, pagina=7, campos=("descripcion",)), "CCCCCSCC"),
    "D5: el juez emparejó otra fila, no hay referencia de los campos": (
        resultado("difiere", pdf(7, descripcion="alfa uno"), excel(20, descripcion="otra"),
                  campos=("descripcion", "accion_correctiva", "calificacion")),
        item("difiere", "D5", fila=20, pagina=7,
             campos=("descripcion", "accion_correctiva", "calificacion")), "CSSSSSCC"),
    "A1 emparejado: la fila del Excel no es su contraparte": (
        resultado("difiere", pdf(7, descripcion="alfa uno"), excel(20, descripcion="otra"),
                  campos=("descripcion",)),
        item("difiere", "A1", fila=20, pagina=7, campos=("descripcion",)), "CSSSSSCC"),
    "D2: hallazgo de más, nada que medir en sus campos": (
        resultado("falta_en_excel", pdf(7, descripcion="alfa uno")),
        item("falta_en_excel", "D2", pagina=7, etapa="e3", campos_e3=("de_mas",)), "SSSSSSSE"),
    "C con descripción distinta: criterio por definir, sin referencia en ese campo": (
        resultado("difiere", pdf(7, descripcion="alfa uno"), excel(20, descripcion="otra"),
                  campos=("descripcion",)),
        item("difiere", "C1", fila=20, pagina=7, campos=("descripcion",)), "CSCCCSCC"),
    "A5: el Excel invierte la polaridad, E3 acertó": (
        resultado("difiere", pdf(7, descripcion=NO), excel(20, descripcion=SI),
                  campos=("descripcion",)),
        item("difiere", "A5", fila=20, pagina=7, campos=("descripcion",)), "CCCCCCCC"),
    "D7 de E3 que invierte la polaridad": (
        resultado("difiere", pdf(7, descripcion=NO), excel(20, descripcion=SI),
                  campos=("descripcion",)),
        item("difiere", "D7", fila=20, pagina=7, campos=("descripcion",), etapa="e3",
             campos_e3=("descripcion",)), "CECCCECC"),
    "D3: tupla mal asignada por E3": (
        resultado("falta_en_excel", pdf(7, descripcion="alfa uno")),
        item("falta_en_excel", "D3", pagina=7, etapa="e3", campos_e3=("tupla",)), "ESSSSSCC"),
    "D4: tupla de la Etapa 1": (
        resultado("falta_en_excel", pdf(7, descripcion="alfa uno")),
        item("falta_en_excel", "D4", pagina=7, etapa="e1", campos_e3=("tupla",)), "1SSSSSCC"),
    "clasificación distinta en un par correcto: error de E3": (
        resultado("coincide", pdf(7, descripcion="alfa uno", clasificacion="Otros"),
                  excel(20, descripcion="alfa uno", clasificacion="Verificación ECAP")),
        item("coincide", "OK", fila=20, pagina=7), "CCCCESCC"),
    "Excel con una clasificación que no es de la lista de la SEC: sin referencia": (
        resultado("coincide", pdf(7, descripcion="alfa uno", clasificacion="Verificación ECAP"),
                  excel(20, descripcion="alfa uno", clasificacion="NTSyCS: Cumplimiento NT")),
        item("coincide", "OK", fila=20, pagina=7), "CCCCSSCC"),
    "E3 con el rótulo del informe y no la categoría de la SEC: error": (
        resultado("coincide", pdf(7, descripcion="alfa uno", clasificacion="Documentación"),
                  excel(20, descripcion="alfa uno", clasificacion="Verificación DUF")),
        item("coincide", "OK", fila=20, pagina=7), "CCCCESCC"),
    "Excel sin columna de calificación: sin referencia": (
        resultado("coincide", pdf(7, descripcion="alfa uno"),
                  excel(20, descripcion="alfa uno", calificacion=None)),
        item("coincide", "OK", fila=20, pagina=7), "CCCSCSCC"),
}


@pytest.mark.parametrize("caso", list(CASOS_HALLAZGO), ids=list(CASOS_HALLAZGO))
def test_veredicto_por_campo_de_cada_hallazgo(caso: str) -> None:
    res, it, esperado = CASOS_HALLAZGO[caso]
    medida = medir([res], [it])
    (h,) = medida.hallazgos
    assert dict(h.veredictos) == veredictos(esperado)
    assert medida.omisiones == []


CASOS_OMISION = {
    "D1 con la tupla y la página en el mapa de E1: error de E3": ("C1", "REL 1", 10, E),
    "D1 sin página de contraparte: error de E3": ("C1", "REL 1", None, E),
    "D1 de una tupla que E1 no descubrió: error de E1": ("C9", "REL 9", None, E1),
    "D1 con la página fuera del rango del paño en E1: error de E1": ("C1", "REL 1", 40, E1),
}


@pytest.mark.parametrize("caso", list(CASOS_OMISION), ids=list(CASOS_OMISION))
def test_omision_de_e3_o_de_e1(caso: str) -> None:
    pano, rele, pagina, esperado = CASOS_OMISION[caso]
    medida = medir(
        [resultado("extra_en_excel", None, excel(30, pano=pano, rele=rele), pano=pano, rele=rele)],
        [item("extra_en_excel", "D1", fila=30, etapa="e3", campos_e3=("omision",), pano=pano,
              rele=rele, contraparte_pdf=pagina)])
    assert medida.hallazgos == []
    (o,) = medida.omisiones
    assert (o.veredicto, o.referencia) == (esperado, "D1")
    conteo = medida.conteo("omision")
    assert conteo == {"hallazgos_evaluados": 1, "correctos": 0, "errores": int(esperado == E),
                      "errores_e1": int(esperado == E1), "sin_referencia": 0}


@pytest.mark.parametrize("pano,rele,esperado", [
    ("C1", "REL 1", E),      # la contraparte está en el mapa y la pág. 7 en su sección
    ("C9", "REL 9", E1),     # la tupla correcta no está en el mapa de E1
    ("C3", "REL 3", E1),     # está, pero la pág. 7 no es de su sección
])
def test_tupla_mal_asignada_es_de_e1_segun_la_tupla_de_su_contraparte(
        pano: str, rele: str, esperado: Veredicto) -> None:
    d3 = item("falta_en_excel", "D3", pagina=7, etapa="e3", campos_e3=("tupla",), pano="C2",
              rele="REL 2")
    d3["origenes"][0]["contraparte_excel"] = {"referencia": 40, "cita": "x"}
    medida = medir([
        resultado("falta_en_excel", pdf(7, descripcion="alfa uno", pano="C2", rele="REL 2"),
                  pano="C2", rele="REL 2"),
        resultado("extra_en_excel", None, excel(40, pano=pano, rele=rele), pano=pano, rele=rele),
    ], [d3, {**item("extra_en_excel", "C1", fila=40, pano=pano, rele=rele), "id": "i2"}])
    assert medida.hallazgos[0].veredictos["tupla"] == esperado


def test_texto_identico_sin_item_es_correcto_y_lo_no_adjudicado_no_cuenta() -> None:
    identico = resultado("coincide", pdf(13, descripcion="zeta"), excel(26, descripcion="zeta"))
    distinto = resultado("coincide", pdf(14, descripcion="eta"), excel(27, descripcion="teta"))
    huerfano = resultado("falta_en_excel", pdf(15, descripcion="iota"))

    muestra = medir([identico, distinto], [item("coincide", "OK", fila=20, pagina=7)],
                    coincide="muestra")
    assert [h.referencia for h in muestra.hallazgos] == ["ok_texto_identico", "fuera_de_universo"]
    assert dict(muestra.hallazgos[0].veredictos) == veredictos("CCCCCSCC")
    assert dict(muestra.hallazgos[1].veredictos) == veredictos("SSSSSSSS")

    todos = medir([huerfano], [item("coincide", "OK", fila=20, pagina=7)])
    assert todos.hallazgos[0].referencia == "sin_adjudicar"
    assert dict(todos.hallazgos[0].veredictos) == veredictos("SSSSSSSS")


def test_conteos_por_campo_y_por_tupla() -> None:
    medida = medir([
        resultado("coincide", pdf(7, descripcion="alfa uno"), excel(20, descripcion="alfa uno")),
        resultado("falta_en_excel", pdf(8, descripcion="beta dos")),
        resultado("extra_en_excel", None, excel(30, pano="C2", rele="REL 2"), pano="C2",
                  rele="REL 2"),
    ], [
        item("coincide", "OK", fila=20, pagina=7),
        {**item("falta_en_excel", "D2", pagina=8, etapa="e3", campos_e3=("de_mas",)),
         "id": "i2", "lado_pdf": {"pagina": 8, "clasificaciones": ["Clase uno"], "citas": [
             {"texto": "beta dos", "fuente": "adjudicacion", "modelo": OPUS}]}},
        {**item("extra_en_excel", "D1", fila=30, etapa="e3", campos_e3=("omision",),
                pano="C2", rele="REL 2"), "id": "i3"},
    ])
    assert medida.conteo("tupla") == {"hallazgos_evaluados": 1, "correctos": 1, "errores": 0,
                                      "errores_e1": 0, "sin_referencia": 1}
    assert medida.conteo("de_mas") == {"hallazgos_evaluados": 2, "correctos": 1, "errores": 1,
                                       "errores_e1": 0, "sin_referencia": 0}
    # La omisión cuenta los hallazgos reales que E3 sacó y las que le faltaron.
    assert medida.conteo("omision") == {"hallazgos_evaluados": 2, "correctos": 1, "errores": 1,
                                        "errores_e1": 0, "sin_referencia": 1}
    assert medida.por_tupla() == {"tuplas": 2, "tuplas_con_omision": 1, "tuplas_con_de_mas": 1,
                                  "hallazgos_e3": 2, "omisiones": 1, "de_mas": 1,
                                  "hallazgos_sin_referencia": 0,
                                  "filas_excel_sin_referencia": 0}


# ------------------------------------------------------------ mapa de la Etapa 1


def test_la_etapa1_explica_un_error_si_la_tupla_o_la_pagina_no_estan_en_su_mapa() -> None:
    mapa = MapaE1.de([
        seccion("BT1/ET1", 10, 12, ("REL A", [])),
        seccion("HT1/CT1", 30, 35, ("REL B", ["CT1A"]), ("REL A", [])),
    ])
    assert not mapa.explica("ET1", "REL A")
    assert not mapa.explica("et-1", "rel-a")            # misma clave que la Etapa 3
    assert mapa.explica("ET9", "REL A")                 # paño fuera del mapa
    assert mapa.explica("ET1", "REL Z")                 # relé fuera del mapa
    assert not mapa.explica("CT1A", "REL B")            # sub-paño con el relé que lo declaró
    assert mapa.explica("CT1A", "REL A")                # sub-paño de otro relé
    assert not mapa.explica("BT1", "REL A", 11)
    assert mapa.explica("BT1", "REL A", 13)             # página fuera del rango del paño
    assert not mapa.explica("CT1A", "REL B", 32)
    assert mapa.explica("CT1A", "REL B", 12)


# ------------------------------------------------------------ control de copia


def h(pano: str = "C1", rele: str = "REL 1", *, fuente: str = "pdf", descripcion: str = "alfa",
      accion: str | None = "accion", calificacion: str | None = "Menor",
      clasificacion: str = "Otros", transversal: bool = False) -> Hallazgo:
    return Hallazgo.model_validate({
        "pano": pano, "rele": rele, "clasificacion": clasificacion, "descripcion": descripcion,
        "accion_correctiva": accion, "calificacion": calificacion, "es_transversal": transversal,
        "evidencia": {"fuente": fuente, "pagina_pdf": 7 if fuente == "pdf" else None,
                      "fila_excel": None if fuente == "pdf" else 20, "texto_crudo": "x"}})


def x(*args: Any, **kw: Any) -> Hallazgo:
    return h(*args, fuente="excel", **kw)


def test_texto_copia_unifica_solo_la_tipografia() -> None:
    assert texto_copia("“Phase IOC” – b \n c") == '"Phase IOC" - b c'
    assert texto_copia("‘a’ — b") == "'a' - b"
    assert texto_copia(None) is None
    # Nada que cambie el contenido: negación, signo, cifras, mayúsculas.
    assert texto_copia("No cumple") != texto_copia("Cumple")
    assert texto_copia("-5 [ms]") != texto_copia("5 [ms]")
    assert texto_copia("0,5") != texto_copia("0.5")
    assert texto_copia("SEL") != texto_copia("sel")


def test_copia_con_comillas_y_guiones_tipograficos_es_correcta() -> None:
    medida = medir_copia(
        [h(descripcion='La señal "IRIG-B" falla', accion="Revisar - ya")],
        [x(descripcion="La señal “IRIG-B” falla", accion="Revisar – ya")], MAPA)
    assert [dict(m.veredictos) for m in medida.hallazgos] == [veredictos("CCCCCCC", CAMPOS_COPIA)]
    assert medida.hallazgos[0].referencia == "copia_misma_tupla"
    assert medida.omisiones == []


def test_copia_que_pierde_un_guion_es_error_en_la_descripcion() -> None:
    medida = medir_copia([h(descripcion="1.Manual2.Automático", calificacion="Relevante")],
                         [x(descripcion="1.Manual-2.Automático")], MAPA)
    (m,) = medida.hallazgos
    # El par se presume por la tupla y el orden: los demás campos no se juzgan.
    assert (m.referencia, dict(m.veredictos)) == (
        "copia_orden", veredictos("CESSSCC", CAMPOS_COPIA))


def test_copia_compara_accion_calificacion_y_clasificacion_del_par() -> None:
    medida = medir_copia([
        h(descripcion="uno", accion="otra accion"),
        h(descripcion="dos", calificacion="Crítico"),
        h(descripcion="tres", clasificacion="Coord. de Protecciones"),
        h(descripcion="cuatro"),
        h(descripcion="cinco"),
    ], [
        x(descripcion="uno"),
        x(descripcion="dos"),
        x(descripcion="tres", clasificacion="Ver. Coord. de Protecciones"),
        x(descripcion="cuatro", calificacion=None),
        x(descripcion="cinco", clasificacion="Ver. Tiempo Máx. Actuación"),   # no es de la SEC
    ], MAPA)
    assert [dict(m.veredictos) for m in medida.hallazgos] == [veredictos(v, CAMPOS_COPIA) for v in (
        "CCECCCC", "CCCECCC", "CCCCCCC", "CCCSCCC", "CCCCSCC")]


def test_copia_en_otra_tupla_es_error_de_tupla_y_de_e1_si_e1_no_la_tiene() -> None:
    def tupla(pano: str, rele: str) -> tuple[str, dict[str, Veredicto]]:
        (m,) = medir_copia([h("C1", "REL 1", descripcion="uno")],     # pág. 7
                           [x(pano, rele, descripcion="uno")], MAPA).hallazgos
        return m.referencia, dict(m.veredictos)

    assert tupla("C2", "REL 2") == ("copia_otra_tupla", veredictos("ECCCCCC", CAMPOS_COPIA))
    assert tupla("C9", "REL 9") == ("copia_otra_tupla", veredictos("1CCCCCC", CAMPOS_COPIA))
    # C3 está en el mapa, pero la pág. 7 no es de su sección: E1 se la dio a otra.
    assert tupla("C3", "REL 3") == ("copia_otra_tupla", veredictos("1CCCCCC", CAMPOS_COPIA))


def test_copia_de_mas_omision_y_filas_transversales() -> None:
    medida = medir_copia([h(descripcion="uno"), h(descripcion="inventado")], [
        x(descripcion="uno"),
        x("C2", "REL 2", descripcion="omitido"),
        x("C9", "REL 9", descripcion="fuera de E1"),
        x("C1", "-", descripcion="análisis transversal"),          # relé sin alfanuméricos
        x("C1", "Análisis", descripcion="otra", transversal=True),
        # Patrón del catálogo de hoy, aunque la E2 de la ronda no lo marcara.
        x("C1", "Sensibilidad del Sistema de protecciones.", descripcion="otra más"),
    ], MAPA, patrones_transversales=("sensibilidad del sistema",))
    assert [dict(m.veredictos) for m in medida.hallazgos] == [
        veredictos("CCCCCCC", CAMPOS_COPIA), veredictos("SSSSSSE", CAMPOS_COPIA)]
    assert [(o.tupla, o.veredicto, o.referencia) for o in medida.omisiones] == [
        (("c2", "rel2"), E, "copia_sin_pareja"), (("c9", "rel9"), E1, "copia_sin_pareja")]
    assert medida.por_tupla() == {"tuplas": 3, "tuplas_con_omision": 2, "tuplas_con_de_mas": 1,
                                  "hallazgos_e3": 2, "omisiones": 2, "de_mas": 1,
                                  "hallazgos_sin_referencia": 0,
                                  "filas_excel_sin_referencia": 0}


def test_copia_empareja_duplicados_y_desempata_por_la_accion() -> None:
    medida = medir_copia(
        [h(descripcion="igual", accion="b"), h(descripcion="igual", accion="a"),
         h(descripcion="doble"), h(descripcion="doble")],
        [x(descripcion="igual", accion="a"), x(descripcion="igual", accion="b"),
         x(descripcion="doble"), x(descripcion="doble")], MAPA)
    assert [dict(m.veredictos) for m in medida.hallazgos] == [
        veredictos("CCCCCCC", CAMPOS_COPIA)] * 4
    assert medida.omisiones == []


# ------------------------------------------------------------ runs y filas


RUN = "2026-10-17_01-00-00_claude-opus-5-5"


def _run_adjudicado(med: Path, res: list[dict[str, Any]] | None = None,
                    items: list[dict[str, Any]] | None = None) -> tuple[Path, GtAplicable]:
    """Un run de B2 que es fuente del GT de su informe (sha256 de sus archivos).
    Por defecto, un «difiere» que el GT atribuye a E3 en la descripción (D6)."""
    res = res or [resultado("difiere", pdf(7, descripcion="alfa uno"),
                            excel(20, descripcion="otra"), campos=("descripcion",))]
    run = med / "b2" / "runs" / RUN
    run.mkdir(parents=True)
    rep = reporte(res, OPUS)
    (run / "reporte_final.json").write_text(json.dumps(rep), "utf-8")
    (run / "etapa3_pdf_hallazgos.json").write_text(
        json.dumps([r["hallazgo_pdf"] for r in res if r["hallazgo_pdf"]]), "utf-8")
    (run / "etapa1_panos.json").write_text(
        json.dumps([p.model_dump() for p in MAPA.panos]), "utf-8")
    gt = gt_de(items or [item("difiere", "D6", fila=20, pagina=7, campos=("descripcion",),
                              etapa="e3", campos_e3=("descripcion",))])
    (run / "input_informe_original.hash").write_text(gt.sha256_informe_original, "utf-8")
    (run / "input_excel.hash").write_text(gt.sha256_excel, "utf-8")
    datos = gt.model_dump(mode="json")
    datos["fuentes"][0].update(
        run_id=RUN, carpeta=f"b2/runs/{RUN}", sha256_reporte=_sha256(run / "reporte_final.json"),
        sha256_e3=_sha256(run / "etapa3_pdf_hallazgos.json"))
    for it in datos["items"]:
        for origen in it["origenes"]:
            origen["run_id"] = RUN
    gt = GtInforme.model_validate(datos)
    ruta = med / "gt" / "comparador" / f"{gt.informe}.json"
    ruta.parent.mkdir(parents=True)
    ruta.write_text(serializar(gt), "utf-8")
    return run, GtAplicable(ruta, _sha256(ruta), gt)


def _sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _run_copia(med: Path, run_id: str, *, con_e2: bool = True) -> Path:
    run = med / "b0" / "runs" / run_id
    run.mkdir(parents=True)
    (run / "etapa3_pdf_hallazgos.json").write_text(
        json.dumps([h(descripcion="uno").model_dump(mode="json")]), "utf-8")
    if con_e2:
        (run / "etapa2_excel_normalizado.json").write_text(json.dumps(
            [x(descripcion="uno").model_dump(mode="json"),
             x(descripcion="dos").model_dump(mode="json")]), "utf-8")
    (run / "etapa1_panos.json").write_text(
        json.dumps([p.model_dump() for p in MAPA.panos]), "utf-8")
    return run


def test_medir_casos_toma_las_fuentes_del_gt_y_los_informes_con_copia(tmp_path: Path) -> None:
    med = tmp_path / "mediciones"
    run, gt = _run_adjudicado(med)
    copia = _run_copia(med, "2026-10-16_00-00-00_claude-haiku-5-5")
    sin_e2 = _run_copia(med, "2026-10-16_00-00-01_claude-haiku-5-5", con_e2=False)
    otro = _run_copia(med, "2026-10-16_00-00-02_claude-haiku-5-5")
    casos = [
        Caso("B2", OPUS, "Equis", run),
        Caso("B0", "claude-haiku-5-5", "Beta", copia),
        Caso("B0", "claude-haiku-5-5", "Eta", sin_e2),     # sin etapa2: no se mide
        Caso("B0", "claude-haiku-5-5", "Zeta", otro),        # su Excel no copia el PDF
    ]
    mediciones = medir_casos(casos, [gt], mediciones=med)
    assert [(m.fuente, m.caso.informe) for m in mediciones] == [
        ("b2_adjudicado", "Equis"), (FUENTE_COPIA, "Beta")]
    assert mediciones[0].medida.conteo("descripcion")["errores"] == 1
    assert mediciones[1].medida.conteo("omision")["errores"] == 1

    por_campo, por_tupla = filas(mediciones)
    assert [list(f) for f in por_campo] == [COLUMNAS_POR_CAMPO] * (len(CAMPOS) + len(CAMPOS_COPIA))
    assert [list(f) for f in por_tupla] == [COLUMNAS_POR_TUPLA] * 2
    assert por_campo[1] == {
        "fuente": "b2_adjudicado", "ronda": "B2", "modelo": OPUS, "informe": "Equis",
        "campo": "descripcion", "hallazgos_evaluados": 1, "correctos": 0, "errores": 1,
        "errores_e1": 0, "sin_referencia": 0}
    # Sin texto de los informes: solo identificadores y números.
    for fila in por_campo + por_tupla:
        assert all(isinstance(v, int) or v in {
            "b2_adjudicado", FUENTE_COPIA, "B2", "B0", OPUS, "claude-haiku-5-5", "Equis",
            "Beta", *CAMPOS} for v in fila.values()), fila


def test_un_run_fuente_que_cambio_desde_el_gt_falla(tmp_path: Path) -> None:
    med = tmp_path / "mediciones"
    run, gt = _run_adjudicado(med)
    ruta = run / "reporte_final.json"
    ruta.write_text(ruta.read_text("utf-8") + "\n", "utf-8")
    with pytest.raises(ValueError, match="cambió"):
        medir_casos([Caso("B2", OPUS, "Equis", run)], [gt], mediciones=med)


def test_un_run_que_no_es_fuente_del_gt_no_se_mide_con_la_adjudicacion(tmp_path: Path) -> None:
    med = tmp_path / "mediciones"
    run, gt = _run_adjudicado(med)
    otro = med / "b1" / "runs" / "2026-10-16_23-00-00_claude-opus-5-5"
    otro.parent.mkdir(parents=True)
    run.rename(otro)
    assert medir_casos([Caso("B1", OPUS, "Equis", otro)], [gt], mediciones=med) == []


def test_generar_escribe_los_csv_de_la_extraccion(tmp_path: Path) -> None:
    from comparador.metricas_lote import COLUMNAS, generar
    from tests.test_metricas_lote import _leer_csv, _mediciones, _precios

    salida = tmp_path / "salida"
    res = generar(_mediciones(tmp_path), _precios(tmp_path), salida)
    for nombre, columnas in (("extraccion_por_campo.csv", COLUMNAS_POR_CAMPO),
                             ("extraccion_por_tupla.csv", COLUMNAS_POR_TUPLA)):
        assert COLUMNAS[nombre] == columnas
        assert res.tablas[nombre] == []          # ni fuentes del GT ni Beta/Eta
        assert (salida / nombre).read_text("utf-8").splitlines() == [",".join(columnas)]
        assert _leer_csv(salida / nombre) == []


# ------------------------------------------------------------ rondas posteriores al GT (E10)


RUN_B3 = "2026-10-25_10-00-00_claude-opus-5-5"


def _run_posterior(med: Path, gt: GtAplicable, resultados: list[dict[str, Any]], *,
                   ronda: str = "b3", run_id: str = RUN_B3, hashes: bool = True) -> Path:
    """Un run de una ronda posterior al GT (B3), del mismo informe y Excel (sha256),
    que no es fuente del GT."""
    run = med / ronda / "runs" / run_id
    run.mkdir(parents=True)
    rep = reporte(resultados, OPUS)
    (run / "reporte_final.json").write_text(json.dumps(rep), "utf-8")
    e3 = [r["hallazgo_pdf"] for r in resultados if r.get("hallazgo_pdf")]
    (run / "etapa3_pdf_hallazgos.json").write_text(json.dumps(e3), "utf-8")
    (run / "etapa1_panos.json").write_text(
        json.dumps([p.model_dump() for p in MAPA.panos]), "utf-8")
    if hashes:
        (run / "input_informe_original.hash").write_text(gt.gt.sha256_informe_original, "utf-8")
        (run / "input_excel.hash").write_text(gt.gt.sha256_excel, "utf-8")
    return run


# El mismo «difiere» que adjudicó el GT (D6 de E3) y un hallazgo que el GT no conoce.
RESULTADOS_B3 = [
    resultado("difiere", pdf(7, descripcion="alfa uno"), excel(20, descripcion="otra"),
              campos=("descripcion",)),
    resultado("falta_en_excel", pdf(9, descripcion="gama nueva")),
]


def test_un_run_de_una_ronda_posterior_se_mide_contra_el_gt(tmp_path: Path) -> None:
    from comparador.metricas_extraccion import FUENTE_CONTRA_GT

    med = tmp_path / "mediciones"
    fuente, gt = _run_adjudicado(med)
    b3 = _run_posterior(med, gt, RESULTADOS_B3)

    mediciones = medir_casos([Caso("B2", OPUS, "Equis", fuente),
                              Caso("B3", OPUS, "Equis", b3)], [gt], mediciones=med)

    assert [(m.fuente, m.caso.ronda) for m in mediciones] == [
        ("b2_adjudicado", "B2"), (FUENTE_CONTRA_GT, "B3")]
    medida = mediciones[1].medida
    # Lo que calza con el ítem del GT recibe veredicto como en B2 (error de E3 en
    # la descripción); el hallazgo que el GT no conoce queda sin referencia.
    assert [h.referencia for h in medida.hallazgos] == ["D6", "sin_adjudicar"]
    assert dict(medida.hallazgos[0].veredictos) == veredictos("CECCCSCC")
    assert dict(medida.hallazgos[1].veredictos) == veredictos("SSSSSSSS")
    assert medida.conteo("descripcion") == {"hallazgos_evaluados": 1, "correctos": 0,
                                            "errores": 1, "errores_e1": 0, "sin_referencia": 1}
    assert medida.conteo("tupla")["sin_referencia"] == 1

    por_campo, por_tupla = filas(mediciones)
    assert [list(f) for f in por_tupla] == [COLUMNAS_POR_TUPLA] * 2
    assert COLUMNAS_POR_TUPLA[-2] == "hallazgos_sin_referencia"
    assert [f["hallazgos_sin_referencia"] for f in por_tupla] == [0, 1]
    assert {f["fuente"] for f in por_campo} == {"b2_adjudicado", FUENTE_CONTRA_GT}


def test_un_run_posterior_de_otro_informe_o_sin_hashes_no_se_mide(tmp_path: Path) -> None:
    med = tmp_path / "mediciones"
    _, gt = _run_adjudicado(med)
    sin_hashes = _run_posterior(med, gt, RESULTADOS_B3, hashes=False)
    otro = _run_posterior(med, gt, RESULTADOS_B3, run_id="2026-10-25_11-00-00_claude-opus-5-5")
    (otro / "input_excel.hash").write_text("f" * 64, "utf-8")

    assert medir_casos([Caso("B3", OPUS, "Equis", sin_hashes),
                        Caso("B3", OPUS, "Equis", otro)], [gt], mediciones=med) == []


def test_un_run_de_la_ronda_del_gt_que_no_es_fuente_no_se_mide(tmp_path: Path) -> None:
    """B2 con Haiku: mismo informe y Excel, pero de la ronda del GT (no posterior):
    las filas de B0-B2 de los CSV no cambian."""
    med = tmp_path / "mediciones"
    _, gt = _run_adjudicado(med)
    haiku = _run_posterior(med, gt, RESULTADOS_B3, ronda="b2",
                           run_id="2026-10-17_02-00-00_claude-haiku-5-5")
    assert medir_casos([Caso("B2", "claude-haiku-5-5", "Equis", haiku)], [gt],
                       mediciones=med) == []


def test_una_ronda_sin_numero_con_gt_aplicable_falla(tmp_path: Path) -> None:
    med = tmp_path / "mediciones"
    _, gt = _run_adjudicado(med)
    run = _run_posterior(med, gt, RESULTADOS_B3, ronda="prueba")
    with pytest.raises(ValueError, match="Prueba"):
        medir_casos([Caso("Prueba", OPUS, "Equis", run)], [gt], mediciones=med)


def _con_fuente_b3(med: Path, gt: GtAplicable, b3: Path) -> GtAplicable:
    """El GT con B3 como fuente de una ronda posterior: adjudica el «falta» que el
    GT de B2 no conocía (C1, idx 1 del run de B3)."""
    datos = gt.gt.model_dump(mode="json")
    universo = {**datos["fuentes"][0]["universo"], "regla": "complemento", "resultados": 2,
                "items": 1, "adjudicados_antes": 1}
    datos["fuentes"].append({
        **datos["fuentes"][0], "ronda": "B3", "run_id": b3.name, "carpeta": f"b3/runs/{b3.name}",
        "adjudicacion": "b3.json",
        "sha256_reporte": _sha256(b3 / "reporte_final.json"),
        "sha256_e3": _sha256(b3 / "etapa3_pdf_hallazgos.json"), "complementa": ["B2"],
        "universo": universo})
    falta = item("falta_en_excel", "C1", pagina=9)
    falta["lado_pdf"]["citas"][0]["texto"] = "gama nueva"
    falta.update(id="i2", origenes=[{**falta["origenes"][0], "ronda": "B3", "run_id": b3.name,
                                     "idx": 1}])
    datos["items"].append(falta)
    nuevo = GtInforme.model_validate(datos)
    ruta = gt.ruta
    ruta.write_text(serializar(nuevo), "utf-8")
    return GtAplicable(ruta, _sha256(ruta), nuevo)


def test_una_fuente_de_una_ronda_posterior_se_mide_contra_el_gt(tmp_path: Path) -> None:
    """B3 como fuente del GT (adjudica lo que el GT de B2 no adjudicaba) no es una
    fuente base: se sigue midiendo contra el GT, y su ítem propio se compara con
    su propio reporte. Otra ronda posterior (B3s) también se sigue midiendo: la
    ronda de referencia es la de las fuentes base, no la de B3."""
    from comparador.metricas_extraccion import FUENTE_CONTRA_GT

    med = tmp_path / "mediciones"
    fuente, gt = _run_adjudicado(med)
    b3 = _run_posterior(med, gt, RESULTADOS_B3)
    gt = _con_fuente_b3(med, gt, b3)
    b3s = _run_posterior(med, gt, RESULTADOS_B3, ronda="b3s",
                         run_id="2026-10-25_11-00-00_claude-opus-5-5")

    mediciones = medir_casos([Caso("B2", OPUS, "Equis", fuente), Caso("B3", OPUS, "Equis", b3),
                              Caso("B3s", OPUS, "Equis", b3s)], [gt], mediciones=med)

    assert [(m.fuente, m.caso.ronda) for m in mediciones] == [
        ("b2_adjudicado", "B2"), (FUENTE_CONTRA_GT, "B3"), (FUENTE_CONTRA_GT, "B3s")]
    for m in mediciones[1:]:
        assert [h.referencia for h in m.medida.hallazgos] == ["D6", "C1"]
        assert dict(m.medida.hallazgos[1].veredictos)["tupla"] == Veredicto.CORRECTO


def test_una_repeticion_de_e4_fuente_del_gt_se_lee_de_su_carpeta(tmp_path: Path) -> None:
    """Una repetición de E4 del run fuente (replay_e4/AG1/<el mismo run_id>) como
    fuente del GT: lo que adjudica se compara con el reporte de la repetición,
    no con el de su origen, que tiene el mismo run_id."""
    from comparador.metricas_extraccion import FUENTE_CONTRA_GT

    med = tmp_path / "mediciones"
    fuente, gt = _run_adjudicado(med)
    repeticion = med / "replay_e4" / "AG1" / RUN
    repeticion.mkdir(parents=True)
    (repeticion / "reporte_final.json").write_text(
        json.dumps(reporte(RESULTADOS_B3, OPUS)), "utf-8")
    datos = gt.gt.model_dump(mode="json")
    datos["fuentes"].append({
        **datos["fuentes"][0], "ronda": "AG1", "carpeta": f"replay_e4/AG1/{RUN}",
        "ronda_origen": "B2", "adjudicacion": "ag1.json", "complementa": ["B2"],
        "sha256_reporte": _sha256(repeticion / "reporte_final.json"),
        "universo": {**datos["fuentes"][0]["universo"], "regla": "complemento",
                     "resultados": 2, "items": 1, "adjudicados_antes": 1}})
    falta = item("falta_en_excel", "C1", pagina=9)
    falta["lado_pdf"]["citas"][0]["texto"] = "gama nueva"
    falta.update(id="i2", origenes=[{**falta["origenes"][0], "ronda": "AG1", "run_id": RUN,
                                     "idx": 1}])
    datos["items"].append(falta)
    nuevo = GtInforme.model_validate(datos)
    gt.ruta.write_text(serializar(nuevo), "utf-8")
    gt = GtAplicable(gt.ruta, _sha256(gt.ruta), nuevo)
    b3 = _run_posterior(med, gt, RESULTADOS_B3)

    mediciones = medir_casos([Caso("B2", OPUS, "Equis", fuente), Caso("B3", OPUS, "Equis", b3)],
                             [gt], mediciones=med)

    assert [(m.fuente, m.caso.ronda) for m in mediciones] == [
        ("b2_adjudicado", "B2"), (FUENTE_CONTRA_GT, "B3")]
    assert [h.referencia for h in mediciones[1].medida.hallazgos] == ["D6", "C1"]
    assert dict(mediciones[1].medida.hallazgos[1].veredictos)["tupla"] == Veredicto.CORRECTO


# ---------------------------------------------- lo que hereda una ronda posterior


def _contra_gt(tmp_path: Path, fuente: list[dict[str, Any]], items: list[dict[str, Any]],
               b3: list[dict[str, Any]]) -> Medida:
    med = tmp_path / "mediciones"
    origen, gt = _run_adjudicado(med, fuente, items)
    run = _run_posterior(med, gt, b3)
    (medicion,) = [m for m in medir_casos([Caso("B2", OPUS, "Equis", origen),
                                           Caso("B3", OPUS, "Equis", run)], [gt],
                                          mediciones=med) if m.caso.ronda == "B3"]
    return medicion.medida


def _d6_e3(descripcion: str, **kw: Any) -> list[dict[str, Any]]:
    return [resultado("difiere", pdf(7, descripcion=descripcion, **kw),
                      excel(20, descripcion="otra"), campos=("descripcion",))]


D6_E3 = [item("difiere", "D6", fila=20, pagina=7, campos=("descripcion",), etapa="e3",
              campos_e3=("descripcion",))]


@pytest.mark.parametrize(("b3", "esperado"), [
    (_d6_e3("alfa uno"), "CECCCSCC"),                      # E3 extrajo lo mismo que en B2
    (_d6_e3("ALFA  uno"), "CECCCSCC"),                     # solo mayúsculas y espacios
    (_d6_e3("alfa uno, solo lo de este relé"), "CSCCCSCC"),  # otra descripción, misma cita
    # La cita solo en el texto crudo: calza por clave, pero E3 extrajo otra descripción.
    (_d6_e3("solo lo de este relé", crudo="alfa uno | accion alfa"), "CSCCCSCC"),
])
def test_el_error_que_el_gt_atribuye_a_e3_solo_vale_si_e3_extrajo_lo_mismo(
        tmp_path: Path, b3: list[dict[str, Any]], esperado: str) -> None:
    """Contra el GT, el veredicto de un campo que el GT atribuye a E3 vale si el
    valor de E3 es el que se adjudicó en el run fuente; si no, sin referencia."""
    medida = _contra_gt(tmp_path, _d6_e3("alfa uno"), D6_E3, b3)
    (h,) = medida.hallazgos
    assert (h.referencia, dict(h.veredictos)) == ("D6", veredictos(esperado))


FUENTE_HEREDA = [
    resultado("difiere", pdf(7, descripcion="alfa uno", calificacion="Relevante"),
              excel(20, descripcion="alfa uno"), campos=("calificacion",)),
    resultado("difiere", pdf(8, descripcion="beta dos"), excel(21, descripcion="beta 2"),
              campos=("descripcion",)),
]
_D6_E4 = item("difiere", "D6", fila=21, pagina=8, campos=("descripcion",))
ITEMS_HEREDA = [
    item("difiere", "A4", fila=20, pagina=7, campos=("calificacion",)),
    {**_D6_E4, "id": "i2", "origenes": [{**_D6_E4["origenes"][0], "idx": 1}],
     "lado_pdf": {"pagina": 8, "clasificaciones": ["Otros"], "citas": [
         {"texto": "beta dos", "fuente": "adjudicacion", "modelo": OPUS}]}},
]


def test_el_correcto_heredado_de_un_a_o_una_d6_de_e4_solo_vale_si_e3_extrajo_lo_mismo(
        tmp_path: Path) -> None:
    igual = _contra_gt(tmp_path / "igual", FUENTE_HEREDA, ITEMS_HEREDA, FUENTE_HEREDA)
    assert [dict(h.veredictos) for h in igual.hallazgos] == [
        veredictos("CCCCCSCC"), veredictos("CCCCCSCC")]

    distinto = [
        resultado("difiere", pdf(7, descripcion="alfa uno", calificacion="Crítico"),
                  excel(20, descripcion="alfa uno"), campos=("calificacion",)),
        resultado("difiere", pdf(8, descripcion="beta dos y más"),
                  excel(21, descripcion="beta 2"), campos=("descripcion",)),
    ]
    medida = _contra_gt(tmp_path / "distinto", FUENTE_HEREDA, ITEMS_HEREDA, distinto)
    # A4: la calificación de E3 ya no es la que se adjudicó correcta; D6 de E4:
    # la descripción tampoco. Los campos que no difieren siguen correctos.
    assert [dict(h.veredictos) for h in medida.hallazgos] == [
        veredictos("CCCSCSCC"), veredictos("CSCCCSCC")]


def test_sin_el_run_fuente_tal_como_se_adjudico_no_se_mide_contra_el_gt(
        tmp_path: Path) -> None:
    med = tmp_path / "mediciones"
    origen, gt = _run_adjudicado(med)
    run = _run_posterior(med, gt, RESULTADOS_B3)
    ruta = origen / "reporte_final.json"
    ruta.write_text(ruta.read_text("utf-8") + "\n", "utf-8")
    with pytest.raises(ValueError, match="fuente"):
        medir_casos([Caso("B3", OPUS, "Equis", run)], [gt], mediciones=med)
    ruta.unlink()
    with pytest.raises(ValueError, match="fuente"):
        medir_casos([Caso("B3", OPUS, "Equis", run)], [gt], mediciones=med)


# ---------------------------------------------- filas del Excel sin referencia


def test_una_fila_extra_en_excel_sin_adjudicar_es_una_omision_sin_referencia() -> None:
    """Una fila «extra en Excel» sin ítem del GT: no se sabe si E3 omitió su
    hallazgo. No es un hallazgo de E3, pero cuenta sin referencia en la omisión
    y aparte en ``filas_excel_sin_referencia``."""
    medida = medir([
        resultado("coincide", pdf(7, descripcion="alfa uno"), excel(20, descripcion="alfa uno")),
        resultado("extra_en_excel", None, excel(31, pano="C2", rele="REL 2"), pano="C2",
                  rele="REL 2"),
        resultado("extra_en_excel", None, excel(30)),     # adjudicada (C1): tiene referencia
    ], [item("coincide", "OK", fila=20, pagina=7),
        {**item("extra_en_excel", "C1", fila=30), "id": "i2"}])
    assert medida.conteo("omision") == {"hallazgos_evaluados": 1, "correctos": 1, "errores": 0,
                                        "errores_e1": 0, "sin_referencia": 1}
    tupla = medida.por_tupla()
    assert (tupla["hallazgos_sin_referencia"], tupla["filas_excel_sin_referencia"]) == (0, 1)
    assert COLUMNAS_POR_TUPLA[-1] == "filas_excel_sin_referencia"
    copia = medir_copia([h(descripcion="uno")], [x(descripcion="uno")], MAPA)
    assert copia.por_tupla()["filas_excel_sin_referencia"] == 0
