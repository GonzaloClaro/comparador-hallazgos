"""Visor de página: qué PDF se muestra, qué páginas y qué se resalta (sin API)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
import pytest

from comparador.schemas import (
    CitaChecklist,
    EstadoCita,
    Evidencia,
    FuenteEvidencia,
    Hallazgo,
    VerificacionCita,
)
from comparador.visor_pdf import (
    COLOR_ACCION,
    COLOR_DESCRIPCION,
    EstadoPdf,
    PaginaVisor,
    Resaltado,
    paginas_citas,
    paginas_hallazgo,
    paginas_mencionadas,
    pdf_del_run,
    render_pagina,
)

DESC = "Los ajustes de la función 51 difieren del estudio de coordinación vigente"
ACCION = "Ajustar la función 51 según el estudio vigente"


def _pdf(ruta: Path, paginas: int = 3) -> Path:
    doc = fitz.open()
    for n in range(1, paginas + 1):
        pagina = doc.new_page()
        pagina.insert_text((40, 200), f"Informe de auditoría, página {n}", fontsize=9)
        if n == 2:
            pagina.insert_text((40, 220), DESC, fontsize=9)
            pagina.insert_text((40, 234), ACCION, fontsize=9)
    doc.save(ruta)
    return ruta


def _hash(run: Path, sufijo: str, ruta: Path) -> None:
    (run / f"input_{sufijo}.hash").write_text(hashlib.sha256(ruta.read_bytes()).hexdigest())


class TestPdfDelRun:
    def test_ok_con_la_huella_del_pdf_procesado(self, tmp_path: Path):
        _hash(tmp_path, "pdf", _pdf(tmp_path / "input.pdf"))
        pdf = pdf_del_run(tmp_path)
        assert (pdf.estado, pdf.ruta, pdf.total, pdf.desde_docx) == (
            EstadoPdf.OK, tmp_path / "input.pdf", 3, False)

    def test_ok_con_la_huella_del_pdf_con_texto(self, tmp_path: Path):
        # Con modelo no-Claude el modelo leyó el adecuado; se verificó contra input.pdf.
        _hash(tmp_path, "pdf_texto", _pdf(tmp_path / "input.pdf"))
        (tmp_path / "input_pdf.hash").write_text("a" * 64)
        assert pdf_del_run(tmp_path).estado == EstadoPdf.OK

    def test_run_antiguo_con_adecuado(self, tmp_path: Path):
        # Antes de 0.7.0 solo se hasheaba el adecuado (misma paginación).
        _pdf(tmp_path / "input.pdf")
        _hash(tmp_path, "pdf", _pdf(tmp_path / "input_adecuado.pdf", paginas=2))
        assert pdf_del_run(tmp_path).estado == EstadoPdf.OK

    def test_falta(self, tmp_path: Path):
        assert pdf_del_run(tmp_path).estado == EstadoPdf.FALTA

    def test_hash_distinto(self, tmp_path: Path):
        _pdf(tmp_path / "input.pdf")
        (tmp_path / "input_pdf.hash").write_text("0" * 64)
        assert pdf_del_run(tmp_path).estado == EstadoPdf.HASH_DISTINTO

    def test_docx_convertido(self, tmp_path: Path):
        (tmp_path / "input.docx").write_bytes(b"docx")
        _hash(tmp_path, "pdf", _pdf(tmp_path / "input.pdf"))
        pdf = pdf_del_run(tmp_path)
        assert (pdf.estado, pdf.desde_docx) == (EstadoPdf.OK, True)

    def test_huella_del_docx_no_valida_el_pdf(self, tmp_path: Path):
        # input_informe_original.hash es la del DOCX subido, no la del PDF convertido.
        (tmp_path / "input.docx").write_bytes(b"docx")
        _hash(tmp_path, "informe_original", _pdf(tmp_path / "input.pdf"))
        assert pdf_del_run(tmp_path).estado == EstadoPdf.HASH_DISTINTO


def _hallazgo(v_desc: VerificacionCita | None, v_accion: VerificacionCita | None,
              pagina: int = 2) -> Hallazgo:
    return Hallazgo(
        pano="C1", rele="SEL 751", clasificacion="Ajustes", descripcion=DESC,
        accion_correctiva=ACCION,
        evidencia=Evidencia(fuente=FuenteEvidencia.PDF, pagina_pdf=pagina, texto_crudo="x",
                            verificacion_descripcion=v_desc, verificacion_accion=v_accion),
    )


def _v(estado: EstadoCita, pagina: int | None = 2) -> VerificacionCita:
    return VerificacionCita(estado=estado, pagina=pagina)


class TestPaginas:
    def test_verificadas_se_resaltan_en_su_pagina(self):
        paginas = paginas_hallazgo(_hallazgo(_v(EstadoCita.VERIFICADA), _v(EstadoCita.VERIFICADA)))
        assert paginas == [PaginaVisor(2, (
            Resaltado(DESC, "completa", COLOR_DESCRIPCION),
            Resaltado(ACCION, "completa", COLOR_ACCION),
        ))]

    def test_fila_partida_muestra_dos_paginas(self):
        paginas = paginas_hallazgo(_hallazgo(_v(EstadoCita.CONTINUA_PAGINA_SIGUIENTE), None))
        assert paginas == [
            PaginaVisor(2, (Resaltado(DESC, "inicio", COLOR_DESCRIPCION),)),
            PaginaVisor(3, (Resaltado(DESC, "final", COLOR_DESCRIPCION),)),
        ]

    def test_no_encontrada_muestra_la_pagina_sin_resaltar(self):
        paginas = paginas_hallazgo(_hallazgo(
            VerificacionCita(estado=EstadoCita.NO_ENCONTRADA, pagina_citada=2), None))
        assert paginas == [PaginaVisor(2)]

    def test_reporte_anterior_sin_verificacion(self):
        assert paginas_hallazgo(_hallazgo(None, None)) == [PaginaVisor(2)]

    def test_citas_del_checklist(self):
        citas = [
            CitaChecklist(pagina=2, texto=DESC, verificacion=_v(EstadoCita.VERIFICADA)),
            CitaChecklist(pagina=5, texto="otra", verificacion=VerificacionCita(
                estado=EstadoCita.NO_ENCONTRADA, pagina_citada=5)),
        ]
        assert paginas_citas(citas) == [
            PaginaVisor(2, (Resaltado(DESC, "completa", COLOR_DESCRIPCION),)),
            PaginaVisor(5),
        ]

    @pytest.mark.parametrize(("texto", "paginas"), [
        ("2, 5-6 y 9", [2, 5, 6, 9]),
        ("45–47", [45, 46, 47]),
        ("1 y 600", [1]),          # la 600 no existe en el PDF
        (None, []),
        ("portada", []),
        # Revisión 2026-10-18: números de tabla, figura o sección no son páginas.
        ("Tabla 4-1 (págs. 9, 22)", [9, 22]),
        ("sección 5.1.6.1, p. 30", [30]),
        ("Figura 23-20, 12", [12]),
        ("30-28", [30, 28]),       # rango invertido: dos páginas sueltas
    ])
    def test_paginas_mencionadas(self, texto: str | None, paginas: list[int]):
        assert paginas_mencionadas(texto, total=100) == (paginas, False)

    def test_rango_enorme_se_acota_y_lo_dice(self):
        paginas, recortadas = paginas_mencionadas("1-228", total=456)
        assert len(paginas) == 30 and recortadas

    def test_pdf_reemplazado_en_un_run_nuevo_con_adecuado_no_se_acepta(self, tmp_path: Path):
        # Run 0.7.0 con adecuación: input.pdf tiene huella propia; que el
        # adecuado calce no alcanza.
        _hash(tmp_path, "pdf_texto", _pdf(tmp_path / "original.pdf"))
        _hash(tmp_path, "pdf", _pdf(tmp_path / "input_adecuado.pdf", paginas=2))
        _pdf(tmp_path / "input.pdf", paginas=5)   # otro archivo
        assert pdf_del_run(tmp_path).estado == EstadoPdf.HASH_DISTINTO


class TestRender:
    def test_png_con_resaltado_y_sin_tocar_el_pdf(self, tmp_path: Path):
        ruta = _pdf(tmp_path / "input.pdf")
        antes = ruta.read_bytes()

        resaltado = render_pagina(ruta, 2, (
            Resaltado(DESC, "completa", COLOR_DESCRIPCION),
            Resaltado("texto que no está", "completa", COLOR_ACCION),
        ), dpi=40)
        plano = render_pagina(ruta, 2, dpi=40)

        assert resaltado.png.startswith(b"\x89PNG") and plano.png.startswith(b"\x89PNG")
        assert (resaltado.ubicados, resaltado.repetidos) == (1, False)
        assert resaltado.png != plano.png
        assert ruta.read_bytes() == antes

    def test_texto_repetido_se_resalta_en_todas_sus_apariciones(self, tmp_path: Path):
        # Eta p8: el mismo hallazgo en la tabla del paño DT1 y en la del D1.
        doc = fitz.open()
        pagina = doc.new_page()
        for i, linea in enumerate(["Tabla Resumen 2: paño DT1", DESC, "Tabla Resumen 3: paño D1",
                                   DESC]):
            pagina.insert_text((40, 200 + 30 * i), linea, fontsize=9)
        ruta = tmp_path / "repetido.pdf"
        doc.save(ruta)

        render = render_pagina(ruta, 1, (Resaltado(DESC, "completa", COLOR_DESCRIPCION),), dpi=40)

        assert (render.ubicados, render.repetidos) == (1, True)
        from comparador.citas import PaginasPdf, ubicar

        with PaginasPdf(ruta) as pp:
            assert len(ubicar(pp.texto(1), DESC)) == 2   # una caja por aparición
