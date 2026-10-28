"""Tests del troceo de PDFs que no caben en contexto. count_tokens mockeado."""

from pathlib import Path
from typing import Any

import anthropic
import pytest
from pypdf import PdfReader, PdfWriter

from comparador import troceo
from comparador.troceo import Tramo, a_pagina_absoluta, a_paginas_absolutas, planificar_tramos


def _pdf(tmp_path: Path, paginas: int) -> Path:
    w = PdfWriter()
    for _ in range(paginas):
        w.add_blank_page(width=200, height=200)
    ruta = tmp_path / "informe.pdf"
    with open(ruta, "wb") as f:
        w.write(f)
    return ruta


def _tokens_por_pagina(monkeypatch: pytest.MonkeyPatch, por_pagina: int) -> list[int]:
    """count_tokens simulado: tokens proporcionales a las páginas del PDF."""
    import base64
    import io

    conteos: list[int] = []

    def _contar(*, pdf_base64: str, **kw: Any) -> int:
        n = len(PdfReader(io.BytesIO(base64.b64decode(pdf_base64))).pages)
        conteos.append(n * por_pagina)
        return n * por_pagina

    monkeypatch.setattr(troceo, "contar_tokens_pdf", _contar)
    return conteos


def _planificar(ruta: Path) -> list[Tramo]:
    return planificar_tramos(ruta, modelo="claude-sonnet-5-5", system_prompt="s", user_prompt="u")


class TestPlanificarTramos:
    def test_si_cabe_es_un_solo_tramo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        _tokens_por_pagina(monkeypatch, 2_000)
        tramos = _planificar(_pdf(tmp_path, 300))  # 600k < 900k
        assert len(tramos) == 1 and tramos[0].es_completo

    def test_si_no_cabe_se_parte_en_tramos_que_caben(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        _tokens_por_pagina(monkeypatch, 2_300)
        tramos = _planificar(_pdf(tmp_path, 456))  # ~1.05M, como Beta
        assert len(tramos) == 2
        assert [(t.pagina_inicio, t.pagina_fin) for t in tramos] == [(1, 228), (229, 456)]
        assert all((t.tokens or 0) <= 900_000 for t in tramos)

    def test_mas_de_600_paginas_se_parte_aunque_quepa_en_tokens(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        _tokens_por_pagina(monkeypatch, 500)
        tramos = _planificar(_pdf(tmp_path, 700))  # 350k tokens pero 700 págs
        assert len(tramos) == 2
        assert all(t.pagina_fin - t.pagina_inicio + 1 <= 600 for t in tramos)

    def test_modelo_no_claude_no_trocea(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        conteos = _tokens_por_pagina(monkeypatch, 2_300)
        tramos = planificar_tramos(
            _pdf(tmp_path, 456), modelo="gpt-5", system_prompt="s", user_prompt="u",
        )
        assert len(tramos) == 1 and tramos[0].tokens is None
        assert conteos == []  # ni siquiera se llama a count_tokens

    def test_pdf_que_no_cabe_inline_se_cuenta_por_mitades(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # count_tokens no acepta Files API: un PDF > tope inline se bisecta
        # hasta que cada parte cabe, y se suman los conteos.
        import base64
        import io

        conteos = _tokens_por_pagina(monkeypatch, 1_000)
        monkeypatch.setattr(
            troceo, "pdf_cabe_inline",
            lambda b64: len(PdfReader(io.BytesIO(base64.b64decode(b64))).pages) <= 100,
        )
        tramos = _planificar(_pdf(tmp_path, 300))  # 300k tokens: cabe en contexto
        assert len(tramos) == 1 and tramos[0].tokens == 300_000
        assert len(conteos) == 4 and all(c <= 100_000 for c in conteos)


class TestFallbackDeModelo:
    """count_tokens va directo al SDK: el troceo replica el fallback del router."""

    def _sin_acceso(self, monkeypatch: pytest.MonkeyPatch, modelo_sin_acceso: str) -> list[str]:
        import httpx

        modelos: list[str] = []

        def _contar(*, modelo: str, **kw: Any) -> int:
            modelos.append(modelo)
            if modelo == modelo_sin_acceso:
                resp = httpx.Response(404, request=httpx.Request("POST", "https://x"))
                raise anthropic.NotFoundError("model not found", response=resp, body=None)
            return 1_000

        monkeypatch.setattr(troceo, "contar_tokens_pdf", _contar)
        return modelos

    def test_cuenta_con_el_respaldo_claude(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        modelos = self._sin_acceso(monkeypatch, "claude-sonnet-5-5")
        monkeypatch.setattr(troceo.settings, "modelo_extraccion_fallback", "claude-sonnet-5")
        tramos = _planificar(_pdf(tmp_path, 10))
        assert len(tramos) == 1 and tramos[0].tokens == 1_000
        assert modelos == ["claude-sonnet-5-5", "claude-sonnet-5"]

    def test_respaldo_no_claude_no_cuenta(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        self._sin_acceso(monkeypatch, "claude-sonnet-5-5")
        monkeypatch.setattr(troceo.settings, "modelo_extraccion_fallback", "gpt-5.5")
        tramos = _planificar(_pdf(tmp_path, 10))
        assert len(tramos) == 1 and tramos[0].tokens is None

    def test_sin_respaldo_falla_ruidosamente(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        self._sin_acceso(monkeypatch, "claude-sonnet-5-5")
        monkeypatch.setattr(troceo.settings, "modelo_extraccion_fallback", "")
        with pytest.raises(anthropic.NotFoundError):
            _planificar(_pdf(tmp_path, 10))


class TestMasDe600Paginas:
    def test_no_cuenta_el_documento_entero(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        conteos = _tokens_por_pagina(monkeypatch, 500)
        tramos = _planificar(_pdf(tmp_path, 700))
        assert len(tramos) == 2
        assert all(c <= 600 * 500 for c in conteos)  # ningún conteo de las 700 págs


class TestPaginasAbsolutas:
    def test_primer_tramo_no_se_desplaza(self):
        assert a_paginas_absolutas("3, 10-12", Tramo(1, 228, 456, "", None)) == "3, 10-12"

    def test_tramo_posterior_desplaza_todos_los_numeros(self):
        assert a_paginas_absolutas("1 y 6", Tramo(229, 456, 456, "", None)) == "229 y 234"

    def test_numero_fuera_del_tramo_no_se_desplaza(self):
        # 300 no es una posición dentro de un tramo de 228 páginas: el modelo
        # citó la página absoluta (o la impresa) y desplazarla la corrompería.
        assert a_paginas_absolutas("5, 300", Tramo(229, 456, 456, "", None)) == "233, 300"

    def test_none_se_mantiene(self):
        assert a_paginas_absolutas(None, Tramo(229, 456, 456, "", None)) is None

    def test_pagina_de_una_cita(self):
        tramo = Tramo(229, 456, 456, "", None)
        assert a_pagina_absoluta(2, tramo) == 230
        assert a_pagina_absoluta(300, tramo) == 300   # ya era absoluta: no se toca
        assert a_pagina_absoluta(5, Tramo(1, 228, 456, "", None)) == 5
