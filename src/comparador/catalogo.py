"""Carga del catálogo de hints por empresa auditora.

El catálogo vive en `catalogo_empresas.yaml` y es configuración, no schema:
actualizarlo no incrementa `schema_version`. En la Etapa 3 el bloque de la
empresa seleccionada se inyecta al prompt de extracción como contexto.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

from comparador.config import settings
from comparador.schemas import EmpresaAuditora


class HintsEmpresa(BaseModel):
    """Bloque de hints de una empresa auditora del catálogo."""

    descripcion_formato: str
    mapeo_columnas: dict[str, list[str]]
    calificacion_por_seccion_visual: bool
    identificacion_rele: str
    notas_adicionales: str
    # Patrones (contains, normalizado sin acentos/mayúsculas) que identifican
    # filas del Excel sin relé específico — van a estado "transversal" y no
    # entran al matching. Usar patrones multi-palabra específicos.
    filas_transversales: list[str] = []

    @property
    def es_placeholder(self) -> bool:
        """El bloque existe pero aún no fue caracterizado con informes reales.

        La extracción corre igual (sin hints útiles), pero la UI debe
        advertirlo — nunca degradar en silencio (espíritu del invariante 12).
        Señal robusta: una empresa caracterizada siempre tiene mapeo de
        columnas; el marcador "[Pendiente" cubre borradores parciales.
        """
        return not self.mapeo_columnas or "[Pendiente" in self.descripcion_formato


class EmpresaNoCatalogadaError(Exception):
    """La empresa no tiene bloque en el catálogo. Nunca hacer fallback silencioso."""


def cargar_hints_empresa(
    empresa: EmpresaAuditora,
    ruta_catalogo: Path | None = None,
) -> HintsEmpresa:
    """Devuelve el bloque de hints de la empresa seleccionada.

    Raises:
        EmpresaNoCatalogadaError: si la empresa no está en el catálogo.
        FileNotFoundError: si el archivo de catálogo no existe.
    """
    ruta = ruta_catalogo or settings.catalogo_empresas_path
    with open(ruta, encoding="utf-8") as f:
        catalogo = yaml.safe_load(f)

    if not isinstance(catalogo, dict) or empresa.value not in catalogo:
        disponibles = sorted(catalogo.keys()) if isinstance(catalogo, dict) else []
        raise EmpresaNoCatalogadaError(
            f"La empresa '{empresa.value}' no tiene bloque en el catálogo {ruta}. "
            f"Bloques disponibles: {disponibles}. "
            "Agregar el bloque antes de procesar — no hay fallback al prompt genérico."
        )

    return HintsEmpresa.model_validate(catalogo[empresa.value])
