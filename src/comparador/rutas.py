"""Comparación de rutas por identidad de archivo y guarda de las salidas
privadas frente a git (sin dependencias internas: la usan la configuración, la
persistencia y las herramientas)."""

from __future__ import annotations

import os
import subprocess
import warnings
from pathlib import Path


def ruta_dentro_de(ruta: Path, carpeta: Path) -> bool:
    """`ruta` es `carpeta` o está dentro, comparando archivos y no texto: el
    disco de macOS (y el de Windows) no distingue mayúsculas — runs/ y Runs/
    son la misma carpeta — y una ruta puede pasar por un enlace simbólico. Si
    `carpeta` todavía no existe, se compara desde su ancestro existente más
    cercano (lo que falta, sin distinguir mayúsculas: ante la duda, dentro)."""
    ruta, carpeta = ruta.resolve(), carpeta.resolve()
    if ruta.is_relative_to(carpeta):
        return True
    base, faltan = carpeta, list[str]()
    while not base.exists() and base != base.parent:
        faltan.insert(0, base.name.casefold())
        base = base.parent
    for ancestro in (ruta, *ruta.parents):
        if ancestro.exists() and os.path.samefile(ancestro, base):
            partes = [p.casefold() for p in ruta.relative_to(ancestro).parts]
            return partes[:len(faltan)] == faltan
    return False


def exigir_ignorada_por_git(ruta: Path, opcion: str, *, carpeta: bool = False) -> None:
    """Una salida con texto de informes reales (repetición de E4, vectores, GT
    del comparador) no puede quedar en un repositorio git sin que git la ignore:
    un `git add -A` la subiría. Fuera de todo repositorio no hay nada que
    comprobar (el repositorio se busca por su `.git`, sin git). Con `carpeta`,
    la ignorada tiene que ser la carpeta entera: un `*.npz` no cubre el
    reporte_final.json de al lado. Si git no está instalado o falla, avisa y
    sigue: sin git tampoco hay `git add`. `opcion` nombra la ruta en el mensaje."""
    absoluta = ruta.resolve()
    raiz = next((d for d in (absoluta, *absoluta.parents) if (d / ".git").exists()), None)
    if raiz is None:
        return
    no_ignorada = (f"{opcion} ({ruta}) queda dentro del repositorio {raiz} y git no la "
                   "ignora: es una salida de informes reales y un `git add` la subiría. "
                   "Usar una carpeta que git ignore (p. ej. bajo mediciones/).")
    if absoluta == raiz:
        raise ValueError(no_ignorada)
    relativa = absoluta.relative_to(raiz).as_posix() + ("/" if carpeta else "")
    try:
        r = subprocess.run(["git", "-C", str(raiz), "check-ignore", "-q", "--", relativa],
                           capture_output=True, text=True, check=False)
    except OSError as exc:
        motivo = str(exc)
    else:
        if r.returncode == 0:
            return
        if r.returncode == 1:
            raise ValueError(no_ignorada)
        motivo = r.stderr.strip() or f"código {r.returncode}"
    warnings.warn(f"No se pudo comprobar con git que {opcion} ({ruta}) quede fuera del "
                  f"control de versiones ({motivo}): es una salida de informes reales, "
                  "revisarla antes de un `git add`.", stacklevel=2)
