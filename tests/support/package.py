# SPDX-License-Identifier: GPL-3.0-or-later
"""El paquete ``geoblender`` para las pruebas sin Blender (plan 001 §5.3 y §5.4.6).

Carga ``geoblender/`` por ruta con ``gbtools.package.load_geoblender``. ``bl`` nunca se
importa desde aquí: es la capa de presentación y solo existe dentro de Blender.
"""

from __future__ import annotations

import importlib
from types import ModuleType

from tests.support.repo import ROOT, tools_on_path

PACKAGE_NAME = "geoblender"


def load_geoblender() -> ModuleType:
    """Carga (una sola vez) ``geoblender/`` como el paquete ``geoblender``."""
    tools_on_path()
    from gbtools.package import load_geoblender as _load

    return _load(ROOT, PACKAGE_NAME)


def import_geoblender(subpackage: str) -> ModuleType:
    """Importa ``geoblender.<subpackage>`` (p. ej. ``"core"``); nunca ``bl``."""
    if subpackage.partition(".")[0] == "bl":
        raise ValueError(
            f"«{subpackage}» es la capa de presentación: solo se importa dentro de "
            "Blender (tests/blender/), nunca en las pruebas sin Blender"
        )
    load_geoblender()
    return importlib.import_module(f"{PACKAGE_NAME}.{subpackage}")
