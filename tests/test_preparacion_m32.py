"""Ensayo con falsos de M32 (justificar antes de elegir), sin API.

Como se correrá M32 (paso 6), en un temporal: una ronda «B2» sintética con la
configuración de hoy (``evaluar_lote``), la base con caché estricta desde el run
(M32B: con el mismo código, todo sale de la caché) y la variante con
JUEZ_JUSTIFICA_PRIMERO, con caché mixta desde la base (M32V): el preflight no llama
ni escribe; cada consulta al juez de emparejamiento se paga (otro schema y otro
prompt) y lleva el schema de la variante; lo que no cambia del juez de redacción
sale de la caché; ``metricas_lote`` registra el interruptor. Los falsos están en
la frontera con los proveedores, como en ``tests/test_preparacion_m43.py``.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from comparador import evaluar_lote, fichas, reproducir_e4
from comparador.config import settings
from comparador.etapa4_matching import _JuezResponse, _JuezResponseJustificaPrimero
from comparador.llm import client as llm_client
from comparador.llm import embeddings as llm_embeddings
from comparador.llm.client import schema_sha256
from comparador.llm.prompts import system_juez_matching
from comparador.metricas_lote import generar
from comparador.schemas import ReporteInforme
from tests.test_integracion_pipeline import _crear_excel, _crear_pdf
from tests.test_metricas_lote import _leer_csv
from tests.test_preparacion_b3 import (
    _LLMB3,
    CARPETA,
    EMBEDDINGS,
    INFORME,
    OPUS,
    PRECIOS,
    _AnthropicFalso,
    _Linea,
    _OpenAIFalso,
)


@dataclass
class Ensayo:
    run: Path
    base: Path
    variante: Path
    linea_preflight: list[str]
    linea_variante: list[str]
    csv: Path

    def meta(self, carpeta: Path) -> dict[str, Any]:
        datos: dict[str, Any] = json.loads((carpeta / "metadata.json").read_text("utf-8"))
        return datos


def _cli(mp: pytest.MonkeyPatch, modulo: Any, argumentos: list[str]) -> None:
    mp.setattr(sys, "argv", [modulo.__name__.rsplit(".", 1)[-1], *argumentos])
    modulo.main()


def _raws(carpeta: Path, prefijo: str) -> list[dict[str, Any]]:
    return [json.loads(p.read_text("utf-8")) for p in sorted(
        carpeta.glob(f"etapa4_*_raw/{prefijo}_*.json"), key=lambda p: int(p.stem.split("_")[1]))]


@pytest.fixture(scope="module")
def ensayo(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Ensayo]:
    raiz = tmp_path_factory.mktemp("ensayo_m32")
    med = raiz / "mediciones"
    with pytest.MonkeyPatch.context() as mp:
        # La configuración de hoy (asignación global, descripción idéntica y control de
        # códigos encendidos), con la variante apagada, no la del .env de quien corre.
        for campo, valor in (("openai_api_key", "sk-falsa"), ("anthropic_api_key", "sk-falsa"),
                             ("modelo_extraccion", OPUS), ("modelo_extraccion_fallback", ""),
                             ("modelo_juez_matching", ""), ("modelo_embeddings", EMBEDDINGS),
                             ("effort_llm", ""), ("juez_redaccion", True),
                             ("asignacion_global", True), ("descripcion_identica", True),
                             ("control_codigos", True), ("unificar_copias", True),
                             ("juez_justifica_primero", False),
                             ("runs_dir", med / "b2" / "runs")):
            mp.setattr(settings, campo, valor)
        linea = _Linea()
        anthropic = _AnthropicFalso(linea)
        anthropic.llm = _LLMB3()
        openai_falso = _OpenAIFalso(linea)
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

        # M32B: la base con caché estricta desde el propio run (gratis).
        base = med / "replay_e4" / "M32B" / run.name
        _cli(mp, reproducir_e4, [str(run), "--salida", str(base), "--cache", "estricto"])

        # M32V: la variante con caché mixta desde la base.
        mp.setattr(settings, "juez_justifica_primero", True)
        variante = med / "replay_e4" / "M32V" / run.name
        banderas = [str(run), "--salida", str(variante), "--cache", "mixto",
                    "--cache-desde", str(base)]
        linea.llamadas = []
        _cli(mp, reproducir_e4, [*banderas, "--preflight"])
        linea_preflight = list(linea.llamadas)
        _cli(mp, reproducir_e4, banderas)
        linea_variante = list(linea.llamadas)

        csv = raiz / "csv"
        generar(med, PRECIOS, csv)
        yield Ensayo(run, base, variante, linea_preflight, linea_variante, csv)


def test_la_base_sale_entera_de_la_cache_y_reproduce_el_run(ensayo: Ensayo) -> None:
    cache = ensayo.meta(ensayo.base)["cache_jueces"]
    assert (cache["modo"], cache["pagadas"], cache["sin_usar"]) == ("estricto", 0, 0)
    assert ensayo.meta(ensayo.base)["juez_justifica_primero"] is False

    def resultados(carpeta: Path) -> list[dict[str, Any]]:
        rep = ReporteInforme.model_validate_json(
            (carpeta / "reporte_final.json").read_text("utf-8"))
        return [r.model_dump(mode="json") for r in rep.resultados]

    assert resultados(ensayo.base) == resultados(ensayo.run)


def test_el_preflight_no_llama(ensayo: Ensayo) -> None:
    assert ensayo.linea_preflight == []


def test_la_variante_paga_cada_consulta_del_juez_con_su_schema(ensayo: Ensayo) -> None:
    jueces = _raws(ensayo.variante, "judge")
    assert jueces, "el escenario necesita al menos una consulta al juez de emparejamiento"
    assert all(not j.get("desde_cache") for j in jueces)
    assert {j["schema_sha256"] for j in jueces} == {schema_sha256(_JuezResponseJustificaPrimero)}
    assert {j["system_prompt"] for j in jueces} == {system_juez_matching(True)}
    # La base, con el schema de siempre.
    assert {j["schema_sha256"] for j in _raws(ensayo.base, "judge")} == {
        schema_sha256(_JuezResponse)}
    assert ensayo.linea_variante.count("claude:_JuezResponse") == len(jueces)
    meta = ensayo.meta(ensayo.variante)
    assert meta["juez_justifica_primero"] is True
    assert meta["cache_jueces"]["pagadas"] >= len(jueces)


def test_metricas_lote_registra_el_interruptor(ensayo: Ensayo) -> None:
    filas = {f["etiqueta"]: f for f in _leer_csv(ensayo.csv / "replay_e4.csv")}
    assert (filas["M32B"]["juez_justifica_primero"], filas["M32V"]["juez_justifica_primero"]) == (
        "False", "True")
    assert {filas[e]["descripcion_identica"] for e in ("M32B", "M32V")} == {"True"}
    assert float(filas["M32V"]["costo_usd"]) > float(filas["M32B"]["costo_usd"]) == 0
