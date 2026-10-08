# SPDX-License-Identifier: GPL-3.0-or-later
"""Aviso de alturas elipsoidales (spec 006, T13; plan 006 §5.3.2 y §5.4 A16; D-8, DP-46).

- **RF-006-06**: si la mediana de (cota nueva − MDT del proyecto), con la bilineal del MDT en
  al menos 100 posiciones comunes, está entre 40 y 60 m en valor absoluto (extremos
  incluidos), se avisa con la mediana: +50 y −45 m avisan (también con un 20 % de cotas
  aberrantes, que moverían la media y no la mediana); 0, ±30 y ±70 m, no; con 99 posiciones
  comunes (las demás en un hueco del MDT, fuera de él o sin cota), no, y con 100, sí. El
  texto del aviso es el del plan §5.5 («… es de 51,3 m …»), en español y en inglés.
- D-8 (DP-46): la banda es la de la península y Baleares (``gis.vertical.ellipsoidal_band_m``,
  40–60 m); en Canarias (el ámbito EPSG de REGCAN95) no hay banda ni aviso hasta que se
  fije la suya. Una banda explícita se comprueba como el parámetro (``gis.param_*``).
- A16: se comparan como mucho :data:`MAX_SAMPLES` posiciones, elegidas siempre igual.
- Las entradas no se modifican (arrays de solo lectura).
"""

import unittest
from unittest import mock

import numpy as np

from tests.support.package import import_geoblender

gis = import_geoblender("gis")
vertical = import_geoblender("gis.vertical")
georef = import_geoblender("core.georef")

CATALOG = georef.load_catalog()
H25830 = CATALOG.horizontal(25830)
V5782 = CATALOG.vertical(5782)
NAME = "mdt_2025"
WEST, SOUTH = 700_000.0, 4_400_000.0


def _plane(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Cota del MDT de referencia: un plano con pendiente en X y en Y."""
    return 800.0 + 0.02 * (x - WEST) - 0.01 * (y - SOUTH)


def _reference(surface=_plane, *, crs=H25830, vertical_ref=V5782, west=WEST,
               south=SOUTH) -> object:
    """El MDT de referencia: 40 × 40 celdas de 1 m con un hueco de 10 × 10 celdas en la
    esquina SE (sin dato), de solo lectura."""
    grid = gis.Grid(west=west, north=south + 40.0, dx=1.0, dy=1.0, ncols=40, nrows=40)
    x, y = grid.centers()
    values = surface(x - west + WEST, y - south + SOUTH)
    values[30:, 30:] = np.nan
    values.flags.writeable = False  # una entrada nunca se modifica
    return gis.Raster(grid, values, crs, vertical_ref)


def _inside(count: int = 225, *, west=WEST, south=SOUTH) -> tuple[np.ndarray, np.ndarray]:
    """``count`` posiciones (≤ 225) de una malla de 15 × 15 dentro del MDT, lejos del hueco y
    sin caer en sus centros."""
    i, j = np.meshgrid(np.arange(15), np.arange(15))
    x = west + 1.3 + 1.7 * i.ravel()
    y = south + 12.2 + 1.9 * j.ravel()
    return x[:count], y[:count]


def _points(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
    xyz = np.column_stack((x, y, z))
    xyz.flags.writeable = False  # una entrada nunca se modifica
    return xyz


def _shifted(offset: float, *, outliers: int = 0, surface=_plane) -> np.ndarray:
    """Las 225 posiciones con la cota del MDT + ``offset``; las ``outliers`` primeras, con
    +400 m (cotas aberrantes que no mueven la mediana)."""
    x, y = _inside()
    z = surface(x, y) + offset
    z[:outliers] = surface(x[:outliers], y[:outliers]) + 400.0
    return _points(x, y, z)


def _constant(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.full(np.broadcast(x, y).shape, 700.0)


class OffsetTest(unittest.TestCase):
    """RF-006-06: aviso con la mediana dentro de la banda de 40–60 m en valor absoluto."""

    def test_offsets_inside_the_band_warn_with_the_median(self) -> None:
        """+50 y −45 m (y +51,3 m) avisan con la mediana (≤ 10⁻⁹ m), también con 45 de las
        225 cotas a +400 m; las 225 posiciones son comunes."""
        reference = _reference()
        for offset, outliers in ((50.0, 0), (-45.0, 0), (51.3, 0), (50.0, 45), (-45.0, 45)):
            with self.subTest(offset=offset, outliers=outliers):
                check = vertical.check_vertical_offset(
                    _shifted(offset, outliers=outliers), reference, name=NAME)
                self.assertTrue(check.warn)
                self.assertAlmostEqual(check.median_m, offset, delta=1e-9)
                self.assertEqual(check.samples, 225)
                self.assertEqual(check.positions, 225)
                self.assertEqual(check.band_m, (40.0, 60.0))
                self.assertEqual(check.min_samples, 100)
                self.assertEqual(check.reference, NAME)

    def test_offsets_outside_the_band_do_not_warn(self) -> None:
        """0, ±30 y ±70 m no avisan; la mediana se da igualmente."""
        reference = _reference()
        for offset in (0.0, 30.0, 70.0, -30.0, -70.0):
            with self.subTest(offset=offset):
                check = vertical.check_vertical_offset(_shifted(offset), reference)
                self.assertFalse(check.warn)
                self.assertAlmostEqual(check.median_m, offset, delta=1e-9)
                self.assertEqual(check.samples, 225)
                self.assertIsNone(check.message())

    def test_band_edges_are_included(self) -> None:
        """40 y 60 m exactos (y −40, −60) avisan; 39,9 y 60,1 m, no."""
        reference = _reference(_constant)
        for offset, warn in ((40.0, True), (60.0, True), (-40.0, True), (-60.0, True),
                             (39.9, False), (60.1, False)):
            with self.subTest(offset=offset):
                check = vertical.check_vertical_offset(
                    _shifted(offset, surface=_constant), reference)
                self.assertEqual(check.warn, warn)

    def test_message_shows_the_median(self) -> None:
        """El aviso del plan §5.5, con la mediana al decímetro; sin aviso, ``None``."""
        reference = _reference()
        check = vertical.check_vertical_offset(_shifted(51.3), reference, name=NAME)
        self.assertEqual(
            check.message(),
            "La mediana de la diferencia con el MDT «mdt_2025» es de 51,3 m: las cotas "
            "pueden ser alturas elipsoidales (GNSS o dron sin geoide). ¿Continuar?",
        )
        self.assertEqual(
            check.message("en"),
            "The median difference with DTM «mdt_2025» is 51.3 m: the elevations may be "
            "ellipsoidal heights (GNSS or drone without geoid). Continue?",
        )
        check = vertical.check_vertical_offset(_shifted(-45.0), reference, name=NAME)
        self.assertIn("es de -45 m", check.message())


class SamplesTest(unittest.TestCase):
    """RF-006-06: hacen falta al menos 100 posiciones comunes; A16: como mucho 100.000."""

    def _mixed(self, common: int) -> np.ndarray:
        """``common`` posiciones comunes a +50 m y 60 que no lo son: 20 en el hueco del MDT,
        20 fuera de él y 20 sin cota."""
        x, y = _inside(common)
        hole_x = WEST + 32.3 + 0.3 * np.arange(20)
        hole_y = np.full(20, SOUTH + 5.2)
        out_x = WEST - 5.0 - np.arange(20)
        out_y = np.full(20, SOUTH + 20.0)
        nan_x, nan_y = _inside(20)
        xs = np.concatenate((x, hole_x, out_x, nan_x))
        ys = np.concatenate((y, hole_y, out_y, nan_y))
        z = _plane(xs, ys) + 50.0
        z[-20:] = np.nan
        return _points(xs, ys, z)

    def test_fewer_than_100_common_positions_do_not_warn(self) -> None:
        """Con 99 posiciones comunes, sin aviso y sin mediana; con 100, aviso. Las que caen
        en el hueco, fuera del MDT o sin cota no cuentan."""
        reference = _reference()
        check = vertical.check_vertical_offset(self._mixed(99), reference)
        self.assertFalse(check.warn)
        self.assertIsNone(check.median_m)
        self.assertEqual(check.samples, 99)
        self.assertEqual(check.positions, 139)
        self.assertIsNone(check.message())
        check = vertical.check_vertical_offset(self._mixed(100), reference)
        self.assertTrue(check.warn)
        self.assertAlmostEqual(check.median_m, 50.0, delta=1e-9)
        self.assertEqual(check.samples, 100)

    def test_min_samples_argument(self) -> None:
        """``min_samples`` explícito: con 10, 99 posiciones bastan; 0 o no entero es un
        error del programa."""
        reference = _reference()
        check = vertical.check_vertical_offset(self._mixed(99), reference, min_samples=10)
        self.assertTrue(check.warn)
        self.assertEqual(check.min_samples, 10)
        for bad in (0, -1, 2.5, True):
            with self.subTest(min_samples=bad), self.assertRaises((TypeError, ValueError)):
                vertical.check_vertical_offset(self._mixed(99), reference, min_samples=bad)

    def test_subsample_is_bounded_and_repeatable(self) -> None:
        """Con más posiciones que :data:`MAX_SAMPLES` (aquí, 150 de 225) se comparan 150,
        repartidas por toda la lista y siempre las mismas: con la diferencia creciente con el
        orden (0,1 m por posición), la mediana es la de esas 150 (11,15 m), no la de las 225
        (11,2 m)."""
        self.assertEqual(vertical.MAX_SAMPLES, 100_000)
        self.assertEqual(vertical.MIN_SAMPLES, 100)
        reference = _reference()
        x, y = _inside()
        z = _plane(x, y) + 0.1 * np.arange(225)
        xyz = _points(x, y, z)
        with mock.patch.object(vertical, "MAX_SAMPLES", 150):
            first = vertical.check_vertical_offset(xyz, reference)
            second = vertical.check_vertical_offset(xyz, reference)
        self.assertEqual(first.samples, 150)
        self.assertEqual(first.positions, 225)
        chosen = (np.arange(150) * 225) // 150
        expected = float(np.median(z[chosen] - _plane(x[chosen], y[chosen])))
        self.assertAlmostEqual(expected, 11.15, delta=1e-9)
        self.assertAlmostEqual(first.median_m, expected, delta=1e-9)
        self.assertEqual((first.median_m, first.samples), (second.median_m, second.samples))


class BandTest(unittest.TestCase):
    """D-8 (DP-46): la banda de la península y Baleares; en Canarias, sin aviso."""

    def test_band_is_the_parameter(self) -> None:
        params = import_geoblender("gis.params")
        self.assertEqual(params.default("gis.vertical.ellipsoidal_band_m"), (40.0, 60.0))
        self.assertEqual(vertical.ellipsoidal_band(_reference()), (40.0, 60.0))

    def test_balearic_islands_use_the_band(self) -> None:
        """Mallorca (ETRS89 / UTM 31N y altitudes de Mallorca, EPSG:9392) avisa a +50 m."""
        west, south = 490_000.0, 4_380_000.0
        reference = _reference(crs=CATALOG.horizontal(25831),
                               vertical_ref=CATALOG.vertical(9392), west=west, south=south)
        x, y = _inside(west=west, south=south)
        z = _plane(x - west + WEST, y - south + SOUTH) + 50.0
        check = vertical.check_vertical_offset(_points(x, y, z), reference)
        self.assertEqual(check.band_m, (40.0, 60.0))
        self.assertTrue(check.warn)

    def test_canary_islands_have_no_band(self) -> None:
        """Tenerife en REGCAN95 / UTM 28N (EPSG:4083) y en ETRS89 / UTM 28N (EPSG:25828):
        sin banda ni aviso a +50 m; la mediana se da igualmente."""
        west, south = 350_000.0, 3_130_000.0
        for epsg in (4083, 25828):
            with self.subTest(epsg=epsg):
                reference = _reference(crs=CATALOG.horizontal(epsg),
                                       vertical_ref=CATALOG.vertical(9398),
                                       west=west, south=south)
                self.assertIsNone(vertical.ellipsoidal_band(reference))
                x, y = _inside(west=west, south=south)
                z = _plane(x - west + WEST, y - south + SOUTH) + 50.0
                check = vertical.check_vertical_offset(_points(x, y, z), reference)
                self.assertIsNone(check.band_m)
                self.assertFalse(check.warn)
                self.assertAlmostEqual(check.median_m, 50.0, delta=1e-9)
                self.assertIsNone(check.message())

    def test_explicit_band(self) -> None:
        """Una banda explícita manda (también en Canarias) y se comprueba como el
        parámetro: desordenada o fuera de [0; 200] m → ``gis.param_*``."""
        reference = _reference()
        check = vertical.check_vertical_offset(_shifted(45.0), reference, band_m=[30, 45])
        self.assertTrue(check.warn)
        self.assertEqual(check.band_m, (30.0, 45.0))
        for band, code in (((60.0, 40.0), "gis.param_not_list"),
                           ((40.0,), "gis.param_not_list"),
                           ((40.0, 250.0), "gis.param_out_of_range")):
            with self.subTest(band=band), self.assertRaises(gis.GisError) as caught:
                vertical.check_vertical_offset(_shifted(45.0), reference, band_m=band)
            self.assertEqual(caught.exception.code, code)


class ContractTest(unittest.TestCase):
    """Entradas mal formadas: errores del programa; la API, en ``gis``."""

    def test_bad_inputs(self) -> None:
        reference = _reference()
        xyz = _shifted(50.0)
        with self.assertRaises(TypeError):
            vertical.check_vertical_offset(xyz, reference.values)
        with self.assertRaises(TypeError):
            vertical.check_vertical_offset(xyz.tolist(), reference)
        with self.assertRaises(ValueError):
            vertical.check_vertical_offset(xyz[:, :2], reference)
        with self.assertRaises(TypeError):
            vertical.check_vertical_offset(xyz.astype(np.int64), reference)

    def test_empty_input(self) -> None:
        check = vertical.check_vertical_offset(np.empty((0, 3)), _reference())
        self.assertFalse(check.warn)
        self.assertIsNone(check.median_m)
        self.assertEqual((check.samples, check.positions), (0, 0))

    def test_package_reexports(self) -> None:
        for name in ("VerticalCheck", "check_vertical_offset", "ellipsoidal_band"):
            with self.subTest(name=name):
                self.assertIn(name, gis.__all__)
                self.assertIs(getattr(gis, name), getattr(vertical, name))


if __name__ == "__main__":
    unittest.main()
