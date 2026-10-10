# SPDX-License-Identifier: GPL-3.0-or-later
"""La copia de pruebas de la extensión que se registra en Blender (spec 001, RF-001-09;
spec 006, T48).

``tools/run_blender_tests.py`` no prueba la extensión del repositorio sino una copia en
una carpeta temporal: con las exclusiones del manifiesto, sin ``wheels/`` y con
``wheels = []`` en el manifiesto de la copia (con ruedas, Blender instala y quita pyproj en
cada habilitar y deshabilitar; spec 006, T11). :func:`make_copy` la hace.

Cada parte de «blender» de ``tools/check.py`` hacía su copia y, al habilitar la extensión
por primera vez, abría cada fichero recién copiado (y el antivirus lo examinaba: unos
0,7 s) y lo compilaba (unos 0,5 s): ≈ 1,5 s por parte en reposo, más con el equipo cargado
(RNF-001-01). :func:`prepare` hace una sola copia, compila sus fuentes en ``pyc/`` con la
disposición de ``sys.pycache_prefix`` (:func:`bytecode_path`) y lee una vez cada fichero;
``check.py`` la prepara mientras corren las unitarias y la pasa a todas las partes
(``run_blender_tests.py --copia``), que la usan tal cual y no la borran.

Solo biblioteca estándar (HER-01).
"""

from __future__ import annotations

import os
import py_compile
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import layout, manifest, sync

EXTENSION_FOLDER = layout.EXTENSION_DIR  # la copia: <destino>/geoblender
BYTECODE_FOLDER = "pyc"  # su código compilado: <destino>/pyc (sys.pycache_prefix)
# La copia de pruebas va sin las ruedas de la extensión (ver el docstring del módulo).
NO_WHEELS_PATTERN = "/wheels/"
READ_CHUNK = 1 << 20


def read_manifest(root: Path) -> dict[str, Any]:
    """El manifiesto de la extensión de ``root`` (con BOM se lee igual: el BOM lo señalan
    TXT-01, MAN-01 y el paso «manifiesto»; convergencia de la spec 001, T56)."""
    text = (Path(root) / layout.MANIFEST_RELPATH).read_bytes().decode("utf-8-sig")
    return tomllib.loads(text)


def make_copy(
    root: Path, target: Path, manifest_data: Mapping[str, Any] | None = None
) -> Path:
    """Deja en ``<target>/geoblender`` la copia de pruebas de la extensión de ``root``
    (con las exclusiones de ``manifest_data``, el manifiesto de ``root`` si no se da, sin
    ``wheels/`` y con ``wheels = []``) y devuelve esa carpeta. Sobre una copia anterior,
    solo copia lo que cambió y quita lo que sobra (``gbtools.sync.mirror``)."""
    data = read_manifest(root) if manifest_data is None else manifest_data
    copy = Path(target) / EXTENSION_FOLDER
    sync.mirror(
        Path(root) / layout.EXTENSION_DIR,
        copy,
        [*manifest.exclude_patterns(data), NO_WHEELS_PATTERN],
    )
    manifest.rewrite_wheels(copy / Path(layout.MANIFEST_RELPATH).name, [])
    return copy


def bytecode_path(prefix: Path, source: Path) -> Path:
    """Dónde busca Python el código compilado de ``source`` con ``sys.pycache_prefix`` =
    ``prefix``: el prefijo, la carpeta absoluta de la fuente sin la unidad y
    ``<nombre>.<etiqueta del intérprete>.pyc`` (lo mismo que
    ``importlib.util.cache_from_source``, sin cambiar ``sys.pycache_prefix`` del
    proceso)."""
    folder = os.path.abspath(os.path.dirname(source))
    if folder[1:2] == ":" and folder[:1] not in "\\/":  # como importlib: sin «C:»
        folder = folder[2:]
    name = Path(source).stem
    tag = sys.implementation.cache_tag
    return Path(prefix, folder.lstrip("\\/"), f"{name}.{tag}.pyc")


def compile_copy(copy: Path, prefix: Path) -> int:
    """Compila cada ``.py`` de ``copy`` en ``prefix`` (:func:`bytecode_path`), validado
    por la fecha y el tamaño de la fuente, como lo escribe Python; devuelve cuántos. Una
    fuente que no compila lanza su ``SyntaxError``."""
    count = 0
    for source in sorted(Path(copy).rglob("*.py")):
        try:
            py_compile.compile(
                str(source),
                cfile=str(bytecode_path(prefix, source)),
                doraise=True,
                invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP,
            )
        except py_compile.PyCompileError as exc:
            raise exc.exc_value from None
        count += 1
    return count


def warm(folder: Path) -> int:
    """Lee una vez cada fichero de ``folder`` (el antivirus examina un fichero nuevo la
    primera vez que se abre: así no lo hace cada parte al habilitar); devuelve cuántos."""
    count = 0
    for path in Path(folder).rglob("*"):
        if path.is_file():
            with open(path, "rb") as stream:
                while stream.read(READ_CHUNK):
                    pass
            count += 1
    return count


def prepare(root: Path, target: Path) -> Path:
    """La copia de pruebas compartida en ``target``: la copia (:func:`make_copy`), su
    código compilado en ``<target>/pyc`` (:func:`compile_copy`) y cada fichero leído una
    vez (:func:`warm`); devuelve ``target``."""
    target = Path(target)
    copy = make_copy(root, target)
    compile_copy(copy, target / BYTECODE_FOLDER)
    warm(target)
    return target
