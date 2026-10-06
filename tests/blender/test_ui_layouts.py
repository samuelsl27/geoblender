# SPDX-License-Identifier: GPL-3.0-or-later
"""Disposiciones de Geoblender (spec 003, T25; RF-003-16; CW §6.2 y §6.4; BS §8.12,
Disposición ▸).

- RF-003-16: elegir una disposición que el fichero no tiene la añade desde los recursos
  (``resources/geoblender_ui.blend``, sin dejar la biblioteca en el fichero) y la deja
  pendiente de activar en la ventana (la asignación es diferida: se aplica en la GUI,
  M14); elegirla otra vez no la añade de nuevo.
- RF-003-16: «Quitar esta disposición» borra solo ese espacio de trabajo, nunca datos
  (``bpy.data.objects`` igual), y no quita la principal ni un espacio de Blender; si una
  ventana la está usando, la ventana pasa antes a la principal y se borra cuando el cambio
  se ha aplicado.
- RF-003-16: «Restaurar la disposición» la vuelve a anexar con su reparto original y con
  el mismo nombre, sin dejar copias ni la biblioteca.
- RF-003-07, RF-003-16 (CW §6.2): las disposiciones de R-62 y R-57 se ven desactivadas en
  Herramientas ▸ Disposición ▸ y en la ventana Disposición ▾, y elegirlas informa
  «Disponible en …» sin cambiar nada.
- CW §6.4: la ventana Disposición ▾ lista las disposiciones del fichero (la activa,
  hundida), las que faltan, Quitar, Restaurar, la fila de acceso rápido y la barra de
  estado minera.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import draw

ADD = "geoblender.ui_add_layout"
REMOVE = "geoblender.ui_remove_layout"
RESTORE = "geoblender.ui_restore_layout"
DATA = "Geoblender · Datos"
SECTION_PLAN = "Geoblender · Sección y planta"
LATER = {"VERSION_REVIEW": "R-62", "DRAWINGS": "R-57"}


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def area_types(workspace: bpy.types.WorkSpace) -> list[str]:
    return sorted(area.type for area in workspace.screens[0].areas)


class LayoutsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.load_file()
        blender_ext.enable()
        cls.layouts = _module("bl.ui.layouts")
        cls.switcher = _module("bl.ui.switcher")
        cls.main = cls.switcher.main_workspace()

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.unload()

    def setUp(self) -> None:
        blender_ext.load_file()
        self.window = bpy.context.window_manager.windows[0]
        self.objects = sorted(obj.name for obj in bpy.data.objects)

    def add(self, layout_id: str) -> set[str]:
        with bpy.context.temp_override(window=self.window):
            return bpy.ops.geoblender.ui_add_layout(layout=layout_id)

    @contextmanager
    def this_window(self, name: str) -> Iterator[None]:
        """La ventana con el espacio ``name`` («esta disposición»): en segundo plano la
        asignación diferida no se aplica, así que se simula el espacio de la ventana."""
        workspace = bpy.data.workspaces[name]
        with (mock.patch.object(self.layouts, "context_workspace", return_value=workspace),
              bpy.context.temp_override(window=self.window)):
            yield

    def assert_objects_unchanged(self) -> None:
        self.assertEqual(sorted(obj.name for obj in bpy.data.objects), self.objects)

    def test_add_absent_layout(self) -> None:
        """RF-003-16: una disposición ausente se añade desde los recursos, marcada, y queda
        pendiente de activar; la segunda vez no se añade otra vez."""
        self.assertNotIn(DATA, bpy.data.workspaces)
        self.assertEqual(self.add("DATA"), {"FINISHED"})
        workspace = bpy.data.workspaces.get(DATA)
        self.assertIsNotNone(workspace)
        self.assertTrue(workspace.geoblender_mode)
        self.assertEqual(self.switcher.pending(self.window), DATA)
        self.assertEqual(len(bpy.data.libraries), 0)
        count = len(bpy.data.workspaces)
        self.assertEqual(self.add("DATA"), {"FINISHED"})
        self.assertEqual(len(bpy.data.workspaces), count)
        self.assert_objects_unchanged()

    def test_remove_only_that_workspace(self) -> None:
        """RF-003-16: quitar borra solo ese espacio de trabajo (no datos); la principal y
        un espacio de Blender no se quitan."""
        self.add("MAIN")
        self.add("DATA")
        self.add("SECTION_PLAN")
        before = sorted(ws.name for ws in bpy.data.workspaces)
        with bpy.context.temp_override(window=self.window):
            self.assertEqual(bpy.ops.geoblender.ui_remove_layout(workspace=DATA), {"FINISHED"})
        self.assertEqual(sorted(ws.name for ws in bpy.data.workspaces),
                         [name for name in before if name != DATA])
        self.assert_objects_unchanged()
        for name in (self.main, "Layout"):
            with self.subTest(name=name), self.this_window(name):
                self.assertTrue(self.layouts.remove_check(bpy.context))
                self.assertEqual(bpy.ops.geoblender.ui_remove_layout(), {"CANCELLED"})
                self.assertIn(name, bpy.data.workspaces)
        # Sin «workspace», la de esta ventana.
        with self.this_window(SECTION_PLAN):
            self.assertEqual(self.layouts.remove_check(bpy.context), "")
            self.assertEqual(bpy.ops.geoblender.ui_remove_layout(), {"FINISHED"})
        self.assertNotIn(SECTION_PLAN, bpy.data.workspaces)
        self.assert_objects_unchanged()

    def test_remove_active_waits_for_switch(self) -> None:
        """RF-003-16: si una ventana usa la disposición, pasa a la principal y se borra
        cuando el cambio se ha aplicado."""
        self.add("MAIN")
        self.add("DATA")
        with mock.patch.object(self.layouts, "windows_using", return_value=[self.window]):
            with bpy.context.temp_override(window=self.window):
                self.assertEqual(bpy.ops.geoblender.ui_remove_layout(workspace=DATA),
                                 {"FINISHED"})
            self.assertIn(DATA, bpy.data.workspaces)
            self.assertEqual(self.switcher.pending(self.window), self.main)
            self.assertIn(DATA, self.layouts.pending_names())
            self.layouts.check_pending()  # la ventana aún la usa
            self.assertIn(DATA, bpy.data.workspaces)
        with mock.patch.object(self.layouts, "windows_using", return_value=[]):
            self.layouts.check_pending()
        self.assertNotIn(DATA, bpy.data.workspaces)
        self.assertEqual(self.layouts.pending_names(), ())
        self.assert_objects_unchanged()

    def test_restore(self) -> None:
        """RF-003-16: restaurar la vuelve a anexar con su reparto original y su nombre."""
        self.add("DATA")
        original = area_types(bpy.data.workspaces[DATA])
        bpy.data.workspaces[DATA].screens[0].areas[0].type = "CONSOLE"
        self.assertNotEqual(area_types(bpy.data.workspaces[DATA]), original)
        with bpy.context.temp_override(window=self.window):
            self.assertEqual(bpy.ops.geoblender.ui_restore_layout(workspace=DATA),
                             {"FINISHED"})
        restored = bpy.data.workspaces[DATA]
        self.assertEqual(area_types(restored), original)
        self.assertTrue(restored.geoblender_mode)
        self.assertEqual([ws.name for ws in bpy.data.workspaces if ws.name.startswith(DATA)],
                         [DATA])
        self.assertEqual(len(bpy.data.libraries), 0)
        self.assert_objects_unchanged()
        with self.this_window("Layout"):
            self.assertTrue(self.layouts.restore_check(bpy.context))
            self.assertEqual(bpy.ops.geoblender.ui_restore_layout(), {"CANCELLED"})

    def test_later_entries_disabled(self) -> None:
        """RF-003-07, CW §6.2: las de R-62 y R-57, desactivadas en el menú y, elegidas,
        «Disponible en …» sin cambiar nada."""
        menu = draw(bpy.types.GEOBLENDER_MT_ui_layouts, bpy.context)
        added = {item.properties.layout: item.enabled for item in menu.of_kind("operator")
                 if item.target == ADD}
        self.assertEqual(set(added), {"MAIN", "SECTION_PLAN", "DATA", "DESIGN_PROFILE",
                                      "PHASES", *LATER})
        for layout_id, enabled in added.items():
            self.assertEqual(enabled, layout_id not in LATER, layout_id)
        names = sorted(ws.name for ws in bpy.data.workspaces)
        for layout_id in LATER:
            with self.subTest(layout=layout_id):
                self.assertEqual(self.add(layout_id), {"CANCELLED"})
                self.assertEqual(sorted(ws.name for ws in bpy.data.workspaces), names)
        description = bpy.types.GEOBLENDER_OT_ui_add_layout.description(
            bpy.context, SimpleNamespace(layout="VERSION_REVIEW"))
        self.assertIn("Disponible en R-62", description)

    def test_panel(self) -> None:
        """CW §6.4: la ventana lista las del fichero (la activa, hundida) y las que faltan
        (las de R-62 y R-57, desactivadas), Quitar, Restaurar, la fila y la barra de
        estado."""
        self.add("MAIN")
        self.add("DATA")
        ctx = SimpleNamespace(window=self.window, workspace=bpy.data.workspaces[self.main],
                              screen=self.window.screen, scene=bpy.context.scene, area=None,
                              preferences=bpy.context.preferences)
        panel = draw(bpy.types.GEOBLENDER_PT_ui_layouts, ctx)
        operators = panel.of_kind("operator")
        chosen = [(item.properties.layout, item.options.get("depress"), item.enabled)
                  for item in operators if item.target == ADD]
        self.assertEqual(chosen[:2], [("MAIN", True, True), ("DATA", False, True)])
        missing = {layout_id: enabled for layout_id, _depress, enabled in chosen[2:]}
        self.assertEqual(set(missing), {"SECTION_PLAN", "DESIGN_PROFILE", "PHASES", *LATER})
        for layout_id, enabled in missing.items():
            self.assertEqual(enabled, layout_id not in LATER, layout_id)
        targets = [item.target for item in operators]
        self.assertIn(REMOVE, targets)
        self.assertIn(RESTORE, targets)
        self.assertIn("geoblender.ui_toggle_quick_access_row", targets)
        remove = next(item for item in operators if item.target == REMOVE)
        self.assertFalse(remove.enabled)  # la principal no se quita
        self.assertIn("show_mining_statusbar", [item.target for item in panel.of_kind("prop")])


if __name__ == "__main__":
    unittest.main()
