# SPDX-License-Identifier: GPL-3.0-or-later
"""Caso de referencia del grabado de la pista: la parte de la sección de CE-017-01 (spec 017, T13; HU-017-1; RF-017-21 y 23; CE-017-01 y CE-017-09; plan 017 §5.4 A8):
la rampa recta de 200 m, con la sección de 11,5 m (calzada de 10,5 m, arcén 0 m, caballón 1 m), contra el **cálculo a mano en las mismas celdas**.

Verifica **de forma independiente** lo que hace ``design.road_engrave``: el corte y el relleno de la calzada y del caballón salen de contar a mano las filas de
centros de celda que caen en cada ancho (``tests.support.road_data.ramp_calzada_by_hand``: ``cross · n² · h² · L / 2`` m³) y de sumar su apartamiento del plano,
**no** de llamar al código bajo prueba. Todo es sintético, en el dominio y sin Blender.

- **CE-017-01 · la sección con el 20 % transversal** (RF-017-21): sobre el plano del 4 % con una pendiente transversal del 20 %, con la rasante en el terreno del eje,
  el corte y el relleno de la calzada son los del cálculo a mano (500 m³ cada uno con celdas de 1 m) a ≤ 10⁻⁹ relativo, con celdas de 2 m, de 1 m y de 0,5 m; y los
  de la sección entera suman el caballón del lado bajo (celdas cuyo centro cae a más de 5,25 m y a ≤ 6,25 m del eje).
- **CE-017-01 · el movimiento 0** (RF-017-21): sin pendiente transversal la rasante es el terreno: la superficie no cambia ni un bit y los volúmenes son 0.
- **CE-017-09 · la cubicación** (RF-017-23): el corte y el relleno que da el grabado (sección y borde) son los de restar la superficie de partida y la resultante celda a
  celda, que es lo que da la cubicación de la 011 entre las dos.
"""

from __future__ import annotations

import functools
import unittest
from typing import Any

import numpy as np

from tests.support import road_data as rd
from tests.support.package import import_geoblender

params = import_geoblender("design.params")
road_axis = import_geoblender("design.road_axis")
road_engrave = import_geoblender("design.road_engrave")
road_section = import_geoblender("design.road_section")

TOL = 1e-9
"""RF-017-21 y 23: el corte y el relleno, a ≤ 10⁻⁹ relativo del cálculo a mano en las mismas celdas."""
PROFILE = rd.profile_with(reach_m=12.5)
"""El perfil de referencia (calzada 10,5 m, arcén 0 m, caballón 1 m) con un alcance de 12,5 m: la ventana de trabajo de la rampa de 200 m es de unos 10.000 celdas."""
PROJECT = {params.TOLERANCE_FACE: 1.0, params.VERIFY_MIN_THICKNESS: 0.05, params.EDGE_MAX_STEP: 1.0, params.EDGE_MIN_SHARE: 99.0}


@functools.lru_cache(maxsize=None)
def ramp(step_m: float, cross_pct: float) -> tuple[Any, Any, Any, Any]:
    """La rampa de CE-017-01 (de (100, 200) a (300, 200) locales) grabada en una rejilla de ``step_m`` m con la rasante en el terreno del eje: el terreno, el trabajo, la
    sección y lo grabado (de solo lectura: una vez por rejilla y pendiente; ``ramp.__wrapped__`` lo calcula de nuevo)."""
    grid = rd.grid_of(step_m)
    terrain = rd.ramp_terrain(grid, cross_pct=cross_pct)
    line = rd.absolute((rd.RAMP_ORIGIN, rd.RAMP_DESTINATION), grid)
    axis = road_axis.axis_of(line, PROFILE.curve_radius_m, PROFILE.min_radius_m, PROFILE.station_step_m)
    window = road_engrave.engrave_window(axis, rd.road_profile(PROFILE), grid)
    section = road_section.section_cells(axis, PROFILE.carriageway_m, PROFILE.shoulder_m, PROFILE.berm_m, terrain, grid, window)
    on_axis = road_section.sample_terrain(terrain, grid, axis.points[:, 0], axis.points[:, 1])
    job = rd.axis_job(grid, terrain, line, profile=PROFILE)
    return terrain, job, section, road_engrave.engrave(job, section, section.levels(axis.stations, on_axis), PROJECT)


def berm_rows_by_hand(step_m: float) -> list[float]:
    """Las distancias al eje (m) de las filas de centros de celda del lado del caballón (a ``(k + ½)·h``): las que pasan de la semianchura de la calzada (5,25 m) y no
    de la de la sección por ese lado (6,25 m); una celda cuyo centro cae justo en el borde cuenta."""
    centres = [(k + 0.5) * step_m for k in range(int(8.0 / step_m))]
    return [d for d in centres if 5.25 + 1e-9 < d <= 6.25 + 1e-9]


class RampSectionTest(unittest.TestCase):
    def test_the_carriageway_cut_and_fill_of_ce_017_01_are_those_of_the_cells_by_hand(self) -> None:
        """RF-017-21, CE-017-01: sobre el plano del 4 % con el 20 % transversal, la calzada de 10,5 m de la rampa de 200 m da 500 m³ de corte (al norte) y 500 m³ de
        relleno (al sur) con celdas de 1 m, y los del cálculo a mano en las mismas celdas con las de 2 m y las de 0,5 m, a ≤ 10⁻⁹ relativo."""
        for step in (1.0, 2.0, 0.5):
            with self.subTest(step_m=step):
                terrain, _job, section, found = ramp(step, rd.RAMP_CROSS_PCT)
                by_hand = rd.ramp_calzada_by_hand(step_m=step)
                grid = rd.grid_of(step)
                start = terrain[found.window]
                drop = start - found.applied
                calzada = section.kind == int(road_section.SectionClass.CARRIAGEWAY)
                self.assertEqual(int(calzada.sum()), 2 * by_hand.rows_per_side * by_hand.columns)
                np.testing.assert_allclose(float(np.maximum(drop[calzada], 0.0).sum()) * grid.cell_area, by_hand.cut_m3, rtol=TOL)
                np.testing.assert_allclose(float(np.maximum(-drop[calzada], 0.0).sum()) * grid.cell_area, by_hand.fill_m3, rtol=TOL)
                if step == 1.0:
                    self.assertAlmostEqual(by_hand.cut_m3, 500.0, delta=TOL)
                self.assertEqual(found.off_level, (), "las celdas de la calzada quedan todas en su rasante")

    def test_the_whole_section_adds_the_berm_of_the_low_side(self) -> None:
        """RF-017-21, RF-017-20, CE-017-01: el corte de la sección es el de la calzada (el arcén es de 0 m) y su relleno, el de la calzada más las filas del caballón del
        lado bajo (a 5,25 m < d ≤ 6,25 m del eje), cada celda a su apartamiento del plano (``0,2 · d``): con celdas de 1 m, 500 + 200 · 0,2 · 5,5 = 720 m³."""
        for step in (1.0, 2.0, 0.5):
            with self.subTest(step_m=step):
                _terrain, _job, _section, found = ramp(step, rd.RAMP_CROSS_PCT)
                by_hand = rd.ramp_calzada_by_hand(step_m=step)
                berm = sum(0.2 * d for d in berm_rows_by_hand(step)) * step * step * by_hand.columns
                np.testing.assert_allclose(found.section_cut_m3, by_hand.cut_m3, rtol=TOL)
                np.testing.assert_allclose(found.section_fill_m3, by_hand.fill_m3 + berm, rtol=TOL)
                if step == 1.0:
                    self.assertAlmostEqual(found.section_fill_m3, 720.0, delta=TOL)

    def test_without_a_cross_slope_the_gradient_is_the_terrain_and_nothing_moves(self) -> None:
        """RF-017-21, CE-017-01: sobre el plano del 4 % sin pendiente transversal, su rasante es el terreno (movimiento 0 m): la superficie es la de partida bit a bit,
        el corte, el relleno, el borde y las alturas son 0 y no hay grupos."""
        terrain, _job, _section, found = ramp(1.0, 0.0)
        np.testing.assert_array_equal(found.surface, terrain[found.window])
        self.assertEqual((found.cut_m3, found.fill_m3, found.cut_height_max_m, found.fill_height_max_m), (0.0, 0.0, 0.0, 0.0))
        self.assertEqual(int(found.changed.sum()), 0)
        self.assertEqual(found.off_level, ())
        self.assertFalse(found.needs_confirmation)

    def test_the_cubication_between_the_start_and_the_result_is_the_cut_and_fill_of_the_figures(self) -> None:
        """RF-017-23, CE-017-09: el corte y el relleno que da el grabado (sección y borde juntos) son los de restar la superficie de partida y la resultante celda a celda
        por el área de la celda, a ≤ 10⁻⁹ relativo: lo que dará la cubicación de la 011 entre las dos."""
        terrain, _job, _section, found = ramp(1.0, rd.RAMP_CROSS_PCT)
        drop = terrain[found.window] - found.surface
        np.testing.assert_allclose(found.cut_m3, np.maximum(drop, 0.0).sum(), rtol=TOL)
        np.testing.assert_allclose(found.fill_m3, np.maximum(-drop, 0.0).sum(), rtol=TOL)
        np.testing.assert_allclose(found.net_m3, found.cut_m3 - found.fill_m3, rtol=TOL)
        self.assertGreater(found.edge_cut_m3 + found.edge_fill_m3, 0.0)

    def test_the_same_input_gives_the_same_engraving_bit_by_bit(self) -> None:
        """RF-015-02 (reproducible), RF-017-21: el mismo trabajo, la misma sección y la misma rasante dan la misma superficie bit a bit y las mismas cifras."""
        _t1, _j1, _s1, first = ramp.__wrapped__(1.0, rd.RAMP_CROSS_PCT)
        _t2, _j2, _s2, second = ramp.__wrapped__(1.0, rd.RAMP_CROSS_PCT)
        np.testing.assert_array_equal(first.surface, second.surface)
        self.assertEqual(first.figure_values(), second.figure_values())


if __name__ == "__main__":
    unittest.main()
