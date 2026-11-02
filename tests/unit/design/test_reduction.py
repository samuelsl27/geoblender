# SPDX-License-Identifier: GPL-3.0-or-later
"""Las dos reducciones exactas de semillas de la euclídea exacta (spec 013, T08; HU-013-3;
RF-013-12; CE-013-01; plan 013 A5, D-22, T3; ADR-0014).

``design.reduction`` retira de la búsqueda exacta las semillas que no pueden ser la mejor de ninguna
celda, sin cambiar ninguna cota (``T(p) = mín_q [f_q + k·|p − q|]``, con ``k = t·h`` m por celda de
distancia):

- **Dominada**: ``U(q) < f_q − 10⁻⁹`` con ``U`` una cota superior de ``T`` (el *chamfer* sin
  escala, que es la longitud de un camino real): otra semilla da menos en la propia celda de ``q``
  y, como ``T`` es ``k``-Lipschitz, ``q`` nunca es la mejor.
- **Redundante**: sus 8 vecinas son semillas con ``f_n ≤ f_q + k·g`` (``g`` = ``MIN_GAIN``): para
  cualquier otra celda ``p``, la vecina mejor orientada queda al menos ``g`` más cerca y su cono no
  es mayor. ``p`` es siempre el centro de una celda, así que ``g`` es el mínimo sobre la retícula
  entera (1, en los puntos del eje), no el del plano continuo (0,4824).

Se comprueba, frente a la fuerza bruta de los oráculos (``tests/support/design_oracles.py``),
que **ninguna cota cambia** (≤ 10⁻⁹ m) en ≥ 400 casos aleatorios de semillas sueltas, de contorno y
macizas, con la cota más ceñida posible (``U = T``) y con la del *chamfer* sin escala; que el
umbral de la redundante es el límite exacto (con un poco más, quitar la semilla sí cambia la cota);
y las cuentas a mano.
"""

from __future__ import annotations

import math
import unittest
from typing import Any

import numpy as np

from tests.support import design_fixtures as dfx
from tests.support import design_oracles as oracles
from tests.support.package import import_geoblender

reduction = import_geoblender("design.reduction")

TOLERANCE_M = 1e-9
NEIGHBOURS = tuple((d_row, d_col) for d_row in (-1, 0, 1) for d_col in (-1, 0, 1)
                   if (d_row, d_col) != (0, 0))


def seeds_of(shape: tuple[int, int], cells: dict[tuple[int, int], float]) -> np.ndarray:
    """Una rejilla ``+inf`` con las semillas ``{(fila, columna): cota}``."""
    found = np.full(shape, np.inf)
    for cell, z in cells.items():
        found[cell] = z
    return found


def brute(values: np.ndarray, tan: float, step: float) -> np.ndarray:
    """La euclídea exacta por fuerza bruta (oráculo), ascendente."""
    return oracles.brute_force_euclidean(values, tan, step)


def reduced_brute(values: np.ndarray, found: Any, tan: float, step: float) -> np.ndarray:
    """Lo que da la búsqueda con solo las semillas que quedan, más la propia cota en las celdas
    retiradas (``mín(T, f)``): la forma de usar una ``Reduction`` (plan 013, A5)."""
    kept = np.full(values.shape, np.inf)
    kept[found.rows, found.cols] = found.values
    return np.minimum(brute(kept, tan, step), values)


zone = dfx.random_zone


class MinGainTest(unittest.TestCase):
    """La ganancia mínima ``g`` de la redundante es el ínfimo exacto sobre las celdas."""

    def test_the_minimum_gain_over_the_lattice_is_one(self) -> None:
        """RF-013-12, plan A5: para todo desplazamiento entero ``p − q ≠ 0`` (hasta 60 celdas), la
        mejor de las 8 vecinas de ``q`` deja ``p`` más cerca en ``|p − q| − |p − n| ≥ g``, y hay
        celdas (el eje, ``(d, 0)``) en las que es exactamente ``g``: ``MIN_GAIN`` es el mínimo de la
        retícula, ni más (quitaría semillas que importan) ni menos (reduciría de menos)."""
        radius = 60
        offsets = np.arange(-radius, radius + 1, dtype=np.float64)
        d_col, d_row = np.meshgrid(offsets, offsets)
        keep = (d_col != 0) | (d_row != 0)
        d_col, d_row = d_col[keep], d_row[keep]
        distance = np.hypot(d_row, d_col)
        best = np.full(distance.shape, -np.inf)
        for n_row, n_col in NEIGHBOURS:
            best = np.maximum(best, distance - np.hypot(d_row - n_row, d_col - n_col))
        self.assertAlmostEqual(float(best.min()), reduction.MIN_GAIN, delta=1e-12)
        self.assertGreaterEqual(float(best.min()), reduction.MIN_GAIN - 1e-12)


class DominatedTest(unittest.TestCase):
    """``U(q) < f_q − 10⁻⁹``: otra semilla da menos en su propia celda."""

    def test_a_seed_that_another_one_undercuts_is_dominated(self) -> None:
        """A mano: dos semillas en una fila de 9 celdas de 1 m, con ``k = 1``: la de 90 en la celda
        0 da 94 en la 4, así que la de 100 de la 4 queda dominada; con 96 empata (100) y no lo
        está; con 95,9999 sí; la que da menos nunca lo está."""
        for low, dominated in ((90.0, True), (96.0, False), (95.9999, True), (96.0 + 1e-10, False)):
            values = seeds_of((1, 9), {(0, 0): low, (0, 4): 100.0})
            bound = oracles.dijkstra(values, 1.0, 1.0, scale=1.0)
            found = reduction.dominated_cells(values, bound)
            with self.subTest(low=low):
                self.assertEqual(bool(found[0, 4]), dominated)
                self.assertFalse(found[0, 0])
                self.assertEqual(int(found.sum()), int(dominated))

    def test_only_seeds_are_dominated_and_the_tolerance_is_one_nanometre_of_height(self) -> None:
        """Una celda sin semilla (``+inf``) no está dominada nunca; con la tolerancia por defecto de
        10⁻⁹ m, una diferencia de 5·10⁻¹⁰ m no domina y una de 2·10⁻⁹ m sí."""
        values = seeds_of((1, 6), {(0, 0): 50.0, (0, 5): 55.0 + 5e-10})
        bound = oracles.dijkstra(values, 1.0, 1.0, scale=1.0)
        self.assertFalse(reduction.dominated_cells(values, bound).any())
        self.assertTrue(reduction.dominated_cells(values, bound, tolerance=0.0)[0, 5])
        values = seeds_of((1, 6), {(0, 0): 50.0, (0, 5): 55.0 + 2e-9})
        bound = oracles.dijkstra(values, 1.0, 1.0, scale=1.0)
        self.assertEqual(np.flatnonzero(reduction.dominated_cells(values, bound)).tolist(), [5])


class RedundantTest(unittest.TestCase):
    """Sus 8 vecinas son semillas con ``f_n ≤ f_q + k·g``."""

    def test_the_inside_of_a_flat_block_is_redundant_and_its_ring_is_not(self) -> None:
        """A mano: un bloque de 5 × 5 semillas a 100 m en una rejilla de 7 × 7 deja redundantes las
        9 celdas de dentro (sus 8 vecinas son semillas iguales) y ninguna de las 16 del anillo
        (tienen una vecina que no es semilla); una celda que no es semilla nunca lo es."""
        values = np.full((7, 7), np.inf)
        values[1:6, 1:6] = 100.0
        found = reduction.redundant_cells(values, 0.7)
        expected = np.zeros((7, 7), dtype=bool)
        expected[2:5, 2:5] = True
        self.assertTrue(np.array_equal(found, expected))

    def test_the_border_of_the_grid_is_never_redundant(self) -> None:
        """Una celda de la orilla de la rejilla no tiene sus 8 vecinas: una rejilla entera de
        semillas planas solo retira las de dentro; con 3 × 3, solo la del centro; con 2 × 5 o 1 × 7,
        ninguna."""
        for shape, count in (((3, 3), 1), ((6, 8), 4 * 6), ((2, 5), 0), ((1, 7), 0), ((5, 1), 0)):
            with self.subTest(shape=shape):
                found = reduction.redundant_cells(np.full(shape, 100.0), 0.5)
                self.assertEqual(int(found.sum()), count)
                self.assertFalse(found[0].any() or found[-1].any())
                self.assertFalse(found[:, 0].any() or found[:, -1].any())

    def test_the_threshold_is_the_height_of_one_cell_of_slope(self) -> None:
        """A mano, con ``k = 0,5`` m por celda (``t = 0,5``, ``h = 1``): la semilla del centro de un
        bloque de 3 × 3 es redundante si ninguna vecina pasa de ``f + k`` (la de más arriba, 100,5);
        con 100,5 + 10⁻⁹ ya no; las vecinas más bajas no importan; una vecina que no es semilla
        siempre lo impide."""
        rise = 0.5
        base = seeds_of((3, 3), {(r, c): 100.0 for r in range(3) for c in range(3)})
        cases = ((100.5, True), (100.5 + 1e-9, False), (99.0, True), (-50.0, True),
                 (math.inf, False))
        for neighbour, redundant in cases:
            for cell in NEIGHBOURS:
                values = base.copy()
                values[1 + cell[0], 1 + cell[1]] = neighbour
                with self.subTest(neighbour=neighbour, cell=cell):
                    self.assertEqual(bool(reduction.redundant_cells(values, rise)[1, 1]),
                                     redundant)

    def test_a_flat_slope_of_zero_needs_the_neighbours_not_to_be_higher(self) -> None:
        """Con ``k = 0`` (pendiente 0), la semilla del centro es redundante si ninguna vecina es
        más alta que ella."""
        values = np.full((3, 3), 100.0)
        self.assertTrue(reduction.redundant_cells(values, 0.0)[1, 1])
        values[0, 0] = 100.0 + 1e-9
        self.assertFalse(reduction.redundant_cells(values, 0.0)[1, 1])

    def test_a_band_of_rows_is_the_same_as_the_whole_grid(self) -> None:
        """Calcular por bandas de filas (``start``, ``stop``) da lo mismo que la rejilla entera,
        también con bandas de una fila, la primera y la última."""
        rng = np.random.default_rng(3)
        values = zone(rng, (14, 17), "solid", 0.7)
        whole = reduction.redundant_cells(values, 0.7)
        for start, stop in ((0, 14), (0, 1), (13, 14), (3, 9), (5, 6)):
            with self.subTest(band=(start, stop)):
                part = reduction.redundant_cells(values, 0.7, start=start, stop=stop)
                self.assertTrue(np.array_equal(part, whole[start:stop]))
                dom = reduction.dominated_cells(values, values - 1.0, start=start, stop=stop)
                self.assertTrue(np.array_equal(
                    dom, reduction.dominated_cells(values, values - 1.0)[start:stop]))


class ThresholdIsExactTest(unittest.TestCase):
    """El umbral de la redundante es el límite: pasado, quitar la semilla cambia la cota."""

    def build(self, bump: float) -> tuple[np.ndarray, int]:
        """Una fila central de 3 × 24 con la semilla ``q`` (100 m) en la columna 1 rodeada de sus 8
        vecinas a ``100 + k·bump``; la celda lejana del eje (fila 1, última columna) la gobierna
        ``q`` sola. Devuelve las semillas y la columna de ``q``."""
        values = np.full((3, 24), np.inf)
        values[:, 0:3] = 100.0 + 0.5 * bump
        values[1, 1] = 100.0
        return values, 1

    def test_just_above_the_threshold_removing_the_seed_changes_the_far_cell(self) -> None:
        """Con ``k = 0,5``: a ``f_q + k·1,0`` la semilla es redundante y quitarla no cambia nada
        (empate a lo largo del eje); a ``f_q + k·1,01`` no lo es y quitarla subiría la cota de la
        celda lejana en ``0,01·k`` = 0,005 m, mucho más que 10⁻⁹ m."""
        for bump, redundant in ((1.0, True), (1.01, False)):
            values, col = self.build(bump)
            alone = values.copy()
            alone[1, col] = np.inf
            exact = brute(values, 0.5, 1.0)
            without = np.minimum(brute(alone, 0.5, 1.0), values)  # la cota de la celda retirada
            with self.subTest(bump=bump):
                self.assertEqual(bool(reduction.redundant_cells(values, 0.5)[1, col]), redundant)
                change = float(np.abs(without - exact).max())
                if redundant:
                    self.assertLessEqual(change, TOLERANCE_M)
                else:
                    self.assertGreater(change, 4e-3)


class ReductionTest(unittest.TestCase):
    """``reduce_seeds``: las dos reglas juntas, con sus cuentas."""

    def test_counts_and_kept_seeds_by_hand(self) -> None:
        """A mano, rejilla de 7 × 9 con ``k = 1``: un bloque macizo de 5 × 5 semillas a 96 m (filas
        y columnas 1 a 5; las 9 de dentro son redundantes) y una semilla suelta a 100 m en la fila
        3, columna 8, a 3 celdas del bloque: el bloque le da 96 + 3 = 99 < 100, así que es dominada.
        Quedan las 16 del anillo del bloque (26 semillas = 1 + 9 + 16)."""
        values = np.full((7, 9), np.inf)
        values[1:6, 1:6] = 96.0
        values[3, 8] = 100.0
        bound = oracles.dijkstra(values, 1.0, 1.0, scale=1.0)
        found = reduction.reduce_seeds(values, bound, 1.0)
        self.assertEqual((found.dominated, found.redundant, found.kept), (1, 9, 16))
        self.assertEqual(found.seeds, 26)
        self.assertEqual(found.dominated + found.redundant + found.kept, found.seeds)
        self.assertNotIn((3, 8), set(zip(found.rows.tolist(), found.cols.tolist(), strict=True)))
        self.assertNotIn((3, 3), set(zip(found.rows.tolist(), found.cols.tolist(), strict=True)))

    def test_the_kept_seeds_are_listed_by_row_then_column_with_their_height(self) -> None:
        """Las que quedan van por filas y luego por columnas, con la cota de la rejilla, como
        arrays nuevos de enteros y float64; una rejilla sin semillas no deja ninguna."""
        rng = np.random.default_rng(8)
        values = zone(rng, (13, 15), "mixed", 0.7)
        bound = brute(values, 1.0, 1.0)
        found = reduction.reduce_seeds(values, bound, 1.0)
        order = np.lexsort((found.cols, found.rows))
        self.assertTrue(np.array_equal(order, np.arange(found.kept)))
        self.assertTrue(np.array_equal(values[found.rows, found.cols], found.values))
        self.assertEqual(found.values.dtype, np.float64)
        self.assertEqual(found.rows.dtype.kind, "i")
        self.assertFalse(np.shares_memory(found.values, values))
        empty = reduction.reduce_seeds(np.full((4, 5), np.inf), np.full((4, 5), np.inf), 1.0)
        self.assertEqual((empty.seeds, empty.kept, empty.dominated, empty.redundant), (0, 0, 0, 0))

    def test_a_seed_both_dominated_and_redundant_counts_once_as_dominated(self) -> None:
        """Una semilla que cumple las dos reglas se cuenta como dominada: las cuentas suman las
        semillas. Un bloque plano de 3 × 3 con la central a 100 y las demás a 90 y ``k = 1``: la
        central es redundante (las vecinas no pasan de 100 + 1) y dominada (90 + 1 < 100)."""
        values = np.full((3, 3), 90.0)
        values[1, 1] = 100.0
        bound = oracles.dijkstra(values, 1.0, 1.0, scale=1.0)
        found = reduction.reduce_seeds(values, bound, 1.0)
        self.assertEqual((found.dominated, found.redundant, found.kept), (1, 0, 8))

    def test_no_input_is_modified(self) -> None:
        """Ni las semillas ni la cota se modifican (ni se marcan de solo lectura)."""
        rng = np.random.default_rng(12)
        values = zone(rng, (16, 18), "solid", 0.7)
        bound = brute(values, 0.7, 1.0)
        before = (values.copy(), bound.copy())
        reduction.reduce_seeds(values, bound, 0.7)
        self.assertTrue(np.array_equal(values, before[0]))
        self.assertTrue(np.array_equal(bound, before[1]))
        self.assertTrue(values.flags.writeable and bound.flags.writeable)

    def test_by_units_it_is_the_same_and_yields_between_bands(self) -> None:
        """``reduce_units`` cede una unidad por banda de filas y entrega lo mismo que
        ``reduce_seeds``; con bandas de una fila hay una unidad por fila; cerrar a mitad no deja
        nada."""
        rng = np.random.default_rng(13)
        values = zone(rng, (20, 22), "solid", 0.7)
        bound = brute(values, 0.7, 1.0)
        whole = reduction.reduce_seeds(values, bound, 0.7)
        units = reduction.reduce_units(values, bound, 0.7, rows_per_unit=1)
        count = 0
        while True:
            try:
                next(units)
            except StopIteration as stop:
                banded = stop.value
                break
            count += 1
        self.assertGreaterEqual(count, 20)
        for name in ("rows", "cols", "values"):
            self.assertTrue(np.array_equal(getattr(whole, name), getattr(banded, name)))
        self.assertEqual((whole.dominated, whole.redundant), (banded.dominated, banded.redundant))
        half = reduction.reduce_units(values, bound, 0.7, rows_per_unit=2)
        next(half)
        half.close()

    def test_bad_input_is_a_program_error(self) -> None:
        """Una cota de otra forma, unas semillas de otra dimensión, una pendiente negativa, NaN o
        infinita y unas bandas de menos de una fila son errores del programa (``ValueError``)."""
        values = np.full((4, 5), 100.0)
        for args in ((values, np.zeros((4, 6)), 1.0), (values[0], values[0], 1.0),
                     (values, values, -1.0), (values, values, math.nan),
                     (values, values, math.inf)):
            with self.subTest(shape=np.shape(args[1]), rise=args[2]):
                with self.assertRaises(ValueError):
                    reduction.reduce_seeds(*args)
        with self.assertRaises(ValueError):
            list(reduction.reduce_units(values, values, 1.0, rows_per_unit=0))


class ExactnessTest(unittest.TestCase):
    """Ninguna reducción cambia ninguna cota: frente a la fuerza bruta sin reducir."""

    KINDS = dfx.ZONE_KINDS

    def compare(self, rng: np.random.Generator, cases: int, tight: bool) -> dict[str, int]:
        total = {"dominated": 0, "redundant": 0, "seeds": 0, "cases": 0}
        for index in range(cases):
            shape = (int(rng.integers(5, 15)), int(rng.integers(5, 15)))
            tan = float(rng.choice([0.0, 0.1, 0.3, 0.7, 1.5, 3.0]))
            step = float(rng.choice([0.5, 1.0, 2.5]))
            kind = self.KINDS[index % len(self.KINDS)]
            values = zone(rng, shape, kind, tan * step)
            exact = brute(values, tan, step)
            bound = exact if tight else oracles.dijkstra(values, tan, step, scale=1.0)
            found = reduction.reduce_seeds(values, bound, tan * step)
            got = reduced_brute(values, found, tan, step)
            difference = float(np.abs(got - exact).max())
            if difference > TOLERANCE_M:
                self.fail(f"caso {index} ({kind}, {shape}, t={tan}, h={step}, "
                          f"{'U=T' if tight else 'chamfer'}): cota cambiada en {difference:.3g} m")
            total["dominated"] += found.dominated
            total["redundant"] += found.redundant
            total["seeds"] += found.seeds
            total["cases"] += 1
        return total

    def test_the_reduced_search_equals_brute_force_with_the_tightest_bound(self) -> None:
        """RF-013-12, plan A5: 400 casos aleatorios (semillas sueltas, de contorno, macizas y
        mezcladas; rejillas de 5 a 14 celdas de lado; pendientes de 0 a 3; pasos de 0,5 a 2,5 m),
        con la cota ceñida al máximo (``U = T``, la que más semillas domina): la búsqueda con solo
        las semillas que quedan, más la cota propia de las retiradas, es igual a la fuerza bruta de
        las semillas todas a ≤ 10⁻⁹ m, y las dos reglas han retirado de verdad."""
        total = self.compare(np.random.default_rng(20_261_102), 400, tight=True)
        self.assertEqual(total["cases"], 400)
        self.assertGreater(total["dominated"], 1_000)
        self.assertGreater(total["redundant"], 50)

    def test_the_reduced_search_equals_brute_force_with_the_chamfer_bound(self) -> None:
        """Igual con la cota que se usa de verdad, el *chamfer* sin escala (Dijkstra del oráculo
        con ``escala = 1``, que nunca queda por debajo de la euclídea): 100 casos."""
        total = self.compare(np.random.default_rng(31), 100, tight=False)
        self.assertGreater(total["dominated"], 500)
        self.assertGreater(total["redundant"], 10)

    def test_a_bound_looser_than_the_chamfer_is_also_exact(self) -> None:
        """La exactitud no depende de lo ceñida que sea la cota (solo la cantidad que se retira):
        con ``U = T + 5`` se retiran menos por dominadas que con ``U = T`` y el resultado sigue
        siendo exacto."""
        rng = np.random.default_rng(32)
        for index in range(30):
            values = zone(rng, (10, 12), self.KINDS[index % 4], 0.7)
            exact = brute(values, 1.0, 0.7)
            loose = reduction.reduce_seeds(values, exact + 5.0, 0.7)
            tight = reduction.reduce_seeds(values, exact, 0.7)
            self.assertLessEqual(loose.dominated, tight.dominated)
            difference = np.abs(reduced_brute(values, loose, 1.0, 0.7) - exact).max()
            self.assertLessEqual(float(difference), TOLERANCE_M)


if __name__ == "__main__":
    unittest.main()
