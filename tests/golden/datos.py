"""Acceso a los datos reales privados que usan los tests golden.

- `mediciones/`: las rondas B0-B2 (evaluacion_B*.json, runs con sus JSON
  intermedios y respuestas crudas, inventario). Solo lectura.
- `informes_reales/`: los informes y Excel originales. Solo lectura.

Ninguno de los dos está en git: sin ellos los tests golden se saltan (con
GOLDEN_OBLIGATORIO=1 saltarse hace fallar la sesión, tests/conftest.py). Las
rondas se identifican como en `evaluacion_B*.json` (modelo × informe → run_id).

GOLDEN_MEDICIONES reemplaza la carpeta de mediciones (p. ej. una vacía, para
probar la compuerta) y GOLDEN_INFORMES la de los informes.

Los golden quedan limitados a los informes medidos (inventario_informes.json):
una carpeta nueva en informes_reales/, completa o no, no entra ni los rompe.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from comparador.evaluar_lote import descubrir_casos

ROOT = Path(__file__).resolve().parents[2]
MEDICIONES = Path(os.environ.get("GOLDEN_MEDICIONES") or ROOT / "mediciones")
INFORMES = Path(os.environ.get("GOLDEN_INFORMES") or ROOT / "informes_reales")
# Rondas cuyos runs ya no cambian: los conteos fijos de los golden valen solo
# para ellas (las rondas nuevas se agregan sin romperlos).
RONDAS_CONGELADAS = ("b0", "b1", "b2")

HAY_MEDICIONES = all(
    (MEDICIONES / r / f"evaluacion_{r.upper()}.json").is_file() for r in RONDAS_CONGELADAS
)
HAY_INFORMES = INFORMES.is_dir()

requiere_mediciones = pytest.mark.skipif(
    not HAY_MEDICIONES, reason=f"sin mediciones en {MEDICIONES} (datos privados, fuera de git)"
)
requiere_informes = pytest.mark.skipif(
    not HAY_INFORMES, reason="sin informes_reales/ (datos privados, fuera de git)"
)

SUBESTACIONES = ("Epsilon", "Añañuca", "Zeta", "Alfa", "Beta", "Eta", "Gamma")


def plano(texto: str) -> str:
    """Sin tildes ni mayúsculas: macOS guarda los nombres de carpeta en NFD."""
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c)).casefold()


def subestacion(carpeta: str) -> str | None:
    """La subestación de una carpeta, o None si no es uno de los informes medidos."""
    return next((s for s in SUBESTACIONES if plano(s) in plano(carpeta)), None)


# Campos que agregó el schema 0.7.0 (referencias verificables). Las rondas
# B0-B2 se guardaron antes: para compararlas con la salida actual se quitan,
# junto con schema_version, de los dos lados.
CAMPOS_070 = frozenset({
    "verificacion_descripcion", "verificacion_accion", "hoja_excel", "fila_oculta",
    "citas", "resultado_modelo", "motivo_ajuste", "bajados_sin_cita_verificada",
    "filas_excel_ocultas",
})
# Campos que agregó el schema 0.8.0 (informes leídos por partes, M08).
CAMPOS_080 = frozenset({
    "tramos_respaldo", "aviso_tramos", "causa_ajuste",
    "tramos_leidos", "marcados_un_tramo", "bajados_un_tramo",
})
# Campos que agregó el schema 0.9.0 (PD71: emparejamiento dudoso por fila disputada).
CAMPOS_090 = frozenset({"emparejamiento_dudoso"})
# Campos que agregó el schema 0.10.0 (PD60: el hallazgo del PDF nombra a otro relé).
CAMPOS_0100 = frozenset({"otros_reles_nombrados"})


def sin_campos_070(dato: Any) -> Any:
    """El JSON sin schema_version ni los campos de 0.7.0 y posteriores (0.8.0,
    0.9.0 y 0.10.0), a cualquier profundidad: como lo escribía el schema 0.6.0."""
    if isinstance(dato, dict):
        return {
            k: sin_campos_070(v) for k, v in dato.items()
            if k != "schema_version"
            and k not in CAMPOS_070 | CAMPOS_080 | CAMPOS_090 | CAMPOS_0100
        }
    if isinstance(dato, list):
        return [sin_campos_070(v) for v in dato]
    return dato


def leer_json(ruta: Path) -> Any:
    return json.loads(ruta.read_text(encoding="utf-8"))


def sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


@dataclass(frozen=True)
class Caso:
    """Un modelo × informe de una ronda, tal como lo registra evaluacion_B*.json."""

    ronda: str
    modelo: str
    carpeta: str
    run_id: str
    fila: dict[str, Any]

    @property
    def run_dir(self) -> Path:
        return MEDICIONES / self.ronda / "runs" / self.run_id

    @property
    def subestacion(self) -> str:
        # Un informe que no es de los medidos se nombra por su carpeta.
        return subestacion(self.carpeta) or self.carpeta

    @property
    def id(self) -> str:
        modelo = self.modelo.removeprefix("claude-").split("-")[0]
        return f"{self.ronda}-{modelo}-{self.subestacion}"

    def tiene(self, nombre: str) -> bool:
        return (self.run_dir / nombre).exists()

    def json(self, nombre: str) -> Any:
        return leer_json(self.run_dir / nombre)


def rondas_con_evaluacion() -> list[str]:
    """Rondas con su evaluacion_<RONDA>.json (b0, b1, b2, b3, b3s…), en orden."""
    rondas = []
    for carpeta in MEDICIONES.glob("b*"):
        nombre = re.fullmatch(r"b(\d+)([a-z]*)", carpeta.name)
        if nombre and (carpeta / f"evaluacion_{carpeta.name.upper()}.json").is_file():
            rondas.append((int(nombre[1]), nombre[2], carpeta.name))
    return [ronda for *_, ronda in sorted(rondas)]


def casos(*rondas: str) -> list[Caso]:
    """Casos de las rondas pedidas (vacío si no hay mediciones)."""
    if not HAY_MEDICIONES:
        return []
    salida = []
    for ronda in rondas:
        evaluacion = leer_json(MEDICIONES / ronda / f"evaluacion_{ronda.upper()}.json")
        for modelo, filas in evaluacion["resultados"].items():
            for fila in filas:
                salida.append(Caso(ronda, modelo, fila["informe"], fila["run_id"], fila))
    return salida


def ids(lista: list[Caso]) -> list[str]:
    return [c.id for c in lista]


@cache
def inventario() -> dict[str, dict[str, Any]]:
    """inventario_informes.json por subestación."""
    return {
        sub: x for x in leer_json(MEDICIONES / "inventario_informes.json")
        if (sub := subestacion(x["carpeta"])) is not None
    }


def _carpetas_medidas() -> set[str] | None:
    """Carpetas (NFC) del inventario medido; None si no hay mediciones."""
    ruta = MEDICIONES / "inventario_informes.json"
    if not ruta.is_file():
        return None
    return {unicodedata.normalize("NFC", x["carpeta"]) for x in leer_json(ruta)}


@cache
def casos_informes() -> dict[str, dict[str, Any]]:
    """Insumos de cada informe medido por subestación, elegidos con la misma
    regla que usó la medición (evaluar_lote.descubrir_casos). Solo las carpetas
    del inventario medido (sin mediciones, las de los 7 informes conocidos):
    una carpeta nueva u omitida no entra. Con inventario, descubrir_casos ni
    recorre las demás (corta ante dos planillas en cualquier carpeta que mira);
    una carpeta medida que dejó de ser un caso falla a la vista."""
    if not HAY_INFORMES:
        return {}
    medidas = _carpetas_medidas()
    casos, _ = descubrir_casos(INFORMES, sorted(medidas) if medidas is not None else None)
    return {
        sub: c for c in casos
        if (sub := subestacion(c["nombre"])) is not None
        and (medidas is None or unicodedata.normalize("NFC", c["nombre"]) in medidas)
    }
