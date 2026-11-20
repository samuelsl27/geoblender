# SPDX-License-Identifier: GPL-3.0-or-later
"""La malla, los 16 rumbos y la red 2D de la ruta (spec 017, T06; HU-017-1; RF-017-09, 11 y 06; RNF-017-01 y 06; plan 017 §5.4 A1,
§5.7 P-6 y P-13, §7.3 y §9; D-8, D-10 y D-23): ``route_mesh`` (la malla, un múltiplo entero del paso, el nodo con la media de su
bloque), los 16 rumbos y los pasos admisibles (``HEADINGS``, ``step_masks``), la red 2D por pasos (``network_steps``: Dijkstra con
``heapq``) y el pasillo (``corridor``).

Todo en mallas de ≤ 200 × 200 nodos y, el oráculo, de ≤ 24 × 20 (el Bellman–Ford de ``design_oracles.hand_net`` es de pasadas
completas sobre todas las aristas, en Python); las mallas de 40 × 40 a 60 × 60 con muros y huecos y la de 175.525 nodos (RNF-017-01) son
de ``milestone_road_net`` (las pruebas de más de 1 s van al paso «hito», RNF-017-09). Los casos de los plano a 4 m salen de
``tests.support.road_data`` (la ladera del 38 % con la curva de nivel a 22,5° de un eje de la rejilla, CE-017-04); el oráculo es
independiente de ``design.road_net`` (``design_oracles.hand_net``, con su propia copia de los 16 rumbos y con la malla de bloques hecha
a mano).
"""

from __future__ import annotations

import dataclasses
import inspect
import math
import unittest
from collections.abc import Iterator
from typing import Any

import numpy as np

from tests.support import design_oracles as oracles
from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.support.timing import drive_steps, least_of

road_net = import_geoblender("design.road_net")
gis = import_geoblender("gis")
project_model = import_geoblender("core.project.model")

CELL_M = 2.0
"""El paso de las rejillas de los casos pequeños (m)."""
STEP_BUDGET_S = 0.05
"""Lo que dura una llamada del paso como mucho (RNF-017-06)."""


def grid_of(rows: int, cols: int, step: float = CELL_M) -> Any:
    """Una rejilla de ``rows × cols`` celdas de ``step`` m, absoluta, en el norte de un UTM."""
    return gis.Grid(west=500_000.0, north=4_400_000.0, dx=step, dy=step, ncols=cols, nrows=rows)


def run(steps: Iterator[Any]) -> tuple[Any, int]:
    """Recorre unos pasos: lo que lleva el último y cuántos fueron."""
    found, count = None, 0
    for step in steps:
        count += 1
        assert isinstance(step, project_model.Progress)
        if step.result is not None:
            found = step.result
    return found, count


def net_of(mesh: Any, target: Any, pd: float, hmax: float) -> Any:
    return run(road_net.network_steps(mesh, target, pd, hmax))[0]


def flat_mesh(rows: int, cols: int, *, step: float = CELL_M, mask: np.ndarray | None = None, level: float = 100.0,
              holes: tuple[tuple[int, int], ...] = ()) -> Any:
    """Una malla de ``rows × cols`` nodos (un nodo por celda, ``k = 1``) de un plano a ``level`` m, con ``holes`` celdas sin dato."""
    surface = np.full((rows, cols), level)
    for row, column in holes:
        surface[row, column] = np.nan
    return road_net.route_mesh(grid_of(rows, cols, step), surface, step, mask)


def random_case(seed: int, ni: int, nj: int, factor: int) -> dict[str, Any]:
    """Un terreno al azar de ``ni × nj`` nodos de ``factor × factor`` celdas de 2 m (la cota de cada nodo al azar y un ruido pequeño por
    celda), con tres muros (cajas de celdas prohibidas) y un 2 % de celdas sin dato."""
    rng = np.random.default_rng(seed)
    rows, cols = ni * factor, nj * factor
    surface = np.kron(2.0 * rng.random((ni, nj)), np.ones((factor, factor))) + rng.uniform(-0.05, 0.05, (rows, cols))
    surface[rng.random((rows, cols)) < 0.02] = np.nan
    forbidden = np.zeros((rows, cols), dtype=bool)
    for _ in range(3):
        r, c = int(rng.integers(0, rows)), int(rng.integers(0, cols))
        forbidden[r:r + int(rng.integers(1, max(2, rows // 3))), c:c + int(rng.integers(1, 3))] = True
    return {"surface": surface, "forbidden": forbidden, "factor": factor, "ni": ni, "nj": nj}


class HeadingsTest(unittest.TestCase):
    def test_the_sixteen_headings_are_the_ones_of_the_spec_clockwise_from_the_north(self) -> None:
        """RF-017-11 (D-8, D-23): los rumbos son 16 —los 8 pasos inmediatos y los 8 «de caballo», (±1, ±2) y (±2, ±1)— y están
        numerados en sentido horario desde el norte (el 0 es el norte, el 4 el este, el 8 el sur y el 12 el oeste); coinciden con la
        copia independiente del oráculo y de ``road_data``."""
        headings = road_net.HEADINGS
        self.assertEqual(len(headings), 16)
        self.assertEqual(headings, rd.ORACLE_HEADINGS)
        self.assertEqual(headings, oracles.HAND_HEADINGS)
        self.assertEqual(road_net.HEADING_COUNT, 16)
        self.assertEqual([headings[index] for index in (0, 4, 8, 12)], [(0, 1), (1, 0), (0, -1), (-1, 0)])
        azimuths = [rd.heading_azimuth_deg(step) for step in headings]
        self.assertEqual(azimuths[0], 0.0)
        self.assertEqual(azimuths, sorted(azimuths))
        gaps = {round(b - a, 2) for a, b in zip(azimuths, azimuths[1:] + [360.0], strict=True)}
        self.assertEqual(gaps, {18.43, 26.57})
        immediate = {(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)} - {(0, 0)}
        knights = {(dx, dy) for dx in (-2, -1, 1, 2) for dy in (-2, -1, 1, 2) if {abs(dx), abs(dy)} == {1, 2}}
        self.assertEqual(set(headings), immediate | knights)
        self.assertEqual(road_net.STEP_UNITS, tuple(math.hypot(dx, dy) for dx, dy in headings))
        self.assertEqual(sorted({round(unit, 6) for unit in road_net.STEP_UNITS}), [1.0, round(math.sqrt(2), 6), round(math.sqrt(5), 6)])

    def test_there_is_no_way_to_ask_for_eight(self) -> None:
        """RF-017-11 (B2): 16 es el único número de rumbos que se ofrece: ninguna función del módulo tiene un parámetro para el número o
        la lista de rumbos, la lista de rumbos es una tupla (no se puede recortar) y las máscaras de paso son 16 y siempre 16."""
        for function in (road_net.route_mesh, road_net.mesh_factor, road_net.step_masks, road_net.network_steps, road_net.corridor):
            with self.subTest(function=function.__name__):
                names = set(inspect.signature(function).parameters)
                self.assertFalse({name for name in names if any(word in name for word in ("heading", "direction", "count", "number"))})
        self.assertIsInstance(road_net.HEADINGS, tuple)
        with self.assertRaises(TypeError):
            road_net.HEADINGS[0] = (0, 0)  # type: ignore[index]
        masks = road_net.step_masks(flat_mesh(6, 6), 0.1, 0.0)
        self.assertEqual(len(masks), 16)


class MeshTest(unittest.TestCase):
    def test_the_node_is_a_block_of_cells_with_the_mean_of_their_heights(self) -> None:
        """RF-017-09 (P-6, D-10): la malla de la ruta de un múltiplo entero del paso: el nodo es un bloque de ``k × k`` celdas (la fila 0,
        al norte) y su cota, la media de las del bloque; el lado del nodo es ``k`` veces el paso."""
        grid = grid_of(8, 12, 1.0)
        surface = np.arange(96, dtype=float).reshape(8, 12) ** 1.5
        mesh = road_net.route_mesh(grid, surface, 4.0)
        self.assertEqual((mesh.k, mesh.mesh_m, mesh.shape, mesh.size), (4, 4.0, (2, 3), 6))
        for i in range(2):
            for j in range(3):
                block = [surface[r, c] for r in range(4 * i, 4 * i + 4) for c in range(4 * j, 4 * j + 4)]
                self.assertAlmostEqual(float(mesh.z[i, j]), math.fsum(block) / 16.0, delta=1e-9)
        self.assertTrue(mesh.walkable.all())
        self.assertFalse(mesh.forbidden.any())
        self.assertIsNone(mesh.weight)
        self.assertEqual(road_net.route_mesh(grid, surface, 1.0).shape, (8, 12))  # k = 1: un nodo por celda
        self.assertTrue(np.array_equal(road_net.route_mesh(grid, surface, 1.0).z, surface))

    def test_a_node_with_a_cell_without_data_or_prohibited_is_not_stepped_on(self) -> None:
        """RF-017-09, RF-017-06: un nodo con alguna celda sin dato, o que las máscaras prohíben pisar (alguna celda de su bloque en la
        máscara), no se pisa; el de las celdas sin dato no tiene cota y el prohibido sí (la media de sus celdas); los demás se pisan."""
        grid = grid_of(8, 8, 1.0)
        surface = np.full((8, 8), 50.0)
        surface[1, 1] = np.nan  # el bloque (0, 0)
        mask = np.zeros((8, 8), dtype=bool)
        mask[7, 7] = True  # el bloque (1, 1): una sola celda
        mesh = road_net.route_mesh(grid, surface, 4.0, mask)
        self.assertEqual(mesh.walkable.tolist(), [[False, True], [True, False]])
        self.assertEqual(mesh.forbidden.tolist(), [[False, False], [False, True]])
        self.assertTrue(math.isnan(mesh.z[0, 0]))
        self.assertEqual(float(mesh.z[1, 1]), 50.0)
        surface[1, 1] = np.inf  # un infinito tampoco es un dato
        self.assertFalse(road_net.route_mesh(grid, surface, 4.0).walkable[0, 0])

    def test_the_blocks_that_leave_the_grid_are_not_stepped_on(self) -> None:
        """RF-017-09: con una rejilla que no es múltiplo del bloque (10 × 10 celdas y bloques de 4), los bloques incompletos del sur y del
        este son nodos que no se pisan y sin cota (el borde de la rejilla); los demás, sí."""
        mesh = road_net.route_mesh(grid_of(10, 10, 1.0), np.full((10, 10), 5.0), 4.0)
        self.assertEqual(mesh.shape, (3, 3))
        self.assertEqual(mesh.walkable.tolist(), [[True, True, False], [True, True, False], [False, False, False]])
        self.assertEqual(int(np.isnan(mesh.z).sum()), 5)

    def test_the_mesh_is_an_integer_multiple_of_the_project_step(self) -> None:
        """RF-017-09 (D-10): la malla de la ruta es un múltiplo entero del paso del proyecto; si no lo es, rechazo (``ValueError``), y
        también con celdas no cuadradas o una entrada de otra forma; los tipos que no son, ``TypeError``."""
        grid = grid_of(8, 8, 2.0)
        surface = np.zeros((8, 8))
        self.assertEqual([road_net.mesh_factor(grid, mesh) for mesh in (2.0, 4.0, 6.0, 16.0)], [1, 2, 3, 8])
        self.assertEqual(road_net.mesh_factor(gis.Grid(west=0.0, north=0.0, dx=0.1, dy=0.1, ncols=9, nrows=9), 0.3), 3)
        for wrong in (3.0, 5.0, 4.5, 1.0, 0.0, -4.0, math.nan, math.inf):
            with self.subTest(mesh=wrong), self.assertRaises(ValueError):
                road_net.route_mesh(grid, surface, wrong)
        for wrong in (True, "4", None):
            with self.subTest(mesh=wrong), self.assertRaises(TypeError):
                road_net.route_mesh(grid, surface, wrong)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            road_net.route_mesh(gis.Grid(west=0.0, north=0.0, dx=2.0, dy=1.0, ncols=8, nrows=8), surface, 2.0)
        with self.assertRaises(ValueError):
            road_net.route_mesh(grid, np.zeros((8, 7)), 4.0)
        with self.assertRaises(ValueError):
            road_net.route_mesh(grid, surface, 4.0, np.zeros((7, 8), dtype=bool))

    def test_the_inputs_are_not_modified_and_the_result_is_read_only(self) -> None:
        """RF-017-09: la malla no modifica la superficie ni las máscaras (se lee) y sus arrays son de solo lectura; dos llamadas con lo
        mismo dan lo mismo."""
        grid = grid_of(8, 8, 1.0)
        surface = np.linspace(0.0, 30.0, 64).reshape(8, 8)
        surface[2, 2] = np.nan
        mask = np.zeros((8, 8), dtype=bool)
        mask[5, 5] = True
        weight = np.ones((8, 8))
        weight[0, 0] = 3.0
        before = (surface.copy(), mask.copy(), weight.copy())
        mesh = road_net.route_mesh(grid, surface, 4.0, mask, avoid_weight=weight)
        for array, kept in zip((surface, mask, weight), before, strict=True):
            self.assertTrue(np.array_equal(array, kept, equal_nan=True))
        for array in (mesh.z, mesh.forbidden, mesh.walkable, mesh.weight):
            self.assertFalse(array.flags.writeable)
        again = road_net.route_mesh(grid, surface, 4.0, mask, avoid_weight=weight)
        self.assertTrue(np.array_equal(mesh.z, again.z, equal_nan=True))

    def test_the_weight_of_a_node_is_the_greatest_of_the_cells_of_its_block(self) -> None:
        """RF-017-06 (plan §5.8 H-6): con las zonas «preferible no afectar», un nodo «ve» la zona si alguna celda de su bloque está en
        ella y lleva el mayor peso de sus celdas; sin zona pesa 1; un peso por debajo de 1 es un error del programa."""
        grid = grid_of(8, 8, 1.0)
        weight = np.ones((8, 8))
        weight[0, 0], weight[1, 1], weight[6, 5] = 2.5, 4.0, 1.5
        mesh = road_net.route_mesh(grid, np.zeros((8, 8)), 4.0, avoid_weight=weight)
        self.assertEqual(mesh.weight.tolist(), [[4.0, 1.0], [1.0, 1.5]])
        for wrong in (0.5, np.nan):
            bad = weight.copy()
            bad[3, 3] = wrong
            with self.subTest(weight=wrong), self.assertRaises(ValueError):
                road_net.route_mesh(grid, np.zeros((8, 8)), 4.0, avoid_weight=bad)

    def test_a_point_belongs_to_its_node_and_the_center_is_the_one_of_its_block(self) -> None:
        """RF-017-09: ``node_of`` da el nodo del bloque que contiene el punto absoluto (uno en el borde de dos celdas va a la del este
        y a la del sur) y ``center_of`` el centro del bloque, en absolutas float64; fuera de la rejilla, ``ValueError``."""
        grid = grid_of(8, 12, 1.0)
        mesh = road_net.route_mesh(grid, np.zeros((8, 12)), 4.0)
        west, north = grid.west, grid.north
        self.assertEqual(mesh.node_of(west + 0.1, north - 0.1), (0, 0))
        self.assertEqual(mesh.node_of(west + 4.0, north - 4.0), (1, 1))
        self.assertEqual(mesh.node_of(west + 3.999, north - 3.999), (0, 0))
        self.assertEqual(mesh.node_of(west + 11.9, north - 7.9), (1, 2))
        self.assertEqual(mesh.center_of(0, 0), (west + 2.0, north - 2.0))
        self.assertEqual(mesh.center_of(1, 2), (west + 10.0, north - 6.0))
        for i in range(2):
            for j in range(3):
                self.assertEqual(mesh.node_of(*mesh.center_of(i, j)), (i, j))
        for x, y in ((west - 0.1, north - 1.0), (west + 12.0, north - 1.0), (west + 1.0, north + 0.1), (west + 1.0, north - 8.0)):
            with self.subTest(point=(x, y)), self.assertRaises(ValueError):
                mesh.node_of(x, y)
        for node in ((2, 0), (0, 3), (-1, 0)):
            with self.subTest(node=node), self.assertRaises(ValueError):
                mesh.center_of(*node)


class StepMasksTest(unittest.TestCase):
    def test_a_step_is_admissible_by_its_difference_of_height(self) -> None:
        """RF-017-09: un paso es admisible si ``|Δcota| ≤ pd·L(h) + 2H`` (con ``pd`` en tanto por uno y ``H`` la altura máxima de desmonte y
        terraplén): en un plano del 10 % hacia el este con la malla de 2 m, el paso al este (``Δ = 0,2 m``) lo es con ``pd = 0,10`` (y con
        ``pd = 0`` y ``H = 0,1``), no con una pizca menos; y con ``H = 0`` y pd = 0, solo los pasos que no cambian de cota."""
        grid = grid_of(5, 5)
        surface = np.tile(0.2 * np.arange(5), (5, 1))
        mesh = road_net.route_mesh(grid, surface, CELL_M)
        east = road_net.HEADINGS.index((1, 0))
        north = road_net.HEADINGS.index((0, 1))
        for pd, hmax, expected in ((0.10, 0.0, True), (0.0999, 0.0, False), (0.0, 0.1, True), (0.0, 0.0999, False), (0.5, 0.0, True)):
            with self.subTest(pd=pd, hmax=hmax):
                masks = road_net.step_masks(mesh, pd, hmax)
                self.assertEqual(bool(masks[east][2, 1]), expected)  # (1, 0) es el este: de la columna 1 a la 2
                self.assertEqual(bool(masks[east][2, 4]), False)  # el extremo sale de la malla
        flat = road_net.step_masks(mesh, 0.0, 0.0)
        self.assertTrue(flat[north][2, 2])  # el plano no cambia hacia el norte
        self.assertFalse(flat[east][2, 2])
        self.assertFalse(flat[road_net.HEADINGS.index((2, 1))][2, 2])

    def test_a_prohibited_or_empty_node_closes_the_step_that_ends_or_crosses_it(self) -> None:
        """RF-017-09, RF-017-06: ni un extremo ni un nodo intermedio prohibido o sin dato; en los pasos «de caballo» los intermedios son los
        dos que la recta atraviesa: el paso (2, 1) de (fila 1, columna 0) a (fila 0, columna 2) cruza el (1, 1) y el (0, 1) de la malla."""
        knight = road_net.HEADINGS.index((2, 1))
        free = road_net.step_masks(flat_mesh(3, 3), 0.1, 0.0)
        self.assertTrue(free[knight][1, 0])
        for name, node in (("el extremo", (0, 2)), ("un intermedio", (1, 1)), ("el otro intermedio", (0, 1)), ("la salida", (1, 0))):
            with self.subTest(prohibited=name):
                mask = np.zeros((3, 3), dtype=bool)
                mask[node] = True
                self.assertFalse(road_net.step_masks(flat_mesh(3, 3, mask=mask), 0.1, 0.0)[knight][1, 0])
                self.assertFalse(road_net.step_masks(flat_mesh(3, 3, holes=(node,)), 0.1, 0.0)[knight][1, 0])
        mask = np.zeros((3, 3), dtype=bool)
        mask[2, 2] = True  # un nodo que nada tiene que ver con el paso
        self.assertTrue(road_net.step_masks(flat_mesh(3, 3, mask=mask), 0.1, 0.0)[knight][1, 0])
        mask = np.zeros((3, 3), dtype=bool)
        mask[0, 1] = True  # un paso inmediato no atraviesa ningún intermedio: el este (1, 1) → (1, 1) no lo cruza; el (1, 1), que acaba en él, sí
        masks = road_net.step_masks(flat_mesh(3, 3, mask=mask), 0.1, 0.0)
        self.assertTrue(masks[road_net.HEADINGS.index((1, 0))][1, 0])
        self.assertFalse(masks[road_net.HEADINGS.index((1, 1))][1, 0])

    def test_the_masks_are_symmetric_and_read_only(self) -> None:
        """RF-017-09: si el paso de ``a`` a ``b`` es admisible, el de ``b`` a ``a`` (el rumbo opuesto, ocho más) también: el grafo es no
        dirigido y la red desde el destino vale desde el origen; son 16, de la forma de la malla y de solo lectura."""
        case = random_case(11, 9, 8, 2)
        mesh = road_net.route_mesh(grid_of(18, 16), case["surface"], 2.0 * 2, case["forbidden"])
        masks = road_net.step_masks(mesh, 0.1, 0.4)
        self.assertEqual(len(masks), 16)
        rows, cols = mesh.shape
        count = 0
        for h, (dx, dy) in enumerate(road_net.HEADINGS):
            self.assertEqual(masks[h].shape, mesh.shape)
            self.assertFalse(masks[h].flags.writeable)
            for i in range(rows):
                for j in range(cols):
                    if masks[h][i, j]:
                        count += 1
                        self.assertTrue(masks[(h + 8) % 16][i - dy, j + dx], (h, i, j))
        self.assertGreater(count, 100)

    def test_the_least_gradient_of_a_step_on_a_38_percent_hillside(self) -> None:
        """RF-017-11 (CE-017-04): en un plano del 38 % con la curva de nivel a 22,5° de un eje de la rejilla la menor pendiente de paso es
        del 2,7 % (0,38·sen 4,065°, el paso (2, 1)) y no del 14,5 % (0,38·sen 22,5°) de los 8 rumbos inmediatos, a ≤ 10⁻⁹ relativo del
        cálculo a mano; y los pasos admisibles con ``pd`` una pizca por encima de ella son solo ese y su opuesto, y con una pizca por
        debajo, ninguno."""
        mesh = road_net.route_mesh(rd.GRID, rd.hillside_terrain(rd.GRID), 4.0)
        i, j = 50, 50
        slopes = [abs(mesh.z[i - dy, j + dx] - mesh.z[i, j]) / (4.0 * math.hypot(dx, dy)) for dx, dy in road_net.HEADINGS]
        by_hand = 0.38 * math.sin(math.atan2(1, 2) - math.radians(22.5))
        self.assertAlmostEqual(min(slopes) / by_hand, 1.0, delta=1e-9)
        self.assertAlmostEqual(by_hand * 100.0, 2.694, places=3)
        self.assertEqual({road_net.HEADINGS[h] for h, value in enumerate(slopes) if value == min(slopes)} | {(2, 1)}, {(2, 1), (-2, -1)})
        self.assertAlmostEqual(min(slopes[::2]) / (0.38 * math.sin(math.radians(22.5))), 1.0, delta=1e-9)
        self.assertAlmostEqual(0.38 * math.sin(math.radians(22.5)) * 100.0, 14.54, places=2)
        for h, (dx, dy) in enumerate(road_net.HEADINGS):
            self.assertAlmostEqual(slopes[h] * 100.0, rd.hillside_heading_slope_pct(dx, dy), delta=1e-9)
        for factor, expected in ((1.0 + 1e-6, {(2, 1), (-2, -1)}), (1.0 - 1e-6, set()), (1.0 + 1e-6 + 0.0, {(2, 1), (-2, -1)})):
            masks = road_net.step_masks(mesh, by_hand * factor, 0.0)
            found = {road_net.HEADINGS[h] for h in range(16) if masks[h][i, j]}
            with self.subTest(factor=factor):
                self.assertEqual(found, expected)
        found = {road_net.HEADINGS[h] for h, mask in enumerate(road_net.step_masks(mesh, 0.10, 0.0)) if mask[i, j]}
        self.assertEqual(found, {(2, 1), (-2, -1)})  # con el 10 % de B2: solo ese paso y su opuesto

    def test_the_inputs_are_checked(self) -> None:
        """RF-017-09: la pendiente y la altura son números finitos no negativos y la malla, una ``RouteMesh``: errores del programa."""
        mesh = flat_mesh(4, 4)
        for pd, hmax in ((-0.1, 0.0), (0.1, -1.0), (math.nan, 0.0), (0.1, math.inf)):
            with self.subTest(pd=pd, hmax=hmax), self.assertRaises(ValueError):
                road_net.step_masks(mesh, pd, hmax)
        for pd, hmax in (("0.1", 0.0), (0.1, None), (True, 0.0)):
            with self.subTest(pd=pd, hmax=hmax), self.assertRaises(TypeError):
                road_net.step_masks(mesh, pd, hmax)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            road_net.step_masks(object(), 0.1, 0.0)  # type: ignore[arg-type]


class NetworkTest(unittest.TestCase):
    CASES = ((1, 8, 8, 1, 0.10, 0.5), (2, 12, 10, 2, 0.08, 0.3), (3, 16, 16, 3, 0.12, 1.0), (4, 24, 20, 1, 0.10, 0.4),
             (5, 10, 14, 2, 0.20, 0.0), (6, 20, 12, 2, 0.05, 2.0))

    def test_the_network_is_the_one_of_an_independent_bellman_ford_on_the_explicit_graph(self) -> None:
        """RF-017-09, RF-017-11, RF-017-06: la red 2D es igual a la de una implementación independiente (Bellman–Ford sobre el grafo
        explícito, ``design_oracles.hand_net``, con la malla de bloques hecha a mano) en mallas de 8 × 8 a 24 × 20 nodos con muros, celdas
        sin dato y huecos, con bloques de 1 a 3 celdas, pendientes del 5 al 20 % y alturas de 0 a 2 m; la alcanzabilidad y las distancias
        (a ≤ 10⁻¹² relativo: las dos suman las mismas longitudes en otro orden)."""
        for seed, ni, nj, factor, pd, hmax in self.CASES:
            case = random_case(seed, ni, nj, factor)
            grid = grid_of(ni * factor, nj * factor)
            mesh = road_net.route_mesh(grid, case["surface"], CELL_M * factor, case["forbidden"])
            with self.subTest(seed=seed, nodes=(ni, nj), factor=factor):
                every = [(i, j) for i in range(ni) for j in range(nj)]
                walkable = oracles.hand_net(case["surface"], case["forbidden"], factor, CELL_M, pd, hmax, every) == 0.0
                centered = sorted((node for node in every if walkable[node]), key=lambda n: abs(n[0] - ni / 2) + abs(n[1] - nj / 2))
                for target in centered:  # el más cercano al centro desde el que la red llega a algo
                    expected = oracles.hand_net(case["surface"], case["forbidden"], factor, CELL_M, pd, hmax, [target])
                    if int(np.isfinite(expected).sum()) > 10:
                        break
                found = net_of(mesh, target, pd, hmax)
                self.assertEqual(found.dist.shape, (ni, nj))
                self.assertTrue(np.array_equal(np.isfinite(found.dist), np.isfinite(expected)))
                np.testing.assert_allclose(found.dist, expected, rtol=1e-12, atol=0.0)
                self.assertGreater(found.reached, 10)  # no es un caso vacío
                self.assertLess(found.reached, ni * nj)  # ni uno sin nada que cerrar
                self.assertEqual(found.reached, int(np.isfinite(expected).sum()))
                self.assertTrue((found.dist[~mesh.walkable] == np.inf).all())  # nada prohibido ni sin dato se pisa

    def test_a_set_of_nodes_is_a_destination_as_the_nearest_of_them(self) -> None:
        """RF-017-09 (el destino por cota, T08): el destino puede ser un conjunto de nodos (una máscara booleana de la forma de la
        malla): la longitud mínima al más próximo, igual a la del oráculo con varios destinos; uno que no se pisa se descarta."""
        case = random_case(21, 14, 14, 2)
        grid = grid_of(28, 28)
        mesh = road_net.route_mesh(grid, case["surface"], 4.0, case["forbidden"])
        zone = np.zeros(mesh.shape, dtype=bool)
        zone[2:5, 11] = True
        zone[10, 1:3] = True
        targets = [tuple(int(v) for v in node) for node in np.argwhere(zone)]
        found = net_of(mesh, zone, 0.1, 0.6)
        expected = oracles.hand_net(case["surface"], case["forbidden"], 2, CELL_M, 0.1, 0.6, targets)
        np.testing.assert_allclose(found.dist, expected, rtol=1e-12, atol=0.0)
        own = {int(flat) for flat in found.sources}
        self.assertEqual(own, {i * 14 + j for i, j in targets if mesh.walkable[i, j]})
        self.assertTrue((found.dist.ravel()[sorted(own)] == 0.0).all())
        self.assertEqual(net_of(mesh, [2, 11], 0.1, 0.6).sources.tolist(), net_of(mesh, (2, 11), 0.1, 0.6).sources.tolist())

    def test_in_a_free_plane_the_network_is_at_most_2_8_percent_longer_than_the_straight_line(self) -> None:
        """RF-017-11 (D-22; 1/cos 13,28° − 1 = 2,75 %): en un plano sin restricciones la distancia de la red 2D no pasa de la recta en más
        de un 2,8 % en ningún nodo (y la roza: pasa del 2,6 % lejos del origen); con solo los 8 rumbos inmediatos pasaría del 8 %: la
        comprobación distingue."""
        mesh = road_net.route_mesh(rd.GRID, np.full(rd.GRID.shape, 100.0), 4.0)
        found = net_of(mesh, (50, 50), 0.10, 0.0)
        self.assertEqual(found.reached, mesh.size)
        di, dj = np.indices(mesh.shape)
        straight = 4.0 * np.hypot(di - 50, dj - 50)
        ratios = found.dist[straight > 0] / straight[straight > 0]
        self.assertLessEqual(float(ratios.max()), 1.0 + rd.DETOUR_BOUND_PCT / 100.0)
        self.assertGreaterEqual(float(ratios.min()), 1.0 - 1e-12)
        self.assertGreater(float(ratios.max()), 1.026)
        flat = np.full((30, 30), 100.0)
        eight = oracles.hand_net(flat, None, 1, 4.0, 0.1, 0.0, [(15, 15)], headings=oracles.HAND_HEADINGS[::2])
        around = 4.0 * np.hypot(*(np.indices((30, 30)) - 15))
        wide = eight[around > 0] / around[around > 0]
        self.assertGreater(float(wide.max()), 1.08)  # 1/cos 22,5° − 1 = 8,24 %

    def test_a_38_percent_hillside_has_a_route_at_ten_percent_only_along_one_step(self) -> None:
        """RF-017-11 (CE-017-04): en la ladera del 38 % con la curva de nivel a 22,5° y pd = 10 % **la red 2D llega** del destino al origen
        (los de la ruta de diez pasos (2, 1) de 89,443 m de ``road_data``) y solo a los nodos de la recta de ese paso: con 8 rumbos no
        habría ruta (14,5 % > 10 %), con 16 sí. Con pd = 2,6 % (una pizca bajo el 2,69 %) no llega a ninguno."""
        mesh = road_net.route_mesh(rd.GRID, rd.hillside_terrain(rd.GRID), 4.0)
        origin = mesh.node_of(*rd.absolute([rd.HILL_ORIGIN])[0])
        destination = mesh.node_of(*rd.absolute([rd.HILL_DESTINATION])[0])
        self.assertEqual((origin, destination), ((75, 25), (65, 45)))
        found = net_of(mesh, destination, 0.10, 0.0)
        self.assertTrue(found.reaches(*origin))
        self.assertAlmostEqual(found.distance_to(*origin) / (rd.HILL_STEPS * 4.0 * math.sqrt(5.0)), 1.0, delta=1e-9)
        self.assertAlmostEqual(found.distance_to(*origin), 89.4427191, places=6)
        on_the_line = sum(1 for t in range(-100, 100) if 0 <= 65 - t < 100 and 0 <= 45 + 2 * t < 100)
        self.assertEqual(found.reached, on_the_line)
        self.assertTrue(all(found.reaches(65 - t, 45 + 2 * t) for t in range(-22, 28)))
        self.assertEqual(net_of(mesh, destination, 0.026, 0.0).reached, 1)  # solo el destino
        crop = rd.hillside_terrain(rd.GRID)[240:320, 80:200]  # nodos 60 a 80 y 20 a 50: el mismo plano, en pequeño
        near_destination, near_origin = (destination[0] - 60, destination[1] - 20), (origin[0] - 60, origin[1] - 20)
        sixteen = oracles.hand_net(crop, None, 4, 1.0, 0.10, 0.0, [near_destination])
        self.assertAlmostEqual(float(sixteen[near_origin]), 89.4427191, places=6)
        eight = oracles.hand_net(crop, None, 4, 1.0, 0.10, 0.0, [near_destination], headings=oracles.HAND_HEADINGS[::2])
        self.assertEqual(int(np.isfinite(eight).sum()), 1)  # con 8 rumbos no hay ruta

    def test_a_prohibited_or_empty_node_is_not_stepped_on_and_an_isolated_origin_is_not_reachable(self) -> None:
        """RF-017-09, RF-017-06: un nodo prohibido o sin dato no se pisa (ni la red pasa por él: da ``inf``) y las demás distancias lo
        rodean; un origen cercado por nodos prohibidos (los 8 vecinos: también cierran los pasos «de caballo» que lo cruzarían) no es
        alcanzable; un destino que no se pisa da una red vacía."""
        free = net_of(flat_mesh(9, 9), (4, 8), 0.1, 0.0)
        self.assertEqual(free.reached, 81)
        self.assertEqual(free.distance_to(4, 0), 8 * CELL_M)
        hole = net_of(flat_mesh(9, 9, holes=((4, 4),)), (4, 8), 0.1, 0.0)
        self.assertEqual(hole.reached, 80)
        self.assertEqual(hole.distance_to(4, 4), math.inf)
        self.assertGreater(hole.distance_to(4, 0), 8 * CELL_M)  # rodea el hueco
        ring = np.zeros((9, 9), dtype=bool)
        ring[3:6, 3:6] = True
        ring[4, 4] = False
        walled = flat_mesh(9, 9, mask=ring)
        isolated = net_of(walled, (4, 8), 0.1, 0.0)
        self.assertFalse(isolated.reaches(4, 4))
        self.assertEqual(isolated.reached, 81 - 9)
        around = net_of(walled, (4, 4), 0.1, 0.0)  # desde dentro del cerco no sale a ningún sitio
        self.assertEqual(around.reached, 1)
        self.assertEqual(net_of(walled, (3, 3), 0.1, 0.0).reached, 0)  # un destino prohibido: no se pisa
        self.assertEqual(net_of(walled, (3, 3), 0.1, 0.0).sources.size, 0)

    def test_a_wall_with_a_gap_makes_the_route_go_around(self) -> None:
        """RF-017-06, RF-017-09: con un muro (nodos prohibidos) con un hueco, la distancia de la red 2D es la del rodeo por el hueco, a
        mano: la recta atravesaría el muro."""
        wall = np.zeros((11, 11), dtype=bool)
        wall[:, 5] = True
        wall[0, 5] = False  # el hueco, al norte
        found = net_of(flat_mesh(11, 11, mask=wall), (10, 0), 0.1, 0.0)
        direct = CELL_M * math.hypot(10, 10)
        self.assertGreater(found.distance_to(10, 10), direct)  # el rodeo es más largo que la recta
        reverse = net_of(flat_mesh(11, 11, mask=wall), (0, 4), 0.1, 0.0)  # desde el pie del hueco
        self.assertAlmostEqual(found.distance_to(0, 4), reverse.distance_to(10, 0), delta=1e-9)  # la red es no dirigida
        expected = oracles.hand_net(np.full((11, 11), 100.0), wall, 1, CELL_M, 0.1, 0.0, [(10, 0)])
        np.testing.assert_allclose(found.dist, expected, rtol=1e-12, atol=0.0)

    def test_the_same_inputs_give_the_same_network_bit_for_bit(self) -> None:
        """RF-017-09 (RF-015-02, D-23): con las mismas entradas, la misma red (los desempates de la cola son por su índice) y los
        nodos de partida salen ordenados, vengan como vengan."""
        case = random_case(31, 14, 12, 2)
        mesh = road_net.route_mesh(grid_of(28, 24), case["surface"], 4.0, case["forbidden"])
        zone = np.zeros(mesh.shape, dtype=bool)
        zone[1:3, 3:5] = True
        first, second = (net_of(mesh, zone, 0.1, 0.5) for _ in range(2))
        self.assertTrue(np.array_equal(first.dist, second.dist))
        self.assertEqual(first.sources.tolist(), sorted(first.sources.tolist()))
        for array in (first.dist, first.sources):
            self.assertFalse(array.flags.writeable)

    def test_the_destination_and_the_inputs_are_checked_when_called(self) -> None:
        """RF-017-09: el destino es un nodo ``(i, j)`` de la malla o una máscara booleana de su forma; lo demás, un error del programa que
        se dice **al llamar**, no al avanzar el primer paso (``ValueError`` o ``TypeError``)."""
        mesh = flat_mesh(5, 6)
        for target in ((5, 0), (0, 6), (-1, 0), np.zeros((5, 5), dtype=bool), np.zeros((5, 6), dtype=int)):
            with self.subTest(target=target), self.assertRaises(ValueError):
                road_net.network_steps(mesh, target, 0.1, 0.0)  # type: ignore[arg-type]
        for target in ((1.5, 2), None, "ab", (1, 2, 3), (True, 2)):
            with self.subTest(target=target), self.assertRaises(TypeError):
                road_net.network_steps(mesh, target, 0.1, 0.0)  # type: ignore[arg-type]
        for kwargs in ({"budget_s": 0.0}, {"budget_s": -1.0}, {"budget_s": math.nan}):
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                road_net.network_steps(mesh, (0, 0), 0.1, 0.0, **kwargs)
        with self.assertRaises(ValueError):
            road_net.network_steps(mesh, (0, 0), -0.1, 0.0)
        with self.assertRaises(TypeError):
            road_net.network_steps(object(), (0, 0), 0.1, 0.0)  # type: ignore[arg-type]
        self.assertEqual(net_of(mesh, (np.int64(2), np.int64(3)), 0.1, 0.0).sources.tolist(), [2 * 6 + 3])  # índices de numpy


class CorridorTest(unittest.TestCase):
    def test_with_a_margin_of_zero_the_corridor_is_the_shortest_route(self) -> None:
        """RF-017-09: con la holgura 0 el pasillo es la ruta más corta (aquí la recta de la fila: 16 nodos de 4 m = 64,0 m, la cota
        inferior) y es el conjunto de los nodos con ``d_origen + d_destino ≤ la más corta``; con más holgura crece y siempre contiene el
        de menos."""
        mesh = flat_mesh(9, 21, step=4.0)
        origin, destination = (4, 2), (4, 18)
        net_o, net_d = net_of(mesh, origin, 0.1, 0.0), net_of(mesh, destination, 0.1, 0.0)
        tight = road_net.corridor(net_o, net_d, 0.0)
        self.assertTrue(tight.reachable)
        self.assertEqual(tight.lower_bound_m, 64.0)
        self.assertEqual(tight.margin_m, 0.0)
        self.assertEqual(tight.nodes, 17)
        self.assertEqual({tuple(node) for node in np.argwhere(tight.mask).tolist()}, {(4, j) for j in range(2, 19)})
        self.assertIs(tight.mesh, mesh)
        previous = tight.mask
        for margin in (4.0, 8.0, 16.0, 60.0):
            wide = road_net.corridor(net_o, net_d, margin)
            with self.subTest(margin=margin):
                self.assertEqual(wide.lower_bound_m, 64.0)
                self.assertTrue(bool((wide.mask | ~previous).all()))
                self.assertGreater(wide.nodes, int(previous.sum()))
                previous = wide.mask
        self.assertFalse(tight.mask.flags.writeable)

    def test_the_corridor_is_the_ellipse_of_the_margin_and_not_a_strip_of_that_width(self) -> None:
        """RF-017-09 (H-1): el pasillo es ``{n : d_o(n) + d_d(n) ≤ la más corta + holgura}`` con las distancias del oráculo independiente;
        y la holgura no es el ancho: con 60 m de holgura sobre una ruta de 120 m el pasillo mide a medio camino más de 100 m de lado a
        lado (el semieje menor de la elipse, √(90² − 60²) = 67 m a cada lado), no 60."""
        case = random_case(41, 18, 18, 1)
        grid = grid_of(18, 18)
        mesh = road_net.route_mesh(grid, case["surface"], CELL_M, case["forbidden"])
        for margin in (0.0, 2.0, 9.0):
            origin, destination = (15, 2), (2, 15)
            expected_o = oracles.hand_net(case["surface"], case["forbidden"], 1, CELL_M, 0.1, 0.6, [origin])
            expected_d = oracles.hand_net(case["surface"], case["forbidden"], 1, CELL_M, 0.1, 0.6, [destination])
            found = road_net.corridor(net_of(mesh, origin, 0.1, 0.6), net_of(mesh, destination, 0.1, 0.6), margin)
            with self.subTest(margin=margin):
                shortest = float(expected_d[origin])
                self.assertEqual(found.reachable, math.isfinite(shortest))
                if found.reachable:
                    self.assertAlmostEqual(found.lower_bound_m, shortest, delta=1e-9)
                    by_hand = (expected_o + expected_d) <= shortest + margin + 1e-9 * shortest
                    self.assertTrue(np.array_equal(found.mask, by_hand))
        flat = flat_mesh(61, 41, step=4.0)
        wide = road_net.corridor(net_of(flat, (50, 20), 0.1, 0.0), net_of(flat, (20, 20), 0.1, 0.0), 60.0)
        self.assertEqual(wide.lower_bound_m, 120.0)
        middle = np.flatnonzero(wide.mask[35])
        self.assertGreater((middle.max() - middle.min() + 1) * 4.0, 100.0)
        self.assertLess((middle.max() - middle.min() + 1) * 4.0, 160.0)
        self.assertEqual(int(wide.mask[35, 20]), 1)

    def test_an_unreachable_origin_has_no_corridor(self) -> None:
        """RF-017-09, RF-017-12: si la red no alcanza el origen (cercado por nodos prohibidos) no hay cota inferior ni pasillo
        (``reachable`` falso, ``lower_bound_m`` ``None`` y la máscara vacía): quien sigue (T08) dice por qué; un origen que no se pisa es
        lo mismo."""
        ring = np.zeros((9, 9), dtype=bool)
        ring[3:6, 3:6] = True
        ring[4, 4] = False
        mesh = flat_mesh(9, 9, mask=ring)
        net_d = net_of(mesh, (4, 8), 0.1, 0.0)
        for origin in ((4, 4), (3, 3)):
            found = road_net.corridor(net_of(mesh, origin, 0.1, 0.0), net_d, 20.0)
            with self.subTest(origin=origin):
                self.assertFalse(found.reachable)
                self.assertIsNone(found.lower_bound_m)
                self.assertEqual(found.nodes, 0)

    def test_the_corridor_is_built_from_two_networks_of_the_same_mesh(self) -> None:
        """RF-017-09: el pasillo pide dos redes 2D de la misma malla y una holgura finita y no negativa: errores del programa."""
        first, second = flat_mesh(5, 5), flat_mesh(5, 5)
        net_a, net_b, net_c = net_of(first, (0, 0), 0.1, 0.0), net_of(first, (4, 4), 0.1, 0.0), net_of(second, (4, 4), 0.1, 0.0)
        self.assertTrue(road_net.corridor(net_a, net_b, 0.0).reachable)
        with self.assertRaises(ValueError):
            road_net.corridor(net_a, net_c, 0.0)
        for margin in (-1.0, math.nan, math.inf):
            with self.subTest(margin=margin), self.assertRaises(ValueError):
                road_net.corridor(net_a, net_b, margin)
        with self.assertRaises(TypeError):
            road_net.corridor(net_a, first, 0.0)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            road_net.corridor(net_a, net_b, "60")  # type: ignore[arg-type]


class NoVolumesTest(unittest.TestCase):
    def test_nothing_of_a_volume_or_a_length_of_the_road_comes_out_of_the_mesh(self) -> None:
        """RF-017-09: ninguna cifra de volumen ni de longitud de la pista sale de la malla de la ruta: lo que dan la malla, la red y el
        pasillo es la malla, las distancias de búsqueda, la cota inferior y el pasillo (ningún campo de corte, relleno, volumen ni
        longitud de la pista)."""
        names = {field.name for kind in (road_net.RouteMesh, road_net.Network, road_net.Corridor) for field in dataclasses.fields(kind)}
        self.assertTrue({"z", "dist", "lower_bound_m", "mask"} <= names)
        self.assertFalse({name for name in names if any(word in name for word in ("volume", "cut", "fill", "length"))})
        self.assertFalse({name for name in dir(road_net.Corridor) if any(word in name for word in ("volume", "length"))})


class StepsTest(unittest.TestCase):
    def test_the_steps_report_progress_and_the_last_one_carries_the_network(self) -> None:
        """RNF-017-06, RF-017-09: la red 2D va por pasos con su progreso (``Progress`` de la fase de la red, de uno en uno hasta el total) y
        solo el último lleva el resultado (la ``Network``), que es el mismo que el de una corrida con otro presupuesto."""
        mesh = road_net.route_mesh(rd.GRID, np.full(rd.GRID.shape, 100.0), 4.0)  # 100 × 100 nodos
        seen: list[Any] = []
        final = None
        for step in road_net.network_steps(mesh, (50, 50), 0.1, 0.0, budget_s=0.004):
            seen.append(step)
            if step.result is not None:
                final = step.result
        self.assertGreater(len(seen), 2)
        self.assertEqual({step.phase for step in seen}, {"road_net"})
        self.assertEqual([step.done for step in seen[:-1]], list(range(1, len(seen))))
        self.assertTrue(all(step.result is None for step in seen[:-1]))
        self.assertIs(seen[-1].result, final)
        self.assertEqual(seen[-1].done, seen[-1].total)
        self.assertEqual(final.reached, 10_000)
        self.assertTrue(np.array_equal(final.dist, net_of(mesh, (50, 50), 0.1, 0.0).dist))

    def test_each_call_of_a_step_is_within_the_budget(self) -> None:
        """RNF-017-06: cada llamada del paso de la red 2D (la que el hilo de Blender hace a ``next``) tarda como mucho 0,05 s, también con
        200 × 200 nodos (40.000: unos 0,08 s de red entera, en varios pasos); con la máquina cargada, se mide otra vez (la medida
        es del código, no de los demás procesos)."""
        mesh = road_net.route_mesh(rd.GRID, rd.ramp_terrain(rd.GRID), 2.0)  # 200 × 200 nodos
        self.assertEqual(mesh.shape, (200, 200))

        def longest() -> float:
            return drive_steps(road_net.network_steps(mesh, (100, 100), 0.10, 14.0)).longest_s

        count = drive_steps(road_net.network_steps(mesh, (100, 100), 0.10, 14.0))
        self.assertGreater(count.steps, 1)
        self.assertEqual(count.result.reached, 40_000)
        self.assertLessEqual(least_of(longest, STEP_BUDGET_S, attempts=3), STEP_BUDGET_S)

    def test_closing_in_the_middle_leaves_nothing(self) -> None:
        """RNF-017-06, RF-017-09: cerrar el generador a mitad no deja nada: ni resultado a medias, ni cambios en la malla (solo lee), ni
        nada que impida volver a calcular, con el mismo resultado."""
        mesh = road_net.route_mesh(rd.GRID, rd.ramp_terrain(rd.GRID), 4.0)
        kept = (mesh.z.copy(), mesh.walkable.copy(), mesh.forbidden.copy())
        steps = road_net.network_steps(mesh, (50, 50), 0.10, 14.0, budget_s=0.004)
        first = next(steps)
        self.assertIsNone(first.result)
        steps.close()  # type: ignore[attr-defined]
        self.assertEqual(list(steps), [])
        for array, before in zip((mesh.z, mesh.walkable, mesh.forbidden), kept, strict=True):
            self.assertTrue(np.array_equal(array, before, equal_nan=True))
        again = net_of(mesh, (50, 50), 0.10, 14.0)
        self.assertEqual(again.reached, 10_000)
        never = road_net.network_steps(mesh, (50, 50), 0.10, 14.0)
        never.close()  # type: ignore[attr-defined]  # sin empezar: tampoco hay nada que deshacer
        self.assertEqual(list(never), [])


if __name__ == "__main__":
    unittest.main()
