"""Ensayo con falsos de la ronda B3 (PD38, E10 del Bloque 23), sin API.

Antes de pagar B3 se comprueba que lo que la ronda guarda responde cada pregunta
que se le va a hacer. Corre la CLI de ``evaluar_lote`` como se correrá B3, en un
temporal, sobre un caso tipo Gamma (Reliable Energy, con planilla, ficha y GT
del comparador, todo sintético):

- ``b3``: completo con la cita del checklist (CITA_CHECKLIST encendida);
- ``b3s``: solo el checklist y sin la cita (``--solo-checklist --sin-cita-checklist``);

cada uno con su copia congelada de ``src/`` (``--codigo-congelado``) y su
RUNS_DIR, y después ``metricas_lote`` sobre esa carpeta de mediciones.

Los falsos están en la frontera con los proveedores (los SDK de Anthropic y de
OpenAI), no en ``llamar_llm_estructurado``: el cliente real arma la petición
(thinking adaptativo con ``display: summarized`` para Opus 5.5, M20) y guarda lo
que devuelve la API (modelo servido, resumen del razonamiento). Las respuestas
son las del escenario de ``tests/test_integracion_pipeline.py``. El GT del
comparador se arma de una corrida previa con los mismos falsos (son
deterministas): así la corrida de B3 calza con él por clave estable.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import openpyxl
import pytest
import yaml
from pydantic import BaseModel

from comparador import etapa0_checklist as e0
from comparador import evaluar_lote, fichas
from comparador.adjudicacion import campos_que_difieren
from comparador.config import settings
from comparador.etapa4_matching import textos_a_embeber
from comparador.evaluar_checklist import cargar_mapeo
from comparador.gt_comparador import VERSION_GT, GtInforme, serializar, texto_identico
from comparador.llm import client as llm_client
from comparador.llm import embeddings as llm_embeddings
from comparador.metricas_lote import Resultado, generar
from comparador.persistence import cargar_vectores, hash_arbol, version_codigo
from comparador.pipeline import ejecutar_pipeline
from comparador.schemas import EmpresaAuditora, EstadoHallazgo, Hallazgo, ReporteInforme
from tests.test_integracion_pipeline import (
    CITA_INVENTADA,
    PORTADA,
    LLMFalso,
    _crear_excel,
    _crear_pdf,
    embeddings_falsos,
)
from tests.test_metricas_lote import _leer_csv
from tests.test_persistence import copiar_src

ROOT = Path(__file__).resolve().parents[1]
PRECIOS = ROOT / "docs" / "metricas" / "precios.yaml"
CARPETA = "S-E Sintética (Auditor Reliable Energy)"
INFORME = "Sintética"                        # nombre corto en los CSV
OPUS = "claude-opus-5-5"
EMBEDDINGS = "text-embedding-3-large"
RESUMEN = "Resumen sintético del razonamiento"
PEDIDO_M20 = {"thinking": {"type": "adaptive", "display": "summarized"}}

# Tres puntos con un código propio en la planilla (no comparten ítem con otros):
# - P_FC: «cumple» con una cita que el PDF no tiene; la planilla dice NO. Con la
#   cita baja a no verificable (la bajada evita un falso cumple); sin ella, falso cumple.
# - P_AC: igual, pero la planilla dice SI (la bajada pierde un acierto).
# - P_NC: «no cumple» y la planilla dice NO (incumplimiento detectado).
_MAPEO = cargar_mapeo()
_UNICOS = [n for n, c in _MAPEO.items() if list(_MAPEO.values()).count(c) == 1]
P_FC, P_AC, P_NC = _UNICOS[:3]


class _LLMB3(LLMFalso):
    """El escenario del test de integración, con el checklist de B3."""

    @staticmethod
    def _checklist(kw: dict[str, Any]) -> dict[str, Any]:
        con_cita = kw["response_model"] is e0._ChecklistConCitaResponse
        items = []
        for n in range(1, e0.TOTAL_PUNTOS + 1):
            resultado = "no_cumple" if n == P_NC else "cumple"
            item: dict[str, Any] = {"numero": n, "resultado": resultado, "paginas": "1",
                                    "referencia": "portada"}
            if con_cita:
                texto = CITA_INVENTADA if n in (P_FC, P_AC) else PORTADA
                item["cita"] = {"pagina": 1, "texto": texto} if resultado == "cumple" else None
            items.append(item)
        return {"items": items}


@dataclass
class _Linea:
    """Orden de las llamadas a los dos proveedores en una corrida."""

    llamadas: list[str] = field(default_factory=list)


class _AnthropicFalso:
    """SDK de Anthropic falso: ``messages.stream`` responde con el escenario
    (bloque thinking con el resumen + texto JSON) y ``count_tokens`` con poco."""

    def __init__(self, linea: _Linea) -> None:
        self.linea = linea
        self.llm: LLMFalso = _LLMB3()
        self.pedidos: list[dict[str, Any]] = []
        falso = self

        class _Stream:
            def __init__(self, kw: dict[str, Any]) -> None:
                self.kw = kw

            def __enter__(self) -> _Stream:
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def get_final_message(self) -> Any:
                return falso._responder(self.kw)

        class _Messages:
            def stream(self, **kw: Any) -> _Stream:
                return _Stream(kw)

            def count_tokens(self, **kw: Any) -> Any:
                return SimpleNamespace(input_tokens=5_000)

        self.messages = _Messages()

    def _responder(self, kw: dict[str, Any]) -> Any:
        self.pedidos.append(kw)
        modelo: type[BaseModel] = kw["output_format"]
        self.linea.llamadas.append(f"claude:{modelo.__name__}")
        bloques = kw["messages"][0]["content"]
        texto = next(b["text"] for b in bloques if b["type"] == "text")
        pdf = next((b["source"]["data"] for b in bloques if b["type"] == "document"), None)
        parsed, meta = self.llm(modelo=kw["model"], system_prompt=kw["system"],
                                user_prompt=texto, response_model=modelo, pdf_base64=pdf)
        return SimpleNamespace(
            content=[SimpleNamespace(type="thinking", thinking=RESUMEN),
                     SimpleNamespace(type="text", text=json.dumps(meta["response_raw"]))],
            usage=SimpleNamespace(input_tokens=meta["tokens_prompt"],
                                  output_tokens=meta["tokens_completion"],
                                  cache_read_input_tokens=0),
            parsed_output=parsed, stop_reason="end_turn", model=kw["model"])


class _OpenAIFalso:
    """SDK de OpenAI falso: los vectores del escenario y el modelo servido."""

    def __init__(self, linea: _Linea) -> None:
        self.linea = linea
        self.pedidos: list[list[str]] = []
        self.embeddings = SimpleNamespace(create=self._crear)

    def _crear(self, *, model: str, input: list[str]) -> Any:
        self.pedidos.append(list(input))
        self.linea.llamadas.append(f"openai:{len(input)}")
        matriz, _ = embeddings_falsos(list(input))
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[float(v) for v in fila]) for fila in matriz],
            usage=SimpleNamespace(prompt_tokens=len(input), total_tokens=len(input)),
            model=model)


# ------------------------------------------------------------ insumos sintéticos


def _sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _planilla(ruta: Path) -> Path:
    """CheckList de revisión con el formato del CEN: los códigos del mapeo (los
    repetidos, como el 7.7, en filas repetidas), NO en P_FC y P_NC, SI en el resto."""
    no = {_MAPEO[P_FC], _MAPEO[P_NC]}
    repeticiones: dict[str, int] = {}
    for codigo in _MAPEO.values():
        base, _, k = codigo.partition("#")
        repeticiones[base] = max(repeticiones.get(base, 0), int(k or 1))
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Check List"
    fila = 3
    for base, veces in repeticiones.items():
        for j in range(1, veces + 1):
            codigo = base if j == 1 else f"{base}#{j}"
            veredicto = "NO" if codigo in no else "SI"
            for col, valor in ((6, base), (7, f"Ítem {codigo}"), (8, veredicto), (9, "obs")):
                ws.cell(row=fila, column=col, value=valor)
            fila += 1
    wb.save(ruta)
    return ruta


def _clase(r: Any) -> tuple[str, str, dict[str, Any]] | None:
    """Clase del GT sintético de cada resultado: OK los «coincide» con texto
    idéntico; A el «difiere» de polaridad (el Excel se equivoca); D de E3 en la
    descripción el otro «difiere»; C las faltas; D1 de E3 (omisión) lo extra.
    Un «coincide» con redacción distinta queda fuera del GT: sin referencia."""
    if r.estado == EstadoHallazgo.COINCIDE:
        return ("OK", "OK", {}) if texto_identico(r) else None
    if r.estado == EstadoHallazgo.DIFIERE:
        if any("Polaridad opuesta" in (d.detalle or "") for d in r.diferencias):
            return "A", "A5", {}
        return "D", "D6", {"etapa_causa": "e3", "campos_extraccion": ["descripcion"]}
    if r.estado == EstadoHallazgo.FALTA_EN_EXCEL:
        return "C", "C1", {"depende_de": ["P14"]}
    if r.estado == EstadoHallazgo.EXTRA_EN_EXCEL:
        return "D", "D1", {"etapa_causa": "e3", "campos_extraccion": ["omision"]}
    return None   # transversal: no entra al GT


def _gt_sintetico(reporte: ReporteInforme, sha_informe: str, sha_excel: str,
                  fuente: Path, *, modelo: str = OPUS,
                  clasificar: Callable[[Any], tuple[str, str, dict[str, Any]] | None] = _clase,
                  errores_excel: Sequence[dict[str, Any]] = ()) -> GtInforme:
    """GT adjudicado sobre el run ``fuente`` (en mediciones/b2/runs, con sus sha256:
    la extracción contra el GT compara lo que extrajo E3 con lo de la fuente).
    ``clasificar`` da la clase de cada resultado (por defecto ``_clase``) y
    ``errores_excel``, los errores reales del Excel del informe (M27)."""
    items: list[dict[str, Any]] = []
    for i, r in enumerate(reporte.resultados):
        clase = clasificar(r)
        if clase is None:
            continue
        nombre, sub, extra = clase
        h, x = r.hallazgo_pdf, r.hallazgo_excel
        items.append({
            "id": f"i{i}", "pano": r.pano, "rele": r.rele, "estado": r.estado.value,
            "campos": [c.value for c in campos_que_difieren(r)],
            "lado_excel": None if x is None else {"fila": x.evidencia.fila_excel},
            "lado_pdf": None if h is None else {
                "pagina": h.evidencia.pagina_pdf, "clasificaciones": [h.clasificacion],
                "citas": [{"texto": h.descripcion, "fuente": "adjudicacion", "modelo": modelo}]},
            "clase": nombre, "subclase": sub, "nivel_validacion": "verificado", **extra,
            "origenes": [{"modelo": modelo, "ronda": "B2", "run_id": fuente.name, "idx": i,
                          "tipo_match": r.tipo_match.value, "subclase": sub,
                          "nivel_validacion": "verificado"}],
        })
    coincide = [r for r in reporte.resultados if r.estado == EstadoHallazgo.COINCIDE]
    return GtInforme.model_validate({
        "version_gt": VERSION_GT, "informe": CARPETA,
        "sha256_informe_original": sha_informe, "sha256_excel": sha_excel,
        "fuentes": [{"modelo": modelo, "ronda": "B2", "run_id": fuente.name,
                     "carpeta": f"b2/runs/{fuente.name}",
                     "adjudicacion": "sintetica.json", "sha256_adjudicacion": "0",
                     "sha256_reporte": _sha(fuente / "reporte_final.json"),
                     "sha256_e3": _sha(fuente / "etapa3_pdf_hallazgos.json"),
                     "verificado_por_segundo_agente": True,
                     "universo": {
                         "regla": "sintético", "coincide": "todos",
                         "resultados": len(reporte.resultados),
                         "transversales": reporte.resumen.transversales, "items": len(items),
                         "barrido": {"coincide": len(coincide),
                                     "texto_identico": sum(texto_identico(r)
                                                           for r in coincide)}}}],
        "items": items, "errores_excel": list(errores_excel),
    })


# ------------------------------------------------------------ el ensayo


@dataclass
class Ensayo:
    mediciones: Path
    csv: Path
    resultado: Resultado
    ficha: dict[str, Any]
    gt: Path
    linea_b3: list[str]
    linea_b3s: list[str]
    anthropic: _AnthropicFalso

    def evaluacion(self, carpeta: str) -> dict[str, Any]:
        (ruta,) = (self.mediciones / carpeta).glob("evaluacion_*.json")
        datos: dict[str, Any] = json.loads(ruta.read_text(encoding="utf-8"))
        return datos

    def fila(self, carpeta: str) -> dict[str, Any]:
        (fila,) = self.evaluacion(carpeta)["resultados"][OPUS]
        return fila

    def run(self, carpeta: str) -> Path:
        return self.mediciones / carpeta / "runs" / self.fila(carpeta)["run_id"]

    def tabla(self, nombre: str, **filtro: str) -> list[dict[str, str]]:
        return [f for f in _leer_csv(self.csv / nombre)
                if all(f[k] == v for k, v in filtro.items())]


def _correr_cli(mp: pytest.MonkeyPatch, runs: Path, argumentos: list[str]) -> None:
    mp.setattr(settings, "runs_dir", runs)
    mp.setattr(sys, "argv", ["evaluar_lote", *argumentos])
    evaluar_lote.main()


@pytest.fixture(scope="module")
def ensayo(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Ensayo]:
    raiz = tmp_path_factory.mktemp("ensayo_b3")
    med = raiz / "mediciones"
    with pytest.MonkeyPatch.context() as mp:
        # main() y correr_lote cambian la configuración global: vuelve al salir. Los
        # valores son los de B3 (los de config.py de entonces: la asignación global
        # apagada, encendida por defecto desde el 2026-10-26), no los del .env de
        # quien corre.
        for campo, valor in (("openai_api_key", "sk-falsa"), ("anthropic_api_key", "sk-falsa"),
                             ("modelo_extraccion", OPUS), ("modelo_extraccion_fallback", ""),
                             ("modelo_juez_matching", ""), ("modelo_embeddings", EMBEDDINGS),
                             ("effort_llm", ""), ("juez_redaccion", True),
                             ("cita_checklist", True), ("asignacion_global", False),
                             ("threshold_descripcion", 0.85), ("threshold_accion", 0.85),
                             ("top_k_candidatos", 5), ("umbral_tokens_troceo", 900_000),
                             ("runs_a_retener", settings.runs_a_retener),
                             ("runs_incompletos_a_retener", settings.runs_incompletos_a_retener),
                             ("runs_dir", raiz / "runs")):
            mp.setattr(settings, campo, valor)
        linea = _Linea()
        anthropic = _AnthropicFalso(linea)
        openai_falso = _OpenAIFalso(linea)
        # Los falsos reemplazan a los clientes: ningún camino llega a un proveedor
        # (van encima de la guarda de sesión de tests/conftest.py; al salir, vuelve).
        mp.setattr(llm_client, "get_client_anthropic", lambda: anthropic)
        mp.setattr(llm_client, "get_client", lambda: openai_falso)
        mp.setattr(llm_embeddings, "get_client", lambda: openai_falso)
        mp.setattr(fichas, "RUTA_DEFAULT", raiz / "sin_fichas.yaml")

        caso = raiz / "informes_reales" / CARPETA
        caso.mkdir(parents=True)
        pdf = _crear_pdf(caso / "Informe Sintético.pdf")
        excel = _crear_excel(caso / "Tabla de Hallazgos Sintética.xlsx")
        planilla = _planilla(caso / "CheckList Revisión Sintética.xlsx")

        # GT del comparador desde una corrida previa con los mismos falsos, que
        # queda en mediciones/b2/runs como su fuente en la medición real.
        mp.setattr(settings, "runs_dir", med / "b2" / "runs")
        previo, run_previo = asyncio.run(
            ejecutar_pipeline(pdf, excel, EmpresaAuditora.RELIABLE_ENERGY))
        gt = med / "gt" / "comparador" / f"{CARPETA}.json"
        gt.parent.mkdir(parents=True)
        gt.write_text(serializar(_gt_sintetico(previo, _sha(pdf), _sha(excel), run_previo)),
                      "utf-8")

        ficha = {"fecha_planilla": "2026-10-20", "fecha_fuente": "conocida", "revisor": "R1",
                 "sha256_planilla": _sha(planilla),
                 "sha256_criterios_al_ingresar": version_codigo()["sha256_checklist_puntos.yaml"],
                 "con_herramienta": False, "uso": "prueba", "grupo": None, "nota": "sintética"}
        ruta_fichas = med / "fichas_informes.yaml"
        ruta_fichas.write_text(yaml.safe_dump({"version_fichas": "1.0",
                                               "informes": {CARPETA: ficha}},
                                              allow_unicode=True), encoding="utf-8")
        comunes = ["--modelos", OPUS, "--base", str(raiz / "informes_reales"),
                   "--informes", INFORME, "--fichas", str(ruta_fichas)]

        # B3: completo con la cita.
        anthropic.llm, linea.llamadas = _LLMB3(), []
        _correr_cli(mp, med / "b3" / "runs", [
            *comunes, "--etiqueta", "B3", "--salida", str(med / "b3" / "evaluacion_B3.json"),
            "--gt-comparador", str(gt.parent),
            "--codigo-congelado", str(copiar_src(med / "b3" / "src"))])
        linea_b3 = list(linea.llamadas)

        # B3s: solo el checklist, sin la cita.
        anthropic.llm, linea.llamadas = _LLMB3(), []
        _correr_cli(mp, med / "b3s" / "runs", [
            *comunes, "--etiqueta", "B3s", "--salida", str(med / "b3s" / "evaluacion_B3S.json"),
            "--solo-checklist", "--sin-cita-checklist",
            "--codigo-congelado", str(copiar_src(med / "b3s" / "src"))])
        linea_b3s = list(linea.llamadas)

        csv = raiz / "csv"
        resultado = generar(med, PRECIOS, csv)
        yield Ensayo(med, csv, resultado, ficha, gt, linea_b3, linea_b3s, anthropic)


# ------------------------------------------------------------ las preguntas de B3


def test_metricas_lote_reproduce_lo_guardado(ensayo: Ensayo) -> None:
    # El ensayo no clasifica los errores de su checklist (M09, alcance B3 Opus):
    # sin m09.json quedan a la vista como discrepancias. Ninguna otra.
    m09 = [d for d in ensayo.resultado.discrepancias if d.startswith("M09")]
    assert m09 and all("sin clasificar (falta adjudicacion_checklist/m09.json)" in d
                       for d in m09)
    assert [d for d in ensayo.resultado.discrepancias if not d.startswith("M09")] == []
    assert {f["ronda"] for f in ensayo.tabla("comparador_por_informe.csv")} == {"B3"}
    (comparador,) = ensayo.tabla("comparador_por_informe.csv")
    assert comparador["estado"] == "completo"


def test_version_del_codigo_es_la_copia_congelada(ensayo: Ensayo) -> None:
    for carpeta, etiqueta in (("b3", "B3"), ("b3s", "B3s")):
        congelado = hash_arbol(ensayo.mediciones / carpeta / "src")[0][:16]
        evaluacion = ensayo.evaluacion(carpeta)
        assert evaluacion["codigo_congelado"]["sha256_codigo"] == congelado
        assert evaluacion["version_codigo"]["sha256_codigo"] == congelado
        meta = json.loads((ensayo.run(carpeta) / "metadata.json").read_text("utf-8"))
        assert meta["version_codigo"]["sha256_codigo"] == congelado
        (ficha_version,) = ensayo.tabla("ficha_version.csv", version=etiqueta)
        assert ficha_version["sha256_codigo"] == congelado
        assert ficha_version["src"] == f"{carpeta}/src"
        assert ficha_version["archivos_distintos_del_actual"] == "0"


def test_la_clave_de_openai_se_probo_antes_de_claude_y_quedo_registrada(ensayo: Ensayo) -> None:
    # B3: la del lote y la del pipeline, las dos antes de la primera llamada a Claude.
    primera_claude = next(i for i, x in enumerate(ensayo.linea_b3) if x.startswith("claude"))
    assert ensayo.linea_b3[:primera_claude] == ["openai:1", "openai:1"]
    for prueba in (ensayo.evaluacion("b3")["prueba_clave_openai"], json.loads(
            (ensayo.run("b3") / "metadata.json").read_text("utf-8"))["prueba_clave_openai"]):
        assert (prueba["ok"], prueba["modelo"], prueba["modelo_servido"], prueba["tokens"]) == (
            True, EMBEDDINGS, EMBEDDINGS, 1)
    # B3s no pasa por E4: ni prueba ni embeddings.
    assert not [x for x in ensayo.linea_b3s if x.startswith("openai")]
    assert ensayo.evaluacion("b3s")["prueba_clave_openai"] is None
    meta_b3s = json.loads((ensayo.run("b3s") / "metadata.json").read_text("utf-8"))
    assert "prueba_clave_openai" not in meta_b3s


def test_cumples_bajados_por_falta_de_cita_contra_la_planilla(ensayo: Ensayo) -> None:
    (b3,) = ensayo.tabla("citas_checklist.csv", ronda="B3", escenario="planilla_al_medir")
    assert b3["cita_checklist"] == "True"
    assert (b3["bajados_sin_cita_verificada"], b3["puntos_bajados"]) == (
        "2", ";".join(map(str, sorted((P_FC, P_AC)))))
    assert (b3["bajados_que_eran_falso_cumple"], b3["bajados_que_eran_acierto"]) == ("1", "1")
    # B3s, sin la cita, no baja nada: el falso cumple que B3 evitó queda a la vista.
    assert ensayo.tabla("citas_checklist.csv", ronda="B3s") == []
    (b3s,) = ensayo.tabla("checklist_por_informe.csv", ronda="B3s")
    assert b3s["puntos_falso_cumple"] == str(P_FC)


def test_confianza_del_checklist_de_b3_y_b3s_por_separado(ensayo: Ensayo) -> None:
    filas = ensayo.tabla("confianza_checklist.csv", escenario="planilla_al_medir")
    assert sorted(f["ronda"] for f in filas) == ["B3", "B3s"]
    por_ronda = {f["ronda"]: f for f in filas}
    for ronda, (no_verificables, falsos_cumple) in (("B3", ("2", "0")), ("B3s", ("0", "1"))):
        f = por_ronda[ronda]
        assert (f["modelo"], f["informes"], f["evaluados"], f["muestra"]) == (
            OPUS, "1", "38", "fuera")
        assert (f["no_verificables"], f["falsos_cumple"]) == (no_verificables, falsos_cumple)
        assert f["veredictos_no_gt"] == "2" and f["incumplimientos_detectados"] == "1"


def test_tiempo_por_relojes(ensayo: Ensayo) -> None:
    """Con el checklist de B3s (sin la cita) junto al de B3 (con ella): lo que
    la cita cuesta en tiempo. El de B3s va marcado solo_checklist."""
    for ronda, modo in (("B3", "completo"), ("B3s", "solo_checklist")):
        (tiempo,) = ensayo.tabla("tiempo_por_informe.csv", ronda=ronda)
        assert (tiempo["fuente_tiempo"], tiempo["modo"]) == ("relojes", modo)
        assert float(tiempo["camino_critico_relojes"]) >= 0
        assert tiempo["t_checklist"] != ""
    (b3,) = ensayo.tabla("tiempo_por_informe.csv", ronda="B3")
    assert all(b3[c] != "" for c in ("t_e1", "t_e2", "t_e3", "t_e4", "t_e5"))


def test_comparador_contra_el_gt(ensayo: Ensayo) -> None:
    guardado = ensayo.fila("b3")["comparador_gt"]
    assert guardado["sha256_gt"] == _sha(ensayo.gt)
    assert guardado["adjudicados"] > 0 and guardado["A"] == 1 and guardado["D"] >= 1
    (fila,) = ensayo.tabla("comparador_gt_por_run.csv", ronda="B3")
    assert fila["evaluacion_guardada"] == "igual"
    assert "comparador_gt" not in ensayo.fila("b3s")


def test_extraccion_contra_el_gt(ensayo: Ensayo) -> None:
    por_campo = {f["campo"]: f for f in ensayo.tabla("extraccion_por_campo.csv", ronda="B3")}
    assert {f["fuente"] for f in por_campo.values()} == {"contra_gt"}
    # El «difiere» que el GT atribuye a E3 en la descripción.
    assert por_campo["descripcion"]["errores"] == "1"
    assert int(por_campo["tupla"]["correctos"]) > 0
    (tupla,) = ensayo.tabla("extraccion_por_tupla.csv", ronda="B3")
    # El «coincide» con redacción distinta que quedó fuera del GT: sin referencia.
    assert tupla["hallazgos_sin_referencia"] == "1"
    assert tupla["filas_excel_sin_referencia"] == "0"   # ninguna fila «extra» sin adjudicar
    assert ensayo.tabla("extraccion_por_campo.csv", ronda="B3s") == []


def test_modelo_pedido_y_servido(ensayo: Ensayo) -> None:
    b3 = ensayo.tabla("control_modelo_servido.csv", ronda="B3")
    assert {f["etapa"] for f in b3} >= {"checklist", "e1", "e3", "embeddings"}
    assert {f["estado"] for f in b3} == {"ok"}
    servidos = {f["etapa"]: f["modelos_servidos"] for f in b3}
    assert servidos["checklist"].startswith(OPUS) and servidos["embeddings"].startswith(EMBEDDINGS)
    b3s = ensayo.tabla("control_modelo_servido.csv", ronda="B3s")
    assert [(f["etapa"], f["estado"]) for f in b3s] == [("checklist", "ok")]
    # M20: cada petición a Opus 5.5 pidió el thinking adaptativo con el resumen.
    assert ensayo.anthropic.pedidos
    assert all(p["thinking"] == PEDIDO_M20["thinking"] for p in ensayo.anthropic.pedidos)


def test_razonamiento_resumen_de_opus_guardado_y_fuera_de_los_csv(ensayo: Ensayo) -> None:
    raws = [p for carpeta in ("b3", "b3s") for p in ensayo.run(carpeta).glob("*_raw/*.json")
            if p.name != "embeddings.json"]
    assert len(raws) > 5
    for raw in raws:
        meta = json.loads(raw.read_text("utf-8"))
        assert meta["razonamiento_resumen"] == [RESUMEN], raw
        assert meta["parametros_thinking"] == PEDIDO_M20, raw
        assert meta["modelo_servido"] == OPUS, raw
    for csv in ensayo.csv.glob("*.csv"):
        assert RESUMEN not in csv.read_text("utf-8"), csv.name


def test_vectores_de_e4_guardados(ensayo: Ensayo) -> None:
    run = ensayo.run("b3")
    vectores, modelo = cargar_vectores(run / "etapa4_embeddings.npz")
    e3 = [Hallazgo.model_validate(h) for h in json.loads(
        (run / "etapa3_pdf_hallazgos.json").read_text("utf-8"))]
    e2 = [Hallazgo.model_validate(h) for h in json.loads(
        (run / "etapa2_excel_normalizado.json").read_text("utf-8"))]
    assert modelo == EMBEDDINGS and list(vectores) == textos_a_embeber(e3, e2)
    assert llm_embeddings.PALABRA_PRUEBA not in vectores
    assert all(np.isfinite(v).all() for v in vectores.values())
    assert not list(ensayo.run("b3s").glob("*.npz"))


def test_ficha_copiada_y_muestra(ensayo: Ensayo) -> None:
    esperada = fichas.Ficha.model_validate(ensayo.ficha).model_dump(mode="json")
    for carpeta, ronda in (("b3", "B3"), ("b3s", "B3s")):
        assert ensayo.fila(carpeta)["ficha"] == esperada
        (fila,) = ensayo.tabla("checklist_por_informe.csv", ronda=ronda)
        assert (fila["muestra"], fila["estado"], fila["informe"]) == ("fuera", "evaluado",
                                                                      INFORME)


def test_costo_y_control_de_tokens(ensayo: Ensayo) -> None:
    # La prueba de la clave no es una llamada de E4: los tokens de cada etapa
    # siguen siendo la suma de sus raw.
    # B2 es la corrida fuente del GT (mediciones/b2/runs, sin evaluación).
    control = ensayo.tabla("control_tokens.csv")
    assert {f["ronda"] for f in control} == {"B2", "B3", "B3s"}
    assert {f["estado"] for f in control} == {"ok"}
    for ronda in ("B3", "B3s"):
        (costo,) = ensayo.tabla("costo_por_informe.csv", ronda=ronda)
        assert float(costo["costo_usd"]) > 0 and costo["estado_run"] == "completo"
        # El costo del checklist con y sin la cita, por separado.
        (checklist,) = ensayo.tabla("costo_por_informe_etapa.csv", ronda=ronda,
                                    etapa="checklist")
        assert float(checklist["costo_usd"]) > 0
