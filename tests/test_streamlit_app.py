"""Pantalla de resultados de Streamlit con AppTest (sin navegador, sin API).

Reportes sintéticos 0.8.0 (actual; `_reporte_060` arma el contenido de 0.6.0
con el schema actual y `_checklist_por_partes` le agrega la lectura por partes
de M08), 0.6.0 y 0.5.0 (retrocompatibilidad, reabiertos desde el historial).
AppTest no permite seleccionar filas de un dataframe: `st.dataframe` se
envuelve para que cada tabla con selección devuelva la fila 0 seleccionada,
así también se renderiza el detalle del hallazgo.

Los runs van a un runs_dir temporal (monkeypatch de settings.runs_dir) y el
feedback a un feedback_dir temporal (tests/conftest.py).
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import streamlit
from streamlit.testing.v1 import AppTest

from comparador import feedback
from comparador.config import settings
from comparador.etapa5_consolidar import consolidar_reporte
from comparador.schemas import (
    Calificacion,
    CampoDiferente,
    ChecklistInforme,
    Diferencia,
    EmpresaAuditora,
    EquivalenciaRedaccion,
    EstadoHallazgo,
    Evidencia,
    FeedbackRun,
    FuenteEvidencia,
    Hallazgo,
    ItemChecklist,
    MatchResult,
    MetadatosInforme,
    MotivoIncorrecto,
    ReporteInforme,
    ResultadoChecklist,
    TipoMatch,
)

APP = Path(__file__).resolve().parent.parent / "streamlit_app.py"
RUN_ID = "2026-01-01_00-00-00_sintetico"

JUSTIFICACION_JUEZ = "Ambos describen la falta de sincronización horaria del equipo."


def _h(fuente: FuenteEvidencia, pano: str, rele: str, desc: str, accion: str,
       calificacion: Calificacion, transversal: bool = False) -> Hallazgo:
    return Hallazgo(
        pano=pano, rele=rele, clasificacion="Verificación DUF", descripcion=desc,
        accion_correctiva=accion, calificacion=calificacion, es_transversal=transversal,
        evidencia=Evidencia(
            fuente=fuente,
            pagina_pdf=7 if fuente == FuenteEvidencia.PDF else None,
            fila_excel=12 if fuente == FuenteEvidencia.EXCEL else None,
            texto_crudo=desc,
        ),
    )


def _pdf(pano: str, rele: str, desc: str, accion: str = "Acción PDF",
         calificacion: Calificacion = Calificacion.MENOR) -> Hallazgo:
    return _h(FuenteEvidencia.PDF, pano, rele, desc, accion, calificacion)


def _excel(pano: str, rele: str, desc: str, accion: str = "Acción PDF",
           calificacion: Calificacion = Calificacion.MENOR) -> Hallazgo:
    return _h(FuenteEvidencia.EXCEL, pano, rele, desc, accion, calificacion)


def _transversal(pano: str, rele: str, desc: str) -> MatchResult:
    return MatchResult(
        pano=pano, rele=rele, estado=EstadoHallazgo.TRANSVERSAL,
        tipo_match=TipoMatch.SIN_MATCH, confianza=0.0, justificacion="Fila transversal.",
        hallazgo_pdf=None,
        hallazgo_excel=_h(FuenteEvidencia.EXCEL, pano, rele, desc, "Revisar",
                          Calificacion.MENOR, transversal=True),
    )


def _reporte_060() -> ReporteInforme:
    """7 resultados: un difiere con los tres campos, dos coincide (uno con
    redacción distinta), un falta, un extra y dos filas transversales."""
    resultados = [
        MatchResult(
            pano="C1", rele="SEL 751", estado=EstadoHallazgo.DIFIERE,
            tipo_match=TipoMatch.UNICIDAD, confianza=1.0, justificacion="Única clasificación.",
            hallazgo_pdf=_pdf("C1", "SEL 751", "Ajustes 51 distintos al estudio",
                              "Ajustar la 51", Calificacion.RELEVANTE),
            hallazgo_excel=_excel("C1", "SEL 751", "Sin registro de eventos",
                                  "Habilitar registro", Calificacion.MENOR),
            # Orden del backend (invariante 16): la UI debe respetarlo.
            diferencias=[
                Diferencia(campo=CampoDiferente.DESCRIPCION, valor_pdf="Ajustes 51 distintos "
                           "al estudio", valor_excel="Sin registro de eventos",
                           detalle="Similitud semántica 0.31, bajo el umbral"),
                Diferencia(campo=CampoDiferente.ACCION_CORRECTIVA, valor_pdf="Ajustar la 51",
                           valor_excel="Habilitar registro"),
                Diferencia(campo=CampoDiferente.CALIFICACION, valor_pdf="Relevante",
                           valor_excel="Menor"),
            ],
        ),
        MatchResult(
            pano="C2", rele="SEL 751", estado=EstadoHallazgo.COINCIDE,
            tipo_match=TipoMatch.SEMANTICO_ALTO, confianza=0.9, justificacion="Mismo hallazgo.",
            hallazgo_pdf=_pdf("C2", "SEL 751", "Sincronización horaria externa: no cumple"),
            hallazgo_excel=_excel("C2", "SEL 751", "Equipo no posee sincronización vía GPS"),
            equivalencias_redaccion=[EquivalenciaRedaccion(
                campo=CampoDiferente.DESCRIPCION,
                valor_pdf="Sincronización horaria externa: no cumple",
                valor_excel="Equipo no posee sincronización vía GPS",
                similitud=0.8, justificacion=JUSTIFICACION_JUEZ,
            )],
        ),
        MatchResult(
            pano="C2", rele="SEL 751", estado=EstadoHallazgo.COINCIDE,
            tipo_match=TipoMatch.UNICIDAD, confianza=1.0, justificacion="Única clasificación.",
            hallazgo_pdf=_pdf("C2", "SEL 751", "DUF desactualizado"),
            hallazgo_excel=_excel("C2", "SEL 751", "DUF desactualizado"),
        ),
        MatchResult(
            pano="C3", rele="SEL 451", estado=EstadoHallazgo.FALTA_EN_EXCEL,
            tipo_match=TipoMatch.SIN_MATCH, confianza=0.0, justificacion="Sin candidatos.",
            hallazgo_pdf=_pdf("C3", "SEL 451", "Prueba de inyección pendiente"),
            hallazgo_excel=None,
        ),
        MatchResult(
            pano="C3", rele="SEL 451", estado=EstadoHallazgo.EXTRA_EN_EXCEL,
            tipo_match=TipoMatch.SIN_MATCH, confianza=0.0, justificacion="Sin par en el PDF.",
            hallazgo_pdf=None,
            hallazgo_excel=_excel("C3", "SEL 451", "Interruptor 52C3 ausente en el DUF"),
        ),
        # Filas transversales: una de varios paños y otra con el nombre de un
        # paño real (Epsilon fila 37, Eta fila 52): no deben mezclarse
        # con los hallazgos de ese paño.
        _transversal("C1, C2", "Análisis de coordinación", "Falta el estudio de coordinación"),
        _transversal("C1", "-", "Sensibilidad del sistema de protecciones"),
    ]
    checklist = ChecklistInforme(items=[
        ItemChecklist(numero=1, enunciado="Portada", resultado=ResultadoChecklist.CUMPLE,
                      paginas="1"),
        ItemChecklist(numero=2, enunciado="Índice", resultado=ResultadoChecklist.NO_CUMPLE),
        ItemChecklist(numero=3, enunciado="DUF", resultado=ResultadoChecklist.NO_VERIFICABLE),
    ], cumplen=1, total=38)
    metadatos = MetadatosInforme(coordinado="Coordinado de Prueba",
                                 subestacion="Subestación Prueba", informe_id="AUD-001")
    reporte = consolidar_reporte(resultados, metadatos, EmpresaAuditora.RELIABLE_ENERGY,
                                 checklist)
    return reporte.model_copy(update={"fecha_procesamiento": datetime(2026, 1, 1)})


def _json_060(reporte: ReporteInforme) -> dict[str, Any]:
    """El mismo reporte como lo escribía el schema 0.6.0 (sin los campos de 0.7.0)."""
    from tests.golden.datos import sin_campos_070

    data: dict[str, Any] = sin_campos_070(reporte.model_dump(mode="json"))
    data["schema_version"] = "0.6.0"
    for r in data["resultados"]:
        r["schema_version"] = "0.6.0"
        for lado in ("hallazgo_pdf", "hallazgo_excel"):
            if r[lado]:
                r[lado]["schema_version"] = "0.6.0"
    return data


def _json_050(reporte: ReporteInforme) -> dict[str, Any]:
    """El mismo reporte como lo escribía el schema 0.5.0 (sin los campos de 0.6.0)."""
    data = _json_060(reporte)
    data["schema_version"] = "0.5.0"
    del data["resumen"]["coinciden_con_redaccion_distinta"]
    for r in data["resultados"]:
        r["schema_version"] = "0.5.0"
        del r["equivalencias_redaccion"]
        for lado in ("hallazgo_pdf", "hallazgo_excel"):
            if r[lado]:
                r[lado]["schema_version"] = "0.5.0"
    return data


@pytest.fixture
def runs_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    runs = tmp_path / "runs"
    (runs / RUN_ID).mkdir(parents=True)
    monkeypatch.setattr(settings, "runs_dir", runs)
    return runs


@pytest.fixture(autouse=True)
def seleccionar_primera_fila(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    original = streamlit.dataframe

    def _dataframe(*args: Any, **kwargs: Any) -> Any:
        elemento = original(*args, **kwargs)
        return {"selection": {"rows": [0]}} if kwargs.get("on_select") else elemento

    monkeypatch.setattr(streamlit, "dataframe", _dataframe)
    yield


def _abrir(reporte: ReporteInforme) -> AppTest:
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.session_state["reporte"] = reporte
    at.session_state["run_id"] = RUN_ID
    at.session_state["feedback"] = FeedbackRun()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


_RE_TILE = re.compile(
    r'<div class="lbl">(.*?)</div><div class="val">(.*?)</div>(?:<div class="sub">(.*?)</div>)?'
)


def _tiles(at: AppTest) -> dict[str, tuple[str, str]]:
    (html,) = [m.value for m in at.markdown if 'class="tiles"' in m.value]
    return {lbl: (val, sub) for lbl, val, sub in _RE_TILE.findall(html)}


def _expander(at: AppTest, prefijo: str) -> Any:
    (exp,) = [e for e in at.expander if e.label.startswith(prefijo)]
    return exp


def _titulos_panos(at: AppTest) -> list[str]:
    return [e.label for e in at.expander if e.label.startswith("Paño ")]


def _selectbox(at: AppTest, label: str) -> Any:
    (sb,) = [s for s in at.selectbox if s.label == label]
    return sb


TILES_060 = {
    "Total": ("7", ""),
    "Coinciden": ("2", "1 con redacción distinta"),
    "Difieren": ("1", ""),
    "🔴 Falta en Excel": ("1", ""),
    "🟠 Falta en el PDF": ("1", ""),
    "⚪ Transversales": ("2", ""),
    "Checklist": ("1/38", ""),
}


class TestReporte060:
    def test_renderiza_sin_excepciones_con_totales_del_informe(self, runs_dir: Path) -> None:
        at = _abrir(_reporte_060())

        assert _tiles(at) == TILES_060
        cabecera = next(m.value for m in at.markdown if 'class="header-cen"' in m.value)
        assert "Subestación Prueba" in cabecera
        assert "3 paños" in cabecera  # sin la fila transversal
        assert _titulos_panos(at) == [
            "Paño C1 · 1 hallazgos · 0 OK",
            "Paño C2 · 2 hallazgos · 2 OK · 1 con redacción distinta",
            "Paño C3 · 2 hallazgos · 0 OK · 🔴 1 falta en Excel",
        ]
        assert _expander(at, "Checklist de aprobación").label.startswith(
            "Checklist de aprobación · 1/38 cumplen")

    def test_tiles_no_cambian_al_filtrar(self, runs_dir: Path) -> None:
        # Invariante 29: los tiles muestran siempre el total del informe.
        at = _abrir(_reporte_060())
        antes = _tiles(at)

        _selectbox(at, "Estado").select("difiere").run()
        assert not at.exception
        assert _titulos_panos(at) == ["Paño C1 · 1 hallazgos · 0 OK"]  # el filtro aplicó
        assert _tiles(at) == antes == TILES_060

        _selectbox(at, "Estado").select("Todos").run()
        _selectbox(at, "Paño").select("C3").run()
        assert _titulos_panos(at) == ["Paño C3 · 2 hallazgos · 0 OK · 🔴 1 falta en Excel"]
        assert _tiles(at) == TILES_060

    def test_orden_de_diferencias_descripcion_accion_calificacion(self, runs_dir: Path) -> None:
        # Invariante 16, en el detalle y en la columna Comentario.
        at = _abrir(_reporte_060())
        c1 = _expander(at, "Paño C1")

        lineas = [m.value for m in c1.markdown if m.value.startswith("- **")]
        assert [linea.split("**")[1] for linea in lineas] == [
            "Descripción", "Acción correctiva", "Calificación",
        ]
        (tabla,) = c1.dataframe
        assert list(tabla.value["Comentario"]) == [
            "🟡 Difiere: Descripción · Acción correctiva · Calificación: Relevante vs Menor"
        ]

    def test_transversales_en_su_propia_seccion(self, runs_dir: Path) -> None:
        at = _abrir(_reporte_060())

        seccion = _expander(at, "⚪ Filas transversales del Excel")
        assert seccion.label == "⚪ Filas transversales del Excel · 2 · revisión manual"
        (tabla,) = seccion.dataframe
        assert list(tabla.value["Fila"]) == ["-", "Análisis de coordinación"]
        assert list(tabla.value["Paño(s)"]) == ["C1", "C1, C2"]
        # Fuera de los paños y de los filtros.
        for titulo in _titulos_panos(at):
            (tabla_pano,) = _expander(at, titulo).dataframe
            assert not {"-", "Análisis de coordinación"} & set(tabla_pano.value["Relé"])
        assert "transversal" not in _selectbox(at, "Estado").options
        assert "C1, C2" not in _selectbox(at, "Paño").options

    def test_coincide_con_redaccion_distinta_en_tile_titulo_y_detalle(
        self, runs_dir: Path
    ) -> None:
        at = _abrir(_reporte_060())

        assert _tiles(at)["Coinciden"] == ("2", "1 con redacción distinta")
        c2 = _expander(at, "Paño C2")
        assert c2.label.endswith("· 1 con redacción distinta")
        (tabla,) = c2.dataframe
        assert list(tabla.value["Comentario"]) == [
            "✅ Coincide · redacción distinta", "✅ Coincide",
        ]
        detalle = " ".join(m.value for m in c2.markdown)
        assert "Coincide con redacción distinta" in detalle
        assert JUSTIFICACION_JUEZ in detalle
        assert "similitud 0.80" in detalle



def _idx_difiere(reporte: ReporteInforme) -> int:
    return next(i for i, m in enumerate(reporte.resultados)
                if m.estado == EstadoHallazgo.DIFIERE)


def _feedback_guardado() -> dict[str, Any]:
    ruta = settings.feedback_dir / RUN_ID / "feedback.json"
    data: dict[str, Any] = json.loads(ruta.read_text(encoding="utf-8"))
    return data


class TestFeedback:
    """Feedback en settings.feedback_dir (temporal por tests/conftest.py), fuera de runs/."""

    def test_se_guarda_en_la_carpeta_de_feedback_y_no_en_el_run(self, runs_dir: Path) -> None:
        reporte = _reporte_060()
        (runs_dir / RUN_ID / "reporte_final.json").write_text(
            reporte.model_dump_json(), encoding="utf-8")
        at = _abrir(reporte)
        idx = _idx_difiere(reporte)

        at.radio(key=f"fb_{RUN_ID}_{idx}").set_value("✓ correcto").run()

        assert not at.exception
        assert _feedback_guardado()["veredictos_resultados"] == {str(idx): "correcto"}
        assert not (runs_dir / RUN_ID / "feedback.json").exists()
        # Copia del reporte: el feedback sigue legible cuando la retención borre el run.
        assert (settings.feedback_dir / RUN_ID / "reporte_final.json").exists()

    def test_incorrecto_pide_el_motivo_y_lo_guarda(self, runs_dir: Path) -> None:
        reporte = _reporte_060()
        at = _abrir(reporte)
        idx = _idx_difiere(reporte)
        assert not [s for s in at.selectbox if s.key == f"motivo_{RUN_ID}_{idx}"]

        at.radio(key=f"fb_{RUN_ID}_{idx}").set_value("✗ incorrecto").run()
        motivo = at.selectbox(key=f"motivo_{RUN_ID}_{idx}")
        assert motivo.value is None   # sin elegir: nada que guardar todavía
        assert _feedback_guardado()["motivos_resultados"] == {}
        motivo.select(MotivoIncorrecto.MISMA_INFORMACION).run()
        at.text_input(key=f"detalle_{RUN_ID}_{idx}").input("dice lo mismo que la fila 12").run()

        assert not at.exception, [e.value for e in at.exception]
        assert _feedback_guardado()["motivos_resultados"] == {str(idx): {
            "motivo": "misma_informacion_otra_redaccion",
            "detalle": "dice lo mismo que la fila 12"}}

        # Si deja de ser ✗, el motivo se borra (no queda un motivo huérfano).
        at.radio(key=f"fb_{RUN_ID}_{idx}").set_value("✓ correcto").run()
        assert _feedback_guardado()["motivos_resultados"] == {}
        assert not [s for s in at.selectbox if s.key == f"motivo_{RUN_ID}_{idx}"]

    def test_checklist_muestra_la_respuesta_y_el_feedback_anterior(self, runs_dir: Path) -> None:
        at = AppTest.from_file(str(APP), default_timeout=60)
        at.session_state["reporte"] = _reporte_060()
        at.session_state["run_id"] = RUN_ID
        at.session_state["feedback"] = FeedbackRun(
            respuestas_checklist={"1": "SI", "3": "N/A"},
            veredictos_checklist={"2": "incorrecto"})
        at.run()

        assert not at.exception, [e.value for e in at.exception]
        (tabla,) = _expander(at, "Checklist de aprobación").dataframe
        assert list(tabla.value["Tu respuesta"]) == ["SI", "— sin revisar", "N/A"]
        assert list(tabla.value["Feedback anterior"]) == ["—", "✗ incorrecto", "—"]

    def test_sin_feedback_anterior_no_hay_esa_columna(self, runs_dir: Path) -> None:
        at = _abrir(_reporte_060())
        (tabla,) = _expander(at, "Checklist de aprobación").dataframe
        assert "Feedback anterior" not in tabla.value.columns
        assert list(tabla.value["Tu respuesta"]) == ["— sin revisar"] * 3

    def test_feedback_antiguo_dentro_del_run_se_lee_al_reabrir(self, runs_dir: Path) -> None:
        reporte = _reporte_060()
        run = runs_dir / RUN_ID
        (run / "reporte_final.json").write_text(reporte.model_dump_json(), encoding="utf-8")
        idx = _idx_difiere(reporte)
        antiguo = FeedbackRun(veredictos_resultados={str(idx): "incorrecto"},
                              comentarios="Revisado antes de F6g.")
        (run / "feedback.json").write_text(antiguo.model_dump_json(), encoding="utf-8")
        at = AppTest.from_file(str(APP), default_timeout=60)
        at.run()

        _selectbox(at, "Reabrir un run").select(RUN_ID).run()
        (abrir,) = [b for b in at.button if b.label == "Abrir"]
        abrir.click().run()

        assert not at.exception, [e.value for e in at.exception]
        assert at.session_state["feedback"].comentarios == "Revisado antes de F6g."
        assert at.radio(key=f"fb_{RUN_ID}_{idx}").value == "✗ incorrecto"
        # Al cambiarlo se guarda en la carpeta nueva, con lo antiguo incluido;
        # el archivo antiguo no se toca.
        at.radio(key=f"fb_{RUN_ID}_{idx}").set_value("✓ correcto").run()
        assert _feedback_guardado()["comentarios"] == "Revisado antes de F6g."
        assert json.loads((run / "feedback.json").read_text())["veredictos_resultados"] == {
            str(idx): "incorrecto"}


    def test_ediciones_seguidas_de_la_grilla_se_guardan_todas(self, runs_dir: Path) -> None:
        """Como el navegador: acumula las ediciones bajo el ID del data_editor que
        tiene en pantalla y las reinicia si llega otro ID. Si la columna se armara
        con las respuestas recién guardadas, el ID cambiaría tras cada edición y
        la siguiente se perdería (revisión F6g: una de cada dos)."""
        at = _abrir(_reporte_060())
        grilla = _Grilla(at)
        id_inicial = grilla.id

        for fila, valor in [(0, "SI"), (1, "NO"), (2, "N/A"), (0, "NO")]:
            grilla.editar(fila, valor)

        assert _feedback_guardado()["respuestas_checklist"] == {"1": "NO", "2": "NO", "3": "N/A"}
        # El mecanismo: los datos de la grilla no cambian mientras el run está
        # abierto, así que su ID tampoco (AppTest muestra esos datos, sin las
        # ediciones que el navegador pone encima).
        assert grilla.id == id_inicial

    def test_reabrir_el_mismo_run_no_borra_respuestas(self, runs_dir: Path) -> None:
        (runs_dir / RUN_ID / "reporte_final.json").write_text(
            _reporte_060().model_dump_json(), encoding="utf-8")
        at = AppTest.from_file(str(APP), default_timeout=60)
        at.run()
        _reabrir(at)
        _Grilla(at).editar(0, "SI")

        (nuevo,) = [b for b in at.button if b.label == "← Nuevo análisis"]
        nuevo.click().run()
        _reabrir(at)
        _Grilla(at).editar(1, "NO")

        assert _feedback_guardado()["respuestas_checklist"] == {"1": "SI", "2": "NO"}

    def test_la_descarga_md_se_arma_al_clic_desde_lo_guardado(self, runs_dir: Path) -> None:
        at = _abrir(_reporte_060())
        at.text_area(key=f"comentarios_{RUN_ID}").input("Revisado hasta el paño C3.").run()
        assert "Revisado hasta el paño C3." in _md_de_la_descarga(at)

        # Lo que se guarda después de dibujar la página (el texto que se confirma
        # con el mismo clic en la descarga) también entra: se lee al hacer clic.
        def _sumar(fb: FeedbackRun) -> None:
            fb.comentarios += " Falta el C4."

        feedback.actualizar_feedback(RUN_ID, _sumar)
        assert "Revisado hasta el paño C3. Falta el C4." in _md_de_la_descarga(at)

    def test_un_texto_pendiente_se_guarda_aunque_el_rerun_salga_de_la_pantalla(
        self, runs_dir: Path
    ) -> None:
        # El texto se confirma en el mismo rerun que el clic en «Nuevo análisis»:
        # el callback lo guarda antes de que el script deje de dibujar el campo.
        at = _abrir(_reporte_060())
        at.text_area(key=f"comentarios_{RUN_ID}").input("Cierre de la revisión.")
        (nuevo,) = [b for b in at.button if b.label == "← Nuevo análisis"]
        nuevo.click().run()

        assert not at.exception
        assert at.session_state["reporte"] is None
        assert _feedback_guardado()["comentarios"] == "Cierre de la revisión."

    def test_dos_sesiones_sobre_el_mismo_run_no_se_pisan(self, runs_dir: Path) -> None:
        reporte = _reporte_060()
        idx = _idx_difiere(reporte)
        primera, segunda = _abrir(reporte), _abrir(reporte)

        primera.radio(key=f"fb_{RUN_ID}_{idx}").set_value("✗ incorrecto").run()
        primera.selectbox(key=f"motivo_{RUN_ID}_{idx}").select(MotivoIncorrecto.OTRO).run()
        # La segunda pestaña se abrió antes y no vio nada de eso.
        segunda.text_area(key=f"comentarios_{RUN_ID}").input("Nota de la otra pestaña.").run()

        guardado = _feedback_guardado()
        assert guardado["veredictos_resultados"] == {str(idx): "incorrecto"}
        assert guardado["motivos_resultados"][str(idx)]["motivo"] == "otro"
        assert guardado["comentarios"] == "Nota de la otra pestaña."

    def test_comentarios_de_dos_pestanas_quedan_los_dos(self, runs_dir: Path) -> None:
        primera, segunda = _abrir(_reporte_060()), _abrir(_reporte_060())
        clave = f"comentarios_{RUN_ID}"

        segunda.text_area(key=clave).input("B: revisado hasta el paño C3.").run()
        primera.text_area(key=clave).input("A: el punto 12 está mal.").run()

        juntos = "B: revisado hasta el paño C3.\n\nA: el punto 12 está mal."
        assert _feedback_guardado()["comentarios"] == juntos
        # La pestaña que guardó después ve los dos textos y sigue editando sobre ellos.
        assert primera.text_area(key=clave).value == juntos
        primera.text_area(key=clave).input(juntos + " Listo.").run()
        assert _feedback_guardado()["comentarios"] == juntos + " Listo."

    def test_detalle_y_check_en_el_mismo_rerun_no_dejan_un_motivo(self, runs_dir: Path) -> None:
        reporte = _reporte_060()
        idx = _idx_difiere(reporte)
        at = _abrir(reporte)
        at.radio(key=f"fb_{RUN_ID}_{idx}").set_value("✗ incorrecto").run()
        at.selectbox(key=f"motivo_{RUN_ID}_{idx}").select(MotivoIncorrecto.OTRO).run()

        # Los dos cambios llegan juntos (el navegador los junta si el script
        # anterior todavía corría): el detalle no revive el motivo de un ✓.
        at.radio(key=f"fb_{RUN_ID}_{idx}").set_value("✓ correcto")
        at.text_input(key=f"detalle_{RUN_ID}_{idx}").input("algo")
        at.run()

        assert _feedback_guardado()["motivos_resultados"] == {}
        assert at.session_state["feedback"].motivos_resultados == {}

    def test_si_la_retencion_ya_borro_el_run_igual_se_copia_el_reporte(
        self, runs_dir: Path
    ) -> None:
        reporte = _reporte_060()
        at = _abrir(reporte)
        shutil.rmtree(runs_dir / RUN_ID)

        at.text_area(key=f"comentarios_{RUN_ID}").input("Revisado.").run()

        copia = settings.feedback_dir / RUN_ID / "reporte_final.json"
        assert ReporteInforme.model_validate_json(copia.read_text(encoding="utf-8")) == reporte


class _Grilla:
    """La grilla del checklist como la maneja el navegador: acumula ediciones
    bajo el ID que tiene en pantalla y las reinicia si llega otro."""

    def __init__(self, at: AppTest) -> None:
        self.at = at
        self.id = self._tabla().proto.id
        self.ediciones: dict[str, Any] = {}

    def _tabla(self) -> Any:
        (tabla,) = _expander(self.at, "Checklist de aprobación").dataframe
        return tabla

    def editar(self, fila: int, valor: str) -> None:
        from streamlit.proto.WidgetStates_pb2 import WidgetState

        self.ediciones[str(fila)] = {"Tu respuesta": valor}
        estados = self.at._tree.get_widget_states()
        estados.widgets.append(WidgetState(id=self.id, string_value=json.dumps({
            "edited_rows": self.ediciones, "added_rows": [], "deleted_rows": []})))
        self.at._run(estados)
        assert not self.at.exception, [e.value for e in self.at.exception]
        if self._tabla().proto.id != self.id:
            self.id, self.ediciones = self._tabla().proto.id, {}


def _reabrir(at: AppTest) -> None:
    _selectbox(at, "Reabrir un run").select(RUN_ID).run()
    (abrir,) = [b for b in at.button if b.label == "Abrir"]
    abrir.click().run()
    assert not at.exception, [e.value for e in at.exception]


def _md_de_la_descarga(at: AppTest) -> str:
    """Ejecuta la generación diferida del botón «⬇ Feedback (.md)», como al hacer
    clic (las funciones se capturan al registrarse: fixture `descargas_diferidas`)."""
    (boton,) = [b for b in at.get("download_button") if b.proto.label == "⬇ Feedback (.md)"]
    assert boton.proto.deferred_file_id, "el .md debe armarse al hacer clic"
    md: str = _DIFERIDAS[boton.proto.deferred_file_id]()
    return md


_DIFERIDAS: dict[str, Any] = {}


@pytest.fixture(autouse=True)
def descargas_diferidas(monkeypatch: pytest.MonkeyPatch) -> None:
    from streamlit.runtime.media_file_manager import MediaFileManager

    original = MediaFileManager.add_deferred

    def _registrar(self: Any, data_callable: Any, *args: Any, **kwargs: Any) -> str:
        file_id: str = original(self, data_callable, *args, **kwargs)
        _DIFERIDAS[file_id] = data_callable
        return file_id

    monkeypatch.setattr(MediaFileManager, "add_deferred", _registrar)

# Redacción de PD72 (provisoria hasta el feedback del equipo revisor).
MOTIVO_E7 = (
    "Revisar a qué hallazgo corresponde esta fila. El Excel dice que no cumple, pero en la "
    "misma pág. 26 hay otro hallazgo del PDF que dice que cumple (descripción «Comparación "
    "con ECAP adjunto en INFOTÉCNICA: Cumple») y que también podría ser el de esta fila. Si "
    "es ese, el Excel invirtió el veredicto.")


def _reporte_con_dudoso(motivo_e7: str | None = MOTIVO_E7) -> ReporteInforme:
    """Dos pares semantico_alto (0,80) que difieren en la descripción: el de E7 con
    `emparejamiento_dudoso` (asignación global, PD71; schema 0.9.0) y el de E8 sin.
    Con `motivo_e7=None`, como con la asignación apagada: ninguno lo trae."""
    def par(pano: str, motivo: str | None) -> MatchResult:
        return MatchResult(
            pano=pano, rele="SEL 451", estado=EstadoHallazgo.DIFIERE,
            tipo_match=TipoMatch.SEMANTICO_ALTO, confianza=0.8,
            justificacion="El ítem describe el ECAP del equipo.",
            hallazgo_pdf=_pdf(pano, "SEL 451", "El equipo no se encuentra ajustado según ECAP"),
            hallazgo_excel=_excel(pano, "SEL 451", "Comparación con ECAP: No cumple"),
            diferencias=[Diferencia(
                campo=CampoDiferente.DESCRIPCION,
                valor_pdf="El equipo no se encuentra ajustado según ECAP",
                valor_excel="Comparación con ECAP: No cumple",
                detalle="Similitud semántica 0.74, bajo el umbral de coincidencia 0.85")],
            emparejamiento_dudoso=motivo,
        )

    metadatos = MetadatosInforme(coordinado="Coordinado de Prueba",
                                 subestacion="Subestación Prueba", informe_id="AUD-002")
    return consolidar_reporte([par("E7", motivo_e7), par("E8", None)], metadatos,
                              EmpresaAuditora.RELIABLE_ENERGY).model_copy(
        update={"fecha_procesamiento": datetime(2026, 10, 25)})


class TestEmparejamientoDudoso090:
    """PD71 (decisión del usuario 2026-10-25): el par con `emparejamiento_dudoso` se
    muestra como un semantico_bajo («(revisar)», caja amarilla, aviso de emparejamiento
    dudoso con el motivo), aunque su confianza sea alta; el badge sigue siendo el de su
    tipo de match."""

    def test_comentario_caja_y_aviso_con_el_motivo(self, runs_dir: Path) -> None:
        at = _abrir(_reporte_con_dudoso())

        e7 = _expander(at, "Paño E7")
        (tabla,) = e7.dataframe
        assert list(tabla.value["Comentario"]) == ["(revisar) 🟡 Difiere: Descripción"]
        assert list(tabla.value["Match"]) == ["🟪 ~"]
        (caja,) = [m.value for m in e7.markdown if 'class="justif' in m.value]
        assert caja.startswith('<div class="justif warn">')
        avisos = [c.value for c in e7.caption]
        # El aviso es el motivo del backend, sin una frase de la interfaz que dependa de
        # su última oración (invariante 24; PD72: el motivo termina con la consecuencia).
        assert f"⚠ Emparejamiento dudoso (0.80). {MOTIVO_E7}" in avisos
        assert not any("el par es confiable" in a for a in avisos)

    def test_sin_el_campo_el_mismo_par_es_confiable(self, runs_dir: Path) -> None:
        at = _abrir(_reporte_con_dudoso())

        e8 = _expander(at, "Paño E8")
        (tabla,) = e8.dataframe
        assert list(tabla.value["Comentario"]) == ["🟡 Difiere: Descripción"]
        (caja,) = [m.value for m in e8.markdown if 'class="justif' in m.value]
        assert caja.startswith('<div class="justif">')
        avisos = " ".join(c.value for c in e8.caption)
        assert "el par es confiable" in avisos and "Emparejamiento dudoso" not in avisos

    def test_la_guia_explica_el_revisar_de_un_par_de_confianza_alta(
        self, runs_dir: Path
    ) -> None:
        at = _abrir(_reporte_con_dudoso())

        guia = _expander(at, "📖 Guía de lectura")
        (texto,) = [m.value for m in guia.markdown
                    if "🟪 **~** también puede salir **(revisar)**" in m.value]
        # El motivo trae la página del otro hallazgo solo si E3 la dio: la guía no
        # promete una página que puede no estar (revisión de PD72).
        assert "El detalle dice cuál es y, si se conoce, en qué página." in texto
        assert "cuál es y en qué página" not in texto

    def test_sin_pares_dudosos_la_guia_queda_como_antes(self, runs_dir: Path) -> None:
        # Con la asignación apagada ningún par trae el campo: la guía no explica un caso
        # que no puede aparecer (pedido del usuario: con el interruptor apagado, todo
        # idéntico a antes del 0.9.0).
        at = _abrir(_reporte_con_dudoso(motivo_e7=None))

        guia = _expander(at, "📖 Guía de lectura")
        (confianza,) = [m.value for m in guia.markdown if "🟥 **!** — sin match" in m.value]
        assert "también puede salir **(revisar)**" not in confianza
        assert "🟠 *Falta en el PDF*. |\n\nEn resumen:" in confianza


# PD60 (schema 0.10.0): los otros relés de la sección que nombra el hallazgo del PDF.
OTROS = ["INGEPAC EF-ZT", "INGEPAC EF-MD"]
AVISO_CON_FILA = (
    "La viñeta del informe también nombra a: INGEPAC EF-ZT, INGEPAC EF-MD. Se comparó entera "
    "con esta fila del Excel: si el Excel la repartió entre relés, la diferencia puede venir "
    "solo de eso.")
AVISO_SIN_FILA = (
    "La viñeta del informe también nombra a: INGEPAC EF-ZT, INGEPAC EF-MD. No hay fila del "
    "Excel emparejada con ella: si el Excel la repartió entre relés, la falta puede venir "
    "solo de eso.")
# «Coincide» (decisión del usuario 2026-10-26): no hay diferencia que explicar.
AVISO_COINCIDE = (
    "La viñeta del informe también nombra a: INGEPAC EF-ZT, INGEPAC EF-MD. Se comparó entera "
    "con esta fila del Excel y coinciden: revisar que la fila no deje fuera la parte de los "
    "otros relés.")


def _reporte_con_otros_reles(con_marca: bool = True) -> ReporteInforme:
    """BT2: un difiere cuya viñeta nombra a los otros dos relés; CT2: la misma viñeta
    sin par en el Excel; C1: un difiere que no nombra a otro relé ([]); CT1: un coincide
    cuya viñeta nombra a los otros dos. Con
    `con_marca=False`, como un reporte 0.9.0: la evidencia no trae el campo."""
    def marcar(h: Hallazgo, otros: list[str]) -> Hallazgo:
        return h.model_copy(update={"evidencia": h.evidencia.model_copy(
            update={"otros_reles_nombrados": otros if con_marca else None})})

    def par(pano: str, otros: list[str], excel: bool, coincide: bool = False) -> MatchResult:
        rele = "INGEPAC EF-TD"
        if coincide:
            return MatchResult(
                pano=pano, rele=rele, estado=EstadoHallazgo.COINCIDE,
                tipo_match=TipoMatch.UNICIDAD, confianza=1.0, justificacion="Única clasificación.",
                hallazgo_pdf=marcar(_pdf(pano, rele, "El ECAP presenta diferencias"), otros),
                hallazgo_excel=_excel(pano, rele, "El ECAP presenta diferencias"),
            )
        return MatchResult(
            pano=pano, rele=rele,
            estado=EstadoHallazgo.DIFIERE if excel else EstadoHallazgo.FALTA_EN_EXCEL,
            tipo_match=TipoMatch.UNICIDAD if excel else TipoMatch.SIN_MATCH,
            confianza=1.0 if excel else 0.0, justificacion="Única clasificación.",
            hallazgo_pdf=marcar(_pdf(pano, rele, "El ECAP presenta diferencias"), otros),
            hallazgo_excel=_excel(pano, rele, "Diferencias en 50G W1") if excel else None,
            diferencias=[Diferencia(
                campo=CampoDiferente.DESCRIPCION, valor_pdf="El ECAP presenta diferencias",
                valor_excel="Diferencias en 50G W1")] if excel else [],
        )

    metadatos = MetadatosInforme(coordinado="Coordinado de Prueba",
                                 subestacion="Subestación Prueba", informe_id="AUD-003")
    return consolidar_reporte(
        [par("BT2", OTROS, True), par("CT2", OTROS, False), par("C1", [], True),
         par("CT1", OTROS, True, coincide=True)],
        metadatos, EmpresaAuditora.RELIABLE_ENERGY,
    ).model_copy(update={"fecha_procesamiento": datetime(2026, 10, 26)})


class TestOtrosRelesNombrados0100:
    """PD60 (decisión del usuario 2026-10-26): solo aviso. El detalle avisa que la
    viñeta del informe también nombra a otros relés de su sección; el estado, el
    comentario y los tiles no cambian."""

    def test_detalle_avisa_con_la_fila_del_excel(self, runs_dir: Path) -> None:
        at = _abrir(_reporte_con_otros_reles())
        bt2 = _expander(at, "Paño BT2")
        assert AVISO_CON_FILA in [i.value for i in bt2.info]
        (tabla,) = bt2.dataframe
        assert list(tabla.value["Comentario"]) == ["🟡 Difiere: Descripción"]

    def test_detalle_avisa_sin_fila_del_excel(self, runs_dir: Path) -> None:
        at = _abrir(_reporte_con_otros_reles())
        assert AVISO_SIN_FILA in [i.value for i in _expander(at, "Paño CT2").info]

    def test_detalle_avisa_distinto_en_un_coincide(self, runs_dir: Path) -> None:
        at = _abrir(_reporte_con_otros_reles())
        avisos = [i.value for i in _expander(at, "Paño CT1").info]
        assert AVISO_COINCIDE in avisos
        assert AVISO_CON_FILA not in avisos

    def test_sin_otros_reles_no_avisa(self, runs_dir: Path) -> None:
        at = _abrir(_reporte_con_otros_reles())
        assert "también nombra a" not in _textos(_expander(at, "Paño C1"))

    def test_reporte_090_no_avisa_y_lo_demas_queda_igual(self, runs_dir: Path) -> None:
        con = _abrir(_reporte_con_otros_reles())
        sin = _abrir(_reporte_con_otros_reles(con_marca=False))
        for pano in ("Paño BT2", "Paño CT2", "Paño C1", "Paño CT1"):
            assert "también nombra a" not in _textos(_expander(sin, pano))
            (t_con,) = _expander(con, pano).dataframe
            (t_sin,) = _expander(sin, pano).dataframe
            assert t_con.value.equals(t_sin.value)
        assert _tiles(con) == _tiles(sin)
        guia = " ".join(m.value for m in _expander(sin, "📖 Guía de lectura").markdown)
        assert "nombran a otro relé" not in guia

    def test_la_guia_explica_el_aviso(self, runs_dir: Path) -> None:
        at = _abrir(_reporte_con_otros_reles())
        guia = " ".join(m.value for m in _expander(at, "📖 Guía de lectura").markdown)
        assert "nombran a otro relé" in guia
        assert "Otros relés nombrados (PDF)" in guia


class TestReporte050:
    def test_se_reabre_desde_el_historial(self, runs_dir: Path) -> None:
        (runs_dir / RUN_ID / "reporte_final.json").write_text(
            json.dumps(_json_050(_reporte_060()), ensure_ascii=False), encoding="utf-8")
        at = AppTest.from_file(str(APP), default_timeout=60)
        at.run()
        assert not at.exception

        _selectbox(at, "Reabrir un run").select(RUN_ID).run()
        (abrir,) = [b for b in at.button if b.label == "Abrir"]
        abrir.click().run()

        assert not at.exception, [e.value for e in at.exception]
        reporte = at.session_state["reporte"]
        assert reporte.schema_version == "0.5.0"
        assert reporte.resumen.coinciden_con_redaccion_distinta == 0
        # Mismos totales; sin la variante "redacción distinta" (no existía en 0.5.0).
        assert _tiles(at) == {**TILES_060, "Coinciden": ("2", "")}
        assert _titulos_panos(at)[1] == "Paño C2 · 2 hallazgos · 2 OK"
        (tabla,) = _expander(at, "Paño C2").dataframe
        assert list(tabla.value["Comentario"]) == ["✅ Coincide", "✅ Coincide"]
        assert _expander(at, "⚪ Filas transversales del Excel")


def _con_referencias(reporte: ReporteInforme) -> ReporteInforme:
    """El difiere de C1 con su cita verificada en la p. 7 y su fila del Excel
    oculta por un filtro (schema 0.7.0); el resumen lo recalcula el backend."""
    from comparador.schemas import EstadoCita, VerificacionCita

    resultados = []
    for m in reporte.resultados:
        if m.estado == EstadoHallazgo.DIFIERE:
            assert m.hallazgo_pdf and m.hallazgo_excel
            evidencia = m.hallazgo_pdf.evidencia.model_copy(update={
                "verificacion_descripcion": VerificacionCita(
                    estado=EstadoCita.VERIFICADA, pagina=7),
                "verificacion_accion": VerificacionCita(
                    estado=EstadoCita.NO_ENCONTRADA, pagina_citada=7),
            })
            pdf = m.hallazgo_pdf.model_copy(update={"evidencia": evidencia})
            excel = m.hallazgo_excel.model_copy(update={
                "evidencia": m.hallazgo_excel.evidencia.model_copy(update={
                    "hoja_excel": "Tabla de Hallazgos (2)", "fila_oculta": True})})
            m = m.model_copy(update={"hallazgo_pdf": pdf, "hallazgo_excel": excel})
        resultados.append(m)
    metadatos = MetadatosInforme(coordinado=reporte.coordinado, subestacion=reporte.subestacion,
                                 informe_id=reporte.informe_id)
    return consolidar_reporte(resultados, metadatos, reporte.empresa_auditora,
                              reporte.checklist).model_copy(
        update={"fecha_procesamiento": reporte.fecha_procesamiento})


def _guardar_pdf(run_dir: Path, total: int = 7) -> None:
    """input.pdf del run (7 páginas, el hallazgo de C1 en la 7) y su huella."""
    import hashlib

    import fitz

    doc = fitz.open()
    for n in range(1, total + 1):
        pagina = doc.new_page()
        pagina.insert_text((40, 60), f"Página {n} del informe de auditoría", fontsize=9)
        if n == 7:
            pagina.insert_text((40, 80), "Ajustes 51 distintos al estudio", fontsize=9)
    ruta = run_dir / "input.pdf"
    doc.save(ruta)
    (run_dir / "input_pdf.hash").write_text(hashlib.sha256(ruta.read_bytes()).hexdigest())


def _clave_visor(reporte: ReporteInforme) -> str:
    idx = next(i for i, m in enumerate(reporte.resultados) if m.estado == EstadoHallazgo.DIFIERE)
    return f"visor_{RUN_ID}_{idx}"


def _textos(contenedor: Any) -> str:
    return " ".join(e.value for tipo in ("markdown", "caption", "info", "warning")
                    for e in getattr(contenedor, tipo))


class TestReferencias070:
    def test_detalle_muestra_la_cita_la_hoja_y_la_fila_oculta(self, runs_dir: Path) -> None:
        at = _abrir(_con_referencias(_reporte_060()))

        avisos = " ".join(w.value for w in at.warning)
        assert "1 fila del Excel" in avisos and "oculta" in avisos
        c1 = _expander(at, "Paño C1")
        detalle = _textos(c1)
        assert "verificada en la p. 7" in detalle
        assert "no aparece en la p. 7" in detalle            # la acción
        assert "hoja «Tabla de Hallazgos (2)», fila 12" in detalle
        assert "Esta fila está **oculta**" in detalle
        assert "no es una cita literal" in detalle
        (tabla,) = c1.dataframe
        assert list(tabla.value["Evidencia"]) == [
            "PDF p.7 (cita no verificada) · Excel f.12 (oculta)"]

    def test_visor_muestra_la_pagina_citada(self, runs_dir: Path) -> None:
        _guardar_pdf(runs_dir / RUN_ID)
        reporte = _con_referencias(_reporte_060())
        at = _abrir(reporte)

        at.toggle(key=_clave_visor(reporte)).set_value(True).run()

        assert not at.exception, [e.value for e in at.exception]
        (imagen,) = at.get("image")
        assert imagen.captions == ["Página 7 de 7"]

    def test_visor_sin_pdf_avisa(self, runs_dir: Path) -> None:
        reporte = _con_referencias(_reporte_060())
        at = _abrir(reporte)

        at.toggle(key=_clave_visor(reporte)).set_value(True).run()

        assert not at.exception
        assert not at.get("image")
        assert any("no conserva el PDF" in i.value for i in at.info)

    def test_visor_con_pdf_ajeno_no_se_muestra(self, runs_dir: Path) -> None:
        _guardar_pdf(runs_dir / RUN_ID)
        (runs_dir / RUN_ID / "input_pdf.hash").write_text("0" * 64)
        reporte = _con_referencias(_reporte_060())
        at = _abrir(reporte)

        at.toggle(key=_clave_visor(reporte)).set_value(True).run()

        assert not at.get("image")
        assert any("no es el que se analizó" in w.value for w in at.warning)


class TestReporte060Reabierto:
    def test_sin_verificacion_lo_dice(self, runs_dir: Path) -> None:
        (runs_dir / RUN_ID / "reporte_final.json").write_text(
            json.dumps(_json_060(_con_referencias(_reporte_060())), ensure_ascii=False),
            encoding="utf-8")
        at = AppTest.from_file(str(APP), default_timeout=60)
        at.run()
        _selectbox(at, "Reabrir un run").select(RUN_ID).run()
        (abrir,) = [b for b in at.button if b.label == "Abrir"]
        abrir.click().run()

        assert not at.exception, [e.value for e in at.exception]
        assert at.session_state["reporte"].schema_version == "0.6.0"
        detalle = _textos(_expander(at, "Paño C1"))
        assert "anterior a la verificación de citas" in detalle
        assert "Excel** — fila 12" in detalle
        assert not any("oculta" in w.value for w in at.warning)


def _checklist_con_citas(reporte: ReporteInforme) -> ReporteInforme:
    """Punto 1 con cita verificada en la p. 7; punto 3 bajado (cita no encontrada)."""
    from comparador.schemas import CitaChecklist, EstadoCita, VerificacionCita

    assert reporte.checklist is not None
    items = [
        ItemChecklist(numero=1, enunciado="Portada", resultado=ResultadoChecklist.CUMPLE,
                      paginas="7", citas=[CitaChecklist(
                          pagina=7, texto="Ajustes 51 distintos al estudio",
                          verificacion=VerificacionCita(estado=EstadoCita.VERIFICADA, pagina=7))]),
        ItemChecklist(numero=2, enunciado="Índice", resultado=ResultadoChecklist.NO_CUMPLE),
        ItemChecklist(numero=3, enunciado="DUF", resultado=ResultadoChecklist.NO_VERIFICABLE,
                      paginas="12", resultado_modelo=ResultadoChecklist.CUMPLE,
                      motivo_ajuste="El modelo respondió «cumple», pero su cita no se pudo "
                                    "verificar (no aparece en la p. 12)",
                      citas=[CitaChecklist(pagina=12, texto="Diagrama unilineal",
                                           verificacion=VerificacionCita(
                                               estado=EstadoCita.NO_ENCONTRADA,
                                               pagina_citada=12))]),
    ]
    checklist = ChecklistInforme(items=items, cumplen=1, total=38, bajados_sin_cita_verificada=1)
    return reporte.model_copy(update={"checklist": checklist})


class TestChecklistConCita:
    def test_tile_columna_y_resultado_del_modelo(self, runs_dir: Path) -> None:
        at = _abrir(_checklist_con_citas(_reporte_060()))

        assert _tiles(at)["Checklist"] == ("1/38", "1 «cumple» sin cita verificada")
        (tabla,) = _expander(at, "Checklist de aprobación").dataframe
        df = tabla.value
        assert list(df["Resultado"])[2] == "➖ No verificable (el modelo dijo ✅ Cumple)"
        assert "verificada en la p. 7" in list(df["Cita"])[0]
        assert "no aparece en la p. 12" in list(df["Cita"])[2]

    def test_evidencia_de_un_punto_en_el_visor(self, runs_dir: Path) -> None:
        _guardar_pdf(runs_dir / RUN_ID)
        at = _abrir(_checklist_con_citas(_reporte_060()))

        at.selectbox(key=f"evidencia_checklist_{RUN_ID}").select("1. Portada").run()

        assert not at.exception, [e.value for e in at.exception]
        (imagen,) = at.get("image")
        assert imagen.captions == ["Página 7 de 7"]

    def test_punto_bajado_muestra_el_motivo(self, runs_dir: Path) -> None:
        _guardar_pdf(runs_dir / RUN_ID)
        at = _abrir(_checklist_con_citas(_reporte_060()))

        at.selectbox(key=f"evidencia_checklist_{RUN_ID}").select("3. DUF").run()

        assert any("no se pudo verificar" in w.value for w in at.warning)
        # La p. 12 no existe en este PDF de 7 páginas: se avisa, no se rompe.
        assert any("La página 12 no existe" in w.value for w in at.warning)

    def test_sin_cita_no_hay_columna(self, runs_dir: Path) -> None:
        at = _abrir(_reporte_060())
        (tabla,) = _expander(at, "Checklist de aprobación").dataframe
        assert "Cita" not in tabla.value.columns


def _checklist_paginas_5_y_7(reporte: ReporteInforme, numero: int = 1,
                             paginas: str = "5, 7") -> ReporteInforme:
    """`_checklist_con_citas` con la columna Páginas del punto 1 en «5, 7»
    (cita verificada solo en la 7), o la de otro `numero` en `paginas`."""
    r = _checklist_con_citas(reporte)
    assert r.checklist is not None
    items = [i.model_copy(update={"paginas": paginas}) if i.numero == numero else i
             for i in r.checklist.items]
    return r.model_copy(update={"checklist": r.checklist.model_copy(update={"items": items})})


def _descargas(monkeypatch: pytest.MonkeyPatch) -> list[tuple[bytes, str | None]]:
    """Lo que entregaría cada botón de descarga diferida: los bytes y el nombre."""
    from streamlit.runtime.media_file_manager import MediaFileManager

    entregas: list[tuple[bytes, str | None]] = []
    original = MediaFileManager.add_deferred

    def espia(self: MediaFileManager, data_callable: Any, mimetype: str | None,
              coordinates: str, file_name: str | None = None) -> str:
        entregas.append((data_callable(), file_name))
        return original(self, data_callable, mimetype, coordinates, file_name=file_name)

    monkeypatch.setattr(MediaFileManager, "add_deferred", espia)
    return entregas


def _elegir_punto(at: AppTest, punto: str) -> None:
    at.selectbox(key=f"evidencia_checklist_{RUN_ID}").select(punto).run()
    assert not at.exception, [e.value for e in at.exception]


def _recorrer(at: AppTest, numero: int) -> None:
    at.toggle(key=f"recorrer_pagina_checklist_{RUN_ID}_{numero}").set_value(True).run()
    assert not at.exception, [e.value for e in at.exception]


class TestRecorrerPdf:
    """PD58: el texto fijo sobre el alcance de la página citada y recorrer el PDF."""

    def test_texto_fijo_junto_al_visor(self, runs_dir: Path) -> None:
        _guardar_pdf(runs_dir / RUN_ID)
        at = _abrir(_checklist_paginas_5_y_7(_reporte_060()))
        _elegir_punto(at, "1. Portada")

        assert any(c.value == "La página respalda la respuesta del sistema, pero no descarta "
                   "que el informe diga algo distinto en otra parte." for c in at.caption)

    def test_recorrer_parte_en_la_vecina_de_la_pagina_citada(self, runs_dir: Path) -> None:
        # La citada es la 7 (la última): parte en la 6, no repite la imagen de arriba.
        _guardar_pdf(runs_dir / RUN_ID)
        at = _abrir(_checklist_paginas_5_y_7(_reporte_060()))
        _elegir_punto(at, "1. Portada")
        _recorrer(at, 1)

        pagina = at.number_input(key=f"otra_pagina_checklist_{RUN_ID}_1")
        assert pagina.value == 6
        assert [c for i in at.get("image") for c in i.captions] == ["Página 7 de 7",
                                                                    "Página 6 de 7"]
        pagina.set_value(5).run()

        assert not at.exception, [e.value for e in at.exception]
        assert "Página 5 de 7" in [c for i in at.get("image") for c in i.captions]

    @pytest.mark.parametrize(("elegida", "inicio", "despues"), [(4, 5, 2), (2, 3, 4)])
    def test_recorrer_parte_junto_a_la_pagina_elegida(
            self, runs_dir: Path, elegida: int, inicio: int, despues: int) -> None:
        _guardar_pdf(runs_dir / RUN_ID)
        at = _abrir(_checklist_paginas_5_y_7(_reporte_060(), numero=2, paginas="2, 3, 4"))
        _elegir_punto(at, "2. Índice")
        at.selectbox(key=f"pagina_checklist_{RUN_ID}_2").select(elegida).run()
        _recorrer(at, 2)

        assert at.number_input(key=f"otra_pagina_checklist_{RUN_ID}_2").value == inicio
        assert [c for i in at.get("image") for c in i.captions] == [
            f"Página {elegida} de 7", f"Página {inicio} de 7"]
        at.selectbox(key=f"pagina_checklist_{RUN_ID}_2").select(despues).run()
        assert not at.exception, [e.value for e in at.exception]
        assert at.get("image")[0].proto.imgs[0].caption == f"Página {despues} de 7"

    def test_al_recorrer_la_pagina_citada_conserva_el_resaltado(self, runs_dir: Path) -> None:
        _guardar_pdf(runs_dir / RUN_ID)
        at = _abrir(_checklist_paginas_5_y_7(_reporte_060()))
        _elegir_punto(at, "1. Portada")
        _recorrer(at, 1)
        pagina = at.number_input(key=f"otra_pagina_checklist_{RUN_ID}_1")

        pagina.set_value(7).run()         # vuelve a la de la cita
        citada, recorrida = at.get("image")
        assert citada.proto.imgs[0].url == recorrida.proto.imgs[0].url
        pagina.set_value(6).run()
        assert at.get("image")[1].proto.imgs[0].url != citada.proto.imgs[0].url

    def test_otras_paginas_de_la_columna_paginas(self, runs_dir: Path) -> None:
        _guardar_pdf(runs_dir / RUN_ID)
        at = _abrir(_checklist_paginas_5_y_7(_reporte_060()))
        _elegir_punto(at, "1. Portada")
        _recorrer(at, 1)

        assert any(c.value == "Otras páginas que menciona el sistema (sin verificar): 5."
                   for c in at.caption)

    def test_otras_paginas_avisa_si_la_columna_nombra_mas_de_las_que_se_listan(
            self, runs_dir: Path) -> None:
        _guardar_pdf(runs_dir / RUN_ID, total=40)
        at = _abrir(_checklist_paginas_5_y_7(_reporte_060(), paginas="1-40"))
        _elegir_punto(at, "1. Portada")
        _recorrer(at, 1)

        (otras,) = [c.value for c in at.caption if c.value.startswith("Otras páginas")]
        assert otras.endswith(", 30; la columna Páginas nombra más, que no se listan.")
        assert ", 7," not in otras        # la citada no se repite

    def test_punto_sin_paginas_se_puede_recorrer(self, runs_dir: Path) -> None:
        _guardar_pdf(runs_dir / RUN_ID)
        at = _abrir(_checklist_paginas_5_y_7(_reporte_060()))
        _elegir_punto(at, "2. Índice")
        _recorrer(at, 2)

        assert at.number_input(key=f"otra_pagina_checklist_{RUN_ID}_2").value == 1
        assert [c for i in at.get("image") for c in i.captions] == ["Página 1 de 7"]

    def test_descarga_del_pdf_completo(self, runs_dir: Path,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
        _guardar_pdf(runs_dir / RUN_ID)
        entregas = _descargas(monkeypatch)
        at = _abrir(_checklist_paginas_5_y_7(_reporte_060()))
        _elegir_punto(at, "1. Portada")
        _recorrer(at, 1)

        etiquetas = [b.proto.label for b in at.get("download_button")]
        assert "⬇ Descargar el PDF completo" in etiquetas
        assert entregas[-1] == ((runs_dir / RUN_ID / "input.pdf").read_bytes(),
                                f"informe_{RUN_ID}.pdf")

    def test_informe_en_word_descarga_el_pdf_convertido(self, runs_dir: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
        _guardar_pdf(runs_dir / RUN_ID)
        (runs_dir / RUN_ID / "input.docx").write_bytes(b"docx")
        entregas = _descargas(monkeypatch)
        at = _abrir(_checklist_paginas_5_y_7(_reporte_060()))
        _elegir_punto(at, "1. Portada")
        _recorrer(at, 1)

        etiquetas = [b.proto.label for b in at.get("download_button")]
        assert "⬇ Descargar el PDF convertido" in etiquetas
        assert "⬇ Descargar el PDF completo" not in etiquetas
        assert entregas[-1] == ((runs_dir / RUN_ID / "input.pdf").read_bytes(),
                                f"informe_{RUN_ID}_convertido.pdf")

    def test_guia_del_checklist_menciona_el_alcance(self, runs_dir: Path) -> None:
        at = _abrir(_reporte_060())

        guia = " ".join(m.value for m in at.markdown)
        assert "📄 **Ver la evidencia**" in guia
        assert "no descarta" in guia and "Recorrer el PDF completo" in guia
        assert "el convertido, si llegó en Word" in guia

    def test_sin_pdf_no_ofrece_recorrer(self, runs_dir: Path) -> None:
        at = _abrir(_checklist_paginas_5_y_7(_reporte_060()))
        _elegir_punto(at, "1. Portada")

        assert any("no conserva el PDF" in i.value for i in at.info)
        assert not [t for t in at.toggle if t.label == "Recorrer el PDF completo"]
        assert not at.number_input

    def test_detalle_del_comparador_no_trae_recorrer(self, runs_dir: Path) -> None:
        _guardar_pdf(runs_dir / RUN_ID)
        reporte = _con_referencias(_reporte_060())
        at = _abrir(reporte)

        at.toggle(key=_clave_visor(reporte)).set_value(True).run()

        assert not at.exception, [e.value for e in at.exception]
        assert not [t for t in at.toggle if t.label == "Recorrer el PDF completo"]
        assert not any("no descarta" in c.value for c in at.caption)


def test_historial_no_lista_un_run_solo_checklist_como_incompleto(runs_dir: Path) -> None:
    solo = runs_dir / "2026-01-02_00-00-00_solo"
    solo.mkdir()
    (solo / "metadata.json").write_text(json.dumps({"modo": "solo_checklist"}))
    a_medias = runs_dir / "2026-01-03_00-00-00_a_medias"
    a_medias.mkdir()

    at = AppTest.from_file(str(APP), default_timeout=60)
    at.run()

    assert not at.exception
    (incompletos,) = [e for e in at.expander if e.label.startswith("Procesamientos incompletos")]
    assert incompletos.label == "Procesamientos incompletos (2)"   # RUN_ID vacío y el a medias


class TestProcesamientoEnDosFases:
    """El clic en «Iniciar» solo registra el pedido; el rerun siguiente procesa
    con los controles deshabilitados. Si siguieran activos, tocar cualquiera
    cortaría el procesamiento ya pagado (revisión F6g)."""

    @staticmethod
    def _cargar(at: AppTest) -> None:
        at.run()
        informe, excel = at.file_uploader
        informe.set_value(("informe.pdf", b"%PDF-1.4 falso", "application/pdf"))
        excel.set_value(("tabla.xlsx", b"PK falso", "application/vnd.ms-excel"))
        at.run()

    @staticmethod
    def _pipeline(monkeypatch: pytest.MonkeyPatch, falla: BaseException | None) -> list[str]:
        import comparador.convertir
        import comparador.pipeline

        llamadas: list[str] = []

        async def _falso(*, run_dir: Path, **_: Any) -> Any:
            llamadas.append(run_dir.name)
            if falla is not None:
                raise falla
            return _reporte_060(), run_dir

        monkeypatch.setattr(comparador.pipeline, "ejecutar_pipeline", _falso)
        monkeypatch.setattr(comparador.convertir, "adecuar_pdf_para_llm",
                            lambda ruta, modelo=None: (ruta, None))
        return llamadas

    @staticmethod
    def _iniciar(at: AppTest) -> None:
        (iniciar,) = [b for b in at.button if b.label == "Iniciar comparación"]
        iniciar.click().run()

    def test_procesa_con_los_controles_deshabilitados(
        self, runs_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Stop durante el procesamiento: el script se detiene en la fase 2, así
        # que la página queda como estaba mientras procesaba.
        from streamlit.runtime.scriptrunner_utils.exceptions import StopException

        llamadas = self._pipeline(monkeypatch, StopException())
        at = AppTest.from_file(str(APP), default_timeout=60)
        self._cargar(at)

        self._iniciar(at)

        assert len(llamadas) == 1
        assert at.radio[0].disabled
        assert all(u.proto.disabled for u in at.file_uploader)
        assert [b for b in at.button if b.label == "Iniciar comparación"][0].disabled
        error = json.loads((runs_dir / llamadas[0] / "error.json").read_text())
        # Streamlit no distingue el botón Stop de una conexión cortada.
        assert error["tipo"] == "Detenido" and "conexión" in error["mensaje"]
        # «R» (rerun) vuelve a habilitar todo con los archivos y la empresa
        # conservados, y explica qué pasó (tras el Stop no se podía dibujar).
        at.run()
        assert any("Procesamiento detenido" in e.value for e in at.error)
        assert not at.radio[0].disabled
        assert not [b for b in at.button if b.label == "Iniciar comparación"][0].disabled
        assert len(llamadas) == 1

    @staticmethod
    def _pipeline_que_detiene(monkeypatch: pytest.MonkeyPatch,
                              falla: Exception | None) -> list[str]:
        """Un Stop real: el runtime queda detenido (Streamlit 1.59 no deja
        dibujar ni escribir el estado de la sesión) y la etapa sigue: o llega al
        próximo aviso de progreso, o falla por su cuenta."""
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        import comparador.convertir
        import comparador.pipeline

        llamadas: list[str] = []

        async def _falso(*, run_dir: Path, on_progreso: Any, **_: Any) -> Any:
            llamadas.append(run_dir.name)
            contexto = get_script_run_ctx()
            assert contexto is not None
            contexto.script_requests.request_stop()
            if falla is not None:
                raise falla
            on_progreso("descubrir_panos")
            return _reporte_060(), run_dir

        monkeypatch.setattr(comparador.pipeline, "ejecutar_pipeline", _falso)
        monkeypatch.setattr(comparador.convertir, "adecuar_pdf_para_llm",
                            lambda ruta, modelo=None: (ruta, None))
        return llamadas

    def test_tras_un_stop_real_la_pantalla_dice_que_paso(
        self, runs_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        llamadas = self._pipeline_que_detiene(monkeypatch, None)
        at = AppTest.from_file(str(APP), default_timeout=60)
        self._cargar(at)
        self._iniciar(at)

        error = json.loads((runs_dir / llamadas[0] / "error.json").read_text())
        assert error["tipo"] == "Detenido"
        at.run()   # R
        assert any("Procesamiento detenido" in e.value for e in at.error)
        assert not at.radio[0].disabled

    def test_un_stop_y_una_falla_de_la_etapa_dejan_el_error_real(
        self, runs_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        llamadas = self._pipeline_que_detiene(monkeypatch, RuntimeError("la API respondió 529"))
        at = AppTest.from_file(str(APP), default_timeout=60)
        self._cargar(at)
        self._iniciar(at)

        error = json.loads((runs_dir / llamadas[0] / "error.json").read_text())
        assert (error["tipo"], error["mensaje"]) == ("RuntimeError", "la API respondió 529")
        at.run()
        assert any("la API respondió 529" in e.value for e in at.error)

    def test_si_no_se_lee_el_feedback_dice_que_el_run_si_termino(
        self, runs_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        llamadas = self._pipeline(monkeypatch, None)

        def _tomado(run_id: str) -> FeedbackRun:
            raise TimeoutError("Otro proceso tiene tomado el feedback.")

        monkeypatch.setattr(feedback, "cargar_feedback", _tomado)
        at = AppTest.from_file(str(APP), default_timeout=60)
        self._cargar(at)
        self._iniciar(at)

        assert at.session_state["reporte"] is None
        assert any("sí terminó" in e.value and llamadas[0] in e.value for e in at.error)

    def test_si_falla_vuelve_habilitada_con_el_error(
        self, runs_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import comparador.convertir
        import comparador.pipeline

        llamadas: list[str] = []

        async def _falla_la_primera(*, run_dir: Path, **_: Any) -> Any:
            llamadas.append(run_dir.name)
            if len(llamadas) == 1:
                raise RuntimeError("falla simulada del modelo")
            return _reporte_060(), run_dir

        monkeypatch.setattr(comparador.pipeline, "ejecutar_pipeline", _falla_la_primera)
        monkeypatch.setattr(comparador.convertir, "adecuar_pdf_para_llm",
                            lambda ruta, modelo=None: (ruta, None))
        at = AppTest.from_file(str(APP), default_timeout=60)
        self._cargar(at)

        self._iniciar(at)

        # Sin otra interacción: habilitada, con el error y los archivos conservados.
        assert any("falla simulada del modelo" in e.value for e in at.error)
        assert not at.radio[0].disabled
        assert at.session_state["reporte"] is None
        # Reintentar procesa otra vez (sin volver a subir nada) y abre el resultado;
        # al volver a la pantalla de carga, el error viejo ya no está.
        self._iniciar(at)
        assert len(llamadas) == 2 and at.session_state["run_id"] == llamadas[1]
        (nuevo,) = [b for b in at.button if b.label == "← Nuevo análisis"]
        nuevo.click().run()
        assert not any("falla simulada" in e.value for e in at.error)

    def test_abrir_un_run_borra_el_error_anterior(
        self, runs_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (runs_dir / RUN_ID / "reporte_final.json").write_text(
            _reporte_060().model_dump_json(), encoding="utf-8")
        self._pipeline(monkeypatch, RuntimeError("falla simulada del modelo"))
        at = AppTest.from_file(str(APP), default_timeout=60)
        self._cargar(at)
        self._iniciar(at)
        assert any("falla simulada" in e.value for e in at.error)
        # AppTest conserva los elementos del render interrumpido por st.rerun()
        # (el navegador los borra al terminar el run): un run limpio.
        at.run()
        assert any("falla simulada" in e.value for e in at.error)

        _reabrir(at)
        (nuevo,) = [b for b in at.button if b.label == "← Nuevo análisis"]
        nuevo.click().run()

        assert not any("falla simulada" in e.value for e in at.error)

    def test_un_error_json_ilegible_no_impide_procesar(
        self, runs_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cortado = runs_dir / "2026-01-02_00-00-00_cortado"
        cortado.mkdir()
        (cortado / "error.json").write_text('{"tipo": "Err', encoding="utf-8")
        llamadas = self._pipeline(monkeypatch, None)
        at = AppTest.from_file(str(APP), default_timeout=60)
        self._cargar(at)
        assert not at.exception, [e.value for e in at.exception]

        self._iniciar(at)

        assert not at.exception, [e.value for e in at.exception]
        assert len(llamadas) == 1 and at.session_state["run_id"] == llamadas[0]

    def test_al_terminar_abre_el_resultado(
        self, runs_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        llamadas = self._pipeline(monkeypatch, None)
        at = AppTest.from_file(str(APP), default_timeout=60)
        self._cargar(at)

        self._iniciar(at)

        assert not at.exception, [e.value for e in at.exception]
        assert len(llamadas) == 1
        assert at.session_state["run_id"] == llamadas[0]
        from comparador import persistence
        # Terminado: ya no está en curso, la retención lo puede contar.
        assert not any(p.name == llamadas[0] for p in persistence._EN_CURSO)
        assert _tiles(at)["Total"][0] == str(_reporte_060().resumen.total)


def _troceo(run_dir: Path) -> None:
    """troceo.json de un informe de 456 págs leído en dos partes."""
    (run_dir / "troceo.json").write_text(json.dumps({
        "checklist": {"total_paginas": 456, "tramos": [
            {"paginas": [1, 228], "tokens": 593423}, {"paginas": [229, 456], "tokens": 482567}]},
        "descubrir_panos": {"paginas_leidas": [1, 228], "total_paginas": 456},
    }))


def test_aviso_de_informe_troceado_pide_revisar_los_cumple(runs_dir: Path) -> None:
    """M07 en un reporte < 0.8.0 (sin la marca por punto de M08): el aviso dice lo
    que hace la fusión de tramos (un 'cumple' de un solo tramo gana), no que los
    puntos de ausencia quedan 'no verificable', y que es anterior a la marca."""
    _troceo(runs_dir / RUN_ID)
    at = _abrir(_reporte_060())

    avisos = " ".join(i.value for i in at.info)
    assert "anterior a la marca por punto" in avisos
    assert "2 tramos (págs 1-228, 229-456)" in avisos
    assert "un 'cumple' puede venir de un solo tramo" in avisos
    assert "revisa todos los 'cumple'" in avisos
    assert "AUSENCIA" not in avisos
    assert "Lectura por partes" not in avisos


PARTES = [(1, 228), (229, 456)]


def _checklist_por_partes(reporte: ReporteInforme, *, bajar: bool = False,
                          con_cita: bool = False) -> ReporteInforme:
    """M08 (schema 0.8.0), informe leído en dos partes: el 1 lo respaldan las dos;
    el 3 (fuera de la lista de PD44) es «cumple» solo en la primera y queda marcado
    en los dos modos; el 7 (en la lista) es «cumple» solo en la segunda: marcado o,
    con `bajar`, bajado a no verificable. Los textos son los del backend."""
    from comparador.etapa0_checklist import aviso_un_tramo, motivo_un_tramo
    from comparador.schemas import CausaAjuste

    siete: dict[str, Any] = {"resultado": ResultadoChecklist.CUMPLE}
    if bajar:
        siete = {"resultado": ResultadoChecklist.NO_VERIFICABLE,
                 "resultado_modelo": ResultadoChecklist.CUMPLE,
                 "motivo_ajuste": motivo_un_tramo([2], PARTES),
                 "causa_ajuste": CausaAjuste.UN_TRAMO}
    items = [
        ItemChecklist(numero=1, enunciado="Portada", resultado=ResultadoChecklist.CUMPLE,
                      paginas="1, 300", tramos_respaldo=[1, 2]),
        ItemChecklist(numero=2, enunciado="Índice", resultado=ResultadoChecklist.NO_CUMPLE,
                      paginas="3", tramos_respaldo=[1]),
        ItemChecklist(numero=3, enunciado="DUF", paginas="12", tramos_respaldo=[1],
                      aviso_tramos=aviso_un_tramo([1], PARTES),
                      resultado=ResultadoChecklist.CUMPLE),
        ItemChecklist(numero=7, enunciado="Planilla de ajustes", paginas="301",
                      tramos_respaldo=[2], aviso_tramos=aviso_un_tramo([2], PARTES), **siete),
    ]
    checklist = ChecklistInforme(
        items=items, cumplen=2 if bajar else 3, total=38,
        bajados_sin_cita_verificada=0 if con_cita else None, tramos_leidos=PARTES,
        marcados_un_tramo=1 if bajar else 2, bajados_un_tramo=1 if bajar else None)
    return reporte.model_copy(update={"checklist": checklist})


AVISO_3 = ("Visto en 1 de 2 partes del informe (págs. 1-228); las págs. 229-456 no lo "
           "respaldan: revísalas antes de darlo por cumplido.")
AVISO_7 = ("Visto en 1 de 2 partes del informe (págs. 229-456); las págs. 1-228 no lo "
           "respaldan: revísalas antes de darlo por cumplido.")


class TestLecturaPorPartes:
    """M08 en pantalla: la columna, el aviso del punto, el tile y el aviso general."""

    def test_columna_despues_de_paginas_con_el_aviso_del_backend(self, runs_dir: Path) -> None:
        at = _abrir(_checklist_por_partes(_reporte_060()))

        (tabla,) = _expander(at, "Checklist de aprobación").dataframe
        columnas = list(tabla.value.columns)
        assert columnas[columnas.index("Páginas") + 1] == "Lectura por partes"
        assert "Cita" not in columnas                    # no depende de la cita
        assert list(tabla.value["Lectura por partes"]) == ["—", "—", AVISO_3, AVISO_7]

    def test_con_cita_la_columna_va_antes_de_la_cita(self, runs_dir: Path) -> None:
        at = _abrir(_checklist_por_partes(_reporte_060(), con_cita=True))

        (tabla,) = _expander(at, "Checklist de aprobación").dataframe
        columnas = list(tabla.value.columns)
        assert columnas[columnas.index("Páginas"):columnas.index("Páginas") + 3] == [
            "Páginas", "Lectura por partes", "Cita"]

    def test_leido_entero_no_hay_columna(self, runs_dir: Path) -> None:
        at = _abrir(_checklist_con_citas(_reporte_060()))

        (tabla,) = _expander(at, "Checklist de aprobación").dataframe
        assert "Lectura por partes" not in tabla.value.columns

    def test_tile_cuenta_los_vistos_en_parte(self, runs_dir: Path) -> None:
        at = _abrir(_checklist_por_partes(_reporte_060()))

        assert _tiles(at)["Checklist"] == ("3/38", "2 vistos solo en parte del informe")

    def test_tile_en_modo_bajar_y_con_cita(self, runs_dir: Path) -> None:
        reporte = _checklist_por_partes(_reporte_060(), bajar=True)
        assert reporte.checklist is not None
        reporte.checklist.bajados_sin_cita_verificada = 2
        at = _abrir(reporte)

        assert _tiles(at)["Checklist"] == (
            "2/38", "2 «cumple» sin cita verificada · 1 visto solo en parte del informe · "
                    "1 bajado por lectura en partes")

    def test_evidencia_de_un_punto_muestra_el_aviso(self, runs_dir: Path) -> None:
        at = _abrir(_checklist_por_partes(_reporte_060()))

        at.selectbox(key=f"evidencia_checklist_{RUN_ID}").select("3. DUF").run()

        assert not at.exception, [e.value for e in at.exception]
        assert [w.value for w in at.warning if w.value.startswith("Visto en")] == [AVISO_3]

    def test_evidencia_de_un_punto_bajado_muestra_motivo_y_aviso(self, runs_dir: Path) -> None:
        at = _abrir(_checklist_por_partes(_reporte_060(), bajar=True))

        at.selectbox(key=f"evidencia_checklist_{RUN_ID}").select(
            "7. Planilla de ajustes").run()

        avisos = [w.value for w in at.warning]
        assert ("El informe se leyó en partes por su longitud; este punto exige revisar todo "
                "el informe: revisa las páginas 1-228.") in avisos
        assert AVISO_7 in avisos

    def test_aviso_general_al_dia_en_modo_marcar(self, runs_dir: Path) -> None:
        _troceo(runs_dir / RUN_ID)
        at = _abrir(_checklist_por_partes(_reporte_060()))

        avisos = " ".join(i.value for i in at.info)
        assert "2 partes (págs 1-228, 229-456)" in avisos
        assert "vistos en una sola parte llevan el aviso en la columna «Lectura por partes»" \
            in avisos
        assert "Los demás «cumple» también se revisan, como siempre" in avisos
        assert "tramo" not in avisos
        assert "anterior a la marca por punto" not in avisos
        assert "pasaron a «no verificable»" not in avisos

    def test_aviso_general_en_modo_bajar_dice_lo_que_bajo(self, runs_dir: Path) -> None:
        _troceo(runs_dir / RUN_ID)
        at = _abrir(_checklist_por_partes(_reporte_060(), bajar=True))

        avisos = " ".join(i.value for i in at.info)
        assert "columna «Lectura por partes»" in avisos
        assert "Los demás «cumple» también se revisan, como siempre" in avisos
        assert "exigen revisar todo el informe" in avisos
        assert "pasaron a «no verificable»" in avisos

    def test_aviso_general_en_modo_bajar_sin_bajados_no_dice_que_bajaron(
        self, runs_dir: Path
    ) -> None:
        """Revisión del Bloque 24: la frase depende de lo que pasó (bajados_un_tramo),
        no del modo: con 0 bajados no anuncia una bajada que no ocurrió."""
        _troceo(runs_dir / RUN_ID)
        reporte = _checklist_por_partes(_reporte_060())   # el 7 sigue en «cumple»
        assert reporte.checklist is not None
        reporte.checklist.bajados_un_tramo = 0             # modo bajar, nada bajó
        at = _abrir(reporte)

        avisos = " ".join(i.value for i in at.info)
        assert "columna «Lectura por partes»" in avisos
        assert "pasaron a «no verificable»" not in avisos

    def test_aviso_general_con_tres_partes_no_dice_una_sola(self, runs_dir: Path) -> None:
        """Con N partes el aviso cae en todo «cumple» que no ven todas (regla k < N)."""
        (runs_dir / RUN_ID / "troceo.json").write_text(json.dumps({"checklist": {
            "total_paginas": 456, "tramos": [
                {"paginas": [1, 150]}, {"paginas": [151, 300]}, {"paginas": [301, 456]}]}}))
        reporte = _checklist_por_partes(_reporte_060())
        assert reporte.checklist is not None
        reporte.checklist.tramos_leidos = [(1, 150), (151, 300), (301, 456)]
        at = _abrir(reporte)

        avisos = " ".join(i.value for i in at.info)
        assert "3 partes (págs 1-150, 151-300, 301-456)" in avisos
        assert "Los «cumple» que no se vieron en todas las partes llevan el aviso" in avisos
        assert "una sola parte" not in avisos

    def test_guia_del_checklist_explica_los_informes_largos(self, runs_dir: Path) -> None:
        at = _abrir(_reporte_060())

        guia = " ".join(m.value for m in at.markdown)
        assert "**Informes largos**" in guia
        assert "**Lectura por partes**" in guia


class TestDescripcionIdentica0110:
    """M30 (schema 0.11.0): un par de descripción idéntica, emparejado sin juez, se
    muestra con su badge y su interpretación (sin la entrada, abrir el detalle daba
    KeyError)."""

    def test_cada_tipo_de_match_tiene_badge_interpretacion_y_guia(self, runs_dir: Path) -> None:
        at = _abrir(_reporte_descripcion_identica())
        assert not at.exception
        (tabla,) = _expander(at, "Paño C9").dataframe
        assert list(tabla.value["Match"]) == ["🟩 ="]
        textos = _textos(_expander(at, "Paño C9"))
        assert "la misma descripción en el PDF y el Excel" in textos
        guia = " ".join(m.value for m in _expander(at, "📖 Guía de lectura").markdown)
        for tipo in TipoMatch:
            assert tipo.value in _BADGES, tipo
        assert "🟩 **=** — descripción idéntica" in guia


_BADGES = re.search(r"BADGE_MATCH = \{(.*?)\}", APP.read_text(encoding="utf-8"), re.S).group(1)


def _reporte_descripcion_identica() -> ReporteInforme:
    rele = "SEL 451"
    par = MatchResult(
        pano="C9", rele=rele, estado=EstadoHallazgo.DIFIERE,
        tipo_match=TipoMatch.DESCRIPCION_IDENTICA, confianza=1.0,
        justificacion="Descripción idéntica en el PDF y el Excel en paño C9 / relé SEL 451.",
        hallazgo_pdf=_pdf("C9", rele, "Comparación con ECAP: No cumple",
                          calificacion=Calificacion.RELEVANTE),
        hallazgo_excel=_excel("C9", rele, "Comparación con ECAP: No cumple"),
        diferencias=[Diferencia(campo=CampoDiferente.CALIFICACION, valor_pdf="Relevante",
                                valor_excel="Menor")],
    )
    metadatos = MetadatosInforme(coordinado="Coordinado de Prueba",
                                 subestacion="Subestación Prueba", informe_id="AUD-030")
    return consolidar_reporte([par], metadatos, EmpresaAuditora.RELIABLE_ENERGY).model_copy(
        update={"fecha_procesamiento": datetime(2026, 10, 26)})
