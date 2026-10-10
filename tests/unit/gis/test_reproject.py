# SPDX-License-Identifier: GPL-3.0-or-later
"""Reproyección a la rejilla del proyecto (spec 006, T12; plan 006 §5.3.2, §5.4 A6 y §6 D7).

Dominio puro: las transformaciones son dobles de prueba (``Rigid``: giro alrededor de un
punto, traslación y desplazamiento de la cota, con su inversa exacta), sin pyproj.

- **RF-006-05** (transformar la fuente al CRS del proyecto, un ráster directamente sobre la
  rejilla del proyecto): con un giro de 0,5° y una traslación de 100,3 / −200,7 m, un plano
  de la fuente sale en la rejilla del proyecto a ≤ 10⁻⁶ m del plano transformado, con la
  media de los s × s subcentros (s = ``gis.reproject.supersample``, 4) o con la bilineal en
  el centro; un cambio de datum de +50,000 m llega a las cotas (y no se aplica si la
  referencia vertical es la misma); sin precisión conocida (la directa o la inversa),
  ``gis.transform_unknown_accuracy`` con los dos CRS y sin transformar nada; el informe cita
  la transformación y el submuestreo. Cobertura: la celda vale si sus subcentros válidos
  (con los 4 vecinos de la bilineal en la fuente) alcanzan la fracción mínima, y vale la
  media de los válidos; un punto que la transformación no puede llevar (∞, fuera de su
  rejilla) es sin dato.
- **RF-006-28**: por bloques de filas con avance y cancelación; el tamaño del bloque no
  cambia el resultado.
"""

import math
import unittest
import warnings
from unittest import mock

import numpy as np

from tests.support.package import import_geoblender

gis = import_geoblender("gis")
resample = import_geoblender("gis.resample")
ports = import_geoblender("gis.ports")
params = import_geoblender("gis.params")
georef = import_geoblender("core.georef")
ParamError = import_geoblender("core.params").ParamError
worker_api = import_geoblender("jobs.worker_api")

CATALOG = georef.load_catalog()
H25830 = CATALOG.horizontal(25830)
H23030 = CATALOG.horizontal(23030)
V5782 = CATALOG.vertical(5782)
INFO = ports.TransformInfo("Transformación de prueba (giro y traslación)", 0.2)
UNKNOWN = ports.TransformInfo("Transformación de prueba sin precisión", None)
SHIFT = (100.3, -200.7)
ANGLE_DEG = 0.5
PIVOT = (700_020.0, 4_400_020.0)
AREA_MEAN = "area_mean"
BILINEAR = "bilinear"


def _plane(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Cota de la fuente (en su CRS): un plano con pendiente en X y en Y."""
    return 800.0 + 0.02 * (x - 700_000.0) - 0.01 * (y - 4_400_000.0)


def _source(ncols: int = 40, nrows: int = 40, *, vertical=V5782) -> object:
    """El plano en una rejilla de 1 m (oeste 700 000, norte 4 400 040), de solo lectura."""
    grid = gis.Grid(west=700_000.0, north=4_400_000.0 + nrows, dx=1.0, dy=1.0,
                    ncols=ncols, nrows=nrows)
    values = _plane(*grid.centers())
    values.flags.writeable = False  # una entrada nunca se modifica
    return gis.Raster(grid, values, H23030, vertical)


class Rigid:
    """``Transform`` falso: giro de ``angle_deg`` (antihorario) alrededor de ``pivot``,
    traslación ``shift`` y ``dz`` en la cota; ``inverse=True``, el inverso exacto.
    ``outside_x``: los puntos de entrada con X mayor quedan fuera de su rejilla (∞, como
    PROJ). Cuenta los puntos que transforma."""

    def __init__(self, info=INFO, *, angle_deg=ANGLE_DEG, shift=SHIFT, dz=0.0,
                 inverse=False, outside_x=math.inf) -> None:
        self.info = info
        self.angle = math.radians(angle_deg)
        self.shift = shift
        self.dz = dz
        self.inverse = inverse
        self.outside_x = outside_x
        self.points = 0

    def pair(self) -> "Rigid":
        """El inverso exacto, con la misma ``info``."""
        return Rigid(self.info, angle_deg=math.degrees(self.angle), shift=self.shift,
                     dz=self.dz, inverse=not self.inverse)

    def apply(self, xyz: np.ndarray) -> np.ndarray:
        xyz = np.asarray(xyz, dtype=np.float64)
        self.points += len(xyz)
        cos, sin = math.cos(self.angle), math.sin(self.angle)
        out = np.array(xyz, copy=True)
        x, y = xyz[:, 0] - PIVOT[0], xyz[:, 1] - PIVOT[1]
        if self.inverse:
            x, y = x - self.shift[0], y - self.shift[1]
            out[:, 0] = PIVOT[0] + cos * x + sin * y
            out[:, 1] = PIVOT[1] - sin * x + cos * y
            out[:, 2] = xyz[:, 2] - self.dz
        else:
            out[:, 0] = PIVOT[0] + cos * x - sin * y + self.shift[0]
            out[:, 1] = PIVOT[1] + sin * x + cos * y + self.shift[1]
            out[:, 2] = xyz[:, 2] + self.dz
        out[xyz[:, 0] > self.outside_x] = math.inf
        return out


def _call(src, target, direct, inverse=None, **options):
    options.setdefault("method", AREA_MEAN)
    return resample.reproject_to_grid(
        src, target, transform=direct, inverse=direct.pair() if inverse is None else inverse,
        target_crs=H25830, target_vertical=V5782, **options,
    )


def _expected(target, direct, *, dz=0.0) -> np.ndarray:
    """La cota de cada celda destino: el plano de la fuente en el centro llevado a la
    fuente con la inversa (la media de subcentros simétricos de un plano es su centro)."""
    x, y = target.centers()
    back = direct.pair().apply(np.column_stack((x.ravel(), y.ravel(), np.zeros(x.size))))
    return _plane(back[:, 0], back[:, 1]).reshape(target.shape) + dz


# El cuadrado de la fuente, girado y trasladado, contiene esta rejilla de 28 × 28 m.
INSIDE = gis.Grid(west=700_106.0, north=4_399_834.0, dx=1.0, dy=1.0, ncols=28, nrows=28)


class PlaneTest(unittest.TestCase):
    """RF-006-05: un plano se reproyecta a ≤ 10⁻⁶ m y el cambio de datum llega a las cotas."""

    def test_rotation_and_translation(self) -> None:
        """Giro de 0,5° y traslación de 100,3 / −200,7 m: cada celda de la rejilla del
        proyecto dentro de la fuente vale el plano transformado (≤ 10⁻⁶ m) con la media de
        4 × 4 subcentros y con la bilineal en el centro; el ráster va en la rejilla y en el
        CRS del proyecto y el informe cita la transformación y el submuestreo."""
        src = _source()
        before = src.values.copy()
        direct = Rigid()
        expected = _expected(INSIDE, direct)
        for method, supersample in ((AREA_MEAN, 4), (BILINEAR, 1)):
            with self.subTest(method=method):
                result, report = _call(src, INSIDE, direct, method=method)
                self.assertIs(result.grid, INSIDE)
                self.assertIs(result.crs, H25830)
                self.assertIs(result.vertical, V5782)
                self.assertEqual(result.values.dtype, np.float64)
                self.assertLessEqual(float(np.max(np.abs(result.values - expected))), 1e-6)
                self.assertIsInstance(report, gis.ResampleReport)
                self.assertEqual(report.method, method)
                self.assertIs(report.transform, INFO)
                self.assertEqual(report.supersample, supersample)
                self.assertEqual(report.min_valid_fraction,
                                 params.default("gis.resample.min_valid_fraction"))
                self.assertEqual((report.cells, report.valid_cells), (784, 784))
                self.assertEqual(report.cell_area_m2, 1.0)
        np.testing.assert_array_equal(src.values, before)
        self.assertEqual(params.default("gis.reproject.supersample"), 4)

    def test_datum_shift(self) -> None:
        """Un cambio de datum de +50,000 m (altura elipsoidal → EPSG:5782) se aplica a las
        cotas con la transformación directa; con la misma referencia vertical, no."""
        direct = Rigid(dz=50.0)
        for vertical, dz in ((gis.ELLIPSOIDAL_ETRS89, 50.0), (V5782, 0.0)):
            with self.subTest(vertical=vertical.name):
                result, _ = _call(_source(vertical=vertical), INSIDE, direct)
                expected = _expected(INSIDE, direct, dz=dz)
                self.assertLessEqual(float(np.max(np.abs(result.values - expected))), 1e-6)

    def test_unknown_accuracy(self) -> None:
        """Sin precisión conocida, en la directa o en la inversa:
        ``gis.transform_unknown_accuracy`` con los dos CRS y la fuente, sin transformar
        ningún punto."""
        src = _source()
        for label, direct, inverse in (
            ("directa", Rigid(UNKNOWN), Rigid(INFO, inverse=True)),
            ("inversa", Rigid(INFO), Rigid(UNKNOWN, inverse=True)),
        ):
            with self.subTest(transform=label):
                with self.assertRaises(gis.GisError) as caught:
                    _call(src, INSIDE, direct, inverse, name="mdt_ed50.tif")
                error = caught.exception
                self.assertEqual(error.code, "gis.transform_unknown_accuracy")
                self.assertEqual(error.obj, "mdt_ed50.tif")
                self.assertEqual(error.values["source_crs"], "EPSG:23030 + EPSG:5782")
                self.assertEqual(error.values["target_crs"], "EPSG:25830 + EPSG:5782")
                self.assertIn("EPSG:23030 + EPSG:5782", str(error))
                self.assertIn("EPSG:25830 + EPSG:5782", str(error))
                self.assertEqual(direct.points + inverse.points, 0)


class CoverageTest(unittest.TestCase):
    """RF-006-05: cobertura por submuestreo según la fracción mínima."""

    # Solo traslación: los centros de la fuente (6 × 6) van de 0,5 a 5,5 m del borde de la
    # rejilla destino, que tiene la misma forma; en la primera y la última fila o columna,
    # la mitad de los subcentros quedan fuera de los centros de la fuente (sin los 4
    # vecinos de la bilineal), y en las esquinas, tres cuartos.
    SRC = _source(6, 6)
    DIRECT = Rigid(angle_deg=0.0)
    TARGET = gis.Grid(west=700_000.0 + SHIFT[0], north=4_400_006.0 + SHIFT[1], dx=1.0,
                      dy=1.0, ncols=6, nrows=6)

    def _expected(self, fraction: float) -> np.ndarray:
        """El plano en la posición media de los subcentros válidos (a 0,75 de la celda en
        la primera fila o columna, a 0,25 en la última y en el centro en las demás), donde
        su parte válida (1/4, 1/2 o 1) alcanza ``fraction``."""
        offset = np.array([0.75, 0.5, 0.5, 0.5, 0.5, 0.25])
        part = np.array([0.5, 1.0, 1.0, 1.0, 1.0, 0.5])
        x = 700_000.0 + np.arange(6.0) + offset
        y = 4_400_006.0 - np.arange(6.0) - offset
        expected = _plane(x[None, :], y[:, None])
        expected[np.outer(part, part) < fraction] = np.nan
        return expected

    def test_min_valid_fraction(self) -> None:
        """Con 4 × 4 y con 2 × 2 subcentros: fracción 1 → solo el interior (16 celdas);
        0,5 → también los bordes (32); 0,25 → todas (36); cada una, la media de sus
        subcentros válidos (≤ 10⁻⁶ m)."""
        for supersample in (4, 2):
            for fraction, valid in ((1.0, 16), (0.5, 32), (0.3, 32), (0.25, 36)):
                with self.subTest(supersample=supersample, fraction=fraction):
                    result, report = _call(self.SRC, self.TARGET, self.DIRECT,
                                           min_valid_fraction=fraction,
                                           supersample=supersample)
                    expected = self._expected(fraction)
                    np.testing.assert_array_equal(np.isnan(result.values),
                                                  np.isnan(expected))
                    np.testing.assert_allclose(result.values, expected, rtol=0.0,
                                               atol=1e-6)
                    self.assertEqual(report.valid_cells, valid)
                    self.assertEqual(report.supersample, supersample)
                    self.assertEqual(report.min_valid_fraction, fraction)

    def test_outside_the_transformation(self) -> None:
        """Un punto que la transformación no puede llevar (∞) es sin dato, sin avisos de
        numpy: en la inversa, las columnas con X > 700 103,3 del destino; en la directa
        (la cota, con otro datum), las de X > 700 002 de la fuente."""
        direct = Rigid(angle_deg=0.0, dz=50.0)
        inverse = Rigid(angle_deg=0.0, dz=50.0, inverse=True, outside_x=700_103.3)
        src = _source(6, 6, vertical=gis.ELLIPSOIDAL_ETRS89)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            result, report = _call(src, self.TARGET, direct, inverse)
            self.assertEqual(report.valid_cells, 4 * 2)
            self.assertTrue(np.isnan(result.values[:, 3:]).all())
            direct.outside_x = 700_002.0
            result, report = _call(src, self.TARGET, direct, min_valid_fraction=0.25)
        self.assertEqual(report.valid_cells, 6 * 2)
        self.assertTrue(np.isnan(result.values[:, 2:]).all())
        np.testing.assert_allclose(result.values[:, :2], self._expected(0.25)[:, :2] + 50.0,
                                   rtol=0.0, atol=1e-6)


class ContractTest(unittest.TestCase):
    """RF-006-05: parámetros, pareja de transformaciones y argumentos."""

    SRC = _source(6, 6)
    TARGET = CoverageTest.TARGET

    def test_supersample_checked(self) -> None:
        """RF-006-05, RF-006-11: fuera de [1; 16] o no entero, el error del parámetro
        (``ParamError`` ``core.param_*``), con su clave; la fracción mínima, igual."""
        for value, code in ((0, "core.param_out_of_range"), (17, "core.param_out_of_range"),
                            (2.5, "core.param_not_integer")):
            with self.subTest(value=value):
                with self.assertRaises(ParamError) as caught:
                    _call(self.SRC, self.TARGET, Rigid(), supersample=value)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(caught.exception.field, "gis.reproject.supersample")
        with self.assertRaises(ParamError) as caught:
            _call(self.SRC, self.TARGET, Rigid(), min_valid_fraction=0.0)
        self.assertEqual((caught.exception.code, caught.exception.field),
                         ("core.param_out_of_range", "gis.resample.min_valid_fraction"))

    def test_pair_must_be_inverse(self) -> None:
        """La «inversa» que no devuelve los puntos de la directa (≤ 1 mm) es un error del
        programa: nada se reproyecta con una pareja equivocada."""
        direct = Rigid()
        for inverse in (direct, Rigid(shift=(100.3, -200.6), inverse=True)):
            with self.subTest(inverse=inverse.shift), self.assertRaises(ValueError):
                _call(self.SRC, self.TARGET, direct, inverse)

    def test_wrong_arguments(self) -> None:
        """Un método que no es de cotas, o argumentos de otro tipo, son errores del
        programa."""
        for method in ("nearest", "mode", None):
            with self.subTest(method=method), self.assertRaises(ValueError):
                _call(self.SRC, self.TARGET, Rigid(), method=method)
        base = {"transform": Rigid(), "inverse": Rigid(inverse=True),
                "target_crs": H25830, "target_vertical": V5782, "method": AREA_MEAN}
        for key, value in (("transform", object()), ("inverse", None),
                           ("target_crs", 25830), ("target_vertical", None)):
            with self.subTest(argument=key), self.assertRaises(TypeError):
                resample.reproject_to_grid(self.SRC, self.TARGET, **{**base, key: value})
        with self.assertRaises(TypeError):
            resample.reproject_to_grid(self.SRC.values, self.TARGET, **base)

    def test_package_exports(self) -> None:
        self.assertIn("reproject_to_grid", gis.__all__)
        self.assertIs(gis.reproject_to_grid, resample.reproject_to_grid)

    def test_blocks_progress_and_cancel(self) -> None:
        """RF-006-28: con bloques de una fila, el mismo resultado bit a bit; avance tras
        cada bloque hasta 1; si se cancela en el 3.º, ``JobCancelled``."""
        src, direct = _source(), Rigid()
        expected, _ = _call(src, INSIDE, direct)
        seen: list[float] = []
        with mock.patch.object(resample, "BLOCK_ITEMS", 1):
            got, _ = _call(src, INSIDE, direct, progress=lambda frac, text: seen.append(frac))
            asked: list[int] = []

            def cancelled() -> bool:
                asked.append(1)
                return len(asked) > 2

            with self.assertRaises(worker_api.JobCancelled) as caught:
                _call(src, INSIDE, direct, cancelled=cancelled)
        np.testing.assert_array_equal(got.values, expected.values)
        self.assertEqual(len(seen), INSIDE.nrows)
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(seen[-1], 1.0)
        self.assertIn(f"3 de {INSIDE.nrows}", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
