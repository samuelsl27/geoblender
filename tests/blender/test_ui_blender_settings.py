# SPDX-License-Identifier: GPL-3.0-or-later
"""«Ajustes de Blender» (spec 019, T19; RF-019-03; ADR-0032 punto 3; plan 019 §2.1).

- La orden abre una ventana nueva y su espacio es uno **no marcado** («Layout»); se fija **en el ciclo
  siguiente**, no con una asignación y una lectura seguidas.
- En ese espacio **pasan los ``poll`` nativos** (el filtro no la afecta); en el de Geoblender, ninguno.
- La ventana original sigue como estaba (en Geoblender).
- Sin ventana nueva (sin interfaz) la orden lo dice y no cambia nada; desactivar la extensión no deja
  temporizador ni pendiente.

En ``blender -b`` ``wm.window_new`` no tiene contexto: la apertura se sustituye por una ventana falsa
(el diálogo y la ventana real, en el H3). Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from types import ModuleType, SimpleNamespace
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name

GB_NAME = "gbtest_t19_geoblender"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _natives() -> list[type]:
    return [c for c in bpy.types.Panel.__subclasses__()
            if getattr(c, "bl_space_type", "") == "PROPERTIES"
            and not c.__name__.startswith("GEOBLENDER_") and getattr(c, "is_registered", False)]


def _call(cls: type, context: object) -> bool:
    poll = getattr(cls, "poll", None)
    if poll is None:
        return True
    try:
        return bool(poll(context))
    except Exception:  # noqa: BLE001 - como Blender: si el poll falla, se dibuja
        return True


class BlenderSettingsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()
        cls.switcher = _module("bl.ui.switcher")
        cls.nf = _module("bl.ui.native_filter")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.release()

    def setUp(self) -> None:
        blender_ext.load_file()
        self.switcher.forget()
        self.window = bpy.context.window_manager.windows[0]
        self.fake = SimpleNamespace(workspace=bpy.data.workspaces["Layout"], as_pointer=lambda: 987654321)
        self.gb = SimpleNamespace(name=GB_NAME, geoblender_mode=True)

    def tearDown(self) -> None:
        self.nf.remove()

    def open(self) -> set[str]:
        with mock.patch.object(self.switcher, "_new_window", return_value=self.fake) as opener:
            with bpy.context.temp_override(window=self.window):
                result = bpy.ops.geoblender.ui_blender_settings()
        self.assertEqual(opener.call_count, 1)
        return result

    def test_opens_a_window_with_an_unmarked_workspace_next_cycle(self) -> None:
        """RF-019-03: la orden crea una ventana y su espacio es no marcado; se fija en el ciclo siguiente."""
        self.fake.workspace = None  # recién abierta: aún sin el espacio de la orden
        self.assertEqual(self.open(), {"FINISHED"})
        self.assertIsNone(self.fake.workspace, "se asignó en el mismo ciclo")
        self.assertTrue(bpy.app.timers.is_registered(self.switcher.settle_settings))
        self.switcher.settle_settings([self.window, self.fake])  # lo que hace el temporizador
        self.assertFalse(self.fake.workspace.geoblender_mode)
        self.assertEqual(self.fake.workspace.name, "Layout")
        self.assertEqual(self.switcher.pending(self.fake), "Layout")

    def test_native_polls_pass_there_and_the_original_window_is_untouched(self) -> None:
        """RF-019-03: en el espacio de la ventana pasan los ``poll`` nativos aunque el filtro esté puesto;
        la ventana original no cambia."""
        here = SimpleNamespace(workspace=bpy.data.workspaces["Layout"])
        natives = _natives()
        plain = {c: _call(c, here) for c in natives}  # sin filtro: lo que decide cada panel por sí mismo
        before = (self.window.workspace.name, self.switcher.pending(self.window))
        self.assertTrue(self.nf.sync([SimpleNamespace(workspace=self.gb)]))
        self.open()
        self.switcher.settle_settings([self.window, self.fake])
        here = SimpleNamespace(workspace=self.fake.workspace)
        from_geoblender = SimpleNamespace(workspace=self.gb)
        self.assertEqual([c.__name__ for c in natives if c.poll(from_geoblender)], [])
        self.assertEqual({c: _call(c, here) for c in natives}, plain)  # el filtro no la afecta
        self.assertTrue(any(plain.values()))
        self.assertEqual((self.window.workspace.name, self.switcher.pending(self.window)), before)

    def test_without_a_new_window_it_says_so_and_changes_nothing(self) -> None:
        """Sin interfaz (``wm.window_new`` no tiene contexto) la orden informa y no deja pendientes."""
        with bpy.context.temp_override(window=self.window):
            self.assertEqual(bpy.ops.geoblender.ui_blender_settings(), {"CANCELLED"})
        self.assertFalse(bpy.app.timers.is_registered(self.switcher.settle_settings))
        self.assertEqual(self.switcher._SESSION.settings, [])  # noqa: SLF001

    def test_without_a_free_workspace_it_says_why_and_what_to_do(self) -> None:
        """RF-019-03, UI-09 (T41 f): si todos los espacios de Blender están ocupados o marcados (``settings_workspace`` da
        ``None``), la orden no falla en silencio: avisa de por qué no abre y qué hacer, y no abre ninguna ventana."""
        reports: list[tuple[set[str], str]] = []
        operator = bpy.types.GEOBLENDER_OT_ui_blender_settings
        fake_self = SimpleNamespace(report=lambda kind, text: reports.append((kind, text)))
        with mock.patch.object(self.switcher, "settings_workspace", return_value=None),                 mock.patch.object(self.switcher, "_new_window") as opener:
            # ``report`` de un operador real no se puede sustituir: se llama a ``execute`` con un ``self`` simulado.
            self.assertEqual(operator.execute(fake_self, SimpleNamespace(window=self.window)), {"CANCELLED"})
        self.assertEqual(opener.call_count, 0)
        ((kind, text),) = reports
        self.assertEqual(kind, {"WARNING"})
        self.assertIn("en uso", text)
        self.assertIn("Cierre", text)  # qué hacer
        self.assertNotIn("_", text)

    def test_disabling_leaves_no_timer_nor_pending(self) -> None:
        """UI-16/17: desactivar la extensión no deja temporizador ni ventanas pendientes."""
        self.open()
        self.assertTrue(bpy.app.timers.is_registered(self.switcher.settle_settings))
        blender_ext.release()
        self.assertFalse(bpy.app.timers.is_registered(self.switcher.settle_settings))
        self.assertEqual(self.switcher._SESSION.settings, [])  # noqa: SLF001
        blender_ext.enable()

    def test_the_command_is_reachable_from_the_menu_and_the_element_panel(self) -> None:
        """UI-32: está en Herramientas ▾ y al pie del panel del elemento."""
        cat = _module("core.catalog").load()
        self.assertIn("geoblender.ui_blender_settings", cat.commands)
        source = _module("bl.ui.element_panel")
        self.assertEqual(source.SETTINGS_OPERATOR, "geoblender.ui_blender_settings")
        layout = mock.MagicMock()
        source.draw_settings_button(layout)
        layout.operator.assert_called_once()
        self.assertEqual(layout.operator.call_args.args[0], "geoblender.ui_blender_settings")


if __name__ == "__main__":
    unittest.main()
