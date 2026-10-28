"""Tests de confianza, sensibilidad, estabilidad y versión de las métricas (sin API)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from comparador import metricas_confianza as conf


def _punto(informe: str, punto: int, veredicto: str, resultado: str, ronda: str = "B2",
           modelo: str = "claude-sonnet-5-5") -> dict[str, Any]:
    from comparador.evaluar_checklist import clasificar
    from comparador.schemas import ResultadoChecklist

    return {
        "ronda": ronda, "modelo": modelo, "informe": informe, "punto": punto,
        "codigo_gt": "x", "veredicto_gt": veredicto, "resultado": resultado,
        "clasificacion": clasificar(ResultadoChecklist(resultado), veredicto),
    }


class TestWilsonYBootstrap:
    def test_wilson_valor_conocido(self):
        lo, hi = conf.wilson(173, 210)
        assert (round(lo, 3), round(hi, 3)) == (0.767, 0.869)

    def test_wilson_con_cero_no_baja_de_cero(self):
        lo, hi = conf.wilson(0, 10)
        assert lo == 0.0 and 0 < hi < 0.35

    def test_wilson_rechaza_n_cero(self):
        with pytest.raises(ValueError):
            conf.wilson(0, 0)

    def test_bootstrap_es_determinista_y_acotado(self):
        pares = [(30, 35), (25, 36), (31, 35)]
        a = conf.bootstrap_por_informe(pares)
        assert a == conf.bootstrap_por_informe(pares)
        assert 25 / 36 <= a[0] <= a[1] <= 31 / 35


class TestEscenarios:
    def test_solo_cambian_las_celdas_del_criterio_sin_importar_tildes(self):
        assert conf.veredicto_escenario("Beta", 6, "NO", "planilla_corregida") == "SI"
        assert conf.veredicto_escenario("Epsilon", 23, "NO", "planilla_corregida") == "SI"
        assert conf.veredicto_escenario("Epsilon", 22, "NO", "planilla_corregida") == "NO"
        assert conf.veredicto_escenario("Beta", 6, "NO", "planilla_al_medir") == "NO"

    def test_celdas_que_equipo_dio_por_correctas_no_cambian(self):
        # 2026-10-17: Zeta/Añañuca 23 (SI) y Gamma 6 (NO) eran correctas.
        assert conf.veredicto_escenario("Zeta", 23, "SI", "planilla_corregida") == "SI"
        assert conf.veredicto_escenario("Añañuca", 23, "SI", "planilla_corregida") == "SI"
        assert conf.veredicto_escenario("Gamma", 6, "NO", "planilla_corregida") == "NO"

    def test_confianza_cuenta_por_escenario(self):
        puntos = [
            _punto("Beta", 6, "NO", "cumple"),     # falso cumple; con la celda corregida, acierto
            _punto("Beta", 7, "SI", "cumple"),
            _punto("Epsilon", 9, "NO", "cumple"),    # ídem
            _punto("Epsilon", 10, "NO", "no_cumple"),
        ]
        filas = {f["escenario"]: f for f in conf.filas_confianza_checklist(puntos)}
        al_medir, corregida = filas["planilla_al_medir"], filas["planilla_corregida"]
        assert (al_medir["aciertos"], al_medir["falsos_cumple"]) == (2, 2)
        assert al_medir["veredictos_no_gt"] == 3
        assert (corregida["aciertos"], corregida["falsos_cumple"]) == (4, 0)
        assert al_medir["informes"] == 2 and al_medir["incumplimientos_detectados"] == 1
        assert al_medir["peor_informe_pct"] == 50.0
        # La celda corregida pasa de la fila NO a la fila SI de la matriz (M42).
        assert (al_medir["gt_no_cumple"], al_medir["gt_si_cumple"]) == (2, 1)
        assert (corregida["gt_no_cumple"], corregida["gt_si_cumple"]) == (0, 3)
        assert (corregida["veredictos_si_gt"], corregida["veredictos_no_gt"]) == (3, 1)


def _puntos_matriz() -> list[dict[str, Any]]:
    """SI: 3 cumple, 1 no verificable, 1 no cumple; NO: 3 no cumple, 1 cumple."""
    return [
        *(_punto("X", n, "SI", "cumple") for n in (1, 2, 3)),
        _punto("X", 4, "SI", "no_verificable"), _punto("X", 5, "SI", "no_cumple"),
        *(_punto("X", n, "NO", "no_cumple") for n in (11, 12, 13)),
        _punto("X", 14, "NO", "cumple"),
    ]


class TestMatrizChecklist:
    """M42: matriz 2×3, TNR, TPR y falso cumple sobre los NO con intervalos."""

    def _fila(self, puntos: list[dict[str, Any]]) -> dict[str, Any]:
        return next(f for f in conf.filas_confianza_checklist(puntos)
                    if f["escenario"] == "planilla_al_medir")

    def test_matriz_de_seis_celdas_tnr_y_tpr(self):
        fila = self._fila(_puntos_matriz())
        assert [fila[c] for c in conf.CELDAS_MATRIZ] == [3, 1, 1, 1, 0, 3]
        assert (fila["veredictos_si_gt"], fila["veredictos_no_gt"]) == (5, 4)
        assert (fila["pct_tnr"], fila["pct_tpr"]) == (60.0, 75.0)
        assert (fila["tpr_wilson95_inf"], fila["tpr_wilson95_sup"]) == (30.1, 95.4)

    def test_falso_cumple_sobre_los_no_con_wilson_y_sin_cota_si_hubo_alguno(self):
        fila = self._fila(_puntos_matriz())
        assert fila["tasa_falso_cumple_sobre_no"] == 25.0
        assert (fila["falso_cumple_wilson95_inf"], fila["falso_cumple_wilson95_sup"]) == (
            4.6, 69.9)
        assert fila["falso_cumple_cota_regla_de_tres"] == ""

    def test_sin_falsos_cumple_la_cota_es_la_regla_de_tres(self):
        puntos = [_punto("X", n, "NO", "no_cumple") for n in range(18)]
        fila = self._fila(puntos)
        assert fila["falso_cumple_cota_regla_de_tres"] == 16.7       # 3/18
        assert (fila["falso_cumple_wilson95_inf"], fila["falso_cumple_wilson95_sup"]) == (
            0.0, 17.6)
        # Con menos de 3 NO, la regla de tres no acota nada: 100 %.
        assert self._fila(puntos[:2])["falso_cumple_cota_regla_de_tres"] == 100.0

    def test_sin_veredictos_no_las_tasas_sobre_los_no_quedan_vacias(self):
        fila = self._fila([_punto("X", 1, "SI", "cumple"), _punto("X", 2, "SI", "no_cumple")])
        assert fila["veredictos_no_gt"] == 0 and fila["pct_tnr"] == 50.0
        for columna in ("pct_tpr", "tpr_wilson95_inf", "tpr_wilson95_sup",
                        "falso_cumple_wilson95_inf", "falso_cumple_wilson95_sup",
                        "falso_cumple_cota_regla_de_tres", "tasa_falso_cumple_sobre_no"):
            assert fila[columna] == "", columna
        sin_si = self._fila([_punto("X", 1, "NO", "no_cumple")])
        assert sin_si["pct_tnr"] == ""


class TestCausasFalsoCumple:
    @pytest.mark.parametrize(("ronda", "informe", "punto", "causa"), [
        ("B0", "Añañuca", 17, "error_del_sistema_corregido"),
        ("B2", "Beta", 22, "error_del_sistema_corregido"),
        # Solo los casos ya diagnosticados; uno nuevo en un punto con pregunta abierta, no.
        ("B1", "Beta", 22, "sin_explicacion_conocida"),
        ("B3", "Epsilon", 10, "sin_explicacion_conocida"),
        # Gamma 6 de B0–B2 depende de P1 (decisión del usuario 2026-10-26, PD68).
        ("B0", "Gamma", 6, "criterio_abierto_pregunta_equipo"),
        ("B1", "Gamma", 6, "criterio_abierto_pregunta_equipo"),
        ("B2", "Gamma", 6, "criterio_abierto_pregunta_equipo"),
        # Un falso cumple nuevo, después de B2, no hereda el diagnóstico.
        ("B3", "Gamma", 6, "sin_explicacion_conocida"),
        ("B3", "Añañuca", 17, "sin_explicacion_conocida"),
        ("B2", "Beta", 6, "celda_gt_contradice_criterio_equipo"),
        ("B2", "Epsilon", 10, "criterio_abierto_pregunta_equipo"),
        ("B2", "Epsilon", 3, "sin_explicacion_conocida"),
    ])
    def test_causa(self, ronda: str, informe: str, punto: int, causa: str):
        assert conf.causa_falso_cumple(ronda, informe, punto)[0] == causa

    def test_preguntas_abiertas_salen_del_origen_del_yaml(self):
        # PD68: fuente única, el bloque `origen` de checklist_puntos.yaml.
        from comparador.etapa0_checklist import cargar_puntos

        esperado = {p["numero"]: tuple(p["origen"]["preguntas"])
                    for p in cargar_puntos() if p["origen"]["preguntas"]}
        assert esperado == conf.PREGUNTAS_ABIERTAS
        # Anclas: la pregunta propia del punto va primera; P6 no va en 37 ni 38 (D4).
        assert conf.PREGUNTAS_ABIERTAS[32] == ("P11", "P6", "P13")
        assert conf.PREGUNTAS_ABIERTAS[25] == ("P21",)
        assert conf.PREGUNTAS_ABIERTAS[10] == ("P2",)
        assert 37 not in conf.PREGUNTAS_ABIERTAS and 38 not in conf.PREGUNTAS_ABIERTAS

    def test_caso_con_su_propia_pregunta(self):
        # Decisión del usuario 2026-10-26: Epsilon tiene función 21, así que su 32 depende de
        # P11 (la pregunta propia del punto), no de P6 ni de P13.
        assert conf.causa_falso_cumple("B0", "Epsilon", 32) == (
            "criterio_abierto_pregunta_equipo", "tasks/equipo/preguntas_v3.md P11")

    def test_preguntas_del_caso_son_de_un_caso_y_de_su_punto(self):
        for caso, preguntas in conf.PREGUNTAS_DEL_CASO.items():
            assert caso in conf.FALSOS_CUMPLE_POR_PREGUNTA_ABIERTA
            assert preguntas and set(preguntas) <= set(conf.PREGUNTAS_ABIERTAS[caso[2]])

    @pytest.mark.parametrize(("ronda", "informe", "punto", "referencia"), [
        ("B2", "Epsilon", 30, "P9; P10"),     # varias preguntas: todas, unidas (D3)
        ("B2", "Gamma", 6, "P1"),
        ("B2", "Epsilon", 10, "P2"),
    ])
    def test_referencia_lista_todas_las_preguntas_del_punto(
        self, ronda: str, informe: str, punto: int, referencia: str
    ):
        assert conf.causa_falso_cumple(ronda, informe, punto) == (
            "criterio_abierto_pregunta_equipo", f"tasks/equipo/preguntas_v3.md {referencia}")

    def test_cada_caso_diagnosticado_tiene_pregunta_en_el_origen(self):
        # Si alguien quita del YAML la pregunta de un caso ya diagnosticado,
        # causa_falso_cumple no puede dar su referencia.
        faltan = [c for c in conf.FALSOS_CUMPLE_POR_PREGUNTA_ABIERTA
                  if c[2] not in conf.PREGUNTAS_ABIERTAS]
        assert faltan == []

    def test_errores_corregidos_y_preguntas_abiertas_no_se_solapan(self):
        # Un mismo caso no puede tener dos causas: el error corregido ganaría en silencio.
        corregidos = {(r, i, p) for r, i, p in conf.ERRORES_SISTEMA_CORREGIDOS}
        assert corregidos.isdisjoint(conf.FALSOS_CUMPLE_POR_PREGUNTA_ABIERTA)
        comodines = {(r, p) for r, i, p in corregidos if i == "*"}
        assert not [c for c in conf.FALSOS_CUMPLE_POR_PREGUNTA_ABIERTA
                    if (c[0], c[2]) in comodines]


def _src(raiz: Path, enunciado_22: str, system: str) -> None:
    (raiz / "comparador" / "llm").mkdir(parents=True)
    (raiz / "comparador" / "checklist_puntos.yaml").write_text(
        "puntos:\n"
        "  - {numero: 21, enunciado: a, donde_buscar: b}\n"
        f"  - {{numero: 22, enunciado: {enunciado_22}, donde_buscar: b}}\n",
        encoding="utf-8",
    )
    (raiz / "comparador" / "llm" / "prompts.py").write_text(
        f'SYSTEM_CHECKLIST = """{system}"""\n', encoding="utf-8"
    )


class TestEstabilidadYVersion:
    def test_estabilidad_solo_en_puntos_con_prompt_sin_cambio(self, tmp_path: Path):
        _src(tmp_path / "b1" / "src", "viejo", "s")
        _src(tmp_path / "b2" / "src", "nuevo", "s")
        puntos = [
            _punto("X", 21, "SI", "cumple", "B1"), _punto("X", 21, "SI", "no_verificable", "B2"),
            _punto("X", 22, "SI", "cumple", "B1"), _punto("X", 22, "SI", "no_cumple", "B2"),
        ]
        (fila,) = conf.filas_estabilidad_checklist(tmp_path, puntos)
        assert fila["puntos_con_prompt_sin_cambio"] == 1          # solo el 21
        assert (fila["comparaciones"], fila["mismo_resultado"]) == (1, 0)
        assert fila["system_prompt_checklist_igual"] is True

    def test_hash_arbol_ignora_pycache_y_detecta_cambios(self, tmp_path: Path):
        src = tmp_path / "src"
        _src(src, "a", "s")
        h1, n1 = conf.hash_arbol(src)
        (src / "comparador" / "__pycache__").mkdir()
        (src / "comparador" / "__pycache__" / "x.py").write_text("basura", encoding="utf-8")
        assert conf.hash_arbol(src) == (h1, n1)
        (src / "comparador" / "llm" / "prompts.py").write_text("cambio", encoding="utf-8")
        assert conf.hash_arbol(src)[0] != h1
