# SPDX-License-Identifier: GPL-3.0-or-later
"""Migración del esquema 1 al 2, la procedencia (spec 008 §8, último caso, y §11; T09;
RF-002-20, RF-002-22; plan 008 §5.2.4 y §5.4.12).

Los proyectos del esquema 1 son sintéticos y fieles a lo que dejaba la spec 002
(``core_fixtures.make_schema_1``: sin las tablas de la procedencia y con la definición
antigua de la extensión). Se migran con la migración real del registro (``m0002``) y el
``migrate_steps`` de la 002, sin cambios: copia previa con sus huellas, una transacción,
fila en ``gb_schema_migration``, evento ``migration`` y cabecera regenerada.

Las bases que escribe «otro programa» en estas pruebas son conexiones de ``sqlite3`` sin
``gb_writer()``, como QGIS.
"""

import hashlib
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from tests.support.core_fixtures import (
    SCHEMA_1_DEFINITION,
    SCHEMA_1_TABLES,
    FakeClock,
    FakePids,
    make_schema_1,
    make_session,
    make_settings,
    project_tmp,
)
from tests.support.package import import_geoblender

create = import_geoblender("core.project.create")
open_mod = import_geoblender("core.project.open")
model = import_geoblender("core.project.model")
schema = import_geoblender("core.project.schema")
manifest_mod = import_geoblender("core.project.manifest")
events_mod = import_geoblender("core.project.events")
copytree = import_geoblender("core.project.copytree")
migrations = import_geoblender("core.project.migrations")
m0002 = import_geoblender("core.project.migrations.m0002")
provenance_schema = import_geoblender("core.provenance.schema")
gpkg = import_geoblender("core.gpkg")
gpkg_base = import_geoblender("core.gpkg.base")
userdata_mod = import_geoblender("core.userdata")

SESSION_A = make_session()
SESSION_B = make_session(
    session_uid="00000000-0000-4000-8000-000000000002", host="PC-PRUEBA-B", user="otra",
    pid=777, geoblender_version="0.3.0",
)
EXCLUDE = ("cache", ".lock")
BACKUP_NAME = "Cantera Prueba.gbproj.respaldo-esquema-1"
PROVENANCE = tuple(provenance_schema.TABLES)
# Lo que deja QGIS en un proyecto: una capa suya y la declaración de otra extensión, aquí
# con el mismo texto que la de Geoblender en el esquema 1 (la migración no la toca).
FOREIGN_EXTENSION = ("capa_qgis", None, "otra_extension", SCHEMA_1_DEFINITION, "read-write")


def _snapshot(root: Path) -> dict[str, tuple[int, str, int] | str]:
    """Cada fichero de la carpeta (recursiva) con tamaño, sha256 y fecha; y cada carpeta."""
    found: dict[str, tuple[int, str, int] | str] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_dir():
            found[rel] = "carpeta"
        else:
            stat = path.stat()
            found[rel] = (stat.st_size, hashlib.sha256(path.read_bytes()).hexdigest(), stat.st_mtime_ns)
    return found


def _structure(database: Path) -> tuple[list[tuple], list[tuple]]:
    """El ``sqlite_master`` (sin las páginas raíz) y las filas de ``gpkg_extensions``, en
    orden."""
    conn = sqlite3.connect(database)
    try:
        master = conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
        extensions = conn.execute(
            "SELECT table_name, column_name, extension_name, definition, scope "
            "FROM gpkg_extensions ORDER BY table_name, column_name, extension_name"
        ).fetchall()
    finally:
        conn.close()
    return master, extensions


def _dump(database: Path) -> list[str]:
    conn = sqlite3.connect(database)
    try:
        return list(conn.iterdump())
    finally:
        conn.close()


class Env:
    """Una carpeta con un proyecto del esquema 1 creado y cerrado por la sesión A."""

    def __init__(self, tmp: Path) -> None:
        self.parent = tmp / "proyectos"
        self.parent.mkdir()
        self.userdata = userdata_mod.UserData(tmp / "datos_usuario")
        self.clock = FakeClock()
        self.pids = FakePids({SESSION_A.pid, SESSION_B.pid})
        self.root = self.create("Cantera Prueba")
        self.db = self.root / "project.gpkg"
        make_schema_1(self.root)

    def create(self, name: str) -> Path:
        created = create.create_project(
            self.parent, make_settings(name=name), SESSION_A, self.userdata, clock=self.clock
        )
        created.project.close()
        return created.root

    def migrate(self, session=SESSION_B) -> list:
        """Migra con el registro real y el esquema de esta versión (lo que hace el operador
        de abrir cuando se acepta migrar)."""
        return list(
            migrations.migrate_steps(
                self.root, session, self.userdata, clock=self.clock, pid_alive=self.pids
            )
        )

    def open(self, session=SESSION_B, **kwargs):
        return open_mod.open_project(
            self.root, session, self.userdata, clock=self.clock, pid_alive=self.pids, **kwargs
        )

    def read(self, sql: str, database: Path | None = None) -> list[tuple]:
        with gpkg.GpkgConnection.open_read(database or self.db) as db:
            return db.connection.execute(sql).fetchall()

    def prints(self, root: Path | None = None):
        return copytree.fingerprint(root or self.root, exclude=EXCLUDE)


class RegistryTest(unittest.TestCase):
    def test_the_step_1_to_2_is_registered(self) -> None:
        """RF-002-20 (plan 008 §5.2.4): el registro tiene la migración 1 → 2 de la
        procedencia, que no cambia el esquema mínimo de lectura (sigue en 1, RF-002-22), y
        es la cadena del esquema 1 al de esta versión."""
        self.assertEqual(schema.SCHEMA_VERSION, 2)
        migration = m0002.MIGRATION
        self.assertIn(migration, migrations.REGISTRY)
        self.assertEqual(
            (migration.from_version, migration.to_version, migration.description),
            (1, 2, "procedencia (spec 008)"),
        )
        self.assertIsNone(migration.min_reader_schema)
        self.assertIs(migration.apply, m0002.apply)
        self.assertEqual(migrations.plan_migrations(1, schema.SCHEMA_VERSION), (migration,))


class MigrateTest(unittest.TestCase):
    def test_schema_1_project_is_faithful(self) -> None:
        """Spec 008 §8, último caso: el proyecto sintético del esquema 1 tiene lo que
        dejaba la 002 (sus tres tablas internas y sus disparadores, con la definición
        antigua de la extensión) y nada de la procedencia, y abre en solo lectura «sin
        migrar» (RF-002-20)."""
        with project_tmp() as tmp:
            env = Env(tmp)
            conn = sqlite3.connect(env.db)
            try:
                self.assertEqual(schema.missing_objects(conn, 1), [])
                missing = schema.missing_objects(conn, 2)
                names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
                declared = conn.execute(
                    "SELECT table_name, definition FROM gpkg_extensions "
                    "WHERE extension_name = 'imga_geoblender' ORDER BY table_name"
                ).fetchall()
            finally:
                conn.close()
            provenance = (
                [f"table {name}" for name in PROVENANCE]
                + [f"index {name}" for name in provenance_schema.INDEXES]
                + [f"trigger {name}" for name in provenance_schema.TRIGGERS]
            )
            self.assertEqual(missing, provenance)
            self.assertFalse(names & {item.split(" ", 1)[1] for item in provenance})
            self.assertEqual(
                declared, [(table, SCHEMA_1_DEFINITION) for table in sorted(SCHEMA_1_TABLES)]
            )
            self.assertEqual(env.read("SELECT schema_version, min_reader_schema FROM gb_project"), [(1, 1)])
            result = env.open()
            try:
                self.assertEqual(result.project.read_only_reason, model.ReadOnlyCode.NOT_MIGRATED)
            finally:
                result.project.close()

    def test_migrates_with_a_backup_and_opens_without_provenance(self) -> None:
        """Spec 008 §8, último caso; RF-002-20: migrar un proyecto del esquema 1 con la
        migración real hace antes la copia previa ``…respaldo-esquema-1`` junto al original
        con sus huellas (y del esquema 1), registra la fila 1 → 2 en
        ``gb_schema_migration`` y el evento ``migration``, deja la base y la cabecera en el
        esquema 2 con ``min_reader_schema`` 1, y el proyecto abre en escritura sin que le
        falte nada, sin avisos y sin parámetros, entradas ni operaciones (las 12 tablas de
        la procedencia, vacías)."""
        with project_tmp() as tmp:
            env = Env(tmp)
            before = env.prints()
            steps = env.migrate()
            result = steps[-1].result
            backup = env.parent / BACKUP_NAME
            self.assertIsInstance(result, migrations.MigrationResult)
            self.assertEqual((result.from_version, result.to_version), (1, 2))
            self.assertEqual(result.applied, ((1, 2),))
            self.assertEqual(result.backup, backup)
            self.assertEqual(result.warnings, ())
            self.assertEqual(env.prints(backup), before)
            self.assertEqual(
                env.read("SELECT schema_version FROM gb_project", backup / "project.gpkg"), [(1,)]
            )
            self.assertEqual(
                sorted(path.name for path in env.parent.iterdir()),
                sorted([env.root.name, BACKUP_NAME]),
            )
            self.assertEqual(
                env.read(
                    "SELECT from_version, to_version, applied_with, backup_dir, user_host "
                    "FROM gb_schema_migration"
                ),
                [(1, 2, "0.3.0", BACKUP_NAME, SESSION_B.user_host)],
            )
            with gpkg.GpkgConnection.open_read(env.db) as db:
                migrated = events_mod.read_events(db.connection, events_mod.EventKind.MIGRATION)
            self.assertEqual(
                [(item.data["from"], item.data["to"], item.data["backup_dir"]) for item in migrated],
                [(1, 2, BACKUP_NAME)],
            )
            self.assertIn("procedencia (spec 008)", migrated[0].message)
            self.assertEqual(
                env.read("SELECT schema_version, min_reader_schema, last_written_with FROM gb_project"),
                [(2, 1, "0.3.0")],
            )
            header = manifest_mod.read_manifest(env.root)
            self.assertEqual((header.schema_version, header.min_reader_schema), (2, 1))
            with gpkg.GpkgConnection.open_read(env.db) as db:
                record = schema.read_project(db.connection)
                registered = schema.read_migrations(db.connection)
                self.assertEqual(schema.missing_objects(db.connection, 2), [])
            self.assertEqual(registered, ((1, 2),))
            self.assertEqual(
                manifest_mod.compare(header, record, registered).status,
                manifest_mod.ManifestStatus.CONSISTENT,
            )
            self.assertFalse((env.root / ".lock").exists())
            opened = env.open()
            try:
                project = opened.project
                self.assertEqual(project.mode, model.OpenMode.WRITE_LOCAL)
                self.assertEqual(project.schema_version, 2)
                self.assertEqual(opened.warnings, ())
                with project.read() as conn:
                    counts = {
                        table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                        for table in PROVENANCE
                    }
            finally:
                project.close()
            self.assertEqual(counts, dict.fromkeys(PROVENANCE, 0))
            for table in ("gb_parameter", "gb_input", "gb_operation"):
                self.assertIn(table, counts)

    def test_created_and_migrated_have_the_same_structure(self) -> None:
        """RF-002-20 (plan 008 §5.2.4): crear un proyecto de cero (ya en el esquema 2) y
        migrar uno del esquema 1 dan el mismo ``sqlite_master`` (tablas, índices y disparadores con su
        SQL) y las mismas filas de ``gpkg_extensions`` (la definición sin número de esquema
        también en las tres tablas del 1)."""
        with project_tmp() as tmp:
            env = Env(tmp)
            fresh = env.create("Cantera Nueva") / "project.gpkg"
            env.migrate()
            migrated_master, migrated_extensions = _structure(env.db)
            fresh_master, fresh_extensions = _structure(fresh)
            self.assertEqual(migrated_master, fresh_master)
            self.assertEqual(migrated_extensions, fresh_extensions)
            definitions = {row[3] for row in migrated_extensions if row[2] == "imga_geoblender"}
            self.assertEqual(definitions, {gpkg_base.EXTENSION_DEFINITION})
            self.assertEqual(
                sorted(row[0] for row in migrated_extensions if row[2] == "imga_geoblender"),
                sorted(schema.INTERNAL_TABLES),
            )

    def test_migrating_twice_is_harmless(self) -> None:
        """RF-002-20 (spec 002, I-2; plan 008 §5.4.12): volver a migrar un proyecto ya
        migrado no hace nada (ni copia previa ni cambio de un byte), y aplicar ``m0002``
        otra vez sobre la base migrada, o sobre una creada de cero, no cambia su volcado
        SQL."""
        with project_tmp() as tmp:
            env = Env(tmp)
            env.migrate()
            before = _snapshot(env.parent)
            result = env.migrate()[-1].result
            self.assertEqual((result.applied, result.backup), ((), None))
            self.assertEqual((result.from_version, result.to_version), (2, 2))
            self.assertEqual(_snapshot(env.parent), before)
            fresh = env.create("Cantera Nueva") / "project.gpkg"
            for database in (env.db, fresh):
                with self.subTest(base=database.parent.name):
                    dump = _dump(database)
                    for _ in range(2):
                        with gpkg.GpkgConnection.open_write(database) as db:
                            with db.transaction() as conn:
                                m0002.apply(conn)
                        self.assertEqual(_dump(database), dump)

    def test_user_tables_and_other_extensions_are_untouched(self) -> None:
        """Constitución, principio 7; RF-002-20: una capa que añadió QGIS al proyecto del
        esquema 1 y la declaración de otra extensión (aunque tenga el mismo texto que la de
        Geoblender en el esquema 1) quedan como estaban; solo cambian las declaraciones de
        Geoblender."""
        with project_tmp() as tmp:
            env = Env(tmp)
            foreign = sqlite3.connect(env.db, isolation_level=None)
            try:
                foreign.execute("CREATE TABLE capa_qgis (fid INTEGER PRIMARY KEY, nota TEXT)")
                foreign.executemany(
                    "INSERT INTO capa_qgis (nota) VALUES (?)", [("1,5",), ("esquema 1",)]
                )
                foreign.execute(
                    "INSERT INTO gpkg_extensions VALUES (?, ?, ?, ?, ?)", FOREIGN_EXTENSION
                )
            finally:
                foreign.close()
            rows_sql = "SELECT * FROM capa_qgis ORDER BY fid"
            others_sql = "SELECT * FROM gpkg_extensions WHERE extension_name <> 'imga_geoblender'"
            rows, others = env.read(rows_sql), env.read(others_sql)
            self.assertIn(FOREIGN_EXTENSION, others)
            env.migrate()
            self.assertEqual(env.read(rows_sql), rows)
            self.assertEqual(env.read(others_sql), others)
            definitions = env.read(
                "SELECT DISTINCT definition FROM gpkg_extensions "
                "WHERE extension_name = 'imga_geoblender'"
            )
            self.assertEqual(definitions, [(gpkg_base.EXTENSION_DEFINITION,)])

    def test_a_reader_of_schema_1_opens_the_migrated_read_only(self) -> None:
        """RF-002-22 (spec 008 §11; plan 008 §5.4.12): con ``SCHEMA_VERSION = 1`` simulado
        (un Geoblender de la 002), el proyecto migrado abre en solo lectura con el aviso de
        «versión más moderna» (esquema 2), lee su base sin echar nada en falta, y abrir y
        cerrar no cambian ningún fichero."""
        with project_tmp() as tmp:
            env = Env(tmp)
            env.migrate()
            before = _snapshot(env.parent)
            with mock.patch.object(open_mod, "SCHEMA_VERSION", 1):
                inspection = open_mod.inspect_project(
                    env.root, SESSION_A, env.userdata, clock=env.clock, pid_alive=env.pids
                )
                self.assertIs(inspection.schema, open_mod.SchemaRelation.NEWER)
                result = env.open(SESSION_A)
            project = result.project
            try:
                self.assertEqual(project.mode, model.OpenMode.READ_ONLY)
                self.assertEqual(project.read_only_reason, model.ReadOnlyCode.SCHEMA_NEWER)
                self.assertFalse(project.header_only)
                message = result.status.message
                for text in ("más moderna", "esquema 2", "0.3.0"):
                    self.assertIn(text, message)
                with project.read() as conn:
                    self.assertEqual(schema.read_project(conn).schema_version, 2)
            finally:
                project.close()
            self.assertEqual(_snapshot(env.parent), before)


if __name__ == "__main__":
    unittest.main()
