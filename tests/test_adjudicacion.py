"""Tests de la alineación adjudicación ↔ reporte ↔ Etapa 3 (sin API, datos sintéticos).

La adjudicación del comparador clasifica cada resultado de un reporte por su
índice, que no es estable entre corridas: `comparador.adjudicacion` comprueba que
cada ítem sea de su resultado (paño, relé, estado, página y fila), ubica su
hallazgo del PDF en la Etapa 3 y arma las claves estables con que se busca en
otro reporte. Textos inventados: ningún texto de informes reales.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from comparador import etapa4_matching as e4
from comparador.adjudicacion import (
    AlineacionError,
    ClaveExcel,
    ClavePdf,
    NivelValidacion,
    alinear,
    alinear_todos,
    buscar,
    campos_que_difieren,
    cargar_adjudicacion,
    clase_final,
    claves_del_item,
    item_desde_dict,
    mapa_e3,
    normalizar_texto,
)
from comparador.schemas import CampoDiferente, EstadoHallazgo, Hallazgo, MatchResult

# ------------------------------------------------------------------ fixtures


def hallazgo(
    pano: str = "C1", rele: str = "REL 1", *, fuente: str = "pdf", pagina: int | None = None,
    fila: int | None = None, clasificacion: str = "Clase uno", descripcion: str = "texto alfa",
    accion: str | None = "accion alfa", calificacion: str = "Menor", crudo: str | None = None,
    pagina_citada: int | None = None,
) -> dict[str, Any]:
    evidencia: dict[str, Any] = {
        "fuente": fuente, "pagina_pdf": pagina, "fila_excel": fila,
        "texto_crudo": crudo if crudo is not None else f"{descripcion} | {accion}",
    }
    if pagina_citada is not None:
        evidencia["verificacion_descripcion"] = {
            "estado": "en_otra_pagina", "pagina": pagina, "pagina_citada": pagina_citada,
        }
    return {
        "pano": pano, "rele": rele, "clasificacion": clasificacion, "descripcion": descripcion,
        "accion_correctiva": accion, "calificacion": calificacion, "evidencia": evidencia,
    }


def pdf(pagina: int = 7, **kw: Any) -> dict[str, Any]:
    return hallazgo(pagina=pagina, **kw)


def excel(fila: int = 20, **kw: Any) -> dict[str, Any]:
    return hallazgo(fuente="excel", fila=fila, **kw)


def resultado(
    estado: str, h_pdf: dict[str, Any] | None = None, h_excel: dict[str, Any] | None = None,
    campos: tuple[str, ...] = (), pano: str = "C1", rele: str = "REL 1",
) -> dict[str, Any]:
    tipo = "sin_match" if estado in ("falta_en_excel", "extra_en_excel") else "unicidad"
    return {
        "pano": pano, "rele": rele, "estado": estado, "tipo_match": tipo,
        "confianza": 1.0 if tipo == "unicidad" else 0.0, "justificacion": "j",
        "hallazgo_pdf": h_pdf, "hallazgo_excel": h_excel,
        "diferencias": [{"campo": c, "valor_pdf": "a", "valor_excel": "b"} for c in campos],
    }


def item(
    idx: int, estado: str, *, pagina: int | None = 7, fila: int | None = 20,
    cita_pdf: str = "texto alfa", cita_excel: str = "texto alfa", subclase: str = "OK",
    pano: str = "C1", rele: str = "REL 1", **extra: Any,
) -> dict[str, Any]:
    return {
        "idx": idx, "pano": pano, "rele": rele, "estado": estado, "tipo_match": "unicidad",
        "confianza": 1.0, "clase": subclase[:1] if subclase != "OK" else "OK",
        "subclase": subclase, "explicacion": "e",
        "pdf": None if pagina is None else {"pagina": pagina, "cita": cita_pdf},
        "excel": None if fila is None else {"fila": fila, "cita": cita_excel},
        "verificacion": {"confirmado": True, "clase_corregida": subclase, "nota": "n"},
        **extra,
    }


def modelos(
    resultados: list[dict[str, Any]], e3: list[dict[str, Any]]
) -> tuple[list[MatchResult], list[Hallazgo]]:
    return ([MatchResult.model_validate(r) for r in resultados],
            [Hallazgo.model_validate(h) for h in e3])


# ------------------------------------------------------------ clase y lados


def test_clase_y_subclase_finales_son_las_del_verificador() -> None:
    corregido = item_desde_dict({**item(0, "extra_en_excel", subclase="A2"),
                                 "verificacion": {"confirmado": False, "clase_corregida": "C2",
                                                  "nota": "n"}})
    assert (corregido.clase, corregido.subclase) == ("C", "C2")
    # Coincide sin subclase (así la dejó un adjudicador): clase OK.
    sin_sub = item_desde_dict({**item(1, "coincide"), "subclase": None, "verificacion": None})
    assert (sin_sub.clase, sin_sub.subclase) == ("OK", "OK")
    assert clase_final({"subclase": "D6"}) == "D"


def test_clase_desconocida_falla() -> None:
    with pytest.raises(ValueError, match="clase desconocida"):
        item_desde_dict(item(0, "difiere", subclase="Z9"))


def test_nivel_de_validacion() -> None:
    assert item_desde_dict(item(0, "coincide")).nivel_validacion == NivelValidacion.VERIFICADO
    sin = item_desde_dict({**item(0, "coincide"), "verificacion": None})
    assert sin.nivel_validacion == NivelValidacion.SOLO_ADJUDICADOR


def test_regla_de_contraparte_por_el_lado_que_falta_en_el_resultado() -> None:
    falta = item_desde_dict(item(0, "falta_en_excel", fila=31))
    assert falta.excel is not None and falta.excel.es_contraparte
    assert falta.pdf is not None and not falta.pdf.es_contraparte
    assert falta.lado_excel_propio is None and falta.lado_pdf_propio is falta.pdf
    extra = item_desde_dict(item(1, "extra_en_excel", pagina=9))
    assert extra.pdf is not None and extra.pdf.es_contraparte
    assert extra.lado_pdf_propio is None
    par = item_desde_dict(item(2, "difiere"))
    assert par.lado_pdf_propio is par.pdf and par.lado_excel_propio is par.excel


def test_marca_de_contraparte_que_contradice_la_regla_falla() -> None:
    datos = item(0, "difiere")
    datos["excel"]["es_contraparte"] = True
    with pytest.raises(ValueError, match="contraparte"):
        item_desde_dict(datos)


def test_cargar_adjudicacion_lee_cabecera_e_items(tmp_path: Path) -> None:
    ruta = tmp_path / "b2_opus_X.json"
    ruta.write_text(json.dumps({
        "informe": "S-E X (Auditora Ensaut)", "ronda": "B2", "modelo": "claude-opus-5-5",
        "run_id": "r1", "items": [item(0, "coincide"), item(1, "falta_en_excel", fila=None,
                                                           duplica_idx=0)],
    }), encoding="utf-8")
    adj = cargar_adjudicacion(ruta)
    assert (adj.informe, adj.ronda, adj.modelo, adj.run_id) == (
        "S-E X (Auditora Ensaut)", "B2", "claude-opus-5-5", "r1")
    assert [i.idx for i in adj.items] == [0, 1]
    assert adj.items[1].duplica_idx == 0 and adj.items[1].excel is None


# ------------------------------------------------------------ alineación


def _caso_basico() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    p0 = pdf(7, descripcion="alfa uno")
    p1 = pdf(8, descripcion="beta dos")
    resultados = [
        resultado("difiere", p0, excel(20), campos=("calificacion",)),
        resultado("falta_en_excel", p1),
        resultado("extra_en_excel", None, excel(21)),
    ]
    return resultados, [p1, p0]   # E3 en otro orden que el reporte


def test_alinear_devuelve_el_indice_del_hallazgo_en_e3() -> None:
    resultados, e3 = modelos(*_caso_basico())
    assert alinear(item_desde_dict(item(0, "difiere", cita_pdf="alfa uno")), resultados, e3) == 1
    assert alinear(item_desde_dict(item(1, "falta_en_excel", pagina=8, fila=None,
                                        cita_pdf="beta dos")), resultados, e3) == 0
    # Sin lado PDF propio: no hay hallazgo de E3 (la página adjudicada es de la contraparte).
    assert alinear(item_desde_dict(item(2, "extra_en_excel", pagina=99, fila=21)),
                   resultados, e3) is None


@pytest.mark.parametrize(("cambio", "mensaje"), [
    ({"estado": "coincide"}, "estado"),
    ({"pano": "C2"}, "paño"),
    ({"rele": "REL 2"}, "relé"),
    ({"pdf": {"pagina": 9, "cita": "alfa uno"}}, "página"),
    ({"excel": {"fila": 22, "cita": "x"}}, "fila"),
    ({"idx": 7}, "no existe"),
])
def test_alinear_falla_si_el_item_no_es_de_su_resultado(cambio: dict[str, Any],
                                                        mensaje: str) -> None:
    resultados, e3 = modelos(*_caso_basico())
    datos = {**item(0, "difiere", cita_pdf="alfa uno"), **cambio}
    with pytest.raises(AlineacionError, match=mensaje):
        alinear(item_desde_dict(datos), resultados, e3)


def test_alinear_acepta_la_pagina_que_cito_el_modelo_antes_del_reanclaje() -> None:
    # Reporte 0.7.0: la Etapa 3 movió la página 5 → 6; la adjudicación dice 5.
    h = pdf(6, pagina_citada=5)
    resultados, e3 = modelos([resultado("falta_en_excel", h)], [h])
    assert alinear(item_desde_dict(item(0, "falta_en_excel", pagina=5, fila=None)),
                   resultados, e3) == 0


def test_mapa_e3_reparte_en_orden_los_hallazgos_identicos() -> None:
    h = pdf(7)
    resultados, e3 = modelos(
        [resultado("coincide", h, excel(20)), resultado("coincide", h, excel(21))], [h, h])
    assert mapa_e3(resultados, e3) == {0: 0, 1: 1}


def test_hallazgo_del_reporte_que_no_esta_en_e3_falla() -> None:
    resultados, e3 = modelos([resultado("falta_en_excel", pdf(7))], [pdf(7, descripcion="otro")])
    with pytest.raises(AlineacionError, match="Etapa 3"):
        mapa_e3(resultados, e3)


def test_hallazgo_de_e3_que_no_llega_al_reporte_falla() -> None:
    h = pdf(7)
    resultados, e3 = modelos([resultado("falta_en_excel", h)], [h, pdf(8)])
    with pytest.raises(AlineacionError, match="Etapa 3"):
        mapa_e3(resultados, e3)


def test_alinear_todos_valida_cada_item(tmp_path: Path) -> None:
    resultados, e3 = modelos(*_caso_basico())
    ruta = tmp_path / "b2_sonnet_X.json"
    ruta.write_text(json.dumps({"informe": "S-E X (A)", "ronda": "B2", "run_id": "r",
                                "modelo": "m", "items": [
                                    item(0, "difiere", cita_pdf="alfa uno"),
                                    item(2, "extra_en_excel", fila=21)]}), encoding="utf-8")
    assert alinear_todos(cargar_adjudicacion(ruta), resultados, e3) == {0: 1, 2: None}


# ------------------------------------------------------------ claves y búsqueda


def test_clave_de_tupla_es_la_de_la_etapa_4() -> None:
    for pano, rele in [("C1", "SEL-787"), ("BT1-CT1", "sel 787"), ("ET_2", "Rel X")]:
        h = Hallazgo.model_validate(hallazgo(pano, rele, pagina=1))
        assert ClaveExcel.de(h.pano, h.rele, 1).tupla == e4._clave_tupla(h)


def test_normalizar_texto() -> None:
    assert normalizar_texto("  Ｆalla  DE\n fase ") == "falla de fase"


def test_claves_del_item_y_busqueda_unica() -> None:
    resultados, e3 = modelos(*_caso_basico())
    it = item_desde_dict(item(0, "difiere", cita_pdf="ALFA  uno"))
    claves = claves_del_item(it, resultados[0])
    assert claves.excel == ClaveExcel(tupla=("c1", "rel1"), fila=20)
    assert claves.pdf == ClavePdf(tupla=("c1", "rel1"), pagina=7, citas=("alfa uno",))
    assert buscar(claves, resultados).estado == "unico"
    assert buscar(claves, resultados).indices == (0,)


def test_busqueda_tolera_grafia_de_separadores_pero_no_otra_pagina() -> None:
    clave = ClavePdf(tupla=("c1", "rel1"), pagina=7, citas=("alfa",))
    otra_grafia = Hallazgo.model_validate(pdf(7, rele="REL-1", descripcion="Alfa beta"))
    assert clave.calza(otra_grafia)
    assert not clave.calza(Hallazgo.model_validate(pdf(8, descripcion="alfa")))
    assert not clave.calza(Hallazgo.model_validate(pdf(7, descripcion="gama", accion="beta")))
    # La clasificación no entra: cada modelo la rotula a su manera.
    assert clave.calza(Hallazgo.model_validate(pdf(7, descripcion="alfa", clasificacion="Otra")))
    # La cita también se busca en la acción y en el texto crudo de la evidencia.
    assert clave.calza(Hallazgo.model_validate(pdf(7, descripcion="x", accion="ALFA")))
    assert clave.calza(Hallazgo.model_validate(pdf(7, descripcion="x", accion=None,
                                                   crudo="... alfa ...")))


def test_busqueda_ninguno_y_ambiguo() -> None:
    p_a = pdf(7, descripcion="falla alfa uno")
    p_b = pdf(7, descripcion="falla alfa dos")
    resultados, _ = modelos([resultado("falta_en_excel", p_a),
                             resultado("falta_en_excel", p_b)], [p_a, p_b])
    def clave(cita: str) -> ClavePdf:
        return ClavePdf(tupla=("c1", "rel1"), pagina=7, citas=(cita,))
    from comparador.adjudicacion import Claves
    assert buscar(Claves(None, clave("alfa uno")), resultados).indices == (0,)
    ambiguo = buscar(Claves(None, clave("falla alfa")), resultados)
    assert (ambiguo.estado, ambiguo.indices) == ("ambiguo", (0, 1))
    assert buscar(Claves(None, clave("gama")), resultados).estado == "ninguno"


def test_campos_que_difieren_en_orden_canonico() -> None:
    r = MatchResult.model_validate(resultado("difiere", pdf(7), excel(20),
                                             campos=("calificacion", "descripcion")))
    assert campos_que_difieren(r) == (CampoDiferente.DESCRIPCION, CampoDiferente.CALIFICACION)
    assert r.estado == EstadoHallazgo.DIFIERE


def test_cita_con_vineta_calza_con_el_texto_crudo_partido_en_celdas() -> None:
    # La cita viene de la capa de texto del PDF; E3 separa las celdas con « | ».
    clave = ClavePdf.de("C1", "REL 1", 7, ["Criticidad menor • Se debe revisar."])
    h = Hallazgo.model_validate(pdf(7, descripcion="x", accion="se debe revisar",
                                    crudo="x | Criticidad menor | • Se debe revisar."))
    assert clave.calza(h)
    with pytest.raises(ValueError, match="sin cita"):
        ClavePdf.de("C1", "REL 1", 7, [" • "])
