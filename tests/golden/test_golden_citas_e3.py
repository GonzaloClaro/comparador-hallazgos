"""Verificación de citas de la Etapa 3 sobre los runs reales de B2 (sin API).

Cada hallazgo guardado en B2 pasa por la verificación de 0.7.0 contra el PDF
que vio el modelo: la descripción y la acción son literales en su página
casi siempre. Las excepciones quedan fijadas acá una por una (medidas el
2026-10-18), para que un cambio en la normalización que esconda una
discrepancia real (o invente una) rompa el test:

- Sonnet, Alfa: el modelo escribió "No Cumplir" donde el PDF dice "No
  Cumple" (alteración real del modelo, que el comparador dio por coincide).
- Opus, Alfa: una fila de tabla partida entre las págs. 29 y 30 (el
  comienzo al pie de la 29, el final arriba de la 30).
- Haiku: Añañuca y Gamma con descripciones parafraseadas. Hasta la
  revisión del 2026-10-18 cuatro de ellas salían "continúa en la página
  siguiente" porque un prefijo y un sufijo cualquiera de dos páginas calzaban;
  no eran filas partidas.

Todo lo que no está en la lista debe quedar "verificada" en su página.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.golden.datos import Caso, casos, ids, requiere_informes, requiere_mediciones
from tests.golden.test_golden_replay_e1_e3 import replay_verificado

pytestmark = [pytest.mark.golden, requiere_mediciones, requiere_informes]

CASOS = [c for c in casos("b2") if c.tiene("etapa1_panos.json")
         and c.tiene("etapa3_pdf_hallazgos.json")]

NC, CONTINUA = "no_encontrada", "continua_pagina_siguiente"

# (modelo, subestación) → (campo, paño, página, estado, inicio del texto) de
# cada cita que no quedó "verificada" en su página.
NO_VERIFICADAS: dict[tuple[str, str], list[tuple[str, str, int, str, str]]] = {
    ("claude-sonnet-5-5", "Alfa"): [
        ("descripcion", "C2", 14, NC, "Coordinación de ajustes de protección. No Cumplir"),
    ],
    ("claude-opus-5-5", "Alfa"): [
        ("descripcion", "CT1A", 29, CONTINUA, "Mediante inyección secundaria"),
        ("descripcion", "CT1B", 29, CONTINUA, "Mediante inyección secundaria"),
        ("descripcion", "HT1", 29, CONTINUA, "Mediante inyección secundaria"),
    ],
    ("claude-haiku-5-5", "Añañuca"): [
        ("descripcion", "C1", 10, NC, "Estudio de coordinación de ajustes"),
        ("descripcion", "C2", 14, NC, "Estudio de coordinación de ajustes"),
        ("accion_correctiva", "C2", 14, NC, "Se debe actualizar ECAP entregado"),
        ("descripcion", "C2", 15, NC, "Ante una falla trifásica (3F)"),
        ("descripcion", "CT", 19, NC, "Estudio de coordinación de ajustes"),
        ("descripcion", "CT", 20, NC, "Se verifica un incumplimiento normativo"),
    ],
    ("claude-haiku-5-5", "Gamma"): [
        ("descripcion", "BT2", 17, NC, "CT2: La verificación se ha realizado"),
        ("descripcion", "CT2", 17, NC, "CT2: La verificación se ha realizado"),
    ],
}


@pytest.mark.parametrize("caso", CASOS, ids=ids(CASOS))
def test_estados_de_las_citas(caso: Caso, pdf_visto: Callable[[Caso], Path]) -> None:
    no_verificadas = []
    for _, h in replay_verificado(caso, pdf_visto(caso)):
        ev = h.evidencia
        assert ev.verificacion_descripcion is not None
        # La acción se verifica siempre que tenga texto.
        assert (ev.verificacion_accion is None) is (not h.accion_correctiva)
        for campo, v, texto in (
            ("descripcion", ev.verificacion_descripcion, h.descripcion),
            ("accion_correctiva", ev.verificacion_accion, h.accion_correctiva or ""),
        ):
            if v is not None and v.estado != "verificada":
                assert ev.pagina_pdf is not None
                no_verificadas.append((campo, h.pano, ev.pagina_pdf, v.estado.value, texto))

    esperadas = NO_VERIFICADAS.get((caso.modelo, caso.subestacion), [])
    assert len(no_verificadas) == len(esperadas), no_verificadas
    for obtenida, esperada in zip(no_verificadas, esperadas, strict=True):
        assert obtenida[:4] == esperada[:4]
        assert obtenida[4].startswith(esperada[4])
