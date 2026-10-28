"""Interfaz Streamlit del comparador de hallazgos + checklist.

Alternativa al dashboard FastAPI (rama `streamlit`). Reusa TODO el backend:
pipeline, conversión, exportación y persistencia son idénticos; solo cambia la
capa de presentación.

Ejecutar:  uv run streamlit run streamlit_app.py
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import html
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from streamlit.runtime.scriptrunner_utils.exceptions import StopException
from streamlit.runtime.uploaded_file_manager import UploadedFile

from comparador import feedback
from comparador.catalogo import cargar_hints_empresa
from comparador.citas import etiqueta_verificacion
from comparador.config import settings
from comparador.convertir import adecuar_pdf_para_llm, convertir_docx_a_pdf
from comparador.exportar import exportar_csv, exportar_feedback_guardado, exportar_xlsx
from comparador.persistence import (
    cargar_json,
    crear_run_dir,
    en_curso,
    es_solo_checklist,
    guardar_hash_input,
    guardar_json,
    terminar_run,
)
from comparador.pipeline import ejecutar_pipeline
from comparador.schemas import (
    CampoDiferente,
    ChecklistInforme,
    EmpresaAuditora,
    EstadoCita,
    EstadoHallazgo,
    FeedbackRun,
    ItemChecklist,
    MatchResult,
    MotivoDiferencia,
    MotivoFeedback,
    MotivoIncorrecto,
    ReporteInforme,
    ResultadoChecklist,
    TipoMatch,
    VerificacionCita,
)
from comparador.visor_pdf import (
    EstadoPdf,
    PaginaRenderizada,
    PaginaVisor,
    PdfDelRun,
    Resaltado,
    paginas_citas,
    paginas_hallazgo,
    paginas_mencionadas,
    pdf_del_run,
    render_pagina,
)

# Un hallazgo del grupo de un paño: (índice global, MatchResult).
ItemGrupo = tuple[int, MatchResult]

st.set_page_config(page_title="Comparador de Hallazgos", page_icon="⚡", layout="wide")

# Estilos: paleta y componentes del dashboard original (header teal, tiles de
# color semántico).
st.markdown("""
<style>
  .header-cen { background:#1B3A4B; color:#fff; padding:20px 28px; border-radius:8px;
                margin-bottom:8px; }
  .header-cen h1 { margin:0; font-size:1.6rem; }
  .header-cen .meta { color:rgba(255,255,255,.7); font-size:.9rem; margin-top:4px; }
  .tiles { display:flex; gap:14px; margin:14px 0; }
  .tile { flex:1; border-radius:8px; padding:12px 16px; text-align:center; }
  .tile .lbl { font-size:.72rem; text-transform:uppercase; letter-spacing:.05em;
               color:#374151; }
  .tile .val { font-size:1.9rem; font-weight:700; line-height:1.1; }
  .tile .sub { font-size:.72rem; color:#374151; margin-top:2px; }
  .t-total   { background:#f3f4f6; }
  .t-ok      { background:#dcfce7; }
  .t-dif     { background:#fef9c3; }
  .t-falta   { background:#fee2e2; }
  .t-extra   { background:#ffedd5; }
  .t-trans   { background:#e5e7eb; }
  .t-check   { background:#dbeafe; }
  .justif { border-left:4px solid #9ca3af; background:#f9fafb; padding:10px 14px;
            border-radius:0 6px 6px 0; margin:10px 0 4px; font-size:.92rem; }
  .justif.warn { border-left-color:#eab308; background:#fefce8; }
</style>
""", unsafe_allow_html=True)

EMPRESAS = {"Ensaut": EmpresaAuditora.ENSAUT,
            "Sdi": EmpresaAuditora.SDI,
            "Reliable Energy": EmpresaAuditora.RELIABLE_ENERGY}

BADGE_MATCH = {"unicidad": "🟦 U", "descripcion_identica": "🟩 =", "semantico_alto": "🟪 ~",
               "semantico_bajo": "🟨 ?", "sin_match": "🟥 !"}

ETIQUETA_ESTADO = {
    EstadoHallazgo.COINCIDE.value: "✅ Coincide",
    EstadoHallazgo.DIFIERE.value: "🟡 Difiere",
    EstadoHallazgo.FALTA_EN_EXCEL.value: "🔴 FALTA EN EXCEL (grave)",
    EstadoHallazgo.EXTRA_EN_EXCEL.value: "🟠 Falta en el PDF (info)",
    EstadoHallazgo.TRANSVERSAL.value: "⚪ Transversal (revisión manual)",
}

# Variante de "coincide": algún campo de texto quedó bajo el umbral de
# similitud y el juez de redacción lo declaró mismo contenido (viene en
# MatchResult.equivalencias_redaccion; la UI solo lo presenta).
ETIQUETA_COINCIDE_REDACCION = "✅ Coincide · redacción distinta"

ETIQUETA_CAMPO = {
    CampoDiferente.DESCRIPCION.value: "Descripción",
    CampoDiferente.ACCION_CORRECTIVA.value: "Acción correctiva",
    CampoDiferente.CALIFICACION.value: "Calificación",
}

# Motivo de cada Diferencia (Diferencia.motivo, lo decide la Etapa 4), entre
# paréntesis en la columna Comentario. La calificación ya muestra sus valores; un
# reporte anterior a 0.12.0 no trae motivo y se ve como antes.
ETIQUETA_MOTIVO_DIFERENCIA = {
    MotivoDiferencia.VACIO_UN_LADO.value: "vacío en un lado",
    MotivoDiferencia.SIN_EMBEDDINGS.value: "sin comparar: revisar",
    MotivoDiferencia.SIMILITUD_BAJA.value: "textos poco parecidos",
    MotivoDiferencia.POLARIDAD_OPUESTA.value: "Cumple vs No cumple",
    MotivoDiferencia.CODIGO_CAMBIADO.value: "código o número distinto",
    MotivoDiferencia.JUEZ_REDACCION.value: "contenido distinto",
}

# Interpretación del emparejamiento en el punto de decisión (condensa la
# pestaña «Match y confianza» del expander). Texto estático por tipo_match: presentación
# pura, ningún cálculo en el frontend.
INTERPRETACION_MATCH = {
    TipoMatch.UNICIDAD.value: (
        "Emparejamiento seguro (confianza {c}): única clasificación en este "
        "paño/relé en ambos archivos, así que el par es el mismo hallazgo. Si "
        "difiere, mirar si la diferencia es de contenido o solo de redacción."
    ),
    TipoMatch.DESCRIPCION_IDENTICA.value: (
        "Emparejamiento seguro (confianza {c}): la misma descripción en el PDF y el "
        "Excel de este paño/relé, emparejada sin LLM. Si difiere, la diferencia está "
        "en la acción correctiva o en la calificación."
    ),
    TipoMatch.SEMANTICO_ALTO.value: (
        "Emparejamiento semántico en la banda alta de la rúbrica ({c}): el par "
        "es confiable. Si difiere, mirar si la diferencia es de contenido o solo "
        "de redacción."
    ),
    TipoMatch.SEMANTICO_BAJO.value: (
        "⚠ Emparejamiento dudoso ({c}): confirmar primero que ambos lados "
        "hablen del mismo hallazgo; recién entonces las diferencias tienen "
        "sentido."
    ),
    TipoMatch.SIN_MATCH.value: (
        "Sin par en el otro archivo — no hay emparejamiento que interpretar."
    ),
}
# Par con emparejamiento_dudoso (schema 0.9.0, asignación global: PD71): dudoso
# aunque su confianza sea alta. El motivo lo escribe entero el backend, de lo que hay
# que hacer a la consecuencia (PD72): la interfaz no le agrega frases (invariante 24).
INTERPRETACION_EMPAREJAMIENTO_DUDOSO = "⚠ Emparejamiento dudoso ({c}). {motivo}"
# Hallazgo del PDF que nombra a otros relés de su sección (schema 0.10.0, PD60): los
# nombres los da el backend; el texto es fijo y solo informa (no cambia el estado).
AVISO_OTROS_RELES = (
    "La viñeta del informe también nombra a: {reles}. Se comparó entera con esta fila del "
    "Excel: si el Excel la repartió entre relés, la diferencia puede venir solo de eso."
)
# Sin fila del Excel («falta en Excel»): cambia solo la segunda frase.
AVISO_OTROS_RELES_SIN_FILA = (
    "La viñeta del informe también nombra a: {reles}. No hay fila del Excel emparejada con "
    "ella: si el Excel la repartió entre relés, la falta puede venir solo de eso."
)
# «Coincide» (decisión del usuario 2026-10-26): no hay diferencia que explicar.
AVISO_OTROS_RELES_COINCIDE = (
    "La viñeta del informe también nombra a: {reles}. Se comparó entera con esta fila del "
    "Excel y coinciden: revisar que la fila no deje fuera la parte de los otros relés."
)

RESULTADO_CHECKLIST = {
    ResultadoChecklist.CUMPLE.value: "✅ Cumple",
    ResultadoChecklist.NO_CUMPLE.value: "❌ No cumple",
    ResultadoChecklist.NO_VERIFICABLE.value: "➖ No verificable",
}

# Estado de la verificación de una cita (comparador.citas): solo presentación.
ICONO_CITA = {
    EstadoCita.VERIFICADA.value: "✅",
    EstadoCita.CONTINUA_PAGINA_SIGUIENTE.value: "✅",
    EstadoCita.EN_OTRA_PAGINA.value: "↪️",
    EstadoCita.NO_ENCONTRADA.value: "⚠️",
    EstadoCita.SIN_TEXTO.value: "👁️",
}

ETAPAS = {
    "convertir_docx": "Convirtiendo DOCX a PDF...",
    "adecuar_pdf": "Adecuando el PDF a los límites de la API...",
    "verificaciones_paralelas": "Checklist + paños (en paralelo)...",
    "checklist": "Verificando checklist de aprobación...",
    "descubrir_panos": "Paños y relés descubiertos.",
    "normalizar_excel": "Excel normalizado.",
    "extraccion_pdf": "Extrayendo hallazgos del PDF...",
    "matching": "Comparando hallazgos...",
    "consolidar": "Consolidando reporte...",
}

VEREDICTOS = ["— sin revisar", "✓ correcto", "✗ incorrecto"]
# Respuesta del equipo revisor en el checklist, como en la planilla oficial.
SIN_RESPUESTA = "— sin revisar"
RESPUESTAS_CHECKLIST = [SIN_RESPUESTA, *feedback.RESPUESTAS_CHECKLIST]
_V_A_STR = {"✓ correcto": "correcto", "✗ incorrecto": "incorrecto"}
_STR_A_V = {"correcto": "✓ correcto", "incorrecto": "✗ incorrecto"}

ss = st.session_state
ss.setdefault("reporte", None)
ss.setdefault("run_id", None)
ss.setdefault("feedback", None)
ss.setdefault("error_procesamiento", None)
ss.setdefault("ultimo_run", None)


# ─────────────────────────── persistencia de feedback ───────────────────────

@functools.cache
def _empresa_sin_caracterizar(empresa: EmpresaAuditora) -> bool:
    """Best-effort para la advertencia de la UI: un catálogo ilegible no debe
    tumbar la pantalla de carga — el error real salta ruidoso (con error.json)
    cuando la Etapa 3 intente cargar los hints."""
    try:
        return cargar_hints_empresa(empresa).es_placeholder
    except Exception:  # noqa: BLE001
        return False


def abrir_feedback(run_id: str) -> bool:
    """Carga el feedback del run. Si no se puede (otro proceso tiene tomado el
    feedback, o el archivo está dañado), no abre el run: deja el aviso para la
    pantalla de carga y nunca una pantalla de resultados sin feedback."""
    try:
        cargado = feedback.cargar_feedback(run_id)
    except (TimeoutError, OSError, ValueError) as exc:
        ss.error_procesamiento = (f"No se pudo leer el feedback del run {run_id} "
                                  f"({type(exc).__name__}: {exc}). Reintentar en un momento.")
        return False
    ss.feedback = cargado
    ss[_clave_guardado(run_id)] = ss.feedback.model_copy(deep=True)
    # Base fija de la columna «Tu respuesta» mientras el run está abierto: el
    # ID del data_editor depende de sus datos, y si la columna se armara con
    # las respuestas recién guardadas, cada edición cambiaría el ID y la
    # siguiente se perdería (revisión F6g). Las ediciones quedan en el widget.
    ss[_clave_base_checklist(run_id)] = dict(ss.feedback.respuestas_checklist)
    return True


def _clave_base_checklist(run_id: str) -> str:
    return f"checklist_base_{run_id}"


def _clave_guardado(run_id: str) -> str:
    return f"feedback_guardado_{run_id}"


def guardar_feedback() -> None:
    """Guarda solo lo que esta sesión cambió desde su último guardado, sobre lo
    que hay en disco: otra pestaña abierta sobre el mismo run no se pisa. En
    feedback/<run_id>/, fuera de runs/ (la retención no lo borra); el reporte
    en memoria se copia si la retención ya borró el run."""
    guardado = ss.get(_clave_guardado(ss.run_id)) or FeedbackRun()
    cambios = feedback.cambios(guardado, ss.feedback)
    if not cambios:
        return
    resultado = feedback.actualizar_feedback(ss.run_id, cambios.aplicar, reporte=ss.reporte)
    if cambios.comentarios is not None and resultado.comentarios != ss.feedback.comentarios:
        # Otra pestaña había cambiado el comentario: quedaron los dos textos y
        # esta sesión los adopta (guardar_feedback corre siempre en un callback,
        # así que puede actualizar el campo antes de dibujarlo).
        ss.feedback.comentarios = resultado.comentarios
        ss[f"comentarios_{ss.run_id}"] = resultado.comentarios
    ss[_clave_guardado(ss.run_id)] = ss.feedback.model_copy(deep=True)


def _hay_run_abierto() -> bool:
    # Un callback corre antes del script: solo si el run sigue abierto.
    return ss.get("feedback") is not None and ss.get("run_id") is not None


# ─────────────────────────────── procesamiento ──────────────────────────────

def procesar(archivo_informe: UploadedFile, archivo_excel: UploadedFile,
             empresa: EmpresaAuditora) -> None:
    """Procesa el informe; ante cualquier falla deja ss.error_procesamiento para
    la pantalla de carga, que vuelve habilitada."""
    try:
        run_dir = crear_run_dir(settings.modelo_extraccion)
    except Exception as exc:  # noqa: BLE001 — se muestra al usuario
        ss.error_procesamiento = f"No se pudo crear el run: {type(exc).__name__}: {exc}"
        return
    # Se anota ahora, antes de procesar: tras el botón Stop Streamlit ya no
    # deja escribir el estado de la sesión, y el aviso se lee de su error.json.
    ss.ultimo_run = run_dir.name
    try:
        _procesar_en(run_dir, archivo_informe, archivo_excel, empresa)
    finally:
        # Mientras el run está en curso la retención no lo borra (tras Stop, la
        # etapa ya enviada sigue en su hilo y se puede iniciar otro).
        terminar_run(run_dir)


def _registrar_falla(run_dir: Path, exc: BaseException, tipo: str | None = None,
                     mensaje: str | None = None) -> None:
    """error.json del run (invariante 20) y el aviso para la pantalla de carga.
    El error.json va primero: tras un Stop, escribir el estado de la sesión (o
    dibujar) lanza StopException, y el aviso sale igual de ese archivo."""
    # "notas": si fallan dos etapas en paralelo, la segunda viaja como nota
    # (pipeline._persistir_checklist_y_e1) y no está en str(exc).
    notas = list(getattr(exc, "__notes__", []))
    # Disco lleno o carpeta borrada: el aviso en pantalla igual sale.
    with contextlib.suppress(OSError):
        guardar_json(run_dir, "error.json", {
            "tipo": tipo or type(exc).__name__,
            "mensaje": mensaje or str(exc),
            "notas": notas,
            "traceback": traceback.format_exc(),
            "fecha": datetime.now().isoformat(),
        })
    ss.error_procesamiento = (
        "\n\n".join([mensaje or f"{type(exc).__name__}: {exc}", *notas])
        + f"\n\nLos intermediates del run quedaron en "
        f"{run_dir.relative_to(settings.runs_dir.parent)}/ para diagnóstico."
    )


def _procesar_en(run_dir: Path, archivo_informe: UploadedFile, archivo_excel: UploadedFile,
                 empresa: EmpresaAuditora) -> None:
    try:
        if _empresa_sin_caracterizar(empresa):
            guardar_json(run_dir, "advertencias.json", {
                "empresa_sin_caracterizar": empresa.value,
                "detalle": "Catálogo placeholder: extracción sin hints específicos.",
            })
        es_docx = archivo_informe.name.lower().endswith(".docx")
        ruta_informe = run_dir / ("input.docx" if es_docx else "input.pdf")
        ruta_excel = run_dir / "input.xlsx"
        ruta_informe.write_bytes(archivo_informe.getvalue())
        ruta_excel.write_bytes(archivo_excel.getvalue())
        # Cadena de custodia: hash del archivo tal como se subió (el pipeline
        # hashea el PDF ya convertido/adecuado) + nombres originales.
        guardar_hash_input(run_dir, ruta_informe, "informe_original")
        guardar_json(run_dir, "inputs.json", {
            "informe": archivo_informe.name,
            "excel": archivo_excel.name,
        })
    except Exception as exc:  # noqa: BLE001 — p. ej. disco lleno: se muestra al usuario
        _registrar_falla(run_dir, exc)
        return

    st.caption("⏹ Para cancelar (p. ej. si te equivocaste de archivo), usa el "
               "botón **Stop** arriba a la derecha: la etapa ya enviada al "
               "modelo no se recupera, pero no se envía ninguna más. Después "
               "pulsa **R** (o ⋮ → *Rerun*) para volver a habilitar la pantalla.")
    t0 = time.monotonic()

    def _transcurrido() -> str:
        mm, ss = divmod(int(time.monotonic() - t0), 60)
        return f"{mm:02d}:{ss:02d}"

    adecuacion = None
    with st.status("Procesando informe... 00:00", expanded=True) as status:
        # Temporizador mm:ss (invariante 28): el label se actualiza en cada
        # etapa y cada línea de progreso queda timestampeada.
        def _progreso(etapa: str) -> None:
            status.update(label=f"Procesando informe... {_transcurrido()}")
            status.write(f"`{_transcurrido()}` {ETAPAS.get(etapa, etapa)}")

        try:
            ruta_pdf = ruta_informe
            conversion = None
            if es_docx:
                _progreso("convertir_docx")
                ruta_pdf, conversion = convertir_docx_a_pdf(ruta_informe, run_dir / "input.pdf")
                if conversion:
                    status.write(
                        f"⚠ {conversion['imagenes_omitidas']} imágenes del DOCX no se "
                        f"pudieron convertir ({', '.join(conversion['tipos_omitidos'])}); "
                        "quedan marcadas en el PDF como [IMAGEN NO CONVERTIBLE]."
                    )
            _progreso("adecuar_pdf")
            # Las citas se verifican contra el PDF con texto (misma paginación).
            ruta_pdf_texto = ruta_pdf
            ruta_pdf, adecuacion = adecuar_pdf_para_llm(ruta_pdf)
            if adecuacion:
                status.write(
                    f"⚠ El PDF supera el tamaño que acepta el modelo: se envían sus "
                    f"{adecuacion['paginas_enviadas']} páginas rasterizadas, sin recortar. "
                    "Las citas se verifican contra el PDF original (misma paginación)."
                )
            if adecuacion or conversion:
                guardar_json(run_dir, "adecuacion.json", {
                    **(adecuacion or {}),
                    **({"conversion": conversion} if conversion else {}),
                })

            reporte, _ = asyncio.run(ejecutar_pipeline(
                ruta_pdf=ruta_pdf, ruta_excel=ruta_excel, empresa_auditora=empresa,
                on_progreso=_progreso, run_dir=run_dir, ruta_pdf_texto=ruta_pdf_texto,
            ))
        except StopException as exc:
            # El botón Stop o una conexión cortada con el navegador (Streamlit no
            # los distingue). Tras el Stop ya no se puede dibujar nada: el aviso
            # queda para cuando la pantalla vuelva (R o ⋮ → Rerun).
            _registrar_falla(run_dir, exc, tipo="Detenido", mensaje=(
                "Procesamiento detenido: botón Stop o se cortó la conexión con el "
                "navegador. La etapa ya enviada al modelo terminó en segundo plano."))
            raise
        except Exception as exc:  # noqa: BLE001 — el error se muestra al usuario
            # Se muestra después del rerun que vuelve a habilitar la pantalla
            # (con los controles deshabilitados no habría cómo reintentar).
            # Antes de dibujar nada: con un Stop pendiente, dibujar lanzaría.
            _registrar_falla(run_dir, exc)
            status.update(label="El procesamiento falló", state="error")
            return
        status.update(label=f"Procesamiento completado en {_transcurrido()}",
                      state="complete")

    if abrir_feedback(run_dir.name):
        ss.reporte = reporte
        ss.run_id = run_dir.name
    else:
        ss.error_procesamiento += (
            f"\n\nEl procesamiento sí terminó y quedó guardado como {run_dir.name}: ábrelo "
            "desde «Procesamientos anteriores» en un momento; no hace falta volver a "
            "iniciarlo (sería otra corrida pagada).")


def _aviso_del_ultimo_run() -> tuple[str, str] | None:
    """Qué pasó con el último procesamiento de la sesión si no dejó su aviso:
    tras el botón Stop (o una conexión cortada) Streamlit no deja escribir el
    estado de la sesión, así que se lee del run. (nivel, texto) o None."""
    nombre = ss.get("ultimo_run")
    if not nombre:
        return None
    run = settings.runs_dir / nombre
    if (run / "reporte_final.json").exists():
        return None
    if en_curso(run):
        return ("info", "El procesamiento detenido está terminando en segundo plano la etapa "
                        "que ya se envió al modelo; su registro quedará en «Procesamientos "
                        "incompletos».")
    try:
        error = cargar_json(run / "error.json")
    except (OSError, ValueError):
        return None
    return ("error", "\n\n".join([
        f"{error.get('tipo', 'Error')}: {error.get('mensaje', 'sin detalle')}",
        *error.get("notas", []),
        f"Los intermediates del run quedaron en "
        f"{run.relative_to(settings.runs_dir.parent)}/ para diagnóstico.",
    ]))


# ───────────────────────────── pantalla de carga ────────────────────────────

def pantalla_carga() -> None:
    st.title("⚡ Comparador de Hallazgos")
    st.caption("Auditorías del Coordinador Eléctrico Nacional — "
               "PDF vs Excel + checklist de 38 puntos")

    # Dos fases: el clic en «Iniciar» solo registra el pedido y el rerun
    # siguiente procesa con los controles deshabilitados. Si siguieran activos,
    # tocar cualquiera mandaría un rerun que corta el procesamiento ya pagado
    # (revisión F6g); deshabilitados conservan la empresa y los archivos.
    pendiente: EmpresaAuditora | None = ss.pop("procesar_empresa", None)
    bloqueado = pendiente is not None
    if not bloqueado:
        if ss.get("error_procesamiento"):
            st.error(ss.error_procesamiento)
        elif aviso := _aviso_del_ultimo_run():
            (st.info if aviso[0] == "info" else st.error)(aviso[1])
    empresa_label = st.radio("Empresa auditora", list(EMPRESAS), horizontal=True,
                             disabled=bloqueado)
    if empresa_label and _empresa_sin_caracterizar(EMPRESAS[empresa_label]):
        st.warning(
            f"**{empresa_label} aún no está caracterizada en el catálogo**: la "
            "extracción corre sin hints específicos de su formato y puede ser "
            "menos precisa. Los resultados requieren revisión extra."
        )
    col1, col2 = st.columns(2)
    informe = col1.file_uploader("Informe técnico (PDF o DOCX)", type=["pdf", "docx"],
                                 disabled=bloqueado)
    excel = col2.file_uploader("Tabla de hallazgos (Excel)", type=["xlsx"], disabled=bloqueado)

    if st.button("Iniciar comparación", type="primary",
                 disabled=bloqueado or not (informe and excel and empresa_label)):
        assert empresa_label is not None
        ss.procesar_empresa = EMPRESAS[empresa_label]
        ss.error_procesamiento = ss.ultimo_run = None
        st.rerun()
    zona_procesamiento = st.container()
    _seccion_historial(bloqueado)

    if pendiente is not None:
        if informe is None or excel is None:
            ss.error_procesamiento = "Faltan los archivos: vuelve a subirlos."
        else:
            with zona_procesamiento:
                procesar(informe, excel, pendiente)
        # Con éxito abre el resultado; con error vuelve a la pantalla de carga
        # habilitada, con los archivos y la empresa conservados y el error a la vista.
        st.rerun()


def _seccion_historial(bloqueado: bool = False) -> None:
    todos = sorted(
        (d for d in settings.runs_dir.iterdir() if d.is_dir()),
        reverse=True,
    ) if settings.runs_dir.exists() else []
    runs = [d for d in todos if (d / "reporte_final.json").exists()]
    # Un run que corrió solo el checklist (medición) no es un procesamiento a medias.
    incompletos = [d for d in todos
                   if not (d / "reporte_final.json").exists() and not es_solo_checklist(d)]
    if not runs and not incompletos:
        return
    if runs:
        with st.expander(f"Procesamientos anteriores ({len(runs)})"):
            elegido = st.selectbox("Reabrir un run", [d.name for d in runs], index=None,
                                   disabled=bloqueado)
            if elegido and st.button("Abrir", disabled=bloqueado):
                data = cargar_json(settings.runs_dir / elegido / "reporte_final.json")
                try:
                    reporte = ReporteInforme.model_validate(data)
                except ValueError:
                    st.error("Ese run es de una versión incompatible del schema y no "
                             "puede abrirse.")
                    return
                ss.error_procesamiento = None
                if abrir_feedback(elegido):
                    ss.reporte, ss.run_id = reporte, elegido
                    ss.ultimo_run = None
                st.rerun()
    if incompletos:
        with st.expander(f"Procesamientos incompletos ({len(incompletos)})"):
            for run in incompletos[:10]:
                error_path = run / "error.json"
                if error_path.exists():
                    try:
                        error = cargar_json(error_path)
                    except (OSError, ValueError):
                        # Un archivo cortado (p. ej. un corte de luz) no puede
                        # impedir procesar: el historial se dibuja antes.
                        st.warning(f"{run.name}: error.json ilegible; revisar intermediates.")
                        continue
                    st.warning(" | ".join([
                        f"{run.name}: {error.get('tipo', 'Error')} - "
                        f"{error.get('mensaje', 'sin detalle')}",
                        *error.get("notas", []),
                    ]))
                else:
                    st.info(f"{run.name}: sin reporte_final.json; revisar intermediates.")


# ────────────────────────── pantalla de resultados ──────────────────────────

def _advertencia_adecuacion(r: ReporteInforme) -> None:
    """Advertencia durable si el PDF fue truncado: se lee del run (sobrevive
    reruns y cubre también los runs reabiertos desde el historial)."""
    run = settings.runs_dir / ss.run_id
    ruta_troceo = run / "troceo.json"
    if ruta_troceo.exists():
        t = cargar_json(ruta_troceo)
        ck = t.get("checklist") or {}
        e1 = t.get("descubrir_panos") or {}
        if ck:
            st.info(_aviso_checklist_por_partes(ck, r.checklist))
        if e1.get("advertencia"):
            st.warning(e1["advertencia"])
        elif e1.get("paginas_leidas"):
            a, b = e1["paginas_leidas"]
            st.info(
                f"Los paños se descubrieron leyendo las págs {a}-{b} de {e1['total_paginas']} "
                "(las tablas resumen van al inicio del informe). Si algún paño tiene su "
                "tabla resumen más adelante, sus filas del Excel aparecerán como 'extra'."
            )
    ruta = run / "adecuacion.json"
    if not ruta.exists():
        return
    a = cargar_json(ruta)
    conv = a.get("conversion")
    if conv:
        st.warning(
            f"**{conv['imagenes_omitidas']} imágenes del DOCX no se pudieron convertir** "
            f"({', '.join(conv['tipos_omitidos'])}) y quedaron marcadas en el PDF como "
            "[IMAGEN NO CONVERTIBLE]. Si contenían evidencia, revisarla en el DOCX original."
        )
    if a.get("truncado"):
        # Solo runs anteriores al 2026-10-18: desde entonces un informe que no
        # cabe falla con PdfExcedeLimitesError en vez de recortarse.
        st.warning(
            f"**El informe tiene {a['paginas_originales']} páginas y solo se "
            f"analizaron las primeras {a['paginas_enviadas']}** (límite de la "
            "API). Los hallazgos de las páginas restantes no entraron a la "
            "comparación: revisar esa sección a mano."
        )
    elif a.get("rasterizado"):
        st.caption(
            "ℹ El PDF fue rasterizado para cumplir los límites de la API; las "
            "citas de página refieren al archivo adecuado (misma paginación)."
        )


def _aviso_checklist_por_partes(ck: dict[str, Any], cl: ChecklistInforme | None) -> str:
    """Aviso general (M07) de un checklist leído por partes. Con la marca por punto
    de M08 (schema 0.8.0) remite a la columna «Lectura por partes»; un reporte
    anterior conserva el aviso de entonces. En los dos, todos los «cumple» se
    revisan (riesgo de anclaje)."""
    n = len(ck["tramos"])
    rangos = ", ".join(f"{a}-{b}" for a, b in (x["paginas"] for x in ck["tramos"]))
    if cl is None or cl.tramos_leidos is None:
        return (
            "Procesamiento anterior a la marca por punto de la lectura por partes. "
            f"El informe ({ck['total_paginas']} págs) no cabe completo en el contexto "
            f"del modelo: el checklist se evaluó en {n} tramos "
            f"(págs {rangos}) y se fusionó. Cada tramo ve solo una parte del informe: "
            "un 'cumple' puede venir de un solo tramo aunque el resto del informe no "
            "se haya revisado para ese punto, así que revisa todos los 'cumple' con "
            "más cuidado. Lo que falte en un tramo no lo da por incumplido: si la "
            "evidencia podría estar en otro tramo, queda 'no verificable'."
        )
    vistos = "vistos en una sola parte" if n == 2 else "que no se vieron en todas las partes"
    bajados = (
        " Además, los puntos que exigen revisar todo el informe y no se vieron en todas "
        "las partes pasaron a «no verificable», con las páginas a revisar."
        if cl.bajados_un_tramo else ""
    )
    return (
        f"El informe ({ck['total_paginas']} págs) no cabe completo en el contexto del "
        f"modelo: el checklist se evaluó en {n} partes (págs {rangos}) y se fusionó. "
        f"Los «cumple» {vistos} llevan el aviso en la columna «Lectura por partes», con "
        f"las páginas que no los respaldan.{bajados} Los demás «cumple» también se "
        "revisan, como siempre. Lo que falte en una parte no lo da por incumplido: si la "
        "evidencia podría estar en otra parte, queda 'no verificable'."
    )


def pantalla_resultados() -> None:
    r: ReporteInforme = ss.reporte

    izq, der = st.columns([5, 1])
    with izq:
        # Datos de terceros (vienen del Excel/PDF vía LLM): escapar siempre
        # antes de interpolar en HTML con unsafe_allow_html.
        st.markdown(
            f'<div class="header-cen"><h1>{html.escape(r.coordinado)} — '
            f'{html.escape(r.subestacion)}</h1>'
            f'<div class="meta">{html.escape(r.informe_id)} · '
            f'Auditoría: {r.empresa_auditora.value} · '
            f'{len({m.pano for m in _no_transversales(r)})} paños · '
            f'{len({m.rele for m in _no_transversales(r)})} relés · '
            f'{r.resumen.total} hallazgos analizados</div></div>',
            unsafe_allow_html=True,
        )
    if der.button("← Nuevo análisis"):
        ss.reporte = ss.run_id = ss.feedback = None
        st.rerun()

    _advertencia_adecuacion(r)
    _advertencia_columnas_excel(r)
    _advertencia_filas_ocultas(r)
    _tiles(r)
    _descargas(r)
    _guia(r)
    if r.checklist:
        _checklist(r)
    _resultados_por_pano(r)
    _seccion_transversales(r)
    _comentarios()


def _no_transversales(r: ReporteInforme) -> list[MatchResult]:
    """Resultados del matching real: las filas transversales van aparte."""
    return [m for m in r.resultados if m.estado != EstadoHallazgo.TRANSVERSAL]


def _advertencia_columnas_excel(r: ReporteInforme) -> None:
    if r.columnas_ausentes_excel:
        cols = ", ".join(r.columnas_ausentes_excel)
        st.warning(
            f"El Excel no trae las columnas: **{cols}**. El formato regulatorio "
            "debe traerlas (confirmado por la revisora, 2026-07-16) — pedir a la "
            "auditora el Excel completo. Esos campos no se compararon."
        )


def _advertencia_filas_ocultas(r: ReporteInforme) -> None:
    n = r.resumen.filas_excel_ocultas
    if n:
        st.warning(
            f"**{n} {'fila' if n == 1 else 'filas'} del Excel** con hallazgos "
            f"{'está oculta' if n == 1 else 'están ocultas'} en el archivo (filtro activo u "
            "ocultadas a mano): al abrirlo no se ven. Quita el filtro para revisarlas; el "
            "detalle de cada hallazgo indica si su fila está oculta."
        )


def _tiles(r: ReporteInforme) -> None:
    res = r.resumen
    sub_coinciden = (
        f"{res.coinciden_con_redaccion_distinta} con redacción distinta"
        if res.coinciden_con_redaccion_distinta else ""
    )
    tiles: list[tuple[str, str, object, str]] = [
        ("t-total", "Total", res.total, ""),
        ("t-ok", "Coinciden", res.coinciden, sub_coinciden),
        ("t-dif", "Difieren", res.difieren, ""),
        ("t-falta", "🔴 Falta en Excel", res.faltan_en_excel, ""),
        ("t-extra", "🟠 Falta en el PDF", res.extra_en_excel, ""),
    ]
    if res.transversales:
        tiles.append(("t-trans", "⚪ Transversales", res.transversales, ""))
    if r.checklist:
        cl = r.checklist
        sin_cita, marcados, bajados = (
            cl.bajados_sin_cita_verificada, cl.marcados_un_tramo, cl.bajados_un_tramo)
        sub_check = " · ".join(texto for texto in (
            f"{sin_cita} «cumple» sin cita verificada" if sin_cita else "",
            f"{marcados} {'visto' if marcados == 1 else 'vistos'} solo en parte del informe"
            if marcados else "",
            f"{bajados} {'bajado' if bajados == 1 else 'bajados'} por lectura en partes"
            if bajados else "",
        ) if texto)
        tiles.append(("t-check", "Checklist", f"{cl.cumplen}/{cl.total}", sub_check))
    celdas = "".join(
        f'<div class="tile {clase}"><div class="lbl">{lbl}</div>'
        f'<div class="val">{val}</div>'
        + (f'<div class="sub">{sub}</div>' if sub else "")
        + "</div>"
        for clase, lbl, val, sub in tiles
    )
    st.markdown(f'<div class="tiles">{celdas}</div>', unsafe_allow_html=True)


def _descargas(r: ReporteInforme) -> None:
    c1, c2, c3 = st.columns(3)
    c1.download_button("⬇ Excel", exportar_xlsx(r), file_name=f"comparacion_{ss.run_id}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    c2.download_button("⬇ CSV", exportar_csv(r), file_name=f"comparacion_{ss.run_id}.csv",
                       mime="text/csv")
    run_id = ss.run_id
    c3.download_button("⬇ Feedback (.md)", lambda: _md_al_clic(r, run_id),
                       file_name=f"feedback_{run_id}.md", mime="text/markdown")


# Un texto se guarda al salir del campo, y el clic en la descarga es justo lo
# que lo hace salir: el navegador pide el archivo en paralelo con el rerun que
# guarda el texto (Streamlit 1.59 no los ordena). La espera deja que el
# callback de ese rerun guarde primero; el .md se lee recién después.
ESPERA_DESCARGA_S = 0.8


def _md_al_clic(r: ReporteInforme, run_id: str) -> str:
    time.sleep(ESPERA_DESCARGA_S)
    return exportar_feedback_guardado(r, run_id)


def _checklist(r: ReporteInforme) -> None:
    cl = r.checklist
    assert cl is not None
    con_alerta = " ⚠️" if any(i.resultado == ResultadoChecklist.NO_CUMPLE for i in cl.items) else ""
    with st.expander(f"Checklist de aprobación · {cl.cumplen}/{cl.total} cumplen{con_alerta}",
                     expanded=bool(con_alerta)):
        claves = [str(i.numero) for i in cl.items]
        columnas: dict[str, list[Any]] = {
            "N°": [i.numero for i in cl.items],
            "Punto": [i.enunciado for i in cl.items],
            "Resultado": [_resultado_checklist(i) for i in cl.items],
            "Páginas": [i.paginas or "—" for i in cl.items],
        }
        # Columna de M08 solo si el informe se leyó por partes (schema 0.8.0);
        # el aviso lo escribe el backend.
        if cl.tramos_leidos is not None:
            columnas["Lectura por partes"] = [i.aviso_tramos or "—" for i in cl.items]
        # Columna de la cita solo si el procesamiento la pidió (CITA_CHECKLIST).
        if cl.bajados_sin_cita_verificada is not None:
            columnas["Cita"] = [_texto_citas(i) for i in cl.items]
        columnas["Referencia / Observación"] = [i.referencia or "—" for i in cl.items]
        # Feedback anterior (✓/✗ sobre el resultado): solo lectura, si lo hay.
        if ss.feedback.veredictos_checklist:
            columnas["Feedback anterior"] = [
                _STR_A_V.get(ss.feedback.veredictos_checklist.get(k, ""), "—") for k in claves]
        respuestas = ss.feedback.respuestas_checklist
        base = ss.setdefault(_clave_base_checklist(ss.run_id), dict(respuestas))
        columnas["Tu respuesta"] = [base.get(k, SIN_RESPUESTA) for k in claves]
        key = f"checklist_{ss.run_id}"
        st.data_editor(
            pd.DataFrame(columnas), hide_index=True, use_container_width=True,
            key=key, on_change=_al_editar_checklist, args=(key, claves),
            column_config={
                "Punto": st.column_config.TextColumn(width="large"),
                "Lectura por partes": st.column_config.TextColumn(width="large"),
                "Cita": st.column_config.TextColumn(width="large"),
                "Tu respuesta": st.column_config.SelectboxColumn(
                    options=RESPUESTAS_CHECKLIST, width="small", required=True,
                    help="Tu veredicto, como en la planilla: SI, NO o N/A"),
            },
            disabled=[c for c in columnas if c != "Tu respuesta"],
        )
        if cl.bajados_sin_cita_verificada is None:
            st.caption("Este procesamiento no pidió citas: sus «cumple» no están verificados "
                       "contra el PDF.")
        _evidencia_de_un_punto(cl.items)


def _al_editar_checklist(key: str, claves: list[str]) -> None:
    """La columna «Tu respuesta»: la base fija del run con las ediciones de la
    grilla encima (el widget las acumula mientras el run está abierto)."""
    if not _hay_run_abierto():
        return
    base = ss.get(_clave_base_checklist(ss.run_id), {})
    valores: list[object] = [base.get(k, SIN_RESPUESTA) for k in claves]
    for fila, cambios in ss[key].get("edited_rows", {}).items():
        if "Tu respuesta" in cambios:
            valores[int(fila)] = cambios["Tu respuesta"]
    if feedback.aplicar_respuestas(valores, ss.feedback.respuestas_checklist, claves):
        guardar_feedback()


def _resultado_checklist(item: ItemChecklist) -> str:
    texto = RESULTADO_CHECKLIST[item.resultado.value]
    if item.resultado_modelo is not None:
        texto += f" (el modelo dijo {RESULTADO_CHECKLIST[item.resultado_modelo.value]})"
    return texto


def _texto_citas(item: ItemChecklist) -> str:
    if not item.citas:
        return item.motivo_ajuste or "—"
    return " · ".join(
        f"{ICONO_CITA[c.verificacion.estado.value] if c.verificacion else ''} «{c.texto}» "
        f"({etiqueta_verificacion(c.verificacion)})"
        for c in item.citas
    )


def _evidencia_de_un_punto(items: list[ItemChecklist]) -> None:
    """Selector de un punto y su evidencia en el PDF (st.data_editor no
    permite seleccionar filas)."""
    opciones = {f"{i.numero}. {i.enunciado[:90]}": i for i in items}
    if not opciones:
        return
    eleccion = st.selectbox(
        "Ver la evidencia de un punto en el PDF", list(opciones), index=None,
        placeholder="Elige un punto", key=f"evidencia_checklist_{ss.run_id}",
    )
    if eleccion is None:
        return
    item = opciones[eleccion]
    if item.motivo_ajuste:
        st.warning(item.motivo_ajuste)
    if item.aviso_tramos:
        st.warning(item.aviso_tramos)
    for c in item.citas:
        st.info(f"**Cita:** {c.texto}")
        st.caption(f"{ICONO_CITA[c.verificacion.estado.value] if c.verificacion else ''} "
                   f"{etiqueta_verificacion(c.verificacion)}")
    st.caption(ALCANCE_EVIDENCIA)
    _visor(paginas_citas(item.citas), paginas_texto=item.paginas,
           clave=f"pagina_checklist_{ss.run_id}_{item.numero}", recorrer=True)


def _marca_feedback(clave: str) -> str:
    return {"correcto": "✓", "incorrecto": "✗"}.get(
        ss.feedback.veredictos_resultados.get(clave, ""), "—")


GUIA_ESTADOS = (
    "Cada hallazgo termina en uno de cinco **estados**, ordenados por gravedad:\n\n"
    "| Estado | Qué significa | Gravedad |\n"
    "|---|---|---|\n"
    "| ✅ Coincide | El hallazgo está en ambos lados y sus campos calzan. | — |\n"
    "| ✅ Coincide · redacción distinta | Variante de Coincide: la descripción o "
    "la acción quedó bajo el umbral de similitud, pero el **juez de redacción** "
    "(LLM) concluyó que dice lo mismo con otras palabras (el Excel parafrasea el "
    "PDF). | **Validar** la equivalencia en el detalle; ✗ si en realidad "
    "difiere. |\n"
    "| 🟡 Difiere | Está en ambos lados, pero algún campo no coincide "
    "(descripción, acción correctiva o calificación). Si un lado dice que "
    "**cumple** y el otro que **no cumple**, siempre es Difiere (control de "
    "polaridad). | Revisar los campos. |\n"
    "| 🟠 Falta en el PDF | Está en el Excel sin respaldo visible en el PDF. | "
    "**Informativo** — no es grave, pero conviene saberlo. |\n"
    "| 🔴 FALTA EN EXCEL | Está en el PDF y no en el Excel: **no llegaría al "
    "regulador**. | **Grave** — el Excel manda. |\n"
    "| ⚪ Transversal | Fila del Excel sin relé específico (ej. \"Análisis de "
    "coordinación\"): no entra al matching, tiene su propia sección. | "
    "**Revisión manual**. |\n"
)

GUIA_DIFIERE = (
    "\n**Cómo leer un 🟡 Difiere en la columna Comentario.** Después de los dos "
    "puntos van los campos que no coinciden, en el orden descripción → acción "
    "correctiva → calificación, separados por «·». Entre paréntesis, por qué:\n\n"
    "| Lo que ves | Qué significa |\n"
    "|---|---|\n"
    "| Calificación: Menor vs Relevante | El PDF dice **Menor** y el Excel "
    "**Relevante** (siempre primero el PDF). |\n"
    "| … (Cumple vs No cumple) | Un lado dice que cumple y el otro que no. Siempre es "
    "Difiere, sin IA. |\n"
    "| … (código o número distinto) | Los textos son casi iguales, pero cambia un "
    "código o número (p. ej. «50N» en el PDF y «67N» en el Excel). Sin IA. |\n"
    "| … (contenido distinto) | Los textos se parecen poco y el juez de redacción (IA) "
    "concluyó que no dicen lo mismo. |\n"
    "| … (textos poco parecidos) | Los textos se parecen poco y no pasaron por el juez "
    "de redacción (por ejemplo, porque el emparejamiento es dudoso). |\n"
    "| … (vacío en un lado) | El campo tiene texto en un archivo y está vacío en el "
    "otro. |\n"
    "| … (sin comparar: revisar) | No se pudo medir el parecido; revisar a mano. |\n"
    "| (revisar) al inicio | El emparejamiento es dudoso: confirmar primero que esa "
    "fila del Excel es la de este hallazgo. |\n\n"
    "Los dos textos completos y el motivo con detalle (por ejemplo, qué código "
    "cambió) están al abrir el hallazgo, en **Diferencias detectadas**.\n"
)

GUIA_CONFIANZA_TIPOS = (
    "**Confianza** = qué tan seguro está el sistema de que emparejó el hallazgo "
    "correcto (que este hallazgo del PDF corresponde a ese del Excel). Es sobre "
    "el *emparejamiento*, no sobre el contenido.\n\n"
    '**"Difiere"** = ya emparejados, sus campos no coinciden. Un *"Difiere · '
    'conf 0.72"* se lee: *"el juez ubicó este par en la banda 0.65–0.79 de su '
    'rúbrica: probablemente son el mismo hallazgo, con una ambigüedad concreta; '
    'y una vez emparejados, algún campo difiere"*. La confianza **ordena qué '
    "mirar primero**; no es la probabilidad de que el par esté bien.\n\n"
    '| Tipo de match | Confianza | Cómo interpretar un "Difiere" |\n'
    "|---|---|---|\n"
    "| 🟦 **U** — único por clasificación | 1.00 | Emparejamiento **seguro** "
    "(única clasificación en la tupla paño/relé, sin LLM): el par es el mismo "
    "hallazgo. La diferencia hay que mirarla: puede ser de contenido o solo de "
    "redacción. |\n"
    "| 🟩 **=** — descripción idéntica | 1.00 | Emparejamiento **seguro**: la misma "
    "descripción en el PDF y el Excel de la tupla, sin LLM (con varias filas iguales, "
    "repartidas por acción correctiva). Si difiere, la diferencia está en la acción o "
    "en la calificación. |\n"
    "| 🟪 **~** — semántico, confianza alta | ≥ 0.80 | El juez ubicó el par en "
    "la banda alta de su rúbrica: el emparejamiento es confiable. La diferencia "
    "hay que mirarla igual que en U. |\n"
    "| 🟨 **?** — semántico, confianza baja | 0.50 – 0.79 | Emparejamiento "
    "**dudoso**: puede que difiera porque en realidad **no son el mismo "
    "hallazgo**. Primero confirmar el emparejamiento en el detalle; recién ahí "
    "la diferencia tiene sentido. |\n"
    "| 🟥 **!** — sin match | — | No se encontró par: 🔴 *Falta en Excel* o "
    "🟠 *Falta en el PDF*. |\n\n"
)
# Solo en un reporte con algún par con emparejamiento_dudoso (schema 0.9.0,
# asignación global: PD71); con la asignación apagada no puede aparecer.
GUIA_EMPAREJAMIENTO_DUDOSO = (
    "Un 🟪 **~** también puede salir **(revisar)**, como un 🟨 **?**: cuando otro "
    "hallazgo del PDF que dice lo contrario (cumple / no cumple) también podía "
    "corresponder a esa fila del Excel. El detalle dice cuál es y, si se conoce, en qué "
    "página.\n\n"
)
GUIA_CONFIANZA_RUBRICA = (
    'En resumen: un "Difiere" con 🟦 U es lo más accionable (el emparejamiento '
    'no puede estar mal; queda ver si la diferencia es de contenido o de '
    'redacción); un "Difiere" con 🟨 ? '
    "**no es necesariamente una inconsistencia del auditor** — puede ser un "
    "emparejamiento equivocado del sistema.\n\n"
    "El número no es libre: el juez asigna la confianza siguiendo una **rúbrica "
    "anclada** con criterios del dominio, y ante duda debe elegir el rango "
    "inferior. Es una **banda relativa** para ordenar la revisión, no una "
    "probabilidad medida:\n\n"
    "| Rango | Criterio |\n"
    "|---|---|\n"
    "| 0.90+ | Mismo problema en el mismo equipo; solo cambia la redacción o el "
    "nivel de detalle. |\n"
    "| 0.80 – 0.89 | Mismo problema de fondo, descrito desde otro ángulo (p. ej. "
    "síntoma vs. causa). |\n"
    "| 0.65 – 0.79 | Probablemente el mismo, pero con una ambigüedad concreta: "
    "alcance, componente o acción no calzan del todo. |\n"
    "| 0.50 – 0.64 | Dudoso: comparten tema, pero podría ser otro hallazgo del "
    "mismo equipo. |\n"
    "| < 0.50 | No se empareja — queda como faltante/extra. |\n"
)

ALCANCE_EVIDENCIA = ("La página respalda la respuesta del sistema, pero no descarta que el "
                     "informe diga algo distinto en otra parte.")

GUIA_CHECKLIST = (
    "Antes de comparar, el sistema verifica que el informe cumpla los **38 "
    "puntos regulatorios** de aprobación, leyendo el PDF completo:\n\n"
    "- ✅ **Cumple** — hay evidencia en el informe. Cuando el procesamiento pide citas "
    "(por defecto), cada «cumple» trae su **cita** y el sistema comprueba que esté "
    "escrita en la página indicada; un «cumple» cuya cita no aparece, es muy corta, "
    "está en varias páginas o en una página que es una imagen pasa a **no "
    "verificable**, con el motivo a la vista.\n"
    "- ❌ **No cumple** — el punto falta o la evidencia lo contradice.\n"
    "- ➖ **No verificable** — el sistema no encontró evidencia suficiente para "
    "decidir; **revisar a mano**, no significa que esté mal.\n"
    "- 📑 **Informes largos** — si el informe no cabe completo en el modelo, el checklist "
    "se lee **por partes** y se fusiona. Un «cumple» que no respaldan todas las partes "
    "lleva el aviso en la columna **Lectura por partes**, con las páginas que no lo "
    "respaldan: revísalas antes de darlo por cumplido. Según la configuración del "
    "procesamiento, los puntos que exigen revisar todo el informe pasan además a **no "
    "verificable**, con las páginas a revisar. Los demás «cumple» se revisan como "
    "siempre.\n"
    "- 📄 **Ver la evidencia** — la página citada respalda la respuesta del sistema, "
    "pero no descarta que el informe diga algo distinto en otra parte. Con **Recorrer "
    "el PDF completo** puedes ir a las páginas vecinas, a cualquier página o descargar "
    "el PDF del informe (el convertido, si llegó en Word).\n\n"
    "El resultado es informativo: no bloquea la comparación. La decisión de "
    "aprobar es siempre de la revisora."
)

GUIA_CITAS = (
    "Cada hallazgo del PDF trae su **página**, y la herramienta comprueba por código "
    "que la **descripción** y la **acción** estén escritas tal cual en esa página:\n\n"
    "- ✅ **verificada**: el texto está en la página (o sigue en la siguiente, cuando "
    "una fila de la tabla se parte).\n"
    "- ↪️ **está en otra página**: el texto está en otra página del mismo paño; se usa "
    "esa página y se indica la que dio el modelo. Si aparece en **varias** páginas y "
    "no en la citada, no se adivina: queda como no verificada.\n"
    "- ⚠️ **no aparece**: la página tiene texto, pero no ese. El modelo pudo alterar o "
    "resumir el texto: **revisar a mano**.\n"
    "- 👁️ **sin texto**: la página es una imagen (escaneada, un diagrama): confirmar a "
    "la vista.\n\n"
    "Que el texto esté en la página **no confirma** el paño, el relé ni la calificación. "
    "Con **Ver en el PDF** se muestra la página con la descripción resaltada en amarillo "
    "y la acción en celeste.\n\n"
    "Del **Excel** se indica la hoja y la fila, y se avisa si la fila está oculta por un "
    "filtro. Si el informe llegó en Word, las páginas son las del PDF convertido, que no "
    "coinciden con la paginación de Word."
)
# Solo en un reporte con algún hallazgo del PDF que nombra a otro relé (schema 0.10.0,
# PD60); un reporte anterior no lo revisó.
GUIA_OTROS_RELES = (
    "\n\n- ℹ️ **Nombra a otro relé**: cuando la descripción o la acción de un hallazgo del "
    "PDF nombran a otro relé de su tabla, el detalle lo avisa y la descarga los lista en la "
    "columna *Otros relés nombrados (PDF)*. Pasa cuando el informe pone en una sola viñeta "
    "lo de varios relés: se copió entera a cada relé y se comparó entera con la fila del "
    "Excel. Si el Excel la repartió entre relés, la diferencia puede venir solo de eso. Es "
    "un aviso: no cambia el estado del hallazgo."
)

GUIA_FEEDBACK = (
    "En cada punto del checklist anota **tu respuesta** (SI, NO o N/A, como en la "
    "planilla) y en cada hallazgo marca si el sistema **acertó (✓)** o **se "
    "equivocó (✗)**; con ✗, elige qué falló. Al final hay un campo de comentarios "
    "generales. Todo se guarda solo, en una carpeta propia que la limpieza de "
    "procesamientos antiguos no borra, y se descarga como Markdown (*⬇ Feedback*), "
    "que marca dónde tu respuesta contradice al sistema. Envíalo al equipo de "
    "desarrollo: sirve para medir y corregir el sistema. Hoy nada se ajusta solo "
    "con tus respuestas."
)


def _guia(r: ReporteInforme) -> None:
    dudoso = any(m.emparejamiento_dudoso is not None for m in r.resultados)
    otros_reles = any(m.hallazgo_pdf and m.hallazgo_pdf.evidencia.otros_reles_nombrados
                      for m in r.resultados)
    with st.expander("📖 Guía de lectura — estados, confianza, citas, checklist y feedback"):
        tabs = st.tabs(["Estados", "Match y confianza", "Citas", "Checklist", "Feedback"])
        with tabs[0]:
            st.markdown(GUIA_ESTADOS + GUIA_DIFIERE)
        with tabs[1]:
            st.markdown(GUIA_CONFIANZA_TIPOS + (GUIA_EMPAREJAMIENTO_DUDOSO if dudoso else "")
                        + GUIA_CONFIANZA_RUBRICA)
        with tabs[2]:
            st.markdown(GUIA_CITAS + (GUIA_OTROS_RELES if otros_reles else ""))
        with tabs[3]:
            st.markdown(GUIA_CHECKLIST)
        with tabs[4]:
            st.markdown(GUIA_FEEDBACK)


def _resultados_por_pano(r: ReporteInforme) -> None:
    st.subheader("Hallazgos por paño")
    st.caption(
        "🟦 U seguro · 🟩 = descripción idéntica · 🟪 ~ confianza alta · "
        "🟨 ? confianza baja (revisar) · "
        "🟥 ! sin match — detalles en la guía de lectura. "
        "Marca la casilla a la izquierda de una fila para ver el detalle y dejar tu feedback."
    )

    # Las filas transversales tienen su propia sección: no entran ni a los
    # grupos por paño ni a las opciones de los filtros.
    matcheables = _no_transversales(r)
    estados = ["Todos"] + sorted({m.estado.value for m in matcheables})
    fcol1, fcol2, fcol3 = st.columns(3)
    filtro_estado = fcol1.selectbox("Estado", estados)
    panos = sorted({m.pano for m in matcheables})
    filtro_pano = fcol2.selectbox("Paño", ["Todos"] + panos)
    reles = sorted({m.rele for m in matcheables})
    filtro_rele = fcol3.selectbox("Relé", ["Todos"] + reles)

    # Expandir/colapsar todo (DISENO §9.1): override por run; None = default.
    exp_key = f"exp_override_{ss.run_id}"
    ss.setdefault(exp_key, None)
    bcol1, bcol2, _ = st.columns([1, 1, 4])
    if bcol1.button("Expandir todo"):
        ss[exp_key] = True
    if bcol2.button("Colapsar todo"):
        ss[exp_key] = False

    for pano in panos:
        if filtro_pano != "Todos" and pano != filtro_pano:
            continue
        grupo = [(i, m) for i, m in enumerate(r.resultados)
                 if m.pano == pano
                 and m.estado != EstadoHallazgo.TRANSVERSAL
                 and (filtro_estado == "Todos" or m.estado.value == filtro_estado)
                 and (filtro_rele == "Todos" or m.rele == filtro_rele)]
        if not grupo:
            continue

        titulo = _titulo_pano(pano, [m for _, m in grupo])

        # Colapso inicial (DISENO §9.1): colapsado solo si todo coincide.
        expandido_default = any(m.estado != EstadoHallazgo.COINCIDE for _, m in grupo)
        expandido = ss[exp_key] if ss[exp_key] is not None else expandido_default

        with st.expander(titulo, expanded=expandido):
            df = pd.DataFrame({
                "#": [n for n, _ in enumerate(grupo, 1)],
                "Match": [BADGE_MATCH.get(m.tipo_match.value, "?") for _, m in grupo],
                "Relé": [m.rele for _, m in grupo],
                "Hallazgo": [_desc(m) for _, m in grupo],
                "PDF": ["✓" if m.hallazgo_pdf else "✗" for _, m in grupo],
                "Excel": ["✓" if m.hallazgo_excel else "✗" for _, m in grupo],
                "Conf.": ["—" if m.tipo_match.value == "sin_match" else f"{m.confianza:.2f}"
                          for _, m in grupo],
                "Comentario": [_comentario(m) for _, m in grupo],
                "Evidencia": [_evidencia(m) for _, m in grupo],
                "Feedback": [_marca_feedback(str(i)) for i, _ in grupo],
            })
            seleccion = st.dataframe(
                df, hide_index=True, use_container_width=True,
                # Los filtros en la key resetean la selección al filtrar: una
                # selección que sobrevive con datos distintos abriría el
                # detalle de OTRO hallazgo (o un IndexError).
                key=f"tabla_{ss.run_id}_{pano}_{filtro_estado}_{filtro_rele}",
                on_select="rerun", selection_mode="single-row",
                column_config={"Hallazgo": st.column_config.TextColumn(width="large")},
            )
            filas = seleccion["selection"]["rows"]
            if filas:
                _detalle(grupo[filas[0]])


def _seccion_transversales(r: ReporteInforme) -> None:
    """Filas del Excel sin relé específico: fuera del matching, revisión manual."""
    grupo = [(i, m) for i, m in enumerate(r.resultados)
             if m.estado == EstadoHallazgo.TRANSVERSAL]
    if not grupo:
        return

    with st.expander(
        f"⚪ Filas transversales del Excel · {len(grupo)} · revisión manual",
        expanded=False,
    ):
        st.caption(
            "Filas tipo \"Análisis de coordinación\" que no pertenecen a un "
            "relé específico (según el catálogo de la empresa). No entran al "
            "matching — revisarlas a mano contra el informe."
        )
        df = pd.DataFrame({
            "#": [n for n, _ in enumerate(grupo, 1)],
            "Paño(s)": [m.pano for _, m in grupo],
            "Fila": [m.rele for _, m in grupo],
            "Hallazgo": [_desc(m) for _, m in grupo],
            "Evidencia": [_evidencia(m) for _, m in grupo],
            "Feedback": [_marca_feedback(str(i)) for i, _ in grupo],
        })
        seleccion = st.dataframe(
            df, hide_index=True, use_container_width=True,
            key=f"tabla_transversales_{ss.run_id}",
            on_select="rerun", selection_mode="single-row",
            column_config={"Hallazgo": st.column_config.TextColumn(width="large")},
        )
        filas = seleccion["selection"]["rows"]
        if filas:
            _detalle(grupo[filas[0]])


def _cita(nombre: str, texto: str, v: VerificacionCita | None) -> None:
    st.info(f"**{nombre}:** {texto}")
    if v is not None:
        st.caption(f"{ICONO_CITA[v.estado.value]} {etiqueta_verificacion(v)}")


def _detalle(item: ItemGrupo) -> None:
    idx, m = item
    st.markdown(f"##### Detalle — {m.pano} · {m.rele}")
    c1, c2 = st.columns(2)
    with c1:
        if m.hallazgo_pdf:
            h = m.hallazgo_pdf
            ev = h.evidencia
            st.markdown(f"**PDF** — página {ev.pagina_pdf}" if ev.pagina_pdf else "**PDF**")
            _cita("Descripción", h.descripcion, ev.verificacion_descripcion)
            if h.accion_correctiva:
                _cita("Acción correctiva", h.accion_correctiva, ev.verificacion_accion)
            if ev.verificacion_descripcion is None:
                st.caption("Procesamiento anterior a la verificación de citas: este texto no "
                           "está comprobado contra el PDF.")
            else:
                st.caption("Verificar el texto confirma la página; no confirma paño, relé "
                           "ni calificación.")
            if ev.otros_reles_nombrados:
                if not m.hallazgo_excel:
                    aviso = AVISO_OTROS_RELES_SIN_FILA
                elif m.estado == EstadoHallazgo.COINCIDE:
                    aviso = AVISO_OTROS_RELES_COINCIDE
                else:
                    aviso = AVISO_OTROS_RELES
                st.info(aviso.format(reles=", ".join(ev.otros_reles_nombrados)), icon="ℹ️")
            st.caption(f"Texto que extrajo el modelo (puede unir celdas; no es una cita "
                       f"literal): {ev.texto_crudo}")
        else:
            st.markdown("**PDF**")
            st.warning("No presente en PDF")
    with c2:
        if m.hallazgo_excel:
            ev = m.hallazgo_excel.evidencia
            donde = (f"hoja «{ev.hoja_excel}», fila {ev.fila_excel}" if ev.hoja_excel
                     else f"fila {ev.fila_excel}")
            st.markdown(f"**Excel** — {donde}" if ev.fila_excel else "**Excel**")
            if ev.fila_oculta:
                st.warning("Esta fila está **oculta** en el Excel (filtro activo u ocultada a "
                           "mano): quita el filtro para verla.")
            st.info(ev.texto_crudo)
        else:
            st.markdown("**Excel**")
            st.warning("No presente en Excel")

    if m.hallazgo_pdf and m.hallazgo_pdf.evidencia.pagina_pdf:
        pagina = m.hallazgo_pdf.evidencia.pagina_pdf
        if st.toggle(f"Ver en el PDF (página {pagina})", key=f"visor_{ss.run_id}_{idx}"):
            _visor(paginas_hallazgo(m.hallazgo_pdf), clave=f"pagina_visor_{ss.run_id}_{idx}")

    # Caja con borde lateral (DISENO §9.1): amarillo si el emparejamiento es
    # dudoso, gris si no. La justificación viene del LLM: siempre escapar.
    st.markdown(
        f'<div class="justif{" warn" if m.emparejamiento_es_dudoso else ""}">'
        f'<b>Justificación del match:</b> {html.escape(m.justificacion)}</div>',
        unsafe_allow_html=True,
    )
    confianza = f"{m.confianza:.2f}"
    st.caption(
        INTERPRETACION_EMPAREJAMIENTO_DUDOSO.format(c=confianza, motivo=m.emparejamiento_dudoso)
        if m.emparejamiento_dudoso is not None
        else INTERPRETACION_MATCH[m.tipo_match.value].format(c=confianza)
    )

    if m.diferencias:
        st.markdown("**Diferencias detectadas** (por qué se marca 🟡 Difiere):")
        for d in m.diferencias:
            linea = (f"- **{ETIQUETA_CAMPO[d.campo.value]}** — "
                     f"PDF: {d.valor_pdf or '(vacío)'} · Excel: {d.valor_excel or '(vacío)'}")
            if d.detalle:
                linea += f"  \n  ↳ _{d.detalle}_"
            st.markdown(linea)

    if m.equivalencias_redaccion:
        st.markdown("**Coincide con redacción distinta** — campos bajo el umbral de "
                    "similitud que el juez de redacción declaró con el mismo contenido:")
        for e in m.equivalencias_redaccion:
            st.markdown(
                f"- **{ETIQUETA_CAMPO[e.campo.value]}** — similitud {e.similitud:.2f}"
                f"  \n  PDF: {e.valor_pdf}  \n  Excel: {e.valor_excel}"
                f"  \n  ↳ _Juez de redacción: {e.justificacion}_"
            )
        st.caption("Es una decisión automática del juez de redacción (LLM), no una "
                   "coincidencia literal. Si el contenido en realidad difiere, marca ✗ "
                   "en «¿El sistema acertó en este hallazgo?».")

    # El feedback se guarda en callbacks (on_change): Streamlit los corre antes
    # del script, así un cambio no se pierde si el mismo rerun sale de la
    # pantalla o deja de dibujar el widget, y todo lo que se dibuja ya lo ve.
    clave = str(idx)
    key = f"fb_{ss.run_id}_{idx}"
    actual = _STR_A_V.get(ss.feedback.veredictos_resultados.get(clave, ""), VEREDICTOS[0])
    st.radio("¿El sistema acertó en este hallazgo?", VEREDICTOS,
             index=VEREDICTOS.index(actual), horizontal=True, key=key,
             on_change=_al_cambiar_veredicto, args=(clave, key))
    if ss.feedback.veredictos_resultados.get(clave) == "incorrecto":
        _motivo_incorrecto(clave, idx)


def _al_cambiar_veredicto(clave: str, key: str) -> None:
    if not _hay_run_abierto():
        return
    nuevo = _V_A_STR.get(ss[key])
    if nuevo:
        ss.feedback.veredictos_resultados[clave] = nuevo
    else:
        ss.feedback.veredictos_resultados.pop(clave, None)
    if nuevo != "incorrecto":
        ss.feedback.motivos_resultados.pop(clave, None)
    guardar_feedback()


def _motivo_incorrecto(clave: str, idx: int) -> None:
    """Con ✗: qué falló (para medir dónde se equivoca el sistema)."""
    actual = ss.feedback.motivos_resultados.get(clave) or MotivoFeedback()
    opciones = list(MotivoIncorrecto)
    claves = (clave, f"motivo_{ss.run_id}_{idx}", f"detalle_{ss.run_id}_{idx}")
    st.selectbox(
        "¿Qué falló?", opciones, format_func=lambda m: feedback.ETIQUETA_MOTIVO[m],
        index=opciones.index(actual.motivo) if actual.motivo else None,
        placeholder="Elige el motivo", key=claves[1],
        on_change=_al_cambiar_motivo, args=claves,
    )
    st.text_input("Detalle (opcional)", value=actual.detalle, max_chars=200, key=claves[2],
                  on_change=_al_cambiar_motivo, args=claves)


def _al_cambiar_motivo(clave: str, key_motivo: str, key_detalle: str) -> None:
    # Si el mismo rerun pasó el veredicto a ✓, el motivo ya no corresponde.
    if not _hay_run_abierto() or ss.feedback.veredictos_resultados.get(clave) != "incorrecto":
        return
    nuevo = MotivoFeedback(motivo=ss.get(key_motivo),
                           detalle=(ss.get(key_detalle) or "").strip())
    if nuevo == MotivoFeedback():
        ss.feedback.motivos_resultados.pop(clave, None)
    else:
        ss.feedback.motivos_resultados[clave] = nuevo
    guardar_feedback()


def _comentarios() -> None:
    st.subheader("Comentarios de la revisión")
    key = f"comentarios_{ss.run_id}"
    st.text_area("Observaciones generales (se guardan al salir del campo)",
                 value=ss.feedback.comentarios, key=key,
                 on_change=_al_cambiar_comentarios, args=(key,))


def _al_cambiar_comentarios(key: str) -> None:
    if _hay_run_abierto():
        ss.feedback.comentarios = ss[key]
        guardar_feedback()


def _desc(m: MatchResult) -> str:
    h = m.hallazgo_pdf or m.hallazgo_excel
    return h.descripcion if h else ""


# Título del paño colapsado (DISENO §9.1, decisión del usuario 2026-10-27): el total y
# su desglose por estado, con los colores de ETIQUETA_ESTADO, para ver qué hay dentro
# sin abrirlo. Los segmentos en 0 se omiten; la suma da el total del paño (sin las
# filas transversales, que tienen su propia sección).
SEGMENTOS_TITULO_PANO = (
    (EstadoHallazgo.COINCIDE, "✅", "coincide", "coinciden"),
    (EstadoHallazgo.DIFIERE, "🟡", "difiere", "difieren"),
    (EstadoHallazgo.FALTA_EN_EXCEL, "🔴", "falta en Excel", "faltan en Excel"),
    (EstadoHallazgo.EXTRA_EN_EXCEL, "🟠", "falta en el PDF", "faltan en el PDF"),
)


def _titulo_pano(pano: str, grupo: list[MatchResult]) -> str:
    segmentos = []
    for estado, icono, singular, plural in SEGMENTOS_TITULO_PANO:
        n = sum(1 for m in grupo if m.estado == estado)
        if not n:
            continue
        segmento = f"{icono} {n} {singular if n == 1 else plural}"
        if estado == EstadoHallazgo.COINCIDE:
            # "Coincide · redacción distinta" es una decisión automática del juez
            # que la revisora valida: el paño sigue colapsado si todo coincide
            # (§9.1), pero el título lo avisa (decisión del usuario 2026-10-17).
            redaccion = sum(1 for m in grupo if m.estado == estado and m.equivalencias_redaccion)
            if redaccion:
                segmento += f" ({redaccion} con redacción distinta)"
        segmentos.append(segmento)
    total = f"{len(grupo)} hallazgo{'' if len(grupo) == 1 else 's'}"
    return f"Paño {pano} · {total} = " + " + ".join(segmentos)


def _comentario(m: MatchResult) -> str:
    """Columna Comentario (DISENO §9.1): en 'difiere' lista los campos que
    difieren; calificación con valores inline por ser cortos. Prefijo
    '(revisar)' cuando el emparejamiento es dudoso."""
    if m.estado == EstadoHallazgo.DIFIERE:
        partes = [
            f"{ETIQUETA_CAMPO[d.campo.value]}: {d.valor_pdf} vs {d.valor_excel}"
            if d.campo == CampoDiferente.CALIFICACION
            else ETIQUETA_CAMPO[d.campo.value] + (
                f" ({ETIQUETA_MOTIVO_DIFERENCIA[d.motivo.value]})" if d.motivo else "")
            for d in m.diferencias
        ]
        base = "🟡 Difiere: " + " · ".join(partes)
    elif m.estado == EstadoHallazgo.COINCIDE and m.equivalencias_redaccion:
        base = ETIQUETA_COINCIDE_REDACCION
    else:
        base = ETIQUETA_ESTADO[m.estado.value]
    if m.emparejamiento_es_dudoso:
        base = "(revisar) " + base
    return base


@st.cache_data(show_spinner=False, max_entries=20)
def _pdf_del_run(run_dir: str, mtime_ns: int) -> PdfDelRun:
    return pdf_del_run(Path(run_dir))


@st.cache_data(show_spinner=False, max_entries=64)
def _png_pagina(ruta: str, mtime_ns: int, pagina: int,
                resaltados: tuple[tuple[str, str, tuple[float, float, float]], ...]
                ) -> PaginaRenderizada:
    return render_pagina(Path(ruta), pagina, tuple(
        Resaltado(texto, parte, color) for texto, parte, color in resaltados  # type: ignore[arg-type]
    ))


def _visor(paginas: list[PaginaVisor], paginas_texto: str | None = None,
           clave: str | None = None, recorrer: bool = False) -> None:
    """Las páginas del PDF del run, con el texto respaldado resaltado.

    Sin páginas resaltables, se ofrecen las de `paginas_texto` (la columna
    Páginas del checklist). Con más de dos páginas se elige una (`clave`).
    Con `recorrer` (checklist), además se puede ir a cualquier página del PDF
    y descargarlo completo.
    """
    run_dir = settings.runs_dir / str(ss.run_id)
    ruta = run_dir / "input.pdf"
    mtime = ruta.stat().st_mtime_ns if ruta.is_file() else 0
    pdf = _pdf_del_run(str(run_dir), mtime)
    if pdf.estado == EstadoPdf.FALTA:
        st.info("Este procesamiento no conserva el PDF (es anterior a que se guardara, o lo "
                "borró la política de retención): búscalo en tu copia del informe.")
        return
    if pdf.estado == EstadoPdf.HASH_DISTINTO:
        st.warning("El PDF guardado en este procesamiento no es el que se analizó (su huella "
                   "no coincide): no se muestra.")
        return
    if pdf.desde_docx:
        st.caption("El informe llegó en Word: estas son las páginas del PDF convertido, que no "
                   "coinciden con la paginación de Word. Para ubicarlo en el Word, busca el "
                   "texto resaltado.")
    if not paginas:
        mencionadas, recortadas = paginas_mencionadas(paginas_texto, pdf.total)
        paginas = [PaginaVisor(n) for n in mencionadas]
        if paginas:
            st.caption("Páginas según la columna Páginas: es texto del modelo, sin verificar"
                       + (f"; se muestran las primeras {len(paginas)}." if recortadas else "."))
    if not paginas:
        st.caption("Sin páginas que mostrar.")
        if not recorrer:
            return
    todas = {p.pagina: p for p in paginas}
    if len(paginas) > 2:
        elegida = st.selectbox("Página", list(todas), key=clave)
        paginas = [todas[elegida]]
    for p in paginas:
        _pagina_del_visor(pdf, mtime, p)
    if recorrer and st.toggle("Recorrer el PDF completo", key=f"recorrer_{clave}"):
        mencionadas, recortadas = paginas_mencionadas(paginas_texto, pdf.total)
        otras = [n for n in mencionadas if n not in todas]
        if otras or recortadas:
            st.caption("Otras páginas que menciona el sistema (sin verificar): "
                       f"{', '.join(map(str, otras))}"
                       + ("; la columna Páginas nombra más, que no se listan." if recortadas
                          else "."))
        # Parte en la vecina de la página que ya se muestra arriba, no en la misma.
        mostradas = [p.pagina for p in paginas if 1 <= p.pagina <= pdf.total]
        n = int(st.number_input(
            "Página del PDF", min_value=1, max_value=pdf.total, step=1, key=f"otra_{clave}",
            value=next((m for m in (max(mostradas, default=0) + 1,
                                    min(mostradas, default=0) - 1) if 1 <= m <= pdf.total), 1),
            help="Usa − y + para las páginas vecinas o escribe un número."))
        _pagina_del_visor(pdf, mtime, todas.get(n, PaginaVisor(n)))
        convertido = "_convertido" if pdf.desde_docx else ""
        st.download_button(
            f"⬇ Descargar el PDF {'convertido' if pdf.desde_docx else 'completo'}",
            lambda: ruta.read_bytes(), file_name=f"informe_{ss.run_id}{convertido}.pdf",
            mime="application/pdf", key=f"pdf_{clave}")


def _pagina_del_visor(pdf: PdfDelRun, mtime: int, p: PaginaVisor) -> None:
    if not 1 <= p.pagina <= pdf.total:
        st.warning(f"La página {p.pagina} no existe en el PDF ({pdf.total} páginas).")
        return
    render = _png_pagina(str(pdf.ruta), mtime, p.pagina, tuple(
        (r.texto, r.parte, r.color) for r in p.resaltados))
    if render.repetidos:
        st.warning("El texto aparece más de una vez en esta página (por ejemplo, el mismo "
                   "hallazgo en la tabla de otro paño): están resaltadas todas; confirma "
                   "cuál corresponde a este paño y relé.")
    nota = ("" if render.ubicados == len(p.resaltados)
            else " · no se pudo resaltar todo el texto")
    st.image(render.png, caption=f"Página {p.pagina} de {pdf.total}{nota}", width="stretch")


def _evidencia(m: MatchResult) -> str:
    partes = []
    if m.hallazgo_pdf and m.hallazgo_pdf.evidencia.pagina_pdf:
        ev = m.hallazgo_pdf.evidencia
        v = ev.verificacion_descripcion
        pagina = f"p.{ev.pagina_pdf}"
        if v and v.estado == EstadoCita.CONTINUA_PAGINA_SIGUIENTE and v.pagina:
            pagina = f"pp.{v.pagina}-{v.pagina + 1}"
        if any(c is not None and not c.respaldada for c in (v, ev.verificacion_accion)):
            pagina += " (cita no verificada)"
        partes.append(f"PDF {pagina}")
    if m.hallazgo_excel and m.hallazgo_excel.evidencia.fila_excel:
        oculta = " (oculta)" if m.hallazgo_excel.evidencia.fila_oculta else ""
        partes.append(f"Excel f.{m.hallazgo_excel.evidencia.fila_excel}{oculta}")
    return " · ".join(partes) or "—"


# ────────────────────────────────── router ──────────────────────────────────

if ss.reporte is None:
    pantalla_carga()
else:
    pantalla_resultados()
