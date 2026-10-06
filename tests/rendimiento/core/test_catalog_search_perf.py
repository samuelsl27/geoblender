# SPDX-License-Identifier: GPL-3.0-or-later
"""Búsqueda de la línea de comandos en el catálogo, sin Blender (spec 003, T35;
RNF-003-07; plan 003 §5.4, 10 y §7).

Se ejecuta con ``tools/check.py --rendimiento`` (el Python de Blender, fuera de Blender).
La lista que ve la persona dentro de Blender (con dónde está cada comando) la mide
``tests/rendimiento/blender/perf_ui_draw_cost.py``.

- RNF-003-07: ``core.catalog.search.search`` con el catálogo completo (≥ 350 comandos)
  tarda ≤ 20 ms por consulta, la primera (que construye el índice) incluida.
"""

import statistics
import sys
import time
import unittest

from tests.support.package import import_geoblender

catalog = import_geoblender("core.catalog")
search = import_geoblender("core.catalog.search")

BUDGET_MS = 20.0
QUERIES = ("cubicar", "volume", "R-38", "r38", "005", "planta", "sondeos", "ns", "v", "T3",
           "exportar a dxf", "ventana de trabajo")


def _ms(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


class SearchSpeedTest(unittest.TestCase):
    def test_query_under_20_ms(self) -> None:
        """RNF-003-07: ≤ 20 ms por consulta con el catálogo completo."""
        cat = catalog.load()
        self.assertGreaterEqual(len(cat.commands), 350)
        times: list[float] = []
        for language in ("es", "en"):
            for query in QUERIES:
                for _ in range(10):
                    start = time.perf_counter()
                    search.search(cat, query, language=language, is_available=lambda _k: True)
                    times.append((time.perf_counter() - start) * 1000.0)
        print(f"RNF-003-07: búsqueda de F10 ({len(cat.commands)} comandos, "
              f"{len(QUERIES)} consultas × 2 idiomas × 10): mediana "
              f"{_ms(statistics.median(times))} ms, máximo {_ms(max(times))} ms "
              f"(≤ {_ms(BUDGET_MS)} ms)", file=sys.stderr, flush=True)
        self.assertLessEqual(max(times), BUDGET_MS)


if __name__ == "__main__":
    unittest.main()
