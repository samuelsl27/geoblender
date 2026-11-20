# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_road_net» (spec 017, T06; RF-017-09, RF-017-11; RNF-017-01 y 06; plan 017 §7.3 y §7.4): lo que pasa de 1 s
y no entra en el «verde» (``tools/check.py``, RNF-017-09). El «verde» deja en ``test_road_net`` lo que cubre cada RF (en mallas de ≤ 200 ×
200 nodos y el oráculo en las de ≤ 24 × 20); esto lo ejecuta el paso «hito» de ``tools/check.py --completo`` (la publicación lo pide siempre).

- **El oráculo, en mallas de 40 × 40 y de 60 × 60 con muros y huecos** (RF-017-09, RF-017-11): la red 2D de ``design.road_net`` igual a la del
  Bellman–Ford de pasadas completas sobre el grafo explícito (``design_oracles.hand_net``), que en 3.600 nodos tarda segundos.
- **La red de la escala** (RNF-017-01, RNF-017-06; plan §7.3): la malla de 4 m de la rejilla de 2,81 M celdas (1.699 × 1.654 celdas de 1 m
  → 425 × 414 = 175.950 nodos, 16 rumbos) en los dos terrenos del plan —un talud del 4 % libre con 14 m de altura, y uno del 38 % con un
  muro con hueco y 2 m de altura—: cada corrida en ≤ 5 s (la spec pide ≤ 10 s por las dos, del origen y del destino; medido: 0,29 s, el
  plan midió 0,35 s con 175.525 nodos), cada paso en ≤ 0,05 s y el pasillo de 60 m de **holgura** de una ruta de 1,5 km con 21.978 a
  31.856 nodos y no los 5.640 de una franja de 60 m de ancho (``docs/trampas.md`` §2).
"""

from __future__ import annotations

import time
import unittest
from typing import Any

import numpy as np

from tests.support import design_oracles as oracles
from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.support.timing import drive_steps, least_of

road_net = import_geoblender("design.road_net")
gis = import_geoblender("gis")

CELL_M = 2.0
RUN_LIMIT_S = 5.0
"""Lo que puede tardar una corrida de la red 2D de 175.950 nodos (RNF-017-01: ≤ 10 s por las dos corridas, la del origen y la del destino)."""
STEP_LIMIT_S = 0.05


def run(steps: Any) -> Any:
    found = None
    for step in steps:
        if step.result is not None:
            found = step.result
    return found


def random_case(seed: int, ni: int, nj: int, factor: int) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    rows, cols = ni * factor, nj * factor
    surface = np.kron(2.0 * rng.random((ni, nj)), np.ones((factor, factor))) + rng.uniform(-0.05, 0.05, (rows, cols))
    surface[rng.random((rows, cols)) < 0.02] = np.nan
    forbidden = np.zeros((rows, cols), dtype=bool)
    for _ in range(6):
        r, c = int(rng.integers(0, rows)), int(rng.integers(0, cols))
        forbidden[r:r + int(rng.integers(1, max(2, rows // 3))), c:c + int(rng.integers(1, 3))] = True
    return {"surface": surface, "forbidden": forbidden}


class LargeOracleTest(unittest.TestCase):
    def test_the_network_is_the_one_of_the_oracle_on_40_by_40_and_60_by_60_nodes_with_walls_and_holes(self) -> None:
        """RF-017-09, RF-017-11, RF-017-06: la red 2D igual a la del Bellman–Ford independiente en mallas de 40 × 40 y de 60 × 60 nodos (con
        bloques de 1 y de 2 celdas), con muros (cajas prohibidas), celdas sin dato y pendientes del 8 y del 12 %: las mismas distancias a
        ≤ 10⁻¹² relativo y los mismos nodos inalcanzables."""
        for seed, ni, nj, factor, pd, hmax in ((51, 40, 40, 1, 0.08, 0.6), (52, 60, 60, 1, 0.12, 0.8), (53, 40, 50, 2, 0.10, 0.5)):
            case = random_case(seed, ni, nj, factor)
            mesh = road_net.route_mesh(gis.Grid(west=500_000.0, north=4_400_000.0, dx=CELL_M, dy=CELL_M, ncols=nj * factor,
                                                nrows=ni * factor), case["surface"], CELL_M * factor, case["forbidden"])
            target = (ni // 2, nj // 2)
            for node in sorted(((i, j) for i in range(ni) for j in range(nj)), key=lambda n: abs(n[0] - ni // 2) + abs(n[1] - nj // 2)):
                if mesh.walkable[node]:
                    target = node
                    break
            with self.subTest(seed=seed, nodes=(ni, nj), factor=factor):
                expected = oracles.hand_net(case["surface"], case["forbidden"], factor, CELL_M, pd, hmax, [target])
                found = run(road_net.network_steps(mesh, target, pd, hmax))
                self.assertTrue(np.array_equal(np.isfinite(found.dist), np.isfinite(expected)))
                np.testing.assert_allclose(found.dist, expected, rtol=1e-12, atol=0.0)
                self.assertGreater(found.reached, ni * nj // 3)
                self.assertLess(found.reached, ni * nj)


class ScaleTest(unittest.TestCase):
    """La malla de la rejilla de 2,81 M celdas (RNF-017-01), construida una vez por clase."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = rd.scale_grid()
        cls.x, _y = np.meshgrid((np.arange(cls.grid.ncols) + 0.5) * cls.grid.dx, (np.arange(cls.grid.nrows) + 0.5) * cls.grid.dy)

    def mesh(self, surface: np.ndarray, mask: np.ndarray | None = None) -> Any:
        return road_net.route_mesh(self.grid, surface, 4.0, mask)

    def drive(self, mesh: Any, target: tuple[int, int], pd: float, hmax: float) -> tuple[Any, float, float]:
        """La red entera, el tiempo de la mejor de tres corridas y la llamada más larga de un paso."""
        found = drive_steps(road_net.network_steps(mesh, target, pd, hmax))
        total = least_of(lambda: drive_steps(road_net.network_steps(mesh, target, pd, hmax)).total_s, RUN_LIMIT_S, attempts=3)
        longest = least_of(lambda: drive_steps(road_net.network_steps(mesh, target, pd, hmax)).longest_s, STEP_LIMIT_S, attempts=2)
        return found.result, total, longest

    def test_the_free_slope_of_4_percent_with_14_m_of_height(self) -> None:
        """RNF-017-01, RNF-017-06: la red 2D de 175.950 nodos en un talud del 4 % libre con pd = 10 % y 14 m de altura: llega a todos los
        pisables, cada corrida tarda ≤ 5 s (medida: 0,29 s) y cada paso ≤ 0,05 s."""
        surface = 100.0 + 0.04 * self.x
        mesh = self.mesh(surface)
        self.assertEqual(mesh.shape, (425, 414))
        found, total, longest = self.drive(mesh, (212, 20), 0.10, 14.0)
        self.assertEqual(found.reached, int(mesh.walkable.sum()))
        self.assertLessEqual(total, RUN_LIMIT_S)
        self.assertLessEqual(longest, STEP_LIMIT_S)

    def test_the_38_percent_slope_with_a_wall_with_a_gap_and_2_m_of_height(self) -> None:
        """RNF-017-01, RNF-017-06: lo mismo en un talud del 38 % con un muro con hueco y 2 m de altura (el caso difícil del plan §7.3: las
        pendientes cierran muchos pasos y el muro obliga al rodeo): cada corrida ≤ 5 s y cada paso ≤ 0,05 s."""
        surface = 100.0 + 0.38 * self.x
        wall = np.zeros(self.grid.shape, dtype=bool)
        middle = self.grid.ncols // 2
        wall[:, middle:middle + 12] = True
        wall[self.grid.nrows - 80:self.grid.nrows - 56, middle:middle + 12] = False
        mesh = self.mesh(surface, wall)
        found, total, longest = self.drive(mesh, (212, 20), 0.10, 2.0)
        self.assertGreater(found.reached, 10_000)
        self.assertLessEqual(total, RUN_LIMIT_S)
        self.assertLessEqual(longest, STEP_LIMIT_S)

    def test_the_corridor_of_60_m_of_margin_is_not_a_strip_of_60_m(self) -> None:
        """RF-017-09 (H-1), RNF-017-01: el pasillo de 60 m de **holgura** de la ruta de 1.500 m del barranco de 14 m (de oeste a este por la
        mitad de la rejilla de escala) tiene de 21.978 a 31.856 nodos (los del plan: con este terreno, 21.978; las dos corridas, ≤ 10 s) y no los
        5.640 de una franja de 60 m de ancho (15 × 375 nodos); su cota inferior es la longitud de la red (1.500 m: la ruta cabe en
        un rumbo)."""
        spec = rd.scale_ravine_spec()
        mesh = self.mesh(rd.scale_ravine_terrain())
        origin = mesh.node_of(*rd.absolute([spec.origin], self.grid)[0])
        destination = mesh.node_of(*rd.absolute([spec.destination], self.grid)[0])
        started = time.perf_counter()
        net_origin = run(road_net.network_steps(mesh, origin, 0.10, 14.0))
        net_dest = run(road_net.network_steps(mesh, destination, 0.10, 14.0))
        found = road_net.corridor(net_origin, net_dest, 60.0)
        self.assertLessEqual(time.perf_counter() - started, 2.0 * RUN_LIMIT_S)
        self.assertTrue(found.reachable)
        self.assertAlmostEqual(found.lower_bound_m, 1_500.0, delta=4.0)
        self.assertGreaterEqual(found.nodes, 21_978)  # los del plan: 21.978 con el barranco y 31.856 con la ladera del 38 %
        self.assertLessEqual(found.nodes, 31_856)
        self.assertGreater(found.nodes, 5_640)
        self.assertLess(road_net.corridor(net_origin, net_dest, 0.0).nodes, 400)


if __name__ == "__main__":
    unittest.main()
