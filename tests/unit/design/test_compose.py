# SPDX-License-Identifier: GPL-3.0-or-later
"""La superficie de diseño: composición con las máscaras (spec 013, T12; HU-013-2; RF-013-29;
CE-013-06; plan 013 A10, D-9).

``design.compose`` mezcla el escalonado con la superficie de partida **solo donde las máscaras de
la 012 lo admiten** y deja en todas las demás celdas exactamente la de partida, sin suavizar el
borde de lo prohibido (las transiciones son de R-36; D-9):

- **Corte**: el mínimo de las dos solo en las celdas de corte admitido (``cut_allowed``).
- **Relleno**: el máximo solo en las de relleno admitido o de la franja de solo relleno
  (``fill_allowed`` o ``fill_strip``).
- **Lo demás**: la de partida, bit a bit (también donde no hay dato), y lo que no tiene cota en el
  escalonado (``NaN`` o infinito: sin envolvente o más allá del alcance) tampoco mueve nada.
- **Acotado**: el dominio de trabajo acotado a unos sectores o una capa solo puede restar celdas.

Se prueba a mano, contra un cálculo celda a celda en Python con rejillas aleatorias y con las
máscaras reales de V01 (el rechazo por recinto con las funciones de la 012 es de
``tests/referencia/des/test_ref_design_masks.py``).
"""

from __future__ import annotations

import math
import unittest
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import design_fixtures as dfx
from tests.support.package import import_geoblender

compose = import_geoblender("design.compose")
combine = import_geoblender("gis.masks.combine")
model = import_geoblender("design.model")

CUT = model.BenchSense.CUT
FILL = model.BenchSense.FILL


def brute_force(start: np.ndarray, stepped: np.ndarray, allowed: np.ndarray, sense: Any
                ) -> np.ndarray:
    """La composición celda a celda con floats de Python (A10)."""
    pick = min if sense == CUT else max
    out = np.empty_like(start)
    for row in range(start.shape[0]):
        for col in range(start.shape[1]):
            base = float(start[row, col])
            other = float(stepped[row, col])
            if allowed[row, col] and math.isfinite(base) and math.isfinite(other):
                out[row, col] = pick(base, other)
            else:
                out[row, col] = base
    return out


class ComposeByHandTest(unittest.TestCase):
    """RF-013-29: el mínimo en corte y el máximo en relleno, solo donde se admite."""

    def setUp(self) -> None:
        self.start = np.array([[10.0, 10.0, 10.0, 10.0],
                               [10.0, 10.0, 10.0, 10.0],
                               [10.0, 10.0, 10.0, 10.0]])
        self.stepped = np.array([[8.0, 12.0, 9.5, 10.0],
                                 [8.0, 12.0, 9.5, 10.0],
                                 [8.0, 12.0, 9.5, 10.0]])
        self.allowed = np.array([[True, True, True, True],
                                 [True, True, False, False],
                                 [False, False, False, False]])

    def test_cut_is_the_minimum_where_allowed(self) -> None:
        """RF-013-29: en corte, ``mín(escalonado, partida)`` en las celdas admitidas; el
        escalonado por encima de la partida no sube nada (un corte nunca rellena) y en las celdas
        no admitidas queda la de partida."""
        found = compose.compose(self.start, self.stepped, self.allowed, CUT)
        expected = np.array([[8.0, 10.0, 9.5, 10.0],
                             [8.0, 10.0, 10.0, 10.0],
                             [10.0, 10.0, 10.0, 10.0]])
        np.testing.assert_array_equal(found, expected)

    def test_fill_is_the_maximum_where_allowed(self) -> None:
        """RF-013-29: en relleno, ``máx(escalonado, partida)`` en las admitidas (un relleno nunca
        excava) y la de partida en las demás."""
        found = compose.compose(self.start, self.stepped, self.allowed, FILL)
        expected = np.array([[10.0, 12.0, 10.0, 10.0],
                             [10.0, 12.0, 10.0, 10.0],
                             [10.0, 10.0, 10.0, 10.0]])
        np.testing.assert_array_equal(found, expected)

    def test_the_sense_can_be_a_string(self) -> None:
        """El sentido llega como texto del enumerado (``cut``, ``fill``)."""
        cut = compose.compose(self.start, self.stepped, self.allowed, "cut")
        fill = compose.compose(self.start, self.stepped, self.allowed, "fill")
        np.testing.assert_array_equal(cut, compose.compose(self.start, self.stepped,
                                                           self.allowed, CUT))
        np.testing.assert_array_equal(fill, compose.compose(self.start, self.stepped,
                                                            self.allowed, FILL))

    def test_held_cells_are_the_start_bit_for_bit(self) -> None:
        """RF-013-29, D-9: donde no se admite, exactamente la de partida (sin suavizar el borde de
        lo prohibido: la vecina que cambia no arrastra a la prohibida)."""
        start = np.array([[0.1, 0.2, 0.30000000000000004], [1e-300, -0.0, 7.0]])
        stepped = start - 1.0
        allowed = np.array([[True, False, True], [False, True, False]])
        found = compose.compose(start, stepped, allowed, CUT)
        held = ~allowed
        self.assertEqual(found[held].tobytes(), start[held].tobytes())
        self.assertTrue(np.all(found[allowed] < start[allowed]))

    def test_no_data_stays_no_data_and_a_missing_step_moves_nothing(self) -> None:
        """RF-013-29: una celda sin dato en la partida sigue sin dato; un escalonado sin cota
        (``NaN``, ±inf: sin envolvente o más allá del alcance) deja la de partida y no la borra."""
        start = np.array([[5.0, np.nan, 5.0, 5.0, np.inf]])
        stepped = np.array([[np.nan, 3.0, np.inf, -np.inf, 3.0]])
        allowed = np.ones(start.shape, dtype=bool)
        for sense in (CUT, FILL):
            with self.subTest(sense=sense), np.errstate(all="raise"):
                found = compose.compose(start, stepped, allowed, sense)
                np.testing.assert_array_equal(found, start)

    def test_result_is_new_float64_and_inputs_are_not_touched(self) -> None:
        """Una entrada nunca se modifica: el resultado es un array nuevo de float64, aunque nada
        cambie, y los float32 se componen en float64."""
        start32 = self.start.astype(np.float32)
        stepped32 = self.stepped.astype(np.float32)
        before = (start32.copy(), stepped32.copy(), self.allowed.copy())
        found = compose.compose(start32, stepped32, self.allowed, CUT)
        self.assertEqual(found.dtype, np.float64)
        self.assertFalse(np.shares_memory(found, start32))
        np.testing.assert_array_equal(start32, before[0])
        np.testing.assert_array_equal(stepped32, before[1])
        np.testing.assert_array_equal(self.allowed, before[2])
        nothing = compose.compose(self.start, self.stepped, np.zeros(self.start.shape, bool), CUT)
        self.assertFalse(np.shares_memory(nothing, self.start))
        np.testing.assert_array_equal(nothing, self.start)

    def test_composing_by_bands_is_the_same_bit_for_bit(self) -> None:
        """La composición es puntual: partir la rejilla en bandas de filas (los pasos de T14) no
        cambia ni un bit."""
        rng = np.random.default_rng(13)
        start = 100.0 + rng.normal(0.0, 5.0, (37, 23))
        stepped = 100.0 + rng.normal(0.0, 8.0, (37, 23))
        allowed = rng.random((37, 23)) < 0.6
        whole = compose.compose(start, stepped, allowed, FILL)
        parts = [compose.compose(start[a:b], stepped[a:b], allowed[a:b], FILL)
                 for a, b in ((0, 9), (9, 10), (10, 30), (30, 37))]
        self.assertEqual(np.concatenate(parts).tobytes(), whole.tobytes())

    def test_wrong_inputs_are_program_errors(self) -> None:
        """Una forma que no casa, una máscara que no es booleana o un sentido desconocido son
        errores del programa (``ValueError``)."""
        with self.assertRaisesRegex(ValueError, "misma forma"):
            compose.compose(self.start, self.stepped[:2], self.allowed, CUT)
        with self.assertRaisesRegex(ValueError, "misma forma"):
            compose.compose(self.start, self.stepped, self.allowed[:2], CUT)
        with self.assertRaisesRegex(ValueError, "booleana"):
            compose.compose(self.start, self.stepped, self.allowed.astype(np.int8), CUT)
        with self.assertRaises(ValueError):
            compose.compose(self.start, self.stepped, self.allowed, "dig")
        with self.assertRaises(ValueError):
            compose.compose(self.start[0], self.stepped[0], self.allowed[0], CUT)


class ComposeBruteForceTest(unittest.TestCase):
    """RF-013-29: 40 rejillas aleatorias (con huecos e infinitos) frente al cálculo celda a celda."""

    def test_random_grids_match_the_cell_by_cell_calculation(self) -> None:
        rng = np.random.default_rng(2026)
        for case in range(40):
            shape = (int(rng.integers(1, 14)), int(rng.integers(1, 14)))
            start = 100.0 + rng.normal(0.0, 6.0, shape)
            stepped = 100.0 + rng.normal(0.0, 6.0, shape)
            start[rng.random(shape) < 0.1] = np.nan
            stepped[rng.random(shape) < 0.1] = np.nan
            stepped[rng.random(shape) < 0.05] = np.inf
            stepped[rng.random(shape) < 0.05] = -np.inf
            allowed = rng.random(shape) < 0.55
            for sense in (CUT, FILL):
                with self.subTest(case=case, sense=sense.value):
                    found = compose.compose(start, stepped, allowed, sense)
                    expected = brute_force(start, stepped, allowed, sense)
                    np.testing.assert_array_equal(found, expected)


class MasksTest(dfx.DesignProjectCase):
    """RF-013-29, RF-012-13: lo que admiten las máscaras reales de V01 (cinco restricciones, el
    límite legal, el perímetro y su franja de solo relleno)."""

    def test_cut_is_the_cut_allowed_mask(self) -> None:
        """El corte admitido es el ``cut_allowed`` de las máscaras, tal cual (una máscara nueva)."""
        masks = self.masks()
        found = compose.admitted(masks, CUT)
        np.testing.assert_array_equal(found, masks.cut_allowed())
        self.assertFalse(np.shares_memory(found, masks.classes))
        self.assertEqual(found.dtype, np.bool_)
        self.assertEqual(found.shape, masks.grid.shape)
        self.assertGreater(int(found.sum()), 0)

    def test_fill_is_fill_allowed_or_the_fill_only_strip(self) -> None:
        """El relleno admitido es ``fill_allowed`` o la franja de solo relleno (RF-012-13): más
        celdas que el corte, la franja incluida."""
        masks = self.masks()
        found = compose.admitted(masks, FILL)
        np.testing.assert_array_equal(found, masks.fill_allowed() | masks.fill_strip())
        self.assertTrue(np.all(found[masks.fill_strip()]))
        self.assertFalse(np.any(masks.cut_allowed() & masks.fill_strip()))
        self.assertGreater(int(found.sum()), int(masks.fill_allowed().sum()))

    def test_what_is_forbidden_is_not_admitted(self) -> None:
        """Las zonas prohibidas quedan fuera: la torre (intocable) en los dos sentidos, la cuneta
        («sin corte») solo en corte y la balsa («sin relleno») solo en relleno; fuera del
        perímetro, nada."""
        masks = self.masks()
        cut = compose.admitted(masks, CUT)
        fill = compose.admitted(masks, FILL)
        tower, ditch, pond = (masks.zone(code).mask(masks.grid.shape)
                              for code in ("torre", "cuneta", "balsa"))
        self.assertFalse(np.any(cut & tower) or np.any(fill & tower))
        self.assertFalse(np.any(cut & ditch))
        self.assertTrue(np.any(fill & ditch))
        self.assertFalse(np.any(fill & pond))
        self.assertTrue(np.any(cut & pond))
        outside = (masks.classes & int(combine.ClassBit.PERIMETER)) == 0
        self.assertFalse(np.any(cut & outside) or np.any(fill & outside))

    def test_the_work_domain_can_only_remove_cells(self) -> None:
        """El dominio de trabajo acotado (sectores o capa) solo resta celdas: lo admitido dentro
        de él es lo admitido por las máscaras en esas celdas; sin acotar, es lo mismo que
        :func:`admitted`."""
        masks = self.masks()
        bound = np.zeros(masks.grid.shape, dtype=bool)
        bound[:, :80] = True
        for sense in (CUT, FILL):
            with self.subTest(sense=sense.value):
                free = compose.allowed_cells(masks, sense)
                np.testing.assert_array_equal(free, compose.admitted(masks, sense))
                bounded = compose.allowed_cells(masks, sense, bound)
                np.testing.assert_array_equal(bounded, free & bound)
                self.assertLess(int(bounded.sum()), int(free.sum()))
                self.assertGreater(int(bounded.sum()), 0)

    def test_a_domain_of_another_shape_is_a_program_error(self) -> None:
        masks = self.masks()
        with self.assertRaises(ValueError):
            compose.allowed_cells(masks, CUT, np.ones((3, 3), dtype=bool))
        with self.assertRaises(ValueError):
            compose.allowed_cells(masks, CUT, np.ones(masks.grid.shape, dtype=np.int8))

    def test_the_composition_changes_nothing_outside_what_is_admitted(self) -> None:
        """Con las máscaras reales: un escalonado que cruza todo el sitio solo cambia las celdas
        admitidas; el resto es la partida bit a bit."""
        masks = self.masks()
        start = cfx.site_start().values
        for sense, shift in ((CUT, -6.0), (FILL, 6.0)):
            with self.subTest(sense=sense.value):
                allowed = compose.allowed_cells(masks, sense)
                found = compose.compose(start, start + shift, allowed, sense)
                self.assertEqual(found[~allowed].tobytes(), start[~allowed].tobytes())
                np.testing.assert_array_equal(found[allowed], start[allowed] + shift)
                self.assertEqual(int((found != start).sum()), int(allowed.sum()))


if __name__ == "__main__":
    unittest.main()
