"""Tests de la validación de salida de la Etapa 1 (defensa del universo)."""

import pytest

from comparador.etapa1_descubrir_panos import (
    DescubrimientoInvalidoError,
    _PanoResponse,
    _validar_panos,
)


def _pano(inicio: int, fin: int, nombre: str = "C1") -> _PanoResponse:
    return _PanoResponse(nombre=nombre, pagina_inicio=inicio, pagina_fin=fin, reles=[])


class TestValidarPanos:
    def test_lista_vacia_falla_ruidosamente(self):
        with pytest.raises(DescubrimientoInvalidoError, match="ningún paño"):
            _validar_panos([], total_paginas=80)

    def test_rango_valido_pasa(self):
        _validar_panos([_pano(6, 7)], total_paginas=80)

    def test_inicio_mayor_que_fin_falla(self):
        with pytest.raises(DescubrimientoInvalidoError, match="rango de páginas"):
            _validar_panos([_pano(9, 6)], total_paginas=80)

    def test_pagina_cero_falla(self):
        with pytest.raises(DescubrimientoInvalidoError, match="rango de páginas"):
            _validar_panos([_pano(0, 3)], total_paginas=80)

    def test_fin_fuera_del_documento_falla(self):
        with pytest.raises(DescubrimientoInvalidoError, match="80 páginas"):
            _validar_panos([_pano(78, 81)], total_paginas=80)


class TestDescubrirPorTramo:
    """Informe que no cabe en contexto: E1 lee solo el primer tramo."""

    def _correr(self, monkeypatch, tmp_path, pano_fin: int):
        from typing import Any

        from comparador import etapa1_descubrir_panos as e1
        from comparador.troceo import Tramo

        monkeypatch.setattr(
            e1, "planificar_tramos",
            lambda ruta, **kw: [Tramo(1, 228, 456, "t1", 580_000),
                                Tramo(229, 456, 456, "t2", 460_000)],
        )
        llamadas: list[dict[str, Any]] = []

        def _llm(**kw: Any):
            llamadas.append(kw)
            resp = e1._ListaPanosResponse(panos=[e1._PanoResponse(
                nombre="E1", pagina_inicio=10, pagina_fin=pano_fin,
                reles=[e1._ReleResponse(nombre="SEL 651R", evidencia_origen="x")],
            )])
            return resp, {"tokens_total": 5}

        monkeypatch.setattr(e1, "llamar_llm_estructurado", _llm)
        panos, meta = e1.descubrir_panos(tmp_path / "x.pdf")
        return panos, meta, llamadas

    def test_usa_solo_el_primer_tramo(self, monkeypatch, tmp_path):
        panos, meta, llamadas = self._correr(monkeypatch, tmp_path, pano_fin=29)
        assert len(llamadas) == 1 and llamadas[0]["pdf_base64"] == "t1"
        assert "páginas 1 a 228 de un informe de 456" in llamadas[0]["user_prompt"]
        assert meta["troceo"]["paginas_leidas"] == [1, 228]
        assert "advertencia" not in meta["troceo"]
        assert panos[0].pagina_fin == 29

    def test_pano_en_el_borde_del_tramo_se_advierte(self, monkeypatch, tmp_path):
        _, meta, _ = self._correr(monkeypatch, tmp_path, pano_fin=228)
        assert "podría continuar" in meta["troceo"]["advertencia"]


class TestSubPanos:
    """Decisión 1 (2026-10-17): E1 lee los sub-paños de la lista "Relé X,
    Serial: …, Paño Y" previa a las tablas de transformador (Alfa pág. 28:
    SEL 351S en CT1A/CT1B, SEL 311C en HT1, SEL 387E en "Paños HT2-ET2")."""

    @pytest.mark.parametrize("sub_pano", ["CT1A", "HT1", "HT2-ET2", "BT1-CT1", "ET3B"])
    def test_codigos_de_pano_validos(self, sub_pano: str):
        from comparador.etapa1_descubrir_panos import _es_sub_pano_valido

        assert _es_sub_pano_valido(sub_pano)

    @pytest.mark.parametrize("sub_pano", ["BT1 y CT1", "Paño CT1A", "1000000001", "HT1/CT1"])
    def test_lo_que_no_es_codigo_no_es_valido(self, sub_pano: str):
        from comparador.etapa1_descubrir_panos import _es_sub_pano_valido

        assert not _es_sub_pano_valido(sub_pano)

    def _correr(self, monkeypatch, tmp_path, reles):
        from typing import Any

        from comparador import etapa1_descubrir_panos as e1
        from comparador.troceo import Tramo

        monkeypatch.setattr(
            e1, "planificar_tramos", lambda ruta, **kw: [Tramo(1, 314, 314, "t1", 600_000)],
        )

        def _llm(**kw: Any):
            resp = e1._ListaPanosResponse(panos=[e1._PanoResponse(
                nombre="HT1/CT1", pagina_inicio=28, pagina_fin=30, reles=reles,
            )])
            return resp, {"tokens_total": 5}

        monkeypatch.setattr(e1, "llamar_llm_estructurado", _llm)
        return e1.descubrir_panos(tmp_path / "x.pdf")

    def test_sub_panos_pasan_a_rele_descubierto(self, monkeypatch, tmp_path):
        from comparador.etapa1_descubrir_panos import _ReleResponse

        panos, meta = self._correr(monkeypatch, tmp_path, [
            _ReleResponse(nombre="SEL 351S", evidencia_origen="x", sub_panos=["CT1A", " CT1B "]),
            _ReleResponse(nombre="SEL 311C", evidencia_origen="x", sub_panos=["HT1"]),
            _ReleResponse(nombre="SEL 387", evidencia_origen="x"),  # sin lista → []
        ])
        assert [(r.nombre, r.sub_panos) for r in panos[0].reles] == [
            ("SEL 351S", ["CT1A", "CT1B"]), ("SEL 311C", ["HT1"]), ("SEL 387", []),
        ]
        assert "sub_panos_descartados" not in meta

    def test_sub_pano_invalido_se_descarta_y_queda_en_metadata(self, monkeypatch, tmp_path):
        from comparador.etapa1_descubrir_panos import _ReleResponse

        panos, meta = self._correr(monkeypatch, tmp_path, [
            _ReleResponse(nombre="SEL 387", evidencia_origen="x",
                          sub_panos=["Serial 1000000001", "BT1-CT1"]),
        ])
        assert panos[0].reles[0].sub_panos == ["BT1-CT1"]
        assert meta["sub_panos_descartados"] == [
            "paño 'HT1/CT1', relé 'SEL 387': sub-paño 'Serial 1000000001' no es un "
            "código de paño"
        ]

    def test_grafias_inequivocas_de_la_lista_se_normalizan(self, monkeypatch, tmp_path):
        # Alfa pág. 28 (pypdf): "• Relé SEL 351S, Serial: 1000000001, - Paño
        # CT1A." Copiado literal, el ítem trae prefijo y punto final; descartarlo
        # devolvería al relé el paño de la sección (el bug original).
        from comparador.etapa1_descubrir_panos import _ReleResponse

        panos, meta = self._correr(monkeypatch, tmp_path, [
            _ReleResponse(nombre="SEL 351S", evidencia_origen="x",
                          sub_panos=["Paño CT1A.", "CT1B.", "CT1A"]),
            _ReleResponse(nombre="SEL 311C", evidencia_origen="x", sub_panos=["Paños HT1"]),
            _ReleResponse(nombre="SEL 387E", evidencia_origen="x", sub_panos=["HT2/ET2"]),
            _ReleResponse(nombre="SEL 387", evidencia_origen="x", sub_panos=["Paños BT1 y CT1"]),
        ])
        assert [(r.nombre, r.sub_panos) for r in panos[0].reles] == [
            ("SEL 351S", ["CT1A", "CT1B"]),  # sin repetir
            ("SEL 311C", ["HT1"]),
            ("SEL 387E", ["HT2-ET2"]),
            ("SEL 387", ["BT1-CT1"]),
        ]
        assert "sub_panos_descartados" not in meta
        assert "paño 'HT1/CT1', relé 'SEL 351S': sub-paño 'Paño CT1A.' → 'CT1A'" in (
            meta["reparaciones"]
        )

    def test_codigo_sin_digito_vale_si_es_componente_de_una_seccion(self):
        # Añañuca pág. 17: "Paño CT –" y la sección "CT" (el Excel usa "CT").
        from comparador.etapa1_descubrir_panos import (
            _filtrar_sub_panos,
            _PanoResponse,
            _ReleResponse,
        )

        panos = [
            _PanoResponse(nombre="CT", pagina_inicio=17, pagina_fin=17, reles=[
                _ReleResponse(nombre="NOJA POWER RC-01ES", evidencia_origen="x",
                              sub_panos=["Paño CT –", "XX"]),
            ]),
        ]
        descartados, _ = _filtrar_sub_panos(panos)
        assert panos[0].reles[0].sub_panos == ["CT"]
        assert descartados == [
            "paño 'CT', relé 'NOJA POWER RC-01ES': sub-paño 'XX' no es un código de paño"
        ]

    def test_nombre_de_rele_con_el_pano_pegado_se_limpia_y_fusiona(self, monkeypatch, tmp_path):
        # Salida real de B1 Sonnet Zeta: el paño pegado al nombre del relé.
        # Sin limpiar, la tupla nunca calza con el "SEL 551C" del Excel y la
        # reparación de la Etapa 3 no la reconoce (su BASE no es relé de E1).
        from comparador.etapa1_descubrir_panos import _ReleResponse

        panos, meta = self._correr(monkeypatch, tmp_path, [
            _ReleResponse(nombre="SEL 551C (Paño BT1)", evidencia_origen="Paño BT1"),
            _ReleResponse(nombre="SEL 387", evidencia_origen="x", sub_panos=["BT1-CT1"]),
            _ReleResponse(nombre="SEL 551C (Paño CT1)", evidencia_origen="Paño CT1"),
        ])
        assert [(r.nombre, r.sub_panos) for r in panos[0].reles] == [
            ("SEL 551C", ["BT1", "CT1"]), ("SEL 387", ["BT1-CT1"]),
        ]
        assert panos[0].reles[0].evidencia_origen == "Paño BT1 | Paño CT1"
        assert meta["reparaciones"] == [
            "paño 'HT1/CT1': relé 'SEL 551C (Paño BT1)' → 'SEL 551C' con sub-paño 'BT1'",
            "paño 'HT1/CT1': relé 'SEL 551C (Paño CT1)' → 'SEL 551C' con sub-paño 'CT1'",
            "paño 'HT1/CT1': relé 'SEL 551C' repetido, fusionado en uno solo",
        ]

    @pytest.mark.parametrize("nombre", ["GE Multilin (F650)", "SEL 387 (diferencial)"])
    def test_parentesis_que_no_es_inequivocamente_un_pano_no_se_toca(
        self, monkeypatch, tmp_path, nombre: str
    ):
        # "F650" tiene forma de código pero es un modelo: sin "Paño" delante ni
        # ser componente de la sección, no es inequívoco.
        from comparador.etapa1_descubrir_panos import _ReleResponse

        panos, meta = self._correr(monkeypatch, tmp_path, [
            _ReleResponse(nombre=nombre, evidencia_origen="x"),
        ])
        assert [(r.nombre, r.sub_panos) for r in panos[0].reles] == [(nombre, [])]
        assert "reparaciones" not in meta

    def test_componente_de_la_seccion_entre_parentesis_tambien_se_limpia(
        self, monkeypatch, tmp_path
    ):
        from comparador.etapa1_descubrir_panos import _ReleResponse

        panos, _ = self._correr(monkeypatch, tmp_path, [
            _ReleResponse(nombre="SEL 311C (HT1)", evidencia_origen="x"),
        ])
        assert [(r.nombre, r.sub_panos) for r in panos[0].reles] == [("SEL 311C", ["HT1"])]

    def test_modelo_repetido_en_el_pano_se_fusiona(self, monkeypatch, tmp_path):
        # B1 Haiku Alfa devolvió "SEL 351S" dos veces en HT1/CT1.
        from comparador.etapa1_descubrir_panos import _ReleResponse

        panos, meta = self._correr(monkeypatch, tmp_path, [
            _ReleResponse(nombre="SEL 351S", evidencia_origen="x", sub_panos=["CT1A"]),
            _ReleResponse(nombre="SEL 351S", evidencia_origen="x", sub_panos=["CT1B"]),
            _ReleResponse(nombre="SEL 311C", evidencia_origen="x", sub_panos=["HT1"]),
        ])
        assert [(r.nombre, r.sub_panos) for r in panos[0].reles] == [
            ("SEL 351S", ["CT1A", "CT1B"]), ("SEL 311C", ["HT1"]),
        ]
        assert panos[0].reles[0].evidencia_origen == "x"
        assert meta["reparaciones"] == [
            "paño 'HT1/CT1': relé 'SEL 351S' repetido, fusionado en uno solo"
        ]

    def test_schema_de_structured_outputs_no_exige_sub_panos(self):
        # Opcional para Anthropic (sin "default" en el schema: OpenAI strict
        # lo vuelve requerido por su cuenta) y con descripción para el modelo.
        from comparador.etapa1_descubrir_panos import _ReleResponse

        schema = _ReleResponse.model_json_schema()
        assert "sub_panos" not in schema["required"]
        assert "default" not in schema["properties"]["sub_panos"]
        assert "LITERALES" in schema["properties"]["sub_panos"]["description"]
