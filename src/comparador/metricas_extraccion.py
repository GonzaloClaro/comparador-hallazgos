"""Métrica de la extracción (Etapa 3) por campo, sin API (M15).

Las falsas alarmas del comparador mezclan errores de la Etapa 3 y de la Etapa 4.
Esta métrica mide solo la extracción: cada campo de cada hallazgo de E3 sale
``correcto``, ``error`` (de la Etapa 3), ``error_e1`` (lo explica la Etapa 1) o
``sin_referencia`` (no hay con qué compararlo: nunca cuenta como correcto).
Dos referencias:

- ``<ronda>_adjudicado`` (hoy ``b2_adjudicado``): los runs que son fuente base
  del GT del comparador (``comparador.gt_comparador``). Cada hallazgo de E3
  aparece una vez como lado PDF del reporte (``adjudicacion.mapa_e3``); su
  resultado se evalúa contra el GT (``evaluar_comparador``) y la clase dice qué
  falló.
- ``control_copia``: Beta y Eta, donde el Excel copia el PDF (lo
  comprobaron los verificadores de la adjudicación de B2): E3 contra E2, sin la
  Etapa 4, en cada ronda que guardó las dos etapas. Ahí el Excel es una
  transcripción completa: también ve lo que E3 omitió.
- ``contra_gt``: los runs de una ronda posterior a la de las fuentes base del
  GT (B3 frente a B2, por el número de la etiqueta) con el mismo informe y Excel
  (sha256, ``evaluar_comparador.gt_aplicable``), también si su adjudicación
  complementa el GT (es fuente de una ronda posterior: sus ítems se comparan con
  su propio reporte). Igual que con la adjudicación, pero el reporte no es el
  que se adjudicó: un hallazgo cuyo resultado calza
  con un ítem del GT por clave estable recibe veredicto por campo; uno que no
  calza queda sin referencia en todos sus campos (columna
  ``hallazgos_sin_referencia`` de ``extraccion_por_tupla.csv``). La clave dice
  qué hallazgo es, no qué extrajo E3: el veredicto de la adjudicación sobre la
  descripción, la acción, la calificación o la clasificación (el error que
  atribuye a E1/E3, o el «correcto» de un A o de una D6 de la Etapa 4 en un
  campo que difiere) vale solo si E3 extrajo en ese campo lo mismo que en el
  run fuente (``normalizar_texto``); si no, sin referencia. Por eso hace falta
  el reporte de cada fuente del GT, tal como se adjudicó (sha256), en
  ``<mediciones>/<ronda>/runs/<run_id>``. Una fila del Excel «extra» sin
  adjudicar puede ser una omisión que el GT no conoce: cuenta sin referencia
  en ``omision`` y aparte en ``filas_excel_sin_referencia``. Solo ve las
  omisiones y los errores que el GT ya conoce.

Campos: ``tupla`` (paño y relé), ``descripcion``, ``accion_correctiva``,
``calificacion``, ``clasificacion``, ``polaridad`` (solo con la adjudicación),
``omision`` (hallazgos reales que E3 extrajo, y los que le faltaron) y
``de_mas`` (hallazgos que no existen).

**Con la adjudicación.** Un hallazgo cuyo resultado no está adjudicado (fuera de
la muestra de «coincide» de Beta y Eta, o sin adjudicar) no tiene
referencia. Uno adjudicado:

- Error: lo que el GT atribuye a la extracción (falsa alarma D con
  ``etapa_causa`` e1 o e3 y el campo en ``campos_extraccion``). Un hallazgo de
  más no tiene referencia en sus otros campos.
- ``tupla``, ``omision`` y ``de_mas``: correctos en lo demás, también en A, B y
  C (E3 siguió al PDF y a la invariante 8; lo pendiente en una C es el criterio
  del Excel).
- Texto y calificación: la referencia es la fila del Excel de su par, si es su
  contraparte (no en A1/A2, cuya contraparte no está en el Excel; ni en D5, el
  juez emparejó otra fila; ni en una falta). Correcto si el campo no difiere, o
  si difiere y la adjudicación dice que el Excel se equivoca (A) o que es lo
  mismo en otras palabras (D6 de la Etapa 4). Si difiere en una C u otra D, sin
  referencia; también si el Excel no trae el campo (Epsilon: calificación).
- ``clasificacion``: en ese par, E3 contra el Excel con la clave de unicidad de
  la Etapa 4 (alias incluidos); distinta = error de E3 (no está adjudicada). Si
  la del Excel no es de la lista oficial de la SEC, sin referencia.
- ``polaridad``: en ese par, el «cumple»/«no cumple» de la descripción y la
  acción de cada lado (``etapa4_matching._polaridad``). Igual = correcto;
  opuesta = el veredicto de ese campo (un A5 deja correcta a E3).

**Control de copia.** E3 y E2 se alinean sin la Etapa 4 y comparando con
``texto_copia`` (solo comillas, guiones y espacios tipográficos: una comparación
difusa escondería una negación o un número): (1) en la misma tupla, por
descripción (y acción, para desempatar iguales); (2) en otra tupla, por
descripción: error de tupla; (3) lo que queda en una tupla se empareja en
orden: error de descripción y los demás campos sin referencia (el par solo se
presume); (4) sin pareja: hallazgo de más o fila omitida. Las filas
transversales del Excel según la regla de hoy (invariante 19b: los patrones del
catálogo y el relé sin alfanuméricos, también en las rondas anteriores a ellos)
no se le piden a E3.

**Errores de la Etapa 1.** E3 extrae por sección del mapa de la Etapa 1
(``etapa1_panos.json``). Un error de tupla o una omisión es de la Etapa 1 si la
tupla correcta (la de su fila del Excel, si se conoce) no es válida en ese mapa
(``etapa3_extraer_hallazgos._problemas_pano_rele``) o si la página del hallazgo
cae fuera del rango de todas las secciones de su paño. Sin tupla correcta
conocida, queda de la Etapa 3. Una falsa alarma con ``etapa_causa`` e1 (D4) es
de la Etapa 1.

**Limitaciones.** Con la adjudicación el recall sale inflado: no fue exhaustiva y
solo ve las omisiones que el Excel sí trae (el control de copia sí las ve, en dos
informes). Con 7 informes la potencia es baja. La clasificación se mide contra
el Excel, solo donde este usa la lista de la SEC.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, NamedTuple

from comparador import evaluar_comparador
from comparador.adjudicacion import mapa_e3, normalizar_texto
from comparador.catalogo import cargar_hints_empresa
from comparador.etapa2_normalizar_excel import _es_transversal, _normaliza
from comparador.etapa3_extraer_hallazgos import (
    _componentes,
    _normalizar_clave,
    _problemas_pano_rele,
    _Universo,
    _universo_etapa1,
)
from comparador.etapa4_matching import (
    _CLASIFICACIONES_SEC,
    _clave_clasificacion,
    _normalizar_clasificacion,
    _polaridad,
    clave_tupla,
)
from comparador.evaluar_comparador import GtAplicable, ResultadoEvaluado, evaluar, gt_aplicable
from comparador.gt_comparador import FuenteGt, GtInforme, ItemGt, hashes_del_run
from comparador.persistence import cargar_json
from comparador.schemas import (
    EmpresaAuditora,
    EstadoHallazgo,
    Hallazgo,
    MatchResult,
    PanoDescubierto,
    ReporteInforme,
)

FUENTE_COPIA = "control_copia"
FUENTE_CONTRA_GT = "contra_gt"
# Informes cuyo Excel copia el PDF, comprobado por los dos verificadores de la
# adjudicación de B2 (Beta: las filas, en orden, son las Tablas Resumen 1-23;
# Eta: 0 diferencias en 120 celdas), con su auditora (filas transversales).
INFORMES_COPIA = {"Beta": EmpresaAuditora.ENSAUT, "Eta": EmpresaAuditora.ENSAUT}
CAMPOS = ("tupla", "descripcion", "accion_correctiva", "calificacion", "clasificacion",
          "polaridad", "omision", "de_mas")
CAMPOS_COPIA = tuple(c for c in CAMPOS if c != "polaridad")
COLUMNAS_POR_CAMPO = ["fuente", "ronda", "modelo", "informe", "campo", "hallazgos_evaluados",
                      "correctos", "errores", "errores_e1", "sin_referencia"]
COLUMNAS_POR_TUPLA = ["fuente", "ronda", "modelo", "informe", "tuplas", "tuplas_con_omision",
                      "tuplas_con_de_mas", "hallazgos_e3", "omisiones", "de_mas",
                      "hallazgos_sin_referencia", "filas_excel_sin_referencia"]
E3_JSON, E2_JSON = "etapa3_pdf_hallazgos.json", "etapa2_excel_normalizado.json"

Tupla = tuple[str, str]


class Veredicto(StrEnum):
    CORRECTO = "correcto"
    ERROR = "error"                 # de la Etapa 3
    ERROR_E1 = "error_e1"           # lo explica el mapa de la Etapa 1
    SIN_REFERENCIA = "sin_referencia"


C, E, E1, S = Veredicto.CORRECTO, Veredicto.ERROR, Veredicto.ERROR_E1, Veredicto.SIN_REFERENCIA


# ---------------------------------------------------------------- Etapa 1


@dataclass(frozen=True)
class MapaE1:
    """Paños, relés y rangos de páginas que la Etapa 1 le dio a la Etapa 3."""

    panos: tuple[PanoDescubierto, ...]
    universo: _Universo

    @classmethod
    def de(cls, panos: Sequence[PanoDescubierto]) -> MapaE1:
        return cls(tuple(panos), _universo_etapa1(list(panos)))

    @classmethod
    def del_run(cls, run_dir: Path) -> MapaE1:
        return cls.de([PanoDescubierto.model_validate(p)
                       for p in cargar_json(run_dir / "etapa1_panos.json")])

    def explica(self, pano: str, rele: str, pagina: int | None = None) -> bool:
        """¿La Etapa 1 explica que E3 no pusiera un hallazgo en la tupla
        correcta (pano, rele)? Sí si la tupla no es válida en su mapa, o si la
        página del hallazgo cae fuera de todas las secciones de ese paño."""
        if _problemas_pano_rele(pano, rele, self.universo):
            return True
        if pagina is None:
            return False
        clave = _normalizar_clave(pano)
        secciones = [s for s in self.panos if clave in _componentes(s.nombre) or any(
            clave in _componentes(sub) for r in s.reles for sub in r.sub_panos)]
        return not any(s.pagina_inicio <= pagina <= s.pagina_fin for s in secciones)


# ---------------------------------------------------------------- medida


@dataclass(frozen=True)
class HallazgoMedido:
    indice_e3: int
    tupla: Tupla
    referencia: str                 # subclase del GT, veredicto sin ítem o alineación de copia
    veredictos: Mapping[str, Veredicto]


@dataclass(frozen=True)
class OmisionMedida:
    """Una fila del Excel cuyo hallazgo E3 no extrajo."""

    tupla: Tupla
    referencia: str
    veredicto: Veredicto            # ERROR o ERROR_E1


@dataclass(frozen=True)
class Medida:
    campos: tuple[str, ...]
    hallazgos: list[HallazgoMedido]
    omisiones: list[OmisionMedida]
    tuplas: frozenset[Tupla]
    # Filas del Excel «extra» sin adjudicar: no se sabe si E3 omitió su hallazgo.
    filas_excel_sin_referencia: int = 0

    def conteo(self, campo: str) -> dict[str, int]:
        """Evaluados = correctos + errores (de E3 y de E1). En ``omision`` los
        errores son las filas omitidas, que no son hallazgos de E3, y las filas
        «extra» sin adjudicar suman a lo sin referencia."""
        if campo not in self.campos:
            raise ValueError(f"campo {campo!r} no medido (campos: {self.campos})")
        vistos = Counter(h.veredictos[campo] for h in self.hallazgos)
        if campo == "omision":
            vistos.update(o.veredicto for o in self.omisiones)
            vistos[S] += self.filas_excel_sin_referencia
        return {"hallazgos_evaluados": vistos[C] + vistos[E] + vistos[E1],
                "correctos": vistos[C], "errores": vistos[E], "errores_e1": vistos[E1],
                "sin_referencia": vistos[S]}

    def por_tupla(self) -> dict[str, int]:
        """``hallazgos_sin_referencia``: hallazgos de E3 sin referencia en ningún
        campo (su resultado no calza con el GT o quedó fuera de su universo);
        ``filas_excel_sin_referencia``: filas «extra» sin adjudicar."""
        de_mas = [h for h in self.hallazgos if h.veredictos["de_mas"] in (E, E1)]
        return {"tuplas": len(self.tuplas),
                "tuplas_con_omision": len({o.tupla for o in self.omisiones}),
                "tuplas_con_de_mas": len({h.tupla for h in de_mas}),
                "hallazgos_e3": len(self.hallazgos), "omisiones": len(self.omisiones),
                "de_mas": len(de_mas),
                "hallazgos_sin_referencia": sum(
                    all(v == S for v in h.veredictos.values()) for h in self.hallazgos),
                "filas_excel_sin_referencia": self.filas_excel_sin_referencia}


def _tupla(h: Hallazgo) -> Tupla:
    return clave_tupla(h.pano, h.rele)


_SEC = frozenset(_normalizar_clasificacion(c) for c in _CLASIFICACIONES_SEC)


def _clasificacion(h: Hallazgo, x: Hallazgo) -> Veredicto:
    """E3 contra el Excel con la clave de unicidad de la Etapa 4 (alias
    incluidos). Sin referencia si la del Excel no es de la lista oficial de la
    SEC (Epsilon usa otra lista; Gamma, «Ver. Tiempo Máx. Actuación»)."""
    referencia = _clave_clasificacion(x)
    if referencia not in _SEC:
        return S
    return C if _clave_clasificacion(h) == referencia else E


# ---------------------------------------------------------------- con la adjudicación

# Su par no es su contraparte: A1/A2 (no está en el Excel), D5 (el juez emparejó otra fila).
_PAR_AJENO = frozenset({"A1", "A2", "D5"})
_CAMPOS_PAR = ("descripcion", "accion_correctiva", "calificacion")


@dataclass(frozen=True)
class _Referencia:
    """Lo que la adjudicación dice del resultado de un hallazgo."""

    nombre: str                     # subclase, o el veredicto de la evaluación sin ítem
    clase: str | None               # None: sin referencia
    etapa_causa: str | None = None
    campos_extraccion: frozenset[str] = frozenset()
    paginas_contraparte: tuple[int, ...] = ()   # D1: página del hallazgo omitido
    fila_contraparte: int | None = None         # fila del Excel que le correspondía
    # Contra el GT (no en el run fuente): los hallazgos del PDF que se
    # adjudicaron en los runs fuente de su ítem. None: el run es la fuente.
    hallazgos_fuente: tuple[Hallazgo, ...] | None = None

    def atribuye(self, campo: str) -> bool:
        """¿El GT atribuye a la extracción (E1 o E3) un error en ese campo?"""
        return (self.clase == "D" and campo in self.campos_extraccion
                and self.etapa_causa in ("e1", "e3"))

    def como_en_la_fuente(self, h: Hallazgo, campo: str) -> bool:
        """¿E3 extrajo en ese campo lo mismo que en el run fuente adjudicado?
        Solo entonces vale lo que la adjudicación dijo de él."""
        return self.hallazgos_fuente is None or any(
            _valor(f, campo) == _valor(h, campo) for f in self.hallazgos_fuente)


def _valor(h: Hallazgo, campo: str) -> str | None:
    valor = getattr(h, campo)
    return None if valor is None else normalizar_texto(str(valor))


def _referencia(ev: ResultadoEvaluado, items: Mapping[str, ItemGt], modelo: str,
                fuentes: Mapping[tuple[str, str], ReporteInforme] | None = None) -> _Referencia:
    if ev.veredicto == evaluar_comparador.Veredicto.OK_TEXTO_IDENTICO:
        return _Referencia(ev.veredicto.value, "OK")
    if ev.veredicto != evaluar_comparador.Veredicto.ADJUDICADO or ev.item_gt is None:
        return _Referencia(ev.veredicto.value, None)
    g = items[ev.item_gt]
    origenes = [o for o in g.origenes if o.modelo == modelo] or g.origenes
    return _Referencia(
        g.subclase, g.clase, g.etapa_causa, frozenset(c.value for c in g.campos_extraccion),
        tuple(o.contraparte_pdf.referencia for o in origenes if o.contraparte_pdf),
        next((o.contraparte_excel.referencia for o in origenes if o.contraparte_excel), None),
        None if fuentes is None else tuple(
            h for o in origenes
            if (h := fuentes[(o.ronda, o.run_id)].resultados[o.idx].hallazgo_pdf) is not None))


def _campo_del_par(ref: _Referencia, campo: str, r: MatchResult, par: bool) -> Veredicto:
    h = r.hallazgo_pdf
    assert h is not None
    if ref.atribuye(campo):
        if not ref.como_en_la_fuente(h, campo):
            return S
        return E1 if ref.etapa_causa == "e1" else E
    x = r.hallazgo_excel
    if not par or x is None or (campo != "descripcion" and getattr(x, campo) is None):
        return S
    if campo not in {d.campo.value for d in r.diferencias}:
        return C
    if (ref.clase == "A" or (ref.nombre == "D6" and ref.etapa_causa == "e4")) and (
            ref.como_en_la_fuente(h, campo)):
        return C
    return S


def _polaridad_del_par(r: MatchResult, par: bool, campos: Mapping[str, Veredicto]) -> Veredicto:
    h, x = r.hallazgo_pdf, r.hallazgo_excel
    if not par or h is None or x is None:
        return S
    vistos = []
    for campo in ("descripcion", "accion_correctiva"):
        p, q = _polaridad(getattr(h, campo) or ""), _polaridad(getattr(x, campo) or "")
        if p is not None and q is not None:
            vistos.append(C if p == q else campos[campo])
    errores = [v for v in vistos if v in (E, E1)]
    if errores:
        return errores[0]
    return S if not vistos or S in vistos else C


def _veredictos_adjudicado(r: MatchResult, ref: _Referencia, mapa: MapaE1,
                           filas_excel: Mapping[int, set[Tupla]]) -> dict[str, Veredicto]:
    h = r.hallazgo_pdf
    assert h is not None
    if ref.clase is None:
        return dict.fromkeys(CAMPOS, S)
    if ref.atribuye("de_mas"):
        return {**dict.fromkeys(CAMPOS, S), "de_mas": E}
    v = {"omision": C, "de_mas": C, "tupla": C}
    if ref.atribuye("tupla"):
        correctas = filas_excel.get(ref.fila_contraparte, set()) if ref.fila_contraparte else set()
        de_e1 = ref.etapa_causa == "e1" or bool(correctas) and all(
            mapa.explica(pano, rele, h.evidencia.pagina_pdf) for pano, rele in correctas)
        v["tupla"] = E1 if de_e1 else E
    par = r.hallazgo_excel is not None and ref.nombre not in _PAR_AJENO
    for campo in _CAMPOS_PAR:
        v[campo] = _campo_del_par(ref, campo, r, par)
    if ref.atribuye("clasificacion") and ref.como_en_la_fuente(h, "clasificacion"):
        v["clasificacion"] = E1 if ref.etapa_causa == "e1" else E
    elif not par or r.hallazgo_excel is None:
        v["clasificacion"] = S
    else:
        v["clasificacion"] = _clasificacion(h, r.hallazgo_excel)
    v["polaridad"] = _polaridad_del_par(r, par, v)
    return {c: v[c] for c in CAMPOS}


def medir_adjudicado(reporte: ReporteInforme, e3: Sequence[Hallazgo], gt: GtInforme,
                     mapa: MapaE1, *, modelo: str,
                     fuentes: Mapping[tuple[str, str], ReporteInforme] | None = None) -> Medida:
    """Cada hallazgo de E3 contra la adjudicación de su resultado (el GT es el
    del informe del reporte: no se vuelve a comprobar el sha256). ``fuentes``
    (por ronda y run, los reportes de las fuentes del GT): el reporte no es el
    que se adjudicó y lo heredado se compara con lo que extrajo E3 en la fuente."""
    resultados = reporte.resultados
    ev = evaluar(reporte, gt, sha256_informe=gt.sha256_informe_original,
                 sha256_excel=gt.sha256_excel, modelo=modelo)
    indices = mapa_e3(resultados, e3)
    items = {g.id: g for g in gt.items}
    filas_excel: dict[int, set[Tupla]] = defaultdict(set)
    for r in resultados:
        if r.hallazgo_excel is not None and r.hallazgo_excel.evidencia.fila_excel is not None:
            filas_excel[r.hallazgo_excel.evidencia.fila_excel].add(
                (r.hallazgo_excel.pano, r.hallazgo_excel.rele))
    hallazgos: list[HallazgoMedido] = []
    omisiones: list[OmisionMedida] = []
    filas_sin_referencia = 0
    for i, (r, evaluado) in enumerate(zip(resultados, ev.resultados, strict=True)):
        ref = _referencia(evaluado, items, modelo, fuentes)
        if r.estado == EstadoHallazgo.EXTRA_EN_EXCEL and ref.clase is None:
            filas_sin_referencia += 1
        if r.hallazgo_pdf is not None:
            hallazgos.append(HallazgoMedido(indices[i], _tupla(r.hallazgo_pdf), ref.nombre,
                                            _veredictos_adjudicado(r, ref, mapa, filas_excel)))
        if ref.atribuye("omision"):
            x = r.hallazgo_excel
            pano, rele = (x.pano, x.rele) if x is not None else (r.pano, r.rele)
            de_e1 = ref.etapa_causa == "e1" or mapa.explica(pano, rele) or any(
                mapa.explica(pano, rele, p) for p in ref.paginas_contraparte)
            omisiones.append(OmisionMedida(clave_tupla(pano, rele), ref.nombre,
                                           E1 if de_e1 else E))
    tuplas = frozenset(clave_tupla(r.pano, r.rele) for r in resultados
                       if r.estado != EstadoHallazgo.TRANSVERSAL)
    return Medida(CAMPOS, sorted(hallazgos, key=lambda m: m.indice_e3), omisiones, tuplas,
                  filas_sin_referencia)


# ---------------------------------------------------------------- control de copia

_TIPOGRAFIA = str.maketrans({**dict.fromkeys("“”„«»", '"'), **dict.fromkeys("‘’", "'"),
                             **dict.fromkeys("‐‑‒–—−", "-")})


def texto_copia(texto: str | None) -> str | None:
    """NFKC, comillas y guiones tipográficos unificados y espacios colapsados:
    lo que cambia al copiar el PDF al Excel sin cambiar el contenido. Letras,
    cifras, signos y mayúsculas quedan como están."""
    if texto is None:
        return None
    return " ".join(unicodedata.normalize("NFKC", texto).translate(_TIPOGRAFIA).split())


_Clave = Callable[[Hallazgo], Hashable]
# Pasadas de la alineación, en orden. Tras las dos primeras ya no quedan
# hallazgos con la descripción de una fila libre de su misma tupla.
_PASADAS: tuple[tuple[_Clave, str], ...] = (
    (lambda h: (_tupla(h), texto_copia(h.descripcion), texto_copia(h.accion_correctiva)),
     "copia_misma_tupla"),
    (lambda h: (_tupla(h), texto_copia(h.descripcion)), "copia_misma_tupla"),
    (lambda h: texto_copia(h.descripcion), "copia_otra_tupla"),
    (_tupla, "copia_orden"),
)


def _alinear_copia(e3: Sequence[Hallazgo], e2: Sequence[Hallazgo],
                   filas: Sequence[int]) -> tuple[dict[int, tuple[int, str]], list[int]]:
    """(índice de E3 → (índice de E2, pasada), filas de E2 sin pareja)."""
    pares: dict[int, tuple[int, str]] = {}
    libres2 = list(filas)
    for clave, tipo in _PASADAS:
        cola: dict[Hashable, list[int]] = defaultdict(list)
        for j in libres2:
            cola[clave(e2[j])].append(j)
        for i, h in enumerate(e3):
            if i not in pares and cola.get(clave(h)):
                pares[i] = (cola[clave(h)].pop(0), tipo)
        usados = {j for j, _ in pares.values()}
        libres2 = [j for j in libres2 if j not in usados]
    return pares, libres2


def _igual(valor_e3: str | None, valor_excel: str | None) -> Veredicto:
    """Acción o calificación (StrEnum) del par; sin valor en el Excel, sin referencia."""
    if valor_excel is None:          # el Excel no trae la columna
        return S
    return C if texto_copia(valor_e3) == texto_copia(valor_excel) else E


def medir_copia(e3: Sequence[Hallazgo], e2: Sequence[Hallazgo], mapa: MapaE1, *,
                patrones_transversales: Sequence[str] = ()) -> Medida:
    """E3 contra E2 en un informe cuyo Excel copia el PDF, sin la Etapa 4. Las
    filas transversales según la regla de hoy (``patrones_transversales``: los
    del catálogo de su auditora) no se le piden a E3, aunque la E2 de una ronda
    anterior no las marcara."""
    patrones = [_normaliza(p) for p in patrones_transversales if p.strip()]
    filas = [j for j, x in enumerate(e2)
             if not (x.es_transversal or _es_transversal(x.rele, patrones))]
    pares, sin_pareja = _alinear_copia(e3, e2, filas)
    hallazgos: list[HallazgoMedido] = []
    for i, h in enumerate(e3):
        if i not in pares:
            hallazgos.append(HallazgoMedido(i, _tupla(h), "copia_sin_pareja",
                                            {**dict.fromkeys(CAMPOS_COPIA, S), "de_mas": E}))
            continue
        j, tipo = pares[i]
        x = e2[j]
        v = {"omision": C, "de_mas": C, "tupla": C}
        if tipo == "copia_orden":
            v |= {"descripcion": E, "accion_correctiva": S, "calificacion": S,
                  "clasificacion": S}
        else:
            if tipo == "copia_otra_tupla":
                v["tupla"] = E1 if mapa.explica(x.pano, x.rele, h.evidencia.pagina_pdf) else E
            v |= {"descripcion": C,
                  "accion_correctiva": _igual(h.accion_correctiva, x.accion_correctiva),
                  "calificacion": _igual(h.calificacion, x.calificacion),
                  "clasificacion": _clasificacion(h, x)}
        hallazgos.append(HallazgoMedido(i, _tupla(h), tipo, {c: v[c] for c in CAMPOS_COPIA}))
    omisiones = [OmisionMedida(_tupla(e2[j]), "copia_sin_pareja",
                               E1 if mapa.explica(e2[j].pano, e2[j].rele) else E)
                 for j in sin_pareja]
    tuplas = frozenset([*(_tupla(h) for h in e3), *(_tupla(e2[j]) for j in filas)])
    return Medida(CAMPOS_COPIA, hallazgos, omisiones, tuplas)


# ---------------------------------------------------------------- runs


class Caso(NamedTuple):
    """Un run de una evaluación: ronda, modelo, informe (nombre corto) y carpeta."""

    ronda: str
    modelo: str
    informe: str
    run_dir: Path


@dataclass(frozen=True)
class Medicion:
    fuente: str
    caso: Caso
    medida: Medida


def _hallazgos(ruta: Path) -> list[Hallazgo]:
    return [Hallazgo.model_validate(h) for h in cargar_json(ruta)]


def _sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _fuente_del_gt(caso: Caso,
                   gts: Sequence[GtAplicable]) -> tuple[GtInforme, FuenteGt] | None:
    """La fuente base del GT que es este run. Una fuente de una ronda posterior
    (``complementa``) no: su archivo adjudica solo lo que el GT de antes no
    adjudicaba, y el run se mide contra el GT como cualquier ronda posterior."""
    for g in gts:
        for f in g.gt.fuentes:
            if (not f.complementa and f.run_id == caso.run_dir.name
                    and f.ronda.casefold() == caso.ronda.casefold()):
                return g.gt, f
    return None


def medir_run_adjudicado(run_dir: Path, gt: GtInforme, fuente: FuenteGt) -> Medida:
    """Un run fuente del GT, con los mismos archivos con que se armó (si no, falla)."""
    cambios = [] if hashes_del_run(run_dir) == (gt.sha256_informe_original, gt.sha256_excel) \
        else ["el informe o el Excel"]
    for nombre, esperado in (("reporte_final.json", fuente.sha256_reporte),
                             (E3_JSON, fuente.sha256_e3)):
        if not (run_dir / nombre).is_file() or _sha256(run_dir / nombre) != esperado:
            cambios.append(nombre)
    if cambios:
        raise ValueError(f"{run_dir.name} es fuente del GT de {gt.informe}, pero "
                         f"{', '.join(cambios)} cambió desde que se armó el GT")
    reporte = ReporteInforme.model_validate(cargar_json(run_dir / "reporte_final.json"))
    return medir_adjudicado(reporte, _hallazgos(run_dir / E3_JSON), gt,
                            MapaE1.del_run(run_dir), modelo=fuente.modelo)


def reportes_fuente(gt: GtInforme, mediciones: Path, *,
                    para: str) -> dict[tuple[str, str], ReporteInforme]:
    """Por ronda y run (una repetición de E4 comparte el run_id con su origen),
    el reporte de cada fuente del GT tal como se adjudicó (``<mediciones>/<su
    carpeta>``, sha256): si falta o cambió, falla."""
    reportes: dict[tuple[str, str], ReporteInforme] = {}
    for f in gt.fuentes:
        ruta = mediciones / f.carpeta / "reporte_final.json"
        if not ruta.is_file() or _sha256(ruta) != f.sha256_reporte:
            raise ValueError(
                f"{para}: medirlo contra el GT de {gt.informe} necesita el reporte de su fuente "
                f"{f.modelo} tal como se adjudicó, y {ruta} no existe o cambió")
        reportes[(f.ronda, f.run_id)] = ReporteInforme.model_validate(cargar_json(ruta))
    return reportes


def medir_run_contra_gt(run_dir: Path, gt: GtInforme, *, modelo: str,
                        mediciones: Path) -> Medida:
    """Un run que no es fuente del GT, de su mismo informe y Excel: lo que calza
    con un ítem del GT recibe veredicto si E3 extrajo lo mismo que en la fuente;
    lo demás queda sin referencia."""
    reporte = ReporteInforme.model_validate(cargar_json(run_dir / "reporte_final.json"))
    return medir_adjudicado(reporte, _hallazgos(run_dir / E3_JSON), gt,
                            MapaE1.del_run(run_dir), modelo=modelo,
                            fuentes=reportes_fuente(gt, mediciones, para=run_dir.name))


def _numero_ronda(etiqueta: str) -> int | None:
    m = re.fullmatch(r"[Bb](\d+)\w*", etiqueta)
    return int(m[1]) if m else None


def _gt_posterior(caso: Caso, gts: Sequence[GtAplicable]) -> GtAplicable | None:
    """El GT del informe y Excel del run si su ronda es posterior a la de todas
    las fuentes base del GT (B3 frente a B2; una fuente de una ronda posterior no
    corre la referencia); None si no hay GT o la ronda no es posterior (B0-B2 no
    se miden contra el GT: sus filas no cambian). Una ronda sin número con GT
    aplicable falla: no se puede saber si es posterior."""
    hashes = hashes_del_run(caso.run_dir)
    if hashes is None:
        return None
    aplicable = gt_aplicable(gts, *hashes)
    if aplicable is None:
        return None
    rondas = {f.ronda: _numero_ronda(f.ronda) for f in aplicable.gt.fuentes
              if not f.complementa}
    numero = _numero_ronda(caso.ronda)
    if numero is None or None in rondas.values():
        raise ValueError(
            f"{caso.run_dir.name}: no se puede ordenar la ronda {caso.ronda!r} respecto de las "
            f"fuentes del GT de {aplicable.gt.informe} ({sorted(rondas)}): la etiqueta debe ser "
            "B<número> (p. ej. B3, B3s)")
    return aplicable if numero > max(n for n in rondas.values() if n is not None) else None


def medir_run_copia(run_dir: Path, empresa: EmpresaAuditora) -> Medida:
    return medir_copia(_hallazgos(run_dir / E3_JSON), _hallazgos(run_dir / E2_JSON),
                       MapaE1.del_run(run_dir),
                       patrones_transversales=cargar_hints_empresa(empresa).filas_transversales)


def medir_casos(casos: Iterable[Caso], gts: Sequence[GtAplicable], *,
                mediciones: Path) -> list[Medicion]:
    """Primero los runs fuente de un GT (con su adjudicación), después los de
    Beta y Eta que guardaron las etapas 2 y 3 (control de copia) y al
    final los de rondas posteriores al GT con su mismo informe y Excel (contra
    el GT, con los reportes de sus fuentes leídos de ``mediciones``): las filas
    de antes no se mueven."""
    casos = list(casos)
    salida: list[Medicion] = []
    fuentes: set[Path] = set()
    for caso in casos:
        fuente = _fuente_del_gt(caso, gts)
        if fuente is not None:
            gt, f = fuente
            if f.modelo != caso.modelo:
                raise ValueError(f"{caso.run_dir.name}: el GT de {gt.informe} lo tiene como "
                                 f"run de {f.modelo}, la evaluación como de {caso.modelo}")
            fuentes.add(caso.run_dir)
            salida.append(Medicion(f"{f.ronda.lower()}_adjudicado", caso,
                                   medir_run_adjudicado(caso.run_dir, gt, f)))
    for caso in casos:
        if caso.informe in INFORMES_COPIA and all(
                (caso.run_dir / n).is_file() for n in (E3_JSON, E2_JSON)):
            salida.append(Medicion(FUENTE_COPIA, caso,
                                   medir_run_copia(caso.run_dir, INFORMES_COPIA[caso.informe])))
    for caso in casos:
        if caso.run_dir in fuentes:
            continue
        aplicable = _gt_posterior(caso, gts)
        if aplicable is not None:
            salida.append(Medicion(FUENTE_CONTRA_GT, caso, medir_run_contra_gt(
                caso.run_dir, aplicable.gt, modelo=caso.modelo, mediciones=mediciones)))
    return salida


def filas(mediciones: Sequence[Medicion]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(``extraccion_por_campo.csv``, ``extraccion_por_tupla.csv``): solo conteos."""
    por_campo: list[dict[str, Any]] = []
    por_tupla: list[dict[str, Any]] = []
    for m in mediciones:
        base = {"fuente": m.fuente, "ronda": m.caso.ronda, "modelo": m.caso.modelo,
                "informe": m.caso.informe}
        por_campo += [{**base, "campo": c, **m.medida.conteo(c)} for c in m.medida.campos]
        por_tupla.append({**base, **m.medida.por_tupla()})
    return por_campo, por_tupla
