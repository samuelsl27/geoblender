# SPDX-License-Identifier: GPL-3.0-or-later
"""La transición del borde de un diseño con el terreno no afectado (spec 014, T26 y T40; HU-014-5;
RF-014-19; plan 014 A10, §5.3.1; hallazgo F-1 de la T38).

``design.edges.transition_steps``: semillas ``z`` (la superficie de partida) en el anillo exterior
de una celda del dominio ``D`` con dato de terreno; ``T↓ = ENV↓(·, tan θ)`` y ``T↑ = ENV↑(·, tan θ)``
con la envolvente de la 013 y el ángulo de transición ``θ`` (el parámetro
``des.edge.transition_deg``, sin valor por defecto: D-9); dentro de ``D``, ``S'' = clip(mín(máx(S,
T↓), T↑), mín(S, z), máx(S, z))``: la transición **solo acerca la superficie al terreno** (T40: no
convierte un corte en relleno ni un relleno en corte, ni ahonda un corte ni sube un relleno); fuera,
``S``; el volumen de la transición, ``Σ |S'' − S| · área de celda``.

- A mano: un terreno llano de 100 m y un dominio de 10 × 20 celdas de 2 m con una corta de 10 m en
  su mitad oeste y un relleno de 10 m en la este; con el *chamfer* 5×5 la distancia al anillo de
  una celda a ``k`` celdas del borde es ``k · 2 · 0,98644`` m, así que ``S''`` y el volumen salen a
  mano por anillos (56, 48, 40, 32 y 24 celdas a 1 … 5 celdas).
- Por fuerza bruta: una ladera con onda, un dominio con una muesca, una celda del anillo sin dato
  y una celda de la superficie sin dato, con la euclídea exacta.
- En los dos: ninguna pareja del borde (una celda del dominio y su vecina fuera, con dato de
  terreno) más empinada que ``θ``, cuando antes lo eran.
- Junto a un escarpe previo más empinado que ``θ`` (T40, F-1): una corta de 4 m a su pie, en una
  zona sin relleno admitido, no pasa a relleno (antes, 80 celdas por encima del terreno, hasta
  2,31 m y 93,5 m³); una corta de 2 m en lo alto no se ahonda (antes, 20 celdas hasta 0,31 m, y el
  salto creado subía de 2,0 a 2,31 m); y en 20 casos al azar con escarpes, la de la euclídea exacta
  es la cota de la fuerza bruta y ninguna celda del dominio queda fuera de ``[mín(S, z), máx(S,
  z)]`` con ninguna de las dos métricas.
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


def joined(surface: np.ndarray, start: np.ndarray, domain: np.ndarray, *, tan: float = TAN,
           step: float = STEP) -> np.ndarray:
    """``S' = mín(máx(S, T↓), T↑)`` en el dominio (A10 sin acotar), con las envolventes euclídeas
    exactas por fuerza bruta desde el anillo (8 vecinos, con dato de terreno); fuera, ``S``."""
    ring = np.zeros(domain.shape, dtype=bool)
    padded = np.pad(domain, 1)
    for d_row, d_col in NEIGHBOURS_8:
        ring |= padded[1 + d_row:1 + d_row + domain.shape[0], 1 + d_col:1 + d_col + domain.shape[1]]
    ring &= ~domain & np.isfinite(start)
    upper = oracles.brute_force_euclidean(np.where(ring, start, np.inf), tan, step,
                                          direction="up")
    lower = oracles.brute_force_euclidean(np.where(ring, start, -np.inf), tan, step,
                                          direction="down")
    return np.where(domain, np.minimum(np.maximum(surface, lower), upper), surface)


def brute_force(surface: np.ndarray, start: np.ndarray, domain: np.ndarray, *, tan: float = TAN,
                step: float = STEP) -> np.ndarray:
    """``S''``: :func:`joined` acotada en el dominio entre ``mín(S, z)`` y ``máx(S, z)`` (T40; sin
    dato de terreno, ``S``)."""
    raw = joined(surface, start, domain, tan=tan, step=step)
    low, high = np.fmin(surface, start), np.fmax(surface, start)
    return np.where(domain, np.clip(raw, low, high), surface)


def outside(found: np.ndarray, surface: np.ndarray, start: np.ndarray, domain: np.ndarray
            ) -> np.ndarray:
    """Las celdas del dominio con dato que quedan fuera de ``[mín(S, z), máx(S, z)]``: las que la
    transición aleja del terreno (las que pasan de corte a relleno o al revés, o se ahondan o
    suben más que el diseño)."""
    with np.errstate(invalid="ignore"):
        low, high = np.fmin(surface, start), np.fmax(surface, start)
        return domain & np.isfinite(found) & ((found < low) | (found > high))


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
        """RF-014-19, A10: ``S'' = clip(mín(máx(S, T↓), T↑), mín(S, z), máx(S, z))`` en el dominio
        a ≤ 10⁻⁹ m (en esta ladera, más tendida que ``θ``, la cota no cambia nada); la celda sin
        dato sigue sin dato y la del anillo sin dato no siembra; el volumen, ``Σ |S'' − S| · 4 m²``
        a mano."""
        expected = brute_force(self.surface, self.start, self.domain)
        np.testing.assert_array_equal(expected, joined(self.surface, self.start, self.domain))
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


# --- Junto a un escarpe previo (T40; hallazgo F-1 de la T38) --------------------------------------

SCARP_ANGLE_DEG = 35.0
"""El ángulo de transición de los casos del escarpe (el del análisis de la cantera)."""
SCARP_REACH = math.tan(math.radians(SCARP_ANGLE_DEG)) * CHAMFER_SCALE
"""Lo que baja (o sube) la transición por celda de 1 m en línea recta: ``tan 35° · 0,98644``."""
SCARP_THICKNESS_M = 0.02
"""El espesor mínimo de la 012 de los casos (un dato de entrada)."""


def scarp_edge(surface: np.ndarray, start: np.ndarray, allowed: np.ndarray) -> Any:
    """La operación ``des.edge_transition`` (``edge_transition_steps``) en la rejilla de 40 × 40
    celdas de 1 m con lo que admiten las máscaras ``allowed`` (el corte **o** el relleno
    admitidos, como ``design.store``): salto admitido de 1 m y el 99 %."""
    return finish(edges.edge_transition_steps(
        surface, start, dfx.grid_from(40, 40, 1.0), angle_deg=SCARP_ANGLE_DEG,
        min_thickness_m=SCARP_THICKNESS_M, threshold_m=1.0, share_pct=99.0, allowed=allowed,
        name="Escarpe"))


class ScarpTest(unittest.TestCase):
    """RF-014-19, HU-014-5, A10 (T40; F-1): con un escarpe previo de 3 m más empinado que ``θ`` en
    el anillo, la transición solo acerca la superficie al terreno."""

    def test_a_cut_at_the_foot_of_a_scarp_is_not_turned_into_fill(self) -> None:
        """(a) Una corta de 4 m (a 96 m) al pie de un escarpe de 3 m (el terreno, 100 m, y 103 m
        en las 10 filas del norte), en una zona **sin relleno admitido** (la 012 solo admite ahí
        el corte): ninguna celda queda por encima del terreno (antes, la descendente desde lo alto
        del escarpe subía 80 celdas sobre él, hasta 2,31 m y 93,5 m³). A mano: a ``k`` celdas del
        escarpe, ``T↓ = 103 − tan 35° · 0,98644 · k`` pasa del terreno si ``k ≤ 4`` (3 / 0,6907 =
        4,34): esas 4 filas (80 celdas) se quedan en el terreno bit a bit, sin moverse; las demás,
        entre la corta y el terreno; el salto creado, ≤ 1 m y sin aviso."""
        start = np.full((40, 40), 100.0)
        start[:10] = 103.0
        surface = start.copy()
        surface[10:20, 10:30] = 96.0
        fill_allowed = np.ones((40, 40), dtype=bool)
        fill_allowed[10:20, 10:30] = False
        outcome = scarp_edge(surface, start, np.ones((40, 40), dtype=bool) | fill_allowed)
        grid = outcome.grid
        np.testing.assert_array_equal(outcome.domain, surface != start)
        self.assertEqual(int(np.count_nonzero((grid > start) & ~fill_allowed)), 0)
        self.assertEqual(int(outside(grid, surface, start, outcome.domain).sum()), 0)
        self.assertTrue(all(3.0 - SCARP_REACH * k > 0.0 for k in range(1, 5)))
        self.assertLess(3.0 - SCARP_REACH * 5, 0.0)
        np.testing.assert_array_equal(grid[10:14, 10:30], start[10:14, 10:30])
        self.assertTrue(bool(((grid[14:20, 10:30] >= 96.0) & (grid[14:20, 10:30] < 100.0)).all()))
        self.assertLessEqual(outcome.report.maximum_m, 1.0)
        self.assertFalse(outcome.report.warned)

    def test_b_a_cut_on_top_of_a_scarp_is_not_deepened(self) -> None:
        """(b) Una corta de 2 m (a 101 m) en lo alto de un escarpe de 3 m (103 m en las 20 filas
        del norte, 100 m al sur), hasta su borde: ninguna celda queda por debajo de la corta
        (antes, la ascendente desde el pie la ahondaba en las 20 celdas de la fila del borde,
        ``100 + 0,6907`` = 100,69 m, 0,31 m) y el salto creado no pasa del de sin transición: 2,0 m,
        a mano, entre la corta (101 m) y lo alto del escarpe (103 m) en las esquinas de esa fila
        (antes, 2,31 m)."""
        start = np.full((40, 40), 100.0)
        start[:20] = 103.0
        surface = start.copy()
        surface[5:20, 10:30] = 101.0
        outcome = scarp_edge(surface, start, np.ones((40, 40), dtype=bool))
        grid = outcome.grid
        self.assertEqual(int(np.count_nonzero(outcome.domain & (grid < surface))), 0)
        self.assertEqual(int(outside(grid, surface, start, outcome.domain).sum()), 0)
        np.testing.assert_array_equal(grid[19, 10:30], surface[19, 10:30])
        before = finish(edges.created_steps(surface, start, outcome.domain,
                                            dfx.grid_from(40, 40, 1.0), SCARP_THICKNESS_M, 1.0,
                                            99.0))
        self.assertEqual(before.maximum_m, 2.0)
        self.assertEqual(outcome.report.maximum_m, 2.0)


RANDOM_CASES = 20


def scarp_case(seed: int) -> tuple[Any, float, np.ndarray, np.ndarray, np.ndarray, float]:
    """Un caso al azar: una rejilla de 16 a 28 celdas por lado de 1 o 2 m; una ladera con un
    **escarpe** de 2 a 6 m (de subida o de bajada) a lo largo de una fila o de una columna; una
    corta y un relleno de 1 a 6 m en rectángulos al azar (pueden cruzar el escarpe); el ángulo de
    transición, de 20 a 45°; el dominio, las celdas que mueve el diseño (``transition_domain``).
    Devuelve la rejilla, el paso, el terreno, el diseño, el dominio y el ángulo."""
    rng = np.random.default_rng(seed)
    nrows, ncols = (int(value) for value in rng.integers(16, 29, size=2))
    step = float(rng.choice((1.0, 2.0)))
    rows, cols = np.indices((nrows, ncols))
    x, y = (cols + 0.5) * step, (nrows - rows - 0.5) * step
    start = 200.0 + rng.uniform(-0.3, 0.3) * x + rng.uniform(-0.3, 0.3) * y
    height = float(rng.uniform(2.0, 6.0) * rng.choice((-1.0, 1.0)))
    if rng.random() < 0.5:
        start += np.where(rows < int(rng.integers(nrows // 4, 3 * nrows // 4)), height, 0.0)
    else:
        start += np.where(cols < int(rng.integers(ncols // 4, 3 * ncols // 4)), height, 0.0)
    surface = start.copy()
    for change in (-rng.uniform(1.0, 6.0), rng.uniform(1.0, 6.0)):
        top, left = int(rng.integers(1, nrows - 5)), int(rng.integers(1, ncols - 5))
        bottom = int(rng.integers(top + 3, nrows))
        right = int(rng.integers(left + 3, ncols))
        surface[top:bottom, left:right] = start[top:bottom, left:right] + change
    domain = edges.transition_domain(surface, start, SCARP_THICKNESS_M)
    return (dfx.grid_from(nrows, ncols, step), step, start, surface, domain,
            float(rng.uniform(20.0, 45.0)))


class RandomScarpTest(unittest.TestCase):
    """RF-014-19, A10 (T40; F-1): 20 casos al azar con escarpes."""

    def test_the_transition_never_moves_a_cell_away_from_the_terrain(self) -> None:
        """En cada caso, con la euclídea exacta, la transición es la de la fuerza bruta (A10 acotada
        entre ``mín(S, z)`` y ``máx(S, z)``) a ≤ 10⁻⁹ m, con su volumen; con las dos métricas,
        ninguna celda del dominio queda fuera de ``[mín(S, z), máx(S, z)]``. Sin la cota (A10 antes
        de la T40), al menos la mitad de los casos deja celdas fuera (16 de los 20: 324 celdas,
        hasta 3,88 m): los escarpes cuentan."""
        away = 0
        for seed in range(RANDOM_CASES):
            geometry, step, start, surface, domain, angle = scarp_case(seed)
            tan = math.tan(math.radians(angle))
            with self.subTest(seed=seed):
                self.assertTrue(domain.any())
                raw = joined(surface, start, domain, tan=tan, step=step)
                away += int(outside(raw, surface, start, domain).any())
                expected = brute_force(surface, start, domain, tan=tan, step=step)
                exact = finish(edges.transition_steps(surface, start, domain, geometry, angle,
                                                      metric="exact"))
                chamfer = finish(edges.transition_steps(surface, start, domain, geometry, angle))
                self.assertLessEqual(float(np.abs(exact.grid - expected).max()), TOLERANCE_M)
                moved = np.abs(expected - surface)
                self.assertAlmostEqual(exact.volume_m3,
                                       math.fsum(moved.ravel().tolist()) * step * step,
                                       delta=1e-6)
                for found in (exact, chamfer):
                    self.assertEqual(int(outside(found.grid, surface, start, domain).sum()), 0)
                    np.testing.assert_array_equal(found.grid[~domain], surface[~domain])
        self.assertGreaterEqual(away, RANDOM_CASES // 2)


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

    def test_a_domain_cell_without_terrain_keeps_the_design(self) -> None:
        """T40 (la transición solo acerca la superficie al terreno): una celda del dominio sin dato
        de terreno no tiene terreno al que acercarse y conserva la superficie de diseño bit a bit
        (antes, la celda de la corta a 5 celdas del borde subía de 90 a ``100 − t·a·5``); sus
        vecinas, como siempre."""
        start = self.start.copy()
        start[10, 10] = np.nan
        found = finish(edges.transition_steps(self.surface, start, self.domain, self.geometry,
                                              ANGLE_DEG))
        self.assertEqual(found.grid[10, 10], self.surface[10, 10])
        reference = finish(edges.transition_steps(self.surface, self.start, self.domain,
                                                  self.geometry, ANGLE_DEG))
        self.assertGreater(reference.grid[10, 10], self.surface[10, 10])
        np.testing.assert_array_equal(found.grid[9:12, 11], reference.grid[9:12, 11])

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
