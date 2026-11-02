# SPDX-License-Identifier: GPL-3.0-or-later
"""Casos de referencia de las envolventes (spec 013, T06 y T08; RF-013-11, RF-013-12, RF-013-15;
CE-013-01, CE-013-02; ADR-0014; plan 013 §7.1).

- **CE-013-01 · regresión del error 5** (el *chamfer* 3×3 daba un cono con un 8 % de error):
  un cono desde un punto, con el *chamfer* 5×5, difiere de la distancia euclídea **≤ 1,4 %** en
  toda la rejilla (RF-013-12), en las dos direcciones, frente a los triángulos pitagóricos hechos a
  mano y frente al cono analítico del punto; con la escala 0,98644 del ADR-0014 el error está en
  −1,356 % a +1,355 %. Una pared plana alineada con la rejilla da, **con el *chamfer* 5×5**, una
  distancia a lo largo del eje un 1,356 % corta (``n·h·t·0,98644``), dentro del 1,4 % de RF-013-12
  (spec 0.3). **Con la euclídea exacta (T08)** el cono da la distancia entre centros de celda con
  error relativo ≤ 10⁻⁹ y queda a ≤ media celda del cono analítico del punto, y la pared da la
  cota exacta (``f ± t·h·n``, ≤ 10⁻⁹ m).
- **CE-013-02 · regresión del error 6** (la envolvente no era un punto fijo): con semillas
  dispersas, usar la envolvente como semilla en todas sus celdas no cambia ninguna más de 10⁻⁹ m,
  en las dos direcciones y, con el *chamfer*, con pendiente por sectores (tres sectores con taludes
  de 10,6°, 18° y el de su perfil; la exacta solo admite la constante, RF-013-16).
"""

from __future__ import annotations

import math
import unittest
from typing import Any

import numpy as np

from tests.support import design_fixtures as dfx
from tests.support.package import import_geoblender

envelopes = import_geoblender("design.envelopes")

SCALE = 0.98644
MAX_DISTANCE_ERROR = 0.014
"""RF-013-12: el *chamfer* 5×5 difiere de la euclídea ≤ 1,4 % (error relativo, cono de un punto)."""
TOLERANCE_M = 1e-9


def solve(seed: np.ndarray, slope: Any, grid: Any, direction: str) -> Any:
    steps = list(envelopes.chamfer_steps(seed, grid, slope, direction, name="e1"))
    return steps[-1].result


def solve_exact(seed: np.ndarray, slope: Any, grid: Any, direction: str) -> Any:
    steps = list(envelopes.exact_steps(seed, grid, slope, direction, name="e1"))
    return steps[-1].result


class ConeTest(unittest.TestCase):
    """CE-013-01: el cono de un punto (201 × 201 celdas de 1 m, 200 m, 35°)."""

    def setUp(self) -> None:
        self.case = dfx.cone_case()
        self.slope = envelopes.constant_slope(self.case.slope_deg)
        self.far = self.case.distances() > 0.0

    def relative_error(self, found: np.ndarray, exact: np.ndarray, sign: float) -> np.ndarray:
        """El error relativo de la distancia: ``(E − f)/(t·d)`` menos 1 (con ``E`` y ``exact`` ya
        en la cara que toca, ``sign`` ±1) en las celdas que no son la semilla."""
        z = self.case.seed_z
        return (sign * (found - z))[self.far] / (sign * (exact - z))[self.far] - 1.0

    def test_cone_distance_error_is_within_1_4_percent(self) -> None:
        """CE-013-01, RF-013-12: en toda la rejilla, el *chamfer* 5×5 (ascendente y descendente)
        difiere del cono exacto ≤ 1,4 %; con la escala del ADR-0014, de −1,356 % (a lo largo de
        los ejes) a +1,35 %; la celda de la semilla queda a su cota."""
        for direction, sign in (("up", 1.0), ("down", -1.0)):
            found = solve(self.case.seeds(), self.slope, self.case.grid, direction)
            exact = self.case.up() if direction == "up" else self.case.down()
            error = self.relative_error(found.grid, exact, sign)
            with self.subTest(direction=direction):
                self.assertEqual(found.grid[self.case.seed_row, self.case.seed_col], 200.0)
                self.assertLessEqual(float(np.abs(error).max()), MAX_DISTANCE_ERROR)
                self.assertAlmostEqual(float(error.min()), SCALE - 1.0, delta=1e-9)
                self.assertGreater(float(error.max()), 0.012)
                self.assertLessEqual(found.violation, TOLERANCE_M)

    def test_cone_against_the_analytic_cone_of_the_point(self) -> None:
        """CE-013-01, ADR-0014: frente al cono analítico del punto (la distancia de su centro a
        cada centro de celda, desde la esquina de la rejilla), el error relativo también está
        dentro del 1,4 %."""
        case = self.case
        x, y = case.seed_point
        distance = dfx.analytic_distance(case.grid, x, y)
        exact = case.seed_z + case.slope_tan * distance
        found = solve(case.seeds(), self.slope, case.grid, "up").grid
        error = self.relative_error(found, exact, 1.0)
        self.assertLessEqual(float(np.abs(error).max()), MAX_DISTANCE_ERROR)

    def test_hand_distances_in_the_four_quadrants(self) -> None:
        """CE-013-01: en las celdas de los triángulos pitagóricos de la spec (3-4-5, 5-12-13,
        8-15-17, 20-21-29, 60-80-100, un eje de 100 m y una diagonal de 100√2 m), en los cuatro
        cuadrantes, la cota difiere de la hecha a mano ``f ± t·d`` ≤ 1,4 % de lo que sube o baja."""
        case = self.case
        up = solve(case.seeds(), self.slope, case.grid, "up").grid
        down = solve(case.seeds(), self.slope, case.grid, "down").grid
        for d_row, d_col, meters in dfx.CONE_HAND:
            for sign_row in (1, -1):
                for sign_col in (1, -1):
                    cell = (case.seed_row + sign_row * d_row, case.seed_col + sign_col * d_col)
                    rise = case.slope_tan * meters
                    with self.subTest(cell=cell, meters=meters):
                        self.assertLessEqual(abs(up[cell] - (case.seed_z + rise)),
                                             MAX_DISTANCE_ERROR * rise + TOLERANCE_M)
                        self.assertLessEqual(abs(down[cell] - (case.seed_z - rise)),
                                             MAX_DISTANCE_ERROR * rise + TOLERANCE_M)


class WallTest(unittest.TestCase):
    """CE-013-01 (spec 0.3): la pared alineada con la rejilla, con el *chamfer* 5×5."""

    def test_wall_along_the_axis_is_1_356_percent_short(self) -> None:
        """CE-013-01, RF-013-12: una columna entera de semillas a 250 m con t = 0,5: a lo largo del
        eje la cota es ``f ± t·h·n·0,98644`` (a ≤ 10⁻⁹ m), un 1,356 % menos de lo que da la
        euclídea (``f ± t·h·n``) y por tanto dentro del 1,4 %; en las celdas de la pared, su cota.
        La exactitud de la pared (≤ 10⁻⁹ m) es de la euclídea exacta (T08)."""
        for step in (1.0, 2.0):
            case = dfx.wall_case(step)
            slope = envelopes.SlopeField(case.slope_tan)
            columns = np.abs(np.arange(case.grid.ncols) - case.column)
            for direction, sign in (("up", 1.0), ("down", -1.0)):
                found = solve(case.seeds(), slope, case.grid, direction).grid
                exact = case.up() if direction == "up" else case.down()
                by_hand = case.wall_z + sign * case.slope_tan * step * columns * SCALE
                with self.subTest(step=step, direction=direction):
                    self.assertLessEqual(float(np.abs(found - by_hand[None, :]).max()),
                                         TOLERANCE_M)
                    self.assertTrue((found[:, case.column] == case.wall_z).all())
                    off = columns > 0
                    rise = np.abs(exact - case.wall_z)[:, off]
                    error = (np.abs(found - case.wall_z)[:, off] - rise) / rise
                    self.assertLessEqual(float(np.abs(error).max()), MAX_DISTANCE_ERROR)
                    self.assertAlmostEqual(float(error.min()), SCALE - 1.0, delta=1e-9)
                    self.assertAlmostEqual(float(error.max()), SCALE - 1.0, delta=1e-9)


class ExactConeTest(unittest.TestCase):
    """CE-013-01 (T08): el cono de un punto con la euclídea exacta (201 × 201 celdas de 1 m, 35°)"""

    def setUp(self) -> None:
        self.case = dfx.cone_case()
        self.slope = envelopes.SlopeField(self.case.slope_tan)
        self.far = self.case.distances() > 0.0

    def test_the_distance_is_the_one_between_cell_centres_to_1e_9(self) -> None:
        """CE-013-01, RF-013-12: con la euclídea exacta, la distancia (``(E − f)/t``) difiere de la
        calculada a mano entre centros de celda (``h·√(Δfila² + Δcolumna²)``) ≤ 10⁻⁹ relativo en
        toda la rejilla y en las dos direcciones; la celda de la semilla queda a su cota exacta."""
        case = self.case
        for direction, sign in (("up", 1.0), ("down", -1.0)):
            found = solve_exact(case.seeds(), self.slope, case.grid, direction)
            by_hand = case.up() if direction == "up" else case.down()
            error = ((sign * (found.grid - case.seed_z))[self.far]
                     / (sign * (by_hand - case.seed_z))[self.far] - 1.0)
            with self.subTest(direction=direction):
                self.assertEqual(found.grid[case.seed_row, case.seed_col], case.seed_z)
                self.assertLessEqual(float(np.abs(error).max()), TOLERANCE_M)
                self.assertLessEqual(found.violation, TOLERANCE_M)

    def test_the_distance_is_within_half_a_cell_of_the_analytic_cone_of_the_point(self) -> None:
        """CE-013-01, ADR-0014: frente al cono analítico del punto (la distancia de su centro a cada
        centro de celda, desde la esquina de la rejilla), la distancia de la euclídea exacta queda a
        ≤ media celda (0,5 m) en toda la rejilla."""
        case = self.case
        x, y = case.seed_point
        analytic = dfx.analytic_distance(case.grid, x, y)
        found = solve_exact(case.seeds(), self.slope, case.grid, "up").grid
        measured = (found - case.seed_z) / case.slope_tan
        self.assertLessEqual(float(np.abs(measured - analytic).max()), 0.5 * case.grid.dx)

    def test_hand_distances_in_the_four_quadrants(self) -> None:
        """CE-013-01: en las celdas de los triángulos pitagóricos de la spec (3-4-5, 5-12-13,
        8-15-17, 20-21-29, 60-80-100, un eje de 100 m y una diagonal de 100√2 m), en los cuatro
        cuadrantes, la cota es exactamente la hecha a mano ``f ± t·d`` (≤ 10⁻⁹ m)."""
        case = self.case
        up = solve_exact(case.seeds(), self.slope, case.grid, "up").grid
        down = solve_exact(case.seeds(), self.slope, case.grid, "down").grid
        for d_row, d_col, meters in dfx.CONE_HAND:
            for sign_row in (1, -1):
                for sign_col in (1, -1):
                    cell = (case.seed_row + sign_row * d_row, case.seed_col + sign_col * d_col)
                    rise = case.slope_tan * meters
                    with self.subTest(cell=cell, meters=meters):
                        self.assertAlmostEqual(up[cell], case.seed_z + rise, delta=TOLERANCE_M)
                        self.assertAlmostEqual(down[cell], case.seed_z - rise, delta=TOLERANCE_M)

    def test_the_chamfer_stays_within_1_4_percent_of_the_exact_cone(self) -> None:
        """RF-013-12: las dos métricas, frente a frente: el *chamfer* 5×5 escalado difiere de la
        exacta ≤ 1,4 % de lo que sube el cono en toda la rejilla (y la exacta es la de la spec)."""
        case = self.case
        exact = solve_exact(case.seeds(), self.slope, case.grid, "up").grid
        chamfer = solve(case.seeds(), self.slope, case.grid, "up").grid
        rise = (exact - case.seed_z)[self.far]
        self.assertLessEqual(float(np.abs((chamfer - case.seed_z)[self.far] / rise - 1.0).max()),
                             MAX_DISTANCE_ERROR)


class ExactWallTest(unittest.TestCase):
    """CE-013-01 (spec 0.3, T08): la pared alineada con la rejilla, con la euclídea exacta."""

    def test_the_wall_gives_the_exact_height_to_1e_9(self) -> None:
        """CE-013-01, RF-013-12: una columna entera de semillas a 250 m con t = 0,5 (rejillas de 41
        × 41 celdas de 1 y de 2 m): la cota exacta, ``f ± t·h·n`` (``n`` = columnas a la pared), a
        ≤ 10⁻⁹ m en toda la rejilla y en las dos direcciones; la pared queda a su cota; el *chamfer*
        escalado queda un 1,356 % más corto, que es lo que esta métrica evita."""
        for step in (1.0, 2.0):
            case = dfx.wall_case(step)
            slope = envelopes.SlopeField(case.slope_tan)
            columns = np.abs(np.arange(case.grid.ncols) - case.column)
            for direction, sign in (("up", 1.0), ("down", -1.0)):
                found = solve_exact(case.seeds(), slope, case.grid, direction).grid
                by_hand = case.wall_z + sign * case.slope_tan * step * columns
                with self.subTest(step=step, direction=direction):
                    self.assertLessEqual(float(np.abs(found - by_hand[None, :]).max()),
                                         TOLERANCE_M)
                    self.assertTrue((found[:, case.column] == case.wall_z).all())
                    exact = case.up() if direction == "up" else case.down()
                    self.assertLessEqual(float(np.abs(found - exact).max()), TOLERANCE_M)
                    chamfer = solve(case.seeds(), slope, case.grid, direction).grid
                    off = columns > 0
                    shortfall = (1.0 - np.abs(chamfer - case.wall_z)[:, off]
                                 / np.abs(found - case.wall_z)[:, off])
                    self.assertAlmostEqual(float(shortfall.min()), 1.0 - SCALE, delta=1e-9)
                    self.assertAlmostEqual(float(shortfall.max()), 1.0 - SCALE, delta=1e-9)


class SeedsOfTheEnvelopeTest(unittest.TestCase):
    """CE-013-02: la envolvente usada como semilla no cambia nada."""

    def test_the_exact_envelope_of_scattered_seeds_is_a_fixed_point(self) -> None:
        """CE-013-02 (T08): con la euclídea exacta y veinticuatro semillas dispersas en 60 × 80
        celdas de 2 m, con 35° (y un factor de malla de 0,8), usar la envolvente como semilla en
        todas sus celdas no cambia ninguna más de 10⁻⁹ m, en las dos direcciones, y respeta cada
        semilla."""
        grid = dfx.grid_from(60, 80, 2.0)
        seed = dfx.scattered_seeds(grid.shape, 24, seed=20_261_102)
        for mesh in (1.0, 0.8):
            slope = envelopes.constant_slope(35.0, mesh)
            for direction in ("up", "down"):
                found = solve_exact(seed, slope, grid, direction)
                again = solve_exact(found.grid, slope, grid, direction)
                finite = np.isfinite(seed)
                sign = 1.0 if direction == "up" else -1.0
                with self.subTest(mesh_factor=mesh, direction=direction):
                    self.assertLessEqual(float(np.abs(again.grid - found.grid).max()),
                                         TOLERANCE_M)
                    self.assertLessEqual(found.violation, TOLERANCE_M)
                    self.assertTrue(((found.grid - seed)[finite] * sign <= 0.0).all())

    def assert_fixed_point(self, seed: np.ndarray, slope: Any, grid: Any) -> None:
        for direction in ("up", "down"):
            found = solve(seed, slope, grid, direction)
            again = solve(found.grid, slope, grid, direction)
            with self.subTest(direction=direction):
                self.assertLessEqual(float(np.abs(again.grid - found.grid).max()), TOLERANCE_M)
                self.assertLessEqual(found.violation, TOLERANCE_M)
                finite = np.isfinite(seed)
                sign = 1.0 if direction == "up" else -1.0
                self.assertTrue(((found.grid - seed)[finite] * sign <= 0.0).all())

    def test_scattered_seeds_with_a_constant_slope(self) -> None:
        """CE-013-02: veinticuatro semillas dispersas de cotas distintas en 60 × 80 celdas de 2 m,
        con 35° (también con un factor de malla de 0,8), en las dos direcciones."""
        grid = dfx.grid_from(60, 80, 2.0)
        seed = dfx.scattered_seeds(grid.shape, 24, seed=20_261_102)
        for mesh in (1.0, 0.8):
            with self.subTest(mesh_factor=mesh):
                self.assert_fixed_point(seed, envelopes.constant_slope(35.0, mesh), grid)

    def test_scattered_seeds_with_three_sectors(self) -> None:
        """CE-013-02: con semillas dispersas y pendiente por sectores —tres franjas de 50 columnas
        con 10,6° y 18° impuestos y el talud general del perfil ``REST_5_35_6``— la envolvente de
        las dos direcciones es un punto fijo y respeta las semillas."""
        case = dfx.three_sectors_case()
        profile = case.profile
        rules = [envelopes.SlopeRule.from_degrees(10.6), envelopes.SlopeRule.from_degrees(18.0),
                 envelopes.SlopeRule(profile.general_tan, profile.mesh_factor)]
        slope = envelopes.sector_slope(case.labels(), rules, rules[2])
        seed = dfx.scattered_seeds(case.grid.shape, 15, seed=7, low=150.0, high=210.0)
        self.assert_fixed_point(seed, slope, case.grid)
        self.assert_fixed_point(case.seeds(), slope, case.grid)

    def test_the_sector_slopes_are_tangent_of_the_general_slope(self) -> None:
        """RF-013-13: una cresta de semillas a 200 m baja, en cada sector, con la tangente de su
        talud (a lo largo de la columna ``n`` filas más abajo: ``200 − n·escala·tan``), a ≤ 10⁻⁹ m
        mientras ningún otro sector cambie el camino más corto por la fila de semillas."""
        case = dfx.three_sectors_case()
        profile = case.profile
        rules = [envelopes.SlopeRule.from_degrees(10.6), envelopes.SlopeRule.from_degrees(18.0),
                 envelopes.SlopeRule(profile.general_tan, profile.mesh_factor)]
        slope = envelopes.sector_slope(case.labels(), rules, rules[2])
        found = solve(case.seeds(), slope, case.grid, "down").grid
        tans = (math.tan(math.radians(10.6)), math.tan(math.radians(18.0)), profile.general_tan)
        for index, tan in enumerate(tans):
            column = case.edges[index] + 25  # el centro de la franja
            for rows_down in (1, 10, 50):
                with self.subTest(sector=index + 1, rows=rows_down):
                    by_hand = case.crest_z - rows_down * SCALE * tan
                    self.assertAlmostEqual(found[rows_down, column], by_hand, delta=TOLERANCE_M)


if __name__ == "__main__":
    unittest.main()
