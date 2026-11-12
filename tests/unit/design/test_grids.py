# SPDX-License-Identifier: GPL-3.0-or-later
"""El anillo de Chebyshev y las componentes 4-conexas de una máscara (spec 014, T03; RF-014-02,
RF-014-03, RF-014-17, RF-014-21; plan 014 A2, A3 y §8).

``design.grids`` da dos utilidades de rejilla en numpy puro:

- :func:`dilate_square`: las celdas a distancia de Chebyshev ≤ ``k`` de una celda marcada (la
  dilatación cuadrada de lado ``2k + 1``; el anillo de coronación es ``dilate_square(R, k) ∧ ¬R``).
  Se compara con la fuerza bruta (cada celda marcada pinta su cuadrado).
- :func:`label_components_steps`: las componentes 4-conexas, por tramos de fila y unión-búsqueda,
  por bandas de filas y por pasos. Se compara con una **inundación de referencia** (una cola por
  celda, en Python) en 200 rejillas aleatorias, con bandas de 256 filas y con bandas de pocas filas
  (para que casi todas las uniones crucen de una banda a otra), y en formas patológicas: una
  espiral (un solo camino muy largo), peines (cientos de tramos que se unen tarde, por arriba y por
  abajo), tableros de ajedrez (ningún tramo toca a otro), una serpiente de 600 filas que cruza las
  bandas, diagonales (que no son 4-conexas), la rejilla llena y la vacía. Las etiquetas van de 1 al
  número de componentes en el orden de su primera celda (fila a fila) y 0 fuera; ``sizes[i − 1]``
  son las celdas de la etiqueta ``i``.
"""

from __future__ import annotations

import unittest
from collections import deque
from typing import Any
from unittest import mock

import numpy as np

from tests.support.package import import_geoblender

grids = import_geoblender("design.grids")


def brute_dilate(mask: np.ndarray, k: int) -> np.ndarray:
    """Cada celda marcada pinta su cuadrado de lado ``2k + 1`` (oráculo)."""
    rows, cols = mask.shape
    found = np.zeros_like(mask, dtype=bool)
    for row, col in zip(*np.nonzero(mask), strict=True):
        found[max(0, row - k):min(rows, row + k + 1), max(0, col - k):min(cols, col + k + 1)] = True
    return found


def flood_labels(mask: np.ndarray) -> tuple[np.ndarray, list[int]]:
    """Las componentes 4-conexas por inundación (oráculo): etiqueta 1, 2… en el orden de la primera
    celda de cada una al recorrer la rejilla fila a fila, y sus celdas."""
    rows, cols = mask.shape
    labels = np.zeros(mask.shape, dtype=np.int64)
    sizes: list[int] = []
    for row in range(rows):
        for col in range(cols):
            if not mask[row, col] or labels[row, col]:
                continue
            label = len(sizes) + 1
            labels[row, col] = label
            queue = deque([(row, col)])
            count = 0
            while queue:
                r, c = queue.popleft()
                count += 1
                for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                    if 0 <= nr < rows and 0 <= nc < cols and mask[nr, nc] and not labels[nr, nc]:
                        labels[nr, nc] = label
                        queue.append((nr, nc))
            sizes.append(count)
    return labels, sizes


def finish(mask: np.ndarray) -> tuple[list[Any], Any]:
    """Los pasos de :func:`label_components_steps` y su resultado (el del último)."""
    found = list(grids.label_components_steps(mask))
    return found, found[-1].result


def spiral(size: int) -> np.ndarray:
    """Un camino de una celda de ancho que da vueltas hacia dentro, separado de sí mismo por una
    celda: una tortuga avanza mientras la celda siguiente y la de después están libres y gira a la
    derecha si no; para cuando no puede avanzar ni girando."""
    found = np.zeros((size, size), dtype=bool)
    headings = ((0, 1), (1, 0), (0, -1), (-1, 0))

    def free(row: int, col: int) -> bool:
        return not (0 <= row < size and 0 <= col < size) or not found[row, col]

    def inside(row: int, col: int) -> bool:
        return 0 <= row < size and 0 <= col < size

    row, col, heading = 0, 0, 0
    found[row, col] = True
    turns = 0
    while turns < 2:
        d_row, d_col = headings[heading]
        ahead = (row + d_row, col + d_col)
        beyond = (row + 2 * d_row, col + 2 * d_col)
        if inside(*ahead) and not found[ahead] and free(*beyond):
            row, col = ahead
            found[row, col] = True
            turns = 0
        else:
            heading = (heading + 1) % 4
            turns += 1
    return found


def comb(rows: int, cols: int, *, spine_at_top: bool) -> np.ndarray:
    """Dientes de una celda en las columnas pares unidos por un lomo arriba o abajo."""
    found = np.zeros((rows, cols), dtype=bool)
    found[:, ::2] = True
    found[0 if spine_at_top else rows - 1, :] = True
    return found


def snake(rows: int, cols: int) -> np.ndarray:
    """Una serpiente que baja por filas pares de lado a lado, unidas por un extremo alterno."""
    found = np.zeros((rows, cols), dtype=bool)
    found[::2, :] = True
    for row in range(1, rows, 2):
        found[row, cols - 1 if (row // 2) % 2 == 0 else 0] = True
    return found


class DilateSquareTest(unittest.TestCase):
    """RF-014-02 (plan 014 A2): la dilatación de Chebyshev ≤ ``k``."""

    def test_random_masks_equal_the_brute_force(self) -> None:
        rng = np.random.default_rng(1402)
        for case in range(120):
            shape = (int(rng.integers(1, 30)), int(rng.integers(1, 30)))
            mask = rng.random(shape) < rng.uniform(0.0, 0.2)
            k = int(rng.integers(0, 8))
            with self.subTest(case=case, shape=shape, k=k):
                found = grids.dilate_square(mask, k)
                self.assertEqual(found.dtype, np.bool_)
                np.testing.assert_array_equal(found, brute_dilate(mask, k))

    def test_one_cell_paints_its_square_and_clips_at_the_edge(self) -> None:
        mask = np.zeros((9, 9), dtype=bool)
        mask[4, 4] = True
        found = grids.dilate_square(mask, 3)
        self.assertEqual(int(found.sum()), 49)
        self.assertTrue(found[1:8, 1:8].all())
        corner = np.zeros((9, 9), dtype=bool)
        corner[0, 8] = True
        self.assertEqual(int(grids.dilate_square(corner, 3).sum()), 16)
        self.assertTrue(grids.dilate_square(corner, 50).all())

    def test_the_crown_ring_is_k_cells_wide(self) -> None:
        area = np.zeros((20, 20), dtype=bool)
        area[6:14, 5:15] = True
        ring = grids.dilate_square(area, 3) & ~area
        self.assertEqual(int(ring.sum()), 14 * 16 - 8 * 10)

    def test_zero_is_a_copy_and_the_input_is_not_modified(self) -> None:
        mask = np.zeros((5, 6), dtype=bool)
        mask[2, 3] = True
        before = mask.copy()
        found = grids.dilate_square(mask, 0)
        np.testing.assert_array_equal(found, mask)
        self.assertIsNot(found, mask)
        grids.dilate_square(mask, 2)
        np.testing.assert_array_equal(mask, before)

    def test_program_errors(self) -> None:
        with self.assertRaises(ValueError):
            grids.dilate_square(np.zeros((3, 3), dtype=bool), -1)
        with self.assertRaises(ValueError):
            grids.dilate_square(np.zeros(3, dtype=bool), 1)


class LabelComponentsTest(unittest.TestCase):
    """RF-014-03, RF-014-17, RF-014-21 (plan 014 A3, §8): las componentes 4-conexas."""

    def assert_same_as_flood(self, mask: np.ndarray) -> None:
        _steps, labels = finish(mask)
        expected, sizes = flood_labels(mask)
        self.assertEqual(labels.grid.dtype, np.int32)
        self.assertEqual(labels.grid.shape, mask.shape)
        np.testing.assert_array_equal(labels.grid, expected)
        self.assertEqual(labels.sizes.tolist(), sizes)
        self.assertEqual(labels.count, len(sizes))

    def test_random_grids_equal_the_flood_fill(self) -> None:
        rng = np.random.default_rng(14021)
        for case in range(200):
            shape = (int(rng.integers(1, 45)), int(rng.integers(1, 45)))
            mask = rng.random(shape) < rng.uniform(0.05, 0.95)
            band = int(rng.integers(1, 6)) if case % 2 else grids.BAND_ROWS
            with self.subTest(case=case, shape=shape, band=band), \
                    mock.patch.object(grids, "BAND_ROWS", band):
                self.assert_same_as_flood(mask)

    def test_pathological_shapes(self) -> None:
        board = (np.add.outer(np.arange(40), np.arange(37)) % 2).astype(bool)
        blocks = (np.add.outer(np.arange(40) // 2, np.arange(38) // 2) % 2).astype(bool)
        diagonal = np.eye(30, dtype=bool) | np.eye(30, k=2, dtype=bool)
        shapes = {
            "espiral": spiral(61),
            "espiral impar": spiral(40),
            "peine con lomo arriba": comb(50, 301, spine_at_top=True),
            "peine con lomo abajo": comb(50, 301, spine_at_top=False),
            "tablero": board,
            "tablero de 2 × 2": blocks,
            "diagonales": diagonal,
            "llena": np.ones((17, 23), dtype=bool),
            "vacía": np.zeros((17, 23), dtype=bool),
            "una fila": np.array([[True, True, False, True, False, False, True]]),
            "una columna": np.array([[True], [True], [False], [True]]),
        }
        for name, mask in shapes.items():
            for band in (grids.BAND_ROWS, 1, 3):
                with self.subTest(shape=name, band=band), \
                        mock.patch.object(grids, "BAND_ROWS", band):
                    self.assert_same_as_flood(mask)

    def test_a_spiral_is_one_component(self) -> None:
        mask = spiral(61)
        _steps, labels = finish(mask)
        self.assertEqual(labels.count, 1)
        self.assertEqual(int(labels.sizes[0]), int(mask.sum()))

    def test_a_snake_across_bands_of_256_rows_is_one_component(self) -> None:
        mask = snake(601, 9)
        self.assertGreater(mask.shape[0], 2 * grids.BAND_ROWS)
        self.assert_same_as_flood(mask)
        _steps, labels = finish(mask)
        self.assertEqual(labels.count, 1)

    def test_a_checkerboard_has_one_component_per_cell(self) -> None:
        mask = (np.add.outer(np.arange(300), np.arange(41)) % 2 == 0)
        _steps, labels = finish(mask)
        self.assertEqual(labels.count, int(mask.sum()))
        self.assertTrue((labels.sizes == 1).all())

    def test_empty_mask_has_no_components(self) -> None:
        _steps, labels = finish(np.zeros((0, 4), dtype=bool))
        self.assertEqual(labels.count, 0)
        self.assertEqual(labels.grid.shape, (0, 4))
        _steps, labels = finish(np.zeros((5, 4), dtype=bool))
        self.assertEqual(labels.count, 0)
        self.assertEqual(labels.sizes.tolist(), [])
        self.assertFalse(labels.grid.any())

    def test_steps_end_with_the_labels_and_the_input_is_not_modified(self) -> None:
        mask = comb(20, 31, spine_at_top=False)
        before = mask.copy()
        found, labels = finish(mask)
        np.testing.assert_array_equal(mask, before)
        self.assertIsInstance(labels, grids.Labels)
        self.assertEqual({step.phase for step in found}, {"components"})
        self.assertTrue(all(step.result is None for step in found[:-1]))
        self.assertEqual(found[-1].done, found[-1].total)

    def test_closing_halfway_is_clean(self) -> None:
        steps = grids.label_components_steps(snake(601, 9), budget_s=0.0)
        next(steps)
        steps.close()

    def test_program_errors(self) -> None:
        with self.assertRaises(ValueError):
            next(grids.label_components_steps(np.zeros(4, dtype=bool)))


if __name__ == "__main__":
    unittest.main()
