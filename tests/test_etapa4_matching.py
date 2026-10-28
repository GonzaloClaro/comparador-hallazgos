"""Tests de la Etapa 4: matching por (paño, relé).

Sin llamadas reales a OpenAI: embeddings y juez se reemplazan por fakes.
Los embeddings fake asignan un vector one-hot por texto único, de modo que
textos idénticos tienen similitud 1.0 y textos distintos 0.0.
"""

from typing import Any

import numpy as np
import pytest

from comparador import etapa4_matching
from comparador.config import settings
from comparador.etapa4_matching import (
    _ALIAS_CLASIFICACION,
    _CLASIFICACIONES_SEC,
    _NOTA_DESEMPATE,
    JuezInvalidoError,
    _clave_clasificacion,
    _JuezResponse,
    _limpiar_justificacion_juez,
    _mejor_asignacion,
    ejecutar_matching,
)
from comparador.llm.embeddings import similitud_coseno
from comparador.schemas import (
    Calificacion,
    CampoDiferente,
    EstadoHallazgo,
    Evidencia,
    FuenteEvidencia,
    Hallazgo,
    MotivoDiferencia,
    TipoMatch,
)


def _hallazgo(
    pano: str = "C1",
    rele: str = "SEL 351R",
    clasificacion: str = "Verificación DUF",
    descripcion: str = "Relaciones de transformación desactualizadas en DUF.",
    accion: str = "Actualizar la relación de transformación del DUF.",
    calificacion: Calificacion = Calificacion.MENOR,
    fuente: FuenteEvidencia = FuenteEvidencia.PDF,
    es_transversal: bool = False,
) -> Hallazgo:
    return Hallazgo(
        pano=pano,
        rele=rele,
        clasificacion=clasificacion,
        descripcion=descripcion,
        accion_correctiva=accion,
        calificacion=calificacion,
        es_transversal=es_transversal,
        evidencia=Evidencia(fuente=fuente, texto_crudo=descripcion),
    )


@pytest.fixture
def embeddings_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un vector one-hot por texto único: iguales → sim 1.0, distintos → 0.0."""

    def _calcular(
        textos: list[str],
    ) -> tuple[np.ndarray[Any, np.dtype[np.float64]], None]:
        matriz = np.zeros((len(textos), max(len(textos), 1)), dtype=np.float64)
        indice_por_texto: dict[str, int] = {}
        for i, t in enumerate(textos):
            j = indice_por_texto.setdefault(t, len(indice_por_texto))
            matriz[i, j] = 1.0
        return matriz, None

    monkeypatch.setattr(etapa4_matching, "calcular_embeddings", _calcular)


@pytest.fixture
def juez_prohibido(monkeypatch: pytest.MonkeyPatch) -> None:
    """Falla si el matching invoca al LLM-as-judge."""

    def _no_llamar(**kwargs: Any) -> Any:
        raise AssertionError("El juez LLM no debería invocarse en este caso.")

    monkeypatch.setattr(etapa4_matching, "llamar_llm_estructurado", _no_llamar)


@pytest.fixture(params=[False, True], ids=["en-orden", "asignacion-global"])
def ambos_modos(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> bool:
    """El test corre con el emparejamiento en orden (ASIGNACION_GLOBAL=false:
    el del control de PD26 y el de B2) y con la asignación global (el default
    desde el 2026-10-26): lo que prueba no depende del modo."""
    monkeypatch.setattr(settings, "asignacion_global", request.param)
    return bool(request.param)


@pytest.fixture(autouse=True)
def _sin_juez_redaccion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Estos tests fijan el matching y la detección por umbral con la pasada
    final (4e) apagada, que es el comportamiento previo exacto. La polaridad
    y el juez de redacción se prueban en test_etapa4_redaccion.py."""
    monkeypatch.setattr(settings, "juez_redaccion", False)


class TestMatchingPorUnicidad:
    def test_unicidad_identica_coincide_sin_llm(
        self, embeddings_fake: None, juez_prohibido: None
    ):
        pdf = [_hallazgo(fuente=FuenteEvidencia.PDF)]
        excel = [_hallazgo(fuente=FuenteEvidencia.EXCEL)]

        resultados, metas = ejecutar_matching(pdf, excel)

        assert len(resultados) == 1
        r = resultados[0]
        assert r.tipo_match == TipoMatch.UNICIDAD
        assert r.confianza == 1.0
        assert r.estado == EstadoHallazgo.COINCIDE
        assert r.diferencias == []
        assert metas == []

    def test_unicidad_calificacion_distinta_difiere(
        self, embeddings_fake: None, juez_prohibido: None
    ):
        pdf = [_hallazgo(calificacion=Calificacion.RELEVANTE)]
        excel = [_hallazgo(calificacion=Calificacion.MENOR, fuente=FuenteEvidencia.EXCEL)]

        resultados, _ = ejecutar_matching(pdf, excel)

        r = resultados[0]
        assert r.tipo_match == TipoMatch.UNICIDAD
        assert r.estado == EstadoHallazgo.DIFIERE
        assert [d.campo for d in r.diferencias] == [CampoDiferente.CALIFICACION]
        assert r.diferencias[0].valor_pdf == "Relevante"
        assert r.diferencias[0].valor_excel == "Menor"

    def test_unicidad_clasificacion_case_insensitive(
        self, embeddings_fake: None, juez_prohibido: None
    ):
        pdf = [_hallazgo(clasificacion="verificación duf")]
        excel = [_hallazgo(clasificacion="Verificación DUF", fuente=FuenteEvidencia.EXCEL)]

        resultados, _ = ejecutar_matching(pdf, excel)
        assert resultados[0].tipo_match == TipoMatch.UNICIDAD

    def test_no_cruza_tuplas(self, embeddings_fake: None, juez_prohibido: None):
        # Misma clasificación pero paños distintos: nunca match cross-tupla.
        pdf = [_hallazgo(pano="C1")]
        excel = [_hallazgo(pano="C2", fuente=FuenteEvidencia.EXCEL)]

        resultados, _ = ejecutar_matching(pdf, excel)

        estados = {r.estado for r in resultados}
        assert estados == {EstadoHallazgo.FALTA_EN_EXCEL, EstadoHallazgo.EXTRA_EN_EXCEL}
        assert all(r.tipo_match == TipoMatch.SIN_MATCH for r in resultados)

    @pytest.mark.usefixtures("ambos_modos")
    def test_clasificacion_repetida_no_va_por_unicidad(
        self, embeddings_fake: None, monkeypatch: pytest.MonkeyPatch
    ):
        # Dos hallazgos de la misma clasificación en el PDF: el carril de
        # unicidad no aplica y el juez LLM decide.
        llamadas: list[dict[str, Any]] = []

        def _juez_fake(**kwargs: Any) -> tuple[_JuezResponse, dict[str, Any]]:
            llamadas.append(kwargs)
            return (
                _JuezResponse(indice_candidato=0, confianza=90, justificacion="Match claro."),
                {"tokens_total": 100},
            )

        monkeypatch.setattr(etapa4_matching, "llamar_llm_estructurado", _juez_fake)

        pdf = [
            _hallazgo(descripcion="Problema A en DUF."),
            _hallazgo(descripcion="Problema B en DUF."),
        ]
        excel = [
            _hallazgo(descripcion="Problema A en DUF.", fuente=FuenteEvidencia.EXCEL),
            _hallazgo(descripcion="Problema B en DUF.", fuente=FuenteEvidencia.EXCEL),
        ]

        resultados, metas = ejecutar_matching(pdf, excel)

        assert len(llamadas) == 2
        assert len(metas) == 2
        assert all(r.tipo_match == TipoMatch.SEMANTICO_ALTO for r in resultados)
        assert all(r.confianza == 0.9 for r in resultados)


class TestCamposVacios:
    def test_accion_vacia_es_diferencia_automatica(
        self, embeddings_fake: None, juez_prohibido: None
    ):
        # Vacío en un lado, contenido en el otro: diferencia sin embeddings.
        pdf = [_hallazgo(accion="")]
        excel = [_hallazgo(accion="Actualizar el DUF.", fuente=FuenteEvidencia.EXCEL)]

        resultados, _ = ejecutar_matching(pdf, excel)

        r = resultados[0]
        assert r.estado == EstadoHallazgo.DIFIERE
        assert [d.campo for d in r.diferencias] == [CampoDiferente.ACCION_CORRECTIVA]
        assert r.diferencias[0].detalle == "Con contenido solo en el Excel (vacío en el PDF)"
        assert r.diferencias[0].motivo == MotivoDiferencia.VACIO_UN_LADO

    def test_cache_no_embebe_strings_vacios(self, monkeypatch: pytest.MonkeyPatch):
        # La API de embeddings rechaza "" — nunca debe llegar al batch.
        recibidos: list[list[str]] = []

        def _calcular(
            textos: list[str],
        ) -> tuple[np.ndarray[Any, np.dtype[np.float64]], None]:
            recibidos.append(textos)
            return np.eye(max(len(textos), 1), dtype=np.float64)[: len(textos)], None

        monkeypatch.setattr(etapa4_matching, "calcular_embeddings", _calcular)
        monkeypatch.setattr(
            etapa4_matching, "llamar_llm_estructurado",
            lambda **kw: (_JuezResponse(indice_candidato=0, confianza=90, justificacion="x"), {}),
        )

        pdf = [_hallazgo(accion="")]
        excel = [_hallazgo(accion="", fuente=FuenteEvidencia.EXCEL)]
        ejecutar_matching(pdf, excel)

        for batch in recibidos:
            assert "" not in batch


class TestInanicionTopK:
    def test_candidatos_tomados_no_bloquean_a_los_tardios(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Tupla con más candidatos que top_k (5): el pool debe recalcularse
        excluyendo los ya matcheados ANTES del top-k, o los últimos hallazgos
        quedan sin candidatos (falsos "falta en Excel"). Es el modo en orden
        (ASIGNACION_GLOBAL=false); el de la asignación global, que ve las filas
        tomadas, es test_inanicion_del_top_k en test_etapa4_asignacion_global."""
        monkeypatch.setattr(settings, "asignacion_global", False)
        n = 6

        # Embeddings artificiales: todos los PDF prefieren a los Excel en el
        # mismo orden E0 > E1 > ... > E5 (ángulos crecientes en 2D).
        vectores: dict[str, np.ndarray[Any, np.dtype[np.float64]]] = {}
        for j in range(n):
            angulo = j * 0.1
            vectores[f"Hallazgo excel {j}"] = np.array([np.cos(angulo), np.sin(angulo)])
            vectores[f"Hallazgo pdf {j}"] = np.array([1.0, 0.0])

        neutro = np.array([0.0, 1.0])

        def _calcular(
            textos: list[str],
        ) -> tuple[np.ndarray[Any, np.dtype[np.float64]], None]:
            return np.array([vectores.get(t, neutro) for t in textos]), None

        monkeypatch.setattr(etapa4_matching, "calcular_embeddings", _calcular)
        monkeypatch.setattr(
            etapa4_matching, "llamar_llm_estructurado",
            lambda **kw: (_JuezResponse(indice_candidato=0, confianza=90, justificacion="x"), {}),
        )

        # Misma clasificación repetida en ambos lados: unicidad no aplica.
        pdf = [_hallazgo(descripcion=f"Hallazgo pdf {i}", accion=f"a{i}") for i in range(n)]
        excel = [
            _hallazgo(
                descripcion=f"Hallazgo excel {i}", accion=f"a{i}",
                fuente=FuenteEvidencia.EXCEL,
            )
            for i in range(n)
        ]

        resultados, _ = ejecutar_matching(pdf, excel)

        faltantes = [r for r in resultados if r.estado == EstadoHallazgo.FALTA_EN_EXCEL]
        extras = [r for r in resultados if r.estado == EstadoHallazgo.EXTRA_EN_EXCEL]
        assert faltantes == [], "El pool fijo de top-k dejó hallazgos tardíos sin candidatos"
        assert extras == []
        assert sum(1 for r in resultados if r.hallazgo_pdf and r.hallazgo_excel) == n


class TestNormalizacionTuplas:
    def test_separadores_triviales_no_parten_la_tupla(
        self, embeddings_fake: None, juez_prohibido: None
    ):
        # La normalización de _clave_tupla (separadores/mayúsculas) NO es
        # fusión de grafías: "SEL-787" y "SEL 787" son la misma escritura.
        pdf = [_hallazgo(rele="SEL-787")]
        excel = [_hallazgo(rele="SEL 787", fuente=FuenteEvidencia.EXCEL)]

        resultados, _ = ejecutar_matching(pdf, excel)

        assert len(resultados) == 1
        assert resultados[0].tipo_match == TipoMatch.UNICIDAD
        assert resultados[0].rele == "SEL 787"  # grafía del Excel (regulatorio)

    def test_grafias_distintas_nunca_se_fusionan(
        self, embeddings_fake: None, juez_prohibido: None
    ):
        # Decisión de la revisora (2026-07-16): el sistema NUNCA unifica
        # grafías con tokens distintos — las tuplas quedan separadas y
        # visibles como falta/extra para que ella decida.
        # Casos reales que antes se fusionaban: Epsilon "SEL-651RA"/"SEL 651R",
        # Añañuca "COOPER KYLE FORM 6"/"COOPER FORM 6".
        pdf = [_hallazgo(pano="C1", rele="COOPER KYLE FORM 6")]
        excel = [_hallazgo(pano="C1", rele="COOPER FORM 6", fuente=FuenteEvidencia.EXCEL)]

        resultados, _ = ejecutar_matching(pdf, excel)

        estados = sorted(r.estado.value for r in resultados)
        assert estados == ["extra_en_excel", "falta_en_excel"]
        assert all("Grafías de relé unificadas" not in r.justificacion for r in resultados)

    def test_calificacion_ausente_no_es_diferencia(
        self, embeddings_fake: None, juez_prohibido: None
    ):
        pdf = [_hallazgo(calificacion=Calificacion.RELEVANTE)]
        excel = [_hallazgo(calificacion=None, fuente=FuenteEvidencia.EXCEL)]

        resultados, _ = ejecutar_matching(pdf, excel)
        assert resultados[0].estado == EstadoHallazgo.COINCIDE
        assert resultados[0].diferencias == []


class TestTransversales:
    def test_transversal_emite_resultado_directo_sin_matching(
        self, embeddings_fake: None, juez_prohibido: None
    ):
        # La transversal sale directo; el hallazgo normal de la misma tupla
        # matchea por unicidad sin que la transversal interfiera.
        pdf = [_hallazgo()]
        excel = [
            _hallazgo(fuente=FuenteEvidencia.EXCEL),
            _hallazgo(
                rele="Análisis de coordinación",
                clasificacion="Coord. de Protecciones",
                descripcion="Estudio de coordinación transversal.",
                fuente=FuenteEvidencia.EXCEL,
                es_transversal=True,
            ),
        ]

        resultados, _ = ejecutar_matching(pdf, excel)

        transversales = [r for r in resultados if r.estado == EstadoHallazgo.TRANSVERSAL]
        assert len(transversales) == 1
        t = transversales[0]
        assert t.tipo_match == TipoMatch.SIN_MATCH
        assert t.confianza == 0.0
        assert t.hallazgo_pdf is None
        assert t.hallazgo_excel is not None
        assert "transversal" in t.justificacion.lower()

        unicidad = [r for r in resultados if r.tipo_match == TipoMatch.UNICIDAD]
        assert len(unicidad) == 1

    def test_pdf_identico_a_transversal_queda_falta_en_excel(
        self, embeddings_fake: None, juez_prohibido: None
    ):
        # La transversal no es candidata del matching: un hallazgo del PDF
        # con texto idéntico NO se le empareja.
        pdf = [_hallazgo(descripcion="Estudio de coordinación transversal.")]
        excel = [
            _hallazgo(
                rele="Análisis de coordinación",
                descripcion="Estudio de coordinación transversal.",
                fuente=FuenteEvidencia.EXCEL,
                es_transversal=True,
            ),
        ]

        resultados, _ = ejecutar_matching(pdf, excel)

        estados = sorted(r.estado.value for r in resultados)
        assert estados == ["falta_en_excel", "transversal"]

    def test_transversal_no_consume_embeddings(
        self, monkeypatch: pytest.MonkeyPatch, juez_prohibido: None
    ):
        capturados: list[str] = []

        def _calcular(
            textos: list[str],
        ) -> tuple[np.ndarray[Any, np.dtype[np.float64]], None]:
            capturados.extend(textos)
            matriz = np.zeros((len(textos), max(len(textos), 1)), dtype=np.float64)
            for i in range(len(textos)):
                matriz[i, i % matriz.shape[1]] = 1.0
            return matriz, None

        monkeypatch.setattr(etapa4_matching, "calcular_embeddings", _calcular)

        pdf = [_hallazgo()]
        excel = [
            _hallazgo(fuente=FuenteEvidencia.EXCEL),
            _hallazgo(
                rele="Análisis de coordinación",
                descripcion="Texto transversal que no debe embeberse.",
                fuente=FuenteEvidencia.EXCEL,
                es_transversal=True,
            ),
        ]

        ejecutar_matching(pdf, excel)

        assert all("transversal que no debe embeberse" not in t for t in capturados)


class TestJuezResponseBounds:
    def test_confianza_valida(self):
        r = _JuezResponse(indice_candidato=0, confianza=90, justificacion="ok")
        assert r.confianza == 90

    @pytest.mark.parametrize("valor", [-1, 100, 150.0])
    def test_confianza_fuera_de_rango_falla(self, valor: float):
        with pytest.raises(ValueError, match="fuera del rango 0-99"):
            _JuezResponse(indice_candidato=0, confianza=valor, justificacion="x")


class TestDeteccionDiferencias:
    def test_orden_descripcion_accion_calificacion(
        self, embeddings_fake: None, juez_prohibido: None
    ):
        # Los tres campos difieren; el orden reportado es obligatorio.
        pdf = [_hallazgo(
            descripcion="Descripción versión PDF.",
            accion="Acción versión PDF.",
            calificacion=Calificacion.RELEVANTE,
        )]
        excel = [_hallazgo(
            descripcion="Descripción versión Excel.",
            accion="Acción versión Excel.",
            calificacion=Calificacion.MENOR,
            fuente=FuenteEvidencia.EXCEL,
        )]

        resultados, _ = ejecutar_matching(pdf, excel)

        r = resultados[0]
        assert r.estado == EstadoHallazgo.DIFIERE
        assert [d.campo for d in r.diferencias] == [
            CampoDiferente.DESCRIPCION,
            CampoDiferente.ACCION_CORRECTIVA,
            CampoDiferente.CALIFICACION,
        ]
        assert r.diferencias[2].motivo == MotivoDiferencia.CALIFICACION_DISTINTA

    def test_detalle_similitud_incluye_umbral(
        self, embeddings_fake: None, juez_prohibido: None
    ):
        # El detalle debe dar la referencia completa: similitud medida + umbral.
        pdf = [_hallazgo(descripcion="Descripción versión PDF.")]
        excel = [_hallazgo(
            descripcion="Descripción versión Excel.", fuente=FuenteEvidencia.EXCEL,
        )]

        resultados, _ = ejecutar_matching(pdf, excel)

        d = resultados[0].diferencias[0]
        assert d.campo == CampoDiferente.DESCRIPCION
        assert d.detalle == (
            f"Similitud semántica 0.00, bajo el umbral de coincidencia "
            f"{settings.threshold_descripcion:.2f}"
        )
        assert d.motivo == MotivoDiferencia.SIMILITUD_BAJA


@pytest.mark.usefixtures("ambos_modos")
class TestConfianzaSemantica:
    def test_confianza_baja_es_semantico_bajo(
        self, embeddings_fake: None, monkeypatch: pytest.MonkeyPatch
    ):
        def _juez_fake(**kwargs: Any) -> tuple[_JuezResponse, dict[str, Any]]:
            return (
                _JuezResponse(indice_candidato=0, confianza=60, justificacion="Dudoso."),
                {},
            )

        monkeypatch.setattr(etapa4_matching, "llamar_llm_estructurado", _juez_fake)

        pdf = [
            _hallazgo(descripcion="Problema A."),
            _hallazgo(descripcion="Problema B."),
        ]
        excel = [
            _hallazgo(descripcion="Problema A.", fuente=FuenteEvidencia.EXCEL),
            _hallazgo(descripcion="Problema C.", fuente=FuenteEvidencia.EXCEL),
        ]

        resultados, _ = ejecutar_matching(pdf, excel)
        semanticos = [r for r in resultados if r.tipo_match == TipoMatch.SEMANTICO_BAJO]
        assert semanticos
        assert all(r.confianza == 0.6 for r in semanticos)

    def test_indice_fuera_de_rango_falla_ruidoso_con_metadata(
        self, embeddings_fake: None, monkeypatch: pytest.MonkeyPatch
    ):
        # Un índice imposible es un error del LLM, no un rechazo: degradarlo
        # dejaría una justificación que afirma lo contrario del estado.
        def _juez_fake(**kwargs: Any) -> tuple[_JuezResponse, dict[str, Any]]:
            return (
                _JuezResponse(indice_candidato=7, confianza=90, justificacion="x"),
                {"tokens_total": 100},
            )

        monkeypatch.setattr(etapa4_matching, "llamar_llm_estructurado", _juez_fake)

        pdf = [_hallazgo(descripcion="Problema A."), _hallazgo(descripcion="Problema B.")]
        excel = [
            _hallazgo(descripcion="Problema A.", fuente=FuenteEvidencia.EXCEL),
            _hallazgo(descripcion="Problema C.", fuente=FuenteEvidencia.EXCEL),
        ]

        with pytest.raises(JuezInvalidoError, match="índice 7") as exc_info:
            ejecutar_matching(pdf, excel)
        # La metadata de las llamadas ya pagadas viaja con el error para que
        # el pipeline la persista (invariante 20).
        assert any(m.get("tokens_total") == 100 for m in exc_info.value.llm_metadata)

    def test_juez_rechaza_queda_falta_en_excel_con_confianza_cero(
        self, embeddings_fake: None, monkeypatch: pytest.MonkeyPatch
    ):
        def _juez_fake(**kwargs: Any) -> tuple[_JuezResponse, dict[str, Any]]:
            return (
                _JuezResponse(indice_candidato=None, confianza=20, justificacion="Nada calza."),
                {},
            )

        monkeypatch.setattr(etapa4_matching, "llamar_llm_estructurado", _juez_fake)

        pdf = [
            _hallazgo(descripcion="Problema A."),
            _hallazgo(descripcion="Problema B."),
        ]
        excel = [
            _hallazgo(descripcion="Problema X.", fuente=FuenteEvidencia.EXCEL),
            _hallazgo(descripcion="Problema Y.", fuente=FuenteEvidencia.EXCEL),
        ]

        resultados, _ = ejecutar_matching(pdf, excel)

        faltantes = [r for r in resultados if r.estado == EstadoHallazgo.FALTA_EN_EXCEL]
        assert len(faltantes) == 2
        assert all(r.confianza == 0.0 for r in faltantes)
        extras = [r for r in resultados if r.estado == EstadoHallazgo.EXTRA_EN_EXCEL]
        assert len(extras) == 2

    def test_referencia_a_candidato_se_limpia_en_el_resultado(
        self, embeddings_fake: None, monkeypatch: pytest.MonkeyPatch
    ):
        def _juez_fake(**kwargs: Any) -> tuple[_JuezResponse, dict[str, Any]]:
            return (
                _JuezResponse(
                    indice_candidato=0, confianza=90,
                    justificacion="El PDF reporta X; el candidato [0] es idéntico.",
                ),
                {},
            )

        monkeypatch.setattr(etapa4_matching, "llamar_llm_estructurado", _juez_fake)

        pdf = [_hallazgo(descripcion="Problema A."), _hallazgo(descripcion="Problema B.")]
        excel = [
            _hallazgo(descripcion="Problema A.", fuente=FuenteEvidencia.EXCEL),
            _hallazgo(descripcion="Problema C.", fuente=FuenteEvidencia.EXCEL),
        ]

        resultados, _ = ejecutar_matching(pdf, excel)

        semanticos = [r for r in resultados if r.tipo_match == TipoMatch.SEMANTICO_ALTO]
        assert semanticos
        assert all("candidato" not in r.justificacion.lower() for r in semanticos)
        assert all("[0]" not in r.justificacion for r in semanticos)
        assert "el Excel es idéntico" in semanticos[0].justificacion


class TestLimpiarJustificacionJuez:
    def test_candidato_singular_se_reemplaza_por_excel(self):
        texto = "El PDF reporta X; el candidato [0] es idéntico."
        assert _limpiar_justificacion_juez(texto) == "El PDF reporta X; el Excel es idéntico."

    @pytest.mark.parametrize("indice", [0, 1, 2, 13])
    def test_da_igual_el_indice(self, indice: int):
        texto = f"el candidato [{indice}] registra lo mismo"
        assert _limpiar_justificacion_juez(texto) == "el Excel registra lo mismo"

    def test_candidatos_plural_con_dos_indices_colapsa_a_uno(self):
        texto = "los candidatos [0] y [1] describen síntomas del mismo problema"
        esperado = "los Excel describen síntomas del mismo problema"
        assert _limpiar_justificacion_juez(texto) == esperado

    def test_sin_referencia_a_candidato_queda_intacto(self):
        texto = "Ningún candidato corresponde al hallazgo del PDF."
        assert _limpiar_justificacion_juez(texto) == texto


class TestAliasClasificacion:
    def test_alias_apuntan_a_categorias_oficiales(self):
        assert set(_ALIAS_CLASIFICACION.values()) <= set(_CLASIFICACIONES_SEC)
        assert not set(_ALIAS_CLASIFICACION) & set(_CLASIFICACIONES_SEC)

    def test_categorias_oficiales_no_colapsan_entre_si(self):
        claves = {_clave_clasificacion(_hallazgo(clasificacion=c)) for c in _CLASIFICACIONES_SEC}
        assert len(claves) == len(_CLASIFICACIONES_SEC)

    @pytest.mark.parametrize(
        ("variante", "canonica"),
        [
            ("Acceso, Registro y Sincr.", "Ver. Acceso, Registro y Sincr."),
            ("Coord. de Protecciones", "Ver. Coord. de Protecciones"),
            ("Ver. Coor. de Protecciones", "Ver. Coord. de Protecciones"),
            ("Ver. Acceso, Registro y Sinc.", "Ver. Acceso, Registro y Sincr."),
            ("Prueba Apert. Interruptor", "Prueba Apert. de Interruptor"),
            # Mayúsculas, espacios repetidos y sin punto final.
            ("ACCESO,  registro y Sincr", "Ver. Acceso, Registro y Sincr."),
            (" Verificación  ECAP. ", "Verificación ECAP"),
        ],
    )
    def test_variante_y_canonica_comparten_clave(self, variante: str, canonica: str):
        assert _clave_clasificacion(_hallazgo(clasificacion=variante)) == _clave_clasificacion(
            _hallazgo(clasificacion=canonica)
        )

    def test_alias_habilita_unicidad_sin_juez_y_conserva_literales(
        self, embeddings_fake: None, juez_prohibido: None
    ):
        # Zeta: el Excel escribe "Acceso, Registro y Sincr." fuera de la
        # lista desplegable; el PDF trae la categoría oficial.
        pdf = [_hallazgo(clasificacion="Ver. Acceso, Registro y Sincr.")]
        excel = [_hallazgo(
            clasificacion="Acceso, Registro y Sincr.", fuente=FuenteEvidencia.EXCEL,
        )]

        resultados, _ = ejecutar_matching(pdf, excel)

        assert len(resultados) == 1
        r = resultados[0]
        assert r.tipo_match == TipoMatch.UNICIDAD
        assert r.estado == EstadoHallazgo.COINCIDE
        assert r.hallazgo_pdf is not None and r.hallazgo_excel is not None
        assert r.hallazgo_pdf.clasificacion == "Ver. Acceso, Registro y Sincr."
        assert r.hallazgo_excel.clasificacion == "Acceso, Registro y Sincr."
        assert "(Excel: 'Acceso, Registro y Sincr.')" in r.justificacion


_DESC_BETA = (
    "La base Infotécnica no considera información asociada a la protección "
    "SEL 651R del paño E1."
)
_ACCION_ECAP = (
    "Se debe disponer en la base de Infotécnica del ECAP actualizado asociado "
    "al equipo auditado de acuerdo con el artículo 6-4 de la NTSyCS 2019."
)
_ACCION_PRINT_OUT = (
    "Se debe cargar en la base de Infotécnica el Print Out asociado al equipo auditado."
)


def _beta(
    accion: str,
    calificacion: Calificacion,
    fuente: FuenteEvidencia,
    descripcion: str = _DESC_BETA,
) -> Hallazgo:
    return _hallazgo(
        pano="E1", rele="SEL 651R", clasificacion="Verificación ECAP",
        descripcion=descripcion, accion=accion, calificacion=calificacion, fuente=fuente,
    )


@pytest.fixture
def juez_elige_primero(monkeypatch: pytest.MonkeyPatch, ambos_modos: bool) -> None:
    """Juez que siempre elige el primer candidato, y top-k que ante empates
    de similitud respeta el orden del Excel: con descripciones idénticas el
    juez toma el primer Excel, sin mirar la acción. En los dos modos: en orden
    (ASIGNACION_GLOBAL=false) toma el primero libre; con la asignación global
    (el default, que corre el desempate por acción después) pide también la
    fila ya tomada, la pierde en empate y la vuelve a pedir sin ella."""

    def _top_k(
        query: np.ndarray[Any, np.dtype[np.float64]],
        candidatos: np.ndarray[Any, np.dtype[np.float64]],
        k: int = 5,
    ) -> list[tuple[int, float]]:
        sims = [similitud_coseno(query, c) for c in candidatos]
        orden = sorted(range(len(sims)), key=lambda i: -sims[i])[:k]
        return [(i, sims[i]) for i in orden]

    def _juez(**kwargs: Any) -> tuple[_JuezResponse, dict[str, Any]]:
        return (
            _JuezResponse(indice_candidato=0, confianza=95, justificacion="Misma descripción."),
            {},
        )

    monkeypatch.setattr(etapa4_matching, "top_k_similares", _top_k)
    monkeypatch.setattr(etapa4_matching, "llamar_llm_estructurado", _juez)


class TestDesempatePorAccion:
    def test_caso_beta_juez_cruzado_se_corrige(
        self, embeddings_fake: None, juez_elige_primero: None
    ):
        pdf = [
            _beta(_ACCION_ECAP, Calificacion.RELEVANTE, FuenteEvidencia.PDF),
            _beta(_ACCION_PRINT_OUT, Calificacion.MENOR, FuenteEvidencia.PDF),
        ]
        # Orden inverso en el Excel: el juez empareja ECAP↔Print Out.
        excel = [
            _beta(_ACCION_PRINT_OUT, Calificacion.MENOR, FuenteEvidencia.EXCEL),
            _beta(_ACCION_ECAP, Calificacion.RELEVANTE, FuenteEvidencia.EXCEL),
        ]

        resultados, _ = ejecutar_matching(pdf, excel)

        assert len(resultados) == 2
        for r in resultados:
            assert r.hallazgo_pdf is not None and r.hallazgo_excel is not None
            assert r.hallazgo_pdf.accion_correctiva == r.hallazgo_excel.accion_correctiva
            assert r.hallazgo_pdf.calificacion == r.hallazgo_excel.calificacion
            assert r.estado == EstadoHallazgo.COINCIDE
            assert r.diferencias == []
            assert r.tipo_match == TipoMatch.SEMANTICO_ALTO
            assert r.confianza == 0.95
            assert r.justificacion == f"Misma descripción. {_NOTA_DESEMPATE}"

    def test_asignacion_del_juez_ya_optima_no_agrega_nota(
        self, embeddings_fake: None, juez_elige_primero: None, ambos_modos: bool
    ):
        pdf = [
            _beta(_ACCION_ECAP, Calificacion.RELEVANTE, FuenteEvidencia.PDF),
            _beta(_ACCION_PRINT_OUT, Calificacion.MENOR, FuenteEvidencia.PDF),
        ]
        excel = [
            _beta(_ACCION_ECAP, Calificacion.RELEVANTE, FuenteEvidencia.EXCEL),
            _beta(_ACCION_PRINT_OUT, Calificacion.MENOR, FuenteEvidencia.EXCEL),
        ]

        resultados, _ = ejecutar_matching(pdf, excel)

        assert all(r.estado == EstadoHallazgo.COINCIDE for r in resultados)
        assert all(_NOTA_DESEMPATE not in r.justificacion for r in resultados)
        primero, segundo = resultados
        assert primero.justificacion == "Misma descripción."
        if ambos_modos:
            # El segundo pidió la fila del primero (descripción idéntica), la perdió
            # en empate y tomó la suya al volver a preguntar: lleva la nota de la
            # asignación global, no la del desempate (que no cambió nada).
            assert segundo.justificacion == (
                "Misma descripción. (Asignación global: antes perdió una fila del Excel frente "
                "a otro hallazgo al que el juez dio la misma confianza (0.95); en un empate se "
                "queda el que ya tenía la fila.)")
        else:
            assert segundo.justificacion == "Misma descripción."

    def test_descripciones_distintas_no_se_reasignan(
        self, embeddings_fake: None, juez_elige_primero: None
    ):
        # La acción solo desempata entre descripciones idénticas: aunque
        # cruzar mejore la acción, la descripción sigue mandando (inv. 15).
        desc_e1 = _DESC_BETA
        desc_e2 = _DESC_BETA.replace("paño E1", "paño E2")
        pdf = [
            _beta(_ACCION_ECAP, Calificacion.RELEVANTE, FuenteEvidencia.PDF, desc_e1),
            _beta(_ACCION_PRINT_OUT, Calificacion.MENOR, FuenteEvidencia.PDF, desc_e2),
        ]
        excel = [
            _beta(_ACCION_PRINT_OUT, Calificacion.MENOR, FuenteEvidencia.EXCEL, desc_e1),
            _beta(_ACCION_ECAP, Calificacion.RELEVANTE, FuenteEvidencia.EXCEL, desc_e2),
        ]

        resultados, _ = ejecutar_matching(pdf, excel)

        assert len(resultados) == 2
        for r in resultados:
            assert r.hallazgo_pdf is not None and r.hallazgo_excel is not None
            assert r.hallazgo_pdf.descripcion == r.hallazgo_excel.descripcion
            assert r.estado == EstadoHallazgo.DIFIERE
            assert [d.campo for d in r.diferencias] == [
                CampoDiferente.ACCION_CORRECTIVA, CampoDiferente.CALIFICACION,
            ]
            assert _NOTA_DESEMPATE not in r.justificacion

    def test_descripcion_excel_distinta_no_entra_al_grupo(
        self, embeddings_fake: None, juez_elige_primero: None
    ):
        # Ambos PDF dicen X, pero el segundo Excel dice Y: el par PDF X ↔
        # Excel Y no se toca aunque cruzar mejore la acción — solo se
        # desempata entre filas de descripción idéntica en AMBOS lados.
        desc_y = _DESC_BETA.replace("paño E1", "paño E2")
        pdf = [
            _beta(_ACCION_ECAP, Calificacion.RELEVANTE, FuenteEvidencia.PDF),
            _beta(_ACCION_PRINT_OUT, Calificacion.MENOR, FuenteEvidencia.PDF),
        ]
        excel = [
            _beta(_ACCION_PRINT_OUT, Calificacion.MENOR, FuenteEvidencia.EXCEL),
            _beta(_ACCION_ECAP, Calificacion.RELEVANTE, FuenteEvidencia.EXCEL, desc_y),
        ]

        resultados, _ = ejecutar_matching(pdf, excel)

        assert len(resultados) == 2
        pares = {
            (r.hallazgo_pdf.accion_correctiva, r.hallazgo_excel.accion_correctiva)
            for r in resultados
            if r.hallazgo_pdf is not None and r.hallazgo_excel is not None
        }
        assert pares == {(_ACCION_ECAP, _ACCION_PRINT_OUT), (_ACCION_PRINT_OUT, _ACCION_ECAP)}
        assert all(_NOTA_DESEMPATE not in r.justificacion for r in resultados)

    def test_sin_accion_no_hay_desempate(
        self, embeddings_fake: None, juez_elige_primero: None
    ):
        # Sin acción en el PDF no hay señal para desempatar: se respeta al juez.
        pdf = [
            _beta("", Calificacion.RELEVANTE, FuenteEvidencia.PDF),
            _beta("", Calificacion.MENOR, FuenteEvidencia.PDF),
        ]
        excel = [
            _beta(_ACCION_PRINT_OUT, Calificacion.MENOR, FuenteEvidencia.EXCEL),
            _beta(_ACCION_ECAP, Calificacion.RELEVANTE, FuenteEvidencia.EXCEL),
        ]

        resultados, _ = ejecutar_matching(pdf, excel)

        assert all(_NOTA_DESEMPATE not in r.justificacion for r in resultados)

    def test_excel_omite_una_fila_el_faltante_cae_en_la_correcta(
        self, embeddings_fake: None, juez_elige_primero: None
    ):
        # El Excel omitió la fila ECAP/Relevante. El juez empareja el primer
        # PDF (ECAP) con la única fila del Excel (Print Out) y deja faltante
        # al Print Out: un "difiere" falso y el faltante en la fila equivocada.
        pdf = [
            _beta(_ACCION_ECAP, Calificacion.RELEVANTE, FuenteEvidencia.PDF),
            _beta(_ACCION_PRINT_OUT, Calificacion.MENOR, FuenteEvidencia.PDF),
        ]
        excel = [_beta(_ACCION_PRINT_OUT, Calificacion.MENOR, FuenteEvidencia.EXCEL)]

        resultados, _ = ejecutar_matching(pdf, excel)

        assert len(resultados) == 2
        falta, par = resultados
        assert falta.estado == EstadoHallazgo.FALTA_EN_EXCEL
        assert falta.hallazgo_pdf is not None and falta.hallazgo_excel is None
        assert falta.hallazgo_pdf.accion_correctiva == _ACCION_ECAP
        assert falta.tipo_match == TipoMatch.SIN_MATCH
        assert falta.confianza == 0.0
        assert _NOTA_DESEMPATE in falta.justificacion

        assert par.estado == EstadoHallazgo.COINCIDE
        assert par.hallazgo_pdf is not None and par.hallazgo_excel is not None
        assert par.hallazgo_pdf.accion_correctiva == _ACCION_PRINT_OUT
        assert par.hallazgo_excel.accion_correctiva == _ACCION_PRINT_OUT
        # Hereda el veredicto del juez sobre la descripción (idéntica).
        assert par.tipo_match == TipoMatch.SEMANTICO_ALTO
        assert par.confianza == 0.95
        assert par.justificacion == f"Misma descripción. {_NOTA_DESEMPATE}"

    def test_pdf_omite_una_fila_el_extra_cae_en_la_correcta(
        self, embeddings_fake: None, juez_elige_primero: None
    ):
        pdf = [_beta(_ACCION_PRINT_OUT, Calificacion.MENOR, FuenteEvidencia.PDF)]
        excel = [
            _beta(_ACCION_ECAP, Calificacion.RELEVANTE, FuenteEvidencia.EXCEL),
            _beta(_ACCION_PRINT_OUT, Calificacion.MENOR, FuenteEvidencia.EXCEL),
        ]

        resultados, _ = ejecutar_matching(pdf, excel)

        assert len(resultados) == 2
        par, extra = resultados
        assert par.estado == EstadoHallazgo.COINCIDE
        assert par.hallazgo_excel is not None
        assert par.hallazgo_excel.accion_correctiva == _ACCION_PRINT_OUT
        assert par.justificacion == f"Misma descripción. {_NOTA_DESEMPATE}"

        assert extra.estado == EstadoHallazgo.EXTRA_EN_EXCEL
        assert extra.hallazgo_pdf is None and extra.hallazgo_excel is not None
        assert extra.hallazgo_excel.accion_correctiva == _ACCION_ECAP
        assert _NOTA_DESEMPATE in extra.justificacion

    def test_extra_ya_correcto_no_se_toca(
        self, embeddings_fake: None, juez_elige_primero: None
    ):
        # El juez ya dejó como extra la fila que sobra: sin cambios ni nota.
        pdf = [_beta(_ACCION_PRINT_OUT, Calificacion.MENOR, FuenteEvidencia.PDF)]
        excel = [
            _beta(_ACCION_PRINT_OUT, Calificacion.MENOR, FuenteEvidencia.EXCEL),
            _beta(_ACCION_ECAP, Calificacion.RELEVANTE, FuenteEvidencia.EXCEL),
        ]

        resultados, _ = ejecutar_matching(pdf, excel)

        assert [r.estado for r in resultados] == [
            EstadoHallazgo.COINCIDE, EstadoHallazgo.EXTRA_EN_EXCEL,
        ]
        assert all(_NOTA_DESEMPATE not in r.justificacion for r in resultados)


class TestMejorAsignacion:
    def test_exhaustiva_encuentra_optimo_que_greedy_perderia(self):
        # Greedy tomaría (0,0)=0.9 y dejaría (1,1)=0.0; el óptimo cruza (1.6).
        assert _mejor_asignacion([[0.9, 0.8], [0.8, 0.0]], [(0, 0), (1, 1)]) == [(0, 1), (1, 0)]

    def test_empate_conserva_la_asignacion_del_juez(self):
        assert _mejor_asignacion([[0.5, 0.5], [0.5, 0.5]], [(0, 0), (1, 1)]) == [(0, 0), (1, 1)]

    def test_rectangular_elige_que_fila_queda_sin_par(self):
        # 2 PDF, 1 Excel: el par debe ser el PDF cuya acción calza.
        assert _mejor_asignacion([[0.0], [1.0]], [(0, 0)]) == [(1, 0)]

    def test_entre_optimos_conserva_los_pares_del_juez(self):
        # PDF 0 y 1 son duplicados exactos: ambos óptimos valen 2.0, pero
        # solo uno conserva el par (1, 1) que hizo el juez.
        similitudes = [[0.0, 1.0], [0.0, 1.0], [1.0, 0.0]]
        assert _mejor_asignacion(similitudes, [(0, 0), (1, 1)]) == [(1, 1), (2, 0)]

    def test_greedy_sobre_seis(self):
        n = 7
        rotada = [[1.0 if j == (i + 1) % n else 0.0 for j in range(n)] for i in range(n)]
        identidad = [(i, i) for i in range(n)]
        assert _mejor_asignacion(rotada, identidad) == [(i, (i + 1) % n) for i in range(n)]


def test_top_k_empates_respetan_el_orden_original():
    # Textos idénticos → mismo embedding → empate exacto. El orden debe ser el
    # del Excel (estable); antes argsort()[::-1] lo invertía y cruzaba pares.
    import numpy as np

    from comparador.llm.embeddings import top_k_similares

    q = np.array([1.0, 0.0])
    cands = np.array([[0.0, 1.0], [1.0, 0.0], [1.0, 0.0], [0.5, 0.5]])
    assert [i for i, _ in top_k_similares(q, cands, k=3)] == [1, 2, 3]


@pytest.fixture(autouse=True)
def _sin_descripcion_identica(monkeypatch: pytest.MonkeyPatch) -> None:
    """Estos tests fijan el camino del juez con descripciones idénticas (y lo que
    reproducen de B2, AG1 y AG2, que corrieron sin M30). DESCRIPCION_IDENTICA,
    encendido por defecto desde el 2026-10-27, se prueba en
    test_etapa4_descripcion_identica.py."""
    monkeypatch.setattr(settings, "descripcion_identica", False)
