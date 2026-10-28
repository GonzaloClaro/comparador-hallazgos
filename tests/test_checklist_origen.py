"""Origen y estado de cada criterio del checklist (M66, PD53; Bloque 23, E9). Sin API.

Cada punto de checklist_puntos.yaml lleva un bloque `origen`, fuera del prompt:
si el criterio relaja el enunciado oficial, las preguntas abiertas al equipo
revisor que lo afectan y la historia cronológica de quién lo fijó. El riesgo que
vigila este archivo es el sello falso: dar por confirmado un criterio que el
equipo revisor no escribió (lección del 2026-10-17 en tasks/lessons.md: un ✓
sobre un texto que redactamos no es un criterio firme).
"""

from __future__ import annotations

import copy
import re
import subprocess
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from comparador.etapa0_checklist import RUTA_PUNTOS, ChecklistConfigError, cargar_puntos
from comparador.llm.prompts import user_checklist

ROOT = Path(__file__).resolve().parents[1]

TIPOS = {
    "literal_equipo",
    "aprobado_sobre_texto_nuestro",
    "inferido_planillas",
    "propuesto",
    "base_checklist_general",
}
# Fuera del repo (privadas, nunca en un clon): se aceptan por prefijo, sin exigir que existan.
PREFIJOS_PRIVADOS = ("checklist_general/", "mediciones/", "informes_reales/")
# Criterios ajustados el 2026-10-16 por inferencia desde las planillas (cabecera del YAML).
INFERIDOS_2026_10_16 = (14, 17, 18, 20, 22, 26, 27, 29, 35, 36)
# Criterio que pide menos que el enunciado oficial sin que nadie lo decidiera (P4b de la v3).
PUNTOS_P4B = (2, 5, 7, 8, 11, 12, 13, 15, 21)
# Puntos que una pregunta de la v3 nombra sin que esa pregunta vaya en su origen: menciones
# informativas, cada una con su motivo. Toda otra mención exige la pregunta en el origen.
_P7 = "P7 pregunta qué puntos revisar siempre a mano; el criterio de cada uno va en su pregunta"
_P24 = "la herramienta divide el ítem 1.4 en los puntos 3, 4 y 5; P24 es solo sobre el 3"
MENCIONES_SIN_PREGUNTA: dict[tuple[str, int], str] = {
    ("P4", 28): "la desviación punto a punto «va en el 28»: remite, no pregunta",
    ("P4b", 3): "«el código del informe es el punto 3 y va en P24»",
    ("P5", 17): "contexto: el 18 usa las tablas de corrientes que revisa el 17",
    ("P6", 10): "«El punto 10, esquemas adaptativos, va aparte en P2»",
    **{("P7", n): _P7 for n in (6, 10, 17, 22, 23, 30, 32)},
    ("P9", 25): "ejemplo de cómo está escrita la regla general: «como el 25 de P21»",
    ("P9", 36): "ejemplo: para la reconexión (punto 36) se pide declararla en los hallazgos",
    ("P12", 38): "contexto: la inspección visual ya la revisa el 38; la pregunta es sobre el 35",
    ("P24", 4): _P24,
    ("P24", 5): _P24,
}
RUTA_PREGUNTAS_V3 = ROOT / "tasks" / "equipo" / "preguntas_v3.md"
_TITULO_V3 = re.compile(r"^### (?:★ )?(?P<p>P\d+b?) · (?P<resto>.*)$", re.MULTILINE)
_PREGUNTA_V3 = re.compile(r"^### (?:★ )?(?P<p>P\d+b?) · (?P<texto>.*?)(?=^##|\Z)",
                          re.MULTILINE | re.DOTALL)
# Cómo nombra la v3 un punto: «Punto 22», «puntos 26 a 28 y 32», «en el 30 y el 31» (no «el 17
# de octubre» ni «el 5.2», que es un ítem), una fila «| 14 (4.5) |» o «**6** (ítem 2.3».
_MESES = "enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre"
_PUNTOS = re.compile(r"[Pp]untos? (?P<lista>\d+(?:(?:, | y | a )\d+)*)")
_EL_N = re.compile(rf"\b[Ee]l (?P<n>\d{{1,2}})\b(?![.,]\d| de (?:{_MESES}))")
_FILA = re.compile(r"^\| (?P<n>\d{1,2}) \(\d+\.\d+\) \||\*\*(?P<b>\d{1,2})\*\* \(ítem",
                   re.MULTILINE)

SELLO_FALSO = "confirmado: true solo con tipo literal_equipo"
_RUTA = re.compile(r"(?P<ruta>[\w./-]+)(?P<resto>.*)", re.DOTALL)
_COMMIT_EN_REFERENCIA = re.compile(r"commit (?P<hex>[0-9a-f]{7,40})\b")


def _crudo() -> dict[str, Any]:
    datos: dict[str, Any] = yaml.safe_load(RUTA_PUNTOS.read_text(encoding="utf-8"))
    return datos


def _historias() -> list[tuple[int, dict[str, Any]]]:
    return [(p["numero"], e) for p in cargar_puntos() for e in p["origen"]["historia"]]


def _origen(numero: int) -> dict[str, Any]:
    (punto,) = [p for p in cargar_puntos() if p["numero"] == numero]
    origen: dict[str, Any] = punto["origen"]
    return origen


def _cargar_mutado(tmp_path: Path, mutar: Callable[[dict[str, Any]], None]) -> None:
    """Carga una copia del YAML real con `mutar` aplicado a su lista de puntos."""
    datos = copy.deepcopy(_crudo())
    mutar(datos)
    ruta = tmp_path / "puntos.yaml"
    ruta.write_text(yaml.safe_dump(datos, allow_unicode=True, sort_keys=False), encoding="utf-8")
    cargar_puntos(ruta)


def _entrada(datos: dict[str, Any], numero: int, i: int = 0) -> dict[str, Any]:
    entrada: dict[str, Any] = datos["puntos"][numero - 1]["origen"]["historia"][i]
    return entrada


# ------------------------------------------------------------ el YAML real


def test_los_38_tienen_origen_con_historia() -> None:
    puntos = cargar_puntos()
    sin_origen = [p["numero"] for p in puntos if not p.get("origen", {}).get("historia")]
    assert sin_origen == []


def test_tipos_y_fechas_validos_en_orden_cronologico() -> None:
    for punto in _crudo()["puntos"]:
        historia = punto["origen"]["historia"]
        for entrada in historia:
            assert entrada["tipo"] in TIPOS, (punto["numero"], entrada["tipo"])
            # Entre comillas: una fecha sin comillas llega como date, no como str.
            assert isinstance(entrada["fecha"], str), (punto["numero"], entrada["fecha"])
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", entrada["fecha"])
            date.fromisoformat(entrada["fecha"])
        fechas = [e["fecha"] for e in historia]
        assert fechas == sorted(fechas), punto["numero"]


@pytest.mark.skipif(
    not (ROOT / "tasks").is_dir(),
    reason="requiere material interno no publicado (tasks/)")
def test_referencias_apuntan_a_rutas_del_repo_o_privadas_conocidas() -> None:
    malas = []
    for numero, entrada in _historias():
        for parte in entrada["referencia"].split("; "):
            if _COMMIT_EN_REFERENCIA.match(parte) or parte.startswith(PREFIJOS_PRIVADOS):
                continue
            m = _RUTA.fullmatch(parte)
            assert m is not None
            ruta, resto = m["ruta"], m["resto"]
            # Tras la ruta solo va un ancla: ":12-14", ", pregunta 4", " (…)" o "#…".
            ancla_valida = resto == "" or resto.startswith((":", ",", " (", "#"))
            if not ancla_valida or not (ROOT / ruta).exists():
                malas.append((numero, parte))
    assert malas == []


def test_commits_existen_en_git() -> None:
    if not (ROOT / ".git").exists():
        pytest.skip("sin .git (copia sin historia): no se pueden comprobar los commits")
    commits = {e["commit"] for _, e in _historias() if e["commit"]}
    commits |= {
        m["hex"] for _, e in _historias()
        for m in _COMMIT_EN_REFERENCIA.finditer(e["referencia"])
    }
    assert commits
    faltantes = [
        c for c in sorted(commits)
        if subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--verify", "--quiet", f"{c}^{{commit}}"],
            capture_output=True, check=False,
        ).returncode != 0
    ]
    assert faltantes == []


def test_confirmado_solo_literal_del_equipo_con_respuesta_escrita() -> None:
    sellos_falsos = [
        (numero, entrada["tipo"], entrada["referencia"])
        for numero, entrada in _historias()
        if entrada["confirmado"] and not (
            entrada["tipo"] == "literal_equipo"
            and re.match(r"tasks/equipo/respuestas_[\w-]+\.md\b", entrada["referencia"])
        )
    ]
    assert sellos_falsos == []


@pytest.mark.parametrize("numero", INFERIDOS_2026_10_16)
def test_inferidos_el_2026_10_16_figuran_sin_confirmar(numero: int) -> None:
    inferidos = [
        e for e in _origen(numero)["historia"]
        if e["tipo"] == "inferido_planillas" and e["fecha"] == "2026-10-16"
    ]
    assert inferidos
    assert not any(e["confirmado"] for e in inferidos)


@pytest.mark.parametrize("numero", (17, 18))
def test_17_y_18_no_tienen_ninguna_entrada_confirmada(numero: int) -> None:
    # Un ✓ sobre nuestra opción (b) y una respuesta a una descripción equivocada del 18:
    # ninguna fuente del equipo revisor respalda estos criterios con sus palabras.
    historia = _origen(numero)["historia"]
    assert not any(e["confirmado"] for e in historia)
    assert any(e["tipo"] == "aprobado_sobre_texto_nuestro" for e in historia)


def test_transmitido_por_el_usuario_queda_dicho_en_la_nota() -> None:
    # Decisión del usuario 2026-10-24: lo que transmitió del equipo revisor el 2026-10-17
    # (respuestas_v3_celdas.md) es literal_equipo confirmado, y la nota lo dice.
    entradas = [
        (numero, e) for numero, e in _historias()
        if e["referencia"].startswith("tasks/equipo/respuestas_v3_celdas.md") and e["confirmado"]
    ]
    assert {numero for numero, _ in entradas} >= {22, 23}
    for _, entrada in entradas:
        assert "transmitido por el usuario el 2026-10-17" in entrada["nota"]


def _titulos_v3() -> dict[str, str]:
    """Pregunta de la v3 → resto de su título («### [★ ]P6 · …»)."""
    texto = RUTA_PREGUNTAS_V3.read_text(encoding="utf-8")
    return {m["p"]: m["resto"] for m in _TITULO_V3.finditer(texto)}


@pytest.mark.skipif(
    not (ROOT / "tasks").is_dir(),
    reason="requiere material interno no publicado (tasks/)")
def test_preguntas_del_origen_existen_en_la_v3() -> None:
    titulos = _titulos_v3()
    faltan = [
        (p["numero"], pregunta) for p in cargar_puntos()
        for pregunta in p["origen"]["preguntas"] if pregunta not in titulos
    ]
    assert faltan == []


def _puntos_de_la_lista(lista: str) -> set[int]:
    """«26 a 28 y 32» → {26, 27, 28, 32}."""
    puntos: set[int] = set()
    for parte in re.split(r", | y ", lista):
        desde, _, hasta = parte.partition(" a ")
        puntos |= set(range(int(desde), int(hasta or desde) + 1))
    return puntos


def _puntos_nombrados_en_la_v3() -> set[tuple[str, int]]:
    """(pregunta, punto) por cada punto que nombra una pregunta, en el título o el cuerpo."""
    nombrados: set[tuple[str, int]] = set()
    for m in _PREGUNTA_V3.finditer(RUTA_PREGUNTAS_V3.read_text(encoding="utf-8")):
        texto = m["texto"]
        puntos = {n for x in _PUNTOS.finditer(texto) for n in _puntos_de_la_lista(x["lista"])}
        puntos |= {int(x["n"]) for x in _EL_N.finditer(texto)}
        puntos |= {int(x["n"] or x["b"]) for x in _FILA.finditer(texto)}
        nombrados |= {(m["p"], n) for n in puntos if 1 <= n <= 38}
    return nombrados


@pytest.mark.skipif(
    not (ROOT / "tasks").is_dir(),
    reason="requiere material interno no publicado (tasks/)")
def test_puntos_que_nombra_cada_pregunta_la_llevan_en_el_origen() -> None:
    # Cada punto que una pregunta nombra, en el título o en el cuerpo, la lleva en su origen
    # o figura en MENCIONES_SIN_PREGUNTA con su motivo; ninguna excepción sobra ni está en el
    # origen. Y al revés: ninguna pregunta en un punto que no nombra (PD68, D4: P6 no va en
    # 37 ni 38). Se leen todas las preguntas, también las «Sobre la herramienta».
    nombrados = _puntos_nombrados_en_la_v3()
    en_origen = {
        (pregunta, p["numero"]) for p in cargar_puntos() for pregunta in p["origen"]["preguntas"]
    }
    assert sorted(nombrados - en_origen) == sorted(MENCIONES_SIN_PREGUNTA)
    assert sorted(en_origen - nombrados) == []


def test_p4b_en_los_9_puntos_que_relajan_sin_decision() -> None:
    con_p4b = {p["numero"] for p in cargar_puntos() if "P4b" in p["origen"]["preguntas"]}
    assert con_p4b == set(PUNTOS_P4B)
    assert all(_origen(n)["relaja_enunciado"] for n in PUNTOS_P4B)


def test_user_checklist_identico_con_y_sin_origen() -> None:
    puntos = cargar_puntos()
    sin_origen = [{k: v for k, v in p.items() if k != "origen"} for p in puntos]
    for con_cita in (False, True):
        assert user_checklist(puntos, con_cita) == user_checklist(sin_origen, con_cita)


# ------------------------------------------------------------ el cargador rechaza


def test_clave_desconocida_en_un_punto_falla(tmp_path: Path) -> None:
    def mutar(d: dict[str, Any]) -> None:
        d["puntos"][4]["nota_interna"] = "x"

    with pytest.raises(ChecklistConfigError, match="nota_interna"):
        _cargar_mutado(tmp_path, mutar)


def test_origen_faltante_falla(tmp_path: Path) -> None:
    def mutar(d: dict[str, Any]) -> None:
        del d["puntos"][4]["origen"]

    with pytest.raises(ChecklistConfigError, match="origen"):
        _cargar_mutado(tmp_path, mutar)


def test_campo_desconocido_dentro_del_origen_falla(tmp_path: Path) -> None:
    # p. ej. copiar la `evidencia` del borrador (citas de fuentes privadas).
    def mutar(d: dict[str, Any]) -> None:
        _entrada(d, 1)["evidencia"] = "cita"

    with pytest.raises(
        ChecklistConfigError, match=r"historia\.0\.evidencia\s+Extra inputs are not permitted"
    ):
        _cargar_mutado(tmp_path, mutar)


@pytest.mark.parametrize(("campo", "valor"), [
    ("tipo", "inferido"),
    ("fecha", "2026-13-01"),
    ("fecha", "16-10-2026"),
    ("fecha", date(2026, 10, 16)),
    ("commit", "xyz1234"),
    ("commit", "abc12"),
    ("confirmado", "true"),
    ("referencia", ""),
    ("nota", ""),
])
def test_valores_invalidos_en_la_historia_fallan(tmp_path: Path, campo: str, valor: Any) -> None:
    def mutar(d: dict[str, Any]) -> None:
        _entrada(d, 1)[campo] = valor

    with pytest.raises(ChecklistConfigError, match="punto 1"):
        _cargar_mutado(tmp_path, mutar)


@pytest.mark.parametrize("preguntas", [["4b"], ["P4c"], ["P9/P10"], "P4", ["P4", "P4"]])
def test_preguntas_invalidas_fallan(tmp_path: Path, preguntas: Any) -> None:
    def mutar(d: dict[str, Any]) -> None:
        d["puntos"][0]["origen"]["preguntas"] = preguntas

    with pytest.raises(ChecklistConfigError, match="punto 1"):
        _cargar_mutado(tmp_path, mutar)


def test_historia_fuera_de_orden_falla(tmp_path: Path) -> None:
    def mutar(d: dict[str, Any]) -> None:
        d["puntos"][5]["origen"]["historia"].reverse()

    with pytest.raises(ChecklistConfigError, match="punto 6"):
        _cargar_mutado(tmp_path, mutar)


@pytest.mark.parametrize("tipo", sorted(TIPOS - {"literal_equipo"}))
def test_confirmado_con_otro_tipo_falla(tmp_path: Path, tipo: str) -> None:
    def mutar(d: dict[str, Any]) -> None:
        # Punto 17, entrada del 2026-07-16: el ✓ sobre nuestra opción (b).
        (entrada,) = [e for e in d["puntos"][16]["origen"]["historia"]
                      if e["tipo"] == "aprobado_sobre_texto_nuestro"]
        entrada["tipo"] = tipo
        entrada["confirmado"] = True

    with pytest.raises(ChecklistConfigError, match=SELLO_FALSO):
        _cargar_mutado(tmp_path, mutar)


def test_confirmado_literal_sin_respuesta_escrita_falla(tmp_path: Path) -> None:
    def mutar(d: dict[str, Any]) -> None:
        entrada = _entrada(d, 1)
        entrada.update(tipo="literal_equipo", confirmado=True,
                       referencia="tasks/equipo/preguntas_v3.md, P4")

    with pytest.raises(ChecklistConfigError, match=SELLO_FALSO):
        _cargar_mutado(tmp_path, mutar)
