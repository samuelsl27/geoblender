# SPDX-License-Identifier: GPL-3.0-or-later
"""Acceso rápido del proyecto y de la vista (spec 003, T20; AR §2 y §3; BS §1 y §3).

- RF-003-11: en modo Geoblender, la fila 2 de cada Vista 3D (``VIEW3D_HT_tool_header``,
  delante de los ajustes de la herramienta) dibuja los 24 controles de AR §3.1 en su orden y
  con un separador entre grupos en una Vista 3D de 1300 px; a 650 px quedan Vista, Sección
  (la banda en icono), Nueva polilínea, Encaje y «»», que abre los plegados; en edición de
  malla y de curva, solo el subconjunto de AR §3.3; Vista, Sección, Nueva polilínea y Encaje
  no se pliegan nunca, a ninguna anchura; nada en modo Blender ni con la preferencia
  apagada; «Mostrar la fila de acceso rápido de la vista» la vuelve a mostrar.
- RF-003-03 (AR §2): en la barra superior, tras Ayuda, Guardar, Deshacer, Rehacer, Datos ▾,
  Refrescar y Versión activa (con su título en los niveles A y B; en C, solo el icono).

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from types import ModuleType, SimpleNamespace

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import FakeLayout, draw

SNAP = "tool_settings.use_snap"
NEVER_FOLDED_GROUPS = ("view", "section")
NEVER_FOLDED = ("geoblender.ui_draw_polyline", SNAP)
VERSION = "GEOBLENDER_PT_core_version"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


class _Area:
    """Un área simulada con su puntero (la clave del estado por área)."""

    def __init__(self, pointer: int) -> None:
        self.type = "VIEW_3D"
        self._pointer = pointer

    def as_pointer(self) -> int:
        return self._pointer


def context(width: float, *, mode: str = "OBJECT", geoblender: bool = True,
            area: object | None = None) -> SimpleNamespace:
    """La fila 2 de una Vista 3D de ``width`` px en el modo ``mode``."""
    return SimpleNamespace(
        workspace=SimpleNamespace(geoblender_mode=geoblender, use_filter_by_owner=False),
        screen=SimpleNamespace(show_fullscreen=False),
        area=area or _Area(1),
        region=SimpleNamespace(type="TOOL_HEADER", width=width, alignment="TOP"),
        mode=mode,
        scene=bpy.context.scene,
        space_data=None,
        window=bpy.context.window_manager.windows[0],
    )


class QuickAccessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.cat = _module("core.catalog").load()
        cls.schema = _module("core.catalog.schema")
        cls.quick = _module("bl.ui.quick_access")
        cls.items = cls.cat.quick_access("view")
        cls.groups = {item.key: item.group for item in cls.items}
        cls.extras = {item.extra for item in cls.items if item.extra}

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.release()

    def tearDown(self) -> None:
        self.preferences().show_view_quick_access = True

    def preferences(self) -> object:
        return bpy.context.preferences.addons[module_name()].preferences.ui

    def row(self, ctx: SimpleNamespace) -> FakeLayout:
        owner = SimpleNamespace(layout=FakeLayout())
        self.quick.draw_view_row(owner, ctx)
        return owner.layout

    def keys(self, layout: FakeLayout) -> list[str]:
        """Las claves del catálogo de los controles dibujados, en orden (sin «»» ni el ▾
        de un control doble)."""
        found = []
        for item in layout.items:
            if item.kind == "operator":
                found.append(self.schema.make_key(item.target, vars(item.properties)))
            elif item.kind in ("menu", "popover") and item.target not in self.extras:
                if item.target != self.quick.MORE_PANEL:
                    found.append(item.target)
            elif item.kind == "prop":
                found.append(f"tool_settings.{item.target}")
        return found

    def test_prepended_to_tool_header(self) -> None:
        """RF-003-11 (AR §1): la fila 2 se dibuja delante de los ajustes de la herramienta,
        con una sola función añadida."""
        functions = bpy.types.VIEW3D_HT_tool_header.draw._draw_funcs
        ours = [f for f in functions if f is self.quick.draw_view_row]
        self.assertEqual(len(ours), 1)
        self.assertIs(functions[0], self.quick.draw_view_row)

    def test_full_row(self) -> None:
        """RF-003-11: a 1300 px en modo Objeto, los 24 controles de AR §3.1 en orden, un
        separador de línea entre grupos y sin «»»."""
        layout = self.row(context(1300))
        self.assertEqual(self.keys(layout), [item.key for item in self.items])
        separators = [item for item in layout.items if item.kind == "separator"]
        self.assertEqual(len(separators), len({item.group for item in self.items}) - 1)
        self.assertNotIn(self.quick.MORE_PANEL, [item.target for item in layout.items])
        snap = [item for item in layout.items if item.kind == "prop"]
        self.assertEqual([item.text for item in snap], [""])

    def test_two_views(self) -> None:
        """RF-003-11 (AR §3.3): a 650 px quedan Vista, Sección (la banda en solo icono),
        Nueva polilínea y Encaje, con «»» al final; «»» abre los plegados de esa vista."""
        area = _Area(650)
        layout = self.row(context(650, area=area))
        shown = self.keys(layout)
        expected = [item.key for item in self.items
                    if item.group in NEVER_FOLDED_GROUPS or item.key in NEVER_FOLDED]
        self.assertEqual(shown, expected)
        band = [item for item in layout.items if item.target == "GEOBLENDER_PT_geo_band"]
        self.assertEqual([item.text for item in band], [""])
        self.assertEqual(layout.items[-1].target, self.quick.MORE_PANEL)
        more = draw(bpy.types.GEOBLENDER_PT_ui_quick_access_more, context(650, area=area))
        folded = [item.key for item in self.items if item.key not in expected]
        self.assertEqual(self.keys(more), folded)
        self.assertTrue(all(item.text for item in more.items if item.kind != "separator"))

    def test_edit_modes(self) -> None:
        """RF-003-11 (AR §3.3): en edición de malla y de curva, solo Vista, Sección, Nueva
        polilínea, Encaje, Plano de trabajo y Objeto actual, más «»»."""
        subset = [item.key for item in self.items if item.edit_modes]
        for mode in ("EDIT_MESH", "EDIT_CURVE"):
            with self.subTest(mode=mode):
                layout = self.row(context(1300, mode=mode))
                self.assertEqual(self.keys(layout), subset)
                self.assertEqual(layout.items[-1].target, self.quick.MORE_PANEL)

    def test_never_folded(self) -> None:
        """RF-003-11: a ninguna anchura ni en ningún modo se pliegan Vista, Sección, Nueva
        polilínea ni Encaje."""
        core = [item.key for item in self.items
                if item.group in NEVER_FOLDED_GROUPS or item.key in NEVER_FOLDED]
        for width in (200, 400, 650, 900, 1100, 1300, 1900):
            for mode in ("OBJECT", "EDIT_MESH", "SCULPT"):
                with self.subTest(width=width, mode=mode):
                    shown = self.keys(self.row(context(width, mode=mode)))
                    self.assertEqual([key for key in shown if key in core], core)

    def test_nothing_in_blender_mode(self) -> None:
        """RF-003-11: en modo Blender, o con la preferencia apagada, la fila 2 es la de
        Blender."""
        self.assertEqual(self.row(context(1300, geoblender=False)).items, [])
        self.preferences().show_view_quick_access = False
        self.assertEqual(self.row(context(1300)).items, [])

    def test_toggle_row(self) -> None:
        """AR §3.3: «Mostrar la fila de acceso rápido de la vista» enciende la preferencia
        y la fila 2 de las Vistas 3D de la pantalla; otra vez, apaga la preferencia."""
        spaces = [area.spaces.active for area in bpy.context.window.screen.areas
                  if area.type == "VIEW_3D"]
        self.assertTrue(spaces)
        for space in spaces:
            space.show_region_tool_header = False
        with bpy.context.temp_override(window=bpy.context.window_manager.windows[0]):
            bpy.ops.geoblender.ui_toggle_quick_access_row()
            self.assertTrue(self.preferences().show_view_quick_access)
            self.assertTrue(all(space.show_region_tool_header for space in spaces))
            bpy.ops.geoblender.ui_toggle_quick_access_row()
        self.assertFalse(self.preferences().show_view_quick_access)
        self.assertTrue(all(space.show_region_tool_header for space in spaces))

    def test_project_quick_access(self) -> None:
        """RF-003-03 (AR §2, BS §3): en la barra, tras Ayuda, Guardar, Deshacer, Rehacer,
        Datos ▾, Refrescar y Versión activa, con su título en B y solo el icono en C."""
        topbar = _module("bl.ui.topbar")
        level = _module("core.catalog.width").Level
        expected = ["geoblender.core_save_project", "ed.undo", "ed.redo",
                    "GEOBLENDER_MT_core_data", "geoblender.core_refresh", VERSION]
        bar = SimpleNamespace(workspace=SimpleNamespace(geoblender_mode=True),
                              screen=SimpleNamespace(show_fullscreen=False),
                              region=SimpleNamespace(width=1920), scene=bpy.context.scene)
        for current, titled in ((level.B, True), (level.C, False)):
            with self.subTest(level=current):
                layout = FakeLayout()
                topbar.draw_geoblender(layout, bar, current)
                targets = [item.target for item in layout.items]
                tail = targets[targets.index("GEOBLENDER_MT_ui_help") + 1:]
                self.assertEqual([t for t in tail if t], expected)
                version = [item for item in layout.items if item.target == VERSION]
                self.assertEqual(bool(version[0].text), titled)


if __name__ == "__main__":
    unittest.main()
