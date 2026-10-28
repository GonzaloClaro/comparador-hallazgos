"""Fixtures comunes a toda la suite y compuerta de los golden (GOLDEN_OBLIGATORIO)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest

from comparador.config import settings

# ------------------------------------------------------------ compuerta golden

EXENTO = "exento:"


class CompuertaGolden:
    """Con GOLDEN_OBLIGATORIO=1, un test `golden` saltado hace fallar la sesión.

    Sin mediciones/ o con una ronda que no trae los casos, los golden se saltan
    y la suite queda verde sin haber probado nada: con la variable, eso falla.
    Cuenta como salto la parametrización vacía (pytest la salta con «got empty
    parameter set»), no un xfail. Solo se permiten saltos cuyo motivo empiece
    con «exento:» (se imprimen al final), y la sesión también falla si no
    corrió ningún golden.
    """

    def __init__(self) -> None:
        self.golden: set[str] = set()
        self.corridos: set[str] = set()
        self.saltados: dict[str, str] = {}
        self.exentos: dict[str, str] = {}

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        self.golden = {i.nodeid for i in session.items if i.get_closest_marker("golden")}

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.nodeid not in self.golden:
            return
        if report.skipped and not hasattr(report, "wasxfail"):
            motivo = _motivo_del_salto(report)
            destino = self.exentos if motivo.startswith(EXENTO) else self.saltados
            destino[report.nodeid] = motivo
        elif report.when == "call":
            self.corridos.add(report.nodeid)

    def problemas(self) -> list[str]:
        problemas = [f"golden saltado: {nodeid}: {motivo}"
                     for nodeid, motivo in self.saltados.items()]
        if not self.corridos:
            problemas.append("no corrió ningún test golden")
        return problemas

    def pytest_sessionfinish(self, session: pytest.Session) -> None:
        if self.problemas() and session.exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def pytest_terminal_summary(self, terminalreporter: Any) -> None:
        terminalreporter.section("GOLDEN_OBLIGATORIO")
        terminalreporter.line(f"golden corridos: {len(self.corridos)}")
        for nodeid, motivo in self.exentos.items():
            terminalreporter.line(f"{nodeid}: {motivo}")
        for problema in self.problemas():
            terminalreporter.line(f"FALLA: {problema}", red=True)


def _motivo_del_salto(report: pytest.TestReport) -> str:
    """El motivo tal como lo muestra pytest, sin el prefijo «Skipped: »."""
    motivo = report.longrepr[2] if isinstance(report.longrepr, tuple) else str(report.longrepr)
    return motivo.removeprefix("Skipped: ")


def pytest_configure(config: pytest.Config) -> None:
    if os.environ.get("GOLDEN_OBLIGATORIO", "") not in ("", "0"):
        config.pluginmanager.register(CompuertaGolden(), "compuerta_golden")


# ------------------------------------------------------------ fixtures


@pytest.fixture(autouse=True, scope="session")
def sin_clientes_reales() -> Iterator[None]:
    """Ningún test crea un cliente real de OpenAI o Anthropic: con una clave
    real en el entorno (o en el .env), gastaría. De sesión, para cubrir también
    los fixtures de módulo y de sesión, que corren antes que los de función.
    Quien necesite un cliente lo reemplaza por un falso con su monkeypatch:
    queda encima de este y, al terminar, vuelve la guarda. `pytest.fail` no lo
    atrapa un `except Exception` del código bajo prueba."""
    from comparador.llm import client, embeddings

    def _prohibido() -> Any:
        pytest.fail("Un test intentó crear un cliente real de un proveedor LLM: "
                    "reemplazar get_client / get_client_anthropic por un falso.")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(client, "get_client", _prohibido)
        mp.setattr(client, "get_client_anthropic", _prohibido)
        # embeddings.py importó get_client por nombre: su referencia es otra.
        mp.setattr(embeddings, "get_client", _prohibido)
        yield


@pytest.fixture(autouse=True, scope="session")
def gt_comparador_por_defecto_vacio(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """evaluar_lote, reproducir_e4 y evaluar_comparador buscan por defecto los GT
    del comparador en mediciones/gt/comparador (datos privados): un test que
    corre su CLI sin --gt-comparador / --gt-dir no los lee ni depende de ellos.
    Los dos primeros importaron GT_DIR_DEFAULT por nombre: se cambia en los
    tres. De sesión, como la guarda de los clientes, para cubrir los fixtures de
    módulo (los golden importaron el nombre al recolectar: siguen con el real)."""
    from comparador import evaluar_comparador, evaluar_lote, reproducir_e4

    vacia = tmp_path_factory.mktemp("gt_comparador")
    with pytest.MonkeyPatch.context() as mp:
        for modulo in (evaluar_comparador, evaluar_lote, reproducir_e4):
            mp.setattr(modulo, "GT_DIR_DEFAULT", vacia)
        yield


@pytest.fixture(autouse=True)
def feedback_dir_temporal(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Ningún test escribe en la carpeta real de feedback (trabajo humano que
    no se recupera). Va en su propio temporal, fuera del `tmp_path` del test,
    porque varios tests usan `tmp_path` como runs_dir y el feedback no puede
    quedar dentro de runs/."""
    monkeypatch.setattr(settings, "feedback_dir", tmp_path_factory.mktemp("feedback"))


@pytest.fixture(autouse=True)
def fichas_por_defecto_ausentes(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """evaluar_lote lee por defecto mediciones/fichas_informes.yaml (datos privados):
    un test que corre su CLI sin --fichas no depende de ese archivo."""
    from comparador import fichas

    monkeypatch.setattr(fichas, "RUTA_DEFAULT",
                        tmp_path_factory.mktemp("fichas") / "fichas_informes.yaml")


@pytest.fixture(autouse=True)
def runs_en_curso_aislados() -> Iterator[None]:
    """Cada test arranca sin runs marcados en curso por otro (persistence)."""
    from comparador import persistence

    antes = set(persistence._EN_CURSO)
    persistence._EN_CURSO.clear()
    yield
    persistence._EN_CURSO.clear()
    persistence._EN_CURSO.update(antes)


# Copia pública: los tests golden necesitan los datos privados (mediciones/ e informes reales), que
# no se publican; sin ellos no se recolectan.
_RAIZ_PUBLICA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if not os.path.isdir(os.path.join(_RAIZ_PUBLICA, "mediciones")):
    collect_ignore_glob = ["golden/test_*.py"]
