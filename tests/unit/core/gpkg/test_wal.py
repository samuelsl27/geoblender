# SPDX-License-Identifier: GPL-3.0-or-later
"""Vuelta al diario clásico y lectura de una base en WAL (spec 002, T09; RF-002-17,
RF-002-13; plan 002 §5.4 y §6).

QGIS 4.2 pasa a WAL un GeoPackage local al editar y lo deja así al cerrar; mientras lo
tiene abierto, otra conexión no puede volverlo al diario clásico. Geoblender lo devuelve
con ``locking_mode = EXCLUSIVE`` (sin memoria compartida, válido en red) y
``journal_mode = DELETE``, sin perder filas; si otro programa lo tiene abierto, «ocupado»
sin cambios. Leer una base en WAL en el sitio crearía ``-wal`` y ``-shm`` junto a ella: se
lee una copia privada.

Las bases en WAL de estas pruebas las preparan las propias pruebas (el literal lo prohíbe
ARQ-17 solo en el código de la extensión).
"""

import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path

from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender
from tests.support.trees import child_env, child_temp

gpkg = import_geoblender("core.gpkg")
wal = import_geoblender("core.gpkg.wal")
errors = import_geoblender("core.errors")

WAL_PRAGMA = "PRAGMA journal_mode=" + "WAL"
# Escritor que confirma 50 filas en WAL y termina sin cerrar (como un QGIS que se cae):
# deja el -wal sin consolidar y un -shm huérfano.
KILLED_WRITER = f"""
import os, sqlite3, sys
conn = sqlite3.connect(sys.argv[1], isolation_level=None)
conn.execute("{WAL_PRAGMA}")
for index in range(50):
    conn.execute("BEGIN")
    conn.execute("INSERT INTO t (v) VALUES (?)", (index,))
    conn.execute("COMMIT")
os._exit(0)
"""


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v INTEGER)")
    finally:
        conn.close()


def _wal_db_closed(path: Path) -> None:
    """Una base en WAL cerrada limpiamente: cabecera WAL y sin ``-wal``."""
    _make_db(path)
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        conn.execute(WAL_PRAGMA)
        conn.executemany("INSERT INTO t (v) VALUES (?)", [(1,), (2,), (3,)])
    finally:
        conn.close()


def _killed_writer(path: Path) -> None:
    """Una base con 50 filas confirmadas que solo están en el ``-wal``."""
    _make_db(path)
    with child_temp() as temp:
        subprocess.run(
            [sys.executable, "-B", "-s", "-c", KILLED_WRITER, str(path)],
            env=child_env(None, temp),
            check=True,
            timeout=60,
            capture_output=True,
        )


def _snapshot(folder: Path) -> dict[str, tuple[int, int]]:
    return {
        path.name: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in sorted(folder.iterdir())
    }


def _count(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return int(conn.execute("SELECT count(*) FROM t").fetchone()[0])
    finally:
        conn.close()


class ToClassicJournalTest(unittest.TestCase):
    def test_already_classic(self) -> None:
        """RF-002-16: una base en diario clásico queda igual y no se toca."""
        with project_tmp() as tmp:
            path = tmp / "p.gpkg"
            _make_db(path)
            before = _snapshot(tmp)
            result = gpkg.to_classic_journal(path)
            self.assertEqual(result.outcome, gpkg.WalOutcome.ALREADY_CLASSIC)
            self.assertEqual(_snapshot(tmp), before)

    def test_wal_header_without_wal_file(self) -> None:
        """RF-002-17: cabecera WAL sin ``-wal`` → diario clásico, con las filas."""
        with project_tmp() as tmp:
            path = tmp / "p.gpkg"
            _wal_db_closed(path)
            self.assertEqual(gpkg.read_header(path).journal, "wal")
            self.assertFalse(Path(f"{path}-wal").exists())
            result = gpkg.to_classic_journal(path)
            self.assertEqual(result.outcome, gpkg.WalOutcome.CONVERTED)
            self.assertEqual(gpkg.read_header(path).journal, "classic")
            self.assertEqual(_count(path), 3)
            self.assertEqual(sorted(p.name for p in tmp.iterdir()), ["p.gpkg"])

    def test_wal_file_from_killed_writer(self) -> None:
        """RF-002-17: un ``-wal`` con 50 filas confirmadas (escritor terminado con
        ``os._exit``) → diario clásico, 50 filas, ``integrity_check`` = ok, sin ``-wal``
        ni el ``-shm`` huérfano, y el tamaño consolidado en el resultado."""
        with project_tmp() as tmp:
            path = tmp / "p.gpkg"
            _killed_writer(path)
            self.assertTrue(Path(f"{path}-wal").exists())
            wal_bytes = Path(f"{path}-wal").stat().st_size
            result = gpkg.to_classic_journal(path)
            self.assertEqual(result.outcome, gpkg.WalOutcome.CONVERTED)
            self.assertEqual(result.wal_bytes, wal_bytes)
            self.assertGreater(result.wal_bytes, 0)
            header = gpkg.read_header(path)
            self.assertEqual(header.journal, "classic")
            self.assertFalse(header.has_wal or header.has_shm or header.has_journal)
            self.assertEqual(_count(path), 50)
            conn = sqlite3.connect(path)
            try:
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            finally:
                conn.close()

    def test_busy_when_open_elsewhere(self) -> None:
        """RF-002-17: con otra conexión abierta en WAL (QGIS editando) → «ocupado», sin
        cambios en la base (volcado y cabecera)."""
        with project_tmp() as tmp:
            path = tmp / "p.gpkg"
            _wal_db_closed(path)
            other = sqlite3.connect(path, isolation_level=None)
            try:
                other.execute("SELECT count(*) FROM t").fetchone()
                dump = list(other.iterdump())
                result = gpkg.to_classic_journal(path, timeout_s=0.2)
                self.assertEqual(result.outcome, gpkg.WalOutcome.BUSY)
                self.assertEqual(gpkg.read_header(path).journal, "wal")
                self.assertEqual(list(other.iterdump()), dump)
            finally:
                other.close()
            self.assertEqual(gpkg.to_classic_journal(path).outcome, gpkg.WalOutcome.CONVERTED)


class PrivateReadTest(unittest.TestCase):
    def test_read_wal_creates_nothing_beside_it(self) -> None:
        """RF-002-13, RF-002-17: la lectura de una base en WAL (con su ``-wal`` de 50
        filas) no crea ni cambia ningún fichero junto a ella: lee una copia privada, con
        todas las filas."""
        with project_tmp() as tmp, project_tmp(prefix="geoblender-privada-") as private:
            folder = tmp / "proyecto"
            folder.mkdir()
            path = folder / "project.gpkg"
            _killed_writer(path)
            before = _snapshot(folder)
            with gpkg.GpkgConnection.open_read(path, private_dir=private) as db:
                count = db.connection.execute("SELECT count(*) FROM t").fetchone()[0]
                self.assertFalse(db.writable)
                self.assertEqual(db.source, path)
                self.assertTrue(db.path.is_relative_to(private))
                self.assertEqual(_snapshot(folder), before)
            self.assertEqual(count, 50)
            self.assertEqual(_snapshot(folder), before)

    def test_private_copy_is_classic_and_replaced(self) -> None:
        """RF-002-13: la copia privada queda en diario clásico y sin ficheros
        acompañantes; una segunda lectura sustituye la copia anterior."""
        with project_tmp() as tmp, project_tmp(prefix="geoblender-privada-") as private:
            path = tmp / "project.gpkg"
            _wal_db_closed(path)
            copy = wal.private_copy(path, private)
            self.assertEqual(copy.parent, private)
            self.assertEqual(gpkg.read_header(copy).journal, "classic")
            self.assertEqual(sorted(p.name for p in private.iterdir()), [copy.name])
            again = wal.private_copy(path, private)
            self.assertEqual(again, copy)
            self.assertEqual(_count(again), 3)

    def test_read_wal_without_private_dir(self) -> None:
        """RF-002-13: sin carpeta privada, leer una base en WAL es un error y no se crea
        nada junto a ella."""
        with project_tmp() as tmp:
            path = tmp / "project.gpkg"
            _wal_db_closed(path)
            before = _snapshot(tmp)
            with self.assertRaises(errors.DatabaseError):
                gpkg.GpkgConnection.open_read(path)
            self.assertEqual(_snapshot(tmp), before)


if __name__ == "__main__":
    unittest.main()
