# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_road_route» (spec 017, T07; RF-017-10, RF-017-12; RNF-017-02, 06 y 07; plan 017 §7.3 y §7.4): lo que pasa de 1 s
y no entra en el «verde» (``tools/check.py``, RNF-017-09). El «verde» deja en ``test_road_route`` lo que cubre cada RF (en mallas de ≤ 40 × 40
nodos); esto lo ejecuta el paso «hito» de ``tools/check.py --completo`` (la publicación lo pide siempre).

- **La ruta de 1,5 km del barranco, a escala** (RNF-017-02, RNF-017-06; plan §7.3): la malla de 4 m de la rejilla de 2,81 M celdas
  (425 × 414 = 175.950 nodos, 16 rumbos), con el barranco de 14 m a medio camino, la altura máxima de 14 m, el paso de cota de 0,28 m, λ = 2 1/m
  y los 16 rumbos, con holguras de 2 y de 4 m (los pasillos de 1.120 y 1.860 nodos del plan: 90.776 y 203.810 estados expandidos, 0,61 s y
  2,10 s en el prototipo): la ruta existe, cumple cada condición de RF-017-10 (recalculada, ``test_road_route.verify``), tarda ≤ 10 s
  (la spec pide ≤ 90 s para cualquier pasillo) y cada llamada del paso ≤ 0,2 s.
- **El presupuesto, a escala** (RF-017-12, P-3): con 50.000 estados expandidos de presupuesto la búsqueda de la holgura de 8 m (unos
  600.000 estados necesarios) se detiene exactamente ahí, sin ruta y con la causa del presupuesto (**no** «no hay ruta»).

La ladera del 38 % y los pasillos de 8 a 60 m de holgura (de 36 a 96 s y de 0,7 a 1,2 GB, sin y con presupuesto) los mide la T34
(``tests/rendimiento/des``).
"""

from __future__ import annotations

import dataclasses
import time
import unittest
from typing import Any

import numpy as np

from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.support.timing import drive_steps, least_of
from tests.unit.design import test_road_route as base

road_route = import_geoblender("design.road_route")
road_model = import_geoblender("design.road_model")

RUN_LIMIT_S = 10.0
"""Lo que puede tardar la búsqueda de estas holguras (medido: 0,4 y 1,1 s; la spec pide ≤ 90 s para cualquier pasillo, RNF-017-02)."""
STEP_LIMIT_S = 0.2
"""Lo que dura una llamada del paso como mucho (RNF-017-06)."""


class ScaleTest(unittest.TestCase):
    """El barranco de la rejilla de 2,81 M celdas (construido una vez por clase)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = rd.scale_grid()
        cls.surface = rd.scale_ravine_terrain()
        spec = rd.scale_ravine_spec()
        cls.origin = tuple(float(v) for v in rd.absolute([spec.origin], cls.grid)[0])
        cls.destination = tuple(float(v) for v in rd.absolute([spec.destination], cls.grid)[0])

    def prepare(self, margin_m: float, budget: int = rd.ROUTE.search_budget) -> tuple[Any, Any, Any]:
        route = dataclasses.replace(rd.ROUTE, margin_m=margin_m, search_budget=budget)
        job = rd.route_job(self.grid, self.surface, self.origin, self.destination, route=route)
        mesh, corridor = rd.route_corridor(job)
        return job, mesh, corridor

    def test_the_route_of_1500_m_over_the_ravine_with_a_narrow_margin(self) -> None:
        """RF-017-10, RNF-017-02, RNF-017-06: la ruta de 1,5 km sobre el barranco de 14 m con holguras de 2 y de 4 m existe, cumple cada
        condición (pendiente de cada paso ≤ 10 %, rumbo a lo sumo al contiguo, ``|cota − terreno| ≤ 14 m``, nodos que se pisan), tarda ≤ 10 s
        (medido: 0,4 y 1,1 s) y cada llamada del paso, ≤ 0,2 s; los estados expandidos son los del plan (90.776 y 203.810 con su terreno:
        aquí, ±25 %), y no pasa de la cota inferior de la red 2D más que lo que cuestan el desvío vertical y los giros."""
        for margin_m, expected in ((2.0, 90_776), (4.0, 203_810)):
            job, mesh, corridor = self.prepare(margin_m)
            started = time.perf_counter()
            run = drive_steps(road_route.route_steps(job, corridor))
            elapsed = time.perf_counter() - started
            route = run.result
            with self.subTest(margin_m=margin_m):
                base.verify(self, job, mesh, route)
                self.assertLessEqual(elapsed, RUN_LIMIT_S)
                longest = run.longest_s  # con la máquina cargada, se mide otra vez (la medida es del código, no de los demás procesos)
                if longest > STEP_LIMIT_S:
                    longest = least_of(lambda: drive_steps(road_route.route_steps(job, corridor)).longest_s, STEP_LIMIT_S, attempts=1,
                                       max_attempts=3)
                self.assertLessEqual(longest, STEP_LIMIT_S)
                self.assertGreater(run.steps, 5)
                self.assertGreater(route.expanded, 0.75 * expected)
                self.assertLess(route.expanded, 1.25 * expected)
                self.assertEqual((route.nodes[0], route.nodes[-1]), (mesh.node_of(*self.origin), mesh.node_of(*self.destination)))
                self.assertGreaterEqual(route.cost + 1e-9, corridor.lower_bound_m)
                self.assertLess(route.cost, 2.0 * corridor.lower_bound_m)  # una ruta de 1,5 km con 14 m de barranco: ≈ 1,4 × la recta

    def test_the_budget_stops_a_search_at_scale(self) -> None:
        """RF-017-12, RF-017-10 (P-3): con un presupuesto de 50.000 estados expandidos, la búsqueda de la holgura de 8 m (unos 600.000
        necesarios) se detiene en 50.000 con la causa del presupuesto y sin ruta, en ≤ 2 s (medido: 0,3 s)."""
        job, _mesh, corridor = self.prepare(8.0, budget=50_000)
        started = time.perf_counter()
        route = drive_steps(road_route.route_steps(job, corridor)).result
        self.assertLessEqual(time.perf_counter() - started, 2.0)
        self.assertFalse(route.ok)
        self.assertEqual(route.cause, road_model.NoRouteCause.BUDGET)
        self.assertEqual((route.expanded, route.nodes, route.budget), (50_000, (), 50_000))
        self.assertGreater(route.seen, 50_000)
        self.assertTrue(np.isfinite(corridor.lower_bound_m))


if __name__ == "__main__":
    unittest.main()
