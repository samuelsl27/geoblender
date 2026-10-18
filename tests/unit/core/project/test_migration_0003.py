# SPDX-License-Identifier: GPL-3.0-or-later
"""Migración del esquema 2 al 3: versiones, revisiones y decisiones de la propiedad (spec 009,
T04; RF-009-02, RF-009-04, RF-009-12, RF-009-23; plan 009 §5.2.1–§5.2.3 y D-24).

El proyecto del esquema 2 es ``esquema2.zip`` (T03), que escribió el código de partida con los
datos de la 005, la 006 y la 008: se descomprime una vez para todo el módulo en una carpeta
temporal y se migra con la migración real del registro (``m0003``) y el ``migrate_steps`` de la
002, sin cambios. Lo que se mira antes y después: cada fichero de la carpeta (tamaño, sha256 y
fecha), cada fila de cada tabla, ``sqlite_master`` y el estado de seguimiento de cada tabla de
datos (``core.datasets.tracking``: su ``last_change`` y la huella de su SQL). Las pruebas de los
disparadores trabajan cada una sobre una copia de la base ya migrada.

Las bases que escribe «otro programa» son conexiones de ``sqlite3`` sin ``gb_writer()``, como
QGIS.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import tempfile
import unittest
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any
from unittest import mock

from tests.support import schema2_project as fixture
from tests.support.core_fixtures import FakeClock, FakePids, make_session, make_settings, project_tmp
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
m0003 = import_geoblender("core.project.migrations.m0003")
versions_schema = import_geoblender("core.versions.schema")
provenance_schema = import_geoblender("core.provenance.schema")
tracking = import_geoblender("core.datasets.tracking")
gpkg = import_geoblender("core.gpkg")
gpkg_base = import_geoblender("core.gpkg.base")
userdata_mod = import_geoblender("core.userdata")

SESSION = make_session(
    session_uid="00000000-0000-4000-8000-000000000003", host="PC-PRUEBA-B", user="otra",
    pid=778, geoblender_version="0.4.0",
)
USER_HOST = "otra@PC-PRUEBA-B"
BACKUP_NAME = f"{fixture.PROJECT_NAME}.gbproj.respaldo-esquema-2"
DATABASE = "project.gpkg"
WRITTEN = ("project.gpkg", "project.gpkg-journal", "manifest.json")
"""Lo único de la carpeta del proyecto que puede cambiar al migrar (RF-009-02)."""
VERSION_TABLES = ("gb_version", "gb_revision", "gb_revision_item", "gb_decision",
                  "gb_decision_link")
NEW_COLUMNS: dict[str, dict[str, object]] = {
    "gb_dataset": {"version_uid": "", "title": None},
    "gb_operation": {"revision_uid": ""},
}
"""Las columnas que añade el esquema 3 a las tablas de la 008 y su valor en lo migrado: todo es
del proyecto."""
PROJECT_CHANGES = ("schema_version", "last_written_with", "modified_at")
APPENDED = ("gb_event", "gb_schema_migration", "gpkg_extensions")
"""Las tablas a las que la migración solo añade filas: su evento, su fila y las declaraciones
de las tablas nuevas."""
SEQUENCES = ("gb_event", "gb_schema_migration")
NOW = "2026-10-18T10:00:00.000Z"
USER = "prueba@PC-PRUEBA-A"

_STATE: dict[str, Any] = {}


def _uid(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012x}"


def _files(folder: Path, skip: Path | None = None) -> dict[str, object]:
    """Cada fichero de ``folder`` (recursiva) con su tamaño, su sha256 y su fecha, y cada
    carpeta; sin lo que hay dentro de ``skip``."""
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
    """Las columnas y las filas (por ``rowid``) de cada tabla de la base."""
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
    """``sqlite_master`` sin las páginas raíz: (tipo, nombre) → (tabla, SQL)."""
    with gpkg.GpkgConnection.open_read(database) as db:
        rows = db.connection.execute("SELECT type, name, tbl_name, sql FROM sqlite_master")
        return {(kind, name): (table, sql) for kind, name, table, sql in rows}


def _states(database: Path) -> dict[str, Any]:
    with gpkg.GpkgConnection.open_read(database) as db:
        return tracking.table_states(db.connection)


def _internal_structure(database: Path) -> tuple[list[tuple], list[tuple]]:
    """Lo de Geoblender en ``sqlite_master`` (todo lo de sus tablas internas, sin las páginas
    raíz) y sus filas de ``gpkg_extensions``, en orden."""
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
    """Descomprime ``esquema2.zip``, mira todo, lo migra con el registro real y vuelve a
    mirarlo."""
    tmp = unittest.enterModuleContext(project_tmp("gb-m3-"))
    work = tmp / "z"
    work.mkdir()
    root = fixture.extract(work)
    database = root / DATABASE
    userdata = userdata_mod.UserData(tmp / "u")
    clock = FakeClock()
    pids = FakePids({SESSION.pid})
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
    def test_the_step_2_to_3_is_registered(self) -> None:
        """RF-009-02 (plan §5.2.3, D-24): el esquema de esta versión es el 3, con
        ``min_reader_schema`` 1; el registro tiene la migración 2 → 3 «versiones y revisiones
        (spec 009)», que no cambia el esquema mínimo de lectura (lo sube crear la primera
        versión, D-24) y aplica ``apply_schema_3``; la cadena desde el 1 es ``m0002`` y
        ``m0003``; las tablas internas son las del 1, las de la procedencia y las cinco
        nuevas."""
        self.assertEqual((schema.SCHEMA_VERSION, schema.MIN_READER_SCHEMA), (3, 1))
        migration = m0003.MIGRATION
        self.assertIn(migration, migrations.REGISTRY)
        self.assertEqual(
            (migration.from_version, migration.to_version, migration.description),
            (2, 3, "versiones y revisiones (spec 009)"),
        )
        self.assertIsNone(migration.min_reader_schema)
        self.assertIs(migration.apply, m0003.apply)
        self.assertEqual(migrations.plan_migrations(2, schema.SCHEMA_VERSION), (migration,))
        self.assertEqual(migrations.plan_migrations(1, schema.SCHEMA_VERSION),
                         (m0002.MIGRATION, migration))
        self.assertEqual(versions_schema.INTERNAL_TABLES, VERSION_TABLES)
        self.assertEqual(
            schema.INTERNAL_TABLES,
            schema.SCHEMA_1_TABLES + provenance_schema.INTERNAL_TABLES + VERSION_TABLES,
        )


class MigrateSchema2Test(unittest.TestCase):
    """El proyecto de ``esquema2.zip``, migrado una vez en ``setUpModule``."""

    def read(self, sql: str, database: Path | None = None) -> list[tuple]:
        with gpkg.GpkgConnection.open_read(database or _STATE["database"]) as db:
            return db.connection.execute(sql).fetchall()

    def test_backup_row_event_and_header(self) -> None:
        """RF-009-02, RF-009-23 (RF-002-20; plan §5.2.3): migrar deja antes la copia previa
        ``…respaldo-esquema-2`` junto al original con las huellas del proyecto sin migrar (y del
        esquema 2), una fila 2 → 3 en ``gb_schema_migration`` con quién y con qué versión, el
        evento ``migration``, la base y la cabecera en el esquema 3 con ``min_reader_schema`` 1
        y de acuerdo, nada echado en falta, el diario clásico y sin cerrojo."""
        result = _STATE["steps"][-1].result
        root, backup = _STATE["root"], _STATE["backup"]
        self.assertIsInstance(result, migrations.MigrationResult)
        self.assertEqual((result.from_version, result.to_version, result.applied),
                         (2, 3, ((2, 3),)))
        self.assertEqual((result.backup, result.warnings), (backup, ()))
        self.assertEqual(copytree.fingerprint(backup), _STATE["prints"])
        self.assertEqual(self.read("SELECT schema_version FROM gb_project", backup / DATABASE),
                         [(2,)])
        self.assertEqual(sorted(path.name for path in root.parent.iterdir()),
                         sorted([root.name, BACKUP_NAME]))
        self.assertEqual(
            self.read("SELECT from_version, to_version, applied_with, backup_dir, user_host "
                      "FROM gb_schema_migration"),
            [(2, 3, "0.4.0", BACKUP_NAME, USER_HOST)],
        )
        with gpkg.GpkgConnection.open_read(_STATE["database"]) as db:
            migrated = events_mod.read_events(db.connection, events_mod.EventKind.MIGRATION)
            record = schema.read_project(db.connection)
            registered = schema.read_migrations(db.connection)
            missing = schema.missing_objects(db.connection, 3)
            journal = db.connection.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(
            [(item.data["from"], item.data["to"], item.data["backup_dir"]) for item in migrated],
            [(2, 3, BACKUP_NAME)],
        )
        self.assertIn("versiones y revisiones (spec 009)", migrated[0].message)
        self.assertEqual((record.schema_version, record.min_reader_schema,
                          record.last_written_with), (3, 1, "0.4.0"))
        self.assertEqual((registered, missing, journal), (((2, 3),), [], "delete"))
        header = manifest_mod.read_manifest(root)
        self.assertEqual((header.schema_version, header.min_reader_schema), (3, 1))
        self.assertEqual(manifest_mod.compare(header, record, registered).status,
                         manifest_mod.ManifestStatus.CONSISTENT)
        self.assertFalse((root / ".lock").exists())
        self.assertFalse((root / f"{DATABASE}-journal").exists())

    def test_rows_files_and_hashes_unchanged(self) -> None:
        """RF-009-02, RF-009-23 (plan §5.2.3: no hay datos que migrar): tras migrar, ningún
        fichero de la carpeta del proyecto ni de sus entregas (``fuentes/``) distinto de la base,
        su diario y la cabecera cambia de tamaño, de huella ni de fecha; cada fila de cada tabla
        que había es igual (de ``gb_project`` solo cambian el esquema, quién escribió y cuándo;
        a ``gb_event``, ``gb_schema_migration`` y ``gpkg_extensions`` solo se les añaden filas);
        las columnas nuevas, vacías (todo es del proyecto); las cinco tablas nuevas, vacías; y
        el seguimiento de cada tabla de datos (``last_change`` y la huella de su SQL), igual: ni
        un hash de lo que existe cambia."""
        prefix = f"{fixture.PROJECT_FOLDER}/"
        written = {prefix + name for name in WRITTEN}
        before = {rel: value for rel, value in _STATE["files"].items() if rel not in written}
        after = {rel: value for rel, value in _STATE["after_files"].items() if rel not in written}
        self.assertEqual(after, before)
        self.assertIn(prefix + DATABASE, _STATE["after_files"])
        self.assertGreater(len(before), 20)

        old, new = _STATE["tables"], _STATE["after_tables"]
        self.assertEqual(sorted(set(new) - set(old)), sorted(VERSION_TABLES))
        for table in VERSION_TABLES:
            with self.subTest(nueva=table):
                self.assertEqual(new[table][1], [])
        for table, (columns, rows) in old.items():
            with self.subTest(tabla=table):
                after_columns, after_rows = new[table]
                added = tuple(column for column in after_columns if column not in columns)
                self.assertEqual(added, tuple(NEW_COLUMNS.get(table, {})))
                index = [after_columns.index(column) for column in columns]
                projected = [tuple(row[i] for i in index) for row in after_rows]
                if table == "gb_project":
                    keep = [i for i, column in enumerate(columns) if column not in PROJECT_CHANGES]
                    self.assertEqual([tuple(row[i] for i in keep) for row in projected],
                                     [tuple(row[i] for i in keep) for row in rows])
                    self.assertEqual(projected[0][columns.index("schema_version")], 3)
                elif table in APPENDED:
                    self.assertEqual(projected[: len(rows)], rows)
                    self.assertGreater(len(projected), len(rows))
                elif table == "sqlite_sequence":
                    self.assertEqual([row for row in projected if row[0] not in SEQUENCES],
                                     [row for row in rows if row[0] not in SEQUENCES])
                else:
                    self.assertEqual(projected, rows)
                for column, value in NEW_COLUMNS.get(table, {}).items():
                    position = after_columns.index(column)
                    self.assertEqual({row[position] for row in after_rows}, {value})
        self.assertEqual(len(old["gb_dataset"][1]), 29)
        self.assertEqual(_STATE["after_states"], _STATE["states"])
        self.assertGreater(len(_STATE["states"]), 20)

    def test_only_schema_3_changes_the_structure(self) -> None:
        """RF-009-02 (plan §5.2.2 y §5.2.3): de ``sqlite_master`` solo cambian el SQL de
        ``gb_dataset`` y de ``gb_operation`` (las columnas nuevas, tras la última y antes de las
        restricciones), el índice de nombres vivos (por versión) y los cuatro disparadores que
        nombran las columnas nuevas; lo nuevo es de las cinco tablas, de esas dos y de
        ``gb_parameter`` (el ámbito de versión); lo de los datos (capas, sondeos, rejillas) y
        de las demás tablas internas, igual."""
        before, after = _STATE["master"], _STATE["after_master"]
        replaced = {("table", "gb_dataset"), ("table", "gb_operation"),
                    *versions_schema.REPLACED}
        changed = {key for key in before if after.get(key) != before[key]}
        self.assertEqual(changed, replaced)
        self.assertEqual(
            {key[1] for key in replaced if key[0] != "table"},
            {"gb_dataset_name_active", "gb_dataset_fixed", "gb_dataset_name_ins",
             "gb_dataset_name_upd", "gb_operation_fixed"},
        )
        added = {key: value for key, value in after.items() if key not in before}
        owners = set(VERSION_TABLES) | {"gb_dataset", "gb_operation", "gb_parameter"}
        self.assertEqual({table for table, _sql in added.values()}, owners)
        expected = (
            {("table", table) for table in VERSION_TABLES}
            | {("index", name) for name in versions_schema.INDEXES}
            | {("trigger", name) for name in versions_schema.TRIGGERS}
            | {("index", name) for name in versions_schema.PROVENANCE_INDEXES}
            | {("trigger", name) for name in versions_schema.PROVENANCE_TRIGGERS}
        ) - replaced
        self.assertLessEqual(expected, set(added))
        for table in ("gb_dataset", "gb_operation"):
            with self.subTest(tabla=table):
                old, sql = before[("table", table)][1], after[("table", table)][1]
                self.assertEqual(old.count("CHECK"), sql.count("CHECK"))
                constraints = "\n  CHECK ("  # las restricciones de la tabla, al final
                self.assertEqual(old[old.index(constraints):], sql[sql.index(constraints):])
                for column in NEW_COLUMNS[table]:
                    self.assertLess(sql.index(f" {column} "), sql.index(constraints))
                    self.assertNotIn(f" {column} ", old)

    def test_schema_2_is_still_the_one_of_the_starting_code(self) -> None:
        """RF-009-02, RF-009-23 (spec 002 §6, I-3: un esquema publicado no cambia): las tablas,
        los índices y los disparadores del esquema 2 que crea ``core.provenance.schema``
        (``create_tables``, de la migración 1 → 2 y primer paso de crear un proyecto) son, con
        su SQL, los que escribió el código de partida en ``esquema2.zip``, también los que el
        esquema 3 sustituye."""
        before = {name: sql for (_kind, name), (_table, sql) in _STATE["master"].items()}
        expected = {**provenance_schema.TABLES, **provenance_schema.INDEXES,
                    **provenance_schema.TRIGGERS}
        self.assertEqual(len(expected), 82)
        self.assertEqual(
            sorted(name for name, sql in expected.items()
                   if before.get(name) != versions_schema.stored_sql(sql)), [])

    def test_same_structure_as_a_new_project(self) -> None:
        """RF-009-02 (plan §5.2.3): crear un proyecto de cero (el esquema 2 y después
        ``apply_schema_3``) y migrar el del esquema 2 dan lo mismo de Geoblender en
        ``sqlite_master`` (tablas, índices y disparadores con su SQL) y las mismas filas suyas
        en ``gpkg_extensions``, con las cinco tablas nuevas declaradas ``write-only``."""
        with project_tmp("gb-m3n-") as tmp:
            created = create.create_project(
                tmp, make_settings(name="Cantera Nueva"), SESSION,
                userdata_mod.UserData(tmp / "u"), clock=FakeClock(),
            )
            created.project.close()
            fresh = created.root / DATABASE
            migrated_master, migrated_extensions = _internal_structure(_STATE["database"])
            fresh_master, fresh_extensions = _internal_structure(fresh)
            with gpkg.GpkgConnection.open_read(fresh) as db:
                versions = db.connection.execute(
                    "SELECT schema_version, min_reader_schema FROM gb_project").fetchone()
                missing = schema.missing_objects(db.connection, 3)
        self.assertEqual(migrated_master, fresh_master)
        self.assertEqual(migrated_extensions, fresh_extensions)
        self.assertEqual((tuple(versions), missing), ((3, 1), []))
        declared = {row[0]: row[3:] for row in migrated_extensions}
        self.assertEqual(sorted(declared), sorted(schema.INTERNAL_TABLES))
        for table in VERSION_TABLES:
            self.assertEqual(declared[table], (gpkg_base.EXTENSION_DEFINITION, "write-only"))
        self.assertGreater(len(migrated_master), 150)

    def test_migrating_again_changes_nothing(self) -> None:
        """RF-009-02 (spec 002, I-2; plan §5.2.3): volver a migrar el proyecto migrado no hace
        nada (ni copia previa ni un byte distinto en la carpeta), y aplicar ``m0003`` dos
        veces más sobre una copia de su base, o de una creada de cero, no cambia ni su volcado
        SQL ni sus bytes."""
        work, root = _STATE["work"], _STATE["root"]
        before = _files(work)
        steps = list(migrations.migrate_steps(
            root, SESSION, _STATE["userdata"], clock=_STATE["clock"], pid_alive=_STATE["pids"]))
        result = steps[-1].result
        self.assertEqual((result.applied, result.backup), ((), None))
        self.assertEqual((result.from_version, result.to_version), (3, 3))
        self.assertEqual(_files(work), before)
        with project_tmp("gb-m3a-") as tmp:
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
                                m0003.apply(conn)
                        self.assertEqual(_dump(database), dump)
                    self.assertEqual(_sha256(database), digest)

    def test_a_reader_of_schema_2_opens_it_read_only(self) -> None:
        """RF-009-02, RF-002-22 (spec 009 §11; plan §5.2.3, D-24): con ``SCHEMA_VERSION = 2``
        simulado (un Geoblender de la 008), el proyecto migrado (``min_reader_schema`` 1) abre
        en solo lectura con el aviso de «versión más moderna» (esquema 3), entero y no solo la
        cabecera: lee sus tablas sin echar nada en falta; y abrir y cerrar no cambian ningún
        fichero."""
        work, root = _STATE["work"], _STATE["root"]
        before = _files(work)
        with mock.patch.object(open_mod, "SCHEMA_VERSION", 2):
            inspection = open_mod.inspect_project(
                root, SESSION, _STATE["userdata"], clock=_STATE["clock"],
                pid_alive=_STATE["pids"])
            self.assertIs(inspection.schema, open_mod.SchemaRelation.NEWER)
            result = open_mod.open_project(
                root, SESSION, _STATE["userdata"], clock=_STATE["clock"],
                pid_alive=_STATE["pids"])
        project = result.project
        try:
            self.assertEqual(project.mode, model.OpenMode.READ_ONLY)
            self.assertEqual(project.read_only_reason, model.ReadOnlyCode.SCHEMA_NEWER)
            self.assertFalse(project.header_only)
            for text in ("más moderna", "esquema 3", "0.4.0"):
                self.assertIn(text, result.status.message)
            with project.read() as conn:
                self.assertEqual(schema.read_project(conn).schema_version, 3)
                self.assertEqual(schema.missing_objects(conn, 2), [])
                live = conn.execute(
                    "SELECT count(*) FROM gb_dataset WHERE status = 'current'").fetchone()[0]
        finally:
            project.close()
        self.assertEqual(live, 29)
        self.assertEqual(_files(work), before)


# --- Las reglas del esquema 3 sobre una copia de la base migrada -------------------------------

Case = tuple[str, str, Sequence[Any], str]
V01, V02, V03, V04 = (_uid(0x901), _uid(0x902), _uid(0x903), _uid(0x904))
R01, R02A, R02B, R03 = (_uid(0x911), _uid(0x921), _uid(0x922), _uid(0x931))
DECISION = _uid(0x951)


def _insert_sql(table: str, row: dict[str, Any], verb: str = "INSERT") -> tuple[str, tuple]:
    names = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    return f"{verb} INTO {table} ({names}) VALUES ({marks})", tuple(row.values())


def version_row(uid: str, number: int, status: str = "BORRADOR", **changes: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "uid": uid, "code": f"V{number:02d}", "feature": f"rasgo{number}",
        "title": f"Versión {number}", "status": status, "parent_uid": None,
        "parent_revision_uid": None, "request": None, "reason_created": "Prueba",
        "reason_closed": None if status in ("BORRADOR", "VIGENTE") else "Cerrada en la prueba",
        "created_at": NOW, "created_by": USER, "status_changed_at": NOW,
        "status_changed_by": USER, "modified_at": NOW,
    }
    unknown = set(changes) - set(row)
    if unknown:
        raise KeyError(unknown)
    return {**row, **changes}


def revision_row(uid: str, version_uid: str, number: int = 1, **changes: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "uid": uid, "version_uid": version_uid, "number": number, "state": "open",
        "reason": "Revisión inicial", "created_at": NOW, "created_by": USER,
    }
    return {**row, **changes}


FROZEN = {"state": "frozen", "closed_at": NOW, "closed_by": USER,
          "snapshot_dir": "snapshots/V02.r1", "snapshot_sha256": "a" * 64, "snapshot_bytes": 0,
          "geoblender_version": "0.4.0"}
CLOSED = {"state": "closed", "closed_at": NOW, "closed_by": USER}


def _changed(column: str) -> str:
    """Una expresión SQL que da otro valor que el de ``column``."""
    if column in ("fid", "number", "snapshot_bytes"):
        return f"coalesce({column}, 0) + 100"
    return f"coalesce({column}, '') || '-otro'"


class VersionRulesTest(unittest.TestCase):
    """Una copia de la base migrada, abierta para escribir como Geoblender, con cuatro
    versiones: V01 BORRADOR (r1 abierta), V02 VIGENTE (r1 congelada y r2 abierta), V03
    DESCARTADO (r1 cerrada) y V04 SUPERADO (sin revisiones)."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="gb-m3r-", ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / DATABASE
        shutil.copyfile(_STATE["database"], self.path)
        self.db = gpkg.GpkgConnection.open_write(self.path)
        self.addCleanup(self.db.close)
        self.accept(
            _insert_sql("gb_version", version_row(V01, 1)),
            _insert_sql("gb_revision", revision_row(R01, V01)),
            _insert_sql("gb_version", version_row(V02, 2, "VIGENTE")),
            _insert_sql("gb_revision", revision_row(R02A, V02)),
            (self.update_sql("gb_revision", FROZEN, R02A)),
            _insert_sql("gb_revision", revision_row(R02B, V02, 2, reason="Siguiente")),
            _insert_sql("gb_version", version_row(V03, 3)),
            _insert_sql("gb_revision", revision_row(R03, V03)),
            (self.update_sql("gb_revision", CLOSED, R03)),
            ("UPDATE gb_version SET status = 'DESCARTADO', reason_closed = 'No sirve' "
             "WHERE uid = ?", (V03,)),
            _insert_sql("gb_version", version_row(V04, 4, "SUPERADO")),
        )

    # Ayudas -------------------------------------------------------------------------------

    @staticmethod
    def update_sql(table: str, values: dict[str, Any], uid: str) -> tuple[str, tuple]:
        assignments = ", ".join(f"{column} = ?" for column in values)
        return f"UPDATE {table} SET {assignments} WHERE uid = ?", (*values.values(), uid)

    def dump(self) -> list[str]:
        return list(self.db.connection.iterdump())

    def scalar(self, sql: str, args: Sequence[Any] = ()) -> Any:
        return self.db.connection.execute(sql, args).fetchone()[0]

    def accept(self, *statements: tuple[str, Sequence[Any]]) -> None:
        """Ejecuta las sentencias en una transacción que se confirma."""
        with self.db.transaction() as conn:
            for sql, args in statements:
                conn.execute(sql, args)

    def assertRejected(self, cases: Iterable[Case]) -> None:
        """Cada caso (etiqueta, SQL, argumentos, texto esperado dentro del error) falla con
        ``IntegrityError``, en una sola transacción, y nada cambia."""
        before = self.dump()
        with self.db.transaction() as conn:
            for label, sql, args, expected in cases:
                with self.subTest(label):
                    with self.assertRaises(sqlite3.IntegrityError) as caught:
                        conn.execute(sql, args)
                    self.assertIn(expected, str(caught.exception))
        self.assertEqual(self.dump(), before)

    def existing(self, table: str, where: str, **changes: Any) -> dict[str, Any]:
        """Una fila de ``table`` (la primera de ``where``), sin ``fid`` y con ``changes``."""
        cursor = self.db.connection.execute(f"SELECT * FROM {table} WHERE {where} LIMIT 1")
        names = [column[0] for column in cursor.description]
        row = dict(zip(names, cursor.fetchone(), strict=True))
        row.pop("fid")
        unknown = set(changes) - set(row)
        if unknown:
            raise KeyError(unknown)
        return {**row, **changes}

    def dataset(self, number: int, name: str, version_uid: str, **changes: Any) -> dict[str, Any]:
        return self.existing(
            "gb_dataset", "name = 'demo_benches'", uid=_uid(0xa00 + number), name=name,
            locator=f"des_{number}", selector="", version_uid=version_uid, input_uid=None,
            immutable=0, superseded_by=None, **changes)

    def operation(self, number: int, scope: str, revision_uid: str) -> dict[str, Any]:
        return self.existing(
            "gb_operation", "op_type = 'demo.area'", uid=_uid(0xb00 + number), scope=scope,
            revision_uid=revision_uid, supersedes_uid=None, superseded_by=None)

    def parameter(self, number: int, version_uid: str) -> dict[str, Any]:
        return self.existing(
            "gb_parameter", "scope = 'project'", uid=_uid(0xc00 + number), scope="version",
            scope_uid=version_uid)

    @staticmethod
    def message(table: str, text: str) -> str:
        return f"{table}: {text}"

    # Pruebas ------------------------------------------------------------------------------

    def test_nothing_is_deleted_or_replaced(self) -> None:
        """RF-009-12: no se borra ninguna versión, revisión, elemento congelado, decisión ni
        enlace, tampoco con ``REPLACE`` (que borraría la fila que choca sin disparar los
        ``BEFORE DELETE``): ni una fila con la identidad de otra, ni otra VIGENTE (que
        sustituiría a la que hay), ni otra revisión abierta de la misma versión."""
        item = {"revision_uid": R02A, "item_kind": "dataset", "item_uid": _uid(0xa99),
                "part": "produced", "content_sha256": "b" * 64, "copied": 1,
                "snapshot_path": "snapshots/V02.r1/rasters/x.tif", "file_sha256": "c" * 64,
                "file_size": 10}
        decision = {"uid": DECISION, "decided_by": "Propiedad", "decided_at": "2026-10-17",
                    "what": "Bancos de 10 m", "source_text": "correo del 17/10/2026",
                    "recorded_by": USER, "recorded_at": NOW}
        link = {"decision_uid": DECISION, "item_kind": "version", "item_uid": V01}
        # V01 sin revisión abierta: así sustituir su r1 solo choca con su identidad.
        self.accept(_insert_sql("gb_revision_item", item), _insert_sql("gb_decision", decision),
                    _insert_sql("gb_decision_link", link),
                    self.update_sql("gb_revision", CLOSED, R01))
        no_delete, append_only = versions_schema.MSG_NO_DELETE, versions_schema.MSG_APPEND_ONLY
        cases: list[Case] = [
            (f"borrar {table}", f"DELETE FROM {table}", (),
             self.message(table, no_delete if table in ("gb_version", "gb_revision")
                          else append_only))
            for table in VERSION_TABLES
        ]
        cases += [
            ("reemplazar una versión",
             *_insert_sql("gb_version", version_row(V01, 5), "INSERT OR REPLACE"),
             self.message("gb_version", versions_schema.MSG_NO_REPLACE)),
            ("reemplazar un código",
             *_insert_sql("gb_version", version_row(_uid(0x905), 1), "INSERT OR REPLACE"),
             self.message("gb_version", versions_schema.MSG_NO_REPLACE)),
            ("reemplazar una revisión",
             *_insert_sql("gb_revision", revision_row(R01, V01, 7), "INSERT OR REPLACE"),
             self.message("gb_revision", versions_schema.MSG_NO_REPLACE)),
            ("reemplazar un número de revisión",
             *_insert_sql("gb_revision", revision_row(_uid(0x919), V01, 1), "INSERT OR REPLACE"),
             self.message("gb_revision", versions_schema.MSG_NO_REPLACE)),
            ("otra revisión abierta",
             *_insert_sql("gb_revision", revision_row(_uid(0x923), V02, 3), "INSERT OR REPLACE"),
             self.message("gb_revision", versions_schema.MSG_REVISION_OPEN)),
            ("otra VIGENTE con REPLACE",
             "UPDATE OR REPLACE gb_version SET status = 'VIGENTE' WHERE uid = ?", (V01,),
             self.message("gb_version", versions_schema.MSG_CURRENT)),
            ("otra VIGENTE nueva",
             *_insert_sql("gb_version", version_row(_uid(0x905), 5, "VIGENTE"),
                          "INSERT OR REPLACE"),
             self.message("gb_version", versions_schema.MSG_CURRENT)),
            ("reemplazar un elemento",
             *_insert_sql("gb_revision_item", item, "INSERT OR REPLACE"),
             self.message("gb_revision_item", append_only)),
            ("reemplazar una decisión",
             *_insert_sql("gb_decision", decision, "INSERT OR REPLACE"),
             self.message("gb_decision", append_only)),
            ("reemplazar un enlace",
             *_insert_sql("gb_decision_link", link, "INSERT OR REPLACE"),
             self.message("gb_decision_link", append_only)),
        ]
        self.assertRejected(cases)
        self.assertEqual(self.scalar("SELECT count(*) FROM gb_version"), 4)
        self.assertEqual(self.scalar("SELECT count(*) FROM gb_revision"), 4)

    def test_fixed_columns_and_append_only_rows(self) -> None:
        """RF-009-04, RF-009-02 (plan §5.2.1 y §5.2.2): no cambian la identidad de una versión
        (código, rasgo, de cuál parte, encargo, motivo y alta) ni la de una revisión (versión,
        número, motivo y alta), ni la versión de un dato ni la revisión de una operación; los
        elementos congelados, las decisiones y sus enlaces no se modifican; escribir el mismo
        valor sí pasa, y el título de un dato y el de una versión editable cambian."""
        self.accept(
            ("INSERT INTO gb_revision_item (revision_uid, item_kind, item_uid, part) "
             "VALUES (?, 'operation', ?, 'immutable')", (R02A, _uid(0xb99))),
            ("INSERT INTO gb_decision (uid, decided_by, decided_at, what, source_text, "
             "recorded_by, recorded_at) VALUES (?, 'Propiedad', '2026-10-17', 'Bancos', "
             "'correo', ?, ?)", (DECISION, USER, NOW)),
            ("INSERT INTO gb_decision_link (decision_uid, item_kind, item_uid) "
             "VALUES (?, 'parameter', 'demo.bench_height')", (DECISION,)),
        )
        cases: list[Case] = []
        for table, uid in (("gb_version", V01), ("gb_revision", R01)):
            message = self.message(table, versions_schema.MSG_FIXED[table])
            cases += [
                (f"{table}.{column}", f"UPDATE {table} SET {column} = {_changed(column)} "
                 "WHERE uid = ?", (uid,), message)
                for column in versions_schema.FIXED_COLUMNS[table]
            ]
        for table in versions_schema.APPEND_ONLY_TABLES:
            cases.append((f"modificar {table}", f"UPDATE {table} SET fid = fid", (),
                          self.message(table, versions_schema.MSG_APPEND_ONLY)))
        dataset_uid = self.scalar("SELECT uid FROM gb_dataset WHERE name = 'demo_benches'")
        cases += [
            ("gb_dataset.version_uid", "UPDATE gb_dataset SET version_uid = ? WHERE uid = ?",
             (V01, dataset_uid),
             self.message("gb_dataset", provenance_schema.MSG_FIXED["gb_dataset"])),
            ("gb_operation.revision_uid",
             "UPDATE gb_operation SET revision_uid = ? WHERE op_type = 'demo.area'", (R01,),
             self.message("gb_operation", provenance_schema.MSG_FIXED["gb_operation"])),
        ]
        self.assertGreaterEqual(len(cases), 20)
        self.assertRejected(cases)
        same_version = ", ".join(f"{column} = {column}"
                                 for column in versions_schema.FIXED_COLUMNS["gb_version"])
        self.accept(
            (f"UPDATE gb_version SET {same_version}", ()),
            ("UPDATE gb_dataset SET version_uid = version_uid, title = 'Bancos' WHERE uid = ?",
             (dataset_uid,)),
            ("UPDATE gb_version SET title = 'Otra' WHERE uid = ?", (V01,)),
        )
        self.assertEqual(self.scalar("SELECT title FROM gb_dataset WHERE uid = ?",
                                     (dataset_uid,)), "Bancos")

    def test_status_transitions(self) -> None:
        """RF-009-03, RF-009-04 (D-3): solo BORRADOR → VIGENTE, BORRADOR → DESCARTADO, VIGENTE →
        SUPERADO y VIGENTE → DESCARTADO, con una sola VIGENTE y motivo al cerrarse; de una
        versión SUPERADO o DESCARTADO no cambia nada (ni el estado, ni el título, ni el
        motivo)."""
        status = self.message("gb_version", versions_schema.MSG_STATUS)
        closed = self.message("gb_version", versions_schema.MSG_CLOSED)
        set_status = "UPDATE gb_version SET status = ? WHERE uid = ?"
        self.assertRejected([
            ("BORRADOR → SUPERADO", set_status, ("SUPERADO", V01), status),
            ("VIGENTE → BORRADOR", set_status, ("BORRADOR", V02), status),
            ("dos VIGENTE", set_status, ("VIGENTE", V01),
             self.message("gb_version", versions_schema.MSG_CURRENT)),
            ("DESCARTADO → BORRADOR", set_status, ("BORRADOR", V03), status),
            ("SUPERADO → BORRADOR", set_status, ("BORRADOR", V04), status),
            ("título de una DESCARTADO", "UPDATE gb_version SET title = 'x' WHERE uid = ?",
             (V03,), closed),
            ("motivo de una SUPERADO",
             "UPDATE gb_version SET reason_closed = 'otro' WHERE uid = ?", (V04,), closed),
            ("SUPERADO sin motivo", "UPDATE gb_version SET status = 'SUPERADO', "
             "reason_closed = NULL WHERE uid = ?", (V02,), "CHECK constraint failed"),
            ("estado desconocido", *_insert_sql(
                "gb_version", version_row(_uid(0x906), 6, "VIGENTE ")), "CHECK constraint failed"),
        ])
        self.accept(
            ("UPDATE gb_version SET status = 'SUPERADO', reason_closed = 'Superada por V01' "
             "WHERE uid = ?", (V02,)),
            (set_status, ("VIGENTE", V01)),
            ("UPDATE gb_version SET status = 'DESCARTADO', reason_closed = 'Mal' WHERE uid = ?",
             (V01,)),
        )
        statuses = dict(self.db.connection.execute("SELECT code, status FROM gb_version"))
        self.assertEqual(statuses, {"V01": "DESCARTADO", "V02": "SUPERADO",
                                    "V03": "DESCARTADO", "V04": "SUPERADO"})

    def test_revision_states(self) -> None:
        """RF-009-04, RF-009-06 (plan §5.2.1): una revisión nueva está abierta y es de una
        versión BORRADOR o VIGENTE, con una sola abierta por versión; una abierta se congela
        (con su instantánea) o se cierra una vez; de una congelada solo cambia la marca de
        alterada (D-31), y una cerrada no cambia."""
        new = self.message("gb_revision", versions_schema.MSG_REVISION_NEW)
        state = self.message("gb_revision", versions_schema.MSG_REVISION_STATE)
        self.assertRejected([
            ("otra abierta", *_insert_sql("gb_revision", revision_row(_uid(0x912), V01, 2)),
             self.message("gb_revision", versions_schema.MSG_REVISION_OPEN)),
            ("en una SUPERADO", *_insert_sql("gb_revision", revision_row(_uid(0x941), V04)), new),
            ("en una DESCARTADO",
             *_insert_sql("gb_revision", revision_row(_uid(0x932), V03, 2)), new),
            ("nueva ya congelada", *_insert_sql(
                "gb_revision", revision_row(_uid(0x913), V01, 2, **FROZEN)), new),
            ("de una versión que no existe",
             *_insert_sql("gb_revision", revision_row(_uid(0x9ff), _uid(0x9fe))), new),
            ("congelada → abierta", "UPDATE gb_revision SET state = 'open', closed_at = NULL, "
             "closed_by = NULL, snapshot_dir = NULL, snapshot_sha256 = NULL WHERE uid = ?",
             (R02A,), state),
            ("otra instantánea", "UPDATE gb_revision SET snapshot_dir = 'snapshots/x' "
             "WHERE uid = ?", (R02A,), state),
            ("otro motivo", "UPDATE gb_revision SET reason = 'otro' WHERE uid = ?", (R02A,),
             self.message("gb_revision", versions_schema.MSG_FIXED["gb_revision"])),
            ("cerrada → congelada", *self.update_sql("gb_revision", FROZEN, R03), state),
            ("cerrada por otro", "UPDATE gb_revision SET closed_by = 'otro' WHERE uid = ?",
             (R03,), state),
            ("congelar sin instantánea", "UPDATE gb_revision SET state = 'frozen', "
             "closed_at = ?, closed_by = ? WHERE uid = ?", (NOW, USER, R01),
             "CHECK constraint failed"),
            ("alterada sin congelar", "UPDATE gb_revision SET altered_at = ? WHERE uid = ?",
             (NOW, R01), "CHECK constraint failed"),
        ])
        self.accept(
            ("UPDATE gb_revision SET altered_at = ?, altered_detail = '[\"x\"]' WHERE uid = ?",
             (NOW, R02A)),
            ("UPDATE gb_revision SET altered_at = NULL, altered_detail = NULL WHERE uid = ?",
             (R02A,)),
            self.update_sql("gb_revision", CLOSED, R01),
            _insert_sql("gb_revision", revision_row(_uid(0x912), V01, 2)),
        )
        self.assertRejected([
            ("cerrada otra vez", "UPDATE gb_revision SET state = 'open', closed_at = NULL, "
             "closed_by = NULL WHERE uid = ?", (R01,), state),
        ])
        opened = self.db.connection.execute(
            "SELECT version_uid, number FROM gb_revision WHERE state = 'open' ORDER BY version_uid"
        ).fetchall()
        self.assertEqual(opened, [(V01, 2), (V02, 2)])

    def test_dataset_names_per_version(self) -> None:
        """RF-009-02 (plan §5.2.2; spec §8): dos datos vivos con el mismo nombre en dos
        versiones, y uno de versión con el nombre de uno del proyecto, se admiten; dos vivos
        con el mismo nombre en la misma versión (o en el proyecto) no, tampoco al volver a
        estar vivo uno sustituido ni con ``REPLACE``."""
        live = self.message("gb_dataset", provenance_schema.MSG_LIVE_DATASET)
        self.accept(
            _insert_sql("gb_dataset", self.dataset(1, "des_final", V01)),
            _insert_sql("gb_dataset", self.dataset(2, "des_final", V02)),
            _insert_sql("gb_dataset", self.dataset(3, "demo_benches", V01)),
            _insert_sql("gb_dataset", self.dataset(4, "des_final", V01, status="superseded")),
        )
        self.assertRejected([
            ("mismo nombre en V01", *_insert_sql("gb_dataset", self.dataset(5, "des_final", V01)),
             live),
            ("mismo nombre en el proyecto",
             *_insert_sql("gb_dataset", self.dataset(6, "demo_benches", "")), live),
            ("con REPLACE", *_insert_sql("gb_dataset", self.dataset(7, "des_final", V02),
                                         "INSERT OR REPLACE"), live),
            ("vuelve a estar vivo", "UPDATE gb_dataset SET status = 'current' WHERE uid = ?",
             (_uid(0xa04),), live),
        ])
        found = self.db.connection.execute(
            "SELECT version_uid, count(*) FROM gb_dataset WHERE name = 'des_final' "
            "AND status = 'current' GROUP BY version_uid ORDER BY version_uid").fetchall()
        self.assertEqual(found, [(V01, 1), (V02, 1)])
        # El índice es parcial (``version_uid <> ''``): la consulta repite esa condición.
        plan = " ".join(str(row) for row in self.db.connection.execute(
            "EXPLAIN QUERY PLAN SELECT uid FROM gb_dataset WHERE version_uid = ? "
            "AND version_uid <> ''", (V01,)))
        self.assertIn("gb_dataset_version", plan)

    def test_operation_scope(self) -> None:
        """RF-009-04, RF-009-05 (plan §5.2.2, ``gb_operation_scope``): una operación de versión
        se registra en la revisión abierta de una versión BORRADOR o VIGENTE, y una de proyecto,
        sin revisión: se rechazan una de versión sin revisión, en una congelada, en una cerrada,
        en una que no existe o en la abierta de una versión ya SUPERADO, y una de proyecto con
        revisión."""
        scope = self.message("gb_operation", versions_schema.MSG_OPERATION_SCOPE)
        self.accept(
            _insert_sql("gb_operation", self.operation(1, "version", R01)),
            _insert_sql("gb_operation", self.operation(2, "version", R02B)),
            _insert_sql("gb_operation", self.operation(3, "project", "")),
            ("UPDATE gb_version SET status = 'SUPERADO', reason_closed = 'Prueba' WHERE uid = ?",
             (V02,)),
        )
        self.assertRejected([
            ("de versión sin revisión",
             *_insert_sql("gb_operation", self.operation(4, "version", "")), scope),
            ("de proyecto con revisión",
             *_insert_sql("gb_operation", self.operation(5, "project", R01)), scope),
            ("en una congelada",
             *_insert_sql("gb_operation", self.operation(6, "version", R02A)), scope),
            ("en una cerrada",
             *_insert_sql("gb_operation", self.operation(7, "version", R03)), scope),
            ("en una que no existe",
             *_insert_sql("gb_operation", self.operation(8, "version", _uid(0x9ff))), scope),
            ("en la abierta de una SUPERADO",
             *_insert_sql("gb_operation", self.operation(9, "version", R02B)), scope),
        ])
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM gb_operation WHERE revision_uid <> ''"), 2)
        plan = " ".join(str(row) for row in self.db.connection.execute(
            "EXPLAIN QUERY PLAN SELECT uid FROM gb_operation WHERE revision_uid = ? "
            "AND revision_uid <> ''", (R01,)))
        self.assertIn("gb_operation_revision", plan)

    def test_version_parameters(self) -> None:
        """RF-009-04, RF-009-29 (plan §5.2.2, ``gb_parameter_version``): un parámetro de versión
        solo se crea o se cambia en una versión BORRADOR o VIGENTE; los del proyecto no
        cambian de regla, y escribir el mismo valor en el de una versión cerrada sí pasa."""
        rejected = self.message("gb_parameter", versions_schema.MSG_PARAMETER_VERSION)
        self.accept(
            _insert_sql("gb_parameter", self.parameter(1, V01)),
            _insert_sql("gb_parameter", self.parameter(2, V02)),
            ("UPDATE gb_parameter SET reason = 'Otro motivo' WHERE uid = ?", (_uid(0xc01),)),
            ("UPDATE gb_version SET status = 'DESCARTADO', reason_closed = 'Mal' WHERE uid = ?",
             (V01,)),
        )
        self.assertRejected([
            ("en una SUPERADO", *_insert_sql("gb_parameter", self.parameter(3, V04)), rejected),
            ("en una que no existe",
             *_insert_sql("gb_parameter", self.parameter(4, _uid(0x9ff))), rejected),
            ("cambiar el de una DESCARTADO",
             "UPDATE gb_parameter SET reason = 'Otro' WHERE uid = ?", (_uid(0xc01),), rejected),
        ])
        self.accept(
            ("UPDATE gb_parameter SET reason = reason, value = value WHERE uid = ?",
             (_uid(0xc01),)),
            ("UPDATE gb_parameter SET reason = 'Cambio' WHERE scope = 'project'", ()),
            ("UPDATE gb_parameter SET reason = 'Cambio' WHERE uid = ?", (_uid(0xc02),)),
        )

    def test_foreign_connection(self) -> None:
        """RF-009-12, RF-009-04 (RF-002-15): desde una conexión sin ``gb_writer()`` (QGIS,
        GDAL), insertar (una fila válida), cambiar, borrar y sustituir fallan en las cinco
        tablas nuevas, y también registrar una operación o un parámetro de versión, o cambiar
        la versión de un dato; todo se lee y el volcado SQL no cambia."""
        self.accept(  # una fila en cada tabla de solo inserción, para cambiarla y borrarla
            ("INSERT INTO gb_revision_item (revision_uid, item_kind, item_uid, part) "
             "VALUES (?, 'operation', ?, 'immutable')", (R02A, _uid(0xb99))),
            ("INSERT INTO gb_decision (uid, decided_by, decided_at, what, source_text, "
             "recorded_by, recorded_at) VALUES (?, 'Propiedad', '2026-10-17', 'Bancos', "
             "'correo', ?, ?)", (_uid(0x952), USER, NOW)),
            ("INSERT INTO gb_decision_link (decision_uid, item_kind, item_uid) "
             "VALUES (?, 'version', ?)", (_uid(0x952), V02)),
        )
        foreign = sqlite3.connect(self.path, isolation_level=None)
        try:
            before = list(foreign.iterdump())
            rows = {
                "gb_version": version_row(_uid(0x907), 7),
                "gb_revision": revision_row(_uid(0x914), V01, 2),
                "gb_revision_item": {"revision_uid": R02A, "item_kind": "input",
                                     "item_uid": _uid(0xe01), "part": "immutable"},
                "gb_decision": {"uid": DECISION, "decided_by": "Propiedad",
                                "decided_at": "2026-10-17", "what": "Bancos",
                                "source_text": "correo", "recorded_by": USER,
                                "recorded_at": NOW},
                "gb_decision_link": {"decision_uid": DECISION, "item_kind": "version",
                                     "item_uid": V01},
            }
            writes: list[tuple[str, str, tuple]] = []
            for table, row in rows.items():
                writes += [
                    (table, *_insert_sql(table, row)),
                    (table, f"UPDATE {table} SET fid = fid", ()),
                    (table, f"DELETE FROM {table}", ()),
                    (table, f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}", ()),
                ]
            writes += [
                ("gb_operation", "INSERT INTO gb_operation (uid, op_type, op_version, module, "
                 "scope, repeatable, settings, settings_sha256, status, geoblender_version, "
                 "executor, user_host, host, session_uid, started_at, finished_at, "
                 "revision_uid) VALUES (?, 'demo.area', '1.0', 'demo', 'version', 0, '{}', "
                 "'x', 'done', '0.4.0', 'blender', ?, 'PC', 's', ?, ?, ?)",
                 (_uid(0xb10), USER, NOW, NOW, R01)),
                ("gb_parameter", "UPDATE gb_parameter SET scope = 'version', scope_uid = ?",
                 (V04,)),
                ("gb_dataset", "UPDATE gb_dataset SET version_uid = ?", (V01,)),
            ]
            for table, sql, args in writes:
                with self.subTest(tabla=table, orden=" ".join(sql.split()[:3])):
                    with self.assertRaises(sqlite3.Error):
                        foreign.execute(sql, args)
            for table in VERSION_TABLES:
                with self.subTest(tabla=table, orden="SELECT"):
                    foreign.execute(f"SELECT count(*) FROM {table}").fetchone()
            after = list(foreign.iterdump())
        finally:
            foreign.close()
        self.assertEqual(after, before)
        self.assertEqual(len(writes), 23)


if __name__ == "__main__":
    unittest.main()
