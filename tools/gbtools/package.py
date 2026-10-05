# SPDX-License-Identifier: GPL-3.0-or-later
"""Carga del código de Geoblender por ruta, sin Blender (plan 001 §5.4.6).

``load_geoblender`` crea el paquete ``geoblender`` a partir de ``<raíz>/geoblender/``
con ``importlib``: los imports relativos funcionan, el nombre no depende de la carpeta
y coincide con el final de ``bl_ext.<repo>.geoblender``. No importa ``bpy``: el
``__init__.py`` raíz solo importa ``bl`` dentro de ``register()`` (ARQ-02, ARQ-03).

Lo usan ``tests/support/package.py`` y las herramientas que reutilizan código del
producto (HER-01 solo admite ``geoblender`` cargado así, nunca ``geoblender.bl``).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from .layout import EXTENSION_DIR

EXTENSION_FOLDER = EXTENSION_DIR


def load_geoblender(root: Path, name: str = "geoblender") -> ModuleType:
    """Carga ``<root>/geoblender/`` como el paquete ``name`` y lo devuelve.

    Si ya está cargado desde esa misma carpeta, devuelve el módulo existente sin volver
    a ejecutarlo. Lanza ``ImportError`` si ``name`` ya corresponde a otra carpeta o si
    no existe ``<root>/geoblender/__init__.py``.
    """
    package_dir = Path(root) / EXTENSION_FOLDER
    init = package_dir / "__init__.py"
    existing = sys.modules.get(name)
    if existing is not None:
        loaded_from = getattr(existing, "__file__", None)
        if loaded_from and Path(loaded_from).resolve() == init.resolve():
            return existing
        raise ImportError(
            f"Ya hay un módulo «{name}» cargado desde «{loaded_from}»; no se puede "
            f"cargar también «{init}» con ese nombre"
        )
    if not init.is_file():
        raise ImportError(
            f"No existe «{init}»: la raíz del repositorio debe contener la extensión "
            f"en «{EXTENSION_FOLDER}/»"
        )
    spec = importlib.util.spec_from_file_location(
        name, init, submodule_search_locations=[str(package_dir)]
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"No se puede cargar «{init}» como paquete «{name}»")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module
