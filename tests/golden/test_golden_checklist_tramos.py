"""Fusión de tramos del checklist sobre las respuestas reales de Beta (B2, sin API).

Beta (456 págs.) se evaluó en dos tramos. Las respuestas crudas de cada
tramo pasan por la fusión actual: el resultado de cada punto debe ser el que
guardó B2, y la evidencia (páginas y referencia) debe incluir la guardada.
Desde 0.7.0 la fusión une la evidencia de todos los tramos con el resultado
ganador; antes quedaba solo la del primero.

M08 (Bloque 24): sobre los 9 runs de Beta de B0-B2, la lectura por partes
marca o baja exactamente los puntos fijados, sin cambiar lo guardado en modo
«marcar».
"""

from __future__ import annotations

import re

import pytest

from comparador.etapa0_checklist import (
    _ChecklistResponse,
    _fusionar,
    cargar_puntos,
    checklist_desde_raw,
    visto_en_parte,
)
from comparador.evaluar_checklist import clasificar
from comparador.schemas import CausaAjuste, ChecklistInforme, ResultadoChecklist
from comparador.troceo import Tramo, a_paginas_absolutas
from tests.golden.datos import Caso, casos, ids, requiere_mediciones

pytestmark = [pytest.mark.golden, requiere_mediciones]

CASOS = [c for c in casos("b2") if c.tiene("checklist.json")
         and "llamadas" in c.json("checklist_raw/verificar_checklist.json")]


def _numeros(paginas: str | None) -> set[int]:
    return {int(n) for n in re.findall(r"\d+", paginas or "")}


def test_beta_es_el_informe_troceado() -> None:
    assert sorted({c.subestacion for c in CASOS}) == ["Beta"]
    assert len(CASOS) == 3


@pytest.mark.parametrize("caso", CASOS, ids=ids(CASOS))
def test_fusion_conserva_el_resultado_y_suma_la_evidencia(caso: Caso) -> None:
    raw = caso.json("checklist_raw/verificar_checklist.json")
    total = raw["troceo"]["total_paginas"]
    respuestas = []
    for llamada, tramo_info in zip(raw["llamadas"], raw["troceo"]["tramos"], strict=True):
        tramo = Tramo(*tramo_info["paginas"], total, "", None)
        respuesta = _ChecklistResponse.model_validate(llamada["response_raw"])
        for item in respuesta.items:
            item.paginas = a_paginas_absolutas(item.paginas, tramo)
        respuestas.append({i.numero: i for i in respuesta.items})

    guardados = {i["numero"]: i for i in caso.json("checklist.json")["items"]}
    sumaron_evidencia = 0
    for punto in cargar_puntos():
        item = _fusionar(respuestas, punto)
        guardado = guardados[punto["numero"]]
        assert item.resultado.value == guardado["resultado"], punto["numero"]
        assert _numeros(guardado["paginas"]) <= _numeros(item.paginas), punto["numero"]
        if guardado["referencia"]:
            assert guardado["referencia"].strip() in (item.referencia or ""), punto["numero"]
        sumaron_evidencia += _numeros(item.paginas) != _numeros(guardado["paginas"])
    # Hay puntos que cumplen en los dos tramos: la fusión suma la evidencia del segundo.
    assert sumaron_evidencia > 0


# --- M08: lectura por partes sobre los 9 runs de Beta (B0-B2, sin API) ---

CASOS_M08 = [c for c in casos("b0", "b1", "b2")
             if "llamadas" in c.json("checklist_raw/verificar_checklist.json")]

# Por run: los «cumple» que respalda una sola de las dos partes (k < N) y, de
# ellos, los de la lista que exige todo el informe (PD44): los que se bajan en
# modo «bajar». Calculados sin API con la simulación del Bloque 24 (2026-10-24).
VISTOS_Y_LISTA = {
    "b0-sonnet-Beta": ([4, 5, 8, 10, 12, 13, 14, 15, 16, 17, 18, 21, 24, 26, 30, 31, 32],
                         [8, 15, 17, 18, 21, 30, 31, 32]),
    "b0-opus-Beta": ([4, 5, 6, 8, 10, 12, 13, 14, 15, 16, 17, 18, 21, 30, 31, 32, 35],
                       [8, 15, 17, 18, 21, 30, 31, 32]),
    "b0-haiku-Beta": ([1, 4, 5, 10, 12, 14, 15, 16, 17, 18, 21, 24, 29, 30, 31, 37],
                        [15, 17, 18, 21, 30, 31]),
    "b1-sonnet-Beta": ([4, 5, 6, 8, 10, 12, 13, 14, 15, 16, 17, 18, 21, 30, 31, 32],
                         [8, 15, 17, 18, 21, 30, 31, 32]),
    "b1-opus-Beta": ([4, 5, 8, 12, 13, 14, 15, 16, 17, 18, 21, 30, 31, 32],
                       [8, 15, 17, 18, 21, 30, 31, 32]),
    "b1-haiku-Beta": ([5, 12, 13, 14, 15, 16, 17, 18, 21, 24, 32, 35, 37],
                        [15, 17, 18, 21, 32]),
    "b2-sonnet-Beta": ([4, 5, 6, 8, 12, 13, 14, 15, 16, 17, 18, 21, 22, 30, 31, 32],
                         [8, 15, 17, 18, 21, 30, 31, 32]),
    "b2-opus-Beta": ([4, 5, 6, 8, 12, 13, 14, 15, 16, 17, 18, 21, 30, 31, 32],
                       [8, 15, 17, 18, 21, 30, 31, 32]),
    "b2-haiku-Beta": ([4, 5, 12, 14, 15, 16, 17, 18, 21, 24, 30, 31, 32, 37],
                        [15, 17, 18, 21, 30, 31, 32]),
}


def test_m08_los_nueve_runs_de_beta_leidos_en_dos_partes() -> None:
    assert sorted(ids(CASOS_M08)) == sorted(VISTOS_Y_LISTA)
    assert sum(len(v) for v, _ in VISTOS_Y_LISTA.values()) == 138
    assert sum(len(lista) for _, lista in VISTOS_Y_LISTA.values()) == 66


def _desde_raw(caso: Caso, modo: str) -> ChecklistInforme:
    return checklist_desde_raw(caso.json("checklist_raw/verificar_checklist.json"),
                               cargar_puntos(), modo=modo)  # type: ignore[arg-type]


@pytest.mark.parametrize("caso", CASOS_M08, ids=ids(CASOS_M08))
def test_m08_marcar_avisa_en_los_vistos_sin_cambiar_lo_guardado(caso: Caso) -> None:
    vistos, _ = VISTOS_Y_LISTA[caso.id]
    cl = _desde_raw(caso, "marcar")
    guardados = {i["numero"]: i["resultado"] for i in caso.json("checklist.json")["items"]}
    assert {i.numero: i.resultado.value for i in cl.items} == guardados
    assert cl.tramos_leidos == [(1, 228), (229, 456)]
    assert [i.numero for i in cl.items if visto_en_parte(i, 2)] == vistos
    assert [i.numero for i in cl.items if i.aviso_tramos] == vistos
    assert (cl.marcados_un_tramo, cl.bajados_un_tramo) == (len(vistos), None)
    assert all(i.causa_ajuste is None and i.resultado_modelo is None for i in cl.items)


@pytest.mark.parametrize("caso", CASOS_M08, ids=ids(CASOS_M08))
def test_m08_bajar_quita_solo_los_de_la_lista(caso: Caso) -> None:
    vistos, lista = VISTOS_Y_LISTA[caso.id]
    cl = _desde_raw(caso, "bajar")
    bajados = [i for i in cl.items if i.causa_ajuste == CausaAjuste.UN_TRAMO]
    assert [i.numero for i in bajados] == lista
    assert all((i.resultado, i.resultado_modelo) == (
        ResultadoChecklist.NO_VERIFICABLE, ResultadoChecklist.CUMPLE) for i in bajados)
    assert (cl.marcados_un_tramo, cl.bajados_un_tramo) == (len(vistos) - len(lista), len(lista))
    guardados = {i["numero"]: i["resultado"] for i in caso.json("checklist.json")["items"]}
    assert {i.numero: i.resultado.value for i in cl.items if i.numero not in lista} == {
        n: r for n, r in guardados.items() if n not in lista}


def test_m08_aviso_y_motivo_nombran_la_parte_que_no_respalda() -> None:
    """B2 Opus, punto 30: lo respalda solo la primera parte."""
    (caso,) = [c for c in CASOS_M08 if c.id == "b2-opus-Beta"]
    marcar = {i.numero: i for i in _desde_raw(caso, "marcar").items}[30]
    assert marcar.tramos_respaldo == [1]
    assert marcar.aviso_tramos == (
        "Visto en 1 de 2 partes del informe (págs. 1-228); las págs. 229-456 no lo respaldan: "
        "revísalas antes de darlo por cumplido.")
    bajar = {i.numero: i for i in _desde_raw(caso, "bajar").items}[30]
    assert bajar.motivo_ajuste == (
        "El informe se leyó en partes por su longitud; este punto exige revisar todo el "
        "informe: revisa las páginas 229-456.")


def test_m08_b2_opus_pierde_7_aciertos_en_modo_bajar() -> None:
    """28 → 21 de 33 aciertos (planilla al medir): los 7 de la lista con planilla eran SI."""
    (caso,) = [c for c in CASOS_M08 if c.id == "b2-opus-Beta"]
    gt = {i["numero"]: i["veredicto_gt"] for i in caso.fila["checklist_gt"]["items"]}

    def aciertos(cl: ChecklistInforme) -> int:
        return sum(1 for i in cl.items if i.numero in gt
                   and clasificar(i.resultado, gt[i.numero]) == "acierto")

    assert (len(gt), caso.fila["checklist_gt"]["aciertos"]) == (33, 28)
    assert (aciertos(_desde_raw(caso, "marcar")), aciertos(_desde_raw(caso, "bajar"))) == (28, 21)
