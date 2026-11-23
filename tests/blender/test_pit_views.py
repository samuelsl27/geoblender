# SPDX-License-Identifier: GPL-3.0-or-later
"""El TIN y el sólido de excavación de una corta como vistas (spec 018, T30; HU-018-4; RF-018-30; RNF-018-09; ADR-0005, ADR-0021; plan 018 §4, §5.5; comprobación manual M4), sin proyecto.

Las vistas reciben lo que entrega el dominio (las polilíneas y la línea de cielo; la superficie de partida y la de la corta) y lo llevan a un objeto en coordenadas locales relativas al GeoOrigin.
Con proyecto (los datos ``des_pbl_``, ``des_psk_`` y ``des_pbk_`` de una corta creada, sus cargadores y «no escribe nada») es el hito ``milestone_pit_h2.py`` (letra ``ha``).

- RF-018-30 (a): el TIN y el sólido tienen cargador del tipo ``DESIGN`` con su nombre traducido; ``des_psf_`` (la superficie de cualquier entidad) sigue sin cargador.
- RF-018-30, ADR-0005 (b): el TIN de unas polilíneas con la línea de cielo, **recortado a lo que encierra**: la CDT rellena la envolvente convexa y aquí solo queda lo de dentro de la línea
  más externa (un contorno en L: su área, no la de su envolvente); las aristas de las polilíneas están en la malla, la cota de cada vértice es la suya y las coordenadas son locales.
- ADR-0021 (c): con la CDT de Blender si su tiempo estimado cabe en ``gis.tin.blender_cdt_max_s`` y con la pura, por pasos, si no (el mismo TIN).
- RNF-018-09 (d): el aviso de triángulos sale **antes** de crear nada: por encima del límite, ``des.pit_view_large`` y ninguna malla; sin límite (confirmado), se crea.
- RF-018-30 (e): el sólido es una malla **cerrada** (cada arista en dos caras, volumen positivo) entre la superficie de partida y la de la corta, en locales, sin cifras.
- RF-018-30 (f): una corta que no baja la superficie no tiene sólido (``des.pit_view_empty``); regenerar da lo mismo y cerrar a mitad no deja nada.
- Principio 8 (z): desactivar Geoblender quita los cargadores.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.support import blender_ext

KIND = "DESIGN"
X0, Y0, Z0 = 700_000, 4_400_000, 100


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{blender_ext.module_name()}.{name}")


def run(steps: Any) -> Any:
    """Los pasos hasta el final: lo que devuelven."""
    while True:
        try:
            next(steps)
        except StopIteration as done:
            return done.value


def ring(points: list[tuple[float, float]], z: float) -> np.ndarray:
    """El anillo absoluto (sin repetir el primer vértice) de los puntos locales ``points``, todos a la cota ``z``."""
    xy = np.asarray(points, dtype=np.float64) + np.array([X0, Y0], dtype=np.float64)
    return np.column_stack([xy, np.full(len(xy), z)])


def shoelace(points: np.ndarray) -> float:
    x, y = points[:, 0], points[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2.0)


class PitViewsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        cls.views = _module("bl.scene.views")
        cls.pit_views = _module("bl.scene.pit_views")
        cls.des_views = _module("bl.scene.des_views")
        cls.triangulator = _module("bl.scene.triangulator")
        cls.messages = _module("design.messages")
        cls.i18n = _module("core.i18n")
        cls.mesh = _module("bl.scene.mesh")
        cls.georef = _module("core.georef")
        cls.origin = cls.georef.GeoOrigin(X0, Y0, Z0)
        catalog = cls.georef.load_catalog()
        cls.crs, cls.vertical = catalog.horizontal(25830), catalog.vertical(5782)

    def request(self, name: str = "Corta") -> Any:
        return SimpleNamespace(origin=self.origin, record=SimpleNamespace(name=f"des_pbl_{name}"), name=f"Triangulación {name}", lod=0, project=None)

    def parts_of(self, steps: Any) -> Any:
        return run(steps)

    # --- el TIN ----------------------------------------------------------------------------------------------------------

    def l_shape(self) -> tuple[list[tuple[np.ndarray, bool]], list[tuple[np.ndarray, bool]]]:
        """Un contorno en L (el cuadrado de 100 m sin su cuarto noreste: 7.500 m²) como línea de cielo, y dentro la cresta y el pie de un banco."""
        outer = ring([(0, 0), (100, 0), (100, 50), (50, 50), (50, 100), (0, 100)], 130.0)
        crest = ring([(10, 10), (90, 10), (90, 40), (40, 40), (40, 90), (10, 90)], 120.0)
        foot = ring([(20, 20), (80, 20), (80, 30), (30, 30), (30, 80), (20, 80)], 110.0)
        return [(crest, True), (foot, True)], [(outer, True)]

    def test_a_the_tin_and_the_solid_have_their_loaders_and_the_surface_of_an_entity_still_has_none(self) -> None:
        """RF-018-30 (plan 018 §5.5): ``des_pbl_`` (las polilíneas de la corta) se carga como TIN y ``des_pbk_`` como sólido de excavación, del tipo ``DESIGN``, con su nombre traducido;
        la superficie de cualquier entidad (``des_psf_``) sigue sin cargador."""
        tin = self.views.loader_for("des_pbl_corta")
        solid = self.views.loader_for("des_pbk_corta")
        self.assertEqual((tin.prefix, tin.kind, tin.label), ("des_pbl_", KIND, "Pit TIN"))
        self.assertEqual((solid.prefix, solid.kind, solid.label), ("des_pbk_", KIND, "Pit excavation solid"))
        self.assertIs(tin.load, self.pit_views.load_pit_tin)
        self.assertIs(solid.load, self.pit_views.load_pit_solid)
        self.assertEqual(self.i18n.translate("es", tin.label), "TIN de la corta")
        self.assertEqual(self.i18n.translate("es", solid.label), "Sólido de excavación de la corta")
        self.assertEqual(self.i18n.untranslated([tin.label, solid.label]), [])
        self.assertIsNone(self.views.loader_for("des_psf_corta"))
        self.assertEqual(len({label for _family, label in self.des_views.LOADERS}), len(self.des_views.LOADERS))

    def test_b_the_tin_is_clipped_to_the_outermost_line_and_keeps_every_edge(self) -> None:
        """RF-018-30, ADR-0005: con las polilíneas y la línea de cielo de un contorno en L, el TIN tiene **el área de la L** (7.500 m²) y no la de su envolvente (10.000 m²),
        cada arista de las polilíneas y de la línea de cielo es una arista de la malla, cada vértice tiene su cota y las coordenadas son locales (float32 sin pérdida)."""
        lines, skyline = self.l_shape()
        parts = self.parts_of(self.pit_views.tin_steps(self.request(), lines, skyline))
        (obj,) = parts.objects
        mesh = obj.data
        local = self.mesh.mesh_vertices_local(mesh)
        self.assertLess(float(np.abs(local[:, :2]).max()), 200.0, "locales respecto al GeoOrigin, no absolutas")
        world = local.astype(np.float64) + np.array([0.0, 0.0, Z0])
        triangles = self.mesh.mesh_triangles(mesh)
        area = sum(shoelace(world[tri][:, :2]) for tri in triangles)
        self.assertAlmostEqual(area, 7_500.0, delta=1e-3)
        found = {tuple(sorted((int(a), int(b)))) for tri in triangles for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0]))}
        key = {tuple(np.round(point, 3)): index for index, point in enumerate(world)}
        for points, _closed in (*lines, *skyline):
            local_points = points - np.array([X0, Y0, 0.0]) + np.array([0.0, 0.0, 0.0])
            for first, second in zip(local_points, np.roll(local_points, -1, axis=0)):
                a, b = key[tuple(np.round(first, 3))], key[tuple(np.round(second, 3))]
                self.assertIn(tuple(sorted((a, b))), found, "una arista obligatoria falta en la malla")
        self.assertEqual(sorted(set(np.round(world[:, 2], 3).tolist())), [110.0, 120.0, 130.0])
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(mesh)

    def test_c_the_cdt_of_blender_only_if_its_estimate_fits_and_the_pure_one_otherwise(self) -> None:
        """ADR-0021, RF-018-30: con el tiempo estimado dentro de ``gis.tin.blender_cdt_max_s`` triangula la CDT de Blender; si no, la pura por pasos, **sin** llamar a la de Blender, y
        dan el mismo TIN (la misma área)."""
        lines, skyline = self.l_shape()
        triangulate = self.triangulator.BlenderTriangulator.triangulate
        with mock.patch.object(self.triangulator.BlenderTriangulator, "triangulate", autospec=True, side_effect=triangulate) as native:
            first = self.parts_of(self.pit_views.tin_steps(self.request(), lines, skyline))
        self.assertEqual(native.call_count, 1)
        too_slow = self.triangulator.TriangulationChoice(10, 99.0, 2.0, False)
        with mock.patch.object(self.triangulator.BlenderTriangulator, "triangulate", autospec=True) as native, \
                mock.patch.object(self.triangulator, "choose_triangulation", return_value=too_slow):
            second = self.parts_of(self.pit_views.tin_steps(self.request(), lines, skyline))
        native.assert_not_called()
        for parts in (first, second):
            mesh = parts.objects[0].data
            world = self.mesh.mesh_vertices_local(mesh).astype(np.float64)
            area = sum(shoelace(world[tri][:, :2]) for tri in self.mesh.mesh_triangles(mesh))
            self.assertAlmostEqual(area, 7_500.0, delta=1e-3)
        for parts in (first, second):
            bpy.data.meshes.remove(parts.objects[0].data)

    def test_d_the_warning_of_triangles_comes_before_creating_anything(self) -> None:
        """RNF-018-09: por encima del límite de triángulos (un parámetro de la vista) sale ``des.pit_view_large`` **antes** de crear ninguna malla; sin límite (el sí de la persona), se crea."""
        lines, skyline = self.l_shape()
        before = len(bpy.data.meshes)
        with self.assertRaises(self.messages.DesignError) as caught:
            self.parts_of(self.pit_views.tin_steps(self.request("Grande"), lines, skyline, max_triangles=5))
        self.assertEqual(caught.exception.code, "des.pit_view_large")
        self.assertIn("Grande", str(caught.exception))
        self.assertEqual(len(bpy.data.meshes), before, "no se creó ninguna malla")
        self.assertEqual(self.pit_views.MAX_TRIANGLES, 300_000)
        parts = self.parts_of(self.pit_views.tin_steps(self.request("Grande"), lines, skyline, max_triangles=None))
        self.assertEqual(len(bpy.data.meshes), before + 1)
        bpy.data.meshes.remove(parts.objects[0].data)

    # --- el sólido -------------------------------------------------------------------------------------------------------

    def rasters(self, depth: float = 5.0) -> tuple[Any, Any]:
        """La partida llana a 100 m en 20 × 20 celdas de 2 m y la corta que la baja ``depth`` m en un bloque de 6 × 6 celdas."""
        grid = _module("gis.grid").Grid(X0 + 0.0, Y0 + 40.0, 2.0, 2.0, 20, 20)
        raster = _module("gis.raster").Raster
        start = np.full((20, 20), 100.0)
        surface = start.copy()
        surface[7:13, 7:13] -= depth
        return raster(grid, start, self.crs, self.vertical), raster(grid, surface, self.crs, self.vertical)

    def test_e_the_solid_is_a_closed_mesh_between_the_two_surfaces(self) -> None:
        """RF-018-30: el sólido de excavación entre la partida y la corta es una malla **cerrada** (cada arista en dos caras), con volumen positivo (los centros de las celdas del corte: 5 × 5
        intervalos de 2 m a 5 m de profundidad, 500 m³), en locales y sin ninguna cifra en el objeto."""
        start, surface = self.rasters()
        parts = self.parts_of(self.pit_views.solid_steps(self.request("Sólida"), start, surface))
        (obj,) = parts.objects
        mesh = obj.data
        local = self.mesh.mesh_vertices_local(mesh).astype(np.float64)
        triangles = self.mesh.mesh_triangles(mesh)
        edges: dict[tuple[int, int], int] = {}
        for tri in triangles:
            for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
                edges[(min(a, b), max(a, b))] = edges.get((min(a, b), max(a, b)), 0) + 1
        self.assertEqual(set(edges.values()), {2}, "malla cerrada")
        a, b, c = (local[triangles[:, index]] for index in range(3))
        volume = float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)
        self.assertAlmostEqual(volume, 500.0, delta=1e-3)
        self.assertLess(float(np.abs(local[:, :2]).max()), 100.0)
        self.assertEqual(list(obj.keys()), [], "sin cifras en el objeto")
        self.assertEqual(parts.notes, ())
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(mesh)

    def test_f_a_pit_that_does_not_lower_the_surface_has_no_solid_and_regenerating_gives_the_same(self) -> None:
        """RF-018-30, RF-010-01: sin celdas de corte, ``des.pit_view_empty``; el aviso de triángulos del sólido sale antes de crear; cargar dos veces da los mismos vértices y caras, y cerrar a
        mitad no deja ninguna malla."""
        start, surface = self.rasters()
        before = len(bpy.data.meshes)
        with self.assertRaises(self.messages.DesignError) as caught:
            self.parts_of(self.pit_views.solid_steps(self.request(), start, start))
        self.assertEqual(caught.exception.code, "des.pit_view_empty")
        with self.assertRaises(self.messages.DesignError) as caught:
            self.parts_of(self.pit_views.solid_steps(self.request(), start, surface, max_triangles=10))
        self.assertEqual(caught.exception.code, "des.pit_view_large")
        self.assertEqual(len(bpy.data.meshes), before)
        runs = [self.parts_of(self.pit_views.solid_steps(self.request(), start, surface)) for _ in range(2)]
        first, second = (self.mesh.mesh_vertices_local(parts.objects[0].data) for parts in runs)
        np.testing.assert_array_equal(first, second)
        np.testing.assert_array_equal(self.mesh.mesh_triangles(runs[0].objects[0].data), self.mesh.mesh_triangles(runs[1].objects[0].data))
        for parts in runs:
            bpy.data.meshes.remove(parts.objects[0].data)
        steps = self.pit_views.solid_steps(self.request(), start, surface)
        next(steps)
        steps.close()
        self.assertEqual(len(bpy.data.meshes), before, "cerrar a mitad no deja nada")
        lines, skyline = self.l_shape()
        steps = self.pit_views.tin_steps(self.request(), lines, skyline)
        for _ in range(3):
            next(steps)
        steps.close()
        self.assertEqual(len(bpy.data.meshes), before)

    def test_z_deactivating_geoblender_removes_the_loaders(self) -> None:
        """Principio 8: quitar los cargadores del diseño quita también los del TIN y el sólido (``des_views.unregister``), y registrarlos otra vez los devuelve."""
        self.assertIsNotNone(self.views.loader_for("des_pbl_corta"))
        self.des_views.unregister()
        self.assertIsNone(self.views.loader_for("des_pbl_corta"))
        self.assertIsNone(self.views.loader_for("des_pbk_corta"))
        self.des_views.register()
        self.assertIsNotNone(self.views.loader_for("des_pbl_corta"))
        self.assertIsNotNone(self.views.loader_for("des_pbk_corta"))


if __name__ == "__main__":
    unittest.main()
