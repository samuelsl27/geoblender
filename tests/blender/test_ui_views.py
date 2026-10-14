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

T22:

- RF-003-13: «Encuadrar la ventana de trabajo» con una ventana sintética en UTM (GeoOrigin
  de la 002) deja las 8 esquinas de la caja (ventana × cotas de lo visible en ella; sin
  nada, el cursor ± 50 m) dentro de la región y entre los planos de recorte de la vista,
  en perspectiva y en ortográfica, con ``clip_end / clip_start`` ≤ 10⁵ (la proyección
  de la prueba es la de Blender para una Vista 3D: sensor de 36 mm, factor 2 y ajuste al
  lado mayor de la región; en ortográfica, profundidades de −clip_end/2 a clip_end/2).
- RF-003-09, RF-003-13 (spec §8): sin proyecto o sin ventana de trabajo, desactivado con
  «Primero defina la ventana de trabajo (Proyecto ▸ … ▸ Ventana de trabajo …)».
- RF-003-14: una vista guardada en una ranura se restaura con ≤ 1 mm de centro, ≤ 0,01° de
  orientación, la distancia y la proyección, también tras guardar el fichero (en temporal)
  y volverlo a abrir; el centro va en coordenadas locales (a ±8 km del origen, float32 da
  ≤ 0,5 mm).
- RF-003-09, RF-003-14 (spec §8): una ranura vacía se dibuja desactivada y su descripción
  dice «Guarde antes la vista n (Ctrl+Mayús+F…)»; invocada, informa eso y no cambia la
  vista.

T23 (D-1):

- RF-003-15: «Recorte ▸ Banda de la vista» con w = 5 m deja los planos de recorte de esa
  región a ±5 m del cursor 3D, perpendiculares a la mirada (≤ 1 mm, también a ±8 km del
  origen y en una vista oblicua); la otra Vista 3D no cambia; «Sin recorte» los quita; el
  semiancho se ajusta con F9 (``REGISTER`` y ``UNDO``, de 0,1 a 1000 m); la caja nativa
  (Alt+B) sustituye a la banda (spec §8).
- RF-003-07 (D-1): los demás modos de recorte son de R-16: desactivados en Recorte ▸ y,
  invocados, «Disponible en R-16 · …» sin cambiar nada; el menú Recorte ▾ está disponible
  (tiene «Sin recorte» y «Banda de la vista»).

Se ejecuta con ``tools/run_blender_tests.py``. Sin interfaz, la geometría de las áreas es
la del fichero de fábrica (la Vista 3D de «Layout» es la mayor).
"""

import importlib
import math
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock

import bpy
from mathutils import Quaternion, Vector

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import draw

MAX_ANGLE_DEG = 0.01
MAX_CENTRE_M = 0.001
SENSOR_MM = 36.0  # sensor de la Vista 3D (DEFAULT_SENSOR_WIDTH de Blender)
VIEW_ZOOM = 2.0  # CAMERA_PARAM_ZOOM_INIT_PERSP: el factor de la Vista 3D (no de la cámara)
# Ventana sintética en UTM y su GeoOrigin (los de tests/support/core_fixtures.py, spec 002).
WINDOW_UTM = (699_500.4, 4_399_500.6, 700_500.2, 4_400_500.9)
ORIGIN_UTM = (700_000, 4_400_000, 0)
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
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()
        cls.views = _module("bl.ui.views")
        cls.cat = _module("core.catalog").load()

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.release()

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


def project_corner(rv3d: bpy.types.RegionView3D, space: bpy.types.SpaceView3D,
                   region: bpy.types.Region, point: Vector) -> tuple[float, float, float]:
    """(x, y) en la región, en px desde su esquina inferior izquierda, y la profundidad
    desde el ojo de un punto local, con la proyección de una Vista 3D de Blender
    (``BKE_camera_params_from_view3d``: el lado mayor de la región ve
    ``sensor / lens × zoom / 2`` por unidad de profundidad; en ortográfica, el semiancho
    del lado mayor es ``view_distance × sensor / lens``; comprobado con
    ``view3d.view_selected`` en 5.2.1)."""
    rotation = rv3d.view_rotation
    right = rotation @ Vector((1.0, 0.0, 0.0))
    up = rotation @ Vector((0.0, 1.0, 0.0))
    back = rotation @ Vector((0.0, 0.0, 1.0))
    eye = rv3d.view_location + back * rv3d.view_distance
    relative = point - eye
    depth = -relative.dot(back)
    width, height = region.width, region.height
    if rv3d.view_perspective == "ORTHO":
        half_large = rv3d.view_distance * SENSOR_MM / space.lens
    else:
        half_large = depth * SENSOR_MM / space.lens * VIEW_ZOOM / 2.0
    scale = (max(width, height) / 2.0) / half_large
    return (width / 2.0 + relative.dot(right) * scale,
            height / 2.0 + relative.dot(up) * scale, depth)


@contextmanager
def project_open(window_utm: tuple[float, ...] | None, *,
                 without_window: bool = False) -> Iterator[None]:
    """El proyecto abierto, sintético: su ventana de trabajo (``without_window``: ninguna)
    y su GeoOrigin; con ``window_utm`` ``None``, ningún proyecto."""
    georef = _module("core.georef")
    session = _module("bl.scene.project_session")
    if window_utm is None:
        fake = None
    else:
        fake = SimpleNamespace(window=None if without_window else georef.Window(*window_utm),
                               origin=georef.GeoOrigin(*ORIGIN_UTM))
    with mock.patch.object(session, "current", return_value=fake):
        yield


def add_block(name: str, xy: tuple[float, float, float, float],
              z: tuple[float, float]) -> bpy.types.Object:
    """Una caja de malla en coordenadas locales (sin el GeoOrigin en ``location``)."""
    x0, y0, x1, y1 = xy
    z0, z1 = z
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(x, y, zz) for x in (x0, x1) for y in (y0, y1) for zz in (z0, z1)],
                     [], [])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


class FrameAndSavedViewsTest(ViewsTestCase):
    """En modo Geoblender: encuadrar, guardar y recuperar tienen atajo en la Vista 3D y
    pasan por la puerta de modo."""

    def setUp(self) -> None:
        super().setUp()
        window().workspace.geoblender_mode = True
        self.addCleanup(lambda: setattr(window().workspace, "geoblender_mode", False))
        for obj in list(bpy.context.scene.objects):
            bpy.data.objects.remove(obj)
        self.area = view3d_areas()[0]
        self.space = self.area.spaces.active
        self.region = main_region(self.area)

    def corners(self, z: tuple[float, float]) -> list[Vector]:
        x0, y0, x1, y1 = WINDOW_UTM
        ox, oy, oz = ORIGIN_UTM
        return [Vector((x - ox, y - oy, zz - oz)) for x in (x0, x1) for y in (y0, y1)
                for zz in z]

    def assertFramed(self, corners: list[Vector]) -> None:
        rv3d = self.rv3d(self.area)
        start, end = self.space.clip_start, self.space.clip_end
        self.assertLessEqual(end / start, 1e5 * (1 + 1e-6))
        if rv3d.view_perspective == "ORTHO":
            near, far = -end / 2.0, end / 2.0
        else:
            near, far = start, end
        for corner in corners:
            x, y, depth = project_corner(rv3d, self.space, self.region, corner)
            self.assertTrue(0.0 <= x <= self.region.width, (corner, x))
            self.assertTrue(0.0 <= y <= self.region.height, (corner, y))
            self.assertTrue(near <= depth <= far, (corner, depth, near, far))

    def test_frame_work_window(self) -> None:
        """RF-003-13: las 8 esquinas de la ventana × las cotas de lo visible en ella, dentro
        de la región y entre los planos de recorte, en perspectiva y en ortográfica, con
        una relación lejano/cercano ≤ 10⁵; lo que está fuera de la ventana no cuenta."""
        add_block("Dentro", (-100.0, -50.0, 120.0, 80.0), (150.0, 260.0))
        add_block("Fuera", (5000.0, 5000.0, 5010.0, 5010.0), (-900.0, 2000.0))
        rv3d = self.rv3d(self.area)
        for perspective in ("PERSP", "ORTHO"):
            with self.subTest(perspective=perspective):
                rv3d.view_perspective = perspective
                rv3d.view_location = (0.0, 0.0, 0.0)
                rv3d.view_distance = 10.0
                self.space.clip_start, self.space.clip_end = 0.01, 1000.0
                with project_open(WINDOW_UTM), in_view(self.area):
                    self.assertEqual(bpy.ops.geoblender.ui_frame_work_window(), {"FINISHED"})
                self.assertFramed(self.corners((150.0, 260.0)))
                self.assertEqual(rv3d.view_perspective, perspective)

    def test_frame_without_objects(self) -> None:
        """RF-003-13: sin nada visible en la ventana, las cotas son las del cursor ± 50 m;
        desde la barra superior, en la Vista 3D de destino."""
        bpy.context.scene.cursor.location = (0.0, 0.0, 212.4)
        with project_open(WINDOW_UTM), from_topbar():
            self.assertEqual(bpy.ops.geoblender.ui_frame_work_window(), {"FINISHED"})
        self.assertFramed(self.corners((162.4, 262.4)))

    def test_frame_needs_work_window(self) -> None:
        """RF-003-09 (spec §8): sin proyecto, o sin ventana de trabajo, no se puede encuadrar
        y el mensaje nombra el paso previo y su ruta."""
        pattern = r"Primero defina la ventana de trabajo \(Proyecto ▸ .*Ventana de trabajo"
        for patch in (project_open(None), project_open(WINDOW_UTM, without_window=True)):
            with self.subTest(patch=patch), patch, in_view(self.area):
                self.assertFalse(bpy.ops.geoblender.ui_frame_work_window.poll())
                with self.assertRaisesRegex(RuntimeError, pattern):
                    bpy.ops.geoblender.ui_frame_work_window()

    def set_view(self, location: tuple[float, float, float], rotation: Quaternion,
                 distance: float, perspective: str) -> None:
        rv3d = self.rv3d(self.area)
        rv3d.view_location = location
        rv3d.view_rotation = rotation
        rv3d.view_distance = distance
        rv3d.view_perspective = perspective

    def assertSameView(self, location: Vector, rotation: Quaternion, distance: float,
                       perspective: str) -> None:
        rv3d = self.rv3d(self.area)
        self.assertLessEqual((rv3d.view_location - location).length, MAX_CENTRE_M)
        difference = rv3d.view_rotation.rotation_difference(rotation)
        self.assertLessEqual(math.degrees(difference.angle), MAX_ANGLE_DEG)
        self.assertAlmostEqual(rv3d.view_distance, distance, delta=1e-3)
        self.assertEqual(rv3d.view_perspective, perspective)

    def test_store_and_recall(self) -> None:
        """RF-003-14: guardar la ranura 2 y recuperarla tras mover la vista, también después
        de guardar el fichero y abrirlo otra vez; a ±8 km del origen, ≤ 1 mm."""
        location = Vector((7999.123, -7999.456, 1234.5))
        rotation = Quaternion((0.82, 0.21, -0.31, 0.43)).normalized()
        self.set_view(location, rotation, 321.5, "ORTHO")
        with in_view(self.area):
            self.assertEqual(bpy.ops.geoblender.ui_store_view(slot=2), {"FINISHED"})
        self.set_view((0.0, 0.0, 0.0), Quaternion(), 15.0, "PERSP")
        with in_view(self.area):
            self.assertEqual(bpy.ops.geoblender.ui_recall_view(slot=2), {"FINISHED"})
        self.assertSameView(location, rotation, 321.5, "ORTHO")
        with tempfile.TemporaryDirectory(prefix="gb-t22-") as folder:
            path = Path(folder) / "vistas.blend"
            bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True)
            blender_ext.load_file(path)
            self.addCleanup(blender_ext.load_file)
        self.area = view3d_areas()[0]
        self.set_view((1.0, 2.0, 3.0), Quaternion(), 15.0, "PERSP")
        with in_view(self.area):
            self.assertEqual(bpy.ops.geoblender.ui_recall_view(slot=2), {"FINISHED"})
        self.assertSameView(location, rotation, 321.5, "ORTHO")

    def test_empty_slot(self) -> None:
        """RF-003-09, RF-003-14 (spec §8): una ranura vacía se dibuja desactivada y su
        descripción dice cómo guardarla; invocada, lo informa y no cambia la vista."""
        bpy.context.scene.geoblender_views.clear()
        with in_view(self.area):
            bpy.ops.geoblender.ui_store_view(slot=1)
        ctx = SimpleNamespace(workspace=SimpleNamespace(geoblender_mode=True),
                              area=self.area, scene=bpy.context.scene, space_data=None,
                              window=window())
        layout = draw(bpy.types.GEOBLENDER_MT_ui_recall_view, ctx)
        slots = {item.properties.slot: item.enabled for item in layout.items
                 if item.target == "geoblender.ui_recall_view"}
        self.assertEqual(slots, {1: True, 2: False, 3: False, 4: False})
        cls = bpy.types.GEOBLENDER_OT_ui_recall_view
        text = cls.description(bpy.context, SimpleNamespace(slot=4))
        self.assertEqual(text, "Guarde antes la vista 4 (Ctrl+Mayús+F8)")
        before = self.rv3d(self.area).view_location.copy()
        with in_view(self.area):
            self.assertEqual(bpy.ops.geoblender.ui_recall_view(slot=4), {"CANCELLED"})
        self.assertEqual(self.rv3d(self.area).view_location, before)


class ClipBandTest(ViewsTestCase):
    """En modo Geoblender: Alt+0 (Sin recorte) está en la Vista 3D y pasa por la puerta."""

    MAX_PLANE_M = 0.001

    def setUp(self) -> None:
        super().setUp()
        window().workspace.geoblender_mode = True
        self.addCleanup(lambda: setattr(window().workspace, "geoblender_mode", False))
        self.big, self.small = self.second_view()
        for area in (self.big, self.small):
            self.rv3d(area).use_clip_planes = False

    def side(self, plane: object, point: Vector) -> float:
        a, b, c, d = plane
        return a * point.x + b * point.y + c * point.z + d

    def assertBand(self, area: bpy.types.Area, cursor: Vector, half: float) -> None:
        """Los dos primeros planos a ±``half`` del cursor a lo largo de la mirada; lo de
        dentro de la banda, visible (lado ≥ 0 de los seis planos), y lo de fuera, no."""
        rv3d = self.rv3d(area)
        self.assertTrue(rv3d.use_clip_planes)
        planes = [tuple(plane) for plane in rv3d.clip_planes]
        look = (rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))).normalized()
        front, back = cursor + look * half, cursor - look * half
        self.assertLessEqual(abs(self.side(planes[1], front)), self.MAX_PLANE_M)
        self.assertLessEqual(abs(self.side(planes[0], back)), self.MAX_PLANE_M)
        for inside in (cursor, cursor + look * (half - 0.01), cursor - look * (half - 0.01)):
            self.assertTrue(all(self.side(plane, inside) >= 0 for plane in planes), inside)
        for outside in (cursor + look * (half + 0.01), cursor - look * (half + 0.01)):
            self.assertTrue(any(self.side(plane, outside) < 0 for plane in planes), outside)

    def clip(self, area: bpy.types.Area, **properties: object) -> set[str]:
        with in_view(area):
            return bpy.ops.geoblender.geo_set_clip_mode(**properties)

    def test_band_in_one_view(self) -> None:
        """RF-003-15, CE-003-05: fijar el cursor, Mirando al este y Banda (w = 5 m): planos
        a ±5 m del cursor solo en esa vista; «Sin recorte» (Alt+0) los quita."""
        cursor = Vector((7999.123, -7999.877, 250.456))
        bpy.context.scene.cursor.location = cursor
        with in_view(self.big):
            bpy.ops.geoblender.ui_set_view(view="EAST")
        self.assertEqual(self.clip(self.big, mode="BAND", half_width=5.0), {"FINISHED"})
        self.assertBand(self.big, cursor, 5.0)
        self.assertFalse(self.rv3d(self.small).use_clip_planes)
        self.assertEqual(self.views.clip_mode(self.rv3d(self.big)), "BAND")
        self.assertEqual(self.clip(self.big, mode="NONE"), {"FINISHED"})
        self.assertFalse(self.rv3d(self.big).use_clip_planes)
        self.assertEqual(self.views.clip_mode(self.rv3d(self.big)), "NONE")

    def test_oblique_view_and_f9(self) -> None:
        """RF-003-15: en una isométrica la banda es perpendicular a la mirada; el semiancho
        se ajusta con F9 (el operador se repite con otro valor) y vale de 0,1 a 1000 m."""
        cursor = Vector((-7654.321, 7123.987, -150.789))
        bpy.context.scene.cursor.location = cursor
        with in_view(self.small):
            bpy.ops.geoblender.ui_set_view(view="ISO_SW")
        self.clip(self.small, mode="BAND", half_width=5.0)
        self.assertBand(self.small, cursor, 5.0)
        self.clip(self.small, mode="BAND", half_width=12.5)
        self.assertBand(self.small, cursor, 12.5)
        cls = bpy.types.GEOBLENDER_OT_geo_set_clip_mode
        self.assertEqual(cls.bl_options & {"REGISTER", "UNDO"}, {"REGISTER", "UNDO"})
        half = bpy.ops.geoblender.geo_set_clip_mode.get_rna_type().properties["half_width"]
        self.assertEqual((round(half.hard_min, 3), half.hard_max, half.default), (0.1, 1000.0, 5.0))
        self.assertFalse(self.rv3d(self.big).use_clip_planes)

    def test_native_box_replaces_band(self) -> None:
        """Spec §8: la caja de recorte de Blender (Alt+B) sustituye a la banda: el modo deja
        de ser «Banda»."""
        self.clip(self.big, mode="BAND", half_width=5.0)
        rv3d = self.rv3d(self.big)
        rv3d.clip_planes[0] = (0.0, 0.0, 1.0, 3.0)  # lo que haría Alt+B
        self.assertEqual(self.views.clip_mode(rv3d), "BOX")

    def test_other_modes_are_r16(self) -> None:
        """RF-003-07 (D-1): Delante, Detrás y Banda atenuada son de R-16: desactivados en
        Recorte ▸ e, invocados, no cambian nada; Recorte ▾ está disponible."""
        ctx = SimpleNamespace(workspace=SimpleNamespace(geoblender_mode=True), area=self.big,
                              scene=bpy.context.scene, space_data=None, window=window())
        layout = draw(bpy.types.GEOBLENDER_MT_geo_clip, ctx)
        modes = {item.properties.mode: item.enabled for item in layout.items
                 if item.target == "geoblender.geo_set_clip_mode"}
        self.assertEqual(modes, {"NONE": True, "FRONT": False, "BACK": False, "BAND": True,
                                 "BAND_FADED": False})
        commands = _module("bl.ui.commands")
        self.assertTrue(commands.is_available("GEOBLENDER_MT_geo_clip"))
        for mode in ("FRONT", "BACK", "BAND_FADED"):
            with self.subTest(mode=mode):
                self.assertEqual(self.clip(self.big, mode=mode), {"CANCELLED"})
                self.assertFalse(self.rv3d(self.big).use_clip_planes)


if __name__ == "__main__":
    unittest.main()
