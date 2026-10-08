# SPDX-License-Identifier: GPL-3.0-or-later
"""Triangulador propio (spec 006, T17; plan 006 §5.3.1 y §5.4 A9; ADR-0021,
``gis.cdt.PureTriangulator``).

- **RF-006-13**: triangulación de Delaunay restringida. Ningún vértice queda dentro del
  círculo circunscrito de un triángulo salvo que lo tape una arista obligatoria (se comprueba
  en 200 nubes al azar, la mitad con aristas obligatorias, con la propiedad global, la local de
  cada arista y, para las nubes pequeñas, frente a la triangulación de Delaunay por fuerza
  bruta); cada arista obligatoria es arista; los triángulos son índices de la entrada (ningún
  vértice nuevo, todos usados), antihorarios y sin solapes, y cubren la envolvente convexa
  completa (también cuando el supertriángulo deja fuera una arista del borde).
- Casos degenerados sin fallo: malla regular (todos los cuadrados cocirculares), 4 y 12
  puntos cocirculares, puntos casi cocirculares (`cos`/`sin`) y restricciones casi colineales,
  comprobados con aritmética exacta; todos alineados, menos de 3 puntos, puntos repetidos,
  una arista que pasa por un vértice o dos que se cruzan → ``TriangulationError``.
- El contrato del puerto (``ports.Triangulator``) se comprueba con ``check_contract``, que
  también rechaza salidas rotas (la usará el triangulador de Blender, T23).

Las entradas no se modifican (arrays de solo lectura).
"""

import itertools
import math
import unittest
from fractions import Fraction
from unittest import mock

import numpy as np

from tests.support.package import import_geoblender

gis = import_geoblender("gis")
cdt = import_geoblender("gis.cdt")
ports = import_geoblender("gis.ports")
messages = import_geoblender("gis.messages")
worker_api = import_geoblender("jobs.worker_api")

TOL = 1e-9  # tolerancia relativa de las comprobaciones en float de la prueba
CLOUDS = 200


def _frozen(rows, dtype) -> np.ndarray:
    array = np.array(rows, dtype=dtype)
    array.flags.writeable = False  # una entrada nunca se modifica
    return array


def _xy(rows) -> np.ndarray:
    return _frozen(rows, np.float64).reshape(-1, 2)


def _pairs(rows=()) -> np.ndarray:
    return _frozen(rows, np.int32).reshape(-1, 2)


NO_EDGES = _pairs()


def _triangulate(xy, edges=NO_EDGES, **options) -> np.ndarray:
    return cdt.PureTriangulator(**options).triangulate(xy, edges)


def _error(xy, edges=NO_EDGES):
    """El ``TriangulationError`` de la triangulación; si no lo hay, la prueba falla."""
    try:
        _triangulate(xy, edges)
    except ports.TriangulationError as error:
        return error
    raise AssertionError("se esperaba un TriangulationError y no hubo ninguno")


def _canonical(tri) -> set[tuple[int, int, int]]:
    """Los triángulos como conjunto, cada uno empezando por su menor índice (mismo giro)."""
    out = set()
    for a, b, c in np.asarray(tri).tolist():
        rotations = ((a, b, c), (b, c, a), (c, a, b))
        out.add(min(rotations))
    return out


def _undirected(tri) -> set[tuple[int, int]]:
    edges = set()
    for a, b, c in np.asarray(tri).tolist():
        for u, v in ((a, b), (b, c), (c, a)):
            edges.add((min(u, v), max(u, v)))
    return edges


def _cross(o, a, b) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _hull_area(xy) -> float:
    """Área de la envolvente convexa (cadena monótona de Andrew en float, relativa al primer
    punto; solo para comprobar)."""
    xy = np.asarray(xy)
    pts = sorted(map(tuple, (xy - xy[0]).tolist()))
    lower: list = []
    for p in pts:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list = []
    for p in reversed(pts):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    return 0.5 * sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(hull, hull[1:] + hull[:1]))


def _scale(xy) -> float:
    return float(max(np.ptp(xy[:, 0]), np.ptp(xy[:, 1]), 1e-300))


def _assert_triangulation(test, xy, edges, tri, *, slivers: bool = False) -> None:
    """RF-006-13, comprobado sin el código probado: int32 (m, 3), índices de la entrada
    (ningún vértice nuevo) y todos usados, antihorarios, cada arista dirigida una sola vez
    (sin solapes), borde convexo, área = envolvente convexa, m = 2n − h − 2 y cada arista
    obligatoria, arista. Con ``slivers``, el giro de los triángulos de área ínfima (que el
    float no resuelve) lo comprueba ``_assert_exactly_delaunay``."""
    n = len(xy)
    test.assertIsInstance(tri, np.ndarray)
    test.assertEqual(tri.dtype, np.int32)
    test.assertEqual((tri.ndim, tri.shape[1]), (2, 3))
    test.assertGreaterEqual(int(tri.min()), 0)
    test.assertLess(int(tri.max()), n, "vértice nuevo")
    test.assertTrue(np.all(np.bincount(tri.ravel(), minlength=n) > 0), "vértice sin usar")
    p = xy[tri]
    area2 = ((p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1])
             - (p[:, 1, 1] - p[:, 0, 1]) * (p[:, 2, 0] - p[:, 0, 0]))
    if not slivers:
        test.assertTrue(np.all(area2 > 0), "triángulo horario o degenerado")
    directed = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]).astype(np.int64)
    keys = directed[:, 0] * n + directed[:, 1]
    test.assertEqual(len(np.unique(keys)), len(keys), "arista dirigida repetida: solape")
    boundary = directed[~np.isin(directed[:, 1] * n + directed[:, 0], keys)]
    scale = _scale(xy)
    for i, j in boundary.tolist():
        side = ((xy[j, 0] - xy[i, 0]) * (xy[:, 1] - xy[i, 1])
                - (xy[j, 1] - xy[i, 1]) * (xy[:, 0] - xy[i, 0]))
        test.assertGreaterEqual(float(side.min()), -TOL * scale * scale, "borde no convexo")
    hull = _hull_area(xy)
    test.assertAlmostEqual(float(area2.sum()) / 2.0, hull, delta=TOL * hull)
    test.assertEqual(len(tri), 2 * n - len(boundary) - 2)
    present = _undirected(tri)
    for a, b in np.asarray(edges).tolist():
        test.assertIn((min(a, b), max(a, b)), present, f"falta la arista obligatoria {a}–{b}")


def _incircle(corners, points) -> tuple[np.ndarray, np.ndarray]:
    """Determinante de ``incircle`` (> 0: el punto está dentro) de triángulos ``corners``
    (..., 3, 2) con puntos ``points`` (..., 2), con difusión de numpy, y su escala (la suma
    de los valores absolutos de sus términos)."""
    d = corners - points[..., None, :]
    lift = (d * d).sum(-1)
    dx, dy = d[..., 0], d[..., 1]
    det = np.zeros(lift.shape[:-1])
    scale = np.zeros(lift.shape[:-1])
    for k in range(3):
        i, j = (k + 1) % 3, (k + 2) % 3
        det += lift[..., k] * (dx[..., i] * dy[..., j] - dx[..., j] * dy[..., i])
        scale += lift[..., k] * (np.abs(dx[..., i] * dy[..., j]) + np.abs(dx[..., j] * dy[..., i]))
    return det, scale


def _orient(o, a, b) -> np.ndarray:
    return ((a[..., 0] - o[..., 0]) * (b[..., 1] - o[..., 1])
            - (a[..., 1] - o[..., 1]) * (b[..., 0] - o[..., 0]))


def _blocked(p, q, segments) -> np.ndarray:
    """Para cada segmento p[i]–q[i], si cruza (en el interior de los dos) alguno de
    ``segments`` (k, 2, 2)."""
    if len(segments) == 0:
        return np.zeros(len(p), dtype=bool)
    a, b = segments[None, :, 0], segments[None, :, 1]
    pp, qq = p[:, None], q[:, None]
    crossing = ((_orient(a, b, pp) * _orient(a, b, qq) < 0)
                & (_orient(pp, qq, a) * _orient(pp, qq, b) < 0))
    return crossing.any(axis=1)


def _assert_delaunay(test, xy, edges, tri) -> None:
    """RF-006-13: ningún vértice dentro del círculo circunscrito de un triángulo salvo a
    través de una arista obligatoria (el segmento del centroide al vértice la cruza), y cada
    arista no obligatoria es localmente de Delaunay (el vértice opuesto del otro triángulo
    no está dentro), lo que basta para que sea la de Delaunay restringida."""
    corners = xy[tri]
    det, scale = _incircle(corners[:, None], xy[None, :])
    rows, inside = np.nonzero(det > TOL * scale)
    segments = xy[np.asarray(edges, dtype=np.int64)].reshape(-1, 2, 2)
    visible = ~_blocked(corners[rows].mean(axis=1), xy[inside], segments)
    if visible.any():
        k = int(np.argmax(visible))
        test.fail(f"el vértice {inside[k]} está dentro del círculo del triángulo {tri[rows[k]]}")
    n = len(xy)
    m = len(tri)
    u = tri.ravel().astype(np.int64)
    v = tri[:, [1, 2, 0]].ravel().astype(np.int64)
    apex = tri[:, [2, 0, 1]].ravel()
    owner = np.repeat(np.arange(m), 3)
    keys = u * n + v
    order = np.argsort(keys)
    where = np.searchsorted(keys[order], v * n + u)
    where = np.minimum(where, len(keys) - 1)
    twin = order[where]
    interior = keys[twin] == v * n + u
    fixed = np.array([min(a, b) * n + max(a, b) for a, b in np.asarray(edges).tolist()],
                     dtype=np.int64)
    free = interior & ~np.isin(np.minimum(u, v) * n + np.maximum(u, v), fixed)
    det, scale = _incircle(corners[owner[free]], xy[apex[twin[free]]])
    bad = det > TOL * scale
    if bad.any():
        k = int(np.argmax(bad))
        test.fail(f"la arista {u[free][k]}–{v[free][k]} no es localmente de Delaunay")


def _brute_delaunay(xy) -> set[tuple[int, int, int]]:
    """Los triángulos de Delaunay por fuerza bruta: los de círculo vacío (nube sin cuatro
    puntos cocirculares)."""
    triples = np.array(list(itertools.combinations(range(len(xy)), 3)))
    clockwise = _orient(xy[triples[:, 0]], xy[triples[:, 1]], xy[triples[:, 2]]) < 0
    triples[clockwise] = triples[clockwise][:, [0, 2, 1]]
    det, scale = _incircle(xy[triples][:, None], xy[None, :])
    empty = np.all(det <= TOL * scale, axis=1)
    return _canonical(triples[empty])


def _exact(*values):
    return [Fraction(v) for v in values]


def _orient_exact(a, b, c) -> Fraction:
    ax, ay, bx, by, cx, cy = _exact(*a, *b, *c)
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def _incircle_exact(a, b, c, d) -> Fraction:
    ax, ay, bx, by, cx, cy, dx, dy = _exact(*a, *b, *c, *d)
    rows = [(px - dx, py - dy) for px, py in ((ax, ay), (bx, by), (cx, cy))]
    lift = [u * u + v * v for u, v in rows]
    (adx, ady), (bdx, bdy), (cdx, cdy) = rows
    return (lift[0] * (bdx * cdy - cdx * bdy) + lift[1] * (cdx * ady - adx * cdy)
            + lift[2] * (adx * bdy - bdx * ady))


def _assert_exactly_delaunay(test, xy, edges, tri) -> None:
    """Como ``_assert_triangulation`` y ``_assert_delaunay``, pero con aritmética exacta:
    todos los triángulos con área positiva y ninguna arista no obligatoria con el vértice
    opuesto estrictamente dentro (para los casos casi degenerados)."""
    pts = [tuple(p) for p in xy.tolist()]
    for a, b, c in tri.tolist():
        test.assertGreater(_orient_exact(pts[a], pts[b], pts[c]), 0)
    n = len(pts)
    fixed = {(min(a, b), max(a, b)) for a, b in np.asarray(edges).tolist()}
    apex: dict[tuple[int, int], int] = {}
    for a, b, c in tri.tolist():
        apex[(a, b)], apex[(b, c)], apex[(c, a)] = c, a, b
    for (u, v), w in apex.items():
        other = apex.get((v, u))
        if other is None or (min(u, v), max(u, v)) in fixed:
            continue
        test.assertLessEqual(_incircle_exact(pts[w], pts[u], pts[v], pts[other]), 0)
    test.assertEqual(n, len(np.unique(tri)))


def _random_cloud(seed: int) -> np.ndarray:
    """Nube de 3 a 40 puntos al azar en coordenadas locales (±8 km del origen) y de 1 m a
    1 km de lado; una de cada cuatro, en una retícula (con alineaciones y cocircularidades
    exactas)."""
    rng = np.random.default_rng(1000 + seed)
    n = int(rng.integers(3, 41))
    offset = rng.uniform(-8000.0, 8000.0, 2).round(3)
    side = float(10.0 ** rng.uniform(0.0, 3.0))
    xy = rng.uniform(0.0, side, (n, 2))
    if seed % 4 == 3:
        step = side / 8.0
        xy = np.unique(np.round(xy / step) * step, axis=0)
    xy = xy + offset
    if len(xy) < 3 or abs(_hull_area(xy)) <= 1e-9 * side * side:
        xy = np.vstack([xy, offset + [0.0, 0.0], offset + [side, 0.0], offset + [0.0, side]])
        xy = np.unique(xy, axis=0)
    return xy


def _random_constraints(rng, xy, count: int) -> np.ndarray:
    """Hasta ``count`` aristas obligatorias al azar que no se cruzan ni pasan cerca (1 ‰ del
    lado) de otro punto."""
    n = len(xy)
    margin = 1e-3 * _scale(xy)
    chosen: list[tuple[int, int]] = []
    for _ in range(20 * count):
        if len(chosen) >= count:
            break
        i, j = (int(v) for v in rng.choice(n, 2, replace=False))
        a, b = xy[i], xy[j]
        ab = b - a
        t = np.clip(((xy - a) @ ab) / float(ab @ ab), 0.0, 1.0)
        dist = np.hypot(*(xy - (a + t[:, None] * ab)).T)
        dist[[i, j]] = np.inf
        if dist.min() <= margin or (min(i, j), max(i, j)) in chosen:
            continue
        segments = xy[np.array(chosen, dtype=np.int64)].reshape(-1, 2, 2)
        if _blocked(a[None], b[None], segments)[0]:
            continue
        chosen.append((min(i, j), max(i, j)))
    return _pairs(chosen)


class PortTest(unittest.TestCase):
    """ADR-0021: ``PureTriangulator`` cumple el puerto ``Triangulator`` y se llama
    ``pure@1`` (la versión del algoritmo va a la procedencia, RF-006-26)."""

    def test_port(self) -> None:
        triangulator = cdt.PureTriangulator()
        self.assertIsInstance(triangulator, ports.Triangulator)
        self.assertEqual(triangulator.name, "pure@1")
        self.assertEqual(cdt.NAME, "pure@1")
        self.assertIn("PureTriangulator", gis.__all__)
        self.assertIs(gis.PureTriangulator, cdt.PureTriangulator)

    def test_single_triangle_and_square(self) -> None:
        """RF-006-13: tres puntos dan un triángulo antihorario aunque lleguen en orden
        horario; un cuadrado, dos (sus 4 vértices son cocirculares)."""
        tri = _triangulate(_xy([(0.0, 0.0), (0.0, 1.0), (1.0, 0.0)]))
        self.assertEqual(_canonical(tri), {(0, 2, 1)})
        square = _xy([(10.0, 10.0), (11.0, 10.0), (11.0, 11.0), (10.0, 11.0)])
        tri = _triangulate(square)
        self.assertEqual(len(tri), 2)
        _assert_triangulation(self, square, NO_EDGES, tri)
        _assert_exactly_delaunay(self, square, NO_EDGES, tri)


class RandomCloudsTest(unittest.TestCase):
    """RF-006-13 en 200 nubes al azar (la mitad con aristas obligatorias)."""

    def test_constrained_delaunay_in_200_clouds(self) -> None:
        """Propiedad de Delaunay restringida (global con visibilidad y local de cada arista),
        aristas obligatorias como aristas, sin vértices nuevos y envolvente completa."""
        constrained = 0
        for seed in range(CLOUDS):
            xy = _xy(_random_cloud(seed))
            edges = NO_EDGES
            if seed % 2:
                rng = np.random.default_rng(5000 + seed)
                edges = _random_constraints(rng, xy, max(1, len(xy) // 3))
                constrained += len(edges) > 0
            with self.subTest(seed=seed, n=len(xy), edges=len(edges)):
                tri = _triangulate(xy, edges)
                _assert_triangulation(self, xy, edges, tri)
                _assert_delaunay(self, xy, edges, tri)
        self.assertGreaterEqual(constrained, 90)

    def test_equals_brute_force_delaunay(self) -> None:
        """Sin aristas obligatorias y sin cuatro puntos cocirculares, la triangulación es la
        de Delaunay (única), igual a la de fuerza bruta."""
        for seed in range(12):
            rng = np.random.default_rng(300 + seed)
            xy = _xy(rng.uniform(-50.0, 50.0, (int(rng.integers(4, 13)), 2)) + [-7000.0, 6000.0])
            with self.subTest(seed=seed):
                self.assertEqual(_canonical(_triangulate(xy)), _brute_delaunay(xy))

    def test_order_does_not_matter(self) -> None:
        """Con datos no degenerados la triangulación restringida es única: permutar los
        puntos y las aristas (y darles la vuelta) da los mismos triángulos."""
        for seed in range(10):
            rng = np.random.default_rng(700 + seed)
            xy = _xy(rng.uniform(0.0, 200.0, (60, 2)) + [3000.0, -5000.0])
            edges = _random_constraints(rng, xy, 12)
            perm = rng.permutation(len(xy))
            inverse = np.argsort(perm)
            moved = _xy(xy[perm])
            moved_edges = _pairs(inverse[np.asarray(edges)][rng.permutation(len(edges))][:, ::-1])
            with self.subTest(seed=seed):
                base = _triangulate(xy, edges)
                other = perm[_triangulate(moved, moved_edges)]
                self.assertEqual(_canonical(other), _canonical(base))

    def test_deterministic(self) -> None:
        """Mismas entradas, mismos triángulos en el mismo orden (bit a bit)."""
        xy = _xy(_random_cloud(7))
        edges = _random_constraints(np.random.default_rng(1), xy, 4)
        first = _triangulate(xy, edges)
        self.assertTrue(np.array_equal(first, _triangulate(xy, edges)))
        self.assertTrue(first.flags.c_contiguous)
        rows = first.tolist()
        self.assertEqual(rows, sorted(rows), "orden canónico: filas ordenadas")
        self.assertTrue(all(r[0] == min(r) for r in rows), "cada fila desde su menor índice")


class ConstraintsTest(unittest.TestCase):
    """RF-006-13: cada arista obligatoria es una arista del resultado."""

    def test_long_constraints_across_a_dense_cloud(self) -> None:
        """Roturas largas que cruzan cientos de triángulos (volteos de Sloan con
        cuadriláteros no convexos) y una rotura que ya es arista de Delaunay."""
        rng = np.random.default_rng(42)
        cloud = rng.uniform(0.0, 300.0, (300, 2))
        rails = [(x, y) for x in (20.0, 280.0) for y in (30.0, 90.0, 150.0, 210.0, 270.0)]
        xy = _xy(np.vstack([cloud, rails]) - [8000.0, -4000.0])
        first = len(cloud)
        edges = [(first + k, first + 5 + k) for k in range(5)]
        delaunay = _triangulate(xy)
        a, b = sorted(_undirected(delaunay))[0]
        edges.append((a, b))
        tri = _triangulate(xy, _pairs(edges))
        _assert_triangulation(self, xy, edges, tri)
        _assert_delaunay(self, xy, edges, tri)
        self.assertNotEqual(_canonical(tri), _canonical(delaunay))

    def test_polyline_and_repeated_edges(self) -> None:
        """Una polilínea con vértices comunes, una arista repetida al revés (se toma una
        vez) y aristas que acaban en el borde."""
        rng = np.random.default_rng(3)
        cloud = rng.uniform(0.0, 100.0, (80, 2))
        line = [(5.0 * k, 50.0 + 20.0 * math.sin(k / 3.0)) for k in range(21)]
        xy = _xy(np.vstack([line, cloud]))
        edges = [(k, k + 1) for k in range(20)] + [(4, 3)]
        tri = _triangulate(xy, _pairs(edges))
        _assert_triangulation(self, xy, edges, tri)
        _assert_delaunay(self, xy, edges, tri)

    def test_nearly_collinear_constraint(self) -> None:
        """Una restricción casi colineal con vértices a 10⁻⁷ m de ella por los dos lados, y
        una polilínea en zigzag de ±10⁻⁸ m: las aristas están, todos los triángulos tienen
        área positiva y la propiedad se cumple con aritmética exacta."""
        base = [(-5000.0, 2000.0), (-4900.0, 2000.0)]
        near = [(-4950.0, 2000.0 + 1e-7), (-4950.0, 2000.0 - 1e-7), (-4975.0, 2000.0 + 3e-8),
                (-4925.0, 2000.0 - 3e-8)]
        zigzag = [(-4990.0 + 10.0 * k, 2050.0 + (1e-8 if k % 2 else -1e-8)) for k in range(9)]
        ring = [(-4950.0 + 70.0 * math.cos(k), 2010.0 + 70.0 * math.sin(k)) for k in range(12)]
        xy = _xy(base + near + zigzag + ring)
        edges = [(0, 1)] + [(6 + k, 7 + k) for k in range(8)]
        tri = _triangulate(xy, _pairs(edges))
        _assert_triangulation(self, xy, edges, tri)
        _assert_exactly_delaunay(self, xy, edges, tri)

    def test_side_decided_only_by_exact_arithmetic(self) -> None:
        """Una restricción de 5,7 km en diagonal con un vértice a 10⁻¹³ m a cada lado de su
        centro: el filtro en float no decide de qué lado están (manda ``Fraction``), y la
        arista pasa entre los dos."""
        xy = _xy([(-6000.0, -2000.0), (-2000.0, 2000.0), (-4000.0, 1e-13), (-4000.0, -1e-13),
                  (-5000.0, 500.0), (-3000.0, -500.0), (-3500.0, 1200.0), (-4500.0, -1200.0)])
        a, b, c = xy[0].tolist(), xy[1].tolist(), xy[2].tolist()
        left = (a[0] - c[0]) * (b[1] - c[1])
        right = (a[1] - c[1]) * (b[0] - c[0])
        self.assertLessEqual(abs(left - right), cdt._CCW_BOUND * (abs(left) + abs(right)))
        self.assertEqual(cdt.orient2d(*a, *b, *c), 1)
        self.assertEqual(cdt.orient2d(*a, *b, *xy[3].tolist()), -1)
        tri = _triangulate(xy, _pairs([(0, 1)]))
        _assert_triangulation(self, xy, [(0, 1)], tri, slivers=True)
        _assert_exactly_delaunay(self, xy, [(0, 1)], tri)
        self.assertIn((0, 1), _undirected(tri))


class DegenerateTest(unittest.TestCase):
    """Casos degenerados (plan §7.2): sin fallo o con ``TriangulationError``."""

    def test_regular_grid(self) -> None:
        """Malla regular de 12 × 9 a 0,5 m lejos del origen (todos sus cuadrados son
        cocirculares): 2 triángulos por celda, cada uno medio cuadrado exacto, y una
        restricción en diagonal por celdas."""
        cols, rows = np.meshgrid(np.arange(12), np.arange(9))
        xy = _xy(np.column_stack([-7999.5 + 0.5 * cols.ravel(), 5000.25 + 0.5 * rows.ravel()]))
        diagonal = [(k * 12 + k, (k + 1) * 12 + k + 1) for k in range(8)]
        for edges in (NO_EDGES, _pairs(diagonal)):
            with self.subTest(edges=len(edges)):
                tri = _triangulate(xy, edges)
                self.assertEqual(len(tri), 2 * 11 * 8)
                _assert_triangulation(self, xy, edges, tri)
                _assert_exactly_delaunay(self, xy, edges, tri)
                p = xy[tri]
                area2 = ((p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1])
                         - (p[:, 1, 1] - p[:, 0, 1]) * (p[:, 2, 0] - p[:, 0, 0]))
                self.assertTrue(np.all(area2 == 0.25))

    def test_long_constraints_across_a_regular_grid(self) -> None:
        """Dos restricciones largas que atraviesan en oblicuo la malla regular de 12 × 9 sin
        pasar por ningún nudo: los volteos de Sloan encuentran cuadriláteros con tres
        vértices alineados (no convexos estrictos) y no los voltean."""
        cols, rows = np.meshgrid(np.arange(12), np.arange(9))
        xy = _xy(np.column_stack([-7999.5 + 0.5 * cols.ravel(), 5000.25 + 0.5 * rows.ravel()]))
        edges = [(0, 7 * 12 + 11), (2 * 12, 8 * 12 + 7)]
        tri = _triangulate(xy, _pairs(edges))
        _assert_triangulation(self, xy, edges, tri)
        _assert_exactly_delaunay(self, xy, edges, tri)

    def test_cocircular_points(self) -> None:
        """Los 12 puntos enteros del círculo de radio 5 (cocirculares exactos): 10
        triángulos; con el centro, el abanico de 12 desde él (única)."""
        circle = [(5, 0), (4, 3), (3, 4), (0, 5), (-3, 4), (-4, 3), (-5, 0), (-4, -3),
                  (-3, -4), (0, -5), (3, -4), (4, -3)]
        xy = _xy(np.array(circle, dtype=float) + [1234.0, -567.0])
        tri = _triangulate(xy)
        self.assertEqual(len(tri), 10)
        _assert_triangulation(self, xy, NO_EDGES, tri)
        _assert_exactly_delaunay(self, xy, NO_EDGES, tri)
        with_center = _xy(np.vstack([xy, [[1234.0, -567.0]]]))
        tri = _triangulate(with_center)
        self.assertEqual(_canonical(tri),
                         {min(((12, k, (k + 1) % 12), (k, (k + 1) % 12, 12),
                               ((k + 1) % 12, 12, k))) for k in range(12)})

    def test_nearly_cocircular_points(self) -> None:
        """24 puntos de un círculo calculados con ``cos`` y ``sin`` (cocirculares salvo el
        redondeo: el filtro no decide y manda la aritmética exacta), con y sin el centro."""
        ring = [(-6000.0 + 50.0 * math.cos(k * math.pi / 12), 3000.0
                 + 50.0 * math.sin(k * math.pi / 12)) for k in range(24)]
        for extra in ([], [(-6000.0, 3000.0)]):
            xy = _xy(ring + extra)
            with self.subTest(center=bool(extra)):
                tri = _triangulate(xy)
                _assert_triangulation(self, xy, NO_EDGES, tri)
                _assert_exactly_delaunay(self, xy, NO_EDGES, tri)
                if extra:
                    self.assertTrue(all(24 in t for t in tri.tolist()))

    def test_hull_edge_missed_by_the_super_triangle(self) -> None:
        """Un borde recto de 2 km (11 puntos cada 200 m) con un punto interior a 1 mm del
        centro de cada tramo: el círculo de cada triángulo del borde (radio 5.000 km) contiene
        el vértice del supertriángulo, así que la triangulación de Delaunay de todos deja fuera
        las 10 aristas del borde, y la envolvente convexa sigue completa (A9: se añaden como
        restricción) y de Delaunay."""
        top = [(-1000.0 + 200.0 * k, 2000.0) for k in range(11)]
        inner = [(-900.0 + 200.0 * k, 2000.0 - 0.001) for k in range(10)]
        bottom = [(-1000.0 + 2000.0 * t, 1990.0 - 9.0 * math.sin(math.pi * t))
                  for t in np.linspace(0.0, 1.0, 21)[1:-1]]
        xy = _xy(top + inner + bottom)
        tri = _triangulate(xy)
        _assert_triangulation(self, xy, NO_EDGES, tri)
        _assert_delaunay(self, xy, NO_EDGES, tri)
        border = {(k, 11 + k, k + 1) for k in range(10)}  # antihorarios, el borde arriba
        self.assertEqual(_canonical(tri) & border, border)
        with mock.patch.object(cdt, "SUPER_SCALE", 1.0):
            for seed in range(0, 40, 4):
                small = _xy(_random_cloud(seed))
                with self.subTest(seed=seed):
                    tri = _triangulate(small)
                    _assert_triangulation(self, small, NO_EDGES, tri)
                    _assert_delaunay(self, small, NO_EDGES, tri)

    def test_collinear_points_are_rejected(self) -> None:
        """Todos alineados (también en diagonal y lejos del origen) → error con el número de
        puntos; menos de 3 puntos → error."""
        line = [(-7000.0 + 0.5 * k, 3000.0 + 0.25 * k) for k in range(10)]
        for rows in (line, line[:3], [(1.0, 1.0), (1.0, 2.0), (1.0, -3.0)]):
            with self.subTest(n=len(rows)):
                error = _error(_xy(rows))
                self.assertEqual(error.code, "gis.triangulation_input")
                self.assertEqual((error.field, error.value), ("puntos", len(rows)))
                self.assertIn("alineados", str(error))
        for rows in ([], [(0.0, 0.0)], [(0.0, 0.0), (1.0, 1.0)]):
            with self.subTest(n=len(rows)):
                error = _error(_xy(rows))
                self.assertEqual(error.code, "gis.triangulation_input")
                self.assertIn("al menos 3", str(error))


class ErrorsTest(unittest.TestCase):
    """Lo que el contrato no admite: ``TriangulationError`` con el texto del catálogo (datos)
    o ``ValueError``/``TypeError`` (error del programa)."""

    def test_duplicate_points(self) -> None:
        xy = _xy([(0.0, 0.0), (5.0, 0.0), (0.0, 5.0), (5.0, 0.0), (2.0, 2.0)])
        error = _error(xy)
        self.assertIsInstance(error, gis.GisError)
        self.assertEqual(error.code, "gis.triangulation_input")
        self.assertEqual((error.field, error.value), ("vértice", 3))
        self.assertEqual(
            str(error),
            "El triangulador pure@1 no puede triangular estos datos: los vértices 1 y 3 "
            "coinciden en (5; 0).",
        )
        self.assertEqual(error.msgid, messages.MESSAGES["gis.triangulation_input"].msgid)

    def test_constraint_through_a_vertex(self) -> None:
        """Junto al extremo (en el abanico de 0) y lejos de él (al recorrer los triángulos
        que cruza)."""
        xy = _xy([(0.0, 0.0), (2.0, 2.0), (1.0, 1.0), (2.0, 0.0), (0.0, 2.0)])
        error = _error(xy, _pairs([(0, 1)]))
        self.assertEqual(error.code, "gis.triangulation_input")
        self.assertEqual((error.field, error.value), ("arista", "0–1"))
        self.assertIn("la arista obligatoria 0–1 pasa por el vértice 2", str(error))
        far = _xy([(0.0, 0.0), (10.0, 0.0), (5.0, 0.0), (2.5, 1.0), (2.5, -1.0), (7.5, 1.0),
                   (7.5, -1.0), (5.0, 3.0), (5.0, -3.0)])
        self.assertNotIn((0, 2), _undirected(_triangulate(far)))
        self.assertIn("la arista obligatoria 0–1 pasa por el vértice 2",
                      str(_error(far, _pairs([(0, 1)]))))

    def test_crossing_constraints(self) -> None:
        xy = _xy([(0.0, 0.0), (2.0, 2.0), (2.0, 0.0), (0.0, 2.0), (1.0, 3.0)])
        error = _error(xy, _pairs([(0, 1), (2, 3)]))
        self.assertEqual(error.code, "gis.triangulation_input")
        self.assertIn("las aristas obligatorias 2–3 y 0–1 se cruzan", str(error))

    def test_not_finite(self) -> None:
        error = _error(_xy([(0.0, 0.0), (1.0, 0.0), (math.nan, 1.0)]))
        self.assertEqual((error.field, error.value), ("vértice", 2))
        self.assertIn("no tiene coordenadas finitas", str(error))

    def test_program_errors(self) -> None:
        """Formas, tipos e índices que el contrato no admite: error del programa."""
        xy = _xy([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)])
        cases = (
            (ValueError, np.zeros((3, 3)), NO_EDGES),
            (ValueError, np.zeros(6), NO_EDGES),
            (TypeError, np.zeros((3, 2), dtype=np.int64), NO_EDGES),
            (ValueError, xy, np.zeros((1, 3), dtype=np.int32)),
            (TypeError, xy, np.zeros((1, 2))),
            (ValueError, xy, _pairs([(0, 3)])),
            (ValueError, xy, _pairs([(-1, 2)])),
            (ValueError, xy, _pairs([(1, 1)])),
        )
        for kind, points, edges in cases:
            with self.subTest(kind=kind.__name__, points=points.shape, edges=edges.shape), \
                    self.assertRaises(kind):
                _triangulate(points, edges)

    def test_inputs_untouched(self) -> None:
        """Las entradas de solo lectura no se tocan, y otros tipos válidos (float32,
        aristas int64) dan lo mismo."""
        xy = _xy(_random_cloud(1))
        edges = _random_constraints(np.random.default_rng(2), xy, 3)
        before = (xy.copy(), edges.copy())
        tri = _triangulate(xy, edges)
        self.assertTrue(np.array_equal(xy, before[0]) and np.array_equal(edges, before[1]))
        small = xy.astype(np.float32)
        self.assertTrue(np.array_equal(_triangulate(small, edges.astype(np.int64)),
                                       _triangulate(_xy(small), edges)))
        self.assertEqual(tri.dtype, np.int32)


class ContractTest(unittest.TestCase):
    """``check_contract``: el contrato del puerto, también para el triangulador de Blender
    (T23)."""

    def setUp(self) -> None:
        rng = np.random.default_rng(11)
        self.xy = _xy(rng.uniform(0.0, 100.0, (40, 2)))
        self.edges = _random_constraints(rng, self.xy, 5)
        self.tri = _triangulate(self.xy, self.edges)

    def _broken(self, tri, edges=None) -> str:
        with self.assertRaises(ports.TriangulationError) as caught:
            cdt.check_contract(self.xy, self.edges if edges is None else edges, tri,
                               name="prueba@0")
        self.assertEqual(caught.exception.code, "gis.triangulation_contract")
        self.assertIn("prueba@0", str(caught.exception))
        return str(caught.exception)

    def test_valid_output(self) -> None:
        cdt.check_contract(self.xy, self.edges, self.tri, name="prueba@0")

    def test_broken_outputs(self) -> None:
        """Un vértice nuevo, otro tipo, un triángulo de menos (con sus vértices en otros o
        dejando uno sin usar), uno horario, uno repetido y una arista obligatoria que falta."""
        tri = self.tri
        self.assertIn("vértice 40",
                      self._broken(np.vstack([tri[:-1], [[0, 1, 40]]]).astype(np.int32)))
        self.assertIn("int32", self._broken(tri.astype(np.int64)))
        counts = np.bincount(tri.ravel(), minlength=40)
        shared = next(r for r in range(len(tri)) if counts[tri[r]].min() >= 2)
        self.assertIn("envolvente", self._broken(np.delete(tri, shared, axis=0)))
        lonely = int(np.argmin(counts))
        self.assertIn(f"el vértice {lonely} no está en ningún triángulo",
                      self._broken(tri[~(tri == lonely).any(axis=1)]))
        self.assertIn("horario", self._broken(np.vstack([tri[:-1], tri[-1:, ::-1]])))
        self.assertIn("repetid", self._broken(np.vstack([tri, tri[:1]])))
        free = _triangulate(self.xy)
        absent = [e for e in _random_constraints(np.random.default_rng(9), self.xy, 40).tolist()
                  if (min(e), max(e)) not in _undirected(free)]
        self.assertIn("falta la arista obligatoria",
                      self._broken(free, _pairs(absent[:1])))


class ProgressTest(unittest.TestCase):
    """RF-006-28: avance y cancelación (para el trabajo ``gis_triangulate``)."""

    def test_progress_and_cancel(self) -> None:
        xy = _xy(np.random.default_rng(5).uniform(0.0, 50.0, (200, 2)))
        seen: list[float] = []
        with mock.patch.object(cdt, "PROGRESS_STEP", 16):
            _triangulate(xy, progress=lambda fraction, text: seen.append(fraction))
            self.assertGreater(len(seen), 5)
            self.assertEqual(seen, sorted(seen))
            self.assertEqual(seen[-1], 1.0)
            with self.assertRaises(worker_api.JobCancelled):
                _triangulate(xy, cancelled=lambda: True)


if __name__ == "__main__":
    unittest.main()
