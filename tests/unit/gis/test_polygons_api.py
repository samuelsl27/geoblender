# SPDX-License-Identifier: GPL-3.0-or-later
"""La geometría 2D de la 011, bajada a ``gis`` (spec 012, T03; HU-012-4; RF-012-07, RF-012-12;
plan 012 §5.6, D-18 y T2).

La validación, los solapes y el recorte de polígonos (``reserves.polygons``) y la fracción
exacta de celda (``reserves.coverage``) pasan a ``gis.polygons`` y ``gis.coverage`` (nivel 2), para
que las máscaras de las restricciones (``gis.masks``: la celda entera dentro de un polígono,
RF-012-12; los sectores de búsqueda, RF-012-07) y el diseño los usen sin importar ``reserves``.
En ``gis`` los errores son neutros (:class:`PolygonProblem`: posición, problema y área), sin
códigos de nota de la cubicación; ``reserves`` conserva su API sobre lo de ``gis``.

Estas pruebas repiten en ``gis`` los casos de ``tests/unit/reserves/test_polygons.py`` y
``test_coverage.py`` (con las mismas referencias independientes: áreas a mano y la de
Sutherland–Hodgman) y comprueban que ``reserves`` da los mismos objetos, los mismos problemas y
las mismas aristas, bit a bit.
"""

from __future__ import annotations

import math
import unittest

import numpy as np

from tests.support.package import import_geoblender

gis = import_geoblender("gis")
gis_polygons = import_geoblender("gis.polygons")
gis_coverage = import_geoblender("gis.coverage")
res_polygons = import_geoblender("reserves.polygons")
res_coverage = import_geoblender("reserves.coverage")
messages = import_geoblender("reserves.messages")

Grid = gis.Grid
WEST = 735_000.0
SOUTH = 4_434_000.0
ORIGIN = np.array([WEST, SOUTH])
TOLERANCE = 1e-12
"""Error relativo admitido de un área."""


def _ring(points) -> np.ndarray:
    """Un anillo ABSOLUTO desde coordenadas relativas a (WEST, SOUTH)."""
    return np.asarray(points, dtype=np.float64) + ORIGIN


def _rect(x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
    return _ring([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])


def _square(side: float, angle: float, center) -> np.ndarray:
    h = side / 2.0
    c, s = math.cos(angle), math.sin(angle)
    points = np.array([[-h, -h], [h, -h], [h, h], [-h, h]]) @ np.array([[c, s], [-s, c]])
    return _ring(points + np.asarray(center, dtype=np.float64))


def _shoelace(points) -> float:
    pairs = zip(points, points[1:] + points[:1])
    return math.fsum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in pairs) / 2.0


def _sh_area(subject: np.ndarray, clip: np.ndarray) -> float:
    """El área (m²) de ``subject`` recortado por el polígono CONVEXO ``clip`` (Sutherland–
    Hodgman), en metros relativos a (WEST, SOUTH)."""
    points = [tuple(p) for p in (subject - ORIGIN).tolist()]
    window = clip - ORIGIN
    if _shoelace([tuple(p) for p in window.tolist()]) < 0.0:
        window = window[::-1]
    for (ax, ay), (bx, by) in zip(window.tolist(), np.roll(window, -1, axis=0).tolist()):
        if not points:
            return 0.0

        def side(p, ax=ax, ay=ay, bx=bx, by=by) -> float:
            return (bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax)

        out = []
        for current, following in zip(points, points[1:] + points[:1]):
            sc, sf = side(current), side(following)
            if sc >= 0.0:
                out.append(current)
            if (sc >= 0.0) != (sf >= 0.0):
                t = sc / (sc - sf)
                out.append((current[0] + t * (following[0] - current[0]),
                            current[1] + t * (following[1] - current[1])))
        points = out
    return abs(_shoelace(points)) if len(points) >= 3 else 0.0


def _edges_area(edges: np.ndarray) -> float:
    return 0.5 * float(np.sum(edges[:, 0, 0] * edges[:, 1, 1] - edges[:, 1, 0] * edges[:, 0, 1]))


def _clip_area(rings, clip_rings) -> float:
    return _edges_area(gis_polygons.clip(rings, clip_rings, origin=(WEST, SOUTH)))


def _layer_rings() -> list[tuple[np.ndarray, ...]]:
    """Los polígonos de la capa con problemas de la 011 (sin su campo): válido, pajarita, sin
    área, válido, y dos que se solapan 5 × 4 = 20 m²."""
    return [
        (_rect(0, 0, 10, 10),),
        (_ring([[20, 0], [30, 0], [20, 10], [30, 10]]),),
        (_ring([[40, 0], [50, 0], [45, 0]]),),
        (_rect(0, 20, 10, 30),),
        (_rect(20, 20, 30, 30),),
        (_rect(25, 23, 40, 27),),
    ]


class GisPolygonsTest(unittest.TestCase):
    def test_problems_are_neutral(self) -> None:
        """RF-012-07, RF-012-12 (plan 012 §5.6, T2): ``gis.polygons.problems`` da los problemas
        de la 011 (RF-011-08) sin códigos de la cubicación: la posición del polígono, el
        problema y, en un solape, el otro y el área (20 m², exacta en rectángulos)."""
        found = gis_polygons.problems(_layer_rings())
        self.assertEqual([(p.index, p.problem, p.other, p.area_m2) for p in found],
                         [(1, "self_intersecting", None, None), (2, "no_area", None, None),
                          (4, "overlap", 5, 20.0)])
        self.assertTrue(all(isinstance(p, gis_polygons.PolygonProblem) for p in found))
        cases = {
            "pico": ((_ring([[0, 0], [10, 0], [10, 10], [5, 10], [5, 15], [5, 10], [0, 10]]),),
                     "self_intersecting"),
            "hueco que toca": ((_rect(0, 0, 10, 10), _ring([[0, 0], [3, 2], [2, 3]])),
                               "self_intersecting"),
            "cuello de 0,5 mm": ((_ring([[0, 0], [10, 0], [10, 4.9995], [5, 4.9995], [5, 5.0],
                                         [10, 5.0], [10, 10], [0, 10]]),), "self_intersecting"),
            "1 mm²": ((_ring([[0, 0], [0.002, 0], [0.002, 0.0005], [0, 0.0005]]),), "no_area"),
            "hueco fuera": ((_rect(0, 0, 10, 10), _rect(20, 20, 22, 22)), "hole_outside"),
            "hueco en un hueco": ((_rect(0, 0, 10, 10), _rect(2, 2, 8, 8), _rect(4, 4, 5, 5)),
                                  "hole_outside"),
        }
        for name, (rings, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual([(p.index, p.problem) for p in gis_polygons.problems([rings])],
                                 [(0, expected)])
        self.assertEqual(gis_polygons.problems([(_rect(0, 0, 10, 10), _rect(2, 2, 8, 8))]), ())

    def test_overlaps_and_contacts(self) -> None:
        """RF-012-12 (A6 de la 011): lados comunes, esquinas y un solape de 0,4 mm no se solapan;
        dos cuadrados girados, el área de Sutherland–Hodgman (≤ 10⁻¹²)."""
        layer = [(_rect(0, 0, 10, 10),), (_rect(10, 0, 20, 10),), (_rect(0, 10, 5, 20),),
                 (_rect(20, 10, 30, 20),), (_rect(6, 9.9996, 9, 14),)]
        self.assertEqual(gis_polygons.overlaps(layer), ())
        first = _square(20.0, 0.3, (100.0, 100.0))
        second = _square(16.0, 0.9, (108.0, 104.0))
        found = gis_polygons.overlaps([(first,), (second,)])
        self.assertEqual([(o.first, o.second) for o in found], [(0, 1)])
        reference = _sh_area(first, second)
        self.assertLessEqual(abs(found[0].area_m2 - reference) / reference, TOLERANCE)

    def test_clip(self) -> None:
        """RF-012-12 (A6 y D-21 de la 011): el recorte da el área exacta: dos rectángulos que se
        cruzan, 20 m²; con un lado común en el mismo sentido, 100; que solo se tocan, nada; una L
        contra un cuadrado girado con un hueco, la de Sutherland–Hodgman (1 640,42 m²)."""
        domain = (_rect(0, 0, 10, 10),)
        self.assertEqual(_clip_area(domain, (_rect(5, 3, 20, 7),)), 20.0)
        self.assertEqual(_clip_area(domain, (_rect(0, 0, 30, 10),)), 100.0)
        touching = gis_polygons.clip(domain, (_rect(10, 0, 20, 10),), origin=(WEST, SOUTH))
        self.assertEqual(touching.shape, (0, 2, 2))
        outer = _square(60.0, 0.4, (40.0, 40.0))
        hole = _square(10.0, 0.4, (40.0, 40.0))
        letter = _ring([[0, 0], [60, 0], [60, 20], [20, 20], [20, 60], [0, 60]]) + 10.0
        area = _clip_area((letter,), (outer, hole))
        reference = _sh_area(letter, outer) - _sh_area(letter, hole)
        self.assertAlmostEqual(reference, 1640.42, delta=0.01)
        self.assertLessEqual(abs(area - reference) / reference, TOLERANCE)
        edges = gis_polygons.local_edges((outer, hole), ORIGIN)
        # Los vértices girados, redondeados a float64 en coordenadas UTM (≈ 10⁻¹⁰ m).
        self.assertAlmostEqual(_edges_area(edges), 60.0 ** 2 - 10.0 ** 2, delta=1e-6)

    def test_coverage(self) -> None:
        """RF-012-12 (A5 de la 011): la fracción de celda en ``gis.coverage``: un rectángulo de
        10 × 6 m con la esquina en mitad de una celda da 60 m² y cuartos de celda en sus
        esquinas; por bandas, lo mismo bit a bit."""
        grid = Grid(WEST, SOUTH + 20.0, 1.0, 1.0, 20, 20)
        rect = _rect(2.5, 3.5, 12.5, 9.5)
        edges = gis_coverage.polygon_edges([rect], grid)
        whole = gis_coverage.band_coverage(edges, grid, slice(None))
        self.assertEqual(float(np.sum(whole.fraction)) * grid.cell_area, 60.0)
        corners = whole.fraction[(whole.rows == 20 - 4) & (whole.cols == 2)]
        self.assertEqual(corners.tolist(), [0.25])
        parts = [gis_coverage.band_coverage(edges, grid, slice(k, k + 3)) for k in range(0, 20, 3)]
        self.assertEqual(np.concatenate([p.fraction for p in parts]).tolist(),
                         whole.fraction.tolist())
        self.assertGreater(gis_coverage.signed_area(rect), 0.0)


class ReservesOnGisTest(unittest.TestCase):
    def test_reserves_gives_the_same_objects(self) -> None:
        """RF-012-07, RF-012-12 (plan 012 §5.6): ``reserves.coverage`` reexporta ``gis.coverage``
        y ``reserves.polygons`` usa los mismos datos y constantes de ``gis.polygons``."""
        for name in ("FRACTION_EPSILON", "CoverageBand", "band_coverage", "polygon_edges",
                     "signed_area"):
            with self.subTest(name):
                self.assertIs(getattr(res_coverage, name), getattr(gis_coverage, name))
        for name in ("Overlap", "TOLERANCE_M", "AREA_TOLERANCE_M2"):
            with self.subTest(name):
                self.assertIs(getattr(res_polygons, name), getattr(gis_polygons, name))

    def test_reserves_problems_and_errors_on_gis(self) -> None:
        """RF-012-07 (plan 012 §5.6): los problemas de ``reserves.polygons`` son los de
        ``gis.polygons`` con sus códigos ``res.*``, y siguen lanzándose como ``ResError``; el
        recorte por el ámbito da las aristas de ``gis.polygons.clip`` bit a bit."""
        rings = _layer_rings()
        layer = [res_polygons.Polygon(fid, f"Fase {fid}" if fid != 4 else "", r)
                 for fid, r in enumerate(rings, 1)]
        found = res_polygons.problems(layer)
        self.assertEqual([(p.code, p.fid, p.other_fid, p.area_m2) for p in found],
                         [("res.domain_self_intersecting", 2, None, None),
                          ("res.domain_no_area", 3, None, None),
                          ("res.domain_value_empty", 4, None, None),
                          ("res.domain_overlap", 5, 6, 20.0)])
        with self.assertRaises(messages.ResError) as caught:
            res_polygons.validate(layer, field="fase", layer="Fases")
        self.assertIsInstance(caught.exception, res_polygons.DomainsError)
        with self.assertRaises(res_polygons.ScopeError):
            res_polygons.validate_scope(layer, layer="Ámbito")
        steps = res_polygons.problem_steps(layer)
        count = 0
        while True:
            try:
                next(steps)
                count += 1
            except StopIteration as stop:
                self.assertEqual(stop.value, found)
                break
        self.assertEqual(count, len(layer) + 1)   # uno por polígono y uno por par de cajas
        domain = res_polygons.Polygon(1, "L", (_ring([[0, 0], [60, 0], [60, 20], [20, 20],
                                                     [20, 60], [0, 60]]) + 10.0,))
        scope = res_polygons.Polygon(0, "", (_square(60.0, 0.4, (40.0, 40.0)),))
        self.assertTrue(np.array_equal(
            res_polygons.clip_to_scope(domain, scope, origin=(WEST, SOUTH)),
            gis_polygons.clip(domain.rings, scope.rings, origin=(WEST, SOUTH))))


if __name__ == "__main__":
    unittest.main()
