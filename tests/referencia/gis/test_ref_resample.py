# SPDX-License-Identifier: GPL-3.0-or-later
"""Casos de referencia del remuestreo a la rejilla del proyecto (spec 006, T10; RF-006-11,
RF-006-30; plan 006 §5.4 A6 y §7.2; ADR-0014; constitución, principio 2).

- **Plano** z = 805,3 + 0,37·x − 0,21·y (x, y locales, m) en los centros de la fuente:
  reproducido con error ≤ 10⁻⁹ m en cada celda con dato. Media por área (exacta para un
  plano cuando los trozos de cada celda son simétricos respecto a su centro): 0,5 → 1 m,
  0,5 m desplazada 0,25 m → 1 m, 0,5 → 2 m y 1 → 5 m. Bilineal (exacta para un plano): 5 →
  1 m (el método que elige ``choose_method``), 0,5 → 1 m y 1,000294 × 1,000302 → 1 m
  desplazada. Las celdas sin dato son exactamente las que se esperan: en la media, las que no
  están enteras dentro de la fuente (fracción mínima 1); en la bilineal, aquellas cuyo
  centro cae fuera del cuadro de centros de la fuente.
- **Volumen conservado** con la media por área (RF-006-11): sobre la zona totalmente
  cubierta, Σ cota × área de las celdas de 1 m es el volumen de la fuente escalonada sobre
  esa zona, calculado aparte con el solape de cada columna y cada fila de la fuente con la
  zona; error relativo ≤ 10⁻⁹, de 0,5 m (desplazada 0,25 m) → 1 m y de la rejilla «de 1 m» de
  Silvestre (1,0002942907592702 × 1,0003022974607014 m) → 1 m. Superficie: la de
  ``tests/data/gis`` (z = 800 + 0,5x − 0,25y + 3 sin(x/7)).
- **Moda de clases** (RF-006-30): de la rejilla «de 1 m» de Silvestre (paso entre 1 y 2 m)
  a 1 m, cada celda destino solapa como mucho 2 columnas (L + R = 1) y 2 filas (B + T = 1)
  de origen. Con un código distinto por bloque de 3 × 3 celdas de origen, el área de cada
  código en una celda destino es el producto de su parte en X por su parte en Y, y la mayor
  es la del código de la celda de origen que contiene el centro de la celda destino (con L,
  R, B y T ≠ ½). La moda es ese código en todas las celdas totalmente cubiertas.
"""

import math
import unittest

import numpy as np

from tests.support.package import import_geoblender

gis = import_geoblender("gis")
resample = import_geoblender("gis.resample")
georef = import_geoblender("core.georef")

CATALOG = georef.load_catalog()
CRS = CATALOG.horizontal(25830)
VERTICAL = CATALOG.vertical(5782)
X0, Y0 = 700_000.0, 4_400_000.0  # origen de las coordenadas locales de las fórmulas
B24_DX = 1.0002942907592702
B24_DY = 1.0003022974607014

PLANE = (805.3, 0.37, -0.21)  # c, a, b
PLANE_TOLERANCE_M = 1e-9
VOLUME_TOLERANCE = 1e-9  # relativo


def _grid(west: float, north: float, dx: float, dy: float, ncols: int, nrows: int):
    return gis.Grid(west=X0 + west, north=Y0 + north, dx=dx, dy=dy, ncols=ncols,
                    nrows=nrows)


def _plane(grid) -> np.ndarray:
    x, y = grid.centers()
    c, a, b = PLANE
    return c + a * (x - X0) + b * (y - Y0)


def _surface(grid) -> np.ndarray:
    """La superficie de ``tests/data/gis`` en los centros de ``grid``."""
    x, y = grid.centers()
    lx = x - X0
    return 800.0 + 0.5 * lx - 0.25 * (y - Y0) + 3.0 * np.sin(lx / 7.0)


def _raster(grid, values):
    return gis.Raster(grid, values, CRS, VERTICAL)


def _edges(grid) -> tuple[np.ndarray, np.ndarray]:
    """Bordes de las columnas (de oeste a este) y de las filas (de norte a sur), locales."""
    xs = (grid.west - X0) + np.arange(grid.ncols + 1) * grid.dx
    ys = (grid.north - Y0) - np.arange(grid.nrows + 1) * grid.dy
    return xs, ys


def _expected_valid(src_grid, target, method: str) -> np.ndarray:
    """Celdas con dato esperadas: en la media, las que están enteras dentro de la fuente; en
    la bilineal, las de centro dentro del cuadro de centros de la fuente."""
    sx, sy = _edges(src_grid)
    tx, ty = _edges(target)
    if method == "area_mean":
        cols = (tx[:-1] >= sx[0]) & (tx[1:] <= sx[-1])
        rows = (ty[:-1] <= sy[0]) & (ty[1:] >= sy[-1])
    else:
        cx, cy = (tx[:-1] + tx[1:]) / 2, (ty[:-1] + ty[1:]) / 2
        cols = (cx >= sx[0] + src_grid.dx / 2) & (cx <= sx[-1] - src_grid.dx / 2)
        rows = (cy <= sy[0] - src_grid.dy / 2) & (cy >= sy[-1] + src_grid.dy / 2)
    return rows[:, None] & cols[None, :]


class PlaneTest(unittest.TestCase):
    """RF-006-11: un plano reproducido ≤ 10⁻⁹ m por los dos métodos."""

    CASES = (
        ("area_mean", _grid(0, 40, 0.5, 0.5, 120, 80), _grid(0, 40, 1, 1, 60, 40)),
        ("area_mean", _grid(0.25, 39.75, 0.5, 0.5, 120, 80), None),
        ("area_mean", _grid(0, 40, 0.5, 0.5, 120, 80), _grid(0, 40, 2, 2, 30, 20)),
        ("area_mean", _grid(0, 40, 1, 1, 60, 40), _grid(0, 40, 5, 5, 12, 8)),
        ("bilinear", _grid(0, 40, 5, 5, 12, 8), _grid(0, 40, 1, 1, 60, 40)),
        ("bilinear", _grid(0, 40, 0.5, 0.5, 120, 80), _grid(0, 40, 1, 1, 60, 40)),
        ("bilinear", _grid(0.3, 39.6, B24_DX, B24_DY, 60, 40), None),
    )

    def test_plane(self) -> None:
        for method, src_grid, target in self.CASES:
            target = target or gis.aligned_grid(src_grid.extent, 1.0)
            with self.subTest(method=method, source=(src_grid.dx, src_grid.west - X0),
                              step=target.dx):
                result, report = resample.resample_to_grid(
                    _raster(src_grid, _plane(src_grid)), target, method=method)
                valid = np.isfinite(result.values)
                np.testing.assert_array_equal(valid, _expected_valid(src_grid, target, method))
                error = float(np.max(np.abs(result.values[valid] - _plane(target)[valid])))
                self.assertLessEqual(error, PLANE_TOLERANCE_M, f"error máximo {error:.3e} m")
                self.assertEqual(report.valid_cells, int(valid.sum()))
                self.assertGreater(report.valid_cells, 0)

    def test_five_to_one_chooses_bilinear(self) -> None:
        """5 m → 1 m: ``choose_method`` da la bilineal; 0,5 → 1 m, la media."""
        one = _grid(0, 40, 1, 1, 60, 40)
        self.assertEqual(resample.choose_method(_grid(0, 40, 5, 5, 12, 8), one), "bilinear")
        self.assertEqual(resample.choose_method(_grid(0, 40, 0.5, 0.5, 120, 80), one),
                         "area_mean")


class VolumeConservationTest(unittest.TestCase):
    """RF-006-11: la media por área conserva el volumen de la zona totalmente cubierta."""

    CASES = (
        ("0,5 m desplazada 0,25 m", _grid(0.25, 60.25, 0.5, 0.5, 160, 120)),
        ("1,000294 × 1,000302 m", _grid(0, 100, B24_DX, B24_DY, 150, 100)),
    )

    def test_volume(self) -> None:
        for label, src_grid in self.CASES:
            with self.subTest(source=label):
                values = _surface(src_grid)
                target = gis.aligned_grid(src_grid.extent, 1.0)
                result, report = resample.resample_to_grid(_raster(src_grid, values), target,
                                                           method="area_mean")
                valid = np.isfinite(result.values)
                np.testing.assert_array_equal(
                    valid, _expected_valid(src_grid, target, "area_mean"))
                rows = np.flatnonzero(valid.any(axis=1))
                cols = np.flatnonzero(valid.any(axis=0))
                self.assertEqual(int(valid.sum()), rows.size * cols.size)  # un rectángulo
                tx, ty = _edges(target)
                zone_x = (tx[cols[0]], tx[cols[-1] + 1])
                zone_y = (ty[rows[-1] + 1], ty[rows[0]])  # sur, norte
                sx, sy = _edges(src_grid)
                ox = np.clip(np.minimum(sx[1:], zone_x[1]) - np.maximum(sx[:-1], zone_x[0]),
                             0.0, None)
                oy = np.clip(np.minimum(sy[:-1], zone_y[1]) - np.maximum(sy[1:], zone_y[0]),
                             0.0, None)
                expected = math.fsum((values * oy[:, None] * ox[None, :]).ravel())
                got = math.fsum(result.values[valid].ravel()) * target.cell_area
                error = abs(got - expected) / expected
                self.assertLessEqual(error, VOLUME_TOLERANCE,
                                     f"{got:.6f} m³ frente a {expected:.6f} m³")
                self.assertEqual(report.valid_area_m2, valid.sum() * 1.0)


class ClassModeTest(unittest.TestCase):
    """RF-006-30: la moda de 1,000294 × 1,000302 m → 1 m es el código de la celda de origen
    que contiene el centro de cada celda destino."""

    def test_mode(self) -> None:
        src_grid = _grid(0.3, 39.6, B24_DX, B24_DY, 60, 40)
        rows, cols = np.indices(src_grid.shape)
        codes = (100 * (rows // 3) + cols // 3 + 1).astype(np.float64)  # 14 × 20 bloques
        target = gis.aligned_grid(src_grid.extent, 1.0)
        result, report = resample.resample_classes_to_grid(_raster(src_grid, codes), target)
        valid = _expected_valid(src_grid, target, "area_mean")
        np.testing.assert_array_equal(np.isfinite(result.values), valid)
        x, y = target.centers()
        col = np.floor((x - src_grid.west) / src_grid.dx).astype(int)
        row = np.floor((src_grid.north - y) / src_grid.dy).astype(int)
        expected = codes[row[valid], col[valid]]
        np.testing.assert_array_equal(result.values[valid], expected)
        self.assertEqual(report.method, "mode")
        self.assertEqual(report.valid_cells, int(valid.sum()))


if __name__ == "__main__":
    unittest.main()
