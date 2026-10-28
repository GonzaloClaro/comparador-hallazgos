"""Tests de las partes puras (sin LLM) de la Etapa 3."""

import pytest

from comparador.etapa3_extraer_hallazgos import (
    _problemas_pano_rele,
    _split_pano_compuesto,
    _universo_etapa1,
)
from comparador.schemas import PanoDescubierto, ReleDescubierto


def _seccion(nombre: str, *reles: ReleDescubierto) -> PanoDescubierto:
    return PanoDescubierto(nombre=nombre, pagina_inicio=1, pagina_fin=2, reles=list(reles))


def _rele(nombre: str, *sub_panos: str) -> ReleDescubierto:
    return ReleDescubierto(nombre=nombre, evidencia_origen="x", sub_panos=list(sub_panos))


UNIVERSO = _universo_etapa1([
    _seccion("BT1/ET1", _rele("ABB RET670")),
    _seccion("E1", _rele("SEL 351S")),
    _seccion("E2", _rele("SEL 351S")),
])


class TestValidacionContraEtapa1:
    def test_pano_y_rele_validos_pasan(self):
        assert _problemas_pano_rele("BT1", "ABB RET670", UNIVERSO) == []

    def test_tolera_mayusculas_y_espacios(self):
        assert _problemas_pano_rele("bt1", "abb  ret670", UNIVERSO) == []

    def test_tolera_guion_en_vez_de_espacio(self):
        # Caso real Eta (Haiku 5.5): E1 "GE-12IAC53A5A", E3 "GE 12IAC53A5A".
        assert _problemas_pano_rele("BT1", "ABB-RET670", UNIVERSO) == []
        assert _problemas_pano_rele("BT1", "SEL-351S", UNIVERSO) == []

    def test_grafia_distinta_es_problema(self):
        # Quitar separadores no es fusionar grafías (invariante 19c).
        assert _problemas_pano_rele("BT1", "SEL 351R", UNIVERSO) == [
            "el relé 'SEL 351R' no está en el mapa de la Etapa 1"
        ]

    def test_pano_alucinado_es_problema(self):
        problemas = _problemas_pano_rele("C9", "ABB RET670", UNIVERSO)
        assert len(problemas) == 1 and "paño 'C9'" in problemas[0]

    def test_rele_alucinado_es_problema(self):
        problemas = _problemas_pano_rele("BT1", "SIEMENS 7SJ82", UNIVERSO)
        assert len(problemas) == 1 and "relé 'SIEMENS 7SJ82'" in problemas[0]


class TestValidacionPorParConSubPanos:
    """Alfa pág. 28: la tabla "HT1/CT1" declara SEL 351S en CT1A/CT1B y
    SEL 311C en HT1. Un sub-paño que no es componente de ninguna sección solo
    vale junto al relé que lo declaró (invariante 14)."""

    UNIVERSO = _universo_etapa1([
        _seccion("HT1/CT1", _rele("SEL 351S", "CT1A", "CT1B"), _rele("SEL 311C", "HT1"),
                 _rele("SEL 387")),
        _seccion("HT2/ET2", _rele("SEL 387E", "HT2-ET2")),
    ])

    def test_sub_pano_con_su_rele_es_valido(self):
        assert _problemas_pano_rele("CT1A", "SEL 351S", self.UNIVERSO) == []
        assert _problemas_pano_rele("ct1b", "SEL-351S", self.UNIVERSO) == []

    def test_sub_pano_con_otro_rele_es_problema(self):
        problemas = _problemas_pano_rele("CT1A", "SEL 311C", self.UNIVERSO)
        assert len(problemas) == 1
        assert "sub-paño de otro relé" in problemas[0] and "'SEL 311C'" in problemas[0]

    def test_componentes_de_la_seccion_siguen_validos_con_cualquier_rele(self):
        # Se mantiene la regla previa para los componentes de las secciones.
        assert _problemas_pano_rele("HT1", "SEL 387", self.UNIVERSO) == []
        assert _problemas_pano_rele("CT1", "SEL 351S", self.UNIVERSO) == []

    def test_sub_pano_compuesto_se_valida_por_componentes(self):
        # "HT2-ET2" se desdobla en HT2 y ET2, ambos componentes de la sección.
        assert self.UNIVERSO.reles_por_sub_pano.keys() == {"ct1a", "ct1b"}

    def test_sub_pano_y_rele_inventados_reportan_ambos(self):
        problemas = _problemas_pano_rele("CT9Z", "SEL 999", self.UNIVERSO)
        assert len(problemas) == 2


class TestSplitPanoCompuesto:
    def test_pano_simple_no_se_desdobla(self):
        assert _split_pano_compuesto("C1") == ["C1"]

    def test_pano_compuesto_se_desdobla(self):
        assert _split_pano_compuesto("BT1/ET1") == ["BT1", "ET1"]

    def test_espacios_alrededor_de_barra(self):
        assert _split_pano_compuesto("BT1 / ET1") == ["BT1", "ET1"]

    def test_triple(self):
        assert _split_pano_compuesto("A/B/C") == ["A", "B", "C"]

    @pytest.mark.parametrize("nombre", ["BT1-CT1", "BT1 - CT1", "BT1 – CT1", "BT1—CT1"])
    def test_guion_entre_codigos_se_desdobla(self, nombre: str):
        # Zeta / Gamma: mismo desdoblamiento que la Etapa 2.
        assert _split_pano_compuesto(nombre) == ["BT1", "CT1"]

    @pytest.mark.parametrize("nombre", ["E-1", "DT1 – P.NEUTRO"])
    def test_guion_sin_dos_codigos_no_se_parte(self, nombre: str):
        assert _split_pano_compuesto(nombre) == [nombre]

    def test_barra_y_guion_combinados(self):
        assert _split_pano_compuesto("CH/BT1-CT1") == ["CH", "BT1", "CT1"]
