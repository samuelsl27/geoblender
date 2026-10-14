# SPDX-License-Identifier: GPL-3.0-or-later
"""Validación de una superficie en rejilla (spec 006, T14; plan 006 §5.3.2 y §5.4 A17).

- **RF-006-23**: ``validate_raster(raster, *, window, z_range)`` informa del área de la
  rejilla y del área y el porcentaje sin dato (m², %), del área de cada hueco interior (m²),
  de las celdas con dato fuera de la ventana de trabajo y de las cotas fuera del rango
  plausible (``gis.validate.z_range_m``, de −500 a 5.000 m con los extremos dentro; −9999 y
  6.000 m quedan fuera: un posible sin dato no declarado).
- A17: los huecos son las componentes 4-conexas del sin dato (NaN o ±∞); las que tocan el
  borde de la rejilla son el sin dato exterior y no son huecos. Cada área es el número de
  celdas por el área exacta de la celda (|dx·dy|, RF-006-02), sin tolerancia. Los huecos van
  de mayor a menor área y, a igual área, por su primera celda (de norte a sur y de oeste a
  este). Una celda está fuera de la ventana si alguna parte de ella queda fuera (con una
  tolerancia de 10⁻⁹ del paso).

Las componentes se comparan con un relleno por inundación independiente, celda a celda, en
máscaras aleatorias. Las entradas no se modifican (arrays de solo lectura).
"""

import math
import unittest
from collections import deque
from unittest import mock

import numpy as np

from tests.support.package import import_geoblender

gis = import_geoblender("gis")
validate = import_geoblender("gis.validate")
georef = import_geoblender("core.georef")
ParamError = import_geoblender("core.params").ParamError

NAN = math.nan
CATALOG = georef.load_catalog()
CRS = CATALOG.horizontal(25830)
VERTICAL = CATALOG.vertical(5782)
WEST, NORTH = 700_000.0, 4_400_015.0
DX, DY = 2.0, 1.5  # área de celda 3 m², no el cuadrado del paso
B24_DX = 1.0002942907592702
B24_DY = 1.0003022974607014

# 12 × 10 celdas («#» = sin dato): exterior en tres esquinas (14 celdas: NO, NE y SO), un
# hueco en forma de C de 5 celdas (15 m²) y uno de 1 celda (3 m²).
LAYOUT = (
    "##........##",
    "#..........#",
    "#..##.......",
    "...#....#...",
    "...##.......",
    "............",
    "............",
    "............",
    "###.........",
    "####........",
)


def _mask(layout) -> np.ndarray:
    return np.array([[cell == "#" for cell in row] for row in layout], dtype=bool)


def _values(mask: np.ndarray, *, nodata: float = NAN) -> np.ndarray:
    """Un plano con pendiente y ``nodata`` donde marca la máscara."""
    rows, cols = np.indices(mask.shape, dtype=np.float64)
    values = 800.0 + 0.1 * cols - 0.2 * rows
    values[mask] = nodata
    return values


def _raster(values, *, dx: float = DX, dy: float = DY, west: float = WEST,
            north: float = NORTH):
    array = np.array(values, dtype=np.float64)
    array.flags.writeable = False  # una entrada nunca se modifica
    nrows, ncols = array.shape
    grid = gis.Grid(west=west, north=north, dx=dx, dy=dy, ncols=ncols, nrows=nrows)
    return gis.Raster(grid, array, CRS, VERTICAL)


def _extent(raster):
    return raster.grid.extent


def _flood(mask: np.ndarray) -> list[tuple[int, int, bool]]:
    """Componentes 4-conexas de ``mask`` por inundación, celda a celda: (celdas, primera
    celda en orden de filas, toca el borde), en el orden de su primera celda."""
    nrows, ncols = mask.shape
    seen = np.zeros_like(mask)
    found = []
    for row in range(nrows):
        for col in range(ncols):
            if not mask[row, col] or seen[row, col]:
                continue
            seen[row, col] = True
            queue = deque([(row, col)])
            cells, border = 0, False
            while queue:
                r, c = queue.popleft()
                cells += 1
                border |= r in (0, nrows - 1) or c in (0, ncols - 1)
                for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                    if 0 <= nr < nrows and 0 <= nc < ncols and mask[nr, nc] \
                            and not seen[nr, nc]:
                        seen[nr, nc] = True
                        queue.append((nr, nc))
            found.append((cells, row * ncols + col, border))
    return found


def _expected_holes(mask: np.ndarray, cell_area: float) -> tuple[float, ...]:
    """Las áreas de los huecos interiores por inundación, de mayor a menor y, a igual área,
    por su primera celda."""
    holes = [(cells, first) for cells, first, border in _flood(mask) if not border]
    holes.sort(key=lambda hole: (-hole[0], hole[1]))
    return tuple(cells * cell_area for cells, _ in holes)


def _outside_brute(raster, window) -> int:
    """Celdas con dato con alguna parte fuera de ``window``, celda a celda."""
    grid = raster.grid
    count = 0
    for row in range(grid.nrows):
        top = grid.north - row * grid.dy
        bottom = grid.north - (row + 1) * grid.dy
        for col in range(grid.ncols):
            left = grid.west + col * grid.dx
            right = grid.west + (col + 1) * grid.dx
            inside = (left >= window.xmin and right <= window.xmax
                      and bottom >= window.ymin and top <= window.ymax)
            if math.isfinite(raster.values[row, col]) and not inside:
                count += 1
    return count


class HolesTest(unittest.TestCase):
    """RF-006-23 (A17): área y porcentaje sin dato; huecos interiores frente al exterior."""

    def test_exterior_nodata_and_two_interior_holes(self) -> None:
        """Sin dato exterior en tres esquinas (14 celdas) frente a dos huecos interiores de 5
        y 1 celdas: 2 huecos de 15 y 3 m² exactos; 20 celdas sin dato = 60 m² de 360 m²
        (16,67 %)."""
        raster = _raster(_values(_mask(LAYOUT)))
        report = validate.validate_raster(raster, window=_extent(raster))
        self.assertEqual(report.surface_type, "grid")
        self.assertEqual(report.area_m2, 360.0)
        self.assertEqual(report.nodata_area_m2, 60.0)
        self.assertEqual(report.nodata_pct, 60.0 / 360.0 * 100.0)
        self.assertEqual(report.hole_areas_m2, (15.0, 3.0))
        self.assertEqual(len(report.hole_areas_m2), 2)
        self.assertEqual(report.cells_outside_window, 0)
        self.assertEqual(report.out_of_range, 0)
        self.assertEqual(report.z_range_m, (-500.0, 5000.0))
        self.assertIsNone(report.flat_pct)
        self.assertIsNone(report.max_edge_m)
        self.assertIsNone(report.degenerate)

    def test_areas_use_the_exact_cell_area(self) -> None:
        """Con los pasos de una rejilla importada (B24), cada área es el número de celdas
        por |dx·dy|, sin tolerancia."""
        raster = _raster(_values(_mask(LAYOUT)), dx=B24_DX, dy=B24_DY)
        report = validate.validate_raster(raster, window=_extent(raster))
        area = abs(B24_DX * B24_DY)
        self.assertEqual(report.area_m2, 120 * area)
        self.assertEqual(report.nodata_area_m2, 20 * area)
        self.assertEqual(report.hole_areas_m2, (5 * area, 1 * area))

    def test_infinities_are_nodata(self) -> None:
        """±∞ es sin dato, como NaN (no una cota fuera de rango)."""
        mask = _mask(LAYOUT)
        values = _values(mask)
        values[3, 8] = math.inf
        values[2, 3] = -math.inf
        raster = _raster(values)
        report = validate.validate_raster(raster, window=_extent(raster))
        self.assertEqual(report.hole_areas_m2, (15.0, 3.0))
        self.assertEqual(report.out_of_range, 0)

    def test_four_connectivity(self) -> None:
        """Una celda que solo toca el exterior en diagonal es un hueco; un canal de una
        celda hasta el borde lo hace exterior; una U cuyos brazos se unen abajo es un solo
        hueco; a igual área, el orden es el de la primera celda."""
        layout = (
            "#.........",   # (0,0): exterior
            ".#.....#..",   # (1,1): solo en diagonal con (0,0) → hueco; (1,7) → hueco
            "...#.#....",   # U: brazos en las columnas 3 y 5…
            "...#.#.#..",   # …(3,7) → hueco
            "...###....",   # …unidos en la fila 4 → un hueco de 7 celdas
            "..........",
            "........#.",   # (6,8)-(7,8)-(7,9): toca el borde este → exterior
            "........##",
            ".##.......",   # bloque con un canal de una celda hasta el borde sur →
            "..#.......",   # exterior
        )
        mask = _mask(layout)
        raster = _raster(_values(mask))
        report = validate.validate_raster(raster, window=_extent(raster))
        # Huecos: la U (7 celdas) y (1,1), (1,7) y (3,7), de 1 celda, por su primera celda.
        self.assertEqual(report.hole_areas_m2, (21.0, 3.0, 3.0, 3.0))
        self.assertEqual(report.hole_areas_m2, _expected_holes(mask, 3.0))
        self.assertEqual(report.nodata_area_m2, int(mask.sum()) * 3.0)

    def test_without_nodata_or_all_nodata(self) -> None:
        """Sin ningún sin dato: 0 m² y ningún hueco. Todo sin dato: el 100 %, exterior."""
        full = _raster(_values(np.zeros((4, 5), dtype=bool)))
        report = validate.validate_raster(full, window=_extent(full))
        self.assertEqual((report.nodata_area_m2, report.hole_areas_m2), (0.0, ()))
        self.assertEqual(report.nodata_pct, 0.0)
        empty = _raster(np.full((4, 5), NAN))
        report = validate.validate_raster(empty, window=_extent(empty))
        self.assertEqual(report.nodata_area_m2, 60.0)
        self.assertEqual(report.nodata_pct, 100.0)
        self.assertEqual(report.hole_areas_m2, ())
        self.assertEqual(report.cells_outside_window, 0)
        single = _raster(np.array([[NAN]]))
        self.assertEqual(validate.validate_raster(single, window=_extent(single))
                         .hole_areas_m2, ())

    def test_random_masks_match_a_flood_fill(self) -> None:
        """Máscaras aleatorias de 23 × 31 celdas (30–65 % sin dato, cerca del umbral de
        percolación: componentes ramificadas y huecos dentro de huecos de dato): las mismas
        áreas que la inundación celda a celda, en el mismo orden."""
        rng = np.random.default_rng(20261008)
        for fraction in (0.3, 0.45, 0.5, 0.55, 0.6, 0.65):
            mask = rng.random((23, 31)) < fraction
            raster = _raster(_values(mask))
            with self.subTest(fraction=fraction):
                report = validate.validate_raster(raster, window=_extent(raster))
                self.assertEqual(report.hole_areas_m2, _expected_holes(mask, 3.0))
                self.assertEqual(report.nodata_area_m2, int(mask.sum()) * 3.0)

    def test_row_blocks_give_the_same_report(self) -> None:
        """Por bloques de una fila, el mismo informe que de una vez."""
        rng = np.random.default_rng(7)
        mask = rng.random((17, 13)) < 0.5
        values = _values(mask)
        values[5, 5] = 6000.0
        raster = _raster(values)
        window = georef.Window(WEST + 4.0, NORTH - 21.0, WEST + 20.0, NORTH - 3.0)
        whole = validate.validate_raster(raster, window=window)
        with mock.patch.object(validate, "BLOCK_ITEMS", 1):
            blocks = validate.validate_raster(raster, window=window)
        self.assertEqual(blocks, whole)
        self.assertEqual(whole.hole_areas_m2, _expected_holes(mask & (values != 6000.0), 3.0))
        self.assertEqual(whole.out_of_range, 1)
        self.assertEqual(whole.cells_outside_window, _outside_brute(raster, window))
        self.assertGreater(whole.cells_outside_window, 0)


class WindowTest(unittest.TestCase):
    """RF-006-23: celdas con dato fuera de la ventana de trabajo."""

    def test_cells_outside_the_window(self) -> None:
        """Ventana sin las 2 columnas de cada lado ni las 2 filas del sur: 42 celdas con
        dato fuera (12 + 17 + 13; las sin dato no cuentan)."""
        raster = _raster(_values(_mask(LAYOUT)))
        window = georef.Window(WEST + 4.0, NORTH - 12.0, WEST + 20.0, NORTH)
        report = validate.validate_raster(raster, window=window)
        self.assertEqual(report.cells_outside_window, 42)
        self.assertEqual(report.cells_outside_window, _outside_brute(raster, window))
        # Los huecos y el sin dato no dependen de la ventana.
        self.assertEqual(report.hole_areas_m2, (15.0, 3.0))
        self.assertEqual(report.nodata_area_m2, 60.0)

    def test_partly_outside_cells_count(self) -> None:
        """Una celda con una parte fuera cuenta: la columna 2 (oeste 700.004–700.006) con la
        ventana desde 700.005; y la fila 0 con la ventana hasta 0,1 m por debajo del norte."""
        raster = _raster(_values(_mask(LAYOUT)))
        for window in (georef.Window(WEST + 5.0, NORTH - 15.0, WEST + 24.0, NORTH),
                       georef.Window(WEST, NORTH - 15.0, WEST + 24.0, NORTH - 0.1),
                       georef.Window(WEST + 3.0, NORTH - 13.7, WEST + 21.1, NORTH - 2.0)):
            with self.subTest(window=window):
                report = validate.validate_raster(raster, window=window)
                self.assertEqual(report.cells_outside_window,
                                 _outside_brute(raster, window))
                self.assertGreater(report.cells_outside_window, 0)

    def test_window_around_or_away(self) -> None:
        """Una ventana que contiene la rejilla: 0 fuera; una que no la toca: todas las celdas
        con dato (100 de 120)."""
        raster = _raster(_values(_mask(LAYOUT)))
        around = georef.Window(WEST - 100.0, NORTH - 200.0, WEST + 100.0, NORTH + 100.0)
        away = georef.Window(WEST + 1000.0, NORTH, WEST + 1100.0, NORTH + 100.0)
        self.assertEqual(validate.validate_raster(raster, window=around)
                         .cells_outside_window, 0)
        self.assertEqual(validate.validate_raster(raster, window=away)
                         .cells_outside_window, 100)

    def test_edge_tolerance(self) -> None:
        """La ventana igual a la extensión de una rejilla B24, o dentro de ella por 10⁻¹⁰ del
        paso, deja 0 celdas fuera; por 10⁻⁶ m, la columna del borde cuenta."""
        raster = _raster(_values(np.zeros((6, 7), dtype=bool)), dx=B24_DX, dy=B24_DY,
                         west=700_123.0, north=4_400_321.5)
        extent = _extent(raster)
        self.assertEqual(validate.validate_raster(raster, window=extent)
                         .cells_outside_window, 0)
        near = georef.Window(extent.xmin + 1e-10 * B24_DX, extent.ymin, extent.xmax,
                             extent.ymax - 1e-10 * B24_DY)
        self.assertEqual(validate.validate_raster(raster, window=near)
                         .cells_outside_window, 0)
        inner = georef.Window(extent.xmin, extent.ymin, extent.xmax - 1e-6, extent.ymax)
        self.assertEqual(validate.validate_raster(raster, window=inner)
                         .cells_outside_window, 6)


class RangeTest(unittest.TestCase):
    """RF-006-23: cotas fuera del rango plausible (posible sin dato no declarado)."""

    def _values(self) -> np.ndarray:
        values = _values(np.zeros((5, 6), dtype=bool))
        values[1, 1] = -9999.0
        values[1, 2] = 6000.0
        values[2, 1] = -500.0    # extremos: dentro del rango
        values[2, 2] = 5000.0
        values[3, 1] = -500.001
        values[3, 2] = 5000.001
        values[4, 0] = NAN       # sin dato en el borde: ni hueco ni fuera de rango
        values[0, 5] = -math.inf
        return values

    def test_default_range(self) -> None:
        """−9999, 6.000, −500,001 y 5.000,001 m están fuera de [−500; 5.000] m; −500 y
        5.000 m, dentro; NaN y −∞ son sin dato."""
        raster = _raster(self._values())
        report = validate.validate_raster(raster, window=_extent(raster))
        self.assertEqual(report.out_of_range, 4)
        self.assertEqual(report.z_range_m, (-500.0, 5000.0))
        self.assertEqual(report.nodata_area_m2, 6.0)
        self.assertEqual(report.hole_areas_m2, ())

    def test_explicit_range(self) -> None:
        """Un rango explícito manda y se comprueba como el parámetro
        (``gis.validate.z_range_m``): desordenado o fuera de [−11.000; 9.000] m →
        ``ParamError`` ``core.param_*`` con la clave (RF-006-23)."""
        raster = _raster(self._values())
        report = validate.validate_raster(raster, window=_extent(raster), z_range=[0, 1000])
        self.assertEqual(report.out_of_range, 6)  # −9999, 6000, −500, 5000, −500,001…
        self.assertEqual(report.z_range_m, (0.0, 1000.0))
        report = validate.validate_raster(raster, window=_extent(raster),
                                          z_range=(-10000.0, 5500.0))
        self.assertEqual(report.out_of_range, 1)
        for bad, code in (((1000.0, 0.0), "core.param_not_list"),
                          ((0.0,), "core.param_not_list"),
                          ((-20000.0, 0.0), "core.param_out_of_range")):
            with self.subTest(z_range=bad), self.assertRaises(ParamError) as caught:
                validate.validate_raster(raster, window=_extent(raster), z_range=bad)
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(caught.exception.field, "gis.validate.z_range_m")


class ContractTest(unittest.TestCase):
    """Entradas intactas; mal formadas, errores del programa; la API, en ``gis``."""

    def test_input_untouched(self) -> None:
        raster = _raster(_values(_mask(LAYOUT)))
        before = raster.values.copy()
        validate.validate_raster(raster, window=_extent(raster))
        np.testing.assert_array_equal(raster.values, before)
        self.assertFalse(raster.values.flags.writeable)

    def test_bad_inputs(self) -> None:
        raster = _raster(_values(_mask(LAYOUT)))
        with self.assertRaises(TypeError):
            validate.validate_raster(raster.values, window=_extent(raster))
        with self.assertRaises(TypeError):
            validate.validate_raster(raster, window=(WEST, NORTH - 15.0, WEST + 24.0, NORTH))

    def test_exported(self) -> None:
        self.assertIs(gis.validate_raster, validate.validate_raster)
        self.assertIn("validate_raster", gis.__all__)


if __name__ == "__main__":
    unittest.main()
