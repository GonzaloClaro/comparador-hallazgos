"""Tests de conversión DOCX→PDF y adecuación por proveedor."""

import io
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter

from comparador import convertir
from comparador.convertir import (
    PdfExcedeLimitesError,
    _convertir_docx_python,
    adecuar_pdf_para_llm,
)

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="png" ContentType="image/png"/>
<Default Extension="emf" ContentType="image/x-emf"/>
<Override PartName="/word/document.xml"
 ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1"
 Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
 Target="word/document.xml"/>
</Relationships>"""

_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rImg1"
 Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
 Target="media/image1.png"/>
<Relationship Id="rImg2"
 Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
 Target="media/image2.emf"/>
</Relationships>"""


def _drawing(rid: str) -> str:
    return (
        '<w:p><w:r><w:drawing><wp:inline><wp:extent cx="100" cy="100"/>'
        '<wp:docPr id="1" name="x"/><a:graphic><a:graphicData><pic:pic><pic:blipFill>'
        f'<a:blip r:embed="{rid}"/></pic:blipFill></pic:pic></a:graphicData></a:graphic>'
        "</wp:inline></w:drawing></w:r></w:p>"
    )


def _docx_con_emf(ruta: Path) -> Path:
    ns = (
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"'
    )
    doc = (
        f'<?xml version="1.0" encoding="UTF-8"?><w:document {ns}><w:body>'
        "<w:p><w:r><w:t>Tabla resumen de hallazgos</w:t></w:r></w:p>"
        f'{_drawing("rImg1")}{_drawing("rImg2")}</w:body></w:document>'
    )
    png = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(png, format="PNG")
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
        z.writestr("word/document.xml", doc)
        z.writestr("word/media/image1.png", png.getvalue())
        z.writestr("word/media/image2.emf", b"\x01\x00\x00\x00 no es un EMF valido")
    return ruta


class TestDocxImagenesNoConvertibles:
    def test_emf_se_reemplaza_por_aviso_y_se_cuenta(self, tmp_path: Path):
        docx = _docx_con_emf(tmp_path / "informe.docx")
        pdf, info = _convertir_docx_python(docx, tmp_path / "informe.pdf")
        texto = "".join(p.extract_text() or "" for p in PdfReader(pdf).pages)
        assert "Tabla resumen de hallazgos" in texto
        assert "IMAGEN NO CONVERTIBLE" in texto
        assert info == {"imagenes_omitidas": 1, "tipos_omitidos": ["image/x-emf"]}


def _pdf(tmp_path: Path, paginas: int) -> Path:
    w = PdfWriter()
    for _ in range(paginas):
        w.add_blank_page(width=200, height=200)
    ruta = tmp_path / "x.pdf"
    with open(ruta, "wb") as f:
        w.write(f)
    return ruta


class TestAdecuarPorProveedor:
    def test_claude_1m_no_recorta_informes_largos(self, tmp_path: Path):
        ruta = _pdf(tmp_path, 456)
        assert adecuar_pdf_para_llm(ruta, "claude-sonnet-5-5") == (ruta, None)

    def test_otros_proveedores_fallan_sobre_100_paginas(self, tmp_path: Path):
        # Decisión del usuario 2026-10-18: no se recorta (el modelo no vería parte del informe).
        ruta = _pdf(tmp_path, 120)
        with pytest.raises(PdfExcedeLimitesError, match="120 páginas.*gpt-5"):
            adecuar_pdf_para_llm(ruta, "gpt-5")
        assert not list(tmp_path.glob("*_adecuado.pdf"))

    def test_haiku_4_tambien_falla(self, tmp_path: Path):
        with pytest.raises(PdfExcedeLimitesError):
            adecuar_pdf_para_llm(_pdf(tmp_path, 101), "claude-haiku-4-5")

    def test_hasta_100_paginas_y_liviano_no_se_toca(self, tmp_path: Path):
        ruta = _pdf(tmp_path, 100)
        assert adecuar_pdf_para_llm(ruta, "gpt-5") == (ruta, None)

    def test_solo_tamano_rasteriza_sin_recortar(self, tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch):
        # Un PDF pesado por una imagen de ruido: rasterizado a 110 dpi pesa mucho menos.
        import fitz
        import numpy as np

        doc = fitz.open()
        ruido = np.random.default_rng(0).integers(0, 255, (800, 800, 3), dtype=np.uint8)
        imagen = io.BytesIO()
        Image.fromarray(ruido).save(imagen, format="PNG")
        for _ in range(3):
            doc.new_page(width=200, height=200).insert_image(
                fitz.Rect(0, 0, 200, 200), stream=imagen.getvalue())
        ruta = tmp_path / "x.pdf"
        doc.save(ruta)
        monkeypatch.setattr(convertir, "MAX_BYTES_OTROS", ruta.stat().st_size - 1)

        destino, info = adecuar_pdf_para_llm(ruta, "gpt-5")

        assert destino == tmp_path / "x_adecuado.pdf" and info is not None
        assert (info["paginas_originales"], info["paginas_enviadas"], info["truncado"]) == (
            3, 3, False)
        assert len(PdfReader(destino).pages) == 3

    def test_rasterizado_que_sigue_excediendo_falla_y_no_deja_archivo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(convertir, "MAX_BYTES_OTROS", 1)
        with pytest.raises(PdfExcedeLimitesError, match="rasterizado sigue"):
            adecuar_pdf_para_llm(_pdf(tmp_path, 2), "gpt-5")
        assert not list(tmp_path.glob("*_adecuado.pdf"))
