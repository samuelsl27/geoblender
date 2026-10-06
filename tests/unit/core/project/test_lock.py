# SPDX-License-Identifier: GPL-3.0-or-later
"""Cerrojo de un solo escritor, ``.lock`` (spec 002, T13; RF-002-04, RF-002-09; plan 002
§5.4; formato-proyecto §5.2).

Un proyecto lo escribe una sola sesión: la que crea ``.lock`` en exclusiva
(``O_CREAT | O_EXCL``, atómico también sobre SMB), con su sesión, equipo, usuario,
proceso, hora y modo. Un cerrojo del mismo equipo cuyo proceso ya no está en ejecución
es huérfano (Blender se cerró de golpe) y se sustituye; el de otra sesión viva deja el
proyecto en solo lectura con su equipo, usuario y hora. Un ``.lock`` que existe pero no
se puede leer (vacío, JSON a medias) se relee 3 veces cada 100 ms y, si sigue así, cuenta
como activo de titular desconocido: nunca como libre ni como huérfano. Liberar solo
borra el cerrojo propio.
"""

import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

from tests.support.core_fixtures import FakeClock, FakePids, make_session, project_tmp
from tests.support.package import import_geoblender
from tests.support.repo import ROOT
from tests.support.trees import child_env, child_temp

lock = import_geoblender("core.project.lock")
errors = import_geoblender("core.errors")
paths = import_geoblender("core.paths")
timeutil = import_geoblender("core.timeutil")

SESSION_A = make_session()
SESSION_A2 = make_session(session_uid="00000000-0000-4000-8000-0000000000a2", pid=5151)
SESSION_B = make_session(
    session_uid="00000000-0000-4000-8000-000000000002", host="PC-PRUEBA-B", user="otra", pid=777
)
RACE_ROUNDS = 20

# Proceso hijo que intenta adquirir el cerrojo de cada carpeta a la vez que otro (la
# ronda n empieza a la misma hora en los dos: inicio + n · 50 ms); da su resultado por una
# línea de la salida y sigue vivo (su cerrojo no es huérfano) hasta que la prueba cierra su
# entrada.
RACER = r"""
import json, sys, time
ROUND_S = 0.05
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
from tests.support.package import import_geoblender
lock = import_geoblender("core.project.lock")
errors = import_geoblender("core.errors")
sysinfo = import_geoblender("core.sysinfo")
session = sysinfo.current_session("0.1.0")
start = float(sys.argv[2])
results = []
for index, folder in enumerate(sys.argv[3:]):
    while time.time() < start + index * ROUND_S:
        pass
    try:
        lock.acquire(Path(folder), session, lock.LockMode.LOCAL)
        results.append("won")
    except errors.LockError as exc:
        results.append("lost:" + str(exc.context.get("state")))
print(json.dumps({"session": session.session_uid, "results": results}), flush=True)
sys.stdin.read()
"""


def _write_lock(root: Path, session, *, clock=None, mode="local") -> bytes:
    """Un ``.lock`` de ``session`` escrito como lo escribiría Geoblender."""
    info = lock.LockInfo.new(session, lock.LockMode(mode), clock or FakeClock())
    content = lock.encode_lock(info)
    (root / ".lock").write_bytes(content)
    return content


class AcquireTest(unittest.TestCase):
    def test_acquire_free_marks_session(self) -> None:
        """RF-002-04: con el cerrojo libre se adquiere y queda marcado con sesión,
        equipo, usuario, proceso, hora, versión y modo; sin rutas; con longitud fija."""
        with project_tmp() as tmp:
            clock = FakeClock()
            pids = FakePids()
            self.assertEqual(lock.inspect(tmp, SESSION_A, clock=clock, pid_alive=pids).state,
                             lock.LockState.FREE)
            acquired = lock.acquire(tmp, SESSION_A, lock.LockMode.NETWORK, clock=clock,
                                    pid_alive=pids)
            self.assertIsNone(acquired.replaced)
            raw = (tmp / ".lock").read_bytes()
            self.assertEqual(len(raw), lock.LOCK_SIZE)
            data = json.loads(raw.decode("utf-8"))
            self.assertEqual(
                data,
                {
                    "session_uid": SESSION_A.session_uid,
                    "host": "PC-PRUEBA-A",
                    "user": "prueba",
                    "pid": 4242,
                    "started_at": "2026-10-05T08:12:44.000Z",
                    "heartbeat_at": "2026-10-05T08:12:44.000Z",
                    "geoblender_version": "0.1.0",
                    "mode": "network",
                },
            )
            self.assertEqual(paths.find_absolute_paths(data), [])
            status = lock.inspect(tmp, SESSION_A, clock=clock, pid_alive=pids)
            self.assertEqual(status.state, lock.LockState.OURS)
            self.assertEqual(status.holder, acquired.info)
            again = lock.acquire(tmp, SESSION_A, lock.LockMode.NETWORK, clock=clock,
                                 pid_alive=pids)
            self.assertEqual(again.info, acquired.info)
            self.assertEqual((tmp / ".lock").read_bytes(), raw)

    def test_orphan_same_host_is_replaced(self) -> None:
        """RF-002-04: el cerrojo de un proceso del mismo equipo que ya no está en
        ejecución es huérfano y se sustituye; el anterior se devuelve para registrarlo.
        Si ese PID vuelve a estar vivo (reutilizado), cuenta como activo."""
        with project_tmp() as tmp:
            clock = FakeClock()
            _write_lock(tmp, SESSION_A2)
            reused = FakePids({SESSION_A2.pid})
            self.assertEqual(lock.inspect(tmp, SESSION_A, clock=clock, pid_alive=reused).state,
                             lock.LockState.ACTIVE)
            dead = FakePids()
            status = lock.inspect(tmp, SESSION_A, clock=clock, pid_alive=dead)
            self.assertEqual(status.state, lock.LockState.ORPHAN)
            self.assertEqual(status.holder.session_uid, SESSION_A2.session_uid)
            acquired = lock.acquire(tmp, SESSION_A, lock.LockMode.LOCAL, clock=clock,
                                    pid_alive=dead)
            self.assertEqual(acquired.replaced.session_uid, SESSION_A2.session_uid)
            self.assertEqual(lock.read_holder(tmp, clock=clock).session_uid, SESSION_A.session_uid)

    def test_other_host_is_active(self) -> None:
        """RF-002-09: el cerrojo de otra sesión de otro equipo es ACTIVE con su equipo,
        usuario y hora de inicio, aunque su PID no exista en este equipo; adquirir falla
        con esos datos y no cambia el fichero."""
        with project_tmp() as tmp:
            clock = FakeClock()
            content = _write_lock(tmp, SESSION_B)
            clock.advance(minutes=5)
            status = lock.inspect(tmp, SESSION_A, clock=clock, pid_alive=FakePids())
            self.assertEqual(status.state, lock.LockState.ACTIVE)
            self.assertEqual(status.holder.host, "PC-PRUEBA-B")
            self.assertEqual(status.holder.user, "otra")
            self.assertEqual(status.holder.started_at, "2026-10-05T08:12:44.000Z")
            text = status.describe()
            for expected in ("PC-PRUEBA-B", "otra", "05/10/2026"):
                self.assertIn(expected, text)
            with self.assertRaises(errors.LockError) as caught:
                lock.acquire(tmp, SESSION_A, lock.LockMode.LOCAL, clock=clock,
                             pid_alive=FakePids())
            self.assertEqual(caught.exception.context["state"], "active")
            self.assertIn("PC-PRUEBA-B", str(caught.exception))
            self.assertIn("otra", str(caught.exception))
            self.assertEqual((tmp / ".lock").read_bytes(), content)

    def test_unreadable_lock_is_active_unknown(self) -> None:
        """RF-002-09: un ``.lock`` vacío, con JSON a medias o sin los campos se relee 3
        veces cada 100 ms y, si sigue así, es ACTIVE de titular desconocido (nunca FREE
        ni ORPHAN, aunque nadie esté vivo); adquirir falla y no lo toca."""
        good = lock.encode_lock(lock.LockInfo.new(SESSION_A2, lock.LockMode.LOCAL, FakeClock()))
        for name, content in (
            ("vacío", b""),
            ("a medias", good[:40]),
            ("sin campos", b'{"session_uid": "x"}'),
            ("binario", b"\xff\xfe\x00"),
        ):
            with self.subTest(lock=name), project_tmp() as tmp:
                (tmp / ".lock").write_bytes(content)
                clock = FakeClock()
                start = clock.monotonic()
                status = lock.inspect(tmp, SESSION_A, clock=clock, pid_alive=FakePids())
                self.assertEqual(status.state, lock.LockState.ACTIVE)
                self.assertIsNone(status.holder)
                self.assertAlmostEqual(clock.monotonic() - start, 0.3)
                self.assertIn("desconocido", status.describe())
                with self.assertRaises(errors.LockError):
                    lock.acquire(tmp, SESSION_A, lock.LockMode.LOCAL, clock=clock,
                                 pid_alive=FakePids())
                self.assertEqual((tmp / ".lock").read_bytes(), content)

    def test_lock_written_during_rereads(self) -> None:
        """RF-002-09: un ``.lock`` a medio escribir que se completa durante las
        relecturas se lee con su titular."""
        with project_tmp() as tmp:
            target = tmp / ".lock"
            target.write_bytes(b"")
            full = lock.encode_lock(lock.LockInfo.new(SESSION_B, lock.LockMode.LOCAL, FakeClock()))

            class CompletingClock(FakeClock):
                def sleep(self, seconds: float) -> None:
                    super().sleep(seconds)
                    target.write_bytes(full)

            status = lock.inspect(tmp, SESSION_A, clock=CompletingClock(), pid_alive=FakePids())
            self.assertEqual(status.state, lock.LockState.ACTIVE)
            self.assertEqual(status.holder.session_uid, SESSION_B.session_uid)

    def test_two_processes_one_winner(self) -> None:
        """RF-002-04, RF-002-09: dos procesos que adquieren a la vez el cerrojo de la
        misma carpeta: gana exactamente uno (20 repeticiones) y el fichero es suyo."""
        with project_tmp() as tmp, child_temp() as temp:
            folders = []
            for index in range(RACE_ROUNDS):
                folder = tmp / f"p{index:02d}.gbproj"
                folder.mkdir()
                folders.append(str(folder))
            start = time.time() + 1.5
            racers = [
                subprocess.Popen(
                    [sys.executable, "-B", "-s", "-c", RACER, str(ROOT), repr(start), *folders],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=child_env(None, temp),
                    text=True,
                )
                for _ in range(2)
            ]
            try:
                reports = []
                for racer in racers:
                    line = racer.stdout.readline()
                    self.assertTrue(line, racer.stderr.read() if racer.poll() is not None else "")
                    reports.append(json.loads(line))
                for index, folder in enumerate(folders):
                    outcomes = [report["results"][index] for report in reports]
                    with self.subTest(ronda=index, resultados=outcomes):
                        self.assertEqual(outcomes.count("won"), 1)
                        self.assertEqual(outcomes.count("lost:active"), 1)
                        winner = reports[outcomes.index("won")]["session"]
                        holder = json.loads((Path(folder) / ".lock").read_text(encoding="utf-8"))
                        self.assertEqual(holder["session_uid"], winner)
            finally:
                for racer in racers:
                    try:
                        racer.communicate(timeout=30)
                    except subprocess.TimeoutExpired:
                        racer.kill()
                        racer.communicate()


class ReleaseTest(unittest.TestCase):
    def test_release_only_own_lock(self) -> None:
        """RF-002-04, RF-002-09: liberar borra el cerrojo propio y nunca uno ajeno (ni
        uno ilegible); sin cerrojo no hace nada."""
        with project_tmp() as tmp:
            clock = FakeClock()
            self.assertFalse(lock.release(tmp, SESSION_A, clock=clock))
            content = _write_lock(tmp, SESSION_B)
            self.assertFalse(lock.release(tmp, SESSION_A, clock=clock))
            self.assertEqual((tmp / ".lock").read_bytes(), content)
            (tmp / ".lock").write_bytes(b"{")
            self.assertFalse(lock.release(tmp, SESSION_A, clock=clock))
            self.assertTrue((tmp / ".lock").exists())
            (tmp / ".lock").unlink()
            lock.acquire(tmp, SESSION_A, lock.LockMode.LOCAL, clock=clock, pid_alive=FakePids())
            self.assertTrue(lock.release(tmp, SESSION_A, clock=clock))
            self.assertFalse((tmp / ".lock").exists())

    def test_times_are_utc(self) -> None:
        """RF-002-04: las horas del cerrojo son UTC con milisegundos y «Z»."""
        info = lock.LockInfo.new(SESSION_A, lock.LockMode.LOCAL, FakeClock())
        self.assertEqual(timeutil.parse_utc(info.started_at), FakeClock().now())


if __name__ == "__main__":
    unittest.main()
