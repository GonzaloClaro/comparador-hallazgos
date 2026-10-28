"""Confianza, sensibilidad, estabilidad y versión de las métricas del checklist.

Complementa ``metricas_lote`` (que las escribe como CSV) para que
``docs/04_metricas.md`` diga cuánto confiar en cada cifra sin prometer de más:

- ``filas_confianza_checklist``: aciertos con intervalo de Wilson al 95 % y un
  bootstrap que remuestrea INFORMES (los puntos de un mismo informe no son
  independientes: comparten PDF, auditora y revisor). Con 6 informes el
  bootstrap es ancho y así se reporta. Además (M42) la matriz 2×3 (SI/NO de la
  planilla × cumple, no verificable, no cumple), la TNR, la TPR con Wilson y el
  falso cumple sobre los NO con Wilson y cota por regla de tres, separado dentro
  y fuera de muestra (M39, columna ``muestra`` de cada punto).
- Escenarios ``planilla_al_medir`` (el GT tal como lo leyó cada ronda) y
  ``planilla_corregida``: las celdas que contradecían el criterio del equipo revisor se
  corrigieron en las planillas el 2026-10-17, después de B0–B2
  (tasks/equipo/respuestas_v3_celdas.md: motivo, respaldo y hashes). Las rondas
  ya medidas guardan el valor viejo; este escenario les aplica el nuevo.
- ``filas_falsos_cumple``: cada falso cumple con su causa conocida.
- ``filas_estabilidad_checklist``: entre B1 y B2, en los puntos cuyo enunciado y
  criterio NO cambiaron, cuántas veces el mismo modelo dio el mismo resultado
  (lo que cambia ahí es variabilidad del modelo, no de la solución).
- ``filas_ficha_version``: hash del código medido en cada ronda y del actual.
"""

from __future__ import annotations

import math
import random
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from comparador.etapa0_checklist import cargar_puntos
from comparador.evaluar_checklist import clasificar
from comparador.persistence import hash_arbol
from comparador.schemas import ResultadoChecklist

# Celdas corregidas en las planillas el 2026-10-17 por contradecir el criterio del equipo revisor:
# (informe, punto) → veredicto nuevo. Motivo, respaldo y hashes en
# tasks/equipo/respuestas_v3_celdas.md. Las mediciones B0–B2 se hicieron con el valor viejo.
CELDAS_GT_CORREGIDAS: dict[tuple[str, int], str] = {
    ("beta", 6): "SI",
    ("epsilon", 9): "SI",
    ("epsilon", 23): "SI",
}
# Punto → preguntas abiertas al equipo revisor (tasks/equipo/preguntas_v3.md). Fuente única: el
# bloque `origen` de checklist_puntos.yaml (PD68). Solo da la referencia; la causa la deciden
# los casos explícitos de abajo.
PREGUNTAS_ABIERTAS: dict[int, tuple[str, ...]] = {
    p["numero"]: tuple(p["origen"]["preguntas"])
    for p in cargar_puntos() if p["origen"]["preguntas"]
}
# Falsos cumple ya diagnosticados como dependientes de esas preguntas: (ronda, informe,
# punto). Explícitos, sin comodín: un falso cumple nuevo en esos puntos (otra ronda u otro
# informe) queda "sin explicación conocida" hasta diagnosticarlo.
# Gamma 6 falló en B0, B1 y B2 (no en todos los modelos). De la causa, solo «que el informe
# muestre» el DUF son palabras del equipo revisor; leerlo como «dentro del PDF» es redacción
# nuestra del 2026-10-17, sin confirmar. La v3 (Parte 7) le dijo al equipo revisor que queda
# pendiente de P1: con A sería un error del sistema; con B, una celda a corregir (PD68, D1).
FALSOS_CUMPLE_POR_PREGUNTA_ABIERTA: frozenset[tuple[str, str, int]] = frozenset({
    ("B0", "epsilon", 10), ("B1", "epsilon", 10), ("B2", "epsilon", 10),
    ("B0", "epsilon", 32), ("B2", "epsilon", 30),
    ("B0", "gamma", 6), ("B1", "gamma", 6), ("B2", "gamma", 6),
})
# Casos cuyo diagnóstico apunta solo a algunas de las preguntas del punto (decisión del usuario
# 2026-10-26); los demás llevan todas. Epsilon tiene función 21: su 32 depende de P11, no de P6
# (lo que no existe) ni de P13 (anexos).
PREGUNTAS_DEL_CASO: dict[tuple[str, str, int], tuple[str, ...]] = {
    ("B0", "epsilon", 32): ("P11",),
}
# Errores del sistema ya diagnosticados y corregidos: (ronda, informe o "*", punto). La ronda
# siempre va explícita: una corrección no puede explicar fallas de rondas posteriores a ella.
# Se evalúan ANTES que las celdas del GT y las preguntas abiertas.
ERRORES_SISTEMA_CORREGIDOS: dict[tuple[str, str, int], str] = {
    ("B0", "*", 17): "hint 17 aceptaba tablas de tiempos como corrientes; corregido en B1 "
                     "(tasks/todo.md, Bloque 21)",
    ("B2", "beta", 22): "hint 22 creaba una 2a excepción a 'levantado = cumple' (invariante "
                          "19d); corregido después de B2 (tasks/lessons.md, 2026-10-17)",
}
ESCENARIOS = ("planilla_al_medir", "planilla_corregida")
# Puntos de los anexos (docs/04_metricas.md §2.4): sus errores no entran a M09 (PD20).
PUNTOS_ANEXOS = (26, 27, 28, 32)
# Matriz 2×3 del checklist (M42): veredicto de la planilla × resultado del sistema.
CELDAS_MATRIZ = (
    "gt_si_cumple", "gt_si_no_verificable", "gt_si_no_cumple",
    "gt_no_cumple", "gt_no_no_verificable", "gt_no_no_cumple",
)
_Z95 = 1.959964
_REMUESTREOS = 2000
_SEMILLA = 2026


def clave_informe(nombre: str) -> str:
    """'Zeta' / 'Añañuca' / 'Gamma' → 'zeta' / 'ananuca' / 'gamma'."""
    sin_tildes = unicodedata.normalize("NFKD", nombre)
    return "".join(c for c in sin_tildes if not unicodedata.combining(c)).casefold().strip()


def wilson(k: int, n: int, z: float = _Z95) -> tuple[float, float]:
    """Intervalo de Wilson para una proporción k/n (n > 0)."""
    if n <= 0:
        raise ValueError("n debe ser positivo")
    p = k / n
    den = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / den
    margen = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centro - margen), min(1.0, centro + margen)


def bootstrap_por_informe(
    por_informe: list[tuple[int, int]], remuestreos: int = _REMUESTREOS, semilla: int = _SEMILLA
) -> tuple[float, float]:
    """Percentiles 2.5 y 97.5 de la proporción agregada remuestreando informes."""
    rng = random.Random(semilla)
    m = len(por_informe)
    valores = []
    for _ in range(remuestreos):
        muestra = [por_informe[rng.randrange(m)] for _ in range(m)]
        n = sum(t for _, t in muestra)
        valores.append(sum(k for k, _ in muestra) / n)
    valores.sort()
    return valores[int(0.025 * remuestreos)], valores[int(0.975 * remuestreos) - 1]


def veredicto_escenario(informe: str, punto: int, veredicto: str, escenario: str) -> str:
    if escenario == "planilla_corregida":
        return CELDAS_GT_CORREGIDAS.get((clave_informe(informe), punto), veredicto)
    return veredicto


def _pct(x: float) -> float:
    return round(100 * x, 1)


def _tasas_matriz(matriz: dict[str, int]) -> dict[str, Any]:
    """TNR, TPR con Wilson y falso cumple sobre los NO con Wilson y cota (M42).

    Orden de lectura: primero el falso cumple sobre los NO (el error caro), después
    la TPR y después los no verificables. Sin veredictos NO (o SI) las tasas
    sobre ellos quedan vacías. Con 0 falsos cumple, la regla de tres acota la
    tasa bajo 3/n (100 % si n < 3).
    """
    si = matriz["gt_si_cumple"] + matriz["gt_si_no_verificable"] + matriz["gt_si_no_cumple"]
    no = matriz["gt_no_cumple"] + matriz["gt_no_no_verificable"] + matriz["gt_no_no_cumple"]
    tasas: dict[str, Any] = {
        "veredictos_si_gt": si,
        "pct_tnr": _pct(matriz["gt_si_cumple"] / si) if si else "",
        "pct_tpr": "", "tpr_wilson95_inf": "", "tpr_wilson95_sup": "",
        "falso_cumple_wilson95_inf": "", "falso_cumple_wilson95_sup": "",
        "falso_cumple_cota_regla_de_tres": "",
    }
    if no:
        tp_lo, tp_hi = wilson(matriz["gt_no_no_cumple"], no)
        fc_lo, fc_hi = wilson(matriz["gt_no_cumple"], no)
        tasas |= {
            "pct_tpr": _pct(matriz["gt_no_no_cumple"] / no),
            "tpr_wilson95_inf": _pct(tp_lo), "tpr_wilson95_sup": _pct(tp_hi),
            "falso_cumple_wilson95_inf": _pct(fc_lo), "falso_cumple_wilson95_sup": _pct(fc_hi),
            "falso_cumple_cota_regla_de_tres": (
                _pct(min(1.0, 3 / no)) if matriz["gt_no_cumple"] == 0 else ""),
        }
    return tasas


def filas_confianza_checklist(por_punto: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Por escenario × ronda × modelo × muestra (dentro o fuera de muestra, M39),
    sobre los informes con checklist revisado."""
    filas: list[dict[str, Any]] = []
    for escenario in ESCENARIOS:
        grupos: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for p in por_punto:
            grupos[(p["ronda"], p["modelo"], p.get("muestra", ""))].append(p)
        for (ronda, modelo, muestra), puntos in sorted(grupos.items()):
            clases: dict[str, int] = defaultdict(int)
            matriz = dict.fromkeys(CELDAS_MATRIZ, 0)
            por_informe: dict[str, list[int]] = defaultdict(lambda: [0, 0])
            veredictos_no = detectados = 0
            for p in puntos:
                veredicto = veredicto_escenario(
                    p["informe"], int(p["punto"]), p["veredicto_gt"], escenario
                )
                if veredicto not in ("SI", "NO"):
                    raise ValueError(f"Veredicto de la planilla desconocido: {veredicto!r} "
                                     f"({p['informe']}, punto {p['punto']})")
                resultado = ResultadoChecklist(p["resultado"])
                clase = clasificar(resultado, veredicto)
                clases[clase] += 1
                matriz[f"gt_{veredicto.lower()}_{resultado.value}"] += 1
                por_informe[p["informe"]][1] += 1
                if clase == "acierto":
                    por_informe[p["informe"]][0] += 1
                if veredicto == "NO":
                    veredictos_no += 1
                    detectados += p["resultado"] == "no_cumple"
            n, k = len(puntos), clases["acierto"]
            lo, hi = wilson(k, n)
            pares = [(a, t) for a, t in por_informe.values()]
            b_lo, b_hi = bootstrap_por_informe(pares)
            tasas = [a / t for a, t in pares]
            filas.append({
                "escenario": escenario, "ronda": ronda, "modelo": modelo,
                "informes": len(pares), "evaluados": n, "aciertos": k,
                "pct_aciertos": _pct(k / n),
                "wilson95_inf": _pct(lo), "wilson95_sup": _pct(hi),
                "bootstrap95_inf": _pct(b_lo), "bootstrap95_sup": _pct(b_hi),
                "peor_informe_pct": _pct(min(tasas)), "mejor_informe_pct": _pct(max(tasas)),
                "no_verificables": clases["no_verificable"],
                "falsos_no_cumple": clases["falso_no_cumple"],
                "falsos_cumple": clases["falso_cumple"],
                "veredictos_no_gt": veredictos_no,
                "incumplimientos_detectados": detectados,
                "tasa_falso_cumple_sobre_no": (
                    _pct(clases["falso_cumple"] / veredictos_no) if veredictos_no else ""
                ),
                **matriz, **_tasas_matriz(matriz), "muestra": muestra,
            })
    return filas


def causa_falso_cumple(ronda: str, informe: str, punto: int) -> tuple[str, str]:
    """(causa, referencia) de un falso cumple según lo que sabemos hoy."""
    inf = clave_informe(informe)
    for clave in ((ronda, inf, punto), (ronda, "*", punto)):
        if clave in ERRORES_SISTEMA_CORREGIDOS:
            return "error_del_sistema_corregido", ERRORES_SISTEMA_CORREGIDOS[clave]
    if (inf, punto) in CELDAS_GT_CORREGIDAS:
        return ("celda_gt_contradice_criterio_equipo",
                "tasks/equipo/respuestas_v3_celdas.md (corregida en la planilla el 2026-10-17)")
    if (ronda, inf, punto) in FALSOS_CUMPLE_POR_PREGUNTA_ABIERTA:
        seccion = "; ".join(PREGUNTAS_DEL_CASO.get((ronda, inf, punto), PREGUNTAS_ABIERTAS[punto]))
        return "criterio_abierto_pregunta_equipo", f"tasks/equipo/preguntas_v3.md {seccion}"
    return "sin_explicacion_conocida", ""


def filas_falsos_cumple(por_punto: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filas = []
    for p in por_punto:
        if p["clasificacion"] != "falso_cumple":
            continue
        causa, ref = causa_falso_cumple(p["ronda"], p["informe"], int(p["punto"]))
        filas.append({
            "ronda": p["ronda"], "modelo": p["modelo"], "informe": p["informe"],
            "punto": p["punto"], "codigo_gt": p["codigo_gt"], "causa": causa, "referencia": ref,
        })
    return filas


def _prompts_checklist(src: Path) -> dict[int, tuple[str, str]]:
    datos = yaml.safe_load((src / "comparador" / "checklist_puntos.yaml").read_text("utf-8"))
    return {
        int(p["numero"]): (str(p["enunciado"]), str(p["donde_buscar"]))
        for p in datos["puntos"]
    }


def _system_checklist(src: Path) -> str:
    """Texto de SYSTEM_CHECKLIST tal como está escrito en prompts.py de esa copia."""
    texto = (src / "comparador" / "llm" / "prompts.py").read_text("utf-8")
    inicio = texto.index("SYSTEM_CHECKLIST")
    fin = texto.index('"""', texto.index('"""', inicio) + 3)
    return texto[inicio:fin]


def filas_estabilidad_checklist(
    mediciones: Path, por_punto: list[dict[str, Any]], de: str = "B1", a: str = "B2"
) -> list[dict[str, Any]]:
    """Mismo modelo, mismo informe, mismo punto con prompt idéntico: ¿mismo resultado?"""
    src_de, src_a = mediciones / de.lower() / "src", mediciones / a.lower() / "src"
    prompts_de, prompts_a = _prompts_checklist(src_de), _prompts_checklist(src_a)
    sin_cambio = {n for n in prompts_de if prompts_de[n] == prompts_a.get(n)}
    system_igual = _system_checklist(src_de) == _system_checklist(src_a)
    resultado: dict[tuple[str, str, str, int], str] = {}
    for p in por_punto:
        resultado[(p["ronda"], p["modelo"], p["informe"], int(p["punto"]))] = p["resultado"]
    filas = []
    for modelo in sorted({p["modelo"] for p in por_punto}):
        comparados = iguales = 0
        for (ronda, mod, informe, punto), res in resultado.items():
            if ronda != de or mod != modelo or punto not in sin_cambio:
                continue
            otro = resultado.get((a, modelo, informe, punto))
            if otro is None:
                continue
            comparados += 1
            iguales += res == otro
        filas.append({
            "de": de, "a": a, "modelo": modelo,
            "puntos_con_prompt_sin_cambio": len(sin_cambio),
            "system_prompt_checklist_igual": system_igual,
            "comparaciones": comparados, "mismo_resultado": iguales,
            "pct_mismo_resultado": _pct(iguales / comparados) if comparados else "",
        })
    return filas


def _archivos_de_codigo(src: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(src)): p.read_bytes()
        for p in src.rglob("*") if p.is_file() and p.suffix in (".py", ".yaml")
        and "__pycache__" not in p.parts
    }


def _version_runs(registrados: list[str], h: str | None) -> str:
    """sin_registro (la ronda no registró qué código corrió: B0-B2), sin_src (lo
    registró pero no trae su copia), igual o distinta (frente a su copia)."""
    if not registrados:
        return "sin_registro"
    if h is None:
        return "sin_src"
    return "igual" if all(x == h for x in registrados) else "distinta"


def filas_ficha_version(
    mediciones: Path, rondas_meta: list[tuple[str, str, list[str], Path]], src_actual: Path,
    registrados: dict[str, tuple[list[str], str]] | None = None,
) -> list[dict[str, Any]]:
    """Una fila por ronda (hash del código medido) más una para el código actual.

    ``rondas_meta``: (etiqueta, fecha de la evaluación, modelos medidos, carpeta
    de la ronda). El código medido es la copia ``src/`` de la carpeta de la
    ronda (``b3s`` puede llamarse distinto que su etiqueta). Sin esa copia, la
    columna ``src`` dice «falta» y no hay hash: el de un árbol vacío haría
    parecer atribuible una ronda que no lo es.

    ``registrados``, por etiqueta: (sha256_codigo que registraron los runs de la
    evaluación, sha256 de la copia congelada verificada al lanzar o ""). La
    columna ``version_runs`` los contrasta con el hash de la copia
    (``_version_runs``): «distinta» es una discrepancia para metricas_lote.
    """
    h_actual, n_actual = hash_arbol(src_actual)
    actuales = _archivos_de_codigo(src_actual)
    filas: list[dict[str, Any]] = []
    for etiqueta, fecha, modelos, directorio in rondas_meta:
        src = directorio / "src"
        runs, congelado = (registrados or {}).get(etiqueta, ([], ""))
        base = {"version": etiqueta, "fecha": fecha, "modelos": ";".join(modelos)}
        registro = {"sha256_codigo_runs": ";".join(runs), "sha256_codigo_congelado": congelado}
        todos = [*runs, *([congelado] if congelado else [])]
        if not src.is_dir():
            filas.append({**base, "sha256_codigo": "", "archivos": "",
                          "archivos_distintos_del_actual": "", "distintos": "", "src": "falta",
                          **registro, "version_runs": _version_runs(todos, None)})
            continue
        h, n = hash_arbol(src)
        medidos = _archivos_de_codigo(src)
        distintos = sorted(
            k for k in set(medidos) | set(actuales) if medidos.get(k) != actuales.get(k)
        )
        filas.append({
            **base, "sha256_codigo": h[:16], "archivos": n,
            "archivos_distintos_del_actual": len(distintos),
            "distintos": ";".join(distintos), "src": src.relative_to(mediciones).as_posix(),
            **registro, "version_runs": _version_runs(todos, h[:16]),
        })
    filas.append({
        "version": "actual", "fecha": "", "modelos": "", "sha256_codigo": h_actual[:16],
        "archivos": n_actual, "archivos_distintos_del_actual": 0, "distintos": "",
        "src": src_actual.name,
    })
    return filas
