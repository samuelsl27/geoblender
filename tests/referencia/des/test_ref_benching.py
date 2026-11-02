# SPDX-License-Identifier: GPL-3.0-or-later
"""Casos de referencia del escalonado (spec 013, T09 y T10; HU-013-5; RF-013-22 a RF-013-27;
CE-013-03, CE-013-04, CE-013-05; plan 013 A7, A8, A9).

- **CE-013-04 · regresión de los errores 13 y 15** (T10): un sector con talud general máximo de
  10,6° con ``REST_5_35_6`` tiene una berma de **19,5765237 m** (la spec dice «19,576 m», ese valor
  truncado al milímetro; cálculo a mano, ≤ 10⁻⁹ relativo) y el resto, de 6 m; las anchuras medidas
  en la rejilla coinciden con ellas dentro de una celda; y la inclinación entre celdas de dos
  sectores no pasa de la cara más la tolerancia de cara (sin la regularización pasaba de 60°: con
  las envolventes de cada sector por separado, la pared entre sectores llega a 87°).
- **CE-013-05 · regresión del error 14** (T10): tras escalonar un frente de tres sectores
  (10,6°, 18° y el del perfil), la inclinación máxima entre celdas con el recorte final es ≤ la
  cara más la tolerancia (sin recorte pasaba de 60°: 69,7°), y el corte sigue por encima de ``S``.
- **CE-013-03 · escalonado de referencia**: un plano inclinado de 160 × 40 celdas de 1 m
  (``z = 140 + 0,25·(columna + 0,5)``, de 140,125 a 179,875 m, exacto en binario) se escalona en
  corte y en relleno con ``EXPL_10_60_6`` y ``REST_5_35_6`` (ancla 125 m):

  - las **bermas** están en ``z₀ + n·h`` (≤ 10⁻⁹ m), y todo el resultado coincide con el cálculo a
    mano (aritmética racional del piso ``n`` y de la fracción ``f``);
  - el **corte** queda por encima de ``S`` y el **relleno** por debajo, con diferencia ``< h``;
  - las **caras** no pasan de ``α`` más la tolerancia de cara (``des.tolerance.face_deg``, 1°): con
    la pendiente 0,25 del plano, la cara mide ``atan(0,25·(1 + B·tan α/h))`` (27,0° y 24,7°), y
    con una pendiente igual al talud general del perfil (``h/a``) llega exactamente a ``α``;
  - el **volumen** entre el escalonado y ``S`` es el calculado a mano sobre los mismos centros de
    celda (≤ 10⁻⁹ relativo): 16.313,8438763 m³ con ``EXPL_10_60_6`` y 7.306,80538192 m³ con
    ``REST_5_35_6``, iguales en corte y en relleno.
"""

from __future__ import annotations

import math
import unittest
from collections.abc import Callable
from typing import Any

import numpy as np

from tests.support import design_fixtures as dfx
from tests.support import design_oracles as oracles
from tests.support.package import import_geoblender

benching = import_geoblender("design.benching")
envelopes = import_geoblender("design.envelopes")
params = import_geoblender("design.params")
design_model = import_geoblender("design.model")

TOLERANCE_M = 1e-9
RELATIVE = 1e-9
FACE_TOLERANCE_DEG = float(next(item for item in params.DEFINITIONS
                                if item.key == params.TOLERANCE_FACE).default)
"""La tolerancia de cara por defecto del proyecto (°)."""
VOLUMES_M3 = {"EXPL_10_60_6": 16313.8438763, "REST_5_35_6": 7306.80538192}
"""Los volúmenes (m³) de la spec, calculados a mano con el oráculo racional; iguales en corte y en
relleno (la escalera de uno es la del otro vista al revés, y el plano recorre 40 y 32 bancos)."""
SENSES: tuple[tuple[str, bool], ...] = (("corte", False), ("relleno", True))


def tan_of(profile: Any) -> float:
    return math.tan(math.radians(profile.face_deg))


def stairs(profile: Any, surface: np.ndarray, *, fill: bool) -> np.ndarray:
    function: Callable[..., np.ndarray] = benching.bench_fill if fill else benching.bench_cut
    return function(surface, profile.height_m, tan_of(profile), profile.berm_m, profile.anchor_m)


def hand(profile: Any, surface: np.ndarray, *, fill: bool) -> np.ndarray:
    return oracles.hand_stairs(surface, profile.height_m, tan_of(profile), profile.berm_m,
                               profile.anchor_m, fill=fill)


class PlaneBenchingTest(unittest.TestCase):
    """CE-013-03: el plano inclinado con los dos perfiles de la spec, en los dos sentidos."""

    def setUp(self) -> None:
        self.case = dfx.plane_case()
        self.surface = self.case.surface()
        self.row = self.surface[0].copy()
        self.profiles = (dfx.EXPL_10_60_6, dfx.REST_5_35_6)

    def each(self) -> Any:
        for profile in self.profiles:
            for sense, fill in SENSES:
                yield profile, sense, fill, stairs(profile, self.surface, fill=fill)

    def test_whole_result_is_the_hand_calculation(self) -> None:
        """RF-013-22, RF-013-23: cada celda coincide con el cálculo a mano (piso y fracción en
        racionales) a ≤ 10⁻⁹ m, y todas las filas son la misma."""
        for profile, sense, fill, found in self.each():
            with self.subTest(profile=profile.name, sense=sense):
                self.assertEqual(found.shape, (40, 160))
                expected = hand(profile, self.row, fill=fill)
                self.assertLessEqual(float(np.abs(found - expected).max()), TOLERANCE_M)
                self.assertTrue(np.all(found == found[0]))

    def test_berms_are_at_the_anchor_levels(self) -> None:
        """RF-013-22 a RF-013-24: la parte plana de cada banco (celdas vecinas de una fila a la
        misma cota) está en una cota ``z₀ + n·h`` a ≤ 10⁻⁹ m; salen todos los niveles que cruza el
        plano (los mismos del cálculo a mano), y nada más."""
        for profile, sense, fill, found in self.each():
            with self.subTest(profile=profile.name, sense=sense):
                row = found[0]
                plateau = row[:-1][np.abs(np.diff(row)) <= 1e-12]
                levels = np.array(dfx.hand_levels(profile, float(self.row.min()) - profile.height_m,
                                                  float(self.row.max()) + profile.height_m))
                distance = np.abs(plateau[:, None] - levels[None, :]).min(axis=1)
                self.assertLessEqual(float(distance.max()), TOLERANCE_M)
                found_levels = {round(float(value), 6) for value in plateau}
                expected_row = hand(profile, self.row, fill=fill)
                expected_plateau = expected_row[:-1][np.abs(np.diff(expected_row)) <= 1e-12]
                self.assertEqual(found_levels, {round(float(v), 6) for v in expected_plateau})
                crossed = {round(float(level), 6) for level in levels
                           if self.row.min() < level < self.row.max()}
                self.assertGreaterEqual(len(crossed), 4)
                self.assertLessEqual(crossed, found_levels)

    def test_cut_is_above_and_fill_below_by_less_than_one_bench(self) -> None:
        """RF-013-22, RF-013-23: el corte queda por encima de ``S`` y el relleno por debajo, a menos
        de ``h`` de ella, en toda celda."""
        for profile, sense, fill, found in self.each():
            with self.subTest(profile=profile.name, sense=sense):
                gap = (self.surface - found) if fill else (found - self.surface)
                self.assertGreaterEqual(float(gap.min()), 0.0)
                self.assertLess(float(gap.max()), profile.height_m)
                self.assertGreater(float(gap.max()), 0.0)

    def test_faces_do_not_pass_the_profile_angle(self) -> None:
        """RF-013-22, RF-013-23: la inclinación entre celdas vecinas de una fila no pasa de ``α``
        más la tolerancia de cara; con la pendiente 0,25 del plano, la cara mide
        ``atan(0,25·(1 + B·tan α/h))`` (a mano: 27,0° y 24,7°)."""
        for profile, sense, fill, found in self.each():
            with self.subTest(profile=profile.name, sense=sense):
                slope = float(np.abs(np.diff(found[0])).max())
                hand_slope = 0.25 * (1.0 + profile.berm_m * tan_of(profile) / profile.height_m)
                self.assertAlmostEqual(slope, hand_slope, delta=TOLERANCE_M)
                angle = math.degrees(math.atan(slope))
                self.assertLessEqual(angle, profile.face_deg + FACE_TOLERANCE_DEG)
                self.assertLess(angle, profile.face_deg)

    def test_face_reaches_the_profile_angle_with_the_general_slope(self) -> None:
        """Con un plano de pendiente igual al talud general del perfil (``h/a``), la cara llega
        exactamente a ``α`` (≤ 10⁻⁹°) y a ninguna celda más empinada, en corte y en relleno."""
        for profile in self.profiles:
            general = dfx.PlaneCase(self.case.grid, 140.0, profile.general_tan).surface()
            for sense, fill in SENSES:
                with self.subTest(profile=profile.name, sense=sense):
                    found = stairs(profile, general, fill=fill)
                    angle = math.degrees(math.atan(float(np.abs(np.diff(found[0])).max())))
                    self.assertAlmostEqual(angle, profile.face_deg, delta=1e-9)

    def test_volume_is_the_hand_calculation(self) -> None:
        """CE-013-03: el volumen entre el escalonado y ``S`` (celdas de 1 m²) es el calculado a mano
        sobre los mismos centros de celda (≤ 10⁻⁹ relativo) y vale lo de la spec."""
        area = float(self.case.grid.cell_area)
        for profile, sense, fill, found in self.each():
            with self.subTest(profile=profile.name, sense=sense):
                gap = (self.surface - found) if fill else (found - self.surface)
                volume = math.fsum(gap.reshape(-1)) * area
                expected_row = hand(profile, self.row, fill=fill)
                expected_gap = (self.row - expected_row) if fill else (expected_row - self.row)
                expected = math.fsum(expected_gap) * self.surface.shape[0] * area
                self.assertAlmostEqual(volume / expected, 1.0, delta=RELATIVE)
                self.assertAlmostEqual(volume / VOLUMES_M3[profile.name], 1.0, delta=RELATIVE)

    def test_anchor_levels_are_the_same_for_every_surface(self) -> None:
        """RF-013-24: otro plano (más alto, más empinado y con otra cota mínima) usa las mismas
        cotas ``z₀ + n·h``: sus bermas están en la misma lista."""
        higher = dfx.PlaneCase(self.case.grid, 52.5, 0.6).surface()
        for profile in self.profiles:
            for sense, fill in SENSES:
                with self.subTest(profile=profile.name, sense=sense):
                    row = stairs(profile, higher, fill=fill)[0]
                    plateau = row[:-1][np.abs(np.diff(row)) <= 1e-12]
                    levels = np.array(dfx.hand_levels(profile, float(higher.min()) - 5.0,
                                                      float(higher.max()) + 15.0))
                    distance = np.abs(plateau[:, None] - levels[None, :]).min(axis=1)
                    self.assertGreater(plateau.size, 10)
                    self.assertLessEqual(float(distance.max()), TOLERANCE_M)


class ProfileCodeTest(unittest.TestCase):
    """Los perfiles de la spec y los de ``design.model`` dan el mismo escalonado."""

    def test_bench_profile_of_the_model_gives_the_fixture_result(self) -> None:
        """Un ``BenchProfile`` de ``design.model`` (los mismos números) escalona igual que los
        valores del perfil de pruebas: es la entrada real del escalonado (RF-013-18)."""
        surface = dfx.plane_case().surface()
        for fixture in (dfx.EXPL_10_60_6, dfx.REST_5_35_6):
            profile = design_model.BenchProfile(fixture.code, fixture.name, fixture.height_m,
                                                fixture.face_deg, fixture.berm_m,
                                                fixture.anchor_m)
            tan_face = math.tan(math.radians(profile.face_deg))
            for fill, function in ((False, benching.bench_cut), (True, benching.bench_fill)):
                with self.subTest(profile=profile.name, fill=fill):
                    found = function(surface, profile.height_m, tan_face, profile.berm_m,
                                     profile.anchor_m)
                    np.testing.assert_array_equal(found, stairs(fixture, surface, fill=fill))


# --- CE-013-04 y CE-013-05: los sectores con talud impuesto (T10) ---------------------------------

CUT_STEEP_DEG = 60.0
"""«Pasaba de 60°»: el umbral de la spec para las inclinaciones sin regularización ni recorte."""


def run(steps: Any) -> Any:
    """El resultado (último paso) de unos pasos."""
    return list(steps)[-1].result


def max_incline_deg(grid: np.ndarray, columns: tuple[int, ...] | None = None) -> float:
    """La mayor inclinación (°) entre celdas vecinas a 8 vecinos (paso 1 m). Con ``columns``, solo
    las parejas que cruzan el borde entre la columna ``c − 1`` y la ``c`` para cada ``c``: las de
    dos sectores."""
    if columns is not None:
        worst = 0.0
        for column in columns:
            left, right = grid[:, column - 1], grid[:, column]
            slopes = [np.abs(left - right), np.abs(left[1:] - right[:-1]) / math.sqrt(2.0),
                      np.abs(left[:-1] - right[1:]) / math.sqrt(2.0)]
            worst = max(worst, max(float(item.max()) for item in slopes))
        return math.degrees(math.atan(worst))
    worst = 0.0
    for d_row, d_col in ((0, 1), (1, 0), (1, 1), (1, -1)):
        rows, cols = grid.shape
        first = grid[0:rows - d_row, max(0, -d_col):cols - max(0, d_col)]
        second = grid[d_row:rows, max(0, d_col):cols - max(0, -d_col)]
        worst = max(worst, float((np.abs(first - second) / math.hypot(d_row, d_col)).max()))
    return math.degrees(math.atan(worst))


def plateau_runs(column: np.ndarray, profile: Any) -> list[int]:
    """Las anchuras, en celdas, de los tramos planos en una cota ``z₀ + n·h`` (a ≤ 10⁻⁹ m) que
    están enteros dentro de la columna (sin tocar la primera ni la última fila)."""
    levels = (column - profile.anchor_m) / profile.height_m
    flat = np.abs(levels - np.round(levels)) * profile.height_m <= TOLERANCE_M
    runs: list[int] = []
    start: int | None = None
    for row, value in enumerate(flat):
        if value and start is None:
            start = row
        elif not value and start is not None:
            if start > 0:
                runs.append(row - start)
            start = None
    return runs


class Front:
    """Un frente de sectores calculado por etapas (A7, A9): la envolvente descendente de la cresta
    de semillas con la pendiente de cada sector, el escalonado en corte con la berma de cada sector
    (``sector_berm``) y el recorte final.

    - ``walled=False``: la envolvente del *chamfer* con la pendiente por sectores (entrar en una
      celda cuesta con la pendiente de la celda de llegada): ya es regular.
    - ``walled=True``: la envolvente de cada sector por separado (con su pendiente en toda la
      rejilla) unidas por las etiquetas: la pared de las envolventes que se juntan sin más, que es
      el error 15.
    """

    def __init__(self, case: Any, *, walled: bool) -> None:
        self.case = case
        self.labels = case.labels()
        profile = case.profile
        rules = [envelopes.SlopeRule(profile.general_tan, profile.mesh_factor) if deg is None
                 else envelopes.SlopeRule.from_degrees(deg, profile.mesh_factor)
                 for deg in case.imposed_deg]
        self.slope = envelopes.sector_slope(self.labels, rules)
        if walled:
            self.envelope = np.empty(case.grid.shape)
            for index, rule in enumerate(rules, start=1):
                own = run(envelopes.chamfer_steps(case.seeds(), case.grid,
                                                  envelopes.SlopeField(rule.effective), "down",
                                                  name="e1")).grid
                self.envelope[self.labels == index] = own[self.labels == index]
        else:
            self.envelope = run(envelopes.chamfer_steps(case.seeds(), case.grid, self.slope,
                                                        "down", name="e1")).grid
        self.model = design_model.BenchProfile(profile.code, profile.name, profile.height_m,
                                               profile.face_deg, profile.berm_m,
                                               profile.anchor_m, profile.mesh_factor)
        self.berms = np.array([benching.sector_berm(self.model, deg) for deg in case.imposed_deg])
        self.tan_face = tan_of(profile)

    def regularized(self) -> Any:
        return run(benching.regularize_steps(self.envelope, self.case.grid, self.slope,
                                             name="e1"))

    def stairs(self, surface: np.ndarray) -> np.ndarray:
        profile = self.case.profile
        return benching.bench_cut(surface, profile.height_m, self.tan_face,
                                  self.berms[self.labels - 1], profile.anchor_m)

    def trimmed(self, stairs: np.ndarray, surface: np.ndarray) -> Any:
        return run(benching.final_trim_steps(stairs, surface, self.case.grid, self.tan_face,
                                             self.case.profile.mesh_factor, "cut", name="d1"))


class ImposedBermTest(unittest.TestCase):
    """CE-013-04: el sector de 10,6° con ``REST_5_35_6`` (errores 13 y 15)."""

    def setUp(self) -> None:
        self.case = dfx.imposed_sector_case()
        self.cell = float(self.case.grid.dx)

    def test_berm_of_the_sector_is_19_576_by_hand(self) -> None:
        """RF-013-25: la berma del sector de 10,6° es ``5/tan 10,6° − 5/tan 35°`` =
        **19,5765237 m** (la spec la trunca a 19,576 m), a ≤ 10⁻⁹ relativo del cálculo a mano y de
        la de los datos de referencia; la del otro sector, la mínima del perfil (6 m)."""
        front = Front(self.case, walled=False)
        tendido, normal = front.berms
        by_hand = 5.0 / math.tan(math.radians(10.6)) - 5.0 / math.tan(math.radians(35.0))
        self.assertAlmostEqual(tendido / by_hand, 1.0, delta=RELATIVE)
        self.assertAlmostEqual(tendido / 19.5765237, 1.0, delta=RELATIVE)
        self.assertAlmostEqual(tendido / self.case.berm_m("frente_tendido"), 1.0, delta=RELATIVE)
        self.assertEqual(math.floor(tendido * 1000.0) / 1000.0, 19.576)
        self.assertEqual(normal, 6.0)
        self.assertEqual(normal, self.case.berm_m("frente_normal"))

    def test_measured_widths_match_within_one_cell(self) -> None:
        """RF-013-25: las anchuras medidas en la rejilla (celdas planas en ``z₀ + n·h`` por banco)
        coinciden con las bermas dentro de una celda: en el sector de 10,6° (columna 10, lejos del
        borde) 19,58 m y en el otro (columna 115) 6 m, con la envolvente de los sectores, la
        regularización (que no la cambia: ya es regular), el escalonado y el recorte final."""
        front = Front(self.case, walled=False)
        regular = front.regularized()
        self.assertEqual(regular.lowered, 0)
        self.assertLessEqual(float(np.abs(regular.grid - front.envelope).max()), TOLERANCE_M)
        final = front.trimmed(front.stairs(regular.grid), regular.grid).grid
        for column, berm in ((10, front.berms[0]), (115, front.berms[1])):
            runs = plateau_runs(final[:, column], self.case.profile)
            with self.subTest(column=column, berm=berm):
                self.assertGreaterEqual(len(runs), 2)
                for width in runs:
                    self.assertLessEqual(abs(width * self.cell - berm), self.cell)

    def test_walls_between_sectors_need_the_regularization(self) -> None:
        """RF-013-26: con las envolventes de cada sector por separado (error 15) hay una pared de
        87° en el borde entre sectores que el recorte no puede quitar (el corte no baja de ``S``,
        que ya la tiene); regularizadas con la tangente más empinada de los sectores, el escalonado
        recortado no pasa de la cara más la tolerancia de cara (34,6° < 36°) en toda la rejilla ni
        entre las celdas de los dos sectores, y el corte sigue por encima de ``S``."""
        front = Front(self.case, walled=True)
        border = (60,)
        self.assertGreater(max_incline_deg(front.envelope, border), CUT_STEEP_DEG)
        without = front.trimmed(front.stairs(front.envelope), front.envelope)
        self.assertGreater(max_incline_deg(without.grid, border), CUT_STEEP_DEG)
        self.assertGreater(without.clamped, 100)
        regular = front.regularized()
        self.assertEqual(regular.tan, float(front.slope.max_tan))
        self.assertGreater(regular.lowered, 1000)
        stairs = front.stairs(regular.grid)
        self.assertGreater(max_incline_deg(stairs, border), CUT_STEEP_DEG)  # sin el recorte
        final = front.trimmed(stairs, regular.grid)
        limit = FACE_TOLERANCE_DEG + self.case.profile.face_deg
        self.assertLessEqual(max_incline_deg(final.grid, border), limit)
        self.assertLessEqual(max_incline_deg(final.grid), limit)
        self.assertEqual(final.clamped, 0)
        self.assertGreaterEqual(float((final.grid - regular.grid).min()), 0.0)


class ThreeSectorsTest(unittest.TestCase):
    """CE-013-05: un frente de tres sectores con taludes de 10,6°, 18° y el del perfil
    (error 14)."""

    def setUp(self) -> None:
        self.case = dfx.three_sectors_case()
        self.limit = FACE_TOLERANCE_DEG + self.case.profile.face_deg

    def test_trim_brings_every_face_under_the_profile_angle(self) -> None:
        """RF-013-27: el escalonado de la envolvente de los tres sectores pasa de 60° (69,6°) entre
        las celdas de sectores distintos; con el recorte final, la inclinación máxima de toda la
        rejilla es ≤ la cara más la tolerancia de cara (34,6° frente a 35° + 1°), en cada borde, y
        el corte sigue por encima de ``S``."""
        front = Front(self.case, walled=False)
        surface = front.regularized().grid
        stairs = front.stairs(surface)
        self.assertGreater(max_incline_deg(stairs), CUT_STEEP_DEG)
        self.assertGreater(max_incline_deg(stairs, (50,)), CUT_STEEP_DEG)
        final = front.trimmed(stairs, surface)
        self.assertLessEqual(max_incline_deg(final.grid), self.limit)
        self.assertLess(max_incline_deg(final.grid), self.case.profile.face_deg)
        for border in (50, 100):
            with self.subTest(border=border):
                self.assertLessEqual(max_incline_deg(final.grid, (border,)), self.limit)
        self.assertGreaterEqual(float((final.grid - surface).min()), 0.0)
        self.assertLessEqual(float((final.grid - stairs).max()), 0.0)
        self.assertEqual(final.clamped, 0)

    def test_no_step_is_left_with_the_envelopes_of_each_sector(self) -> None:
        """RF-013-26, RF-013-27: con las envolventes de cada sector por separado (paredes de 86° y
        80°), ni el recorte las quita (el corte no baja de ``S``) ni se queda sin hacer: con la
        regularización y el recorte, ninguna inclinación de la rejilla pasa de la cara más la
        tolerancia y el corte sigue por encima de la envolvente regularizada."""
        front = Front(self.case, walled=True)
        borders = (50, 100)
        self.assertGreater(max_incline_deg(front.envelope, borders), CUT_STEEP_DEG)
        without = front.trimmed(front.stairs(front.envelope), front.envelope)
        self.assertGreater(max_incline_deg(without.grid, borders), CUT_STEEP_DEG)
        regular = front.regularized()
        final = front.trimmed(front.stairs(regular.grid), regular.grid)
        self.assertLessEqual(max_incline_deg(final.grid), self.limit)
        self.assertGreaterEqual(float((final.grid - regular.grid).min()), 0.0)
        self.assertEqual(final.clamped, 0)

    def test_berms_and_widths_of_the_three_sectors(self) -> None:
        """Las bermas de los tres sectores son las de la cuenta a mano (19,5765 m, 8,2477 m y 6 m
        del perfil) y las anchuras medidas en columnas lejos de los bordes (10, 97 y 145) coinciden
        con ellas dentro de una celda tras el escalonado y el recorte."""
        front = Front(self.case, walled=False)
        expected = (5.0 / math.tan(math.radians(10.6)) - 5.0 / math.tan(math.radians(35.0)),
                    5.0 / math.tan(math.radians(18.0)) - 5.0 / math.tan(math.radians(35.0)), 6.0)
        for found, by_hand in zip(front.berms, expected, strict=True):
            self.assertAlmostEqual(found / by_hand, 1.0, delta=RELATIVE)
        surface = front.regularized().grid
        final = front.trimmed(front.stairs(surface), surface).grid
        for column, berm in zip((10, 97, 145), expected, strict=True):
            runs = plateau_runs(final[:, column], self.case.profile)
            with self.subTest(column=column, berm=berm):
                self.assertGreaterEqual(len(runs), 2)
                for width in runs:
                    self.assertLessEqual(abs(width - berm), 1.0)


if __name__ == "__main__":
    unittest.main()
