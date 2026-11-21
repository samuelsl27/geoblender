# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_road_operation» (spec 017, T20 (a); RF-017-23, 02, 10, 12, 17 y E1 y E4; RNF-017-02, RNF-017-06 y RNF-017-09; plan 017 §5.3.2, §7.1 y §7.4): lo que monta la cantera en la
rejilla de 2 m con la malla de la ruta de 4 m, y no entra en el «verde» (``tools/check.py``). El «verde» deja en ``test_road_operation`` los tres modos, las cifras de a mano, los rechazos, los otros
diseños y cerrar a mitad en la rejilla de 2 m de ≤ 200 × 200 celdas; esto lo ejecuta el paso «hito» de ``tools/check.py --completo`` (la publicación lo pide siempre).

- **E1 con la ruta de 218.000 estados** (RF-017-09 a 23; plan §7.3): la pista de la cantera con el fondo de 175 m y el corredor del 8 % con una esquina, con la malla de la ruta de **4 m**, la holgura de 60 m
  y el perfil de referencia con su alcance de 60 m: ``road_compute_steps`` da lo que dan las piezas compuestas a mano (``test_ref_roads.compose``) —la superficie de la ventana, la huella, el eje con sus dos
  curvas que bajan de 20 m, la rasante y las **veintitrés** cifras—, **dice la holgura del pasillo** y los estados expandidos (H-10: con 8 o 16 m la ruta atraviesa la pared del fondo), no cambia ninguna
  entrada, es **la misma bit a bit** con el presupuesto mínimo y por defecto, y **ninguna llamada del hilo pasa de 0,2 s** (RNF-017-06; medido ≈ 0,05 s) con el cálculo entero en ≤ 20 s (≈ 1,9 s).
- **La rampa a una cota** (E4; RF-017-02, 10, D-4, RF-017-17): del terreno de entrada (140 m) a la zona de la berma de 125 m con pd = 20 %: la ruta termina en la zona, la rasante acaba en la cota pedida
  (125 m), el resultado dice el destino alcanzado y que cabe en la tolerancia, y como la media (≈ 13 %) pasa de pm lleva el aviso de la media y ``mean_exceeded``.
"""

from __future__ import annotations

import time
import unittest

import numpy as np

from tests.referencia.des import test_ref_roads as h1
from tests.support import road_data as rd
from tests.unit.design import test_road_operation as base

TOTAL_LIMIT_S = 20.0
"""Lo que puede tardar la pista de E1 entera con la malla de 4 m y la holgura de 60 m (medido ≈ 1,9 s; la spec pide ≤ 60 s la ruta de 1,5 km, RNF-017-02, y ≤ 15 s el grabado de una caja de ≤ 2 M celdas)."""
CALL_LIMIT_S = 0.2
"""RNF-017-06: lo que puede tardar una llamada del hilo (un ``next`` de los pasos)."""


class FullE1Test(unittest.TestCase):
    """E1 con la malla de la ruta de 4 m en la rejilla de 2 m (la cantera se construye una vez por clase)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.job = h1.e1_job(2.0, 4.0, 4.0, rd.PROFILE)
        cls.before = base.digest_of(cls.job)
        started = time.perf_counter()
        cls.steps, cls.outcome, cls.slowest_s = base.run(cls.job)
        cls.elapsed_s = time.perf_counter() - started

    def test_the_outcome_is_the_composition_by_hand_with_the_twenty_three_figures(self) -> None:
        """RF-017-23, RF-017-09 a 21, E1: la superficie de la ventana, la huella, el eje (con **dos curvas cuyo radio baja de 20 m** y sus avisos, RF-017-14), la rasante (de 190 a 175 m) y las veintitrés
        cifras son las de la composición a mano de la T14 (``h1.compose``); la ruta no pasa de un paso de cota sobre el terreno de sus nodos."""
        road = h1.compose(self.job)
        outcome = self.outcome
        self.assertEqual(outcome.window, road.window)
        np.testing.assert_array_equal(outcome.surface, road.found.surface)
        np.testing.assert_array_equal(outcome.footprint, road.found.footprint)
        np.testing.assert_array_equal(outcome.axis.points, road.axis.points)
        np.testing.assert_array_equal(outcome.levels, road.z)
        base.check_figures(self, outcome, road)
        self.assertEqual(len(outcome.figures), 23)
        self.assertEqual((outcome.levels[0], outcome.levels[-1]), (190.0, 175.0))
        self.assertGreaterEqual(outcome.axis.curve_count, 2)
        self.assertEqual([notice.code for notice in outcome.notices[:2]], ["des.road_radius_reduced"] * 2)
        self.assertEqual((outcome.off_level, outcome.mean_exceeded), ((), False))

    def test_the_outcome_says_the_corridor_slack_and_the_states_of_the_search(self) -> None:
        """RF-017-10, RF-017-12, H-10: con la holgura de 60 m el resultado dice la holgura, los nodos del pasillo (1.806), los estados expandidos (≈ 218.000, dentro del presupuesto de 5.000.000) y el destino
        alcanzado: la ruta cambia con la holgura y la persona ha de poder leerlo en el resumen."""
        route = self.outcome.route
        self.assertEqual((route.margin_m, route.mesh_m, route.budget), (60.0, 4.0, 5_000_000))
        self.assertGreater(route.corridor_nodes, 1_000)
        self.assertGreater(route.expanded, 100_000)
        self.assertLess(route.expanded, route.budget)
        destination = self.job.geometry.destination
        self.assertLessEqual(float(np.hypot(route.arrival.x - destination[0], route.arrival.y - destination[1])), route.mesh_m)  # el nodo de llegada es el del punto de destino
        self.assertIsNone(route.arrival.within_tolerance)  # sin cota pedida (la del terreno): nada con que compararla

    def test_the_same_input_gives_the_same_outcome_bit_by_bit_and_the_inputs_are_not_modified(self) -> None:
        """RF-015-02, RF-017-10 (D-23), principio 7: la misma entrada con el presupuesto mínimo da la misma pista bit a bit (la superficie, el eje, la rasante y las veintitrés cifras) y ni la superficie de
        partida ni las máscaras cambian."""
        again = base.last(base.road_store.road_compute_steps(h1.e1_job(2.0, 4.0, 4.0, rd.PROFILE), base.COMMON, budget_s=1e-9))
        self.assertEqual(again.surface.tobytes(), self.outcome.surface.tobytes())
        self.assertEqual((again.axis.points.tobytes(), again.levels.tobytes()), (self.outcome.axis.points.tobytes(), self.outcome.levels.tobytes()))
        self.assertEqual(again.figures, self.outcome.figures)
        self.assertEqual(base.digest_of(self.job), self.before)

    def test_every_call_of_the_thread_takes_at_most_0_2_seconds_and_the_whole_chain_at_most_20(self) -> None:
        """RNF-017-06, RNF-017-02, RNF-017-04, RF-017-30: ninguna llamada del hilo pasa de 0,2 s (medido ≈ 0,05 s: la ruta cede cada ≈ 2.000 estados expandidos) y el cálculo entero, de la ruta al grabado
        y sin proyecto, tarda ≤ 20 s (medido ≈ 1,9 s)."""
        self.assertGreater(len(self.steps), 50)
        self.assertLessEqual(self.slowest_s, CALL_LIMIT_S)
        self.assertLessEqual(self.elapsed_s, TOTAL_LIMIT_S)


class LevelRampTest(unittest.TestCase):
    """La rampa a una cota por los bancos (E4, sin la accesibilidad)."""

    def test_the_ramp_ends_at_the_requested_level_reports_the_arrival_and_warns_of_the_mean(self) -> None:
        """RF-017-02, RF-017-10, RF-017-17, D-4, E4: con un destino por cota (125 m en la zona de la berma, tolerancia 0,5 m) la ruta termina en la zona y la rasante acaba en la cota pedida
        (``des.road_z_end_m`` = 125 m); el resultado dice el destino alcanzado (lugar y cota) y ``within_tolerance``; la pendiente media pasa de pm: aviso y ``mean_exceeded``; y es la composición a mano."""
        job = h1.level_job()
        outcome = base.last(base.road_store.road_compute_steps(job, base.COMMON))
        road = h1.compose(job)
        found = base.values_of(outcome)
        self.assertEqual(found["des.road_z_end_m"], h1.LEVEL_M)
        arrival = outcome.route.arrival
        self.assertEqual((arrival.requested_m, arrival.within_tolerance), (h1.LEVEL_M, True))
        self.assertEqual((arrival.x, arrival.y), (float(road.axis.points[-1, 0]), float(road.axis.points[-1, 1])))
        np.testing.assert_array_equal(outcome.surface, road.found.surface)
        np.testing.assert_array_equal(outcome.levels, road.z)
        base.check_figures(self, outcome, road)
        self.assertTrue(outcome.mean_exceeded)
        self.assertIn("des.road_mean_gradient", [notice.code for notice in outcome.notices])


if __name__ == "__main__":
    unittest.main()
