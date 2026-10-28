"""Compuerta de los golden y red de seguridad de la suite (Bloque 23, E1).

- GOLDEN_OBLIGATORIO=1 (hooks de tests/conftest.py): un test golden saltado
  hace fallar la sesión, salvo motivo «exento:»; también si no corrió ninguno.
  Se prueba con sesiones de pytest aparte (pytester).
- Los 3 errores reales del Excel (test_golden_errores_no_mostrados): la
  verificación son funciones puras, probadas acá con reportes sintéticos
  armados con el schema real, sin datos privados.
- Ningún test crea un cliente real de OpenAI ni de Anthropic (tampoco desde un
  fixture de módulo) ni lee los GT privados por defecto, y los temporales de
  los tests que pasan no se conservan.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

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
    TipoMatch,
)
from tests.golden import test_golden_errores_no_mostrados as errores
from tests.golden.datos import Caso

ROOT = Path(__file__).resolve().parents[1]
OPUS = "claude-opus-5-5"
SONNET = "claude-sonnet-5-5"

# ------------------------------------------------------------ GOLDEN_OBLIGATORIO

INI = "[pytest]\nmarkers =\n    golden: datos reales\n"


@pytest.fixture
def sesion(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    """Una sesión de pytest aparte con los hooks de tests/conftest.py."""
    monkeypatch.delenv("GOLDEN_OBLIGATORIO", raising=False)
    monkeypatch.delenv("GOLDEN_MEDICIONES", raising=False)
    pytester.makeini(INI)
    pytester.makeconftest('pytest_plugins = ["tests.conftest"]\n')
    return pytester


GOLDEN_SALTADO = """
    import pytest
    pytestmark = pytest.mark.golden
    def test_corre():
        pass
    def test_saltado():
        pytest.skip("sin mediciones/")
"""


def test_sin_la_variable_un_golden_saltado_no_cambia_nada(sesion: pytest.Pytester) -> None:
    sesion.makepyfile(GOLDEN_SALTADO)

    resultado = sesion.runpytest()

    assert resultado.ret == pytest.ExitCode.OK
    resultado.assert_outcomes(passed=1, skipped=1)


def test_un_golden_saltado_hace_fallar_la_sesion(
    sesion: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOLDEN_OBLIGATORIO", "1")
    sesion.makepyfile(GOLDEN_SALTADO)

    resultado = sesion.runpytest()

    assert resultado.ret == pytest.ExitCode.TESTS_FAILED
    resultado.stdout.fnmatch_lines(["*test_saltado*sin mediciones/*"])


def test_un_salto_exento_se_permite_y_se_imprime(
    sesion: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOLDEN_OBLIGATORIO", "1")
    sesion.makepyfile("""
        import pytest
        def test_no_golden_saltado():
            pytest.skip("los saltos fuera de los golden no cuentan")
        @pytest.mark.golden
        def test_corre():
            pass
        @pytest.mark.golden
        def test_exento():
            pytest.skip("exento: sin repeticiones de E4 todavía")
    """)

    resultado = sesion.runpytest()

    assert resultado.ret == pytest.ExitCode.OK
    resultado.stdout.fnmatch_lines(["*test_exento*exento: sin repeticiones de E4 todavía*"])


def test_una_parametrizacion_vacia_cuenta_como_salto(
    sesion: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOLDEN_OBLIGATORIO", "1")
    sesion.makepyfile("""
        import pytest
        pytestmark = pytest.mark.golden
        def test_corre():
            pass
        @pytest.mark.parametrize("caso", [])
        def test_sin_casos(caso):
            pass
    """)

    resultado = sesion.runpytest()

    assert resultado.ret == pytest.ExitCode.TESTS_FAILED
    resultado.stdout.fnmatch_lines(["*test_sin_casos*empty parameter set*"])


def test_sin_ningun_golden_corrido_la_sesion_falla(
    sesion: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOLDEN_OBLIGATORIO", "1")
    sesion.makepyfile("""
        import pytest
        def test_no_golden():
            pass
        @pytest.mark.golden
        def test_exento():
            pytest.skip("exento: nada que evaluar")
    """)

    resultado = sesion.runpytest()

    assert resultado.ret == pytest.ExitCode.TESTS_FAILED
    resultado.stdout.fnmatch_lines(["*no corrió ningún test golden*"])


def test_un_xfail_no_es_un_salto(
    sesion: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOLDEN_OBLIGATORIO", "1")
    sesion.makepyfile("""
        import pytest
        pytestmark = pytest.mark.golden
        def test_corre():
            pass
        @pytest.mark.xfail(strict=True, raises=AssertionError, reason="falla conocida")
        def test_conocido():
            assert False
    """)

    resultado = sesion.runpytest()

    assert resultado.ret == pytest.ExitCode.OK
    resultado.assert_outcomes(passed=1, xfailed=1)


@pytest.mark.parametrize(("obligatorio", "codigo"), [
    pytest.param("1", pytest.ExitCode.TESTS_FAILED, id="con-GOLDEN_OBLIGATORIO"),
    pytest.param(None, pytest.ExitCode.OK, id="sin-la-variable"),
])
def test_con_mediciones_vacias_los_golden_se_saltan(
    sesion: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    obligatorio: str | None, codigo: pytest.ExitCode,
) -> None:
    """GOLDEN_MEDICIONES apunta a una carpeta vacía: requiere_mediciones salta el
    golden. En un proceso aparte, porque tests.golden.datos fija la carpeta al
    importarse."""
    vacia = tmp_path / "mediciones"
    vacia.mkdir()
    monkeypatch.setenv("GOLDEN_MEDICIONES", str(vacia))
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    if obligatorio:
        monkeypatch.setenv("GOLDEN_OBLIGATORIO", obligatorio)
    sesion.makepyfile("""
        import pytest
        from tests.golden.datos import requiere_mediciones
        pytestmark = [pytest.mark.golden, requiere_mediciones]
        def test_golden():
            pass
    """)

    resultado = sesion.runpytest_subprocess()

    assert resultado.ret == codigo
    resultado.assert_outcomes(skipped=1)


# ------------------------------------------- errores reales del Excel (reportes sintéticos)

ERROR_107, ERROR_98, ERROR_39 = errores.ERRORES


def _hallazgo(fuente: FuenteEvidencia, *, fila: int | None = None, pagina: int | None = None,
              clasificacion: str = "Excel") -> Hallazgo:
    return Hallazgo(
        pano="HT2", rele="SEL 387E", clasificacion=clasificacion, descripcion="texto",
        calificacion=Calificacion.MENOR,
        evidencia=Evidencia(fuente=fuente, pagina_pdf=pagina, fila_excel=fila, texto_crudo="t"),
    )


def _resultado(
    error: errores.ErrorNoMostrado, estado: EstadoHallazgo, *, pagina: int | None = None,
    clasificacion: str | None = None, campos: tuple[str, ...] = (),
    equivalentes: tuple[str, ...] = (),
) -> MatchResult:
    """Resultado de la fila del caso; sin página, la fila queda sin hallazgo del PDF."""
    pdf = None if pagina is None else _hallazgo(
        FuenteEvidencia.PDF, pagina=pagina, clasificacion=clasificacion or error.clasificacion_pdf)
    return MatchResult(
        pano="HT2", rele="SEL 387E", estado=estado, tipo_match=TipoMatch.SEMANTICO_ALTO,
        confianza=0.9, justificacion="", hallazgo_pdf=pdf,
        hallazgo_excel=_hallazgo(FuenteEvidencia.EXCEL, fila=error.fila_excel),
        diferencias=[Diferencia(campo=CampoDiferente(c), valor_pdf="a", valor_excel="b")
                     for c in campos],
        equivalencias_redaccion=[
            EquivalenciaRedaccion(campo=CampoDiferente(c), valor_pdf="a", valor_excel="b",
                                  similitud=0.7, justificacion="")
            for c in equivalentes],
    )


def _reporte(*resultados: MatchResult) -> dict[str, object]:
    """Como se lee reporte_final.json (el JSON del schema real), con otra fila
    que coincide."""
    otra_fila = MatchResult(
        pano="HT2", rele="SEL 387E", estado=EstadoHallazgo.COINCIDE,
        tipo_match=TipoMatch.UNICIDAD, confianza=1.0, justificacion="",
        hallazgo_pdf=_hallazgo(FuenteEvidencia.PDF, pagina=1),
        hallazgo_excel=_hallazgo(FuenteEvidencia.EXCEL, fila=1),
    )
    return {"resultados": [r.model_dump(mode="json") for r in (*resultados, otra_fila)]}


def _visible(error: errores.ErrorNoMostrado) -> MatchResult:
    return _resultado(error, EstadoHallazgo.DIFIERE, pagina=error.pagina_pdf,
                      campos=error.campos)


def test_la_fila_107_en_coincide_no_pasa_la_verificacion() -> None:
    reporte = _reporte(_resultado(ERROR_107, EstadoHallazgo.COINCIDE, pagina=32))

    assert errores.escondido(reporte, ERROR_107)
    assert errores.verificar_error(reporte, ERROR_107)


@pytest.mark.parametrize("error", errores.ERRORES, ids=lambda e: f"{e.subestacion}-{e.fila_excel}")
def test_el_error_visible_con_su_contraparte_pasa(error: errores.ErrorNoMostrado) -> None:
    reporte = _reporte(_visible(error))

    assert errores.escondido(reporte, error) == []
    assert errores.sin_contraparte(reporte, error) == []
    assert errores.verificar_error(reporte, error) == []


@pytest.mark.parametrize("resultados", [
    pytest.param((), id="la-fila-no-aparece"),
    pytest.param((_resultado(ERROR_98, EstadoHallazgo.EXTRA_EN_EXCEL),), id="extra-en-excel"),
    pytest.param((_resultado(ERROR_98, EstadoHallazgo.DIFIERE, pagina=30,
                             campos=("calificacion",)),), id="otra-pagina"),
    pytest.param((_resultado(ERROR_98, EstadoHallazgo.DIFIERE, pagina=31, clasificacion="Otra",
                             campos=("calificacion",)),), id="otra-clasificacion"),
    pytest.param((_resultado(ERROR_98, EstadoHallazgo.DIFIERE, pagina=31,
                             campos=("descripcion", "calificacion")),), id="otro-campo-difiere"),
    pytest.param((_resultado(ERROR_98, EstadoHallazgo.DIFIERE, pagina=31, campos=("calificacion",),
                             equivalentes=("descripcion",)),), id="equivalente-por-el-juez"),
    pytest.param((_visible(ERROR_98), _resultado(ERROR_98, EstadoHallazgo.COINCIDE, pagina=31)),
                 id="dos-resultados-uno-coincide"),
])
def test_sin_su_contraparte_alfa_98_no_pasa(resultados: tuple[MatchResult, ...]) -> None:
    reporte = _reporte(*resultados)

    assert errores.sin_contraparte(reporte, ERROR_98)
    assert errores.verificar_error(reporte, ERROR_98)


def test_ananuca_39_basta_con_que_la_alerta_lleve_a_la_pagina_20() -> None:
    """La contraparte de Añañuca 39 es una estimación del verificador, no
    validada por el equipo revisor: en la repetición de E4 se exige solo que no
    coincida y que la alerta lleve a la pág. 20."""
    otra_diferencia = _reporte(_resultado(ERROR_39, EstadoHallazgo.DIFIERE, pagina=20,
                                          campos=("accion_correctiva",)))
    rotulo_generico = _reporte(_resultado(ERROR_39, EstadoHallazgo.DIFIERE, pagina=19,
                                          campos=("descripcion",)))
    coincide = _reporte(_resultado(ERROR_39, EstadoHallazgo.COINCIDE, pagina=20))

    assert not ERROR_39.contraparte_validada
    assert errores.sin_contraparte(otra_diferencia, ERROR_39)
    assert errores.verificar_error(otra_diferencia, ERROR_39) == []
    assert errores.verificar_error(rotulo_generico, ERROR_39)
    assert errores.verificar_error(coincide, ERROR_39)


# ------------------------------- inversión de Alfa E7 (fila 69): nunca «coincide»

(INVERSION_E7,) = errores.INVERSIONES


def _de_la_tupla(estado: EstadoHallazgo, *, fila: int | None = 69, pagina: int | None = 26,
                 pano: str = "E7", rele: str = "SEL 451", campos: tuple[str, ...] = (),
                 equivalentes: tuple[str, ...] = ()) -> MatchResult:
    """Resultado de la tupla del caso; sin fila, sin hallazgo del Excel (falta);
    sin página, sin hallazgo del PDF (extra)."""
    def hallazgo(fuente: FuenteEvidencia, **evidencia: int) -> Hallazgo:
        return Hallazgo(pano=pano, rele=rele, clasificacion="Verificación ECAP",
                        descripcion="texto", calificacion=Calificacion.MENOR,
                        evidencia=Evidencia(fuente=fuente, texto_crudo="t", **evidencia))
    return MatchResult(
        pano=pano, rele=rele, estado=estado, tipo_match=TipoMatch.SEMANTICO_ALTO,
        confianza=0.8, justificacion="",
        hallazgo_pdf=None if pagina is None else hallazgo(FuenteEvidencia.PDF, pagina_pdf=pagina),
        hallazgo_excel=None if fila is None else hallazgo(FuenteEvidencia.EXCEL, fila_excel=fila),
        diferencias=[Diferencia(campo=CampoDiferente(c), valor_pdf="a", valor_excel="b")
                     for c in campos],
        equivalencias_redaccion=[
            EquivalenciaRedaccion(campo=CampoDiferente(c), valor_pdf="a", valor_excel="b",
                                  similitud=0.56, justificacion="") for c in equivalentes],
    )


def test_la_inversion_es_alfa_69_en_e7_sel_451_pag_26() -> None:
    esperada = errores.InversionConocida("Alfa", 69, "E7", "SEL 451", 26)
    assert esperada == INVERSION_E7


@pytest.mark.parametrize("resultados", [
    pytest.param((_de_la_tupla(EstadoHallazgo.DIFIERE, campos=("descripcion",)),),
                 id="difiere-en-la-descripcion"),
    pytest.param((_de_la_tupla(EstadoHallazgo.DIFIERE, campos=("descripcion",),
                               rele="SEL-451"),), id="otra-grafia-del-rele"),
    pytest.param((_de_la_tupla(EstadoHallazgo.DIFIERE, campos=("descripcion", "calificacion"),
                               equivalentes=("accion_correctiva",)),),
                 id="la-accion-equivalente-no-esconde-la-descripcion"),
    pytest.param((_de_la_tupla(EstadoHallazgo.EXTRA_EN_EXCEL, pagina=None),
                  _de_la_tupla(EstadoHallazgo.FALTA_EN_EXCEL, fila=None)),
                 id="extra-y-falta-a-la-vista"),
])
def test_la_inversion_a_la_vista_pasa(resultados: tuple[MatchResult, ...]) -> None:
    assert errores.inversion_escondida(_reporte(*resultados), INVERSION_E7) == []


@pytest.mark.parametrize(("resultados", "problema"), [
    pytest.param((_de_la_tupla(EstadoHallazgo.COINCIDE),), "sale «coincide» con la pág. 26",
                 id="coincide-b1"),
    pytest.param((_de_la_tupla(EstadoHallazgo.COINCIDE, equivalentes=("descripcion",)),),
                 "sale «coincide · redacción distinta» con la pág. 26", id="redaccion-ag1"),
    pytest.param((_de_la_tupla(EstadoHallazgo.DIFIERE, campos=("calificacion",),
                               equivalentes=("descripcion",)),),
                 "descripción dada por equivalente", id="difiere-con-la-descripcion-equivalente"),
    # El camino de B1 con otra diferencia: la descripción coincide sobre el umbral
    # y sale «difiere» solo por la calificación o la acción. El equipo revisor
    # revisaría eso, y la inversión está en la descripción.
    pytest.param((_de_la_tupla(EstadoHallazgo.DIFIERE, campos=("calificacion",)),),
                 "sale «difiere» con la pág. 26 sin la descripción entre las diferencias",
                 id="difiere-solo-en-la-calificacion"),
    pytest.param((_de_la_tupla(EstadoHallazgo.DIFIERE, campos=("accion_correctiva",)),),
                 "sin la descripción entre las diferencias", id="difiere-solo-en-la-accion"),
    pytest.param((_de_la_tupla(EstadoHallazgo.DIFIERE, campos=("descripcion",)),
                  _de_la_tupla(EstadoHallazgo.COINCIDE)), "sale «coincide»",
                 id="dos-resultados-uno-coincide"),
    pytest.param((_de_la_tupla(EstadoHallazgo.FALTA_EN_EXCEL, fila=None),), "no aparece",
                 id="la-fila-no-aparece"),
    pytest.param((_de_la_tupla(EstadoHallazgo.DIFIERE, campos=("descripcion",), pano="E5"),),
                 "no aparece", id="la-fila-en-otra-tupla"),
    pytest.param((_de_la_tupla(EstadoHallazgo.DIFIERE, campos=("descripcion",), pagina=25),),
                 "el caso ya no se identifica", id="sin-la-pagina-en-la-tupla"),
])
def test_la_inversion_escondida_o_sin_identificar_no_pasa(
    resultados: tuple[MatchResult, ...], problema: str
) -> None:
    problemas = errores.inversion_escondida(_reporte(*resultados), INVERSION_E7)

    assert any(problema in p for p in problemas), problemas


def test_lo_ya_ocurrido_va_declarado_con_su_motivo() -> None:
    """B1 y AG1 con Opus escondieron la inversión: a la vista, con su motivo;
    AG2 (con V2) y las demás fuentes se exigen."""
    declaradas = errores.INVERSION_ESCONDIDA_CONOCIDA
    assert set(declaradas) == {("b1", OPUS, "Alfa", 69),
                               ("replay_e4/AG1", OPUS, "Alfa", 69)}
    assert declaradas[("b1", OPUS, "Alfa", 69)].startswith("B1, antes de 19e")
    assert declaradas[("replay_e4/AG1", OPUS, "Alfa", 69)].startswith(
        "AG1, antes de V2 (PD71)")


def test_lo_declarado_es_xfail_estricto_y_lo_demas_se_exige() -> None:
    (marca,) = errores.marcas_inversion("replay_e4/AG1", OPUS, INVERSION_E7)
    assert (marca.name, marca.kwargs["strict"], marca.kwargs["raises"]) == (
        "xfail", True, AssertionError)
    assert marca.kwargs["reason"] == errores.INVERSION_ESCONDIDA_CONOCIDA[
        ("replay_e4/AG1", OPUS, "Alfa", 69)]
    for fuente, modelo in (("replay_e4/AG2", OPUS), ("replay_e4/AG1", SONNET), ("b2", OPUS),
                           ("b1", SONNET), ("b4", OPUS)):
        assert errores.marcas_inversion(fuente, modelo, INVERSION_E7) == [], (fuente, modelo)


# ------------------------------------- exención de E4: causa anterior a E4 (PD23)


def test_la_exencion_de_e4_es_solo_alfa_98_con_sonnet() -> None:
    """Alfa 98 con Sonnet no lo puede arreglar la asignación global (E3 no
    extrajo la contraparte en ese relé): su repetición de E4 se salta con
    motivo. Con Opus, y las demás filas, se exigen como siempre."""
    assert set(errores.CAUSA_ANTERIOR_A_E4) == {("Alfa", 98, SONNET)}
    motivo = errores.exencion_e4(ERROR_98, SONNET)
    assert motivo is not None and motivo.startswith("causa anterior a E4: ")
    assert errores.exencion_e4(ERROR_98, OPUS) is None
    for error in (ERROR_107, ERROR_39):
        for modelo in (SONNET, OPUS):
            assert errores.exencion_e4(error, modelo) is None, (error, modelo)


def test_la_exencion_salta_con_un_motivo_exento_y_lo_demas_corre() -> None:
    """Compatible con GOLDEN_OBLIGATORIO: un salto «exento:» con el motivo."""
    (marca,) = errores.marcas_repeticion(errores.exencion_e4(ERROR_98, SONNET))
    assert marca.name == "skip"
    assert marca.kwargs["reason"] == f"exento: {errores.exencion_e4(ERROR_98, SONNET)}"
    assert errores.marcas_repeticion(None) == []


def _e3(*hallazgos: tuple[str, str, str, int]) -> list[dict[str, Any]]:
    """Hallazgos de E3 como en etapa3_pdf_hallazgos.json (lo que lee el golden)."""
    return [{"pano": p, "rele": r, "clasificacion": c, "descripcion": "texto",
             "evidencia": {"pagina_pdf": pag, "texto_crudo": "t"}} for p, r, c, pag in hallazgos]


ECAP = "Verificación ECAP"
SIN_CONTRAPARTE = _e3(("HT2", "SEL 387E", ECAP, 31), ("HT2", "SEL 387E", ECAP, 32),
                      ("HT2", "SEL 311C", "Coordinación de Protecciones", 32))


@pytest.mark.parametrize(("hallazgos", "vigente"), [
    pytest.param(SIN_CONTRAPARTE, True, id="atribuida-a-otro-rele"),
    pytest.param([], True, id="e3-vacia"),
    pytest.param(SIN_CONTRAPARTE + _e3(("HT2", "SEL 311C", ECAP, 31)), False, id="extraida"),
    pytest.param(_e3(("ht2", "SEL-311C", ECAP, 31)), False, id="otra-grafia-misma-tupla"),
    pytest.param(_e3(("HT2", "SEL 311C", ECAP, 30)), False, id="extraida-con-otra-pagina"),
    pytest.param(_e3(("HT2", "SEL 311", ECAP, 31)), True, id="otro-rele"),
])
def test_la_causa_anterior_a_e4_sigue_mientras_e3_no_extraiga_la_contraparte(
    hallazgos: list[dict[str, Any]], vigente: bool
) -> None:
    """La tupla se normaliza como en E4 (etapa4_matching.clave_tupla): otra
    grafía del mismo relé es la misma tupla. Con otra página también cuenta como
    extraída: la exención ya no se sostiene y la repetición debe mostrarlo."""
    assert errores.causa_anterior_vigente(hallazgos, "HT2", "SEL 311C", ERROR_98) is vigente


E2_FILA_98 = [{"pano": "HT2", "rele": "SEL 311C", "clasificacion": ECAP,
               "evidencia": {"fila_excel": 98}}]


E2_FILA_98_DOS_PANOS = E2_FILA_98 + [{"pano": "HT3", "rele": "SEL 311C", "clasificacion": ECAP,
                                     "evidencia": {"fila_excel": 98}}]


@pytest.mark.parametrize(("modelo", "e2", "hallazgos", "exento"), [
    pytest.param(SONNET, E2_FILA_98, SIN_CONTRAPARTE, True, id="sonnet-causa-vigente"),
    pytest.param(SONNET, E2_FILA_98, SIN_CONTRAPARTE + _e3(("HT2", "SEL 311C", ECAP, 31)),
                 False, id="sonnet-e3-de-este-run-la-extrae"),
    pytest.param(SONNET, E2_FILA_98_DOS_PANOS,
                 SIN_CONTRAPARTE + _e3(("HT3", "SEL 311C", ECAP, 31)), False,
                 id="sonnet-la-extrae-en-una-de-las-tuplas-de-la-fila"),
    pytest.param(OPUS, E2_FILA_98, SIN_CONTRAPARTE, False, id="opus-sin-exencion-declarada"),
])
def test_la_exencion_depende_del_run(
    modelo: str, e2: list[dict[str, Any]], hallazgos: list[dict[str, Any]], exento: bool
) -> None:
    """Revisión del Bloque 24: la exención declarada (subestación, fila, modelo)
    se aplica a un run solo si la causa sigue en SU E3, en cada tupla de la fila;
    otro run de Alfa con Sonnet cuya E3 extraiga la contraparte se exige, sin
    pedir quitar la exención (que la repetición de B2 sigue necesitando)."""
    motivo = errores.exencion_del_run(ERROR_98, modelo, e2, hallazgos)
    assert motivo == (errores.exencion_e4(ERROR_98, SONNET) if exento else None)
    for error in (ERROR_107, ERROR_39):
        assert errores.exencion_del_run(error, modelo, e2, hallazgos) is None


def test_la_exencion_se_sostiene_con_la_fila_a_la_vista_y_la_causa_vigente() -> None:
    extra = _reporte(_resultado(ERROR_98, EstadoHallazgo.EXTRA_EN_EXCEL))

    assert errores.exencion_vigente(extra, E2_FILA_98, SIN_CONTRAPARTE, ERROR_98) == []
    # Sin la exención, la misma repetición no pasaría: no muestra el error.
    assert errores.verificar_error(extra, ERROR_98)


@pytest.mark.parametrize(("reporte", "hallazgos", "esperado"), [
    pytest.param(_reporte(_resultado(ERROR_98, EstadoHallazgo.COINCIDE, pagina=31)),
                 SIN_CONTRAPARTE, "sale «coincide»", id="fila-escondida"),
    pytest.param(_reporte(), SIN_CONTRAPARTE, "no aparece", id="fila-ausente"),
    pytest.param(_reporte(_resultado(ERROR_98, EstadoHallazgo.EXTRA_EN_EXCEL)),
                 SIN_CONTRAPARTE + _e3(("HT2", "SEL 311C", ECAP, 31)),
                 "la exención no aplica a este run", id="e3-ya-la-extrae"),
])
def test_la_exencion_no_se_sostiene(
    reporte: dict[str, Any], hallazgos: list[dict[str, Any]], esperado: str
) -> None:
    problemas = errores.exencion_vigente(reporte, E2_FILA_98, hallazgos, ERROR_98)

    assert any(esperado in p for p in problemas), problemas


def _origen_con_etapas(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, modelo: str,
                       hallazgos_e3: list[dict[str, Any]]) -> Path:
    """Una repetición de Alfa con su run de origen (E2 y E3 en disco, como en
    mediciones/<ronda>/runs/<run_id>/)."""
    import json

    from tests.golden import datos

    carpeta = tmp_path / "replay_e4" / "AG1" / "run-alfa"
    monkeypatch.setattr(datos, "MEDICIONES", tmp_path)
    caso = _caso("run-alfa", modelo)
    caso.run_dir.mkdir(parents=True)
    for nombre, contenido in (("etapa2_excel_normalizado.json", E2_FILA_98),
                              ("etapa3_pdf_hallazgos.json", hallazgos_e3)):
        (caso.run_dir / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    monkeypatch.setattr(errores, "REPETICIONES", [carpeta])
    monkeypatch.setattr(errores, "_origen", lambda _: caso)
    return carpeta


@pytest.mark.parametrize("modelo", [SONNET, OPUS])
def test_las_repeticiones_de_e4_aplican_la_exencion_solo_donde_corresponde(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, modelo: str
) -> None:
    """Una repetición de Alfa: con Sonnet, la fila 98 se salta «exento:» y
    pasa al test de la exención; la 107 se exige igual. Con Opus no hay exención."""
    carpeta = _origen_con_etapas(monkeypatch, tmp_path, modelo, SIN_CONTRAPARTE)

    parametros = {p.values[1].fila_excel: p for p in errores._parametros_repeticiones()}
    exentos = errores._parametros_exentos()

    assert sorted(parametros) == [98, 107]
    assert list(parametros[107].marks) == []
    if modelo == SONNET:
        (marca,) = parametros[98].marks
        assert marca.name == "skip" and marca.kwargs["reason"].startswith(
            "exento: causa anterior a E4")
        assert [(p.values, list(p.marks)) for p in exentos] == [((carpeta, ERROR_98), [])]
    else:
        assert list(parametros[98].marks) == []
        (sin_exentos,) = exentos
        assert sin_exentos.marks[0].kwargs["reason"].startswith("exento: ninguna de las 1")


def test_una_repeticion_cuya_e3_tiene_la_contraparte_se_exige(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Revisión del Bloque 24: Alfa 98 con Sonnet, pero la E3 de ESTE origen
    extrajo la contraparte: la repetición debe mostrar el error (sin salto) y no
    entra al test de la exención."""
    _origen_con_etapas(monkeypatch, tmp_path, SONNET,
                       SIN_CONTRAPARTE + _e3(("HT2", "SEL 311C", ECAP, 31)))

    parametros = {p.values[1].fila_excel: p for p in errores._parametros_repeticiones()}
    (sin_exentos,) = errores._parametros_exentos()

    assert list(parametros[98].marks) == [] and list(parametros[107].marks) == []
    assert sin_exentos.marks[0].kwargs["reason"].startswith("exento: ninguna de las 1")


def test_una_repeticion_de_e4_sin_metadata_cuenta_como_incompleta(tmp_path: Path) -> None:
    """Revisión del Bloque 24: `_repetir` escribe metadata.json al final; una
    carpeta sin ella (repetición que falló después de pagar, o a medias) no es
    «sin repeticiones todavía»: el golden la nombra y falla."""
    completa = tmp_path / "replay_e4" / "AG1" / "run-completo"
    a_medias = tmp_path / "replay_e4" / "AG1" / "run-a-medias"
    vacia = tmp_path / "replay_e4" / "AG2" / "run-vacio"
    for carpeta in (completa, a_medias / "etapa4_llm_judge_raw", vacia):
        carpeta.mkdir(parents=True)
    (completa / "metadata.json").write_text('{"modo": "replay_e4"}', encoding="utf-8")
    (a_medias / "etapa4_llm_judge_raw" / "judge_0.json").write_text("{}", encoding="utf-8")
    (tmp_path / "replay_e4" / "AG1" / "nota.txt").write_text("no es una carpeta")

    assert errores.repeticiones_incompletas(tmp_path) == [a_medias, vacia]
    assert errores.repeticiones_incompletas(tmp_path / "no-existe") == []


def test_el_golden_falla_con_una_repeticion_a_medias(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    a_medias = tmp_path / "replay_e4" / "AG1" / "run-a-medias"
    monkeypatch.setattr(errores, "INCOMPLETAS", [a_medias])

    with pytest.raises(AssertionError, match=r"AG1/run-a-medias.*sin metadata\.json"):
        errores.test_ninguna_repeticion_de_e4_quedo_a_medias()
    monkeypatch.setattr(errores, "INCOMPLETAS", [])
    errores.test_ninguna_repeticion_de_e4_quedo_a_medias()


def test_la_exencion_sin_la_fila_en_e2_falla_con_un_mensaje_claro() -> None:
    extra = _reporte(_resultado(ERROR_98, EstadoHallazgo.EXTRA_EN_EXCEL))

    with pytest.raises(LookupError, match="fila 98"):
        errores.exencion_vigente(extra, [], SIN_CONTRAPARTE, ERROR_98)


def _caso(run_id: str, modelo: str = OPUS, subestacion: str = "Alfa",
          **fila: str) -> Caso:
    return Caso("b3", modelo, f"S-E {subestacion} (Auditora Reliable Energy)", run_id, dict(fila))


def test_caso_ignora_el_run_solo_del_checklist(monkeypatch: pytest.MonkeyPatch) -> None:
    completo = _caso("run-completo")
    monkeypatch.setattr(errores, "casos", lambda ronda: [
        completo, _caso("run-solo-checklist", modo="solo_checklist"), _caso("otro", SONNET)])

    assert errores._caso("b3", "Alfa", OPUS) == completo


def test_caso_ambiguo_falla_con_un_mensaje_claro(monkeypatch: pytest.MonkeyPatch) -> None:
    """LookupError y no AssertionError: en B2 el xfail(raises=AssertionError) no
    debe tapar un caso mal resuelto."""
    monkeypatch.setattr(errores, "casos", lambda ronda: [_caso("run-1"), _caso("run-2")])

    with pytest.raises(LookupError, match=r"Alfa.*2 runs.*run-1.*run-2"):
        errores._caso("b3", "Alfa", OPUS)


def test_el_origen_de_una_repeticion_de_e4_se_busca_en_las_evaluaciones() -> None:
    origen = _caso("run-origen")
    candidatos = [_caso("otro", SONNET), origen]

    assert errores.caso_de_origen("run-origen", candidatos) == origen
    with pytest.raises(LookupError, match="no está en ninguna evaluación"):
        errores.caso_de_origen("run-desconocido", candidatos)
    with pytest.raises(LookupError, match="más de una"):
        errores.caso_de_origen("run-origen", [origen, origen])


@pytest.mark.parametrize(("ronda", "con_comparador", "esperado"), [
    pytest.param("b2", {("Alfa", OPUS), ("Gamma", OPUS)}, None, id="evalua-un-caso"),
    pytest.param("b3", {("Gamma", OPUS)}, "exento: b3 solo Gamma (M63)",
                 id="declarada-sin-casos"),
    pytest.param("b3s", set(), "exento: b3s es solo del checklist", id="solo-checklist"),
    pytest.param("b4", {("Gamma", OPUS)}, "b4 corrió el comparador sin ninguno",
                 id="no-declarada"),
    pytest.param("b3", {("Añañuca", SONNET)}, "b3 está en RONDAS_SIN_CASOS pero evalúa",
                 id="declaracion-vencida"),
])
def test_cobertura_de_cada_ronda(
    ronda: str, con_comparador: set[tuple[str, str]], esperado: str | None
) -> None:
    motivo = errores.cobertura(ronda, con_comparador)

    if esperado is None:
        assert motivo is None
    else:
        assert motivo is not None and motivo.startswith(esperado), motivo


# ------------------------------------------------------------ sin clientes reales


def test_ningun_test_crea_un_cliente_real() -> None:
    from comparador.llm import client, embeddings

    # embeddings.py importó get_client por nombre: su referencia es otra.
    for crear in (client.get_client, client.get_client_anthropic,
                  embeddings.get_client):  # type: ignore[attr-defined]
        with pytest.raises(pytest.fail.Exception, match="cliente real"):
            crear()


def _gt_por_defecto() -> dict[str, Path]:
    """GT_DIR_DEFAULT de cada módulo que lo tiene (lo importan por nombre)."""
    import sys

    from comparador import evaluar_comparador, evaluar_lote, reproducir_e4  # noqa: F401

    return {nombre: modulo.GT_DIR_DEFAULT for nombre, modulo in list(sys.modules.items())
            if nombre.startswith("comparador") and hasattr(modulo, "GT_DIR_DEFAULT")}


@pytest.fixture(scope="module")
def visto_desde_un_fixture_de_modulo() -> dict[str, Any]:
    """Corre antes que los fixtures de función: lo que ve un fixture de módulo
    (como el ensayo de B3) al crear un cliente o buscar los GT por defecto."""
    from comparador.llm import client, embeddings

    clientes = []
    for crear in (client.get_client, client.get_client_anthropic,
                  embeddings.get_client):  # type: ignore[attr-defined]
        try:
            crear()
        except pytest.fail.Exception as exc:
            clientes.append(str(exc))
        else:
            clientes.append("se creó un cliente real")
    return {"clientes": clientes, "gt": _gt_por_defecto()}


def test_la_guarda_cubre_los_fixtures_de_modulo(
    visto_desde_un_fixture_de_modulo: dict[str, Any]
) -> None:
    clientes = visto_desde_un_fixture_de_modulo["clientes"]
    assert len(clientes) == 3
    assert all("cliente real de un proveedor" in c for c in clientes), clientes


def test_ningun_test_lee_los_gt_privados_por_defecto(
    visto_desde_un_fixture_de_modulo: dict[str, Any]
) -> None:
    """Sin --gt-comparador / --gt-dir, evaluar_lote, reproducir_e4 y
    evaluar_comparador buscan en mediciones/gt/comparador (datos privados)."""
    from comparador.rutas import ruta_dentro_de

    privados = ROOT / "mediciones"
    for gt in (visto_desde_un_fixture_de_modulo["gt"], _gt_por_defecto()):
        assert {"comparador.evaluar_comparador", "comparador.evaluar_lote",
                "comparador.reproducir_e4"} <= set(gt)
        dentro = {nombre: ruta for nombre, ruta in gt.items() if ruta_dentro_de(ruta, privados)}
        assert not dentro


def test_los_temporales_de_los_tests_que_pasan_no_se_conservan(
    pytestconfig: pytest.Config,
) -> None:
    """Los golden copian datos privados al tmp_path (reportes, raw de los jueces
    con los prompts): pytest conserva por defecto los de las 3 últimas sesiones."""
    assert pytestconfig.getini("tmp_path_retention_policy") == "failed"


# ------------------------------------------------- golden limitados al inventario (M39)


def test_una_carpeta_nueva_en_informes_reales_no_rompe_los_golden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Los golden usan solo los informes medidos (inventario_informes.json): una
    carpeta nueva, completa o incompleta, no los rompe ni entra en sus casos."""
    import json

    from tests.golden import datos

    informes = tmp_path / "informes"
    for carpeta in ("S-E Beta (Auditora Ensaut)", "S-E Eta (Auditora Ensaut)",
                    "S-E Nueva (Auditora Ensaut)"):
        (informes / carpeta).mkdir(parents=True)
        for archivo in ("Informe.pdf", "Tabla de Hallazgos.xlsx"):
            (informes / carpeta / archivo).write_bytes(b"x")
    (informes / "S-E Incompleta (Auditora Ensaut)").mkdir()
    mediciones = tmp_path / "mediciones"
    mediciones.mkdir()
    (mediciones / "inventario_informes.json").write_text(
        json.dumps([{"carpeta": "S-E Beta (Auditora Ensaut)"}]), encoding="utf-8")
    monkeypatch.setattr(datos, "INFORMES", informes)
    monkeypatch.setattr(datos, "HAY_INFORMES", True)
    monkeypatch.setattr(datos, "MEDICIONES", mediciones)
    datos.casos_informes.cache_clear()
    try:
        # Eta tiene carpeta, pero no está en este inventario medido.
        assert list(datos.casos_informes()) == ["Beta"]
    finally:
        datos.casos_informes.cache_clear()
    assert datos.subestacion("S-E Nueva (Auditora Ensaut)") is None
    assert datos.subestacion("S-E Añañuca (Auditora Reliable Energy)") == "Añañuca"


@pytest.mark.parametrize("planillas", [
    pytest.param(["CheckList A.xlsx", "CheckList B.xlsx"], id="dos-planillas"),
    pytest.param(["CheckList A.xlsx", "~$CheckList A.xlsx"], id="bloqueo-de-excel"),
])
def test_una_carpeta_fuera_del_inventario_con_dos_planillas_no_rompe_los_golden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, planillas: list[str]
) -> None:
    """descubrir_casos corta ante dos planillas en una carpeta: los golden solo
    recorren las carpetas del inventario medido, así que una carpeta ajena (o
    la planilla abierta en Excel, con su «~$») no los rompe."""
    import json

    from tests.golden import datos

    informes = tmp_path / "informes"
    for carpeta, archivos in (
        ("S-E Beta (Auditora Ensaut)", ["Informe.pdf", "Tabla de Hallazgos.xlsx"]),
        ("S-E Nueva (Auditora Ensaut)", ["Informe.pdf", "Tabla de Hallazgos.xlsx", *planillas]),
    ):
        (informes / carpeta).mkdir(parents=True)
        for archivo in archivos:
            (informes / carpeta / archivo).write_bytes(b"x")
    mediciones = tmp_path / "mediciones"
    mediciones.mkdir()
    (mediciones / "inventario_informes.json").write_text(
        json.dumps([{"carpeta": "S-E Beta (Auditora Ensaut)"}]), encoding="utf-8")
    monkeypatch.setattr(datos, "INFORMES", informes)
    monkeypatch.setattr(datos, "HAY_INFORMES", True)
    monkeypatch.setattr(datos, "MEDICIONES", mediciones)
    datos.casos_informes.cache_clear()
    try:
        assert list(datos.casos_informes()) == ["Beta"]
    finally:
        datos.casos_informes.cache_clear()
