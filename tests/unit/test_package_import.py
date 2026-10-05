# SPDX-License-Identifier: GPL-3.0-or-later
"""La extensión se importa sin Blender (RF-001-03; plan 001 §5.4.6).

Se carga ``geoblender/`` por ruta como paquete ``geoblender`` y se importan el paquete
raíz y todos sus paquetes salvo ``bl``: ningún módulo de Blender debe acabar en
``sys.modules`` y ``geoblender.bl`` no debe importarse.
"""

import sys
import unittest

from tests.support.package import PACKAGE_NAME, import_geoblender, load_geoblender
from tests.support.repo import EXTENSION_DIR, tools_on_path

tools_on_path()

from gbtools.rules.imports import is_blender_module  # noqa: E402

# Paquetes de ADR-0004 que se importan sin Blender (spec 001, RF-001-03).
DOMAIN_PACKAGES = (
    "core",
    "jobs",
    "gis",
    "drillholes",
    "geomodel",
    "implicit",
    "blockmodel",
    "pitopt",
    "design",
    "reserves",
    "interop",
    "plans",
)
PURE_PACKAGES = (*DOMAIN_PACKAGES, "adapters", "workers")
BL_SUBPACKAGES = ("props", "scene", "draw", "gn", "ops", "ui")


def _blender_modules_loaded() -> list[str]:
    """Módulos de Blender (lista y prefijos de ARQ-01) presentes en ``sys.modules``."""
    return sorted(name for name in sys.modules if is_blender_module(name))


def _unload() -> None:
    for name in [n for n in sys.modules if n.partition(".")[0] == PACKAGE_NAME]:
        del sys.modules[name]


class PackageImportTest(unittest.TestCase):
    def setUp(self) -> None:
        _unload()
        self.addCleanup(_unload)

    def test_root_imports_without_blender(self) -> None:
        """RF-001-03: el paquete raíz se importa sin Blender y no carga ``bl``."""
        root = load_geoblender()
        self.assertEqual(root.__name__, PACKAGE_NAME)
        self.assertTrue(callable(root.register))
        self.assertTrue(callable(root.unregister))
        self.assertEqual(_blender_modules_loaded(), [])
        self.assertNotIn(f"{PACKAGE_NAME}.bl", sys.modules)
        self.assertIs(load_geoblender(), root, "cargarlo otra vez no lo reejecuta")

    def test_packages_import_without_blender(self) -> None:
        """RF-001-03: paquetes de dominio, ``adapters`` y ``workers``, sin Blender."""
        for name in PURE_PACKAGES:
            with self.subTest(paquete=name):
                module = import_geoblender(name)
                self.assertEqual(module.__name__, f"{PACKAGE_NAME}.{name}")
                self.assertTrue(module.__doc__, "cada paquete explica su papel")
        self.assertEqual(_blender_modules_loaded(), [])
        self.assertNotIn(f"{PACKAGE_NAME}.bl", sys.modules)

    def test_bl_is_never_imported_by_the_helper(self) -> None:
        """RF-001-03: el ayudante se niega a importar ``bl`` fuera de Blender."""
        for name in ("bl", "bl.ui", "bl.compat"):
            with self.subTest(paquete=name), self.assertRaises(ValueError):
                import_geoblender(name)
        self.assertNotIn(f"{PACKAGE_NAME}.bl", sys.modules)

    def test_bl_tree_exists(self) -> None:
        """RF-001-03: existen los paquetes de ADR-0004 y el árbol de ``bl``."""
        self.assertTrue((EXTENSION_DIR / "__init__.py").is_file())
        for name in (*PURE_PACKAGES, "bl", *(f"bl/{sub}" for sub in BL_SUBPACKAGES)):
            with self.subTest(paquete=name):
                self.assertTrue((EXTENSION_DIR / name / "__init__.py").is_file())
        self.assertTrue((EXTENSION_DIR / "bl" / "compat.py").is_file())


if __name__ == "__main__":
    unittest.main()
