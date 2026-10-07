# SPDX-License-Identifier: GPL-3.0-or-later
"""*Job Object* de Windows de los workers (spec 004, T10; RF-004-10, RF-004-13; plan 004
§5.3.3, §5.4.5 y §6).

Cada worker en proceso aparte se asigna a su propio *Job Object* con
``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``: los procesos que lance entran en él solos, terminarlo
(``TerminateJobObject``) termina el worker **y sus hijos** de una vez, y cerrar su último
*handle* (también cuando Blender muere) termina lo que quede. Aquí se prueba con procesos de
Python que no hacen nada (``time.sleep``), lanzados con ``-B -I``.
"""

import os
import subprocess
import sys
import time
import unittest

from tests.support import jobs_fixtures as _support
from tests.support.package import import_geoblender
from tests.support.resources import WINDOWS, WINDOWS_HINT, skip_reason

winjob = import_geoblender("jobs.winjob")

DEATH_MAX_S = 1.0
"""RF-004-10: el proceso termina en ≤ 1 s una vez que se pide terminarlo."""
EXIT_CODE = 77
SLEEPER = "import time; time.sleep(60)"
# Un worker que lanza un hijo (como el pip de la instalación) y cuenta su pid por la salida.
PARENT = (
    "import subprocess, sys, time\n"
    "child = subprocess.Popen([sys.executable, '-B', '-I', '-c', 'import time; time.sleep(60)'],\n"
    "                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)\n"
    "print(child.pid, flush=True)\n"
    "time.sleep(60)\n"
)


def _python(source: str, **options) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-B", "-I", "-c", source],
                            stdin=subprocess.DEVNULL, **options)


class _JobCase(unittest.TestCase):
    """Un *Job Object* nuevo por prueba; al acabar, se cierra (y con él, lo que quede)."""

    def setUp(self):
        self.job = winjob.JobObject()
        self.addCleanup(self.job.close)

    def launch(self, source: str = SLEEPER, **options) -> subprocess.Popen:
        """Lanza ``source`` y lo asigna al *Job Object* al momento, antes de que pueda
        lanzar nada."""
        process = _python(source, **options)
        self.addCleanup(self._reap, process)
        self.job.assign(process.pid)
        return process

    @staticmethod
    def _reap(process: subprocess.Popen) -> None:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        if process.stdout is not None:
            process.stdout.close()

    def wait_empty(self, timeout_s: float = DEATH_MAX_S) -> int:
        """Espera a que no quede ningún proceso en el *Job Object*; devuelve cuántos
        quedan."""
        deadline = time.monotonic() + timeout_s
        while (count := self.job.active_processes()) and time.monotonic() < deadline:
            time.sleep(0.02)
        return count


@unittest.skipUnless(os.name == "nt", skip_reason(WINDOWS, WINDOWS_HINT))
class TerminateTest(_JobCase):
    """RF-004-10: terminar el *Job Object* termina el worker y todos sus hijos."""

    def test_terminate_ends_the_worker_and_its_child(self):
        """RF-004-10: el hijo que lanza el worker entra solo en su *Job Object*; al
        terminarlo, los dos dejan de existir en ≤ 1 s y el worker sale con el código
        pedido."""
        parent = self.launch(PARENT, stdout=subprocess.PIPE)
        child_pid = int(parent.stdout.readline())
        self.assertTrue(_support.pid_alive(child_pid))
        self.assertEqual(self.job.active_processes(), 2)
        started = time.monotonic()
        self.assertTrue(self.job.terminate(EXIT_CODE))
        self.assertEqual(parent.wait(timeout=DEATH_MAX_S), EXIT_CODE)
        self.assertTrue(_support.wait_until_dead(child_pid, timeout_s=DEATH_MAX_S))
        self.assertLessEqual(time.monotonic() - started, DEATH_MAX_S)
        self.assertEqual(self.wait_empty(), 0)

    def test_terminate_twice_is_harmless(self):
        """RF-004-10: terminar otra vez un *Job Object* ya vacío no falla."""
        process = self.launch()
        self.assertTrue(self.job.terminate(EXIT_CODE))
        self.assertEqual(process.wait(timeout=DEATH_MAX_S), EXIT_CODE)
        self.assertTrue(self.job.terminate(EXIT_CODE))


@unittest.skipUnless(os.name == "nt", skip_reason(WINDOWS, WINDOWS_HINT))
class KillOnCloseTest(_JobCase):
    """RF-004-13: cerrar el último *handle* del *Job Object* (lo hace Windows si Blender
    muere) termina lo que quede dentro."""

    def test_close_ends_what_is_left(self):
        """RF-004-13: con ``KILL_ON_JOB_CLOSE``, al cerrarlo el proceso deja de existir en
        ≤ 1 s."""
        process = self.launch()
        self.assertFalse(self.job.closed)
        self.job.close()
        self.assertTrue(self.job.closed)
        process.wait(timeout=DEATH_MAX_S)
        self.assertFalse(_support.pid_alive(process.pid))

    def test_closed_job_object(self):
        """RF-004-13: cerrarlo otra vez no falla; terminarlo ya cerrado no hace nada
        (``False``); asignarle un proceso o contarlos es un error de programación."""
        self.job.close()
        self.job.close()
        self.assertFalse(self.job.terminate(EXIT_CODE))
        with self.assertRaises(ValueError):
            self.job.assign(1234)
        with self.assertRaises(ValueError):
            self.job.active_processes()

    def test_context_manager_closes_it(self):
        """RF-004-13: usado con ``with``, se cierra al salir."""
        with winjob.JobObject() as job:
            self.assertFalse(job.closed)
        self.assertTrue(job.closed)


class ArgumentsTest(unittest.TestCase):
    """RF-004-10: lo que no es un proceso o un código de salida se rechaza antes de llamar
    a Windows."""

    def test_supported_only_on_windows(self):
        """RF-004-10: ``supported()`` dice si hay *Job Objects* (solo en Windows)."""
        self.assertEqual(winjob.supported(), sys.platform == "win32")

    @unittest.skipUnless(os.name == "nt", skip_reason(WINDOWS, WINDOWS_HINT))
    def test_bad_values(self):
        """RF-004-10: un pid que no es un entero positivo y un código de salida fuera de
        0–2³²−1 (o 259, que se confundiría con «sigue vivo») son ``ValueError``."""
        with winjob.JobObject() as job:
            for pid in (0, -3, True, 2.5, "12"):
                with self.subTest(pid=pid), self.assertRaises(ValueError):
                    job.assign(pid)
            for code in (-1, 2**32, 259, 1.5, None):
                with self.subTest(code=code), self.assertRaises(ValueError):
                    job.terminate(code)


if __name__ == "__main__":
    unittest.main()
