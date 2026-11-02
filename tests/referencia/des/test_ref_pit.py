# SPDX-License-Identifier: GPL-3.0-or-later
"""Corta circular de referencia (spec 013, T12; HU-013-2; RF-013-22, RF-013-29, RF-013-30;
CE-013-09; plan 013 A8, A10, A11; D-8; inv. 07 §3.10).

La corta de la spec: fondo de R₀ = 50 m, **seis bancos de 10 m, cara de 70°, berma de 8 m** y un
terreno llano a 60 m. La semilla es el fondo (el disco de celdas a ≤ 50 m del eje, a 0 m), la
envolvente es la **ascendente** con el talud general del perfil (``h / (h/tan α + B)``), el
escalonado es de corte (ancla en el fondo) y la superficie de diseño es el mínimo con el terreno
donde se admite: el volumen que da el informe coincide con los **1.308.944 m³** del cálculo
analítico (troncos de cono de los seis bancos) dentro de la tolerancia de D-8 [la domina el
muestreo del disco semilla, de hasta media celda]: **≤ 1 % con celdas de 1 m y ≤ 2 % con celdas de
2 m**. Medido con este código (espesor mínimo 0,02 m, el de la 012):

| celdas | *chamfer* 5×5 | exacta |
| --- | --- | --- |
| 1 m | −0,28 % | −0,50 % |
| 2 m | −0,68 % | −0,93 % |

Además de la cifra, se comprueban el resto del informe (todo es desmonte, ni un metro cúbico de
relleno), las bermas reales (a ``z₀ + n·h`` de los seis bancos) y que la inclinación no pasa de la
cara más la tolerancia (ningún aviso de inclinación).
"""

from __future__ import annotations

import math
import unittest
from typing import Any

import numpy as np

from tests.support import design_fixtures as dfx
from tests.support.package import import_geoblender

benching = import_geoblender("design.benching")
berms = import_geoblender("design.berms")
compose = import_geoblender("design.compose")
envelopes = import_geoblender("design.envelopes")
params = import_geoblender("design.params")
report = import_geoblender("design.report")
res_provenance = import_geoblender("reserves.provenance")

ANALYTIC_M3 = 1_308_944.0
"""El volumen de CE-013-09 (m³): ``Σ π·h/3·(rᵢ² + rᵢ·Rᵢ + Rᵢ²)`` de los seis bancos."""
TOLERANCE_REL = {1.0: 0.01, 2.0: 0.02}
"""D-8: la tolerancia relativa del volumen según el paso de celda (m)."""
MIN_THICKNESS_M = float(res_provenance.VERIFY_MIN_THICKNESS_DEF.default)
"""El espesor mínimo de verificación de la 012 (0,02 m): ``res.verify.min_thickness_m``."""
FACE_TOLERANCE_DEG = float(next(item for item in params.DEFINITIONS
                                if item.key == params.TOLERANCE_FACE).default)


def run(steps: Any) -> Any:
    return list(steps)[-1].result


class Pit:
    """La corta de CE-013-09 calculada de punta a punta con un paso de celda y una métrica."""

    def __init__(self, step: float, metric: str) -> None:
        self.case = dfx.pit_case(step)
        profile = self.case.profile
        self.slope = envelopes.SlopeField(profile.general_tan)
        seeds = self.case.seeds()
        if metric == "chamfer5":
            found = run(envelopes.chamfer_steps(seeds, self.case.grid, self.slope, "up",
                                                name="corta"))
        else:
            found = run(envelopes.exact_steps(seeds, self.case.grid, self.slope, "up",
                                              name="corta"))
        self.envelope = found.grid
        tan_face = math.tan(math.radians(profile.face_deg))
        self.stairs = benching.bench_cut(self.envelope, profile.height_m, tan_face,
                                         profile.berm_m, profile.anchor_m)
        self.terrain = self.case.terrain()
        self.allowed = np.ones(self.terrain.shape, dtype=bool)
        self.design = compose.compose(self.terrain, self.stairs, self.allowed, "cut")
        self.report = run(report.report_steps(
            self.terrain, self.design, self.case.grid, self.allowed,
            min_thickness_m=MIN_THICKNESS_M, face_deg=profile.face_deg,
            face_tolerance_deg=FACE_TOLERANCE_DEG, warning_ratio=2.0))


class PitVolumeTest(unittest.TestCase):
    """CE-013-09: el volumen de la corta coincide con el analítico dentro de la tolerancia de D-8."""

    def test_analytic_volume_of_the_case_is_1_308_944(self) -> None:
        """El cálculo analítico de los datos de referencia es el de la spec, 1.308.944 m³."""
        self.assertAlmostEqual(dfx.pit_case(1.0).analytic_m3, ANALYTIC_M3, delta=0.5)

    def test_volume_is_within_the_tolerance_of_d8_with_both_metrics(self) -> None:
        """RF-013-22, RF-013-29, RF-013-30: ≤ 1 % con celdas de 1 m y ≤ 2 % con celdas de 2 m, con
        la envolvente *chamfer* 5×5 y con la exacta; todo es desmonte."""
        for step, tolerance in TOLERANCE_REL.items():
            for metric in ("chamfer5", "exact"):
                with self.subTest(celda_m=step, metrica=metric):
                    pit = Pit(step, metric)
                    relative = pit.report.cut_m3 / ANALYTIC_M3 - 1.0
                    self.assertLessEqual(abs(relative), tolerance)
                    self.assertEqual(pit.report.fill_m3, 0.0)
                    self.assertEqual(pit.report.fill_cells, 0)

    def test_report_volume_is_the_sum_of_the_cells(self) -> None:
        """El desmonte del informe es la suma celda a celda de ``terreno − diseño`` (con el
        espesor mínimo), por el área de celda, a ≤ 10⁻¹² relativo."""
        pit = Pit(1.0, "chamfer5")
        difference = pit.terrain - pit.design
        counted = difference[difference > MIN_THICKNESS_M]
        expected = math.fsum(counted.tolist()) * pit.case.grid.cell_area
        self.assertAlmostEqual(pit.report.cut_m3 / expected, 1.0, delta=1e-12)
        self.assertEqual(pit.report.cut_cells, counted.size)
        self.assertEqual(pit.report.moved_area_m2, counted.size * pit.case.grid.cell_area)

    def test_the_pit_is_the_circle_of_the_case(self) -> None:
        """La boca de la corta sale donde dice el cálculo analítico (111,84 m de radio): el área
        con movimiento es la del círculo de la boca dentro de ``±1 %`` con celdas de 1 m, y el
        fondo, a la cota 0."""
        pit = Pit(1.0, "chamfer5")
        mouth = math.pi * pit.case.top_radius_m ** 2
        self.assertAlmostEqual(pit.report.moved_area_m2 / mouth, 1.0, delta=0.01)
        self.assertEqual(float(pit.design.min()), 0.0)
        self.assertEqual(float(pit.design.max()), pit.case.terrain_z)

    def test_the_stairs_are_at_the_six_bench_levels(self) -> None:
        """RF-013-28: las bermas reales de la corta están en las cotas ``z₀ + n·h`` de los bancos
        (0 a 50 m; el último, a 60 m, es el terreno, sin movimiento), sin diferencia con el
        anclaje."""
        pit = Pit(1.0, "chamfer5")
        moved = report.moved_cells(pit.terrain, pit.design, MIN_THICKNESS_M)
        found = run(berms.berms_steps(pit.design, pit.case.grid, pit.case.profile.height_m,
                                      pit.case.profile.anchor_m,
                                      np.zeros(pit.design.shape, dtype=np.int16),
                                      (berms.BermScope("", pit.case.profile.code),),
                                      moved=moved))
        levels = [row.level_m for row in found.table]
        self.assertEqual(levels, [0.0, 10.0, 20.0, 30.0, 40.0, 50.0])
        self.assertTrue(all(row.anchor_diff_m == 0.0 for row in found.table))

    def test_no_slope_is_over_the_face_plus_the_tolerance(self) -> None:
        """Con la cara de 70° y la tolerancia de cara de 1°, la inclinación máxima de la corta
        no pasa de 71° y el informe no avisa de ninguna inclinación."""
        for step in TOLERANCE_REL:
            with self.subTest(celda_m=step):
                pit = Pit(step, "chamfer5")
                self.assertLessEqual(pit.report.slope_max_deg, 70.0 + FACE_TOLERANCE_DEG)
                self.assertGreater(pit.report.slope_max_deg, 60.0)
                self.assertNotIn("des.slope_over_face",
                                 [notice.code for notice in pit.report.notices])


if __name__ == "__main__":
    unittest.main()
