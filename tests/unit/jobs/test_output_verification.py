# SPDX-License-Identifier: GPL-3.0-or-later
"""La comprobación de los resultados de un trabajo, fuera del hilo de Blender (spec 005, T53;
RNF-005-06; RF-004-05, RF-004-13; plan 004 §5.3.4).

RF-004-05: un trabajo no termina «Terminado» sin comprobar antes que cada resultado declarado
está dentro de ``out/`` con su huella sha256. Con los de V-ref (las once tablas de la base,
unos 75 MB) esa comprobación era una llamada de 0,2–0,6 s del hilo de Blender al acabar el
trabajo (T32: ``JobRunner.poll``, desde el temporizador del monitor). Ahora el sondeo que ve
el final la empieza en un hilo *daemon* y otro sondeo posterior da el final: el sha256 nunca
se calcula en el hilo que sondea (se cuenta, no se cronometra) y el trabajo sigue «En curso»
(en su hueco, RF-004-04, y sin ``on_finish``) hasta que la comprobación acaba. Un resultado
alterado sigue dejándolo «Fallido» (``output_hash_mismatch``); al
cerrar el lanzador, la comprobación en marcha se espera y el trabajo acaba con su estado.
"""

import dataclasses
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.support import jobs_fixtures as _support
from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR

catalog = import_geoblender("jobs.catalog")
runner = import_geoblender("jobs.runner")

WORKER = "gbtest_outputs"
DEADLINE_S = 30.0
POLL_S = 0.01
BLOCK = bytes(range(256)) * 256
"""Lo que se escribe en cada resultado (64 KiB)."""


def _outputs_run(ctx):
    """El tipo de trabajo de estas pruebas: dos resultados declarados con su huella; con
    ``alter``, el último cambia después de declararlo."""
    path = None
    for index in range(2):
        path = ctx.output_path(f"tabla_{index}.bin")
        path.write_bytes(BLOCK)
        ctx.add_output(path, f"tabla_{index}")
    if ctx.request.params.get("alter"):
        with open(path, "r+b") as handle:
            handle.write(b"X")
    return {"tablas": 2}


def _quick(params) -> float:
    return 0.01


class _Hashing:
    """``runner._sha256`` vigilado: cuenta las huellas que se calculan en el hilo que sondea y,
    fuera de él, las de los resultados de :data:`WORKER` esperan a :attr:`release` (así se ve
    el trabajo mientras se comprueba)."""

    def __init__(self) -> None:
        self.real = runner._sha256
        self.polling = threading.current_thread()
        self.in_poll: list[str] = []
        self.elsewhere: list[str] = []
        self.started = threading.Event()
        self.release = threading.Event()

    def __call__(self, path: Path):
        if threading.current_thread() is self.polling:
            self.in_poll.append(path.name)
        elif path.name.startswith("tabla_"):
            self.elsewhere.append(path.name)
            self.started.set()
            self.release.wait(DEADLINE_S)
        return self.real(path)


class VerificationTest(unittest.TestCase):
    def setUp(self) -> None:
        base = self.enterContext(_support.jobs_tmp())
        self.enterContext(mock.patch.dict(catalog._REGISTRY, clear=True))
        catalog.register_worker(catalog.WorkerInfo(WORKER, "Outputs test job",
                                                   estimate_s=_quick, run=_outputs_run))
        builtin = next(info for info in catalog.BUILTIN_WORKERS if info.name == "selftest")
        catalog.register_worker(dataclasses.replace(builtin, default_timeout_s=60.0))
        self.runner = runner.JobRunner(jobs_root=base / "jobs", package_dir=EXTENSION_DIR,
                                       blender_python=Path(sys.executable))
        self.addCleanup(self.runner.shutdown)
        self.hashing = _Hashing()
        self.enterContext(mock.patch.object(runner, "_sha256", self.hashing))
        self.addCleanup(self.hashing.release.set)
        self.finished: list = []

    def submit(self, worker: str = WORKER, **params):
        request = _support_request(worker, params)
        return self.runner.submit(request, on_finish=self.finished.append)

    def until(self, condition, what: str) -> None:
        deadline = time.monotonic() + DEADLINE_S
        while not condition():
            self.assertLess(time.monotonic(), deadline, f"no llegó a tiempo: {what}")
            self.runner.poll()
            time.sleep(POLL_S)

    def test_poll_never_hashes_and_the_job_ends_after_the_check(self) -> None:
        """RNF-005-06, RF-004-05, RF-004-04 (T53): el sondeo que ve acabar el trabajo no
        calcula ninguna huella: la comprobación va en otro hilo y, mientras dura, el trabajo
        sigue «En curso» (en su hueco: el siguiente de la cola espera) sin final ni
        ``on_finish``. Acabada, un sondeo da «Terminado» con sus dos resultados y su
        ``on_finish``, una vez, y arranca el siguiente."""
        handle = self.submit()
        queued = self.submit("selftest", n=1000, chunks=1)
        self.until(lambda: self.hashing.started.is_set() or bool(self.hashing.in_poll),
                   "la comprobación de los resultados")
        self.assertEqual(self.hashing.in_poll, [])
        for _ in range(3):
            self.runner.poll()
        self.assertEqual((handle.state, handle.result(), self.finished, queued.state),
                         ("running", None, [], "queued"))
        self.hashing.release.set()
        self.until(lambda: queued.result() is not None, "el siguiente trabajo de la cola")
        result = handle.result()
        self.assertEqual(result.state, "succeeded")
        self.assertEqual(sorted(ref.role for ref in result.outputs), ["tabla_0", "tabla_1"])
        self.assertEqual(dict(result.summary), {"tablas": 2})
        self.assertEqual([item.job_uid for item in self.finished].count(handle.job_uid), 1)
        self.assertEqual(sorted(self.hashing.elsewhere), ["tabla_0.bin", "tabla_1.bin"])
        self.assertEqual(self.hashing.in_poll, [])

    def test_an_altered_output_still_fails(self) -> None:
        """RF-004-05 (T53): un resultado que cambia después de declararlo deja el trabajo
        «Fallido» con ``output_hash_mismatch`` (y sin resultados), comprobado fuera del hilo
        que sondea."""
        self.hashing.release.set()
        handle = self.submit(alter=True)
        self.until(lambda: handle.result() is not None, "el final del trabajo")
        result = handle.result()
        self.assertEqual((result.state, result.error_code, result.outputs),
                         ("failed", "output_hash_mismatch", ()))
        self.assertIn("out/tabla_1.bin", result.error_text)
        self.assertEqual(self.hashing.in_poll, [])
        self.assertIn("tabla_1.bin", self.hashing.elsewhere)

    def test_shutdown_waits_for_the_check(self) -> None:
        """RF-004-13, RF-004-05 (T53): cerrar el lanzador con la comprobación en marcha la
        espera; el trabajo, que ya había acabado, acaba «Terminado» con sus resultados y el
        siguiente sondeo da su final."""
        handle = self.submit()
        self.until(lambda: self.hashing.started.is_set() or bool(self.hashing.in_poll),
                   "la comprobación de los resultados")
        threading.Timer(0.1, self.hashing.release.set).start()
        self.runner.shutdown()
        self.runner.poll()
        result = handle.result()
        self.assertIsNotNone(result)
        self.assertEqual((result.state, len(result.outputs)), ("succeeded", 2))
        self.assertEqual([item.job_uid for item in self.finished], [handle.job_uid])
        self.assertEqual(self.hashing.in_poll, [])


def _support_request(worker: str, params: dict):
    protocol = import_geoblender("jobs.protocol")
    return protocol.new_request(worker, label="Comprobación de resultados", owner="jobs",
                                params=params)


if __name__ == "__main__":
    unittest.main()
