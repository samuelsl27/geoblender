# SPDX-License-Identifier: GPL-3.0-or-later
"""Vistas mineras, Vista 3D de destino, encuadre, vistas guardadas y recorte de la vista
(spec 003, T21–T23; spec §6.1, §7 y §8; BS §8.12; AR §3.1 y §4).

T21:

- RF-003-12: las 9 vistas mineras de spec §6.1 dejan la Vista 3D en ortográfica con la
  dirección de mirada (error ≤ 0,01°) y el «arriba en pantalla» de la tabla (norte en
  planta; +Z en las laterales; la proyección de +Z en las isométricas).
- Spec §7 (Vista 3D de destino): desde una Vista 3D, esa; desde la barra superior (sin
  área), la última en la que se usó un comando de vista de Geoblender o, si no hay, la
  mayor de la ventana; sin ninguna Vista 3D, el comando no se puede ejecutar y lo dice.
- AR §4: el menú circular de vistas ya tiene sus vistas disponibles.

Se ejecuta con ``tools/run_blender_tests.py``. Sin interfaz, la geometría de las áreas es
la del fichero de fábrica (la Vista 3D de «Layout» es la mayor).
"""

import importlib
import math
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace

import bpy
from mathutils import Vector

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import draw

MAX_ANGLE_DEG = 0.01
S3 = 1.0 / math.sqrt(3.0)
UP_Z = (0.0, 0.0, 1.0)
# Spec §6.1: vista → (dirección de mirada, arriba en pantalla; None = proyección de +Z).
MINING_VIEWS: dict[str, tuple[tuple[float, float, float], tuple[float, float, float] | None]] = {
    "PLAN": ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    "NORTH": ((0.0, 1.0, 0.0), UP_Z),
    "SOUTH": ((0.0, -1.0, 0.0), UP_Z),
    "EAST": ((1.0, 0.0, 0.0), UP_Z),
    "WEST": ((-1.0, 0.0, 0.0), UP_Z),
    "ISO_NE": ((-S3, -S3, -S3), None),
    "ISO_NW": ((S3, -S3, -S3), None),
    "ISO_SE": ((-S3, S3, -S3), None),
    "ISO_SW": ((S3, S3, -S3), None),
}


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def angle_deg(a: Vector, b: Vector) -> float:
    return math.degrees(a.normalized().angle(b.normalized(), 0.0))


def expected_up(look: tuple[float, ...], up: tuple[float, ...] | None) -> Vector:
    d = Vector(look).normalized()
    if up is not None:
        return Vector(up)
    z = Vector(UP_Z)
    return (z - z.dot(d) * d).normalized()


def window() -> bpy.types.Window:
    return bpy.context.window_manager.windows[0]


def view3d_areas() -> list[bpy.types.Area]:
    return [area for area in window().screen.areas if area.type == "VIEW_3D"]


def main_region(area: bpy.types.Area) -> bpy.types.Region:
    return next(region for region in area.regions if region.type == "WINDOW")


@contextmanager
def in_view(area: bpy.types.Area) -> Iterator[None]:
    """Contexto de una Vista 3D (como un comando lanzado desde ella)."""
    with bpy.context.temp_override(window=window(), area=area, region=main_region(area)):
        yield


@contextmanager
def from_topbar() -> Iterator[None]:
    """Contexto de la barra superior: la ventana, sin área."""
    with bpy.context.temp_override(window=window(), area=None, region=None):
        yield


class ViewsTestCase(unittest.TestCase):
    """La extensión habilitada una vez para la clase, sobre el fichero de fábrica."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.load_file()
        blender_ext.enable()
        cls.views = _module("bl.ui.views")
        cls.cat = _module("core.catalog").load()

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.unload()

    def setUp(self) -> None:
        self.views.forget()  # sin «última Vista 3D usada»

    def rv3d(self, area: bpy.types.Area) -> bpy.types.RegionView3D:
        return area.spaces.active.region_3d

    def second_view(self) -> tuple[bpy.types.Area, bpy.types.Area]:
        """(la mayor, una pequeña): la línea de tiempo de «Layout» pasa a Vista 3D."""
        areas = view3d_areas()
        if len(areas) == 1:
            small = next(a for a in window().screen.areas if a.type == "DOPESHEET_EDITOR")
            small.type = "VIEW_3D"
            self.addCleanup(setattr, small, "type", "DOPESHEET_EDITOR")
        areas = sorted(view3d_areas(), key=lambda a: a.width * a.height, reverse=True)
        return areas[0], areas[-1]


class MiningViewsTest(ViewsTestCase):
    def test_nine_views(self) -> None:
        """RF-003-12: las 9 vistas de spec §6.1, ortográficas, con su dirección y su
        arriba con un error ≤ 0,01°."""
        area = view3d_areas()[0]
        rv3d = self.rv3d(area)
        for view, (look, up) in MINING_VIEWS.items():
            with self.subTest(view=view):
                rv3d.view_perspective = "PERSP"
                with in_view(area):
                    self.assertEqual(bpy.ops.geoblender.ui_set_view(view=view), {"FINISHED"})
                self.assertEqual(rv3d.view_perspective, "ORTHO")
                direction = rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))
                screen_up = rv3d.view_rotation @ Vector((0.0, 1.0, 0.0))
                self.assertLessEqual(angle_deg(direction, Vector(look)), MAX_ANGLE_DEG)
                self.assertLessEqual(angle_deg(screen_up, expected_up(look, up)), MAX_ANGLE_DEG)

    def test_target_from_topbar(self) -> None:
        """Spec §7: desde la barra superior, la mayor Vista 3D si no se ha usado ninguna;
        después, la última usada; la otra no cambia."""
        big, small = self.second_view()
        for area in (big, small):
            with in_view(area):
                bpy.ops.geoblender.ui_set_view(view="PLAN")
        self.views.forget()
        with from_topbar():
            bpy.ops.geoblender.ui_set_view(view="EAST")
        east = Vector((1.0, 0.0, 0.0))
        self.assertLessEqual(angle_deg(self.rv3d(big).view_rotation @ Vector((0, 0, -1)), east),
                             MAX_ANGLE_DEG)
        self.assertEqual(self.rv3d(small).view_rotation @ Vector((0, 0, -1)),
                         Vector((0.0, 0.0, -1.0)))
        with in_view(small):
            bpy.ops.geoblender.ui_set_view(view="NORTH")
        with from_topbar():
            bpy.ops.geoblender.ui_set_view(view="WEST")
        west = Vector((-1.0, 0.0, 0.0))
        self.assertLessEqual(angle_deg(self.rv3d(small).view_rotation @ Vector((0, 0, -1)),
                                       west), MAX_ANGLE_DEG)
        self.assertLessEqual(angle_deg(self.rv3d(big).view_rotation @ Vector((0, 0, -1)), east),
                             MAX_ANGLE_DEG)

    def test_no_view3d(self) -> None:
        """Spec §7: sin ninguna Vista 3D en la ventana, el comando no se puede ejecutar y su
        mensaje lo dice."""
        areas = view3d_areas()
        for area in areas:
            area.type = "OUTLINER"
            self.addCleanup(setattr, area, "type", "VIEW_3D")
        with from_topbar():
            self.assertFalse(bpy.ops.geoblender.ui_set_view.poll())
            with self.assertRaisesRegex(RuntimeError, "Vista 3D"):
                bpy.ops.geoblender.ui_set_view(view="PLAN")

    def test_pie_views_available(self) -> None:
        """AR §4: en el menú circular de vistas, las vistas mineras ya están disponibles."""
        ctx = SimpleNamespace(workspace=SimpleNamespace(geoblender_mode=True), area=None,
                              scene=bpy.context.scene, space_data=None, window=window())
        layout = draw(bpy.types.GEOBLENDER_MT_ui_pie_views, ctx)
        views = [item for item in layout.items if item.target == "geoblender.ui_set_view"]
        self.assertEqual(len(views), 6)
        self.assertTrue(all(item.enabled for item in views))


if __name__ == "__main__":
    unittest.main()
