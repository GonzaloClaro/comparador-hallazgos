"""M61: la llamada del checklist por la API de Batch (CHECKLIST_BATCH).

SDK REAL de Anthropic contra httpx.MockTransport (sin red ni clave real): el lote
lleva exactamente los parámetros del stream de hoy, el PDF grande va por Files
API y se borra recién cuando el lote termina, y todo lo que no es un resultado
válido falla ruidosamente con la metadata de la llamada.
"""

import base64
import json
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from comparador.config import Settings, settings
from comparador.llm import client
from tests.test_llm_client import _Resp, _stream_ok

LOTE = "msgbatch_1"
URL_RESULTADOS = f"https://api.anthropic.com/v1/messages/batches/{LOTE}/results"
MENSAJE = {
    "id": "m", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
    "content": [{"type": "thinking", "thinking": "Reviso el punto.", "signature": "firma"},
                {"type": "text", "text": '{"ok": true}'}],
    "stop_reason": "end_turn", "stop_sequence": None,
    "usage": {"input_tokens": 50, "output_tokens": 20},
}


def _exito(mensaje: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"type": "succeeded", "message": mensaje or MENSAJE}


def _lote(estado: str) -> dict[str, Any]:
    terminado = estado == "ended"
    return {
        "id": LOTE, "type": "message_batch", "processing_status": estado,
        "request_counts": {"processing": 0 if terminado else 1, "succeeded": int(terminado),
                           "errored": 0, "canceled": 0, "expired": 0},
        "created_at": "2026-10-26T00:00:00Z", "expires_at": "2026-10-27T00:00:00Z",
        "results_url": URL_RESULTADOS if terminado else None,
    }


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Responde según el endpoint. `consultas`: estados que devuelve cada retrieve
    (el último se repite: results() vuelve a consultar el lote)."""
    api: dict[str, Any] = {"eventos": [], "cuerpos": {}, "headers": {},
                           "consultas": ["in_progress", "ended"], "resultado": _exito()}

    def responder(request: httpx.Request) -> httpx.Response:
        metodo, ruta = request.method, request.url.path
        api["eventos"].append((metodo, ruta))
        if metodo == "POST" and ruta == "/v1/messages":
            api["cuerpos"]["stream"] = json.loads(request.content)
            return _stream_ok()
        if metodo == "POST" and ruta == "/v1/messages/batches":
            api["cuerpos"]["lote"] = json.loads(request.content)
            api["headers"]["lote"] = dict(request.headers)
            return httpx.Response(200, json=_lote("in_progress"))
        if metodo == "GET" and ruta == f"/v1/messages/batches/{LOTE}":
            consultas = api["consultas"]
            return httpx.Response(200, json=_lote(
                consultas.pop(0) if len(consultas) > 1 else consultas[0]))
        if metodo == "GET" and ruta == f"/v1/messages/batches/{LOTE}/results":
            linea = json.dumps({"custom_id": client._CUSTOM_ID_LOTE, "result": api["resultado"]})
            return httpx.Response(200, content=(linea + "\n").encode())
        if metodo == "POST" and ruta == f"/v1/messages/batches/{LOTE}/cancel":
            return httpx.Response(200, json=_lote("canceling"))
        if metodo == "POST" and ruta == "/v1/files":
            return httpx.Response(200, json={
                "id": "file_123", "type": "file", "filename": "informe.pdf",
                "mime_type": "application/pdf", "size_bytes": 10,
                "created_at": "2026-10-26T00:00:00Z"})
        if metodo == "DELETE" and ruta == "/v1/files/file_123":
            return httpx.Response(200, json={"id": "file_123", "type": "file_deleted"})
        raise AssertionError(f"Endpoint inesperado: {metodo} {ruta}")

    monkeypatch.setattr(settings, "anthropic_api_key", "x")
    sdk = client._crear_cliente_anthropic(transport=httpx.MockTransport(responder))
    monkeypatch.setattr(client, "get_client_anthropic", lambda: sdk)
    monkeypatch.setattr(client, "_esperar", lambda s: None)
    return api


def _llamar(batch: bool, pdf_base64: str | None = None) -> tuple[_Resp, dict[str, Any]]:
    return client.llamar_llm_estructurado(
        modelo="claude-opus-5-5", system_prompt="s", user_prompt="u",
        response_model=_Resp, pdf_base64=pdf_base64, pdf_filename="informe.pdf", batch=batch,
    )


class TestPedidoDelLote:
    def test_lleva_los_mismos_parametros_que_el_stream(self, api: dict[str, Any]) -> None:
        pdf = base64.b64encode(b"%PDF chico").decode()
        _llamar(batch=False, pdf_base64=pdf)
        _llamar(batch=True, pdf_base64=pdf)
        stream = dict(api["cuerpos"]["stream"])
        assert stream.pop("stream") is True
        (pedido,) = api["cuerpos"]["lote"]["requests"]
        assert pedido["custom_id"] == client._CUSTOM_ID_LOTE
        # Mismo modelo, max_tokens, thinking, system, mensajes (PDF incluido) y schema.
        assert pedido["params"] == stream
        assert pedido["params"]["output_config"]["format"]["type"] == "json_schema"

    def test_con_effort_el_formato_se_suma_al_output_config(
        self, api: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "effort_llm", "high")
        _llamar(batch=False)
        _llamar(batch=True)
        stream = dict(api["cuerpos"]["stream"])
        stream.pop("stream")
        (pedido,) = api["cuerpos"]["lote"]["requests"]
        assert pedido["params"] == stream
        assert pedido["params"]["output_config"]["effort"] == "high"

    def test_pdf_grande_va_por_files_api_y_se_borra_al_terminar_el_lote(
        self, api: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(client, "_MAX_B64_INLINE", 10)
        _, meta = _llamar(batch=True, pdf_base64=base64.b64encode(b"%PDF muy grande").decode())
        (pedido,) = api["cuerpos"]["lote"]["requests"]
        assert pedido["params"]["messages"][0]["content"][0]["source"] == {
            "type": "file", "file_id": "file_123"}
        assert api["headers"]["lote"]["anthropic-beta"] == client._BETA_FILES
        eventos = api["eventos"]
        # El archivo se borra después de leer los resultados, nunca antes.
        assert eventos.index(("DELETE", "/v1/files/file_123")) > eventos.index(
            ("GET", f"/v1/messages/batches/{LOTE}/results"))
        assert meta["pdf_via"] == "files_api"


class TestResultado:
    def test_exito_devuelve_lo_mismo_que_el_stream_mas_el_lote(
        self, api: dict[str, Any]
    ) -> None:
        resp_stream, meta_stream = _llamar(batch=False)
        resp, meta = _llamar(batch=True)
        assert resp == resp_stream and resp.ok
        assert (meta["via_llm"], meta["batch_id"]) == ("batch", LOTE)
        assert meta["tiempo_en_cola_segundos"] >= 0
        assert "via_llm" not in meta_stream and "batch_id" not in meta_stream
        for campo in ("modelo", "modelo_servido", "stop_reason", "tokens_prompt",
                      "tokens_completion", "tokens_total", "parametros_thinking",
                      "schema_sha256", "system_prompt", "user_prompt_text", "pdf_incluido",
                      "pdf_via", "response_raw", "razonamiento_resumen"):
            assert meta[campo] == meta_stream[campo], campo
        assert meta["tokens_prompt"] == 50 and meta["tokens_completion"] == 20
        # Esperó el fin del lote: create → retrieve (en curso) → retrieve (terminado).
        consultas = [e for e in api["eventos"] if e == ("GET", f"/v1/messages/batches/{LOTE}")]
        assert len(consultas) >= 2

    @pytest.mark.parametrize("resultado", [
        {"type": "errored", "error": {"type": "error", "error": {
            "type": "invalid_request_error", "message": "pedido inválido"}}},
        {"type": "expired"},
        {"type": "canceled"},
    ])
    def test_lote_sin_exito_falla_con_su_metadata(
        self, api: dict[str, Any], resultado: dict[str, Any]
    ) -> None:
        api["resultado"] = resultado
        with pytest.raises(client.LlamadaFallidaError, match=resultado["type"]) as info:
            _llamar(batch=True)
        meta = info.value.llm_metadata
        assert meta["llamada_fallida"] is True and meta["batch_id"] == LOTE
        assert meta["via_llm"] == "batch"

    def test_respuesta_que_no_valida_falla_con_sus_tokens(self, api: dict[str, Any]) -> None:
        malo = {**MENSAJE, "content": [{"type": "text", "text": '{"ok": "quizás"}'}]}
        api["resultado"] = _exito(malo)
        with pytest.raises(client.LlamadaFallidaError, match="no valida") as info:
            _llamar(batch=True)
        meta = info.value.llm_metadata
        assert (meta["tokens_prompt"], meta["tokens_completion"]) == (50, 20)
        assert meta["texto_crudo"] == '{"ok": "quizás"}' and meta["batch_id"] == LOTE

    def test_refusal_falla_con_su_metadata(self, api: dict[str, Any]) -> None:
        api["resultado"] = _exito({**MENSAJE, "stop_reason": "refusal", "content": []})
        with pytest.raises(client.LlamadaFallidaError, match="refusal") as info:
            _llamar(batch=True)
        assert info.value.llm_metadata["batch_id"] == LOTE

    def test_espera_agotada_cancela_el_lote_y_falla(
        self, api: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(client, "_ESPERA_MAXIMA_LOTE_SEGUNDOS", 0)
        api["consultas"] = ["in_progress"]
        with pytest.raises(client.LlamadaFallidaError, match="cancel") as info:
            _llamar(batch=True)
        assert ("POST", f"/v1/messages/batches/{LOTE}/cancel") in api["eventos"]
        assert info.value.llm_metadata["batch_id"] == LOTE


class TestSinBatch:
    def test_apagado_no_toca_la_api_de_batch(self, api: dict[str, Any]) -> None:
        _llamar(batch=False)
        assert not [e for e in api["eventos"] if "batches" in e[1]]

    def test_modelo_no_claude_con_batch_falla(self) -> None:
        with pytest.raises(ValueError, match="Batch"):
            client.llamar_llm_estructurado(
                modelo="gpt-5", system_prompt="s", user_prompt="u",
                response_model=_Resp, batch=True)

    @pytest.mark.parametrize("campos", [
        {"modelo_extraccion": "gpt-5"},
        {"modelo_extraccion_fallback": "gpt-5"},
    ])
    def test_config_con_modelo_no_claude_falla_al_arrancar(
        self, campos: dict[str, str]
    ) -> None:
        with pytest.raises(ValidationError, match="CHECKLIST_BATCH"):
            Settings(checklist_batch=True, **campos)  # type: ignore[arg-type]
