# SPDX-License-Identifier: GPL-3.0-or-later
"""El plano de base robusto y su límite de inclinación (spec 016, T06; RF-016-02, RF-016-04, RF-016-05, RF-016-07;
CE-016-02; plan 016 A2, §5.2.2, §7.1).

:mod:`design.stockpiles` ajusta el plano de base de un acopio al terreno de su corona (el anillo de ``crown_inner_m`` a
``crown_outer_m`` m alrededor de su huella, con el disco exacto de A1) por mínimos cuadrados, descartando las celdas
cuyo residuo se aparta de la mediana más que el residuo máximo, y lo limita a la inclinación máxima conservando su
azimut y apoyando el término independiente en el cuantil de apoyo. Se prueba con:

- **cuentas a mano**: el cuantil de un ejemplo de diez celdas (2,4 m) y el plano limitado a 22,5°;
- **implementaciones independientes** (``tests.support.design_oracles``: bucles de Python sin numpy, mínimos cuadrados
  en racionales exactos): ``hand_plane``, ``hand_cell_slope_deg`` y ``hand_crown``, que a su vez se prueban aquí con
  un ejemplo que se sabe;
- la **cantera de la 016** (``tests.support.stockpile_data``): un montón de forma conocida sobre un plano de 3° o de
  8° con ocho celdas atípicas en la corona (CE-016-02), con celdas de 1 m y de 2 m.
"""

from __future__ import annotations

import math
import time
import unittest

import numpy as np

from tests.support import design_oracles as oracles
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender

gis = import_geoblender("gis")
stockpiles = import_geoblender("design.stockpiles")

THRESHOLD_M = 0.3
"""El umbral de huella de la 011 (``res.anthropic_presence_m``, D-17): con él se forma la huella de los casos."""
# Los umbrales de D-3 (ADOPTADO «sin confirmar»; la inclinación máxima y el cuantil, HIPÓTESIS): valores de ENTRADA de
# estas pruebas, no los que la implementación da por defecto (no da ninguno: P-6 del plan, «sin cifras a mano»).
D3 = {"crown_inner_m": 1.0, "crown_outer_m": 3.0, "crown_slope_deg": 12.0, "crown_flat_min_m2": 10.0,
      "max_residual_m": 1.0, "fit_rounds": 4, "tilt_max_deg": 4.0, "support_quantile": 0.6}


def params_of(**changes: float) -> object:
    """Los parámetros de A2 con los umbrales de D-3 y los cambios de ``changes``."""
    return stockpiles.PlaneParams(**{**D3, **changes})


def fit_kwargs(**changes: float) -> dict[str, float]:
    """Lo que :func:`stockpiles.fit_plane` pide de los parámetros de D-3 (con ``changes``)."""
    merged = {**D3, **changes}
    return {"rounds": merged["fit_rounds"], "max_residual_m": merged["max_residual_m"],
            "tilt_max_deg": merged["tilt_max_deg"], "quantile": merged["support_quantile"]}


def cells_of(grid: object, z: np.ndarray, mask: np.ndarray) -> list[tuple[float, float, float]]:
    """``(x, y, z)`` de las celdas de ``mask`` en el orden de lectura (fila 0 al norte), para el oráculo."""
    x, y = grid.centers()
    return [(float(x[r, c]), float(y[r, c]), float(z[r, c])) for r, c in np.argwhere(mask)]


def worst_error(plane: object, case: object, where: np.ndarray | None = None) -> float:
    """El mayor ``|plano − plano sintético|`` (m) en ``where`` (por defecto, toda la ventana)."""
    error = np.abs(plane.values(case.grid) - case.base)
    return float(error.max() if where is None else error[where].max())


def window(size_m: float = 30.0, step_m: float = 1.0) -> object:
    """Una ventana pequeña de los casos (de (0, 0) a (``size_m``, ``size_m``) locales)."""
    return sdata.window_grid(step_m, size_m)


class CrownTest(unittest.TestCase):
    """La corona: la huella dilatada ``crown_outer_m`` menos la dilatada ``crown_inner_m`` (RF-016-02)."""

    def blob(self, rows: int = 21, cols: int = 25) -> np.ndarray:
        found = np.zeros((rows, cols), dtype=bool)
        found[6:10, 8:15] = True
        found[9:13, 12:16] = True
        found[3, 20] = True
        return found

    def test_matches_the_brute_force_hand_crown(self) -> None:
        """RF-016-02: la corona es igual, celda a celda, a la de la fuerza bruta (cada celda contra cada celda de la
        huella, en metros), con celdas de 0,5, 1 y 2 m y con la separación interior en cero."""
        footprint = self.blob()
        for cell, inner, outer in ((1.0, 1.0, 3.0), (2.0, 1.0, 3.0), (0.5, 1.0, 3.0), (1.0, 0.0, 2.0),
                                   (1.0, 1.5, 4.0), (2.0, 2.0, 6.0)):
            with self.subTest(cell=cell, inner=inner, outer=outer):
                found = stockpiles.crown_of(footprint, cell, inner_m=inner, outer_m=outer)
                np.testing.assert_array_equal(found, oracles.hand_crown(footprint, cell, inner, outer))
                self.assertFalse((found & footprint).any(), "la corona no toca la huella")

    def test_a_single_cell_has_a_ring_counted_by_hand(self) -> None:
        """Con celdas de 1 m, el disco de 3 m son 29 celdas y el de 1 m, 5: el anillo de una celda son 24."""
        footprint = np.zeros((11, 11), dtype=bool)
        footprint[5, 5] = True
        found = stockpiles.crown_of(footprint, 1.0, inner_m=1.0, outer_m=3.0)
        self.assertEqual(int(found.sum()), 29 - 5)
        self.assertFalse(found[5, 5] or found[5, 6] or found[4, 5])
        self.assertTrue(found[5, 8] and found[3, 4] and not found[5, 9] and not found[2, 2])

    def test_no_footprint_or_an_inverted_ring_has_no_cells(self) -> None:
        """Sin huella, o con la separación interior no menor que la exterior, no hay corona (A2 rechaza el acopio)."""
        self.assertFalse(stockpiles.crown_of(np.zeros((9, 9), bool), 1.0, inner_m=1.0, outer_m=3.0).any())
        footprint = np.zeros((9, 9), dtype=bool)
        footprint[4, 4] = True
        self.assertFalse(stockpiles.crown_of(footprint, 1.0, inner_m=3.0, outer_m=3.0).any())
        self.assertFalse(stockpiles.crown_of(footprint, 1.0, inner_m=4.0, outer_m=3.0).any())

    def test_inputs_are_not_modified_and_the_mask_is_a_mask(self) -> None:
        """Principio 7: la huella no se modifica; una huella que no es booleana, de 2 dimensiones, es un error."""
        footprint = self.blob()
        before = footprint.copy()
        stockpiles.crown_of(footprint, 1.0, inner_m=1.0, outer_m=3.0)
        np.testing.assert_array_equal(footprint, before)
        with self.assertRaises(ValueError):
            stockpiles.crown_of(footprint.astype(np.int8), 1.0, inner_m=1.0, outer_m=3.0)
        with self.assertRaises(ValueError):
            stockpiles.crown_of(footprint[0], 1.0, inner_m=1.0, outer_m=3.0)


class CellSlopeTest(unittest.TestCase):
    """La pendiente de la celda (°): diferencias centradas, de un lado en el borde (RF-016-02)."""

    def test_matches_the_hand_slope_with_a_hole(self) -> None:
        """Igual al bucle de ``hand_cell_slope_deg`` (centrada y, en el borde, de un lado), con pasos distintos en X y
        en Y y una celda sin dato: ella y las que la usan salen NaN y las demás, no."""
        rng = np.random.default_rng(20_261_118)
        z = np.cumsum(rng.normal(0.0, 0.4, size=(9, 11)), axis=1) + np.cumsum(rng.normal(0.0, 0.4, (9, 11)), axis=0)
        z[4, 5] = np.nan
        found = stockpiles.cell_slope_deg(z, 2.0, 0.5)
        by_hand = oracles.hand_cell_slope_deg(z.tolist(), 2.0, 0.5)
        np.testing.assert_array_equal(np.isnan(found), np.isnan(by_hand))
        np.testing.assert_allclose(found, by_hand, rtol=1e-12, atol=1e-12, equal_nan=True)
        self.assertEqual(int(np.isnan(found).sum()), 5)  # la celda y sus cuatro vecinas (diferencias centradas)

    def test_a_plane_has_its_own_slope_everywhere(self) -> None:
        """Un plano de 3° tiene 3° en toda la ventana, también en el borde (≤ 10⁻⁹ °); el de 0°, 0°."""
        grid = window(120.0)
        found = stockpiles.cell_slope_deg(sdata.plane(3.0).values(grid), 1.0, 1.0)
        self.assertLess(float(np.abs(found - 3.0).max()), 1e-9)
        self.assertEqual(float(stockpiles.cell_slope_deg(sdata.plane(0.0).values(grid), 1.0, 1.0).max()), 0.0)

    def test_the_slope_does_not_depend_on_the_orientation_of_the_rows(self) -> None:
        """Una rejilla con las filas al revés da la misma pendiente al revés (no hay signo que se confunda)."""
        z = sdata.plane(8.0).values(window(60.0))
        np.testing.assert_allclose(stockpiles.cell_slope_deg(z[::-1], 1.0, 1.0),
                                   stockpiles.cell_slope_deg(z, 1.0, 1.0)[::-1], atol=1e-12)

    def test_refuses_what_has_no_slope(self) -> None:
        """Una rejilla de una fila o de una columna, un paso nulo o negativo o de 3 dimensiones: ``ValueError``."""
        with self.assertRaises(ValueError):
            stockpiles.cell_slope_deg(np.zeros((1, 5)), 1.0, 1.0)
        with self.assertRaises(ValueError):
            stockpiles.cell_slope_deg(np.zeros((5, 1)), 1.0, 1.0)
        with self.assertRaises(ValueError):
            stockpiles.cell_slope_deg(np.zeros((5, 5, 2)), 1.0, 1.0)
        for step in (0.0, -1.0, math.nan, math.inf):
            with self.subTest(step=step), self.assertRaises(ValueError):
                stockpiles.cell_slope_deg(np.zeros((5, 5)), step, 1.0)


class OracleTest(unittest.TestCase):
    """Los oráculos de A2 dan lo que se sabe antes de usarlos de árbitro."""

    def test_hand_plane_recovers_an_exact_plane_and_drops_the_outlier(self) -> None:
        """Veinticinco celdas en un plano z = 10 + 0,1·x − 0,2·y con una atípica de +5 m en el centro (la media de
        las celdas: no inclina el ajuste, solo lo sube 0,2 m): el residuo de las demás es −0,2 y el de la atípica, 4,8;
        con la mediana en −0,2 se descarta la atípica y el plano sale exacto."""
        cells = [(float(j), float(i), 10.0 + 0.1 * j - 0.2 * i + (5.0 if (i, j) == (2, 2) else 0.0))
                 for i in range(5) for j in range(5)]
        found = oracles.hand_plane(cells, rounds=4, max_residual_m=1.0, tilt_max_deg=45.0, quantile=0.6)
        self.assertEqual(found.kept, tuple(index != 12 for index in range(25)))
        self.assertAlmostEqual(found.east_slope, 0.1, delta=1e-14)
        self.assertAlmostEqual(found.north_slope, -0.2, delta=1e-14)
        self.assertAlmostEqual(found.at(0.0, 0.0), 10.0, delta=1e-13)
        self.assertFalse(found.limited)

    def test_hand_plane_support_level_by_hand(self) -> None:
        """Diez celdas con z = x (x de 0 a 4 en dos filas): inclinación 45°; limitada a 0°, el plano es llano y su
        nivel el cuantil 0,6 de [0 0 1 1 2 2 3 3 4 4], de índice 0,6·9 = 5,4: 2 + 0,4·(3 − 2) = 2,4."""
        cells = [(float(j), float(i), float(j)) for i in range(2) for j in range(5)]
        found = oracles.hand_plane(cells, rounds=4, max_residual_m=1.0, tilt_max_deg=0.0, quantile=0.6)
        self.assertTrue(found.limited)
        self.assertAlmostEqual(found.fitted_tilt_deg, 45.0, delta=1e-12)
        self.assertEqual((found.east_slope, found.north_slope), (0.0, 0.0))
        self.assertAlmostEqual(found.pivot_z, 2.4, delta=1e-12)

    def test_hand_plane_refuses_what_does_not_make_a_plane(self) -> None:
        """Dos celdas, o tres en una recta, no determinan un plano."""
        with self.assertRaises(ValueError):
            oracles.hand_plane([(0.0, 0.0, 1.0), (1.0, 0.0, 2.0)], rounds=1, max_residual_m=1.0,
                               tilt_max_deg=4.0, quantile=0.6)
        with self.assertRaises(ValueError):
            oracles.hand_plane([(0.0, 0.0, 1.0), (1.0, 1.0, 2.0), (2.0, 2.0, 3.0)], rounds=1,
                               max_residual_m=1.0, tilt_max_deg=4.0, quantile=0.6)


class HandCalculationTest(unittest.TestCase):
    """Los dos ejemplos de cuenta a mano, con la implementación (``fit_plane``) y no solo con el oráculo."""

    def ramp(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        x = np.array([[0.0, 1.0, 2.0, 3.0, 4.0]] * 2) + 700_000.0
        y = np.array([[0.0] * 5, [1.0] * 5]) + 4_400_000.0
        return x - 700_000.0, x, y, np.ones((2, 5), dtype=bool)

    def test_support_level_is_the_quantile_of_the_residuals(self) -> None:
        """Con z = x y la inclinación limitada a 0°, el plano es llano en el cuantil 0,6 de los residuos, 2,4 m (el
        ejemplo del oráculo, hecho a mano); con la inclinación de 45° y el azimut al este (90°) del ajuste."""
        z, x, y, crown = self.ramp()
        found = stockpiles.fit_plane(z, crown, x, y, rounds=4, max_residual_m=1.0, tilt_max_deg=0.0, quantile=0.6)
        self.assertTrue(found.limited)
        self.assertAlmostEqual(found.fitted_tilt_deg, 45.0, delta=1e-9)
        self.assertAlmostEqual(found.azimuth_deg, 90.0, delta=1e-9)
        self.assertEqual((found.east_slope, found.north_slope, found.tilt_deg), (0.0, 0.0, 0.0))
        self.assertAlmostEqual(found.pivot_z, 2.4, delta=1e-12)
        self.assertAlmostEqual(float(found.at(x[0, 0], y[1, 3])), 2.4, delta=1e-12)

    def test_a_limited_tilt_keeps_the_azimuth_and_moves_the_level(self) -> None:
        """Limitada a 22,5° (tan = √2 − 1 = t), el nivel en el pivote (2; 0,5) es el cuantil 0,6 de (1 − t)·x + 2t,
        o sea (1 − t)·2,4 + 2t; la pendiente al este es t y al norte 0; el azimut sigue al este."""
        z, x, y, crown = self.ramp()
        found = stockpiles.fit_plane(z, crown, x, y, rounds=4, max_residual_m=1.0, tilt_max_deg=22.5, quantile=0.6)
        t = math.tan(math.radians(22.5))
        self.assertAlmostEqual(found.east_slope, t, delta=1e-12)
        self.assertAlmostEqual(found.north_slope, 0.0, delta=1e-12)
        self.assertAlmostEqual(found.tilt_deg, 22.5, delta=1e-9)
        self.assertAlmostEqual(found.azimuth_deg, 90.0, delta=1e-9)
        self.assertAlmostEqual(found.pivot_z, (1.0 - t) * 2.4 + 2.0 * t, delta=1e-12)
        self.assertAlmostEqual(float(found.at(700_002.0, 4_400_000.5)), found.pivot_z, delta=1e-12)  # el pivote
        self.assertAlmostEqual(float(found.at(700_000.0, 4_400_000.0)), found.pivot_z - 2.0 * t, delta=1e-12)
        by_hand = oracles.hand_plane(cells_of_ramp(x, y, z), rounds=4, max_residual_m=1.0, tilt_max_deg=22.5,
                                     quantile=0.6)
        self.assertAlmostEqual(found.pivot_z, by_hand.pivot_z, delta=1e-12)
        self.assertAlmostEqual(found.east_slope, by_hand.east_slope, delta=1e-12)

    def test_the_quantile_ends_are_the_lowest_and_the_highest_residual(self) -> None:
        """Con el cuantil 0 el plano limitado pasa por la celda más baja de la corona y con el 1, por la más alta (en
        la cuenta a mano de los residuos); el de en medio, entre los dos."""
        z, x, y, crown = self.ramp()
        low = stockpiles.fit_plane(z, crown, x, y, rounds=4, max_residual_m=1.0, tilt_max_deg=0.0, quantile=0.0)
        high = stockpiles.fit_plane(z, crown, x, y, rounds=4, max_residual_m=1.0, tilt_max_deg=0.0, quantile=1.0)
        self.assertAlmostEqual(low.pivot_z, 0.0, delta=1e-12)
        self.assertAlmostEqual(high.pivot_z, 4.0, delta=1e-12)


def cells_of_ramp(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> list[tuple[float, float, float]]:
    """Las diez celdas de la rampa en el orden de lectura, para el oráculo."""
    return [(float(x[r, c]), float(y[r, c]), float(z[r, c])) for r in range(2) for c in range(5)]


class PlaneRecoveryTest(unittest.TestCase):
    """CE-016-02, RF-016-02: el plano de 3° con celdas atípicas en la corona se recupera a ≤ 10⁻⁶ m."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = {(shape, step): sdata.mound_case(shape, 3.0, step_m=step)
                     for shape in ("cone", "pyramid") for step in (1.0, 2.0)}

    def mark(self, case: object) -> np.ndarray:
        return sdata.in_box(case.mark_box, case.grid)

    def test_the_mark_crown_recovers_the_plane_with_the_outliers_in_it(self) -> None:
        """Corona de la marca (huella = la marca): con los atípicos de +3 y −2,5 m dentro, el plano sale a ≤ 10⁻⁶ m del
        sintético en **toda la ventana** (en la práctica, a 10⁻¹¹), con el azimut y la inclinación del plano de los
        casos; sin avisos (3° < la inclinación máxima de 4°) y con celdas de 1 y de 2 m, de cono y de pirámide."""
        for (shape, step), case in self.cases.items():
            with self.subTest(shape=shape, step=step):
                found = stockpiles.base_plane(case.terrain, self.mark(case), case.grid, params_of())
                self.assertLess(worst_error(found, case), 1e-6)
                self.assertAlmostEqual(found.tilt_deg, 3.0, delta=1e-8)
                self.assertAlmostEqual(found.azimuth_deg, sdata.AZIMUTH_DEG, delta=1e-8)
                self.assertFalse(found.limited)
                self.assertEqual(found.notes, ())
                self.assertFalse((found.kept & case.outliers).any(), "una atípica entró en el ajuste")
                full = stockpiles.crown_of(self.mark(case), step, inner_m=1.0, outer_m=3.0)
                self.assertGreater(int((full & case.outliers).sum()), 0, "el caso no tiene atípicas en la corona")

    def test_the_footprint_crown_of_the_cone_recovers_the_plane(self) -> None:
        """Corona de la huella del cono (las celdas más altas que el umbral de 0,3 m): el plano sale a ≤ 10⁻⁶ m en toda
        la huella, con las cuatro atípicas de esa corona fuera del ajuste."""
        for step in (1.0, 2.0):
            case = self.cases["cone", step]
            footprint = case.height > THRESHOLD_M
            with self.subTest(step=step):
                found = stockpiles.base_plane(case.terrain, footprint, case.grid, params_of())
                self.assertLess(worst_error(found, case, footprint), 1e-6)
                self.assertFalse((found.kept & case.outliers).any())

    def test_the_robust_rounds_are_what_drops_the_outliers(self) -> None:
        """Con todas las celdas «llanas» (pendiente de corona de 89°), solo el descarte por el residuo quita las
        atípicas: kept = corona − atípicas, y el plano sale a ≤ 10⁻⁶ m; con un residuo máximo que no descarta nada, el
        ajuste se aparta del plano más de 10⁻³ m (las atípicas pesan)."""
        case = self.cases["cone", 1.0]
        footprint = self.mark(case)
        robust = stockpiles.base_plane(case.terrain, footprint, case.grid, params_of(crown_slope_deg=89.0))
        crown = stockpiles.crown_of(footprint, 1.0, inner_m=1.0, outer_m=3.0)
        outliers = int((case.outliers & crown).sum())
        self.assertGreater(outliers, 0)
        self.assertEqual(int(robust.kept.sum()), int(crown.sum()) - outliers)
        self.assertLess(worst_error(robust, case), 1e-6)
        loose = stockpiles.base_plane(case.terrain, footprint, case.grid,
                                      params_of(crown_slope_deg=89.0, max_residual_m=1000.0))
        self.assertEqual(int(loose.kept.sum()), int(crown.sum()))
        self.assertGreater(worst_error(loose, case), 1e-3)

    def test_equal_to_the_independent_hand_calculation(self) -> None:
        """El plano es el del oráculo (ecuaciones normales en racionales exactos, mediana y descarte a mano) a ≤ 10⁻⁹
        relativo en cada celda de la ventana, con las mismas celdas descartadas, con y sin las atípicas en el ajuste."""
        case = self.cases["cone", 1.0]
        footprint = self.mark(case)
        for slope in (12.0, 89.0):
            with self.subTest(crown_slope_deg=slope):
                found = stockpiles.base_plane(case.terrain, footprint, case.grid, params_of(crown_slope_deg=slope))
                slopes = oracles.hand_cell_slope_deg(case.terrain.tolist(), 1.0, 1.0)
                crown = stockpiles.crown_of(footprint, 1.0, inner_m=1.0, outer_m=3.0)  # probada aparte (CrownTest)
                selected = crown & (slopes < slope)
                by_hand = oracles.hand_plane(cells_of(case.grid, case.terrain, selected), rounds=4,
                                             max_residual_m=1.0, tilt_max_deg=4.0, quantile=0.6)
                np.testing.assert_array_equal(found.crown, selected)
                self.assertEqual(tuple(found.kept[selected]), by_hand.kept)
                x, y = case.grid.centers()
                expected = np.array([[by_hand.at(float(x[r, c]), float(y[r, c])) for c in range(case.grid.ncols)]
                                     for r in range(0, case.grid.nrows, 7)])
                np.testing.assert_allclose(found.at(x, y)[::7], expected, rtol=1e-9, atol=0.0)

    def test_the_inputs_are_not_modified(self) -> None:
        """Principio 7: ni la superficie ni la huella cambian."""
        case = self.cases["cone", 1.0]
        z, footprint = case.terrain.copy(), self.mark(case)
        before = footprint.copy()
        stockpiles.base_plane(case.terrain, footprint, case.grid, params_of())
        np.testing.assert_array_equal(case.terrain, z)
        np.testing.assert_array_equal(footprint, before)

    def test_one_call_is_far_below_the_step_budget(self) -> None:
        """RNF-016-03: calcular el plano de una marca de la ventana de los casos (120 × 120 celdas) cabe en un paso de
        la interfaz (≤ 0,2 s por llamada; medido, unos milisegundos)."""
        case = self.cases["cone", 1.0]
        footprint = self.mark(case)
        stockpiles.base_plane(case.terrain, footprint, case.grid, params_of())
        started = time.perf_counter()
        stockpiles.base_plane(case.terrain, footprint, case.grid, params_of())
        self.assertLess(time.perf_counter() - started, 0.2)


class TiltLimitTest(unittest.TestCase):
    """RF-016-07: el plano de 8° con la inclinación máxima de 4°."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = sdata.mound_case("cone", 8.0)
        cls.footprint = sdata.in_box(cls.case.mark_box, cls.case.grid)
        cls.found = stockpiles.base_plane(cls.case.terrain, cls.footprint, cls.case.grid, params_of())

    def test_the_plane_is_limited_keeping_the_azimuth(self) -> None:
        """El ajuste es el de 8° (≤ 10⁻⁹ °); el plano queda en 4° con el mismo azimut (30°, ≤ 10⁻⁹ °)."""
        found = self.found
        self.assertTrue(found.limited)
        self.assertAlmostEqual(found.fitted_tilt_deg, 8.0, delta=1e-9)
        self.assertAlmostEqual(found.tilt_deg, 4.0, delta=1e-9)
        self.assertAlmostEqual(found.azimuth_deg, sdata.AZIMUTH_DEG, delta=1e-9)
        self.assertAlmostEqual(math.degrees(math.atan2(found.east_slope, found.north_slope)), 30.0, delta=1e-9)
        self.assertAlmostEqual(found.slope_percent, 100.0 * math.tan(math.radians(4.0)), delta=1e-9)

    def test_the_note_carries_both_tilts_the_limit_and_the_quantile(self) -> None:
        """El aviso es ``des.stockpile_tilt_limited`` con la inclinación del ajuste, la limitada y el cuantil de apoyo;
        con la marca y el lugar se lee en español con las dos inclinaciones (RF-016-07: «NO DEBERÁ dar el acopio sin
        esa nota»)."""
        self.assertEqual([note.code for note in self.found.notes], ["des.stockpile_tilt_limited"])
        values = self.found.notes[0].values
        self.assertAlmostEqual(values["fitted"], 8.0, delta=1e-9)
        self.assertEqual((values["limit"], values["quantile"]), (4.0, 0.6))
        notice = self.found.notes[0].notice("Acopio 7", 699_760.0, 4_399_760.0)
        self.assertEqual((notice.code, notice.severity), ("des.stockpile_tilt_limited", "warning"))
        text = notice.text("es")
        for part in ("«Acopio 7»", "8,0°", "4,0°", "0,6"):
            self.assertIn(part, text)

    def test_the_plane_is_the_hand_calculation(self) -> None:
        """El plano limitado es el del oráculo (racionales exactos; el nivel, el cuantil 0,6 ordenando los residuos) a
        ≤ 10⁻⁹ relativo: su nivel, sus dos pendientes y su valor en cada celda."""
        case, found = self.case, self.found
        slopes = oracles.hand_cell_slope_deg(case.terrain.tolist(), 1.0, 1.0)
        crown = stockpiles.crown_of(self.footprint, 1.0, inner_m=1.0, outer_m=3.0)  # probada aparte con la fuerza bruta
        selected = crown & (slopes < 12.0)
        by_hand = oracles.hand_plane(cells_of(case.grid, case.terrain, selected), rounds=4, max_residual_m=1.0,
                                     tilt_max_deg=4.0, quantile=0.6)
        self.assertTrue(by_hand.limited)
        self.assertEqual(tuple(found.kept[selected]), by_hand.kept)
        self.assertAlmostEqual(found.east_slope / by_hand.east_slope, 1.0, delta=1e-9)
        self.assertAlmostEqual(found.north_slope / by_hand.north_slope, 1.0, delta=1e-9)
        x, y = case.grid.centers()
        expected = np.array([[by_hand.at(float(x[r, c]), float(y[r, c])) for c in range(0, 120, 9)]
                             for r in range(0, 120, 9)])
        np.testing.assert_allclose(found.at(x, y)[::9, ::9], expected, rtol=1e-9, atol=0.0)

    def test_the_level_is_the_quantile_of_the_crown(self) -> None:
        """Una cuenta que no usa ninguna de las dos implementaciones: el plano limitado deja bajo él la fracción
        ``support_quantile`` de las celdas del ajuste (con ±1 celda), y con el cuantil 0 pasa por la más baja y con el
        1, por la más alta."""
        case = self.case
        kept = self.found.kept
        x, y = case.grid.centers()
        below = float((case.terrain[kept] <= self.found.at(x, y)[kept] + 1e-12).mean())
        self.assertAlmostEqual(below, 0.6, delta=2.0 / kept.sum())
        for quantile, pick in ((0.0, np.min), (1.0, np.max)):
            plane = stockpiles.base_plane(case.terrain, self.footprint, case.grid,
                                          params_of(support_quantile=quantile))
            rest = case.terrain[kept] - plane.at(x, y)[kept]
            self.assertAlmostEqual(float(pick(rest)), 0.0, delta=1e-9)

    def test_a_plane_under_the_limit_is_not_touched_and_has_no_note(self) -> None:
        """RF-016-07 solo cuando pasa de la inclinación máxima: con 3° y un límite de 4° no hay nota, y con un límite
        de 8,5° tampoco el de 8°."""
        case = self.case
        found = stockpiles.base_plane(case.terrain, self.footprint, case.grid, params_of(tilt_max_deg=8.5))
        self.assertFalse(found.limited)
        self.assertEqual(found.notes, ())
        self.assertAlmostEqual(found.tilt_deg, 8.0, delta=1e-9)
        self.assertLess(worst_error(found, case), 1e-6)

    def test_a_limit_of_zero_gives_a_level_plane_that_remembers_its_azimuth(self) -> None:
        """Con la inclinación máxima 0° el plano es horizontal (sus dos pendientes, 0), conserva el azimut del ajuste
        (30°) y su nivel es el cuantil de los residuos."""
        found = stockpiles.base_plane(self.case.terrain, self.footprint, self.case.grid,
                                      params_of(tilt_max_deg=0.0))
        self.assertTrue(found.limited)
        self.assertEqual((found.east_slope, found.north_slope, found.tilt_deg), (0.0, 0.0, 0.0))
        self.assertAlmostEqual(found.azimuth_deg, sdata.AZIMUTH_DEG, delta=1e-9)


class FlatCrownTest(unittest.TestCase):
    """RF-016-02 y RF-016-05: las celdas de la corona menos empinadas que la pendiente de corona."""

    def seam_case(self, step_m: float = 1.0) -> tuple[object, np.ndarray, np.ndarray, np.ndarray]:
        """Una ventana de 120 m con un plano de 3° al oeste de x = 60 y uno de 20° al este (con un escalón entre los
        dos), y una huella cuadrada de 60 m en el centro (con celdas de ``step_m`` m)."""
        grid = window(120.0, step_m)
        x, _ = sdata.local_centers(grid)
        z = np.where(x < 60.0, sdata.plane(3.0).values(grid), sdata.plane(20.0, z_pivot=140.0).values(grid))
        return grid, z, sdata.in_box((30.0, 30.0, 90.0, 90.0), grid), x

    def test_only_the_flat_cells_are_used_when_they_sum_the_minimum_area(self) -> None:
        """Con la mitad llana (3°) y la otra empinada (20°), las celdas llanas de la corona suman más de 10 m²: solo
        ellas entran, y el plano es el de 3° (≤ 10⁻⁹ m) y no una mezcla; sin nota."""
        grid, z, footprint, x = self.seam_case()
        found = stockpiles.base_plane(z, footprint, grid, params_of())
        self.assertEqual(found.notes, ())
        flat = sdata.plane(3.0).values(grid)
        self.assertLess(float(np.abs(found.at(*grid.centers()) - flat)[x < 60.0].max()), 1e-9)
        self.assertTrue((x[found.kept] < 60.0).all())
        crown = stockpiles.crown_of(footprint, 1.0, inner_m=1.0, outer_m=3.0)
        self.assertTrue((found.crown <= crown).all() and found.crown.sum() < crown.sum(),
                        "solo las celdas llanas, que son menos que la corona")

    def test_the_minimum_area_is_a_threshold_by_hand(self) -> None:
        """Con el área llana igual al área mínima, valen las llanas; con medio metro cuadrado menos de lo que hace
        falta, se usa toda la corona y el aviso lleva el área llana, la pendiente de corona y el área mínima."""
        grid, z, footprint, x = self.seam_case()
        crown = stockpiles.crown_of(footprint, 1.0, inner_m=1.0, outer_m=3.0)
        slopes = oracles.hand_cell_slope_deg(z.tolist(), 1.0, 1.0)
        flat_cells = int((crown & (slopes < 12.0)).sum())
        self.assertGreater(flat_cells, 100)
        exact = stockpiles.base_plane(z, footprint, grid, params_of(crown_flat_min_m2=float(flat_cells)))
        self.assertEqual(exact.notes, ())
        self.assertEqual(int(exact.crown.sum()), flat_cells)
        short = stockpiles.base_plane(z, footprint, grid,
                                      params_of(crown_flat_min_m2=flat_cells + 0.5, tilt_max_deg=89.0))
        self.assertEqual([note.code for note in short.notes], ["des.stockpile_crown_few_flat"])
        self.assertEqual(int(short.crown.sum()), int(crown.sum()))
        self.assertEqual(dict(short.notes[0].values), {"area": float(flat_cells), "slope": 12.0,
                                                        "minimum": flat_cells + 0.5})

    def test_the_minimum_area_is_in_square_metres_not_in_cells(self) -> None:
        """Con celdas de 2 m (4 m² cada una) y N celdas llanas, un área mínima de 2·N m² (más que N celdas, menos que
        4·N m²) se cumple y no hay nota; con 4·N + 1 m² no, y la nota lleva 4·N m² llanos."""
        grid, z, footprint, _ = self.seam_case(2.0)
        crown = stockpiles.crown_of(footprint, 2.0, inner_m=1.0, outer_m=3.0)
        slopes = oracles.hand_cell_slope_deg(z.tolist(), 2.0, 2.0)
        flat_cells = int((crown & (slopes < 12.0)).sum())
        self.assertGreater(flat_cells, 20)
        enough = stockpiles.base_plane(z, footprint, grid, params_of(crown_flat_min_m2=2.0 * flat_cells))
        self.assertEqual(enough.notes, ())
        self.assertEqual(int(enough.crown.sum()), flat_cells)
        short = stockpiles.base_plane(z, footprint, grid, params_of(crown_flat_min_m2=4.0 * flat_cells + 1.0,
                                                                    tilt_max_deg=89.0))
        self.assertEqual(dict(short.notes[0].values)["area"], 4.0 * flat_cells)

    def test_a_steep_crown_uses_the_whole_crown_with_the_note(self) -> None:
        """RF-016-05 (la corona no llega al área llana mínima): en un plano de 20° ninguna celda es llana; se usa toda
        la corona, el plano sale exacto (inclinación máxima de 30° para no limitar) y la nota dice 0 m² llanos."""
        case = sdata.mound_case("cone", 20.0)
        footprint = sdata.in_box(case.mark_box, case.grid)
        found = stockpiles.base_plane(case.terrain, footprint, case.grid, params_of(tilt_max_deg=30.0))
        self.assertEqual([note.code for note in found.notes], ["des.stockpile_crown_few_flat"])
        self.assertEqual(dict(found.notes[0].values), {"area": 0.0, "slope": 12.0, "minimum": 10.0})
        crown = stockpiles.crown_of(footprint, 1.0, inner_m=1.0, outer_m=3.0)
        np.testing.assert_array_equal(found.crown, crown)
        self.assertLess(worst_error(found, case), 1e-6)
        text = found.notes[0].notice("Acopio 2", 699_760.0, 4_399_760.0).text("es")
        for part in ("«Acopio 2»", "toda la corona", "12,0°"):
            self.assertIn(part, text)

    def test_a_note_comes_before_the_tilt_note(self) -> None:
        """Las notas salen en el orden de A2: primero la corona, después la inclinación (20° con una máxima de 4°)."""
        case = sdata.mound_case("cone", 20.0)
        footprint = sdata.in_box(case.mark_box, case.grid)
        found = stockpiles.base_plane(case.terrain, footprint, case.grid, params_of())
        self.assertEqual([note.code for note in found.notes],
                         ["des.stockpile_crown_few_flat", "des.stockpile_tilt_limited"])


class RejectionTest(unittest.TestCase):
    """RF-016-04: la corona sin celdas o sin terreno rechaza el acopio nombrando su marca."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = window(30.0)
        cls.z = sdata.plane(3.0, pivot=(15.0, 15.0)).values(cls.grid)
        cls.footprint = sdata.in_box((10.0, 10.0, 20.0, 20.0), cls.grid)

    def rejected(self, z: np.ndarray, footprint: np.ndarray, grid: object | None = None,
                 **changes: float) -> object:
        with self.assertRaises(stockpiles.StockpileRejected) as caught:
            stockpiles.base_plane(z, footprint, grid or self.grid, params_of(**changes))
        return caught.exception.message

    def test_a_footprint_that_fills_the_window_has_no_crown(self) -> None:
        """Sin corona (la huella ocupa toda la ventana): rechazo ``des.stockpile_no_crown_cells`` con la separación
        interior y la exterior, y la marca y su lugar en el aviso (en español, con el nombre de la marca)."""
        message = self.rejected(self.z, np.ones(self.grid.shape, dtype=bool))
        self.assertEqual(message.code, "des.stockpile_no_crown_cells")
        self.assertEqual(dict(message.values), {"inner": 1.0, "outer": 3.0})
        notice = message.notice("Acopio 3", 699_715.0, 4_399_715.0)
        self.assertEqual((notice.code, notice.severity), ("des.stockpile_no_crown_cells", "warning"))
        self.assertIn("«Acopio 3»", notice.text("es"))
        self.assertIn("Acopio 3", notice.text("en"))

    def test_an_inverted_ring_or_no_footprint_has_no_crown(self) -> None:
        """La separación interior igual a la exterior, o una huella vacía, tampoco tienen corona."""
        self.assertEqual(self.rejected(self.z, self.footprint, crown_inner_m=3.0).code,
                         "des.stockpile_no_crown_cells")
        self.assertEqual(self.rejected(self.z, np.zeros(self.grid.shape, dtype=bool)).code,
                         "des.stockpile_no_crown_cells")

    def test_too_few_cells_for_a_plane_are_a_rejection_with_the_ring(self) -> None:
        """Una corona de una celda (huella en la esquina de una ventana de 3 × 3, con 1 a 1,5 m) no ajusta un plano:
        el mismo rechazo y con los valores del anillo (no los de la función de ajuste, que no los conoce)."""
        grid = window(3.0)
        footprint = np.zeros((3, 3), dtype=bool)
        footprint[0, 0] = True
        message = self.rejected(np.zeros((3, 3)), footprint, grid, crown_outer_m=1.5)
        self.assertEqual(message.code, "des.stockpile_no_crown_cells")
        self.assertEqual(dict(message.values), {"inner": 1.0, "outer": 1.5})

    def test_cells_without_terrain_in_the_crown_are_a_rejection_with_the_first_one(self) -> None:
        """Dos celdas de la corona sin dato: ``des.stockpile_no_terrain_crown`` con cuántas son y el lugar (absoluto,
        float64, el centro de la celda) de la primera en el orden de lectura (fila 0 al norte), calculado a mano; la
        marca y el lugar de la llamada no lo pisan."""
        crown = oracles.hand_crown(self.footprint.tolist(), 1.0, 1.0, 3.0)
        found = np.argwhere(crown)
        (r1, c1), (r2, c2) = found[7], found[40]
        z = self.z.copy()
        z[r1, c1] = z[r2, c2] = np.nan
        message = self.rejected(z, self.footprint)
        self.assertEqual(message.code, "des.stockpile_no_terrain_crown")
        east, north = self.grid.west + (c1 + 0.5), self.grid.north - (r1 + 0.5)
        self.assertEqual(dict(message.values), {"cells": 2, "x": east, "y": north})
        notice = message.notice("Acopio 4", 1.0, 2.0)
        self.assertEqual((notice.values["x"], notice.values["y"], notice.values["mark"]), (east, north, "Acopio 4"))

    def test_the_footprint_is_not_read_by_the_plane(self) -> None:
        """A2 no mira la huella (la mira A3: RF-016-04, «falta terreno en su huella»): una celda sin dato dentro de
        ella no cambia el plano ni rechaza."""
        z = self.z.copy()
        z[self.footprint] = np.nan
        found = stockpiles.base_plane(z, self.footprint, self.grid, params_of())
        reference = stockpiles.base_plane(self.z, self.footprint, self.grid, params_of())
        np.testing.assert_array_equal(found.at(*self.grid.centers()), reference.at(*self.grid.centers()))

    def test_cells_in_a_line_do_not_determine_a_plane(self) -> None:
        """``fit_plane`` con tres celdas en una recta, o con dos, es un rechazo (sin los valores del anillo)."""
        x, y = self.grid.centers()
        z = self.z
        for cells in ([(5, 3), (5, 4), (5, 5), (5, 6)], [(5, 3), (6, 4)]):
            crown = np.zeros(self.grid.shape, dtype=bool)
            for row, col in cells:
                crown[row, col] = True
            with self.subTest(cells=len(cells)), self.assertRaises(stockpiles.StockpileRejected) as caught:
                stockpiles.fit_plane(z, crown, x, y, **fit_kwargs())
            self.assertEqual(caught.exception.message.code, "des.stockpile_no_crown_cells")

    def test_a_rejection_is_named_in_its_text(self) -> None:
        """El rechazo es una excepción con su código y su mensaje (para el registro) y no se lanza con un código que
        no está en el catálogo del diseño."""
        message = self.rejected(self.z, np.ones(self.grid.shape, dtype=bool))
        error = stockpiles.StockpileRejected(message.code, **dict(message.values))
        self.assertIn("des.stockpile_no_crown_cells", str(error))
        with self.assertRaises(ValueError):
            stockpiles.StockpileRejected("des.no_such_message")


class RobustRoundsTest(unittest.TestCase):
    """RF-016-02: el número de vueltas del ajuste robusto es el de ``fit_rounds``, igual que el oráculo."""

    @classmethod
    def setUpClass(cls) -> None:
        rng = np.random.default_rng(15)  # elegida (explorando semillas): cada una de las 8 vueltas descarta celdas
        cls.grid = sdata.window_grid(1.0, 20.0)
        cls.x, cls.y = cls.grid.centers()
        cls.z = (100.0 + 0.03 * (cls.x - cls.x[0, 0]) - 0.02 * (cls.y - cls.y[0, 0])
                 + rng.standard_t(1.0, size=cls.grid.shape))
        cls.crown = np.ones(cls.grid.shape, dtype=bool)

    def kept_after(self, rounds: int) -> tuple[np.ndarray, object]:
        found = stockpiles.fit_plane(self.z, self.crown, self.x, self.y, rounds=rounds, max_residual_m=1.0,
                                     tilt_max_deg=80.0, quantile=0.6)
        return found.kept, found

    def test_each_round_is_the_hand_calculation(self) -> None:
        """Con ruido de Cauchy (400 celdas, escala 1 m), cada vuelta de 1 a 8 descarta lo que el oráculo (a mano, en
        racionales): las mismas celdas y el mismo plano (≤ 10⁻⁹ relativo); y las vueltas importan: cada una descarta
        más (con esta semilla, de 193 a 179 celdas)."""
        cells = cells_of(self.grid, self.z, self.crown)
        kept_sets = []
        for rounds in range(1, 9):
            with self.subTest(rounds=rounds):
                kept, found = self.kept_after(rounds)
                by_hand = oracles.hand_plane(cells, rounds=rounds, max_residual_m=1.0, tilt_max_deg=80.0,
                                             quantile=0.6)
                self.assertEqual(tuple(kept.ravel()), by_hand.kept)
                self.assertAlmostEqual(found.east_slope / by_hand.east_slope, 1.0, delta=1e-9)
                self.assertAlmostEqual(found.north_slope / by_hand.north_slope, 1.0, delta=1e-9)
                self.assertAlmostEqual(float(found.at(self.x[3, 4], self.y[3, 4])
                                             / by_hand.at(float(self.x[3, 4]), float(self.y[3, 4]))), 1.0, delta=1e-9)
                kept_sets.append(int(kept.sum()))
        self.assertEqual(len(set(kept_sets)), 8, kept_sets)
        self.assertEqual(kept_sets, sorted(kept_sets, reverse=True), "cada vuelta descarta, nunca recupera")

    def test_a_discard_that_leaves_fewer_than_three_cells_is_not_made(self) -> None:
        """Cuatro celdas en las esquinas de un cuadrado de 1 m con z = (0, 0, 0, 10): el ajuste da b = c = 5 y a los
        cuatro un residuo de ±2,5 m, todos a más de 1 m de la mediana (0); descartarlos dejaría 0 celdas, así que no
        se descarta ninguna y el plano es el del primer ajuste (también en el oráculo)."""
        x = np.array([[0.0, 1.0], [0.0, 1.0]]) + 700_000.0
        y = np.array([[1.0, 1.0], [0.0, 0.0]]) + 4_400_000.0
        z = np.array([[0.0, 10.0], [0.0, 0.0]])
        crown = np.ones((2, 2), dtype=bool)
        found = stockpiles.fit_plane(z, crown, x, y, rounds=4, max_residual_m=1.0, tilt_max_deg=89.0, quantile=0.6)
        self.assertTrue(found.kept.all())
        self.assertAlmostEqual(found.east_slope, 5.0, delta=1e-9)
        self.assertAlmostEqual(found.north_slope, 5.0, delta=1e-9)
        by_hand = oracles.hand_plane([(float(x[r, c]), float(y[r, c]), float(z[r, c])) for r in range(2)
                                      for c in range(2)], rounds=4, max_residual_m=1.0, tilt_max_deg=89.0,
                                     quantile=0.6)
        self.assertEqual(by_hand.kept, (True,) * 4)
        self.assertAlmostEqual(found.pivot_z, by_hand.pivot_z, delta=1e-9)


class ParamsTest(unittest.TestCase):
    """Los parámetros de A2: sus rangos son los de la familia ``stockpile`` (``design.params.STOCKPILE_RANGES``)."""

    def test_valid_parameters_are_kept_as_given(self) -> None:
        """Se guardan tal cual (sin valores por defecto: los pone quien los resuelve, con su procedencia)."""
        found = params_of()
        for name, value in D3.items():
            self.assertEqual(getattr(found, name), value)
        with self.assertRaises(TypeError):
            stockpiles.PlaneParams()  # sin cifras a mano: ni una por defecto

    def test_out_of_range_values_are_refused_naming_the_parameter(self) -> None:
        """Un valor fuera de rango (o que no es un número, o un entero que no lo es) es un ``ValueError`` que nombra el
        parámetro: pendiente 0 o 90°, inclinación máxima 90°, cuantil 1,2, 0 vueltas, residuo 0, NaN, texto, 1,5
        vueltas."""
        for name, value in (("crown_slope_deg", 0.0), ("crown_slope_deg", 90.0), ("tilt_max_deg", 90.0),
                            ("tilt_max_deg", -1.0), ("support_quantile", 1.2), ("fit_rounds", 0),
                            ("max_residual_m", 0.0), ("crown_outer_m", math.nan), ("crown_inner_m", "1"),
                            ("fit_rounds", 1.5), ("fit_rounds", True), ("crown_flat_min_m2", -1.0)):
            with self.subTest(name=name, value=value), self.assertRaisesRegex(ValueError, name):
                params_of(**{name: value})

    def test_fit_plane_checks_the_same_values(self) -> None:
        """``fit_plane`` rechaza los mismos valores y las formas que no cuadran (``ValueError``)."""
        grid = window(10.0)
        x, y = grid.centers()
        z, crown = np.zeros(grid.shape), np.ones(grid.shape, dtype=bool)
        for changes in ({"rounds": 0}, {"max_residual_m": 0.0}, {"tilt_max_deg": 90.0}, {"quantile": -0.1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                stockpiles.fit_plane(z, crown, x, y, **{**fit_kwargs(), **changes})
        with self.assertRaises(ValueError):
            stockpiles.fit_plane(z, crown.astype(int), x, y, **fit_kwargs())
        with self.assertRaises(ValueError):
            stockpiles.fit_plane(z, crown[:5], x, y, **fit_kwargs())
        with self.assertRaises(ValueError):
            stockpiles.fit_plane(z, crown, x[:, :5], y, **fit_kwargs())
        z[0, 0] = np.nan
        with self.assertRaises(ValueError):  # un hueco en la corona lo rechaza ``base_plane``, no ``fit_plane``
            stockpiles.fit_plane(z, crown, x, y, **fit_kwargs())

    def test_base_plane_needs_square_cells_and_a_matching_window(self) -> None:
        """La rejilla de los acopios es la del proyecto, de celdas cuadradas; la superficie y la huella cuadran con
        ella."""
        grid = gis.Grid(sdata.BASE[0], sdata.BASE[1] + 10.0, 1.0, 2.0, 10, 5)
        with self.assertRaises(ValueError):
            stockpiles.base_plane(np.zeros(grid.shape), np.zeros(grid.shape, bool), grid, params_of())
        square = window(10.0)
        with self.assertRaises(ValueError):
            stockpiles.base_plane(np.zeros((9, 10)), np.zeros(square.shape, bool), square, params_of())
        with self.assertRaises(ValueError):
            stockpiles.base_plane(np.zeros(square.shape), np.zeros((9, 10), bool), square, params_of())


if __name__ == "__main__":
    unittest.main()
