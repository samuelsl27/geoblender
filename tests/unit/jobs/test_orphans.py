# SPDX-License-Identifier: GPL-3.0-or-later
"""Cierre del lanzador y procesos huérfanos (spec 004, T13; HU-004-6, RF-004-13; plan 004
§5.3.3, §5.4.3 y §5.4.5).

Al cerrarse Blender o desactivarse Geoblender, ``JobRunner.shutdown`` pide parar a todos sus
trabajos, espera hasta 1 s, termina el *Job Object* de los que siguen vivos (el worker y lo
que lanzó) y los deja «Interrumpido», también a los de la cola, todo en ≤ 3 s. Si el proceso
de Blender muere de golpe, Windows cierra el *handle* del *Job Object* de cada worker y
termina el worker y sus hijos; la vigilancia del padre (fin de la entrada estándar, paso 3
del arranque) es la segunda capa. No queda ningún proceso huérfano.

Para no esperar en serie, todo se lanza a la vez al empezar (``setUpModule``) y cada prueba
mira lo que quedó:

- (a) ``running``, ``ignore`` y ``queued``: un lanzador de dos huecos con dos sumas largas en
  curso (``ignore`` no atiende la cancelación) y una tercera en la cola; se cierra con
  ``shutdown(timeout_s=3)``.
- (b) dos procesos intermedios, que hacen de Blender: cada uno lanza un trabajo con su propio
  lanzador, espera a que esté en marcha, cuenta sus procesos y muere con ``os._exit`` sin
  cerrar nada. ``job``: un worker que lanza un nieto ``python -c "import time;
  time.sleep(60)"``; ``eof``: una suma larga sin *Job Object* (como si Windows no lo
  admitiera), donde solo actúa la vigilancia del padre.
- (c) ``forced``: en este proceso, el worker que lanza el nieto y no atiende la cancelación;
  se cancela con el plazo de gracia mínimo (1 s) y el lanzador lo termina a la fuerza.

Los trabajos usan una copia del paquete con el worker de prueba ``gbtest_orphans``.
"""

import dataclasses
import json
import shutil
import subprocess
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
messages = import_geoblender("jobs.messages")
protocol = import_geoblender("jobs.protocol")
records = import_geoblender("jobs.records")
runner = import_geoblender("jobs.runner")

TEST_WORKER = "gbtest_orphans"
LONG_SUM = {"n": 1000, "chunks": 40, "sleep_s": 0.5}
"""20 s si nadie la para."""
QUICK_SUM = {"n": 1000, "chunks": 2}
GRACE_S = 1.0
"""El plazo de gracia mínimo válido (el del caso ``forced``)."""
SHUTDOWN_TIMEOUT_S = 3.0
"""RF-004-13 (tarea T13): ``shutdown`` termina todo en ≤ 3 s."""
ORPHAN_MAX_S = 5.0
"""RF-004-13: los workers, y lo que lanzaron, dejan de existir en ≤ 5 s."""
WATCH_EXTRA_S = 2.0
"""Lo que se sigue mirando un proceso después del plazo, para medir una muerte tardía."""
JOB_TIMEOUT_S = 120.0
DEADLINE_S = 30.0
POLL_S = 0.02
INTERMEDIATE_EXIT = 9
GRANDCHILD_PREFIX = "nieto "
CLOSING_JOBS = ("running", "ignore", "queued")
CREATION_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)

LABELS = {
    "running": "Cierre en curso",
    "ignore": "Cierre sin atender",
    "queued": "Cierre en cola",
    "forced": "Nieto cancelado a la fuerza",
    "late": "Después del cierre",
}
"""El nombre de cada trabajo (su ``label``), el que citan los mensajes."""

# Worker de prueba que se añade a la copia del paquete: lanza un nieto que duerme 60 s,
# avisa de su pid y espera sin atender la cancelación.
TEST_WORKER_SOURCE = '''# SPDX-License-Identifier: GPL-3.0-or-later
"""Worker de las pruebas de huérfanos: lanza un nieto y no atiende la cancelación."""

import subprocess
import sys
import time

GRANDCHILD = "import time; time.sleep(60)"


def main(ctx):
    child = subprocess.Popen(
        [sys.executable, "-B", "-I", "-c", GRANDCHILD],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    ctx.log("info", f"nieto {child.pid}")
    end = time.monotonic() + 60
    while time.monotonic() < end:
        time.sleep(0.05)
    return {"grandchild": child.pid}
'''

# Proceso intermedio: hace de Blender. Carga la copia del paquete por ruta (como el arranque
# de los workers), lanza un trabajo con su propio lanzador, espera a que esté en marcha,
# escribe en su salida una línea JSON con sus procesos y muere con os._exit sin cerrar nada.
INTERMEDIATE_SOURCE = '''# SPDX-License-Identifier: GPL-3.0-or-later
"""Proceso intermedio de las pruebas de huérfanos (hace de Blender)."""

import sys

sys.dont_write_bytecode = True

import dataclasses  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

package_dir, jobs_root, mode = sys.argv[1:4]
spec = importlib.util.spec_from_file_location(
    "geoblender", os.path.join(package_dir, "__init__.py"),
    submodule_search_locations=[package_dir],
)
module = importlib.util.module_from_spec(spec)
sys.modules["geoblender"] = module
spec.loader.exec_module(module)

from geoblender.jobs import catalog, protocol, runner, winjob  # noqa: E402

if mode == "eof":
    winjob.supported = lambda: False  # sin Job Object: solo vigila el fin de stdin

builtin = next(info for info in catalog.BUILTIN_WORKERS if info.name == "selftest")
catalog.register_worker(dataclasses.replace(builtin, policy="subprocess",
                                            default_timeout_s=120.0))
catalog.register_worker(catalog.WorkerInfo("gbtest_orphans", "Orphans test worker",
                                           policy="subprocess", default_timeout_s=120.0))
job_runner = runner.JobRunner(jobs_root=Path(jobs_root), package_dir=Path(package_dir),
                              blender_python=Path(sys.executable))
if mode == "eof":
    request = protocol.new_request("selftest", label="Huérfano sin Job Object", owner="jobs",
                                   params={"n": 1000, "chunks": 40, "sleep_s": 0.5})
else:
    request = protocol.new_request("gbtest_orphans", label="Huérfano con nieto", owner="jobs")
handle = job_runner.submit(request)
report = {"pid": os.getpid(), "worker": handle.pid, "job_dir": str(handle.job_dir.path),
          "job_object": winjob.supported()}
deadline = time.monotonic() + 30.0
while "ready" not in report:
    if time.monotonic() > deadline or handle.result() is not None:
        report["error"] = f"el trabajo no llegó a estar en marcha: {handle.state} {handle.message}"
        break
    for update in job_runner.poll():
        for event in update.events:
            if mode == "eof" and event.type == "start":
                report["ready"] = True
            if event.type == "log" and event.msg.startswith("nieto "):
                report["grandchild"] = int(event.msg.split()[1])
                report["ready"] = True
    time.sleep(0.02)
report["exit_at"] = time.time()
print(json.dumps(report), flush=True)
os._exit(9)
'''

_HANDLES: dict[str, object] = {}
_RUNNERS: dict[str, object] = {}
_UPDATES: dict[str, list] = {}
_FINISHED: dict[str, list] = {}
_INTERMEDIATES: dict[str, "_Intermediate"] = {}
_STATE: dict[str, object] = {}


class _Intermediate:
    """Un proceso intermedio lanzado por la prueba. Un hilo espera su informe (la línea JSON
    que escribe antes de morir) y, desde ese momento, apunta con la hora del sistema cuándo
    deja de existir cada proceso que lanzó (``worker`` y, si lo hay, ``grandchild``)."""

    def __init__(self, script: Path, package: Path, jobs_root: Path, mode: str) -> None:
        jobs_root.mkdir()
        self.process = subprocess.Popen(
            [sys.executable, "-B", "-I", str(script), str(package), str(jobs_root), mode],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=CREATION_FLAGS,
        )
        self.report: dict = {}
        self.dead_at: dict[str, float] = {}
        self.error: str | None = None
        self.stderr = ""
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def join(self) -> None:
        self._thread.join(DEADLINE_S + ORPHAN_MAX_S + WATCH_EXTRA_S)

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.kill()

    def _watch(self) -> None:
        try:
            out, err = self.process.communicate(timeout=DEADLINE_S)
        except subprocess.TimeoutExpired:
            self.error = "el proceso intermedio no terminó a tiempo"
            return
        self.stderr = err.decode("utf-8", "replace")
        try:
            self.report = json.loads(out.decode("utf-8").strip().splitlines()[-1])
        except (IndexError, ValueError):
            self.error = f"el proceso intermedio no informó: {self.stderr[-2000:]}"
            return
        pids = {name: self.report[name] for name in ("worker", "grandchild")
                if isinstance(self.report.get(name), int)}
        until = time.monotonic() + ORPHAN_MAX_S + WATCH_EXTRA_S
        while pids and time.monotonic() < until:
            for name, pid in list(pids.items()):
                if not _support.pid_alive(pid):
                    self.dead_at[name] = time.time()
                    del pids[name]
            if pids:
                time.sleep(POLL_S)


def _request(name: str, worker: str = "selftest", params: dict | None = None, **options):
    return protocol.new_request(worker, label=LABELS[name], owner="jobs", params=params,
                                **options)


def _on_finish(result) -> None:
    _FINISHED.setdefault(result.job_uid, []).append(result)


def _submit(name: str, job_runner, request) -> None:
    _HANDLES[name] = job_runner.submit(request, on_finish=_on_finish)


def _poll(job_runner) -> list:
    updates = job_runner.poll()
    for update in updates:
        _UPDATES.setdefault(update.job_uid, []).append(update)
    return updates


def _events(name: str) -> list:
    return [event for update in _UPDATES.get(_HANDLES[name].job_uid, ())
            for event in update.events]


def _grandchild(name: str) -> int | None:
    for event in _events(name):
        if event.type == "log" and event.msg.startswith(GRANDCHILD_PREFIX):
            return int(event.msg[len(GRANDCHILD_PREFIX):])
    return None


def _wait_for(condition, what: str, *job_runners) -> None:
    deadline = time.monotonic() + DEADLINE_S
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"no llegó a tiempo: {what}")
        for job_runner in job_runners:
            _poll(job_runner)
        time.sleep(POLL_S)


def _close_runners() -> None:
    """Limpieza: ningún worker de este módulo sigue vivo al acabar, pase lo que pase."""
    for job_runner in _RUNNERS.values():
        job_runner.shutdown(timeout_s=SHUTDOWN_TIMEOUT_S)


def _state_bytes(names) -> dict[str, bytes]:
    return {name: (_HANDLES[name].job_dir.path / records.RECORD_FILE).read_bytes()
            for name in names}


def setUpModule() -> None:
    tmp = _support.jobs_tmp()
    base = tmp.__enter__()
    unittest.addModuleCleanup(tmp.__exit__, None, None, None)

    registry = mock.patch.dict(catalog._REGISTRY, clear=True)
    registry.start()
    unittest.addModuleCleanup(registry.stop)
    builtin = next(info for info in catalog.BUILTIN_WORKERS if info.name == "selftest")
    catalog.register_worker(dataclasses.replace(builtin, policy="subprocess",
                                                default_timeout_s=JOB_TIMEOUT_S))
    catalog.register_worker(catalog.WorkerInfo(TEST_WORKER, "Orphans test worker",
                                               policy="subprocess",
                                               default_timeout_s=JOB_TIMEOUT_S))

    copy = base / "pkg"
    shutil.copytree(
        EXTENSION_DIR, copy,
        ignore=shutil.ignore_patterns("__pycache__", "*.py[cod]", "bl", "resources",
                                      "thirdparty", "wheels"),
    )
    (copy / "workers" / f"{TEST_WORKER}.py").write_bytes(TEST_WORKER_SOURCE.encode("utf-8"))
    script = base / "intermedio.py"
    script.write_bytes(INTERMEDIATE_SOURCE.encode("utf-8"))

    # 1. Los procesos intermedios, primero: son los que más tardan en arrancar.
    for name, mode in (("job", "grandchild"), ("eof", "eof")):
        intermediate = _Intermediate(script, copy, base / f"jobs_{name}", mode)
        _INTERMEDIATES[name] = intermediate
        unittest.addModuleCleanup(intermediate.close)

    # 2. Los trabajos de este proceso.
    root = base / "jobs"
    root.mkdir()
    _STATE["root"] = root
    options = {"jobs_root": root, "package_dir": copy, "blender_python": Path(sys.executable)}
    closing = runner.JobRunner(**options, max_subprocess=2)
    forced = runner.JobRunner(**options, max_subprocess=1)
    _RUNNERS.update(closing=closing, forced=forced)
    unittest.addModuleCleanup(_close_runners)
    _submit("running", closing, _request("running", params=LONG_SUM))
    _submit("ignore", closing, _request("ignore", params={**LONG_SUM, "ignore_cancel": True}))
    _submit("queued", closing, _request("queued", params=LONG_SUM))
    _submit("forced", forced, _request("forced", TEST_WORKER, grace_s=GRACE_S))
    _STATE["queued_before"] = (_HANDLES["queued"].state, _HANDLES["queued"].pid)

    def started() -> bool:
        return ("start" in [event.type for event in _events("running")]
                and "start" in [event.type for event in _events("ignore")]
                and _grandchild("forced") is not None)

    _wait_for(started, "arranque de los trabajos", closing, forced)

    # 3. A la vez: cancelar «forced» (vence su plazo de gracia mientras se cierra el otro
    #    lanzador) y cerrar «closing».
    grandchild = _grandchild("forced")
    _STATE["forced_grandchild"] = grandchild
    _STATE["grandchild_alive_at_cancel"] = _support.pid_alive(grandchild)
    _STATE["forced_cancel"] = forced.cancel(_HANDLES["forced"].job_uid)
    workers = {name: _HANDLES[name].pid for name in ("running", "ignore")}
    begin = time.monotonic()
    try:
        closing.shutdown(timeout_s=SHUTDOWN_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - lo comprueban las pruebas de (a)
        _STATE["shutdown_error"] = exc
    _STATE["shutdown_s"] = time.monotonic() - begin
    _STATE["alive_after_shutdown"] = {name: _support.pid_alive(pid)
                                      for name, pid in workers.items()}
    _STATE["states_after_shutdown"] = {name: _HANDLES[name].state for name in CLOSING_JOBS}
    _STATE["finished_during_shutdown"] = sum(
        len(_FINISHED.get(_HANDLES[name].job_uid, ())) for name in CLOSING_JOBS)

    # 4. Los finales se cuentan en el siguiente sondeo; cerrar otra vez no cambia nada; y no
    #    se admiten trabajos nuevos.
    if "shutdown_error" not in _STATE:
        _STATE["finals"] = _poll(closing)
        _STATE["second_poll"] = _poll(closing)
        closed = _state_bytes(CLOSING_JOBS)
        begin = time.monotonic()
        closing.shutdown(timeout_s=SHUTDOWN_TIMEOUT_S)
        _STATE["second_shutdown_s"] = time.monotonic() - begin
        _STATE["unchanged_after_second"] = _state_bytes(CLOSING_JOBS) == closed
        folders = sorted(path.name for path in root.iterdir())
        try:
            closing.submit(_request("late", params=QUICK_SUM))
        except RuntimeError as exc:
            _STATE["late_error"] = exc
        _STATE["folders_unchanged"] = sorted(path.name for path in root.iterdir()) == folders

    # 5. «forced», hasta que acaba, apuntando cuándo deja de existir cada proceso.
    dead_at: dict[str, float] = {}
    pids = {"worker": _HANDLES["forced"].pid, "grandchild": grandchild}

    def forced_done() -> bool:
        for name, pid in pids.items():
            if name not in dead_at and not _support.pid_alive(pid):
                dead_at[name] = time.time()
        return _HANDLES["forced"].result() is not None and len(dead_at) == len(pids)

    _wait_for(forced_done, "terminación forzada de «forced»", forced)
    _STATE["forced_dead_at"] = dead_at

    # 6. Los procesos intermedios.
    for intermediate in _INTERMEDIATES.values():
        intermediate.join()


def _lines(name: str) -> list[dict]:
    """Las líneas de ``events.jsonl`` del trabajo, en orden (eventos y notas)."""
    text = _HANDLES[name].job_dir.events_file.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def _notes(name: str) -> list[str]:
    return [line["note"] for line in _lines(name) if "note" in line]


def _log(path_or_name) -> str:
    path = (_HANDLES[path_or_name].job_dir.log_file if isinstance(path_or_name, str)
            else path_or_name)
    return path.read_text(encoding="utf-8", errors="replace")


class _ClosingCase(unittest.TestCase):
    """Comprobaciones comunes de los trabajos del lanzador que se cierra."""

    def setUp(self) -> None:
        error = _STATE.get("shutdown_error")
        if error is not None:
            self.fail(f"shutdown lanzó {type(error).__name__}: {error}")

    def interrupted(self, name: str):
        """El trabajo ``name`` quedó «Interrumpido» (``job_interrupted``, con su nombre) en
        su :class:`JobResult`, su *handle* y su ``state.json``, con la cancelación por el
        cierre y sin resultados; devuelve su ``state.json``."""
        handle = _HANDLES[name]
        result = handle.result()
        record = records.read_record(handle.job_dir)
        self.assertEqual((result.state, handle.state, record.state), ("interrupted",) * 3)
        expected = messages.render("job_interrupted", job=LABELS[name])
        self.assertEqual(expected, f"El trabajo «{LABELS[name]}» quedó interrumpido: "
                                   "Geoblender se cerró mientras se ejecutaba.")
        self.assertEqual((result.error_code, result.error_text), ("job_interrupted", expected))
        self.assertEqual(handle.message, expected)
        self.assertEqual((record.error.code, record.error.text), ("job_interrupted", expected))
        self.assertEqual(record.cancel.reason, "shutdown")
        self.assertIsNotNone(record.ended_at)
        self.assertEqual((result.outputs, record.outputs), ((), ()))
        self.assertIn("el trabajo termina «Interrumpido»", _log(name))
        notes = _notes(name)
        self.assertEqual(notes[-1], "finished")
        return record


class ShutdownTest(_ClosingCase):
    """RF-004-13 (a): ``shutdown`` con dos trabajos en curso y uno en cola termina todo en
    ≤ 3 s y los deja «Interrumpido»."""

    def test_everything_ends_within_three_seconds(self):
        """RF-004-13: ``shutdown(timeout_s=3)`` vuelve en ≤ 3 s y, al volver, ya no existe
        ninguno de los dos workers (tampoco el que no atiende la cancelación, que se
        terminó tras esperarlo 1 s)."""
        self.assertLessEqual(_STATE["shutdown_s"], SHUTDOWN_TIMEOUT_S)
        self.assertGreaterEqual(_STATE["shutdown_s"], runner.SHUTDOWN_STOP_WAIT_S)
        self.assertEqual(_STATE["alive_after_shutdown"], {"running": False, "ignore": False})

    def test_all_marked_interrupted(self):
        """RF-004-13: los tres trabajos constan «Interrumpido» al volver ``shutdown``, en el
        *handle*, en el resultado y en ``state.json``, con su mensaje en español."""
        self.assertEqual(_STATE["states_after_shutdown"],
                         dict.fromkeys(CLOSING_JOBS, "interrupted"))
        for name in CLOSING_JOBS:
            with self.subTest(job=name):
                self.interrupted(name)

    def test_running_job_was_asked_to_stop(self):
        """RF-004-13: al que atiende la petición se le pidió parar (centinela ``cancel``,
        nota con el motivo ``shutdown``) y paró solo (salida 3, no forzado); su evento
        ``cancelled`` llega en su final, sin perderse."""
        record = self.interrupted("running")
        self.assertTrue(_HANDLES["running"].job_dir.cancel_file.exists())
        self.assertEqual(record.exit_code, runner.EXIT_CANCELLED)
        self.assertFalse(record.cancel.forced)
        notes = _notes("running")
        self.assertLess(notes.index("cancel_requested"), notes.index("finished"))
        self.assertNotIn("terminated", notes)
        requested = next(line for line in _lines("running")
                         if line.get("note") == "cancel_requested")
        self.assertEqual(requested["reason"], "shutdown")
        self.assertIn("cancelled", [event.type for event in _events("running")])
        self.assertIn("se pidió cancelar el trabajo al cerrarse Geoblender", _log("running"))

    def test_ignoring_job_was_terminated(self):
        """RF-004-13: al que no atiende la petición se le terminó su *Job Object* tras
        esperarlo 1 s: forzado, con el código del lanzador, nota ``terminated`` y la
        terminación en ``job.log``."""
        record = self.interrupted("ignore")
        self.assertTrue(record.cancel.forced)
        self.assertEqual(record.exit_code, runner.EXIT_TERMINATED)
        notes = _notes("ignore")
        self.assertLess(notes.index("cancel_requested"), notes.index("terminated"))
        self.assertLess(notes.index("terminated"), notes.index("finished"))
        terminated = next(line for line in _lines("ignore") if line.get("note") == "terminated")
        self.assertEqual((terminated["reason"], terminated["shutdown_wait_s"]),
                         ("shutdown", runner.SHUTDOWN_STOP_WAIT_S))
        self.assertIn("al cerrarse Geoblender, el worker seguía vivo tras esperarlo 1 s",
                      _log("ignore"))

    def test_queued_job_never_started(self):
        """RF-004-13: el de la cola queda «Interrumpido» sin haber arrancado: sin proceso,
        sin hora de inicio ni salida, sin nota de arranque y sin centinela."""
        self.assertEqual(_STATE["queued_before"], ("queued", None))
        record = self.interrupted("queued")
        handle = _HANDLES["queued"]
        self.assertIsNone(handle.pid)
        self.assertIsNone(record.pid)
        self.assertIsNone(record.started_at)
        self.assertIsNone(record.exit_code)
        self.assertIsNone(handle.result().duration_s)
        self.assertEqual(_notes("queued"), ["finished"])
        self.assertFalse(handle.job_dir.cancel_file.exists())

    def test_finals_reported_by_the_next_poll(self):
        """RF-004-13: ``shutdown`` no llama a ningún ``on_finish``; el siguiente ``poll``
        cuenta los tres finales (y llama a cada ``on_finish`` una vez) y el otro, nada."""
        self.assertEqual(_STATE["finished_during_shutdown"], 0)
        finals = {update.job_uid: update for update in _STATE["finals"]}
        expected = {_HANDLES[name].job_uid: name for name in CLOSING_JOBS}
        self.assertEqual(set(finals), set(expected))
        for uid, name in expected.items():
            with self.subTest(job=name):
                self.assertTrue(finals[uid].finished)
                self.assertEqual(finals[uid].result.state, "interrupted")
                self.assertEqual(_FINISHED[uid], [_HANDLES[name].result()])
        self.assertEqual(_STATE["second_poll"], [])

    def test_closed_runner(self):
        """RF-004-13: cerrar otra vez vuelve al momento sin tocar ningún ``state.json``, y
        el lanzador cerrado no admite trabajos nuevos (``RuntimeError``) ni crea su
        carpeta."""
        self.assertLess(_STATE["second_shutdown_s"], 0.5)
        self.assertTrue(_STATE["unchanged_after_second"])
        self.assertTrue(_RUNNERS["closing"].closed)
        self.assertIsInstance(_STATE.get("late_error"), RuntimeError)
        self.assertIn("cerrado", str(_STATE["late_error"]))
        self.assertTrue(_STATE["folders_unchanged"])


class _IntermediateCase(unittest.TestCase):
    """Comprobaciones comunes de un proceso intermedio que muere de golpe."""

    def intermediate(self, name: str) -> "_Intermediate":
        """El proceso intermedio ``name`` puso su trabajo en marcha, informó de sus
        procesos y murió con ``os._exit``."""
        intermediate = _INTERMEDIATES[name]
        self.assertIsNone(intermediate.error)
        self.assertNotIn("error", intermediate.report, intermediate.stderr)
        self.assertEqual(intermediate.process.returncode, INTERMEDIATE_EXIT)
        return intermediate

    def dead_within(self, intermediate: "_Intermediate", process: str) -> None:
        """El proceso ``process`` que lanzó dejó de existir en ≤ 5 s desde que el
        intermedio murió (hora de antes de ``os._exit``)."""
        self.assertIn(process, intermediate.dead_at,
                      f"«{process}» seguía vivo {ORPHAN_MAX_S + WATCH_EXTRA_S} s después")
        elapsed = intermediate.dead_at[process] - intermediate.report["exit_at"]
        self.assertLessEqual(elapsed, ORPHAN_MAX_S)


class ParentDeathTest(_IntermediateCase):
    """RF-004-13 (b): si muere el proceso que lanzó un worker, el worker deja de existir en
    ≤ 5 s, con *Job Object* y, sin él, por la vigilancia del padre."""

    def test_worker_dies_with_its_launcher(self):
        """RF-004-13: un proceso intermedio lanza un worker (en su *Job Object*) y muere con
        ``os._exit``: según ``pid_alive``, el worker deja de existir en ≤ 5 s."""
        intermediate = self.intermediate("job")
        self.assertTrue(intermediate.report["job_object"])
        self.dead_within(intermediate, "worker")

    def test_parent_watch_without_job_object(self):
        """RF-004-13: sin *Job Object*, el worker ve el fin de su entrada estándar al morir
        el proceso intermedio y termina con el código 4 en ≤ 5 s (lo dice su
        ``job.log``)."""
        intermediate = self.intermediate("eof")
        self.assertFalse(intermediate.report["job_object"])
        self.dead_within(intermediate, "worker")
        log = _log(Path(intermediate.report["job_dir"]) / "job.log")
        self.assertIn("el proceso padre ya no está (fin de la entrada estándar): el worker "
                      "termina con el código 4", log)


class GrandchildTest(_IntermediateCase):
    """RF-004-13 (c): un nieto que lanzó el worker deja de existir en ≤ 5 s tras la
    terminación forzada del worker y tras la muerte del proceso que lo lanzó."""

    def test_grandchild_dies_after_forced_cancel(self):
        """RF-004-10, RF-004-13: el nieto vivía cuando se canceló el worker (que no atiende
        la cancelación); al vencer el plazo de gracia el lanzador terminó el *Job Object*
        (forzado, código 137) y el nieto dejó de existir en ≤ 5 s desde esa terminación
        (nota ``terminated`` de ``events.jsonl``)."""
        self.assertTrue(_STATE["forced_cancel"])
        self.assertTrue(_STATE["grandchild_alive_at_cancel"])
        handle = _HANDLES["forced"]
        record = records.read_record(handle.job_dir)
        self.assertEqual((handle.result().state, record.state), ("cancelled", "cancelled"))
        self.assertEqual((record.cancel.reason, record.cancel.forced), ("user", True))
        self.assertEqual(record.exit_code, runner.EXIT_TERMINATED)
        terminated = next(line for line in _lines("forced") if line.get("note") == "terminated")
        dead_at = _STATE["forced_dead_at"]
        self.assertLessEqual(dead_at["grandchild"] - terminated["ts"], ORPHAN_MAX_S)
        self.assertLessEqual(dead_at["worker"] - terminated["ts"], ORPHAN_MAX_S)

    def test_grandchild_dies_with_the_launcher(self):
        """RF-004-13: el worker de un proceso intermedio lanzó un nieto; al morir el
        intermedio con ``os._exit``, el nieto deja de existir en ≤ 5 s."""
        intermediate = self.intermediate("job")
        self.assertIsInstance(intermediate.report.get("grandchild"), int)
        self.dead_within(intermediate, "grandchild")


class NoOrphanTest(unittest.TestCase):
    """RF-004-13: al final no queda vivo ningún proceso de los que se lanzaron."""

    def test_no_process_left(self):
        """RF-004-13: ni los workers ni los nietos ni los procesos intermedios siguen
        vivos."""
        pids = {name: _HANDLES[name].pid for name in ("running", "ignore", "forced")}
        pids["forced_grandchild"] = _STATE["forced_grandchild"]
        for key, intermediate in _INTERMEDIATES.items():
            pids[f"{key}_intermediate"] = intermediate.process.pid
            for process in ("worker", "grandchild"):
                if isinstance(intermediate.report.get(process), int):
                    pids[f"{key}_{process}"] = intermediate.report[process]
        self.assertEqual(len(pids), 9)
        for name, pid in pids.items():
            with self.subTest(process=name):
                self.assertFalse(_support.pid_alive(pid))


if __name__ == "__main__":
    unittest.main()
