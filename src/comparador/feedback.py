"""Feedback del equipo revisor: dónde vive y cómo se lee y se guarda.

Vive en `settings.feedback_dir/<run_id>/` (por defecto `feedback/`), fuera de
`runs/` y de git: la retención automática de runs no lo toca (excepción
acotada a la regla 21 de CLAUDE.md, decisión del usuario 2026-10-18). Al
guardar se copian el `reporte_final.json`, el `version.json` y el
`inputs.json` del run, para que el feedback siga legible cuando la retención
borre el run. Un `feedback.json` anterior, dentro del run, se migra a
`feedback/` la primera vez que se lee.

Cada sesión guarda solo lo que ella cambió (`cambios` + `actualizar_feedback`),
sobre lo que hay en disco y bajo un lock de hilos y de procesos (Streamlit y
el server legacy son procesos distintos): dos pestañas de Streamlit no se
pisan y, si las dos cambian el comentario general, se conservan los dos
textos. La UI vanilla (legacy) reemplaza sus mapas de ✓/✗ y el comentario
(no toca SI/NO/N/A). Toda escritura es atómica, con un temporal propio.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from comparador.config import settings
from comparador.persistence import cargar_json
from comparador.rutas import ruta_dentro_de
from comparador.schemas import FeedbackRun, MotivoFeedback, MotivoIncorrecto, ReporteInforme

# Lo que ve el equipo revisor al marcar ✗ (los códigos están en el schema).
ETIQUETA_MOTIVO: dict[MotivoIncorrecto, str] = {
    MotivoIncorrecto.MISMA_INFORMACION: "Es la misma información, con otra redacción",
    MotivoIncorrecto.EMPAREJO_MAL: "Emparejó filas que no corresponden",
    MotivoIncorrecto.NO_ESTA_ASI_EN_PDF: "El hallazgo no está así en el PDF",
    MotivoIncorrecto.PANO_O_RELE: "Paño o relé equivocado",
    MotivoIncorrecto.ESCONDE_DIFERENCIA: "Dice que coincide, pero hay una diferencia",
    MotivoIncorrecto.OTRO: "Otro",
}

_COPIAS = ("reporte_final.json", "version.json", "inputs.json")
_MAPAS = ("veredictos_resultados", "motivos_resultados", "respuestas_checklist",
          "veredictos_checklist")
# Las sesiones de un mismo Streamlit (o de un mismo server legacy) son hilos:
# _LOCK las ordena; entre procesos, el archivo de bloqueo (_bloqueo).
_LOCK = threading.RLock()
_ESPERA_BLOQUEO_S = 15.0

# Respuestas del equipo revisor en el checklist, como en la planilla oficial.
RESPUESTAS_CHECKLIST = ("SI", "NO", "N/A")


class RunIdInvalidoError(ValueError):
    """El identificador no es el nombre de un run (posible path traversal)."""


def validar_run_id(run_id: str) -> str:
    if (not run_id or run_id in (".", "..") or Path(run_id).name != run_id
            or any(c in run_id for c in "/\\:\x00")):
        raise RunIdInvalidoError(f"Identificador de run inválido: {run_id!r}")
    return run_id


def _raiz() -> Path:
    """FEEDBACK_DIR, comprobado otra vez al usarlo (un cambio en caliente se
    salta el validador de la configuración): nunca dentro de runs/."""
    raiz = settings.feedback_dir.resolve()
    if ruta_dentro_de(raiz, settings.runs_dir):
        raise RuntimeError(f"La carpeta de feedback ({raiz}) está dentro de runs/: la "
                           "retención la borraría.")
    return raiz


def carpeta_feedback(run_id: str) -> Path:
    """La carpeta del feedback de un run; nunca dentro de runs/."""
    raiz = _raiz()
    carpeta = (raiz / validar_run_id(run_id)).resolve()
    if not carpeta.is_relative_to(raiz):
        raise RunIdInvalidoError(f"Identificador de run inválido: {run_id!r}")
    return carpeta


def cargar_feedback(run_id: str) -> FeedbackRun:
    """El feedback guardado del run. Uno anterior, dentro del run, se migra a
    feedback/ al leerlo: si no, la retención lo borraría con el run aunque la
    interfaz lo siga mostrando."""
    with _bloqueo():
        return _cargar(run_id)


def guardar_feedback(run_id: str, feedback: FeedbackRun,
                     reporte: ReporteInforme | None = None) -> Path:
    """Escribe el feedback completo (atómico: es trabajo humano que no se
    recupera) y deja en su carpeta una copia legible del reporte y su versión.
    Para guardar lo que cambió una sesión, `actualizar_feedback`.

    `reporte` es el que tiene abierto la interfaz: si la retención ya borró
    el run, se escribe desde memoria, porque sin él los índices del feedback
    no se pueden interpretar."""
    with _bloqueo():
        return _guardar(run_id, feedback, reporte)


def _cargar(run_id: str) -> FeedbackRun:
    nuevo = carpeta_feedback(run_id) / "feedback.json"
    if nuevo.exists():
        return FeedbackRun.model_validate(cargar_json(nuevo))
    antiguo = settings.runs_dir / validar_run_id(run_id) / "feedback.json"
    if antiguo.exists():
        feedback = FeedbackRun.model_validate(cargar_json(antiguo))
        # Migrar no es editar: conserva la fecha de la última actualización.
        _guardar(run_id, feedback.model_copy(deep=True), sellar=False)
        return feedback
    return FeedbackRun()


def _guardar(run_id: str, feedback: FeedbackRun, reporte: ReporteInforme | None = None,
             sellar: bool = True) -> Path:
    carpeta = carpeta_feedback(run_id)
    carpeta.mkdir(parents=True, exist_ok=True)
    run_dir = settings.runs_dir / run_id
    for nombre in _COPIAS:
        copia = carpeta / nombre
        if not _legible(copia) and (run_dir / nombre).exists():
            _escribir_atomico(copia, (run_dir / nombre).read_bytes())
    copia_reporte = carpeta / "reporte_final.json"
    if reporte is not None and not _legible(copia_reporte):
        _escribir_atomico(copia_reporte, reporte.model_dump_json(indent=2).encode())
    if sellar:
        feedback.actualizado = datetime.now()
    # Nunca se escribe un archivo que después no se pueda volver a cargar: el
    # modelo no valida al asignar (la UI lo modifica en el lugar).
    validado = FeedbackRun.model_validate(feedback.model_dump())
    ruta = carpeta / "feedback.json"
    _escribir_atomico(ruta, validado.model_dump_json(indent=2).encode())
    return ruta


@contextmanager
def _bloqueo() -> Iterator[None]:
    """Lock de hilos (reentrante) y, por fuera, uno del sistema operativo entre
    procesos sobre FEEDBACK_DIR/.feedback.lock (fcntl en mac y Linux, msvcrt en
    Windows). El archivo no se borra nunca: el sistema libera el bloqueo si el
    proceso muere, así que no hay bloqueos huérfanos que limpiar."""
    with _LOCK:
        if getattr(_BLOQUEO_HILO, "profundidad", 0):
            _BLOQUEO_HILO.profundidad += 1
            try:
                yield
            finally:
                _BLOQUEO_HILO.profundidad -= 1
            return
        raiz = _raiz()
        raiz.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(raiz / ".feedback.lock", os.O_CREAT | os.O_RDWR)
        try:
            limite = time.monotonic() + _ESPERA_BLOQUEO_S
            while not _tomar_bloqueo(descriptor):
                if time.monotonic() > limite:
                    # El mismo bloqueo protege lecturas y escrituras: el mensaje
                    # no dice cuál (cada llamador lo dice).
                    raise TimeoutError(
                        f"Otro proceso tiene tomado el feedback desde hace más de "
                        f"{_ESPERA_BLOQUEO_S:.0f} s.")
                time.sleep(0.01)
            _BLOQUEO_HILO.profundidad = 1
            try:
                yield
            finally:
                _BLOQUEO_HILO.profundidad = 0
                _soltar_bloqueo(descriptor)
        finally:
            os.close(descriptor)


if sys.platform == "win32":
    import msvcrt

    def _tomar_bloqueo(descriptor: int) -> bool:
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _soltar_bloqueo(descriptor: int) -> None:
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _tomar_bloqueo(descriptor: int) -> bool:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def _soltar_bloqueo(descriptor: int) -> None:
        fcntl.flock(descriptor, fcntl.LOCK_UN)


_BLOQUEO_HILO = threading.local()


@dataclass
class CambiosFeedback:
    """Lo que una sesión cambió desde su último guardado: por mapa, la clave y
    su valor nuevo (None = se quitó); `comentarios` None = no cambió."""

    mapas: dict[str, dict[str, Any]] = field(default_factory=dict)
    comentarios: str | None = None
    # El comentario que la sesión tenía guardado: si el de disco es otro, lo
    # cambió otra sesión y se conservan los dos.
    comentarios_antes: str = ""

    def __bool__(self) -> bool:
        return any(self.mapas.values()) or self.comentarios is not None

    def aplicar(self, feedback: FeedbackRun) -> None:
        for campo, cambios in self.mapas.items():
            mapa: dict[str, Any] = getattr(feedback, campo)
            for clave, valor in cambios.items():
                if valor is None:
                    mapa.pop(clave, None)
                else:
                    mapa[clave] = valor.model_copy() if isinstance(valor, BaseModel) else valor
        if self.comentarios is not None:
            feedback.comentarios = _fusionar_comentario(
                feedback.comentarios, self.comentarios_antes, self.comentarios)


def _fusionar_comentario(en_disco: str, antes: str, nuevo: str) -> str:
    if en_disco in (antes, nuevo):
        return nuevo
    # Otra sesión lo cambió mientras tanto: no se pisa ni se borra su texto.
    if antes and nuevo.startswith(antes):
        # Esta sesión agregó al final: se suma solo lo nuevo, en el orden en que
        # se guardó (así lo que tenía la otra sigue siendo el comienzo).
        return en_disco + nuevo[len(antes):]
    if antes and en_disco.startswith(antes):
        # La otra agregó y esta corrigió o vació su texto: el cambio queda en su
        # lugar y lo de la otra, después (vaciar deja solo lo de la otra).
        resto = en_disco[len(antes):]
        return nuevo + resto if nuevo.strip() else resto.lstrip()
    return "\n\n".join(texto for texto in (en_disco, nuevo) if texto.strip())


def cambios(antes: FeedbackRun, despues: FeedbackRun) -> CambiosFeedback:
    mapas = {}
    for campo in _MAPAS:
        a, d = getattr(antes, campo), getattr(despues, campo)
        mapas[campo] = {k: d.get(k) for k in a.keys() | d.keys() if a.get(k) != d.get(k)}
    comentarios = despues.comentarios if despues.comentarios != antes.comentarios else None
    return CambiosFeedback(mapas, comentarios, antes.comentarios)


def actualizar_feedback(run_id: str, cambiar: Callable[[FeedbackRun], None],
                        reporte: ReporteInforme | None = None) -> FeedbackRun:
    """Relee lo guardado, aplica `cambiar` y lo guarda, todo bajo el lock: lo
    que otra sesión guardó mientras tanto se conserva. Un motivo cuyo resultado
    dejó de ser ✗ se descarta. Devuelve el feedback guardado."""
    with _bloqueo():
        feedback = _cargar(run_id)
        cambiar(feedback)
        feedback.motivos_resultados = motivos_vigentes(feedback)
        _guardar(run_id, feedback, reporte)
        return feedback


def _legible(ruta: Path) -> bool:
    """Existe y es JSON completo (una copia cortada a medias se rehace)."""
    try:
        json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return True


def _escribir_atomico(ruta: Path, contenido: bytes) -> None:
    descriptor, temporal = tempfile.mkstemp(dir=ruta.parent, prefix=f".{ruta.name}.",
                                            suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as archivo:
            archivo.write(contenido)
        for intento in range(20):
            try:
                os.replace(temporal, ruta)
                break
            except PermissionError:
                # Windows: falla mientras otro programa (antivirus, indexador)
                # tiene abierto el destino un instante.
                if intento == 19:
                    raise
                time.sleep(0.05)
    finally:
        if os.path.exists(temporal):
            os.unlink(temporal)


def motivos_vigentes(feedback: FeedbackRun) -> dict[str, MotivoFeedback]:
    """Los motivos de los resultados que siguen marcados ✗. Streamlit borra el
    motivo cuando el veredicto deja de ser ✗; un feedback editado en la UI
    vanilla o escrito antes puede conservar uno huérfano."""
    return {clave: m for clave, m in feedback.motivos_resultados.items()
            if feedback.veredictos_resultados.get(clave) == "incorrecto"}


def aplicar_respuestas(valores: Sequence[object], almacen: dict[str, str],
                       claves: list[str]) -> bool:
    """Aplica una columna de respuestas al almacén. Lo que no es SI/NO/N/A
    («— sin revisar», o una celda vaciada, que la grilla entrega como NaN o
    None) cuenta como sin respuesta. Devuelve si algo cambió (para guardar
    solo entonces)."""
    cambio = False
    for clave, crudo in zip(claves, valores, strict=True):
        valor = crudo if crudo in RESPUESTAS_CHECKLIST else None
        if valor != almacen.get(clave):
            cambio = True
            if valor:
                almacen[clave] = valor
            else:
                almacen.pop(clave, None)
    return cambio
