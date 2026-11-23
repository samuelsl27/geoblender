# SPDX-License-Identifier: GPL-3.0-or-later
"""Las polilíneas adaptadas a la banda de la rampa (spec 018, T21c2; HU-018-4; RF-018-21 y 28; CE-018-05 y 11).

La disposición plana quita de cada pie y cada cresta lo que cae bajo la banda, la corta en su borde, no deja cruces con los bordes de la banda y no modifica nada; la superficie
de la espiral de CE-018-05 se triangula sin que se rechace nada y la rampa manda con su Z dentro de su banda."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np

from tests.support import pit_data as pd
from tests.support.package import import_geoblender
from tests.unit.design import test_pit_bench_ramp as rp

pit_band = import_geoblender("design.pit_band")
pit_bench = import_geoblender("design.pit_bench")
pit_surface = import_geoblender("design.pit_surface")


def band_of(x0: float, x1: float, y: float, half: float, z0: float = 0.0, z1: float = 0.0, n: int = 11) -> object:
    x = np.linspace(x0, x1, n)
    z = np.linspace(z0, z1, n)
    lines = tuple(np.column_stack([x, np.full(n, y + off), z]) for off in (half, 0.0, -half))
    return SimpleNamespace(breaklines=lines)


def square(side: float = 100.0, z: float = 5.0) -> object:
    return SimpleNamespace(vertices=np.array([[0.0, 0, z], [side, 0, z], [side, side, z], [0, side, z]]), closed=True)


class ArrangeTest(unittest.TestCase):
    def test_without_bands_nothing_changes(self) -> None:
        ring = square()
        out = pit_band.arrange([ring], [])
        self.assertEqual(len(out), 1)
        self.assertTrue(np.array_equal(out[0].vertices, ring.vertices))
        self.assertTrue(out[0].closed)

    def test_band_far_away_keeps_the_ring_closed(self) -> None:
        out = pit_band.arrange([square()], [band_of(200.0, 220.0, 50.0, 3.0)])
        self.assertEqual((len(out), out[0].closed), (1, True))

    def test_band_across_a_side_cuts_it_at_the_margin_with_the_z_of_the_ring(self) -> None:
        """Una banda que cruza el lado inferior (sin vértices dentro) lo corta en dos trozos abiertos, a ``margin`` del borde de la banda."""
        ring = square(z=7.0)
        out = pit_band.arrange([ring], [band_of(40.0, 60.0, 0.0, 3.0, 1.0, 2.0)])
        self.assertEqual(len(out), 1)
        self.assertFalse(out[0].closed)
        v = out[0].vertices
        ends = v[[0, -1]]
        self.assertTrue(np.allclose(ends[:, 2], 7.0))
        self.assertTrue(np.allclose(np.sort(ends[:, 0]), [40.0 - 0.05, 60.0 + 0.05]) or np.allclose(np.sort(ends[:, 0]), [60.0 + 0.05, 40.0 - 0.05]))
        self.assertTrue(np.allclose(ends[:, 1], 0.0))

    def test_no_piece_crosses_the_band_lines_and_inputs_are_untouched(self) -> None:
        ring = square()
        before = ring.vertices.copy()
        band = band_of(-10.0, 50.0, 0.0, 4.0, 5.0, 8.0)
        out = pit_band.arrange([ring], [band])
        self.assertTrue(np.array_equal(before, ring.vertices))
        polygon = pit_band.band_polygon(band)
        mids = np.vstack([0.5 * (p.vertices[:-1, :2] + p.vertices[1:, :2]) for p in out])
        self.assertFalse(bool(pit_band._inside(mids, polygon).any()))

    def test_deterministic(self) -> None:
        a = pit_band.arrange([square()], [band_of(-10.0, 50.0, 0.0, 4.0)])
        b = pit_band.arrange([square()], [band_of(-10.0, 50.0, 0.0, 4.0)])
        self.assertTrue(all(np.array_equal(x.vertices, y.vertices) for x, y in zip(a, b, strict=True)))


class SpiralSurfaceTest(unittest.TestCase):
    """CE-018-05 y 11: la superficie de la espiral sin que la triangulación rechace nada."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.job = rp.spiral_job()
        cls.found = pit_bench.ascend(cls.job)
        cls.result = pit_surface.rasterize(cls.job, cls.found, cls.found.ramps, crs=pd.CRS, vertical=pd.VERTICAL)

    def test_arranged_lines_do_not_cross_the_band(self) -> None:
        band = self.found.ramps[0].band
        pieces = pit_band.arrange(self.found.polylines, [band])
        polygon = pit_band.band_polygon(band)
        mids = np.vstack([0.5 * (p.vertices[:-1, :2] + p.vertices[1:, :2]) for p in pieces])
        self.assertFalse(bool(pit_band._inside(mids, polygon).any()))
        self.assertGreater(len(pieces), len(self.found.polylines))

    def test_volume_by_bench_adds_up(self) -> None:
        self.assertGreater(self.result.cut_m3, 0.0)
        self.assertAlmostEqual(float(self.result.bench_m3.sum()), self.result.cut_m3, delta=1e-6 * self.result.cut_m3)
        self.assertGreaterEqual(len(self.result.bench_m3), 5)

    def test_ramp_rules_inside_its_band(self) -> None:
        """La superficie en el eje de la rampa sigue su Z (a ± media celda de pendiente)."""
        checked = self.found.ramps[0]
        grid = self.job.grid
        axis = checked.band.axis
        col = np.floor((axis[:, 0] - grid.west) / grid.dx).astype(int)
        row = np.floor((grid.north - axis[:, 1]) / grid.dy).astype(int)
        value = self.result.surface[row, col]
        good = np.isfinite(value)
        self.assertTrue(bool(good.all()))
        error = np.abs(value - axis[:, 2])
        self.assertLess(float(np.median(error)), 0.3)

    def test_deterministic(self) -> None:
        again = pit_surface.rasterize(self.job, self.found, self.found.ramps, crs=pd.CRS, vertical=pd.VERTICAL)
        self.assertTrue(np.array_equal(self.result.surface, again.surface, equal_nan=True))


class ZigzagSurfaceTest(unittest.TestCase):
    """CE-018-06 y 11: la superficie del zig-zag de cinco bancos, también sin rechazos de la triangulación."""

    def test_surface_and_volume_by_bench(self) -> None:
        job = rp.zigzag_job()
        found = pit_bench.ascend(job)
        result = pit_surface.rasterize(job, found, found.ramps, crs=pd.CRS, vertical=pd.VERTICAL)
        self.assertGreater(result.cut_m3, 0.0)
        self.assertAlmostEqual(float(result.bench_m3.sum()), result.cut_m3, delta=1e-6 * result.cut_m3)
        pieces = pit_band.arrange(found.polylines, [found.ramps[0].band])
        polygon = pit_band.band_polygon(found.ramps[0].band)
        mids = np.vstack([0.5 * (p.vertices[:-1, :2] + p.vertices[1:, :2]) for p in pieces])
        self.assertFalse(bool(pit_band._inside(mids, polygon).any()))


if __name__ == "__main__":
    unittest.main()
