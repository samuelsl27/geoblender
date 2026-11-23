# SPDX-License-Identifier: GPL-3.0-or-later
"""La línea de cielo de la corta (spec 018, T19; HU-018-4; RF-018-29; CE-018-07; plan 018 §5.4 A11, §5.7 P-9).

Sobre el terreno plano inclinado de CE-018-07 y la corta circular de CE-018-03: la cota de cada vértice es la del terreno (≤ 10⁻⁶ m), la
línea está a no más de media celda de la intersección exacta, su longitud y el área que encierra igualan las analíticas, y la distancia
mínima al límite legal sale igual al cálculo a mano; además, una corta que no sale a superficie, varias partes y la cancelación. Sin
proyecto y sin Blender; rejillas de ≤ 200 × 200."""

from __future__ import annotations

import math
import unittest

import numpy as np

from tests.support import pit_data as pd
from tests.support.package import import_geoblender
from tests.unit.design import milestone_pit_h1 as h1

pit_bench = import_geoblender("design.pit_bench")
pit_surface = import_geoblender("design.pit_surface")
pit_sky = import_geoblender("design.pit_sky")
worker_api = import_geoblender("jobs.worker_api")
gis_contours = import_geoblender("gis.contours")
gis_polygons = import_geoblender("gis.polygons")
gis_raster = import_geoblender("gis.raster")

CELL_M = 2.0
FIRST_RADIUS_M = 50.0


def sky_of(grid: object, start: np.ndarray, design: np.ndarray, **changes: object) -> object:
    return pit_sky.skyline(start, design, grid, crs=pd.CRS, vertical=pd.VERTICAL, **changes)


def pit_of(grid: object, **changes: object) -> tuple[object, object]:
    job = h1.up_job(grid, **changes)
    found = pit_bench.ascend(job)
    return job, pit_surface.rasterize(job, found, (), crs=pd.CRS, vertical=pd.VERTICAL)


class InclinedCase:
    """La corta circular de CE-018-03 sobre el terreno inclinado un 10 % de CE-018-07, a una rejilla de ``CELL_M`` m."""

    def __init__(self, step_m: float = CELL_M) -> None:
        self.grid = pd.grid_of(step_m)
        self.start = pd.inclined_terrain(self.grid)
        self.job = h1.up_job(self.grid, start=self.start)
        self.found = pit_bench.ascend(self.job)
        self.surface = pit_surface.rasterize(self.job, self.found, (), crs=pd.CRS, vertical=pd.VERTICAL)
        self.sky = sky_of(self.grid, self.start, self.surface.stepped)
        self.benches = len(h1.of_kind(self.found, "crest"))
        self.exact, self.exact_length_m, self.exact_area_m2 = self.exact_line()

    def pit_height(self, radius: np.ndarray) -> np.ndarray:
        """La cota analítica de la corta circular (cara, berma y fondo) a ``radius`` m del centro."""
        knots = [0.0, pd.CIRCLE_RADIUS_M]
        heights = [pd.FLOOR_Z_M, pd.FLOOR_Z_M]
        for index, (foot, crest) in enumerate(pd.circle_radii_by_hand(benches=self.benches)):
            top = pd.FLOOR_Z_M + (index + 1) * pd.EXPL.height_m
            knots += [foot, crest]
            heights += [top - pd.EXPL.height_m, top]
        return np.interp(radius, knots, heights)

    def gap_on(self, grid: object) -> np.ndarray:
        """``terreno - corta`` analítica (m) en los centros de ``grid``: positiva donde se excava."""
        x, y = pd.local_centers(grid)
        radius = np.hypot(x - pd.CENTER[0], y - pd.CENTER[1])
        gap = pd.INCLINED_Z_AT_X0_M + pd.INCLINED_PCT / 100.0 * x - self.pit_height(radius)
        return np.where(radius <= pd.circle_radii_by_hand(benches=self.benches)[-1][1], gap, -1.0)  # fuera de la última cresta no hay corta

    def exact_line(self) -> tuple[np.ndarray, float, float]:
        """La intersección exacta, de la función analítica en una rejilla de 0,25 m (la corta alcanza el terreno en varias partes: una berma
        queda a trozos por debajo del terreno en el lado alto): sus segmentos locales ``(k, 2, 2)``, su longitud (m) y el área excavada (m²)."""
        fine = pd.grid_of(0.25)
        gap = self.gap_on(fine)
        lines = gis_contours.contours_from_raster(gis_raster.Raster(fine, np.clip(gap, -0.9, 0.9), pd.CRS, pd.VERTICAL), interval_m=1.0,
                                                  base_m=0.0, simplify_m=0.0, min_length_m=0.0)
        origin = np.asarray(pd.origin_of(fine))
        pieces, length = [], 0.0
        for line in lines:
            ring = line.xyz[:, :2] - origin
            end = np.vstack([ring[1:], ring[:1]]) if line.closed else ring[1:]
            pieces.append(np.stack([ring[: len(end)], end], axis=1))
            length += line.length_m
        return np.concatenate(pieces), length, float((gap > 0.0).sum()) * fine.cell_area


def to_segments(points: np.ndarray, segments: np.ndarray) -> np.ndarray:
    """La distancia de cada punto ``(n, 2)`` al conjunto de ``segments`` ``(k, 2, 2)``."""
    result = np.empty(len(points))
    for index, point in enumerate(points):
        p = np.repeat(np.stack([point, point])[None], len(segments), axis=0)
        result[index] = gis_polygons.segment_distance(p, segments).min()
    return result


class InclinedTerrainTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.case = InclinedCase()
        cls.local = np.asarray(pd.origin_of(cls.case.grid))

    def vertices(self) -> np.ndarray:
        return np.vstack([part.xyz for part in self.case.sky.parts])

    def test_one_closed_part_with_its_figures(self) -> None:
        """RF-018-29: partes cerradas y sus cifras (partes, longitud, área, cotas)."""
        sky = self.case.sky
        self.assertGreaterEqual(sky.n_parts, 1)
        self.assertTrue(sky.parts[0].closed)
        self.assertEqual(sky.z_min_m, float(self.vertices()[:, 2].min()))
        self.assertEqual(sky.z_max_m, float(self.vertices()[:, 2].max()))
        self.assertGreater(sky.length3d_m, sky.length_m)

    def test_elevation_is_the_terrain_at_each_vertex(self) -> None:
        """RF-018-29, CE-018-07: en cada punto la línea tiene la cota del terreno, a ≤ 10⁻⁶ m."""
        vertices = self.vertices()
        local = vertices[:, :2] - self.local
        terrain = pd.INCLINED_Z_AT_X0_M + pd.INCLINED_PCT / 100.0 * local[:, 0]
        self.assertLessEqual(float(np.abs(vertices[:, 2] - terrain).max()), 1e-6)

    def test_line_is_within_half_a_cell_of_the_exact_intersection(self) -> None:
        """CE-018-07: cada vértice a no más de media celda de la intersección exacta."""
        local = self.vertices()[:, :2] - self.local
        self.assertLessEqual(float(to_segments(local, self.case.exact).max()), CELL_M / 2.0)

    def test_length_and_area_match_the_analytic_ones(self) -> None:
        """CE-018-07: la longitud (en planta) y el área que encierra igualan las analíticas en la tolerancia de CE-018-03 (D-11: ≤ 0,1 %)."""
        sky = self.case.sky
        self.assertLess(abs(sky.length_m / self.case.exact_length_m - 1.0), 1e-3)
        self.assertLess(abs(sky.area_m2 / self.case.exact_area_m2 - 1.0), 1e-3)

    def test_no_distances_without_limits(self) -> None:
        """RF-018-29: sin límite legal ni perímetro, no hay distancias (``None``)."""
        self.assertIsNone(self.case.sky.legal)
        self.assertIsNone(self.case.sky.perimeter)

    def test_inputs_are_not_modified(self) -> None:
        """Regla 6: ni la partida ni la corta cambian."""
        case = self.case
        start, design = case.start.copy(), case.surface.stepped.copy()
        sky_of(case.grid, start, design)
        self.assertTrue(np.array_equal(start, case.start))
        self.assertTrue(np.array_equal(design, case.surface.stepped, equal_nan=True))


class DistanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.case = InclinedCase()
        cls.local = np.asarray(pd.origin_of(cls.case.grid))

    def box(self, left: float, bottom: float, right: float, top: float) -> tuple:
        ring = pd.absolute([(left, bottom), (right, bottom), (right, top), (left, top)], self.case.grid)
        return ((ring,),)

    def sky(self, **changes: object) -> object:
        return sky_of(self.case.grid, self.case.start, self.case.surface.stepped, **changes)

    def test_distance_to_the_legal_limit_by_hand(self) -> None:
        """RF-018-29, CE-018-07: el límite legal es un rectángulo a 17 m del punto más al oeste de la intersección exacta: la distancia sale igual (media celda) y con su lugar."""
        west = float(self.case.exact[:, :, 0].min())
        found = self.sky(legal=self.box(west - 17.0 - 50.0, 0.0, west - 17.0, 400.0)).legal
        self.assertAlmostEqual(found.distance_m, 17.0, delta=CELL_M / 2.0)
        self.assertAlmostEqual(math.hypot(*(found.on_line[:2] - found.on_boundary[:2])), found.distance_m, delta=1e-9)
        self.assertAlmostEqual(found.on_boundary[0] - self.local[0], west - 17.0, delta=1e-9)
        self.assertEqual(found.on_line.shape, (3,))

    def test_distance_is_zero_if_the_line_crosses_the_perimeter(self) -> None:
        """RF-018-29: un perímetro que corta la línea da distancia 0."""
        found = self.sky(perimeter=self.box(0.0, 0.0, 200.0, 400.0)).perimeter
        self.assertEqual(found.distance_m, 0.0)

    def test_perimeter_around_everything_gives_its_distance(self) -> None:
        """RF-018-29: la distancia al perímetro de actuación (el borde de un rectángulo que lo contiene todo) a mano."""
        east = float(self.case.exact[:, :, 0].max())
        found = self.sky(perimeter=self.box(-1000.0, -1000.0, east + 23.0, 2000.0)).perimeter
        self.assertAlmostEqual(found.distance_m, 23.0, delta=CELL_M / 2.0)

    def test_no_line_gives_no_distance(self) -> None:
        """RF-018-29: sin línea no hay distancia, aunque haya límite."""
        grid = pd.grid_of(4.0)
        start = pd.flat_terrain(grid)
        found = sky_of(grid, start, start + 5.0, legal=((pd.absolute([(0, 0), (9, 0), (9, 9)], grid),),))
        self.assertIsNone(found.legal)


class NoSurfaceTest(unittest.TestCase):
    def test_a_pit_that_does_not_reach_the_surface_has_no_line(self) -> None:
        """RF-018-29: una corta por encima del terreno (nada se excava) o que ocupa toda la rejilla no da línea: 0 partes y sin cifras de cota."""
        grid = pd.grid_of(4.0)
        start = pd.flat_terrain(grid)
        for label, design in (("sin excavar", start + 5.0), ("todo excavado", start - 5.0)):
            with self.subTest(label):
                sky = sky_of(grid, start, design)
                self.assertEqual((sky.n_parts, sky.parts, sky.length_m, sky.area_m2), (0, (), 0.0, 0.0))
                self.assertIsNone(sky.z_min_m)
                self.assertIsNone(sky.z_max_m)

    def test_flat_terrain_gives_the_edge_of_the_enclosure(self) -> None:
        """RF-018-29: sobre el terreno llano a la cota de la última cresta la corta no tiene diferencia que cruce 0 dentro del recinto: la línea es el borde del recinto, a una celda del círculo de la última cresta y a la cota del terreno."""
        grid = pd.grid_of(2.0)
        job, found = pit_of(grid)
        sky = sky_of(grid, job.start, found.stepped)
        radius = pd.circle_radii_by_hand()[-1][1]
        self.assertEqual(sky.n_parts, 1)
        local = sky.parts[0].xyz[:, :2] - np.asarray(pd.origin_of(grid))
        around = np.hypot(local[:, 0] - pd.CENTER[0], local[:, 1] - pd.CENTER[1])
        self.assertLessEqual(float(np.abs(around - radius).max()), 1.0)
        self.assertLessEqual(float(np.abs(sky.parts[0].xyz[:, 2] - pd.TOP_Z_M).max()), 1e-6)


class SeveralPartsTest(unittest.TestCase):
    def test_two_pits_give_two_parts_and_the_sum_of_their_areas(self) -> None:
        """RF-018-29: dos cavidades separadas dan dos partes; el área es la suma y la longitud también."""
        grid = pd.grid_of(2.0)
        x, y = pd.local_centers(grid)
        start = pd.flat_terrain(grid, 100.0)
        areas = []
        signed = np.full(grid.shape, np.inf)
        for cx, cy, r in ((100.0, 200.0, 30.0), (300.0, 200.0, 20.0)):
            signed = np.minimum(signed, np.hypot(x - cx, y - cy) - r)
            areas.append(math.pi * r * r)
        design = 100.0 + 0.5 * signed
        sky = sky_of(grid, start, design)
        self.assertEqual(sky.n_parts, 2)
        self.assertAlmostEqual(sky.area_m2 / sum(areas), 1.0, delta=0.01)
        self.assertAlmostEqual(sky.length_m / (2 * math.pi * 50.0), 1.0, delta=0.01)

    def test_a_hole_is_subtracted_from_the_area(self) -> None:
        """RF-018-29: una isla dentro de la cavidad se resta del área que encierra (par-impar)."""
        grid = pd.grid_of(2.0)
        x, y = pd.local_centers(grid)
        start = pd.flat_terrain(grid, 100.0)
        design = 100.0 + 0.5 * (np.abs(np.hypot(x - 200.0, y - 200.0) - 40.0) - 20.0)
        sky = sky_of(grid, start, design)
        self.assertEqual(sky.n_parts, 2)
        self.assertAlmostEqual(sky.area_m2 / (math.pi * (60.0**2 - 20.0**2)), 1.0, delta=0.01)


class ErrorsAndCancelTest(unittest.TestCase):
    def test_shape_errors_are_program_errors(self) -> None:
        """Una superficie que no es de la forma de la rejilla es un error del programa."""
        grid = pd.grid_of(4.0)
        with self.assertRaises(ValueError):
            sky_of(grid, pd.flat_terrain(grid), np.zeros((3, 3)))

    def test_cancelling_leaves_nothing(self) -> None:
        """Cancelar a mitad lanza JobCancelled y no deja nada."""
        grid = pd.grid_of(2.0)
        job, found = pit_of(grid)
        with self.assertRaises(worker_api.JobCancelled):
            sky_of(grid, job.start, found.stepped, cancelled=lambda: True)

    def test_progress_ends_at_one(self) -> None:
        """El avance termina en 1."""
        grid = pd.grid_of(4.0)
        job, found = pit_of(grid)
        seen: list[float] = []
        sky_of(grid, job.start, found.stepped, progress=lambda fraction, text: seen.append(fraction))
        self.assertTrue(seen and seen[-1] == 1.0)


if __name__ == "__main__":
    unittest.main()
