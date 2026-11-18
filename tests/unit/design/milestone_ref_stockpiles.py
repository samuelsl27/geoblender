# SPDX-License-Identifier: GPL-3.0-or-later
"""El hito H1 de la detección de acopios a escala, con los oráculos de fuerza bruta (spec 016, T10; P-13; RNF-016-06;
RF-016-02, RF-016-06, RF-016-07, RF-016-08; CE-016-01 y CE-016-02).

``tests/referencia/des/test_ref_stockpiles.py`` (el «verde») verifica A1 a A5 contra el cálculo a mano de
``grow_by_hand``, que mide las distancias de la corona y de la marca ampliada sobre **el borde** de cada máscara para
que cueste ≈ 0,1 s. Aquí, en el paso «hito» (más de 1 s por prueba), se comprueba que ese cálculo a mano da lo mismo
que los oráculos de fuerza bruta de la 016 **sobre las huellas reales de los casos**, a su escala:

- la corona (``oracles.hand_crown``: cada celda contra cada celda de la huella) de las huellas finales del cono de
  CE-016-02 (3° y 8°), de los cinco acopios y de tres candidatos del levantamiento (los dos que se tocan, ya repartidos),
  y la marca ampliada (``oracles.hand_dilate``) de las marcas de los dos acopios aislados;
- el ``hand_grow`` de ``test_stockpile_footprint`` (A2 y A3 enteros con esas distancias por fuerza bruta) sobre la ventana
  entera de 120 × 120 celdas del cono de 3° de CE-016-02 (≈ 13 s por vuelta, ``docs/trampas.md`` §2): el mismo plano en
  cada celda, la misma huella, el mismo volumen, las mismas vueltas y las mismas notas que el cálculo a mano y que el
  código.
"""

from __future__ import annotations

import math
import unittest

import numpy as np

from tests.referencia.des.test_ref_stockpiles import (D3, assert_notes, assert_plane_and_volume, box_mask, cone_runs,
                                                      hand_notes, near, survey_run)
from tests.support import design_oracles as oracles
from tests.support import stockpile_data as sdata
from tests.unit.design.test_stockpile_footprint import expected_codes, hand_grow

REACH = 5
"""Las celdas que se añaden a la caja de una huella para su corona (la exterior son 3 m)."""


def tight(mask: np.ndarray, reach: int = REACH) -> tuple[slice, slice]:
    """La caja de ``mask`` más ``reach`` celdas por lado, recortada a la máscara."""
    rows, cols = np.nonzero(mask)
    return (slice(max(int(rows.min()) - reach, 0), min(int(rows.max()) + reach + 1, mask.shape[0])),
            slice(max(int(cols.min()) - reach, 0), min(int(cols.max()) + reach + 1, mask.shape[1])))


class BruteForceNearTest(unittest.TestCase):
    """La corona y la marca ampliada de ``near`` son las de fuerza bruta de ``design_oracles`` sobre las huellas reales."""

    def check_crown(self, footprint: np.ndarray, label: str) -> None:
        crop = footprint[tight(footprint)]
        brute = oracles.hand_crown(crop.tolist(), 1.0, D3["crown_inner_m"], D3["crown_outer_m"])
        fast = near(crop, 1.0, D3["crown_outer_m"]) & ~near(crop, 1.0, D3["crown_inner_m"])
        np.testing.assert_array_equal(fast, brute, label)

    def test_the_crown_of_every_final_footprint_is_the_brute_force_one(self) -> None:
        """RF-016-02, RF-016-06: la corona de la huella final de cada caso (la de ``near`` y la de ``hand_crown``) es la
        misma celda a celda: el cono de 3° y el de 8°, los cinco acopios (el 1 y el 2, repartidos), y tres candidatos."""
        run = survey_run()
        for tilt, (case, _outcome, item, _grown, _mark) in cone_runs().items():
            footprint = np.zeros(case.grid.shape, dtype=bool)
            footprint.ravel()[item.cells] = True
            with self.subTest(f"cono de {tilt}°"):
                self.check_crown(footprint, f"cono {tilt}")
        footprints = [(item.key, item.cells) for item in run.outcome.stockpiles]
        footprints += [(name, candidate.cells) for name, candidate in run.named_candidates()[:3]]
        for name, cells in footprints:
            footprint = np.zeros(run.grid.shape, dtype=bool)
            footprint.ravel()[cells] = True
            with self.subTest(name):
                self.check_crown(footprint, name)

    def test_the_enlarged_mark_of_the_isolated_stockpiles_is_the_brute_force_one(self) -> None:
        """RF-016-02: la marca del Acopio 3 ampliada por su margen de 6 m y la del Acopio 4, por el de 10 m, son las de
        ``hand_dilate`` (cada celda contra cada celda de la marca), celda a celda."""
        run = survey_run()
        for mark in sdata.MARKS[2:4]:
            margin = D3["margin_m"] if mark.margin_m is None else mark.margin_m
            mask = box_mask(run.grid, mark.box)
            crop = mask[tight(mask, reach=math.ceil(margin) + 1)]
            with self.subTest(mark.name):
                np.testing.assert_array_equal(near(crop, 1.0, margin), oracles.hand_dilate(crop.tolist(), 1.0, margin))


class WholeHandGrowTest(unittest.TestCase):
    """El oráculo entero de fuerza bruta (``hand_grow``) sobre la ventana de 120 × 120 celdas del cono de 3° de CE-016-02."""

    def test_the_cone_on_3_degrees_is_the_whole_brute_force_hand_grow(self) -> None:
        """CE-016-02, RF-016-02, RF-016-05: el ``hand_grow`` de fuerza bruta sobre la ventana entera da, del cono de 3° con
        sus ocho atípicas, la misma huella, el mismo plano a ≤ 10⁻⁹ m en cada celda, el mismo volumen a ≤ 10⁻⁹ relativo, las
        mismas vueltas y las mismas notas que el código y que ``grow_by_hand``."""
        case, _outcome, item, mine, mark = cone_runs()[3.0]
        brute = hand_grow(case.terrain, case.grid, mark, margin_m=D3["margin_m"])
        np.testing.assert_array_equal(np.flatnonzero(brute.found.mask), item.cells)
        np.testing.assert_allclose(item.plane.values(case.grid), brute.base, rtol=0.0, atol=1e-9)
        self.assertAlmostEqual(item.volume_m3 / brute.volume - 1.0, 0.0, delta=1e-9)
        self.assertEqual((item.turns, item.converged), (brute.turns, brute.converged))
        self.assertEqual([note.code for note in item.notes], expected_codes(brute))
        assert_plane_and_volume(self, mine, plane=item.plane, volume=item.volume_m3, turns=item.turns,
                                converged=item.converged)
        assert_notes(self, item.notes, hand_notes(mine))
