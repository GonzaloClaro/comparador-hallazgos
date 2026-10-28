"""Replay del post-proceso de E1 y E3 con las respuestas crudas de B2.

Las respuestas del modelo (`response_raw` de etapa1_raw/ y etapa3_raw/) pasan
por el código ACTUAL de reparación y validación, sin llamar a ningún modelo;
el resultado debe ser idéntico a lo que el run guardó. La Etapa 1, la 3 y el
schema no cambiaron desde B2 salvo por la verificación de citas (0.7.0, cuyas
páginas distintas a B2 se listan una por una), así que cualquier otra
diferencia es una regresión. B0 y B1 no se reproducen: su E1 no pedía
sub-paños y su E3 no tenía reparación ni reintento.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from comparador.catalogo import cargar_hints_empresa
from comparador.citas import PaginasPdf
from comparador.etapa1_descubrir_panos import (
    _filtrar_sub_panos,
    _limpiar_nombres_reles,
    _ListaPanosResponse,
    _validar_panos,
)
from comparador.etapa3_extraer_hallazgos import (
    _cambios_entre_intentos,
    _ListaHallazgosResponse,
    _Procesado,
    _procesar_respuesta,
    _universo_etapa1,
    _verificar_citas,
)
from comparador.evaluar_lote import _empresa
from comparador.schemas import Hallazgo, PanoDescubierto
from tests.golden.datos import (
    Caso,
    casos,
    ids,
    inventario,
    requiere_informes,
    requiere_mediciones,
    sin_campos_070,
)

pytestmark = [pytest.mark.golden, requiere_mediciones]

# Con etapa1_panos.json: desde 2026-10-17 un E1 fallido también deja su raw (llamada
# fallida) y no debe entrar al replay.
CASOS_E1 = [c for c in casos("b2")
            if c.tiene("etapa1_raw/descubrir_panos.json") and c.tiene("etapa1_panos.json")]
CASOS_E3 = [c for c in casos("b2") if c.tiene("etapa1_panos.json") and c.tiene("etapa3_raw")]


@pytest.mark.parametrize("caso", CASOS_E1, ids=ids(CASOS_E1))
def test_e1_post_proceso_reproduce_los_panos_guardados(caso: Caso) -> None:
    raw = caso.json("etapa1_raw/descubrir_panos.json")
    respuesta = _ListaPanosResponse.model_validate(raw["response_raw"])
    # Con troceo la Etapa 1 lee solo el primer tramo (Beta: págs 1-228).
    troceo = raw.get("troceo")
    total = (troceo["paginas_leidas"][1] if troceo
             else inventario()[caso.subestacion]["paginas_pdf_visto_por_el_modelo"])

    _validar_panos(respuesta.panos, total)
    reparaciones = _limpiar_nombres_reles(respuesta.panos)
    descartados, normalizados = _filtrar_sub_panos(respuesta.panos)

    panos = [PanoDescubierto.model_validate(p.model_dump()) for p in respuesta.panos]
    guardados = [PanoDescubierto.model_validate(p) for p in caso.json("etapa1_panos.json")]
    assert panos == guardados
    assert reparaciones + normalizados == raw.get("reparaciones", [])
    assert descartados == raw.get("sub_panos_descartados", [])


def replay_e3(caso: Caso, pano: PanoDescubierto, raw: dict[str, Any],
              universo: Any) -> _Procesado:
    """Reparación y validación de E3 sobre una respuesta cruda guardada."""
    hints = cargar_hints_empresa(_empresa(Path(caso.carpeta)))
    respuesta = _ListaHallazgosResponse.model_validate(raw["response_raw"])
    return _procesar_respuesta(respuesta, pano, hints, universo)


# Páginas que la verificación de citas (0.7.0) deja distintas de B2, por índice
# del hallazgo. B2 anclaba la página con un prefijo de texto_crudo; la
# verificación usa la descripción literal y no mueve la página de una
# descripción que no está en el PDF (queda "no encontrada", a la vista).
PAGINAS_DISTINTAS_A_B2: dict[tuple[str, str], dict[int, tuple[int, int]]] = {
    # Haiku parafraseó la descripción: B2 la había llevado a la p. 19.
    ("claude-haiku-5-5", "Añañuca"): {29: (19, 20)},
}


def replay_verificado(caso: Caso, pdf: Path) -> list[tuple[PanoDescubierto, Hallazgo]]:
    """Post-proceso de E3 + verificación de citas, paño por paño, como en el pipeline."""
    panos = [PanoDescubierto.model_validate(p) for p in caso.json("etapa1_panos.json")]
    universo = _universo_etapa1(panos)
    resultado = []
    with PaginasPdf(pdf) as pp:
        for pano in panos:
            raw = caso.json(f"etapa3_raw/extraer_{pano.nombre.replace('/', '_')}.json")
            definitivo = replay_e3(caso, pano, raw, universo)
            resultado += [(pano, h) for h in _verificar_citas(pp, definitivo.hallazgos, pano)]
    return resultado


@requiere_informes
@pytest.mark.parametrize(
    "caso", [c for c in CASOS_E3 if c.tiene("etapa3_pdf_hallazgos.json")],
    ids=ids([c for c in CASOS_E3 if c.tiene("etapa3_pdf_hallazgos.json")]),
)
def test_e3_con_citas_verificadas_reproduce_lo_guardado(
    caso: Caso, pdf_visto: Callable[[Caso], Path]
) -> None:
    """Igual a B2 en todo (orden, campos, páginas), salvo las páginas listadas."""
    hallazgos = [h.model_dump(mode="json") for _, h in replay_verificado(caso, pdf_visto(caso))]
    guardados = caso.json("etapa3_pdf_hallazgos.json")
    distintas = PAGINAS_DISTINTAS_A_B2.get((caso.modelo, caso.subestacion), {})
    for i, (antes, ahora) in distintas.items():
        assert (guardados[i]["evidencia"]["pagina_pdf"],
                hallazgos[i]["evidencia"]["pagina_pdf"]) == (antes, ahora)
        guardados[i]["evidencia"]["pagina_pdf"] = ahora
    assert sin_campos_070(hallazgos) == sin_campos_070(guardados)


@pytest.mark.parametrize("caso", CASOS_E3, ids=ids(CASOS_E3))
def test_e3_reparacion_y_validacion_reproducen_lo_guardado(caso: Caso) -> None:
    panos = [PanoDescubierto.model_validate(p) for p in caso.json("etapa1_panos.json")]
    universo = _universo_etapa1(panos)
    raw_dir = caso.run_dir / "etapa3_raw"

    hallazgos: list[dict[str, Any]] = []
    for pano in panos:
        nombre = f"extraer_{pano.nombre.replace('/', '_')}"
        raw = caso.json(f"etapa3_raw/{nombre}.json")
        definitivo = replay_e3(caso, pano, raw, universo)
        assert definitivo.reparaciones == raw["reparaciones"], pano.nombre
        assert definitivo.problemas == raw.get("problemas", []), pano.nombre

        intento1 = raw_dir / f"{nombre}_intento1.json"
        assert raw["reintento"] is intento1.exists(), pano.nombre
        if intento1.exists():
            raw1 = caso.json(f"etapa3_raw/{intento1.name}")
            primero = replay_e3(caso, pano, raw1, universo)
            assert primero.problemas == raw1["problemas"] == raw["problemas_primer_intento"]
            assert raw["hallazgos_por_intento"] == [
                {"total": len(p.hallazgos), "validos": p.validos} for p in (primero, definitivo)
            ]
            assert _cambios_entre_intentos(
                primero.hallazgos, definitivo.hallazgos) == raw["cambios_en_reintento"]
            assert ("advertencia_reintento" in raw) is (definitivo.validos < primero.validos)
        hallazgos += [h.model_dump(mode="json") for h in definitivo.hallazgos]

    if caso.tiene("etapa3_pdf_hallazgos.json"):
        # Mismos hallazgos y en el mismo orden. La página la fija la
        # verificación de citas: se compara en el test de arriba.
        def sin_pagina(lista: list[dict[str, Any]]) -> Any:
            return [{**h, "evidencia": {**h["evidencia"], "pagina_pdf": None}}
                    for h in sin_campos_070(lista)]

        assert sin_pagina(hallazgos) == sin_pagina(caso.json("etapa3_pdf_hallazgos.json"))
    else:
        # Run que falló en la Etapa 3: el error registrado cita los problemas
        # que el replay vuelve a encontrar.
        error = caso.json("error.json")
        assert error["tipo"] == "ExtraccionInvalidaError"
        problemas = [p for pano in panos for p in caso.json(
            f"etapa3_raw/extraer_{pano.nombre.replace('/', '_')}.json").get("problemas", [])]
        assert problemas
        assert all(p in error["mensaje"] for p in problemas)
