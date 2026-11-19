# SPDX-License-Identifier: GPL-3.0-or-later
"""Un polígono de espesor grande no cuesta lo que su retícula (spec 016, T25; HU-016-4; RF-016-20, RNF-016-02, RNF-016-03; plan 016
§5.7 P-7 y §7.3; decisión de la sesión principal del 19/11/2026). Va al paso «hito» de ``check.py --completo`` (P-13: 20 ha a 1 m
son 200.000 celdas); la lógica, con cuentas a mano, está en ``test_thickness_polygons.py``, en el «verde».

La T24 midió que triangular la retícula de datos de un polígono (cada celda un dato) cuesta 52 µs por punto: un polígono de 20 ha a 1 m,
≈ 10 s de los 10 que da RNF-016-02. Con **el interior directo** y solo el contorno en el TIN, **un polígono de 20 ha a 1 m cuesta
≤ 1 s** y ninguna llamada del hilo pasa de 0,2 s (RNF-016-03); y el resultado en sus celdas es el espesor del polígono.
"""

from __future__ import annotations

import time
import unittest
from typing import Any

import numpy as np

from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.unit.design import test_thickness as tt

thickness = import_geoblender("design.thickness")

SIDE = 450
"""El lado del polígono (m): 450 × 450 = 20,25 ha a 1 m (202.500 celdas)."""
GRID = sdata.window_grid(1.0, 500.0)
MARGIN = (500 - SIDE) // 2


def square_job(value: float = 2.0) -> Any:
    """El polígono de 20 ha como huella y como único dato (espesor constante), sobre un apoyo plano."""
    west, south = GRID.west + MARGIN, GRID.north - 500.0 + MARGIN
    ring = np.array([[west, south], [west + SIDE, south], [west + SIDE, south + SIDE], [west, south + SIDE]], dtype=np.float64)
    footprint = np.zeros(GRID.shape, dtype=bool)
    footprint[MARGIN:MARGIN + SIDE, MARGIN:MARGIN + SIDE] = True
    return tt.job_of(footprint, polygons=[((ring,), value)], grid=GRID)


class LargePolygonTest(unittest.TestCase):
    """RF-016-20, RNF-016-02, RNF-016-03: el polígono de 20 ha a 1 m."""

    def test_a_polygon_of_20_ha_at_1_m_costs_at_most_a_second_and_gives_its_thickness_in_every_cell(self) -> None:
        """RNF-016-02 (decisión 19/11/2026): el cálculo entero del polígono de 20 ha a 1 m tarda ≤ 1 s (la T24 midió ≈ 10 s con la
        retícula entera); sus 202.500 celdas valen 2 m, las 448 × 448 del interior son directas y se triangulan solo las 1.796 del
        contorno."""
        job = square_job()
        started = time.perf_counter()
        outcome = thickness.compute_body(job)
        took = time.perf_counter() - started
        self.assertLessEqual(took, 1.0, f"{took:.2f} s")
        self.assertEqual(int(np.count_nonzero(outcome.body)), SIDE * SIDE)
        self.assertEqual((outcome.direct_cells, outcome.tin_points), ((SIDE - 2) ** 2, SIDE * SIDE - (SIDE - 2) ** 2))
        np.testing.assert_array_equal(outcome.thickness[outcome.body], np.full(SIDE * SIDE, 2.0))
        self.assertEqual(outcome.volume_m3, 2.0 * SIDE * SIDE)
        self.assertNotIn("des.body_many_data", [notice.code for notice in outcome.notices])

    def test_no_call_of_the_steps_lasts_more_than_a_fifth_of_a_second(self) -> None:
        """RNF-016-03: con el presupuesto de la interfaz (0,05 s) ninguna llamada del hilo pasa de 0,2 s con el polígono de 20 ha."""
        work = thickness.body_steps(square_job(), budget_s=0.05)
        longest, calls = 0.0, 0
        while True:
            started = time.perf_counter()
            try:
                step = next(work)
            except StopIteration:
                break
            longest = max(longest, time.perf_counter() - started)
            calls += 1
            if step.result is not None:
                break
        self.assertGreater(calls, 5)
        self.assertLessEqual(longest, 0.2, f"la llamada más larga, {longest:.3f} s")


if __name__ == "__main__":
    unittest.main()
