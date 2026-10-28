"""Tests de construcción de prompts con hints del catálogo."""

from comparador.catalogo import HintsEmpresa, cargar_hints_empresa
from comparador.llm.prompts import (
    SYSTEM_DESCUBRIR_PANOS,
    retroalimentacion_extraccion,
    system_extraer_hallazgos,
)
from comparador.schemas import EmpresaAuditora, ReleDescubierto


def _reles(*nombres: str) -> list[ReleDescubierto]:
    return [ReleDescubierto(nombre=n, evidencia_origen="x") for n in nombres]


class TestPromptExtraccionConHints:
    def test_hints_ensaut_inyectados(self):
        hints = cargar_hints_empresa(EmpresaAuditora.ENSAUT)
        prompt = system_extraer_hallazgos("BT1/ET1", _reles("ABB RET670"), hints)

        assert 'paño "BT1/ET1"' in prompt
        assert "ABB RET670" in prompt
        assert "Hallazgos" in prompt
        # Contenido del bloque Ensaut del catálogo:
        assert "macro-secciones" in prompt
        assert "Comentario específico" in prompt
        assert "sección visual" in prompt

    def test_ensaut_calificacion_columna_o_seccion_visual(self):
        # Variante B trae columna "Calificación"; la A la codifica por sección.
        hints = cargar_hints_empresa(EmpresaAuditora.ENSAUT)
        prompt = system_extraer_hallazgos("BT1/ET1", _reles("ABB RET670"), hints)

        assert "columna de calificación ('Calificación')" in prompt
        assert "columna explícita" in prompt
        assert "se infiere de la sección visual" in prompt

    def test_solo_seccion_visual_sin_columna(self):
        hints = HintsEmpresa(
            descripcion_formato="x",
            mapeo_columnas={"descripcion": ["Desc"]},
            calificacion_por_seccion_visual=True,
            identificacion_rele="x",
            notas_adicionales="x",
        )
        prompt = system_extraer_hallazgos("C1", _reles("SEL 351R"), hints)

        assert "La calificación NO es una columna" in prompt
        assert "columna explícita" not in prompt

    def test_hints_reliable_energy_inyectados(self):
        hints = cargar_hints_empresa(EmpresaAuditora.RELIABLE_ENERGY)
        prompt = system_extraer_hallazgos("C1", _reles("SEL 351R"), hints)

        assert "'Conclusión'" in prompt
        assert "'Recomendación'" in prompt
        assert "'CLASIFICACIÓN DEL HALLAZGO'" in prompt
        assert "'Relevancia Hallazgo'" in prompt
        assert "La calificación aparece como columna explícita." in prompt
        assert "sección visual donde aparece" not in prompt

    def test_mapeo_del_catalogo_manda_sobre_regla_1(self):
        # Gamma: "CLASIFICACIÓN DEL HALLAZGO" trae la descripción. La
        # precedencia se limita al mapeo: el filtrado (regla 3) y la
        # atomización (regla 4) no los puede anular una nota del catálogo.
        hints = cargar_hints_empresa(EmpresaAuditora.RELIABLE_ENERGY)
        prompt = system_extraer_hallazgos("C1", _reles("SEL 351R"), hints)

        assert "manda sobre el mapeo genérico de la regla 1" in prompt
        assert "manda este bloque" not in prompt

    def test_regla_generica_no_confunde_clasificacion_con_calificacion(self):
        hints = cargar_hints_empresa(EmpresaAuditora.ENSAUT)
        prompt = system_extraer_hallazgos("BT1/ET1", _reles("ABB RET670"), hints)

        assert '"Calificación" → campo "calificacion"' in prompt
        assert '"Clasificación" → campo "calificacion"' not in prompt

    def test_sdi_placeholder_no_rompe_prompt(self):
        hints = cargar_hints_empresa(EmpresaAuditora.SDI)
        prompt = system_extraer_hallazgos("C1", _reles("SEL 351R"), hints)

        assert "sin mapeo de columnas caracterizado" in prompt

    def test_pano_compuesto_lo_desdobla_el_sistema(self):
        hints = cargar_hints_empresa(EmpresaAuditora.ENSAUT)
        prompt = system_extraer_hallazgos("BT1/ET1", _reles("ABB RET670"), hints)

        assert "el sistema lo desdobla" in prompt
        assert "no lo separes tú" in prompt


class TestReglasDeRobustezE3:
    """E3 valida paño y relé contra E1: el prompt no debe empujar a valores
    que la validación rechaza (abortos de B0 con Haiku 5.5, 2026-10-16)."""

    def _prompt(self, empresa: EmpresaAuditora, pano: str = "BT1/CT1") -> str:
        hints = cargar_hints_empresa(empresa)
        return system_extraer_hallazgos(pano, _reles("SEL 387", "SEL 551C"), hints)

    def test_rele_exacto_de_la_lista_y_uno_solo(self):
        prompt = self._prompt(EmpresaAuditora.RELIABLE_ENERGY)
        assert "EXACTAMENTE uno de los relés listados" in prompt
        assert "ni concatenes varios relés" in prompt

    def test_regla_7_generica_de_sub_panos(self):
        # La regla vive en el prompt genérico (no depende de una nota del
        # catálogo): un relé con sub-paños reporta uno de ellos como paño.
        prompt = self._prompt(EmpresaAuditora.ENSAUT)
        assert "SUB-PAÑOS: si un relé de la lista de arriba trae sub-paños" in prompt
        assert "aplica a todos sus sub-paños" in prompt
        assert "Un relé sin sub-paños usa el paño de la sección" in prompt
        assert "manda este bloque" not in prompt  # la precedencia global sigue acotada

    def test_reliable_ya_no_manda_al_pano_de_la_seccion(self):
        # Antes: "si el sub-paño no es ninguno de esos (CT1A), usa el paño que
        # estás analizando" — eso generaba los 62 falta/extra de Alfa.
        notas = " ".join(
            cargar_hints_empresa(EmpresaAuditora.RELIABLE_ENERGY).notas_adicionales.split()
        )
        assert "usa el paño que estás analizando" not in notas
        assert '"CT1A" o "CT1B" para el SEL 351S de la tabla "HT1/CT1"' in notas

    def test_descripcion_y_accion_literales(self):
        prompt = self._prompt(EmpresaAuditora.ENSAUT)
        assert '"descripcion" y "accion_correctiva" también se copian LITERALES' in prompt

    def test_reliable_no_prohibe_por_nombre_una_grafia_valida(self):
        # Añañuca usa literalmente "COOPER KYLE FORM 6" en el párrafo previo a la tabla.
        hints = cargar_hints_empresa(EmpresaAuditora.RELIABLE_ENERGY)
        assert "nunca la de los títulos" not in hints.identificacion_rele
        assert "esa es entonces la grafía" in hints.identificacion_rele


class TestSubPanosEnPrompts:
    """Decisión 1 (2026-10-17): E1 lee los sub-paños de la lista "Relé X,
    Serial: …, Paño Y" y E3 los recibe junto a cada relé."""

    def test_e1_pide_sub_panos_literales_y_unidos_por_guion(self):
        assert '"sub_panos"' in SYSTEM_DESCUBRIR_PANOS
        assert '["CT1A", "CT1B"]' in SYSTEM_DESCUBRIR_PANOS
        assert '"Paños HT2-ET2" → ["HT2-ET2"]' in SYSTEM_DESCUBRIR_PANOS
        assert '"Paños BT1 y CT1" → ["BT1-CT1"]' in SYSTEM_DESCUBRIR_PANOS
        assert "UNA sola vez por paño" in SYSTEM_DESCUBRIR_PANOS

    def test_e3_muestra_los_sub_panos_de_cada_rele(self):
        hints = cargar_hints_empresa(EmpresaAuditora.RELIABLE_ENERGY)
        reles = [
            ReleDescubierto(nombre="SEL 351S", evidencia_origen="x", sub_panos=["CT1A", "CT1B"]),
            ReleDescubierto(nombre="SEL 311C", evidencia_origen="x", sub_panos=["HT1"]),
            ReleDescubierto(nombre="SEL 387", evidencia_origen="x"),
        ]
        prompt = system_extraer_hallazgos("HT1/CT1", reles, hints)
        assert (
            'paño "HT1/CT1" que tiene los relés: SEL 351S (sub-paños: CT1A, CT1B), '
            "SEL 311C (sub-paños: HT1), SEL 387." in prompt
        )

    def test_sin_sub_panos_el_prompt_no_cambia(self):
        # Ensaut no declara listas: la línea de relés queda como antes.
        hints = cargar_hints_empresa(EmpresaAuditora.ENSAUT)
        prompt = system_extraer_hallazgos("BT1/ET1", _reles("ABB RET670", "SEL 351S"), hints)
        assert 'paño "BT1/ET1" que tiene los relés: ABB RET670, SEL 351S.' in prompt
        assert "(sub-paños:" not in prompt.split("FUENTE:")[0]

    def test_retroalimentacion_lista_problemas_y_valores_validos(self):
        reles = [ReleDescubierto(nombre="SEL 551C", evidencia_origen="x", sub_panos=["BT1", "CT1"])]
        bloque = retroalimentacion_extraccion(
            ["el relé 'SEL 351R' no está en el mapa de la Etapa 1"], reles, ["BT1", "CT1"]
        )
        assert "- el relé 'SEL 351R' no está en el mapa de la Etapa 1" in bloque
        assert "SEL 551C (sub-paños: BT1, CT1)" in bloque
        assert "Paños: BT1, CT1." in bloque
        assert "lista COMPLETA" in bloque

    def test_retroalimentacion_deja_salida_si_el_error_es_de_la_etapa1(self):
        # B1 Haiku Zeta: E1 omitió CT1. Sin salida explícita, "corrige" empuja
        # a reasignar el hallazgo a otro paño en vez de fallar ruidosamente.
        bloque = retroalimentacion_extraccion(
            ["el paño 'CT1' no está en el mapa de la Etapa 1"], _reles("SEL 551C"), ["BT1", "ET1"]
        )
        assert "no existe" not in bloque
        assert "mapa también puede estar incompleto" in bloque
        assert "devuélvelo tal cual" in bloque and "NO lo reasignes" in bloque
