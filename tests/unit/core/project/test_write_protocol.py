# SPDX-License-Identifier: GPL-3.0-or-later
"""Protocolo de escritura del proyecto, ``Project.write_transaction()`` (spec 002, T17;
RF-002-12, RF-002-16, RF-002-17; plan 002 §5.4, «Escritura»).

Cada escritura: 1) solo en un modo de escritura; 2) con el cerrojo de esta sesión;
3) con la base en diario clásico, devolviéndola a él si otro programa la pasó a WAL (y si
la tiene abierta, solo lectura indicando qué cerrar); 4) ``BEGIN IMMEDIATE`` … ``COMMIT``;
5) la base sigue en diario clásico. Cualquier error de disco, de red o de SQLite deshace
la transacción, cierra la conexión y deja el proyecto en solo lectura con el motivo. Si
QGIS u otro programa está leyendo, la escritura devuelve el control enseguida (≤ 0,2 s de
espera) con el estado «reintentando» y no cambia nada; al reintentar cuando termina, se
completa.

Las bases en WAL de estas pruebas las preparan las propias pruebas (el literal lo prohíbe
ARQ-17 solo en el código de la extensión).
"""

import sqlite3
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.support.core_fixtures import FakeClock, FakePids, make_session, make_settings, project_tmp
from tests.support.package import import_geoblender

create = import_geoblender("core.project.create")
session_mod = import_geoblender("core.project.session")
model = import_geoblender("core.project.model")
events = import_geoblender("core.project.events")
lock = import_geoblender("core.project.lock")
errors = import_geoblender("core.errors")
gpkg = import_geoblender("core.gpkg")
connection = import_geoblender("core.gpkg.connection")
userdata_mod = import_geoblender("core.userdata")

SESSION_A = make_session()
SESSION_B = make_session(
    session_uid="00000000-0000-4000-8000-000000000002", host="PC-PRUEBA-B", user="otra", pid=777
)
WAL_PRAGMA = "PRAGMA journal_mode=" + "WAL"
NOW = "2026-10-05T08:12:44.000Z"


def _created(tmp: Path):
    parent = tmp / "proyectos"
    parent.mkdir()
    clock = FakeClock()
    result = create.create_project(
        parent, make_settings(), SESSION_A, userdata_mod.UserData(tmp / "u"), clock=clock
    )
    return result.project, clock


def _event(conn: sqlite3.Connection, message: str) -> None:
    events.record_event(conn, events.EventKind.OPEN, message, session=SESSION_A, at=NOW)


def _dump(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return list(conn.iterdump())
    finally:
        conn.close()


def _messages(path: Path) -> list[str]:
    with gpkg.GpkgConnection.open_read(path) as db:
        return [item.message for item in events.read_events(db.connection)]


class FailureTest(unittest.TestCase):
    def test_os_error_midway_rolls_back_and_goes_read_only(self) -> None:
        """RF-002-12: un error de disco o de red a mitad de una escritura deja la base
        como estaba (volcado SQL idéntico), avisa con el motivo y pasa a solo lectura;
        después no se escribe nada más."""
        with project_tmp() as tmp:
            project, _clock = _created(tmp)
            before = _dump(project.database_path)
            with self.assertLogs("geoblender.core.project", "WARNING"):
                with self.assertRaises(errors.ProjectError) as caught:
                    with project.write_transaction() as conn:
                        _event(conn, "primera fila")
                        raise OSError(64, "El nombre de red especificado ya no está disponible")
            self.assertEqual(caught.exception.code, "core.project_write_failed")
            self.assertIn("ya no está disponible", str(caught.exception))
            self.assertEqual(_dump(project.database_path), before)
            self.assertEqual(project.mode, model.OpenMode.READ_ONLY)
            self.assertEqual(project.read_only_reason, model.ReadOnlyCode.WRITE_FAILED)
            self.assertIn("ya no está disponible", project.status.message)
            with self.assertRaises(errors.ProjectError):
                with project.write_transaction():
                    pass
            self.assertEqual(_dump(project.database_path), before)
            project.close()

    def test_sqlite_error_on_commit_rolls_back(self) -> None:
        """RF-002-12: un fallo de E/S de SQLite al confirmar deja la base igual y el
        proyecto en solo lectura con el motivo."""
        with project_tmp() as tmp:
            project, _clock = _created(tmp)
            before = _dump(project.database_path)
            real = connection.GpkgConnection._locking

            def failing(self, sql: str) -> None:
                if sql == "COMMIT":
                    raise sqlite3.OperationalError("disk I/O error")
                real(self, sql)

            with mock.patch.object(connection.GpkgConnection, "_locking", failing):
                with self.assertLogs("geoblender.core.project", "WARNING"):
                    with self.assertRaises(errors.ProjectError):
                        with project.write_transaction() as conn:
                            _event(conn, "no llega")
            self.assertEqual(_dump(project.database_path), before)
            self.assertEqual(project.read_only_reason, model.ReadOnlyCode.WRITE_FAILED)
            self.assertIn("disk I/O error", project.status.message)
            project.close()

    def test_own_error_rolls_back_and_stays_writable(self) -> None:
        """RF-002-12: un error de Geoblender dentro de la transacción (una validación) la
        deshace sin pasar a solo lectura."""
        with project_tmp() as tmp:
            project, _clock = _created(tmp)
            before = _dump(project.database_path)
            invalid = errors.ValidationError("core.x", "no vale", obj="Prueba", field="campo")
            with self.assertRaises(errors.ValidationError):
                with project.write_transaction() as conn:
                    _event(conn, "no llega")
                    raise invalid
            self.assertEqual(_dump(project.database_path), before)
            self.assertTrue(project.writable)
            project.close()

    def test_foreign_lock_blocks_writing(self) -> None:
        """RF-002-12: si otra sesión forzó el cerrojo, no se escribe nada y el proyecto
        pasa a solo lectura con el motivo «cerrojo perdido»."""
        with project_tmp() as tmp:
            project, clock = _created(tmp)
            clock.advance(minutes=31)
            seen = lock.inspect(project.root, SESSION_B, clock=clock, pid_alive=FakePids())
            lock.force(project.root, SESSION_B, lock.LockMode.LOCAL, seen.holder, clock=clock,
                       pid_alive=FakePids())
            before = _dump(project.database_path)
            with self.assertLogs("geoblender.core.project", "WARNING"):
                with self.assertRaises(errors.LockError):
                    with project.write_transaction() as conn:
                        _event(conn, "no llega")
            self.assertEqual(_dump(project.database_path), before)
            self.assertEqual(project.read_only_reason, model.ReadOnlyCode.LOCK_LOST)
            project.close()
            self.assertEqual(lock.read_holder(project.root, clock=clock).session_uid,
                             SESSION_B.session_uid)


class JournalTest(unittest.TestCase):
    def test_classic_journal_after_each_write(self) -> None:
        """RF-002-16: tras cada escritura la base sigue en diario clásico y sin ``-wal``."""
        with project_tmp() as tmp:
            project, _clock = _created(tmp)
            for index in range(3):
                with project.write_transaction() as conn:
                    _event(conn, f"escritura {index}")
                header = gpkg.read_header(project.database_path)
                self.assertEqual(header.journal, "classic")
                self.assertFalse(header.has_wal)
            project.close()

    def test_wal_between_writes_is_recovered(self) -> None:
        """RF-002-17: una base que otra conexión pasó a WAL entre dos escrituras vuelve al
        diario clásico antes de escribir, sin perder nada, con aviso y evento
        ``wal_recovered``."""
        with project_tmp() as tmp:
            project, _clock = _created(tmp)
            with project.write_transaction() as conn:
                _event(conn, "antes")
            foreign = sqlite3.connect(project.database_path, isolation_level=None)
            try:
                foreign.execute(WAL_PRAGMA)
                foreign.execute("CREATE TABLE ajena (a TEXT)")
                foreign.execute("INSERT INTO ajena VALUES ('de QGIS')")
            finally:
                foreign.close()
            self.assertEqual(gpkg.read_header(project.database_path).journal, "wal")
            with project.write_transaction() as conn:
                _event(conn, "después")
            self.assertEqual(gpkg.read_header(project.database_path).journal, "classic")
            messages = _messages(project.database_path)
            self.assertIn("después", messages)
            with gpkg.GpkgConnection.open_read(project.database_path) as db:
                kinds = [item.kind for item in events.read_events(db.connection)]
                self.assertEqual(db.connection.execute("SELECT a FROM ajena").fetchone()[0],
                                 "de QGIS")
            self.assertIn("wal_recovered", kinds)
            self.assertTrue(any("WAL" in item for item in project.take_notices()))
            self.assertEqual(project.take_notices(), [])
            project.close()

    def test_wal_busy_goes_read_only(self) -> None:
        """RF-002-17: si la base está en WAL y otro programa la tiene abierta, no se
        escribe y el proyecto pasa a solo lectura indicando que se cierre ese programa."""
        with project_tmp() as tmp:
            project, _clock = _created(tmp)
            foreign = sqlite3.connect(project.database_path, isolation_level=None)
            try:
                foreign.execute(WAL_PRAGMA)
                count = foreign.execute("SELECT count(*) FROM gb_event").fetchone()[0]
                with self.assertLogs("geoblender.core.project", "WARNING"):
                    with self.assertRaises(errors.ProjectError) as caught:
                        with project.write_transaction() as conn:
                            _event(conn, "no llega")
                self.assertEqual(caught.exception.code, "core.project_wal_busy")
                self.assertEqual(project.read_only_reason, model.ReadOnlyCode.WAL_BUSY)
                self.assertIn("QGIS", project.status.message)
                self.assertEqual(
                    foreign.execute("SELECT count(*) FROM gb_event").fetchone()[0], count
                )
            finally:
                foreign.close()
            project.close()


class BusyTest(unittest.TestCase):
    def test_foreign_reader_returns_control_and_retries(self) -> None:
        """RF-002-12, RF-002-16: con una lectura ajena abierta, la escritura devuelve el
        control enseguida (espera ≤ 0,2 s) con el estado «reintentando» sin cambiar nada y
        sin pasar a solo lectura; cuando la lectura termina, el reintento se completa."""
        with project_tmp() as tmp:
            project, _clock = _created(tmp)
            before = _dump(project.database_path)
            reader = sqlite3.connect(project.database_path, isolation_level=None)
            try:
                reader.execute("BEGIN")
                reader.execute("SELECT count(*) FROM gb_event").fetchone()
                start = time.perf_counter()
                attempt = project.try_write(lambda conn: _event(conn, "con QGIS leyendo"))
                elapsed = time.perf_counter() - start
            finally:
                reader.execute("COMMIT")
                reader.close()
            self.assertEqual(attempt.state, session_mod.WriteState.RETRYING)
            self.assertIn("reintentando", attempt.message)
            self.assertLessEqual(elapsed, 0.25, f"{elapsed:.3f} s")
            self.assertEqual(_dump(project.database_path), before)
            self.assertTrue(project.writable)
            attempt = project.try_write(lambda conn: _event(conn, "con QGIS leyendo"))
            self.assertEqual(attempt.state, session_mod.WriteState.DONE)
            self.assertIn("con QGIS leyendo", _messages(project.database_path))
            project.close()


if __name__ == "__main__":
    unittest.main()
