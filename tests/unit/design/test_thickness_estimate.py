# SPDX-License-Identifier: GPL-3.0-or-later
"""El aviso del cuerpo apoyado por el coste de las cajas del TIN y no por el área (spec 016, T44; HU-016-4; RF-016-20;
RNF-016-02; plan 016 §7.3 y §8).

La T37 midió que el cálculo de un cuerpo con datos en secciones depende de **cómo de separadas** están las secciones, no del área ni del
número de datos: con las mismas 100 ha, 10 secciones a 100 m cuestan 5,66 s y 5 a 200 m, 9,09 s (y 8 a 200 m, 11,27 s: más de los 10 s de
RNF-016-02). Los triángulos entre dos secciones lejanas son astillas largas y ``gis.tin.tin_to_raster`` cuesta lo que suman las cajas de
sus triángulos (``thickness._row_costs``). El aviso de la T25 (más de 100 ha con secciones) solo miraba el área: ahora el resumen estima
el coste de ese cálculo con lo que ``_row_costs`` suma y **avisa si pasa de** :data:`thickness.SLOW_BODY_S` (unos 8 s), con la causa (la
separación de los datos) y el coste estimado.

- :class:`CostTest`: el coste es lo que suman las cajas del TIN (a mano, con ``_row_costs``) y crece con la separación de las secciones,
  no con el área.
- :class:`EstimateTest`: la estimación (``thickness.estimate_seconds``) con las cifras medidas en la T37 —las 100 ha de 10 secciones a 100 m
  quedan por debajo del límite y las de 5 y 8 a 200 m, por encima—; el aviso con su causa y su coste estimado, en los dos idiomas, y solo
  cuando se pasa del límite.

El cálculo de las 100 ha de verdad (con el aviso del resultado) está en ``milestone_thickness_steps.py`` (P-13).
"""

from __future__ import annotations

import math
import unittest
from typing import Any
from unittest import mock

from tests.support.package import import_geoblender
from tests.unit.design import test_thickness as tt
from tests.unit.design import test_thickness_steps as steps

thickness = import_geoblender("design.thickness")

SLOW = "des.body_sections_large"

# El coste de las cajas del TIN (``_row_costs``) de las 100 ha de la T37 (ventana de 1.000 × 1.000 celdas de 1 m; ``steps.sections``),
# medido en el Python de Blender el 19/11/2026 junto al tiempo de ``body_steps`` entero (4,76 s, 8,15 s y 10,09 s): 0,12 µs por unidad.
COST_100_HA_10_AT_100 = 38_925_692.0
COST_100_HA_5_AT_200 = 64_304_496.0
COST_100_HA_8_AT_200 = 87_939_732.0


def job_of_sections(side: int, count: int, spacing: int) -> Any:
    """Un cuerpo «bajo un techo» de una ventana de ``side`` × ``side`` celdas de 1 m con ``count`` secciones diagonales a ``spacing``
    celdas una de otra (``steps.sections``: las astillas de P-7)."""
    case = steps.CallsTest()
    case.GRID = steps.sdata.window_grid(1.0, float(side))
    return case.job(steps.sections(side, count, spacing))


def spied_costs() -> tuple[list[float], Any]:
    """Un espía de ``thickness._row_costs``: el coste total (la suma de las filas) de cada TIN que rasteriza."""
    seen: list[float] = []
    original = thickness._row_costs

    def spy(tin: Any, shape: tuple[int, int]) -> Any:
        found = original(tin, shape)
        seen.append(math.fsum(float(price) for price in found[0]))
        return found

    return seen, mock.patch.object(thickness, "_row_costs", spy)


SIDE = 160
"""La ventana de las pruebas (celdas de 1 m: 2,6 ha): con las secciones de abajo cada cálculo cuesta ≈ 0,1 s."""
NEAR = (8, 20)
"""Ocho secciones a 20 celdas una de otra."""
FAR = (4, 40)
"""Cuatro secciones a 40 celdas: con la mitad de datos, el TIN cuesta más (astillas más largas)."""


def computed(shape: tuple[int, int] = FAR) -> Any:
    """El cuerpo de la ventana de :data:`SIDE` con ``shape`` = (secciones, separación en celdas)."""
    return thickness.compute_body(job_of_sections(SIDE, *shape))


class CostTest(unittest.TestCase):
    """RNF-016-02: el coste del cálculo es lo que suman las cajas del TIN, y depende de la separación de las secciones."""

    def test_the_cost_is_what_the_boxes_of_the_tin_sum(self) -> None:
        """RNF-016-02: ``BodyOutcome.tin_cost`` es la suma, sobre las filas, de lo que cuesta rasterizar el TIN (``_row_costs``: las celdas
        de la caja de cada triángulo y 4 por triángulo y fila), tal como la ve el espía; sin TIN (menos de tres datos) es 0."""
        seen, spy = spied_costs()
        with spy:
            outcome = computed()
        self.assertEqual(len(seen), 1)
        self.assertGreater(seen[0], 100_000.0)
        self.assertEqual(outcome.tin_cost, seen[0])
        pair = tt.run(tt.job_of(tt.box(3, 21, 3, 21), points=tt.points_of({(10, 10): 2.0, (14, 14): 3.0})))
        self.assertEqual((pair.tin_cost, pair.tin_points), (0.0, 2))

    def test_the_cost_grows_with_the_separation_of_the_sections_and_not_with_the_area_or_the_number_of_data(self) -> None:
        """RNF-016-02 (T37): en la misma ventana, **4 secciones a 40 celdas cuestan más que 8 a 20**, con la mitad de datos: lo que manda
        es lo largas y separadas que son las astillas del TIN (como las 100 ha de 5 secciones a 200 m frente a las de 10 a 100 m)."""
        near, far = computed(NEAR), computed(FAR)
        self.assertGreater(near.tin_points, 1.5 * far.tin_points)
        self.assertEqual(near.body.shape, far.body.shape)
        self.assertGreater(far.tin_cost, 1.2 * near.tin_cost)


class EstimateTest(unittest.TestCase):
    """RNF-016-02: el coste estimado y su aviso."""

    def test_the_estimate_is_the_base_plus_the_unit_cost_of_the_boxes(self) -> None:
        """RNF-016-02: ``estimate_seconds(coste)`` = el tiempo de leer y escribir la superficie (``BODY_BASE_S``) más el de rasterizar
        cada unidad de coste del TIN (``TIN_UNIT_S``, 0,12 µs medidos); sin TIN, solo el primero. Y ``BodyOutcome.estimated_s`` es la
        de su coste."""
        self.assertEqual(thickness.estimate_seconds(0.0), thickness.BODY_BASE_S)
        self.assertEqual(thickness.estimate_seconds(2_000_000.0), thickness.BODY_BASE_S + thickness.TIN_UNIT_S * 2_000_000.0)
        outcome = computed()
        self.assertEqual(outcome.estimated_s, thickness.estimate_seconds(outcome.tin_cost))
        self.assertEqual((thickness.SLOW_BODY_S, thickness.BODY_BASE_S, thickness.TIN_UNIT_S), (8.0, 1.0, 0.12e-6))

    def test_100_ha_of_10_sections_at_100_m_is_under_the_limit_and_5_or_8_at_200_m_are_over_it(self) -> None:
        """RNF-016-02 (T37): con las cifras medidas, el cuerpo de 100 ha de **10 secciones a 100 m** (5,66 s de «Calcular» a «Crear»)
        queda por debajo del límite y el de **5 a 200 m** (9,09 s) y el de **8 a 200 m** (11,27 s, más de los 10 s del RNF) por encima;
        la estimación sigue a la medida con un margen de 0,6 s."""
        for cost, measured in ((COST_100_HA_10_AT_100, 5.66), (COST_100_HA_5_AT_200, 9.09), (COST_100_HA_8_AT_200, 11.27)):
            with self.subTest(coste=cost):
                self.assertLessEqual(abs(thickness.estimate_seconds(cost) - measured), 0.6)
        self.assertLess(thickness.estimate_seconds(COST_100_HA_10_AT_100), thickness.SLOW_BODY_S)
        self.assertGreater(thickness.estimate_seconds(COST_100_HA_5_AT_200), thickness.SLOW_BODY_S)
        self.assertGreater(thickness.estimate_seconds(COST_100_HA_8_AT_200), thickness.SLOW_BODY_S)

    def test_the_notice_comes_when_the_estimate_passes_the_limit_with_the_estimate_and_the_cause(self) -> None:
        """RNF-016-02: con el límite entre las dos estimaciones de la misma ventana (4 secciones a 40 celdas y 8 a 20) **solo avisa la más
        costosa**; el aviso lleva el coste estimado (a la décima) y el límite, en los dos idiomas dice la causa (la separación de los
        datos de espesor) y no deja nada sin escribir."""
        near, far = computed(NEAR), computed(FAR)
        limit = (near.estimated_s + far.estimated_s) / 2.0
        with mock.patch.object(thickness, "SLOW_BODY_S", limit):
            near, far = computed(NEAR), computed(FAR)
        self.assertNotIn(SLOW, [item.code for item in near.notices])
        (notice,) = [item for item in far.notices if item.code == SLOW]
        self.assertEqual(notice.severity, "warning")
        self.assertEqual((notice.values["entity"], notice.values["seconds"], notice.values["limit"]),
                         ("Cuerpo A", round(far.estimated_s, 1), limit))
        self.assertNotIn("area", notice.values)
        for language, words in (("es", ("separación", "estimados", "tarda")), ("en", ("separation", "estimated"))):
            text = notice.text(language)
            self.assertNotIn("{", text)
            for word in words:
                self.assertIn(word, text, language)
        self.assertIn(f"{round(far.estimated_s, 1):.1f}".replace(".", ","), notice.text("es"))
        self.assertIn(f"{round(far.estimated_s, 1):.1f}", notice.text("en"))

    def test_the_area_no_longer_decides(self) -> None:
        """RNF-016-02: el aviso ya no mira el área (la T25 avisaba por encima de 100 ha con secciones): la constante del área ya no
        existe y con el límite por defecto estas ventanas no avisan, ni siquiera con las secciones más separadas."""
        self.assertFalse(hasattr(thickness, "SECTIONS_LARGE_M2"))
        for shape in (NEAR, FAR):
            outcome = computed(shape)
            self.assertNotIn(SLOW, [item.code for item in outcome.notices])
            self.assertLess(outcome.estimated_s, thickness.SLOW_BODY_S)


if __name__ == "__main__":
    unittest.main()
