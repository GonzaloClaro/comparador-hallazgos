"""Páginas y citas de la Etapa 3: verificación por campo contra el PDF.

Es la evidencia que la revisora usa para ubicar el hallazgo: la descripción y
la acción se buscan literales en la capa de texto (comparador.citas), con un
estado a la vista y sin corregir ni descartar nada en silencio. Los casos del
algoritmo de búsqueda están en test_citas.py; acá, cómo los aplica E3.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from comparador.citas import PaginasPdf
from comparador.etapa3_extraer_hallazgos import _verificar_citas
from comparador.schemas import (
    EstadoCita,
    Evidencia,
    FuenteEvidencia,
    Hallazgo,
    PanoDescubierto,
    ReleDescubierto,
)

DESC_A = "El relé presenta ajustes de sobrecorriente desactualizados respecto del estudio"
ACCION_A = "Actualizar los ajustes de sobrecorriente según el estudio vigente"
DESC_B = "La base Infotécnica no registra el ECAP vigente de la protección auditada"
RELLENO = "Informe técnico de auditoría de protecciones, tabla resumen de hallazgos"


@pytest.fixture
def pdf(tmp_path: Path) -> Path:
    """Págs. 5-7 del rango del paño: A en la 5, B en la 6, la 7 escaneada (sin texto)."""
    doc = fitz.open()
    for lineas in [[RELLENO], [RELLENO], [RELLENO], [RELLENO],
                   [RELLENO, DESC_A, ACCION_A], [RELLENO, DESC_B], []]:
        pagina = doc.new_page()
        for i, linea in enumerate(lineas):
            pagina.insert_text((40, 200 + 14 * i), linea, fontsize=9)
    ruta = tmp_path / "informe.pdf"
    doc.save(ruta)
    return ruta


SECCION = PanoDescubierto(
    nombre="C1", pagina_inicio=5, pagina_fin=7,
    reles=[ReleDescubierto(nombre="SEL 351", evidencia_origen="x")],
)


def _hallazgo(descripcion: str, pagina: int | None, accion: str | None = ACCION_A,
              pano: str = "C1") -> Hallazgo:
    return Hallazgo(
        pano=pano, rele="SEL 351", clasificacion="Ajustes", descripcion=descripcion,
        accion_correctiva=accion,
        evidencia=Evidencia(fuente=FuenteEvidencia.PDF, pagina_pdf=pagina,
                            texto_crudo=f"{descripcion} | {accion}"),
    )


def _verificar(pdf: Path, *hallazgos: Hallazgo) -> list[Hallazgo]:
    with PaginasPdf(pdf) as pp:
        return _verificar_citas(pp, list(hallazgos), SECCION)


def test_descripcion_y_accion_verificadas_en_su_pagina(pdf: Path):
    (h,) = _verificar(pdf, _hallazgo(DESC_A, 5))
    ev = h.evidencia
    assert ev.pagina_pdf == 5
    assert ev.verificacion_descripcion is not None and ev.verificacion_accion is not None
    assert ev.verificacion_descripcion.estado == EstadoCita.VERIFICADA
    assert ev.verificacion_accion.estado == EstadoCita.VERIFICADA


def test_descripcion_en_otra_pagina_corrige_y_guarda_la_citada(pdf: Path):
    (h,) = _verificar(pdf, _hallazgo(DESC_B, 5, accion=None))
    v = h.evidencia.verificacion_descripcion
    assert v is not None
    assert (h.evidencia.pagina_pdf, v.estado, v.pagina, v.pagina_citada) == (
        6, EstadoCita.EN_OTRA_PAGINA, 6, 5)
    # Sin acción en el formato: no hay nada que verificar.
    assert h.evidencia.verificacion_accion is None


def test_no_encontrada_conserva_la_pagina_del_modelo(pdf: Path):
    (h,) = _verificar(pdf, _hallazgo("Ajuste de la función 50: No Cumplir", 6, accion=""))
    v = h.evidencia.verificacion_descripcion
    assert v is not None
    assert (h.evidencia.pagina_pdf, v.estado, v.pagina_citada) == (
        6, EstadoCita.NO_ENCONTRADA, 6)
    assert h.evidencia.verificacion_accion is None   # acción vacía: nada que verificar


def test_pagina_sin_texto_no_se_corrige(pdf: Path):
    (h,) = _verificar(pdf, _hallazgo(DESC_A, 7))
    v = h.evidencia.verificacion_descripcion
    assert v is not None
    assert (h.evidencia.pagina_pdf, v.estado) == (7, EstadoCita.SIN_TEXTO)


def test_sin_pagina_busca_en_el_rango_del_pano(pdf: Path):
    (h,) = _verificar(pdf, _hallazgo(DESC_B, None, accion=None))
    v = h.evidencia.verificacion_descripcion
    assert v is not None
    assert (h.evidencia.pagina_pdf, v.estado, v.pagina_citada) == (
        6, EstadoCita.EN_OTRA_PAGINA, None)


def test_accion_muestra_la_pagina_que_dio_el_modelo(pdf: Path, tmp_path: Path):
    # La descripción se corrige de la p. 5 a la 6; la acción está en la 6:
    # su "citada" es la del modelo (5), no la corregida.
    (h,) = _verificar(pdf, _hallazgo(DESC_B, 5, accion="La base Infotécnica no registra el ECAP"))
    v = h.evidencia.verificacion_accion
    assert v is not None and (v.estado, v.pagina, v.pagina_citada) == (
        EstadoCita.VERIFICADA, 6, 5)


@pytest.mark.parametrize(("pagina_modelo", "esperada"), [
    (1, 5),     # posición 1 del recorte 5-7
    (3, 7),     # posición 3
    (6, 6),     # absoluta dentro del paño (el número impreso): no se desplaza
    (12, None),  # ni posición ni página del paño: no se inventa una página
    (0, None),
])
def test_pagina_del_modelo_en_el_paño(pagina_modelo: int, esperada: int | None):
    from comparador.catalogo import cargar_hints_empresa
    from comparador.etapa3_extraer_hallazgos import (
        _ListaHallazgosResponse,
        _procesar_respuesta,
        _universo_etapa1,
    )
    from comparador.schemas import EmpresaAuditora

    respuesta = _ListaHallazgosResponse.model_validate({"hallazgos": [{
        "pano": "C1", "rele": "SEL 351", "clasificacion": "Ajustes", "descripcion": DESC_A,
        "accion_correctiva": ACCION_A, "calificacion": None,
        "evidencia": {"pagina_pdf": pagina_modelo, "texto_crudo": DESC_A},
    }]})
    hints = cargar_hints_empresa(EmpresaAuditora.ENSAUT)
    procesado = _procesar_respuesta(respuesta, SECCION, hints, _universo_etapa1([SECCION]))
    assert procesado.hallazgos[0].evidencia.pagina_pdf == esperada


def test_desdoblados_comparten_la_verificacion(pdf: Path):
    # Un hallazgo desdoblado por paño repite descripción, acción y página.
    a, b = _verificar(pdf, _hallazgo(DESC_B, 5, pano="BT1"), _hallazgo(DESC_B, 5, pano="CT1"))
    assert (a.pano, b.pano) == ("BT1", "CT1")
    assert a.evidencia == b.evidencia
    assert a.evidencia.pagina_pdf == 6


def test_no_toca_nada_mas(pdf: Path):
    original = _hallazgo(DESC_A, 5)
    (h,) = _verificar(pdf, original)
    sin_verificacion = {"verificacion_descripcion", "verificacion_accion"}
    assert h.model_dump(exclude={"evidencia"}) == original.model_dump(exclude={"evidencia"})
    assert h.evidencia.model_dump(exclude=sin_verificacion) == original.evidencia.model_dump(
        exclude=sin_verificacion)
