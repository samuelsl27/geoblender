# SPDX-License-Identifier: GPL-3.0-or-later
"""La transición del borde de un diseño con el terreno no afectado (spec 014, T26; HU-014-5;
RF-014-19; plan 014 A10, §5.3.1).

``design.edges.transition_steps``: semillas ``z`` (la superficie de partida) en el anillo exterior
de una celda del dominio ``D`` con dato de terreno; ``T↓ = ENV↓(·, tan θ)`` y ``T↑ = ENV↑(·, tan θ)``
con la envolvente de la 013 y el ángulo de transición ``θ`` (el parámetro
``des.edge.transition_deg``, sin valor por defecto: D-9); dentro de ``D``, ``S' = mín(máx(S, T↓),
T↑)``; fuera, ``S``; el volumen de la transición, ``Σ |S' − S| · área de celda``.

- A mano: un terreno llano de 100 m y un dominio de 10 × 20 celdas de 2 m con una corta de 10 m en
  su mitad oeste y un relleno de 10 m en la este; con el *chamfer* 5×5 la distancia al anillo de
  una celda a ``k`` celdas del borde es ``k · 2 · 0,98644`` m, así que ``S'`` y el volumen salen a
  mano por anillos (56, 48, 40, 32 y 24 celdas a 1 … 5 celdas).
- Por fuerza bruta: una ladera con onda, un dominio con una muesca, una celda del anillo sin dato
  y una celda de la superficie sin dato, con la euclídea exacta.
- En los dos: ninguna pareja del borde (una celda del dominio y su vecina fuera, con dato de
  terreno) más empinada que ``θ``, cuando antes lo eran.
"""

from __future__ import annotations

import math
import unittest
from typing import Any

import numpy as np

from tests.support import design_fixtures as dfx
from tests.support import design_oracles as oracles
from tests.support.package import import_geoblender

edges = import_geoblender("design.edges")
messages = import_geoblender("design.messages")

TOLERANCE_M = 1e-9
ANGLE_DEG = 30.0
"""El ángulo de transición de las pruebas (un dato de entrada: D-9, sin valor por defecto)."""
TAN = math.tan(math.radians(ANGLE_DEG))
STEP = 2.0
CHAMFER_SCALE = 0.98644
"""La escala del *chamfer* 5×5 (ADR-0014): un paso de eje cuesta ``h · 0,98644``."""

NEIGHBOURS_4 = ((1, 0), (-1, 0), (0, 1), (0, -1))
NEIGHBOURS_8 = (*NEIGHBOURS_4, (1, 1), (1, -1), (-1, 1), (-1, -1))


def finish(steps: Any) -> Any:
    return list(steps)[-1].result


def edge_pairs(domain: np.ndarray, start: np.ndarray, neighbours: tuple[tuple[int, int], ...]
               ) -> list[tuple[int, int, int, int]]:
    """Las parejas del borde: una celda del dominio y su vecina fuera de él con dato de terreno
    (fila y columna de cada una)."""
    nrows, ncols = domain.shape
    found = []
    for row, col in zip(*np.nonzero(domain), strict=True):
        for d_row, d_col in neighbours:
            other_row, other_col = int(row) + d_row, int(col) + d_col
            if (0 <= other_row < nrows and 0 <= other_col < ncols
                    and not domain[other_row, other_col]
                    and math.isfinite(start[other_row, other_col])):
                found.append((int(row), int(col), other_row, other_col))
    return found


def steepest(surface: np.ndarray, start: np.ndarray, pairs: list[tuple[int, int, int, int]]
             ) -> float:
    """La mayor tangente de las parejas: ``|S(a) − z(b)| / |a − b|`` (las celdas de la superficie
    sin dato no cuentan)."""
    worst = 0.0
    for row, col, other_row, other_col in pairs:
        level = float(surface[row, col])
        if math.isfinite(level):
            run = STEP * math.hypot(row - other_row, col - other_col)
            worst = max(worst, abs(level - float(start[other_row, other_col])) / run)
    return worst


# --- A mano: terreno llano, corta y relleno de 10 m ----------------------------------------------

FLAT_ROWS, FLAT_COLS = 20, 30
DOMAIN_ROWS, DOMAIN_COLS = (5, 14), (5, 24)
"""El dominio: filas 5 a 14 y columnas 5 a 24 (10 × 20 celdas, 800 m²)."""
LEVEL_M, DEPTH_M = 100.0, 10.0


def flat_case() -> tuple[Any, np.ndarray, np.ndarray, np.ndarray]:
    """La rejilla, el terreno llano, el dominio y la superficie: la corta de 10 m en las columnas
    5 a 14 del dominio y el relleno de 10 m en las 15 a 24; fuera, el terreno."""
    geometry = dfx.grid_from(FLAT_ROWS, FLAT_COLS, STEP)
    start = np.full((FLAT_ROWS, FLAT_COLS), LEVEL_M)
    domain = np.zeros((FLAT_ROWS, FLAT_COLS), dtype=bool)
    domain[DOMAIN_ROWS[0]:DOMAIN_ROWS[1] + 1, DOMAIN_COLS[0]:DOMAIN_COLS[1] + 1] = True
    surface = start.copy()
    surface[DOMAIN_ROWS[0]:DOMAIN_ROWS[1] + 1, 5:15] = LEVEL_M - DEPTH_M
    surface[DOMAIN_ROWS[0]:DOMAIN_ROWS[1] + 1, 15:25] = LEVEL_M + DEPTH_M
    return geometry, start, domain, surface


class HandTest(unittest.TestCase):
    """RF-014-19, A10: el terreno llano, con el *chamfer* 5×5 (la métrica por defecto) y el
    resultado a mano."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.geometry, cls.start, cls.domain, cls.surface = flat_case()
        cls.before = (cls.start.copy(), cls.domain.copy(), cls.surface.copy())
        cls.found = finish(edges.transition_steps(cls.surface, cls.start, cls.domain,
                                                  cls.geometry, ANGLE_DEG))

    def test_no_edge_pair_is_steeper_than_the_angle(self) -> None:
        """RF-014-19: ninguna pareja del borde (4 vecinos y diagonales) queda más empinada que
        ``θ`` = 30°; antes, la corta y el relleno de 10 m lo eran (tangente 5 en 2 m)."""
        for neighbours in (NEIGHBOURS_4, NEIGHBOURS_8):
            pairs = edge_pairs(self.domain, self.start, neighbours)
            with self.subTest(neighbours=len(neighbours)):
                self.assertTrue(pairs)
                self.assertGreater(steepest(self.surface, self.start, pairs), 4.0)
                self.assertLessEqual(steepest(self.found.grid, self.start, pairs),
                                     TAN + TOLERANCE_M)

    def test_surface_by_hand(self) -> None:
        """RF-014-19, A10: a ``k`` celdas del borde (1 en la primera fila del dominio),
        ``S' = máx(90, 100 − t·a·k)`` en la corta y ``mín(110, 100 + t·a·k)`` en el relleno, con
        ``a = 2 · 0,98644`` m; fuera del dominio, la superficie tal cual."""
        rows, cols = np.indices(self.start.shape)
        k = np.minimum.reduce([rows - DOMAIN_ROWS[0] + 1, DOMAIN_ROWS[1] - rows + 1,
                               cols - DOMAIN_COLS[0] + 1, DOMAIN_COLS[1] - cols + 1])
        reach = TAN * STEP * CHAMFER_SCALE * k
        expected = self.surface.copy()
        cut = self.domain & (cols < 15)
        fill = self.domain & (cols >= 15)
        expected[cut] = np.maximum(LEVEL_M - DEPTH_M, LEVEL_M - reach[cut])
        expected[fill] = np.minimum(LEVEL_M + DEPTH_M, LEVEL_M + reach[fill])
        self.assertLessEqual(float(np.abs(self.found.grid - expected).max()), TOLERANCE_M)
        np.testing.assert_array_equal(self.found.grid[~self.domain], self.surface[~self.domain])

    def test_volume_by_hand(self) -> None:
        """RF-014-19: el volumen de la transición. Por anillos del dominio de 10 × 20 celdas, 56,
        48, 40, 32 y 24 celdas a 1 … 5 celdas del borde (Σ n·k = 520); en cada una cambian
        ``10 − t·a·k`` m (la corta sube y el relleno baja lo mismo, por simetría): ``V = 4 m² ·
        (10 m · 200 − t·a · 520)`` = 5.630,8 m³, en las 200 celdas."""
        unit = TAN * STEP * CHAMFER_SCALE
        rings = ((1, 56), (2, 48), (3, 40), (4, 32), (5, 24))
        self.assertEqual(sum(cells for _k, cells in rings), 200)
        self.assertEqual(sum(k * cells for k, cells in rings), 520)
        by_hand = STEP * STEP * (DEPTH_M * 200 - unit * 520)
        self.assertAlmostEqual(by_hand, 5_630.8, delta=0.05)
        self.assertAlmostEqual(self.found.volume_m3, by_hand, delta=1e-6)
        self.assertEqual(self.found.cells, 200)
        self.assertEqual(self.found.area_m2, 800.0)
        self.assertEqual(self.found.angle_deg, ANGLE_DEG)
        self.assertEqual(self.found.cell_area_m2, STEP * STEP)

    def test_inputs_are_not_modified(self) -> None:
        """Ninguna entrada se modifica y la superficie nueva es otra rejilla."""
        for current, before in zip((self.start, self.domain, self.surface), self.before,
                                   strict=True):
            np.testing.assert_array_equal(current, before)
        self.assertIsNot(self.found.grid, self.surface)

    def test_steps_end_in_the_transition_phase(self) -> None:
        """RF-014-19: por pasos; el último, de la fase ``transition``, lleva la transición."""
        steps = list(edges.transition_steps(self.surface, self.start, self.domain, self.geometry,
                                            ANGLE_DEG))
        self.assertEqual(steps[-1].phase, "transition")
        self.assertIsInstance(steps[-1].result, edges.Transition)


# --- Por fuerza bruta: ladera con onda, dominio con muesca -----------------------------------------

ROWS, COLS = 20, 24


def slope_case() -> tuple[Any, np.ndarray, np.ndarray, np.ndarray]:
    """Una ladera ``280 + 0,2·x + 0,1·y`` con una onda (pendiente < 0,47, menos que tan 30°), una
    celda del anillo sin dato; el dominio, filas 4 a 15 y columnas 4 a 19 con una muesca de 4 × 4
    en su borde norte; la superficie, una corta de 15 m al oeste de la columna 12 y un relleno de
    8 m al este, salvo 4 × 4 celdas del interior que se quedan en el terreno, con una celda sin
    dato."""
    geometry = dfx.grid_from(ROWS, COLS, STEP)
    x = (np.arange(COLS) + 0.5) * STEP
    y = ROWS * STEP - (np.arange(ROWS) + 0.5) * STEP
    xs, ys = np.meshgrid(x, y)
    start = 280.0 + 0.2 * xs + 0.1 * ys + np.sin(xs / 7.0) * np.cos(ys / 5.0)
    start[3, 6] = np.nan
    domain = np.zeros((ROWS, COLS), dtype=bool)
    domain[4:16, 4:20] = True
    domain[4:8, 10:14] = False
    surface = start.copy()
    west = domain & (xs < 12 * STEP)
    surface[west] -= 15.0
    surface[domain & ~west] += 8.0
    surface[9:13, 14:18] = start[9:13, 14:18]
    surface[10, 8] = np.nan
    return geometry, start, domain, surface


def brute_force(surface: np.ndarray, start: np.ndarray, domain: np.ndarray) -> np.ndarray:
    """``S'`` con las envolventes euclídeas exactas por fuerza bruta desde el anillo."""
    ring = np.zeros(domain.shape, dtype=bool)
    for d_row, d_col in NEIGHBOURS_8:
        ring |= np.roll(np.roll(domain, d_row, axis=0), d_col, axis=1)
    ring &= ~domain & np.isfinite(start)
    seeds = np.where(ring, start, np.inf)
    upper = oracles.brute_force_euclidean(seeds, TAN, STEP, direction="up")
    lower = oracles.brute_force_euclidean(np.where(ring, start, -np.inf), TAN, STEP,
                                          direction="down")
    return np.where(domain, np.minimum(np.maximum(surface, lower), upper), surface)


class BruteForceTest(unittest.TestCase):
    """RF-014-19, A10: con la euclídea exacta, frente a la fuerza bruta en una ladera."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.geometry, cls.start, cls.domain, cls.surface = slope_case()
        cls.found = finish(edges.transition_steps(cls.surface, cls.start, cls.domain,
                                                  cls.geometry, ANGLE_DEG, metric="exact"))
        cls.chamfer = finish(edges.transition_steps(cls.surface, cls.start, cls.domain,
                                                    cls.geometry, ANGLE_DEG))

    def test_exact_surface_and_volume_against_the_brute_force(self) -> None:
        """RF-014-19, A10: ``S' = mín(máx(S, T↓), T↑)`` en el dominio a ≤ 10⁻⁹ m; la celda sin
        dato sigue sin dato y la del anillo sin dato no siembra; el volumen, ``Σ |S' − S| · 4 m²``
        a mano."""
        expected = brute_force(self.surface, self.start, self.domain)
        same_nan = np.isnan(self.found.grid) == np.isnan(expected)
        self.assertTrue(bool(same_nan.all()))
        self.assertTrue(math.isnan(self.found.grid[10, 8]))
        finite = np.isfinite(expected)
        self.assertLessEqual(float(np.abs(self.found.grid[finite] - expected[finite]).max()),
                             TOLERANCE_M)
        moved = np.abs(expected - self.surface)[finite]
        self.assertAlmostEqual(self.found.volume_m3, math.fsum(moved.tolist()) * STEP * STEP,
                               delta=1e-6)
        self.assertEqual(self.found.cells, int(np.count_nonzero(moved > TOLERANCE_M)))
        self.assertGreater(self.found.cells, 0)
        self.assertLess(self.found.cells, int(self.domain.sum()) - 1)

    def test_no_edge_pair_is_steeper_than_the_angle(self) -> None:
        """RF-014-19: con las dos métricas, ninguna pareja del borde (4 vecinos y diagonales)
        queda más empinada que ``θ``; antes lo eran."""
        for neighbours in (NEIGHBOURS_4, NEIGHBOURS_8):
            pairs = edge_pairs(self.domain, self.start, neighbours)
            self.assertGreater(steepest(self.surface, self.start, pairs), 2.0)
            for metric, found in (("exact", self.found), ("chamfer5", self.chamfer)):
                with self.subTest(neighbours=len(neighbours), metric=metric):
                    self.assertLessEqual(steepest(found.grid, self.start, pairs),
                                         TAN + TOLERANCE_M)

    def test_cells_between_the_envelopes_do_not_change(self) -> None:
        """Donde la superficie ya está entre ``T↓`` y ``T↑`` (las 16 celdas que se quedan en el
        terreno, cuya pendiente es menor que ``θ``) no cambia ni un bit, y fuera del dominio
        tampoco."""
        expected = brute_force(self.surface, self.start, self.domain)
        kept = np.isfinite(self.surface) & (np.abs(expected - self.surface) <= TOLERANCE_M)
        self.assertEqual(int((kept & self.domain).sum()), 16)
        np.testing.assert_array_equal(self.found.grid[kept], self.surface[kept])
        np.testing.assert_array_equal(self.found.grid[~self.domain],
                                      self.surface[~self.domain])


class LimitsTest(unittest.TestCase):
    """RF-014-19: los rechazos y los casos sin transición."""

    def setUp(self) -> None:
        self.geometry, self.start, self.domain, self.surface = flat_case()

    def test_angle_is_the_parameter_without_default(self) -> None:
        """El ángulo es ``des.edge.transition_deg``: sin valor (D-9) o fuera de (0; 90) se
        rechaza al llamar, nombrando la clave."""
        for value, code in ((None, "des.quarry_param_missing"), (0.0, "des.quarry_param_range"),
                            (90.0, "des.quarry_param_range")):
            with self.subTest(value=value), self.assertRaises(messages.DesignError) as caught:
                edges.transition_steps(self.surface, self.start, self.domain, self.geometry,
                                       value)
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(caught.exception.field, "des.edge.transition_deg")

    def test_wrong_shapes_and_metrics_are_program_errors(self) -> None:
        """Una rejilla de otra forma o una métrica desconocida son errores del programa al
        llamar."""
        for surface, start, domain in ((self.surface[:3], self.start, self.domain),
                                       (self.surface, self.start[:3], self.domain),
                                       (self.surface, self.start, self.domain[:3])):
            with self.assertRaises(ValueError):
                edges.transition_steps(surface, start, domain, self.geometry, ANGLE_DEG)
        with self.assertRaises(ValueError):
            edges.transition_steps(self.surface, self.start, self.domain, self.geometry,
                                   ANGLE_DEG, metric="chamfer3")

    def test_without_untouched_terrain_nothing_changes(self) -> None:
        """Sin anillo con dato (el dominio es toda la rejilla, o el anillo no tiene terreno) no
        hay transición: la superficie tal cual, 0 m³ y 0 celdas."""
        whole = np.ones(self.domain.shape, dtype=bool)
        no_ring = self.start.copy()
        no_ring[~self.domain] = np.nan
        for domain, start in ((whole, self.start), (self.domain, no_ring)):
            found = finish(edges.transition_steps(self.surface, start, domain, self.geometry,
                                                  ANGLE_DEG))
            np.testing.assert_array_equal(found.grid, self.surface)
            self.assertEqual(found.volume_m3, 0.0)
            self.assertEqual(found.cells, 0)


if __name__ == "__main__":
    unittest.main()
