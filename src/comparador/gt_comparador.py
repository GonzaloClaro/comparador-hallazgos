"""GT del comparador (M64): un archivo por informe con la adjudicación de B2 y de
las rondas posteriores.

Une las adjudicaciones de un informe (``mediciones/adjudicacion``, una por ronda
y modelo) en ``mediciones/gt/comparador/<carpeta del informe>.json``. Es privado:
lleva las citas de los informes (D2).

**Rondas.** Las adjudicaciones de la primera ronda (hoy B2, Sonnet y Opus) son las
fuentes base: cada una adjudica todas las alertas de su run. Una ronda posterior
(B3) complementa el GT de las anteriores: su run se evalúa contra él, y su
adjudicación debe cubrir las alertas que ese GT no adjudica (las demás ya las
adjudican los ítems de antes por clave estable; si las vuelve a adjudicar, se
fusionan con las mismas reglas). Sus ítems se suman al final, sin mover los ids.
Una ronda es ``B<número>`` (su run en ``bN/runs/<run_id>``) o una repetición de
E4 (``comparador.reproducir_e4``: su etiqueta, p. ej. AG1, con el reporte en
``replay_e4/<etiqueta>/<run_id>``, el run_id de su run de origen, y la Etapa 3
de ese origen), que complementa al menos el GT de su ronda de origen. Las rondas
se ordenan por cuándo se corrieron (su primera corrida: la fecha del run_id o,
en una repetición, la ``fecha_inicio`` de su metadata.json), así un GT se
completa sin mover ids; las rondas B deben quedar en el orden de su número y
cada repetición después de su ronda de origen. Una fuente se identifica por su
carpeta (``carpeta``: la repetición comparte el run_id con su origen) y cada
origen de un ítem, por su ronda y su run.

Cada ítem se identifica por claves estables, nunca por el índice del resultado
(``comparador.adjudicacion``): lado Excel = tupla + fila; lado PDF = tupla +
página + alguna de sus citas; más el estado y, en un «difiere», los campos que
difieren (D4). Un ítem de una fuente cuyo resultado calza con un ítem de otra
fuente (las mismas claves, estado y campos) se fusiona con él; si su clase es
otra, falla (D3). Además de clase y subclase, cada ítem lleva:

- ``nivel_validacion``: ``verificado`` (el segundo agente lo revisó en alguna de
  las fuentes) o ``solo_adjudicador``. Ninguno es una validación del equipo
  revisor.
- ``depende_de``: las preguntas abiertas de ``tasks/equipo/preguntas_v3.md`` de las
  que depende un «criterio por definir» (C): las que nombra el ``depende_de``
  de su adjudicación y las tablas explícitas ``PREGUNTAS_V3`` y
  ``PREGUNTAS_SIN_MENCION``. Una C sin pregunta falla.
- ``duplica_de``: el ítem del que es copia (el mismo par desdoblado en dos paños).
- ``etapa_causa`` y ``campos_extraccion`` (solo falsas alarmas D): la etapa que
  la origina y qué campo de la Etapa 3 falló (``CAUSA_POR_SUBCLASE`` y la lista
  revisable ``CAUSA_POR_ITEM``).
- ``origenes``: de qué run e índice sale en cada fuente, con su explicación.

El universo de cada fuente dice qué se adjudicó: todos los resultados no
transversales, o todas las alertas y una muestra de «coincide» (Beta y
Eta; ahí los «coincide» con texto idéntico en los 3 campos cuentan por
regla, D13, en una columna aparte). En una ronda posterior cuenta también lo que
ya adjudicaba el GT de las anteriores (``adjudicados_antes``). ``errores_excel``
guarda los errores reales del Excel que la herramienta no mostró en B2 (M27). El
GT se ata al sha256 del informe original y del Excel: el del PDF convertido de
un DOCX no es reproducible.

Uso:
    python -m comparador.gt_comparador construir [--mediciones M] [--salida D] [--sobrescribir]
    python -m comparador.gt_comparador validar [--mediciones M] [--gt D]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, NamedTuple, TypeVar

from pydantic import BaseModel, ConfigDict, model_validator

from comparador.adjudicacion import (
    Adjudicacion,
    AdjudicacionAlineada,
    ClaveExcel,
    ClavePdf,
    Claves,
    ItemAdjudicado,
    NivelValidacion,
    buscar,
    campos_que_difieren,
    cargar_alineada,
    carpeta_del_run,
    directorio_run,
    lados_del_estado,
    nombre_corto,
)
from comparador.persistence import MODO_REPLAY_E4
from comparador.rutas import exigir_ignorada_por_git
from comparador.schemas import CampoDiferente, EstadoHallazgo, MatchResult

RAIZ = Path(__file__).resolve().parent.parent.parent
# 2.0: el universo va en cada fuente, las fuentes de una ronda posterior
# (``complementa``) y los orígenes atados al run de su fuente. 3.0: las
# repeticiones de E4 como fuentes (el run_id de su origen): cada fuente lleva su
# carpeta y su ronda de origen, y cada origen de un ítem su ronda.
VERSION_GT = "3.0"
ORDEN_MODELOS = ("claude-sonnet-5-5", "claude-opus-5-5")
CAMPOS_TEXTO = ("descripcion", "accion_correctiva", "calificacion")
_T = TypeVar("_T")


class GtError(ValueError):
    """El GT no se puede construir o no es válido."""


class ConflictoGtError(GtError):
    """Dos modelos adjudicaron distinto la misma clave."""


class CampoExtraccion(StrEnum):
    """Qué falló de la Etapa 3 en una falsa alarma que viene de la extracción."""

    TUPLA = "tupla"                 # paño o relé
    DESCRIPCION = "descripcion"
    ACCION = "accion_correctiva"
    CALIFICACION = "calificacion"
    CLASIFICACION = "clasificacion"
    OMISION = "omision"             # no extrajo el hallazgo para esa tupla
    DE_MAS = "de_mas"               # extrajo un hallazgo que no existe


EtapaCausa = Literal["e1", "e3", "e4"]
Clase = Literal["A", "B", "C", "D", "E", "OK"]

# ---------------------------------------------------------------- tablas explícitas

# Preguntas de la adjudicación (numeración vieja, «pregunta 4.1») → numeración
# nueva de tasks/equipo/preguntas_v3.md. Solo cuentan en los ítems C: en una D5
# la mención explica qué hay detrás, no es una dependencia.
PREGUNTAS_V3: dict[str, tuple[str, ...]] = {
    "4.1": ("P14",),          # incumplimiento repetido en la tabla: ¿una vez por relé?
    "4.2": ("P15", "P16"),    # prueba pendiente: ¿una fila o dos?; pendiente fuera de la tabla
    "4.3": ("P17",),          # «No cumple» calificado «Sin hallazgo»
}
# Ítems C cuya explicación no cita pregunta, por (subestación, subclase). Una
# adjudicación nueva nombra la pregunta en ``depende_de`` (numeración de la v3).
PREGUNTAS_SIN_MENCION: dict[tuple[str, str], tuple[str, ...]] = {
    ("Añañuca", "C1"): ("P14",),   # la misma falta en dos filas de la tabla, el Excel una vez
    ("Añañuca", "C2"): ("P19",),   # el Excel redacta una acción que el informe no trae
    ("Alfa", "C2"): ("P18",),  # reparto de un hallazgo entre los relés del transformador
}

# Etapa que origina cada subclase de falsa alarma y qué campo de E3 falló.
# D7 («otro error de extracción») no tiene valor por defecto: va ítem por ítem.
CAUSA_POR_SUBCLASE: dict[str, tuple[EtapaCausa, tuple[CampoExtraccion, ...]]] = {
    "D1": ("e3", (CampoExtraccion.OMISION,)),   # la extracción omitió el hallazgo en un relé
    "D2": ("e3", (CampoExtraccion.DE_MAS,)),    # la extracción creó un hallazgo de más
    "D3": ("e3", (CampoExtraccion.TUPLA,)),     # paño o relé mal asignado
    "D4": ("e1", (CampoExtraccion.TUPLA,)),     # sub-paño o normalización (Etapa 1); 0 en B2
    "D5": ("e4", ()),                           # el juez emparejó mal
    "D6": ("e4", ()),                           # paráfrasis no reconocida
}
_VINETA_ECAP: tuple[EtapaCausa, tuple[CampoExtraccion, ...]] = (
    "e3", (CampoExtraccion.DESCRIPCION,))
# Excepciones por (ronda, modelo, subestación, idx de su adjudicación). Fuente:
# la explicación de cada ítem y las notas de b2_opus_Gamma.json.
CAUSA_POR_ITEM: dict[tuple[str, str, str, int],
                     tuple[EtapaCausa, tuple[CampoExtraccion, ...]]] = {
    # Gamma, págs. 13 y 16: E3 copió entera a cada relé la viñeta del ECAP
    # que reparte funciones entre relés; el Excel trae solo lo de cada uno (P18).
    # Opus: 7 de sus 11 D6 (5 de 9 sin duplicados), 06_mejoras M15.
    **{("B2", "claude-opus-5-5", "Gamma", i): _VINETA_ECAP
       for i in (3, 9, 14, 20, 48, 56, 62)},
    # Sonnet: los mismos pares en su run (3, 9, 14, 19 y la copia 47 del 3); su
    # explicación lo dice («la extracción copió la celda completa a cada relé»).
    **{("B2", "claude-sonnet-5-5", "Gamma", i): _VINETA_ECAP for i in (3, 9, 14, 19, 47)},
    # Alfa (Sonnet), D7: E3 partió un ítem en dos; este pedazo trae otra
    # descripción y la acción vacía.
    ("B2", "claude-sonnet-5-5", "Alfa", 47): ("e3", (CampoExtraccion.DESCRIPCION,
                                                          CampoExtraccion.ACCION)),
    ("B2", "claude-sonnet-5-5", "Alfa", 56): ("e3", (CampoExtraccion.DESCRIPCION,
                                                          CampoExtraccion.ACCION)),
    # Alfa (Sonnet), D7: E3 convirtió en hallazgo un bloque que cumple.
    ("B2", "claude-sonnet-5-5", "Alfa", 99): ("e3", (CampoExtraccion.DE_MAS,)),
}


class ErrorExcelDef(NamedTuple):
    """Error real del Excel que la herramienta no mostró en B2 (04 §3.7, M27).
    Los mismos casos que tests/golden/test_golden_errores_no_mostrados.py."""

    subestacion: str
    fila_excel: int
    pagina_pdf: int
    clasificacion_pdf: str            # etiqueta genérica del hallazgo del PDF
    campos: tuple[str, ...]           # los únicos campos que deben diferir
    subclase: str
    contraparte_validada: bool        # False: estimación del verificador
    no_mostrado_en_b2: tuple[str, ...]
    fuente_modelo: str                # adjudicación de la que salen las citas
    fuente_idx: int | None            # ítem con las citas; None: error_excel_no_detectado
    fuente_ronda: str = "B2"


ERRORES_EXCEL_B2 = (
    ErrorExcelDef("Alfa", 107, 32, "Verificación ECAP", ("calificacion",), "A4", True,
                  ("claude-opus-5-5",), "claude-opus-5-5", 99),
    ErrorExcelDef("Alfa", 98, 31, "Verificación ECAP", ("calificacion",), "A4", True,
                  ("claude-sonnet-5-5",), "claude-sonnet-5-5", 102),
    ErrorExcelDef("Añañuca", 39, 20, "Ver. Coord. de Protecciones", ("descripcion",), "A3", False,
                  ("claude-sonnet-5-5", "claude-opus-5-5"), "claude-opus-5-5", None),
)

# ---------------------------------------------------------------- formato


class _Estricto(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CitaGt(_Estricto):
    texto: str
    # adjudicacion: la cita literal que anotó el adjudicador. descripcion_e3: la
    # cita adjudicada no está en el hallazgo (citó el contexto del PDF, p. ej. que
    # el bloque cumple) y la clave usa la descripción que extrajo E3.
    fuente: Literal["adjudicacion", "descripcion_e3"]
    modelo: str


class LadoExcelGt(_Estricto):
    fila: int
    citas: list[CitaGt] = []          # informativas: la clave es la fila


class LadoPdfGt(_Estricto):
    pagina: int
    clasificaciones: list[str]        # las de E3 de cada modelo; no entran en la clave
    citas: list[CitaGt]               # la clave calza con alguna


class ReferenciaGt(_Estricto):
    """Contraparte que estimó el adjudicador para el lado que el resultado no tiene."""

    referencia: int                   # página o fila
    cita: str


class OrigenGt(_Estricto):
    modelo: str
    ronda: str                        # con run_id, su fuente (una repetición comparte run_id)
    run_id: str
    idx: int
    tipo_match: str
    subclase: str
    nivel_validacion: NivelValidacion
    duplica_idx: int | None = None
    contraparte_idx: int | None = None
    contraparte_pdf: ReferenciaGt | None = None
    contraparte_excel: ReferenciaGt | None = None
    explicacion: str = ""
    nota_verificacion: str = ""


class ItemGt(_Estricto):
    id: str
    pano: str
    rele: str
    estado: EstadoHallazgo
    campos: list[CampoDiferente]
    lado_excel: LadoExcelGt | None
    lado_pdf: LadoPdfGt | None
    clase: Clase
    subclase: str
    nivel_validacion: NivelValidacion
    depende_de: list[str] = []
    # Copia de otro resultado (el mismo par desdoblado en dos paños): no cuenta
    # «sin duplicados». duplica_de: el original, si también está en el GT.
    es_duplicado: bool = False
    duplica_de: str | None = None
    etapa_causa: EtapaCausa | None = None
    campos_extraccion: list[CampoExtraccion] = []
    origenes: list[OrigenGt]

    @model_validator(mode="after")
    def _coherente(self) -> ItemGt:
        problemas = []
        if self.estado == EstadoHallazgo.TRANSVERSAL:
            problemas.append("los transversales no entran al GT (invariante 19b)")
        if (self.lado_pdf is not None, self.lado_excel is not None) != lados_del_estado(
                self.estado):
            problemas.append(f"lados que no corresponden al estado {self.estado.value}")
        if self.lado_pdf is not None and not self.lado_pdf.citas:
            problemas.append("lado PDF sin cita")
        if (self.estado == EstadoHallazgo.DIFIERE) != bool(self.campos):
            problemas.append("campos solo y siempre en un «difiere»")
        if not (self.subclase == self.clase == "OK" or self.subclase.startswith(self.clase)):
            problemas.append(f"subclase {self.subclase} no es de la clase {self.clase}")
        if (self.clase == "C") != bool(self.depende_de):
            problemas.append("depende_de solo y siempre en un criterio por definir (C)")
        if (self.clase == "D") != (self.etapa_causa is not None):
            problemas.append("etapa_causa solo y siempre en una falsa alarma (D)")
        if self.duplica_de is not None and not self.es_duplicado:
            problemas.append("duplica_de sin es_duplicado")
        if self.clase != "D" and self.campos_extraccion:
            problemas.append("campos_extraccion solo en una falsa alarma (D)")
        fuentes = [(o.ronda, o.run_id) for o in self.origenes]
        if not fuentes or len(set(fuentes)) != len(fuentes):
            problemas.append(f"orígenes vacíos o repetidos: {fuentes}")
        if problemas:
            raise ValueError(f"ítem {self.id}: " + "; ".join(problemas))
        return self

    def lados(self) -> tuple[bool, bool]:
        return (self.lado_pdf is not None, self.lado_excel is not None)

    def claves(self) -> Claves:
        excel = (None if self.lado_excel is None
                 else ClaveExcel.de(self.pano, self.rele, self.lado_excel.fila))
        pdf = (None if self.lado_pdf is None
               else ClavePdf.de(self.pano, self.rele, self.lado_pdf.pagina,
                                [c.texto for c in self.lado_pdf.citas]))
        return Claves(excel, pdf)

    def calza_par(self, r: MatchResult) -> bool:
        """El resultado tiene los mismos lados y cada clave calza (el mismo par)."""
        return (r.hallazgo_pdf is not None, r.hallazgo_excel is not None) == self.lados() and (
            self.claves().calza(r))

    def mismo_estado_y_campos(self, r: MatchResult) -> bool:
        """Mismo estado y, en un «difiere», los mismos campos que difieren (D4)."""
        return r.estado == self.estado and list(campos_que_difieren(r)) == self.campos

    def adjudica(self, r: MatchResult) -> bool:
        """El mismo par, con el mismo estado y los mismos campos: la misma clave."""
        return self.calza_par(r) and self.mismo_estado_y_campos(r)


class BarridoGt(_Estricto):
    """«Coincide» del reporte de la fuente y cuántos tienen texto idéntico (D13)."""

    coincide: int
    texto_identico: int


class UniversoGt(_Estricto):
    regla: str
    coincide: Literal["todos", "muestra"]
    resultados: int
    transversales: int
    items: int                        # los que adjudica su archivo
    barrido: BarridoGt
    # Ronda posterior: resultados del run que ya adjudicaba el GT de las rondas
    # anteriores (por clave estable). 0 en una fuente base.
    adjudicados_antes: int = 0


class FuenteGt(_Estricto):
    modelo: str
    ronda: str                        # en una repetición de E4, su etiqueta (AG1)
    run_id: str
    # Carpeta de su run bajo mediciones/ (``adjudicacion.carpeta_del_run``):
    # bN/runs/<run_id>, o replay_e4/<etiqueta>/<run_id> en una repetición de E4.
    carpeta: str
    # Repetición de E4: la ronda del run que repite (de ahí su Etapa 3).
    ronda_origen: str | None = None
    adjudicacion: str
    sha256_adjudicacion: str
    sha256_reporte: str
    sha256_e3: str
    verificado_por_segundo_agente: bool
    universo: UniversoGt
    # Rondas cuyo GT complementa (vacío: fuente base, adjudica todas sus alertas).
    complementa: list[str] = []

    @property
    def carpeta_e3(self) -> str:
        """Carpeta de su Etapa 3: la del run de origen en una repetición de E4."""
        if self.ronda_origen is None:
            return self.carpeta
        return carpeta_del_run(self.ronda_origen, self.run_id)


class ErrorExcelGt(_Estricto):
    id: str
    fila_excel: int
    pagina_pdf: int
    clasificacion_pdf: str
    campos: list[CampoDiferente]
    subclase: str
    contraparte_validada: bool
    no_mostrado_en_b2: list[str]
    cita_pdf: str
    cita_excel: str
    fuente: str


class GtInforme(_Estricto):
    version_gt: str
    informe: str
    sha256_informe_original: str
    sha256_excel: str
    fuentes: list[FuenteGt]
    items: list[ItemGt]
    errores_excel: list[ErrorExcelGt] = []

    @model_validator(mode="after")
    def _coherente(self) -> GtInforme:
        if self.version_gt != VERSION_GT:
            raise ValueError(f"version_gt {self.version_gt!r}: este código lee {VERSION_GT!r}")
        ids = [i.id for i in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("ids de ítems repetidos")
        sueltos = sorted({i.duplica_de for i in self.items} - set(ids) - {None}, key=str)
        if sueltos:
            raise ValueError(f"duplica_de apunta a ítems que no existen: {sueltos}")
        unicas = ([(f.ronda, f.run_id) for f in self.fuentes], [f.carpeta for f in self.fuentes],
                  [(f.ronda, f.modelo) for f in self.fuentes])
        if any(len(set(u)) != len(u) for u in unicas):
            raise ValueError("fuentes repetidas: una carpeta (run) y una ronda por modelo, una vez")
        for f in self.fuentes:
            esperada = carpeta_del_run(f.ronda, f.run_id, f.ronda_origen)
            if f.carpeta != esperada:
                raise ValueError(f"fuentes: {f.ronda}/{f.modelo} con la carpeta {f.carpeta!r}, "
                                 f"que no es la de su ronda, run y ronda de origen ({esperada!r})")
        de_otra_fuente = ({(o.ronda, o.modelo, o.run_id) for i in self.items for o in i.origenes}
                          - {(f.ronda, f.modelo, f.run_id) for f in self.fuentes})
        if de_otra_fuente:
            raise ValueError(f"orígenes de runs sin fuente: {sorted(de_otra_fuente)}")
        rondas = {f.ronda for f in self.fuentes}
        for f in self.fuentes:
            if f.ronda in f.complementa or not set(f.complementa) <= rondas:
                raise ValueError(f"{f.ronda}/{f.modelo}: complementa {f.complementa}, que no "
                                 f"son otras rondas del GT ({sorted(rondas)})")
            if f.ronda_origen is not None and f.ronda_origen not in f.complementa:
                raise ValueError(f"{f.ronda}/{f.modelo}: repetición de E4 de {f.ronda_origen}, "
                                 f"que no está en lo que complementa ({f.complementa})")
        if self.fuentes and all(f.complementa for f in self.fuentes):
            raise ValueError("sin fuente base: todas complementan otra ronda")
        return self

    def coincide_en_universo(self, modelo: str | None) -> bool:
        """¿Se adjudicaron todos los «coincide»? Sí si todas las fuentes de ese
        modelo los adjudicaron; con un modelo sin fuente, si todas las fuentes."""
        universos = ([f.universo for f in self.fuentes if f.modelo == modelo]
                     or [f.universo for f in self.fuentes])
        return all(u.coincide == "todos" for u in universos)


# ---------------------------------------------------------------- construcción


def texto_identico(r: MatchResult) -> bool:
    """D13: «coincide» con descripción, acción y calificación idénticas entre
    PDF y Excel (solo se colapsan los espacios)."""
    p, e = r.hallazgo_pdf, r.hallazgo_excel
    if r.estado != EstadoHallazgo.COINCIDE or p is None or e is None:
        return False

    def norma(valor: object) -> str | None:
        return None if valor is None else " ".join(str(valor).split())

    return all(norma(getattr(p, c)) == norma(getattr(e, c)) for c in CAMPOS_TEXTO)


def _sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


_MENCION = re.compile(r"preguntas?\s+(\d+\.\d+(?:\s*(?:,|y|e)\s*\d+\.\d+)*)", re.IGNORECASE)


def preguntas_de(sub: str, item: ItemAdjudicado) -> list[str]:
    """Preguntas abiertas de las que depende un ítem C (vacío si no es C): las
    que nombra su ``depende_de`` y las que cita su explicación con la numeración
    vieja; si no hay ninguna, las de ``PREGUNTAS_SIN_MENCION``."""
    if item.clase != "C":
        if item.depende_de:
            raise GtError(f"{sub} idx {item.idx}: depende_de solo en un criterio por definir "
                          f"(C), no en {item.subclase}")
        return []
    texto = f"{item.explicacion} {item.nota_verificacion}"
    menciones = {n for m in _MENCION.finditer(texto) for n in re.findall(r"\d+\.\d+", m[1])}
    desconocidas = sorted(menciones - set(PREGUNTAS_V3))
    if desconocidas:
        raise GtError(f"{sub} idx {item.idx}: pregunta {desconocidas} sin traducir en "
                      "PREGUNTAS_V3")
    preguntas = {p for n in menciones for p in PREGUNTAS_V3[n]} | set(item.depende_de)
    if not preguntas:
        preguntas = set(PREGUNTAS_SIN_MENCION.get((sub, item.subclase), ()))
    if not preguntas:
        raise GtError(f"{sub} idx {item.idx}: criterio por definir ({item.subclase}) sin "
                      "pregunta (PREGUNTAS_SIN_MENCION)")
    return sorted(preguntas, key=lambda p: int(p[1:]))


def causa_de(ronda: str, modelo: str, sub: str,
             item: ItemAdjudicado) -> tuple[EtapaCausa | None, list[CampoExtraccion]]:
    """Etapa que origina una falsa alarma (D) y qué campo de E3 falló."""
    clave = (ronda, modelo, sub, item.idx)
    if item.clase != "D":
        if clave in CAUSA_POR_ITEM:
            raise GtError(f"CAUSA_POR_ITEM: {sub} idx {item.idx} con {modelo} ({ronda}) no es D")
        return None, []
    causa = CAUSA_POR_ITEM.get(clave) or CAUSA_POR_SUBCLASE.get(item.subclase)
    if causa is None:
        raise GtError(f"{sub} idx {item.idx} con {modelo} ({ronda}): {item.subclase} sin causa "
                      "(CAUSA_POR_ITEM)")
    return causa[0], list(causa[1])


def _citas_pdf(modelo: str, item: ItemAdjudicado, r: MatchResult) -> list[CitaGt]:
    h = r.hallazgo_pdf
    assert h is not None
    lado = item.lado_pdf_propio
    if lado is not None and lado.cita.strip():
        try:
            calza = ClavePdf.de(h.pano, h.rele, lado.referencia, [lado.cita]).calza(h)
        except ValueError:
            calza = False
        if calza:
            return [CitaGt(texto=lado.cita, fuente="adjudicacion", modelo=modelo)]
    return [CitaGt(texto=h.descripcion, fuente="descripcion_e3", modelo=modelo)]


def _referencia(item: ItemAdjudicado, lado: Literal["pdf", "excel"]) -> ReferenciaGt | None:
    dato = item.pdf if lado == "pdf" else item.excel
    if dato is None or not dato.es_contraparte:
        return None
    return ReferenciaGt(referencia=dato.referencia, cita=dato.cita)


def _item_de(al: AdjudicacionAlineada, item: ItemAdjudicado, sub: str) -> ItemGt:
    modelo = al.adjudicacion.modelo
    r = al.resultados[item.idx]
    lado_excel = lado_pdf = None
    if r.hallazgo_excel is not None:
        propio = item.lado_excel_propio
        fila = r.hallazgo_excel.evidencia.fila_excel
        if fila is None:
            raise GtError(f"{al.adjudicacion.ruta.name} idx {item.idx}: Excel sin fila")
        lado_excel = LadoExcelGt(
            fila=fila,
            citas=[CitaGt(texto=propio.cita, fuente="adjudicacion", modelo=modelo)]
            if propio is not None and propio.cita.strip() else [])
    if r.hallazgo_pdf is not None:
        propio = item.lado_pdf_propio
        pagina = propio.referencia if propio is not None else r.hallazgo_pdf.evidencia.pagina_pdf
        if pagina is None:
            raise GtError(f"{al.adjudicacion.ruta.name} idx {item.idx}: PDF sin página")
        lado_pdf = LadoPdfGt(
            pagina=pagina,
            clasificaciones=[r.hallazgo_pdf.clasificacion],
            citas=_citas_pdf(modelo, item, r))
    etapa, campos_e3 = causa_de(al.adjudicacion.ronda, modelo, sub, item)
    return ItemGt(
        id=f"{modelo}#{item.idx}", pano=r.pano, rele=r.rele, estado=r.estado,
        campos=list(campos_que_difieren(r)) if r.estado == EstadoHallazgo.DIFIERE else [],
        lado_excel=lado_excel, lado_pdf=lado_pdf, clase=item.clase,
        subclase=item.subclase, nivel_validacion=item.nivel_validacion,
        depende_de=preguntas_de(sub, item), etapa_causa=etapa, campos_extraccion=campos_e3,
        origenes=[OrigenGt(
            modelo=modelo, ronda=al.adjudicacion.ronda, run_id=al.adjudicacion.run_id,
            idx=item.idx,
            tipo_match=r.tipo_match.value, subclase=item.subclase,
            nivel_validacion=item.nivel_validacion, duplica_idx=item.duplica_idx,
            contraparte_idx=item.contraparte_idx, contraparte_pdf=_referencia(item, "pdf"),
            contraparte_excel=_referencia(item, "excel"), explicacion=item.explicacion,
            nota_verificacion=item.nota_verificacion)],
    )


def _union(a: Sequence[_T], b: Sequence[_T]) -> list[_T]:
    return list(dict.fromkeys([*a, *b]))


def _origen(g: ItemGt) -> str:
    o = g.origenes[0]
    return f"{o.modelo} idx {o.idx} ({o.ronda}, run {o.run_id})"


def _fusionar(g: ItemGt, nuevo: ItemGt) -> ItemGt:
    """El mismo ítem adjudicado por otra fuente: misma clase y causa, o falla."""
    for campo in ("clase", "subclase", "etapa_causa", "campos_extraccion"):
        if getattr(g, campo) != getattr(nuevo, campo):
            raise ConflictoGtError(
                f"{g.pano}/{g.rele} ({g.estado.value}): {campo} {getattr(g, campo)!r} con "
                f"{_origen(g)} y {getattr(nuevo, campo)!r} con {_origen(nuevo)}")
    lado_excel = g.lado_excel
    if g.lado_excel is not None and nuevo.lado_excel is not None:
        lado_excel = g.lado_excel.model_copy(
            update={"citas": _union(g.lado_excel.citas, nuevo.lado_excel.citas)})
    lado_pdf = g.lado_pdf
    if g.lado_pdf is not None and nuevo.lado_pdf is not None:
        lado_pdf = g.lado_pdf.model_copy(update={
            "clasificaciones": _union(g.lado_pdf.clasificaciones, nuevo.lado_pdf.clasificaciones),
            "citas": _union(g.lado_pdf.citas, nuevo.lado_pdf.citas)})
    verificado = NivelValidacion.VERIFICADO in (g.nivel_validacion, nuevo.nivel_validacion)
    return g.model_copy(update={
        "lado_excel": lado_excel, "lado_pdf": lado_pdf,
        "nivel_validacion": (NivelValidacion.VERIFICADO if verificado
                             else NivelValidacion.SOLO_ADJUDICADOR),
        "depende_de": sorted(_union(g.depende_de, nuevo.depende_de), key=lambda p: int(p[1:])),
        "origenes": [*g.origenes, *nuevo.origenes],
    })


def _universo(al: AdjudicacionAlineada, antes: set[int],
              complementa: Sequence[str]) -> UniversoGt:
    """Qué cubre una fuente: lo que adjudica su archivo más, en una ronda
    posterior, lo que ya adjudicaba el GT de las anteriores (``antes``). Toda
    alerta debe quedar cubierta."""
    res = al.resultados
    no_transversales = {i for i, r in enumerate(res) if r.estado != EstadoHallazgo.TRANSVERSAL}
    propios = {it.idx for it in al.adjudicacion.items}
    adjudicados = propios | antes
    alertas = {i for i in no_transversales if res[i].estado != EstadoHallazgo.COINCIDE}
    nombre = al.adjudicacion.ruta.name
    if propios - no_transversales:
        raise GtError(f"{nombre}: adjudica transversales {sorted(propios - no_transversales)}")
    if alertas - adjudicados:
        de_antes = f" (ni el GT de {', '.join(complementa)})" if complementa else ""
        raise GtError(f"{nombre}: alertas sin adjudicar {sorted(alertas - adjudicados)}"
                      f"{de_antes}")
    coincide = [r for r in res if r.estado == EstadoHallazgo.COINCIDE]
    todos = adjudicados == no_transversales
    muestra = len(adjudicados) - len(alertas)
    regla = ("todos los resultados no transversales" if todos else
             f"todas las alertas y una muestra de {muestra} de {len(coincide)} «coincide»")
    if complementa:
        regla += f"; {len(antes)} ya los adjudicaba el GT de {', '.join(complementa)}"
    return UniversoGt(
        regla=regla, coincide="todos" if todos else "muestra", resultados=len(res),
        transversales=len(res) - len(no_transversales), items=len(propios),
        barrido=BarridoGt(coincide=len(coincide),
                          texto_identico=sum(texto_identico(r) for r in coincide)),
        adjudicados_antes=len(antes),
    )


def hashes_del_run(run: Path) -> tuple[str, str] | None:
    """sha256 del informe original y del Excel que guardó el run (None si falta
    alguno): a eso se ata un GT."""
    rutas = (run / "input_informe_original.hash", run / "input_excel.hash")
    if not all(r.is_file() for r in rutas):
        return None
    informe, excel = (r.read_text(encoding="utf-8").strip() for r in rutas)
    return informe, excel


def _errores_excel(sub: str,
                   por_fuente: dict[tuple[str, str], AdjudicacionAlineada]) -> list[ErrorExcelGt]:
    errores = []
    for n, e in enumerate(d for d in ERRORES_EXCEL_B2 if d.subestacion == sub):
        al = por_fuente.get((e.fuente_ronda, e.fuente_modelo))
        if al is None:
            raise GtError(f"{sub}: el error de la fila {e.fila_excel} sale de la adjudicación "
                          f"de {e.fuente_modelo} en {e.fuente_ronda}, que no está entre las "
                          "fuentes")
        if e.fuente_idx is None:
            dato = al.adjudicacion.cabecera.get("error_excel_no_detectado") or {}
            pdf, excel = dato.get("cita_pdf") or {}, dato.get("cita_excel") or {}
            referencias: tuple[object, ...] = (pdf.get("pagina"), excel.get("fila"),
                                               dato.get("fila_excel"))
            citas = (str(pdf.get("texto") or ""), str(excel.get("texto") or ""))
            fuente = f"{al.adjudicacion.ruta.name}: error_excel_no_detectado"
            esperado: tuple[object, ...] = (e.pagina_pdf, e.fila_excel, e.fila_excel)
        else:
            (item,) = [i for i in al.adjudicacion.items if i.idx == e.fuente_idx]
            referencias = (item.pdf.referencia if item.pdf else None,
                           item.excel.referencia if item.excel else None)
            citas = (item.pdf.cita if item.pdf else "", item.excel.cita if item.excel else "")
            fuente = f"{al.adjudicacion.ruta.name}: idx {e.fuente_idx}"
            esperado = (e.pagina_pdf, e.fila_excel)
        if referencias != esperado or not all(citas):
            raise GtError(f"{fuente}: página/fila {referencias} ≠ {esperado} o sin citas")
        errores.append(ErrorExcelGt(
            id=f"e{n + 1}", fila_excel=e.fila_excel, pagina_pdf=e.pagina_pdf,
            clasificacion_pdf=e.clasificacion_pdf, campos=[CampoDiferente(c) for c in e.campos],
            subclase=e.subclase, contraparte_validada=e.contraparte_validada,
            no_mostrado_en_b2=list(e.no_mostrado_en_b2), cita_pdf=citas[0], cita_excel=citas[1],
            fuente=fuente))
    return errores


_RONDA = re.compile(r"[Bb](\d+)\w*")


def numero_ronda(etiqueta: str) -> int:
    """'B2' → 2, 'B3s' → 3: las rondas B del GT deben quedar en el orden de ese número."""
    m = _RONDA.fullmatch(etiqueta)
    if m is None:
        raise GtError(f"ronda {etiqueta!r}: no se puede ordenar respecto de las otras; la "
                      "etiqueta debe ser B<número> (p. ej. B2, B3s) o la de una repetición "
                      "de E4 que declara repeticion_e4")
    return int(m[1])


_FECHA_RUN = re.compile(r"(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})_")


def fecha_de_la_fuente(mediciones: Path, adj: Adjudicacion) -> datetime:
    """Cuándo se corrió el run adjudicado. El de una ronda, por su run_id
    (``<aaaa-mm-dd_hh-mm-ss>_<modelo>``, invariante 20). Una repetición de E4
    lleva el run_id de su origen: va la ``fecha_inicio`` de su metadata.json, que
    además debe ser la de una repetición de ese run que terminó."""
    if adj.ronda_origen is None:
        m = _FECHA_RUN.match(adj.run_id)
        if m is None:
            raise GtError(f"{adj.ruta.name}: run_id {adj.run_id!r} sin la fecha de la corrida "
                          "(<aaaa-mm-dd_hh-mm-ss>_<modelo>)")
        return datetime.strptime(m[1], "%Y-%m-%d_%H-%M-%S")
    ruta = mediciones / adj.carpeta / "metadata.json"
    if not ruta.is_file():
        raise GtError(f"{adj.ruta.name}: {adj.carpeta} sin metadata.json (la repetición de E4 "
                      "no terminó)")
    meta = json.loads(ruta.read_text(encoding="utf-8"))
    if (meta.get("modo"), meta.get("run_origen")) != (MODO_REPLAY_E4, adj.run_id):
        raise GtError(f"{adj.ruta.name}: {adj.carpeta}/metadata.json con modo "
                      f"{meta.get('modo')!r} y run_origen {meta.get('run_origen')!r}; se espera "
                      f"la repetición de E4 ({MODO_REPLAY_E4!r}) de {adj.run_id}")
    try:
        return datetime.fromisoformat(str(meta["fecha_inicio"]))
    except (KeyError, ValueError) as e:
        raise GtError(f"{adj.ruta.name}: {adj.carpeta}/metadata.json sin fecha_inicio "
                      f"válida ({meta.get('fecha_inicio')!r})") from e


def _orden_modelo(al: AdjudicacionAlineada) -> tuple[int, str]:
    modelo = al.adjudicacion.modelo
    return (ORDEN_MODELOS.index(modelo) if modelo in ORDEN_MODELOS else len(ORDEN_MODELOS),
            modelo)


def rondas_en_orden(mediciones: Path, alineadas: Sequence[AdjudicacionAlineada]
                    ) -> list[list[AdjudicacionAlineada]]:
    """Las fuentes agrupadas por ronda, en el orden en que se corrieron (la
    primera corrida de cada ronda: ``fecha_de_la_fuente``) y, dentro de una
    ronda, Sonnet antes que Opus. Falla si las rondas B no quedan en el orden de
    su número o si una repetición de E4 no va después de su ronda de origen."""
    por_ronda: dict[str, list[AdjudicacionAlineada]] = defaultdict(list)
    fechas: dict[str, list[datetime]] = defaultdict(list)
    for a in alineadas:
        adj = a.adjudicacion
        numero_ronda(adj.ronda if adj.ronda_origen is None else adj.ronda_origen)
        por_ronda[adj.ronda].append(a)
        fechas[adj.ronda].append(fecha_de_la_fuente(mediciones, adj))
    for ronda, grupo in por_ronda.items():
        if len({a.adjudicacion.ronda_origen is None for a in grupo}) > 1:
            raise GtError(f"ronda {ronda}: mezcla fuentes de una ronda y repeticiones de E4")
    orden = sorted(por_ronda, key=lambda r: (min(fechas[r]), r))
    numeros = [(numero_ronda(r), r) for r in orden if por_ronda[r][0].adjudicacion.ronda_origen
               is None]
    if [n for n, _ in numeros] != sorted(n for n, _ in numeros):
        raise GtError(f"las rondas se corrieron en otro orden que su número: "
                      f"{[r for _, r in numeros]}")
    for k, ronda in enumerate(orden):
        for a in por_ronda[ronda]:
            origen = a.adjudicacion.ronda_origen
            if origen is None:
                continue
            if origen not in por_ronda:
                raise GtError(f"{a.adjudicacion.ruta.name}: su ronda de origen {origen} no está "
                              f"entre las fuentes del GT ({orden}): no hay qué complementar")
            if origen not in orden[:k]:
                raise GtError(f"{a.adjudicacion.ruta.name}: la repetición de E4 se corrió antes "
                              f"que su ronda de origen {origen} ({orden})")
    return [sorted(por_ronda[r], key=_orden_modelo) for r in orden]


def _fuente(mediciones: Path, al: AdjudicacionAlineada, run: Path, universo: UniversoGt,
            complementa: list[str]) -> FuenteGt:
    adj = al.adjudicacion
    return FuenteGt(
        modelo=adj.modelo, ronda=adj.ronda, run_id=adj.run_id, carpeta=adj.carpeta,
        ronda_origen=adj.ronda_origen, adjudicacion=adj.ruta.name,
        sha256_adjudicacion=_sha256(adj.ruta),
        sha256_reporte=_sha256(run / "reporte_final.json"),
        sha256_e3=_sha256(mediciones / adj.carpeta_e3 / "etapa3_pdf_hallazgos.json"),
        verificado_por_segundo_agente=bool(adj.cabecera.get("verificado_por_segundo_agente")),
        universo=universo, complementa=complementa)


def _adjudicados_por(gt: GtInforme, run: Path) -> set[int]:
    """Resultados del run que el GT ya adjudica (la regla de evaluar_comparador)."""
    from comparador import evaluar_comparador

    return {r.idx for r in evaluar_comparador.evaluar_run(run, gt).adjudicados}


def _ensamblar(informe: str, hashes: tuple[str, str], fuentes: list[FuenteGt],
               items: list[ItemGt], posicion: dict[tuple[str, str, int], int],
               errores: list[ErrorExcelGt]) -> GtInforme:
    """El GT con los ítems numerados en orden (i001…) y cada copia atada a su original."""
    ids = [f"i{k + 1:03d}" for k in range(len(items))]
    finales = []
    for k, g in enumerate(items):
        # Una copia lo es aunque el original no esté en el GT (muestra de Beta).
        copias = [(o.ronda, o.run_id, o.duplica_idx) for o in g.origenes
                  if o.duplica_idx is not None]
        originales = {posicion[c] for c in copias if c in posicion}
        if len(originales) > 1:
            raise ConflictoGtError(f"{informe}: {ids[k]} duplica ítems distintos según la fuente")
        finales.append(g.model_copy(update={
            "id": ids[k], "es_duplicado": bool(copias),
            "duplica_de": ids[originales.pop()] if originales else None}))
    gt = GtInforme(version_gt=VERSION_GT, informe=informe, sha256_informe_original=hashes[0],
                   sha256_excel=hashes[1], fuentes=fuentes, items=finales, errores_excel=errores)
    # Ida y vuelta por JSON: revalida todo (model_copy no valida).
    return GtInforme.model_validate(gt.model_dump(mode="json"))


def construir_gt(mediciones: Path, rutas: Sequence[Path], *,
                 con_errores_excel: bool = True) -> GtInforme:
    """GT de un informe desde sus adjudicaciones (una por ronda y modelo), ronda
    por ronda en el orden en que se corrieron: la primera da las fuentes base y
    cada ronda posterior complementa el GT de las anteriores (ver el docstring
    del módulo). Sin ``con_errores_excel`` (p. ej. el GT de una sola fuente, para
    medir cuánto de él se encuentra en el run del otro modelo) no lleva
    errores_excel."""
    alineadas = [cargar_alineada(mediciones, r) for r in rutas]
    informes = {unicodedata.normalize("NFC", a.adjudicacion.informe) for a in alineadas}
    claves = [(a.adjudicacion.ronda, a.adjudicacion.modelo) for a in alineadas]
    runs = {a.adjudicacion.carpeta: directorio_run(mediciones, a.adjudicacion)
            for a in alineadas}
    if len(informes) != 1 or len(set(claves)) != len(claves) or len(runs) != len(claves):
        raise GtError(f"se espera un informe y un archivo (y un run) por ronda y modelo: "
                      f"{informes}, {claves}")
    (informe,) = informes
    sub = nombre_corto(informe)
    hashes = set()
    for run in runs.values():
        par = hashes_del_run(run)
        if par is None:
            raise GtError(f"{run.name}: sin input_informe_original.hash o input_excel.hash")
        hashes.add(par)
    if len(hashes) != 1:
        raise GtError(f"{informe}: los runs no son del mismo informe y Excel: {sorted(hashes)}")
    (hashes_informe,) = hashes

    fuentes: list[FuenteGt] = []
    items: list[ItemGt] = []
    posicion: dict[tuple[str, str, int], int] = {}  # (ronda, run_id, idx) → ítem
    previo: GtInforme | None = None                 # el GT de las rondas anteriores
    for grupo in rondas_en_orden(mediciones, alineadas):
        complementa = list(dict.fromkeys(f.ronda for f in fuentes))
        for al in grupo:
            run = runs[al.adjudicacion.carpeta]
            fuente = (al.adjudicacion.ronda, al.adjudicacion.run_id)
            antes = _adjudicados_por(previo, run) if previo is not None else set()
            fuentes.append(_fuente(mediciones, al, run, _universo(al, antes, complementa),
                                   complementa))
            for it in al.adjudicacion.items:
                nuevo = _item_de(al, it, sub)
                # La clave encuentra su resultado, y solo ese, en su propio reporte.
                busqueda = buscar(nuevo.claves(), al.resultados)
                if busqueda.indices != (it.idx,):
                    raise GtError(f"{al.adjudicacion.ruta.name} idx {it.idx}: su clave "
                                  f"encuentra {busqueda.indices} en su propio reporte")
                r = al.resultados[it.idx]
                iguales = [k for k, g in enumerate(items) if g.adjudica(r)]
                if len(iguales) > 1:
                    raise ConflictoGtError(f"{al.adjudicacion.ruta.name} idx {it.idx}: calza "
                                           f"con {len(iguales)} ítems de otras fuentes")
                if iguales and fuente in {(o.ronda, o.run_id)
                                          for o in items[iguales[0]].origenes}:
                    raise ConflictoGtError(f"{al.adjudicacion.ruta.name} idx {it.idx}: calza "
                                           "con otro ítem de la misma fuente")
                if iguales:
                    items[iguales[0]] = _fusionar(items[iguales[0]], nuevo)
                    posicion[(*fuente, it.idx)] = iguales[0]
                else:
                    posicion[(*fuente, it.idx)] = len(items)
                    items.append(nuevo)
        previo = _ensamblar(informe, hashes_informe, fuentes, items, posicion, [])

    por_fuente = {(a.adjudicacion.ronda, a.adjudicacion.modelo): a for a in alineadas}
    return _ensamblar(informe, hashes_informe, fuentes, items, posicion,
                      _errores_excel(sub, por_fuente) if con_errores_excel else [])


def adjudicaciones_por_informe(mediciones: Path) -> dict[str, list[Path]]:
    """Archivos de mediciones/adjudicacion agrupados por carpeta del informe (NFC)."""
    grupos: dict[str, list[Path]] = defaultdict(list)
    for ruta in sorted((mediciones / "adjudicacion").glob("*.json")):
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        grupos[unicodedata.normalize("NFC", str(datos.get("informe", ruta.stem)))].append(ruta)
    return dict(grupos)


def nombre_archivo(informe: str) -> str:
    return unicodedata.normalize("NFC", informe) + ".json"


def cargar_gt(ruta: Path) -> GtInforme:
    return GtInforme.model_validate_json(ruta.read_text(encoding="utf-8"))


def serializar(gt: GtInforme) -> str:
    return gt.model_dump_json(indent=1) + "\n"


# ---------------------------------------------------------------- validación


def validar_gt(gt: GtInforme, mediciones: Path) -> list[str]:
    """Problemas del GT contra sus fuentes (vacío: válido). Cada fuente debe
    seguir intacta (sha256) y su propio run (el de su carpeta) debe evaluarse
    sin nada «sin adjudicar» dentro del universo: cada resultado adjudicado va
    al ítem que tiene ese origen y con la clase de su adjudicación (en una ronda
    posterior, el resto lo adjudican los ítems de antes)."""
    from comparador import evaluar_comparador

    problemas: list[str] = []
    for f in gt.fuentes:
        ruta_adj = mediciones / "adjudicacion" / f.adjudicacion
        run = mediciones / f.carpeta
        for ruta, esperado in ((ruta_adj, f.sha256_adjudicacion),
                               (run / "reporte_final.json", f.sha256_reporte),
                               (mediciones / f.carpeta_e3 / "etapa3_pdf_hallazgos.json",
                                f.sha256_e3)):
            if not ruta.is_file() or _sha256(ruta) != esperado:
                problemas.append(f"{f.modelo}: {ruta} no existe o cambió")
        if problemas:
            continue
        ev = evaluar_comparador.evaluar_run(run, gt)
        adjudicacion = {it.idx: it
                        for it in cargar_alineada(mediciones, ruta_adj).adjudicacion.items}
        de_origen = {(o.ronda, o.run_id, o.idx): g for g in gt.items for o in g.origenes}
        # En una ronda posterior, lo que su archivo no adjudica lo adjudica el GT
        # de las anteriores.
        sin_origen = {"transversal", "ok_texto_identico", "fuera_de_universo"} | (
            {"adjudicado"} if f.complementa else set())
        for r in ev.resultados:
            esperado_item = de_origen.get((f.ronda, f.run_id, r.idx))
            if esperado_item is None:
                if r.veredicto not in sin_origen:
                    problemas.append(f"{f.modelo} resultado {r.idx}: {r.veredicto} "
                                     f"({r.motivo}) fuera de la adjudicación")
                continue
            if r.item_gt != esperado_item.id or r.clase != adjudicacion[r.idx].clase:
                problemas.append(f"{f.modelo} resultado {r.idx}: {r.veredicto} ({r.motivo}), "
                                 f"ítem {r.item_gt} y no {esperado_item.id}")
    return problemas


# ---------------------------------------------------------------- CLI


def _construir(mediciones: Path, salida: Path, sobrescribir: bool) -> int:
    exigir_ignorada_por_git(salida, "--salida", carpeta=True)   # el GT lleva citas
    codigo = 0
    for informe, rutas in sorted(adjudicaciones_por_informe(mediciones).items()):
        gt = construir_gt(mediciones, rutas)
        problemas = validar_gt(gt, mediciones)
        if problemas:
            print(f"{informe}: NO VÁLIDO\n  " + "\n  ".join(problemas))
            codigo = 1
            continue
        destino = salida / nombre_archivo(informe)
        texto = serializar(gt)
        if destino.exists() and destino.read_text(encoding="utf-8") != texto and not sobrescribir:
            print(f"{destino}: ya existe y es distinto (usar --sobrescribir)")
            codigo = 1
            continue
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto, encoding="utf-8")
        fusionados = sum(len(i.origenes) > 1 for i in gt.items)
        print(f"{destino}: {len(gt.items)} ítems de {len(gt.fuentes)} fuentes ({fusionados} "
              "con más de una), "
              f"{len(gt.errores_excel)} errores del Excel")
    return codigo


def _validar(mediciones: Path, carpeta: Path) -> int:
    rutas = sorted(carpeta.glob("*.json"))
    if not rutas:
        print(f"{carpeta}: sin GT")
        return 1
    codigo = 0
    for ruta in rutas:
        try:
            problemas = validar_gt(cargar_gt(ruta), mediciones)
        except ValueError as e:
            problemas = [str(e)]
        print(f"{ruta.name}: {'OK' if not problemas else 'NO VÁLIDO'}")
        for p in problemas:
            print(f"  {p}")
        codigo |= bool(problemas)
    return codigo


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("accion", choices=("construir", "validar"))
    p.add_argument("--mediciones", type=Path, default=RAIZ / "mediciones")
    p.add_argument("--salida", "--gt", dest="carpeta", type=Path, default=None,
                   help="carpeta de los GT (por defecto <mediciones>/gt/comparador)")
    p.add_argument("--sobrescribir", action="store_true")
    a = p.parse_args()
    carpeta = a.carpeta or a.mediciones / "gt" / "comparador"
    if a.accion == "construir":
        sys.exit(_construir(a.mediciones, carpeta, a.sobrescribir))
    sys.exit(_validar(a.mediciones, carpeta))


if __name__ == "__main__":
    main()
