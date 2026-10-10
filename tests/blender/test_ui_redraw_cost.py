# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que Geoblender hace en cada redibujo de la ventana no rehace nada del catálogo ni
vuelve a medir textos (spec 003, T46; RNF-003-03; RF-003-03, RF-003-11, RF-003-28).

Con la medida de la T42, el redibujo costaba 1,44 ms más en modo Geoblender: la fila 2, la
barra superior, la barra de estado y los ``poll`` de sus operadores (Blender los llama en
cada redibujo) volvían a calcular lo mismo cada vez. Tras un primer dibujo:

- la barra superior y la fila 2 no vuelven a ordenar el acceso rápido del catálogo
  (``Catalog.quick_access``) y dibujan lo mismo;
- el ``poll`` de Encuadrar la ventana de trabajo, sin proyecto, no rehace la tabla de
  traducciones del catálogo (``Catalog.translations``, unos 0,17 ms) y sigue diciendo su
  paso previo;
- la barra de estado no vuelve a medir con ``blf`` los textos que ya midió ni a pasar el
  cursor a absolutas si no se ha movido; si se mueve, sus coordenadas cambian; y un campo
  registrado después se ve en su sitio.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import FakeLayout

SYNTHETIC = "gbtest_t46"
THIN = " "  # espacio fino sin ruptura de los miles (core.i18n.format_xyz)


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


class _Area:
    def __init__(self, pointer: int, kind: str = "VIEW_3D") -> None:
        self.type = kind
        self.show_menus = True
        self._pointer = pointer

    def as_pointer(self) -> int:
        return self._pointer


class RedrawCostTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()
        cls.cat = _module("core.catalog").load()
        cls.catalog_cls = type(cls.cat)
        cls.quick = _module("bl.ui.quick_access")
        cls.statusbar = _module("bl.ui.statusbar")
        cls.georef = _module("bl.scene.georef")
        cls.window = bpy.context.window_manager.windows[0]

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.release()

    def setUp(self) -> None:
        bpy.context.scene.cursor.location = (12.34, -28.98, 212.4)
        self.addCleanup(self.statusbar.unregister_field, SYNTHETIC)

    def context(self, *, width: float, area: Any, region_type: str = "HEADER") -> Any:
        return SimpleNamespace(
            workspace=SimpleNamespace(geoblender_mode=True, use_filter_by_owner=False),
            screen=SimpleNamespace(show_fullscreen=False, show_statusbar=True),
            area=area, region=SimpleNamespace(type=region_type, width=width, alignment="TOP"),
            mode="OBJECT", scene=bpy.context.scene, space_data=None, window=self.window,
            preferences=bpy.context.preferences)

    @contextmanager
    def spy(self, name: str) -> Iterator[mock.MagicMock]:
        """Cuenta las llamadas al método ``name`` del catálogo sin cambiar lo que da."""
        original = getattr(self.catalog_cls, name)
        with mock.patch.object(self.catalog_cls, name, autospec=True,
                               side_effect=original) as found:
            yield found

    def draw_topbar(self) -> list[tuple[str, str, str]]:
        owner = SimpleNamespace(layout=FakeLayout())
        ctx = self.context(width=1920.0, area=_Area(7, "TOPBAR"))
        bpy.types.TOPBAR_HT_upper_bar.draw_left(owner, ctx)
        return [(item.kind, item.target, item.text) for item in owner.layout.items]

    def draw_row(self) -> list[tuple[str, str, str]]:
        owner = SimpleNamespace(layout=FakeLayout())
        self.quick.draw_view_row(owner, self.context(width=1300.0, area=_Area(1),
                                                     region_type="TOOL_HEADER"))
        return [(item.kind, item.target, item.text) for item in owner.layout.items]

    def draw_statusbar(self) -> list[str]:
        layout = FakeLayout()
        ctx = SimpleNamespace(workspace=SimpleNamespace(geoblender_mode=True),
                              region=SimpleNamespace(width=1920.0), scene=bpy.context.scene,
                              window=self.window, screen=self.window.screen, area=None,
                              preferences=bpy.context.preferences)
        self.statusbar.draw_statusbar(SimpleNamespace(layout=layout), ctx)
        return layout.texts()

    def test_topbar_and_row_do_not_sort_the_catalog(self) -> None:
        """RNF-003-03 (RF-003-03, RF-003-11): tras un primer dibujo, la barra superior y la
        fila 2 dibujan lo mismo sin volver a ordenar el acceso rápido del catálogo."""
        topbar, row = self.draw_topbar(), self.draw_row()
        self.assertTrue(topbar and row)
        with self.spy("quick_access") as quick_access, self.spy("translations") as table:
            for _ in range(3):
                self.assertEqual(self.draw_topbar(), topbar)
                self.assertEqual(self.draw_row(), row)
        self.assertEqual(quick_access.call_count, 0)
        self.assertEqual(table.call_count, 0)

    def test_work_window_poll_does_not_rebuild_translations(self) -> None:
        """RNF-003-03: sin proyecto, el ``poll`` de Encuadrar la ventana de trabajo (un
        control de la fila 2, que Blender comprueba en cada redibujo) dice su paso previo
        sin rehacer la tabla de traducciones del catálogo."""
        poll = bpy.ops.geoblender.ui_frame_work_window.poll
        self.assertFalse(poll())
        views = _module("bl.ui.views")
        message = views.no_work_window_message()
        with self.spy("translations") as table:
            for _ in range(5):
                self.assertFalse(poll())
                self.assertEqual(views.no_work_window_message(), message)
        self.assertEqual(table.call_count, 0)
        self.assertIn("▸", message)

    def test_statusbar_measures_each_text_once(self) -> None:
        """RNF-003-03 (RF-003-28): la barra de estado no vuelve a medir con ``blf`` lo que
        ya midió ni a pasar a absolutas un cursor que no se ha movido; si se mueve, sus
        coordenadas cambian."""
        fake = self.georef.SceneGeoref("uid", "Cantera sintética", 25830, 0,
                                       (736500, 4435900, 0))
        with mock.patch.object(self.georef, "project_georeference", return_value=fake):
            first = self.draw_statusbar()
            with mock.patch.object(self.statusbar.blf, "dimensions",
                                   wraps=self.statusbar.blf.dimensions) as dimensions, \
                    mock.patch.object(self.statusbar, "local_to_world",
                                      wraps=self.statusbar.local_to_world) as to_world:
                for _ in range(3):
                    self.assertEqual(self.draw_statusbar(), first)
                self.assertEqual(dimensions.call_count, 0)
                self.assertEqual(to_world.call_count, 0)
                bpy.context.scene.cursor.location = (13.0, -28.98, 212.4)
                moved = self.draw_statusbar()
                self.assertEqual(to_world.call_count, 1)
        self.assertNotEqual(moved, first)
        self.assertIn(f"X 736{THIN}513,00  Y 4{THIN}435{THIN}871,02  Z 212,40", moved)

    def test_statusbar_field_registered_later(self) -> None:
        """Contrato 5 (RF-003-28): un campo registrado después de dibujar se ve en su
        sitio, y al quitarlo deja de verse."""
        self.draw_statusbar()

        def draw(layout: Any, _context: Any) -> None:
            layout.label(text="⟳ 1 · 42 %", translate=False)

        self.statusbar.register_field(SYNTHETIC, priority=1, draw=draw,
                                      width_px=lambda _context: 60.0, order=15.0)
        texts = self.draw_statusbar()
        self.assertEqual(texts[1], "⟳ 1 · 42 %")
        self.statusbar.unregister_field(SYNTHETIC)
        self.assertNotIn("⟳ 1 · 42 %", self.draw_statusbar())


if __name__ == "__main__":
    unittest.main()
