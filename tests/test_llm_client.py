"""Tests del cliente LLM: parámetros por modelo, Files API e instrumentación. Sin red."""

import base64
import json
import threading
from typing import Any

import anthropic
import httpx
import openai
import pytest
from pydantic import BaseModel

from comparador.config import settings
from comparador.llm import client
from comparador.llm.client import parametros_thinking


class TestParametrosThinking:
    def test_sonnet_5_5_apaga_con_between_tools(self):
        # "disabled" devuelve 400 en Sonnet 5.5 (verificado contra la API).
        assert parametros_thinking("claude-sonnet-5-5") == {"thinking": {"type": "between_tools"}}

    def test_opus_5_5_no_se_puede_apagar_y_pide_el_resumen(self):
        # Siempre adaptativo (apagarlo es 400): display «summarized» para que los
        # bloques thinking traigan el resumen y no lleguen vacíos (M20).
        adaptativo = {"type": "adaptive", "display": "summarized"}
        assert parametros_thinking("claude-opus-5-5") == {"thinking": adaptativo}
        for effort in ("low", "xhigh"):
            assert parametros_thinking("claude-opus-5-5", effort) == {
                "output_config": {"effort": effort}, "thinking": adaptativo,
            }

    def test_haiku_5_5_y_modelos_previos_usan_disabled(self):
        for modelo in ("claude-haiku-5-5", "claude-sonnet-5", "claude-opus-4-8"):
            assert parametros_thinking(modelo)["thinking"] == {"type": "disabled"}

    def test_haiku_4_5_no_lleva_thinking(self):
        assert parametros_thinking("claude-haiku-4-5") == {}

    @pytest.mark.parametrize("effort", ["xhigh", "max"])
    def test_effort_alto_no_admite_apagado(self, effort: str):
        assert parametros_thinking("claude-sonnet-5-5", effort) == {
            "output_config": {"effort": effort}
        }


class _Resp(BaseModel):
    ok: bool


class _FakeStream:
    def __init__(self, kwargs: dict[str, Any], registro: list[dict[str, Any]]) -> None:
        registro.append(kwargs)

    def __enter__(self) -> "_FakeStream":
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def get_final_message(self) -> Any:
        class _Bloque:
            type = "text"
            text = '{"ok": true}'

        class _Uso:
            input_tokens = 10
            output_tokens = 2
            cache_read_input_tokens = 0

        class _Msg:
            stop_reason = "end_turn"
            model = "claude-sonnet-5-5"
            content = [_Bloque()]
            usage = _Uso()
            parsed_output = _Resp(ok=True)

        return _Msg()


class _FakeAnthropic:
    def __init__(self) -> None:
        self.llamadas: list[dict[str, Any]] = []
        self.subidos: list[tuple[str, bytes]] = []
        self.borrados: list[str] = []
        fake = self

        class _Files:
            def upload(self, file: tuple[str, bytes, str]) -> Any:
                fake.subidos.append((file[0], file[1]))
                return type("F", (), {"id": "file_123"})()

            def delete(self, file_id: str) -> None:
                fake.borrados.append(file_id)

        class _Beta:
            files = _Files()

        class _Messages:
            def stream(self, **kw: Any) -> _FakeStream:
                return _FakeStream(kw, fake.llamadas)

            def count_tokens(self, **kw: Any) -> Any:
                fake.llamadas.append(kw)
                return type("C", (), {"input_tokens": 1234})()

        self.beta = _Beta()
        self.messages = _Messages()


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> _FakeAnthropic:
    f = _FakeAnthropic()
    monkeypatch.setattr(client, "get_client_anthropic", lambda: f)
    return f


class TestFuentePdf:
    def test_pdf_chico_va_inline(self, fake: _FakeAnthropic):
        b64 = base64.b64encode(b"%PDF chico").decode()
        _, meta = client._llamar_anthropic(
            modelo="claude-sonnet-5-5", system_prompt="s", user_prompt="u",
            response_model=_Resp, pdf_base64=b64,
        )
        doc = fake.llamadas[0]["messages"][0]["content"][0]
        assert doc["source"]["type"] == "base64"
        assert meta["pdf_via"] == "base64"
        assert fake.subidos == []

    def test_pdf_grande_va_por_files_api_y_se_borra(
        self, fake: _FakeAnthropic, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(client, "_MAX_B64_INLINE", 10)
        b64 = base64.b64encode(b"%PDF muy grande para inline").decode()
        _, meta = client._llamar_anthropic(
            modelo="claude-sonnet-5-5", system_prompt="s", user_prompt="u",
            response_model=_Resp, pdf_base64=b64, pdf_filename="informe.pdf",
        )
        llamada = fake.llamadas[0]
        assert llamada["messages"][0]["content"][0]["source"] == {
            "type": "file", "file_id": "file_123",
        }
        assert llamada["extra_headers"]["anthropic-beta"] == client._BETA_FILES
        assert fake.subidos == [("informe.pdf", b"%PDF muy grande para inline")]
        assert fake.borrados == ["file_123"]
        assert meta["pdf_via"] == "files_api"

    def test_metadata_registra_modelo_servido_y_thinking(self, fake: _FakeAnthropic):
        _, meta = client._llamar_anthropic(
            modelo="claude-sonnet-5-5", system_prompt="s", user_prompt="u",
            response_model=_Resp, pdf_base64=None,
        )
        assert meta["modelo_servido"] == "claude-sonnet-5-5"
        assert meta["parametros_thinking"] == {"thinking": {"type": "between_tools"}}
        assert fake.llamadas[0]["max_tokens"] == 64000
        # Sonnet con between_tools no razona ni recibe display (sería un 400).
        assert meta["razonamiento_resumen"] is None
        # Sin respuesta HTTP que leer (cliente falso): cero reintentos, sin códigos.
        assert meta["reintentos_sdk"] == 0 and meta["codigos_http_reintentados"] == []

    def test_metadata_registra_el_schema_que_se_mando(self, fake: _FakeAnthropic):
        """El schema del response_model va en la request (output_format): la
        caché de jueces lo compara (cache_jueces)."""
        _, meta = client._llamar_anthropic(
            modelo="claude-sonnet-5-5", system_prompt="s", user_prompt="u",
            response_model=_Resp, pdf_base64=None,
        )
        assert fake.llamadas[0]["output_format"] is _Resp
        assert meta["schema_sha256"] == client.schema_sha256(_Resp)
        assert len(meta["schema_sha256"]) == 64


class _BloqueThinking:
    type = "thinking"
    signature = "firma"

    def __init__(self, texto: str) -> None:
        self.thinking = texto


class TestRazonamientoResumen:
    """M20: con Opus 5.5 el resumen del razonamiento (bloques thinking no vacíos)
    queda en la metadata, solo para diagnóstico; el JSON se sigue leyendo del text."""

    @staticmethod
    def _con_thinking(fake: _FakeAnthropic, monkeypatch: pytest.MonkeyPatch, textos: list[str],
                      stop_reason: str = "end_turn") -> None:
        class _Stream(_FakeStream):
            def get_final_message(self) -> Any:
                msg = super().get_final_message()
                msg.model = "claude-opus-5-5"
                msg.content = [_BloqueThinking(t) for t in textos] + list(msg.content)
                msg.stop_reason = stop_reason
                if stop_reason == "refusal":
                    msg.parsed_output = None
                return msg

        monkeypatch.setattr(fake.messages, "stream", lambda **kw: _Stream(kw, fake.llamadas))

    @staticmethod
    def _llamar() -> Any:
        return client._llamar_anthropic(
            modelo="claude-opus-5-5", system_prompt="s", user_prompt="u",
            response_model=_Resp, pdf_base64=None,
        )

    def test_resumen_queda_en_la_metadata(
        self, fake: _FakeAnthropic, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._con_thinking(fake, monkeypatch, ["Reviso el punto 3.", "", "Concluyo."])
        respuesta, meta = self._llamar()
        assert fake.llamadas[0]["thinking"] == {"type": "adaptive", "display": "summarized"}
        assert meta["razonamiento_resumen"] == ["Reviso el punto 3.", "Concluyo."]
        assert respuesta.ok and meta["response_raw"] == {"ok": True}

    def test_bloques_vacios_no_dejan_resumen(
        self, fake: _FakeAnthropic, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # display «omitted» (o un bloque sin texto): el thinking llega vacío.
        self._con_thinking(fake, monkeypatch, [""])
        _, meta = self._llamar()
        assert meta["razonamiento_resumen"] is None and meta["response_raw"] == {"ok": True}

    def test_refusal_lleva_el_resumen(
        self, fake: _FakeAnthropic, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._con_thinking(fake, monkeypatch, ["Lo pienso."], stop_reason="refusal")
        with pytest.raises(client.LlamadaFallidaError, match="rechazó") as info:
            self._llamar()
        assert info.value.llm_metadata["razonamiento_resumen"] == ["Lo pienso."]


class TestContarTokens:
    def test_cuenta_con_el_pdf_inline(self, fake: _FakeAnthropic):
        b64 = base64.b64encode(b"%PDF chico").decode()
        n = client.contar_tokens_pdf(
            modelo="claude-sonnet-5-5", system_prompt="s", user_prompt="u", pdf_base64=b64,
        )
        assert n == 1234
        assert fake.llamadas[0]["messages"][0]["content"][0]["source"]["type"] == "base64"
        assert fake.subidos == []

    def test_pdf_grande_no_se_sube_a_files_api(
        self, fake: _FakeAnthropic, monkeypatch: pytest.MonkeyPatch
    ):
        # count_tokens rechaza los archivos de Files API (400 real, B0 2026-10-16):
        # el PDF grande se cuenta por partes en troceo, nunca subiéndolo.
        monkeypatch.setattr(client, "_MAX_B64_INLINE", 10)
        b64 = base64.b64encode(b"%PDF muy grande para inline").decode()
        with pytest.raises(ValueError, match="por partes"):
            client.contar_tokens_pdf(
                modelo="claude-sonnet-5-5", system_prompt="s", user_prompt="u", pdf_base64=b64,
            )
        assert fake.subidos == [] and fake.llamadas == []

    def test_modelo_no_claude_falla(self):
        with pytest.raises(ValueError, match="no es un modelo Claude"):
            client.contar_tokens_pdf(
                modelo="gpt-5", system_prompt="s", user_prompt="u", pdf_base64="x",
            )


def _error_stream(tipo: str, status: int = 200) -> anthropic.APIStatusError:
    """Error como el que el SDK lanza al recibir `event: error` con el stream abierto."""
    respuesta = httpx.Response(status, request=httpx.Request("POST", "https://api.anthropic.com"))
    return anthropic.APIStatusError(
        tipo, response=respuesta, body={"type": "error", "error": {"type": tipo}},
    )


class TestReintentosStream:
    @pytest.fixture
    def sin_espera(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(client, "_esperar", lambda s: None)

    def _fallar_primero(self, fake: _FakeAnthropic, monkeypatch: pytest.MonkeyPatch,
                        errores: list[Exception]) -> None:
        original = fake.messages.stream

        def stream(**kw: Any) -> _FakeStream:
            if errores:
                raise errores.pop(0)
            return original(**kw)

        monkeypatch.setattr(fake.messages, "stream", stream)

    def test_overloaded_a_mitad_del_stream_se_reintenta(
        self, fake: _FakeAnthropic, monkeypatch: pytest.MonkeyPatch, sin_espera: None
    ):
        # Con streaming el SDK solo reintenta el POST inicial: un event: error
        # (HTTP 200) o un corte de conexión a mitad del stream los reintenta el cliente.
        self._fallar_primero(fake, monkeypatch, [
            _error_stream("overloaded_error"), httpx.RemoteProtocolError("cortado"),
        ])
        _, meta = client._llamar_anthropic(
            modelo="claude-sonnet-5-5", system_prompt="s", user_prompt="u",
            response_model=_Resp, pdf_base64=None,
        )
        assert meta["reintentos_stream"] == 2

    def test_error_de_request_no_se_reintenta(
        self, fake: _FakeAnthropic, monkeypatch: pytest.MonkeyPatch, sin_espera: None
    ):
        self._fallar_primero(fake, monkeypatch, [_error_stream("invalid_request_error", 400)])
        with pytest.raises(anthropic.APIStatusError):
            client._llamar_anthropic(
                modelo="claude-sonnet-5-5", system_prompt="s", user_prompt="u",
                response_model=_Resp, pdf_base64=None,
            )
        assert fake.llamadas == []

    def test_se_rinde_tras_los_reintentos(
        self, fake: _FakeAnthropic, monkeypatch: pytest.MonkeyPatch, sin_espera: None
    ):
        self._fallar_primero(
            fake, monkeypatch, [_error_stream("overloaded_error")] * (client._MAX_REINTENTOS + 1),
        )
        with pytest.raises(anthropic.APIStatusError):
            client._llamar_anthropic(
                modelo="claude-sonnet-5-5", system_prompt="s", user_prompt="u",
                response_model=_Resp, pdf_base64=None,
            )

    def test_files_api_se_sube_una_vez_aunque_haya_reintento(
        self, fake: _FakeAnthropic, monkeypatch: pytest.MonkeyPatch, sin_espera: None
    ):
        monkeypatch.setattr(client, "_MAX_B64_INLINE", 10)
        self._fallar_primero(fake, monkeypatch, [_error_stream("api_error")])
        b64 = base64.b64encode(b"%PDF muy grande para inline").decode()
        client._llamar_anthropic(
            modelo="claude-sonnet-5-5", system_prompt="s", user_prompt="u",
            response_model=_Resp, pdf_base64=b64,
        )
        assert len(fake.subidos) == 1 and fake.borrados == ["file_123"]


def _sse(eventos: list[dict[str, Any]]) -> httpx.Response:
    cuerpo = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in eventos)
    return httpx.Response(200, headers={"content-type": "text/event-stream"},
                          content=cuerpo.encode())


_INICIO_SSE = {"type": "message_start", "message": {
    "id": "m", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
    "content": [], "stop_reason": None, "stop_sequence": None,
    "usage": {"input_tokens": 50, "output_tokens": 1}}}


def _stream_ok() -> httpx.Response:
    """Respuesta de Opus 5.5 con display «summarized»: bloque thinking y luego el JSON."""
    return _sse([
        _INICIO_SSE,
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "thinking_delta", "thinking": "Reviso el punto."}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "signature_delta", "signature": "firma"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1,
         "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 1,
         "delta": {"type": "text_delta", "text": '{"ok": true}'}},
        {"type": "content_block_stop", "index": 1},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
         "usage": {"output_tokens": 20}},
        {"type": "message_stop"},
    ])


def _stream_cortado_por_sobrecarga() -> httpx.Response:
    """HTTP 200 y después `event: error`: el SDK no lo reintenta, lo reintenta el cliente."""
    return _sse([_INICIO_SSE, {"type": "error", "error": {
        "type": "overloaded_error", "message": "Overloaded"}}])


def _error_http(status: int) -> httpx.Response:
    tipo = "rate_limit_error" if status == 429 else "overloaded_error"
    return httpx.Response(status, headers={"retry-after-ms": "1"},
                          json={"type": "error", "error": {"type": tipo, "message": "x"}})


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """SDK REAL de Anthropic (con el hook de get_client_anthropic) contra
    httpx.MockTransport: responde en orden lo que el test ponga en `cola`, sin
    red y sin clave real."""
    api: dict[str, list[Any]] = {"cola": [], "retry_count": [], "thinking": []}

    def responder(request: httpx.Request) -> httpx.Response:
        api["retry_count"].append(request.headers["x-stainless-retry-count"])
        api["thinking"].append(json.loads(request.content).get("thinking"))
        respuesta: httpx.Response = api["cola"].pop(0)
        return respuesta

    monkeypatch.setattr(settings, "anthropic_api_key", "x")
    sdk = client._crear_cliente_anthropic(transport=httpx.MockTransport(responder))
    monkeypatch.setattr(client, "get_client_anthropic", lambda: sdk)
    monkeypatch.setattr(client, "_esperar", lambda s: None)
    return api


def _llamar_opus() -> tuple[_Resp, dict[str, Any]]:
    return client._llamar_anthropic(
        modelo="claude-opus-5-5", system_prompt="s", user_prompt="u",
        response_model=_Resp, pdf_base64=None,
    )


class TestReintentosDelSdk:
    """M58 (D8): conteo (header x-stainless-retry-count) y códigos (event hook de
    httpx) de los reintentos del SDK, con el SDK real contra httpx.MockTransport."""

    def test_429_reintentado_por_el_sdk_queda_en_la_metadata(
        self, api: dict[str, list[Any]]
    ) -> None:
        api["cola"] += [_error_http(429), _stream_ok()]
        respuesta, meta = _llamar_opus()
        assert api["retry_count"] == ["0", "1"]
        assert meta["reintentos_sdk"] == 1 and meta["codigos_http_reintentados"] == [429]
        assert meta["reintentos_stream"] == 0
        # M20 con el SDK real: el display viaja en la request y el resumen vuelve.
        assert api["thinking"] == [{"type": "adaptive", "display": "summarized"}] * 2
        assert meta["razonamiento_resumen"] == ["Reviso el punto."]
        assert respuesta.ok and meta["response_raw"] == {"ok": True}

        # El registro es por llamada: la siguiente arranca de cero.
        api["cola"].append(_stream_ok())
        _, meta = _llamar_opus()
        assert meta["reintentos_sdk"] == 0 and meta["codigos_http_reintentados"] == []

    def test_suma_los_reintentos_de_cada_intento_de_stream(
        self, api: dict[str, list[Any]]
    ) -> None:
        api["cola"] += [_error_http(529), _stream_cortado_por_sobrecarga(),
                        _error_http(429), _stream_ok()]
        _, meta = _llamar_opus()
        assert api["retry_count"] == ["0", "1", "0", "1"]
        assert meta["reintentos_stream"] == 1
        assert meta["reintentos_sdk"] == 2 and meta["codigos_http_reintentados"] == [529, 429]

    def test_reintentos_del_sdk_agotados_tambien_cuentan(
        self, api: dict[str, list[Any]]
    ) -> None:
        # El SDK se rinde tras sus reintentos (4 × 529) y el cliente reintenta el stream:
        # esos 3 reintentos se leen del header del request que falló.
        api["cola"] += [_error_http(529)] * (client._MAX_REINTENTOS + 1) + [_stream_ok()]
        _, meta = _llamar_opus()
        assert api["retry_count"] == ["0", "1", "2", "3", "0"]
        assert meta["reintentos_stream"] == 1
        assert meta["reintentos_sdk"] == client._MAX_REINTENTOS
        assert meta["codigos_http_reintentados"] == [529] * (client._MAX_REINTENTOS + 1)

    def test_reintentos_agotados_viajan_en_la_excepcion(
        self, api: dict[str, list[Any]]
    ) -> None:
        # Sobrecarga sostenida: el SDK se rinde (4 × 529) en cada uno de los 4
        # intentos de stream del cliente. La excepción sale con su tipo y su
        # mensaje, y con la metadata de la llamada fallida (formato común): las
        # etapas la persisten como raw y metricas_lote cuenta el sobrecargo.
        intentos = client._MAX_REINTENTOS + 1
        api["cola"] += [_error_http(529)] * (intentos * intentos)
        with pytest.raises(anthropic.APIStatusError, match="529|verloaded") as info:
            _llamar_opus()
        meta = info.value.llm_metadata  # type: ignore[attr-defined]
        assert (meta["modelo"], meta["llamada_fallida"]) == ("claude-opus-5-5", True)
        assert meta["error"].startswith(type(info.value).__name__)
        assert meta["reintentos_sdk"] == client._MAX_REINTENTOS * intentos
        assert meta["reintentos_stream"] == client._MAX_REINTENTOS
        assert meta["codigos_http_reintentados"] == [529] * (intentos * intentos)
        assert isinstance(meta["tiempo_segundos"], float)

    def test_error_de_request_tambien_lleva_su_metadata(
        self, api: dict[str, list[Any]]
    ) -> None:
        api["cola"].append(httpx.Response(400, json={
            "type": "error", "error": {"type": "invalid_request_error", "message": "x"}}))
        with pytest.raises(anthropic.BadRequestError) as info:
            _llamar_opus()
        meta = info.value.llm_metadata  # type: ignore[attr-defined]
        assert (meta["reintentos_sdk"], meta["reintentos_stream"]) == (0, 0)
        assert meta["codigos_http_reintentados"] == [400] and meta["llamada_fallida"] is True

    def test_respuesta_que_no_valida_lleva_reintentos_y_resumen(
        self, api: dict[str, list[Any]]
    ) -> None:
        # El SDK valida al cerrar el bloque de texto: la metadata sale del snapshot.
        api["cola"] += [_error_http(429), _sse([
            _INICIO_SSE,
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "thinking_delta", "thinking": "Me quedo sin espacio."}},
            {"type": "content_block_stop", "index": 0},
            {"type": "content_block_start", "index": 1,
             "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 1,
             "delta": {"type": "text_delta", "text": '{"ok": tru'}},
            {"type": "content_block_stop", "index": 1},
        ])]
        with pytest.raises(client.LlamadaFallidaError, match="no valida") as info:
            _llamar_opus()
        meta = info.value.llm_metadata
        assert meta["texto_crudo"] == '{"ok": tru' and meta["usage_parcial"] is True
        assert meta["razonamiento_resumen"] == ["Me quedo sin espacio."]
        assert meta["reintentos_sdk"] == 1 and meta["codigos_http_reintentados"] == [429]

    def test_los_codigos_son_del_hilo_de_la_llamada(self) -> None:
        # Las llamadas corren en hilos del executor (gather, Semaphore(3) de E3).
        with client.codigos_http_reintentados() as codigos:
            otro = threading.Thread(target=client._anotar_codigo_http,
                                    args=(httpx.Response(503),))
            otro.start()
            otro.join()
            client._anotar_codigo_http(httpx.Response(429))
            client._anotar_codigo_http(httpx.Response(200))
        client._anotar_codigo_http(httpx.Response(500))  # fuera de una llamada
        assert codigos == [429]


class TestFilesApiLimpieza:
    def test_falla_al_borrar_no_bota_la_respuesta(
        self, fake: _FakeAnthropic, monkeypatch: pytest.MonkeyPatch
    ):
        def borrar_falla(file_id: str) -> None:
            raise _error_stream("api_error", 500)

        monkeypatch.setattr(client, "_MAX_B64_INLINE", 10)
        monkeypatch.setattr(fake.beta.files, "delete", borrar_falla)
        b64 = base64.b64encode(b"%PDF muy grande para inline").decode()
        respuesta, meta = client._llamar_anthropic(
            modelo="claude-sonnet-5-5", system_prompt="s", user_prompt="u",
            response_model=_Resp, pdf_base64=b64,
        )
        assert respuesta.ok and meta["pdf_via"] == "files_api"


class TestJsonInvalido:
    def test_json_que_no_valida_da_error_legible(
        self, fake: _FakeAnthropic, monkeypatch: pytest.MonkeyPatch
    ):
        def stream(**kw: Any) -> Any:
            raise _Resp.model_validate_json('{"ok": "trunca')  # ValidationError real

        monkeypatch.setattr(fake.messages, "stream", stream)
        with pytest.raises(RuntimeError, match="max_tokens"):
            client._llamar_anthropic(
                modelo="claude-sonnet-5-5", system_prompt="s", user_prompt="u",
                response_model=_Resp, pdf_base64=None,
            )


class TestLlamadaFallidaLlevaSuMetadata:
    """Una respuesta pagada que no sirve viaja en la excepción para persistirse (invariante 20)."""

    @staticmethod
    def _llamar() -> Any:
        return client._llamar_anthropic(
            modelo="claude-sonnet-5-5", system_prompt="s", user_prompt="u",
            response_model=_Resp, pdf_base64=None,
        )

    def test_json_que_no_valida_con_el_stream_real_del_sdk(
        self, fake: _FakeAnthropic, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """MessageStream REAL del SDK con eventos sintéticos: valida el JSON al cerrar el
        bloque de texto, antes del message_delta con stop_reason y output_tokens finales."""
        from anthropic._models import construct_type_unchecked
        from anthropic.lib.streaming._messages import MessageStream
        from anthropic.types import RawMessageStreamEvent

        eventos = [
            {"type": "message_start", "message": {
                "id": "m", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
                "content": [], "stop_reason": None, "stop_sequence": None,
                "usage": {"input_tokens": 900, "output_tokens": 1}}},
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": '{"ok": tru'}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "max_tokens", "stop_sequence": None},
             "usage": {"output_tokens": 64000}},
            {"type": "message_stop"},
        ]

        class _Crudo:
            def __iter__(self) -> Any:
                return iter(construct_type_unchecked(type_=RawMessageStreamEvent, value=e)
                            for e in eventos)

            def close(self) -> None:
                return None

        class _Gestor:
            def __enter__(self) -> MessageStream[Any]:
                return MessageStream(_Crudo(), output_format=_Resp)  # type: ignore[arg-type]

            def __exit__(self, *a: object) -> None:
                return None

        monkeypatch.setattr(fake.messages, "stream", lambda **kw: _Gestor())
        with pytest.raises(client.LlamadaFallidaError, match="no valida") as info:
            self._llamar()
        meta = info.value.llm_metadata
        assert isinstance(info.value, RuntimeError)
        assert meta["llamada_fallida"] is True and meta["modelo"] == "claude-sonnet-5-5"
        assert meta["tokens_prompt"] == 900 and meta["texto_crudo"] == '{"ok": tru'
        # Lo que el SDK todavía no sabe en ese momento no se inventa: queda marcado.
        assert meta["usage_parcial"] is True and "stop_reason" not in meta
        assert "puede estar cortada por max_tokens o ser un rechazo" in str(info.value)

    @pytest.mark.parametrize(("stop_reason", "error"), [
        ("refusal", "rechazó"), ("end_turn", "no devolvió respuesta parseable"),
    ])
    def test_refusal_y_respuesta_vacia_llevan_metadata_completa(
        self, fake: _FakeAnthropic, monkeypatch: pytest.MonkeyPatch, stop_reason: str, error: str
    ) -> None:
        class _StreamSinParseo(_FakeStream):
            def get_final_message(self) -> Any:
                msg = super().get_final_message()
                msg.stop_reason = stop_reason
                msg.parsed_output = None
                return msg

        monkeypatch.setattr(fake.messages, "stream",
                            lambda **kw: _StreamSinParseo(kw, fake.llamadas))
        with pytest.raises(client.LlamadaFallidaError, match=error) as info:
            self._llamar()
        meta = info.value.llm_metadata
        tokens = (meta["tokens_prompt"], meta["tokens_completion"], meta["tokens_total"])
        assert tokens == (10, 2, 12)
        assert meta["llamada_fallida"] is True and meta["stop_reason"] == stop_reason

    def test_no_dispara_el_modelo_de_respaldo(self) -> None:
        assert not issubclass(client.LlamadaFallidaError, client.ERRORES_ACCESO_MODELO)


class TestLlamadaFallidaOpenAI:
    @staticmethod
    def _cliente(monkeypatch: pytest.MonkeyPatch, parse: Any) -> None:
        cliente = type("C", (), {})()
        cliente.beta = type("B", (), {})()
        cliente.beta.chat = type("Ch", (), {})()
        cliente.beta.chat.completions = type("Co", (), {"parse": staticmethod(parse)})()
        monkeypatch.setattr(client, "get_client", lambda: cliente)

    @staticmethod
    def _completion(contenido: str | None, refusal: str | None = None) -> Any:
        from openai.types.chat import ChatCompletion

        return ChatCompletion.model_validate({
            "id": "x", "object": "chat.completion", "created": 0, "model": "gpt-x",
            "choices": [{"index": 0, "finish_reason": "length", "message": {
                "role": "assistant", "content": contenido, "refusal": refusal}}],
            "usage": {"prompt_tokens": 70, "completion_tokens": 5, "total_tokens": 75},
        })

    def _llamar(self) -> Any:
        return client._llamar_openai(modelo="gpt-x", system_prompt="s", user_prompt="u",
                                     response_model=_Resp, pdf_base64=None, pdf_filename="x.pdf")

    def test_respuesta_cortada_por_largo_lleva_sus_tokens(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        completion = self._completion('{"ok": tr')

        def parse(**kw: Any) -> Any:
            raise openai.LengthFinishReasonError(completion=completion)

        self._cliente(monkeypatch, parse)
        with pytest.raises(client.LlamadaFallidaError, match="LengthFinishReasonError") as info:
            self._llamar()
        meta = info.value.llm_metadata
        assert (meta["tokens_prompt"], meta["tokens_completion"]) == (70, 5)
        assert meta["texto_crudo"] == '{"ok": tr' and meta["llamada_fallida"] is True
        assert meta["modelo_servido"] == "gpt-x"

    def test_refusal_lleva_sus_tokens(self, monkeypatch: pytest.MonkeyPatch) -> None:
        completion = self._completion(None, refusal="no puedo")
        respuesta = type("P", (), {"choices": [type("Ch", (), {"message": type(
            "M", (), {"parsed": None, "refusal": "no puedo", "content": None})()})()],
            "usage": completion.usage, "model": "gpt-x"})()
        self._cliente(monkeypatch, lambda **kw: respuesta)
        with pytest.raises(client.LlamadaFallidaError, match="no puedo") as info:
            self._llamar()
        assert info.value.llm_metadata["tokens_total"] == 75
        assert info.value.llm_metadata["modelo_servido"] == "gpt-x"


class TestOpenAIInstrumentado:
    """M58: modelo_servido y códigos HTTP reintentados también en la ruta OpenAI y en
    los embeddings (SDK REAL de OpenAI contra httpx.MockTransport: sin red)."""

    @staticmethod
    def _sdk(monkeypatch: pytest.MonkeyPatch, cola: list[httpx.Response]) -> Any:
        monkeypatch.setattr(settings, "openai_api_key", "x")
        return client._crear_cliente_openai(
            transport=httpx.MockTransport(lambda request: cola.pop(0)))

    @staticmethod
    def _429() -> httpx.Response:
        return httpx.Response(429, headers={"retry-after-ms": "1"},
                              json={"error": {"message": "x", "type": "rate_limit_error"}})

    def test_completion_registra_modelo_servido_y_429(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        completion = {
            "id": "x", "object": "chat.completion", "created": 0, "model": "gpt-x-2026-01-01",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": '{"ok": true}', "refusal": None}}],
            "usage": {"prompt_tokens": 70, "completion_tokens": 5, "total_tokens": 75},
        }
        sdk = self._sdk(monkeypatch, [self._429(), httpx.Response(200, json=completion)])
        monkeypatch.setattr(client, "get_client", lambda: sdk)
        respuesta, meta = client._llamar_openai(
            modelo="gpt-x", system_prompt="s", user_prompt="u", response_model=_Resp,
            pdf_base64=None, pdf_filename="x.pdf")
        assert respuesta.ok and meta["modelo"] == "gpt-x"
        assert meta["modelo_servido"] == "gpt-x-2026-01-01"
        assert meta["codigos_http_reintentados"] == [429]
        assert meta["schema_sha256"] == client.schema_sha256(_Resp)

    def test_429_agotado_viaja_en_la_excepcion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Como en Anthropic: la excepción del SDK sale tal cual, con la metadata
        # de la llamada fallida y los códigos que el SDK reintentó.
        intentos = client._MAX_REINTENTOS + 1
        sdk = self._sdk(monkeypatch, [self._429() for _ in range(intentos)])
        monkeypatch.setattr(client, "get_client", lambda: sdk)
        with pytest.raises(openai.RateLimitError) as info:
            client._llamar_openai(
                modelo="gpt-x", system_prompt="s", user_prompt="u", response_model=_Resp,
                pdf_base64=None, pdf_filename="x.pdf")
        meta = info.value.llm_metadata  # type: ignore[attr-defined]
        assert (meta["modelo"], meta["llamada_fallida"]) == ("gpt-x", True)
        assert meta["codigos_http_reintentados"] == [429] * intentos

    def test_embeddings_registran_modelo_servido_y_429(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from comparador.llm import embeddings

        respuesta = {"object": "list", "model": "embedding-servido",
                     "data": [{"object": "embedding", "index": 0, "embedding": [0.6, 0.8]}],
                     "usage": {"prompt_tokens": 3, "total_tokens": 3}}
        sdk = self._sdk(monkeypatch, [self._429(), httpx.Response(200, json=respuesta)])
        monkeypatch.setattr(embeddings, "get_client", lambda: sdk)
        vectores, usage = embeddings.calcular_embeddings(["texto"])
        assert vectores.tolist() == [[0.6, 0.8]]
        assert usage is not None and usage["modelo"] == settings.modelo_embeddings
        assert usage["modelo_servido"] == "embedding-servido"
        assert usage["codigos_http_reintentados"] == [429]


class TestPruebaClaveOpenAI:
    """PD66: antes de la primera llamada pagada a Claude, un embedding de una
    palabra comprueba que la clave de OpenAI responde (SDK REAL contra
    httpx.MockTransport: sin red). Si no, error claro en español con la causa."""

    @staticmethod
    def _sdk(monkeypatch: pytest.MonkeyPatch, responder: Any) -> list[httpx.Request]:
        from comparador.llm import embeddings

        pedidos: list[httpx.Request] = []

        def _manejar(request: httpx.Request) -> httpx.Response:
            pedidos.append(request)
            return responder()

        monkeypatch.setattr(settings, "openai_api_key", "x")
        sdk = client._crear_cliente_openai(transport=httpx.MockTransport(_manejar))
        monkeypatch.setattr(embeddings, "get_client", lambda: sdk)
        return pedidos

    def test_exito_registra_modelo_servido_y_tokens(self, monkeypatch: pytest.MonkeyPatch):
        from comparador.llm import embeddings

        respuesta = {"object": "list", "model": "text-embedding-3-large-servido",
                     "data": [{"object": "embedding", "index": 0, "embedding": [0.6, 0.8]}],
                     "usage": {"prompt_tokens": 1, "total_tokens": 1}}
        pedidos = self._sdk(monkeypatch, lambda: httpx.Response(200, json=respuesta))

        prueba = embeddings.probar_clave_openai()

        assert json.loads(pedidos[0].content)["input"] == [embeddings.PALABRA_PRUEBA]
        assert len(pedidos) == 1
        assert {k: v for k, v in prueba.items() if k != "segundos"} == {
            "ok": True, "modelo": settings.modelo_embeddings,
            "modelo_servido": "text-embedding-3-large-servido", "tokens": 1}
        assert prueba["segundos"] >= 0

    def test_clave_rechazada(self, monkeypatch: pytest.MonkeyPatch):
        from comparador.llm import embeddings

        cuerpo = {"error": {"message": "Incorrect API key provided", "type":
                            "invalid_request_error", "code": "invalid_api_key"}}
        pedidos = self._sdk(monkeypatch, lambda: httpx.Response(401, json=cuerpo))

        with pytest.raises(embeddings.ClaveOpenAIError) as info:
            embeddings.probar_clave_openai()

        mensaje = str(info.value)
        assert mensaje.startswith("La clave de OpenAI no responde: ¿sin fondos o revocada?")
        assert "autenticación rechazada (401)" in mensaje and "AuthenticationError" in mensaje
        assert isinstance(info.value.__cause__, openai.AuthenticationError)
        assert len(pedidos) == 1   # un 401 no se reintenta

    def test_sin_fondos(self, monkeypatch: pytest.MonkeyPatch):
        from comparador.llm import embeddings

        cuerpo = {"error": {"message": "You exceeded your current quota, please check your "
                            "plan and billing details.", "type": "insufficient_quota",
                            "code": "insufficient_quota"}}
        self._sdk(monkeypatch, lambda: httpx.Response(
            429, headers={"retry-after-ms": "1"}, json=cuerpo))

        with pytest.raises(embeddings.ClaveOpenAIError) as info:
            embeddings.probar_clave_openai()

        mensaje = str(info.value)
        assert "¿sin fondos o revocada?" in mensaje
        assert "sin fondos o cuota agotada (429 insufficient_quota)" in mensaje
        assert isinstance(info.value.__cause__, openai.RateLimitError)

    def test_usa_la_funcion_que_recibe(self) -> None:
        """El pipeline le pasa la función que usará E4 (la que reemplazan los
        tests): la prueba la cubre el mismo falso."""
        import numpy as np

        from comparador.llm import embeddings

        vistos: list[list[str]] = []

        def _calcular(textos: list[str]) -> tuple[Any, dict[str, Any]]:
            vistos.append(textos)
            return np.ones((1, 3)), {"modelo_servido": "falso", "tokens_total": 2}

        prueba = embeddings.probar_clave_openai(_calcular)

        assert vistos == [[embeddings.PALABRA_PRUEBA]]
        assert (prueba["ok"], prueba["modelo_servido"], prueba["tokens"]) == (True, "falso", 2)

    def test_una_respuesta_sin_vector_no_es_una_clave_que_responde(self) -> None:
        import numpy as np

        from comparador.llm import embeddings

        with pytest.raises(embeddings.ClaveOpenAIError, match="sin el vector"):
            embeddings.probar_clave_openai(lambda textos: (np.zeros((0, 0)), None))


class TestRespaldoQueNoRecibeElPdf:
    """El PDF se adecúa para MODELO_EXTRACCION (convertir.adecuar_pdf_para_llm):
    si el principal no está disponible y el respaldo no es Claude de 1M, el
    PDF se comprueba antes de llamarlo — nunca se le manda uno que no le cabe."""

    @staticmethod
    def _pdf(paginas: int) -> str:
        import io

        from pypdf import PdfWriter

        escritor = PdfWriter()
        for _ in range(paginas):
            escritor.add_blank_page(width=200, height=200)
        buffer = io.BytesIO()
        escritor.write(buffer)
        return base64.b64encode(buffer.getvalue()).decode()

    @staticmethod
    def _sin_acceso_al_principal(monkeypatch: pytest.MonkeyPatch, respaldo: str) -> list[str]:
        llamados: list[str] = []

        def _principal(**kw: Any) -> Any:
            llamados.append(kw["modelo"])
            resp = httpx.Response(404, request=httpx.Request("POST", "https://x"))
            raise anthropic.NotFoundError("model not found", response=resp, body=None)

        def _otro(**kw: Any) -> Any:
            llamados.append(kw["modelo"])
            return _Resp(ok=True), {"modelo": kw["modelo"]}

        monkeypatch.setattr(client, "_llamar_anthropic", _principal)
        monkeypatch.setattr(client, "_llamar_openai", _otro)
        monkeypatch.setattr(client.settings, "modelo_extraccion_fallback", respaldo)
        return llamados

    def _llamar(self, pdf_base64: str | None) -> tuple[Any, dict[str, Any]]:
        return client.llamar_llm_estructurado(
            modelo="claude-opus-5-5", system_prompt="s", user_prompt="u",
            response_model=_Resp, pdf_base64=pdf_base64)

    def test_pdf_que_no_cabe_falla_antes_de_llamar_al_respaldo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from comparador.convertir import PdfExcedeLimitesError

        llamados = self._sin_acceso_al_principal(monkeypatch, "gpt-5.5")
        with pytest.raises(PdfExcedeLimitesError, match="101 páginas") as error:
            self._llamar(self._pdf(101))
        assert llamados == ["claude-opus-5-5"]
        assert isinstance(error.value.__cause__, anthropic.NotFoundError)

    def test_pdf_que_cabe_va_al_respaldo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        llamados = self._sin_acceso_al_principal(monkeypatch, "gpt-5.5")
        _, meta = self._llamar(self._pdf(100))
        assert llamados == ["claude-opus-5-5", "gpt-5.5"]
        assert meta["modelo_solicitado"] == "claude-opus-5-5"

    def test_sin_pdf_no_se_comprueba(self, monkeypatch: pytest.MonkeyPatch) -> None:
        llamados = self._sin_acceso_al_principal(monkeypatch, "gpt-5.5")
        self._llamar(None)
        assert llamados == ["claude-opus-5-5", "gpt-5.5"]

    def test_haiku_4_tiene_los_limites_de_otros(self) -> None:
        from comparador.convertir import exceso_de_limites

        pdf = base64.b64decode(self._pdf(101))
        assert exceso_de_limites(pdf, "claude-haiku-4-5") == (
            "tiene 101 páginas y acepta hasta 100")
        assert exceso_de_limites(pdf, "claude-sonnet-5-5") is None

    def test_el_tamano_tambien_cuenta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from comparador import convertir
        from comparador.convertir import PdfExcedeLimitesError, exceso_de_limites

        pdf = base64.b64decode(self._pdf(3))
        monkeypatch.setattr(convertir, "MAX_BYTES_OTROS", len(pdf) - 1)
        assert exceso_de_limites(pdf, "gpt-5.5") == (
            f"pesa {len(pdf) / 1e6:.1f} MB y acepta hasta {(len(pdf) - 1) / 1e6:.0f} MB")
        assert exceso_de_limites(pdf, "claude-opus-5-5") is None
        # Y el cliente no le pasa ese PDF al respaldo.
        llamados = self._sin_acceso_al_principal(monkeypatch, "gpt-5.5")
        with pytest.raises(PdfExcedeLimitesError, match="pesa"):
            self._llamar(self._pdf(3))
        assert llamados == ["claude-opus-5-5"]
