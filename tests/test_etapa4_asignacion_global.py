"""Asignación global del emparejamiento de E4 (ASIGNACION_GLOBAL, 2026-10-18).

Sin API: el juez es una tabla de puntajes (hallazgo del PDF, fila del Excel) →
confianza 0-99 que elige el mejor candidato de los que se le ofrecen, y los
embeddings son one-hot (texto igual → similitud 1, distinto → 0). Los tres
casos son los malos emparejamientos por orden que encontró la adjudicación de
B2 (docs/05 fila 4.6): con el interruptor se arreglan; sin él, se reproducen.
"""

from __future__ import annotations

import itertools
import json
import math
import re
from typing import Any

import numpy as np
import pytest

from comparador import etapa4_matching
from comparador.config import PROJECT_ROOT, Settings, settings
from comparador.etapa4_matching import (
    JuezInvalidoError,
    _JuezRedaccionResponse,
    _JuezResponse,
    _VeredictoRedaccion,
    ejecutar_matching,
)
from comparador.schemas import (
    Calificacion,
    CampoDiferente,
    EstadoHallazgo,
    Evidencia,
    FuenteEvidencia,
    Hallazgo,
    MatchResult,
    TipoMatch,
)

CLASIF = "Verificación DUF"   # la misma en todos: la unicidad (4a) no aplica


def _h(descripcion: str, fuente: FuenteEvidencia = FuenteEvidencia.PDF, fila: int | None = None,
       calificacion: Calificacion = Calificacion.MENOR, accion: str = "Acción",
       pagina: int | None = None) -> Hallazgo:
    return Hallazgo(
        pano="C2", rele="SEL 351R", clasificacion=CLASIF, descripcion=descripcion,
        accion_correctiva=accion, calificacion=calificacion,
        evidencia=Evidencia(fuente=fuente, fila_excel=fila, pagina_pdf=pagina,
                            texto_crudo=descripcion),
    )


def _excel(descripcion: str, fila: int, **kw: Any) -> Hallazgo:
    return _h(descripcion, FuenteEvidencia.EXCEL, fila, **kw)


class JuezPorTabla:
    """Elige el candidato con más puntaje (empate: el primero); null bajo 50."""

    def __init__(self, puntajes: dict[tuple[str, str], int]) -> None:
        self.puntajes = puntajes
        self.llamadas: list[tuple[str, list[str]]] = []

    def __call__(self, **kw: Any) -> tuple[_JuezResponse, dict[str, Any]]:
        prompt = kw["user_prompt"]
        m = re.search(r'Hallazgo del PDF:\n  "(.*)"\n', prompt)
        assert m is not None
        pdf = m.group(1)
        candidatos = [c for _, c in re.findall(r"^  \[(\d+)\] (.*)$", prompt, flags=re.M)]
        self.llamadas.append((pdf, candidatos))
        orden = sorted(range(len(candidatos)),
                       key=lambda i: (-self.puntajes.get((pdf, candidatos[i]), 0), i))
        mejor = orden[0] if orden else None
        puntaje = self.puntajes.get((pdf, candidatos[mejor]), 0) if mejor is not None else 0
        if mejor is None or puntaje < 50:
            return _JuezResponse(indice_candidato=None, confianza=puntaje,
                                 justificacion="Ningún candidato describe el mismo hallazgo."), {}
        return _JuezResponse(indice_candidato=mejor, confianza=puntaje,
                             justificacion=f"Es «{candidatos[mejor]}»."), {"tokens_total": 7}


@pytest.fixture(autouse=True)
def entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "juez_redaccion", False)
    monkeypatch.setattr(settings, "top_k_candidatos", 5)

    def _calcular(textos: list[str]) -> tuple[np.ndarray[Any, Any], None]:
        unicos = list(dict.fromkeys(textos))
        matriz = np.zeros((len(textos), max(len(unicos), 1)))
        for i, t in enumerate(textos):
            matriz[i, unicos.index(t)] = 1.0
        return matriz, None

    monkeypatch.setattr(etapa4_matching, "calcular_embeddings", _calcular)


def _correr(pdf: list[Hallazgo], excel: list[Hallazgo], juez: JuezPorTabla, global_: bool,
            monkeypatch: pytest.MonkeyPatch) -> tuple[list[MatchResult], list[dict[str, Any]]]:
    monkeypatch.setattr(settings, "asignacion_global", global_)
    monkeypatch.setattr(etapa4_matching, "llamar_llm_estructurado", juez)
    return ejecutar_matching(pdf, excel)


def _por_pdf(resultados: list[MatchResult]) -> dict[str, MatchResult]:
    return {r.hallazgo_pdf.descripcion: r for r in resultados if r.hallazgo_pdf}


# --- Los tres casos de B2 ---------------------------------------------------

DUS, DUF = "Diagrama Unilineal Simplificado: No enviado", "Diagrama Unilineal Funcional: no enviado"
FILA_DUF, FILA_ECAP = "DUF no enviado por el coordinado", "ECAP no corresponde"


def _gamma() -> tuple[list[Hallazgo], list[Hallazgo], JuezPorTabla]:
    """Gamma, Sonnet, C2/SEL 351R: el DUS llega primero y toma la fila del DUF."""
    pdf = [_h(DUS), _h(DUF)]
    excel = [_excel(FILA_DUF, 24), _excel(FILA_ECAP, 25)]
    juez = JuezPorTabla({(DUS, FILA_DUF): 62, (DUF, FILA_DUF): 88,
                         (DUS, FILA_ECAP): 20, (DUF, FILA_ECAP): 8})
    return pdf, excel, juez


class TestCasosDeB2:
    def test_gamma_sin_interruptor_reproduce_el_falso_falta(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        pdf, excel, juez = _gamma()
        res = _por_pdf(_correr(pdf, excel, juez, False, monkeypatch)[0])
        assert res[DUS].hallazgo_excel and res[DUS].hallazgo_excel.descripcion == FILA_DUF
        assert res[DUF].estado == EstadoHallazgo.FALTA_EN_EXCEL

    def test_gamma_con_interruptor_el_duf_se_queda_su_fila(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        pdf, excel, juez = _gamma()
        resultados, metas = _correr(pdf, excel, juez, True, monkeypatch)
        res = _por_pdf(resultados)

        assert res[DUF].hallazgo_excel and res[DUF].hallazgo_excel.descripcion == FILA_DUF
        assert (res[DUF].tipo_match, res[DUF].confianza) == (TipoMatch.SEMANTICO_ALTO, 0.88)
        dus = res[DUS]
        assert dus.estado == EstadoHallazgo.FALTA_EN_EXCEL
        assert dus.justificacion.startswith(
            "Perdió la fila 24 del Excel frente a otro hallazgo del PDF al que el juez dio "
            "más confianza (0.88 contra 0.62); entre las filas restantes, el juez: Ningún")
        # 3 consultas: DUS (toma 24), DUF (la desplaza), DUS de nuevo sin la 24.
        assert [p for p, _ in juez.llamadas] == [DUS, DUF, DUS]
        assert FILA_DUF not in juez.llamadas[2][1]
        trazas = [m["asignacion_global"] for m in metas if "asignacion_global" in m]
        assert [(t["resultado"], t["reintento"]) for t in trazas] == [
            ("tomo_fila_libre", False), ("desplazo", False), ("sin_match", True)]
        assert trazas[1]["frente_a"] == {"orden_pdf": 0, "confianza": 0.62}
        assert trazas[2]["filas_perdidas"] == [24]
        # orden_pdf es la posición dentro de la tupla: cada traza dice de cuál es
        # (en Alfa, 17 descripciones de E3 se repiten en más de una tupla; PD23).
        assert {(t["pano"], t["rele"]) for t in trazas} == {("C2", "SEL 351R")}
        # La fila del ECAP quedó libre: extra.
        extras = [r for r in resultados if r.estado == EstadoHallazgo.EXTRA_EN_EXCEL]
        assert [r.hallazgo_excel.descripcion for r in extras if r.hallazgo_excel] == [FILA_ECAP]

    def test_alfa_ct1b_el_hallazgo_inventado_queda_sin_fila(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        inventado, real = "Tiempos de actuación. No cumple", "Simulación DIgSILENT: no cumple"
        fila = "Simulación en DIgSILENT no cumple"
        juez = JuezPorTabla({(inventado, fila): 55, (real, fila): 90})
        pdf, excel = [_h(inventado), _h(real)], [_excel(fila, 81)]

        # Sin el interruptor se reproduce el error de B2: el inventado toma la
        # fila y el real queda sin candidatos.
        sin = _por_pdf(_correr(pdf, excel, JuezPorTabla(juez.puntajes), False, monkeypatch)[0])
        assert sin[inventado].hallazgo_excel is not None
        assert sin[real].estado == EstadoHallazgo.FALTA_EN_EXCEL
        assert sin[real].justificacion == "Sin candidatos disponibles en Excel."

        resultados, _ = _correr(pdf, excel, juez, True, monkeypatch)
        res = _por_pdf(resultados)
        assert res[real].hallazgo_excel is not None
        assert res[inventado].justificacion == (
            "Perdió la fila 81 del Excel frente a otro hallazgo del PDF al que el juez dio más "
            "confianza (0.90 contra 0.55); no quedan otras filas candidatas.")
        assert len(juez.llamadas) == 2

    def test_alfa_ht2_aparece_el_error_de_calificacion(self, monkeypatch: pytest.MonkeyPatch):
        # Opus, fila 107: el hallazgo con el mismo texto (calificación distinta)
        # quedaba "sin candidatos"; ahora se empareja y el error se ve.
        otro, mismo = "Coordinación de protecciones: No cumple", "Verificación ECAP: No cumple"
        excel = [_excel(mismo, 107, calificacion=Calificacion.RELEVANTE)]
        juez = JuezPorTabla({(otro, mismo): 66, (mismo, mismo): 95})
        pdf = [_h(otro), _h(mismo)]

        sin = _por_pdf(_correr(pdf, excel, juez, False, monkeypatch)[0])
        assert sin[mismo].estado == EstadoHallazgo.FALTA_EN_EXCEL

        con = _por_pdf(_correr(pdf, excel, JuezPorTabla(juez.puntajes), True, monkeypatch)[0])
        assert con[mismo].estado == EstadoHallazgo.DIFIERE
        assert [d.campo for d in con[mismo].diferencias] == [CampoDiferente.CALIFICACION]
        assert con[otro].estado == EstadoHallazgo.FALTA_EN_EXCEL


# --- Mecánica ---------------------------------------------------------------

class TestMecanica:
    def test_empate_se_queda_el_que_la_tenia(self, monkeypatch: pytest.MonkeyPatch):
        a, b, fila = "Hallazgo A", "Hallazgo B", "Fila única"
        juez = JuezPorTabla({(a, fila): 80, (b, fila): 80})
        res = _por_pdf(_correr([_h(a), _h(b)], [_excel(fila, 10)], juez, True, monkeypatch)[0])
        assert res[a].hallazgo_excel is not None
        assert res[b].estado == EstadoHallazgo.FALTA_EN_EXCEL
        # La nota dice la verdad: fue un empate, no "más confianza".
        assert res[b].justificacion == (
            "Perdió la fila 10 del Excel frente a otro hallazgo del PDF al que el juez dio la "
            "misma confianza (0.80); en un empate se queda el que ya tenía la fila; no quedan "
            "otras filas candidatas.")

    def test_empate_y_segunda_opcion_lo_dice_en_el_par(self, monkeypatch: pytest.MonkeyPatch):
        a, b, f1, f2 = "Hallazgo A", "Hallazgo B", "Fila uno", "Fila dos"
        juez = JuezPorTabla({(a, f1): 80, (b, f1): 80, (b, f2): 60})
        res = _por_pdf(_correr([_h(a), _h(b)], [_excel(f1, 1), _excel(f2, 2)], juez, True,
                               monkeypatch)[0])
        assert res[b].hallazgo_excel and res[b].hallazgo_excel.descripcion == f2
        assert res[b].justificacion.endswith(
            "(Asignación global: antes perdió la fila 1 del Excel frente a otro hallazgo al que "
            "el juez dio la misma confianza (0.80); en un empate se queda el que ya tenía la "
            "fila.)")
        assert "más confianza" not in res[b].justificacion

    def test_rechazado_toma_su_segunda_opcion(self, monkeypatch: pytest.MonkeyPatch):
        a, b, f1, f2 = "Hallazgo A", "Hallazgo B", "Fila uno", "Fila dos"
        juez = JuezPorTabla({(a, f1): 90, (b, f1): 70, (b, f2): 60})
        res = _por_pdf(_correr([_h(a), _h(b)], [_excel(f1, 1), _excel(f2, 2)], juez, True,
                               monkeypatch)[0])
        assert res[b].hallazgo_excel and res[b].hallazgo_excel.descripcion == f2
        assert res[b].tipo_match == TipoMatch.SEMANTICO_BAJO
        assert res[b].justificacion.endswith(
            "(Asignación global: antes perdió la fila 1 del Excel frente a otro hallazgo al que "
            "el juez dio más confianza (0.90 contra 0.70).)")

    def test_cadena_de_desplazamientos(self, monkeypatch: pytest.MonkeyPatch):
        a, b, c, f1, f2 = "Hallazgo A", "Hallazgo B", "Hallazgo C", "Fila uno", "Fila dos"
        juez = JuezPorTabla({(a, f1): 60, (b, f1): 70, (a, f2): 65, (c, f2): 80})
        res = _por_pdf(_correr([_h(a), _h(b), _h(c)], [_excel(f1, 1), _excel(f2, 2)], juez,
                               True, monkeypatch)[0])
        assert res[b].hallazgo_excel and res[b].hallazgo_excel.descripcion == f1
        assert res[c].hallazgo_excel and res[c].hallazgo_excel.descripcion == f2
        assert res[a].estado == EstadoHallazgo.FALTA_EN_EXCEL
        assert res[a].justificacion.count("Perdió") == 2

    def test_juez_que_siempre_elige_el_primero_termina(self, monkeypatch: pytest.MonkeyPatch):
        n, m = 6, 4
        pdf = [_h(f"Hallazgo {i}") for i in range(n)]
        excel = [_excel(f"Fila {j}", j + 1) for j in range(m)]
        juez = JuezPorTabla({(p.descripcion, e.descripcion): 90 for p in pdf for e in excel})
        resultados, _ = _correr(pdf, excel, juez, True, monkeypatch)
        estados = [r.estado for r in resultados if r.hallazgo_pdf]
        assert estados.count(EstadoHallazgo.FALTA_EN_EXCEL) == n - m
        assert len({r.hallazgo_excel.descripcion for r in resultados
                    if r.hallazgo_pdf and r.hallazgo_excel}) == m   # cada fila una vez
        assert len(juez.llamadas) <= n + m + n * m

    def test_sin_conflictos_mismos_resultados_y_consultas(self, monkeypatch: pytest.MonkeyPatch):
        a, b, f1, f2 = "Hallazgo A", "Hallazgo B", "Fila uno", "Fila dos"
        puntajes = {(a, f1): 90, (b, f2): 85}
        pdf, excel = [_h(a), _h(b)], [_excel(f1, 1), _excel(f2, 2)]
        sin, _ = _correr(pdf, excel, (j1 := JuezPorTabla(puntajes)), False, monkeypatch)
        con, _ = _correr(pdf, excel, (j2 := JuezPorTabla(puntajes)), True, monkeypatch)
        assert [r.model_dump() for r in sin] == [r.model_dump() for r in con]
        # Mismas consultas en cantidad; con el interruptor B también ve la fila que
        # tiene A (así podría disputarla si le diera más confianza).
        assert len(j1.llamadas) == len(j2.llamadas) == 2
        assert j2.llamadas[1] == (b, [f1, f2])

    def test_el_orden_de_extraccion_ya_no_decide(self, monkeypatch: pytest.MonkeyPatch):
        pdf, excel, juez = _gamma()

        def pares(orden: tuple[Hallazgo, ...], global_: bool) -> set[tuple[str, str]]:
            res, _ = _correr(list(orden), excel, JuezPorTabla(juez.puntajes), global_, monkeypatch)
            return {(r.hallazgo_pdf.descripcion, r.hallazgo_excel.descripcion)
                    for r in res if r.hallazgo_pdf and r.hallazgo_excel}

        con = {frozenset(pares(o, True)) for o in itertools.permutations(pdf)}
        sin = {frozenset(pares(o, False)) for o in itertools.permutations(pdf)}
        assert len(con) == 1 and len(sin) == 2

    def test_inanicion_del_top_k(self, monkeypatch: pytest.MonkeyPatch):
        # Más filas que k y un juez selectivo (solo Hi↔Fi): H5 ve primero F0..F4,
        # todas de otros, las rechaza y vuelve a consultar sin ellas. Sin el
        # reintento quedaba en falta sin haber visto nunca su fila libre.
        n = 6
        pdf = [_h(f"Hallazgo {i}") for i in range(n)]
        excel = [_excel(f"Fila {j}", j + 1) for j in range(n)]
        juez = JuezPorTabla({(f"Hallazgo {i}", f"Fila {i}"): 90 for i in range(n)})

        resultados, metas = _correr(pdf, excel, juez, True, monkeypatch)

        res = _por_pdf(resultados)
        assert all(res[f"Hallazgo {i}"].hallazgo_excel.descripcion == f"Fila {i}"  # type: ignore[union-attr]
                   for i in range(n))
        trazas = [m["asignacion_global"] for m in metas if "asignacion_global" in m]
        h5 = [t for t in trazas if t["orden_pdf"] == 5]
        assert [t["resultado"] for t in h5] == ["sin_match_reintenta", "tomo_fila_libre"]
        assert h5[0]["filas_ajenas"] == [1, 2, 3, 4, 5] and h5[1]["reintento"]
        assert etapa4_matching.contar_reintentos(metas) == 1
        # Como en el modo en orden, que le muestra solo las filas libres.
        en_orden = _por_pdf(_correr(pdf, excel, JuezPorTabla(juez.puntajes), False,
                                    monkeypatch)[0])
        assert en_orden["Hallazgo 5"].hallazgo_excel == res["Hallazgo 5"].hallazgo_excel

    def test_falta_real_con_candidatas_ajenas_no_reintenta(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # La única fila ya es de otro y no queda ninguna libre: una sola consulta,
        # con la respuesta del juez (no «sin candidatos»).
        a, falta, fila = "Ajuste de la curva no cumple", "Registro no enviado", "Ajuste: no cumple"
        juez = JuezPorTabla({(a, fila): 90})
        resultados, metas = _correr([_h(a), _h(falta)], [_excel(fila, 10)], juez, True,
                                    monkeypatch)
        res = _por_pdf(resultados)
        assert res[falta].estado == EstadoHallazgo.FALTA_EN_EXCEL
        assert res[falta].justificacion == "Ningún candidato describe el mismo hallazgo."
        assert [pdf for pdf, _ in juez.llamadas].count(falta) == 1
        assert etapa4_matching.contar_reintentos(metas) == 0

    def test_el_reintento_no_ve_filas_que_tomo_un_hallazgo_anterior(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # A toma F1; B pide F1 con menos confianza y vuelve a la cola detrás de X;
        # X rechaza su top-5 (con F1 ajena) y reintenta acotado; B toma «b»
        # antes del reintento de X. Si el reintento siguiera viendo «b», el top-5
        # dejaría afuera a «xr» y X quedaría en falta, peor que en orden.
        pdf = [_h("A"), _h("B"), _h("X")]
        excel = [_excel(d, f) for f, d in enumerate(
            ["F1", "b", "p1", "p2", "p3", "p4", "xr"], start=1)]
        puntajes = {("A", "F1"): 90, ("B", "F1"): 85, ("B", "b"): 60, ("X", "xr"): 90}

        con = _por_pdf(_correr(pdf, excel, JuezPorTabla(puntajes), True, monkeypatch)[0])
        en_orden = _por_pdf(_correr(pdf, excel, JuezPorTabla(puntajes), False, monkeypatch)[0])

        assert con["X"].hallazgo_excel and con["X"].hallazgo_excel.descripcion == "xr"
        assert en_orden["X"].hallazgo_excel == con["X"].hallazgo_excel

    def test_el_reintento_no_recorre_la_tupla(self, monkeypatch: pytest.MonkeyPatch):
        # Una falta real (X) en una tupla grande: con el top-5 inicial ve una fila
        # ajena y reintenta UNA vez, acotado (sin las filas de hallazgos
        # anteriores), y queda en falta. Ve como mucho k filas más que el modo
        # en orden, nunca las 15 de la tupla.
        pdf = [_h("H0"), _h("X"), *[_h(f"H{i}") for i in range(1, 10)]]
        excel = [*[_excel(f"F{i}", i + 1) for i in range(10)],
                 *[_excel(f"G{i}", 20 + i) for i in range(5)]]
        juez = JuezPorTabla({(f"H{i}", f"F{i}"): 90 for i in range(10)})

        resultados, _ = _correr(pdf, excel, juez, True, monkeypatch)

        vistas_x = [c for p, cs in juez.llamadas if p == "X" for c in cs]
        assert len([p for p, _ in juez.llamadas if p == "X"]) == 2
        assert set(vistas_x) <= {f"F{i}" for i in range(6)}
        assert _por_pdf(resultados)["X"].estado == EstadoHallazgo.FALTA_EN_EXCEL

    def test_falta_real_no_recorre_las_filas(self, monkeypatch: pytest.MonkeyPatch):
        # Un hallazgo sin par cuyo top-k es todo de filas libres no reintenta.
        juez = JuezPorTabla({})
        resultados, metas = _correr([_h("Sin par")], [_excel(f"Fila {j}", j + 1)
                                                      for j in range(8)],
                                    juez, True, monkeypatch)
        assert _por_pdf(resultados)["Sin par"].estado == EstadoHallazgo.FALTA_EN_EXCEL
        assert len(juez.llamadas) == 1

    def test_la_nota_sigue_a_la_fila_final_despues_del_desempate(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # Patrón Beta: descripciones idénticas y acciones distintas. La
        # asignación global hace perder la fila 1 (empate) al segundo hallazgo;
        # el desempate por acción se la devuelve: la nota no debe decir que
        # perdió la fila con la que quedó (ni pasar a otro hallazgo).
        d = "Verificación ECAP: no cumple"
        pdf = [_h(d, accion="Disponer ECAP"), _h(d, accion="Cargar Print Out")]
        excel = [_excel(d, 1, accion="Cargar Print Out"), _excel(d, 2, accion="Disponer ECAP")]

        resultados, _ = _correr(pdf, excel, JuezPorTabla({(d, d): 80}), True, monkeypatch)

        por_accion = {r.hallazgo_pdf.accion_correctiva: r for r in resultados if r.hallazgo_pdf}
        assert por_accion["Cargar Print Out"].hallazgo_excel.evidencia.fila_excel == 1  # type: ignore[union-attr]
        assert por_accion["Disponer ECAP"].hallazgo_excel.evidencia.fila_excel == 2  # type: ignore[union-attr]
        assert all("Asignación global" not in r.justificacion for r in resultados)

    def test_confianzas_fraccionarias_se_ven_distintas(self):
        assert etapa4_matching._frente_a(0.80, 0.804) == (
            "al que el juez dio más confianza (0.804 contra 0.800)")
        assert etapa4_matching._frente_a(0.62, 0.88) == (
            "al que el juez dio más confianza (0.88 contra 0.62)")

    def test_indice_invalido_sigue_lanzando_con_la_traza(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "asignacion_global", True)
        monkeypatch.setattr(etapa4_matching, "llamar_llm_estructurado", lambda **kw: (
            _JuezResponse(indice_candidato=7, confianza=90, justificacion="x"), {"t": 1}))
        with pytest.raises(JuezInvalidoError) as info:
            ejecutar_matching([_h("A"), _h("B")], [_excel("F1", 1), _excel("F2", 2)])
        assert any("asignacion_global" in m for m in info.value.llm_metadata)


# --- PD71 V2: 19e(c) para el par que termina con una fila que perdió un hallazgo
# de polaridad opuesta a la fila (decisión del usuario 2026-10-25) --------------
# La marca es de la fila, no del par que la ganó: la lleva quien la tenga al final,
# la haya perdido el hallazgo opuesto por desplazamiento o por rechazo, así que no
# depende del orden de E3 (18b) ni de cuántas veces cambie de manos. Desde el schema
# 0.9.0 el par la lleva en `emparejamiento_dudoso`, con el motivo, y se trata como un
# semantico_bajo: el detalle de sus diferencias es el de siempre.

# Alfa Opus, tupla (E7, SEL 451) en AG1: el «Cumple» toma la fila 69 (que el
# Excel invierte a «No cumple») con 0,57; el «no ajustado» pierde la 68 (0,97 de
# otro) y en el reintento le quita la 69 al «Cumple» con 0,80; el «Cumple» queda en
# falta (0,30). Los embeddings son one-hot: las dos descripciones del par nuevo
# quedan bajo el umbral (similitud 0) y la acción es idéntica (no se compara).
E7_CUMPLE = ("Comparación con ECAP adjunto en INFOTÉCNICA: Cumple. Si bien se encuentra ECAP "
             "en infotecnica, no se mencionan los ajustes de la función 79 para el paño E7.")
E7_NO_AJUSTADO = "El equipo no se encuentra ajustado de acuerdo con lo descrito en el ECAP"
E7_OTRO = "Diagrama unilineal sin la función 79"
FILA_68, FILA_69 = "DUF sin la función 79", "Comparación con ECAP adjunto en INFOTÉCNICA: No cumple"
PAGINA_CUMPLE = 12
# El motivo empieza por lo que hay que hacer, dice dónde está el «Cumple» y cuál es
# (el comienzo de su descripción: en su página puede haber otros hallazgos de la
# tupla) y termina con la consecuencia (PD72, redacción provisoria del 2026-10-26).
MOTIVO_E7 = (
    "Revisar a qué hallazgo corresponde esta fila. El Excel dice que no cumple, pero en la "
    "pág. 12 hay otro hallazgo del PDF que dice que cumple (descripción «Comparación con ECAP "
    "adjunto en INFOTÉCNICA: Cumple. Si bien se encuentra ECAP…») y que también podría ser el "
    "de esta fila. Si es ese, el Excel invirtió el veredicto.")
BAJO_EL_UMBRAL = "Similitud semántica 0.00, bajo el umbral de coincidencia 0.85"


Puntajes = dict[tuple[str, str], int]


def _e7(dueno: str = E7_CUMPLE) -> tuple[list[Hallazgo], list[Hallazgo], Puntajes]:
    pdf = [_h(E7_OTRO), _h(dueno, pagina=PAGINA_CUMPLE), _h(E7_NO_AJUSTADO)]
    excel = [_excel(FILA_68, 68), _excel(FILA_69, 69)]
    puntajes = {(E7_OTRO, FILA_68): 97, (dueno, FILA_69): 57, (dueno, FILA_68): 30,
                (E7_NO_AJUSTADO, FILA_68): 90, (E7_NO_AJUSTADO, FILA_69): 80}
    return pdf, excel, puntajes


class JuecesConRedaccion(JuezPorTabla):
    """El juez de matching por tabla y un juez de redacción permisivo: todo ítem
    que le llega es «mismo contenido», como el de AG1 con la fila 69. Lo que
    llegue a él puede esconder la inversión; lo que no, queda a la vista."""

    def __init__(self, puntajes: dict[tuple[str, str], int]) -> None:
        super().__init__(puntajes)
        self.lotes: list[list[dict[str, Any]]] = []

    def __call__(self, **kw: Any) -> tuple[Any, dict[str, Any]]:
        if kw["response_model"] is not _JuezRedaccionResponse:
            return super().__call__(**kw)
        items = json.loads(kw["user_prompt"])
        self.lotes.append(items)
        return _JuezRedaccionResponse(veredictos=[
            _VeredictoRedaccion(id=it["id"], justificacion="Mismo contenido.",
                                mismo_contenido=True) for it in items]), {"tokens_total": 9}

    def textos_excel_juzgados(self) -> list[str]:
        return [it["texto_excel"] for lote in self.lotes for it in lote]


@pytest.fixture
def con_redaccion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "juez_redaccion", True)
    monkeypatch.setattr(settings, "threshold_descripcion", 0.85)
    monkeypatch.setattr(settings, "threshold_accion", 0.85)
    # El prompt real es texto + JSON; el juez falso recibe solo el JSON de los ítems.
    monkeypatch.setattr(etapa4_matching, "user_juez_redaccion", json.dumps)


def _trazas(metas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m["asignacion_global"] for m in metas if "asignacion_global" in m]


def _perdidas(metas: list[dict[str, Any]]) -> list[tuple[int, str, bool]]:
    """(hallazgo, desplazo/rechazado, si el que perdió la fila es de polaridad opuesta)."""
    return [(t["orden_pdf"], t["resultado"], t["perdedor_polaridad_opuesta"])
            for t in _trazas(metas) if "frente_a" in t]


@pytest.mark.usefixtures("con_redaccion")
class TestDudosoPorFilaDisputada:
    def test_e7_el_par_que_desplazo_al_cumple_difiere_sin_juez(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        pdf, excel, puntajes = _e7()
        juez = JuecesConRedaccion(puntajes)
        resultados, metas = _correr(pdf, excel, juez, True, monkeypatch)
        res = _por_pdf(resultados)

        par = res[E7_NO_AJUSTADO]
        assert par.hallazgo_excel and par.hallazgo_excel.evidencia.fila_excel == 69
        assert (par.tipo_match, par.confianza) == (TipoMatch.SEMANTICO_ALTO, 0.80)
        assert par.estado == EstadoHallazgo.DIFIERE
        assert par.equivalencias_redaccion == []
        # Como un semantico_bajo: la diferencia de 4c, y el motivo en el par.
        assert [(d.campo, d.detalle) for d in par.diferencias] == [
            (CampoDiferente.DESCRIPCION, BAJO_EL_UMBRAL)]
        assert par.emparejamiento_dudoso == MOTIVO_E7
        assert par.emparejamiento_es_dudoso
        # La fila 69 no llega al juez de redacción; el otro par sí (como siempre).
        assert juez.textos_excel_juzgados() == [FILA_68]
        assert res[E7_OTRO].estado == EstadoHallazgo.COINCIDE
        assert res[E7_OTRO].emparejamiento_dudoso is None
        # El «Cumple» desplazado queda a la vista como falta, con la nota de siempre.
        assert res[E7_CUMPLE].estado == EstadoHallazgo.FALTA_EN_EXCEL
        assert res[E7_CUMPLE].emparejamiento_dudoso is None
        assert res[E7_CUMPLE].justificacion.startswith(
            "Perdió la fila 69 del Excel frente a otro hallazgo del PDF al que el juez dio más "
            "confianza (0.80 contra 0.57)")

    def test_la_traza_registra_el_motivo(self, monkeypatch: pytest.MonkeyPatch):
        pdf, excel, puntajes = _e7()
        _, metas = _correr(pdf, excel, JuecesConRedaccion(puntajes), True, monkeypatch)
        trazas = _trazas(metas)
        assert [(t["orden_pdf"], t["resultado"]) for t in trazas] == [
            (0, "tomo_fila_libre"), (1, "tomo_fila_libre"), (2, "rechazado"), (2, "desplazo"),
            (1, "sin_match")]
        assert trazas[3]["frente_a"] == {"orden_pdf": 1, "confianza": 0.57}
        # Cada consulta en que alguien pierde una fila (desplazado o rechazado) dice si
        # quien la perdió es de polaridad opuesta a ella; las demás no llevan la clave.
        assert _perdidas(metas) == [(2, "rechazado", False), (2, "desplazo", True)]
        assert all("perdedor_polaridad_opuesta" not in t for t in trazas if "frente_a" not in t)

    @pytest.mark.parametrize("cumple_primero", [True, False],
                             ids=["cumple-primero", "cumple-despues"])
    def test_no_depende_del_orden_de_e3(self, cumple_primero: bool,
                                        monkeypatch: pytest.MonkeyPatch):
        # Mismos hallazgos, misma fila y mismas confianzas; solo cambia el orden de E3.
        # Primero el «Cumple»: toma la 69 libre y el «no ajustado» se la quita. Después:
        # el «no ajustado» la toma libre y al «Cumple» le rechazan el pedido. El par final
        # es el mismo, y en los dos la fila la perdió un hallazgo de polaridad opuesta.
        pdf = [_h(E7_CUMPLE, pagina=PAGINA_CUMPLE), _h(E7_NO_AJUSTADO)]
        if not cumple_primero:
            pdf.reverse()
        juez = JuecesConRedaccion({(E7_NO_AJUSTADO, FILA_69): 85, (E7_CUMPLE, FILA_69): 57})
        resultados, metas = _correr(pdf, [_excel(FILA_69, 69)], juez, True, monkeypatch)
        res = _por_pdf(resultados)

        par = res[E7_NO_AJUSTADO]
        assert par.hallazgo_excel and par.hallazgo_excel.evidencia.fila_excel == 69
        assert par.confianza == 0.85
        assert par.estado == EstadoHallazgo.DIFIERE
        assert par.equivalencias_redaccion == []
        assert [(d.campo, d.detalle) for d in par.diferencias] == [
            (CampoDiferente.DESCRIPCION, BAJO_EL_UMBRAL)]
        assert par.emparejamiento_dudoso == MOTIVO_E7
        assert juez.textos_excel_juzgados() == []
        assert res[E7_CUMPLE].estado == EstadoHallazgo.FALTA_EN_EXCEL
        assert _perdidas(metas) == (
            [(1, "desplazo", True)] if cumple_primero else [(1, "rechazado", True)])

    @pytest.mark.parametrize("dueno", [
        "Comparación con ECAP adjunto en INFOTÉCNICA: faltan los ajustes de la función 79",
        "Comparación con ECAP adjunto en INFOTÉCNICA: No cumple. Faltan los ajustes de la 79",
    ], ids=["dueno-sin-polaridad", "dueno-misma-polaridad"])
    def test_desplazamiento_sin_polaridad_opuesta_sigue_al_juez(
        self, dueno: str, monkeypatch: pytest.MonkeyPatch
    ):
        pdf, excel, puntajes = _e7(dueno)
        juez = JuecesConRedaccion(puntajes)
        resultados, metas = _correr(pdf, excel, juez, True, monkeypatch)

        par = _por_pdf(resultados)[E7_NO_AJUSTADO]
        assert par.hallazgo_excel and par.hallazgo_excel.evidencia.fila_excel == 69
        assert par.estado == EstadoHallazgo.COINCIDE
        assert [e.campo for e in par.equivalencias_redaccion] == [CampoDiferente.DESCRIPCION]
        assert all(r.emparejamiento_dudoso is None for r in resultados)
        assert sorted(juez.textos_excel_juzgados()) == sorted([FILA_68, FILA_69])
        assert _perdidas(metas) == [(2, "rechazado", False), (2, "desplazo", False)]

    def test_rechazo_sin_polaridad_opuesta_sigue_al_juez(self, monkeypatch: pytest.MonkeyPatch):
        # Al que pide la fila 69 se lo rechazan, pero no dice «cumple»: nada que marcar.
        otro = "Comparación con ECAP adjunto en INFOTÉCNICA: faltan los ajustes de la función 79"
        pdf = [_h(E7_NO_AJUSTADO), _h(otro)]
        juez = JuecesConRedaccion({(E7_NO_AJUSTADO, FILA_69): 85, (otro, FILA_69): 57})
        resultados, metas = _correr(pdf, [_excel(FILA_69, 69)], juez, True, monkeypatch)

        par = _por_pdf(resultados)[E7_NO_AJUSTADO]
        assert par.estado == EstadoHallazgo.COINCIDE
        assert [e.campo for e in par.equivalencias_redaccion] == [CampoDiferente.DESCRIPCION]
        assert par.emparejamiento_dudoso is None
        assert juez.textos_excel_juzgados() == [FILA_69]
        assert _perdidas(metas) == [(1, "rechazado", False)]

    def test_apagada_sin_asignacion_global_no_hay_dudoso(self, monkeypatch: pytest.MonkeyPatch):
        # En orden, el «no ajustado» toma la fila 69 y el «Cumple», que llega después,
        # no la ve: nadie la pierde y el par va al juez de redacción, como en B2.
        pdf = [_h(E7_NO_AJUSTADO), _h(E7_CUMPLE, pagina=PAGINA_CUMPLE)]
        juez = JuecesConRedaccion({(E7_NO_AJUSTADO, FILA_69): 85, (E7_CUMPLE, FILA_69): 57})
        resultados, metas = _correr(pdf, [_excel(FILA_69, 69)], juez, False, monkeypatch)

        res = _por_pdf(resultados)
        assert res[E7_NO_AJUSTADO].estado == EstadoHallazgo.COINCIDE
        assert [e.campo for e in res[E7_NO_AJUSTADO].equivalencias_redaccion] == [
            CampoDiferente.DESCRIPCION]
        assert res[E7_CUMPLE].estado == EstadoHallazgo.FALTA_EN_EXCEL
        assert all(r.emparejamiento_dudoso is None for r in resultados)
        assert juez.textos_excel_juzgados() == [FILA_69]
        assert _trazas(metas) == []

    def test_apagada_e7_sale_como_en_b2(self, monkeypatch: pytest.MonkeyPatch):
        # En orden (B2): el «Cumple» se queda la fila 69 (semantico_bajo, 0,57) y el
        # par difiere por polaridad opuesta, sin juez; el «no ajustado» queda en falta.
        pdf, excel, puntajes = _e7()
        juez = JuecesConRedaccion(puntajes)
        resultados, metas = _correr(pdf, excel, juez, False, monkeypatch)
        res = _por_pdf(resultados)

        par = res[E7_CUMPLE]
        assert par.hallazgo_excel and par.hallazgo_excel.evidencia.fila_excel == 69
        assert (par.tipo_match, par.estado) == (TipoMatch.SEMANTICO_BAJO, EstadoHallazgo.DIFIERE)
        assert [d.campo for d in par.diferencias] == [CampoDiferente.DESCRIPCION]
        assert (par.diferencias[0].detalle or "").startswith("Polaridad opuesta: el PDF indica")
        assert res[E7_NO_AJUSTADO].estado == EstadoHallazgo.FALTA_EN_EXCEL
        assert res[E7_NO_AJUSTADO].justificacion == "Sin candidatos disponibles en Excel."
        assert all(r.emparejamiento_dudoso is None for r in resultados)
        assert juez.textos_excel_juzgados() == [FILA_68]
        assert _trazas(metas) == []

    def test_la_marca_es_de_la_fila_y_pasa_a_quien_la_tenga_al_final(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # El «no ajustado» le quita la fila 69 al «Cumple» y después un tercero se la
        # quita a él. La 69 la perdió un hallazgo de polaridad opuesta: la marca pasa
        # al tercero. El «no ajustado» termina en la fila 70, que no perdió nadie de
        # polaridad opuesta: ese par va al juez de redacción.
        tercero, fila_70 = "Ajustes de la función 79 no informados", "Otra observación"
        pdf = [_h(E7_CUMPLE, pagina=PAGINA_CUMPLE), _h(E7_NO_AJUSTADO), _h(tercero)]
        excel = [_excel(FILA_69, 69), _excel(fila_70, 70)]
        juez = JuecesConRedaccion({(E7_CUMPLE, FILA_69): 57, (E7_CUMPLE, fila_70): 30,
                                   (E7_NO_AJUSTADO, FILA_69): 90, (E7_NO_AJUSTADO, fila_70): 85,
                                   (tercero, FILA_69): 95})
        resultados, metas = _correr(pdf, excel, juez, True, monkeypatch)
        res = _por_pdf(resultados)

        assert _perdidas(metas) == [(1, "desplazo", True), (2, "desplazo", False)]
        filas = {pdf: r.hallazgo_excel.evidencia.fila_excel
                 for pdf, r in res.items() if r.hallazgo_excel is not None}
        assert filas == {tercero: 69, E7_NO_AJUSTADO: 70}
        assert res[tercero].estado == EstadoHallazgo.DIFIERE
        assert [(d.campo, d.detalle) for d in res[tercero].diferencias] == [
            (CampoDiferente.DESCRIPCION, BAJO_EL_UMBRAL)]
        assert res[tercero].emparejamiento_dudoso == MOTIVO_E7
        assert res[E7_NO_AJUSTADO].estado == EstadoHallazgo.COINCIDE
        assert res[E7_NO_AJUSTADO].emparejamiento_dudoso is None
        assert juez.textos_excel_juzgados() == [fila_70]
        assert res[E7_CUMPLE].estado == EstadoHallazgo.FALTA_EN_EXCEL

    def test_tras_el_desempate_por_accion_la_marca_sigue_a_la_fila(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # Fila 69 «Ajustes ECAP: No cumple». En el PDF, el «Cumple» y dos hallazgos con
        # la descripción de la fila y acciones distintas. El «Cumple» toma la 69, el
        # primero de los otros se la quita (la 69 la perdió un hallazgo de polaridad
        # opuesta) y el segundo empata y la pierde. El desempate por acción (4d) le da
        # la 69 al segundo: la marca pasa con la fila y su acción, bajo el umbral, no
        # va al juez de redacción.
        fila, cumple = "Ajustes ECAP: No cumple", "Ajustes ECAP: Cumple"
        accion_fila, accion_1, accion_2 = (
            "Reajustar la función 79 según ECAP", "Revisar ajustes", "Reajustar función 79")
        fijos = {accion_fila: (1.0, 0.0), accion_1: (0.3, math.sqrt(1 - 0.3 ** 2)),
                 accion_2: (0.8, 0.6)}

        def _calcular(textos: list[str]) -> tuple[np.ndarray[Any, Any], None]:
            otros = [t for t in dict.fromkeys(textos) if t not in fijos]
            matriz = np.zeros((len(textos), 2 + len(otros)))
            for i, t in enumerate(textos):
                if t in fijos:
                    matriz[i, :2] = fijos[t]
                else:
                    matriz[i, 2 + otros.index(t)] = 1.0
            return matriz, None

        monkeypatch.setattr(etapa4_matching, "calcular_embeddings", _calcular)
        pdf = [_h(cumple, accion="Otra", pagina=PAGINA_CUMPLE), _h(fila, accion=accion_1),
               _h(fila, accion=accion_2)]
        juez = JuecesConRedaccion({(cumple, fila): 57, (fila, fila): 80})
        resultados, metas = _correr(pdf, [_excel(fila, 69, accion=accion_fila)], juez, True,
                                    monkeypatch)

        assert _perdidas(metas) == [(1, "desplazo", True), (2, "rechazado", False)]
        (par,) = [r for r in resultados if r.hallazgo_pdf and r.hallazgo_excel]
        assert par.hallazgo_pdf and par.hallazgo_pdf.accion_correctiva == accion_2
        assert par.estado == EstadoHallazgo.DIFIERE
        assert par.equivalencias_redaccion == []
        assert [(d.campo, d.detalle) for d in par.diferencias] == [(
            CampoDiferente.ACCION_CORRECTIVA,
            "Similitud semántica 0.80, bajo el umbral de coincidencia 0.85")]
        # Fila «No cumple»; el «Cumple» que la perdió está en la pág. 12.
        assert par.emparejamiento_dudoso == (
            "Revisar a qué hallazgo corresponde esta fila. El Excel dice que no cumple, pero "
            "en la pág. 12 hay otro hallazgo del PDF que dice que cumple (descripción «Ajustes "
            "ECAP: Cumple») y que también podría ser el de esta fila. Si es ese, el Excel "
            "invirtió el veredicto.")
        assert juez.textos_excel_juzgados() == []
        assert sorted((r.hallazgo_pdf.accion_correctiva or "", r.estado.value)
                      for r in resultados if r.hallazgo_pdf and r.hallazgo_excel is None) == [
            ("Otra", "falta_en_excel"), (accion_1, "falta_en_excel")]


def _pdf_en(pagina: int | None, descripcion: str = E7_CUMPLE) -> Hallazgo:
    return _h(descripcion, pagina=pagina)


@pytest.mark.parametrize(("pagina_par", "fila", "perdedores", "esperado"), [
    (None, FILA_69, [_pdf_en(12)], MOTIVO_E7),
    # Revisión del 2026-10-26: en AG1 (Alfa Opus, E7) el par y el «Cumple» están en la
    # pág. 26, con otros dos hallazgos de la tupla. La página sola no dice cuál es el otro.
    # PD72 (decisión del usuario 2026-10-26): este texto, exacto.
    (26, FILA_69, [_pdf_en(26, "Comparación con ECAP adjunto en INFOTÉCNICA: Cumple")],
     "Revisar a qué hallazgo corresponde esta fila. El Excel dice que no cumple, pero en la "
     "misma pág. 26 hay otro hallazgo del PDF que dice que cumple (descripción «Comparación "
     "con ECAP adjunto en INFOTÉCNICA: Cumple») y que también podría ser el de esta fila. Si "
     "es ese, el Excel invirtió el veredicto."),
    (12, FILA_69, [_pdf_en(None, "Ajustes ECAP:\n Cumple")],
     "Revisar a qué hallazgo corresponde esta fila. El Excel dice que no cumple, pero hay otro "
     "hallazgo del PDF que dice que cumple (descripción «Ajustes ECAP: Cumple») y que también "
     "podría ser el de esta fila. Si es ese, el Excel invirtió el veredicto."),
    (12, FILA_69, [_pdf_en(14, "Ajustes A: Cumple"), _pdf_en(None, "Ajustes B: Cumple"),
                   _pdf_en(3, "Ajustes C: Cumple"), _pdf_en(12, "Ajustes D: Cumple")],
     "Revisar a qué hallazgo corresponde esta fila. El Excel dice que no cumple, pero hay otros "
     "4 hallazgos del PDF que dicen que cumple (en la pág. 3, descripción «Ajustes C: Cumple»; "
     "en la misma pág. 12, descripción «Ajustes D: Cumple»; en la pág. 14, descripción "
     "«Ajustes A: Cumple»; descripción «Ajustes B: Cumple») y que también podrían ser el de "
     "esta fila. Si es uno de ellos, el Excel invirtió su veredicto."),
    (None, "Ajustes ECAP: Cumple", [_pdf_en(14, "Ajustes ECAP: No cumple"),
                                     _pdf_en(12, "Ajustes ECAP: incumple")],
     "Revisar a qué hallazgo corresponde esta fila. El Excel dice que cumple, pero hay otros 2 "
     "hallazgos del PDF que dicen que no cumple (en la pág. 12, descripción «Ajustes ECAP: "
     "incumple»; en la pág. 14, descripción «Ajustes ECAP: No cumple») y que también podrían "
     "ser el de esta fila. Si es uno de ellos, el Excel invirtió su veredicto."),
    (14, "Ajustes ECAP: Cumple", [_pdf_en(14, "Ajustes ECAP: No cumple")],
     "Revisar a qué hallazgo corresponde esta fila. El Excel dice que cumple, pero en la misma "
     "pág. 14 hay otro hallazgo del PDF que dice que no cumple (descripción «Ajustes ECAP: No "
     "cumple») y que también podría ser el de esta fila. Si es ese, el Excel invirtió el "
     "veredicto."),
], ids=["otra-pagina-recortada", "misma-pagina", "sin-pagina", "varios", "fila-cumple",
        "fila-cumple-uno"])
def test_motivo_dice_que_dice_cada_lado_y_donde_esta_y_cual_es_el_otro(
    pagina_par: int | None, fila: str, perdedores: list[Hallazgo], esperado: str
):
    # Es el texto de MatchResult.emparejamiento_dudoso (schema 0.9.0): se lee solo,
    # sin la diferencia al lado. Empieza por lo que hay que hacer y termina con la
    # consecuencia (PD72; redacción provisoria hasta el feedback del equipo revisor).
    par_pdf = _pdf_en(pagina_par, E7_NO_AJUSTADO)
    assert etapa4_matching._motivo_fila_disputada(
        par_pdf, _excel(fila, 69), perdedores) == esperado


def test_con_la_asignacion_global_y_sin_juez_de_redaccion_el_par_igual_es_dudoso(
    monkeypatch: pytest.MonkeyPatch
):
    # La marca es del emparejamiento (4b'), no del juez de redacción (4e): con
    # JUEZ_REDACCION=false (fixture `entorno`) la pasada 4e no corre, pero el par de la
    # fila 69 igual se muestra como dudoso.
    pdf, excel, puntajes = _e7()
    resultados, _ = _correr(pdf, excel, JuezPorTabla(puntajes), True, monkeypatch)
    res = _por_pdf(resultados)

    par = res[E7_NO_AJUSTADO]
    assert (par.tipo_match, par.estado) == (TipoMatch.SEMANTICO_ALTO, EstadoHallazgo.DIFIERE)
    assert [(d.campo, d.detalle) for d in par.diferencias] == [
        (CampoDiferente.DESCRIPCION, BAJO_EL_UMBRAL)]
    assert par.emparejamiento_dudoso == MOTIVO_E7
    assert [r.hallazgo_pdf.descripcion for r in resultados
            if r.hallazgo_pdf and r.emparejamiento_dudoso] == [E7_NO_AJUSTADO]


# --- Encendida por defecto (decisión del usuario 2026-10-26) -----------------


def test_encendida_por_defecto_y_en_el_env_example(monkeypatch: pytest.MonkeyPatch):
    """Desde el 2026-10-26 (con la regla V2 de PD71) el default es true, también
    en el .env.example que copia quien instala; el entorno la apaga
    (ASIGNACION_GLOBAL=false = comportamiento previo exacto)."""
    assert Settings.model_fields["asignacion_global"].default is True
    ejemplo = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    assert re.findall(r"^ASIGNACION_GLOBAL=(.*)$", ejemplo, flags=re.M) == ["true"]
    monkeypatch.delenv("ASIGNACION_GLOBAL", raising=False)
    assert Settings(_env_file=None).asignacion_global is True
    monkeypatch.setenv("ASIGNACION_GLOBAL", "false")
    assert Settings(_env_file=None).asignacion_global is False


@pytest.mark.usefixtures("con_redaccion")
def test_con_la_configuracion_por_defecto_e7_no_se_esconde(monkeypatch: pytest.MonkeyPatch):
    """La conducta por defecto (el interruptor en su default, no fijado por el
    test): el par que le ganó la fila 69 al «Cumple» es un emparejamiento dudoso
    y sale «difiere» sin juez de redacción, aunque el juez lo daría por igual."""
    monkeypatch.setattr(settings, "asignacion_global",
                        Settings.model_fields["asignacion_global"].default)
    pdf, excel, puntajes = _e7()
    juez = JuecesConRedaccion(puntajes)
    monkeypatch.setattr(etapa4_matching, "llamar_llm_estructurado", juez)

    resultados, _ = ejecutar_matching(pdf, excel)

    par = _por_pdf(resultados)[E7_NO_AJUSTADO]
    assert par.hallazgo_excel and par.hallazgo_excel.evidencia.fila_excel == 69
    assert (par.estado, par.emparejamiento_dudoso) == (EstadoHallazgo.DIFIERE, MOTIVO_E7)
    assert FILA_69 not in juez.textos_excel_juzgados()


@pytest.fixture(autouse=True)
def _sin_descripcion_identica(monkeypatch: pytest.MonkeyPatch) -> None:
    """Estos tests fijan el camino del juez con descripciones idénticas (y lo que
    reproducen de B2, AG1 y AG2, que corrieron sin M30). DESCRIPCION_IDENTICA,
    encendido por defecto desde el 2026-10-27, se prueba en
    test_etapa4_descripcion_identica.py."""
    monkeypatch.setattr(settings, "descripcion_identica", False)
