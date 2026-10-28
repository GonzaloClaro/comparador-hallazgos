"""Protege la regla 19d en los textos que lee el modelo del checklist (sin API).

Regla 19d (CLAUDE.md, el equipo revisor 2026-07-16 y 2026-10-17): una deficiencia levantada
como hallazgo hace cumplir el punto, sin excepciones. Dos veces se coló una
excepción en un texto que lee el modelo (hint 22 en B2; la excepción del
punto 23 en REGLAS_TRAMO_CHECKLIST, ver tasks/lessons.md): este test busca
patrones acotados de excepción en los 38 criterios (donde_buscar), en
SYSTEM_CHECKLIST, en REGLAS_TRAMO_CHECKLIST y en REGLA_CITA_CHECKLIST.

Protege la 19d en la dirección barata (que no se agreguen excepciones). No
valida que los criterios sean correctos ni controla relajaciones: eso necesita
el origen de cada criterio (fila 8.26 de docs/05_revision_enfoque.md).
"""

from __future__ import annotations

import re
import unicodedata

import pytest

from comparador.etapa0_checklist import REGLAS_TRAMO_CHECKLIST, cargar_puntos
from comparador.llm.prompts import REGLA_CITA_CHECKLIST, SYSTEM_CHECKLIST

# Frases que hacen fallar un punto aunque la deficiencia esté levantada como hallazgo.
PATRONES_EXCEPCION = (
    r"resultado manda",
    r"no basta para cumplir",
    # Un "no cumple" seguido de "aunque ... esté levantado" (no la regla: "CUMPLE aunque...").
    r"\b(no cumple|no se cumple|no_cumple)\b[^.]{0,120}aunque [^.]{0,60}(esta|este|esten) levantad",
    r"levantad[oa]s? como hallazgo[^.]{0,80}\b(no cumple|no se cumple|no_cumple)\b",
    r"\b(no cumple|no se cumple|no_cumple)\b[^.]{0,80}aunque[^.]{0,80}hallazgo",
    # no_cumple por un resultado fuera de norma sin la condición "que el informe no levanta"
    # antes (la redacción vieja de REGLAS_TRAMO_CHECKLIST).
    r"\bno_?cumple\b(?:(?!no (?:lo |la )?levanta)[^.]){0,150}fuera de norma",
)

# Excepciones justificadas: (texto, fragmento normalizado) → por qué no rompen la 19d.
EXCEPCIONES_JUSTIFICADAS: dict[tuple[str, str], str] = {
    ("punto 6",
     "no es adjuntarlo, aunque su desactualizacion este levantada como hallazgo "
     "— responder no_cumple"): (
        "2026-10-17, tasks/equipo/respuestas_v3_celdas.md (Gamma 6): el DUF que no viene "
        "dentro del informe es una omisión del informe, no una deficiencia de la instalación "
        "levantada como hallazgo"
    ),
}


def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto)
    plano = "".join(c for c in sin_tildes if not unicodedata.combining(c)).casefold()
    return " ".join(plano.split())


def _textos() -> dict[str, str]:
    textos = {f"punto {p['numero']}": str(p["donde_buscar"]) for p in cargar_puntos()}
    textos["SYSTEM_CHECKLIST"] = SYSTEM_CHECKLIST
    textos["REGLAS_TRAMO_CHECKLIST"] = REGLAS_TRAMO_CHECKLIST
    textos["REGLA_CITA_CHECKLIST"] = REGLA_CITA_CHECKLIST
    return textos


def _hallazgos(nombre: str, texto: str) -> list[str]:
    plano = _normalizar(texto)
    encontrados = []
    # Una excepción justificada cubre solo las coincidencias que caen DENTRO de su
    # fragmento: una frase nueva al lado no queda tapada.
    tramos = [
        (j.start(), j.end())
        for donde, fragmento in EXCEPCIONES_JUSTIFICADAS if donde == nombre
        for j in re.finditer(re.escape(fragmento), plano)
    ]
    for patron in PATRONES_EXCEPCION:
        for m in re.finditer(patron, plano):
            justificada = any(ini <= m.start() and m.end() <= fin for ini, fin in tramos)
            if not justificada:
                encontrados.append(f"{nombre}: «{plano[max(0, m.start() - 60):m.end() + 30]}»")
    return encontrados


def test_ningun_texto_del_checklist_crea_una_excepcion_a_la_19d() -> None:
    problemas = [h for nombre, texto in _textos().items() for h in _hallazgos(nombre, texto)]
    assert not problemas, (
        "Posible excepción a la regla 19d (levantado como hallazgo = cumple). Si es una "
        "precisión legítima, agregarla a EXCEPCIONES_JUSTIFICADAS con fecha y referencia "
        "a una respuesta del equipo revisor:\n" + "\n".join(problemas)
    )


def test_las_excepciones_justificadas_siguen_en_uso() -> None:
    textos = {k: _normalizar(v) for k, v in _textos().items()}
    huerfanas = [k for k in EXCEPCIONES_JUSTIFICADAS if k[1] not in textos.get(k[0], "")]
    assert not huerfanas, f"Excepciones que ya no aparecen en el texto: {huerfanas}"


@pytest.mark.parametrize("texto", [
    # Hint 22 de B2 (lo destapó Beta 22; tasks/lessons.md 2026-10-17).
    "Levantar la indisponibilidad de la 87B NO basta para cumplir.",
    # Excepción del SYSTEM_CHECKLIST de B0 a B2 (el equipo revisor la retiró el 2026-10-17).
    "En esos puntos el resultado manda: si el valor reportado excede el límite, el punto "
    "no se cumple aunque esté levantado como hallazgo.",
    # Hint 23 de B0 a B2.
    "Si el informe reporta tiempos mayores a 400 ms, el punto NO se cumple, aunque el "
    "cálculo esté bien documentado y el exceso esté levantado como hallazgo.",
    # REGLAS_TRAMO_CHECKLIST hasta el 2026-10-17.
    "- no_cumple: SOLO si este tramo muestra evidencia positiva de incumplimiento (un "
    "resultado fuera de norma, una prueba declarada no realizada o pendiente sin levantar "
    "como hallazgo, etc.).",
])
def test_los_patrones_detectan_las_excepciones_que_ya_se_colaron(texto: str) -> None:
    assert _hallazgos("caso", texto)


def test_una_excepcion_nueva_al_lado_de_la_justificada_no_queda_tapada() -> None:
    (texto_6,) = [str(p["donde_buscar"]) for p in cargar_puntos() if p["numero"] == 6]
    assert not _hallazgos("punto 6", texto_6)
    agregado = texto_6 + " Además, el punto no se cumple aunque esté levantado como hallazgo."
    assert _hallazgos("punto 6", agregado)


@pytest.mark.parametrize("texto", [
    "CUMPLE en dos casos: (a) el informe muestra que cuenta con sincronización GPS, o (b) "
    "muestra que NO cuenta, pero lo levanta explícitamente como hallazgo.",
    "La regla NO tiene excepciones: también vale cuando un RESULTADO excede un límite "
    "normativo (despeje mayor a 400 ms levantado como hallazgo → el punto cumple).",
    "Solo NO cumple si falta la sincronización y el informe no la levanta como hallazgo.",
    "CUMPLE aunque la deficiencia esté levantada como hallazgo: el informe la reportó.",
    "- no_cumple: SOLO si este tramo muestra evidencia positiva de incumplimiento que el "
    "informe NO levanta como hallazgo (un resultado fuera de norma, una prueba pendiente).",
])
def test_los_patrones_no_marcan_la_regla_general(texto: str) -> None:
    assert not _hallazgos("caso", texto)


class TestPrecisionesQueCorrigieronFallasReales:
    """Fijan las precisiones de criterio que corrigieron errores medidos: si alguien las
    "simplifica", el falso cumple o el error que corrigieron puede volver."""

    @staticmethod
    def _hint(numero: int) -> str:
        (punto,) = [p for p in cargar_puntos() if p["numero"] == numero]
        return _normalizar(str(punto["donde_buscar"]))

    def test_punto_6_el_duf_debe_venir_dentro_del_pdf(self) -> None:
        # Gamma 6: el DUF remitido a una carpeta aparte dio falso cumple en 6 corridas.
        hint = self._hint(6)
        assert "dentro del pdf" in hint and "no es adjuntarlo" in hint

    def test_punto_17_tablas_de_tiempos_no_son_tablas_de_corrientes(self) -> None:
        # Añañuca 17 (B0): tablas de tiempos tomadas como corrientes de cortocircuito.
        assert "no son tablas de corrientes" in self._hint(17)

    def test_punto_22_un_hallazgo_de_tiempos_no_declara_la_falta_de_87b(self) -> None:
        # Beta 22 (B2): la categoría "87B/Tpo Máx Despeje" leída como declaración de 87B.
        hint = self._hint(22)
        assert "no lo son un hallazgo que solo reporta tiempos de despeje" in hint

    def test_el_prompt_y_los_tramos_dicen_que_la_regla_no_tiene_excepciones(self) -> None:
        assert "la regla no tiene excepciones" in _normalizar(SYSTEM_CHECKLIST)
        assert "que el informe no levanta como hallazgo" in _normalizar(REGLAS_TRAMO_CHECKLIST)
