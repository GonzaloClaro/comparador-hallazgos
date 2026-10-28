"""Tests de la evaluación del comparador contra su GT (sin API, datos sintéticos).

Cada resultado de un reporte cae en un veredicto (adjudicado, OK por texto
idéntico, sin adjudicar con su motivo, fuera de universo o transversal). Lo sin
adjudicar nunca cuenta como correcto. Textos inventados.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from comparador.evaluar_comparador import (
    GtNoAplicaError,
    MotivoSinAdjudicar,
    PosibleEscondido,
    Veredicto,
    evaluar,
    evaluar_run,
    gt_del_run,
    resumen,
)
from comparador.gt_comparador import VERSION_GT, GtInforme, serializar
from comparador.schemas import ReporteInforme
from tests.test_adjudicacion import excel, pdf, resultado
from tests.test_gt_comparador import reporte

OPUS, SONNET = "claude-opus-5-5", "claude-sonnet-5-5"
SHA_I, SHA_E = "a" * 64, "e" * 64


def item_gt(id_: str, estado: str, *, fila: int | None = None, pagina: int | None = None,
            cita: str = "alfa uno", campos: tuple[str, ...] = (), clase: str = "OK",
            subclase: str | None = None, es_duplicado: bool = False) -> dict[str, Any]:
    subclase = subclase or clase
    return {
        "id": id_, "pano": "C1", "rele": "REL 1", "estado": estado, "campos": list(campos),
        "lado_excel": None if fila is None else {"fila": fila},
        "lado_pdf": None if pagina is None else {
            "pagina": pagina, "clasificaciones": ["Clase uno"],
            "citas": [{"texto": cita, "fuente": "adjudicacion", "modelo": OPUS}]},
        "clase": clase, "subclase": subclase, "nivel_validacion": "verificado",
        "depende_de": ["P14"] if clase == "C" else [], "es_duplicado": es_duplicado,
        "etapa_causa": "e4" if clase == "D" else None,
        "origenes": [{"modelo": OPUS, "ronda": "B2", "run_id": "r", "idx": 0,
                      "tipo_match": "unicidad",
                      "subclase": subclase, "nivel_validacion": "verificado"}],
    }


def gt_de(items: list[dict[str, Any]], *, coincide: str = "todos",
          errores: list[dict[str, Any]] | None = None,
          universos: dict[str, str] | None = None, run_id: str = "r") -> GtInforme:
    """GT sintético de B2: una fuente por modelo de ``universos``. La primera usa
    ``run_id`` (el de los orígenes de ``item_gt``); las demás, uno propio."""
    universos = universos or {OPUS: coincide}
    return GtInforme.model_validate({
        "version_gt": VERSION_GT, "informe": "S-E Equis (Auditora Reliable Energy)",
        "sha256_informe_original": SHA_I, "sha256_excel": SHA_E,
        "fuentes": [{"modelo": m, "ronda": "B2", "run_id": run_id if n == 0 else f"{run_id}-{n}",
                     "carpeta": f"b2/runs/{run_id}" if n == 0 else f"b2/runs/{run_id}-{n}",
                     "adjudicacion": "x.json", "sha256_adjudicacion": "0",
                     "sha256_reporte": "0", "sha256_e3": "0",
                     "verificado_por_segundo_agente": True,
                     "universo": {"regla": "r", "coincide": c, "resultados": 0,
                                  "transversales": 0, "items": len(items),
                                  "barrido": {"coincide": 0, "texto_identico": 0}}}
                    for n, (m, c) in enumerate(universos.items())],
        "items": items, "errores_excel": errores or [],
    })


def evaluar_(resultados: list[dict[str, Any]], gt: GtInforme, modelo: str = OPUS) -> Any:
    rep = ReporteInforme.model_validate(reporte(resultados, modelo))
    return evaluar(rep, gt, sha256_informe=SHA_I, sha256_excel=SHA_E, run_id="run")


P_A, P_B, P_C = pdf(7, descripcion="alfa uno"), pdf(8, descripcion="beta dos"), pdf(9,
                                                                                descripcion="gama")
P_D = pdf(11, descripcion="delta")


def gt_base(**kw: Any) -> GtInforme:
    return gt_de([
        item_gt("i1", "difiere", fila=20, pagina=7, campos=("calificacion",), clase="A",
                subclase="A4"),
        item_gt("i2", "falta_en_excel", pagina=8, cita="beta dos", clase="C", subclase="C1"),
        item_gt("i3", "extra_en_excel", fila=21, clase="D", subclase="D1", es_duplicado=True),
        item_gt("i4", "coincide", fila=22, pagina=9, cita="gama"),
        item_gt("i5", "difiere", fila=25, pagina=11, cita="delta", campos=("descripcion",),
                clase="D", subclase="D6"),
        item_gt("i6", "falta_en_excel", pagina=12, cita="epsilon", clase="A", subclase="A1"),
    ], **kw)


# ------------------------------------------------------------ veredictos


def test_cada_resultado_cae_en_su_veredicto_y_lo_sin_adjudicar_no_cuenta() -> None:
    identico = resultado("coincide", pdf(13, descripcion="zeta", accion="z"),
                         excel(26, descripcion="zeta", accion="z"))
    ev = evaluar_([
        resultado("difiere", P_A, excel(20), campos=("calificacion",)),
        resultado("falta_en_excel", P_B),
        resultado("extra_en_excel", None, excel(21)),
        resultado("coincide", P_C, excel(22)),
        resultado("difiere", P_D, excel(25), campos=("accion_correctiva",)),   # D4
        identico,
        resultado("falta_en_excel", pdf(14, descripcion="eta")),
        resultado("transversal", None, excel(30)),
    ], gt_base())

    assert [(r.veredicto, r.item_gt, r.clase) for r in ev.resultados[:4]] == [
        (Veredicto.ADJUDICADO, "i1", "A"), (Veredicto.ADJUDICADO, "i2", "C"),
        (Veredicto.ADJUDICADO, "i3", "D"), (Veredicto.ADJUDICADO, "i4", "OK")]
    assert [(r.veredicto, r.motivo) for r in ev.resultados[4:]] == [
        (Veredicto.SIN_ADJUDICAR, MotivoSinAdjudicar.CAMPOS_DISTINTOS),
        (Veredicto.OK_TEXTO_IDENTICO, None),
        (Veredicto.SIN_ADJUDICAR, MotivoSinAdjudicar.CLAVE_NO_ENCONTRADA),
        (Veredicto.TRANSVERSAL, None)]
    assert ev.conteo == {"A": 1, "B": 0, "C": 1, "D": 1, "E": 0, "OK": 1}
    assert ev.sin_duplicados["D"] == 0             # i3 es copia
    assert (ev.ok_texto_identico, ev.alertas, ev.alertas_sin_adjudicar) == (1, 5, 2)
    assert ev.precision == 0.5
    assert ev.precision_rango == (1 / 4, 3 / 4)    # las 2 sin adjudicar: todas D … todas A
    assert ev.a_perdidos == ["i6"]


def test_mismo_par_con_otro_estado_queda_sin_adjudicar() -> None:
    ev = evaluar_([resultado("coincide", P_D, excel(25))], gt_base())
    (r,) = ev.resultados
    assert (r.veredicto, r.motivo, r.candidatos) == (
        Veredicto.SIN_ADJUDICAR, MotivoSinAdjudicar.ESTADO_DISTINTO, ("i5",))
    assert ev.conteo["OK"] == 0


@pytest.mark.parametrize("res", [
    resultado("difiere", P_B, excel(20), campos=("calificacion",)),   # fila 20 con otro hallazgo
    resultado("difiere", P_B, excel(24), campos=("descripcion",)),    # la falta ahora tiene pareja
])
def test_otro_emparejamiento_es_par_distinto(res: dict[str, Any]) -> None:
    (r,) = evaluar_([res], gt_base()).resultados
    assert (r.veredicto, r.motivo) == (Veredicto.SIN_ADJUDICAR, MotivoSinAdjudicar.PAR_DISTINTO)


def test_dos_items_del_gt_para_un_resultado_es_ambiguo() -> None:
    gt = gt_de([item_gt("i1", "falta_en_excel", pagina=8, cita="beta", clase="C",
                        subclase="C1"),
                item_gt("i2", "falta_en_excel", pagina=8, cita="dos", clase="A",
                        subclase="A1")])
    (r,) = evaluar_([resultado("falta_en_excel", P_B)], gt).resultados
    assert (r.motivo, r.candidatos) == (MotivoSinAdjudicar.AMBIGUA, ("i1", "i2"))


def test_coincide_con_texto_identico_de_un_par_del_gt_con_otro_estado_no_es_ok() -> None:
    """La regla del texto idéntico (D13) es para un «coincide» sin ítem del GT:
    un A que pasó a «coincide» con el texto igualado queda sin adjudicar."""
    igualado = resultado("coincide", pdf(7, descripcion="alfa uno"),
                         excel(20, descripcion="alfa uno"))
    ev = evaluar_([igualado], gt_base())
    (r,) = ev.resultados
    assert (r.veredicto, r.motivo, r.candidatos) == (
        Veredicto.SIN_ADJUDICAR, MotivoSinAdjudicar.ESTADO_DISTINTO, ("i1",))
    assert ev.ok_texto_identico == 0 and "i1" in ev.a_perdidos


def test_un_item_del_gt_no_se_adjudica_a_dos_resultados() -> None:
    """Dos resultados que calzan con el mismo ítem: ninguno queda adjudicado
    (no se infla la clase ni la precisión) y el ítem no cuenta como perdido."""
    segundo = resultado("difiere", pdf(7, descripcion="alfa uno, otra extracción"), excel(20),
                        campos=("calificacion",))
    ev = evaluar_([resultado("difiere", P_A, excel(20), campos=("calificacion",)), segundo,
                   resultado("difiere", P_D, excel(25), campos=("descripcion",))], gt_base())
    assert [(r.veredicto, r.motivo, r.candidatos) for r in ev.resultados[:2]] == [
        (Veredicto.SIN_ADJUDICAR, MotivoSinAdjudicar.ITEM_REPETIDO, ("i1",))] * 2
    assert (ev.resultados[2].veredicto, ev.resultados[2].item_gt) == (Veredicto.ADJUDICADO, "i5")
    assert (ev.conteo["A"], ev.conteo["D"], ev.precision) == (0, 1, 0.0)
    assert ev.alertas_sin_adjudicar == 2
    assert "i1" not in ev.a_perdidos
    assert resumen(ev)["motivos_sin_adjudicar"] == {"item_repetido": 2}


# Dos ítems A que son el mismo error: el hallazgo del PDF que el Excel no trae,
# con la misma cita, página y tupla; en un modelo el juez lo emparejó con una
# fila ajena (difiere) y en el otro quedó como falta.
A_PAR_AJENO = item_gt("a1", "difiere", fila=24, pagina=9, cita="kappa omitido",
                      campos=("descripcion", "accion_correctiva"), clase="A", subclase="A1")
A_FALTA = item_gt("a2", "falta_en_excel", pagina=9, cita="kappa omitido", clase="A",
                  subclase="A1")
P_K = pdf(9, descripcion="kappa omitido")


@pytest.mark.parametrize(("resultados", "perdidos"), [
    ([resultado("falta_en_excel", P_K)], []),
    ([resultado("difiere", P_K, excel(24), campos=("descripcion", "accion_correctiva"))], []),
    # Sin ninguno de los dos, el error se pierde una vez, con el primer ítem del GT.
    ([], ["a1"]),
])
def test_un_a_no_se_pierde_si_el_run_muestra_el_mismo_error_con_otro_item(
        resultados: list[dict[str, Any]], perdidos: list[str]) -> None:
    ev = evaluar_(resultados, gt_de([A_PAR_AJENO, A_FALTA]))
    assert ev.a_perdidos == perdidos


def test_cada_error_perdido_cuenta_una_vez() -> None:
    # Dos errores distintos (otra página) se pierden los dos.
    otro = item_gt("a3", "falta_en_excel", pagina=12, cita="lambda omitido", clase="A",
                   subclase="A1")
    assert evaluar_([], gt_de([A_PAR_AJENO, A_FALTA, otro])).a_perdidos == ["a1", "a3"]
    # mismo_error no es transitivo del lado del PDF (comparte alguna cita): a1 y a3 no
    # comparten cita, pero a2 comparte una con cada uno. Son un solo error.
    puente = {**A_FALTA, "lado_pdf": {**A_FALTA["lado_pdf"], "citas": [
        *A_FALTA["lado_pdf"]["citas"],
        {"texto": "kappa segundo", "fuente": "adjudicacion", "modelo": OPUS}]}}
    tercero = item_gt("a3", "falta_en_excel", pagina=9, cita="kappa segundo", clase="A",
                      subclase="A1")
    assert evaluar_([], gt_de([A_PAR_AJENO, tercero, puente])).a_perdidos == ["a1"]
    # El run muestra el error por a1: tampoco está perdido por a3 (el mismo error por el
    # puente a2), y el delta no lo informa como un error recién perdido.
    mostrado = resultado("difiere", P_K, excel(24), campos=("descripcion", "accion_correctiva"))
    assert evaluar_([mostrado], gt_de([A_PAR_AJENO, tercero, puente])).a_perdidos == []


def test_el_mismo_error_es_el_del_lado_propio_de_cada_a() -> None:
    # A4 en dos ítems de la misma fila (otros campos): el mismo error del Excel.
    a4_otros = item_gt("a3", "difiere", fila=20, pagina=7, cita="alfa uno",
                       campos=("descripcion", "calificacion"), clase="A", subclase="A4")
    ev = evaluar_([resultado("difiere", P_A, excel(20), campos=("calificacion",))],
                  gt_de([gt_base().items[0].model_dump(mode="json"), a4_otros]))
    assert ev.a_perdidos == []
    # Un A1 emparejado con la fila 20 no es el error de esa fila (A4): su lado
    # propio es el hallazgo del PDF, que el run no muestra.
    a1_fila_20 = item_gt("a4", "difiere", fila=20, pagina=8, cita="beta dos",
                         campos=("descripcion",), clase="A", subclase="A1")
    ev = evaluar_([resultado("difiere", P_A, excel(20), campos=("calificacion",))],
                  gt_de([gt_base().items[0].model_dump(mode="json"), a1_fila_20]))
    assert ev.a_perdidos == ["a4"]
    # Una página u otra cita distinta: otro hallazgo, no se agrupan.
    otra_pagina = {**A_FALTA, "lado_pdf": {**A_FALTA["lado_pdf"], "pagina": 10}}
    otra_cita = item_gt("a2", "falta_en_excel", pagina=9, cita="kappa", clase="A",
                        subclase="A1")
    for falta in (otra_pagina, otra_cita):
        ev = evaluar_([resultado("difiere", P_K, excel(24),
                                 campos=("descripcion", "accion_correctiva"))],
                      gt_de([A_PAR_AJENO, falta]))
        assert ev.a_perdidos == ["a2"]


def test_un_a_con_una_subclase_sin_lado_propio_conocido_falla() -> None:
    raro = item_gt("a9", "falta_en_excel", pagina=9, cita="kappa", clase="A", subclase="A9")
    with pytest.raises(ValueError, match="A9"):
        evaluar_([], gt_de([raro]))


def test_coincide_sin_clave_fuera_de_la_muestra_es_fuera_de_universo() -> None:
    nuevo = resultado("coincide", pdf(20, descripcion="nuevo"), excel(40, descripcion="otro"))
    (r,) = evaluar_([nuevo], gt_base(coincide="muestra")).resultados
    assert (r.veredicto, r.motivo) == (Veredicto.FUERA_DE_UNIVERSO, None)
    (r,) = evaluar_([nuevo], gt_base(coincide="todos")).resultados
    assert r.motivo == MotivoSinAdjudicar.CLAVE_NO_ENCONTRADA
    # Un modelo sin fuente usa la regla más estricta: muestra si alguno muestreó.
    gt = gt_base(universos={OPUS: "todos", SONNET: "muestra"})
    assert not gt.coincide_en_universo("claude-haiku-5-5")
    assert gt.coincide_en_universo(OPUS)


def test_posibles_errores_escondidos() -> None:
    ev = evaluar_([
        resultado("coincide", P_B, excel(20)),     # toma la fila 20 del A i1 (con otro hallazgo)
        resultado("coincide", P_D, excel(25)),     # el par completo del D i5 sale coincide
        resultado("coincide", P_C, excel(22)),     # adjudicado OK: no es sospechoso
    ], gt_base())
    # i2 (C) comparte el hallazgo del PDF con el primero, pero solo se miran A y D.
    assert ev.posibles_escondidos == [PosibleEscondido("i1", "A", 0, par_completo=False),
                                      PosibleEscondido("i5", "D", 1, par_completo=True)]


# ------------------------------------------------------------ errores del Excel


def _error(validada: bool = True) -> dict[str, Any]:
    return {"id": "e1", "fila_excel": 20, "pagina_pdf": 7, "clasificacion_pdf": "Clase uno",
            "campos": ["calificacion"], "subclase": "A4", "contraparte_validada": validada,
            "no_mostrado_en_b2": [OPUS], "cita_pdf": "p", "cita_excel": "e", "fuente": "x"}


@pytest.mark.parametrize(("resultados", "validada", "estado"), [
    ([resultado("difiere", P_A, excel(20), campos=("calificacion",))], True, "mostrado"),
    ([resultado("coincide", P_A, excel(20))], True, "escondido"),
    ([resultado("difiere", P_B, excel(20), campos=("calificacion",))], True, "no_mostrado"),
    ([resultado("difiere", P_A, excel(20), campos=("descripcion",))], True, "no_mostrado"),
    ([resultado("falta_en_excel", P_A)], True, "no_mostrado"),       # la fila no aparece
    ([resultado("difiere", {**P_A, "clasificacion": "Otra"}, excel(20),
                campos=("descripcion",))], False, "mostrado"),      # basta llegar a la página
    ([resultado("difiere", P_B, excel(20), campos=("calificacion",))], False, "no_mostrado"),
])
def test_estado_de_los_errores_del_excel(resultados: list[dict[str, Any]], validada: bool,
                                         estado: str) -> None:
    ev = evaluar_(resultados, gt_de([], errores=[_error(validada)]))
    assert [e.estado for e in ev.errores_excel] == [estado]


def test_error_del_excel_con_equivalencia_del_juez_no_se_muestra() -> None:
    res = resultado("difiere", P_A, excel(20), campos=("calificacion",))
    res["equivalencias_redaccion"] = [{"campo": "descripcion", "valor_pdf": "a",
                                       "valor_excel": "b", "similitud": 0.8,
                                       "justificacion": "j"}]
    (e,) = evaluar_([res], gt_de([], errores=[_error()])).errores_excel
    assert e.estado == "no_mostrado" and "equivalentes" in e.motivos[0]


# ------------------------------------------------------------ hashes y resumen


def test_gt_de_otro_informe_no_aplica() -> None:
    rep = ReporteInforme.model_validate(reporte([], OPUS))
    with pytest.raises(GtNoAplicaError, match="otro informe o Excel"):
        evaluar(rep, gt_base(), sha256_informe=SHA_I, sha256_excel="f" * 64)


def test_run_sin_reporte_no_tiene_comparador_que_evaluar(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "input_informe_original.hash").write_text(SHA_I, "utf-8")
    (run / "input_excel.hash").write_text(SHA_E, "utf-8")
    with pytest.raises(ValueError, match="sin reporte_final.json"):
        evaluar_run(run, gt_base())


def test_evaluar_run_busca_el_gt_por_los_hashes_del_run(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "reporte_final.json").write_text(json.dumps(reporte(
        [resultado("difiere", P_A, excel(20), campos=("calificacion",))], OPUS)), "utf-8")
    with pytest.raises(GtNoAplicaError, match="input_informe_original.hash"):
        evaluar_run(run, gt_base())
    (run / "input_informe_original.hash").write_text(SHA_I + "\n", "utf-8")
    (run / "input_excel.hash").write_text(SHA_E, "utf-8")
    carpeta = tmp_path / "gt"
    carpeta.mkdir()
    (carpeta / "Equis.json").write_text(serializar(gt_base()), "utf-8")
    ev = evaluar_run(run, gt_del_run(run, carpeta))
    assert (ev.run_id, ev.modelo, ev.conteo["A"]) == ("run", OPUS, 1)
    (run / "input_excel.hash").write_text("f" * 64, "utf-8")
    with pytest.raises(GtNoAplicaError, match="ningún GT"):
        gt_del_run(run, carpeta)


def test_resumen_sin_texto_de_los_informes() -> None:
    ev = evaluar_([resultado("difiere", P_A, excel(20), campos=("calificacion",)),
                   resultado("falta_en_excel", pdf(14, descripcion="eta"))],
                  gt_base(errores=[_error()]))
    datos = resumen(ev)
    assert (datos["A"], datos["sin_adjudicar"], datos["alertas_sin_adjudicar"]) == (1, 1, 1)
    assert datos["motivos_sin_adjudicar"] == {"clave_no_encontrada": 1}
    assert datos["estados_sin_adjudicar"] == {"falta_en_excel": 1}
    assert (datos["precision_min"], datos["precision_max"]) == (0.5, 1.0)
    assert datos["errores_excel"] == [{"id": "e1", "fila_excel": 20, "estado": "mostrado"}]
    texto = json.dumps(datos, ensure_ascii=False)
    for palabra in ("alfa", "beta", "Clase uno"):
        assert palabra not in texto
