# SPDX-License-Identifier: GPL-3.0-or-later
"""Migración del esquema 3 al 4: el aspecto de los elementos (spec 019, T03; RF-019-07 a 09;
ADR-0033; plan 019 §5.2).

El proyecto del esquema 3 sale de ``esquema2.zip`` migrado con la ``m0002`` y la ``m0003`` reales
(``target=3``); se mira todo, se migra con ``m0004`` y el ``migrate_steps`` de la 002 y se vuelve
a mirar. Los lectores del esquema 3 se simulan con ``SCHEMA_VERSION = 3``.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tests.support import schema2_project as fixture
from tests.support.core_fixtures import FakeClock, FakePids, make_session, make_settings, project_tmp
from tests.support.package import import_geoblender

create = import_geoblender("core.project.create")
open_mod = import_geoblender("core.project.open")
checkout = import_geoblender("core.project.checkout")
model = import_geoblender("core.project.model")
schema = import_geoblender("core.project.schema")
manifest_mod = import_geoblender("core.project.manifest")
events_mod = import_geoblender("core.project.events")
copytree = import_geoblender("core.project.copytree")
errors = import_geoblender("core.errors")
migrations = import_geoblender("core.project.migrations")
m0003 = import_geoblender("core.project.migrations.m0003")
m0004 = import_geoblender("core.project.migrations.m0004")
tracking = import_geoblender("core.datasets.tracking")
gpkg = import_geoblender("core.gpkg")
gpkg_base = import_geoblender("core.gpkg.base")
userdata_mod = import_geoblender("core.userdata")

SESSION = make_session(
    session_uid="00000000-0000-4000-8000-000000000004", host="PC-PRUEBA-C", user="otra",
    pid=779, geoblender_version="0.5.0",
)
USER_HOST = "otra@PC-PRUEBA-C"
BACKUP_NAME = f"{fixture.PROJECT_NAME}.gbproj.respaldo-esquema-3"
DATABASE = "project.gpkg"
WRITTEN = ("project.gpkg", "project.gpkg-journal", "manifest.json")
PROJECT_CHANGES = ("schema_version", "last_written_with", "modified_at")
APPENDED = ("gb_event", "gb_schema_migration", "gpkg_extensions")
SEQUENCES = ("gb_event", "gb_schema_migration")
TABLE = schema.APPEARANCE_TABLE

_STATE: dict[str, Any] = {}


def _files(folder: Path, skip: Path | None = None) -> dict[str, object]:
    found: dict[str, object] = {}
    for path in sorted(folder.rglob("*")):
        if skip is not None and (path == skip or path.is_relative_to(skip)):
            continue
        rel = path.relative_to(folder).as_posix()
        if path.is_dir():
            found[rel] = "carpeta"
        else:
            stat = path.stat()
            found[rel] = (stat.st_size, hashlib.sha256(path.read_bytes()).hexdigest(),
                          stat.st_mtime_ns)
    return found


def _tables(database: Path) -> dict[str, tuple[tuple[str, ...], list[tuple]]]:
    found: dict[str, tuple[tuple[str, ...], list[tuple]]] = {}
    with gpkg.GpkgConnection.open_read(database) as db:
        conn = db.connection
        names = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        for name in names:
            cursor = conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid')
            found[name] = (tuple(column[0] for column in cursor.description), cursor.fetchall())
    return found


def _master(database: Path) -> dict[tuple[str, str], tuple[str, str | None]]:
    with gpkg.GpkgConnection.open_read(database) as db:
        rows = db.connection.execute("SELECT type, name, tbl_name, sql FROM sqlite_master")
        return {(kind, name): (table, sql) for kind, name, table, sql in rows}


def _states(database: Path) -> dict[str, Any]:
    with gpkg.GpkgConnection.open_read(database) as db:
        return tracking.table_states(db.connection)


def _internal_structure(database: Path) -> tuple[list[tuple], list[tuple]]:
    internal = schema.INTERNAL_TABLES
    marks = ", ".join("?" for _ in internal)
    with gpkg.GpkgConnection.open_read(database) as db:
        conn = db.connection
        master = conn.execute(
            f"SELECT type, name, tbl_name, sql FROM sqlite_master WHERE tbl_name IN ({marks}) "
            "ORDER BY type, name", internal).fetchall()
        extensions = conn.execute(
            "SELECT table_name, column_name, extension_name, definition, scope "
            "FROM gpkg_extensions WHERE extension_name = ? "
            "ORDER BY table_name, column_name", (gpkg_base.EXTENSION_NAME,)).fetchall()
    return master, extensions


def _dump(database: Path) -> list[str]:
    conn = sqlite3.connect(database)
    try:
        return list(conn.iterdump())
    finally:
        conn.close()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setUpModule() -> None:
    tmp = unittest.enterModuleContext(project_tmp("gb-m4-"))
    work = tmp / "z"
    work.mkdir()
    root = fixture.extract(work)
    database = root / DATABASE
    userdata = userdata_mod.UserData(tmp / "u")
    clock = FakeClock()
    pids = FakePids({SESSION.pid})
    list(migrations.migrate_steps(root, SESSION, userdata, clock=clock, pid_alive=pids, target=3))
    backup3 = root.parent / BACKUP_NAME.replace("esquema-3", "esquema-2")
    shutil.rmtree(backup3)  # la copia previa de la 2 → 3: no es de esta prueba
    _STATE.update(
        tmp=tmp, work=work, root=root, database=database, userdata=userdata, clock=clock,
        pids=pids, backup=root.parent / BACKUP_NAME,
        files=_files(work), tables=_tables(database), master=_master(database),
        states=_states(database), prints=copytree.fingerprint(root, exclude=fixture.EXCLUDED),
    )
    steps = list(migrations.migrate_steps(root, SESSION, userdata, clock=clock, pid_alive=pids))
    _STATE.update(
        steps=steps, after_files=_files(work, skip=_STATE["backup"]),
        after_tables=_tables(database), after_master=_master(database),
        after_states=_states(database),
    )


class RegistryTest(unittest.TestCase):
    def test_the_step_3_to_4_is_registered(self) -> None:
        """RF-019-07 (ADR-0033): el esquema es el 4 con ``min_reader_schema`` 1; el registro
        tiene la migración 3 → 4 «aspecto de los elementos (spec 019)», que no cambia el esquema
        mínimo de lectura y aplica ``apply_schema_4``; la tabla es interna y la última."""
        self.assertEqual((schema.SCHEMA_VERSION, schema.MIN_READER_SCHEMA), (4, 1))
        migration = m0004.MIGRATION
        self.assertIn(migration, migrations.REGISTRY)
        self.assertEqual(
            (migration.from_version, migration.to_version, migration.description),
            (3, 4, "aspecto de los elementos (spec 019)"),
        )
        self.assertIsNone(migration.min_reader_schema)
        self.assertIs(migration.apply, m0004.apply)
        self.assertEqual(migrations.plan_migrations(3, 4), (migration,))
        self.assertEqual(migrations.plan_migrations(2, 4), (m0003.MIGRATION, migration))
        self.assertEqual(schema.INTERNAL_TABLES[-1], TABLE)
        self.assertEqual(TABLE, "gb_appearance")


class MigrateSchema3Test(unittest.TestCase):
    def read(self, sql: str, database: Path | None = None) -> list[tuple]:
        with gpkg.GpkgConnection.open_read(database or _STATE["database"]) as db:
            return db.connection.execute(sql).fetchall()

    def test_backup_row_event_and_header(self) -> None:
        """RF-019-07 (RF-002-20): migrar un proyecto del esquema 3 deja la copia previa
        ``…respaldo-esquema-3`` con las huellas del proyecto sin migrar y datos intactos, una fila
        3 → 4, el evento, la base y la cabecera en el esquema 4 con ``min_reader_schema`` 1, de
        acuerdo, nada en falta, diario clásico y sin cerrojo."""
        result = _STATE["steps"][-1].result
        root, backup = _STATE["root"], _STATE["backup"]
        self.assertIsInstance(result, migrations.MigrationResult)
        self.assertEqual((result.from_version, result.to_version, result.applied),
                         (3, 4, ((3, 4),)))
        self.assertEqual((result.backup, result.warnings), (backup, ()))
        self.assertEqual(copytree.fingerprint(backup), _STATE["prints"])
        self.assertEqual(self.read("SELECT schema_version FROM gb_project", backup / DATABASE),
                         [(3,)])
        self.assertEqual(
            self.read("SELECT from_version, to_version, applied_with, backup_dir, user_host "
                      "FROM gb_schema_migration WHERE to_version = 4"),
            [(3, 4, "0.5.0", BACKUP_NAME, USER_HOST)],
        )
        with gpkg.GpkgConnection.open_read(_STATE["database"]) as db:
            migrated = events_mod.read_events(db.connection, events_mod.EventKind.MIGRATION)
            record = schema.read_project(db.connection)
            registered = schema.read_migrations(db.connection)
            missing = schema.missing_objects(db.connection, 4)
            journal = db.connection.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual([(i.data["from"], i.data["to"]) for i in migrated][-1], (3, 4))
        self.assertIn("aspecto de los elementos (spec 019)", migrated[-1].message)
        self.assertEqual((record.schema_version, record.min_reader_schema), (4, 1))
        self.assertEqual((registered[-1], missing, journal), ((3, 4), [], "delete"))
        header = manifest_mod.read_manifest(root)
        self.assertEqual((header.schema_version, header.min_reader_schema), (4, 1))
        self.assertEqual(manifest_mod.compare(header, record, registered).status,
                         manifest_mod.ManifestStatus.CONSISTENT)
        self.assertFalse((root / ".lock").exists())

    def test_nothing_else_changes(self) -> None:
        """RF-019-08 (ADR-0033, punto 5): la tabla nace vacía; ningún fichero fuera de la base,
        su diario y la cabecera cambia; cada fila de cada tabla anterior es igual (de
        ``gb_project`` solo el esquema, quién y cuándo; a ``gb_event``, ``gb_schema_migration`` y
        ``gpkg_extensions`` solo se les añaden filas); el seguimiento de cada tabla de datos
        (``last_change`` y huella), igual; y de ``sqlite_master`` solo se añaden la tabla y sus
        tres disparadores."""
        prefix = f"{fixture.PROJECT_FOLDER}/"
        written = {prefix + name for name in WRITTEN}
        before = {rel: v for rel, v in _STATE["files"].items() if rel not in written}
        after = {rel: v for rel, v in _STATE["after_files"].items() if rel not in written}
        self.assertEqual(after, before)
        old, new = _STATE["tables"], _STATE["after_tables"]
        self.assertEqual(sorted(set(new) - set(old)), [TABLE])
        self.assertEqual(new[TABLE][1], [])
        for table, (columns, rows) in old.items():
            with self.subTest(tabla=table):
                after_columns, after_rows = new[table]
                self.assertEqual(after_columns, columns)
                if table == "gb_project":
                    keep = [i for i, c in enumerate(columns) if c not in PROJECT_CHANGES]
                    self.assertEqual([tuple(r[i] for i in keep) for r in after_rows],
                                     [tuple(r[i] for i in keep) for r in rows])
                    self.assertEqual(after_rows[0][columns.index("schema_version")], 4)
                elif table in APPENDED:
                    self.assertEqual(after_rows[: len(rows)], rows)
                    self.assertGreater(len(after_rows), len(rows))
                elif table == "sqlite_sequence":
                    self.assertEqual([r for r in after_rows if r[0] not in SEQUENCES],
                                     [r for r in rows if r[0] not in SEQUENCES])
                else:
                    self.assertEqual(after_rows, rows)
        self.assertEqual(_STATE["after_states"], _STATE["states"])
        self.assertNotIn(TABLE, _STATE["after_states"])
        before_m, after_m = _STATE["master"], _STATE["after_master"]
        self.assertEqual({k for k in before_m if after_m.get(k) != before_m[k]}, set())
        added = {k for k in after_m if k not in before_m}
        self.assertEqual(
            {name for _kind, name in added if _kind != "index"},
            {TABLE, *schema.APPEARANCE_TRIGGERS},
        )
        self.assertEqual({table for table, _sql in (after_m[k] for k in added)}, {TABLE})

    def test_same_structure_as_a_new_project(self) -> None:
        """RF-019-07 (plan §5.2.3): crear un proyecto de cero y migrar el del esquema 3 dan lo
        mismo de Geoblender en ``sqlite_master`` y en ``gpkg_extensions``, con ``gb_appearance``
        declarada ``write-only``."""
        with project_tmp("gb-m4n-") as tmp:
            created = create.create_project(
                tmp, make_settings(name="Cantera Nueva"), SESSION,
                userdata_mod.UserData(tmp / "u"), clock=FakeClock(),
            )
            created.project.close()
            fresh = created.root / DATABASE
            migrated_master, migrated_ext = _internal_structure(_STATE["database"])
            fresh_master, fresh_ext = _internal_structure(fresh)
            with gpkg.GpkgConnection.open_read(fresh) as db:
                versions = db.connection.execute(
                    "SELECT schema_version, min_reader_schema FROM gb_project").fetchone()
                missing = schema.missing_objects(db.connection, 4)
        self.assertEqual(migrated_master, fresh_master)
        self.assertEqual(migrated_ext, fresh_ext)
        self.assertEqual((tuple(versions), missing), ((4, 1), []))
        declared = {row[0]: row[3:] for row in migrated_ext}
        self.assertEqual(declared[TABLE], (gpkg_base.EXTENSION_DEFINITION, "write-only"))

    def test_migrating_again_changes_nothing(self) -> None:
        """RF-019-07 (spec 002, I-2): volver a migrar no hace nada, y aplicar ``m0004`` dos veces
        más sobre una copia de la base, migrada o creada de cero, no cambia su volcado ni sus
        bytes."""
        work, root = _STATE["work"], _STATE["root"]
        before = _files(work)
        steps = list(migrations.migrate_steps(
            root, SESSION, _STATE["userdata"], clock=_STATE["clock"], pid_alive=_STATE["pids"]))
        result = steps[-1].result
        self.assertEqual((result.applied, result.backup), ((), None))
        self.assertEqual((result.from_version, result.to_version), (4, 4))
        self.assertEqual(_files(work), before)
        with project_tmp("gb-m4a-") as tmp:
            created = create.create_project(
                tmp, make_settings(name="Cantera Nueva"), SESSION,
                userdata_mod.UserData(tmp / "u"), clock=FakeClock(),
            )
            created.project.close()
            copies = {"migrada": tmp / "migrada.gpkg", "nueva": tmp / "nueva.gpkg"}
            shutil.copyfile(_STATE["database"], copies["migrada"])
            shutil.copyfile(created.root / DATABASE, copies["nueva"])
            for label, database in copies.items():
                with self.subTest(base=label):
                    dump, digest = _dump(database), _sha256(database)
                    for _ in range(2):
                        with gpkg.GpkgConnection.open_write(database) as db:
                            with db.transaction() as conn:
                                m0004.apply(conn)
                        self.assertEqual(_dump(database), dump)
                    self.assertEqual(_sha256(database), digest)

    def test_a_reader_of_schema_3_is_told_it_is_newer(self) -> None:
        """RF-019-07 (ADR-0033, consecuencias): con ``SCHEMA_VERSION = 3`` simulado (un Geoblender
        anterior), el proyecto del esquema 4 abre en solo lectura con el aviso de «versión más
        moderna» (esquema 4), entero (no solo la cabecera), y sacar una copia local dice «es de un
        esquema posterior»; abrir y cerrar no cambian ningún fichero."""
        work, root = _STATE["work"], _STATE["root"]
        before = _files(work)
        with (mock.patch.object(open_mod, "SCHEMA_VERSION", 3),
              mock.patch.object(checkout, "SCHEMA_VERSION", 3)):
            inspection = open_mod.inspect_project(
                root, SESSION, _STATE["userdata"], clock=_STATE["clock"],
                pid_alive=_STATE["pids"])
            self.assertIs(inspection.schema, open_mod.SchemaRelation.NEWER)
            with self.assertRaises(errors.ProjectError) as ctx:
                checkout._source_record(inspection)
            self.assertEqual(ctx.exception.code, "core.checkout_schema_newer")
            self.assertIn("esquema posterior", ctx.exception.reason)
            result = open_mod.open_project(
                root, SESSION, _STATE["userdata"], clock=_STATE["clock"],
                pid_alive=_STATE["pids"])
        project = result.project
        try:
            self.assertEqual(project.mode, model.OpenMode.READ_ONLY)
            self.assertEqual(project.read_only_reason, model.ReadOnlyCode.SCHEMA_NEWER)
            self.assertFalse(project.header_only)
            for text in ("más moderna", "esquema 4", "0.5.0"):
                self.assertIn(text, result.status.message)
            with project.read() as conn:
                self.assertEqual(schema.missing_objects(conn, 3), [])
        finally:
            project.close()
        self.assertEqual(_files(work), before)


class WriterRuleTest(unittest.TestCase):
    def test_only_geoblender_writes(self) -> None:
        """RF-019-08 (ADR-0033): una conexión ajena (sin ``gb_writer()``, como QGIS) no escribe,
        cambia ni borra ``gb_appearance``; una de Geoblender sí (la tabla es mutable)."""
        with project_tmp("gb-m4w-") as tmp:
            database = tmp / "w.gpkg"
            shutil.copyfile(_STATE["database"], database)
            row = ("Cota", "DTM", "color", "#56B4E9", "2026-11-25T10:00:00.000Z", "a@b")
            insert = ("INSERT INTO gb_appearance (item_name, item_kind, prop, value, "
                      "modified_at, modified_by) VALUES (?, ?, ?, ?, ?, ?)")
            raw = sqlite3.connect(database)
            try:
                with self.assertRaises(sqlite3.Error):
                    raw.execute(insert, row)
            finally:
                raw.close()
            with gpkg.GpkgConnection.open_write(database) as db:
                with db.transaction() as conn:
                    conn.execute(insert, row)
                    conn.execute("UPDATE gb_appearance SET value = '#000000'")
                    self.assertEqual(
                        conn.execute("SELECT value FROM gb_appearance").fetchall(),
                        [("#000000",)])
                    conn.execute("DELETE FROM gb_appearance")
            raw = sqlite3.connect(database)
            try:
                with self.assertRaises(sqlite3.Error):
                    raw.execute("DELETE FROM gb_appearance")
            finally:
                raw.close()


if __name__ == "__main__":
    unittest.main()
