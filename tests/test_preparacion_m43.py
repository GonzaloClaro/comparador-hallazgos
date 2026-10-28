"""Ensayo con falsos de M43 (comparador.sensibilidad), sin API.

Como se correrá M43, en un temporal: una ronda «B2» sintética (``evaluar_lote``),
el control (``reproducir_e4`` del run sin perturbar), la copia del run con el
etapa2 perturbado (``sensibilidad preparar``), la pasada con la caché del control
(``reproducir_e4 --cache-desde``) y ``sensibilidad evaluar``. Comprueba que la
copia sirve a ``reproducir_e4`` (se llama como el run_id), que la pasada reutiliza
del control lo que no cambió y que los errores que decide el código salen
detectados. Los falsos están en la frontera con los proveedores, como en
``tests/test_preparacion_ag1.py``.
"""

from __future__ import annotations

import csv
import json
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from comparador import evaluar_lote, fichas, reproducir_e4, sensibilidad
from comparador.config import settings
from comparador.etapa4_matching import clave_tupla
from comparador.llm import client as llm_client
from comparador.llm import embeddings as llm_embeddings
from comparador.schemas import EstadoHallazgo, ReporteInforme
from tests.test_integracion_pipeline import _crear_excel, _crear_pdf
from tests.test_preparacion_b3 import (
    _LLMB3,
    CARPETA,
    EMBEDDINGS,
    INFORME,
    OPUS,
    _AnthropicFalso,
    _Linea,
    _OpenAIFalso,
)


@dataclass
class Ensayo:
    run: Path
    m43: Path
    errores: list[sensibilidad.ErrorInyectado]
    salida_json: dict[str, Any]
    filas_csv: list[dict[str, str]]


def _cli(mp: pytest.MonkeyPatch, modulo: Any, argumentos: list[str]) -> None:
    mp.setattr(sys, "argv", [modulo.__name__.rsplit(".", 1)[-1], *argumentos])
    modulo.main()


def _errores(run: Path, control: Path) -> list[sensibilidad.ErrorInyectado]:
    """Un error por tipo determinista y un neutro, sobre «coincide» del control en
    tuplas distintas (como el catálogo real: uno por unidad)."""
    reporte = ReporteInforme.model_validate_json(
        (control / run.name / "reporte_final.json").read_text("utf-8"))
    blancos, tuplas = [], set()
    for r in reporte.resultados:
        h = r.hallazgo_excel
        if (r.estado == EstadoHallazgo.COINCIDE and h is not None and h.calificacion is not None
                and clave_tupla(r.pano, r.rele) not in tuplas):
            tuplas.add(clave_tupla(r.pano, r.rele))
            blancos.append(h)
    assert len(blancos) >= 3, "el escenario necesita 3 «coincide» en tuplas distintas"
    cal, pan, neu = blancos[:3]
    otra = "Relevante" if cal.calificacion.value == "Menor" else "Menor"  # type: ignore[union-attr]

    def error(id_: str, tipo: str, h: Any, valor: str | None, estado: str,
              campos: list[str] | None = None) -> sensibilidad.ErrorInyectado:
        return sensibilidad.ErrorInyectado.model_validate({
            "id": id_, "informe": INFORME, "run_id": run.name, "tipo": tipo,
            "blanco": {"pano": h.pano, "rele": h.rele, "fila": h.evidencia.fila_excel},
            "valor_nuevo": valor, "esperado": {"estado": estado, "campos": campos or []},
            "nota": "ensayo"})

    return [error("cal", "calificacion", cal, otra, "difiere", ["calificacion"]),
            error("pan", "pano", pan, "ZZ9", "falta_en_excel"),
            error("neu", "neutro", neu, neu.descripcion.upper(), "coincide")]


@pytest.fixture(scope="module")
def ensayo(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Ensayo]:
    raiz = tmp_path_factory.mktemp("ensayo_m43")
    med = raiz / "mediciones"
    with pytest.MonkeyPatch.context() as mp:
        for campo, valor in (("openai_api_key", "sk-falsa"), ("anthropic_api_key", "sk-falsa"),
                             ("modelo_extraccion", OPUS), ("modelo_extraccion_fallback", ""),
                             ("modelo_juez_matching", ""), ("modelo_embeddings", EMBEDDINGS),
                             ("effort_llm", ""), ("juez_redaccion", True),
                             ("asignacion_global", True), ("descripcion_identica", True),
                             ("runs_dir", med / "b2" / "runs")):
            mp.setattr(settings, campo, valor)
        anthropic = _AnthropicFalso(_Linea())
        anthropic.llm = _LLMB3()
        openai_falso = _OpenAIFalso(_Linea())
        mp.setattr(llm_client, "get_client_anthropic", lambda: anthropic)
        mp.setattr(llm_client, "get_client", lambda: openai_falso)
        mp.setattr(llm_embeddings, "get_client", lambda: openai_falso)
        mp.setattr(fichas, "RUTA_DEFAULT", raiz / "sin_fichas.yaml")

        caso = raiz / "informes_reales" / CARPETA
        caso.mkdir(parents=True)
        _crear_pdf(caso / "Informe Sintético.pdf")
        _crear_excel(caso / "Tabla de Hallazgos Sintética.xlsx")
        _cli(mp, evaluar_lote, [
            "--modelos", OPUS, "--base", str(raiz / "informes_reales"), "--informes", INFORME,
            "--etiqueta", "B2", "--salida", str(med / "b2" / "evaluacion_B2.json")])
        (fila,) = json.loads((med / "b2" / "evaluacion_B2.json").read_text("utf-8"))[
            "resultados"][OPUS]
        run = med / "b2" / "runs" / fila["run_id"]

        m43 = med / "m43"
        _cli(mp, reproducir_e4, [str(run), "--salida", str(m43 / "control" / run.name),
                                 "--cache", "mixto"])
        errores = _errores(run, m43 / "control")
        catalogo = m43 / "catalogo.json"
        catalogo.write_text(sensibilidad.Catalogo(fecha="2026-10-27", errores=errores)
                            .model_dump_json(indent=2), "utf-8")
        sensibilidad.main(["preparar", "--catalogo", str(catalogo), "--runs-b2",
                           str(run.parent), "--destino", str(m43 / "runs")])
        _cli(mp, reproducir_e4, [str(m43 / "runs" / run.name), "--salida",
                                 str(m43 / "pasada1" / run.name), "--cache", "mixto",
                                 "--cache-desde", str(m43 / "control" / run.name)])
        sensibilidad.main(["evaluar", "--catalogo", str(catalogo), "--control",
                           str(m43 / "control"), "--pasadas", str(m43 / "pasada1"),
                           "--json", str(m43 / "evaluacion.json"),
                           "--csv", str(raiz / "sensibilidad_m43.csv")])
        with (raiz / "sensibilidad_m43.csv").open(encoding="utf-8") as f:
            filas_csv = list(csv.DictReader(f))
        yield Ensayo(run, m43, errores,
                     json.loads((m43 / "evaluacion.json").read_text("utf-8")), filas_csv)


def test_la_copia_sirve_a_reproducir_e4_y_reutiliza_el_control(ensayo: Ensayo) -> None:
    meta = json.loads((ensayo.m43 / "pasada1" / ensayo.run.name / "metadata.json")
                      .read_text("utf-8"))
    assert meta["run_origen"] == ensayo.run.name and meta["modo"] == "replay_e4"
    assert meta["cache_jueces"]["desde_cache"] > 0
    # Nada quedó en runs/ ni en replay_e4/ (fuera de metricas_lote y de los golden).
    assert not (ensayo.m43.parent / "replay_e4").exists()


def test_lo_que_decide_el_codigo_sale_detectado(ensayo: Ensayo) -> None:
    clases = {e["id"]: e["clases"] for e in ensayo.salida_json["errores"]}
    assert (clases["cal"], clases["pan"]) == (["detectado"], ["detectado"])
    # Los embeddings falsos dan similitud 0 entre textos distintos (también si solo
    # cambian las mayúsculas): el ensayo comprueba que el neutro se evalúa, no qué da;
    # qué da con los vectores reales es lo que mide M43.
    assert clases["neu"][0] in ("sin_alerta", "falsa_alarma")
    assert ensayo.salida_json["cambios_fuera_de_los_blancos"] == [
        {"pasada": "pasada1", "cambios": 0}]


def test_el_csv_agregado(ensayo: Ensayo) -> None:
    assert {(f["tipo"], f["decide"], f["detectados"], f["evaluables"])
            for f in ensayo.filas_csv} == {("calificacion", "codigo", "1", "1"),
                                           ("pano", "estructura", "1", "1"),
                                           ("neutro", "control", "0", "1")}
