# SPDX-License-Identifier: GPL-3.0-or-later
"""La ruta 3D de mínimo coste de una pista (spec 017, T07; HU-017-1; RF-017-10, 11 y 06; RF-015-02; RNF-017-02, 06 y 07; plan 017 §5.4 A2,
§5.7 P-3, P-7 y P-13, §7.3 y §9; D-23): ``route_steps`` (un A\\* sobre los estados ``(nodo, nivel, rumbo)`` con la red 2D como cota, por
pasos, con desempates exactos y un presupuesto de estados) y su ``Route``.

Todo en mallas de ≤ 40 × 40 nodos y pocos miles de estados (lo que pasa de 1 s va a ``milestone_road_route``, RNF-017-09). **Lo que se
comprueba de la ruta no sale de ``design.road_route``**: cada condición de RF-017-10 (la pendiente de cada paso, el cambio de rumbo, la
distancia vertical al terreno y los nodos que no se pisan) y el coste del paso (su fórmula, con el desvío medido en la media de los dos
extremos, P-7) se recalculan aquí desde los nodos, los rumbos y las cotas de la ruta y la malla; la comparación del coste con un oráculo
de fuerza bruta es de la T09 (``test_road_route_oracle``).
"""

from __future__ import annotations

import dataclasses
import math
import unittest
from typing import Any

import numpy as np

from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.support.timing import drive_steps, least_of

road_route = import_geoblender("design.road_route")
road_net = import_geoblender("design.road_net")
road_model = import_geoblender("design.road_model")
project_model = import_geoblender("core.project.model")
gis = import_geoblender("gis")

CELL_M = 4.0
"""El lado de un nodo de la malla de los casos (m); con un bloque de ``factor`` celdas por lado, la celda mide ``CELL_M / factor``."""
STEP_LIMIT_S = 0.2
"""Lo que dura una llamada del paso como mucho (RNF-017-06)."""
HYPOTHESES = rd.route_with(mesh_m=CELL_M, level_step_m=0.25, max_cut_fill_m=1.0, lambda_per_m=2.0, turn_m=2.0, margin_m=40.0,
                           simplify_m=4.0, arrival_tol_m=0.25, search_budget=5_000_000)
"""Los parámetros de la ruta de los casos pequeños: HIPÓTESIS de la prueba (T01-a; ninguna es valor por defecto del producto): 4 m de
malla, un paso de cota de 0,25 m (un nivel es la décima parte de la pendiente de un paso recto), 1 m de altura (``M = 4`` niveles a
cada lado), λ = 2 1/m, un giro de 2 m y 40 m de holgura."""


def build(surface: np.ndarray, origin: tuple[int, int], destination: tuple[int, int], *, route: Any = None, pd_pct: float = 10.0,
          factor: int = 1, **options: Any) -> tuple[Any, Any, Any]:
    """El trabajo, la malla y el pasillo de una ruta entre dos **nodos** ``(i, j)`` (sus centros) de la malla de ``route.mesh_m`` m, con
    celdas de ``mesh_m / factor`` m (``surface`` y las máscaras de ``options`` son de las celdas)."""
    route = HYPOTHESES if route is None else route
    cell = route.mesh_m / factor
    rows, cols = surface.shape
    grid = gis.Grid(west=500_000.0, north=4_400_000.0, dx=cell, dy=cell, ncols=cols, nrows=rows)

    def center(node: tuple[int, int]) -> tuple[float, float]:
        return (grid.west + (node[1] + 0.5) * route.mesh_m, grid.north - (node[0] + 0.5) * route.mesh_m)

    job = rd.route_job(grid, surface, center(origin), center(destination), route=route,
                       profile=rd.profile_with(max_gradient_pct=pd_pct), **options)
    mesh, corridor = rd.route_corridor(job)
    return job, mesh, corridor


def build_at(surface: np.ndarray, origin: tuple[float, float], destination: Any, *, route: Any = None, pd_pct: float = 10.0, **options: Any) -> Any:
    """El trabajo de una ruta entre dos **puntos** absolutos (o hasta un ``LevelDestination``) de la malla de ``route.mesh_m`` m sobre celdas de ese lado: como :func:`build` pero sin
    pasar por el centro de un nodo (dos puntos pueden caer en el mismo nodo)."""
    route = HYPOTHESES if route is None else route
    rows, cols = surface.shape
    grid = gis.Grid(west=500_000.0, north=4_400_000.0, dx=route.mesh_m, dy=route.mesh_m, ncols=cols, nrows=rows)
    return rd.route_job(grid, surface, origin, destination, route=route, profile=rd.profile_with(max_gradient_pct=pd_pct), **options)


def node_center(node: tuple[int, int], mesh_m: float = CELL_M) -> tuple[float, float]:
    """El centro absoluto del nodo ``(i, j)`` de la malla de los casos (la de :func:`build` con ``factor`` 1)."""
    return (500_000.0 + (node[1] + 0.5) * mesh_m, 4_400_000.0 - (node[0] + 0.5) * mesh_m)


def run(steps: Any) -> Any:
    """Recorre los pasos: la ``Route`` del último (``Progress`` solo el último lleva el resultado)."""
    found, count = None, 0
    for step in steps:
        count += 1
        assert isinstance(step, project_model.Progress)
        if step.result is not None:
            found = step.result
    assert count >= 1
    return found


def solve(job: Any, corridor: Any) -> Any:
    return run(road_route.route_steps(job, corridor))


def flat(rows: int, cols: int, level: float = 100.0) -> np.ndarray:
    return np.full((rows, cols), level)


def rolling(seed: int, rows: int, cols: int, *, factor: int = 1) -> np.ndarray:
    """Un terreno al azar de ``rows × cols`` nodos: una tendencia del 2 % hacia el este y tres ondas de 0,13 m de amplitud (pendientes de
    paso muy por debajo del 10 % de pd, así que casi todo paso es admisible); con ``factor``, de celdas de ``factor × factor`` por nodo."""
    rng = np.random.default_rng(seed)
    i, j = np.indices((rows, cols))
    z = 100.0 + 0.02 * j * CELL_M
    for _ in range(3):
        ky, kx = rng.uniform(0.15, 0.5, 2)
        phase = rng.uniform(0.0, 6.28, 2)
        z = z + 0.13 * np.sin(kx * j + phase[0]) * np.cos(ky * i + phase[1])
    return np.kron(z, np.ones((factor, factor)))


def walls(seed: int, rows: int, cols: int, *, factor: int = 1) -> np.ndarray:
    """Dos muros de nodos prohibidos (columnas enteras salvo un hueco de cinco nodos al azar cerca de la mitad), de celdas de ``factor ×
    factor``."""
    rng = np.random.default_rng(seed)
    wall = np.zeros((rows, cols), dtype=bool)
    for column in (cols // 3, 2 * cols // 3):
        wall[:, column] = True
        gap = int(rng.integers(rows // 2 - 4, rows // 2 - 1))
        wall[gap:gap + 5, column] = False
    return np.kron(wall, np.ones((factor, factor), dtype=bool)).astype(bool)


def verify(test: unittest.TestCase, job: Any, mesh: Any, route: Any) -> None:
    """RF-017-10 y RF-017-06 **recalculados** sin ``design.road_route``: (a) la pendiente de cada paso ≤ pd, (b) el rumbo cambia a lo sumo
    al contiguo, (c) ``|cota − terreno| ≤ H`` en cada nodo, (d) ningún nodo —ni los que cruza un paso «de caballo»— que no se pisa; que el
    rumbo de cada nodo es el paso que llega a él; el coste del paso, con su fórmula (P-7: el desvío en la media de los dos extremos, el
    peso en la media de los dos nodos, el giro por rumbo cambiado), y los giros."""
    pd = job.profile.max_gradient_pct / 100.0
    params = job.route
    nodes, headings, levels = route.nodes, route.headings, route.levels_m
    test.assertTrue(route.ok)
    test.assertIsNone(route.cause)
    count = len(nodes)
    test.assertGreaterEqual(count, 1)
    test.assertEqual((len(headings), len(levels), route.centers.shape), (count, count, (count, 2)))
    total, turns = 0.0, 0
    for index, (i, j) in enumerate(nodes):
        test.assertTrue(mesh.walkable[i, j], (i, j))  # (d)
        test.assertLessEqual(abs(float(levels[index]) - float(mesh.z[i, j])), params.max_cut_fill_m + 1e-9)  # (c)
        test.assertEqual(route.centers[index].tolist(), list(mesh.center_of(i, j)))
        if index == 0:
            continue
        previous_i, previous_j = nodes[index - 1]
        step = (j - previous_j, previous_i - i)  # (dx, dy)
        test.assertEqual(rd.ORACLE_HEADINGS[headings[index]], step)
        turn = (headings[index] - headings[index - 1]) % 16
        test.assertIn(turn, (0, 1, 15))  # (b)
        length = mesh.mesh_m * math.hypot(*step)
        test.assertLessEqual(abs(float(levels[index]) - float(levels[index - 1])), pd * length + 1e-9)  # (a)
        dx, dy = step
        between: tuple[tuple[int, int], ...] = ()
        if abs(dx) == 2:
            between = ((dx // 2, 0), (dx // 2, dy))
        elif abs(dy) == 2:
            between = ((0, dy // 2), (dx, dy // 2))
        for mid_x, mid_y in between:
            test.assertTrue(mesh.walkable[previous_i - mid_y, previous_j + mid_x], (previous_i - mid_y, previous_j + mid_x))  # (d)
        gap = (abs(float(levels[index]) - float(mesh.z[i, j])) + abs(float(levels[index - 1]) - float(mesh.z[previous_i, previous_j]))) / 2
        weight = 1.0 if mesh.weight is None else (float(mesh.weight[i, j]) + float(mesh.weight[previous_i, previous_j])) / 2
        total += length * (1.0 + params.lambda_per_m * gap) * weight + params.turn_m * (turn != 0)
        turns += turn != 0
    test.assertAlmostEqual(route.cost, total, delta=2e-9 * count + 1e-9)
    test.assertEqual(route.turns, turns)
    test.assertEqual(route.cost, route.cost_units / road_route.COST_SCALE)


def fingerprint(route: Any) -> tuple[Any, ...]:
    """Todo lo que identifica una ruta, comparable bit a bit."""
    return (route.ok, route.cause, route.nodes, route.headings, route.levels_m.tobytes(), route.centers.tobytes(), route.cost,
            route.cost_units, route.turns, route.expanded, route.seen)


class ConditionsTest(unittest.TestCase):
    def test_the_route_respects_each_condition_of_the_spec(self) -> None:
        """RF-017-10, RF-017-06 (RF-017-11): en terrenos al azar de 14 × 18 nodos con dos muros con hueco (nodos prohibidos) y con bloques
        de 1 y de 2 celdas, la ruta cumple (a) pendiente de cada paso ≤ pd, (b) rumbo que cambia a lo sumo al contiguo, (c) ``|cota −
        terreno| ≤ H`` y (d) ningún nodo prohibido (ni los que cruza un paso «de caballo»); y su coste es el de la fórmula, sin salir de la
        cota inferior de la red 2D."""
        for seed, factor in ((1, 1), (2, 1), (3, 2), (4, 1), (5, 2), (6, 1)):
            rows, cols = 14, 18
            surface = rolling(seed, rows, cols, factor=factor)
            wall = walls(seed, rows, cols, factor=factor)
            origin, destination = (7, 1), (6, 16)
            job, mesh, corridor = build(surface, origin, destination, factor=factor, untouchable=wall)
            with self.subTest(seed=seed, factor=factor):
                self.assertTrue(corridor.reachable)
                route = solve(job, corridor)
                verify(self, job, mesh, route)
                self.assertEqual((route.nodes[0], route.nodes[-1]), (origin, destination))
                self.assertGreaterEqual(route.cost + 1e-9, corridor.lower_bound_m)
                self.assertGreater(route.expanded, len(route.nodes))
                self.assertGreaterEqual(route.seen, route.expanded)
                self.assertFalse(any(wall[i * factor, j * factor] for i, j in route.nodes))

    def test_a_wall_with_a_gap_makes_the_route_go_through_the_gap(self) -> None:
        """RF-017-06: con un muro de nodos prohibidos (una columna entera salvo un hueco al norte), la ruta atraviesa el hueco: es más larga
        que la recta que cruzaría el muro y ninguno de sus nodos es del muro."""
        wall = np.zeros((11, 13), dtype=bool)
        wall[:, 6] = True
        wall[1:3, 6] = False
        job, mesh, corridor = build(flat(11, 13), (8, 1), (8, 11), untouchable=wall)
        route = solve(job, corridor)
        verify(self, job, mesh, route)
        self.assertFalse(any(wall[node] for node in route.nodes))
        self.assertTrue(any(node[1] == 6 and node[0] in (1, 2) for node in route.nodes))
        self.assertGreater(route.cost, 10 * CELL_M * 1.05)

    def test_with_the_height_zero_the_route_follows_the_terrain(self) -> None:
        """RF-017-10, RF-017-11 (``s23``: con altura 0, la pista que sigue el terreno): con ``H = 0`` hay un solo nivel y la cota de cada
        nodo es la del terreno; en un plano sin restricciones la ruta de un rumbo de la rejilla es la recta (ocho pasos de 4 m, 32,000 m, ni un
        giro) y en un talud del 2 % hacia el este, la misma."""
        route_h0 = rd.route_with(**{**dataclasses.asdict(HYPOTHESES), "max_cut_fill_m": 0.0})
        for terrain in (flat(9, 13), 100.0 + 0.005 * np.indices((9, 13))[1] * CELL_M):
            job, mesh, corridor = build(terrain, (4, 2), (4, 10), route=route_h0)
            route = solve(job, corridor)
            with self.subTest(terrain=float(terrain[0, -1])):
                verify(self, job, mesh, route)
                self.assertEqual(route.nodes, tuple((4, j) for j in range(2, 11)))
                self.assertEqual(route.headings, (4,) * 9)
                self.assertTrue(np.array_equal(route.levels_m, mesh.z[4, 2:11]))
                self.assertEqual((route.cost, route.turns), (32.0, 0))

    def test_the_start_and_the_end_are_at_the_level_the_job_gives(self) -> None:
        """RF-017-10 (RF-017-02, D-13): la ruta arranca en el origen en el nivel de la cota de inicio y acaba en el destino en el de la cota
        de fin (el más próximo: el paso de cota es de 0,25 m, así que 0,6 m son dos niveles y 0,5 m); sin ellas, en la del terreno; una cota
        de inicio fuera de la altura máxima de desmonte y terraplén no deja arrancar (no hay estado): la ruta sale sin estados expandidos."""
        for start, end, expected_start, expected_end in ((0.5, -0.25, 100.5, 99.75), (0.6, 0.4, 100.5, 100.5), (None, None, 100.0, 100.0)):
            job, mesh, corridor = build(flat(9, 13), (4, 2), (4, 10), start_level_m=None if start is None else 100.0 + start,
                                        end_level_m=None if end is None else 100.0 + end)
            route = solve(job, corridor)
            with self.subTest(start=start, end=end):
                verify(self, job, mesh, route)
                self.assertAlmostEqual(float(route.levels_m[0]), expected_start, delta=1e-12)
                self.assertAlmostEqual(float(route.levels_m[-1]), expected_end, delta=1e-12)
        job, _mesh, corridor = build(flat(9, 13), (4, 2), (4, 10), start_level_m=101.3)
        route = solve(job, corridor)
        self.assertFalse(route.ok)
        self.assertEqual(route.cause, road_model.NoRouteCause.CORRIDOR)
        self.assertEqual((route.expanded, route.nodes), (0, ()))

    def test_the_start_heading_is_free(self) -> None:
        """RF-017-10: la ruta arranca con los 16 rumbos a coste 0: el rumbo de partida no cuesta giro; con una penalización de giro enorme, la
        ruta recta y la de un solo paso «de caballo» no pagan ninguno."""
        huge = rd.route_with(**{**dataclasses.asdict(HYPOTHESES), "turn_m": 1000.0})
        job, mesh, corridor = build(flat(9, 13), (4, 2), (4, 8), route=huge)
        route = solve(job, corridor)
        verify(self, job, mesh, route)
        self.assertEqual((route.cost, route.turns), (24.0, 0))
        job, mesh, corridor = build(flat(9, 13), (4, 2), (3, 4), route=huge)
        route = solve(job, corridor)
        verify(self, job, mesh, route)
        self.assertEqual((route.nodes, route.headings, route.turns), (((4, 2), (3, 4)), (3, 3), 0))
        self.assertAlmostEqual(route.cost, CELL_M * math.sqrt(5.0), delta=2e-9)


def cliff_terrain(rows: int, cols: int, high: float, column: int) -> np.ndarray:
    """Un llano con un escalón de ``high`` m en todas las filas desde la columna ``column``: no se puede rodear."""
    terrain = flat(rows, cols)
    terrain[:, column:] += high
    return terrain


def route_with_levels(height: float, step: float, **changes: Any) -> Any:
    """Los parámetros de los casos de ``HYPOTHESES`` con otra altura máxima y otro paso de cota (y una holgura enorme: el pasillo es todo lo que alcanza la red 2D)."""
    return rd.route_with(**{**dataclasses.asdict(HYPOTHESES), "max_cut_fill_m": height, "level_step_m": step, "margin_m": 100_000.0, **changes})


class LevelJumpTest(unittest.TestCase):
    """RF-017-10 (a), B-1 de la verificación única (T41): los saltos de nivel de un paso se recortan a ±2M y un intervalo **vacío** entero fuera de ellos no se da por bueno."""

    def test_a_step_never_passes_pd_when_the_height_is_not_a_multiple_of_the_level_step(self) -> None:
        """RF-017-10 (a), RF-017-12: con H = 0,5 m y un paso de cota de 0,28 m (H **no** es múltiplo: M = 1 y los niveles solo cubren ±0,28 m, aunque la red 2D admite |Δterreno| ≤ pd·L + 2H) la ruta que
        cruza un escalón de 1,2 m o de 1,35 m no tiene un paso por encima de pd (antes cruzaba con el 16 % y el 19,75 % siendo pd el 10 %: ``verify`` recalcula la pendiente de cada paso); con el
        paso de 0,25 m (H sí es múltiplo) y con un escalón que sí se salva, la ruta es la de siempre."""
        for step, high in ((0.28, 1.2), (0.28, 1.35), (0.25, 1.2), (0.3, 1.0)):
            job, mesh, corridor = build(cliff_terrain(9, 13, high, 7), (4, 2), (4, 11), route=route_with_levels(0.5, step))
            route = solve(job, corridor)
            with self.subTest(step=step, cliff=high):
                self.assertTrue(corridor.reachable)
                self.assertTrue(route.ok)
                verify(self, job, mesh, route)

    def test_a_level_step_bigger_than_the_height_follows_the_terrain_and_a_cliff_it_cannot_cross_is_no_route(self) -> None:
        """RF-017-10 (a), RF-017-12: con un paso de cota mayor que H (M = 0: un solo nivel, la cota del terreno) la ruta sigue el terreno: un escalón de 0,35 m se cruza en un paso recto (pd · 4 m =
        0,4 m) y uno de 1 m, que la red 2D admite (≤ pd·L + 2H), **no se cruza**: la búsqueda lo dice (``CORRIDOR``, sin ruta) en vez de cruzarlo con el 15 % de pendiente de más."""
        job, mesh, corridor = build(cliff_terrain(9, 13, 0.35, 7), (4, 2), (4, 11), route=route_with_levels(0.5, 0.6))
        verify(self, job, mesh, solve(job, corridor))
        job, mesh, corridor = build(cliff_terrain(9, 13, 1.0, 7), (4, 2), (4, 11), route=route_with_levels(0.5, 0.6))
        route = solve(job, corridor)
        self.assertTrue(corridor.reachable)
        self.assertEqual((route.ok, route.cause), (False, road_model.NoRouteCause.CORRIDOR))
        self.assertEqual(route.nodes, ())


class DeterminismTest(unittest.TestCase):
    def test_the_same_inputs_give_the_same_route_bit_for_bit(self) -> None:
        """RF-017-10 (RF-015-02, D-23): con las mismas entradas, la misma ruta bit a bit en dos ejecuciones; y con las celdas, los muros y los
        pesos construidos en **otro orden** (los mismos arrays), también: ni el orden de las celdas ni el de los muros cambia nada."""
        rows, cols = 12, 16
        surface = rolling(7, rows, cols)
        wall = walls(7, rows, cols)
        weight = np.ones((rows, cols))
        weight[3:6, 7:10] = 3.0
        job, mesh, corridor = build(surface, (6, 1), (5, 14), untouchable=wall, avoid_weight=weight)
        first, second = solve(job, corridor), solve(job, corridor)
        verify(self, job, mesh, first)
        self.assertEqual(fingerprint(first), fingerprint(second))
        shuffled = np.empty_like(surface)
        for row in reversed(range(rows)):  # las celdas por filas, de la última a la primera
            shuffled[row] = surface[row]
        other_wall = np.zeros((rows, cols), dtype=bool)
        for column in reversed(range(cols)):  # los muros por columnas, de la última a la primera
            other_wall[:, column] = wall[:, column]
        other_weight = np.ones((rows, cols))
        other_weight[5, 9] = other_weight[3, 7] = 3.0
        for row in (4, 3, 5):
            other_weight[row, 7:10] = 3.0
        self.assertTrue(np.array_equal(other_weight, weight))
        job_b, mesh_b, corridor_b = build(shuffled, (6, 1), (5, 14), untouchable=other_wall, avoid_weight=other_weight)
        self.assertEqual(fingerprint(solve(job_b, corridor_b)), fingerprint(first))
        self.assertTrue(np.array_equal(mesh_b.z, mesh.z))

    def test_the_tie_of_a_symmetric_plane_is_fewest_turns_then_first_heading_clockwise_from_the_north(self) -> None:
        """RF-017-10, D-23, RF-015-02: en un plano simétrico y sin penalización de giro, a 4 nodos al este y 1 al norte hay tres rutas del
        mismo coste (``2·4 m + √5·4 m``, **exacto**: el coste es entero): el paso (2, 1) puede ir primero, en medio o último y los otros
        dos son al este. Gana la de **menos giros** (la de dos giros, este-(2, 1)-este, pierde) y, entre las de un giro, la del **primer
        rumbo en sentido horario desde el norte** al llegar (el (2, 1) es el 3 y el este, el 4): este, este y (2, 1). Al sur, a 4 al este y
        1 al sur, el (2, −1) es el 5 y el este, el 4: gana la de llegar al este, la del (2, −1) primero."""
        zero = rd.route_with(**{**dataclasses.asdict(HYPOTHESES), "turn_m": 0.0})
        for destination, expected_nodes, expected_headings in (
                ((3, 6), ((4, 2), (4, 3), (4, 4), (3, 6)), (4, 4, 4, 3)),
                ((5, 6), ((4, 2), (5, 4), (5, 5), (5, 6)), (5, 5, 4, 4))):
            job, mesh, corridor = build(flat(9, 13), (4, 2), destination, route=zero)
            route = solve(job, corridor)
            with self.subTest(destination=destination):
                verify(self, job, mesh, route)
                self.assertEqual(route.nodes, expected_nodes)
                self.assertEqual(route.headings, expected_headings)
                self.assertEqual(route.turns, 1)
                self.assertEqual(route.cost_units, 2 * 4_000_000_000 + round(4_000_000_000 * math.sqrt(5.0)))
        again = solve(job, corridor)
        self.assertEqual(fingerprint(again), fingerprint(route))

    def test_a_turn_costs_its_penalty_and_the_tie_is_resolved_the_same_way(self) -> None:
        """RF-017-10, D-23: con penalización de giro (2 m por rumbo cambiado) a 4 nodos al este y 1 al norte, la ruta es la misma que sin ella
        (de las de un giro gana la de llegar con el rumbo 3: este, este y (2, 1)) y cuesta además la penalización de su único giro, sin pagar
        ninguna por el rumbo de partida; la de dos giros pierde por su coste y no por el desempate."""
        job, mesh, corridor = build(flat(9, 13), (4, 2), (3, 6))
        route = solve(job, corridor)
        verify(self, job, mesh, route)
        self.assertEqual((route.nodes, route.headings, route.turns), (((4, 2), (4, 3), (4, 4), (3, 6)), (4, 4, 4, 3), 1))
        self.assertEqual(route.cost_units, 2 * 4_000_000_000 + round(4_000_000_000 * math.sqrt(5.0)) + 2_000_000_000)


class WeightTest(unittest.TestCase):
    def test_the_weight_of_the_zones_to_avoid_bends_the_route(self) -> None:
        """RF-017-06 (P-7, plan §5.8 H-6): con el peso de «preferible no afectar» (8) en cinco filas por cinco columnas de nodos en medio
        de la recta, la ruta la rodea (ninguno de sus nodos es de la zona) y cuesta lo que dice la fórmula con el peso en la media de los dos
        nodos; sin zona, la recta atraviesa esa zona; con todo a peso 1, la ruta es la misma que sin pesos, bit a bit."""
        weight = np.ones((11, 15))
        weight[3:8, 5:10] = 8.0
        origin, destination = (5, 1), (5, 13)
        plain = solve(*build(flat(11, 15), origin, destination)[::2])
        self.assertEqual(plain.nodes, tuple((5, j) for j in range(1, 14)))  # la recta, por la zona
        job, mesh, corridor = build(flat(11, 15), origin, destination, avoid_weight=weight)
        weighted = solve(job, corridor)
        verify(self, job, mesh, weighted)  # el coste, con el peso
        self.assertFalse(any(weight[node] > 1.0 for node in weighted.nodes))
        self.assertGreater(plain.cost, 0.0)
        self.assertGreater(weighted.cost, plain.cost)
        self.assertLess(weighted.cost, 8.0 * plain.cost / 2.0)  # rodearla es mejor que atravesarla
        ones_job, _ones_mesh, ones_corridor = build(flat(11, 15), origin, destination, avoid_weight=np.ones((11, 15)))
        self.assertEqual(fingerprint(solve(ones_job, ones_corridor)), fingerprint(plain))


class DestinationTest(unittest.TestCase):
    def test_a_set_of_nodes_is_a_destination_and_the_route_ends_in_the_nearest_of_them(self) -> None:
        """RF-017-10 (D-4, el destino por cota que prepara T08): con un conjunto de nodos de destino (la zona de la rampa), la ruta acaba al
        **extraer** el primero que alcanza —el más barato— y su nivel es el de la cota pedida (el más próximo): en un talud del 4 % hacia el
        este, la cota de la columna 9 menos medio metro es de dos niveles bajo el terreno (la ruta recta del este los baja en el camino: sube
        0,16 m por paso y el paso de 4 m admite 0,4 m de pendiente). La tolerancia de llegada no interviene en la búsqueda: con ella arma
        T08 el conjunto de nodos."""
        terrain = 100.0 + 0.04 * (np.indices((11, 14))[1] + 0.5) * CELL_M
        column = 9
        level = float(terrain[0, column]) - 0.5
        zone = np.zeros((11, 14), dtype=bool)
        zone[3:8, column] = True
        corners = np.array([[[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0]]])
        destination = road_model.LevelDestination(level, 0.6, (tuple(corners),))
        grid = gis.Grid(west=500_000.0, north=4_400_000.0, dx=CELL_M, dy=CELL_M, ncols=14, nrows=11)
        origin = (grid.west + 1.5 * CELL_M, grid.north - 5.5 * CELL_M)  # el nodo (5, 1)
        job = rd.route_job(grid, terrain, origin, destination, route=HYPOTHESES)
        mesh, corridor = rd.route_corridor(job, target=zone)
        route = solve(job, corridor)
        self.assertTrue(route.ok)
        self.assertEqual(route.nodes[0], (5, 1))
        self.assertEqual(route.nodes[-1], (5, column))  # la fila del origen: el más próximo
        self.assertTrue(all(not zone[node] for node in route.nodes[:-1]))  # el primero de la zona que alcanza
        self.assertAlmostEqual(float(route.levels_m[-1]), level, delta=1e-9)  # z − 2·0,25 m
        self.assertAlmostEqual(float(route.levels_m[-1] - mesh.z[5, column]), -0.5, delta=1e-9)
        verify(self, job, mesh, route)


class NoRouteTest(unittest.TestCase):
    DESCENT = {"start_level_m": 101.0, "end_level_m": 99.0}
    """Bajar 2 m (8 niveles de 0,25 m) en pasos de a lo sumo un nivel (pd · 4 m = 0,4 m: ±1 nivel por paso)."""

    def test_the_corridor_that_has_no_3d_route_is_exhausted_and_it_is_not_the_budget(self) -> None:
        """RF-017-10, RF-017-12 (P-3): si la red 2D alcanza el origen y el pasillo no contiene ninguna ruta 3D (aquí, bajar 2 m en cinco pasos
        rectos de a lo sumo 0,25 m cada uno, con la holgura 0: el pasillo es la recta), la búsqueda agota el pasillo: ``ok`` falso, sin ruta y
        con la causa del pasillo, **no** la del presupuesto; con más holgura (60 m: el pasillo es una elipse y la ruta serpentea hasta
        tener el recorrido que pide la pendiente) hay ruta."""
        tight = rd.route_with(**{**dataclasses.asdict(HYPOTHESES), "margin_m": 0.0})
        job, _mesh, corridor = build(flat(15, 20), (7, 5), (7, 10), route=tight, **self.DESCENT)
        self.assertTrue(corridor.reachable)
        self.assertEqual(corridor.nodes, 6)
        route = solve(job, corridor)
        self.assertFalse(route.ok)
        self.assertEqual(route.cause, road_model.NoRouteCause.CORRIDOR)
        self.assertEqual((route.nodes, route.headings, route.cost, route.cost_units, route.turns), ((), (), None, None, 0))
        self.assertGreater(route.expanded, 0)
        self.assertEqual(route.centers.shape, (0, 2))
        self.assertEqual(route.levels_m.shape, (0,))
        wide = rd.route_with(**{**dataclasses.asdict(HYPOTHESES), "margin_m": 60.0})
        job, mesh, corridor = build(flat(15, 20), (7, 5), (7, 10), route=wide, **self.DESCENT)
        found = solve(job, corridor)
        verify(self, job, mesh, found)
        self.assertGreaterEqual(len(found.nodes), 9)  # ocho pasos de a lo sumo un nivel
        self.assertAlmostEqual(float(found.levels_m[0] - found.levels_m[-1]), 2.0, delta=1e-12)

    def test_the_budget_stops_the_search_and_says_how_many_states_it_expanded(self) -> None:
        """RF-017-10, RF-017-12 (P-3, ADOPTADO «sin confirmar»): la búsqueda se detiene a ``search_budget`` estados **expandidos**: la ruta
        sale ``ok`` falso, sin nodos, con los estados expandidos (exactamente el presupuesto) y la causa del presupuesto (no «no hay ruta»);
        con el presupuesto que hacía falta (los expandidos de una corrida entera) la ruta es la misma, y con uno menos no se llega."""
        job, mesh, corridor = build(flat(11, 30), (5, 1), (5, 28))
        full = solve(job, corridor)
        verify(self, job, mesh, full)
        needed = full.expanded
        self.assertGreater(needed, 20)
        for budget in (1, 5, needed - 1):
            small = rd.route_with(**{**dataclasses.asdict(HYPOTHESES), "search_budget": budget})
            job_b, _mesh_b, corridor_b = build(flat(11, 30), (5, 1), (5, 28), route=small)
            route = solve(job_b, corridor_b)
            with self.subTest(budget=budget):
                self.assertFalse(route.ok)
                self.assertEqual(route.cause, road_model.NoRouteCause.BUDGET)
                self.assertEqual((route.expanded, route.nodes, route.cost), (budget, (), None))
                self.assertEqual(route.budget, budget)
                self.assertGreaterEqual(route.seen, budget)
        exact = rd.route_with(**{**dataclasses.asdict(HYPOTHESES), "search_budget": needed})
        job_c, _mesh_c, corridor_c = build(flat(11, 30), (5, 1), (5, 28), route=exact)
        self.assertEqual(fingerprint(solve(job_c, corridor_c))[2:], fingerprint(full)[2:])
        self.assertEqual(road_model.NoRouteCause.BUDGET.value, "des.road_budget")

    def test_an_origin_the_network_does_not_reach_has_no_route(self) -> None:
        """RF-017-10, RF-017-12: si la red 2D no alcanza el origen (cercado por nodos prohibidos) no hay pasillo ni búsqueda: ``ok`` falso, sin
        estados expandidos y con la causa de la red (el diagnóstico es de T08)."""
        ring = np.zeros((9, 9), dtype=bool)
        ring[3:6, 3:6] = True
        ring[4, 4] = False
        job, _mesh, corridor = build(flat(9, 9), (4, 4), (4, 8), untouchable=ring)
        self.assertFalse(corridor.reachable)
        route = solve(job, corridor)
        self.assertFalse(route.ok)
        self.assertEqual(route.cause, road_model.NoRouteCause.NETWORK)
        self.assertEqual((route.expanded, route.seen, route.nodes), (0, 0, ()))


class StepsTest(unittest.TestCase):
    EXHAUSTING = {"start_level_m": 101.0, "end_level_m": 99.0}

    def exhausting(self, budget: int) -> tuple[Any, Any, Any]:
        """Un caso que agota el presupuesto: bajar 2 m entre dos nodos a 20 m en un plano de 15 × 20 nodos con 60 m de holgura (la ruta
        existe y serpentea, pero hacen falta unos 20.000 estados expandidos: más que los presupuestos de estas pruebas)."""
        route = rd.route_with(**{**dataclasses.asdict(HYPOTHESES), "margin_m": 60.0, "search_budget": budget})
        return build(flat(15, 20), (7, 5), (7, 10), route=route, **self.EXHAUSTING)

    def test_the_steps_report_progress_and_the_last_one_carries_the_route(self) -> None:
        """RNF-017-06, RF-017-10: la ruta va por pasos con su progreso (``Progress`` de la fase de la ruta, de uno en uno hasta el total) y
        solo el último lleva el resultado (la ``Route``), el mismo que el de otra corrida con otro presupuesto de tiempo."""
        job, _mesh, corridor = self.exhausting(6_000)
        seen: list[Any] = list(road_route.route_steps(job, corridor, budget_s=0.004))
        self.assertGreater(len(seen), 2)
        self.assertEqual({step.phase for step in seen}, {"road_route"})
        self.assertEqual([step.done for step in seen[:-1]], list(range(1, len(seen))))
        self.assertTrue(all(step.result is None for step in seen[:-1]))
        self.assertEqual(seen[-1].done, seen[-1].total)
        final = seen[-1].result
        self.assertFalse(final.ok)
        self.assertEqual((final.cause, final.expanded), (road_model.NoRouteCause.BUDGET, 6_000))
        self.assertEqual(fingerprint(final), fingerprint(solve(job, corridor)))

    def test_each_call_of_a_step_is_within_the_budget(self) -> None:
        """RNF-017-06: cada llamada del paso de la ruta (la que el hilo de Blender hace a ``next``) tarda como mucho 0,2 s, con miles de
        estados expandidos (se ceden cada 2.000); con la máquina cargada, se mide otra vez (la medida es del código, no de los demás
        procesos)."""
        job, _mesh, corridor = self.exhausting(5_000)

        def longest() -> float:
            return drive_steps(road_route.route_steps(job, corridor, budget_s=0.004)).longest_s

        run_of_steps = drive_steps(road_route.route_steps(job, corridor, budget_s=0.004))
        self.assertGreater(run_of_steps.steps, 1)
        self.assertEqual(run_of_steps.result.expanded, 5_000)
        self.assertLessEqual(least_of(longest, STEP_LIMIT_S, attempts=3), STEP_LIMIT_S)

    def test_closing_in_the_middle_leaves_nothing(self) -> None:
        """RNF-017-06, RF-017-10: cerrar el generador a mitad no deja nada: ni resultado a medias, ni cambios en la malla ni en el pasillo
        (solo se leen) ni nada que impida volver a calcular, con el mismo resultado; sin empezar, tampoco hay nada que deshacer."""
        job, mesh, corridor = self.exhausting(6_000)
        kept = (mesh.z.copy(), mesh.walkable.copy(), corridor.mask.copy(), corridor.net_dest.dist.copy(), job.start.copy())
        steps = road_route.route_steps(job, corridor, budget_s=0.004)
        first = next(steps)
        self.assertIsNone(first.result)
        steps.close()  # type: ignore[attr-defined]
        self.assertEqual(list(steps), [])
        for array, before in zip((mesh.z, mesh.walkable, corridor.mask, corridor.net_dest.dist, job.start), kept, strict=True):
            self.assertTrue(np.array_equal(array, before, equal_nan=True))
        again = solve(job, corridor)
        self.assertEqual(again.expanded, 6_000)
        never = road_route.route_steps(job, corridor)
        never.close()  # type: ignore[attr-defined]
        self.assertEqual(list(never), [])


class ContractTest(unittest.TestCase):
    def test_the_route_is_read_only_and_does_not_carry_a_length_or_a_volume(self) -> None:
        """RF-017-09, RF-017-10: la ruta es inmutable y sus arrays, de solo lectura; ninguna cifra de volumen ni de longitud de la pista sale
        de la malla de la ruta: ningún campo de la ``Route`` lo es (el coste es una cifra de búsqueda, no una longitud); el coste es entero
        (en nanómetros) y ``cost`` es ese entero en metros."""
        job, _mesh, corridor = build(flat(9, 13), (4, 2), (4, 8))
        route = solve(job, corridor)
        self.assertTrue(dataclasses.is_dataclass(route))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            route.cost = 0.0  # type: ignore[misc]
        for array in (route.levels_m, route.centers):
            self.assertFalse(array.flags.writeable)
        names = {field.name for field in dataclasses.fields(road_route.Route)}
        self.assertFalse({name for name in names if any(word in name for word in ("volume", "cut", "fill", "length"))})
        self.assertEqual(road_route.COST_SCALE, 10 ** 9)
        self.assertIsInstance(route.cost_units, int)
        self.assertEqual(route.cost_units, 24_000_000_000)

    def test_the_inputs_are_checked_when_called(self) -> None:
        """RF-017-10: el trabajo es un ``RoadJob`` del modo «trazar» y el pasillo, el de la misma malla, la misma ``pd`` y la misma altura
        que la ruta (si no, la red 2D no es cota de esta búsqueda); el presupuesto de tiempo, finito y positivo: errores del programa que
        se dicen **al llamar**, no al avanzar el primer paso."""
        job, mesh, corridor = build(flat(9, 13), (4, 2), (4, 8))
        with self.assertRaises(TypeError):
            road_route.route_steps(object(), corridor)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            road_route.route_steps(job, object())  # type: ignore[arg-type]
        for budget in (0.0, -1.0, math.nan, math.inf):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                road_route.route_steps(job, corridor, budget_s=budget)
        pd = job.profile.max_gradient_pct / 100.0
        for pd_other, height in ((pd * 2.0, job.route.max_cut_fill_m), (pd, job.route.max_cut_fill_m + 1.0)):
            net = [run(road_net.network_steps(mesh, node, pd_other, height)) for node in ((4, 8), (4, 2))]
            wrong = road_net.corridor(net[1], net[0], 40.0)
            with self.subTest(pd=pd_other, height=height), self.assertRaises(ValueError):
                road_route.route_steps(job, wrong)
        other_mesh = road_net.route_mesh(job.grid, job.start, 2.0 * CELL_M, job.untouchable)
        nets = [run(road_net.network_steps(other_mesh, node, pd, job.route.max_cut_fill_m)) for node in ((2, 4), (2, 1))]
        with self.assertRaises(ValueError):
            road_route.route_steps(job, road_net.corridor(nets[1], nets[0], 40.0))
        on_axis = dataclasses.replace(
            job, request=dataclasses.replace(job.request, mode="on_axis"),
            geometry=road_model.RoadGeometry(line=((500_002.0, 4_399_996.0), (500_012.0, 4_399_990.0))), route=None)
        with self.assertRaises(ValueError):
            road_route.route_steps(on_axis, corridor)


if __name__ == "__main__":
    unittest.main()
