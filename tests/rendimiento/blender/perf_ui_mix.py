# SPDX-License-Identifier: GPL-3.0-or-later
"""Coste del panel de aspecto con 50 elementos seleccionados (spec 019, H1, T14b; RNF-019-01; plan 019 §7.3 y H-7).

La mezcla de la selección (el aspecto común, «varios valores») se recalcula a cada redibujo del editor de Propiedades: con 50
elementos de valores distintos, dibujar el panel de aspecto debe costar ≤ :data:`BUDGET_MS` (la mejor de cinco medianas de
cien dibujos, con la CPU en reposo). Antes de T14b eran 2,55 ms.

Se ejecuta con ``tools/check.py --rendimiento`` o con ``tools/run_blender_tests.py -- --carpeta
tests/rendimiento/blender --patron "perf_ui_mix.py"``.
"""

import unittest
from unittest import mock

import bpy

from tests.blender.test_ui_appearance_roundtrip import RoundtripCase, draw_ms, make_mix_objects
from tests.support import views_fixtures as vf

BUDGET_MS = 0.5


class UiMixCostTest(RoundtripCase):
    def test_50_element_mix_draw_cost(self) -> None:
        make_mix_objects(self.data.project.uid, [o.geoblender.dataset_uid for o in self.objs], 50)
        with mock.patch.object(vf.extension("bl.ui.labels"), "sidebar_width", return_value=1000.0):
            cost = draw_ms(bpy.types.GEOBLENDER_PT_ui_element_look)
        print(f"[RNF-019-01] panel de aspecto con 50 elementos seleccionados: {cost:.3f} ms (≤ {BUDGET_MS} ms)")
        self.assertLessEqual(cost, BUDGET_MS, f"{cost:.3f} ms")


if __name__ == "__main__":
    unittest.main()
