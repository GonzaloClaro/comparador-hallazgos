"""Métricas de las rondas de medición, sin llamar a ninguna API.

Lee lo que dejaron las rondas de ``evaluar_lote`` en ``mediciones/`` y escribe
CSV agregados (sin texto de los informes) para respaldar cada cifra de
``docs/04_metricas.md``:

- ``checklist_por_informe.csv`` y ``checklist_por_punto.csv``: desde los ítems
  de ``evaluacion_B*.json`` (veredicto humano y clasificación de cada punto).
  Es el único registro congelado de cada ronda: re-evaluar con el código actual
  cambiaría el mapeo de algunos puntos.
- ``comparador_por_informe.csv``: recuento de estados de ``reporte_final.json``.
- ``citas_por_informe.csv`` (largo: estado de la verificación de las citas de la
  descripción, la acción y el checklist) y ``citas_checklist.csv`` (por escenario
  de la planilla: «cumple» bajados sin cita y si eran falsos cumple o aciertos),
  desde ``citas`` de la evaluación (PD52). B0-B2 no tienen citas: solo cabecera.
- ``checklist_un_tramo.csv``: informes leídos por partes (M08), por run y
  escenario de la planilla: los «cumple» vistos en una sola parte, los que
  bajarían con ``CHECKLIST_UN_TRAMO=bajar`` (en la lista de PD44) y, contra la
  planilla, cuántos eran falsos cumple o aciertos (o puntos sin planilla), con
  los aciertos del run marcando y bajando. Los runs anteriores a M08 (B0-B2) se
  simulan desde las respuestas de cada parte (``fuente`` simulado, la fusión
  debe dar su checklist.json); los 0.8.0 salen de su checklist.json
  (``guardado``, sus contadores deben cuadrar). Un run leído entero no tiene filas.
- ``costo_por_informe_etapa.csv``, ``costo_por_informe.csv`` y
  ``costo_campana.csv``: costo por llamada desde los ``*_raw/*.json`` de TODOS
  los runs de cada ronda (también los fallidos y los que no entraron a la
  evaluación). Un run fallido solo cuenta las llamadas cuyo raw alcanzó a
  guardarse: su costo es una cota inferior.
  ``costo_por_informe.csv`` suma además los reintentos del SDK y del stream y los
  códigos HTTP reintentados de cada run (vacío en los raw anteriores a M58).
- ``tiempo_por_informe.csv``: duración real y camino crítico. Con
  ``relojes_etapas`` en metadata.json, los tiempos medidos por etapa y el camino
  crítico de los relojes (``fuente_tiempo`` relojes); sin ellos (B0-B2), la
  estimación desde las llamadas. El estimado se conserva siempre para comparar,
  y los tiempos desde las llamadas también (``t_*_llamadas``, al final): el reloj
  de una etapa suma la subida del PDF y count_tokens, que compiten con la etapa
  en paralelo (el checklist de B3 con E1, el de B3s solo).
  Los runs solo checklist con relojes (B3s) entran con ``modo`` solo_checklist.
- ``tamano_informes.csv``: desde ``inventario_informes.json``.
- ``control_tokens.csv``: suma de los raw contra ``tokens_*`` de metadata.json.
- ``control_modelo_servido.csv``: por ronda × modelo × etapa, el modelo pedido
  contra el configurado y los modelos que sirvió la API (avisos impresos, sin
  cortar la generación). El precio va por el modelo PEDIDO.
- ``comparador_gt_por_run.csv``: cada run de las evaluaciones y cada repetición
  de E4 (``replay_e4/<etiqueta>/<run_id>/``) cuyo informe y Excel tienen GT en
  ``gt/comparador`` (sha256), evaluado de nuevo contra él (lo sin adjudicar,
  por motivo y por estado: una fila «extra» sin adjudicar puede ser una
  omisión de E3 que el GT no conoce). Lo que guardaron
  ``evaluar_lote`` (``comparador_gt``) o ``reproducir_e4`` con el MISMO GT
  (sha256 del archivo) debe reproducirse: si no, es una discrepancia.
- ``replay_e4.csv``: una fila por repetición de E4 (modelos, interruptores,
  llamadas pagadas y desde caché, costo, conteos y GT antes y después).
- ``ficha_version.csv``: hash del código medido, desde la copia ``src/`` de la
  carpeta de cada ronda (sin copia, «falta»), contrastado con el que registraron
  sus runs (``version.json``) y la copia congelada de su evaluación
  (``version_runs``: distinta = discrepancia; sin_registro en B0-B2, a la vista).
- ``checklist_errores_clasificados.csv`` (M09): cada falso no cumple o no
  verificable fuera de los anexos, por escenario de la planilla, con su clase de
  ``adjudicacion_checklist/m09.json`` (privado) y la página, tercio y parte de la
  evidencia; sin texto. Un error sin clasificar es una discrepancia.
- ``comparador_confianza_juez.csv`` (M54): por run de cada ronda y repetición de
  E4, los resultados por banda de confianza con los cortes de E4 (las
  transversales, aparte), cruzados con el GT de su informe y Excel por clave
  estable (como ``comparador_gt_por_run.csv``), y los rechazos del juez (desde su
  raw) aparte.
- ``extraccion_por_campo.csv`` y ``extraccion_por_tupla.csv``: la extracción
  (Etapa 3) campo por campo, contra la adjudicación de los runs fuente del GT,
  contra el Excel donde copia el PDF (Beta y Eta) y, en las rondas
  posteriores al GT (B3), contra el GT de su informe y Excel (lo que no calza,
  o lo que E3 extrajo distinto que en la fuente, queda sin referencia; las
  filas «extra» sin adjudicar, aparte), con los errores que explica la Etapa 1 aparte
  (``comparador.metricas_extraccion``, M15).

Dos carpetas con la misma etiqueta (p. ej. B3 y B3s mal rotuladas) fallan: se
mezclarían en todas las tablas. También una evaluación sin sus runs en runs/
junto a ella (corrida con otro RUNS_DIR): saldría de las tablas sin aviso.

Costo de una llamada, con los precios por millón de ``docs/metricas/precios.yaml``::

    tokens_input × input + tokens_cache × cache_lectura + tokens_output × output

``tokens_input`` es ``tokens_prompt`` del raw, que el cliente toma de
``usage.input_tokens`` de Anthropic: ese campo ya EXCLUYE las lecturas de caché,
así que no se les resta. El tramo de precio (Haiku 5.5 sobre 100K tokens) se
decide por el prompt de ESA llamada: input + lecturas de caché. El thinking ya
viene en los tokens de salida.

Uso:
    python -m comparador.metricas_lote --mediciones mediciones \\
        --precios docs/metricas/precios.yaml --salida docs/metricas/datos/
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import unicodedata
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from comparador import (
    adjudicacion,
    fichas,
    metricas_extraccion,
    sensibilidad,
    sensibilidad_checklist,
)
from comparador import metricas_confianza as conf
from comparador.adjudicacion import nombre_corto
from comparador.etapa0_checklist import (
    PUNTOS_EXIGEN_TODO_EL_INFORME,
    cargar_puntos,
    checklist_desde_raw,
    visto_en_parte,
)
from comparador.etapa4_matching import MARCA_COPIA
from comparador.evaluar_checklist import clasificar
from comparador.evaluar_comparador import (
    EvaluacionComparador,
    GtAplicable,
    Veredicto,
    evaluar,
    gt_aplicable,
    gts_de,
    resumen,
)
from comparador.gt_comparador import hashes_del_run
from comparador.persistence import (
    MODO_COMPLETO,
    MODO_REPLAY_E4,
    MODO_SOLO_CHECKLIST,
    nombre_modelo_en_run,
)
from comparador.schemas import CausaAjuste, ChecklistInforme, ReporteInforme, ResultadoChecklist

RAIZ = Path(__file__).resolve().parent.parent.parent

# Etapas que llaman a un modelo, en el orden del pipeline.
ETAPAS = ("checklist", "e1", "e3", "e4_juez", "e4_redaccion", "embeddings")

# Campo de metadata.json con los tokens (prompt + completion) de cada etapa.
CAMPO_METADATA = {
    "checklist": "tokens_checklist",
    "e1": "tokens_e1",
    "e3": "tokens_e3",
    "e4_juez": "tokens_e4",
    "e4_redaccion": "tokens_e4_redaccion",
    "embeddings": "tokens_embeddings",
}

# Paños que la Etapa 3 extrae a la vez: asyncio.Semaphore(3) en el código de
# las tres rondas (mediciones/b*/src/comparador/etapa3_extraer_hallazgos.py).
PARALELISMO_E3 = 3

CLASIFICACIONES = ("acierto", "no_verificable", "falso_no_cumple", "falso_cumple")
ESTADOS_COMPARADOR = ("coincide", "difiere", "falta_en_excel", "extra_en_excel", "transversal")
TIPOS_REQUIEREN_REVISION = ("semantico_bajo", "sin_match")
# Cifras de evaluar_comparador.resumen que van tal cual a comparador_gt_por_run.csv.
COLUMNAS_GT_CIFRAS = (
    "resultados", "transversales", "adjudicados", *adjudicacion.CLASES, "ok_texto_identico",
    "sin_adjudicar", "fuera_de_universo", "alertas", "alertas_sin_adjudicar",
    "precision_alertas", "precision_min", "precision_max", "A_sin_duplicados",
    "D_sin_duplicados",
)


# ---------------------------------------------------------------- precios


@dataclass(frozen=True)
class Tramo:
    """Precios (USD por millón) para prompts de hasta ``hasta_tokens_prompt``."""

    hasta_tokens_prompt: int | None  # inclusivo; None = sin tope
    input: float
    output: float | None
    cache_lectura: float | None
    # API de Batch (M61): solo para las llamadas que la usaron (via_llm "batch").
    batch_input: float | None = None
    batch_output: float | None = None


@dataclass(frozen=True)
class PrecioModelo:
    modelo: str
    tramos: tuple[Tramo, ...]

    def tramo(self, tokens_prompt: int) -> tuple[int, Tramo]:
        """(índice, tramo) que corresponde a un prompt de ``tokens_prompt``."""
        for i, t in enumerate(self.tramos):
            if t.hasta_tokens_prompt is None or tokens_prompt <= t.hasta_tokens_prompt:
                return i, t
        raise AssertionError("cargar_precios garantiza un último tramo sin tope")


def _precio(valor: Any, donde: str, opcional: bool) -> float | None:
    if valor is None and opcional:
        return None
    if isinstance(valor, bool) or not isinstance(valor, int | float) or valor < 0:
        raise ValueError(f"Precio inválido en {donde}: {valor!r}")
    return float(valor)


def _precio_batch(valor: Any, donde: str) -> float | None:
    """Precio de Batch: un número, o {valor, no_verificado, fuente}. Uno no
    verificado no se usa (cobrar una llamada por Batch con él falla)."""
    if isinstance(valor, dict):
        if valor.get("no_verificado"):
            return None
        valor = valor.get("valor")
    return _precio(valor, donde, opcional=True)


def cargar_precios(ruta: Path) -> dict[str, PrecioModelo]:
    """Lee precios.yaml y valida los campos que usa el cálculo de costo."""
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    modelos = (datos or {}).get("modelos")
    if not isinstance(modelos, dict) or not modelos:
        raise ValueError(f"{ruta} no tiene la sección 'modelos'")
    precios: dict[str, PrecioModelo] = {}
    for modelo, cfg in modelos.items():
        crudos = (cfg or {}).get("tramos") or []
        if not crudos:
            raise ValueError(f"El modelo '{modelo}' no tiene tramos de precio")
        tramos: list[Tramo] = []
        for i, t in enumerate(crudos):
            donde = f"{modelo}.tramos[{i}]"
            hasta = t.get("hasta_tokens_prompt")
            if hasta is not None and (not isinstance(hasta, int) or hasta <= 0):
                raise ValueError(f"hasta_tokens_prompt inválido en {donde}: {hasta!r}")
            entrada = _precio(t.get("input"), f"{donde}.input", opcional=False)
            assert entrada is not None
            tramos.append(Tramo(
                hasta_tokens_prompt=hasta,
                input=entrada,
                output=_precio(t.get("output"), f"{donde}.output", opcional=True),
                cache_lectura=_precio(
                    t.get("cache_lectura"), f"{donde}.cache_lectura", opcional=True
                ),
                batch_input=_precio_batch(t.get("batch_input"), f"{donde}.batch_input"),
                batch_output=_precio_batch(t.get("batch_output"), f"{donde}.batch_output"),
            ))
        topes = [t.hasta_tokens_prompt for t in tramos]
        if topes[-1] is not None or None in topes[:-1]:
            raise ValueError(f"'{modelo}': solo el último tramo puede (y debe) no tener tope")
        if topes[:-1] != sorted(set(topes[:-1]), key=lambda x: x or 0):
            raise ValueError(f"'{modelo}': los tramos deben ir de menor a mayor")
        precios[modelo] = PrecioModelo(modelo, tuple(tramos))
    return precios


# --------------------------------------------------------------- llamadas


@dataclass(frozen=True)
class Llamada:
    """Una llamada a un modelo, tal como quedó en su raw."""

    etapa: str
    # El modelo de la request ("modelo" del raw; con respaldo, el de respaldo): decide
    # el precio. El servido ("modelo_servido") solo se controla (control_modelo_servido):
    # en OpenAI trae la fecha (completion.model) y no está en precios.yaml.
    modelo_pedido: str
    tokens_input: int    # usage.input_tokens: sin las lecturas de caché
    tokens_cache: int    # usage.cache_read_input_tokens
    tokens_output: int   # usage.output_tokens (incluye thinking)
    tiempo_segundos: float | None
    pano: str | None = None
    fallida: bool = False  # respuesta pagada que no sirvió: sus tokens son cota inferior
    desde_cache: bool = False  # respuesta reutilizada de otra corrida: no se pagó de nuevo
    modelo_servido: str | None = None
    # Reintentos del SDK y de la validación del stream, y códigos HTTP que el SDK
    # reintentó (llm.client, M58). None: el raw es anterior a ese registro (B0-B2).
    reintentos_sdk: int | None = None
    reintentos_stream: int | None = None
    codigos_http: tuple[int, ...] | None = None
    via_batch: bool = False  # por la API de Batch (M61): se cobra a su precio

    @property
    def tokens_prompt(self) -> int:
        """Largo del prompt que decide el tramo de precio."""
        return self.tokens_input + self.tokens_cache


def etapa_de(raw: Path) -> str:
    """Etapa a la que pertenece un raw, según su carpeta (y nombre en E4)."""
    carpeta = raw.parent.name
    if carpeta == "etapa4_llm_judge_raw":
        return "embeddings" if raw.stem == "embeddings" else "e4_juez"
    por_carpeta = {
        "checklist_raw": "checklist",
        "etapa1_raw": "e1",
        "etapa3_raw": "e3",
        "etapa4_redaccion_raw": "e4_redaccion",
    }
    if carpeta not in por_carpeta:
        raise ValueError(f"Carpeta de respuestas crudas desconocida: {raw}")
    return por_carpeta[carpeta]


def _leer_json(ruta: Path) -> Any:
    return json.loads(ruta.read_text(encoding="utf-8"))


def _aplanar(meta: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Con troceo, el raw del checklist envuelve una llamada por tramo."""
    if "llamadas" in meta:
        for sub in meta["llamadas"]:
            yield from _aplanar(sub)
    else:
        yield meta


def _entero(meta: dict[str, Any], campo: str, raw: Path, requerido: bool) -> int:
    valor = meta.get(campo)
    if valor is None and not requerido:
        return 0
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ValueError(f"{raw}: '{campo}' debería ser entero y es {valor!r}")
    return valor


def _entero_opcional(meta: dict[str, Any], campo: str, raw: Path) -> int | None:
    return None if meta.get(campo) is None else _entero(meta, campo, raw, requerido=True)


def _codigos_http(meta: dict[str, Any], raw: Path) -> tuple[int, ...] | None:
    codigos = meta.get("codigos_http_reintentados")
    if codigos is None:
        return None
    if not isinstance(codigos, list) or not all(
            isinstance(c, int) and not isinstance(c, bool) for c in codigos):
        raise ValueError(f"{raw}: 'codigos_http_reintentados' debería ser una lista de "
                         f"enteros y es {codigos!r}")
    return tuple(codigos)


def llamadas_del_run(run_dir: Path) -> list[Llamada]:
    """Todas las llamadas de un run: anidadas del checklist e intentos de E3 incluidos."""
    llamadas: list[Llamada] = []
    for raw in sorted(run_dir.glob("*_raw/*.json")):
        etapa = etapa_de(raw)
        for m in _aplanar(_leer_json(raw)):
            if not m.get("modelo"):
                raise ValueError(f"{raw}: llamada sin modelo")
            # Una llamada fallida (formato común de llm.client._meta_fallida) puede
            # no traer usage: se cuenta con los tokens que tenga.
            fallida = bool(m.get("llamada_fallida"))
            tiempo = m.get("tiempo_segundos")
            llamadas.append(Llamada(
                etapa=etapa,
                modelo_pedido=str(m["modelo"]),
                tokens_input=_entero(m, "tokens_prompt", raw, requerido=not fallida),
                tokens_cache=_entero(m, "tokens_cache_lectura", raw, requerido=False),
                tokens_output=_entero(m, "tokens_completion", raw, requerido=False),
                tiempo_segundos=float(tiempo) if tiempo is not None else None,
                pano=m.get("pano"),
                fallida=fallida,
                desde_cache=bool(m.get("desde_cache")),
                modelo_servido=str(m["modelo_servido"]) if m.get("modelo_servido") else None,
                reintentos_sdk=_entero_opcional(m, "reintentos_sdk", raw),
                reintentos_stream=_entero_opcional(m, "reintentos_stream", raw),
                codigos_http=_codigos_http(m, raw),
                via_batch=m.get("via_llm") == "batch",
            ))
    return llamadas


def _por(tokens: int, precio: float | None, que: str, modelo: str) -> float:
    if tokens == 0:
        return 0.0
    if precio is None:
        raise ValueError(f"'{modelo}' tiene {tokens} tokens de {que} y no tiene precio para eso")
    return tokens * precio


def costo_llamada(llamada: Llamada, precios: dict[str, PrecioModelo]) -> tuple[float, bool]:
    """(costo en USD, si pagó un tramo sobre el primero) de una llamada."""
    precio = precios.get(llamada.modelo_pedido)
    if precio is None:
        raise ValueError(f"No hay precio para el modelo '{llamada.modelo_pedido}' en precios.yaml")
    i, t = precio.tramo(llamada.tokens_prompt)
    if llamada.via_batch:
        if t.batch_input is None or t.batch_output is None:
            raise ValueError(f"'{llamada.modelo_pedido}' no tiene precio de Batch en precios.yaml")
        if llamada.tokens_cache:
            # El pipeline no usa caché: no hay precio acordado para leerla en Batch.
            raise ValueError(f"Llamada por Batch con {llamada.tokens_cache} tokens de lectura "
                             f"de caché ('{llamada.modelo_pedido}'): sin precio acordado")
        return (llamada.tokens_input * t.batch_input
                + llamada.tokens_output * t.batch_output) / 1_000_000, i > 0
    usd = (
        llamada.tokens_input * t.input
        + _por(llamada.tokens_cache, t.cache_lectura, "lectura de caché", llamada.modelo_pedido)
        + _por(llamada.tokens_output, t.output, "salida", llamada.modelo_pedido)
    ) / 1_000_000
    return usd, i > 0


@dataclass
class Agregado:
    llamadas: int = 0
    llamadas_tramo_alto: int = 0
    llamadas_fallidas: int = 0  # respuestas pagadas que no sirvieron: tokens como cota inferior
    tokens_input: int = 0
    tokens_cache: int = 0
    tokens_output: int = 0
    costo_usd: float = 0.0

    def sumar(self, otro: Agregado) -> None:
        self.llamadas += otro.llamadas
        self.llamadas_tramo_alto += otro.llamadas_tramo_alto
        self.llamadas_fallidas += otro.llamadas_fallidas
        self.tokens_input += otro.tokens_input
        self.tokens_cache += otro.tokens_cache
        self.tokens_output += otro.tokens_output
        self.costo_usd += otro.costo_usd

    def fila(self) -> dict[str, Any]:
        return {
            "llamadas": self.llamadas,
            "llamadas_tramo_alto": self.llamadas_tramo_alto,
            "llamadas_fallidas": self.llamadas_fallidas,
            "tokens_input": self.tokens_input,
            "tokens_cache": self.tokens_cache,
            "tokens_output": self.tokens_output,
            "costo_usd": round(self.costo_usd, 6),
        }


def costo_por_etapa(
    llamadas: list[Llamada], precios: dict[str, PrecioModelo]
) -> dict[str, Agregado]:
    """Agregado por etapa (todas las etapas presentes, aunque tengan 0 llamadas)."""
    por_etapa = {e: Agregado() for e in ETAPAS}
    for ll in llamadas:
        usd, alto = costo_llamada(ll, precios)
        por_etapa[ll.etapa].sumar(Agregado(
            llamadas=1, llamadas_tramo_alto=int(alto), llamadas_fallidas=int(ll.fallida),
            tokens_input=ll.tokens_input,
            tokens_cache=ll.tokens_cache, tokens_output=ll.tokens_output, costo_usd=usd,
        ))
    return por_etapa


# ------------------------------------------------------------------- runs


@dataclass
class Ronda:
    etiqueta: str
    directorio: Path
    evaluacion: dict[str, Any]


@dataclass
class Run:
    ronda: str
    run_id: str
    directorio: Path
    modelo: str
    informe: str
    estado: str          # completo | error | interrumpido
    error_tipo: str
    en_evaluacion: bool
    metadata: dict[str, Any] | None
    llamadas: list[Llamada] = field(default_factory=list)
    fecha_error: str = ""  # "fecha" de error.json (ISO), si el run falló

    @property
    def modo(self) -> str:
        """"completo" o "solo_checklist" (pipeline.ejecutar_solo_checklist)."""
        return str((self.metadata or {}).get("modo") or MODO_COMPLETO)


def cargar_rondas(mediciones: Path) -> list[Ronda]:
    """Una ronda por carpeta b*/ con runs/ (y su evaluacion_*.json, si existe).

    Una evaluación sin runs/ al lado, o con un run_id que no está en runs/, es
    error (ValueError): la ronda se corrió con otro RUNS_DIR y, si no, saldría
    de las tablas (o sin sus runs) sin aviso."""
    rondas: list[Ronda] = []
    for d in sorted(p for p in mediciones.glob("b*") if p.is_dir()):
        evaluaciones = sorted(d.glob("evaluacion_*.json"))
        if not (d / "runs").is_dir():
            if evaluaciones:
                raise ValueError(f"{d} tiene {evaluaciones[0].name} pero no runs/: sus runs "
                                 "quedaron en otro RUNS_DIR (debe ser <carpeta>/runs).")
            continue
        if len(evaluaciones) > 1:
            raise ValueError(f"{d} tiene más de un evaluacion_*.json: {evaluaciones}")
        evaluacion = _leer_json(evaluaciones[0]) if evaluaciones else {}
        faltan = sorted({e["run_id"] for es in evaluacion.get("resultados", {}).values()
                         for e in es if not (d / "runs" / e["run_id"]).is_dir()})
        if faltan:
            raise ValueError(f"{d}/runs no tiene {len(faltan)} run(s) de su evaluación "
                             f"({', '.join(faltan)}): quedaron en otro RUNS_DIR.")
        etiqueta = evaluacion.get("etiqueta") or d.name.upper()
        rondas.append(Ronda(etiqueta, d, evaluacion))
    if not rondas:
        raise ValueError(f"No hay rondas (b*/runs/) en {mediciones}")
    repetidas = sorted(e for e, n in Counter(r.etiqueta for r in rondas).items() if n > 1)
    if repetidas:
        carpetas = [r.directorio.name for r in rondas if r.etiqueta in repetidas]
        raise ValueError(f"Rondas con la misma etiqueta {repetidas} en {carpetas}: se "
                         "mezclarían en todas las tablas. Cada carpeta necesita su etiqueta "
                         "(p. ej. B3 y B3s).")
    return rondas


def _inventario(mediciones: Path) -> list[dict[str, Any]]:
    ruta = mediciones / "inventario_informes.json"
    return list(_leer_json(ruta)) if ruta.exists() else []


def _modelo_por_nombre(run_id: str, conocidos: set[str]) -> str | None:
    """'2026-10-16_22-11-52_claude-opus-5-5-2' → 'claude-opus-5-5' (si es conocido)."""
    resto = run_id.split("_", 2)[-1]
    # La carpeta lleva el nombre saneado (persistence.nombre_modelo_en_run).
    candidatos = [m for m in conocidos
                  if resto == (s := nombre_modelo_en_run(m)) or resto.startswith(s + "-")]
    return max(candidatos, key=len) if candidatos else None


def cargar_runs(
    rondas: list[Ronda], inventario: list[dict[str, Any]], modelos_conocidos: set[str]
) -> list[Run]:
    """Todos los runs de todas las rondas, con su modelo, informe y estado."""
    carpeta_por_archivo = {
        unicodedata.normalize("NFC", i["archivo_original"]): i["carpeta"] for i in inventario
    }
    runs: list[Run] = []
    for ronda in rondas:
        evaluados: dict[str, tuple[str, str]] = {
            e["run_id"]: (modelo, e["informe"])
            for modelo, entradas in ronda.evaluacion.get("resultados", {}).items()
            for e in entradas
        }
        conocidos = modelos_conocidos | set(ronda.evaluacion.get("modelos", []))
        for d in sorted(p for p in (ronda.directorio / "runs").iterdir() if p.is_dir()):
            meta = _leer_json(d / "metadata.json") if (d / "metadata.json").exists() else None
            llamadas = llamadas_del_run(d)
            if d.name in evaluados:
                modelo, carpeta = evaluados[d.name]
            else:
                modelo = (
                    (meta or {}).get("modelo_extraccion")
                    or _modelo_por_nombre(d.name, conocidos)
                    or next((ll.modelo_pedido for ll in llamadas if ll.etapa != "embeddings"), "")
                )
                inputs = _leer_json(d / "inputs.json") if (d / "inputs.json").exists() else {}
                archivo = unicodedata.normalize("NFC", str(inputs.get("informe", "")))
                carpeta = carpeta_por_archivo.get(archivo) or Path(archivo).stem or "?"
            if not modelo:
                raise ValueError(f"No se pudo determinar el modelo del run {d}")
            error: dict[str, Any] = {}
            if meta is not None:
                estado = "completo"
            elif (d / "error.json").exists():
                estado, error = "error", _leer_json(d / "error.json")
            else:
                estado = "interrumpido"
            runs.append(Run(
                ronda=ronda.etiqueta, run_id=d.name, directorio=d, modelo=modelo,
                informe=nombre_corto(carpeta), estado=estado,
                error_tipo=str(error.get("tipo", "")), en_evaluacion=d.name in evaluados,
                metadata=meta, llamadas=llamadas, fecha_error=str(error.get("fecha", "")),
            ))
    return runs


# ------------------------------------------------------- checklist y comparador


def _base(ronda: Ronda, modelo: str, entrada: dict[str, Any]) -> dict[str, Any]:
    return {
        "ronda": ronda.etiqueta, "modelo": modelo,
        "informe": nombre_corto(entrada["informe"]), "run_id": entrada["run_id"],
    }


def _entradas(ronda: Ronda) -> Iterator[tuple[str, dict[str, Any]]]:
    for modelo, entradas in ronda.evaluacion.get("resultados", {}).items():
        for e in entradas:
            yield modelo, e


def codigo_registrado(ronda: Ronda) -> tuple[list[str], str]:
    """(sha256_codigo que registraron los runs de la evaluación, sha256 de la copia
    congelada verificada al lanzar o ""), para contrastarlos con la copia src/ de la
    ronda (ficha_version.csv). De cada run, su version.json (el pipeline lo escribe
    al empezar, también si el run falla) o metadata.version_codigo. Vacíos en las
    rondas anteriores a ese registro (B0-B2)."""
    hashes: set[str] = set()
    for _, e in _entradas(ronda):
        run = ronda.directorio / "runs" / e["run_id"]
        if (run / "version.json").is_file():
            hashes.add(str(_leer_json(run / "version.json")["sha256_codigo"]))
        elif (run / "metadata.json").is_file():
            version = _leer_json(run / "metadata.json").get("version_codigo")
            if version:
                hashes.add(str(version["sha256_codigo"]))
    congelado = (ronda.evaluacion.get("codigo_congelado") or {}).get("sha256_codigo") or ""
    return sorted(hashes), str(congelado)


def casos_extraccion(rondas: list[Ronda]) -> list[metricas_extraccion.Caso]:
    """Los runs de cada evaluación con comparador (ni fallidos ni solo
    checklist), para la métrica de la extracción."""
    return [
        metricas_extraccion.Caso(ronda.etiqueta, modelo, nombre_corto(e["informe"]),
                                 ronda.directorio / "runs" / e["run_id"])
        for ronda in rondas for modelo, e in _entradas(ronda)
        if "error" not in e and e.get("modo") != MODO_SOLO_CHECKLIST
    ]


def cargar_fichas_mediciones(mediciones: Path) -> dict[str, fichas.Ficha]:
    """Las fichas de mediciones/fichas_informes.yaml (M39); vacío si no existe."""
    ruta = mediciones / "fichas_informes.yaml"
    return fichas.cargar_fichas(ruta) if ruta.is_file() else {}


def muestra_de(entrada: dict[str, Any], por_carpeta: dict[str, fichas.Ficha]) -> str:
    """dentro / fuera de muestra / sin_ficha de una entrada de la evaluación: con la
    ficha que copió evaluar_lote (la del momento de medir) o, si la ronda no la
    trae (B0-B2), con la del YAML de mediciones/."""
    copiada = entrada.get("ficha")
    if copiada is not None:
        return fichas.muestra(fichas.Ficha.model_validate(copiada))
    return fichas.muestra(fichas.ficha_de(por_carpeta, entrada["informe"]))


def filas_checklist(
    rondas: list[Ronda], por_carpeta: dict[str, fichas.Ficha] | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(por informe, por punto). Los conteos se recalculan desde los ítems; cada
    fila lleva si el informe está dentro o fuera de muestra (``muestra_de``)."""
    por_informe: list[dict[str, Any]] = []
    por_punto: list[dict[str, Any]] = []
    for ronda in rondas:
        for modelo, e in _entradas(ronda):
            base = _base(ronda, modelo, e)
            muestra = muestra_de(e, por_carpeta or {})
            gt = e.get("checklist_gt")
            estado = "error" if "error" in e else ("sin_gt" if gt is None else "evaluado")
            fila: dict[str, Any] = {**base, "estado": estado, "muestra": muestra}
            if gt is not None:
                items = gt["items"]
                desconocidas = {i["clasificacion"] for i in items} - set(CLASIFICACIONES)
                if desconocidas:
                    raise ValueError(f"Clasificaciones desconocidas en {base}: {desconocidas}")
                n = Counter(i["clasificacion"] for i in items)
                incumplimientos = [i for i in items if i["veredicto_gt"] == "NO"]
                fila.update({
                    "evaluados": len(items),
                    "aciertos": n["acierto"],
                    "no_verificables": n["no_verificable"],
                    "falsos_no_cumple": n["falso_no_cumple"],
                    "falsos_cumple": n["falso_cumple"],
                    "incumplimientos_gt": len(incumplimientos),
                    "incumplimientos_detectados": sum(
                        1 for i in incumplimientos if i["resultado_sistema"] == "no_cumple"
                    ),
                    "puntos_falso_cumple": ";".join(
                        str(i["numero"]) for i in items if i["clasificacion"] == "falso_cumple"
                    ),
                    "puntos_sin_gt": ";".join(str(p) for p in gt.get("sin_gt", [])),
                })
                por_punto.extend({
                    **base,
                    "punto": i["numero"],
                    "codigo_gt": i["codigo_gt"],
                    "veredicto_gt": i["veredicto_gt"],
                    "resultado": i["resultado_sistema"],
                    "clasificacion": i["clasificacion"],
                    "muestra": muestra,
                } for i in items)
            por_informe.append(fila)
    return por_informe, por_punto


BAJADAS_CONTRA_PLANILLA = ("bajados_que_eran_falso_cumple", "bajados_que_eran_acierto")


def _cita_checklist(ronda: Ronda, run_dir: Path) -> Any:
    """Si el run pidió la cita del checklist: la config de la evaluación o, si no
    la trae, la metadata del run; vacío si ninguna lo dice."""
    config = ronda.evaluacion.get("config") or {}
    if "cita_checklist" in config:
        return config["cita_checklist"]
    meta = run_dir / "metadata.json"
    valor = _leer_json(meta).get("cita_checklist") if meta.is_file() else None
    return "" if valor is None else valor


def _bajadas_por_escenario(
    base: dict[str, Any], ck: dict[str, Any], items: list[dict[str, Any]] | None,
    cita_checklist: Any, clave: tuple[str, str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Una fila por escenario de la planilla con los «cumple» bajados sin cita y,
    contra la planilla, cuántos eran falsos cumple (bajada que evitó un error) y
    cuántos aciertos (perdidos). Con la planilla al medir, lo guardado debe
    reproducirse; sin ``puntos_bajados`` (anterior a PD52) se toma lo guardado."""
    puntos = ck.get("puntos_bajados")
    problemas: list[str] = []
    if puntos is not None and len(puntos) != ck["bajados_sin_cita_verificada"]:
        problemas.append(f"{clave} citas.checklist.bajados_sin_cita_verificada: "
                         f"{ck['bajados_sin_cita_verificada']} ≠ {len(puntos)} puntos_bajados")
    filas: list[dict[str, Any]] = []
    for escenario in conf.ESCENARIOS:
        fila = {
            "escenario": escenario, **base, "cita_checklist": cita_checklist,
            "bajados_sin_cita_verificada": ck["bajados_sin_cita_verificada"],
            "puntos_bajados": ";".join(map(str, puntos)) if puntos is not None else "",
        }
        if items is not None and puntos is not None:
            veredictos = [
                conf.veredicto_escenario(base["informe"], int(i["numero"]), i["veredicto_gt"],
                                         escenario)
                for i in items if i["numero"] in puntos]
            fila |= {"bajados_que_eran_falso_cumple": veredictos.count("NO"),
                     "bajados_que_eran_acierto": veredictos.count("SI")}
            if escenario == "planilla_al_medir":
                problemas += [f"{clave} citas.checklist.{c}: {ck[c]} ≠ {fila[c]}"
                              for c in BAJADAS_CONTRA_PLANILLA if c in ck and ck[c] != fila[c]]
        elif items is not None and escenario == "planilla_al_medir":
            fila |= {c: ck.get(c, "") for c in BAJADAS_CONTRA_PLANILLA}
        filas.append(fila)
    return filas, problemas


def filas_citas(
    rondas: list[Ronda],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """(estados de las citas en largo, bajadas del checklist por escenario,
    discrepancias) desde ``citas`` de cada entrada de la evaluación (PD52).

    Las rondas sin citas (B0-B2) no tienen filas: los CSV quedan con la cabecera.
    """
    largo: list[dict[str, Any]] = []
    bajadas: list[dict[str, Any]] = []
    problemas: list[str] = []
    for ronda in rondas:
        for modelo, e in _entradas(ronda):
            citas = e.get("citas")
            if not citas:
                continue
            base = {**_base(ronda, modelo, e), "modo": e.get("modo") or MODO_COMPLETO}
            comparador = citas.get("comparador") or {}
            ck = citas.get("checklist")
            por_ambito = [("comparador_descripcion", comparador.get("descripcion") or {}),
                          ("comparador_accion", comparador.get("accion") or {}),
                          ("checklist", (ck or {}).get("estados") or {})]
            largo += [{**base, "ambito": ambito, "estado": estado, "n": n}
                      for ambito, estados in por_ambito for estado, n in sorted(estados.items())]
            if ck is not None:
                filas, dif = _bajadas_por_escenario(
                    base, ck, (e.get("checklist_gt") or {}).get("items"),
                    _cita_checklist(ronda, ronda.directorio / "runs" / e["run_id"]),
                    (ronda.etiqueta, e["run_id"]))
                bajadas += filas
                problemas += dif
    return largo, bajadas, problemas


# ------------------------------------------- lectura por partes del checklist (M08)


@dataclass(frozen=True)
class LecturaPorPartes:
    """El checklist de un run leído por partes en los dos modos de M08."""

    fuente: str         # guardado (checklist.json 0.8.0) | simulado (raw de un run anterior)
    modo_aplicado: str  # marcar | bajar | ninguno (run anterior a M08)
    tramos: int
    vistos: list[int]   # «cumple» del modelo que no respaldan todas las partes (visto_en_parte)
    en_lista: list[int]  # de ellos, los que siguen en «cumple» y exigen todo el informe
    marcando: dict[int, ResultadoChecklist]
    bajando: dict[int, ResultadoChecklist]

    @property
    def aplicado(self) -> dict[int, ResultadoChecklist]:
        """Los resultados que guardó el run (antes de M08 = los de «marcar»)."""
        return self.bajando if self.modo_aplicado == "bajar" else self.marcando


def _lectura_guardada(ck: ChecklistInforme) -> tuple[LecturaPorPartes, list[str]]:
    """Un checklist.json 0.8.0 leído por partes: el modo que aplicó, el otro
    reconstruido, y lo que no cuadra con sus contadores."""
    assert ck.tramos_leidos is not None
    modo = "marcar" if ck.bajados_un_tramo is None else "bajar"
    vistos = [i.numero for i in ck.items if visto_en_parte(i, len(ck.tramos_leidos))]
    siguen = [i.numero for i in ck.items
              if i.numero in vistos and i.resultado == ResultadoChecklist.CUMPLE]
    bajados = [i.numero for i in ck.items if i.causa_ajuste == CausaAjuste.UN_TRAMO]
    con_aviso = [i.numero for i in ck.items if i.aviso_tramos is not None]
    problemas = [texto for falla, texto in (
        (con_aviso != vistos, f"aviso_tramos en {con_aviso} ≠ vistos en parte {vistos}"),
        (ck.marcados_un_tramo != len(siguen), f"marcados_un_tramo: {ck.marcados_un_tramo} ≠ "
                                              f"{len(siguen)} vistos en parte en «cumple»"),
        ((ck.bajados_un_tramo or 0) != len(bajados),
         f"bajados_un_tramo: {ck.bajados_un_tramo} ≠ {len(bajados)} con causa un_tramo"),
    ) if falla]
    marcando = {i.numero: (i.resultado_modelo or i.resultado)
                if i.causa_ajuste == CausaAjuste.UN_TRAMO else i.resultado for i in ck.items}
    en_lista = bajados if modo == "bajar" else [
        n for n in siguen if n in PUNTOS_EXIGEN_TODO_EL_INFORME]
    bajando = {n: ResultadoChecklist.NO_VERIFICABLE if n in en_lista else r
               for n, r in marcando.items()}
    return LecturaPorPartes("guardado", modo, len(ck.tramos_leidos), vistos, en_lista,
                            marcando, bajando), problemas


def _lectura_simulada(
    raw: dict[str, Any], puntos: list[dict[str, Any]], ck: ChecklistInforme
) -> tuple[LecturaPorPartes | None, list[str]]:
    """Un run anterior a M08: las respuestas de cada parte (raw) pasan por la
    fusión y M08 en los dos modos; la fusión debe dar lo guardado."""
    marcar = checklist_desde_raw(raw, puntos, modo="marcar")
    bajar = checklist_desde_raw(raw, puntos, modo="bajar")
    if marcar.tramos_leidos is None:
        return None, []
    marcando = {i.numero: i.resultado for i in marcar.items}
    guardado = {i.numero: i.resultado for i in ck.items}
    distintos = sorted(n for n in marcando.keys() | guardado.keys()
                       if marcando.get(n) != guardado.get(n))
    problemas = [f"la fusión de las partes del raw no reproduce los puntos {distintos}"
                 ] if distintos else []
    return LecturaPorPartes(
        "simulado", "ninguno", len(marcar.tramos_leidos),
        [i.numero for i in marcar.items if visto_en_parte(i, len(marcar.tramos_leidos))],
        [i.numero for i in bajar.items if i.causa_ajuste == CausaAjuste.UN_TRAMO],
        marcando, {i.numero: i.resultado for i in bajar.items},
    ), problemas


def lectura_por_partes(
    run_dir: Path, puntos: list[dict[str, Any]]
) -> tuple[LecturaPorPartes | None, list[str]]:
    """M08 en un run: None si no tiene checklist o lo leyó entero. Un
    checklist.json 0.8.0 manda (también si su raw trae citas); sin él, se simula
    desde el raw (un raw con citas y sin M08 falla: checklist_desde_raw)."""
    ruta = run_dir / "checklist.json"
    if not ruta.is_file():
        return None, []
    ck = ChecklistInforme.model_validate(_leer_json(ruta))
    if ck.tramos_leidos is not None:
        return _lectura_guardada(ck)
    ruta_raw = run_dir / "checklist_raw" / "verificar_checklist.json"
    raw = _leer_json(ruta_raw) if ruta_raw.is_file() else {}
    if "llamadas" not in raw:
        return None, []
    return _lectura_simulada(raw, puntos, ck)


def _aciertos(resultados: dict[int, ResultadoChecklist], veredictos: dict[int, str]) -> int:
    return sum(1 for n, v in veredictos.items() if clasificar(resultados[n], v) == "acierto")


def filas_un_tramo(rondas: list[Ronda]) -> tuple[list[dict[str, Any]], list[str]]:
    """(filas, discrepancias) de la lectura por partes del checklist (M08): una
    fila por run leído por partes de cada evaluación y escenario de la planilla.

    Cuenta los «cumple» vistos en una sola parte, los que bajarían en modo
    «bajar» (en la lista) y, contra la planilla, cuántos eran falsos cumple,
    aciertos o puntos sin planilla (de los vistos, los que siguen en «cumple» al
    marcar: los que bajó la cita no llevan ese aviso como «cumple»), con los
    aciertos del run marcando y bajando.
    B0-B2 se simulan desde el raw; un run 0.8.0 sale de su checklist.json.
    Discrepancias: contadores guardados que no cuadran, una simulación que no
    reproduce checklist.json, o aciertos en el modo aplicado (planilla al
    medir) distintos de los de la evaluación."""
    puntos = cargar_puntos()
    filas: list[dict[str, Any]] = []
    problemas: list[str] = []
    for ronda in rondas:
        for modelo, e in _entradas(ronda):
            if "error" in e:
                continue
            clave = (ronda.etiqueta, e["run_id"])
            lectura, dif = lectura_por_partes(ronda.directorio / "runs" / e["run_id"], puntos)
            problemas += [f"{clave} checklist.json (lectura por partes): {d}" for d in dif]
            if lectura is None:
                continue
            base = _base(ronda, modelo, e)
            gt = e.get("checklist_gt")
            for escenario in conf.ESCENARIOS:
                fila: dict[str, Any] = {
                    "escenario": escenario, **base, "fuente": lectura.fuente,
                    "modo_aplicado": lectura.modo_aplicado, "tramos": lectura.tramos,
                    "vistos_en_una_parte": len(lectura.vistos),
                    "puntos_vistos": ";".join(map(str, lectura.vistos)),
                    "en_lista": len(lectura.en_lista),
                    "puntos_en_lista": ";".join(map(str, lectura.en_lista)),
                }
                if gt is not None:
                    veredictos = {
                        int(i["numero"]): conf.veredicto_escenario(
                            base["informe"], int(i["numero"]), i["veredicto_gt"], escenario)
                        for i in gt["items"]}
                    # El aviso de «marcar»: los vistos que siguen en «cumple» al marcar
                    # (sin los que bajó la cita, que cuenta citas_checklist.csv).
                    avisados = [n for n in lectura.vistos
                                if lectura.marcando[n] == ResultadoChecklist.CUMPLE]
                    fila |= {
                        "evaluados": len(veredictos),
                        "vistos_que_eran_falso_cumple": sum(
                            1 for n in avisados if veredictos.get(n) == "NO"),
                        "vistos_que_eran_acierto": sum(
                            1 for n in avisados if veredictos.get(n) == "SI"),
                        "en_lista_que_eran_falso_cumple": sum(
                            1 for n in lectura.en_lista if veredictos.get(n) == "NO"),
                        "en_lista_que_eran_acierto": sum(
                            1 for n in lectura.en_lista if veredictos.get(n) == "SI"),
                        "en_lista_sin_planilla": sum(
                            1 for n in lectura.en_lista if n not in veredictos),
                        "aciertos_marcando": _aciertos(lectura.marcando, veredictos),
                        "aciertos_bajando": _aciertos(lectura.bajando, veredictos),
                    }
                    aplicado = _aciertos(lectura.aplicado, veredictos)
                    if escenario == "planilla_al_medir" and aplicado != gt["aciertos"]:
                        problemas.append(
                            f"{clave} checklist_gt.aciertos: {gt['aciertos']} ≠ {aplicado} con "
                            f"el checklist del run (lectura por partes, {lectura.modo_aplicado})")
                filas.append(fila)
    return filas, problemas


# ------------------------------------------- errores del checklist (M09, PD20)

# Clasificación privada de los falsos no cumple y no verificables (fuera de los
# anexos), adjudicada contra el informe y la planilla; la columna ``verificado`` dice
# si un segundo agente la revisó.
RUTA_ERRORES_CHECKLIST = Path("adjudicacion_checklist") / "m09.json"
CLASES_M09 = ("no_encontro", "juzgo_distinto", "criterio_abierto", "criterio_retirado",
              "planilla_dudosa", "evidencia_fuera_del_pdf")
VOCABULARIO_M09 = ("igual", "sinonimo", "distinto", "")
ERRORES_CHECKLIST = ("falso_no_cumple", "no_verificable")
MODELO_COMPUERTA_M10 = "claude-opus-5-5"   # D3(a): el modelo por defecto
# Rondas y modelos cuyos errores se clasifican (D1): sin m09.json, cada error de
# este alcance es una discrepancia; el alcance del archivo debe ser este.
ALCANCE_M09 = (("B2", "claude-opus-5-5"), ("B2", "claude-sonnet-5-5"),
               ("B3", "claude-opus-5-5"), ("B3s", "claude-opus-5-5"))


def tercio_de(pagina: int | None, total: int | None) -> int | str:
    """Tercio del PDF (1, 2 o 3) en que cae el centro de la página de la evidencia;
    "" sin página."""
    if pagina is None or total is None:
        return ""
    if not 1 <= pagina <= total:
        raise ValueError(f"página {pagina} fuera del PDF (1-{total})")
    return (6 * pagina - 3) // (2 * total) + 1


def validar_tramo(tramo: str) -> str:
    """"k/N" (parte k de un informe leído en N > 1 partes) o "" si se leyó entero."""
    if tramo == "":
        return tramo
    k, _, n = tramo.partition("/")
    if not (k.isdigit() and n.isdigit() and 1 <= int(k) <= int(n) and int(n) > 1):
        raise ValueError(f"tramo {tramo!r} no es k/N con 1 ≤ k ≤ N y N > 1")
    return tramo


def _caso_m09(caso: dict[str, Any]) -> tuple[str, str, str, int]:
    clave = (str(caso["ronda"]), str(caso["modelo"]), str(caso["run_id"]), int(caso["punto"]))
    if caso["clase"] not in CLASES_M09:
        raise ValueError(f"M09 {clave}: clase desconocida {caso['clase']!r}")
    if caso.get("vocabulario", "") not in VOCABULARIO_M09:
        raise ValueError(f"M09 {clave}: vocabulario {caso['vocabulario']!r} no es uno de "
                         f"{VOCABULARIO_M09}")
    if caso["clase"] == "criterio_abierto" and clave[3] not in conf.PREGUNTAS_ABIERTAS:
        raise ValueError(f"M09 {clave}: criterio_abierto en un punto sin pregunta abierta "
                         "(bloque origen de checklist_puntos.yaml)")
    preguntas = caso.get("preguntas") or []
    if caso["clase"] != "criterio_abierto" and preguntas:
        raise ValueError(f"M09 {clave}: preguntas en un caso que no es criterio_abierto")
    if caso["clase"] == "criterio_abierto" and not (
            preguntas and set(preguntas) <= set(conf.PREGUNTAS_ABIERTAS[clave[3]])):
        raise ValueError(f"M09 {clave}: preguntas {preguntas} no son las que nombran el caso "
                         f"entre las del bloque origen del punto "
                         f"{conf.PREGUNTAS_ABIERTAS[clave[3]]}")
    return clave


def filas_errores_checklist(
    mediciones: Path, por_punto: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """(filas, discrepancias) de checklist_errores_clasificados.csv (M09).

    Cada falso no cumple o no verificable fuera de los anexos, por escenario de la
    planilla, de las rondas y modelos de ``ALCANCE_M09``, con su clase y, si es
    criterio_abierto, las preguntas que nombran el caso. Sin texto: la
    justificación y la cita se quedan en mediciones/. Un error sin clasificar
    (también si falta el archivo), o una clasificación que no es de un error, es
    una discrepancia; una clase desconocida o un alcance distinto, ValueError."""
    ruta = mediciones / RUTA_ERRORES_CHECKLIST
    datos = _leer_json(ruta) if ruta.is_file() else {"alcance": None, "casos": []}
    alcance = set(ALCANCE_M09)
    if datos["alcance"] is not None and {
            (a["ronda"], a["modelo"]) for a in datos["alcance"]} != alcance:
        raise ValueError(f"{RUTA_ERRORES_CHECKLIST}: el alcance no es ALCANCE_M09 "
                         f"{sorted(alcance)}")
    sin_archivo = "" if ruta.is_file() else f" (falta {RUTA_ERRORES_CHECKLIST})"
    casos: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    for caso in datos["casos"]:
        clave = _caso_m09(caso)
        if clave in casos:
            raise ValueError(f"M09 {clave}: caso repetido")
        casos[clave] = caso
    filas: list[dict[str, Any]] = []
    usados: set[tuple[str, str, str, int]] = set()
    sin_clase: list[str] = []
    for p in por_punto:
        punto = int(p["punto"])
        if (p["ronda"], p["modelo"]) not in alcance or punto in conf.PUNTOS_ANEXOS:
            continue
        clave = (p["ronda"], p["modelo"], p["run_id"], punto)
        for escenario in conf.ESCENARIOS:
            veredicto = conf.veredicto_escenario(p["informe"], punto, p["veredicto_gt"],
                                                 escenario)
            clasificacion = clasificar(ResultadoChecklist(p["resultado"]), veredicto)
            if clasificacion not in ERRORES_CHECKLIST:
                continue
            caso = casos.get(clave)
            if caso is None:
                sin_clase.append(f"M09 {escenario} {p['ronda']} {p['modelo']} {p['informe']} "
                                 f"punto {punto}: {clasificacion} sin clasificar{sin_archivo}")
                continue
            usados.add(clave)
            pagina, total = caso.get("pagina_evidencia"), caso.get("paginas_pdf")
            filas.append({
                "escenario": escenario, "ronda": p["ronda"], "modelo": p["modelo"],
                "informe": p["informe"], "run_id": p["run_id"], "punto": punto,
                "codigo_gt": p["codigo_gt"], "grupo": str(p["codigo_gt"]).split(".")[0],
                "clasificacion": clasificacion, "clase_m09": caso["clase"],
                "pregunta_abierta": "; ".join(caso.get("preguntas") or []),
                "pagina_evidencia": "" if pagina is None else pagina,
                "paginas_pdf": "" if total is None else total,
                "tercio": tercio_de(pagina, total),
                "tramo": validar_tramo(str(caso.get("tramo") or "")),
                "vocabulario": caso.get("vocabulario", ""),
                "verificado": bool(caso.get("verificado_por_segundo_agente")),
            })
    sobrantes = [f"M09 {r} {m} {run} punto {n}: clasificado pero no es un error del checklist"
                 for r, m, run, n in sorted(set(casos) - usados)]
    return filas, sin_clase + sobrantes


def grupos_compuerta_m10(filas: list[dict[str, Any]]) -> list[str]:
    """Grupos del checklist (prefijo del código de la planilla) con casos «no
    encontró» de Opus en al menos dos informes, con la planilla corregida: los
    que abren la compuerta de M10 (PD20, D3(a))."""
    informes: dict[str, set[str]] = {}
    for f in filas:
        if (f["escenario"], f["modelo"], f["clase_m09"]) == (
                "planilla_corregida", MODELO_COMPUERTA_M10, "no_encontro"):
            informes.setdefault(f["grupo"], set()).add(f["informe"])
    return sorted(g for g, inf in informes.items() if len(inf) >= 2)


def conteo_comparador(reporte: dict[str, Any]) -> dict[str, Any]:
    """Recuento de estados de un reporte_final.json (como lo hace la Etapa 5)."""
    resultados = reporte.get("resultados", [])
    estados = Counter(r["estado"] for r in resultados)
    desconocidos = set(estados) - set(ESTADOS_COMPARADOR)
    if desconocidos:
        raise ValueError(f"Estados desconocidos en el reporte: {desconocidos}")
    # El juez de redacción existe desde el schema 0.6.0: antes, columna vacía.
    con_redaccion = "coinciden_con_redaccion_distinta" in reporte.get("resumen", {}) or any(
        "equivalencias_redaccion" in r for r in resultados
    )
    return {
        "total": len(resultados),
        "coinciden": estados["coincide"],
        "difieren": estados["difiere"],
        "faltan_en_excel": estados["falta_en_excel"],
        "extra_en_excel": estados["extra_en_excel"],
        "transversales": estados["transversal"],
        # Sin par o con un emparejamiento dudoso: también el que lleva
        # emparejamiento_dudoso (asignación global, PD71; schema 0.9.0).
        "requieren_revision": sum(
            1 for r in resultados
            if r["estado"] != "transversal"
            and (r.get("tipo_match") in TIPOS_REQUIEREN_REVISION
                 or r.get("emparejamiento_dudoso") is not None)
        ),
        "coinciden_con_redaccion_distinta": sum(
            1 for r in resultados
            if r["estado"] == "coincide" and r.get("equivalencias_redaccion")
        ) if con_redaccion else "",
    }


def filas_comparador(rondas: list[Ronda]) -> list[dict[str, Any]]:
    filas: list[dict[str, Any]] = []
    for ronda in rondas:
        for modelo, e in _entradas(ronda):
            if e.get("modo") == MODO_SOLO_CHECKLIST:
                continue  # no corrió el comparador: no es un error
            fila: dict[str, Any] = {**_base(ronda, modelo, e)}
            reporte = ronda.directorio / "runs" / e["run_id"] / "reporte_final.json"
            if "error" in e or not reporte.exists():
                fila["estado"] = "error"
            else:
                fila["estado"] = "completo"
                fila.update(conteo_comparador(_leer_json(reporte)))
            filas.append(fila)
    return filas


# ------------------------------------------------------------------ tiempo


def makespan(duraciones: list[float], paralelismo: int) -> float:
    """Tiempo total de tareas que toman, en orden, el primer cupo libre de N."""
    cupos = [0.0] * max(1, paralelismo)
    for d in duraciones:
        i = cupos.index(min(cupos))
        cupos[i] += d
    return max(cupos)


def _segundos(llamadas: list[Llamada], etapas: tuple[str, ...]) -> float:
    return sum(ll.tiempo_segundos or 0.0 for ll in llamadas if ll.etapa in etapas)


def tiempos_del_run(run: Run) -> dict[str, float]:
    """Tiempos por etapa y camino crítico estimado de un run completo.

    En el código medido, el checklist (E0), E1 y E2 corren en paralelo y la
    Etapa 3 recién parte cuando terminan los tres (asyncio.gather en
    pipeline.py); E3 extrae de a PARALELISMO_E3 paños (un paño reintentado
    suma sus dos intentos) y E4 llama al juez en serie. Por eso:

        camino crítico = max(E0, E1) + E3 (cupos de 3 paños) + E4

    E2 es local y los embeddings no registran tiempo: quedan fuera.
    """
    por_pano: dict[str, float] = {}
    for ll in run.llamadas:
        if ll.etapa == "e3":
            clave = ll.pano or "?"
            por_pano[clave] = por_pano.get(clave, 0.0) + (ll.tiempo_segundos or 0.0)
    panos_e1 = run.directorio / "etapa1_panos.json"
    orden = [p["nombre"] for p in _leer_json(panos_e1)] if panos_e1.exists() else []
    orden = [p for p in orden if p in por_pano] + sorted(p for p in por_pano if p not in orden)
    t_checklist = _segundos(run.llamadas, ("checklist",))
    t_e1 = _segundos(run.llamadas, ("e1",))
    t_e3 = makespan([por_pano[p] for p in orden], PARALELISMO_E3)
    t_e4 = _segundos(run.llamadas, ("e4_juez", "e4_redaccion"))
    return {
        "t_checklist": t_checklist,
        "t_e1": t_e1,
        "t_e3": t_e3,
        "t_e3_pano_mas_lento": max(por_pano.values(), default=0.0),
        "t_e4": t_e4,
        "camino_critico_estimado": max(t_checklist, t_e1) + t_e3 + t_e4,
    }


# Etapas con reloj en metadata.json (pipeline._reloj) → columna de tiempo_por_informe.csv.
COLUMNA_RELOJ = {"checklist": "t_checklist", "e1": "t_e1", "e2": "t_e2", "e3": "t_e3",
                 "e4": "t_e4", "e5": "t_e5"}


def tiempos_relojes(relojes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Tiempos por etapa medidos (``relojes_etapas`` de metadata.json, M58).

    camino crítico = último fin − primer inicio, sobre todas las etapas con
    reloj: no supone un orden, así que ve el ahorro de reordenar etapas o de
    paralelizar el juez (la fórmula de tiempos_del_run no). E4 incluye los
    embeddings. Una etapa sin reloj queda vacía.
    """
    tramos = [(datetime.fromisoformat(r["inicio"]), float(r["segundos"]))
              for r in relojes.values()]
    inicio = min(i for i, _ in tramos)
    fin = max(i + timedelta(seconds=s) for i, s in tramos)
    return {
        **{col: float(relojes[etapa]["segundos"]) if etapa in relojes else ""
           for etapa, col in COLUMNA_RELOJ.items()},
        "camino_critico_relojes": round((fin - inicio).total_seconds(), 2),
    }


def _intervalo(run: Run) -> tuple[datetime, datetime] | None:
    """(inicio, fin) del run.

    Un run completo, desde metadata.json. Uno fallido no tiene metadata pero
    también ocupó la API: parte en el timestamp de su carpeta (crear_run_dir,
    truncado al segundo: se toma el último instante posible, +1 s) y termina en
    la "fecha" de error.json; si no la hay (interrumpido), cuenta solo su inicio.
    """
    meta = run.metadata
    if meta is not None:
        if not meta.get("fecha_inicio") or not meta.get("fecha_fin"):
            return None
        return (
            datetime.fromisoformat(meta["fecha_inicio"]),
            datetime.fromisoformat(meta["fecha_fin"]),
        )
    inicio = datetime.strptime(run.run_id[:19], "%Y-%m-%d_%H-%M-%S") + timedelta(seconds=1)
    return inicio, datetime.fromisoformat(run.fecha_error) if run.fecha_error else inicio


def runs_solapados(run: Run, runs: list[Run]) -> int:
    """Cuántos otros runs de la misma ronda (también fallidos) se solaparon con este.

    Es una cota inferior: de un run interrumpido solo se conoce el inicio.
    """
    propio = _intervalo(run)
    if propio is None:
        return 0
    n = 0
    for otro in runs:
        if otro is run or otro.ronda != run.ronda:
            continue
        intervalo = _intervalo(otro)
        if intervalo and intervalo[0] < propio[1] and propio[0] < intervalo[1]:
            n += 1
    return n


def filas_tiempo(runs: list[Run]) -> list[dict[str, Any]]:
    """Una fila por run completo. Un run solo checklist entra solo con relojes
    (B3s: el tiempo del checklist sin la cita frente al de B3, con ella), con su
    ``modo`` a la vista: su camino crítico no se compara con el de un run completo."""
    filas: list[dict[str, Any]] = []
    for run in runs:
        if run.estado != "completo":
            continue
        assert run.metadata is not None
        relojes = run.metadata.get("relojes_etapas")
        if run.modo == MODO_SOLO_CHECKLIST and not relojes:
            continue  # sin relojes no hay tiempo medido que comparar
        t = {k: round(v, 2) for k, v in tiempos_del_run(run).items()}
        fila = {
            **_cabecera(run),
            "duracion_segundos": run.metadata.get("duracion_segundos"),
            "runs_solapados": runs_solapados(run, runs),
            **t,
            "t_e2": "", "t_e5": "", "camino_critico_relojes": "", "fuente_tiempo": "estimado",
            "modo": run.modo,
            **{f"{c}_llamadas": t[c] for c in ("t_checklist", "t_e1", "t_e3", "t_e4")},
        }
        # Con relojes, los t_* son los medidos; camino_critico_estimado y los
        # *_llamadas (desde los raw) se conservan para compararlos: el reloj de una
        # etapa incluye además la subida del PDF a Files API y count_tokens, que
        # compiten con la otra etapa en paralelo (B3) y no cuando el checklist corre
        # solo (B3s). Sin relojes (B0-B2), los t_* son los de las llamadas.
        if relojes:
            fila |= {**tiempos_relojes(relojes), "fuente_tiempo": "relojes"}
        filas.append(fila)
    return filas


# ------------------------------------------------------------------- costo


def _cabecera(run: Run) -> dict[str, Any]:
    return {
        "ronda": run.ronda, "modelo": run.modelo, "informe": run.informe,
        "run_id": run.run_id, "en_evaluacion": run.en_evaluacion,
    }


def filas_costo(
    runs: list[Run], precios: dict[str, PrecioModelo]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """(por informe × etapa, por informe, campaña por ronda × modelo)."""
    por_etapa: list[dict[str, Any]] = []
    por_informe: list[dict[str, Any]] = []
    campana: dict[tuple[str, str], tuple[Counter[str], Agregado, Agregado]] = {}
    for run in runs:
        etapas = costo_por_etapa(run.llamadas, precios)
        total = Agregado()
        for etapa, agg in etapas.items():
            total.sumar(agg)
            por_etapa.append({
                **_cabecera(run), "estado_run": run.estado, "etapa": etapa, **agg.fila(),
            })
        por_informe.append({
            **_cabecera(run), "estado_run": run.estado, "error_tipo": run.error_tipo,
            "costo_es_cota_inferior": run.estado != "completo", **total.fila(),
            **reintentos_del_run(run.llamadas),
        })
        n, todos, evaluados = campana.setdefault(
            (run.ronda, run.modelo), (Counter(), Agregado(), Agregado())
        )
        n.update({"runs": 1, run.estado: 1, "en_evaluacion": int(run.en_evaluacion)})
        todos.sumar(total)
        if run.en_evaluacion:
            evaluados.sumar(total)
    filas_campana = [{
        "ronda": ronda, "modelo": modelo, "runs": n["runs"], "runs_completos": n["completo"],
        "runs_error": n["error"], "runs_interrumpidos": n["interrumpido"],
        "runs_en_evaluacion": n["en_evaluacion"], **todos.fila(),
        "costo_usd_runs_evaluados": round(evaluados.costo_usd, 6),
        "costo_usd_fuera_de_evaluacion": round(todos.costo_usd - evaluados.costo_usd, 6),
    } for (ronda, modelo), (n, todos, evaluados) in campana.items()]
    return por_etapa, por_informe, filas_campana


# ----------------------------------------------------------- tamaño y control


def filas_tamano(mediciones: Path, inventario: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filas: list[dict[str, Any]] = []
    for i in inventario:
        troceo = i.get("troceo") or {}
        tramos = (troceo.get("checklist") or {}).get("tramos") or []
        leidas = (troceo.get("descubrir_panos") or {}).get("paginas_leidas")
        referencia = mediciones / i["run_referencia"] if i.get("run_referencia") else None
        input_checklist: int | str = ""
        if referencia is not None and referencia.is_dir():
            input_checklist = sum(
                ll.tokens_prompt for ll in llamadas_del_run(referencia) if ll.etapa == "checklist"
            )
        filas.append({
            "informe": nombre_corto(i["carpeta"]),
            "auditora": i.get("empresa_auditora", ""),
            "formato_original": i.get("formato_original", ""),
            "mb_original": i.get("mb_original", ""),
            "paginas_pdf_visto": i.get("paginas_pdf_visto_por_el_modelo", ""),
            "mb_pdf_visto": i.get("mb_pdf_visto", ""),
            "tokens_input_checklist_b2_sonnet": input_checklist,
            "tramos_checklist": len(tramos) or 1,
            "paginas_leidas_e1": f"{leidas[0]}-{leidas[1]}" if leidas else "todas",
            "panos_e1": len(i.get("panos_e1") or []),
            "filas_excel_normalizadas": i.get("filas_excel_normalizadas", ""),
            "filas_excel_transversales": i.get("filas_excel_transversales", ""),
            "tiene_checklist_gt": i.get("tiene_checklist_gt", ""),
            # convertir_docx_a_pdf solo informa la conversión si omitió imágenes:
            # un DOCX sin ese dato omitió 0. Vacío = no aplica (no es DOCX).
            "imagenes_omitidas_docx": (i.get("conversion_docx") or {}).get(
                "imagenes_omitidas", 0
            ) if i.get("formato_original") == "docx" else "",
        })
    return filas


def _tokens_envoltorio(run_dir: Path) -> list[tuple[str, int, int]]:
    """(raw, tokens_total del envoltorio, suma de sus llamadas) que no cuadran."""
    malos: list[tuple[str, int, int]] = []
    for raw in sorted(run_dir.glob("*_raw/*.json")):
        meta = _leer_json(raw)
        if "llamadas" in meta:
            suma = sum(
                (m.get("tokens_prompt") or 0) + (m.get("tokens_completion") or 0)
                for m in _aplanar(meta)
            )
            if meta.get("tokens_total") != suma:
                malos.append((f"{raw.parent.name}/{raw.name}", meta.get("tokens_total"), suma))
    return malos


def filas_control(runs: list[Run]) -> list[dict[str, Any]]:
    """Suma de los raw (prompt + completion) contra tokens_* de metadata.json.

    Estados: ok, diferencia, campo_ausente (la metadata de esa versión no tenía
    el campo) y sin_metadata (run fallido: no hay contra qué comparar).
    """
    filas: list[dict[str, Any]] = []
    for run in runs:
        for etapa in ETAPAS:
            raw = sum(
                ll.tokens_input + ll.tokens_output for ll in run.llamadas if ll.etapa == etapa
            )
            declarado = (run.metadata or {}).get(CAMPO_METADATA[etapa])
            if run.metadata is None:
                estado = "sin_metadata"
            elif declarado is None:
                estado = "campo_ausente"
            else:
                estado = "ok" if declarado == raw else "diferencia"
            filas.append({
                "ronda": run.ronda, "run_id": run.run_id, "etapa": etapa,
                "tokens_metadata": "" if declarado is None else declarado,
                "tokens_raw": raw,
                "diferencia": "" if declarado is None else raw - declarado,
                "estado": estado,
            })
        for nombre, envoltorio, suma in _tokens_envoltorio(run.directorio):
            filas.append({
                "ronda": run.ronda, "run_id": run.run_id, "etapa": f"envoltorio:{nombre}",
                "tokens_metadata": envoltorio, "tokens_raw": suma,
                "diferencia": suma - (envoltorio or 0), "estado": "diferencia",
            })
    return filas


MODELO_EMBEDDINGS = "text-embedding-3-large"   # el de config.py, si la metadata no lo dice


def _esperados(run: Run) -> dict[str, str]:
    """Modelo que cada etapa debió pedir según la configuración del run.

    Un run fallido no tiene metadata: el de extracción es el del run, y el juez
    (sin configuración que leer) se espera igual a la extracción.
    """
    meta = run.metadata or {}
    extraccion = str(meta.get("modelo_extraccion") or run.modelo)
    juez = str(meta.get("modelo_juez_matching") or extraccion)
    return {"checklist": extraccion, "e1": extraccion, "e3": extraccion, "e4_juez": juez,
            "e4_redaccion": juez,
            "embeddings": str(meta.get("modelo_embeddings") or MODELO_EMBEDDINGS)}


def _conteo(valores: list[str]) -> str:
    return ";".join(f"{v}:{n}" for v, n in sorted(Counter(valores).items()))


def filas_control_modelo_servido(runs: list[Run]) -> list[dict[str, Any]]:
    """Por ronda × modelo × etapa: el modelo pedido contra el esperado y los servidos.

    Estados (pueden sumarse con «;»): pedido_distinto (una llamada pidió otro
    modelo que el configurado, p. ej. el de respaldo), varios_servidos (la API
    sirvió más de un modelo en la ronda), servido_distinto (lo servido no es lo
    pedido ni su versión con fecha); si no, ok, o sin_dato si ninguna llamada
    guardó el servido (los embeddings de B0-B2).
    """
    grupos: dict[tuple[str, str, str], list[tuple[str, Llamada]]] = {}
    for run in runs:
        esperados = _esperados(run)
        for ll in run.llamadas:
            grupos.setdefault((run.ronda, run.modelo, ll.etapa), []).append(
                (esperados[ll.etapa], ll))
    filas: list[dict[str, Any]] = []
    for (ronda, modelo, etapa), llamadas in grupos.items():
        servidos = [ll.modelo_servido for _, ll in llamadas if ll.modelo_servido]
        pedido_distinto = sum(ll.modelo_pedido != esperado for esperado, ll in llamadas)
        servido_distinto = sum(
            1 for _, ll in llamadas if ll.modelo_servido and ll.modelo_servido != ll.modelo_pedido
            and not ll.modelo_servido.startswith(ll.modelo_pedido + "-"))
        problemas = [nombre for nombre, hay in (
            ("pedido_distinto", pedido_distinto), ("varios_servidos", len(set(servidos)) > 1),
            ("servido_distinto", servido_distinto)) if hay]
        filas.append({
            "ronda": ronda, "modelo": modelo, "etapa": etapa,
            "modelo_esperado": ";".join(sorted({e for e, _ in llamadas})),
            "llamadas": len(llamadas),
            "modelos_pedidos": _conteo([ll.modelo_pedido for _, ll in llamadas]),
            "modelos_servidos": _conteo(servidos),
            "llamadas_sin_servido": len(llamadas) - len(servidos),
            "llamadas_pedido_distinto": pedido_distinto,
            "llamadas_servido_distinto": servido_distinto,
            "estado": ";".join(problemas) or ("ok" if servidos else "sin_dato"),
        })
    return filas


def avisos_modelo_servido(filas: list[dict[str, Any]]) -> list[str]:
    return [f"AVISO modelo servido: {f['ronda']} {f['modelo']} {f['etapa']}: {f['estado']} "
            f"(esperado {f['modelo_esperado']}; pedidos {f['modelos_pedidos']}; servidos "
            f"{f['modelos_servidos'] or '-'})"
            for f in filas if f["estado"] not in ("ok", "sin_dato")]


def reintentos_del_run(llamadas: list[Llamada]) -> dict[str, Any]:
    """Reintentos del SDK y del stream, y códigos HTTP reintentados, sumados en el run.

    Vacío (no 0) si ninguna llamada los registró: los raw de B0-B2 son anteriores.
    No incluye llamadas_juez_reintento de la metadata: esas son re-preguntas de la
    asignación global, no reintentos del SDK.
    """
    def suma(valores: list[int | None]) -> int | str:
        presentes = [v for v in valores if v is not None]
        return sum(presentes) if presentes else ""

    con_codigos = [ll.codigos_http for ll in llamadas if ll.codigos_http is not None]
    codigos = [str(c) for cs in con_codigos for c in cs]
    return {
        "reintentos_sdk": suma([ll.reintentos_sdk for ll in llamadas]),
        "reintentos_stream": suma([ll.reintentos_stream for ll in llamadas]),
        "reintentos_http": len(codigos) if con_codigos else "",
        "codigos_http_reintentados": _conteo(codigos),
    }


def discrepancias_evaluacion(
    rondas: list[Ronda], checklist: list[dict[str, Any]], comparador: list[dict[str, Any]]
) -> list[str]:
    """Conteos recalculados que no reproducen los de evaluacion_B*.json."""
    claves_ck = {
        "evaluados": "evaluados", "aciertos": "aciertos", "no_verificables": "no_verificables",
        "falsos_no_cumple": "falsos_no_cumple", "falsos_cumple": "falsos_cumple",
    }
    por_run_ck = {(f["ronda"], f["run_id"]): f for f in checklist}
    por_run_cmp = {(f["ronda"], f["run_id"]): f for f in comparador}
    problemas: list[str] = []
    for ronda in rondas:
        for _, e in _entradas(ronda):
            clave = (ronda.etiqueta, e["run_id"])
            for campo, columna in claves_ck.items():
                esperado = (e.get("checklist_gt") or {}).get(campo)
                obtenido = por_run_ck[clave].get(columna)
                if esperado is not None and esperado != obtenido:
                    problemas.append(f"{clave} checklist.{campo}: {esperado} ≠ {obtenido}")
            for campo, esperado in (e.get("comparador") or {}).items():
                obtenido = por_run_cmp[clave].get(campo)
                if esperado != obtenido:
                    problemas.append(f"{clave} comparador.{campo}: {esperado} ≠ {obtenido}")
    return problemas


# ------------------------------------------- GT del comparador y repeticiones de E4


@dataclass
class Replay:
    """Una repetición de E4 (comparador.reproducir_e4) en replay_e4/<etiqueta>/<run_id>/."""

    etiqueta: str
    directorio: Path
    metadata: dict[str, Any] | None   # None: no terminó (sus raw igual se pagaron)

    @property
    def run_origen(self) -> str:
        return str((self.metadata or {}).get("run_origen") or self.directorio.name)


def cargar_replays(mediciones: Path) -> list[Replay]:
    replays: list[Replay] = []
    for d in sorted(p for p in mediciones.glob("replay_e4/*/*") if p.is_dir()):
        meta = _leer_json(d / "metadata.json") if (d / "metadata.json").is_file() else None
        if meta is not None and meta.get("modo") != MODO_REPLAY_E4:
            raise ValueError(f"{d}: metadata.json no es de una repetición de E4 "
                             f"(modo {meta.get('modo')!r})")
        replays.append(Replay(d.parent.name, d, meta))
    return replays


def _evaluacion_gt(
    run_dir: Path, hashes: tuple[str, str] | None, gts: list[GtAplicable]
) -> tuple[GtAplicable, EvaluacionComparador] | None:
    """(GT, evaluación) del reporte de ``run_dir`` con el GT de esos sha256;
    None si no hay reporte, ni sha256, ni GT para ellos."""
    if hashes is None or not (run_dir / "reporte_final.json").is_file():
        return None
    gt = gt_aplicable(gts, *hashes)
    if gt is None:
        return None
    reporte = ReporteInforme.model_validate(_leer_json(run_dir / "reporte_final.json"))
    return gt, evaluar(reporte, gt.gt, sha256_informe=hashes[0], sha256_excel=hashes[1],
                       run_id=run_dir.name)


def _resumen_gt(
    run_dir: Path, hashes: tuple[str, str] | None, gts: list[GtAplicable]
) -> tuple[GtAplicable, dict[str, Any]] | None:
    """(GT, resumen de la evaluación), como ``_evaluacion_gt``."""
    evaluado = _evaluacion_gt(run_dir, hashes, gts)
    return None if evaluado is None else (evaluado[0], resumen(evaluado[1]))


_NO_COMPARADAS = frozenset({"run_id", "gt", "sha256_gt"})


def comparar_guardada(
    guardado: dict[str, Any] | None, sha256_guardado: str | None, recalculado: dict[str, Any],
    gt: GtAplicable, donde: str,
) -> tuple[str, list[str]]:
    """(estado, diferencias) de una evaluación guardada frente a la recalculada.

    sin_guardar (ronda anterior a M64), error_al_medir (evaluar_lote guardó el
    error de la evaluación: no hay con qué comparar; main lo avisa), otro_gt (se
    hizo con otro archivo del GT: no hay con qué comparar), igual o distinta (con
    el mismo GT debe dar lo mismo; cada campo distinto es una discrepancia).
    """
    if not guardado:
        return "sin_guardar", []
    if "error" in guardado:
        return "error_al_medir", []
    if sha256_guardado != gt.sha256:
        return "otro_gt", []
    problemas = [f"{donde}.{c}: {guardado.get(c)} ≠ {recalculado.get(c)}"
                 for c in sorted((set(guardado) | set(recalculado)) - _NO_COMPARADAS)
                 if guardado.get(c) != recalculado.get(c)]
    return ("distinta" if problemas else "igual"), problemas


@dataclass
class ReplayEvaluado:
    replay: Replay
    origen: Run | None
    gt: GtAplicable | None = None
    original: dict[str, Any] | None = None   # resumen del reporte del run de origen
    repetido: dict[str, Any] | None = None   # resumen del reporte de la repetición
    hashes: tuple[str, str] | None = None    # sha256 del informe y del Excel


def _origen(replay: Replay, runs: list[Run]) -> Run | None:
    candidatos = [r for r in runs if r.run_id == replay.run_origen]
    if len(candidatos) > 1:
        raise ValueError(f"{replay.directorio}: el run de origen {replay.run_origen} está en "
                         f"varias rondas ({[r.ronda for r in candidatos]})")
    return candidatos[0] if candidatos else None


def evaluar_replays(
    replays: list[Replay], runs: list[Run], gts: list[GtAplicable]
) -> list[ReplayEvaluado]:
    """Cada repetición y su run de origen evaluados contra el GT de su informe.

    Los sha256 son los que copió la repetición o, si no los trae, los del run
    de origen (los insumos son los mismos)."""
    evaluados: list[ReplayEvaluado] = []
    for rep in replays:
        origen = _origen(rep, runs)
        hashes = hashes_del_run(rep.directorio) or (
            hashes_del_run(origen.directorio) if origen else None)
        repetido = _resumen_gt(rep.directorio, hashes, gts)
        original = _resumen_gt(origen.directorio, hashes, gts) if origen else None
        con_gt = [x for x in (repetido, original) if x is not None]   # el mismo GT
        evaluados.append(ReplayEvaluado(
            rep, origen, gt=con_gt[0][0] if con_gt else None,
            original=original[1] if original else None,
            repetido=repetido[1] if repetido else None, hashes=hashes))
    return evaluados


def _fila_gt(base: dict[str, Any], gt: GtAplicable, r: dict[str, Any],
             guardada: str) -> dict[str, Any]:
    return {
        **base, "sha256_gt": gt.sha256[:16],
        **{c: r[c] for c in COLUMNAS_GT_CIFRAS},
        "motivos_sin_adjudicar": ";".join(
            f"{motivo}:{n}" for motivo, n in r["motivos_sin_adjudicar"].items()),
        "a_perdidos": len(r["a_perdidos"]),
        "posibles_escondidos": len(r["posibles_escondidos"]),
        "errores_excel": _errores_excel(r),
        "evaluacion_guardada": guardada,
        "estados_sin_adjudicar": ";".join(
            f"{estado}:{n}" for estado, n in r["estados_sin_adjudicar"].items()),
    }


def _errores_excel(r: dict[str, Any]) -> str:
    return ";".join(f"{e['id']}:{e['estado']}" for e in r["errores_excel"])


def filas_comparador_gt(
    rondas: list[Ronda], replays: list[ReplayEvaluado], gts: list[GtAplicable]
) -> tuple[list[dict[str, Any]], list[str]]:
    """(filas, discrepancias): cada run de las evaluaciones y cada repetición de
    E4 con GT, recalculados y comparados con lo guardado (``comparar_guardada``).

    Como ``comparador_por_informe.csv``, los runs son los de cada evaluación
    (no los de un lote abortado); un run solo checklist o fallido no tiene
    comparador que evaluar.
    """
    filas: list[dict[str, Any]] = []
    problemas: list[str] = []
    for ronda in rondas:
        for modelo, e in _entradas(ronda):
            if e.get("modo") == MODO_SOLO_CHECKLIST or "error" in e:
                continue
            run_dir = ronda.directorio / "runs" / e["run_id"]
            evaluado = _resumen_gt(run_dir, hashes_del_run(run_dir), gts)
            if evaluado is None:
                continue
            gt, recalculado = evaluado
            guardado = e.get("comparador_gt")
            guardada, dif = comparar_guardada(
                guardado, (guardado or {}).get("sha256_gt"), recalculado, gt,
                f"{(ronda.etiqueta, e['run_id'])} comparador_gt")
            problemas += dif
            filas.append(_fila_gt({
                "tipo": "ronda", **_base(ronda, modelo, e)}, gt, recalculado, guardada))
    for ev in replays:
        if ev.gt is None or ev.repetido is None:
            continue
        rep = ev.replay
        guardado = (rep.metadata or {}).get("comparador_gt") or {}
        donde = f"replay_e4/{rep.etiqueta}/{rep.directorio.name} comparador_gt"
        guardada, dif = comparar_guardada(guardado.get("replay"), guardado.get("sha256_gt"),
                                          ev.repetido, ev.gt, f"{donde}.replay")
        if ev.original is not None:
            dif += comparar_guardada(guardado.get("original"), guardado.get("sha256_gt"),
                                     ev.original, ev.gt, f"{donde}.original")[1]
        problemas += dif
        filas.append(_fila_gt({
            "tipo": "replay_e4", "ronda": rep.etiqueta,
            "modelo": (rep.metadata or {}).get("modelo_extraccion", ""),
            "informe": nombre_corto(ev.gt.gt.informe), "run_id": rep.directorio.name,
        }, ev.gt, ev.repetido, guardada))
    return filas, problemas


CONTEO_REPLAY = ("coinciden", "difieren", "faltan_en_excel", "extra_en_excel",
                 "requieren_revision", "coinciden_con_redaccion_distinta")
GT_REPLAY = ("A", "D", "sin_adjudicar", "precision_alertas", "a_perdidos",
             "posibles_escondidos", "errores_excel")


def _cifras_gt_replay(r: dict[str, Any] | None, lado: str) -> dict[str, Any]:
    if r is None:
        return {}
    valores = {
        "A": r["A"], "D": r["D"], "sin_adjudicar": r["sin_adjudicar"],
        "precision_alertas": r["precision_alertas"], "a_perdidos": len(r["a_perdidos"]),
        "posibles_escondidos": len(r["posibles_escondidos"]),
        "errores_excel": _errores_excel(r),
    }
    return {f"{c}_{lado}": valores[c] for c in GT_REPLAY}


INTERRUPTORES_E4_REPLAY = ("descripcion_identica", "control_codigos", "unificar_copias",
                           "juez_justifica_primero")


def filas_replay_e4(
    replays: list[ReplayEvaluado], precios: dict[str, PrecioModelo]
) -> list[dict[str, Any]]:
    """Una fila por repetición de E4, también las que no terminaron (su costo
    es una cota inferior). Llamadas desde caché: raw con ``desde_cache``."""
    filas: list[dict[str, Any]] = []
    for ev in replays:
        rep, origen = ev.replay, ev.origen
        meta = rep.metadata or {}
        llamadas = llamadas_del_run(rep.directorio)
        total = Agregado()
        for agg in costo_por_etapa(llamadas, precios).values():
            total.sumar(agg)
        fila: dict[str, Any] = {
            "etiqueta": rep.etiqueta, "run_origen": rep.run_origen,
            "ronda_origen": origen.ronda if origen else "",
            "informe": origen.informe if origen else "",
            "estado": "completo" if rep.metadata is not None else "incompleto",
            "modelo_extraccion": meta.get("modelo_extraccion") or "",
            "modelo_juez_matching": meta.get("modelo_juez_matching") or "",
            "modelo_embeddings": meta.get("modelo_embeddings") or "",
            "asignacion_global": meta.get("asignacion_global", ""),
            "juez_redaccion": meta.get("juez_redaccion", ""),
            "llamadas": len(llamadas),
            "llamadas_pagadas": sum(not ll.desde_cache for ll in llamadas),
            "llamadas_desde_cache": sum(ll.desde_cache for ll in llamadas),
            "llamadas_fallidas": sum(ll.fallida for ll in llamadas),
            "llamadas_juez_reintento": meta.get("llamadas_juez_reintento", ""),
            "costo_usd": round(total.costo_usd, 6),
            "costo_es_cota_inferior": rep.metadata is None,
            "sha256_gt": ev.gt.sha256[:16] if ev.gt else "",
            **_cifras_gt_replay(ev.original, "original"),
            **_cifras_gt_replay(ev.repetido, "replay"),
            # Interruptores de E4 posteriores a AG1 (vacío: la repetición es anterior).
            **{k: meta.get(k, "") for k in INTERRUPTORES_E4_REPLAY},
        }
        for k in CONTEO_REPLAY:
            fila[f"{k}_original"] = (meta.get("conteo_original") or {}).get(k, "")
            fila[f"{k}_replay"] = (meta.get("conteo_replay") or {}).get(k, "")
        filas.append(fila)
    return filas


# ------------------------------------------------------- adjudicación (F3)


CLASES_ADJUDICACION = adjudicacion.CLASES
clase_final = adjudicacion.clase_final


def filas_adjudicacion(mediciones: Path) -> list[dict[str, Any]]:
    """Conteos por informe de la adjudicación del comparador (mediciones/adjudicacion).

    Cada ítem se alinea con su resultado y con la Etapa 3 de su run
    (comparador.adjudicacion: paño, relé, estado, página y fila; si algo no
    corresponde, ValueError). Alertas = resultados que no son coincide ni
    transversal. Precisión de las alertas = A / (A + D). Los ítems con
    ``duplica_idx`` (el mismo par desdoblado en dos paños) se cuentan también
    sin duplicar.
    """
    filas: list[dict[str, Any]] = []
    for ruta in sorted((mediciones / "adjudicacion").glob("*.json")):
        adj = adjudicacion.cargar_alineada(mediciones, ruta).adjudicacion
        conteo = {c: 0 for c in CLASES_ADJUDICACION}
        sin_dup = {c: 0 for c in CLASES_ADJUDICACION}
        alertas = 0
        for item in adj.items:
            conteo[item.clase] += 1
            if item.duplica_idx is None:
                sin_dup[item.clase] += 1
            if item.estado.value not in ("coincide", "transversal"):
                alertas += 1
        a, d = conteo["A"], conteo["D"]
        filas.append({
            "ronda": adj.ronda, "modelo": adj.modelo, "informe": nombre_corto(adj.informe),
            "run_id": adj.run_id, "items_revisados": len(adj.items),
            "alertas": alertas, **conteo,
            "precision_alertas": round(a / (a + d), 4) if a + d else "",
            "A_sin_duplicados": sin_dup["A"], "D_sin_duplicados": sin_dup["D"],
            "verificado_por_segundo_agente": bool(
                adj.cabecera.get("verificado_por_segundo_agente")),
        })
    return filas


_ORDEN_CAMPOS = ("descripcion", "accion_correctiva", "calificacion")


def origen_diferencia(diferencia: dict[str, Any], par_dudoso: bool) -> str:
    """De qué paso de E4 sale una diferencia de un par emparejado (etapa4_matching 4c/4e).

    polaridad: veto determinista Cumple/No cumple. codigo_distinto: sobre el umbral,
    un código o número sustituido (control de códigos, M28 V2). calificacion:
    igualdad de enum.
    copia_unificada: 4f (M34) la igualó con su copia del mismo origen.
    juez_redaccion: bajo el umbral, el juez concluyó que el contenido difiere.
    sin_juez_par_dudoso: bajo el umbral en un par de emparejamiento dudoso
    (`par_dudoso`: MatchResult.emparejamiento_es_dudoso), que por la regla 19e(c)
    no pasa por el juez de redacción: un par semantico_bajo o, con la asignación
    global, el que lleva emparejamiento_dudoso (PD71). sin_juez_otro: cualquier
    otro caso.
    """
    detalle = str(diferencia.get("detalle") or "")
    if detalle.startswith("Polaridad opuesta"):
        return "polaridad"
    if detalle.startswith("Código o número distinto"):
        return "codigo_distinto"
    if diferencia.get("campo") == "calificacion":
        return "calificacion"
    if MARCA_COPIA in detalle:
        return "copia_unificada"
    if "juez de redacción concluyó" in detalle:
        return "juez_redaccion"
    if par_dudoso:
        return "sin_juez_par_dudoso"
    return "sin_juez_otro"


def filas_alertas_por_campo(mediciones: Path) -> list[dict[str, Any]]:
    """Ítems adjudicados con diferencias o equivalencias, por campo, origen y clase.

    Descriptivo (pre-adjudicación, sin validar por el equipo revisor): cruza cada
    ítem de mediciones/adjudicacion con su resultado en reporte_final.json,
    alineado con comparador.adjudicacion. Solo los pares emparejados tienen
    campos (difiere, o coincide con redacción distinta); las faltas y los
    extras no entran. Conteos con y sin duplicados.
    """
    conteo: Counter[tuple[str, ...]] = Counter()
    sin_dup: Counter[tuple[str, ...]] = Counter()
    for ruta in sorted((mediciones / "adjudicacion").glob("*.json")):
        alineada = adjudicacion.cargar_alineada(mediciones, ruta)
        adj = alineada.adjudicacion
        for item in adj.items:
            r = alineada.resultados[item.idx]
            tipo_match = r.tipo_match.value
            if r.diferencias:
                tipo, pares = "diferencia", [
                    (d.campo.value, origen_diferencia(d.model_dump(mode="json"),
                                                      r.emparejamiento_es_dudoso))
                    for d in r.diferencias]
            elif r.equivalencias_redaccion:
                tipo, pares = "equivalencia", [(e.campo.value, "juez_redaccion")
                                               for e in r.equivalencias_redaccion]
            else:
                continue
            pares.sort(key=lambda par: _ORDEN_CAMPOS.index(par[0]))
            clave = (
                adj.ronda, adj.modelo, nombre_corto(adj.informe), r.estado.value, tipo_match,
                tipo, "+".join(c for c, _ in pares), "+".join(o for _, o in pares),
                item.clase, item.subclase,
            )
            conteo[clave] += 1
            if item.duplica_idx is None:
                sin_dup[clave] += 1
    campos = ("ronda", "modelo", "informe", "estado", "tipo_match", "tipo", "campos", "origen",
              "clase", "subclase")
    return [{**dict(zip(campos, clave, strict=True)), "n": n, "n_sin_duplicados": sin_dup[clave]}
            for clave, n in sorted(conteo.items())]


# ------------------------------------------ confianza del juez de E4 (M54, PD20)

# Bandas de los pares del juez con los cortes de E4 (0,5 acepta, 0,8 separa
# semantico_bajo de semantico_alto), más las de unicidad y sin pareja, las
# transversales (no entran a E4, 19b) y los rechazos del juez (solo en el raw),
# aparte y sin cruce con el GT.
BANDAS_PARES = ("50-64", "65-79", "80-89", "90-100")
# Los pares sin juez (unicidad y, con M30, descripción idéntica) tienen su banda.
BANDAS_JUEZ = ("unicidad", "descripcion_identica", *BANDAS_PARES, "sin_match", "transversal",
               "rechazo_conf_baja", "rechazo_seguro")
# Columnas del cruce con el GT (evaluar_comparador): las clases adjudicadas y
# los demás veredictos de un resultado del comparador.
COLUMNAS_GT_JUEZ = (*CLASES_ADJUDICACION, "ok_texto_identico", "sin_adjudicar",
                    "fuera_de_universo")
_CORTES_BANDAS = ((0.65, "50-64"), (0.8, "65-79"), (0.9, "80-89"))


def banda_confianza(r: dict[str, Any]) -> str:
    """Banda de un resultado del reporte. Compara el float tal cual (0,795 no es
    «80+»), y un tipo que contradice su confianza (los cortes de E4) es ValueError.
    Las transversales (por estado) van aparte: no pasan por E4."""
    if r.get("estado") == "transversal":
        return "transversal"
    tipo = r["tipo_match"]
    if tipo in ("unicidad", "descripcion_identica", "sin_match"):
        return str(tipo)
    confianza = float(r["confianza"])
    alto = confianza >= 0.8
    if confianza < 0.5 or tipo not in ("semantico_alto", "semantico_bajo") or alto != (
            tipo == "semantico_alto"):
        raise ValueError(f"{tipo} con confianza {confianza}: no son los cortes de E4")
    return next((b for corte, b in _CORTES_BANDAS if confianza < corte), "90-100")


def rechazo_del_juez(respuesta: dict[str, Any]) -> str | None:
    """None si el juez eligió candidato con confianza ≥ 50 (E4 forma el par). Si no,
    rechazo_seguro (no eligió ninguno, con confianza ≥ 80) o rechazo_conf_baja
    (no eligió con confianza < 80, o eligió con confianza < 50)."""
    confianza = int(respuesta["confianza"])
    if respuesta["indice_candidato"] is not None and confianza >= 50:
        return None
    if respuesta["indice_candidato"] is None and confianza >= 80:
        return "rechazo_seguro"
    return "rechazo_conf_baja"


def _respuestas_juez(run_dir: Path) -> list[dict[str, Any]]:
    """Las respuestas válidas del juez de matching (sin las llamadas fallidas)."""
    respuestas = []
    for raw in sorted((run_dir / "etapa4_llm_judge_raw").glob("judge_*.json")):
        meta = _leer_json(raw)
        if meta.get("llamada_fallida"):
            continue
        respuesta = meta.get("response_raw")
        if not isinstance(respuesta, dict) or not {"indice_candidato", "confianza"} <= set(
                respuesta):
            raise ValueError(f"{raw}: respuesta del juez sin indice_candidato y confianza")
        respuestas.append(respuesta)
    return respuestas


def _columnas_gt(evaluado: tuple[GtAplicable, EvaluacionComparador] | None
                 ) -> list[str] | None:
    """Columna del cruce con el GT de cada resultado del reporte (su clase o su
    veredicto); None sin GT. La clase sale del GT por clave estable, como en
    comparador_gt_por_run.csv: los adjudicacion/*.json de B3, AG1 y AG2 son
    complementos del GT y no cubren el resto de sus resultados."""
    if evaluado is None:
        return None
    return [str(r.clase) if r.veredicto == Veredicto.ADJUDICADO else str(r.veredicto)
            for r in evaluado[1].resultados]


def _filas_juez_run(run_dir: Path, columnas: list[str] | None,
                    base: dict[str, Any]) -> list[dict[str, Any]]:
    resultados = _leer_json(run_dir / "reporte_final.json")["resultados"]
    vacias = {c: "" if columnas is None else 0 for c in COLUMNAS_GT_JUEZ}
    por_banda: dict[str, dict[str, Any]] = {
        b: {**base, "banda": b, "n": 0, "dudosos": 0, **vacias} for b in BANDAS_JUEZ}
    for idx, r in enumerate(resultados):
        banda = banda_confianza(r)
        fila = por_banda[banda]
        fila["n"] += 1
        # MatchResult.emparejamiento_es_dudoso: semantico_bajo o emparejamiento_dudoso (PD71).
        fila["dudosos"] += (r["tipo_match"] == "semantico_bajo"
                            or r.get("emparejamiento_dudoso") is not None)
        if columnas is not None and banda != "transversal":
            fila[columnas[idx]] += 1
    por_banda["transversal"] |= dict.fromkeys(COLUMNAS_GT_JUEZ, "")
    for b in ("rechazo_conf_baja", "rechazo_seguro"):
        por_banda[b] |= {c: "" for c in ("dudosos", *COLUMNAS_GT_JUEZ)}
    for respuesta in _respuestas_juez(run_dir):
        rechazo = rechazo_del_juez(respuesta)
        if rechazo is not None:
            por_banda[rechazo]["n"] += 1
    return list(por_banda.values())


def filas_confianza_juez(
    rondas: list[Ronda], replays: list[ReplayEvaluado], gts: list[GtAplicable]
) -> list[dict[str, Any]]:
    """comparador_confianza_juez.csv (M54): por run con comparador de cada ronda y
    por repetición de E4 terminada, los resultados del reporte por banda de
    confianza (con los emparejamientos dudosos y, si hay GT de su informe y
    Excel, la clase o el veredicto de cada uno contra el GT) y los rechazos del
    juez. Sin GT, las columnas del GT quedan vacías. Sin texto."""
    filas: list[dict[str, Any]] = []
    for ronda in rondas:
        for modelo, e in _entradas(ronda):
            if "error" in e or e.get("modo") == MODO_SOLO_CHECKLIST:
                continue
            run_dir = ronda.directorio / "runs" / e["run_id"]
            meta = _leer_json(run_dir / "metadata.json")
            filas.extend(_filas_juez_run(
                run_dir, _columnas_gt(_evaluacion_gt(run_dir, hashes_del_run(run_dir), gts)),
                {"fuente": "ronda", "etiqueta": ronda.etiqueta, "modelo": modelo,
                 "informe": nombre_corto(e["informe"]),
                 "auditora": meta.get("empresa_auditora", ""), "run_id": e["run_id"],
                 # B0-B2 son anteriores al interruptor: corrieron sin asignación global.
                 "asignacion_global": bool(meta.get("asignacion_global", False))}))
    for ev in replays:
        rep, origen = ev.replay, ev.origen
        if rep.metadata is None or origen is None:
            continue
        filas.extend(_filas_juez_run(
            rep.directorio, _columnas_gt(_evaluacion_gt(rep.directorio, ev.hashes, gts)),
            {"fuente": "replay", "etiqueta": rep.etiqueta, "modelo": origen.modelo,
             "informe": origen.informe,
             "auditora": (origen.metadata or {}).get("empresa_auditora", ""),
             "run_id": rep.run_origen,
             "asignacion_global": bool(rep.metadata.get("asignacion_global", False))}))
    return filas


# --------------------------------------------------------------- escritura


COLUMNAS: dict[str, list[str]] = {
    "sensibilidad_m43.csv": list(sensibilidad.COLUMNAS_CSV),
    "sensibilidad_m43c.csv": list(sensibilidad_checklist.COLUMNAS_CSV),
    "checklist_por_informe.csv": [
        "ronda", "modelo", "informe", "run_id", "estado", "evaluados", "aciertos",
        "no_verificables", "falsos_no_cumple", "falsos_cumple", "incumplimientos_gt",
        "incumplimientos_detectados", "puntos_falso_cumple", "puntos_sin_gt", "muestra",
    ],
    "checklist_por_punto.csv": [
        "ronda", "modelo", "informe", "run_id", "punto", "codigo_gt", "veredicto_gt",
        "resultado", "clasificacion", "muestra",
    ],
    "comparador_por_informe.csv": [
        "ronda", "modelo", "informe", "run_id", "estado", "total", "coinciden", "difieren",
        "faltan_en_excel", "extra_en_excel", "transversales", "requieren_revision",
        "coinciden_con_redaccion_distinta",
    ],
    "costo_por_informe_etapa.csv": [
        "ronda", "modelo", "informe", "run_id", "en_evaluacion", "estado_run", "etapa",
        "llamadas", "llamadas_tramo_alto", "llamadas_fallidas", "tokens_input", "tokens_cache",
        "tokens_output", "costo_usd",
    ],
    "costo_por_informe.csv": [
        "ronda", "modelo", "informe", "run_id", "en_evaluacion", "estado_run", "error_tipo",
        "costo_es_cota_inferior", "llamadas", "llamadas_tramo_alto", "llamadas_fallidas",
        "tokens_input", "tokens_cache", "tokens_output", "costo_usd",
        "reintentos_sdk", "reintentos_stream", "reintentos_http", "codigos_http_reintentados",
    ],
    "costo_campana.csv": [
        "ronda", "modelo", "runs", "runs_completos", "runs_error", "runs_interrumpidos",
        "runs_en_evaluacion", "llamadas", "llamadas_tramo_alto", "llamadas_fallidas",
        "tokens_input", "tokens_cache", "tokens_output", "costo_usd", "costo_usd_runs_evaluados",
        "costo_usd_fuera_de_evaluacion",
    ],
    "tiempo_por_informe.csv": [
        "ronda", "modelo", "informe", "run_id", "en_evaluacion", "duracion_segundos",
        "runs_solapados", "t_checklist", "t_e1", "t_e3", "t_e3_pano_mas_lento", "t_e4",
        "camino_critico_estimado", "t_e2", "t_e5", "camino_critico_relojes", "fuente_tiempo",
        "modo", "t_checklist_llamadas", "t_e1_llamadas", "t_e3_llamadas", "t_e4_llamadas",
    ],
    "tamano_informes.csv": [
        "informe", "auditora", "formato_original", "mb_original", "paginas_pdf_visto",
        "mb_pdf_visto", "tokens_input_checklist_b2_sonnet", "tramos_checklist",
        "paginas_leidas_e1", "panos_e1", "filas_excel_normalizadas",
        "filas_excel_transversales", "tiene_checklist_gt", "imagenes_omitidas_docx",
    ],
    "control_tokens.csv": [
        "ronda", "run_id", "etapa", "tokens_metadata", "tokens_raw", "diferencia", "estado",
    ],
    "control_modelo_servido.csv": [
        "ronda", "modelo", "etapa", "modelo_esperado", "llamadas", "modelos_pedidos",
        "modelos_servidos", "llamadas_sin_servido", "llamadas_pedido_distinto",
        "llamadas_servido_distinto", "estado",
    ],
    "citas_por_informe.csv": [
        "ronda", "modelo", "informe", "run_id", "modo", "ambito", "estado", "n",
    ],
    "citas_checklist.csv": [
        "escenario", "ronda", "modelo", "informe", "run_id", "modo", "cita_checklist",
        "bajados_sin_cita_verificada", "puntos_bajados", *BAJADAS_CONTRA_PLANILLA,
    ],
    "checklist_un_tramo.csv": [
        "escenario", "ronda", "modelo", "informe", "run_id", "fuente", "modo_aplicado",
        "tramos", "evaluados", "vistos_en_una_parte", "puntos_vistos",
        "vistos_que_eran_falso_cumple", "vistos_que_eran_acierto", "en_lista", "puntos_en_lista",
        "en_lista_que_eran_falso_cumple", "en_lista_que_eran_acierto", "en_lista_sin_planilla",
        "aciertos_marcando", "aciertos_bajando",
    ],
    "confianza_checklist.csv": [
        "escenario", "ronda", "modelo", "informes", "evaluados", "aciertos", "pct_aciertos",
        "wilson95_inf", "wilson95_sup", "bootstrap95_inf", "bootstrap95_sup",
        "peor_informe_pct", "mejor_informe_pct", "no_verificables", "falsos_no_cumple",
        "falsos_cumple", "veredictos_no_gt", "incumplimientos_detectados",
        "tasa_falso_cumple_sobre_no",
        # M42: matriz 2×3 (planilla × sistema), TNR, TPR y falso cumple sobre los NO.
        *conf.CELDAS_MATRIZ, "veredictos_si_gt", "pct_tnr", "pct_tpr", "tpr_wilson95_inf",
        "tpr_wilson95_sup", "falso_cumple_wilson95_inf", "falso_cumple_wilson95_sup",
        "falso_cumple_cota_regla_de_tres", "muestra",
    ],
    "falsos_cumple.csv": [
        "ronda", "modelo", "informe", "punto", "codigo_gt", "causa", "referencia",
    ],
    "checklist_errores_clasificados.csv": [
        "escenario", "ronda", "modelo", "informe", "run_id", "punto", "codigo_gt", "grupo",
        "clasificacion", "clase_m09", "pregunta_abierta", "pagina_evidencia", "paginas_pdf",
        "tercio", "tramo", "vocabulario", "verificado",
    ],
    "estabilidad_checklist.csv": [
        "de", "a", "modelo", "puntos_con_prompt_sin_cambio", "system_prompt_checklist_igual",
        "comparaciones", "mismo_resultado", "pct_mismo_resultado",
    ],
    "ficha_version.csv": [
        "version", "fecha", "modelos", "sha256_codigo", "archivos",
        "archivos_distintos_del_actual", "distintos", "src",
        "sha256_codigo_runs", "sha256_codigo_congelado", "version_runs",
    ],
    "comparador_adjudicado.csv": [
        "ronda", "modelo", "informe", "run_id", "items_revisados", "alertas",
        *CLASES_ADJUDICACION, "precision_alertas", "A_sin_duplicados", "D_sin_duplicados",
        "verificado_por_segundo_agente",
    ],
    "comparador_alertas_por_campo.csv": [
        "ronda", "modelo", "informe", "estado", "tipo_match", "tipo", "campos", "origen",
        "clase", "subclase", "n", "n_sin_duplicados",
    ],
    "comparador_confianza_juez.csv": [
        "fuente", "etiqueta", "modelo", "informe", "auditora", "run_id", "asignacion_global",
        "banda", "n", "dudosos", *COLUMNAS_GT_JUEZ,
    ],
    "comparador_gt_por_run.csv": [
        "tipo", "ronda", "modelo", "informe", "run_id", "sha256_gt", *COLUMNAS_GT_CIFRAS,
        "motivos_sin_adjudicar", "a_perdidos", "posibles_escondidos", "errores_excel",
        "evaluacion_guardada", "estados_sin_adjudicar",
    ],
    "replay_e4.csv": [
        "etiqueta", "run_origen", "ronda_origen", "informe", "estado", "modelo_extraccion",
        "modelo_juez_matching", "modelo_embeddings", "asignacion_global", "juez_redaccion",
        "llamadas", "llamadas_pagadas", "llamadas_desde_cache", "llamadas_fallidas",
        "llamadas_juez_reintento", "costo_usd", "costo_es_cota_inferior",
        *(f"{k}_{lado}" for k in CONTEO_REPLAY for lado in ("original", "replay")),
        "sha256_gt",
        *(f"{k}_{lado}" for k in GT_REPLAY for lado in ("original", "replay")),
        *INTERRUPTORES_E4_REPLAY,
    ],
    "extraccion_por_campo.csv": metricas_extraccion.COLUMNAS_POR_CAMPO,
    "extraccion_por_tupla.csv": metricas_extraccion.COLUMNAS_POR_TUPLA,
}


def escribir_csv(ruta: Path, columnas: list[str], filas: list[dict[str, Any]]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="") as f:
        # Columna que falta en la fila → vacía; clave de la fila que no es
        # columna (p. ej. un nombre mal escrito) → ValueError, no se descarta.
        w = csv.DictWriter(
            f, fieldnames=columnas, restval="", lineterminator="\n", extrasaction="raise"
        )
        w.writeheader()
        w.writerows(filas)


@dataclass
class Resultado:
    tablas: dict[str, list[dict[str, Any]]]
    discrepancias: list[str]


def filas_sensibilidad(mediciones: Path) -> list[dict[str, Any]]:
    """M43 (comparador.sensibilidad): con el catálogo, el control y las pasadas de
    mediciones/m43, la sensibilidad por tipo × informe × pasada, sin API. Sin M43,
    vacío (el CSV queda con su cabecera)."""
    m43 = mediciones / "m43"
    pasadas = sorted(p for p in m43.glob("pasada*") if p.is_dir())
    if not ((m43 / "catalogo.json").is_file() and (m43 / "control").is_dir() and pasadas):
        return []
    catalogo = sensibilidad.cargar_catalogo(m43 / "catalogo.json")
    return sensibilidad.filas_csv(sensibilidad.evaluar(catalogo.errores, m43 / "control", pasadas))


def generar(mediciones: Path, ruta_precios: Path, salida: Path) -> Resultado:
    """Calcula todas las tablas y escribe un CSV por tabla en ``salida``."""
    precios = cargar_precios(ruta_precios)
    rondas = cargar_rondas(mediciones)
    inventario = _inventario(mediciones)
    runs = cargar_runs(rondas, inventario, set(precios))
    ck_informe, ck_punto = filas_checklist(rondas, cargar_fichas_mediciones(mediciones))
    comparador = filas_comparador(rondas)
    citas_largo, citas_checklist, discrepancias_citas = filas_citas(rondas)
    un_tramo, discrepancias_un_tramo = filas_un_tramo(rondas)
    errores_checklist, discrepancias_m09 = filas_errores_checklist(mediciones, ck_punto)
    costo_etapa, costo_informe, campana = filas_costo(runs, precios)
    gts = gts_de(mediciones / "gt" / "comparador")
    replays = evaluar_replays(cargar_replays(mediciones), runs, gts)
    comparador_gt, discrepancias_gt = filas_comparador_gt(rondas, replays, gts)
    extraccion_campo, extraccion_tupla = metricas_extraccion.filas(
        metricas_extraccion.medir_casos(casos_extraccion(rondas), gts, mediciones=mediciones))
    ficha_version = conf.filas_ficha_version(
        mediciones,
        [(r.etiqueta, str(r.evaluacion.get("fecha", ""))[:16],
          list(r.evaluacion.get("modelos", [])), r.directorio) for r in rondas],
        RAIZ / "src",
        {r.etiqueta: codigo_registrado(r) for r in rondas},
    )
    # Runs (o copia congelada) de otro código que el de la copia src/ de su ronda: la
    # ficha atribuiría sus cifras a un código que no las produjo.
    discrepancias_version = [
        f"ficha_version {f['version']}: el código registrado (runs: "
        f"{f['sha256_codigo_runs'] or '-'}; copia congelada: "
        f"{f['sha256_codigo_congelado'] or '-'}) no es el de {f['src']} ({f['sha256_codigo']})"
        for f in ficha_version if f.get("version_runs") == "distinta"]
    tablas = {
        "checklist_por_informe.csv": ck_informe,
        "checklist_por_punto.csv": ck_punto,
        "comparador_por_informe.csv": comparador,
        "citas_por_informe.csv": citas_largo,
        "citas_checklist.csv": citas_checklist,
        "checklist_un_tramo.csv": un_tramo,
        "costo_por_informe_etapa.csv": costo_etapa,
        "costo_por_informe.csv": costo_informe,
        "costo_campana.csv": campana,
        "tiempo_por_informe.csv": filas_tiempo(runs),
        "tamano_informes.csv": filas_tamano(mediciones, inventario),
        "control_tokens.csv": filas_control(runs),
        "control_modelo_servido.csv": filas_control_modelo_servido(runs),
        "comparador_adjudicado.csv": filas_adjudicacion(mediciones),
        "comparador_alertas_por_campo.csv": filas_alertas_por_campo(mediciones),
        "comparador_confianza_juez.csv": filas_confianza_juez(rondas, replays, gts),
        "comparador_gt_por_run.csv": comparador_gt,
        "replay_e4.csv": filas_replay_e4(replays, precios),
        "sensibilidad_m43.csv": filas_sensibilidad(mediciones),
        # M43c (la parte del checklist): vacío hasta que corra.
        "sensibilidad_m43c.csv": sensibilidad_checklist.filas_desde_mediciones(mediciones),
        "extraccion_por_campo.csv": extraccion_campo,
        "extraccion_por_tupla.csv": extraccion_tupla,
        "confianza_checklist.csv": conf.filas_confianza_checklist(ck_punto),
        "falsos_cumple.csv": conf.filas_falsos_cumple(ck_punto),
        "checklist_errores_clasificados.csv": errores_checklist,
        "ficha_version.csv": ficha_version,
    }
    # Sin las copias del código de B1 y B2 no hay con qué comparar prompts:
    # el CSV queda solo con la cabecera (no se omite).
    tablas["estabilidad_checklist.csv"] = []
    etiquetas = {r.etiqueta for r in rondas}
    if {"B1", "B2"} <= etiquetas and all(
        (mediciones / e.lower() / "src").is_dir() for e in ("B1", "B2")
    ):
        tablas["estabilidad_checklist.csv"] = conf.filas_estabilidad_checklist(
            mediciones, ck_punto
        )
    for nombre, filas in tablas.items():
        escribir_csv(salida / nombre, COLUMNAS[nombre], filas)
    return Resultado(tablas, discrepancias_evaluacion(rondas, ck_informe, comparador)
                     + discrepancias_gt + discrepancias_citas + discrepancias_un_tramo
                     + discrepancias_version + discrepancias_m09)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--mediciones", type=Path, default=RAIZ / "mediciones")
    p.add_argument("--precios", type=Path, default=RAIZ / "docs" / "metricas" / "precios.yaml")
    p.add_argument("--salida", type=Path, default=RAIZ / "docs" / "metricas" / "datos")
    a = p.parse_args()

    res = generar(a.mediciones, a.precios, a.salida)
    for nombre, filas in res.tablas.items():
        print(f"{a.salida / nombre}: {len(filas)} filas")
    print("\nCosto de la campaña (USD):")
    for c in res.tablas["costo_campana.csv"]:
        print(f"  {c['ronda']} {c['modelo']:20s} runs={c['runs']:2d} "
              f"total={c['costo_usd']:9.4f} evaluados={c['costo_usd_runs_evaluados']:9.4f}")
    control = Counter(f["estado"] for f in res.tablas["control_tokens.csv"])
    print(f"\nControl de tokens (raw vs metadata): {dict(control)}")
    for aviso in avisos_modelo_servido(res.tablas["control_modelo_servido.csv"]):
        print(aviso)
    for f in res.tablas["ficha_version.csv"]:
        if f["src"] == "falta":
            print(f"AVISO: la ronda {f['version']} no trae su copia de src/: su versión del "
                  "código no se puede atribuir")
    sin_registro = [f["version"] for f in res.tablas["ficha_version.csv"]
                    if f.get("version_runs") == "sin_registro"]
    if sin_registro:
        print(f"AVISO: {', '.join(sin_registro)} no registran la versión del código de sus runs "
              "(anteriores a version_codigo): su src/ no se contrasta con ellos")
    for f in res.tablas["replay_e4.csv"]:
        if f["estado"] == "incompleto":
            print(f"AVISO: replay_e4/{f['etiqueta']}/{f['run_origen']} no terminó (sin "
                  f"metadata.json): llamadas pagadas {f['llamadas_pagadas']}, costo como cota "
                  "inferior; rehacerla en una carpeta nueva (el golden de los errores no "
                  "mostrados falla mientras siga)")
    for f in res.tablas["comparador_gt_por_run.csv"]:
        if f["evaluacion_guardada"] == "error_al_medir":
            print(f"AVISO: {f['ronda']} {f['run_id']}: la evaluación contra el GT del comparador "
                  "falló al medir (ver comparador_gt en su evaluación); la fila es la recalculada")
    if res.discrepancias:
        print("\nNO reproduce lo guardado (evaluacion_*.json, checklist.json de los runs leídos "
              "por partes, metadata de replay_e4 o versión del código de los runs):")
        for d in res.discrepancias:
            print(f"  {d}")
        sys.exit(1)
    print("Conteos de checklist y comparador, y evaluaciones contra el GT = lo guardado")


if __name__ == "__main__":
    main()
