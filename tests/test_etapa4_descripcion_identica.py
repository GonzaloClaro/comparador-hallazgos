"""M30 (decisión del usuario 2026-10-26): emparejar sin juez las descripciones
idénticas dentro de la tupla (paso 4a', después de la unicidad y antes del juez).

Con DESCRIPCION_IDENTICA, dentro de la tupla, un hallazgo del PDF y una fila del
Excel con la misma descripción (normalizada solo en espacios y mayúsculas) se
emparejan sin LLM; con duplicados, se reparten por acción correctiva y, en
empate, en el orden del informe y del Excel. Lo que sobra va al juez como hoy.
Apagado = comportamiento previo exacto.
"""

from typing import Any

import pytest

from comparador import etapa4_matching
from comparador.config import settings
from comparador.etapa4_matching import _JuezResponse, ejecutar_matching
from comparador.schemas import (
    Calificacion,
    CampoDiferente,
    EstadoHallazgo,
    FuenteEvidencia,
    TipoMatch,
)
from tests.test_etapa4_matching import _hallazgo, embeddings_fake, juez_prohibido  # noqa: F401

EXCEL = FuenteEvidencia.EXCEL
# Misma clasificación en todos: la unicidad (4a) no aplica y, sin M30, decide el juez.
CLASE = "Verificación DUF"


@pytest.fixture(autouse=True)
def _base(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    request.getfixturevalue("embeddings_fake")
    monkeypatch.setattr(settings, "juez_redaccion", False)
    monkeypatch.setattr(settings, "descripcion_identica", True)


@pytest.fixture(params=[False, True], ids=["en-orden", "asignacion-global"])
def ambos_modos(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> bool:
    monkeypatch.setattr(settings, "asignacion_global", request.param)
    return bool(request.param)


class _Juez:
    """Juez falso: elige el primer candidato con 90 y anota cada pedido."""

    def __init__(self) -> None:
        self.vistos: list[str] = []

    def __call__(self, **kw: Any) -> tuple[_JuezResponse, dict[str, Any]]:
        self.vistos.append(kw["user_prompt"])
        return (_JuezResponse(indice_candidato=0, confianza=90, justificacion="Elegido."),
                {"tokens_total": 1})


@pytest.fixture
def juez(monkeypatch: pytest.MonkeyPatch) -> _Juez:
    falso = _Juez()
    monkeypatch.setattr(etapa4_matching, "llamar_llm_estructurado", falso)
    return falso


def _pdf(desc: str, accion: str = "Actualizar el DUF.", **kw: Any) -> Any:
    return _hallazgo(clasificacion=CLASE, descripcion=desc, accion=accion, **kw)


def _xls(desc: str, accion: str = "Actualizar el DUF.", **kw: Any) -> Any:
    return _hallazgo(clasificacion=CLASE, descripcion=desc, accion=accion, fuente=EXCEL, **kw)


def _par(resultados: list[Any], desc_pdf: str) -> Any:
    (r,) = [r for r in resultados if r.hallazgo_pdf and r.hallazgo_pdf.descripcion == desc_pdf]
    return r


@pytest.mark.usefixtures("ambos_modos", "juez_prohibido")
class TestSinJuez:
    def test_descripciones_identicas_se_emparejan_sin_juez(self) -> None:
        pdf = [_pdf("Problema A."), _pdf("Problema B.")]
        excel = [_xls("Problema B."), _xls("Problema A.")]
        resultados, metas = ejecutar_matching(pdf, excel)
        assert [m for m in metas if m.get("etapa") != "embeddings"] == []
        for desc in ("Problema A.", "Problema B."):
            r = _par(resultados, desc)
            assert r.hallazgo_excel is not None and r.hallazgo_excel.descripcion == desc
            assert (r.tipo_match, r.confianza, r.estado) == (
                TipoMatch.DESCRIPCION_IDENTICA, 1.0, EstadoHallazgo.COINCIDE)
            assert not r.emparejamiento_es_dudoso

    def test_normaliza_solo_espacios_y_mayusculas(self) -> None:
        pdf = [_pdf("Problema  DEL  relé."), _pdf("Otro.")]
        excel = [_xls("problema del relé."), _xls("Otro.")]
        resultados, _ = ejecutar_matching(pdf, excel)
        assert _par(resultados, "Problema  DEL  relé.").tipo_match == TipoMatch.DESCRIPCION_IDENTICA


    def test_calificacion_distinta_difiere(self) -> None:
        # El error de la fila 107 de Alfa: misma descripción, otra calificación.
        pdf = [_pdf("Problema A.", calificacion=Calificacion.RELEVANTE), _pdf("Otro.")]
        excel = [_xls("Problema A.", calificacion=Calificacion.MENOR)]
        resultados, _ = ejecutar_matching(pdf, excel)
        r = _par(resultados, "Problema A.")
        assert r.estado == EstadoHallazgo.DIFIERE
        assert [d.campo for d in r.diferencias] == [CampoDiferente.CALIFICACION]
        assert _par(resultados, "Otro.").estado == EstadoHallazgo.FALTA_EN_EXCEL

    def test_duplicados_se_reparten_por_accion(self) -> None:
        # Beta E1-E9: la misma descripción con dos acciones, en orden cruzado.
        pdf = [_pdf("ECAP.", "Disponer el ECAP."), _pdf("ECAP.", "Cargar el Print Out.")]
        excel = [_xls("ECAP.", "Cargar el Print Out."), _xls("ECAP.", "Disponer el ECAP.")]
        resultados, _ = ejecutar_matching(pdf, excel)
        assert all(r.estado == EstadoHallazgo.COINCIDE for r in resultados)
        assert {(r.hallazgo_pdf.accion_correctiva, r.hallazgo_excel.accion_correctiva)
                for r in resultados if r.hallazgo_pdf and r.hallazgo_excel} == {
            ("Disponer el ECAP.", "Disponer el ECAP."),
            ("Cargar el Print Out.", "Cargar el Print Out.")}
        assert all("se repartieron por acción" in r.justificacion for r in resultados)

    def test_empate_por_orden_del_informe_y_del_excel(self) -> None:
        # Añañuca, fila 42: la misma descripción y la misma acción en las págs. 19 y 20.
        pdf = [_pdf("51N."), _pdf("51N.")]
        excel = [_xls("51N.")]
        resultados, _ = ejecutar_matching(pdf, excel)
        (par,) = [r for r in resultados if r.hallazgo_excel is not None]
        assert par.hallazgo_pdf is pdf[0]
        assert par.tipo_match == TipoMatch.DESCRIPCION_IDENTICA
        (falta,) = [r for r in resultados if r.hallazgo_excel is None]
        assert falta.hallazgo_pdf is pdf[1] and falta.estado == EstadoHallazgo.FALTA_EN_EXCEL

    def test_no_cruza_tuplas(self) -> None:
        resultados, _ = ejecutar_matching([_pdf("Problema A.", pano="C1")],
                                          [_xls("Problema A.", pano="C2")])
        assert {r.estado for r in resultados} == {
            EstadoHallazgo.FALTA_EN_EXCEL, EstadoHallazgo.EXTRA_EN_EXCEL}

    def test_unicidad_primero(self) -> None:
        # Invariante 17: una clasificación única en los dos lados va por unicidad
        # aunque la descripción también sea idéntica.
        pdf = [_hallazgo(clasificacion="Prueba Única", descripcion="Problema A.")]
        excel = [_hallazgo(clasificacion="Prueba Única", descripcion="Problema A.",
                           fuente=EXCEL)]
        (r,) = ejecutar_matching(pdf, excel)[0]
        assert r.tipo_match == TipoMatch.UNICIDAD


@pytest.mark.usefixtures("ambos_modos")
def test_tildes_y_puntuacion_no_se_normalizan(juez: _Juez) -> None:
    pdf = [_pdf("Problema del rele"), _pdf("Otro.")]
    excel = [_xls("Problema del relé."), _xls("Otro.")]
    resultados, _ = ejecutar_matching(pdf, excel)
    assert len(juez.vistos) == 1
    assert _par(resultados, "Problema del rele").tipo_match != TipoMatch.DESCRIPCION_IDENTICA


@pytest.mark.usefixtures("ambos_modos")
def test_lo_que_sobra_va_al_juez_sin_las_filas_tomadas(juez: _Juez) -> None:
    pdf = [_pdf("Problema A."), _pdf("Problema distinto.")]
    excel = [_xls("Problema A."), _xls("Otra redacción.")]
    resultados, _ = ejecutar_matching(pdf, excel)
    # Una sola consulta (la del hallazgo sin par idéntico) y sin la fila ya tomada.
    assert len(juez.vistos) == 1 and "Problema A." not in juez.vistos[0]
    assert _par(resultados, "Problema A.").tipo_match == TipoMatch.DESCRIPCION_IDENTICA
    assert _par(resultados, "Problema distinto.").tipo_match == TipoMatch.SEMANTICO_ALTO


@pytest.mark.usefixtures("ambos_modos")
def test_apagado_es_el_comportamiento_previo(juez: _Juez,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "descripcion_identica", False)
    pdf = [_pdf("Problema A."), _pdf("Problema B.")]
    excel = [_xls("Problema A."), _xls("Problema B.")]
    resultados, _ = ejecutar_matching(pdf, excel)
    assert len(juez.vistos) == 2
    assert TipoMatch.DESCRIPCION_IDENTICA not in {r.tipo_match for r in resultados}


@pytest.mark.usefixtures("juez_prohibido")
def test_polaridad_y_juez_de_redaccion_siguen_corriendo(monkeypatch: pytest.MonkeyPatch) -> None:
    # 4e revisa también estos pares: la acción con polaridad opuesta difiere sin LLM.
    monkeypatch.setattr(settings, "juez_redaccion", True)
    pdf = [_pdf("Problema A.", "Cumple con la norma."), _pdf("Otro.")]
    excel = [_xls("Problema A.", "No cumple con la norma."), _xls("Otro.")]
    resultados, _ = ejecutar_matching(pdf, excel)
    r = _par(resultados, "Problema A.")
    assert r.tipo_match == TipoMatch.DESCRIPCION_IDENTICA
    assert r.estado == EstadoHallazgo.DIFIERE
    assert CampoDiferente.ACCION_CORRECTIVA in [d.campo for d in r.diferencias]
