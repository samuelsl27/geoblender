# SPDX-License-Identifier: GPL-3.0-or-later
"""La superposición de polígonos y la distancia entre segmentos (spec 012, T04; HU-012-1;
RF-012-05, RF-012-06; plan 012 A4, A6, D-36 y D-37).

RF-012-05 pide el área del límite legal, del perímetro, de su intersección y de la franja
perímetro ∖ límite con cada parte (área y centro absoluto) con error relativo ≤ 10⁻⁹; RF-012-06,
el área ganada y perdida de cada restricción (``área(A ∖ A')`` y ``área(A' ∖ A)``). Las dos salen
de :func:`gis.polygons.overlay` (unión, intersección y diferencia de conjuntos de polígonos con
huecos) y su :class:`Region` (aristas, partes con su área y su centro absoluto). Las referencias
son independientes: áreas y centros a mano o por Sutherland–Hodgman con aritmética racional
(``Fraction``) sobre coordenadas enteras, y la distancia punto-segmento escrita a mano.
"""

from __future__ import annotations

import unittest
from fractions import Fraction

import numpy as np

from tests.support import constraints_fixtures as fx
from tests.support.package import import_geoblender

polygons = import_geoblender("gis.polygons")

TOLERANCE = 1e-12
"""Error relativo admitido de un área frente a la exacta (T04)."""

CENTER_TOLERANCE_M = 1e-6
"""Error admitido (m) de un centro absoluto (coordenadas de 4,4·10⁶ m: 10⁻¹² relativo)."""

ORIGIN = np.asarray(fx.BASE)


def _rect(left, bottom, right, top):
    return fx.rectangle(left, bottom, right, top)


def _poly(points):
    return fx.absolute(list(points) + [points[0]])


# Referencias racionales ------------------------------------------------------------------


def _moments(points) -> tuple[Fraction, Fraction, Fraction]:
    """(área con signo, momento en X, momento en Y) racionales del polígono local ``points``."""
    area = mx = my = Fraction(0)
    count = len(points)
    for k in range(count):
        x0, y0 = points[k]
        x1, y1 = points[(k + 1) % count]
        cross = x0 * y1 - x1 * y0
        area += cross
        mx += (x0 + x1) * cross
        my += (y0 + y1) * cross
    return area / 2, mx / 6, my / 6


def _sh(subject, clip):
    """Sutherland–Hodgman racional: ``subject`` (cualquiera) recortado por ``clip`` (convexo y
    antihorario), puntos locales."""
    out = [(Fraction(x), Fraction(y)) for x, y in subject]
    clip = [(Fraction(x), Fraction(y)) for x, y in clip]
    for k in range(len(clip)):
        (ax, ay), (bx, by) = clip[k], clip[(k + 1) % len(clip)]

        def side(p, ax=ax, ay=ay, bx=bx, by=by):
            return (bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax)

        source, out = out, []
        for i in range(len(source)):
            p, q = source[i], source[(i + 1) % len(source)]
            sp, sq = side(p), side(q)
            if sp >= 0:
                out.append(p)
            if (sp >= 0) != (sq >= 0):
                t = sp / (sp - sq)
                out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
        if not out:
            return []
    return out


def _sum(*terms):
    """Suma (con signo) de momentos: ``(+1, m)`` o ``(-1, m)``."""
    area = mx = my = Fraction(0)
    for sign, (a, x, y) in terms:
        area += sign * a
        mx += sign * x
        my += sign * y
    return area, mx, my


def _center(moments) -> tuple[float, float]:
    area, mx, my = moments
    return (fx.BASE[0] + float(mx / area), fx.BASE[1] + float(my / area))


# Ayudas de comprobación -------------------------------------------------------------------


class _Case(unittest.TestCase):

    def assertArea(self, actual: float, expected, msg: str = "") -> None:
        expected = float(expected)
        if expected == 0.0:
            self.assertLessEqual(abs(actual), 1e-9, msg)
        else:
            self.assertLessEqual(abs(actual - expected) / abs(expected), TOLERANCE,
                                 f"{msg}: {actual} frente a {expected}")

    def assertParts(self, region, expected) -> None:
        """``expected``: [(área, (cx, cy) absolutos)], en el orden de las partes."""
        self.assertEqual(len(region.parts), len(expected), region.parts)
        for part, (area, center) in zip(region.parts, expected, strict=True):
            self.assertArea(part.area_m2, area, "área de la parte")
            self.assertEqual(len(part.centroid), 2)
            for got, want in zip(part.centroid, center, strict=True):
                self.assertLessEqual(abs(got - want), CENTER_TOLERANCE_M, (part, center))
        self.assertArea(sum(p.area_m2 for p in region.parts), region.area_m2 or 0.0, "suma")

    def overlay(self, a, b, op):
        region = polygons.overlay(a, b, op, origin=ORIGIN)
        self.assertIsInstance(region, polygons.Region)
        edges = np.asarray(region.edges_local)
        self.assertEqual(edges.shape[1:], (2, 2))
        # El área de la región es la de sus aristas (suma con signo).
        signed = 0.5 * float(np.sum(edges[:, 0, 0] * edges[:, 1, 1]
                                    - edges[:, 1, 0] * edges[:, 0, 1])) if len(edges) else 0.0
        self.assertArea(signed, region.area_m2, "aristas")
        return region


def _abs_center(left, bottom, right, top):
    return (fx.BASE[0] + (left + right) / 2.0, fx.BASE[1] + (bottom + top) / 2.0)


# Pruebas ----------------------------------------------------------------------------------


class TestRectangles(_Case):
    """Rectángulos que se cruzan, con lado común, que se tocan y contenidos (RF-012-05)."""

    def test_crossing(self) -> None:
        a, b = _rect(0, 0, 100, 60), _rect(40, 30, 140, 90)
        inter = self.overlay([[a]], [[b]], "intersection")
        self.assertParts(inter, [(1800.0, _abs_center(40, 30, 100, 60))])
        union = self.overlay([[a]], [[b]], "union")
        self.assertArea(union.area_m2, 6000 + 6000 - 1800)
        self.assertEqual(len(union.parts), 1)
        diff = self.overlay([[a]], [[b]], "difference")
        self.assertArea(diff.area_m2, 6000 - 1800)
        # Centro de A ∖ B: momentos de A menos los de A ∩ B.
        cx = (6000 * 50 - 1800 * 70) / 4200
        cy = (6000 * 30 - 1800 * 45) / 4200
        self.assertParts(diff, [(4200.0, (fx.BASE[0] + cx, fx.BASE[1] + cy))])

    def test_common_side(self) -> None:
        a, b = _rect(0, 0, 100, 100), _rect(100, 20, 200, 80)
        self.assertParts(self.overlay([[a]], [[b]], "intersection"), [])
        union = self.overlay([[a]], [[b]], "union")
        cx = (10000 * 50 + 6000 * 150) / 16000
        self.assertParts(union, [(16000.0, (fx.BASE[0] + cx, fx.BASE[1] + 50.0))])
        self.assertParts(self.overlay([[a]], [[b]], "difference"),
                         [(10000.0, _abs_center(0, 0, 100, 100))])

    def test_touching_corner(self) -> None:
        a, b = _rect(0, 0, 100, 100), _rect(100, 100, 150, 150)
        self.assertParts(self.overlay([[a]], [[b]], "intersection"), [])
        union = self.overlay([[a]], [[b]], "union")
        self.assertParts(union, [(10000.0, _abs_center(0, 0, 100, 100)),
                                 (2500.0, _abs_center(100, 100, 150, 150))])

    def test_contained(self) -> None:
        a, b = _rect(0, 0, 100, 100), _rect(20, 30, 50, 70)
        self.assertParts(self.overlay([[a]], [[b]], "intersection"),
                         [(1200.0, _abs_center(20, 30, 50, 70))])
        self.assertParts(self.overlay([[a]], [[b]], "union"),
                         [(10000.0, _abs_center(0, 0, 100, 100))])
        diff = self.overlay([[a]], [[b]], "difference")
        cx = (10000 * 50 - 1200 * 35) / 8800
        cy = (10000 * 50 - 1200 * 50) / 8800
        self.assertParts(diff, [(8800.0, (fx.BASE[0] + cx, fx.BASE[1] + cy))])
        # B ∖ A: nada.
        self.assertParts(self.overlay([[b]], [[a]], "difference"), [])

    def test_difference_in_two_parts(self) -> None:
        a, b = _rect(0, 0, 100, 40), _rect(40, -10, 60, 50)
        diff = self.overlay([[a]], [[b]], "difference")
        self.assertParts(diff, [(1600.0, _abs_center(0, 0, 40, 40)),
                                (1600.0, _abs_center(60, 0, 100, 40))])

    def test_contiguous_concessions(self) -> None:
        """Dos concesiones contiguas: su unión es una parte sin el lado común (A2, A4)."""
        a, b = _rect(0, 0, 100, 80), _rect(100, 0, 160, 80)
        union = self.overlay([[a]], [[b]], "union")
        self.assertParts(union, [(12800.0, _abs_center(0, 0, 160, 80))])
        edges = np.asarray(union.edges_local)
        on_common = (np.abs(edges[:, 0, 0] - 100.0) < 1e-9) & (np.abs(edges[:, 1, 0] - 100.0)
                                                               < 1e-9)
        self.assertFalse(on_common.any(), edges)
        # Las dos en un mismo conjunto: la misma unión.
        same = self.overlay([[a], [b]], [], "union")
        self.assertParts(same, [(12800.0, _abs_center(0, 0, 160, 80))])
        self.assertParts(self.overlay([[a]], [[b]], "intersection"), [])
        self.assertParts(self.overlay([[a], [b]], [[_rect(90, 10, 110, 20)]], "intersection"),
                         [(200.0, _abs_center(90, 10, 110, 20))])


class TestRotatedWithHole(_Case):
    """Una L contra un cuadrado girado 45° con un hueco: Sutherland–Hodgman racional."""

    L_SHAPE = [(20, 20), (100, 20), (100, 45), (45, 45), (45, 100), (20, 100)]
    DIAMOND = [(50, 10), (90, 50), (50, 90), (10, 50)]
    HOLE = [(50, 35), (65, 50), (50, 65), (35, 50)]

    def setUp(self) -> None:
        self.l_shape = [_poly(self.L_SHAPE)]
        self.diamond = [_poly(self.DIAMOND), _poly(self.HOLE[::-1])]
        lm = _moments(self.L_SHAPE)
        dm = _sum((1, _moments(self.DIAMOND)), (-1, _moments(self.HOLE)))
        inter = _sum((1, _moments(_sh(self.L_SHAPE, self.DIAMOND))),
                     (-1, _moments(_sh(self.L_SHAPE, self.HOLE))))
        self.moments = {
            "intersection": inter,
            "union": _sum((1, lm), (1, dm), (-1, inter)),
            "difference": _sum((1, lm), (-1, inter)),
            "reverse": _sum((1, dm), (-1, inter)),
        }

    def test_operations(self) -> None:
        for op in ("intersection", "union", "difference"):
            with self.subTest(op=op):
                region = self.overlay([self.l_shape], [self.diamond], op)
                moments = self.moments[op]
                self.assertArea(region.area_m2, moments[0], op)
                if op == "union":
                    self.assertEqual(len(region.parts), 1)
                    self.assertParts(region, [(moments[0], _center(moments))])
        region = self.overlay([self.diamond], [self.l_shape], "difference")
        self.assertArea(region.area_m2, self.moments["reverse"][0], "D ∖ L")
        # Las partes suman el total y su centro conjunto es el de la referencia.
        for op, a, b in (("intersection", self.l_shape, self.diamond),
                         ("difference", self.l_shape, self.diamond),
                         ("reverse", self.diamond, self.l_shape)):
            with self.subTest(parts=op):
                region = self.overlay([a], [b], "difference" if op == "reverse" else op)
                total = sum(p.area_m2 for p in region.parts)
                cx = sum(p.area_m2 * (p.centroid[0] - fx.BASE[0]) for p in region.parts) / total
                cy = sum(p.area_m2 * (p.centroid[1] - fx.BASE[1]) for p in region.parts) / total
                want = _center(self.moments[op])
                self.assertLessEqual(abs(fx.BASE[0] + cx - want[0]), CENTER_TOLERANCE_M)
                self.assertLessEqual(abs(fx.BASE[1] + cy - want[1]), CENTER_TOLERANCE_M)

    def test_hole_kept_in_parts(self) -> None:
        """El cuadrado girado solo: una parte con su hueco (área y centro de los dos)."""
        region = self.overlay([self.diamond], [], "union")
        dm = _sum((1, _moments(self.DIAMOND)), (-1, _moments(self.HOLE)))
        self.assertParts(region, [(dm[0], _center(dm))])

    def test_inputs_untouched(self) -> None:
        before = [ring.copy() for ring in self.diamond]
        self.overlay([self.l_shape], [self.diamond], "union")
        for ring, copy in zip(self.diamond, before, strict=True):
            np.testing.assert_array_equal(ring, copy)


class TestLimits(_Case):
    """CE-012-03: el perímetro sintético menos el límite legal da 6 800 m² (0,68 ha)."""

    def test_strip(self) -> None:
        lim = fx.limits()
        legal, perimeter = [[lim.legal_limit]], [[lim.perimeter]]
        self.assertArea(self.overlay(legal, [], "union").area_m2, lim.legal_area_m2)
        self.assertArea(self.overlay(perimeter, [], "union").area_m2, lim.perimeter_area_m2)
        self.assertArea(self.overlay(perimeter, legal, "intersection").area_m2,
                        lim.intersection_m2)
        strip = self.overlay(perimeter, legal, "difference")
        self.assertArea(strip.area_m2, lim.strip_m2)
        self.assertEqual(lim.strip_m2 / 10_000.0, 0.68)
        self.assertParts(strip, [(p.area_m2, p.center) for p in lim.strip_parts])

    def test_redrawn(self) -> None:
        """CE-012-04 con A4: ganado 14 300 m², perdido 0, y la franja en sus dos partes."""
        lim = fx.limits()
        old, new = [[lim.perimeter]], [[lim.redrawn_perimeter]]
        self.assertArea(self.overlay(new, old, "difference").area_m2, lim.gained_m2)
        self.assertArea(self.overlay(old, new, "difference").area_m2, lim.lost_m2)
        strip = self.overlay(new, [[lim.legal_limit]], "difference")
        self.assertArea(strip.area_m2, lim.redrawn_strip_m2)
        expected = sorted(((p.area_m2, p.center) for p in lim.redrawn_strip_parts),
                          key=lambda item: -item[0])
        self.assertParts(strip, expected)

    def test_bad_operation(self) -> None:
        with self.assertRaises(ValueError):
            polygons.overlay([], [], "xor", origin=ORIGIN)
        self.assertParts(self.overlay([], [], "union"), [])


def _point_segment(p, a, b) -> float:
    """Distancia de ``p`` al segmento ``a–b`` (también nulo), a mano."""
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 == 0.0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return ((px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2) ** 0.5


def _hand(a, b, c, d) -> float:
    """Distancia entre los segmentos ``a–b`` y ``c–d``, a mano: 0 si se cruzan (cada uno con
    los extremos del otro a lados opuestos); si no, la menor de las cuatro punto-segmento."""
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    o1 = r[0] * (c[1] - a[1]) - r[1] * (c[0] - a[0])
    o2 = r[0] * (d[1] - a[1]) - r[1] * (d[0] - a[0])
    o3 = s[0] * (a[1] - c[1]) - s[1] * (a[0] - c[0])
    o4 = s[0] * (b[1] - c[1]) - s[1] * (b[0] - c[0])
    if o1 * o2 < 0 and o3 * o4 < 0:
        return 0.0
    return min(_point_segment(a, c, d), _point_segment(b, c, d),
               _point_segment(c, a, b), _point_segment(d, a, b))


class TestSegmentDistance(unittest.TestCase):
    """``segment_distance``: 0 si se cortan; si no, el mínimo de las cuatro distancias
    punto-segmento (plan A6)."""

    CASES = {
        "cruce": (((0, 0), (10, 10)), ((0, 10), (10, 0)), 0.0),
        "cruce en T": (((0, 0), (10, 0)), ((5, 0), (5, 7)), 0.0),
        "paralelos": (((0, 0), (10, 0)), ((2, 3), (8, 3)), 3.0),
        "paralelos desplazados": (((0, 0), (10, 0)), ((13, 4), (20, 4)), 5.0),
        "colineales separados": (((0, 0), (10, 0)), ((12, 0), (20, 0)), 2.0),
        "colineales solapados": (((0, 0), (10, 0)), ((5, 0), (20, 0)), 0.0),
        "oblicuos": (((0, 0), (4, 0)), ((6, 1), (9, 5)), None),
        "nulo y segmento": (((3, 4), (3, 4)), ((0, 0), (10, 0)), 4.0),
        "nulo y nulo": (((0, 0), (0, 0)), ((3, 4), (3, 4)), 5.0),
        "nulo sobre segmento": (((5, 0), (5, 0)), ((0, 0), (10, 0)), 0.0),
    }

    def test_cases(self) -> None:
        names = list(self.CASES)
        p = np.array([self.CASES[n][0] for n in names], dtype=np.float64)
        q = np.array([self.CASES[n][1] for n in names], dtype=np.float64)
        got = polygons.segment_distance(p, q)
        self.assertEqual(got.shape, (len(names),))
        for k, name in enumerate(names):
            (a, b), (c, d), want = self.CASES[name]
            hand = _hand(a, b, c, d)
            if want is not None:
                self.assertAlmostEqual(hand, want, places=12, msg=name)
            else:
                want = hand
            with self.subTest(name=name):
                self.assertAlmostEqual(float(got[k]), want, places=12)
        # Simétrica.
        np.testing.assert_allclose(polygons.segment_distance(q, p), got, rtol=0, atol=1e-12)

    def test_random_against_hand(self) -> None:
        rng = np.random.default_rng(12)
        p = rng.integers(-20, 20, size=(400, 2, 2)).astype(np.float64)
        q = rng.integers(-20, 20, size=(400, 2, 2)).astype(np.float64)
        got = polygons.segment_distance(p, q)
        for k in range(len(p)):
            a, b = p[k]
            c, d = q[k]
            hand = _hand(a.tolist(), b.tolist(), c.tolist(), d.tolist())
            self.assertAlmostEqual(float(got[k]), hand, places=12, msg=(a, b, c, d))


if __name__ == "__main__":
    unittest.main()
