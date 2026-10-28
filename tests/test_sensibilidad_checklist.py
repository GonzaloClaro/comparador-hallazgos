"""M43c: sensibilidad del checklist a la falta de evidencia
(comparador.sensibilidad_checklist). Sin API: PDF, DOCX, checklists y runs sintéticos."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz
import pytest
from pydantic import ValidationError

from comparador import sensibilidad_checklist as sc
from comparador.citas import PaginasPdf, verificar_cita
from comparador.convertir import convertir_docx_a_pdf
from comparador.etapa0_checklist import TOTAL_PUNTOS
from comparador.evaluar_lote import descubrir_casos
from comparador.schemas import (
    CausaAjuste,
    ChecklistInforme,
    CitaChecklist,
    EstadoCita,
    ItemChecklist,
    ResultadoChecklist,
    VerificacionCita,
)

CARPETA = "S-E Prueba (Auditor Reliable Energy)"
RUN_C = "2026-10-27_10-00-00_claude-opus-5-5"
OPUS = "claude-opus-5-5"

# Páginas del PDF base: la 5 repite el texto de la 4 (una cita que el recorte no quita).
PORTADA = "Portada del informe de auditoría técnica de protecciones"
UNILINEAL = "Diagrama unilineal actualizado de la subestación con todos los paños"
ESTUDIO = "Estudio de coordinación de protecciones vigente adjunto al informe"
PRUEBAS = "Registro de pruebas de inyección secundaria realizadas en terreno"
CALIBRACION = "Certificados de calibración vigentes de los equipos de prueba utilizados"
FOTOS = "Anexo de fotografías de los tableros de control y protección"
PAGINAS = [PORTADA, UNILINEAL, ESTUDIO, PRUEBAS, f"{PRUEBAS}\n{CALIBRACION}", FOTOS]


def _sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _pdf(ruta: Path, textos: list[str]) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for texto in textos:
        doc.new_page().insert_textbox(fitz.Rect(40, 120, 560, 740), texto, fontsize=9)
    doc.save(ruta)
    return ruta


def _item(numero: int, resultado: str, citas: list[tuple[int, str]], pp: PaginasPdf,
          **extra: Any) -> ItemChecklist:
    """Un ítem con sus citas verificadas contra el PDF como en la Etapa 0."""
    verificadas = []
    for pagina, texto in citas:
        v = verificar_cita(pp, texto, pagina, (1, pp.total))
        verificadas.append(CitaChecklist(
            pagina=v.pagina if v.estado == EstadoCita.EN_OTRA_PAGINA else pagina, texto=texto,
            verificacion=v))
    paginas = ", ".join(str(p) for p, _ in citas) or None
    return ItemChecklist(numero=numero, enunciado=f"Punto {numero}",
                         resultado=ResultadoChecklist(resultado), paginas=paginas,
                         citas=verificadas, **extra)


def _checklist(pdf: Path, cambios: dict[int, tuple[str, list[tuple[int, str]]]] | None = None,
               extra: dict[int, dict[str, Any]] | None = None) -> ChecklistInforme:
    """38 «cumple» que citan la portada, salvo `cambios` (resultado y citas por punto)."""
    cambios, extra = cambios or {}, extra or {}
    with PaginasPdf(pdf) as pp:
        items = [_item(n, *cambios.get(n, ("cumple", [(1, PORTADA)])), pp, **extra.get(n, {}))
                 for n in range(1, TOTAL_PUNTOS + 1)]
    return ChecklistInforme(items=items, total=TOTAL_PUNTOS, cumplen=sum(
        i.resultado == ResultadoChecklist.CUMPLE for i in items), bajados_sin_cita_verificada=0)


# El control: el 2, el 3 y el 6 citan su página; el 4 cita un texto que también está
# en la 5; el 5 es «no cumple» sin cita y dice apoyarse en la 6.
CONTROL = {2: ("cumple", [(2, UNILINEAL)]), 3: ("cumple", [(3, ESTUDIO)]),
           4: ("cumple", [(4, PRUEBAS)]), 6: ("cumple", [(6, FOTOS)])}


def _control(pdf: Path, cambios: dict[int, tuple[str, list[tuple[int, str]]]] | None = None
             ) -> ChecklistInforme:
    cl = _checklist(pdf, {**CONTROL, **(cambios or {})})
    items = [i.model_copy(update={"resultado": ResultadoChecklist.NO_CUMPLE, "paginas": "6",
                                  "citas": []}) if i.numero == 5 else i for i in cl.items]
    return cl.model_copy(update={"items": items})


def _metadata(modelo: str = OPUS) -> dict[str, Any]:
    return {"modo": "solo_checklist", "modelo_extraccion": modelo, "cita_checklist": True,
            "checklist_un_tramo": "marcar",
            "version_codigo": {"sha256_codigo": "a" * 16,
                               "sha256_checklist_puntos.yaml": "b" * 16}}


def _raw() -> dict[str, Any]:
    """La llamada del checklist como la guarda el run (checklist_raw/verificar_checklist.json)."""
    return {"modelo": OPUS, "modelo_servido": OPUS, "system_prompt": "Eres un revisor",
            "user_prompt_text": "Verifica los siguientes 38 puntos",
            "parametros_thinking": {"thinking": {"type": "adaptive", "display": "summarized"}},
            "schema_sha256": "c" * 64, "response_raw": {"items": []}}


def _guardar_run(carpeta: Path, run_id: str, checklist: ChecklistInforme | None, sha: str,
                 metadata: dict[str, Any] | None = None) -> Path:
    run = carpeta / "runs" / run_id
    (run / "checklist_raw").mkdir(parents=True)
    (run / "input_pdf.hash").write_text(sha, encoding="utf-8")
    (run / "metadata.json").write_text(json.dumps(metadata or _metadata()), encoding="utf-8")
    (run / "checklist_raw" / "verificar_checklist.json").write_text(json.dumps(_raw()), "utf-8")
    if checklist is not None:
        (run / "checklist.json").write_text(checklist.model_dump_json(), encoding="utf-8")
    else:
        (run / "error.json").write_text(json.dumps({"mensaje": "Lote vencido"}), "utf-8")
    return run


def _recorte(**cambios: Any) -> dict[str, Any]:
    return {"id": "PRU-A", "informe": "Prueba", "carpeta": CARPETA, "grupo": "recorte_a",
            "pdf_base_sha256": "0" * 64, "run_control": RUN_C, "paginas_quitadas": [2],
            "blancos": [{"punto": 2, "paginas_cita": [2]}], "afectados": [],
            "nota": "sintético", **cambios}


def _catalogo(*recortes: dict[str, Any]) -> sc.CatalogoChecklist:
    return sc.CatalogoChecklist.model_validate({"fecha": "2026-10-27",
                                                "recortes": list(recortes)})


# ---------------------------------------------------------------------- catálogo


class TestCatalogo:
    def test_un_catalogo_valido(self) -> None:
        catalogo = _catalogo(_recorte(), _recorte(id="PRU-B", grupo="recorte_b",
                                                  paginas_quitadas=[2, 3], afectados=[3]))
        assert catalogo.recorte("PRU-B").declarados == {2, 3}
        with pytest.raises(sc.CatalogoInvalidoError, match="no tiene el recorte"):
            catalogo.recorte("NADA")

    @pytest.mark.parametrize(("recortes", "mensaje"), [
        ([_recorte(), _recorte(grupo="recorte_b")], "ids repetidos"),
        ([_recorte(), _recorte(id="PRU-B")], "más de un recorte por informe y grupo"),
        ([_recorte(blancos=[{"punto": 2, "paginas_cita": [2, 5]}])],
         r"páginas de cita \[5\] no están entre las paginas_quitadas"),
        ([_recorte(afectados=[2])], r"los puntos \[2\] son blanco y afectado"),
        ([_recorte(blancos=[{"punto": 2, "paginas_cita": [2]}] * 2)], "blancos repetidos"),
        ([_recorte(afectados=[3, 3])], "afectados repetidos"),
        ([_recorte(paginas_quitadas=[3, 2])], "sin repetir y en orden"),
        ([_recorte(paginas_quitadas=[2, 2])], "sin repetir y en orden"),
        ([_recorte(informe="Otro")], "no es el nombre corto"),
        ([_recorte(blancos=[{"punto": 39, "paginas_cita": [2]}])], "less than or equal"),
        ([_recorte(paginas_quitadas=[0])], "greater than or equal"),
        ([_recorte(extra="x")], "Extra inputs are not permitted"),
        ([_recorte(id="con espacio")], "pattern"),
        ([], "at least 1 item"),
    ])
    def test_fallas_ruidosas(self, recortes: list[dict[str, Any]], mensaje: str) -> None:
        with pytest.raises(ValidationError, match=mensaje):
            _catalogo(*recortes)

    def test_es_inmutable(self) -> None:
        with pytest.raises(ValidationError, match="frozen"):
            _catalogo(_recorte()).recortes[0].nota = "otra"  # type: ignore[misc]

    def test_cargar_falla_con_el_archivo(self, tmp_path: Path) -> None:
        ruta = tmp_path / "catalogo.json"
        ruta.write_text(json.dumps({"fecha": "2026-10-27",
                                    "recortes": [_recorte(afectados=[2])]}), "utf-8")
        with pytest.raises(sc.CatalogoInvalidoError, match="(?s)catalogo.json.*blanco y afectado"):
            sc.cargar_catalogo(ruta)
        ruta.write_text(_catalogo(_recorte()).model_dump_json(), "utf-8")
        assert sc.cargar_catalogo(ruta) == _catalogo(_recorte())


# ---------------------------------------------------------------------- preparar


@dataclass
class Origen:
    carpeta: Path
    pdf: Path
    excel: Path
    planilla: Path


@pytest.fixture
def origen(tmp_path: Path) -> Origen:
    carpeta = tmp_path / "informes_reales" / CARPETA
    carpeta.mkdir(parents=True)
    (carpeta / "Informe Prueba.docx").write_bytes(b"docx original")
    excel = carpeta / "Tabla de Hallazgos Prueba.xlsx"
    excel.write_bytes(b"excel \x00 original")
    planilla = carpeta / "CheckList Revisión Prueba.xlsx"
    planilla.write_bytes(b"planilla \x01 original")
    (carpeta / "~$Tabla de Hallazgos Prueba.xlsx").write_bytes(b"bloqueo de Office")
    pdf = _pdf(tmp_path / "base" / "Informe Prueba.pdf", [f"Página {i}: {t}" for i, t in
                                                          enumerate(PAGINAS[:5], start=1)])
    return Origen(carpeta, pdf, excel, planilla)


def _recorte_de(origen: Origen, **cambios: Any) -> sc.Recorte:
    return sc.Recorte.model_validate(_recorte(pdf_base_sha256=_sha(origen.pdf), **cambios))


def _textos(pdf: Path) -> list[str]:
    with fitz.open(pdf) as doc:
        return [" ".join(p.get_text().split()) for p in doc]


class TestPrepararInsumos:
    def test_control_copia_byte_a_byte_sin_el_docx_y_no_pisa(
            self, origen: Origen, tmp_path: Path) -> None:
        destino = tmp_path / "insumos" / "control"
        caso = sc.preparar_insumos(origen.pdf, origen.carpeta, destino)
        assert caso == destino / CARPETA
        assert sorted(f.name for f in caso.iterdir()) == [
            "CheckList Revisión Prueba.xlsx", "Informe Prueba.pdf",
            "Tabla de Hallazgos Prueba.xlsx"]
        for original in (origen.pdf, origen.excel, origen.planilla):
            assert (caso / original.name).read_bytes() == original.read_bytes()
        # evaluar_lote lo toma como caso, con el PDF como informe y la planilla.
        (encontrado,), omitidas = descubrir_casos(destino)
        assert omitidas == []
        assert (encontrado["informe"].name, encontrado["excel"].name, encontrado["gt"].name) == (
            "Informe Prueba.pdf", origen.excel.name, origen.planilla.name)
        with pytest.raises(FileExistsError, match="no se pisa"):
            sc.preparar_insumos(origen.pdf, origen.carpeta, destino)

    def test_recorte_con_pypdf_y_su_mapa(self, origen: Origen, tmp_path: Path) -> None:
        destino = tmp_path / "insumos" / "recorte_a"
        recorte = _recorte_de(origen, paginas_quitadas=[2, 4],
                              blancos=[{"punto": 2, "paginas_cita": [2]}])
        caso = sc.preparar_insumos(origen.pdf, origen.carpeta, destino, recorte)
        pdf = caso / "Informe Prueba - PRU-A.pdf"
        assert _textos(pdf) == [f"Página {i}: {' '.join(PAGINAS[i - 1].split())}"
                                for i in (1, 3, 5)]
        mapa = sc.Mapa.model_validate_json((destino / "mapas" / "PRU-A.json").read_text("utf-8"))
        assert mapa.pagina_original == {1: 1, 2: 3, 3: 5}
        assert (mapa.sha256_pdf_base, mapa.sha256_recorte) == (_sha(origen.pdf), _sha(pdf))
        assert (mapa.paginas_base, mapa.paginas_quitadas, mapa.carpeta) == (5, [2, 4], CARPETA)
        # El mapa queda fuera de la carpeta del informe: evaluar_lote la salta con su motivo.
        (encontrado,), omitidas = descubrir_casos(destino)
        assert encontrado["informe"] == pdf
        assert [o.carpeta for o in omitidas] == ["mapas"]
        with pytest.raises(FileExistsError, match="no se pisa"):
            sc.preparar_insumos(origen.pdf, origen.carpeta, destino, recorte)
        # Tampoco pisa el mapa de una preparación anterior en el mismo destino.
        shutil.rmtree(caso)
        with pytest.raises(FileExistsError, match="PRU-A.json ya existe"):
            sc.preparar_insumos(origen.pdf, origen.carpeta, destino, recorte)
        assert not caso.exists()

    @pytest.mark.parametrize(("cambios", "mensaje"), [
        ({"pdf_base_sha256": "f" * 64}, "no es el PDF base del catálogo"),
        ({"paginas_quitadas": [2, 9]}, r"tiene 5 páginas: no se pueden quitar \[9\]"),
        ({"paginas_quitadas": [1, 2, 3, 4, 5],
          "blancos": [{"punto": 2, "paginas_cita": [2]}]}, "quitaría las 5 páginas"),
        ({"carpeta": "S-E Otra (Auditor Reliable Energy)", "informe": "Otra"},
         "es de la carpeta"),
    ])
    def test_fallas_ruidosas_antes_de_escribir(
            self, origen: Origen, tmp_path: Path, cambios: dict[str, Any], mensaje: str) -> None:
        recorte = sc.Recorte.model_validate(
            _recorte(**{"pdf_base_sha256": _sha(origen.pdf), **cambios}))
        destino = tmp_path / "insumos" / "recorte_a"
        with pytest.raises(sc.CatalogoInvalidoError, match=mensaje):
            sc.preparar_insumos(origen.pdf, origen.carpeta, destino, recorte)
        assert not destino.exists()

    def test_dos_excel_de_hallazgos_falla(self, origen: Origen, tmp_path: Path) -> None:
        shutil.copy(origen.excel, origen.carpeta / "Tabla de Hallazgos v2.xlsx")
        with pytest.raises(sc.CatalogoInvalidoError, match="un Excel de hallazgos y hay 2"):
            sc.preparar_insumos(origen.pdf, origen.carpeta, tmp_path / "insumos")

    def test_sin_planilla_copia_solo_el_excel(self, origen: Origen, tmp_path: Path) -> None:
        origen.planilla.unlink()
        caso = sc.preparar_insumos(origen.pdf, origen.carpeta, tmp_path / "insumos")
        assert sorted(f.name for f in caso.iterdir()) == [
            "Informe Prueba.pdf", "Tabla de Hallazgos Prueba.xlsx"]

    def test_cli(self, origen: Origen, tmp_path: Path) -> None:
        catalogo = tmp_path / "catalogo.json"
        catalogo.write_text(sc.CatalogoChecklist(
            fecha="2026-10-27", recortes=[_recorte_de(origen)]).model_dump_json(), "utf-8")
        destino = tmp_path / "insumos" / "recorte_a"
        with pytest.raises(SystemExit) as salida:
            sc.main(["preparar-insumos", "--pdf", str(origen.pdf), "--carpeta-informe",
                     str(origen.carpeta), "--destino", str(destino), "--recorte", "PRU-A"])
        assert salida.value.code == 2   # --recorte necesita --catalogo
        argumentos = ["preparar-insumos", "--pdf", str(origen.pdf), "--carpeta-informe",
                      str(origen.carpeta), "--destino", str(destino), "--recorte", "PRU-A",
                      "--catalogo", str(catalogo)]
        sc.main(argumentos)
        assert (destino / "mapas" / "PRU-A.json").is_file()
        with pytest.raises(SystemExit, match="no se pisa"):
            sc.main(argumentos)


# ---------------------------------------------------------------------- validar


@dataclass
class Control:
    pdf: Path
    runs: Path


@pytest.fixture
def control(tmp_path: Path) -> Control:
    pdf = _pdf(tmp_path / "base" / "Informe Prueba.pdf", PAGINAS)
    _guardar_run(tmp_path / "control", RUN_C, _control(pdf), _sha(pdf))
    return Control(pdf, tmp_path / "control")


def _validar(control: Control, **cambios: Any) -> sc.ValidacionRecorte:
    catalogo = _catalogo(_recorte(pdf_base_sha256=_sha(control.pdf), **cambios))
    resultado = sc.validar_catalogo(catalogo, control.runs, [control.pdf.parent])
    (recorte,) = resultado.recortes
    assert resultado.ok == recorte.ok
    return recorte


def _reescribir_control(control: Control,
                        cambios: dict[int, tuple[str, list[tuple[int, str]]]]) -> None:
    ruta = control.runs / "runs" / RUN_C / "checklist.json"
    ruta.write_text(_control(control.pdf, cambios).model_dump_json(), "utf-8")


# Citas partidas entre el final de una página y el comienzo de la siguiente (una fila
# de tabla cortada por el salto de página): la A solo así (págs. 3-4); la B entera en
# la 2 y partida en las 5-6.
PARTIDA_A = ("Ajustes de la función de sobrecorriente", "revisados y aprobados por el coordinado")
PARTIDA_B = ("Tiempos de despeje medidos en cada paño", "dentro de los límites de la norma técnica")


def _pdf_partido(ruta: Path) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    cuerpo = fitz.Rect(40, 300, 560, 740)
    for arriba, texto, abajo in (
            (None, PORTADA, None), (None, f"{UNILINEAL}\n{' '.join(PARTIDA_B)}", None),
            (None, ESTUDIO, PARTIDA_A[0]), (PARTIDA_A[1], CALIBRACION, None),
            (None, FOTOS, PARTIDA_B[0]), (PARTIDA_B[1], PRUEBAS, None)):
        pagina = doc.new_page()
        pagina.insert_textbox(cuerpo if arriba else fitz.Rect(40, 120, 560, 400), texto,
                              fontsize=9)
        if arriba:
            pagina.insert_text((40, 130), arriba, fontsize=9)
        if abajo:
            pagina.insert_text((40, 700), abajo, fontsize=9)
    doc.save(ruta)
    return ruta


class TestValidarCatalogo:
    def test_la_cita_solo_en_la_pagina_quitada_vale(self, control: Control) -> None:
        v = _validar(control)
        assert v.ok, v
        (blanco,) = v.blancos
        assert (blanco.resultado_control, blanco.paginas_que_respaldan) == ("cumple", [2])
        assert v.citas_no_declaradas == [] and v.avisos == []

    def test_la_cita_repetida_en_una_pagina_que_queda_falla(self, control: Control) -> None:
        v = _validar(control, paginas_quitadas=[4], blancos=[{"punto": 4, "paginas_cita": [4]}])
        assert not v.ok
        (problema,) = v.blancos[0].problemas
        assert "sigue en el recorte (págs. originales [5])" in problema

    def test_cita_de_otro_punto_en_una_pagina_quitada(self, control: Control) -> None:
        v = _validar(control, paginas_quitadas=[2, 3])
        assert not v.ok and v.blancos[0].ok
        assert [(c.punto, c.paginas) for c in v.citas_no_declaradas] == [(3, [3])]
        # Declarado como afectado, vale.
        assert _validar(control, paginas_quitadas=[2, 3], afectados=[3]).ok

    def test_toda_cita_de_otro_punto_aunque_no_respalde(self, control: Control) -> None:
        # Una cita que no se encontró (la página es la que dio el modelo) también cuenta:
        # sin esa página el modelo puede contestar otra cosa.
        _reescribir_control(control, {8: ("no_verificable", [
            (2, "Texto que no aparece en ninguna página del informe")])})
        v = _validar(control)
        assert not v.ok and v.blancos[0].ok
        assert [(c.punto, c.paginas) for c in v.citas_no_declaradas] == [(8, [2])]

    def test_una_cita_en_varias_paginas_las_toca_todas(self, control: Control) -> None:
        # La del punto 9 está en las págs. 4 y 5 y no en la citada: la Etapa 0 no le
        # guarda página. Quitar la 5 la deja en una sola y pasa a respaldar.
        _reescribir_control(control, {9: ("cumple", [(1, PRUEBAS)])})
        cl = sc.cargar_checklist(control.runs / "runs" / RUN_C / "checklist.json")
        (cita,) = cl.items[8].citas
        assert cita.pagina is None and cita.verificacion is not None
        assert (cita.verificacion.estado, cita.verificacion.pagina) == (
            EstadoCita.EN_OTRA_PAGINA, None)
        v = _validar(control, paginas_quitadas=[2, 5])
        assert not v.ok and v.blancos[0].ok
        assert [(c.punto, c.paginas) for c in v.citas_no_declaradas] == [(9, [5])]
        assert _validar(control, paginas_quitadas=[2, 5], afectados=[9]).ok

    def test_una_cita_partida_respalda_en_las_dos_paginas(self, tmp_path: Path) -> None:
        pdf = _pdf_partido(tmp_path / "base" / "Informe Prueba.pdf")
        cl = _checklist(pdf, {2: ("cumple", [(3, " ".join(PARTIDA_A))])})
        assert cl.items[1].citas[0].verificacion == VerificacionCita(
            estado=EstadoCita.CONTINUA_PAGINA_SIGUIENTE, pagina=3)
        _guardar_run(tmp_path / "control", RUN_C, cl, _sha(pdf))
        control = Control(pdf, tmp_path / "control")
        v = _validar(control, paginas_quitadas=[3], blancos=[{"punto": 2, "paginas_cita": [3]}])
        assert v.blancos[0].problemas == [
            "cita que respalda en las páginas [4], fuera de paginas_cita [3]: el recorte le deja "
            "evidencia"]
        v = _validar(control, paginas_quitadas=[3, 4],
                     blancos=[{"punto": 2, "paginas_cita": [3, 4]}])
        assert v.ok, v
        assert v.blancos[0].paginas_que_respaldan == [3, 4]

    def test_la_cita_queda_partida_en_el_recorte(self, tmp_path: Path) -> None:
        # Entera en la 2 (verificada, sin repetir) y partida en las 5-6, que quedan.
        pdf = _pdf_partido(tmp_path / "base" / "Informe Prueba.pdf")
        cl = _checklist(pdf, {2: ("cumple", [(2, " ".join(PARTIDA_B))])})
        assert cl.items[1].citas[0].verificacion == VerificacionCita(
            estado=EstadoCita.VERIFICADA, pagina=2)
        _guardar_run(tmp_path / "control", RUN_C, cl, _sha(pdf))
        v = _validar(Control(pdf, tmp_path / "control"))
        assert v.blancos[0].problemas == [
            "la cita de la p. 2 sigue en el recorte (págs. originales [5])"]

    def test_un_blanco_que_no_es_cumple(self, control: Control) -> None:
        v = _validar(control, paginas_quitadas=[6],
                     blancos=[{"punto": 5, "paginas_cita": [6]}], afectados=[6])
        assert v.blancos[0].problemas == [
            "el control no da «cumple» (no_cumple)",
            "el control no trae una cita verificada que respalde el «cumple»"]

    def test_cita_que_respalda_fuera_de_paginas_cita(self, control: Control) -> None:
        v = _validar(control, paginas_quitadas=[5, 6],
                     blancos=[{"punto": 6, "paginas_cita": [5]}])
        assert not v.ok
        assert v.blancos[0].problemas == [
            "cita que respalda en las páginas [6], fuera de paginas_cita [5]: el recorte le deja "
            "evidencia"]

    def test_cumple_bajado_por_cita_corta_no_es_blanco(
            self, control: Control, tmp_path: Path) -> None:
        # «cumple» con una cita verificada de 3 palabras: no lo respalda (cita_respalda).
        cl = _checklist(control.pdf, {2: ("cumple", [(2, "Diagrama unilineal actualizado")])})
        shutil.rmtree(control.runs)
        _guardar_run(control.runs, RUN_C, cl, _sha(control.pdf))
        assert _validar(control).blancos[0].problemas == [
            "el control no trae una cita verificada que respalde el «cumple»"]

    def test_aviso_de_un_punto_que_dice_apoyarse_en_la_pagina(self, control: Control) -> None:
        v = _validar(control, paginas_quitadas=[6], blancos=[{"punto": 6, "paginas_cita": [6]}])
        assert v.ok
        assert v.avisos == ["punto 5 (no_cumple): sus páginas (6) incluyen las quitadas [6] sin "
                            "citarlas"]

    def test_el_control_debe_haber_leido_el_pdf_base(self, control: Control) -> None:
        (control.runs / "runs" / RUN_C / "input_pdf.hash").write_text("e" * 64, "utf-8")
        v = _validar(control)
        assert not v.ok and "leyó otro PDF" in v.problemas[0]

    def test_sin_el_pdf_base_entre_los_dados(self, control: Control, tmp_path: Path) -> None:
        catalogo = _catalogo(_recorte(pdf_base_sha256=_sha(control.pdf)))
        otro = _pdf(tmp_path / "otros" / "x.pdf", ["otro informe cualquiera de prueba"])
        resultado = sc.validar_catalogo(catalogo, control.runs, [otro])
        assert not resultado.ok and "no está el PDF base" in resultado.recortes[0].problemas[0]

    def test_un_control_leido_por_partes(self, control: Control) -> None:
        ruta = control.runs / "runs" / RUN_C / "checklist.json"
        cl = ChecklistInforme.model_validate_json(ruta.read_text("utf-8"))
        ruta.write_text(cl.model_copy(update={"tramos_leidos": [(1, 3), (4, 6)]})
                        .model_dump_json(), "utf-8")
        v = _validar(control)
        assert not v.ok and "se leyó por partes" in v.problemas[0]

    def test_cli(self, control: Control, tmp_path: Path) -> None:
        catalogo = tmp_path / "catalogo.json"
        salida = tmp_path / "validacion.json"
        comunes = ["validar-catalogo", "--catalogo", str(catalogo), "--control",
                   str(control.runs), "--pdfs", str(control.pdf), "--salida", str(salida)]
        catalogo.write_text(_catalogo(_recorte(pdf_base_sha256=_sha(control.pdf)))
                            .model_dump_json(), "utf-8")
        sc.main(comunes)
        assert json.loads(salida.read_text("utf-8"))["ok"] is True
        catalogo.write_text(_catalogo(_recorte(pdf_base_sha256=_sha(control.pdf),
                                               paginas_quitadas=[2, 3])).model_dump_json(), "utf-8")
        with pytest.raises(SystemExit, match="no es válido") as error:
            sc.main(comunes)
        assert error.value.code != 0
        assert json.loads(salida.read_text("utf-8"))["ok"] is False


# ---------------------------------------------------------------------- evaluar


@dataclass
class Escenario:
    mediciones: Path
    m43c: Path
    catalogo: sc.CatalogoChecklist

    def evaluar(self) -> sc.EvaluacionChecklist:
        return sc.evaluar(self.catalogo, self.m43c / "control",
                          [self.m43c / "recorte_a", self.m43c / "recorte_b"],
                          self.m43c / "insumos")


def _checklist_del_recorte(pdf: Path, cambios: dict[int, tuple[str, list[tuple[int, str]]]],
                           extra: dict[int, dict[str, Any]] | None = None) -> ChecklistInforme:
    """Lo del control (el 5, «no cumple») salvo `cambios`, sobre las páginas del recorte."""
    return _checklist(pdf, {**{n: c for n, c in CONTROL.items() if n not in (2, 3, 6)},
                            5: ("no_cumple", []), **cambios}, extra)


Cambios = dict[int, tuple[str, list[tuple[int, str]]]]


def _escenario(tmp_path: Path, recortes: list[dict[str, Any]],
               corridas: dict[str, tuple[Cambios, dict[int, dict[str, Any]] | None]]
               ) -> Escenario:
    """Como quedará mediciones/m43c: el control, el catálogo, los insumos de cada recorte
    con su mapa y, para los de `corridas`, su run (lo que cambia respecto del control)."""
    med = tmp_path / "mediciones"
    m43c = med / "m43c"
    carpeta = tmp_path / "informes_reales" / CARPETA
    carpeta.mkdir(parents=True)
    (carpeta / "Tabla de Hallazgos Prueba.xlsx").write_bytes(b"excel")
    pdf = _pdf(tmp_path / "base" / "Informe Prueba.pdf", PAGINAS)
    _guardar_run(m43c / "control", RUN_C, _control(pdf), _sha(pdf))
    catalogo = _catalogo(*(_recorte(pdf_base_sha256=_sha(pdf), **r) for r in recortes))
    (m43c / "catalogo.json").write_text(catalogo.model_dump_json(indent=2), "utf-8")
    for hora, r in enumerate(catalogo.recortes, start=11):
        caso = sc.preparar_insumos(pdf, carpeta, m43c / "insumos" / r.grupo, r)
        if r.id in corridas:
            recorte = caso / f"Informe Prueba - {r.id}.pdf"
            _guardar_run(m43c / r.grupo, f"2026-10-27_{hora}-00-00_claude-opus-5-5",
                         _checklist_del_recorte(recorte, *corridas[r.id]), _sha(recorte))
    return Escenario(med, m43c, catalogo)


@pytest.fixture
def escenario(tmp_path: Path) -> Escenario:
    """Dos recortes del mismo informe (uno por grupo), con un run cada uno.

    PRU-A deja las págs. 1, 4 y 5: el 2 sale «no cumple» (el modelo), el 3 lo baja la
    cita, el 6 sigue «cumple» con la calibración de la 5 (escapa), el afectado 4 cambia
    y el 7, que no se declaró, también. PRU-B: nada cambia (el 6 cita la portada y
    escapa)."""
    return _escenario(tmp_path, [
        {"paginas_quitadas": [2, 3, 6], "afectados": [4],
         "blancos": [{"punto": 2, "paginas_cita": [2]}, {"punto": 3, "paginas_cita": [3]},
                     {"punto": 6, "paginas_cita": [6]}, {"punto": 5, "paginas_cita": [6]}]},
        {"id": "PRU-B", "grupo": "recorte_b", "paginas_quitadas": [6],
         "blancos": [{"punto": 6, "paginas_cita": [6]}]},
    ], {"PRU-A": ({2: ("no_cumple", []), 3: ("no_verificable", [(3, ESTUDIO)]),
                   6: ("cumple", [(3, CALIBRACION)]), 4: ("no_verificable", []),
                   7: ("no_cumple", [])},
                  {3: {"resultado_modelo": ResultadoChecklist.CUMPLE,
                       "causa_ajuste": CausaAjuste.SIN_CITA_VERIFICADA,
                       "motivo_ajuste": "cita no verificada"}}),
        "PRU-B": ({}, None)})


class TestEvaluar:
    def test_las_cuatro_clases_afectados_y_cambios_fuera(self, escenario: Escenario) -> None:
        ev = escenario.evaluar()
        a, b = ev.recortes
        assert (a.id, a.run_recorte, b.id) == ("PRU-A", "2026-10-27_11-00-00_claude-opus-5-5",
                                              "PRU-B")
        assert {x.punto: x.clase for x in a.blancos} == {
            2: "detectado_modelo", 3: "detectado_cita", 6: "escapado", 5: "no_evaluable"}
        escapado = next(x for x in a.blancos if x.punto == 6)
        (cita,) = escapado.citas_recorte
        # La cita del escapado: p. 3 del recorte = p. 5 del informe, verificada.
        assert (cita.pagina, cita.pagina_original, cita.estado, cita.respalda) == (
            3, 5, "verificada", True)
        assert [(c.pagina, c.pagina_original) for c in escapado.citas_control] == [(6, 6)]
        bajado = next(x for x in a.blancos if x.punto == 3)
        assert (bajado.resultado_recorte, bajado.resultado_modelo_recorte) == (
            "no_verificable", "cumple")
        assert [x.model_dump() for x in a.afectados] == [
            {"punto": 4, "control": "cumple", "recorte": "no_verificable", "cambio": True}]
        assert [(x.punto, x.control, x.recorte) for x in a.cambios_fuera_de_los_blancos] == [
            (7, "cumple", "no_cumple")]
        assert a.sha256_codigo == "a" * 16
        no_evaluable = next(x for x in a.blancos if x.punto == 5)
        assert no_evaluable.motivos_no_evaluable == [
            "el control no da «cumple» (no_cumple)",
            "el control no trae una cita verificada que respalde el «cumple»"]
        assert [x.motivos_no_evaluable for x in a.blancos if x.punto != 5] == [[], [], []]
        assert [x.clase for x in b.blancos] == ["escapado"]
        assert b.cambios_fuera_de_los_blancos == [] and b.afectados == []

    def test_no_evaluable_si_el_recorte_le_deja_evidencia(
            self, control: Control, tmp_path: Path) -> None:
        # Un «cumple» con otra cita que lo respalda fuera de las páginas del blanco, o
        # con su cita repetida en una página que queda: el recorte no le quita toda la
        # evidencia, no mide nada.
        with PaginasPdf(control.pdf) as pp:
            dos = _item(6, "cumple", [(6, FOTOS), (1, PORTADA)], pp)
            sola = _item(6, "cumple", [(6, FOTOS)], pp)
            corta = _item(6, "cumple", [(6, FOTOS), (1, "Portada del informe")], pp)
            pruebas = _item(4, "cumple", [(4, PRUEBAS)], pp)   # también en la 5
            no = _item(6, "no_cumple", [], pp)
        mapa = sc.recortar_pdf(control.pdf, [4, 6], tmp_path / "recorte.pdf")
        with PaginasPdf(tmp_path / "recorte.pdf") as pr:
            def clase(blanco: sc.Blanco, control_: ItemChecklist) -> str:
                return sc.clasificar(sc.validar_blanco(blanco, control_, pr, mapa), no)

            seis = sc.Blanco(punto=6, paginas_cita=[6])
            assert clase(seis, dos) == "no_evaluable"
            assert clase(seis, sola) == "detectado_modelo"
            # Una cita de 3 palabras no respalda (cita_respalda): no cuenta como evidencia.
            assert clase(seis, corta) == "detectado_modelo"
            assert clase(sc.Blanco(punto=4, paginas_cita=[4]), pruebas) == "no_evaluable"

    def test_una_cita_que_sigue_en_el_recorte_no_es_evaluable(self, tmp_path: Path) -> None:
        # La cita del 4 (pág. 4) está también en la 5, que queda: aunque el recorte siga
        # «cumple» con ella (ahora en su pág. 4), no es un escape. evaluar lo comprueba
        # con el PDF del recorte aunque no se haya validado el catálogo.
        esc = _escenario(tmp_path, [{"paginas_quitadas": [4],
                                     "blancos": [{"punto": 4, "paginas_cita": [4]}]}],
                         {"PRU-A": ({4: ("cumple", [(4, PRUEBAS)])}, None)})
        (r,) = sc.evaluar(esc.catalogo, esc.m43c / "control", [esc.m43c / "recorte_a"],
                          esc.m43c / "insumos").recortes
        (blanco,) = r.blancos
        assert blanco.clase == "no_evaluable"
        assert blanco.motivos_no_evaluable == [
            "la cita de la p. 4 sigue en el recorte (págs. originales [5])"]
        assert [(c.pagina, c.pagina_original, c.estado) for c in blanco.citas_recorte] == [
            (4, 5, "verificada")]

    def test_csv_agregado_sin_texto_y_json_privado_con_citas(
            self, escenario: Escenario, tmp_path: Path) -> None:
        salida_csv, salida_json = tmp_path / "datos" / "m43c.csv", tmp_path / "evaluacion.json"
        sc.main(["evaluar", "--catalogo", str(escenario.m43c / "catalogo.json"), "--control",
                 str(escenario.m43c / "control"), "--recortes", str(escenario.m43c / "recorte_a"),
                 str(escenario.m43c / "recorte_b"), "--insumos", str(escenario.m43c / "insumos"),
                 "--json", str(salida_json), "--csv", str(salida_csv)])
        with salida_csv.open(encoding="utf-8") as f:
            filas = list(csv.DictReader(f))
        assert list(filas[0]) == list(sc.COLUMNAS_CSV)
        por_clase = {(f["recorte"], f["clase"]): f for f in filas}
        assert {c: por_clase[("PRU-A", c)]["blancos"] for c in sc.CLASES} == {
            "detectado_modelo": "1", "detectado_cita": "1", "escapado": "1", "no_evaluable": "1"}
        total = por_clase[("PRU-A", "total")]
        assert (total["blancos"], total["afectados"], total["afectados_cambiados"],
                total["cambios_fuera"], total["informe"], total["grupo"]) == (
            "4", "1", "1", "1", "Prueba", "recorte_a")
        assert por_clase[("PRU-B", "escapado")]["blancos"] == "1"
        assert por_clase[("PRU-A", "escapado")]["cambios_fuera"] == ""
        texto_csv = salida_csv.read_text("utf-8")
        for privado in PAGINAS + [CALIBRACION]:
            assert privado.split("\n")[0] not in texto_csv
        assert CALIBRACION in salida_json.read_text("utf-8")

    def test_metricas_lote_la_regenera_desde_mediciones(
            self, escenario: Escenario, tmp_path: Path) -> None:
        assert sc.filas_desde_mediciones(tmp_path / "sin_m43c") == []
        filas = sc.filas_desde_mediciones(escenario.mediciones)
        assert filas == sc.filas_csv(escenario.evaluar())
        assert len(filas) == 2 * (len(sc.CLASES) + 1)

    def test_metricas_lote_con_un_grupo_sin_correr(self, escenario: Escenario) -> None:
        # Un grupo sin carpeta todavía no se corrió: quedan las filas de los corridos.
        shutil.rmtree(escenario.m43c / "recorte_b")
        filas = sc.filas_desde_mediciones(escenario.mediciones)
        assert {f["recorte"] for f in filas} == {"PRU-A"}
        assert len(filas) == len(sc.CLASES) + 1
        # Con su carpeta, lo que falte es un error.
        (escenario.m43c / "recorte_b" / "runs").mkdir(parents=True)
        with pytest.raises(sc.CatalogoInvalidoError, match="PRU-B: ningún run"):
            sc.filas_desde_mediciones(escenario.mediciones)
        # Sin ningún grupo corrido, nada que medir todavía.
        shutil.rmtree(escenario.m43c / "recorte_a")
        shutil.rmtree(escenario.m43c / "recorte_b")
        assert sc.filas_desde_mediciones(escenario.mediciones) == []

    @pytest.mark.parametrize(("borrar", "mensaje"), [
        ("insumos", r"PRU-A: se esperaba un mapas/PRU-A\.json"),
        ("control", f"se esperaba el run {RUN_C}"),
    ])
    def test_metricas_lote_sin_insumos_o_sin_control_falla(
            self, escenario: Escenario, borrar: str, mensaje: str) -> None:
        # Con catálogo y grupos corridos, nunca un CSV vacío en silencio.
        shutil.rmtree(escenario.m43c / borrar)
        with pytest.raises(sc.CatalogoInvalidoError, match=mensaje):
            sc.filas_desde_mediciones(escenario.mediciones)

    def test_sin_el_pdf_del_recorte_en_los_insumos(self, escenario: Escenario) -> None:
        (escenario.m43c / "insumos" / "recorte_b" / CARPETA / "Informe Prueba - PRU-B.pdf"
         ).unlink()
        with pytest.raises(sc.CatalogoInvalidoError, match="PRU-B: no está el PDF del recorte"):
            escenario.evaluar()

    def test_un_run_fallido_repetido_vale_el_que_termino(self, escenario: Escenario) -> None:
        sha = (escenario.m43c / "recorte_b" / "runs" / "2026-10-27_12-00-00_claude-opus-5-5"
               / "input_pdf.hash").read_text("utf-8")
        _guardar_run(escenario.m43c / "recorte_b", "2026-10-27_09-00-00_claude-opus-5-5", None,
                     sha)
        assert escenario.evaluar().recortes[1].run_recorte == "2026-10-27_12-00-00_claude-opus-5-5"

    def test_fallas_ruidosas(self, escenario: Escenario) -> None:
        runs_b = escenario.m43c / "recorte_b" / "runs"
        (run_b,) = runs_b.iterdir()
        sha = (run_b / "input_pdf.hash").read_text("utf-8")
        # Dos runs completos del mismo recorte.
        shutil.copytree(run_b, runs_b / "2026-10-27_13-00-00_claude-opus-5-5")
        with pytest.raises(sc.CatalogoInvalidoError, match="más de un run leyó el recorte"):
            escenario.evaluar()
        shutil.rmtree(runs_b)
        runs_b.mkdir()
        with pytest.raises(sc.CatalogoInvalidoError, match="PRU-B: ningún run"):
            escenario.evaluar()
        # Solo un run fallido: el error del run.
        _guardar_run(escenario.m43c / "recorte_b", run_b.name, None, sha)
        with pytest.raises(sc.CatalogoInvalidoError, match="no tiene checklist: Lote vencido"):
            escenario.evaluar()

    @pytest.mark.parametrize(("archivo", "cambio", "distinto"), [
        ("metadata.json", {"modelo_extraccion": "claude-sonnet-5-5"}, "modelo_extraccion"),
        ("metadata.json", {"cita_checklist": False}, "cita_checklist"),
        ("metadata.json", {"version_codigo": {"sha256_codigo": "d" * 16,
                                              "sha256_checklist_puntos.yaml": "b" * 16}},
         "sha256_codigo"),
        ("metadata.json", {"version_codigo": {"sha256_codigo": "a" * 16,
                                              "sha256_checklist_puntos.yaml": "e" * 16}},
         "sha256_checklist_puntos.yaml"),
        # EFFORT_LLM no está en metadata.json: se ve en lo que recibió el modelo.
        ("checklist_raw/verificar_checklist.json", {"parametros_thinking": {
            "output_config": {"effort": "high"},
            "thinking": {"type": "adaptive", "display": "summarized"}}}, "parametros_thinking"),
        ("checklist_raw/verificar_checklist.json", {"system_prompt": "Eres otro revisor"},
         "system_prompt"),
        ("checklist_raw/verificar_checklist.json", {"user_prompt_text": "Verifica 37 puntos"},
         "user_prompt_text"),
        ("checklist_raw/verificar_checklist.json", {"schema_sha256": "f" * 64}, "schema_sha256"),
        ("checklist_raw/verificar_checklist.json", {"modelo": "claude-sonnet-5-5"}, "modelo"),
    ])
    def test_otra_configuracion_no_se_compara(
            self, escenario: Escenario, archivo: str, cambio: dict[str, Any], distinto: str
    ) -> None:
        (run_a,) = (escenario.m43c / "recorte_a" / "runs").iterdir()
        ruta = run_a / archivo
        ruta.write_text(json.dumps({**json.loads(ruta.read_text("utf-8")), **cambio}), "utf-8")
        with pytest.raises(sc.CatalogoInvalidoError,
                           match=rf"PRU-A: .*'{re.escape(distinto)}.*no se comparan"):
            escenario.evaluar()

    def test_lo_informativo_no_impide_comparar(self, escenario: Escenario) -> None:
        (run_a,) = (escenario.m43c / "recorte_a" / "runs").iterdir()
        ruta = run_a / "checklist_raw" / "verificar_checklist.json"
        ruta.write_text(json.dumps({**_raw(), "modelo_servido": "otro", "tokens_total": 9,
                                    "response_raw": {"items": [1]}}), "utf-8")
        assert escenario.evaluar().recortes[0].id == "PRU-A"

    @pytest.mark.parametrize("archivo", ["metadata.json",
                                         "checklist_raw/verificar_checklist.json"])
    def test_sin_la_configuracion_del_run_no_se_compara(
            self, escenario: Escenario, archivo: str) -> None:
        (run_a,) = (escenario.m43c / "recorte_a" / "runs").iterdir()
        (run_a / archivo).unlink()
        with pytest.raises(sc.CatalogoInvalidoError, match=f"no tiene {archivo}"):
            escenario.evaluar()

    def test_una_clave_que_falta_en_el_raw_no_pasa_por_igual(self, escenario: Escenario) -> None:
        # Sin la clave en los dos runs, None == None: la comparación no compararía nada.
        for grupo in ("control", "recorte_a"):
            (run,) = (escenario.m43c / grupo / "runs").iterdir()
            ruta = run / sc.RAW_CHECKLIST
            raw = json.loads(ruta.read_text("utf-8"))
            del raw["parametros_thinking"]
            ruta.write_text(json.dumps(raw), "utf-8")
        with pytest.raises(sc.CatalogoInvalidoError, match=r"no guarda \['parametros_thinking'\]"):
            escenario.evaluar()

    def test_un_control_por_partes_no_se_compara_aunque_coincida_el_pedido(
            self, escenario: Escenario) -> None:
        # El raw de una lectura por partes trae una llamada por tramo: se comparan todas,
        # pero antes falla por las partes, con su motivo.
        (run_c,) = (escenario.m43c / "control" / "runs").iterdir()
        (run_c / sc.RAW_CHECKLIST).write_text(json.dumps(
            {"troceo": {"total_paginas": 6}, "llamadas": [_raw(), _raw()]}), "utf-8")
        with pytest.raises(sc.CatalogoInvalidoError, match=r"\(llamada 2\)"):
            escenario.evaluar()
        ruta = run_c / "checklist.json"
        cl = ChecklistInforme.model_validate_json(ruta.read_text("utf-8"))
        ruta.write_text(cl.model_copy(update={"tramos_leidos": [(1, 3), (4, 6)]})
                        .model_dump_json(), "utf-8")
        with pytest.raises(sc.CatalogoInvalidoError, match="se leyó por partes"):
            escenario.evaluar()

    @pytest.mark.parametrize(("recorte", "cambio"), [
        (1, {"paginas_quitadas": [5, 6]}),
        # Lo declarado de antemano tampoco: agregar un afectado o quitar un blanco
        # después de ver el resultado no pasa en silencio.
        (0, {"afectados": [4, 7]}),
        (0, {"blancos": [{"punto": 2, "paginas_cita": [2]}, {"punto": 3, "paginas_cita": [3]},
                         {"punto": 5, "paginas_cita": [6]}]}),
        (1, {"nota": "editada después"}),
    ])
    def test_el_catalogo_no_cambia_despues_de_preparar(
            self, escenario: Escenario, recorte: int, cambio: dict[str, Any]) -> None:
        datos = json.loads(escenario.catalogo.model_dump_json())
        datos["recortes"][recorte].update(cambio)
        escenario.catalogo = sc.CatalogoChecklist.model_validate(datos)
        with pytest.raises(sc.CatalogoInvalidoError,
                           match=f"{datos['recortes'][recorte]['id']}: el catálogo cambió"):
            escenario.evaluar()

    def test_el_control_debe_haber_leido_el_pdf_base(self, escenario: Escenario) -> None:
        (escenario.m43c / "control" / "runs" / RUN_C / "input_pdf.hash").write_text("e" * 64)
        with pytest.raises(sc.CatalogoInvalidoError, match="leyó otro PDF"):
            escenario.evaluar()


# ---------------------------------------------------------------------- paginación

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml"
 ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1"
 Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
 Target="word/document.xml"/>
</Relationships>"""


def _parrafo(n: int) -> str:
    return f"Párrafo {n}: el relé número {n} tiene ajustes revisados y vigentes según estudio."


def _docx(ruta: Path, parrafos: int = 120) -> Path:
    """Un DOCX mínimo (sin python-docx) de varias páginas al convertirlo."""
    cuerpo = "".join(f"<w:p><w:r><w:t>{_parrafo(n)}</w:t></w:r></w:p>"
                     for n in range(1, parrafos + 1))
    documento = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.'
                 f'openxmlformats.org/wordprocessingml/2006/main"><w:body>{cuerpo}</w:body>'
                 "</w:document>")
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/document.xml", documento)
    return ruta


def _checklist_con_citas(pdf: Path, ruta: Path, citas: dict[int, tuple[int, str]]) -> Path:
    with PaginasPdf(pdf) as pp:
        items = [_item(n, "cumple", [citas[n]], pp) for n in sorted(citas)]
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(ChecklistInforme(items=items, cumplen=len(items), total=TOTAL_PUNTOS)
                    .model_dump_json(), "utf-8")
    return ruta


def _pagina_de(pdf: Path, texto: str) -> int:
    with fitz.open(pdf) as doc:
        return next(i for i, p in enumerate(doc, start=1)
                    if texto in " ".join(p.get_text().split()))


class TestVerificarPaginacion:
    def test_con_la_conversion_real(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Sin LibreOffice (mammoth + xhtml2pdf), como en B3 y B4.
        monkeypatch.setattr(shutil, "which", lambda *_: None)
        docx = _docx(tmp_path / "informe.docx")
        (tmp_path / "ref").mkdir()
        referencia, _ = convertir_docx_a_pdf(docx, tmp_path / "ref" / "input.pdf")
        pagina = _pagina_de(referencia, _parrafo(90))
        assert pagina > 1
        checklist = _checklist_con_citas(referencia, tmp_path / "run" / "checklist.json",
                                         {1: (1, _parrafo(1)), 9: (pagina, _parrafo(90)),
                                          12: (1, _parrafo(90))})   # en otra página
        base = tmp_path / "m43c" / "base" / "informe.pdf"
        resultado = sc.verificar_paginacion(docx, checklist, base)
        assert resultado.ok, resultado
        assert resultado.problemas == []
        assert resultado.paginas[0] == resultado.paginas[1] > 1
        assert resultado.paginas_con_texto_distinto == []
        assert [(c.punto, c.estado, c.coincide) for c in resultado.citas] == [
            (1, "verificada", True), (9, "verificada", True), (12, "en_otra_pagina", True)]
        assert (resultado.libreoffice, resultado.igual_al_pdf_del_run) == (False, None)
        assert _sha(base) == resultado.sha256_pdf
        with pytest.raises(FileExistsError, match="no se pisa"):
            sc.verificar_paginacion(docx, checklist, base)

    @staticmethod
    def _conversion_falsa(monkeypatch: pytest.MonkeyPatch, *conversiones: list[str]) -> None:
        pendientes = iter(conversiones)

        def convertir(docx: Path, destino: Path) -> tuple[Path, dict[str, Any] | None]:
            return _pdf(destino, next(pendientes)), None

        monkeypatch.setattr(sc, "convertir_docx_a_pdf", convertir)

    @staticmethod
    def _checklist_con_una_cita_mal(tmp_path: Path) -> Path:
        """Un checklist cuya segunda cita guardada no es la que da esta paginación."""
        ref = _pdf(tmp_path / "ref.pdf", [PORTADA, UNILINEAL, ESTUDIO])
        checklist = _checklist_con_citas(ref, tmp_path / "run" / "checklist.json",
                                         {1: (1, PORTADA), 2: (2, UNILINEAL)})
        cl = ChecklistInforme.model_validate_json(checklist.read_text("utf-8"))
        mal = cl.items[1].citas[0].model_copy(update={"verificacion": VerificacionCita(
            estado=EstadoCita.VERIFICADA, pagina=3)})
        checklist.write_text(cl.model_copy(update={"items": [
            cl.items[0], cl.items[1].model_copy(update={"citas": [mal]})]}).model_dump_json(),
            "utf-8")
        return checklist

    @staticmethod
    def _docx_falso(tmp_path: Path) -> Path:
        docx = tmp_path / "informe.docx"
        docx.write_bytes(b"no se lee: la conversion es falsa")
        return docx

    def test_conversiones_distintas_y_citas_que_no_coinciden(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._conversion_falsa(monkeypatch, [PORTADA, UNILINEAL, ESTUDIO],
                               [PORTADA, FOTOS, ESTUDIO])
        checklist = self._checklist_con_una_cita_mal(tmp_path)
        (checklist.parent / "input_pdf.hash").write_text("c" * 64, "utf-8")
        salida, base = tmp_path / "paginacion.json", tmp_path / "base" / "informe.pdf"
        with pytest.raises(SystemExit, match="no coinciden") as error:
            sc.main(["verificar-paginacion", "--docx", str(self._docx_falso(tmp_path)),
                     "--checklist", str(checklist), "--salida", str(salida),
                     "--pdf-salida", str(base)])
        assert error.value.code != 0
        resultado = sc.Paginacion.model_validate_json(salida.read_text("utf-8"))
        assert (resultado.ok, resultado.paginas, resultado.paginas_con_texto_distinto) == (
            False, [3, 3], [2])
        assert [c.coincide for c in resultado.citas] == [True, False]
        assert resultado.igual_al_pdf_del_run is False
        assert UNILINEAL not in salida.read_text("utf-8")   # sin el texto de las citas
        # Una conversión no verificada no queda como base del control.
        assert not base.exists() and not base.parent.exists()

    def test_citas_que_no_coinciden_con_la_misma_paginacion(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Las dos conversiones son iguales: lo único que falla es la cita.
        self._conversion_falsa(monkeypatch, *[[PORTADA, UNILINEAL, ESTUDIO]] * 2)
        base = tmp_path / "base" / "informe.pdf"
        resultado = sc.verificar_paginacion(self._docx_falso(tmp_path),
                                            self._checklist_con_una_cita_mal(tmp_path), base)
        assert (resultado.paginas, resultado.paginas_con_texto_distinto) == ([3, 3], [])
        assert [c.coincide for c in resultado.citas] == [True, False]
        assert not resultado.ok
        assert resultado.problemas == ["1 de 2 citas no se verifican como en el run"]
        assert not base.exists()

    def test_sin_citas_no_hay_nada_que_ligue_la_paginacion(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Un checklist sin cita (B0-B2, B3s): nada dice que el run paginó igual.
        self._conversion_falsa(monkeypatch, *[[PORTADA, UNILINEAL, ESTUDIO]] * 2)
        ref = _pdf(tmp_path / "ref.pdf", [PORTADA, UNILINEAL, ESTUDIO])
        checklist = _checklist_con_citas(ref, tmp_path / "run" / "checklist.json", {})
        base = tmp_path / "base" / "informe.pdf"
        resultado = sc.verificar_paginacion(self._docx_falso(tmp_path), checklist, base)
        assert (resultado.citas, resultado.paginas_con_texto_distinto) == ([], [])
        assert not resultado.ok
        assert resultado.problemas == [
            "el checklist no trae citas: nada liga esta paginación con la del run (usar el "
            "checklist de una ronda con la cita encendida, B3 o B4)"]
        assert not base.exists()
