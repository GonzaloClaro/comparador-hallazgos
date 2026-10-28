"""Tests de la reparación determinística y el reintento de la Etapa 3.

Decisión del usuario (2026-10-17, "Reparar + reintentar"): un paño con
problemas ya no aborta el informe a la primera. Se repara solo lo inequívoco,
se reintenta una vez el paño con retroalimentación y, si persiste, falla
ruidosamente. Casos reales de las rondas B0/B1 con Haiku 5.5.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from comparador import etapa3_extraer_hallazgos as e3
from comparador.catalogo import cargar_hints_empresa
from comparador.etapa3_extraer_hallazgos import (
    CalificacionNoReconocidaError,
    ExtraccionInvalidaError,
    _extraer_hallazgos_pano,
    _HallazgoResponse,
    _ListaHallazgosResponse,
    _reparar_pano_rele,
    _universo_etapa1,
    llamadas_llm_e3,
)
from comparador.schemas import EmpresaAuditora, PanoDescubierto, ReleDescubierto


def _rele(nombre: str, *sub_panos: str) -> ReleDescubierto:
    return ReleDescubierto(nombre=nombre, evidencia_origen="x", sub_panos=list(sub_panos))


def _seccion(nombre: str, *reles: ReleDescubierto) -> PanoDescubierto:
    return PanoDescubierto(nombre=nombre, pagina_inicio=28, pagina_fin=30, reles=list(reles))


# Alfa págs. 28 y 34: listas "Relé X, Serial: …, Paño Y" previas a la tabla.
ALFA_HT1 = _seccion(
    "HT1/CT1", _rele("SEL 351S", "CT1A", "CT1B"), _rele("SEL 311C", "HT1"), _rele("SEL 387"),
)
ALFA_HT3 = _seccion(
    "HT3/ET3", _rele("SEL 351S", "ET3A", "ET3B"), _rele("SEL 311C", "HT3"),
    _rele("SEL 387E", "HT3-ET3"),
)
# Gamma: "Paño BT1", "Paño BT1-CT1", "Paño CT1".
GAMMA = _seccion(
    "BT1-CT1", _rele("INGEPAC EF-ZT", "BT1"), _rele("INGEPAC EF-TD", "BT1-CT1"),
    _rele("INGEPAC EF-MD", "CT1"),
)
# Zeta: SEL 551C en BT1 y en CT1, SEL 387 en "Paños BT1 y CT1".
ZETA = _seccion("BT1/CT1", _rele("SEL 551C", "BT1", "CT1"), _rele("SEL 387", "BT1-CT1"))


class TestReparacionListaDeReles:
    def test_lista_con_comas_se_desdobla_por_rele_y_sus_sub_panos(self):
        # B0 Haiku Gamma: 'INGEPAC EF-ZT, INGEPAC EF-TD, INGEPAC EF-MD' con
        # el paño de la sección. Cada relé va a SUS sub-paños declarados, no a
        # todos los componentes: (CT1, EF-ZT) y (BT1, EF-MD) no existen.
        pares, reparacion = _reparar_pano_rele(
            "BT1-CT1", "INGEPAC EF-ZT, INGEPAC EF-TD, INGEPAC EF-MD", GAMMA
        )
        assert pares == [
            ("BT1", "INGEPAC EF-ZT"),
            ("BT1-CT1", "INGEPAC EF-TD"),
            ("CT1", "INGEPAC EF-MD"),
        ]
        assert reparacion == (
            "relé 'INGEPAC EF-ZT, INGEPAC EF-TD, INGEPAC EF-MD' → 'INGEPAC EF-ZT', "
            "'INGEPAC EF-TD', 'INGEPAC EF-MD' (desdoblado por relé); paño 'BT1-CT1' → "
            "sub-paños de cada relé: 'INGEPAC EF-ZT' → BT1; 'INGEPAC EF-TD' → BT1-CT1; "
            "'INGEPAC EF-MD' → CT1"
        )

    def test_alfa_cada_rele_a_sus_sub_panos(self):
        pares, _ = _reparar_pano_rele("HT1/CT1", "SEL 351S, SEL 311C", ALFA_HT1)
        assert pares == [("CT1A", "SEL 351S"), ("CT1B", "SEL 351S"), ("HT1", "SEL 311C")]

    def test_rele_sin_sub_panos_conserva_el_pano_de_la_seccion(self):
        pares, _ = _reparar_pano_rele("HT1/CT1", "SEL 311C, SEL 387", ALFA_HT1)
        assert pares == [("HT1", "SEL 311C"), ("HT1/CT1", "SEL 387")]

    def test_pano_distinto_de_la_seccion_se_conserva_para_todos(self):
        # El LLM ya eligió el paño: la reparación solo separa los relés.
        pares, reparacion = _reparar_pano_rele("BT1", "INGEPAC EF-ZT, INGEPAC EF-TD", GAMMA)
        assert pares == [("BT1", "INGEPAC EF-ZT"), ("BT1", "INGEPAC EF-TD")]
        assert reparacion is not None and "sub-paños de cada relé" not in reparacion

    @pytest.mark.parametrize("rele", ["SEL 351S; SEL 311C", "SEL 351S y SEL 311C"])
    def test_punto_y_coma_e_y_tambien_separan(self, rele: str):
        pares, _ = _reparar_pano_rele("HT1/CT1", rele, ALFA_HT1)
        assert list(dict.fromkeys(r for _, r in pares)) == ["SEL 351S", "SEL 311C"]

    def test_si_una_parte_no_es_rele_del_pano_no_se_toca(self):
        # SEL 451 existe en el informe pero no en esta sección: no es inequívoco.
        pares, reparacion = _reparar_pano_rele("HT1/CT1", "SEL 351S, SEL 451", ALFA_HT1)
        assert pares == [("HT1/CT1", "SEL 351S, SEL 451")]
        assert reparacion is None

    def test_rele_normal_no_se_repara(self):
        assert _reparar_pano_rele("CT1A", "SEL 351S", ALFA_HT1) == (
            [("CT1A", "SEL 351S")], None
        )


class TestReparacionSubPanoPegado:
    def test_sub_pano_declarado_pasa_al_pano(self):
        # B0 Haiku Alfa: 'SEL 351S (ET3A)' con el paño de la sección.
        pares, reparacion = _reparar_pano_rele("HT3/ET3", "SEL 351S (ET3A)", ALFA_HT3)
        assert pares == [("ET3A", "SEL 351S")]
        assert reparacion == "relé 'SEL 351S (ET3A)' → 'SEL 351S'; paño 'HT3/ET3' → 'ET3A'"

    def test_componente_de_la_seccion_con_prefijo_pano(self):
        # E3 copia el rótulo de la celda 'SEL 551C (Paño CT1)' con un E1 ya
        # limpio. (El E1 sucio de B1 Sonnet Zeta, con ese mismo texto como
        # nombre del relé, lo limpia la Etapa 1: test_etapa1_validacion.)
        pares, _ = _reparar_pano_rele("BT1/CT1", "SEL 551C (Paño CT1)", ZETA)
        assert pares == [("CT1", "SEL 551C")]

    def test_puntuacion_final_del_rotulo_no_impide_la_reparacion(self):
        pares, _ = _reparar_pano_rele("HT3/ET3", "SEL 351S (Paño ET3A.)", ALFA_HT3)
        assert pares == [("ET3A", "SEL 351S")]

    def test_compuesto_de_la_seccion_tambien_cuenta(self):
        pares, _ = _reparar_pano_rele("HT3-ET3", "SEL 351S (ET3B)", ALFA_HT3)
        assert pares == [("ET3B", "SEL 351S")]

    def test_pano_distinto_de_la_seccion_se_conserva(self):
        # El LLM ya eligió otro paño: el paréntesis no lo pisa.
        pares, reparacion = _reparar_pano_rele("HT3", "SEL 351S (ET3A)", ALFA_HT3)
        assert pares == [("HT3", "SEL 351S")]
        assert reparacion == "relé 'SEL 351S (ET3A)' → 'SEL 351S'"

    def test_sub_pano_de_otro_rele_no_pasa_al_pano(self):
        # HT3 es componente de la sección: sí puede pasar; ET3A no es de SEL 311C.
        pares, _ = _reparar_pano_rele("HT3/ET3", "SEL 311C (ET3A)", ALFA_HT3)
        assert pares == [("HT3/ET3", "SEL 311C")]

    def test_parentesis_que_no_es_pano_solo_limpia_el_rele(self):
        pares, _ = _reparar_pano_rele("HT1/CT1", "SEL 387 (diferencial)", ALFA_HT1)
        assert pares == [("HT1/CT1", "SEL 387")]

    def test_base_que_no_es_rele_del_pano_no_se_toca(self):
        pares, reparacion = _reparar_pano_rele("HT1/CT1", "SEL 351R (CT1A)", ALFA_HT1)
        assert pares == [("HT1/CT1", "SEL 351R (CT1A)")]
        assert reparacion is None


# --- Extracción de un paño con LLM falso -------------------------------------


def _h(
    pano: str,
    rele: str,
    calificacion: str | None = "Menor",
    descripcion: str = "Diagrama Unilineal Funcional: Desactualizado",
) -> _HallazgoResponse:
    return _HallazgoResponse.model_validate({
        "pano": pano,
        "rele": rele,
        "clasificacion": "Verificación DUF",
        "descripcion": descripcion,
        "accion_correctiva": "Actualizar el DUF.",
        "calificacion": calificacion,
        "evidencia": {"pagina_pdf": None, "texto_crudo": descripcion},
    })


class _LLMFalso:
    """Devuelve las respuestas en orden y registra cada llamada."""

    def __init__(self, *respuestas: list[_HallazgoResponse]) -> None:
        self.respuestas = [_ListaHallazgosResponse(hallazgos=r) for r in respuestas]
        self.llamadas: list[dict[str, Any]] = []

    def __call__(self, **kw: Any) -> tuple[_ListaHallazgosResponse, dict[str, Any]]:
        self.llamadas.append(kw)
        n = len(self.llamadas)
        return self.respuestas[n - 1], {"tokens_total": 100 * n, "response_raw": {"intento": n}}


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch):
    def _instalar(*respuestas: list[_HallazgoResponse]) -> _LLMFalso:
        falso = _LLMFalso(*respuestas)
        monkeypatch.setattr(e3, "llamar_llm_estructurado", falso)
        monkeypatch.setattr(e3, "_pdf_del_pano_base64", lambda ruta, pano: "b64")
        return falso
    return _instalar


RELIABLE = cargar_hints_empresa(EmpresaAuditora.RELIABLE_ENERGY)
TODAS = [ALFA_HT1, ALFA_HT3, GAMMA, ZETA]


def _extraer(seccion: PanoDescubierto, universo_de: list[PanoDescubierto] | None = None):
    universo = _universo_etapa1(universo_de or [seccion])
    return _extraer_hallazgos_pano(Path("x.pdf"), seccion, RELIABLE, universo)


def _tuplas(hallazgos: list[Any]) -> list[tuple[str, str]]:
    return [(h.pano, h.rele) for h in hallazgos]


class TestSubPanosDeEtapa1EnEtapa3:
    def test_prompt_muestra_los_sub_panos_de_cada_rele(self, llm):
        falso = llm([_h("CT1A", "SEL 351S")])
        _extraer(ALFA_HT1)
        assert (
            "SEL 351S (sub-paños: CT1A, CT1B), SEL 311C (sub-paños: HT1), SEL 387"
            in falso.llamadas[0]["system_prompt"]
        )

    def test_alfa_sale_con_los_sub_panos_del_excel(self, llm):
        llm([
            _h("CT1A", "SEL 351S"),
            _h("CT1B", "SEL 351S"),
            _h("HT1", "SEL 311C"),
            _h("HT1/CT1", "SEL 387"),  # sin sub-paños: el de la sección
        ])
        hallazgos, meta = _extraer(ALFA_HT1)
        assert _tuplas(hallazgos) == [
            ("CT1A", "SEL 351S"), ("CT1B", "SEL 351S"), ("HT1", "SEL 311C"),
            ("HT1", "SEL 387"), ("CT1", "SEL 387"),
        ]
        assert meta["reintento"] is False and meta["reparaciones"] == []

    def test_sub_pano_compuesto_se_desdobla(self, llm):
        llm([_h("HT3-ET3", "SEL 387E")])
        hallazgos, _ = _extraer(ALFA_HT3)
        assert _tuplas(hallazgos) == [("HT3", "SEL 387E"), ("ET3", "SEL 387E")]
        assert all(h.evidencia.es_multi_pano_origen for h in hallazgos)


class TestReparacionEnLaExtraccion:
    def test_lista_de_reles_se_repara_sin_reintento(self, llm):
        falso = llm([_h("BT1", "INGEPAC EF-ZT, INGEPAC EF-TD")])
        hallazgos, meta = _extraer(GAMMA)
        assert len(falso.llamadas) == 1
        assert _tuplas(hallazgos) == [("BT1", "INGEPAC EF-ZT"), ("BT1", "INGEPAC EF-TD")]
        assert meta["reintento"] is False
        assert meta["reparaciones"] == [
            "relé 'INGEPAC EF-ZT, INGEPAC EF-TD' → 'INGEPAC EF-ZT', 'INGEPAC EF-TD' "
            "(desdoblado por relé)"
        ]

    def test_gamma_lista_con_el_pano_de_la_seccion_no_cruza_sub_panos(self, llm):
        # Caso real B0 Haiku Gamma: las tuplas del Excel, sin (CT1, EF-ZT)
        # ni (BT1, EF-MD) — que la validación no detectaría, porque BT1 y CT1
        # son componentes de la sección y valen con cualquier relé.
        falso = llm([_h("BT1-CT1", "INGEPAC EF-ZT, INGEPAC EF-TD, INGEPAC EF-MD")])
        hallazgos, meta = _extraer(GAMMA)
        assert len(falso.llamadas) == 1 and meta["reintento"] is False
        assert _tuplas(hallazgos) == [
            ("BT1", "INGEPAC EF-ZT"),
            ("BT1", "INGEPAC EF-TD"), ("CT1", "INGEPAC EF-TD"),
            ("CT1", "INGEPAC EF-MD"),
        ]
        assert "sub-paños de cada relé" in meta["reparaciones"][0]

    def test_sub_pano_pegado_se_repara_sin_reintento(self, llm):
        falso = llm([_h("HT3/ET3", "SEL 351S (ET3A)")])
        hallazgos, meta = _extraer(ALFA_HT3)
        assert len(falso.llamadas) == 1
        assert _tuplas(hallazgos) == [("ET3A", "SEL 351S")]
        assert len(meta["reparaciones"]) == 1


class TestReintento:
    def test_rele_inventado_reintenta_con_retroalimentacion(self, llm):
        # B0 Haiku Zeta: 'SEL 351R' no está en el PDF.
        falso = llm(
            [_h("BT1", "SEL 351R"), _h("BT1", "SEL 551C")],
            [_h("BT1", "SEL 551C"), _h("CT1", "SEL 551C")],
        )
        hallazgos, meta = _extraer(ZETA)

        assert len(falso.llamadas) == 2
        primera, segunda = falso.llamadas
        assert segunda["system_prompt"] == primera["system_prompt"]
        assert segunda["user_prompt"].startswith(primera["user_prompt"])
        retro = segunda["user_prompt"][len(primera["user_prompt"]):]
        assert "el relé 'SEL 351R' no está en el mapa de la Etapa 1" in retro
        assert "SEL 551C (sub-paños: BT1, CT1), SEL 387 (sub-paños: BT1-CT1)" in retro
        assert "Paños: BT1, CT1, BT1-CT1." in retro
        assert "lista COMPLETA" in retro

        # La respuesta del reintento reemplaza a la primera (no se fusionan).
        assert _tuplas(hallazgos) == [("BT1", "SEL 551C"), ("CT1", "SEL 551C")]
        assert meta["reintento"] is True
        assert meta["problemas_primer_intento"] == [
            "el relé 'SEL 351R' no está en el mapa de la Etapa 1"
        ]
        assert meta["response_raw"] == {"intento": 2}
        assert meta["intentos_previos"][0]["response_raw"] == {"intento": 1}
        assert meta["intentos_previos"][0]["problemas"] == meta["problemas_primer_intento"]
        assert meta["hallazgos_por_intento"] == [
            {"total": 2, "validos": 1}, {"total": 2, "validos": 2},
        ]
        assert "advertencia_reintento" not in meta

    def test_calificacion_omitida_reintenta(self, llm):
        # B1 Haiku Alfa: calificación null con un formato que la trae.
        falso = llm([_h("CT1A", "SEL 351S", calificacion=None)], [_h("CT1A", "SEL 351S")])
        hallazgos, meta = _extraer(ALFA_HT1)
        assert len(falso.llamadas) == 2
        assert "no trae calificación" in meta["problemas_primer_intento"][0]
        assert hallazgos[0].calificacion is not None

    def test_lista_no_reparable_va_al_reintento(self, llm):
        falso = llm([_h("CT1A", "SEL 351S, SEL 451")], [_h("CT1A", "SEL 351S")])
        _extraer(ALFA_HT1, universo_de=TODAS)
        assert len(falso.llamadas) == 2

    def test_sub_pano_con_rele_ajeno_va_al_reintento(self, llm):
        falso = llm([_h("CT1A", "SEL 311C")], [_h("HT1", "SEL 311C")])
        _, meta = _extraer(ALFA_HT1)
        assert len(falso.llamadas) == 2
        assert "sub-paño de otro relé" in meta["problemas_primer_intento"][0]

    # B1 Haiku Zeta: E1 nombró la sección "BT1/ET1" (su evidencia dice
    # "Paños BT1 – CT1") y E3 leyó bien "CT1" del PDF. El error es de E1.
    ZETA_E1_HAIKU = _seccion("BT1/ET1", _rele("SEL 551C"), _rele("SEL 387"))

    def test_retroalimentacion_no_obliga_a_reasignar_lo_que_el_pdf_atribuye(self, llm):
        falso = llm([_h("CT1", "SEL 551C")], [_h("CT1", "SEL 551C")])
        with pytest.raises(ExtraccionInvalidaError) as exc_info:
            _extraer(self.ZETA_E1_HAIKU)

        retro = falso.llamadas[1]["user_prompt"][len(falso.llamadas[0]["user_prompt"]):]
        assert "el paño 'CT1' no está en el mapa de la Etapa 1" in retro
        assert "devuélvelo tal cual" in retro and "NO lo reasignes" in retro
        # El modelo sostiene lo que dice el PDF: el error de E1 sigue visible.
        assert "paño 'CT1'" in str(exc_info.value)

    def test_reasignacion_entre_intentos_queda_registrada(self, llm):
        # Si el reintento igual mueve el hallazgo de paño, no pasa en silencio.
        llm(
            [_h("CT1", "SEL 551C", descripcion="ECAP del 551C de CT1")],
            [_h("BT1", "SEL 551C", descripcion="ECAP del 551C de CT1")],
        )
        hallazgos, meta = _extraer(self.ZETA_E1_HAIKU)
        assert _tuplas(hallazgos) == [("BT1", "SEL 551C")]
        assert meta["cambios_en_reintento"] == [
            "'ECAP del 551C de CT1...': pasó de (CT1, SEL 551C) a (BT1, SEL 551C)"
        ]

    def test_reintento_que_pierde_hallazgos_validos_advierte(self, llm):
        # El primer intento trae 3 válidos y un relé inventado; el reintento
        # devuelve 1: los 2 válidos perdidos quedan señalados en la metadata.
        llm(
            [
                _h("BT1", "SEL 551C", descripcion="DUF"),
                _h("CT1", "SEL 551C", descripcion="ECAP"),
                _h("BT1-CT1", "SEL 387", descripcion="Tiempos"),
                _h("BT1", "SEL 351R", descripcion="Inventado"),
            ],
            [_h("BT1", "SEL 551C", descripcion="DUF")],
        )
        hallazgos, meta = _extraer(ZETA)
        assert _tuplas(hallazgos) == [("BT1", "SEL 551C")]
        assert meta["hallazgos_por_intento"] == [
            {"total": 5, "validos": 4}, {"total": 1, "validos": 1},
        ]
        assert meta["advertencia_reintento"] == (
            "el reintento trajo 1 hallazgos válidos, menos que los 4 válidos del "
            "primer intento: revisar extraer_BT1_CT1_intento1.json"
        )
        assert meta["cambios_en_reintento"] == [
            "'ECAP...' (CT1, SEL 551C): no volvió en el reintento",
            "'Tiempos...' (BT1, SEL 387), (CT1, SEL 387): no volvió en el reintento",
            "'Inventado...' (BT1, SEL 351R): no volvió en el reintento",
        ]

    def test_reintento_fallido_falla_ruidosamente(self, llm):
        falso = llm([_h("C9", "SIEMENS 7SJ82")], [_h("C9", "SIEMENS 7SJ82")])
        with pytest.raises(ExtraccionInvalidaError) as exc_info:
            _extraer(ALFA_HT1)

        assert len(falso.llamadas) == 2  # un solo reintento
        mensaje = str(exc_info.value)
        assert "paño 'HT1/CT1'" in mensaje and "reintentar una vez" in mensaje
        assert "paño 'C9'" in mensaje and "relé 'SIEMENS 7SJ82'" in mensaje
        # La metadata viaja en la excepción para que el pipeline la persista.
        (meta,) = exc_info.value.llm_metadata
        assert meta["reintento"] is True and len(meta["problemas"]) == 2
        assert meta["intentos_previos"][0]["response_raw"] == {"intento": 1}

    def test_calificacion_fuera_del_enum_falla_sin_reintento(self, llm):
        # Invariante 3: un valor nuevo lo evalúa el usuario, no un reintento.
        falso = llm([_h("CT1A", "SEL 351S", calificacion="Gravísimo")])
        with pytest.raises(ValueError, match="Gravísimo") as exc_info:
            _extraer(ALFA_HT1)
        assert len(falso.llamadas) == 1
        # La respuesta ya pagada viaja en la excepción para persistirla.
        assert isinstance(exc_info.value, CalificacionNoReconocidaError)
        (meta,) = exc_info.value.llm_metadata
        assert meta["response_raw"] == {"intento": 1} and "reintento" not in meta

    def test_calificacion_fuera_del_enum_en_el_reintento_conserva_ambos_intentos(self, llm):
        # "Criticidad relevante" es el valor literal de la columna de Reliable
        # Energy: si el reintento lo devuelve sin mapear, los dos raw pagados
        # se persisten igual (invariante 20).
        falso = llm(
            [_h("CT1A", "SEL 351R")],
            [_h("CT1A", "SEL 351S", calificacion="Criticidad relevante")],
        )
        with pytest.raises(ValueError, match="Criticidad relevante") as exc_info:
            _extraer(ALFA_HT1)
        assert len(falso.llamadas) == 2
        assert isinstance(exc_info.value, CalificacionNoReconocidaError)
        llamadas = llamadas_llm_e3(exc_info.value.llm_metadata)
        assert [n for n, _ in llamadas] == ["extraer_HT1_CT1_intento1", "extraer_HT1_CT1"]
        assert [m["response_raw"] for _, m in llamadas] == [{"intento": 1}, {"intento": 2}]
        assert llamadas[1][1]["reintento"] is True

    def test_error_del_cliente_en_el_reintento_conserva_el_primer_intento(
        self, llm, monkeypatch: pytest.MonkeyPatch
    ):
        falso = llm([_h("CT1A", "SEL 351R")])  # no hay segunda respuesta

        def _llm(**kw: Any) -> Any:
            if falso.llamadas:
                raise RuntimeError("El modelo rechazó la solicitud (refusal).")
            return falso(**kw)

        monkeypatch.setattr(e3, "llamar_llm_estructurado", _llm)
        with pytest.raises(ExtraccionInvalidaError, match="no pudo completar") as exc_info:
            _extraer(ALFA_HT1)
        assert isinstance(exc_info.value.__cause__, RuntimeError)
        llamadas = llamadas_llm_e3(exc_info.value.llm_metadata)
        assert [n for n, _ in llamadas] == ["extraer_HT1_CT1_intento1", "extraer_HT1_CT1"]
        assert llamadas[0][1]["response_raw"] == {"intento": 1}
        assert "refusal" in llamadas[1][1]["error"]
        # Formato común de llamada fallida: con modelo, para que metricas_lote la cuente.
        assert llamadas[1][1]["llamada_fallida"] is True and llamadas[1][1]["modelo"]

    def test_llamada_fallida_del_cliente_en_el_reintento_conserva_sus_tokens(
        self, llm, monkeypatch: pytest.MonkeyPatch
    ):
        from comparador.llm.client import LlamadaFallidaError

        falso = llm([_h("CT1A", "SEL 351R")])

        def _llm(**kw: Any) -> Any:
            if falso.llamadas:
                raise LlamadaFallidaError("JSON que no valida", {
                    "modelo": "claude-x", "llamada_fallida": True, "error": "JSON que no valida",
                    "tokens_prompt": 50, "tokens_completion": 7,
                })
            return falso(**kw)

        monkeypatch.setattr(e3, "llamar_llm_estructurado", _llm)
        with pytest.raises(ExtraccionInvalidaError, match="no pudo completar") as exc_info:
            _extraer(ALFA_HT1)
        (_, definitiva) = llamadas_llm_e3(exc_info.value.llm_metadata)[1]
        assert (definitiva["modelo"], definitiva["tokens_prompt"]) == ("claude-x", 50)
        assert definitiva["reintento"] is True


class TestLlamadasLLMDeEtapa3:
    def test_sin_reintento_una_llamada(self):
        meta = {"pano": "HT1/CT1", "tokens_total": 100, "reintento": False}
        assert llamadas_llm_e3([meta]) == [("extraer_HT1_CT1", meta)]

    def test_con_reintento_dos_llamadas_y_raw_separados(self):
        previo = {"pano": "C1", "tokens_total": 100}
        meta = {"pano": "C1", "tokens_total": 200, "reintento": True,
                "intentos_previos": [previo]}
        llamadas = llamadas_llm_e3([meta])
        assert [n for n, _ in llamadas] == ["extraer_C1_intento1", "extraer_C1"]
        assert "intentos_previos" not in llamadas[1][1]
        assert sum(m["tokens_total"] for _, m in llamadas) == 300


# --- Persistencia en el pipeline ----------------------------------------------


@pytest.fixture
def pipeline_falso(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Pipeline con todas las etapas reemplazadas salvo la persistencia de E3."""
    from comparador import pipeline
    from comparador.schemas import ChecklistInforme, MetadatosInforme

    monkeypatch.setattr(pipeline, "_validar_credenciales", lambda: None)
    monkeypatch.setattr(pipeline, "probar_clave_openai", lambda calcular: {"ok": True})
    monkeypatch.setattr(pipeline, "guardar_hash_input", lambda *a: None)
    monkeypatch.setattr(
        pipeline, "verificar_checklist",
        lambda ruta, *a: (ChecklistInforme(items=[], cumplen=0, total=0), {"tokens_total": 1}),
    )
    monkeypatch.setattr(pipeline, "descubrir_panos", lambda ruta: ([ALFA_HT1], {}))
    monkeypatch.setattr(
        pipeline, "normalizar_excel",
        lambda ruta, patrones: ([], MetadatosInforme(coordinado="c", subestacion="s",
                                                     informe_id="i")),
    )
    monkeypatch.setattr(pipeline, "ejecutar_matching", lambda pdf, excel, **_: ([], []))

    def _correr(extraer: Any) -> Path:
        monkeypatch.setattr(pipeline, "extraer_hallazgos_pdf", extraer)
        run_dir = tmp_path / "run"
        (run_dir / "etapa3_raw").mkdir(parents=True)
        asyncio.run(pipeline.ejecutar_pipeline(
            Path("x.pdf"), Path("x.xlsx"), EmpresaAuditora.RELIABLE_ENERGY, run_dir=run_dir,
        ))
        return run_dir

    return _correr, tmp_path / "run"


META_REINTENTADA = {
    "pano": "HT1/CT1", "tokens_total": 200, "reintento": True,
    "problemas_primer_intento": ["el relé 'SEL 351R' no está en el mapa de la Etapa 1"],
    "intentos_previos": [{"pano": "HT1/CT1", "tokens_total": 100}],
}


class TestPersistenciaE3:
    def test_reintento_exitoso_persiste_ambos_raw_y_suma_tokens(self, pipeline_falso):
        correr, _ = pipeline_falso

        async def _extraer(ruta, panos, empresa, *a):
            return [], [META_REINTENTADA]

        run_dir = correr(_extraer)
        raw = run_dir / "etapa3_raw"
        assert sorted(p.name for p in raw.iterdir()) == [
            "extraer_HT1_CT1.json", "extraer_HT1_CT1_intento1.json",
        ]
        definitiva = json.loads((raw / "extraer_HT1_CT1.json").read_text(encoding="utf-8"))
        assert definitiva["reintento"] is True and "intentos_previos" not in definitiva
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        assert metadata["tokens_e3"] == 300

    def test_reintento_fallido_persiste_ambos_raw_antes_de_propagar(self, pipeline_falso):
        correr, run_dir = pipeline_falso

        async def _extraer(ruta, panos, empresa, *a):
            raise ExtraccionInvalidaError("inválido", llm_metadata=[META_REINTENTADA])

        with pytest.raises(ExtraccionInvalidaError):
            correr(_extraer)
        assert sorted(p.name for p in (run_dir / "etapa3_raw").iterdir()) == [
            "extraer_HT1_CT1.json", "extraer_HT1_CT1_intento1.json",
        ]

    def test_calificacion_fuera_del_enum_tambien_persiste_los_raw(self, pipeline_falso):
        # Sigue siendo ValueError (invariante 3) y el pipeline guarda los raw.
        correr, run_dir = pipeline_falso

        async def _extraer(ruta, panos, empresa, *a):
            raise CalificacionNoReconocidaError("Gravísimo", llm_metadata=[META_REINTENTADA])

        with pytest.raises(ValueError, match="Gravísimo"):
            correr(_extraer)
        assert sorted(p.name for p in (run_dir / "etapa3_raw").iterdir()) == [
            "extraer_HT1_CT1.json", "extraer_HT1_CT1_intento1.json",
        ]


class TestFallaDeUnPanoConservaLosDemas:
    """Si un paño falla, las respuestas ya pagadas de los otros paños viajan en
    el error para que el pipeline las persista (invariante 20)."""

    def _correr(self, monkeypatch: pytest.MonkeyPatch, error: Exception) -> BaseException:
        def falso(ruta: Path, pano: PanoDescubierto, *a: Any) -> tuple[list[Any], dict[str, Any]]:
            if pano.nombre == "C2":
                raise error
            return [], {"pano": pano.nombre, "tokens_total": 10}

        monkeypatch.setattr(e3, "_extraer_hallazgos_pano", falso)
        panos = [_seccion("C1", _rele("SEL 351R")), _seccion("C2", _rele("SEL 351R"))]
        with pytest.raises(ExtraccionInvalidaError) as info:
            asyncio.run(e3.extraer_hallazgos_pdf(
                Path("x.pdf"), panos, EmpresaAuditora.RELIABLE_ENERGY,
            ))
        return info.value

    def test_error_de_validacion_lleva_los_paños_exitosos(self, monkeypatch: pytest.MonkeyPatch):
        propio = {"pano": "C2", "tokens_total": 5}
        exc = self._correr(monkeypatch, ExtraccionInvalidaError("relé 'X'", [propio]))
        assert isinstance(exc, ExtraccionInvalidaError)
        assert [m["pano"] for m in exc.llm_metadata] == ["C2", "C1"]

    def test_error_del_cliente_se_envuelve_con_los_paños_exitosos(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        exc = self._correr(monkeypatch, RuntimeError("refusal"))
        assert "RuntimeError: refusal" in str(exc)
        assert isinstance(exc.__cause__, RuntimeError)
        assert [m["pano"] for m in exc.llm_metadata] == ["C1"]
