# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_ref_roads» (spec 017, T14, hito H1; RF-017-02, 09 a 23; CE-017-01, 03 y E1; RNF-017-09; plan 017 §7.1 y §7.4): lo que pasa de 1 s o monta la fuerza bruta del grabado sobre
una pista de 200 m, y no entra en el «verde» (``tools/check.py``). El «verde» deja en ``tests/referencia/des/test_ref_roads`` la cadena entera en pequeño (cada CE con su cálculo a mano y E1 en una malla de 8 m
de la ruta); esto lo ejecuta el paso «hito» de ``tools/check.py --completo`` (la publicación lo pide siempre).

- **E1 con la ruta de la rejilla de 2 m** (RF-017-09 a 23; plan §7.3): la cantera con el fondo de 175 m de la 014, el corredor del 8 % con una esquina y el borde a 15 m sobre ella, con la malla de la ruta
  de **4 m** y la holgura de 60 m (la ruta busca ≈ 2 s: la red 2D, el A\\* de ≈ 220.000 estados y el pasillo), el perfil de referencia con su alcance de 60 m y la métrica exacta: el eje (con las dos curvas
  que bajan de R = 20 m a 16,6 m con su aviso: los tramos no las dejan caber), la rasante, la sección y el grabado son los del cálculo a mano en las mismas celdas (≤ 10⁻⁹), la misma entrada da la
  misma pista bit a bit y todo, de la ruta al grabado, tarda ≤ 20 s.
- **La fuerza bruta del grabado en las pistas de 200 m** (RF-017-20, 21; CE-017-01, CE-017-03): la rampa con el 20 % transversal y el arcén de 1,5 m, la rampa sin pendiente transversal, el escalón y la línea
  3D irregular, con la sección contrastada con ``road_data.oracle_section`` y el grabado con ``road_data.hand_engrave`` (un bucle por celda y la envolvente de todas las semillas, O(semillas × celdas)) en las
  mismas celdas: ≈ 0,4 s cada una, por eso no están en el «verde».
- **La rampa a una cota con la holgura de 60 m** (E4; RF-017-02, 10): la ruta de la rampa por los bancos con el pasillo de 60 m (≈ 1 s, 100.000 estados) y la misma pista bit a bit.
"""

from __future__ import annotations

import dataclasses
import time
import unittest

import numpy as np

from tests.referencia.des import test_ref_roads as h1
from tests.support import road_data as rd

TOTAL_LIMIT_S = 20.0
"""Lo que puede tardar la pista de E1 entera, de la ruta al grabado, con la malla de 4 m y la holgura de 60 m (medido: ≈ 1,9 s; la spec pide ≤ 60 s la ruta de 1,5 km, RNF-017-02, y ≤ 10 s el grabado de 2 km)."""


class FullE1Test(unittest.TestCase):
    """E1 con la malla de la ruta de 4 m en la rejilla de 2 m (la cantera se construye una vez por clase)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.job = h1.e1_job(2.0, 4.0, 4.0, rd.PROFILE)
        started = time.perf_counter()
        cls.road = h1.compose(cls.job)
        cls.elapsed_s = time.perf_counter() - started

    def test_the_road_down_the_trench_is_the_hand_calculation(self) -> None:
        """RF-017-09 a 18, 20 a 23, E1: la ruta baja del borde por el corredor (el movimiento de tierras en sus nodos no pasa de un paso de cota: 0,28 m), y el eje (con **dos curvas cuyo radio baja de
        20 m al que cabe** y sus avisos: RF-017-14), la rasante (de 190 a 175 m), la sección (con el alcance de 60 m) y el grabado (la métrica exacta) son los del cálculo a mano en las mismas celdas, ≤ 10⁻⁹:
        el eje desde sus vértices con las fórmulas cerradas y la regla de los radios, la rasante con el oráculo O(n²), la sección con la fuerza bruta y el grabado con un bucle por celda y la envolvente de
        todas las semillas."""
        road = self.road
        h1.verify(self, road)
        route = road.route
        terrain = route.mesh.z[tuple(np.array(route.nodes).T)]
        self.assertLessEqual(float(np.abs(route.levels_m - terrain).max()), self.job.route.level_step_m + 1e-9)
        self.assertGreaterEqual(road.axis.curve_count, 2)
        notices = road.axis.notices(h1.ENTITY)
        self.assertGreaterEqual(len(notices), 1)
        self.assertTrue(all(item.code == "des.road_radius_reduced" for item in notices))
        self.assertGreaterEqual(road.axis.min_radius_m, self.job.profile.min_radius_m)
        self.assertLess(road.axis.min_radius_m, self.job.profile.curve_radius_m)
        self.assertEqual((road.found.off_level, road.found.needs_confirmation), ((), False))

    def test_the_figures_are_the_hand_figures_and_fit_the_twenty_three(self) -> None:
        """RF-017-23, E1: las veintitrés cifras: de 190 a 175 m (−15 m), el eje de más de 150 m (``H/pd``) y de la recta, la pendiente máxima ≤ pd y la media el desnivel entre la longitud (Σ|Δcota| = 15 m,
        la rasante solo baja), el radio mínimo (el reducido), las anchuras del perfil y el corte y el relleno de la sección y del borde, con el neto como su diferencia, todas aceptadas por ``road_figures``."""
        figures = self.road.figures()
        self.assertEqual((figures["des.road_z_start_m"], figures["des.road_z_end_m"]), (190.0, 175.0))
        self.assertAlmostEqual(figures["des.road_drop_m"], -15.0, delta=h1.TOL)
        self.assertGreater(figures["des.road_length_m"], max(rd.needed_length_m(h1.E1_DROP_M, 10.0), 160.0))
        self.assertLessEqual(figures["des.road_gradient_max_pct"], 10.0 + 1e-7)
        self.assertAlmostEqual(figures["des.road_gradient_mean_pct"], 15.0 / figures["des.road_length_m"] * 100.0, delta=1e-7)
        self.assertEqual((figures["des.road_width_m"], figures["des.road_section_m"]), (10.5, 11.5))
        self.assertAlmostEqual(figures["des.road_net_m3"], self.road.found.cut_m3 - self.road.found.fill_m3, delta=1e-6)
        self.assertEqual(len(figures), 23)

    def test_the_same_input_gives_the_same_road_bit_by_bit_and_the_inputs_are_not_modified(self) -> None:
        """RF-015-02, RF-017-10, principio 7, E1: la misma entrada con los mismos parámetros da la misma pista bit a bit (la ruta de 220.000 estados, el eje, la rasante, la sección, lo grabado y las
        veintitrés cifras) y ni la superficie de partida ni las máscaras cambian."""
        before = h1.digest(self.job.start, self.job.cut_allowed, self.job.fill_allowed, self.job.untouchable)
        again = h1.compose(h1.e1_job(2.0, 4.0, 4.0, rd.PROFILE))
        self.assertEqual(h1.fingerprint(again), h1.fingerprint(self.road))
        self.assertEqual(h1.digest(self.job.start, self.job.cut_allowed, self.job.fill_allowed, self.job.untouchable), before)

    def test_the_whole_chain_takes_at_most_20_seconds(self) -> None:
        """RNF-017-02, RNF-017-04 (la cadena, de la ruta al grabado, en el dominio y sin proyecto): la pista de E1 con la malla de 4 m tarda ≤ 20 s (medido ≈ 1,9 s, de ellos ≈ 1,85 s la ruta)."""
        self.assertLessEqual(self.elapsed_s, TOTAL_LIMIT_S)


class BruteForceTest(unittest.TestCase):
    """La sección y el grabado de las pistas de 200 m contra la fuerza bruta."""

    def test_the_ramp_with_a_cross_slope_and_a_shoulder_is_the_brute_force_one_in_the_same_cells(self) -> None:
        """RF-017-20, 21, CE-017-01, CE-017-06: con una pendiente transversal del 20 % y el arcén de 1,5 m, la sección (clases, lados, abscisa) y el grabado (la superficie, lo que mueve el borde, el corte y
        el relleno de la sección y del borde) son los de la fuerza bruta en las mismas celdas, ≤ 10⁻⁹: el arcén va al lado de mayor cota (el norte)."""
        road = h1.ramp(rd.RAMP_CROSS_PCT, 1.5)
        h1.verify(self, road)
        shoulder = road.section.kind == h1.road_section.SectionClass.SHOULDER
        self.assertTrue(bool((road.section.side[shoulder] == h1.road_section.LEFT).all()))
        self.assertEqual(int(shoulder.sum()), 400)

    def test_the_ramp_without_a_cross_slope_is_the_brute_force_one_and_moves_nothing(self) -> None:
        """RF-017-20, 21, CE-017-01: la rampa de 200 m sin pendiente transversal (la rasante es el terreno) es la de la fuerza bruta en las mismas celdas, y no mueve nada."""
        road = h1.ramp(0.0)
        h1.verify(self, road)
        self.assertLessEqual(road.found.cut_m3 + road.found.fill_m3, h1.TOL)

    def test_the_restricted_ramps_are_the_brute_force_ones_with_their_groups_and_causes(self) -> None:
        """RF-017-06, 21, 22, CE-017-01: la rampa del 20 % transversal con un corte que no se admite en una caja, con un intocable al que llega la calzada y con una altura máxima de 0,5 m es, de la sección al grabado, la de la fuerza bruta en las
        mismas celdas: las celdas de la calzada que no quedan en su rasante, por causa (``hand_engrave``: un bucle por celda), el corte, el relleno y el borde, que sale solo de las semillas que sí están."""
        for kind in ("mask", "untouchable", "height"):
            with self.subTest(restriction=kind):
                road = h1.restricted_ramp(kind)
                h1.verify(self, road)
                self.assertTrue(road.found.needs_confirmation)

    def test_the_step_and_the_irregular_3d_axis_are_the_brute_force_ones(self) -> None:
        """RF-017-15, 18, 20, 21, CE-017-03: el escalón de 6 m (el borde sube y baja con la rasante de rampa) y la línea 3D irregular (la Z como rasante) son, de la sección al grabado, los de la fuerza
        bruta en las mismas celdas."""
        h1.verify(self, h1.compose(h1.step_job(rd.STEP_AXIS)))
        grid = rd.GRID
        job = h1.axis_3d_job(grid, rd.ramp_terrain(grid), rd.axis_3d_irregular())
        h1.verify(self, h1.compose(job))


class LevelRampTest(unittest.TestCase):
    """La rampa a una cota con la holgura de 60 m (E4, sin la accesibilidad)."""

    def test_the_ramp_with_the_default_corridor_is_the_hand_calculation_and_the_same_bit_by_bit(self) -> None:
        """RF-017-02, 10, 15, 20, 21, D-4, E4: la ruta de la rampa por los bancos con la holgura de 60 m (de la referencia: unos 100.000 estados) termina en la zona a la cota pedida y es, del eje al grabado,
        la del cálculo a mano en las mismas celdas; y la misma entrada da la misma pista bit a bit."""
        job = h1.level_job()
        wide = dataclasses.replace(job, route=dataclasses.replace(job.route, margin_m=60.0))
        road = h1.compose(wide)
        h1.verify(self, road)
        self.assertEqual((road.arrival.requested_m, road.arrival.within_tolerance, float(road.z[-1])), (h1.LEVEL_M, True, h1.LEVEL_M))
        self.assertEqual(h1.fingerprint(h1.compose(wide)), h1.fingerprint(road))


if __name__ == "__main__":
    unittest.main()
