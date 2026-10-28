"""M34 (decisión del usuario 2026-10-27): el mismo veredicto para las copias de un
par del mismo origen, del lado seguro (paso 4f, después de 4e).

Una fila del Excel y un hallazgo del PDF que aplican a varios paños se desdoblan en
una copia por tupla (invariante 8): son el mismo par, y hoy cada copia se juzga por
separado. Con UNIFICAR_COPIAS, las copias del mismo origen (los dos lados marcados
como desdoblados, con los mismos textos, la misma página y la misma fila, el mismo
relé y paños distintos) se igualan: la confianza del juez de emparejamiento a la más
baja (y el corte 0,8 recalculado, con 19e(c) para la que queda dudosa), y el
«difiere» del juez de redacción pasa a las copias que había dado por «mismo
contenido». Nunca empareja entre tuplas (invariante 14) ni rehace el emparejamiento.
Apagado = comportamiento previo exacto.
"""

from typing import Any

import pytest

from comparador import etapa4_matching
from comparador.config import settings
from comparador.etapa4_matching import (
    MARCA_COPIA,
    _unificar_copias,
    contar_copias_unificadas,
)
from comparador.schemas import (
    Calificacion,
    CampoDiferente,
    Diferencia,
    EquivalenciaRedaccion,
    EstadoHallazgo,
    Evidencia,
    FuenteEvidencia,
    Hallazgo,
    MatchResult,
    MotivoDiferencia,
    TipoMatch,
)
from tests.test_etapa4_matching import _hallazgo, embeddings_fake, juez_prohibido  # noqa: F401

DESC_PDF = "No se encuentra el ECAP vigente adjunto en Infotécnica."
DESC_EXCEL = "El ECAP vigente no está adjunto en la plataforma Infotécnica."
ACCION = "Adjuntar el ECAP vigente en Infotécnica."
CONCLUYO = "el juez de redacción concluyó que el contenido difiere: "


def _h(fuente: FuenteEvidencia, pano: str, *, desc: str, multi: bool = True,
       pagina: int = 16, fila: int = 41, rele: str = "SEL 751") -> Hallazgo:
    pdf = fuente == FuenteEvidencia.PDF
    return Hallazgo(
        pano=pano, rele=rele, clasificacion="Verificación ECAP", descripcion=desc,
        accion_correctiva=ACCION, calificacion=Calificacion.MENOR,
        evidencia=Evidencia(fuente=fuente, texto_crudo=desc, es_multi_pano_origen=multi,
                            pagina_pdf=pagina if pdf else None,
                            fila_excel=None if pdf else fila,
                            hoja_excel=None if pdf else "Tabla de Hallazgos"))


def _par(pano: str, confianza: float, *, eq: bool = False, difiere_juez: bool = False,
         multi_pdf: bool = True, multi_excel: bool = True, pagina: int = 16, fila: int = 41,
         desc_pdf: str = DESC_PDF, rele: str = "SEL 751",
         dudoso: str | None = None) -> MatchResult:
    tipo = (TipoMatch.UNICIDAD if confianza == 1.0
            else TipoMatch.SEMANTICO_ALTO if confianza >= 0.8 else TipoMatch.SEMANTICO_BAJO)
    diferencias, equivalencias = [], []
    if eq:
        equivalencias = [EquivalenciaRedaccion(
            campo=CampoDiferente.DESCRIPCION, valor_pdf=desc_pdf, valor_excel=DESC_EXCEL,
            similitud=0.78, justificacion="Mismo incumplimiento, otra redacción.")]
    if difiere_juez:
        diferencias = [Diferencia(
            campo=CampoDiferente.DESCRIPCION, valor_pdf=desc_pdf, valor_excel=DESC_EXCEL,
            detalle=("Similitud semántica 0.78, bajo el umbral de coincidencia 0.85; "
                     f"{CONCLUYO}el Excel agrega otro incumplimiento."))]
    return MatchResult(
        pano=pano, rele=rele, estado=EstadoHallazgo.DIFIERE if diferencias
        else EstadoHallazgo.COINCIDE, tipo_match=tipo, confianza=confianza,
        justificacion="Mismo hallazgo.",
        hallazgo_pdf=_h(FuenteEvidencia.PDF, pano, desc=desc_pdf, multi=multi_pdf,
                        pagina=pagina, rele=rele),
        hallazgo_excel=_h(FuenteEvidencia.EXCEL, pano, desc=DESC_EXCEL, multi=multi_excel,
                          fila=fila, rele=rele),
        diferencias=diferencias, equivalencias_redaccion=equivalencias,
        emparejamiento_dudoso=dudoso)


def _dudosa_sin_juez(pano: str, confianza: float) -> MatchResult:
    """Par dudoso: 4e no lo manda al juez de redacción (19e(c)) y queda con la
    Diferencia de 4c."""
    return _par(pano, confianza).model_copy(update={
        "estado": EstadoHallazgo.DIFIERE, "diferencias": [Diferencia(
            campo=CampoDiferente.DESCRIPCION, valor_pdf=DESC_PDF, valor_excel=DESC_EXCEL,
            detalle="Similitud semántica 0.78, bajo el umbral de coincidencia 0.85")]})


@pytest.fixture(autouse=True)
def _umbrales(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "threshold_descripcion", 0.85)
    monkeypatch.setattr(settings, "threshold_accion", 0.85)


class TestConfianza:
    def test_la_mas_baja_y_el_corte_recalculado(self) -> None:
        # Sonnet B2 Gamma: el mismo prompt dio 84 y 78 (idx 3 y 47).
        alto, bajo = _par("BT1", 0.84), _par("CT1", 0.78)

        a, b = _unificar_copias([alto, bajo])

        assert (a.confianza, a.tipo_match) == (0.78, TipoMatch.SEMANTICO_BAJO)
        assert MARCA_COPIA in a.justificacion and "CT1" in a.justificacion
        assert a.justificacion.startswith("Mismo hallazgo.")
        # La que ya tenía la más baja no cambia.
        assert b == bajo
        assert a.emparejamiento_es_dudoso   # «(revisar)» y requieren_revision

    def test_dentro_de_la_banda_no_cambia_el_tipo(self) -> None:
        a, b = _unificar_copias([_par("BT1", 0.99), _par("CT1", 0.98)])
        assert (a.confianza, a.tipo_match, b.confianza) == (0.98, TipoMatch.SEMANTICO_ALTO, 0.98)

    def test_unicidad_queda_en_uno(self) -> None:
        unico, semantico = _par("BT1", 1.0), _par("CT1", 0.82)
        assert _unificar_copias([unico, semantico]) == [unico, semantico]


class TestRedaccion:
    def test_el_difiere_del_juez_pasa_a_la_copia_con_mismo_contenido(self) -> None:
        # Sonnet B2 Gamma idx 62 (mismo contenido) e idx 14 (difiere), pág. 16, fila 41.
        eq, dif = _par("CT2", 1.0, eq=True), _par("BT2", 1.0, difiere_juez=True)

        a, b = _unificar_copias([eq, dif])

        assert a.estado == EstadoHallazgo.DIFIERE and a.equivalencias_redaccion == []
        (d,) = a.diferencias
        assert d.campo == CampoDiferente.DESCRIPCION
        assert (d.detalle or "").startswith(
            "Similitud semántica 0.78, bajo el umbral de coincidencia 0.85")
        assert MARCA_COPIA in (d.detalle or "") and "BT2" in (d.detalle or "")
        # Nada se descarta en silencio: las dos justificaciones del juez quedan a la vista.
        assert "el Excel agrega otro incumplimiento" in (d.detalle or "")
        assert "Mismo incumplimiento, otra redacción." in (d.detalle or "")
        assert "concluyó que el contenido difiere" not in (d.detalle or "")
        assert d.motivo == MotivoDiferencia.JUEZ_REDACCION
        assert b == dif

    def test_la_copia_que_queda_dudosa_no_se_adjudica_como_parafrasis(self) -> None:
        # 19e(c) otra vez: la copia alta (0,84) pasó por el juez de redacción con
        # «mismo contenido»; al bajar a 0,78 queda dudosa y su equivalencia pasa a
        # Diferencia. La baja nunca fue al juez (ya era dudosa en 4e).
        alto, bajo = _par("BT1", 0.84, eq=True), _dudosa_sin_juez("CT1", 0.78)

        a, b = _unificar_copias([alto, bajo])

        assert a.tipo_match == TipoMatch.SEMANTICO_BAJO
        assert a.estado == EstadoHallazgo.DIFIERE and a.equivalencias_redaccion == []
        (d,) = a.diferencias
        assert (d.detalle or "").startswith(
            "Similitud semántica 0.78, bajo el umbral de coincidencia 0.85")
        assert MARCA_COPIA in (d.detalle or "") and "19e(c)" in (d.detalle or "")
        assert "Mismo incumplimiento, otra redacción." in (d.detalle or "")
        assert b == bajo

    def test_con_los_embeddings_la_similitud_del_detalle_es_la_exacta(self) -> None:
        # La equivalencia guarda la similitud redondeada a 4 decimales (0,7750 desde
        # 0,77496): el detalle, con los embeddings, dice 0.77 como el resto de E4.
        import numpy as np

        eq, dif = _par("CT2", 1.0, eq=True), _par("BT2", 1.0, difiere_juez=True)
        eq = eq.model_copy(update={"equivalencias_redaccion": [
            eq.equivalencias_redaccion[0].model_copy(update={"similitud": 0.775})]})
        coseno = 0.77496
        emb = {DESC_PDF: np.array([1.0, 0.0]),
               DESC_EXCEL: np.array([coseno, (1 - coseno ** 2) ** 0.5])}

        (a, _), (b, _) = (_unificar_copias([eq, dif], emb), _unificar_copias([eq, dif]))

        assert (a.diferencias[0].detalle or "").startswith("Similitud semántica 0.77,")
        assert (b.diferencias[0].detalle or "").startswith("Similitud semántica 0.78,")

    def test_la_exclusion_por_19ec_no_se_propaga_a_una_copia_segura(self) -> None:
        # Una copia dudosa sin juez (Diferencia de 4c) y una por unicidad con «mismo
        # contenido»: la duda es del emparejamiento de la otra tupla, no del texto.
        segura, dudosa = _par("BT1", 1.0, eq=True), _dudosa_sin_juez("CT1", 0.62)

        assert _unificar_copias([segura, dudosa]) == [segura, dudosa]

    def test_el_motivo_de_pd71_no_se_propaga(self) -> None:
        motivo = "Revisar a qué hallazgo corresponde esta fila…"
        a, b = _unificar_copias([_par("BT1", 0.84, dudoso=motivo), _par("CT1", 0.83)])
        assert (a.emparejamiento_dudoso, b.emparejamiento_dudoso) == (motivo, None)
        assert b.confianza == 0.83 and a.confianza == 0.83


class TestQueEsUnaCopia:
    @pytest.mark.parametrize("cambio", [
        {"multi_pdf": False}, {"multi_excel": False},   # sin la marca de desdoblamiento
        {"fila": 44},                                   # otra fila: otro error del Excel
        {"pagina": 13},                                 # otra página
        {"desc_pdf": DESC_PDF + " Además, falta el DUF."},  # otro texto del PDF
        {"rele": "SEL 351"},                            # otro relé
    ])
    def test_otro_origen_no_se_unifica(self, cambio: dict[str, Any]) -> None:
        eq, dif = _par("CT2", 1.0, eq=True), _par("BT2", 1.0, difiere_juez=True, **cambio)
        assert _unificar_copias([eq, dif]) == [eq, dif]

    def test_dos_miembros_en_la_misma_tupla_no_se_unifican(self) -> None:
        eq, dif = _par("BT2", 1.0, eq=True), _par("BT2", 1.0, difiere_juez=True)
        assert _unificar_copias([eq, dif]) == [eq, dif]

    def test_faltas_extras_y_transversales_no_se_tocan(self) -> None:
        par = _par("BT1", 0.84)
        falta = par.model_copy(update={"hallazgo_excel": None, "estado":
                                       EstadoHallazgo.FALTA_EN_EXCEL,
                                       "tipo_match": TipoMatch.SIN_MATCH, "confianza": 0.0})
        assert _unificar_copias([falta, _par("CT1", 0.78)])[0] == falta


def test_contar_copias_unificadas() -> None:
    salida = _unificar_copias([_par("BT1", 0.84, eq=True), _par("CT1", 0.78),
                               _par("CT2", 1.0, eq=True), _par("BT2", 1.0, difiere_juez=True)])
    assert contar_copias_unificadas(salida) == {
        "confianzas_igualadas": 1, "campos_a_diferencia": 2}


class TestEnElMatching:
    """El paso corre después de 4e: no cambia ninguna llamada a los jueces."""

    @pytest.fixture
    def orden(self, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
              ) -> list[str]:
        request.getfixturevalue("embeddings_fake")
        monkeypatch.setattr(settings, "juez_redaccion", True)
        vistos: list[str] = []
        revisar, unificar = etapa4_matching._revisar_redaccion, etapa4_matching._unificar_copias
        monkeypatch.setattr(etapa4_matching, "_revisar_redaccion",
                            lambda *a: vistos.append("4e") or revisar(*a))
        monkeypatch.setattr(etapa4_matching, "_unificar_copias",
                            lambda rs, emb=None: vistos.append("4f") or unificar(rs, emb))
        return vistos

    def _correr(self) -> None:
        # Un par por unicidad: no hace falta el juez de emparejamiento.
        h_pdf = _hallazgo(pano="BT1", descripcion="Alfa.")
        h_excel = _hallazgo(pano="BT1", descripcion="Alfa.", fuente=FuenteEvidencia.EXCEL)
        etapa4_matching.ejecutar_matching([h_pdf], [h_excel])

    @pytest.mark.usefixtures("juez_prohibido")
    def test_apagado_no_corre(self, orden: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
        # Encendido por defecto desde el 2026-10-27 (decisión del usuario, D2).
        assert settings.model_fields["unificar_copias"].default is True
        monkeypatch.setattr(settings, "unificar_copias", False)
        self._correr()
        assert orden == ["4e"]

    @pytest.mark.usefixtures("juez_prohibido")
    def test_encendido_corre_despues_de_4e(self, orden: list[str],
                                            monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "unificar_copias", True)
        self._correr()
        assert orden == ["4e", "4f"]
