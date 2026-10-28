"""Los almacenes con texto de informes reales quedan fuera de git (PD59).

El registro de almacenes privados vive aquí: toda carpeta nueva que guarde
texto de informes reales (runs, feedback, copias, mediciones) se agrega a
`ALMACENES_PRIVADOS`, y toda ruta colgada de la raíz del repo que escriba el
código queda clasificada como privada o versionada. git evalúa las reglas
sobre rutas que no existen: nada aquí depende de que las carpetas existan.

El escaneo del código solo ve rutas ancladas a la raíz con literales
(`PROJECT_ROOT / "x"`, `RAIZ / "x"`, `Path(__file__)…parent / "x"`, también si
la raíz se guarda anotada, en una variable local o se importa con alias): no ve
rutas relativas (`Path("x")`), las que vienen de variables de entorno ni las
f-strings.

git corre sin la configuración global ni la del sistema: un excludesFile de
quien corre los tests no puede tapar ni inventar una regla del .gitignore del
repo. Si git no puede responder, el aviso de `exigir_ignorada_por_git` es un
error: un chequeo que no se hizo no pasa.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from comparador.config import Settings
from comparador.rutas import exigir_ignorada_por_git
from tests.test_persistence import repo_git

pytestmark = pytest.mark.filterwarnings("error::UserWarning")

RAIZ = Path(__file__).resolve().parents[1]

# Con "/" al final, carpetas: git tiene que ignorar la carpeta entera.
ALMACENES_PRIVADOS = ("runs/", "feedback/", "mediciones/", "informes_reales/",
                      "checklist_general/", ".env")
EJEMPLOS_PRIVADOS = ("feedback/20261018_x/feedback.json", "feedback/.feedback.lock",
                     "runs/20261018_x/input.pdf", "mediciones/gt/comparador/x.json",
                     "mediciones/fichas_informes.yaml", "mediciones/adjudicacion_checklist/",
                     "informes_reales/x/informe.pdf", "x.npz", "evaluacion_B3.json",
                     ".env.local")
RAICES_VERSIONADAS = {"src", "docs", "frontend"}
# Binarios de informe: solo los fixtures sintéticos de tests/ se versionan.
EXTENSIONES_DE_INFORME = (".pdf", ".docx", ".xlsx", ".xls", ".npz")


@pytest.fixture(autouse=True)
def _git_sin_configuracion_ajena(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def _raiz() -> Path:
    if not (RAIZ / ".git").exists() or shutil.which("git") is None:
        pytest.skip("el proyecto no está en un repositorio git, o no hay git")
    return RAIZ


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(_raiz()), *args], capture_output=True,
                          text=True, check=True).stdout


def _apunta_a_la_raiz(nodo: ast.expr, archivo: Path, nombres: set[str]) -> bool:
    """`nodo` es la raíz del repo: un nombre que la guarda, o `Path(__file__)`
    con tantos `.parent` (o `.parents[n]`) como hagan falta para llegar a ella."""
    if isinstance(nodo, ast.Name):
        return nodo.id in nombres
    subidas = 0
    while True:
        if isinstance(nodo, ast.Attribute) and nodo.attr == "parent":
            subidas, nodo = subidas + 1, nodo.value
        elif (isinstance(nodo, ast.Subscript) and isinstance(nodo.value, ast.Attribute)
              and nodo.value.attr == "parents" and isinstance(nodo.slice, ast.Constant)
              and isinstance(nodo.slice.value, int)):
            subidas, nodo = subidas + nodo.slice.value + 1, nodo.value.value
        elif (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)
              and nodo.func.attr == "resolve"):
            nodo = nodo.func.value
        else:
            break
    es_file = (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
               and nodo.func.id == "Path" and len(nodo.args) == 1
               and isinstance(nodo.args[0], ast.Name) and nodo.args[0].id == "__file__")
    return es_file and subidas > 0 and archivo.parents[subidas - 1] == RAIZ


def _rutas_ancladas(fuentes: dict[Path, str] | None = None) -> list[tuple[str, str]]:
    """(primer componente, archivo:línea) de cada ruta colgada de la raíz del
    repo con un literal, en `src/**/*.py` y `streamlit_app.py` (o en `fuentes`)."""
    if fuentes is None:
        archivos = sorted((RAIZ / "src").rglob("*.py")) + [RAIZ / "streamlit_app.py"]
        fuentes = {a: a.read_text(encoding="utf-8") for a in archivos}
    arboles = {a: ast.parse(texto) for a, texto in fuentes.items()}
    # Los nombres que guardan la raíz (PROJECT_ROOT, RAIZ, también anotados o
    # locales de una función) valen en todo módulo que los importe, con o sin alias.
    nombres: set[str] = set()
    for archivo, arbol in arboles.items():
        for sentencia in ast.walk(arbol):
            if (isinstance(sentencia, ast.Assign | ast.AnnAssign) and sentencia.value
                    and _apunta_a_la_raiz(sentencia.value, archivo, set())):
                destinos = (sentencia.targets if isinstance(sentencia, ast.Assign)
                            else [sentencia.target])
                nombres |= {t.id for t in destinos if isinstance(t, ast.Name)}
    for arbol in arboles.values():
        for sentencia in ast.walk(arbol):
            if isinstance(sentencia, ast.ImportFrom):
                nombres |= {a.asname for a in sentencia.names
                            if a.asname and a.name in nombres}
    rutas = []
    for archivo, arbol in arboles.items():
        for nodo in ast.walk(arbol):
            if (isinstance(nodo, ast.BinOp) and isinstance(nodo.op, ast.Div)
                    and isinstance(nodo.right, ast.Constant)
                    and isinstance(nodo.right.value, str)
                    and _apunta_a_la_raiz(nodo.left, archivo, nombres)):
                donde = f"{archivo.relative_to(RAIZ).as_posix()}:{nodo.lineno}"
                rutas.append((nodo.right.value.split("/")[0], donde))
    return rutas


@pytest.mark.parametrize("ruta", ALMACENES_PRIVADOS + EJEMPLOS_PRIVADOS)
def test_almacen_privado_ignorado(ruta: str) -> None:
    exigir_ignorada_por_git(_raiz() / ruta, ruta, carpeta=ruta.endswith("/"))


def test_ningun_archivo_versionado_en_almacen_privado() -> None:
    versionados = _git("ls-files", "-z").split("\0")
    privados = [f for f in versionados
                if any(f == a or (a.endswith("/") and f.startswith(a))
                       for a in ALMACENES_PRIVADOS)
                or (f.startswith(".env.") and f != ".env.example")]
    assert privados == []
    binarios = [f for f in versionados
                if f.lower().endswith(EXTENSIONES_DE_INFORME) and not f.startswith("tests/")]
    assert binarios == []
    # Ni agregados a la fuerza (`git add -f`) en otro lado.
    assert _git("ls-files", "-ci", "--exclude-standard") == ""
    # La plantilla de claves sí se versiona.
    assert ".env.example" in versionados


def test_reinclusiones_del_gitignore_tienen_efecto() -> None:
    """Cada «!regla» reincluye de verdad: git no reincluye nada dentro de una
    carpeta ignorada, y una regla muerta (`!runs/.gitkeep`) engaña al lector."""
    lineas = (_raiz() / ".gitignore").read_text(encoding="utf-8").splitlines()
    muertas = []
    for regla in (ln[1:] for ln in lineas if ln.startswith("!")):
        ejemplo = regla.replace("**", "x").replace("*", "x")
        r = subprocess.run(["git", "-C", str(RAIZ), "check-ignore", "--no-index", "-q",
                            "--", ejemplo], check=False)
        if r.returncode != 1:
            muertas.append(f"!{regla} ({ejemplo})")
    assert muertas == []


def test_rutas_de_la_raiz_clasificadas() -> None:
    _raiz()
    rutas = _rutas_ancladas()
    privados = {a.rstrip("/") for a in ALMACENES_PRIVADOS}
    assert {"runs", "feedback"} <= {c for c, _ in rutas}   # el escaneo ve config.py
    sin_clasificar = [f"{c} ({d})" for c, d in rutas
                      if c not in privados | RAICES_VERSIONADAS]
    assert sin_clasificar == [], ("ruta nueva colgada de la raíz: agregarla a "
                                  "ALMACENES_PRIVADOS (y al .gitignore) o a RAICES_VERSIONADAS")
    for componente, donde in rutas:
        if componente in privados:
            exigir_ignorada_por_git(RAIZ / componente, donde, carpeta=True)


def test_escaneo_ve_las_formas_de_guardar_la_raiz() -> None:
    """Una raíz anotada (mypy strict), importada con alias o guardada en una
    variable local también cuenta."""
    fuentes = {
        RAIZ / "src/comparador/zz_a.py": (
            "from pathlib import Path\n"
            "RAIZ_ANOTADA: Path = Path(__file__).resolve().parents[2]\n"
            "SALIDA = RAIZ_ANOTADA / 'salidas_a'\n"),
        RAIZ / "src/comparador/zz_b.py": (
            "from comparador.config import PROJECT_ROOT as BASE_REPO\n"
            "SALIDA = BASE_REPO / 'salidas_b'\n"),
        RAIZ / "src/comparador/zz_c.py": (
            "from pathlib import Path\n"
            "def main() -> None:\n"
            "    raiz = Path(__file__).resolve().parents[2]\n"
            "    print(raiz / 'salidas_c')\n"),
        RAIZ / "src/comparador/config.py": (
            "from pathlib import Path\n"
            "PROJECT_ROOT = Path(__file__).resolve().parents[2]\n"),
    }
    assert sorted(c for c, _ in _rutas_ancladas(fuentes)) == [
        "salidas_a", "salidas_b", "salidas_c"]


def test_settings_por_defecto_en_almacen_ignorado() -> None:
    """Los valores por defecto, no `settings`: conftest cambia feedback_dir por
    una carpeta temporal."""
    _raiz()
    for campo in ("runs_dir", "feedback_dir"):
        defecto = Settings.model_fields[campo].default
        assert isinstance(defecto, Path)
        exigir_ignorada_por_git(defecto, campo, carpeta=True)


@pytest.mark.parametrize(("regla", "ruta"), [
    ("runs/", "runs/"), ("feedback/", "feedback/"), ("mediciones/", "mediciones/"),
    ("informes_reales/", "informes_reales/"), ("checklist_general/", "checklist_general/"),
    (".env*", ".env"), (".env*", ".env.local"), ("*.npz", "x.npz"),
    ("evaluacion_*.json", "evaluacion_B3.json"),
])
def test_el_gitignore_real_sin_una_regla_falla(tmp_path: Path, regla: str, ruta: str) -> None:
    """Los chequeos de arriba no pasan por vacío: en un repo temporal, sin las
    carpetas, el .gitignore real ignora la ruta y sin esa regla deja de hacerlo."""
    lineas = (_raiz() / ".gitignore").read_text(encoding="utf-8").splitlines()
    sin_regla = [ln for ln in lineas if ln.strip() != regla]
    assert len(sin_regla) == len(lineas) - 1, f"la regla {regla} no está en el .gitignore"
    (tmp_path / "completo").mkdir()
    (tmp_path / "mutado").mkdir()
    completo = repo_git(tmp_path / "completo", "\n".join(lineas) + "\n")
    mutado = repo_git(tmp_path / "mutado", "\n".join(sin_regla) + "\n")
    exigir_ignorada_por_git(completo / ruta, ruta, carpeta=ruta.endswith("/"))
    with pytest.raises(ValueError, match="git no la ignora"):
        exigir_ignorada_por_git(mutado / ruta, ruta, carpeta=ruta.endswith("/"))
