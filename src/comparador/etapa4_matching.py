"""Etapa 4: Matching de hallazgos por (paño, relé).

Proceso (DISENO §5):
  4a. Matching determinístico por unicidad de clasificación (sin LLM).
  4b. Matching semántico (embeddings + LLM-as-judge) para lo restante.
  4c. Detección de diferencias en cada match (descripción → acción → calificación).
  4d. Marcado de faltantes y extras, seguido del desempate por acción
      correctiva entre hallazgos de descripción idéntica (decide quién
      empareja con quién y qué fila queda faltante/extra).
  4e. Pasada final sobre los pares: control determinístico de polaridad
      (Cumple vs No cumple) y de códigos o números cambiados sobre el umbral
      (M43), y juez LLM de redacción para los campos de texto bajo el umbral
      de similitud (el Excel parafrasea el PDF).
"""

from __future__ import annotations

import itertools
import re
import unicodedata
from collections import Counter, defaultdict, deque
from collections.abc import Callable, Iterable
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, field_validator

from comparador.config import settings

# Re-exportados («as»): son los puntos que reemplazan los tests y los que usa
# reproducir_e4 (juez real del modo mixto, vectores de --solo-vectores), siempre
# resueltos en este módulo en cada llamada.
from comparador.llm.client import llamar_llm_estructurado as llamar_llm_estructurado
from comparador.llm.embeddings import calcular_embeddings as calcular_embeddings
from comparador.llm.embeddings import similitud_coseno, top_k_similares
from comparador.llm.prompts import (
    SYSTEM_JUEZ_REDACCION,
    system_juez_matching,
    user_juez_matching,
    user_juez_redaccion,
)
from comparador.schemas import (
    CampoDiferente,
    Diferencia,
    EquivalenciaRedaccion,
    EstadoHallazgo,
    Hallazgo,
    MatchResult,
    TipoMatch,
)


class JuezInvalidoError(RuntimeError):
    """El juez LLM devolvió una respuesta estructuralmente inválida.

    Lleva la metadata LLM acumulada hasta el fallo para que el caller la
    persista (invariante 20): los raw de las llamadas ya pagadas — incluida
    la respuesta inválida que motiva el error — no pueden perderse justo en
    el caso que este error existe para diagnosticar.
    """

    def __init__(self, mensaje: str, llm_metadata: list[dict[str, Any]]) -> None:
        super().__init__(mensaje)
        self.llm_metadata = llm_metadata


class JuezNoLlamadoError(RuntimeError):
    """El llamador de los jueces (`ejecutar_matching(llamar=...)`) no hizo la
    llamada, p. ej. la caché estricta de cache_jueces no la tiene: no se envió
    ni se pagó, así que no queda registrada como llamada fallida."""


class VectoresFaltantesError(RuntimeError):
    """Repetición estricta de E4 (`vectores_estrictos`): falta el vector de un
    texto y no se llama a la API de embeddings para calcularlo."""


# Texto → vector de embeddings de E4 (M70): los del run se guardan en
# etapa4_embeddings.npz (persistence.guardar_vectores) para repetir E4 con los
# mismos vectores sin volver a pagarlos.
Vectores = dict[str, NDArray[np.float64]]

# Llamador de los jueces de una ejecución (ejecutar_matching(llamar=...)), p. ej.
# la caché de jueces al repetir E4 (cache_jueces). Con None, _llamar_juez usa
# llamar_llm_estructurado de este módulo, resuelto en cada llamada: es el punto
# que reemplazan los tests.
_LLAMADOR: ContextVar[Callable[..., tuple[Any, dict[str, Any]]] | None] = ContextVar(
    "llamador_jueces_e4", default=None)


def _validar_confianza(v: float) -> float:
    if not 0 <= v <= 99:
        raise ValueError(
            f"Confianza del juez fuera del rango 0-99: {v}. "
            "El prompt pide porcentaje 0-99."
        )
    return v


class _JuezResponse(BaseModel):
    indice_candidato: int | None
    confianza: float
    justificacion: str

    # Validator (no Field ge/le): los bounds no van al JSON schema que se envía
    # al LLM — OpenAI strict mode rechaza minimum/maximum — pero sí se validan
    # client-side al parsear la respuesta, en ambos proveedores.
    @field_validator("confianza")
    @classmethod
    def _confianza_en_rango(cls, v: float) -> float:
        return _validar_confianza(v)


def _juez_justifica_primero() -> type[BaseModel]:
    """M32 (JUEZ_JUSTIFICA_PRIMERO): el mismo schema con la justificación primero.
    Conserva el nombre `_JuezResponse`, que la caché de los jueces usa en su clave
    (el hash del schema, que ve el orden de los campos, separa una de la otra)."""

    class _JuezResponse(BaseModel):
        justificacion: str
        indice_candidato: int | None
        confianza: float

        @field_validator("confianza")
        @classmethod
        def _confianza_en_rango(cls, v: float) -> float:
            return _validar_confianza(v)

    return _JuezResponse


_JuezResponseJustificaPrimero = _juez_justifica_primero()


def _respuesta_juez() -> type[BaseModel]:
    """El schema de la respuesta del juez de emparejamiento según el interruptor."""
    return _JuezResponseJustificaPrimero if settings.juez_justifica_primero else _JuezResponse


def clave_tupla(pano: str, rele: str) -> tuple[str, str]:
    """Clave de agrupación tolerante a grafías: el PDF dice "SEL-787" donde
    el Excel dice "SEL 787" — misma tupla. Se comparan sin separadores ni case.
    Pública: el GT del comparador (comparador.adjudicacion) agrupa igual.
    """
    def norm(texto: str) -> str:
        return texto.replace("-", "").replace(" ", "").replace("_", "").casefold()

    return (norm(pano), norm(rele))


def _clave_tupla(h: Hallazgo) -> tuple[str, str]:
    return clave_tupla(h.pano, h.rele)


def _agrupar_por_pano_rele(
    hallazgos: list[Hallazgo],
) -> dict[tuple[str, str], list[Hallazgo]]:
    grupos: dict[tuple[str, str], list[Hallazgo]] = defaultdict(list)
    for h in hallazgos:
        grupos[_clave_tupla(h)].append(h)
    return grupos


def _comparar_campo_semantico(
    campo: CampoDiferente,
    valor_pdf: str | None,
    valor_excel: str | None,
    threshold: float,
    emb_cache: dict[str, np.ndarray[Any, np.dtype[np.float64]]],
) -> Diferencia | None:
    """Compara un campo de texto libre. None si no hay diferencia relevante."""
    # None = la fuente no trae el campo: no comparable, no es diferencia.
    if valor_pdf is None or valor_excel is None:
        return None

    if valor_pdf == valor_excel:
        return None

    # Vacío en un lado y con contenido en el otro: diferencia automática,
    # sin pasar por embeddings (la similitud contra "" no está definida).
    if bool(valor_pdf.strip()) != bool(valor_excel.strip()):
        lado_lleno = "PDF" if valor_pdf.strip() else "Excel"
        lado_vacio = "Excel" if lado_lleno == "PDF" else "PDF"
        return Diferencia(
            campo=campo,
            valor_pdf=valor_pdf,
            valor_excel=valor_excel,
            detalle=f"Con contenido solo en el {lado_lleno} (vacío en el {lado_vacio})",
        )

    emb_pdf = emb_cache.get(valor_pdf)
    emb_excel = emb_cache.get(valor_excel)
    if emb_pdf is None or emb_excel is None:
        return Diferencia(
            campo=campo,
            valor_pdf=valor_pdf,
            valor_excel=valor_excel,
            detalle="No se pudo comparar automáticamente (sin embeddings); revisar manualmente",
        )

    similitud = similitud_coseno(emb_pdf, emb_excel)
    if similitud < threshold:
        return Diferencia(
            campo=campo,
            valor_pdf=valor_pdf,
            valor_excel=valor_excel,
            detalle=_detalle_bajo_umbral(similitud, threshold),
        )
    return None


def _detalle_bajo_umbral(similitud: float, threshold: float) -> str:
    return f"Similitud semántica {similitud:.2f}, bajo el umbral de coincidencia {threshold:.2f}"


def _detectar_diferencias(
    h_pdf: Hallazgo,
    h_excel: Hallazgo,
    emb_cache: dict[str, np.ndarray[Any, np.dtype[np.float64]]],
) -> list[Diferencia]:
    """Compara los tres campos en orden: descripción → acción → calificación."""
    diferencias: list[Diferencia] = []

    diff_desc = _comparar_campo_semantico(
        CampoDiferente.DESCRIPCION,
        h_pdf.descripcion, h_excel.descripcion,
        settings.threshold_descripcion, emb_cache,
    )
    if diff_desc:
        diferencias.append(diff_desc)

    diff_accion = _comparar_campo_semantico(
        CampoDiferente.ACCION_CORRECTIVA,
        h_pdf.accion_correctiva, h_excel.accion_correctiva,
        settings.threshold_accion, emb_cache,
    )
    if diff_accion:
        diferencias.append(diff_accion)

    # Solo comparable si ambos lados traen calificación (los Excel de algunas
    # auditoras no la incluyen — sin dato no hay diferencia que reportar).
    if (
        h_pdf.calificacion is not None
        and h_excel.calificacion is not None
        and h_pdf.calificacion != h_excel.calificacion
    ):
        diferencias.append(Diferencia(
            campo=CampoDiferente.CALIFICACION,
            valor_pdf=h_pdf.calificacion.value,
            valor_excel=h_excel.calificacion.value,
        ))

    return diferencias


# Lista desplegable oficial de la plantilla SEC ('Tabla de Hallazgos'!F1:F11).
_CLASIFICACIONES_SEC = (
    "Verificación DUF",
    "Verificación ECAP",
    "Ver. Coord. de Protecciones",
    "Ver. 87B/Tpo Máx Despeje Falla",
    "Ver. Acceso, Registro y Sincr.",
    "Prueba Oper. de Protección",
    "Prueba Apert. de Interruptor",
    "Prueba Estabilidad 87T",
    "Prueba Pendiente",
    "Servicios Auxiliares CA-CC",
    "Otros",
)

# Grafías vistas en Excel reales (Zeta, Alfa) y en la hoja Definiciones
# de la plantilla, que difieren de la lista desplegable.
_ALIAS_CLASIFICACION = {
    "Acceso, Registro y Sincr.": "Ver. Acceso, Registro y Sincr.",
    "Coord. de Protecciones": "Ver. Coord. de Protecciones",
    "Ver. Coor. de Protecciones": "Ver. Coord. de Protecciones",
    "Ver. Acceso, Registro y Sinc.": "Ver. Acceso, Registro y Sincr.",
    "Prueba Apert. Interruptor": "Prueba Apert. de Interruptor",
}


def _normalizar_texto(texto: str) -> str:
    return " ".join(texto.split()).casefold()


def _normalizar_clasificacion(texto: str) -> str:
    return _normalizar_texto(texto).rstrip(". ")


_ALIAS_CLASIFICACION_NORMALIZADO = {
    _normalizar_clasificacion(alias): _normalizar_clasificacion(canonica)
    for alias, canonica in _ALIAS_CLASIFICACION.items()
}


def _clave_clasificacion(h: Hallazgo) -> str:
    """Clave de unicidad (4a): la categoría SEC canónica, no el literal.

    El literal de `h.clasificacion` no se toca (trazabilidad): el alias solo
    evita que "Acceso, Registro y Sincr." y "Ver. Acceso, Registro y Sincr."
    cuenten como clasificaciones distintas y rompan la unicidad.
    """
    clave = _normalizar_clasificacion(h.clasificacion)
    return _ALIAS_CLASIFICACION_NORMALIZADO.get(clave, clave)


_RE_CANDIDATO_JUEZ = re.compile(
    r"candidatos?\s*\[\d+\](?:\s*(?:y|,)\s*\[\d+\])*", re.IGNORECASE
)


def _limpiar_justificacion_juez(justificacion: str) -> str:
    """Reemplaza las referencias del juez a "candidato [N]" por "Excel".

    El prompt (SYSTEM_JUEZ_MATCHING) le muestra al LLM una lista de candidatos
    numerada y le enseña a justificar citando ese índice ("el candidato [2]
    registra..."). Ese índice es un artefacto efímero de esta llamada — no
    significa nada para el revisor, que en el detalle ya ve directamente cuál
    es el hallazgo del Excel emparejado. Se normaliza a una palabra estable.
    """
    return _RE_CANDIDATO_JUEZ.sub("Excel", justificacion)


def _match_por_unicidad(
    pano: str,
    rele: str,
    pdf_tupla: list[Hallazgo],
    excel_tupla: list[Hallazgo],
    emb_cache: dict[str, np.ndarray[Any, np.dtype[np.float64]]],
) -> tuple[list[MatchResult], list[Hallazgo], list[Hallazgo]]:
    """4a: clasificación que aparece exactamente UNA vez en ambos lados de la
    tupla → match seguro sin LLM (defensa contra falsos positivos del semántico).

    Returns:
        Tupla de (matches por unicidad, restantes PDF, restantes Excel).
    """
    conteo_pdf = Counter(_clave_clasificacion(h) for h in pdf_tupla)
    conteo_excel = Counter(_clave_clasificacion(h) for h in excel_tupla)

    resultados: list[MatchResult] = []
    matcheados_pdf: set[int] = set()
    matcheados_excel: set[int] = set()

    for i, h_pdf in enumerate(pdf_tupla):
        clave = _clave_clasificacion(h_pdf)
        if conteo_pdf[clave] != 1 or conteo_excel[clave] != 1:
            continue

        idx_excel, h_excel = next(
            (j, h) for j, h in enumerate(excel_tupla) if _clave_clasificacion(h) == clave
        )

        diffs = _detectar_diferencias(h_pdf, h_excel, emb_cache)
        estado = EstadoHallazgo.COINCIDE if not diffs else EstadoHallazgo.DIFIERE

        etiqueta = f"'{h_pdf.clasificacion}'"
        if h_pdf.clasificacion.strip() != h_excel.clasificacion.strip():
            etiqueta += f" (Excel: '{h_excel.clasificacion}')"

        resultados.append(MatchResult(
            pano=pano, rele=rele,
            estado=estado,
            tipo_match=TipoMatch.UNICIDAD,
            confianza=1.0,
            justificacion=(
                f"Única {etiqueta} en paño {pano} / relé {rele} "
                "en ambos archivos — emparejamiento determinístico, sin otro "
                "candidato posible."
            ),
            hallazgo_pdf=h_pdf, hallazgo_excel=h_excel,
            diferencias=diffs,
        ))
        matcheados_pdf.add(i)
        matcheados_excel.add(idx_excel)

    restantes_pdf = [h for i, h in enumerate(pdf_tupla) if i not in matcheados_pdf]
    restantes_excel = [h for j, h in enumerate(excel_tupla) if j not in matcheados_excel]
    return resultados, restantes_pdf, restantes_excel


_NOTA_DESEMPATE = "Desempate por acción correctiva entre hallazgos de descripción idéntica."
_MAX_N_PERMUTACIONES = 6
# Margen contra ruido de punto flotante en sumas de cosenos.
_EPS = 1e-9


def _similitud_accion(
    accion_pdf: str | None,
    accion_excel: str | None,
    emb_cache: dict[str, np.ndarray[Any, np.dtype[np.float64]]],
) -> float:
    if accion_pdf is None or accion_excel is None:
        return 0.0
    if not accion_pdf.strip() or not accion_excel.strip():
        return 0.0
    if accion_pdf == accion_excel:
        return 1.0
    emb_pdf = emb_cache.get(accion_pdf)
    emb_excel = emb_cache.get(accion_excel)
    if emb_pdf is None or emb_excel is None:
        return 0.0
    return similitud_coseno(emb_pdf, emb_excel)


def _mejor_asignacion(
    similitudes: list[list[float]],
    actual: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Elige len(actual) pares (PDF i, Excel j) que maximizan la similitud total.

    `similitudes` es PDF × Excel y puede ser rectangular: con más filas de un
    lado, la asignación decide también cuáles quedan sin par. Exhaustiva si
    ningún lado supera _MAX_N_PERMUTACIONES, greedy sobre eso. Entre óptimos
    prefiere el que conserva más pares de `actual` (lo que decidió el juez),
    y sin mejora estricta devuelve `actual` tal cual.
    """
    n_pdf = len(similitudes)
    n_excel = len(similitudes[0]) if similitudes else 0
    m = len(actual)
    conservados = set(actual)

    def total(pares: Iterable[tuple[int, int]]) -> float:
        return sum(similitudes[i][j] for i, j in pares)

    if max(n_pdf, n_excel) <= _MAX_N_PERMUTACIONES:
        candidatas = [
            list(zip(filas, columnas, strict=True))
            for filas in itertools.combinations(range(n_pdf), m)
            for columnas in itertools.permutations(range(n_excel), m)
        ]
        mejor = max(total(c) for c in candidatas)
        candidata = max(
            (c for c in candidatas if total(c) >= mejor - _EPS),
            key=lambda c: len(conservados.intersection(c)),
        )
    else:
        candidata = []
        usados_pdf: set[int] = set()
        usados_excel: set[int] = set()
        pares = sorted(
            ((i, j) for i in range(n_pdf) for j in range(n_excel)),
            key=lambda par: (-similitudes[par[0]][par[1]], par not in conservados),
        )
        for i, j in pares:
            if len(candidata) == m:
                break
            if i not in usados_pdf and j not in usados_excel:
                candidata.append((i, j))
                usados_pdf.add(i)
                usados_excel.add(j)

    return sorted(candidata) if total(candidata) > total(actual) + _EPS else actual


def _desempatar_por_accion(
    resultados: list[MatchResult],
    emb_cache: dict[str, np.ndarray[Any, np.dtype[np.float64]]],
) -> list[MatchResult]:
    """Reparte pares, faltantes y extras de descripción idéntica por acción.

    El juez solo ve descripciones: con 2+ filas de descripción idéntica
    (Beta E1–E9: misma descripción ECAP, una con acción "disponer
    ECAP"/Relevante y otra "cargar Print Out"/Menor) su elección es
    arbitraria. Un cruce fabrica falsos "difiere" en acción y calificación y,
    si un lado omite una de esas filas, además deja el faltante/extra sobre la
    fila equivocada — justo la omisión que la herramienta debe detectar.

    Por cada descripción normalizada se agrupan los pares cuya descripción es
    idéntica en PDF y Excel, más los faltantes y extras con esa descripción, y
    se eligen tantos pares como hizo el juez maximizando la similitud de
    acción. Un par con descripciones distintas no entra a ningún grupo: la
    descripción sigue estableciendo el match (invariante 15); la acción solo
    desempata.

    El veredicto del juez (tipo, confianza, justificación) es sobre la
    descripción, idéntica en todo el grupo: cada PDF que sigue emparejado
    conserva el suyo y el que pasa de faltante a emparejado hereda el del PDF
    que desplazó.

    No aplica a los pares por unicidad (4a): unicidad = una sola fila de esa
    clasificación por lado, no hay socio alternativo con el que permutar.

    Args:
        resultados: pares, faltantes y extras de 4b/4d de UNA tupla.
    """
    grupos: dict[str, list[int]] = defaultdict(list)
    for k, r in enumerate(resultados):
        descripciones = {
            _normalizar_texto(h.descripcion)
            for h in (r.hallazgo_pdf, r.hallazgo_excel)
            if h is not None
        }
        if len(descripciones) == 1:
            grupos[descripciones.pop()].append(k)

    salida = list(resultados)
    for indices in grupos.values():
        en_par = [
            k for k in indices
            if resultados[k].hallazgo_pdf is not None and resultados[k].hallazgo_excel is not None
        ]
        if not en_par:
            continue
        # Pares primero en ambos lados: la asignación del juez es (i, i), i < m.
        pos_pdf = en_par + [k for k in indices if resultados[k].hallazgo_excel is None]
        pos_excel = en_par + [k for k in indices if resultados[k].hallazgo_pdf is None]
        pdfs = [h for k in pos_pdf if (h := resultados[k].hallazgo_pdf) is not None]
        excels = [h for k in pos_excel if (h := resultados[k].hallazgo_excel) is not None]
        m = len(en_par)
        actual = [(i, i) for i in range(m)]

        similitudes = [
            [_similitud_accion(p.accion_correctiva, e.accion_correctiva, emb_cache) for e in excels]
            for p in pdfs
        ]
        nuevos = _mejor_asignacion(similitudes, actual)
        if nuevos == actual:
            continue

        socio = dict(nuevos)
        veredictos_libres = [resultados[pos_pdf[i]] for i in range(m) if i not in socio]

        for i, k in enumerate(pos_pdf):
            j = socio.get(i)
            if (i < m and j == i) or (i >= m and j is None):
                continue
            original = resultados[k]
            if j is None:
                salida[k] = MatchResult(
                    pano=original.pano, rele=original.rele,
                    estado=EstadoHallazgo.FALTA_EN_EXCEL,
                    tipo_match=TipoMatch.SIN_MATCH,
                    confianza=0.0,
                    justificacion=(
                        f"Hallazgo del PDF sin correspondencia en Excel. {_NOTA_DESEMPATE}"
                    ),
                    hallazgo_pdf=pdfs[i], hallazgo_excel=None,
                )
                continue
            base = original if i < m else veredictos_libres.pop(0)
            diffs = _detectar_diferencias(pdfs[i], excels[j], emb_cache)
            salida[k] = base.model_copy(update={
                "hallazgo_pdf": pdfs[i],
                "hallazgo_excel": excels[j],
                "diferencias": diffs,
                "estado": EstadoHallazgo.COINCIDE if not diffs else EstadoHallazgo.DIFIERE,
                "justificacion": f"{base.justificacion} {_NOTA_DESEMPATE}".strip(),
            })

        # Los extras originales que siguen sin par quedan donde estaban; los
        # Excel que perdieron su par ocupan el lugar de los extras que lo ganaron.
        emparejados_excel = set(socio.values())
        lugares_libres = [pos_excel[j] for j in range(m, len(excels)) if j in emparejados_excel]
        desplazados = [j for j in range(m) if j not in emparejados_excel]
        for k, j in zip(lugares_libres, desplazados, strict=True):
            salida[k] = MatchResult(
                pano=resultados[k].pano, rele=resultados[k].rele,
                estado=EstadoHallazgo.EXTRA_EN_EXCEL,
                tipo_match=TipoMatch.SIN_MATCH,
                confianza=0.0,
                justificacion=f"Hallazgo en Excel sin correspondencia en PDF. {_NOTA_DESEMPATE}",
                hallazgo_pdf=None, hallazgo_excel=excels[j],
            )

    return salida


def _match_por_descripcion_identica(
    pano: str,
    rele: str,
    pdf_tupla: list[Hallazgo],
    excel_tupla: list[Hallazgo],
    emb_cache: dict[str, np.ndarray[Any, np.dtype[np.float64]]],
) -> tuple[list[MatchResult], list[Hallazgo], list[Hallazgo]]:
    """4a' (M30, DESCRIPCION_IDENTICA): descripción idéntica sin juez.

    Después de la unicidad y antes del juez: dentro de la tupla, el hallazgo
    del PDF y la fila del Excel con la misma descripción (_normalizar_texto:
    solo espacios y mayúsculas) se emparejan sin LLM; en B2 el juez siempre
    eligió ese candidato cuando lo había. Con varias filas de la misma
    descripción se reparten como en el desempate por acción (_mejor_asignacion
    sobre la similitud de acción) y en empate gana el orden del informe y del
    Excel: el resultado no depende del juez ni del orden de 4b. Lo que sobra de
    un grupo sigue al juez, sin las filas ya tomadas.

    Returns:
        Tupla de (pares, restantes PDF, restantes Excel).
    """
    filas_por_desc: dict[str, list[int]] = defaultdict(list)
    for j, h in enumerate(excel_tupla):
        filas_por_desc[_normalizar_texto(h.descripcion)].append(j)
    pdf_por_desc: dict[str, list[int]] = defaultdict(list)
    for i, h in enumerate(pdf_tupla):
        pdf_por_desc[_normalizar_texto(h.descripcion)].append(i)

    pares: list[tuple[int, int, bool]] = []
    for desc, idx_pdf in pdf_por_desc.items():
        idx_excel = filas_por_desc.get(desc)
        if not desc or not idx_excel:
            continue
        similitudes = [
            [_similitud_accion(pdf_tupla[i].accion_correctiva,
                               excel_tupla[j].accion_correctiva, emb_cache) for j in idx_excel]
            for i in idx_pdf
        ]
        orden = [(k, k) for k in range(min(len(idx_pdf), len(idx_excel)))]
        repartido = len(idx_pdf) > 1 or len(idx_excel) > 1
        pares.extend((idx_pdf[a], idx_excel[b], repartido)
                     for a, b in _mejor_asignacion(similitudes, orden))

    resultados: list[MatchResult] = []
    for i, j, repartido in sorted(pares):
        h_pdf, h_excel = pdf_tupla[i], excel_tupla[j]
        diffs = _detectar_diferencias(h_pdf, h_excel, emb_cache)
        justificacion = (
            f"Descripción idéntica en el PDF y el Excel en paño {pano} / relé {rele} — "
            "emparejamiento determinístico, sin juez."
        )
        if repartido:
            justificacion += (
                " Hay varias filas con esa descripción: se repartieron por acción correctiva "
                "(en empate, en el orden del informe y del Excel)."
            )
        resultados.append(MatchResult(
            pano=pano, rele=rele,
            estado=EstadoHallazgo.COINCIDE if not diffs else EstadoHallazgo.DIFIERE,
            tipo_match=TipoMatch.DESCRIPCION_IDENTICA,
            confianza=1.0,
            justificacion=justificacion,
            hallazgo_pdf=h_pdf, hallazgo_excel=h_excel,
            diferencias=diffs,
        ))

    tomados_pdf = {i for i, _, _ in pares}
    tomados_excel = {j for _, j, _ in pares}
    restantes_pdf = [h for i, h in enumerate(pdf_tupla) if i not in tomados_pdf]
    restantes_excel = [h for j, h in enumerate(excel_tupla) if j not in tomados_excel]
    return resultados, restantes_pdf, restantes_excel


def textos_a_embeber(hallazgos_pdf: list[Hallazgo], hallazgos_excel: list[Hallazgo]) -> list[str]:
    """Textos únicos que E4 embebe, en el orden en que los pide: descripción y
    acción correctiva del PDF y después del Excel, sin las filas transversales
    (no entran al matching)."""
    textos_unicos: list[str] = []
    seen: set[str] = set()

    for h in hallazgos_pdf + [h for h in hallazgos_excel if not h.es_transversal]:
        for texto in [h.descripcion, h.accion_correctiva]:
            # None (campo ausente) y "" no se embeben: la API rechaza vacíos y
            # esos casos se resuelven sin similitud semántica.
            if texto and texto.strip() and texto not in seen:
                textos_unicos.append(texto)
                seen.add(texto)
    return textos_unicos


def _construir_cache_embeddings(
    hallazgos_pdf: list[Hallazgo],
    hallazgos_excel: list[Hallazgo],
    vectores: Vectores | None = None,
    estrictos: bool = False,
) -> tuple[dict[str, np.ndarray[Any, np.dtype[np.float64]]], dict[str, Any] | None]:
    """Embeddings de todos los textos únicos.

    Con `vectores` (M70), usa los que ya trae y calcula solo los que faltan, que
    agrega al mismo dict para que quien llama los guarde. Con `estrictos`, un
    faltante es VectoresFaltantesError, sin llamar a la API. Sin vectores, una
    sola llamada con todos los textos, como siempre.

    Returns:
        Tupla de (cache texto→vector, usage de la llamada de embeddings, o None
        si no hubo llamada).
    """
    textos_unicos = textos_a_embeber(hallazgos_pdf, hallazgos_excel)
    guardados: Vectores = {} if vectores is None else vectores
    faltantes = [t for t in textos_unicos if t not in guardados]
    if faltantes and estrictos:
        raise VectoresFaltantesError(
            f"Faltan los vectores de {len(faltantes)} de los {len(textos_unicos)} textos de E4 "
            f"(modo estricto: no se llama a la API de embeddings). Primero: "
            f"{faltantes[0][:80]!r}."
        )
    usage = None
    if faltantes:
        embeddings, usage = calcular_embeddings(faltantes)
        guardados.update({texto: embeddings[i] for i, texto in enumerate(faltantes)})
    return {texto: guardados[texto] for texto in textos_unicos}, usage


def _modelo_juez() -> str:
    """Modelo de los dos jueces de la etapa (matching y redacción)."""
    return settings.modelo_juez_matching or settings.modelo_extraccion


# --- 4e: pasada final — polaridad + juez de redacción (decisión 2026-10-17) ---
#
# Descripción y acción se comparan por similitud coseno con umbral
# (invariante 19). En los informes de Reliable el Excel PARAFRASEA el PDF con
# el mismo contenido (Zeta C1: "Sincronización horaria externa. No
# cumple…" vs "Equipo no posee sincronización horaria vía GPS…" → 0.80) y
# ningún umbral separa paráfrasis (0.36-0.82) de diferencias reales
# (0.44-0.76). Sobre el umbral, además, los embeddings no distinguen la
# negación (Alfa E7: "…INFOTÉCNICA: Cumple" vs "…INFOTÉCNICA: No cumple"
# quedó como coincide). La pasada no toca el emparejamiento (tipo_match,
# confianza ni justificación): solo revisa los campos de texto de cada par.

_CAMPOS_TEXTO = (CampoDiferente.DESCRIPCION, CampoDiferente.ACCION_CORRECTIVA)
_MAX_ITEMS_POR_LOTE_REDACCION = 15

Polaridad = Literal["+", "-"]
_VEREDICTO: dict[Polaridad, str] = {"+": "cumple", "-": "no cumple"}

_RE_INCUMPLE = re.compile(r"\bincumpl\w*")
_RE_CUMPLE = re.compile(r"\bcumplen?\b")
_RE_POSITIVO = re.compile(r"\bsin\s+hallazgos?\b|\bsin\s+anormalidad(?:es)?\b")
_RE_LIMITE_FRASE = re.compile(r"[.;:,]")
# Cada "cumple" se lee en su frase. Negado justo antes ("no cumple", "no se
# cumple", "no lo cumple", "tampoco cumple") o como respuesta de formulario
# ("Cumple: No") → negativo.
_RE_NEGACION_PREVIA = re.compile(r"\b(?:no|tampoco|nunca)\s+(?:(?:se|lo|la|los|las)\s+)?$")
_RE_NEGACION_POSTERIOR = re.compile(r"\s*:\s*no\s*(?:[.;,]|$)")
# Con cuantificador o matiz ("ningún relé cumple", "no todos los relés
# cumplen", "cumple parcialmente") no es un veredicto único: no cuenta para
# ningún signo. Contarlo como "cumple" forzaría una "polaridad opuesta"
# falsa contra un "No cumple" del otro lado, sin pasar por el juez.
_RE_CUANTIFICADOR_PREVIO = re.compile(r"\bningun[oa]?\b|\bno\s+tod[oa]s?\b")
_RE_MATIZ_POSTERIOR = re.compile(r"\s+parcialmente\b")


def _polaridad(texto: str) -> Polaridad | None:
    """Veredicto explícito del texto: "-" si dice que no cumple, "+" si dice
    que cumple, None si no dice ninguna de las dos cosas o dice ambas.

    Es una red de seguridad al COMPARAR dos textos ya extraídos, no un
    filtro: qué ítems del PDF son hallazgos lo sigue decidiendo la Etapa 3
    con criterio semántico (invariante 6). Acá solo se detecta que un lado
    diga "Cumple" y el otro "No cumple", la negación que los embeddings no
    distinguen. Un texto mixto ("cumple X, pero no cumple Y") no tiene
    veredicto único → None.
    """
    descompuesto = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in descompuesto if not unicodedata.combining(c))
    normalizado = " ".join(sin_tildes.casefold().split())

    negativo = _RE_INCUMPLE.search(normalizado) is not None
    positivo = _RE_POSITIVO.search(normalizado) is not None
    for m in _RE_CUMPLE.finditer(normalizado):
        frase_previa = _RE_LIMITE_FRASE.split(normalizado[: m.start()])[-1]
        resto = normalizado[m.end():]
        if _RE_NEGACION_PREVIA.search(frase_previa) or _RE_NEGACION_POSTERIOR.match(resto):
            negativo = True
        elif not (
            _RE_CUANTIFICADOR_PREVIO.search(frase_previa) or _RE_MATIZ_POSTERIOR.match(resto)
        ):
            positivo = True
    if negativo == positivo:
        return None
    return "-" if negativo else "+"


# Control de códigos (M28 V2, decisión del usuario 2026-10-27). Sobre el umbral,
# la similitud tampoco ve un código o un número cambiado en una oración que, por
# lo demás, copia el PDF: M43 plantó «50N»→«67N» (Epsilon), «50G»→«51G» y
# «2,50»→«0,50» (Beta) y salieron «coincide» sin que ningún juez los viera; en
# Alfa C3 y C4 la acción del PDF dice «paño E5» y el Excel, C3 y C4 (CB69).
# Término: un número con hasta 3 letras pegadas (50N, 87T, E5, BT1, 2,50); una
# palabra larga pegada a un dígito no cuenta («Manual2»). Solo alerta una
# SUSTITUCIÓN, un término en cada lado que el otro no tiene: un término de un
# solo lado (el artículo o la tensión que agrega el Excel) no contradice al otro,
# y fue lo que dejó a M28 V1 en falsas alarmas (20 «coincide» de B2).
_RE_TERMINO = re.compile(r"\b[^\W\d_]{0,3}\d+(?:[.,]\d+)?[^\W\d_]{0,3}\b")
_RE_NUMERO = re.compile(r"\d+(?:[.,]\d+)?")


def _clave_termino(termino: str) -> str:
    """Un número puro vale por su valor (2,50 = 2.5); el resto, sin mayúsculas."""
    termino = unicodedata.normalize("NFKC", termino).casefold()
    if _RE_NUMERO.fullmatch(termino):
        return str(Decimal(termino.replace(",", ".")).normalize())
    return termino


def _sobrantes(terminos: list[str], otros: list[str]) -> list[str]:
    """Los términos (con su grafía) que no están en `otros`, como multiconjunto."""
    restantes = Counter(_clave_termino(t) for t in otros)
    sobrantes: list[str] = []
    for termino in terminos:
        clave = _clave_termino(termino)
        if restantes[clave] > 0:
            restantes[clave] -= 1
        else:
            sobrantes.append(termino)
    return sobrantes


def _terminos_sustituidos(texto_pdf: str, texto_excel: str
                          ) -> tuple[list[str], list[str]] | None:
    """Los términos con dígito que cada lado tiene y el otro no, en el orden del
    texto, si los dos lados tienen alguno; None si no hay sustitución."""
    del_pdf = _RE_TERMINO.findall(texto_pdf)
    del_excel = _RE_TERMINO.findall(texto_excel)
    solo_pdf, solo_excel = _sobrantes(del_pdf, del_excel), _sobrantes(del_excel, del_pdf)
    return (solo_pdf, solo_excel) if solo_pdf and solo_excel else None


def _diferencia_codigo(campo: CampoDiferente, valor_pdf: str, valor_excel: str,
                       sustituidos: tuple[list[str], list[str]], similitud: float
                       ) -> Diferencia:
    del_pdf, del_excel = (", ".join(f"«{t}»" for t in lado) for lado in sustituidos)
    return Diferencia(
        campo=campo,
        valor_pdf=valor_pdf,
        valor_excel=valor_excel,
        detalle=(
            f"Código o número distinto: el PDF dice {del_pdf} y el Excel {del_excel} "
            f"(similitud semántica {similitud:.2f}; la similitud no distingue un código "
            "cambiado)"
        ),
    )


def _polaridades_opuestas(texto_a: str, texto_b: str) -> bool:
    """Los dos textos tienen veredicto explícito y es el contrario."""
    pol_a, pol_b = _polaridad(texto_a), _polaridad(texto_b)
    return pol_a is not None and pol_b is not None and pol_a != pol_b


_LARGO_DESCRIPCION_MOTIVO = 80


def _comienzo(texto: str) -> str:
    """Comienzo de una descripción para nombrar el hallazgo en el motivo: hasta
    _LARGO_DESCRIPCION_MOTIVO caracteres, cortado en un espacio y con «…» si sigue."""
    texto = " ".join(texto.split())
    if len(texto) <= _LARGO_DESCRIPCION_MOTIVO:
        return texto
    return texto[:_LARGO_DESCRIPCION_MOTIVO + 1].rsplit(" ", 1)[0].rstrip(" ,;:.") + "…"


def _en_pagina(perdedor: Hallazgo, pagina_par: int | None) -> str:
    """«en la pág. N» de un hallazgo que perdió la fila, «en la misma pág. N» si es
    la del hallazgo del par; vacío si no tiene página."""
    pagina = perdedor.evidencia.pagina_pdf
    if pagina is None:
        return ""
    return f"en la {'misma ' if pagina == pagina_par else ''}pág. {pagina}"


def _descripcion_perdedor(perdedor: Hallazgo) -> str:
    """El comienzo de la descripción de un hallazgo que perdió la fila, rotulado
    «descripción»: es lo que extrajo E3, no una cita verificada (21b). La página sola
    no alcanza: en la de la tabla del paño suele haber otros hallazgos de la tupla, a
    veces el del mismo par (Alfa Opus, E7, pág. 26)."""
    return f"descripción «{_comienzo(perdedor.descripcion)}»"


def _motivo_fila_disputada(h_pdf: Hallazgo, h_excel: Hallazgo,
                           perdedores: list[Hallazgo]) -> str:
    """`MatchResult.emparejamiento_dudoso` del par cuya fila la perdió, en la
    asignación global, uno o más hallazgos del PDF de polaridad opuesta a ella
    (PD71). Empieza por lo que hay que hacer, sigue con qué dice cada lado, dónde
    están y cuáles son los otros hallazgos, y termina con la consecuencia (PD72,
    redacción provisoria hasta que opine el equipo revisor). Sin jerga del algoritmo
    (el equipo revisor no ve la asignación global) y legible solo: la interfaz lo
    muestra como aviso del emparejamiento, sin agregarle frases (invariante 24)."""
    polaridad = _polaridad(h_excel.descripcion)
    assert polaridad is not None and perdedores, "fila disputada sin polaridad o sin perdedores"
    fila = _VEREDICTO[polaridad]
    otro = _VEREDICTO["+" if polaridad == "-" else "-"]
    pagina_par = h_pdf.evidencia.pagina_pdf
    if len(perdedores) == 1:
        (perdedor,) = perdedores
        hay = (f"hay otro hallazgo del PDF que dice que {otro} "
               f"({_descripcion_perdedor(perdedor)}) y que también podría ser el de esta "
               "fila. Si es ese, el Excel invirtió el veredicto.")
        donde = _en_pagina(perdedor, pagina_par)
        if donde:
            hay = f"{donde} {hay}"
    else:
        ordenados = sorted(perdedores, key=lambda h: (h.evidencia.pagina_pdf is None,
                                                      h.evidencia.pagina_pdf or 0))
        cuales = "; ".join(
            ", ".join(filter(None, (_en_pagina(h, pagina_par), _descripcion_perdedor(h))))
            for h in ordenados)
        hay = (f"hay otros {len(perdedores)} hallazgos del PDF que dicen que {otro} "
               f"({cuales}) y que también podrían ser el de esta fila. Si es uno de ellos, "
               "el Excel invirtió su veredicto.")
    return (f"Revisar a qué hallazgo corresponde esta fila. El Excel dice que {fila}, "
            f"pero {hay}")


def _texto_campo(h: Hallazgo, campo: CampoDiferente) -> str | None:
    return h.descripcion if campo == CampoDiferente.DESCRIPCION else h.accion_correctiva


def _threshold_campo(campo: CampoDiferente) -> float:
    if campo == CampoDiferente.DESCRIPCION:
        return settings.threshold_descripcion
    return settings.threshold_accion


def _similitud_textos(
    valor_pdf: str,
    valor_excel: str,
    emb_cache: dict[str, np.ndarray[Any, np.dtype[np.float64]]],
) -> float | None:
    """Similitud coseno de un campo de texto de un par, o None cuando ese
    campo no se compara por embeddings (idéntico, vacío en un lado o sin
    embeddings): esos casos los resuelve _comparar_campo_semantico sin
    similitud y la pasada final no los toca."""
    if valor_pdf == valor_excel or not valor_pdf.strip() or not valor_excel.strip():
        return None
    emb_pdf = emb_cache.get(valor_pdf)
    emb_excel = emb_cache.get(valor_excel)
    if emb_pdf is None or emb_excel is None:
        return None
    return similitud_coseno(emb_pdf, emb_excel)


@dataclass(frozen=True)
class _PendienteRedaccion:
    """Campo de un par, bajo el umbral, que adjudica el juez de redacción."""

    indice: int  # posición del par en la lista de resultados
    campo: CampoDiferente
    similitud: float


class _VeredictoRedaccion(BaseModel):
    id: int
    # La justificación va antes del veredicto: structured outputs genera los
    # campos en el orden del schema, así el modelo razona antes de decidir.
    justificacion: str
    mismo_contenido: bool


class _JuezRedaccionResponse(BaseModel):
    veredictos: list[_VeredictoRedaccion]


def _llamar_juez(
    llm_metadata: list[dict[str, Any]], contexto: dict[str, Any], **kwargs: Any
) -> tuple[Any, dict[str, Any]]:
    """Llama a un juez de E4. Si la llamada falla, agrega su entrada (formato
    común de llamada fallida, ver llm.client) y deja en la excepción original
    la metadata de E4 acumulada, sin cambiar su tipo ni su mensaje: el pipeline
    persiste los raw ya pagados y el run falla igual (invariante 20). Nunca
    hay un veredicto por defecto. Una llamada que no se hizo (JuezNoLlamadoError)
    no agrega entrada: no hay raw de algo que no ocurrió."""
    llamar = _LLAMADOR.get() or llamar_llm_estructurado
    try:
        return llamar(**kwargs)
    except JuezNoLlamadoError:
        raise   # ejecutar_matching le deja la metadata acumulada
    except Exception as exc:
        fallida = getattr(exc, "llm_metadata", None)
        entrada = dict(fallida) if isinstance(fallida, dict) else {"modelo": kwargs["modelo"]}
        entrada.update({"llamada_fallida": True, "error": f"{type(exc).__name__}: {exc}",
                        **contexto})
        llm_metadata.append(entrada)
        exc.llm_metadata = llm_metadata  # type: ignore[attr-defined]
        raise


def _consultar_juez_redaccion(
    resultados: list[MatchResult],
    pendientes: list[_PendienteRedaccion],
    llm_metadata: list[dict[str, Any]],
) -> dict[tuple[int, CampoDiferente], _VeredictoRedaccion]:
    """Envía los pendientes al juez en lotes y valida cada respuesta.

    Las metas se agregan a `llm_metadata` con meta["tipo"] = "juez_redaccion"
    y el detalle del lote (qué par y campo es cada id).

    Raises:
        JuezInvalidoError: ids faltantes, sobrantes o duplicados. Un ítem sin
            veredicto válido nunca se da por "mismo contenido".
    """
    veredictos: dict[tuple[int, CampoDiferente], _VeredictoRedaccion] = {}
    for n_lote, inicio in enumerate(range(0, len(pendientes), _MAX_ITEMS_POR_LOTE_REDACCION)):
        lote = pendientes[inicio : inicio + _MAX_ITEMS_POR_LOTE_REDACCION]

        # ids 1..n por lote: cortos y sin relación con índices internos.
        items: list[dict[str, str | int]] = []
        trazas: list[dict[str, Any]] = []
        for id_item, p in enumerate(lote, 1):
            r = resultados[p.indice]
            assert r.hallazgo_pdf is not None and r.hallazgo_excel is not None
            items.append({
                "id": id_item,
                "campo": p.campo.value,
                "pano": r.pano,
                "rele": r.rele,
                "clasificacion": r.hallazgo_excel.clasificacion,
                "texto_pdf": _texto_campo(r.hallazgo_pdf, p.campo) or "",
                "texto_excel": _texto_campo(r.hallazgo_excel, p.campo) or "",
            })
            # La similitud queda en la traza para auditoría, pero no va al
            # prompt: anclaría al juez al mismo criterio que se le pide revisar.
            trazas.append({
                "id": id_item,
                "campo": p.campo.value,
                "pano": r.pano,
                "rele": r.rele,
                "pagina_pdf": r.hallazgo_pdf.evidencia.pagina_pdf,
                "fila_excel": r.hallazgo_excel.evidencia.fila_excel,
                "similitud": round(p.similitud, 4),
            })

        respuesta, meta = _llamar_juez(
            llm_metadata, {"tipo": "juez_redaccion", "lote": trazas},
            modelo=_modelo_juez(),
            system_prompt=SYSTEM_JUEZ_REDACCION,
            user_prompt=user_juez_redaccion(items),
            response_model=_JuezRedaccionResponse,
        )
        meta["tipo"] = "juez_redaccion"
        meta["lote"] = trazas
        llm_metadata.append(meta)

        recibidos = [v.id for v in respuesta.veredictos]
        esperados = set(range(1, len(lote) + 1))
        faltantes = sorted(esperados - set(recibidos))
        sobrantes = sorted(set(recibidos) - esperados)
        duplicados = sorted(i for i, n in Counter(recibidos).items() if n > 1)
        if faltantes or sobrantes or duplicados:
            raise JuezInvalidoError(
                f"El juez de redacción devolvió una respuesta inválida en el lote "
                f"{n_lote + 1} ({len(lote)} ítems): ids faltantes {faltantes}, "
                f"sobrantes {sobrantes}, duplicados {duplicados}.",
                llm_metadata,
            )

        por_id = {v.id: v for v in respuesta.veredictos}
        for id_item, p in enumerate(lote, 1):
            veredictos[(p.indice, p.campo)] = por_id[id_item]
    return veredictos


def _revisar_redaccion(
    resultados: list[MatchResult],
    emb_cache: dict[str, np.ndarray[Any, np.dtype[np.float64]]],
    llm_metadata: list[dict[str, Any]],
) -> list[MatchResult]:
    """4e: revisa descripción y acción de cada par (PDF y Excel presentes).

    1. Polaridad opuesta (un lado dice que cumple y el otro que no) → el
       campo es Diferencia SIEMPRE, con la similitud sobre o bajo el umbral,
       sin consultar al juez.
    2. Sobre el umbral, con `CONTROL_CODIGOS`: un código o número sustituido
       (un término con dígito en cada lado que el otro no tiene) → Diferencia,
       sin consultar al juez. Bajo el umbral no aplica: el juez ve el texto.
    3. Bajo el umbral, sin polaridad opuesta → juez de redacción. Mismo
       contenido: la Diferencia sale y el campo queda como
       EquivalenciaRedaccion visible para la revisora. Distinto: la
       Diferencia queda, con la conclusión del juez en el detalle. Salvo en
       un par de emparejamiento dudoso (19e(c), `emparejamiento_es_dudoso`:
       `semantico_bajo` o, con la asignación global, `emparejamiento_dudoso`,
       PD71), que queda con la Diferencia de 4c sin consultar al juez.

    Las diferencias "contenido solo en un lado" y "sin embeddings" no se
    tocan (no hay similitud que adjudicar), ni la calificación. El estado se
    recalcula y el orden descripción → acción → calificación se mantiene
    (invariante 16).
    """
    sin_juez: dict[tuple[int, CampoDiferente], Diferencia] = {}
    pendientes: dict[tuple[int, CampoDiferente], _PendienteRedaccion] = {}

    for k, r in enumerate(resultados):
        if r.hallazgo_pdf is None or r.hallazgo_excel is None:
            continue
        for campo in _CAMPOS_TEXTO:
            valor_pdf = _texto_campo(r.hallazgo_pdf, campo)
            valor_excel = _texto_campo(r.hallazgo_excel, campo)
            if valor_pdf is None or valor_excel is None:
                continue
            similitud = _similitud_textos(valor_pdf, valor_excel, emb_cache)
            if similitud is None:
                continue

            pol_pdf, pol_excel = _polaridad(valor_pdf), _polaridad(valor_excel)
            if pol_pdf is not None and pol_excel is not None and pol_pdf != pol_excel:
                lado_cumple, lado_no = ("PDF", "Excel") if pol_pdf == "+" else ("Excel", "PDF")
                sin_juez[(k, campo)] = Diferencia(
                    campo=campo,
                    valor_pdf=valor_pdf,
                    valor_excel=valor_excel,
                    detalle=(
                        f"Polaridad opuesta: el {lado_cumple} indica que cumple y el "
                        f"{lado_no} que no cumple (similitud semántica {similitud:.2f}; "
                        "la similitud no distingue la negación)"
                    ),
                )
            elif similitud >= _threshold_campo(campo):
                sustituidos = (_terminos_sustituidos(valor_pdf, valor_excel)
                               if settings.control_codigos else None)
                if sustituidos:
                    sin_juez[(k, campo)] = _diferencia_codigo(
                        campo, valor_pdf, valor_excel, sustituidos, similitud)
            elif not r.emparejamiento_es_dudoso:
                # Un par de emparejamiento dudoso no se adjudica como paráfrasis: si
                # el emparejamiento mismo es dudoso, "mismo contenido" apilaría dos
                # incertidumbres y podría esconder una diferencia real (calibración
                # B1, Alfa E7: el juez de matching unió "equipo no ajustado según
                # ECAP" con la fila "INFOTÉCNICA: No cumple", cuyo par real en el PDF
                # dice "Cumple"; con la asignación global, AG1 llegó al mismo par
                # como semantico_alto, 0,80, y por eso lleva emparejamiento_dudoso,
                # PD71). Queda como Diferencia, el lado seguro.
                pendientes[(k, campo)] = _PendienteRedaccion(k, campo, similitud)

    veredictos = _consultar_juez_redaccion(resultados, list(pendientes.values()), llm_metadata)

    salida = list(resultados)
    for k in sorted({k for k, _ in sin_juez} | {k for k, _ in pendientes}):
        r = resultados[k]
        assert r.hallazgo_pdf is not None and r.hallazgo_excel is not None
        # Un par tiene a lo sumo una Diferencia por campo.
        por_campo = {d.campo: d for d in r.diferencias}
        equivalencias: list[EquivalenciaRedaccion] = []
        for campo in _CAMPOS_TEXTO:
            if (k, campo) in sin_juez:
                por_campo[campo] = sin_juez[(k, campo)]
                continue
            pendiente = pendientes.get((k, campo))
            if pendiente is None:
                continue
            valor_pdf = _texto_campo(r.hallazgo_pdf, campo) or ""
            valor_excel = _texto_campo(r.hallazgo_excel, campo) or ""
            veredicto = veredictos[(k, campo)]
            if veredicto.mismo_contenido:
                por_campo.pop(campo, None)
                equivalencias.append(EquivalenciaRedaccion(
                    campo=campo,
                    valor_pdf=valor_pdf,
                    valor_excel=valor_excel,
                    similitud=round(pendiente.similitud, 4),
                    justificacion=veredicto.justificacion,
                ))
            else:
                detalle = _detalle_bajo_umbral(pendiente.similitud, _threshold_campo(campo))
                por_campo[campo] = Diferencia(
                    campo=campo,
                    valor_pdf=valor_pdf,
                    valor_excel=valor_excel,
                    detalle=f"{detalle}; {CONCLUYO_DIFIERE}{veredicto.justificacion}",
                )

        # El orden de declaración de CampoDiferente ES el orden obligatorio
        # descripción → acción → calificación.
        diferencias = [por_campo[c] for c in CampoDiferente if c in por_campo]
        salida[k] = r.model_copy(update={
            "diferencias": diferencias,
            "equivalencias_redaccion": equivalencias,
            "estado": EstadoHallazgo.COINCIDE if not diferencias else EstadoHallazgo.DIFIERE,
        })
    return salida


# --- 4f: copias del mismo origen (M34, decisión del usuario 2026-10-27) ---
#
# Una fila del Excel y un hallazgo del PDF que aplican a varios paños se
# desdoblan en una copia por tupla (invariante 8): es el mismo par, y cada copia
# se juzga por separado. Los jueces no siempre dan lo mismo a la misma entrada
# (Sonnet, Gamma B2: 84 y 78 para el mismo prompt; «mismo contenido» en una
# copia y «difiere» en otra). Con UNIFICAR_COPIAS, después de 4e (no cambia
# ninguna llamada a los jueces), las copias se igualan del lado seguro: la
# confianza del emparejamiento a la más baja (con el corte 0,8 recalculado, y
# 19e(c) para la copia que queda dudosa) y el «difiere» del juez de redacción a
# las copias que había dado por «mismo contenido». Solo iguala veredictos de
# copias del mismo origen: nunca empareja entre tuplas (invariante 14) ni rehace
# el emparejamiento ni la asignación global. Una exclusión por 19e(c) no se
# propaga (es una duda del emparejamiento de otra tupla, no un veredicto sobre el
# texto), ni el motivo de PD71 (nombra un hallazgo de otra tupla).

CONCLUYO_DIFIERE = "el juez de redacción concluyó que el contenido difiere: "
MARCA_COPIA = "copia del mismo origen"


def _clave_copia(r: MatchResult) -> tuple[Any, ...] | None:
    """Origen de un par: los dos lados desdoblados (`es_multi_pano_origen`) con los
    mismos textos, página, fila y relé. None si no puede tener copias."""
    h_pdf, h_excel = r.hallazgo_pdf, r.hallazgo_excel
    if (h_pdf is None or h_excel is None or not h_pdf.evidencia.es_multi_pano_origen
            or not h_excel.evidencia.es_multi_pano_origen):
        return None

    def lado(h: Hallazgo, posicion: tuple[Any, ...]) -> tuple[Any, ...]:
        return (*posicion, h.evidencia.texto_crudo, h.descripcion, h.accion_correctiva,
                h.calificacion, h.clasificacion)

    return (clave_tupla(r.pano, r.rele)[1],
            lado(h_pdf, (h_pdf.evidencia.pagina_pdf,)),
            lado(h_excel, (h_excel.evidencia.hoja_excel, h_excel.evidencia.fila_excel)))


def _grupos_de_copias(resultados: list[MatchResult]) -> list[list[int]]:
    """Índices de los pares de cada origen con dos o más copias, a lo sumo una por
    tupla (si dos caen en la misma tupla no son copias del desdoblamiento)."""
    grupos: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    for k, r in enumerate(resultados):
        if (clave := _clave_copia(r)) is not None:
            grupos[clave].append(k)
    return [g for g in grupos.values() if len(g) > 1 and len(
        {clave_tupla(resultados[k].pano, resultados[k].rele) for k in g}) == len(g)]


def _difiere_del_juez(r: MatchResult, campo: CampoDiferente) -> str | None:
    """La justificación con que el juez de redacción dio «difiere» a ese campo."""
    for d in r.diferencias:
        if d.campo == campo and CONCLUYO_DIFIERE in (d.detalle or ""):
            return (d.detalle or "").split(CONCLUYO_DIFIERE, 1)[1]
    return None


def _a_diferencia(r: MatchResult, cambios: dict[CampoDiferente, str]) -> MatchResult:
    """Pasa a Diferencia las equivalencias de redacción de `cambios` (campo →
    detalle), con el estado recalculado y el orden de la invariante 16."""
    por_campo = {d.campo: d for d in r.diferencias}
    for e in r.equivalencias_redaccion:
        if e.campo in cambios:
            por_campo[e.campo] = Diferencia(campo=e.campo, valor_pdf=e.valor_pdf,
                                            valor_excel=e.valor_excel, detalle=cambios[e.campo])
    diferencias = [por_campo[c] for c in CampoDiferente if c in por_campo]
    return r.model_copy(update={
        "diferencias": diferencias,
        "equivalencias_redaccion": [e for e in r.equivalencias_redaccion
                                    if e.campo not in cambios],
        "estado": EstadoHallazgo.COINCIDE if not diferencias else EstadoHallazgo.DIFIERE,
    })


def _unificar_copias(
    resultados: list[MatchResult],
    emb_cache: dict[str, np.ndarray[Any, np.dtype[np.float64]]] | None = None,
) -> list[MatchResult]:
    """`emb_cache` (en E4) da la similitud exacta del detalle; sin él (lo guardado),
    la de la equivalencia, redondeada a 4 decimales."""

    def similitud(e: EquivalenciaRedaccion) -> float:
        exacta = (_similitud_textos(e.valor_pdf, e.valor_excel, emb_cache)
                  if emb_cache is not None else None)
        return e.similitud if exacta is None else exacta

    salida = list(resultados)
    for grupo in _grupos_de_copias(salida):
        # 1. Confianza: la más baja entre las copias semánticas (unicidad y
        # descripción idéntica no consultan al juez y quedan en 1,0).
        semanticas = [k for k in grupo if salida[k].tipo_match in (
            TipoMatch.SEMANTICO_ALTO, TipoMatch.SEMANTICO_BAJO)]
        if len(semanticas) > 1:
            k_min = min(semanticas, key=lambda k: salida[k].confianza)
            minima, pano_min = salida[k_min].confianza, salida[k_min].pano
            for k in semanticas:
                r = salida[k]
                if r.confianza <= minima:
                    continue
                texto_min, texto_propia = _dos_confianzas(minima, r.confianza)
                tipo = TipoMatch.SEMANTICO_ALTO if minima >= 0.8 else TipoMatch.SEMANTICO_BAJO
                r = r.model_copy(update={
                    "confianza": minima, "tipo_match": tipo,
                    "justificacion": (
                        f"{r.justificacion} Confianza igualada a la de su {MARCA_COPIA} en el "
                        f"paño {pano_min} ({texto_min} en vez de {texto_propia}): la misma fila "
                        "del Excel y el mismo hallazgo del PDF, desdoblados por paño, cuentan "
                        "con la menor."),
                })
                # 19e(c) otra vez: la copia que quedó dudosa no se adjudica como paráfrasis.
                if r.emparejamiento_es_dudoso and r.equivalencias_redaccion:
                    r = _a_diferencia(r, {e.campo: (
                        f"{_detalle_bajo_umbral(similitud(e), _threshold_campo(e.campo))}; "
                        f"con la confianza igualada a la de su {MARCA_COPIA} el par queda dudoso, "
                        "y un par dudoso no se adjudica como paráfrasis (19e(c)). El juez de "
                        f"redacción había dado mismo contenido: {e.justificacion}")
                        for e in r.equivalencias_redaccion})
                salida[k] = r
        # 2. Redacción: el «difiere» del juez pasa a las copias con «mismo contenido».
        for campo in _CAMPOS_TEXTO:
            difiere = [(salida[k].pano, j) for k in grupo
                       if (j := _difiere_del_juez(salida[k], campo)) is not None]
            if not difiere:
                continue
            pano_otro, justificacion_otro = difiere[0]
            for k in grupo:
                e = next((e for e in salida[k].equivalencias_redaccion if e.campo == campo), None)
                if e is None:
                    continue
                salida[k] = _a_diferencia(salida[k], {campo: (
                    f"{_detalle_bajo_umbral(similitud(e), _threshold_campo(campo))}; su "
                    f"{MARCA_COPIA} en el paño {pano_otro} la adjudicó como contenido distinto "
                    f"({justificacion_otro}) y este par como misma redacción "
                    f"({e.justificacion}): del lado seguro, cuenta como diferencia.")})
    return salida


def _paso_4f(
    resultados: list[MatchResult],
    emb_cache: dict[str, np.ndarray[Any, np.dtype[np.float64]]] | None = None,
) -> list[MatchResult]:
    """4f. Apagado (UNIFICAR_COPIAS=false) = comportamiento previo exacto."""
    return _unificar_copias(resultados, emb_cache) if settings.unificar_copias else resultados


def contar_copias_unificadas(resultados: list[MatchResult]) -> dict[str, int]:
    """Lo que cambió 4f (para la metadata del run): confianzas igualadas y campos
    que pasaron de «mismo contenido» a Diferencia."""
    return {
        "confianzas_igualadas": sum(MARCA_COPIA in r.justificacion for r in resultados),
        "campos_a_diferencia": sum(MARCA_COPIA in (d.detalle or "")
                                   for r in resultados for d in r.diferencias),
    }


def _falta(pano: str, rele: str, h_pdf: Hallazgo, justificacion: str) -> MatchResult:
    return MatchResult(
        pano=pano, rele=rele,
        estado=EstadoHallazgo.FALTA_EN_EXCEL,
        tipo_match=TipoMatch.SIN_MATCH,
        confianza=0.0,
        justificacion=justificacion,
        hallazgo_pdf=h_pdf, hallazgo_excel=None,
    )


def _par(
    pano: str, rele: str, h_pdf: Hallazgo, h_excel: Hallazgo, confianza: float,
    justificacion: str, emb_cache: dict[str, np.ndarray],
) -> MatchResult:
    tipo = TipoMatch.SEMANTICO_ALTO if confianza >= 0.8 else TipoMatch.SEMANTICO_BAJO
    diffs = _detectar_diferencias(h_pdf, h_excel, emb_cache)
    return MatchResult(
        pano=pano, rele=rele,
        estado=EstadoHallazgo.COINCIDE if not diffs else EstadoHallazgo.DIFIERE,
        tipo_match=tipo,
        confianza=confianza,
        justificacion=justificacion,
        hallazgo_pdf=h_pdf, hallazgo_excel=h_excel,
        diferencias=diffs,
    )


def _preguntar_juez(
    h_pdf: Hallazgo,
    emb_pdf: np.ndarray,
    disponibles: list[int],
    restantes_excel: list[Hallazgo],
    emb_cache: dict[str, np.ndarray],
    llm_metadata: list[dict[str, Any]],
    pano: str,
    rele: str,
    traza: dict[str, Any] | None = None,
) -> tuple[_JuezResponse, list[tuple[int, float]], float]:
    """Una consulta al juez de matching con el top-k de `disponibles`.

    Devuelve la respuesta, los candidatos ofrecidos (índice en
    `restantes_excel`, similitud) y la confianza como fracción. Un índice fuera
    de rango es un error del LLM, no un rechazo: JuezInvalidoError. `traza`
    (asignación global) queda en la metadata de la llamada.
    """
    embs_disponibles = np.array([
        emb_cache[restantes_excel[j].descripcion] for j in disponibles
    ])
    top_k = top_k_similares(emb_pdf, embs_disponibles, k=settings.top_k_candidatos)
    candidatos_validos = [(disponibles[idx], sim) for idx, sim in top_k]
    candidatos_desc = [restantes_excel[idx].descripcion for idx, _ in candidatos_validos]

    contexto: dict[str, Any] = {"pano": pano, "rele": rele}
    if traza is not None:
        contexto["asignacion_global"] = traza
    juez_resp, juez_meta = _llamar_juez(
        llm_metadata, contexto,
        modelo=_modelo_juez(),
        system_prompt=system_juez_matching(settings.juez_justifica_primero),
        user_prompt=user_juez_matching(h_pdf.descripcion, candidatos_desc),
        response_model=_respuesta_juez(),
    )
    if traza is not None:
        juez_meta["asignacion_global"] = traza
    llm_metadata.append(juez_meta)

    if juez_resp.indice_candidato is not None and not (
        0 <= juez_resp.indice_candidato < len(candidatos_validos)
    ):
        # Error del LLM, no un rechazo: degradarlo a "falta en
        # Excel" dejaría una justificación que afirma lo contrario.
        raise JuezInvalidoError(
            f"El juez devolvió el índice {juez_resp.indice_candidato} "
            f"con solo {len(candidatos_validos)} candidatos "
            f"(paño {pano} / relé {rele}).",
            llm_metadata,
        )
    # El juez responde porcentaje 0-99; el schema usa fracción 0.0-1.0
    # (1.0 queda reservado para matches por unicidad).
    return juez_resp, candidatos_validos, juez_resp.confianza / 100.0


def contar_reintentos(metas: list[dict[str, Any]]) -> int:
    """Consultas extra de la asignación global (las que repiten un hallazgo)."""
    return sum(1 for m in metas if (m.get("asignacion_global") or {}).get("reintento"))


# Filas que perdió cada hallazgo del PDF en la asignación global, por id() del
# hallazgo: (fila del Excel, confianza propia, confianza del que la tomó).
Perdidas = dict[int, list[tuple[Hallazgo, float, float]]]
# Filas que, en la asignación global, perdió un hallazgo del PDF de polaridad
# opuesta a la fila (desplazado o rechazado; PD71): id() de la fila del Excel →
# esos hallazgos, en el orden en que la perdieron.
FilasDisputadas = dict[int, list[Hallazgo]]


def _emparejar_en_orden(
    pano: str,
    rele: str,
    restantes_pdf: list[Hallazgo],
    restantes_excel: list[Hallazgo],
    emb_cache: dict[str, np.ndarray],
    llm_metadata: list[dict[str, Any]],
) -> tuple[list[MatchResult], set[int], Perdidas, FilasDisputadas]:
    """4b clásico: cada hallazgo del PDF, en el orden de E3, consulta al juez
    con las filas que todavía nadie tomó y se queda con la que elige.

    Devuelve los resultados (en el orden del PDF), los índices de
    `restantes_excel` emparejados, las filas perdidas y las disputadas
    (ninguna de las dos: sin la asignación global nadie pierde una fila).
    """
    nuevos_matcheados_excel: set[int] = set()
    resultados_tupla: list[MatchResult] = []
    for h_pdf in restantes_pdf:
        emb_pdf = emb_cache.get(h_pdf.descripcion)
        if emb_pdf is None:
            resultados_tupla.append(
                _falta(pano, rele, h_pdf, "Sin embeddings disponibles para comparar."))
            continue

        # El pool de candidatos se recalcula por hallazgo, excluyendo
        # los ya matcheados ANTES del top-k. Filtrar después de fijar
        # el top-k dejaba sin candidatos a los hallazgos tardíos en
        # tuplas con más de k hallazgos (falsos "falta en Excel"
        # dependientes del orden de extracción).
        disponibles = [
            j for j, h in enumerate(restantes_excel)
            if j not in nuevos_matcheados_excel and h.descripcion in emb_cache
        ]
        if not disponibles:
            resultados_tupla.append(
                _falta(pano, rele, h_pdf, "Sin candidatos disponibles en Excel."))
            continue

        juez_resp, candidatos, confianza = _preguntar_juez(
            h_pdf, emb_pdf, disponibles, restantes_excel, emb_cache, llm_metadata, pano, rele
        )
        justificacion = _limpiar_justificacion_juez(juez_resp.justificacion)
        if juez_resp.indice_candidato is not None and confianza >= 0.5:
            idx_real = candidatos[juez_resp.indice_candidato][0]
            nuevos_matcheados_excel.add(idx_real)
            resultados_tupla.append(_par(
                pano, rele, h_pdf, restantes_excel[idx_real], confianza, justificacion, emb_cache
            ))
        else:
            resultados_tupla.append(_falta(pano, rele, h_pdf, justificacion))
    return resultados_tupla, nuevos_matcheados_excel, {}, {}


def _texto_fila(h_excel: Hallazgo) -> str:
    fila = h_excel.evidencia.fila_excel
    return f"la fila {fila} del Excel" if fila else "una fila del Excel"


def _frente_a(propia: float, rival: float) -> str:
    """Por qué se perdió una fila, con las confianzas reales (sin inventar)."""
    if rival > propia:
        texto_rival, texto_propia = _dos_confianzas(rival, propia)
        return f"al que el juez dio más confianza ({texto_rival} contra {texto_propia})"
    return (f"al que el juez dio la misma confianza ({propia:.2f}); en un empate se queda "
            "el que ya tenía la fila")


def _dos_confianzas(a: float, b: float) -> tuple[str, str]:
    """Dos confianzas distintas con los decimales necesarios para que se vean
    distintas (el juez puede dar fracciones: 0.804 contra 0.80)."""
    for decimales in range(2, 6):
        texto_a, texto_b = f"{a:.{decimales}f}", f"{b:.{decimales}f}"
        if texto_a != texto_b:
            return texto_a, texto_b
    return repr(a), repr(b)


def _emparejar_asignacion_global(
    pano: str,
    rele: str,
    restantes_pdf: list[Hallazgo],
    restantes_excel: list[Hallazgo],
    emb_cache: dict[str, np.ndarray],
    llm_metadata: list[dict[str, Any]],
) -> tuple[list[MatchResult], set[int], Perdidas, FilasDisputadas]:
    """4b con asignación global (ASIGNACION_GLOBAL, decisión del usuario
    2026-10-18): aceptación diferida, sin cambiar el prompt del juez.

    Cada hallazgo del PDF consulta al juez con el top-k de las filas de la
    tupla que no perdió (también las que tiene otro hallazgo). Si elige una
    fila libre, la toma; si la tiene otro con menos confianza, se la quita y
    el desplazado vuelve a consultar sin esa fila; si no, este vuelve a
    consultar sin ella. En un empate se queda el que la tenía. El orden de E3
    solo decide los empates: un hallazgo con más confianza ya no pierde su
    fila por haber sido extraído después (B2: el DUS de Gamma tomó la fila
    del DUF a 0,62 y el DUF, que la habría tomado a 0,88, quedó sin ella).

    Si el juez no elige ninguna fila, entre las que vio había filas de otro
    hallazgo y quedan filas libres que no vio, este vuelve a consultar UNA
    vez, acotado a las filas que estaban libres en ese momento y sin las que
    entretanto tomó un hallazgo anterior en el orden de E3: ve lo que le
    habría mostrado el modo en orden (sin esto, un top-k lleno de filas
    ajenas lo dejaba en falta sin ver la suya), nunca toda la tupla
    (invariante 18). Puede disputar una fila que tomó un hallazgo posterior,
    pero no una de uno anterior. Un segundo rechazo es falta.

    Termina: cada consulta repetida suma una fila perdida o es el único
    reintento acotado de ese hallazgo (cota n + m + n·m consultas por tupla;
    en la práctica, una extra por conflicto). Ningún texto del juez se
    inventa: el que queda sin fila lleva una nota determinista con las
    confianzas; la de un par que antes
    perdió una fila se agrega después del desempate por acción
    (`_notas_asignacion_global`), que puede cambiar con qué fila queda.

    Las filas que perdió un hallazgo cuya descripción tiene la polaridad
    opuesta a la de la fila (PD71, Alfa E7 en AG1: el «Cumple» perdió
    frente a otro la fila que el Excel invierte a «No cumple») salen en el
    cuarto valor, con esos hallazgos: quien tenga la fila al final es un
    emparejamiento dudoso (`_marcar_filas_disputadas`). La marca es de
    la fila, no de quien la ganó: vale igual si el opuesto la perdió por
    desplazamiento o porque le rechazaron el pedido (no depende del orden de
    E3) y pasa al dueño final aunque la fila cambie de manos después. La
    traza de cada consulta en que alguien pierde una fila lo dice
    (`perdedor_polaridad_opuesta`).
    """
    n, m = len(restantes_pdf), len(restantes_excel)
    perdidas: list[set[int]] = [set() for _ in range(n)]
    # Filas del único reintento de quien rechazó un top-k con filas ajenas: las
    # libres en ese momento (None = todavía no reintentó).
    acotadas: list[set[int] | None] = [None] * n
    perdio_frente: dict[int, list[tuple[int, float, float]]] = defaultdict(list)
    dueno: dict[int, int] = {}                          # fila → hallazgo del PDF
    vigente: dict[int, tuple[int, float, str]] = {}     # hallazgo → (fila, confianza, justif.)
    cierre: dict[int, MatchResult] = {}                 # hallazgos que quedaron en falta
    disputadas: dict[int, list[int]] = defaultdict(list)  # fila → perdedores opuestos a ella
    cola = deque(range(n))
    cota, consultas = n + m + n * m, 0

    def perder(perdedor: int, j: int, propia: float, rival: float,
               traza: dict[str, Any]) -> None:
        """`perdedor` pierde la fila j y vuelve a consultar sin ella."""
        perdidas[perdedor].add(j)
        perdio_frente[perdedor].append((j, propia, rival))
        opuesta = _polaridades_opuestas(restantes_pdf[perdedor].descripcion,
                                        restantes_excel[j].descripcion)
        traza["perdedor_polaridad_opuesta"] = opuesta
        if opuesta:
            disputadas[j].append(perdedor)
        cola.append(perdedor)

    def nota_perdidas(i: int) -> str:
        return "; ".join(
            f"Perdió {_texto_fila(restantes_excel[j])} frente a otro hallazgo del PDF "
            f"{_frente_a(propia, rival)}"
            for j, propia, rival in perdio_frente[i]
        )

    while cola:
        i = cola.popleft()
        h_pdf = restantes_pdf[i]
        emb_pdf = emb_cache.get(h_pdf.descripcion)
        if emb_pdf is None:
            cierre[i] = _falta(pano, rele, h_pdf, "Sin embeddings disponibles para comparar.")
            continue
        acotada = acotadas[i]
        disponibles = [
            j for j, h in enumerate(restantes_excel)
            if j not in perdidas[i] and h.descripcion in emb_cache
            # El reintento acotado ve lo que vería en orden: sin las filas que ya
            # tiene un hallazgo anterior (puede disputar las de uno posterior).
            and (acotada is None or (j in acotada and dueno.get(j, n) > i))
        ]
        if not disponibles:
            perdio = nota_perdidas(i)
            cierre[i] = _falta(pano, rele, h_pdf, (
                f"{perdio}; no quedan otras filas candidatas." if perdio
                else "Sin candidatos disponibles en Excel."
            ))
            continue

        consultas += 1
        assert consultas <= cota, "asignación global sin terminar: revisar el algoritmo"
        traza: dict[str, Any] = {
            # orden_pdf es la posición dentro de la tupla: la tupla identifica la traza
            # (una descripción puede repetirse en varias tuplas).
            "pano": pano,
            "rele": rele,
            "orden_pdf": i,
            "reintento": bool(perdidas[i]) or acotadas[i] is not None,
            "filas_perdidas": sorted(
                restantes_excel[j].evidencia.fila_excel or -1 for j in perdidas[i]),
        }
        juez_resp, candidatos, confianza = _preguntar_juez(
            h_pdf, emb_pdf, disponibles, restantes_excel, emb_cache, llm_metadata,
            pano, rele, traza,
        )
        justificacion = _limpiar_justificacion_juez(juez_resp.justificacion)
        if juez_resp.indice_candidato is None or confianza < 0.5:
            mostradas = {j for j, _ in candidatos}
            ajenas = [j for j in mostradas if j in dueno]
            libres = {j for j in disponibles if j not in dueno}
            if ajenas and acotadas[i] is None and libres - mostradas:
                traza["resultado"] = "sin_match_reintenta"
                traza["filas_ajenas"] = sorted(
                    restantes_excel[j].evidencia.fila_excel or -1 for j in ajenas)
                acotadas[i] = libres
                cola.append(i)
                continue
            traza["resultado"] = "sin_match"
            perdio = nota_perdidas(i)
            cierre[i] = _falta(pano, rele, h_pdf, (
                f"{perdio}; entre las filas restantes, el juez: {justificacion}" if perdio
                else justificacion
            ))
            continue

        j = candidatos[juez_resp.indice_candidato][0]
        if j not in dueno:
            traza["resultado"] = "tomo_fila_libre"
            dueno[j] = i
            vigente[i] = (j, confianza, justificacion)
            continue
        k = dueno[j]
        confianza_k = vigente[k][1]
        traza["frente_a"] = {"orden_pdf": k, "confianza": confianza_k}
        if confianza > confianza_k:
            traza["resultado"] = "desplazo"
            dueno[j] = i
            vigente[i] = (j, confianza, justificacion)
            del vigente[k]
            perder(k, j, confianza_k, confianza, traza)
        else:
            traza["resultado"] = "rechazado"
            perder(i, j, confianza, confianza_k, traza)

    resultados_tupla: list[MatchResult] = []
    for i, h_pdf in enumerate(restantes_pdf):
        if i not in vigente:
            resultados_tupla.append(cierre[i])
            continue
        j, confianza, justificacion = vigente[i]
        resultados_tupla.append(_par(
            pano, rele, h_pdf, restantes_excel[j], confianza, justificacion, emb_cache
        ))
    historial: Perdidas = {
        id(restantes_pdf[i]): [(restantes_excel[f], p, r) for f, p, r in perdio_frente[i]]
        for i in perdio_frente if perdio_frente[i]
    }
    filas_disputadas: FilasDisputadas = {
        id(restantes_excel[j]): [restantes_pdf[k] for k in perdedores]
        for j, perdedores in disputadas.items()
    }
    return resultados_tupla, set(dueno), historial, filas_disputadas


def _notas_asignacion_global(resultados: list[MatchResult],
                             historial: Perdidas) -> list[MatchResult]:
    """La nota «antes perdió…» de cada par, según la fila con que quedó después
    del desempate por acción (no la que tenía al emparejar): sin la fila con
    que terminó y sin heredar la de otro hallazgo."""
    salida = []
    for r in resultados:
        perdio = historial.get(id(r.hallazgo_pdf)) if r.hallazgo_pdf is not None else None
        if perdio and r.hallazgo_excel is not None:
            filas = "; ".join(
                f"{_texto_fila(fila)} frente a otro hallazgo {_frente_a(p, rival)}"
                for fila, p, rival in perdio if fila is not r.hallazgo_excel
            )
            if filas:
                r = r.model_copy(update={
                    "justificacion": f"{r.justificacion} (Asignación global: antes perdió {filas}.)"
                })
        salida.append(r)
    return salida


def _marcar_filas_disputadas(resultados: list[MatchResult],
                             disputadas: FilasDisputadas) -> list[MatchResult]:
    """El par que tiene una fila disputada (la perdió, en la asignación global,
    un hallazgo del PDF de polaridad opuesta a ella; PD71) lleva el motivo en
    `emparejamiento_dudoso`: es un emparejamiento dudoso, como un
    semantico_bajo (19e(c) en 4e, «(revisar)» en la interfaz y
    `requieren_revision`). La marca es de la fila: la lleva quien la tenga
    después del desempate por acción, que puede dársela a otro hallazgo."""
    salida = []
    for r in resultados:
        perdedores = (disputadas.get(id(r.hallazgo_excel))
                      if r.hallazgo_pdf is not None and r.hallazgo_excel is not None else None)
        if perdedores:
            assert r.hallazgo_pdf is not None and r.hallazgo_excel is not None
            r = r.model_copy(update={"emparejamiento_dudoso": _motivo_fila_disputada(
                r.hallazgo_pdf, r.hallazgo_excel, perdedores)})
        salida.append(r)
    return salida


def ejecutar_matching(
    hallazgos_pdf: list[Hallazgo],
    hallazgos_excel: list[Hallazgo],
    *,
    vectores: Vectores | None = None,
    vectores_estrictos: bool = False,
    llamar: Callable[..., tuple[Any, dict[str, Any]]] | None = None,
) -> tuple[list[MatchResult], list[dict[str, Any]]]:
    """Ejecuta el matching completo entre hallazgos PDF y Excel.

    Args:
        vectores: texto → vector ya calculado (M70). Se usan esos y solo se
            calculan los que faltan, que se agregan a este mismo dict (quien
            llama los guarda, también si E4 falla después).
        vectores_estrictos: un vector faltante es VectoresFaltantesError, sin
            llamar a la API (repetición de E4 sin API).
        llamar: reemplaza a llamar_llm_estructurado en los dos jueces durante
            esta ejecución (la caché de jueces de cache_jueces).
        Sin ninguno de los tres, el comportamiento es el de siempre.

    Returns:
        Tupla de (lista de MatchResult, lista de metadata de llamadas: el
        usage de embeddings (meta["etapa"] == "embeddings"), el juez de
        matching y el juez de redacción (meta["tipo"] == "juez_redaccion")).

    Cualquier falla después de pagar llamadas (no solo las de los jueces)
    deja la metadata acumulada en la excepción original, sin cambiar su tipo
    ni su mensaje: el pipeline persiste los raw ya pagados (invariante 20).
    """
    llm_metadata: list[dict[str, Any]] = []
    token = _LLAMADOR.set(llamar)
    try:
        resultados = _ejecutar_matching(
            hallazgos_pdf, hallazgos_excel, llm_metadata, vectores, vectores_estrictos)
    except Exception as exc:
        if not isinstance(getattr(exc, "llm_metadata", None), list):
            exc.llm_metadata = llm_metadata  # type: ignore[attr-defined]
        raise
    finally:
        _LLAMADOR.reset(token)
    return resultados, llm_metadata


def _ejecutar_matching(
    hallazgos_pdf: list[Hallazgo],
    hallazgos_excel: list[Hallazgo],
    llm_metadata: list[dict[str, Any]],
    vectores: Vectores | None,
    vectores_estrictos: bool,
) -> list[MatchResult]:
    # Las filas transversales del Excel (sin relé específico, según el
    # catálogo de la empresa) no entran al matching: se apartan ANTES de
    # calcular embeddings para que no consuman tokens ni aparezcan como
    # candidatas del top-k. Van directo a su propio estado.
    transversales = [h for h in hallazgos_excel if h.es_transversal]
    hallazgos_excel = [h for h in hallazgos_excel if not h.es_transversal]

    resultados: list[MatchResult] = []
    for h_trans in transversales:
        resultados.append(MatchResult(
            pano=h_trans.pano, rele=h_trans.rele,
            estado=EstadoHallazgo.TRANSVERSAL,
            tipo_match=TipoMatch.SIN_MATCH,
            confianza=0.0,
            justificacion=(
                "Fila transversal del Excel según el catálogo de la empresa — "
                "no pertenece a un relé específico; excluida del matching, "
                "revisión manual."
            ),
            hallazgo_pdf=None, hallazgo_excel=h_trans,
        ))

    emb_cache, emb_usage = _construir_cache_embeddings(
        hallazgos_pdf, hallazgos_excel, vectores, vectores_estrictos)

    grupos_pdf = _agrupar_por_pano_rele(hallazgos_pdf)
    grupos_excel = _agrupar_por_pano_rele(hallazgos_excel)

    # Nombres legibles por tupla (la clave está normalizada): primer hallazgo
    # visto, con preferencia por la grafía del Excel (formato regulatorio).
    # Grafías distintas del mismo relé NUNCA se fusionan (decisión de la
    # revisora 2026-07-16): tuplas separadas quedan visibles como
    # falta/extra para que ella decida. La normalización de _clave_tupla
    # (separadores y mayúsculas) no es fusión.
    display: dict[tuple[str, str], tuple[str, str]] = {}
    for h in hallazgos_excel + hallazgos_pdf:
        display.setdefault(_clave_tupla(h), (h.pano, h.rele))

    todas_tuplas = set(grupos_pdf.keys()) | set(grupos_excel.keys())

    if emb_usage:
        llm_metadata.append(emb_usage)

    for clave in sorted(todas_tuplas):
        pano, rele = display[clave]
        pdf_tupla = grupos_pdf.get(clave, [])
        excel_tupla = grupos_excel.get(clave, [])

        # --- 4a: matching determinístico por unicidad de clasificación ---
        matches_unicidad, restantes_pdf, restantes_excel = _match_por_unicidad(
            pano, rele, pdf_tupla, excel_tupla, emb_cache
        )
        resultados.extend(matches_unicidad)

        # --- 4a': descripción idéntica, sin juez (M30) ---
        # DESCRIPCION_IDENTICA=false = comportamiento previo exacto.
        if settings.descripcion_identica:
            matches_identicos, restantes_pdf, restantes_excel = _match_por_descripcion_identica(
                pano, rele, restantes_pdf, restantes_excel, emb_cache
            )
            resultados.extend(matches_identicos)

        # --- 4b: matching semántico para lo restante ---
        if restantes_pdf and restantes_excel:
            # ASIGNACION_GLOBAL=false = comportamiento previo exacto (en orden).
            emparejar = (
                _emparejar_asignacion_global if settings.asignacion_global
                else _emparejar_en_orden
            )
            resultados_tupla, nuevos_matcheados_excel, historial, disputadas = emparejar(
                pano, rele, restantes_pdf, restantes_excel, emb_cache, llm_metadata
            )

            # --- 4d: extras en Excel (no matcheados) ---
            for idx_e, h_excel in enumerate(restantes_excel):
                if idx_e not in nuevos_matcheados_excel:
                    resultados_tupla.append(MatchResult(
                        pano=pano, rele=rele,
                        estado=EstadoHallazgo.EXTRA_EN_EXCEL,
                        tipo_match=TipoMatch.SIN_MATCH,
                        confianza=0.0,
                        justificacion="Hallazgo en Excel sin correspondencia en PDF.",
                        hallazgo_pdf=None, hallazgo_excel=h_excel,
                    ))

            # Después de 4d: el desempate también decide qué fila queda
            # faltante/extra cuando un lado tiene menos filas de esa descripción.
            # Las filas disputadas (asignación global) se marcan después del
            # desempate: la marca es de la fila, no del hallazgo que la ganó.
            resultados.extend(_marcar_filas_disputadas(_notas_asignacion_global(
                _desempatar_por_accion(resultados_tupla, emb_cache), historial), disputadas))

        elif restantes_pdf:
            for h_pdf in restantes_pdf:
                resultados.append(MatchResult(
                    pano=pano, rele=rele,
                    estado=EstadoHallazgo.FALTA_EN_EXCEL,
                    tipo_match=TipoMatch.SIN_MATCH,
                    confianza=0.0,
                    justificacion=f"Sin hallazgos en Excel para paño {pano} / relé {rele}.",
                    hallazgo_pdf=h_pdf, hallazgo_excel=None,
                ))

        elif restantes_excel:
            for h_excel in restantes_excel:
                resultados.append(MatchResult(
                    pano=pano, rele=rele,
                    estado=EstadoHallazgo.EXTRA_EN_EXCEL,
                    tipo_match=TipoMatch.SIN_MATCH,
                    confianza=0.0,
                    justificacion=f"Sin hallazgos en PDF para paño {pano} / relé {rele}.",
                    hallazgo_pdf=None, hallazgo_excel=h_excel,
                ))

    # --- 4e: polaridad + juez de redacción, sobre los pares ya decididos ---
    # Apagado (JUEZ_REDACCION=false) = comportamiento previo exacto.
    if settings.juez_redaccion:
        resultados = _revisar_redaccion(resultados, emb_cache, llm_metadata)

    # --- 4f: copias del mismo origen, del lado seguro (M34) ---
    return _paso_4f(resultados, emb_cache)
