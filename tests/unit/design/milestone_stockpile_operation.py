# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que quedará obsoleto al crear una detección de acopios (spec 016, T12; HU-016-1; RF-015-03, RF-015-13, RF-015-16,
RF-016-10; plan 016 §5.3.2 y §5.7 P-2): el hito de ``test_stockpile_operation`` (casos (a)).

Sobre la cantera de los acopios (rejilla gruesa de 2 m, V01), con operaciones **sintéticas** que hacen de lo que una detección
deja y de lo que depende de ella (cada una registra su operación con lo que lee y escribe una tabla de juguete, como
``test_platform_operation.ObsoleteCase``): una detección previa **de una versión** y otra **del proyecto**, y, de lo que se les apoya,
una operación en V01, otra del proyecto y una que consume lo que escribió la primera (la cascada). «Calcular» una detección que
**sustituye** a la previa dice, en el resumen y sin escribir nada, lo que quedará obsoleto: con el mecanismo de la 015 (la
operación vigente, en cascada, sin la propia sustituida); si es de una versión, las de esa versión; si es del proyecto, las del
proyecto y las de cualquier versión (una versión puede consumir un dato del proyecto, no al revés, RF-009-05). Una detección
que no sustituye nada no deja obsoleto nada. Va al paso «hito» (P-13): tres proyectos de operaciones sintéticas sobre la rejilla
de 2 m.
"""

from __future__ import annotations

import unittest
from collections.abc import Sequence
from typing import Any, ClassVar

from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.unit.design import test_stockpile_operation as ops
from tests.unit.design import test_stockpile_prepare as tp

builtin = import_geoblender("core.content.builtin")
contract = import_geoblender("core.provenance.contract")
datasets = import_geoblender("core.datasets.model")
gpkg_base = import_geoblender("core.gpkg.base")
operations = import_geoblender("core.provenance.operations")
preview = import_geoblender("design.preview")
provenance = import_geoblender("design.provenance")
steps = import_geoblender("design.steps")
versions_model = import_geoblender("core.versions.model")

PREVIOUS_VERSION, PREVIOUS_PROJECT = "des.probe_detection", "des.probe_detection_project"
CONSUMER_VERSION, CONSUMER_PROJECT = "des.probe_consumer", "des.probe_consumer_project"
"""Los tipos de operación de prueba: lo que deja una detección (de una versión y del proyecto) y lo que depende de ella."""
USER = "Samuel (IMGA)"


class ObsoleteCase(tp.PrepareCase):
    """V01 de la cantera de los acopios con los tipos de operación de prueba registrados y ``made``, que registra una operación
    sintética (lo que lee y una tabla de juguete que escribe) en V01 o en el proyecto."""

    uids: ClassVar[dict[str, str]]
    written: ClassVar[dict[str, str]]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        definitions = [contract.OperationDef(op_type, "1.0", "des", "Operation of the tests", False, scope=scope)
                       for op_type, scope in ((PREVIOUS_VERSION, "version"), (CONSUMER_VERSION, "version"),
                                              (PREVIOUS_PROJECT, "project"), (CONSUMER_PROJECT, "project"))]
        cls.enterClassContext(registered(*definitions))
        cls.uids, cls.written = {}, {}

    @classmethod
    def made(cls, key: str, op_type: str, reads: Sequence[str] = (), *, version: bool = True) -> str:
        """Registra la operación ``key`` de ``op_type`` (de V01 si ``version`` y si no, del proyecto): lee los datos ``reads`` y
        escribe una tabla de juguete (su nombre, en ``written[key]``); su uid queda en ``uids[key]``."""
        cls.clock.advance(minutes=1)
        label = f"des_probe_{len(cls.uids) + 1}"
        handle = operations.begin_operation(
            cls.project, op_type, settings={"name": key},
            inputs=[operations.Use(name, "surface") for name in reads], executor="blender",
            version=cls.v1.uid if version else None)
        locator = versions_model.version_locator(label, cls.v1.code) if version else label
        with cls.project.write_transaction() as conn:
            gpkg_base.create_attribute_table(conn, locator, [gpkg_base.ColumnDef("value", "DOUBLE")], label,
                                             "Dato sintético de la prueba de la T12 (spec 016)")
            conn.execute(f'INSERT INTO "{locator}" (value) VALUES (1.0)')
            handle.complete(conn, outputs=[datasets.DatasetSpec(
                label, "des", "table", datasets.Store.GPKG, locator, reader=builtin.GPKG_LAYER.id,
                role="entity_surface")])
        cls.uids[key], cls.written[key] = str(handle.uid), label
        return str(handle.uid)

    def calculate(self, asked: Any, **options: Any) -> Any:
        """«Calcular» ``asked`` hasta el final: la ``Calculation``, que se descarta al acabar."""
        options.setdefault("masks", self.masks_v1)
        options.setdefault("version", self.v1.uid)
        calculation = ops.last(steps.stockpile_run(self.project, asked, **options))
        self.addCleanup(calculation.discard)
        return calculation


class VersionDetectionTest(ObsoleteCase):
    """RF-015-03, RF-016-10, RF-015-16: lo que dependía de una detección **de V01** queda obsoleto, con la cascada."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made("previa", PREVIOUS_VERSION)
        cls.made("retirada A", CONSUMER_VERSION, [cls.written["previa"]])
        cls.made("retirada B", CONSUMER_VERSION, [cls.written["retirada A"]])
        cls.made("sin relación", CONSUMER_VERSION, [])

    def test_what_depended_on_the_replaced_detection_is_listed_in_cascade_without_writing(self) -> None:
        """RF-015-03, RF-016-10, RF-015-16: «Calcular» la detección que **sustituye** a la previa de V01 dice en el resumen
        que quedan obsoletas las dos operaciones que dependían de ella —la que lee lo que escribió y la que lee lo de esa— con
        sus nombres entre «» y sin la sustituida ni la que no tiene relación; es una nota (no un aviso), al final, con su
        cuenta; y no escribe nada."""
        before = self.state()
        calculation = self.calculate(tp.request(surface=tp.VERSION_SURFACE), supersedes=self.uids["previa"])
        self.assertEqual(self.state(), before)
        summary = calculation.summary
        self.assertEqual([(item.kind, item.name, item.op_type, item.uid) for item in summary.obsolete],
                         [(preview.ObsoleteKind.DEPENDENT, "retirada A", CONSUMER_VERSION, self.uids["retirada A"]),
                          (preview.ObsoleteKind.DEPENDENT, "retirada B", CONSUMER_VERSION, self.uids["retirada B"])])
        last = summary.notices[-1]
        self.assertEqual(last.code, "des.stockpile_obsolete_dependents")
        self.assertEqual((last.values["entity"], last.values["operations"]), ("Acopios", 2))
        self.assertEqual(last.severity, "note")
        for part in ("«Acopios»", "2 operaciones", "«retirada A»", "«retirada B»"):
            self.assertIn(part, last.text("es"))
        self.assertNotIn("sin relación", last.text("es"))
        self.assertEqual(calculation.notices, summary.notices)
        calculation.discard()
        self.assertEqual(self.state(), before)

    def test_a_detection_that_replaces_nothing_makes_nothing_stale(self) -> None:
        """RF-015-03: sin operación que sustituir (la primera detección o una nueva), el resumen no dice nada obsoleto."""
        summary = self.calculate(tp.request(surface=tp.VERSION_SURFACE)).summary
        self.assertEqual(summary.obsolete, ())
        self.assertNotIn("des.stockpile_obsolete_dependents", ops.codes(summary))

    def test_an_operation_with_nothing_depending_on_it_is_not_a_dependency(self) -> None:
        """RF-015-16: sustituir la operación de la que nadie depende no deja obsoleto nada (la que no tiene relación)."""
        summary = self.calculate(tp.request(surface=tp.VERSION_SURFACE), supersedes=self.uids["sin relación"]).summary
        self.assertEqual(summary.obsolete, ())

    def test_one_dependent_is_told_in_the_singular(self) -> None:
        """RF-015-13, RF-015-24 (spec 014, T60): con una sola operación que depende, el resumen dice «1 operación» y «1
        operation», no «1 operaciones»."""
        summary = self.calculate(tp.request(surface=tp.VERSION_SURFACE), supersedes=self.uids["retirada A"]).summary
        self.assertEqual([item.name for item in summary.obsolete], ["retirada B"])
        note = summary.notices[-1]
        self.assertIn("quedará obsoleta 1 operación", note.text("es"))
        self.assertIn("1 operation that", note.text("en"))


class ProjectDetectionTest(ObsoleteCase):
    """RF-015-03, RF-016-10, RF-015-16, D-15, RF-009-05: lo que dependía de una detección **del proyecto** queda obsoleto en el
    proyecto y en cualquier versión."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made("previa del proyecto", PREVIOUS_PROJECT, version=False)
        cls.made("cubicación", CONSUMER_PROJECT, [cls.written["previa del proyecto"]], version=False)
        cls.made("retirada en V01", CONSUMER_VERSION, [cls.written["previa del proyecto"]])
        cls.made("informe", CONSUMER_PROJECT, [cls.written["cubicación"]], version=False)

    def test_what_depended_on_a_project_detection_is_listed_in_the_project_and_in_the_versions(self) -> None:
        """RF-015-03, RF-016-10, D-15: la detección **del proyecto** (una superficie del proyecto, sin versión activa) que
        sustituye a la previa del proyecto deja obsoleto lo que la usaba: una operación del proyecto (la cubicación), una de
        V01 (una versión puede consumir un dato del proyecto) y, en cascada, lo que usó lo de la cubicación; por orden de
        registro y sin la sustituida; la nota dice «del proyecto» sin llamar a ninguna versión; y no escribe nada."""
        before = self.state()
        calculation = self.calculate(tp.request(), version=None, masks=None, supersedes=self.uids["previa del proyecto"])
        self.assertEqual(self.state(), before)
        self.assertEqual(calculation.op_type, provenance.STOCKPILE_DETECT_PROJECT)
        summary = calculation.summary
        self.assertEqual([(item.name, item.op_type) for item in summary.obsolete],
                         [("cubicación", CONSUMER_PROJECT), ("retirada en V01", CONSUMER_VERSION),
                          ("informe", CONSUMER_PROJECT)])
        self.assertTrue(all(item.label == "" for item in summary.obsolete))
        note = summary.notices[-1]
        self.assertEqual((note.code, note.values["operations"]), ("des.stockpile_obsolete_dependents", 3))
        for part in ("3 operaciones", "«cubicación»", "«retirada en V01»", "«informe»"):
            self.assertIn(part, note.text("es"))
        self.assertEqual((summary.version, summary.scope), (None, "project"))
        calculation.discard()
        self.assertEqual(self.state(), before)


if __name__ == "__main__":
    unittest.main()
