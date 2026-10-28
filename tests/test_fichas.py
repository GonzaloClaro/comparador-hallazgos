"""Tests de las fichas por informe del set de medición (M39), sin datos privados."""

from __future__ import annotations

import hashlib
import unicodedata
from pathlib import Path
from typing import Any

import pytest
import yaml

from comparador import fichas

SHA_PLANILLA = hashlib.sha256(b"planilla").hexdigest()
BETA = "S-E Beta (Auditora Ensaut)"
ANANUCA_NFC = unicodedata.normalize("NFC", "S-E Añañuca (Auditora Reliable Energy)")


def _ficha(**campos: Any) -> dict[str, Any]:
    return {
        "fecha_planilla": "2026-07-22", "fecha_fuente": "propiedades_xlsx", "revisor": None,
        "sha256_planilla": SHA_PLANILLA, "sha256_criterios_al_ingresar": "e1d191313a247c6a",
        "con_herramienta": False, "uso": "ajuste", **campos,
    }


def _yaml(tmp_path: Path, informes: dict[str, Any]) -> Path:
    ruta = tmp_path / "fichas_informes.yaml"
    ruta.write_text(yaml.safe_dump({"version_fichas": "1.0", "informes": informes},
                                   allow_unicode=True), encoding="utf-8")
    return ruta


def test_carga_las_fichas_y_las_busca_por_carpeta_en_cualquier_normalizacion(tmp_path: Path):
    cargadas = fichas.cargar_fichas(_yaml(tmp_path, {
        BETA: _ficha(), ANANUCA_NFC: _ficha(revisor="R2", uso="prueba")}))
    assert set(cargadas) == {BETA, ANANUCA_NFC}
    # macOS entrega los nombres de carpeta en NFD.
    nfd = unicodedata.normalize("NFD", ANANUCA_NFC)
    ficha = fichas.ficha_de(cargadas, nfd)
    assert ficha is not None and ficha.revisor == "R2"
    assert fichas.ficha_de(cargadas, "S-E Otra (Auditora Ensaut)") is None


@pytest.mark.parametrize(("uso", "con_herramienta", "muestra"), [
    ("ajuste", False, "dentro"),
    ("prueba", False, "fuera"),        # solo una planilla hecha sin la herramienta es prueba
    ("prueba", True, "dentro"),
    ("prueba", "desconocido", "dentro"),
])
def test_fuera_de_muestra_solo_prueba_sin_herramienta(
    tmp_path: Path, uso: str, con_herramienta: Any, muestra: str
):
    (ficha,) = fichas.cargar_fichas(_yaml(tmp_path, {
        BETA: _ficha(uso=uso, con_herramienta=con_herramienta)})).values()
    assert fichas.muestra(ficha) == muestra
    assert fichas.muestra(None) == "sin_ficha"


@pytest.mark.parametrize(("campos", "mensaje"), [
    ({"revisor": "Nombre Apellido"}, "revisor"),     # nunca un nombre: código R1, R2…
    ({"revisor": "r1"}, "revisor"),
    ({"uso": "entrenamiento"}, "uso"),
    ({"con_herramienta": "no"}, "con_herramienta"),  # ni bool laxo ni texto libre
    ({"sha256_planilla": "abc"}, "sha256_planilla"),
    ({"sha256_criterios_al_ingresar": "E1D191313A247C6A"}, "sha256_criterios"),
    ({"fecha_fuente": "memoria"}, "fecha_fuente"),
    ({"fecha_fuente": None}, "fecha_fuente"),        # una fecha dice de dónde sale
    ({"sha256_planilla": None}, "sin planilla"),     # sin planilla no hay fecha ni herramienta
    ({"con_herramienta": None}, "con_herramienta"),  # con planilla sí
    ({"nombre_revisor": "x"}, "nombre_revisor"),     # campo desconocido
])
def test_ficha_invalida_falla(tmp_path: Path, campos: dict[str, Any], mensaje: str):
    with pytest.raises(ValueError, match=mensaje):
        fichas.cargar_fichas(_yaml(tmp_path, {BETA: _ficha(**campos)}))


def test_clave_que_no_esta_en_nfc_falla(tmp_path: Path):
    nfd = unicodedata.normalize("NFD", ANANUCA_NFC)
    with pytest.raises(ValueError, match="NFC"):
        fichas.cargar_fichas(_yaml(tmp_path, {nfd: _ficha()}))


def test_informe_sin_planilla(tmp_path: Path):
    (ficha,) = fichas.cargar_fichas(_yaml(tmp_path, {BETA: _ficha(
        fecha_planilla=None, fecha_fuente=None, sha256_planilla=None,
        con_herramienta=None)})).values()
    assert fichas.problemas_planilla(ficha, None) == []
    assert fichas.muestra(ficha) == "dentro"


def test_la_planilla_se_contrasta_con_el_archivo_real(tmp_path: Path):
    (ficha,) = fichas.cargar_fichas(_yaml(tmp_path, {BETA: _ficha()})).values()
    planilla = tmp_path / "CheckList Revisión.xlsx"
    planilla.write_bytes(b"planilla")
    assert fichas.problemas_planilla(ficha, planilla) == []
    planilla.write_bytes(b"otra planilla")             # p. ej. reemplazada por una pre-llenada
    (problema,) = fichas.problemas_planilla(ficha, planilla)
    assert "sha256" in problema
    (problema,) = fichas.problemas_planilla(ficha, None)
    assert "no hay planilla" in problema
    sin = ficha.model_copy(update={"sha256_planilla": None, "fecha_planilla": None,
                                   "fecha_fuente": None, "con_herramienta": None})
    (problema,) = fichas.problemas_planilla(sin, planilla)
    assert "sin planilla" in problema
