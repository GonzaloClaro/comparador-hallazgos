"""Tests de persistencia de runs."""

import errno
import json
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from comparador import persistence
from comparador.config import Settings
from comparador.persistence import cargar_json, crear_run_dir, guardar_json
from comparador.schemas import EmpresaAuditora, ReporteInforme, ResumenInforme


class TestCrearRunDir:
    def test_runs_simultaneos_no_comparten_carpeta(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(persistence.settings, "runs_dir", tmp_path)
        # Este test aísla el mecanismo de sufijo ante colisión de nombre del
        # de retención de incompletos (son cosas distintas): si no se
        # desactiva, la limpieza automática borraría los incompletos viejos
        # entre llamada y llamada y liberaría su nombre — justo lo que este
        # test verifica que NUNCA pase dentro del mismo segundo.
        monkeypatch.setattr(persistence.settings, "runs_incompletos_a_retener", 100)

        # Mismo segundo (llamadas consecutivas): deben salir carpetas distintas.
        dirs = [crear_run_dir("modelo-x") for _ in range(3)]

        assert len({d.name for d in dirs}) == 3
        for d in dirs:
            assert d.is_dir()
            assert (d / "etapa3_raw").is_dir()

    def test_sufijo_incremental_ante_colision(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(persistence.settings, "runs_dir", tmp_path)
        a = crear_run_dir("m")
        b = crear_run_dir("m")
        if a.name.split("_")[0:2] == b.name.split("_")[0:2]:
            assert b.name.endswith("-2")


    def test_nombre_de_modelo_con_dos_puntos_da_un_run_id_valido(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # Un fine-tune de OpenAI: "ft:gpt-4o-mini-2024-07-18:acme::abc123".
        from comparador import feedback

        monkeypatch.setattr(persistence.settings, "runs_dir", tmp_path)
        run = crear_run_dir("ft:gpt-4o-mini-2024-07-18:acme::abc123")
        assert run.name.endswith("_ft_gpt-4o-mini-2024-07-18_acme__abc123")
        assert feedback.validar_run_id(run.name) == run.name


class TestRutaDentroDe:
    def test_misma_carpeta_con_otras_mayusculas(self, tmp_path: Path):
        from comparador.rutas import ruta_dentro_de

        runs = tmp_path / "runs"
        runs.mkdir()
        if not Path(str(runs).upper()).exists():
            pytest.skip("este disco distingue mayúsculas")
        assert ruta_dentro_de(Path(str(runs).upper()) / "replay", runs)
        assert not ruta_dentro_de(tmp_path / "otra" / "replay", runs)

    def test_carpeta_que_todavia_no_existe(self, tmp_path: Path):
        from comparador.rutas import ruta_dentro_de

        runs = tmp_path / "mediciones" / "b3" / "runs"   # aún no creada
        (tmp_path / "mediciones" / "b3").mkdir(parents=True)
        assert ruta_dentro_de(runs / "replay", runs)
        assert ruta_dentro_de(tmp_path / "mediciones" / "B3" / "RUNS" / "replay", runs)
        assert not ruta_dentro_de(tmp_path / "mediciones" / "b3" / "replay_e4", runs)


def repo_git(carpeta: Path, gitignore: str) -> Path:
    """Un repositorio git nuevo en `carpeta/repo` con ese .gitignore (sin git, salta)."""
    if shutil.which("git") is None:
        pytest.skip("sin git instalado")
    repo = carpeta / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".gitignore").write_text(gitignore, encoding="utf-8")
    return repo


class TestExigirIgnoradaPorGit:
    """Las salidas con texto de informes reales (repeticiones de E4, vectores,
    GT del comparador) no quedan al alcance de un `git add`."""

    def test_dentro_de_un_repo_tiene_que_estar_ignorada(self, tmp_path: Path) -> None:
        from comparador.rutas import exigir_ignorada_por_git

        repo = repo_git(tmp_path, "privado/\n*.npz\n")
        exigir_ignorada_por_git(repo / "privado" / "replay" / "x", "--salida", carpeta=True)
        exigir_ignorada_por_git(repo / "docs" / "v.npz", "--solo-vectores")
        for ruta, carpeta in ((repo / "replay_tmp", True), (repo / "docs" / "v.json", False),
                              (repo / "docs", True),   # un *.npz no cubre la carpeta entera
                              (repo, True)):
            with pytest.raises(ValueError, match="git no la ignora"):
                exigir_ignorada_por_git(ruta, "--salida", carpeta=carpeta)
        assert not (repo / "replay_tmp").exists()

    def test_otras_mayusculas_o_un_enlace_no_la_esquivan(self, tmp_path: Path) -> None:
        from comparador.rutas import exigir_ignorada_por_git

        repo = repo_git(tmp_path, "privado/\n")
        (tmp_path / "enlace").symlink_to(repo, target_is_directory=True)
        with pytest.raises(ValueError, match="git no la ignora"):
            exigir_ignorada_por_git(tmp_path / "enlace" / "replay", "--salida", carpeta=True)
        exigir_ignorada_por_git(tmp_path / "enlace" / "privado" / "r", "--salida", carpeta=True)
        if Path(str(repo).upper()).exists():   # disco que no distingue mayúsculas
            exigir_ignorada_por_git(Path(str(repo).upper()) / "PRIVADO" / "r", "--salida",
                                    carpeta=True)

    def test_fuera_de_todo_repo_no_hay_nada_que_comprobar(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from comparador import rutas

        def _no_llamar(*args: object, **kwargs: object) -> None:
            raise AssertionError("fuera de un repo no se llama a git")

        monkeypatch.setattr(subprocess, "run", _no_llamar)
        rutas.exigir_ignorada_por_git(tmp_path / "replay", "--salida", carpeta=True)

    @pytest.mark.parametrize("falla", ["sin_git", "git_falla"])
    def test_sin_git_avisa_y_sigue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, falla: str
    ) -> None:
        """No depende de que git exista: sin git tampoco hay `git add`."""
        from comparador import rutas

        (tmp_path / "repo" / ".git").mkdir(parents=True)   # un repo, sin pedirle nada a git

        def _run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            if falla == "sin_git":
                raise FileNotFoundError("git")
            return subprocess.CompletedProcess([], 128, "", "fatal: algo")

        monkeypatch.setattr(subprocess, "run", _run)
        with pytest.warns(UserWarning, match="No se pudo comprobar con git"):
            rutas.exigir_ignorada_por_git(tmp_path / "repo" / "replay", "--salida",
                                          carpeta=True)

    def test_el_gitignore_del_proyecto_cubre_las_salidas_privadas(self) -> None:
        from comparador.rutas import exigir_ignorada_por_git

        raiz = Path(__file__).resolve().parents[1]
        if not (raiz / ".git").exists() or shutil.which("git") is None:
            pytest.skip("el proyecto no está en un repositorio git, o no hay git")
        exigir_ignorada_por_git(raiz / "mediciones" / "replay_e4" / "AG1" / "r", "--salida",
                                carpeta=True)
        exigir_ignorada_por_git(raiz / "mediciones" / "gt" / "comparador", "--salida",
                                carpeta=True)
        # Los vectores llevan los textos de los hallazgos: ignorados en cualquier carpeta.
        exigir_ignorada_por_git(raiz / "docs" / "x" / "etapa4_embeddings.npz",
                                "--solo-vectores")
        with pytest.raises(ValueError, match="git no la ignora"):
            exigir_ignorada_por_git(raiz / "replay_tmp", "--salida", carpeta=True)


class TestLimpiarRunsAntiguos:
    def _crear_run_completo(self, base: Path, nombre: str, mtime: float) -> Path:
        run_dir = base / nombre
        run_dir.mkdir()
        (run_dir / "reporte_final.json").write_text("{}", encoding="utf-8")
        os.utime(run_dir, (mtime, mtime))
        return run_dir

    def _crear_run_incompleto(self, base: Path, nombre: str, mtime: float) -> Path:
        run_dir = base / nombre
        run_dir.mkdir()
        os.utime(run_dir, (mtime, mtime))
        return run_dir

    def test_conserva_solo_los_mas_recientes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(persistence.settings, "runs_dir", tmp_path)
        monkeypatch.setattr(persistence.settings, "runs_a_retener", 3)

        ahora = time.time()
        for i, nombre in enumerate(["r1", "r2", "r3", "r4", "r5"]):
            self._crear_run_completo(tmp_path, nombre, ahora - (5 - i) * 100)

        borrados = persistence.limpiar_runs_antiguos()

        assert {d.name for d in borrados} == {"r1", "r2"}
        assert {d.name for d in tmp_path.iterdir()} == {"r3", "r4", "r5"}

    def test_incompleto_unico_sobrevive_dentro_del_top(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(persistence.settings, "runs_dir", tmp_path)
        monkeypatch.setattr(persistence.settings, "runs_a_retener", 1)

        ahora = time.time()
        incompleto = tmp_path / "incompleto"
        incompleto.mkdir()
        os.utime(incompleto, (ahora - 1000, ahora - 1000))
        self._crear_run_completo(tmp_path, "reciente", ahora)

        borrados = persistence.limpiar_runs_antiguos()

        assert borrados == []
        assert incompleto.exists()

    def test_incompletos_viejos_se_borran_salvo_el_mas_reciente(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(persistence.settings, "runs_dir", tmp_path)
        monkeypatch.setattr(persistence.settings, "runs_incompletos_a_retener", 1)

        ahora = time.time()
        viejo = self._crear_run_incompleto(tmp_path, "incompleto_viejo", ahora - 200)
        reciente = self._crear_run_incompleto(tmp_path, "incompleto_reciente", ahora - 100)

        borrados = persistence.limpiar_runs_antiguos()

        assert borrados == [viejo]
        assert not viejo.exists()
        assert reciente.exists()

    def test_runs_incompletos_a_retener_configurable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(persistence.settings, "runs_dir", tmp_path)
        monkeypatch.setattr(persistence.settings, "runs_incompletos_a_retener", 2)

        ahora = time.time()
        self._crear_run_incompleto(tmp_path, "i1", ahora - 300)
        self._crear_run_incompleto(tmp_path, "i2", ahora - 200)
        self._crear_run_incompleto(tmp_path, "i3", ahora - 100)

        borrados = persistence.limpiar_runs_antiguos()

        assert {d.name for d in borrados} == {"i1"}
        assert {d.name for d in tmp_path.iterdir()} == {"i2", "i3"}

    def test_runs_incompletos_a_retener_menor_a_uno_falla_ruidoso(self):
        with pytest.raises(ValidationError):
            Settings(runs_incompletos_a_retener=0)

    def test_runs_a_retener_configurable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(persistence.settings, "runs_dir", tmp_path)
        monkeypatch.setattr(persistence.settings, "runs_a_retener", 1)

        ahora = time.time()
        self._crear_run_completo(tmp_path, "viejo", ahora - 100)
        self._crear_run_completo(tmp_path, "nuevo", ahora)

        borrados = persistence.limpiar_runs_antiguos()

        assert {d.name for d in borrados} == {"viejo"}

    def test_runs_a_retener_menor_a_uno_falla_ruidoso(self):
        with pytest.raises(ValidationError):
            Settings(runs_a_retener=0)

    def test_crear_run_dir_dispara_la_limpieza(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(persistence.settings, "runs_dir", tmp_path)
        monkeypatch.setattr(persistence.settings, "runs_a_retener", 1)

        ahora = time.time()
        viejo1 = self._crear_run_completo(tmp_path, "viejo1_completo", ahora - 200)
        viejo2 = self._crear_run_completo(tmp_path, "viejo2_completo", ahora - 100)

        crear_run_dir("modelo-y")

        assert not viejo1.exists()
        assert viejo2.exists()



class TestRunEnCurso:
    def test_la_retencion_no_borra_un_run_en_curso(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Tras el botón Stop, la etapa ya enviada sigue en su hilo y se puede
        iniciar otro procesamiento: el run detenido no se borra mientras se
        escribe (antes ocupaba el único cupo de incompletos y se perdía)."""
        from comparador.persistence import terminar_run

        monkeypatch.setattr(persistence.settings, "runs_dir", tmp_path)
        monkeypatch.setattr(persistence.settings, "runs_incompletos_a_retener", 1)
        detenido = crear_run_dir("modelo-a")
        os.utime(detenido, (1, 1))   # el más viejo
        nuevo = crear_run_dir("modelo-b")

        assert detenido.exists()
        terminar_run(detenido)
        terminar_run(nuevo)
        otro = crear_run_dir("modelo-c")

        assert not detenido.exists()          # liberado, ya cuenta para la retención
        assert nuevo.exists() and otro.exists()
        terminar_run(otro)

    def test_un_run_que_otro_borra_a_mitad_no_rompe_la_retencion(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from comparador.persistence import limpiar_runs_antiguos

        monkeypatch.setattr(persistence.settings, "runs_dir", tmp_path)
        for nombre in ("a", "b", "c"):
            (tmp_path / nombre).mkdir()
        original = Path.stat
        llamadas_b = 0

        def _stat(self: Path, *args: object, **kwargs: object) -> os.stat_result:
            nonlocal llamadas_b
            if self.name == "b":
                llamadas_b += 1
                if llamadas_b > 1:   # existía en el iterdir; otro lo borró antes del stat
                    raise FileNotFoundError(errno.ENOENT, "borrado", str(self))
            return original(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "stat", _stat)
        limpiar_runs_antiguos(retener=1, retener_incompletos=1)   # no lanza
        assert llamadas_b > 1

    def test_si_la_retencion_falla_el_run_nuevo_no_queda_en_curso(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(persistence.settings, "runs_dir", tmp_path)

        def _falla(*args: object, **kwargs: object) -> list[Path]:
            raise PermissionError("sin permiso")

        monkeypatch.setattr(persistence, "limpiar_runs_antiguos", _falla)
        with pytest.raises(PermissionError):
            crear_run_dir("modelo-x")
        assert not persistence._EN_CURSO

class TestRunSoloChecklist:
    def test_la_retencion_lo_trata_como_completo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # Sin reporte_final.json, pero terminado: no se poda como incompleto.
        monkeypatch.setattr(persistence.settings, "runs_dir", tmp_path)
        monkeypatch.setattr(persistence.settings, "runs_a_retener", 3)
        monkeypatch.setattr(persistence.settings, "runs_incompletos_a_retener", 1)
        ahora = time.time()
        solo = tmp_path / "solo"
        solo.mkdir()
        (solo / "metadata.json").write_text(json.dumps({"modo": "solo_checklist"}))
        os.utime(solo, (ahora - 500, ahora - 500))
        for i, nombre in enumerate(["inc1", "inc2"]):
            d = tmp_path / nombre
            d.mkdir()
            os.utime(d, (ahora - 100 * (2 - i), ahora - 100 * (2 - i)))

        persistence.limpiar_runs_antiguos()

        assert persistence.es_solo_checklist(solo)
        assert {d.name for d in tmp_path.iterdir()} == {"solo", "inc2"}

    def test_metadata_ilegible_no_es_solo_checklist(self, tmp_path: Path):
        (tmp_path / "metadata.json").write_text("{no es json")
        assert not persistence.es_solo_checklist(tmp_path)


class TestFormatoReporteFinal:
    def test_fecha_procesamiento_iso_y_roundtrip(self, tmp_path: Path):
        reporte = ReporteInforme(
            empresa_auditora=EmpresaAuditora.ENSAUT,
            coordinado="COORDINADO C",
            subestacion="Theta",
            informe_id="EN-1",
            fecha_auditoria=None,
            fecha_procesamiento=datetime(2026, 7, 7, 12, 0, 0),
            modelo_extraccion="claude-haiku-4-5",
            modelo_embeddings="text-embedding-3-large",
            resumen=ResumenInforme(
                total=0, coinciden=0, difieren=0,
                faltan_en_excel=0, extra_en_excel=0, requieren_revision=0,
            ),
            resultados=[],
        )

        # Igual que pipeline.py: mode="json" para formato estable (ISO-8601).
        guardar_json(tmp_path, "reporte_final.json", reporte.model_dump(mode="json"))
        data = cargar_json(tmp_path / "reporte_final.json")

        assert data["fecha_procesamiento"] == "2026-07-07T12:00:00"
        restaurado = ReporteInforme.model_validate(data)
        assert restaurado.fecha_procesamiento == reporte.fecha_procesamiento


class TestVectoresE4:
    """etapa4_embeddings.npz (M70): los vectores de E4 en la raíz del run, para
    repetir E4 sin volver a pagar (y con los mismos vectores) los embeddings."""

    TEXTOS = ["DUF desactualizado ", "Relé sin GPS.\nNo cumple", "ñandú 😀", "", "x" * 3000]

    def _vectores(self, dtype: type = np.float32) -> dict[str, np.ndarray]:
        rng = np.random.default_rng(7)
        # Lo que entrega el SDK de OpenAI: float32 decodificados como float64.
        return {t: rng.normal(size=16).astype(dtype).astype(np.float64) for t in self.TEXTOS}

    def test_ida_y_vuelta_exacta_en_float32(self, tmp_path: Path):
        vectores = self._vectores()

        ruta = persistence.guardar_vectores(tmp_path, vectores, "text-embedding-3-large")
        cargados, modelo = persistence.cargar_vectores(ruta)

        assert ruta == tmp_path / "etapa4_embeddings.npz" == tmp_path / persistence.ARCHIVO_VECTORES
        assert modelo == "text-embedding-3-large"
        assert list(cargados) == self.TEXTOS
        assert all(v.dtype == np.float64 and np.array_equal(v, vectores[t])
                   for t, v in cargados.items())
        with np.load(ruta, allow_pickle=False) as npz:
            assert npz["vectores"].dtype == np.float32   # sin perder nada

    def test_lo_que_no_es_float32_exacto_se_guarda_en_float64(self, tmp_path: Path):
        vectores = self._vectores(np.float64)
        ruta = persistence.guardar_vectores(tmp_path, vectores, "m")
        cargados, _ = persistence.cargar_vectores(ruta)
        assert all(np.array_equal(cargados[t], vectores[t]) for t in self.TEXTOS)
        with np.load(ruta, allow_pickle=False) as npz:
            assert npz["vectores"].dtype == np.float64

    def test_escribir_en_una_ruta_cualquiera_sin_pisar(self, tmp_path: Path):
        destino = tmp_path / "vectores_e4" / "run.npz"
        persistence.escribir_vectores(destino, self._vectores(), "m")
        assert set(persistence.cargar_vectores(destino)[0]) == set(self.TEXTOS)
        with pytest.raises(FileExistsError):
            persistence.escribir_vectores(destino, self._vectores(), "m")

    def test_un_texto_que_numpy_no_conserva_falla_al_guardar(self, tmp_path: Path):
        with pytest.raises(ValueError, match="no se conserva"):
            persistence.guardar_vectores(tmp_path, {"texto\x00": np.ones(3)}, "m")
        assert not (tmp_path / persistence.ARCHIVO_VECTORES).exists()

    def test_se_carga_sin_pickle(self, tmp_path: Path):
        ruta = tmp_path / "malo.npz"
        np.savez(ruta, textos=np.array([{"a": 1}], dtype=object),
                 vectores=np.ones((1, 3), dtype=np.float32), modelo=np.array("m"))
        with pytest.raises(ValueError):
            persistence.cargar_vectores(ruta)

    @pytest.mark.parametrize("caso", ["filas", "repetidos", "sin_modelo", "nan"])
    def test_un_archivo_inconsistente_falla(self, tmp_path: Path, caso: str):
        textos = np.array(["a", "a"] if caso == "repetidos" else ["a", "b"])
        vectores = np.ones((1 if caso == "filas" else 2, 3), dtype=np.float32)
        if caso == "nan":
            vectores[0, 0] = np.nan
        campos = {"textos": textos, "vectores": vectores}
        if caso != "sin_modelo":
            campos["modelo"] = np.array("m")
        ruta = tmp_path / "x.npz"
        np.savez(ruta, **campos)
        with pytest.raises(ValueError, match="x.npz"):
            persistence.cargar_vectores(ruta)


# ------------------------------------------------------------ código congelado (E10)


def copiar_src(destino: Path) -> Path:
    """Copia del paquete que corre como `destino/comparador` (lo que se hace con
    `cp -R src mediciones/b3/src` antes de una ronda), sin __pycache__."""
    import shutil

    shutil.copytree(Path(persistence.__file__).resolve().parent, destino / "comparador",
                    ignore=shutil.ignore_patterns("__pycache__"))
    return destino


class TestCodigoCongelado:
    """`--codigo-congelado` (evaluar_lote, reproducir_e4): antes de gastar en una
    ronda, el código que corre es el de la copia congelada de `src/`, con el mismo
    hash que la ficha de versión de metricas_lote le dará a la ronda."""

    def test_copia_exacta_pasa_con_el_hash_de_version_codigo(self, tmp_path: Path):
        copia = copiar_src(tmp_path / "src")

        verificado = persistence.verificar_codigo_congelado(copia)

        version = persistence.version_codigo()
        assert verificado["sha256_codigo"] == version["sha256_codigo"]
        assert verificado["archivos_codigo"] == version["archivos_codigo"]
        # El mismo hash que la ficha de versión de la ronda (metricas_confianza).
        assert persistence.hash_arbol(copia)[0][:16] == version["sha256_codigo"]

    @pytest.mark.parametrize("cambio", ["contenido", "archivo_nuevo", "archivo_borrado",
                                        "fuera_de_comparador"])
    def test_una_copia_distinta_falla_nombrando_los_archivos(self, tmp_path: Path, cambio: str):
        copia = copiar_src(tmp_path / "src")
        paquete = copia / "comparador"
        if cambio == "contenido":
            (paquete / "pipeline.py").write_text(
                (paquete / "pipeline.py").read_text(encoding="utf-8") + "\n# cambio\n",
                encoding="utf-8")
            esperado = "comparador/pipeline.py"
        elif cambio == "archivo_nuevo":
            (paquete / "nuevo.py").write_text("x = 1\n", encoding="utf-8")
            esperado = "comparador/nuevo.py"
        elif cambio == "archivo_borrado":
            (paquete / "rutas.py").unlink()
            esperado = "comparador/rutas.py"
        else:   # la ficha de versión hashea todo src/: un .py suelto también la cambia
            (copia / "suelto.py").write_text("x = 1\n", encoding="utf-8")
            esperado = "suelto.py"

        with pytest.raises(persistence.CodigoNoCongeladoError,
                           match="no es el de la copia congelada") as info:
            persistence.verificar_codigo_congelado(copia)
        assert esperado in str(info.value)

    def test_criterios_distintos_fallan(self, tmp_path: Path):
        copia = copiar_src(tmp_path / "src")
        yaml_copia = copia / "comparador" / "checklist_puntos.yaml"
        yaml_copia.write_text(yaml_copia.read_text(encoding="utf-8") + "\n# otro criterio\n",
                              encoding="utf-8")
        with pytest.raises(persistence.CodigoNoCongeladoError,
                           match="comparador/checklist_puntos.yaml"):
            persistence.verificar_codigo_congelado(copia)

    def test_catalogo_configurado_fuera_del_paquete_y_distinto_falla(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # CATALOGO_EMPRESAS_PATH puede apuntar fuera del paquete: version_codigo
        # hashea el configurado, así que la copia congelada debe traer el mismo.
        copia = copiar_src(tmp_path / "src")
        otro = tmp_path / "catalogo_otro.yaml"
        otro.write_text((copia / "comparador" / "catalogo_empresas.yaml").read_text(
            encoding="utf-8") + "\n# hint nuevo\n", encoding="utf-8")
        monkeypatch.setattr(persistence.settings, "catalogo_empresas_path", otro)
        with pytest.raises(persistence.CodigoNoCongeladoError, match="catalogo_empresas"):
            persistence.verificar_codigo_congelado(copia)

    @pytest.mark.parametrize("carpeta", ["inexistente", "sin_comparador"])
    def test_carpeta_que_no_es_una_copia_de_src_falla(self, tmp_path: Path, carpeta: str):
        destino = tmp_path / carpeta
        if carpeta == "sin_comparador":
            destino.mkdir()
            (destino / "algo.py").write_text("x = 1\n", encoding="utf-8")
        with pytest.raises(persistence.CodigoNoCongeladoError, match="copia de src/"):
            persistence.verificar_codigo_congelado(destino)
