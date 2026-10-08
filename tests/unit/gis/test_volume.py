# SPDX-License-Identifier: GPL-3.0-or-later
"""Volumen entre dos superficies en la misma rejilla (spec 006, T04; plan 006 §5.3.2 y
§5.4 A2; ADR-0014).

- **RF-006-03**: ``volume_between(upper, lower, *, mask, min_thickness_m)`` calcula celda a
  celda, con el área de celda exacta de RF-006-02 (|dx·dy|), el corte (``upper`` por encima
  de ``lower``), el relleno, el neto (corte − relleno, m³), el área con dato y el área sin
  dato (m²). Con d = upper − lower y e = espesor mínimo (A2): corte = Σ max(d − e, 0)·A y
  relleno = Σ max(−d − e, 0)·A sobre las celdas con dato en las dos superficies (y dentro
  de la máscara); una celda sin dato (NaN) en cualquiera de las dos no suma volumen y cuenta
  como área sin dato, salvo que la máscara la deje fuera. Dos superficies en rejillas de
  geometría distinta (esquina, paso o número de celdas, bit a bit), o en CRS o referencia
  vertical distintos, son ``gis.grid_mismatch``. Las entradas no se modifican.

Casos de 3 × 3 celdas de 2 × 1,5 m (A = 3 m², no el cuadrado del paso) con valores binarios
exactos: los resultados se comparan sin tolerancia. Los casos de referencia (corta circular
y prisma B24) están en ``tests/referencia/gis/test_ref_volume.py``.

Además, ``gis.raster.Raster`` (plan 006 §5.3.2), que crea esta tarea: rejilla, valores
float64 de su forma (NaN = sin dato), CRS y referencia vertical.
"""

import math
import unittest

import numpy as np

from tests.support.package import import_geoblender

gis = import_geoblender("gis")
grid = import_geoblender("gis.grid")
raster = import_geoblender("gis.raster")
messages = import_geoblender("gis.messages")
georef = import_geoblender("core.georef")
errors = import_geoblender("core.errors")

NAN = math.nan
CATALOG = georef.load_catalog()
CRS = CATALOG.horizontal(25830)
VERTICAL = CATALOG.vertical(5782)

# Rejilla de 3 × 3 celdas de 2 × 1,5 m en UTM: área de celda 3 m².
GRID = grid.Grid(west=700_000.0, north=4_400_004.5, dx=2.0, dy=1.5, ncols=3, nrows=3)
CELL = 3.0

UPPER = np.array(
    [
        [10.0, 10.0, NAN],
        [10.0, 10.0, 10.0],
        [10.0, 10.0, 10.0],
    ]
)
LOWER = np.array(
    [
        [8.0, 9.0, 10.0],
        [11.0, 12.5, 9.75],
        [10.25, NAN, 7.0],
    ]
)
# d = UPPER − LOWER = [[2, 1, NaN], [−1, −2,5, 0,25], [−0,25, NaN, 3]]: 7 celdas con dato
# (corte 2 + 1 + 0,25 + 3 = 6,25 m; relleno 1 + 2,5 + 0,25 = 3,75 m) y 2 sin dato.
MASK = np.array(
    [
        [True, True, True],
        [False, True, True],
        [True, True, False],
    ]
)


def _raster(values: np.ndarray, *, on: object = GRID, crs: object = CRS,
            vertical: object = VERTICAL) -> object:
    return raster.Raster(grid=on, values=values, crs=crs, vertical=vertical)


def _result(cut: float, fill: float, net: float, area: float, nodata: float) -> object:
    return grid.VolumeResult(
        cut_m3=cut, fill_m3=fill, net_m3=net, area_m2=area, nodata_area_m2=nodata,
        cell_area_m2=CELL,
    )


class VolumeTest(unittest.TestCase):
    """RF-006-03: corte, relleno, neto, área con y sin dato, espesor mínimo y máscara."""

    def setUp(self) -> None:
        self.upper = _raster(UPPER.copy())
        self.lower = _raster(LOWER.copy())

    def test_cut_fill_net_and_areas(self) -> None:
        """Corte 6,25 × 3 = 18,75 m³; relleno 3,75 × 3 = 11,25 m³; neto 7,5 m³; 7 celdas
        con dato (21 m²) y 2 sin dato, una en cada superficie (6 m²)."""
        result = grid.volume_between(self.upper, self.lower)
        self.assertEqual(result, _result(18.75, 11.25, 7.5, 21.0, 6.0))
        for name in ("cut_m3", "fill_m3", "net_m3", "area_m2", "nodata_area_m2",
                     "cell_area_m2"):
            with self.subTest(field=name):
                self.assertIs(type(getattr(result, name)), float)

    def test_swapped_surfaces(self) -> None:
        """Al cambiar de orden las superficies, el corte y el relleno se cambian y el neto
        cambia de signo; las áreas no cambian."""
        result = grid.volume_between(self.lower, self.upper)
        self.assertEqual(result, _result(11.25, 18.75, -7.5, 21.0, 6.0))

    def test_min_thickness(self) -> None:
        """Con espesor mínimo e (A2), cada celda aporta max(d − e, 0) al corte y
        max(−d − e, 0) al relleno: lo que no pasa de e no cuenta (d = 1 con e = 1 da 0).
        El área con dato no depende de e."""
        cases = {
            0.5: (13.5, 7.5, 6.0),  # corte 1,5 + 0,5 + 2,5; relleno 0,5 + 2
            1.0: (9.0, 4.5, 4.5),  # corte 1 + 2; relleno 1,5
            3.0: (0.0, 0.0, 0.0),
            10.0: (0.0, 0.0, 0.0),
        }
        for thickness, (cut, fill, net) in cases.items():
            with self.subTest(min_thickness_m=thickness):
                result = grid.volume_between(self.upper, self.lower, min_thickness_m=thickness)
                self.assertEqual(result, _result(cut, fill, net, 21.0, 6.0))
        self.assertEqual(
            grid.volume_between(self.upper, self.lower, min_thickness_m=1),
            _result(9.0, 4.5, 4.5, 21.0, 6.0),
        )

    def test_mask(self) -> None:
        """La máscara deja fuera (1, 0) (d = −1) y (2, 2) (d = 3): corte 3,25 × 3, relleno
        2,75 × 3; 5 celdas con dato y 2 sin dato dentro de ella (las de fuera no cuentan
        como sin dato)."""
        result = grid.volume_between(self.upper, self.lower, mask=MASK)
        self.assertEqual(result, _result(9.75, 8.25, 1.5, 15.0, 6.0))
        result = grid.volume_between(self.upper, self.lower, mask=MASK, min_thickness_m=0.5)
        self.assertEqual(result, _result(6.0, 6.0, 0.0, 15.0, 6.0))  # 1,5 + 0,5; 2

    def test_empty_mask_and_no_data(self) -> None:
        """Una máscara vacía no suma nada; dos superficies sin dato, todo sin dato."""
        empty = np.zeros((3, 3), dtype=bool)
        self.assertEqual(
            grid.volume_between(self.upper, self.lower, mask=empty),
            _result(0.0, 0.0, 0.0, 0.0, 0.0),
        )
        blank = _raster(np.full((3, 3), NAN))
        self.assertEqual(grid.volume_between(blank, self.lower),
                         _result(0.0, 0.0, 0.0, 0.0, 27.0))
        full = np.ones((3, 3), dtype=bool)
        self.assertEqual(grid.volume_between(self.upper, self.lower, mask=full),
                         grid.volume_between(self.upper, self.lower))

    def test_cell_area_is_exact(self) -> None:
        """RF-006-02 en el volumen: el área de celda es |dx·dy| de la rejilla, también con
        pasos distintos en X y en Y (1,0002942907592702 × 1,0003022974607014 m, B24)."""
        b24 = grid.Grid(west=700_000.0, north=4_400_003.0, dx=1.0002942907592702,
                        dy=1.0003022974607014, ncols=3, nrows=3)
        upper = _raster(np.full((3, 3), 12.0), on=b24)
        lower = _raster(np.full((3, 3), 2.0), on=b24)
        result = grid.volume_between(upper, lower)
        self.assertEqual(result.cell_area_m2, b24.cell_area)
        self.assertEqual(result.cut_m3, 90.0 * b24.cell_area)
        self.assertEqual(result.area_m2, 9.0 * b24.cell_area)

    def test_inputs_unchanged(self) -> None:
        """Las superficies y la máscara no se modifican (constitución: una entrada del
        usuario se lee; lo producido se escribe aparte)."""
        mask = MASK.copy()
        grid.volume_between(self.upper, self.lower, mask=mask, min_thickness_m=0.5)
        np.testing.assert_array_equal(self.upper.values, UPPER)
        np.testing.assert_array_equal(self.lower.values, LOWER)
        np.testing.assert_array_equal(mask, MASK)
        self.assertTrue(self.upper.values.flags.writeable)
        self.assertTrue(mask.flags.writeable)

    def test_bad_arguments(self) -> None:
        """Un espesor mínimo negativo, no finito o que no es un número, y una máscara de
        otra forma o que no es booleana, son errores del programa (``ValueError`` o
        ``TypeError``): quien llama los valida antes."""
        for thickness in (-0.1, NAN, math.inf):
            with self.subTest(min_thickness_m=thickness):
                with self.assertRaises(ValueError):
                    grid.volume_between(self.upper, self.lower, min_thickness_m=thickness)
        for thickness in (True, "1", None):
            with self.subTest(min_thickness_m=thickness):
                with self.assertRaises(TypeError):
                    grid.volume_between(self.upper, self.lower, min_thickness_m=thickness)
        with self.assertRaises(ValueError):
            grid.volume_between(self.upper, self.lower, mask=np.ones((3, 4), dtype=bool))
        for mask in (np.ones((3, 3)), [[True] * 3] * 3):
            with self.subTest(mask=type(mask).__name__):
                with self.assertRaises(TypeError):
                    grid.volume_between(self.upper, self.lower, mask=mask)
        with self.assertRaises(TypeError):
            grid.volume_between(self.upper, LOWER)

    def test_reexported(self) -> None:
        """``gis`` reexporta ``volume_between``, ``VolumeResult`` y ``Raster``."""
        self.assertIs(gis.volume_between, grid.volume_between)
        self.assertIs(gis.VolumeResult, grid.VolumeResult)
        self.assertIs(gis.Raster, raster.Raster)
        for name in ("Raster", "VolumeResult", "volume_between"):
            self.assertIn(name, gis.__all__)


class MismatchTest(unittest.TestCase):
    """RF-006-03: solo se cubica entre superficies de la misma geometría, bit a bit, y del
    mismo CRS y referencia vertical; si no, ``gis.grid_mismatch`` con el detalle."""

    def setUp(self) -> None:
        self.upper = _raster(UPPER.copy())

    def _check(self, lower: object, field: str, value: object, detail: str) -> None:
        with self.assertRaises(messages.GisError) as caught:
            grid.volume_between(self.upper, lower)
        error = caught.exception
        self.assertIsInstance(error, errors.GeoblenderError)
        self.assertEqual(error.code, "gis.grid_mismatch")
        self.assertEqual(error.field, field)
        self.assertEqual(error.value, value)
        self.assertIn(detail, str(error))
        self.assertIn("«superior»", str(error))
        self.assertIn("«inferior»", str(error))

    def test_geometry(self) -> None:
        """Esquina, pasos (1 ulp ya es distinto) y número de columnas o filas."""
        ulp = math.nextafter(2.0, 3.0)
        cases = (
            ({"west": 700_001.0}, "west", 700_001.0, "oeste 700000 frente a 700001"),
            ({"north": 4_400_006.0}, "north", 4_400_006.0, "norte 4400004,5 frente a 4400006"),
            ({"dx": ulp}, "dx", ulp, f"paso en X 2 frente a {repr(ulp).replace('.', ',')}"),
            ({"dy": 1.0}, "dy", 1.0, "paso en Y 1,5 frente a 1"),
            ({"ncols": 4}, "ncols", 4, "columnas 3 frente a 4"),
            ({"nrows": 2}, "nrows", 2, "filas 3 frente a 2"),
        )
        base = {"west": GRID.west, "north": GRID.north, "dx": GRID.dx, "dy": GRID.dy,
                "ncols": GRID.ncols, "nrows": GRID.nrows}
        for change, field, value, detail in cases:
            with self.subTest(field=field):
                other = grid.Grid(**{**base, **change})
                lower = _raster(np.zeros(other.shape), on=other)
                self._check(lower, field, value, detail)

    def test_crs_and_vertical(self) -> None:
        """La misma rejilla en otro CRS o con otra referencia vertical no es la misma
        superficie."""
        lower = _raster(LOWER.copy(), crs=CATALOG.horizontal(23030))
        self._check(lower, "crs", 23030, "CRS EPSG:25830 frente a EPSG:23030")
        local = CATALOG.local_vertical("Cota de obra")
        lower = _raster(LOWER.copy(), vertical=local)
        self._check(lower, "vertical", "Referencia local (Cota de obra)",
                    "referencia vertical EPSG:5782 frente a Referencia local (Cota de obra)")

    def test_names(self) -> None:
        """Los nombres de las superficies van en el mensaje."""
        other = grid.Grid(700_002.0, GRID.north, GRID.dx, GRID.dy, 3, 3)
        lower = _raster(np.zeros((3, 3)), on=other)
        with self.assertRaises(messages.GisError) as caught:
            grid.volume_between(self.upper, lower, names=("MDT 2026", "Corta final"))
        text = str(caught.exception)
        self.assertIn("«MDT 2026»", text)
        self.assertIn("«Corta final»", text)
        self.assertEqual(caught.exception.values["upper"], "MDT 2026")


class RasterTest(unittest.TestCase):
    """``gis.raster.Raster`` (plan 006 §5.3.2): valores float64 de la forma de su rejilla,
    con CRS y referencia vertical; uno mal formado es un error del programa."""

    def test_valid(self) -> None:
        values = LOWER.copy()
        surface = _raster(values)
        self.assertIs(surface.grid, GRID)
        self.assertIs(surface.values, values)  # sin copia
        self.assertIs(surface.crs, CRS)
        self.assertIs(surface.vertical, VERTICAL)
        with self.assertRaises(AttributeError):
            surface.values = UPPER  # type: ignore[misc]

    def test_invalid(self) -> None:
        with self.assertRaises(TypeError):
            _raster(LOWER.astype(np.float32))
        with self.assertRaises(TypeError):
            _raster(LOWER.tolist())
        for shape in ((3,), (3, 4), (4, 3), (3, 3, 1)):
            with self.subTest(shape=shape):
                with self.assertRaises(ValueError):
                    _raster(np.zeros(shape))
        with self.assertRaises(TypeError):
            _raster(LOWER.copy(), on=(700_000.0, 4_400_004.5, 2.0, 1.5, 3, 3))
        with self.assertRaises(TypeError):
            _raster(LOWER.copy(), crs=25830)
        with self.assertRaises(TypeError):
            _raster(LOWER.copy(), vertical=None)


if __name__ == "__main__":
    unittest.main()
