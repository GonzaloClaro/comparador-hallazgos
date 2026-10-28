"""Feedback del equipo revisor fuera de runs/ (comparador.feedback, F6g 2026-10-18).

El feedback_dir de cada test es temporal (tests/conftest.py); acá runs_dir
también lo es, en otra carpeta.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from comparador import feedback
from comparador.config import Settings, settings
from comparador.persistence import limpiar_runs_antiguos
from comparador.schemas import FeedbackRun, MotivoFeedback, MotivoIncorrecto, ReporteInforme

RUN_ID = "2026-01-01_00-00-00_claude-opus-5-5"


@pytest.fixture
def runs_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    runs = tmp_path / "runs"
    (runs / RUN_ID).mkdir(parents=True)
    monkeypatch.setattr(settings, "runs_dir", runs)
    return runs


class TestRunId:
    @pytest.mark.parametrize("run_id", ["", ".", "..", "../x", "a/b", "a\\b", "C:x", "a\x00b"])
    def test_rechaza_lo_que_no_es_un_nombre_de_run(self, run_id: str, runs_dir: Path) -> None:
        with pytest.raises(feedback.RunIdInvalidoError):
            feedback.validar_run_id(run_id)
        with pytest.raises(feedback.RunIdInvalidoError):
            feedback.carpeta_feedback(run_id)

    def test_acepta_un_run_normal(self, runs_dir: Path) -> None:
        assert feedback.carpeta_feedback(RUN_ID) == (settings.feedback_dir / RUN_ID).resolve()


class TestFueraDeRuns:
    def test_la_configuracion_rechaza_feedback_dentro_de_runs(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="FEEDBACK_DIR"):
            Settings(runs_dir=tmp_path / "runs", feedback_dir=tmp_path / "runs" / "feedback")

    def test_guarda_aunque_se_cambie_en_caliente(
        self, runs_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Un monkeypatch (o un cambio en caliente) se salta el validador: la
        # carpeta se vuelve a comprobar al usarla.
        monkeypatch.setattr(settings, "feedback_dir", runs_dir / "feedback")
        with pytest.raises(RuntimeError, match="dentro de runs"):
            feedback.guardar_feedback(RUN_ID, FeedbackRun())
        assert not (runs_dir / "feedback").exists()


class TestGuardarYCargar:
    def test_sin_feedback_devuelve_uno_vacio(self, runs_dir: Path) -> None:
        assert feedback.cargar_feedback(RUN_ID) == FeedbackRun()

    def test_ida_y_vuelta_con_respuestas_y_motivos(self, runs_dir: Path) -> None:
        fb = FeedbackRun(
            veredictos_resultados={"3": "incorrecto"},
            motivos_resultados={"3": MotivoFeedback(motivo=MotivoIncorrecto.EMPAREJO_MAL,
                                                    detalle="fila 40, no la 39")},
            respuestas_checklist={"1": "SI", "2": "NO", "7": "N/A"},
            comentarios="ok",
        )
        ruta = feedback.guardar_feedback(RUN_ID, fb)

        assert ruta == settings.feedback_dir.resolve() / RUN_ID / "feedback.json"
        assert not (runs_dir / RUN_ID / "feedback.json").exists()
        assert not list(ruta.parent.glob("*.tmp"))
        leido = feedback.cargar_feedback(RUN_ID)
        assert leido.actualizado is not None
        assert leido.model_dump(exclude={"actualizado"}) == fb.model_dump(exclude={"actualizado"})

    def test_copia_el_reporte_la_version_y_los_insumos_una_vez(self, runs_dir: Path) -> None:
        run = runs_dir / RUN_ID
        for nombre in ("reporte_final.json", "version.json", "inputs.json"):
            (run / nombre).write_text(json.dumps({"archivo": nombre}), encoding="utf-8")
        (run / "metadata.json").write_text("{}", encoding="utf-8")

        feedback.guardar_feedback(RUN_ID, FeedbackRun())
        (run / "reporte_final.json").write_text('{"otro": 1}', encoding="utf-8")
        feedback.guardar_feedback(RUN_ID, FeedbackRun(comentarios="segunda vez"))

        carpeta = settings.feedback_dir / RUN_ID
        assert sorted(p.name for p in carpeta.iterdir()) == [
            "feedback.json", "inputs.json", "reporte_final.json", "version.json"]
        # La copia es la del primer guardado (el reporte que se revisó).
        assert json.loads((carpeta / "reporte_final.json").read_text()) == {
            "archivo": "reporte_final.json"}

    def test_no_escribe_un_archivo_que_no_se_pueda_volver_a_cargar(self, runs_dir: Path) -> None:
        feedback.guardar_feedback(RUN_ID, FeedbackRun(respuestas_checklist={"1": "SI"}))
        fb = feedback.cargar_feedback(RUN_ID)
        fb.respuestas_checklist["2"] = None  # type: ignore[assignment]

        with pytest.raises(ValidationError):
            feedback.guardar_feedback(RUN_ID, fb)

        assert feedback.cargar_feedback(RUN_ID).respuestas_checklist == {"1": "SI"}
        assert not list((settings.feedback_dir / RUN_ID).glob("*.tmp"))

    def test_si_la_retencion_ya_borro_el_run_copia_el_reporte_abierto(
        self, runs_dir: Path
    ) -> None:
        # La interfaz tiene el reporte en memoria: sin él, los índices del
        # feedback no se pueden interpretar.
        from tests.test_streamlit_app import _reporte_060

        reporte = _reporte_060()
        feedback.guardar_feedback("run-borrado", FeedbackRun(comentarios="x"), reporte=reporte)

        copia = settings.feedback_dir / "run-borrado" / "reporte_final.json"
        assert ReporteInforme.model_validate_json(copia.read_text(encoding="utf-8")) == reporte

    def test_la_copia_del_run_tiene_prioridad_sobre_la_de_memoria(self, runs_dir: Path) -> None:
        from tests.test_streamlit_app import _reporte_060

        (runs_dir / RUN_ID / "reporte_final.json").write_text('{"del": "run"}', encoding="utf-8")
        feedback.guardar_feedback(RUN_ID, FeedbackRun(), reporte=_reporte_060())
        assert json.loads((settings.feedback_dir / RUN_ID / "reporte_final.json").read_text()) == {
            "del": "run"}

    def test_run_sin_archivos_no_impide_guardar(self, runs_dir: Path) -> None:
        feedback.guardar_feedback("run-que-ya-no-existe", FeedbackRun(comentarios="x"))
        assert feedback.cargar_feedback("run-que-ya-no-existe").comentarios == "x"

    def test_el_nuevo_tiene_prioridad_sobre_el_antiguo(self, runs_dir: Path) -> None:
        (runs_dir / RUN_ID / "feedback.json").write_text(
            FeedbackRun(comentarios="antiguo").model_dump_json(), encoding="utf-8")
        assert feedback.cargar_feedback(RUN_ID).comentarios == "antiguo"

        feedback.guardar_feedback(RUN_ID, FeedbackRun(comentarios="nuevo"))

        assert feedback.cargar_feedback(RUN_ID).comentarios == "nuevo"
        # El antiguo no se toca.
        assert json.loads((runs_dir / RUN_ID / "feedback.json").read_text())[
            "comentarios"] == "antiguo"

    def test_el_antiguo_sin_los_campos_nuevos_carga(self, runs_dir: Path) -> None:
        (runs_dir / RUN_ID / "feedback.json").write_text(json.dumps({
            "veredictos_resultados": {"0": "correcto"},
            "veredictos_checklist": {"5": "incorrecto"},
            "comentarios": "", "actualizado": "2026-07-20T10:00:00",
        }), encoding="utf-8")

        fb = feedback.cargar_feedback(RUN_ID)

        assert fb.veredictos_checklist == {"5": "incorrecto"}
        assert fb.respuestas_checklist == {} and fb.motivos_resultados == {}

    def test_sobrevive_a_la_retencion_de_runs(self, runs_dir: Path) -> None:
        run = runs_dir / RUN_ID
        (run / "reporte_final.json").write_text('{"r": 1}', encoding="utf-8")
        feedback.guardar_feedback(RUN_ID, FeedbackRun(comentarios="revisado"))
        for i, nombre in enumerate(("b", "c", "d"), start=1):
            nuevo = runs_dir / nombre
            nuevo.mkdir()
            (nuevo / "reporte_final.json").write_text("{}", encoding="utf-8")
            os.utime(nuevo, (run.stat().st_mtime + i, run.stat().st_mtime + i))

        borrados = limpiar_runs_antiguos(retener=3)

        assert borrados == [run]
        assert feedback.cargar_feedback(RUN_ID).comentarios == "revisado"
        assert (settings.feedback_dir / RUN_ID / "reporte_final.json").exists()


class TestGuardarPorDiferencias:
    """Cada sesión guarda solo lo que cambió (feedback.cambios +
    actualizar_feedback): dos pestañas sobre el mismo run no se pisan."""

    def test_cambios_ve_altas_bajas_y_modificaciones(self) -> None:
        antes = FeedbackRun(veredictos_resultados={"0": "correcto", "1": "incorrecto"},
                            respuestas_checklist={"1": "SI"}, comentarios="a")
        despues = antes.model_copy(deep=True)
        despues.veredictos_resultados.pop("0")
        despues.veredictos_resultados["1"] = "correcto"
        despues.veredictos_resultados["2"] = "incorrecto"

        c = feedback.cambios(antes, despues)

        assert c.mapas["veredictos_resultados"] == {"0": None, "1": "correcto",
                                                    "2": "incorrecto"}
        assert c.mapas["respuestas_checklist"] == {}
        assert c.comentarios is None
        assert c and not feedback.cambios(antes, antes)

    def test_dos_sesiones_conservan_lo_de_la_otra(self, runs_dir: Path) -> None:
        cargado_a = feedback.cargar_feedback(RUN_ID)
        cargado_b = feedback.cargar_feedback(RUN_ID)
        a, b = cargado_a.model_copy(deep=True), cargado_b.model_copy(deep=True)
        a.respuestas_checklist.update({"1": "SI", "2": "NO"})
        a.veredictos_resultados["0"] = "incorrecto"
        a.motivos_resultados["0"] = MotivoFeedback(motivo=MotivoIncorrecto.OTRO)
        b.comentarios = "nota de la otra pestaña"
        b.respuestas_checklist["3"] = "N/A"

        feedback.actualizar_feedback(RUN_ID, feedback.cambios(cargado_a, a).aplicar)
        feedback.actualizar_feedback(RUN_ID, feedback.cambios(cargado_b, b).aplicar)

        fb = feedback.cargar_feedback(RUN_ID)
        assert fb.respuestas_checklist == {"1": "SI", "2": "NO", "3": "N/A"}
        assert fb.veredictos_resultados == {"0": "incorrecto"}
        assert fb.motivos_resultados["0"].motivo == MotivoIncorrecto.OTRO
        assert fb.comentarios == "nota de la otra pestaña"

    def test_comentarios_de_dos_sesiones_se_conservan(self, runs_dir: Path) -> None:
        cargado_a = feedback.cargar_feedback(RUN_ID)
        cargado_b = feedback.cargar_feedback(RUN_ID)
        a, b = cargado_a.model_copy(deep=True), cargado_b.model_copy(deep=True)
        b.comentarios = "B: revisado hasta el paño C3."
        a.comentarios = "A: el punto 12 está mal."

        feedback.actualizar_feedback(RUN_ID, feedback.cambios(cargado_b, b).aplicar)
        fusionado = feedback.actualizar_feedback(RUN_ID, feedback.cambios(cargado_a, a).aplicar)

        assert fusionado.comentarios == "B: revisado hasta el paño C3.\n\nA: el punto 12 está mal."
        # Vaciar el propio campo no borra el texto que escribió la otra sesión.
        vacio = a.model_copy(update={"comentarios": ""})
        assert feedback.actualizar_feedback(
            RUN_ID, feedback.cambios(a, vacio).aplicar).comentarios == fusionado.comentarios

    def test_agregar_al_comentario_suma_solo_lo_nuevo(self, runs_dir: Path) -> None:
        feedback.guardar_feedback(RUN_ID, FeedbackRun(comentarios="Base."))
        base = feedback.cargar_feedback(RUN_ID)
        otra, esta = base.model_copy(deep=True), base.model_copy(deep=True)
        otra.comentarios = "Base. Nota de la otra."
        esta.comentarios = "Base. Nota de esta."
        feedback.actualizar_feedback(RUN_ID, feedback.cambios(base, otra).aplicar)

        resultado = feedback.actualizar_feedback(RUN_ID, feedback.cambios(base, esta).aplicar)

        # Lo que agregó cada una, en el orden en que se guardó.
        assert resultado.comentarios == "Base. Nota de la otra. Nota de esta."

    @pytest.mark.parametrize(("texto_b", "esperado"), [
        ("Revisado hasta C3.\n\nFalta el punto 13.",
         "Revisado hasta C3.\n\nFalta el punto 13.\n\nPaño C4 OK."),
        ("Revisado hasta C3.", "Revisado hasta C3.\n\nPaño C4 OK."),
    ], ids=["corrige", "borra"])
    def test_las_dos_agregan_y_una_corrige_o_borra_su_nota(
        self, runs_dir: Path, texto_b: str, esperado: str
    ) -> None:
        """Sin duplicar la base: B agrega, A agrega (B no lo ve) y B corrige o
        borra su nota: queda la de A y el cambio de B en su lugar."""
        feedback.guardar_feedback(RUN_ID, FeedbackRun(comentarios="Revisado hasta C3."))
        base = feedback.cargar_feedback(RUN_ID)

        def guardar(antes: FeedbackRun, texto: str) -> FeedbackRun:
            despues = antes.model_copy(update={"comentarios": texto})
            guardado = feedback.actualizar_feedback(
                RUN_ID, feedback.cambios(antes, despues).aplicar)
            return despues.model_copy(update={"comentarios": guardado.comentarios})

        b = guardar(base, "Revisado hasta C3.\n\nFalta el punto 12.")
        guardar(base, "Revisado hasta C3.\n\nPaño C4 OK.")
        assert feedback.cargar_feedback(RUN_ID).comentarios == (
            "Revisado hasta C3.\n\nFalta el punto 12.\n\nPaño C4 OK.")

        assert guardar(b, texto_b).comentarios == esperado

    def test_si_la_otra_lo_vacio_queda_el_texto_sin_saltos_de_mas(self, runs_dir: Path) -> None:
        feedback.guardar_feedback(RUN_ID, FeedbackRun(comentarios="Revisado hasta C3."))
        base = feedback.cargar_feedback(RUN_ID)
        otra = base.model_copy(update={"comentarios": ""})
        feedback.actualizar_feedback(RUN_ID, feedback.cambios(base, otra).aplicar)
        esta = base.model_copy(update={"comentarios": "Revisado hasta C4."})

        resultado = feedback.actualizar_feedback(RUN_ID, feedback.cambios(base, esta).aplicar)

        assert resultado.comentarios == "Revisado hasta C4."

    def test_corregir_o_vaciar_la_propia_nota_no_toca_la_de_la_otra(self, runs_dir: Path) -> None:
        feedback.guardar_feedback(RUN_ID, FeedbackRun(comentarios="Revisado hasta C3."))
        base = feedback.cargar_feedback(RUN_ID)
        otra, esta = base.model_copy(deep=True), base.model_copy(deep=True)
        otra.comentarios = "Revisado hasta C3.\n\nFalta el punto 12."
        feedback.actualizar_feedback(RUN_ID, feedback.cambios(base, otra).aplicar)

        esta.comentarios = "Revisado hasta C4."
        corregido = feedback.actualizar_feedback(RUN_ID, feedback.cambios(base, esta).aplicar)
        assert corregido.comentarios == "Revisado hasta C4.\n\nFalta el punto 12."
        vacio = esta.model_copy(update={"comentarios": ""})
        assert feedback.actualizar_feedback(
            RUN_ID, feedback.cambios(esta, vacio).aplicar).comentarios == "Falta el punto 12."

    def test_guardados_simultaneos_no_pierden_ninguno(self, runs_dir: Path) -> None:
        import threading

        def responder(n: int) -> None:
            def cambiar(fb: FeedbackRun) -> None:
                fb.respuestas_checklist[str(n)] = "SI"
            feedback.actualizar_feedback(RUN_ID, cambiar)

        hilos = [threading.Thread(target=responder, args=(n,)) for n in range(1, 39)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()

        assert len(feedback.cargar_feedback(RUN_ID).respuestas_checklist) == 38
        assert not [p for p in (settings.feedback_dir / RUN_ID).iterdir()
                    if p.name.endswith(".tmp")]

    def test_dos_procesos_no_se_pisan(self, runs_dir: Path) -> None:
        """Streamlit y el server legacy son procesos distintos: el lock de hilos
        no alcanza, el archivo de bloqueo sí."""
        import multiprocessing

        contexto = multiprocessing.get_context("spawn")
        procesos = [contexto.Process(target=_responder_en_otro_proceso, args=(
            str(settings.runs_dir), str(settings.feedback_dir), campo, 40))
            for campo in ("respuestas_checklist", "veredictos_resultados")]
        for proceso in procesos:
            proceso.start()
        for proceso in procesos:
            proceso.join(60)
            assert proceso.exitcode == 0

        fb = feedback.cargar_feedback(RUN_ID)
        assert len(fb.respuestas_checklist) == 40
        assert len(fb.veredictos_resultados) == 40

    def test_el_archivo_de_bloqueo_que_quedo_no_traba(self, runs_dir: Path) -> None:
        # El bloqueo es del sistema operativo, no la existencia del archivo: uno
        # que quedó de un proceso que murió no traba nada.
        settings.feedback_dir.mkdir(parents=True, exist_ok=True)
        (settings.feedback_dir / ".feedback.lock").write_text("99999")

        feedback.guardar_feedback(RUN_ID, FeedbackRun(comentarios="ok"))

        assert feedback.cargar_feedback(RUN_ID).comentarios == "ok"

    def test_un_bloqueo_tomado_por_otro_proceso_hace_esperar_y_avisa(
        self, runs_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import multiprocessing

        monkeypatch.setattr(feedback, "_ESPERA_BLOQUEO_S", 0.3)
        contexto = multiprocessing.get_context("spawn")
        tomado, soltar = contexto.Event(), contexto.Event()
        otro = contexto.Process(target=_tomar_bloqueo_en_otro_proceso, args=(
            str(settings.runs_dir), str(settings.feedback_dir), tomado, soltar))
        otro.start()
        try:
            assert tomado.wait(30)
            with pytest.raises(TimeoutError, match="tiene tomado el feedback"):
                feedback.guardar_feedback(RUN_ID, FeedbackRun(comentarios="x"))
        finally:
            soltar.set()
            otro.join(30)
        # Liberado por el otro proceso, se guarda.
        feedback.guardar_feedback(RUN_ID, FeedbackRun(comentarios="después"))
        assert feedback.cargar_feedback(RUN_ID).comentarios == "después"

    def test_una_copia_cortada_se_rehace(self, runs_dir: Path) -> None:
        (runs_dir / RUN_ID / "reporte_final.json").write_text('{"r": 1}', encoding="utf-8")
        carpeta = settings.feedback_dir / RUN_ID
        carpeta.mkdir(parents=True)
        (carpeta / "reporte_final.json").write_text('{"r": ', encoding="utf-8")

        feedback.guardar_feedback(RUN_ID, FeedbackRun())

        assert json.loads((carpeta / "reporte_final.json").read_text()) == {"r": 1}


class TestFeedbackAnterior:
    def test_se_migra_al_leerlo_y_sobrevive_a_la_retencion(self, runs_dir: Path) -> None:
        """Abierto el run con su feedback anterior (dentro del run), la retención
        lo borra antes del primer guardado: lo anterior no se pierde."""
        run = runs_dir / RUN_ID
        (run / "reporte_final.json").write_text('{"r": 1}', encoding="utf-8")
        (run / "feedback.json").write_text(FeedbackRun(
            veredictos_resultados={"1": "incorrecto"}, comentarios="anterior",
        ).model_dump_json(), encoding="utf-8")
        abierto = feedback.cargar_feedback(RUN_ID)
        sesion = abierto.model_copy(deep=True)

        shutil.rmtree(run)
        sesion.veredictos_resultados["7"] = "correcto"
        feedback.actualizar_feedback(RUN_ID, feedback.cambios(abierto, sesion).aplicar)

        fb = feedback.cargar_feedback(RUN_ID)
        assert fb.veredictos_resultados == {"1": "incorrecto", "7": "correcto"}
        assert fb.comentarios == "anterior"
        assert (settings.feedback_dir / RUN_ID / "reporte_final.json").exists()

    def test_migrar_conserva_la_fecha_de_la_ultima_actualizacion(self, runs_dir: Path) -> None:
        (runs_dir / RUN_ID / "feedback.json").write_text(json.dumps({
            "comentarios": "anterior", "actualizado": "2026-07-20T10:00:00"}), encoding="utf-8")

        primera, segunda = feedback.cargar_feedback(RUN_ID), feedback.cargar_feedback(RUN_ID)

        assert primera.actualizado == segunda.actualizado
        assert str(segunda.actualizado) == "2026-07-20 10:00:00"


class TestAplicarRespuestas:
    def test_detecta_cambios_y_borra_las_vacias(self) -> None:
        almacen = {"1": "SI", "2": "NO"}

        assert feedback.aplicar_respuestas(["SI", None, "N/A"], almacen, ["1", "2", "3"])
        assert almacen == {"1": "SI", "3": "N/A"}
        assert not feedback.aplicar_respuestas(["SI", None, "N/A"], almacen, ["1", "2", "3"])

    @pytest.mark.parametrize("vacia", [None, float("nan"), "— sin revisar", ""])
    def test_una_celda_vaciada_cuenta_como_sin_respuesta(self, vacia: object) -> None:
        # La grilla de Streamlit entrega NaN o None al vaciar una celda: antes
        # se guardaba como respuesta y el archivo ya no se podía volver a cargar.
        almacen = {"1": "SI"}
        assert feedback.aplicar_respuestas([vacia, vacia], almacen, ["1", "2"])
        assert almacen == {}
        assert not feedback.aplicar_respuestas([vacia], almacen, ["2"])

    def test_largos_distintos_fallan(self) -> None:
        with pytest.raises(ValueError):
            feedback.aplicar_respuestas(["SI"], {}, ["1", "2"])


class TestSchema:
    def test_respuesta_del_checklist_fuera_de_la_planilla_falla(self) -> None:
        with pytest.raises(ValidationError):
            FeedbackRun.model_validate({"respuestas_checklist": {"1": "Cumple"}})

    def test_motivo_desconocido_falla(self) -> None:
        with pytest.raises(ValidationError):
            MotivoFeedback.model_validate({"motivo": "no_se"})

    def test_cada_motivo_tiene_su_etiqueta(self) -> None:
        assert set(feedback.ETIQUETA_MOTIVO) == set(MotivoIncorrecto)


def test_los_tests_no_escriben_en_la_carpeta_real() -> None:
    from comparador.config import PROJECT_ROOT

    assert not settings.feedback_dir.resolve().is_relative_to(PROJECT_ROOT.resolve())


def _responder_en_otro_proceso(runs: str, raiz: str, campo: str, n: int) -> None:
    from comparador import feedback as fb_mod
    from comparador.config import settings as s

    s.runs_dir, s.feedback_dir = Path(runs), Path(raiz)
    valor = "SI" if campo == "respuestas_checklist" else "correcto"
    for k in range(1, n + 1):
        def cambiar(fb: FeedbackRun, k: int = k) -> None:
            getattr(fb, campo)[str(k)] = valor
        fb_mod.actualizar_feedback(RUN_ID, cambiar)


def _tomar_bloqueo_en_otro_proceso(runs: str, raiz: str, tomado: Any, soltar: Any) -> None:
    from comparador import feedback as fb_mod
    from comparador.config import settings as s

    s.runs_dir, s.feedback_dir = Path(runs), Path(raiz)
    with fb_mod._bloqueo():
        tomado.set()
        soltar.wait(30)


def test_la_configuracion_no_muestra_las_claves() -> None:
    from comparador.config import Settings

    texto = repr(Settings(openai_api_key="sk-secreta-123", anthropic_api_key="sk-ant-secreta"))
    assert "secreta" not in texto


def test_un_error_de_validacion_no_muestra_las_claves(tmp_path: Path) -> None:
    from comparador.config import Settings

    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, runs_dir=tmp_path / "runs",
                 feedback_dir=tmp_path / "runs" / "feedback",
                 anthropic_api_key="sk-ant-SECRETA-0123456789abcdefghijklmnop")
    assert "FEEDBACK_DIR" in str(error.value)
    assert "SECRETA" not in str(error.value) and "input_value" not in str(error.value)
