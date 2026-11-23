# SPDX-License-Identifier: GPL-3.0-or-later
"""La vista previa de la corta con el proyecto (spec 018, T29; HU-018-1, HU-018-4; RF-018-32, RF-015-26, RF-015-08; plan 018 §5.5; comprobación manual M3), como prueba de **hito**: ``check.py
--completo`` la ejecuta; el «verde» tiene los datos puros en ``test_pit_preview_data`` y lo que se dibuja en ``tests/blender/test_pit_preview.py``.

Sobre el proyecto de las cortas (rejilla de 2 m) con la corta ascendente ``Corta del fondo`` de V01 (:class:`PreviewCase`):

- **Antes de calcular** (a): la vista previa de la petición lee y **no escribe** (ni base ni ficheros), enseña el polígono de fondo con su cota y el resumen; lo que rechazaría «Calcular» es
  ``refusal``; con las máscaras sin compilar, el aviso.
- **Tras calcular** (b): con lo que dejó «Calcular», las polilíneas, la línea de cielo, las rampas y los hallazgos **son los del resultado** (mismos vértices), con los bancos y el corte.
- **De una corta de la versión** (c): por su código, sus datos guardados dan las mismas polilíneas y la misma línea de cielo que el resultado; una sin calcular lo dice; un código que no es de una
  corta, ``ValueError``.
- **Cerrar a mitad** (d) no deja nada.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from tests.support.package import import_geoblender
from tests.unit.design.milestone_pit_create import BY, NAME
from tests.unit.design.milestone_pit_prepare_checks import request
from tests.unit.design.milestone_pit_recompute import RecomputeCase

access = import_geoblender("gis.masks.access")
design_preview = import_geoblender("design.preview")


def last(work: Any) -> Any:
    found = None
    for step in work:
        found = step.result if step.result is not None else found
    return found


class PreviewCase(RecomputeCase):
    def preview(self, ask: Any) -> Any:
        return last(design_preview.pit_preview_steps(self.project, ask, self.v1.uid))


class PitPreviewProjectTest(PreviewCase):
    """RF-018-32: lo que dice la vista previa de una corta con el proyecto, en orden."""

    def test_a_before_calculating_it_reads_and_writes_nothing(self) -> None:
        """RF-018-32, RF-015-03, RF-015-26: antes de calcular, el polígono de fondo con su cota, el resumen y **nada escrito**; un perfil que no existe es ``refusal`` y no hay dibujo."""
        before = self.snapshot()
        found = self.preview(design_preview.PitAsk(request=request()))
        self.assertEqual(self.snapshot(), before, "la vista previa ha escrito algo")
        self.assertEqual((found.name, found.mode, found.calculated, found.refusal), (NAME, "up", False, None))
        self.assertTrue(found.drawable)
        (source,) = found.sources
        self.assertEqual(source.level_m, 125.0)
        self.assertIn("no se calcula ni se escribe nada", " ".join(text for text, _alert in found.lines("es")))
        refused = self.preview(design_preview.PitAsk(request=request(profile="no_existe")))
        self.assertIsNotNone(refused.refusal)
        self.assertFalse(refused.drawable)
        self.assertTrue(refused.lines("es")[0][1])

    def test_b_after_calculating_the_drawing_is_the_result(self) -> None:
        """RF-018-32, RF-018-26: con la preparación y el resultado de «Calcular», las polilíneas, la línea de cielo, las rampas y los hallazgos son los del resultado y los bancos son 1 a 5."""
        calc = self.calculate(request())
        found = self.preview(design_preview.PitAsk(request=request(), prepared=calc.entity, outcome=calc.outcome, by="type"))
        self.assertTrue(found.calculated)
        self.assertEqual(found.by, "type")
        self.assertEqual(len(found.polylines), len(calc.outcome.polylines))
        for shown, kept in zip(found.polylines, calc.outcome.polylines, strict=True):
            np.testing.assert_array_equal(shown.vertices, kept.vertices)
            self.assertEqual((shown.kind, shown.bench), (str(kept.kind.value), kept.bench))
        self.assertEqual(len(found.skyline), len(calc.outcome.skyline))
        self.assertEqual(found.findings, tuple(calc.outcome.findings))
        self.assertEqual(found.bench_numbers, tuple(sorted({item.bench for item in calc.outcome.polylines})))
        self.assertGreater(found.cut_m3 or 0.0, 0.0)

    def test_c_a_pit_of_the_version_by_its_code_gives_what_is_stored(self) -> None:
        """RF-018-32, RF-015-26: de la corta ya creada, por su código, las polilíneas y la línea de cielo guardadas son las del resultado (mismos vértices); un código que no es de una corta es un
        error."""
        calc = self.calculate(request())
        self.clock.advance(minutes=1)
        stored = calc.create(decided_by=BY)
        self.assertTrue(stored.handle.uid)
        found = self.preview(design_preview.PitAsk(code="PIT-001"))
        self.assertTrue(found.calculated)
        self.assertEqual(len(found.polylines), len(calc.outcome.polylines))
        by_key = {(item.kind, item.bench): item for item in found.polylines}
        for kept in calc.outcome.polylines:
            np.testing.assert_array_equal(by_key[(str(kept.kind.value), kept.bench)].vertices, kept.vertices)
        self.assertEqual(len(found.skyline), len(calc.outcome.skyline))
        self.assertEqual(len(found.findings), len(calc.outcome.findings))
        with self.assertRaises(ValueError):
            self.preview(design_preview.PitAsk(code="PLT-001"))

    def test_d_closing_the_steps_midway_leaves_nothing(self) -> None:
        """RF-015-26: cerrar los pasos a mitad no escribe nada."""
        before = self.snapshot()
        work = design_preview.pit_preview_steps(self.project, design_preview.PitAsk(request=request()), self.v1.uid)
        next(work)
        work.close()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(access.mask_state(self.project, self.v1.uid)[0], access.MaskState.CURRENT)
