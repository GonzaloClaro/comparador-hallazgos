"""Ensayo con falsos de M43c (comparador.sensibilidad_checklist), sin API.

Como se correrá M43c, en un temporal: ``preparar-insumos`` del control con el PDF base,
``evaluar_lote --solo-checklist --checklist-batch`` sobre esos insumos (con la planilla
y su ficha), el catálogo escrito con el checklist del control, ``validar-catalogo``,
``preparar-insumos`` del recorte, ``evaluar_lote`` sobre el recorte y ``evaluar``. El
SDK de Anthropic es falso solo en la frontera (con la API de Batch, como en
``tests/test_preparacion_m61.py``) y su modelo lee el PDF que recibe: responde según
las páginas que tiene, así el recorte cambia lo que contesta. Comprueba que cada run
se identifica por el PDF que leyó y que cada blanco cae en su clase.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz
import pytest
import yaml

from comparador import sensibilidad_checklist as sc
from comparador.adjudicacion import nombre_corto
from comparador.config import settings
from comparador.etapa0_checklist import TOTAL_PUNTOS
from comparador.llm import client as llm_client
from comparador.persistence import version_codigo
from tests.test_integracion_pipeline import LLMFalso, _crear_excel
from tests.test_preparacion_b3 import CARPETA, OPUS, _correr_cli, _Linea, _planilla
from tests.test_preparacion_m61 import _AnthropicConBatch

PORTADA = "Informe de auditoría técnica de protecciones de la subestación sintética"
EV_MODELO = "Diagrama unilineal actualizado con todos los paños de la subestación"
EV_CITA = "Estudio de coordinación de protecciones vigente adjunto como anexo"
EV_ESCAPA = "Protocolo de pruebas de inyección secundaria de cada relé"
EV_OTRA = "Resumen de las pruebas de inyección realizadas en terreno a los relés"
ANEXO = "Anexo fotográfico de los tableros de control y protección"
PAGINAS = [PORTADA, EV_MODELO, EV_CITA, EV_ESCAPA, EV_OTRA, ANEXO]
QUITADAS = [2, 3, 4]
# El recorte deja las págs. 1, 5 y 6 del informe.
P_MODELO, P_CITA, P_ESCAPA, P_AFECTADO = 7, 12, 20, 25


def _paginas(pdf_base64: str) -> list[str]:
    with fitz.open(stream=base64.b64decode(pdf_base64), filetype="pdf") as doc:
        return [" ".join(p.get_text().split()) for p in doc]


class _LLMQueLee(LLMFalso):
    """Un checklist que depende de las páginas del PDF que recibe. Sin su evidencia:
    P_MODELO dice «no cumple» (lo detecta el modelo); P_CITA insiste en «cumple» con
    una cita que ya no está (lo baja el código); P_ESCAPA sigue en «cumple» con otra
    evidencia (escapa); P_AFECTADO, que cita la página de P_CITA, queda «no
    verificable». El resto, «cumple» con la portada."""

    @staticmethod
    def _checklist(kw: dict[str, Any]) -> dict[str, Any]:
        paginas = _paginas(kw["pdf_base64"])

        def donde(texto: str) -> int | None:
            return next((i for i, t in enumerate(paginas, start=1) if texto in t), None)

        items = []
        for n in range(1, TOTAL_PUNTOS + 1):
            resultado, cita = "cumple", (donde(PORTADA), PORTADA)
            if n == P_MODELO:
                p = donde(EV_MODELO)
                resultado, cita = ("cumple", (p, EV_MODELO)) if p else ("no_cumple", (None, ""))
            elif n == P_CITA:
                cita = (donde(EV_CITA) or 3, EV_CITA)
            elif n == P_ESCAPA:
                p = donde(EV_ESCAPA)
                cita = (p, EV_ESCAPA) if p else (donde(EV_OTRA), EV_OTRA)
            elif n == P_AFECTADO:
                p = donde(EV_CITA)
                resultado, cita = ("cumple", (p, EV_CITA)) if p else ("no_verificable", (None, ""))
            pagina, texto = cita
            items.append({"numero": n, "resultado": resultado, "referencia": None,
                          "paginas": str(pagina) if pagina else None,
                          "cita": {"pagina": pagina, "texto": texto} if pagina else None})
        return {"items": items}


def _sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _pdf(ruta: Path) -> Path:
    ruta.parent.mkdir(parents=True)
    doc = fitz.open()
    for texto in PAGINAS:
        doc.new_page().insert_textbox(fitz.Rect(40, 120, 560, 740), texto, fontsize=9)
    doc.save(ruta)
    return ruta


@dataclass
class Ensayo:
    m43c: Path
    mediciones: Path
    base: Path
    planilla: Path
    csv: Path
    anthropic: _AnthropicConBatch

    def run(self, grupo: str) -> Path:
        (fila,) = json.loads((self.m43c / grupo / "evaluacion_M43C.json").read_text("utf-8"))[
            "resultados"][OPUS]
        assert "error" not in fila, fila
        return self.m43c / grupo / "runs" / str(fila["run_id"])

    def json(self, nombre: str) -> dict[str, Any]:
        datos: dict[str, Any] = json.loads((self.m43c / nombre).read_text("utf-8"))
        return datos


def _lote(m43c: Path, grupo: str, fichas: Path) -> list[str]:
    return ["--modelos", OPUS, "--base", str(m43c / "insumos" / grupo), "--etiqueta", "M43c",
            "--salida", str(m43c / grupo / "evaluacion_M43C.json"), "--solo-checklist",
            "--checklist-batch", "--fichas", str(fichas)]


@pytest.fixture(scope="module")
def ensayo(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Ensayo]:
    raiz = tmp_path_factory.mktemp("ensayo_m43c")
    med = raiz / "mediciones"
    m43c = med / "m43c"
    with pytest.MonkeyPatch.context() as mp:
        for campo, valor in (("openai_api_key", ""), ("anthropic_api_key", "sk-falsa"),
                             ("modelo_extraccion", OPUS), ("modelo_extraccion_fallback", ""),
                             ("effort_llm", ""), ("cita_checklist", True),
                             ("checklist_batch", False), ("checklist_un_tramo", "marcar"),
                             ("umbral_tokens_troceo", 900_000),
                             ("runs_a_retener", settings.runs_a_retener),
                             ("runs_incompletos_a_retener", settings.runs_incompletos_a_retener)):
            mp.setattr(settings, campo, valor)
        anthropic = _AnthropicConBatch(_Linea())
        anthropic.llm = _LLMQueLee()
        mp.setattr(llm_client, "get_client_anthropic", lambda: anthropic)
        mp.setattr(llm_client, "_esperar", lambda s: None)

        # La carpeta del informe como en informes_reales/: el Word original (no se
        # copia), la Tabla de Hallazgos y la planilla, con su ficha.
        caso = raiz / "informes_reales" / CARPETA
        caso.mkdir(parents=True)
        (caso / "Informe Sintético.docx").write_bytes(b"el Word original: no se usa")
        _crear_excel(caso / "Tabla de Hallazgos Sintética.xlsx")
        planilla = _planilla(caso / "CheckList Revisión Sintética.xlsx")
        fichas = med / "fichas_informes.yaml"
        fichas.parent.mkdir(parents=True)
        fichas.write_text(yaml.safe_dump({"version_fichas": "1.0", "informes": {CARPETA: {
            "fecha_planilla": "2026-10-20", "fecha_fuente": "conocida", "revisor": "R1",
            "sha256_planilla": _sha(planilla),
            "sha256_criterios_al_ingresar": version_codigo()["sha256_checklist_puntos.yaml"],
            "con_herramienta": False, "uso": "prueba", "grupo": None, "nota": "sintética"}}},
            allow_unicode=True), encoding="utf-8")
        base = _pdf(raiz / "base" / "Informe Sintético.pdf")

        # El control: el PDF base entero.
        sc.main(["preparar-insumos", "--pdf", str(base), "--carpeta-informe", str(caso),
                 "--destino", str(m43c / "insumos" / "control")])
        _correr_cli(mp, m43c / "control" / "runs", _lote(m43c, "control", fichas))
        (fila,) = json.loads((m43c / "control" / "evaluacion_M43C.json").read_text("utf-8"))[
            "resultados"][OPUS]

        # El catálogo, con el checklist del control, antes de correr el recorte.
        catalogo = m43c / "catalogo.json"
        catalogo.write_text(sc.CatalogoChecklist(fecha="2026-10-27", recortes=[sc.Recorte(
            id="SIN-A", informe=nombre_corto(CARPETA), carpeta=CARPETA, grupo="recorte_a",
            pdf_base_sha256=_sha(base), run_control=fila["run_id"], paginas_quitadas=QUITADAS,
            blancos=[sc.Blanco(punto=P_MODELO, paginas_cita=[2]),
                     sc.Blanco(punto=P_CITA, paginas_cita=[3]),
                     sc.Blanco(punto=P_ESCAPA, paginas_cita=[4])],
            afectados=[P_AFECTADO], nota="ensayo")]).model_dump_json(indent=2), "utf-8")
        sc.main(["validar-catalogo", "--catalogo", str(catalogo), "--control",
                 str(m43c / "control"), "--pdfs", str(base.parent), "--salida",
                 str(m43c / "validacion.json")])

        # El recorte y su corrida.
        sc.main(["preparar-insumos", "--pdf", str(base), "--carpeta-informe", str(caso),
                 "--destino", str(m43c / "insumos" / "recorte_a"), "--recorte", "SIN-A",
                 "--catalogo", str(catalogo)])
        _correr_cli(mp, m43c / "recorte_a" / "runs", _lote(m43c, "recorte_a", fichas))

        salida_csv = raiz / "sensibilidad_m43c.csv"
        sc.main(["evaluar", "--catalogo", str(catalogo), "--control", str(m43c / "control"),
                 "--recortes", str(m43c / "recorte_a"), "--insumos", str(m43c / "insumos"),
                 "--json", str(m43c / "evaluacion.json"), "--csv", str(salida_csv)])
        yield Ensayo(m43c, med, base, planilla, salida_csv, anthropic)


def test_el_control_leyo_el_pdf_base_con_la_planilla_y_su_ficha(ensayo: Ensayo) -> None:
    run = ensayo.run("control")
    assert (run / "input_pdf.hash").read_text("utf-8") == _sha(ensayo.base)
    inputs = json.loads((run / "inputs.json").read_text("utf-8"))
    assert (inputs["informe"], inputs["modo"]) == ("Informe Sintético.pdf", "solo_checklist")
    meta = json.loads((run / "metadata.json").read_text("utf-8"))
    assert meta["checklist_batch"] is True and meta["cita_checklist"] is True
    (fila,) = json.loads((ensayo.m43c / "control" / "evaluacion_M43C.json")
                         .read_text("utf-8"))["resultados"][OPUS]
    # La planilla copiada byte a byte vale con la ficha del informe original.
    assert fila["ficha"]["sha256_planilla"] == _sha(ensayo.planilla)
    assert fila["checklist_gt"]["evaluados"] > 0


def test_el_catalogo_valido(ensayo: Ensayo) -> None:
    validacion = ensayo.json("validacion.json")
    assert validacion["ok"] is True, validacion
    (recorte,) = validacion["recortes"]
    assert [(b["punto"], b["paginas_que_respaldan"]) for b in recorte["blancos"]] == [
        (P_MODELO, [2]), (P_CITA, [3]), (P_ESCAPA, [4])]


def test_el_recorte_es_el_pdf_que_leyo_el_modelo(ensayo: Ensayo) -> None:
    run = ensayo.run("recorte_a")
    mapa = sc.Mapa.model_validate_json(
        (ensayo.m43c / "insumos" / "recorte_a" / "mapas" / "SIN-A.json").read_text("utf-8"))
    assert (run / "input_pdf.hash").read_text("utf-8") == mapa.sha256_recorte
    assert mapa.pagina_original == {1: 1, 2: 5, 3: 6}
    # Lo que recibió el modelo en el último lote: las tres páginas que quedan.
    (pedido,) = ensayo.anthropic.lotes[-1]["requests"]
    (documento,) = [b for b in pedido["params"]["messages"][0]["content"]
                    if b["type"] == "document"]
    assert _paginas(documento["source"]["data"]) == [PORTADA, EV_OTRA, ANEXO]


def test_cada_blanco_en_su_clase(ensayo: Ensayo) -> None:
    (recorte,) = ensayo.json("evaluacion.json")["recortes"]
    clases = {b["punto"]: b["clase"] for b in recorte["blancos"]}
    assert clases == {P_MODELO: "detectado_modelo", P_CITA: "detectado_cita",
                      P_ESCAPA: "escapado"}
    escapado = next(b for b in recorte["blancos"] if b["punto"] == P_ESCAPA)
    assert [(c["pagina"], c["pagina_original"], c["estado"]) for c in escapado["citas_recorte"]
            ] == [(2, 5, "verificada")]
    assert recorte["afectados"] == [{"punto": P_AFECTADO, "control": "cumple",
                                     "recorte": "no_verificable", "cambio": True}]
    assert recorte["cambios_fuera_de_los_blancos"] == []
    assert [b["motivos_no_evaluable"] for b in recorte["blancos"]] == [[], [], []]
    # El control y el recorte corrieron con el mismo código y el mismo pedido al modelo,
    # y el pipeline real guarda todo lo que se compara.
    for grupo in ("control", "recorte_a"):
        run = ensayo.run(grupo)
        meta = json.loads((run / "metadata.json").read_text("utf-8"))
        assert recorte["sha256_codigo"] == meta["version_codigo"]["sha256_codigo"]
        raw = json.loads((run / sc.RAW_CHECKLIST).read_text("utf-8"))
        assert set(sc.LLAMADA_COMPARABLE) <= set(raw), sorted(raw)
        assert raw["system_prompt"] and raw["user_prompt_text"]


def test_el_csv_agregado_y_metricas_lote(ensayo: Ensayo) -> None:
    with ensayo.csv.open(encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    assert [(f["clase"], f["blancos"]) for f in filas] == [
        ("detectado_modelo", "1"), ("detectado_cita", "1"), ("escapado", "1"),
        ("no_evaluable", "0"), ("total", "3")]
    assert {(f["informe"], f["recorte"], f["grupo"]) for f in filas} == {
        ("Sintética", "SIN-A", "recorte_a")}
    assert (filas[-1]["afectados_cambiados"], filas[-1]["cambios_fuera"]) == ("1", "0")
    texto = ensayo.csv.read_text("utf-8")
    assert not [t for t in PAGINAS if t in texto]
    # metricas_lote lo regenera desde mediciones/ con el mismo resultado.
    assert [{k: str(v) for k, v in f.items()}
            for f in sc.filas_desde_mediciones(ensayo.mediciones)] == filas
