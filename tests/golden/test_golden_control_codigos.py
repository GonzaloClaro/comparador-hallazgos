"""Control de códigos (M28 V2, decisión del usuario 2026-10-27) sobre lo guardado, sin API.

Sobre el umbral, un código o número sustituido entre el PDF y el Excel es
Diferencia sin LLM (etapa4_matching 4e, `CONTROL_CODIGOS`). Es el punto ciego que
mostró M43: 3 cambios mínimos en pares que copian el PDF salieron «coincide».

1. Barrido de los reportes guardados (B0-B3, las repeticiones de E4 y M43): la
   regla solo marca, sobre el umbral, los 3 escapes de M43 y la acción de Alfa
   C3 y C4, donde el PDF copió «paño E5» (CB69). Una marca nueva sobre lo guardado
   es una falsa alarma posible: se adjudica antes de cambiar este test.
2. B2 (14 runs, caché estricta y vectores de D1): con el control encendido, la
   repetición da la base de regresión salvo la acción de Alfa C3 y C4, con los
   dos modelos; el estado y el resumen no cambian (esos pares ya difieren por la
   calificación).
3. M43: la repetición estricta de cada pasada con el código de hoy da la guardada
   en `pasada{1,2}_codigos`, y su evaluación, la guardada: los 3 escapes salen
   detectados (cambios mínimos 7 de 8 detectados, 1 otra alerta, 0 escapes) y lo
   demás no cambia.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from comparador import sensibilidad
from comparador.config import settings
from comparador.etapa4_matching import _terminos_sustituidos
from comparador.reproducir_e4 import reproducir_e4
from comparador.schemas import ReporteInforme
from tests.golden.datos import MEDICIONES, Caso, requiere_mediciones
from tests.golden.test_golden_replay_e4 import (
    _base,
    _casos_con_vectores,
    _sin_version,
    _vectores,
)

pytestmark = [pytest.mark.golden, requiere_mediciones]

M43 = MEDICIONES / "m43"
PREFIJO = "Código o número distinto"

# (paño, relé, fila del Excel, campo, del PDF, del Excel)
CB69 = {("C3", "SEL 451", 36, "accion_correctiva", ("E5",), ("C3",)),
        ("C4", "SEL 451", 43, "accion_correctiva", ("E5",), ("C4",))}
ESCAPES_M43 = {("BT2", "SEL 311C", 20, "descripcion", ("50N",), ("67N",)),    # Epsilon, M43-02
               ("BT1", "GE D30", 33, "descripcion", ("50G",), ("51G",)),      # Beta, M43-32
               ("ET3", "SEL 351S", 97, "descripcion", ("2,50",), ("0,50",))}  # Beta, M43-39


def _reportes_guardados() -> list[Path]:
    patrones = ("b[0-9]*/runs/*/reporte_final.json", "replay_e4/*/*/reporte_final.json",
                "m43/*/*/reporte_final.json")
    return [p for patron in patrones for p in sorted(MEDICIONES.glob(patron))
            if not p.parts[-3].endswith("_codigos")]


def _marcas(resultados: list[dict[str, Any]]) -> set[tuple[Any, ...]]:
    """Campos sobre el umbral que la regla marcaría: los que no llevan Diferencia ni
    EquivalenciaRedaccion (bajo el umbral siempre llevan una de las dos)."""
    marcas = set()
    for r in resultados:
        h_pdf, h_excel = r.get("hallazgo_pdf"), r.get("hallazgo_excel")
        if not h_pdf or not h_excel:
            continue
        con_alerta = ({d["campo"] for d in r["diferencias"]}
                      | {e["campo"] for e in r.get("equivalencias_redaccion") or []})
        for campo in ("descripcion", "accion_correctiva"):
            if campo in con_alerta or h_pdf.get(campo) is None or h_excel.get(campo) is None:
                continue
            if sustituidos := _terminos_sustituidos(h_pdf[campo], h_excel[campo]):
                marcas.add((r["pano"], r["rele"], h_excel["evidencia"]["fila_excel"], campo,
                            tuple(sustituidos[0]), tuple(sustituidos[1])))
    return marcas


def test_barrido_de_lo_guardado() -> None:
    reportes = _reportes_guardados()
    assert len(reportes) >= 102
    por_fuente: dict[str, set[tuple[Any, ...]]] = {}
    for ruta in reportes:
        marcas = _marcas(json.loads(ruta.read_text(encoding="utf-8"))["resultados"])
        if marcas:
            por_fuente.setdefault(ruta.relative_to(MEDICIONES).parts[0], set()).update(marcas)
    # Alfa C3/C4 en cada ronda y repetición que la trae; los escapes, solo en las
    # pasadas de M43 (el control no tiene errores plantados).
    assert por_fuente == {"b0": CB69, "b1": CB69, "b2": CB69, "replay_e4": CB69,
                          "m43": CB69 | ESCAPES_M43}


@pytest.fixture
def _config_de_b2_con_control(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "effort_llm", "")
    monkeypatch.setattr(settings, "asignacion_global", False)
    monkeypatch.setattr(settings, "descripcion_identica", False)
    monkeypatch.setattr(settings, "control_codigos", True)
    monkeypatch.setattr(settings, "unificar_copias", False)   # la base de B2 corrió sin M34


@pytest.mark.usefixtures("_config_de_b2_con_control")
@pytest.mark.parametrize("caso", _casos_con_vectores())
def test_b2_cambia_solo_la_accion_de_alfa(caso: Caso, tmp_path: Path) -> None:
    base, salida = _base(caso), tmp_path / "replay"
    meta = reproducir_e4(caso.run_dir, salida, None, vectores=_vectores(caso),
                         cache="estricto", cache_desde=base)

    assert (meta["control_codigos"], meta["cache_jueces"]["pagadas"]) == (True, 0)
    # Por el schema de hoy, como test_golden_replay_e4 (la base es de un schema anterior).
    # Sin el motivo de cada Diferencia (0.12.0), que la base no trae.
    esperado, repetido = (_sin_version(ReporteInforme.model_validate_json(
        (d / "reporte_final.json").read_text(encoding="utf-8")).model_dump(mode="json"))
        for d in (base, salida))
    nuevas = set()
    for antes, despues in zip(esperado["resultados"], repetido["resultados"], strict=True):
        agregadas = [d for d in despues["diferencias"] if d not in antes["diferencias"]]
        # Solo se agregan diferencias del control; nada más cambia en el par.
        assert _sin_version({**despues, "diferencias": [
            d for d in despues["diferencias"] if d not in agregadas]}) == _sin_version(antes)
        for d in agregadas:
            assert d["detalle"].startswith(PREFIJO), d["detalle"]
            h_excel = despues["hallazgo_excel"]
            nuevas.add((despues["pano"], despues["rele"], h_excel["evidencia"]["fila_excel"],
                        d["campo"]))
    assert nuevas == ({c[:4] for c in CB69} if caso.subestacion == "Alfa" else set())
    # Esos pares ya difieren por la calificación: el resumen no cambia.
    assert repetido["resumen"] == esperado["resumen"]


def _runs_m43() -> list[Any]:
    if not (M43 / "pasada1_codigos").is_dir():
        return [pytest.param(None, None, id="sin-m43",
                             marks=pytest.mark.skip(reason="exento: sin mediciones/m43"))]
    return [pytest.param(pasada, run.name, id=f"{pasada}-{run.name}")
            for pasada in ("pasada1", "pasada2") for run in sorted((M43 / "runs").iterdir())]


@pytest.mark.parametrize(("pasada", "run_id"), _runs_m43())
def test_m43_la_repeticion_estricta_da_la_guardada(pasada: str, run_id: str,
                                                   tmp_path: Path) -> None:
    # La configuración del proceso con que se repitió: la de hoy (asignación global,
    # descripción idéntica y control de códigos encendidos).
    assert (settings.asignacion_global, settings.descripcion_identica,
            settings.control_codigos) == (True, True, True)
    origen, guardada = M43 / pasada / run_id, M43 / f"{pasada}_codigos" / run_id
    vectores = origen / "etapa4_embeddings.npz"
    if not vectores.is_file():
        vectores = MEDICIONES / "b2" / "vectores_e4" / f"{run_id}.npz"
    con_jueces = any(origen.glob("etapa4_*_raw/judge_*.json")) or any(
        origen.glob("etapa4_*_raw/redaccion_*.json"))
    salida = tmp_path / "replay"

    meta = reproducir_e4(M43 / "runs" / run_id, salida, None, vectores=vectores,
                         cache="estricto", cache_desde=origen if con_jueces else None)

    assert (meta["cache_jueces"]["pagadas"], meta["vectores"]["calculados"]) == (0, 0)
    repetido, esperado = (ReporteInforme.model_validate_json(
        (d / "reporte_final.json").read_text(encoding="utf-8")) for d in (salida, guardada))
    assert _sin_version([r.model_dump(mode="json") for r in repetido.resultados]) == (
        _sin_version([r.model_dump(mode="json") for r in esperado.resultados]))


@pytest.fixture(scope="module")
def evaluacion_codigos() -> sensibilidad.Evaluacion:
    if not (M43 / "pasada1_codigos").is_dir():
        pytest.skip("exento: sin mediciones/m43")
    sha = (M43 / "catalogo.sha256").read_text(encoding="utf-8").split()[0]
    assert hashlib.sha256((M43 / "catalogo.json").read_bytes()).hexdigest() == sha
    catalogo = sensibilidad.cargar_catalogo(M43 / "catalogo.json")
    return sensibilidad.evaluar(catalogo.errores, M43 / "control",
                                [M43 / "pasada1_codigos", M43 / "pasada2_codigos"])


def test_m43_con_el_control_reproduce_la_evaluacion_guardada(
        evaluacion_codigos: sensibilidad.Evaluacion) -> None:
    guardada = json.loads((M43 / "evaluacion_codigos.json").read_text(encoding="utf-8"))
    assert evaluacion_codigos.model_dump(mode="json") == guardada


def test_m43_con_el_control_los_escapes_salen_detectados(
        evaluacion_codigos: sensibilidad.Evaluacion) -> None:
    por_tipo: dict[str, Counter[str]] = {}
    for e in evaluacion_codigos.errores:
        assert e.clases[0] == e.clases[1], e.id
        por_tipo.setdefault(e.tipo, Counter())[e.clases[0]] += 1
    # Igual que M43 salvo los cambios mínimos: de 4 detectados, 1 otra alerta y 3
    # escapes a 7 detectados y 1 otra alerta.
    assert {t: dict(c) for t, c in por_tipo.items()} == {
        "calificacion": {"detectado": 8}, "polaridad": {"detectado": 8},
        "pano": {"detectado": 8}, "fila_borrada": {"detectado": 8},
        "accion": {"detectado": 8}, "descripcion": {"detectado": 3, "otra_alerta": 5},
        "minimo": {"detectado": 7, "otra_alerta": 1},
        "neutro": {"sin_alerta": 8}}
    clases = {e.id: e.clases for e in evaluacion_codigos.errores}
    assert all(clases[i] == ["detectado", "detectado"] for i in ("M43-02", "M43-32", "M43-39"))
    assert evaluacion_codigos.cambios_fuera_de_los_blancos == [
        {"pasada": "pasada1_codigos", "cambios": 0}, {"pasada": "pasada2_codigos", "cambios": 0}]
