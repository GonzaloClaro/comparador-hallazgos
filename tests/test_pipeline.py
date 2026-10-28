"""Tests del orquestador: preflight de credenciales, persistencia de E4 y relojes."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from comparador.config import settings
from comparador.pipeline import (
    CredencialesFaltantesError,
    _guardar_metas_e4,
    _reloj,
    _tokens_e4,
    _validar_credenciales,
)


class TestPreflightCredenciales:
    def test_sin_openai_falla_siempre(self, monkeypatch: pytest.MonkeyPatch):
        # Los embeddings son siempre OpenAI: sin esa key el run moriría en la
        # Etapa 4 después de gastar todos los tokens de extracción.
        monkeypatch.setattr(settings, "openai_api_key", "")
        monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-x")
        monkeypatch.setattr(settings, "modelo_extraccion", "claude-sonnet-5")
        with pytest.raises(CredencialesFaltantesError, match="OPENAI_API_KEY"):
            _validar_credenciales()

    def test_modelo_claude_sin_anthropic_falla(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "openai_api_key", "sk-x")
        monkeypatch.setattr(settings, "anthropic_api_key", "")
        monkeypatch.setattr(settings, "modelo_extraccion", "claude-sonnet-5")
        monkeypatch.setattr(settings, "modelo_juez_matching", "")
        with pytest.raises(CredencialesFaltantesError, match="ANTHROPIC_API_KEY"):
            _validar_credenciales()

    def test_todo_openai_no_exige_anthropic(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "openai_api_key", "sk-x")
        monkeypatch.setattr(settings, "anthropic_api_key", "")
        monkeypatch.setattr(settings, "modelo_extraccion", "gpt-5")
        monkeypatch.setattr(settings, "modelo_juez_matching", "")
        _validar_credenciales()

    def test_juez_claude_exige_anthropic(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "openai_api_key", "sk-x")
        monkeypatch.setattr(settings, "anthropic_api_key", "")
        monkeypatch.setattr(settings, "modelo_extraccion", "gpt-5")
        monkeypatch.setattr(settings, "modelo_juez_matching", "claude-sonnet-5")
        with pytest.raises(CredencialesFaltantesError, match="ANTHROPIC_API_KEY"):
            _validar_credenciales()

    def test_fallback_claude_exige_anthropic(self, monkeypatch: pytest.MonkeyPatch):
        # El fallback puede ejecutarse en cualquier llamada: su key también
        # se valida ANTES de gastar tokens, no al momento del fallback.
        monkeypatch.setattr(settings, "openai_api_key", "sk-x")
        monkeypatch.setattr(settings, "anthropic_api_key", "")
        monkeypatch.setattr(settings, "modelo_extraccion", "gpt-5")
        monkeypatch.setattr(settings, "modelo_juez_matching", "")
        monkeypatch.setattr(settings, "modelo_extraccion_fallback", "claude-sonnet-5")
        with pytest.raises(CredencialesFaltantesError, match="ANTHROPIC_API_KEY"):
            _validar_credenciales()


class TestMetasE4:
    METAS = [
        {"etapa": "embeddings", "tokens_total": 1000},
        {"tokens_total": 10, "response_raw": "juez A"},
        {"tipo": "juez_redaccion", "tokens_total": 300, "response_raw": "lote 1"},
        {"tokens_total": 20, "response_raw": "juez B"},
        {"tipo": "juez_redaccion", "tokens_total": 400, "response_raw": "lote 2"},
    ]

    def test_redaccion_en_su_carpeta_y_judge_contiguos(self, tmp_path: Path):
        # Invariante 20: cada llamada pagada queda persistida; la numeración
        # del juez de matching no se corre por las llamadas de redacción.
        _guardar_metas_e4(tmp_path, self.METAS)

        judge = tmp_path / "etapa4_llm_judge_raw"
        redaccion = tmp_path / "etapa4_redaccion_raw"
        assert sorted(p.name for p in judge.iterdir()) == [
            "embeddings.json", "judge_0.json", "judge_1.json",
        ]
        assert sorted(p.name for p in redaccion.iterdir()) == [
            "redaccion_0.json", "redaccion_1.json",
        ]
        assert json.loads((judge / "judge_1.json").read_text())["response_raw"] == "juez B"
        assert json.loads((redaccion / "redaccion_1.json").read_text())["response_raw"] == "lote 2"

    def test_tokens_por_origen_sin_solaparse(self):
        assert _tokens_e4(self.METAS) == {
            "tokens_e4": 30,
            "tokens_e4_redaccion": 700,
            "tokens_embeddings": 1000,
        }


class TestPreflightSoloChecklist:
    """Modo solo checklist (medición de B3): sin embeddings ni juez, OpenAI solo
    hace falta si el modelo lo es."""

    def test_claude_sin_openai_pasa(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "openai_api_key", "")
        monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-x")
        monkeypatch.setattr(settings, "modelo_extraccion", "claude-opus-5-5")
        monkeypatch.setattr(settings, "modelo_extraccion_fallback", "")
        monkeypatch.setattr(settings, "modelo_juez_matching", "gpt-5")  # no participa
        _validar_credenciales(solo_checklist=True)

    def test_gpt_sin_openai_falla(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "openai_api_key", "")
        monkeypatch.setattr(settings, "modelo_extraccion", "gpt-5")
        monkeypatch.setattr(settings, "modelo_extraccion_fallback", "")
        with pytest.raises(CredencialesFaltantesError, match="OPENAI_API_KEY"):
            _validar_credenciales(solo_checklist=True)

    def test_claude_sin_anthropic_falla(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "openai_api_key", "")
        monkeypatch.setattr(settings, "anthropic_api_key", "")
        monkeypatch.setattr(settings, "modelo_extraccion", "claude-opus-5-5")
        monkeypatch.setattr(settings, "modelo_extraccion_fallback", "")
        with pytest.raises(CredencialesFaltantesError, match="ANTHROPIC_API_KEY"):
            _validar_credenciales(solo_checklist=True)


class TestReloj:
    def test_inicio_con_microsegundos(self) -> None:
        # Truncado al segundo no ordena etapas que arrancan en el mismo segundo
        # (camino crítico desde los relojes, M58).
        relojes: dict[str, dict[str, Any]] = {}
        with _reloj(relojes, "e1"):
            pass
        inicio = datetime.strptime(relojes["e1"]["inicio"], "%Y-%m-%dT%H:%M:%S.%f")
        assert abs((datetime.now() - inicio).total_seconds()) < 60
        assert relojes["e1"]["segundos"] >= 0
