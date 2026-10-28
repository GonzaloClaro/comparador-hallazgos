"""FastAPI server: endpoints REST + sirve frontend estático."""

from __future__ import annotations

import asyncio
import contextlib
import io
import traceback
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from comparador import feedback as feedback_mod
from comparador.config import settings
from comparador.convertir import adecuar_pdf_para_llm, convertir_docx_a_pdf
from comparador.exportar import exportar_csv, exportar_feedback_guardado, exportar_xlsx
from comparador.persistence import (
    cargar_json,
    crear_run_dir,
    guardar_hash_input,
    guardar_json,
    terminar_run,
)
from comparador.pipeline import EstadoPipeline, ejecutar_pipeline
from comparador.schemas import EmpresaAuditora, FeedbackRun, ReporteInforme

app = FastAPI(title="Comparador de Hallazgos")

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


def _validar_run_id(run_id: str) -> Path | None:
    run_path = (settings.runs_dir / run_id).resolve()
    if not run_path.is_relative_to(settings.runs_dir.resolve()):
        return None
    return run_path

_runs_estado: dict[str, EstadoPipeline] = {}
_runs_reporte: dict[str, ReporteInforme] = {}
# El event loop solo guarda referencias débiles a las tasks: sin esta
# referencia fuerte, el GC podría matar un run en curso silenciosamente.
_tareas_activas: set[asyncio.Task[None]] = set()


@app.post("/api/procesar")
async def procesar(
    pdf: UploadFile,
    excel: UploadFile,
    empresa_auditora: str = Form(...),
) -> JSONResponse:
    try:
        empresa = EmpresaAuditora(empresa_auditora)
    except ValueError:
        validas = ", ".join(e.value for e in EmpresaAuditora)
        return JSONResponse(
            {"error": f"Empresa auditora inválida: {empresa_auditora!r}. Válidas: {validas}"},
            status_code=400,
        )

    # Los archivos se leen antes de crear el run: si la subida falla, no queda
    # un run marcado en curso que nadie libere.
    bytes_informe, bytes_excel = await pdf.read(), await excel.read()
    run_dir = crear_run_dir(settings.modelo_extraccion)
    run_id = run_dir.name

    es_docx = (pdf.filename or "").lower().endswith(".docx")
    ruta_informe = run_dir / ("input.docx" if es_docx else "input.pdf")
    ruta_excel = run_dir / "input.xlsx"

    try:
        ruta_informe.write_bytes(bytes_informe)
        ruta_excel.write_bytes(bytes_excel)
        # Cadena de custodia (paridad con Streamlit): hash y nombre del archivo
        # tal como se subió — el pipeline hashea el PDF ya convertido/adecuado.
        guardar_hash_input(run_dir, ruta_informe, "informe_original")
        guardar_json(run_dir, "inputs.json", {
            "informe": pdf.filename or ruta_informe.name,
            "excel": excel.filename or ruta_excel.name,
        })
    except BaseException as exc:
        # Antes de la tarea (y de su finally): registrar y liberar acá.
        with contextlib.suppress(OSError):
            guardar_json(run_dir, "error.json", {
                "tipo": type(exc).__name__, "mensaje": str(exc),
                "traceback": traceback.format_exc(), "fecha": datetime.now().isoformat(),
            })
        terminar_run(run_dir)
        raise

    estado = EstadoPipeline()
    _runs_estado[run_id] = estado

    async def _run() -> None:
        try:
            loop = asyncio.get_running_loop()
            ruta_pdf = ruta_informe

            estado.avanzar("preparando_archivo")
            conversion = None
            if es_docx:
                ruta_pdf, conversion = await loop.run_in_executor(
                    None, convertir_docx_a_pdf, ruta_informe, run_dir / "input.pdf"
                )
            # No-Claude: más de 100 págs falla (PdfExcedeLimitesError); solo tamaño → rasteriza.
            # Las citas se verifican contra el PDF con texto (misma paginación).
            ruta_pdf_texto = ruta_pdf
            ruta_pdf, adecuacion = await loop.run_in_executor(
                None, adecuar_pdf_para_llm, ruta_pdf
            )
            if adecuacion or conversion:
                guardar_json(run_dir, "adecuacion.json", {
                    **(adecuacion or {}),
                    **({"conversion": conversion} if conversion else {}),
                })

            estado.avanzar("iniciando")
            reporte, _ = await ejecutar_pipeline(
                ruta_pdf=ruta_pdf,
                ruta_excel=ruta_excel,
                empresa_auditora=empresa,
                on_progreso=estado.avanzar,
                run_dir=run_dir,
                ruta_pdf_texto=ruta_pdf_texto,
            )
            estado.completar()
            _runs_reporte[run_id] = reporte
        except Exception as e:
            estado.fallar(f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
            # También a disco: el estado en memoria muere con el proceso y el
            # run quedaría sin registro del porqué (invariante 20).
            guardar_json(run_dir, "error.json", {
                "tipo": type(e).__name__,
                "mensaje": str(e),
                "notas": list(getattr(e, "__notes__", [])),
                "traceback": traceback.format_exc(),
                "fecha": datetime.now().isoformat(),
            })
        finally:
            terminar_run(run_dir)

    tarea = asyncio.create_task(_run())
    _tareas_activas.add(tarea)
    tarea.add_done_callback(_tareas_activas.discard)

    return JSONResponse({"run_id": run_id})


@app.get("/api/runs/{run_id}/estado")
async def get_estado(run_id: str) -> JSONResponse:
    if _validar_run_id(run_id) is None:
        return JSONResponse({"error": "Run ID inválido"}, status_code=400)
    estado = _runs_estado.get(run_id)
    if not estado:
        return JSONResponse({"error": "Run no encontrado"}, status_code=404)

    data = estado.to_dict()
    data["run_id"] = run_id
    data["tiempo_inicio"] = None
    data["tiempo_fin"] = None
    return JSONResponse(data)


@app.get("/api/runs/{run_id}/reporte")
async def get_reporte(run_id: str) -> JSONResponse:
    reporte = _obtener_reporte(run_id)
    if reporte is None:
        return JSONResponse({"error": "Reporte no disponible"}, status_code=404)
    return JSONResponse(reporte.model_dump(mode="json"))


@app.get("/api/runs/{run_id}/export/xlsx")
async def export_xlsx(run_id: str) -> Response:
    reporte = _obtener_reporte(run_id)
    if reporte is None:
        return JSONResponse({"error": "Reporte no disponible"}, status_code=404)

    contenido = exportar_xlsx(reporte)
    return Response(
        content=contenido,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="comparacion_{run_id}.xlsx"'},
    )


@app.get("/api/runs/{run_id}/export/csv")
async def export_csv(run_id: str) -> Response:
    reporte = _obtener_reporte(run_id)
    if reporte is None:
        return JSONResponse({"error": "Reporte no disponible"}, status_code=404)

    contenido = exportar_csv(reporte)
    return Response(
        content=contenido,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="comparacion_{run_id}.csv"'},
    )


@app.get("/api/runs/{run_id}/feedback")
async def get_feedback(run_id: str) -> JSONResponse:
    try:
        fb = feedback_mod.cargar_feedback(run_id)
    except feedback_mod.RunIdInvalidoError:
        return JSONResponse({"error": "Run ID inválido"}, status_code=400)
    except (TimeoutError, OSError, ValueError) as exc:
        # La UI no debe seguir con un feedback vacío: su próximo POST pisaría lo guardado.
        return JSONResponse({"error": f"No se pudo leer el feedback: {exc}"}, status_code=503)
    return JSONResponse(fb.model_dump(mode="json"))


_CAMPOS_FEEDBACK_VANILLA = {"veredictos_resultados", "veredictos_checklist", "comentarios"}


@app.post("/api/runs/{run_id}/feedback")
async def guardar_feedback(run_id: str, feedback: FeedbackRun) -> JSONResponse:
    run_path = _validar_run_id(run_id)
    if run_path is None or not run_path.is_dir():
        return JSONResponse({"error": "Run no encontrado"}, status_code=404)
    try:
        # Solo los campos que edita la UI vanilla, y solo si vienen en el
        # cuerpo: las respuestas SI/NO/N/A y los motivos se editan en Streamlit.
        # frontend/app.js manda solo esos tres; un cliente que reenviara el
        # objeto completo del GET tampoco los pisaría. Sus mapas de ✓/✗
        # reemplazan a los guardados (legacy); un ✗ que pasó a ✓ pierde su
        # motivo (actualizar_feedback descarta los huérfanos).
        def cambiar(existente: FeedbackRun) -> None:
            for campo in feedback.model_fields_set & _CAMPOS_FEEDBACK_VANILLA:
                setattr(existente, campo, getattr(feedback, campo))

        feedback_mod.actualizar_feedback(run_id, cambiar)
    except feedback_mod.RunIdInvalidoError:
        return JSONResponse({"error": "Run ID inválido"}, status_code=400)
    return JSONResponse({"ok": True})


@app.get("/api/runs/{run_id}/export/feedback")
async def export_feedback(run_id: str) -> Response:
    reporte = _obtener_reporte(run_id)
    if reporte is None or _validar_run_id(run_id) is None:
        return JSONResponse({"error": "Reporte no disponible"}, status_code=404)
    try:
        contenido = exportar_feedback_guardado(reporte, run_id)
    except feedback_mod.RunIdInvalidoError:
        return JSONResponse({"error": "Run ID inválido"}, status_code=400)
    return Response(
        content=contenido,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="feedback_{run_id}.md"'},
    )


@app.get("/api/runs/{run_id}/logs")
async def descargar_logs(run_id: str) -> Response:
    """Zip con todos los intermediates del run, para debug de errores."""
    run_path = _validar_run_id(run_id)
    if run_path is None or not run_path.is_dir():
        return JSONResponse({"error": "Run no encontrado"}, status_code=404)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for archivo in sorted(run_path.rglob("*")):
            if archivo.is_file():
                zf.write(archivo, archivo.relative_to(run_path))

    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="logs_{run_id}.zip"'},
    )


@app.get("/api/runs")
async def list_runs() -> JSONResponse:
    runs: list[dict[str, Any]] = []
    if settings.runs_dir.exists():
        for d in sorted(settings.runs_dir.iterdir(), reverse=True):
            if d.is_dir() and (d / "reporte_final.json").exists():
                meta_path = d / "metadata.json"
                meta = cargar_json(meta_path) if meta_path.exists() else {}
                runs.append({
                    "run_id": d.name,
                    "tiene_reporte": True,
                    **meta,
                })
    return JSONResponse(runs)


def _obtener_reporte(run_id: str) -> ReporteInforme | None:
    """Reporte desde memoria o disco, siempre validado contra el schema.

    Un reporte_final.json de un schema incompatible (runs históricos de
    versiones previas) se trata como no disponible — el contrato con el
    frontend es ReporteInforme, no JSON arbitrario.
    """
    if _validar_run_id(run_id) is None:
        return None
    reporte = _runs_reporte.get(run_id)
    if reporte:
        return reporte

    reporte_path = settings.runs_dir / run_id / "reporte_final.json"
    if reporte_path.exists():
        try:
            return ReporteInforme.model_validate(cargar_json(reporte_path))
        except ValueError:
            return None

    return None


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
