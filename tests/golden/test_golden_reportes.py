"""Reportes medidos: schema actual, polaridad y UI.

- Todos los reporte_final.json (schema 0.5.0 de B0/B1 y 0.6.0 de B2) cargan
  con el ReporteInforme actual: es el contrato del historial de la UI.
- Barrido de `_polaridad` sobre todos los pares (PDF y Excel presentes) de las
  tres rondas congeladas: la única polaridad opuesta real es Alfa E7 (PDF
  "...: Cumple" vs Excel "...: No cumple"). Si el detector empieza a marcar
  otros pares, son "Difiere" forzados sin pasar por el juez: hay que revisarlo.
  Los conteos fijos valen solo para B0-B2; en las rondas siguientes se exige
  que todo par con polaridad opuesta salga "difiere".
- La pantalla de resultados de Streamlit abre reportes reales sin excepciones.
"""

from __future__ import annotations

import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from comparador.config import settings
from comparador.etapa4_matching import _polaridad
from comparador.schemas import CampoDiferente, EstadoHallazgo, FeedbackRun, ReporteInforme
from tests.golden.datos import (
    MEDICIONES,
    RONDAS_CONGELADAS,
    Caso,
    casos,
    leer_json,
    requiere_mediciones,
)

pytestmark = [pytest.mark.golden, requiere_mediciones]

REPORTES = sorted(MEDICIONES.glob("b*/runs/*/reporte_final.json"))
CONGELADOS = [r for r in REPORTES if r.parents[2].name in RONDAS_CONGELADAS]
POSTERIORES = [r for r in REPORTES if r.parents[2].name not in RONDAS_CONGELADAS]
APP = Path(__file__).resolve().parents[2] / "streamlit_app.py"


def _id(ruta: Path) -> str:
    return f"{ruta.parents[2].name}-{ruta.parent.name}"


def test_cantidad_de_reportes_por_version() -> None:
    versiones = Counter(
        (r.parents[2].name, leer_json(r)["schema_version"]) for r in CONGELADOS
    )
    assert versiones == {("b0", "0.5.0"): 21, ("b1", "0.5.0"): 19, ("b2", "0.6.0"): 20}


@pytest.mark.parametrize("ruta", REPORTES, ids=[_id(r) for r in REPORTES])
def test_reporte_carga_con_el_schema_actual(ruta: Path) -> None:
    data = leer_json(ruta)
    reporte = ReporteInforme.model_validate(data)
    assert len(reporte.resultados) == reporte.resumen.total
    if data["schema_version"] == "0.5.0":
        # Los campos de 0.6.0 toman su default (retrocompatibilidad).
        assert reporte.resumen.coinciden_con_redaccion_distinta == 0
        assert all(m.equivalencias_redaccion == [] for m in reporte.resultados)


def _campos_opuestos(resultado: dict[str, Any]) -> list[str]:
    """Campos de texto con polaridad opuesta entre el PDF y el Excel del par."""
    pdf, excel = resultado["hallazgo_pdf"], resultado["hallazgo_excel"]
    campos = []
    for campo in ("descripcion", "accion_correctiva"):
        a, b = pdf.get(campo), excel.get(campo)
        if not (a and b):
            continue
        pa, pb = _polaridad(a), _polaridad(b)
        if pa and pb and pa != pb:
            campos.append(campo)
    return campos


def _pares_opuestos() -> tuple[int, list[tuple[str, str, str, str, str, str]]]:
    """Pares y polaridades opuestas de las rondas congeladas."""
    pares = 0
    opuestos = []
    for ruta in CONGELADOS:
        data = leer_json(ruta)
        for r in data["resultados"]:
            if not (r["hallazgo_pdf"] and r["hallazgo_excel"]):
                continue
            pares += 1
            opuestos += [(ruta.parents[2].name, ruta.parent.name, data["subestacion"],
                          r["pano"], r["rele"], campo) for campo in _campos_opuestos(r)]
    return pares, opuestos


def test_polaridad_opuesta_solo_en_alfa_e7() -> None:
    pares, opuestos = _pares_opuestos()

    assert pares == 3214
    assert {o[2:] for o in opuestos} == {("ALFA", "E7", "SEL 451", "descripcion")}
    # B0 Sonnet, B1 Opus y B2 Opus emparejaron ese par (los demás runs no).
    assert [(o[0], o[1].split("_")[-1]) for o in opuestos] == [
        ("b0", "claude-sonnet-5-5"), ("b1", "claude-opus-5-5"), ("b2", "claude-opus-5-5"),
    ]


def test_b2_reporta_la_polaridad_opuesta_como_difiere() -> None:
    """Desde B2 (control de polaridad en 4e) ese par sale como Difiere con la
    polaridad en el detalle, aunque la similitud supere el umbral."""
    _, opuestos = _pares_opuestos()
    for ronda, run_id, _, pano, rele, campo in opuestos:
        if ronda != "b2":
            continue
        reporte = ReporteInforme.model_validate(
            leer_json(MEDICIONES / ronda / "runs" / run_id / "reporte_final.json"))
        (par,) = [m for m in reporte.resultados if m.pano == pano and m.rele == rele
                  and m.hallazgo_pdf and m.hallazgo_excel
                  and m.hallazgo_pdf.descripcion != m.hallazgo_excel.descripcion
                  and _polaridad(m.hallazgo_pdf.descripcion) == "+"]
        assert par.estado == EstadoHallazgo.DIFIERE
        (diferencia,) = [d for d in par.diferencias if d.campo == CampoDiferente(campo)]
        assert (diferencia.detalle or "").startswith("Polaridad opuesta")


@pytest.mark.parametrize("ruta", [pytest.param(r, id=_id(r)) for r in POSTERIORES] or [
    pytest.param(None, id="sin-rondas-nuevas",
                 marks=pytest.mark.skip(reason="exento: sin rondas posteriores a B2 todavía"))])
def test_rondas_nuevas_reportan_toda_polaridad_opuesta_como_difiere(ruta: Path) -> None:
    """Polaridad opuesta = Diferencia siempre (invariante 19e(a)): ningún par
    con polaridad opuesta sale con ese campo sin diferencia."""
    mal = [(r["pano"], r["rele"], campo, r["estado"])
           for r in leer_json(ruta)["resultados"] if r["hallazgo_pdf"] and r["hallazgo_excel"]
           for campo in _campos_opuestos(r)
           if r["estado"] != "difiere" or campo not in {d["campo"] for d in r["diferencias"]}]
    assert not mal, mal


# Uno por informe y por versión de schema: B1 (0.5.0) y B2 (0.6.0), Sonnet.
CASOS_UI = [c for c in casos("b1", "b2")
            if c.modelo == "claude-sonnet-5-5" and c.tiene("reporte_final.json")]


@pytest.mark.parametrize("caso", CASOS_UI, ids=[c.id for c in CASOS_UI])
def test_ui_abre_el_reporte_real(
    caso: Caso, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # La UI lee el run desde runs_dir: se trabaja sobre una copia en tmp_path
    # para que mediciones/ (datos de las rondas) nunca se modifique (el
    # feedback va a un feedback_dir temporal, tests/conftest.py). Se copian
    # los archivos que la UI lee del run (advertencias de troceo y adecuación)
    # para seguir cubriendo esos avisos.
    run_tmp = tmp_path / caso.run_id
    run_tmp.mkdir()
    origen = MEDICIONES / caso.ronda / "runs" / caso.run_id
    for nombre in ("troceo.json", "adecuacion.json"):
        if (origen / nombre).exists():
            shutil.copyfile(origen / nombre, run_tmp / nombre)
    monkeypatch.setattr(settings, "runs_dir", tmp_path)
    reporte = ReporteInforme.model_validate(caso.json("reporte_final.json"))
    at = AppTest.from_file(str(APP), default_timeout=120)
    at.session_state["reporte"] = reporte
    at.session_state["run_id"] = caso.run_id
    at.session_state["feedback"] = FeedbackRun()

    at.run()

    assert not at.exception, [e.value for e in at.exception]
    tiles: Any = next(m.value for m in at.markdown if 'class="tiles"' in m.value)
    assert f'<div class="val">{reporte.resumen.total}</div>' in tiles
