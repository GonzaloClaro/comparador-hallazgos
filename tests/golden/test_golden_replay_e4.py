"""Repetición de E4 sin API sobre B2 (M70): caché de jueces y vectores guardados.

1. Sin vectores (siempre): la caché armada con los raw de cada run de B2
   (Sonnet y Opus) encuentra cada llamada del juez de matching y del de
   redacción cuando se pide en el orden guardado y con los parámetros que
   pediría hoy el cliente (Opus: B2 no mandaba thinking; hoy pide adaptive con
   display, M20), y devuelve la respuesta de esa misma llamada. Fija cuántas
   claves repetidas tiene cada run (104 en los 14). Además, con los mismos
   textos el código de hoy arma exactamente los prompts de B2.
2. Con los vectores recalculados de B2 (D1, `mediciones/b2/vectores_e4/`).
   Los embeddings de OpenAI no son reproducibles bit a bit, así que D1 no da
   los vectores exactos de B2 (que no los guardó):
   - las similitudes guardadas salen con un ruido acotado (`RUIDO_MAXIMO`),
     ninguna cruza un umbral del run, el orden del top-k cambia solo donde
     está fijado (`ORDEN_CAMBIADO`) y los tokens que cobró D1 son los de B2;
   - la base de regresión (`mediciones/b2/replay_base/<run_id>/`, 2026-10-24)
     es la repetición de los 14 runs con esos vectores: 12 salieron enteros de
     la caché de B2 y en Beta se pagaron una vez las 4 llamadas cuyo prompt
     cambió (`PAGADAS_EN_LA_BASE`, ≈US$0,03, caché mixta). Frente a B2 solo
     difiere lo fijado en `DIFERENCIAS_CONOCIDAS` (fuera de los campos nuevos
     del schema y el ruido de las similitudes);
   - la repetición estricta de cada run, con la caché de la base
     (`cache_desde`), no pide nada fuera de ella y da exactamente el reporte de
     la base: un cambio de código de E4/E5 aparece como diferencia y se
     clasifica, nunca se tapa.
   Sin esos vectores, un único parámetro se salta con «exento:» (compatible
   con GOLDEN_OBLIGATORIO); con algunos sí y otros no, los que faltan fallan.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from comparador.cache_jueces import SCHEMA_SIN_REGISTRO, CacheJueces, leer_raws
from comparador.config import settings
from comparador.etapa4_matching import _JuezRedaccionResponse, _JuezResponse
from comparador.evaluar_comparador import GT_DIR_DEFAULT
from comparador.llm.client import sha256_de_schema
from comparador.llm.prompts import (
    SYSTEM_JUEZ_MATCHING,
    SYSTEM_JUEZ_REDACCION,
    user_juez_matching,
    user_juez_redaccion,
)
from comparador.persistence import cargar_vectores
from comparador.reproducir_e4 import (
    _items_redaccion,
    partes_matching,
    reproducir_e4,
    verificar_similitudes,
)
from comparador.schemas import ReporteInforme
from tests.golden.datos import (
    MEDICIONES,
    RONDAS_CONGELADAS,
    Caso,
    casos,
    ids,
    requiere_mediciones,
)

pytestmark = [pytest.mark.golden, requiere_mediciones]

MODELOS = ("claude-sonnet-5-5", "claude-opus-5-5")
CASOS = [c for c in casos("b2") if c.modelo in MODELOS and c.tiene("reporte_final.json")]
VECTORES_B2 = MEDICIONES / "b2" / "vectores_e4"
HAY_VECTORES = any(VECTORES_B2.glob("*.npz"))
EXENTO_SIN_VECTORES = "exento: sin vectores de B2 (D1)"

# Claves de prompt que se repiten dentro de cada run (cola por clave). Sonnet
# y Opus suman 53 y 51.
CLAVES_REPETIDAS = {
    "b2-sonnet-Epsilon": 1, "b2-sonnet-Añañuca": 0, "b2-sonnet-Zeta": 1,
    "b2-sonnet-Alfa": 12, "b2-sonnet-Beta": 22, "b2-sonnet-Eta": 11,
    "b2-sonnet-Gamma": 6,
    "b2-opus-Epsilon": 1, "b2-opus-Añañuca": 0, "b2-opus-Zeta": 1,
    "b2-opus-Alfa": 10, "b2-opus-Beta": 22, "b2-opus-Eta": 11,
    "b2-opus-Gamma": 6,
}

# Diferencias de fondo entre el reporte de B2 y el de la base, por caso: (idx,
# ruta del campo, guardado, repetido), sin textos del informe. Todas vienen de
# las 4 llamadas de Beta que se volvieron a preguntar porque los vectores de
# D1 cambiaron su prompt: el juez eligió el mismo candidato con otra redacción
# de la justificación y, a veces, otra confianza.
DIFERENCIAS_CONOCIDAS: dict[str, list[tuple[int, str, Any, Any]]] = {
    "b2-sonnet-Beta": [(169, "confianza", 0.98, 0.99), (169, "justificacion", ..., ...)],
    "b2-opus-Beta": [(23, "confianza", 0.98, 0.97), (23, "justificacion", ..., ...),
                       (115, "justificacion", ..., ...), (169, "justificacion", ..., ...)],
}


def _modelo_de(carpeta: str) -> type[Any]:
    return _JuezRedaccionResponse if carpeta == "etapa4_redaccion_raw" else _JuezResponse


@pytest.fixture(autouse=True)
def _config_de_b2(monkeypatch: pytest.MonkeyPatch) -> None:
    """B2 corrió sin effort y sin asignación global (no lo registra el run)."""
    monkeypatch.setattr(settings, "effort_llm", "")
    monkeypatch.setattr(settings, "asignacion_global", False)
    # La base de regresión es la de B2, sin M30 (encendido por defecto desde el 2026-10-27).
    monkeypatch.setattr(settings, "descripcion_identica", False)
    # Ni el control de códigos (M28 V2, encendido por defecto desde el 2026-10-27).
    monkeypatch.setattr(settings, "control_codigos", False)
    # Ni las copias unificadas (M34, encendido por defecto desde el 2026-10-27).
    monkeypatch.setattr(settings, "unificar_copias", False)


def test_estan_los_14_runs_de_sonnet_y_opus() -> None:
    assert sorted(c.id for c in CASOS) == sorted(CLAVES_REPETIDAS)


def _en_orden_de_llamada(run_dir: Path) -> list[tuple[str, dict[str, Any]]]:
    """(carpeta/archivo, raw) de los jueces en el orden en que se llamaron,
    leído aparte de la caché: judge_0, judge_1, … y redaccion_0, …"""
    salida = []
    for carpeta, prefijo in (("etapa4_llm_judge_raw", "judge"),
                             ("etapa4_redaccion_raw", "redaccion")):
        n = 0
        while (archivo := run_dir / carpeta / f"{prefijo}_{n}.json").is_file():
            salida.append((f"{carpeta}/{archivo.name}",
                           json.loads(archivo.read_text(encoding="utf-8"))))
            n += 1
    return salida


@pytest.mark.parametrize("caso", CASOS, ids=ids(CASOS))
def test_la_cache_encuentra_cada_llamada_en_el_orden_guardado(caso: Caso) -> None:
    llamadas = _en_orden_de_llamada(caso.run_dir)
    assert len(llamadas) == sum(1 for _ in caso.run_dir.glob("etapa4_*_raw/*_*.json"))
    cache = CacheJueces.desde_run(caso.run_dir, modo="estricto")

    for nombre, raw in llamadas:
        respuesta, meta = cache(
            modelo=raw["modelo"], system_prompt=raw["system_prompt"],
            user_prompt=raw["user_prompt_text"], response_model=_modelo_de(nombre.split("/")[0]))
        assert meta["raw_origen"] == str(caso.run_dir.resolve() / nombre)
        assert respuesta.model_dump(mode="json") == raw["response_raw"]

    resumen = cache.resumen()
    assert (resumen["excluidas_fallidas"], resumen["excluidas_respaldo"]) == (0, 0)
    assert resumen["desde_cache"] == resumen["cargadas"] == len(llamadas) > 0
    assert resumen["sin_usar"] == 0
    assert resumen["claves_repetidas"] == CLAVES_REPETIDAS[caso.id]
    assert len(leer_raws(caso.run_dir).respuestas) == len(llamadas)


def test_b2_tiene_104_claves_repetidas() -> None:
    assert sum(CLAVES_REPETIDAS.values()) == 104


# Imprime el JSON schema de los jueces de E4 de la copia de src/ indicada (sin
# importar el paquete de hoy: corre en otro proceso).
_SCHEMAS_DE_UNA_RONDA = """
import json, sys
sys.path.insert(0, sys.argv[1])
from comparador import etapa4_matching as e4
print(json.dumps({nombre: getattr(e4, nombre).model_json_schema()
                  for nombre in ("_JuezResponse", "_JuezRedaccionResponse")
                  if hasattr(e4, nombre)}))
"""


@pytest.mark.parametrize("ronda", RONDAS_CONGELADAS)
def test_los_raw_sin_schema_registrado_son_del_schema_de_su_ronda(
    ronda: str, tmp_path: Path
) -> None:
    """Los raw de B0-B2 (y los de la base de D1) no traen `schema_sha256`: la
    caché les asigna un schema fijo, que debe ser el de los jueces del código
    congelado de cada ronda, no el de hoy (si el de hoy cambia, esos raw
    dejan de coincidir)."""
    src = MEDICIONES / ronda / "src"
    assert (src / "comparador" / "etapa4_matching.py").is_file(), f"falta {src}"
    # -B: importar la copia congelada no debe escribir __pycache__ en mediciones/.
    salida = subprocess.run([sys.executable, "-I", "-B", "-c", _SCHEMAS_DE_UNA_RONDA, str(src)],
                            capture_output=True, text=True, check=True, cwd=tmp_path)
    schemas = json.loads(salida.stdout)
    assert not any(src.rglob("__pycache__")), "la prueba escribió bytecode en mediciones/"

    assert "_JuezResponse" in schemas
    for carpeta, modelo in (("etapa4_llm_judge_raw", "_JuezResponse"),
                            ("etapa4_redaccion_raw", "_JuezRedaccionResponse")):
        if modelo in schemas:
            assert sha256_de_schema(schemas[modelo]) == SCHEMA_SIN_REGISTRO[carpeta], modelo


@pytest.mark.parametrize("caso", CASOS, ids=ids(CASOS))
def test_el_codigo_de_hoy_arma_los_mismos_prompts_que_b2(caso: Caso) -> None:
    """Con los mismos textos, los dos jueces de hoy mandan exactamente el prompt
    de B2 (system y user): tras D1, un faltante de la caché en la repetición
    estricta solo puede venir de los vectores, del top-k o del orden."""
    for nombre, raw in _en_orden_de_llamada(caso.run_dir):
        if nombre.startswith("etapa4_redaccion_raw"):
            assert raw["system_prompt"] == SYSTEM_JUEZ_REDACCION
            items = _items_redaccion(raw["user_prompt_text"])
            assert user_juez_redaccion(items) == raw["user_prompt_text"]
            assert [t["id"] for t in raw["lote"]] == [i["id"] for i in items]
        else:
            assert raw["system_prompt"] == SYSTEM_JUEZ_MATCHING
            pdf, candidatos = partes_matching(raw["user_prompt_text"])
            assert user_juez_matching(pdf, candidatos) == raw["user_prompt_text"], nombre


# --- Con los vectores de D1 ---------------------------------------------------

BASE_B2 = MEDICIONES / "b2" / "replay_base"
# Ruido de las similitudes recalculadas, según los decimales con que se guardó
# cada una (D1: hasta 0,003 en las trazas, mediana 0,00025; el detalle de las
# diferencias redondea a 2 y puede moverse un centésimo).
RUIDO_MAXIMO = {4: 0.005, 2: 0.01}
# Consultas del juez de matching cuyo orden de candidatos (entre los que vio B2)
# cambió con los vectores de D1: empates casi exactos (0,5246 contra 0,5258).
ORDEN_CAMBIADO = {
    "b2-sonnet-Beta": ["etapa4_llm_judge_raw/judge_139.json"],
    "b2-opus-Beta": ["etapa4_llm_judge_raw/judge_17.json",
                       "etapa4_llm_judge_raw/judge_139.json"],
}
# Llamadas que pagó la base porque su prompt cambió: las de ORDEN_CAMBIADO y,
# en Opus, judge_96, donde entró otro quinto candidato (verificar_similitudes
# compara el orden de los candidatos mostrados, no la pertenencia al top-k).
PAGADAS_EN_LA_BASE = {"b2-sonnet-Beta": 1, "b2-opus-Beta": 3}


def _dentro_del_ruido(guardada: float, recalculada: float, decimales: int) -> bool:
    # round: 0.78 - 0.77 da 0.010000000000000009 en coma flotante.
    return round(abs(guardada - recalculada), 6) <= RUIDO_MAXIMO[decimales]


def _casos_con_vectores() -> list[Any]:
    if not HAY_VECTORES:
        return [pytest.param(None, id="sin-vectores-B2",
                             marks=pytest.mark.skip(reason=EXENTO_SIN_VECTORES))]
    return [pytest.param(c, id=c.id) for c in CASOS]


def _vectores(caso: Caso) -> Path:
    ruta = VECTORES_B2 / f"{caso.run_id}.npz"
    assert ruta.is_file(), f"falta {ruta}: D1 debe calcular los vectores de los 14 runs"
    return ruta


def _base(caso: Caso) -> Path:
    ruta = BASE_B2 / caso.run_id
    assert (ruta / "reporte_final.json").is_file(), f"falta la base de regresión {ruta}"
    return ruta


def test_el_orden_cambiado_y_lo_pagado_son_de_runs_medidos() -> None:
    assert set(ORDEN_CAMBIADO) <= set(PAGADAS_EN_LA_BASE) <= set(CLAVES_REPETIDAS)
    assert set(DIFERENCIAS_CONOCIDAS) <= set(PAGADAS_EN_LA_BASE)
    assert sum(PAGADAS_EN_LA_BASE.values()) == 4


@pytest.mark.parametrize("caso", _casos_con_vectores())
def test_los_vectores_de_d1_dan_las_similitudes_de_b2_con_ruido_acotado(caso: Caso) -> None:
    vectores, modelo = cargar_vectores(_vectores(caso))
    meta = caso.json("metadata.json")
    assert modelo == meta["modelo_embeddings"]

    resultado = verificar_similitudes(caso.run_dir, vectores)

    umbrales = (meta["threshold_descripcion"], meta["threshold_accion"])
    for d in resultado["distintas"]:
        guardada, recalculada = d["guardada"], d["recalculada"]
        assert recalculada is not None, d
        decimales = 2 if d["origen"].endswith(":diferencias") else 4
        assert _dentro_del_ruido(guardada, recalculada, decimales), d
        assert all((guardada >= u) == (recalculada >= u) for u in umbrales), d
    assert [f["origen"] for f in resultado["orden_top_k"]["fuera_de_orden"]] == (
        ORDEN_CAMBIADO.get(caso.id, []))
    assert resultado["orden_top_k"]["consultas"] == sum(
        1 for _ in caso.run_dir.glob("etapa4_llm_judge_raw/judge_*.json"))
    # Mismos textos que embebió B2: los tokens que cobró D1 son los de B2.
    ficha = json.loads(_vectores(caso).with_suffix(".json").read_text(encoding="utf-8"))
    assert ficha["uso"]["tokens_total"] == caso.json(
        "etapa4_llm_judge_raw/embeddings.json")["tokens_total"]
    assert ficha["similitudes"] == resultado


_NUMERO = re.compile(r"\d+\.\d+")


def _sin_version(dato: Any) -> Any:
    """El JSON sin schema_version a ninguna profundidad, ni el motivo de cada
    Diferencia (0.12.0): la base se guardó con el schema de su momento, y ni la
    versión ni el rótulo del motivo, que repite lo que dice el detalle, son fondo
    del resultado."""
    if isinstance(dato, dict):
        diferencia = "campo" in dato and "valor_pdf" in dato
        return {k: _sin_version(v) for k, v in dato.items()
                if k != "schema_version" and not (diferencia and k == "motivo")}
    if isinstance(dato, list):
        return [_sin_version(v) for v in dato]
    return dato


def _diferencias_de_fondo(guardado: Any, repetido: Any, ruta: str = "",
                          salida: list[tuple[str, Any, Any]] | None = None
                          ) -> list[tuple[str, Any, Any]]:
    """Lo que difiere entre dos resultados (como JSON), sin contar lo que trae
    el schema nuevo (campos que el guardado no tiene; deben venir vacíos), la
    versión del schema ni el ruido de las similitudes (RUIDO_MAXIMO)."""
    salida = [] if salida is None else salida
    if isinstance(guardado, dict) and isinstance(repetido, dict):
        for clave in set(repetido) - set(guardado):
            assert repetido[clave] is None, f"{ruta}.{clave}: campo nuevo con valor"
        for clave in guardado:
            if clave != "schema_version":
                _diferencias_de_fondo(guardado[clave], repetido.get(clave, "<falta>"),
                                      f"{ruta}.{clave}" if ruta else clave, salida)
    elif (isinstance(guardado, list) and isinstance(repetido, list)
          and len(guardado) == len(repetido)):
        for a, b in zip(guardado, repetido, strict=True):
            _diferencias_de_fondo(a, b, ruta + "[]", salida)
    elif guardado != repetido:
        ruido = (ruta.endswith(".similitud") and isinstance(guardado, float)
                 and isinstance(repetido, float) and _dentro_del_ruido(guardado, repetido, 4))
        if (ruta.endswith(".detalle") and isinstance(guardado, str)
                and isinstance(repetido, str)
                and _NUMERO.sub("#", guardado) == _NUMERO.sub("#", repetido)):
            ruido = all(_dentro_del_ruido(float(a), float(b), 2) for a, b in zip(
                _NUMERO.findall(guardado), _NUMERO.findall(repetido), strict=True))
        if not ruido:
            salida.append((ruta, guardado, repetido))
    return salida


def _fondo_del_reporte(guardado: dict[str, Any],
                       repetido: dict[str, Any]) -> list[tuple[int, str, Any, Any]]:
    assert len(guardado["resultados"]) == len(repetido["resultados"])
    salida: list[tuple[int, str, Any, Any]] = []
    for idx, (a, b) in enumerate(zip(guardado["resultados"], repetido["resultados"],
                                                strict=True)):
        for ruta, x, y in _diferencias_de_fondo(a, b):
            texto = ruta == "justificacion"
            salida.append((idx, ruta, ... if texto else x, ... if texto else y))
    return salida


@pytest.mark.parametrize("caso", _casos_con_vectores())
def test_la_base_coincide_con_b2_salvo_lo_conocido(caso: Caso) -> None:
    base = _base(caso)
    meta = json.loads((base / "metadata.json").read_text(encoding="utf-8"))
    assert meta["run_origen"] == caso.run_id
    assert (meta["asignacion_global"], meta["juez_redaccion"]) == (
        False, caso.json("metadata.json").get("juez_redaccion", True))
    pagadas = PAGADAS_EN_LA_BASE.get(caso.id, 0)
    cache = meta["cache_jueces"]
    assert (cache["modo"], cache["pagadas"], cache["sin_usar"]) == (
        "mixto" if pagadas else "estricto", pagadas, pagadas)
    assert meta["vectores"]["calculados"] == 0
    assert meta["vectores"]["sha256"] == hashlib.sha256(_vectores(caso).read_bytes()).hexdigest()

    diferencias = _fondo_del_reporte(
        caso.json("reporte_final.json"),
        json.loads((base / "reporte_final.json").read_text(encoding="utf-8")))

    assert diferencias == DIFERENCIAS_CONOCIDAS.get(caso.id, [])
    assert meta["conteo_replay"] == meta["conteo_original"]
    gt = meta["comparador_gt"]
    if gt is not None:
        assert gt["replay"] == gt["original"]


@pytest.mark.parametrize("caso", _casos_con_vectores())
def test_la_repeticion_estricta_reproduce_la_base(caso: Caso, tmp_path: Path) -> None:
    base, salida = _base(caso), tmp_path / "replay"
    gt_dir = GT_DIR_DEFAULT if GT_DIR_DEFAULT.is_dir() else None

    # Un faltante de la caché sale acá como CacheJuecesFaltanteError: es un
    # fallo de caché (o de vectores), no un cambio de código.
    meta = reproducir_e4(caso.run_dir, salida, gt_dir, vectores=_vectores(caso),
                         cache="estricto", cache_desde=base)

    cache = meta["cache_jueces"]
    assert (cache["desde"], cache["pagadas"], cache["sin_usar"]) == (str(base.resolve()), 0, 0)
    assert meta["vectores"]["calculados"] == 0
    # Cada respuesta apunta a su raw: lo que pagó la base, a la base (no al raw
    # de B2 del mismo nombre); lo que la base sirvió de B2 conserva su origen.
    for raw in sorted(salida.glob("etapa4_*_raw/*_*.json")):
        en_la_base = json.loads((base / raw.parent.name / raw.name).read_text(encoding="utf-8"))
        assert json.loads(raw.read_text(encoding="utf-8"))["raw_origen"] == (
            en_la_base["raw_origen"] if en_la_base.get("desde_cache")
            else str(base.resolve() / raw.parent.name / raw.name)), raw.name
    esperado = ReporteInforme.model_validate(
        json.loads((base / "reporte_final.json").read_text(encoding="utf-8")))
    datos = json.loads((salida / "reporte_final.json").read_text(encoding="utf-8"))
    # Con la asignación apagada (B2), los campos nuevos del schema van vacíos: el
    # emparejamiento dudoso de PD71 (0.9.0) solo existe con la asignación global.
    assert [r["emparejamiento_dudoso"] for r in datos["resultados"]] == (
        [None] * len(datos["resultados"]))
    repetido = ReporteInforme.model_validate(datos)
    assert _sin_version([r.model_dump(mode="json") for r in repetido.resultados]) == _sin_version([
        r.model_dump(mode="json") for r in esperado.resultados]), (
        f"todas las llamadas salieron de la caché ({cache['desde_cache']}): la diferencia es "
        "de código de E4/E5, no de la caché; clasificarla antes de rehacer la base")
    # El resto del reporte también (resumen completo, checklist, metadatos):
    # un error del propio conteo de E5 no se ve en los resultados.
    no_comparables = {"fecha_procesamiento"}
    assert _sin_version(repetido.model_dump(mode="json", exclude=no_comparables)) == _sin_version(
        esperado.model_dump(mode="json", exclude=no_comparables))
    assert meta["conteo_replay"] == json.loads(
        (base / "metadata.json").read_text(encoding="utf-8"))["conteo_replay"]
