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
- **Con una altura que no es múltiplo del paso de cota** (B-1 de la verificación única, T41; RF-017-10 (a)): el barrido de arriba **varía el paso sin que H sea múltiplo** (0,5 con 0,28 y 0,6; 0,75 con 0,4;
  1 con 0,3 y 0,45: antes todas las parejas eran múltiplos), :class:`SteepSweepTest` hace otros 300 casos de **relieve fuerte** (escalones de varios metros, pd del 10 al 40 %) con parejas que no son múltiplos
  y :class:`NonMultipleTest` fija el caso del escalón de 1,2 m con la ruta del oráculo.
"""

from __future__ import annotations

import time
import unittest
from collections import Counter
from typing import Any

import numpy as np

from tests.support.package import import_geoblender
from tests.unit.design import test_road_route as base
from tests.unit.design import test_road_route_oracle as green

road_model = import_geoblender("design.road_model")

CASES = 300
"""Los casos del barrido (6 s en total, ≈ 20 ms cada uno; el tiempo se anota en la *Verificación* de la T09)."""
SEED = 20_261_120
"""La semilla del barrido: los mismos casos en cada ejecución (la prueba es determinista)."""
LEVELS = {0.0: (0.2,), 0.25: (0.25, 0.18), 0.5: (0.25, 0.2, 0.28, 0.6), 0.75: (0.25, 0.4), 1.0: (0.25, 0.2, 0.3, 0.45)}
"""Las alturas máximas de los casos y los pasos de cota con que se combinan (``M`` de 0 a 5 niveles por lado). **Varios pares (H, paso) no son múltiplos** (0,5 con 0,28 y 0,6; 0,75 con
0,4; 1 con 0,3 y 0,45; 0,25 con 0,18): con una altura que no es múltiplo del paso de cota, o con un paso mayor que la altura, los niveles solo cubren ±M·Δz y la red 2D admite más desnivel
(pd·L + 2H) que el que salvan los saltos de nivel (B-1 de la verificación única, T41)."""
STEEP_CASES = 300
"""Los casos del barrido de relieve fuerte (≈ 8 s en total)."""
STEEP_SEED = 20_261_122
"""La semilla del barrido de relieve fuerte."""
STEEP_LEVELS = ((0.5, 0.28), (0.5, 0.6), (1.0, 0.3), (1.0, 0.45), (0.75, 0.4), (1.5, 0.4), (2.0, 0.7), (0.25, 0.18))
"""Los pares (H, paso de cota) del relieve fuerte: **ninguno es múltiplo** (el paso mayor que H, o H entre dos múltiplos del paso)."""


def random_case(rng: np.random.Generator, *, steep: bool = False) -> dict[str, Any]:
    """Los datos de un caso al azar: la superficie (por celdas), la malla, los parámetros, el origen y el destino, lo que no se pisa, los pesos
    y las cotas de inicio y de fin. Todo sale del generador: los mismos en cada ejecución. Con ``steep``, el **relieve fuerte** de B-1: ruido de 1 a 3 m
    (escalones de varios metros entre nodos vecinos), pendientes de diseño del 10 al 40 % y las parejas (H, paso) de :data:`STEEP_LEVELS`."""
    rows, cols = int(rng.integers(5, 9)), int(rng.integers(6, 9))
    factor = int(rng.choice((1, 1, 1, 2)))
    amplitude = float(rng.choice((1.0, 2.0, 3.0) if steep else (0.05, 0.05, 0.2, 0.5)))
    i, j = np.indices((rows, cols))
    nodes = (100.0 + float(rng.uniform(-0.03, 0.03)) * j * green.CELL_M + float(rng.uniform(-0.03, 0.03)) * i * green.CELL_M
             + amplitude * rng.standard_normal((rows, cols)))
    surface = np.kron(nodes, np.ones((factor, factor)))
    if steep:
        hmax, step = STEEP_LEVELS[int(rng.integers(len(STEEP_LEVELS)))]
    else:
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
            "pd_pct": float(rng.choice((10.0, 20.0, 40.0) if steep else (4.0, 7.0, 10.0, 15.0))), "options": options}


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


class SteepSweepTest(unittest.TestCase):
    def test_random_cases_of_strong_relief_with_a_height_that_is_not_a_multiple_of_the_step_give_the_oracles_routes(self) -> None:
        """RF-017-10 (a), RF-017-12, D-23: ``STEEP_CASES`` casos al azar de **relieve fuerte** (ruido de 1 a 3 m: escalones de varios metros entre nodos vecinos; pd del 10 al 40 %) con las parejas
        (H, paso de cota) de ``STEEP_LEVELS``, **ninguna múltiplo** (el paso mayor que H, o H entre dos múltiplos del paso) dan en el A\\* el pasillo, el coste entero, los giros, los nodos,
        los rumbos y los niveles del oráculo de fuerza bruta, y la misma ausencia de ruta cuando no la hay (B-1 de la verificación única: antes, con estas parejas, el A\\* daba rutas con un paso por
        encima de pd y rutas donde el oráculo no halla ninguna; el verificador B midió 22 diferencias en 1.200 casos); el barrido cubre casos con y sin ruta."""
        rng = np.random.default_rng(STEEP_SEED)
        outcome: Counter[str] = Counter()
        started = time.perf_counter()
        for index in range(STEEP_CASES):
            case = random_case(rng, steep=True)
            with self.subTest(case=index):
                found, hand = green.compare(self, case["surface"], case["origin"], case["destination"], route=case["route"],
                                            factor=case["factor"], pd_pct=case["pd_pct"], **case["options"])
                outcome["route" if hand.found else "no route: " + str(found.cause.value)] += 1
                outcome["vertical work"] += hand.found and any(hand.levels)
        elapsed = time.perf_counter() - started
        print(f"\nmilestone_road_route_oracle (relieve fuerte): {STEEP_CASES} casos en {elapsed:.1f} s; {dict(outcome)}")
        self.assertGreaterEqual(outcome["route"], STEEP_CASES // 10)
        self.assertGreaterEqual(sum(count for name, count in outcome.items() if name.startswith("no route")), STEEP_CASES // 10)
        self.assertGreaterEqual(outcome["vertical work"], STEEP_CASES // 10)


class NonMultipleTest(unittest.TestCase):
    """B-1 de la verificación única (T41): con una altura que **no** es múltiplo del paso de cota (M = ⌊H/Δz⌋ y los niveles solo cubren ±M·Δz) la ruta de la búsqueda es la del oráculo; las
    parejas (H, paso) de todos los demás casos son múltiplos."""

    def test_a_height_that_is_not_a_multiple_of_the_level_step_gives_the_oracles_route(self) -> None:
        """RF-017-10 (a), RF-017-12: con H = 0,5 m y el paso de cota de 0,28 m, el escalón de 1,2 m que no se puede rodear (8 × 9 nodos) se cruza en el oráculo con pasos «de caballo» de dos
        niveles hacia abajo (coste 39,137 m); antes la búsqueda lo cruzaba con una pendiente del 16 % en un paso recto de 4 m (28,48 m) y ahora da la misma ruta que el oráculo; con 8 × 8 nodos
        el oráculo no encuentra ninguna ruta admisible (antes la búsqueda daba una de 24,48 m) y la búsqueda dice ahora lo mismo: sin ruta por el pasillo."""
        params = green.with_route(max_cut_fill_m=0.5, level_step_m=0.28)
        found, hand = green.compare(self, base.cliff_terrain(8, 9, 1.2, 4), (3, 1), (3, 7), route=params)
        self.assertTrue(found.ok)
        self.assertEqual(hand.cost_units, 39_137_336_090)
        self.assertGreater(found.cost, 4 * 7)  # más que la recta (28 m): da un rodeo por los pasos «de caballo»
        found, hand = green.compare(self, base.cliff_terrain(8, 8, 1.2, 4), (3, 1), (3, 6), route=params)
        self.assertEqual((found.ok, hand.found), (False, False))
        self.assertEqual(found.cause, road_model.NoRouteCause.CORRIDOR)


if __name__ == "__main__":
    unittest.main()
