# SPDX-License-Identifier: GPL-3.0-or-later
"""El guion de la demostración de la procedencia en Blender (spec 008, T39;
``tools/inblender/provenance_demo.py``; plan 008 §7.1).

- RF-008-17, RF-003-06: con la extensión habilitada, el guion registra la demostración sobre
  ella (los tipos ``demo.*`` en los registros de la extensión, no en otra copia de
  Geoblender) y sus operadores ``gbdemo.*`` con su panel, fuera del catálogo de comandos de
  Geoblender; sin proyecto abierto no están disponibles. Al quitarlo no queda nada: ni sus
  clases, ni los tipos, ni el código ``demo`` en la lista de códigos de módulo.

La cadena con un proyecto se comprueba sin Blender (``tests/unit/core/provenance/test_demo.py``)
y a mano en la GUI (M0 a M5 de ``tasks.md``). Se ejecuta con ``tools/run_blender_tests.py``
(que pone ``tools/`` en ``sys.path``).
"""

import importlib
import unittest
from typing import Any

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name

script = importlib.import_module("inblender.provenance_demo")

IDNAMES = (
    "gbdemo.import_boundary",
    "gbdemo.digitize",
    "gbdemo.area",
    "gbdemo.bench_years",
    "gbdemo.stockpiles",
    "gbdemo.balance",
)


def _registries(contract: Any) -> tuple[dict[str, object], ...]:
    views = (contract.OPERATIONS, contract.GROUPS, contract.FIGURES, contract.IMPORTERS)
    return tuple(dict(view) for view in views)


class ProvenanceDemoScriptTest(unittest.TestCase):
    def setUp(self) -> None:
        blender_ext.unload()
        self.addCleanup(blender_ext.unload)
        self.addCleanup(script.unregister)

    def test_registers_gbdemo_operators_outside_the_catalog(self) -> None:
        """RF-008-17, RF-003-06: el guion registra la demostración sobre la extensión
        habilitada y los operadores ``gbdemo.*`` y su panel, que no son del catálogo y sin
        proyecto no están disponibles; quitarlo deja la extensión y Blender como estaban."""
        blender_ext.enable()
        package = module_name()
        self.assertEqual(script.extension_module(), package)
        contract = importlib.import_module(f"{package}.core.provenance.contract")
        catalog = importlib.import_module(f"{package}.core.catalog").load()
        before = _registries(contract)
        types_before = set(dir(bpy.types))

        demo = script.register(package)
        self.assertIs(script.current_demo(), demo)
        self.assertEqual(demo.package, package)
        self.assertIn("demo.area", contract.OPERATIONS)
        self.assertIn("demo.stockpiles", contract.GROUPS)
        self.assertIn("demo", contract.MODULE_CODES)
        for cls in script.CLASSES:
            self.assertTrue(cls.is_registered, cls.__name__)
            self.assertFalse(cls.__name__.startswith("GEOBLENDER_"))
        self.assertEqual(sorted(cls.bl_idname for cls in script.OPERATORS), sorted(IDNAMES))
        for idname in IDNAMES:
            group, name = idname.split(".")
            operator = getattr(getattr(bpy.ops, group), name)
            self.assertEqual(operator.idname_py(), idname)
            self.assertFalse(operator.poll(), idname)  # sin proyecto abierto
            self.assertEqual(catalog.by_idname(idname), ())
        with self.assertRaises(RuntimeError):
            script.register(package)

        script.unregister()
        self.assertIsNone(script.current_demo())
        for cls in script.CLASSES:
            self.assertFalse(cls.is_registered, cls.__name__)
        self.assertEqual(_registries(contract), before)
        self.assertNotIn("demo", contract.MODULE_CODES)
        self.assertEqual(set(dir(bpy.types)), types_before)
        script.unregister()  # sin nada registrado, no hace nada


if __name__ == "__main__":
    unittest.main()
