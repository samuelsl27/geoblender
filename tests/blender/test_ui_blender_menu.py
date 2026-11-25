# SPDX-License-Identifier: GPL-3.0-or-later
"""«Blender ▾» en la cabecera de la Vista 3D (spec 019, T20; RF-019-05, RF-019-04;
ADR-0032 punto 5; plan 019 A4).

- En modo Geoblender y en modo Objeto, ``VIEW3D_MT_editor_menus.draw_collapsible`` dibuja un
  solo menú «Blender ▾» (con *View, Select, Add, Object*) y no los cuatro sueltos; la fila de
  Geoblender sigue a su lado.
- En edición, o en una ventana de Blender, o con los menús plegados, se dibuja lo nativo
  tal cual (hacen falta *Mesh*, *Curve*…).
- Tras desactivar la extensión, ``draw_collapsible`` es **el mismo objeto** de antes; ``draw``
  de la cabecera no se toca, de modo que F3 sigue encontrando los menús.
- Mismo mecanismo que el filtro: se instala con la primera ventana en modo Geoblender y se
  retira con la última (P-5); es idempotente, también tras ``script.reload``.

Se ejecuta con ``tools/run_blender_tests.py`` (sin pantalla: se dibuja en un diseño falso).
"""

import importlib
import unittest
from types import ModuleType, SimpleNamespace
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name

TARGET = "VIEW3D_MT_editor_menus"
NATIVES = ("VIEW3D_MT_view", "VIEW3D_MT_select_object", "VIEW3D_MT_add", "VIEW3D_MT_object")
BLENDER_MENU = "GEOBLENDER_MT_ui_blender"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


class FakeLayout:
    """Un diseño que anota lo que se le dibuja (``row`` devuelve el mismo)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def row(self, **_kw: object) -> "FakeLayout":
        return self

    def menu(self, name: str, **_kw: object) -> None:
        self.calls.append(("menu", name))

    def menu_contents(self, name: str) -> None:
        self.calls.append(("menu_contents", name))

    def label(self, **_kw: object) -> None:
        self.calls.append(("label", ""))

    def separator(self, **_kw: object) -> None:
        pass

    def names(self, kind: str) -> list[str]:
        return [name for k, name in self.calls if k == kind]


def _raw_collapsible() -> object:
    """``draw_collapsible`` tal como lo ve la clase (la función del classmethod)."""
    return getattr(getattr(bpy.types, TARGET), "draw_collapsible").__func__


class BlenderMenuTest(unittest.TestCase):
    """RF-019-05, RF-019-04: el parche de ``draw_collapsible`` y el menú «Blender ▾»."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.release()

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        self.nf = _module("bl.ui.native_filter")
        self.headers = _module("bl.ui.headers")
        self.gb = SimpleNamespace(name="gbtest_t20_geoblender", geoblender_mode=True)
        self.blender_ws = bpy.data.workspaces.get("Layout") or bpy.data.workspaces[0]
        self.gb_window = SimpleNamespace(workspace=self.gb)
        self.bl_window = SimpleNamespace(workspace=self.blender_ws)
        self.cls = getattr(bpy.types, TARGET)

    def tearDown(self) -> None:
        if blender_ext.is_enabled():
            self.nf.remove()

    def _context(self, mode: str = "OBJECT", workspace: object = None,
                 show_menus: bool = True) -> SimpleNamespace:
        return SimpleNamespace(mode=mode, workspace=workspace or self.gb,
                               area=SimpleNamespace(show_menus=show_menus))

    def _draw(self, context: SimpleNamespace) -> tuple[FakeLayout, mock.Mock]:
        layout = FakeLayout()
        with mock.patch.object(self.headers, "draw_row1") as row1:
            self.cls.draw_collapsible(context, layout)
        return layout, row1

    def test_object_mode_draws_one_blender_menu(self) -> None:
        """RF-019-05: en modo Geoblender y Objeto hay «Blender ▾» y no los cuatro sueltos;
        la fila de Geoblender se dibuja una vez, al lado."""
        self.assertTrue(self.nf.sync([self.gb_window]))
        layout, row1 = self._draw(self._context("OBJECT"))
        self.assertEqual(layout.names("menu"), [BLENDER_MENU])
        self.assertEqual(layout.names("menu_contents"), [])
        row1.assert_called_once()

    def test_blender_menu_holds_the_four_natives(self) -> None:
        """RF-019-05: dentro de «Blender ▾» están View, Select, Add y Object, y se dice que
        siguen el idioma de Blender (UI-34)."""
        self.assertTrue(self.nf.sync([self.gb_window]))
        menu = getattr(bpy.types, BLENDER_MENU)
        layout = FakeLayout()
        menu.draw(SimpleNamespace(layout=layout), self._context("OBJECT"))
        self.assertEqual(layout.names("menu"), list(NATIVES))
        self.assertIn("label", [k for k, _n in layout.calls])
        for name in NATIVES:
            self.assertTrue(hasattr(bpy.types, name), name)

    def test_edit_mode_keeps_the_natives(self) -> None:
        """RF-019-05: en edición, lo nativo tal cual (menu_contents de la cabecera)."""
        self.assertTrue(self.nf.sync([self.gb_window]))
        for mode in ("EDIT_MESH", "EDIT_CURVE", "SCULPT"):
            layout, row1 = self._draw(self._context(mode))
            self.assertEqual(layout.names("menu_contents"), [TARGET], mode)
            self.assertEqual(layout.names("menu"), [], mode)
            row1.assert_not_called()

    def test_blender_window_and_collapsed_menus_untouched(self) -> None:
        """RF-019-05: una ventana de Blender, o con los menús plegados, dibuja lo nativo."""
        self.assertTrue(self.nf.sync([self.gb_window, self.bl_window]))
        layout, _row1 = self._draw(self._context("OBJECT", workspace=self.blender_ws))
        self.assertEqual(layout.names("menu_contents"), [TARGET])
        layout, _row1 = self._draw(self._context("OBJECT", show_menus=False))
        self.assertEqual(layout.names("menu_contents"), [])
        self.assertEqual(layout.names("menu"), [TARGET])  # el plegado nativo

    def test_identity_after_unregister_and_f3_menus_unchanged(self) -> None:
        """RF-019-04: tras desactivar, ``draw_collapsible`` es el mismo objeto y sin entrada
        propia; ``draw`` de la cabecera no se tocó nunca (F3 recorre ese ``draw``)."""
        before = _raw_collapsible()
        draw_before = self.cls.__dict__.get("draw")
        own_before = self.cls.__dict__.get("draw_collapsible")
        self.assertIsNone(own_before)
        self.assertTrue(self.nf.sync([self.gb_window]))
        self.assertIsNot(_raw_collapsible(), before)  # de verdad parcheó
        self.assertIn("draw_collapsible", self.cls.__dict__)
        self.assertIs(self.cls.__dict__.get("draw"), draw_before)
        blender_ext.release()
        cls = getattr(bpy.types, TARGET)
        self.assertNotIn("draw_collapsible", cls.__dict__)
        self.assertIs(_raw_collapsible(), before)
        self.assertIs(cls.__dict__.get("draw"), draw_before)
        self.assertFalse(hasattr(bpy.types, BLENDER_MENU))

    def test_lives_with_the_windows_and_is_idempotent(self) -> None:
        """P-5: se pone con la primera ventana en modo Geoblender y se retira con la última;
        instalar dos veces no lo envuelve dos veces."""
        before = _raw_collapsible()
        self.assertFalse(self.nf.sync([self.bl_window]))
        self.assertIs(_raw_collapsible(), before)
        self.assertTrue(self.nf.sync([self.gb_window, self.bl_window]))
        patched = _raw_collapsible()
        self.assertTrue(self.nf.install())
        self.assertIs(_raw_collapsible(), patched)
        self.assertFalse(self.nf.sync([self.bl_window]))
        self.assertIs(_raw_collapsible(), before)

    def test_survives_script_reload(self) -> None:
        """ADR-0032: tras recargar el módulo (pierde su estado) el parche se recupera de su
        marca, no se envuelve otra vez y se retira dejando el original."""
        before = _raw_collapsible()
        # script.reload desactiva (quita avisos y manejadores del módulo viejo) y recarga el
        # módulo con el parche puesto por un caso que no pasó por unregister()
        self.nf.unregister()
        self.assertTrue(self.nf.install())
        reloaded = importlib.reload(self.nf)
        self.nf = reloaded
        self.assertTrue(reloaded.install())
        self.assertIsNot(_raw_collapsible(), before)
        reloaded.remove()
        self.assertNotIn("draw_collapsible", self.cls.__dict__)
        self.assertIs(_raw_collapsible(), before)


if __name__ == "__main__":
    unittest.main()
