"""E4 con vectores ya calculados y llamador de jueces inyectado (M70).

Sin API: los embeddings y el juez son falsos. `ejecutar_matching` sin los
argumentos nuevos se comporta exactamente como antes (una llamada de
embeddings con todos los textos únicos, en orden, y el juez del módulo).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from comparador import etapa4_matching
from comparador.config import settings
from comparador.etapa4_matching import _JuezResponse, ejecutar_matching
from comparador.schemas import Evidencia, FuenteEvidencia, Hallazgo

CLASIF = "Verificación DUF"   # la misma en todos: la unicidad (4a) no aplica


def _h(descripcion: str, accion: str | None, fuente: FuenteEvidencia = FuenteEvidencia.PDF,
       fila: int | None = None, es_transversal: bool = False) -> Hallazgo:
    return Hallazgo(
        pano="C1", rele="SEL 351R", clasificacion=CLASIF, descripcion=descripcion,
        accion_correctiva=accion, calificacion="Menor", es_transversal=es_transversal,
        evidencia=Evidencia(fuente=fuente, fila_excel=fila, texto_crudo=descripcion),
    )


def _excel(descripcion: str, accion: str | None, fila: int, **kw: Any) -> Hallazgo:
    return _h(descripcion, accion, FuenteEvidencia.EXCEL, fila, **kw)


PDF = [_h("DUF desactualizado", "Actualizar el DUF"),
       _h("Relé sin sincronización GPS", "Instalar GPS")]
EXCEL = [_excel("Falta actualizar el DUF", "Actualizar DUF", 10),
         _excel("Relé sin sincronización GPS", "Instalar GPS", 11),
         _excel("No se adjunta el estudio de coordinación", "Adjuntar", 12, es_transversal=True)]
TEXTOS = ["DUF desactualizado", "Actualizar el DUF", "Relé sin sincronización GPS",
          "Instalar GPS", "Falta actualizar el DUF", "Actualizar DUF"]


class EmbeddingsFalsos:
    """Un vector fijo por texto (no depende del lote) y registro de cada llamada."""

    def __init__(self) -> None:
        self.llamadas: list[list[str]] = []

    @staticmethod
    def vector(texto: str) -> np.ndarray[Any, np.dtype[np.float64]]:
        semilla = sum(ord(c) * (i + 1) for i, c in enumerate(texto))
        v = np.random.default_rng(semilla).normal(size=8)
        if "DUF" in texto:
            v[0] += 6.0
        if "GPS" in texto:
            v[1] += 6.0
        return v.astype(np.float32).astype(np.float64)

    def __call__(self, textos: list[str]) -> tuple[np.ndarray[Any, Any], dict[str, Any]]:
        self.llamadas.append(list(textos))
        return (np.array([self.vector(t) for t in textos]),
                {"etapa": "embeddings", "modelo": "m", "tokens_total": 3 * len(textos)})


class Juez:
    """Elige el candidato 0 con confianza 90; registra cada llamada."""

    def __init__(self) -> None:
        self.llamadas: list[dict[str, Any]] = []

    def __call__(self, **kw: Any) -> tuple[Any, dict[str, Any]]:
        self.llamadas.append(kw)
        if kw["response_model"] is _JuezResponse:
            return _JuezResponse(indice_candidato=0, confianza=90, justificacion="igual"), {
                "modelo": kw["modelo"], "tokens_total": 7}
        items = kw["user_prompt"].count('"id"')
        return kw["response_model"].model_validate({"veredictos": [
            {"id": i, "justificacion": "igual", "mismo_contenido": True}
            for i in range(1, items + 1)]}), {"modelo": kw["modelo"], "tokens_total": 9}


def _prohibido(*_: Any, **__: Any) -> Any:
    raise AssertionError("no debía llamarse")


@pytest.fixture
def falsos(monkeypatch: pytest.MonkeyPatch) -> tuple[EmbeddingsFalsos, Juez]:
    monkeypatch.setattr(settings, "juez_redaccion", True)
    monkeypatch.setattr(settings, "asignacion_global", False)
    monkeypatch.setattr(settings, "top_k_candidatos", 5)
    embeddings, juez = EmbeddingsFalsos(), Juez()
    monkeypatch.setattr(etapa4_matching, "calcular_embeddings", embeddings)
    monkeypatch.setattr(etapa4_matching, "llamar_llm_estructurado", juez)
    return embeddings, juez


def _dump(resultados: list[Any]) -> list[dict[str, Any]]:
    return [r.model_dump(mode="json") for r in resultados]


def test_textos_a_embeber_en_el_orden_en_que_e4_los_pide() -> None:
    """PDF y después Excel; descripción y acción; sin vacíos, None, repetidos ni
    filas transversales (que no entran al matching)."""
    pdf = [*PDF, _h("DUF desactualizado", ""), _h("Otro", None), _h("   ", "Actualizar el DUF")]
    assert etapa4_matching.textos_a_embeber(pdf, EXCEL) == [*TEXTOS[:4], "Otro", *TEXTOS[4:]]


def test_sin_los_argumentos_nuevos_el_comportamiento_es_el_previo(
    falsos: tuple[EmbeddingsFalsos, Juez]
) -> None:
    embeddings, juez = falsos
    previo, metas_previas = ejecutar_matching(PDF, EXCEL)
    llamadas_previas = (list(embeddings.llamadas), len(juez.llamadas))

    explicito, metas = ejecutar_matching(PDF, EXCEL, vectores=None, vectores_estrictos=False,
                                         llamar=None)

    assert llamadas_previas == ([TEXTOS], 3)   # un lote con todo, como antes de M70
    assert embeddings.llamadas == [TEXTOS, TEXTOS] and len(juez.llamadas) == 6
    assert _dump(explicito) == _dump(previo)
    assert metas == metas_previas


def test_capturar_los_vectores_no_cambia_el_reporte(falsos: tuple[EmbeddingsFalsos, Juez]) -> None:
    embeddings, _ = falsos
    sin_captura, metas_sin = ejecutar_matching(PDF, EXCEL)
    vectores: dict[str, Any] = {}

    con_captura, metas_con = ejecutar_matching(PDF, EXCEL, vectores=vectores)

    assert _dump(con_captura) == _dump(sin_captura) and metas_con == metas_sin
    assert embeddings.llamadas[1] == TEXTOS
    assert list(vectores) == TEXTOS
    assert all(np.array_equal(vectores[t], EmbeddingsFalsos.vector(t)) for t in TEXTOS)


def test_con_todos_los_vectores_no_llama_a_los_embeddings(
    falsos: tuple[EmbeddingsFalsos, Juez], monkeypatch: pytest.MonkeyPatch
) -> None:
    pagado, metas_pagadas = ejecutar_matching(PDF, EXCEL)
    monkeypatch.setattr(etapa4_matching, "calcular_embeddings", _prohibido)
    vectores = {t: EmbeddingsFalsos.vector(t) for t in reversed(TEXTOS)}
    vectores["texto de otro run"] = np.zeros(8)

    guardado, metas = ejecutar_matching(PDF, EXCEL, vectores=vectores, vectores_estrictos=True)

    assert _dump(guardado) == _dump(pagado)
    assert metas == [m for m in metas_pagadas if m.get("etapa") != "embeddings"]
    assert len(vectores) == len(TEXTOS) + 1   # nada nuevo


def test_solo_calcula_los_que_faltan_y_los_agrega(falsos: tuple[EmbeddingsFalsos, Juez]) -> None:
    embeddings, _ = falsos
    pagado, _ = ejecutar_matching(PDF, EXCEL)
    vectores = {t: EmbeddingsFalsos.vector(t) for t in TEXTOS[::2]}

    mixto, metas = ejecutar_matching(PDF, EXCEL, vectores=vectores)

    assert embeddings.llamadas[-1] == TEXTOS[1::2]
    assert [m for m in metas if m.get("etapa") == "embeddings"] == [
        {"etapa": "embeddings", "modelo": "m", "tokens_total": 9}]
    assert set(vectores) == set(TEXTOS)
    assert _dump(mixto) == _dump(pagado)


def test_estricto_con_un_vector_faltante_falla_sin_llamar_a_nadie(
    falsos: tuple[EmbeddingsFalsos, Juez], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(etapa4_matching, "calcular_embeddings", _prohibido)
    monkeypatch.setattr(etapa4_matching, "llamar_llm_estructurado", _prohibido)
    vectores = {t: EmbeddingsFalsos.vector(t) for t in TEXTOS[:-1]}

    with pytest.raises(etapa4_matching.VectoresFaltantesError,
                       match="1 de los 6 textos") as exc:
        ejecutar_matching(PDF, EXCEL, vectores=vectores, vectores_estrictos=True)

    assert exc.value.llm_metadata == []  # type: ignore[attr-defined]
    with pytest.raises(etapa4_matching.VectoresFaltantesError):
        ejecutar_matching(PDF, EXCEL, vectores_estrictos=True)   # sin vectores: todos faltan


def test_el_llamador_inyectado_reemplaza_al_juez_solo_en_esa_ejecucion(
    falsos: tuple[EmbeddingsFalsos, Juez]
) -> None:
    _, juez_del_modulo = falsos
    inyectado = Juez()
    pagado, metas_pagadas = ejecutar_matching(PDF, EXCEL)
    llamadas_modulo = len(juez_del_modulo.llamadas)

    con_inyectado, metas = ejecutar_matching(PDF, EXCEL, llamar=inyectado)

    assert len(juez_del_modulo.llamadas) == llamadas_modulo
    assert [k["user_prompt"] for k in inyectado.llamadas] == [
        k["user_prompt"] for k in juez_del_modulo.llamadas]
    assert _dump(con_inyectado) == _dump(pagado) and metas == metas_pagadas
    assert etapa4_matching._LLAMADOR.get() is None
    ejecutar_matching(PDF, EXCEL)   # la siguiente vuelve al del módulo
    assert len(juez_del_modulo.llamadas) == 2 * llamadas_modulo


def test_si_el_llamador_inyectado_falla_queda_su_entrada_y_se_restaura(
    falsos: tuple[EmbeddingsFalsos, Juez]
) -> None:
    _, juez_del_modulo = falsos

    def _falla(**kw: Any) -> Any:
        raise RuntimeError("sin caché para esta llamada")

    with pytest.raises(RuntimeError, match="sin caché") as exc:
        ejecutar_matching(PDF, EXCEL, llamar=_falla)

    (embeddings, fallida) = exc.value.llm_metadata  # type: ignore[attr-defined]
    assert embeddings["etapa"] == "embeddings"
    assert fallida["llamada_fallida"] is True and fallida["pano"] == "C1"
    assert etapa4_matching._LLAMADOR.get() is None
    antes = len(juez_del_modulo.llamadas)
    ejecutar_matching(PDF, EXCEL)
    assert len(juez_del_modulo.llamadas) > antes


@pytest.fixture(autouse=True)
def _sin_descripcion_identica(monkeypatch: pytest.MonkeyPatch) -> None:
    """Estos tests fijan el camino del juez con descripciones idénticas (y lo que
    reproducen de B2, AG1 y AG2, que corrieron sin M30). DESCRIPCION_IDENTICA,
    encendido por defecto desde el 2026-10-27, se prueba en
    test_etapa4_descripcion_identica.py."""
    monkeypatch.setattr(settings, "descripcion_identica", False)
