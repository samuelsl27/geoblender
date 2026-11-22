# SPDX-License-Identifier: GPL-3.0-or-later
"""El desfase de la 018, primera mitad: simplificar y la curva cruda (spec 018, T06; RF-018-10;
plan 018 §5.4 A1 y A3, P-2 y P-3; CE-018-01), y la regresión bit a bit de ``gis.polygons`` tras
dar nombre público a sus ayudas (T-1 de plan §10)."""

from __future__ import annotations

import ast
import hashlib
import math
import unittest
from pathlib import Path

import numpy as np

from tests.support.package import import_geoblender

offset = import_geoblender("gis.offset")
polygons = import_geoblender("gis.polygons")

TOL = 0.01
D = 10.0 / math.tan(math.radians(60.0))
"""5,7735 m: h / tan α de CE-018-01."""


def _square(side: float) -> np.ndarray:
    return np.array([[0.0, 0.0], [side, 0.0], [side, side], [0.0, side]])


def _area(ring: np.ndarray) -> float:
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def _min_distance(points: np.ndarray, ring: np.ndarray) -> np.ndarray:
    a, b = ring, np.roll(ring, -1, axis=0)
    d = b - a
    w = points[:, None, :] - a[None, :, :]
    t = np.clip(np.einsum("pej,ej->pe", w, d) / np.einsum("ej,ej->e", d, d), 0.0, 1.0)
    rest = w - t[:, :, None] * d[None, :, :]
    return np.hypot(rest[..., 0], rest[..., 1]).min(axis=1)


class RawOffsetTest(unittest.TestCase):
    """RF-018-10, CE-018-01."""

    def test_miter_square_area_and_four_vertices(self) -> None:
        curve = offset.raw_offset(_square(100.0), D, tol=TOL, corner="miter")
        self.assertEqual(len(curve.points), 4)
        expected = 100.0 ** 2 + 4 * 100.0 * D + 4 * D ** 2
        self.assertAlmostEqual(_area(curve.points), expected, places=6)
        self.assertEqual(sorted(curve.source_edge.tolist()), [0, 1, 2, 3])

    def test_round_square_area_within_arc_tolerance_one_sign(self) -> None:
        ring = _square(100.0)
        curve = offset.raw_offset(ring, D, tol=TOL)
        exact = 100.0 ** 2 + 4 * 100.0 * D + math.pi * D ** 2
        self.assertAlmostEqual(exact, 12414.12, delta=0.01)
        area = _area(curve.points)
        self.assertGreaterEqual(area, exact - 1e-9)
        self.assertLessEqual(area, exact + (4 * 100.0 + 2 * math.pi * D) * TOL)
        dist = _min_distance(curve.points, ring)
        self.assertGreaterEqual(float(dist.min()), D - 1e-9)
        self.assertLessEqual(float(dist.max()), D + TOL + 1e-9)
        mids = 0.5 * (curve.points + np.roll(curve.points, -1, axis=0))
        self.assertGreaterEqual(float(_min_distance(mids, ring).min()), D - 1e-9)

    def test_inward_square_miter_is_exact(self) -> None:
        curve = offset.raw_offset(_square(100.0), D, tol=TOL, side=-1, corner="miter")
        self.assertEqual(len(curve.points), 4)
        self.assertAlmostEqual(_area(curve.points), (100.0 - 2 * D) ** 2, places=6)

    def test_inward_round_convex_corner_gives_both_ends(self) -> None:
        """Un giro que no abre el lado del desfase: los dos extremos (A4 quitará el cruce)."""
        curve = offset.raw_offset(_square(100.0), D, tol=TOL, side=-1)
        self.assertEqual(len(curve.points), 8)

    def test_vertex_count_stable_in_six_passes(self) -> None:
        """T-1: un desfase con dos puntos por esquina duplicaría los vértices en cada pasada."""
        angle = np.linspace(0.0, 2.0 * math.pi, 720, endpoint=False)
        ring = 150.0 * np.column_stack([np.cos(angle), np.sin(angle)])
        for k in range(6):
            ring = offset.raw_offset(ring, (D, 6.0)[k % 2], tol=TOL).points
            self.assertEqual(len(ring), 720, f"pasada {k + 1}")

    def test_distance_per_edge_makes_a_step(self) -> None:
        ring = _square(100.0)
        curve = offset.raw_offset(ring, np.array([5.0, 5.0, 8.0, 8.0]), tol=TOL, corner="miter")
        # Aristas 0 y 1 a 5 m; 2 y 3 a 8 m: el inglete entre ellas es el cruce de las dos rectas.
        self.assertAlmostEqual(float(curve.points[:, 1].min()), -5.0)
        self.assertAlmostEqual(float(curve.points[:, 0].max()), 105.0)
        self.assertAlmostEqual(float(curve.points[:, 1].max()), 108.0)
        self.assertAlmostEqual(float(curve.points[:, 0].min()), -8.0)

    def test_miter_limit_falls_back_to_both_ends(self) -> None:
        spike = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 0.5]])
        curve = offset.raw_offset(spike, 1.0, tol=TOL, corner="miter")
        self.assertGreater(len(curve.points), 3)

    def test_concave_corner_gives_both_ends(self) -> None:
        ring = np.array([[0.0, 0.0], [20.0, 0.0], [20.0, 20.0], [10.0, 20.0],
                         [10.0, 10.0], [0.0, 10.0]])
        curve = offset.raw_offset(ring, 2.0, tol=TOL)
        at_concave = curve.source_edge[(curve.source_edge == 3) | (curve.source_edge == 4)]
        self.assertGreaterEqual(len(at_concave), 2)

    def test_errors(self) -> None:
        for kwargs in ({"corner": "bevel"}, {"side": 0}, {"tol": 0.0}):
            args = {"tol": TOL, **kwargs}
            with self.assertRaises(ValueError, msg=str(kwargs)):
                offset.raw_offset(_square(10.0), 1.0, **args)
        with self.assertRaises(ValueError):
            offset.raw_offset(_square(10.0), -1.0, tol=TOL)
        with self.assertRaises(ValueError):
            offset.raw_offset(np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 0.0], [0.0, 1.0]]),
                              1.0, tol=TOL)

    def test_input_is_not_modified(self) -> None:
        ring = _square(100.0)
        before = ring.copy()
        offset.raw_offset(ring, D, tol=TOL)
        offset.simplify_ring(ring, 1.0)
        offset.closing(ring, 3.0, tol=TOL)
        np.testing.assert_array_equal(ring, before)


class SimplifyTest(unittest.TestCase):
    """RF-018-10 (simplificación)."""

    def test_keeps_shape_within_tolerance(self) -> None:
        rng = np.random.default_rng(7)
        angle = np.linspace(0.0, 2.0 * math.pi, 2000, endpoint=False)
        ring = 100.0 * np.column_stack([np.cos(angle), np.sin(angle)])
        ring += rng.normal(0.0, 0.01, ring.shape)
        simple = offset.simplify_ring(ring, 0.05)
        self.assertLess(len(simple), 400)
        self.assertGreaterEqual(len(simple), 3)
        self.assertLessEqual(float(_min_distance(ring, simple).max()), 0.05 + 1e-9)
        self.assertGreater(_area(simple), 0.0)

    def test_collinear_vertices_removed(self) -> None:
        ring = np.array([[0.0, 0.0], [5.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])
        self.assertEqual(len(offset.simplify_ring(ring, 0.001)), 4)

    def test_zero_tolerance_is_a_copy(self) -> None:
        ring = _square(10.0)
        out = offset.simplify_ring(ring, 0.0)
        np.testing.assert_array_equal(out, ring)
        self.assertIsNot(out, ring)


class ClosingTest(unittest.TestCase):
    """D-15: el cierre solo ensancha."""

    def test_convex_keeps_area_and_never_shrinks(self) -> None:
        ring = _square(100.0)
        out = offset.closing(ring, 3.0, tol=TOL)
        self.assertGreaterEqual(_area(out), _area(ring) - 1e-6)
        self.assertLessEqual(_area(out), _area(ring) + 4 * 100.0 * TOL)

    def test_irregular_convex_never_shrinks(self) -> None:
        angle = np.linspace(0.0, 2.0 * math.pi, 9, endpoint=False)
        ring = np.column_stack([40.0 * np.cos(angle), 25.0 * np.sin(angle)])
        out = offset.closing(ring, 2.0, tol=TOL)
        self.assertGreaterEqual(_area(out), _area(ring) - 1e-6)
        self.assertLessEqual(_area(out), _area(ring) + 200.0 * TOL)

    def test_custom_offset_is_used(self) -> None:
        calls: list[int] = []

        def stub(ring: np.ndarray, d: float, side: int) -> np.ndarray:
            calls.append(side)
            return ring

        offset.closing(_square(10.0), 1.0, tol=TOL, offset=stub)
        self.assertEqual(calls, [1, -1])


class PolygonsPublicNamesTest(unittest.TestCase):
    """T-1: las ayudas de ``polygons`` con nombre público y sin cambiar ningún resultado."""

    def test_public_names_and_no_private_aliases(self) -> None:
        for name in ("box_pairs", "crossings", "splice", "chain", "ray_counts", "following",
                     "expand"):
            self.assertTrue(callable(getattr(polygons, name)), name)
            self.assertIn(name, polygons.__all__)
            self.assertFalse(hasattr(polygons, "_" + name), name)

    def test_clip_overlay_problems_bit_for_bit(self) -> None:
        """El resumen SHA-256 de ``clip``, ``overlay`` y ``problems`` sobre seis pares de
        polígonos aleatorios (semilla fija) se calculó **antes** de renombrar: no cambia."""
        rng = np.random.default_rng(20261122)
        digest = hashlib.sha256()
        origin = (500000.0, 4400000.0)
        for k in range(6):
            n = 12 + 7 * k
            ang = np.sort(rng.uniform(0, 2 * np.pi, n))
            rad = rng.uniform(30, 60, n)
            a = np.column_stack([500000 + rad * np.cos(ang), 4400000 + rad * np.sin(ang)])
            ang2 = np.sort(rng.uniform(0, 2 * np.pi, n + 3))
            rad2 = rng.uniform(25, 65, n + 3)
            b = np.column_stack([500012 + rad2 * np.cos(ang2), 4400007 + rad2 * np.sin(ang2)])
            digest.update(np.ascontiguousarray(polygons.clip([a], [b], origin=origin)).tobytes())
            for op in polygons.OPERATIONS:
                region = polygons.overlay([[a]], [[b]], op, origin=origin)
                digest.update(np.ascontiguousarray(region.edges_local).tobytes())
                digest.update(repr(region.area_m2).encode())
            digest.update(repr([repr(p) for p in polygons.problems([[a], [b]])]).encode())
        self.assertEqual(digest.hexdigest(),
                         "a174e020874705d8fc7370334459446d378f4d302801d8512ea5bf2cfcf07ba4")


class OffsetModuleRulesTest(unittest.TestCase):
    """P-2: ``gis/offset.py`` solo importa numpy, la biblioteca estándar, ``polygons`` y el
    ``Progress`` de ``core.project.model``."""

    def test_imports(self) -> None:
        source = Path(offset.__file__).read_text(encoding="utf-8")
        allowed_top = {"__future__", "math", "collections", "contextlib", "dataclasses", "numpy"}
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(alias.name.split(".")[0], allowed_top)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    # T07: ``polygons`` y el ``Progress`` de los pasos (como ``gis.search``).
                    self.assertIn((node.level, node.module),
                                  {(1, "polygons"), (2, "core.project.model")})
                else:
                    self.assertIn((node.module or "").split(".")[0], allowed_top)


if __name__ == "__main__":
    unittest.main()
