# SPDX-License-Identifier: GPL-3.0-or-later
"""Versiones del esquema del proyecto (spec 002, T20 y T21; RF-002-13, RF-002-20,
RF-002-21, RF-002-22; ADR-0006 §7; formato-proyecto §7; plan 002 §5.4, «Migración»).

Migrar (T20): con el esquema 1 no hay migraciones (registro vacío), así que se prueban con
migraciones de prueba inyectadas (1 → 2 → 3) y un esquema soportado 3. Antes de migrar se
hace una copia completa junto al original (``<Nombre>.gbproj.respaldo-esquema-<N>``, con
las mismas huellas); todas las migraciones y sus filas de ``gb_schema_migration`` van en
una transacción, y después se regenera la cabecera desde la base de datos. Si una falla,
el proyecto queda como estaba (volcado SQL y cabecera idénticos) y se conserva la copia
previa. Una cadena con hueco se rechaza antes de tocar nada, y quien no acepta migrar
abre en solo lectura «sin migrar».

Las bases que escribe «otro programa» en estas pruebas son conexiones de ``sqlite3`` sin
``gb_writer()``, como QGIS.
"""

import hashlib
import json
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from tests.support.core_fixtures import FakeClock, FakePids, make_session, make_settings, project_tmp
from tests.support.package import import_geoblender

create = import_geoblender("core.project.create")
open_mod = import_geoblender("core.project.open")
model = import_geoblender("core.project.model")
schema = import_geoblender("core.project.schema")
manifest_mod = import_geoblender("core.project.manifest")
events_mod = import_geoblender("core.project.events")
lock = import_geoblender("core.project.lock")
copytree = import_geoblender("core.project.copytree")
migrations = import_geoblender("core.project.migrations")
errors = import_geoblender("core.errors")
gpkg = import_geoblender("core.gpkg")
userdata_mod = import_geoblender("core.userdata")

SESSION_A = make_session()
SESSION_A2 = make_session(session_uid="00000000-0000-4000-8000-0000000000a2", pid=5151)
SESSION_B = make_session(
    session_uid="00000000-0000-4000-8000-000000000002", host="PC-PRUEBA-B", user="otra",
    pid=777, geoblender_version="0.3.0",
)
EXCLUDE = ("cache", ".lock")
BACKUP_NAME = "Cantera Prueba.gbproj.respaldo-esquema-1"
WAL_PRAGMA = "PRAGMA journal_mode=" + "WAL"


def _m1_2(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS gb_test_m2 (fid INTEGER PRIMARY KEY AUTOINCREMENT, "
        "nota TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO gb_test_m2 (nota) VALUES ('creada en la migración 1 → 2')")


def _m2_3(conn: sqlite3.Connection) -> None:
    columns = [row[1] for row in conn.execute("PRAGMA table_info(gb_test_m2)")]
    if "extra" not in columns:
        conn.execute("ALTER TABLE gb_test_m2 ADD COLUMN extra TEXT")
    conn.execute("UPDATE gb_test_m2 SET extra = 'añadida en la migración 2 → 3'")


def _m2_3_fails(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE gb_test_m2 ADD COLUMN extra TEXT")
    conn.execute("INSERT INTO tabla_que_no_existe VALUES (1)")


def _m3_4(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS gb_test_m4 (fid INTEGER PRIMARY KEY)")


M1_2 = migrations.Migration(1, 2, "tabla de prueba gb_test_m2", _m1_2)
M2_3 = migrations.Migration(2, 3, "columna de prueba extra", _m2_3)
M2_3_FAILS = migrations.Migration(2, 3, "columna de prueba que falla", _m2_3_fails)
M3_4 = migrations.Migration(3, 4, "tabla de prueba gb_test_m4", _m3_4)


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


class Env:
    """Un proyecto de esquema 1 creado y cerrado por la sesión A."""

    def __init__(self, tmp: Path) -> None:
        self.parent = tmp / "proyectos"
        self.parent.mkdir()
        self.userdata = userdata_mod.UserData(tmp / "datos_usuario")
        self.clock = FakeClock()
        self.pids = FakePids({SESSION_A.pid, SESSION_B.pid})
        self.created = create.create_project(
            self.parent, make_settings(), SESSION_A, self.userdata, clock=self.clock
        )
        self.created.project.close()
        self.root = self.created.root
        self.db = self.root / "project.gpkg"

    def migrate_steps(self, registry, target=3, session=SESSION_B, **kwargs):
        kwargs.setdefault("clock", self.clock)
        kwargs.setdefault("pid_alive", self.pids)
        return migrations.migrate_steps(
            self.root, session, self.userdata, registry, target=target, **kwargs
        )

    def migrate(self, registry, target=3, **kwargs) -> list:
        return list(self.migrate_steps(registry, target, **kwargs))

    def open(self, session=SESSION_B, **kwargs):
        kwargs.setdefault("clock", self.clock)
        kwargs.setdefault("pid_alive", self.pids)
        return open_mod.open_project(self.root, session, self.userdata, **kwargs)

    def dump(self) -> list[str]:
        conn = sqlite3.connect(self.db)
        try:
            return list(conn.iterdump())
        finally:
            conn.close()

    def read(self, sql: str) -> list[tuple]:
        with gpkg.GpkgConnection.open_read(self.db) as db:
            return db.connection.execute(sql).fetchall()

    def events(self, kind=None) -> list:
        with gpkg.GpkgConnection.open_read(self.db) as db:
            return events_mod.read_events(db.connection, kind)

    def prints(self, root: Path | None = None):
        return copytree.fingerprint(root or self.root, exclude=EXCLUDE)


class MigrationChainTest(unittest.TestCase):
    def test_empty_registry_in_schema_1(self) -> None:
        """RF-002-20: el esquema 1 no tiene migraciones (registro vacío): un proyecto de
        esquema 1 no se migra, no se copia ni cambia nada."""
        self.assertEqual(schema.SCHEMA_VERSION, 1)
        self.assertEqual(migrations.REGISTRY, ())
        self.assertEqual(migrations.plan_migrations(1, 1), ())
        with project_tmp() as tmp:
            env = Env(tmp)
            before = _snapshot(env.parent)
            steps = list(migrations.migrate_steps(
                env.root, SESSION_B, env.userdata, clock=env.clock, pid_alive=env.pids
            ))
            result = steps[-1].result
            self.assertIsInstance(result, migrations.MigrationResult)
            self.assertEqual(result.applied, ())
            self.assertIsNone(result.backup)
            self.assertEqual(_snapshot(env.parent), before)

    def test_plan_in_order_and_gaps_rejected(self) -> None:
        """RF-002-20: las migraciones se aplican en orden N → N+1 sin huecos; una cadena
        con hueco, un salto de más de una versión o dos migraciones desde la misma versión
        se rechazan, y no se migra hacia atrás."""
        self.assertEqual(migrations.plan_migrations(1, 3, (M2_3, M1_2)), (M1_2, M2_3))
        self.assertEqual(migrations.plan_migrations(2, 3, (M1_2, M2_3)), (M2_3,))
        with self.assertRaises(errors.ProjectError) as caught:
            migrations.plan_migrations(1, 4, (M1_2, M3_4))
        self.assertEqual(caught.exception.code, "core.migration_gap")
        self.assertIn("2 → 3", str(caught.exception))
        skip = migrations.Migration(1, 3, "salta una versión", _m1_2)
        for registry in ((skip,), (M1_2, M1_2, M2_3)):
            with self.assertRaises(errors.ProjectError) as caught:
                migrations.plan_migrations(1, 3, registry)
            self.assertEqual(caught.exception.code, "core.migration_invalid")
        with self.assertRaises(errors.ProjectError) as caught:
            migrations.plan_migrations(3, 1, (M1_2, M2_3))
        self.assertEqual(caught.exception.code, "core.migration_newer")


class MigrateTest(unittest.TestCase):
    def test_migrates_with_a_backup_and_registers_each_step(self) -> None:
        """RF-002-20: migrar 1 → 2 → 3 crea antes ``<Nombre>.gbproj.respaldo-esquema-1``
        junto al original con las mismas huellas (sin caché ni cerrojo), aplica las
        migraciones en orden, registra dos filas en ``gb_schema_migration`` y sus
        eventos, regenera la cabecera desde la base de datos y libera el cerrojo; después
        el proyecto abre en escritura con el esquema 3."""
        with project_tmp() as tmp:
            env = Env(tmp)
            before = env.prints()
            steps = env.migrate((M1_2, M2_3))
            result = steps[-1].result
            backup = env.parent / BACKUP_NAME
            self.assertEqual(result.backup, backup)
            self.assertEqual(result.applied, ((1, 2), (2, 3)))
            self.assertEqual((result.from_version, result.to_version), (1, 3))
            self.assertEqual(env.prints(backup), before)
            self.assertEqual(
                sorted(path.name for path in env.parent.iterdir()),
                sorted([env.root.name, BACKUP_NAME]),
            )
            rows = env.read(
                "SELECT from_version, to_version, applied_with, backup_dir, user_host "
                "FROM gb_schema_migration ORDER BY fid"
            )
            self.assertEqual(
                rows,
                [
                    (1, 2, "0.3.0", BACKUP_NAME, SESSION_B.user_host),
                    (2, 3, "0.3.0", BACKUP_NAME, SESSION_B.user_host),
                ],
            )
            self.assertEqual(
                env.read("SELECT nota, extra FROM gb_test_m2"),
                [("creada en la migración 1 → 2", "añadida en la migración 2 → 3")],
            )
            record = env.read("SELECT schema_version, min_reader_schema, last_written_with FROM gb_project")
            self.assertEqual(record, [(3, 1, "0.3.0")])
            header = manifest_mod.read_manifest(env.root)
            self.assertEqual(header.schema_version, 3)
            self.assertEqual(header.geoblender_version, "0.3.0")
            with gpkg.GpkgConnection.open_read(env.db) as db:
                db_record = schema.read_project(db.connection)
                registered = schema.read_migrations(db.connection)
            self.assertEqual(
                manifest_mod.compare(header, db_record, registered).status,
                manifest_mod.ManifestStatus.CONSISTENT,
            )
            migrated = env.events(events_mod.EventKind.MIGRATION)
            self.assertEqual(
                [(item.data["from"], item.data["to"], item.data["backup_dir"]) for item in migrated],
                [(1, 2, BACKUP_NAME), (2, 3, BACKUP_NAME)],
            )
            self.assertFalse((env.root / ".lock").exists())
            phases = [step.phase for step in steps]
            self.assertEqual(
                [phase for index, phase in enumerate(phases) if phase not in phases[:index]],
                list(migrations.PHASES),
            )
            self.assertTrue(all(step.result is None for step in steps[:-1]))
            with mock.patch.object(open_mod, "SCHEMA_VERSION", 3):
                opened = env.open()
            try:
                self.assertEqual(opened.project.mode, model.OpenMode.WRITE_LOCAL)
                self.assertEqual(opened.project.schema_version, 3)
                self.assertEqual(opened.warnings, ())
            finally:
                opened.project.close()

    def test_failure_leaves_the_project_as_before_and_keeps_the_backup(self) -> None:
        """RF-002-21: si falla la segunda migración, el volcado SQL y la cabecera quedan
        idénticos a los de antes (ninguna de las dos se aplica), se conserva la copia
        previa, el error explica qué migración falló y dónde está la copia, el fallo va
        al registro técnico y el cerrojo se libera."""
        with project_tmp() as tmp:
            env = Env(tmp)
            dump, header = env.dump(), (env.root / "manifest.json").read_bytes()
            before = env.prints()
            with self.assertLogs("geoblender.core.project", "WARNING") as logged:
                with self.assertRaises(errors.ProjectError) as caught:
                    env.migrate((M1_2, M2_3_FAILS))
            self.assertEqual(caught.exception.code, "core.migration_failed")
            message = str(caught.exception)
            self.assertIn("2 → 3", message)
            self.assertIn(BACKUP_NAME, message)
            self.assertIn("migration_failed", "\n".join(logged.output))
            self.assertEqual(env.dump(), dump)
            self.assertEqual((env.root / "manifest.json").read_bytes(), header)
            self.assertEqual(env.prints(env.parent / BACKUP_NAME), before)
            self.assertEqual(env.read("SELECT count(*) FROM gb_schema_migration"), [(0,)])
            self.assertFalse((env.root / ".lock").exists())

    def test_gap_rejected_before_touching_anything(self) -> None:
        """RF-002-20: una cadena con hueco (falta la 2 → 3) se rechaza sin copiar, sin
        tomar el cerrojo y sin cambiar nada."""
        with project_tmp() as tmp:
            env = Env(tmp)
            before = _snapshot(env.parent)
            with self.assertRaises(errors.ProjectError) as caught:
                env.migrate((M1_2, M3_4), target=4)
            self.assertEqual(caught.exception.code, "core.migration_gap")
            self.assertEqual(_snapshot(env.parent), before)

    def test_not_accepting_opens_read_only_not_migrated(self) -> None:
        """RF-002-13, RF-002-20: quien no acepta migrar abre en solo lectura «sin
        migrar», con las dos versiones y cómo migrarlo, sin copia previa y sin cambiar
        ningún fichero."""
        with project_tmp() as tmp:
            env = Env(tmp)
            before = _snapshot(env.parent)
            with mock.patch.object(open_mod, "SCHEMA_VERSION", 3):
                inspection = open_mod.inspect_project(
                    env.root, SESSION_B, env.userdata, clock=env.clock, pid_alive=env.pids
                )
                self.assertIs(inspection.schema, open_mod.SchemaRelation.OLDER)
                result = env.open()
            project = result.project
            self.assertEqual(project.mode, model.OpenMode.READ_ONLY)
            self.assertEqual(project.read_only_reason, model.ReadOnlyCode.NOT_MIGRATED)
            self.assertIn("esquema 1", result.status.message)
            self.assertIn("3", result.status.message)
            self.assertIn("migrar", result.status.message)
            with project.read() as conn:
                self.assertEqual(schema.read_project(conn).schema_version, 1)
            project.close()
            self.assertEqual(_snapshot(env.parent), before)

    def test_backup_name_does_not_replace_an_existing_one(self) -> None:
        """RF-002-20: si ya hay una copia previa del esquema 1, la nueva lleva el sufijo
        «-2» y la anterior no se toca."""
        with project_tmp() as tmp:
            env = Env(tmp)
            old = env.parent / BACKUP_NAME
            old.mkdir()
            (old / "nota.txt").write_bytes(b"copia de otro dia")
            result = env.migrate((M1_2, M2_3))[-1].result
            self.assertEqual(result.backup.name, BACKUP_NAME + "-2")
            self.assertEqual(sorted(path.name for path in old.iterdir()), ["nota.txt"])
            self.assertEqual(
                env.read("SELECT DISTINCT backup_dir FROM gb_schema_migration"),
                [(BACKUP_NAME + "-2",)],
            )

    def test_cancel_before_migrating_changes_nothing(self) -> None:
        """RF-002-20, RNF-002-06: cancelar durante la copia previa o justo antes de migrar
        no deja copia previa (ni parcial ni completa), libera el cerrojo y no cambia el
        proyecto."""
        for phase, after in (("copia previa", 2), ("migración", 1)):
            with self.subTest(phase=phase), project_tmp() as tmp:
                env = Env(tmp)
                before = _snapshot(env.parent)
                steps = env.migrate_steps((M1_2, M2_3))
                seen = 0
                for step in steps:
                    if step.phase == phase:
                        seen += 1
                        if seen == after:
                            break
                self.assertTrue((env.root / ".lock").exists())
                steps.close()
                self.assertEqual(_snapshot(env.parent), before)

    def test_other_program_writing_during_the_backup(self) -> None:
        """RF-002-20, RF-002-21: si otro programa (QGIS) escribe en la base mientras se
        hace la copia previa, la copia ya no es la del proyecto antes de migrar: no se
        migra, la copia se descarta, lo escrito por ese programa se conserva y el error
        dice qué hacer."""
        real_copy = migrations.copy_steps

        def copy_with_foreign_write(*args, **kwargs):
            """La copia real; justo después de copiar ``project.gpkg``, otro programa
            escribe en el original."""
            written = False
            for step in real_copy(*args, **kwargs):
                yield step
                if not written and step.phase == "copia" and "project.gpkg" in step.message:
                    foreign = sqlite3.connect(env.db, isolation_level=None)
                    try:
                        foreign.execute("CREATE TABLE capa_qgis (a TEXT)")
                        foreign.execute("INSERT INTO capa_qgis VALUES ('editada')")
                    finally:
                        foreign.close()
                    written = True
            self.assertTrue(written)

        with project_tmp() as tmp:
            env = Env(tmp)
            header = (env.root / "manifest.json").read_bytes()
            with mock.patch.object(migrations, "copy_steps", copy_with_foreign_write):
                with self.assertRaises(errors.ProjectError) as caught:
                    env.migrate((M1_2, M2_3))
            self.assertEqual(caught.exception.code, "core.migration_source_changed")
            self.assertIn("vuelva a intentarlo", str(caught.exception))
            self.assertEqual(env.read("SELECT a FROM capa_qgis"), [("editada",)])
            self.assertEqual(env.read("SELECT schema_version FROM gb_project"), [(1,)])
            self.assertEqual(env.read("SELECT count(*) FROM gb_schema_migration"), [(0,)])
            self.assertEqual((env.root / "manifest.json").read_bytes(), header)
            self.assertEqual(sorted(path.name for path in env.parent.iterdir()), [env.root.name])
            self.assertFalse((env.root / ".lock").exists())

    def test_header_not_written_is_regenerated_on_open(self) -> None:
        """RF-002-05, RF-002-20: si tras migrar no se puede escribir la cabecera, la base
        ya migrada manda: se avisa y, al abrir, la cabecera se regenera desde la base
        (la migración registrada explica el esquema distinto)."""
        with project_tmp() as tmp:
            env = Env(tmp)
            failure = errors.ProjectError(
                "core.manifest_write_failed", "disco lleno", obj="Proyecto", field="manifest.json"
            )
            with mock.patch.object(migrations, "write_manifest", side_effect=failure):
                with self.assertLogs("geoblender.core.project", "WARNING") as logged:
                    result = env.migrate((M1_2, M2_3))[-1].result
            self.assertIn("write_failed", "\n".join(logged.output))
            self.assertTrue(any("cabecera" in item for item in result.warnings))
            self.assertEqual(manifest_mod.read_manifest(env.root).schema_version, 1)
            self.assertEqual(env.read("SELECT schema_version FROM gb_project"), [(3,)])
            with mock.patch.object(open_mod, "SCHEMA_VERSION", 3):
                opened = env.open()
            try:
                self.assertTrue(opened.project.writable)
                self.assertEqual(manifest_mod.read_manifest(env.root).schema_version, 3)
                self.assertIn(
                    "manifest_rewritten", [item.kind for item in env.events()]
                )
            finally:
                opened.project.close()

    def test_wal_left_by_qgis_is_recovered_before_the_backup(self) -> None:
        """RF-002-17, RF-002-20: una base que QGIS dejó en WAL (ya cerrado) vuelve al
        diario clásico antes de la copia previa, sin perder lo que escribió QGIS (que
        queda también en la copia), con aviso y evento ``wal_recovered``."""
        with project_tmp() as tmp:
            env = Env(tmp)
            conn = sqlite3.connect(env.db, isolation_level=None)
            try:
                conn.execute(WAL_PRAGMA)
                conn.execute("CREATE TABLE capa_qgis (a TEXT)")
                conn.execute("INSERT INTO capa_qgis VALUES ('editada')")
            finally:
                conn.close()
            self.assertEqual(gpkg.read_header(env.db).journal, "wal")
            result = env.migrate((M1_2, M2_3))[-1].result
            self.assertTrue(any("WAL" in item for item in result.warnings))
            self.assertEqual(gpkg.read_header(env.db).journal, "classic")
            self.assertEqual(env.read("SELECT a FROM capa_qgis"), [("editada",)])
            self.assertIn("wal_recovered", [item.kind for item in env.events()])
            with gpkg.GpkgConnection.open_read(result.backup / "project.gpkg") as db:
                self.assertEqual(
                    db.connection.execute("SELECT a FROM capa_qgis").fetchall(), [("editada",)]
                )
                self.assertEqual(schema.read_project(db.connection).schema_version, 1)

    def test_wal_held_open_by_another_program_is_not_migrated(self) -> None:
        """RF-002-17, RF-002-20: con la base abierta en WAL por otro programa (QGIS
        editando) no se copia ni se migra nada, y el error dice qué cerrar."""
        with project_tmp() as tmp:
            env = Env(tmp)
            foreign = sqlite3.connect(env.db, isolation_level=None)
            try:
                foreign.execute(WAL_PRAGMA)
                foreign.execute("CREATE TABLE capa_qgis (a TEXT)")
                foreign.execute("INSERT INTO capa_qgis VALUES ('editando')")
                before = _snapshot(env.parent)
                with self.assertRaises(errors.ProjectError) as caught:
                    env.migrate((M1_2, M2_3))
                self.assertEqual(caught.exception.code, "core.migration_wal_busy")
                self.assertIn("cierre", str(caught.exception))
                self.assertEqual(_snapshot(env.parent), before)
            finally:
                foreign.close()

    def test_orphan_lock_is_replaced_and_recorded(self) -> None:
        """RF-002-04, RF-002-20: un cerrojo huérfano del mismo equipo (Blender cerrado de
        golpe) se sustituye para migrar, queda registrado y se libera al terminar."""
        with project_tmp() as tmp:
            env = Env(tmp)
            info = lock.LockInfo.new(SESSION_A, lock.LockMode.LOCAL, env.clock)
            (env.root / ".lock").write_bytes(lock.encode_lock(info))
            env.pids.kill(SESSION_A.pid)
            env.migrate((M1_2, M2_3), session=SESSION_A2)
            self.assertIn("lock_orphan_replaced", [item.kind for item in env.events()])
            self.assertFalse((env.root / ".lock").exists())
            self.assertFalse((env.parent / BACKUP_NAME / ".lock").exists())

    def test_lock_held_by_another_session_is_not_migrated(self) -> None:
        """RF-002-09, RF-002-20: si otra sesión tiene el proyecto abierto en escritura no
        se migra (ni se copia): error con quién lo tiene."""
        with project_tmp() as tmp:
            env = Env(tmp)
            holder = env.open(SESSION_A).project
            try:
                before = _snapshot(env.parent)
                with self.assertRaises(errors.LockError) as caught:
                    env.migrate((M1_2, M2_3))
                self.assertIn("PC-PRUEBA-A", str(caught.exception))
                self.assertEqual(_snapshot(env.parent), before)
            finally:
                holder.close()


if __name__ == "__main__":
    unittest.main()
