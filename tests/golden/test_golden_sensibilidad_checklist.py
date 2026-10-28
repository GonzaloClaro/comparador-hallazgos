"""M43c (la parte del checklist de M43) sobre lo guardado, sin API.

Se quitaron del PDF reconvertido de Zeta y Gamma las páginas que respaldaban
13 «cumple» del control (catálogo congelado y verificado antes de correr): la
portada, las pruebas de la diferencial y el estudio de coordinación. Los 13 salen
detectados por el modelo (no verificable o no cumple): ninguno se escapa como un
falso cumple. Re-evaluar lo guardado da la evaluación guardada y fija sus cifras. No
es una tasa de falsos cumple: son ausencias sintéticas, 13 blancos en 2 informes.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter

import pytest

from comparador import sensibilidad_checklist as sc
from tests.golden.datos import MEDICIONES, requiere_mediciones

pytestmark = [pytest.mark.golden, requiere_mediciones]

M43C = MEDICIONES / "m43c"


@pytest.fixture(scope="module")
def evaluacion() -> sc.EvaluacionChecklist:
    if not (M43C / "catalogo.json").is_file():
        pytest.skip("exento: sin mediciones/m43c")
    catalogo = sc.cargar_catalogo(M43C / "catalogo.json")
    return sc.evaluar(catalogo, M43C / "control",
                      [M43C / "recorte_a", M43C / "recorte_b"], M43C / "insumos")


def test_el_catalogo_es_el_congelado() -> None:
    if not (M43C / "catalogo.sha256").is_file():
        pytest.skip("exento: sin mediciones/m43c")
    sha = (M43C / "catalogo.sha256").read_text(encoding="utf-8").split()[0]
    assert hashlib.sha256((M43C / "catalogo.json").read_bytes()).hexdigest() == sha


def test_reproduce_la_evaluacion_guardada(evaluacion: sc.EvaluacionChecklist) -> None:
    guardada = json.loads((M43C / "evaluacion.json").read_text(encoding="utf-8"))
    assert evaluacion.model_dump(mode="json") == guardada


def test_cifras(evaluacion: sc.EvaluacionChecklist) -> None:
    por_recorte = {r.id: Counter(b.clase for b in r.blancos) for r in evaluacion.recortes}
    assert por_recorte == {"MAC-A": Counter(detectado_modelo=4),
                           "MAC-B": Counter(detectado_modelo=2),
                           "SP-A": Counter(detectado_modelo=5),
                           "SP-B": Counter(detectado_modelo=2)}
    # Todo el control y los recortes con el mismo código congelado.
    assert {r.sha256_codigo for r in evaluacion.recortes} == {"c6e7c9bb69adf39c"}


def test_el_csv_es_el_de_metricas_lote(evaluacion: sc.EvaluacionChecklist) -> None:
    assert sc.filas_csv(evaluacion) == sc.filas_desde_mediciones(MEDICIONES)
