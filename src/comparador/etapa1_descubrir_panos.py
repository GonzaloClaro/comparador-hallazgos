"""Etapa 1: Descubrimiento de paños y relés en el PDF.

Una sola llamada LLM multimodal con el PDF completo (o con su primer tramo,
si no cabe en el contexto del modelo).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from comparador.config import settings
from comparador.etapa2_normalizar_excel import _CODIGO_PANO, split_guion_entre_codigos
from comparador.llm.client import llamar_llm_estructurado
from comparador.llm.prompts import SYSTEM_DESCUBRIR_PANOS, USER_DESCUBRIR_PANOS
from comparador.schemas import PanoDescubierto, ReleDescubierto
from comparador.troceo import nota_tramo, planificar_tramos


class DescubrimientoInvalidoError(Exception):
    """La Etapa 1 devolvió una estructura inutilizable.

    E3 valida sus paños contra el universo de E1; esta es la defensa simétrica
    para el universo mismo. Sin ella, panos=[] "completa exitosamente" con todo
    el Excel como extra, y un rango de páginas inválido produce recortes vacíos.
    """


class _ReleResponse(BaseModel):
    nombre: str
    evidencia_origen: str
    # default_factory (no default=[]) para que el JSON schema no lleve
    # "default": Anthropic lo trata como opcional y OpenAI strict lo exige.
    sub_panos: list[str] = Field(
        default_factory=list,
        description=(
            "Códigos de paño LITERALES que la lista 'Relé X, Serial: …, Paño Y' "
            "previa a la tabla resumen asigna a este relé, en el orden de la "
            "lista (ej. ['CT1A', 'CT1B']). Un sub-paño que abarca varios paños "
            "va unido por guion ('Paños HT2-ET2' → 'HT2-ET2'; 'Paños BT1 y CT1' "
            "→ 'BT1-CT1'). Vacío si el informe no trae esa lista."
        ),
    )


class _PanoResponse(BaseModel):
    nombre: str
    pagina_inicio: int
    pagina_fin: int
    reles: list[_ReleResponse]


class _ListaPanosResponse(BaseModel):
    panos: list[_PanoResponse]


def _validar_panos(panos: list[_PanoResponse], total_paginas: int) -> None:
    if not panos:
        raise DescubrimientoInvalidoError(
            "La Etapa 1 no encontró ningún paño en el PDF. Sin paños no hay "
            "nada que extraer ni comparar — revisar el informe o el modelo."
        )
    for p in panos:
        if not (1 <= p.pagina_inicio <= p.pagina_fin <= total_paginas):
            raise DescubrimientoInvalidoError(
                f"La Etapa 1 devolvió un rango de páginas inválido para el paño "
                f"'{p.nombre}': {p.pagina_inicio}-{p.pagina_fin} "
                f"(el PDF tiene {total_paginas} páginas)."
            )


# "Paño CT1A", "Paños HT1": la Etapa 3 lo reusa para el relé "BASE (Paño X)".
_PREFIJO_PANO = re.compile(r"^pa[ñn]os?\s+", re.IGNORECASE)
# Separadores de un sub-paño que abarca varios paños: "HT2/ET2", "BT1 y CT1".
_SEPARADOR_SUB_PANO = re.compile(r"\s*/\s*|\s+y\s+")
# Relé con el paño pegado: "SEL 551C (Paño BT1)" (B1 Sonnet Zeta).
_RELE_CON_PANO = re.compile(r"^(?P<base>[^()]+?)\s*\((?P<interior>[^()]+)\)$")


def _componentes_secciones(panos: list[_PanoResponse]) -> frozenset[str]:
    """Componentes de los nombres de sección ("HT1/CT1" → ht1, ct1), en minúsculas."""
    return frozenset(
        codigo.casefold()
        for p in panos
        for parte in p.nombre.split("/")
        for codigo in split_guion_entre_codigos(parte.strip())
    )


def _es_sub_pano_valido(sub_pano: str, componentes: frozenset[str] = frozenset()) -> bool:
    """Código de paño, o compuesto de códigos unidos por guion ("HT2-ET2").

    Misma gramática de código que la Etapa 2: lo que no la cumple (un serial,
    texto libre) no se puede validar después en la Etapa 3. Un código sin
    dígito ("CT", Añañuca) vale solo si es componente de alguna sección.
    """
    return all(
        re.fullmatch(_CODIGO_PANO, codigo) or codigo.casefold() in componentes
        for codigo in split_guion_entre_codigos(sub_pano)
    )


def _normalizar_sub_pano(sub_pano: str, componentes: frozenset[str] = frozenset()) -> str:
    """Quita solo lo inequívoco que rodea al código copiado de la lista.

    "Paño CT1A." → "CT1A", "Paño CT –" → "CT" (prefijo y puntuación o guion
    final del ítem de la lista); "HT2/ET2" y "BT1 y CT1" → "HT2-ET2" /
    "BT1-CT1" (el compuesto va unido por guion, como pide el prompt; la Etapa 3
    lo desdobla igual). Lo que sigue sin ser código queda tal cual, para que la
    validación lo descarte a la vista.
    """
    limpio = _PREFIJO_PANO.sub("", sub_pano.strip()).rstrip(" .,;:-–—")
    partes = [p for p in _SEPARADOR_SUB_PANO.split(limpio) if p]
    if len(partes) > 1 and all(_es_sub_pano_valido(p, componentes) for p in partes):
        return "-".join(partes)
    return limpio


def _limpiar_nombres_reles(panos: list[_PanoResponse]) -> list[str]:
    """Saca el paño pegado al nombre del relé y fusiona los repetidos del paño.

    "SEL 551C (Paño BT1)" y "SEL 551C (Paño CT1)" → un solo "SEL 551C" con
    sub-paños ["BT1", "CT1"]: es lo que pide el prompt, y con el nombre sucio
    la tupla nunca calza con el Excel ni la reparación de la Etapa 3 lo
    reconoce. Solo cuando es inequívoco: el paréntesis dice "Paño(s)" o es un
    componente de la sección — "GE Multilin (F650)" es un modelo, no un paño.
    Un mismo modelo repetido en el paño (Haiku en Alfa) también se fusiona.

    Returns:
        Las reparaciones en texto legible, para la metadata.
    """
    componentes = _componentes_secciones(panos)
    reparaciones: list[str] = []
    for p in panos:
        componentes_seccion = _componentes_secciones([p])
        por_nombre: dict[str, _ReleResponse] = {}
        for r in p.reles:
            m = _RELE_CON_PANO.match(r.nombre.strip())
            if m is not None:
                interior = _normalizar_sub_pano(m["interior"], componentes)
                dice_pano = _PREFIJO_PANO.match(m["interior"].strip()) is not None
                es_componente = interior.casefold() in componentes_seccion
                if _es_sub_pano_valido(interior, componentes) and (dice_pano or es_componente):
                    reparaciones.append(
                        f"paño '{p.nombre}': relé '{r.nombre}' → '{m['base'].strip()}' "
                        f"con sub-paño '{interior}'"
                    )
                    r.nombre = m["base"].strip()
                    r.sub_panos = [interior, *r.sub_panos]
            previo = por_nombre.get(r.nombre)
            if previo is None:
                por_nombre[r.nombre] = r
                continue
            previo.sub_panos = [*previo.sub_panos, *r.sub_panos]
            if r.evidencia_origen not in previo.evidencia_origen:
                previo.evidencia_origen = f"{previo.evidencia_origen} | {r.evidencia_origen}"
            reparaciones.append(
                f"paño '{p.nombre}': relé '{r.nombre}' repetido, fusionado en uno solo"
            )
        p.reles = list(por_nombre.values())
    return reparaciones


def _filtrar_sub_panos(panos: list[_PanoResponse]) -> tuple[list[str], list[str]]:
    """Normaliza los sub-paños de cada relé y deja solo los que son código de paño.

    Returns:
        (descartados, normalizados) en texto legible para la metadata: un
        sub-paño descartado deja al relé con el paño de la sección, y eso nunca
        debe pasar en silencio.
    """
    componentes = _componentes_secciones(panos)
    descartados: list[str] = []
    normalizados: list[str] = []
    for p in panos:
        for r in p.reles:
            validos: dict[str, str] = {}
            for crudo in (s.strip() for s in r.sub_panos if s.strip()):
                sub = _normalizar_sub_pano(crudo, componentes)
                if not _es_sub_pano_valido(sub, componentes):
                    descartados.append(
                        f"paño '{p.nombre}', relé '{r.nombre}': sub-paño '{crudo}' "
                        "no es un código de paño"
                    )
                    continue
                if sub != crudo:
                    normalizados.append(
                        f"paño '{p.nombre}', relé '{r.nombre}': sub-paño '{crudo}' → '{sub}'"
                    )
                validos.setdefault(sub.casefold(), sub)
            r.sub_panos = list(validos.values())
    return descartados, normalizados


def descubrir_panos(ruta_pdf: Path) -> tuple[list[PanoDescubierto], dict[str, Any]]:
    """Descubre los paños y relés presentes en un PDF de auditoría.

    Si el informe no cabe en el contexto, se lee solo el primer tramo: las
    tablas resumen van al inicio en todos los formatos conocidos (págs 4-36 en
    los 7 informes reales). Como el primer tramo arranca en la página 1, las
    páginas devueltas ya son absolutas. Si algún paño termina justo en el borde
    del tramo, la tabla podría continuar fuera: queda advertido en la metadata.

    Returns:
        Tupla de (lista de paños descubiertos, metadata de la llamada LLM).
    """
    tramo = planificar_tramos(
        ruta_pdf, modelo=settings.modelo_extraccion,
        system_prompt=SYSTEM_DESCUBRIR_PANOS, user_prompt=USER_DESCUBRIR_PANOS,
    )[0]
    user_prompt = USER_DESCUBRIR_PANOS
    if not tramo.es_completo:
        user_prompt += nota_tramo(tramo)

    respuesta, metadata = llamar_llm_estructurado(
        modelo=settings.modelo_extraccion,
        system_prompt=SYSTEM_DESCUBRIR_PANOS,
        user_prompt=user_prompt,
        response_model=_ListaPanosResponse,
        pdf_base64=tramo.pdf_base64,
        pdf_filename=ruta_pdf.name,
    )

    try:
        _validar_panos(respuesta.panos, total_paginas=tramo.pagina_fin)
    except DescubrimientoInvalidoError as exc:
        # La respuesta inválida ya se pagó y es justo lo que explica el error:
        # viaja en la excepción para que el pipeline la persista (invariante 20).
        exc.llm_metadata = {  # type: ignore[attr-defined]
            **metadata, "llamada_fallida": True, "error": str(exc),
        }
        raise
    reparaciones = _limpiar_nombres_reles(respuesta.panos)
    descartados, normalizados = _filtrar_sub_panos(respuesta.panos)
    reparaciones += normalizados
    if reparaciones:
        metadata["reparaciones"] = reparaciones
    if descartados:
        metadata["sub_panos_descartados"] = descartados
    if not tramo.es_completo:
        metadata["troceo"] = {
            "paginas_leidas": [tramo.pagina_inicio, tramo.pagina_fin],
            "total_paginas": tramo.total_paginas,
        }
        en_borde = [p.nombre for p in respuesta.panos if p.pagina_fin >= tramo.pagina_fin]
        if en_borde:
            metadata["troceo"]["advertencia"] = (
                f"Los paños {en_borde} terminan en la última página leída "
                f"({tramo.pagina_fin}); su tabla resumen podría continuar fuera del tramo."
            )

    panos = [
        PanoDescubierto(
            nombre=p.nombre,
            pagina_inicio=p.pagina_inicio,
            pagina_fin=p.pagina_fin,
            reles=[
                ReleDescubierto(
                    nombre=r.nombre,
                    evidencia_origen=r.evidencia_origen,
                    sub_panos=r.sub_panos,
                )
                for r in p.reles
            ],
        )
        for p in respuesta.panos
    ]

    return panos, metadata
