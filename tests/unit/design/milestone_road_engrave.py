# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_road_engrave» (spec 017, T13; RF-017-21; RNF-017-04, 06 y 07; plan 017 §5.4 A9 y §7.3): lo que pasa de 1 s y no entra en el «verde»
(``tools/check.py``, RNF-017-09). El «verde» deja en ``test_road_engrave`` y en ``test_ref_road_engrave`` lo que cubre cada RF (en mallas de ≤ 800 × 800 celdas y con
alcances de unos 12 m); esto lo ejecuta el paso «hito» de ``tools/check.py --completo`` (la publicación lo pide siempre).

- **Grabar 2 km con la métrica exacta** (RNF-017-04, RNF-017-06; plan §7.3): el eje de 2.035 m de la escala (63 vértices, 61 curvas de R = 20 m, en diagonal) sobre la
  rejilla de 2,81 M celdas, con la sección de 11,5 m, los ángulos de 60° y de 35° y el alcance de 60 m, con una rasante que sube y baja sobre el terreno (el borde corta y
  rellena a tramos): el grabado entero tarda ≤ 15 s **por cada 2 M celdas de la ventana de trabajo** (RNF-017-04 se da para una caja de ≤ 2 M celdas; el plan midió 8,31 s
  con 1,58 M: huella 0,16 s, ascendente 2,74 s, descendente 2,70 s, alcance 2,67 s y compuesto 0,02 s) con **cada llamada del paso en ≤ 0,2 s**. La ventana de **este** eje
  (``rd.scale_axis_2km``: la caja del corredor de 1.431 × 1.431 celdas ampliada por 62 celdas a cada lado) es de **2,42 M celdas**, no de 1,58 M: el tiempo es el de la
  ventana, no el del corredor (``docs/trampas.md``).
- **La misma pista con el *chamfer* 5×5** (RNF-017-04): ≤ 2 s (el plan midió 0,43 s).
- **La superficie es la de partida fuera de lo que mueve** (RF-017-21): a escala, ni un bit de la rejilla fuera de la sección y de su borde cambia, y el corte y el relleno son
  los de restar las dos superficies.
"""

from __future__ import annotations

import time
import unittest
from typing import Any

import numpy as np

from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.support.timing import least_of

params = import_geoblender("design.params")
road_axis = import_geoblender("design.road_axis")
road_engrave = import_geoblender("design.road_engrave")
road_section = import_geoblender("design.road_section")

STEP_LIMIT_S = 0.2
"""Lo que puede tardar cada llamada del paso (RNF-017-06)."""
EXACT_LIMIT_S = 15.0
"""Lo que puede tardar el grabado de 2 km con la métrica exacta en local con una caja de ≤ 2 M celdas (RNF-017-04)."""
BOX_CELLS = 2_000_000
"""La caja a que se refiere EXACT_LIMIT_S: con una mayor, el plazo crece con ella (el coste es el de la ventana)."""
CHAMFER_LIMIT_S = 2.0
"""Lo que puede tardar con el *chamfer* (RNF-017-04)."""
PROJECT = {params.TOLERANCE_FACE: 1.0, params.VERIFY_MIN_THICKNESS: 0.05, params.EDGE_MAX_STEP: 1.0, params.EDGE_MIN_SHARE: 99.0}
"""Los parámetros del proyecto que lee el borde (valores de la prueba, no de un proyecto)."""
PROFILE = rd.PROFILE
"""El perfil de referencia: calzada 10,5 m, arcén 0 m, caballón 1 m, desmonte a 60°, terraplén a 35°, alcance de 60 m y métrica exacta."""
WAVE_M, WAVE_PERIOD_M = 2.5, 300.0
"""La rasante sube y baja 2,5 m sobre el terreno del eje cada 300 m (HIPÓTESIS de la prueba: desmonte y terraplén a tramos, con una pendiente de diseño de hasta el 14 %)."""


def terrain_of(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Un plano que sube al noreste (8,5 % en la diagonal del eje)."""
    return 150.0 + 0.06 * (x + y)


class ScaleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = rd.scale_grid()
        cls.terrain = np.asarray(terrain_of(*rd.local_centers(cls.grid)), dtype=np.float64)
        cls.line = rd.scale_axis_2km()
        cls.axis = road_axis.axis_of(cls.line, PROFILE.curve_radius_m, PROFILE.min_radius_m, PROFILE.station_step_m)

    def prepare(self, profile: Any) -> tuple[Any, Any, Any]:
        """El trabajo, la sección (en la ventana de trabajo) y su rasante por celda para el perfil ``profile``."""
        road_profile = rd.road_profile(profile)
        window = road_engrave.engrave_window(self.axis, road_profile, self.grid)
        section = road_section.section_cells(self.axis, profile.carriageway_m, profile.shoulder_m, profile.berm_m, self.terrain, self.grid, window)
        on_axis = road_section.sample_terrain(self.terrain, self.grid, self.axis.points[:, 0], self.axis.points[:, 1])
        wave = WAVE_M * np.sin(2.0 * np.pi * self.axis.stations / WAVE_PERIOD_M)
        job = rd.axis_job(self.grid, self.terrain, self.line, profile=profile)
        return job, section, section.levels(self.axis.stations, on_axis + wave)

    def timed(self, job: Any, section: Any, levels: Any) -> tuple[Any, float, float, int]:
        """El grabado por pasos: el resultado, la llamada más larga al generador (s), el total (s) y cuántas llamadas fueron."""
        steps = road_engrave.engrave_steps(job, section, levels, PROJECT)
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

    def test_engraving_2_km_with_the_exact_metric_in_at_most_15_s_per_2_m_cells_and_calls_of_at_most_0_2_s(self) -> None:
        """RNF-017-04, RNF-017-06, RF-017-21: el eje de 2 km con 61 curvas se graba entero con la métrica exacta (alcance de 60 m, 60° y 35°) en ≤ 15 s por cada 2 M celdas de
        la ventana de trabajo (la de este eje es de 2,42 M celdas: ≤ 18,1 s), con cada llamada del paso en ≤ 0,2 s (la mejor de dos pasadas para la llamada más larga: la
        prueba es de plazo)."""
        self.assertEqual(self.axis.curve_count, 61)
        job, section, levels = self.prepare(PROFILE)
        cells = (section.window[0].stop - section.window[0].start) * (section.window[1].stop - section.window[1].start)
        self.assertGreater(cells, 2_300_000)
        self.assertLess(cells, 2_500_000)
        self.assertGreater(section.cell_count, 22_000)
        found, longest, total, count = self.timed(job, section, levels)
        limit = EXACT_LIMIT_S * max(cells, BOX_CELLS) / BOX_CELLS
        self.assertGreater(count, 20, "cede el hilo por unidades")
        self.assertLessEqual(total, limit, f"el grabado entero tardó {total:.2f} s con una ventana de {cells:,} celdas")
        if longest > STEP_LIMIT_S:
            longest = least_of(lambda: self.timed(job, section, levels)[1], STEP_LIMIT_S, attempts=2, max_attempts=2)
        self.assertLessEqual(longest, STEP_LIMIT_S, f"una llamada de {longest:.3f} s (el total de la pasada, {total:.2f} s)")
        start = self.terrain[found.window]
        moved = found.surface != start
        np.testing.assert_array_equal(moved, (found.footprint & (found.applied != start)) | found.changed)
        quiet = ~found.footprint & ~found.changed
        np.testing.assert_array_equal(found.surface[quiet], start[quiet])
        drop = start - found.surface
        np.testing.assert_allclose(found.cut_m3, np.maximum(drop, 0.0).sum() * self.grid.cell_area, rtol=1e-9)
        np.testing.assert_allclose(found.fill_m3, np.maximum(-drop, 0.0).sum() * self.grid.cell_area, rtol=1e-9)
        self.assertGreater(found.edge_cut_m3, 0.0)
        self.assertGreater(found.edge_fill_m3, 0.0)
        self.assertEqual(found.off_level, ())

    def test_engraving_2_km_with_the_chamfer_in_at_most_2_s(self) -> None:
        """RNF-017-04, RF-017-21: la misma pista con el *chamfer* 5×5 del perfil se graba en ≤ 2 s con cada llamada del paso en ≤ 0,2 s, y su corte y su relleno son
        los de la métrica exacta salvo lo que mide de menos el *chamfer* (±1,4 % de la distancia: el de la sección, igual; el del borde, a menos del 10 %)."""
        profile = rd.profile_with(metric="chamfer5")
        job, section, levels = self.prepare(profile)
        found, longest, total, _count = self.timed(job, section, levels)
        self.assertLessEqual(total, CHAMFER_LIMIT_S, f"el grabado entero tardó {total:.2f} s")
        self.assertLessEqual(longest, STEP_LIMIT_S, f"una llamada de {longest:.3f} s")
        self.assertEqual(found.metric.value, "chamfer5")
        exact = self.timed(*self.prepare(PROFILE))[0]
        self.assertAlmostEqual(found.section_cut_m3, exact.section_cut_m3, delta=1e-9 * exact.section_cut_m3)
        self.assertGreater(found.edge_cut_m3, 0.0)
        for name in ("edge_cut_m3", "edge_fill_m3"):
            self.assertAlmostEqual(getattr(found, name), getattr(exact, name), delta=0.1 * getattr(exact, name), msg=name)


if __name__ == "__main__":
    unittest.main()
