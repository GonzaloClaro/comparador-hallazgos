"""Ensayo con falsos de la repetición de E4 con la asignación global (PD23, AG1), sin API.

Antes de pagar PD23 (PD38) se comprueba que lo que la repetición guarda responde
lo que se le va a preguntar. Corre en un temporal, con los comandos de PD23:

1. Una ronda «B2» sintética (``evaluar_lote``, asignación global apagada) sobre
   un informe con UN conflicto real: en la tupla (BT1, SEL 551C) el juez falso
   le da a P1 la fila de P2 (62) y a P2 su propia fila con más confianza (88).
   Con la asignación apagada P1 se queda la fila de P2 (P2 falta, la fila de P1
   sobra) y el error del Excel en la calificación de la fila de P2 queda
   escondido, como Alfa 107 con Opus; con la global, P2 la desplaza.
2. Como B2: el run no guarda vectores; ``--solo-vectores`` los calcula aparte (D1).
3. GT del informe adjudicado sobre el run de B2, con ese error del Excel (M27).
4. La base de regresión (como ``mediciones/b2/replay_base/<run_id>``): repetición
   mixta con la asignación apagada; la copia congelada del código en
   ``mediciones/replay_e4_codigo/AG1/src``, fuera de ``replay_e4/``.
5. ``--preflight`` (no llama ni escribe), la repetición con
   ``ASIGNACION_GLOBAL=true``, ``--vectores``, ``--cache mixto``,
   ``--cache-desde`` la base, ``--gt-comparador`` y ``--codigo-congelado``, y
   ``metricas_lote``. Después, las funciones del golden de los errores no
   mostrados sobre lo que quedó, incluida la exención (CAUSA_ANTERIOR_A_E4).

Los falsos están en la frontera con los proveedores (los SDK), como en
``tests/test_preparacion_b3.py``: el cliente real arma la petición y la caché de
los jueces compara sus parámetros. Corre con Sonnet y con Opus (PD23 repite los dos).
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from comparador import fichas, reproducir_e4
from comparador.config import settings
from comparador.etapa4_matching import clave_tupla, textos_a_embeber
from comparador.gt_comparador import serializar
from comparador.llm import client as llm_client
from comparador.llm import embeddings as llm_embeddings
from comparador.metricas_lote import Resultado, cargar_replays, generar
from comparador.persistence import hash_arbol
from comparador.schemas import Hallazgo, ReporteInforme
from tests import test_integracion_pipeline as integracion
from tests.golden import datos
from tests.golden import test_golden_errores_no_mostrados as errores
from tests.test_integracion_pipeline import (
    C_DUF,
    C_OPER,
    P1,
    P2,
    R5_EXCEL,
    LLMFalso,
    _crear_excel,
    _crear_pdf,
)
from tests.test_metricas_lote import _leer_csv
from tests.test_persistence import copiar_src
from tests.test_preparacion_b3 import (
    CARPETA,
    EMBEDDINGS,
    INFORME,
    OPUS,
    PRECIOS,
    _AnthropicFalso,
    _clase,
    _gt_sintetico,
    _Linea,
    _OpenAIFalso,
)

SONNET = "claude-sonnet-5-5"
# El conflicto de (BT1, SEL 551C): (hallazgo del PDF, fila del Excel) → confianza.
PUNTAJES = {(P1, P2): 62, (P1, P1): 55, (P2, P2): 88}


class _LLMAG1(LLMFalso):
    """El escenario del test de integración con el juez del conflicto: elige,
    entre las filas que se le ofrecen, la de más puntaje (null bajo 50)."""

    @staticmethod
    def _juez_matching(kw: dict[str, Any]) -> dict[str, Any]:
        prompt = kw["user_prompt"]
        m = re.search(r'Hallazgo del PDF:\n  "(.*)"\n', prompt)
        assert m is not None
        if m[1] not in (P1, P2):
            return LLMFalso._juez_matching(kw)
        candidatos = [c for _, c in re.findall(r"^  \[(\d+)\] (.*)$", prompt, flags=re.M)]
        puntajes = [PUNTAJES.get((m[1], c), 0) for c in candidatos]
        mejor = max(range(len(candidatos)), key=lambda i: (puntajes[i], -i))
        if puntajes[mejor] < 50:
            return {"indice_candidato": None, "confianza": 10,
                    "justificacion": "ningún candidato"}
        return {"indice_candidato": mejor, "confianza": puntajes[mejor],
                "justificacion": "mismo hallazgo"}


def _clase_ag1(r: Any) -> tuple[str, str, dict[str, Any]] | None:
    """Como el GT de B2: los resultados de la tupla del conflicto son falsas
    alarmas de E4 (D5, el juez emparejó mal); el resto, como en el ensayo de B3."""
    if clave_tupla(r.pano, r.rele) == clave_tupla("BT1", "SEL 551C"):
        return "D", "D5", {"etapa_causa": "e4"}
    return _clase(r)


@dataclass
class Ensayo:
    modelo: str
    mediciones: Path
    run: Path
    npz: Path
    base: Path
    salida: Path
    codigo: Path
    csv: Path
    resultado: Resultado
    linea_preflight: list[str]
    arbol_igual_tras_preflight: bool
    linea_ag1: list[str]
    pedidos_ag1: list[dict[str, Any]]

    def json(self, ruta: Path) -> Any:
        return json.loads(ruta.read_text(encoding="utf-8"))

    def reporte(self, carpeta: Path) -> dict[str, Any]:
        reporte: dict[str, Any] = self.json(carpeta / "reporte_final.json")
        return reporte

    def fila_excel(self, descripcion: str) -> int:
        (fila,) = {h["evidencia"]["fila_excel"] for h in self.json(
            self.run / "etapa2_excel_normalizado.json") if h["descripcion"] == descripcion}
        return int(fila)

    def tabla(self, nombre: str, **filtro: str) -> list[dict[str, str]]:
        return [f for f in _leer_csv(self.csv / nombre)
                if all(f[k] == v for k, v in filtro.items())]


def _arbol(raiz: Path) -> dict[Path, bytes | None]:
    return {p.relative_to(raiz): (p.read_bytes() if p.is_file() else None)
            for p in raiz.rglob("*")}


def _cli(mp: pytest.MonkeyPatch, modulo: Any, argumentos: list[str]) -> None:
    mp.setattr(sys, "argv", [modulo.__name__.rsplit(".", 1)[-1], *argumentos])
    modulo.main()


@pytest.fixture(scope="module", params=[SONNET, OPUS], ids=["sonnet", "opus"])
def ensayo(request: pytest.FixtureRequest,
           tmp_path_factory: pytest.TempPathFactory) -> Iterator[Ensayo]:
    from comparador import evaluar_lote

    modelo: str = request.param
    raiz = tmp_path_factory.mktemp(f"ensayo_ag1_{modelo}")
    med = raiz / "mediciones"
    with pytest.MonkeyPatch.context() as mp:
        # Valores de B2 (los de config.py de entonces: la asignación global apagada,
        # encendida por defecto desde el 2026-10-26), no los del .env de quien corre.
        for campo, valor in (("openai_api_key", "sk-falsa"), ("anthropic_api_key", "sk-falsa"),
                             ("modelo_extraccion", modelo), ("modelo_extraccion_fallback", ""),
                             ("modelo_juez_matching", ""), ("modelo_embeddings", EMBEDDINGS),
                             ("effort_llm", ""), ("juez_redaccion", True),
                             ("cita_checklist", True), ("asignacion_global", False),
                             # AG1 corrió sin M30 (encendido por defecto desde el 2026-10-27).
                             ("descripcion_identica", False),
                             ("threshold_descripcion", 0.85), ("threshold_accion", 0.85),
                             ("top_k_candidatos", 5), ("umbral_tokens_troceo", 900_000),
                             ("runs_a_retener", settings.runs_a_retener),
                             ("runs_incompletos_a_retener", settings.runs_incompletos_a_retener),
                             ("runs_dir", med / "b2" / "runs")):
            mp.setattr(settings, campo, valor)
        linea = _Linea()
        anthropic = _AnthropicFalso(linea)
        anthropic.llm = _LLMAG1()
        openai_falso = _OpenAIFalso(linea)
        mp.setattr(llm_client, "get_client_anthropic", lambda: anthropic)
        mp.setattr(llm_client, "get_client", lambda: openai_falso)
        mp.setattr(llm_embeddings, "get_client", lambda: openai_falso)
        # Sin fichas: el fixture de función de tests/conftest.py corre después.
        mp.setattr(fichas, "RUTA_DEFAULT", raiz / "sin_fichas.yaml")

        # El Excel se equivoca en la calificación de la fila de P2 (el PDF dice Relevante).
        filas = [[*f[:5], "Menor"] if f[3] == P2 else f for f in integracion.FILAS_EXCEL]
        mp.setattr(integracion, "FILAS_EXCEL", filas)
        caso = raiz / "informes_reales" / CARPETA
        caso.mkdir(parents=True)
        _crear_pdf(caso / "Informe Sintético.pdf")
        _crear_excel(caso / "Tabla de Hallazgos Sintética.xlsx")

        # 1. La ronda B2, con su copia de src/ como mediciones/b2/src.
        _cli(mp, evaluar_lote, [
            "--modelos", modelo, "--base", str(raiz / "informes_reales"), "--informes", INFORME,
            "--etiqueta", "B2", "--salida", str(med / "b2" / "evaluacion_B2.json")])
        copiar_src(med / "b2" / "src")
        evaluacion = json.loads((med / "b2" / "evaluacion_B2.json").read_text("utf-8"))
        (fila,) = evaluacion["resultados"][modelo]
        run = med / "b2" / "runs" / fila["run_id"]

        # 2. Como B2: sin vectores en el run; D1 los calcula aparte.
        (run / "etapa4_embeddings.npz").unlink()
        npz = med / "b2" / "vectores_e4" / f"{run.name}.npz"
        _cli(mp, reproducir_e4, [str(run), "--solo-vectores", str(npz)])

        # 3. GT del informe adjudicado sobre el run de B2, con el error del Excel.
        reporte = ReporteInforme.model_validate_json(
            (run / "reporte_final.json").read_text("utf-8"))
        fila_p2 = next(h["evidencia"]["fila_excel"] for h in json.loads(
            (run / "etapa2_excel_normalizado.json").read_text("utf-8")) if h["descripcion"] == P2)
        error_excel = {"id": "e1", "fila_excel": fila_p2, "pagina_pdf": 4,
                       "clasificacion_pdf": C_OPER, "campos": ["calificacion"],
                       "subclase": "A4", "contraparte_validada": True,
                       "no_mostrado_en_b2": [modelo], "cita_pdf": P2, "cita_excel": P2,
                       "fuente": "sintética"}
        gt = med / "gt" / "comparador" / f"{CARPETA}.json"
        gt.parent.mkdir(parents=True)
        gt.write_text(serializar(_gt_sintetico(
            reporte, (run / "input_informe_original.hash").read_text().strip(),
            (run / "input_excel.hash").read_text().strip(), run, modelo=modelo,
            clasificar=_clase_ag1, errores_excel=[error_excel])), "utf-8")

        # 4. Base de regresión (asignación apagada) y código congelado de AG1.
        base = med / "b2" / "replay_base" / run.name
        _cli(mp, reproducir_e4, [str(run), "--salida", str(base), "--vectores", str(npz),
                                 "--cache", "mixto"])
        codigo = copiar_src(med / "replay_e4_codigo" / "AG1" / "src")

        # 5. PD23: preflight, repetición con la asignación global y métricas.
        mp.setattr(settings, "asignacion_global", True)
        salida = med / "replay_e4" / "AG1" / run.name
        banderas = [str(run), "--salida", str(salida), "--vectores", str(npz),
                    "--cache", "mixto", "--cache-desde", str(base),
                    "--gt-comparador", str(gt.parent), "--codigo-congelado", str(codigo)]
        linea.llamadas = []
        antes = _arbol(raiz)
        _cli(mp, reproducir_e4, [*banderas, "--preflight"])
        linea_preflight, igual = list(linea.llamadas), _arbol(raiz) == antes
        anthropic.pedidos = []
        _cli(mp, reproducir_e4, banderas)
        linea_ag1, pedidos_ag1 = list(linea.llamadas), list(anthropic.pedidos)

        csv = raiz / "csv"
        resultado = generar(med, PRECIOS, csv)
        yield Ensayo(modelo, med, run, npz, base, salida, codigo, csv, resultado,
                     linea_preflight, igual, linea_ag1, pedidos_ag1)


def _meta(ensayo: Ensayo) -> dict[str, Any]:
    meta: dict[str, Any] = ensayo.json(ensayo.salida / "metadata.json")
    return meta


def _raws(carpeta: Path, subcarpeta: str) -> list[dict[str, Any]]:
    return [json.loads(p.read_text("utf-8"))
            for p in sorted((carpeta / subcarpeta).glob("*.json"),
                            key=lambda p: int(p.stem.split("_")[-1]))]


# ------------------------------------------------------------ preflight y gasto


def test_el_preflight_no_llamo_ni_escribio(ensayo: Ensayo) -> None:
    assert ensayo.linea_preflight == []
    assert ensayo.arbol_igual_tras_preflight


def test_la_clave_de_openai_se_probo_antes_del_primer_juez(ensayo: Ensayo) -> None:
    """Una sola llamada a OpenAI (la prueba): los vectores de D1 cubren todo."""
    assert ensayo.linea_ag1[0] == "openai:1"
    assert [x for x in ensayo.linea_ag1 if x.startswith("openai")] == ["openai:1"]
    assert ensayo.linea_ag1[1:] == ["claude:_JuezResponse"] * 2
    prueba = _meta(ensayo)["prueba_clave_openai"]
    assert (prueba["ok"], prueba["modelo"], prueba["modelo_servido"]) == (
        True, EMBEDDINGS, EMBEDDINGS)


def test_lo_servido_desde_la_cache_y_lo_pagado(ensayo: Ensayo) -> None:
    """De la base: la primera consulta de P1, la de Q y el juez de redacción
    (mismo prompt). Pagadas: P2 con las dos filas y P1 sin la que perdió, las
    únicas que llegaron al proveedor. Sin usar: P2 con solo la fila de P1."""
    meta = _meta(ensayo)
    cache = meta["cache_jueces"]
    assert (cache["modo"], cache["desde"]) == ("mixto", str(ensayo.base.resolve()))
    assert (cache["desde_cache"], cache["pagadas"], cache["sin_usar"]) == (3, 2, 1)
    assert len(ensayo.pedidos_ag1) == cache["pagadas"]
    assert all(p["model"] == ensayo.modelo for p in ensayo.pedidos_ag1)
    textos = textos_a_embeber(
        [Hallazgo.model_validate(h) for h in ensayo.json(ensayo.run / "etapa3_pdf_hallazgos.json")],
        [Hallazgo.model_validate(h)
         for h in ensayo.json(ensayo.run / "etapa2_excel_normalizado.json")])
    assert meta["vectores"]["origen"] == "indicado"
    assert (meta["vectores"]["cargados"], meta["vectores"]["calculados"]) == (len(textos), 0)
    assert not (ensayo.salida / "etapa4_embeddings.npz").exists()
    assert meta["tokens_embeddings"] == 0
    (fila,) = ensayo.tabla("replay_e4.csv")
    assert (fila["llamadas_desde_cache"], fila["llamadas_pagadas"]) == ("3", "2")
    assert float(fila["costo_usd"]) > 0
    for raw in _raws(ensayo.salida, "etapa4_llm_judge_raw"):
        assert raw.get("desde_cache", False) == (raw["tokens_total"] == 0), raw


def test_la_traza_de_la_asignacion_global_queda_en_los_raw(ensayo: Ensayo) -> None:
    raws = _raws(ensayo.salida, "etapa4_llm_judge_raw")
    trazas = [r["asignacion_global"] for r in raws if r["asignacion_global"]["pano"] == "BT1"]
    assert [(t["orden_pdf"], t["reintento"], t["resultado"]) for t in trazas] == [
        (0, False, "tomo_fila_libre"), (1, False, "desplazo"), (0, True, "tomo_fila_libre")]
    assert trazas[1]["frente_a"] == {"orden_pdf": 0, "confianza": 0.62}
    assert trazas[2]["filas_perdidas"] == [ensayo.fila_excel(P2)]
    assert {t["rele"] for t in trazas} == {"SEL 551C"}
    # Las 4 consultas al juez de matching llevan la traza, con su tupla.
    assert [(r["asignacion_global"]["pano"], r["asignacion_global"]["resultado"])
            for r in raws][3:] == [("C3", "sin_match")]
    # La base (apagada) no la trae: es lo único que cambia la repetición.
    assert not any("asignacion_global" in r for r in _raws(ensayo.base, "etapa4_llm_judge_raw"))
    meta = _meta(ensayo)
    assert (meta["asignacion_global"], meta["llamadas_juez_reintento"]) == (True, 1)
    assert ensayo.json(ensayo.base / "metadata.json")["asignacion_global"] is False


def test_lo_que_atribuye_las_cifras_queda_en_la_metadata(ensayo: Ensayo) -> None:
    meta = _meta(ensayo)
    congelado = hash_arbol(ensayo.codigo)[0][:16]
    assert meta["codigo_congelado"]["sha256_codigo"] == congelado
    assert meta["version_codigo"]["sha256_codigo"] == congelado
    assert meta["run_origen"] == ensayo.run.name
    assert (meta["modelo_extraccion"], meta["modelo_extraccion_fallback"],
            meta["effort_llm_origen"]) == (ensayo.modelo, None, "raw")
    assert meta["vectores"]["sha256"] and meta["vectores"]["archivo"] == ensayo.npz.name
    # Mismos insumos que el run: la repetición se evalúa contra el GT sin buscarlo.
    for nombre in ("input_informe_original.hash", "input_excel.hash"):
        assert (ensayo.salida / nombre).read_bytes() == (ensayo.run / nombre).read_bytes()


# ------------------------------------------------------------ contra el GT y métricas


def test_el_gt_registra_lo_que_la_asignacion_global_cambio(ensayo: Ensayo) -> None:
    """El error del Excel pasa de no mostrado a mostrado y no se pierde ningún A.
    El «coincide» nuevo (P1 con su fila, correcto) toma un lado de dos D5 del GT
    de B2: sale como posible escondido nuevo, que se adjudica contra la fuente."""
    gt = _meta(ensayo)["comparador_gt"]
    delta = gt["delta"]
    assert delta["errores_excel"] == [{"id": "e1", "fila_excel": ensayo.fila_excel(P2),
                                       "antes": "no_mostrado", "despues": "mostrado"}]
    assert delta["a_perdidos_nuevos"] == [] and gt["replay"]["a_perdidos"] == []
    nuevos = delta["posibles_escondidos_nuevos"]
    # El mismo resultado (P1 con su fila) contra dos ítems D5: la falsa alarma con
    # la fila de P2 (comparte el lado del PDF) y la fila de P1 «extra» (su par entero).
    assert len({p["idx"] for p in nuevos}) == 1
    assert sorted((p["clase"], p["par_completo"]) for p in nuevos) == [
        ("D", False), ("D", True)]
    assert gt["replay"]["estados_sin_adjudicar"] == {"coincide": 1, "difiere": 1}


def test_metricas_lote_reproduce_lo_guardado(ensayo: Ensayo) -> None:
    """La carpeta del código congelado (replay_e4_codigo/AG1/src) no es una
    ronda ni una repetición: cargar_replays solo recorre replay_e4/."""
    assert ensayo.resultado.discrepancias == []
    assert [r.directorio for r in cargar_replays(ensayo.mediciones)] == [ensayo.salida]
    (fila,) = ensayo.tabla("replay_e4.csv")
    assert (fila["etiqueta"], fila["run_origen"], fila["ronda_origen"], fila["estado"]) == (
        "AG1", ensayo.run.name, "B2", "completo")
    assert (fila["asignacion_global"], fila["llamadas_juez_reintento"]) == ("True", "1")
    assert (fila["errores_excel_original"], fila["errores_excel_replay"]) == (
        "e1:no_mostrado", "e1:mostrado")
    (gt,) = ensayo.tabla("comparador_gt_por_run.csv", tipo="replay_e4")
    assert (gt["ronda"], gt["run_id"], gt["evaluacion_guardada"]) == (
        "AG1", ensayo.run.name, "igual")
    assert gt["errores_excel"] == "e1:mostrado"
    assert [f["version"] for f in ensayo.tabla("ficha_version.csv")] == ["B2", "actual"]


# ------------------------------------------------------------ golden de los errores no mostrados


def _errores_sinteticos(ensayo: Ensayo, subestacion: str) -> tuple[errores.ErrorNoMostrado,
                                                                    errores.ErrorNoMostrado]:
    """Como Alfa 107 (la fila de P2: el par equivocado esconde la
    calificación) y como Alfa 98 (la fila de R5, sin contraparte en E3)."""
    modelos = frozenset({ensayo.modelo})
    return (errores.ErrorNoMostrado(subestacion, ensayo.fila_excel(P2), 4, C_OPER,
                                    ("calificacion",), modelos, True),
            errores.ErrorNoMostrado(subestacion, ensayo.fila_excel(R5_EXCEL), 5, C_DUF,
                                    ("calificacion",), modelos, True))


def test_las_funciones_del_golden_sobre_la_repeticion(
    ensayo: Ensayo, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Las funciones y los tests del golden, tal cual, sobre la carpeta de la
    repetición: la de P2 se ve con su contraparte (en B2 no); la de R5 se exime
    con su motivo y la exención se sostiene (fila a la vista, causa en la E3)."""
    monkeypatch.setattr(datos, "MEDICIONES", ensayo.mediciones)
    monkeypatch.setattr(datos, "HAY_MEDICIONES", True)
    (caso,) = datos.casos("b2")
    error_p2, error_r5 = _errores_sinteticos(ensayo, caso.subestacion)
    monkeypatch.setattr(errores, "ERRORES", (error_p2, error_r5))
    monkeypatch.setattr(errores, "REPETICIONES", [ensayo.salida])
    motivo = "causa anterior a E4: E3 no extrajo la contraparte de R5 en (C3, SEL 451)"
    monkeypatch.setattr(errores, "CAUSA_ANTERIOR_A_E4", {
        (caso.subestacion, error_r5.fila_excel, ensayo.modelo): motivo})

    original, repetido = ensayo.reporte(ensayo.run), ensayo.reporte(ensayo.salida)
    assert errores.verificar_error(original, error_p2)        # B2: par equivocado
    assert errores.verificar_error(repetido, error_p2) == []  # AG1: se ve con su contraparte
    parametros = {p.values[1].fila_excel: p for p in errores._parametros_repeticiones()}
    assert list(parametros[error_p2.fila_excel].marks) == []
    (marca,) = parametros[error_r5.fila_excel].marks
    assert marca.kwargs["reason"] == f"exento: {motivo}"
    errores.test_cada_repeticion_de_e4_tiene_su_origen(ensayo.salida)
    errores.test_la_repeticion_de_e4_deja_ver_el_error(ensayo.salida, error_p2)
    errores.test_ninguna_de_esas_filas_sale_coincide("b2", error_r5, ensayo.modelo)
    (exento,) = errores._parametros_exentos()
    assert exento.values == (ensayo.salida, error_r5)
    errores.test_la_exencion_de_la_repeticion_de_e4_se_sostiene(ensayo.salida, error_r5)
    # Sin la exención, la repetición fallaría: R5 no tiene contraparte en E3.
    assert errores.verificar_error(repetido, error_r5)
    e3 = ensayo.json(ensayo.run / "etapa3_pdf_hallazgos.json")
    assert errores.causa_anterior_vigente(e3, "C3", "SEL 451", error_r5)
    assert not errores.causa_anterior_vigente(e3, "BT1", "SEL 551C", error_p2)
