# SPDX-License-Identifier: GPL-3.0-or-later
"""La orden que abre «Importar un fichero…» con cada extensión, leída del código sin ``bpy``
(spec 006, T32; spec 005, T59): para comparar la documentación con el código.

``bl/ops/io.py`` solo se importa dentro de Blender: aquí se lee su árbol sintáctico
(``IMPORTERS``, ``EXTENSIONS`` y ``LATER``) y el de ``bl/ops/gis.py`` (el ``bl_idname`` de
cada importador de la topografía). De una extensión que traen otras entradas (``LATER``),
«Importar un fichero…» abre la primera orden cuya entrada del catálogo de comandos de la 003 ya
está entregada, como ``bl.ops.io.importer_for``; si ninguna lo está, no la importa. La de
:data:`BY_CONTENT` la decide su contenido.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR

IO_OPS = EXTENSION_DIR / "bl" / "ops" / "io.py"
GIS_OPS = EXTENSION_DIR / "bl" / "ops" / "gis.py"
BY_CONTENT = ".xyz"
"""La extensión cuyo contenido decide el importador (``bl.ops.io.importer_for``): el de MDT
si sus primeras líneas forman una malla regular y, si no, el de puntos."""


def _assignments(path: Path) -> dict[str, ast.expr]:
    """El valor (su árbol) de cada asignación de nivel de módulo de ``path``, por su nombre."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found[target.id] = node.value
        elif (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
              and node.value is not None):
            found[node.target.id] = node.value
    return found


def _delivered(catalog: Any, key: str) -> bool:
    """Si la entrada del catálogo que trae la orden ``key`` ya la entrega."""
    command = catalog.commands.get(key)
    entry = None if command is None else catalog.entries.get(command.entry)
    return bool(entry is not None and entry.delivered)


def import_routes() -> dict[str, tuple[str, ...]]:
    """La orden (``bl_idname``) que abre «Importar un fichero…» con cada extensión que importa
    (en minúsculas y con su punto): una o, la de :data:`BY_CONTENT`, las dos entre las que
    decide su contenido (el MDT y los puntos). ``ValueError`` si ``bl/ops/io.py`` ya no tiene
    la forma que se lee aquí."""
    io_names = _assignments(IO_OPS)
    commands = {name: value.value for name, value in _assignments(GIS_OPS).items()
                if name.startswith("IMPORT_") and isinstance(value, ast.Constant)}
    importers, later = io_names.get("IMPORTERS"), io_names.get("LATER")
    extensions = ast.literal_eval(io_names["EXTENSIONS"]) if "EXTENSIONS" in io_names else ()
    if not (isinstance(importers, ast.Dict) and isinstance(later, ast.Dict)):
        raise ValueError("bl/ops/io.py ya no define IMPORTERS y LATER como diccionarios")
    routes: dict[str, tuple[str, ...]] = {}
    for key, value in zip(importers.keys, importers.values, strict=True):
        if not (isinstance(key, ast.Constant) and isinstance(value, ast.Name)
                and value.id in commands):
            raise ValueError(f"IMPORTERS de bl/ops/io.py: {ast.unparse(value)} no es un "
                             f"importador de bl/ops/gis.py")
        routes[key.value] = (commands[value.id],)
    if BY_CONTENT not in extensions or BY_CONTENT in routes:
        raise ValueError(f"bl/ops/io.py ya no decide «{BY_CONTENT}» por su contenido")
    routes[BY_CONTENT] = (commands["IMPORT_DTM"], commands["IMPORT_POINTS"])
    catalog = import_geoblender("core.catalog").load()
    for key, value in zip(later.keys, later.values, strict=True):
        ready = [key_ for key_ in ast.literal_eval(value) if _delivered(catalog, key_)]
        if ready:
            routes[ast.literal_eval(key)] = (ready[0],)
    return routes


def label_es(idname: str) -> str:
    """La etiqueta en español de la orden ``idname`` en el catálogo de comandos («Sondeos…»)."""
    return import_geoblender("core.catalog").load().commands[idname].label_es
