"""Adjudicación del comparador alineada con su reporte y con la Etapa 3.

La adjudicación de cada ronda (``mediciones/adjudicacion/<ronda>_<modelo>_<informe>.json``,
p. ej. ``b2_opus_Gamma.json``) clasifica cada resultado de un
``reporte_final.json`` por su índice (``idx``), y el índice no es estable entre
corridas. Este módulo:

- lee los ítems con su clase final (la del segundo verificador si la corrigió) y
  su nivel de validación;
- comprueba que cada ítem sea de su resultado: paño, relé, estado, página y fila
  (``alinear``), y ubica su hallazgo del PDF en ``etapa3_pdf_hallazgos.json``;
- arma las claves estables con que el GT del comparador se busca en otro reporte
  (``claves_del_item``, ``buscar``): lado Excel = tupla + fila; lado PDF = tupla +
  página + clasificación + la cita adjudicada contenida en el texto del hallazgo.
  La tupla se normaliza como en la Etapa 4 (``etapa4_matching.clave_tupla``).

**Regla de contraparte.** Cuando el resultado no tiene un lado (una «falta en
Excel» no tiene hallazgo del Excel; un «extra en Excel», del PDF), lo que la
adjudicación anota en ese lado es la contraparte que el adjudicador estimó, no
un lado del resultado: no se compara con el reporte ni entra en las claves. Las
marcas ``es_contraparte`` explícitas deben coincidir con la regla.

**Nivel de validación.** ``verificado``: el segundo agente revisó el ítem (lo
confirmó o corrigió su clase, y manda la suya). ``solo_adjudicador``: no lo
revisó. Ninguno de los dos es una validación del equipo revisor.

**Repeticiones de E4.** La adjudicación de una repetición de E4
(``comparador.reproducir_e4``) declara en su cabecera ``repeticion_e4``: su
carpeta (``replay_e4/<etiqueta>/<run_id>``, con el run_id de su run de origen) y
la ronda de ese origen. El reporte es el de la repetición; la Etapa 3, la del
run de origen (la repetición solo rehace E4 y E5).
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from comparador.etapa4_matching import clave_tupla
from comparador.schemas import CampoDiferente, EstadoHallazgo, Hallazgo, MatchResult

CLASES = ("A", "B", "C", "D", "E", "OK")
ORDEN_CAMPOS = (CampoDiferente.DESCRIPCION, CampoDiferente.ACCION_CORRECTIVA,
                CampoDiferente.CALIFICACION)


class AlineacionError(ValueError):
    """Un ítem adjudicado no corresponde a su resultado o a la Etapa 3."""


class NivelValidacion(StrEnum):
    VERIFICADO = "verificado"
    SOLO_ADJUDICADOR = "solo_adjudicador"


# ------------------------------------------------------------ clase y lados


def subclase_final(item: Mapping[str, Any]) -> str:
    """Subclase final (A1, D6, OK...): la del segundo verificador si la corrigió."""
    corregida = (item.get("verificacion") or {}).get("clase_corregida")
    return str(corregida or item.get("subclase") or item.get("clase") or "")


def clase_final(item: Mapping[str, Any]) -> str:
    """Clase de un ítem adjudicado: la letra (A..E) u "OK"."""
    valor = subclase_final(item)
    return "OK" if valor.upper().startswith("OK") else valor[:1].upper()


def lados_del_estado(estado: EstadoHallazgo) -> tuple[bool, bool]:
    """(tiene lado PDF, tiene lado Excel) de un resultado con ese estado."""
    return (estado != EstadoHallazgo.EXTRA_EN_EXCEL and estado != EstadoHallazgo.TRANSVERSAL,
            estado != EstadoHallazgo.FALTA_EN_EXCEL)


@dataclass(frozen=True)
class LadoAdjudicado:
    """Lo que el adjudicador anotó de un lado: página (PDF) o fila (Excel) y cita."""

    referencia: int
    cita: str
    es_contraparte: bool


@dataclass(frozen=True)
class ItemAdjudicado:
    idx: int
    pano: str
    rele: str
    estado: EstadoHallazgo
    clase: str
    subclase: str
    pdf: LadoAdjudicado | None
    excel: LadoAdjudicado | None
    duplica_idx: int | None
    contraparte_idx: int | None
    nivel_validacion: NivelValidacion
    explicacion: str
    nota_verificacion: str
    # Preguntas abiertas (numeración de tasks/equipo/preguntas_v3.md: «P14») de las
    # que depende un criterio por definir, si la adjudicación las nombra.
    depende_de: tuple[str, ...] = ()

    @property
    def lado_pdf_propio(self) -> LadoAdjudicado | None:
        return None if self.pdf is None or self.pdf.es_contraparte else self.pdf

    @property
    def lado_excel_propio(self) -> LadoAdjudicado | None:
        return None if self.excel is None or self.excel.es_contraparte else self.excel


def _lado(datos: Mapping[str, Any] | None, campo: str, propio: bool,
          idx: int) -> LadoAdjudicado | None:
    if not datos or datos.get(campo) is None:   # p. ej. {"fila": null, "cita": null}
        return None
    es_contraparte = not propio
    marcado = datos.get("es_contraparte")
    if marcado is not None and bool(marcado) != es_contraparte:
        raise ValueError(f"idx {idx}: es_contraparte={marcado} contradice la regla de "
                         "contraparte (el lado existe en el resultado si y solo si no es "
                         "contraparte)")
    return LadoAdjudicado(int(datos[campo]), str(datos.get("cita") or ""), es_contraparte)


_PREGUNTA = re.compile(r"P\d+")


def _depende_de(datos: Mapping[str, Any], idx: int) -> tuple[str, ...]:
    valor = datos.get("depende_de") or []
    if not isinstance(valor, list) or not all(
            isinstance(p, str) and _PREGUNTA.fullmatch(p) for p in valor):
        raise ValueError(f"idx {idx}: depende_de {valor!r} no es una lista de preguntas de la "
                         "v3 (P14, P19…)")
    return tuple(valor)


def item_desde_dict(datos: Mapping[str, Any]) -> ItemAdjudicado:
    """Un ítem de la adjudicación, con clase final y la regla de contraparte."""
    idx = int(datos["idx"])
    clase = clase_final(datos)
    if clase not in CLASES:
        raise ValueError(f"clase desconocida {clase!r} en idx {idx}")
    subclase = "OK" if clase == "OK" else subclase_final(datos)
    estado = EstadoHallazgo(datos["estado"])
    con_pdf, con_excel = lados_del_estado(estado)
    verificacion = datos.get("verificacion") or {}
    return ItemAdjudicado(
        idx=idx, pano=str(datos["pano"]), rele=str(datos["rele"]), estado=estado,
        clase=clase, subclase=subclase,
        pdf=_lado(datos.get("pdf"), "pagina", con_pdf, idx),
        excel=_lado(datos.get("excel"), "fila", con_excel, idx),
        duplica_idx=datos.get("duplica_idx"), contraparte_idx=datos.get("contraparte_idx"),
        nivel_validacion=(NivelValidacion.VERIFICADO if verificacion
                          else NivelValidacion.SOLO_ADJUDICADOR),
        explicacion=str(datos.get("explicacion") or ""),
        nota_verificacion=str(verificacion.get("nota") or ""),
        depende_de=_depende_de(datos, idx),
    )


CARPETA_REPETICIONES = "replay_e4"


def carpeta_del_run(ronda: str, run_id: str, ronda_origen: str | None = None) -> str:
    """Carpeta de un run bajo mediciones/: ``bN/runs/<run_id>`` en una ronda, y
    ``replay_e4/<etiqueta>/<run_id>`` en una repetición de E4 (``ronda_origen``:
    la ronda del run que repite, cuyo run_id lleva)."""
    if ronda_origen is not None:
        return f"{CARPETA_REPETICIONES}/{ronda}/{run_id}"
    return f"{ronda.lower()}/runs/{run_id}"


@dataclass(frozen=True)
class Adjudicacion:
    """Un archivo de mediciones/adjudicacion: cabecera completa e ítems."""

    ruta: Path
    informe: str           # carpeta del informe
    ronda: str             # en una repetición de E4, su etiqueta (p. ej. AG1)
    modelo: str
    run_id: str
    items: list[ItemAdjudicado]
    cabecera: dict[str, Any]
    # Repetición de E4: la ronda de su run de origen (None en una ronda).
    ronda_origen: str | None = None

    @property
    def carpeta(self) -> str:
        """Carpeta de su run bajo mediciones/ (``carpeta_del_run``)."""
        return carpeta_del_run(self.ronda, self.run_id, self.ronda_origen)

    @property
    def carpeta_e3(self) -> str:
        """Carpeta de su Etapa 3: la del run de origen en una repetición de E4."""
        if self.ronda_origen is None:
            return self.carpeta
        return carpeta_del_run(self.ronda_origen, self.run_id)


def _ronda_origen(datos: Mapping[str, Any], ronda: str, run_id: str) -> str | None:
    """La ronda de origen que declara una repetición de E4 (None si no lo es),
    con su carpeta comprobada: ``replay_e4/<su etiqueta>/<el run_id de su origen>``."""
    repeticion = datos.get("repeticion_e4")
    if repeticion is None:
        return None
    origen = str(repeticion.get("ronda_origen") or "")
    esperada = carpeta_del_run(ronda, run_id, origen)
    if not origen or repeticion.get("carpeta") != esperada:
        raise ValueError(f"repeticion_e4: carpeta {repeticion.get('carpeta')!r} y ronda de "
                         f"origen {origen!r}; se espera la carpeta {esperada!r} (la etiqueta "
                         "de la ronda y el run_id de su origen) y la ronda de origen")
    return origen


def cargar_adjudicacion(ruta: Path) -> Adjudicacion:
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    ronda, run_id = str(datos.get("ronda", "")), str(datos.get("run_id", ""))
    try:
        items = [item_desde_dict(i) for i in datos.get("items", [])]
        ronda_origen = _ronda_origen(datos, ronda, run_id)
    except (KeyError, ValueError) as e:
        raise ValueError(f"{ruta.name}: {e}") from e
    return Adjudicacion(
        ruta=ruta, informe=str(datos.get("informe", ruta.stem)), ronda=ronda,
        modelo=str(datos.get("modelo", "")), run_id=run_id, items=items,
        cabecera={k: v for k, v in datos.items() if k != "items"}, ronda_origen=ronda_origen,
    )


def nombre_corto(carpeta: str) -> str:
    """'S-E Añañuca (Auditora Reliable Energy)' → 'Añañuca' (en NFC)."""
    nombre = unicodedata.normalize("NFC", carpeta).strip()
    nombre = re.sub(r"\s*\([^)]*\)\s*$", "", nombre)
    return re.sub(r"^S-?E\s+", "", nombre, flags=re.IGNORECASE)


def directorio_run(mediciones: Path, adj: Adjudicacion) -> Path:
    """Carpeta del run adjudicado (la de la repetición, en una repetición de E4)."""
    return mediciones / adj.carpeta


# ------------------------------------------------------------ alineación


def paginas_del_hallazgo(h: Hallazgo) -> set[int]:
    """Páginas con que se puede referir un hallazgo del PDF: la suya y, en un
    reporte 0.7.0 re-anclado, la que citó el modelo (``pagina_citada``)."""
    ev = h.evidencia
    paginas = {ev.pagina_pdf} if ev.pagina_pdf is not None else set()
    for v in (ev.verificacion_descripcion, ev.verificacion_accion):
        if v is not None and v.pagina_citada is not None:
            paginas.add(v.pagina_citada)
    return paginas


def _huella(h: Hallazgo) -> str:
    return h.model_dump_json()


def mapa_e3(resultados: Sequence[MatchResult], e3: Sequence[Hallazgo]) -> dict[int, int]:
    """Índice del resultado → índice de su hallazgo del PDF en la Etapa 3.

    Cada hallazgo de E3 debe aparecer exactamente una vez como ``hallazgo_pdf``
    del reporte (por igualdad de contenido). Los idénticos se reparten en orden.
    """
    libres: dict[str, list[int]] = defaultdict(list)
    for j, h in enumerate(e3):
        libres[_huella(h)].append(j)
    mapa: dict[int, int] = {}
    for i, r in enumerate(resultados):
        if r.hallazgo_pdf is None:
            continue
        cola = libres.get(_huella(r.hallazgo_pdf))
        if not cola:
            raise AlineacionError(f"resultado {i}: su hallazgo del PDF no está en la Etapa 3 "
                                  "(o aparece más veces en el reporte que en E3)")
        mapa[i] = cola.pop(0)
    sobrantes = sorted(j for cola in libres.values() for j in cola)
    if sobrantes:
        raise AlineacionError(f"hallazgos de la Etapa 3 que no llegan al reporte: {sobrantes}")
    return mapa


def _alinear(item: ItemAdjudicado, resultados: Sequence[MatchResult],
             indices: Mapping[int, int]) -> int | None:
    if not 0 <= item.idx < len(resultados):
        raise AlineacionError(f"idx {item.idx}: no existe en el reporte "
                              f"({len(resultados)} resultados)")
    r = resultados[item.idx]
    problemas = [
        f"{nombre} {visto!r} ≠ {adjudicado!r}"
        for nombre, visto, adjudicado in (("paño", r.pano, item.pano), ("relé", r.rele, item.rele),
                                          ("estado", r.estado.value, item.estado.value))
        if visto != adjudicado
    ]
    pdf, excel = item.lado_pdf_propio, item.lado_excel_propio
    if not problemas:
        if pdf is not None and r.hallazgo_pdf is not None and (
                pdf.referencia not in paginas_del_hallazgo(r.hallazgo_pdf)):
            problemas.append(f"página {sorted(paginas_del_hallazgo(r.hallazgo_pdf))} ≠ "
                             f"{pdf.referencia}")
        if excel is not None and r.hallazgo_excel is not None and (
                excel.referencia != r.hallazgo_excel.evidencia.fila_excel):
            problemas.append(f"fila {r.hallazgo_excel.evidencia.fila_excel} ≠ "
                             f"{excel.referencia}")
    if problemas:
        raise AlineacionError(f"idx {item.idx} no corresponde a su resultado: "
                              + "; ".join(problemas))
    return indices.get(item.idx)


def alinear(item: ItemAdjudicado, resultados: Sequence[MatchResult],
            e3: Sequence[Hallazgo]) -> int | None:
    """Comprueba que el ítem sea de su resultado (paño, relé, estado, página y
    fila) y devuelve el índice de su hallazgo del PDF en la Etapa 3 (None si el
    resultado no tiene lado PDF). AlineacionError si algo no corresponde."""
    return _alinear(item, resultados, mapa_e3(resultados, e3))


def alinear_todos(adj: Adjudicacion, resultados: Sequence[MatchResult],
                  e3: Sequence[Hallazgo]) -> dict[int, int | None]:
    """``alinear`` de cada ítem: idx → índice en E3."""
    indices = mapa_e3(resultados, e3)
    try:
        return {it.idx: _alinear(it, resultados, indices) for it in adj.items}
    except AlineacionError as e:
        raise AlineacionError(f"{adj.ruta.name}: {e}") from e


@dataclass(frozen=True)
class AdjudicacionAlineada:
    adjudicacion: Adjudicacion
    resultados: list[MatchResult]
    e3: list[Hallazgo]
    indices_e3: dict[int, int | None]


def cargar_alineada(mediciones: Path, ruta: Path) -> AdjudicacionAlineada:
    """Adjudicación + reporte + Etapa 3 de su run (la del run de origen en una
    repetición de E4), con cada ítem alineado."""
    adj = cargar_adjudicacion(ruta)
    reporte = directorio_run(mediciones, adj) / "reporte_final.json"
    ruta_e3 = mediciones / adj.carpeta_e3 / "etapa3_pdf_hallazgos.json"
    for archivo in (reporte, ruta_e3):
        if not archivo.exists():
            raise ValueError(f"{ruta.name}: no existe {archivo}")
    resultados = [MatchResult.model_validate(r)
                  for r in json.loads(reporte.read_text(encoding="utf-8"))["resultados"]]
    e3 = [Hallazgo.model_validate(h) for h in json.loads(ruta_e3.read_text(encoding="utf-8"))]
    return AdjudicacionAlineada(adj, resultados, e3, alinear_todos(adj, resultados, e3))


# ------------------------------------------------------------ claves estables


def normalizar_texto(texto: str) -> str:
    """NFKC, sin mayúsculas y con los espacios colapsados."""
    return " ".join(unicodedata.normalize("NFKC", texto).casefold().split())


def normalizar_cita(texto: str) -> str:
    """Como ``normalizar_texto`` y además solo letras y dígitos: la cita se
    copió de la capa de texto del PDF («Criticidad menor • Se debe…») y la
    Etapa 3 separa las celdas con « | » en el texto crudo."""
    return " ".join(re.sub(r"[^\w]+", " ", normalizar_texto(texto)).replace("_", " ").split())


def campos_que_difieren(r: MatchResult) -> tuple[CampoDiferente, ...]:
    """Campos con diferencia, en el orden del reporte al revisor (invariante 16)."""
    return tuple(c for c in ORDEN_CAMPOS if c in {d.campo for d in r.diferencias})


@dataclass(frozen=True)
class ClaveExcel:
    tupla: tuple[str, str]
    fila: int

    @classmethod
    def de(cls, pano: str, rele: str, fila: int) -> ClaveExcel:
        return cls(clave_tupla(pano, rele), fila)

    def calza(self, h: Hallazgo | None) -> bool:
        return (h is not None and h.evidencia.fila_excel == self.fila
                and clave_tupla(h.pano, h.rele) == self.tupla)


@dataclass(frozen=True)
class ClavePdf:
    """Tupla, página y citas, normalizadas. Calza si alguna cita está en la
    descripción, la acción o el texto crudo del hallazgo.

    La clasificación no entra: la Etapa 3 de Sonnet usa el rótulo de la fila
    del informe («Documentación Técnica») y la de Opus la categoría del
    catálogo («Verificación ECAP») para el mismo hallazgo; con ella, el GT de
    Sonnet se encuentra en el run de Opus en 239 de 297 ítems, sin ella en 288
    (y la cita ya distingue los hallazgos de una misma página).
    """

    tupla: tuple[str, str]
    pagina: int
    citas: tuple[str, ...]

    @classmethod
    def de(cls, pano: str, rele: str, pagina: int, citas: Sequence[str]) -> ClavePdf:
        normalizadas = tuple(dict.fromkeys(n for c in citas if (n := normalizar_cita(c))))
        if not normalizadas:
            raise ValueError(f"clave del PDF sin cita ({pano}, {rele}, pág. {pagina})")
        return cls(clave_tupla(pano, rele), pagina, normalizadas)

    def calza(self, h: Hallazgo | None) -> bool:
        if (h is None or clave_tupla(h.pano, h.rele) != self.tupla
                or self.pagina not in paginas_del_hallazgo(h)):
            return False
        textos = [normalizar_cita(t) for t in (h.descripcion, h.accion_correctiva or "",
                                                h.evidencia.texto_crudo)]
        return any(cita in texto for cita in self.citas for texto in textos)


@dataclass(frozen=True)
class Claves:
    excel: ClaveExcel | None
    pdf: ClavePdf | None

    def calza(self, r: MatchResult) -> bool:
        """Cada clave presente calza con el lado correspondiente del resultado."""
        return ((self.excel is None or self.excel.calza(r.hallazgo_excel))
                and (self.pdf is None or self.pdf.calza(r.hallazgo_pdf)))

    def calza_algun_lado(self, r: MatchResult) -> bool:
        return ((self.excel is not None and self.excel.calza(r.hallazgo_excel))
                or (self.pdf is not None and self.pdf.calza(r.hallazgo_pdf)))


def claves_del_item(item: ItemAdjudicado, resultado: MatchResult) -> Claves:
    """Claves de los lados propios de un ítem ya alineado con su resultado, con
    la cita que anotó el adjudicador."""
    excel = pdf = None
    if item.lado_excel_propio is not None and resultado.hallazgo_excel is not None:
        h = resultado.hallazgo_excel
        excel = ClaveExcel.de(h.pano, h.rele, item.lado_excel_propio.referencia)
    if item.lado_pdf_propio is not None and resultado.hallazgo_pdf is not None:
        h = resultado.hallazgo_pdf
        pdf = ClavePdf.de(h.pano, h.rele, item.lado_pdf_propio.referencia,
                          [item.lado_pdf_propio.cita])
    return Claves(excel, pdf)


@dataclass(frozen=True)
class Busqueda:
    estado: Literal["unico", "ninguno", "ambiguo"]
    indices: tuple[int, ...]


def buscar(claves: Claves, resultados: Sequence[MatchResult]) -> Busqueda:
    """Resultados de un reporte cuyos lados calzan con todas las claves."""
    if claves.excel is None and claves.pdf is None:
        raise ValueError("búsqueda sin claves")
    indices = tuple(i for i, r in enumerate(resultados) if claves.calza(r))
    estado: Literal["unico", "ninguno", "ambiguo"] = (
        "ninguno" if not indices else "unico" if len(indices) == 1 else "ambiguo")
    return Busqueda(estado, indices)
