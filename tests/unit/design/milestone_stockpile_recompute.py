# SPDX-License-Identifier: GPL-3.0-or-later
"""Recalcular la detección de acopios y reproducirla desde lo congelado (spec 016, T14; HU-016-1; RF-016-10, RF-015-02,
RF-015-04, RF-015-16, RF-009-11; CE-016-01; plan 016 §5.1, §5.3.1 y §8): el hito de ``milestone_stockpile_detection`` (casos (d) y
(e): lo ligero está en ``RecomputeTest``). Va al paso «hito» (P-13): proyectos de 2 m con congelar y reproducir, y varias
detecciones recalculadas.

- **Reproducir** (:class:`ReproduceTest`): la detección de V01 con candidatos y **decisiones** (un candidato convertido en
  acopio y otro descartado), recalculada y congelada en ``V01.r1``: reproducirla **sin proyecto**, desde la capa de marcas, la
  superficie, las bases y las máscaras congeladas y los parámetros congelados, da de cada dato —la tabla de acopios, la de
  candidatos, la base y el espesor de cada material, el terreno sin acopios, la superficie con que se detectó y el informe— el
  **mismo hash** que registró la operación y las mismas cifras, **sin escribir nada** en el proyecto; y cambiar el umbral y
  recalcular **después** de congelar no marca nada de lo congelado (la revisión sigue congelada y se reproduce otra vez igual).
- **Lo que deja obsoleta la operación entera** (:class:`StaleTest`, :class:`FieldEditTest` y :class:`DependentsTest`,
  CE-016-01): la geometría de la capa de marcas (con su causa: el dato de la capa), el campo de una marca (que se aplica al
  recalcular, no es un parámetro de la entidad) y lo que depende de lo que escribió la detección **del proyecto**, en el
  proyecto y en una versión (RF-009-05), que queda obsoleto con su causa.
- **Lo que impide recalcular** (:class:`RefusalTest` y :class:`ScopeTest`): un parámetro o una entrada que cambian entre
  prepararlo y empezar la operación (``des.input_changed``: la operación nueva queda fallida y la anterior, vigente); y una
  superficie que cambió de ámbito (``des.stockpile_scope_changed``: no se empieza nada).
"""

from __future__ import annotations

import dataclasses
import unittest
from typing import Any, ClassVar
from unittest import mock

from tests.support import design_fixtures as dfx
from tests.support import res_fixtures
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.versions_fixtures import change_counter, files
from tests.unit.design import milestone_stockpile_detection as ops
from tests.unit.design import milestone_stockpile_operation as mso
from tests.unit.design import milestone_stockpile_prepare as tp

builtin = import_geoblender("core.content.builtin")
contract = import_geoblender("core.provenance.contract")
datasets = import_geoblender("core.datasets.model")
core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
design_reproduce = import_geoblender("design.reproduce")
freeze = import_geoblender("core.versions.freeze")
gis = import_geoblender("gis")
gis_store = import_geoblender("gis.store")
messages = import_geoblender("design.messages")
operations = import_geoblender("core.provenance.operations")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
reproduce_mod = import_geoblender("core.versions.reproduce")
store = import_geoblender("design.store")
stockpile_store = import_geoblender("design.stockpile_store")
stockpiles = import_geoblender("design.stockpiles")

CODE = ops.CODE
USER = ops.USER
THRESHOLD_KEY = ops.THRESHOLD_KEY
SURFACE_KEY = design_params.entity_key(CODE, "surface")
FROZEN_THRESHOLD = 0.45
"""El umbral de la huella con que se congela la detección de :class:`ReproduceTest` (no el de por defecto, 0,30 m)."""


def rewrite_marks(project: Any, clock: Any, *, move_first: float = 0.0, margins: dict[str, float] | None = None) -> None:
    """Cambia la capa de marcas como al editarla en QGIS y volver a registrarla (el contenido nuevo del mismo dato): desplaza
    ``move_first`` m al este el polígono de la primera marca y pone el ``margen`` de las marcas de ``margins``."""
    srs = int(project.record.crs_epsg)
    with project.read() as conn:
        found = gis_store.read_features(conn, sdata.MARKS_LAYER)
    shift = [move_first, 0.0]
    parts = tuple(tuple(tuple(ring + shift if index == 0 else ring for ring in part) for part in entity)
                  for index, entity in enumerate(found.parts))
    rows = gis_store.feature_rows(type(found)(found.kind, found.fids, parts, found.columns, found.values), srs)
    writer = contract.OperationDef(dfx.LAYERS_TYPE, "1.0", "gis", "Layers of the tests", False)
    with registered(writer):
        clock.advance(minutes=1)
        handle = operations.begin_operation(project, dfx.LAYERS_TYPE, settings={"name": sdata.MARKS_LAYER},
                                            executor="blender")
        with project.write_transaction() as conn:
            if move_first:
                for row in rows:
                    conn.execute(f'UPDATE "{sdata.MARKS_LAYER}" SET geom = ? WHERE fid = ?', (row[1], row[0]))
            for name, margin in (margins or {}).items():
                conn.execute(f'UPDATE "{sdata.MARKS_LAYER}" SET "margen" = ? WHERE nombre = ?', (margin, name))
            handle.complete(conn, outputs=(datasets.DatasetSpec(
                sdata.MARKS_LAYER, "gis", "vector", datasets.Store.GPKG, sdata.MARKS_LAYER, reader=builtin.GPKG_LAYER.id,
                role="features", crs_epsg=srs, input_uid=None, immutable=False),), message="Capa de marcas editada")


class ReproduceTest(ops.RecomputeCase):
    """RF-016-10, RF-015-02, RF-015-04, RF-009-11, RF-009-19: la detección de V01 con candidatos y decisiones (``c03`` convertido,
    ``c05`` descartado), recalculada con ellas y congelada en ``V01.r1``."""

    revision: ClassVar[str]
    uid: ClassVar[str]

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        """Los tipos de la detección con sus funciones reales de recalcular y de reproducir (las que registra ``bl``)."""
        return tuple(provenance.OPERATION_TYPES_BY_NAME[op_type].definition(
            ops.recompute_function, design_reproduce.reproduce_stockpile_detect)
            for op_type in provenance.STOCKPILE_DETECT_TYPES)

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.create(tp.request(surface=tp.VERSION_SURFACE, candidates=True))
        stockpile_store.decide_candidate(cls.project, CODE, "c03", "converted", "Es un acopio de mineral", version=cls.v1,
                                         decided_by=USER)
        stockpile_store.decide_candidate(cls.project, CODE, "c05", "discarded", "Es una escombrera antigua", version=cls.v1,
                                         decided_by=USER)
        with cls.project.write_transaction() as conn:  # lo congelado se calculó con otro umbral que el de por defecto
            core_params.ParameterStore(cls.project).change(
                conn, THRESHOLD_KEY, value=FROZEN_THRESHOLD, source="prueba de reproducir (T14)", source_kind="person",
                decided_by=USER, reason="Se congela con otro umbral")
        cls.clock.advance(minutes=1)
        again = ops.finish(recompute_mod.recompute_steps(cls.project))
        assert [result.status for result in again.results] == [recompute_mod.UnitStatus.DONE]
        cls.uid = str(again.results[0].operations[0])
        cls.clock.advance(minutes=1)
        frozen = ops.finish(freeze.freeze_steps(cls.project, cls.v1.uid, reason="Entrega de la prueba"))
        cls.revision = str(frozen.frozen.uid)
        cls.clock.advance(minutes=1)

    def reproduce(self) -> Any:
        """La reproducción de V01.r1, comprobando que **no escribió** nada en el proyecto (los ficheros y el contador de
        cambios de la base, sin la caché donde reproduce)."""
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = ops.finish(reproduce_mod.reproduce_steps(self.project, self.revision))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root)), before,
                         "reproducir no escribe en el proyecto")
        return report

    def written(self, uid: str) -> list[tuple[str, str]]:
        """Lo que escribió la operación ``uid``: ``(papel, nombre)`` de cada dato, en su orden."""
        return [(role, name) for role, name in self.query(
            "SELECT io.role, d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'out' AND io.item_kind = 'dataset' ORDER BY io.fid", uid)]

    def assert_same(self, report: Any) -> None:
        """La detección reprodujo cada dato que escribió (el mismo papel y nombre, en su orden) y cada cifra, todos iguales."""
        mine = [check for check in report.outputs if check.operation_uid == self.uid]
        self.assertEqual([(check.role, check.name) for check in mine], self.written(self.uid))
        self.assertEqual(len(mine), 11, "siete familias, con la base y el espesor de tres materiales")
        self.assertTrue(all(check.same for check in mine), [check for check in mine if not check.same])
        found = [check for check in report.figures if check.operation_uid == self.uid]
        self.assertEqual(len(found), len(self.figures_of(self.uid)))
        self.assertGreater(len(found), 20)
        self.assertTrue(all(check.same for check in found), [check for check in found if not check.same])
        self.assertFalse(report.not_reproducible)
        self.assertTrue(report.matches)

    def test_a_reproducing_the_frozen_revision_gives_the_same_without_writing(self) -> None:
        """RF-016-10, RF-015-02, RF-009-11: reproducir V01.r1 —sin proyecto, desde la capa de marcas, el levantamiento, las
        máscaras y los parámetros congelados, con las decisiones sobre los candidatos— da de cada dato de la detección (la tabla
        de acopios, la de candidatos, la base y el espesor de los **tres** materiales —el del candidato convertido es «sin
        material»—, el terreno sin acopios, la superficie con que se detectó y el informe) el **mismo hash** que registró la
        operación y las mismas cifras, sin escribir nada en el proyecto."""
        self.assert_same(self.reproduce())
        roles = [role for role, _name in self.written(self.uid)]
        self.assertEqual(roles, ["stockpiles", "stockpile_candidates", *["stockpile_base"] * 3,
                                 *["stockpile_thickness"] * 3, "stockpile_ground", "stockpile_surface",
                                 provenance.ENTITY_REPORT_ROLE])

    def test_b_changing_and_recomputing_after_freezing_leaves_the_frozen_revision_as_it_was(self) -> None:
        """RF-016-10, RF-015-16, RF-009-19, RF-009-11, RF-008-26, CE-016-01: congelada V01.r1, cambiar el umbral de la huella
        deja obsoleta la detección (la operación entera, con su causa) y «Recalcular lo obsoleto» la repite **registrando la
        nueva en la revisión abierta**; lo congelado no cambia (la revisión sigue congelada, sus elementos son los mismos, la
        operación sustituida queda en ella como historia, no se marca nada de ella) y V01.r1 se reproduce otra vez igual, con
        los hash de cuando se congeló (aunque lo vivo ya sea otro)."""
        items = self.query("SELECT * FROM gb_revision_item WHERE revision_uid = ? ORDER BY fid", self.revision)
        self.assertTrue(items)
        frozen = self.hashes_of(self.uid)
        self.change_threshold(0.6)
        self.assertEqual(self.stale_causes(self.uid), {("parameter_changed", THRESHOLD_KEY)})
        self.clock.advance(minutes=1)
        outcome = ops.finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results], [recompute_mod.UnitStatus.DONE])
        (opened,) = self.query("SELECT uid FROM gb_revision WHERE version_uid = ? AND state = 'open'", self.v1.uid)[0]
        (made,) = outcome.results[0].operations
        self.assertEqual(self.query("SELECT supersedes_uid, revision_uid FROM gb_operation WHERE uid = ?", made),
                         [(self.uid, opened)])
        self.assertEqual(self.query("SELECT revision_uid FROM gb_operation WHERE uid = ?", self.uid), [(self.revision,)])
        self.assertEqual(self.query("SELECT state FROM gb_revision WHERE uid = ?", self.revision), [("frozen",)])
        self.assertEqual(self.query("SELECT * FROM gb_revision_item WHERE revision_uid = ? ORDER BY fid", self.revision),
                         items)
        self.assertEqual(self.hashes_of(self.uid), frozen)
        table = provenance.dataset_name("stk", "Acopios")
        self.assertNotEqual(self.hashes_of(made)[table], frozen[table], "lo vivo cambió")
        self.assertEqual(self.recompute_plan(), [])
        self.assert_same(self.reproduce())


class DecisionsRecomputeTest(ops.RecomputeCase):
    """RF-016-08, RF-016-10, RF-015-16 (**en orden**): las decisiones sobre los candidatos son un parámetro de la entidad, y
    recalcular las aplica; lo que ya no escribe la operación nueva deja de estar vigente."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.create(tp.request(surface=tp.VERSION_SURFACE, candidates=True))

    def test_a_deciding_and_recomputing_converts_the_candidate_into_a_stockpile(self) -> None:
        """RF-016-08, RF-016-10, RF-015-16: convertir el candidato ``c03`` (un cambio del parámetro ``decisions``) deja
        obsoleta la detección y **recalcular** —sin pasar por la ventana— lo aplica: el candidato es un acopio más de la tabla
        (origen ``candidate``), con su base y su espesor en «sin material», y las cifras cuentan seis acopios."""
        old = self.current()
        stockpile_store.decide_candidate(self.project, CODE, "c03", "converted", "Es un acopio de mineral", version=self.v1,
                                         decided_by=USER)
        self.assertEqual(self.stale_causes(old), {("parameter_changed", design_params.entity_key(CODE, "decisions"))})
        self.clock.advance(minutes=1)
        handle = ops.recompute_function(self.request_for(old))
        rows = self.table("stk")
        self.assertEqual([row["key"] for row in rows], [*tp.NAMES, "c03"])
        self.assertEqual((rows[-1]["origin"], rows[-1]["material"]), ("candidate", None))
        (mine,) = stockpile_store.detections_on(self.project, self.v1.uid, tp.VERSION_SURFACE)
        self.assertEqual((mine.operation, [item.material for item in mine.materials]), (handle.uid, ["mineral", "estéril", None]))
        self.assertEqual(self.stale_causes(handle.uid), set())

    def test_b_taking_the_decision_back_and_recomputing_retires_what_the_new_operation_no_longer_writes(self) -> None:
        """RF-016-08, RF-016-10, RF-015-16: volver a preguntar por ``c03`` y recalcular quita el acopio: la base y el espesor de
        «sin material», que la operación nueva ya no escribe, pasan a «sustituidos» en la misma transacción (no quedan vigentes
        sin una operación que los respalde) y la consulta ya no los da."""
        old = self.current()
        names = [provenance.dataset_name(family, "Acopios sin material") for family in ("stb", "stt")]
        self.assertEqual([self.query("SELECT status FROM gb_dataset WHERE name = ?", name) for name in names],
                         [[("current",)], [("current",)]])
        stockpile_store.decide_candidate(self.project, CODE, "c03", "pending", "Se vuelve a preguntar", version=self.v1,
                                         decided_by=USER)
        self.clock.advance(minutes=1)
        handle = ops.recompute_function(self.request_for(old))
        self.assertEqual([row["key"] for row in self.table("stk")], list(tp.NAMES))
        self.assertEqual([self.query("SELECT status FROM gb_dataset WHERE name = ?", name) for name in names],
                         [[("superseded",)], [("superseded",)]])
        (mine,) = stockpile_store.detections_on(self.project, self.v1.uid, tp.VERSION_SURFACE)
        self.assertEqual((mine.operation, [item.material for item in mine.materials]), (handle.uid, ["mineral", "estéril"]))


class StaleCase(ops.RecomputeCase, mso.ObsoleteCase):
    """Lo de ``RecomputeCase`` y ``ObsoleteCase`` (las operaciones sintéticas de lo que depende de una detección): las clases
    crean las detecciones que necesitan."""

    @classmethod
    def both(cls) -> None:
        """La detección de V01 (sobre su copia del levantamiento) y la del proyecto, con las cinco marcas."""
        cls.create(tp.request(surface=tp.VERSION_SURFACE))
        cls.create(tp.request(), version=None, masks=None)

    def now(self) -> dict[str, str]:
        """La operación vigente de cada ámbito."""
        return {"version": self.current(), "project": self.current(version=False)}


class StaleTest(StaleCase):
    """CE-016-01, RF-016-10, RF-015-16, RF-016-04: lo que deja obsoleta la operación entera cuando se edita la capa de marcas
    (**en orden**: ``test_a`` y ``test_b``)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.both()

    def test_a_a_geometry_edited_in_the_marks_layer_makes_both_stale_and_an_overlap_is_not_recomputed(self) -> None:
        """CE-016-01, RF-016-10, RF-015-16, RF-016-04: mover en QGIS el polígono del Acopio 1 dos metros al este cambia la capa
        de marcas, **entrada** de la operación con su hash: la detección de V01 y la del proyecto quedan obsoletas
        **enteras** con la capa como causa (``dataset_changed``) y ya no son «al día». Pero esa marca se solapa ahora con la
        del Acopio 2 (40 m²): «Recalcular lo obsoleto» no la repite (se rechaza al preparar, nombrando las dos marcas), no
        empieza ninguna operación y las anteriores siguen vigentes, obsoletas."""
        old = self.now()
        operations_before = self.query("SELECT count(*) FROM gb_operation")
        rewrite_marks(self.project, self.clock, move_first=2.0)
        for uid in old.values():
            self.assertEqual(self.stale_causes(uid), {("dataset_changed", sdata.MARKS_LAYER)})
        self.assertEqual(stockpile_store.detections_on(self.project, self.v1.uid, tp.VERSION_SURFACE), ())
        self.assertEqual(stockpile_store.detections_on(self.project, self.v1.uid, sdata.SURVEY_DATASET), ())
        self.clock.advance(minutes=1)
        operations_after_edit = self.query("SELECT count(*) FROM gb_operation")
        outcome = ops.finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results], [recompute_mod.UnitStatus.FAILED] * 2)
        for result in outcome.results:
            self.assertEqual(result.code, "core.recompute_failed")
            for part in ("«Acopio 1»", "«Acopio 2»", "se solapan"):
                self.assertIn(part, str(result.reason))
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation"), operations_after_edit, "no empieza ninguna")
        self.assertGreater(operations_after_edit[0][0], operations_before[0][0], "la edición de la capa sí es una operación")
        self.assertEqual(self.now(), old)

    def test_b_a_mark_moved_without_overlapping_is_recomputed_keeping_the_identity(self) -> None:
        """CE-016-01, RF-016-10, RF-015-16: con la marca del Acopio 1 dos metros al **oeste** de donde estaba (cuatro metros
        al oeste de la edición anterior, que sigue sin recalcular) no se solapa con ninguna: «Recalcular lo obsoleto» repite las
        dos detecciones —la misma identidad, las mismas cinco claves— y cambian las huellas de las dos marcas que se tocan (se
        reparten sus celdas de otro modo) y las de las otras tres, no; quedan al día."""
        old = self.now()
        before = {version: {row["key"]: row for row in self.table("stk", version=version)} for version in (True, False)}
        rewrite_marks(self.project, self.clock, move_first=-4.0)
        self.clock.advance(minutes=1)
        outcome = ops.finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results], [recompute_mod.UnitStatus.DONE] * 2)
        new = self.now()
        for scope, uid in old.items():
            with self.subTest(scope=scope):
                self.assertNotEqual(new[scope], uid)
                self.assertEqual(self.stale_causes(new[scope]), set())
        for version in (True, False):
            after = {row["key"]: row for row in self.table("stk", version=version)}
            self.assertEqual(list(after), list(before[version]), "la misma identidad: las mismas marcas")
            changed = {key for key in after if after[key]["footprint"] != before[version][key]["footprint"]}
            self.assertTrue(changed and changed <= {"Acopio 1", "Acopio 2"}, changed)  # se tocan: se reparten sus celdas
        self.assertEqual(self.recompute_plan(), [])
        self.assertEqual(len(stockpile_store.detections_on(self.project, self.v1.uid, tp.VERSION_SURFACE)), 1)


class FieldEditTest(StaleCase):
    """RF-016-10, RF-016-02: lo que se lee de un campo de la capa de marcas se aplica al recalcular."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.both()

    def test_a_field_of_a_mark_is_applied_when_recomputing_and_is_not_a_parameter_of_the_entity(self) -> None:
        """RF-016-10, RF-016-02, RF-015-16 (T11: el margen de cada marca sale de la capa cada vez que se prepara y no es un
        parámetro de la entidad): el ``margen`` del Acopio 2 cambiado en la capa se **aplica al recalcular** (la fila de su
        acopio lo lleva y su huella es la de la detección con ese margen, calculada aparte), y los parámetros de la entidad, con
        su historial, no se tocan."""
        job = ops.survey_job(flat=False)
        marks = tuple(dataclasses.replace(mark, margin_m=14.0) if mark.key == "Acopio 2" else mark for mark in job.marks)
        wanted = {item.key: int(item.cells.size)
                  for item in stockpiles.detect_stockpiles(dataclasses.replace(job, marks=marks)).stockpiles}["Acopio 2"]
        before = {row["key"]: row for row in self.table("stk")}
        rows = self.parameter_rows()
        rewrite_marks(self.project, self.clock, margins={"Acopio 2": 14.0})
        for uid in self.now().values():  # el hash de la capa cuenta todas sus columnas: la deja obsoleta, solo por ella
            self.assertLessEqual(self.stale_causes(uid), {("dataset_changed", sdata.MARKS_LAYER)})
        self.clock.advance(minutes=1)
        for version in (True, False):
            handle = ops.recompute_function(self.request_for(self.current(version=version), version=version))
            self.assertEqual(self.query("SELECT status FROM gb_operation WHERE uid = ?", handle.uid), [("done",)])
            after = {row["key"]: row for row in self.table("stk", version=version)}
            with self.subTest(version=version):
                self.assertEqual((before["Acopio 2"]["margin_m"], after["Acopio 2"]["margin_m"]), (10.0, 14.0))
                self.assertEqual(after["Acopio 2"]["cells"], wanted)
        self.assertEqual(self.parameter_rows(), rows, "el margen de una marca no es un parámetro de la entidad")


class DependentsTest(StaleCase):
    """CE-016-01, RF-015-16, RF-009-05: lo que depende de lo que escribió la detección **del proyecto**, en el proyecto y en una
    versión, queda obsoleto con su causa."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.create(tp.request(), version=None, masks=None)
        base = provenance.dataset_name(provenance.STOCKPILE_BASE_GRID, "Acopios estéril")
        cls.made("cubicación", mso.CONSUMER_PROJECT, [base], version=False)
        cls.made("retirada en V01", mso.CONSUMER_VERSION, [base])
        cls.made("sin relación", mso.CONSUMER_PROJECT, [], version=False)

    def test_recomputing_the_detection_of_the_project_makes_what_used_its_data_stale(self) -> None:
        """CE-016-01 (la última frase), RF-016-10, RF-015-16, RF-009-05: recalcular la detección **del proyecto** con otro
        umbral cambia la base de los acopios de estéril: lo que la consumía —una operación del proyecto y otra de V01, que
        puede consumir un dato del proyecto— queda obsoleto con su causa (el dato que cambió) y lo que no tiene relación, no
        (la parte de proyecto de lo obsoleto que la T10 dejó para aquí)."""
        base = provenance.dataset_name(provenance.STOCKPILE_BASE_GRID, "Acopios estéril")
        for name in ("cubicación", "retirada en V01", "sin relación"):
            self.assertEqual(self.stale_causes(self.uids[name]), set())
        self.change_threshold(0.6)
        self.clock.advance(minutes=1)
        handle = ops.recompute_function(self.request_for(self.current(version=False), version=False))
        for name in ("cubicación", "retirada en V01"):
            with self.subTest(consumer=name):
                self.assertIn(("dataset_changed", base), self.stale_causes(self.uids[name]))
        self.assertEqual(self.stale_causes(self.uids["sin relación"]), set())
        self.assertEqual(self.stale_causes(handle.uid), set())


class RefusalTest(ops.RecomputeCase):
    """RF-016-10, RF-015-02, RF-013-17 (``des.input_changed``): lo que impide registrar un recálculo, con la detección de V01 y
    la del proyecto creadas."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.create(tp.request(surface=tp.VERSION_SURFACE))
        cls.create(tp.request(), version=None, masks=None)

    def test_a_parameter_that_changes_before_the_operation_starts_is_not_registered(self) -> None:
        """RF-013-17, RF-015-16: si el umbral de la huella cambia entre que se prepara el recálculo y que la operación nueva
        empieza (y anota los valores que lee), el cálculo no le corresponde: al avanzar, ``des.input_changed`` con el
        parámetro, la operación nueva queda fallida y la anterior, vigente, sin sustituir y sin temporales; lo mismo en V01 y
        en el proyecto."""
        real = store.OperationStart.begin
        for version, changed in ((True, 0.45), (False, 0.5)):
            old = self.current(version=version)

            def racing(start: Any, project: Any, **options: Any) -> Any:
                self.change_threshold(changed)  # cambia justo antes de empezar
                return real(start, project, **options)

            self.clock.advance(minutes=1)
            with self.subTest(version=version):
                with mock.patch.object(store.OperationStart, "begin", racing):
                    handle, work = store.recompute_run(self.request_for(old, version=version))
                with self.assertRaises(messages.DesignError) as caught:
                    ops.finish(work)
                self.assertEqual(caught.exception.code, "des.input_changed")
                self.assertIn(THRESHOLD_KEY, caught.exception.text)
                self.assertEqual(self.query("SELECT status, supersedes_uid FROM gb_operation WHERE uid = ?", handle.uid),
                                 [("failed", old)])
                self.assertEqual(self.query("SELECT superseded_by FROM gb_operation WHERE uid = ?", old), [(None,)])
                self.assertEqual(self.current(version=version), old)
                self.assertEqual(self.temporaries(), [])
        self.assertEqual(stockpile_store.detections_on(self.project, self.v1.uid, tp.VERSION_SURFACE), (),
                         "obsoleta: el umbral cambió")

    def test_an_input_that_changes_before_the_operation_starts_is_not_registered(self) -> None:
        """RF-013-04, RF-013-17: si la superficie sobre la que se detecta cambia entre que se prepara el recálculo y que la
        operación nueva empieza, el resultado no le corresponde: ``des.input_changed`` al empezar (con el dato), la
        operación nueva queda fallida, la anterior sigue vigente sin sustituir y no queda ningún temporal."""
        old = self.current(version=False)
        real = store.OperationStart.begin
        shifted = gis.Raster(self.grid, sdata.survey(self.grid) + 1.0, sdata.CRS, sdata.VERTICAL)

        def racing(start: Any, project: Any, **options: Any) -> Any:
            self.clock.advance(minutes=1)
            res_fixtures.write_grids(self.project, [(sdata.SURVEY_LABEL, shifted)],
                                     message="El levantamiento cambia justo antes de empezar")
            return real(start, project, **options)

        self.clock.advance(minutes=1)
        with mock.patch.object(store.OperationStart, "begin", racing):
            with self.assertRaises(messages.DesignError) as caught:
                store.recompute_run(self.request_for(old, version=False))
        self.assertEqual(caught.exception.code, "des.input_changed")
        self.assertIn(sdata.SURVEY_DATASET, caught.exception.text)
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE supersedes_uid = ? ORDER BY fid DESC LIMIT 1", old),
                         [("failed",)])
        self.assertEqual(self.query("SELECT superseded_by FROM gb_operation WHERE uid = ?", old), [(None,)])
        self.assertEqual(self.current(version=False), old)
        self.assertEqual(self.temporaries(), [])


class ScopeTest(ops.RecomputeCase):
    """RF-016-10, D-15: una detección toma su ámbito de su superficie, y recalcularla no lo cambia."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.create(tp.request(surface=tp.VERSION_SURFACE))
        cls.create(tp.request(), version=None, masks=None)

    def test_a_surface_that_changed_scope_is_refused_before_starting_anything(self) -> None:
        """RF-016-10, D-15: si la superficie de la detección de V01 pasa a ser una **del proyecto** (el levantamiento),
        recalcularla como la misma operación de la versión no es posible: ``des.stockpile_scope_changed`` al llamar, nombrando
        la detección y la superficie, sin empezar ninguna operación ni escribir nada; y si la del proyecto pasa a una de V01, lo
        rechaza la preparación (una operación del proyecto no consume un dato de versión, RF-009-05). La anterior sigue
        vigente."""
        old, project_old = self.current(), self.current(version=False)
        self.change(SURFACE_KEY, sdata.SURVEY_DATASET)
        before = self.state()
        with self.assertRaises(messages.DesignError) as caught:
            store.recompute_run(self.request_for(old))
        error = caught.exception
        self.assertEqual(error.code, "des.stockpile_scope_changed")
        self.assertEqual((error.values["name"], error.values["surface"]), ("Acopios", sdata.SURVEY_DATASET))
        for text in (error.text, error.text_in("en")):
            self.assertIn(sdata.SURVEY_DATASET, text)
            self.assertNotIn("{", text)
        self.assertEqual(self.state(), before, "no empieza ni escribe nada")
        self.assertEqual(self.current(), old)
        self.change(SURFACE_KEY, tp.VERSION_SURFACE, version=False)
        before = self.state()
        with self.assertRaises(Exception) as other:
            store.recompute_run(self.request_for(project_old, version=False))
        self.assertIn(getattr(other.exception, "code", None), ("des.surface_other_version", "core.version_required"))
        self.assertEqual(self.state(), before)
        self.assertEqual(self.current(version=False), project_old)

    def test_what_is_not_a_detection_is_a_program_error(self) -> None:
        """RF-016-10: lo que no es una petición de recalcular, o es la de otro tipo, o lleva los ajustes de otra cosa, es un
        error del programa (``TypeError`` y ``ValueError``), no un mensaje al usuario."""
        with self.assertRaises(TypeError):
            stockpile_store.recompute_detection("petición")  # type: ignore[arg-type]
        other = recompute_mod.RecomputeRequest(self.project, "uid", provenance.STOCKPILE_REMOVAL, {}, (), ())
        with self.assertRaises(ValueError):
            stockpile_store.recompute_detection(other)
        empty = recompute_mod.RecomputeRequest(self.project, "uid", provenance.STOCKPILE_DETECT_PROJECT, {}, (), ())
        with self.assertRaises(ValueError):
            stockpile_store.recompute_detection(empty)


if __name__ == "__main__":
    unittest.main()
