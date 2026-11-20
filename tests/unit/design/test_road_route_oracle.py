# SPDX-License-Identifier: GPL-3.0-or-later
"""La ruta 3D contra el oráculo de fuerza bruta (spec 017, T09; HU-017-1; RF-017-10, RF-017-09, RF-017-11 y RF-017-12; RF-015-02; plan 017 §7.1,
§5.4 A1 a A3; D-23): el coste, los giros y **la ruta** del A\\* de ``design.road_route`` son los de ``design_oracles.hand_route`` —un Dijkstra
completo sobre el grafo explícito de estados ``(nodo, nivel, rumbo)``, por fuerza bruta, que no comparte con el A\\* ni la cola, ni las tablas
de saltos, ni la cota admisible, ni el empaquetado de las etiquetas— en mallas de 8 × 8 nodos y 5 niveles, y su pasillo es el que sale de
la red 2D a mano (``hand_corridor``, sobre ``hand_net``).

Lo que se compara, caso a caso: **si hay ruta** (sin ella, que no la haya el oráculo: la causa del pasillo agotado o de la red 2D), el coste
entero (nanómetros: ``Route.cost_units`` frente al del oráculo, **exacto**), los giros, los nodos, el rumbo con que se llega a cada uno y el
nivel de cada nodo, también con el desempate de D-23 (el menor número de giros, luego el primer rumbo en sentido horario desde el norte, y
entre dos orígenes de un mismo estado el de menor rumbo anterior y menor salto de nivel) y con el peso de «preferible no afectar»; y el
pasillo del código frente al del oráculo, nodo a nodo. Lo que pasa de 1 s (el barrido de cientos de casos al azar) va a
``milestone_road_route_oracle`` (RNF-017-09); aquí, los casos que dan cada propiedad en menos de medio segundo.
"""

from __future__ import annotations

import dataclasses
import math
import unittest
from typing import Any

import numpy as np

from tests.support import design_oracles as oracles
from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.unit.design import test_road_route as base

road_model = import_geoblender("design.road_model")

CELL_M = base.CELL_M
FIVE_LEVELS = rd.route_with(mesh_m=CELL_M, level_step_m=0.25, max_cut_fill_m=0.5, lambda_per_m=2.0, turn_m=2.0, margin_m=100_000.0,
                            simplify_m=4.0, arrival_tol_m=0.25, search_budget=5_000_000)
"""Los parámetros de los casos del oráculo (HIPÓTESIS de la prueba, T01-a; ninguno es valor por defecto del producto): malla de 4 m, paso de
cota de 0,25 m y altura de 0,5 m (``M = 2``: **cinco niveles** por nodo), λ = 2 1/m, un giro de 2 m y una holgura enorme (el pasillo es todo
lo que alcanza la red 2D; los casos con pasillo estrecho la bajan)."""


def with_route(route: Any = FIVE_LEVELS, **changes: Any) -> Any:
    return rd.route_with(**{**dataclasses.asdict(route), **changes})


def oracle_corridor(job: Any, mesh: Any, origin: tuple[int, int], destination: tuple[int, int], factor: int) -> np.ndarray:
    """El pasillo **a mano** (``hand_net`` desde el origen y desde el destino): ``(ni, nj)`` booleano."""
    return oracles.hand_corridor(job.start, job.untouchable, factor, mesh.mesh_m / factor, job.profile.max_gradient_pct / 100.0,
                                 job.route.max_cut_fill_m, origin, destination, job.route.margin_m)


def oracle_route(job: Any, mesh: Any, origin: tuple[int, int], destination: tuple[int, int], factor: int, domain: np.ndarray) -> Any:
    """La ruta del oráculo con los mismos datos que el trabajo: la superficie y lo que no se pisa (por celdas), la malla, ``pd``, la altura, el
    paso de cota, λ, el giro, las cotas de inicio y de fin, el peso (por celdas) y el pasillo."""
    params = job.route
    return oracles.hand_route(
        job.start, job.untouchable, factor, mesh.mesh_m / factor, job.profile.max_gradient_pct / 100.0, params.max_cut_fill_m,
        params.level_step_m, params.lambda_per_m, params.turn_m, origin, destination, start_level_m=job.start_level_m,
        end_level_m=job.end_level_m, weight=job.avoid_weight, domain=domain)


def levels_of(route: Any, mesh: Any, step_m: float) -> tuple[int, ...]:
    """El nivel (múltiplos del paso de cota sobre el terreno del nodo) de cada nodo de la ruta."""
    return tuple(round((float(level) - float(mesh.z[node])) / step_m) for level, node in zip(route.levels_m, route.nodes, strict=True))


def compare(test: unittest.TestCase, surface: np.ndarray, origin: tuple[int, int], destination: tuple[int, int], *, route: Any = FIVE_LEVELS,
            factor: int = 1, pd_pct: float = 10.0, **options: Any) -> tuple[Any, Any]:
    """Un caso: el A\\* y el oráculo con los mismos datos; compara el pasillo (nodo a nodo), si hay ruta y, con ella, el coste entero, los giros,
    los nodos, los rumbos y los niveles; recalcula además las condiciones de RF-017-10 (``test_road_route.verify``). Da ``(ruta, oráculo)``."""
    job, mesh, corridor = base.build(surface, origin, destination, route=route, pd_pct=pd_pct, factor=factor, **options)
    domain = oracle_corridor(job, mesh, origin, destination, factor)
    test.assertTrue(np.array_equal(corridor.mask, domain), "el pasillo del código no es el de la red 2D a mano")
    found = base.solve(job, corridor)
    hand = oracle_route(job, mesh, origin, destination, factor, domain)
    test.assertEqual(found.ok, hand.found)
    if not hand.found:
        test.assertEqual(found.cause, road_model.NoRouteCause.CORRIDOR if corridor.reachable else road_model.NoRouteCause.NETWORK)
        return found, hand
    base.verify(test, job, mesh, found)
    test.assertEqual(found.cost_units, hand.cost_units)
    test.assertEqual(found.turns, hand.turns)
    test.assertEqual(found.nodes, hand.nodes)
    test.assertEqual(found.headings, hand.headings)
    test.assertEqual(levels_of(found, mesh, job.route.level_step_m), hand.levels)
    return found, hand


def gap_wall(rows: int, cols: int, column: int, gap: tuple[int, int]) -> np.ndarray:
    """Una columna de nodos prohibidos salvo un hueco (filas ``gap[0]`` a ``gap[1]`` sin incluir)."""
    wall = np.zeros((rows, cols), dtype=bool)
    wall[:, column] = True
    wall[gap[0]:gap[1], column] = False
    return wall


class OracleSelfTest(unittest.TestCase):
    """Lo que el oráculo da en casos cuya respuesta se sabe **a mano** (y que no dependen de ``design``): sin ellos, que coincida con el A\\*
    no probaría nada."""

    def test_on_a_flat_plane_a_straight_line_costs_its_length_and_the_corridor_is_the_hand_network(self) -> None:
        """RF-017-10, RF-017-09: en un plano 8 × 8 de cinco niveles la ruta de un rumbo de la rejilla (cinco pasos de 4 m al este) es la recta:
        20 m, ni un giro, el nivel 0 en todos los nodos (``cost_units`` 20·10⁹); con la holgura 0, el pasillo es la recta y con una holgura
        enorme son los 64 nodos; el grafo explícito tiene 64 · 5 · 16 = 5.120 estados y en la recta el desempate no decide nunca (``tied``)."""
        flat = base.flat(8, 8)
        job, mesh, _corridor = base.build(flat, (3, 1), (3, 6), route=FIVE_LEVELS)
        domain = oracle_corridor(job, mesh, (3, 1), (3, 6), 1)
        self.assertEqual(int(domain.sum()), 64)
        hand = oracle_route(job, mesh, (3, 1), (3, 6), 1, domain)
        self.assertTrue(hand.found)
        self.assertEqual((hand.cost_units, hand.turns, hand.levels), (20_000_000_000, 0, (0,) * 6))
        self.assertEqual(hand.nodes, tuple((3, j) for j in range(1, 7)))
        self.assertEqual(hand.headings, (4,) * 6)
        self.assertEqual((hand.states, hand.tied), (64 * 5 * 16, 0))
        tight = with_route(margin_m=0.0)
        job_t, mesh_t, _corridor_t = base.build(flat, (3, 1), (3, 6), route=tight)
        self.assertEqual(oracle_corridor(job_t, mesh_t, (3, 1), (3, 6), 1).sum(), 6)
        # con una holgura finita (9,5 m: ni la de la recta ni la de todo) el pasillo es la elipse y el del código coincide nodo a nodo (``compare``)
        found, hand = compare(self, flat, (3, 1), (3, 6), route=with_route(margin_m=9.5))
        self.assertTrue(found.ok)
        _job_m, _mesh_m, corridor_m = base.build(flat, (3, 1), (3, 6), route=with_route(margin_m=9.5))
        self.assertTrue(6 < int(corridor_m.mask.sum()) < 64)
        self.assertEqual(hand.cost_units, 20_000_000_000)


class AgainstTheOracleTest(unittest.TestCase):
    def test_a_rolling_terrain_with_vertical_work_gives_the_oracles_route(self) -> None:
        """RF-017-10, RF-017-11: en un terreno al azar de 8 × 8 nodos, con una cota de inicio a medio metro sobre el terreno (dos niveles) y una de
        fin a 0,4 m sobre él (1,6 niveles: el más próximo es el 2, no el 1), la ruta —el coste entero, los giros, los nodos, los rumbos y los
        niveles— es la del oráculo, y mueve tierra (algún nodo fuera de nivel 0)."""
        for seed in (1,):
            surface = base.rolling(seed, 8, 8)
            with self.subTest(seed=seed):
                found, hand = compare(self, surface, (6, 1), (1, 6), start_level_m=float(surface[6, 1]) + 0.5,
                                      end_level_m=float(surface[1, 6]) + 0.4)
                self.assertTrue(found.ok)
                self.assertTrue(any(hand.levels))
                self.assertEqual((hand.levels[0], hand.levels[-1]), (2, 2))

    def test_with_a_wall_with_a_gap_the_route_goes_through_the_gap_like_the_oracles(self) -> None:
        """RF-017-10, RF-017-06: con una columna de nodos prohibidos y un hueco de dos nodos, la ruta del A\\* y la del oráculo pasan por él (por
        un paso «de caballo» cuyos dos nodos intermedios se pisan) y por ningún nodo del muro, con el mismo coste, giros y nodos; con el hueco
        al otro lado, que el límite de giro no deja alcanzar desde el origen, ninguno de los dos encuentra ruta."""
        wall = gap_wall(8, 8, 4, (3, 5))
        found, hand = compare(self, base.rolling(3, 8, 8), (1, 1), (2, 7), untouchable=wall)
        self.assertTrue(found.ok)
        self.assertTrue(any(node[1] == 4 and node[0] in (3, 4) for node in hand.nodes))
        self.assertFalse(any(wall[node] for node in hand.nodes))
        self.assertGreater(len(hand.nodes), 4)
        unreachable, hand_none = compare(self, base.rolling(3, 8, 8), (1, 1), (1, 7), untouchable=wall)
        self.assertEqual((unreachable.ok, hand_none.found), (False, False))

    def test_the_tie_of_a_symmetric_plane_is_resolved_like_the_oracle_with_the_rule_of_the_spec(self) -> None:
        """RF-017-10, D-23, RF-015-02: en un plano sin penalización de giro, a 4 nodos al este y 1 al norte (o al sur) hay tres rutas de un mismo
        coste y el oráculo desempata por la regla de D-23 (el menor número de giros, luego el primer rumbo en sentido horario desde el norte
        al llegar): el A\\* da su misma ruta —este, este y el paso (2, 1) al norte; el (2, −1) y dos al este al sur—, con el desempate decidiendo
        (``tied``) y **bit a bit lo mismo** en una segunda ejecución."""
        zero = with_route(turn_m=0.0)
        for destination, expected in (((3, 5), (4, 4, 4, 3)), ((5, 5), (5, 5, 4, 4))):
            with self.subTest(destination=destination):
                found, hand = compare(self, base.flat(8, 8), (4, 1), destination, route=zero)
                self.assertEqual(hand.headings, expected)
                self.assertEqual((hand.turns, hand.cost_units), (1, 2 * 4_000_000_000 + round(4_000_000_000 * math.sqrt(5.0))))
                self.assertGreater(hand.tied, 0)
                job, _mesh, corridor = base.build(base.flat(8, 8), (4, 1), destination, route=zero)
                self.assertEqual(base.fingerprint(base.solve(job, corridor)), base.fingerprint(found))

    def test_a_route_that_can_only_turn_clockwise_is_the_oracles_route(self) -> None:
        """RF-017-10 (b), RF-017-06: con dos tramos de nodos prohibidos (las filas 1 y 3, de la columna 1 a la 4) que dejan al este la única subida o
        bajada, la ruta de (2, 0) a (4, 7) va al este por la fila 2 y baja después con dos giros **de rumbo creciente** (este, (2, −1) y
        (1, −1): del 4 al 5 y al 6, el contiguo siguiente en sentido horario): el A\\* los encuentra como el oráculo (con el rumbo más alto
        al llegar: no hay otra), y el coste incluye los dos giros."""
        wall = np.zeros((8, 8), dtype=bool)
        wall[1, 1:5] = wall[3, 1:5] = True
        found, hand = compare(self, base.flat(8, 8), (2, 0), (4, 7), untouchable=wall)
        self.assertTrue(found.ok)
        self.assertEqual((hand.headings, hand.turns), ((4, 4, 4, 4, 4, 5, 6), 2))
        by_hand = 4 * 4_000_000_000 + round(4_000_000_000 * math.sqrt(5.0)) + round(4_000_000_000 * math.sqrt(2.0)) + 2 * 2_000_000_000
        self.assertEqual(hand.cost_units, by_hand)  # cuatro pasos al este, el (2, −1), el (1, −1) y dos giros de 2 m

    def test_the_weight_of_the_zones_to_avoid_bends_the_route_like_the_oracles(self) -> None:
        """RF-017-10, RF-017-06 (P-7): con el peso 8 de «preferible no afectar» en un bloque de 3 × 2 nodos en medio de la recta, el A\\* y el
        oráculo la rodean (ningún nodo de la zona), con el coste del paso medido en la media de los pesos de sus dos nodos; sin zona, la
        recta la atraviesa; y con el origen de peso 2 y el destino de peso 3 (que ninguna ruta evita) la recta cuesta, a mano, 4 m · (1,5 + 5 · 1 +
        2) = 34 m."""
        weight = np.ones((8, 8))
        weight[2:5, 3:5] = 8.0
        origin, destination = (3, 0), (3, 7)
        plain, _hand_plain = compare(self, base.flat(8, 8), origin, destination)
        self.assertEqual(plain.nodes, tuple((3, j) for j in range(8)))
        found, hand = compare(self, base.flat(8, 8), origin, destination, avoid_weight=weight)
        self.assertFalse(any(weight[node] > 1.0 for node in hand.nodes))
        self.assertGreater(found.cost_units, plain.cost_units)
        # el origen y el destino de peso distinto de 1 (nunca se evitan): el primer y el último paso cuestan con la media de sus dos nodos
        ends = np.ones((8, 8))
        ends[3, 0], ends[3, 7] = 2.0, 3.0
        weighted, hand_ends = compare(self, base.flat(8, 8), origin, destination, avoid_weight=ends)
        self.assertEqual(weighted.nodes, plain.nodes)
        self.assertGreater(weighted.cost_units, plain.cost_units)
        self.assertEqual(hand_ends.cost_units, 34_000_000_000)  # 4 m · (1,5 + 5 · 1 + 2), a mano: la media (2 + 1)/2, cinco de 1 y (1 + 3)/2

    def test_a_cell_block_of_two_by_two_cells_is_a_node_of_the_mean_like_the_oracles(self) -> None:
        """RF-017-09, RF-017-10 (P-6): con bloques de 2 × 2 celdas (16 × 16 celdas de 2 m: 8 × 8 nodos de 4 m) la cota del nodo es la media de las
        cuatro y un nodo con una sola celda prohibida no se pisa; el A\\* y el oráculo dan lo mismo."""
        surface = base.rolling(4, 8, 8, factor=2)
        forbidden = np.zeros((16, 16), dtype=bool)
        forbidden[6, 8] = True  # una sola celda del nodo (3, 4): no se pisa
        found, hand = compare(self, surface, (6, 1), (2, 6), factor=2, untouchable=forbidden)
        self.assertTrue(found.ok)
        self.assertNotIn((3, 4), hand.nodes)


class NoRouteTest(unittest.TestCase):
    def test_where_the_oracle_finds_no_route_the_search_exhausts_its_corridor(self) -> None:
        """RF-017-10, RF-017-12: bajar 1,5 m (seis niveles de 0,25 m, de +0,75 a −0,75 m sobre el terreno) con la holgura 0 no tiene ruta en el
        grafo explícito del oráculo (el pasillo es la recta de cinco pasos de 4 m y cada uno admite a lo sumo un nivel: 0,4 m de pendiente) y el
        A\\* agota el pasillo con la causa del pasillo, sin la del presupuesto; con la holgura que deja los pasos «de caballo» (tres niveles
        cada uno), los dos encuentran la misma ruta."""
        steep = with_route(max_cut_fill_m=0.75, margin_m=0.0)
        found, hand = compare(self, base.flat(8, 8), (3, 1), (3, 6), route=steep, start_level_m=100.75, end_level_m=99.25)
        self.assertFalse(found.ok)
        self.assertEqual((found.cause, hand.found), (road_model.NoRouteCause.CORRIDOR, False))
        wide = with_route(steep, margin_m=100_000.0)
        found, hand = compare(self, base.flat(8, 8), (3, 1), (3, 6), route=wide, start_level_m=100.75, end_level_m=99.25)
        self.assertTrue(found.ok)
        self.assertEqual((hand.levels[0], hand.levels[-1]), (3, -3))
        self.assertLess(len(hand.nodes), 6)  # menos pasos que la recta: el paso «de caballo» baja tres niveles

    def test_an_origin_the_2d_network_does_not_reach_has_no_route_for_the_oracle_either(self) -> None:
        """RF-017-09, RF-017-12: con el origen cercado por nodos prohibidos la red 2D a mano no lo alcanza (pasillo vacío): el oráculo no encuentra
        ruta y el A\\* tampoco (la causa de la red)."""
        ring = np.zeros((8, 8), dtype=bool)
        ring[2:5, 2:5] = True
        ring[3, 3] = False
        found, hand = compare(self, base.flat(8, 8), (3, 3), (3, 7), untouchable=ring)
        self.assertEqual((found.ok, hand.found, found.cause), (False, False, road_model.NoRouteCause.NETWORK))

    def test_a_start_level_out_of_the_height_gives_no_state_in_either(self) -> None:
        """RF-017-10: una cota de inicio fuera de la altura máxima de desmonte y terraplén (a 1,3 m del terreno con 0,5 m) no deja arrancar:
        ni el A\\* ni el oráculo tienen estado de partida."""
        found, hand = compare(self, base.flat(8, 8), (3, 1), (3, 6), start_level_m=101.3)
        self.assertEqual((found.ok, hand.found), (False, False))
        self.assertEqual(found.expanded, 0)


if __name__ == "__main__":
    unittest.main()
