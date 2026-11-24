# SPDX-License-Identifier: GPL-3.0-or-later
"""Tiempo de habilitar la extensión dentro de Blender (RNF-001-03; plan 001 §5.4.9).

Se ejecuta con ``tools/check.py --rendimiento`` o, a mano, con
``tools/run_blender_tests.py -- --carpeta tests/rendimiento/blender --patron "perf_*.py"``.
Cada ciclo parte de la extensión fuera de ``sys.modules`` (importación en frío), mide
``addon_utils.enable`` con ``time.perf_counter()`` y la deshabilita.
"""

import statistics
import sys
import time
import unittest

from tests.support import blender_ext

CYCLES = 3
BUDGET_S = 0.57  # RNF-001-03 (spec 001 0.13, DIFF-001a): mediana ≤ 0,57 s (≈ 0,55 s medido ± 0,02 s)


def _seconds(value: float) -> str:
    """Segundos con tres decimales y coma decimal (salida en español)."""
    return f"{value:.3f}".replace(".", ",")


class RegistrationSpeedTest(unittest.TestCase):
    def test_enable_under_half_second(self) -> None:
        """RNF-001-03: habilitar Geoblender en segundo plano tarda ≤ 0,57 s (mediana de
        3 ciclos; spec 001 0.13)."""
        times: list[float] = []
        try:
            for _ in range(CYCLES):
                blender_ext.unload()
                start = time.perf_counter()
                blender_ext.enable()
                times.append(time.perf_counter() - start)
                blender_ext.disable()
        finally:
            blender_ext.unload()
        median = statistics.median(times)
        print(
            f"RNF-001-03: habilitar Geoblender, mediana de {CYCLES} ciclos: "
            f"{_seconds(median)} s ({'; '.join(_seconds(value) for value in times)} s)",
            file=sys.stderr,
            flush=True,
        )
        self.assertLessEqual(median, BUDGET_S)


if __name__ == "__main__":
    unittest.main()
