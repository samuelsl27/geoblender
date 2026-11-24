# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que la medida a escala de la T36 hizo cambiar en el código de la corta (spec 018, T36; RF-018-13, RF-018-26, RF-018-35; RNF-018-05 y RNF-018-06).

- **El ancho de fondo de una descendente que se colapsa** (RF-018-13): un círculo de 720 vértices con 1 mm de arco **no** se cuelga minutos en el desfase de ``_fits`` ni de ``_useful_width``.
- **Las distancias de berma** (RF-018-26): la distancia mínima entre dos anillos que da ``pit_report._nearest_units`` (con descarte por cajas) es la de fuerza bruta, con el mismo vértice.
- **La línea de cielo por pasos** (RF-018-35): ``skyline_steps`` cede el hilo varias veces y da lo mismo que ``skyline``; ``contours_from_raster_steps``, lo mismo que ``contours_from_raster``.

Sin proyecto y sin Blender; mallas pequeñas."""

from __future__ import annotations

import math
import time
import unittest

import numpy as np

from tests.support import pit_data as pd
from tests.support.package import import_geoblender
from tests.unit.design import milestone_pit_h1 as h1

pit_bench = import_geoblender("design.pit_bench")
pit_model = import_geoblender("design.pit_model")
pit_report = import_geoblender("design.pit_report")
pit_sky = import_geoblender("design.pit_sky")
contours = import_geoblender("gis.contours")
raster_mod = import_geoblender("gis.raster")


class CollapsingCircleTest(unittest.TestCase):
    def test_a_collapsing_circle_does_not_hang_in_the_floor_width(self) -> None:
        """RF-018-13: la descendente de un círculo de 60 m de 720 vértices con arco de 1 mm termina en unos segundos (con el desfase de ancho de fondo se colgaba minutos), con 3 bancos y el ancho de
        fondo de la última planta (≈ el diámetro de su círculo)."""
        grid = pd.GRID
        started = time.perf_counter()
        job = h1.down_job(grid, start=pd.limit_terrain(grid), sources=(pit_model.PitSource("limite", pd.absolute(pd.circle_ring(60.0, 720), grid), None),),
                          params=pit_model.PitParams(arc_tol_m=0.001, simplify_m=1e-6, min_floor_width_m=pd.MIN_FLOOR_WIDTH_M))
        found = pit_bench.descend(job)
        self.assertLess(time.perf_counter() - started, 20.0)
        self.assertEqual((found.count, found.stop), (3, pit_model.StopCriterion.FLOOR_WIDTH))
        self.assertAlmostEqual(found.floor_width_m, 36.0, delta=0.3)  # el pie del banco 3, de 18 m de radio (60 − 3·(10 + 6) + 6)
        self.assertGreater(found.floor_width_m, pd.MIN_FLOOR_WIDTH_M)


def brute_nearest(points: np.ndarray, line: np.ndarray, closed: bool) -> tuple[float, int]:
    """La distancia mínima en planta de ``points`` a las aristas de ``line`` y el índice (el menor) del punto que la da, de fuerza bruta."""
    a = line[:, :2]
    b = np.roll(a, -1, axis=0) if closed else a[1:]
    a = a if closed else a[:-1]
    delta = b - a
    length2 = (delta ** 2).sum(axis=1)
    p = points[:, None, :]
    t = np.clip(np.where(length2 > 0.0, ((p - a[None]) * delta).sum(axis=2) / length2, 0.0), 0.0, 1.0)
    distance = np.hypot(*(p - (a[None] + t[:, :, None] * delta[None])).transpose(2, 0, 1)).min(axis=1)
    index = int(np.argmin(distance))
    return float(distance[index]), index


class NearestTest(unittest.TestCase):
    def test_pruned_nearest_equals_brute_force(self) -> None:
        """RF-018-26: la menor distancia entre dos anillos (concéntricos, rugosos o desplazados) y el vértice que la da son los de fuerza bruta, bit a bit, con anillos de miles de vértices."""
        cases = []
        for seed, noise, shift in ((1, 0.0, 0.0), (2, 0.4, 0.0), (3, 0.3, 7.0)):
            inner = pd.rough_ring(seed, 1700, noise, 50.0)
            outer = pd.rough_ring(seed + 10, 1800, noise, 58.0) + shift
            cases.append((inner, outer))
        cases.append((pd.circle_ring(10.0, 1500), pd.circle_ring(10.0, 1500)))  # empates: el mismo radio
        cases.append((pd.rough_ring(5, 1500, 0.2, 20.0), pd.rough_ring(6, 1600, 0.2, 90.0)))
        cases.append((pd.rough_ring(8, 400, 0.2, 40.0), pd.rough_ring(9, 500, 0.2, 46.0)))  # lejos
        for inner, outer in cases:
            for first, second in ((inner, outer), (outer, inner)):
                with self.subTest(a=len(first), b=len(second)):
                    got = pit_report._nearest(first, second, True)
                    self.assertEqual(got, brute_nearest(first, second, True))
        line = pd.rough_ring(9, 300, 0.2, 30.0)
        self.assertEqual(pit_report._nearest(line[:100], line[100:], False), brute_nearest(line[:100], line[100:], False))


def slope_grid() -> tuple[object, np.ndarray, np.ndarray]:
    grid = pd.grid_of(2.0)
    start = pd.flat_terrain(grid)
    job = h1.up_job(grid)
    found = pit_bench.ascend(job)
    from tests.unit.design.test_pit_report import surface_of
    _found, surface = surface_of(job)
    return grid, start, surface.stepped


class SkylineStepsTest(unittest.TestCase):
    def test_contours_by_steps_equal_the_direct_ones_and_yield(self) -> None:
        """RF-018-35: ``contours_from_raster_steps`` cede el hilo por bloques (varias veces en una malla de 200 × 200 con bloques pequeños) y da las mismas curvas que ``contours_from_raster``."""
        grid = pd.grid_of(2.0)
        x, y = pd.local_centers(grid)
        values = 100.0 + 0.05 * (x - 200.0) ** 2 / 10.0 + 0.02 * y
        raster = raster_mod.Raster(grid, values, pd.CRS, pd.VERTICAL)
        direct = contours.contours_from_raster(raster, interval_m=1.0, simplify_m=0.0, min_length_m=0.0, name="x")
        work = contours.contours_from_raster_steps(raster, interval_m=1.0, simplify_m=0.0, min_length_m=0.0, name="x")
        yields = 0
        while True:
            try:
                next(work)
                yields += 1
            except StopIteration as done:
                stepped = done.value
                break
        self.assertGreaterEqual(yields, 1)
        self.assertEqual(len(stepped), len(direct))
        for one, other in zip(stepped, direct, strict=True):
            self.assertTrue(np.array_equal(one.xyz, other.xyz))
            self.assertEqual((one.closed, one.elevation), (other.closed, other.elevation))

    def test_skyline_steps_equal_the_direct_skyline_and_yield(self) -> None:
        """RF-018-35: ``skyline_steps`` cede el hilo al menos tres veces (la diferencia, las curvas y las cifras) y da la misma línea de cielo que ``skyline``: partes, longitudes y área."""
        grid, start, design = slope_grid()
        direct = pit_sky.skyline(start, design, grid, crs=pd.CRS, vertical=pd.VERTICAL)
        work = pit_sky.skyline_steps(start, design, grid, crs=pd.CRS, vertical=pd.VERTICAL)
        yields = 0
        while True:
            try:
                next(work)
                yields += 1
            except StopIteration as done:
                stepped = done.value
                break
        self.assertGreaterEqual(yields, 3)
        self.assertGreater(direct.n_parts, 0)
        self.assertEqual((stepped.n_parts, stepped.length_m, stepped.length3d_m, stepped.area_m2), (direct.n_parts, direct.length_m, direct.length3d_m, direct.area_m2))
        for one, other in zip(stepped.parts, direct.parts, strict=True):
            self.assertTrue(np.array_equal(one.xyz, other.xyz))


if __name__ == "__main__":
    unittest.main()
