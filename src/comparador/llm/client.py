"""Wrapper de clientes LLM (OpenAI y Anthropic) con PDFs y structured outputs.

El proveedor se decide por el nombre del modelo: "claude-*" va a Anthropic,
el resto a OpenAI. Los embeddings siempre van a OpenAI (Anthropic no ofrece
API de embeddings).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import random
import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, TypeVar, cast

import anthropic
import httpx
import openai
from anthropic.lib._parse._transform import transform_schema
from openai import OpenAI
from pydantic import BaseModel, TypeAdapter, ValidationError

from comparador.config import settings
from comparador.convertir import PdfExcedeLimitesError, exceso_de_limites

T = TypeVar("T", bound=BaseModel)

_client: OpenAI | None = None
_client_anthropic: anthropic.Anthropic | None = None


logger = logging.getLogger(__name__)

# Reintentos de transitorios del request HTTP inicial (rate limit, timeout,
# 5xx/529, conexión) los maneja el SDK: backoff exponencial con jitter y
# respeto de Retry-After. Con streaming, los errores que llegan DESPUÉS del
# HTTP 200 (event: error overloaded/api_error, corte de conexión a mitad del
# stream) el SDK no los reintenta: los reintenta _llamar_anthropic.
_MAX_REINTENTOS = 3

# Errores de acceso al modelo que habilitan el fallback: key inválida (401),
# key sin permisos sobre el modelo (403) o modelo inexistente para esa cuenta
# (404). Los transitorios NO están acá — esos se reintentan, no se cambia de
# modelo.
ERRORES_ACCESO_MODELO = (
    openai.AuthenticationError,
    openai.PermissionDeniedError,
    openai.NotFoundError,
    anthropic.AuthenticationError,
    anthropic.PermissionDeniedError,
    anthropic.NotFoundError,
)


# Los códigos HTTP de los reintentos del SDK (M58): el SDK reintenta 408, 409,
# 429 y 5xx por su cuenta y solo lo escribe en el log. Un event hook de httpx
# anota los códigos no 2xx en un registro por hilo: las llamadas corren en
# hilos del executor (gather del pipeline, Semaphore(3) de E3) sobre el mismo
# cliente, y cada una abre su registro con `codigos_http_reintentados()`.
_registro_http = threading.local()


def _anotar_codigo_http(response: httpx.Response) -> None:
    """Event hook de httpx: corre en el hilo que hizo el request."""
    codigos: list[int] | None = getattr(_registro_http, "codigos", None)
    if codigos is not None and not response.is_success:
        codigos.append(response.status_code)


@contextmanager
def codigos_http_reintentados() -> Iterator[list[int]]:
    """Códigos no 2xx que recibe este hilo mientras dura el bloque. En una
    llamada que termina con respuesta, cada uno fue reintentado (por el SDK o
    por el bucle de stream de _llamar_anthropic). Los reintentos por error de
    conexión no tienen código: solo cuentan en reintentos_sdk."""
    codigos: list[int] = []
    _registro_http.codigos = codigos
    try:
        yield codigos
    finally:
        _registro_http.codigos = None


def _http_instrumentado(transport: httpx.BaseTransport | None) -> dict[str, Any]:
    """kwargs del cliente httpx del SDK: el hook y, solo en tests, un transporte
    simulado (httpx.MockTransport, sin red). Sin transporte el DefaultHttpxClient
    del SDK arma el suyo (keepalive TCP, proxies del entorno)."""
    kwargs: dict[str, Any] = {"event_hooks": {"response": [_anotar_codigo_http]}}
    if transport is not None:
        kwargs["transport"] = transport
    return kwargs


def _crear_cliente_openai(transport: httpx.BaseTransport | None = None) -> OpenAI:
    return OpenAI(
        api_key=settings.openai_api_key, max_retries=_MAX_REINTENTOS,
        http_client=openai.DefaultHttpxClient(**_http_instrumentado(transport)),
    )


def _crear_cliente_anthropic(transport: httpx.BaseTransport | None = None) -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key=settings.anthropic_api_key, max_retries=_MAX_REINTENTOS,
        http_client=anthropic.DefaultHttpxClient(**_http_instrumentado(transport)),
    )


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = _crear_cliente_openai()
    return _client


def get_client_anthropic() -> anthropic.Anthropic:
    global _client_anthropic
    if _client_anthropic is None:
        _client_anthropic = _crear_cliente_anthropic()
    return _client_anthropic


def pdf_a_base64(ruta: Path) -> str:
    data = ruta.read_bytes()
    return base64.b64encode(data).decode("utf-8")


def sha256_de_schema(schema: dict[str, Any]) -> str:
    """sha256 de un JSON schema, sin ordenar las claves: el orden de las
    propiedades es el orden en que genera el modelo (también el de los campos
    opcionales, que `required` no lista)."""
    texto = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def schema_sha256(response_model: type[BaseModel]) -> str:
    """Huella del schema que va en la request (output_format en Anthropic,
    response_format en OpenAI): queda en el raw de cada llamada y la caché de
    jueces la compara (cache_jueces)."""
    return sha256_de_schema(response_model.model_json_schema())


def llamar_llm_estructurado(
    *,
    modelo: str,
    system_prompt: str,
    user_prompt: str,
    response_model: type[T],
    pdf_base64: str | None = None,
    pdf_filename: str = "documento.pdf",
    batch: bool = False,
) -> tuple[T, dict[str, Any]]:
    """Llama al LLM con structured outputs y opcionalmente un PDF.

    Con `batch` (solo Claude, M61) la misma request va por la API de Batch:
    mitad de precio, y espera a que el lote termine.

    Returns:
        Tupla de (respuesta parseada, metadata con raw response y tiempos).
    """
    if batch and not modelo.startswith("claude"):
        raise ValueError(f"La API de Batch es de Anthropic; '{modelo}' no es un modelo Claude")
    try:
        if modelo.startswith("claude"):
            return _llamar_anthropic(
                modelo=modelo,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=response_model,
                pdf_base64=pdf_base64,
                pdf_filename=pdf_filename,
                batch=batch,
            )
        return _llamar_openai(
            modelo=modelo,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=response_model,
            pdf_base64=pdf_base64,
            pdf_filename=pdf_filename,
        )
    except ERRORES_ACCESO_MODELO as exc:
        fallback = settings.modelo_extraccion_fallback
        if not fallback or fallback == modelo:
            raise
        # El PDF se adecuó para MODELO_EXTRACCION, no para el respaldo: si al
        # respaldo no le cabe, fallar antes de llamarlo (nunca se recorta).
        exceso = (exceso_de_limites(base64.b64decode(pdf_base64), fallback)
                  if pdf_base64 is not None else None)
        if exceso:
            raise PdfExcedeLimitesError(
                f"El modelo {modelo} no está disponible ({type(exc).__name__}) y el modelo de "
                f"respaldo {fallback} no recibe este PDF: {exceso}. No se recorta: usa como "
                "respaldo un modelo Claude de 1M de contexto o resuelve el acceso al principal."
            ) from exc
        # Vía el router (no directo a un proveedor): el fallback puede ser de
        # cualquier proveedor. La recursión es de profundidad 1 — en la
        # llamada interna modelo == fallback y se relanza.
        respuesta, metadata = llamar_llm_estructurado(
            modelo=fallback,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=response_model,
            pdf_base64=pdf_base64,
            pdf_filename=pdf_filename,
            batch=batch,
        )
        metadata["modelo_solicitado"] = modelo
        metadata["fallback_por_error"] = str(exc)
        return respuesta, metadata


_EFFORT_SIN_APAGADO = ("xhigh", "max")


def parametros_thinking(modelo: str, effort: str = "") -> dict[str, Any]:
    """thinking/effort de la request según el modelo.

    Para extracción estructurada el razonamiento se apaga donde la API lo
    permite (consume max_tokens sin mejorar el JSON), pero cada generación
    lo expresa distinto:
    - claude-opus-5-5: no se puede apagar (400) — se controla con effort. Pide
      display «summarized» para guardar el resumen del razonamiento en la
      metadata (M20, solo diagnóstico): con el default («omitted») los bloques
      thinking llegan vacíos. No cambia lo que razona ni lo que se factura.
    - claude-sonnet-5-5: "disabled" es 400; el apagado es "between_tools", que
      no admite display (400).
    - el resto de sonnet/opus/haiku-5-5: "disabled".
    Con effort xhigh/max ningún modelo acepta el apagado: queda adaptativo.
    """
    extra: dict[str, Any] = {}
    if effort:
        extra["output_config"] = {"effort": effort}
    if modelo.startswith("claude-opus-5-5"):
        extra["thinking"] = {"type": "adaptive", "display": "summarized"}
        return extra
    if effort in _EFFORT_SIN_APAGADO:
        return extra
    if modelo.startswith("claude-sonnet-5-5"):
        extra["thinking"] = {"type": "between_tools"}
    elif "sonnet" in modelo or "opus" in modelo or modelo.startswith("claude-haiku-5-5"):
        extra["thinking"] = {"type": "disabled"}
    return extra


# Sobre este tamaño el PDF va por Files API: el request completo (base64
# infla ~33%) tiene tope de 32 MB y los informes DOCX convertidos llegan a 45.
_MAX_B64_INLINE = 24_000_000
_BETA_FILES = "files-api-2025-04-14"


@contextmanager
def _fuente_pdf(
    client: anthropic.Anthropic, pdf_base64: str, filename: str
) -> Iterator[tuple[dict[str, Any], str]]:
    """Bloque `document` del PDF: inline si cabe, si no subido a Files API.

    El archivo subido se borra al salir (no queda almacenado en la cuenta).
    Devuelve (source, vía) — la vía queda en la metadata del run.
    """
    if len(pdf_base64) <= _MAX_B64_INLINE:
        yield {"type": "base64", "media_type": "application/pdf", "data": pdf_base64}, "base64"
        return
    subido = client.beta.files.upload(
        file=(filename, base64.b64decode(pdf_base64), "application/pdf"),
    )
    try:
        yield {"type": "file", "file_id": subido.id}, "files_api"
    finally:
        try:
            client.beta.files.delete(subido.id)
        except anthropic.APIError as exc:
            # No botar una respuesta ya pagada (ni disparar el fallback de
            # modelo) porque falló la limpieza: el archivo queda en la cuenta.
            logger.warning("No se pudo borrar %s de Files API: %s", subido.id, exc)


def pdf_cabe_inline(pdf_base64: str) -> bool:
    """¿El PDF entra como base64 en el request (sin Files API)?"""
    return len(pdf_base64) <= _MAX_B64_INLINE


def contar_tokens_pdf(*, modelo: str, system_prompt: str, user_prompt: str, pdf_base64: str) -> int:
    """Tokens de input de la request (count_tokens: gratis, sin generar).

    Solo modelos Claude y solo PDFs inline: count_tokens rechaza los archivos
    de la Files API (400 "File sources are not supported"). Un PDF más grande
    se cuenta por partes (troceo._contar_rango).
    """
    if not modelo.startswith("claude"):
        raise ValueError(f"count_tokens es de Anthropic; '{modelo}' no es un modelo Claude")
    if not pdf_cabe_inline(pdf_base64):
        raise ValueError("PDF demasiado grande para count_tokens inline: contarlo por partes")
    conteo = get_client_anthropic().messages.count_tokens(
        model=modelo,
        system=system_prompt,
        messages=[{"role": "user", "content": cast(Any, [
            {"type": "document", "source": {
                "type": "base64", "media_type": "application/pdf", "data": pdf_base64,
            }},
            {"type": "text", "text": user_prompt},
        ])}],
    )
    return conteo.input_tokens


class LlamadaFallidaError(RuntimeError):
    """La llamada se hizo (y se pagó), pero su respuesta no sirve: JSON que no
    valida contra el schema, refusal o salida no parseable.

    Lleva la metadata parcial de esa llamada en ``llm_metadata`` (formato común
    de llamada fallida, ver ``_meta_fallida``) para que la etapa la persista
    antes de propagar (invariante 20). Sigue siendo RuntimeError y no entra en
    ERRORES_ACCESO_MODELO: no dispara el modelo de respaldo.
    """

    def __init__(self, mensaje: str, llm_metadata: dict[str, Any]) -> None:
        super().__init__(mensaje)
        self.llm_metadata = llm_metadata


def _meta_fallida(modelo: str, error: str, **campos: Any) -> dict[str, Any]:
    """Formato común de una llamada fallida: modelo y marca siempre; tokens,
    stop_reason y texto crudo cuando existen (metricas_lote cuenta los tokens
    que haya, como cota inferior del costo)."""
    return {"modelo": modelo, "llamada_fallida": True, "error": error,
            **{k: v for k, v in campos.items() if v is not None}}


def _adjuntar_meta_fallida(exc: Exception, modelo: str, t0: float, **campos: Any) -> None:
    """Deja en ``exc.llm_metadata`` la llamada fallida (formato común, con el
    tiempo desde ``t0`` y los reintentos) si el error del proveedor no la trae,
    sin cambiar su tipo ni su mensaje: las etapas persisten esa metadata como
    raw de la llamada (invariante 20) y metricas_lote cuenta sus reintentos."""
    if getattr(exc, "llm_metadata", None) is None:
        exc.llm_metadata = _meta_fallida(  # type: ignore[attr-defined]
            modelo, f"{type(exc).__name__}: {exc}",
            tiempo_segundos=round(time.monotonic() - t0, 2), **campos)


def _campos_snapshot(stream: Any) -> dict[str, Any]:
    """Lo que el stream ya acumuló cuando la respuesta no validó (best effort:
    sin snapshot, la llamada fallida queda con modelo y error solamente)."""
    try:
        snap = stream.current_message_snapshot
    except Exception:  # noqa: BLE001 — diagnóstico, nunca debe tapar el error real
        return {}
    uso = getattr(snap, "usage", None)
    entrada = getattr(uso, "input_tokens", None)
    salida = getattr(uso, "output_tokens", None)
    return {
        "modelo_servido": getattr(snap, "model", None),
        "stop_reason": getattr(snap, "stop_reason", None),
        "tokens_prompt": entrada,
        "tokens_completion": salida,
        "tokens_total": entrada + salida if entrada is not None and salida is not None else None,
        "tokens_cache_lectura": getattr(uso, "cache_read_input_tokens", None),
        "texto_crudo": next((b.text for b in getattr(snap, "content", []) or []
                             if getattr(b, "type", None) == "text"), None),
        "razonamiento_resumen": _resumen_razonamiento(getattr(snap, "content", []) or []),
    }


def _resumen_razonamiento(contenido: Iterable[Any]) -> list[str] | None:
    """Textos de los bloques thinking no vacíos (Opus 5.5 con display
    «summarized», M20), o None. Es un resumen, no el razonamiento: solo para
    diagnóstico, nunca evidencia para el equipo revisor."""
    textos = [b.thinking for b in contenido
              if getattr(b, "type", None) == "thinking" and getattr(b, "thinking", "")]
    return textos or None


def _reintentos_sdk(origen: object) -> int:
    """Reintentos que el SDK hizo antes del intento que produjo `origen`: el
    stream abierto o el error con que se rindió. El SDK numera cada intento en
    el header x-stainless-retry-count de su request. 0 si no hay request que
    leer (clientes falsos de los tests, error sin request)."""
    try:
        respuesta = getattr(origen, "response", None)
        request = (respuesta.request if respuesta is not None
                   else getattr(origen, "request", None))
        if request is None:
            return 0
        return int(request.headers.get("x-stainless-retry-count", 0))
    except Exception:  # noqa: BLE001 — diagnóstico, nunca debe tapar la respuesta ni el error
        return 0


def _es_transitorio_stream(exc: Exception) -> bool:
    """¿Error transitorio que el SDK no reintenta por llegar con el stream abierto?

    Solo errores de conexión/transporte o un `event: error` de sobrecarga o
    interno del servidor. Los errores de request (400, auth, etc.) se propagan.
    """
    if isinstance(exc, (anthropic.APIConnectionError, httpx.TransportError)):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        cuerpo = exc.body if isinstance(exc.body, dict) else {}
        error = cuerpo.get("error")
        tipo = error.get("type") if isinstance(error, dict) else None
        return tipo in ("overloaded_error", "api_error") or exc.status_code >= 500
    return False


def _esperar(segundos: float) -> None:
    time.sleep(segundos)


def _llamar_anthropic(
    *,
    modelo: str,
    system_prompt: str,
    user_prompt: str,
    response_model: type[T],
    pdf_base64: str | None,
    pdf_filename: str = "documento.pdf",
    batch: bool = False,
) -> tuple[T, dict[str, Any]]:
    client = get_client_anthropic()
    extra = parametros_thinking(modelo, settings.effort_llm)

    with ExitStack() as pila:
        user_content: list[dict[str, Any]] = []
        via_pdf = None
        if pdf_base64:
            source, via_pdf = pila.enter_context(_fuente_pdf(client, pdf_base64, pdf_filename))
            user_content.append({"type": "document", "source": source})
            if via_pdf == "files_api":
                extra["extra_headers"] = {"anthropic-beta": _BETA_FILES}
        user_content.append({"type": "text", "text": user_prompt})
        comunes: dict[str, Any] = {
            "modelo": modelo, "extra": extra, "response_model": response_model,
            "system_prompt": system_prompt, "user_prompt": user_prompt,
            "pdf_incluido": pdf_base64 is not None, "via_pdf": via_pdf}
        if batch:
            # Dentro del ExitStack: el PDF de Files API vive hasta que el lote termina.
            return _llamar_anthropic_batch(client, user_content=user_content, **comunes)

        # Streaming: con PDFs de cientos de páginas (y el thinking siempre
        # activo de Opus 5.5) una request no-streaming excede el timeout HTTP.
        # El PDF de Files API se sube una vez y se reusa en cada reintento.
        # Los reintentos del SDK (y sus códigos HTTP) se cuentan solo en el
        # request de generación, sumados sobre los intentos propios de stream:
        # la subida y el borrado de Files API quedan fuera del registro.
        codigos_http = pila.enter_context(codigos_http_reintentados())
        reintentos_sdk = 0

        def _reintentos() -> dict[str, Any]:
            return {"reintentos_sdk": reintentos_sdk,
                    "codigos_http_reintentados": list(codigos_http)}

        t0 = time.monotonic()
        for intento in range(_MAX_REINTENTOS + 1):
            stream_abierto = False
            try:
                with client.messages.stream(
                    model=modelo,
                    max_tokens=64000,
                    **extra,
                    system=system_prompt,
                    messages=[{"role": "user", "content": cast(Any, user_content)}],
                    output_format=response_model,
                ) as stream:
                    stream_abierto = True
                    reintentos_sdk += _reintentos_sdk(stream)
                    try:
                        response = stream.get_final_message()
                    except ValidationError as exc:
                        # El SDK valida al cerrar el bloque de texto, ANTES del
                        # message_delta: el snapshot no trae stop_reason ni los
                        # tokens de salida finales. Por eso no se afirma la causa
                        # (corte por max_tokens o rechazo en texto libre) y el
                        # usage queda marcado como parcial (cota inferior).
                        mensaje = (
                            f"El modelo devolvió una respuesta que no valida contra "
                            f"{response_model.__name__} (puede estar cortada por max_tokens "
                            f"o ser un rechazo; ver texto_crudo en el raw): {exc}"
                        )
                        raise LlamadaFallidaError(mensaje, _meta_fallida(
                            modelo, mensaje,
                            tiempo_segundos=round(time.monotonic() - t0, 2),
                            usage_parcial=True,
                            **_reintentos(),
                            **_campos_snapshot(stream),
                        )) from exc
                break
            except LlamadaFallidaError:
                raise
            except ValidationError as exc:
                # No validó antes de abrir el stream: sin snapshot del que leer.
                mensaje = (
                    f"El modelo devolvió una respuesta que no valida contra "
                    f"{response_model.__name__} (puede estar cortada por max_tokens o ser un "
                    f"rechazo): {exc}"
                )
                raise LlamadaFallidaError(mensaje, _meta_fallida(
                    modelo, mensaje, tiempo_segundos=round(time.monotonic() - t0, 2),
                    **_reintentos(),
                )) from exc
            except Exception as exc:
                if not stream_abierto:
                    # El SDK se rindió (o falló) antes de abrir el stream: sus
                    # reintentos se leen del request del error.
                    reintentos_sdk += _reintentos_sdk(exc)
                if intento == _MAX_REINTENTOS or not _es_transitorio_stream(exc):
                    # Sale tal cual (tipo y mensaje: el respaldo de modelo depende
                    # del tipo), con la metadata de la llamada fallida para que la
                    # etapa la persista: sin ella se pierde el registro del sobrecargo.
                    _adjuntar_meta_fallida(exc, modelo, t0, reintentos_stream=intento,
                                           **_reintentos())
                    raise
                espera = min(2**intento, 30) + random.uniform(0, 1)
                logger.warning("Error transitorio a mitad del stream (%s); reintento en %.1fs",
                               exc, espera)
                _esperar(espera)
        elapsed = time.monotonic() - t0

    return _cerrar_respuesta(
        response, response.parsed_output, elapsed=elapsed,
        campos_ok={"reintentos_stream": intento, **_reintentos()},
        campos_fallida=_reintentos(), **comunes,
    )


def _cerrar_respuesta(
    response: Any,
    parsed: T | None,
    *,
    modelo: str,
    extra: dict[str, Any],
    response_model: type[T],
    system_prompt: str,
    user_prompt: str,
    pdf_incluido: bool,
    via_pdf: str | None,
    elapsed: float,
    campos_ok: dict[str, Any],
    campos_fallida: dict[str, Any],
    error_parseo: str | None = None,
) -> tuple[T, dict[str, Any]]:
    """Metadata de una respuesta de Anthropic (stream o lote): la misma en los
    dos caminos, más lo propio de cada uno (`campos_ok` / `campos_fallida`).
    Un refusal o una respuesta sin parsear sale como LlamadaFallidaError."""
    texto_raw = next((b.text for b in response.content if b.type == "text"), None)
    resumen = _resumen_razonamiento(response.content)
    uso = response.usage
    tokens_prompt = uso.input_tokens
    tokens_completion = uso.output_tokens

    error = None
    if response.stop_reason == "refusal":
        detalle = getattr(response, "stop_details", None)
        categoria = getattr(detalle, "category", None) if detalle else None
        error = f"El modelo rechazó la solicitud (refusal, categoría={categoria})."
    elif parsed is None:
        error = error_parseo or (
            f"El modelo no devolvió respuesta parseable (stop_reason={response.stop_reason}).")
    if error is not None:
        raise LlamadaFallidaError(error, _meta_fallida(
            modelo, error,
            modelo_servido=response.model,
            stop_reason=response.stop_reason,
            tiempo_segundos=round(elapsed, 2),
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            tokens_total=tokens_prompt + tokens_completion,
            tokens_cache_lectura=getattr(uso, "cache_read_input_tokens", None),
            texto_crudo=texto_raw,
            razonamiento_resumen=resumen,
            **campos_fallida,
        ))

    metadata: dict[str, Any] = {
        "modelo": modelo,
        "modelo_servido": response.model,
        "stop_reason": response.stop_reason,
        **campos_ok,
        "tiempo_segundos": round(elapsed, 2),
        "tokens_prompt": tokens_prompt,
        "tokens_completion": tokens_completion,
        "tokens_total": tokens_prompt + tokens_completion,
        "tokens_cache_lectura": getattr(uso, "cache_read_input_tokens", None),
        "parametros_thinking": {k: v for k, v in extra.items() if k != "extra_headers"},
        "schema_sha256": schema_sha256(response_model),
        "system_prompt": system_prompt,
        "user_prompt_text": user_prompt,
        "pdf_incluido": pdf_incluido,
        "pdf_via": via_pdf,
        "response_raw": json.loads(texto_raw) if texto_raw else None,
        "razonamiento_resumen": resumen,
    }

    assert parsed is not None  # sin error, hay respuesta parseada
    return parsed, metadata


# Lote de un solo pedido por llamada (M61): la etapa no cambia y el resultado
# se procesa igual que el del stream. Batch cobra la mitad; la latencia va de
# minutos a horas y la API corta a las 24 h.
_CUSTOM_ID_LOTE = "llamada"
_CONSULTA_LOTE_SEGUNDOS = 30
_ESPERA_MAXIMA_LOTE_SEGUNDOS = 24 * 3600


def _formato_salida(response_model: type[BaseModel]) -> dict[str, Any]:
    """El `output_config.format` que arma `messages.stream(output_format=...)`
    del SDK, para mandarlo en un lote (que no acepta el modelo Pydantic). Un
    test lo compara con el request del stream."""
    esquema = TypeAdapter(response_model).json_schema()
    return {"type": "json_schema", "schema": transform_schema(esquema)}


def _llamar_anthropic_batch(
    client: anthropic.Anthropic,
    *,
    user_content: list[dict[str, Any]],
    **comunes: Any,
) -> tuple[Any, dict[str, Any]]:
    modelo: str = comunes["modelo"]
    response_model: type[BaseModel] = comunes["response_model"]
    extra = dict(comunes["extra"])
    headers = extra.pop("extra_headers", None)
    output_config = {**extra.pop("output_config", {}), "format": _formato_salida(response_model)}
    params = {"model": modelo, "max_tokens": 64000, **extra, "output_config": output_config,
              "system": comunes["system_prompt"],
              "messages": [{"role": "user", "content": user_content}]}

    t0 = time.monotonic()
    lote = client.messages.batches.create(
        requests=[{"custom_id": _CUSTOM_ID_LOTE, "params": cast(Any, params)}],
        extra_headers=headers)
    # El lote sigue (y se cobra) aunque este proceso se corte: el id queda en el log
    # para recuperar el resultado con batches.results.
    logger.warning("Lote %s creado (%s); se espera a que termine", lote.id, modelo)
    lote_de = {"via_llm": "batch", "batch_id": lote.id}

    def _falla(mensaje: str) -> LlamadaFallidaError:
        return LlamadaFallidaError(mensaje, _meta_fallida(
            modelo, mensaje, tiempo_segundos=round(time.monotonic() - t0, 2), **lote_de))

    while lote.processing_status != "ended":
        if time.monotonic() - t0 >= _ESPERA_MAXIMA_LOTE_SEGUNDOS:
            client.messages.batches.cancel(lote.id)
            raise _falla(f"El lote {lote.id} no terminó en {_ESPERA_MAXIMA_LOTE_SEGUNDOS} s: "
                         "se canceló.")
        _esperar(_CONSULTA_LOTE_SEGUNDOS)
        lote = client.messages.batches.retrieve(lote.id)
    en_cola = time.monotonic() - t0

    resultados = [r for r in client.messages.batches.results(lote.id)
                  if r.custom_id == _CUSTOM_ID_LOTE]
    if len(resultados) != 1:
        raise _falla(f"El lote {lote.id} devolvió {len(resultados)} resultados para "
                     f"«{_CUSTOM_ID_LOTE}» (se esperaba 1).")
    resultado = resultados[0].result
    if resultado.type != "succeeded":
        detalle = getattr(getattr(resultado, "error", None), "error", None)
        raise _falla(f"El lote {lote.id} terminó con «{resultado.type}»"
                     + (f": {detalle.type}: {detalle.message}" if detalle else "."))

    response = resultado.message
    texto = next((b.text for b in response.content if b.type == "text"), None)
    parsed, error_parseo = None, None
    if response.stop_reason != "refusal" and texto is not None:
        try:
            parsed = response_model.model_validate_json(texto)
        except ValidationError as exc:
            error_parseo = (f"El modelo devolvió una respuesta que no valida contra "
                            f"{response_model.__name__}: {exc}")
    campos = {**lote_de, "tiempo_en_cola_segundos": round(en_cola, 2)}
    return _cerrar_respuesta(response, parsed, elapsed=en_cola, campos_ok=campos,
                             campos_fallida=campos, error_parseo=error_parseo, **comunes)


def _llamar_openai(
    *,
    modelo: str,
    system_prompt: str,
    user_prompt: str,
    response_model: type[T],
    pdf_base64: str | None,
    pdf_filename: str,
) -> tuple[T, dict[str, Any]]:
    client = get_client()

    user_content: list[dict[str, Any]] = []

    if pdf_base64:
        user_content.append({
            "type": "file",
            "file": {
                "filename": pdf_filename,
                "file_data": f"data:application/pdf;base64,{pdf_base64}",
            },
        })

    user_content.append({"type": "text", "text": user_prompt})

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    # Sin header de reintentos: parse() no expone el request (haría falta
    # with_raw_response). Solo los códigos, por el hook del cliente.
    t0 = time.monotonic()
    with codigos_http_reintentados() as codigos_http:
        try:
            completion = client.beta.chat.completions.parse(
                model=modelo,
                messages=messages,  # type: ignore[arg-type]
                response_format=response_model,
            )
        except (openai.LengthFinishReasonError, openai.ContentFilterFinishReasonError) as exc:
            # Respuesta pagada cortada por largo o por el filtro de contenido: el
            # análogo del max_tokens de Anthropic. Viaja con su usage y su texto.
            error = f"{type(exc).__name__}: {exc}"
            cortada = getattr(exc, "completion", None)  # el error de filtro no la trae
            uso_corte = cortada.usage if cortada is not None else None
            texto = (cortada.choices[0].message.content
                     if cortada is not None and cortada.choices else None)
            raise LlamadaFallidaError(error, _meta_fallida(
                modelo, error,
                modelo_servido=cortada.model if cortada is not None else None,
                tiempo_segundos=round(time.monotonic() - t0, 2),
                tokens_prompt=uso_corte.prompt_tokens if uso_corte else None,
                tokens_completion=uso_corte.completion_tokens if uso_corte else None,
                tokens_total=uso_corte.total_tokens if uso_corte else None,
                texto_crudo=texto,
                codigos_http_reintentados=codigos_http,
            )) from exc
        except Exception as exc:
            # Como en Anthropic: el error del SDK (p. ej. 429 tras sus reintentos)
            # sale tal cual, con la metadata de la llamada fallida.
            _adjuntar_meta_fallida(exc, modelo, t0, codigos_http_reintentados=codigos_http)
            raise
    elapsed = time.monotonic() - t0
    message = completion.choices[0].message

    if message.parsed is None:
        error = f"El modelo rechazó la respuesta: {message.refusal}"
        uso_oa = completion.usage
        raise LlamadaFallidaError(error, _meta_fallida(
            modelo, error,
            modelo_servido=completion.model,
            tiempo_segundos=round(elapsed, 2),
            tokens_prompt=uso_oa.prompt_tokens if uso_oa else None,
            tokens_completion=uso_oa.completion_tokens if uso_oa else None,
            tokens_total=uso_oa.total_tokens if uso_oa else None,
            texto_crudo=message.content,
            codigos_http_reintentados=codigos_http,
        ))

    metadata: dict[str, Any] = {
        "modelo": modelo,
        "modelo_servido": completion.model,
        "codigos_http_reintentados": codigos_http,
        "tiempo_segundos": round(elapsed, 2),
        "tokens_prompt": completion.usage.prompt_tokens if completion.usage else None,
        "tokens_completion": completion.usage.completion_tokens if completion.usage else None,
        "tokens_total": completion.usage.total_tokens if completion.usage else None,
        "schema_sha256": schema_sha256(response_model),
        "system_prompt": system_prompt,
        "user_prompt_text": user_prompt,
        "pdf_incluido": pdf_base64 is not None,
        "response_raw": json.loads(message.content) if message.content else None,
    }

    return message.parsed, metadata
