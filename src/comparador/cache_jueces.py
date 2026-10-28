"""Caché de los jueces de E4 leída de los raw de un run (M70).

Para repetir E4 sobre los hallazgos de una corrida guardada sin volver a pagar
los jueces (o pagando solo lo nuevo): cada llamada al juez de matching o al de
redacción se busca por su clave y, si la corrida la hizo, se responde con lo
que el modelo respondió entonces.

- Clave: modelo pedido, system prompt, user prompt, response_model (nombre y
  sha256 de su JSON schema, que va en la request) y los parámetros de
  thinking/effort normalizados. Cualquier cambio de modelo, prompt, schema o
  parámetros la invalida (la caché nunca reutiliza en silencio una respuesta a
  otra request). Los raw anteriores al registro del schema (B0-B2 y la base de
  D1) valen con el schema de los jueces de entonces (`SCHEMA_SIN_REGISTRO`,
  el de las copias de src/ de B0-B2). La normalización de los parámetros solo
  iguala lo que no cambia la respuesta: `display` (si el resumen del
  razonamiento vuelve o no, M20) y, en
  Opus 5.5, `{"type": "adaptive"}` frente a no mandar thinking (siempre razona
  adaptativo; B2 no lo mandaba). Sonnet sin parámetro (razona) no es
  `between_tools` (no razona).
- Cola por clave: B2 repitió 104 prompts idénticos dentro de un mismo run y en
  23 la confianza cambió de una vez a otra. Cada aparición consume la
  siguiente respuesta guardada, en el orden numérico de los raw (judge_N,
  redaccion_N), que es el orden en que se llamó.
- Modos: «estricto» falla ante cualquier llamada que no esté (o cuya cola ya
  se consumió) sin llamar a nadie; «mixto» paga esas con el llamador real.
- Lo servido desde la caché lleva `desde_cache`, `raw_origen` (la ruta
  absoluta del raw: la base de regresión y su run tienen el mismo nombre de
  carpeta) y tokens en 0 (los originales en `tokens_origen`): metricas_lote no
  lo cuenta como gasto.

Las llamadas fallidas y las respuestas del modelo de respaldo
(`fallback_por_error`: respondió otro modelo) no entran a la caché.
"""

from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from comparador.config import settings
from comparador.etapa4_matching import JuezNoLlamadoError, _JuezRedaccionResponse, _JuezResponse
from comparador.llm.client import parametros_thinking, schema_sha256

Modo = Literal["estricto", "mixto"]
MODOS: tuple[Modo, ...] = ("estricto", "mixto")
Llamador = Callable[..., tuple[Any, dict[str, Any]]]

# Carpeta de raw → (prefijo de los archivos, response_model del juez).
_CARPETAS: dict[str, tuple[str, type[Any]]] = {
    "etapa4_llm_judge_raw": ("judge", _JuezResponse),
    "etapa4_redaccion_raw": ("redaccion", _JuezRedaccionResponse),
}
# Schema de los raw que no traen `schema_sha256` (anteriores a su registro en
# llm.client: B0-B2 y la base de D1): el de los jueces de mediciones/b{0,1,2}/src,
# idéntico en las tres rondas y al del 2026-10-24 (lo fija el golden
# test_golden_replay_e4). Nunca se actualiza al schema de hoy: si este cambia,
# esos raw dejan de coincidir.
SCHEMA_SIN_REGISTRO: dict[str, str] = {
    "etapa4_llm_judge_raw": "32186e1d3efb8a180d84de7165d20bf6bb87fe8c8cf80a44db328e2b64ebbcd3",
    "etapa4_redaccion_raw": "9c24d9484895eccff4eb91dcb05ab2fb3b1ec1ada5665e91badfa6d16225eb02",
}
_IGNORADOS = frozenset({"embeddings.json"})
# Lo que E4 agrega a la metadata del cliente: describe la corrida de origen
# (traza de la asignación global, lote del juez de redacción), no la respuesta.
_CONTEXTO_E4 = frozenset({"tipo", "lote", "asignacion_global", "pano", "rele"})
_TOKENS = ("tokens_prompt", "tokens_completion", "tokens_total", "tokens_cache_lectura")
# Lo que no ocurrió al servir desde la caché (solo si el raw lo trae).
_EN_CERO: dict[str, Any] = {
    "tiempo_segundos": 0.0, "reintentos_stream": 0, "reintentos_sdk": 0,
    "codigos_http_reintentados": [],
}
_SIN_PARAMETROS = "<parámetros no registrados>"


class CacheJuecesFaltanteError(JuezNoLlamadoError):
    """Modo estricto: una llamada que la caché no tiene, o cuyas respuestas
    guardadas ya se usaron todas. No se llamó a nadie: E4 no la registra como
    llamada fallida."""


@dataclass(frozen=True)
class ClaveLlamada:
    modelo: str
    system_prompt: str
    user_prompt: str
    response_model: str
    schema: str       # sha256 del JSON schema del response_model (llm.client.schema_sha256)
    parametros: str   # JSON canónico de normalizar_parametros


@dataclass(frozen=True)
class RespuestaGuardada:
    clave: ClaveLlamada
    raw: dict[str, Any]
    origen: str   # ruta absoluta del raw: "<carpeta fuente>/<carpeta de raw>/<archivo>.json"


@dataclass(frozen=True)
class RawsDelRun:
    respuestas: list[RespuestaGuardada]   # en orden de llamada dentro de cada carpeta
    fallidas: list[str] = field(default_factory=list)
    de_respaldo: list[str] = field(default_factory=list)


def normalizar_parametros(modelo: str, parametros: dict[str, Any]) -> str:
    """Parámetros de thinking/effort de una request, como JSON canónico, sin lo
    que no cambia la respuesta (ver el docstring del módulo)."""
    normalizados = dict(parametros)
    thinking = normalizados.pop("thinking", None)
    if isinstance(thinking, dict):
        thinking = {k: v for k, v in thinking.items() if k != "display"}
    if thinking is not None and not (
        modelo.startswith("claude-opus-5-5") and thinking == {"type": "adaptive"}
    ):
        normalizados["thinking"] = thinking
    return json.dumps(normalizados, sort_keys=True, ensure_ascii=False)


def parametros_de_llamada(modelo: str) -> dict[str, Any]:
    """Los parámetros que mandaría hoy llm.client para este modelo (solo Claude
    los usa; OpenAI no registra ninguno)."""
    if not modelo.startswith("claude"):
        return {}
    return parametros_thinking(modelo, settings.effort_llm)


def clave_de_llamada(*, modelo: str, system_prompt: str, user_prompt: str,
                     response_model: type[Any]) -> ClaveLlamada:
    return ClaveLlamada(modelo, system_prompt, user_prompt, response_model.__name__,
                        schema_sha256(response_model),
                        normalizar_parametros(modelo, parametros_de_llamada(modelo)))


def _clave_del_raw(raw: dict[str, Any], carpeta: str, archivo: Path) -> ClaveLlamada:
    response_model = _CARPETAS[carpeta][1]
    try:
        modelo, system, user = raw["modelo"], raw["system_prompt"], raw["user_prompt_text"]
    except KeyError as exc:
        raise ValueError(f"{archivo}: raw de juez sin {exc}") from exc
    if raw.get("response_raw") is None:
        raise ValueError(f"{archivo}: raw de juez sin response_raw")
    if "parametros_thinking" in raw:
        parametros = normalizar_parametros(modelo, raw["parametros_thinking"])
    elif not str(modelo).startswith("claude"):
        parametros = normalizar_parametros(modelo, {})
    else:
        # Sin registro no se sabe qué se pidió: nunca coincide con una llamada.
        parametros = _SIN_PARAMETROS
    schema = raw.get("schema_sha256") or SCHEMA_SIN_REGISTRO[carpeta]
    return ClaveLlamada(modelo, system, user, response_model.__name__, schema, parametros)


def leer_raws(run_dir: Path) -> RawsDelRun:
    """Las respuestas de los dos jueces de un run (o de una repetición), en el
    orden numérico de sus raw. Un nombre que no es judge_N / redaccion_N (salvo
    embeddings.json) falla: no se adivina qué llamada es."""
    run_dir = run_dir.resolve()   # el origen de cada respuesta es su ruta, no su nombre
    respuestas: list[RespuestaGuardada] = []
    fallidas: list[str] = []
    de_respaldo: list[str] = []
    for carpeta, (prefijo, _) in _CARPETAS.items():
        numerados: list[tuple[int, Path]] = []
        for archivo in sorted((run_dir / carpeta).glob("*.json")):
            if archivo.name in _IGNORADOS:
                continue
            m = re.fullmatch(rf"{prefijo}_(\d+)\.json", archivo.name)
            if m is None:
                raise ValueError(f"{archivo}: no es un raw de juez ({prefijo}_N.json)")
            numerados.append((int(m[1]), archivo))
        for _, archivo in sorted(numerados):
            origen = str(archivo)
            raw = json.loads(archivo.read_text(encoding="utf-8"))
            if raw.get("llamada_fallida"):
                fallidas.append(origen)
            elif "fallback_por_error" in raw:
                de_respaldo.append(origen)
            else:
                clave = _clave_del_raw(raw, carpeta, archivo)
                respuestas.append(RespuestaGuardada(clave, raw, origen))
    return RawsDelRun(respuestas, fallidas, de_respaldo)


def _meta_desde_cache(guardada: RespuestaGuardada) -> dict[str, Any]:
    """La metadata del cliente de la llamada original, marcada como servida
    desde la caché y sin gasto. Una respuesta que ya venía de una caché
    conserva su primer origen."""
    raw = guardada.raw
    meta = {k: v for k, v in raw.items() if k not in _CONTEXTO_E4}
    if raw.get("desde_cache"):
        origen, tokens_origen = raw["raw_origen"], raw["tokens_origen"]
        tiempo_origen = raw.get("tiempo_origen")
    else:
        origen = guardada.origen
        tokens_origen = {k: raw.get(k) for k in _TOKENS}
        tiempo_origen = raw.get("tiempo_segundos")
    meta.update({k: v.copy() if isinstance(v, list) else v
                 for k, v in _EN_CERO.items() if k in raw})
    meta.update({k: 0 for k in _TOKENS})
    meta.update(desde_cache=True, raw_origen=origen, tokens_origen=tokens_origen,
                tiempo_origen=tiempo_origen)
    return meta


class CacheJueces:
    """Llamador compatible con `llamar_llm_estructurado` para los jueces de E4
    (`etapa4_matching.ejecutar_matching(llamar=...)`)."""

    def __init__(self, respuestas: Iterable[RespuestaGuardada], *, modo: Modo,
                 llamar_real: Llamador | None = None, fallidas: int = 0,
                 de_respaldo: int = 0) -> None:
        if modo not in MODOS:
            raise ValueError(f"modo de caché desconocido: {modo!r} (opciones: {MODOS})")
        if modo == "mixto" and llamar_real is None:
            raise ValueError("el modo mixto necesita el llamador real que paga lo que falta")
        self.modo = modo
        self._llamar_real = llamar_real
        self._colas: dict[ClaveLlamada, deque[RespuestaGuardada]] = {}
        self._cargadas = 0
        for r in respuestas:
            self._colas.setdefault(r.clave, deque()).append(r)
            self._cargadas += 1
        self._por_clave = {clave: len(cola) for clave, cola in self._colas.items()}
        self._fallidas, self._de_respaldo = fallidas, de_respaldo
        self.desde_cache = 0
        self.pagadas = 0
        self.desde: str | None = None   # ruta absoluta de la carpeta de la que salió (desde_run)

    @classmethod
    def desde_run(cls, run_dir: Path, *, modo: Modo,
                  llamar_real: Llamador | None = None) -> CacheJueces:
        raws = leer_raws(run_dir)
        cache = cls(raws.respuestas, modo=modo, llamar_real=llamar_real,
                    fallidas=len(raws.fallidas), de_respaldo=len(raws.de_respaldo))
        cache.desde = str(run_dir.resolve())
        return cache

    def __call__(self, *, modelo: str, system_prompt: str, user_prompt: str,
                 response_model: type[Any], pdf_base64: str | None = None,
                 pdf_filename: str = "documento.pdf") -> tuple[Any, dict[str, Any]]:
        if pdf_base64 is not None:
            raise ValueError(
                "La caché de jueces no cubre llamadas con PDF (la clave no lo incluye).")
        clave = clave_de_llamada(modelo=modelo, system_prompt=system_prompt,
                                 user_prompt=user_prompt, response_model=response_model)
        cola = self._colas.get(clave)
        if cola:
            guardada = cola.popleft()
            self.desde_cache += 1
            return (response_model.model_validate(guardada.raw["response_raw"]),
                    _meta_desde_cache(guardada))
        if self.modo == "estricto" or self._llamar_real is None:
            usadas = self._por_clave.get(clave, 0)
            motivo = (f"ya se usaron las {usadas} respuestas guardadas para esa clave"
                      if usadas else "el run de origen no hizo esa llamada")
            raise CacheJuecesFaltanteError(
                f"Caché de jueces en modo estricto: {response_model.__name__} con {modelo}, "
                f"{motivo} (vectores, prompt, modelo, schema o parámetros distintos, o más "
                f"llamadas que en el run de origen). Prompt: {user_prompt[:120]!r}"
            )
        self.pagadas += 1
        return self._llamar_real(modelo=modelo, system_prompt=system_prompt,
                                 user_prompt=user_prompt, response_model=response_model)

    def resumen(self) -> dict[str, Any]:
        """Para la metadata de la repetición: qué se cargó y qué se usó."""
        return {
            "modo": self.modo,
            "cargadas": self._cargadas,
            "excluidas_fallidas": self._fallidas,
            "excluidas_respaldo": self._de_respaldo,
            "claves": len(self._por_clave),
            "claves_repetidas": sum(1 for n in self._por_clave.values() if n > 1),
            "desde_cache": self.desde_cache,
            "pagadas": self.pagadas,
            "sin_usar": sum(len(cola) for cola in self._colas.values()),
        }
