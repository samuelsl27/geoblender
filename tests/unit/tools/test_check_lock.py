# SPDX-License-Identifier: GPL-3.0-or-later
"""Un solo ``tools/check.py`` a la vez en el equipo (spec 006, T46; RNF-001-01, RNF-007-01;
RF-004-28): ``gbtools.check_lock`` y su uso en ``check.main``.

- RNF-001-01, RNF-007-01 (spec 006, T46): dos ``check.py`` a la vez (de la carpeta del
  proyecto y de un *worktree*, o de dos sesiones) compiten por los procesadores y sus
  pruebas de tiempo fallan. ``check.py`` toma al empezar un cerrojo del equipo: un
  fichero de ``%LOCALAPPDATA%\\Geoblender\\`` (``GEOBLENDER_CHECK_LOCK`` lo cambia de
  sitio) con un bloqueo del sistema (``msvcrt.locking``), que se suelta solo si el proceso
  muere, sin ficheros que haya que borrar a mano. Si otro lo tiene, escribe una sola vez
  en español que espera, con el pid y la carpeta del que lo tiene (que este guarda en el
  fichero), y espera; el tiempo que informa empieza al tomarlo. Las órdenes que lanza
  llevan ``GEOBLENDER_CHECK_LOCK_HELD`` con su pid: un ``check.py`` lanzado desde ellas no
  espera a su padre. Si el cerrojo no se puede usar, un aviso, y la comprobación sigue.

Las pruebas usan cerrojos en carpetas temporales, nunca el de ``%LOCALAPPDATA%``; el otro
``check.py`` es un proceso de Python que toma el cerrojo con ``gbtools.check_lock``.
"""

import inspect
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock

from tests.support.check_cli import FakeRunner, run_check
from tests.support.repo import ROOT, tools_on_path

tools_on_path()

import check  # noqa: E402
from gbtools import check_lock, layout  # noqa: E402

TOOLS = ROOT / "tools"
DEADLINE_S = 15.0  # lo más que se espera a un proceso o a un cerrojo
HOLD_S = 1.0  # lo que el otro check.py simulado tiene el cerrojo en la prueba de check.main
# El otro check.py: toma el cerrojo, dice «TOMADO» y lo tiene HOLD_S segundos (o hasta que
# se le cierra la entrada, con «-»), y lo suelta.
HOLDER = (
    "import sys, time\n"
    "sys.dont_write_bytecode = True\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "from pathlib import Path\n"
    "from gbtools import check_lock\n"
    "lock = check_lock.CheckLock(Path(sys.argv[2]), sys.argv[3])\n"
    "lock.acquire()\n"
    "print('TOMADO', flush=True)\n"
    "if sys.argv[4] == '-':\n"
    "    sys.stdin.read()\n"
    "else:\n"
    "    time.sleep(float(sys.argv[4]))\n"
    "lock.release()\n"
)


class _Stop(Exception):
    """Para la espera de una prueba que no debe esperar."""


def _never(_seconds: float) -> None:
    raise _Stop("esperó")


def _environ() -> dict[str, str]:
    """El entorno del proceso sin ``GEOBLENDER_CHECK_LOCK_HELD`` (dentro de
    ``tools/check.py``, las pruebas lo heredan de él)."""
    return {k: v for k, v in os.environ.items() if k != check_lock.ENV_HELD}


class _Holder:
    """Otro proceso que tiene el cerrojo ``path`` (como otro ``check.py``)."""

    def __init__(self, path: Path, folder: str, hold: str = "-") -> None:
        self.folder = folder
        self.process = subprocess.Popen(
            [sys.executable, "-B", "-s", "-c", HOLDER, str(TOOLS), str(path), folder, hold],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", env=_environ(),
        )
        line = self.process.stdout.readline().strip()
        if line != "TOMADO":
            self.process.kill()
            raise AssertionError(f"el otro proceso no tomó el cerrojo: «{line}» "
                                 f"{self.process.stderr.read()}")

    def close(self) -> int:
        """Lo deja terminar (si espera a la entrada, se la cierra) y da su código."""
        self.process.stdin.close()
        try:
            return self.process.wait(DEADLINE_S)
        finally:
            self.process.stdout.close()
            self.process.stderr.close()

    def kill(self) -> None:
        """Lo mata (sin que suelte el cerrojo), si sigue vivo, y cierra sus tuberías."""
        self.process.kill()
        self.process.wait(DEADLINE_S)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()


class _Polls:
    """La espera de ``acquire`` (``sleep``): cuenta las vueltas, llama a ``action`` en la
    vuelta ``at`` y, si pasan ``limit``, para la prueba."""

    def __init__(self, at: int = 0, action: Callable[[], object] | None = None,
                 limit: int = 1000) -> None:
        self.count = 0
        self.at, self.action, self.limit = at, action, limit

    def __call__(self, seconds: float) -> None:
        self.count += 1
        if self.action is not None and self.count == self.at:
            self.action()
        if self.count > self.limit:
            raise _Stop(f"sigue esperando tras {self.limit} vueltas")
        time.sleep(min(seconds, 0.01))


class LockPathTest(unittest.TestCase):
    def test_default_and_variable(self) -> None:
        """RNF-001-01, RNF-007-01 (spec 006, T46): el cerrojo está en
        ``%LOCALAPPDATA%\\Geoblender\\check.lock``, común a la carpeta del proyecto y a
        todos los *worktrees*; ``GEOBLENDER_CHECK_LOCK`` lo cambia de sitio; sin las dos,
        el motivo, con las dos variables."""
        local = Path(tempfile.gettempdir()) / "perfil-local"
        self.assertEqual(check_lock.lock_path({"LOCALAPPDATA": str(local)}),
                         local.joinpath(*layout.CHECK_LOCK_PARTS))
        # La carpeta de Geoblender en %LOCALAPPDATA%, la misma que la del espejo.
        self.assertEqual(layout.CHECK_LOCK_PARTS,
                         (layout.MIRROR_STATE_PARTS[0], "check.lock"))
        other = Path(tempfile.gettempdir()) / "otro.lock"
        self.assertEqual(
            check_lock.lock_path({"LOCALAPPDATA": str(local), "GEOBLENDER_CHECK_LOCK": str(other)}),
            other,
        )
        with self.assertRaises(check_lock.LockProblem) as caught:
            check_lock.lock_path({})
        self.assertIn("LOCALAPPDATA", str(caught.exception))
        self.assertIn("GEOBLENDER_CHECK_LOCK", str(caught.exception))
        self.assertIs(inspect.signature(check.main).parameters["lock_file"].default,
                      check_lock.lock_path)


class CheckLockTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="gb-cerrojo-")
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name).joinpath(*layout.CHECK_LOCK_PARTS)

    def lock(self, folder: str) -> check_lock.CheckLock:
        lock = check_lock.CheckLock(self.path, folder)
        self.addCleanup(lock.release)
        return lock

    def test_second_waits_once_until_the_first_releases(self) -> None:
        """RNF-001-01, RNF-007-01 (spec 006, T46): el primero toma el cerrojo (y crea su
        carpeta) y guarda en él su pid y su carpeta; el segundo espera y avisa una sola
        vez, con ese pid y esa carpeta, aunque dé varias vueltas; cuando el primero lo
        suelta, lo toma el segundo y el fichero dice el suyo. Soltado, el fichero queda
        sin dueño y nada que borrar a mano."""
        first, second = self.lock("C:\\obra\\uno"), self.lock("C:\\obra\\dos")
        self.assertTrue(first.acquire(sleep=_never))
        self.assertEqual(first.owner, os.getpid())
        holder = check_lock.read_holder(self.path)
        self.assertEqual((holder.pid, holder.folder), (os.getpid(), "C:\\obra\\uno"))
        self.assertRegex(holder.since, r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$")
        seen: list[check_lock.Holder | None] = []
        polls = _Polls(at=3, action=first.release)
        self.assertTrue(second.acquire(on_wait=seen.append, sleep=polls))
        self.assertEqual(polls.count, 3)
        self.assertEqual(seen, [holder])
        self.assertEqual(check_lock.read_holder(self.path).folder, "C:\\obra\\dos")
        second.release()
        self.assertIsNone(check_lock.read_holder(self.path))
        self.assertTrue(self.path.is_file())
        self.assertTrue(self.lock("C:\\obra\\tres").acquire(sleep=_never))

    def test_parent_lock_is_inherited(self) -> None:
        """RNF-001-01, RNF-007-01 (spec 006, T46): con ``GEOBLENDER_CHECK_LOCK_HELD`` = el
        pid del que lo tiene (lo que lleva cada orden de ``check.py``), no se espera ni se
        toma: es de su padre, que lo sigue teniendo. Con otro pid, se espera."""
        parent = self.lock("C:\\obra\\padre")
        parent.acquire(sleep=_never)
        child = self.lock("C:\\obra\\hija")
        self.assertFalse(child.acquire(inherited=str(os.getpid()), on_wait=self.fail,
                                       sleep=_never))
        self.assertEqual(child.owner, os.getpid())
        child.release()
        self.assertEqual(check_lock.read_holder(self.path).folder, "C:\\obra\\padre")
        stranger = self.lock("C:\\obra\\otra")
        seen: list[check_lock.Holder | None] = []
        with self.assertRaises(_Stop):
            stranger.acquire(inherited="999999", on_wait=seen.append, sleep=_never)
        self.assertEqual([h.pid for h in seen], [os.getpid()])

    def test_holder_not_written_yet(self) -> None:
        """RNF-001-01, RNF-007-01 (spec 006, T46): si el que lo tiene aún no ha escrito
        quién es (o no se puede leer), se espera sin avisar hasta ``unknown_after_s`` y
        entonces se avisa una vez, sin pid; si después se lee, se avisa con él."""
        first = self.lock("C:\\obra\\uno")
        first.acquire(sleep=_never)
        fd = os.open(self.path, os.O_RDWR | os.O_BINARY)
        try:
            os.write(fd, b" " * check_lock.INFO_SIZE)
        finally:
            os.close(fd)
        now = [0.0]  # el reloj de la espera: cada vuelta, 1 s
        polls = [0]

        def sleep(_seconds: float) -> None:
            polls[0] += 1
            now[0] += 1.0
            if polls[0] == 4:
                first._write_holder()  # el que lo tiene escribe por fin quién es
            elif polls[0] == 6:
                first.release()
            elif polls[0] > 50:
                raise _Stop("sigue esperando")

        seen: list[check_lock.Holder | None] = []
        second = self.lock("C:\\obra\\dos")
        self.assertTrue(second.acquire(on_wait=seen.append, sleep=sleep,
                                       clock=lambda: now[0], unknown_after_s=2.5))
        self.assertEqual(polls[0], 6)
        self.assertEqual(len(seen), 2, seen)
        self.assertIsNone(seen[0])
        self.assertEqual(seen[1].folder, "C:\\obra\\uno")

    def test_killed_holder_frees_the_lock(self) -> None:
        """RNF-001-01, RNF-007-01 (spec 006, T46): el cerrojo de otro proceso se ve (su pid
        y su carpeta) y, si ese proceso muere a mitad (sin soltarlo), el sistema lo suelta
        y el que esperaba lo toma, sin borrar nada."""
        other = _Holder(self.path, "C:\\obra\\otro-worktree")
        self.addCleanup(other.kill)
        seen: list[check_lock.Holder | None] = []
        polls = _Polls(at=2, action=other.kill, limit=int(DEADLINE_S / 0.01))
        waiting = self.lock("C:\\obra\\esta")
        self.assertTrue(waiting.acquire(on_wait=seen.append, sleep=polls, poll_s=0.01))
        self.assertEqual([(h.pid, h.folder) for h in seen],
                         [(other.process.pid, "C:\\obra\\otro-worktree")])
        self.assertEqual(check_lock.read_holder(self.path).pid, os.getpid())

    def test_wait_message(self) -> None:
        """RNF-001-01, RNF-007-01 (spec 006, T46): la línea de espera, en español, dice
        que espera a otro ``tools/check.py`` de este equipo, con su pid, su carpeta y desde
        cuándo, o que no se sabe cuál."""
        holder = check_lock.Holder(4321, "C:\\obra\\Geoblender", "2026-10-10 10:31:05")
        text = check_lock.wait_message(holder)
        self.assertTrue(text.startswith(check_lock.WAIT_PREFIX), text)
        for part in ("otro tools/check.py", "este equipo", "pid 4321",
                     "«C:\\obra\\Geoblender»", "2026-10-10 10:31:05", "espera"):
            self.assertIn(part, text)
        self.assertIn("no se sabe", check_lock.wait_message(None))


def _verdict_seconds(out: str) -> float:
    found = re.search(r"^RESULTADO: .*\((\d+),(\d) s\)", out, re.MULTILINE)
    if found is None:
        raise AssertionError(f"sin RESULTADO:\n{out}")
    return float(f"{found.group(1)}.{found.group(2)}")


class CheckMainLockTest(unittest.TestCase):
    """``check.main`` con el cerrojo en una carpeta temporal y el ejecutor simulado."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="gb-cerrojo-")
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "check.lock"

    def run_main(self, environ: dict[str, str] | None = None) -> tuple[object, float]:
        start = time.perf_counter()
        result = run_check(lock_file=lambda env: self.path,
                           environ=_environ() if environ is None else environ)
        return result, time.perf_counter() - start

    def test_waits_for_another_check_and_times_from_the_lock(self) -> None:
        """RNF-001-01, RNF-007-01 (spec 006, T46): con otro ``check.py`` en marcha, este
        escribe tras su cabecera una sola línea de espera, con el pid y la carpeta del otro,
        y espera; cuando el otro termina, ejecuta los pasos como siempre (mismo resumen y
        código), y el tiempo de ``RESULTADO`` empieza al tomar el cerrojo: no cuenta la
        espera. Sus órdenes llevan ``GEOBLENDER_CHECK_LOCK_HELD`` con su pid, y al acabar
        suelta el cerrojo."""
        other = _Holder(self.path, "C:\\obra\\Geo_blender-wt\\008", hold=str(HOLD_S))
        self.addCleanup(other.kill)
        with mock.patch.object(check_lock, "POLL_S", 0.02):
            result, total = self.run_main()
        self.assertEqual(other.close(), 0)
        self.assertEqual(result.code, 0, result.out + result.err)
        lines = result.out.splitlines()
        waits = [n for n, line in enumerate(lines) if line.startswith(check_lock.WAIT_PREFIX)]
        self.assertEqual(waits, [1], result.out)
        self.assertTrue(lines[0].startswith("Geoblender · comprobación completa"), lines[0])
        self.assertIn(f"pid {other.process.pid}", lines[1])
        self.assertIn("«C:\\obra\\Geo_blender-wt\\008»", lines[1])
        self.assertRegex(lines[2], r"^  correcto  unitarias ")
        self.assertRegex(lines[-1], r"^RESULTADO: VERDE \(")
        self.assertGreaterEqual(total - _verdict_seconds(result.out), HOLD_S / 2,
                                f"total {total:.2f} s\n{result.out}")
        self.assertTrue(result.runner.calls)
        for call in result.runner.calls:
            self.assertEqual(call.env.get(check_lock.ENV_HELD), str(os.getpid()), call.cmd)
        after = check_lock.CheckLock(self.path, "C:\\obra\\siguiente")
        self.addCleanup(after.release)
        self.assertTrue(after.acquire(sleep=_never))

    def test_free_lock_same_output(self) -> None:
        """RNF-001-01, RNF-007-01 (spec 006, T46): con el cerrojo libre no hay línea de
        espera y la salida es la de siempre (salvo las duraciones)."""
        with_lock, _seconds = self.run_main()
        without = run_check()
        self.assertEqual(with_lock.code, without.code)

        def plain(text: str) -> str:
            return re.sub(r"\d+,\d s", "x s", text)

        self.assertEqual(plain(with_lock.out), plain(without.out))
        self.assertNotIn(check_lock.WAIT_PREFIX, with_lock.out)

    def test_lock_of_the_parent_check(self) -> None:
        """RNF-001-01, RNF-007-01 (spec 006, T46): un ``check.py`` lanzado desde una orden
        de otro (con ``GEOBLENDER_CHECK_LOCK_HELD`` = su pid) no espera a su padre."""
        parent = check_lock.CheckLock(self.path, "C:\\obra\\padre")
        parent.acquire(sleep=_never)
        self.addCleanup(parent.release)
        safety = threading.Timer(DEADLINE_S, parent.release)  # si esperase, no para siempre
        safety.start()
        self.addCleanup(safety.cancel)
        result, total = self.run_main({**_environ(), check_lock.ENV_HELD: str(os.getpid())})
        self.assertEqual(result.code, 0, result.out)
        self.assertNotIn(check_lock.WAIT_PREFIX, result.out)
        self.assertLess(total, DEADLINE_S)
        self.assertEqual(check_lock.read_holder(self.path).folder, "C:\\obra\\padre")

    def test_unusable_lock_is_a_warning(self) -> None:
        """RNF-001-01, RNF-007-01 (spec 006, T46): si el cerrojo no se puede crear (su
        carpeta es un fichero), un aviso con la ruta, y la comprobación sigue."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        blocker = self.path.parent / "fichero"
        blocker.write_text("x", encoding="utf-8")
        self.path = blocker / "check.lock"
        result, _seconds = self.run_main()
        self.assertEqual(result.code, 0, result.out)
        self.assertIn("AVISO:", result.out)
        self.assertIn(str(self.path), result.out)
        self.assertRegex(result.out.splitlines()[-1], r"^RESULTADO: VERDE \(")


if __name__ == "__main__":
    unittest.main()
