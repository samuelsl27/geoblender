# SPDX-License-Identifier: GPL-3.0-or-later
"""El desfase de la 018, segunda mitad: cruces propios, regla de la vuelta, encadenado y
verificación (spec 018, T07; RF-018-10; plan 018 §5.4 A4 y trampas T-1 y T-2; CE-018-01 y 02).

El oráculo de las pruebas es independiente del motor: la distancia de cada vértice a todas las
aristas de la fuente, la simplicidad por fuerza bruta y el área por una rejilla de puntos con la
definición «a ≤ d de la fuente» (fuera) o «dentro y a ≥ d» (dentro)."""

from __future__ import annotations

import math
import time
import unittest

import numpy as np

from tests.support.package import import_geoblender

offset = import_geoblender("gis.offset")

TOL = 0.01


def _poly(*points: tuple[float, float]) -> np.ndarray:
    return np.array(points, dtype=np.float64)


L_SHAPE = _poly((0, 0), (40, 0), (40, 20), (20, 20), (20, 40), (0, 40))
DUMBBELL = _poly((0, 0), (30, 0), (30, 13), (50, 13), (50, 0), (80, 0), (80, 30), (50, 30),
                 (50, 17), (30, 17), (30, 30), (0, 30))
C_SHAPE = _poly((0, 0), (40, 0), (40, 18), (30, 18), (30, 10), (10, 10), (10, 30), (30, 30),
                (30, 22), (40, 22), (40, 40), (0, 40))


def _distance(points: np.ndarray, ring: np.ndarray) -> np.ndarray:
    a, b = ring, np.roll(ring, -1, axis=0)
    d = b - a
    w = points[:, None, :] - a[None, :, :]
    t = np.clip(np.einsum("pej,ej->pe", w, d) / np.einsum("ej,ej->e", d, d), 0.0, 1.0)
    rest = w - t[:, :, None] * d[None, :, :]
    return np.hypot(rest[..., 0], rest[..., 1]).min(axis=1)


def _inside(points: np.ndarray, ring: np.ndarray) -> np.ndarray:
    x, y = points[:, 0][:, None], points[:, 1][:, None]
    ax, ay = ring[:, 0][None, :], ring[:, 1][None, :]
    bx, by = np.roll(ring[:, 0], -1)[None, :], np.roll(ring[:, 1], -1)[None, :]
    spans = (ay > y) != (by > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        hit = x < ax + (y - ay) * (bx - ax) / (by - ay)
    return (np.sum(spans & hit, axis=1) % 2) == 1


def _area(ring: np.ndarray) -> float:
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def _grid_area(source: np.ndarray, d: float, side: int, cell: float = 0.2) -> float:
    """El área de {a ≤ d de la fuente} (fuera) o {dentro y a ≥ d} (dentro) por una rejilla."""
    low, high = source.min(axis=0) - (d + 1.0), source.max(axis=0) + (d + 1.0)
    xs = np.arange(low[0] + cell / 2, high[0], cell)
    ys = np.arange(low[1] + cell / 2, high[1], cell)
    total = 0
    for y in ys:
        pts = np.column_stack([xs, np.full_like(xs, y)])
        inside = _inside(pts, source)
        dist = _distance(pts, source)
        total += int(np.sum(inside | (dist <= d))) if side > 0 else int(np.sum(inside & (dist >= d)))
    return total * cell * cell


def _simple(ring: np.ndarray) -> bool:
    """Fuerza bruta (todos los pares, por filas): ningún par de aristas no contiguas se cruza."""
    n = len(ring)
    a, b = ring, np.roll(ring, -1, axis=0)
    for i in range(n):
        j = np.arange(i + 2, n if i > 0 else n - 1)
        if not j.size:
            continue
        d = b[i] - a[i]
        o1 = d[0] * (a[j, 1] - a[i, 1]) - d[1] * (a[j, 0] - a[i, 0])
        o2 = d[0] * (b[j, 1] - a[i, 1]) - d[1] * (b[j, 0] - a[i, 0])
        e = b[j] - a[j]
        o3 = e[:, 0] * (a[i, 1] - a[j, 1]) - e[:, 1] * (a[i, 0] - a[j, 0])
        o4 = e[:, 0] * (b[i, 1] - a[j, 1]) - e[:, 1] * (b[i, 0] - a[j, 0])
        if np.any((o1 * o2 < -1e-12) & (o3 * o4 < -1e-12)):
            return False
    return True


def _oracle(test: unittest.TestCase, result: object, source: np.ndarray, d: float) -> None:
    """Cada vértice a ≥ d − tol de todas las aristas de la fuente, y cada anillo, simple."""
    loops = list(result.rings) + list(result.holes)
    for loop in loops:
        test.assertTrue(_simple(loop))
        test.assertGreaterEqual(float(_distance(loop, source).min()), d - TOL - 1e-9)


class OffsetRingTest(unittest.TestCase):
    """RF-018-10, plan §5.4 A4."""

    def test_reflex_corner_loops_are_removed(self) -> None:
        result = offset.offset_ring(L_SHAPE, 3.0, 1, tol=TOL)
        self.assertTrue(result.verified)
        self.assertEqual((len(result.rings), len(result.holes)), (1, 0))
        _oracle(self, result, L_SHAPE, 3.0)
        expected = _grid_area(L_SHAPE, 3.0, 1)
        self.assertAlmostEqual(_area(result.rings[0]), expected, delta=0.004 * expected)
        self.assertGreater(_area(result.rings[0]), expected - 0.004 * expected)

    def test_inward_offset_of_concave_ring(self) -> None:
        result = offset.offset_ring(L_SHAPE, 3.0, -1, tol=TOL)
        self.assertTrue(result.verified)
        self.assertEqual(len(result.rings), 1)
        _oracle(self, result, L_SHAPE, 3.0)
        expected = _grid_area(L_SHAPE, 3.0, -1)
        self.assertAlmostEqual(_area(result.rings[0]), expected, delta=0.004 * expected)

    def test_a_polyline_that_splits_in_two(self) -> None:
        result = offset.offset_ring(DUMBBELL, 3.0, -1, tol=TOL)
        self.assertTrue(result.verified)
        self.assertEqual((len(result.rings), len(result.holes)), (2, 0))
        _oracle(self, result, DUMBBELL, 3.0)
        total = sum(_area(r) for r in result.rings)
        expected = _grid_area(DUMBBELL, 3.0, -1)
        self.assertAlmostEqual(total, expected, delta=0.004 * expected)

    def test_a_hole_when_the_mouth_closes(self) -> None:
        result = offset.offset_ring(C_SHAPE, 3.0, 1, tol=TOL)
        self.assertTrue(result.verified)
        self.assertEqual((len(result.rings), len(result.holes)), (1, 1))
        self.assertGreater(_area(result.rings[0]), 0.0)
        self.assertLess(_area(result.holes[0]), 0.0)
        _oracle(self, result, C_SHAPE, 3.0)
        net = _area(result.rings[0]) + _area(result.holes[0])
        expected = _grid_area(C_SHAPE, 3.0, 1)
        self.assertAlmostEqual(net, expected, delta=0.004 * expected)

    def test_inward_offset_that_vanishes_is_empty_and_verified(self) -> None:
        result = offset.offset_ring(L_SHAPE, 30.0, -1, tol=TOL)
        self.assertTrue(result.verified)
        self.assertEqual((len(result.rings), len(result.holes)), (0, 0))

    def test_square_with_arcs_matches_ce_018_01(self) -> None:
        d = 10.0 / math.tan(math.radians(60.0))
        square = _poly((0, 0), (100, 0), (100, 100), (0, 100))
        result = offset.offset_ring(square, d, 1, tol=TOL)
        self.assertTrue(result.verified)
        exact = 100.0 ** 2 + 400.0 * d + math.pi * d * d
        self.assertGreaterEqual(_area(result.rings[0]), exact - 1e-9)
        self.assertLessEqual(_area(result.rings[0]) - exact, 400.0 * TOL + 4 * d * TOL)

    def test_distance_per_edge_steps_up(self) -> None:
        square = _poly((0, 0), (100, 0), (100, 100), (0, 100))
        dist = np.array([5.0, 5.0, 8.0, 8.0])
        result = offset.offset_ring(square, dist, 1, tol=TOL)
        self.assertTrue(result.verified)
        self.assertEqual(len(result.rings), 1)
        ring = result.rings[0]
        # Cada lado queda a su distancia (en las esquinas, el abanico tiene su propio radio).
        self.assertTrue(np.any(np.isclose(ring[:, 1], -5.0, atol=1e-9)))
        self.assertTrue(np.any(np.isclose(ring[:, 0], 105.0, atol=1e-9)))
        self.assertTrue(np.any(np.isclose(ring[:, 1], 108.0, atol=1e-9)))
        self.assertTrue(np.any(np.isclose(ring[:, 0], -8.0, atol=1e-9)))

    def test_source_edge_of_every_vertex(self) -> None:
        result = offset.offset_ring(L_SHAPE, 3.0, 1, tol=TOL)
        self.assertEqual(len(result.source_edge_of_vertex), 1)
        sources = result.source_edge_of_vertex[0]
        self.assertEqual(sources.shape, (len(result.rings[0]),))
        self.assertTrue(np.all((sources >= 0) & (sources < len(L_SHAPE))))
        # Un vértice del resultado está a la distancia (≈) de la arista de la que sale.
        # La arista de origen de un vértice está a ≥ d − tol de él (y todas lo están).
        a, b = L_SHAPE, np.roll(L_SHAPE, -1, axis=0)
        for vertex, edge in zip(result.rings[0], sources.tolist(), strict=True):
            d = b[edge] - a[edge]
            t = min(1.0, max(0.0, float((vertex - a[edge]) @ d / (d @ d))))
            near = float(np.hypot(*(vertex - (a[edge] + t * d))))
            self.assertGreaterEqual(near, 3.0 - TOL - 1e-9)
            self.assertLess(near, 3.0 + 3.0 * 0.5 + 10.0)

    def test_inputs_are_not_modified_and_validated(self) -> None:
        ring = L_SHAPE.copy()
        offset.offset_ring(ring, 3.0, 1, tol=TOL)
        self.assertTrue(np.array_equal(ring, L_SHAPE))
        with self.assertRaises(ValueError):
            offset.offset_ring(L_SHAPE[::-1], 3.0, 1, tol=TOL)
        with self.assertRaises(ValueError):
            offset.offset_ring_steps(L_SHAPE, 3.0, 1, tol=TOL, edges_per_step=0)


class NoisyRingTest(unittest.TestCase):
    """T-1 y T-2 del plan: los trozos de menos de 1 mm y los vértices que se multiplican."""

    @staticmethod
    def _noisy(count: int, radius: float, noise: float, seed: int) -> np.ndarray:
        rng = np.random.default_rng(seed)
        angle = np.linspace(0.0, 2.0 * math.pi, count, endpoint=False)
        r = radius + rng.uniform(-noise, noise, count)
        return np.column_stack([r * np.cos(angle), r * np.sin(angle)])

    def test_noisy_ring_is_one_simple_verified_ring(self) -> None:
        for seed in range(5):
            ring = self._noisy(500, 100.0, 0.6, seed)
            result = offset.offset_ring(ring, 5.0, 1, tol=TOL)
            self.assertTrue(result.verified, (seed, result.defect, result.defect_at))
            self.assertEqual((len(result.rings), len(result.holes)), (1, 0), seed)
            self.assertTrue(_simple(result.rings[0]))

    def test_vertices_do_not_double_in_successive_offsets(self) -> None:
        angle = np.linspace(0.0, 2.0 * math.pi, 720, endpoint=False)
        ring = np.column_stack([100.0 * np.cos(angle), 100.0 * np.sin(angle)])
        counts = []
        for _ in range(6):
            result = offset.offset_ring(ring, 5.0, 1, tol=TOL)
            ring = result.rings[0]
            counts.append(len(ring))
        self.assertLessEqual(max(counts), 720 + 40)

    def test_500_vertices_is_fast(self) -> None:
        """El objetivo (≤ 20 ms con 500 vértices, medido: 16 ms con ruido de 0,3 m) se mide sin
        carga; aquí solo una cota holgada, porque ``check.py`` corre las pruebas en paralelo."""
        ring = self._noisy(500, 100.0, 0.3, 7)
        best = math.inf
        for _ in range(7):
            start = time.perf_counter()
            offset.offset_ring(ring, 5.0, 1, tol=TOL)
            best = min(best, time.perf_counter() - start)
        self.assertLess(best, 0.100)


class StepsTest(unittest.TestCase):
    """Cede cada ≈ 2.000 aristas y se cancela."""

    @staticmethod
    def _circle(count: int) -> np.ndarray:
        angle = np.linspace(0.0, 2.0 * math.pi, count, endpoint=False)
        return np.column_stack([1000.0 * np.cos(angle), 1000.0 * np.sin(angle)])

    def test_yields_about_every_2000_edges(self) -> None:
        ring = self._circle(9000)
        steps = list(offset.offset_ring_steps(ring, 5.0, 1, tol=TOL))
        self.assertGreaterEqual(len(steps), 10)
        self.assertLessEqual(len(steps), 30)
        self.assertTrue(all(s.result is None for s in steps[:-1]))
        self.assertIsInstance(steps[-1].result, offset.OffsetResult)
        self.assertTrue(steps[-1].result.verified)
        self.assertEqual(offset.EDGES_PER_STEP, 2000)
        more = list(offset.offset_ring_steps(ring, 5.0, 1, tol=TOL, edges_per_step=500))
        self.assertGreater(len(more), len(steps))

    def test_same_result_whatever_the_step(self) -> None:
        ring = NoisyRingTest._noisy(300, 100.0, 0.6, 3)
        one = offset.offset_ring(ring, 5.0, 1, tol=TOL)
        small = list(offset.offset_ring_steps(ring, 5.0, 1, tol=TOL, edges_per_step=40))[-1].result
        self.assertEqual(len(one.rings), len(small.rings))
        self.assertTrue(np.array_equal(one.rings[0], small.rings[0]))

    def test_cancel_by_closing(self) -> None:
        steps = offset.offset_ring_steps(self._circle(9000), 5.0, 1, tol=TOL)
        first = next(steps)
        self.assertIsNone(first.result)
        steps.close()
        with self.assertRaises(StopIteration):
            next(steps)


class CheckOffsetTest(unittest.TestCase):
    """«Nunca un resultado dudoso en silencio»."""

    def test_a_result_too_close_to_the_source_is_rejected_with_place_and_defect(self) -> None:
        source = _poly((0, 0), (40, 0), (40, 40), (0, 40))
        bad = source + np.array([[0.0, 0.0], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]])
        ok, at, kind, defect = offset.check_offset(source, 3.0, [bad], [np.arange(4)], tol=TOL)
        self.assertFalse(ok)
        self.assertEqual(kind, "distance")
        self.assertAlmostEqual(defect, 3.0 - TOL, delta=1e-6)
        self.assertIsNotNone(at)

    def test_a_crossing_result_is_rejected(self) -> None:
        source = _poly((0, 0), (40, 0), (40, 40), (0, 40))
        bow = _poly((-10, -10), (50, 50), (50, -10), (-10, 50))
        ok, at, kind, _ = offset.check_offset(source, 3.0, [bow], [np.arange(4)], tol=TOL)
        self.assertFalse(ok)
        self.assertEqual(kind, "crossing")
        self.assertAlmostEqual(at[0], 20.0, places=6)

    def test_a_good_result_passes(self) -> None:
        result = offset.offset_ring(L_SHAPE, 3.0, 1, tol=TOL)
        ok, at, kind, defect = offset.check_offset(
            L_SHAPE, 3.0, list(result.rings), list(result.source_edge_of_vertex), tol=TOL)
        self.assertEqual((ok, at, kind, defect), (True, None, "", 0.0))


class ClosingWithFullOffsetTest(unittest.TestCase):
    """T06 nota 3: el cierre con el desfase completo vale también en anillos cóncavos."""

    def test_closing_a_notch_fills_it_and_never_shrinks(self) -> None:
        notch = _poly((0, 0), (40, 0), (40, 18), (20, 18), (20, 22), (40, 22), (40, 40), (0, 40))

        def full(ring: np.ndarray, distance: float, side: int) -> np.ndarray:
            result = offset.offset_ring(ring, distance, side, tol=TOL)
            return max(result.rings, key=_area)

        closed = offset.closing(notch, 3.0, tol=TOL, offset=full)
        self.assertGreaterEqual(_area(closed), _area(notch) - 1e-6)
        self.assertGreater(_area(closed), _area(notch) + 0.5 * 20.0 * 4.0)


if __name__ == "__main__":
    unittest.main()
