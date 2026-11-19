# SPDX-License-Identifier: GPL-3.0-or-later
"""El cuerpo apoyado por pasos con 20 y 100 ha, los tiempos del plan §7.3 (spec 016, T24; HU-016-4; RF-016-20; RNF-016-02,
RNF-016-03; plan 016 §5.4 A11, §5.7 P-7, §7.3). Va al paso «hito» de ``check.py --completo`` (P-13: pasan de 1 s); lo rápido
—la igualdad bit a bit, las bandas, los 8.000 puntos colineales, 12 ha por pasos— está en ``test_thickness_steps.py`` y en
``tests/unit/gis/test_cdt_steps.py``, en el «verde».

Con datos en líneas (secciones) los triángulos entre dos secciones diagonales son astillas de caja grande y ``tin_to_raster`` cuesta
lo que suman esas cajas (plan §2.1): 100 ha de secciones, 6,9 s de una pieza. Por bandas el total baja (más cabe en la caché) y **cada
llamada** del hilo de Blender, con el presupuesto de 0,05 s de la interfaz, dura ≈ 25 ms.

- :class:`LargeWindowTest`: 100 ha con 7.500 datos en 10 secciones diagonales, con 10.000 datos sueltos y 20 ha con secciones:
  ninguna llamada de ``body_steps`` pasa de 0,2 s y el cálculo entero cabe en los 10 s de RNF-016-02.
- :class:`LargeRasterTest`: el espesor por bandas de 49 ha de secciones es el de una pieza, bit a bit.
- :class:`SlowNoticeTest` (T44; RNF-016-02): el aviso del resumen sale por el **coste estimado de las cajas del TIN**, no por el área: las
  mismas 100 ha con 10 secciones a 100 m no avisan y con 5 o con 8 a 200 m, sí (con la causa y el coste estimado).
"""

from __future__ import annotations

import time
import unittest
from typing import Any

import numpy as np

from tests.support.package import import_geoblender
from tests.unit.design import test_thickness_steps as steps

thickness = import_geoblender("design.thickness")

SLOW = "des.body_sections_large"

LIMIT_S = steps.LIMIT_S
"""RNF-016-03: ninguna llamada del hilo de Blender dura más."""
TOTAL_S = 10.0
"""RNF-016-02: calcular un cuerpo apoyado, ≤ 10 s (con 100 ha de secciones, el límite que el resumen avisa: plan §5.7 P-7)."""


def timed(side: int, xy: np.ndarray) -> tuple[Any, list[float], float]:
    """El resultado, la duración de cada llamada de ``body_steps`` (presupuesto de la interfaz, 0,05 s) y el total, de una ventana
    de ``side`` × ``side`` celdas de 1 m con los datos ``xy`` (unidades de celda)."""
    case = steps.CallsTest()
    case.GRID = steps.sdata.window_grid(1.0, float(side))
    job = case.job(xy)
    work = thickness.body_steps(job, budget_s=0.05)
    laps: list[float] = []
    last = None
    started = time.perf_counter()
    while True:
        lap = time.perf_counter()
        try:
            last = next(work)
        except StopIteration:
            break
        laps.append(time.perf_counter() - lap)
    total = time.perf_counter() - started
    assert last is not None and last.result is not None
    return last.result, laps, total


class LargeWindowTest(unittest.TestCase):
    """RNF-016-02, RNF-016-03: ninguna llamada pasa de 0,2 s y el total cabe en 10 s, con 20 y 100 ha."""

    def check(self, name: str, side: int, xy: np.ndarray) -> Any:
        outcome, laps, total = timed(side, xy)
        message = (f"{name}: {len(xy)} datos, ventana de {side}²: total {total:.2f} s, {len(laps)} llamadas, la mayor "
                   f"{max(laps) * 1000:.0f} ms")
        self.assertLessEqual(max(laps), LIMIT_S, message)
        self.assertLessEqual(total, TOTAL_S, message)
        self.assertGreater(len(laps), 20, message)
        self.assertGreater(outcome.tin_cells, 0, message)
        return outcome

    def test_20_ha_of_sections(self) -> None:
        """20 ha con datos en secciones diagonales (plan §7.3: 0,19 + 1,01 s de una pieza)."""
        self.check("20 ha de secciones", 450, steps.sections(450, 4, 112))

    def test_100_ha_of_sections(self) -> None:
        """100 ha con 10 secciones diagonales de 7.500 datos (plan §7.3: 0,45 + 6,9 s con 7.985 datos)."""
        data = steps.sections(1000, 10, 100)
        self.assertEqual(len(data), 7500)
        outcome = self.check("100 ha de secciones", 1000, data)
        self.assertNotIn(SLOW, [item.code for item in outcome.notices], "10 secciones a 100 m: 5,7 s estimados, por debajo del límite")

    def test_100_ha_of_loose_data(self) -> None:
        """100 ha con 10.000 datos sueltos (plan §7.3: 0,15 + 0,39 s)."""
        self.check("100 ha de datos sueltos", 1000, steps.loose((1000, 1000), 10_000, 3))


class SlowNoticeTest(unittest.TestCase):
    """RNF-016-02 (T44): el aviso de lo lento sale por el coste estimado del TIN y no por el área (las 100 ha son las mismas)."""

    def check(self, name: str, count: int, spacing: int, data: int) -> Any:
        xy = steps.sections(1000, count, spacing)
        self.assertEqual(len(xy), data)
        outcome, laps, total = timed(1000, xy)
        message = f"{name}: {len(xy)} datos, total {total:.2f} s, la mayor llamada {max(laps) * 1000:.0f} ms"
        self.assertLessEqual(max(laps), LIMIT_S, message)
        self.assertGreater(outcome.tin_cost, 0.0, message)
        self.assertAlmostEqual(outcome.estimated_s, thickness.estimate_seconds(outcome.tin_cost), places=12)
        return outcome

    def test_100_ha_of_5_sections_at_200_m_is_warned_with_the_cause_and_the_estimated_cost(self) -> None:
        """5 secciones a 200 m (3.700 datos; T37: 9,09 s de «Calcular» a «Crear», más de lo que el aviso deja pasar) avisan con el coste
        estimado (entre 8 y 10 s) y la separación de las secciones como causa, en los dos idiomas."""
        outcome = self.check("5 secciones a 200 m", 5, 200, 3700)
        (notice,) = [item for item in outcome.notices if item.code == SLOW]
        self.assertGreater(outcome.estimated_s, thickness.SLOW_BODY_S)
        self.assertLess(outcome.estimated_s, 10.0)
        self.assertEqual((notice.values["seconds"], notice.values["limit"]), (round(outcome.estimated_s, 1), thickness.SLOW_BODY_S))
        self.assertIn("separación", notice.text("es"))
        self.assertIn(f"{round(outcome.estimated_s, 1):.1f}".replace(".", ","), notice.text("es"))
        self.assertIn("separation", notice.text("en"))

    def test_100_ha_of_8_sections_at_200_m_is_warned_over_the_ten_seconds(self) -> None:
        """8 secciones a 200 m (4.600 datos; T37: 11,27 s, más de los 10 s de RNF-016-02) avisan con un coste estimado de más de 10 s."""
        outcome = self.check("8 secciones a 200 m", 8, 200, 4600)
        self.assertIn(SLOW, [item.code for item in outcome.notices])
        self.assertGreater(outcome.estimated_s, 10.0)


class LargeRasterTest(unittest.TestCase):
    """RF-016-20: las bandas dan lo mismo que una pieza con 49 ha de astillas."""

    def test_the_49_ha_raster_by_bands_is_the_one_piece_raster(self) -> None:
        """El espesor del TIN de 49 ha de secciones diagonales (4.160 datos con cotas al azar) por bandas, con el coste por
        defecto, es, bit a bit, el de ``tin_to_raster`` de una pieza."""
        side = 700
        xy = steps.sections(side, 8, 90)
        tin = steps.make_tin(xy, np.random.default_rng(5).uniform(0.5, 6.0, len(xy)))
        banded, units = steps.by_bands(tin, (side, side))
        whole = steps.one_piece(tin, (side, side))
        self.assertGreater(units, 50)
        self.assertEqual(banded.tobytes(), whole.tobytes())


if __name__ == "__main__":
    unittest.main()
