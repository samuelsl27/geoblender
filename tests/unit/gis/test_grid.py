# SPDX-License-Identifier: GPL-3.0-or-later
"""Rejilla de paso exacto (spec 006, T03; plan 006 §5.3.2 y §5.4 A1; ADR-0014).

- **RF-006-01**: el paso de una rejilla del proyecto es múltiplo de 0,5 m entre 0,5 y 5 m
  (0,25, 0,75 y 5,5 se rechazan con ``gis.step_invalid`` y el valor); sus cuatro bordes son
  múltiplos enteros de la unidad de alineación del paso (``core.georef.alignment_unit`` de
  la 002, que ``gis.grid`` no redefine: 0,5 → 1, 1 → 1, 1,5 → 3, 2,5 → 5, 4,5 → 9, 5 → 5);
  ``aligned_grid`` amplía la extensión hacia fuera y ``project_grid`` no acepta una ventana
  sin alinear (``gis.window_not_aligned``).
- **RF-006-02**: el área de celda es el cuadrado exacto del paso en las rejillas del
  proyecto y |dx·dy| en las importadas, nunca un valor nominal: la celda «de 1 m» de
  Silvestre, de 1,000294 × 1,000302 m (B24, su prueba ``test_B24_area_real_celda``), mide
  1,0005967 m² y no 1 m².

Además, lo que usan las tareas siguientes: la georreferencia (``transform``), la extensión
(``extent``, un ``core.georef.Window``), los centros de celda en float64 absoluto, de norte a
sur, y la comparación de geometría bit a bit (``same_geometry``, para ``gis.grid_mismatch``).
"""

import math
import unittest
from fractions import Fraction
from pathlib import Path

import numpy as np

from tests.support.package import import_geoblender

gis = import_geoblender("gis")
grid = import_geoblender("gis.grid")
messages = import_geoblender("gis.messages")
georef = import_geoblender("core.georef")
errors = import_geoblender("core.errors")

# Paso válido → unidad de alineación (RF-006-01, RF-002-24): el menor entero de metros
# múltiplo del paso.
UNITS: dict[float, int] = {
    0.5: 1, 1.0: 1, 1.5: 3, 2.0: 2, 2.5: 5, 3.0: 3, 3.5: 7, 4.0: 4, 4.5: 9, 5.0: 5,
}

# Celda real de la rejilla «de 1 m» de Silvestre (B24; plan 006 §5.4 A2).
B24_DX = 1.0002942907592702
B24_DY = 1.0003022974607014


def _windows() -> tuple[object, ...]:
    """Extensiones de prueba: en UTM (huso 30), con bordes ya múltiplos de 9 m (ninguno
    se mueve), con coordenadas negativas (locales) y de menos de una celda."""
    return (
        georef.Window(700000.3, 4399990.7, 700010.2, 4400003.1),
        georef.Window(699993.0, 4399989.0, 700011.0, 4400010.0),
        georef.Window(-7.2, -3.1, 4.4, 2.0),
        georef.Window(0.1, 0.1, 0.2, 0.2),
    )


class StepTest(unittest.TestCase):
    """RF-006-01: pasos admitidos y rechazados."""

    def test_valid_steps(self) -> None:
        for step in UNITS:
            with self.subTest(step=step):
                self.assertIsNone(grid.validate_step(step))
        self.assertIsNone(grid.validate_step(1))  # un entero también es un paso

    def test_invalid_steps(self) -> None:
        """0,25, 0,75 y 5,5 (los de la tarea) y lo que no es un paso: ``gis.step_invalid``
        con el valor, en el texto y en el error."""
        for step, shown in ((0.25, "0,25"), (0.75, "0,75"), (5.5, "5,5")):
            with self.subTest(step=step):
                with self.assertRaises(messages.GisError) as caught:
                    grid.validate_step(step)
                error = caught.exception
                self.assertIsInstance(error, errors.GeoblenderError)
                self.assertEqual(error.code, "gis.step_invalid")
                self.assertEqual(error.value, step)
                self.assertIn(f"{shown} m", str(error))
                self.assertEqual(str(error), messages.render("gis.step_invalid", value=step))
        for step in (0.0, -1.0, 0.4999, 5.0000001, 10.0, math.nan, math.inf, True, "1",
                     None):
            with self.subTest(step=step):
                with self.assertRaises(messages.GisError) as caught:
                    grid.validate_step(step)
                self.assertEqual(caught.exception.code, "gis.step_invalid")

    def test_invalid_step_in_grids(self) -> None:
        """Ninguna rejilla del proyecto se crea con otro paso (el error de ``gis``, no el
        de ``core``)."""
        window = georef.Window(0.0, 0.0, 9.0, 9.0)
        for step in (0.25, 0.75, 5.5):
            for make in (grid.aligned_grid, grid.project_grid):
                with self.subTest(step=step, make=make.__name__):
                    with self.assertRaises(messages.GisError) as caught:
                        make(window, step)
                    self.assertEqual(caught.exception.code, "gis.step_invalid")
                    self.assertEqual(caught.exception.value, step)


class AlignmentTest(unittest.TestCase):
    """RF-006-01: bordes múltiplos de la unidad de alineación, ampliados hacia fuera."""

    def test_uses_core_georef(self) -> None:
        """``Window`` y ``alignment_unit`` son los de ``core.georef`` (002), sin
        redefinirlos."""
        self.assertIs(grid.Window, georef.Window)
        self.assertIs(grid.alignment_unit, georef.alignment_unit)
        source = Path(grid.__file__).read_text(encoding="utf-8")
        self.assertNotIn("def alignment_unit", source)
        self.assertNotIn("class Window", source)

    def test_units(self) -> None:
        """La celda más pequeña posible se amplía a un cuadrado de la unidad: 0,5 → 1,
        1 → 1, 1,5 → 3, 2,5 → 5, 4,5 → 9, 5 → 5 (y los demás pasos)."""
        for step, unit in UNITS.items():
            with self.subTest(step=step):
                result = grid.aligned_grid(georef.Window(0.1, 0.1, 0.2, 0.2), step)
                extent = result.extent
                self.assertEqual(
                    (extent.xmin, extent.ymin, extent.xmax, extent.ymax),
                    (0.0, 0.0, float(unit), float(unit)),
                )
                self.assertEqual(result.ncols, round(unit / step))
                self.assertEqual(result.nrows, round(unit / step))

    def test_aligned_outwards(self) -> None:
        """Cada borde es múltiplo de la unidad, contiene la extensión pedida y no se
        aleja de ella una unidad entera; ``ncols``·paso y ``nrows``·paso dan exactos el
        ancho y el alto; el paso de las celdas es el del proyecto."""
        for window in _windows():
            for step, unit in UNITS.items():
                with self.subTest(window=window, step=step):
                    result = grid.aligned_grid(window, step)
                    extent = result.extent
                    self.assertEqual((result.dx, result.dy), (step, step))
                    for edge in (extent.xmin, extent.ymin, extent.xmax, extent.ymax):
                        self.assertEqual(math.fmod(edge, unit), 0.0)
                    self.assertLessEqual(extent.xmin, window.xmin)
                    self.assertLessEqual(extent.ymin, window.ymin)
                    self.assertGreaterEqual(extent.xmax, window.xmax)
                    self.assertGreaterEqual(extent.ymax, window.ymax)
                    self.assertGreater(extent.xmin, window.xmin - unit)
                    self.assertGreater(extent.ymin, window.ymin - unit)
                    self.assertLess(extent.xmax, window.xmax + unit)
                    self.assertLess(extent.ymax, window.ymax + unit)
                    self.assertEqual(Fraction(result.ncols) * Fraction(step),
                                     Fraction(extent.xmax) - Fraction(extent.xmin))
                    self.assertEqual(Fraction(result.nrows) * Fraction(step),
                                     Fraction(extent.ymax) - Fraction(extent.ymin))
                    # La misma ventana que alinea la 002 (RF-002-24): celda a celda.
                    self.assertEqual(extent, georef.align_window(window, step))

    def test_example(self) -> None:
        """Un caso escrito a mano: paso 1,5 m (unidad 3 m)."""
        result = grid.aligned_grid(
            georef.Window(700000.3, 4399990.7, 700010.2, 4400003.1), 1.5
        )
        self.assertEqual(
            (result.west, result.north, result.dx, result.dy, result.ncols, result.nrows),
            (699999.0, 4400004.0, 1.5, 1.5, 8, 10),
        )

    def test_aligned_window_is_kept(self) -> None:
        """Una extensión ya alineada no se amplía más."""
        window = georef.Window(699993.0, 4399989.0, 700011.0, 4400010.0)
        for step in (0.5, 1.0, 1.5, 3.0):  # unidades 1, 1, 3, 3
            with self.subTest(step=step):
                self.assertEqual(grid.aligned_grid(window, step).extent, window)

    def test_project_grid(self) -> None:
        """La ventana del proyecto ya viene alineada (RF-002-24): la rejilla la cubre
        exacta."""
        for window in _windows():
            for step in UNITS:
                with self.subTest(window=window, step=step):
                    aligned = georef.align_window(window, step)
                    result = grid.project_grid(aligned, step)
                    self.assertEqual(result.extent, aligned)
                    self.assertTrue(
                        result.same_geometry(grid.aligned_grid(window, step))
                    )

    def test_project_grid_rejects_unaligned_window(self) -> None:
        """Una ventana sin alinear no da una rejilla del proyecto: ``gis.window_not_aligned``
        con el borde y su valor."""
        cases = (
            (georef.Window(700000.5, 4399990.0, 700010.0, 4400003.0), 1.0, "xmin",
             700000.5),
            (georef.Window(699999.0, 4399989.0, 700011.0, 4400005.0), 1.5, "ymax",
             4400005.0),
            (georef.Window(0.0, 0.0, 7.5, 10.0), 2.5, "xmax", 7.5),
        )
        for window, step, edge, value in cases:
            with self.subTest(window=window, step=step):
                with self.assertRaises(messages.GisError) as caught:
                    grid.project_grid(window, step)
                error = caught.exception
                self.assertEqual(error.code, "gis.window_not_aligned")
                self.assertEqual((error.field, error.value), (edge, value))
                self.assertEqual(error.values["unit"], georef.alignment_unit(step))


class CellAreaTest(unittest.TestCase):
    """RF-006-02: área de celda exacta, nunca nominal."""

    def test_project_cell_area_is_exact(self) -> None:
        """Rejilla del proyecto: el cuadrado exacto del paso (sin redondeo)."""
        window = georef.Window(700000.3, 4399990.7, 700010.2, 4400003.1)
        for step in UNITS:
            with self.subTest(step=step):
                area = grid.project_grid(georef.align_window(window, step), step).cell_area
                self.assertEqual(Fraction(area), Fraction(step) ** 2)
                self.assertEqual(area, step * step)

    def test_imported_cell_area_b24(self) -> None:
        """Rejilla importada de 1,000294 × 1,000302 m (Silvestre, B24,
        ``test_B24_area_real_celda``): área = |dx·dy| = 1,0005967 m², no 1 m²; en un
        prisma de 10 m de alto sobre 10⁶ celdas, 10 005 966,77 m³ (plan §5.4 A2)."""
        imported = grid.Grid(700000.0, 4400048.0, B24_DX, B24_DY, 1000, 1000)
        self.assertEqual(imported.cell_area, abs(B24_DX * B24_DY))
        self.assertNotEqual(imported.cell_area, 1.0)
        self.assertAlmostEqual(imported.cell_area, 1.000596677, delta=1e-9)
        self.assertAlmostEqual(10.0 * 1e6 * imported.cell_area, 10_005_966.77, delta=0.005)
        # El sesgo de B24: con el área nominal de 1 m², un −0,06 % en todos los volúmenes.
        self.assertAlmostEqual((1.0 - imported.cell_area) / imported.cell_area, -0.000596,
                               delta=0.000001)


class GridTest(unittest.TestCase):
    """La geometría de una rejilla (base de RF-006-01 a RF-006-03)."""

    def setUp(self) -> None:
        self.grid = grid.Grid(700000.0, 4400048.0, 0.5, 0.5, 6, 4)

    def test_transform_and_extent(self) -> None:
        """``transform`` = (dx, 0, oeste, 0, −dy, norte); ``extent``, absoluta."""
        self.assertEqual(self.grid.transform, (0.5, 0.0, 700000.0, 0.0, -0.5, 4400048.0))
        self.assertEqual(self.grid.extent,
                         georef.Window(700000.0, 4400046.0, 700003.0, 4400048.0))
        self.assertIsInstance(self.grid.extent, georef.Window)
        self.assertEqual(self.grid.shape, (4, 6))
        imported = grid.Grid(700000.0, 4400048.0, B24_DX, B24_DY, 3, 2)
        self.assertEqual(imported.extent.xmax, 700000.0 + 3 * B24_DX)
        self.assertEqual(imported.extent.ymin, 4400048.0 - 2 * B24_DY)

    def test_centers(self) -> None:
        """Centros de celda absolutos en float64, filas de norte a sur; ``rows`` elige
        una banda de filas."""
        x, y = self.grid.centers()
        self.assertEqual(x.shape, (4, 6))
        self.assertEqual(y.shape, (4, 6))
        self.assertEqual(x.dtype, np.float64)
        self.assertEqual(y.dtype, np.float64)
        self.assertEqual(x[0].tolist(), [700000.25 + 0.5 * j for j in range(6)])
        self.assertEqual(y[:, 0].tolist(), [4400047.75 - 0.5 * i for i in range(4)])
        self.assertTrue(np.all(x == x[0]))
        self.assertTrue(np.all(y.T == y[:, 0]))
        band_x, band_y = self.grid.centers(slice(1, 3))
        self.assertEqual(band_x.shape, (2, 6))
        np.testing.assert_array_equal(band_x, x[1:3])
        np.testing.assert_array_equal(band_y, y[1:3])
        # En UTM no se pierde nada (float64): 4 400 047,75 exacto.
        self.assertEqual(float(y[0, 0]), 4400047.75)

    def test_same_geometry(self) -> None:
        """Misma geometría solo si todo coincide bit a bit (1 ulp de paso ya no)."""
        same = grid.Grid(700000.0, 4400048.0, 0.5, 0.5, 6, 4)
        self.assertTrue(self.grid.same_geometry(same))
        self.assertTrue(grid.Grid(-0.0, 0.0, 1.0, 1.0, 1, 1).same_geometry(
            grid.Grid(0.0, -0.0, 1.0, 1.0, 1, 1)))
        others = (
            grid.Grid(700000.5, 4400048.0, 0.5, 0.5, 6, 4),
            grid.Grid(700000.0, 4400047.0, 0.5, 0.5, 6, 4),
            grid.Grid(700000.0, 4400048.0, math.nextafter(0.5, 1.0), 0.5, 6, 4),
            grid.Grid(700000.0, 4400048.0, 0.5, 1.0, 6, 4),
            grid.Grid(700000.0, 4400048.0, 0.5, 0.5, 7, 4),
            grid.Grid(700000.0, 4400048.0, 0.5, 0.5, 6, 5),
        )
        for other in others:
            with self.subTest(other=other):
                self.assertFalse(self.grid.same_geometry(other))
        self.assertFalse(self.grid.same_geometry(self.grid.extent))  # type: ignore[arg-type]

    def test_geometry_mismatch(self) -> None:
        """Spec 011, T11 (RF-011-03; plan 011 §5.3.2): la comparación de ``gis.grid_mismatch``,
        pública y sin leer celdas: la primera diferencia (campo, valor de la segunda y detalle
        en español) de la rejilla bit a bit, el CRS o la referencia vertical; sin referencias
        verticales (una rejilla de espesores, plan 011 R7), solo la rejilla y el CRS."""
        catalog = georef.load_catalog()
        crs, other_crs = catalog.horizontal(25830), catalog.horizontal(25829)
        vertical, local = catalog.vertical(5782), catalog.local_vertical("NP-0 del plano 3")
        same = grid.Grid(700000.0, 4400048.0, 0.5, 0.5, 6, 4)
        self.assertIsNone(grid.geometry_mismatch(self.grid, same, crs, crs, vertical, vertical))
        cases = (
            (grid.Grid(700000.5, 4400048.0, 0.5, 0.5, 6, 4), crs, vertical,
             ("west", 700000.5, "oeste 700000 frente a 700000,5")),
            (grid.Grid(700000.0, 4400048.0, 1.0, 1.0, 6, 4), crs, vertical,
             ("dx", 1.0, "paso en X 0,5 frente a 1")),
            (grid.Grid(700000.0, 4400048.0, 0.5, 0.5, 6, 5), crs, vertical,
             ("nrows", 5, "filas 4 frente a 5")),
            (same, other_crs, vertical, ("crs", 25829, "CRS EPSG:25830 frente a EPSG:25829")),
            (same, crs, local, ("vertical", "Referencia local (NP-0 del plano 3)",
                                "referencia vertical EPSG:5782 frente a Referencia local "
                                "(NP-0 del plano 3)")),
        )
        for other, other_crs_ref, other_vertical, expected in cases:
            with self.subTest(expected=expected[0]):
                self.assertEqual(grid.geometry_mismatch(self.grid, other, crs, other_crs_ref,
                                                        vertical, other_vertical), expected)
        self.assertIsNone(grid.geometry_mismatch(self.grid, same, crs, crs, None, None))
        self.assertEqual(grid.geometry_mismatch(self.grid, same, crs, other_crs, None, None)[0],
                         "crs")

    def test_immutable_float64(self) -> None:
        """Inmutable; las coordenadas y los pasos, en float de Python (float64)."""
        made = grid.Grid(700000, 4400048, 1, 1, 2, 3)
        for name in ("west", "north", "dx", "dy"):
            self.assertIs(type(getattr(made, name)), float)
        for name in ("ncols", "nrows"):
            self.assertIs(type(getattr(made, name)), int)
        with self.assertRaises(AttributeError):
            made.west = 0.0  # type: ignore[misc]

    def test_invalid_geometry(self) -> None:
        """Una rejilla sin celdas, con un paso nulo, negativo o no finito, o con
        coordenadas no finitas es un error del programa (quien la lee la valida antes)."""
        bad = (
            (math.nan, 0.0, 1.0, 1.0, 1, 1),
            (0.0, math.inf, 1.0, 1.0, 1, 1),
            (0.0, 0.0, 0.0, 1.0, 1, 1),
            (0.0, 0.0, 1.0, -1.0, 1, 1),
            (0.0, 0.0, math.inf, 1.0, 1, 1),
            (0.0, 0.0, 1.0, 1.0, 0, 1),
            (0.0, 0.0, 1.0, 1.0, 1, -2),
        )
        for args in bad:
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    grid.Grid(*args)
        for args in ((True, 0.0, 1.0, 1.0, 1, 1), ("0", 0.0, 1.0, 1.0, 1, 1),
                     (0.0, 0.0, 1.0, 1.0, 1.0, 1), (0.0, 0.0, 1.0, 1.0, 1, True)):
            with self.subTest(args=args):
                with self.assertRaises(TypeError):
                    grid.Grid(*args)

    def test_package_reexports(self) -> None:
        """``gis`` reexporta la API de la rejilla (plan §5.1)."""
        for name in ("Grid", "validate_step", "aligned_grid", "project_grid"):
            with self.subTest(name=name):
                self.assertIn(name, gis.__all__)
                self.assertIs(getattr(gis, name), getattr(grid, name))


if __name__ == "__main__":
    unittest.main()
