"""Tests de la construcción y el formato del GT del comparador (sin API, datos sintéticos).

Arman en tmp_path una carpeta mediciones/ mínima con la forma de B2: dos runs
(Sonnet y Opus) del mismo informe, cada uno con su reporte, su Etapa 3 y los
sha256 de los insumos, y la adjudicación de cada uno. Textos inventados.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from comparador.adjudicacion import NivelValidacion, item_desde_dict
from comparador.evaluar_comparador import evaluar_run
from comparador.gt_comparador import (
    VERSION_GT,
    CampoExtraccion,
    ConflictoGtError,
    GtError,
    GtInforme,
    _construir,
    cargar_gt,
    construir_gt,
    preguntas_de,
    validar_gt,
)
from tests.test_adjudicacion import excel, item, pdf, resultado

SONNET, OPUS = "claude-sonnet-5-5", "claude-opus-5-5"
INFORME = "S-E Equis (Auditora Reliable Energy)"
RUN = {SONNET: "2026-10-17_01-00-00_claude-sonnet-5-5", OPUS: "2026-10-17_02-00-00_claude-opus-5-5"}


def reporte(resultados: list[dict[str, Any]], modelo: str) -> dict[str, Any]:
    return {
        "empresa_auditora": "ReliableEnergy", "coordinado": "c", "subestacion": "s",
        "informe_id": "i", "fecha_auditoria": None, "fecha_procesamiento": "2026-10-17T00:00:00",
        "modelo_extraccion": modelo, "modelo_embeddings": "e",
        "resumen": {"total": len(resultados), "coinciden": 0, "difieren": 0, "faltan_en_excel": 0,
                    "extra_en_excel": 0, "requieren_revision": 0},
        "resultados": resultados,
    }


def escribir_run(med: Path, modelo: str, resultados: list[dict[str, Any]],
                 items: list[dict[str, Any]], *, excel_hash: str = "e" * 64,
                 cabecera: dict[str, Any] | None = None, ronda: str = "B2",
                 run_id: str | None = None) -> Path:
    run_id = run_id or RUN[modelo]
    run = med / ronda.lower() / "runs" / run_id
    run.mkdir(parents=True, exist_ok=True)
    (run / "reporte_final.json").write_text(json.dumps(reporte(resultados, modelo)), "utf-8")
    e3 = [r["hallazgo_pdf"] for r in resultados if r["hallazgo_pdf"]]
    (run / "etapa3_pdf_hallazgos.json").write_text(json.dumps(e3), "utf-8")
    (run / "input_informe_original.hash").write_text("a" * 64 + "\n", "utf-8")
    (run / "input_excel.hash").write_text(excel_hash + "\n", "utf-8")
    adj = med / "adjudicacion"
    adj.mkdir(parents=True, exist_ok=True)
    corto = "sonnet" if modelo == SONNET else "opus"
    (adj / f"{ronda.lower()}_{corto}_Equis.json").write_text(json.dumps({
        "informe": INFORME, "ronda": ronda, "modelo": modelo, "run_id": run_id,
        "verificado_por_segundo_agente": True, "items": items, **(cabecera or {}),
    }), "utf-8")
    return run


def sin_verificar(datos: dict[str, Any]) -> dict[str, Any]:
    return {**datos, "verificacion": None}


P_A, P_B, P_C = pdf(7, descripcion="alfa uno"), pdf(8, descripcion="beta dos"), pdf(9,
                                                                                descripcion="gama")


def caso_base(med: Path, *, clase_opus_0: str = "A4") -> None:
    """Sonnet: difiere A4, falta C1 (pregunta 4.1), extra D1, coincide OK sin
    verificar, transversal. Opus: el mismo difiere y el mismo extra; el hallazgo
    de la falta lo empareja con otra fila (coincide); el mismo coincide, verificado."""
    escribir_run(med, SONNET, [
        resultado("difiere", P_A, excel(20), campos=("calificacion",)),
        resultado("falta_en_excel", P_B),
        resultado("extra_en_excel", None, excel(21)),
        resultado("coincide", P_C, excel(22)),
        resultado("transversal", None, excel(23)),
    ], [
        item(0, "difiere", cita_pdf="alfa uno", subclase="A4"),
        item(1, "falta_en_excel", pagina=8, fila=31, cita_pdf="beta dos", subclase="C1",
             explicacion="Depende de la pregunta 4.1."),
        item(2, "extra_en_excel", pagina=8, fila=21, subclase="D1"),
        sin_verificar(item(3, "coincide", pagina=9, fila=22, cita_pdf="gama")),
    ])
    escribir_run(med, OPUS, [
        resultado("difiere", {**P_A, "clasificacion": "Otra"}, excel(20), campos=("calificacion",)),
        resultado("coincide", P_B, excel(24)),
        resultado("extra_en_excel", None, excel(21)),
        resultado("coincide", P_C, excel(22)),
    ], [
        item(0, "difiere", cita_pdf="ALFA UNO", subclase=clase_opus_0),
        item(1, "coincide", pagina=8, fila=24, cita_pdf="beta dos"),
        item(2, "extra_en_excel", pagina=None, fila=21, subclase="D1"),
        item(3, "coincide", pagina=9, fila=22, cita_pdf="gama"),
    ])


def adjudicaciones(med: Path) -> list[Path]:
    return sorted((med / "adjudicacion").glob("*.json"))


# ------------------------------------------------------------ construcción


def test_construir_une_las_fuentes_y_fusiona_la_misma_clave(tmp_path: Path) -> None:
    caso_base(tmp_path)
    gt = construir_gt(tmp_path, adjudicaciones(tmp_path))

    assert (gt.version_gt, gt.informe) == (VERSION_GT, INFORME)
    assert (gt.sha256_informe_original, gt.sha256_excel) == ("a" * 64, "e" * 64)
    assert [(f.ronda, f.modelo, f.complementa) for f in gt.fuentes] == [
        ("B2", SONNET, []), ("B2", OPUS, [])]
    por_estado = {(i.estado.value, i.lado_excel.fila if i.lado_excel else None): i
                  for i in gt.items}
    assert len(gt.items) == 5     # 4 de Sonnet + el coincide nuevo de Opus
    difiere = por_estado[("difiere", 20)]
    assert [o.modelo for o in difiere.origenes] == [SONNET, OPUS]
    assert (difiere.clase, difiere.subclase, difiere.campos) == ("A", "A4", ["calificacion"])
    assert difiere.lado_pdf is not None
    assert difiere.lado_pdf.clasificaciones == ["Clase uno", "Otra"]    # no entra en la clave
    assert [c.texto for c in difiere.lado_pdf.citas] == ["alfa uno", "ALFA UNO"]
    falta = por_estado[("falta_en_excel", None)]
    assert falta.depende_de == ["P14"] and falta.lado_excel is None
    assert falta.origenes[0].contraparte_excel is not None
    assert falta.origenes[0].contraparte_excel.referencia == 31
    extra = por_estado[("extra_en_excel", 21)]
    assert (extra.etapa_causa, extra.campos_extraccion) == ("e3", [CampoExtraccion.OMISION])
    # Sin verificar con Sonnet, verificado con Opus: el ítem queda verificado.
    assert por_estado[("coincide", 22)].nivel_validacion == NivelValidacion.VERIFICADO
    assert [o.modelo for o in por_estado[("coincide", 24)].origenes] == [OPUS]
    universo = gt.fuentes[0].universo
    assert (universo.coincide, universo.transversales, universo.adjudicados_antes) == (
        "todos", 1, 0)
    assert validar_gt(gt, tmp_path) == []


def test_conflicto_de_clase_entre_modelos_para_la_misma_clave_falla(tmp_path: Path) -> None:
    caso_base(tmp_path, clase_opus_0="D6")
    with pytest.raises(ConflictoGtError, match="clase"):
        construir_gt(tmp_path, adjudicaciones(tmp_path))


def test_mismo_par_con_otros_campos_no_se_fusiona(tmp_path: Path) -> None:
    # D4: la clave de un «difiere» incluye los campos que difieren.
    escribir_run(tmp_path, SONNET, [resultado("difiere", P_A, excel(20), campos=("calificacion",))],
                 [item(0, "difiere", cita_pdf="alfa uno", subclase="A4")])
    escribir_run(tmp_path, OPUS, [resultado("difiere", P_A, excel(20), campos=("descripcion",))],
                 [item(0, "difiere", cita_pdf="alfa uno", subclase="D6")])
    gt = construir_gt(tmp_path, adjudicaciones(tmp_path))
    assert [(i.subclase, i.campos) for i in gt.items] == [("A4", ["calificacion"]),
                                                          ("D6", ["descripcion"])]


def test_fuentes_de_otro_excel_fallan(tmp_path: Path) -> None:
    caso_base(tmp_path)
    (tmp_path / "b2" / "runs" / RUN[OPUS] / "input_excel.hash").write_text("f" * 64, "utf-8")
    with pytest.raises(GtError, match="mismo informe y Excel"):
        construir_gt(tmp_path, adjudicaciones(tmp_path))


def test_cita_que_no_esta_en_su_hallazgo_usa_la_descripcion_de_e3(tmp_path: Path) -> None:
    # El adjudicador citó el contexto del PDF (p. ej. que el bloque cumple).
    escribir_run(tmp_path, SONNET, [resultado("falta_en_excel", P_B)], [
        item(0, "falta_en_excel", pagina=8, fila=None, cita_pdf="otro texto del pdf",
             subclase="D2")])
    gt = construir_gt(tmp_path, adjudicaciones(tmp_path))
    (g,) = gt.items
    assert g.lado_pdf is not None
    assert [(c.texto, c.fuente) for c in g.lado_pdf.citas] == [("beta dos", "descripcion_e3")]


def test_universo_con_muestra_de_coincide_y_barrido_de_texto_identico(tmp_path: Path) -> None:
    identico = resultado("coincide", pdf(9, descripcion="x", accion="y"),
                         excel(22, descripcion="x", accion="y"))
    escribir_run(tmp_path, SONNET, [resultado("coincide", P_C, excel(20)), identico], [
        item(0, "coincide", pagina=9, fila=20, cita_pdf="gama")])
    (fuente,) = construir_gt(tmp_path, adjudicaciones(tmp_path)).fuentes
    universo = fuente.universo
    assert (universo.coincide, universo.items, universo.resultados) == ("muestra", 1, 2)
    assert (universo.barrido.coincide, universo.barrido.texto_identico) == (2, 1)


def test_alerta_sin_adjudicar_en_la_fuente_falla(tmp_path: Path) -> None:
    escribir_run(tmp_path, SONNET, [resultado("coincide", P_C, excel(20)),
                                    resultado("falta_en_excel", P_B)],
                 [item(0, "coincide", pagina=9, fila=20, cita_pdf="gama")])
    with pytest.raises(GtError, match="alertas sin adjudicar"):
        construir_gt(tmp_path, adjudicaciones(tmp_path))


def test_copia_de_un_resultado_que_no_esta_en_el_gt(tmp_path: Path) -> None:
    escribir_run(tmp_path, SONNET, [resultado("coincide", P_C, excel(20)),
                                    resultado("coincide", P_A, excel(21))],
                 [item(1, "coincide", pagina=7, fila=21, cita_pdf="alfa uno", duplica_idx=0)])
    (g,) = construir_gt(tmp_path, adjudicaciones(tmp_path)).items
    assert (g.es_duplicado, g.duplica_de) == (True, None)


def test_copia_dentro_del_gt_apunta_al_original(tmp_path: Path) -> None:
    escribir_run(tmp_path, SONNET, [resultado("coincide", P_C, excel(20)),
                                    resultado("coincide", P_A, excel(21))],
                 [item(0, "coincide", pagina=9, fila=20, cita_pdf="gama"),
                  item(1, "coincide", pagina=7, fila=21, cita_pdf="alfa uno", duplica_idx=0)])
    original, copia = construir_gt(tmp_path, adjudicaciones(tmp_path)).items
    assert (copia.es_duplicado, copia.duplica_de) == (True, original.id)


def test_validar_detecta_una_fuente_que_cambio(tmp_path: Path) -> None:
    caso_base(tmp_path)
    gt = construir_gt(tmp_path, adjudicaciones(tmp_path))
    reporte_opus = tmp_path / "b2" / "runs" / RUN[OPUS] / "reporte_final.json"
    reporte_opus.write_text(reporte_opus.read_text("utf-8") + " ", "utf-8")
    assert any("cambió" in p for p in validar_gt(gt, tmp_path))


def test_cli_construir_no_pisa_un_gt_distinto(tmp_path: Path) -> None:
    caso_base(tmp_path)
    salida = tmp_path / "gt"
    assert _construir(tmp_path, salida, sobrescribir=False) == 0
    (archivo,) = salida.glob("*.json")
    assert archivo.name == f"{INFORME}.json"
    assert cargar_gt(archivo) == construir_gt(tmp_path, adjudicaciones(tmp_path))
    archivo.write_text(archivo.read_text("utf-8").replace('"i001"', '"i001" '), "utf-8")
    assert _construir(tmp_path, salida, sobrescribir=False) == 1
    assert _construir(tmp_path, salida, sobrescribir=True) == 0



def test_cli_construir_no_deja_el_gt_en_una_carpeta_versionable(tmp_path: Path) -> None:
    """El GT lleva citas de los informes: dentro de un repositorio git, solo en
    una carpeta que git ignore."""
    from tests.test_persistence import repo_git

    caso_base(tmp_path)
    repo = repo_git(tmp_path, "mediciones/\n")
    with pytest.raises(ValueError, match="git no la ignora"):
        _construir(tmp_path, repo / "gt", sobrescribir=False)
    assert not (repo / "gt").exists()
    assert _construir(tmp_path, repo / "mediciones" / "gt", sobrescribir=False) == 0


# ------------------------------------------------------------ rondas posteriores

RUN_B3 = "2026-10-24_02-00-00_claude-opus-5-5"
# El par P_B / fila 24, que Opus emparejó en B2 como «coincide» (OK), sale
# «difiere» en B3: el GT de B2 no lo adjudica (mismo par, otro estado).
DIFIERE_B3 = item(1, "difiere", pagina=8, fila=24, cita_pdf="beta dos", subclase="C1",
                  depende_de=["P14"])


def caso_b3(med: Path, items_b3: list[dict[str, Any]] | None = None) -> Path:
    """caso_base más un run de B3 con Opus: el difiere, el extra y el coincide de
    B2 salen igual (los adjudica el GT de B2); el par P_B / fila 24 sale «difiere»."""
    caso_base(med)
    return escribir_run(med, OPUS, [
        resultado("difiere", P_A, excel(20), campos=("calificacion",)),
        resultado("difiere", P_B, excel(24), campos=("descripcion",)),
        resultado("extra_en_excel", None, excel(21)),
        resultado("coincide", P_C, excel(22)),
    ], [DIFIERE_B3] if items_b3 is None else items_b3, ronda="B3", run_id=RUN_B3)


def test_una_ronda_posterior_complementa_el_gt_de_las_anteriores(tmp_path: Path) -> None:
    """B3 adjudica solo lo que el GT de B2 no adjudica en su run; lo demás ya lo
    adjudican los ítems de B2 por clave estable. El mismo par puede quedar con
    dos ítems de distinto estado (el «coincide» OK de B2 y el «difiere» de B3)."""
    run_b3 = caso_b3(tmp_path)
    gt = construir_gt(tmp_path, adjudicaciones(tmp_path))

    assert [(f.ronda, f.modelo, f.run_id, f.complementa) for f in gt.fuentes] == [
        ("B2", SONNET, RUN[SONNET], []), ("B2", OPUS, RUN[OPUS], []),
        ("B3", OPUS, RUN_B3, ["B2"])]
    b3 = gt.fuentes[2].universo
    assert (b3.coincide, b3.resultados, b3.items, b3.adjudicados_antes) == ("todos", 4, 1, 3)
    assert len(gt.items) == 6 and gt.items[5].id == "i006"     # los de B2 no cambian de id
    nuevo = gt.items[5]
    assert (nuevo.estado.value, nuevo.campos, nuevo.clase, nuevo.subclase, nuevo.depende_de) == (
        "difiere", ["descripcion"], "C", "C1", ["P14"])
    assert [(o.modelo, o.run_id, o.idx) for o in nuevo.origenes] == [(OPUS, RUN_B3, 1)]
    (coincide,) = [g for g in gt.items if g.estado.value == "coincide" and g.lado_excel
                   and g.lado_excel.fila == 24]
    assert (coincide.clase, [o.run_id for o in coincide.origenes]) == ("OK", [RUN[OPUS]])
    assert validar_gt(gt, tmp_path) == []
    ev = evaluar_run(run_b3, gt)
    assert ev.sin_adjudicar == []
    assert ev.conteo == {"A": 1, "B": 0, "C": 1, "D": 1, "E": 0, "OK": 1}


def test_una_ronda_posterior_que_deja_una_alerta_sin_adjudicar_falla(tmp_path: Path) -> None:
    caso_b3(tmp_path, items_b3=[])
    with pytest.raises(GtError, match=r"alertas sin adjudicar \[1\]"):
        construir_gt(tmp_path, adjudicaciones(tmp_path))


@pytest.mark.parametrize(("subclase", "conflicto"), [("A4", False), ("D6", True)])
def test_una_ronda_posterior_se_fusiona_con_la_misma_clave_y_respeta_d3(
        tmp_path: Path, subclase: str, conflicto: bool) -> None:
    """Un resultado de B3 que el GT de B2 ya adjudica puede adjudicarse de nuevo:
    se fusiona con su ítem (el mismo modelo en otra ronda) si la clase es la
    misma, y falla si es otra (D3)."""
    caso_b3(tmp_path, items_b3=[item(0, "difiere", cita_pdf="alfa uno", subclase=subclase),
                                DIFIERE_B3])
    if conflicto:
        with pytest.raises(ConflictoGtError, match="clase"):
            construir_gt(tmp_path, adjudicaciones(tmp_path))
        return
    gt = construir_gt(tmp_path, adjudicaciones(tmp_path))
    assert [(o.modelo, o.run_id) for o in gt.items[0].origenes] == [
        (SONNET, RUN[SONNET]), (OPUS, RUN[OPUS]), (OPUS, RUN_B3)]
    assert (gt.fuentes[2].universo.items, gt.fuentes[2].universo.adjudicados_antes) == (2, 3)
    assert validar_gt(gt, tmp_path) == []


def test_una_ronda_sin_numero_no_se_puede_ordenar(tmp_path: Path) -> None:
    escribir_run(tmp_path, SONNET, [resultado("coincide", P_C, excel(20))],
                 [item(0, "coincide", pagina=9, fila=20, cita_pdf="gama")], ronda="Prueba")
    with pytest.raises(GtError, match="B<número>"):
        construir_gt(tmp_path, adjudicaciones(tmp_path))


# ------------------------------------------------------------ repeticiones de E4

FECHA_AG1 = "2026-10-25T19:00:00.000001"


def escribir_repeticion(med: Path, modelo: str, resultados: list[dict[str, Any]],
                        items: list[dict[str, Any]], *, etiqueta: str = "AG1",
                        ronda_origen: str = "B2", fecha: str | None = FECHA_AG1,
                        metadata: dict[str, Any] | None = None,
                        carpeta: str | None = None) -> Path:
    """Una repetición de E4 (comparador.reproducir_e4) del run de B2 del modelo:
    replay_e4/<etiqueta>/<run_id>, con el MISMO run_id que su origen, su reporte,
    los sha256 de los insumos y su metadata, sin Etapa 3 (es la del origen)."""
    run_id = RUN[modelo]
    rep = med / "replay_e4" / etiqueta / run_id
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "reporte_final.json").write_text(json.dumps(reporte(resultados, modelo)), "utf-8")
    (rep / "input_informe_original.hash").write_text("a" * 64 + "\n", "utf-8")
    (rep / "input_excel.hash").write_text("e" * 64 + "\n", "utf-8")
    meta = {"modo": "replay_e4", "run_origen": run_id, "fecha_inicio": fecha}
    (rep / "metadata.json").write_text(json.dumps(metadata or meta), "utf-8")
    corto = "sonnet" if modelo == SONNET else "opus"
    (med / "adjudicacion" / f"{etiqueta.lower()}_{corto}_Equis.json").write_text(json.dumps({
        "informe": INFORME, "ronda": etiqueta, "modelo": modelo, "run_id": run_id,
        "repeticion_e4": {"carpeta": carpeta or f"replay_e4/{etiqueta}/{run_id}",
                          "ronda_origen": ronda_origen},
        "verificado_por_segundo_agente": True, "items": items,
    }), "utf-8")
    return rep


# La repetición del run de Opus empareja distinto: la fila 24, que en B2 iba con
# P_B («coincide», OK), queda como «extra» (el resultado 1, la adjudicación
# nueva); P_B queda como falta, que ya adjudica el ítem C1 de Sonnet. El índice 1
# es en B2 Opus otro resultado (el «coincide» de P_B con la fila 24): un origen
# atado solo al run confundiría los dos.
RESULTADOS_AG1 = [
    resultado("difiere", {**P_A, "clasificacion": "Otra"}, excel(20), campos=("calificacion",)),
    resultado("extra_en_excel", None, excel(24)),
    resultado("falta_en_excel", P_B),
    resultado("extra_en_excel", None, excel(21)),
    resultado("coincide", P_C, excel(22)),
]
EXTRA_AG1 = item(1, "extra_en_excel", pagina=None, fila=24, subclase="D5")


def test_una_repeticion_de_e4_complementa_el_gt_con_el_run_id_de_su_origen(
        tmp_path: Path) -> None:
    caso_base(tmp_path)
    rep = escribir_repeticion(tmp_path, OPUS, RESULTADOS_AG1, [EXTRA_AG1])
    gt = construir_gt(tmp_path, adjudicaciones(tmp_path))

    assert [(f.ronda, f.modelo, f.run_id, f.carpeta, f.ronda_origen, f.complementa)
            for f in gt.fuentes] == [
        ("B2", SONNET, RUN[SONNET], f"b2/runs/{RUN[SONNET]}", None, []),
        ("B2", OPUS, RUN[OPUS], f"b2/runs/{RUN[OPUS]}", None, []),
        ("AG1", OPUS, RUN[OPUS], f"replay_e4/AG1/{RUN[OPUS]}", "B2", ["B2"])]
    ag1, b2_opus = gt.fuentes[2], gt.fuentes[1]
    # El reporte es el de la repetición; la Etapa 3, la de su origen.
    assert ag1.sha256_reporte == _sha(rep / "reporte_final.json") != b2_opus.sha256_reporte
    assert ag1.sha256_e3 == b2_opus.sha256_e3
    assert (ag1.universo.items, ag1.universo.adjudicados_antes, ag1.universo.coincide) == (
        1, 4, "todos")
    assert len(gt.items) == 6 and gt.items[5].id == "i006"
    nuevo = gt.items[5]
    assert (nuevo.estado.value, nuevo.subclase, nuevo.etapa_causa) == (
        "extra_en_excel", "D5", "e4")
    assert [(o.ronda, o.modelo, o.run_id, o.idx) for o in nuevo.origenes] == [
        ("AG1", OPUS, RUN[OPUS], 1)]
    assert validar_gt(gt, tmp_path) == []
    ev = evaluar_run(rep, gt)
    assert ev.sin_adjudicar == []
    assert ev.conteo == {"A": 1, "B": 0, "C": 1, "D": 2, "E": 0, "OK": 1}


def _sha(ruta: Path) -> str:
    import hashlib

    return hashlib.sha256(ruta.read_bytes()).hexdigest()


@pytest.mark.parametrize(("subclase", "conflicto"), [("A4", False), ("D6", True)])
def test_una_repeticion_que_vuelve_a_adjudicar_se_fusiona_y_respeta_d3(
        tmp_path: Path, subclase: str, conflicto: bool) -> None:
    """El mismo resultado, adjudicado en B2 y en su repetición de E4 (el mismo
    run_id en dos fuentes): se fusiona si la clase es la misma; si no, D3."""
    caso_base(tmp_path)
    escribir_repeticion(tmp_path, OPUS, RESULTADOS_AG1, [
        item(0, "difiere", cita_pdf="alfa uno", subclase=subclase), EXTRA_AG1])
    if conflicto:
        with pytest.raises(ConflictoGtError, match="clase"):
            construir_gt(tmp_path, adjudicaciones(tmp_path))
        return
    gt = construir_gt(tmp_path, adjudicaciones(tmp_path))
    assert [(o.ronda, o.modelo, o.run_id) for o in gt.items[0].origenes] == [
        ("B2", SONNET, RUN[SONNET]), ("B2", OPUS, RUN[OPUS]), ("AG1", OPUS, RUN[OPUS])]
    assert validar_gt(gt, tmp_path) == []


@pytest.mark.parametrize(("fecha", "orden"), [
    (FECHA_AG1, ["B2", "B3", "AG1"]),             # se corrió después de B3, como AG1
    ("2026-10-20T12:00:00", ["B2", "AG1", "B3"]),  # entre B2 y B3
])
def test_las_rondas_se_ordenan_por_fecha_y_la_repeticion_va_despues_de_su_origen(
        tmp_path: Path, fecha: str, orden: list[str]) -> None:
    """Las rondas van en el orden en que se corrieron: un GT se completa sin
    mover los ids de lo adjudicado antes (los ítems nuevos van al final)."""
    caso_b3(tmp_path)
    escribir_repeticion(tmp_path, OPUS, RESULTADOS_AG1, [EXTRA_AG1], fecha=fecha)
    gt = construir_gt(tmp_path, adjudicaciones(tmp_path))
    assert [f.ronda for f in gt.fuentes] == ["B2", "B2", *orden[1:]]
    assert {f.ronda: f.complementa for f in gt.fuentes[2:]} == {
        r: orden[:k + 1] for k, r in enumerate(orden[1:])}
    ids = {o.ronda: g.id for g in gt.items for o in g.origenes if o.ronda != "B2"}
    assert ids == {orden[1]: "i006", orden[2]: "i007"}
    assert validar_gt(gt, tmp_path) == []


@pytest.mark.parametrize(("cambio", "error", "mensaje"), [
    ({"metadata": {"modo": "replay_e4", "run_origen": "otro run",
                   "fecha_inicio": FECHA_AG1}}, GtError, "run_origen"),
    ({"metadata": {"modo": "pipeline", "run_origen": RUN[OPUS],
                   "fecha_inicio": FECHA_AG1}}, GtError, "replay_e4"),
    ({"fecha": None}, GtError, "fecha_inicio"),
    ({"fecha": "2026-10-16T00:00:00"}, GtError, "antes que su ronda de origen"),
    ({"ronda_origen": "B1"}, ValueError, "no existe .*b1/runs"),   # su Etapa 3 es la del origen
    ({"carpeta": "replay_e4/AG2/x"}, ValueError, "carpeta"),
])
def test_una_repeticion_mal_identificada_falla(
        tmp_path: Path, cambio: dict[str, Any], error: type[Exception], mensaje: str) -> None:
    caso_base(tmp_path)
    escribir_repeticion(tmp_path, OPUS, RESULTADOS_AG1, [EXTRA_AG1], **cambio)
    with pytest.raises(error, match=mensaje):
        construir_gt(tmp_path, adjudicaciones(tmp_path))


def test_una_repeticion_sin_su_ronda_de_origen_en_el_gt_falla(tmp_path: Path) -> None:
    """La repetición complementa el GT de su ronda de origen: sin ella no hay
    qué complementar (el run de origen existe, pero su adjudicación no)."""
    caso_base(tmp_path)
    for ruta in adjudicaciones(tmp_path):
        ruta.unlink()
    escribir_repeticion(tmp_path, OPUS, RESULTADOS_AG1, [EXTRA_AG1])
    with pytest.raises(GtError, match="ronda de origen B2 no está"):
        construir_gt(tmp_path, adjudicaciones(tmp_path))


def test_una_repeticion_sin_metadata_falla(tmp_path: Path) -> None:
    """Sin metadata.json la repetición no terminó: no se adjudica."""
    caso_base(tmp_path)
    rep = escribir_repeticion(tmp_path, OPUS, RESULTADOS_AG1, [EXTRA_AG1])
    (rep / "metadata.json").unlink()
    with pytest.raises(GtError, match="metadata.json"):
        construir_gt(tmp_path, adjudicaciones(tmp_path))


def test_formato_de_una_repeticion(tmp_path: Path) -> None:
    caso_base(tmp_path)
    escribir_repeticion(tmp_path, OPUS, RESULTADOS_AG1, [EXTRA_AG1])
    datos = construir_gt(tmp_path, adjudicaciones(tmp_path)).model_dump(mode="json")
    for cambio, mensaje in (
            (lambda d: d["fuentes"][2].update(carpeta=f"b2/runs/{RUN[OPUS]}"), "carpeta"),
            (lambda d: d["fuentes"][2].update(ronda_origen=None), "carpeta"),
            (lambda d: d["fuentes"][2].update(complementa=[]), "complementa"),
            (lambda d: d["items"][5]["origenes"][0].update(ronda="AG2"), "sin fuente")):
        copia = json.loads(json.dumps(datos))
        cambio(copia)
        with pytest.raises(ValidationError, match=mensaje):
            GtInforme.model_validate(copia)


def test_coincide_en_universo_con_dos_fuentes_del_mismo_modelo(tmp_path: Path) -> None:
    caso_b3(tmp_path)
    datos = construir_gt(tmp_path, adjudicaciones(tmp_path)).model_dump(mode="json")
    assert GtInforme.model_validate(datos).coincide_en_universo(OPUS)
    datos["fuentes"][2]["universo"]["coincide"] = "muestra"
    gt = GtInforme.model_validate(datos)
    assert not gt.coincide_en_universo(OPUS)
    assert gt.coincide_en_universo(SONNET)


# ------------------------------------------------------------ preguntas y causas


def _item_c(texto: str, subclase: str = "C1") -> Any:
    return item_desde_dict(item(0, "falta_en_excel", fila=None, subclase=subclase,
                                explicacion=texto))


def test_preguntas_de_traduce_la_numeracion_vieja() -> None:
    assert preguntas_de("Equis", _item_c("Pregunta 4.2 pendiente")) == ["P15", "P16"]
    assert preguntas_de("Equis", _item_c("depende de las preguntas 4.1 y 4.3")) == ["P14", "P17"]
    assert preguntas_de("Añañuca", _item_c("sin mención", "C2")) == ["P19"]
    assert preguntas_de("Alfa", _item_c("sin mención", "C2")) == ["P18"]
    # En una falsa alarma la mención no es dependencia.
    d5 = item_desde_dict(item(0, "difiere", subclase="D5", explicacion="pregunta 4.1"))
    assert preguntas_de("Equis", d5) == []


def test_preguntas_de_acepta_la_dependencia_explicita_de_la_adjudicacion() -> None:
    """Una adjudicación nueva nombra la pregunta con la numeración de la v3."""
    explicito = item_desde_dict(item(0, "falta_en_excel", fila=None, subclase="C1",
                                     explicacion="sin mención", depende_de=["P14"]))
    assert preguntas_de("Equis", explicito) == ["P14"]
    d6 = item_desde_dict(item(0, "difiere", subclase="D6", depende_de=["P14"]))
    with pytest.raises(GtError, match="depende_de"):
        preguntas_de("Equis", d6)
    with pytest.raises(ValueError, match="depende_de"):
        item_desde_dict(item(0, "falta_en_excel", fila=None, subclase="C1",
                             depende_de=["4.1"]))


@pytest.mark.parametrize(("texto", "mensaje"), [
    ("sin mención", "sin pregunta"),
    ("pregunta 4.9", "sin traducir"),
])
def test_criterio_por_definir_sin_pregunta_conocida_falla(texto: str, mensaje: str) -> None:
    with pytest.raises(GtError, match=mensaje):
        preguntas_de("Equis", _item_c(texto))


def test_d7_sin_causa_explicita_falla(tmp_path: Path) -> None:
    escribir_run(tmp_path, SONNET, [resultado("falta_en_excel", P_B)], [
        item(0, "falta_en_excel", pagina=8, fila=None, cita_pdf="beta dos", subclase="D7")])
    with pytest.raises(GtError, match="sin causa"):
        construir_gt(tmp_path, adjudicaciones(tmp_path))


# ------------------------------------------------------------ formato


def _gt_dict(tmp_path: Path) -> dict[str, Any]:
    caso_base(tmp_path)
    datos: dict[str, Any] = construir_gt(tmp_path, adjudicaciones(tmp_path)).model_dump(
        mode="json")
    return datos


def test_formato_rechaza_campos_desconocidos(tmp_path: Path) -> None:
    datos = _gt_dict(tmp_path)
    datos["items"][0]["nota_libre"] = "x"
    with pytest.raises(ValidationError, match="nota_libre"):
        GtInforme.model_validate(datos)


@pytest.mark.parametrize(("cambio", "mensaje"), [
    (lambda d: d.update(version_gt="0.9"), "version_gt"),
    (lambda d: d["items"][1].update(depende_de=[]), "depende_de"),
    (lambda d: d["items"][0].update(etapa_causa="e3"), "etapa_causa"),
    (lambda d: d["items"][0].update(campos=[]), "campos"),
    (lambda d: d["items"][0].update(es_duplicado=True, duplica_de="i999"), "duplica_de"),
    (lambda d: d["items"][0].update(subclase="D6"), "subclase"),
    (lambda d: d["fuentes"][1].update(run_id=d["fuentes"][0]["run_id"]), "fuentes"),
    (lambda d: d["items"][0]["origenes"][0].update(run_id="otro run"), "sin fuente"),
    (lambda d: d["items"][0]["origenes"][1].update(run_id=RUN[SONNET], modelo=SONNET),
     "repetidos"),
    (lambda d: d["fuentes"][0].update(complementa=["B2"]), "complementa"),
    (lambda d: d["fuentes"][0].update(complementa=["B1"]), "complementa"),
    (lambda d: d["fuentes"][0].update(carpeta=f"b3/runs/{RUN[SONNET]}"), "carpeta"),
    (lambda d: d["fuentes"][1].update(ronda_origen="B2"), "carpeta"),
    (lambda d: d["items"][0]["origenes"][1].update(ronda="B3"), "sin fuente"),
])
def test_formato_valida_la_coherencia(tmp_path: Path, cambio: Any, mensaje: str) -> None:
    datos = _gt_dict(tmp_path)
    cambio(datos)
    with pytest.raises(ValidationError, match=mensaje):
        GtInforme.model_validate(datos)
