"""Repite solo el emparejamiento (E4) y la consolidación (E5) de un run guardado.

Para medir un cambio de E4 (p. ej. ASIGNACION_GLOBAL) sobre los mismos
hallazgos que ya extrajo una corrida, sin volver a pagar el checklist, E1 ni
E3: lee `etapa2_excel_normalizado.json`, `etapa3_pdf_hallazgos.json` y
`reporte_final.json` del run, vuelve a llamar a los embeddings y a los jueces
de E4 con el modelo del run (salvo lo que cubren los vectores guardados y la
caché de jueces, ver «Sin API»), y escribe el resultado en `--salida`, fuera de
runs/ (la retención no lo toca y el run original no cambia) y, dentro de un
repositorio git, en una carpeta que git ignore (lleva texto de los informes; lo
mismo con `--solo-vectores`). La configuración
de E4 sale de `config_e4.json` (o de `metadata.json` en los runs anteriores a
ese archivo) y el effort, de los raw de los jueces (va en la request: ver
`_effort_del_run`), salvo ASIGNACION_GLOBAL, que es lo que se mide y sale del
proceso, no del run: encendida por defecto desde el 2026-10-26, así que para
repetir con el emparejamiento en orden (el control de PD26 sobre los runs
nuevos, o la base de regresión de B2) hay que pedir ASIGNACION_GLOBAL=false;
`metadata.json` y el preflight dicen con cuál corrió y con cuál corrió el run
(`asignacion_global_run`; sin la clave, el run es anterior al interruptor y
emparejó en orden) y, si son la misma, avisan que la repetición no mide el
interruptor (`aviso_asignacion_global`: el control de PD26 lanzado sin
ASIGNACION_GLOBAL=false saldría de la caché sin pagar nada y con el mismo
conteo). No es un error: así se repite B2 con la caché estricta. Un run que falló en E4
o E5 después de pagar (sin `metadata.json` ni `reporte_final.json`) también se
repite: empresa y metadatos del informe salen de `config_e4.json` y el
checklist de `checklist.json`; la metadata de la repetición deja
`conteo_original` en None. Cada repetición va
en `mediciones/replay_e4/<etiqueta>/<run_id>/` (D5; p. ej. AG1 para la medición
de la asignación global): ahí la leen metricas_lote (`replay_e4.csv`) y los
golden de los errores no mostrados.

Si hay un GT del comparador para el informe y el Excel del run de origen
(sha256, `--gt-comparador`; por defecto mediciones/gt/comparador), se valida
antes de gastar y `metadata.json` guarda la evaluación contra él del reporte
original y del repetido, y el delta (`evaluar_comparador.evaluacion_repeticion`).
La salida lleva una copia de los sha256 de los insumos del run, para evaluarla
sin buscar el run de origen.

Sin API (M70):
- Vectores: con `--vectores <npz>`, o los del run (`etapa4_embeddings.npz`, que
  el pipeline guarda desde M70) si existen, E4 usa esos vectores y solo paga
  los que falten; los de una repetición que pagó alguno quedan en su salida.
  El modelo de embeddings del npz debe ser el del run.
- `--cache {no,mixto,estricto}`: las respuestas de los jueces del run de
  origen sirven de caché (comparador.cache_jueces, cola por clave). «mixto»
  paga lo que no está; «estricto» no exige credenciales ni llama a la API:
  falla antes de empezar si falta un vector y ante la primera llamada que la
  caché no tiene. `metadata.json` registra el modo, de dónde salió la caché,
  lo servido desde ella y lo pagado.
- `--cache-desde <carpeta>`: la caché sale de los raw de los jueces de esa
  carpeta (p. ej. una repetición anterior) en vez de los del run de origen. Así
  lo que pagó una repetición mixta sirve a las estrictas siguientes: la base de
  regresión de B2 (`mediciones/b2/replay_base/<run_id>/`) completa las llamadas
  que los vectores recalculados de D1 cambiaron. Una repetición de otro run
  (`run_origen` de su metadata.json distinto) falla antes de gastar.
- `--solo-vectores <npz>`: calcula y guarda solo los vectores de E4 del run de
  origen (paga embeddings, ~US$0,0005 por informe), con un `.json` al lado con
  el uso y la comparación de las similitudes recalculadas con las que guardó
  el run (`verificar_similitudes`). Para los runs de B2, que no guardaron
  vectores (D1).

Antes de gastar (E10 del Bloque 23): con ``--codigo-congelado <copia de src/>``
el código que corre debe ser esa copia (si no, sale sin llamar a nada) y, salvo
con ``--cache estricto``, la clave de OpenAI debe responder un embedding de una
palabra antes del primer juez (PD66, ``prueba_clave_openai`` en metadata.json).
``--solo-vectores`` no la hace: no llama a Claude y su primera llamada ya es la
de los embeddings. ``--preflight`` (PD23) hace solo lo que no llama a ninguna API
(sin esa prueba) y sale sin escribir nada: código congelado, insumos y
configuración del run, vectores (que existan y sean del modelo del run; avisa
cuántos textos no cubren), caché, GT, salida (fuera de runs/ y del run,
ignorada por git, sin contenido) y credenciales presentes (no en estricto).
`metadata.json` guarda la copia congelada verificada (`codigo_congelado`) y el
modelo de respaldo del proceso.

Uso con los vectores de D1 y la caché mixta de la base de B2 (D10): paga solo
las llamadas a los jueces que la caché no tiene (las que cambia el
interruptor); sin `--vectores` ni `--cache` pagaría embeddings y todos los
jueces, ~US$0,1-0,6 por informe con Opus en B2 (así se midió AG1, cuando el
default era false):
    ASIGNACION_GLOBAL=true uv run python -m comparador.reproducir_e4 \\
        mediciones/b2/runs/<run_id> --salida mediciones/replay_e4/AG1/<run_id> \\
        --vectores mediciones/b2/vectores_e4/<run_id>.npz --cache mixto \\
        --cache-desde mediciones/b2/replay_base/<run_id>
(los comandos exactos de PD23, con ``--preflight`` primero, en tasks/todo.md).
Vectores de un run de B2 (D1) y repetición estricta, sin API, con ellos (B2
corrió con la asignación apagada: con el default de hoy, la caché estricta no
tendría las consultas que cambia la asignación global):
    uv run python -m comparador.reproducir_e4 mediciones/b2/runs/<run_id> \\
        --solo-vectores mediciones/b2/vectores_e4/<run_id>.npz
    ASIGNACION_GLOBAL=false uv run python -m comparador.reproducir_e4 \\
        mediciones/b2/runs/<run_id> --salida mediciones/replay_e4/<etiqueta>/<run_id> \\
        --vectores mediciones/b2/vectores_e4/<run_id>.npz --cache estricto
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import re
import shutil
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, NamedTuple

from comparador import etapa4_matching
from comparador.cache_jueces import MODOS, CacheJueces
from comparador.config import settings
from comparador.etapa4_matching import (
    Vectores,
    VectoresFaltantesError,
    contar_copias_unificadas,
    contar_reintentos,
    ejecutar_matching,
    textos_a_embeber,
)
from comparador.etapa5_consolidar import consolidar_reporte
from comparador.evaluar_comparador import (
    GT_DIR_DEFAULT,
    EvaluacionComparador,
    GtAplicable,
    evaluacion_repeticion,
    evaluar,
    gt_aplicable,
    gts_de,
)
from comparador.evaluar_comparador import resumen as resumen_evaluacion
from comparador.gt_comparador import hashes_del_run
from comparador.llm.embeddings import probar_clave_openai, similitud_coseno
from comparador.persistence import (
    ARCHIVO_CONFIG_E4,
    ARCHIVO_VECTORES,
    MODO_REPLAY_E4,
    CodigoNoCongeladoError,
    cargar_json,
    cargar_vectores,
    escribir_vectores,
    guardar_json,
    guardar_vectores,
    verificar_codigo_congelado,
    version_codigo,
)
from comparador.pipeline import (
    CredencialesFaltantesError,
    _guardar_metas_e4,
    _tokens_e4,
    _validar_credenciales,
)
from comparador.rutas import exigir_ignorada_por_git, ruta_dentro_de
from comparador.schemas import (
    ChecklistInforme,
    EmpresaAuditora,
    Hallazgo,
    MetadatosInforme,
    ReporteInforme,
    ResumenInforme,
)

# Los sha256 de los insumos del run: atan la repetición al GT de su informe.
HASHES_INSUMOS = ("input_informe_original.hash", "input_excel.hash")
# (GT, sha256 de los insumos, evaluación del reporte original: None si el run no terminó)
_EvaluacionGt = tuple[GtAplicable, tuple[str, str], EvaluacionComparador | None]
# Lo que E5 copia al reporte: metadatos del informe, empresa y checklist.
_ContextoE5 = tuple[MetadatosInforme, EmpresaAuditora, ChecklistInforme | None]
ModoCache = Literal["no", "mixto", "estricto"]
_OrigenVectores = tuple[Path, Vectores, str]   # (archivo, vectores, "run" | "indicado")
MODOS_CACHE: tuple[str, ...] = ("no", *MODOS)


def _sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _llamar_real(**kwargs: Any) -> tuple[Any, dict[str, Any]]:
    """El juez real de E4, para lo que la caché mixta no tiene. Se resuelve en
    cada llamada: es el mismo punto que reemplazan los tests."""
    return etapa4_matching.llamar_llm_estructurado(**kwargs)


def _hallazgos(run_dir: Path) -> tuple[list[Hallazgo], list[Hallazgo]]:
    return ([Hallazgo.model_validate(h)
             for h in cargar_json(run_dir / "etapa3_pdf_hallazgos.json")],
            [Hallazgo.model_validate(h)
             for h in cargar_json(run_dir / "etapa2_excel_normalizado.json")])


def _conteo(resumen: ResumenInforme) -> dict[str, int]:
    return {
        "coinciden": resumen.coinciden, "difieren": resumen.difieren,
        "faltan_en_excel": resumen.faltan_en_excel, "extra_en_excel": resumen.extra_en_excel,
        "requieren_revision": resumen.requieren_revision,
        "coinciden_con_redaccion_distinta": resumen.coinciden_con_redaccion_distinta,
    }


class _Preparacion(NamedTuple):
    """Lo que la repetición lee y valida sin costo antes de gastar."""

    run_dir: Path
    original: ReporteInforme | None
    contexto: _ContextoE5
    hallazgos_pdf: list[Hallazgo]
    hallazgos_excel: list[Hallazgo]
    gt: _EvaluacionGt | None
    config: dict[str, Any]           # la de E4 del run, que rige durante la repetición
    asignacion_global_run: bool      # la del run (no rige: la de la repetición es la del proceso)
    origen_effort: str
    origen: _OrigenVectores | None
    faltan_vectores: int             # textos de E4 sin vector cargado (en mixto, se pagan)
    cache_jueces: CacheJueces | None


def reproducir_e4(run_dir: Path, salida: Path, gt_dir: Path | None = None, *,
                  vectores: Path | None = None, cache: ModoCache = "no",
                  cache_desde: Path | None = None,
                  codigo_congelado: dict[str, Any] | None = None) -> dict[str, Any]:
    """E4 + E5 sobre los hallazgos guardados de `run_dir`; escribe en `salida`.

    Usa los modelos, umbrales, interruptores y effort de E4 del run
    (config_e4.json o metadata.json, y los raw de los jueces), salvo
    ASIGNACION_GLOBAL, que es lo que se quiere medir y viene de la
    configuración actual (encendida por defecto desde el 2026-10-26; con
    ASIGNACION_GLOBAL=false, el emparejamiento en orden); la del run queda en
    `asignacion_global_run` y, si es la misma, `aviso_asignacion_global` dice
    que la repetición no mide el interruptor. Devuelve la metadata
    escrita (con el conteo antes y después; antes = None si el run no terminó).
    La diferencia de conteos mezcla el interruptor con la variación del juez
    entre corridas: cada cambio se atribuye con la traza `asignacion_global` de
    los raw.

    Con `gt_dir`, el GT del informe y Excel del run (si hay uno) evalúa el
    reporte original antes de gastar y el repetido al final; sin GT aplicable,
    `comparador_gt` queda en None. Más de un GT para el run falla antes de gastar.

    `vectores` (o, sin él, el etapa4_embeddings.npz del run si existe), `cache`
    (no / mixto / estricto) y `cache_desde` (carpeta con los raw de los jueces
    que sirven de caché; por defecto el run): ver el docstring del módulo. Todo lo que puede
    fallar sin costo (modelo del npz, vectores faltantes en estricto, raw de
    los jueces ilegibles, effort que no concuerda, run fallido sin
    config_e4.json) falla antes de crear la salida (`preflight` hace solo eso).
    `codigo_congelado` (la copia de src/ ya verificada, `--codigo-congelado`)
    queda en la metadata.
    """
    prep = _preparar(run_dir, salida, gt_dir, vectores=vectores, cache=cache,
                     cache_desde=cache_desde)
    with _config_del_run_aplicada(prep.config):
        return _repetir(prep.run_dir, salida, prep.original, prep.contexto, prep.hallazgos_pdf,
                        prep.hallazgos_excel, prep.gt, prep.origen, prep.cache_jueces,
                        prep.origen_effort, prep.asignacion_global_run, codigo_congelado)


def preflight(run_dir: Path, salida: Path, gt_dir: Path | None = None, *,
              vectores: Path | None = None, cache: ModoCache = "no",
              cache_desde: Path | None = None) -> dict[str, Any]:
    """Todo lo que `reproducir_e4` valida antes de gastar, sin llamar a ninguna
    API ni escribir nada: insumos y configuración del run, vectores (modelo del
    npz; en estricto, que no falte ninguno), caché de los jueces, GT, salida
    (fuera de runs/ y del run, ignorada por git, sin contenido) y, salvo en
    estricto, las credenciales presentes con la configuración del run. La
    prueba de la clave de OpenAI es una llamada: corre al lanzar la repetición.
    Devuelve lo validado, sin texto de los informes, con la asignación global
    del proceso y la del run (y el aviso si son la misma)."""
    prep = _preparar(run_dir, salida, gt_dir, vectores=vectores, cache=cache,
                     cache_desde=cache_desde)
    estricto = prep.cache_jueces is not None and prep.cache_jueces.modo == "estricto"
    with _config_del_run_aplicada(prep.config):
        if not estricto:
            _validar_credenciales()
        resumen_gt = None
        if prep.gt is not None:
            aplicable, _, ev_original = prep.gt
            resumen_gt = {"gt": aplicable.ruta.name, "original": None if ev_original is None
                          else resumen_evaluacion(ev_original)}
        textos = len(textos_a_embeber(prep.hallazgos_pdf, prep.hallazgos_excel))
        return {
            "run_origen": prep.run_dir.name,
            "salida": str(salida),
            "modelo_extraccion": settings.modelo_extraccion,
            "modelo_juez_matching": settings.modelo_juez_matching or None,
            "modelo_extraccion_fallback": settings.modelo_extraccion_fallback or None,
            "modelo_embeddings": settings.modelo_embeddings,
            "asignacion_global": settings.asignacion_global,
            "asignacion_global_run": prep.asignacion_global_run,
            # Como la asignación global, salen del proceso (M30 y el control de códigos).
            "descripcion_identica": settings.descripcion_identica,
            "control_codigos": settings.control_codigos,
            "unificar_copias": settings.unificar_copias,
            "juez_justifica_primero": settings.juez_justifica_primero,
            "aviso_asignacion_global": aviso_asignacion_global(prep.asignacion_global_run,
                                                               settings.asignacion_global),
            "juez_redaccion": settings.juez_redaccion,
            "effort_llm": settings.effort_llm,
            "effort_llm_origen": prep.origen_effort,
            "vectores": {
                "origen": prep.origen[2] if prep.origen else None,
                "archivo": str(prep.origen[0]) if prep.origen else None,
                "textos": textos,
                "cubiertos": textos - prep.faltan_vectores,
                "faltan": prep.faltan_vectores,
            },
            "cache_jueces": ({"modo": "no"} if prep.cache_jueces is None else {
                "modo": prep.cache_jueces.modo, "desde": prep.cache_jueces.desde,
                "cargadas": prep.cache_jueces.resumen()["cargadas"]}),
            "comparador_gt": resumen_gt,
            "credenciales": "no se exigen (caché estricta)" if estricto else "presentes",
            "conteo_original": (_conteo(prep.original.resumen)
                                if prep.original is not None else None),
        }


@contextmanager
def _config_del_run_aplicada(config: dict[str, Any]) -> Iterator[None]:
    """La configuración del run rige solo durante la repetición (o el
    preflight): al terminar, o fallar, vuelve la del proceso."""
    anterior = {campo: getattr(settings, campo) for campo in config}
    for campo, valor in config.items():
        setattr(settings, campo, valor)
    try:
        yield
    finally:
        for campo, valor in anterior.items():
            setattr(settings, campo, valor)


def _preparar(run_dir: Path, salida: Path, gt_dir: Path | None, *, vectores: Path | None,
              cache: ModoCache, cache_desde: Path | None) -> _Preparacion:
    """Lee y valida, sin costo y sin escribir, todo lo que la repetición necesita."""
    if cache not in MODOS_CACHE:
        raise ValueError(f"cache debe ser una de {MODOS_CACHE}, no {cache!r}")
    if cache_desde is not None:
        if cache == "no":
            raise ValueError("cache_desde requiere cache mixto o estricto")
        if not any(cache_desde.glob("etapa4_*_raw/*_*.json")):
            raise ValueError(f"cache_desde: {cache_desde} no tiene raw de los jueces de E4")
    run_dir = run_dir.resolve()   # "." (cwd dentro del run) no tiene nombre
    if cache_desde is not None and (cache_desde / "metadata.json").is_file():
        # La base de otro run: ninguna clave acertaría y se pagarían todos los
        # jueces, mezclando su variación con el efecto del cambio que se mide.
        de_la_cache = cargar_json(cache_desde / "metadata.json").get("run_origen")
        if de_la_cache is not None and de_la_cache != run_dir.name:
            raise ValueError(f"cache_desde: {cache_desde} es de otro run ({de_la_cache}, no "
                             f"{run_dir.name}): su caché no tiene los jueces de este run.")
    if ruta_dentro_de(salida, settings.runs_dir):
        raise ValueError(f"--salida debe quedar fuera de {settings.runs_dir} (la retención "
                         "la trataría como un run y podría borrarla).")
    if ruta_dentro_de(salida, run_dir):
        raise ValueError(f"--salida no puede quedar dentro del run de origen {run_dir}: "
                         "sobrescribiría sus archivos (invariante 20).")
    exigir_ignorada_por_git(salida, "--salida", carpeta=True)
    if salida.exists() and (not salida.is_dir() or any(salida.iterdir())):
        raise ValueError(f"--salida ({salida}) ya existe con contenido: usar una carpeta "
                         "nueva para no mezclar los raw de dos repeticiones.")
    guardada, archivo_config = _config_guardada(run_dir)
    original = (ReporteInforme.model_validate(cargar_json(run_dir / "reporte_final.json"))
                if (run_dir / "reporte_final.json").is_file() else None)
    contexto = _contexto_e5(run_dir, original, guardada, archivo_config)
    hallazgos_pdf, hallazgos_excel = _hallazgos(run_dir)
    gt = _evaluacion_original(run_dir, original, gt_dir)
    config = _config_del_run(guardada)
    config["effort_llm"], origen_effort = _effort_del_run(
        run_dir, guardada.get("effort_llm"), archivo_config)
    origen = _vectores_de_origen(run_dir, vectores, config["modelo_embeddings"])
    cargados = origen[1] if origen else {}
    textos = textos_a_embeber(hallazgos_pdf, hallazgos_excel)
    faltan = [t for t in textos if t not in cargados]
    if cache == "estricto" and faltan:
        raise VectoresFaltantesError(
            f"--cache estricto: faltan los vectores de {len(faltan)} de los {len(textos)} "
            f"textos de E4 ({'en ' + origen[0].name if origen else 'el run no los guardó'}). "
            "Calcularlos con --solo-vectores (paga embeddings) o usar --cache mixto.")
    fuente_cache = (cache_desde or run_dir).resolve()
    cache_jueces = None if cache == "no" else CacheJueces.desde_run(
        fuente_cache, modo=cache, llamar_real=_llamar_real)
    return _Preparacion(run_dir, original, contexto, hallazgos_pdf, hallazgos_excel, gt, config,
                        _asignacion_global_del_run(guardada), origen_effort, origen,
                        len(faltan), cache_jueces)


def _vectores_de_origen(run_dir: Path, indicado: Path | None,
                        modelo_embeddings: str) -> _OrigenVectores | None:
    """Los vectores indicados o, si no, los del run; None si no hay. Un npz de
    otro modelo de embeddings falla: con otros vectores E4 no se repite."""
    if indicado is not None:
        ruta, de_donde = indicado, "indicado"
    elif (run_dir / ARCHIVO_VECTORES).is_file():
        ruta, de_donde = run_dir / ARCHIVO_VECTORES, "run"
    else:
        return None
    vectores, modelo = cargar_vectores(ruta)
    if modelo != modelo_embeddings:
        raise ValueError(f"{ruta} tiene vectores de {modelo} y el run usó {modelo_embeddings}: "
                         "con otros vectores E4 no se repite.")
    return ruta, vectores, de_donde


def _evaluacion_original(run_dir: Path, original: ReporteInforme | None,
                         gt_dir: Path | None) -> _EvaluacionGt | None:
    """El GT del run y la evaluación del reporte original, sin gastar (None si
    no aplica; la evaluación en None si el run no terminó)."""
    hashes = hashes_del_run(run_dir)
    if gt_dir is None or hashes is None:
        return None
    gt = gt_aplicable(gts_de(gt_dir), *hashes)
    if gt is None:
        return None
    ev = None if original is None else evaluar(
        original, gt.gt, sha256_informe=hashes[0], sha256_excel=hashes[1], run_id=run_dir.name)
    return gt, hashes, ev


def _config_guardada(run_dir: Path) -> tuple[dict[str, Any], str]:
    """(configuración de E4 del run, archivo del que sale): config_e4.json, que
    el pipeline escribe antes de E4, o metadata.json en los runs anteriores a
    ese archivo. Sin ninguno de los dos (run fallido anterior a config_e4.json)
    no se adivina."""
    for nombre in (ARCHIVO_CONFIG_E4, "metadata.json"):
        if (run_dir / nombre).is_file():
            return cargar_json(run_dir / nombre), nombre
    raise FileNotFoundError(
        f"{run_dir} no tiene {ARCHIVO_CONFIG_E4} ni metadata.json (run fallido anterior a "
        f"{ARCHIVO_CONFIG_E4}): no se sabe con qué configuración repetir E4.")


def _contexto_e5(run_dir: Path, original: ReporteInforme | None, guardada: dict[str, Any],
                 archivo_config: str) -> _ContextoE5:
    """Metadatos del informe, empresa y checklist que E5 copia al reporte: los
    del reporte original o, si el run no terminó, los de config_e4.json y el
    checklist.json que el pipeline guardó antes de E3."""
    if original is not None:
        return (MetadatosInforme(
            coordinado=original.coordinado, subestacion=original.subestacion,
            informe_id=original.informe_id, fecha_auditoria=original.fecha_auditoria,
            columnas_ausentes=original.columnas_ausentes_excel,
        ), original.empresa_auditora, original.checklist)
    if archivo_config != ARCHIVO_CONFIG_E4:
        raise FileNotFoundError(
            f"{run_dir} no tiene reporte_final.json ni {ARCHIVO_CONFIG_E4}: faltan los "
            "metadatos del informe y la empresa para consolidar la repetición.")
    return (MetadatosInforme.model_validate(guardada["metadatos_informe"]),
            EmpresaAuditora(guardada["empresa_auditora"]),
            ChecklistInforme.model_validate(cargar_json(run_dir / "checklist.json")))


def _effort_del_run(run_dir: Path, registrado: str | None,
                    archivo_config: str) -> tuple[str, str]:
    """(effort, de dónde sale) con que el run llamó a los jueces de E4. Va en
    la request y la caché lo compara (cache_jueces.normalizar_parametros): con
    el effort del entorno, la caché no encontraría nada (estricta) o pagaría
    todo (mixta). Sale de `parametros_thinking` de los raw de Claude; si
    ninguno lo registra (OpenAI, o Claude anterior al registro), del effort
    guardado en la configuración del run o, si no hay, de la configuración
    actual. Valores distintos entre los raw, o con el guardado, fallan."""
    en_los_raw: set[str] = set()
    for archivo in run_dir.glob("etapa4_*_raw/*_*.json"):
        parametros = cargar_json(archivo).get("parametros_thinking")
        if isinstance(parametros, dict):
            en_los_raw.add(str((parametros.get("output_config") or {}).get("effort", "")))
    distintos = en_los_raw | ({registrado} if en_los_raw and registrado is not None else set())
    if len(distintos) > 1:
        raise ValueError(f"{run_dir}: los raw de los jueces (y {archivo_config}) no concuerdan "
                         f"en el effort: {sorted(distintos)}; no se sabe con cuál repetir E4.")
    if en_los_raw:
        return en_los_raw.pop(), "raw"
    if registrado is not None:
        return registrado, archivo_config
    return settings.effort_llm, "configuracion_actual"


def _config_del_run(meta_run: dict[str, Any]) -> dict[str, Any]:
    """Modelos, umbrales e interruptores de E4 con que corrió el run."""
    return {
        "modelo_extraccion": meta_run["modelo_extraccion"],
        "modelo_juez_matching": meta_run.get("modelo_juez_matching") or "",
        # Sin la clave, el run es anterior a la pasada 4e (B0, B1): no se enciende.
        "juez_redaccion": bool(meta_run.get("juez_redaccion", False)),
        "modelo_embeddings": meta_run.get("modelo_embeddings") or settings.modelo_embeddings,
        "top_k_candidatos": int(meta_run.get("top_k_candidatos", settings.top_k_candidatos)),
        "threshold_descripcion": float(
            meta_run.get("threshold_descripcion", settings.threshold_descripcion)),
        "threshold_accion": float(meta_run.get("threshold_accion", settings.threshold_accion)),
    }


def _asignacion_global_del_run(meta_run: dict[str, Any]) -> bool:
    """La asignación global con que corrió el run. No rige en la repetición
    (lo que se mide es la del proceso), pero queda al lado para saber si la
    repetición midió el interruptor. Sin la clave, el run es anterior al
    interruptor (B0-B2): emparejó en orden."""
    return bool(meta_run.get("asignacion_global", False))


def aviso_asignacion_global(del_run: bool, del_proceso: bool) -> str | None:
    """El aviso de una repetición con la misma asignación global que el run
    (None si difieren): no mide el interruptor. No es un error (así se repite
    B2 con la caché estricta), pero el control de PD26 lanzado sin
    ASIGNACION_GLOBAL=false sobre un run nuevo, encendido, quedaría en verde
    (todo desde la caché, el mismo conteo) sin haber medido nada."""
    if del_run != del_proceso:
        return None
    return (f"AVISO: la repetición usa la misma asignación global que el run ({del_run}): no "
            "mide el interruptor" + (" (el control de PD26 repite con ASIGNACION_GLOBAL=false)"
                                     if del_run else ""))


def _repetir(run_dir: Path, salida: Path, original: ReporteInforme | None,
             contexto: _ContextoE5, hallazgos_pdf: list[Hallazgo],
             hallazgos_excel: list[Hallazgo], gt: _EvaluacionGt | None,
             origen: _OrigenVectores | None, cache_jueces: CacheJueces | None,
             origen_effort: str, asignacion_global_run: bool,
             codigo_congelado: dict[str, Any] | None) -> dict[str, Any]:
    estricto = cache_jueces is not None and cache_jueces.modo == "estricto"
    prueba_clave = None
    if not estricto:   # la repetición estricta no llama a la API: no exige claves
        _validar_credenciales()
        # PD66: la clave de OpenAI responde antes de pagar el juez (ni la salida existe).
        prueba_clave = probar_clave_openai(etapa4_matching.calcular_embeddings)

    salida.mkdir(parents=True, exist_ok=True)
    for nombre in HASHES_INSUMOS:
        if (run_dir / nombre).is_file():
            shutil.copyfile(run_dir / nombre, salida / nombre)
    cargados = len(origen[1]) if origen else 0
    vectores: Vectores = dict(origen[1]) if origen else {}
    t0, inicio = time.monotonic(), datetime.now()
    try:
        resultados, metas = ejecutar_matching(
            hallazgos_pdf, hallazgos_excel, vectores=vectores, vectores_estrictos=estricto,
            llamar=cache_jueces)
    except Exception as exc:
        metas_pagadas = getattr(exc, "llm_metadata", None)
        if isinstance(metas_pagadas, list):
            _guardar_metas_e4(salida, metas_pagadas)
        if len(vectores) > cargados:   # pagados en esta repetición; no tapan el error de E4
            try:
                guardar_vectores(salida, vectores, settings.modelo_embeddings)
            except Exception as error_vectores:
                exc.add_note(f"Tampoco se guardaron los vectores de E4: {error_vectores}")
        raise
    if len(vectores) > cargados:
        guardar_vectores(salida, vectores, settings.modelo_embeddings)
    reporte = consolidar_reporte(resultados, *contexto)
    guardar_json(salida, "etapa4_matches.json", [r.model_dump(mode="json") for r in resultados])
    _guardar_metas_e4(salida, metas)
    guardar_json(salida, "reporte_final.json", reporte.model_dump(mode="json"))
    comparador_gt = None
    if gt is not None:
        aplicable, (sha_informe, sha_excel), ev_original = gt
        ev_replay = evaluar(reporte, aplicable.gt, sha256_informe=sha_informe,
                            sha256_excel=sha_excel, run_id=salida.name)
        comparador_gt = evaluacion_repeticion(aplicable, ev_original, ev_replay)
    metadata = {
        "modo": MODO_REPLAY_E4,
        "run_origen": run_dir.name,
        "modelo_extraccion": settings.modelo_extraccion,
        "modelo_juez_matching": settings.modelo_juez_matching or None,
        # El respaldo del proceso (el run no lo guarda en config_e4.json): si una
        # llamada lo usó, su raw lo dice (fallback_por_error).
        "modelo_extraccion_fallback": settings.modelo_extraccion_fallback or None,
        "modelo_embeddings": settings.modelo_embeddings,
        "asignacion_global": settings.asignacion_global,
        "asignacion_global_run": asignacion_global_run,
        "descripcion_identica": settings.descripcion_identica,
        "control_codigos": settings.control_codigos,
        "unificar_copias": settings.unificar_copias,
        "juez_justifica_primero": settings.juez_justifica_primero,
        "aviso_asignacion_global": aviso_asignacion_global(asignacion_global_run,
                                                           settings.asignacion_global),
        "juez_redaccion": settings.juez_redaccion,
        "top_k_candidatos": settings.top_k_candidatos,
        "threshold_descripcion": settings.threshold_descripcion,
        "threshold_accion": settings.threshold_accion,
        "effort_llm": settings.effort_llm,
        "effort_llm_origen": origen_effort,
        "llamadas_juez_reintento": contar_reintentos(metas),
        "copias_unificadas": contar_copias_unificadas(resultados),
        **_tokens_e4(metas),
        "cache_jueces": ({**cache_jueces.resumen(), "desde": cache_jueces.desde}
                         if cache_jueces else {"modo": "no"}),
        "prueba_clave_openai": prueba_clave,
        "vectores": {
            "origen": origen[2] if origen else None,
            "archivo": origen[0].name if origen else None,
            "sha256": _sha256(origen[0]) if origen else None,
            "cargados": cargados,
            "calculados": len(vectores) - cargados,
        },
        "conteo_original": _conteo(original.resumen) if original is not None else None,
        "conteo_replay": _conteo(reporte.resumen),
        "comparador_gt": comparador_gt,
        "fecha_inicio": inicio.isoformat(),
        "fecha_fin": datetime.now().isoformat(),
        "duracion_segundos": round(time.monotonic() - t0, 1),
        "version_codigo": version_codigo(),
        # La copia congelada de src/ contra la que se verificó (None sin el flag).
        "codigo_congelado": codigo_congelado,
    }
    guardar_json(salida, "metadata.json", metadata)
    return metadata


def _items_redaccion(user_prompt: str) -> list[dict[str, Any]]:
    """Los ítems (JSON) del prompt del juez de redacción (prompts.user_juez_redaccion)."""
    inicio = user_prompt.index("[")
    items, _ = json.JSONDecoder().raw_decode(user_prompt, inicio)
    if not isinstance(items, list) or not all(isinstance(i, dict) and "id" in i for i in items):
        raise ValueError("el prompt del juez de redacción no trae la lista de ítems")
    return items


_RE_MATCHING = re.compile(
    r'Hallazgo del PDF:\n  "(?P<pdf>.*)"\n\nCandidatos del Excel \(por índice\):\n'
    r"(?P<candidatos>.*)\n\n¿Cuál candidato", re.DOTALL)
_RE_SIMILITUD_DETALLE = re.compile(r"[Ss]imilitud semántica (\d+\.\d\d)")


def partes_matching(user_prompt: str) -> tuple[str, list[str]]:
    """(descripción del PDF, candidatos en el orden mostrado) del prompt del juez
    de matching (prompts.user_juez_matching)."""
    m = _RE_MATCHING.match(user_prompt)
    if m is None:
        raise ValueError("no es un prompt del juez de matching")
    partes = re.split(r"(?:^|\n)  \[(\d+)\] ", m["candidatos"])
    if partes[0] or [int(i) for i in partes[1::2]] != list(range(len(partes) // 2)):
        raise ValueError("los candidatos del prompt del juez de matching no están numerados 0..n")
    return m["pdf"], partes[2::2]


def _numero(ruta: Path) -> int:
    m = re.fullmatch(r"[a-z]+_(\d+)", ruta.stem)
    return int(m[1]) if m else -1


def verificar_similitudes(run_dir: Path, vectores: Vectores) -> dict[str, Any]:
    """Recalcula con `vectores` lo que el run guardó de las similitudes, para
    comprobar que unos vectores recalculados (D1) son los que vio E4:
    - a 4 decimales, las de la traza de cada lote del juez de redacción y las
      de las equivalencias del reporte;
    - a 2 decimales, la del detalle de cada diferencia de descripción o acción
      del reporte («Similitud semántica 0.76…»);
    - el orden de los candidatos que vio el juez de matching (top-k de mayor a
      menor similitud): si cambia, cambia el prompt y la caché no lo encuentra.
      Solo compara el orden de los candidatos mostrados, no su pertenencia al
      top-k: otro candidato que entra al quinto lugar por un empate (Beta con
      Opus, judge_96, en D1) recién lo detecta la repetición estricta.
    Un texto sin vector cuenta como distinto (recalculada None)."""
    distintas: list[dict[str, Any]] = []
    comparadas = 0

    def comparar(origen: str, ident: int, texto_pdf: str, texto_excel: str,
                 guardada: float, decimales: int = 4) -> None:
        nonlocal comparadas
        comparadas += 1
        a, b = vectores.get(texto_pdf), vectores.get(texto_excel)
        recalculada = (None if a is None or b is None
                       else round(similitud_coseno(a, b), decimales))
        if recalculada != guardada:
            distintas.append({"origen": origen, "id": ident, "guardada": guardada,
                              "recalculada": recalculada})

    for archivo in sorted((run_dir / "etapa4_redaccion_raw").glob("redaccion_*.json"),
                          key=_numero):
        raw = cargar_json(archivo)
        if raw.get("llamada_fallida"):
            continue   # sin el prompt no se sabe qué textos eran
        por_id = {i["id"]: i for i in _items_redaccion(raw["user_prompt_text"])}
        for traza in raw["lote"]:
            item = por_id[traza["id"]]
            comparar(f"etapa4_redaccion_raw/{archivo.name}", traza["id"], item["texto_pdf"],
                     item["texto_excel"], traza["similitud"])
    if (run_dir / "reporte_final.json").is_file():
        for idx, r in enumerate(cargar_json(run_dir / "reporte_final.json")["resultados"]):
            for e in r.get("equivalencias_redaccion") or []:
                comparar("reporte_final.json", idx, e["valor_pdf"], e["valor_excel"],
                         e["similitud"])
            for d in r.get("diferencias") or []:
                m = _RE_SIMILITUD_DETALLE.search(d.get("detalle") or "")
                if m and d["campo"] in ("descripcion", "accion_correctiva"):
                    comparar("reporte_final.json:diferencias", idx, d["valor_pdf"],
                             d["valor_excel"], float(m[1]), decimales=2)

    consultas = 0
    fuera_de_orden: list[dict[str, Any]] = []
    for archivo in sorted((run_dir / "etapa4_llm_judge_raw").glob("judge_*.json"), key=_numero):
        raw = cargar_json(archivo)
        if raw.get("llamada_fallida"):
            continue
        pdf, candidatos = partes_matching(raw["user_prompt_text"])
        consultas += 1
        textos = [pdf, *candidatos]
        if any(t not in vectores for t in textos):
            fuera_de_orden.append({"origen": f"etapa4_llm_judge_raw/{archivo.name}",
                                   "similitudes": None})
            continue
        sims = [similitud_coseno(vectores[pdf], vectores[c]) for c in candidatos]
        if any(a < b for a, b in itertools.pairwise(sims)):
            fuera_de_orden.append({"origen": f"etapa4_llm_judge_raw/{archivo.name}",
                                   "similitudes": [round(x, 4) for x in sims]})
    return {"comparadas": comparadas, "distintas": distintas,
            "orden_top_k": {"consultas": consultas, "fuera_de_orden": fuera_de_orden}}


def calcular_vectores_del_run(run_dir: Path, destino: Path) -> dict[str, Any]:
    """Calcula (paga) los vectores de E4 de un run con su modelo de embeddings y
    los escribe en `destino` (.npz, que no debe existir), con `destino`.json al
    lado: uso, sha256 del npz y `verificar_similitudes` contra lo que guardó
    el run. El run no cambia. Devuelve lo que escribe en el .json."""
    run_dir = run_dir.resolve()
    ficha = destino.with_suffix(".json")
    if destino.suffix != ".npz":
        raise ValueError(f"--solo-vectores: {destino} debe terminar en .npz")
    if ruta_dentro_de(destino, settings.runs_dir):
        raise ValueError(f"--solo-vectores debe quedar fuera de {settings.runs_dir} (la "
                         "retención podría borrarlo).")
    if ruta_dentro_de(destino, run_dir):
        raise ValueError(f"--solo-vectores no puede quedar dentro del run de origen {run_dir} "
                         "(invariante 20).")
    for ruta in (destino, ficha):
        exigir_ignorada_por_git(ruta, "--solo-vectores")   # el npz lleva los textos
        if ruta.exists():
            raise FileExistsError(f"{ruta} ya existe: son vectores pagados, no se pisan.")
    hallazgos_pdf, hallazgos_excel = _hallazgos(run_dir)
    modelo = _config_guardada(run_dir)[0].get("modelo_embeddings") or settings.modelo_embeddings
    if not settings.openai_api_key:
        raise CredencialesFaltantesError(
            "Falta OPENAI_API_KEY en .env (los embeddings siempre usan OpenAI).")

    textos = textos_a_embeber(hallazgos_pdf, hallazgos_excel)
    anterior = settings.modelo_embeddings
    settings.modelo_embeddings = modelo
    try:
        matriz, uso = etapa4_matching.calcular_embeddings(textos)
    finally:
        settings.modelo_embeddings = anterior
    vectores = {texto: matriz[i] for i, texto in enumerate(textos)}
    escribir_vectores(destino, vectores, modelo)
    resumen = {
        "run_origen": run_dir.name,
        "modelo_embeddings": modelo,
        "textos": len(textos),
        "dimension": int(matriz.shape[1]) if textos else 0,
        "uso": uso,
        "sha256_npz": _sha256(destino),
        "similitudes": verificar_similitudes(run_dir, vectores),
        "fecha": datetime.now().isoformat(),
        "version_codigo": version_codigo(),
    }
    guardar_json(ficha.parent, ficha.name, resumen)
    return resumen


def _imprimir_preflight(run_dir: Path, salida: Path, gt_dir: Path, *, vectores: Path | None,
                        cache: ModoCache, cache_desde: Path | None) -> None:
    """`preflight` desde la CLI: lo validado, o sale con el motivo (sin traza)."""
    try:
        r = preflight(run_dir, salida, gt_dir, vectores=vectores, cache=cache,
                      cache_desde=cache_desde)
    except (ValueError, OSError, VectoresFaltantesError, CredencialesFaltantesError) as exc:
        sys.exit(f"Preflight: {exc} (no se llamó a ninguna API ni se escribió nada)")
    v, c, gt = r["vectores"], r["cache_jueces"], r["comparador_gt"]
    print(f"run de origen: {r['run_origen']} ({r['modelo_extraccion']}, juez "
          f"{r['modelo_juez_matching'] or 'el mismo'}, respaldo: "
          f"{r['modelo_extraccion_fallback'] or '(ninguno)'})")
    print(f"asignación global: {r['asignacion_global']} (el run: {r['asignacion_global_run']}) · "
          f"descripción idéntica: {r['descripcion_identica']} · "
          f"control de códigos: {r['control_codigos']} · "
          f"copias unificadas: {r['unificar_copias']} · "
          f"juez justifica primero: {r['juez_justifica_primero']} · "
          f"juez de redacción: {r['juez_redaccion']} · effort: "
          f"{r['effort_llm'] or '(sin effort)'} ({r['effort_llm_origen']})")
    if r["aviso_asignacion_global"]:
        print(r["aviso_asignacion_global"])
    print(f"vectores: {v['cubiertos']} de {v['textos']} textos de E4 "
          f"({v['archivo'] or 'sin npz'})")
    if v["faltan"] and c["modo"] != "estricto":
        print(f"AVISO: faltan {v['faltan']} vectores: se pagarán sus embeddings y, con otros "
              "vectores, la caché puede no encontrar los jueces (¿npz de otro run?)")
    print(f"caché {c['modo']}" + (f" desde {c['desde']}: {c['cargadas']} respuestas"
                                  if c["modo"] != "no" else ""))
    print("sin GT del comparador para este informe y Excel" if gt is None
          else f"GT {gt['gt']}" + ("" if gt["original"] is None else
                                   f": original A {gt['original']['A']}, D {gt['original']['D']}, "
                                   f"sin adjudicar {gt['original']['sin_adjudicar']}"))
    print(f"credenciales: {r['credenciales']} · salida: {r['salida']} (sin contenido; fuera de "
          "git o ignorada por git)")
    print("Preflight OK: pasó todo lo que se valida antes de gastar, sin llamar a ninguna API ni "
          "escribir nada (la prueba de la clave de OpenAI es una llamada: corre al lanzar la "
          "repetición).")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run_dir", type=Path)
    destino = p.add_mutually_exclusive_group(required=True)
    destino.add_argument("--salida", type=Path,
                         help="carpeta nueva, p. ej. mediciones/replay_e4/<etiqueta>/<run_id>")
    destino.add_argument("--solo-vectores", type=Path, metavar="NPZ",
                         help="solo calcula (paga) y guarda los vectores de E4 del run, p. ej. "
                              "mediciones/b2/vectores_e4/<run_id>.npz")
    p.add_argument("--vectores", type=Path, default=None,
                   help="npz con los vectores de E4 del run (por defecto el "
                        "etapa4_embeddings.npz del run, si existe)")
    p.add_argument("--cache", choices=MODOS_CACHE, default="no",
                   help="respuestas de los jueces del run como caché: no (por defecto), "
                        "mixto (paga lo que falta) o estricto (sin API; falla ante un faltante)")
    p.add_argument("--cache-desde", type=Path, default=None, metavar="CARPETA",
                   help="toma la caché de los jueces de esa carpeta (p. ej. una repetición "
                        "anterior) en vez del run de origen; requiere --cache mixto o estricto")
    p.add_argument("--gt-comparador", type=Path, default=None,
                   help="carpeta de los GT del comparador (por defecto "
                        "mediciones/gt/comparador, si existe)")
    p.add_argument("--codigo-congelado", type=Path, default=None, metavar="CARPETA",
                   help="copia congelada de src/ de la repetición: el código que corre debe "
                        "ser ese, si no sale antes de gastar")
    p.add_argument("--preflight", action="store_true",
                   help="solo valida lo que se valida antes de gastar (código congelado, "
                        "insumos y configuración del run, vectores, caché, GT, salida, "
                        "credenciales presentes) y sale sin llamar a ninguna API ni escribir nada")
    a = p.parse_args()
    if a.preflight and a.solo_vectores is not None:
        p.error("--preflight es para la repetición (--salida), no para --solo-vectores")
    congelado = None
    if a.codigo_congelado is not None:
        try:
            congelado = verificar_codigo_congelado(a.codigo_congelado)
        except CodigoNoCongeladoError as exc:
            sys.exit(str(exc))
        print(f"Código congelado: {a.codigo_congelado} = el que corre "
              f"({congelado['sha256_codigo']})")
    if not (a.run_dir / "etapa3_pdf_hallazgos.json").exists():
        sys.exit(f"{a.run_dir} no tiene etapa3_pdf_hallazgos.json")
    if a.solo_vectores is not None:
        if a.vectores is not None or a.cache != "no":
            p.error("--solo-vectores no se combina con --vectores ni con --cache")
        resumen = calcular_vectores_del_run(a.run_dir, a.solo_vectores)
        sim = resumen["similitudes"]
        tokens = (resumen["uso"] or {}).get("tokens_total")
        print(f"{resumen['textos']} vectores de {resumen['run_origen']} en {a.solo_vectores} "
              f"({tokens} tokens de {resumen['modelo_embeddings']}); similitudes del run: "
              f"{sim['comparadas']} comparadas, {len(sim['distintas'])} distintas")
        return
    if a.vectores is not None and not a.vectores.is_file():
        sys.exit(f"--vectores: no existe {a.vectores}")
    if a.cache_desde is not None and (a.cache == "no" or not a.cache_desde.is_dir()):
        p.error("--cache-desde necesita una carpeta existente y --cache mixto o estricto")
    if a.gt_comparador is not None and not a.gt_comparador.is_dir():
        sys.exit(f"--gt-comparador: no existe la carpeta de GT del comparador {a.gt_comparador}")
    if a.preflight:
        _imprimir_preflight(a.run_dir, a.salida, a.gt_comparador or GT_DIR_DEFAULT,
                            vectores=a.vectores, cache=a.cache, cache_desde=a.cache_desde)
        return
    meta = reproducir_e4(a.run_dir, a.salida, a.gt_comparador or GT_DIR_DEFAULT,
                         vectores=a.vectores, cache=a.cache, cache_desde=a.cache_desde,
                         codigo_congelado=congelado)
    print(f"asignación global: {meta['asignacion_global']} (el run: "
          f"{meta['asignacion_global_run']}) · descripción idéntica: {meta['descripcion_identica']}"
          f" · control de códigos: {meta['control_codigos']}"
          f" · copias unificadas: {meta['unificar_copias']}"
          f" · juez justifica primero: {meta['juez_justifica_primero']}"
          f" · consultas extra: {meta['llamadas_juez_reintento']}")
    if meta["aviso_asignacion_global"]:
        print(meta["aviso_asignacion_global"])
    c, v = meta["cache_jueces"], meta["vectores"]
    if c["modo"] != "no":
        desde = f" (desde {c['desde']})" if a.cache_desde is not None else ""
        print(f"caché {c['modo']}{desde}: {c['desde_cache']} desde la caché, "
              f"{c['pagadas']} pagadas, {c['sin_usar']} sin usar")
    print(f"vectores: {v['cargados']} cargados ({v['origen'] or 'ninguno'}), "
          f"{v['calculados']} calculados")
    print(f"effort: {meta['effort_llm'] or '(sin effort)'} ({meta['effort_llm_origen']})")
    if meta["conteo_original"] is None:
        print("el run de origen no terminó: sin conteo original")
    antes = meta["conteo_original"] or {}
    for clave, despues in meta["conteo_replay"].items():
        print(f"  {clave:35s} {antes.get(clave, '-')!s:>4} → {despues:4d}")
    gt = meta["comparador_gt"]
    if gt is None:
        print("sin GT del comparador para este informe y Excel")
        return
    original = gt["original"] or {}
    print(f"GT {gt['gt']}: " + ", ".join(
        f"{c} {original.get(c, '-')} → {gt['replay'][c]}" for c in ("A", "D", "sin_adjudicar")))
    if gt["delta"] is None:
        return
    for clave in ("a_perdidos_nuevos", "posibles_escondidos_nuevos"):
        print(f"  {clave}: {gt['delta'][clave]}")
    for e in gt["delta"]["errores_excel"]:
        print(f"  error del Excel fila {e['fila_excel']}: {e['antes']} → {e['despues']}")


if __name__ == "__main__":
    main()
