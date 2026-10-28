"""Errores reales del Excel que la herramienta no deja ver (fila 4.26 de 05_revision_enfoque).

La adjudicación de B2 encontró errores reales del Excel cuya alerta no lleva a
la revisora al error (docs/04_metricas.md §3.7). Cada caso queda como
regresión con claves estables, sin texto de los informes y nunca con el índice
del resultado: fila del Excel, página y clasificación del hallazgo del PDF, y
los campos que deben diferir (los demás deben coincidir sin pasar por una
"redacción distinta" del juez, que podría tapar un par equivocado).

- Alfa, fila 107 (HT2, SEL 387E): con su hallazgo "Verificación ECAP" de la
  pág. 32, difiere solo la calificación. Con Opus quedó con otro hallazgo de la
  misma página.
- Alfa, fila 98 (HT2, SEL 311C): con su "Verificación ECAP" de la pág. 31,
  difiere solo la calificación. Con Sonnet quedó como "extra en Excel".
- Añañuca, fila 39: con la conclusión de coordinación de la pág. 20 (no con el
  rótulo genérico de la pág. 19), difiere la descripción. Escondido con los dos.
  Esa contraparte es una estimación del verificador, no validada por el equipo
  revisor (M27).

En B2 (reportes congelados) los casos escondidos son fallas conocidas: xfail
estricto, solo por la aserción. En las rondas siguientes el test exige que se
vean: una ronda nueva que los siga escondiendo falla, y marcarla es una
decisión consciente. Además, ninguna de esas filas puede salir "coincide" en
ninguna ronda (error escondido). Es una condición necesaria, no suficiente: no
reemplaza adjudicar los "coincide" nuevos de una ronda.

Compuerta (M27): cada ronda con comparador posterior a B2 evalúa al menos uno
de los casos o declara por qué no (RONDAS_SIN_CASOS); las solo del checklist
quedan exentas. Las repeticiones de E4 (`reproducir_e4`, en
mediciones/replay_e4/<etiqueta>/<run_id>/) se verifican sin xfail, salvo lo
que no puede arreglar ningún cambio de E4 (CAUSA_ANTERIOR_A_E4, PD23): Alfa
98 con Sonnet, porque E3 no extrajo la contraparte en el relé de esa fila y E4
nunca cruza relés (invariante 14). La exención depende del run: esa
repetición se salta con su motivo («exento:») solo si la causa sigue en la E3
de su run de origen, y otro test exige que la fila siga a la vista; si la E3
de ese origen tiene la contraparte, la exención no aplica y el caso se exige.
Las repeticiones a medias (sin metadata.json) hacen fallar el golden.

Inversiones conocidas (INVERSIONES; red de seguridad de la asignación global,
encendida por defecto desde el 2026-10-26): Alfa, fila 69 (E7, SEL 451,
pág. 26), donde el Excel invierte el «Cumple» del PDF por «No cumple» (08 CB01
y CB24). B2 la muestra con los dos modelos, pero B1 con Opus (antes de 19e) y
AG1 con Opus (la asignación global antes de V2, PD71) la escondieron como
«coincide». En ninguna ronda ni repetición de E4, también las nuevas, esa fila
puede salir «coincide» (tampoco «coincide · redacción distinta»), ni con la
descripción dada por equivalente por el juez de redacción, ni emparejada sin
la descripción entre sus diferencias (un «difiere» solo en la calificación o
la acción): la inversión está en la descripción. Lo ya ocurrido va a la vista
en INVERSION_ESCONDIDA_CONOCIDA: xfail estricto, con su motivo, y una
declaración sin caso evaluado falla.

La verificación son funciones puras sobre el reporte (probadas con reportes
sintéticos en tests/test_compuerta_golden.py).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from comparador.etapa4_matching import clave_tupla
from comparador.persistence import MODO_SOLO_CHECKLIST
from comparador.reproducir_e4 import MODO_REPLAY_E4
from tests.golden.datos import (
    MEDICIONES,
    Caso,
    casos,
    leer_json,
    requiere_mediciones,
    rondas_con_evaluacion,
)

pytestmark = [pytest.mark.golden, requiere_mediciones]


class ErrorNoMostrado(NamedTuple):
    subestacion: str
    fila_excel: int
    pagina_pdf: int
    clasificacion_pdf: str           # etiqueta genérica del hallazgo del PDF, no texto
    campos: tuple[str, ...]          # los únicos campos que deben diferir
    escondido_en_b2: frozenset[str]  # modelos en los que B2 no lo muestra
    contraparte_validada: bool       # False: estimación del verificador (M27)


ERRORES = (
    ErrorNoMostrado("Alfa", 107, 32, "Verificación ECAP", ("calificacion",),
                    frozenset({"claude-opus-5-5"}), True),
    ErrorNoMostrado("Alfa", 98, 31, "Verificación ECAP", ("calificacion",),
                    frozenset({"claude-sonnet-5-5"}), True),
    ErrorNoMostrado("Añañuca", 39, 20, "Ver. Coord. de Protecciones", ("descripcion",),
                    frozenset({"claude-sonnet-5-5", "claude-opus-5-5"}), False),
)
MODELOS = ("claude-sonnet-5-5", "claude-opus-5-5")
# (subestación, fila del Excel, modelo) → por qué una repetición de E4 no puede
# mostrar ese error: su causa está antes de E4. Solo vale mientras siga
# (exencion_vigente); lo no declarado se exige.
CAUSA_ANTERIOR_A_E4 = {
    ("Alfa", 98, "claude-sonnet-5-5"): (
        "causa anterior a E4: en B2, E3 atribuyó la «Verificación ECAP» de la pág. 31 al "
        "SEL 387E, no al SEL 311C; la tupla (HT2, SEL 311C) no tiene contraparte y E4 nunca "
        "cruza relés (inv. 14)"),
}
# Rondas posteriores a B2 con comparador que no evalúan ninguno de los casos,
# con su motivo. Lo no declarado falla.
RONDAS_SIN_CASOS = {"b3": "solo Gamma (M63)"}
# B2 y las rondas posteriores que tengan su evaluación guardada.
RONDAS = [r for r in rondas_con_evaluacion() if int(re.sub(r"\D", "", r)) >= 2]


# ------------------------------------------------------------ verificación (pura)


def resultados_de_la_fila(reporte: dict[str, Any], fila: int) -> list[dict[str, Any]]:
    return [
        r for r in reporte["resultados"]
        if ((r.get("hallazgo_excel") or {}).get("evidencia") or {}).get("fila_excel") == fila
    ]


def _pagina(resultado: dict[str, Any]) -> int | None:
    return ((resultado.get("hallazgo_pdf") or {}).get("evidencia") or {}).get("pagina_pdf")


def escondido(reporte: dict[str, Any], error: ErrorNoMostrado) -> list[str]:
    """Lo que esconde el error en cualquier ronda: la fila no aparece o sale «coincide»."""
    resultados = resultados_de_la_fila(reporte, error.fila_excel)
    if not resultados:
        return [f"la fila {error.fila_excel} no aparece en el reporte"]
    return [f"la fila {error.fila_excel} sale «coincide» con la pág. {_pagina(r)}"
            for r in resultados if r["estado"] == "coincide"]


def sin_contraparte(reporte: dict[str, Any], error: ErrorNoMostrado) -> list[str]:
    """Por qué la alerta no lleva al error con su contraparte (vacío: lleva): un
    único resultado «difiere» con el hallazgo del PDF del caso (página y
    clasificación), solo en los campos del caso y sin campos dados por
    equivalentes por el juez de redacción."""
    resultados = resultados_de_la_fila(reporte, error.fila_excel)
    if len(resultados) != 1:
        return [f"la fila {error.fila_excel} aparece {len(resultados)} veces (se espera 1)"]
    (resultado,) = resultados
    pdf = resultado.get("hallazgo_pdf") or {}
    visto = (resultado["estado"], _pagina(resultado), pdf.get("clasificacion"),
             tuple(d["campo"] for d in resultado["diferencias"]))
    esperado = ("difiere", error.pagina_pdf, error.clasificacion_pdf, error.campos)
    problemas = [] if visto == esperado else [f"(estado, página, clasificación, campos) = "
                                              f"{visto}, se espera {esperado}"]
    # Los demás campos coinciden por sí mismos, no por una "redacción distinta" del juez.
    equivalentes = sorted({e["campo"] for e in resultado.get("equivalencias_redaccion") or []})
    if equivalentes:
        problemas.append(f"campos dados por equivalentes por el juez: {equivalentes}")
    return problemas


def sin_alerta_a_la_pagina(reporte: dict[str, Any], error: ErrorNoMostrado) -> list[str]:
    """Exigencia mínima: alguna alerta de la fila lleva a la página del caso."""
    if any(r["estado"] != "coincide" and _pagina(r) == error.pagina_pdf
           for r in resultados_de_la_fila(reporte, error.fila_excel)):
        return []
    return [f"ninguna alerta de la fila {error.fila_excel} lleva a la pág. {error.pagina_pdf}"]


def verificar_error(reporte: dict[str, Any], error: ErrorNoMostrado) -> list[str]:
    """Todo lo que se exige en una repetición de E4 (vacío: el error se ve). Sin
    contraparte validada, basta con que la alerta lleve a su página."""
    exigencia = sin_contraparte if error.contraparte_validada else sin_alerta_a_la_pagina
    return escondido(reporte, error) + exigencia(reporte, error)


def exencion_e4(error: ErrorNoMostrado, modelo: str) -> str | None:
    """Por qué una repetición de E4 con ese modelo no puede mostrar el error
    (None: debe mostrarlo)."""
    return CAUSA_ANTERIOR_A_E4.get((error.subestacion, error.fila_excel, modelo))


def marcas_repeticion(motivo: str | None) -> list[pytest.MarkDecorator]:
    """Las marcas del caso en una repetición de E4: un salto «exento:» con el
    motivo de la exención que aplica al run (exencion_del_run); sin ella,
    ninguna (se exige)."""
    return [] if motivo is None else [pytest.mark.skip(reason=f"exento: {motivo}")]


def causa_anterior_vigente(hallazgos_e3: list[dict[str, Any]], pano: str, rele: str,
                           error: ErrorNoMostrado) -> bool:
    """La causa anterior a E4 sigue: E3 no extrajo ningún hallazgo de la
    clasificación del caso en la tupla (paño, relé) de la fila, normalizada como
    en E4 (otra grafía del relé es la misma tupla). Con cualquier página: si E3
    la extrae, aunque sea con otra, E4 ya tiene con qué emparejarla."""
    tupla = clave_tupla(pano, rele)
    return not any(clave_tupla(h["pano"], h["rele"]) == tupla
                   and h.get("clasificacion") == error.clasificacion_pdf for h in hallazgos_e3)


def tuplas_de_la_fila(hallazgos_e2: list[dict[str, Any]], fila: int) -> list[tuple[str, str]]:
    """Las tuplas (paño, relé) de la fila del Excel según E2 (una fila con
    varios paños se desdobla en varias)."""
    tuplas = sorted({(h["pano"], h["rele"]) for h in hallazgos_e2
                     if (h.get("evidencia") or {}).get("fila_excel") == fila})
    if not tuplas:
        raise LookupError(f"la fila {fila} no está en la Etapa 2 del run")
    return tuplas


def exencion_del_run(error: ErrorNoMostrado, modelo: str, hallazgos_e2: list[dict[str, Any]],
                     hallazgos_e3: list[dict[str, Any]]) -> str | None:
    """La exención declarada (exencion_e4), aplicada a un run: solo si su causa
    sigue en la E3 de ese run, en cada tupla de la fila. La declaración va por
    (subestación, fila, modelo), pero otro run de esa combinación puede haber
    extraído la contraparte: entonces no aplica y el caso se exige (None)."""
    motivo = exencion_e4(error, modelo)
    if motivo is None or not all(
            causa_anterior_vigente(hallazgos_e3, pano, rele, error)
            for pano, rele in tuplas_de_la_fila(hallazgos_e2, error.fila_excel)):
        return None
    return motivo


def exencion_vigente(reporte: dict[str, Any], hallazgos_e2: list[dict[str, Any]],
                     hallazgos_e3: list[dict[str, Any]], error: ErrorNoMostrado) -> list[str]:
    """Por qué la exención ya no se sostiene (vacío: se sostiene): la fila debe
    seguir a la vista en el reporte (aparece y no sale «coincide») y la causa
    seguir en la E3 del run, en cada tupla de la fila."""
    problemas = escondido(reporte, error)
    for pano, rele in tuplas_de_la_fila(hallazgos_e2, error.fila_excel):
        if not causa_anterior_vigente(hallazgos_e3, pano, rele, error):
            problemas.append(
                f"la E3 de este run ya extrae una «{error.clasificacion_pdf}» en ({pano}, "
                f"{rele}): la causa de la fila {error.fila_excel} no es anterior a E4 y la "
                "exención no aplica a este run (su repetición de E4 debe mostrar el error)")
    return problemas


def cobertura(ronda: str, con_comparador: set[tuple[str, str]]) -> str | None:
    """Por qué la ronda no evalúa ninguno de los casos (None: evalúa alguno). Un
    motivo «exento:» es un salto permitido; cualquier otro, un fallo."""
    evaluados = sorted({(e.subestacion, m) for e in ERRORES for m in MODELOS} & con_comparador)
    if ronda in RONDAS_SIN_CASOS:
        if evaluados:
            return f"{ronda} está en RONDAS_SIN_CASOS pero evalúa {evaluados}: quitarla de ahí"
        return f"exento: {ronda} {RONDAS_SIN_CASOS[ronda]}"
    if not con_comparador:
        return f"exento: {ronda} es solo del checklist"
    if not evaluados:
        return (f"{ronda} corrió el comparador sin ninguno de los casos "
                f"({sorted(con_comparador)}): declararla en RONDAS_SIN_CASOS con su motivo")
    return None


def caso_de_origen(run_origen: str, candidatos: list[Caso]) -> Caso:
    """El caso de la ronda cuyo run repitió una repetición de E4."""
    encontrados = [c for c in candidatos if c.run_id == run_origen]
    if not encontrados:
        raise LookupError(f"el run de origen {run_origen} no está en ninguna evaluación")
    if len(encontrados) > 1:
        raise LookupError(f"el run de origen {run_origen} está en más de una evaluación: "
                          f"{[c.ronda for c in encontrados]}")
    return encontrados[0]


# ------------------------------------------------------------ rondas


def _con_comparador(ronda: str) -> set[tuple[str, str]]:
    """(subestación, modelo) que la ronda corrió con el comparador: una ronda
    puede ser parcial (B3: un informe, un modelo) o solo del checklist (B3s)."""
    return {(c.subestacion, c.modelo) for c in casos(ronda)
            if c.fila.get("modo") != MODO_SOLO_CHECKLIST}


def _combinaciones() -> list[tuple[str, ErrorNoMostrado, str]]:
    return [(ronda, error, modelo) for ronda in RONDAS for error in ERRORES for modelo in MODELOS
            if (error.subestacion, modelo) in _con_comparador(ronda)]


def _caso(ronda: str, subestacion: str, modelo: str) -> Caso:
    """El run con comparador de ese informe y modelo (una ronda puede traer
    además un run solo del checklist del mismo informe). LookupError, no
    AssertionError: el xfail de B2 no debe tapar un caso mal resuelto."""
    encontrados = [c for c in casos(ronda) if c.modelo == modelo and c.subestacion == subestacion
                   and c.fila.get("modo") != MODO_SOLO_CHECKLIST]
    if len(encontrados) != 1:
        raise LookupError(f"{ronda}: {subestacion} con {modelo} tiene {len(encontrados)} runs "
                          f"con comparador (se espera 1): {[c.run_id for c in encontrados]}")
    return encontrados[0]


def _reporte(ronda: str, error: ErrorNoMostrado, modelo: str) -> dict[str, Any]:
    reporte: dict[str, Any] = _caso(ronda, error.subestacion, modelo).json("reporte_final.json")
    return reporte


def _parametros() -> list[Any]:
    return [
        pytest.param(
            ronda, error, modelo,
            id=f"{ronda}-{modelo.removeprefix('claude-').split('-')[0]}-"
               f"{error.subestacion}-{error.fila_excel}",
            # raises=AssertionError: solo la aserción puede "fallar como se espera"; un
            # caso no encontrado u otro error rompe el test en vez de quedar escondido.
            marks=[pytest.mark.xfail(strict=True, raises=AssertionError,
                                     reason="escondido en B2 (04 §3.7)")]
            if ronda == "b2" and modelo in error.escondido_en_b2 else [],
        )
        for ronda, error, modelo in _combinaciones()
    ]


@pytest.mark.parametrize(("ronda", "error", "modelo"), _parametros())
def test_el_error_real_se_muestra_con_su_contraparte(
    ronda: str, error: ErrorNoMostrado, modelo: str
) -> None:
    reporte = _reporte(ronda, error, modelo)
    assert resultados_de_la_fila(reporte, error.fila_excel), (
        f"la fila {error.fila_excel} no aparece en el reporte")
    problemas = sin_contraparte(reporte, error)
    assert not problemas, problemas


@pytest.mark.parametrize(
    ("ronda", "error", "modelo"), _combinaciones(),
    ids=lambda v: v if isinstance(v, str) else f"{v.subestacion}-{v.fila_excel}")
def test_ninguna_de_esas_filas_sale_coincide(
    ronda: str, error: ErrorNoMostrado, modelo: str
) -> None:
    problemas = escondido(_reporte(ronda, error, modelo), error)
    assert not problemas, problemas


@pytest.mark.parametrize("ronda", RONDAS)
def test_cada_ronda_evalua_algun_caso_o_declara_por_que_no(ronda: str) -> None:
    motivo = cobertura(ronda, _con_comparador(ronda))
    if motivo is not None and motivo.startswith("exento:"):
        pytest.skip(motivo)
    assert motivo is None, motivo


# ------------------------------------------------------------ repeticiones de E4

REPETICIONES = sorted(
    p.parent for p in MEDICIONES.glob("replay_e4/*/*/metadata.json")
    if leer_json(p).get("modo") == MODO_REPLAY_E4
)


def repeticiones_incompletas(mediciones: Path) -> list[Path]:
    """Las carpetas replay_e4/<etiqueta>/<run_id> sin metadata.json, que
    reproducir_e4 escribe al final: una repetición que falló (quizá después de
    pagar) o quedó a medias. No es «sin repeticiones todavía»."""
    return sorted(p for p in mediciones.glob("replay_e4/*/*")
                  if p.is_dir() and not (p / "metadata.json").is_file())


INCOMPLETAS = repeticiones_incompletas(MEDICIONES)


def _id_repeticion(carpeta: Path) -> str:
    return f"{carpeta.parent.name}-{carpeta.name}"


def _origen(carpeta: Path) -> Caso:
    """El caso repetido, buscado por run_origen en todas las rondas evaluadas."""
    meta = leer_json(carpeta / "metadata.json")
    caso = caso_de_origen(meta["run_origen"], casos(*rondas_con_evaluacion()))
    if meta["modelo_extraccion"] != caso.modelo:
        raise LookupError(f"{_id_repeticion(carpeta)} corrió con {meta['modelo_extraccion']} "
                          f"y su origen {caso.run_id} con {caso.modelo}")
    return caso


def _exento(motivo: str, aridad: int) -> list[Any]:
    """Sin nada que evaluar: un salto «exento:» explícito, no una
    parametrización vacía (que con GOLDEN_OBLIGATORIO falla)."""
    return [pytest.param(*[None] * aridad, marks=pytest.mark.skip(reason=f"exento: {motivo}"),
                         id="sin-repeticiones")]


def _parametros_origen() -> list[Any]:
    if not REPETICIONES:
        return _exento("sin repeticiones de E4 todavía", 1)
    return [pytest.param(carpeta, id=_id_repeticion(carpeta)) for carpeta in REPETICIONES]


def _exencion_de_la_repeticion(caso: Caso, error: ErrorNoMostrado) -> str | None:
    """exencion_del_run con la E2 y la E3 del run de origen (se leen solo si hay
    una exención declarada para la combinación)."""
    if exencion_e4(error, caso.modelo) is None:
        return None
    return exencion_del_run(error, caso.modelo, caso.json("etapa2_excel_normalizado.json"),
                            caso.json("etapa3_pdf_hallazgos.json"))


def _parametros_repeticiones() -> list[Any]:
    if not REPETICIONES:
        return _exento("sin repeticiones de E4 todavía", 2)
    parametros = []
    for carpeta in REPETICIONES:
        try:
            caso = _origen(carpeta)
        except LookupError:
            continue   # lo reporta test_cada_repeticion_de_e4_tiene_su_origen
        parametros += [
            pytest.param(carpeta, error, id=f"{_id_repeticion(carpeta)}-"
                         f"{error.subestacion}-{error.fila_excel}",
                         marks=marcas_repeticion(_exencion_de_la_repeticion(caso, error)))
            for error in ERRORES
            if error.subestacion == caso.subestacion and caso.modelo in MODELOS
        ]
    return parametros or _exento(f"ninguna de las {len(REPETICIONES)} repeticiones de E4 "
                                 "es de Alfa o Añañuca con Sonnet u Opus", 2)


def _parametros_exentos() -> list[Any]:
    """Las repeticiones de E4 a las que aplica una exención de CAUSA_ANTERIOR_A_E4
    (la causa sigue en la E3 de su origen)."""
    if not REPETICIONES:
        return _exento("sin repeticiones de E4 todavía", 2)
    parametros = []
    for carpeta in REPETICIONES:
        try:
            caso = _origen(carpeta)
        except LookupError:
            continue   # lo reporta test_cada_repeticion_de_e4_tiene_su_origen
        parametros += [
            pytest.param(carpeta, error, id=f"{_id_repeticion(carpeta)}-"
                         f"{error.subestacion}-{error.fila_excel}")
            for error in ERRORES
            if error.subestacion == caso.subestacion and _exencion_de_la_repeticion(caso, error)
        ]
    return parametros or _exento(f"ninguna de las {len(REPETICIONES)} repeticiones de E4 cae "
                                 "en CAUSA_ANTERIOR_A_E4", 2)


def test_ninguna_repeticion_de_e4_quedo_a_medias() -> None:
    """Una repetición sin metadata.json no se evalúa (no está en REPETICIONES):
    si se dejara pasar, PD23 se decidiría sin ese caso. Rehacerla en una carpeta
    nueva (los raw pagados quedan en replay_e4.csv como cota inferior)."""
    assert not INCOMPLETAS, [
        f"{p.parent.name}/{p.name}: repetición de E4 sin metadata.json (falló o quedó a "
        "medias): rehacerla en una carpeta nueva" for p in INCOMPLETAS]


@pytest.mark.parametrize("carpeta", _parametros_origen())
def test_cada_repeticion_de_e4_tiene_su_origen(carpeta: Path) -> None:
    caso = _origen(carpeta)
    assert (carpeta / "reporte_final.json").is_file(), f"{caso.run_id}: sin reporte_final.json"


@pytest.mark.parametrize(("carpeta", "error"), _parametros_repeticiones())
def test_la_repeticion_de_e4_deja_ver_el_error(carpeta: Path, error: ErrorNoMostrado) -> None:
    """Sin xfail: «coincide» falla duro; Alfa 98 y 107 exigen la
    contraparte completa; Añañuca 39, que la alerta lleve a la pág. 20. Lo de
    CAUSA_ANTERIOR_A_E4 se salta con su motivo (y lo cubre el test siguiente)."""
    problemas = verificar_error(leer_json(carpeta / "reporte_final.json"), error)
    assert not problemas, problemas


@pytest.mark.parametrize(("carpeta", "error"), _parametros_exentos())
def test_la_exencion_de_la_repeticion_de_e4_se_sostiene(
    carpeta: Path, error: ErrorNoMostrado
) -> None:
    """Lo exento no queda escondido: la fila sigue a la vista (la causa en la
    E3 del run de origen ya la exige _parametros_exentos)."""
    caso = _origen(carpeta)
    problemas = exencion_vigente(leer_json(carpeta / "reporte_final.json"),
                                 caso.json("etapa2_excel_normalizado.json"),
                                 caso.json("etapa3_pdf_hallazgos.json"), error)
    assert not problemas, (caso.run_id, problemas)


def _error(subestacion: str, fila: int) -> ErrorNoMostrado:
    (error,) = [e for e in ERRORES if (e.subestacion, e.fila_excel) == (subestacion, fila)]
    return error


@pytest.mark.parametrize(("subestacion", "fila", "modelo"), sorted(CAUSA_ANTERIOR_A_E4))
def test_la_causa_de_cada_exencion_esta_en_b2(subestacion: str, fila: int, modelo: str) -> None:
    """La exención se sostiene en B2, que es el origen de las repeticiones de
    PD23: con el modelo exento la fila queda a la vista y E3 no tiene la
    contraparte; con un modelo que en B2 sí muestra el error, E3 la extrajo (la
    función distingue los dos casos con los datos reales)."""
    error = _error(subestacion, fila)
    exento = _caso("b2", subestacion, modelo)
    e2 = exento.json("etapa2_excel_normalizado.json")
    assert exencion_vigente(exento.json("reporte_final.json"), e2,
                            exento.json("etapa3_pdf_hallazgos.json"), error) == []
    for otro in MODELOS:
        if otro in error.escondido_en_b2 or (subestacion, otro) not in _con_comparador("b2"):
            continue
        e3 = _caso("b2", subestacion, otro).json("etapa3_pdf_hallazgos.json")
        assert not all(causa_anterior_vigente(e3, pano, rele, error)
                       for pano, rele in tuplas_de_la_fila(e2, fila)), otro


# ------------------------------------------------------------ inversiones que nunca coinciden


class InversionConocida(NamedTuple):
    """Un error real del Excel que invierte el veredicto de un hallazgo del PDF
    («Cumple» → «No cumple») y que alguna ronda o repetición de E4 escondió
    como «coincide». Claves estables, sin texto ni índices: fila del Excel,
    tupla (paño, relé) y página del hallazgo del PDF invertido."""

    subestacion: str
    fila_excel: int
    pano: str
    rele: str
    pagina_pdf: int


INVERSIONES = (
    # Alfa E7, SEL 451, pág. 26: el PDF dice «…INFOTÉCNICA: Cumple» y la fila 69 del
    # Excel, «No cumple» (08 CB01 y CB24; GT del comparador: i068 A, i069 D5, i136 E).
    InversionConocida("Alfa", 69, "E7", "SEL 451", 26),
)
# (fuente, modelo, subestación, fila) → por qué ahí la inversión salió «coincide».
# La fuente es la ronda («b1») o la repetición de E4 («replay_e4/AG1»). Lo que ya
# pasó queda a la vista como xfail estricto con su motivo; lo no declarado se exige.
INVERSION_ESCONDIDA_CONOCIDA = {
    ("b1", "claude-opus-5-5", "Alfa", 69): (
        "B1, antes de 19e (2026-10-17): sin control de polaridad, la descripción coincidió "
        "por similitud (0,88, sobre el umbral) en un par semantico_bajo (08 CB24)"),
    ("replay_e4/AG1", "claude-opus-5-5", "Alfa", 69): (
        "AG1, antes de V2 (PD71): el par que ganó la fila por desplazamiento (0,80) fue al "
        "juez de redacción, que lo dio por «mismo contenido» (08 CB24)"),
}


def resultados_de_la_tupla(reporte: dict[str, Any], inversion: InversionConocida
                           ) -> list[dict[str, Any]]:
    """Los resultados de la fila del caso en su tupla (otra grafía del relé es
    la misma tupla, como en E4)."""
    tupla = clave_tupla(inversion.pano, inversion.rele)
    return [r for r in resultados_de_la_fila(reporte, inversion.fila_excel)
            if clave_tupla(r["hallazgo_excel"]["pano"], r["hallazgo_excel"]["rele"]) == tupla]


def _paginas_pdf_de_la_tupla(reporte: dict[str, Any], tupla: tuple[str, str]) -> set[int]:
    return {pagina for r in reporte["resultados"]
            if (pdf := r.get("hallazgo_pdf")) and clave_tupla(pdf["pano"], pdf["rele"]) == tupla
            and (pagina := _pagina(r)) is not None}


def inversion_escondida(reporte: dict[str, Any], inversion: InversionConocida) -> list[str]:
    """Lo que esconde la inversión (vacío: a la vista). El caso debe
    identificarse con sus claves (la fila en su tupla y algún hallazgo del PDF
    de la tupla en la página) y la inversión está en la descripción: ningún
    resultado de la fila puede salir «coincide» (tampoco «coincide · redacción
    distinta») ni dar la descripción por equivalente con el juez de
    redacción, y si está emparejado con un hallazgo del PDF, la descripción
    tiene que estar entre sus diferencias (un «difiere» solo en la
    calificación o la acción la esconde igual: el equipo revisor revisaría
    eso). La fila sin par («extra en Excel») queda a la vista. Condición
    necesaria, no suficiente: el par puede seguir equivocado, pero a la
    vista."""
    donde = f"la fila {inversion.fila_excel} de ({inversion.pano}, {inversion.rele})"
    resultados = resultados_de_la_tupla(reporte, inversion)
    if not resultados:
        return [f"{donde} no aparece en el reporte"]
    problemas = []
    if inversion.pagina_pdf not in _paginas_pdf_de_la_tupla(
            reporte, clave_tupla(inversion.pano, inversion.rele)):
        problemas.append(f"ningún hallazgo del PDF de ({inversion.pano}, {inversion.rele}) está "
                         f"en la pág. {inversion.pagina_pdf}: el caso ya no se identifica")
    for r in resultados:
        equivalentes = {e["campo"] for e in r.get("equivalencias_redaccion") or []}
        con = f"con la pág. {_pagina(r)}"
        if r["estado"] == "coincide":
            redaccion = " · redacción distinta" if equivalentes else ""
            problemas.append(f"{donde} sale «coincide{redaccion}» {con}")
        elif "descripcion" in equivalentes:
            problemas.append(f"{donde} sale «{r['estado']}» {con}, con la descripción dada por "
                             "equivalente por el juez de redacción")
        elif r.get("hallazgo_pdf") and "descripcion" not in {
                d["campo"] for d in r.get("diferencias") or []}:
            problemas.append(f"{donde} sale «{r['estado']}» {con} sin la descripción entre las "
                             "diferencias")
    return problemas


def _fuentes_con_la_inversion(inversion: InversionConocida) -> list[tuple[str, str, Path]]:
    """(fuente, modelo, reporte) de cada run con comparador de la subestación en
    las rondas evaluadas (un run que falló no entrega reporte: no esconde nada)
    y de cada repetición de E4 de un run suyo."""
    fuentes = [(c.ronda, c.modelo, c.run_dir / "reporte_final.json")
               for ronda in rondas_con_evaluacion() for c in casos(ronda)
               if c.subestacion == inversion.subestacion
               and c.fila.get("modo") != MODO_SOLO_CHECKLIST and not c.tiene("error.json")]
    for carpeta in REPETICIONES:
        try:
            caso = _origen(carpeta)
        except LookupError:
            continue   # lo reporta test_cada_repeticion_de_e4_tiene_su_origen
        if caso.subestacion == inversion.subestacion:
            fuentes.append((f"replay_e4/{carpeta.parent.name}", caso.modelo,
                            carpeta / "reporte_final.json"))
    return fuentes


def _combinaciones_inversion() -> list[tuple[str, str, Path, InversionConocida]]:
    return [(fuente, modelo, reporte, inversion) for inversion in INVERSIONES
            for fuente, modelo, reporte in _fuentes_con_la_inversion(inversion)]


def marcas_inversion(fuente: str, modelo: str, inversion: InversionConocida
                     ) -> list[pytest.MarkDecorator]:
    """Lo declarado en INVERSION_ESCONDIDA_CONOCIDA: xfail estricto, solo por la
    aserción (si deja de fallar, hay que quitar la declaración); lo demás se exige."""
    motivo = INVERSION_ESCONDIDA_CONOCIDA.get(
        (fuente, modelo, inversion.subestacion, inversion.fila_excel))
    return [] if motivo is None else [
        pytest.mark.xfail(strict=True, raises=AssertionError, reason=motivo)]


def _parametros_inversion() -> list[Any]:
    parametros = [
        pytest.param(reporte, inversion, id=f"{fuente.removeprefix('replay_e4/')}-"
                     f"{modelo.removeprefix('claude-').split('-')[0]}-"
                     f"{inversion.subestacion}-{inversion.fila_excel}",
                     marks=marcas_inversion(fuente, modelo, inversion))
        for fuente, modelo, reporte, inversion in _combinaciones_inversion()
    ]
    return parametros or _exento("ninguna ronda ni repetición de E4 trae las subestaciones de "
                                 "INVERSIONES", 2)


@pytest.mark.parametrize(("reporte", "inversion"), _parametros_inversion())
def test_la_inversion_nunca_sale_coincide(reporte: Path, inversion: InversionConocida) -> None:
    """En ninguna ronda ni repetición de E4 (también las nuevas): lo ya ocurrido
    va declarado, con su motivo, en INVERSION_ESCONDIDA_CONOCIDA."""
    problemas = inversion_escondida(leer_json(reporte), inversion)
    assert not problemas, problemas


def test_cada_inversion_escondida_declarada_tiene_su_caso() -> None:
    """Una declaración que no corresponde a ninguna fuente evaluada no tapa
    nada y confunde: se quita."""
    evaluadas = {(fuente, modelo, inversion.subestacion, inversion.fila_excel)
                 for fuente, modelo, _, inversion in _combinaciones_inversion()}
    sobran = sorted(set(INVERSION_ESCONDIDA_CONOCIDA) - evaluadas)
    assert not sobran, f"declaradas sin caso evaluado: {sobran}"
