"""M34 (copias del mismo origen, paso 4f) sobre lo guardado, sin API.

1. Barrido: 4f aplicado a todos los reportes guardados (B0-B3, las repeticiones de
   E4 y M43). Con Opus no cambia ninguna clase (solo bajan confianzas sin cambiar de tipo);
   lo que cambia de estado o de tipo es Sonnet y Haiku en Gamma (fijado abajo).
2. 4f no cambia ninguna llamada a los jueces: la repetición estricta de cada run de
   B2 (y de las repeticiones de E4 posteriores a PD72: M30, M33 y CC), con UNIFICAR_COPIAS,
   sale entera de la caché y da exactamente 4f aplicado al reporte de la base.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from comparador.config import settings
from comparador.etapa4_matching import _grupos_de_copias, _unificar_copias
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

# (carpeta del run relativa a mediciones, paño, antes, después) de lo que cambia de
# estado o de tipo de emparejamiento: «estado» (coincide → difiere) o «tipo»
# (semantico_alto → semantico_bajo).
CAMBIOS_DE_CLASE = {
    # Sonnet B1 Gamma: 84 y 80 contra 78 en el mismo origen.
    ("b1/runs/2026-10-16_23-36-05_claude-sonnet-5-5", "BT1", "tipo"),
    ("b1/runs/2026-10-16_23-36-05_claude-sonnet-5-5", "CT2", "tipo"),
    # Sonnet B2 Gamma: idx 3 (0,84 → 0,78) e idx 62 (mismo contenido → difiere,
    # su copia idx 14 la dio por distinta; pág. 16, fila 41).
    ("b2/runs/2026-10-17_01-37-43_claude-sonnet-5-5", "BT1", "tipo"),
    ("b2/runs/2026-10-17_01-37-43_claude-sonnet-5-5", "CT2", "estado"),
    # Haiku B2 Gamma: idx 8, por unicidad, mismo contenido → difiere.
    ("b2/runs/2026-10-17_02-08-20_claude-haiku-5-5", "BT2", "estado"),
}


def _reportes() -> list[Path]:
    patrones = ("b[0-9]*/runs/*/reporte_final.json", "replay_e4/*/*/reporte_final.json",
                "m43/*/*/reporte_final.json")
    return [p for patron in patrones for p in sorted(MEDICIONES.glob(patron))]


def test_barrido_de_lo_guardado() -> None:
    con_grupos, cambios = 0, set()
    for ruta in _reportes():
        resultados = ReporteInforme.model_validate_json(
            ruta.read_text(encoding="utf-8")).resultados
        if not _grupos_de_copias(resultados):
            continue
        con_grupos += 1
        carpeta = str(ruta.parent.relative_to(MEDICIONES))
        for antes, despues in zip(resultados, _unificar_copias(resultados), strict=True):
            # 4f nunca mueve un par de tupla ni cambia sus hallazgos.
            assert (antes.pano, antes.rele, antes.hallazgo_pdf, antes.hallazgo_excel) == (
                despues.pano, despues.rele, despues.hallazgo_pdf, despues.hallazgo_excel)
            assert despues.confianza <= antes.confianza
            if antes.estado != despues.estado:
                cambios.add((carpeta, antes.pano, "estado"))
            if antes.tipo_match != despues.tipo_match:
                cambios.add((carpeta, antes.pano, "tipo"))
    assert con_grupos >= 60
    assert cambios == CAMBIOS_DE_CLASE
    assert not any("opus" in c[0] for c in cambios)


def _resultados(carpeta: Path) -> list[Any]:
    return ReporteInforme.model_validate_json(
        (carpeta / "reporte_final.json").read_text(encoding="utf-8")).resultados


def _ordenados(resultados: list[Any]) -> list[str]:
    """Para comparar sin el orden: E5 ordena por estado, y un par que 4f pasa a
    «difiere» cambia de lugar en la lista."""
    return sorted(json.dumps(r, sort_keys=True, ensure_ascii=False)
                  for r in _sin_version([r.model_dump(mode="json") for r in resultados]))


@pytest.fixture
def _config_de_b2_con_4f(monkeypatch: pytest.MonkeyPatch) -> None:
    for campo, valor in (("effort_llm", ""), ("asignacion_global", False),
                         ("descripcion_identica", False), ("control_codigos", False),
                         ("juez_justifica_primero", False), ("unificar_copias", True)):
        monkeypatch.setattr(settings, campo, valor)


@pytest.mark.usefixtures("_config_de_b2_con_4f")
@pytest.mark.parametrize("caso", _casos_con_vectores())
def test_4f_no_cambia_ninguna_llamada_en_b2(caso: Caso, tmp_path: Path) -> None:
    base, salida = _base(caso), tmp_path / "replay"
    meta = reproducir_e4(caso.run_dir, salida, None, vectores=_vectores(caso),
                         cache="estricto", cache_desde=base)

    assert (meta["unificar_copias"], meta["cache_jueces"]["pagadas"],
            meta["cache_jueces"]["sin_usar"]) == (True, 0, 0)
    assert _ordenados(_resultados(salida)) == _ordenados(_unificar_copias(_resultados(base)))


def _repeticiones() -> list[Any]:
    # Las posteriores a PD72 (AG1 y AG2 guardan el texto anterior del motivo del
    # emparejamiento dudoso, que el código de hoy redacta distinto).
    carpetas = [MEDICIONES / "replay_e4" / e for e in ("M30", "M33", "CC")]
    return [pytest.param(r, id=f"{r.parent.name}-{r.name}")
            for c in carpetas if c.is_dir() for r in sorted(c.iterdir())
            if (r / "metadata.json").is_file()] or [
        pytest.param(None, marks=pytest.mark.skip(reason="exento: sin repeticiones de E4"))]


@pytest.mark.parametrize("repeticion", _repeticiones())
def test_4f_no_cambia_ninguna_llamada_en_las_repeticiones(
        repeticion: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    meta_rep = json.loads((repeticion / "metadata.json").read_text(encoding="utf-8"))
    for campo in ("asignacion_global", "descripcion_identica", "control_codigos"):
        monkeypatch.setattr(settings, campo, bool(meta_rep.get(campo, False)))
    monkeypatch.setattr(settings, "effort_llm", "")
    monkeypatch.setattr(settings, "juez_justifica_primero", False)
    monkeypatch.setattr(settings, "unificar_copias", True)
    run = MEDICIONES / "b2" / "runs" / meta_rep["run_origen"]
    vectores = MEDICIONES / "b2" / "vectores_e4" / f"{run.name}.npz"

    meta = reproducir_e4(run, tmp_path / "replay", None, vectores=vectores,
                         cache="estricto", cache_desde=repeticion)

    assert (meta["cache_jueces"]["pagadas"], meta["cache_jueces"]["sin_usar"]) == (0, 0)
    assert _ordenados(_resultados(tmp_path / "replay")) == _ordenados(
        _unificar_copias(_resultados(repeticion)))
