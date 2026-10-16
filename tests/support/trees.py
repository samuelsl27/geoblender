# SPDX-License-Identifier: GPL-3.0-or-later
"""Árboles de ficheros temporales para las pruebas.

Se crean en la carpeta temporal local (``%TEMP%``), nunca en el repositorio, y se
borran al salir: las pruebas «en rojo» no versionan ficheros que romperían las reglas
sobre el árbol real (plan 001 §6).

Un proceso hijo que lanza una prueba (Blender, el Python de Blender, una orden de
``tools/check.py``) recibe su propia carpeta temporal (:func:`child_temp` y
:func:`child_env`): lo que deje en ella (la copia de un lanzador que sale a mitad, la
carpeta de sesión de Blender) se borra con ella, y la prueba no tiene que buscarlo en el
``%TEMP%`` compartido, donde otra comprobación que se ejecute a la vez tiene las suyas
(convergencia de la spec 001, T61).

La carpeta temporal de una prueba (:func:`temp_folder`) se borra al terminar con
:func:`remove_tree`, también lo de solo lectura: las entradas que un trabajo copia a su
carpeta lo son (``jobs.paths``), y ``shutil.rmtree(..., True)`` no las borra en Windows y no
dice nada (spec 005, T50: miles de carpetas en ``%TEMP%``).
"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
import time
import unittest
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import TypeVar

_Result = TypeVar("_Result")

# Intentos de remove_tree y la espera entre ellos (0,1 s, 0,2 s…): un proceso hijo que acaba
# de terminar puede tardar un poco en soltar sus ficheros.
REMOVE_ATTEMPTS = 4
REMOVE_WAIT_S = 0.1

DAY_S = 86_400.0
# Las variables con que Python (TMPDIR, TEMP, TMP, en ese orden) y Blender (TEMP, TMP)
# eligen la carpeta temporal en Windows.
TEMP_VARIABLES: tuple[str, ...] = ("TMPDIR", "TEMP", "TMP")


@contextmanager
def child_temp(prefix: str = "geoblender-hijo-") -> Iterator[Path]:
    """Carpeta temporal propia de un proceso hijo, nueva y dentro del ``%TEMP%`` de este
    proceso; al salir se borra entera, con lo que el hijo dejara en ella, y nada más."""
    with tempfile.TemporaryDirectory(prefix=prefix, ignore_cleanup_errors=True) as tmp:
        yield Path(tmp)


def child_env(env: Mapping[str, str] | None, temp: Path) -> dict[str, str]:
    """Copia de ``env`` (por defecto, el entorno de este proceso) con ``TMPDIR``,
    ``TEMP`` y ``TMP`` en ``temp`` (:func:`child_temp`)."""
    result = dict(os.environ if env is None else env)
    result.update(dict.fromkeys(TEMP_VARIABLES, str(temp)))
    return result


def child_runner(temp: Path, run: Callable[..., _Result]) -> Callable[..., _Result]:
    """El ejecutor de órdenes ``run`` (``gbtools.blender.run`` o uno con su firma) con el
    entorno de cada orden pasado por :func:`child_env`: cada hijo, con su carpeta
    temporal en ``temp``."""

    def runner(
        cmd: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> _Result:
        return run(cmd, env=child_env(env, temp), cwd=cwd, timeout=timeout)

    return runner


def _writable_and_again(function: Callable[[str], object], path: str,
                        error: BaseException) -> None:
    """Para ``shutil.rmtree``: lo de solo lectura, con permiso de escritura y otra vez;
    cualquier otro fallo (un fichero abierto) se propaga."""
    if not isinstance(error, PermissionError):
        raise error
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    function(path)


def remove_tree(folder: Path, *, attempts: int = REMOVE_ATTEMPTS) -> None:
    """Borra ``folder`` entera, también lo de solo lectura; si no existe, nada. Si algo no se
    puede borrar (un fichero abierto), lo intenta ``attempts`` veces y lanza el error: nada
    se queda en ``%TEMP%`` en silencio (spec 005, T50)."""
    for attempt in range(attempts):
        try:
            shutil.rmtree(folder, onexc=_writable_and_again)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(REMOVE_WAIT_S * (attempt + 1))


def temp_folder(case: unittest.TestCase, prefix: str) -> Path:
    """Carpeta temporal nueva de la prueba ``case``, de ruta corta (``prefix`` y unas letras,
    en el ``%TEMP%`` de este proceso), que se borra al terminar con :func:`remove_tree`."""
    folder = Path(tempfile.mkdtemp(prefix=prefix))
    case.addCleanup(remove_tree, folder)
    return folder


@contextmanager
def temp_tree(files: Mapping[str, str | bytes]) -> Iterator[Path]:
    """Crea los ficheros indicados en una carpeta temporal y la borra al terminar.

    Las claves son rutas relativas con «/»; una clave que termina en «/» crea una
    carpeta vacía. El texto se escribe en UTF-8 tal cual, sin traducir los finales de
    línea; los bytes, sin cambios.
    """
    with tempfile.TemporaryDirectory(prefix="geoblender-arbol-") as tmp:
        root = Path(tmp)
        for rel, content in files.items():
            target = root / rel
            if rel.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            data = content.encode("utf-8") if isinstance(content, str) else content
            target.write_bytes(data)
        yield root


def age_folders(root: Path, seconds: float = DAY_S) -> None:
    """Retrasa ``seconds`` la fecha de modificación de ``root`` y de todas sus
    carpetas. Así, crear o borrar algo en una de ellas le pone una fecha distinta,
    aunque el reloj del sistema de ficheros avance a saltos de varios ms (la foto del
    repositorio compara la fecha de cada carpeta: convergencia de la spec 001, T51)."""
    past = time.time() - seconds
    folders = [Path(current) for current, _dirs, _files in os.walk(root)]
    for folder in reversed(folders):  # las de dentro primero: no tocan la de fuera
        os.utime(folder, (past, past))
