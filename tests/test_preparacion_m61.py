"""Ensayo con falsos de la ronda M61 (checklist por la API de Batch), sin API.

Corre la CLI de ``evaluar_lote`` como se correrá M61 (``--solo-checklist
--checklist-batch``, Opus, con su copia congelada de ``src/``; carpeta ``b4`` y
etiqueta B4, la convención de las rondas que leen metricas_lote y los golden) en un temporal,
sobre el caso sintético del ensayo de B3, y después ``metricas_lote``. El SDK de
Anthropic es falso solo en la frontera: el cliente real arma el lote. Comprueba
que lo guardado responde cada pregunta de M61: que la llamada fue por Batch (con
su lote y su tiempo en cola), su costo a precio de Batch, y el checklist contra
la planilla (que no se le atribuye a Batch).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from comparador import etapa0_checklist as e0
from comparador import fichas
from comparador.config import settings
from comparador.llm import client as llm_client
from comparador.metricas_lote import Resultado, cargar_precios, generar
from tests.test_integracion_pipeline import _crear_excel, _crear_pdf
from tests.test_metricas_lote import _leer_csv
from tests.test_persistence import copiar_src
from tests.test_preparacion_b3 import (
    CARPETA,
    INFORME,
    OPUS,
    PRECIOS,
    _AnthropicFalso,
    _correr_cli,
    _Linea,
    _planilla,
)

LOTE = "msgbatch_m61"


class _AnthropicConBatch(_AnthropicFalso):
    """El SDK falso del ensayo de B3 con ``messages.batches``: el lote queda en
    curso en la primera consulta y termina en la segunda."""

    def __init__(self, linea: _Linea) -> None:
        super().__init__(linea)
        self.lotes: list[dict[str, Any]] = []
        self.consultas = 0
        falso = self

        class _Batches:
            def create(self, *, requests: list[dict[str, Any]], **_: Any) -> Any:
                falso.lotes.append({"requests": requests})
                return SimpleNamespace(id=LOTE, processing_status="in_progress")

            def retrieve(self, lote: str) -> Any:
                falso.consultas += 1
                estado = "ended" if falso.consultas >= 2 else "in_progress"
                return SimpleNamespace(id=lote, processing_status=estado)

            def results(self, lote: str) -> Iterator[Any]:
                (pedido,) = falso.lotes[-1]["requests"]
                mensaje = falso._responder(falso._como_stream(pedido["params"]))
                yield SimpleNamespace(custom_id=pedido["custom_id"], result=SimpleNamespace(
                    type="succeeded", message=mensaje))

            def cancel(self, lote: str) -> Any:
                raise AssertionError("el ensayo no cancela lotes")

        self.messages.batches = _Batches()  # type: ignore[attr-defined]

    @staticmethod
    def _como_stream(params: dict[str, Any]) -> dict[str, Any]:
        """Los kwargs del stream que equivalen al lote: el modelo de respuesta
        según el schema del pedido (el lote no lleva la clase Pydantic)."""
        formato = params["output_config"]["format"]
        modelos: list[type[BaseModel]] = [e0._ChecklistConCitaResponse, e0._ChecklistResponse]
        (modelo,) = [m for m in modelos if llm_client._formato_salida(m) == formato]
        return {**params, "output_format": modelo}


@dataclass
class Ensayo:
    mediciones: Path
    csv: Path
    resultado: Resultado
    anthropic: _AnthropicConBatch

    def evaluacion(self) -> dict[str, Any]:
        datos: dict[str, Any] = json.loads(
            (self.mediciones / "b4" / "evaluacion_B4.json").read_text(encoding="utf-8"))
        return datos

    def run(self) -> Path:
        (fila,) = self.evaluacion()["resultados"][OPUS]
        return self.mediciones / "b4" / "runs" / fila["run_id"]

    def tabla(self, nombre: str, **filtro: str) -> list[dict[str, str]]:
        return [f for f in _leer_csv(self.csv / nombre)
                if all(f[k] == v for k, v in filtro.items())]


@pytest.fixture(scope="module")
def ensayo(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Ensayo]:
    raiz = tmp_path_factory.mktemp("ensayo_m61")
    med = raiz / "mediciones"
    with pytest.MonkeyPatch.context() as mp:
        for campo, valor in (("openai_api_key", ""), ("anthropic_api_key", "sk-falsa"),
                             ("modelo_extraccion", OPUS), ("modelo_extraccion_fallback", ""),
                             ("effort_llm", ""), ("cita_checklist", True),
                             ("checklist_batch", False), ("umbral_tokens_troceo", 900_000)):
            mp.setattr(settings, campo, valor)
        anthropic = _AnthropicConBatch(_Linea())
        mp.setattr(llm_client, "get_client_anthropic", lambda: anthropic)
        mp.setattr(llm_client, "_esperar", lambda s: None)
        mp.setattr(fichas, "RUTA_DEFAULT", raiz / "sin_fichas.yaml")

        caso = raiz / "informes_reales" / CARPETA
        caso.mkdir(parents=True)
        _crear_pdf(caso / "Informe Sintético.pdf")
        _crear_excel(caso / "Tabla de Hallazgos Sintética.xlsx")  # el caso lo exige
        _planilla(caso / "CheckList Revisión Sintética.xlsx")
        _correr_cli(mp, med / "b4" / "runs", [
            "--modelos", OPUS, "--base", str(raiz / "informes_reales"), "--informes", INFORME,
            "--etiqueta", "B4", "--salida", str(med / "b4" / "evaluacion_B4.json"),
            "--solo-checklist", "--checklist-batch",
            "--codigo-congelado", str(copiar_src(med / "b4" / "src"))])

        csv = raiz / "csv"
        resultado = generar(med, PRECIOS, csv)
        yield Ensayo(med, csv, resultado, anthropic)


def test_la_llamada_fue_por_batch_y_solo_por_batch(ensayo: Ensayo) -> None:
    (lote,) = ensayo.anthropic.lotes
    (pedido,) = lote["requests"]
    assert pedido["params"]["model"] == OPUS
    assert ensayo.anthropic.pedidos  # el resultado salió del lote, no de un stream aparte
    (raw,) = (ensayo.run() / "checklist_raw").glob("*.json")
    meta = json.loads(raw.read_text(encoding="utf-8"))
    assert (meta["via_llm"], meta["batch_id"]) == ("batch", LOTE)
    assert meta["tiempo_en_cola_segundos"] >= 0


def test_la_configuracion_queda_registrada(ensayo: Ensayo) -> None:
    assert ensayo.evaluacion()["config"]["checklist_batch"] is True
    metadata = json.loads((ensayo.run() / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["checklist_batch"] is True and metadata["modo"] == "solo_checklist"


def test_costo_a_precio_de_batch(ensayo: Ensayo) -> None:
    assert ensayo.resultado.discrepancias == []
    (fila,) = ensayo.tabla("costo_por_informe_etapa.csv", ronda="B4", etapa="checklist")
    entrada, salida = int(fila["tokens_input"]), int(fila["tokens_output"])
    (tramo,) = cargar_precios(PRECIOS)[OPUS].tramos
    assert tramo.batch_input is not None and tramo.batch_output is not None
    esperado = (entrada * tramo.batch_input + salida * tramo.batch_output) / 1e6
    assert float(fila["costo_usd"]) == pytest.approx(esperado, abs=1e-6)
    en_linea = (entrada * tramo.input + salida * tramo.output) / 1e6  # type: ignore[operator]
    assert float(fila["costo_usd"]) == pytest.approx(en_linea / 2, abs=1e-6)


def test_checklist_contra_la_planilla(ensayo: Ensayo) -> None:
    (fila,) = ensayo.tabla("checklist_por_informe.csv", ronda="B4")
    assert fila["informe"] == INFORME and int(fila["evaluados"]) > 0
