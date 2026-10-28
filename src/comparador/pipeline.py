"""Orquestador end-to-end del pipeline de comparación."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, TypeVar

from comparador import etapa4_matching
from comparador.catalogo import cargar_hints_empresa
from comparador.config import settings
from comparador.etapa0_checklist import cargar_puntos, verificar_checklist
from comparador.etapa1_descubrir_panos import descubrir_panos
from comparador.etapa2_normalizar_excel import normalizar_excel
from comparador.etapa3_extraer_hallazgos import (
    ExtraccionInvalidaError,
    extraer_hallazgos_pdf,
    llamadas_llm_e3,
)
from comparador.etapa4_matching import (
    Vectores,
    contar_copias_unificadas,
    contar_reintentos,
    ejecutar_matching,
)
from comparador.etapa5_consolidar import consolidar_reporte
from comparador.llm.embeddings import probar_clave_openai
from comparador.persistence import (
    ARCHIVO_CONFIG_E4,
    MODO_COMPLETO,
    MODO_SOLO_CHECKLIST,
    crear_run_dir,
    guardar_hash_input,
    guardar_json,
    guardar_llm_raw,
    guardar_vectores,
    terminar_run,
    version_codigo,
)
from comparador.schemas import (
    SCHEMA_VERSION,
    ChecklistInforme,
    EmpresaAuditora,
    MetadatosInforme,
    PanoDescubierto,
    ReporteInforme,
)

T = TypeVar("T")


class CredencialesFaltantesError(Exception):
    """Falta una API key que la configuración de modelos exige."""


def _guardar_metas_e4(run_dir: Path, metas: list[dict[str, Any]]) -> None:
    """Raw de E4: judge_0..judge_{N-1} contiguos (naming estable entre runs
    para auditoría) + el registro de embeddings aparte; los lotes del juez de
    redacción en su propia carpeta, redaccion_0..redaccion_{M-1}."""
    i_judge = 0
    i_redaccion = 0
    for meta in metas:
        if meta.get("etapa") == "embeddings":
            guardar_llm_raw(run_dir, "etapa4_llm_judge_raw", "embeddings", meta)
        elif meta.get("tipo") == "juez_redaccion":
            guardar_llm_raw(run_dir, "etapa4_redaccion_raw", f"redaccion_{i_redaccion}", meta)
            i_redaccion += 1
        else:
            guardar_llm_raw(run_dir, "etapa4_llm_judge_raw", f"judge_{i_judge}", meta)
            i_judge += 1


@contextmanager
def _reloj(relojes: dict[str, dict[str, Any]], etapa: str) -> Iterator[None]:
    """Inicio y duración de una etapa, para metadata.json: sin reloj por etapa no
    se puede atribuir un cambio de tiempo (las etapas corren en paralelo)."""
    inicio, t0 = datetime.now(), time.monotonic()
    try:
        yield
    finally:
        relojes[etapa] = {
            "inicio": inicio.isoformat(timespec="microseconds"),
            "segundos": round(time.monotonic() - t0, 2),
        }


def _con_reloj(
    relojes: dict[str, dict[str, Any]], etapa: str, fn: Callable[..., T], *args: Any
) -> T:
    with _reloj(relojes, etapa):
        return fn(*args)


def _persistir_checklist(
    run_dir: Path, res_checklist: tuple[ChecklistInforme, dict[str, Any]] | BaseException
) -> None:
    """Guarda lo que dejó el checklist: el resultado y su raw, o la respuesta
    pagada que trae la excepción si falló (invariante 20). No relanza."""
    if isinstance(res_checklist, BaseException):
        meta = getattr(res_checklist, "llm_metadata", None)
        if isinstance(meta, dict):
            guardar_llm_raw(run_dir, "checklist_raw", "verificar_checklist", meta)
    else:
        checklist, meta_checklist = res_checklist
        guardar_json(run_dir, "checklist.json", checklist.model_dump(mode="json"))
        guardar_llm_raw(run_dir, "checklist_raw", "verificar_checklist", meta_checklist)


def _persistir_checklist_y_e1(
    run_dir: Path,
    res_checklist: tuple[ChecklistInforme, dict[str, Any]] | BaseException,
    res_e1: tuple[list[PanoDescubierto], dict[str, Any]] | BaseException,
) -> None:
    """Guarda lo que dejaron el checklist y E1, terminen bien o mal (invariante 20).

    Si alguna falló, se guarda la respuesta pagada que trae su excepción y se
    relanza la excepción original, sin cambiar su tipo ni su mensaje (la otra,
    si también falló, va como nota). Ninguna falla produce reporte_final.json:
    lo ya pagado queda solo como intermedio.
    """
    _persistir_checklist(run_dir, res_checklist)
    if isinstance(res_e1, BaseException):
        meta = getattr(res_e1, "llm_metadata", None)
        if isinstance(meta, dict):
            guardar_llm_raw(run_dir, "etapa1_raw", "descubrir_panos", meta)
    else:
        panos, meta_e1 = res_e1
        guardar_json(run_dir, "etapa1_panos.json", [p.model_dump(mode="json") for p in panos])
        guardar_llm_raw(run_dir, "etapa1_raw", "descubrir_panos", meta_e1)
    errores = [r for r in (res_checklist, res_e1) if isinstance(r, BaseException)]
    if errores:
        for otro in errores[1:]:
            errores[0].add_note(
                f"También falló la otra etapa en paralelo: {type(otro).__name__}: {otro}"
            )
        raise errores[0]


def _config_e4(empresa_auditora: EmpresaAuditora, metadatos: MetadatosInforme) -> dict[str, Any]:
    """Lo que reproducir_e4 necesita para repetir E4 y E5 de este run si falla
    después de pagar (sin metadata.json ni reporte_final.json): la
    configuración de E4 (con el effort, que va en la request de los jueces),
    la empresa y los metadatos del informe. El checklist ya está en
    checklist.json y los hallazgos en los JSON de E2 y E3."""
    return {
        "empresa_auditora": empresa_auditora.value,
        "modelo_extraccion": settings.modelo_extraccion,
        "modelo_juez_matching": settings.modelo_juez_matching or None,
        "modelo_embeddings": settings.modelo_embeddings,
        "juez_redaccion": settings.juez_redaccion,
        "asignacion_global": settings.asignacion_global,
        "descripcion_identica": settings.descripcion_identica,
        "control_codigos": settings.control_codigos,
        "unificar_copias": settings.unificar_copias,
        "juez_justifica_primero": settings.juez_justifica_primero,
        "top_k_candidatos": settings.top_k_candidatos,
        "threshold_descripcion": settings.threshold_descripcion,
        "threshold_accion": settings.threshold_accion,
        "effort_llm": settings.effort_llm,
        "metadatos_informe": metadatos.model_dump(mode="json"),
    }


def _tokens_e4(metas: list[dict[str, Any]]) -> dict[str, int]:
    """Tokens de E4 por origen para metadata.json: juez de matching, juez de
    redacción y embeddings, por separado (se suman sin solaparse)."""
    def total(filtro: Callable[[dict[str, Any]], bool]) -> int:
        return sum(m.get("tokens_total", 0) or 0 for m in metas if filtro(m))

    return {
        "tokens_e4": total(
            lambda m: m.get("etapa") != "embeddings" and m.get("tipo") != "juez_redaccion"
        ),
        "tokens_e4_redaccion": total(lambda m: m.get("tipo") == "juez_redaccion"),
        "tokens_embeddings": total(lambda m: m.get("etapa") == "embeddings"),
    }


def _validar_credenciales(solo_checklist: bool = False) -> None:
    """Preflight: falla ANTES de gastar tokens, no en la Etapa 4.

    Los embeddings son siempre OpenAI; la extracción/juez depende del prefijo
    del modelo. Sin este check, un run con la key equivocada muere en el
    matching después de completar checklist + E1 + E3 (~400K tokens). En modo
    solo checklist no hay embeddings ni juez: OpenAI solo si el modelo lo es.
    """
    # Incluye el fallback: si está configurado, puede ejecutarse en cualquier
    # llamada y necesita su key igual que el modelo principal.
    modelos = {
        m
        for m in (
            settings.modelo_extraccion,
            "" if solo_checklist else settings.modelo_juez_matching,
            settings.modelo_extraccion_fallback,
        )
        if m
    }
    faltantes = []
    if solo_checklist:
        if any(not m.startswith("claude") for m in modelos) and not settings.openai_api_key:
            faltantes.append("OPENAI_API_KEY (hay modelos que no son claude-* configurados)")
    elif not settings.openai_api_key:
        faltantes.append("OPENAI_API_KEY (los embeddings siempre usan OpenAI)")
    if any(m.startswith("claude") for m in modelos) and not settings.anthropic_api_key:
        faltantes.append("ANTHROPIC_API_KEY (hay modelos claude-* configurados)")
    if faltantes:
        raise CredencialesFaltantesError(
            "Faltan credenciales en .env: " + "; ".join(faltantes) + "."
        )


class EstadoPipeline:
    def __init__(self) -> None:
        self.estado: str = "procesando"
        self.etapa_actual: str = ""
        self.etapas_completadas: list[str] = []
        self.error: str | None = None

    def avanzar(self, etapa: str) -> None:
        if self.etapa_actual:
            self.etapas_completadas.append(self.etapa_actual)
        self.etapa_actual = etapa

    def completar(self) -> None:
        if self.etapa_actual:
            self.etapas_completadas.append(self.etapa_actual)
        self.etapa_actual = ""
        self.estado = "completado"

    def fallar(self, error: str) -> None:
        self.estado = "error"
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {
            "estado": self.estado,
            "etapa_actual": self.etapa_actual,
            "etapas_completadas": self.etapas_completadas,
            "error": self.error,
        }


async def ejecutar_pipeline(
    ruta_pdf: Path,
    ruta_excel: Path,
    empresa_auditora: EmpresaAuditora,
    on_progreso: Callable[[str], None] | None = None,
    run_dir: Path | None = None,
    ruta_pdf_texto: Path | None = None,
) -> tuple[ReporteInforme, Path]:
    """Ejecuta el pipeline completo de comparación.

    Args:
        ruta_pdf: Ruta al PDF del coordinado (el que lee el modelo).
        ruta_excel: Ruta al Excel regulatorio.
        empresa_auditora: Empresa seleccionada por el usuario; determina los
            hints del catálogo que se aplican en la extracción.
        on_progreso: Callback opcional para reportar progreso.
        run_dir: Directorio del run (si None, crea uno nuevo).
        ruta_pdf_texto: PDF con capa de texto para verificar las citas, si no
            es `ruta_pdf` (el adecuado para modelos no-Claude va rasterizado,
            con la misma paginación). None = `ruta_pdf`.

    Returns:
        Tupla de (ReporteInforme, ruta del directorio del run).
    """
    _validar_credenciales()

    # Cargar los hints acá (no solo en E3) adelanta EmpresaNoCatalogadaError
    # a antes de gastar tokens, y provee los patrones de filas transversales
    # que E2 necesita.
    hints = cargar_hints_empresa(empresa_auditora)

    propio = run_dir is None
    if run_dir is None:
        run_dir = crear_run_dir(settings.modelo_extraccion)
    try:

        t0 = time.monotonic()
        fecha_inicio = datetime.now()
        version = version_codigo()
        relojes: dict[str, dict[str, Any]] = {}

        def progreso(etapa: str) -> None:
            if on_progreso:
                on_progreso(etapa)

        # --- Hashes de inputs y versión del código ---
        guardar_hash_input(run_dir, ruta_pdf, "pdf")
        ruta_texto = ruta_pdf_texto or ruta_pdf
        if ruta_texto != ruta_pdf:
            guardar_hash_input(run_dir, ruta_texto, "pdf_texto")
        guardar_hash_input(run_dir, ruta_excel, "excel")
        # También en los runs que fallan (metadata.json solo existe si el run termina).
        guardar_json(run_dir, "version.json", version)

        loop = asyncio.get_running_loop()

        # --- Preflight sin costo: criterios del checklist y Excel (E2) ---
        # Antes de gastar en el checklist y E1: un ChecklistConfigError o un Excel
        # inválido fallan acá, sin ninguna llamada pagada.
        cargar_puntos()
        hallazgos_excel, metadatos_informe = await loop.run_in_executor(
            None, _con_reloj, relojes, "e2", normalizar_excel, ruta_excel, hints.filas_transversales
        )
        hallazgos_excel_dump = [h.model_dump(mode="json") for h in hallazgos_excel]
        guardar_json(run_dir, "etapa2_excel_normalizado.json", hallazgos_excel_dump)
        progreso("normalizar_excel")

        # --- Prueba de la clave de OpenAI (PD66), antes de la primera llamada pagada ---
        # Los embeddings de E4 son siempre de OpenAI: sin fondos o con la clave
        # revocada, E4 fallaría después de pagar checklist, E1 y E3. Con la misma
        # función que usará E4; no es una llamada de E4 (va solo a metadata.json).
        prueba_clave = await loop.run_in_executor(
            None, probar_clave_openai, etapa4_matching.calcular_embeddings)

        # --- Checklist + E1 en paralelo (los dos leen solo el PDF) ---
        progreso("verificaciones_paralelas")
        res_checklist, res_e1 = await asyncio.gather(
            loop.run_in_executor(
                None, _con_reloj, relojes, "checklist", verificar_checklist, ruta_pdf, ruta_texto
            ),
            loop.run_in_executor(None, _con_reloj, relojes, "e1", descubrir_panos, ruta_pdf),
            return_exceptions=True,
        )
        _persistir_checklist_y_e1(run_dir, res_checklist, res_e1)
        assert not isinstance(res_checklist, BaseException)
        assert not isinstance(res_e1, BaseException)
        (checklist, meta_checklist), (panos, meta_e1) = res_checklist, res_e1
        progreso("descubrir_panos")

        # Informe que no cupo entero en el contexto: el troceo nunca es silencioso
        # (la UI lo lee de acá, también al reabrir el run).
        if "troceo" in meta_checklist or "troceo" in meta_e1:
            guardar_json(run_dir, "troceo.json", {
                "checklist": meta_checklist.get("troceo"),
                "descubrir_panos": meta_e1.get("troceo"),
            })

        # --- E3: extracción de hallazgos del PDF ---
        progreso("extraccion_pdf")

        try:
            with _reloj(relojes, "e3"):
                hallazgos_pdf, metas_e3 = await extraer_hallazgos_pdf(
                    ruta_pdf, panos, empresa_auditora, ruta_texto
                )
        except ExtraccionInvalidaError as exc:
            # Igual que el juez de E4: los dos intentos del paño que falló son el
            # artefacto que explica el error (invariante 20).
            for nombre, meta in llamadas_llm_e3(exc.llm_metadata):
                guardar_llm_raw(run_dir, "etapa3_raw", nombre, meta)
            raise

        guardar_json(
            run_dir, "etapa3_pdf_hallazgos.json", [h.model_dump(mode="json") for h in hallazgos_pdf]
        )
        # Un paño reintentado deja dos raw: extraer_{paño}_intento1 y extraer_{paño}.
        for nombre, meta in llamadas_llm_e3(metas_e3):
            guardar_llm_raw(run_dir, "etapa3_raw", nombre, meta)

        # --- E4: matching ---
        progreso("matching")
        guardar_json(run_dir, ARCHIVO_CONFIG_E4, _config_e4(empresa_auditora, metadatos_informe))

        # ejecutar_matching es síncrono y bloqueante (embeddings + LLM-judge con
        # reintentos): sin executor congelaría el event loop y el polling del front.
        # Los vectores de embeddings quedan en el run (M70): sin ellos E4 no se
        # repite igual ni sin volver a pagarlos (reproducir_e4).
        vectores: Vectores = {}
        try:
            resultados, metas_e4 = await loop.run_in_executor(
                None, _con_reloj, relojes, "e4", partial(ejecutar_matching, vectores=vectores),
                hallazgos_pdf, hallazgos_excel,
            )
        except Exception as exc:
            # Persistir los raw ya pagados ANTES de propagar: la respuesta inválida
            # del juez (JuezInvalidoError) o la llamada que falló en el cliente
            # (etapa4_matching._llamar_juez) es justo el artefacto que explica el
            # error (invariante 20). La excepción sale tal cual.
            metas = getattr(exc, "llm_metadata", None)
            if isinstance(metas, list):
                _guardar_metas_e4(run_dir, metas)
            if vectores:   # pagados antes de la falla; guardarlos no tapa el error de E4
                try:
                    guardar_vectores(run_dir, vectores, settings.modelo_embeddings)
                except Exception as error_vectores:
                    exc.add_note(f"Tampoco se guardaron los vectores de E4: {error_vectores}")
            raise

        guardar_json(run_dir, "etapa4_matches.json",
                     [r.model_dump(mode="json") for r in resultados])
        _guardar_metas_e4(run_dir, metas_e4)
        if vectores:
            guardar_vectores(run_dir, vectores, settings.modelo_embeddings)

        # --- E5: consolidación ---
        progreso("consolidar")

        with _reloj(relojes, "e5"):
            reporte = consolidar_reporte(resultados, metadatos_informe, empresa_auditora, checklist)

        # mode="json" garantiza fecha_procesamiento en ISO-8601, igual que
        # model_dump_json() del endpoint — un solo formato para el contrato.
        guardar_json(run_dir, "reporte_final.json", reporte.model_dump(mode="json"))

        metadata_run: dict[str, Any] = {
            "empresa_auditora": empresa_auditora.value,
            "modelo_extraccion": settings.modelo_extraccion,
            "modelo_juez_matching": settings.modelo_juez_matching or None,
            "modelo_embeddings": settings.modelo_embeddings,
            "schema_version": reporte.schema_version,
            "total_hallazgos_pdf": len(hallazgos_pdf),
            "total_hallazgos_excel": len(hallazgos_excel),
            "total_transversales_excel": sum(1 for h in hallazgos_excel if h.es_transversal),
            "total_panos": len(panos),
            "tokens_checklist": meta_checklist.get("tokens_total"),
            "tokens_e1": meta_e1.get("tokens_total"),
            "tokens_e3": sum(
                m.get("tokens_total", 0) or 0 for _, m in llamadas_llm_e3(metas_e3)
            ),
            **_tokens_e4(metas_e4),
            "fecha_inicio": fecha_inicio.isoformat(),
            "fecha_fin": datetime.now().isoformat(),
            "duracion_segundos": round(time.monotonic() - t0, 1),
            "threshold_descripcion": settings.threshold_descripcion,
            "threshold_accion": settings.threshold_accion,
            "juez_redaccion": settings.juez_redaccion,
            "cita_checklist": settings.cita_checklist,
            "checklist_un_tramo": settings.checklist_un_tramo,
            "checklist_batch": settings.checklist_batch,
            "asignacion_global": settings.asignacion_global,
            "descripcion_identica": settings.descripcion_identica,
            "control_codigos": settings.control_codigos,
            "unificar_copias": settings.unificar_copias,
            "juez_justifica_primero": settings.juez_justifica_primero,
            # Consultas extra del juez por conflictos de la asignación global.
            "llamadas_juez_reintento": contar_reintentos(metas_e4),
            "copias_unificadas": contar_copias_unificadas(resultados),
            "top_k_candidatos": settings.top_k_candidatos,
            "relojes_etapas": relojes,
            "version_codigo": version,
            "modo": MODO_COMPLETO,
            "prueba_clave_openai": prueba_clave,
        }
        guardar_json(run_dir, "metadata.json", metadata_run)

        return reporte, run_dir
    finally:
        # La retención no borra un run en curso; el que creó el pipeline lo libera él.
        if propio:
            terminar_run(run_dir)


async def ejecutar_solo_checklist(
    ruta_pdf: Path,
    *,
    run_dir: Path | None = None,
    ruta_pdf_texto: Path | None = None,
    on_progreso: Callable[[str], None] | None = None,
    empresa_auditora: EmpresaAuditora | None = None,
) -> tuple[ChecklistInforme, Path]:
    """Solo la Etapa 0 (checklist), con la misma persistencia que el pipeline.

    Para medir el checklist sin pagar el resto del informe (ronda B3: la cita
    del checklist encendida y apagada sobre el mismo informe). El run queda
    marcado con `modo: "solo_checklist"` en metadata.json: la retención lo
    trata como completo y las métricas no lo cuentan en el comparador.
    """
    _validar_credenciales(solo_checklist=True)
    propio = run_dir is None
    if run_dir is None:
        run_dir = crear_run_dir(settings.modelo_extraccion)
    try:

        t0 = time.monotonic()
        fecha_inicio = datetime.now()
        version = version_codigo()
        relojes: dict[str, dict[str, Any]] = {}

        guardar_hash_input(run_dir, ruta_pdf, "pdf")
        ruta_texto = ruta_pdf_texto or ruta_pdf
        if ruta_texto != ruta_pdf:
            guardar_hash_input(run_dir, ruta_texto, "pdf_texto")
        guardar_json(run_dir, "version.json", version)

        cargar_puntos()  # preflight sin costo
        if on_progreso:
            on_progreso("checklist")
        loop = asyncio.get_running_loop()
        try:
            resultado = await loop.run_in_executor(
                None, _con_reloj, relojes, "checklist", verificar_checklist, ruta_pdf, ruta_texto
            )
        except Exception as exc:
            _persistir_checklist(run_dir, exc)
            raise
        _persistir_checklist(run_dir, resultado)
        checklist, meta = resultado
        if "troceo" in meta:
            guardar_json(run_dir, "troceo.json", {
                "checklist": meta["troceo"], "descubrir_panos": None,
            })

        guardar_json(run_dir, "metadata.json", {
            "modo": MODO_SOLO_CHECKLIST,
            "empresa_auditora": empresa_auditora.value if empresa_auditora else None,
            "modelo_extraccion": settings.modelo_extraccion,
            "schema_version": SCHEMA_VERSION,
            "tokens_checklist": meta.get("tokens_total"),
            # No corrieron: 0 tokens (los controles de métricas los esperan).
            "tokens_e1": 0, "tokens_e3": 0, "tokens_e4": 0, "tokens_e4_redaccion": 0,
            "tokens_embeddings": 0,
            "fecha_inicio": fecha_inicio.isoformat(),
            "fecha_fin": datetime.now().isoformat(),
            "duracion_segundos": round(time.monotonic() - t0, 1),
            "cita_checklist": settings.cita_checklist,
            "checklist_un_tramo": settings.checklist_un_tramo,
            "checklist_batch": settings.checklist_batch,
            "relojes_etapas": relojes,
            "version_codigo": version,
        })
        return checklist, run_dir
    finally:
        # La retención no borra un run en curso; el que creó el pipeline lo libera él.
        if propio:
            terminar_run(run_dir)
