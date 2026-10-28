"""M32 (decisión del usuario 2026-10-27): el juez de emparejamiento justifica antes
de elegir. Con JUEZ_JUSTIFICA_PRIMERO, el schema de la respuesta pide primero la
justificación y después el índice y la confianza (structured outputs genera en ese
orden), y el prompt lo pide en ese orden; nada más cambia. El schema conserva el
nombre `_JuezResponse`, que la caché de los jueces usa en su clave. Apagado = el
prompt y el schema de siempre (los de B2).

Solo se prueba esta variante (decisión del usuario): la regla del veredicto opuesto
y mostrar la clasificación no.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from comparador import etapa4_matching
from comparador.config import settings
from comparador.etapa4_matching import (
    _JuezResponse,
    _JuezResponseJustificaPrimero,
    _respuesta_juez,
)
from comparador.llm.client import schema_sha256
from comparador.llm.prompts import SYSTEM_JUEZ_MATCHING, system_juez_matching
from comparador.schemas import FuenteEvidencia
from tests.test_etapa4_matching import _hallazgo, embeddings_fake  # noqa: F401

RUBRICA = "Usa esta rúbrica"


class TestSchema:
    def test_la_justificacion_va_primero_y_el_nombre_no_cambia(self) -> None:
        assert list(_JuezResponseJustificaPrimero.model_json_schema()["properties"]) == [
            "justificacion", "indice_candidato", "confianza"]
        assert list(_JuezResponse.model_json_schema()["properties"]) == [
            "indice_candidato", "confianza", "justificacion"]
        assert _JuezResponseJustificaPrimero.__name__ == _JuezResponse.__name__
        assert (_JuezResponseJustificaPrimero.model_json_schema()["title"]
                == _JuezResponse.model_json_schema()["title"])
        # El hash del schema ve el orden: la caché no sirve una por la otra.
        assert schema_sha256(_JuezResponseJustificaPrimero) != schema_sha256(_JuezResponse)

    def test_la_misma_validacion_de_la_confianza(self) -> None:
        with pytest.raises(ValidationError, match="0-99"):
            _JuezResponseJustificaPrimero(justificacion="x", indice_candidato=0, confianza=100)
        assert _JuezResponseJustificaPrimero(
            justificacion="x", indice_candidato=None, confianza=40).confianza == 40

    def test_el_interruptor_elige_el_schema(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert settings.model_fields["juez_justifica_primero"].default is False
        monkeypatch.setattr(settings, "juez_justifica_primero", False)
        assert _respuesta_juez() is _JuezResponse
        monkeypatch.setattr(settings, "juez_justifica_primero", True)
        assert _respuesta_juez() is _JuezResponseJustificaPrimero


class TestPrompt:
    def test_apagado_es_el_de_siempre(self) -> None:
        assert system_juez_matching(False) is SYSTEM_JUEZ_MATCHING

    def test_solo_cambia_el_bloque_de_la_respuesta(self) -> None:
        variante = system_juez_matching(True)
        inicio = SYSTEM_JUEZ_MATCHING.index("Responde con:")
        fin = SYSTEM_JUEZ_MATCHING.index(RUBRICA)
        assert variante.startswith(SYSTEM_JUEZ_MATCHING[:inicio])
        assert variante.endswith(SYSTEM_JUEZ_MATCHING[fin:])
        bloque = variante[inicio:variante.index(RUBRICA)]
        # Primero la justificación, después el índice y la confianza.
        assert bloque.index("justificación") < bloque.index("índice") < bloque.index("confianza")
        assert "en este orden" in bloque
        # Lo demás del pedido no cambia: el 0-99 sin 100 y el ejemplo con «[2]»,
        # que usa _limpiar_justificacion_juez.
        assert "Nunca uses 100" in bloque and "el candidato [2]" in bloque

    def test_falla_si_el_bloque_no_esta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from comparador.llm import prompts

        monkeypatch.setattr(prompts, "SYSTEM_JUEZ_MATCHING", "Otro prompt sin el bloque.")
        with pytest.raises(ValueError, match="Responde con"):
            prompts.system_juez_matching(True)


class TestEnElMatching:
    @pytest.fixture
    def pedidos(self, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
                ) -> list[dict[str, Any]]:
        request.getfixturevalue("embeddings_fake")
        monkeypatch.setattr(settings, "juez_redaccion", False)
        monkeypatch.setattr(settings, "descripcion_identica", False)
        vistos: list[dict[str, Any]] = []

        def juez(**kw: Any) -> tuple[Any, dict[str, Any]]:
            vistos.append(kw)
            respuesta = kw["response_model"](justificacion="El mismo hallazgo.",
                                             indice_candidato=0, confianza=90)
            return respuesta, {"tokens_total": 1}

        monkeypatch.setattr(etapa4_matching, "llamar_llm_estructurado", juez)
        return vistos

    def _correr(self) -> list[Any]:
        # Dos filas de la misma clasificación en la tupla: decide el juez.
        pdf = [_hallazgo(descripcion="Alfa del PDF.")]
        excel = [_hallazgo(descripcion="Alfa del Excel.", fuente=FuenteEvidencia.EXCEL),
                 _hallazgo(descripcion="Beta del Excel.", fuente=FuenteEvidencia.EXCEL)]
        resultados, _ = etapa4_matching.ejecutar_matching(pdf, excel)
        return resultados

    @pytest.mark.parametrize("encendido", [False, True])
    def test_el_juez_recibe_el_prompt_y_el_schema_del_interruptor(
            self, pedidos: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch,
            encendido: bool) -> None:
        monkeypatch.setattr(settings, "juez_justifica_primero", encendido)
        resultados = self._correr()
        (kw,) = pedidos
        assert kw["system_prompt"] == system_juez_matching(encendido)
        assert kw["response_model"] is (
            _JuezResponseJustificaPrimero if encendido else _JuezResponse)
        # El resultado se lee igual con cualquiera de los dos.
        par = next(r for r in resultados if r.hallazgo_pdf and r.hallazgo_excel)
        assert (par.confianza, par.justificacion) == (0.9, "El mismo hallazgo.")
