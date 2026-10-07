# SPDX-License-Identifier: GPL-3.0-or-later
"""Autodiagnóstico en un proceso aparte (spec 004, T08; HU-004-1, HU-004-2; RF-004-01,
RF-004-15; plan 004 §5.1 y §5.4.3).

``workers/selftest.py`` envuelve ``jobs.selftest.run`` (probado con un contexto falso en
``tests/unit/jobs/test_selftest.py``). Aquí se lanza de verdad con el arranque,
``python.exe -I -B -u workers/_bootstrap.py … --kind blender`` (``LaunchedWorker`` de
``tests/support/jobs_fixtures.py``), con cada parámetro de la suma por trozos: ``sleep_s``,
``fail_at``, ``crash_at`` e ``ignore_cancel`` (``stdout_noise``, en ``test_bootstrap.py``).
Todos los workers del módulo se lanzan a la vez al empezar (``setUpModule``); la
cancelación se pide antes de lanzar (el centinela ``cancel`` ya está en la carpeta), así la
prueba no depende de esperas.
"""

import unittest

import numpy as np

from tests.support import jobs_fixtures as _support

SUM_N = 3_000_001
SUM_CHUNKS = 7
SLEEP_CHUNKS = 4
SLEEP_S = 0.05
CANCEL_CHUNKS = 40

_RUNS: dict[str, _support.WorkerRun] = {}
_JOBS: dict[str, object] = {}


def setUpModule() -> None:
    tmp = _support.jobs_tmp()
    base = tmp.__enter__()
    unittest.addModuleCleanup(tmp.__exit__, None, None, None)
    root = base / "jobs"
    params = {
        "sum": {"n": SUM_N, "chunks": SUM_CHUNKS},
        "sleep": {"n": 1000, "chunks": SLEEP_CHUNKS, "sleep_s": SLEEP_S},
        "fail": {"n": 1000, "chunks": 3, "fail_at": 2},
        "crash": {"n": 1000, "chunks": 3, "crash_at": 2},
        "cancel": {"n": 1000, "chunks": CANCEL_CHUNKS, "sleep_s": SLEEP_S},
        "ignore": {"n": 1000, "chunks": 4, "ignore_cancel": True},
    }
    launched: dict[str, _support.LaunchedWorker] = {}
    for name, values in params.items():
        job = _support.prepare_job(root, params=values)
        if name in ("cancel", "ignore"):
            job.cancel_file.touch()
        _JOBS[name] = job
        worker = _support.LaunchedWorker(job.path)
        unittest.addModuleCleanup(worker.close)
        launched[name] = worker
    for name, worker in launched.items():
        _RUNS[name] = worker.finish()


class SumTest(unittest.TestCase):
    """HU-004-1: la suma por trozos termina con su resultado exacto."""

    def test_exact_sum_and_final_progress(self):
        """RF-004-01, RF-004-15: n(n−1)/2 exacta con n = 3 000 001 (varios bloques por
        trozo) en el resumen y en ``out/sum.npy``; ``start`` primero, ``result`` el último
        y el avance hasta 1,0 («Trozo 7 de 7»)."""
        run = _RUNS["sum"]
        self.assertEqual(run.returncode, 0, run.log)
        expected = SUM_N * (SUM_N - 1) // 2
        self.assertEqual(expected, 4_500_001_500_000)
        self.assertEqual((run.types()[0], run.types()[-1]), ("start", "result"))
        result = run.of_type("result")[0]
        self.assertEqual(result.summary["sum"], expected)
        value = np.load(_JOBS["sum"].path / "out" / "sum.npy", allow_pickle=False)
        self.assertEqual(int(value), expected)
        last = run.of_type("progress")[-1]
        self.assertEqual((last.frac, last.msg), (1.0, f"Trozo {SUM_CHUNKS} de {SUM_CHUNKS}"))


class SleepTest(unittest.TestCase):
    """HU-004-1: ``sleep_s`` alarga cada trozo."""

    def test_sleep_per_chunk(self):
        """Con 4 trozos de 0,05 s, entre ``start`` y ``result`` pasan al menos 0,2 s (horas
        del propio worker) y el último avance es 1,0."""
        run = _RUNS["sleep"]
        self.assertEqual(run.returncode, 0, run.log)
        start = run.of_type("start")[0]
        result = run.of_type("result")[0]
        self.assertGreaterEqual(result.ts - start.ts, SLEEP_CHUNKS * SLEEP_S)
        last = run.of_type("progress")[-1]
        self.assertEqual((last.frac, last.msg),
                         (1.0, f"Trozo {SLEEP_CHUNKS} de {SLEEP_CHUNKS}"))


class FailAtTest(unittest.TestCase):
    """HU-004-2: ``fail_at`` provoca un fallo explicado."""

    def test_fail_at_ends_with_error_event_and_code_2(self):
        """RF-004-15: salida 2 con el evento ``error`` del autodiagnóstico (código,
        ``msgid``, valores y texto en español), sin resultado ni traza."""
        run = _RUNS["fail"]
        self.assertEqual(run.returncode, 2, run.log)
        self.assertEqual(run.types()[-1], "error")
        error = run.of_type("error")[0]
        self.assertEqual(error.code, "selftest_failed")
        self.assertEqual(error.msgid,
                         "Self-test: failure provoked at chunk {chunk} of {chunks}.")
        self.assertEqual(error.msg, "Autodiagnóstico: fallo provocado en el trozo 2 de 3.")
        self.assertEqual(dict(error.values), {"chunk": 2, "chunks": 3})
        self.assertNotIn("result", run.types())
        self.assertFalse(_JOBS["fail"].result_file.exists())
        self.assertNotIn("Traceback", run.log)
        self.assertNotIn(b"Traceback", run.channel)


class CrashAtTest(unittest.TestCase):
    """HU-004-2: ``crash_at`` tumba el proceso del worker."""

    def test_crash_at_exits_7_without_result(self):
        """``os._exit(7)`` en el trozo 2: salida 7, el canal acaba en el avance del trozo 1 y
        no hay resultado ni ``result.json``."""
        run = _RUNS["crash"]
        self.assertEqual(run.returncode, 7, run.log)
        self.assertEqual(run.invalid, ())
        self.assertEqual(run.types()[-1], "progress")
        self.assertEqual(run.events[-1].msg, "Trozo 1 de 3")
        for kind in ("result", "error", "cancelled"):
            self.assertNotIn(kind, run.types())
        self.assertFalse(_JOBS["crash"].result_file.exists())
        self.assertEqual(list((_JOBS["crash"].path / "out").iterdir()), [])


class CancelTest(unittest.TestCase):
    """HU-004-1: el worker atiende el centinela ``cancel`` de su carpeta."""

    def test_cancel_file_stops_the_worker(self):
        """Con el centinela ya puesto, un trabajo de 2 s para en el primer trozo: evento
        ``cancelled`` («Cancelado en el trozo 1 de 40») y salida 3, sin resultado."""
        run = _RUNS["cancel"]
        self.assertEqual(run.returncode, 3, run.log)
        self.assertEqual(run.types()[-1], "cancelled")
        cancelled = run.of_type("cancelled")[0]
        self.assertEqual(cancelled.msg, f"Cancelado en el trozo 1 de {CANCEL_CHUNKS}")
        self.assertLess(cancelled.ts - run.of_type("start")[0].ts, 1.0)
        self.assertNotIn("result", run.types())
        self.assertFalse(_JOBS["cancel"].result_file.exists())


class IgnoreCancelTest(unittest.TestCase):
    """HU-004-2: ``ignore_cancel`` no atiende la cancelación (para probar el plazo de
    gracia)."""

    def test_ignore_cancel_finishes(self):
        """Con el centinela puesto, termina con su resultado exacto y salida 0, sin evento
        ``cancelled``."""
        run = _RUNS["ignore"]
        self.assertEqual(run.returncode, 0, run.log)
        self.assertTrue(_JOBS["ignore"].cancel_file.exists())
        self.assertNotIn("cancelled", run.types())
        self.assertEqual(run.of_type("result")[0].summary["sum"], 1000 * 999 // 2)


if __name__ == "__main__":
    unittest.main()
