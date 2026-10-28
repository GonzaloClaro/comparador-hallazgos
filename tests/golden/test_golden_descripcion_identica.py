"""M30 (DESCRIPCION_IDENTICA) sobre B2, sin API: donde el Excel copia el PDF
(Beta y Eta, Ensaut) y en Epsilon, el paso 4a' empareja sin juez todo lo
que hoy va al juez de emparejamiento, con los mismos pares que B2.

Corre E4 con el código de hoy, los vectores recalculados de B2 (D1, estrictos) y
un juez que falla si se lo llama; el juez de redacción va apagado (no es lo que
se mide). Compara solo el emparejamiento (qué hallazgo del PDF va con qué fila
del Excel), no los estados.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from comparador.config import settings
from comparador.etapa4_matching import ejecutar_matching
from comparador.persistence import cargar_vectores
from comparador.reproducir_e4 import _hallazgos
from comparador.schemas import ReporteInforme, TipoMatch
from tests.golden.datos import MEDICIONES, casos, ids, requiere_mediciones

pytestmark = [pytest.mark.golden, requiere_mediciones]

# Informe → llamadas al juez de emparejamiento que el paso evita en B2 (las de hoy,
# con cualquier modelo: el Excel copia el PDF).
EVITADAS = {"Beta": 182, "Eta": 33, "Epsilon": 9}
CASOS = [c for c in casos("b2") if c.modelo in ("claude-sonnet-5-5", "claude-opus-5-5")
         and c.subestacion in EVITADAS and c.tiene("reporte_final.json")]


def _pares(resultados: list[Any]) -> set[tuple[str, str, int | None, int | None, str]]:
    return {
        (r.pano, r.rele, r.hallazgo_pdf.evidencia.pagina_pdf,
         r.hallazgo_excel.evidencia.fila_excel, r.hallazgo_pdf.descripcion)
        for r in resultados if r.hallazgo_pdf is not None and r.hallazgo_excel is not None
    }


def _sin_juez(**_: Any) -> Any:
    raise AssertionError("con DESCRIPCION_IDENTICA no debería quedar nada para el juez")


def test_cubre_los_informes_y_modelos() -> None:
    assert {(c.subestacion, c.modelo) for c in CASOS} == {
        (s, m) for s in EVITADAS for m in ("claude-sonnet-5-5", "claude-opus-5-5")}


@pytest.mark.parametrize("caso", CASOS, ids=ids(CASOS))
def test_mismos_pares_sin_juez(caso: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    vectores_npz = MEDICIONES / "b2" / "vectores_e4" / f"{caso.run_id}.npz"
    vectores, _ = cargar_vectores(Path(vectores_npz))
    monkeypatch.setattr(settings, "descripcion_identica", True)
    monkeypatch.setattr(settings, "juez_redaccion", False)
    pdf, excel = _hallazgos(caso.run_dir)

    resultados, metas = ejecutar_matching(
        pdf, excel, vectores=vectores, vectores_estrictos=True, llamar=_sin_juez)

    b2 = ReporteInforme.model_validate(caso.json("reporte_final.json"))
    assert _pares(resultados) == _pares(b2.resultados)
    assert [m for m in metas if m.get("etapa") != "embeddings"] == []
    # Lo que en B2 fue al juez (no por unicidad) ahora sale con el tipo nuevo.
    juez_b2 = sum(r.tipo_match in (TipoMatch.SEMANTICO_ALTO, TipoMatch.SEMANTICO_BAJO)
                  for r in b2.resultados)
    identicos = sum(r.tipo_match == TipoMatch.DESCRIPCION_IDENTICA for r in resultados)
    assert juez_b2 == identicos
    assert len(list((caso.run_dir / "etapa4_llm_judge_raw").glob("judge_*.json"))) == (
        EVITADAS[caso.subestacion])
