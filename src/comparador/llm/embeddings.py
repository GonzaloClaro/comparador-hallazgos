"""Cálculo de embeddings, similitud coseno y la prueba de la clave de OpenAI."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import numpy as np
import openai
from numpy.typing import NDArray

from comparador.config import settings
from comparador.llm.client import codigos_http_reintentados, get_client

CalcularEmbeddings = Callable[[list[str]], tuple[NDArray[np.float64], dict[str, Any] | None]]


def calcular_embeddings(
    textos: list[str],
) -> tuple[NDArray[np.float64], dict[str, Any] | None]:
    """Calcula embeddings para una lista de textos en un solo batch.

    Returns:
        Tupla de (matriz de shape (len(textos), dim_embedding), usage de la
        llamada para el registro de tokens del run — None si no hubo llamada).
    """
    if not textos:
        return np.array([], dtype=np.float64).reshape(0, 0), None

    client = get_client()
    with codigos_http_reintentados() as codigos_http:
        response = client.embeddings.create(
            model=settings.modelo_embeddings,
            input=textos,
        )

    vecs = [item.embedding for item in response.data]
    usage = None
    if response.usage:
        usage = {
            "etapa": "embeddings",
            "modelo": settings.modelo_embeddings,
            "modelo_servido": response.model,
            "tokens_prompt": response.usage.prompt_tokens,
            "tokens_total": response.usage.total_tokens,
            "codigos_http_reintentados": codigos_http,
        }
    return np.array(vecs, dtype=np.float64), usage


# ------------------------------------------------------------ prueba de la clave (PD66)

# La palabra que se embebe para probar la clave (~1 token, ~US$0,000001).
PALABRA_PRUEBA = "prueba"


class ClaveOpenAIError(RuntimeError):
    """La clave de OpenAI no responde (sin fondos, revocada o inválida): se
    detecta antes de la primera llamada pagada a Claude."""


def _causa(exc: Exception) -> str:
    if isinstance(exc, openai.AuthenticationError):
        motivo = "autenticación rechazada (401): clave inválida o revocada"
    elif isinstance(exc, openai.PermissionDeniedError):
        motivo = "permiso denegado (403): la clave no tiene acceso al modelo de embeddings"
    elif isinstance(exc, openai.RateLimitError):
        motivo = ("sin fondos o cuota agotada (429 insufficient_quota)"
                  if getattr(exc, "code", None) == "insufficient_quota"
                  else "límite de solicitudes (429) que siguió tras los reintentos")
    elif isinstance(exc, openai.APIConnectionError):
        motivo = "sin conexión con OpenAI"
    elif isinstance(exc, openai.APIStatusError):
        motivo = f"error HTTP {exc.status_code} de OpenAI"
    elif isinstance(exc, openai.OpenAIError):
        motivo = "error del cliente de OpenAI (¿falta OPENAI_API_KEY?)"
    else:
        motivo = "error inesperado"
    return f"{motivo}. {type(exc).__name__}: {exc}"


def probar_clave_openai(calcular: CalcularEmbeddings | None = None) -> dict[str, Any]:
    """Embedding de una palabra para comprobar que la clave de OpenAI responde.

    Los embeddings de E4 son siempre de OpenAI: una clave sin fondos o revocada
    fallaría en E4 después de pagar el checklist, E1 y E3. Quien la llama
    (pipeline, evaluar_lote, reproducir_e4) lo hace antes de la primera llamada
    pagada a Claude y le pasa la función que usará E4
    (``etapa4_matching.calcular_embeddings``, la que reemplazan los tests); sin
    ella, ``calcular_embeddings`` de este módulo.

    Devuelve lo que se registra en metadata.json (no es una llamada de E4: no
    va a los raw ni a ``tokens_embeddings``): ok, modelo pedido, modelo servido,
    tokens y segundos. Si no responde, ``ClaveOpenAIError`` con la causa.
    """
    calcular = calcular or calcular_embeddings
    t0 = time.monotonic()
    try:
        matriz, uso = calcular([PALABRA_PRUEBA])
    except Exception as exc:
        raise ClaveOpenAIError(
            "La clave de OpenAI no responde: ¿sin fondos o revocada? No se llamó a Claude "
            f"(no se gastó nada en Claude). Causa: {_causa(exc)}") from exc
    if matriz.shape[0] != 1 or not matriz.size:
        raise ClaveOpenAIError(
            "La clave de OpenAI no responde: ¿sin fondos o revocada? No se llamó a Claude. "
            f"Causa: la respuesta llegó sin el vector (forma {matriz.shape}).")
    uso = uso or {}
    return {
        "ok": True,
        "modelo": settings.modelo_embeddings,
        "modelo_servido": uso.get("modelo_servido"),
        "tokens": uso.get("tokens_total"),
        "segundos": round(time.monotonic() - t0, 2),
    }


# ------------------------------------------------------------ similitud


def similitud_coseno(a: NDArray[np.float64], b: NDArray[np.float64]) -> float:
    """Similitud coseno entre dos vectores."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def top_k_similares(
    query: NDArray[np.float64],
    candidatos: NDArray[np.float64],
    k: int = 5,
) -> list[tuple[int, float]]:
    """Retorna los top-k candidatos más similares al query.

    Returns:
        Lista de (índice, similitud) ordenada de mayor a menor.
    """
    if candidatos.size == 0:
        return []

    normas_c = np.linalg.norm(candidatos, axis=1)
    norma_q = np.linalg.norm(query)

    mascara_valida = (normas_c > 0) & (norma_q > 0)
    similitudes = np.zeros(len(candidatos))
    if norma_q > 0:
        similitudes[mascara_valida] = (
            candidatos[mascara_valida] @ query / (normas_c[mascara_valida] * norma_q)
        )

    # Orden estable: ante empates (textos idénticos) se respeta el orden del
    # Excel. argsort()[::-1] invertía los empatados y cruzaba pares (Beta E1-E9).
    indices = np.argsort(-similitudes, kind="stable")[:k]
    return [(int(i), float(similitudes[i])) for i in indices]
