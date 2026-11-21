# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_road_access» (spec 017, T15; RF-017-24; RNF-017-05 y 06; plan 017 §5.4 A10 y §7.3): lo que pasa de 1 s y no entra en el «verde»
(``tools/check.py``, RNF-017-09). El «verde» deja en ``test_road_access`` lo que cubre cada RF (en mallas de ≤ 200 × 200 celdas); esto lo ejecuta el paso «hito» de
``tools/check.py --completo`` (la publicación lo pide siempre).

- **A10 sobre 2,81 M celdas** (RNF-017-05, RNF-017-06; plan §7.3, rejilla de 1.654 × 1.699 celdas de 1 m, pendiente transitable del 12 % y ancho mínimo de 10 m, es decir, un disco de
  radio de 5 celdas): con una componente y con siete (seis franjas intocables de 12 filas y una entrada en cada una), lo alcanzable es **exactamente** lo que no es intocable
  (en todas las celdas el terreno pasa de pendiente transitable en ninguna), cada llamada del paso tarda ≤ 0,2 s y el total (que el plan midió en 0,17 s) ≤ 1 s: la parte de
  A10 de los 5 s de RNF-017-05 (la accesibilidad entera, con 250 tramos de berma, 5 plataformas y 20 zonas, es de T16 y de T34).
- **Con una máscara fragmentada** (el plan midió 0,21 s con 186.000 componentes): el 35 % de las celdas intocables al azar, una sola entrada: ≤ 1,5 s, con cada llamada en ≤ 0,2 s.
"""

from __future__ import annotations

import time
import unittest
from typing import Any

import numpy as np

from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.support.timing import least_of

road_access = import_geoblender("design.road_access")

STEP_LIMIT_S = 0.2
"""Lo que puede tardar cada llamada del paso (RNF-017-06)."""
SCALE_LIMIT_S = 1.0
"""Lo que puede tardar A10 entera sobre 2,81 M celdas (el plan midió 0,17 s; la accesibilidad entera, ≤ 5 s: RNF-017-05)."""
FRAGMENTED_LIMIT_S = 1.5
"""Lo mismo con una máscara fragmentada (el plan midió 0,21 s)."""
WALK_SLOPE_PCT, WALK_WIDTH_M = 12.0, 10.0
"""La pendiente transitable y el ancho mínimo del plan §7.3 (HIPÓTESIS de la prueba, como los de la referencia de IMGA: ninguno es valor por defecto)."""
BANDS = 7
BAND_ROWS = 12
"""Las siete componentes: seis franjas intocables de 12 filas entre siete tramos de la rejilla."""


class ScaleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = rd.scale_grid()
        x, y = rd.local_centers(cls.grid)
        cls.terrain = 150.0 + 4.0 * np.sin(x / 150.0) + 3.0 * np.cos(y / 120.0)
        cls.rng = np.random.default_rng(20261121)

    def job(self, untouchable: np.ndarray, entries: list[tuple[float, float]], width_m: float = WALK_WIDTH_M) -> Any:
        return rd.access_job(self.grid, self.terrain, entries, untouchable=untouchable, access=rd.AccessData(WALK_SLOPE_PCT, width_m, 0.0))

    @staticmethod
    def timed(job: Any) -> tuple[Any, float, float, int]:
        """A10 por pasos: el resultado, la llamada más larga al generador (s), el total (s) y cuántas llamadas fueron."""
        steps = road_access.access_steps(job)
        longest, count, total, last = 0.0, 0, 0.0, None
        while True:
            before = time.perf_counter()
            try:
                last = next(steps)
            except StopIteration:
                break
            spent = time.perf_counter() - before
            longest, count, total = max(longest, spent), count + 1, total + spent
        return last.result, longest, total, count

    def check(self, job: Any, limit_s: float) -> tuple[Any, int]:
        """Recorre A10 por pasos y comprueba el plazo total y el de cada llamada (la mejor de dos pasadas para la más larga: la prueba es de plazo); da el resultado y los pasos."""
        found, longest, total, count = self.timed(job)
        self.assertGreater(count, 3, "cede el hilo por unidades")
        self.assertLessEqual(total, limit_s, f"A10 tardó {total:.2f} s sobre {self.grid.nrows * self.grid.ncols:,} celdas")
        if longest > STEP_LIMIT_S:
            longest = least_of(lambda: self.timed(job)[1], STEP_LIMIT_S, attempts=2, max_attempts=2)
        self.assertLessEqual(longest, STEP_LIMIT_S, f"una llamada de {longest:.3f} s (el total de la pasada, {total:.2f} s)")
        return found, count

    def test_the_whole_grid_and_seven_components_in_at_most_1_s_and_calls_of_at_most_0_2_s(self) -> None:
        """RNF-017-05, RNF-017-06, RF-017-24: sobre 2,81 M celdas, con una componente (lo alcanzable es toda la rejilla) y con siete (seis franjas intocables y una entrada en cada
        tramo: lo alcanzable es todo lo que no es intocable, a celda), A10 entera tarda ≤ 1 s y cada llamada del paso, ≤ 0,2 s; el resultado por pasos es el de una vez."""
        none = np.zeros(self.grid.shape, dtype=bool)
        found, _count = self.check(self.job(none, [(10.5, 10.5)]), SCALE_LIMIT_S)
        self.assertTrue(found.reachable.all())
        self.assertEqual(found.area_m2, float(self.grid.nrows * self.grid.ncols))
        self.assertAlmostEqual(found.z_min_m, float(self.terrain.min()), delta=1e-9)
        self.assertAlmostEqual(found.z_max_m, float(self.terrain.max()), delta=1e-9)
        height = self.grid.nrows // BANDS
        bands = np.zeros(self.grid.shape, dtype=bool)
        for k in range(1, BANDS):
            bands[k * height:k * height + BAND_ROWS, :] = True
        entries = [(10.5, float(self.grid.nrows - (k * height + BAND_ROWS + 20) - 0.5)) for k in range(BANDS)]
        job = self.job(bands, entries)
        found, _count = self.check(job, SCALE_LIMIT_S)
        np.testing.assert_array_equal(found.reachable, ~bands)
        self.assertEqual(found.area_m2, float((~bands).sum()) * self.grid.cell_area)
        np.testing.assert_array_equal(road_access.access(job).reachable, found.reachable)
        one = road_access.access(self.job(bands, entries[:1]))
        self.assertTrue(one.reachable[:height].all() and not one.reachable[height:].any(), "una entrada alcanza solo su tramo")

    def test_a_fragmented_mask_in_at_most_1_5_s(self) -> None:
        """RNF-017-05, RNF-017-06, RF-017-24: con el 35 % de las celdas intocables al azar (decenas de miles de componentes) y una entrada, A10 entera tarda ≤ 1,5 s con cada
        llamada del paso en ≤ 0,2 s, no alcanza una celda intocable y lo alcanzable es una parte de lo que no lo es (la unión de las componentes con la entrada)."""
        mask = self.rng.random(self.grid.shape) < 0.35
        row, col = self.grid.nrows // 2, self.grid.ncols // 2
        while mask[row, col]:
            col += 1
        found, _count = self.check(self.job(mask, [(col + 0.5, float(self.grid.nrows - row) - 0.5)], width_m=1.0), FRAGMENTED_LIMIT_S)
        self.assertTrue(found.reachable[row, col])
        self.assertFalse((found.reachable & mask).any())
        self.assertGreater(int(found.reachable.sum()), 100_000)
        self.assertLess(int(found.reachable.sum()), int((~mask).sum()))


if __name__ == "__main__":
    unittest.main()
