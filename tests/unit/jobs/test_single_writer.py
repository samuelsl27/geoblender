# SPDX-License-Identifier: GPL-3.0-or-later
"""Escritor único: los trabajos no tocan el proyecto (spec 004, T16; RF-004-14; plan 004
§5.2, §7 y principio 7 de la constitución).

Un proyecto falso (``project.gpkg`` y ``blocks.duckdb`` de bytes aleatorios) con la raíz de
trabajos en su caché (``<proyecto>/cache/jobs``, la de un proyecto en disco local; RF-004-18)
y diez trabajos del autodiagnóstico, en proceso aparte y en hilo, que acaban bien, mal o
cancelados (también uno en cola y uno forzado al vencer su plazo de gracia). Los lanzadores
tienen la raíz del proyecto como ruta prohibida (``forbidden_roots``). Mientras trabajan,
nada más escribe en el proyecto. Al acabar, las huellas sha256 de los dos ficheros son las
mismas, ninguna petición contiene la ruta del proyecto y lo único nuevo está dentro de la
carpeta de cada trabajo. Una petición con la ruta del proyecto no llega a prepararse.

Los diez se lanzan a la vez al empezar (``setUpModule``) y cada prueba mira lo que dejaron.
"""

import dataclasses
import json
import os
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
inprocess = import_geoblender("jobs.inprocess")
messages = import_geoblender("jobs.messages")
paths = import_geoblender("jobs.paths")
protocol = import_geoblender("jobs.protocol")
runner = import_geoblender("jobs.runner")

QUICK = {"n": 1000, "chunks": 2}
FAIL = {"n": 1000, "chunks": 4, "fail_at": 2}
LONG = {"n": 1000, "chunks": 40, "sleep_s": 0.5}
"""20 s si nadie la para: proceso aparte (más de 5 s estimados)."""
THREAD_CANCEL = {"n": 1000, "chunks": 20, "sleep_s": 0.2}
"""4 s estimados: en hilo, con la política «auto»."""
GRACE_S = 1.0
"""El plazo de gracia mínimo válido: el trabajo forzado dura ~1 s tras cancelarlo."""
JOB_TIMEOUT_S = 120.0
DEADLINE_S = 30.0
POLL_S = 0.02

# Nombre → (ejecutor, parámetros, opciones de la petición, estado final esperado).
JOBS: dict[str, tuple[str, dict, dict, str]] = {
    "proc_sum": ("subprocess", QUICK, {}, "succeeded"),
    "proc_noise": ("subprocess", {**QUICK, "stdout_noise": True}, {}, "succeeded"),
    "proc_fail": ("subprocess", FAIL, {}, "failed"),
    "proc_crash": ("subprocess", {"n": 1000, "chunks": 4, "crash_at": 2}, {}, "failed"),
    "proc_cancel": ("subprocess", LONG, {}, "cancelled"),
    "proc_forced": ("subprocess", {**LONG, "ignore_cancel": True}, {"grace_s": GRACE_S},
                    "cancelled"),
    "proc_queued": ("subprocess", LONG, {}, "cancelled"),
    "thread_sum": ("inprocess", QUICK, {}, "succeeded"),
    "thread_fail": ("inprocess", FAIL, {}, "failed"),
    "thread_cancel": ("inprocess", THREAD_CANCEL, {}, "cancelled"),
}
CANCEL_ON_START = ("proc_cancel", "proc_forced", "thread_cancel")

_HANDLES: dict[str, object] = {}
_RUNNERS: list[object] = []
_EVENTS: dict[str, list[str]] = {}
_STATE: dict[str, object] = {}


def _request(name: str):
    _executor, params, options, _final = JOBS[name]
    return protocol.new_request("selftest", label=f"Escritor único: {name}", owner="jobs",
                                params=params, **options)


def _poll() -> None:
    for job_runner in _RUNNERS:
        for update in job_runner.poll():
            _EVENTS.setdefault(update.job_uid, []).extend(e.type for e in update.events)


def _started(name: str) -> bool:
    return "start" in _EVENTS.get(_HANDLES[name].job_uid, ())


def _wait_until(condition, what: str) -> None:
    deadline = time.monotonic() + DEADLINE_S
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"no llegó a tiempo: {what}")
        _poll()
        time.sleep(POLL_S)


def _job_threads_alive() -> bool:
    return any(t.name.startswith(inprocess.THREAD_NAME_PREFIX) and t.is_alive()
               for t in threading.enumerate())


def _close_runners() -> None:
    for job_runner in _RUNNERS:
        job_runner.shutdown(timeout_s=3.0)
    deadline = time.monotonic() + DEADLINE_S
    while _job_threads_alive() and time.monotonic() < deadline:
        time.sleep(POLL_S)


def _snapshot(base: Path) -> dict[str, str]:
    """Ruta relativa (con «/») → huella sha256 de cada fichero bajo ``base``."""
    found: dict[str, str] = {}
    for folder, _dirs, files in os.walk(base):
        for name in files:
            path = Path(folder) / name
            found[path.relative_to(base).as_posix()] = _support.sha256_file(path)
    return found


def _strings(value: object) -> list[str]:
    """Todos los textos de un valor JSON (claves y valores, en profundidad)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for key, item in value.items() for s in (*_strings(key), *_strings(item))]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


def setUpModule() -> None:
    tmp = _support.jobs_tmp()
    base = tmp.__enter__()
    unittest.addModuleCleanup(tmp.__exit__, None, None, None)
    # Las limpiezas van al revés: los lanzadores se cierran antes de borrar la carpeta.
    unittest.addModuleCleanup(_close_runners)
    project = _support.make_fake_project(base)
    jobs_root = paths.resolve_jobs_root(project_cache_dir=project.root / "cache",
                                        user_dir=base / "usuario")
    _STATE.update(base=base, project=project, jobs_root=jobs_root,
                  fingerprints=project.fingerprints(), snapshot=_snapshot(base))

    registry = mock.patch.dict(catalog._REGISTRY, clear=True)
    registry.start()
    unittest.addModuleCleanup(registry.stop)
    builtin = next(info for info in catalog.BUILTIN_WORKERS if info.name == "selftest")
    in_thread = dataclasses.replace(builtin, default_timeout_s=JOB_TIMEOUT_S)
    as_process = dataclasses.replace(in_thread, policy="subprocess")
    catalog.register_worker(in_thread)

    options = {"jobs_root": jobs_root, "package_dir": EXTENSION_DIR,
               "blender_python": Path(sys.executable), "forbidden_roots": [project.root]}
    processes = runner.JobRunner(**options, max_subprocess=6)
    threads = runner.JobRunner(**options, max_inprocess=3)
    _RUNNERS.extend([processes, threads])

    # Un lanzador de seis huecos con siete trabajos: «proc_queued» espera en la cola (nadie
    # ha sondeado aún, así que ningún hueco se ha liberado) y se cancela allí.
    with mock.patch.dict(catalog._REGISTRY, {"selftest": as_process}):
        for name, (executor, *_rest) in JOBS.items():
            if executor == "subprocess":
                _HANDLES[name] = processes.submit(_request(name))
    _STATE["queued_state"] = _HANDLES["proc_queued"].state
    _STATE["queued_cancel"] = _HANDLES["proc_queued"].cancel()
    for name, (executor, *_rest) in JOBS.items():
        if executor == "inprocess":
            _HANDLES[name] = threads.submit(_request(name))

    # Las cancelaciones en curso, en cuanto cada uno arranca; luego, hasta que acaban todos.
    pending = list(CANCEL_ON_START)

    def cancel_started() -> bool:
        for name in list(pending):
            if _started(name):
                _HANDLES[name].cancel()
                pending.remove(name)
        return not pending

    _wait_until(cancel_started, "arranque de los trabajos que se cancelan")
    _wait_until(lambda: all(h.result() is not None for h in _HANDLES.values()),
                "final de los diez trabajos")
    _wait_until(lambda: not _job_threads_alive(), "fin de los hilos de los trabajos")


class SingleWriterTest(unittest.TestCase):
    def test_ten_jobs_of_every_kind(self) -> None:
        """RF-004-14: los diez trabajos, en los dos ejecutores, acaban como se esperaba:
        tres «Terminado», tres «Fallido» y cuatro «Cancelado» (uno en cola y uno forzado)."""
        self.assertEqual(len(_HANDLES), 10)
        self.assertEqual(_STATE["queued_state"], "queued")
        self.assertTrue(_STATE["queued_cancel"])
        finals = {name: handle.result().state for name, handle in _HANDLES.items()}
        self.assertEqual(finals, {name: spec[3] for name, spec in JOBS.items()})
        executors = {name: json.loads(
            (handle.job_dir.path / "state.json").read_text(encoding="utf-8"))["executor"]
            for name, handle in _HANDLES.items()}
        self.assertEqual(executors, {name: spec[0] for name, spec in JOBS.items()})

    def test_project_fingerprints_unchanged(self) -> None:
        """RF-004-14: con la raíz de trabajos dentro del proyecto y sin escrituras de
        Blender durante los trabajos, las huellas sha256 de ``project.gpkg`` y
        ``blocks.duckdb`` no cambian."""
        project = _STATE["project"]
        self.assertEqual(sorted(_STATE["fingerprints"]), ["blocks.duckdb", "project.gpkg"])
        self.assertEqual(project.fingerprints(), _STATE["fingerprints"])

    def test_requests_without_project_path(self) -> None:
        """RF-004-14: ninguna petición contiene la ruta del proyecto (ni con «/», ni
        escapada en JSON, ni en otras mayúsculas), y ninguno de sus textos la nombra."""
        root = str(_STATE["project"].root)
        forms = {root, root.replace("\\", "/"), json.dumps(root)[1:-1]}
        flat_root = root.replace("\\", "/").casefold()
        for name, handle in _HANDLES.items():
            with self.subTest(trabajo=name):
                raw = (handle.job_dir.path / protocol.REQUEST_FILE).read_text(encoding="utf-8")
                for form in forms:
                    self.assertNotIn(form.casefold(), raw.casefold())
                texts = _strings(json.loads(raw))
                self.assertTrue(texts)
                for text in texts:
                    self.assertNotIn(flat_root, text.replace("\\", "/").casefold())

    def test_writes_only_in_job_folders(self) -> None:
        """RF-004-14: lo que había no cambia y lo único nuevo está dentro de la carpeta de
        uno de los diez trabajos (``<proyecto>/cache/jobs/<job_uid>/``)."""
        base, before = _STATE["base"], _STATE["snapshot"]
        after = _snapshot(base)
        for rel, digest in before.items():
            self.assertEqual(after.get(rel), digest, rel)
        jobs = _STATE["jobs_root"].relative_to(base).as_posix()
        folders = {f"{jobs}/{handle.job_uid}/" for handle in _HANDLES.values()}
        outside = [rel for rel in after
                   if rel not in before and not rel.startswith(tuple(folders))]
        self.assertEqual(outside, [])
        written = {rel.split("/")[3] for rel in after if rel not in before}
        self.assertEqual(written, {handle.job_uid for handle in _HANDLES.values()})

    def test_project_path_rejected(self) -> None:
        """RF-004-14: una petición con la ruta del proyecto en sus parámetros no se
        prepara (``request_path_outside_job``): no se crea su carpeta y el proyecto no
        cambia."""
        project = _STATE["project"]
        jobs_root = _STATE["jobs_root"]
        before = sorted(p.name for p in jobs_root.iterdir())
        request = protocol.new_request("selftest", label="Con la ruta del proyecto",
                                       owner="jobs", params={"source": str(project.gpkg)})
        with self.assertRaises(messages.JobError) as caught:
            _RUNNERS[0].prepare(request)
        self.assertEqual(caught.exception.code, "request_path_outside_job")
        self.assertEqual(sorted(p.name for p in jobs_root.iterdir()), before)
        self.assertNotIn(request.job_uid, before)
        self.assertEqual(project.fingerprints(), _STATE["fingerprints"])


if __name__ == "__main__":
    unittest.main()
