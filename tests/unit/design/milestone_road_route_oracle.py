# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_road_route_oracle» (spec 017, T09; RF-017-10, RF-017-09, RF-017-11 y RF-017-12; RF-015-02; plan 017 §7.1; D-23): lo
que pasa de 1 s y no entra en el «verde» (``tools/check.py``, RNF-017-09). El «verde» deja en ``test_road_route_oracle`` un caso por
propiedad (8 × 8 nodos y cinco niveles); esto lo ejecuta el paso «hito» de ``tools/check.py --completo`` (la publicación lo pide siempre).

- **El barrido al azar** (RF-017-10, RF-017-12, D-23): 300 casos de mallas de 5 × 6 a 8 × 8 nodos (bloques de 1 y de 2 celdas), terrenos
  de ruido de 0,05 a 0,5 m, pendientes de diseño del 4 al 15 %, alturas de 0 a 1 m con pasos de cota de 0,2 y de 0,25 m, λ de 0 a 2 1/m,
  giros de 0 a 6 m, holguras de 0 m a ilimitada (el pasillo estrecho recorta el grafo), nodos prohibidos, zonas de «preferible no afectar» y
  cotas de inicio y de fin con y sin ellas: en **todos** el pasillo del código es el de la red 2D a mano y, si hay ruta, el coste entero, los
  giros, los nodos, los rumbos y los niveles de la ruta del A\\* son los del oráculo de fuerza bruta (``design_oracles.hand_route``), con
  la misma ausencia de ruta cuando no la hay. El barrido cuenta lo que cubre: hay casos con y sin ruta, con el pasillo agotado y con la red
  2D que no alcanza el origen, y casos en que **el desempate de D-23 decidió** la ruta.
"""

from __future__ import annotations

import time
import unittest
from collections import Counter
from typing import Any

import numpy as np

from tests.unit.design import test_road_route_oracle as green

CASES = 300
"""Los casos del barrido (6 s en total, ≈ 20 ms cada uno; el tiempo se anota en la *Verificación* de la T09)."""
SEED = 20_261_120
"""La semilla del barrido: los mismos casos en cada ejecución (la prueba es determinista)."""
LEVELS = {0.0: (0.2,), 0.25: (0.25,), 0.5: (0.25, 0.2), 0.75: (0.25,), 1.0: (0.25, 0.2)}
"""Las alturas máximas de los casos y los pasos de cota con que se combinan (``M`` de 0 a 5 niveles por lado)."""


def random_case(rng: np.random.Generator) -> dict[str, Any]:
    """Los datos de un caso al azar: la superficie (por celdas), la malla, los parámetros, el origen y el destino, lo que no se pisa, los pesos
    y las cotas de inicio y de fin. Todo sale del generador: los mismos en cada ejecución."""
    rows, cols = int(rng.integers(5, 9)), int(rng.integers(6, 9))
    factor = int(rng.choice((1, 1, 1, 2)))
    amplitude = float(rng.choice((0.05, 0.05, 0.2, 0.5)))
    i, j = np.indices((rows, cols))
    nodes = (100.0 + float(rng.uniform(-0.03, 0.03)) * j * green.CELL_M + float(rng.uniform(-0.03, 0.03)) * i * green.CELL_M
             + amplitude * rng.standard_normal((rows, cols)))
    surface = np.kron(nodes, np.ones((factor, factor)))
    hmax = float(rng.choice(tuple(LEVELS)))
    step = float(rng.choice(LEVELS[hmax]))
    route = green.with_route(max_cut_fill_m=hmax, level_step_m=step, lambda_per_m=float(rng.choice((0.0, 0.5, 2.0))),
                             turn_m=float(rng.choice((0.0, 2.0, 6.0))), margin_m=float(rng.choice((0.0, 9.5, 18.0, 100_000.0, 100_000.0))))
    forbidden = np.zeros((rows, cols), dtype=bool)
    for _ in range(int(rng.integers(0, 3))):
        r0, c0 = int(rng.integers(0, rows)), int(rng.integers(0, cols))
        forbidden[r0:r0 + int(rng.integers(1, 4)), c0:c0 + int(rng.integers(1, 4))] = True
    free = [(a, b) for a in range(rows) for b in range(cols) if not forbidden[a, b]]
    for _ in range(50):
        origin, destination = (free[int(rng.integers(len(free)))] for _ in range(2))
        if abs(origin[0] - destination[0]) + abs(origin[1] - destination[1]) >= 3:
            break
    weight = None
    if rng.random() < 0.3:
        weight = np.ones((rows, cols))
        r0, c0 = int(rng.integers(0, rows)), int(rng.integers(0, cols))
        weight[r0:r0 + int(rng.integers(1, 4)), c0:c0 + int(rng.integers(1, 4))] = float(rng.choice((2.0, 3.0, 8.0)))
        weight = np.kron(weight, np.ones((factor, factor)))
    options: dict[str, Any] = {"untouchable": np.kron(forbidden, np.ones((factor, factor), dtype=bool)).astype(bool)}
    if weight is not None:
        options["avoid_weight"] = weight
    reach = (hmax // step + 1.4) * step
    for name, node in (("start_level_m", origin), ("end_level_m", destination)):
        if rng.random() < 0.5:
            options[name] = float(nodes[node]) + float(rng.uniform(-reach, reach))
    return {"surface": surface, "origin": origin, "destination": destination, "route": route, "factor": factor,
            "pd_pct": float(rng.choice((4.0, 7.0, 10.0, 15.0))), "options": options}


class SweepTest(unittest.TestCase):
    def test_random_cases_give_the_routes_of_the_brute_force_oracle(self) -> None:
        """RF-017-10, RF-017-09, RF-017-11, RF-017-12, D-23, RF-015-02: ``CASES`` casos al azar (la misma semilla en cada ejecución) dan en el
        A\\* el pasillo, el coste entero, los giros, los nodos, los rumbos y los niveles del oráculo de fuerza bruta, y la misma ausencia de ruta
        cuando no la hay; el barrido cubre casos con ruta, sin ella por el pasillo y por la red 2D, y casos en que decidió el desempate."""
        rng = np.random.default_rng(SEED)
        outcome: Counter[str] = Counter()
        started = time.perf_counter()
        for index in range(CASES):
            case = random_case(rng)
            with self.subTest(case=index):
                found, hand = green.compare(self, case["surface"], case["origin"], case["destination"], route=case["route"],
                                            factor=case["factor"], pd_pct=case["pd_pct"], **case["options"])
                if hand.found:
                    outcome["route"] += 1
                    outcome["tie decided"] += hand.tied > 0
                    outcome["turned"] += hand.turns > 0
                    outcome["vertical work"] += any(hand.levels)
                else:
                    outcome["no route: " + str(found.cause.value)] += 1
        elapsed = time.perf_counter() - started
        print(f"\nmilestone_road_route_oracle: {CASES} casos en {elapsed:.1f} s; {dict(outcome)}")
        self.assertGreaterEqual(outcome["route"], CASES // 3)
        self.assertGreaterEqual(outcome["no route: des.road_no_route_corridor"] + outcome["no route: des.road_budget"], 1)
        self.assertGreaterEqual(sum(count for name, count in outcome.items() if name.startswith("no route")), CASES // 10)
        self.assertGreaterEqual(outcome["tie decided"], CASES // 10)
        self.assertGreaterEqual(outcome["vertical work"], CASES // 10)


if __name__ == "__main__":
    unittest.main()
