"""Troceo de PDFs que no caben en el contexto del modelo.

Con los modelos Claude de 1M de contexto, un informe entra entero hasta ~900k
tokens (umbral configurable) y 600 páginas. Los informes más largos (Beta:
456 págs ≈ 1.04M tokens) se parten en tramos de páginas consecutivas, cada uno
verificado con count_tokens. Si el modelo no es Claude no se trocea: ahí rigen
los límites de convertir.adecuar_pdf_para_llm.
"""

from __future__ import annotations

import base64
import io
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter

from comparador.config import settings
from comparador.llm.client import (
    ERRORES_ACCESO_MODELO,
    contar_tokens_pdf,
    pdf_a_base64,
    pdf_cabe_inline,
)

MAX_PAGINAS_POR_REQUEST = 600
_MAX_ITERACIONES = 4


@dataclass(frozen=True)
class Tramo:
    pagina_inicio: int  # 1-indexed, posición física en el PDF completo
    pagina_fin: int
    total_paginas: int
    pdf_base64: str
    tokens: int | None

    @property
    def es_completo(self) -> bool:
        return self.pagina_inicio == 1 and self.pagina_fin == self.total_paginas


def _recortar_base64(reader: PdfReader, inicio: int, fin: int) -> str:
    writer = PdfWriter()
    for i in range(inicio - 1, fin):
        writer.add_page(reader.pages[i])
    buf = io.BytesIO()
    writer.write(buf)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _contar_rango(
    reader: PdfReader, inicio: int, fin: int, b64: str, *,
    modelo: str, system_prompt: str, user_prompt: str,
) -> int:
    """Tokens de las páginas inicio..fin con el prompt.

    count_tokens solo acepta PDFs inline (no Files API): si el rango no cabe,
    se bisecta y se suman las mitades. La suma cuenta el prompt una vez por
    mitad — sobreestima unos miles de tokens, en la dirección segura (trocear
    de más nunca hace perder páginas).
    """
    if pdf_cabe_inline(b64):
        return contar_tokens_pdf(
            modelo=modelo, system_prompt=system_prompt, user_prompt=user_prompt, pdf_base64=b64,
        )
    if inicio == fin:
        raise RuntimeError(f"La página {inicio} sola supera el tamaño que count_tokens acepta")
    medio = (inicio + fin) // 2
    return sum(
        _contar_rango(
            reader, i, f, _recortar_base64(reader, i, f),
            modelo=modelo, system_prompt=system_prompt, user_prompt=user_prompt,
        )
        for i, f in ((inicio, medio), (medio + 1, fin))
    )


def planificar_tramos(
    ruta_pdf: Path, *, modelo: str, system_prompt: str, user_prompt: str
) -> list[Tramo]:
    """Un solo tramo si el PDF cabe; si no, tramos de páginas que caben.

    El corte es proporcional por páginas y cada tramo se verifica con
    count_tokens: si alguno se pasa del umbral, se aumenta la cantidad de
    tramos y se re-corta (las páginas densas no se reparten parejo).

    count_tokens va directo al SDK (no por el router), así que aplica acá la
    misma política de fallback de modelo que llamar_llm_estructurado: ante un
    error de acceso se planifica para MODELO_EXTRACCION_FALLBACK.
    """
    try:
        return _planificar(ruta_pdf, modelo, system_prompt, user_prompt)
    except ERRORES_ACCESO_MODELO:
        fallback = settings.modelo_extraccion_fallback
        if not fallback or fallback == modelo:
            raise
        return planificar_tramos(
            ruta_pdf, modelo=fallback, system_prompt=system_prompt, user_prompt=user_prompt,
        )


def _planificar(ruta_pdf: Path, modelo: str, system_prompt: str, user_prompt: str) -> list[Tramo]:
    reader = PdfReader(ruta_pdf)
    total = len(reader.pages)
    completo = pdf_a_base64(ruta_pdf)
    if not modelo.startswith("claude"):
        # Otros proveedores: rigen los límites de convertir.adecuar_pdf_para_llm.
        return [Tramo(1, total, total, completo, None)]
    contexto = {"modelo": modelo, "system_prompt": system_prompt, "user_prompt": user_prompt}
    tokens: int | None = None
    if total <= MAX_PAGINAS_POR_REQUEST:
        # Sobre 600 páginas se trocea igual: no tiene sentido contar el total.
        tokens = _contar_rango(reader, 1, total, completo, **contexto)
        if tokens <= settings.umbral_tokens_troceo:
            return [Tramo(1, total, total, completo, tokens)]

    n = max(
        math.ceil((tokens or 0) / settings.tokens_por_tramo),
        math.ceil(total / MAX_PAGINAS_POR_REQUEST),
        2,
    )
    for _ in range(_MAX_ITERACIONES):
        por_tramo = math.ceil(total / n)
        tramos: list[Tramo] = []
        for inicio in range(1, total + 1, por_tramo):
            fin = min(total, inicio + por_tramo - 1)
            b64 = _recortar_base64(reader, inicio, fin)
            t = _contar_rango(reader, inicio, fin, b64, **contexto)
            tramos.append(Tramo(inicio, fin, total, b64, t))
        if all((t.tokens or 0) <= settings.umbral_tokens_troceo for t in tramos):
            return tramos
        n += 1
    raise RuntimeError(
        f"No se pudo trocear {ruta_pdf.name} ({total} págs, {tokens} tokens) en tramos "
        f"bajo {settings.umbral_tokens_troceo} tokens tras {_MAX_ITERACIONES} intentos."
    )


def nota_tramo(tramo: Tramo) -> str:
    """Contexto que se agrega al prompt cuando el modelo ve solo un tramo."""
    return (
        f"\n\nIMPORTANTE — VES SOLO UN TRAMO DEL INFORME: este PDF contiene las páginas "
        f"{tramo.pagina_inicio} a {tramo.pagina_fin} de un informe de "
        f"{tramo.total_paginas} páginas (el informe no cabe completo en una sola "
        f"lectura). La página 1 de este PDF es la página {tramo.pagina_inicio} del "
        "informe. Reporta las páginas como posición dentro de ESTE PDF."
    )


def a_pagina_absoluta(pagina: int, tramo: Tramo) -> int:
    """Una página citada (posición en el tramo) en el PDF completo.

    Solo se desplaza una posición válida dentro del tramo: un número mayor que
    su largo no es una posición en este PDF (el modelo citó la página absoluta
    o la impresa) y desplazarlo lo corrompería.
    """
    if 1 <= pagina <= tramo.pagina_fin - tramo.pagina_inicio + 1:
        return pagina + tramo.pagina_inicio - 1
    return pagina


def a_paginas_absolutas(paginas: str | None, tramo: Tramo) -> str | None:
    """Re-numera las páginas citadas (posición en el tramo) al PDF completo.

    Solo desplaza números que son posiciones válidas dentro del tramo: uno
    mayor que el largo del tramo no es una posición en este PDF (el modelo
    citó la página absoluta o la impresa) y desplazarlo lo corrompería.
    """
    if not paginas or tramo.pagina_inicio == 1:
        return paginas
    return re.sub(r"\d+", lambda m: str(a_pagina_absoluta(int(m.group()), tramo)), paginas)


def info_tramos(tramos: list[Tramo]) -> dict[str, Any]:
    """Resumen persistible del troceo (para metadata y la advertencia de la UI)."""
    return {
        "total_paginas": tramos[0].total_paginas,
        "tramos": [
            {"paginas": [t.pagina_inicio, t.pagina_fin], "tokens": t.tokens}
            for t in tramos
        ],
    }
