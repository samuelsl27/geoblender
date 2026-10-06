# SPDX-License-Identifier: GPL-3.0-or-later
"""Solo lectura sin tocar nada (spec 002, T18; RF-002-13, RF-002-17; plan 002 §5.4,
«Solo lectura sin ensuciar»).

Mientras un proyecto está abierto en solo lectura, Geoblender no crea, modifica ni borra
ningún fichero dentro de su carpeta. Para cada motivo (bloqueado por otra sesión, esquema
posterior, sin migrar, WAL ocupado por otro programa, a petición; y también tras perder
el cerrojo) se comprueba que la lista de ficheros del proyecto, sus tamaños, sus sha256 y
sus fechas de modificación son idénticos antes y después de abrir, leer y cerrar. Una base
en WAL se lee en una copia privada fuera del proyecto: no aparecen ``-wal`` ni ``-shm``
junto a ella.

Las bases en WAL de estas pruebas las preparan las propias pruebas (el literal lo prohíbe
ARQ-17 solo en el código de la extensión).
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
lock = import_geoblender("core.project.lock")
gpkg = import_geoblender("core.gpkg")
userdata_mod = import_geoblender("core.userdata")

SESSION_A = make_session()
SESSION_B = make_session(
    session_uid="00000000-0000-4000-8000-000000000002", host="PC-PRUEBA-B", user="otra", pid=777
)
WAL_PRAGMA = "PRAGMA journal_mode=" + "WAL"


def _snapshot(root: Path) -> dict[str, tuple[int, str, int] | str]:
    """Cada fichero de la carpeta (recursiva): tamaño, sha256 y fecha de modificación; y
    cada subcarpeta."""
    found: dict[str, tuple[int, str, int] | str] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_dir():
            found[rel] = "carpeta"
        else:
            stat = path.stat()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            found[rel] = (stat.st_size, digest, stat.st_mtime_ns)
    return found


class Env:
    def __init__(self, tmp: Path) -> None:
        parent = tmp / "proyectos"
        parent.mkdir()
        self.userdata = userdata_mod.UserData(tmp / "datos_usuario")
        self.clock = FakeClock()
        self.pids = FakePids({SESSION_A.pid, SESSION_B.pid})
        self.created = create.create_project(
            parent, make_settings(), SESSION_A, self.userdata, clock=self.clock
        )
        self.root = self.created.root

    def open(self, session, **kwargs):
        return open_mod.open_project(
            self.root, session, self.userdata, clock=self.clock, pid_alive=self.pids, **kwargs
        )


class ReadOnlyGuaranteeTest(unittest.TestCase):
    def _assert_untouched(self, env: Env, session, reason, **kwargs) -> None:
        before = _snapshot(env.root)
        result = env.open(session, **kwargs)
        project = result.project
        self.assertEqual(project.mode, model.OpenMode.READ_ONLY)
        self.assertEqual(project.read_only_reason, reason)
        self.assertTrue(project.status.message.startswith("Solo lectura: "))
        with project.read() as conn:
            self.assertEqual(schema.read_project(conn).uid, env.created.record.uid)
            conn.execute("SELECT count(*) FROM gb_event").fetchone()
        project.reload()
        self.assertEqual(project.cache_dir(), env.userdata.cache_dir(project.uid))
        project.close()
        self.assertEqual(_snapshot(env.root), before)

    def test_locked(self) -> None:
        """RF-002-13: bloqueado por otra sesión: nada cambia en la carpeta."""
        with project_tmp() as tmp:
            env = Env(tmp)
            self._assert_untouched(env, SESSION_B, model.ReadOnlyCode.LOCKED)
            env.created.project.close()

    def test_reserved(self) -> None:
        """RF-002-13: reservado para una copia local: nada cambia en la carpeta."""
        with project_tmp() as tmp:
            env = Env(tmp)
            env.created.project.close()
            info = lock.LockInfo.new(SESSION_A, lock.LockMode.CHECKOUT, env.clock)
            (env.root / ".lock").write_bytes(lock.encode_lock(info))
            self._assert_untouched(env, SESSION_B, model.ReadOnlyCode.RESERVED)

    def test_requested(self) -> None:
        """RF-002-13: a petición del usuario: nada cambia en la carpeta."""
        with project_tmp() as tmp:
            env = Env(tmp)
            env.created.project.close()
            self._assert_untouched(env, SESSION_B, model.ReadOnlyCode.REQUESTED, want_write=False)

    def test_newer_schema(self) -> None:
        """RF-002-13, RF-002-22: esquema posterior al de esta versión: nada cambia."""
        with project_tmp() as tmp:
            env = Env(tmp)
            env.created.project.close()
            with gpkg.GpkgConnection.open_write(env.root / "project.gpkg") as db:
                with db.transaction() as conn:
                    conn.execute("UPDATE gb_project SET schema_version = 2")
            path = env.root / "manifest.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["schema_version"] = 2
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self._assert_untouched(env, SESSION_B, model.ReadOnlyCode.SCHEMA_NEWER)

    def test_not_migrated(self) -> None:
        """RF-002-13, RF-002-20: esquema anterior sin migrar (simulado: esta versión
        soportaría el 2): nada cambia."""
        with project_tmp() as tmp:
            env = Env(tmp)
            env.created.project.close()
            with mock.patch.object(open_mod, "SCHEMA_VERSION", 2):
                self._assert_untouched(env, SESSION_B, model.ReadOnlyCode.NOT_MIGRATED)

    def test_wal_busy(self) -> None:
        """RF-002-13, RF-002-17: la base en WAL abierta por otro programa (QGIS editando):
        solo lectura indicando qué cerrar, y la lista de ficheros (también ``-wal`` y
        ``-shm``), sus sha256 y sus fechas no cambian."""
        with project_tmp() as tmp:
            env = Env(tmp)
            env.created.project.close()
            foreign = sqlite3.connect(env.root / "project.gpkg", isolation_level=None)
            try:
                foreign.execute(WAL_PRAGMA)
                foreign.execute("CREATE TABLE capa_qgis (a TEXT)")
                foreign.execute("INSERT INTO capa_qgis VALUES ('editando')")
                self.assertTrue((env.root / "project.gpkg-wal").exists())
                before = _snapshot(env.root)
                result = env.open(SESSION_B)
                self.assertEqual(result.project.read_only_reason, model.ReadOnlyCode.WAL_BUSY)
                self.assertIn("cierre", result.status.message)
                with result.project.read() as conn:
                    row = conn.execute("SELECT a FROM capa_qgis").fetchone()
                self.assertEqual(row[0], "editando")
                result.project.close()
                self.assertEqual(_snapshot(env.root), before)
            finally:
                foreign.close()

    def test_wal_left_closed_read_on_request(self) -> None:
        """RF-002-13: una base que QGIS dejó en WAL (ya cerrado), abierta en solo lectura,
        se lee en una copia privada: no aparecen ``-wal`` ni ``-shm`` en el proyecto."""
        with project_tmp() as tmp:
            env = Env(tmp)
            env.created.project.close()
            conn = sqlite3.connect(env.root / "project.gpkg", isolation_level=None)
            try:
                conn.execute(WAL_PRAGMA)
            finally:
                conn.close()
            self.assertEqual(gpkg.read_header(env.root / "project.gpkg").journal, "wal")
            self._assert_untouched(env, SESSION_B, model.ReadOnlyCode.REQUESTED, want_write=False)
            self.assertFalse((env.root / "project.gpkg-wal").exists())
            self.assertFalse((env.root / "project.gpkg-shm").exists())

    def test_after_losing_the_lock(self) -> None:
        """RF-002-12, RF-002-13: tras perder el cerrojo (otra sesión lo forzó), leer y
        cerrar no cambian nada."""
        with project_tmp() as tmp:
            env = Env(tmp)
            project = env.created.project
            env.clock.advance(minutes=31)
            seen = lock.inspect(env.root, SESSION_B, clock=env.clock, pid_alive=env.pids)
            lock.force(env.root, SESSION_B, lock.LockMode.LOCAL, seen.holder, clock=env.clock,
                       pid_alive=env.pids)
            with self.assertLogs("geoblender.core.project", "WARNING"):
                self.assertEqual(project.heartbeat(), lock.LockCheck.LOST)
            self.assertEqual(project.read_only_reason, model.ReadOnlyCode.LOCK_LOST)
            before = _snapshot(env.root)
            with project.read() as conn:
                schema.read_project(conn)
            project.close()
            self.assertEqual(_snapshot(env.root), before)


if __name__ == "__main__":
    unittest.main()
