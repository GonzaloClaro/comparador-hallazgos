"""PD71 V2 sobre lo guardado de AG1, sin API (decisión del usuario 2026-10-25).

Con la asignación global, el par que termina con una fila que perdió un
hallazgo de polaridad opuesta a ella cuenta como dudoso para 19e(c): sus
campos bajo el umbral no van al juez de redacción y salen «difiere», y desde el
schema 0.9.0 lleva el motivo en `emparejamiento_dudoso` y suma a «requieren
revisión», como un semantico_bajo. La marca
es de la fila (también si al hallazgo opuesto le rechazaron el pedido); en AG1
da lo mismo que la V2 simulada, que solo miraba al desplazado: ningún hallazgo
de polaridad opuesta perdió una fila por rechazo y la fila 69 de E7 no cambió
de manos después. La simulación de PD71 (`mediciones/scripts_offline/bloque24/pd71_simulacion.py`,
salida `pd71_simulacion.json`) calculó qué cambiaría en las 5 repeticiones de
AG1 (`mediciones/replay_e4/AG1/<run_id>/`); acá corre el código de E4 y E5 de
hoy sobre lo mismo y debe dar la variante V2 de la simulación.

Cada repetición se rehace con la configuración que registró AG1
(ASIGNACION_GLOBAL=true), los hallazgos de su run de origen de B2, los vectores
de D1 y los jueces de AG1, sin llamar a ninguna API:
- juez de matching: la caché estricta con los raw de AG1 (V2 actúa en 4e y no
  cambia ningún prompt de matching);
- juez de redacción: el veredicto que AG1 guardó para cada ítem (campo, paño,
  relé, clasificación y los dos textos). La caché por prompt no alcanza: el
  campo que V2 saca del juez sale de su lote, que cambia (y con él los lotes de
  15 que le siguen), y esos prompts no están guardados; pedirlos sería pagar.
  Responder cada ítem con lo guardado es el mismo supuesto de la simulación
  («los demás veredictos quedan como están guardados»). Donde V2 no saca nada,
  cada lote pedido es idéntico a uno guardado: la repetición es estricta.

Se exige, por repetición: que los únicos ítems guardados que nadie pide sean los
campos de los pares dudosos que en AG1 fueron al juez; que frente al reporte de
AG1 cambien exactamente los resultados de la variante V2 (y nada más de esos
resultados); que `emparejamiento_dudoso` lo lleven exactamente los pares dudosos
de V2; y que el resumen del reporte, la evaluación contra el GT y el golden de
los errores no mostrados sean los de V2. La simulación es anterior al campo: su
«requieren revisión» no cuenta los pares dudosos de confianza alta, y acá se suman.
La evaluación es contra el GT con que corrió la simulación (su sha256): el GT se
completa por rondas sin mover lo de antes, así que se rearma con las rondas hasta
la de la simulación (desde AG2, el de Alfa suma i137 y su sha256 cambia).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

import pytest

from comparador.cache_jueces import CacheJueces, leer_raws
from comparador.config import settings
from comparador.etapa4_matching import (
    _JuezRedaccionResponse,
    _JuezResponse,
    _VeredictoRedaccion,
    clave_tupla,
    ejecutar_matching,
)
from comparador.etapa5_consolidar import consolidar_reporte
from comparador.evaluar_comparador import (
    GT_DIR_DEFAULT,
    GtAplicable,
    evaluar,
    gt_aplicable,
    gts_de,
    resumen,
)
from comparador.gt_comparador import GtInforme, construir_gt, hashes_del_run, serializar
from comparador.llm.prompts import SYSTEM_JUEZ_REDACCION
from comparador.persistence import cargar_vectores
from comparador.reproducir_e4 import _items_redaccion
from comparador.schemas import Hallazgo, MatchResult, MetadatosInforme, ReporteInforme, TipoMatch
from tests.golden.datos import MEDICIONES, leer_json, requiere_mediciones, subestacion
from tests.golden.test_golden_errores_no_mostrados import (
    ERRORES,
    exencion_del_run,
    verificar_error,
)

pytestmark = [pytest.mark.golden, requiere_mediciones]

AG1 = MEDICIONES / "replay_e4" / "AG1"
SIMULACION = MEDICIONES / "scripts_offline" / "bloque24" / "pd71_simulacion.json"
VECTORES_B2 = MEDICIONES / "b2" / "vectores_e4"
RUNS = sorted(p.parent.name for p in AG1.glob("*/metadata.json"))
EXENTO = "exento: sin la repetición AG1 o la simulación de PD71"
# Lo que AG1 registró de la configuración de E4 (además de la asignación global).
CONFIG_E4 = ("modelo_extraccion", "modelo_juez_matching", "modelo_embeddings", "juez_redaccion",
             "top_k_candidatos", "threshold_descripcion", "threshold_accion", "effort_llm")


def _parametros() -> list[Any]:
    if not RUNS or not SIMULACION.is_file():
        return [pytest.param(None, id="sin-AG1", marks=pytest.mark.skip(reason=EXENTO))]
    return [pytest.param(r, id=r) for r in RUNS]


def _clave_item(item: dict[str, Any]) -> tuple[Any, ...]:
    return (item["campo"], item["pano"], item["rele"], item["clasificacion"],
            item["texto_pdf"], item["texto_excel"])


class JuecesDeAG1:
    """Los dos jueces de AG1 sin API (ver el docstring del módulo)."""

    def __init__(self, carpeta: Path) -> None:
        raws = leer_raws(carpeta)
        assert not raws.fallidas and not raws.de_respaldo
        redaccion = [r for r in raws.respuestas
                     if r.clave.response_model == _JuezRedaccionResponse.__name__]
        self.matching = CacheJueces(
            [r for r in raws.respuestas if r.clave.response_model == _JuezResponse.__name__],
            modo="estricto")
        self.modelos = {r.clave.modelo for r in redaccion}
        self.prompts: Counter[str] = Counter(r.raw["user_prompt_text"] for r in redaccion)
        # Ítem → (veredicto, (tupla, campo, página, fila) de la traza del lote), en orden.
        self.guardados: dict[tuple[Any, ...], deque[tuple[dict[str, Any], tuple[Any, ...]]]] = (
            defaultdict(deque))
        for r in redaccion:
            assert r.raw["system_prompt"] == SYSTEM_JUEZ_REDACCION
            veredictos = {v["id"]: v for v in r.raw["response_raw"]["veredictos"]}
            trazas = {t["id"]: t for t in r.raw["lote"]}
            for item in _items_redaccion(r.raw["user_prompt_text"]):
                t = trazas[item["id"]]
                self.guardados[_clave_item(item)].append((veredictos[item["id"]], (
                    clave_tupla(t["pano"], t["rele"]), t["campo"], t["pagina_pdf"],
                    t["fila_excel"])))
        self.lotes_identicos = 0
        self.lotes_nuevos = 0

    def __call__(self, **kw: Any) -> tuple[Any, dict[str, Any]]:
        if kw["response_model"] is not _JuezRedaccionResponse:
            return self.matching(**kw)
        assert kw["system_prompt"] == SYSTEM_JUEZ_REDACCION and {kw["modelo"]} == self.modelos
        if self.prompts[kw["user_prompt"]] > 0:
            self.prompts[kw["user_prompt"]] -= 1
            self.lotes_identicos += 1
        else:
            self.lotes_nuevos += 1
        veredictos = []
        for item in _items_redaccion(kw["user_prompt"]):
            cola = self.guardados.get(_clave_item(item))
            assert cola, f"AG1 no adjudicó el ítem {item['pano']}/{item['rele']} {item['campo']}"
            guardado, _ = cola.popleft()
            veredictos.append(_VeredictoRedaccion(
                id=item["id"], justificacion=guardado["justificacion"],
                mismo_contenido=guardado["mismo_contenido"]))
        return _JuezRedaccionResponse(veredictos=veredictos), {"modelo": kw["modelo"]}

    def sin_pedir(self) -> list[tuple[Any, ...]]:
        return sorted(traza for cola in self.guardados.values() for _, traza in cola)


def _repetir(run_id: str, monkeypatch: pytest.MonkeyPatch) -> tuple[ReporteInforme, JuecesDeAG1]:
    carpeta, origen = AG1 / run_id, MEDICIONES / "b2" / "runs" / run_id
    meta = leer_json(carpeta / "metadata.json")
    assert (meta["modo"], meta["run_origen"], meta["asignacion_global"]) == (
        "replay_e4", run_id, True)
    for campo in CONFIG_E4:
        monkeypatch.setattr(settings, campo, "" if meta[campo] is None else meta[campo])
    monkeypatch.setattr(settings, "asignacion_global", True)
    # AG1 y AG2 corrieron sin M30 (encendido por defecto desde el 2026-10-27).
    monkeypatch.setattr(settings, "descripcion_identica", False)
    # Ni con el control de códigos (M28 V2, encendido por defecto desde el 2026-10-27).
    monkeypatch.setattr(settings, "control_codigos", False)
    # Ni las copias unificadas (M34, encendido por defecto desde el 2026-10-27).
    monkeypatch.setattr(settings, "unificar_copias", False)
    hallazgos_pdf = [Hallazgo.model_validate(h)
                     for h in leer_json(origen / "etapa3_pdf_hallazgos.json")]
    hallazgos_excel = [Hallazgo.model_validate(h)
                       for h in leer_json(origen / "etapa2_excel_normalizado.json")]
    vectores, modelo = cargar_vectores(VECTORES_B2 / f"{run_id}.npz")
    assert modelo == meta["modelo_embeddings"]
    jueces = JuecesDeAG1(carpeta)

    resultados, _ = ejecutar_matching(hallazgos_pdf, hallazgos_excel, vectores=dict(vectores),
                                      vectores_estrictos=True, llamar=jueces)

    ag1 = _reporte_ag1(run_id)
    metadatos = MetadatosInforme(
        coordinado=ag1.coordinado, subestacion=ag1.subestacion, informe_id=ag1.informe_id,
        fecha_auditoria=ag1.fecha_auditoria, columnas_ausentes=ag1.columnas_ausentes_excel)
    return consolidar_reporte(resultados, metadatos, ag1.empresa_auditora, ag1.checklist), jueces


def _reporte_ag1(run_id: str) -> ReporteInforme:
    return ReporteInforme.model_validate(leer_json(AG1 / run_id / "reporte_final.json"))


def _clave_par(r: MatchResult) -> str:
    lados = [None if h is None else h.model_dump(mode="json")
             for h in (r.hallazgo_pdf, r.hallazgo_excel)]
    return json.dumps([r.pano, r.rele, *lados], sort_keys=True, ensure_ascii=False)


def _correspondencia(antes: ReporteInforme, despues: ReporteInforme) -> list[tuple[int, int]]:
    """(idx en AG1, idx en la repetición) de cada par, por su contenido: V2 no
    cambia ningún emparejamiento, solo el estado de algunos pares."""
    por_clave: dict[str, deque[int]] = defaultdict(deque)
    for n, r in enumerate(despues.resultados):
        por_clave[_clave_par(r)].append(n)
    pares = [(n, por_clave[_clave_par(r)].popleft()) for n, r in enumerate(antes.resultados)]
    assert len(pares) == len(despues.resultados)
    return pares


_SOLO_4E = {"estado", "diferencias", "equivalencias_redaccion"}
# Lo que cambia el schema 0.9.0 en cada par: la versión y la marca de V2. AG1 se
# guardó con el 0.8.0 (la marca se carga en None) y la marca se compara aparte.
_MARCA = {"schema_version", "emparejamiento_dudoso"}


# El único par dudoso de AG1: Alfa con Opus, E7, fila 69. El «Cumple» que la
# perdió está en la misma página que el hallazgo del par, junto con otros dos de la
# tupla: el motivo lo identifica por su descripción (revisión del 2026-10-26). La
# redacción es la de PD72 (decisión del usuario 2026-10-26, provisoria hasta el
# feedback del equipo revisor).
MOTIVOS = {"2026-10-17_01-46-55_claude-opus-5-5": (
    "Revisar a qué hallazgo corresponde esta fila. El Excel dice que no cumple, pero en la "
    "misma pág. 26 hay otro hallazgo del PDF que dice que cumple (descripción «Comparación "
    "con ECAP adjunto en INFOTÉCNICA: Cumple») y que también podría ser el de esta fila. Si "
    "es ese, el Excel invirtió el veredicto.")}


def _dudosos(antes: ReporteInforme, despues: ReporteInforme) -> dict[int, str]:
    """idx en AG1 → motivo, de los pares de la repetición con emparejamiento_dudoso."""
    assert all(r.emparejamiento_dudoso is None for r in antes.resultados)
    return {n: motivo for n, m in _correspondencia(antes, despues)
            if (motivo := despues.resultados[m].emparejamiento_dudoso) is not None}


def _cambios(antes: ReporteInforme, despues: ReporteInforme) -> list[dict[str, Any]]:
    salida = []
    for n, m in _correspondencia(antes, despues):
        a, d = antes.resultados[n], despues.resultados[m]
        # Fuera de lo que decide 4e, todo igual (emparejamiento, confianza, justificación).
        assert a.model_dump(mode="json", exclude=_SOLO_4E | _MARCA) == d.model_dump(
            mode="json", exclude=_SOLO_4E | _MARCA), n
        if a.model_dump(mode="json", exclude=_MARCA) == d.model_dump(mode="json",
                                                                     exclude=_MARCA):
            continue
        salida.append({
            "idx_ag1": n, "estado_antes": a.estado.value, "estado_despues": d.estado.value,
            "campos_antes": [x.campo.value for x in a.diferencias],
            "equivalencias_antes": [x.campo.value for x in a.equivalencias_redaccion],
            "campos_despues": [x.campo.value for x in d.diferencias],
            "detalles_nuevos": [x.detalle or "" for x in d.diferencias
                                if x.campo.value in [e.campo.value
                                                     for e in a.equivalencias_redaccion]],
        })
    return salida


def _normalizado(dato: Any) -> Any:
    return json.loads(json.dumps(dato, ensure_ascii=False, default=str))


@pytest.mark.parametrize("run_id", _parametros())
def test_v2_sobre_ag1_reproduce_la_simulacion(run_id: str,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    sim = leer_json(SIMULACION)
    assert sim["repeticion"] == "AG1" and "V2" in sim["variantes"]
    info = sim["runs"][run_id]
    esperado = info["variantes"]["V2"]

    reporte, jueces = _repetir(run_id, monkeypatch)

    # Jueces: todo de AG1; nadie pide los campos que V2 saca del juez de redacción.
    assert (jueces.matching.pagadas, jueces.matching.resumen()["sin_usar"]) == (0, 0)
    dudosos = [p for p in info["pares_desplazamiento"]
               if p["vigente_al_final"] and p["polaridad_opuesta_dueno_fila"]]
    assert sorted(p["idx"] for p in dudosos) == esperado["pares_dudosos_idx_ag1"]
    sacados = sorted((clave_tupla(*p["tupla"]), c["campo"], p["pagina"], p["fila"])
                     for p in dudosos for c in p["campos"]
                     if c["veredicto_juez_redaccion"] is not None)
    assert jueces.sin_pedir() == sacados
    assert (jueces.lotes_nuevos == 0) == (not sacados)

    # Frente a AG1 cambian exactamente los resultados de V2: lo que iba al juez de
    # redacción queda como la diferencia de 4c (bajo el umbral, como en un semantico_bajo).
    ag1 = _reporte_ag1(run_id)
    cambios = _cambios(ag1, reporte)
    claves = ("idx_ag1", "estado_antes", "estado_despues", "campos_antes",
              "equivalencias_antes", "campos_despues")
    assert [{k: c[k] for k in claves} for c in cambios] == [
        {k: c[k] for k in claves} for c in esperado["cambios"]]
    for c in cambios:
        assert c["detalles_nuevos"] and all(
            "bajo el umbral" in x and "juez de redacción" not in x
            for x in c["detalles_nuevos"])

    # El motivo lo llevan exactamente los pares dudosos de V2 (schema 0.9.0).
    dudosos = _dudosos(ag1, reporte)
    assert sorted(dudosos) == esperado["pares_dudosos_idx_ag1"]
    assert list(dudosos.values()) == ([MOTIVOS[run_id]] if run_id in MOTIVOS else [])

    # Resumen del reporte (con los pares dudosos de confianza alta en «requieren
    # revisión»), evaluación contra el GT y golden de los errores no mostrados.
    resumen_v2 = dict(esperado["resumen_reporte"])
    resumen_v2["requieren_revision"] += sum(
        1 for n in dudosos
        if ag1.resultados[n].tipo_match not in (TipoMatch.SEMANTICO_BAJO, TipoMatch.SIN_MATCH))
    assert reporte.resumen.model_dump(mode="json") == resumen_v2
    hashes = hashes_del_run(AG1 / run_id)
    assert hashes is not None
    aplicable = gt_aplicable(gts_de(GT_DIR_DEFAULT), *hashes)
    assert aplicable is not None
    gt = _gt_de_la_simulacion(aplicable, info["sha256_gt"])
    ev = evaluar(reporte, gt, sha256_informe=hashes[0], sha256_excel=hashes[1],
                 run_id=run_id, modelo=reporte.modelo_extraccion)
    evaluacion = {k: v for k, v in esperado["evaluacion"].items() if k != "sin_adjudicar_detalle"}
    assert _normalizado(resumen(ev)) == evaluacion
    assert _golden(reporte, gt.informe, run_id) == [
        {k: g[k] for k in ("fila", "estado")} for g in esperado["golden"]]


def _gt_de_la_simulacion(aplicable: GtAplicable, sha256: str) -> GtInforme:
    """El GT con el sha256 que registró la simulación: el de hoy o, si una ronda
    posterior lo completó, el que se arma con sus fuentes hasta alguna ronda (en
    el orden en que se corrieron, el de ``fuentes``)."""
    if aplicable.sha256 == sha256:
        return aplicable.gt
    fuentes = aplicable.gt.fuentes
    rondas = list(dict.fromkeys(f.ronda for f in fuentes))
    for k in range(1, len(rondas)):
        gt = construir_gt(MEDICIONES, [MEDICIONES / "adjudicacion" / f.adjudicacion
                                       for f in fuentes if f.ronda in rondas[:k]])
        if hashlib.sha256(serializar(gt).encode("utf-8")).hexdigest() == sha256:
            return gt
    pytest.fail(f"{aplicable.ruta.name}: ninguna de sus rondas {rondas} rearma el GT de la "
                f"simulación ({sha256[:16]}…)")


def _golden(reporte: ReporteInforme, informe: str, run_id: str) -> list[dict[str, Any]]:
    """Los errores no mostrados de la subestación, como los evalúa la simulación."""
    sub = subestacion(informe)
    origen = MEDICIONES / "b2" / "runs" / run_id
    e2 = leer_json(origen / "etapa2_excel_normalizado.json")
    e3 = leer_json(origen / "etapa3_pdf_hallazgos.json")
    datos = reporte.model_dump(mode="json")
    salida = []
    for error in ERRORES:
        if error.subestacion != sub:
            continue
        exento = exencion_del_run(error, reporte.modelo_extraccion, e2, e3) is not None
        estado = "exento" if exento else ("pasa" if not verificar_error(datos, error) else "FALLA")
        salida.append({"fila": error.fila_excel, "estado": estado})
    return salida


def test_la_variante_v2_de_la_simulacion_es_la_de_pd71() -> None:
    """Las cifras de tasks/todo.md (PD71) y DISENO §5 4b′: E7 recuperado, sin A
    perdidos, golden en verde y, sumando los 5 runs, A 40, D 28, E 0."""
    if not RUNS or not SIMULACION.is_file():
        pytest.skip(EXENTO)
    v2 = leer_json(SIMULACION)["por_variante"]["V2"]
    t = v2["contra_gt"]
    assert (t["A"], t["D"], t["E"], t["precision_alertas"]) == (40, 28, 0, 0.5882)
    assert (v2["recupera_e7"], v2["golden_en_verde"], v2["a_perdidos_nuevos"],
            v2["pares_dudosos"], v2["alertas_sumadas"]) == (True, True, [], 1, 1)
