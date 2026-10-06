# SPDX-License-Identifier: GPL-3.0-or-later
"""Cerrojo de un solo escritor, ``.lock`` (spec 002, T13 y T14; RF-002-04, RF-002-09 a
RF-002-12; plan 002 §5.4; formato-proyecto §5.2).

Un proyecto lo escribe una sola sesión: la que crea ``.lock`` en exclusiva
(``O_CREAT | O_EXCL``, atómico también sobre SMB), con su sesión, equipo, usuario,
proceso, hora y modo. Un cerrojo del mismo equipo cuyo proceso ya no está en ejecución
es huérfano (Blender se cerró de golpe) y se sustituye; el de otra sesión viva deja el
proyecto en solo lectura con su equipo, usuario y hora. Un ``.lock`` que existe pero no
se puede leer (vacío, JSON a medias) se relee 3 veces cada 100 ms y, si sigue así, cuenta
como activo de titular desconocido: nunca como libre ni como huérfano. Liberar solo
borra el cerrojo propio.

Un cerrojo sin renovar más que el umbral (30 min por defecto) o que es la reserva de una
copia local se puede forzar, con aviso y solo si sigue siendo el que vio el usuario. La
sesión que lo tiene lo renueva cada 5 min reescribiéndolo en el sitio, sin truncarlo antes
(otro equipo nunca lo ve vacío), y si otra lo forzó, la comprobación dice LOST.
"""

import json
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

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


class StaleAndForceTest(unittest.TestCase):
    def test_stale_threshold(self) -> None:
        """RF-002-10: el cerrojo de otra sesión sin renovar desde hace 29 min no se ofrece
        forzar y desde hace 31 min sí (umbral de 30 min por defecto, configurable: con 10
        min, a los 11); el aviso dice quién lo tenía, desde cuándo y qué se perderá."""
        with project_tmp() as tmp:
            clock = FakeClock()
            _write_lock(tmp, SESSION_B)
            clock.advance(minutes=29)
            status = lock.inspect(tmp, SESSION_A, clock=clock, pid_alive=FakePids())
            self.assertEqual(status.state, lock.LockState.ACTIVE)
            self.assertFalse(status.can_force)
            clock.advance(minutes=2)
            status = lock.inspect(tmp, SESSION_A, clock=clock, pid_alive=FakePids())
            self.assertEqual(status.state, lock.LockState.STALE)
            self.assertTrue(status.can_force)
            warning = status.force_warning()
            for expected in ("otra", "PC-PRUEBA-B", "05/10/2026", "31 min", "perder"):
                self.assertIn(expected, warning)
            fresh = FakeClock()
            _write_lock(tmp, SESSION_B, clock=fresh)
            fresh.advance(minutes=11)
            self.assertEqual(
                lock.inspect(
                    tmp, SESSION_A, clock=fresh, pid_alive=FakePids(), stale_minutes=10
                ).state,
                lock.LockState.STALE,
            )
            self.assertEqual(
                lock.inspect(tmp, SESSION_A, clock=fresh, pid_alive=FakePids()).state,
                lock.LockState.ACTIVE,
            )

    def test_stale_same_host_with_reused_pid(self) -> None:
        """RF-002-10: un cerrojo del mismo equipo con el PID reutilizado por otro
        programa cuenta como activo hasta que caduca su marca."""
        with project_tmp() as tmp:
            clock = FakeClock()
            _write_lock(tmp, SESSION_A2)
            alive = FakePids({SESSION_A2.pid})
            clock.advance(minutes=29)
            self.assertEqual(
                lock.inspect(tmp, SESSION_A, clock=clock, pid_alive=alive).state,
                lock.LockState.ACTIVE,
            )
            clock.advance(minutes=2)
            self.assertEqual(
                lock.inspect(tmp, SESSION_A, clock=clock, pid_alive=alive).state,
                lock.LockState.STALE,
            )

    def test_force_requires_seen_holder(self) -> None:
        """RF-002-10: forzar exige el titular que vio el usuario: si el cerrojo cambió
        entre el aviso y la confirmación (p. ej. su sesión lo renovó), no se fuerza; uno
        activo tampoco. Con el titular visto, se sustituye y se devuelve el anterior."""
        with project_tmp() as tmp:
            clock = FakeClock()
            _write_lock(tmp, SESSION_B)
            clock.advance(minutes=31)
            seen = lock.inspect(tmp, SESSION_A, clock=clock, pid_alive=FakePids())
            self.assertEqual(seen.state, lock.LockState.STALE)
            renewed = _write_lock(tmp, SESSION_B, clock=clock)
            with self.assertRaises(errors.LockError) as caught:
                lock.force(
                    tmp, SESSION_A, lock.LockMode.LOCAL, seen.holder, clock=clock,
                    pid_alive=FakePids(),
                )
            self.assertEqual(caught.exception.code, "core.lock_not_forceable")
            self.assertEqual((tmp / ".lock").read_bytes(), renewed)
            clock.advance(minutes=31)
            seen = lock.inspect(tmp, SESSION_A, clock=clock, pid_alive=FakePids())
            other = lock.LockInfo.new(SESSION_A2, lock.LockMode.LOCAL, clock)
            with self.assertRaises(errors.LockError) as caught:
                lock.force(
                    tmp, SESSION_A, lock.LockMode.LOCAL, other, clock=clock,
                    pid_alive=FakePids(),
                )
            self.assertEqual(caught.exception.code, "core.lock_changed")
            self.assertEqual((tmp / ".lock").read_bytes(), renewed)
            acquired = lock.force(
                tmp, SESSION_A, lock.LockMode.LOCAL, seen.holder, clock=clock,
                pid_alive=FakePids(),
            )
            self.assertEqual(acquired.replaced, seen.holder)
            holder = lock.read_holder(tmp, clock=clock)
            self.assertEqual(holder.session_uid, SESSION_A.session_uid)

    def test_checkout_reservation_is_forceable(self) -> None:
        """RF-002-10: la reserva de una copia local es RESERVED aunque sea reciente o su
        proceso haya terminado (nunca huérfana): no se adquiere sin más, se ofrece forzar
        avisando de que la copia ya no se podrá publicar, y forzarla funciona."""
        with project_tmp() as tmp:
            clock = FakeClock()
            _write_lock(tmp, SESSION_A2, mode="checkout")
            clock.advance(minutes=1)
            status = lock.inspect(tmp, SESSION_A, clock=clock, pid_alive=FakePids())
            self.assertEqual(status.state, lock.LockState.RESERVED)
            self.assertTrue(status.can_force)
            self.assertIn("copia local", status.force_warning())
            self.assertIn("publicar", status.force_warning())
            with self.assertRaises(errors.LockError) as caught:
                lock.acquire(
                    tmp, SESSION_A, lock.LockMode.LOCAL, clock=clock, pid_alive=FakePids()
                )
            self.assertEqual(caught.exception.context["state"], "reserved")
            acquired = lock.force(
                tmp, SESSION_A, lock.LockMode.LOCAL, status.holder, clock=clock,
                pid_alive=FakePids(),
            )
            self.assertEqual(acquired.replaced.mode, lock.LockMode.CHECKOUT)


class HeartbeatTest(unittest.TestCase):
    def test_heartbeat_renews_in_place(self) -> None:
        """RF-002-11: la marca de actividad comprueba que el cerrojo sigue siendo de esta
        sesión y lo renueva en el mismo fichero (misma longitud, mismo inicio)."""
        with project_tmp() as tmp:
            clock = FakeClock()
            lock.acquire(tmp, SESSION_A, lock.LockMode.LOCAL, clock=clock, pid_alive=FakePids())
            before = (tmp / ".lock").stat()
            clock.advance(minutes=5)
            self.assertEqual(lock.heartbeat(tmp, SESSION_A, clock=clock), lock.LockCheck.OK)
            holder = lock.read_holder(tmp, clock=clock)
            self.assertEqual(holder.heartbeat_at, "2026-10-05T08:17:44.000Z")
            self.assertEqual(holder.started_at, "2026-10-05T08:12:44.000Z")
            after = (tmp / ".lock").stat()
            self.assertEqual(after.st_size, lock.LOCK_SIZE)
            self.assertEqual(after.st_ino, before.st_ino)
            clock.advance(minutes=29)
            self.assertEqual(
                lock.inspect(tmp, SESSION_B, clock=clock, pid_alive=FakePids()).state,
                lock.LockState.ACTIVE,
            )

    def test_heartbeat_lost(self) -> None:
        """RF-002-11, RF-002-12: si otra sesión forzó el cerrojo, o ya no está, o no se
        puede leer, la comprobación devuelve LOST y no escribe nada."""
        with project_tmp() as tmp:
            clock = FakeClock()
            lock.acquire(tmp, SESSION_A, lock.LockMode.LOCAL, clock=clock, pid_alive=FakePids())
            clock.advance(minutes=31)
            seen = lock.inspect(tmp, SESSION_B, clock=clock, pid_alive=FakePids())
            lock.force(
                tmp, SESSION_B, lock.LockMode.LOCAL, seen.holder, clock=clock,
                pid_alive=FakePids(),
            )
            forced = (tmp / ".lock").read_bytes()
            self.assertEqual(lock.heartbeat(tmp, SESSION_A, clock=clock), lock.LockCheck.LOST)
            self.assertEqual((tmp / ".lock").read_bytes(), forced)
            (tmp / ".lock").write_bytes(b"{ a medias")
            self.assertEqual(lock.heartbeat(tmp, SESSION_A, clock=clock), lock.LockCheck.LOST)
            self.assertEqual((tmp / ".lock").read_bytes(), b"{ a medias")
            (tmp / ".lock").unlink()
            self.assertEqual(lock.heartbeat(tmp, SESSION_A, clock=clock), lock.LockCheck.LOST)
            self.assertFalse((tmp / ".lock").exists())

    def test_heartbeat_io_error(self) -> None:
        """RF-002-12: si renovar falla por un error de disco o de red, la comprobación
        devuelve FAILED (no se sabe si el cerrojo sigue siendo nuestro)."""
        with project_tmp() as tmp:
            clock = FakeClock()
            lock.acquire(tmp, SESSION_A, lock.LockMode.LOCAL, clock=clock, pid_alive=FakePids())
            with mock.patch.object(lock, "_open_for_update", side_effect=OSError(64, "red")):
                self.assertEqual(
                    lock.heartbeat(tmp, SESSION_A, clock=clock), lock.LockCheck.FAILED
                )

    def test_concurrent_reader_never_sees_empty(self) -> None:
        """RF-002-11: un lector que lee el cerrojo en bucle mientras se renueva 500 veces
        nunca lo ve vacío ni a medias (la marca se reescribe sin truncar antes)."""
        with project_tmp() as tmp:
            clock = FakeClock()
            lock.acquire(tmp, SESSION_A, lock.LockMode.LOCAL, clock=clock, pid_alive=FakePids())
            target = tmp / ".lock"
            stop = threading.Event()
            seen = {"reads": 0, "bad": []}

            def reader() -> None:
                while not stop.is_set():
                    with target.open("rb") as handle:
                        content = handle.read()
                    seen["reads"] += 1
                    try:
                        if lock.decode_lock(content).session_uid != SESSION_A.session_uid:
                            seen["bad"].append(content[:60])
                    except ValueError:
                        seen["bad"].append(content[:60])

            thread = threading.Thread(target=reader)
            thread.start()
            try:
                for _ in range(500):
                    clock.advance(seconds=1)
                    self.assertEqual(
                        lock.heartbeat(tmp, SESSION_A, clock=clock), lock.LockCheck.OK
                    )
            finally:
                stop.set()
                thread.join()
            self.assertGreater(seen["reads"], 0)
            self.assertEqual(seen["bad"], [])

if __name__ == "__main__":
    unittest.main()
