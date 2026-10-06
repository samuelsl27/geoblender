# SPDX-License-Identifier: GPL-3.0-or-later
"""Modo red y caché del proyecto (spec 002, T30; RF-002-30, RF-002-13; plan 002 §5.2,
«Caché del proyecto», y §5.4, «Red»; ADR-0010).

Un proyecto abierto en escritura desde una carpeta de red dice que está en modo «red» y
su caché (``Project.cache_dir()``, la única de todas las specs) va al disco local del
equipo, ``cache/<uid>/`` de los datos de usuario: nunca se crea ``cache/`` en la carpeta
de red. En solo lectura, tampoco (no se escribe nada en el proyecto). Solo en disco local
y en escritura la caché es ``<proyecto>/cache/``.

La red se **simula** inyectando la detección de la unidad (``GetDriveTypeW`` =
``DRIVE_REMOTE``), como hace ``core.paths.is_network_path``: las pruebas no tocan la red.
"""

import os
import unittest
from pathlib import Path

from tests.support.core_fixtures import FakeClock, FakePids, make_session, make_settings, project_tmp
from tests.support.package import import_geoblender

create = import_geoblender("core.project.create")
open_mod = import_geoblender("core.project.open")
model = import_geoblender("core.project.model")
lock = import_geoblender("core.project.lock")
paths = import_geoblender("core.paths")
userdata_mod = import_geoblender("core.userdata")

SESSION_A = make_session()
SESSION_B = make_session(
    session_uid="00000000-0000-4000-8000-000000000002", host="PC-PRUEBA-B", user="otra", pid=777
)


def remote_drive(root: str) -> int:
    """Detección de unidad simulada: toda unidad es de red (``DRIVE_REMOTE``)."""
    return paths.DRIVE_REMOTE


def fixed_drive(root: str) -> int:
    """Detección de unidad simulada: toda unidad es un disco fijo (``DRIVE_FIXED``)."""
    return 3


def tree(root: Path) -> list[str]:
    """Todo lo que hay en la carpeta del proyecto (rutas relativas con «/»)."""
    found: list[str] = []
    for folder, dirs, files in os.walk(root):
        base = Path(folder).relative_to(root)
        found.extend((base / name).as_posix() for name in (*dirs, *files))
    return sorted(found)


class Env:
    """Un proyecto creado por la sesión A en una carpeta temporal que la detección de
    unidad simulada da por local (``fixed_drive``) o de red (``remote_drive``)."""

    def __init__(self, tmp: Path, drive_type=remote_drive) -> None:
        self.parent = tmp / "red"
        self.parent.mkdir()
        self.userdata = userdata_mod.UserData(tmp / "datos_usuario")
        self.clock = FakeClock()
        self.pids = FakePids({SESSION_A.pid, SESSION_B.pid})
        self.drive_type = drive_type
        self.created = create.create_project(
            self.parent, make_settings(), SESSION_A, self.userdata, clock=self.clock,
            drive_type=drive_type,
        )
        self.root = self.created.root
        self.uid = self.created.record.uid

    def open(self, session, **kwargs):
        kwargs.setdefault("clock", self.clock)
        kwargs.setdefault("pid_alive", self.pids)
        kwargs.setdefault("drive_type", self.drive_type)
        return open_mod.open_project(self.root, session, self.userdata, **kwargs)

    def use_cache(self, project, job: str = "trabajo-1") -> Path:
        """Lo que haría una spec que usa la caché (la 004 con sus trabajos, la 006 con sus
        vistas): crear una carpeta y un fichero dentro de ``cache_dir()``."""
        jobs = project.cache_dir() / "jobs" / job
        jobs.mkdir(parents=True)
        (jobs / "resultado.npz").write_bytes(b"datos regenerables")
        return jobs


class NetworkModeTest(unittest.TestCase):
    def test_network_write_mode_and_cache_on_this_computer(self) -> None:
        """RF-002-30: creado y abierto en escritura desde una carpeta de red (detección
        simulada), el proyecto está en modo «red» (cerrojo ``network``) y su caché es
        ``cache/<uid>/`` de los datos de usuario; usarla no crea ``cache/`` en el
        proyecto."""
        with project_tmp() as tmp:
            env = Env(tmp)
            created = env.created.project
            self.assertTrue(env.created.network)
            self.assertTrue(created.is_network)
            self.assertEqual(created.mode, model.OpenMode.WRITE_NETWORK)
            self.assertIn("red", created.status.message)
            self.assertEqual(lock.read_holder(env.root).mode, lock.LockMode.NETWORK)
            self.assertEqual(created.cache_dir(), env.userdata.cache_dir(env.uid))
            used = env.use_cache(created)
            self.assertTrue(paths.is_within(used, env.userdata.root))
            self.assertNotIn("cache", tree(env.root))
            created.close()
            result = env.open(SESSION_B)
            opened = result.project
            try:
                self.assertEqual(opened.mode, model.OpenMode.WRITE_NETWORK)
                self.assertEqual(lock.read_holder(env.root).mode, lock.LockMode.NETWORK)
                self.assertEqual(opened.cache_dir(), env.userdata.cache_dir(env.uid))
                env.use_cache(opened, "trabajo-2")
                with opened.write_transaction() as conn:
                    conn.execute("SELECT 1")
            finally:
                opened.close()
            self.assertNotIn("cache", tree(env.root))

    def test_network_read_only_cache_on_this_computer(self) -> None:
        """RF-002-30, RF-002-13: en red y en solo lectura (bloqueado por otra sesión o a
        petición), la caché también va a los datos de usuario y nada aparece en la
        carpeta del proyecto."""
        with project_tmp() as tmp:
            env = Env(tmp)
            holder = env.created.project
            locked = env.open(SESSION_B).project
            requested = env.open(SESSION_B, want_write=False).project
            try:
                for reader, reason in ((locked, model.ReadOnlyCode.LOCKED),
                                       (requested, model.ReadOnlyCode.REQUESTED)):
                    with self.subTest(motivo=reason.value):
                        self.assertEqual(reader.read_only_reason, reason)
                        self.assertTrue(reader.is_network)
                        self.assertEqual(reader.cache_dir(), env.userdata.cache_dir(env.uid))
                before = tree(env.root)
                env.use_cache(locked)
                self.assertEqual(tree(env.root), before)
                self.assertNotIn("cache", before)
            finally:
                requested.close()
                locked.close()
                holder.close()

    def test_lost_lock_moves_cache_to_this_computer(self) -> None:
        """RF-002-30, RF-002-12: si un proyecto local en escritura pierde el cerrojo pasa
        a solo lectura, y desde entonces su caché es la de los datos de usuario (no se
        escribe más en la carpeta del proyecto)."""
        with project_tmp() as tmp:
            env = Env(tmp, drive_type=fixed_drive)
            created = env.created.project
            self.assertEqual(created.cache_dir(), env.root / "cache")
            env.clock.advance(minutes=31)
            seen = lock.inspect(env.root, SESSION_B, clock=env.clock, pid_alive=env.pids)
            lock.force(env.root, SESSION_B, lock.LockMode.LOCAL, seen.holder, clock=env.clock,
                       pid_alive=env.pids)
            with self.assertLogs("geoblender.core.project", "WARNING"):
                self.assertIs(created.heartbeat(), lock.LockCheck.LOST)
            self.assertEqual(created.read_only_reason, model.ReadOnlyCode.LOCK_LOST)
            self.assertEqual(created.cache_dir(), env.userdata.cache_dir(env.uid))
            created.close()


class LocalModeTest(unittest.TestCase):
    def test_local_write_cache_in_project(self) -> None:
        """RF-002-30 (plan 002 §5.2): en disco local (detección simulada) y escritura,
        modo «escritura local» y la caché es ``<proyecto>/cache/``; en solo lectura, la
        de los datos de usuario."""
        with project_tmp() as tmp:
            env = Env(tmp, drive_type=fixed_drive)
            created = env.created.project
            self.assertFalse(created.is_network)
            self.assertEqual(created.mode, model.OpenMode.WRITE_LOCAL)
            self.assertNotIn("red", created.status.message)
            self.assertEqual(lock.read_holder(env.root).mode, lock.LockMode.LOCAL)
            self.assertEqual(created.cache_dir(), env.root / "cache")
            env.use_cache(created)
            self.assertIn("cache/jobs/trabajo-1/resultado.npz", tree(env.root))
            reader = env.open(SESSION_B).project
            self.assertEqual(reader.cache_dir(), env.userdata.cache_dir(env.uid))
            reader.close()
            created.close()

    def test_inspection_sees_network(self) -> None:
        """RF-002-30: la inspección (sin escribir) dice si la carpeta es de red, con la
        detección de la unidad inyectada."""
        with project_tmp() as tmp:
            env = Env(tmp, drive_type=fixed_drive)
            env.created.project.close()
            local = open_mod.inspect_project(env.root, SESSION_B, env.userdata,
                                             drive_type=fixed_drive)
            remote = open_mod.inspect_project(env.root, SESSION_B, env.userdata,
                                              drive_type=remote_drive)
            self.assertFalse(local.network)
            self.assertTrue(remote.network)


if __name__ == "__main__":
    unittest.main()
