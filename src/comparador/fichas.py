"""Ficha por informe del set de medición (M39, docs/06_mejoras.md).

Cada informe con el que se mide entra con una ficha en
``mediciones/fichas_informes.yaml`` (privado, fuera de git, con su MANIFEST):

- ``fecha_planilla`` y ``fecha_fuente``: cuándo se hizo la planilla del equipo
  revisor y de dónde sale esa fecha (``conocida`` o ``propiedades_xlsx``: la
  fecha de modificación guardada en el archivo).
- ``revisor``: código (R1, R2…), nunca un nombre; null = no se sabe quién la hizo.
- ``sha256_planilla``: la planilla con que se mide (evaluar_lote la contrasta con
  el archivo real antes de gastar).
- ``sha256_criterios_al_ingresar``: ``sha256_checklist_puntos.yaml`` de
  ``persistence.version_codigo`` (16 hex) cuando el informe entró al set.
- ``con_herramienta``: si la planilla se hizo con la herramienta a la vista
  (true/false/«desconocido»). Una planilla hecha con ella es «GT asistido»: por
  anclaje tiende a 0 falsos cumple.
- ``uso``: ``ajuste`` (se usó para ajustar prompts o criterios) o ``prueba``.
- ``grupo`` y ``nota``: opcionales.

Las cifras se separan en dentro y fuera de muestra: «fuera» solo con uso prueba
y una planilla hecha sin la herramienta. La clave es el nombre de la carpeta en
``informes_reales/`` en NFC (macOS lo entrega en NFD): ``ficha_de`` normaliza.
"""

from __future__ import annotations

import hashlib
import unicodedata
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, model_validator

from comparador.config import PROJECT_ROOT

RUTA_DEFAULT = PROJECT_ROOT / "mediciones" / "fichas_informes.yaml"
DENTRO, FUERA, SIN_FICHA = "dentro", "fuera", "sin_ficha"


class Ficha(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fecha_planilla: date | None
    fecha_fuente: Literal["conocida", "propiedades_xlsx"] | None
    revisor: str | None = Field(pattern=r"^R\d+$")
    sha256_planilla: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    sha256_criterios_al_ingresar: str | None = Field(pattern=r"^[0-9a-f]{16}$")
    con_herramienta: StrictBool | Literal["desconocido"] | None
    uso: Literal["ajuste", "prueba"]
    grupo: str | None = None
    nota: str | None = None

    @model_validator(mode="after")
    def _coherente(self) -> Ficha:
        if (self.fecha_planilla is None) != (self.fecha_fuente is None):
            raise ValueError("fecha_planilla y fecha_fuente van juntas: una fecha dice de "
                             "dónde sale")
        if self.sha256_planilla is None:
            if self.fecha_planilla is not None or self.con_herramienta is not None:
                raise ValueError("sin planilla (sha256_planilla null) no hay fecha_planilla "
                                 "ni con_herramienta")
        elif self.con_herramienta is None:
            raise ValueError("con planilla, con_herramienta es true, false o «desconocido»")
        return self


class _Archivo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_fichas: str | None = None
    informes: dict[str, Ficha]


def cargar_fichas(ruta: Path) -> dict[str, Ficha]:
    """Fichas por carpeta. ValueError si el archivo no valida o una clave no está en NFC."""
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    try:
        archivo = _Archivo.model_validate(datos)
    except ValidationError as exc:
        raise ValueError(f"{ruta}: {exc}") from exc
    no_nfc = [k for k in archivo.informes if not unicodedata.is_normalized("NFC", k)]
    if no_nfc:
        raise ValueError(f"{ruta}: claves que no están en NFC: {no_nfc}")
    return archivo.informes


def ficha_de(fichas: dict[str, Ficha], carpeta: str) -> Ficha | None:
    return fichas.get(unicodedata.normalize("NFC", carpeta))


def muestra(ficha: Ficha | None) -> str:
    """«fuera» solo si el informe es de prueba y su planilla se hizo sin la herramienta."""
    if ficha is None:
        return SIN_FICHA
    return FUERA if ficha.uso == "prueba" and ficha.con_herramienta is False else DENTRO


def problemas_planilla(ficha: Ficha, planilla: Path | None) -> list[str]:
    """La planilla de la carpeta contra la de la ficha (sha256)."""
    if planilla is None:
        return [] if ficha.sha256_planilla is None else [
            "la ficha tiene planilla y en la carpeta no hay planilla"]
    sha = hashlib.sha256(planilla.read_bytes()).hexdigest()
    if ficha.sha256_planilla is None:
        return [f"la ficha dice sin planilla y en la carpeta está {planilla.name}"]
    if sha != ficha.sha256_planilla:
        return [f"el sha256 de {planilla.name} ({sha[:16]}) no es el de la ficha "
                f"({ficha.sha256_planilla[:16]})"]
    return []
