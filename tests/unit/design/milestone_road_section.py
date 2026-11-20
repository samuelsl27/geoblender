# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_road_section» (spec 017, T12; RF-017-20; RNF-017-04 y 06; plan 017 §5.4 A6 y A7 y §7.3): lo que pasa de 1 s y no entra en el
«verde» (``tools/check.py``, RNF-017-09). El «verde» deja en ``test_road_section`` y en ``test_ref_road_section`` lo que cubre cada RF (en mallas de ≤ 400 × 400
celdas de 1 m); esto lo ejecuta el paso «hito» de ``tools/check.py --completo`` (la publicación lo pide siempre).

- **La huella de 2 km con 61 curvas** (RNF-017-04, RNF-017-06; plan §7.3): el eje de 2.035 m de la escala (63 vértices, 61 curvas de R = 20 m, en diagonal) sobre
  la rejilla de 2,81 M celdas, con la sección de 11,5 m (≈ 23.000 celdas): cada llamada del paso (una unidad de trabajo) en ≤ 0,2 s (RNF-017-06; el plan midió 0,16 s
  la huella entera) y la longitud medida de la huella, la del eje con un error ≤ 1 celda (error 20).
- **La misma sección con la rejilla entera como ventana** (RF-017-20): la abscisa, el lado y la clase de cada celda no dependen de la ventana en que se miden, a escala.
"""

from __future__ import annotations

import math
import time
import unittest
from typing import Any

import numpy as np

from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.support.timing import least_of

road_axis = import_geoblender("design.road_axis")
road_section = import_geoblender("design.road_section")

STEP_LIMIT_S = 0.2
"""Lo que puede tardar cada llamada del paso (RNF-017-06)."""
PROFILE = rd.PROFILE
"""El perfil de referencia: calzada 10,5 m, arcén 0 m y caballón 1 m (sección de 11,5 m)."""


def cross_slope(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Un plano que sube al noreste: en la diagonal del eje (de suroeste a noreste, con curvas) el lado más alto es el izquierdo."""
    return 150.0 + 0.1 * (x + y)


class ScaleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = rd.scale_grid()
        cls.axis = road_axis.axis_of(rd.scale_axis_2km(), PROFILE.curve_radius_m, PROFILE.min_radius_m, PROFILE.station_step_m)
        cls.terrain = np.asarray(cross_slope(*rd.local_centers(cls.grid)), dtype=np.float64)

    def arguments(self, window: Any) -> tuple[Any, ...]:
        return (self.axis, PROFILE.carriageway_m, PROFILE.shoulder_m, PROFILE.berm_m, self.terrain, self.grid, window)

    def paced(self) -> tuple[Any, float, int, float]:
        """La sección por pasos, la llamada más larga al generador (s), cuántas fueron y el total (s)."""
        steps = road_section.section_steps(*self.arguments(None))
        longest, count, total = 0.0, 0, 0.0
        while True:
            before = time.perf_counter()
            try:
                next(steps)
            except StopIteration as done:
                spent = time.perf_counter() - before
                return done.value, max(longest, spent), count, total + spent
            spent = time.perf_counter() - before
            longest, count, total = max(longest, spent), count + 1, total + spent

    def test_the_footprint_of_the_2_km_axis_with_61_curves_in_calls_of_at_most_0_2_s(self) -> None:
        """RNF-017-06, RNF-017-04, RF-017-20: el eje de 2 km con 61 curvas sobre la rejilla de 2,81 M celdas da una sección de ≈ 23.000 celdas con la longitud del
        eje ± 1 celda (error 20), con cada llamada del paso en ≤ 0,2 s (la mejor de las pasadas: la prueba es de plazo)."""
        self.assertEqual(self.axis.curve_count, 61)
        section, _, count, total = self.paced()
        self.assertGreater(count, 20, "cede el hilo por teselas y por bloques")
        self.assertGreater(section.cell_count, 22_000)
        self.assertLess(section.cell_count, 26_000)
        self.assertLessEqual(abs(section.length_m - self.axis.length_m), math.sqrt(2.0) * self.grid.dx, "la longitud de su huella a lo largo del eje")
        self.assertGreater(abs(section.length_m - (self.axis.length_m + PROFILE.section_m)), 5.0, "no es la de un *buffer* de extremos redondos")
        longest = least_of(lambda: self.paced()[1], STEP_LIMIT_S)
        self.assertLessEqual(longest, STEP_LIMIT_S, f"una llamada de {longest:.3f} s (el total de la pasada, {total:.3f} s)")

    def test_the_section_does_not_depend_on_the_window_it_is_measured_in(self) -> None:
        """RF-017-20: con la rejilla entera como ventana, la sección de las mismas celdas tiene la misma clase, el mismo lado y, bit a bit, la misma abscisa y la
        misma distancia lateral que con la caja del corredor."""
        box = road_section.section_cells(*self.arguments(None))
        whole = road_section.section_cells(*self.arguments((slice(0, self.grid.nrows), slice(0, self.grid.ncols))))
        self.assertEqual(box.cell_count, whole.cell_count)
        for name in ("kind", "side", "sigma", "lateral"):
            np.testing.assert_array_equal(getattr(box, name), getattr(whole, name)[box.window], err_msg=name)


if __name__ == "__main__":
    unittest.main()
