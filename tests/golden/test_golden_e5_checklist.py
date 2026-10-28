"""E5 y evaluación del checklist sobre los runs medidos (deterministas, sin LLM).

- E5: consolidar etapa4_matches.json debe reproducir el resumen y el orden de
  resultados de reporte_final.json, en las tres rondas. Desde B0/B1 la Etapa 5
  solo sumó el conteo coinciden_con_redaccion_distinta (0.6.0), que en los
  matches de B0/B1 sin equivalencias_redaccion da 0, igual que el default con
  que se cargan sus reportes 0.5.0.
- Checklist: `evaluar_checklist.evaluar` sobre el checklist guardado de cada
  run de B2 contra el CheckList Revisión humano debe reproducir, punto a punto,
  los ítems de evaluacion_B2.json (mismo mapeo y mismo GT que la medición),
  salvo en las celdas que se corrigieron en las planillas después de B2
  (`metricas_confianza.CELDAS_GT_CORREGIDAS`): ahí debe leer el valor nuevo,
  con su nota de corrección, y ninguna otra celda que lea la evaluación (los
  ítems de los 38 puntos) puede haber cambiado. El resto de la planilla lo
  respaldan los hashes de tasks/equipo/respuestas_v3_celdas.md.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from comparador.config import settings
from comparador.etapa5_consolidar import consolidar_reporte
from comparador.evaluar_checklist import clasificar, evaluar
from comparador.metricas_confianza import CELDAS_GT_CORREGIDAS, clave_informe
from comparador.schemas import (
    ChecklistInforme,
    MatchResult,
    MetadatosInforme,
    ReporteInforme,
    ResultadoChecklist,
)
from tests.golden.datos import (
    MEDICIONES,
    RONDAS_CONGELADAS,
    Caso,
    casos,
    casos_informes,
    ids,
    leer_json,
    requiere_informes,
    requiere_mediciones,
)

pytestmark = [pytest.mark.golden, requiere_mediciones]

# Todo run terminado, también los 3 de B0 que no entraron a evaluacion_B0.json.
RUNS_E5 = sorted(p.parent for p in MEDICIONES.glob("b*/runs/*/etapa4_matches.json")
                 if (p.parent / "reporte_final.json").exists())
FILAS = {(c.ronda, c.run_id): c.fila for c in casos("b0", "b1", "b2")}
CASOS_CHECKLIST = [c for c in casos("b2") if c.fila.get("checklist_gt")]


def test_hay_casos() -> None:
    # Conteo fijo de las rondas congeladas: las nuevas se agregan sin romperlo.
    congelados = [r for r in RUNS_E5 if r.parents[1].name in RONDAS_CONGELADAS]
    assert len(congelados) == 60
    assert sum((r.parents[1].name, r.name) in FILAS for r in congelados) == 57
    assert len(CASOS_CHECKLIST) == 17


@pytest.mark.parametrize("run_dir", RUNS_E5, ids=[f"{r.parents[1].name}-{r.name}" for r in RUNS_E5])
def test_e5_reproduce_el_reporte(run_dir: Path) -> None:
    guardado = ReporteInforme.model_validate(leer_json(run_dir / "reporte_final.json"))
    matches = [MatchResult.model_validate(m) for m in leer_json(run_dir / "etapa4_matches.json")]
    metadatos = MetadatosInforme(
        coordinado=guardado.coordinado, subestacion=guardado.subestacion,
        informe_id=guardado.informe_id, fecha_auditoria=guardado.fecha_auditoria,
        columnas_ausentes=guardado.columnas_ausentes_excel,
    )
    checklist = ChecklistInforme.model_validate(leer_json(run_dir / "checklist.json"))

    nuevo = consolidar_reporte(matches, metadatos, guardado.empresa_auditora, checklist)

    assert nuevo.resumen == guardado.resumen
    assert nuevo.resultados == guardado.resultados
    assert nuevo.checklist == guardado.checklist
    # El resumen también es el que registró la medición.
    fila = FILAS.get((run_dir.parents[1].name, run_dir.name))
    if fila is not None:
        esperado = fila["comparador"]
        assert {k: getattr(nuevo.resumen, k) for k in esperado} == esperado


@requiere_informes
@pytest.mark.parametrize("caso", CASOS_CHECKLIST, ids=ids(CASOS_CHECKLIST))
def test_checklist_reproduce_la_evaluacion_b2(
    caso: Caso, monkeypatch: pytest.MonkeyPatch
) -> None:
    reporte = ReporteInforme.model_validate(caso.json("reporte_final.json"))
    assert ChecklistInforme.model_validate(caso.json("checklist.json")) == reporte.checklist
    gt: Path = casos_informes()[caso.subestacion]["gt"]
    monkeypatch.setattr(settings, "runs_dir", MEDICIONES / caso.ronda / "runs")

    ev = evaluar(caso.run_id, gt)

    medido = caso.fila["checklist_gt"]
    items = [asdict(i) for i in ev.items]
    esperado = _con_celdas_corregidas(caso.subestacion, medido["items"], items)
    assert items == esperado
    assert ev.sin_gt == medido["sin_gt"]
    clases = [i["clasificacion"] for i in esperado]
    assert (len(ev.items), ev.aciertos, ev.no_verificables, ev.falsos_no_cumple,
            ev.falsos_cumple) == (len(esperado), clases.count("acierto"),
                                  clases.count("no_verificable"),
                                  clases.count("falso_no_cumple"), clases.count("falso_cumple"))
    assert reporte.checklist is not None
    assert reporte.checklist.cumplen == caso.fila["checklist_cumplen"]


def _con_celdas_corregidas(
    subestacion: str, medidos: list[dict[str, Any]], nuevos: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Lo medido en B2, con las celdas corregidas el 2026-10-17 en su valor nuevo."""
    corregidas = {p: v for (inf, p), v in CELDAS_GT_CORREGIDAS.items()
                  if inf == clave_informe(subestacion)}
    nuevos_por_punto = {i["numero"]: i for i in nuevos}
    esperado = []
    for item in medidos:
        veredicto = corregidas.pop(item["numero"], None)
        if veredicto is not None:
            assert item["veredicto_gt"] != veredicto  # la medición usó el valor viejo
            obs = nuevos_por_punto[item["numero"]]["observacion_gt"]
            assert obs.startswith("Corregido 2026-10-17"), obs
            item = {**item, "veredicto_gt": veredicto, "observacion_gt": obs,
                    "clasificacion": clasificar(ResultadoChecklist(item["resultado_sistema"]),
                                                veredicto)}
        esperado.append(item)
    assert not corregidas, f"celdas corregidas sin evaluar: {corregidas}"
    return esperado
