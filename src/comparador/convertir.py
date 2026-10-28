"""Conversión de insumos a PDF apto para el LLM.

Dos responsabilidades:
1. DOCX → PDF. Preferencia: LibreOffice headless si está instalado (máxima
   fidelidad de tablas). Fallback: mammoth + xhtml2pdf, 100% Python, sin
   binarios ni apps externas — verificado que preserva las Tablas Resumen
   de hallazgos legibles (2026-07-07). Las imágenes que PIL no sabe abrir
   (EMF/WMF de Word) se reemplazan por un aviso visible en el PDF.
2. Adecuar PDFs a los límites del proveedor. Con Claude (modelos de 1M de
   contexto) no hace falta: los PDFs grandes van por Files API y los que no
   caben en contexto se trocean por tokens (ver etapa0/etapa1). Con otros
   modelos (OpenAI, Haiku 4.5) un informe de más de 100 páginas falla con un
   error claro (decisión del usuario 2026-10-18: recortarlo daba «no cumple» y
   faltas falsas por páginas que el modelo nunca vio); uno que solo excede el
   tamaño se rasteriza completo, sin recortar.
"""

from __future__ import annotations

import base64
import io
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from comparador.config import settings

MAX_PAGINAS_OTROS = 100
MAX_BYTES_OTROS = 25_000_000  # margen bajo los 32MB de request (base64 infla ~33%)


class ConversionError(Exception):
    """No fue posible convertir el archivo a PDF."""


class PdfExcedeLimitesError(Exception):
    """El informe no cabe en un request del modelo elegido y no se recorta."""


def convertir_docx_a_pdf(
    ruta_docx: Path, ruta_pdf: Path
) -> tuple[Path, dict[str, Any] | None]:
    """Convierte un DOCX a PDF. LibreOffice si está; si no, mammoth+xhtml2pdf.

    Devuelve (ruta del PDF, info). La info no es None si la conversión perdió
    algo (imágenes no convertibles): el caller la persiste y la muestra.
    """
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        res = subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf",
             "--outdir", str(ruta_pdf.parent), str(ruta_docx)],
            capture_output=True, text=True, timeout=600,
        )
        generado = ruta_pdf.parent / (ruta_docx.stem + ".pdf")
        if res.returncode == 0 and generado.exists():
            if generado != ruta_pdf:
                generado.rename(ruta_pdf)
            return ruta_pdf, None
        # Si LibreOffice está pero falla, se cae al fallback puro Python.

    return _convertir_docx_python(ruta_docx, ruta_pdf)


def _convertir_docx_python(
    ruta_docx: Path, ruta_pdf: Path
) -> tuple[Path, dict[str, Any] | None]:
    """Fallback puro Python: DOCX → HTML (mammoth) → PDF (xhtml2pdf)."""
    import mammoth
    from PIL import Image
    from xhtml2pdf import pisa

    omitidas: list[str] = []

    def _convertir_imagen(imagen: Any) -> dict[str, str]:
        with imagen.open() as f:
            datos = f.read()
        try:
            with Image.open(io.BytesIO(datos)) as im:
                im.load()
        except Exception:
            # EMF/WMF (vectores de Windows) no se pueden rasterizar sin
            # LibreOffice: se marcan visibles en el PDF y se cuentan.
            omitidas.append(str(imagen.content_type))
            return {"src": "", "alt": f"[IMAGEN NO CONVERTIBLE: {imagen.content_type}]"}
        return {"src": f"data:{imagen.content_type};base64,{base64.b64encode(datos).decode()}"}

    with open(ruta_docx, "rb") as f:
        html = mammoth.convert_to_html(
            f, convert_image=mammoth.images.img_element(_convertir_imagen)
        ).value
    # xhtml2pdf no muestra el alt de una imagen vacía: el aviso va como texto.
    html = html.replace('<img alt="[IMAGEN NO CONVERTIBLE:', "<p><b>[IMAGEN NO CONVERTIBLE:")
    html = html.replace(']" src="" />', "]</b></p>")

    # xhtml2pdf necesita un documento con <head> para el charset de tildes.
    documento = f'<html><head><meta charset="utf-8"></head><body>{html}</body></html>'
    try:
        with open(ruta_pdf, "wb") as salida:
            estado = pisa.CreatePDF(documento, dest=salida, encoding="utf-8")
    except Exception as exc:
        ruta_pdf.unlink(missing_ok=True)  # no dejar un PDF parcial engañoso
        raise ConversionError(f"Falló la conversión DOCX→PDF (mammoth+xhtml2pdf): {exc}") from exc

    if estado.err or not ruta_pdf.exists() or ruta_pdf.stat().st_size == 0:
        ruta_pdf.unlink(missing_ok=True)
        raise ConversionError(
            f"Falló la conversión DOCX→PDF (mammoth+xhtml2pdf): {estado.err} errores."
        )
    info = None
    if omitidas:
        info = {"imagenes_omitidas": len(omitidas), "tipos_omitidos": sorted(set(omitidas))}
    return ruta_pdf, info


def _usa_limites_claude(modelo: str) -> bool:
    """Modelos Claude de 1M de contexto: 600 páginas por request y Files API.

    Haiku 4.5 es el único Claude vigente de 200k (100 páginas).
    """
    return modelo.startswith("claude") and not modelo.startswith("claude-haiku-4")


def exceso_de_limites(pdf: bytes, modelo: str) -> str | None:
    """Por qué el PDF no cabe tal cual en `modelo` (None si cabe).

    Es para el modelo de respaldo (MODELO_EXTRACCION_FALLBACK), que no pasa
    por adecuar_pdf_para_llm: esa adecuación se hace para MODELO_EXTRACCION.
    """
    if _usa_limites_claude(modelo):
        return None
    paginas = len(PdfReader(io.BytesIO(pdf)).pages)
    if paginas > MAX_PAGINAS_OTROS:
        return f"tiene {paginas} páginas y acepta hasta {MAX_PAGINAS_OTROS}"
    if len(pdf) > MAX_BYTES_OTROS:
        return (f"pesa {len(pdf) / 1e6:.1f} MB y acepta hasta "
                f"{MAX_BYTES_OTROS / 1e6:.0f} MB")
    return None


def adecuar_pdf_para_llm(
    ruta_pdf: Path, modelo: str | None = None
) -> tuple[Path, dict[str, Any] | None]:
    """Adecua el PDF a los límites de un modelo que no es Claude de 1M.

    Con Claude de 1M no se toca: los PDFs grandes van por Files API y los que
    no caben en contexto se trocean en etapa0/etapa1 (sin perder páginas). Con
    otro modelo, más de MAX_PAGINAS_OTROS páginas → PdfExcedeLimitesError (no se
    recorta: el modelo no vería parte del informe); más de MAX_BYTES_OTROS →
    se rasteriza completo y, si aun así excede, PdfExcedeLimitesError.

    Devuelve (ruta a usar, info de adecuación). Si el PDF ya cumple, la ruta
    es la original y la info es None. El archivo adecuado queda junto al
    original con sufijo "_adecuado" — el original no se toca. La info existe
    para que el caller la persista y la muestre: una adecuación nunca puede
    ser silenciosa para el revisor.
    """
    modelo = modelo or settings.modelo_extraccion
    if _usa_limites_claude(modelo):
        return ruta_pdf, None

    paginas = len(PdfReader(ruta_pdf).pages)
    tamano = ruta_pdf.stat().st_size
    if paginas > MAX_PAGINAS_OTROS:
        raise PdfExcedeLimitesError(
            f"El informe tiene {paginas} páginas y el modelo {modelo} acepta hasta "
            f"{MAX_PAGINAS_OTROS} por lectura. No se recorta (el modelo no vería parte del "
            "informe): usa un modelo Claude de 1M de contexto (por ejemplo claude-opus-5-5), "
            "que lee hasta 600 páginas y trocea los informes más largos."
        )
    if tamano <= MAX_BYTES_OTROS:
        return ruta_pdf, None

    import fitz  # pymupdf — import local: solo se paga si hace falta

    from comparador.citas import FITZ_LOCK

    destino = ruta_pdf.with_name(ruta_pdf.stem + "_adecuado.pdf")
    # MuPDF no es thread-safe: mismo lock que la verificación de citas y el visor.
    with FITZ_LOCK, fitz.open(ruta_pdf) as src, fitz.open() as out:
        n = len(src)
        for i in range(n):
            pagina = src[i]
            pix = pagina.get_pixmap(dpi=110)
            img = pix.tobytes("jpeg", jpg_quality=70)
            nueva = out.new_page(width=pagina.rect.width, height=pagina.rect.height)
            nueva.insert_image(nueva.rect, stream=img)
        out.save(destino, deflate=True, garbage=3)
    enviados = destino.stat().st_size
    if enviados > MAX_BYTES_OTROS:
        destino.unlink()
        raise PdfExcedeLimitesError(
            f"El informe pesa {tamano / 1e6:.1f} MB y rasterizado sigue en "
            f"{enviados / 1e6:.1f} MB: "
            f"el modelo {modelo} acepta hasta {MAX_BYTES_OTROS / 1e6:.0f} MB por lectura. Usa un "
            "modelo Claude de 1M de contexto (por ejemplo claude-opus-5-5)."
        )
    info = {
        "paginas_originales": paginas,
        "paginas_enviadas": n,
        "truncado": False,
        "rasterizado": True,
        "bytes_originales": tamano,
        "bytes_enviados": enviados,
    }
    return destino, info
