# SPDX-License-Identifier: GPL-3.0-or-later
"""El código compilado de las órdenes de Python de ``tools/check.py``, fuera del repositorio
(spec 005, T44; RNF-001-01, RF-001-09).

Las órdenes de Python de la comprobación («unitarias», «referencia», «motor», «licencias»…)
van con ``-B``: ningún ``__pycache__`` en el repositorio (plan 001 §5.3). Así, cada proceso
compilaba en memoria todo lo que importaba (la extensión, las pruebas y las herramientas, y
los módulos de la biblioteca de Python que Blender no trae compilados): ≈ 0,5 s por proceso
en reposo, más con el equipo cargado, y una comprobación lanza unos 40. :func:`refresh` deja
ese código compilado en una carpeta de la temporal del sistema, una por raíz
(:func:`default_folder`), con la disposición de ``sys.pycache_prefix``
(``ext_copy.bytecode_path``); ``check.py`` la refresca al empezar, en otro hilo
(:func:`prepare`), y la pasa a sus órdenes de Python en ``PYTHONPYCACHEPREFIX``
(:data:`ENV_PREFIX`), que la leen sin escribir nada (``-B``). Con esa variable, Python busca
ahí todo lo compilado, también lo de la biblioteca estándar (no lo que hay junto a sus
fuentes): por eso se compila entera, sin ``site-packages``, y de ``site-packages`` lo que
Blender trae compilado (:func:`trees`).

- Lo del repositorio (la extensión, ``tests/`` y ``tools/``) se valida por el hash de su
  fuente (``CHECKED_HASH``, PEP 552): al importarlo, Python compara el hash de la fuente y,
  si cambió (aunque conserve la fecha y el tamaño), la compila otra vez en memoria. Lo demás
  (el intérprete y las carpetas de paquetes, que no se editan), por la fecha y el tamaño de
  la fuente, como lo escribe Python.
- Solo se compila lo que falta o ya no vale; lo compilado de una fuente del repositorio que
  ya no existe se borra. Una fuente que no compila se anota y no para nada (al importarla,
  Python dará su error, como sin la carpeta).
- Si la carpeta falta, está a medias o no se pudo refrescar, lo que se ejecuta es lo mismo:
  Python compila en memoria lo que no encuentra o no vale. Cada ``.pyc`` se escribe entero o
  no se escribe (``py_compile``).
- :func:`prepare` anota en la carpeta su raíz (:data:`ROOT_FILE`) y borra las carpetas de las
  raíces que ya no existen (un *worktree* borrado): la temporal del sistema no crece sin fin.

Solo biblioteca estándar (HER-01).
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import py_compile
import shutil
import sys
import sysconfig
import tempfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import layout
from .blender import DEPS_SITE_RELPATH
from .ext_copy import bytecode_path

STORE_FOLDER = "geoblender-pyc"  # en la carpeta temporal del sistema: una carpeta por raíz
ENV_PREFIX = "PYTHONPYCACHEPREFIX"  # la variable con que la reciben las órdenes
ROOT_FILE = "raiz.txt"  # la raíz de una carpeta (para borrarla cuando ya no exista)
SITE_PACKAGES = "site-packages"
CACHE_DIR = "__pycache__"
REPO_FOLDERS: tuple[str, ...] = (layout.EXTENSION_DIR, "tests", "tools")
_CHECKED_HASH = 0b11  # banderas de un .pyc validado por el hash de su fuente (PEP 552)
_HEADER_BYTES = 16


@dataclass(frozen=True)
class Tree:
    """Una carpeta de fuentes que se compila: ``checked``, validada por el hash de cada
    fuente (si no, por su fecha y tamaño); ``precompiled_only``, solo las fuentes que ya
    tienen su ``.pyc`` en el ``__pycache__`` de su carpeta; ``skip``, subcarpetas (por su
    nombre) que no se recorren."""

    folder: Path
    checked: bool = False
    precompiled_only: bool = False
    skip: tuple[str, ...] = ()


@dataclass
class Refresh:
    """Lo que hizo :func:`refresh`: fuentes compiladas, las que ya estaban al día, ``.pyc``
    borrados (su fuente ya no existe) y las fuentes que no compilan."""

    compiled: int = 0
    fresh: int = 0
    removed: int = 0
    failed: list[str] = field(default_factory=list)


def default_folder(root: Path) -> Path:
    """La carpeta del código compilado de la raíz ``root``: en la carpeta temporal del
    sistema, fuera del repositorio (RF-001-09), y una por raíz (cada clon o *worktree*
    tiene sus fuentes), como el almacén de tiempos de ``check.py``."""
    name = os.path.normcase(os.path.abspath(root))
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / STORE_FOLDER / digest


def trees(root: Path, sites: Sequence[Path] = (), *, interpreter: bool = True) -> list[Tree]:
    """Lo que se compila para la raíz ``root``: la extensión, ``tests/`` y ``tools/``
    (por el hash de su fuente); con ``interpreter``, la biblioteca de Python del intérprete
    en uso (el de Blender), sin ``site-packages``, y de ``site-packages`` lo que trae
    compilado; ``.deps/site`` si existe, y las carpetas de paquetes ``sites`` (la del motor de
    cálculo de pruebas)."""
    root = Path(root)
    found = [Tree(root / name, checked=True) for name in REPO_FOLDERS]
    if interpreter:
        found += [
            Tree(Path(sysconfig.get_path("stdlib")), skip=(SITE_PACKAGES,)),
            Tree(Path(sysconfig.get_path("purelib")), precompiled_only=True),
        ]
    deps = root / DEPS_SITE_RELPATH
    if deps.is_dir():
        found.append(Tree(deps))
    found += [Tree(Path(site)) for site in sites]
    return found


def _sources(tree: Tree) -> Iterator[Path]:
    """Las fuentes ``.py`` de ``tree`` que se compilan."""
    tag = sys.implementation.cache_tag
    for folder, dirs, files in os.walk(tree.folder):
        dirs[:] = sorted(d for d in dirs if d != CACHE_DIR and d not in tree.skip)
        cached: set[str] | None = None
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            if tree.precompiled_only:
                if cached is None:
                    cache = os.path.join(folder, CACHE_DIR)
                    cached = set(os.listdir(cache)) if os.path.isdir(cache) else set()
                if f"{name[:-3]}.{tag}.pyc" not in cached:
                    continue
            yield Path(folder, name)


def _fresh(source: Path, compiled: Path, checked: bool) -> bool:
    """Si el ``.pyc`` ``compiled`` vale para ``source``: el número mágico del intérprete y
    el hash de la fuente (``checked``) o su fecha y tamaño, como lo comprueba Python."""
    try:
        with open(compiled, "rb") as stream:
            header = stream.read(_HEADER_BYTES)
    except OSError:
        return False
    if len(header) < _HEADER_BYTES or header[:4] != importlib.util.MAGIC_NUMBER:
        return False
    flags = int.from_bytes(header[4:8], "little")
    if checked:
        return (flags == _CHECKED_HASH
                and header[8:16] == importlib.util.source_hash(source.read_bytes()))
    stat = source.stat()
    validated = ((int(stat.st_mtime) & 0xFFFFFFFF).to_bytes(4, "little")
                 + (stat.st_size & 0xFFFFFFFF).to_bytes(4, "little"))
    return flags == 0 and header[8:16] == validated


def _prune(prefix: Path, tree: Tree) -> int:
    """Borra lo compilado de las fuentes de ``tree`` que ya no existen; devuelve cuántos."""
    mirror = bytecode_path(prefix, tree.folder / "x.py").parent
    if not mirror.is_dir():
        return 0
    suffix = f".{sys.implementation.cache_tag}.pyc"
    removed = 0
    for folder, _dirs, files in os.walk(mirror):
        relative = Path(folder).relative_to(mirror)
        for name in files:
            if name.endswith(suffix):
                source = tree.folder / relative / f"{name[:-len(suffix)]}.py"
                if not source.is_file():
                    os.remove(os.path.join(folder, name))
                    removed += 1
    return removed


def refresh(prefix: Path, trees: Sequence[Tree]) -> Refresh:
    """Compila en ``prefix`` (con la disposición de ``PYTHONPYCACHEPREFIX``) cada fuente de
    ``trees`` que no tiene ahí su ``.pyc`` o cuyo ``.pyc`` ya no vale, y borra lo de las
    fuentes de un árbol ``checked`` que ya no existen. Una fuente que no compila se anota
    (``failed``); un error al escribir (``OSError``) sale tal cual."""
    found = Refresh()
    prefix = Path(prefix)
    for tree in trees:
        if not tree.folder.is_dir():
            continue
        mode = (py_compile.PycInvalidationMode.CHECKED_HASH if tree.checked
                else py_compile.PycInvalidationMode.TIMESTAMP)
        for source in _sources(tree):
            compiled = bytecode_path(prefix, source)
            try:
                if _fresh(source, compiled, tree.checked):
                    found.fresh += 1
                    continue
                py_compile.compile(str(source), cfile=str(compiled), doraise=True,
                                   invalidation_mode=mode)
            except FileNotFoundError:  # la fuente ya no está (se borró mientras tanto)
                continue
            except py_compile.PyCompileError:
                found.failed.append(str(source))
                continue
            found.compiled += 1
        if tree.checked:
            found.removed += _prune(prefix, tree)
    return found


def prune_roots(store: Path) -> list[Path]:
    """Borra las carpetas de ``store`` cuya raíz (:data:`ROOT_FILE`) ya no existe; las que
    no la dicen se dejan. Devuelve las borradas."""
    removed: list[Path] = []
    if not Path(store).is_dir():
        return removed
    for folder in sorted(Path(store).iterdir()):
        try:
            root = (folder / ROOT_FILE).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if root and not Path(root).is_dir():
            shutil.rmtree(folder, ignore_errors=True)
            removed.append(folder)
    return removed


def prepare(
    folder: Path, root: Path, sites: Sequence[Path] = (), *, interpreter: bool = True
) -> Refresh:
    """La carpeta del código compilado de ``root`` al día: anota su raíz, la refresca con
    :func:`trees` (``sites``: la carpeta del motor de cálculo de pruebas) y borra las de las
    raíces que ya no existen; devuelve lo que hizo :func:`refresh`."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ROOT_FILE).write_text(str(root), encoding="utf-8")
    found = refresh(folder, trees(root, sites, interpreter=interpreter))
    prune_roots(folder.parent)
    return found
