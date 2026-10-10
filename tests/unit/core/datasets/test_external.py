# SPDX-License-Identifier: GPL-3.0-or-later
"""Datos del proyecto cambiados fuera de Geoblender (spec 008, T32; RF-008-21, RF-008-56,
RF-008-57; RF-008-52, RF-008-53, RF-008-58; ADR-0025 §4 y §6; plan 008 §5.2.2, §5.3.1,
§5.4.2, §5.4.6 y §5.4.9).

``core.datasets.external.external_check_steps`` comprueba, por pasos medidos por tiempo, los
datos seguidos del proyecto (nunca ``exports/``) y los originales de las entradas:

- prefiltro (``gpkg_contents.last_change``, el SQL y los disparadores de su tabla, o el tamaño
  y la fecha de su fichero) y hash de contenido de lo que salta, con su lector y su
  normalizador;
- otro contenido en una capa editable: edición externa (``core.external_edit``) y lo que
  depende de ella, obsoleto, sin deshacer nada; en una no editable, además, bloqueada hasta
  aceptarla con motivo (``accept_edit``), recalcularla o reimportarla; lo importado que cambia
  o pierde su protección, «dañado» (solo se reimporta); lo que ya no está, «falta» (y vuelve a
  vigente si reaparece con su contenido);
- un original de ``originals/`` con otra huella o que falta: aviso y no sirve para
  reimportar;
- todo se registra al final, en una transacción, salvo lo que cambió mientras se comprobaba;
  en solo lectura no se escribe nada.

Cada prueba usa el proyecto de ``test_gate`` (esquema 2, reloj simulado): la entrada
«Limites_v1» importada en ``res_limites``; ``res_contorno`` (editable a mano) y ``res_bocas``
(no editable) calculados de ella; ``res_area`` de ``res_contorno``.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest import mock

from tests.support.dataset_tables import rebuild_like_gdal
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.provenance_readers import registered as readers_registered
from tests.unit.core.inputs.test_check import ROWS
from tests.unit.core.inputs.test_registry import (
    MTIME_NS,
    NOT_APPLICABLE,
    ROWS_B,
    SESSION,
    SOURCE,
    _digest,
)
from tests.unit.core.provenance.test_gate import (
    EDITED_AT,
    PLAN,
    GateCase,
    _spec,
    _table,
)

external = import_geoblender("core.datasets.external")
datasets = import_geoblender("core.datasets")
tracking = import_geoblender("core.datasets.tracking")
inputs_model = import_geoblender("core.inputs.model")
provenance = import_geoblender("core.provenance")
operations = import_geoblender("core.provenance.operations")
messages = import_geoblender("core.provenance.messages")
gate = import_geoblender("core.provenance.gate")
readers = import_geoblender("core.content.readers")
builtin = import_geoblender("core.content.builtin")
events = import_geoblender("core.project.events")
project_model = import_geoblender("core.project.model")
session_mod = import_geoblender("core.project.session")
hashing = import_geoblender("core.hashing")

ProvenanceError = messages.ProvenanceError
Use = operations.Use
Verdict = external.DatasetVerdict
Offer = external.Offer
Status = datasets.DatasetStatus


def _read_bytes(request: Any) -> Iterator[float]:
    """Un lector de rejillas de prueba: los bytes del fichero, por trozos."""
    yield from builtin.read_document(request)


BYTES = readers.ContentReader("test.bytes_grid", 1, ("raster",), False, False, None, _read_bytes)
"""El lector de las rejillas de prueba de ``rasters/``."""
GRID = provenance.OperationDef("res.grid", "1.0", "res", "Test grid", True,
                               recompute=lambda request: None)
"""Una operación que se puede repetir (escribe la rejilla y las cotas)."""
REPORT = provenance.OperationDef("res.report", "1.0", "res", "Test report", False)
TERRAIN_FILE = "rasters/res_mdt.bin"
REPORT_FILE = "exports/res_informe.pdf"
EDITED_TEXT = ("El dato «{name}» se editó fuera de Geoblender: se registra la edición externa "
               "y lo que depende de él queda obsoleto.")
BLOCKED_TEXT = ("La capa «{name}» se editó fuera de Geoblender y no se edita a mano: acepte la "
                "edición con un motivo, recalcule o reimporte")
MISSING_TEXT = ("Falta el dato «{name}» ({locator}): recalcúlelo o reimpórtelo; mientras "
                "falte, no se ejecuta ninguna operación que lo consuma.")
DAMAGED_TEXT = ("El dato «{name}», lo importado de la entrada «{input}», está dañado: cambió o "
                "perdió su protección; solo se puede reimportar.")
ORIGINAL = b"sondeo;este;norte;cota\nS-01;715000,1;4400000,2;352,4\n"


class ExternalCase(GateCase):
    """El proyecto de ``test_gate`` con la operación repetible «res.grid», el informe de
    ``exports/`` y el lector de las rejillas de prueba."""

    def setUp(self) -> None:
        super().setUp()
        self.enterContext(registered(GRID, REPORT))
        self.enterContext(readers_registered(BYTES))

    # --- Ayudas -----------------------------------------------------------------------------

    def check(self, **kw: Any) -> Any:
        """Todos los pasos de la comprobación; su resultado."""
        steps = list(external.external_check_steps(self.project, **kw))
        for step in steps:
            self.assertIsInstance(step, project_model.Progress)
        outcome = steps[-1].result
        self.assertIsInstance(outcome, external.ExternalOutcome)
        return outcome

    def verdicts(self, outcome: Any) -> dict[str, Any]:
        return {item.record.name: item.verdict for item in outcome.findings}

    def finding(self, outcome: Any, name: str) -> Any:
        (found,) = [item for item in outcome.findings if item.record.name == name]
        return found

    def path(self, locator: str) -> Path:
        return Path(self.project.root, *locator.split("/"))

    def qgis(self, sql: str, args: tuple[Any, ...] = (), *, table: str, at: str) -> None:
        """Otro programa cambia ``table`` y deja su ``last_change`` en ``at``."""
        conn = sqlite3.connect(self.project.database_path, isolation_level=None)
        try:
            conn.execute(sql, args)
            conn.execute("UPDATE gpkg_contents SET last_change = ? WHERE table_name = ?",
                         (at, table))
        finally:
            conn.close()

    def rebuild(self, table: str) -> None:
        """Otro programa rehace ``table`` como GDAL al cambiar un campo (sin disparadores)."""
        conn = sqlite3.connect(self.project.database_path, isolation_level=None)
        try:
            rebuild_like_gdal(conn, table)
        finally:
            conn.close()

    def offers(self, name: str) -> tuple[Any, ...]:
        return self.read(lambda conn: external.offers(conn, self.uid(name)))

    def terrain(self, data: bytes = b"rejilla v1") -> Any:
        """La rejilla ``res_mdt`` que escribe «res.grid» (repetible) y ``res_plano``, que
        calcula «res.plan» a partir de ella."""
        path = self.path(TERRAIN_FILE)
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)
        grid = operations.begin_operation(self.project, GRID.op_type, settings={},
                                          executor="blender")
        self.write(lambda conn: grid.complete(conn, outputs=[datasets.DatasetSpec(
            "res_mdt", "res", "raster", "rasters", TERRAIN_FILE, reader=BYTES.id,
            role="terrain")]))
        plan = operations.begin_operation(self.project, PLAN.op_type, settings={},
                                          executor="blender", inputs=[Use("res_mdt", "terrain")])
        self.write(lambda conn: (_table(conn, "res_plano", (("P-1", 1.0),)),
                                 plan.complete(conn, outputs=[_spec("res_plano", "plan")])))
        return grid

    def report(self) -> None:
        """El informe ``res_informe`` de ``exports/`` (sin seguimiento)."""
        path = self.path(REPORT_FILE)
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"%PDF-1.7 informe")
        handle = operations.begin_operation(self.project, REPORT.op_type, settings={},
                                            executor="blender")
        self.write(lambda conn: handle.complete(conn, outputs=[datasets.DatasetSpec(
            "res_informe", "res", "report", "exports", REPORT_FILE,
            reader=builtin.DOCUMENT.id, role="report")]))

    def levels(self, op_type: str = GRID.op_type, *, supersedes: str | None = None,
               value: float = 1.0) -> Any:
        """Las cotas ``res_cotas`` (no editables) que escribe una operación de tipo
        ``op_type`` (las crea la primera vez); con ``supersedes``, las recalcula."""
        new = self.dataset("res_cotas") is None
        handle = operations.begin_operation(self.project, op_type, settings={},
                                            executor="blender", supersedes=supersedes)

        def work(conn: sqlite3.Connection) -> Any:
            if new:
                _table(conn, "res_cotas", (("N-1", value),))
            else:
                conn.execute('UPDATE "res_cotas" SET valor = ?', (value,))
            return handle.complete(conn, outputs=[_spec("res_cotas", "levels")])

        self.write(work)
        return handle

    def plans(self) -> Any:
        """Una entrada documental de dos ficheros (plano y memoria), registrada."""
        declarations = inputs_model.input_declarations(NOT_APPLICABLE, NOT_APPLICABLE, {})
        return self.register(inputs_model.InputSpec(
            "planos", "document", "res", SOURCE.id,
            files=[inputs_model.SourceFile("../../fuentes/plano.dxf", "main", "original"),
                   inputs_model.SourceFile("../../fuentes/plano.txt", "sidecar", "original")],
            file_prints=[inputs_model.SourcePrint(hashing.sha256_bytes(b"dxf"), size=3,
                                                  mtime_ns=MTIME_NS),
                         inputs_model.SourcePrint(hashing.sha256_bytes(b"txt"), size=3,
                                                  mtime_ns=MTIME_NS)],
            digest=_digest("planos", "document", declarations),
            crs_h=NOT_APPLICABLE, crs_v=NOT_APPLICABLE,
        ))

    def store_original(self, input_uid: str, name: str, data: bytes, ord_: int = 0) -> Path:
        """El original del fichero ``ord_`` (por su orden) de la entrada ``input_uid`` guardado
        en ``originals/<uid>/`` con su huella, como lo deja ``store_originals_steps``."""
        path = self.path(f"originals/{input_uid}/{name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        found = path.stat()
        ords = [row["ord"] for row in self.rows("gb_input_file", "input_uid = ?", (input_uid,))]

        def work(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE gb_input_file SET original_path = ?, original_sha256 = ?, "
                "original_size = ?, original_mtime_ns = ? WHERE input_uid = ? AND ord = ?",
                (f"originals/{input_uid}/{name}", hashing.sha256_bytes(data), found.st_size,
                 found.st_mtime_ns, input_uid, ords[ord_]))
            conn.execute("UPDATE gb_input SET original = 'stored' WHERE uid = ?", (input_uid,))

        self.write(work)
        return path

    def original_row(self, input_uid: str) -> dict[str, Any]:
        (row,) = self.rows("gb_input_file", "input_uid = ?", (input_uid,))
        return row

    def touch(self, path: Path) -> int:
        """Otra fecha (un segundo después) para ``path``; la devuelve."""
        mtime = path.stat().st_mtime_ns + 10**9
        os.utime(path, ns=(mtime, mtime))
        return mtime

    def assertRejected(self, error: type[BaseException], code: str,
                       work: Callable[[sqlite3.Connection], Any]) -> None:
        """``work`` se rechaza en una transacción de escritura sin escribir nada."""
        before = self.full_state()
        with self.assertRaises(error) as caught:
            self.write(work)
        self.assertEqual(getattr(caught.exception, "code", None), code, str(caught.exception))
        self.assertEqual(self.full_state(), before)


class EditedTest(ExternalCase):
    def test_editable_layer_edited_outside_is_recorded_without_undoing_it(self) -> None:
        """RF-008-21 (spec §8, «Límite (capa editable) editado en QGIS»): ``res_contorno``,
        editado desde otra conexión, salta en el prefiltro, se hashea y queda registrado como
        edición externa (``core.external_edit``, hecha fuera, que consume la versión anterior y
        produce la nueva) con su aviso, sin deshacerla; lo que depende de él queda obsoleto y
        no se ofrece nada: es editable. La siguiente vez no salta ni escribe."""
        before = self.dataset("res_contorno")
        self.foreign('UPDATE "res_contorno" SET valor = 2.5 WHERE codigo = ?', ("C-02",),
                     table="res_contorno")
        now = self.later()
        outcome = self.check()
        self.assertTrue(outcome.recorded)
        finding = self.finding(outcome, "res_contorno")
        self.assertEqual((finding.verdict, finding.status), (Verdict.EDITED, Status.CURRENT))
        self.assertEqual(outcome.texts(), (EDITED_TEXT.format(name="res_contorno"),))
        self.assertTrue(outcome.texts("en")[0].startswith(
            "Dataset «res_contorno» was edited outside Geoblender"))
        (edit,) = self.external_edits()
        self.assertEqual((edit["uid"], edit["executor"], edit["status"], edit["finished_at"]),
                         (finding.operation_uid, "external", "done", now))
        io = self.rows("gb_operation_io", "operation_uid = ?", (edit["uid"],))
        after = self.dataset("res_contorno")
        self.assertEqual([(row["direction"], row["content_sha256"]) for row in io],
                         [("in", before.content_sha256), ("out", after.content_sha256)])
        self.assertEqual((after.status, after.tracked_last_change), (Status.CURRENT, EDITED_AT))
        (event,) = self.logged(events.EventKind.EXTERNAL_EDIT)
        self.assertEqual(event.entity_uid, before.uid)
        self.assertEqual(self.stale_names(), {"res_area"})
        self.assertEqual(self.table("res_contorno", "codigo = ?", ("C-02",))[0][-1], 2.5)
        self.assertEqual(self.offers("res_contorno"), ())
        again = self.assertUnchanged(self.check)
        self.assertEqual((again.findings, again.originals), ((), ()))
        self.assertIn(before.uid, again.checked)


class BlockedTest(ExternalCase):
    def test_layer_not_editable_stays_blocked_until_accepted_or_recomputed(self) -> None:
        """RF-008-56, RF-008-21 (spec §8, «Bocas de sondeos (capa no editable) editadas en
        QGIS»): ``res_bocas`` cambiada desde otra conexión queda registrada como edición
        externa y, además, bloqueada con el texto exacto de la spec §8, sin deshacerla; se
        ofrece aceptar la edición; aceptarla sin motivo o aceptar lo que no está bloqueado se
        rechaza sin escribir nada; con motivo (sin rutas), vuelve a vigente con su evento y se
        puede operar con ella. Unas cotas que escribió por última vez una operación repetible
        (antes, una que no lo es), bloqueadas igual, ofrecen además recalcularlas y dejan de
        estar bloqueadas al recalcularlas."""
        self.foreign('INSERT INTO "res_bocas" (codigo, valor) VALUES (?, ?)', ("S-02", 11.0),
                     table="res_bocas")
        outcome = self.check()
        finding = self.finding(outcome, "res_bocas")
        self.assertEqual((finding.verdict, finding.status), (Verdict.EDITED, Status.BLOCKED))
        self.assertEqual(finding.text(), EDITED_TEXT.format(name="res_bocas") + " "
                         + BLOCKED_TEXT.format(name="res_bocas"))
        self.assertEqual(self.dataset("res_bocas").status, Status.BLOCKED)
        self.assertEqual(len(self.table("res_bocas")), 2)
        self.assertEqual(self.offers("res_bocas"), (Offer.ACCEPT,))
        self.assertEqual([external.offer_label(offer) for offer in Offer],
                         ["Aceptar la edición", "Recalcular", "Reimportar"])
        self.assertEqual([external.offer_label(offer, "en") for offer in Offer],
                         ["Accept the edit", "Recompute", "Reimport"])
        uid = self.uid("res_bocas")
        self.assertRejected(ProvenanceError, "core.accept_edit_reason_missing",
                            lambda conn: external.accept_edit(conn, self.project, uid, "  "))
        self.assertRejected(ProvenanceError, "core.accept_edit_not_blocked",
                            lambda conn: external.accept_edit(conn, self.project,
                                                              self.uid("res_contorno"), "sí"))
        self.assertBlocked(self.can_run(Use("res_bocas", "collars")),
                           gate.BlockKind.DATASET_BLOCKED)
        now = self.later()
        accepted = self.write(lambda conn: external.accept_edit(
            conn, self.project, "res_bocas",
            "La propiedad añade la boca S-02 (Q:\\entregas\\bocas.pdf)"))
        self.assertEqual((accepted.status, accepted.modified_at), (Status.CURRENT, now))
        (event,) = self.logged(events.EventKind.EDIT_ACCEPTED)
        self.assertEqual((event.entity_kind, event.entity_uid, event.message),
                         ("dataset", uid, "Edición externa de «res_bocas» aceptada: La "
                                          "propiedad añade la boca S-02 (bocas.pdf)"))
        self.assertEqual((event.data["reason"], event.data["accepted_by"]),
                         ("La propiedad añade la boca S-02 (bocas.pdf)", SESSION.user_host))
        self.assertReady(self.can_run(Use("res_bocas", "collars")))
        self.assertEqual(self.offers("res_bocas"), ())

        self.levels(PLAN.op_type)
        levels = self.levels(value=2.0)
        self.foreign('UPDATE "res_cotas" SET valor = 9.0', table="res_cotas")
        self.assertEqual(self.verdicts(self.check()), {"res_cotas": Verdict.EDITED})
        self.assertEqual(self.offers("res_cotas"), (Offer.ACCEPT, Offer.RECOMPUTE))
        self.levels(supersedes=levels.uid, value=2.0)
        self.assertEqual(self.dataset("res_cotas").status, Status.CURRENT)
        self.assertEqual(self.check().findings, ())


class DamagedTest(ExternalCase):
    def test_imported_data_changed_or_rebuilt_is_damaged_and_only_reimported(self) -> None:
        """RF-008-52, RF-008-21 (ADR-0025 §4; plan §5.4.9, I-8): lo importado de
        «Limites_v1» con una columna borrada (``DROP COLUMN``, que no dispara nada) y lo
        importado de «collares» en una tabla común rehecha sin disparadores quedan «dañados»,
        con su aviso nombrando su entrada y su evento, y lo que depende de ellos, obsoleto;
        solo se ofrece reimportarlos y aceptar su edición se rechaza; el acumulado de esa
        tabla, con el mismo contenido, no es una edición y recupera sus disparadores. Lo
        dañado ya no se vuelve a comprobar ni se marca «falta» o vigente."""
        self.load(self.collars(), ROWS_B, table="res_ensayos", dataset="res_ensayos_b",
                  shared=True)
        self.foreign('ALTER TABLE "res_limites" DROP COLUMN ley')
        self.rebuild("res_ensayos")
        outcome = self.check()
        self.assertEqual(self.verdicts(outcome), {"res_limites": Verdict.DAMAGED,
                                                  "res_ensayos_b": Verdict.DAMAGED,
                                                  "res_ensayos": Verdict.SAME})
        self.assertEqual(outcome.texts(), (
            DAMAGED_TEXT.format(name="res_limites", input="Limites_v1"),
            DAMAGED_TEXT.format(name="res_ensayos_b", input="collares"),
        ))
        for name in ("res_limites", "res_ensayos_b"):
            with self.subTest(name=name):
                self.assertEqual(self.dataset(name).status, Status.DAMAGED)
                self.assertEqual(self.offers(name), (Offer.REIMPORT,))
        self.assertEqual(len(self.logged(events.EventKind.DATASET_DAMAGED)), 2)
        with self.project.read() as conn:
            state = tracking.table_states(conn, ["res_ensayos"])["res_ensayos"]
        self.assertTrue(state.tracked)
        self.assertLessEqual({"res_contorno", "res_bocas", "res_area"}, self.stale_names())
        uid = self.uid("res_limites")
        self.assertRejected(ProvenanceError, "core.dataset_damaged",
                            lambda conn: external.accept_edit(conn, self.project, uid, "sí"))
        for change in (external.mark_missing, external.restore):
            with self.subTest(change=change.__name__), self.assertRaises(ValueError):
                self.write(lambda conn, c=change: c(conn, self.project, uid))
        again = self.assertUnchanged(self.check)
        self.assertEqual(again.findings, ())
        self.assertNotIn(uid, again.checked)


class MissingTest(ExternalCase):
    def test_deleted_file_is_missing_until_it_comes_back(self) -> None:
        """RF-008-57, RF-008-21 (spec §8, «Fichero de rasters/ borrado»; plan §5.4.9): un
        fichero de ``rasters/`` borrado queda «falta», con su aviso y su evento, y lo que
        depende de él, obsoleto; se ofrece recalcularlo (lo escribe una operación repetible);
        mientras falte no se vuelve a avisar. El fichero que vuelve con su contenido (aunque
        con su tamaño y su fecha de antes, se hashea) pasa a vigente, con su evento, y lo que
        dependía de él deja de estar obsoleto; con otro contenido no vuelve a vigente. Nada de
        ``exports/`` se comprueba."""
        self.terrain()
        self.report()
        path = self.path(TERRAIN_FILE)
        before = path.stat()
        path.unlink()
        self.path(REPORT_FILE).unlink()
        outcome = self.check()
        self.assertEqual(self.verdicts(outcome), {"res_mdt": Verdict.MISSING})
        self.assertEqual(outcome.texts(),
                         (MISSING_TEXT.format(name="res_mdt", locator=TERRAIN_FILE),))
        (event,) = self.logged(events.EventKind.DATASET_MISSING)
        self.assertEqual((event.entity_kind, event.entity_uid), ("dataset", self.uid("res_mdt")))
        self.assertEqual(self.dataset("res_mdt").status, Status.MISSING)
        self.assertEqual(self.stale_names(), {"res_plano"})
        self.assertEqual(self.offers("res_mdt"), (Offer.RECOMPUTE,))
        self.assertEqual(self.dataset("res_informe").status, Status.CURRENT)
        self.assertNotIn(self.uid("res_informe"), outcome.checked)
        self.assertEqual(self.assertUnchanged(self.check).findings, ())

        path.write_bytes(b"rejilla v2")
        uid = self.uid("res_mdt")
        with self.assertRaises(ValueError):
            self.write(lambda conn: external.restore(conn, self.project, uid))
        path.write_bytes(b"rejilla v1")
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        outcome = self.check()
        finding = self.finding(outcome, "res_mdt")
        self.assertEqual((finding.verdict, finding.status), (Verdict.RESTORED, Status.CURRENT))
        self.assertEqual(outcome.texts(), (
            "El dato «res_mdt» vuelve a estar en el proyecto con su contenido registrado: "
            "vigente otra vez.",))
        (event,) = self.logged(events.EventKind.DATASET_RESTORED)
        self.assertEqual(event.entity_uid, uid)
        self.assertEqual(self.dataset("res_mdt").status, Status.CURRENT)
        self.assertEqual(self.stale_names(), set())
        self.assertEqual(self.assertUnchanged(self.check).findings, ())

    def test_dropped_table_is_missing_until_it_is_restored(self) -> None:
        """RF-008-57, RF-008-52 (spec §8, «tabla eliminada desde QGIS»; plan §5.4.9): lo
        importado de «Limites_v1», ``res_area`` y la tabla común de «collares», eliminados desde
        otra conexión, quedan «falta», con su aviso, y lo que depende de lo importado, obsoleto;
        se ofrece reimportar lo importado y el acumulado que escribió su importación, y de
        ``res_area`` (de una operación que no se repite), nada. La tabla repuesta tal como
        estaba (con sus disparadores y su ``last_change``, como de una copia de seguridad) se
        hashea y vuelve a vigente; lo importado repuesto sin sus disparadores de protección,
        aunque con su contenido, no vuelve: queda «dañado»."""
        self.load(self.collars(), ROWS_B, table="res_ensayos", dataset="res_ensayos_b",
                  shared=True)
        with self.project.read() as conn:
            saved = {table: [sql for (sql,) in conn.execute(
                "SELECT sql FROM sqlite_master WHERE tbl_name = ? AND sql IS NOT NULL "
                "ORDER BY type <> 'table'", (table,))] for table in ("res_area", "res_limites")}
            (change,) = conn.execute("SELECT last_change FROM gpkg_contents WHERE table_name = "
                                     "'res_area'").fetchone()
        for table in ("res_limites", "res_area", "res_ensayos"):
            self.foreign(f'DROP TABLE "{table}"')
        outcome = self.check()
        self.assertEqual(self.verdicts(outcome), {"res_limites": Verdict.MISSING,
                                                  "res_area": Verdict.MISSING,
                                                  "res_ensayos_b": Verdict.MISSING,
                                                  "res_ensayos": Verdict.MISSING})
        self.assertEqual(outcome.texts()[:2], (
            MISSING_TEXT.format(name="res_limites", locator="res_limites"),
            MISSING_TEXT.format(name="res_area", locator="res_area"),
        ))
        self.assertEqual(len(self.logged(events.EventKind.DATASET_MISSING)), 4)
        self.assertEqual(self.stale_names(), {"res_contorno", "res_bocas", "res_area"})
        self.assertEqual([self.offers(name) for name in ("res_limites", "res_ensayos_b",
                                                         "res_ensayos", "res_area")],
                         [(Offer.REIMPORT,), (Offer.REIMPORT,), (Offer.REIMPORT,), ()])

        conn = sqlite3.connect(self.project.database_path, isolation_level=None)
        try:
            for sql in saved["res_area"]:
                conn.execute(sql)
            conn.execute('INSERT INTO "res_area" (codigo, valor) VALUES (?, ?)', ("total", 12.0))
            conn.execute("UPDATE gpkg_contents SET last_change = ? WHERE table_name = ?",
                         (change, "res_area"))
            conn.execute(saved["res_limites"][0])
            conn.executemany('INSERT INTO "res_limites" (input_uid, codigo, ley) VALUES (?, ?, ?)',
                             [(self.record.uid, code, value) for code, value in ROWS])
        finally:
            conn.close()
        uid = self.uid("res_limites")
        with self.assertRaises(ValueError):
            self.write(lambda conn: external.restore(conn, self.project, uid))
        now = self.later()
        outcome = self.check()
        self.assertEqual(self.verdicts(outcome), {"res_limites": Verdict.DAMAGED,
                                                  "res_area": Verdict.RESTORED})
        self.assertEqual((self.dataset("res_area").status, self.dataset("res_area").checked_at),
                         (Status.CURRENT, now))
        self.assertEqual(self.dataset("res_limites").status, Status.DAMAGED)
        self.assertEqual(len(self.logged(events.EventKind.DATASET_RESTORED)), 1)

    def test_public_api(self) -> None:
        """RF-008-21, RF-008-56, RF-008-57 (plan §5.3.1): ``core.datasets`` reexporta la
        comprobación de los datos, aceptar una edición, lo que se ofrece, marcar «falta» y
        volver a vigente; los eventos nuevos tienen su nombre del plan §5.2.3; marcar «falta»
        lo que ya falta no escribe nada y volver a vigente lo que no falta es un error del
        programa (aunque su contenido sea el registrado); un presupuesto que no es un número
        positivo, también."""
        for name in ("ExternalOutcome", "Offer", "accept_edit", "external_check_steps",
                     "mark_missing", "offers", "original_usable", "restore"):
            with self.subTest(name=name):
                self.assertIn(name, datasets.__all__)
                self.assertIs(getattr(datasets, name), getattr(external, name))
        self.assertEqual(
            (events.EventKind.EDIT_ACCEPTED.value, events.EventKind.DATASET_RESTORED.value,
             events.EventKind.ORIGINAL_ALTERED.value),
            ("edit_accepted", "dataset_restored", "original_altered"))
        uid = self.uid("res_area")
        self.set_status("res_area", "missing")
        self.assertUnchanged(lambda: self.write(
            lambda conn: external.mark_missing(conn, self.project, uid)))
        self.set_status("res_area", "current")
        self.foreign('UPDATE "res_area" SET valor = valor', table="res_area")
        with self.assertRaises(ValueError):
            self.write(lambda conn: external.restore(conn, self.project, uid))
        for bad, error in (("0,02", TypeError), (True, TypeError), (0, ValueError),
                           (-1.0, ValueError)):
            with self.subTest(budget=bad), self.assertRaises(error):
                external.external_check_steps(self.project, budget_s=bad)


class ContainerTest(ExternalCase):
    def test_vacuum_or_a_rebuilt_table_with_the_same_content_is_not_an_edit(self) -> None:
        """RF-008-21 (ADR-0025 §6; plan §5.4.2): un ``VACUUM`` desde otra conexión no salta,
        no avisa ni escribe nada; la tabla guardada otra vez con el mismo contenido (otro
        ``last_change``) o rehecha sin sus disparadores (como GDAL al cambiar un campo) salta,
        se hashea y no es una edición: no avisa, anota el seguimiento y le repone los
        disparadores; la siguiente vez no salta."""
        self.foreign("VACUUM")
        outcome = self.assertUnchanged(self.check)
        self.assertEqual((outcome.findings, outcome.originals, outcome.texts()), ((), (), ()))
        self.assertEqual(len(outcome.checked), 4)
        self.rebuild("res_bocas")
        self.foreign('UPDATE "res_contorno" SET valor = valor', table="res_contorno")
        now = self.later()
        outcome = self.check()
        self.assertEqual(self.verdicts(outcome), {"res_contorno": Verdict.SAME,
                                                  "res_bocas": Verdict.SAME})
        self.assertEqual(outcome.texts(), ())
        self.assertEqual(self.external_edits(), [])
        with self.project.read() as conn:
            self.assertTrue(tracking.table_states(conn, ["res_bocas"])["res_bocas"].tracked)
        after = self.dataset("res_contorno")
        self.assertEqual((after.tracked_last_change, after.checked_at), (EDITED_AT, now))
        self.assertEqual(self.assertUnchanged(self.check).findings, ())


class OriginalsTest(ExternalCase):
    def test_altered_original_is_warned_and_not_used_to_reimport(self) -> None:
        """RF-008-53 (plan §5.2.2 y §5.4.9, I-13): el original guardado de «collares» se
        comprueba por su tamaño y su fecha y, si cambian, por su huella: con otra fecha y la
        misma huella se anota la fecha sin aviso; con otra huella se avisa (un evento por
        contenido visto) y no sirve para reimportar; uno que falta, igual; en solo lectura se
        detecta sin escribir nada. Una entrada sin original guardado no tiene original que
        sirva."""
        collars, _import = self.load(self.collars(), ROWS_B, table="res_ensayos",
                                     dataset="res_ensayos_b", shared=True)
        path = self.store_original(collars.uid, "collares.csv", ORIGINAL)
        self.assertTrue(external.original_usable(self.project, collars.uid))
        self.assertFalse(external.original_usable(self.project, self.record.uid))
        self.assertEqual(self.assertUnchanged(self.check).originals, ())

        mtime = path.stat().st_mtime_ns + 10**9
        os.utime(path, ns=(mtime, mtime))
        (found,) = self.check().originals
        self.assertEqual((found.verdict, found.text()), (external.OriginalVerdict.SAME, None))
        self.assertEqual(self.original_row(collars.uid)["original_mtime_ns"], mtime)
        self.assertTrue(external.original_usable(self.project, collars.uid))

        path.write_bytes(ORIGINAL.replace(b"352,4", b"352,5"))
        altered = ("El original «collares.csv» de la entrada «collares» ya no coincide con su "
                   "huella: no sirve para reimportar.")
        outcome = self.check()
        (found,) = outcome.originals
        self.assertEqual((found.verdict, found.usable, outcome.texts()),
                         (external.OriginalVerdict.ALTERED, False, (altered,)))
        (event,) = self.logged(events.EventKind.ORIGINAL_ALTERED)
        self.assertEqual((event.entity_kind, event.entity_uid, event.message),
                         ("input", collars.uid, altered))
        self.assertEqual(event.data["seen_sha256"], hashing.sha256_file(path))
        self.assertFalse(external.original_usable(self.project, collars.uid))
        again = self.assertUnchanged(self.check)
        self.assertEqual(again.texts(), (altered,))
        path.write_bytes(ORIGINAL.replace(b"352,4", b"352,6"))
        self.assertEqual(self.check().texts(), (altered,))
        self.assertEqual(len(self.logged(events.EventKind.ORIGINAL_ALTERED)), 2)

        path.unlink()
        self.project.set_read_only(project_model.ReadOnlyCode.LOCKED, "otra sesión")
        outcome = self.assertUnchanged(self.check)
        self.assertFalse(outcome.recorded)
        self.assertEqual(outcome.texts(), (
            "Falta el original «collares.csv» de la entrada «collares» en el proyecto: no sirve "
            "para reimportar.",))
        self.assertFalse(external.original_usable(self.project, collars.uid))
        with self.assertRaises(ProvenanceError) as caught:
            external.original_usable(self.project, "00000000-0000-4000-8000-0000000002ff")
        self.assertEqual(caught.exception.code, "core.input_unknown")

    def test_each_original_of_an_input_is_warned(self) -> None:
        """RF-008-53 (I-13): de una entrada de dos ficheros, cada original alterado tiene su
        aviso y su evento, aunque los dos queden iguales."""
        plans = self.plans()
        first = self.store_original(plans.uid, "plano.dxf", b"dxf", 0)
        second = self.store_original(plans.uid, "plano.txt", b"txt", 1)
        self.assertTrue(external.original_usable(self.project, plans.uid))
        for path in (first, second):
            path.write_bytes(b"otro")
        outcome = self.check()
        self.assertEqual([(item.ord, item.verdict) for item in outcome.originals],
                         [(0, external.OriginalVerdict.ALTERED),
                          (1, external.OriginalVerdict.ALTERED)])
        self.assertEqual([event.data["file"] for event
                          in self.logged(events.EventKind.ORIGINAL_ALTERED)],
                         ["plano.dxf", "plano.txt"])
        self.assertFalse(external.original_usable(self.project, plans.uid))


class SessionTest(ExternalCase):
    def test_read_only_detects_without_writing(self) -> None:
        """RF-008-58, RF-008-21, RF-008-56, RF-008-57 (plan §5.4.6): en solo lectura se
        detecta lo editado fuera (con el bloqueo de lo no editable) y lo que falta, con sus
        avisos, sin escribir nada en el proyecto."""
        self.foreign('INSERT INTO "res_bocas" (codigo, valor) VALUES (?, ?)', ("S-02", 11.0),
                     table="res_bocas")
        self.foreign('DROP TABLE "res_area"')
        self.project.set_read_only(project_model.ReadOnlyCode.LOCKED, "otra sesión")
        outcome = self.assertUnchanged(self.check)
        self.assertFalse(outcome.recorded)
        self.assertEqual(self.verdicts(outcome), {"res_bocas": Verdict.EDITED,
                                                  "res_area": Verdict.MISSING})
        self.assertEqual(outcome.texts(), (
            EDITED_TEXT.format(name="res_bocas") + " " + BLOCKED_TEXT.format(name="res_bocas"),
            MISSING_TEXT.format(name="res_area", locator="res_area"),
        ))

    def test_what_changes_while_checking_is_left_for_next_time(self) -> None:
        """RF-008-21, RF-008-58 (plan §5.4.6, I-5 e I-7): lo que esta sesión registra después
        de la foto (la puerta antes de operar registra la edición de ``res_contorno``) no se
        vuelve a tomar por edición externa, y lo que otro programa vuelve a cambiar entre el
        hash y el registro queda para la siguiente comprobación (``stale``), sin escribir nada
        de ello; con la base ocupada, el registro se reintenta en el paso siguiente."""
        self.qgis('UPDATE "res_contorno" SET valor = 4.0', table="res_contorno",
                  at="2030-01-01T00:00:00.000Z")
        self.qgis('UPDATE "res_area" SET valor = 13.0', table="res_area",
                  at="2030-01-01T00:00:00.000Z")
        steps = external.external_check_steps(self.project)
        step = next(steps)
        while step.phase != "registro":
            step = next(steps)
        self.assertReady(self.can_run(Use("res_contorno", "outline")))
        self.assertEqual(len(self.external_edits()), 1)
        self.qgis('UPDATE "res_area" SET valor = 14.0', table="res_area",
                  at="2030-01-02T00:00:00.000Z")
        real = self.project.try_write
        calls: list[int] = []

        def busy(work: Any) -> Any:
            calls.append(1)
            if len(calls) == 1:
                return session_mod.WriteAttempt(session_mod.WriteState.RETRYING, None,
                                                "La base de datos está ocupada")
            return real(work)

        with mock.patch.object(self.project, "try_write", busy):
            rest = list(steps)
        self.assertIn("La base de datos está ocupada", [item.message for item in rest])
        outcome = rest[-1].result
        self.assertEqual((outcome.findings, outcome.stale),
                         ((), (self.uid("res_contorno"), self.uid("res_area"))))
        self.assertEqual(len(self.external_edits()), 1)
        self.assertEqual(self.verdicts(self.check()), {"res_area": Verdict.EDITED})
        self.assertEqual(self.table("res_area")[0][-1], 14.0)
        with self.project.read() as conn:
            (sha,) = conn.execute(
                "SELECT to_sha256 FROM gb_dataset_change WHERE dataset_uid = ? ORDER BY fid "
                "DESC LIMIT 1", (self.uid("res_area"),)).fetchone()
            current = datasets.get(conn, "res_area")
            self.assertEqual(sha, datasets.content_digest(conn, self.project,
                                                          current).content_sha256)

    def test_change_before_hashing_is_hashed_as_it_is_then(self) -> None:
        """RF-008-21 (plan §5.4.2): si otro programa vuelve a cambiar una tabla entre su
        prefiltro y su hash, se hashea y se registra como está al hashearla (una sola edición
        externa, con el contenido último)."""
        self.qgis('UPDATE "res_contorno" SET valor = 4.0', table="res_contorno",
                  at="2030-01-01T00:00:00.000Z")
        steps = external.external_check_steps(self.project, budget_s=1e-9)
        step = next(steps)
        while (step.phase, step.done) != ("prefiltro", 2):
            step = next(steps)
        self.qgis('UPDATE "res_contorno" SET valor = 6.0', table="res_contorno",
                  at="2030-01-02T00:00:00.000Z")
        outcome = list(steps)[-1].result
        self.assertEqual(self.verdicts(outcome), {"res_contorno": Verdict.EDITED})
        self.assertEqual(len(self.external_edits()), 1)
        with self.project.read() as conn:
            current = datasets.get(conn, "res_contorno")
            self.assertEqual(current.content_sha256, datasets.content_digest(
                conn, self.project, current).content_sha256)
        self.assertEqual(self.check().findings, ())

    def test_large_file_is_hashed_in_several_steps(self) -> None:
        """RF-008-21, RF-008-58 (plan §2 y §5.4.6: por trozos medidos por tiempo): una
        rejilla de ``rasters/`` que saltó se hashea por trozos, en varios pasos; si cambia
        mientras se lee, queda para la próxima (también en solo lectura, donde no hay registro
        que lo vea), como un original que cambia entre su prefiltro y su huella; si no, se
        registra su edición externa (bloqueada: no es editable)."""
        self.terrain(bytes(3 << 20))
        path = self.path(TERRAIN_FILE)
        path.write_bytes(bytes(3 << 20)[:-1] + b"\x01")
        mtime = path.stat().st_mtime_ns + 10**9
        os.utime(path, ns=(mtime, mtime))
        original = self.store_original(self.record.uid, "Limites_v1.gpkg", b"original")
        self.touch(original)
        with mock.patch.object(type(self.project), "writable", property(lambda _self: False)):
            steps = external.external_check_steps(self.project, budget_s=0.001)
            step = next(steps)
            while step.phase != "contenido":
                step = next(steps)
            os.utime(path, ns=(mtime + 10**9, mtime + 10**9))
            self.touch(original)
            outcome = self.assertUnchanged(lambda: list(steps)[-1].result)
        self.assertEqual((outcome.recorded, outcome.findings, outcome.originals, outcome.stale),
                         (False, (), (), (self.uid("res_mdt"),
                                          f"originals/{self.record.uid}/Limites_v1.gpkg")))
        steps = list(external.external_check_steps(self.project, budget_s=0.001))
        self.assertGreaterEqual(len([step for step in steps if step.phase == "contenido"]), 2)
        finding = self.finding(steps[-1].result, "res_mdt")
        self.assertEqual((finding.verdict, finding.status), (Verdict.EDITED, Status.BLOCKED))

    def test_unreadable_or_claimed_files(self) -> None:
        """RF-008-21, RF-008-58 (plan §5.4.6, I-5): un fichero que salta y no se puede leer
        (su lector no está registrado) se avisa sin registrar nada; uno que reclama una
        operación en curso de esta sesión no se comprueba mientras la escribe."""
        self.terrain()
        path = self.path(TERRAIN_FILE)
        path.write_bytes(b"rejilla v2")
        mtime = path.stat().st_mtime_ns + 10**9
        os.utime(path, ns=(mtime, mtime))
        readers.unregister_reader(BYTES.id)
        outcome = self.assertUnchanged(self.check)
        finding = self.finding(outcome, "res_mdt")
        self.assertEqual((finding.verdict, finding.status), (Verdict.UNREADABLE, Status.CURRENT))
        self.assertTrue(outcome.texts()[0].startswith(
            "No se puede leer el dato «res_mdt» para comprobarlo ("))
        readers.register_reader(BYTES)
        redo = operations.begin_operation(self.project, GRID.op_type, settings={},
                                          executor="blender")
        redo.claim_paths(TERRAIN_FILE)
        outcome = self.assertUnchanged(self.check)
        self.assertEqual(outcome.findings, ())
        self.assertNotIn(self.uid("res_mdt"), outcome.checked)
        redo.cancel("prueba: no se escribe")
        self.assertEqual(self.verdicts(self.check()), {"res_mdt": Verdict.EDITED})
