"""Persistencia de runs: cada procesamiento guarda intermediates y metadata."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from comparador.config import settings


def crear_run_dir(modelo: str) -> Path:
    """Crea un directorio de run garantizado único.

    Resolución de segundos + sufijo incremental ante colisión: dos runs nunca
    comparten carpeta (compartirla corrompería el registro de auditoría, con
    ambos procesos pisándose los intermediates).
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    base = f"{timestamp}_{nombre_modelo_en_run(modelo)}"
    settings.runs_dir.mkdir(parents=True, exist_ok=True)

    nombre = base
    contador = 2
    while True:
        run_dir = settings.runs_dir / nombre
        try:
            run_dir.mkdir(exist_ok=False)
            break
        except FileExistsError:
            nombre = f"{base}-{contador}"
            contador += 1

    (run_dir / "etapa3_raw").mkdir(exist_ok=True)
    (run_dir / "etapa4_llm_judge_raw").mkdir(exist_ok=True)

    # En curso hasta terminar_run(): quien llama lo libera al terminar o fallar.
    with _LOCK_EN_CURSO:
        _EN_CURSO.add(run_dir.resolve())
    try:
        limpiar_runs_antiguos()
    except BaseException:
        terminar_run(run_dir)   # quien llamó no recibe la ruta: no podría liberarlo
        raise
    return run_dir


def nombre_modelo_en_run(modelo: str) -> str:
    """El modelo como va en el nombre de la carpeta del run: saneado, porque un
    fine-tune de OpenAI trae ":" (inválido en Windows y rechazado como
    identificador de run por comparador.feedback)."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", modelo)


# Runs que un proceso está escribiendo (Streamlit, server, evaluar_lote): la
# retención no los borra aunque otro run ocupe el cupo de incompletos. Pasa
# tras el botón Stop: la etapa ya enviada al modelo sigue en su hilo hasta
# terminar, y mientras tanto se puede iniciar otro procesamiento.
_EN_CURSO: set[Path] = set()
_LOCK_EN_CURSO = threading.Lock()


def en_curso(run_dir: Path) -> bool:
    """El run lo está escribiendo este proceso."""
    with _LOCK_EN_CURSO:
        return run_dir.resolve() in _EN_CURSO


def terminar_run(run_dir: Path) -> None:
    """El run dejó de escribirse (terminó, falló o se detuvo)."""
    with _LOCK_EN_CURSO:
        _EN_CURSO.discard(run_dir.resolve())


MODO_COMPLETO = "completo"
MODO_SOLO_CHECKLIST = "solo_checklist"
# Repetición de E4 + E5 fuera de runs/ (comparador.reproducir_e4).
MODO_REPLAY_E4 = "replay_e4"


def es_solo_checklist(run_dir: Path) -> bool:
    """El run corrió solo el checklist (`pipeline.ejecutar_solo_checklist`)."""
    try:
        meta = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(meta, dict) and meta.get("modo") == MODO_SOLO_CHECKLIST


def _run_completo(run_dir: Path) -> bool:
    """Un run terminó bien (reporte_final.json, o el checklist en un run solo
    checklist) o falló registrando el error (error.json).

    Es el criterio de la retención, no el del historial: server.list_runs y el
    historial de Streamlit listan como reabribles solo los runs con
    reporte_final.json.
    """
    return (
        (run_dir / "reporte_final.json").exists() or (run_dir / "error.json").exists()
        or es_solo_checklist(run_dir)
    )


def _mtime(run_dir: Path) -> float | None:
    try:
        return run_dir.stat().st_mtime
    except OSError:
        return None


def _borrar(run_dirs: list[Path]) -> list[Path]:
    borrados = []
    for run_dir in run_dirs:
        try:
            shutil.rmtree(run_dir)
            borrados.append(run_dir)
        except OSError as exc:
            warnings.warn(f"No se pudo borrar el run antiguo {run_dir}: {exc}", stacklevel=2)
    return borrados


def limpiar_runs_antiguos(
    retener: int | None = None, retener_incompletos: int | None = None
) -> list[Path]:
    """Conserva los runs más recientes y borra el resto.

    Ordena por mtime del directorio (no por nombre): hay runs históricos con
    formatos de timestamp distintos (con y sin segundos) que no comparan bien
    lexicográficamente entre sí.

    Los runs completos (terminados bien o con error.json) conservan `retener`
    los más recientes. Los incompletos (se cortaron a medio procesar, sin
    ninguno de los dos archivos) conservan solo `retener_incompletos` — alcanza
    con el más reciente para poder inspeccionar qué venía pasando; el resto no
    aporta nada de valor de auditoría.

    Un run incompleto que sigue siendo el más reciente de su categoría
    sobrevive aunque esté efectivamente en curso — solo se podan los
    incompletos MÁS VIEJOS que ese, nunca el que podría estar corriendo ahora.
    """
    if retener is None:
        retener = settings.runs_a_retener
    if retener_incompletos is None:
        retener_incompletos = settings.runs_incompletos_a_retener

    if not settings.runs_dir.exists():
        return []

    with _LOCK_EN_CURSO:
        en_curso = set(_EN_CURSO)
    # Otra sesión u otro proceso puede borrar un run entre el iterdir y el stat.
    con_fecha = [(m, d) for d in settings.runs_dir.iterdir()
                 if d.is_dir() and d.resolve() not in en_curso
                 and (m := _mtime(d)) is not None]
    candidatos = [d for _, d in sorted(con_fecha, key=lambda par: par[0], reverse=True)]

    completos = [d for d in candidatos if _run_completo(d)]
    incompletos = [d for d in candidatos if not _run_completo(d)]

    return _borrar(completos[retener:]) + _borrar(incompletos[retener_incompletos:])


def guardar_hash_input(run_dir: Path, ruta: Path, sufijo: str) -> str:
    sha = hashlib.sha256(ruta.read_bytes()).hexdigest()
    (run_dir / f"input_{sufijo}.hash").write_text(sha, encoding="utf-8")
    return sha


def guardar_json(run_dir: Path, nombre: str, data: Any) -> Path:
    ruta = run_dir / nombre
    ruta.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return ruta


def guardar_llm_raw(run_dir: Path, subcarpeta: str, nombre: str, metadata: dict[str, Any]) -> Path:
    carpeta = run_dir / subcarpeta
    carpeta.mkdir(exist_ok=True)
    ruta = carpeta / f"{nombre}.json"
    ruta.write_text(json.dumps(metadata, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8")
    return ruta


# Vectores de embeddings de E4 (M70), en la raíz del run: no van como .json en
# un *_raw/ porque metricas_lote cuenta cada uno de esos archivos como una llamada.
ARCHIVO_VECTORES = "etapa4_embeddings.npz"
# Configuración de E4, empresa y metadatos del informe, guardados antes de E4:
# reproducir_e4 repite E4 y E5 de un run que falló después de pagar el
# checklist, E1 y E3 (sin metadata.json ni reporte_final.json).
ARCHIVO_CONFIG_E4 = "config_e4.json"


def guardar_vectores(run_dir: Path, vectores: dict[str, NDArray[np.float64]], modelo: str) -> Path:
    """Los vectores de E4 del run en `etapa4_embeddings.npz` (ver escribir_vectores)."""
    ruta = run_dir / ARCHIVO_VECTORES
    escribir_vectores(ruta, vectores, modelo)
    return ruta


def escribir_vectores(ruta: Path, vectores: dict[str, NDArray[np.float64]], modelo: str) -> None:
    """npz con los textos (unicode), la matriz de vectores (fila i = textos[i])
    y el modelo de embeddings. Nunca pisa un archivo existente: son vectores pagados.

    La matriz va en float32, lo que entrega la API (el SDK de OpenAI los recibe
    en base64 float32), salvo que no sean float32 exactos: entonces en float64.
    Así la ida y vuelta (cargar_vectores) devuelve exactamente los mismos
    números y E4 se repite igual. Un texto que numpy no conserva (termina en
    NUL) falla antes de escribir.
    """
    textos = list(vectores)
    arreglo_textos = np.array(textos, dtype=np.str_)
    if [str(t) for t in arreglo_textos] != textos:
        raise ValueError("Un texto de E4 no se conserva en el npz (numpy quita los NUL finales).")
    dim = len(next(iter(vectores.values()))) if vectores else 0
    matriz = np.array([vectores[t] for t in textos], dtype=np.float64).reshape(len(textos), dim)
    en_float32 = matriz.astype(np.float32)
    exacta = np.array_equal(en_float32.astype(np.float64), matriz)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("xb") as archivo:
        np.savez(archivo, textos=arreglo_textos, vectores=en_float32 if exacta else matriz,
                 modelo=np.array(modelo, dtype=np.str_))


def cargar_vectores(ruta: Path) -> tuple[dict[str, NDArray[np.float64]], str]:
    """(texto → vector en float64, modelo de embeddings) de un npz de
    escribir_vectores, sin pickle. Un archivo inconsistente falla ruidosamente."""
    with np.load(ruta, allow_pickle=False) as npz:
        faltan = {"textos", "vectores", "modelo"} - set(npz.files)
        if faltan:
            raise ValueError(f"{ruta}: le faltan {sorted(faltan)}")
        textos = [str(t) for t in npz["textos"]]
        matriz = npz["vectores"].astype(np.float64)
        modelo = str(npz["modelo"])
    if matriz.ndim != 2 or matriz.shape[0] != len(textos):
        raise ValueError(f"{ruta}: {len(textos)} textos y una matriz {matriz.shape}")
    if len(set(textos)) != len(textos):
        raise ValueError(f"{ruta}: textos repetidos")
    if not np.isfinite(matriz).all():
        raise ValueError(f"{ruta}: vectores con valores no finitos")
    return {texto: matriz[i] for i, texto in enumerate(textos)}, modelo


def _archivos_hasheados(raiz: Path) -> list[Path]:
    return sorted(
        p for p in raiz.rglob("*")
        if p.is_file() and p.suffix in (".py", ".yaml") and "__pycache__" not in p.parts
    )


def _hash_archivos(raiz: Path, base: Path) -> tuple[str, int]:
    """sha256 de los .py y .yaml bajo ``raiz`` (rutas relativas a ``base`` + contenido)."""
    h = hashlib.sha256()
    archivos = _archivos_hasheados(raiz)
    for p in archivos:
        h.update(str(p.relative_to(base)).encode())
        h.update(p.read_bytes())
    return h.hexdigest(), len(archivos)


def _hash_por_archivo(raiz: Path, base: Path) -> dict[str, str]:
    """Ruta relativa a ``base`` → sha256 de cada archivo que entra en _hash_archivos."""
    return {p.relative_to(base).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in _archivos_hasheados(raiz)}


_PAQUETE = Path(__file__).resolve().parent


def _corto(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()[:16]


def hash_arbol(src: Path) -> tuple[str, int]:
    """sha256 del árbol de código (rutas relativas + contenido) y cantidad de archivos.

    Cubre los .py y los .yaml (los criterios y el catálogo son parte de la
    versión). Es el hash de la ficha de versión (metricas_confianza).
    """
    return _hash_archivos(src, src)


def version_codigo() -> dict[str, Any]:
    """Huella del código y de los criterios con que corre un run.

    Sin ella no se sabe de qué versión es un run: las métricas, el feedback y
    las políticas de revisión caducan con cada cambio de código o de criterio.
    Recorre solo el paquete (con una instalación no editable, su carpeta padre
    es site-packages), con las rutas relativas que usa la ficha de versión, así
    que sha256_codigo coincide con su fila "actual". El catálogo es el que está
    configurado (settings.catalogo_empresas_path), no necesariamente el del paquete.
    """
    sha, archivos = _hash_archivos(_PAQUETE, _PAQUETE.parent)
    return {
        "sha256_codigo": sha[:16],
        "archivos_codigo": archivos,
        "sha256_checklist_puntos.yaml": _corto(_PAQUETE / "checklist_puntos.yaml"),
        "sha256_catalogo_empresas.yaml": _corto(settings.catalogo_empresas_path),
    }


class CodigoNoCongeladoError(ValueError):
    """El código que corre no es la copia congelada de la ronda (``--codigo-congelado``)."""


def verificar_codigo_congelado(carpeta: Path) -> dict[str, Any]:
    """Antes de gastar en una ronda: el código que corre debe ser la copia
    congelada ``carpeta`` (una copia de ``src/``, p. ej. ``mediciones/b3/src``).

    Compara ``version_codigo()`` con lo mismo calculado sobre la copia: el hash
    del árbol (``hash_arbol``, el de la ficha de versión que metricas_lote le da
    a la ronda, así que un archivo suelto fuera de ``comparador/`` también
    cuenta), los criterios del checklist y el catálogo configurado contra el de
    la copia. Devuelve la carpeta y el hash verificado; si algo difiere,
    ``CodigoNoCongeladoError`` con los archivos distintos.
    """
    paquete = carpeta / "comparador"
    if not paquete.is_dir():
        raise CodigoNoCongeladoError(
            f"--codigo-congelado: {carpeta} no es una copia de src/ (falta {paquete}).")
    actual = version_codigo()
    sha, archivos = hash_arbol(carpeta)
    congelada = {
        "sha256_codigo": sha[:16],
        "archivos_codigo": archivos,
        **{f"sha256_{nombre}": _corto(paquete / nombre) if (paquete / nombre).is_file()
           else "falta" for nombre in ("checklist_puntos.yaml", "catalogo_empresas.yaml")},
    }
    if congelada != actual:
        corre = _hash_por_archivo(_PAQUETE, _PAQUETE.parent)
        copia = _hash_por_archivo(carpeta, carpeta)
        distintos = sorted(k for k in corre.keys() | copia.keys() if corre.get(k) != copia.get(k))
        if congelada["sha256_catalogo_empresas.yaml"] != actual["sha256_catalogo_empresas.yaml"]:
            distintos.append(
                f"catalogo_empresas.yaml configurado ({settings.catalogo_empresas_path})")
        raise CodigoNoCongeladoError(
            f"--codigo-congelado: el código que corre (sha256 {actual['sha256_codigo']}, "
            f"{actual['archivos_codigo']} archivos) no es el de la copia congelada {carpeta} "
            f"(sha256 {congelada['sha256_codigo']}, {congelada['archivos_codigo']} archivos). "
            f"Distintos: {', '.join(distintos)}. Volver a copiar src/ o deshacer el cambio; "
            "no se llamó a ninguna API.")
    return {"carpeta": str(carpeta), "sha256_codigo": actual["sha256_codigo"],
            "archivos_codigo": actual["archivos_codigo"]}


def cargar_json(ruta: Path) -> Any:
    return json.loads(ruta.read_text(encoding="utf-8"))
