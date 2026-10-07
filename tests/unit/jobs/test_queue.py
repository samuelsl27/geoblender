# SPDX-License-Identifier: GPL-3.0-or-later
"""Cola, máximos de trabajos a la vez y entorno del worker (spec 004, T15; RF-004-04;
plan 004 §5.3.1, §5.3.3, §5.4.2 y §6, D-2).

Como mucho ``max_subprocess`` workers en proceso aparte (2 por defecto) y ``max_inprocess``
trabajos en hilo (1 por defecto) a la vez; los demás esperan «En cola» y arrancan por orden
de llegada en cuanto queda sitio. ``reconfigure`` cambia el máximo de procesos y la raíz de
los trabajos sin parar el lanzador. El worker hereda el entorno de Blender sin variables
``PYTHON*`` ni ``PIP_*`` y con ``OPENBLAS_NUM_THREADS``, ``OMP_NUM_THREADS`` y
``MKL_NUM_THREADS`` = ``max(1, cpu // max_subprocess)`` si el usuario no las fijó
(``jobs/interpreter.py``: ``child_env`` y ``blas_threads_for``).

Para no esperar en serie, todos los trabajos se lanzan a la vez al empezar
(``setUpModule``), cada escenario con su lanzador, y se sondean hasta que acaban; en cada
sondeo se cuenta cuántos hay en curso y cuántos procesos siguen vivos:

- ``fifo``: 5 sumas en proceso aparte con el máximo por defecto (2).
- ``env``: un intérprete falso (``.cmd``) que guarda su entorno en la carpeta del trabajo;
  se lanza con variables ``PYTHON*``, ``PIP_*`` y la ``OMP_NUM_THREADS`` del usuario en el
  entorno, una vez con el máximo 2 y otra tras ``reconfigure(max_subprocess=4)``.
- ``up``: 3 sumas con el máximo 1; después, ``reconfigure(max_subprocess=3)``.
- ``down``: 3 sumas con el máximo 2; ``reconfigure(max_subprocess=1)`` con dos en curso.
- ``threads``: 3 sumas en hilo con ``max_inprocess = 2`` y, detrás, una en proceso aparte.
- ``moved``: una suma en hilo en una raíz y, tras ``reconfigure(jobs_root=…)``, otra en la
  nueva (con el máximo de hilos por defecto, 1).
"""

import dataclasses
import json
import os
import sys
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from tests.support import jobs_fixtures as _support
from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR

catalog = import_geoblender("jobs.catalog")
interpreter = import_geoblender("jobs.interpreter")
protocol = import_geoblender("jobs.protocol")
records = import_geoblender("jobs.records")
runner = import_geoblender("jobs.runner")

SUM_PARAMS = {"n": 1000, "chunks": 2, "sleep_s": 0.1}
"""0,2 s estimados: en hilo con la política del autodiagnóstico; en proceso aparte, con el
tipo declarado ``subprocess`` mientras se lanza."""
JOB_TIMEOUT_S = 120.0
DEADLINE_S = 30.0
POLL_S = 0.02

FIFO = ("fifo_1", "fifo_2", "fifo_3", "fifo_4", "fifo_5")
UP = ("up_1", "up_2", "up_3")
DOWN = ("down_1", "down_2", "down_3")
THREADS = ("thread_1", "thread_2", "thread_3")
MOVED = ("moved_1", "moved_2")
BLAS_VARIABLES = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
USER_OMP = "3"
PARENT_ENV = {
    "PYTHONPATH": "gbtest-pythonpath",
    "PYTHONHOME": "gbtest-pythonhome",
    "PYTHONSTARTUP": "gbtest-startup",
    "PYTHONUTF8": "1",
    "PIP_USER": "1",
    "PIP_REQUIRE_VIRTUALENV": "1",
    "PIP_NO_INDEX": "1",
    "PIPX_HOME": "gbtest-pipx",
    "GBTEST_KEEP": "1",
    "OMP_NUM_THREADS": USER_OMP,
}
"""El entorno de Blender al lanzar los trabajos ``env``: lo que el worker no debe heredar,
lo que sí (``PIPX_HOME`` no es ``PIP_*``) y la ``OMP_NUM_THREADS`` que fijó el usuario."""
ENV_SCRIPT = "@echo off\r\nset > env.txt\r\nexit 0\r\n"
"""El intérprete falso de ``env``: guarda su entorno en la carpeta del trabajo (su carpeta
de trabajo) y termina sin resultado."""
ENV_FILE = "env.txt"

_HANDLES: dict[str, object] = {}
_RUNNERS: dict[str, object] = {}
_STATE: dict[str, object] = {}
_MAX: dict[str, int] = {"fifo_running": 0, "fifo_alive": 0, "threads_running": 0,
                        "up_running": 0}


def _request(name: str):
    return protocol.new_request("selftest", label=f"Cola {name}", owner="jobs",
                                params=SUM_PARAMS)


def _submit(name: str, job_runner) -> None:
    _HANDLES[name] = job_runner.submit(_request(name))
    _RUNNERS[name] = job_runner


def _states(names) -> list[str]:
    return [_HANDLES[name].state for name in names]


def _saved_states(names) -> list[str]:
    return [records.read_record(_HANDLES[name].job_dir).state for name in names]


def _sample() -> None:
    """Cuántos trabajos hay en curso y cuántos procesos siguen vivos ahora."""
    fifo = [_HANDLES[name] for name in FIFO]
    alive = sum(1 for handle in fifo
                if handle.pid is not None and _support.pid_alive(handle.pid))
    counts = {
        "fifo_running": sum(handle.state == "running" for handle in fifo),
        "fifo_alive": alive,
        "threads_running": sum(state == "running" for state in _states(THREADS)),
        "up_running": sum(state == "running" for state in _states(UP)),
    }
    for key, value in counts.items():
        _MAX[key] = max(_MAX[key], value)


def _poll_all() -> None:
    for job_runner in {id(r): r for r in _RUNNERS.values()}.values():
        job_runner.poll()


def _wait_all() -> None:
    deadline = time.monotonic() + DEADLINE_S
    while True:
        _sample()
        if all(handle.result() is not None for handle in _HANDLES.values()):
            return
        if time.monotonic() > deadline:
            pending = [name for name, handle in _HANDLES.items() if handle.result() is None]
            raise AssertionError(f"no acabaron a tiempo: {pending}")
        _poll_all()
        time.sleep(POLL_S)


def _note_ts(name: str, kind: str) -> float:
    """La hora de la nota ``kind`` (``launched``, ``finished``) del lanzador en
    ``events.jsonl``."""
    folder = _HANDLES[name].job_dir
    for line in folder.events_file.read_text(encoding="utf-8").splitlines():
        data = json.loads(line)
        if data.get(runner.NOTE_KEY) == kind:
            return data["ts"]
    raise AssertionError(f"«{name}» no tiene la nota {kind}")


def _max_overlap(names) -> int:
    """Cuántos de ``names`` estaban a la vez en curso (de su arranque a su final) como
    mucho, según las notas del lanzador."""
    spans = [(_note_ts(name, "launched"), _note_ts(name, "finished")) for name in names]
    return max(sum(1 for start, end in spans if start <= at < end) for at, _ in spans)


def _child_env(name: str) -> dict[str, str]:
    """El entorno que recibió el intérprete falso del trabajo ``name``."""
    text = (_HANDLES[name].job_dir.path / ENV_FILE).read_bytes().decode("utf-8", "replace")
    variables: dict[str, str] = {}
    for line in text.splitlines():
        variable, sep, value = line.partition("=")
        if sep and variable:
            variables[variable] = value
    return variables


def _cpu() -> int:
    return os.process_cpu_count() or 1


def _shutdown_all() -> None:
    for job_runner in {id(r): r for r in _RUNNERS.values()}.values():
        job_runner.shutdown()


def setUpModule() -> None:
    tmp = _support.jobs_tmp()
    base = tmp.__enter__()
    unittest.addModuleCleanup(tmp.__exit__, None, None, None)
    root = base / "jobs"
    other_root = base / "otra" / "jobs"
    _STATE["root"] = root
    _STATE["other_root"] = other_root

    registry = mock.patch.dict(catalog._REGISTRY, clear=True)
    registry.start()
    unittest.addModuleCleanup(registry.stop)
    unittest.addModuleCleanup(_shutdown_all)  # va antes: las limpiezas van al revés
    builtin = next(info for info in catalog.BUILTIN_WORKERS if info.name == "selftest")
    catalog.register_worker(dataclasses.replace(builtin, default_timeout_s=JOB_TIMEOUT_S))
    as_process = {"selftest": dataclasses.replace(builtin, policy="subprocess",
                                                  default_timeout_s=JOB_TIMEOUT_S)}

    fake_dir = base / "fake_env"
    fake_dir.mkdir()
    fake_env = fake_dir / "dump_env.cmd"
    fake_env.write_bytes(ENV_SCRIPT.encode("ascii"))

    def new_runner(**options):
        options.setdefault("jobs_root", root)
        options.setdefault("blender_python", Path(sys.executable))
        return runner.JobRunner(package_dir=EXTENSION_DIR, **options)

    # env: el intérprete falso, con el entorno de Blender «contaminado».
    env_runner = new_runner(blender_python=fake_env)
    with mock.patch.dict(os.environ, PARENT_ENV), mock.patch.dict(catalog._REGISTRY,
                                                                   as_process):
        for variable in BLAS_VARIABLES:
            if variable not in PARENT_ENV:
                os.environ.pop(variable, None)
        _submit("env_2", env_runner)
        env_runner.reconfigure(max_subprocess=4)
        _submit("env_4", env_runner)
        _STATE["parent_env_after"] = {name: os.environ.get(name) for name in PARENT_ENV}

    # fifo: 5 en proceso aparte con el máximo por defecto.
    fifo_runner = new_runner()
    with mock.patch.dict(catalog._REGISTRY, as_process):
        for name in FIFO:
            _submit(name, fifo_runner)
    _STATE["fifo_after_submit"] = _states(FIFO)
    _STATE["fifo_saved_after_submit"] = _saved_states(FIFO)
    _STATE["fifo_events_after_submit"] = [_HANDLES[name].job_dir.events_file.exists()
                                          for name in FIFO]

    # up: máximo 1 y luego 3, sin sondear entre medias.
    up_runner = new_runner(max_subprocess=1)
    with mock.patch.dict(catalog._REGISTRY, as_process):
        for name in UP:
            _submit(name, up_runner)
    _STATE["up_after_submit"] = _states(UP)
    up_runner.reconfigure(max_subprocess=3)
    _STATE["up_after_reconfigure"] = _states(UP)
    _STATE["up_max"] = up_runner.max_subprocess

    # down: máximo 2 y luego 1, con dos en curso.
    down_runner = new_runner()
    with mock.patch.dict(catalog._REGISTRY, as_process):
        for name in DOWN:
            _submit(name, down_runner)
    _STATE["down_after_submit"] = _states(DOWN)
    down_runner.reconfigure(max_subprocess=1)
    _STATE["down_after_reconfigure"] = _states(DOWN)

    # threads: dos huecos de hilo; el de proceso aparte, detrás, no espera a los hilos.
    threads_runner = new_runner(max_inprocess=2)
    for name in THREADS:
        _submit(name, threads_runner)
    with mock.patch.dict(catalog._REGISTRY, as_process):
        _submit("process_after_threads", threads_runner)
    _STATE["threads_after_submit"] = _states((*THREADS, "process_after_threads"))
    _STATE["threads_max"] = threads_runner.max_inprocess

    # moved: otra raíz para lo que se prepare después.
    moved_runner = new_runner()
    _submit("moved_1", moved_runner)
    moved_runner.reconfigure(jobs_root=other_root)
    _submit("moved_2", moved_runner)
    _STATE["moved_after_submit"] = _states(MOVED)
    _STATE["moved_root"] = moved_runner.jobs_root

    _wait_all()


class QueueOrderTest(unittest.TestCase):
    """Cinco trabajos en proceso aparte con el máximo por defecto (2)."""

    def test_waiting_jobs_are_queued(self):
        """RF-004-04: con dos en curso, los otros tres quedan «En cola» (también en su
        ``state.json``) y sin arrancar."""
        self.assertEqual(_STATE["fifo_after_submit"],
                         ["running", "running", "queued", "queued", "queued"])
        self.assertEqual(_STATE["fifo_saved_after_submit"],
                         ["running", "running", "queued", "queued", "queued"])
        self.assertEqual(_STATE["fifo_events_after_submit"],
                         [True, True, False, False, False])

    def test_never_more_than_two_processes(self):
        """RF-004-04: nunca hay más de 2 workers en proceso aparte a la vez (en curso para
        el lanzador y procesos vivos), y llega a haber 2."""
        self.assertEqual(_MAX["fifo_running"], 2)
        self.assertLessEqual(_MAX["fifo_alive"], 2)
        self.assertGreaterEqual(_MAX["fifo_alive"], 1)
        self.assertEqual(_max_overlap(FIFO), 2)

    def test_start_in_arrival_order(self):
        """RF-004-04: arrancan por orden de llegada, cada uno cuando acaba otro."""
        launched = {name: _note_ts(name, "launched") for name in FIFO}
        self.assertEqual(sorted(FIFO, key=launched.get), list(FIFO))
        finished = sorted(_note_ts(name, "finished") for name in FIFO[:2])
        self.assertGreaterEqual(launched["fifo_3"], finished[0])
        self.assertGreaterEqual(launched["fifo_4"], finished[1])

    def test_all_finish(self):
        """RF-004-04: los cinco acaban «Terminado» en proceso aparte."""
        for name in FIFO:
            with self.subTest(name=name):
                result = _HANDLES[name].result()
                self.assertEqual(result.state, "succeeded")
                self.assertEqual(records.read_record(result.job_dir).executor, "subprocess")


class ChildEnvironmentTest(unittest.TestCase):
    """El entorno que recibe el worker en proceso aparte (plan §5.3.3)."""

    def test_child_gets_blas_threads(self):
        """RF-004-04: el worker recibe ``OPENBLAS_NUM_THREADS`` y ``MKL_NUM_THREADS`` =
        ``max(1, cpu // máximo)``, con el máximo vigente al lanzarlo (2, y 4 tras
        ``reconfigure``)."""
        for name, maximum in (("env_2", 2), ("env_4", 4)):
            with self.subTest(name=name):
                env = _child_env(name)
                expected = str(max(1, _cpu() // maximum))
                self.assertEqual(env.get("OPENBLAS_NUM_THREADS"), expected)
                self.assertEqual(env.get("MKL_NUM_THREADS"), expected)

    def test_child_keeps_user_threads(self):
        """RF-004-04: la variable de hilos que fijó el usuario llega tal cual."""
        for name in ("env_2", "env_4"):
            with self.subTest(name=name):
                self.assertEqual(_child_env(name).get("OMP_NUM_THREADS"), USER_OMP)

    def test_child_has_no_python_or_pip_variables(self):
        """RF-004-04: el worker no recibe variables ``PYTHON*`` ni ``PIP_*``; el resto del
        entorno de Blender, sí."""
        for name in ("env_2", "env_4"):
            with self.subTest(name=name):
                env = _child_env(name)
                leaked = [variable for variable in env
                          if variable.upper().startswith(("PYTHON", "PIP_"))]
                self.assertEqual(leaked, [])
                self.assertEqual(env.get("GBTEST_KEEP"), "1")
                self.assertEqual(env.get("PIPX_HOME"), "gbtest-pipx")
                self.assertIn("PATH", {variable.upper() for variable in env})

    def test_blender_environment_untouched(self):
        """RF-004-04: lanzar no cambia el entorno del proceso de Blender."""
        self.assertEqual(_STATE["parent_env_after"], PARENT_ENV)


class InProcessLimitTest(unittest.TestCase):
    """Los huecos de hilo (``max_inprocess``)."""

    def test_two_threads_at_most(self):
        """RF-004-04: con ``max_inprocess = 2``, dos trabajos en hilo a la vez y el tercero
        «En cola» hasta que acaba uno, por orden de llegada."""
        self.assertEqual(_STATE["threads_max"], 2)
        self.assertEqual(_STATE["threads_after_submit"][:3], ["running", "running", "queued"])
        self.assertEqual(_MAX["threads_running"], 2)
        self.assertEqual(_max_overlap(THREADS), 2)
        first_end = min(_note_ts(name, "finished") for name in THREADS[:2])
        self.assertGreaterEqual(_note_ts("thread_3", "launched"), first_end)
        for name in THREADS:
            with self.subTest(name=name):
                result = _HANDLES[name].result()
                self.assertEqual(result.state, "succeeded")
                self.assertEqual(records.read_record(result.job_dir).executor, "inprocess")

    def test_waiting_thread_does_not_hold_processes(self):
        """RF-004-04: un trabajo en hilo que espera su hueco no retiene a uno en proceso
        aparte que llega después."""
        self.assertEqual(_STATE["threads_after_submit"][2:], ["queued", "running"])
        self.assertEqual(_HANDLES["process_after_threads"].result().state, "succeeded")
        self.assertLess(_note_ts("process_after_threads", "launched"),
                        _note_ts("thread_3", "launched"))

    def test_one_thread_by_default(self):
        """RF-004-04: con el máximo de hilos por defecto (1), el segundo trabajo en hilo
        espera «En cola» a que acabe el primero."""
        self.assertEqual(_STATE["moved_after_submit"], ["running", "queued"])
        self.assertEqual(_max_overlap(MOVED), 1)
        self.assertGreaterEqual(_note_ts("moved_2", "launched"),
                                _note_ts("moved_1", "finished"))


class ReconfigureTest(unittest.TestCase):
    """``reconfigure`` con trabajos en curso y en la cola."""

    def test_raising_the_maximum_starts_queued_jobs(self):
        """RF-004-04: al subir el máximo de 1 a 3, los dos de la cola arrancan al momento,
        sin esperar al sondeo."""
        self.assertEqual(_STATE["up_after_submit"], ["running", "queued", "queued"])
        self.assertEqual(_STATE["up_after_reconfigure"], ["running", "running", "running"])
        self.assertEqual(_STATE["up_max"], 3)
        self.assertEqual(_MAX["up_running"], 3)
        for name in UP:
            with self.subTest(name=name):
                self.assertEqual(_HANDLES[name].result().state, "succeeded")

    def test_lowering_the_maximum_keeps_running_jobs(self):
        """RF-004-04: al bajar el máximo de 2 a 1, los dos en curso siguen hasta acabar
        bien y el de la cola espera a que no quede ninguno."""
        self.assertEqual(_STATE["down_after_submit"], ["running", "running", "queued"])
        self.assertEqual(_STATE["down_after_reconfigure"], ["running", "running", "queued"])
        for name in DOWN:
            with self.subTest(name=name):
                result = _HANDLES[name].result()
                self.assertEqual(result.state, "succeeded")
                self.assertIsNone(records.read_record(result.job_dir).cancel)
        last_end = max(_note_ts(name, "finished") for name in DOWN[:2])
        self.assertGreaterEqual(_note_ts("down_3", "launched"), last_end)

    def test_new_jobs_root_for_later_jobs(self):
        """RF-004-04: con otra raíz, lo que se prepara después va a ella y lo que ya estaba
        preparado sigue en la suya y acaba bien."""
        self.assertEqual(_STATE["moved_root"], _STATE["other_root"])
        self.assertEqual(_HANDLES["moved_1"].job_dir.path.parent, _STATE["root"])
        self.assertEqual(_HANDLES["moved_2"].job_dir.path.parent, _STATE["other_root"])
        for name in MOVED:
            with self.subTest(name=name):
                self.assertEqual(_HANDLES[name].result().state, "succeeded")


class LimitsValidationTest(unittest.TestCase):
    """Los máximos que no valen, sin lanzar nada."""

    def _runner(self, **options):
        return runner.JobRunner(jobs_root=_STATE["root"], package_dir=EXTENSION_DIR,
                                blender_python=Path(sys.executable), **options)

    def test_defaults(self):
        """RF-004-04: por defecto, 2 en proceso aparte y 1 en hilo (D-2)."""
        job_runner = self._runner()
        self.assertEqual(job_runner.max_subprocess, 2)
        self.assertEqual(job_runner.max_inprocess, 1)
        self.assertEqual(runner.DEFAULT_MAX_SUBPROCESS, 2)
        self.assertEqual(runner.DEFAULT_MAX_INPROCESS, 1)

    def test_invalid_maximums_rejected(self):
        """RF-004-04: un máximo que no es un entero ≥ 1 no se admite."""
        for option in ("max_subprocess", "max_inprocess"):
            for value in (0, -1, True, 1.5, "2", None):
                with self.subTest(option=option, value=value), self.assertRaises(ValueError):
                    self._runner(**{option: value})

    def test_invalid_reconfigure_changes_nothing(self):
        """RF-004-04: ``reconfigure`` con un valor que no vale no cambia nada, tampoco lo
        que sí valía en la misma llamada."""
        job_runner = self._runner(max_subprocess=3)
        new_root = _STATE["root"].parent / "nueva"
        for options in ({"max_subprocess": 0}, {"max_subprocess": True},
                        {"max_subprocess": 2.0}, {"jobs_root": Path("relativa")},
                        {"max_subprocess": 0, "jobs_root": new_root},
                        {"max_subprocess": 2, "jobs_root": Path("relativa")}):
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    job_runner.reconfigure(**options)
                self.assertEqual(job_runner.max_subprocess, 3)
                self.assertEqual(job_runner.jobs_root, _STATE["root"])
        job_runner.reconfigure()
        self.assertEqual((job_runner.max_subprocess, job_runner.jobs_root),
                         (3, _STATE["root"]))


class ChildEnvTest(unittest.TestCase):
    """``interpreter.child_env``: el entorno del hijo a partir del de Blender."""

    def test_drops_python_and_pip_variables(self):
        """RF-004-04: quita toda variable ``PYTHON*`` y ``PIP_*`` (sin distinguir
        mayúsculas, como Windows) y conserva el resto tal cual."""
        base = {
            "PATH": "a;b", "SystemRoot": "w", "PYTHONPATH": "x", "PythonHome": "x",
            "pythonstartup": "x", "PYTHON": "x", "PIP_USER": "1", "pip_target": "x",
            "Pip_Require_Virtualenv": "1", "PIPX_HOME": "p", "MYPYTHON": "m",
            "PY_COLORS": "0", "GEOBLENDER_X": "ñ",
        }
        env = interpreter.child_env(base, blas_threads=6)
        kept = {name: value for name, value in env.items() if name not in BLAS_VARIABLES}
        self.assertEqual(kept, {"PATH": "a;b", "SystemRoot": "w", "PIPX_HOME": "p",
                                "MYPYTHON": "m", "PY_COLORS": "0", "GEOBLENDER_X": "ñ"})

    def test_sets_blas_threads_when_missing(self):
        """RF-004-04: sin ellas, fija las tres variables de hilos de BLAS."""
        env = interpreter.child_env({"PATH": "a"}, blas_threads=12)
        self.assertEqual({name: env[name] for name in BLAS_VARIABLES},
                         dict.fromkeys(BLAS_VARIABLES, "12"))

    def test_keeps_user_blas_settings(self):
        """RF-004-04: las que fijó el usuario mandan (con sus mayúsculas, sin duplicarlas)
        y solo se añaden las que faltan."""
        env = interpreter.child_env({"omp_num_threads": "3", "OPENBLAS_NUM_THREADS": "1"},
                                    blas_threads=12)
        self.assertEqual(env, {"omp_num_threads": "3", "OPENBLAS_NUM_THREADS": "1",
                               "MKL_NUM_THREADS": "12"})

    def test_empty_user_value_counts_as_unset(self):
        """RF-004-04: una variable de hilos vacía no fija nada: se sustituye."""
        env = interpreter.child_env({"MKL_NUM_THREADS": "", "omp_num_threads": " "},
                                    blas_threads=4)
        self.assertEqual(env, dict.fromkeys(BLAS_VARIABLES, "4"))

    def test_does_not_modify_base(self):
        """RF-004-04: devuelve un diccionario nuevo y no toca el entorno de partida."""
        base = {"PATH": "a", "PIP_USER": "1"}
        frozen = types.MappingProxyType(dict(base))
        env = interpreter.child_env(frozen, blas_threads=2)
        self.assertEqual(dict(frozen), base)
        self.assertIsInstance(env, dict)
        self.assertIsNot(env, base)
        real = interpreter.child_env(os.environ, blas_threads=1)
        self.assertTrue(all(isinstance(k, str) and isinstance(v, str)
                            for k, v in real.items()))

    def test_invalid_arguments(self):
        """RF-004-04: hilos que no son un entero ≥ 1, ``ValueError``; un nombre o un valor
        que no es texto, ``TypeError``."""
        for value in (0, -2, True, 2.0, "4", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                interpreter.child_env({}, blas_threads=value)
        for base in ({"PATH": 1}, {1: "a"}):
            with self.subTest(base=base), self.assertRaises(TypeError):
                interpreter.child_env(base, blas_threads=1)


class BlasThreadsTest(unittest.TestCase):
    """``interpreter.blas_threads_for``: ``max(1, cpu // máximo)`` (plan §5.3.3, D-2)."""

    def test_split_between_workers(self):
        """RF-004-04: los procesadores se reparten entre los workers a la vez, al menos
        1 hilo cada uno."""
        cases = {(2, 24): 12, (4, 24): 6, (1, 24): 24, (3, 24): 8, (2, 1): 1, (2, 3): 1,
                 (4, 5): 1}
        for (maximum, cpu), expected in cases.items():
            with self.subTest(maximum=maximum, cpu=cpu):
                self.assertEqual(interpreter.blas_threads_for(maximum, cpu_count=cpu),
                                 expected)

    def test_uses_this_machine(self):
        """RF-004-04: sin ``cpu_count``, los procesadores que puede usar este proceso; si
        no se saben, 1."""
        self.assertEqual(interpreter.blas_threads_for(2), max(1, _cpu() // 2))
        with mock.patch.object(interpreter.os, "process_cpu_count", return_value=None):
            self.assertEqual(interpreter.blas_threads_for(1), 1)

    def test_invalid_arguments(self):
        """RF-004-04: un máximo o unos procesadores que no son un entero ≥ 1,
        ``ValueError``."""
        for value in (0, -1, True, 1.5, None):
            with self.subTest(max_parallel=value), self.assertRaises(ValueError):
                interpreter.blas_threads_for(value, cpu_count=8)
            with self.subTest(cpu_count=value), self.assertRaises(ValueError):
                interpreter.blas_threads_for(2, cpu_count=value if value is not None else 0)


if __name__ == "__main__":
    unittest.main()
