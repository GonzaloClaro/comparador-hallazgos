"""Tests del harness de medición en lote: detección de casos y resumen (sin LLM)."""

import json
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from comparador.config import settings
from comparador.evaluar_lote import _resumen_caso, descubrir_casos
from comparador.schemas import EmpresaAuditora, ReporteInforme, ResumenInforme


def _caso(base: Path, carpeta: str, archivos: list[str]) -> None:
    d = base / carpeta
    d.mkdir(parents=True)
    for a in archivos:
        (d / a).write_bytes(b"x")


def test_filtro_tolera_nfd_y_tildes(tmp_path: Path):
    # macOS guarda "Añañuca" descompuesto (n + tilde combinante): el filtro
    # escrito con o sin tilde debe encontrarlo igual.
    nfd = unicodedata.normalize("NFD", "S-E Añañuca (Auditora Reliable Energy)")
    _caso(tmp_path, nfd, ["Informe.pdf", "Tabla de Hallazgos.xlsx"])
    _caso(tmp_path, "S-E Beta (Auditora Ensaut)", ["Informe.pdf", "Tabla de Hallazgos.xlsx"])
    for filtro in (["Añañuca"], ["ananuca"], ["AÑAÑUCA"]):
        casos, _ = descubrir_casos(tmp_path, filtro)
        assert [c["empresa"] for c in casos] == [EmpresaAuditora.RELIABLE_ENERGY]


def test_pdf_preferido_y_sin_comprimidos(tmp_path: Path):
    _caso(tmp_path, "S-E X (Auditora Ensaut)", [
        "Informe.docx", "Informe.pdf", "Informe - comprimido.pdf", "Informe_adecuado.pdf",
        "Tabla de Hallazgos.xlsx", "CheckList Revisión X.xlsx",
    ])
    (caso,), omitidas = descubrir_casos(tmp_path)
    assert caso["informe"].name == "Informe.pdf" and omitidas == []
    assert caso["gt"].name == "CheckList Revisión X.xlsx"


def test_mas_de_una_planilla_de_revision_falla(tmp_path: Path):
    _caso(tmp_path, "S-E X (Auditora Ensaut)", [
        "Informe.pdf", "Tabla de Hallazgos.xlsx",
        "CheckList Revisión X.xlsx", "CheckList Revisión X (pre-llenada).xlsx",
    ])
    with pytest.raises(ValueError, match="Más de una planilla"):
        descubrir_casos(tmp_path)


def test_los_archivos_de_bloqueo_de_office_no_cuentan(tmp_path: Path):
    # Con la planilla, el Excel o el informe abiertos, Office deja «~$<nombre>»
    # al lado: no es una segunda planilla ni un segundo Excel ni un informe.
    _caso(tmp_path, "S-E X (Auditora Ensaut)", [
        "Informe.pdf", "~$Informe.docx", "Tabla de Hallazgos.xlsx", "~$Tabla de Hallazgos.xlsx",
        "CheckList Revisión X.xlsx", "~$CheckList Revisión X.xlsx",
    ])
    (caso,), omitidas = descubrir_casos(tmp_path)
    assert omitidas == []
    assert (caso["informe"].name, caso["excel"].name, caso["gt"].name) == (
        "Informe.pdf", "Tabla de Hallazgos.xlsx", "CheckList Revisión X.xlsx")


def test_carpetas_omitidas_con_su_motivo_en_vez_de_saltarlas(tmp_path: Path):
    """M39: una carpeta incompleta o ambigua no se salta en silencio (ni toma el
    primer Excel, ni corta el lote por una auditora desconocida): queda omitida
    con su motivo."""
    ok = ["Informe.pdf", "Tabla de Hallazgos.xlsx"]
    _caso(tmp_path, "S-E Bien (Auditora Ensaut)", ok)
    _caso(tmp_path, "S-E Sin Excel (Auditora Ensaut)", ["Informe.pdf", "CheckList Revisión.xlsx"])
    _caso(tmp_path, "S-E Sin Informe (Auditora Ensaut)", ["Tabla de Hallazgos.xlsx"])
    _caso(tmp_path, "S-E Dos Excel (Auditora Ensaut)",
          ["Informe.pdf", "Tabla de Hallazgos A.xlsx", "Tabla de Hallazgos B.xlsx"])
    _caso(tmp_path, "S-E Sin Auditora", ok)

    casos, omitidas = descubrir_casos(tmp_path)

    assert [c["nombre"] for c in casos] == ["S-E Bien (Auditora Ensaut)"]
    motivos = {o.carpeta: o.motivo for o in omitidas}
    assert set(motivos) == {"S-E Sin Excel (Auditora Ensaut)", "S-E Sin Informe (Auditora Ensaut)",
                            "S-E Dos Excel (Auditora Ensaut)", "S-E Sin Auditora"}
    assert "sin Excel" in motivos["S-E Sin Excel (Auditora Ensaut)"]
    assert "sin informe" in motivos["S-E Sin Informe (Auditora Ensaut)"]
    assert "Tabla de Hallazgos A.xlsx, Tabla de Hallazgos B.xlsx" in motivos[
        "S-E Dos Excel (Auditora Ensaut)"]
    assert "empresa auditora" in motivos["S-E Sin Auditora"]


def test_un_filtro_que_apunta_a_una_carpeta_omitida_es_error(tmp_path: Path):
    _caso(tmp_path, "S-E Bien (Auditora Ensaut)", ["Informe.pdf", "Tabla de Hallazgos.xlsx"])
    _caso(tmp_path, "S-E Sin Excel (Auditora Ensaut)", ["Informe.pdf"])
    assert len(descubrir_casos(tmp_path, ["bien"])[0]) == 1
    with pytest.raises(ValueError, match="Sin Excel.*sin Excel"):
        descubrir_casos(tmp_path, ["sin excel"])


def test_resumen_incluye_coincidencias_del_juez_de_redaccion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # La medición entre rondas debe ver cuántos "coinciden" decidió el juez
    # de redacción (schema 0.6.0), no solo el total de coincidencias.
    monkeypatch.setattr(settings, "runs_dir", tmp_path)
    reporte = ReporteInforme(
        empresa_auditora=EmpresaAuditora.RELIABLE_ENERGY, coordinado="c",
        subestacion="s", informe_id="i", fecha_auditoria=None,
        fecha_procesamiento=datetime(2026, 10, 17), modelo_extraccion="m",
        modelo_embeddings="e",
        resumen=ResumenInforme(
            total=5, coinciden=4, difieren=1, faltan_en_excel=0, extra_en_excel=0,
            requieren_revision=0, coinciden_con_redaccion_distinta=3,
        ),
        resultados=[],
    )
    fila = _resumen_caso(
        {"nombre": "S-E X", "gt": None}, {"run_id": "run_x", "reporte": reporte}
    )
    assert fila["comparador"]["coinciden"] == 4
    assert fila["comparador"]["coinciden_con_redaccion_distinta"] == 3


def test_resumen_de_citas_cruza_las_bajadas_con_la_planilla():
    """Lo que la ronda B3 necesita para decidir el interruptor CITA_CHECKLIST:
    cuántos "cumple" bajados eran falsos cumple y cuántos eran aciertos."""
    from comparador.evaluar_checklist import ItemEvaluado
    from comparador.evaluar_lote import resumen_citas
    from comparador.schemas import (
        ChecklistInforme,
        CitaChecklist,
        EstadoCita,
        EstadoHallazgo,
        Evidencia,
        FuenteEvidencia,
        Hallazgo,
        ItemChecklist,
        MatchResult,
        ResultadoChecklist,
        TipoMatch,
        VerificacionCita,
    )

    def v(estado: str) -> VerificacionCita:
        return VerificacionCita(estado=EstadoCita(estado), pagina=1)

    pdf = Hallazgo(pano="C1", rele="R", clasificacion="x", descripcion="d", accion_correctiva="a",
                   evidencia=Evidencia(fuente=FuenteEvidencia.PDF, pagina_pdf=1, texto_crudo="d",
                                       verificacion_descripcion=v("no_encontrada"),
                                       verificacion_accion=v("verificada")))
    bajado = dict(resultado=ResultadoChecklist.NO_VERIFICABLE,
                  resultado_modelo=ResultadoChecklist.CUMPLE, motivo_ajuste="m")
    checklist = ChecklistInforme(items=[
        ItemChecklist(numero=1, enunciado="e", resultado=ResultadoChecklist.CUMPLE,
                      citas=[CitaChecklist(pagina=1, texto="t", verificacion=v("verificada"))]),
        ItemChecklist(numero=2, enunciado="e", **bajado),
        ItemChecklist(numero=3, enunciado="e", **bajado),
    ], cumplen=1, total=38, bajados_sin_cita_verificada=2)
    reporte = ReporteInforme(
        empresa_auditora=EmpresaAuditora.ENSAUT, coordinado="c", subestacion="s",
        informe_id="i", fecha_auditoria=None, fecha_procesamiento=datetime(2026, 10, 18),
        modelo_extraccion="m", modelo_embeddings="e",
        resumen=ResumenInforme(total=1, coinciden=0, difieren=0, faltan_en_excel=1,
                               extra_en_excel=0, requieren_revision=1),
        resultados=[MatchResult(pano="C1", rele="R", estado=EstadoHallazgo.FALTA_EN_EXCEL,
                                tipo_match=TipoMatch.SIN_MATCH, confianza=0.0,
                                justificacion="x", hallazgo_pdf=pdf, hallazgo_excel=None)],
        checklist=checklist,
    )
    gt = [ItemEvaluado(n, "c", veredicto, "no_verificable", "no_verificable", "")
          for n, veredicto in ((1, "SI"), (2, "NO"), (3, "SI"))]

    assert resumen_citas(reporte, gt) == {
        "comparador": {"descripcion": {"no_encontrada": 1}, "accion": {"verificada": 1}},
        "checklist": {
            "bajados_sin_cita_verificada": 2, "puntos_bajados": [2, 3],
            "estados": {"verificada": 1},
            "bajados_que_eran_falso_cumple": 1, "bajados_que_eran_acierto": 1,
        },
    }
    # Checklist sin cita (interruptor apagado o reporte < 0.7.0): solo el comparador.
    sin_cita = reporte.model_copy(update={"checklist": checklist.model_copy(
        update={"bajados_sin_cita_verificada": None})})
    assert set(resumen_citas(sin_cita)) == {"comparador"}


def test_bajadas_con_cita_respaldada_no_cuentan_como_bajadas_sin_cita():
    """PD52: la regla de etapa0 (cita_respalda). Un «cumple» bajado por otro motivo
    (M08: con cita respaldada, apoyado en un solo tramo) no es una bajada por falta
    de cita, ni tampoco una cita verificada demasiado corta deja de serlo."""
    from comparador.evaluar_checklist import ItemEvaluado
    from comparador.evaluar_lote import resumen_citas_checklist
    from comparador.schemas import (
        ChecklistInforme,
        CitaChecklist,
        EstadoCita,
        ItemChecklist,
        ResultadoChecklist,
        VerificacionCita,
    )

    def item(n: int, texto: str | None, estado: str = "verificada") -> ItemChecklist:
        citas = [] if texto is None else [CitaChecklist(
            pagina=1, texto=texto, verificacion=VerificacionCita(estado=EstadoCita(estado),
                                                                 pagina=1))]
        return ItemChecklist(numero=n, enunciado="e", resultado=ResultadoChecklist.NO_VERIFICABLE,
                             resultado_modelo=ResultadoChecklist.CUMPLE, motivo_ajuste="m",
                             citas=citas)

    checklist = ChecklistInforme(items=[
        item(1, "Tabla 9 resultados de las pruebas"),            # respaldada: otro motivo
        item(2, "Capítulo 4"),                                    # corta: sí es sin cita
        item(3, "Tabla 9 resultados de las pruebas", "no_encontrada"),
        item(4, None),
    ], cumplen=0, total=38, bajados_sin_cita_verificada=3)
    gt = [ItemEvaluado(n, "c", "NO", "no_verificable", "no_verificable", "")
          for n in (1, 2, 3, 4)]

    resumen = resumen_citas_checklist(checklist, gt)

    assert resumen is not None
    assert (resumen["bajados_que_eran_falso_cumple"], resumen["bajados_que_eran_acierto"]) == (
        3, 0)
    assert resumen["puntos_bajados"] == [2, 3, 4]


# ------------------------------------------------------------ GT del comparador (M64)

CARPETA_GT = "S-E Equis (Auditora Reliable Energy)"   # el informe de los GT sintéticos


def _caso_con_archivos(base: Path) -> tuple[Path, Path]:
    """Carpeta de un caso con un Excel de hallazgos válido (main() lo normaliza
    antes de gastar) y un informe que nadie lee (main() no corre el lote)."""
    from tests.test_integracion_pipeline import _crear_excel

    d = base / CARPETA_GT
    d.mkdir(parents=True)
    informe = d / "Informe.pdf"
    informe.write_bytes(b"informe equis")
    return informe, _crear_excel(d / "Tabla de Hallazgos.xlsx")


def _sha(ruta: Path) -> str:
    import hashlib

    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _gt_para(sha_informe: str, sha_excel: str, informe: str = CARPETA_GT) -> str:
    """GT sintético (con una cita marcada) atado a esos sha256, serializado."""
    from comparador.gt_comparador import GtInforme, serializar
    from tests.test_evaluar_comparador import gt_de, item_gt

    gt = gt_de([item_gt("i1", "difiere", fila=20, pagina=7, cita="CITA PRIVADA uno",
                        campos=("calificacion",), clase="A", subclase="A4")])
    return serializar(GtInforme.model_validate({
        **gt.model_dump(mode="json"), "informe": informe,
        "sha256_informe_original": sha_informe, "sha256_excel": sha_excel}))


def _main(monkeypatch: pytest.MonkeyPatch, argv: list[str],
          lotes: list[list[dict[str, Any]]], runs_dir: Path | None = None) -> None:
    """main() con correr_lote y la prueba de la clave de OpenAI reemplazados:
    anota los casos y no corre nada. RUNS_DIR es el de la convención
    (<carpeta de la salida>/runs) salvo que el test pase otro."""
    from comparador import evaluar_lote

    salida = Path(argv[argv.index("--salida") + 1])
    monkeypatch.setattr(settings, "runs_dir", runs_dir or salida.parent / "runs")

    async def _lote(modelos: list[str], casos: list[dict[str, Any]], paralelo: int,
                    solo_checklist: bool = False) -> dict[str, list[dict[str, Any]]]:
        lotes.append(casos)
        return {m: [] for m in modelos}

    monkeypatch.setattr(evaluar_lote, "correr_lote", _lote)
    monkeypatch.setattr(evaluar_lote, "probar_clave_openai",
                        lambda calcular: {"ok": True, "modelo_servido": "falso"})
    monkeypatch.setattr(sys, "argv", ["evaluar_lote", "--modelos", "claude-x", *argv])
    evaluar_lote.main()


def test_gt_del_comparador_de_otro_informe_o_excel_sale_antes_de_gastar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Hay GT para la carpeta del informe, pero de otro Excel: medir contra él
    # daría cifras de otro informe. Sale antes de correr nada (antes de gastar).
    informe, _ = _caso_con_archivos(tmp_path / "base")
    gt_dir = tmp_path / "gt"
    gt_dir.mkdir()
    (gt_dir / f"{CARPETA_GT}.json").write_text(_gt_para(_sha(informe), "f" * 64), "utf-8")
    salida = tmp_path / "evaluacion.json"
    lotes: list[list[dict[str, Any]]] = []

    with pytest.raises(SystemExit) as exc:
        _main(monkeypatch, ["--salida", str(salida), "--base", str(tmp_path / "base"),
                            "--gt-comparador", str(gt_dir)], lotes)

    assert isinstance(exc.value.code, str) and "otro informe o Excel" in exc.value.code
    assert CARPETA_GT in exc.value.code
    assert lotes == [] and not salida.exists()


def test_gt_del_comparador_que_calza_va_al_caso_y_sin_gt_se_sigue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from comparador.persistence import version_codigo
    from tests.test_integracion_pipeline import _crear_excel

    informe, excel = _caso_con_archivos(tmp_path / "base")
    otro = tmp_path / "base" / "S-E Ye (Auditora Ensaut)"
    otro.mkdir()
    (otro / "Informe Y.pdf").write_bytes(b"y")
    _crear_excel(otro / "Tabla de Hallazgos Y.xlsx")
    gt_dir = tmp_path / "gt"
    gt_dir.mkdir()
    (gt_dir / f"{CARPETA_GT}.json").write_text(_gt_para(_sha(informe), _sha(excel)), "utf-8")
    salida = tmp_path / "evaluacion.json"
    lotes: list[list[dict[str, Any]]] = []

    _main(monkeypatch, ["--salida", str(salida), "--base", str(tmp_path / "base"),
                        "--gt-comparador", str(gt_dir)], lotes)

    (casos,) = lotes
    por_nombre = {c["nombre"]: c for c in casos}
    aplicable = por_nombre[CARPETA_GT]["gt_comparador"]
    assert aplicable.gt.informe == CARPETA_GT
    assert aplicable.sha256 == _sha(gt_dir / f"{CARPETA_GT}.json")
    assert por_nombre["S-E Ye (Auditora Ensaut)"]["gt_comparador"] is None   # no es error
    datos = json.loads(salida.read_text(encoding="utf-8"))
    assert datos["version_codigo"] == version_codigo()
    assert "config" in datos


@pytest.mark.parametrize("asignacion_global", [True, False])
def test_la_salida_registra_la_asignacion_global_del_proceso(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, asignacion_global: bool
):
    """Encendida por defecto desde el 2026-10-26: una ronda con el interruptor
    de antes (false) tiene que poder distinguirse después."""
    _caso_con_archivos(tmp_path / "base")
    monkeypatch.setattr(settings, "asignacion_global", asignacion_global)
    salida = tmp_path / "evaluacion.json"

    _main(monkeypatch, ["--salida", str(salida), "--base", str(tmp_path / "base")], [])

    config = json.loads(salida.read_text(encoding="utf-8"))["config"]
    assert config["asignacion_global"] is asignacion_global


@pytest.mark.parametrize("problema", ["dos_gt", "carpeta_inexistente"])
def test_gt_del_comparador_ambiguo_o_carpeta_inexistente_sale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problema: str
):
    informe, excel = _caso_con_archivos(tmp_path / "base")
    gt_dir = tmp_path / "gt"
    if problema == "dos_gt":
        gt_dir.mkdir()
        for nombre in ("a.json", "b.json"):
            (gt_dir / nombre).write_text(_gt_para(_sha(informe), _sha(excel)), "utf-8")
    lotes: list[list[dict[str, Any]]] = []

    with pytest.raises(SystemExit) as exc:
        _main(monkeypatch, ["--salida", str(tmp_path / "ev.json"),
                            "--base", str(tmp_path / "base"), "--gt-comparador", str(gt_dir)],
              lotes)

    assert isinstance(exc.value.code, str) and "GT" in exc.value.code
    assert lotes == []


def test_solo_checklist_no_mira_el_gt_del_comparador(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Sin comparador no hay nada que evaluar contra el GT: ni se valida.
    informe, _ = _caso_con_archivos(tmp_path / "base")
    gt_dir = tmp_path / "gt"
    gt_dir.mkdir()
    (gt_dir / f"{CARPETA_GT}.json").write_text(_gt_para(_sha(informe), "f" * 64), "utf-8")
    lotes: list[list[dict[str, Any]]] = []

    _main(monkeypatch, ["--salida", str(tmp_path / "ev.json"), "--base", str(tmp_path / "base"),
                        "--gt-comparador", str(gt_dir), "--solo-checklist"], lotes)

    (casos,) = lotes
    assert casos[0]["gt_comparador"] is None


def test_resumen_con_gt_va_aparte_del_comparador_y_sin_texto(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """metricas_lote compara cada clave de "comparador" con los conteos
    recalculados: la evaluación contra el GT va en su propia clave, con el
    sha256 del GT con que se hizo y sin citas."""
    from comparador.evaluar_comparador import gts_de
    from tests.test_adjudicacion import excel, pdf, resultado
    from tests.test_evaluar_comparador import OPUS, SHA_E, SHA_I
    from tests.test_gt_comparador import reporte

    monkeypatch.setattr(settings, "runs_dir", tmp_path / "runs")
    run = tmp_path / "runs" / "run_x"
    run.mkdir(parents=True)
    (run / "input_informe_original.hash").write_text(SHA_I, "utf-8")
    (run / "input_excel.hash").write_text(SHA_E, "utf-8")
    datos = reporte([resultado("difiere", pdf(7, descripcion="CITA PRIVADA uno"), excel(20),
                               campos=("calificacion",))], OPUS)
    (run / "reporte_final.json").write_text(json.dumps(datos), "utf-8")
    gt_dir = tmp_path / "gt"
    gt_dir.mkdir()
    (gt_dir / "x.json").write_text(_gt_para(SHA_I, SHA_E), "utf-8")
    (aplicable,) = gts_de(gt_dir)

    fila = _resumen_caso({"nombre": CARPETA_GT, "gt": None, "gt_comparador": aplicable},
                         {"run_id": "run_x", "reporte": ReporteInforme.model_validate(datos)})

    assert "comparador_gt" not in fila["comparador"]
    gt = fila["comparador_gt"]
    assert (gt["A"], gt["adjudicados"], gt["sin_adjudicar"]) == (1, 1, 0)
    assert gt["sha256_gt"] == _sha(gt_dir / "x.json")
    assert "CITA PRIVADA" not in json.dumps(fila, ensure_ascii=False, default=str)


def test_si_falla_la_evaluacion_contra_el_gt_del_comparador_la_fila_conserva_lo_demas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Un bug en evaluar_run (lo último que llena la fila) no convierte el run
    pagado en un «error»: la fila conserva el checklist contra la planilla, las
    citas y los tokens, y el error queda en su propia clave (la clave «error»
    del primer nivel hace que metricas_lote salte la fila entera)."""
    from types import SimpleNamespace

    from comparador import evaluar_lote

    def _falla(run_dir: Path, gt: Any) -> Any:
        raise RuntimeError("bug al evaluar")

    monkeypatch.setattr(evaluar_lote, "evaluar_run", _falla)
    monkeypatch.setattr(evaluar_lote, "evaluar", lambda run_id, planilla: SimpleNamespace(
        items=[], aciertos=30, no_verificables=1, falsos_no_cumple=2, falsos_cumple=0,
        sin_gt=[]))
    monkeypatch.setattr(settings, "runs_dir", tmp_path / "runs")
    (tmp_path / "runs" / "run_x").mkdir(parents=True)
    (tmp_path / "runs" / "run_x" / "metadata.json").write_text(
        json.dumps({"tokens_checklist": 9, "duracion_segundos": 1.0}), "utf-8")
    reporte = ReporteInforme(
        empresa_auditora=EmpresaAuditora.RELIABLE_ENERGY, coordinado="c",
        subestacion="s", informe_id="i", fecha_auditoria=None,
        fecha_procesamiento=datetime(2026, 10, 17), modelo_extraccion="m",
        modelo_embeddings="e",
        resumen=ResumenInforme(total=0, coinciden=0, difieren=0, faltan_en_excel=0,
                               extra_en_excel=0, requieren_revision=0),
        resultados=[],
    )

    fila = _resumen_caso(
        {"nombre": CARPETA_GT, "gt": tmp_path / "planilla.xlsx",
         "gt_comparador": SimpleNamespace(gt=None)},
        {"run_id": "run_x", "reporte": reporte})

    assert "error" not in fila
    assert fila["comparador_gt"] == {"error": "RuntimeError: bug al evaluar"}
    assert fila["checklist_gt"]["aciertos"] == 30
    assert fila["tokens"] == {"tokens_checklist": 9} and "comparador" in fila
    assert fila["citas"]["comparador"] == {"descripcion": {}, "accion": {}}


# ------------------------------------------------------------ fichas por informe (M39)


def _fichas(tmp_path: Path, informes: dict[str, Any]) -> Path:
    import yaml

    ruta = tmp_path / "fichas_informes.yaml"
    ruta.write_text(yaml.safe_dump({"version_fichas": "1.0", "informes": informes},
                                   allow_unicode=True), encoding="utf-8")
    return ruta


SIN_PLANILLA = {"fecha_planilla": None, "fecha_fuente": None, "revisor": None,
                "sha256_planilla": None, "sha256_criterios_al_ingresar": None,
                "con_herramienta": None, "uso": "prueba"}


def test_la_ficha_de_cada_caso_se_valida_y_va_al_caso(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    _caso_con_archivos(tmp_path / "base")
    _caso(tmp_path / "base", "S-E Sin Excel (Auditora Ensaut)", ["Informe.pdf"])
    ruta = _fichas(tmp_path, {CARPETA_GT: SIN_PLANILLA})
    lotes: list[list[dict[str, Any]]] = []

    _main(monkeypatch, ["--salida", str(tmp_path / "ev.json"), "--base", str(tmp_path / "base"),
                        "--fichas", str(ruta)], lotes)

    (casos,) = lotes
    assert [c["nombre"] for c in casos] == [CARPETA_GT]
    assert casos[0]["ficha"]["uso"] == "prueba"
    # La carpeta omitida se avisa antes de correr.
    assert "S-E Sin Excel (Auditora Ensaut)" in capsys.readouterr().out


@pytest.mark.parametrize("problema", ["sin_ficha", "planilla_distinta", "archivo_inexistente",
                                      "ficha_invalida"])
def test_fichas_que_no_calzan_salen_antes_de_gastar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problema: str
):
    _caso_con_archivos(tmp_path / "base")
    (tmp_path / "base" / CARPETA_GT / "CheckList Revisión.xlsx").write_bytes(b"planilla")
    ficha = {**SIN_PLANILLA, "sha256_planilla": "0" * 64, "fecha_planilla": "2026-07-01",
             "fecha_fuente": "propiedades_xlsx", "con_herramienta": False}
    informes = {
        "sin_ficha": {"S-E Otra (Auditora Ensaut)": ficha},
        "planilla_distinta": {CARPETA_GT: ficha},
        "archivo_inexistente": {},
        "ficha_invalida": {CARPETA_GT: {**ficha, "revisor": "Nombre Apellido"}},
    }[problema]
    ruta = _fichas(tmp_path, informes)
    if problema == "archivo_inexistente":
        ruta.unlink()
    monkeypatch.setattr("comparador.evaluar_lote.cargar_gt", lambda ruta: None)
    lotes: list[list[dict[str, Any]]] = []

    with pytest.raises(SystemExit) as exc:
        _main(monkeypatch, ["--salida", str(tmp_path / "ev.json"),
                            "--base", str(tmp_path / "base"), "--fichas", str(ruta)], lotes)

    assert isinstance(exc.value.code, str) and "ficha" in exc.value.code.lower()
    assert lotes == [] and not (tmp_path / "ev.json").exists()


def test_la_ficha_se_copia_en_la_fila_tambien_si_el_run_falla(monkeypatch: pytest.MonkeyPatch):
    import asyncio

    from comparador import evaluar_lote

    async def _falla(caso: dict[str, Any], solo_checklist: bool = False) -> dict[str, Any]:
        return {"run_id": "r1", "error": "RuntimeError: x"}

    monkeypatch.setattr(evaluar_lote, "_correr_caso", _falla)
    for campo in ("modelo_extraccion", "runs_a_retener", "runs_incompletos_a_retener"):
        monkeypatch.setattr(settings, campo, getattr(settings, campo))
    caso = {"nombre": "S-E X", "gt": None, "ficha": {"uso": "prueba"}}

    resultados = asyncio.run(evaluar_lote.correr_lote(["claude-x"], [caso], paralelo=1))

    (fila,) = resultados["claude-x"]
    assert fila["ficha"] == {"uso": "prueba"} and "error" in fila


# ------------------------------------------------------------ código congelado (E10)


def test_codigo_congelado_igual_corre_y_queda_en_la_salida(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from comparador.persistence import version_codigo
    from tests.test_persistence import copiar_src

    _caso_con_archivos(tmp_path / "base")
    copia = copiar_src(tmp_path / "mediciones" / "b3" / "src")
    salida = tmp_path / "mediciones" / "b3" / "evaluacion_B3.json"
    lotes: list[list[dict[str, Any]]] = []

    _main(monkeypatch, ["--salida", str(salida), "--base", str(tmp_path / "base"),
                        "--codigo-congelado", str(copia)], lotes)

    assert len(lotes) == 1
    datos = json.loads(salida.read_text(encoding="utf-8"))
    assert datos["codigo_congelado"] == {
        "carpeta": str(copia), "sha256_codigo": version_codigo()["sha256_codigo"],
        "archivos_codigo": version_codigo()["archivos_codigo"]}


def test_codigo_congelado_distinto_sale_antes_de_gastar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from tests.test_persistence import copiar_src

    _caso_con_archivos(tmp_path / "base")
    copia = copiar_src(tmp_path / "src")
    (copia / "comparador" / "etapa4_matching.py").write_text("# otra versión\n", "utf-8")
    salida = tmp_path / "evaluacion.json"
    lotes: list[list[dict[str, Any]]] = []

    with pytest.raises(SystemExit) as exc:
        _main(monkeypatch, ["--salida", str(salida), "--base", str(tmp_path / "base"),
                            "--codigo-congelado", str(copia)], lotes)

    assert isinstance(exc.value.code, str)
    assert "no es el de la copia congelada" in exc.value.code
    assert "comparador/etapa4_matching.py" in exc.value.code
    assert lotes == [] and not salida.exists()


def test_sin_codigo_congelado_la_salida_lo_dice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _caso_con_archivos(tmp_path / "base")
    salida = tmp_path / "evaluacion.json"
    lotes: list[list[dict[str, Any]]] = []

    _main(monkeypatch, ["--salida", str(salida), "--base", str(tmp_path / "base")], lotes)

    assert len(lotes) == 1
    assert json.loads(salida.read_text(encoding="utf-8"))["codigo_congelado"] is None


# ------------------------------------------------------------ preflight sin API (PD38)


def test_preflight_valida_todo_y_sale_sin_llamar_a_nada(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """`--preflight`: lo que main() valida antes de gastar (salida, código congelado,
    casos, planillas, fichas, GT y credenciales presentes), sin la prueba de la
    clave de OpenAI (es una llamada), sin correr el lote ni escribir la salida."""
    from comparador import evaluar_lote
    from tests.test_persistence import copiar_src

    informe, excel = _caso_con_archivos(tmp_path / "base")
    gt_dir = tmp_path / "gt"
    gt_dir.mkdir()
    (gt_dir / f"{CARPETA_GT}.json").write_text(_gt_para(_sha(informe), _sha(excel)), "utf-8")
    monkeypatch.setattr(settings, "openai_api_key", "sk-x")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-x")
    monkeypatch.setattr(settings, "modelo_extraccion_fallback", "")
    llamadas: list[str] = []

    def _no(nombre: str) -> Any:
        def _registrar(*_: Any, **__: Any) -> Any:
            llamadas.append(nombre)
            raise AssertionError(nombre)
        return _registrar

    monkeypatch.setattr(evaluar_lote, "correr_lote", _no("correr_lote"))
    monkeypatch.setattr(evaluar_lote, "probar_clave_openai", _no("probar_clave_openai"))
    salida = tmp_path / "mediciones" / "b3" / "evaluacion_B3.json"
    monkeypatch.setattr(settings, "runs_dir", salida.parent / "runs")
    monkeypatch.setattr(sys, "argv", [
        "evaluar_lote", "--modelos", "claude-opus-5-5", "--salida", str(salida),
        "--base", str(tmp_path / "base"), "--gt-comparador", str(gt_dir),
        "--codigo-congelado", str(copiar_src(tmp_path / "src")), "--preflight"])

    evaluar_lote.main()

    assert llamadas == [] and not salida.exists()
    salida_texto = capsys.readouterr().out
    assert "Preflight OK" in salida_texto and "GT del comparador: 1 de 1" in salida_texto


@pytest.mark.parametrize("falla", [False, True])
def test_preflight_convierte_el_informe_word_sin_gastar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    falla: bool
):
    """Un informe .docx (Gamma en B3) se convierte dentro de cada run: el
    preflight prueba la conversión, que es local y gratis, en un temporal."""
    from comparador import evaluar_lote

    informe, _ = _caso_con_archivos(tmp_path / "base")
    docx = informe.with_suffix(".docx")
    informe.rename(docx)
    monkeypatch.setattr(settings, "openai_api_key", "sk-x")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-x")
    monkeypatch.setattr(settings, "modelo_extraccion_fallback", "")
    monkeypatch.setattr(evaluar_lote, "correr_lote", lambda *a, **k: pytest.fail("corrió"))
    convertidos: list[tuple[Path, Path]] = []

    def _convertir(ruta_docx: Path, ruta_pdf: Path) -> tuple[Path, Any]:
        convertidos.append((ruta_docx, ruta_pdf))
        if falla:
            raise RuntimeError("LibreOffice no abrió el archivo")
        ruta_pdf.write_bytes(b"%PDF-1.4 equis")
        return ruta_pdf, {"imagenes_omitidas": 2}

    monkeypatch.setattr(evaluar_lote, "convertir_docx_a_pdf", _convertir)
    salida = tmp_path / "ev.json"
    monkeypatch.setattr(settings, "runs_dir", tmp_path / "runs")
    monkeypatch.setattr(sys, "argv", [
        "evaluar_lote", "--modelos", "claude-opus-5-5", "--salida", str(salida),
        "--base", str(tmp_path / "base"), "--preflight", "--solo-checklist"])

    if falla:
        with pytest.raises(SystemExit) as exc:
            evaluar_lote.main()
        assert isinstance(exc.value.code, str)
        assert "Informe.docx" in exc.value.code and "LibreOffice no abrió" in exc.value.code
    else:
        evaluar_lote.main()
        texto = capsys.readouterr().out
        assert "Preflight OK" in texto and "imagenes_omitidas" in texto
    assert [d for d, _ in convertidos] == [docx]
    # El PDF de prueba va a un temporal: ni junto al informe ni en runs/.
    assert not convertidos[0][1].exists() and convertidos[0][1].parent != docx.parent
    assert not salida.exists() and not (tmp_path / "runs").exists()


@pytest.mark.parametrize("solo_checklist", [False, True])
def test_preflight_sin_credenciales_sale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, solo_checklist: bool
):
    from comparador import evaluar_lote

    _caso_con_archivos(tmp_path / "base")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "modelo_extraccion_fallback", "")
    monkeypatch.setattr(evaluar_lote, "correr_lote", lambda *a, **k: pytest.fail("corrió"))
    monkeypatch.setattr(settings, "runs_dir", tmp_path / "runs")
    monkeypatch.setattr(sys, "argv", [
        "evaluar_lote", "--modelos", "claude-opus-5-5", "--salida", str(tmp_path / "ev.json"),
        "--base", str(tmp_path / "base"), "--preflight",
        *(["--solo-checklist"] if solo_checklist else [])])

    with pytest.raises(SystemExit) as exc:
        evaluar_lote.main()

    assert isinstance(exc.value.code, str) and "ANTHROPIC_API_KEY" in exc.value.code
    assert ("OPENAI_API_KEY" in exc.value.code) is not solo_checklist


# ------------------------------------------------- RUNS_DIR de la ronda (revisión del Bloque 23)


@pytest.mark.parametrize("preflight", [False, True])
@pytest.mark.parametrize("runs", ["por_defecto", "de_otra_ronda"])
def test_runs_dir_que_no_es_el_de_la_salida_sale_antes_de_gastar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, preflight: bool, runs: str
):
    """metricas_lote y los golden leen los runs de una evaluación en runs/ junto a
    ella: sin RUNS_DIR (runs/ del proyecto, con retención) o con el de otra ronda,
    los runs pagados quedarían donde nadie los mide. Sale antes de gastar, también
    en el preflight."""
    _caso_con_archivos(tmp_path / "base")
    salida = tmp_path / "mediciones" / "b3" / "evaluacion_B3.json"
    runs_dir = {"por_defecto": tmp_path / "runs",
                "de_otra_ronda": tmp_path / "mediciones" / "b3s" / "runs"}[runs]
    lotes: list[list[dict[str, Any]]] = []

    with pytest.raises(SystemExit) as exc:
        _main(monkeypatch, ["--salida", str(salida), "--base", str(tmp_path / "base"),
                            *(["--preflight"] if preflight else [])], lotes, runs_dir=runs_dir)

    assert isinstance(exc.value.code, str) and "RUNS_DIR" in exc.value.code
    assert str(salida.parent / "runs") in exc.value.code
    assert lotes == [] and not salida.exists()


# --------------------------------- preflight con las validaciones locales gratis (Bloque 23)


@pytest.mark.parametrize("preflight", [False, True])
@pytest.mark.parametrize("problema", ["criterios", "catalogo", "excel"])
def test_criterios_catalogo_y_excel_se_validan_antes_de_gastar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, preflight: bool, problema: str
):
    """Lo que el pipeline valida gratis dentro del run (criterios del checklist,
    hints de la auditora, E2) también lo valida main() antes de gastar: si no, la
    falla dejaba escrita la salida con una fila de error y un run, y la misma
    --salida ya no se podía repetir."""
    from comparador import etapa0_checklist

    _, excel = _caso_con_archivos(tmp_path / "base")
    if problema == "criterios":
        ruta = tmp_path / "puntos.yaml"
        ruta.write_text("puntos:\n  - {numero: 1, enunciado: x, donde_buscar: y}\n", "utf-8")
        monkeypatch.setattr(etapa0_checklist, "RUTA_PUNTOS", ruta)
    elif problema == "catalogo":
        ruta = tmp_path / "catalogo.yaml"
        ruta.write_text("Ensaut: {}\n", "utf-8")
        monkeypatch.setattr(settings, "catalogo_empresas_path", ruta)
    else:
        excel.write_bytes(b"no es un xlsx")
    salida = tmp_path / "mediciones" / "b3" / "evaluacion_B3.json"
    lotes: list[list[dict[str, Any]]] = []

    with pytest.raises(SystemExit) as exc:
        _main(monkeypatch, ["--salida", str(salida), "--base", str(tmp_path / "base"),
                            *(["--preflight"] if preflight else [])], lotes)

    esperado = {"criterios": "checklist_puntos.yaml", "catalogo": CARPETA_GT,
                "excel": CARPETA_GT}[problema]
    assert isinstance(exc.value.code, str) and esperado in exc.value.code
    assert lotes == [] and not salida.exists()


def test_solo_checklist_no_normaliza_el_excel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # B3s no lee el Excel (el run solo checklist ni lo copia): no se valida.
    _, excel = _caso_con_archivos(tmp_path / "base")
    excel.write_bytes(b"no es un xlsx")
    lotes: list[list[dict[str, Any]]] = []

    _main(monkeypatch, ["--salida", str(tmp_path / "ev.json"), "--base", str(tmp_path / "base"),
                        "--solo-checklist"], lotes)

    assert len(lotes) == 1
