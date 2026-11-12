# SPDX-License-Identifier: GPL-3.0-or-later
"""La distancia euclídea exacta al más próximo y su valor (spec 014, T04; RF-014-11; plan 014 A7).

:func:`design.grids.nearest_value_steps` da, para cada celda de la rejilla, el cuadrado de la
distancia euclídea entre centros de celda a la celda marcada más próxima (en celdas², exacto, y en
m² con el lado de la celda) y el valor de esa celda; si hay varias igual de cerca, el **menor**
valor (RF-014-11: «empate: la cota más baja»). Se compara con la **fuerza bruta** (cada semilla
contra cada celda) en rejillas de 200 × 200 con semillas aleatorias, con bandas de 256 filas y con
bandas de pocas filas (para que la pasada por columnas cruce de una banda a otra), y con **empates
construidos**: los cuatro vecinos a la misma distancia, las ternas pitagóricas (3, 4, 5: una semilla
en la misma columna y otra en otra columna a la misma distancia), una retícula regular de semillas
(muchas celdas a la misma distancia de dos o cuatro) y valores de un conjunto pequeño.
"""

from __future__ import annotations

import math
import unittest
from typing import Any
from unittest import mock

import numpy as np

from tests.support.package import import_geoblender

grids = import_geoblender("design.grids")


def brute_nearest(mask: np.ndarray, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """El oráculo: cada semilla contra cada celda; a igual ``d²``, el menor valor."""
    rows, cols = mask.shape
    grid_r, grid_c = np.indices((rows, cols))
    best = np.full((rows, cols), np.iinfo(np.int64).max, dtype=np.int64)
    value = np.full((rows, cols), np.nan)
    for row, col in zip(*np.nonzero(mask), strict=True):
        d2 = (grid_r - row) ** 2 + (grid_c - col) ** 2
        seed = values[row, col]
        better = (d2 < best) | ((d2 == best) & (seed < value))
        best[better] = d2[better]
        value[better] = seed
    return best, value


def finish(mask: np.ndarray, values: np.ndarray, cell: float = 1.0, **kwargs: Any
           ) -> tuple[list[Any], Any]:
    """Los pasos de :func:`nearest_value_steps` y su resultado (el del último)."""
    found = list(grids.nearest_value_steps(mask, values, cell, **kwargs))
    return found, found[-1].result


class NearestValueTest(unittest.TestCase):
    """RF-014-11 (plan 014 A7): la distancia exacta con el valor del más próximo."""

    def assert_same_as_brute(self, mask: np.ndarray, values: np.ndarray) -> None:
        _steps, found = finish(mask, values)
        expected_d2, expected_value = brute_nearest(mask, values)
        self.assertEqual(found.cells2.dtype, np.int64)
        self.assertEqual(found.value.dtype, np.float64)
        np.testing.assert_array_equal(found.cells2, expected_d2)
        np.testing.assert_array_equal(found.value, expected_value)

    def test_random_seeds_on_200_by_200_equal_the_brute_force(self) -> None:
        rng = np.random.default_rng(1411)
        for case in range(8):
            mask = np.zeros((200, 200), dtype=bool)
            count = int(rng.integers(1, 120))
            mask.flat[rng.choice(mask.size, count, replace=False)] = True
            if case % 2:  # valores de un conjunto pequeño: muchos empates con valores distintos
                values = rng.integers(0, 4, mask.shape).astype(np.float64) * 2.5 + 300.0
            else:
                values = rng.uniform(150.0, 450.0, mask.shape)
            band = grids.BAND_ROWS if case < 4 else int(rng.integers(1, 40))
            with self.subTest(case=case, seeds=count, band=band), \
                    mock.patch.object(grids, "BAND_ROWS", band):
                self.assert_same_as_brute(mask, values)

    def test_random_shapes_and_densities_equal_the_brute_force(self) -> None:
        rng = np.random.default_rng(14111)
        for case in range(60):
            shape = (int(rng.integers(1, 40)), int(rng.integers(1, 40)))
            mask = rng.random(shape) < rng.uniform(0.01, 0.6)
            if not mask.any():
                mask[int(rng.integers(shape[0])), int(rng.integers(shape[1]))] = True
            values = rng.integers(-3, 3, shape).astype(np.float64)
            band = int(rng.integers(1, 6)) if case % 2 else grids.BAND_ROWS
            with self.subTest(case=case, shape=shape, band=band), \
                    mock.patch.object(grids, "BAND_ROWS", band):
                self.assert_same_as_brute(mask, values)

    def test_constructed_ties_take_the_lowest_value(self) -> None:
        mask = np.zeros((31, 33), dtype=bool)
        values = np.zeros(mask.shape)
        center = (15, 16)
        # d² = 25 desde el centro: (±5, 0), (0, ±5), (3, 4), (−4, 3); el menor valor, 211.
        for (d_row, d_col), value in {(5, 0): 240.0, (-5, 0): 230.0, (0, 5): 225.0,
                                      (0, -5): 228.0, (3, 4): 211.0, (-4, 3): 219.0}.items():
            mask[center[0] + d_row, center[1] + d_col] = True
            values[center[0] + d_row, center[1] + d_col] = value
        _steps, found = finish(mask, values)
        self.assertEqual(int(found.cells2[center]), 25)
        self.assertEqual(float(found.value[center]), 211.0)
        self.assert_same_as_brute(mask, values)
        # La misma columna arriba y abajo (la pasada por columnas): el menor de los dos.
        column = np.zeros((11, 3), dtype=bool)
        column[[0, 10], 1] = True
        column_values = np.zeros(column.shape)
        column_values[0, 1], column_values[10, 1] = 5.0, 4.0
        _steps, found = finish(column, column_values)
        self.assertEqual(float(found.value[5, 1]), 4.0)
        self.assertEqual(float(found.value[4, 1]), 5.0)
        self.assert_same_as_brute(column, column_values)

    def test_a_lattice_of_seeds_has_many_ties(self) -> None:
        mask = np.zeros((200, 200), dtype=bool)
        mask[3::8, 5::8] = True
        rng = np.random.default_rng(14112)
        values = rng.integers(0, 3, mask.shape).astype(np.float64) * 10.0
        expected_d2, _expected = brute_nearest(mask, values)
        seeds = np.argwhere(mask)
        ties = 0
        for row, col in ((7, 9), (7, 5), (3, 9)):  # a igual distancia de 4, 2 y 2 semillas
            d2 = ((seeds - (row, col)) ** 2).sum(axis=1)
            ties += int((d2 == expected_d2[row, col]).sum())
        self.assertEqual(ties, 8)
        for band in (grids.BAND_ROWS, 7):
            with self.subTest(band=band), mock.patch.object(grids, "BAND_ROWS", band):
                self.assert_same_as_brute(mask, values)

    def test_the_seed_itself_is_at_zero_and_metres_use_the_cell(self) -> None:
        mask = np.zeros((6, 7), dtype=bool)
        mask[1, 2] = True
        mask[4, 6] = True
        values = np.full(mask.shape, np.nan)  # fuera de las semillas no se lee
        values[1, 2], values[4, 6] = 412.5, 398.0
        _steps, found = finish(mask, values, 2.5)
        self.assertEqual(int(found.cells2[1, 2]), 0)
        self.assertEqual(float(found.value[1, 2]), 412.5)
        self.assertEqual(int(found.cells2[5, 0]), 4 * 4 + 2 * 2)
        self.assertEqual(found.cell, 2.5)
        self.assertEqual(float(found.d2[5, 0]), 20 * 2.5 * 2.5)
        self.assertEqual(float(math.sqrt(found.d2[4, 3])), 3 * 2.5)

    def test_empty_mask_has_no_nearest(self) -> None:
        mask = np.zeros((4, 5), dtype=bool)
        _steps, found = finish(mask, np.zeros(mask.shape))
        self.assertTrue((found.cells2 == -1).all())
        self.assertTrue(np.isnan(found.value).all())
        self.assertTrue(np.isinf(found.d2).all())
        _steps, found = finish(np.zeros((0, 3), dtype=bool), np.zeros((0, 3)))
        self.assertEqual(found.cells2.shape, (0, 3))

    def test_steps_end_with_the_result_and_the_inputs_are_not_modified(self) -> None:
        rng = np.random.default_rng(14113)
        mask = rng.random((70, 90)) < 0.02
        values = rng.uniform(0.0, 9.0, mask.shape)
        before = (mask.copy(), values.copy())
        found, result = finish(mask, values)
        np.testing.assert_array_equal(mask, before[0])
        np.testing.assert_array_equal(values, before[1])
        self.assertIsInstance(result, grids.Nearest)
        self.assertEqual({step.phase for step in found}, {"nearest"})
        self.assertTrue(all(step.result is None for step in found[:-1]))
        self.assertEqual(found[-1].done, found[-1].total)

    def test_closing_halfway_is_clean(self) -> None:
        mask = np.zeros((300, 300), dtype=bool)
        mask[::37, ::41] = True
        steps = grids.nearest_value_steps(mask, np.ones(mask.shape), 1.0, budget_s=0.0)
        next(steps)
        steps.close()

    def test_program_errors(self) -> None:
        mask = np.ones((3, 3), dtype=bool)
        values = np.ones((3, 3))
        with self.assertRaises(ValueError):
            grids.nearest_value_steps(np.ones(3, dtype=bool), np.ones(3), 1.0)
        with self.assertRaises(ValueError):
            grids.nearest_value_steps(mask, np.ones((3, 4)), 1.0)
        with self.assertRaises(ValueError):
            grids.nearest_value_steps(mask, values, 0.0)
        with self.assertRaises(ValueError):
            grids.nearest_value_steps(mask, values, math.inf)
        values[1, 1] = math.nan  # una semilla sin valor
        with self.assertRaises(ValueError):
            grids.nearest_value_steps(mask, values, 1.0)


if __name__ == "__main__":
    unittest.main()
