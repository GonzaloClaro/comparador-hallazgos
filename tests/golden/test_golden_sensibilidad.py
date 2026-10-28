"""M43 sobre lo guardado, sin API: re-evaluar el control y las dos pasadas de
mediciones/m43 da lo mismo que la evaluación guardada, y fija sus cifras.

64 errores (8 por tipo) en los 7 informes con Opus, con el código de la ronda
(asignación global y descripción idéntica encendidas). Lo que decide el código y
la estructura sale detectado (~100 % por construcción); de los que deciden los
jueces, escapan 3 cambios mínimos en pares que copian el PDF (un código o un número
en una oración larga: la similitud queda sobre el umbral y nadie más la mira). No
es una tasa de errores reales.
"""

from __future__ import annotations

import json
from collections import Counter

import pytest

from comparador import sensibilidad
from tests.golden.datos import MEDICIONES, requiere_mediciones

pytestmark = [pytest.mark.golden, requiere_mediciones]

M43 = MEDICIONES / "m43"


@pytest.fixture(scope="module")
def evaluacion() -> sensibilidad.Evaluacion:
    if not (M43 / "catalogo.json").is_file():
        pytest.skip("exento: sin mediciones/m43")
    catalogo = sensibilidad.cargar_catalogo(M43 / "catalogo.json")
    return sensibilidad.evaluar(catalogo.errores, M43 / "control",
                                [M43 / "pasada1", M43 / "pasada2"])


def test_reproduce_la_evaluacion_guardada(evaluacion: sensibilidad.Evaluacion) -> None:
    guardada = json.loads((M43 / "evaluacion.json").read_text(encoding="utf-8"))
    assert evaluacion.model_dump(mode="json") == guardada


def test_el_catalogo_es_el_congelado() -> None:
    import hashlib

    if not (M43 / "catalogo.sha256").is_file():
        pytest.skip("exento: sin mediciones/m43")
    sha = (M43 / "catalogo.sha256").read_text(encoding="utf-8").split()[0]
    assert hashlib.sha256((M43 / "catalogo.json").read_bytes()).hexdigest() == sha


def test_cifras(evaluacion: sensibilidad.Evaluacion) -> None:
    por_tipo: dict[str, Counter[str]] = {}
    for e in evaluacion.errores:
        assert e.clases[0] == e.clases[1], e.id   # las dos pasadas coinciden
        por_tipo.setdefault(e.tipo, Counter())[e.clases[0]] += 1
    assert {t: dict(c) for t, c in por_tipo.items()} == {
        "calificacion": {"detectado": 8}, "polaridad": {"detectado": 8},
        "pano": {"detectado": 8}, "fila_borrada": {"detectado": 8},
        "accion": {"detectado": 8}, "descripcion": {"detectado": 3, "otra_alerta": 5},
        "minimo": {"detectado": 4, "otra_alerta": 1, "escapado": 3},
        "neutro": {"sin_alerta": 8}}
    escapados = {(e.id, e.informe, e.par_control) for e in evaluacion.errores
                 if "escapado" in e.clases}
    assert escapados == {("M43-02", "Epsilon", "literal"), ("M43-32", "Beta", "literal"),
                         ("M43-39", "Beta", "literal")}
    assert evaluacion.cambios_fuera_de_los_blancos == [
        {"pasada": "pasada1", "cambios": 0}, {"pasada": "pasada2", "cambios": 0}]
