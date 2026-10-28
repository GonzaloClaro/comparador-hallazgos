"""PD60: la marca «nombra a otro relé» sobre las extracciones guardadas de B2 y B3.

Sin API y sin PDF: por cada sección del ``etapa1_panos.json`` guardado, las
respuestas crudas de E3 pasan por el post-proceso actual (``replay_e3``) y por
``_marcar_otros_reles``; la marca se cruza con el ``reporte_final.json`` del run
por (paño, relé, descripción, acción) y con el GT del comparador
(``evaluar_comparador``). Exige:

1. Las marcas exactas por run: solo Gamma con Opus (B2 y B3) y con Sonnet,
   10 resultados cada uno; los demás informes (Zeta CB33 y Alfa CB20
   incluidos) y Haiku, ninguna.
2. Recall de CB30 (la viñeta del ECAP copiada entera a cada relé): sus 7 D6 con
   Opus y sus 5 con Sonnet llevan la marca.
3. Lo marcado según el GT: Opus {D6: 7, C1: 3}, Sonnet {D6: 5, C1: 3, OK: 2};
   ninguna marca sobre un error real (clase A).

Sin texto de los informes: solo índices, clases y nombres de relé.
"""

from __future__ import annotations

from collections import Counter

import pytest

from comparador.etapa3_extraer_hallazgos import _marcar_otros_reles, _universo_etapa1
from comparador.evaluar_comparador import evaluar_run, gt_del_run
from comparador.schemas import PanoDescubierto, ReporteInforme
from tests.golden.datos import MEDICIONES, Caso, casos, ids, requiere_mediciones
from tests.golden.test_golden_replay_e1_e3 import replay_e3

pytestmark = [pytest.mark.golden, requiere_mediciones]

CASOS = [c for c in casos("b2", "b3") if c.tiene("etapa1_panos.json")
         and c.tiene("etapa3_raw") and c.tiene("reporte_final.json")]
GT_DIR = MEDICIONES / "gt" / "comparador"

ZT, TD, MD = "INGEPAC EF-ZT", "INGEPAC EF-TD", "INGEPAC EF-MD"
# idx del resultado → otros relés nombrados. Opus da los mismos idx en B2 y B3.
OPUS = {2: [ZT], 3: [ZT], 8: [TD], 9: [TD], 14: [ZT, MD], 20: [TD, MD], 47: [ZT],
        48: [ZT], 56: [ZT, TD], 62: [ZT, MD]}
SONNET = {2: [ZT], 3: [ZT], 8: [TD], 9: [TD], 14: [ZT, MD], 19: [TD, MD], 46: [ZT],
          47: [ZT], 56: [ZT, TD], 62: [ZT, MD]}
MARCAS: dict[tuple[str, str], dict[int, list[str]]] = {
    ("b2-opus-Gamma", "claude-opus-5-5"): OPUS,
    ("b3-opus-Gamma", "claude-opus-5-5"): OPUS,
    ("b2-sonnet-Gamma", "claude-sonnet-5-5"): SONNET,
}
# CB30: los «difiere» D6 de la viñeta del ECAP (fila Documentación Técnica de las
# Tablas 4 y 5). Los otros D6 de Gamma son de CB32 y no nombran a otro relé.
CB30 = {"claude-opus-5-5": {3, 9, 14, 20, 48, 56, 62}, "claude-sonnet-5-5": {3, 9, 14, 19, 47}}
CLASES = {"claude-opus-5-5": {"D6": 7, "C1": 3}, "claude-sonnet-5-5": {"D6": 5, "C1": 3, "OK": 2}}


def _marcas(caso: Caso) -> dict[int, list[str]]:
    """idx del resultado → otros relés nombrados, solo los que nombran a alguno."""
    panos = [PanoDescubierto.model_validate(p) for p in caso.json("etapa1_panos.json")]
    universo = _universo_etapa1(panos)
    por_clave: dict[tuple[str, str, str, str | None], list[str]] = {}
    for pano in panos:
        raw = caso.json(f"etapa3_raw/extraer_{pano.nombre.replace('/', '_')}.json")
        for h in _marcar_otros_reles(replay_e3(caso, pano, raw, universo).hallazgos, pano):
            clave = (h.pano, h.rele, h.descripcion, h.accion_correctiva)
            assert h.evidencia.otros_reles_nombrados is not None
            # Un hallazgo repetido en la sección da la misma marca.
            assert por_clave.setdefault(clave, h.evidencia.otros_reles_nombrados) == \
                h.evidencia.otros_reles_nombrados
    reporte = ReporteInforme.model_validate(caso.json("reporte_final.json"))
    marcas = {}
    for idx, m in enumerate(reporte.resultados):
        if m.hallazgo_pdf is None:
            continue
        h = m.hallazgo_pdf
        otros = por_clave[(h.pano, h.rele, h.descripcion, h.accion_correctiva)]
        if otros:
            marcas[idx] = otros
    return marcas


@pytest.mark.parametrize("caso", CASOS, ids=ids(CASOS))
def test_marcas_exactas_por_run(caso: Caso) -> None:
    assert _marcas(caso) == MARCAS.get((caso.id, caso.modelo), {})


@pytest.mark.parametrize("caso", [c for c in CASOS if (c.id, c.modelo) in MARCAS],
                         ids=ids([c for c in CASOS if (c.id, c.modelo) in MARCAS]))
def test_lo_marcado_segun_el_gt(caso: Caso) -> None:
    marcas = _marcas(caso)
    ev = evaluar_run(caso.run_dir, gt_del_run(caso.run_dir, GT_DIR))
    por_idx = {r.idx: r for r in ev.resultados}
    clases = Counter(por_idx[i].subclase or por_idx[i].clase for i in marcas)
    assert clases == CLASES[caso.modelo]
    assert not any(por_idx[i].clase == "A" for i in marcas)
    # Recall de CB30: todos sus D6 llevan la marca.
    cb30 = CB30[caso.modelo]
    assert {i for i in cb30 if por_idx[i].subclase == "D6"} == cb30
    assert cb30 <= set(marcas)


INFORMES = ("Epsilon", "Añañuca", "Zeta", "Alfa", "Beta", "Eta", "Gamma")
# Los 21 runs completos de B2 y B3 (Alfa con Haiku no tiene reporte): el «0 marcas»
# de los demás informes, Zeta (CB33) y Alfa (CB20) incluidos, no pasa por vacío.
ESPERADOS = ({f"b2-{m}-{i}" for m in ("sonnet", "opus", "haiku") for i in INFORMES}
             - {"b2-haiku-Alfa"}) | {"b3-opus-Gamma"}


def test_cubre_los_21_runs_esperados() -> None:
    assert {c.id for c in CASOS} == ESPERADOS
    assert {(c.id, c.modelo) for c in CASOS} >= set(MARCAS)
