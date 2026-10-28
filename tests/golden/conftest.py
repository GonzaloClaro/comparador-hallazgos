"""Fixtures de los tests golden (datos reales privados, solo lectura)."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from pypdf import PdfReader

from comparador.convertir import _convertir_docx_python
from tests.golden.datos import Caso, casos_informes, inventario, sha256


@pytest.fixture(scope="session")
def pdf_visto(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Callable[[Caso], Path]]:
    """El PDF que vio el modelo en un run medido.

    Un informe PDF se usa tal cual y debe tener el mismo sha256 que el run
    (`input_pdf.hash`). Un DOCX se convierte de nuevo con el mismo camino que
    usó la medición (mammoth + xhtml2pdf, sin LibreOffice): la conversión no
    es reproducible byte a byte (fecha de creación en los metadatos), pero sí
    su texto por página, que es lo único que usa el anclaje de páginas de la
    Etapa 3. Se convierte una vez por sesión, en un directorio temporal que se
    borra al terminar la sesión (pytest conserva sus temporales de las últimas
    corridas; los informes privados no deben quedar ahí): ~1 minuto para
    Zeta y Gamma.

    Atajo opcional: si GOLDEN_PDFS_RUNS apunta a una carpeta con
    `<run_id>/input.pdf` (los runs originales con sus insumos) y ese PDF tiene
    el sha256 del run, se usa ese archivo exacto y no se convierte nada.
    """
    convertidos: dict[str, Path] = {}
    runs_con_pdf = os.environ.get("GOLDEN_PDFS_RUNS")

    def _pdf(caso: Caso) -> Path:
        esperado = (caso.run_dir / "input_pdf.hash").read_text().strip()
        insumo: Path = casos_informes()[caso.subestacion]["informe"]
        if insumo.suffix.lower() == ".pdf":
            assert sha256(insumo) == esperado, (
                f"{insumo.name} no es el PDF que vio el modelo en {caso.run_id}"
            )
            return insumo
        if runs_con_pdf:
            original = Path(runs_con_pdf) / caso.run_id / "input.pdf"
            if original.is_file() and sha256(original) == esperado:
                return original
        if caso.subestacion not in convertidos:
            destino = tmp_path_factory.mktemp("docx_convertido") / "input.pdf"
            convertidos[caso.subestacion], _ = _convertir_docx_python(insumo, destino)
        ruta = convertidos[caso.subestacion]
        paginas = inventario()[caso.subestacion]["paginas_pdf_visto_por_el_modelo"]
        assert len(PdfReader(ruta).pages) == paginas
        return ruta

    yield _pdf
    for ruta in convertidos.values():
        shutil.rmtree(ruta.parent, ignore_errors=True)
