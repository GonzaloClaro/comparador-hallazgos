"""Tests de la pasada final de la Etapa 4 (4e): polaridad + juez de redacción.

Sin llamadas reales: los embeddings fake dan una similitud coseno exacta por
par de textos y el juez de redacción es un fake de llamar_llm_estructurado.
Los textos de los casos vienen de la ronda B0 (informes reales de Reliable).
"""

import json
import math
from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from comparador import etapa4_matching
from comparador.config import settings
from comparador.etapa4_matching import (
    _MAX_ITEMS_POR_LOTE_REDACCION,
    JuezInvalidoError,
    _JuezRedaccionResponse,
    _polaridad,
    _terminos_sustituidos,
    _VeredictoRedaccion,
    ejecutar_matching,
)
from comparador.llm.prompts import SYSTEM_JUEZ_REDACCION, user_juez_redaccion
from comparador.schemas import (
    Calificacion,
    CampoDiferente,
    Diferencia,
    EstadoHallazgo,
    Evidencia,
    FuenteEvidencia,
    Hallazgo,
    MatchResult,
    TipoMatch,
)

# Alfa E7: diferencia REAL (veredicto invertido) que no se puede perder.
E7_PDF = (
    "Comparación con ECAP adjunto en INFOTÉCNICA: Cumple. Si bien se encuentra "
    "ECAP en infotecnica, no se mencionan los ajustes de la función 79 para el paño E7."
)
E7_PDF_CORTO = "Comparación con ECAP adjunto en INFOTÉCNICA: Cumple"
E7_EXCEL = "Comparación con ECAP adjunto en INFOTÉCNICA: No cumple"
# Zeta C1: paráfrasis con el mismo contenido (0.80 en B0).
SINCRO_PDF = (
    "Sincronización horaria externa. No cumple, ya que se incumple con el "
    "artículo 3-24 de la NTSyCS."
)
SINCRO_EXCEL = (
    "Equipo no posee sincronizacion horaria vía GPS, por lo que incumple con el "
    "artículo 3-24 de la NTSyCS."
)
# Gamma: el Excel detalla lo que el PDF rotula (0.44 en B0).
GAMMA_EXCEL = (
    "Existe un incumplimiento respecto al Art. 5-40 literal b) de la NTSyCS: "
    "despeje ≥ 400 ms en la barra de MT."
)
ACCION = "Se debe gestionar la sincronización horaria del equipo."
THRESHOLD = 0.85


def _hallazgo(
    descripcion: str,
    accion: str | None = ACCION,
    calificacion: Calificacion | None = Calificacion.MENOR,
    fuente: FuenteEvidencia = FuenteEvidencia.PDF,
    pano: str = "C1",
    rele: str = "COOPER FORM 6",
    clasificacion: str = "Ver. Acceso, Registro y Sincr.",
) -> Hallazgo:
    return Hallazgo(
        pano=pano, rele=rele, clasificacion=clasificacion,
        descripcion=descripcion, accion_correctiva=accion, calificacion=calificacion,
        evidencia=Evidencia(
            fuente=fuente, texto_crudo=descripcion,
            pagina_pdf=7 if fuente == FuenteEvidencia.PDF else None,
            fila_excel=12 if fuente == FuenteEvidencia.EXCEL else None,
        ),
    )


def _excel(descripcion: str, **kwargs: Any) -> Hallazgo:
    return _hallazgo(descripcion, fuente=FuenteEvidencia.EXCEL, **kwargs)


@pytest.fixture(autouse=True)
def _redaccion_encendida(monkeypatch: pytest.MonkeyPatch) -> None:
    # Explícito: los tests no dependen del .env local.
    monkeypatch.setattr(settings, "juez_redaccion", True)
    monkeypatch.setattr(settings, "control_codigos", True)
    monkeypatch.setattr(settings, "threshold_descripcion", THRESHOLD)
    monkeypatch.setattr(settings, "threshold_accion", THRESHOLD)


@pytest.fixture
def similitudes(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], float]:
    """Similitud coseno exacta por par (texto_a, texto_b), que cada test
    completa; los demás textos son one-hot (similitud 0 entre distintos).
    Un texto no debe aparecer en dos pares."""
    pares: dict[tuple[str, str], float] = {}

    def _calcular(textos: list[str]) -> tuple[np.ndarray[Any, np.dtype[np.float64]], None]:
        base = 2 * len(pares)
        dim = base + len(textos)
        vectores: dict[str, np.ndarray[Any, np.dtype[np.float64]]] = {}
        for n, ((a, b), s) in enumerate(pares.items()):
            va = np.zeros(dim)
            va[2 * n] = 1.0
            vb = np.zeros(dim)
            vb[2 * n], vb[2 * n + 1] = s, math.sqrt(1 - s * s)
            vectores[a], vectores[b] = va, vb
        matriz = np.zeros((len(textos), dim))
        for i, t in enumerate(textos):
            if t in vectores:
                matriz[i] = vectores[t]
            else:
                matriz[i, base + i] = 1.0
        return matriz, None

    monkeypatch.setattr(etapa4_matching, "calcular_embeddings", _calcular)
    return pares


class JuezRedaccionFake:
    """Reemplaza llamar_llm_estructurado: registra cada lote y responde con
    `decidir(item)`, o con `respuesta(items)` si se fuerza una salida."""

    def __init__(self) -> None:
        self.decidir: Callable[[dict[str, Any]], bool] = lambda item: True
        self.respuesta: Callable[[list[dict[str, Any]]], list[_VeredictoRedaccion]] | None = None
        self.lotes: list[list[dict[str, Any]]] = []
        self.kwargs: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> tuple[_JuezRedaccionResponse, dict[str, Any]]:
        assert kwargs["response_model"] is _JuezRedaccionResponse, (
            "Solo el juez de redacción debería invocarse en estos casos."
        )
        items = json.loads(kwargs["user_prompt"])
        self.lotes.append(items)
        self.kwargs.append(kwargs)
        if self.respuesta is not None:
            veredictos = self.respuesta(items)
        else:
            veredictos = [
                _VeredictoRedaccion(
                    id=it["id"], justificacion=f"justificación {it['id']}",
                    mismo_contenido=self.decidir(it),
                )
                for it in items
            ]
        return _JuezRedaccionResponse(veredictos=veredictos), {"tokens_total": 50}


@pytest.fixture
def juez(monkeypatch: pytest.MonkeyPatch) -> JuezRedaccionFake:
    fake = JuezRedaccionFake()
    monkeypatch.setattr(etapa4_matching, "llamar_llm_estructurado", fake)
    # El prompt real es texto + JSON; el fake recibe solo el JSON de los ítems.
    monkeypatch.setattr(etapa4_matching, "user_juez_redaccion", json.dumps)
    return fake


@pytest.fixture
def juez_prohibido(monkeypatch: pytest.MonkeyPatch) -> None:
    def _no_llamar(**kwargs: Any) -> Any:
        raise AssertionError("Ningún juez LLM debería invocarse en este caso.")

    monkeypatch.setattr(etapa4_matching, "llamar_llm_estructurado", _no_llamar)


class TestPolaridad:
    @pytest.mark.parametrize(
        ("texto", "esperado"),
        [
            (E7_PDF, "+"),
            (E7_PDF_CORTO, "+"),
            (E7_EXCEL, "-"),
            (SINCRO_PDF, "-"),
            (SINCRO_EXCEL, "-"),
            (GAMMA_EXCEL, "-"),
            ("Tiempos de actuación. No Cumple", "-"),
            ("NO SE CUMPLE con el artículo 6-4.", "-"),
            ("Los equipos no cumplen con la norma.", "-"),
            ("Cumple con lo establecido.", "+"),
            ("Sin hallazgos.", "+"),
            ("Correcto, sin anormalidades.", "+"),
            # Negaciones que no son "no (se) cumple" justo antes.
            ("El paño E2 tampoco cumple con el artículo 3-24.", "-"),
            ("El equipo no lo cumple.", "-"),
            ("Cumple: No", "-"),
            ("Cumple: no.", "-"),
            # "cumple" en medio de la frase sigue siendo veredicto: es el caso
            # que la polaridad protege sobre el umbral contra un "no cumple".
            ("El equipo cumple con el artículo 3-24.", "+"),
            ("Cumple: no se observan diferencias.", "+"),
            ("No se observan anormalidades y el equipo cumple con la norma.", "+"),
        ],
    )
    def test_veredicto_explicito(self, texto: str, esperado: str):
        assert _polaridad(texto) == esperado

    @pytest.mark.parametrize(
        "texto",
        [
            # Mixtos: no hay veredicto único.
            "Cumple la función 50, pero no cumple la función 51.",
            "Cumple. Sin embargo, incumple el artículo 3-24.",
            # Cuantificador o matiz: no es un veredicto único.
            "Ningún relé cumple con la sincronización.",
            "No todos los relés cumplen.",
            "Cumple parcialmente con el art. 3-24",
            # Sin marcadores.
            "Relaciones de TC se encuentran erróneas en DUF",
            "Se debe dar cumplimiento al artículo 6-4 de la NTSyCS.",
            "",
        ],
    )
    def test_sin_veredicto_unico_es_none(self, texto: str):
        assert _polaridad(texto) is None


class TestPolaridadEnMatching:
    def test_opuesta_sobre_el_umbral_es_diferencia_sin_juez(
        self, similitudes: dict[tuple[str, str], float], juez_prohibido: None
    ):
        # Caso real (B1, Opus): "Cumple" vs "No cumple" con similitud sobre el
        # umbral quedaba como coincide — los embeddings no ven la negación.
        similitudes[(E7_PDF_CORTO, E7_EXCEL)] = 0.93

        resultados, metas = ejecutar_matching([_hallazgo(E7_PDF_CORTO)], [_excel(E7_EXCEL)])

        r = resultados[0]
        assert r.estado == EstadoHallazgo.DIFIERE
        assert [d.campo for d in r.diferencias] == [CampoDiferente.DESCRIPCION]
        detalle = r.diferencias[0].detalle or ""
        assert detalle.startswith(
            "Polaridad opuesta: el PDF indica que cumple y el Excel que no cumple"
        )
        assert "0.93" in detalle
        assert r.equivalencias_redaccion == []
        # El emparejamiento no se toca.
        assert r.tipo_match == TipoMatch.UNICIDAD
        assert r.confianza == 1.0
        assert metas == []

    def test_opuesta_bajo_el_umbral_no_va_al_juez(
        self, similitudes: dict[tuple[str, str], float], juez_prohibido: None
    ):
        # Alfa E7 tal cual B0 (0.76): diferencia real, nunca al juez.
        similitudes[(E7_PDF, E7_EXCEL)] = 0.76

        resultados, _ = ejecutar_matching([_hallazgo(E7_PDF)], [_excel(E7_EXCEL)])

        r = resultados[0]
        assert r.estado == EstadoHallazgo.DIFIERE
        assert (r.diferencias[0].detalle or "").startswith("Polaridad opuesta:")
        assert "juez de redacción" not in (r.diferencias[0].detalle or "")

    def test_lado_que_cumple_es_el_excel(
        self, similitudes: dict[tuple[str, str], float], juez_prohibido: None
    ):
        similitudes[(E7_EXCEL, E7_PDF_CORTO)] = 0.93

        resultados, _ = ejecutar_matching([_hallazgo(E7_EXCEL)], [_excel(E7_PDF_CORTO)])

        assert (resultados[0].diferencias[0].detalle or "").startswith(
            "Polaridad opuesta: el Excel indica que cumple y el PDF que no cumple"
        )

    def test_misma_polaridad_sobre_el_umbral_coincide_sin_juez(
        self, similitudes: dict[tuple[str, str], float], juez_prohibido: None
    ):
        similitudes[(SINCRO_PDF, SINCRO_EXCEL)] = 0.90

        resultados, _ = ejecutar_matching([_hallazgo(SINCRO_PDF)], [_excel(SINCRO_EXCEL)])

        r = resultados[0]
        assert r.estado == EstadoHallazgo.COINCIDE
        # Sobre el umbral es una coincidencia normal, no "redacción distinta".
        assert r.equivalencias_redaccion == []

    def test_polaridad_en_la_accion(
        self, similitudes: dict[tuple[str, str], float], juez_prohibido: None
    ):
        accion_pdf = "Se debe dejar constancia de que el equipo cumple."
        accion_excel = "Se debe reajustar el equipo, ya que no cumple."
        similitudes[(accion_pdf, accion_excel)] = 0.90

        resultados, _ = ejecutar_matching(
            [_hallazgo(SINCRO_PDF, accion=accion_pdf)],
            [_excel(SINCRO_PDF, accion=accion_excel)],
        )

        r = resultados[0]
        assert [d.campo for d in r.diferencias] == [CampoDiferente.ACCION_CORRECTIVA]
        assert (r.diferencias[0].detalle or "").startswith("Polaridad opuesta:")

    def test_cumple_con_matiz_no_fuerza_polaridad_y_va_al_juez(
        self, similitudes: dict[tuple[str, str], float], juez: JuezRedaccionFake
    ):
        # "Cumple parcialmente" no es "cumple": contra un "No cumple" no se
        # inventa una polaridad opuesta; lo adjudica el juez con su criterio.
        parcial = "Sincronización horaria externa. Cumple parcialmente."
        similitudes[(parcial, SINCRO_EXCEL)] = 0.70
        juez.decidir = lambda item: False

        resultados, _ = ejecutar_matching([_hallazgo(parcial)], [_excel(SINCRO_EXCEL)])

        detalle = resultados[0].diferencias[0].detalle or ""
        assert len(juez.lotes) == 1
        assert not detalle.startswith("Polaridad opuesta")
        assert "el juez de redacción concluyó que el contenido difiere" in detalle


# M43 (2026-10-27): cambios mínimos que escaparon en pares que copian el PDF
# (sobre el umbral, sin juez), y la acción copiada de Alfa C3 (CB69).
EPSILON_PDF = ("El DUF indica habilitada la función 51N y 50N, sin embargo, el ECAP no "
               "las define habilitadas")
EPSILON_EXCEL = EPSILON_PDF.replace("50N", "67N")
BETA_PDF = ("Se observa que el parámetro “50P2P” se encuentra ajustada en “2,50”, sin "
              "embargo, el ECAP define un valor de “0,8”.")
BETA_EXCEL = BETA_PDF.replace("2,50", "0,50")
ALFA_ACCION_PDF = ("Se debe actualizar ECAP para el paño E5, ya que no se mencionan los "
                       "ajustes de la función 79.")
ALFA_ACCION_EXCEL = ALFA_ACCION_PDF.replace("E5", "C3")


class TestTerminosSustituidos:
    @pytest.mark.parametrize(
        ("texto_pdf", "texto_excel", "esperado"),
        [
            (EPSILON_PDF, EPSILON_EXCEL, (["50N"], ["67N"])),
            (BETA_PDF, BETA_EXCEL, (["2,50"], ["0,50"])),
            ("Las funciones 50, 50G y 50BF.", "Las funciones 50, 51G y 50BF.",
             (["50G"], ["51G"])),
            (ALFA_ACCION_PDF, ALFA_ACCION_EXCEL, (["E5"], ["C3"])),
        ],
    )
    def test_un_termino_cambiado_en_los_dos_lados(
        self, texto_pdf: str, texto_excel: str, esperado: tuple[list[str], list[str]]
    ):
        assert _terminos_sustituidos(texto_pdf, texto_excel) == esperado

    @pytest.mark.parametrize(
        ("texto_pdf", "texto_excel"),
        [
            # Un término de un solo lado no contradice al otro (lo que cayó M28 V1).
            ("No posee sincronización horaria.",
             "No posee sincronización horaria, incumple el artículo 3-24 de la NTSyCS."),
            ("Actualizar el ECAP del paño BT1.", "Actualizar el ECAP del paño BT1 de 13,8 kV."),
            # Mismo valor con otra grafía.
            ("Ajustada en 2,50 s.", "Ajustada en 2.5 s."),
            ("Ajustada en 0,5 s.", "Ajustada en 0,50 s."),
            ("La función 50n.", "La función 50N."),
            # Separadores que parten distinto la misma secuencia (Beta, B0-B2).
            ("Selector S2 1.Manual2.Automático", "Selector S2 1.Manual-2.Automático"),
            ("Actualizar el ECAP del paño BT1-CT1.", "Actualizar el ECAP del paño BT1 y CT1."),
            # Una palabra larga pegada a un dígito no es un código.
            ("Selector Manual2 activo.", "Selector Manual3 activo."),
            ("Sin números.", "Tampoco aquí."),
            ("", "Función 50N."),
        ],
    )
    def test_sin_sustitucion(self, texto_pdf: str, texto_excel: str):
        assert _terminos_sustituidos(texto_pdf, texto_excel) is None


class TestControlCodigos:
    def test_codigo_cambiado_sobre_el_umbral_difiere_sin_juez(
        self, similitudes: dict[tuple[str, str], float], juez_prohibido: None
    ):
        similitudes[(EPSILON_PDF, EPSILON_EXCEL)] = 0.97

        resultados, metas = ejecutar_matching(
            [_hallazgo(EPSILON_PDF)], [_excel(EPSILON_EXCEL)])

        r = resultados[0]
        assert r.estado == EstadoHallazgo.DIFIERE
        assert [d.campo for d in r.diferencias] == [CampoDiferente.DESCRIPCION]
        assert r.diferencias[0].detalle == (
            "Código o número distinto: el PDF dice «50N» y el Excel «67N» (similitud "
            "semántica 0.97; la similitud no distingue un código cambiado)")
        assert r.equivalencias_redaccion == []
        # El emparejamiento no se toca y no hubo llamadas.
        assert (r.tipo_match, r.confianza) == (TipoMatch.UNICIDAD, 1.0)
        assert metas == []

    def test_en_la_accion_y_en_orden_con_la_calificacion(
        self, similitudes: dict[tuple[str, str], float], juez_prohibido: None
    ):
        # Alfa C3 (CB69): el PDF copió «paño E5» y el Excel lo corrigió; la
        # calificación también difiere.
        similitudes[(ALFA_ACCION_PDF, ALFA_ACCION_EXCEL)] = 0.98

        resultados, _ = ejecutar_matching(
            [_hallazgo(SINCRO_PDF, accion=ALFA_ACCION_PDF)],
            [_excel(SINCRO_PDF, accion=ALFA_ACCION_EXCEL,
                    calificacion=Calificacion.RELEVANTE)])

        r = resultados[0]
        assert [d.campo for d in r.diferencias] == [
            CampoDiferente.ACCION_CORRECTIVA, CampoDiferente.CALIFICACION]
        assert (r.diferencias[0].detalle or "").startswith(
            "Código o número distinto: el PDF dice «E5» y el Excel «C3»")

    def test_varios_terminos_se_nombran_todos(
        self, similitudes: dict[tuple[str, str], float], juez_prohibido: None
    ):
        pdf, excel = "Funciones 50G y 51G habilitadas.", "Funciones 67G y 68G habilitadas."
        similitudes[(pdf, excel)] = 0.95

        resultados, _ = ejecutar_matching([_hallazgo(pdf)], [_excel(excel)])

        assert (resultados[0].diferencias[0].detalle or "").startswith(
            "Código o número distinto: el PDF dice «50G», «51G» y el Excel «67G», «68G»")

    def test_un_termino_agregado_coincide(
        self, similitudes: dict[tuple[str, str], float], juez_prohibido: None
    ):
        pdf = "No posee sincronización horaria."
        excel = "No posee sincronización horaria, incumple el artículo 3-24 de la NTSyCS."
        similitudes[(pdf, excel)] = 0.90

        resultados, _ = ejecutar_matching([_hallazgo(pdf)], [_excel(excel)])

        assert resultados[0].estado == EstadoHallazgo.COINCIDE

    def test_bajo_el_umbral_decide_el_juez(
        self, similitudes: dict[tuple[str, str], float], juez: JuezRedaccionFake
    ):
        # Bajo el umbral la sustitución no se marca: el juez ve los dos textos.
        similitudes[(EPSILON_PDF, EPSILON_EXCEL)] = 0.80

        resultados, _ = ejecutar_matching(
            [_hallazgo(EPSILON_PDF)], [_excel(EPSILON_EXCEL)])

        assert len(juez.lotes) == 1
        assert resultados[0].estado == EstadoHallazgo.COINCIDE
        assert [e.campo for e in resultados[0].equivalencias_redaccion] == [
            CampoDiferente.DESCRIPCION]

    def test_la_polaridad_opuesta_sigue_primero(
        self, similitudes: dict[tuple[str, str], float], juez_prohibido: None
    ):
        pdf, excel = "Función 50N: Cumple.", "Función 67N: No cumple."
        similitudes[(pdf, excel)] = 0.93

        resultados, _ = ejecutar_matching([_hallazgo(pdf)], [_excel(excel)])

        assert (resultados[0].diferencias[0].detalle or "").startswith("Polaridad opuesta:")

    def test_apagado_comportamiento_previo_exacto(
        self, similitudes: dict[tuple[str, str], float], juez_prohibido: None,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setattr(settings, "control_codigos", False)
        similitudes[(EPSILON_PDF, EPSILON_EXCEL)] = 0.97

        resultados, metas = ejecutar_matching(
            [_hallazgo(EPSILON_PDF)], [_excel(EPSILON_EXCEL)])

        assert resultados[0].estado == EstadoHallazgo.COINCIDE
        assert resultados[0].diferencias == []
        assert metas == []

    def test_con_el_juez_de_redaccion_apagado_no_corre(
        self, similitudes: dict[tuple[str, str], float], juez_prohibido: None,
        monkeypatch: pytest.MonkeyPatch,
    ):
        # Como la polaridad, vive en 4e: JUEZ_REDACCION=false = comportamiento previo.
        monkeypatch.setattr(settings, "juez_redaccion", False)
        similitudes[(EPSILON_PDF, EPSILON_EXCEL)] = 0.97

        resultados, _ = ejecutar_matching(
            [_hallazgo(EPSILON_PDF)], [_excel(EPSILON_EXCEL)])

        assert resultados[0].estado == EstadoHallazgo.COINCIDE


class TestJuezRedaccion:
    def test_mismo_contenido_coincide_con_equivalencia(
        self, similitudes: dict[tuple[str, str], float], juez: JuezRedaccionFake
    ):
        similitudes[(SINCRO_PDF, SINCRO_EXCEL)] = 0.80

        resultados, metas = ejecutar_matching([_hallazgo(SINCRO_PDF)], [_excel(SINCRO_EXCEL)])

        r = resultados[0]
        assert r.estado == EstadoHallazgo.COINCIDE
        assert r.diferencias == []
        assert len(r.equivalencias_redaccion) == 1
        e = r.equivalencias_redaccion[0]
        assert e.campo == CampoDiferente.DESCRIPCION
        assert (e.valor_pdf, e.valor_excel) == (SINCRO_PDF, SINCRO_EXCEL)
        assert e.similitud == pytest.approx(0.80, abs=1e-4)
        assert e.justificacion == "justificación 1"
        # El emparejamiento y su justificación no se tocan.
        assert r.tipo_match == TipoMatch.UNICIDAD
        assert r.confianza == 1.0
        assert r.justificacion.startswith("Única")

        # Lo que ve el juez: el par completo, sin la similitud (no anclar).
        assert juez.lotes == [[{
            "id": 1, "campo": "descripcion", "pano": "C1", "rele": "COOPER FORM 6",
            "clasificacion": "Ver. Acceso, Registro y Sincr.",
            "texto_pdf": SINCRO_PDF, "texto_excel": SINCRO_EXCEL,
        }]]
        assert juez.kwargs[0]["system_prompt"] == SYSTEM_JUEZ_REDACCION

        # Persistencia: la meta se distingue y trae la traza del lote.
        (meta,) = metas
        assert meta["tipo"] == "juez_redaccion"
        assert meta["tokens_total"] == 50
        assert meta["lote"] == [{
            "id": 1, "campo": "descripcion", "pano": "C1", "rele": "COOPER FORM 6",
            "pagina_pdf": 7, "fila_excel": 12, "similitud": pytest.approx(0.80, abs=1e-4),
        }]

    def test_contenido_distinto_difiere_con_la_conclusion_del_juez(
        self, similitudes: dict[tuple[str, str], float], juez: JuezRedaccionFake
    ):
        similitudes[(SINCRO_PDF, SINCRO_EXCEL)] = 0.80
        juez.decidir = lambda item: False

        resultados, _ = ejecutar_matching([_hallazgo(SINCRO_PDF)], [_excel(SINCRO_EXCEL)])

        r = resultados[0]
        assert r.estado == EstadoHallazgo.DIFIERE
        assert r.equivalencias_redaccion == []
        assert [d.campo for d in r.diferencias] == [CampoDiferente.DESCRIPCION]
        assert r.diferencias[0].detalle == (
            "Similitud semántica 0.80, bajo el umbral de coincidencia 0.85; el juez "
            "de redacción concluyó que el contenido difiere: justificación 1"
        )

    def test_decide_por_campo_y_conserva_el_orden(
        self, similitudes: dict[tuple[str, str], float], juez: JuezRedaccionFake
    ):
        # Descripción: mismo contenido. Acción: difiere. Calificación: difiere.
        accion_pdf = "Se debe instalar un reloj GPS."
        accion_excel = "Se debe actualizar el ECAP en Infotécnica."
        similitudes[(SINCRO_PDF, SINCRO_EXCEL)] = 0.80
        similitudes[(accion_pdf, accion_excel)] = 0.50
        juez.decidir = lambda item: item["campo"] == "descripcion"

        resultados, _ = ejecutar_matching(
            [_hallazgo(SINCRO_PDF, accion=accion_pdf, calificacion=Calificacion.RELEVANTE)],
            [_excel(SINCRO_EXCEL, accion=accion_excel, calificacion=Calificacion.MENOR)],
        )

        r = resultados[0]
        assert r.estado == EstadoHallazgo.DIFIERE
        assert [d.campo for d in r.diferencias] == [
            CampoDiferente.ACCION_CORRECTIVA, CampoDiferente.CALIFICACION,
        ]
        assert [e.campo for e in r.equivalencias_redaccion] == [CampoDiferente.DESCRIPCION]
        # Un solo lote con los dos campos del par.
        assert [it["campo"] for it in juez.lotes[0]] == ["descripcion", "accion_correctiva"]

    def test_orden_con_polaridad_juez_y_calificacion(
        self, similitudes: dict[tuple[str, str], float], juez: JuezRedaccionFake
    ):
        accion_pdf = "Se debe dejar constancia de que el equipo cumple."
        accion_excel = "Se debe reajustar el equipo, ya que no cumple."
        similitudes[(SINCRO_PDF, GAMMA_EXCEL)] = 0.44
        similitudes[(accion_pdf, accion_excel)] = 0.90
        juez.decidir = lambda item: False

        resultados, _ = ejecutar_matching(
            [_hallazgo(SINCRO_PDF, accion=accion_pdf, calificacion=Calificacion.CRITICO)],
            [_excel(GAMMA_EXCEL, accion=accion_excel, calificacion=Calificacion.MENOR)],
        )

        r = resultados[0]
        assert [d.campo for d in r.diferencias] == [
            CampoDiferente.DESCRIPCION, CampoDiferente.ACCION_CORRECTIVA,
            CampoDiferente.CALIFICACION,
        ]
        # Solo la descripción fue al juez: la acción la resolvió la polaridad.
        assert [it["campo"] for it in juez.lotes[0]] == ["descripcion"]

    def test_vacio_ausente_y_sin_embeddings_no_van_al_juez(
        self, similitudes: dict[tuple[str, str], float], juez_prohibido: None,
        monkeypatch: pytest.MonkeyPatch,
    ):
        # Acción vacía en el PDF ("contenido solo en un lado") y descripción
        # sin embeddings: no hay similitud que adjudicar.
        real = etapa4_matching._construir_cache_embeddings

        def _cache_sin_excel(pdf: list[Hallazgo], excel: list[Hallazgo], *args: Any) -> Any:
            cache, usage = real(pdf, excel, *args)
            cache.pop(SINCRO_EXCEL, None)
            return cache, usage

        monkeypatch.setattr(etapa4_matching, "_construir_cache_embeddings", _cache_sin_excel)

        resultados, metas = ejecutar_matching(
            [_hallazgo(SINCRO_PDF, accion="")], [_excel(SINCRO_EXCEL, accion=ACCION)],
        )

        r = resultados[0]
        assert [d.detalle for d in r.diferencias] == [
            "No se pudo comparar automáticamente (sin embeddings); revisar manualmente",
            "Con contenido solo en el Excel (vacío en el PDF)",
        ]
        assert r.equivalencias_redaccion == []
        assert metas == []

    def test_accion_ausente_en_el_excel_no_va_al_juez(
        self, similitudes: dict[tuple[str, str], float], juez_prohibido: None
    ):
        resultados, _ = ejecutar_matching(
            [_hallazgo(SINCRO_PDF)], [_excel(SINCRO_PDF, accion=None, calificacion=None)],
        )
        assert resultados[0].estado == EstadoHallazgo.COINCIDE

    def test_faltantes_y_extras_no_se_tocan(
        self, similitudes: dict[tuple[str, str], float], juez_prohibido: None
    ):
        resultados, _ = ejecutar_matching(
            [_hallazgo(SINCRO_PDF, pano="C1")], [_excel(SINCRO_EXCEL, pano="C2")],
        )
        assert sorted(r.estado.value for r in resultados) == ["extra_en_excel", "falta_en_excel"]
        assert all(r.equivalencias_redaccion == [] for r in resultados)

    @pytest.mark.parametrize(
        ("modelo_juez", "esperado"), [("gpt-juez", "gpt-juez"), ("", "claude-extraccion")],
    )
    def test_usa_el_modelo_del_juez_de_matching(
        self, similitudes: dict[tuple[str, str], float], juez: JuezRedaccionFake,
        monkeypatch: pytest.MonkeyPatch, modelo_juez: str, esperado: str,
    ):
        monkeypatch.setattr(settings, "modelo_juez_matching", modelo_juez)
        monkeypatch.setattr(settings, "modelo_extraccion", "claude-extraccion")
        similitudes[(SINCRO_PDF, SINCRO_EXCEL)] = 0.80

        ejecutar_matching([_hallazgo(SINCRO_PDF)], [_excel(SINCRO_EXCEL)])

        assert juez.kwargs[0]["modelo"] == esperado

    def test_lotes_de_hasta_15_items_con_ids_por_lote(
        self, similitudes: dict[tuple[str, str], float], juez: JuezRedaccionFake
    ):
        n = _MAX_ITEMS_POR_LOTE_REDACCION + 1
        pdf, excel = [], []
        for i in range(n):
            texto_pdf, texto_excel = f"Hallazgo PDF número {i}", f"Hallazgo Excel número {i}"
            similitudes[(texto_pdf, texto_excel)] = 0.70
            pdf.append(_hallazgo(texto_pdf, pano=f"C{i:02d}"))
            excel.append(_excel(texto_excel, pano=f"C{i:02d}"))
        # Pares impares: mismo contenido. Verifica que cada veredicto vuelve
        # a SU par también en el segundo lote (ids reiniciados en 1).
        juez.decidir = lambda item: int(item["texto_pdf"].split()[-1]) % 2 == 1

        resultados, metas = ejecutar_matching(pdf, excel)

        assert [len(lote) for lote in juez.lotes] == [_MAX_ITEMS_POR_LOTE_REDACCION, 1]
        assert [it["id"] for it in juez.lotes[1]] == [1]
        assert [m["tipo"] for m in metas] == ["juez_redaccion", "juez_redaccion"]
        for r in resultados:
            assert r.hallazgo_pdf is not None
            impar = int(r.hallazgo_pdf.descripcion.split()[-1]) % 2 == 1
            if impar:
                assert r.estado == EstadoHallazgo.COINCIDE
                assert r.equivalencias_redaccion[0].valor_pdf == r.hallazgo_pdf.descripcion
            else:
                assert r.estado == EstadoHallazgo.DIFIERE
                assert r.equivalencias_redaccion == []


def _ids(*ids: int) -> Callable[[list[dict[str, Any]]], list[_VeredictoRedaccion]]:
    def _respuesta(items: list[dict[str, Any]]) -> list[_VeredictoRedaccion]:
        return [_VeredictoRedaccion(id=i, justificacion="x", mismo_contenido=True) for i in ids]

    return _respuesta


class TestSalidaInvalidaDelJuez:
    @pytest.mark.parametrize(
        ("respuesta", "mensaje"),
        [
            (_ids(1), r"faltantes \[2\]"),
            (_ids(1, 2, 3), r"sobrantes \[3\]"),
            (_ids(1, 1, 2), r"duplicados \[1\]"),
        ],
    )
    def test_falla_ruidoso_con_la_metadata(
        self, similitudes: dict[tuple[str, str], float], juez: JuezRedaccionFake,
        respuesta: Callable[[list[dict[str, Any]]], list[_VeredictoRedaccion]], mensaje: str,
    ):
        # Dos pares bajo el umbral en un lote: nunca se asume "mismo
        # contenido" para un ítem sin veredicto válido.
        similitudes[(SINCRO_PDF, SINCRO_EXCEL)] = 0.80
        similitudes[(E7_PDF, "Otro texto del Excel")] = 0.60
        juez.respuesta = respuesta

        with pytest.raises(JuezInvalidoError, match=mensaje) as exc_info:
            ejecutar_matching(
                [_hallazgo(SINCRO_PDF, pano="C1"), _hallazgo(E7_PDF, pano="C2")],
                [_excel(SINCRO_EXCEL, pano="C1"), _excel("Otro texto del Excel", pano="C2")],
            )

        assert "juez de redacción" in str(exc_info.value)
        # La respuesta inválida viaja con el error para persistirla (inv. 20).
        assert [m.get("tipo") for m in exc_info.value.llm_metadata] == ["juez_redaccion"]


class TestJuezApagado:
    def test_comportamiento_previo_exacto(
        self, similitudes: dict[tuple[str, str], float], juez_prohibido: None,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setattr(settings, "juez_redaccion", False)
        similitudes[(E7_PDF_CORTO, E7_EXCEL)] = 0.93
        similitudes[(SINCRO_PDF, SINCRO_EXCEL)] = 0.80

        resultados, metas = ejecutar_matching(
            [_hallazgo(E7_PDF_CORTO, pano="E7"), _hallazgo(SINCRO_PDF, pano="C1")],
            [_excel(E7_EXCEL, pano="E7"), _excel(SINCRO_EXCEL, pano="C1")],
        )

        por_pano = {r.pano: r for r in resultados}
        # Sin polaridad: sobre el umbral sigue siendo coincide.
        assert por_pano["E7"].estado == EstadoHallazgo.COINCIDE
        # Sin juez: bajo el umbral, diferencia con el detalle de siempre.
        assert por_pano["C1"].estado == EstadoHallazgo.DIFIERE
        assert por_pano["C1"].diferencias[0].detalle == (
            "Similitud semántica 0.80, bajo el umbral de coincidencia 0.85"
        )
        assert all(r.equivalencias_redaccion == [] for r in resultados)
        assert metas == []


class TestPromptJuezRedaccion:
    def test_items_van_como_json_completo(self):
        items: list[dict[str, str | int]] = [
            {"id": 1, "campo": "descripcion", "pano": "C1", "rele": "COOPER FORM 6",
             "clasificacion": "Verificación ECAP", "texto_pdf": 'Dice "Cumple"\ny más',
             "texto_excel": "“ECAP-068” no adjunto"},
        ]
        prompt = user_juez_redaccion(items)
        inicio, fin = prompt.index("["), prompt.rindex("]") + 1
        assert json.loads(prompt[inicio:fin]) == items

    def test_system_fija_criterios_y_lado_seguro(self):
        assert "mismo_contenido = true SOLO si" in SYSTEM_JUEZ_REDACCION
        assert "Ante la duda, responde false" in SYSTEM_JUEZ_REDACCION
        assert "MISMO id" in SYSTEM_JUEZ_REDACCION

    def test_system_no_da_por_hecho_que_es_el_mismo_hallazgo(self):
        # Para la descripción, "¿es el mismo hallazgo?" es lo que se decide, y
        # la pasada también recibe pares dudosos (semantico_bajo): afirmarlo
        # empujaría al juez hacia "mismo contenido".
        assert "mismo hallazgo)" not in SYSTEM_JUEZ_REDACCION
        assert "YA emparejado" not in SYSTEM_JUEZ_REDACCION
        assert "El emparejamiento puede estar equivocado" in SYSTEM_JUEZ_REDACCION
        assert "NO asumas que ambos textos hablan del mismo hallazgo" in SYSTEM_JUEZ_REDACCION

    def test_ejemplos_no_salen_de_los_informes_reales(self):
        # Con un texto real en el prompt el juez acierta ese ítem por tener la
        # respuesta, y la medición sobre esos informes se infla.
        for texto in (SINCRO_PDF, SINCRO_EXCEL, GAMMA_EXCEL, E7_PDF, E7_EXCEL):
            assert texto not in SYSTEM_JUEZ_REDACCION


class TestEmparejamientoDudoso:
    def test_par_semantico_bajo_no_se_adjudica_como_parafrasis(self, juez_prohibido: None):
        # Calibración B1 (Alfa E7): con un emparejamiento dudoso, "mismo
        # contenido" puede esconder una diferencia real → queda Diferencia.
        a, b = np.array([1.0, 0.0]), np.array([0.8, 0.6])  # coseno 0.80
        dif = Diferencia(campo=CampoDiferente.DESCRIPCION, valor_pdf=SINCRO_PDF,
                         valor_excel=SINCRO_EXCEL, detalle="Similitud semántica 0.80")
        par = MatchResult(
            pano="C1", rele="COOPER FORM 6", estado=EstadoHallazgo.DIFIERE,
            tipo_match=TipoMatch.SEMANTICO_BAJO, confianza=0.6, justificacion="dudoso",
            hallazgo_pdf=_hallazgo(SINCRO_PDF), hallazgo_excel=_excel(SINCRO_EXCEL),
            diferencias=[dif],
        )
        (r,) = etapa4_matching._revisar_redaccion([par], {SINCRO_PDF: a, SINCRO_EXCEL: b}, [])
        assert r.estado == EstadoHallazgo.DIFIERE
        assert r.equivalencias_redaccion == []
        assert r.diferencias == [dif]

    # PD71 V2 (decisión del usuario 2026-10-25): con la asignación global, un par
    # que terminó con una fila que perdió un hallazgo de polaridad opuesta a ella
    # (Alfa E7 en AG1) cuenta como dudoso para 19e(c) aunque sea
    # semantico_alto. ejecutar_matching le deja el motivo en emparejamiento_dudoso
    # (schema 0.9.0) y 4e lo trata como a un semantico_bajo.
    MOTIVO = "Esta fila del Excel indica que no cumple y otro hallazgo…"

    def _par_alto(self, accion_pdf: str, accion_excel: str,
                  cache: dict[str, np.ndarray[Any, np.dtype[np.float64]]],
                  motivo: str | None = None) -> MatchResult:
        """Par semantico_alto con las diferencias que le deja 4c."""
        h_pdf = _hallazgo(SINCRO_PDF, accion=accion_pdf)
        h_excel = _excel(SINCRO_EXCEL, accion=accion_excel)
        return MatchResult(
            pano="E7", rele="SEL 451", estado=EstadoHallazgo.DIFIERE,
            tipo_match=TipoMatch.SEMANTICO_ALTO, confianza=0.8, justificacion="ganado",
            hallazgo_pdf=h_pdf, hallazgo_excel=h_excel,
            diferencias=etapa4_matching._detectar_diferencias(h_pdf, h_excel, cache),
            emparejamiento_dudoso=motivo,
        )

    def _cache(self, accion_pdf: str, accion_excel: str, sim_accion: float
               ) -> dict[str, np.ndarray[Any, np.dtype[np.float64]]]:
        # Descripción 0.80 (bajo el umbral) y acción `sim_accion`.
        return {SINCRO_PDF: np.array([1.0, 0.0, 0.0, 0.0]),
                SINCRO_EXCEL: np.array([0.8, 0.6, 0.0, 0.0]),
                accion_pdf: np.array([0.0, 0.0, 1.0, 0.0]),
                accion_excel: np.array([0.0, 0.0, sim_accion, math.sqrt(1 - sim_accion ** 2)])}

    def test_par_de_fila_disputada_no_va_al_juez(
        self, juez_prohibido: None
    ):
        accion_pdf, accion_excel = "Instalar un reloj GPS.", "Instalar reloj GPS en el equipo."
        cache = self._cache(accion_pdf, accion_excel, 0.90)
        metas: list[dict[str, Any]] = []

        (r,) = etapa4_matching._revisar_redaccion(
            [self._par_alto(accion_pdf, accion_excel, cache, self.MOTIVO)], cache, metas)

        assert r.estado == EstadoHallazgo.DIFIERE
        assert r.equivalencias_redaccion == []
        # Bajo el umbral: la diferencia de 4c, como en un semantico_bajo (el motivo
        # está en el par). Sobre el umbral (acción): como siempre.
        assert [(d.campo, d.detalle) for d in r.diferencias] == [(
            CampoDiferente.DESCRIPCION,
            "Similitud semántica 0.80, bajo el umbral de coincidencia 0.85")]
        # El emparejamiento y su motivo no se tocan, y no hubo llamadas.
        assert (r.tipo_match, r.confianza, r.justificacion, r.emparejamiento_dudoso) == (
            TipoMatch.SEMANTICO_ALTO, 0.8, "ganado", self.MOTIVO)
        assert metas == []

    def test_la_polaridad_opuesta_del_propio_par_sigue_primero(self, juez_prohibido: None):
        accion_pdf = "Se debe dejar constancia de que el equipo cumple."
        accion_excel = "Se debe reajustar el equipo, ya que no cumple."
        cache = self._cache(accion_pdf, accion_excel, 0.60)

        (r,) = etapa4_matching._revisar_redaccion(
            [self._par_alto(accion_pdf, accion_excel, cache, self.MOTIVO)], cache, [])

        detalles = {d.campo: d.detalle or "" for d in r.diferencias}
        assert detalles[CampoDiferente.DESCRIPCION] == (
            "Similitud semántica 0.80, bajo el umbral de coincidencia 0.85")
        assert detalles[CampoDiferente.ACCION_CORRECTIVA].startswith("Polaridad opuesta:")
        assert r.emparejamiento_dudoso == self.MOTIVO

    def test_sin_la_marca_el_mismo_par_va_al_juez(self, juez: JuezRedaccionFake):
        accion = "Instalar un reloj GPS."   # idéntica en los dos lados: no se compara
        cache = self._cache(accion, accion, 1.0)

        (r,) = etapa4_matching._revisar_redaccion([self._par_alto(accion, accion, cache)],
                                                  cache, [])

        assert r.estado == EstadoHallazgo.COINCIDE
        assert [e.campo for e in r.equivalencias_redaccion] == [CampoDiferente.DESCRIPCION]
        assert [it["texto_excel"] for lote in juez.lotes for it in lote] == [SINCRO_EXCEL]
