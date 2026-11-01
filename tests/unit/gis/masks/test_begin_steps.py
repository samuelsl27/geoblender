# SPDX-License-Identifier: GPL-3.0-or-later
"""Empezar a compilar por pasos cortos también tras cambiar un resguardo (spec 012, T31;
RNF-012-06; plan 012 §5.2.3, D-43).

Medido con las órdenes reales en Blender
(``tests/rendimiento/blender/perf_constraints.py``), con las 500 restricciones de §2.2: compilar
otra vez tras cambiar el resguardo de una restricción, o verificar con las máscaras obsoletas (la
orden las compila antes, D-43), dejaba una llamada del hilo de Blender de más de 0,2 s al empezar:
``gather`` leía de una vez las zonas de la compilación anterior (182.753 filas) y
``ensure_masks_steps`` empezaba la operación al llamar. **Sin cambiar ningún resultado**, aquí se
fija lo que lo arregla, de forma rápida:

- **RNF-012-06** (``gather_steps``): lee las zonas anteriores por trozos de filas
  (``zone_runs_steps``) y da la misma entrada que ``gather``: las zonas y los polígonos anteriores
  de las restricciones que cambian y la operación a la que sustituye.
- **RNF-012-06, D-43** (``ensure_masks_steps``): con las máscaras obsoletas, llamar no lee ni
  registra nada; empieza la operación después de varios pasos (los de ``begin_compile_steps``) y da
  al final las mismas máscaras que compilar de una vez. Un rechazo (sin límite legal activo) sale
  al avanzar, sin registrar nada.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

from tests.support import constraints_project as cp
from tests.support.package import import_geoblender

access = import_geoblender("gis.masks.access")
provenance = import_geoblender("gis.masks.provenance")
store = import_geoblender("gis.masks.store")
cparams = import_geoblender("core.constraints.params")
cmessages = import_geoblender("core.constraints.messages")
params = import_geoblender("core.params")

BUDGET_S = 0.05


class BeginStepsTest(cp.ConstraintsProjectCase):
    """V01 compilada y con el resguardo de la torre cambiado solo en V01 (obsoleta)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        for _step in access.ensure_masks_steps(cls.project, cls.v1.uid, budget_s=BUDGET_S):
            pass
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            params.ParameterStore(cls.project).change(
                conn, cparams.buffer_out_key("torre"), value=7.0, reason="Prueba de los pasos",
                version=cls.v1.code)

    def operations(self) -> int:
        return int(self.query("SELECT count(*) FROM gb_operation WHERE op_type = ?",
                              provenance.COMPILE)[0][0])

    def test_a_gather_reads_the_previous_zones_in_pieces(self) -> None:
        """RNF-012-06: tras cambiar un resguardo, ``gather_steps`` lee las zonas de la compilación
        anterior por trozos de filas (más trozos con menos filas por unidad) y da lo mismo que
        ``gather``: la torre como forma anterior con sus tramos, y la operación a la que
        sustituye."""
        self.assertIs(access.mask_state(self.project, self.v1.uid)[0], access.MaskState.STALE)

        def run(rows: int) -> tuple[int, Any]:
            with mock.patch.object(store, "_ZONE_ROWS_PER_UNIT", rows):
                steps = store.gather_steps(self.project, version=self.v1.uid)
                count = 0
                while True:
                    try:
                        next(steps)
                    except StopIteration as stop:
                        return count, stop.value
                    count += 1

        coarse, whole = run(100_000)
        fine, pieces = run(5)
        self.assertGreater(fine, coarse + 3)
        self.assertGreater(coarse, 1)  # ni siquiera de una vez: la lectura, lo anterior, …
        once = store.gather(self.project, version=self.v1.uid)
        for found in (whole, pieces, once):
            self.assertIsNotNone(found.request.previous)
            self.assertEqual(set(found.request.previous.changed), {"torre"})
            self.assertEqual(found.supersedes, once.supersedes)
            self.assertEqual(found.version_uid, self.v1.uid)
        before = once.request.previous.changed["torre"]
        self.assertIsNotNone(before)
        self.assertGreater(before.runs.cells, 0)
        for found in (whole, pieces):
            self.assertEqual(found.request.previous.settings(), once.request.previous.settings())

    def test_b_ensure_masks_steps_begins_in_steps_when_stale(self) -> None:
        """RNF-012-06, D-43: pedir las máscaras obsoletas no lee ni registra nada al llamar; la
        operación empieza después de varios pasos y se compila lo mismo que de una vez."""
        known = self.operations()
        steps = access.ensure_masks_steps(self.project, self.v1.uid, budget_s=BUDGET_S)
        self.assertEqual(self.operations(), known)  # llamar no empieza la operación
        before_start = 0
        masks = None
        for step in steps:
            if self.operations() > known:
                break
            before_start += 1
            self.assertIsNone(step.result)
        self.assertGreater(before_start, 2)  # leer, comprobar cada restricción y cada polígono…
        self.assertEqual(self.operations(), known + 1)
        for step in steps:
            if step.result is not None:
                masks = step.result
        self.assertIs(masks.state, access.MaskState.CURRENT)
        self.assertEqual(self.operations(), known + 1)
        self.assertEqual(access.load_masks(self.project, self.v1.uid).operation_uid,
                         masks.operation_uid)

    def test_c_a_rejection_comes_on_advancing_and_registers_nothing(self) -> None:
        """RNF-012-06, D-43 (RF-012-15): sin límite legal activo en V02, llamar no rechaza ni
        registra nada; al avanzar sale el mismo rechazo de compilar, sin registrar la
        operación."""
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            params.ParameterStore(self.project).create(
                conn, cparams.active_key("concesion"), False, kind="ADOPTADO",
                **cp.PARAMS_BY_HAND, reason="Prueba de los pasos", version=self.v2.code)
        known = self.operations()
        steps = access.ensure_masks_steps(self.project, self.v2.uid, budget_s=BUDGET_S)
        with self.assertRaises(cmessages.ConstraintError) as caught:
            for _step in steps:
                pass
        self.assertEqual(caught.exception.code, "core.constraint_no_legal_limit")
        self.assertEqual(self.operations(), known)


if __name__ == "__main__":
    unittest.main()
