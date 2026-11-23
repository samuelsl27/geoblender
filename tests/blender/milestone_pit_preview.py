# SPDX-License-Identifier: GPL-3.0-or-later
"""El coste de la vista previa de una corta grande (spec 018, T29; RF-018-32; RNF-018-08; plan 018 §5.5 y §7.3), como prueba de **hito**: 60 bancos de 2 polilíneas de 2.000 vértices (pie y cresta) se
convierten en lotes en **≤ 1 s** («activarla») y el trabajo de cada redibujo que no es de ``gpu`` (colocar los nombres sobre la pantalla) es de **≤ 5 ms**. La parte de ``gpu`` no corre en
``blender -b`` (``docs/trampas.md`` §3): los lotes de ``gpu`` se crean una vez al dibujarlos y su coste es el de las demás vistas previas.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import time
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import numpy as np

from tests.support import blender_ext
from tests.support import pit_data as pd
from tests.support.blender_ext import module_name

ORIGIN = SimpleNamespace(x0=700_000, y0=4_400_000, z0=100)
BENCHES = 60
VERTICES = 2_000
ACTIVATE_S = 1.0
REDRAW_S = 0.005


def _module(name: str) -> Any:
    return importlib.import_module(f"{module_name()}.{name}")


def _no_ground(*_args: Any, **_kwargs: Any) -> Any:
    return None
    yield  # noqa: B901 - lo hace un generador


class PitPreviewScaleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        for name, module in (("entity", "bl.draw.entity"), ("pit", "bl.draw.pit"), ("constraints", "bl.draw.constraints"), ("dpreview", "design.preview"), ("model", "core.project.model"),
                             ("access", "gis.masks.access"), ("design_draw", "bl.draw.design")):
            setattr(cls, name, _module(module))

    def found(self) -> Any:
        rings = pd.scale_rings(BENCHES, BENCHES * 2 * VERTICES)
        lines = []
        for number in range(BENCHES):
            for offset, kind in enumerate(("foot", "crest")):
                ring = rings[2 * number + offset]
                z = np.full(len(ring), 100.0 + 10.0 * number + 10.0 * offset)
                lines.append(self.dpreview.PitLine(kind, number + 1, np.column_stack([ring + [ORIGIN.x0, ORIGIN.y0], z]), True))
        return self.dpreview.PitPreview("Corta grande", "PIT-001", "V01", self.access.MaskState.CURRENT, mode="up", start_surface="terreno", cell_m=1.0, calculated=True, polylines=tuple(lines),
                                        bench_numbers=tuple(range(1, BENCHES + 1)))

    def test_a_sixty_benches_of_two_polylines_are_activated_within_a_second_and_redrawn_within_five_ms(self) -> None:
        """RNF-018-08, RF-018-32: 60 bancos × 2 polilíneas × 2.000 vértices (240.000 tramos) se arman en ≤ 1 s, en lotes de la paleta (no uno por polilínea), y colocar los nombres de cada redibujo
        cuesta ≤ 5 ms."""
        found = self.found()

        def steps(*_args: Any, **_kwargs: Any) -> Any:
            return iter([self.model.Progress("preview_pit", 1, 1, "lista", result=found)])

        plan = self.entity.EntityPlan(pit=self.dpreview.PitAsk(request=object()))
        request = self.entity.Request(SimpleNamespace(origin=ORIGIN), "uid-v01", "V01", plan, "es", ("sello",))
        with mock.patch.object(self.dpreview, "pit_preview_steps", side_effect=steps), mock.patch.object(self.constraints, "ground_steps", side_effect=_no_ground):
            started = time.perf_counter()
            work = self.entity.build_steps(request)
            while True:
                try:
                    next(work)
                except StopIteration as done:
                    built = done.value
                    break
            spent = time.perf_counter() - started
        self.assertLess(spent, ACTIVATE_S, f"activarla tardó {spent:.2f} s")
        self.assertEqual(sum(batch.segments for batch in built.lines.batches), BENCHES * 2 * VERTICES)
        self.assertLessEqual(len(built.lines.batches), len(self.pit.BENCH_COLORS))
        matrix, size = np.eye(4), (1920.0, 1080.0)
        best = min(self._redraw(built, matrix, size) for _ in range(5))
        self.assertLess(best, REDRAW_S, f"el redibujo tardó {best * 1000:.2f} ms")

    def _redraw(self, built: Any, matrix: Any, size: tuple[float, float]) -> float:
        started = time.perf_counter()
        self.design_draw.screen_items(built, matrix, size, measure=lambda text: 8.0 * len(text), scale=1.0)
        return time.perf_counter() - started


if __name__ == "__main__":
    unittest.main()
