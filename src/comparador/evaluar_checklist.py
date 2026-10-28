"""Evaluación del checklist automático contra una revisión humana (ground truth).

Este módulo cierra el loop de mejora del checklist: cada vez que exista un
"CheckList Revisión *.xlsx" completado por la revisora (SI/NO por ítem), se
puede medir qué tan bien lo hizo el sistema en cualquier run. Cada punto cae
en exactamente una de cuatro categorías:

- **acierto**: el sistema coincide con el humano (cumple↔SI, no_cumple↔NO).
- **no_verificable**: el sistema no encontró evidencia suficiente para
  decidir. No es un error — el badge le dice a la revisora "revisa este punto
  a mano" — pero tampoco ayuda; la meta es reducirlos con mejores hints sin
  generar errores nuevos.
- **falso_no_cumple**: el sistema dijo ``no_cumple`` y el humano dijo SI.
  Error barato: la revisora mira el punto, ve que sí cumple y lo descarta.
  Cuesta tiempo, no riesgo.
- **falso_cumple**: el sistema dijo ``cumple`` y el humano dijo NO. El error
  caro: un incumplimiento real con checkmark verde — si la revisora confía en
  el sistema, pasa al regulador. La meta es 0.

Las categorías no pesan igual. De mejor a peor:
acierto > no_verificable > falso_no_cumple > falso_cumple.

Flujo de mejora (el loop medible):

1. Correr el pipeline sobre un informe que tenga revisión humana.
2. ``python -m comparador.evaluar_checklist <run_id> <checklist_revisado.xlsx>``
3. Mirar los errores duros y conservadores del detalle: ¿el modelo no
   encontró la evidencia (mejorar ``donde_buscar`` en checklist_puntos.yaml),
   la empresa redacta distinto (mejorar su bloque en catalogo_empresas.yaml),
   o el criterio humano es ambiguo (pregunta para la revisora)?
4. Ajustar la configuración, correr de nuevo, volver a medir. Un cambio se
   acepta solo si las métricas no empeoran en NINGÚN informe con ground truth.

El mapeo entre los 38 puntos del sistema y los códigos de ítem del formato de
revisión del CEN vive en ``mapeo_checklist_gt.yaml`` (es fijo: el formato del
CheckList de Revisión no varía por empresa auditora).

Los puntos del GT marcados con valores distintos de SI/NO (vacíos, "N/A",
etc.) se excluyen de la medición y se reportan aparte.
"""

from __future__ import annotations

import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from comparador.config import settings
from comparador.persistence import cargar_json
from comparador.schemas import ChecklistInforme, ReporteInforme, ResultadoChecklist

# Columnas del formato "CheckList Revisión" del CEN (hoja "Check List"):
# código del ítem (p. ej. "4.10"), enunciado, veredicto SI/NO, observaciones.
_COL_CODIGO, _COL_ENUNCIADO, _COL_VEREDICTO, _COL_OBS = 5, 6, 7, 8


@dataclass
class ItemEvaluado:
    """Resultado de la evaluación de un punto del checklist contra el GT."""

    numero: int
    codigo_gt: str
    veredicto_gt: str          # "SI" | "NO"
    resultado_sistema: str     # valor de ResultadoChecklist
    # "acierto" | "no_verificable" | "falso_no_cumple" | "falso_cumple"
    clasificacion: str
    observacion_gt: str


@dataclass
class Evaluacion:
    """Métricas agregadas de un run contra un checklist revisado."""

    run_id: str
    gt_path: str
    items: list[ItemEvaluado] = field(default_factory=list)
    sin_gt: list[int] = field(default_factory=list)  # puntos sin veredicto SI/NO

    def _cuenta(self, clasificacion: str) -> int:
        return sum(1 for i in self.items if i.clasificacion == clasificacion)

    @property
    def aciertos(self) -> int:
        return self._cuenta("acierto")

    @property
    def no_verificables(self) -> int:
        return self._cuenta("no_verificable")

    @property
    def falsos_no_cumple(self) -> int:
        return self._cuenta("falso_no_cumple")

    @property
    def falsos_cumple(self) -> int:
        return self._cuenta("falso_cumple")


def clasificar(resultado: ResultadoChecklist, veredicto_gt: str) -> str:
    """Clasifica un resultado del sistema contra el veredicto humano.

    Devuelve una de las cuatro categorías (ver docstring del módulo).
    Función pura — es el corazón de la métrica y está testeada exhaustivamente.
    """
    esperado = (ResultadoChecklist.CUMPLE if veredicto_gt == "SI"
                else ResultadoChecklist.NO_CUMPLE)
    if resultado == esperado:
        return "acierto"
    if resultado == ResultadoChecklist.NO_VERIFICABLE:
        return "no_verificable"
    if resultado == ResultadoChecklist.CUMPLE:
        return "falso_cumple"
    return "falso_no_cumple"


def cargar_mapeo() -> dict[int, str]:
    """Carga el mapeo punto-del-sistema → código de ítem del GT."""
    texto = (resources.files("comparador") / "mapeo_checklist_gt.yaml").read_text("utf-8")
    mapeo: dict[int, str] = yaml.safe_load(texto)["mapeo"]
    if sorted(mapeo) != list(range(1, 39)):
        raise ValueError("mapeo_checklist_gt.yaml debe cubrir exactamente los puntos 1..38")
    return mapeo


def cargar_gt(ruta_xlsx: Path) -> dict[str, tuple[str, str]]:
    """Lee un "CheckList Revisión" humano → {codigo: (veredicto, observación)}.

    Los códigos duplicados del formato (existe un 7.7 repetido) se
    desambiguan con el sufijo ``#2``, ``#3``, ... por orden de aparición,
    igual que en ``mapeo_checklist_gt.yaml``.
    """
    # keep_default_na=False: pandas convierte "N/A" en NaN por defecto, y un
    # "N/A" explícito del revisor ("no aplica") no es lo mismo que una celda
    # vacía. Ambos siguen fuera de la métrica (sin_gt), pero se ven distintos.
    df = pd.read_excel(ruta_xlsx, sheet_name="Check List", header=None, keep_default_na=False)
    if df.shape[1] <= _COL_OBS:
        raise ValueError(f"No se encontraron ítems en {ruta_xlsx} (¿hoja 'Check List'?)")

    def _texto(valor: Any) -> str:
        return "" if valor is None or pd.isna(valor) else str(valor).strip()

    filas = df[df[_COL_CODIGO].map(_texto).ne("") & df[_COL_ENUNCIADO].map(_texto).ne("")]
    gt: dict[str, tuple[str, str]] = {}
    vistos: Counter[str] = Counter()
    for fila in filas.itertuples(index=False):
        codigo = _texto(fila[_COL_CODIGO]).rstrip(".")
        # "Sí" con tilde debe contar como "SI": sin esto el punto cae a
        # sin_gt en silencio y la métrica se calcula sobre menos puntos.
        # NFC primero: algunos exports traen el acento descompuesto (I + ́ ).
        veredicto = (
            unicodedata.normalize("NFC", _texto(fila[_COL_VEREDICTO])).upper().replace("Í", "I")
        )
        obs = _texto(fila[_COL_OBS])
        vistos[codigo] += 1
        clave = codigo if vistos[codigo] == 1 else f"{codigo}#{vistos[codigo]}"
        gt[clave] = (veredicto, obs)
    if not gt:
        raise ValueError(f"No se encontraron ítems en {ruta_xlsx} (¿hoja 'Check List'?)")
    return gt


def cargar_checklist_run(run_id: str) -> ChecklistInforme:
    """El checklist de un run: el del reporte final o, en un run que corrió solo
    el checklist (sin reporte final), su checklist.json."""
    run_dir = settings.runs_dir / run_id
    if (run_dir / "reporte_final.json").exists():
        reporte = ReporteInforme.model_validate(cargar_json(run_dir / "reporte_final.json"))
        if reporte.checklist is None:
            raise ValueError(f"El run {run_id} no tiene checklist")
        return reporte.checklist
    if (run_dir / "checklist.json").exists():
        return ChecklistInforme.model_validate(cargar_json(run_dir / "checklist.json"))
    raise ValueError(f"El run {run_id} no tiene reporte_final.json ni checklist.json")


def evaluar(run_id: str, ruta_gt: Path) -> Evaluacion:
    """Evalúa el checklist de un run contra un checklist revisado por humano."""
    resultados = {i.numero: i.resultado for i in cargar_checklist_run(run_id).items}

    mapeo = cargar_mapeo()
    gt = cargar_gt(ruta_gt)

    ev = Evaluacion(run_id=run_id, gt_path=str(ruta_gt))
    for numero, codigo in mapeo.items():
        veredicto, obs = gt.get(codigo, ("", ""))
        if veredicto not in ("SI", "NO"):
            ev.sin_gt.append(numero)
            continue
        resultado = resultados[numero]
        ev.items.append(ItemEvaluado(
            numero=numero, codigo_gt=codigo, veredicto_gt=veredicto,
            resultado_sistema=resultado.value,
            clasificacion=clasificar(resultado, veredicto), observacion_gt=obs,
        ))
    return ev


_MARCAS = {"acierto": "✓", "no_verificable": "~",
           "falso_no_cumple": "✗", "falso_cumple": "‼"}


def _imprimir(ev: Evaluacion) -> None:
    print(f"Run: {ev.run_id}")
    print(f"GT:  {ev.gt_path}\n")
    print(f"{'pt':>3} {'GT':>5} {'GT dice':<7} {'sistema':<15} obs")
    for i in ev.items:
        marca = _MARCAS[i.clasificacion]
        extra = "  ← FALSO CUMPLE" if i.clasificacion == "falso_cumple" else ""
        obs = f" [{i.observacion_gt[:50]}]" if i.observacion_gt else ""
        print(f"{i.numero:>3} {i.codigo_gt:>5} {i.veredicto_gt:<7} "
              f"{marca} {i.resultado_sistema:<13}{obs}{extra}")
    if ev.sin_gt:
        print(f"\nSin veredicto SI/NO en el GT (excluidos — el humano no marcó "
              f"SI/NO, típicamente puntos que no aplican): {ev.sin_gt}")
    n = len(ev.items)
    print(f"\nEvaluados: {n}/38")
    print(f"  aciertos:          {ev.aciertos:>2} ({ev.aciertos / n:.0%})  "
          "sistema coincide con el humano")
    print(f"  no verificables:   {ev.no_verificables:>2}       "
          "sistema sin evidencia suficiente para decidir → revisar a mano")
    print(f"  falsos no-cumple:  {ev.falsos_no_cumple:>2}       "
          "sistema: no cumple · humano: SI → error barato, se descarta al revisar")
    print(f"  falsos cumple:     {ev.falsos_cumple:>2}       "
          "sistema: cumple · humano: NO → EL ERROR CARO; la meta es 0")


def main() -> None:
    if len(sys.argv) != 3:
        print("Uso: python -m comparador.evaluar_checklist <run_id> <checklist_revisado.xlsx>")
        raise SystemExit(2)
    _imprimir(evaluar(sys.argv[1], Path(sys.argv[2])))


if __name__ == "__main__":
    main()
