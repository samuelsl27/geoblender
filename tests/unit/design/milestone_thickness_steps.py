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
"""

from __future__ import annotations

import time
import unittest
from typing import Any

import numpy as np

from tests.support.package import import_geoblender
from tests.unit.design import test_thickness_steps as steps

thickness = import_geoblender("design.thickness")

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
        self.check("100 ha de secciones", 1000, data)

    def test_100_ha_of_loose_data(self) -> None:
        """100 ha con 10.000 datos sueltos (plan §7.3: 0,15 + 0,39 s)."""
        self.check("100 ha de datos sueltos", 1000, steps.loose((1000, 1000), 10_000, 3))


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
