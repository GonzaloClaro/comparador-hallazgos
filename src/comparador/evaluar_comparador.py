"""Evaluación del comparador de un run contra el GT de su informe (M64), sin API.

Como ``evaluar_checklist`` para el checklist: cada resultado del reporte cae en
un veredicto, buscado por claves estables y nunca por el índice del resultado
(``comparador.gt_comparador``):

- ``adjudicado``: un único ítem del GT con el mismo par, estado y campos que
  difieren (D4) → su clase (A..E u OK).
- ``ok_texto_identico``: «coincide» sin ítem del GT para su par, con
  descripción, acción y calificación idénticas en el PDF y el Excel (D13): OK
  por regla automática, en columna aparte. Si el GT tiene ese par con otro
  estado o campos, queda sin adjudicar.
- ``sin_adjudicar``, con su motivo: ``clave_no_encontrada``, ``ambigua``,
  ``par_distinto`` (el GT empareja ese lado con otro, o sin pareja),
  ``estado_distinto``, ``campos_distintos``, ``item_repetido`` (varios
  resultados calzan con el mismo ítem: ninguno se adjudica, no se sabe cuál
  es). Nunca cuenta como correcto.
- ``fuera_de_universo``: «coincide» sin ninguna clave en el GT de un informe
  donde solo se adjudicó una muestra de «coincide» (Beta y Eta).
- ``transversal``: no entra al comparador (invariante 19b).

Métricas: clases con y sin duplicados; alertas (ni coincide ni transversal) y
cuántas quedaron sin adjudicar; precisión A/(A+D) y, si hay alertas sin
adjudicar, su rango (todas D … todas A); los errores reales del GT que el run ya no muestra
(ni con su ítem ni con otro ítem A que sea el mismo error: el mismo hallazgo del
PDF que el Excel omite o invierte, o la misma fila del Excel, ``LADO_PROPIO_A``;
cada error una vez aunque tenga varios ítems A);
los posibles errores escondidos (un «coincide» no adjudicado que toma un lado de
un A o un D del GT) y el estado de los errores reales del Excel no mostrados en
B2 (la misma regla que tests/golden/test_golden_errores_no_mostrados.py).

``GtNoAplicaError`` si el run no es del informe y el Excel del GT (sha256).

Para los lotes y las repeticiones de E4 (``evaluar_lote``, ``reproducir_e4``,
``metricas_lote``): ``gts_de`` lee una carpeta de GT y ``gt_aplicable`` elige
el del informe y Excel de un run (ninguno no es error; dos, o el GT con el
nombre del informe atado a otros archivos, sí). Lo guardado lleva el sha256 del
archivo del GT (``resumen_con_gt``), para saber al recalcular si se hizo con el
mismo GT; ``evaluacion_repeticion`` junta el antes, el después y el ``delta``.

Uso:
    python -m comparador.evaluar_comparador <run_dir> [--gt archivo.json | --gt-dir carpeta]
        [--json]
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import sys
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from comparador.adjudicacion import CLASES
from comparador.gt_comparador import (
    RAIZ,
    ErrorExcelGt,
    GtInforme,
    ItemGt,
    cargar_gt,
    hashes_del_run,
    texto_identico,
)
from comparador.persistence import cargar_json
from comparador.schemas import EstadoHallazgo, MatchResult, ReporteInforme

GT_DIR_DEFAULT = RAIZ / "mediciones" / "gt" / "comparador"


class GtNoAplicaError(ValueError):
    """El run no es del mismo informe y Excel que el GT."""


class Veredicto(StrEnum):
    ADJUDICADO = "adjudicado"
    OK_TEXTO_IDENTICO = "ok_texto_identico"
    SIN_ADJUDICAR = "sin_adjudicar"
    FUERA_DE_UNIVERSO = "fuera_de_universo"
    TRANSVERSAL = "transversal"


class MotivoSinAdjudicar(StrEnum):
    CLAVE_NO_ENCONTRADA = "clave_no_encontrada"
    AMBIGUA = "ambigua"
    PAR_DISTINTO = "par_distinto"
    ESTADO_DISTINTO = "estado_distinto"
    CAMPOS_DISTINTOS = "campos_distintos"
    ITEM_REPETIDO = "item_repetido"


@dataclass(frozen=True)
class ResultadoEvaluado:
    idx: int
    estado: str
    veredicto: Veredicto
    motivo: MotivoSinAdjudicar | None = None
    item_gt: str | None = None
    clase: str | None = None
    subclase: str | None = None
    duplicado: bool = False
    candidatos: tuple[str, ...] = ()     # ítems del GT que comparten alguna clave


@dataclass(frozen=True)
class PosibleEscondido:
    """Un «coincide» no adjudicado que toma un lado de un A o un D del GT."""

    item_gt: str
    clase: str
    idx: int
    par_completo: bool


@dataclass(frozen=True)
class EstadoErrorExcel:
    id: str
    fila_excel: int
    estado: Literal["mostrado", "no_mostrado", "escondido"]
    motivos: tuple[str, ...]


@dataclass
class EvaluacionComparador:
    run_id: str
    informe: str
    modelo: str | None
    resultados: list[ResultadoEvaluado] = field(default_factory=list)
    a_perdidos: list[str] = field(default_factory=list)
    posibles_escondidos: list[PosibleEscondido] = field(default_factory=list)
    errores_excel: list[EstadoErrorExcel] = field(default_factory=list)

    def _con(self, veredicto: Veredicto) -> list[ResultadoEvaluado]:
        return [r for r in self.resultados if r.veredicto == veredicto]

    @property
    def adjudicados(self) -> list[ResultadoEvaluado]:
        return self._con(Veredicto.ADJUDICADO)

    @property
    def conteo(self) -> dict[str, int]:
        cuenta = Counter(r.clase for r in self.adjudicados)
        return {c: cuenta[c] for c in CLASES}

    @property
    def sin_duplicados(self) -> dict[str, int]:
        cuenta = Counter(r.clase for r in self.adjudicados if not r.duplicado)
        return {c: cuenta[c] for c in CLASES}

    @property
    def sin_adjudicar(self) -> list[ResultadoEvaluado]:
        """Dentro del universo y sin clase: nunca cuentan como correctos."""
        return self._con(Veredicto.SIN_ADJUDICAR)

    @property
    def ok_texto_identico(self) -> int:
        return len(self._con(Veredicto.OK_TEXTO_IDENTICO))

    @property
    def fuera_de_universo(self) -> int:
        return len(self._con(Veredicto.FUERA_DE_UNIVERSO))

    @property
    def alertas(self) -> int:
        return sum(r.estado not in ("coincide", "transversal") for r in self.resultados)

    @property
    def alertas_sin_adjudicar(self) -> int:
        return sum(r.estado != "coincide" for r in self.sin_adjudicar)

    @property
    def precision(self) -> float | None:
        """A / (A + D) de lo adjudicado (None sin A ni D)."""
        a, d = self.conteo["A"], self.conteo["D"]
        return a / (a + d) if a + d else None

    @property
    def precision_rango(self) -> tuple[float, float] | None:
        """Precisión si las alertas sin adjudicar fueran todas D … todas A."""
        a, d, n = self.conteo["A"], self.conteo["D"], self.alertas_sin_adjudicar
        return (a / (a + d + n), (a + n) / (a + d + n)) if a + d + n else None


# ---------------------------------------------------------------- evaluación


def _clasificar(i: int, r: MatchResult, gt: GtInforme, coincide_todos: bool) -> ResultadoEvaluado:
    estado = r.estado.value
    if r.estado == EstadoHallazgo.TRANSVERSAL:
        return ResultadoEvaluado(i, estado, Veredicto.TRANSVERSAL)
    pares = [g for g in gt.items if g.calza_par(r)]
    iguales = [g for g in pares if g.mismo_estado_y_campos(r)]
    if len(iguales) == 1:
        g = iguales[0]
        return ResultadoEvaluado(i, estado, Veredicto.ADJUDICADO, item_gt=g.id, clase=g.clase,
                                 subclase=g.subclase, duplicado=g.es_duplicado)
    if len(iguales) > 1:
        return ResultadoEvaluado(i, estado, Veredicto.SIN_ADJUDICAR, MotivoSinAdjudicar.AMBIGUA,
                                 candidatos=tuple(g.id for g in iguales))
    if pares:
        motivo = (MotivoSinAdjudicar.CAMPOS_DISTINTOS
                  if any(g.estado == r.estado for g in pares)
                  else MotivoSinAdjudicar.ESTADO_DISTINTO)
        return ResultadoEvaluado(i, estado, Veredicto.SIN_ADJUDICAR, motivo,
                                 candidatos=tuple(g.id for g in pares))
    if texto_identico(r):
        return ResultadoEvaluado(i, estado, Veredicto.OK_TEXTO_IDENTICO)
    parciales = tuple(g.id for g in gt.items if g.claves().calza_algun_lado(r))
    if parciales:
        return ResultadoEvaluado(i, estado, Veredicto.SIN_ADJUDICAR,
                                 MotivoSinAdjudicar.PAR_DISTINTO, candidatos=parciales)
    if r.estado == EstadoHallazgo.COINCIDE and not coincide_todos:
        return ResultadoEvaluado(i, estado, Veredicto.FUERA_DE_UNIVERSO)
    return ResultadoEvaluado(i, estado, Veredicto.SIN_ADJUDICAR,
                             MotivoSinAdjudicar.CLAVE_NO_ENCONTRADA)


def _sin_repetidos(evaluados: list[ResultadoEvaluado]) -> list[ResultadoEvaluado]:
    """Un ítem del GT adjudica un solo resultado: si calza con varios, ninguno
    queda adjudicado (no se sabe cuál es el suyo) y todos van sin adjudicar."""
    cuenta = Counter(r.item_gt for r in evaluados if r.veredicto == Veredicto.ADJUDICADO)
    return [ResultadoEvaluado(r.idx, r.estado, Veredicto.SIN_ADJUDICAR,
                              MotivoSinAdjudicar.ITEM_REPETIDO, candidatos=(r.item_gt,))
            if r.veredicto == Veredicto.ADJUDICADO and r.item_gt and cuenta[r.item_gt] > 1
            else r for r in evaluados]


# Lado propio del error de cada subclase A, para saber qué ítems A son el mismo
# error: el hallazgo del PDF que el Excel omite (A1) o invierte (A5), o la fila
# del Excel que trae lo que el PDF no dice (A2), con otro texto (A3) u otra
# calificación (A4). El otro lado de un A1 «difiere» es una fila ajena.
LADO_PROPIO_A: dict[str, Literal["pdf", "excel"]] = {
    "A1": "pdf", "A5": "pdf", "A2": "excel", "A3": "excel", "A4": "excel"}


def _lado_propio(g: ItemGt) -> Literal["pdf", "excel"]:
    if g.subclase not in LADO_PROPIO_A:
        raise ValueError(f"ítem {g.id}: la subclase {g.subclase} no tiene lado propio conocido "
                         "(LADO_PROPIO_A): no se puede saber qué ítems son el mismo error")
    return LADO_PROPIO_A[g.subclase]


def mismo_error(g: ItemGt, h: ItemGt) -> bool:
    """¿Dos ítems A son el mismo error? Sí si comparten la clave de su lado
    propio: en el PDF, la tupla, la página y alguna cita (p. ej. el hallazgo que
    un modelo deja como falta y otro empareja con una fila ajena); en el Excel,
    la tupla y la fila."""
    lado = _lado_propio(g)
    if lado != _lado_propio(h):
        return False
    a, b = g.claves(), h.claves()
    if lado == "excel":
        return a.excel is not None and a.excel == b.excel
    return (a.pdf is not None and b.pdf is not None
            and (a.pdf.tupla, a.pdf.pagina) == (b.pdf.tupla, b.pdf.pagina)
            and bool(set(a.pdf.citas) & set(b.pdf.citas)))


def a_perdidos(gt: GtInforme, mostrados: set[str]) -> list[str]:
    """Los errores reales (A del GT) que el run no muestra. Los ítems A que son el
    mismo error (``mismo_error``; del lado del PDF no es transitivo, así que se toman
    las componentes conexas) forman un error: está mostrado si el run muestra
    cualquiera de sus ítems, y si no, cuenta una vez, con el primero del GT."""
    items_a = [g for g in gt.items if g.clase == "A"]
    for g in items_a:
        _lado_propio(g)
    componente = list(range(len(items_a)))

    def raiz(k: int) -> int:
        while componente[k] != k:
            k = componente[k]
        return k

    for i, j in itertools.combinations(range(len(items_a)), 2):
        if mismo_error(items_a[i], items_a[j]):
            # La raíz es siempre el de menor posición: el primero del GT.
            ri, rj = raiz(i), raiz(j)
            componente[max(ri, rj)] = min(ri, rj)
    mostradas = {raiz(k) for k, g in enumerate(items_a) if g.id in mostrados}
    return [g.id for k, g in enumerate(items_a) if raiz(k) == k and k not in mostradas]


def _posibles_escondidos(resultados: Sequence[MatchResult], evaluados: list[ResultadoEvaluado],
                         gt: GtInforme) -> list[PosibleEscondido]:
    salida = []
    for r, ev in zip(resultados, evaluados, strict=True):
        if r.estado != EstadoHallazgo.COINCIDE or ev.veredicto == Veredicto.ADJUDICADO:
            continue
        for g in gt.items:
            if g.clase not in ("A", "D"):
                continue
            claves = g.claves()
            calzan = [c.calza(h) for c, h in ((claves.excel, r.hallazgo_excel),
                                              (claves.pdf, r.hallazgo_pdf)) if c is not None]
            if any(calzan):
                salida.append(PosibleEscondido(g.id, g.clase, ev.idx, all(calzan)))
    return salida


def _pagina(r: MatchResult) -> int | None:
    return r.hallazgo_pdf.evidencia.pagina_pdf if r.hallazgo_pdf is not None else None


def estado_error_excel(resultados: Sequence[MatchResult], e: ErrorExcelGt) -> EstadoErrorExcel:
    """«escondido» si la fila sale «coincide»; «mostrado» si la alerta lleva al
    error: con contraparte validada, un único «difiere» con su hallazgo del PDF
    (página y clasificación), solo en sus campos y sin equivalencias del juez de
    redacción; sin ella, alguna alerta de la fila hacia su página."""
    de_la_fila = [r for r in resultados if r.hallazgo_excel is not None
                  and r.hallazgo_excel.evidencia.fila_excel == e.fila_excel]
    if not de_la_fila:
        return EstadoErrorExcel(e.id, e.fila_excel, "no_mostrado",
                                (f"la fila {e.fila_excel} no aparece en el reporte",))
    coinciden = [r for r in de_la_fila if r.estado == EstadoHallazgo.COINCIDE]
    if coinciden:
        return EstadoErrorExcel(e.id, e.fila_excel, "escondido", tuple(
            f"la fila {e.fila_excel} sale «coincide» con la pág. {_pagina(r)}" for r in coinciden))
    problemas: list[str] = []
    if not e.contraparte_validada:
        if not any(_pagina(r) == e.pagina_pdf for r in de_la_fila):
            problemas.append(f"ninguna alerta de la fila {e.fila_excel} lleva a la pág. "
                             f"{e.pagina_pdf}")
    elif len(de_la_fila) != 1:
        problemas.append(f"la fila {e.fila_excel} aparece {len(de_la_fila)} veces (se espera 1)")
    else:
        (r,) = de_la_fila
        clasificacion = r.hallazgo_pdf.clasificacion if r.hallazgo_pdf else None
        visto = (r.estado.value, _pagina(r), clasificacion,
                 tuple(d.campo.value for d in r.diferencias))
        esperado = ("difiere", e.pagina_pdf, e.clasificacion_pdf, tuple(c.value for c in e.campos))
        if visto != esperado:
            problemas.append(f"(estado, página, clasificación, campos) = {visto}, "
                             f"se espera {esperado}")
        if r.equivalencias_redaccion:
            problemas.append("campos dados por equivalentes por el juez: "
                             f"{sorted({q.campo.value for q in r.equivalencias_redaccion})}")
    return EstadoErrorExcel(e.id, e.fila_excel, "no_mostrado" if problemas else "mostrado",
                            tuple(problemas))


def comprobar_que_aplica(gt: GtInforme, sha256_informe: str, sha256_excel: str) -> None:
    if (sha256_informe, sha256_excel) != (gt.sha256_informe_original, gt.sha256_excel):
        raise GtNoAplicaError(
            f"el GT de {gt.informe} es de otro informe o Excel (sha256 del run "
            f"{sha256_informe[:12]}…/{sha256_excel[:12]}…, del GT "
            f"{gt.sha256_informe_original[:12]}…/{gt.sha256_excel[:12]}…)")


def evaluar(reporte: ReporteInforme, gt: GtInforme, *, sha256_informe: str, sha256_excel: str,
            run_id: str = "", modelo: str | None = None) -> EvaluacionComparador:
    """Evalúa el comparador de un reporte contra el GT de su informe."""
    comprobar_que_aplica(gt, sha256_informe, sha256_excel)
    modelo = modelo or reporte.modelo_extraccion
    coincide_todos = gt.coincide_en_universo(modelo)
    resultados = reporte.resultados
    evaluados = _sin_repetidos([_clasificar(i, r, gt, coincide_todos)
                                for i, r in enumerate(resultados)])
    # Un ítem repetido no se adjudica, pero el run sí muestra su par.
    mostrados = {g for r in evaluados for g in (
        (r.item_gt,) if r.veredicto == Veredicto.ADJUDICADO and r.item_gt
        else r.candidatos if r.motivo == MotivoSinAdjudicar.ITEM_REPETIDO else ())}
    return EvaluacionComparador(
        run_id=run_id, informe=gt.informe, modelo=modelo, resultados=evaluados,
        a_perdidos=a_perdidos(gt, mostrados),
        posibles_escondidos=_posibles_escondidos(resultados, evaluados, gt),
        errores_excel=[estado_error_excel(resultados, e) for e in gt.errores_excel],
    )


def _hashes(run_dir: Path) -> tuple[str, str]:
    hashes = hashes_del_run(run_dir)
    if hashes is None:
        raise GtNoAplicaError(f"{run_dir.name}: sin input_informe_original.hash o "
                              "input_excel.hash, no se puede atar al GT")
    return hashes


def evaluar_run(run_dir: Path, gt: GtInforme) -> EvaluacionComparador:
    sha_informe, sha_excel = _hashes(run_dir)
    ruta = run_dir / "reporte_final.json"
    if not ruta.is_file():
        raise ValueError(f"{run_dir.name}: sin reporte_final.json (run fallido o solo del "
                         "checklist): no hay comparador que evaluar")
    reporte = ReporteInforme.model_validate(cargar_json(ruta))
    return evaluar(reporte, gt, sha256_informe=sha_informe, sha256_excel=sha_excel,
                   run_id=run_dir.name)


@dataclass(frozen=True)
class GtAplicable:
    """Un GT y el sha256 de su archivo: con él se sabe, al recalcular, si una
    evaluación guardada se hizo con el mismo GT."""

    ruta: Path
    sha256: str
    gt: GtInforme


def gts_de(carpeta: Path) -> list[GtAplicable]:
    """Los GT de la carpeta (ninguno si no existe). Uno que no valida, falla."""
    if not carpeta.is_dir():
        return []
    return [GtAplicable(ruta, hashlib.sha256(ruta.read_bytes()).hexdigest(), cargar_gt(ruta))
            for ruta in sorted(carpeta.glob("*.json"))]


def gt_aplicable(gts: Sequence[GtAplicable], sha256_informe: str, sha256_excel: str, *,
                 informe: str | None = None) -> GtAplicable | None:
    """El GT de ese informe y Excel (sha256), o None si no hay (no es error).

    ``GtNoAplicaError`` si hay más de uno, o si el GT del informe de nombre
    ``informe`` (la carpeta del caso) es de otro informe o Excel: medir sin él
    en silencio escondería que el GT quedó atado a archivos que ya no son.
    """
    if informe is not None:
        nombre = unicodedata.normalize("NFC", informe)
        for g in gts:
            if unicodedata.normalize("NFC", g.gt.informe) == nombre:
                comprobar_que_aplica(g.gt, sha256_informe, sha256_excel)
    candidatos = [g for g in gts if (g.gt.sha256_informe_original, g.gt.sha256_excel)
                  == (sha256_informe, sha256_excel)]
    if len(candidatos) > 1:
        raise GtNoAplicaError("más de un GT para el mismo informe y Excel: "
                              f"{', '.join(g.ruta.name for g in candidatos)}")
    return candidatos[0] if candidatos else None


def gt_del_run(run_dir: Path, carpeta: Path) -> GtInforme:
    """El GT de la carpeta cuyo informe y Excel son los del run."""
    aplicable = gt_aplicable(gts_de(carpeta), *_hashes(run_dir))
    if aplicable is None:
        raise GtNoAplicaError(f"{run_dir.name}: ningún GT de {carpeta} es de su informe y Excel")
    return aplicable.gt


def _redondeo(valor: float | None) -> float | None:
    return None if valor is None else round(valor, 4)


def resumen(ev: EvaluacionComparador) -> dict[str, Any]:
    """Cifras de la evaluación, sin texto de los informes."""
    rango = ev.precision_rango
    return {
        "run_id": ev.run_id, "informe": ev.informe, "modelo": ev.modelo,
        "resultados": len(ev.resultados),
        "transversales": len(ev._con(Veredicto.TRANSVERSAL)),
        "adjudicados": len(ev.adjudicados), **ev.conteo,
        "ok_texto_identico": ev.ok_texto_identico,
        "sin_adjudicar": len(ev.sin_adjudicar),
        "motivos_sin_adjudicar": dict(sorted(Counter(
            str(r.motivo) for r in ev.sin_adjudicar).items())),
        "estados_sin_adjudicar": dict(sorted(Counter(
            r.estado for r in ev.sin_adjudicar).items())),
        "fuera_de_universo": ev.fuera_de_universo,
        "alertas": ev.alertas, "alertas_sin_adjudicar": ev.alertas_sin_adjudicar,
        "precision_alertas": _redondeo(ev.precision),
        "precision_min": _redondeo(rango[0]) if rango else None,
        "precision_max": _redondeo(rango[1]) if rango else None,
        "A_sin_duplicados": ev.sin_duplicados["A"], "D_sin_duplicados": ev.sin_duplicados["D"],
        "a_perdidos": ev.a_perdidos,
        "posibles_escondidos": [
            {"item_gt": p.item_gt, "clase": p.clase, "idx": p.idx, "par_completo": p.par_completo}
            for p in ev.posibles_escondidos],
        "errores_excel": [{"id": e.id, "fila_excel": e.fila_excel, "estado": e.estado}
                          for e in ev.errores_excel],
    }


def resumen_con_gt(ev: EvaluacionComparador, gt: GtAplicable) -> dict[str, Any]:
    """``resumen`` con el GT con que se hizo (archivo y sha256): lo que se guarda."""
    return {"gt": gt.ruta.name, "sha256_gt": gt.sha256, **resumen(ev)}


def delta(antes: dict[str, Any], despues: dict[str, Any]) -> dict[str, Any]:
    """Qué cambió entre dos ``resumen`` del mismo informe y GT (p. ej. el run
    de origen y su repetición de E4). Los resultados se identifican por el ítem
    del GT, no por el índice, que cambia entre corridas."""
    ya_escondidos = {(p["item_gt"], p["par_completo"]) for p in antes["posibles_escondidos"]}
    estado_antes = {e["id"]: e["estado"] for e in antes["errores_excel"]}
    return {
        **{c: despues[c] - antes[c] for c in (*CLASES, "sin_adjudicar", "alertas")},
        "a_perdidos_nuevos": sorted(set(despues["a_perdidos"]) - set(antes["a_perdidos"])),
        "a_recuperados": sorted(set(antes["a_perdidos"]) - set(despues["a_perdidos"])),
        "posibles_escondidos_nuevos": [
            p for p in despues["posibles_escondidos"]
            if (p["item_gt"], p["par_completo"]) not in ya_escondidos],
        "errores_excel": [
            {"id": e["id"], "fila_excel": e["fila_excel"], "antes": estado_antes[e["id"]],
             "despues": e["estado"]}
            for e in despues["errores_excel"]],
    }


def evaluacion_repeticion(gt: GtAplicable, original: EvaluacionComparador | None,
                          replay: EvaluacionComparador) -> dict[str, Any]:
    """El reporte original y el repetido contra el mismo GT, y el ``delta``.
    Sin reporte original (el run de origen falló en E4 o E5), ``original`` y
    ``delta`` quedan en None."""
    antes = None if original is None else resumen(original)
    despues = resumen(replay)
    return {"gt": gt.ruta.name, "sha256_gt": gt.sha256, "original": antes, "replay": despues,
            "delta": None if antes is None else delta(antes, despues)}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("run_dir", type=Path)
    grupo = p.add_mutually_exclusive_group()
    grupo.add_argument("--gt", type=Path, help="un GT (falla si no es del informe del run)")
    grupo.add_argument("--gt-dir", type=Path, default=GT_DIR_DEFAULT,
                       help="carpeta donde buscar el GT del informe del run")
    p.add_argument("--json", action="store_true", help="resumen en JSON")
    a = p.parse_args()
    try:
        gt = cargar_gt(a.gt) if a.gt else gt_del_run(a.run_dir, a.gt_dir)
        ev = evaluar_run(a.run_dir, gt)
    except GtNoAplicaError as e:
        print(f"GT no aplica: {e}", file=sys.stderr)
        raise SystemExit(2) from e
    except ValueError as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(2) from e
    datos = resumen(ev)
    if a.json:
        print(json.dumps(datos, ensure_ascii=False, indent=1))
        return
    for clave, valor in datos.items():
        print(f"{clave}: {valor}")
    for r in ev.sin_adjudicar:
        print(f"  sin adjudicar: resultado {r.idx} ({r.estado}) {r.motivo} {list(r.candidatos)}")


if __name__ == "__main__":
    main()
