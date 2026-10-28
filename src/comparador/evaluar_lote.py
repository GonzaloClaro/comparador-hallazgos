"""Medición en lote: pipeline completo sobre todos los informes reales.

Recorre las carpetas de informes reales (una por subestación, con el informe
PDF/DOCX, la Tabla de Hallazgos y, si existe, el CheckList revisado por la
revisora), corre el pipeline con cada modelo pedido y evalúa el checklist
contra el ground truth humano. Es la vara para aceptar o rechazar cambios de
prompts/catálogo: un cambio entra solo si no empeora la medición.

Uso (cada ronda en su carpeta de mediciones/, con sus runs fuera de runs/ para
que la retención no los borre; metricas_lote espera una evaluación por carpeta,
con sus runs en runs/ junto a ella: RUNS_DIR debe ser <carpeta de la salida>/runs,
si no sale antes de gastar):
    RUNS_DIR=mediciones/b3/runs python -m comparador.evaluar_lote \\
        --modelos claude-opus-5-5 --etiqueta B3 \\
        --salida mediciones/b3/evaluacion_B3.json [--informes "Gamma"] \\
        [--codigo-congelado mediciones/b3/src] [--preflight]
(los comandos exactos de B3 y B3s están en tasks/todo.md, PD22).

El resultado (JSON) trae, por modelo × informe: métricas del checklist, ítems
punto a punto (para comparar rondas), resumen del comparador, su evaluación
contra el GT del comparador ("comparador_gt", si hay GT para ese informe y
Excel; sin texto de los informes) y tokens; además, la configuración y la
versión del código. Antes de gastar valida las planillas, las fichas por
informe (M39: ``--fichas``, por defecto ``mediciones/fichas_informes.yaml`` si
existe; cada caso necesita la suya y su planilla debe ser la de la ficha) y los
GT del comparador: un GT de la carpeta del informe atado a otro informe o Excel
corta el lote. La ficha de cada informe se copia en su fila. Las carpetas que no
son un caso (sin informe, sin Excel, con dos Excel o sin auditora reconocible)
se avisan con su motivo; un filtro ``--informes`` que apunta a una de ellas corta.

También antes de gastar (E10 del Bloque 23): con ``--codigo-congelado`` el
código que corre debe ser la copia congelada de ``src/`` de la ronda
(``persistence.verificar_codigo_congelado``; queda en la salida) y, salvo con
``--solo-checklist``, la clave de OpenAI debe responder un embedding de una
palabra (PD66, ``prueba_clave_openai`` en la salida; el pipeline la repite en
cada run). ``--preflight`` hace solo lo que no llama a ninguna API (sin esa
prueba) y sale sin escribir la salida. Lo que el pipeline valida gratis dentro de
cada run (criterios del checklist, hints de la auditora y, salvo con
``--solo-checklist``, el Excel por E2) se valida también antes de crear runs, y
el preflight además convierte cada informe Word en un temporal.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import sys
import tempfile
import traceback
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from comparador import etapa4_matching, fichas
from comparador.catalogo import cargar_hints_empresa
from comparador.config import PROJECT_ROOT, settings
from comparador.convertir import adecuar_pdf_para_llm, convertir_docx_a_pdf
from comparador.etapa0_checklist import cargar_puntos, cita_respalda
from comparador.etapa2_normalizar_excel import normalizar_excel
from comparador.evaluar_checklist import ItemEvaluado, cargar_gt, evaluar
from comparador.evaluar_comparador import (
    GT_DIR_DEFAULT,
    GtAplicable,
    GtNoAplicaError,
    evaluar_run,
    gt_aplicable,
    gts_de,
    resumen_con_gt,
)
from comparador.llm.embeddings import ClaveOpenAIError, probar_clave_openai
from comparador.persistence import (
    MODO_COMPLETO,
    MODO_SOLO_CHECKLIST,
    CodigoNoCongeladoError,
    cargar_json,
    crear_run_dir,
    guardar_hash_input,
    guardar_json,
    terminar_run,
    verificar_codigo_congelado,
    version_codigo,
)
from comparador.pipeline import (
    CredencialesFaltantesError,
    _validar_credenciales,
    ejecutar_pipeline,
    ejecutar_solo_checklist,
)
from comparador.rutas import ruta_dentro_de
from comparador.schemas import (
    ChecklistInforme,
    EmpresaAuditora,
    ReporteInforme,
    ResultadoChecklist,
)

BASE_DEFAULT = PROJECT_ROOT / "informes_reales"


def _empresa(carpeta: Path) -> EmpresaAuditora | None:
    nombre = carpeta.name.lower()
    if "ensaut" in nombre:
        return EmpresaAuditora.ENSAUT
    if "reliable" in nombre:
        return EmpresaAuditora.RELIABLE_ENERGY
    if "sdi" in nombre:
        return EmpresaAuditora.SDI
    return None


def _plano(texto: str) -> str:
    """Sin tildes ni mayúsculas: macOS guarda los nombres en NFD ("Ananuca\u0303e")."""
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c)).casefold()


def _motivo_omision(
    informes: list[Path], excels: list[Path], empresa: EmpresaAuditora | None
) -> str | None:
    if not informes:
        return "sin informe (PDF o DOCX)"
    if not excels:
        return "sin Excel de hallazgos"
    if len(excels) > 1:
        return f"{len(excels)} Excel de hallazgos: {', '.join(f.name for f in excels)}"
    if empresa is None:
        return "no se reconoce la empresa auditora en el nombre"
    return None


@dataclass(frozen=True)
class Omitida:
    """Carpeta que no es un caso, con el motivo (se avisa antes de correr)."""

    carpeta: str
    motivo: str


def descubrir_casos(
    base: Path, filtro: list[str] | None = None
) -> tuple[list[dict[str, Any]], list[Omitida]]:
    """(casos, carpetas omitidas). Un caso por carpeta: informe (PDF preferido
    sobre DOCX), Excel y planilla opcional.

    Una carpeta sin informe, sin Excel, con dos Excel o sin una auditora
    reconocible en el nombre queda omitida con su motivo (antes se saltaba en
    silencio, tomaba el primer Excel o cortaba el lote). Un filtro que apunta a
    una carpeta omitida es error (ValueError), igual que dos planillas: elegir
    una mediría contra la equivocada. Los archivos de bloqueo de Office
    («~$<nombre>», que quedan mientras el archivo está abierto) no cuentan.
    """
    casos: list[dict[str, Any]] = []
    omitidas: list[Omitida] = []
    for carpeta in sorted(p for p in base.iterdir() if p.is_dir()):
        if filtro and not any(_plano(f) in _plano(carpeta.name) for f in filtro):
            continue
        archivos = [f for f in carpeta.iterdir() if f.is_file() and not f.name.startswith("~$")]
        informes = [
            f for f in archivos
            if f.suffix.lower() in (".pdf", ".docx")
            and "comprimido" not in f.name.lower() and "_adecuado" not in f.name
        ]
        informes.sort(key=lambda f: (f.suffix.lower() != ".pdf", f.name))
        excels = sorted(f for f in archivos if f.suffix == ".xlsx" and "hallazgo" in f.name.lower())
        gts = [f for f in archivos if f.suffix == ".xlsx" and "checklist" in f.name.lower()]
        if len(gts) > 1:
            # Elegir uno en silencio mediría contra la planilla equivocada (p. ej. una
            # pre-llenada por la herramienta, que no es una referencia independiente).
            raise ValueError(
                f"Más de una planilla de revisión en {carpeta.name}: "
                f"{', '.join(sorted(f.name for f in gts))}. Dejar solo la de referencia."
            )
        empresa = _empresa(carpeta)
        motivo = _motivo_omision(informes, excels, empresa)
        if motivo is not None:
            omitidas.append(Omitida(carpeta.name, motivo))
            continue
        casos.append({
            "nombre": carpeta.name,
            "empresa": empresa,
            "informe": informes[0],
            "excel": excels[0],
            "gt": gts[0] if gts else None,
        })
    if filtro and omitidas:
        raise ValueError("El filtro --informes apunta a carpetas que no son un caso: " + "; ".join(
            f"{o.carpeta} ({o.motivo})" for o in omitidas))
    return casos, omitidas


async def _correr_caso(caso: dict[str, Any], solo_checklist: bool = False) -> dict[str, Any]:
    """Mismo flujo que la UI: copia insumos, convierte/adecúa, corre el pipeline.

    Con `solo_checklist` corre solo la Etapa 0 (`pipeline.ejecutar_solo_checklist`):
    no copia el Excel y devuelve el checklist en vez del reporte.
    """
    run_dir = crear_run_dir(settings.modelo_extraccion)
    try:
        return await _correr_en(run_dir, caso, solo_checklist)
    finally:
        # La retención no borra un run en curso (informes en paralelo).
        terminar_run(run_dir)


async def _correr_en(run_dir: Path, caso: dict[str, Any], solo_checklist: bool) -> dict[str, Any]:
    modo = MODO_SOLO_CHECKLIST if solo_checklist else MODO_COMPLETO
    es_docx = caso["informe"].suffix.lower() == ".docx"
    ruta_informe = run_dir / ("input.docx" if es_docx else "input.pdf")
    ruta_excel = run_dir / "input.xlsx"
    shutil.copyfile(caso["informe"], ruta_informe)
    if not solo_checklist:
        shutil.copyfile(caso["excel"], ruta_excel)
    guardar_hash_input(run_dir, ruta_informe, "informe_original")
    guardar_json(run_dir, "inputs.json", {
        "informe": caso["informe"].name, "excel": caso["excel"].name, "lote": True,
        "modo": modo,
    })
    loop = asyncio.get_running_loop()
    try:
        ruta_pdf, conversion = ruta_informe, None
        if es_docx:
            ruta_pdf, conversion = await loop.run_in_executor(
                None, convertir_docx_a_pdf, ruta_informe, run_dir / "input.pdf"
            )
        # Las citas se verifican contra el PDF con texto (misma paginación).
        ruta_pdf_texto = ruta_pdf
        ruta_pdf, adecuacion = await loop.run_in_executor(None, adecuar_pdf_para_llm, ruta_pdf)
        if adecuacion or conversion:
            guardar_json(run_dir, "adecuacion.json", {
                **(adecuacion or {}),
                **({"conversion": conversion} if conversion else {}),
            })
        if solo_checklist:
            checklist, _ = await ejecutar_solo_checklist(
                ruta_pdf, run_dir=run_dir, ruta_pdf_texto=ruta_pdf_texto,
                empresa_auditora=caso["empresa"],
            )
        else:
            reporte, _ = await ejecutar_pipeline(
                ruta_pdf=ruta_pdf, ruta_excel=ruta_excel,
                empresa_auditora=caso["empresa"], run_dir=run_dir, ruta_pdf_texto=ruta_pdf_texto,
            )
    except Exception as exc:
        # "notas": si fallan dos etapas en paralelo, la segunda viaja como nota
        # (pipeline._persistir_checklist_y_e1) y no está en str(exc).
        notas = list(getattr(exc, "__notes__", []))
        guardar_json(run_dir, "error.json", {
            "tipo": type(exc).__name__, "mensaje": str(exc), "notas": notas,
            "traceback": traceback.format_exc(), "fecha": datetime.now().isoformat(),
        })
        return {"run_id": run_dir.name, "modo": modo,
                "error": " | ".join([f"{type(exc).__name__}: {exc}", *notas])}
    if solo_checklist:
        return {"run_id": run_dir.name, "checklist": checklist}
    return {"run_id": run_dir.name, "reporte": reporte}


def resumen_citas_checklist(
    cl: ChecklistInforme | None, items_gt: list[ItemEvaluado] | None = None
) -> dict[str, Any] | None:
    """Citas del checklist: cuántos "cumple" bajaron a no verificable por falta de
    cita (y cuáles), y contra la planilla cuántos de esos eran falsos cumple que la
    bajada evitó y cuántos eran aciertos que se perdieron. None si no se pidieron citas.

    Bajado por falta de cita = el modelo dijo «cumple» y ninguna cita lo respalda,
    con la misma regla que lo bajó (etapa0_checklist.cita_respalda): un «cumple»
    bajado por otro motivo, con cita respaldada (M08), no cuenta acá.
    """
    if cl is None or cl.bajados_sin_cita_verificada is None:
        return None
    bajados = sorted(
        i.numero for i in cl.items if i.resultado_modelo == ResultadoChecklist.CUMPLE
        and not any(map(cita_respalda, i.citas)))
    resumen: dict[str, Any] = {
        "bajados_sin_cita_verificada": cl.bajados_sin_cita_verificada,
        "puntos_bajados": bajados,
        "estados": dict(sorted(Counter(
            c.verificacion.estado.value for i in cl.items for c in i.citas if c.verificacion
        ).items())),
    }
    if items_gt is not None:
        resumen |= {
            "bajados_que_eran_falso_cumple": sum(
                1 for i in items_gt if i.numero in bajados and i.veredicto_gt == "NO"),
            "bajados_que_eran_acierto": sum(
                1 for i in items_gt if i.numero in bajados and i.veredicto_gt == "SI"),
        }
    return resumen


def resumen_citas(
    reporte: ReporteInforme, items_gt: list[ItemEvaluado] | None = None
) -> dict[str, Any]:
    """Estados de la verificación de citas (schema 0.7.0) de un reporte.

    Comparador: estado de la descripción y de la acción de cada hallazgo del
    PDF (una vez por resultado). Checklist: ver `resumen_citas_checklist`.
    """
    def contar(estados: list[str]) -> dict[str, int]:
        return dict(sorted(Counter(estados).items()))

    pdf = [m.hallazgo_pdf.evidencia for m in reporte.resultados if m.hallazgo_pdf]
    citas: dict[str, Any] = {"comparador": {
        "descripcion": contar([e.verificacion_descripcion.estado.value for e in pdf
                               if e.verificacion_descripcion]),
        "accion": contar([e.verificacion_accion.estado.value for e in pdf
                          if e.verificacion_accion]),
    }}
    checklist = resumen_citas_checklist(reporte.checklist, items_gt)
    if checklist is not None:
        citas["checklist"] = checklist
    return citas


def _metadata_y_troceo(fila: dict[str, Any], run_id: str) -> None:
    meta_path = settings.runs_dir / run_id / "metadata.json"
    if meta_path.exists():
        meta = cargar_json(meta_path)
        fila["tokens"] = {k: v for k, v in meta.items() if k.startswith("tokens_")}
        fila["duracion_segundos"] = meta.get("duracion_segundos")
    troceo = settings.runs_dir / run_id / "troceo.json"
    if troceo.exists():
        fila["troceo"] = cargar_json(troceo)


def _checklist_gt(ev: Any) -> dict[str, Any]:
    return {
        "evaluados": len(ev.items), "aciertos": ev.aciertos,
        "no_verificables": ev.no_verificables,
        "falsos_no_cumple": ev.falsos_no_cumple, "falsos_cumple": ev.falsos_cumple,
        "sin_gt": ev.sin_gt,
        "items": [asdict(i) for i in ev.items],
    }


def _resumen_solo_checklist(caso: dict[str, Any], resultado: dict[str, Any]) -> dict[str, Any]:
    """Fila de un run que corrió solo el checklist: sin clave "comparador" (las
    métricas y la comparación entre rondas la saltan)."""
    cl: ChecklistInforme = resultado["checklist"]
    fila: dict[str, Any] = {
        "informe": caso["nombre"], "run_id": resultado["run_id"],
        "modo": MODO_SOLO_CHECKLIST, "checklist_cumplen": cl.cumplen,
    }
    _metadata_y_troceo(fila, resultado["run_id"])
    items_gt = None
    if caso["gt"]:
        ev = evaluar(resultado["run_id"], caso["gt"])
        fila["checklist_gt"] = _checklist_gt(ev)
        items_gt = ev.items
    citas = resumen_citas_checklist(cl, items_gt)
    if citas is not None:
        fila["citas"] = {"checklist": citas}
    return fila


def _resumen_caso(caso: dict[str, Any], resultado: dict[str, Any]) -> dict[str, Any]:
    fila: dict[str, Any] = {"informe": caso["nombre"], "run_id": resultado["run_id"]}
    if "error" in resultado:
        fila["error"] = resultado["error"]
        # Un run solo checklist que falló tampoco es un error del comparador
        # (metricas_lote salta las filas con este modo).
        if resultado.get("modo") == MODO_SOLO_CHECKLIST:
            fila["modo"] = MODO_SOLO_CHECKLIST
        return fila
    if "checklist" in resultado:
        return _resumen_solo_checklist(caso, resultado)
    reporte: ReporteInforme = resultado["reporte"]
    r = reporte.resumen
    fila["comparador"] = {
        "total": r.total, "coinciden": r.coinciden, "difieren": r.difieren,
        "faltan_en_excel": r.faltan_en_excel, "extra_en_excel": r.extra_en_excel,
        "transversales": r.transversales, "requieren_revision": r.requieren_revision,
        # Subconjunto de "coinciden" que decidió el juez de redacción (4e):
        # sin esto la medición no ve cuánto pesa el juez entre rondas.
        "coinciden_con_redaccion_distinta": r.coinciden_con_redaccion_distinta,
    }
    if reporte.checklist:
        fila["checklist_cumplen"] = reporte.checklist.cumplen
    # Clave aparte de "comparador": los conteos de esa clave se comparan entre rondas.
    fila["citas"] = resumen_citas(reporte)
    _metadata_y_troceo(fila, resultado["run_id"])
    if caso["gt"]:
        ev = evaluar(resultado["run_id"], caso["gt"])
        fila["checklist_gt"] = _checklist_gt(ev)
        fila["citas"] = resumen_citas(reporte, ev.items)
    gt_comparador: GtAplicable | None = caso.get("gt_comparador")
    if gt_comparador is not None:
        # Clave aparte de "comparador" (metricas_lote compara esa con los conteos);
        # con el sha256 del GT, para recalcularla después con el mismo. Si falla, el
        # error queda en esta clave y el resto de la fila se conserva: una clave
        # "error" arriba haría que metricas_lote saltara el run pagado entero (la
        # evaluación se recalcula desde el run con metricas_lote o evaluar_comparador).
        try:
            ev_cmp = evaluar_run(settings.runs_dir / resultado["run_id"], gt_comparador.gt)
            fila["comparador_gt"] = resumen_con_gt(ev_cmp, gt_comparador)
        except Exception as exc:  # noqa: BLE001 — no perder la fila de un run ya pagado
            fila["comparador_gt"] = {"error": f"{type(exc).__name__}: {exc}"}
    return fila


def _sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def asignar_gt_comparador(casos: list[dict[str, Any]], carpeta: Path) -> None:
    """Pone en cada caso su GT del comparador (``gt_comparador``; None si no hay).

    Antes de gastar: el GT se ata al sha256 del informe original y del Excel
    (los mismos bytes que el run copia). ``GtNoAplicaError`` si el GT de la
    carpeta del informe es de otro informe o Excel, o si hay dos.
    """
    gts = gts_de(carpeta)
    for caso in casos:
        caso["gt_comparador"] = gt_aplicable(
            gts, _sha256(caso["informe"]), _sha256(caso["excel"]), informe=caso["nombre"])


def asignar_fichas(casos: list[dict[str, Any]], ruta: Path | None) -> None:
    """Pone en cada caso su ficha (M39: ``ficha``, como JSON; None sin archivo de fichas).

    Antes de gastar: cada caso necesita su ficha, y la planilla de la carpeta
    debe ser la de la ficha (sha256): una planilla reemplazada (p. ej. por una
    pre-llenada con la herramienta) no es la referencia con que se midió.
    ValueError con todos los problemas juntos.
    """
    if ruta is None:
        for caso in casos:
            caso["ficha"] = None
        return
    por_carpeta = fichas.cargar_fichas(ruta)
    problemas: list[str] = []
    for caso in casos:
        ficha = fichas.ficha_de(por_carpeta, caso["nombre"])
        if ficha is None:
            problemas.append(f"{caso['nombre']}: sin ficha")
            continue
        problemas += [f"{caso['nombre']}: {problema}"
                      for problema in fichas.problemas_planilla(ficha, caso["gt"])]
        caso["ficha"] = ficha.model_dump(mode="json")
    if problemas:
        raise ValueError("; ".join(problemas))


async def correr_lote(
    modelos: list[str], casos: list[dict[str, Any]], paralelo: int, solo_checklist: bool = False
) -> dict[str, list[dict[str, Any]]]:
    """Modelos en serie (el pipeline lee settings.modelo_extraccion en cada
    etapa: mezclar modelos en paralelo los cruzaría); informes en paralelo."""
    original = settings.modelo_extraccion
    # La retención por defecto podaría el lote mientras corre: 3 completos, y
    # 1 incompleto — con informes en paralelo, crear el segundo run borraría
    # al primero a mitad de proceso.
    settings.runs_a_retener = 10_000
    settings.runs_incompletos_a_retener = 10_000
    resultados: dict[str, list[dict[str, Any]]] = {}
    sem = asyncio.Semaphore(paralelo)
    try:
        for modelo in modelos:
            settings.modelo_extraccion = modelo

            async def _uno(caso: dict[str, Any], modelo: str = modelo) -> dict[str, Any]:
                async with sem:
                    print(f"[{modelo}] {caso['nombre']}: procesando...", flush=True)
                    res = await _correr_caso(caso, solo_checklist)
                    try:
                        fila = _resumen_caso(caso, res)
                    except Exception as exc:  # noqa: BLE001 — no botar el lote ya pagado
                        fila = {"informe": caso["nombre"], "run_id": res["run_id"],
                                "error": f"evaluación: {type(exc).__name__}: {exc}"}
                        if solo_checklist:
                            # metricas_lote salta las filas con este modo en el comparador.
                            fila["modo"] = MODO_SOLO_CHECKLIST
                    if caso.get("ficha") is not None:
                        # La ficha con que se midió (M39): metricas_lote separa dentro y
                        # fuera de muestra con esta copia, no con el YAML de hoy.
                        fila["ficha"] = caso["ficha"]
                    estado = fila.get("error") or fila.get("checklist_gt", {}).get("aciertos")
                    print(f"[{modelo}] {caso['nombre']}: {estado}", flush=True)
                    if "error" in (fila.get("comparador_gt") or {}):
                        print(f"[{modelo}] {caso['nombre']}: AVISO: falló la evaluación contra "
                              f"el GT del comparador: {fila['comparador_gt']['error']}",
                              flush=True)
                    return fila

            resultados[modelo] = list(await asyncio.gather(*(_uno(c) for c in casos)))
    finally:
        settings.modelo_extraccion = original
    return resultados


def _validar_insumos_locales(casos: list[dict[str, Any]], solo_checklist: bool) -> None:
    """Lo que el pipeline valida gratis dentro de cada run (criterios del checklist,
    hints de la auditora y, con el comparador, el Excel por E2), antes de crear
    runs: si fallara adentro, quedaría escrita la salida con filas de error y un
    run por caso, y la misma --salida ya no se podría repetir. Sin llamar a
    ninguna API. ValueError con el problema."""
    try:
        cargar_puntos()
    except Exception as exc:  # noqa: BLE001 — se informa y no se gasta nada
        raise ValueError(f"Criterios del checklist: {type(exc).__name__}: {exc}") from exc
    for caso in casos:
        try:
            hints = cargar_hints_empresa(caso["empresa"])
            if not solo_checklist:
                normalizar_excel(caso["excel"], hints.filas_transversales)
        except Exception as exc:  # noqa: BLE001 — se informa y no se gasta nada
            raise ValueError(f"{caso['nombre']}: {type(exc).__name__}: {exc} (no se llamó a "
                             "ninguna API)") from exc


def _probar_conversion_word(casos: list[dict[str, Any]]) -> None:
    """Solo en el preflight: convierte cada informe .docx en un temporal (local y
    gratis), porque dentro del run la conversión corre recién después de crearlo.
    Imprime lo que la conversión perdió (imágenes no convertibles). ValueError si
    falla."""
    for caso in casos:
        if caso["informe"].suffix.lower() != ".docx":
            continue
        with tempfile.TemporaryDirectory() as tmp:
            try:
                _, info = convertir_docx_a_pdf(caso["informe"], Path(tmp) / "input.pdf")
            except Exception as exc:  # noqa: BLE001 — se informa y no se gasta nada
                raise ValueError(f"{caso['nombre']}: no se pudo convertir {caso['informe'].name} "
                                 f"a PDF: {type(exc).__name__}: {exc}") from exc
        print(f"Conversión de {caso['informe'].name}: OK"
              + (f" (perdió: {info})" if info else ""), flush=True)


def _credenciales_presentes(modelos: list[str], solo_checklist: bool) -> None:
    """Las claves que cada modelo del lote exigirá (pipeline._validar_credenciales),
    sin llamar a nada. CredencialesFaltantesError si falta alguna."""
    original = settings.modelo_extraccion
    try:
        for modelo in modelos:
            settings.modelo_extraccion = modelo
            _validar_credenciales(solo_checklist=solo_checklist)
    finally:
        settings.modelo_extraccion = original


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--modelos", required=True, help="lista separada por comas")
    p.add_argument("--salida", required=True, type=Path)
    p.add_argument("--etiqueta", default="")
    p.add_argument("--informes", default="", help="filtro por nombre de carpeta (comas)")
    p.add_argument("--base", type=Path, default=BASE_DEFAULT)
    p.add_argument("--paralelo", type=int, default=2)
    p.add_argument("--solo-checklist", action="store_true",
                   help="corre solo el checklist (Etapa 0), sin el comparador")
    p.add_argument("--checklist-batch", action="store_true",
                   help="checklist por la API de Batch (CHECKLIST_BATCH=true, M61): mitad de "
                        "precio, espera a que termine cada lote; solo modelos Claude")
    p.add_argument("--sin-cita-checklist", action="store_true",
                   help="checklist sin la cita literal (CITA_CHECKLIST=false)")
    p.add_argument("--gt-comparador", type=Path, default=None,
                   help="carpeta de los GT del comparador (por defecto "
                        "mediciones/gt/comparador, si existe)")
    p.add_argument("--fichas", type=Path, default=None,
                   help="fichas por informe (M39; por defecto mediciones/fichas_informes.yaml, "
                        "si existe)")
    p.add_argument("--codigo-congelado", type=Path, default=None, metavar="CARPETA",
                   help="copia congelada de src/ de la ronda (p. ej. mediciones/b3/src): el "
                        "código que corre debe ser ese, si no sale antes de gastar")
    p.add_argument("--preflight", action="store_true",
                   help="solo valida lo que se valida antes de gastar (salida y RUNS_DIR, "
                        "código congelado, casos, planillas, criterios, catálogo, Excel, "
                        "fichas, GT, credenciales presentes) y sale sin llamar a ninguna API "
                        "ni escribir la salida")
    a = p.parse_args()
    # La salida y las planillas se validan antes de gastar: escribir la salida
    # es lo último que hace, y una falla ahí perdería el lote ya pagado.
    if a.salida.suffix.lower() != ".json":
        sys.exit(f"--salida debe ser un archivo .json (no una carpeta): {a.salida}")
    # metricas_lote y los golden leen los runs de una evaluación en runs/ junto a
    # ella: con otro RUNS_DIR (sin la variable, runs/ del proyecto, con retención)
    # los runs pagados quedarían donde nadie los mide. Implica que la salida no
    # queda dentro de RUNS_DIR (la retención la trataría como un run). La misma
    # carpeta = cada una dentro de la otra (por identidad: runs/ ≡ Runs/ en macOS).
    runs_de_la_salida = a.salida.parent / "runs"
    if not (ruta_dentro_de(settings.runs_dir, runs_de_la_salida)
            and ruta_dentro_de(runs_de_la_salida, settings.runs_dir)):
        sys.exit(f"RUNS_DIR ({settings.runs_dir}) debe ser {runs_de_la_salida}: los runs de "
                 "una evaluación van en runs/ junto a ella (metricas_lote y los golden los "
                 f"leen ahí). Correr con RUNS_DIR={runs_de_la_salida}; no se llamó a ninguna API.")
    if a.salida.exists():
        sys.exit(f"{a.salida} ya existe: elegir otra --salida (no se pisa una medición).")
    codigo_congelado = None
    if a.codigo_congelado is not None:
        try:
            codigo_congelado = verificar_codigo_congelado(a.codigo_congelado)
        except CodigoNoCongeladoError as exc:
            sys.exit(str(exc))
        print(f"Código congelado: {a.codigo_congelado} = el que corre "
              f"({codigo_congelado['sha256_codigo']})", flush=True)
    a.salida.parent.mkdir(parents=True, exist_ok=True)
    if a.sin_cita_checklist:
        settings.cita_checklist = False
    if a.checklist_batch:
        settings.checklist_batch = True

    try:
        casos, omitidas = descubrir_casos(a.base, [f for f in a.informes.split(",") if f] or None)
    except ValueError as exc:
        sys.exit(str(exc))
    for omitida in omitidas:
        print(f"Carpeta omitida: {omitida.carpeta}: {omitida.motivo}", flush=True)
    if not casos:
        sys.exit(f"No hay casos en {a.base}")
    for caso in casos:
        if caso["gt"] is not None:
            try:
                cargar_gt(caso["gt"])
            except Exception as exc:  # noqa: BLE001 — se informa y no se gasta nada
                sys.exit(f"No se puede leer la planilla {caso['gt'].name} ({caso['nombre']}): "
                         f"{type(exc).__name__}: {exc}")
    try:
        _validar_insumos_locales(casos, a.solo_checklist)
    except ValueError as exc:
        sys.exit(str(exc))
    if a.fichas is not None and not a.fichas.is_file():
        sys.exit(f"--fichas: no existe el archivo de fichas {a.fichas}")
    ruta_fichas = a.fichas or (fichas.RUTA_DEFAULT if fichas.RUTA_DEFAULT.is_file() else None)
    try:
        asignar_fichas(casos, ruta_fichas)
    except ValueError as exc:
        sys.exit(f"Fichas por informe ({ruta_fichas}): {exc}")
    print(f"Fichas: {ruta_fichas or 'sin archivo de fichas (las filas no llevan ficha)'}",
          flush=True)
    if a.gt_comparador is not None and not a.gt_comparador.is_dir():
        sys.exit(f"--gt-comparador: no existe la carpeta de GT del comparador {a.gt_comparador}")
    if a.solo_checklist:
        # Sin comparador no hay nada que evaluar contra su GT.
        for caso in casos:
            caso["gt_comparador"] = None
    else:
        carpeta_gt = a.gt_comparador or GT_DIR_DEFAULT
        try:
            asignar_gt_comparador(casos, carpeta_gt)
        except GtNoAplicaError as exc:
            sys.exit(f"GT del comparador en {carpeta_gt}: {exc}")
        except ValueError as exc:   # un GT que no valida (pydantic)
            sys.exit(f"No se puede leer un GT del comparador de {carpeta_gt}: {exc}")
        con_gt = sum(c["gt_comparador"] is not None for c in casos)
        print(f"GT del comparador: {con_gt} de {len(casos)} informes", flush=True)
    modelos = [m.strip() for m in a.modelos.split(",") if m.strip()]
    print(f"{len(casos)} informes × {len(modelos)} modelos", flush=True)
    if settings.checklist_batch:
        ajenos = [m for m in [*modelos, settings.modelo_extraccion_fallback]
                  if m and not m.startswith("claude")]
        if ajenos:
            sys.exit(f"--checklist-batch solo funciona con modelos Claude: {ajenos}; no se "
                     "llamó a ninguna API.")
    if a.preflight:
        try:
            _credenciales_presentes(modelos, a.solo_checklist)
        except CredencialesFaltantesError as exc:
            sys.exit(str(exc))
        try:
            _probar_conversion_word(casos)
        except ValueError as exc:
            sys.exit(str(exc))
        print("Preflight OK: pasó todo lo que se valida antes de gastar, sin llamar a ninguna "
              "API (la prueba de la clave de OpenAI es una llamada: corre al lanzar el lote).",
              flush=True)
        return
    prueba_clave = None
    if not a.solo_checklist:
        # PD66: lo último antes de gastar. El pipeline la repite en cada run (antes
        # de Claude); sin esta, una clave sin fondos o revocada dejaría runs fallidos
        # con su error.json y una salida escrita solo con errores.
        try:
            prueba_clave = probar_clave_openai(etapa4_matching.calcular_embeddings)
        except ClaveOpenAIError as exc:
            sys.exit(str(exc))
        print(f"Clave de OpenAI: responde ({prueba_clave['modelo_servido'] or '?'})", flush=True)
    # Antes de correr: es el código con que arranca el lote.
    version = version_codigo()
    resultados = asyncio.run(correr_lote(modelos, casos, a.paralelo, a.solo_checklist))
    a.salida.write_text(json.dumps({
        "etiqueta": a.etiqueta, "fecha": datetime.now().isoformat(),
        "modelos": modelos, "resultados": resultados,
        # Lo que cambia los resultados además del modelo: sin esto, dos rondas
        # con interruptores distintos no se pueden distinguir después.
        "config": {
            "solo_checklist": a.solo_checklist,
            "cita_checklist": settings.cita_checklist,
            "checklist_un_tramo": settings.checklist_un_tramo,
            "checklist_batch": settings.checklist_batch,
            "asignacion_global": settings.asignacion_global,
            "descripcion_identica": settings.descripcion_identica,
            "control_codigos": settings.control_codigos,
            "unificar_copias": settings.unificar_copias,
            "juez_justifica_primero": settings.juez_justifica_primero,
            "juez_redaccion": settings.juez_redaccion,
        },
        "version_codigo": version,
        # La copia congelada de src/ contra la que se verificó (None sin el flag).
        "codigo_congelado": codigo_congelado,
        # La prueba de la clave de OpenAI del lote (None en solo checklist).
        "prueba_clave_openai": prueba_clave,
    }, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for modelo, filas in resultados.items():
        print(f"\n== {modelo}")
        for f in filas:
            g = f.get("checklist_gt")
            ck = (f"aciertos {g['aciertos']}/{g['evaluados']} nv={g['no_verificables']} "
                  f"fnc={g['falsos_no_cumple']} fc={g['falsos_cumple']}") if g else "sin GT"
            c = f.get("comparador")
            cmp_ = (f"coinc={c['coinciden']} dif={c['difieren']} falta={c['faltan_en_excel']} "
                    f"extra={c['extra_en_excel']} trans={c['transversales']} "
                    f"redac={c['coinciden_con_redaccion_distinta']}") if c else ""
            print(f"  {f['informe'][:40]:40s} {f.get('error') or ck}  {cmp_}")


if __name__ == "__main__":
    main()
