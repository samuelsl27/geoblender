# SPDX-License-Identifier: GPL-3.0-or-later
"""Ejecutor en hilo de los trabajos cortos (spec 004, T14; RF-004-03, RF-004-09, RF-004-12,
RF-004-13; plan 004 §5.1, §5.4.1, §5.4.2 y §5.4.5).

Un trabajo estimado en ≤ 5 s cuyo tipo tiene función ``run`` corre en un hilo *daemon* de
Blender (``jobs/inprocess.py``), con el mismo seguimiento, cancelación y registro que en
proceso aparte. Un hilo no se puede matar: si no atiende la cancelación, al vencer su plazo
de gracia el trabajo queda «Cancelado» (forzado), lo que entregue después se descarta y su
hueco de hilo se libera cuando acaba; al cerrar el lanzador, ``shutdown`` no lo espera más
de 1 s y no retiene el cierre.

Para no esperar en serie, todos los trabajos se lanzan a la vez al empezar
(``setUpModule``), cada uno con su propio lanzador (un hueco de hilo cada uno), y se
sondean hasta que acaban; cada prueba mira lo que dejó el suyo:

- ``thread_sum`` y ``proc_sum``: la misma suma por trozos en hilo y en proceso aparte (este,
  con el tipo declarado ``subprocess`` solo mientras se lanza).
- ``proc_long``: una suma estimada en 6 s, que va a proceso aparte; se cancela al lanzarla.
- ``thread_cancel``: una suma de 4 s, cancelada en cuanto envía su primer avance.
- ``thread_raise``: un tipo de trabajo cuya función lanza una excepción no prevista.
- ``thread_fail``: el fallo provocado del autodiagnóstico (``JobFailed``).
- ``thread_ignore``: una suma de 1,8 s que no atiende la cancelación, con el plazo de gracia
  mínimo (1 s), cancelada al lanzarla; ``thread_after``, lanzado en su mismo lanzador en
  cuanto aquella consta «Cancelado» (espera su hueco).
- ``thread_shut``: una suma de 1,6 s que no atiende la cancelación; su lanzador se cierra
  (``shutdown``) en cuanto arranca.
"""

import ast
import dataclasses
import json
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from tests.support import jobs_fixtures as _support
from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR

catalog = import_geoblender("jobs.catalog")
inprocess = import_geoblender("jobs.inprocess")
protocol = import_geoblender("jobs.protocol")
records = import_geoblender("jobs.records")
runner = import_geoblender("jobs.runner")

SUM_N = 1_000_000
SUM_PARAMS = {"n": SUM_N, "chunks": 3, "sleep_s": 0.11}
"""Cada trozo dura más que el intervalo mínimo entre avances (0,1 s): los dos ejecutores
envían todos los avances y sus registros se pueden comparar uno a uno."""
LONG_PARAMS = {"n": 1000, "chunks": 2, "sleep_s": 3.0}
"""6 s estimados: más de 5 s, proceso aparte."""
CANCEL_PARAMS = {"n": 1000, "chunks": 20, "sleep_s": 0.2}
FAIL_PARAMS = {"n": 1000, "chunks": 4, "fail_at": 2}
IGNORE_PARAMS = {"n": 1000, "chunks": 2, "sleep_s": 0.9, "ignore_cancel": True}
SHUT_PARAMS = {"n": 1000, "chunks": 2, "sleep_s": 0.8, "ignore_cancel": True}
AFTER_PARAMS = {"n": 1000, "chunks": 1}
GRACE_S = 1.0
"""El plazo de gracia mínimo válido."""
STOP_MAX_S = 2.0
"""RF-004-09: detenido en ≤ 2 s."""
SHUTDOWN_TIMEOUT_S = 3.0
SHUTDOWN_MAX_S = 3.5
"""Tarea T14: con el hilo que no atiende la cancelación vivo, ``shutdown(timeout_s=3)``
vuelve en ≤ 3,5 s."""
JOB_TIMEOUT_S = 120.0
DEADLINE_S = 30.0
POLL_S = 0.02
RAISE_WORKER = "gbtest_raise"
RAISE_TEXT = "Fallo provocado en el hilo de las pruebas: ñandú"
SUM_LABEL = "Suma en los dos ejecutores"

LABELS = {
    "proc_long": "Suma larga",
    "thread_cancel": "Cancelación en hilo",
    "thread_raise": "Excepción en hilo",
    "thread_fail": "Fallo en hilo",
    "thread_ignore": "Cancelación ignorada en hilo",
    "thread_after": "Después del hilo abandonado",
    "thread_shut": "Cierre con un hilo vivo",
}

_HANDLES: dict[str, object] = {}
_RUNNERS: dict[str, object] = {}
_UPDATES: dict[str, list] = {}
_FINISHED: dict[str, list] = {}
_STATE: dict[str, object] = {}


def _raise_run(ctx):
    """La función del tipo de trabajo ``gbtest_raise``: deja una nota y falla sin
    explicarlo (un error del programa del módulo)."""
    ctx.log("info", "Antes del fallo")
    raise RuntimeError(RAISE_TEXT)


def _quick(params) -> float:
    return 0.01


def _request(name: str, params: dict, *, worker: str = "selftest", **options):
    label = SUM_LABEL if name in ("thread_sum", "proc_sum") else LABELS[name]
    return protocol.new_request(worker, label=label, owner="jobs", params=params, **options)


def _on_finish(result) -> None:
    _FINISHED.setdefault(result.job_uid, []).append(result)


def _submit(name: str, job_runner, job) -> None:
    handle = job_runner.submit(job, on_finish=_on_finish)
    _HANDLES[name] = handle
    _RUNNERS[name] = job_runner
    _STATE.setdefault("state_after_submit", {})[name] = handle.state


def _poll() -> None:
    for job_runner in {id(r): r for r in _RUNNERS.values()}.values():
        for update in job_runner.poll():
            _UPDATES.setdefault(update.job_uid, []).append(update)


def _events(name: str) -> list:
    return [event for update in _UPDATES.get(_HANDLES[name].job_uid, ())
            for event in update.events]


def _types(name: str) -> list[str]:
    return [event.type for event in _events(name)]


def _thread_name(name: str) -> str:
    return inprocess.THREAD_NAME_PREFIX + _HANDLES[name].job_uid


def _thread_alive(name: str) -> bool:
    wanted = _thread_name(name)
    return any(t.name == wanted and t.is_alive() for t in threading.enumerate())


def _job_threads_alive() -> list[threading.Thread]:
    return [t for t in threading.enumerate()
            if t.name.startswith(inprocess.THREAD_NAME_PREFIX) and t.is_alive()]


def _files(name: str) -> dict[str, object]:
    """Lo que hay en la carpeta del registro del trabajo (para ver que no cambia)."""
    folder = _HANDLES[name].job_dir
    return {
        "state": (folder.path / records.RECORD_FILE).read_bytes(),
        "events": folder.events_file.read_bytes(),
        "log": folder.log_file.read_bytes(),
        "result": folder.result_file.exists(),
    }


def _wait_until(condition, what: str) -> None:
    deadline = time.monotonic() + DEADLINE_S
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"no llegó a tiempo: {what}")
        _poll()
        time.sleep(POLL_S)


def _wait_job_threads(timeout_s: float = DEADLINE_S) -> None:
    deadline = time.monotonic() + timeout_s
    while _job_threads_alive() and time.monotonic() < deadline:
        time.sleep(POLL_S)


def setUpModule() -> None:
    tmp = _support.jobs_tmp()
    base = tmp.__enter__()
    unittest.addModuleCleanup(tmp.__exit__, None, None, None)
    # Las cleanups van al revés: los hilos que sigan vivos acaban antes de borrar la carpeta.
    unittest.addModuleCleanup(_wait_job_threads)
    root = base / "jobs"

    registry = mock.patch.dict(catalog._REGISTRY, clear=True)
    registry.start()
    unittest.addModuleCleanup(registry.stop)
    builtin = next(info for info in catalog.BUILTIN_WORKERS if info.name == "selftest")
    catalog.register_worker(dataclasses.replace(builtin, default_timeout_s=JOB_TIMEOUT_S))
    catalog.register_worker(catalog.WorkerInfo(RAISE_WORKER, "Raising test job",
                                               estimate_s=_quick, run=_raise_run))
    as_process = dataclasses.replace(builtin, policy="subprocess",
                                     default_timeout_s=JOB_TIMEOUT_S)

    options = {"jobs_root": root, "package_dir": EXTENSION_DIR,
               "blender_python": Path(sys.executable)}

    def new_runner():
        return runner.JobRunner(**options)

    sum_runner = new_runner()
    folder = sum_runner.prepare(_request("thread_sum", SUM_PARAMS))
    _STATE["prepared_executor"] = records.read_record(folder).executor
    _submit("thread_sum", sum_runner, folder)
    with mock.patch.dict(catalog._REGISTRY, {"selftest": as_process}):
        _submit("proc_sum", new_runner(), _request("proc_sum", SUM_PARAMS))
    _submit("proc_long", new_runner(), _request("proc_long", LONG_PARAMS))
    _submit("thread_cancel", new_runner(), _request("thread_cancel", CANCEL_PARAMS))
    _submit("thread_raise", new_runner(), _request("thread_raise", {}, worker=RAISE_WORKER))
    _submit("thread_fail", new_runner(), _request("thread_fail", FAIL_PARAMS))
    ignore_runner = new_runner()
    _submit("thread_ignore", ignore_runner,
            _request("thread_ignore", IGNORE_PARAMS, grace_s=GRACE_S))
    shut_runner = new_runner()
    _submit("thread_shut", shut_runner, _request("thread_shut", SHUT_PARAMS))

    # 1. Cancelaciones al lanzar: la suma larga en proceso aparte y la que no atiende.
    cancels: dict[str, bool] = {}
    cancel_wall: dict[str, float] = {}
    cancel_at: dict[str, float] = {}
    for name in ("proc_long", "thread_ignore"):
        cancel_wall[name] = time.time()
        cancel_at[name] = time.monotonic()
        cancels[name] = _HANDLES[name].cancel()
    _STATE["cancels"] = cancels
    _STATE["cancel_wall"] = cancel_wall
    _STATE["cancel_at"] = cancel_at

    # 2. «thread_cancel», en cuanto envía su primer avance; el lanzador de «thread_shut» se
    #    cierra en cuanto su trabajo arranca.
    def cancel_and_close() -> bool:
        if "thread_cancel" not in cancel_at and "progress" in _types("thread_cancel"):
            cancel_wall["thread_cancel"] = time.time()
            cancel_at["thread_cancel"] = time.monotonic()
            cancels["thread_cancel"] = _HANDLES["thread_cancel"].cancel()
            cancels["thread_cancel_again"] = _HANDLES["thread_cancel"].cancel()
        if "shutdown_s" not in _STATE and "start" in _types("thread_shut"):
            started = time.monotonic()
            shut_runner.shutdown(timeout_s=SHUTDOWN_TIMEOUT_S)
            _STATE["shutdown_s"] = time.monotonic() - started
            _STATE["state_after_shutdown"] = _HANDLES["thread_shut"].state
            _STATE["shut_thread_alive"] = _thread_alive("thread_shut")
            _STATE["non_daemon"] = [t for t in threading.enumerate() if not t.daemon]
            _STATE["job_threads_daemon"] = [t.daemon for t in _job_threads_alive()]
            _STATE["shut_files"] = _files("thread_shut")
        return "thread_cancel" in cancel_at and "shutdown_s" in _STATE

    _wait_until(cancel_and_close, "cancelación de «thread_cancel» y cierre de su lanzador")

    # 3. Hasta que todos tienen su final; «thread_after» se lanza en cuanto «thread_ignore»
    #    consta «Cancelado» y no arranca hasta que acaba su hilo.
    final_at: dict[str, float] = {}
    after_states: set[str] = set()

    def all_finished() -> bool:
        now = time.monotonic()
        for name, handle in _HANDLES.items():
            if name not in final_at and handle.result() is not None:
                final_at[name] = now
        if "thread_ignore" in final_at and "thread_after" not in _HANDLES:
            _STATE["ignore_alive_at_final"] = _thread_alive("thread_ignore")
            _STATE["ignore_files"] = _files("thread_ignore")
            _STATE["ignore_updates"] = len(_UPDATES[_HANDLES["thread_ignore"].job_uid])
            _submit("thread_after", ignore_runner, _request("thread_after", AFTER_PARAMS))
        if "thread_after" in _HANDLES:
            state = _HANDLES["thread_after"].state
            if _thread_alive("thread_ignore"):
                after_states.add(state)
            elif state != "queued" and "ignore_alive_at_after_start" not in _STATE:
                _STATE["ignore_alive_at_after_start"] = _thread_alive("thread_ignore")
        return "thread_after" in _HANDLES and len(final_at) == len(_HANDLES)

    _wait_until(all_finished, "final de todos los trabajos")
    _STATE["final_at"] = final_at
    _STATE["after_states"] = after_states

    # 4. Los hilos que no atendían la cancelación acaban por su cuenta: lo que entregan se
    #    descarta.
    _wait_until(lambda: not _job_threads_alive(), "fin de los hilos abandonados")
    for _ in range(3):
        _poll()
        time.sleep(POLL_S)
    _STATE["ignore_files_end"] = _files("thread_ignore")
    _STATE["ignore_updates_end"] = len(_UPDATES[_HANDLES["thread_ignore"].job_uid])
    _STATE["shut_files_end"] = _files("thread_shut")


def _job(name: str):
    handle = _HANDLES[name]
    return handle, handle.result(), records.read_record(handle.job_dir)


def _lines(name: str) -> list[dict]:
    """Las líneas de ``events.jsonl`` del trabajo, en orden (eventos y notas)."""
    path = _HANDLES[name].job_dir.events_file
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _kinds(name: str) -> list[str]:
    return [line.get("note") or line["t"] for line in _lines(name)]


def _log(name: str) -> str:
    return _HANDLES[name].job_dir.log_file.read_text(encoding="utf-8", errors="replace")


class ExecutorChoiceTest(unittest.TestCase):
    """RF-004-03: el lanzador elige el ejecutor con la política del tipo de trabajo."""

    def test_short_job_runs_in_a_thread(self):
        """RF-004-03: una suma estimada en ≤ 5 s de un tipo con ``run`` va al hilo: ya lo
        dice el ``state.json`` «En cola» de ``prepare``, y no tiene proceso propio."""
        self.assertEqual(_STATE["prepared_executor"], "inprocess")
        handle, result, record = _job("thread_sum")
        self.assertEqual(record.executor, "inprocess")
        self.assertIsNone(handle.pid)
        self.assertIsNone(record.pid)
        self.assertEqual(_STATE["state_after_submit"]["thread_sum"], "running")

    def test_long_or_declared_jobs_run_in_a_process(self):
        """RF-004-03: estimada en más de 5 s, o de un tipo declarado ``subprocess``, va a
        proceso aparte, con su proceso."""
        for name in ("proc_long", "proc_sum"):
            with self.subTest(job=name):
                handle, _, record = _job(name)
                self.assertEqual(record.executor, "subprocess")
                self.assertIsInstance(handle.pid, int)
        handle, result, _ = _job("proc_long")
        self.assertTrue(_STATE["cancels"]["proc_long"])
        self.assertEqual(result.state, "cancelled")

    def test_no_bpy_and_no_workers_import(self):
        """RF-004-03: después de ejecutar los trabajos en hilo, ``bpy`` no está en
        ``sys.modules``; ``jobs/inprocess.py`` no importa ``workers/``, ``bl/`` ni
        ``bpy``."""
        self.assertNotIn("bpy", sys.modules)
        source = (EXTENSION_DIR / "jobs" / "inprocess.py").read_text(encoding="utf-8")
        imported: list[str] = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = "." * node.level + (node.module or "")
                imported += [base] + [f"{base}.{alias.name}" for alias in node.names]
        for name in imported:
            with self.subTest(module=name):
                parts = name.lstrip(".").split(".")
                self.assertNotIn(parts[0], ("bpy", "bmesh", "gpu", "mathutils"))
                self.assertNotIn("workers", parts)
                self.assertNotIn("bl", parts)


class SameRecordTest(unittest.TestCase):
    """RF-004-03, RF-004-15: el mismo ``jobs.selftest.run`` en hilo deja el mismo
    seguimiento y el mismo registro que en proceso aparte."""

    def test_same_result(self):
        """RF-004-03: los dos terminan «Terminado» con la suma exacta y el mismo resultado
        (``out/sum.npy`` con la misma huella) y el mismo resumen."""
        results = {name: _job(name)[1] for name in ("thread_sum", "proc_sum")}
        for name, result in results.items():
            with self.subTest(job=name):
                self.assertEqual(result.state, "succeeded", result.error_text)
                self.assertEqual(result.summary["sum"], SUM_N * (SUM_N - 1) // 2)
                output = _HANDLES[name].job_dir.outputs_dir / "sum.npy"
                self.assertEqual(int(np.load(output, allow_pickle=False)),
                                 SUM_N * (SUM_N - 1) // 2)
        thread, process = results["thread_sum"], results["proc_sum"]
        self.assertEqual(thread.outputs, process.outputs)
        self.assertEqual(dict(thread.summary), dict(process.summary))
        self.assertGreater(thread.duration_s, 0.0)
        self.assertEqual(_HANDLES["thread_sum"].frac, 1.0)

    def test_same_events(self):
        """RF-004-03: ``poll`` entrega la misma secuencia de eventos (``start``, ``log``,
        los avances con sus mensajes, ``result``) y ``events.jsonl`` tiene las mismas
        líneas, entre las mismas notas del lanzador."""
        def shape(name):
            return [(event.type, event.frac, event.msg) for event in _events(name)
                    if event.type != "start"]

        self.assertEqual(_types("thread_sum"), _types("proc_sum"))
        self.assertEqual(_types("thread_sum")[0], "start")
        self.assertEqual(shape("thread_sum"), shape("proc_sum"))
        self.assertEqual(_kinds("thread_sum"), _kinds("proc_sum"))
        self.assertEqual(_kinds("thread_sum"),
                         ["launched", "start", "log", "progress", "progress", "progress",
                          "result", "finished"])
        delivered = [event.to_json() for event in _events("thread_sum")]
        self.assertEqual([line for line in _lines("thread_sum") if "v" in line], delivered)
        launched = _lines("thread_sum")[0]
        self.assertEqual((launched["executor"], launched["interpreter"]),
                         ("inprocess", "blender"))

    def test_same_state_json(self):
        """RF-004-03, RF-004-15: ``state.json`` coincide en todo menos el ejecutor, el
        proceso y las horas: tipo, nombre, estado, intérprete con las versiones de Python,
        numpy y BLAS, código (0), resultados y sin error ni cancelación."""
        fields = ("worker", "label", "owner", "project_uid", "operation_uid", "state",
                  "interpreter", "exit_code", "error", "cancel", "outputs", "ingested_at")
        thread = _job("thread_sum")[2]
        process = _job("proc_sum")[2]
        self.assertEqual({f: getattr(thread, f) for f in fields},
                         {f: getattr(process, f) for f in fields})
        self.assertEqual(thread.exit_code, 0)
        self.assertEqual(thread.interpreter.kind, "blender")
        self.assertEqual(thread.interpreter.numpy, np.__version__)
        self.assertLessEqual(thread.queued_at, thread.started_at)
        self.assertLessEqual(thread.started_at, thread.ended_at)
        self.assertIsNotNone(thread.last_event_at)
        self.assertAlmostEqual(thread.duration_s, _HANDLES["thread_sum"].result().duration_s)

    def test_same_logs(self):
        """RF-004-03, RF-004-15: ``job.log`` tiene las líneas del arranque (intérprete y
        versiones), del trabajo y de su fin con el código, y la línea final del lanzador;
        ``result.json`` lleva el mismo resumen."""
        for name in ("thread_sum", "proc_sum"):
            with self.subTest(job=name):
                log = _log(name)
                self.assertRegex(log, r"arranque del (worker|trabajo en un hilo)[^\n]*"
                                      r"intérprete blender, Python \d")
                self.assertIn(f"trabajo {_HANDLES[name].job_uid}: tipo selftest", log)
                self.assertRegex(log, r"termina con el código 0")
                self.assertIn("el trabajo termina «Terminado»", log)
                saved = json.loads(_HANDLES[name].job_dir.result_file.read_text(
                    encoding="utf-8"))
                self.assertEqual(saved["t"], "result")
                self.assertEqual(saved["summary"]["sum"], SUM_N * (SUM_N - 1) // 2)
        self.assertIn("(en hilo, código 0)", _log("thread_sum"))


class InProcessCancelTest(unittest.TestCase):
    """RF-004-09: un trabajo en hilo que atiende la cancelación queda detenido en ≤ 2 s."""

    def test_stops_within_two_seconds(self):
        """RF-004-09: cancelado en curso, para en ≤ 2 s (hora de su evento ``cancelled``)
        y queda «Cancelado», no forzado, con el código 3 y sin resultados."""
        self.assertTrue(_STATE["cancels"]["thread_cancel"])
        handle, result, record = _job("thread_cancel")
        cancelled = [event for event in _events("thread_cancel") if event.type == "cancelled"]
        self.assertEqual(len(cancelled), 1)
        stop_s = cancelled[0].ts - _STATE["cancel_wall"]["thread_cancel"]
        self.assertLessEqual(stop_s, STOP_MAX_S)
        self.assertRegex(cancelled[0].msg, r"^Cancelado en el trozo \d+ de 20$")
        self.assertEqual((result.state, handle.state, record.state), ("cancelled",) * 3)
        self.assertEqual(result.error_code, "job_cancelled")
        self.assertEqual(result.error_text, f"Trabajo «{LABELS['thread_cancel']}» cancelado.")
        self.assertEqual((record.cancel.reason, record.cancel.forced), ("user", False))
        self.assertEqual(record.exit_code, runner.EXIT_CANCELLED)
        self.assertEqual(result.outputs, ())
        self.assertTrue(handle.job_dir.cancel_file.exists())
        notes = [line["note"] for line in _lines("thread_cancel") if "note" in line]
        self.assertEqual(notes, ["launched", "cancel_requested", "finished"])

    def test_second_cancel_has_no_effect(self):
        """RF-004-09: cancelar otra vez el mismo trabajo no hace nada (``False``)."""
        self.assertFalse(_STATE["cancels"]["thread_cancel_again"])
        self.assertEqual(len(_FINISHED[_HANDLES["thread_cancel"].job_uid]), 1)


class InProcessFailureTest(unittest.TestCase):
    """RF-004-03, RF-004-12: un fallo en el hilo deja el trabajo «Fallido» sin afectar al
    proceso de Blender."""

    def test_exception_leaves_failed_with_traceback_in_log(self):
        """RF-004-12: una excepción no prevista deja «Fallido» (``worker_crashed``, código
        1) con un mensaje en español sin traza; la traza está en ``job.log``."""
        handle, result, record = _job("thread_raise")
        self.assertEqual((result.state, record.state), ("failed", "failed"))
        self.assertEqual(result.error_code, "worker_crashed")
        self.assertEqual(record.exit_code, runner.EXIT_CRASHED)
        self.assertIn(LABELS["thread_raise"], result.error_text)
        self.assertNotIn("Traceback", result.error_text)
        self.assertNotIn(RAISE_TEXT, result.error_text)
        log = _log("thread_raise")
        self.assertIn("Traceback (most recent call last)", log)
        self.assertIn(f"RuntimeError: {RAISE_TEXT}", log)
        self.assertIn("excepción no capturada", log)
        self.assertEqual(_types("thread_raise"), ["start", "log"])

    def test_job_failed_keeps_its_code(self):
        """RF-004-12: el fallo explicado del cálculo (``JobFailed``) deja «Fallido» con su
        código y su texto, como en proceso aparte (código 2, evento ``error``)."""
        handle, result, record = _job("thread_fail")
        self.assertEqual(result.state, "failed")
        self.assertEqual(result.error_code, "selftest_failed")
        self.assertEqual(result.error_text,
                         "Autodiagnóstico: fallo provocado en el trozo 2 de 4.")
        self.assertEqual(record.exit_code, runner.EXIT_FAILED)
        self.assertEqual(_types("thread_fail")[-1], "error")
        self.assertNotIn("Traceback", _log("thread_fail"))


class IgnoredCancelTest(unittest.TestCase):
    """RF-004-03, RF-004-09: un trabajo en hilo que no atiende la cancelación queda
    «Cancelado» al vencer su plazo de gracia; lo que entregue después se descarta."""

    def test_cancelled_at_grace_expiry(self):
        """RF-004-09: con su hilo aún vivo, queda «Cancelado» (forzado: no atendió la
        petición) al vencer su plazo de gracia de 1 s, sin código de salida."""
        self.assertTrue(_STATE["cancels"]["thread_ignore"])
        self.assertTrue(_STATE["ignore_alive_at_final"])
        elapsed = _STATE["final_at"]["thread_ignore"] - _STATE["cancel_at"]["thread_ignore"]
        self.assertGreaterEqual(elapsed, GRACE_S)
        self.assertLessEqual(elapsed, GRACE_S + 1.0)
        handle, result, record = _job("thread_ignore")
        self.assertEqual((result.state, record.state), ("cancelled", "cancelled"))
        self.assertEqual(result.error_code, "job_cancelled")
        self.assertIn("(forzado)", result.error_text)
        self.assertTrue(record.cancel.forced)
        self.assertIsNone(record.exit_code)
        abandoned = [line for line in _lines("thread_ignore")
                     if line.get("note") == "abandoned"]
        self.assertEqual(len(abandoned), 1)
        self.assertEqual((abandoned[0]["reason"], abandoned[0]["grace_s"]), ("user", GRACE_S))
        self.assertIn("un hilo no se puede terminar", _log("thread_ignore"))

    def test_late_result_is_discarded(self):
        """RF-004-03: cuando su hilo acaba, su resultado se descarta: sin resultados ni
        resumen, sin ``result.json`` ni evento ``result``, y su registro, sus eventos y su
        ``job.log`` no cambian; ``on_finish`` se llamó una vez."""
        handle, result, record = _job("thread_ignore")
        self.assertEqual(result.outputs, ())
        self.assertEqual(dict(result.summary), {})
        self.assertEqual(record.outputs, ())
        self.assertEqual(_STATE["ignore_files_end"], _STATE["ignore_files"])
        self.assertFalse(_STATE["ignore_files_end"]["result"])
        self.assertNotIn("result", [line.get("t") for line in _lines("thread_ignore")])
        self.assertEqual(_STATE["ignore_updates_end"], _STATE["ignore_updates"])
        self.assertEqual(len(_FINISHED[handle.job_uid]), 1)

    def test_thread_slot_freed_when_it_ends(self):
        """RF-004-03 (plan §5.4.5): mientras el hilo abandonado sigue vivo, el siguiente
        trabajo en hilo de su lanzador espera «En cola»; arranca cuando acaba y termina
        bien."""
        self.assertEqual(_STATE["state_after_submit"]["thread_after"], "queued")
        self.assertEqual(_STATE["after_states"], {"queued"})
        self.assertFalse(_STATE["ignore_alive_at_after_start"])
        _, result, record = _job("thread_after")
        self.assertEqual(result.state, "succeeded", result.error_text)
        self.assertEqual(record.executor, "inprocess")


class InProcessShutdownTest(unittest.TestCase):
    """RF-004-13: un hilo que no atiende la cancelación no retiene el cierre."""

    def test_shutdown_returns_in_time(self):
        """RF-004-13: con el hilo vivo, ``shutdown(timeout_s=3)`` vuelve en ≤ 3,5 s (tras
        esperarlo 1 s) y el hilo sigue vivo al volver: no se espera."""
        self.assertLessEqual(_STATE["shutdown_s"], SHUTDOWN_MAX_S)
        self.assertGreaterEqual(_STATE["shutdown_s"], runner.SHUTDOWN_STOP_WAIT_S)
        self.assertTrue(_STATE["shut_thread_alive"])

    def test_only_the_main_thread_is_not_daemon(self):
        """RF-004-13: al volver ``shutdown``, el único hilo que no es *daemon* es el
        principal: los hilos de los trabajos lo son."""
        self.assertEqual(_STATE["non_daemon"], [threading.main_thread()])
        self.assertTrue(_STATE["job_threads_daemon"])
        self.assertTrue(all(_STATE["job_threads_daemon"]))

    def test_marked_interrupted_and_result_discarded(self):
        """RF-004-13: el trabajo consta «Interrumpido» al volver ``shutdown`` (motivo
        ``shutdown``, forzado, nota ``abandoned``), su final se cuenta en el siguiente
        sondeo y lo que entrega su hilo al acabar se descarta."""
        self.assertEqual(_STATE["state_after_shutdown"], "interrupted")
        handle, result, record = _job("thread_shut")
        self.assertEqual((result.state, record.state), ("interrupted", "interrupted"))
        self.assertEqual(result.error_code, "job_interrupted")
        self.assertEqual((record.cancel.reason, record.cancel.forced), ("shutdown", True))
        abandoned = next(line for line in _lines("thread_shut")
                         if line.get("note") == "abandoned")
        self.assertEqual(abandoned["shutdown_wait_s"], runner.SHUTDOWN_STOP_WAIT_S)
        self.assertEqual(len(_FINISHED[handle.job_uid]), 1)
        self.assertEqual(_STATE["shut_files_end"], _STATE["shut_files"])
        self.assertFalse(_STATE["shut_files_end"]["result"])


class ExecutorTest(unittest.TestCase):
    """RF-004-03: el ejecutor en hilo usa la tabla de códigos del proceso aparte y comprueba
    sus argumentos."""

    def test_same_codes_as_the_launcher(self):
        """RF-004-03: los códigos del hilo son los del arranque del proceso aparte."""
        for name in ("EXIT_OK", "EXIT_CRASHED", "EXIT_FAILED", "EXIT_CANCELLED"):
            with self.subTest(code=name):
                self.assertEqual(getattr(inprocess, name), getattr(runner, name))

    def test_rejects_a_foreign_folder_or_no_function(self):
        """RF-004-03: una carpeta que no es la de la petición es ``ValueError`` y una
        función que no se puede llamar, ``TypeError``; no arranca ningún hilo."""
        request = protocol.new_request("selftest", label="Argumentos", owner="jobs")
        before = threading.active_count()
        with _support.temp_jobs_root() as root:
            other = protocol.new_request("selftest", label="Otra", owner="jobs")
            folder = import_geoblender("jobs.paths").job_dir(root, other.job_uid).create()
            with self.assertRaises(ValueError):
                inprocess.InProcessExecutor(request, folder, _raise_run)
            own = import_geoblender("jobs.paths").job_dir(root, request.job_uid).create()
            with self.assertRaises(TypeError):
                inprocess.InProcessExecutor(request, own, "no es una función")
        self.assertEqual(threading.active_count(), before)


if __name__ == "__main__":
    unittest.main()
