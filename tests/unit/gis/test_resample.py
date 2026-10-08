# SPDX-License-Identifier: GPL-3.0-or-later
"""Remuestreo a la rejilla del proyecto (spec 006, T10; plan 006 §5.3.2, §5.4 A6 y §6 D6;
ADR-0014).

- **RF-006-11**: ``choose_method`` elige la media ponderada por área si el paso de la fuente
  es menor o igual que el de la rejilla y la bilineal si es mayor (5 m → 1 m: bilineal).
  ``resample_to_grid`` calcula cada celda con el método declarado: la media por área es la
  suma de cota × área de solape sobre las celdas válidas entre esa área, y la celda cuya
  área cubierta por celdas válidas no alcanza la fracción mínima (1 por defecto,
  ``gis.resample.min_valid_fraction``) queda sin dato; la bilineal deja sin dato la celda a
  la que le falta un vecino (fuera de la fuente o sin dato: NaN o ±∞). Nunca se rellena: la
  fracción mínima solo decide si la media de lo cubierto vale. Una rejilla ya alineada (la
  misma, o una parte de la misma con el mismo paso) da las mismas cotas, bit a bit, por los
  dos métodos. El informe lleva el método, la fracción, las celdas y el área de celda.
- **RF-006-30**: ``resample_classes_to_grid`` asigna a cada celda el código que cubre más
  área (con empate, el menor), nunca uno intermedio, con la misma cobertura mínima; un
  valor que no es un código entero es ``gis.classes_not_integer``.

Los resultados se comparan con un cálculo independiente, celda a celda, del área de solape
de cada par de celdas (``_overlaps``). Avance y cancelación por bloques de filas
(RF-006-28). Los casos analíticos (plano exacto ≤ 10⁻⁹ m y volumen conservado ≤ 10⁻⁹) están
en ``tests/referencia/gis/test_ref_resample.py``.
"""

import math
import unittest
from unittest import mock

import numpy as np

from tests.support.package import import_geoblender

gis = import_geoblender("gis")
resample = import_geoblender("gis.resample")
params = import_geoblender("gis.params")
georef = import_geoblender("core.georef")
worker_api = import_geoblender("jobs.worker_api")

NAN = math.nan
CATALOG = georef.load_catalog()
CRS = CATALOG.horizontal(25830)
VERTICAL = CATALOG.vertical(5782)
AREA_MEAN = "area_mean"
BILINEAR = "bilinear"
WEST, NORTH = 700_000.0, 4_400_010.0
B24_DX = 1.0002942907592702
B24_DY = 1.0003022974607014


def _grid(dx: float, dy: float, ncols: int, nrows: int, *, west: float = WEST,
          north: float = NORTH):
    return gis.Grid(west=west, north=north, dx=dx, dy=dy, ncols=ncols, nrows=nrows)


def _raster(grid, values) -> object:
    array = np.array(values, dtype=np.float64)
    array.flags.writeable = False  # una entrada nunca se modifica
    return gis.Raster(grid, array, CRS, VERTICAL)


def _same(test: unittest.TestCase, got: np.ndarray, expected: np.ndarray) -> None:
    """Las mismas cotas, bit a bit, y NaN en las mismas celdas."""
    test.assertEqual(got.shape, expected.shape)
    test.assertEqual(got.dtype, np.float64)
    nan = np.isnan(expected)
    np.testing.assert_array_equal(np.isnan(got), nan)
    test.assertTrue(
        np.array_equal(got[~nan].view(np.uint64), expected[~nan].view(np.uint64)),
        f"{got} frente a {expected}",
    )


def _overlaps(src_grid, target):
    """Áreas de solape (m²) de cada celda destino con cada celda de origen, por fuerza
    bruta: un array (filas, columnas destino, filas, columnas origen). Coordenadas locales
    (respecto a la esquina noroeste del destino) para no perder decimales."""
    sx0 = src_grid.west - target.west
    sy0 = target.north - src_grid.north  # hacia el sur
    src_x = sx0 + np.arange(src_grid.ncols + 1) * src_grid.dx
    src_y = sy0 + np.arange(src_grid.nrows + 1) * src_grid.dy
    tgt_x = np.arange(target.ncols + 1) * target.dx
    tgt_y = np.arange(target.nrows + 1) * target.dy

    def lengths(tgt, src):
        low = np.maximum.outer(tgt[:-1], src[:-1])
        high = np.minimum.outer(tgt[1:], src[1:])
        return np.maximum(high - low, 0.0)  # (destino, origen)

    ox = lengths(tgt_x, src_x)
    oy = lengths(tgt_y, src_y)
    return oy[:, None, :, None] * ox[None, :, None, :]


def _brute_mean(src_grid, values, target, fraction):
    areas = _overlaps(src_grid, target)
    valid = np.isfinite(values)
    weights = np.where(valid, areas, 0.0)
    covered = weights.sum(axis=(2, 3))
    total = (weights * np.where(valid, values, 0.0)).sum(axis=(2, 3))
    out = np.full(target.shape, NAN)
    ok = covered >= fraction * target.cell_area - 1e-9
    ok &= covered > 0.0
    out[ok] = total[ok] / covered[ok]
    return out


def _brute_mode(src_grid, codes, target, fraction):
    areas = _overlaps(src_grid, target)
    valid = np.isfinite(codes)
    out = np.full(target.shape, NAN)
    for row in range(target.nrows):
        for col in range(target.ncols):
            by_code: dict[float, float] = {}
            for code in np.unique(codes[valid]):
                by_code[float(code)] = float(areas[row, col][valid & (codes == code)].sum())
            covered = sum(by_code.values())
            if covered <= 0.0 or covered < fraction * target.cell_area - 1e-9:
                continue
            best = max(by_code.values())
            out[row, col] = min(c for c, a in by_code.items() if a >= best - 1e-9)
    return out


class ChooseMethodTest(unittest.TestCase):
    """RF-006-11: método por defecto según el paso de la fuente y el de la rejilla."""

    def test_finer_or_equal_source_is_area_mean(self) -> None:
        target = _grid(1.0, 1.0, 4, 4)
        for dx, dy in ((0.5, 0.5), (1.0, 1.0), (0.5, 1.0), (0.25, 0.75)):
            with self.subTest(dx=dx, dy=dy):
                method = resample.choose_method(_grid(dx, dy, 4, 4), target)
                self.assertIs(method, resample.ResampleMethod.AREA_MEAN)
                self.assertEqual(method, AREA_MEAN)

    def test_coarser_source_is_bilinear(self) -> None:
        """5 m → 1 m elige la bilineal; también si solo un paso es mayor (la celda «de
        1 m» de 1,000294 × 1,000302 m, o 0,5 × 2 m)."""
        target = _grid(1.0, 1.0, 4, 4)
        for dx, dy in ((5.0, 5.0), (B24_DX, B24_DY), (0.5, 2.0), (2.0, 0.5)):
            with self.subTest(dx=dx, dy=dy):
                method = resample.choose_method(_grid(dx, dy, 4, 4), target)
                self.assertIs(method, resample.ResampleMethod.BILINEAR)
                self.assertEqual(method, BILINEAR)

    def test_method_names(self) -> None:
        """Los nombres del informe (``ResampleReport.method``)."""
        self.assertEqual([m.value for m in resample.ResampleMethod],
                         ["area_mean", "bilinear", "mode"])


class AlignedTest(unittest.TestCase):
    """RF-006-11 y RF-006-30: un ráster ya alineado sale bit a bit, por los tres métodos."""

    VALUES = np.array([
        [812.123456789, -0.0, 5e-324, NAN, 1e300],
        [-12.5, 0.1, 0.2, 0.3, 4_000.000000001],
        [NAN, NAN, 7.0, 1.0 / 3.0, -1e-300],
        [851.75, 852.0, 853.25, 854.5, 855.125],
    ])

    def test_same_grid(self) -> None:
        for dx, dy in ((1.0, 1.0), (B24_DX, B24_DY), (0.3, 0.7)):
            src_grid = _grid(dx, dy, 5, 4)
            src = _raster(src_grid, self.VALUES)
            for method in (AREA_MEAN, BILINEAR):
                with self.subTest(dx=dx, method=method):
                    result, report = resample.resample_to_grid(src, src_grid, method=method)
                    _same(self, result.values, self.VALUES)
                    self.assertEqual(report.valid_cells, 17)

    def test_part_with_rounded_corner(self) -> None:
        """Una ventana de la rejilla de 1,000294 × 1,000302 m desplazada una celda, con la
        esquina calculada en float64 (a 4·10⁻¹¹ y 4·10⁻¹⁰ celdas por debajo del borde): la
        bilineal da las cotas de la ventana bit a bit; la media, a ≤ 10⁻⁸ m (el trozo de
        4·10⁻¹⁰ de la fila vecina, 3,75 m más alta), también junto al NaN (el trozo de su
        celda no le quita cobertura)."""
        src_grid = _grid(B24_DX, B24_DY, 5, 4)
        values = 800.0 + np.arange(20.0).reshape(4, 5) * 0.75
        values[0, 1] = NAN
        src = _raster(src_grid, values)
        target = _grid(B24_DX, B24_DY, 3, 2, west=WEST + B24_DX, north=NORTH - B24_DY)
        result, _ = resample.resample_to_grid(src, target, method=BILINEAR)
        _same(self, result.values, values[1:3, 1:4])
        result, report = resample.resample_to_grid(src, target, method=AREA_MEAN)
        np.testing.assert_allclose(result.values, values[1:3, 1:4], rtol=0.0, atol=1e-8)
        self.assertEqual(report.valid_cells, 6)

    def test_part_of_the_same_grid(self) -> None:
        """Una ventana de la fuente con el mismo paso (también la última columna y la última
        fila, y junto a un NaN): las cotas de esa ventana."""
        src_grid = _grid(1.0, 1.0, 5, 4)
        src = _raster(src_grid, self.VALUES)
        target = _grid(1.0, 1.0, 3, 2, west=WEST + 2.0, north=NORTH - 2.0)
        for method in (AREA_MEAN, BILINEAR):
            with self.subTest(method=method):
                result, _ = resample.resample_to_grid(src, target, method=method)
                _same(self, result.values, self.VALUES[2:4, 2:5])

    def test_classes_same_grid(self) -> None:
        codes = np.array([[3.0, 1.0, NAN], [7.0, 7.0, 2.0]])
        src_grid = _grid(B24_DX, B24_DY, 3, 2)
        result, report = resample.resample_classes_to_grid(_raster(src_grid, codes), src_grid)
        _same(self, result.values, codes)
        self.assertEqual(report.method, "mode")


class AreaMeanTest(unittest.TestCase):
    """RF-006-11: media ponderada por área, cobertura mínima y sin dato."""

    def test_mean_of_four(self) -> None:
        """0,5 m → 1 m: cada celda, la media de sus 4 subceldas (pesos de 1/4, exactos)."""
        src = _raster(_grid(0.5, 0.5, 4, 2), [[1.0, 2.0, 10.0, 20.0],
                                               [3.0, 6.0, 30.0, 60.0]])
        result, report = resample.resample_to_grid(src, _grid(1.0, 1.0, 2, 1),
                                                   method=AREA_MEAN)
        _same(self, result.values, np.array([[3.0, 30.0]]))
        self.assertEqual(report.method, AREA_MEAN)

    def test_misaligned_coverage(self) -> None:
        """Fuente de 1 m desplazada medio paso en X y en Y: el interior, la media de 4
        cuartos; el borde (cubierto 1/4 o 1/2) queda sin dato con la fracción 1 y, con 0,25,
        es la media de lo cubierto, nunca un relleno."""
        values = np.array([[1.0, 2.0, 4.0], [8.0, 16.0, 32.0], [64.0, 128.0, 256.0]])
        src_grid = _grid(1.0, 1.0, 3, 3, west=WEST + 0.5, north=NORTH - 0.5)
        target = _grid(1.0, 1.0, 4, 4)
        src = _raster(src_grid, values)
        result, report = resample.resample_to_grid(src, target, method=AREA_MEAN)
        expected = np.full((4, 4), NAN)
        expected[1:3, 1:3] = [[27 / 4, 54 / 4], [216 / 4, 432 / 4]]
        _same(self, result.values, expected)
        self.assertEqual((report.cells, report.valid_cells, report.nodata_cells), (16, 4, 12))
        result, report = resample.resample_to_grid(src, target, method=AREA_MEAN,
                                                   min_valid_fraction=0.25)
        expected = np.array([
            [1.0, 1.5, 3.0, 4.0],
            [4.5, 27 / 4, 54 / 4, 18.0],
            [36.0, 216 / 4, 432 / 4, 144.0],
            [64.0, 96.0, 192.0, 256.0],
        ])
        _same(self, result.values, expected)
        self.assertEqual(report.min_valid_fraction, 0.25)

    def test_nodata_never_filled(self) -> None:
        """Una subcelda sin dato: la celda queda sin dato con la fracción 1 (y con 0,8); con
        0,75, la media de las otras tres; cuatro sin dato, sin dato con cualquier
        fracción."""
        values = np.array([[1.0, NAN, NAN, NAN], [3.0, 5.0, NAN, NAN]])
        src = _raster(_grid(0.5, 0.5, 4, 2), values)
        target = _grid(1.0, 1.0, 2, 1)
        for fraction, expected in ((None, [NAN, NAN]), (0.8, [NAN, NAN]),
                                   (0.75, [3.0, NAN]), (1e-6, [3.0, NAN])):
            with self.subTest(fraction=fraction):
                options = {} if fraction is None else {"min_valid_fraction": fraction}
                result, report = resample.resample_to_grid(src, target, method=AREA_MEAN,
                                                           **options)
                _same(self, result.values, np.array([expected]))
                self.assertEqual(report.valid_cells, int(np.isfinite(expected).sum()))

    def test_against_brute_force(self) -> None:
        """Fuente de 1,000294 × 1,000302 m con dos NaN → rejilla de 1 m que la cubre: igual
        que la suma por fuerza bruta de cota × área de solape (≤ 10⁻¹² relativo), con las
        fracciones 1, 0,5 y 0,01."""
        rng = np.random.default_rng(20_261_008)
        values = 800.0 + rng.uniform(-20.0, 20.0, (7, 9))
        values[2, 3] = values[5, 0] = NAN
        src_grid = _grid(B24_DX, B24_DY, 9, 7, west=WEST + 0.3, north=NORTH - 0.6)
        target = gis.aligned_grid(src_grid.extent, 1.0)
        src = _raster(src_grid, values)
        for fraction in (1.0, 0.5, 0.01):
            with self.subTest(fraction=fraction):
                result, report = resample.resample_to_grid(
                    src, target, method=AREA_MEAN, min_valid_fraction=fraction)
                expected = _brute_mean(src_grid, values, target, fraction)
                np.testing.assert_array_equal(np.isnan(result.values), np.isnan(expected))
                np.testing.assert_allclose(result.values, expected, rtol=1e-12)
                self.assertEqual(report.valid_cells, int(np.isfinite(expected).sum()))
                if fraction == 1.0:  # el borde, cubierto en parte
                    self.assertGreater(report.nodata_cells, 0)

    def test_no_overlap(self) -> None:
        """Una rejilla fuera de la fuente: todo sin dato, sin error."""
        src = _raster(_grid(1.0, 1.0, 2, 2), [[1.0, 2.0], [3.0, 4.0]])
        target = _grid(1.0, 1.0, 3, 3, west=WEST + 10.0)
        for method in (AREA_MEAN, BILINEAR):
            with self.subTest(method=method):
                result, report = resample.resample_to_grid(src, target, method=method)
                self.assertTrue(np.isnan(result.values).all())
                self.assertEqual(report.valid_cells, 0)
        result, report = resample.resample_classes_to_grid(src, target)
        self.assertTrue(np.isnan(result.values).all())


class BilinearTest(unittest.TestCase):
    """RF-006-11: interpolación bilineal; sin dato si falta un vecino."""

    def test_reproduces_bilinear_surface(self) -> None:
        """z = a + b·x + c·y + d·x·y (local) en los centros de 2 m → centros de 0,5 m: la
        bilineal la reproduce (≤ 10⁻¹² m); fuera del cuadro de centros de la fuente, sin
        dato."""
        src_grid = _grid(2.0, 2.0, 4, 3)
        target = _grid(0.5, 0.5, 16, 12)

        def surface(grid):
            x, y = grid.centers()
            lx, ly = x - WEST, y - (NORTH - 6.0)
            return 805.25 + 0.375 * lx - 0.125 * ly + 0.0625 * lx * ly

        result, report = resample.resample_to_grid(_raster(src_grid, surface(src_grid)),
                                                   target, method=BILINEAR)
        inside = np.zeros(target.shape, dtype=bool)
        inside[2:10, 2:14] = True  # centros de destino dentro del cuadro de centros
        np.testing.assert_array_equal(np.isfinite(result.values), inside)
        error = np.abs(result.values[inside] - surface(target)[inside])
        self.assertLessEqual(float(error.max()), 1e-12)
        self.assertEqual((report.method, report.valid_cells), (BILINEAR, 96))

    def test_missing_neighbour(self) -> None:
        """2 m → 1 m con un NaN en la esquina noroeste de la fuente: las 4 celdas que lo
        usan con peso no nulo quedan sin dato; las otras 12 del cuadro de centros
        interpolan (un plano, exacto) y las de fuera del cuadro, sin dato."""
        src_grid = _grid(2.0, 2.0, 3, 3)
        target = _grid(1.0, 1.0, 6, 6)

        def plane(grid):
            x, y = grid.centers()
            return 800.0 + 0.5 * (x - WEST) - 0.25 * (NORTH - y)

        values = plane(src_grid)
        values[0, 0] = NAN
        result, report = resample.resample_to_grid(_raster(src_grid, values), target,
                                                   method=BILINEAR)
        # Centros de destino en 0,5, 1,5 … 5,5 m; los de la fuente, en 1, 3 y 5 m.
        expected = np.full(target.shape, NAN)
        expected[1:5, 1:5] = plane(target)[1:5, 1:5]
        expected[1:3, 1:3] = NAN
        np.testing.assert_array_equal(np.isnan(result.values), np.isnan(expected))
        np.testing.assert_allclose(result.values, expected, rtol=0.0, atol=1e-12)
        self.assertEqual(report.valid_cells, 12)

    def test_neighbour_with_zero_weight_not_needed(self) -> None:
        """1 m → 1 m desplazado 1 m: cada centro cae en un centro de la fuente; el NaN de al
        lado no cuenta (peso cero)."""
        values = np.array([[1.0, NAN, 3.0], [4.0, 5.0, NAN]])
        src = _raster(_grid(1.0, 1.0, 3, 2), values)
        target = _grid(1.0, 1.0, 1, 2, west=WEST + 2.0)
        result, _ = resample.resample_to_grid(src, target, method=BILINEAR)
        _same(self, result.values, np.array([[3.0], [NAN]]))


class ClassesTest(unittest.TestCase):
    """RF-006-30: moda por área de una rejilla de clases."""

    def test_mode_of_four(self) -> None:
        """0,5 m → 1 m: la clase de mayor área; con empate, el código menor; nunca un código
        intermedio (1 y 3 nunca dan 2)."""
        codes = np.array([
            [1.0, 2.0, 1.0, 2.0, 3.0, 1.0, 1.0, 3.0],
            [2.0, 2.0, 2.0, 1.0, 3.0, 1.0, 1.0, 3.0],
        ])
        src = _raster(_grid(0.5, 0.5, 8, 2), codes)
        result, report = resample.resample_classes_to_grid(src, _grid(1.0, 1.0, 4, 1))
        _same(self, result.values, np.array([[2.0, 1.0, 1.0, 1.0]]))
        self.assertEqual((report.method, report.valid_cells, report.cell_area_m2),
                         ("mode", 4, 1.0))

    def test_against_brute_force(self) -> None:
        """Fuente de 1,000294 × 1,000302 m desplazada, códigos 2, 5 y 9 al azar y un NaN →
        rejilla de 1 m: el mismo código que el cálculo por fuerza bruta de las áreas, con
        las fracciones 1 y 0,4; nunca otro código."""
        rng = np.random.default_rng(8)
        codes = rng.choice([2.0, 5.0, 9.0], size=(8, 10))
        codes[3, 4] = NAN
        src_grid = _grid(B24_DX, B24_DY, 10, 8, west=WEST + 0.4, north=NORTH - 0.2)
        target = gis.aligned_grid(src_grid.extent, 1.0)
        src = _raster(src_grid, codes)
        for fraction in (1.0, 0.4):
            with self.subTest(fraction=fraction):
                result, report = resample.resample_classes_to_grid(
                    src, target, min_valid_fraction=fraction)
                _same(self, result.values, _brute_mode(src_grid, codes, target, fraction))
                found = set(np.unique(result.values[np.isfinite(result.values)]))
                self.assertLessEqual(found, {2.0, 5.0, 9.0})
                self.assertEqual(report.min_valid_fraction, fraction)

    def test_coverage(self) -> None:
        """Una subcelda sin dato: sin dato con la fracción 1; con 0,75, la moda de las otras
        tres (con empate 4 y 6 → 4)."""
        codes = np.array([[6.0, NAN], [4.0, 6.0]])
        src = _raster(_grid(0.5, 0.5, 2, 2), codes)
        target = _grid(1.0, 1.0, 1, 1)
        result, _ = resample.resample_classes_to_grid(src, target)
        self.assertTrue(np.isnan(result.values).all())
        result, _ = resample.resample_classes_to_grid(src, target, min_valid_fraction=0.75)
        _same(self, result.values, np.array([[6.0]]))
        codes = np.array([[6.0, NAN], [4.0, NAN]])
        result, _ = resample.resample_classes_to_grid(_raster(_grid(0.5, 0.5, 2, 2), codes),
                                                      target, min_valid_fraction=0.5)
        _same(self, result.values, np.array([[4.0]]))

    def test_not_integer_codes(self) -> None:
        """Una cota no es un código: ``gis.classes_not_integer`` con el valor. Solo cuenta
        la parte de la fuente que solapa la rejilla."""
        src = _raster(_grid(1.0, 1.0, 2, 1), [[3.0, 812.5]])
        with self.assertRaises(gis.GisError) as caught:
            resample.resample_classes_to_grid(src, _grid(1.0, 1.0, 2, 1), name="geología")
        error = caught.exception
        self.assertEqual((error.code, error.value, error.obj),
                         ("gis.classes_not_integer", 812.5, "geología"))
        self.assertIn("812,5", str(error))
        result, _ = resample.resample_classes_to_grid(src, _grid(1.0, 1.0, 1, 1))
        _same(self, result.values, np.array([[3.0]]))


class ContractTest(unittest.TestCase):
    """RF-006-11: resultado, informe, parámetros y entradas intactas."""

    SRC = _raster(_grid(0.5, 0.5, 4, 4), np.arange(16.0).reshape(4, 4))
    TARGET = _grid(1.0, 1.0, 2, 2)

    def test_result_and_report(self) -> None:
        """El ráster va en la rejilla destino, con el CRS y la referencia vertical de la
        fuente; el informe, con la fracción por defecto de ``gis.resample.min_valid_fraction``
        y el área de celda exacta."""
        for function, method, options in (
            (resample.resample_to_grid, AREA_MEAN, {"method": AREA_MEAN}),
            (resample.resample_to_grid, BILINEAR, {"method": resample.ResampleMethod.BILINEAR}),
            (resample.resample_classes_to_grid, "mode", {}),
        ):
            with self.subTest(method=method):
                result, report = function(self.SRC, self.TARGET, **options)
                self.assertIsInstance(result, gis.Raster)
                self.assertIs(result.grid, self.TARGET)
                self.assertIs(result.crs, self.SRC.crs)
                self.assertIs(result.vertical, self.SRC.vertical)
                self.assertIsInstance(report, gis.ResampleReport)
                self.assertEqual(report.method, method)
                self.assertEqual(report.min_valid_fraction,
                                 params.default("gis.resample.min_valid_fraction"))
                self.assertEqual((report.cells, report.cell_area_m2), (4, 1.0))
                self.assertIsNone(report.transform)
                self.assertIsNone(report.supersample)

    def test_infinite_is_nodata(self) -> None:
        """Una cota infinita es sin dato, como NaN: nunca sale ±∞ ni entra en una media."""
        values = [[math.inf, 1.0], [2.0, 3.0]]
        target = _grid(1.0, 1.0, 1, 1)
        src = _raster(_grid(0.5, 0.5, 2, 2), values)
        result, _ = resample.resample_to_grid(src, target, method=AREA_MEAN)
        _same(self, result.values, np.array([[NAN]]))
        result, _ = resample.resample_to_grid(src, target, method=AREA_MEAN,
                                              min_valid_fraction=0.75)
        _same(self, result.values, np.array([[2.0]]))
        classes = _raster(src.grid, [[-math.inf, -math.inf], [1.0, 1.0]])
        result, _ = resample.resample_classes_to_grid(classes, target)
        _same(self, result.values, np.array([[NAN]]))
        result, _ = resample.resample_classes_to_grid(classes, target, min_valid_fraction=0.5)
        _same(self, result.values, np.array([[1.0]]))
        shifted = _grid(1.0, 1.0, 1, 1, west=WEST + 0.5, north=NORTH - 0.5)
        for row, col in ((0, 0), (0, 1), (1, 0), (1, 1)):  # cada uno de los 4 vecinos
            with self.subTest(vecino=(row, col)):
                corners = np.array([[1.0, 2.0], [3.0, 4.0]])
                corners[row, col] = -math.inf
                result, report = resample.resample_to_grid(
                    _raster(_grid(1.0, 1.0, 2, 2), corners), shifted, method=BILINEAR)
                _same(self, result.values, np.array([[NAN]]))
                self.assertEqual(report.valid_cells, 0)

    def test_sliver_at_the_edge(self) -> None:
        """Un borde de origen a 1 ulp del borde de la celda destino (paso de
        0,9999999999999999 m): el trozo de 10⁻¹⁶ m va a su celda y la celda vale la cota de
        la primera (≤ 10⁻¹² m) con la media; con la moda, su código."""
        step = 1.0 - 2.0 ** -53
        src_grid = _grid(step, 1.0, 2, 1)
        target = _grid(1.0, 1.0, 1, 1)
        result, report = resample.resample_to_grid(_raster(src_grid, [[805.5, 900.0]]),
                                                   target, method=AREA_MEAN)
        self.assertAlmostEqual(float(result.values[0, 0]), 805.5, delta=1e-12)
        self.assertEqual(report.valid_cells, 1)
        result, _ = resample.resample_classes_to_grid(_raster(src_grid, [[4.0, 9.0]]), target)
        _same(self, result.values, np.array([[4.0]]))

    def test_min_valid_fraction_checked(self) -> None:
        """Fuera de (0; 1] o no numérica: el error del parámetro, con su clave."""
        for value, code in ((0.0, "gis.param_out_of_range"), (1.5, "gis.param_out_of_range"),
                            ("1", "gis.param_not_number")):
            for function, options in ((resample.resample_to_grid, {"method": AREA_MEAN}),
                                      (resample.resample_classes_to_grid, {})):
                with self.subTest(value=value, function=function.__name__):
                    with self.assertRaises(gis.GisError) as caught:
                        function(self.SRC, self.TARGET, min_valid_fraction=value, **options)
                    self.assertEqual(caught.exception.code, code)
                    self.assertEqual(caught.exception.field,
                                     "gis.resample.min_valid_fraction")

    def test_wrong_arguments(self) -> None:
        """Un método que no es de cotas, o argumentos que no son un ``Raster`` y una
        ``Grid``, son errores del programa."""
        for method in ("nearest", "mode", resample.ResampleMethod.MODE, None):
            with self.subTest(method=method), self.assertRaises(ValueError):
                resample.resample_to_grid(self.SRC, self.TARGET, method=method)
        with self.assertRaises(TypeError):
            resample.resample_to_grid(self.SRC.values, self.TARGET, method=AREA_MEAN)
        with self.assertRaises(TypeError):
            resample.resample_classes_to_grid(self.SRC, self.TARGET.extent)

    def test_package_exports(self) -> None:
        for name in ("ResampleMethod", "choose_method", "resample_to_grid",
                     "resample_classes_to_grid"):
            with self.subTest(name=name):
                self.assertIn(name, gis.__all__)
                self.assertIs(getattr(gis, name), getattr(resample, name))


class BlocksTest(unittest.TestCase):
    """RF-006-28: por bloques de filas, con avance y cancelación; el tamaño del bloque no
    cambia el resultado."""

    def setUp(self) -> None:
        rng = np.random.default_rng(3)
        values = 800.0 + rng.uniform(-5.0, 5.0, (13, 11))
        values[4, 6] = NAN
        self.src = _raster(_grid(B24_DX, B24_DY, 11, 13, west=WEST + 0.1), values)
        self.codes = _raster(self.src.grid, np.floor(values / 2.0))
        self.target = gis.aligned_grid(self.src.grid.extent, 1.0)
        self.calls = (
            ("media", lambda **kw: resample.resample_to_grid(
                self.src, self.target, method=AREA_MEAN, min_valid_fraction=0.5, **kw)),
            ("bilineal", lambda **kw: resample.resample_to_grid(
                self.src, self.target, method=BILINEAR, **kw)),
            ("moda", lambda **kw: resample.resample_classes_to_grid(
                self.codes, self.target, min_valid_fraction=0.5, **kw)),
        )

    def test_block_size_does_not_change_the_result(self) -> None:
        for label, call in self.calls:
            with self.subTest(method=label):
                expected, _ = call()
                with mock.patch.object(resample, "BLOCK_ITEMS", 1):
                    got, _ = call()
                _same(self, got.values, expected.values)

    def test_progress_and_cancel(self) -> None:
        """Avance tras cada bloque, creciente hasta 1; si se cancela en el 3.º, para con
        ``JobCancelled`` y no devuelve nada."""
        for label, call in self.calls:
            with self.subTest(method=label), mock.patch.object(resample, "BLOCK_ITEMS", 1):
                seen: list[float] = []
                call(progress=lambda frac, text: seen.append(frac))
                self.assertGreaterEqual(len(seen), 5)
                self.assertEqual(seen, sorted(seen))
                self.assertEqual(seen[-1], 1.0)
                asked: list[int] = []

                def cancelled() -> bool:
                    asked.append(1)
                    return len(asked) > 2

                with self.assertRaises(worker_api.JobCancelled) as caught:
                    call(cancelled=cancelled)
                self.assertIn(f"3 de {len(seen)}", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
