# SPDX-License-Identifier: GPL-3.0-or-later
"""Caso de referencia de las curvas de nivel del cono (spec 006, T21; RF-006-18; plan 006
§5.4 A14 y §7.2).

Cono z = 900 − 0,5·r, con r la distancia en planta a su vértice (E0 + 60,3; N0 + 59,6), que
no cae en ningún nudo: la curva de cota L es el círculo de radio 2·(900 − L). Con los
parámetros por defecto (equidistancia 1 m, maestras cada 5 m, base 0, sin desfase, sin
simplificar ni longitud mínima):

- **Rejilla** de 120 × 120 celdas de 1 m (``contours_from_raster``): cotas de 858 a 899 m
  (la mínima de la rejilla es 857,9 m y la máxima, 899,89 m); cada vértice a **≤ 0,01 m del
  círculo** para r ≥ 20 m (L ≤ 890 m): A14 interpola linealmente en las aristas de 1 m entre
  centros y el error es la flecha de la cuerda de r(s), ≤ 1/(8·(r − 1)) ≈ 0,0066 m a 20 m;
  cada vértice con Z = L y sobre la superficie interpolada linealmente (|Δz| ≤ 1 mm); un
  anillo cerrado y antihorario por cota mientras el círculo cabe entre los centros (r ≤ 58 m,
  L ≥ 871 m) y arcos abiertos con los extremos en el borde las demás; maestras, las 8 cotas
  múltiplos de 5 (860 a 895 m).
- **TIN** con lados de 1 m (malla de triángulos equiláteros de 121 × 140 nudos sobre el cono,
  ``contours_from_tin``): las mismas propiedades, con los extremos de los arcos en aristas
  de borde. El TIN de los centros de la rejilla (``raster_to_tin``) tiene diagonales de √2 m
  y su flecha llega a 2/(8·r): 0,012 m a 20 m (≤ 0,01 m desde 25 m); por eso la referencia de
  un TIN, como la de una rejilla «con celda de 1 m», tiene lados de 1 m.
"""

import math
import unittest

import numpy as np

from tests.support.package import import_geoblender

gis = import_geoblender("gis")
georef = import_geoblender("core.georef")

E0, N0 = 700_000.0, 4_400_000.0
CATALOG = georef.load_catalog()
SIZE = 120  # celdas por lado de la rejilla
LATTICE = (121, 140)  # nudos por fila y filas de la malla de triángulos equiláteros
APEX = (E0 + 60.3, N0 + 59.6)
TOP, SLOPE = 900.0, 0.5
LEVELS = [float(level) for level in range(858, 900)]
CLOSED_RADIUS_M = 58.0  # el mayor círculo (r = 2·(900 − L)) que cabe entre los nudos
CIRCLE_TOLERANCE_M = 0.01  # RF-006-18
SURFACE_TOLERANCE_M = 0.001  # RF-006-18
MIN_RADIUS_M = 20.0  # RF-006-18


def _height(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return TOP - SLOPE * np.hypot(x - APEX[0], y - APEX[1])


def _cone():
    grid = gis.Grid(west=E0, north=N0 + SIZE, dx=1.0, dy=1.0, ncols=SIZE, nrows=SIZE)
    x, y = grid.centers()
    values = _height(x, y)
    values.flags.writeable = False
    return gis.Raster(grid, values, CATALOG.horizontal(25830), CATALOG.vertical(5782))


def _lattice_tin():
    """TIN de triángulos equiláteros de 1 m de lado (filas a √3/2 m, las impares desplazadas
    medio metro), antihorarios, con sus nudos sobre el cono."""
    nx, ny = LATTICE
    rows, cols = np.divmod(np.arange(nx * ny, dtype=np.int64), nx)
    x = E0 + cols + 0.5 * (rows % 2)
    y = N0 + rows * (math.sqrt(3.0) / 2.0)
    i, j = np.meshgrid(np.arange(nx - 1), np.arange(ny - 1))
    i, j = i.ravel(), j.ravel()
    here, up = j * nx + i, (j + 1) * nx + i
    even = j % 2 == 0
    first = np.where(even[:, None], np.column_stack([here, here + 1, up]),
                     np.column_stack([here, up + 1, up]))
    second = np.where(even[:, None], np.column_stack([here + 1, up + 1, up]),
                      np.column_stack([here, here + 1, up + 1]))
    vertices = np.column_stack([x, y, _height(x, y)])
    vertices.flags.writeable = False
    return gis.Tin(vertices, np.vstack([first, second]).astype(np.int32),
                   np.empty((0, 2), dtype=np.int32), np.zeros(len(x), dtype=np.uint8))


def _radius(level: float) -> float:
    return (TOP - level) / SLOPE


def _distance_to_circle(line) -> np.ndarray:
    xy = line.xyz[:, :2]
    return np.abs(np.hypot(xy[:, 0] - APEX[0], xy[:, 1] - APEX[1]) - _radius(line.elevation))


def _signed_area(line) -> float:
    x = line.xyz[:, 0] - APEX[0]
    y = line.xyz[:, 1] - APEX[1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def _grid_edge_z(raster, xyz: np.ndarray) -> np.ndarray:
    """La cota interpolada linealmente en la arista entre centros que contiene cada punto
    (una de sus coordenadas es la de una fila o una columna de centros, bit a bit; NaN si no
    está en ninguna)."""
    g = raster.grid
    v = raster.values
    xs = g.west + (np.arange(g.ncols) + 0.5) * g.dx
    ys = g.north - (np.arange(g.nrows) + 0.5) * g.dy
    x, y = xyz[:, 0], xyz[:, 1]
    out = np.full(len(x), math.nan)
    row = np.minimum(np.searchsorted(-ys, -y), g.nrows - 1)
    col = np.minimum(np.searchsorted(xs, x), g.ncols - 1)
    on_row = ys[row] == y
    on_col = ~on_row & (xs[col] == x)
    c = np.clip(np.searchsorted(xs, x, side="right") - 1, 0, g.ncols - 2)
    s = (x - xs[c]) / (xs[c + 1] - xs[c])
    out[on_row] = (v[row, c] + s * (v[row, c + 1] - v[row, c]))[on_row]
    r = np.clip(np.searchsorted(-ys, -y, side="right") - 1, 0, g.nrows - 2)
    s = (ys[r] - y) / (ys[r] - ys[r + 1])
    out[on_col] = (v[r, col] + s * (v[r + 1, col] - v[r, col]))[on_col]
    return out


def _tin_reference(tin, xyz: np.ndarray):
    """Para cada punto: la distancia en planta a la arista del TIN más cercana entre las que
    tocan su cubeta, la cota interpolada linealmente en ella y si es de borde (de un solo
    triángulo). Cada arista va a todas las cubetas (del lado de la arista mediana) que toca su
    caja ampliada 1 mm: la que contiene un punto está en la cubeta del punto."""
    f = tin.faces.astype(np.int64)
    pairs = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1)
    count = len(tin.vertices)
    unique, counts = np.unique(pairs[:, 0] * count + pairs[:, 1], return_counts=True)
    edges = np.column_stack(np.divmod(unique, count))
    a, b = tin.vertices[edges[:, 0]], tin.vertices[edges[:, 1]]
    size = float(np.median(np.hypot(b[:, 0] - a[:, 0], b[:, 1] - a[:, 1])))
    left, bottom = tin.vertices[:, 0].min() - 1.0, tin.vertices[:, 1].min() - 1.0

    def cells(x, y):
        return (np.floor((x - left) / size).astype(np.int64),
                np.floor((y - bottom) / size).astype(np.int64))

    x0, y0 = cells(np.minimum(a[:, 0], b[:, 0]) - 1e-3, np.minimum(a[:, 1], b[:, 1]) - 1e-3)
    x1, y1 = cells(np.maximum(a[:, 0], b[:, 0]) + 1e-3, np.maximum(a[:, 1], b[:, 1]) + 1e-3)
    height = y1 - y0 + 1
    spans = (x1 - x0 + 1) * height
    owner = np.repeat(np.arange(len(edges)), spans)
    local = np.arange(int(spans.sum())) - np.repeat(np.cumsum(spans) - spans, spans)
    stride = int(y1.max()) + 2
    keys = (x0[owner] + local // height[owner]) * stride + y0[owner] + local % height[owner]
    order = np.argsort(keys, kind="stable")
    keys, owner = keys[order], owner[order]
    px, py = cells(xyz[:, 0], xyz[:, 1])
    wanted = px * stride + py
    lo = np.searchsorted(keys, wanted, side="left")
    hi = np.searchsorted(keys, wanted, side="right")
    point = np.repeat(np.arange(len(xyz)), hi - lo)
    edge = owner[np.arange(len(point)) - np.repeat(np.cumsum(hi - lo) - (hi - lo) - lo, hi - lo)]
    pa, pb, p = a[edge], b[edge], xyz[point]
    ux, uy = pb[:, 0] - pa[:, 0], pb[:, 1] - pa[:, 1]
    t = np.clip(((p[:, 0] - pa[:, 0]) * ux + (p[:, 1] - pa[:, 1]) * uy) / (ux * ux + uy * uy),
                0.0, 1.0)
    d = np.hypot(pa[:, 0] + t * ux - p[:, 0], pa[:, 1] + t * uy - p[:, 1])
    pick = np.lexsort((d, point))
    found, first = np.unique(point[pick], return_index=True)
    assert len(found) == len(xyz), "un punto sin ninguna arista en su cubeta"
    best = pick[first]
    return d[best], pa[best, 2] + t[best] * (pb[best, 2] - pa[best, 2]), counts[edge[best]] == 1

class ConeContoursReferenceTest(unittest.TestCase):
    """RF-006-18: curvas del cono z = 900 − 0,5·r con celda (o lado) de 1 m."""

    def _check(self, lines, surface_z, open_end) -> float:
        """Cotas, maestras, Z, círculo, superficie, anillos cerrados y arcos abiertos; el
        mayor error frente al círculo para r ≥ 20 m."""
        by_level: dict[float, list] = {}
        for line in lines:
            by_level.setdefault(line.elevation, []).append(line)
            self.assertTrue((line.xyz[:, 2] == line.elevation).all())
            self.assertEqual(line.is_index, line.elevation % 5 == 0)
        self.assertEqual(sorted(by_level), LEVELS)
        self.assertEqual(sum(group[0].is_index for group in by_level.values()), 8)
        worst = max(float(_distance_to_circle(line).max()) for line in lines
                    if _radius(line.elevation) >= MIN_RADIUS_M)
        self.assertLessEqual(worst, CIRCLE_TOLERANCE_M)
        xyz = np.vstack([line.xyz for line in lines])
        self.assertLessEqual(float(np.abs(surface_z(xyz) - xyz[:, 2]).max()),
                             SURFACE_TOLERANCE_M)
        ends = []
        for level, group in by_level.items():
            if _radius(level) <= CLOSED_RADIUS_M:
                self.assertEqual(len(group), 1, level)
                self.assertTrue(group[0].closed, level)
                self.assertGreater(_signed_area(group[0]), 0.0)  # antihorario: lo alto dentro
            else:
                self.assertFalse(any(line.closed for line in group), level)
                ends.extend(line.xyz[[0, -1]] for line in group)
        self.assertTrue(open_end(np.vstack(ends)).all())
        return worst

    def test_grid_contours_of_the_cone(self) -> None:
        """RF-006-18: rejilla de 1 m: vértices a ≤ 0,01 m del círculo para r ≥ 20 m,
        |Δz| ≤ 1 mm sobre la superficie interpolada, anillos cerrados dentro, arcos abiertos
        con los extremos en el borde y maestras cada 5 m."""
        raster = _cone()
        grid = raster.grid
        low = (grid.west + 0.5, grid.north - SIZE + 0.5)
        high = (grid.west + SIZE - 0.5, grid.north - 0.5)

        def on_border(xyz):
            x, y = xyz[:, 0], xyz[:, 1]
            return (x == low[0]) | (x == high[0]) | (y == low[1]) | (y == high[1])

        worst = self._check(gis.contours_from_raster(raster),
                            lambda xyz: _grid_edge_z(raster, xyz), on_border)
        self.assertGreater(worst, 0.0)

    def test_tin_contours_of_the_cone(self) -> None:
        """RF-006-18: TIN de lados de 1 m: las mismas propiedades (vértices en aristas del TIN
        y sobre él, a ≤ 0,01 m del círculo para r ≥ 20 m; extremos de los arcos en aristas de
        borde)."""
        tin = _lattice_tin()

        def surface(xyz):
            distance, z, _border = _tin_reference(tin, xyz)
            self.assertLessEqual(float(distance.max()), 1e-6)
            return z

        def on_border(xyz):
            distance, _z, border = _tin_reference(tin, xyz)
            return (distance <= 1e-6) & border

        self._check(gis.contours_from_tin(tin), surface, on_border)


if __name__ == "__main__":
    unittest.main()
