# SPDX-License-Identifier: GPL-3.0-or-later
"""Cabecera SQLite y conexión al GeoPackage del proyecto (spec 002, T06; RF-002-16;
ADR-0006; plan 002 §5.2 y §5.4).

El GeoPackage se mantiene en diario clásico (``journal_mode = delete``) y nunca en WAL,
que no funciona en una unidad de red. La escritura espera como mucho 0,2 s a otro
programa (``busy_timeout``) y devuelve el control con «ocupado»; la lectura de una BD en
diario clásico no crea ningún fichero junto a ella.

Las pruebas que necesitan una BD en WAL la preparan aquí, con su propia conexión: el
literal lo prohíbe ARQ-17 solo en el código de la extensión.
"""

import sqlite3
import time
import unittest
from pathlib import Path

from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender

gpkg = import_geoblender("core.gpkg")
header = import_geoblender("core.gpkg.header")
connection = import_geoblender("core.gpkg.connection")
errors = import_geoblender("core.errors")

SIDE_SUFFIXES = ("-wal", "-shm", "-journal")


def _make_db(path: Path, *, wal: bool = False) -> None:
    """Una BD SQLite con una tabla ``t`` de 3 filas (en WAL si se pide)."""
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        if wal:
            conn.execute("PRAGMA journal_mode=" + "WAL")
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.executemany("INSERT INTO t (v) VALUES (?)", [("a",), ("b",), ("c",)])
    finally:
        conn.close()


def _snapshot(folder: Path) -> dict[str, tuple[int, int]]:
    """Nombre → (tamaño, mtime_ns) de cada fichero de la carpeta."""
    return {
        path.name: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in sorted(folder.iterdir())
    }


def _side_files(path: Path) -> list[str]:
    return [suffix for suffix in SIDE_SUFFIXES if Path(f"{path}{suffix}").exists()]


class HeaderTest(unittest.TestCase):
    def test_classic_and_wal(self) -> None:
        """RF-002-16: la cabecera (bytes 18 y 19) dice «classic» en diario clásico y
        «wal» si la BD está en WAL, aunque ya no haya ``-wal``; y dice qué ficheros hay
        junto a ella."""
        with project_tmp() as tmp:
            classic = tmp / "clasico.gpkg"
            _make_db(classic)
            info = gpkg.read_header(classic)
            self.assertEqual(info.journal, "classic")
            self.assertEqual((info.write_version, info.read_version), (1, 1))
            self.assertFalse(info.has_wal or info.has_shm or info.has_journal)
            self.assertFalse(info.needs_recovery)
            wal = tmp / "wal.gpkg"
            _make_db(wal, wal=True)
            info = gpkg.read_header(wal)
            self.assertEqual(info.journal, "wal")
            self.assertEqual((info.write_version, info.read_version), (2, 2))
            self.assertTrue(info.needs_recovery)

    def test_side_files(self) -> None:
        """RF-002-16, RF-002-17: un ``-wal``, un ``-shm`` o un ``-journal`` no vacío
        (diario caliente) junto a la BD se detectan."""
        with project_tmp() as tmp:
            path = tmp / "p.gpkg"
            _make_db(path)
            Path(f"{path}-journal").write_bytes(b"\xd9\xd5\x05\xf9\x20\xa1\x63\xd7")
            Path(f"{path}-wal").write_bytes(b"")
            info = gpkg.read_header(path)
            self.assertTrue(info.has_journal and info.has_hot_journal and info.has_wal)
            self.assertTrue(info.needs_recovery)
            Path(f"{path}-journal").write_bytes(b"")
            self.assertFalse(gpkg.read_header(path).has_hot_journal)

    def test_not_sqlite_or_missing(self) -> None:
        """RF-002-16: un fichero que no es SQLite o que no existe da un error con la
        ruta, y leer la cabecera no crea nada."""
        with project_tmp() as tmp:
            other = tmp / "otro.gpkg"
            other.write_bytes(b"no es una base de datos" * 10)
            with self.assertRaises(errors.DatabaseError) as caught:
                gpkg.read_header(other)
            self.assertEqual(caught.exception.code, "core.gpkg_not_sqlite")
            with self.assertRaises(errors.DatabaseError) as caught:
                gpkg.read_header(tmp / "no.gpkg")
            self.assertEqual(caught.exception.code, "core.gpkg_missing")
            self.assertEqual(sorted(p.name for p in tmp.iterdir()), ["otro.gpkg"])


class WriteConnectionTest(unittest.TestCase):
    def test_pragmas_and_writer_function(self) -> None:
        """RF-002-16: la conexión de escritura usa diario clásico, ``synchronous = FULL``,
        claves foráneas, ``busy_timeout = 200`` y la función ``gb_writer()``."""
        with project_tmp() as tmp:
            path = tmp / "project.gpkg"
            with gpkg.GpkgConnection.open_write(path, create=True) as db:
                conn = db.connection
                self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "delete")
                self.assertEqual(conn.execute("PRAGMA synchronous").fetchone()[0], 2)
                self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertEqual(conn.execute("PRAGMA busy_timeout").fetchone()[0], 200)
                self.assertEqual(conn.execute("SELECT gb_writer()").fetchone()[0], 1)
                self.assertTrue(db.writable)
            self.assertEqual(connection.BUSY_TIMEOUT_MS, 200)

    def test_classic_journal_after_each_transaction(self) -> None:
        """RF-002-16: tras cada transacción, ``journal_mode`` = ``delete``, la cabecera
        dice diario clásico y no hay ``-wal`` (ni ``-shm`` ni ``-journal``)."""
        with project_tmp() as tmp:
            path = tmp / "project.gpkg"
            with gpkg.GpkgConnection.open_write(path, create=True) as db:
                for index in range(3):
                    with db.transaction() as conn:
                        if index == 0:
                            conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
                        conn.execute("INSERT INTO t (v) VALUES (?)", (str(index),))
                    mode = db.connection.execute("PRAGMA journal_mode").fetchone()[0]
                    self.assertEqual(mode, "delete")
                    self.assertEqual(gpkg.read_header(path).journal, "classic")
                    self.assertEqual(_side_files(path), [])
                count = db.connection.execute("SELECT count(*) FROM t").fetchone()[0]
                self.assertEqual(count, 3)

    def test_rollback_on_error(self) -> None:
        """RF-002-12, RF-002-16: un error a mitad de la transacción la deshace entera."""
        with project_tmp() as tmp:
            path = tmp / "p.gpkg"
            _make_db(path)
            with gpkg.GpkgConnection.open_write(path) as db:
                with self.assertRaises(RuntimeError), db.transaction() as conn:
                    conn.execute("INSERT INTO t (v) VALUES ('d')")
                    raise RuntimeError("fallo simulado")
                self.assertFalse(db.connection.in_transaction)
                count = db.connection.execute("SELECT count(*) FROM t").fetchone()[0]
            self.assertEqual(count, 3)

    def test_busy_returns_quickly(self) -> None:
        """RF-002-16 (plan §5.2): con otra conexión que mantiene una lectura abierta, una
        escritura devuelve «ocupado» en ≤ 0,25 s sin cambiar nada (el ``busy_timeout`` de
        SQLite esperaría 0,29 s en Windows: el cerrojo se toma con un reintento propio) y
        el ``busy_timeout`` vuelve a 200; al liberarla, la misma escritura termina."""
        with project_tmp() as tmp:
            path = tmp / "p.gpkg"
            _make_db(path)
            reader = sqlite3.connect(path, isolation_level=None)
            try:
                reader.execute("BEGIN")
                reader.execute("SELECT count(*) FROM t").fetchone()
                with gpkg.GpkgConnection.open_write(path) as db:
                    start = time.perf_counter()
                    with self.assertRaises(errors.DatabaseBusyError) as caught:
                        with db.transaction() as conn:
                            conn.execute("INSERT INTO t (v) VALUES ('d')")
                    elapsed = time.perf_counter() - start
                    self.assertLessEqual(elapsed, 0.25)
                    self.assertEqual(caught.exception.code, "core.gpkg_busy")
                    self.assertFalse(db.connection.in_transaction)
                    timeout = db.connection.execute("PRAGMA busy_timeout").fetchone()[0]
                    self.assertEqual(timeout, 200)
                    reader.execute("COMMIT")
                    self.assertEqual(reader.execute("SELECT count(*) FROM t").fetchone()[0], 3)
                    with db.transaction() as conn:
                        conn.execute("INSERT INTO t (v) VALUES ('d')")
                    self.assertEqual(reader.execute("SELECT count(*) FROM t").fetchone()[0], 4)
            finally:
                reader.close()

    def test_refuses_wal_and_missing(self) -> None:
        """RF-002-16, RF-002-17: no se abre para escribir una BD en WAL (antes hay que
        devolverla al diario clásico) ni una que no existe sin pedir crearla."""
        with project_tmp() as tmp:
            wal = tmp / "wal.gpkg"
            _make_db(wal, wal=True)
            with self.assertRaises(errors.DatabaseError) as caught:
                gpkg.GpkgConnection.open_write(wal)
            self.assertEqual(caught.exception.code, "core.gpkg_wal")
            self.assertEqual(gpkg.read_header(wal).journal, "wal")
            with self.assertRaises(errors.DatabaseError) as caught:
                gpkg.GpkgConnection.open_write(tmp / "no.gpkg")
            self.assertEqual(caught.exception.code, "core.gpkg_missing")
            self.assertFalse((tmp / "no.gpkg").exists())


class ReadConnectionTest(unittest.TestCase):
    def test_read_creates_no_file(self) -> None:
        """RF-002-13, RF-002-16: abrir para leer una BD en diario clásico, leer y cerrar
        no crea ni cambia ningún fichero de la carpeta."""
        with project_tmp() as tmp:
            path = tmp / "p.gpkg"
            _make_db(path)
            before = _snapshot(tmp)
            with gpkg.GpkgConnection.open_read(path) as db:
                rows = db.connection.execute("SELECT v FROM t ORDER BY id").fetchall()
                self.assertEqual(rows, [("a",), ("b",), ("c",)])
                self.assertFalse(db.writable)
                self.assertEqual(_snapshot(tmp), before)
            self.assertEqual(_snapshot(tmp), before)

    def test_read_cannot_write(self) -> None:
        """RF-002-13: la conexión de lectura no escribe ni tiene ``gb_writer()`` ni
        ``transaction()``."""
        with project_tmp() as tmp:
            path = tmp / "p.gpkg"
            _make_db(path)
            with gpkg.GpkgConnection.open_read(path) as db:
                with self.assertRaises(sqlite3.OperationalError):
                    db.connection.execute("INSERT INTO t (v) VALUES ('x')")
                with self.assertRaises(sqlite3.OperationalError):
                    db.connection.execute("SELECT gb_writer()")
                with self.assertRaises(errors.DatabaseError):
                    with db.transaction():
                        pass
            with sqlite3.connect(path) as check:
                self.assertEqual(check.execute("SELECT count(*) FROM t").fetchone()[0], 3)
            check.close()

    def test_read_missing_creates_nothing(self) -> None:
        """RF-002-13: abrir para leer una BD que no existe es un error y no la crea."""
        with project_tmp() as tmp:
            with self.assertRaises(errors.DatabaseError):
                gpkg.GpkgConnection.open_read(tmp / "no.gpkg")
            self.assertEqual(list(tmp.iterdir()), [])


class UriTest(unittest.TestCase):
    def test_sqlite_uri(self) -> None:
        """RF-002-16: la URI de SQLite de una ruta con unidad y de una UNC (sin
        autoridad, que SQLite rechaza), con caracteres especiales escapados."""
        drive = connection.sqlite_uri(Path("C:/a b/p#1.gpkg"), mode="ro")
        self.assertEqual(drive, "file:///C:/a%20b/p%231.gpkg?mode=ro")
        unc = connection.sqlite_uri(Path("//srv/recurso/p.gpkg"), mode="ro")
        self.assertEqual(unc, "file:////srv/recurso/p.gpkg?mode=ro")


if __name__ == "__main__":
    unittest.main()
