# SPDX-License-Identifier: GPL-3.0-or-later
"""El plan de una congelación (spec 009, T10; RF-009-06, RF-009-07, RF-009-08, RF-009-01; plan
009 A5, D-16, D-18, D-27, D-37 y D-40).

``core.versions.freeze.freeze_plan`` dice, sin escribir nada y en una sola instantánea de la
base, qué se congelaría en la revisión abierta de una versión, sobre el proyecto de la
demostración de versiones (``tests/support/versions_fixtures.py``):

1. **Lo que se congela**, cada cosa en su parte: lo producido por la versión (sus datos vivos,
   las operaciones que los escribieron y sus cifras vigentes), lo derivado o editable a mano del
   proyecto aguas arriba con su operación, lo inmutable (lo importado, su entrada y su
   importación), lo congelado de la versión de la que parte y los parámetros con la fila de su
   historial que usó cada operación (``rev``).
2. **Lo que se copia**: el contenido actual de lo producido y de lo de aguas arriba, una sola
   vez; lo ya copiado en otra revisión congelada y no alterada se referencia; lo inmutable, lo
   heredado y un modelo de bloques (``duckdb``, D-37) se anotan sin copiar. El espacio, lo que
   se copia más un 10 %.
3. **Lo que hay que aceptar** (RF-009-08), con su estado: lo obsoleto, lo que espera revisión a
   mano y las entradas no localizables; y lo que una operación consumió y ya no existe ni está
   congelado, «no reproducible».
4. **Lo que lo impide**: el solo lectura, la comprobación de apertura sin terminar, otra
   congelación en curso, una operación de la versión en curso y una entrada cambiada sin decidir
   (D-40); una versión SUPERADO o DESCARTADO no tiene revisión que congelar.

Datos solo sintéticos.
"""

from __future__ import annotations

import collections
import dataclasses
import math
import os
import re
import sqlite3
import unittest
from typing import Any

from tests.support import provenance_demo as demo_support
from tests.support import versions_demo as vdemo
from tests.support import versions_fixtures as fixtures
from tests.support.package import import_geoblender

freeze = import_geoblender("core.versions.freeze")
model = import_geoblender("core.versions.model")
versions_read = import_geoblender("core.versions.read")
versions_schema = import_geoblender("core.versions.schema")
operations = import_geoblender("core.provenance.operations")
gate = import_geoblender("core.provenance.gate")
project_model = import_geoblender("core.project.model")

ItemKind = model.ItemKind
ItemPart = model.ItemPart
ItemState = model.ItemState
BlockReason = freeze.BlockReason

SOURCE = "Plan de labores (prueba)"
DECIDER = "Samuel (IMGA)"
PIT_DATA = (vdemo.PIT_GRID, vdemo.PIT_MESH, vdemo.PIT_BENCHES)
"""Lo que escribe ``demo.pit`` en su versión."""
UPSTREAM_DATA = (demo_support.STOCKPILES_TABLE, demo_support.CANDIDATES_TABLE,
                 demo_support.YEARS_TABLE, demo_support.BENCHES_TABLE, demo_support.MARKS_TABLE)
"""Lo derivado o editable del proyecto que hay aguas arriba de ``demo.pit_stockpiles``."""
UPSTREAM_STEPS = ("filter", "detect", "years", "digitize")
"""… y las operaciones de la cadena de la 008 que lo escribieron."""
GB_TABLES = ("gb_operation", "gb_operation_io", "gb_operation_param", "gb_revision_item",
             "gb_revision", "gb_dataset", "gb_figure", "gb_parameter", "gb_input", "gb_stale")
_ALIAS = re.compile(r"\b(gb_[a-z_]+)\s+(?:AS\s+)?(\w+)", re.IGNORECASE)
_WRITES = ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER")


class ItemModelTest(unittest.TestCase):
    def test_items_as_the_schema_writes_them(self) -> None:
        """RF-009-07, RF-009-19 (plan §5.2.1 y §5.3.1): lo congelado (``RevisionItem``) tiene
        las columnas de ``gb_revision_item`` en su orden (sin ``fid``), y sus clases, partes y
        estados son los que admite la base."""
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.execute(versions_schema.TABLES["gb_revision_item"])
        columns = [row[1] for row in conn.execute("PRAGMA table_info(gb_revision_item)")]
        self.assertEqual(columns[1:], [field.name for field in
                                       dataclasses.fields(model.RevisionItem)])
        sql = versions_schema.TABLES["gb_revision_item"]
        for column, enum in (("item_kind", ItemKind), ("part", ItemPart), ("state", ItemState)):
            (listed,) = re.findall(rf"CHECK \({column} IN \(([^)]*)\)\)", sql)
            with self.subTest(column=column):
                self.assertEqual(listed.replace("'", "").split(","), [str(value)
                                                                      for value in enum])


class FreezePlanCase(fixtures.VersionsProjectCase):
    """Ayudas para las pruebas del plan de una congelación."""

    def plan(self, version: str = "V01", **kw: Any) -> Any:
        return freeze.freeze_plan(self.project, version, **kw)

    def bench(self, value: float, *, version: str | None = None) -> None:
        """Cambia ``demo.bench_height`` del proyecto o, con ``version``, el de esa versión."""
        self.tick()
        self.write(lambda conn: self.store.change(
            conn, vdemo.BENCH_HEIGHT, value=value, source=SOURCE, decided_by=DECIDER,
            reason="Banco de la prueba", version=version))

    @staticmethod
    def items(plan: Any, kind: Any) -> dict[str, Any]:
        """Los elementos de ``kind`` del plan, por uid."""
        found = {item.item_uid: item for item in plan.items if item.item_kind == kind}
        return found

    @staticmethod
    def parts(plan: Any, kind: Any) -> dict[str, Any]:
        """La parte de cada elemento de ``kind`` del plan, por uid."""
        return {item.item_uid: item.part for item in plan.items if item.item_kind == kind}

    def uids(self, names: tuple[str, ...], version: str | None = None) -> set[str]:
        return {self.record(name, version).uid for name in names}

    def input_uid(self) -> str:
        return str(self.record(self.boundary).input_uid)

    def assertNothingWritten(self, work: Any) -> Any:  # noqa: N802 - unittest
        """``work()`` sin cambiar el contador de cambios de la base ni ningún fichero."""
        files, counter = self.files(), self.change_counter()
        result = work()
        self.assertEqual(self.change_counter(), counter)
        self.assertEqual(self.files(), files)
        return result


class WhatIsFrozenTest(FreezePlanCase):
    def test_parts_copies_and_space(self) -> None:
        """RF-009-07, D-16, D-18 (plan A5 (2), (4) y (5)): con ``demo.pit``,
        ``demo.pit_volume`` y ``demo.pit_stockpiles`` en V01 (y un hueco en V02), el plan de
        V01.r1 tiene lo **producido** (sus 4 datos, sus 3 operaciones y su cifra vigente), lo
        **derivado del proyecto aguas arriba** (los acopios, los candidatos, los años, los
        bancos y las marcas editables a mano, con las 4 operaciones que los escribieron), lo
        **inmutable** (lo importado del límite, su entrada y su importación) y los parámetros
        con la ``rev`` que usó cada operación; nada de V02, ni el área ni el balance, que no
        están aguas arriba. Se copian los 9 datos que pueden cambiar (rejilla y malla con su
        ruta, tablas en el GeoPackage de la instantánea con su nombre), una vez cada contenido;
        lo inmutable se anota sin copiar. El espacio: lo que se copia (los ficheros con su
        tamaño) más un 10 %. Nada que aceptar, nada que lo impida y nada escrito."""
        pit = self.demo.pit(self.project, "V01")
        volume = self.demo.pit_volume(self.project, "V01")
        piles = self.demo.pit_stockpiles(self.project, "V01")
        other = self.demo.pit(self.project, "V02")
        plan = self.assertNothingWritten(self.plan)

        revision = self.read(lambda conn: versions_read.open_revision(conn, self.v1.uid))
        self.assertEqual((plan.version.uid, plan.revision), (self.v1.uid, revision))
        self.assertEqual((plan.label, plan.snapshot_dir), ("V01.r1", "snapshots/V01.r1"))
        produced = self.uids((*PIT_DATA, vdemo.PIT_STOCKPILES_TABLE), "V01")
        upstream = self.uids(UPSTREAM_DATA)
        boundary = self.record(self.boundary)
        self.assertEqual(self.parts(plan, ItemKind.DATASET), {
            **dict.fromkeys(produced, ItemPart.PRODUCED),
            **dict.fromkeys(upstream, ItemPart.UPSTREAM),
            boundary.uid: ItemPart.IMMUTABLE,
        })
        self.assertEqual(self.parts(plan, ItemKind.OPERATION), {
            **dict.fromkeys((pit.uid, volume.uid, piles.uid), ItemPart.PRODUCED),
            **dict.fromkeys((self.chain[step] for step in UPSTREAM_STEPS), ItemPart.UPSTREAM),
            self.chain["boundary"]: ItemPart.IMMUTABLE,
        })
        self.assertNotIn(other.uid, self.parts(plan, ItemKind.OPERATION))
        self.assertEqual(self.parts(plan, ItemKind.INPUT), {self.input_uid(): ItemPart.IMMUTABLE})
        ((figure_uid,),) = self.query("SELECT uid FROM gb_figure WHERE operation_uid = ?",
                                      (volume.uid,))
        self.assertEqual(self.parts(plan, ItemKind.FIGURE), {figure_uid: ItemPart.PRODUCED})
        used = {str(uid): (str(op_uid), int(rev), str(sha)) for uid, op_uid, rev, sha in self.query(
            "SELECT parameter_uid, operation_uid, rev, value_sha256 FROM gb_operation_param "
            "WHERE operation_uid <> ? ORDER BY fid", (other.uid,))}
        parameters = self.items(plan, ItemKind.PARAMETER)
        self.assertEqual(set(parameters), set(used))
        for uid, item in parameters.items():
            op_uid, rev, sha = used[uid]
            self.assertEqual((item.item_rev, item.content_sha256, item.part),
                             (rev, sha, ItemPart.PRODUCED if op_uid == pit.uid
                              else ItemPart.UPSTREAM))
        self.assertEqual({item.state for item in plan.items}, {ItemState.CURRENT})
        self.assertTrue(all(item.revision_uid == revision.uid for item in plan.items))

        # Lo que se copia y dónde; lo inmutable, sin copia.
        datasets = self.items(plan, ItemKind.DATASET)
        for uid, item in datasets.items():
            record = self.record(uid)
            with self.subTest(dataset=record.name):
                self.assertEqual(item.content_sha256, record.content_sha256)
                if uid == boundary.uid:
                    self.assertEqual((item.copied, item.snapshot_path, item.snapshot_layer),
                                     (False, None, None))
                elif str(record.store) == "gpkg":
                    self.assertEqual((item.copied, item.snapshot_path, item.snapshot_layer),
                                     (True, "snapshots/V01.r1/V01.r1.gpkg", record.locator))
                else:
                    self.assertEqual((item.copied, item.snapshot_path, item.snapshot_layer),
                                     (True, f"snapshots/V01.r1/{record.locator}", None))
        copies = {copy.record.uid: copy for copy in plan.to_copy}
        self.assertEqual(set(copies), produced | upstream)
        self.assertEqual(plan.referenced, ())
        self.assertEqual(len({copy.record.content_sha256 for copy in plan.to_copy}), 9)
        for copy in plan.to_copy:
            item = datasets[copy.record.uid]
            self.assertEqual((copy.part, copy.snapshot_path, copy.snapshot_layer),
                             (item.part, item.snapshot_path, item.snapshot_layer))
            if str(copy.record.store) == "gpkg":
                self.assertGreater(copy.size, 0)
            else:
                self.assertEqual(copy.size, os.path.getsize(self.root / copy.record.locator))
        tables = sum(copy.size for copy in plan.to_copy if str(copy.record.store) == "gpkg")
        files = sum(copy.size for copy in plan.to_copy if str(copy.record.store) != "gpkg")
        self.assertEqual(plan.bytes_to_copy, files + tables + freeze.GPKG_BASE_BYTES)
        self.assertEqual(plan.space_needed,
                         plan.bytes_to_copy + math.ceil(plan.bytes_to_copy * 0.10))
        gpkg = tables + freeze.GPKG_BASE_BYTES
        self.assertEqual(plan.cache_needed, gpkg + math.ceil(gpkg * 0.10))
        self.assertEqual((plan.accept, plan.blockers), ((), ()))
        self.assertFalse(plan.blocked)
        self.assertFalse(plan.needs_acceptance)


class CopiedOnceTest(FreezePlanCase):
    def test_already_frozen_is_referenced(self) -> None:
        """RF-009-07, D-16, D-28, RNF-009-06 (plan A5 (4)): tras congelar V01.r1 con lo que
        copia su plan, el de V01.r2 no copia nada (lo referencia todo a V01.r1: 0 bytes); el de
        V02 (con su banco propio de 12 m: otros contenidos) copia lo suyo y referencia los 5
        datos del proyecto ya copiados en V01.r1; con V01.r1 alterada, vuelve a copiarlo
        todo."""
        self.demo.pit(self.project, "V01")
        self.demo.pit_stockpiles(self.project, "V01")
        first = self.plan()
        r1 = self.freeze(self.v1, [(copy.record, str(copy.part)) for copy in first.to_copy])
        upstream = self.uids(UPSTREAM_DATA)
        own = self.uids((*PIT_DATA, vdemo.PIT_STOCKPILES_TABLE), "V01")

        again = self.plan()
        self.assertEqual(again.label, "V01.r2")
        self.assertEqual((again.to_copy, again.bytes_to_copy, again.space_needed), ((), 0, 0))
        self.assertEqual({item.item_uid for item in again.referenced}, own | upstream)
        before = {copy.record.uid: (copy.snapshot_path, copy.snapshot_layer)
                  for copy in first.to_copy}
        for item in again.referenced:
            self.assertFalse(item.copied)
            self.assertEqual((item.snapshot_path, item.snapshot_layer), before[item.item_uid])
            self.assertTrue(item.snapshot_path.startswith("snapshots/V01.r1/"))

        self.bench(12.0, version="V02")
        self.demo.pit(self.project, "V02")
        self.demo.pit_stockpiles(self.project, "V02")
        second = self.plan("V02")
        mine = self.uids((*PIT_DATA, vdemo.PIT_STOCKPILES_TABLE), "V02")
        self.assertEqual({copy.record.uid for copy in second.to_copy}, mine)
        self.assertEqual({item.item_uid for item in second.referenced}, upstream)
        for item in second.referenced:
            self.assertEqual((item.snapshot_path, item.snapshot_layer),
                             ("snapshots/V01.r1/V01.r1.gpkg", self.record(item.item_uid).locator))
        self.assertTrue(all(copy.snapshot_path.startswith("snapshots/V02.r1/")
                            for copy in second.to_copy))

        self.tick()
        self.write(lambda conn: conn.execute(
            "UPDATE gb_revision SET altered_at = ?, altered_detail = '{}' WHERE uid = ?",
            (self.now(), r1)))
        altered = self.plan("V02")
        self.assertEqual({copy.record.uid for copy in altered.to_copy}, mine | upstream)
        self.assertEqual(altered.referenced, ())


class InheritedTest(FreezePlanCase):
    def test_frozen_from_the_parent_is_inherited(self) -> None:
        """RF-009-01, D-27, D-18 (plan A5 (2)): V03 parte de V01.r1 y diseña con sus bancos
        congelados; su plan anota esos bancos como **heredados**, referenciados a la copia de
        V01.r1 y sin copiarlos, y copia solo su diseño; no lleva nada de aguas arriba de V01
        (ni su hueco ni el límite)."""
        self.demo.pit(self.project, "V01")
        r1 = self.freeze(self.v1)
        self.new_version("desde_v01", "Desde V01", parent=self.v1.uid)
        design = self.demo.design_from_parent(self.project, "V03", frozen=r1)
        plan = self.plan("V03")
        benches = self.record(vdemo.PIT_BENCHES, "V01")
        own = self.record(vdemo.DESIGN_TABLE, "V03")
        self.assertEqual(self.parts(plan, ItemKind.DATASET),
                         {benches.uid: ItemPart.INHERITED, own.uid: ItemPart.PRODUCED})
        self.assertEqual(self.parts(plan, ItemKind.OPERATION), {design.uid: ItemPart.PRODUCED})
        self.assertEqual(self.parts(plan, ItemKind.INPUT), {})
        inherited = self.items(plan, ItemKind.DATASET)[benches.uid]
        self.assertEqual((inherited.copied, inherited.snapshot_path, inherited.snapshot_layer,
                          inherited.content_sha256, inherited.state),
                         (False, "snapshots/V01.r1/V01.r1.gpkg", benches.locator,
                          benches.content_sha256, ItemState.CURRENT))
        self.assertEqual([copy.record.uid for copy in plan.to_copy], [own.uid])
        self.assertEqual(plan.referenced, ())


class AcceptTest(FreezePlanCase):
    def test_stale_review_and_unlocatable(self) -> None:
        """RF-009-08 (plan A5 (3)): con el banco propio de V01 cambiado después de su hueco
        (la rejilla, la malla y los bancos, obsoletos) y las rampas dibujadas a mano sobre los
        bancos («revisar a mano»), y la fuente del límite borrada (no localizable), hay que
        aceptar 3 obsoletos, 1 «revisar a mano» y 1 entrada no localizable, cada uno con su
        estado y su texto; los elementos llevan el estado que tenían (lo que escribió la
        operación que espera revisión, también «revisar»). No lo impide nada."""
        pit = self.demo.pit(self.project, "V01")
        sketch = self.demo.sketch(self.project, "V01")
        self.bench(12.0, version="V01")
        os.remove(self.source)
        plan = self.plan()
        found = collections.Counter(entry.state for entry in plan.accept)
        self.assertEqual(found, {ItemState.STALE: 3, ItemState.REVIEW: 1,
                                 ItemState.UNLOCATABLE: 1})
        self.assertEqual([(entry.item_kind, entry.name) for entry in plan.accept], [
            (ItemKind.DATASET, vdemo.PIT_BENCHES), (ItemKind.DATASET, vdemo.PIT_GRID),
            (ItemKind.DATASET, vdemo.PIT_MESH), (ItemKind.OPERATION, vdemo.SKETCH),
            (ItemKind.INPUT, "Limites_v1"),
        ])
        for entry in plan.accept:
            with self.subTest(entry=entry.name):
                self.assertTrue(entry.text)
                if entry.state is ItemState.UNLOCATABLE:
                    self.assertIn("no localizable", entry.text)
                    self.assertEqual(entry.item_uid, self.input_uid())
                else:
                    self.assertTrue(entry.text.startswith("Obsoleto"), entry.text)
        self.assertEqual(plan.accept[3].item_uid, sketch.uid)
        states = {item.item_uid: item.state for item in plan.items}
        self.assertEqual({uid: states[uid] for uid in self.uids(PIT_DATA, "V01")},
                         dict.fromkeys(self.uids(PIT_DATA, "V01"), ItemState.STALE))
        self.assertEqual((states[pit.uid], states[sketch.uid],
                          states[self.record(vdemo.SKETCH_LAYER, "V01").uid],
                          states[self.input_uid()]),
                         (ItemState.STALE, ItemState.REVIEW, ItemState.REVIEW,
                          ItemState.UNLOCATABLE))
        self.assertTrue(plan.needs_acceptance)
        self.assertEqual(plan.blockers, ())


class NotReproducibleTest(FreezePlanCase):
    def test_vanished_content_and_block_models(self) -> None:
        """Spec §8, RF-009-07, RF-009-08, D-37 (plan A5 (3) y (4)): las rampas de V01 se
        dibujaron sobre unos bancos que el hueco rehecho con otro banco ya no tiene ni están
        congelados: su operación queda «no reproducible» (y sigue por aceptar como «revisar a
        mano»); en V02, con esos bancos congelados en V02.r1, solo «revisar». Un modelo de
        bloques (``duckdb``) aguas arriba se anota sin copiar, «no reproducible», como lo que lo
        consumió."""
        self.demo.pit(self.project, "V01")
        sketch = self.demo.sketch(self.project, "V01")
        self.bench(12.0, version="V01")
        self.demo.pit(self.project, "V01")
        plan = self.plan()
        states = {item.item_uid: item.state for item in plan.items}
        self.assertEqual(states[sketch.uid], ItemState.NOT_REPRODUCIBLE)
        self.assertIn((ItemKind.OPERATION, sketch.uid, ItemState.REVIEW),
                      [(entry.item_kind, entry.item_uid, entry.state) for entry in plan.accept])
        self.assertEqual(plan.not_reproducible,
                         tuple(item for item in plan.items if item.item_uid == sketch.uid))

        self.demo.pit(self.project, "V02")
        kept = self.demo.sketch(self.project, "V02")
        self.freeze(self.v2)
        self.bench(12.0, version="V02")
        self.demo.pit(self.project, "V02")
        second = self.plan("V02")
        self.assertEqual({item.item_uid: item.state for item in second.items}[kept.uid],
                         ItemState.REVIEW)
        self.assertEqual(second.not_reproducible, ())

        # Un modelo de bloques aguas arriba del hueco de V01 (D-37), escrito a mano en la base.
        (current_pit,) = [uid for (uid,) in self.query(
            "SELECT operation_uid FROM gb_dataset WHERE name = ? AND version_uid = ?",
            (vdemo.PIT_GRID, self.v1.uid))]
        block = "b10c0000-0000-4000-8000-000000000001"
        content = "c" * 64
        now = self.now()

        def add_block_model(conn: Any) -> None:
            conn.execute(
                "INSERT INTO gb_dataset (uid, name, module, kind, store, locator, reader, "
                "normalizer, content_sha256, operation_uid, tracked, created_at, modified_at) "
                "VALUES (?, 'demo_block_model', 'demo', 'block_model', 'duckdb', "
                "'demo_block_model', 'demo.block_model@1', 'gbch/1', ?, ?, 0, ?, ?)",
                (block, content, self.chain["digitize"], now, now))
            conn.executemany(
                "INSERT INTO gb_operation_io (operation_uid, direction, item_kind, item_uid, "
                "content_sha256, role) VALUES (?, ?, 'dataset', ?, ?, ?)",
                [(self.chain["digitize"], "out", block, content, "block_model"),
                 (current_pit, "in", block, content, "block_model")])

        self.write(add_block_model)
        third = self.plan()
        item = self.items(third, ItemKind.DATASET)[block]
        self.assertEqual((item.part, item.copied, item.snapshot_path, item.state),
                         (ItemPart.UPSTREAM, False, None, ItemState.NOT_REPRODUCIBLE))
        self.assertNotIn(block, {copy.record.uid for copy in third.to_copy})
        self.assertEqual({entry.item_uid: entry.state for entry in third.items}[current_pit],
                         ItemState.NOT_REPRODUCIBLE)


class BlockersTest(FreezePlanCase):
    def test_what_prevents_freezing(self) -> None:
        """RF-009-08, D-40 (plan A5 (1)): lo impiden la comprobación de apertura sin terminar,
        otra congelación en curso (su carpeta temporal en ``snapshots/``), una operación de la
        versión en curso y una entrada cambiada sin decidir aguas arriba, cada cosa con su
        motivo y lo que nombra; y el solo lectura. Una versión DESCARTADO no tiene revisión que
        congelar («Versión no editable») y una que no existe, tampoco."""
        self.demo.pit(self.project, "V01")
        self.assertEqual(self.plan().blockers, ())
        handle = operations.begin_operation(
            self.project, vdemo.PIT_VOLUME, settings={},
            inputs=list(self.demo.version_uses(vdemo.PIT_VOLUME)), executor="blender",
            version="V01")
        self.tick()
        self.write(lambda conn: conn.execute(
            "UPDATE gb_input SET status = 'changed', status_at = ?, status_by = ?, "
            "seen_sha256 = ? WHERE uid = ?", (self.now(), fixtures.USER, "d" * 64,
                                              self.input_uid())))
        temporary = self.root / "snapshots" / "V01.r1.congelando-0a1b2c3d"
        temporary.mkdir(parents=True)
        pending = gate.CheckState()
        pending.start()
        plan = self.plan(pending=pending)
        handle.cancel("Prueba")
        reasons = {blocker.reason: blocker for blocker in plan.blockers}
        self.assertEqual(set(reasons), {BlockReason.OPEN_CHECK, BlockReason.FREEZING,
                                        BlockReason.RUNNING, BlockReason.INPUT_CHANGED})
        self.assertTrue(plan.blocked)
        self.assertEqual(reasons[BlockReason.RUNNING].names, (vdemo.PIT_VOLUME,))
        self.assertEqual(reasons[BlockReason.INPUT_CHANGED].names, ("Limites_v1",))
        self.assertEqual(reasons[BlockReason.FREEZING].names, (temporary.name,))
        for blocker in plan.blockers:
            with self.subTest(reason=str(blocker.reason)):
                self.assertTrue(blocker.text)
                for name in blocker.names:
                    self.assertIn(name, blocker.text)
        pending.finish()
        self.project.set_read_only(project_model.ReadOnlyCode.REQUESTED, "Prueba")
        later = self.plan(pending=pending)
        self.assertEqual({blocker.reason for blocker in later.blockers},
                         {BlockReason.READ_ONLY, BlockReason.FREEZING,
                          BlockReason.INPUT_CHANGED})

    def test_versions_without_an_open_revision(self) -> None:
        """RF-009-04, RF-009-06: una versión DESCARTADO no tiene revisión abierta que
        congelar («V02 está en estado DESCARTADO: …»), y una que no está en el proyecto se
        dice."""
        self.set_status(self.v2, "DESCARTADO", "No sigue")
        with self.assertRaises(model.VersionError) as caught:
            self.plan("V02")
        self.assertEqual(caught.exception.code, "core.version_not_editable")
        with self.assertRaises(model.VersionError) as caught:
            self.plan("V99")
        self.assertEqual(caught.exception.code, "core.version_unknown")


class OneReadTest(FreezePlanCase):
    def test_one_snapshot_and_its_indexes(self) -> None:
        """Plan A5 («una sola lectura, en una instantánea de la base, sin escribir») y §2.1
        (trampa §6): el plan se lee en una sola transacción de lectura (un ``BEGIN`` y su
        ``ROLLBACK``), sin ninguna escritura, y da lo mismo con la conexión de quien llama que
        con la suya; sus consultas no recorren enteras las tablas de la procedencia ni las de
        las versiones (``EXPLAIN QUERY PLAN``), también con lo ya congelado y lo heredado."""
        self.demo.pit(self.project, "V01")
        self.demo.pit_volume(self.project, "V01")
        self.demo.pit_stockpiles(self.project, "V01")
        self.demo.sketch(self.project, "V01")
        r1 = self.freeze(self.v1)
        self.new_version("desde_v01", "Desde V01", parent=self.v1.uid)
        self.demo.design_from_parent(self.project, "V03", frozen=r1)
        self.bench(12.0, version="V01")
        self.demo.pit(self.project, "V01")  # las rampas leyeron unos bancos que ya no están
        mine: list[str] = []
        for version in ("V01", "V03"):
            statements: list[str] = []
            with self.project.read() as conn:
                conn.set_trace_callback(statements.append)
                try:
                    plan = freeze.freeze_plan(self.project, version, conn=conn)
                finally:
                    conn.set_trace_callback(None)
                with self.subTest(version=version):
                    self.assertEqual(plan, self.plan(version))
                    self.assertEqual((statements[0], statements[-1]), ("BEGIN", "ROLLBACK"))
                    self.assertEqual(statements.count("BEGIN"), 1)
                    self.assertFalse([sql for sql in statements
                                      if sql.lstrip().upper().startswith(_WRITES)])
                tagged = [sql for sql in statements if freeze.QUERY_TAG in sql]
                self.assertGreaterEqual(len(tagged), 5)
                mine.extend(tagged)
                for sql in tagged:
                    tables = {alias for table, alias in _ALIAS.findall(sql) if table in GB_TABLES}
                    tables |= {table for table, _alias in _ALIAS.findall(sql)
                               if table in GB_TABLES}
                    with self.subTest(sql=sql):
                        steps = [row[3] for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}")]
                        self.assertFalse([step for step in steps if step.startswith("SCAN ")
                                          and step.split()[1] in tables], steps)
        for table in ("gb_revision_item", "gb_operation_io", "gb_operation_param", "gb_stale"):
            self.assertTrue(any(table in sql for sql in mine), table)
