# SPDX-License-Identifier: GPL-3.0-or-later
"""Caso de referencia de la sección tipo de la pista (spec 017, T12; HU-017-1; RF-017-20; CE-017-06; plan 017 §5.4 A6 y A7 y §5.7 P-10): una pista de eje
recto de 200 m con la sección de 11,5 m, contra el **cálculo a mano en las mismas celdas**.

Verifica **de forma independiente** lo que hace ``design.road_section``: el número de celdas de la calzada, del arcén y del caballón y sus lados salen de
contar a mano las filas de centros de celda que caen en cada ancho (``tests.support.road_data.ramp_calzada_by_hand`` y
``straight_section_by_hand``: fórmulas cerradas de un eje de oeste a este), **no** de llamar al código bajo prueba. Todo es sintético, en el dominio y sin
Blender.

- **CE-017-06 · el error 20** (RF-017-20): una pista de eje recto de 200 m con la sección de 11,5 m (calzada 10,5 m, arcén 0 m, caballón 1 m) tiene una
  huella de 200 m ± 1 celda a lo largo del eje —no los 211,5 m de un *buffer*—, y su calzada, su arcén y su caballón son, a ≤ 10⁻⁹ m, los del cálculo a mano
  en las mismas celdas (con celdas de 1 m: cinco filas de calzada por lado y una de caballón; con celdas de 0,5 m, las celdas cuyo centro cae **justo en el
  borde** del ancho, a 5,25 y a 6,25 m, cuentan).
- **CE-017-06 · los lados** (RF-017-20, D-12): con cotas iguales a ambos lados, el caballón a la derecha en el sentido de la marcha; con una pendiente
  transversal, el arcén en el lado de mayor cota (al pie del talud).
"""

from __future__ import annotations

import unittest
from typing import Any

import numpy as np

from tests.support import road_data as rd
from tests.support.package import import_geoblender

road_axis = import_geoblender("design.road_axis")
road_section = import_geoblender("design.road_section")

TOL = rd.SECTION_CHECK_TOL_M
"""Metros: RF-017-20 pide la sección a ≤ 10⁻⁹ m del cálculo a mano en las mismas celdas."""
PROFILE = rd.PROFILE
"""El perfil de referencia: calzada 10,5 m, arcén 0 m, caballón 1 m (la sección de 11,5 m de CE-017-06)."""
WITH_SHOULDER = rd.profile_with(shoulder_m=1.5)
"""El mismo con un arcén de 1,5 m (para ver el lado del arcén y el del caballón a la vez)."""


def level(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.full(np.shape(x), 150.0)


def cross(pct: float) -> Any:
    """El plano de la rampa del 4 % con ``pct`` % de pendiente transversal al norte (la izquierda de la marcha hacia el este)."""
    return lambda x, y: rd.RAMP_Z0_M + rd.RAMP_SLOPE_PCT / 100.0 * x + pct / 100.0 * (y - rd.RAMP_AXIS_Y_M)


def section(profile: Any, z_of: Any, step_m: float) -> tuple[Any, Any, Any]:
    """La sección del eje de la rampa (de (100, 200) a (300, 200)) con ``profile`` sobre el terreno ``z_of`` en una rejilla de ``step_m`` m, el cálculo
    a mano en las mismas celdas y la rejilla."""
    grid = rd.grid_of(step_m)
    axis = road_axis.axis_of(rd.absolute((rd.RAMP_ORIGIN, rd.RAMP_DESTINATION)), profile.curve_radius_m, profile.min_radius_m, profile.station_step_m)
    found = road_section.section_cells(axis, profile.carriageway_m, profile.shoulder_m, profile.berm_m, z_of(*rd.local_centers(grid)), grid, None)
    by_hand = rd.straight_section_by_hand(grid, z_of, profile.carriageway_m, profile.shoulder_m, profile.berm_m)
    window = found.window
    return found, rd.SectionByHand(by_hand.kind[window], by_hand.side[window], by_hand.sigma[window], by_hand.lateral[window]), grid


class StraightSectionTest(unittest.TestCase):
    def assert_by_hand(self, found: Any, by_hand: Any) -> None:
        np.testing.assert_array_equal(found.kind, by_hand.kind)
        np.testing.assert_array_equal(found.side, by_hand.side)
        np.testing.assert_allclose(found.sigma, by_hand.sigma, rtol=0.0, atol=TOL, equal_nan=True)
        np.testing.assert_allclose(found.lateral, by_hand.lateral, rtol=0.0, atol=TOL, equal_nan=True)

    def test_ce_017_06_the_footprint_of_a_200_m_axis_is_200_m_and_its_cells_are_the_hand_calculation(self) -> None:
        """CE-017-06 (error 20), RF-017-20: una pista de eje recto de 200 m con la sección de 11,5 m (celdas de 1 m) tiene una huella de 200 m ± 1 celda a lo
        largo del eje y no los 211,5 m de un *buffer*; la calzada (cinco filas por lado, ``ramp_calzada_by_hand``: 2 × 5 × 200 = 2.000 celdas), el arcén (0
        celdas: 0 m de ancho) y el caballón (una fila de 200 celdas) son, a ≤ 10⁻⁹ m, los del cálculo a mano en las mismas celdas."""
        found, by_hand, grid = section(PROFILE, level, 1.0)
        hand = rd.ramp_calzada_by_hand(1.0)
        self.assertLessEqual(abs(found.length_m - rd.RAMP_LENGTH_M), grid.dx)
        self.assertGreater(abs(found.length_m - 211.5), 10.0)
        self.assertEqual(found.count_of(road_section.SectionClass.CARRIAGEWAY), 2 * hand.rows_per_side * hand.columns)
        self.assertEqual(found.count_of(road_section.SectionClass.SHOULDER), 0)
        self.assertEqual(found.count_of(road_section.SectionClass.BERM), hand.columns)
        self.assert_by_hand(found, by_hand)

    def test_ce_017_06_cells_at_exactly_the_edge_of_a_width_are_inside(self) -> None:
        """CE-017-06, RF-017-20: con celdas de 0,5 m, los centros de las filas caen justo en 5,25 m (el borde de la calzada) y en 6,25 m (el del caballón):
        «|d| ≤ ancho» las cuenta (22 filas de calzada, 2 de caballón, de 400 columnas), y son las del cálculo a mano, con la huella de 200 m ± 1 celda."""
        found, by_hand, grid = section(PROFILE, level, 0.5)
        self.assertLessEqual(abs(found.length_m - rd.RAMP_LENGTH_M), grid.dx)
        self.assertEqual(found.count_of(road_section.SectionClass.CARRIAGEWAY), 22 * 400)
        self.assertEqual(found.count_of(road_section.SectionClass.BERM), 2 * 400)
        self.assertAlmostEqual(float(found.lateral[found.cells].max()), 6.25, delta=TOL)
        self.assertAlmostEqual(float(found.lateral[found.cells].min()), -5.25, delta=TOL)
        self.assertAlmostEqual(found.area_m2, (22 + 2) * 400 * 0.25, delta=TOL)  # cada celda, 0,25 m²: 2.400 m² en vez de los 9.600 de contar celdas
        self.assert_by_hand(found, by_hand)

    def test_ce_017_06_with_equal_heights_the_berm_is_on_the_right_in_the_direction_of_travel(self) -> None:
        """CE-017-06, RF-017-20, D-12: con cotas iguales a ambos lados, el caballón a la derecha en el sentido de la marcha (hacia el este, el sur): la fila
        de centros a 5,5 m al sur del eje, y ninguna a la izquierda; con un arcén de 1,5 m, este va a la izquierda."""
        for profile, shoulder_cells in ((PROFILE, 0), (WITH_SHOULDER, 400)):
            with self.subTest(arcen_m=profile.shoulder_m):
                found, by_hand, _ = section(profile, level, 1.0)
                berm = found.kind == road_section.SectionClass.BERM
                self.assertEqual(int(berm.sum()), 200)
                self.assertTrue(bool((found.side[berm] == road_section.RIGHT).all()))
                np.testing.assert_allclose(found.lateral[berm], 5.5, rtol=0.0, atol=TOL)
                shoulder = found.kind == road_section.SectionClass.SHOULDER
                self.assertEqual(int(shoulder.sum()), shoulder_cells)
                self.assertTrue(bool((found.side[shoulder] == road_section.LEFT).all()))
                self.assert_by_hand(found, by_hand)

    def test_ce_017_06_with_a_cross_slope_the_shoulder_is_on_the_higher_side(self) -> None:
        """CE-017-06, RF-017-20, D-12: sobre la rampa del 4 % con el 20 % de pendiente transversal, el arcén (1,5 m) en el lado de mayor cota del terreno
        de partida (el norte, a la izquierda en la marcha hacia el este) y el caballón en el otro; con la pendiente al revés, al contrario; y son, a ≤ 10⁻⁹ m, las
        celdas del cálculo a mano."""
        for pct, shoulder_side, berm_side in ((rd.RAMP_CROSS_PCT, road_section.LEFT, road_section.RIGHT),
                                              (-rd.RAMP_CROSS_PCT, road_section.RIGHT, road_section.LEFT)):
            with self.subTest(cross_pct=pct):
                found, by_hand, _ = section(WITH_SHOULDER, cross(pct), 1.0)
                shoulder = found.kind == road_section.SectionClass.SHOULDER
                berm = found.kind == road_section.SectionClass.BERM
                self.assertEqual((int(shoulder.sum()), int(berm.sum())), (400, 200))
                self.assertTrue(bool((found.side[shoulder] == shoulder_side).all()))
                self.assertTrue(bool((found.side[berm] == berm_side).all()))
                self.assert_by_hand(found, by_hand)

    def test_ce_017_06_the_carriageway_cells_of_the_ramp_are_those_of_the_cut_and_fill_hand_calculation(self) -> None:
        """CE-017-06, RF-017-20 (lo que usa la parte de la sección de CE-017-01): sobre la rampa con el 20 % de pendiente transversal, la calzada tiene
        ``rows_per_side`` filas por lado y ``columns`` columnas (``ramp_calzada_by_hand``) y cada celda a ``(k + ½)·h`` del eje se aparta
        ``cross·(k + ½)·h`` m del plano del eje, de modo que ``cross·h·n²/2`` m por columna al norte y lo mismo al sur salen de las distancias laterales."""
        found, _, grid = section(PROFILE, cross(rd.RAMP_CROSS_PCT), 1.0)
        hand = rd.ramp_calzada_by_hand(1.0, rd.RAMP_CROSS_PCT)
        carriageway = found.kind == road_section.SectionClass.CARRIAGEWAY
        self.assertEqual(int(carriageway.sum()), 2 * hand.rows_per_side * hand.columns)
        # el desvío del terreno respecto de su plano a lo largo del eje es cross·|d|: su suma por lado, la de la mano
        offset = rd.RAMP_CROSS_PCT / 100.0 * np.abs(found.lateral[carriageway])
        north = offset[found.side[carriageway] == road_section.LEFT].sum() * grid.cell_area
        south = offset[found.side[carriageway] == road_section.RIGHT].sum() * grid.cell_area
        self.assertAlmostEqual(float(north), hand.cut_m3, delta=1e-6)
        self.assertAlmostEqual(float(south), hand.fill_m3, delta=1e-6)


if __name__ == "__main__":
    unittest.main()
