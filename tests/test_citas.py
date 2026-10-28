"""Verificación de citas contra la capa de texto del PDF (sin LLM).

PDF sintéticos generados con fitz: cada caso imita una forma real en que el
texto de la página y el texto que copió el modelo difieren sin que el
contenido cambie (o cambiando, como "No Cumplir" por "No Cumple").
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import fitz
import pytest

from comparador.citas import (
    PaginasPdf,
    etiqueta_verificacion,
    normalizar,
    ubicar,
    verificar_cita,
)
from comparador.schemas import EstadoCita, VerificacionCita

DESC_A = "El relé presenta ajustes de sobrecorriente desactualizados respecto del estudio vigente"
DESC_B = "La base Infotécnica no registra el ECAP vigente de la protección auditada"
# DESC_A partida en una frontera de palabra, como una fila de tabla que sigue
# en la página siguiente (Alfa p29-p30).
PARTE_1, PARTE_2 = DESC_A[:42], DESC_A[43:]
RELLENO = "Informe técnico de auditoría de protecciones, sección de hallazgos del paño"


Linea = str | tuple[float, str]


def _pdf(tmp_path: Path, paginas: list[list[Linea]], nombre: str = "x.pdf") -> Path:
    """Una página por lista; cada elemento es una línea, en el cuerpo de la página
    (desde y=200) o en una altura dada con (y, texto). Una página vacía = sin texto."""
    doc = fitz.open()
    for lineas in paginas:
        pagina = doc.new_page()
        for i, linea in enumerate(lineas):
            y, texto = linea if isinstance(linea, tuple) else (200 + 14 * i, linea)
            pagina.insert_text((40, y), texto, fontsize=9)
    ruta = tmp_path / nombre
    doc.save(ruta)
    return ruta


# Una fila de tabla cortada por el salto de página: el comienzo al pie de una
# página (A4: 842 pt de alto) y el final arriba de la siguiente.
PARTIDA = [[RELLENO, (760, PARTE_1)], [(130, PARTE_2), RELLENO]]


def _verificar(ruta: Path, texto: str, pagina: int | None, rango: tuple[int, int]
               ) -> VerificacionCita:
    with PaginasPdf(ruta) as pp:
        return verificar_cita(pp, texto, pagina, rango)


class TestNormalizar:
    def test_tildes_compuestas_y_descompuestas_son_iguales(self):
        texto = "coordinación de protección"
        assert normalizar(unicodedata.normalize("NFD", texto)) == normalizar(texto)

    def test_comillas_guiones_y_mayusculas(self):
        assert normalizar("«Verificación» — DUF") == normalizar('"verificacion" - duf')

    def test_ligadura(self):
        assert normalizar("ﬁltro") == normalizar("filtro")

    def test_solo_signos_queda_vacio(self):
        assert normalizar("— ... •") == ""


class TestVerificarCita:
    def test_en_la_pagina_citada(self, tmp_path: Path):
        ruta = _pdf(tmp_path, [[RELLENO, DESC_A], [RELLENO, DESC_B]])
        v = _verificar(ruta, DESC_A, 1, (1, 2))
        assert (v.estado, v.pagina, v.pagina_citada, v.repetida) == (
            EstadoCita.VERIFICADA, 1, None, False)
        assert v.respaldada

    def test_texto_con_saltos_de_linea_del_pdf(self, tmp_path: Path):
        # En el PDF la descripción ocupa dos líneas; el modelo la copia en una.
        ruta = _pdf(tmp_path, [[RELLENO, DESC_A[:40], DESC_A[40:]]])
        assert _verificar(ruta, DESC_A, 1, (1, 1)).estado == EstadoCita.VERIFICADA

    def test_corte_de_linea_con_guion(self, tmp_path: Path):
        ruta = _pdf(tmp_path, [[RELLENO, "ajustes de la protec-", "ción de sobrecorriente"]])
        v = _verificar(ruta, "ajustes de la protección de sobrecorriente", 1, (1, 1))
        assert v.estado == EstadoCita.VERIFICADA

    def test_texto_justificado_espaciado_letra_por_letra(self, tmp_path: Path):
        # Añañuca: el texto justificado sale "p r o t e c c i o n e s".
        ruta = _pdf(tmp_path, [[RELLENO, "v e r i f i c a r  l a s  p r o t e c c i o n e s"]])
        v = _verificar(ruta, "verificar las protecciones", 1, (1, 1))
        assert v.estado == EstadoCita.VERIFICADA

    def test_palabra_alterada_por_el_modelo_no_se_encuentra(self, tmp_path: Path):
        # Alfa (B2, Sonnet): el modelo escribió "No Cumplir"; el PDF dice "No Cumple".
        ruta = _pdf(tmp_path, [[RELLENO, "Ajuste de la función 50: No Cumple"]])
        v = _verificar(ruta, "Ajuste de la función 50: No Cumplir", 1, (1, 1))
        assert (v.estado, v.pagina, v.pagina_citada) == (EstadoCita.NO_ENCONTRADA, None, 1)
        assert not v.respaldada

    def test_frontera_de_palabra(self, tmp_path: Path):
        ruta = _pdf(tmp_path, [[RELLENO, "el informe declara falta DUFactualizado en anexo"]])
        assert _verificar(ruta, "falta DUF", 1, (1, 1)).estado == EstadoCita.NO_ENCONTRADA

    def test_fila_partida_entre_dos_paginas(self, tmp_path: Path):
        ruta = _pdf(tmp_path, PARTIDA)
        v = _verificar(ruta, DESC_A, 1, (1, 2))
        assert (v.estado, v.pagina, v.pagina_citada) == (
            EstadoCita.CONTINUA_PAGINA_SIGUIENTE, 1, None)

    def test_fila_partida_citando_la_segunda_pagina(self, tmp_path: Path):
        ruta = _pdf(tmp_path, PARTIDA)
        v = _verificar(ruta, DESC_A, 2, (1, 2))
        assert (v.estado, v.pagina, v.pagina_citada) == (
            EstadoCita.CONTINUA_PAGINA_SIGUIENTE, 1, 2)

    def test_en_otra_unica_pagina_del_rango(self, tmp_path: Path):
        ruta = _pdf(tmp_path, [[RELLENO, DESC_A], [RELLENO, DESC_B], [RELLENO]])
        v = _verificar(ruta, DESC_B, 1, (1, 3))
        assert (v.estado, v.pagina, v.pagina_citada) == (EstadoCita.EN_OTRA_PAGINA, 2, 1)
        assert v.respaldada

    def test_en_varias_otras_paginas_no_adivina(self, tmp_path: Path):
        ruta = _pdf(tmp_path, [[RELLENO], [DESC_B, RELLENO], [DESC_B, RELLENO]])
        v = _verificar(ruta, DESC_B, 1, (1, 3))
        assert (v.estado, v.pagina, v.pagina_citada, v.repetida) == (
            EstadoCita.EN_OTRA_PAGINA, None, 1, True)

    def test_fuera_del_rango_no_cuenta(self, tmp_path: Path):
        ruta = _pdf(tmp_path, [[RELLENO], [RELLENO], [DESC_B, RELLENO]])
        assert _verificar(ruta, DESC_B, 1, (1, 2)).estado == EstadoCita.NO_ENCONTRADA

    def test_repetida_en_la_misma_pagina(self, tmp_path: Path):
        ruta = _pdf(tmp_path, [[DESC_B, RELLENO, DESC_B]])
        v = _verificar(ruta, DESC_B, 1, (1, 1))
        assert (v.estado, v.repetida) == (EstadoCita.VERIFICADA, True)

    def test_repetida_en_otra_pagina_del_rango(self, tmp_path: Path):
        ruta = _pdf(tmp_path, [[DESC_B, RELLENO], [DESC_B, RELLENO]])
        v = _verificar(ruta, DESC_B, 1, (1, 2))
        assert (v.estado, v.pagina, v.repetida) == (EstadoCita.VERIFICADA, 1, True)

    def test_pagina_sin_texto_no_busca_en_otras(self, tmp_path: Path):
        # Escaneada (Eta p55): que no esté ahí no prueba que esté en otra.
        ruta = _pdf(tmp_path, [[], [DESC_A, RELLENO]])
        v = _verificar(ruta, DESC_A, 1, (1, 2))
        assert (v.estado, v.pagina) == (EstadoCita.SIN_TEXTO, 1)
        assert not v.respaldada

    def test_sin_pagina_citada_busca_en_el_rango(self, tmp_path: Path):
        ruta = _pdf(tmp_path, [[RELLENO], [DESC_A, RELLENO]])
        v = _verificar(ruta, DESC_A, None, (1, 2))
        assert (v.estado, v.pagina, v.pagina_citada) == (EstadoCita.EN_OTRA_PAGINA, 2, None)

    def test_rango_mayor_que_el_documento_se_acota(self, tmp_path: Path):
        ruta = _pdf(tmp_path, [[DESC_A, RELLENO]])
        assert _verificar(ruta, DESC_A, 1, (1, 50)).estado == EstadoCita.VERIFICADA


class TestCasosDeLaRevision:
    """Referencias que se mostraban como verificadas sin serlo (revisión 2026-10-18)."""

    def test_comienzo_y_final_de_filas_distintas_no_son_una_fila_partida(self, tmp_path: Path):
        # El comienzo está a media página y el final a media página de la siguiente.
        ruta = _pdf(tmp_path, [[RELLENO, (400, PARTE_1)], [RELLENO, (400, PARTE_2)]])
        assert _verificar(ruta, DESC_A, 1, (1, 2)).estado == EstadoCita.NO_ENCONTRADA

    def test_el_texto_completo_en_otra_pagina_gana_a_una_fila_partida(self, tmp_path: Path):
        # p1 termina con el comienzo de A; p2 empieza con su final; pero A está
        # completa en la p. 3: es otra fila, no una fila partida.
        ruta = _pdf(tmp_path, [[RELLENO, (760, PARTE_1)], [(130, PARTE_2), RELLENO],
                               [RELLENO, DESC_A]])
        v = _verificar(ruta, DESC_A, 1, (1, 3))
        assert (v.estado, v.pagina, v.pagina_citada) == (EstadoCita.EN_OTRA_PAGINA, 3, 1)

    def test_pagina_escaneada_con_encabezado_y_pie_es_sin_texto(self, tmp_path: Path):
        # Ensaut: encabezado y pie de texto, cuerpo escaneado.
        encabezado = "Informe final de auditoría técnica de protecciones, S/E Prueba"
        ruta = _pdf(tmp_path, [[(40, encabezado), (820, "Página 63 de 120 www.auditora.cl")],
                               [DESC_A, RELLENO]])
        v = _verificar(ruta, DESC_A, 1, (1, 2))
        assert (v.estado, v.pagina) == (EstadoCita.SIN_TEXTO, 1)

    def test_signos_de_comparacion_cambian_el_valor(self, tmp_path: Path):
        ruta = _pdf(tmp_path, [[RELLENO, "El tiempo de despeje es > 400 ms en la zona 2"]])
        cita = "El tiempo de despeje es < 400 ms en la zona 2"
        assert _verificar(ruta, cita, 1, (1, 1)).estado == EstadoCita.NO_ENCONTRADA
        assert _verificar(ruta, "El tiempo de despeje es >400 ms en la zona 2", 1,
                          (1, 1)).estado == EstadoCita.VERIFICADA

    def test_numero_partido_en_dos_palabras_igual_se_verifica(self, tmp_path: Path):
        # Añañuca p. 20: la capa de texto trae "66/13," y "8 kV" como palabras distintas.
        ruta = _pdf(tmp_path, [[RELLENO, "asociadas al transformador 66/13, 8 kV de criticidad"]])
        cita = "asociadas al transformador 66/13,8 kV de criticidad"
        assert _verificar(ruta, cita, 1, (1, 1)).estado == EstadoCita.VERIFICADA

    def test_en_varias_paginas_no_cuenta_como_respaldada(self, tmp_path: Path):
        ruta = _pdf(tmp_path, [[RELLENO], [DESC_B, RELLENO], [DESC_B, RELLENO]])
        assert not _verificar(ruta, DESC_B, 1, (1, 3)).respaldada


class TestPaginasPdf:
    def test_pdf_inexistente_lanza(self, tmp_path: Path):
        with pytest.raises(Exception), PaginasPdf(tmp_path / "no_existe.pdf"):  # noqa: B017
            pass

    def test_falla_de_extraccion_queda_registrada(self, tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch):
        ruta = _pdf(tmp_path, [[DESC_A, RELLENO]])
        with PaginasPdf(ruta) as pp:
            def falla(*a: object, **k: object) -> None:
                raise RuntimeError("contenido malformado")
            monkeypatch.setattr(fitz.Page, "get_text", falla)
            assert not pp.texto(1).tiene_texto
            assert pp.errores == {1: "RuntimeError: contenido malformado"}


class TestUbicar:
    def test_una_caja_por_linea(self, tmp_path: Path):
        ruta = _pdf(tmp_path, [[RELLENO, DESC_A[:40], DESC_A[40:]]])
        with PaginasPdf(ruta) as pp:
            cajas = ubicar(pp.texto(1), DESC_A)
        assert len(cajas) == 2
        assert cajas[0][1] < cajas[1][1]  # la primera línea está más arriba

    def test_inicio_y_final_de_una_cita_partida(self, tmp_path: Path):
        ruta = _pdf(tmp_path, PARTIDA)
        with PaginasPdf(ruta) as pp:
            assert ubicar(pp.texto(1), DESC_A) == []
            assert len(ubicar(pp.texto(1), DESC_A, "inicio")) == 1
            assert len(ubicar(pp.texto(2), DESC_A, "final")) == 1

    def test_no_ubicada(self, tmp_path: Path):
        ruta = _pdf(tmp_path, [[RELLENO]])
        with PaginasPdf(ruta) as pp:
            assert ubicar(pp.texto(1), DESC_B) == []


class TestEtiqueta:
    @pytest.mark.parametrize(("v", "texto"), [
        (None, "sin verificar"),
        (VerificacionCita(estado=EstadoCita.VERIFICADA, pagina=4), "verificada en la p. 4"),
        (VerificacionCita(estado=EstadoCita.CONTINUA_PAGINA_SIGUIENTE, pagina=29),
         "verificada en las pp. 29-30"),
        (VerificacionCita(estado=EstadoCita.EN_OTRA_PAGINA, pagina=7, pagina_citada=6),
         "está en la p. 7 (el modelo citó la p. 6)"),
        (VerificacionCita(estado=EstadoCita.EN_OTRA_PAGINA, pagina_citada=6, repetida=True),
         "aparece en varias páginas, no en la citada (el modelo citó la p. 6): confirmar cuál"),
        (VerificacionCita(estado=EstadoCita.NO_ENCONTRADA, pagina_citada=12),
         "no aparece en la p. 12"),
        (VerificacionCita(estado=EstadoCita.SIN_TEXTO, pagina=55),
         "la p. 55 no tiene texto: confirmar a la vista"),
    ])
    def test_etiquetas(self, v: VerificacionCita | None, texto: str):
        assert etiqueta_verificacion(v) == texto
