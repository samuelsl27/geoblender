# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendimiento de los trabajos en segundo plano (spec 004; RNF-004-01 a RNF-004-08; plan
004 §7, ``tests/rendimiento``).

Se ejecuta con ``tools/check.py --rendimiento``: el Python de Blender, en disco local
(``%TEMP%``), con procesos reales. Cada prueba imprime su cifra en una línea
``RNF-004-nn: …`` (``tools/check.py`` las recoge) y la compara con su presupuesto. Por
ahora está el HITO H1; la T35 añade los demás RNF.

- RNF-004-07 (HITO H1, CE-004-03; RF-004-13 y RF-004-14): 100 trabajos seguidos del
  autodiagnóstico en proceso aparte, con el Python de Blender y por la cola del lanzador
  (4 a la vez, el máximo de la preferencia): 40 que acaban bien, 20 con fallo (10 que
  informan su error y 10 que se caen), 20 cancelados en cuanto arrancan, 10 con tiempo
  agotado (1 s) y 10 que ignoran la cancelación (terminados al vencer su plazo de gracia
  de 1 s). La raíz de trabajos está en la caché de un proyecto falso
  (``<proyecto>/cache/jobs``, la de un proyecto en disco local) con la raíz del proyecto
  prohibida. Al final no queda vivo ningún worker (``pid_alive``) ni ningún proceso nuevo
  que descienda de ellos (los nietos, si los hubiera), las huellas sha256 de
  ``project.gpkg`` y ``blocks.duckdb`` no cambian, ninguna petición lleva la ruta del
  proyecto, lo nuevo está solo en las carpetas de los 100, cada ``state.json`` es el de su
  caso y la memoria del proceso que los lanza crece ≤ 20 MB (conjunto de trabajo y memoria
  privada, con ``GetProcessMemoryInfo``).
"""

import ctypes
import dataclasses
import gc
import json
import os
import sys
import time
import unittest
from collections.abc import Iterable, Mapping
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import numpy as np

from tests.support import jobs_fixtures as _support
from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR

catalog = import_geoblender("jobs.catalog")
paths = import_geoblender("jobs.paths")
protocol = import_geoblender("jobs.protocol")
records = import_geoblender("jobs.records")
runner = import_geoblender("jobs.runner")
selftest = import_geoblender("jobs.selftest")

MiB = 1024 * 1024
MEMORY_BUDGET = 20 * MiB  # RNF-004-07: ≤ 20 MB de crecimiento del proceso que los lanza
PARALLEL = 4
"""Workers a la vez: el máximo de la preferencia (1–4, RF-004-04)."""
GRACE_S = 1.0
"""El plazo de gracia mínimo válido: lo que dura un trabajo que ignora la cancelación."""
TIMEOUT_S = 1.0
"""El tiempo máximo de los trabajos de tiempo agotado."""
JOB_TIMEOUT_S = 120.0
"""El de los demás: ninguno lo alcanza."""
DEADLINE_S = 120.0
"""Plazo de seguridad de los 100 (tardan unos 15 s): un lanzador colgado no cuelga la
prueba."""
EXIT_WAIT_S = 5.0
"""RF-004-13: los procesos terminan en ≤ 5 s."""
POLL_S = 0.02

QUICK = {"n": 1000, "chunks": 2}
LONG = {"n": 1000, "chunks": 40, "sleep_s": 0.5}
"""20 s si nadie la para."""
PARAMS: Mapping[str, Mapping[str, object]] = {
    "ok": QUICK,
    "fail": {"n": 1000, "chunks": 4, "fail_at": 2},
    "crash": {"n": 1000, "chunks": 4, "crash_at": 2},
    "cancel": LONG,
    "timeout": LONG,
    "ignore": {**LONG, "ignore_cancel": True},
}
CANCEL_ON_START = ("cancel", "ignore")
BLOCK: tuple[str, ...] = (
    "ok", "cancel", "fail", "ok", "timeout", "ok", "ignore", "crash", "cancel", "ok",
)
"""Diez trabajos mezclados; los lentos (tiempo agotado y forzados) repartidos."""
ORDER: tuple[str, ...] = BLOCK * 10
COUNTS = {"ok": 40, "fail": 10, "crash": 10, "cancel": 20, "timeout": 10, "ignore": 10}


@dataclass(frozen=True)
class Expected:
    """El ``state.json`` de un caso: estado, código de salida, código del error y
    cancelación (motivo y si fue forzada)."""

    state: str
    exit_code: int
    error: str | None
    cancel_reason: str | None
    forced: bool = False


EXPECTED: Mapping[str, Expected] = {
    "ok": Expected("succeeded", runner.EXIT_OK, None, None),
    "fail": Expected("failed", runner.EXIT_FAILED, "selftest_failed", None),
    "crash": Expected("failed", selftest.CRASH_EXIT_CODE, "worker_crashed", None),
    "cancel": Expected("cancelled", runner.EXIT_CANCELLED, "job_cancelled", "user"),
    "timeout": Expected("timed_out", runner.EXIT_CANCELLED, "job_timeout", "timeout"),
    "ignore": Expected("cancelled", runner.EXIT_TERMINATED, "job_cancelled", "user",
                       forced=True),
}


# --- Memoria y procesos de Windows (ctypes) ----------------------------------------------


class _MemoryCounters(ctypes.Structure):
    """``PROCESS_MEMORY_COUNTERS_EX`` de ``GetProcessMemoryInfo``."""

    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


class _ProcessEntry(ctypes.Structure):
    """``PROCESSENTRY32W`` de ``Process32FirstW``/``Process32NextW``."""

    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


_TH32CS_SNAPPROCESS = 0x00000002
_ERROR_NO_MORE_FILES = 18


def _kernel32() -> ctypes.WinDLL:
    """``kernel32`` propio (no el compartido de ``ctypes.windll``), con sus firmas."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.K32GetProcessMemoryInfo.argtypes = (
        wintypes.HANDLE, ctypes.POINTER(_MemoryCounters), wintypes.DWORD)
    kernel32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ("Process32FirstW", "Process32NextW"):
        function = getattr(kernel32, name)
        function.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ProcessEntry))
        function.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    return kernel32


@dataclass(frozen=True)
class Memory:
    """Memoria de este proceso, en bytes: conjunto de trabajo y memoria privada."""

    working_set: int
    private: int


def _memory() -> Memory:
    """La memoria de este proceso (``GetProcessMemoryInfo``), tras recoger la basura."""
    gc.collect()
    kernel32 = _kernel32()
    counters = _MemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if not kernel32.K32GetProcessMemoryInfo(kernel32.GetCurrentProcess(),
                                            ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return Memory(int(counters.WorkingSetSize), int(counters.PrivateUsage))


def _processes() -> dict[int, tuple[int, str]]:
    """Los procesos de este equipo ahora: pid → (pid del padre, ejecutable)."""
    kernel32 = _kernel32()
    snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snapshot is None or snapshot == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    found: dict[int, tuple[int, str]] = {}
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            found[int(entry.th32ProcessID)] = (int(entry.th32ParentProcessID),
                                               entry.szExeFile)
            more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        error = ctypes.get_last_error()
        if error not in (0, _ERROR_NO_MORE_FILES):
            raise ctypes.WinError(error)
    finally:
        kernel32.CloseHandle(snapshot)
    return found


def _descendants(
    before: Mapping[int, tuple[int, str]],
    after: Mapping[int, tuple[int, str]],
    roots: Iterable[int],
) -> dict[int, str]:
    """Los procesos de ``after`` que no estaban en ``before`` (mismo pid y mismo padre) y
    descienden de algún pid de ``roots``: pid → ejecutable."""
    new = {pid: entry for pid, entry in after.items()
           if before.get(pid, (None,))[0] != entry[0]}
    ancestors = set(roots)
    found: dict[int, str] = {}
    grew = True
    while grew:
        grew = False
        for pid, (parent, exe) in new.items():
            if pid not in found and parent in ancestors:
                found[pid] = exe
                ancestors.add(pid)
                grew = True
    return found


# --- Ayudas ------------------------------------------------------------------------------


def _mb(value: float) -> str:
    """MB (MiB) con un decimal y coma decimal (salida en español)."""
    return f"{value / MiB:+.1f}".replace(".", ",")


def _seconds(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def _report(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


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


@dataclass
class Run:
    """Lo que dejaron los 100 trabajos."""

    cases: tuple[str, ...]
    handles: list
    elapsed_s: float = 0.0
    memory_before: Memory | None = None
    memory_after: Memory | None = None
    refused_cancels: list[str] = dataclasses.field(default_factory=list)
    finished_twice: list[str] = dataclasses.field(default_factory=list)
    alive_workers: list[int] = dataclasses.field(default_factory=list)
    descendants: dict[int, str] = dataclasses.field(default_factory=dict)
    exit_wait_s: float = 0.0


def _request(index: int, case: str):
    timeout = TIMEOUT_S if case == "timeout" else JOB_TIMEOUT_S
    return protocol.new_request(
        "selftest", label=f"HITO H1 {index + 1:03d}: {case}", owner="jobs",
        params=dict(PARAMS[case]), timeout_s=timeout, grace_s=GRACE_S,
    )


def _drive(job_runner, run: Run) -> None:
    """Sondea hasta que acaban los 100, cancelando los que tocan en cuanto arrancan."""
    to_cancel = {handle.job_uid for handle, case in zip(run.handles, run.cases)
                 if case in CANCEL_ON_START}
    pending = {handle.job_uid for handle in run.handles}
    deadline = time.monotonic() + DEADLINE_S
    while pending:
        if time.monotonic() > deadline:
            raise AssertionError(f"{len(pending)} trabajos sin acabar en {DEADLINE_S} s")
        for update in job_runner.poll():
            uid = update.job_uid
            if uid in to_cancel and any(event.type == "start" for event in update.events):
                to_cancel.discard(uid)
                if not job_runner.cancel(uid):
                    run.refused_cancels.append(uid)
            if update.result is not None:
                if uid not in pending:
                    run.finished_twice.append(uid)
                pending.discard(uid)
        time.sleep(POLL_S)


def _wait_for_exit(run: Run, before: Mapping[int, tuple[int, str]], pids: list[int]) -> None:
    """Espera hasta ``EXIT_WAIT_S`` a que no quede vivo ningún worker ni descendiente suyo
    (comprobando cada 20 ms) y apunta lo que quede y lo que tardó."""
    started = time.monotonic()
    while True:
        run.alive_workers = [pid for pid in pids if _support.pid_alive(pid)]
        run.descendants = _descendants(before, _processes(), pids)
        run.exit_wait_s = time.monotonic() - started
        if not run.alive_workers and not run.descendants:
            return
        if run.exit_wait_s >= EXIT_WAIT_S:
            return
        time.sleep(POLL_S)


class HundredJobsTest(unittest.TestCase):
    """HITO H1: 100 trabajos seguidos de todos los finales, sin huérfanos ni escrituras en
    el proyecto y sin que crezca la memoria del lanzador."""

    run_data: Run

    @classmethod
    def setUpClass(cls) -> None:
        tmp = _support.jobs_tmp()
        base = tmp.__enter__()
        cls.addClassCleanup(tmp.__exit__, None, None, None)
        registry = mock.patch.dict(catalog._REGISTRY, clear=True)
        registry.start()
        cls.addClassCleanup(registry.stop)
        builtin = next(info for info in catalog.BUILTIN_WORKERS if info.name == "selftest")
        catalog.register_worker(dataclasses.replace(builtin, policy="subprocess",
                                                    default_timeout_s=JOB_TIMEOUT_S))

        project = _support.make_fake_project(base)
        jobs_root = paths.resolve_jobs_root(project_cache_dir=project.root / "cache",
                                            user_dir=base / "usuario")
        cls.base, cls.project, cls.jobs_root = base, project, jobs_root
        cls.fingerprints = project.fingerprints()
        cls.files_before = _snapshot(base)

        job_runner = runner.JobRunner(
            jobs_root=jobs_root, package_dir=EXTENSION_DIR,
            blender_python=Path(sys.executable), max_subprocess=PARALLEL,
            forbidden_roots=[project.root],
        )
        cls.addClassCleanup(job_runner.shutdown, timeout_s=3.0)

        run = Run(ORDER, [])
        processes_before = _processes()
        run.memory_before = _memory()
        started = time.monotonic()
        run.handles = [job_runner.submit(_request(index, case))
                       for index, case in enumerate(ORDER)]
        _drive(job_runner, run)
        run.elapsed_s = time.monotonic() - started
        run.memory_after = _memory()
        pids = [handle.pid for handle in run.handles if handle.pid is not None]
        _wait_for_exit(run, processes_before, pids)
        cls.run_data = run

    def test_hundred_jobs_of_every_kind(self) -> None:
        """RNF-004-07: son 100 trabajos en proceso aparte, 40 bien, 20 con fallo, 20
        cancelados, 10 con tiempo agotado y 10 que ignoran la cancelación; cada uno acaba
        una sola vez, y las 30 cancelaciones (20 + 10) se aceptan."""
        run = self.run_data
        self.assertEqual(len(run.handles), 100)
        self.assertEqual({case: run.cases.count(case) for case in COUNTS}, COUNTS)
        self.assertEqual(len({handle.job_uid for handle in run.handles}), 100)
        self.assertEqual(run.refused_cancels, [])
        self.assertEqual(run.finished_twice, [])
        self.assertTrue(all(handle.result() is not None for handle in run.handles))

    def test_state_matches_case(self) -> None:
        """RNF-004-07 (CE-004-03): cada ``state.json`` es el de su caso: estado, código de
        salida, error, cancelación (motivo y si fue forzada), proceso aparte con su pid,
        horas y duración, intérprete ``blender``; los que acaban bien entregan la suma exacta
        (499 500) y los demás no entregan nada."""
        for handle, case in zip(self.run_data.handles, self.run_data.cases):
            expected = EXPECTED[case]
            with self.subTest(trabajo=handle.job_uid, caso=case):
                record = records.read_record(handle.job_dir)
                self.assertIsNotNone(record)
                self.assertEqual(record.job_uid, handle.job_uid)
                self.assertEqual(record.state, expected.state)
                self.assertEqual(handle.result().state, expected.state)
                self.assertEqual(record.executor, "subprocess")
                self.assertEqual(record.exit_code, expected.exit_code)
                self.assertEqual(record.pid, handle.pid)
                self.assertIsInstance(record.pid, int)
                self.assertIsNotNone(record.started_at)
                self.assertIsNotNone(record.ended_at)
                self.assertGreaterEqual(record.duration_s, 0.0)
                self.assertEqual(record.interpreter.kind, "blender")
                if expected.error is None:
                    self.assertIsNone(record.error)
                else:
                    self.assertEqual(record.error.code, expected.error)
                if expected.cancel_reason is None:
                    self.assertIsNone(record.cancel)
                else:
                    self.assertEqual(record.cancel.reason, expected.cancel_reason)
                    self.assertIs(record.cancel.forced, expected.forced)
                if case == "ok":
                    self.assertEqual([o.role for o in record.outputs], [selftest.SUM_ROLE])
                    value = np.load(handle.job_dir.path / record.outputs[0].path,
                                    allow_pickle=False)
                    self.assertEqual(int(value), 1000 * 999 // 2)
                else:
                    self.assertEqual(record.outputs, ())

    def test_no_process_left(self) -> None:
        """RNF-004-07 y RF-004-13: al acabar no queda vivo ninguno de los 100 workers
        (``pid_alive``) ni ningún proceso nuevo que descienda de ellos (nietos)."""
        run = self.run_data
        pids = [handle.pid for handle in run.handles]
        self.assertEqual(len(set(pids)), 100)
        self.assertEqual({"workers": run.alive_workers, "descendientes": run.descendants},
                         {"workers": [], "descendientes": {}})
        self.assertLessEqual(run.exit_wait_s, EXIT_WAIT_S)

    def test_project_untouched(self) -> None:
        """RF-004-14: con la raíz de trabajos en la caché del proyecto, las huellas sha256
        de ``project.gpkg`` y ``blocks.duckdb`` no cambian y lo único nuevo está dentro de
        la carpeta de uno de los 100 trabajos."""
        self.assertEqual(self.project.fingerprints(), self.fingerprints)
        after = _snapshot(self.base)
        for rel, digest in self.files_before.items():
            self.assertEqual(after.get(rel), digest, rel)
        jobs = self.jobs_root.relative_to(self.base).as_posix()
        folders = {f"{jobs}/{handle.job_uid}/" for handle in self.run_data.handles}
        outside = [rel for rel in after
                   if rel not in self.files_before and not rel.startswith(tuple(folders))]
        self.assertEqual(outside, [])

    def test_requests_without_project_path(self) -> None:
        """RF-004-14: ninguna de las 100 peticiones contiene la ruta del proyecto (ni con
        «/», ni escapada en JSON, ni en otras mayúsculas)."""
        root = str(self.project.root)
        forms = {root, root.replace("\\", "/"), json.dumps(root)[1:-1]}
        flat_root = root.replace("\\", "/").casefold()
        for handle in self.run_data.handles:
            with self.subTest(trabajo=handle.job_uid):
                raw = (handle.job_dir.path / protocol.REQUEST_FILE).read_text(encoding="utf-8")
                for form in forms:
                    self.assertNotIn(form.casefold(), raw.casefold())
                for text in _strings(json.loads(raw)):
                    self.assertNotIn(flat_root, text.replace("\\", "/").casefold())

    def test_launcher_memory_growth(self) -> None:
        """RNF-004-07: la memoria del proceso que lanza los 100 trabajos (conjunto de
        trabajo y memoria privada, tras recoger la basura) crece ≤ 20 MB."""
        run = self.run_data
        before, after = run.memory_before, run.memory_after
        working_set = after.working_set - before.working_set
        private = after.private - before.private
        _report(
            f"RNF-004-07: 100 trabajos seguidos (40 bien, 20 con fallo, 20 cancelados, "
            f"10 con tiempo agotado y 10 forzados), {PARALLEL} a la vez: "
            f"{_seconds(run.elapsed_s)} s; memoria del lanzador {_mb(working_set)} MB "
            f"(conjunto de trabajo) y {_mb(private)} MB (privada), presupuesto 20 MB; "
            f"{len(run.alive_workers)} workers y {len(run.descendants)} descendientes vivos "
            f"al final (comprobado en {_seconds(run.exit_wait_s)} s)"
        )
        self.assertLessEqual(working_set, MEMORY_BUDGET)
        self.assertLessEqual(private, MEMORY_BUDGET)


if __name__ == "__main__":
    unittest.main()
