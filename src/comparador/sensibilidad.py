"""M43: errores inyectados en el etapa2 normalizado para medir la sensibilidad del
comparador (decisión del usuario 2026-10-27).

Hoy medimos la precisión del comparador (cuántas alertas son errores reales), no su
sensibilidad: de los errores que trae un Excel, cuántos detecta. Este arnés planta
errores conocidos en copias del etapa2 de un run de B2 y mide cuántos salen como
alerta al repetir E4 con `reproducir_e4`:

1. `aplicar`: un catálogo escrito y congelado ANTES de correr (`Catalogo`) cambia
   filas del etapa2 (el mismo efecto que editar la celda del Excel, sin pasar por E2:
   decisión del usuario). Valida todo y falla ruidosamente.
2. `preparar`: copia del run de B2 con el etapa2 perturbado, en una carpeta que se
   llama como el run_id (así `reproducir_e4 --cache-desde` acepta el control).
3. Corridas con la CLI de `reproducir_e4`: un control sin perturbar y dos pasadas con
   la caché del control (lo que cambió se paga en cada una: dos muestras del juez).
4. `evaluar`: cada error, por pasada, contra el control: detectado, otra alerta,
   escapado (sale «coincide») o no evaluable (el control no daba «coincide»); el
   neutro, sin alerta o falsa alarma; y los cambios fuera de los blancos (ruido).

No es una tasa de errores reales: los tipos que decide el código dan ~100 % por
construcción y los errores sintéticos no son los reales. Todo va en mediciones/m43/
(privado, fuera de b*/ y de replay_e4/: no entra a metricas_lote ni a los golden de
las rondas); el CSV agregado, sin texto, va a docs/metricas/datos/.

    uv run python -m comparador.sensibilidad preparar --catalogo mediciones/m43/catalogo.json \\
        --destino mediciones/m43/runs
    uv run python -m comparador.sensibilidad evaluar --catalogo mediciones/m43/catalogo.json \\
        --control mediciones/m43/control --pasadas mediciones/m43/pasada1 mediciones/m43/pasada2 \\
        --json mediciones/m43/evaluacion.json --csv docs/metricas/datos/sensibilidad_m43.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import string
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from comparador.adjudicacion import ClaveExcel, campos_que_difieren
from comparador.config import PROJECT_ROOT
from comparador.etapa4_matching import clave_tupla
from comparador.schemas import (
    Calificacion,
    EstadoHallazgo,
    Hallazgo,
    MatchResult,
    ReporteInforme,
)

TipoError = Literal["calificacion", "polaridad", "pano", "fila_borrada", "descripcion",
                    "accion", "minimo", "neutro"]
# Quién decide si el error sale como alerta: el código (determinista, ~100 % por
# construcción), la estructura de la tupla (el hallazgo del PDF queda sin su fila:
# es determinista si no le quedan candidatos, y si le quedan, decide el juez), los
# jueces LLM (embeddings, juez de emparejamiento, juez de redacción) o nadie (el
# neutro es un control de falsas alarmas).
DECIDE: dict[str, str] = {
    "calificacion": "codigo", "polaridad": "codigo", "pano": "estructura",
    "fila_borrada": "estructura", "descripcion": "jueces", "accion": "jueces",
    "minimo": "jueces", "neutro": "control",
}
CLASES_ERROR = ("detectado", "otra_alerta", "escapado", "no_evaluable")
CLASES_NEUTRO = ("sin_alerta", "falsa_alarma", "no_evaluable")
ARCHIVOS_DEL_RUN = ("etapa3_pdf_hallazgos.json", "metadata.json", "reporte_final.json",
                    "inputs.json", "version.json", "config_e4.json", "input_excel.hash",
                    "input_informe_original.hash", "input_pdf.hash")
CARPETAS_DEL_RUN = ("etapa4_llm_judge_raw", "etapa4_redaccion_raw")
RUNS_B2 = PROJECT_ROOT / "mediciones" / "b2" / "runs"


class CatalogoInvalidoError(ValueError):
    """El catálogo no se puede aplicar tal como está: se corrige antes de pagar."""


class _Estricto(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Blanco(_Estricto):
    pano: str
    rele: str
    fila: int


class Esperado(_Estricto):
    estado: Literal["difiere", "falta_en_excel", "coincide"]
    campos: list[Literal["descripcion", "accion_correctiva", "calificacion"]] = []


class ErrorInyectado(_Estricto):
    id: str
    informe: str
    run_id: str
    tipo: TipoError
    blanco: Blanco
    # calificacion: el valor nuevo; pano: el paño nuevo; fila_borrada: None; el resto:
    # el texto completo nuevo del campo (descripción, salvo `accion`).
    valor_nuevo: str | None
    esperado: Esperado
    nota: str


class Catalogo(_Estricto):
    version: Literal["1.0"] = "1.0"
    fecha: str
    errores: list[ErrorInyectado]


def cargar_catalogo(ruta: Path) -> Catalogo:
    return Catalogo.model_validate_json(ruta.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------- aplicar


def _neutro(texto: str) -> str:
    """Lo que un cambio neutro puede tocar: espacios, mayúsculas y puntuación."""
    sin_puntuacion = texto.translate(str.maketrans("", "", string.punctuation + "«»“”¿¡"))
    return " ".join(sin_puntuacion.split()).casefold()


def _unidad(hallazgos: list[Hallazgo]) -> set[tuple[str, str]]:
    return {clave_tupla(h.pano, h.rele) for h in hallazgos}


def _texto_crudo(h: Hallazgo, campo: str, nuevo: str) -> str:
    viejo = getattr(h, campo) or ""
    crudo = h.evidencia.texto_crudo
    return crudo.replace(viejo, nuevo) if viejo and viejo in crudo else crudo


def aplicar(etapa2: list[Hallazgo], errores: list[ErrorInyectado]) -> list[Hallazgo]:
    """Copia del etapa2 con los errores aplicados. Falla ruidosamente si un blanco
    no existe, si dos errores comparten unidad (las tuplas de la fila), si un paño
    nuevo ya existe, si el cambio no cambia nada o no es del tipo declarado."""
    tuplas_del_informe = _unidad(etapa2)
    por_fila: dict[int, list[int]] = defaultdict(list)
    for i, h in enumerate(etapa2):
        if not h.es_transversal and h.evidencia.fila_excel is not None:
            por_fila[h.evidencia.fila_excel].append(i)

    salida: list[Hallazgo | None] = list(etapa2)
    ocupadas: dict[tuple[str, str], str] = {}
    for e in errores:
        indices = por_fila.get(e.blanco.fila, [])
        fila = [etapa2[i] for i in indices]
        if clave_tupla(e.blanco.pano, e.blanco.rele) not in _unidad(fila):
            raise CatalogoInvalidoError(
                f"{e.id}: el blanco {e.blanco.pano} / {e.blanco.rele}, fila {e.blanco.fila}, no "
                "existe en el etapa2")
        unidad = _unidad(fila)
        if e.tipo == "pano":
            if len(fila) > 1:
                raise CatalogoInvalidoError(f"{e.id}: `pano` sobre una fila de varios paños")
            assert e.valor_nuevo is not None
            nueva = clave_tupla(e.valor_nuevo, e.blanco.rele)
            if nueva in tuplas_del_informe:
                raise CatalogoInvalidoError(
                    f"{e.id}: el paño nuevo {e.valor_nuevo} ya existe en el informe")
            unidad = unidad | {nueva}
        for tupla in unidad:
            if tupla in ocupadas:
                raise CatalogoInvalidoError(
                    f"{e.id} y {ocupadas[tupla]} caen en la misma unidad {tupla}")
            ocupadas[tupla] = e.id

        for i in indices:
            salida[i] = _cambiar(etapa2[i], e)
    return [h for h in salida if h is not None]


def _cambiar(h: Hallazgo, e: ErrorInyectado) -> Hallazgo | None:
    if e.tipo == "fila_borrada":
        return None
    nuevo = e.valor_nuevo
    if nuevo is None:
        raise CatalogoInvalidoError(f"{e.id}: `{e.tipo}` necesita valor_nuevo")
    if e.tipo == "pano":
        return h.model_copy(update={"pano": nuevo})
    if e.tipo == "calificacion":
        if h.calificacion is None:
            raise CatalogoInvalidoError(f"{e.id}: el informe no tiene columna de calificación")
        calificacion = Calificacion(nuevo)
        if calificacion == h.calificacion:
            raise CatalogoInvalidoError(f"{e.id}: la calificación nueva es igual a la original")
        return h.model_copy(update={"calificacion": calificacion})

    campo = "accion_correctiva" if e.tipo == "accion" else "descripcion"
    viejo = getattr(h, campo)
    if campo == "accion_correctiva" and viejo is None:
        raise CatalogoInvalidoError(f"{e.id}: el informe no tiene columna de acción")
    if nuevo == viejo:
        raise CatalogoInvalidoError(f"{e.id}: el texto nuevo es igual al original")
    if e.tipo == "neutro" and _neutro(nuevo) != _neutro(viejo or ""):
        raise CatalogoInvalidoError(
            f"{e.id}: un cambio neutro solo toca espacios, mayúsculas y puntuación")
    if e.tipo == "polaridad" and not (
            "no cumple" in (viejo or "").casefold() and "no cumple" not in nuevo.casefold()
            and "cumple" in nuevo.casefold()):
        raise CatalogoInvalidoError(f"{e.id}: `polaridad` pasa de «No cumple» a «Cumple»")
    evidencia = h.evidencia.model_copy(update={"texto_crudo": _texto_crudo(h, campo, nuevo)})
    return h.model_copy(update={campo: nuevo, "evidencia": evidencia})


# ---------------------------------------------------------------------- preparar


def preparar(run_b2: Path, errores: list[ErrorInyectado], destino: Path) -> Path:
    """Copia del run con el etapa2 perturbado en destino/<run_id> (nueva)."""
    copia = destino / run_b2.name
    if copia.exists():
        raise FileExistsError(f"{copia} ya existe: no se pisa una preparación")
    etapa2 = [Hallazgo.model_validate(h) for h in json.loads(
        (run_b2 / "etapa2_excel_normalizado.json").read_text(encoding="utf-8"))]
    perturbado = aplicar(etapa2, [e for e in errores if e.run_id == run_b2.name])
    copia.mkdir(parents=True)
    for nombre in ARCHIVOS_DEL_RUN:
        if (run_b2 / nombre).is_file():
            shutil.copy2(run_b2 / nombre, copia / nombre)
    for nombre in CARPETAS_DEL_RUN:
        if (run_b2 / nombre).is_dir():
            shutil.copytree(run_b2 / nombre, copia / nombre)
    (copia / "etapa2_excel_normalizado.json").write_text(
        json.dumps([h.model_dump(mode="json") for h in perturbado], ensure_ascii=False, indent=2),
        encoding="utf-8")
    return copia


# ---------------------------------------------------------------------- evaluar


class ResultadoError(BaseModel):
    id: str
    informe: str
    tipo: str
    decide: str
    # El par del control: «literal» (la descripción del Excel copia la del PDF, salvo
    # espacios y mayúsculas) o «parafrasis»; None si no era evaluable. Se lee por acá,
    # no por auditora: Alfa es Reliable Energy y copia el PDF.
    par_control: str | None
    clases: list[str]   # una por pasada


class Evaluacion(BaseModel):
    pasadas: list[str]
    errores: list[ResultadoError]
    cambios_fuera_de_los_blancos: list[dict[str, Any]]


def _reporte(carpeta: Path, run_id: str) -> list[MatchResult]:
    ruta = carpeta / run_id / "reporte_final.json"
    return ReporteInforme.model_validate_json(ruta.read_text(encoding="utf-8")).resultados


def _de_la_fila(resultados: list[MatchResult], pano: str, rele: str,
                fila: int) -> MatchResult | None:
    clave = ClaveExcel.de(pano, rele, fila)
    encontrados = [r for r in resultados if clave.calza(r.hallazgo_excel)]
    return encontrados[0] if len(encontrados) == 1 else None


def _identidad_pdf(h: Hallazgo) -> tuple[Any, ...]:
    return (clave_tupla(h.pano, h.rele), h.evidencia.pagina_pdf, h.descripcion)


def _del_pdf(resultados: list[MatchResult], h: Hallazgo) -> MatchResult | None:
    encontrados = [r for r in resultados if r.hallazgo_pdf is not None
                   and _identidad_pdf(r.hallazgo_pdf) == _identidad_pdf(h)]
    return encontrados[0] if len(encontrados) == 1 else None


def _clase(e: ErrorInyectado, control: MatchResult | None,
           pasada: list[MatchResult]) -> str:
    if control is None or control.estado != EstadoHallazgo.COINCIDE or control.hallazgo_pdf is None:
        return "no_evaluable"
    if e.tipo in ("fila_borrada", "pano"):
        r = _del_pdf(pasada, control.hallazgo_pdf)
        if r is None or r.estado == EstadoHallazgo.COINCIDE:
            return "escapado"
        if r.estado != EstadoHallazgo.FALTA_EN_EXCEL:
            return "otra_alerta"
        if e.tipo == "pano":
            assert e.valor_nuevo is not None
            extra = _de_la_fila(pasada, e.valor_nuevo, e.blanco.rele, e.blanco.fila)
            if extra is None or extra.estado != EstadoHallazgo.EXTRA_EN_EXCEL:
                return "otra_alerta"
        return "detectado"

    r = _de_la_fila(pasada, e.blanco.pano, e.blanco.rele, e.blanco.fila)
    if e.tipo == "neutro":
        return "sin_alerta" if r is not None and r.estado == EstadoHallazgo.COINCIDE else (
            "falsa_alarma")
    if r is None:
        return "otra_alerta"
    if r.estado == EstadoHallazgo.COINCIDE:
        return "escapado"
    campos = {c.value for c in campos_que_difieren(r)}
    if r.estado.value == e.esperado.estado and set(e.esperado.campos) <= campos:
        return "detectado"
    return "otra_alerta"


def _par_control(r: MatchResult | None) -> str | None:
    if (r is None or r.estado != EstadoHallazgo.COINCIDE or r.hallazgo_pdf is None
            or r.hallazgo_excel is None):
        return None
    iguales = (" ".join(r.hallazgo_pdf.descripcion.split()).casefold()
               == " ".join(r.hallazgo_excel.descripcion.split()).casefold())
    return "literal" if iguales else "parafrasis"


def _firma(r: MatchResult) -> tuple[Any, ...]:
    otro = (r.hallazgo_excel.evidencia.fila_excel if r.hallazgo_excel else None,
            _identidad_pdf(r.hallazgo_pdf) if r.hallazgo_pdf else None)
    return (r.estado.value, tuple(c.value for c in campos_que_difieren(r)), otro)


def _clave_resultado(r: MatchResult) -> tuple[Any, ...]:
    if r.hallazgo_excel is not None and r.hallazgo_excel.evidencia.fila_excel is not None:
        return ("excel", clave_tupla(r.pano, r.rele), r.hallazgo_excel.evidencia.fila_excel)
    assert r.hallazgo_pdf is not None
    return ("pdf", *_identidad_pdf(r.hallazgo_pdf))


def _cambios_fuera(errores: list[ErrorInyectado], control: list[MatchResult],
                   pasada: list[MatchResult]) -> int:
    # La unidad de cada error: todas las tuplas de su fila (una fila de varios paños
    # da un hallazgo por paño, y el error los cambia a todos) y, con `pano`, la nueva.
    filas = {e.blanco.fila for e in errores}
    blancos = {clave_tupla(r.pano, r.rele) for r in control
               if r.hallazgo_excel is not None and r.hallazgo_excel.evidencia.fila_excel in filas}
    for e in errores:
        blancos.add(clave_tupla(e.blanco.pano, e.blanco.rele))
        if e.tipo == "pano" and e.valor_nuevo:
            blancos.add(clave_tupla(e.valor_nuevo, e.blanco.rele))
    antes = {_clave_resultado(r): _firma(r) for r in control
             if clave_tupla(r.pano, r.rele) not in blancos}
    despues = {_clave_resultado(r): _firma(r) for r in pasada
               if clave_tupla(r.pano, r.rele) not in blancos}
    return sum(antes.get(k) != despues.get(k) for k in set(antes) | set(despues))


def evaluar(errores: list[ErrorInyectado], control: Path, pasadas: list[Path]) -> Evaluacion:
    """Cada error, por pasada, contra el control (las carpetas tienen <run_id>/)."""
    run_ids = sorted({e.run_id for e in errores})
    reportes_control = {r: _reporte(control, r) for r in run_ids}
    reportes = {p.name: {r: _reporte(p, r) for r in run_ids} for p in pasadas}
    resultados = []
    for e in errores:
        r_control = _de_la_fila(reportes_control[e.run_id], e.blanco.pano, e.blanco.rele,
                                e.blanco.fila)
        resultados.append(ResultadoError(
            id=e.id, informe=e.informe, tipo=e.tipo, decide=DECIDE[e.tipo],
            par_control=_par_control(r_control),
            clases=[_clase(e, r_control, reportes[p.name][e.run_id]) for p in pasadas]))
    cambios = [{"pasada": p.name, "cambios": sum(
        _cambios_fuera([e for e in errores if e.run_id == r], reportes_control[r],
                       reportes[p.name][r]) for r in run_ids)} for p in pasadas]
    return Evaluacion(pasadas=[p.name for p in pasadas], errores=resultados,
                      cambios_fuera_de_los_blancos=cambios)


COLUMNAS_CSV = ("tipo", "decide", "informe", "par_control", "pasada", "errores", "evaluables",
                "detectados", "otra_alerta", "escapados", "sin_alerta", "falsas_alarmas")


def filas_csv(ev: Evaluacion) -> list[dict[str, Any]]:
    """Agregado por tipo × informe × par del control × pasada, sin texto de los informes."""
    grupos: dict[tuple[str, str, str, str, str], list[str]] = defaultdict(list)
    for r in ev.errores:
        for pasada, clase in zip(ev.pasadas, r.clases, strict=True):
            grupos[(r.tipo, r.decide, r.informe, r.par_control or "", pasada)].append(clase)
    return [dict(zip(COLUMNAS_CSV, (
        tipo, decide, informe, par, pasada, len(clases),
        sum(c != "no_evaluable" for c in clases), clases.count("detectado"),
        clases.count("otra_alerta"), clases.count("escapado"), clases.count("sin_alerta"),
        clases.count("falsa_alarma")), strict=True))
        for (tipo, decide, informe, par, pasada), clases in sorted(grupos.items())]


def escribir_csv(ev: Evaluacion, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS_CSV)
        w.writeheader()
        w.writerows(filas_csv(ev))


# ---------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="accion", required=True)
    pre = sub.add_parser("preparar", help="copias de los runs de B2 con el etapa2 perturbado")
    pre.add_argument("--catalogo", type=Path, required=True)
    pre.add_argument("--runs-b2", type=Path, default=RUNS_B2)
    pre.add_argument("--destino", type=Path, required=True)
    ev = sub.add_parser("evaluar", help="clasifica cada error contra el control")
    ev.add_argument("--catalogo", type=Path, required=True)
    ev.add_argument("--control", type=Path, required=True)
    ev.add_argument("--pasadas", type=Path, nargs="+", required=True)
    ev.add_argument("--json", type=Path, required=True)
    ev.add_argument("--csv", type=Path, required=True)
    a = p.parse_args(argv)

    catalogo = cargar_catalogo(a.catalogo)
    if a.accion == "preparar":
        try:
            for run_id in sorted({e.run_id for e in catalogo.errores}):
                print(preparar(a.runs_b2 / run_id, catalogo.errores, a.destino), flush=True)
        except (CatalogoInvalidoError, FileExistsError) as exc:
            sys.exit(str(exc))
        return
    resultado = evaluar(catalogo.errores, a.control, a.pasadas)
    a.json.parent.mkdir(parents=True, exist_ok=True)
    a.json.write_text(resultado.model_dump_json(indent=2), encoding="utf-8")
    escribir_csv(resultado, a.csv)
    for r in resultado.errores:
        print(f"{r.id:>8} {r.tipo:<13} {r.informe:<10} {' '.join(r.clases)}")


if __name__ == "__main__":
    main()
