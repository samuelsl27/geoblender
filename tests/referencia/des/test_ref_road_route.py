# SPDX-License-Identifier: GPL-3.0-or-later
"""Casos de referencia de la ruta de la pista (spec 017, T09; HU-017-1; RF-017-09, RF-017-10, RF-017-11 y RF-017-12; CE-017-01 y CE-017-04;
RNF-017-02; plan 017 §5.4 A1 a A3, §7.1; D-22): la parte de la **ruta** de los dos casos, contra el cálculo a mano.

Verifica **de forma independiente** lo que hicieron T06 a T08 (``design.road_net`` y ``design.road_route``): cada cifra sale de un cálculo a mano
(las fórmulas del plano, trigonometría, la distancia más corta de la red de 16 rumbos como una descomposición entera de cada desplazamiento) y de
las cifras de ``tests.support.road_data`` (hechas a mano), y **ningún** valor esperado se calcula llamando al código bajo prueba. Tolerancia de
D-22: ≤ 10⁻⁹ (m o relativo) frente al cálculo a mano en las mismas celdas; la ruta en un plano, ≤ 2,8 % más larga que la recta. Todo es
sintético, en el dominio y sin Blender; los terrenos son los de la cantera de la 014 (400 × 400 celdas de 1 m) y las partes de ella que dice cada caso.

- **CE-017-01 · rampa recta** (RF-017-10, RF-017-11, RF-017-09): sobre un plano del 4 % cuyo sentido de máxima pendiente es un eje de la rejilla, sin
  restricciones y con pd = 8 %, la ruta de 200 m entre dos puntos (cincuenta pasos de 4 m al este) mide **200,000 m**, no gira, su cota es la del
  terreno (**movimiento 0 m**) y su desnivel es de 8,000 m; la cota inferior de la red 2D es esos mismos 200 m. Y en un plano sin restricciones con
  **un rumbo cualquiera** la ruta no pasa de la distancia recta en más de un **2,8 %** (D-22: 1/cos 13,28° − 1 = 2,75 %): su longitud es, además, la
  distancia más corta de la red de 16 rumbos, calculada a mano como la descomposición entera del desplazamiento en dos rumbos contiguos (con y sin
  penalización de giro: con un solo giro basta).
- **CE-017-04 · regresión de B2** (RF-017-11): en un plano del 38 % con la curva de nivel a 22,5° de un eje de la rejilla y pd = 10 %, la menor
  pendiente de paso de los 16 rumbos es del **2,7 %** (0,38·sen 4,065°) y la de los 8 inmediatos, del **14,5 %** (0,38·sen 22,5°), a ≤ 10⁻⁹ relativo
  del cálculo a mano; la ruta existe (con altura 0 y con la de referencia) y no pasa de pd; y, **como demostración y no como criterio**, con solo los 8
  rumbos inmediatos la red 2D a mano (``design_oracles.hand_net``) no tendría ningún paso admisible con altura 0: sin ruta.
- **CE-017-04 · sin ruta** (RF-017-12): la franja de un nodo (100 m, 30 m de desnivel, pd = 10 %: hacen falta 300 m) no tiene ruta y el diagnóstico da la
  cota mayor alcanzada (la del origen + 10 m), la pendiente mínima necesaria (30 %) y el tramo limitante; con el intocable que cierra el único paso, lo
  mismo con su zona; **sin registrar nada** (ni cambia lo que lee). Con los valores de la referencia de IMGA para la altura (14 m) y el paso de cota
  (0,28 m) la franja llega a 105,76 m y no a 110 m: la altura máxima corta antes la subida (anotado en la *Verificación* de la T09; lo decide T37).
"""

from __future__ import annotations

import math
import unittest
from typing import Any

import numpy as np

from tests.support import design_oracles as oracles
from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.unit.design import test_road_route as base
from tests.unit.design.test_road_no_route import strip_case

road_net = import_geoblender("design.road_net")
road_route = import_geoblender("design.road_route")
road_model = import_geoblender("design.road_model")
messages = import_geoblender("design.messages")
gis = import_geoblender("gis")

TOL = 1e-9
"""Metros o relativo (D-22): lo calculado a mano en las mismas celdas."""
MESH_M = rd.ROUTE.mesh_m
"""La malla de la ruta de referencia (4 m): cada nodo es un bloque de 4 × 4 celdas de 1 m."""
EAST = 4
"""El índice del rumbo al este en los 16 (el 0 es el norte, en sentido horario)."""


def local(centers: np.ndarray) -> np.ndarray:
    """Los centros absolutos de una ruta en coordenadas locales (m desde la esquina suroeste de la cantera)."""
    return np.asarray(centers) - np.asarray(rd.BASE)


def polyline_m(points: np.ndarray) -> float:
    """La longitud (m) de la poligonal de ``points`` (``(k, 2)``), por tramos con ``fsum``."""
    return math.fsum(math.hypot(*(points[k + 1] - points[k])) for k in range(len(points) - 1))


def lattice_distance_m(dx: int, dy: int, cell_m: float) -> float:
    """La distancia más corta de la red de 16 rumbos **a mano**: el desplazamiento ``(dx, dy)`` en nodos como ``n·u + k·v`` con ``u`` y ``v`` dos
    rumbos y ``n``, ``k`` enteros no negativos (la solución del sistema 2 × 2 por Cramer, con aritmética entera), de longitud ``n·|u| + k·|v|`` (m);
    el mínimo de todas las parejas. Con dos rumbos contiguos el determinante es ±1 y la solución es siempre entera: es el camino más corto con un solo
    giro entre dos rumbos contiguos."""
    best = math.inf
    for u in rd.ORACLE_HEADINGS:
        for v in rd.ORACLE_HEADINGS:
            det = u[0] * v[1] - u[1] * v[0]
            if det == 0:
                continue
            n_num, k_num = dx * v[1] - dy * v[0], u[0] * dy - u[1] * dx
            if n_num % det or k_num % det:
                continue
            n, k = n_num // det, k_num // det
            if n >= 0 and k >= 0:
                best = min(best, cell_m * (n * math.hypot(*u) + k * math.hypot(*v)))
    return best


class RampTest(unittest.TestCase):
    """CE-017-01, la parte de la ruta: «sobre un plano de pendiente 4 % cuyo sentido de máxima pendiente es el de un rumbo de la ruta (un eje de
    la rejilla), sin restricciones y con pd = 8 %, una pista «trazar» de 200 m entre dos puntos mide 200,000 m, su rasante es el terreno
    (movimiento 0 m)…»."""

    @classmethod
    def setUpClass(cls) -> None:
        grid = rd.GRID
        cls.terrain = rd.ramp_terrain(grid)
        origin = tuple(float(v) for v in rd.absolute([rd.RAMP_ORIGIN], grid)[0])
        destination = tuple(float(v) for v in rd.absolute([rd.RAMP_DESTINATION], grid)[0])
        cls.job = rd.route_job(grid, cls.terrain, origin, destination, route=rd.ROUTE, profile=rd.profile_with(max_gradient_pct=8.0))
        cls.mesh, cls.corridor = rd.route_corridor(cls.job)
        cls.route = base.solve(cls.job, cls.corridor)

    def test_the_straight_ramp_measures_200_m_and_follows_the_terrain(self) -> None:
        """RF-017-10, RF-017-11, CE-017-01, HU-017-1: la ruta de 200 m del plano del 4 % con pd = 8 % son los cincuenta pasos al este entre el nodo del
        origen y el del destino (fila 50 y columnas 25 a 75 de la malla de 4 m, a mano desde las celdas de 1 m): **200,000 m**, ni un giro, el coste
        (sin movimiento de tierras: λ·0) la misma longitud, la cota de cada nodo la del plano (**movimiento 0 m**, 10⁻⁹), una pendiente de paso del
        4,000 % (a ≤ 10⁻⁹) y un desnivel de 8,000 m; cumple cada condición de RF-017-10."""
        route = self.route
        self.assertTrue(route.ok)
        first, last = (rd.cell_of(point) for point in (rd.RAMP_ORIGIN, rd.RAMP_DESTINATION))
        expected = tuple((first[0] // 4, column) for column in range(first[1] // 4, last[1] // 4 + 1))
        self.assertEqual(route.nodes, expected)
        self.assertEqual(len(route.nodes), 51)
        centers = local(route.centers)
        self.assertAlmostEqual(polyline_m(centers), rd.RAMP_LENGTH_M, delta=TOL)
        self.assertEqual((route.turns, route.headings), (0, (EAST,) * 51))
        self.assertAlmostEqual(route.cost, rd.RAMP_LENGTH_M, delta=TOL)
        plane = rd.RAMP_Z0_M + rd.RAMP_SLOPE_PCT / 100.0 * centers[:, 0]
        movement = float(np.abs(route.levels_m - plane).max())
        self.assertLessEqual(movement, TOL)  # el movimiento de la ruta: 0 m
        steps = np.abs(np.diff(route.levels_m)) / MESH_M * 100.0
        self.assertLessEqual(float(np.abs(steps - rd.RAMP_SLOPE_PCT).max()), TOL)  # 4,000 % en cada paso
        self.assertAlmostEqual(float(route.levels_m[-1] - route.levels_m[0]), rd.RAMP_DROP_M, delta=TOL)
        base.verify(self, self.job, self.mesh, route)

    def test_the_lower_bound_of_the_2d_network_is_the_same_200_m(self) -> None:
        """RF-017-09, CE-017-01: la red 2D (la cota inferior de la longitud de la ruta) alcanza el origen desde el destino y da 200,000 m: la
        distancia en línea recta, que en un rumbo de la rejilla la red de 16 rumbos recorre exacta; y el pasillo (la holgura, no el ancho) contiene la
        ruta entera y no es toda la malla."""
        self.assertTrue(self.corridor.reachable)
        self.assertAlmostEqual(self.corridor.lower_bound_m, rd.RAMP_LENGTH_M, delta=TOL)
        self.assertTrue(all(self.corridor.mask[node] for node in self.route.nodes))
        self.assertLess(int(self.corridor.mask.sum()), int(self.corridor.mask.size))


class UnrestrictedPlaneTest(unittest.TestCase):
    """CE-017-01: «en un plano sin restricciones y con un rumbo cualquiera la ruta no pasa de la distancia recta en más de un 2,8 % (D-22)»."""

    DISPLACEMENTS = ((18, 0), (17, 4), (18, 4), (13, 3), (16, 16), (7, 14), (4, 17), (0, 18), (-17, 4), (-18, -11), (15, -7), (5, -17), (11, 2),
                     (19, 5))
    """Desplazamientos ``(dx, dy)`` en nodos al este y al norte, desde un rumbo de la rejilla (el primero) hasta los de mayor hueco entre dos rumbos
    (13,28° del más próximo), por los cuatro cuadrantes."""

    def test_the_bound_of_the_16_headings_is_2_75_percent_and_is_within_2_8(self) -> None:
        """RF-017-11, D-22: el mayor hueco entre dos de los 16 rumbos es el de (1, 0) a (2, 1), de 26,565°, y a la mitad (13,28°) un camino de dos
        rumbos contiguos pasa de la recta en 1/cos 13,28° − 1 = 2,7486 % (a mano), por debajo del 2,8 % de la spec; con todos los desplazamientos
        de hasta 60 nodos por lado, la descomposición entera a mano **no pasa de esa cota y llega a ella** (la cota es ajustada)."""
        bound = 1.0 / math.cos(math.atan(0.5) / 2.0) - 1.0
        self.assertAlmostEqual(bound * 100.0, 2.7486, delta=5e-5)
        self.assertLess(bound * 100.0, rd.DETOUR_BOUND_PCT)
        worst = 0.0
        for dx in range(-60, 61):
            for dy in range(0, 61):
                if (dx, dy) == (0, 0):
                    continue
                worst = max(worst, lattice_distance_m(dx, dy, 1.0) / math.hypot(dx, dy))
        self.assertLessEqual(worst - 1.0, bound + TOL)
        self.assertGreater(worst - 1.0, bound - 1e-3)

    def test_the_route_in_any_direction_is_the_lattice_distance_and_at_most_2_8_percent_longer(self) -> None:
        """RF-017-10, RF-017-11, RF-017-09, D-22, CE-017-01: en un plano del 4 % de 40 × 40 nodos, con pd = 8 % y sin restricciones, desde el centro
        a 14 destinos en todos los cuadrantes, y **con y sin penalización de giro** (la de la referencia, 4 m, y 0), la ruta mide la distancia más
        corta de la red de 16 rumbos calculada a mano (≤ 10⁻⁹ relativo) y **no pasa de la recta en más de un 2,8 %**; la cota inferior de la red 2D es
        esa misma distancia, y la ruta no gira más de una vez."""
        grid = gis.Grid(west=rd.BASE[0], north=rd.BASE[1] + 160.0, dx=1.0, dy=1.0, ncols=160, nrows=160)
        terrain = rd.ramp_terrain(grid)
        worst = 0.0

        def center(node: tuple[int, int]) -> tuple[float, float]:
            return (grid.west + (node[1] + 0.5) * MESH_M, grid.north - (node[0] + 0.5) * MESH_M)

        for turn in (0.0, 4.0):
            for dx, dy in self.DISPLACEMENTS:
                origin, destination = (20, 20), (20 - dy, 20 + dx)
                job = rd.route_job(grid, terrain, center(origin), center(destination), route=rd.route_with(turn_m=turn),
                                   profile=rd.profile_with(max_gradient_pct=8.0))
                mesh, corridor = rd.route_corridor(job)
                route = base.solve(job, corridor)
                with self.subTest(displacement=(dx, dy), turn_m=turn):
                    self.assertTrue(route.ok)
                    self.assertEqual((route.nodes[0], route.nodes[-1]), (origin, destination))
                    length = polyline_m(np.asarray(route.centers))
                    expected = lattice_distance_m(dx, dy, MESH_M)
                    self.assertAlmostEqual(length, expected, delta=TOL * expected)
                    self.assertAlmostEqual(corridor.lower_bound_m, expected, delta=TOL * expected)
                    ratio = length / (MESH_M * math.hypot(dx, dy))
                    self.assertGreaterEqual(ratio, 1.0 - TOL)
                    self.assertLessEqual((ratio - 1.0) * 100.0, rd.DETOUR_BOUND_PCT)
                    self.assertLessEqual(route.turns, 1)
                    worst = max(worst, ratio - 1.0)
        self.assertGreater(worst * 100.0, 2.5)  # el abanico llega a los rumbos peores: la cota no es vacía


class HillsideTest(unittest.TestCase):
    """CE-017-04, la parte de la ruta: «en un plano del 38 % con la curva de nivel a 22,5° de un eje de la rejilla y pd = 10 %, la menor pendiente
    de paso que ofrecen los 16 rumbos es del 2,7 % (con 8 habría sido del 14,5 % y sin ruta) y la ruta existe y no pasa de pd»."""

    @classmethod
    def setUpClass(cls) -> None:
        grid = rd.GRID
        cls.terrain = rd.hillside_terrain(grid)
        cls.origin = tuple(float(v) for v in rd.absolute([rd.HILL_ORIGIN], grid)[0])
        cls.destination = tuple(float(v) for v in rd.absolute([rd.HILL_DESTINATION], grid)[0])
        first, last = (rd.cell_of(point) for point in (rd.HILL_ORIGIN, rd.HILL_DESTINATION))
        cls.expected_nodes = tuple((first[0] // 4 - step, first[1] // 4 + 2 * step) for step in range(rd.HILL_STEPS + 1))
        assert cls.expected_nodes[-1] == (last[0] // 4, last[1] // 4)

    def prepare(self, route: Any) -> tuple[Any, Any, Any]:
        job = rd.route_job(rd.GRID, self.terrain, self.origin, self.destination, route=route, profile=rd.profile_with(max_gradient_pct=10.0))
        mesh, corridor = rd.route_corridor(job)
        return job, mesh, corridor

    def test_the_smallest_step_gradient_is_2_7_percent_with_16_headings_and_14_5_with_8(self) -> None:
        """RF-017-11, CE-017-04, B2: la pendiente del terreno de la malla de 4 m a lo largo de cada rumbo es ``38·|sen(φ − 22,5°)|`` % (a mano, a
        ≤ 10⁻⁹ relativo): la menor de los **16** rumbos es la del paso (2, 1), de 0,38·sen(atan ½ − 22,5°) = 2,694 % (la spec la redondea a 2,7 %), y la
        menor de los **8** inmediatos, de 0,38·sen 22,5° = 14,542 % (14,5 %): con pd = 10 % ninguno de los 8 sería admisible."""
        mesh = road_net.route_mesh(rd.GRID, self.terrain, MESH_M)
        node = (50, 50)  # un nodo interior: todos los rumbos caen dentro de la malla
        slopes = []
        for heading, (dx, dy) in enumerate(road_net.HEADINGS):
            other = (node[0] - dy, node[1] + dx)
            length = MESH_M * math.hypot(dx, dy)
            slope = abs(float(mesh.z[other] - mesh.z[node])) / length * 100.0
            by_hand = rd.HILL_SLOPE_PCT * abs(math.sin(math.atan2(dy, dx) - math.radians(rd.HILL_CONTOUR_DEG)))
            self.assertAlmostEqual(slope, by_hand, delta=TOL * by_hand)
            slopes.append(slope)
        smallest_16 = 100.0 * 0.38 * math.sin(math.atan(0.5) - math.radians(22.5))
        smallest_8 = 100.0 * 0.38 * math.sin(math.radians(22.5))
        self.assertAlmostEqual(min(slopes), smallest_16, delta=TOL * smallest_16)
        self.assertAlmostEqual(min(slopes[::2]), smallest_8, delta=TOL * smallest_8)
        self.assertEqual((round(min(slopes), 1), round(min(slopes[::2]), 1)), (2.7, 14.5))
        self.assertGreater(min(slopes[::2]), 10.0)  # con 8 rumbos y pd = 10 %: ningún paso admisible
        self.assertLess(min(slopes), 10.0)
        self.assertEqual(slopes.index(min(slopes)), road_net.HEADINGS.index((2, 1)))

    def test_the_route_exists_with_height_zero_and_never_passes_the_design_gradient(self) -> None:
        """RF-017-10, RF-017-11, CE-017-04, HU-017-1: con altura 0 (``s23``, la pista que sigue el terreno) y pd = 10 % la ruta de la ladera del
        38 % **existe**: diez pasos del rumbo (2, 1) (a mano desde las celdas), 89,443 m (10·√80, ≤ 10⁻⁹ relativo), de cota la del terreno (movimiento 0
        m) con un desnivel de 0,38·(−80·sen 22,5° + 40·cos 22,5°) = 2,409 m, y **ningún paso pasa de pd**: todos son del 2,694 %."""
        job, mesh, corridor = self.prepare(rd.route_with(max_cut_fill_m=0.0))
        route = base.solve(job, corridor)
        self.assertTrue(route.ok)
        self.assertEqual(route.nodes, self.expected_nodes)
        self.assertEqual((route.turns, route.headings), (0, (3,) * (rd.HILL_STEPS + 1)))
        length = polyline_m(local(route.centers))
        self.assertAlmostEqual(length, rd.HILL_STEPS * math.sqrt(80.0), delta=TOL * length)
        self.assertAlmostEqual(corridor.lower_bound_m, length, delta=TOL * length)
        centers = local(route.centers)
        angle = math.radians(rd.HILL_CONTOUR_DEG)
        plane = rd.HILL_Z0_M + rd.HILL_SLOPE_PCT / 100.0 * (-(centers[:, 0] - 200.0) * math.sin(angle) + (centers[:, 1] - 200.0) * math.cos(angle))
        self.assertLessEqual(float(np.abs(route.levels_m - plane).max()), TOL)
        drop = 0.38 * (-80.0 * math.sin(angle) + 40.0 * math.cos(angle))
        self.assertAlmostEqual(float(route.levels_m[-1] - route.levels_m[0]), drop, delta=TOL)
        gradients = np.abs(np.diff(route.levels_m)) / math.sqrt(80.0) * 100.0
        self.assertLessEqual(float(gradients.max()), 10.0)
        self.assertAlmostEqual(float(gradients.max()), 0.38 * math.sin(math.atan(0.5) - angle) * 100.0, delta=1e-7)
        base.verify(self, job, mesh, route)

    def test_with_the_reference_height_the_route_is_the_same_and_does_not_pass_pd(self) -> None:
        """RF-017-10, CE-017-04: con los parámetros de la referencia (14 m de altura, paso de cota de 0,28 m, λ = 2 1/m, giro de 4 m) la ruta es la misma
        —el mínimo coste no mueve tierra donde el rumbo (2, 1) ya tiene el 2,7 %—: los diez pasos, 89,443 m, de la cota del terreno, y cada paso
        cumple pd (recalculado)."""
        job, mesh, corridor = self.prepare(rd.ROUTE)
        route = base.solve(job, corridor)
        self.assertTrue(route.ok)
        self.assertEqual(route.nodes, self.expected_nodes)
        self.assertLessEqual(float(np.abs(route.levels_m - mesh.z[tuple(np.array(route.nodes).T)]).max()), TOL)
        self.assertAlmostEqual(route.cost, rd.HILL_STEPS * MESH_M * math.sqrt(5.0), delta=1e-8)
        base.verify(self, job, mesh, route)

    def test_with_only_the_8_immediate_headings_there_would_be_no_route(self) -> None:
        """RF-017-11, CE-017-04, B2 (**demostración, no criterio**): con la red 2D a mano (``hand_net``, Bellman–Ford sobre el grafo explícito) de la
        ladera del 38 % con altura 0 y pd = 10 %, con los 8 rumbos inmediatos **ningún paso es admisible** (todos pasan del 14,5 %): el destino no
        alcanza ni al origen; con los 16, el origen está a 89,443 m (diez pasos del (2, 1)). El código no ofrece 8 rumbos: no hay forma de pedirlos."""
        grid = gis.Grid(west=rd.BASE[0], north=rd.BASE[1] + 60.0, dx=1.0, dy=1.0, ncols=100, nrows=60)
        terrain = rd.hillside_terrain(grid)
        origin, destination = (11, 2), (1, 22)  # diez pasos (2, 1) en una malla de 15 × 25 nodos de 4 m
        sixteen = oracles.hand_net(terrain, None, 4, 1.0, 0.10, 0.0, [destination])
        eight = oracles.hand_net(terrain, None, 4, 1.0, 0.10, 0.0, [destination], headings=oracles.HAND_HEADINGS[::2])
        self.assertTrue(math.isinf(float(eight[origin])))
        self.assertEqual(int(np.isfinite(eight).sum()), 1)  # solo el propio destino
        self.assertAlmostEqual(float(sixteen[origin]), rd.HILL_STEPS * math.sqrt(80.0), delta=TOL * 89.45)
        self.assertGreater(int(np.isfinite(sixteen).sum()), 10)
        self.assertEqual(len(road_net.HEADINGS), 16)


class StripTest(unittest.TestCase):
    """CE-017-04, sin ruta: «con un perímetro de actuación que solo deja pasar una franja recta de 100 m de largo y 4 m de ancho (un nodo de la malla
    de la ruta) para un desnivel de 30 m con pd = 10 % (hacen falta 300 m), no hay ruta y el mensaje da la cota mayor alcanzada (la del origen + 10 m),
    la pendiente mínima necesaria (30 %) y el tramo limitante, sin registrar nada; con un intocable que cierra el único paso, lo mismo con su zona»."""

    @staticmethod
    def snapshot(job: Any, mesh: Any, corridor: Any) -> tuple[bytes, ...]:
        return (np.asarray(job.start).tobytes(), np.asarray(job.untouchable).tobytes(), np.asarray(mesh.z).tobytes(),
                np.asarray(mesh.walkable).tobytes(), np.asarray(corridor.mask).tobytes(), np.asarray(corridor.net_dest.dist).tobytes(),
                np.asarray(corridor.net_origin.dist).tobytes())

    def test_the_strip_has_no_route_and_says_the_level_reached_the_gradient_and_the_stretch(self) -> None:
        """RF-017-12, RF-017-10, CE-017-04: la franja de 100 m con 30 m de desnivel y pd = 10 % (hacen falta 300 m): la red 2D la alcanza, la búsqueda
        agota su pasillo (no el presupuesto), y el diagnóstico da la cota mayor alcanzada desde el origen (**100 + 10 = 110 m**), la menor desde el
        destino (130 − 10 = 120 m), la pendiente mínima necesaria (**30 m sobre 100 m = 30 %**, a ≤ 10⁻⁹) y el tramo limitante (el destino, por la
        pendiente), **sin cambiar nada** de lo que lee."""
        job, mesh, corridor = strip_case()
        before = self.snapshot(job, mesh, corridor)
        self.assertTrue(corridor.reachable)
        self.assertAlmostEqual(corridor.lower_bound_m, 100.0, delta=TOL)
        self.assertAlmostEqual(rd.needed_length_m(30.0, 10.0), rd.STRIP_NEEDED_M, delta=TOL)
        route = base.solve(job, corridor)
        self.assertEqual((route.ok, route.cause), (False, road_model.NoRouteCause.CORRIDOR))
        found = road_route.no_route(job, corridor.net_origin, corridor.net_dest, route)
        self.assertAlmostEqual(found.reached_from_origin_m, rd.STRIP_Z_ORIGIN_M + rd.STRIP_REACH_M, delta=1e-6)
        self.assertAlmostEqual(found.reached_from_destination_m, rd.STRIP_Z_ORIGIN_M + 30.0 - rd.STRIP_REACH_M, delta=1e-6)
        self.assertAlmostEqual(found.min_gradient_pct, rd.STRIP_SLOPE_PCT, delta=TOL * 30.0)
        self.assertGreater(found.min_gradient_pct, job.profile.max_gradient_pct)
        self.assertEqual((found.length_m, found.length_basis), (100.0, "network"))
        self.assertEqual(found.limit.cause, road_model.LimitCause.SLOPE)
        self.assertEqual(found.limit.node, mesh.node_of(*job.geometry.destination))
        self.assertEqual(self.snapshot(job, mesh, corridor), before)  # nada cambia
        error = found.error(job)
        self.assertIsInstance(error, messages.DesignError)
        self.assertEqual(error.code, "des.road_no_route_corridor")
        for expected in ("110", "120", "30 %", "no se relaja ningún límite", "no se crea nada"):
            self.assertIn(expected, error.text)
        self.assertEqual(self.snapshot(job, mesh, corridor), before)

    def test_an_untouchable_that_closes_the_only_pass_gives_the_same_figures_with_its_zone(self) -> None:
        """RF-017-12, RF-017-06, CE-017-04: con el intocable que cierra el único paso (4 m, un nodo) la red 2D no une los extremos: sin ruta (causa de
        la red) y el diagnóstico da la cota mayor alcanzada (100 + 0,10·44 m hasta el intocable = 104,4 m), la menor desde el destino (130 − 0,10·48 =
        125,2 m), la pendiente mínima necesaria con la longitud en línea recta (30 m sobre 100 m: 30 %) y el tramo limitante: el último nodo antes del
        intocable, con **la zona que las máscaras prohíben** como causa, hacia el este; sin cambiar nada."""
        job, mesh, corridor = strip_case(closed=True)
        before = self.snapshot(job, mesh, corridor)
        self.assertFalse(corridor.reachable)
        route = base.solve(job, corridor)
        self.assertEqual((route.ok, route.cause, route.expanded), (False, road_model.NoRouteCause.NETWORK, 0))
        found = road_route.no_route(job, corridor.net_origin, corridor.net_dest, route)
        self.assertAlmostEqual(found.reached_from_origin_m, rd.STRIP_Z_ORIGIN_M + 0.10 * 44.0, delta=TOL)
        self.assertAlmostEqual(found.reached_from_destination_m, rd.STRIP_Z_ORIGIN_M + 30.0 - 0.10 * 48.0, delta=TOL)
        self.assertEqual(found.length_basis, "straight")
        self.assertAlmostEqual(found.length_m, 100.0, delta=TOL)
        self.assertAlmostEqual(found.min_gradient_pct, 30.0, delta=TOL * 30.0)
        self.assertEqual(found.limit.cause, road_model.LimitCause.MASK)
        self.assertEqual((found.limit.heading, found.limit.node), (EAST, mesh.node_of(*np.asarray(rd.absolute([(146.0, 198.0)])[0]))))
        self.assertEqual(found.error(job).code, "des.road_no_route_network")
        self.assertEqual(self.snapshot(job, mesh, corridor), before)

    def test_with_the_reference_height_and_level_step_the_climb_stops_at_105_76_m_and_not_at_110(self) -> None:
        """RF-017-12, CE-017-04 (anotado, no criterio): la cifra de 110 m de la spec («la del origen + 10 m») es la de la subida analítica de 10 m en
        los 100 m (pd·L) y solo sale con una altura máxima de desmonte y terraplén de ≥ 20 m y un paso de cota que divide lo que sube un paso
        (0,2 m: 0,4 m de pendiente por paso): con la altura y el paso de cota de la referencia de IMGA (14 m y 0,28 m) la altura máxima corta antes
        la subida y se llega a **105,76 m** (el tramo limitante es la altura máxima, no la pendiente); la pendiente mínima necesaria no cambia
        (30 %). Lo decide la verificación única (T37)."""
        job, mesh, corridor = strip_case(max_cut_fill_m=14.0, level_step_m=0.28)
        route = base.solve(job, corridor)
        found = road_route.no_route(job, corridor.net_origin, corridor.net_dest, route)
        self.assertAlmostEqual(found.reached_from_origin_m, 105.76, delta=1e-6)
        self.assertLess(found.reached_from_origin_m, rd.STRIP_Z_ORIGIN_M + rd.STRIP_REACH_M - 1.0)
        self.assertAlmostEqual(found.min_gradient_pct, 30.0, delta=TOL * 30.0)
        self.assertEqual(found.limit.cause, road_model.LimitCause.HEIGHT)


if __name__ == "__main__":
    unittest.main()
