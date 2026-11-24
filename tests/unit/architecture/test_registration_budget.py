# SPDX-License-Identifier: GPL-3.0-or-later
"""El límite de habilitar Geoblender es el de la spec 001 0.13 (RNF-001-03, DIFF-001a).

Habilitar la extensión en Blender 5.2.1 en segundo plano tarda ≤ 0,57 s (mediana de 3 ciclos):
el valor medido en reposo (≈ 0,55 s) con un margen de ±0,02 s. Samuel (IMGA) lo decidió el
24/11/2026, porque desde la spec 015 el límite anterior (0,5 s) ya no se cumplía y cada spec
añade ≈ 15 ms; reducirlo con imports perezosos queda como mejora futura. Esta prueba, sin Blender,
fija la constante de ``tests/rendimiento/blender/perf_registration.py``: si vuelve a 0,5 s o se
sube sin un diff aprobado de la spec 001, falla.
"""

from __future__ import annotations

import ast
import unittest

from tests.support.repo import ROOT

PERF = ROOT / "tests" / "rendimiento" / "blender" / "perf_registration.py"
RNF_001_03_BUDGET_S = 0.57  # spec 001 0.13


class RegistrationBudgetTest(unittest.TestCase):
    def test_budget_is_the_approved_limit(self) -> None:
        tree = ast.parse(PERF.read_text(encoding="utf-8"))
        values = [
            node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "BUDGET_S" for t in node.targets)
            and isinstance(node.value, ast.Constant)
        ]
        self.assertEqual(values, [RNF_001_03_BUDGET_S])


if __name__ == "__main__":
    unittest.main()
