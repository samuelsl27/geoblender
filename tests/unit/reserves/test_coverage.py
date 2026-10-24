# SPDX-License-Identifier: GPL-3.0-or-later
"""Fracción exacta del área de cada celda dentro de un polígono (spec 011, T06; HU-011-2;
RF-011-01, RF-011-07; plan 011 A5, D-5 y D-21).

``reserves.coverage`` reparte una celda entre polígonos por la **fracción exacta de su área**
que queda dentro de cada uno (D-5), no por su centro: el área de cada dominio es la de su
polígono y uno menor que una celda recibe lo suyo. Se calcula desde las aristas orientadas del
polígono (exterior antihorario, huecos horarios), en metros relativos a la esquina suroeste de la
rejilla, con el área con signo acumulada por filas (A5), y por bandas de filas.

- ``polygon_edges``: los anillos absolutos de un polígono (el primero, el exterior) como aristas
  orientadas relativas a la esquina suroeste, con los sentidos normalizados.
- ``band_coverage``: las celdas tocadas de una banda de filas, con su fracción (0..1).

Las referencias de las pruebas son independientes del cálculo: el área exacta del polígono de
coordenadas float64 (fórmula del área con ``fractions.Fraction``) y la de su recorte por cada
celda o cada fila (Sutherland–Hodgman contra un rectángulo).
"""

from __future__ import annotations

import math
import unittest
from fractions import Fraction

import numpy as np

from tests.support import res_fixtures as fx
from tests.support.package import import_geoblender

coverage = import_geoblender("reserves.coverage")
gis = import_geoblender("gis")

Grid = gis.Grid

WEST = 735_000.0
SOUTH = 4_434_000.0
TOLERANCE = 1e-12
"""Error relativo admitido (área) y absoluto (fracción de una celda) del cálculo exacto."""


# Referencias independientes -------------------------------------------------------------------


def _open(ring: np.ndarray) -> np.ndarray:
    ring = np.asarray(ring, dtype=np.float64)[:, :2]
    return ring[:-1] if np.array_equal(ring[0], ring[-1]) else ring


def _exact_area(ring: np.ndarray) -> float:
    """El área (≥ 0, m²) del anillo de coordenadas float64, exacta (racional) y redondeada."""
    points = [(Fraction(float(x)), Fraction(float(y))) for x, y in _open(ring)]
    twice = sum(
        (x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1])),
        Fraction(0),
    )
    return float(abs(twice) / 2)


def _clip_area(ring: np.ndarray, xmin: float, ymin: float, xmax: float, ymax: float) -> float:
    """El área (m²) del anillo recortado por el rectángulo (Sutherland–Hodgman, que basta con
    un polígono convexo o, como aquí, con el recorte por un rectángulo de uno simple)."""
    # Respecto a la esquina del rectángulo: el área del recorte, con números pequeños.
    points = [tuple(p) for p in (_open(ring) - np.array([xmin, ymin])).tolist()]
    xmax, ymax = xmax - xmin, ymax - ymin
    xmin = ymin = 0.0
    for axis, bound, keep_low in ((0, xmin, False), (0, xmax, True), (1, ymin, False),
                                  (1, ymax, True)):
        if not points:
            return 0.0
        inside = (lambda p: p[axis] <= bound) if keep_low else (lambda p: p[axis] >= bound)
        out = []
        for current, following in zip(points, points[1:] + points[:1]):
            if inside(current):
                out.append(current)
            if inside(current) != inside(following):
                t = (bound - current[axis]) / (following[axis] - current[axis])
                cut = [current[0] + t * (following[0] - current[0]),
                       current[1] + t * (following[1] - current[1])]
                cut[axis] = bound
                out.append(tuple(cut))
        points = out
    if len(points) < 3:
        return 0.0
    return abs(math.fsum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1)
                         in zip(points, points[1:] + points[:1]))) / 2.0


def _relative(ring: np.ndarray, grid) -> np.ndarray:
    """El anillo en metros relativos a la esquina suroeste de ``grid`` (exacto: Sterbenz)."""
    return _open(ring) - np.array([grid.west, grid.north - grid.nrows * grid.dy])


def _cell_box(grid, row: int, col: int) -> tuple[float, float, float, float]:
    """La celda ``(row, col)`` en metros relativos a la esquina suroeste."""
    bottom = (grid.nrows - 1 - row) * grid.dy
    return (col * grid.dx, bottom, (col + 1) * grid.dx, bottom + grid.dy)


def _dense(band, grid) -> np.ndarray:
    """La banda como array ``(nrows, ncols)`` de la rejilla (cero en las celdas no tocadas)."""
    out = np.zeros(grid.shape)
    out[band.rows, band.cols] = band.fraction
    return out


def _area(band, grid) -> float:
    """El área (m²) de la banda: Σ fracción × área de celda (suma por pares de numpy)."""
    return float(np.sum(band.fraction)) * grid.cell_area


def _whole(rings, grid):
    return coverage.band_coverage(coverage.polygon_edges(rings, grid), grid, slice(None))


def _rotated(points, angle: float, center: tuple[float, float]) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.asarray(points, dtype=np.float64) @ np.array([[c, s], [-s, c]]) + np.array(center)


def _rectangle_with_hole() -> tuple[np.ndarray, np.ndarray]:
    """Un rectángulo de 80 × 50 m girado 0,37 rad, con un hueco triangular (antihorario y
    horario), centrado en un punto cualquiera de una ventana de 120 m."""
    center = (WEST + 60.37, SOUTH + 60.81)
    outer = _rotated([[-40, -25], [40, -25], [40, 25], [-40, 25]], 0.37, center)
    hole = _rotated([[-5, -5], [0, 8], [5, -5]], 0.37, center)
    return outer, hole


def _window_grid(step: float, size: float = 120.0, dx: float | None = None,
                 dy: float | None = None) -> object:
    dx = step if dx is None else dx
    dy = step if dy is None else dy
    count = round(size / step)
    return Grid(WEST, SOUTH + count * dy, dx, dy, count, count)


def _wavy(p: np.ndarray, q: np.ndarray, count: int, amplitude: float, seed: int) -> np.ndarray:
    t = np.linspace(0.0, 1.0, count)
    points = p[None, :] + t[:, None] * (q - p)[None, :]
    normal = np.array([-(q - p)[1], (q - p)[0]]) / math.hypot(*(q - p))
    offset = amplitude * np.sin(np.pi * t * (3 + seed % 5)) * np.sin(np.pi * t)
    return points + offset[:, None] * normal[None, :]


def _partition(grid) -> tuple[list[np.ndarray], np.ndarray]:
    """20 polígonos (5 × 4) que parten un rectángulo de la ventana, con bordes interiores
    ondulados **comunes** (cada lado se genera una vez y el vecino lo recorre al revés; los
    del rectángulo, rectos), y ese rectángulo (como el prototipo del plan, §2.2, más pequeño)."""
    west, south = grid.west, grid.north - grid.nrows * grid.dy
    xs = np.linspace(west + 7.3, west + grid.ncols * grid.dx - 9.1, 6)
    ys = np.linspace(south + 5.7, south + grid.nrows * grid.dy - 6.2, 5)
    sides: dict[tuple, np.ndarray] = {}

    def side(p: np.ndarray, q: np.ndarray) -> np.ndarray:
        key = (tuple(p), tuple(q))
        if key[::-1] in sides:
            return sides[key[::-1]][::-1]
        if key not in sides:
            straight = (p[0] == q[0] and p[0] in (xs[0], xs[-1])) or (
                p[1] == q[1] and p[1] in (ys[0], ys[-1]))
            seed = int(abs(p[0] * 7 + p[1] * 13 + q[0] * 3 + q[1])) % 97
            sides[key] = _wavy(p, q, 40, 0.0 if straight else 2.5, seed)
        return sides[key]

    polygons = []
    for i in range(5):
        for j in range(4):
            a, b = np.array([xs[i], ys[j]]), np.array([xs[i + 1], ys[j]])
            c, d = np.array([xs[i + 1], ys[j + 1]]), np.array([xs[i], ys[j + 1]])
            polygons.append(np.concatenate(
                [side(a, b)[:-1], side(b, c)[:-1], side(c, d)[:-1], side(d, a)[:-1]]))
    outer = np.array([[xs[0], ys[0]], [xs[-1], ys[0]], [xs[-1], ys[-1]], [xs[0], ys[-1]]])
    return polygons, outer


def _assert_bounded(case: unittest.TestCase, band) -> None:
    """Ninguna fracción fuera de [0, 1] (salvo 10⁻¹²) ni nula; filas y columnas en orden."""
    case.assertEqual(band.rows.dtype, np.int64)
    case.assertEqual(band.cols.dtype, np.int64)
    case.assertEqual(band.fraction.dtype, np.float64)
    if band.fraction.size:
        case.assertGreaterEqual(float(band.fraction.min()), -TOLERANCE)
        case.assertLessEqual(float(band.fraction.max()), 1.0 + TOLERANCE)
        case.assertTrue(np.all(band.fraction != 0.0))
        key = band.rows * (int(band.cols.max()) + 1) + band.cols
        case.assertTrue(np.all(np.diff(key) > 0), "celdas repetidas o desordenadas")


# Pruebas ---------------------------------------------------------------------------------------


class AreaTest(unittest.TestCase):
    def test_a_rotated_rectangle_with_a_hole_gives_its_area(self) -> None:
        """RF-011-01, RF-011-07, D-5: un rectángulo girado con un hueco da su área exacta (≤ 10⁻¹²
        relativo) con celdas de 2, 1 y 0,5 m, y también con las celdas de B24 (que no miden 1 m);
        cada fila, la de su franja, y cada celda de unas filas, la de su recorte; ninguna
        fracción fuera de [0, 1]."""
        outer, hole = _rectangle_with_hole()
        exact = _exact_area(outer) - _exact_area(hole)
        grids = [_window_grid(step) for step in fx.PYRAMID_STEPS]
        grids.append(_window_grid(1.0, dx=1.0002942907592702, dy=1.0003022974607014))
        for grid in grids:
            with self.subTest(dx=grid.dx, dy=grid.dy):
                band = _whole([outer, hole], grid)
                _assert_bounded(self, band)
                area = _area(band, grid)
                self.assertLessEqual(abs(area - exact) / exact, TOLERANCE)
                cells = _dense(band, grid)
                rel_outer, rel_hole = _relative(outer, grid), _relative(hole, grid)
                width = grid.ncols * grid.dx
                for row in range(grid.nrows):
                    xmin, ymin, _, ymax = _cell_box(grid, row, 0)
                    strip = (_clip_area(rel_outer, xmin, ymin, width, ymax)
                             - _clip_area(rel_hole, xmin, ymin, width, ymax))
                    self.assertAlmostEqual(float(np.sum(cells[row])) * grid.cell_area, strip,
                                           delta=TOLERANCE * exact, msg=f"fila {row}")
                for row in (grid.nrows // 2, grid.nrows // 4):   # por el hueco y por un lado
                    for col in range(grid.ncols):
                        box = _cell_box(grid, row, col)
                        expected = (_clip_area(rel_outer, *box)
                                    - _clip_area(rel_hole, *box)) / grid.cell_area
                        self.assertAlmostEqual(cells[row, col], expected, delta=TOLERANCE,
                                               msg=f"celda {row}, {col}")

    def test_a_polygon_smaller_than_a_cell_gets_its_fraction(self) -> None:
        """RF-011-07, D-5: un triángulo de 0,2 m² dentro de una celda de 1 m recibe 0,2 (y 0,05
        con 2 m), donde con el centro de celda podría no recibir nada; uno que cae sobre un
        nodo se reparte entre sus cuatro celdas por el área de cada trozo."""
        inside = np.array([[0.2, 0.1], [0.7, 0.1], [0.4, 0.9]]) + [WEST + 13.0, SOUTH + 7.0]
        for step, fraction in ((1.0, 0.2), (2.0, 0.05)):
            with self.subTest(step=step):
                grid = _window_grid(step, size=40.0)
                band = _whole([inside], grid)
                _assert_bounded(self, band)
                self.assertEqual(band.fraction.size, 1)
                # 0,2 m² salvo el redondeo de sus vértices absolutos (≈ 10⁻¹⁰ m²).
                self.assertAlmostEqual(float(band.fraction[0]), fraction, delta=1e-9)
                self.assertAlmostEqual(float(band.fraction[0]),
                                       _exact_area(inside) / grid.cell_area, delta=TOLERANCE)
                row, col = int(band.rows[0]), int(band.cols[0])
                self.assertEqual((row, col), (grid.nrows - 1 - int(7.0 // step),
                                              int(13.0 // step)))
        grid = _window_grid(1.0, size=40.0)
        on_node = _rotated([[-0.31, -0.22], [0.27, -0.29], [0.33, 0.24], [-0.26, 0.31]], 0.2,
                           (WEST + 20.0, SOUTH + 11.0))
        band = _whole([on_node], grid)
        _assert_bounded(self, band)
        self.assertEqual(band.fraction.size, 4)
        rel = _relative(on_node, grid)
        for row, col, value in zip(band.rows, band.cols, band.fraction, strict=True):
            box = _cell_box(grid, int(row), int(col))
            self.assertAlmostEqual(float(value), _clip_area(rel, *box) / grid.cell_area,
                                   delta=TOLERANCE)
        self.assertAlmostEqual(math.fsum(band.fraction), _exact_area(on_node), delta=TOLERANCE)

    def test_a_polygon_beyond_the_grid_counts_only_its_cells_inside(self) -> None:
        """RF-011-07: un polígono que sale de la rejilla por los cuatro lados da en cada celda
        su trozo; uno que la cubre entera, 1 en todas; uno entero fuera, ninguna celda."""
        grid = _window_grid(2.0, size=40.0)
        big = _rotated([[-30, -30], [30, -30], [30, 30], [-30, 30]], 0.61,
                       (WEST + 17.3, SOUTH + 22.9))
        band = _whole([big], grid)
        _assert_bounded(self, band)
        cells = _dense(band, grid)
        rel = _relative(big, grid)
        for row in range(0, grid.nrows, 3):
            for col in range(grid.ncols):
                box = _cell_box(grid, row, col)
                self.assertAlmostEqual(cells[row, col], _clip_area(rel, *box) / grid.cell_area,
                                       delta=TOLERANCE, msg=f"celda {row}, {col}")
        cover = np.array([[-5.0, -7.0], [60.0, -7.0], [60.0, 50.0], [-5.0, 50.0]])
        band = _whole([cover + [WEST, SOUTH]], grid)
        self.assertEqual(band.fraction.size, grid.ncols * grid.nrows)
        self.assertTrue(np.all(np.abs(band.fraction - 1.0) <= TOLERANCE))
        away = np.array([[45.0, 1.0], [52.0, 1.0], [48.0, 9.0]]) + [WEST, SOUTH]
        self.assertEqual(_whole([away], grid).fraction.size, 0)
        west_of = np.array([[-9.0, 1.0], [-2.0, 1.0], [-4.0, 9.0]]) + [WEST, SOUTH]
        self.assertEqual(_whole([west_of], grid).fraction.size, 0)


class DirectionTest(unittest.TestCase):
    def test_ring_directions_are_normalized(self) -> None:
        """RF-011-07, A5: el exterior queda antihorario y los huecos horarios, vengan como
        vengan y cerrados o no; un hueco en el mismo sentido que el exterior se sigue restando."""
        outer, hole = _rectangle_with_hole()
        grid = _window_grid(1.0)
        reference = _whole([outer, hole], grid)
        closed = [np.vstack([ring, ring[:1]]) for ring in (outer, hole)]
        for name, rings in (
            ("cerrados", closed),
            ("exterior horario", [outer[::-1], hole]),
            ("hueco antihorario", [outer, hole[::-1]]),
            ("los dos al revés y cerrados", [closed[0][::-1], closed[1][::-1]]),
        ):
            with self.subTest(name):
                edges = coverage.polygon_edges(rings, grid)
                self.assertEqual(edges.shape, (7, 2, 2))
                self.assertGreater(coverage.signed_area(edges[:4, 0]), 0.0)
                self.assertLess(coverage.signed_area(edges[4:, 0]), 0.0)
                for ring in (edges[:4], edges[4:]):   # cada anillo, una cadena cerrada
                    np.testing.assert_array_equal(ring[:, 1], np.roll(ring[:, 0], -1, axis=0))
                band = coverage.band_coverage(edges, grid, slice(None))
                np.testing.assert_array_equal(band.rows, reference.rows)
                np.testing.assert_array_equal(band.cols, reference.cols)
                np.testing.assert_allclose(band.fraction, reference.fraction, rtol=0.0,
                                           atol=TOLERANCE)
        self.assertGreater(coverage.signed_area(outer), 0.0)
        self.assertLess(coverage.signed_area(outer[::-1]), 0.0)
        self.assertAlmostEqual(abs(coverage.signed_area(closed[0])), _exact_area(outer),
                               delta=TOLERANCE * _exact_area(outer))


class PartitionTest(unittest.TestCase):
    def test_the_pyramid_quadrants_sum_one_in_every_cell(self) -> None:
        """RF-011-07, CE-011-01: los cuatro cuadrantes de la pirámide parten la ventana: en cada
        celda, sus fracciones suman 1 (≤ 10⁻¹²) con 2, 1 y 0,5 m y el vértice en un nodo, en un
        centro de celda o en cualquier sitio; cada cuadrante, su área exacta."""
        for step in fx.PYRAMID_STEPS:
            grid = fx.pyramid_grid(step)
            apexes = fx.pyramid_apexes(step)
            # En un nodo, en el centro de una celda (y) y en cualquier sitio; con 0,5 m, dos.
            chosen = (apexes[0], apexes[23]) if step < 1.0 else (apexes[0], apexes[6], apexes[23])
            for apex in chosen:
                with self.subTest(step=step, apex=apex):
                    total = np.zeros(grid.shape)
                    for quadrant in fx.pyramid_quadrants(apex):
                        band = _whole(quadrant.rings, grid)
                        _assert_bounded(self, band)
                        area = _area(band, grid)
                        exact = _exact_area(quadrant.rings[0])
                        self.assertLessEqual(abs(area - exact) / exact, TOLERANCE)
                        total[band.rows, band.cols] += band.fraction
                    self.assertLessEqual(float(np.abs(total - 1.0).max()), TOLERANCE)

    def test_twenty_polygons_with_shared_borders_sum_one_in_every_covered_cell(self) -> None:
        """RF-011-07, D-5: 20 polígonos con bordes comunes ondulados que parten un rectángulo
        suman en cada celda la fracción de ese rectángulo (≤ 10⁻¹²): 1 en las celdas cubiertas
        del todo; ninguna fracción fuera de [0, 1]; las áreas suman la del rectángulo."""
        grid = Grid(WEST, SOUTH + 90.0, 1.0, 1.0, 110, 90)
        polygons, outer = _partition(grid)
        total = np.zeros(grid.shape)
        areas = []
        for ring in polygons:
            band = _whole([ring], grid)
            _assert_bounded(self, band)
            total[band.rows, band.cols] += band.fraction
            areas.append(_area(band, grid))
        union = _dense(_whole([outer], grid), grid)
        self.assertLessEqual(float(np.abs(total - union).max()), TOLERANCE)
        full = union == 1.0
        self.assertGreater(int(full.sum()), 7_000)
        self.assertLessEqual(float(np.abs(total[full] - 1.0).max()), TOLERANCE)
        exact = _exact_area(outer)
        self.assertLessEqual(abs(math.fsum(areas) - exact) / exact, TOLERANCE)


class BandTest(unittest.TestCase):
    def test_by_bands_gives_the_same_as_at_once(self) -> None:
        """RF-011-07, A5: por bandas de filas (de 1, 7 y 64 filas) sale bit a bit lo mismo que de
        una vez, y cada banda solo da celdas de sus filas."""
        grid = Grid(WEST, SOUTH + 90.0, 1.0, 1.0, 110, 90)
        polygons, _ = _partition(grid)
        outer, hole = _rectangle_with_hole()
        cases = [[polygons[0]], [polygons[7]], [outer, hole]]
        for number, rings in enumerate(cases):
            edges = coverage.polygon_edges(rings, grid)
            whole = coverage.band_coverage(edges, grid, slice(0, grid.nrows))
            for size in (1, 7, 64):
                with self.subTest(case=number, rows=size):
                    parts = []
                    for start in range(0, grid.nrows, size):
                        part = coverage.band_coverage(edges, grid, slice(start, start + size))
                        if part.rows.size:
                            self.assertGreaterEqual(int(part.rows.min()), start)
                            self.assertLess(int(part.rows.max()), start + size)
                        parts.append(part)
                    for name in ("rows", "cols", "fraction"):
                        joined = np.concatenate([getattr(part, name) for part in parts])
                        np.testing.assert_array_equal(joined, getattr(whole, name))

    def test_an_empty_band_and_wrong_arguments(self) -> None:
        """A5: una banda vacía o sin aristas da cero celdas; una banda con paso, unas aristas
        que no son ``(n, 2, 2)`` o no finitas y un anillo de menos de tres vértices son
        errores del programa."""
        grid = _window_grid(2.0, size=40.0)
        edges = coverage.polygon_edges([np.array([[3.0, 3.0], [9.0, 3.0], [6.0, 8.0]])
                                        + [WEST, SOUTH]], grid)
        self.assertEqual(coverage.band_coverage(edges, grid, slice(5, 5)).fraction.size, 0)
        self.assertEqual(coverage.band_coverage(edges, grid, slice(0, 4)).fraction.size, 0)
        empty = coverage.band_coverage(np.zeros((0, 2, 2)), grid, slice(None))
        self.assertEqual((empty.rows.size, empty.cols.size, empty.fraction.size), (0, 0, 0))
        with self.assertRaises(ValueError):
            coverage.band_coverage(edges, grid, slice(0, 10, 2))
        with self.assertRaises(ValueError):
            coverage.band_coverage(edges[:, 0], grid, slice(None))
        with self.assertRaises(ValueError):
            coverage.band_coverage(np.full((3, 2, 2), np.nan), grid, slice(None))
        with self.assertRaises(ValueError):
            coverage.polygon_edges([np.array([[0.0, 0.0], [1.0, 1.0], [0.0, 0.0]])], grid)
        with self.assertRaises(ValueError):
            coverage.polygon_edges([], grid)


if __name__ == "__main__":
    unittest.main()
