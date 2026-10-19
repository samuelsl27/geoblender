# SPDX-License-Identifier: GPL-3.0-or-later
"""Las decisiones de la propiedad (spec 009, T16; RF-009-13, RF-009-12; HU-009-4; plan 009 A10 y
D-33).

``core.versions.decisions`` registra una decisión de la propiedad (quién decide, cuándo, qué y su
origen: una entrada registrada de tipo documento o una referencia en texto) enlazada a claves de
parámetro (todos sus ámbitos) y a versiones, en la transacción de quien llama y con el evento
``decision_recorded``, y la lee: todas, las de un parámetro o las de una versión
(``decisions``) y el decisor de cada parámetro (``deciders``, para Parámetros del proyecto).
Nada se cambia ni se borra (solo inserción, RF-009-12): ni la decisión, ni sus enlaces, ni el
parámetro o la versión que nombra.

Sobre el proyecto de la demostración de versiones (``tests/support/versions_fixtures.py``), con
un documento registrado como entrada (un PDF sintético, ``Acta_propiedad``). Datos solo
sintéticos.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import unittest
from collections.abc import Callable
from typing import Any

from tests.support import provenance_data as data
from tests.support import provenance_demo as demo_support
from tests.support import versions_demo as vdemo
from tests.support import versions_fixtures as fixtures
from tests.support.provenance_contract import registered
from tests.support.package import import_geoblender

decisions = import_geoblender("core.versions.decisions")
model = import_geoblender("core.versions.model")
events = import_geoblender("core.project.events")
provenance = import_geoblender("core.provenance")
operations = import_geoblender("core.provenance.operations")
inputs_model = import_geoblender("core.inputs.model")
inputs_registry = import_geoblender("core.inputs.registry")
readers = import_geoblender("core.content.readers")
builtin = import_geoblender("core.content.builtin")
hashing = import_geoblender("core.hashing")
i18n = import_geoblender("core.i18n")

SWELL = demo_support.SWELL_FACTOR
BENCH = vdemo.BENCH_HEIGHT
WHO = "D. Juan Prueba"
WHAT = "K = 1,23 para el balance de la ampliación"
WHEN = "2026-10-03"
DOCUMENT_NAME = "Acta_propiedad"
NOT_APPLICABLE = {"not_applicable": True}
IMPORT_DOCUMENT = provenance.OperationDef("res.import_document", "1.0", "res",
                                          "Test document import", False)
"""La importación del documento de la prueba (un tipo de operación de prueba)."""
UNCHANGED = ("gb_parameter", "gb_parameter_history", "gb_version", "gb_revision", "gb_input",
             "gb_input_file", "gb_dataset", "gb_operation", "gb_figure", "gb_stale")
"""Lo que registrar una decisión no cambia."""
DECISION_TABLES = ("gb_decision", "gb_decision_link", "gb_event")


class DecisionsCase(fixtures.VersionsProjectCase):
    """El proyecto de la demostración de versiones con el acta de la propiedad registrada como
    entrada de tipo documento (``self.document``, su uid)."""

    def setUp(self) -> None:
        super().setUp()
        self.enterContext(registered(IMPORT_DOCUMENT))
        self.document = self.register_document()

    # --- Ayudas -----------------------------------------------------------------------------

    def register_document(self) -> str:
        """Registra ``fuentes/acta_propiedad.pdf`` como entrada de tipo documento, con su
        importación; devuelve su uid."""
        pdf = self.folder / "fuentes" / "acta_propiedad.pdf"
        pdf.write_bytes(data.report_pdf())
        found = pdf.stat()
        no_crs = inputs_model.input_declarations(NOT_APPLICABLE, NOT_APPLICABLE, {})
        spec = inputs_model.InputSpec(
            DOCUMENT_NAME, "document", "res", builtin.DOCUMENT.id,
            files=[inputs_registry.locate_source(pdf, self.project, self.userdata)],
            file_prints=[inputs_model.SourcePrint(hashing.sha256_file(pdf), size=found.st_size,
                                                  mtime_ns=found.st_mtime_ns)],
            digest=readers.read_content(builtin.DOCUMENT, builtin.DOCUMENT.request(
                "document", no_crs, {"main": pdf})),
            crs_h=NOT_APPLICABLE, crs_v=NOT_APPLICABLE,
        )
        handle = operations.begin_operation(self.project, IMPORT_DOCUMENT.op_type, settings={},
                                            executor="blender")

        def work(conn: sqlite3.Connection) -> str:
            record = inputs_registry.register_input(conn, self.project, spec,
                                                    operation_uid=handle.uid)
            handle.complete(conn)
            return str(record.uid)

        uid = self.write(work)
        self.tick()
        return uid

    def decide(self, **changes: Any) -> Any:
        """Registra una decisión (por defecto, la del acta, enlazada a K y a V02) en su propia
        transacción, un minuto después; devuelve la ``Decision``."""
        self.tick()
        return self.write(lambda conn: self.call(conn, **changes))

    def call(self, conn: sqlite3.Connection, **changes: Any) -> Any:
        """``record_decision`` en ``conn`` con los valores por defecto de la prueba."""
        arguments: dict[str, Any] = {
            "decided_by": WHO, "decided_at": WHEN, "what": WHAT,
            "source_input_uid": self.document, "source_text": None,
            "parameters": (SWELL,), "versions": ("V02",),
        }
        arguments.update(changes)
        return decisions.record_decision(conn, self.project, **arguments)

    def dump(self, tables: tuple[str, ...] = UNCHANGED) -> dict[str, list[tuple[Any, ...]]]:
        """Las filas de ``tables`` (en orden de inserción, si tienen ``fid``)."""
        with self.project.read() as conn:
            return {table: (conn.execute(f"SELECT * FROM {table} ORDER BY fid").fetchall()
                            if table != "gb_stale" else
                            sorted(conn.execute("SELECT * FROM gb_stale").fetchall(), key=repr))
                    for table in tables}

    def recorded(self) -> list[Any]:
        return self.read(lambda conn: events.read_events(conn,
                                                         events.EventKind.DECISION_RECORDED))

    def assertRejected(self, *cases: tuple[str, Callable[[sqlite3.Connection], Any]]) -> None:
        """Cada caso (código, trabajo) se rechaza con su ``VersionError`` **sin escribir nada**:
        en una sola transacción, las tablas de las decisiones y los eventos siguen igual tras
        cada uno; al final, el contador de cambios no se ha movido y el proyecto sigue en
        escritura."""
        counter = self.change_counter()

        def tables(conn: sqlite3.Connection) -> list[list[tuple[Any, ...]]]:
            return [conn.execute(f"SELECT * FROM {table} ORDER BY fid").fetchall()
                    for table in DECISION_TABLES]

        with self.project.write_transaction() as conn:
            before = tables(conn)
            for code, work in cases:
                with self.subTest(code=code):
                    with self.assertRaises(model.VersionError) as caught:
                        work(conn)
                    self.assertEqual(caught.exception.code, code, str(caught.exception))
                    self.assertEqual(tables(conn), before)
        self.assertTrue(self.project.writable)
        self.assertEqual(self.change_counter(), counter)


class RecordTest(DecisionsCase):
    def test_owner_decision_linked_to_a_parameter_and_a_version(self) -> None:
        """RF-009-13 (HU-009-4; «Hecho cuando» de la T16): una decisión con quién decide,
        cuándo, qué y el documento registrado como entrada, enlazada a ``demo.swell_factor`` y
        a V02, se guarda con quién y cuándo la registró y su evento ``decision_recorded``;
        aparece como decisor del parámetro y en la versión (no en V01 ni en otro parámetro), con
        el texto «Propiedad: D. Juan Prueba · 03/10/2026» en los dos idiomas. Registrarla no
        cambia nada más: ni el parámetro (su decisor sigue siendo el suyo), ni la versión, ni
        la entrada, ni ningún fichero del proyecto."""
        before, files = self.dump(), self.files()
        decision = self.decide()
        now = self.now()
        self.assertIsInstance(decision, model.Decision)
        self.assertEqual(
            (decision.decided_by, decision.decided_at, decision.what, decision.source_input_uid,
             decision.source_name, decision.source_text, decision.recorded_by,
             decision.recorded_at),
            (WHO, WHEN, WHAT, self.document, DOCUMENT_NAME, None, fixtures.USER, now),
        )
        self.assertEqual((decision.parameters, decision.versions, decision.version_codes),
                         ((SWELL,), (self.v2.uid,), ("V02",)))
        self.assertEqual(decision.decider(), "Propiedad: D. Juan Prueba · 03/10/2026")
        self.assertEqual(decision.decider("en"), "Owner: D. Juan Prueba · 03/10/2026")
        # Las filas: la decisión y un enlace por clave de parámetro (no por fila) y por versión.
        self.assertEqual(self.query(
            "SELECT uid, decided_by, decided_at, what, source_input_uid, source_text, "
            "recorded_by, recorded_at FROM gb_decision"),
            [(decision.uid, WHO, WHEN, WHAT, self.document, None, fixtures.USER, now)])
        self.assertEqual(self.query(
            "SELECT decision_uid, item_kind, item_uid FROM gb_decision_link ORDER BY fid"),
            [(decision.uid, "parameter", SWELL), (decision.uid, "version", self.v2.uid)])
        # Las lecturas.
        read = self.read
        self.assertEqual(read(lambda conn: decisions.decisions(conn)), (decision,))
        self.assertEqual(read(lambda conn: decisions.decisions(conn, parameter_key=SWELL)),
                         (decision,))
        self.assertEqual(read(lambda conn: decisions.decisions(conn, parameter_key=BENCH)), ())
        for ref in (self.v2.uid, "V02"):
            with self.subTest(version=ref):
                self.assertEqual(read(lambda conn, ref=ref: decisions.decisions(
                    conn, version_uid=ref)), (decision,))
        self.assertEqual(read(lambda conn: decisions.decisions(conn, version_uid="V01")), ())
        self.assertEqual(read(lambda conn: decisions.decisions(conn, version_uid="V09")), ())
        self.assertEqual(read(lambda conn: decisions.decisions(
            conn, parameter_key=SWELL, version_uid="V02")), (decision,))
        self.assertEqual(read(lambda conn: decisions.decisions(
            conn, parameter_key=SWELL, version_uid="V01")), ())
        self.assertEqual(read(lambda conn: decisions.deciders(conn, [SWELL, BENCH, SWELL])),
                         {SWELL: (decision,), BENCH: ()})
        # El evento.
        (event,) = self.recorded()
        self.assertEqual((event.kind, event.entity_kind, event.entity_uid, event.at,
                          event.user_host), ("decision_recorded", "decision", decision.uid, now,
                                             fixtures.USER))
        self.assertEqual(event.data, {
            "decided_by": WHO, "decided_at": WHEN, "what": WHAT,
            "source_input": self.document, "source_name": DOCUMENT_NAME, "source_text": None,
            "parameters": [SWELL], "versions": ["V02"],
        })
        self.assertIn(WHAT, event.message)
        self.assertIn("V02", event.message)
        # Nada más cambia.
        self.assertEqual(self.dump(), before)
        self.assertEqual(self.files(), files)
        (row,) = self.store.scopes(SWELL)
        self.assertNotEqual(row.decided_by, WHO)

    def test_every_scope_of_a_parameter_and_text_reference(self) -> None:
        """RF-009-13 (D-33): el enlace es a la clave del parámetro, así que la decisión es el
        decisor de todos sus ámbitos: el del proyecto, el de V01 y el que V02 tome después.
        El origen puede ser una referencia en texto, sin documento; la fecha, un ``date``;
        cada parámetro y cada versión se enlaza una vez aunque se repita (por uid o por
        código). Las decisiones se leen por la fecha de la decisión (la registrada después con
        una fecha anterior, antes) y las de un mismo parámetro se acumulan: ninguna sustituye a
        otra."""
        version = self.project.session.geoblender_version
        self.write(lambda conn: self.store.ensure_default(conn, BENCH,
                                                          geoblender_version=version))
        self.tick()
        self.write(lambda conn: self.store.change(
            conn, BENCH, value=12.0, source="Plan de labores", decided_by="Samuel (IMGA)",
            reason="Banco de V01", version="V01"))
        first = self.decide()
        second = self.decide(
            decided_at=dt.date(2026, 9, 15), what="Bancos de 12 m en todas las versiones",
            source_input_uid=None, source_text="  Correo de la propiedad del 15/09/2026 ",
            parameters=(BENCH, SWELL, BENCH), versions=("V01", self.v1.uid, "V02"))
        self.assertEqual((second.decided_at, second.source_input_uid, second.source_name,
                          second.source_text), ("2026-09-15", None, None,
                                                "Correo de la propiedad del 15/09/2026"))
        self.assertEqual((second.parameters, second.versions, second.version_codes),
                         ((BENCH, SWELL), (self.v1.uid, self.v2.uid), ("V01", "V02")))
        self.assertEqual(second.decider(), "Propiedad: D. Juan Prueba · 15/09/2026")
        self.tick()
        self.write(lambda conn: self.store.change(
            conn, BENCH, value=11.0, source="Plan de labores", decided_by="Samuel (IMGA)",
            reason="Banco de V02", version="V02"))
        rows = self.store.scopes(BENCH)
        self.assertEqual([(row.scope, row.scope_uid) for row in rows],
                         [("project", ""), ("version", self.v1.uid), ("version", self.v2.uid)])
        found = self.read(lambda conn: decisions.deciders(conn, [row.key for row in rows]))
        for row in rows:
            with self.subTest(scope=row.scope_uid):
                self.assertEqual(found[row.key], (second,))
        self.assertEqual(self.read(lambda conn: decisions.deciders(conn, [SWELL])),
                         {SWELL: (second, first)})
        self.assertEqual(self.read(lambda conn: decisions.decisions(conn)), (second, first))
        self.assertEqual(self.read(lambda conn: decisions.decisions(conn, version_uid="V01")),
                         (second,))
        self.assertEqual(len(self.recorded()), 2)


class AppendOnlyTest(DecisionsCase):
    def test_nothing_changes_or_is_deleted(self) -> None:
        """RF-009-12: una decisión ni se cambia ni se borra. El módulo no ofrece hacerlo, y la
        base lo rechaza también a quien escribe en ella (cambiar, borrar o sustituir con
        ``REPLACE`` la decisión o sus enlaces). Descartar la versión que nombra no la toca: la
        decisión sigue enlazada a ella, y se puede registrar otra que la nombre (es un registro
        nuevo, no un cambio de la versión)."""
        offered = [name for name in dir(decisions) if not name.startswith("_")
                   and callable(getattr(decisions, name))
                   and any(word in name.lower() for word in
                           ("delete", "remove", "drop", "update", "change", "edit", "set_",
                            "replace", "discard"))]
        self.assertEqual(offered, [])
        decision = self.decide()
        before = self.dump(("gb_decision", "gb_decision_link"))
        statements = (
            ("gb_decision", "UPDATE gb_decision SET what = 'otra cosa'"),
            ("gb_decision", "DELETE FROM gb_decision"),
            ("gb_decision", "INSERT OR REPLACE INTO gb_decision (uid, decided_by, decided_at, "
                            "what, source_text, recorded_by, recorded_at) "
                            "SELECT uid, 'Otro', decided_at, what, 'x', recorded_by, "
                            "recorded_at FROM gb_decision"),
            ("gb_decision_link", "UPDATE gb_decision_link SET item_uid = 'demo.production'"),
            ("gb_decision_link", "DELETE FROM gb_decision_link"),
        )

        def work(conn: sqlite3.Connection) -> None:
            for table, sql in statements:
                with self.subTest(sql=sql):
                    with self.assertRaises(sqlite3.DatabaseError) as caught:
                        conn.execute(sql)
                    self.assertTrue(str(caught.exception).startswith(f"{table}: "),
                                    str(caught.exception))

        self.write(work)
        self.assertEqual(self.dump(("gb_decision", "gb_decision_link")), before)
        self.set_status(self.v2, "DESCARTADO", "La propiedad no la quiere")
        self.assertEqual(self.read(lambda conn: decisions.decisions(conn, version_uid="V02")),
                         (decision,))
        later = self.decide(what="La propiedad descarta la ampliación", parameters=())
        self.assertEqual((later.parameters, later.version_codes), ((), ("V02",)))
        self.assertEqual(self.read(lambda conn: decisions.decisions(conn, version_uid="V02")),
                         (decision, later))
        after = self.dump(("gb_decision", "gb_decision_link"))
        for table, rows in before.items():
            with self.subTest(table=table):
                self.assertEqual(after[table][:len(rows)], rows)
                self.assertGreater(len(after[table]), len(rows))


class RejectTest(DecisionsCase):
    def test_rejections_without_writing(self) -> None:
        """RF-009-13 (D-33): sin documento ni texto, rechazo; también sin quién decide, sin qué
        o sin fecha, con una fecha que no es un día («AAAA-MM-DD»), con una entrada que no
        existe o que no es un documento (la capa del límite), con un parámetro o una versión
        que no existen y con una ruta absoluta en un texto (el proyecto no guarda ninguna).
        Cada rechazo, con su texto en español, antes de escribir nada."""
        boundary_input = str(self.record(self.boundary).input_uid)
        call = self.call
        cases: list[tuple[str, Callable[[sqlite3.Connection], Any]]] = [
            ("core.version_decision_source_required",
             lambda conn: call(conn, source_input_uid=None, source_text=None)),
            ("core.version_decision_source_required",
             lambda conn: call(conn, source_input_uid=None, source_text="   ")),
            ("core.version_decision_source_required",
             lambda conn: call(conn, source_input_uid="", source_text="")),
            ("core.version_decision_by_required", lambda conn: call(conn, decided_by=None)),
            ("core.version_decision_by_required", lambda conn: call(conn, decided_by="  ")),
            ("core.version_decision_what_required", lambda conn: call(conn, what="")),
            ("core.version_decision_date_required", lambda conn: call(conn, decided_at=None)),
            ("core.version_decision_input_unknown",
             lambda conn: call(conn, source_input_uid="no-existe")),
            ("core.version_decision_input_kind",
             lambda conn: call(conn, source_input_uid=boundary_input)),
            ("core.version_decision_parameter_unknown",
             lambda conn: call(conn, parameters=(SWELL, "demo.no_existe"))),
            ("core.version_unknown", lambda conn: call(conn, versions=("V02", "V09"))),
            ("core.version_text_path",
             lambda conn: call(conn, what="Ver Q:\\entregas\\acta.pdf")),
            ("core.version_text_path",
             lambda conn: call(conn, source_input_uid=None,
                               source_text="Correo en Q:\\entregas\\correo.msg")),
        ]
        for wrong in ("03/10/2026", "2026-02-30", "2026-10-3", dt.datetime(2026, 10, 3, 9),
                      20261003):
            cases.append(("core.version_decision_date",
                          lambda conn, wrong=wrong: call(conn, decided_at=wrong)))
        self.assertRejected(*cases)
        with self.project.write_transaction() as conn:
            for code, text, work in (
                ("core.version_decision_source_required",
                 "Indique el documento o la referencia de la decisión (un documento registrado "
                 "como entrada o un texto, como «correo del 03/10/2026»)",
                 lambda conn: call(conn, source_input_uid=None)),
                ("core.version_decision_input_kind",
                 "La entrada «Limites_v1» no es un documento (es de tipo vector): una decisión de "
                 "la propiedad se apoya en un documento registrado o en una referencia en texto",
                 lambda conn: call(conn, source_input_uid=boundary_input)),
                ("core.version_decision_date",
                 "La fecha de la decisión es un día («AAAA-MM-DD»), no «03/10/2026»",
                 lambda conn: call(conn, decided_at="03/10/2026")),
            ):
                with self.subTest(code=code), self.assertRaises(model.VersionError) as caught:
                    work(conn)
                self.assertEqual((caught.exception.code, str(caught.exception)), (code, text))
        for argument in ("parameters", "versions"):
            with self.subTest(argument=argument), self.assertRaises(TypeError), \
                    self.project.write_transaction() as conn:
                call(conn, **{argument: "V02" if argument == "versions" else SWELL})
        self.assertEqual(self.recorded(), [])
        self.assertEqual(self.query("SELECT count(*) FROM gb_decision"), [(0,)])


class DocumentsTest(DecisionsCase):
    def test_documents_a_decision_can_cite(self) -> None:
        """RF-009-13 (D-33; T24: «Documento» del diálogo «Registrar decisión…»): las entradas
        de tipo documento que puede citar una decisión, con su uid y su nombre, por nombre: las
        activas; no el límite (es de otro tipo) ni un documento descartado (queda como
        registro, sin usar). Solo lee."""
        found = self.read(decisions.documents)
        self.assertEqual(found, ((self.document, DOCUMENT_NAME),))
        counter = self.change_counter()
        self.assertEqual(self.read(decisions.documents), found)
        self.assertEqual(self.change_counter(), counter)
        self.tick()
        self.write(lambda conn: inputs_registry.discard(conn, self.project, self.document,
                                                        "Acta sustituida por la propiedad"))
        self.assertEqual(self.read(decisions.documents), ())


class ReadTest(unittest.TestCase):
    def test_without_decision_tables(self) -> None:
        """RF-009-13: sin las tablas de las decisiones (un proyecto del esquema 2 abierto en
        solo lectura), no hay ninguna: las lecturas no fallan; sin la de las entradas, ningún
        documento."""
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        self.assertEqual(decisions.decisions(conn), ())
        self.assertEqual(decisions.decisions(conn, parameter_key=SWELL, version_uid="V01"), ())
        self.assertEqual(decisions.deciders(conn, [SWELL]), {SWELL: ()})
        self.assertEqual(decisions.documents(conn), ())

    def test_messages_in_the_language_catalog(self) -> None:
        """RF-009-13 (constitución, principio 10): los textos de las decisiones tienen su
        ``msgid`` en inglés con su español en ``messages.toml``."""
        table = i18n.load_messages()
        codes = [code for code in model.MESSAGES if code.startswith("core.version_decision_")]
        self.assertGreaterEqual(len(codes), 9)
        for code in codes:
            with self.subTest(code=code):
                self.assertIn(model.MESSAGES[code], table)


if __name__ == "__main__":
    unittest.main()
