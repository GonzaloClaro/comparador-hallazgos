"""Ver dentro de la herramienta la página citada del PDF, con la cita resaltada.

Solo para la UI. La página se renderiza a PNG desde el `input.pdf` del run (el
PDF con capa de texto; nunca el adecuado), con anotaciones que no se guardan.
El texto se ubica con el mismo algoritmo que la verificación de citas
(`comparador.citas`): el resaltado nunca contradice el estado del reporte.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

import fitz

from comparador.citas import FITZ_LOCK, normalizar, texto_de_palabras, ubicar
from comparador.schemas import CitaChecklist, EstadoCita, Hallazgo, VerificacionCita

DPI = 130
COLOR_DESCRIPCION = (1.0, 0.85, 0.0)   # amarillo
COLOR_ACCION = (0.55, 0.85, 1.0)       # celeste


class EstadoPdf(StrEnum):
    OK = "ok"
    FALTA = "falta"                    # run antiguo o borrado por la retención
    HASH_DISTINTO = "hash_distinto"    # el archivo no es el que se procesó


@dataclass(frozen=True)
class PdfDelRun:
    estado: EstadoPdf
    ruta: Path | None = None
    desde_docx: bool = False           # páginas del PDF convertido, no las de Word
    total: int = 0


@dataclass(frozen=True)
class Resaltado:
    texto: str
    parte: Literal["completa", "inicio", "final"]
    color: tuple[float, float, float]


@dataclass(frozen=True)
class PaginaVisor:
    pagina: int
    resaltados: tuple[Resaltado, ...] = ()


def _sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _hash(run_dir: Path, sufijo: str) -> str | None:
    ruta = run_dir / f"input_{sufijo}.hash"
    return ruta.read_text(encoding="utf-8").strip() if ruta.is_file() else None


def pdf_del_run(run_dir: Path) -> PdfDelRun:
    """El PDF con texto del run, si sigue ahí y es el que se procesó.

    Se acepta si su sha256 es el del PDF verificado (`input_pdf_texto.hash`),
    el que leyó el modelo (`input_pdf.hash`) o el subido (si no era un DOCX).
    Runs anteriores a 0.7.0 con PDF adecuado (sin `input_pdf_texto.hash`): el
    adecuado tiene la misma paginación que `input.pdf`, así que basta con que
    el adecuado calce; en un run 0.7.0 eso no alcanza, porque `input.pdf` tiene
    su propia huella registrada.
    """
    ruta = run_dir / "input.pdf"
    desde_docx = (run_dir / "input.docx").is_file()
    if not ruta.is_file():
        return PdfDelRun(EstadoPdf.FALTA, desde_docx=desde_docx)
    validos = {_hash(run_dir, "pdf_texto"), _hash(run_dir, "pdf")}
    if not desde_docx:
        validos.add(_hash(run_dir, "informe_original"))
    adecuado = run_dir / "input_adecuado.pdf"
    antiguo_adecuado = (
        _hash(run_dir, "pdf_texto") is None and adecuado.is_file()
        and _sha256(adecuado) == _hash(run_dir, "pdf")
    )
    calza = _sha256(ruta) in validos or antiguo_adecuado
    if not calza:
        return PdfDelRun(EstadoPdf.HASH_DISTINTO, desde_docx=desde_docx)
    with FITZ_LOCK, fitz.open(ruta) as doc:
        total = int(doc.page_count)
    return PdfDelRun(EstadoPdf.OK, ruta, desde_docx, total)


def _resaltados(
    texto: str | None, v: VerificacionCita | None, color: tuple[float, float, float]
) -> list[tuple[int, Resaltado]]:
    """(página, resaltado) de un texto según su verificación; nada si no se respaldó."""
    if not texto or v is None or not v.respaldada or v.pagina is None:
        return []
    if v.estado == EstadoCita.CONTINUA_PAGINA_SIGUIENTE:
        return [(v.pagina, Resaltado(texto, "inicio", color)),
                (v.pagina + 1, Resaltado(texto, "final", color))]
    return [(v.pagina, Resaltado(texto, "completa", color))]


def _agrupar(sin_resaltar: list[int], marcas: list[tuple[int, Resaltado]]) -> list[PaginaVisor]:
    paginas: dict[int, list[Resaltado]] = {p: [] for p in sin_resaltar}
    for pagina, resaltado in marcas:
        paginas.setdefault(pagina, []).append(resaltado)
    return [PaginaVisor(p, tuple(r)) for p, r in sorted(paginas.items())]


def paginas_hallazgo(h: Hallazgo) -> list[PaginaVisor]:
    """La página del hallazgo (y la siguiente si la fila sigue ahí), con la
    descripción en amarillo y la acción en celeste cuando están respaldadas."""
    ev = h.evidencia
    return _agrupar([ev.pagina_pdf] if ev.pagina_pdf else [], [
        *_resaltados(h.descripcion, ev.verificacion_descripcion, COLOR_DESCRIPCION),
        *_resaltados(h.accion_correctiva, ev.verificacion_accion, COLOR_ACCION),
    ])


def paginas_citas(citas: list[CitaChecklist]) -> list[PaginaVisor]:
    """Las páginas de las citas de un punto del checklist: resaltada la cita
    respaldada; sin resaltar la página de una cita que no se pudo verificar."""
    marcas: list[tuple[int, Resaltado]] = []
    sin_resaltar: list[int] = []
    for c in citas:
        propias = _resaltados(c.texto, c.verificacion, COLOR_DESCRIPCION)
        marcas += propias
        if not propias and c.pagina:
            sin_resaltar.append(c.pagina)
    return _agrupar(sin_resaltar, marcas)


_ROTULO_NO_PAGINA = re.compile(
    r"\b(?:tablas?|figuras?|secci[oó]n(?:es)?|cap[ií]tulos?|anexos?|art[ií]culos?|"
    r"numerales?|puntos?|ítems?|items?)\s+[\w.\-–]+(?:\s+a\s+[\w.\-–]+)?",
    re.IGNORECASE,
)
_MARCA_PAGINA = re.compile(r"\b(?:p[áa]g(?:ina)?s?\.?|pp\.)", re.IGNORECASE)


def paginas_mencionadas(
    texto: str | None, total: int, maximo: int = 30
) -> tuple[list[int], bool]:
    """Páginas de un texto libre como "2, 5-6 y 9" (columna Páginas del checklist).

    Es texto del modelo, sin verificar. No se toman como páginas los números de
    una tabla, figura o sección ("Tabla 6-4", "5.1.6.1"); si el texto dice
    "pág."/"páginas", solo los números que siguen. Un rango invertido son dos
    páginas sueltas. Devuelve hasta `maximo` páginas que existen en el PDF y si
    se recortaron otras.
    """
    texto = texto or ""
    marca = _MARCA_PAGINA.search(texto)
    if marca:
        texto = texto[marca.end():]
    texto = _ROTULO_NO_PAGINA.sub(" ", texto)
    texto = re.sub(r"\d+(?:\.\d+)+", " ", texto)
    paginas: list[int] = []
    for inicio, fin in re.findall(r"(\d+)\s*(?:[-–]\s*(\d+))?", texto):
        desde, hasta = int(inicio), int(fin) if fin else int(inicio)
        paginas.extend(range(desde, hasta + 1) if hasta >= desde else (desde, hasta))
    validas = [p for p in dict.fromkeys(paginas) if 1 <= p <= total]
    return validas[:maximo], len(validas) > maximo


@dataclass(frozen=True)
class PaginaRenderizada:
    png: bytes
    ubicados: int          # resaltados que se encontraron en la página
    repetidos: bool        # algún texto aparece más de una vez: se resaltan todas


def render_pagina(
    ruta: Path, pagina: int, resaltados: tuple[Resaltado, ...] = (), dpi: int = DPI
) -> PaginaRenderizada:
    """PNG de la página completa con los textos resaltados.

    Las anotaciones se agregan a una copia abierta en memoria que se cierra
    sin guardar: el PDF del run no cambia.
    """
    with FITZ_LOCK, fitz.open(ruta) as doc:
        page = doc[pagina - 1]
        texto = texto_de_palabras(page.get_text("words", sort=False), float(page.rect.height))
        ubicados, repetidos = 0, False
        for r in resaltados:
            cajas = ubicar(texto, r.texto, r.parte)
            if cajas:
                anotacion = page.add_highlight_annot([fitz.Rect(c) for c in cajas])
                anotacion.set_colors(stroke=r.color)
                anotacion.update()
                ubicados += 1
            if r.parte == "completa" and len(texto.apariciones(normalizar(r.texto))) > 1:
                repetidos = True
        png = page.get_pixmap(dpi=dpi, annots=True).tobytes("png")
    return PaginaRenderizada(bytes(png), ubicados, repetidos)
