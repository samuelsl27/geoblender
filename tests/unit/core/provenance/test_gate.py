# SPDX-License-Identifier: GPL-3.0-or-later
"""Puerta antes de operar (spec 008, T30; RF-008-10, RF-008-21, RF-008-56, RF-008-57,
RF-008-58; ADR-0025 §4 y §6; plan 008 §5.3.1, §5.4.2, §5.4.5 y §5.4.9).

``core.provenance.gate.can_run`` dice, antes de empezar una operación, si se puede ejecutar
(``Ready``), si se niega y por qué (``Blocked``) o si hay que esperar (``Pending``):

- recorre aguas arriba lo que consume hasta sus importaciones y comprueba, con el prefiltro
  rápido, las fuentes de sus entradas y los datos de la cadena; lo que salta se hashea en el
  hilo si cabe en el tiempo de la puerta y, si cambió, se registra antes de operar: la entrada,
  «cambiada»; el dato, como edición externa (``core.external_edit``), «falta» o «dañado»;
- se niega con una entrada cambiada sin decidir aguas arriba (con el aviso de la spec §8 y sus
  tres salidas: Actualizar, Mantener la copia y Cancelar) y con un dato consumido que falta,
  está bloqueado o dañado, nombrándolo; «se mantiene la copia» no se niega;
- espera («Comprobando el proyecto…: espere a que termine») mientras la comprobación de
  apertura no ha comprobado algo de la cadena (``CheckState``) y si un hash es largo: entonces
  lo pide a ``CheckState`` y devuelve «pendiente».

Cada prueba usa el proyecto sintético de ``test_check`` (esquema 2, reloj simulado) con la
fuente «Limites_v1» en ``fuentes/`` y una cadena de operaciones de prueba sobre lo importado.
"""

from __future__ import annotations

import ast
import os
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any
from unittest import mock

from tests.support import provenance_data as data
from tests.support.package import import_geoblender
from tests.support.provenance_checks import assert_source_untouched
from tests.support.provenance_contract import registered
from tests.support.provenance_readers import registered as readers_registered
from tests.support.trees import age_folders
from tests.unit.core.inputs.test_check import CheckCase, _local_ns
from tests.unit.core.inputs.test_registry import GPKG, ROWS_B

gate = import_geoblender("core.provenance.gate")
provenance = import_geoblender("core.provenance")
contract = import_geoblender("core.provenance.contract")
operations = import_geoblender("core.provenance.operations")
messages = import_geoblender("core.provenance.messages")
stale_mod = import_geoblender("core.provenance.stale")
datasets = import_geoblender("core.datasets")
dataset_registry = import_geoblender("core.datasets.registry")
external = import_geoblender("core.datasets.external")
tracking = import_geoblender("core.datasets.tracking")
inputs = import_geoblender("core.inputs")
events = import_geoblender("core.project.events")
project_model = import_geoblender("core.project.model")
readers = import_geoblender("core.content.readers")
builtin = import_geoblender("core.content.builtin")
base = import_geoblender("core.gpkg.base")
hashing = import_geoblender("core.hashing")

ProvenanceError = messages.ProvenanceError
Use = operations.Use
ItemKind = operations.ItemKind
Choice = gate.Choice
BlockKind = gate.BlockKind
PendingReason = gate.PendingReason

OUTLINE = provenance.OperationDef("res.outline", "1.0", "res", "Test outline", False)
AREA = provenance.OperationDef("res.area", "1.0", "res", "Test area", False)
PLAN = provenance.OperationDef("res.plan", "1.0", "res", "Test plan", False)
TERRAIN = provenance.OperationDef("res.terrain", "1.0", "res", "Test terrain", False)
OUTLINE_ROWS = (("C-01", 1.0), ("C-02", 2.0))
EDITED_AT = "2030-01-01T00:00:00.000Z"  # el last_change que deja la edición de otro programa
TERRAIN_FILE = "rasters/res_mdt.bin"

_SLOW_READS: list[str] = []


def _read_slow(request: Any) -> Iterator[float]:
    """Un lector de rejillas de prueba que hashea los bytes del fichero (y anota que leyó)."""
    _SLOW_READS.append(request.files["main"].name)
    yield from builtin.read_document(request)


SLOW = readers.ContentReader("test.slow_grid", 1, ("raster",), False, False,
                             lambda size: 5.0, _read_slow)
"""Un lector cuya estimación pasa siempre del tiempo de la puerta."""


def _table(conn: sqlite3.Connection, name: str, rows: Sequence[tuple[str, float]]) -> None:
    base.create_attribute_table(conn, name, [base.ColumnDef("codigo", "TEXT"),
                                             base.ColumnDef("valor", "DOUBLE")], name)
    conn.executemany(f'INSERT INTO "{name}" (codigo, valor) VALUES (?, ?)', rows)


def _spec(name: str, role: str, *, editable: bool = False) -> Any:
    return datasets.DatasetSpec(name, "res", "table", "gpkg", name, reader=GPKG, role=role,
                                qgis_editable=editable)


class GateCase(CheckCase):
    """El proyecto de ``test_check`` con la cadena de prueba: la entrada «Limites_v1» importada
    en ``res_limites``; «res.outline» la lee y escribe ``res_contorno`` (un límite que su módulo
    declara editable a mano) y ``res_bocas`` (no editable); «res.area» lee ``res_contorno`` y
    escribe ``res_area``. «res.plan» es la operación que se quiere ejecutar."""

    def setUp(self) -> None:
        super().setUp()
        self.enterContext(registered(*contract.CORE_OPERATIONS, OUTLINE, AREA, PLAN, TERRAIN))
        self.state = gate.CheckState()
        self.record = self.import_boundary()
        outline = operations.begin_operation(
            self.project, OUTLINE.op_type, settings={}, executor="blender",
            inputs=[Use("res_limites", "boundary")])

        def write_outline(conn: sqlite3.Connection) -> Any:
            _table(conn, "res_contorno", OUTLINE_ROWS)
            _table(conn, "res_bocas", (("S-01", 10.0),))
            return outline.complete(conn, outputs=[
                _spec("res_contorno", "outline", editable=True), _spec("res_bocas", "collars")])

        self.write(write_outline)
        self.later()
        area = operations.begin_operation(self.project, AREA.op_type, settings={},
                                          executor="blender",
                                          inputs=[Use("res_contorno", "outline")])
        self.write(lambda conn: (_table(conn, "res_area", (("total", 12.0),)),
                                 area.complete(conn, outputs=[_spec("res_area", "area")])))
        self.later()
        self.outline, self.area = outline, area

    # --- Ayudas -----------------------------------------------------------------------------

    def can_run(self, *uses: Any, op_type: str = PLAN.op_type) -> Any:
        return gate.can_run(self.project, op_type, list(uses), pending=self.state)

    def uid(self, name: str) -> str:
        found = self.dataset(name)
        self.assertIsNotNone(found, name)
        return str(found.uid)

    def set_status(self, name: str, status: str) -> None:
        uid = self.uid(name)
        self.write(lambda conn: dataset_registry.set_status(conn, self.project, uid, status))

    def foreign(self, sql: str, args: tuple[Any, ...] = (), *, table: str | None = None) -> None:
        """Lo que hace otro programa (QGIS) con su propia conexión, sin las funciones de
        Geoblender; si toca ``table``, deja su ``last_change`` como lo pone QGIS al guardar."""
        conn = sqlite3.connect(self.project.database_path, isolation_level=None)
        try:
            conn.execute(sql, args)
            if table is not None:
                conn.execute("UPDATE gpkg_contents SET last_change = ? WHERE table_name = ?",
                             (EDITED_AT, table))
        finally:
            conn.close()

    def full_state(self) -> list[Any]:
        """Todo lo que registra la procedencia (con la caché) y las tablas de datos."""
        with self.project.read() as conn:
            found = [conn.execute(f"SELECT * FROM {table} ORDER BY fid").fetchall()
                     for table in ("gb_input", "gb_input_file", "gb_operation",
                                   "gb_operation_io", "gb_dataset", "gb_dataset_change",
                                   "gb_event", "gb_parameter")]
            found.append(conn.execute("SELECT * FROM gb_stale ORDER BY 1, 2, 3, 4").fetchall())
            found.append(conn.execute("SELECT table_name, last_change FROM gpkg_contents "
                                      "ORDER BY 1").fetchall())
            for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                                         "AND name LIKE 'res^_%' ESCAPE '^' ORDER BY 1"
                                         ).fetchall():
                found.append(conn.execute(f'SELECT * FROM "{table}" ORDER BY fid').fetchall())
        return found

    def stale_names(self) -> set[str]:
        """Los datos vivos obsoletos, según la caché."""
        return {item.name for item in stale_mod.stale_items(self.project).items
                if item.item_kind == "dataset"}

    def external_edits(self) -> list[dict[str, Any]]:
        return self.rows("gb_operation", "op_type = ?", (contract.EXTERNAL_EDIT,))

    def assertReady(self, result: Any) -> Any:
        self.assertIsInstance(result, gate.Ready, getattr(result, "text", lambda: result)())
        return result

    def assertBlocked(self, result: Any, *kinds: Any) -> Any:
        self.assertIsInstance(result, gate.Blocked, result)
        self.assertEqual(tuple(reason.kind for reason in result.reasons), kinds)
        return result

    def assertUnchanged(self, work: Callable[[], Any]) -> Any:
        before = self.full_state()
        value = work()
        self.assertEqual(self.full_state(), before)
        return value


class ReadyTest(GateCase):
    def test_ready_without_changes_and_rejections(self) -> None:
        """RF-008-09, RF-008-58: sin nada cambiado ni pendiente, la operación se puede
        ejecutar, sin avisos ni nada obsoleto, y la puerta no escribe nada; con «Limites_v1»
        sin tocar, su fuente no se hashea. Un tipo sin registrar, un dato que no está, lo que
        no es un ``Use`` o un estado que no es ``CheckState`` son errores sin escribir nada."""
        age_folders(self.sources)
        never = AssertionError("sin nada que salte, la puerta no hashea nada")
        with (assert_source_untouched(self.sources),
              mock.patch.object(gate, "read_steps", side_effect=never),
              mock.patch.object(external, "content_digest", side_effect=never)):
            result = self.assertUnchanged(lambda: self.can_run(Use("res_area", "area")))
        self.assertReady(result)
        self.assertEqual((result.notices, result.stale), ((), ()))
        self.assertReady(self.can_run())
        self.assertReady(self.can_run(Use(self.record.uid, "limit", kind="input")))
        with self.assertRaises(ProvenanceError) as caught:
            self.can_run(op_type="res.no_such")
        self.assertEqual(caught.exception.code, "core.operation_unregistered")
        with self.assertRaises(ProvenanceError) as caught:
            self.can_run(Use("res_no_esta", "area"))
        self.assertEqual(caught.exception.code, "core.operation_dataset_unknown")
        with self.assertRaises(TypeError):
            gate.can_run(self.project, PLAN.op_type, ["res_area"], pending=self.state)
        with self.assertRaises(TypeError):
            gate.can_run(self.project, PLAN.op_type, [], pending=None)

    def test_public_api_and_check_state(self) -> None:
        """RF-008-58 (plan §5.1): ``core.provenance`` reexporta la puerta al usarla (importar
        el paquete no la carga); ``CheckState`` empieza sin nada pendiente, pide cada hash una
        vez y rechaza lo que no es un uid o un ``PendingItem``."""
        for name in provenance.GATE_API:
            with self.subTest(name=name):
                self.assertIn(name, provenance.__all__)
                self.assertIn(name, dir(provenance))
                self.assertIs(getattr(provenance, name), getattr(gate, name))
        tree = ast.parse(Path(provenance.__file__).read_text(encoding="utf-8"))
        imported = {alias.name for node in tree.body if isinstance(node, ast.ImportFrom)
                    for alias in node.names} | {node.module for node in tree.body
                                                if isinstance(node, ast.ImportFrom)}
        self.assertNotIn("gate", imported)
        state = gate.CheckState()
        self.assertFalse(state.running)
        self.assertFalse(state.is_pending("dataset", "x"))
        item = gate.PendingItem(ItemKind.INPUT, "x", "Limites_v1", PendingReason.HASHING)
        self.assertTrue(state.request_hash(item))
        self.assertFalse(state.request_hash(item))
        self.assertTrue(state.awaiting("input", "x"))
        self.assertFalse(state.awaiting("dataset", "x"))
        state.hashed("input", "x")
        self.assertEqual(state.requests, ())
        state.start(inputs=["x"], datasets=[])
        self.assertEqual((state.is_pending("input", "x"), state.is_pending("dataset", "x")),
                         (True, False))
        for bad in (lambda: state.request_hash("x"), lambda: state.start(inputs="x"),
                    lambda: state.checked(datasets=[1])):
            with self.assertRaises(TypeError):
                bad()


class ChangedInputTest(GateCase):
    def test_changed_upstream_input_blocks_with_its_warning_and_three_choices(self) -> None:
        """RF-008-10, RF-008-09: con ``Limites_v2`` en lugar de ``v1`` (un vértice movido), la
        puerta comprueba antes de operar la fuente de la entrada que está aguas arriba de
        ``res_area`` (dos operaciones más arriba, no solo la directa), la hashea, la registra
        «cambiada» y se niega con el aviso de la spec §8 (lo que depende de ella y la fecha de
        la fuente) y sus tres salidas: Actualizar, Mantener la copia y Cancelar. Igual si la
        consume directamente o lee lo importado; una operación que no depende de ella se
        ejecuta. Nada se escribe junto a la fuente."""
        moment = self.replace(data.BOUNDARY_V2)
        now = self.later()
        age_folders(self.sources)
        with assert_source_untouched(self.sources):
            result = self.can_run(Use("res_area", "area"))
        (reason,) = self.assertBlocked(result, BlockKind.INPUT_CHANGED).reasons
        text = self.changed_text(self.record, "4 datos, 2 operaciones y 0 cifras",
                                 _local_ns(moment))
        self.assertEqual(reason.text(), text)
        self.assertEqual(result.text(), text)
        self.assertEqual((reason.item_kind, reason.uid, reason.name),
                         (ItemKind.INPUT, self.record.uid, "Limites_v1"))
        self.assertEqual(reason.choices, (Choice.UPDATE, Choice.KEEP, Choice.CANCEL))
        self.assertEqual([gate.choice_label(choice) for choice in reason.choices],
                         ["Actualizar", "Mantener la copia", "Cancelar"])
        self.assertEqual([gate.choice_label(choice, "en") for choice in reason.choices],
                         ["Update", "Keep the copy", "Cancel"])
        self.assertTrue(reason.text("en").startswith(
            "Input «Limites_v1» has changed since it was registered ("))
        row = self.input_row(self.record.uid)
        self.assertEqual((row["status"], row["seen_sha256"], row["status_at"]),
                         ("changed", self.content_of(self.target), now))
        (event,) = self.logged(events.EventKind.INPUT_CHANGED)
        self.assertEqual((event.entity_uid, event.message), (self.record.uid, text))
        # Ya registrada: se vuelve a negar sin hashear ni escribir nada.
        self.hashed = []
        for uses in ([Use("res_area", "area")], [Use("res_limites", "boundary")],
                     [Use("Limites_v1", "limit", kind="input")]):
            with self.subTest(uses=uses):
                found = self.assertUnchanged(lambda u=uses: self.can_run(*u))
                (again,) = self.assertBlocked(found, BlockKind.INPUT_CHANGED).reasons
                self.assertEqual(again.text(), text)
        self.assertReady(self.can_run())
        self.assertEqual(self.external_edits(), [])

    def test_accumulated_data_and_a_source_sent_to_a_job(self) -> None:
        """RF-008-10, RF-008-13, RF-008-58 (plan §5.4.5): el dato acumulado de una tabla común
        depende de las entradas cuya importación lo escribió; una fuente externa cuyo lector no
        estima su tiempo va al trabajo de hash: «pendiente», sin leerla; una no localizable se
        avisa y se sigue con lo importado; cambiada sin decidir, se niega."""
        collars, _import = self.load(self.collars(), ROWS_B, table="res_ensayos",
                                     dataset="res_ensayos_b", shared=True)
        result = self.assertReady(self.can_run(Use("res_ensayos", "assays")))
        self.assertEqual([notice.code for notice in result.notices], ["core.input_unreachable"])
        source = self.sources / "collares.csv"
        source.write_bytes(b"sondeo;este;norte;cota;profundidad\n")
        result = self.assertUnchanged(lambda: self.can_run(Use("res_ensayos", "assays")))
        self.assertEqual(result.items, (gate.PendingItem(
            ItemKind.INPUT, collars.uid, "collares", PendingReason.HASHING),))
        # Cambiada sin decidir: se niega aunque su hash siga pedido.
        self.detect(collars.uid, hashing.sha256_bytes(b"otras bocas"))
        (reason,) = self.assertBlocked(self.can_run(Use("res_ensayos", "assays")),
                                       BlockKind.INPUT_CHANGED).reasons
        self.assertEqual((reason.uid, reason.name), (collars.uid, "collares"))
        self.assertTrue(reason.text().startswith("La entrada «collares» ha cambiado"))
        source.unlink()
        self.state.hashed(ItemKind.INPUT, collars.uid)
        self.assertBlocked(self.can_run(Use("res_ensayos", "assays")), BlockKind.INPUT_CHANGED)

    def test_kept_copy_runs_until_the_source_changes_again(self) -> None:
        """RF-008-12, RF-008-10: con «se mantiene la copia» la operación se ejecuta sin aviso
        y la fuente, tal como se vio, no se vuelve a hashear; si cambia otra vez, la puerta la
        vuelve a dejar «cambiada» y se niega."""
        self.replace(data.BOUNDARY_V2)
        self.assertBlocked(self.can_run(Use("res_area", "area")), BlockKind.INPUT_CHANGED)
        self.write(lambda conn: inputs.keep_copy(conn, self.project, self.record.uid,
                                                 reason="se sigue con la entrega anterior"))
        result = self.assertUnchanged(lambda: self.can_run(Use("res_area", "area")))
        self.assertReady(result)
        self.assertEqual(result.notices, ())
        self.assertEqual(self.input_row(self.record.uid)["status"], "kept")
        self.third_version()
        self.assertBlocked(self.can_run(Use("res_area", "area")), BlockKind.INPUT_CHANGED)
        self.assertEqual(self.input_row(self.record.uid)["status"], "changed")


class DatasetStateTest(GateCase):
    def test_missing_blocked_or_damaged_dataset_is_refused_naming_it(self) -> None:
        """RF-008-57, RF-008-56 (ADR-0025 §4): una operación que consume un dato que falta,
        está bloqueado o dañado se niega nombrándolo (el bloqueado, con el texto de la spec
        §8), sin escribir nada; uno así aguas arriba no la niega: lo que consume queda
        obsoleto y se dice (``stale``)."""
        cases = (
            ("missing", BlockKind.DATASET_MISSING,
             "Falta el dato «res_area» (res_area): recalcúlelo o reimpórtelo; mientras falte, "
             "no se ejecuta ninguna operación que lo consuma."),
            ("blocked", BlockKind.DATASET_BLOCKED,
             "La capa «res_area» se editó fuera de Geoblender y no se edita a mano: acepte la "
             "edición con un motivo, recalcule o reimporte"),
        )
        for status, kind, text in cases:
            with self.subTest(status=status):
                self.set_status("res_area", status)
                result = self.assertUnchanged(lambda: self.can_run(Use("res_area", "area")))
                (reason,) = self.assertBlocked(result, kind).reasons
                self.assertEqual((reason.item_kind, reason.uid, reason.name, reason.choices),
                                 (ItemKind.DATASET, self.uid("res_area"), "res_area", ()))
                self.assertEqual(reason.text(), text)
                self.set_status("res_area", "current")
        self.set_status("res_limites", "damaged")
        result = self.assertUnchanged(lambda: self.can_run(Use("res_limites", "boundary")))
        (reason,) = self.assertBlocked(result, BlockKind.DATASET_DAMAGED).reasons
        self.assertEqual(reason.text(), (
            "El dato «res_limites», lo importado de la entrada «Limites_v1», está dañado: "
            "cambió o perdió su protección; solo se puede reimportar."))
        self.set_status("res_limites", "current")
        self.set_status("res_contorno", "blocked")
        result = self.assertReady(self.can_run(Use("res_area", "area")))
        self.assertEqual(result.stale, ("res_area",))

    def test_dropped_table_and_lost_protection_are_found_before_operating(self) -> None:
        """RF-008-57 (ADR-0025 §4 y §6): una tabla eliminada desde otro programa queda «falta»
        (con su evento y lo que depende de ella obsoleto) antes de operar, y la operación que
        la consume se niega; lo importado con una columna borrada (``DROP COLUMN``, que no
        dispara nada) o que perdió sus disparadores de protección queda «dañado» y lo que lo
        consume se niega."""
        self.foreign('DROP TABLE "res_area"')  # sigue en gpkg_contents
        result = self.can_run(Use("res_area", "area"))
        self.assertBlocked(result, BlockKind.DATASET_MISSING)
        self.assertEqual(self.dataset("res_area").status, datasets.DatasetStatus.MISSING)
        (event,) = self.logged(events.EventKind.DATASET_MISSING)
        self.assertEqual((event.entity_kind, event.entity_uid),
                         ("dataset", self.uid("res_area")))
        self.assertEqual([notice.code for notice in result.notices], ["core.dataset_missing"])

        before = self.dataset("res_limites")
        self.foreign('ALTER TABLE "res_limites" DROP COLUMN ley')
        result = self.can_run(Use("res_limites", "boundary"))
        self.assertBlocked(result, BlockKind.DATASET_DAMAGED)
        self.assertEqual(self.dataset("res_limites").status, datasets.DatasetStatus.DAMAGED)
        (event,) = self.logged(events.EventKind.DATASET_DAMAGED)
        self.assertEqual((event.entity_uid, event.data["input_uid"]),
                         (before.uid, self.record.uid))
        self.assertNotEqual(event.data["seen_sha256"], before.content_sha256)
        self.assertEqual(self.dataset("res_limites").content_sha256, before.content_sha256)
        self.assertIn("res_contorno", self.stale_names())
        # Ya registrados: no se vuelve a escribir nada.
        self.assertUnchanged(lambda: self.can_run(Use("res_limites", "boundary")))

        collars, _import = self.load(self.collars(), ROWS_B, table="res_ensayos",
                                     dataset="res_ensayos_b", shared=True)
        names = tracking.protection_trigger_names("res_ensayos",
                                                  self.dataset("res_ensayos_b").selector)
        self.foreign(f'DROP TRIGGER "{names[1]}"')
        self.assertBlocked(self.can_run(Use("res_ensayos_b", "assays")),
                           BlockKind.DATASET_DAMAGED)
        self.assertEqual(self.dataset("res_ensayos_b").status, datasets.DatasetStatus.DAMAGED)
        self.assertNotIn("seen_sha256", self.logged(events.EventKind.DATASET_DAMAGED)[-1].data)


class ExternalEditTest(GateCase):
    def test_editable_layer_edited_after_opening_is_recorded_and_seen_stale(self) -> None:
        """RF-008-21, RF-008-09 (plan §5.4.5, I-4): el límite editable ``res_contorno``,
        editado desde otra conexión después de abrir, salta en el prefiltro de lo que está
        aguas arriba de ``res_area``; la puerta lo hashea y registra la edición externa antes
        de operar (una operación ``core.external_edit`` hecha fuera, que consume la versión
        anterior y produce la nueva, su cambio y su evento), sin deshacerla, y lo que depende
        de él queda obsoleto: la operación se puede ejecutar y ve ``res_area`` obsoleto, con
        el aviso que lo nombra. La siguiente vez ya no salta."""
        before = self.dataset("res_contorno")
        self.foreign('UPDATE "res_contorno" SET valor = 2.5 WHERE codigo = ?', ("C-02",),
                     table="res_contorno")
        now = self.later()
        result = self.assertReady(self.can_run(Use("res_area", "area")))
        self.assertEqual(result.stale, ("res_area",))
        self.assertEqual([notice.text() for notice in result.notices], [
            "El dato «res_contorno» se editó fuera de Geoblender: se registra la edición "
            "externa y lo que depende de él queda obsoleto."])
        (edit,) = self.external_edits()
        self.assertEqual((edit["status"], edit["executor"], edit["module"], edit["started_at"],
                          edit["finished_at"], edit["repeatable"]),
                         ("done", "external", "core", now, now, 0))
        after = self.dataset("res_contorno")
        self.assertNotEqual(after.content_sha256, before.content_sha256)
        self.assertEqual((after.status, after.operation_uid, after.tracked_last_change),
                         (datasets.DatasetStatus.CURRENT, edit["uid"], EDITED_AT))
        io = self.rows("gb_operation_io", "operation_uid = ?", (edit["uid"],))
        self.assertEqual([(row["direction"], row["item_uid"], row["content_sha256"])
                          for row in io],
                         [("in", before.uid, before.content_sha256),
                          ("out", before.uid, after.content_sha256)])
        (change,) = self.rows("gb_dataset_change", "operation_uid = ?", (edit["uid"],))
        self.assertEqual((change["from_sha256"], change["to_sha256"]),
                         (before.content_sha256, after.content_sha256))
        (event,) = self.logged(events.EventKind.EXTERNAL_EDIT)
        self.assertEqual((event.entity_kind, event.entity_uid, event.data["operation_uid"]),
                         ("dataset", before.uid, edit["uid"]))
        self.assertEqual(self.stale_names(), {"res_area"})
        with self.project.read() as conn:
            self.assertEqual(conn.execute('SELECT valor FROM "res_contorno" WHERE codigo = ?',
                                          ("C-02",)).fetchone(), (2.5,))
        # Ya registrada: no salta, no escribe y lo que consume el límite editado está al día.
        self.assertReady(self.assertUnchanged(lambda: self.can_run(Use("res_area", "area"))))
        fresh = self.assertReady(self.can_run(Use("res_contorno", "outline")))
        self.assertEqual((fresh.notices, fresh.stale), ((), ()))
        # El límite editado sigue dependiendo de la entrada de la que se calculó.
        self.replace(data.BOUNDARY_V2)
        self.assertBlocked(self.can_run(Use("res_contorno", "outline")),
                           BlockKind.INPUT_CHANGED)

    def test_same_content_and_rebuilt_table_are_not_an_edit(self) -> None:
        """RF-008-21 (ADR-0025 §6): la tabla reescrita con el mismo contenido (otro
        ``last_change``) o sin sus disparadores de seguimiento (rehecha) salta, se hashea y no
        es una edición: no avisa, anota el seguimiento, repone los disparadores y la siguiente
        vez no salta."""
        before = self.dataset("res_bocas")
        self.foreign(f'DROP TRIGGER "{tracking.tracking_trigger_names("res_bocas")[0]}"')
        result = self.assertReady(self.can_run(Use("res_bocas", "collars")))
        self.assertEqual((result.notices, result.stale), ((), ()))
        with self.project.read() as conn:
            self.assertTrue(tracking.table_states(conn, ["res_bocas"])["res_bocas"].tracked)
        self.foreign('UPDATE "res_bocas" SET valor = valor', table="res_bocas")
        now = self.later()
        result = self.assertReady(self.can_run(Use("res_bocas", "collars")))
        self.assertEqual((result.notices, result.stale), ((), ()))
        self.assertEqual(self.external_edits(), [])
        after = self.dataset("res_bocas")
        self.assertEqual((after.content_sha256, after.operation_uid, after.status),
                         (before.content_sha256, before.operation_uid, before.status))
        self.assertEqual((after.tracked_last_change, after.checked_at), (EDITED_AT, now))
        self.assertUnchanged(lambda: self.can_run(Use("res_bocas", "collars")))

    def test_layer_not_editable_by_hand_is_blocked(self) -> None:
        """RF-008-56, RF-008-21: ``res_bocas``, que su módulo no declara editable a mano,
        cambiada desde otra conexión con un ``ALTER TABLE`` (no dispara nada: lo delata la
        huella de su SQL): además de la edición externa, queda bloqueada y la operación que la
        consume se niega con el texto de la spec §8; la siguiente vez sigue negándose sin
        registrar otra edición."""
        self.foreign('ALTER TABLE "res_bocas" ADD COLUMN nota TEXT')
        result = self.can_run(Use("res_bocas", "collars"))
        (reason,) = self.assertBlocked(result, BlockKind.DATASET_BLOCKED).reasons
        self.assertEqual(reason.text(), (
            "La capa «res_bocas» se editó fuera de Geoblender y no se edita a mano: acepte la "
            "edición con un motivo, recalcule o reimporte"))
        self.assertEqual(self.dataset("res_bocas").status, datasets.DatasetStatus.BLOCKED)
        self.assertEqual(len(self.external_edits()), 1)
        self.assertEqual([notice.code for notice in result.notices], ["core.external_edit"])
        (event,) = self.logged(events.EventKind.EXTERNAL_EDIT)
        self.assertTrue(event.data["blocked"])
        again = self.assertUnchanged(lambda: self.can_run(Use("res_bocas", "collars")))
        self.assertBlocked(again, BlockKind.DATASET_BLOCKED)

    def test_read_only_detects_without_writing(self) -> None:
        """RF-008-58, RF-008-56, RF-008-10: en solo lectura la puerta detecta lo editado fuera y
        la fuente cambiada sin registrar nada y se niega: el proyecto no admite la operación."""
        self.foreign('INSERT INTO "res_bocas" (codigo, valor) VALUES (?, ?)', ("S-02", 11.0),
                     table="res_bocas")
        self.replace(data.BOUNDARY_V2)
        self.project.set_read_only(project_model.ReadOnlyCode.LOCKED, "otra sesión")
        result = self.assertUnchanged(lambda: self.can_run(Use("res_bocas", "collars")))
        self.assertBlocked(result, BlockKind.READ_ONLY, BlockKind.INPUT_CHANGED,
                           BlockKind.DATASET_BLOCKED)
        self.assertTrue(result.reasons[0].text().startswith(
            "El proyecto «"))
        self.assertEqual(self.input_row(self.record.uid)["status"], "current")


class PendingTest(GateCase):
    def test_waits_while_the_opening_check_has_not_checked_it(self) -> None:
        """RF-008-58: mientras la comprobación de apertura no ha comprobado algo de la cadena,
        la puerta no lo comprueba ella ni escribe nada y devuelve «pendiente» con «Comprobando
        el proyecto…: espere a que termine»; lo que ya se comprobó deja de esperar y, al
        terminar, se ejecuta."""
        self.foreign('UPDATE "res_contorno" SET valor = 3.0', table="res_contorno")
        self.state.start()
        self.assertTrue(self.state.running)
        result = self.assertUnchanged(lambda: self.can_run(Use("res_area", "area")))
        self.assertIsInstance(result, gate.Pending)
        self.assertEqual({(item.item_kind, item.name, item.reason) for item in result.items}, {
            (ItemKind.DATASET, name, PendingReason.CHECKING)
            for name in ("res_area", "res_contorno", "res_limites")
        } | {(ItemKind.INPUT, "Limites_v1", PendingReason.CHECKING)})
        self.assertTrue(result.text().startswith(
            "Comprobando el proyecto…: espere a que termine ("))
        self.assertTrue(result.text("en").startswith("Checking the project…: wait until"))
        self.state.start(datasets=[self.uid("res_contorno")], inputs=[])
        result = self.assertUnchanged(lambda: self.can_run(Use("res_area", "area")))
        self.assertEqual([(item.name, item.reason) for item in result.items],
                         [("res_contorno", PendingReason.CHECKING)])
        self.state.checked(datasets=[self.uid("res_contorno")])
        self.assertFalse(self.state.running)
        self.assertEqual(len(self.assertReady(self.can_run(Use("res_area", "area"))).notices),
                         1)
        self.state.start()
        self.state.finish()
        self.assertFalse(self.state.running)
        self.assertReady(self.can_run(Use("res_area", "area")))

    def test_long_hash_is_pending_and_requested(self) -> None:
        """RF-008-58, RF-008-09 (plan §5.4.5): si un prefiltro salta y el hash no cabe en el
        tiempo de la puerta, devuelve «pendiente» sin registrar nada y pide el hash a
        ``CheckState`` una vez; mientras siga pedido, no lo vuelve a intentar; hecho el hash,
        la orden se repite y se ejecuta. Lo mismo con la fuente de una entrada y con un
        fichero cuyo lector estima más de lo que cabe (sin leerlo)."""
        self.foreign('UPDATE "res_contorno" SET valor = 3.0', table="res_contorno")
        with mock.patch.object(gate, "HASH_LIMIT_S", 0.0):
            result = self.assertUnchanged(lambda: self.can_run(Use("res_area", "area")))
            self.assertIsInstance(result, gate.Pending)
            wanted = gate.PendingItem(ItemKind.DATASET, self.uid("res_contorno"), "res_contorno",
                                      PendingReason.HASHING)
            self.assertEqual(result.items, (wanted,))
            self.assertEqual(self.state.requests, (wanted,))
            self.assertEqual(result.text(), "Comprobando el contenido de «res_contorno»: "
                                             "espere a que termine y repita la orden.")
        self.assertIsInstance(self.can_run(Use("res_area", "area")), gate.Pending)
        self.assertEqual(self.state.requests, (wanted,))
        self.assertEqual(self.external_edits(), [])
        self.state.hashed(ItemKind.DATASET, wanted.uid)
        self.assertEqual(self.state.requests, ())
        self.assertReady(self.can_run(Use("res_area", "area")))
        self.assertEqual(len(self.external_edits()), 1)

        self.replace(data.BOUNDARY_V2)
        with mock.patch.object(gate, "HASH_LIMIT_S", 0.0):
            result = self.assertUnchanged(lambda: self.can_run(Use("res_area", "area")))
        self.assertEqual(result.items, (gate.PendingItem(
            ItemKind.INPUT, self.record.uid, "Limites_v1", PendingReason.HASHING),))

    def test_hash_that_runs_out_of_time_midway_is_pending(self) -> None:
        """RF-008-58: un hash que empieza y se queda sin tiempo a medias (el de un dato, en su
        transacción, que se deshace; el de una fuente, entre dos trozos) deja lo mismo:
        «pendiente», pedido y nada escrito."""
        self.foreign('UPDATE "res_contorno" SET valor = 3.0', table="res_contorno")
        self.replace(data.BOUNDARY_V2)
        with mock.patch.object(gate._Gate, "late", lambda gate_run: True):
            result = self.assertUnchanged(lambda: self.can_run(Use("res_area", "area")))
        self.assertEqual([(item.name, item.reason) for item in result.items],
                         [("res_contorno", PendingReason.HASHING),
                          ("Limites_v1", PendingReason.HASHING)])
        self.assertEqual(self.state.requests, result.items)

    def test_file_whose_reader_estimates_too_long_is_not_read(self) -> None:
        """RF-008-58: un fichero de ``rasters/`` cambiado cuyo lector estima más de lo que cabe
        en la puerta no se lee: «pendiente» y su hash, pedido."""
        self.enterContext(readers_registered(SLOW))
        path = Path(self.project.root, *TERRAIN_FILE.split("/"))
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"rejilla v1")
        terrain = operations.begin_operation(self.project, TERRAIN.op_type, settings={},
                                             executor="blender")
        self.write(lambda conn: terrain.complete(conn, outputs=[datasets.DatasetSpec(
            "res_mdt", "res", "raster", "rasters", TERRAIN_FILE, reader=SLOW.id,
            role="terrain")]))
        _SLOW_READS.clear()
        path.write_bytes(b"rejilla v2, otra")
        os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 10**9))
        result = self.assertUnchanged(lambda: self.can_run(Use("res_mdt", "terrain")))
        self.assertEqual(result.items, (gate.PendingItem(
            ItemKind.DATASET, self.uid("res_mdt"), "res_mdt", PendingReason.HASHING),))
        self.assertEqual(_SLOW_READS, [])
        # El hash de un dato se para entre dos trozos si se pide (antes de empezar, también).
        record = self.dataset("res_mdt")
        calls: list[int] = []

        def second_call() -> bool:
            calls.append(1)
            return len(calls) > 1

        with self.project.read() as conn:
            for cancelled in (lambda: True, second_call):
                with self.subTest(cancelled=cancelled), \
                        self.assertRaises(readers.ReadCancelled):
                    dataset_registry.content_digest(conn, self.project, record,
                                                    cancelled=cancelled)
            digest = dataset_registry.content_digest(conn, self.project, record)
        self.assertNotEqual(digest.content_sha256, record.content_sha256)
        self.assertEqual((digest.reader, digest.normalizer), (SLOW.id, record.normalizer))
        # Sin su lector (su módulo no está activo) no se puede comprobar: se niega.
        self.state.hashed(ItemKind.DATASET, self.uid("res_mdt"))
        readers.unregister_reader(SLOW.id)
        result = self.assertUnchanged(lambda: self.can_run(Use("res_mdt", "terrain")))
        (reason,) = self.assertBlocked(result, BlockKind.DATASET_UNREADABLE).reasons
        self.assertTrue(reason.text().startswith(
            "No se puede leer el dato «res_mdt» para comprobarlo ("))
