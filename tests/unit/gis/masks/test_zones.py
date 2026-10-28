# SPDX-License-Identifier: GPL-3.0-or-later
"""Las zonas de las restricciones en la rejilla (spec 012, T08; RF-012-11, RF-012-12; CE-012-01;
plan 012 A1, A2, D-1, D-19 y D-37).

- **RF-012-12 (D-1)**: una celda está en la zona de una geometría si alguna parte de su área queda
  a una distancia < r − τ (τ = 10⁻⁹ m) de ella, y dentro de un límite solo si está entera dentro.
  :func:`gis.masks.zones.near_runs` (A1, por intervalos de fila de la cápsula) se compara con una
  **fuerza bruta** propia (cada celda × cada segmento, la distancia exacta caja–segmento) en 600
  casos aleatorios de 60 × 60 celdas: segmentos generales, horizontales, verticales, puntos,
  coordenadas enteras y medias y celdas no cuadradas; ninguna diferencia.
- **RF-012-11, RF-012-12 (A2)**: un polígono menor que una celda ocupa las celdas que toca; un
  límite alineado con la rejilla no mete las celdas que solo lo tocan; la banda hacia dentro; por
  trozos de segmentos y de filas, lo mismo que de una vez; los tramos (:class:`Runs`) y sus
  operaciones frente a máscaras de celdas.
"""

import unittest
from datetime import date

import numpy as np

from tests.support import constraints_fixtures as fx
from tests.support.package import import_geoblender
from tests.unit.core.constraints.test_fixtures import segment_box_distance

gis = import_geoblender("gis")
model = import_geoblender("core.constraints.model")
zones = import_geoblender("gis.masks.zones")

TAU = 1e-9  # D-1, D-37 (m)
CASES = 600
G = model.GeometryKind


def constraint(kind, parts):
    """Una restricción mínima con su geometría (lo demás no lo miran las zonas)."""
    return model.Constraint(
        uid="u" * 32, code="r_zona", name="Zona", ctype=model.ConstraintType.UNTOUCHABLE,
        kind=kind, parts=parts, priority=1, reason=None, decided_by=None,
        decided_on=date(2026, 10, 28),
        decision_uid=None, intention_uid=None, source_input=None, source_fid=None,
        layer="core_constraint_polygon", fid=1)


def mask_of(runs, grid) -> np.ndarray:
    return runs.mask((grid.nrows, grid.ncols))


# Fuerza bruta (en metros relativos a la esquina suroeste) ---------------------------------------


def brute_near(segments: np.ndarray, radius: float, grid) -> np.ndarray:
    """Las celdas a distancia < r − τ de algún segmento: cada celda × cada segmento, con la
    distancia exacta caja–segmento de la T02 (0 si se tocan, por Liang–Barsky; si no, el mínimo
    de los extremos a la caja y de las esquinas al segmento). Solo se miden las celdas de la caja
    del segmento ampliada en r y una celda: las demás están a ≥ r."""
    near = np.zeros((grid.nrows, grid.ncols), dtype=bool)
    for a, b in segments:
        low = np.minimum(a, b) - radius
        high = np.maximum(a, b) + radius
        cols = np.arange(max(int(low[0] // grid.dx) - 1, 0),
                         min(int(high[0] // grid.dx) + 2, grid.ncols))
        souths = np.arange(max(int(low[1] // grid.dy) - 1, 0),
                           min(int(high[1] // grid.dy) + 2, grid.nrows))
        if cols.size == 0 or souths.size == 0:
            continue
        left, bottom = np.meshgrid(cols * grid.dx, souths * grid.dy)
        distance = segment_box_distance(a, b, left, bottom, left + grid.dx, bottom + grid.dy)
        rows = grid.nrows - 1 - souths
        near[rows[:, None], cols[None, :]] |= distance < radius - TAU
    return near


def _random_segments(rng, width: float, height: float, kind: int) -> np.ndarray:
    n = int(rng.integers(1, 6))
    span = np.array([width, height])
    if kind == 0:  # coordenadas enteras y medias: bordes y esquinas exactos
        points = rng.integers(-4, int(min(width, height)) * 2 + 8, size=(n, 2, 2)) / 2.0
        return np.minimum(points, span + 4.0)
    if kind == 1:  # horizontales
        points = rng.uniform([-5.0, -5.0], span + 5.0, size=(n, 2, 2))
        points[:, 1, 1] = points[:, 0, 1]
        return points
    if kind == 2:  # verticales, con medias celdas
        points = rng.uniform([-5.0, -5.0], span + 5.0, size=(n, 2, 2))
        points[:, 1, 0] = np.round(points[:, 0, 0] * 2.0) / 2.0
        points[:, 0, 0] = points[:, 1, 0]
        return points
    if kind == 3:  # puntos
        points = rng.uniform([-3.0, -3.0], span + 3.0, size=(n, 1, 2))
        return points.repeat(2, axis=1)
    return rng.uniform([-8.0, -8.0], span + 8.0, size=(n, 2, 2))  # generales


class NearRunsBruteForceTest(unittest.TestCase):
    """RF-012-12 (D-1; A1): la regla por intervalos de fila frente a la fuerza bruta."""

    STEPS = ((1.0, 1.0), (2.0, 2.0), (1.0, 2.0), (1.5, 0.5), (0.5, 1.25))

    def test_random_cases_equal_brute_force(self) -> None:
        rng = np.random.default_rng(20261028)
        differences = []
        for case in range(CASES):
            dx, dy = self.STEPS[case % len(self.STEPS)]
            grid = gis.Grid(500_000.0, 4_400_000.0 + 60 * dy, dx, dy, 60, 60)
            kind = case % 5
            segments = _random_segments(rng, 60 * dx, 60 * dy, kind)
            radius = float(rng.choice([0.5, 1.0, 2.5, 3.0, rng.uniform(0.1, 12.0)]))
            fast = mask_of(zones.near_runs(segments, radius, grid), grid)
            slow = brute_near(segments, radius, grid)
            if not np.array_equal(fast, slow):
                differences.append((case, kind, radius, int(fast.sum()), int(slow.sum())))
        self.assertEqual(differences, [])

    def test_touching_at_exactly_the_radius_does_not_count(self) -> None:
        grid = gis.Grid(500_000.0, 4_400_020.0, 1.0, 1.0, 20, 20)
        point = np.array([[[10.0, 10.0], [10.0, 10.0]]])
        runs = zones.near_runs(point, 3.0, grid)
        mask = mask_of(runs, grid)
        # Celdas de 7 a 12 en x (la de 13 está a 3 m justos: no entra).
        self.assertTrue(mask[grid.nrows - 1 - 10, 12])
        self.assertFalse(mask[grid.nrows - 1 - 10, 13])
        self.assertFalse(mask[grid.nrows - 1 - 10, 6])
        self.assertTrue(np.array_equal(mask, brute_near(point, 3.0, grid)))

    def test_no_radius_no_cells(self) -> None:
        grid = gis.Grid(500_000.0, 4_400_020.0, 1.0, 1.0, 20, 20)
        segment = np.array([[[2.0, 2.0], [15.0, 8.0]]])
        self.assertEqual(zones.near_runs(segment, 0.0, grid).cells, 0)
        self.assertEqual(zones.near_runs(segment, TAU / 2, grid).cells, 0)
        self.assertEqual(zones.near_runs(np.zeros((0, 2, 2)), 5.0, grid).cells, 0)

    def test_bad_segments(self) -> None:
        grid = gis.Grid(500_000.0, 4_400_020.0, 1.0, 1.0, 20, 20)
        with self.assertRaises(ValueError):
            zones.near_runs(np.zeros((3, 2)), 1.0, grid)
        with self.assertRaises(ValueError):
            zones.near_runs(np.array([[[np.nan, 0.0], [1.0, 1.0]]]), 1.0, grid)


class ZonesTest(unittest.TestCase):
    """RF-012-11, RF-012-12 (A2): polígonos, líneas, puntos y límites."""

    def setUp(self) -> None:
        self.grid = fx.mask_grid(1.0)

    def test_segments_of_each_kind(self) -> None:
        grid = self.grid
        corner = np.array([grid.west, grid.extent.ymin])
        point = constraint(G.POINT, ((fx.absolute([(70.0, 70.0)]),),))
        self.assertTrue(np.array_equal(zones.segments_of(point, grid),
                                       [[[70.0, 70.0], [70.0, 70.0]]]))
        path = fx.absolute([(20.0, 70.0), (120.0, 70.0), (120.0, 90.0)])
        line = constraint(G.LINE, ((path,),))
        self.assertTrue(np.array_equal(zones.segments_of(line, grid),
                                       [[[20.0, 70.0], [120.0, 70.0]],
                                        [[120.0, 70.0], [120.0, 90.0]]]))
        square = constraint(G.POLYGON, ((fx.rectangle(20.0, 20.0, 120.0, 120.0),),))
        edges = zones.segments_of(square, grid)
        self.assertEqual(edges.shape, (4, 2, 2))
        self.assertEqual(edges.dtype, np.float64)
        self.assertEqual(float(edges.min()), 20.0)
        self.assertTrue(np.array_equal(corner, [fx.BASE[0], fx.BASE[1]]))
        with self.assertRaises(ValueError):
            zones.edges_of(line, grid)

    def test_polygon_smaller_than_a_cell_takes_the_cells_it_touches(self) -> None:
        grid = self.grid
        inside_one = constraint(G.POLYGON, ((fx.rectangle(50.2, 60.2, 50.7, 60.6),),))
        across_four = constraint(G.POLYGON, ((fx.rectangle(49.8, 59.7, 50.3, 60.4),),))
        for item, cells in ((inside_one, 1), (across_four, 4)):
            runs = zones.zone_runs(item, grid, 0.0)
            self.assertEqual(runs.cells, cells)
            area = zones.area_inside(zones.edges_of(item, grid), grid)
            exact = fx.ring_area(item.parts[0][0])   # 0,2 y 0,35 m² salvo el redondeo de las absolutas
            self.assertAlmostEqual(exact, 0.2 if cells == 1 else 0.35, delta=1e-9)
            self.assertLessEqual(abs(area - exact), 1e-9 * exact)
        mask = mask_of(zones.zone_runs(inside_one, grid, 0.0), grid)
        self.assertTrue(mask[grid.nrows - 1 - 60, 50])

    def test_aligned_limit_does_not_take_the_touching_cells(self) -> None:
        grid = self.grid
        square = constraint(G.POLYGON, ((fx.rectangle(20.0, 20.0, 120.0, 120.0),),))
        zone = zones.zone_runs(square, grid, 0.0)
        self.assertEqual(zone.cells, 10_000)
        limit = zones.limit_runs(zones.edges_of(square, grid), grid, 0.0)
        self.assertEqual(limit.inside.cells, 10_000)
        self.assertEqual(limit.band.cells, 0)
        self.assertEqual(limit.core.cells, 10_000)
        mask = mask_of(limit.inside, grid)
        self.assertTrue(mask[grid.nrows - 1 - 20, 20])
        self.assertFalse(mask[grid.nrows - 1 - 19, 20])
        self.assertFalse(mask[grid.nrows - 1 - 20, 120])

    def test_shifted_limit_takes_only_whole_cells(self) -> None:
        grid = self.grid
        square = constraint(G.POLYGON, ((fx.rectangle(20.5, 20.5, 120.5, 120.5),),))
        limit = zones.limit_runs(zones.edges_of(square, grid), grid, 10.0)
        self.assertEqual(limit.inside.cells, 99 * 99)
        self.assertEqual(zones.zone_runs(square, grid, 0.0).cells, 101 * 101)
        # Banda: las celdas enteras dentro a < 10 m del borde, 10 por lado (21–30, 110–119).
        self.assertEqual(limit.core.cells, 79 * 79)

    def test_line_and_point_need_a_radius(self) -> None:
        point = constraint(G.POINT, ((fx.absolute([(70.0, 70.0)]),),))
        with self.assertRaises(ValueError):
            zones.zone_runs(point, self.grid, 0.0)

    def test_by_pieces_equals_at_once(self) -> None:
        grid = fx.mask_grid(1.0)
        rng = np.random.default_rng(7)
        ring = fx.absolute(np.vstack([np.column_stack([
            70.0 + 40.0 * np.cos(a) * (1.0 + 0.2 * rng.uniform(size=a.size)),
            70.0 + 35.0 * np.sin(a)]) for a in [np.linspace(0.0, 2 * np.pi, 41)[:-1]]]))
        hole = fx.rectangle(60.0, 60.0, 75.5, 80.25)[::-1]
        polygon = constraint(G.POLYGON, ((ring, hole),))
        once = zones.zone_runs(polygon, grid, 6.5)
        steps = zones.zone_steps(polygon, grid, 6.5, segments_per_step=3, rows_per_step=7)
        count = 0
        while True:
            try:
                next(steps)
                count += 1
            except StopIteration as stop:
                pieces = stop.value
                break
        self.assertGreater(count, 20)
        self.assertEqual(pieces, once)
        edges = zones.edges_of(polygon, grid)
        limit_once = zones.limit_runs(edges, grid, 4.25)
        limit_pieces = zones.limit_runs(edges, grid, 4.25, segments_per_step=2,
                                        rows_per_step=5)
        self.assertEqual(limit_pieces, limit_once)
        self.assertGreater(limit_once.band.cells, 0)
        bands = [zones.near_runs(edges, 6.5, grid, rows=slice(start, start + 11))
                 for start in range(0, grid.nrows, 11)]
        self.assertEqual(zones.Runs.union_all(bands), zones.near_runs(edges, 6.5, grid))
        area = sum(zones.area_inside(edges, grid, rows=slice(start, start + 9))
                   for start in range(0, grid.nrows, 9))
        self.assertAlmostEqual(area, zones.area_inside(edges, grid), delta=1e-9)


class RunsTest(unittest.TestCase):
    """Los tramos de fila (A1, A2) frente a las máscaras de celdas."""

    def test_operations_match_masks(self) -> None:
        rng = np.random.default_rng(11)
        for _ in range(40):
            first = rng.uniform(size=(13, 17)) < 0.4
            second = rng.uniform(size=(13, 17)) < 0.5
            a = zones.Runs.from_mask(first)
            b = zones.Runs.from_mask(second)
            self.assertTrue(np.array_equal(a.mask(first.shape), first))
            self.assertEqual(a.cells, int(first.sum()))
            self.assertTrue(np.array_equal(a.union(b).mask(first.shape), first | second))
            self.assertTrue(np.array_equal(a.intersection(b).mask(first.shape),
                                           first & second))
            self.assertTrue(np.array_equal(a.difference(b).mask(first.shape),
                                           first & ~second))
            self.assertEqual(a.union(b), zones.Runs.from_mask(first | second))

    def test_normalized_and_area(self) -> None:
        runs = zones.Runs(np.array([2, 0, 2, 2]), np.array([5, 1, 0, 3]), np.array([8, 4, 3, 4]))
        self.assertEqual(runs.row.tolist(), [0, 2, 2])
        self.assertEqual(runs.col0.tolist(), [1, 0, 5])
        self.assertEqual(runs.col1.tolist(), [4, 4, 8])
        self.assertEqual(runs.cells, 10)
        grid = gis.Grid(0.0, 10.0, 1.5, 0.5, 10, 10)
        self.assertEqual(runs.area(grid), 10 * 0.75)
        window = runs.mask((2, 4), offset=(1, 2))
        self.assertEqual(window.tolist(), [[False] * 4, [True, True, False, True]])
        self.assertEqual(zones.Runs.empty().cells, 0)
        with self.assertRaises(ValueError):
            zones.Runs(np.array([0]), np.array([3]), np.array([2]))


if __name__ == "__main__":
    unittest.main()
