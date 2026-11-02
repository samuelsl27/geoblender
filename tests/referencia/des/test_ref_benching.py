# SPDX-License-Identifier: GPL-3.0-or-later
"""Casos de referencia del escalonado (spec 013, T09; HU-013-5; RF-013-22, RF-013-23, RF-013-24;
CE-013-03; plan 013 A8).

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


if __name__ == "__main__":
    unittest.main()
