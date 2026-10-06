# SPDX-License-Identifier: GPL-3.0-or-later
"""La instantánea del guion de comprobación en la GUI (spec 003, T38;
``tools/inblender/gui_check_003.py``).

- RF-003-23, CE-003-02: ``take_snapshot`` se puede guardar en JSON; dos tomas seguidas
  son iguales; con la extensión habilitada recoge la sustitución de ``draw_left``, los
  atajos y las clases, y tras deshabilitarla es igual a la de antes de habilitarla.
- El guion encuentra la extensión instalada (``extension_module``) y se niega a correr sin
  interfaz.

El conmutado real con temporizadores solo corre con interfaz (M2 de ``tasks.md``). Se
ejecuta con ``tools/run_blender_tests.py`` (que pone ``tools/`` en ``sys.path``).
"""

import importlib
import json
import sys
import unittest

from tests.support import blender_ext
from tests.support.blender_ext import module_name

gui_check = importlib.import_module("inblender.gui_check_003")
ui_snapshot = importlib.import_module("gbtools.ui_snapshot")


class GuiCheckSnapshotTest(unittest.TestCase):
    def setUp(self) -> None:
        blender_ext.unload()
        self.addCleanup(blender_ext.unload)

    def test_snapshot_cycle(self) -> None:
        """RF-003-23, CE-003-02: JSON, dos tomas iguales, cambios al habilitar y ninguno
        tras deshabilitar."""
        before = gui_check.take_snapshot()
        self.assertEqual(json.loads(json.dumps(before)), before)
        self.assertEqual(ui_snapshot.compare(before, gui_check.take_snapshot()), [])
        blender_ext.enable()
        self.assertEqual(gui_check.extension_module(), module_name())
        enabled = gui_check.take_snapshot()
        keys = {difference.key.partition("[")[0]
                for difference in ui_snapshot.compare(before, enabled)}
        self.assertLessEqual({"draw_left", "addon_keymaps", "classes"}, keys)
        self.assertEqual(ui_snapshot.compare(enabled, gui_check.take_snapshot()), [])
        blender_ext.disable()
        self.assertEqual([str(d) for d in ui_snapshot.compare(before, gui_check.take_snapshot())],
                         [])

    def test_needs_interface(self) -> None:
        """El guion se niega a correr en segundo plano: el cambio de espacio de trabajo es
        diferido y los temporizadores no corren sin interfaz."""
        argv = sys.argv
        sys.argv = ["blender", "--", "--toggle", "2"]
        try:
            with self.assertRaises(SystemExit):
                gui_check.main()
        finally:
            sys.argv = argv


if __name__ == "__main__":
    unittest.main()
