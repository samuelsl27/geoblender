# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendimiento de los trabajos en segundo plano (spec 004, H1 y T35; RNF-004-01 a
RNF-004-08; plan 004 §7, ``tests/rendimiento``).

Se ejecuta con ``tools/check.py --rendimiento``: el Python de Blender, en disco local
(``%TEMP%``), con procesos reales. Cada prueba imprime su cifra en una línea
``RNF-004-nn: …``, con el intérprete con que se midió (``tools/check.py`` las recoge), y la
compara con su presupuesto. El RNF-004-03 (lo que dura cada sondeo del seguimiento) y el
RNF-004-04 (un avance llega a la barra de estado) se miden dentro de Blender, con su
``tick``: ``tests/rendimiento/blender/perf_jobs_monitor.py``.

- RNF-004-01: lanzar un trabajo (carpeta, petición y arranque del proceso: ``submit`` de
  una petición, sin entradas) devuelve el control en ≤ 0,2 s: mediana de 20 lanzamientos
  seguidos del autodiagnóstico en proceso aparte con el Python de Blender, cada uno cuando
  ha acabado el anterior.
- RNF-004-02: del lanzamiento (la llamada a ``submit``) al primer evento del worker (su
  ``start``, visto al sondear el lanzador cada 2 ms): ≤ 0,3 s sin motor (los mismos 20, en
  el entorno ``blender``) y ≤ 0,5 s con motor (otros 20 en el entorno ``compute``, con el
  motor de pruebas: arranque aislado e ``import numpy`` del motor), medianas.
- RNF-004-05: con el motor de pruebas, el autodiagnóstico ``matmul`` del menú, A @ B
  float64 2000 × 2000 en el worker (el mejor de 3), en < 1 s.
- RNF-004-06: la cadena de instalación del producto (``RuntimeSetup.install``: instalar con
  el ``pip`` del Python de Blender, verificar con el motor y adoptar) desde el almacén de
  ruedas local, sin red, en unos datos de usuario temporales (no toca el motor de
  pruebas): ≤ 60 s, ≤ 80 MB en disco y ruedas (la descarga) de ≤ 20 MB. El almacén es el de
  ``GEOBLENDER_WHEELHOUSE`` o, si no está definida, aquel del que salió el motor de pruebas
  (su ``runtime.json``); sin almacén, se omite con ``[ENTORNO] runtime``.
- RNF-004-08: ninguna ruta del motor recién instalado ni del motor de pruebas pasa de 240
  caracteres, y tampoco la ruta más larga de su ``site`` puesta en su sitio de los datos
  de usuario por defecto de Blender en este equipo (la de
  ``bpy.utils.extension_path_user``: ``%APPDATA%/Blender Foundation/Blender/<versión>/``
  ``extensions/.user/user_default/<extensión>/runtime/<lock_id>/site``).

Las del motor (la mitad «con motor» del RNF-004-02, el 05, el 06 y el 08) necesitan el
motor de cálculo de pruebas de ``tools/make_runtime.py``; sin él se omiten con
``[ENTORNO] runtime`` y la orden que lo crea.

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
import platform
import re
import statistics
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
from tests.support import resources
from tests.support import runtime as runtime_support
from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR, tools_on_path

tools_on_path()

from gbtools import wheels  # noqa: E402

catalog = import_geoblender("jobs.catalog")
cleanup = import_geoblender("jobs.cleanup")
paths = import_geoblender("jobs.paths")
protocol = import_geoblender("jobs.protocol")
records = import_geoblender("jobs.records")
runner = import_geoblender("jobs.runner")
runtime = import_geoblender("jobs.runtime")
selftest = import_geoblender("jobs.selftest")
worker_api = import_geoblender("jobs.worker_api")

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


# --- T35: lanzar, primer evento, motor de cálculo ------------------------------------------

LAUNCHES = 20
"""Lanzamientos de cada mediana (RNF-004-01 y RNF-004-02)."""
LAUNCH_BUDGET_S = 0.2  # RNF-004-01: mediana ≤ 0,2 s
FIRST_EVENT_BUDGET_S = 0.3  # RNF-004-02: sin motor, mediana ≤ 0,3 s
FIRST_EVENT_ENGINE_BUDGET_S = 0.5  # RNF-004-02: con motor, mediana ≤ 0,5 s
MATMUL_BUDGET_S = 1.0  # RNF-004-05: < 1 s
MATMUL_N = 2000
INSTALL_BUDGET_S = 60.0  # RNF-004-06: desde un almacén local, ≤ 60 s
DISK_BUDGET_MB = 80.0  # RNF-004-06: ≤ 80 MB en disco
DOWNLOAD_BUDGET_MB = 20.0  # RNF-004-06: ruedas de ≤ 20 MB
PATH_BUDGET = 240  # RNF-004-08: ninguna ruta del motor de más de 240 caracteres
FIRST_EVENT_POLL_S = 0.002
"""Cada cuánto se sondea el lanzador hasta ver el primer evento: la cifra sale, como mucho,
2 ms (y lo que dura un sondeo) más tarde que la llegada."""
LAUNCH_DEADLINE_S = 30.0
INSTALL_DEADLINE_S = 600.0
QUICK_SUM = {"op": "chunked_sum", "n": 1000, "chunks": 1}
"""Un autodiagnóstico que acaba enseguida: lo que cuenta es su arranque."""
VERSION_FOLDER = re.compile(r"\d+\.\d+")
WHEELHOUSE_HINT = (
    f"defina {wheels.ENV_WHEELHOUSE} con el almacén de ruedas del motor de cálculo (lo "
    "rellena tools/fetch_runtime_wheels.py --wheelhouse <almacén>)"
)


@dataclass(frozen=True)
class Launch:
    """Un lanzamiento: lo que tardó ``submit`` en devolver el control, lo que tardó en verse
    el primer evento del worker desde que se llamó a ``submit`` y su tipo, y el trabajo."""

    returned_s: float
    first_event_s: float
    first_type: str
    handle: object


class _TestEngine:
    """El motor de cálculo de pruebas visto por el lanzador (``interpreter.ComputeRuntime``):
    el lock de esta versión de Geoblender, su ``lock_id``, listo y su carpeta ``site``."""

    def __init__(self, site: Path) -> None:
        self.lock = runtime.read_lock()
        self.lock_id = self.lock.lock_id
        self._site = Path(site)

    def status(self) -> str:
        return runtime.STATUS_READY

    def site_dir(self) -> Path:
        return self._site


def _seconds3(value: float) -> str:
    """Segundos con tres decimales y coma decimal (salida en español)."""
    return f"{value:.3f}".replace(".", ",")


def _number(value: float, decimals: int = 1) -> str:
    return f"{value:.{decimals}f}".replace(".", ",")


def _wait_result(job_runner, handle, deadline_s: float = LAUNCH_DEADLINE_S):
    """Sondea ``job_runner`` hasta que acaba ``handle`` y devuelve su resultado."""
    deadline = time.monotonic() + deadline_s
    while handle.result() is None:
        if time.monotonic() > deadline:
            raise AssertionError(f"el trabajo {handle.job_uid} no acabó en {deadline_s} s")
        job_runner.poll()
        time.sleep(POLL_S)
    return handle.result()


def _launch(job_runner, request) -> Launch:
    """Lanza ``request``, mide lo que tarda ``submit`` en volver y lo que tarda en verse el
    primer evento del worker (sondeando cada 2 ms) y espera a que acabe."""
    started = time.perf_counter()
    handle = job_runner.submit(request)
    returned = time.perf_counter() - started
    first: tuple[float, str] | None = None
    while first is None:
        for update in job_runner.poll():
            if update.job_uid == handle.job_uid and update.events and first is None:
                first = (time.perf_counter() - started, update.events[0].type)
        if first is not None:
            break
        result = handle.result()
        if result is not None:
            raise AssertionError(f"el trabajo acabó sin eventos: {result.state} "
                                 f"{result.error_code}: {result.error_text}")
        if time.perf_counter() - started > LAUNCH_DEADLINE_S:
            raise AssertionError(f"sin eventos del worker en {LAUNCH_DEADLINE_S} s")
        time.sleep(FIRST_EVENT_POLL_S)
    _wait_result(job_runner, handle)
    return Launch(returned, first[0], first[1], handle)


def _median_line(values: list[float]) -> str:
    """«mediana X s de N (mín. A, máx. B)», con tres decimales."""
    return (f"mediana {_seconds3(statistics.median(values))} s de {len(values)} "
            f"(mín. {_seconds3(min(values))}, máx. {_seconds3(max(values))})")


def _interpreter_text(info) -> str:
    """El intérprete de un ``state.json`` (``InterpreterInfo``), para las líneas de cifra."""
    if info.kind == "compute":
        return (f"motor {info.lock_id}: Python {info.python}, numpy {info.numpy}, "
                f"BLAS {info.blas}")
    return f"Python de Blender {info.python}, numpy {info.numpy}"


def _selftest_registry(cls) -> None:
    """El registro de tipos de trabajo, vacío durante la clase, con el autodiagnóstico en
    proceso aparte (y sin tiempo máximo que alcanzar)."""
    registry = mock.patch.dict(catalog._REGISTRY, clear=True)
    registry.start()
    cls.addClassCleanup(registry.stop)
    builtin = next(info for info in catalog.BUILTIN_WORKERS if info.name == "selftest")
    catalog.register_worker(dataclasses.replace(builtin, policy="subprocess",
                                                default_timeout_s=JOB_TIMEOUT_S))


class LaunchTest(unittest.TestCase):
    """Lanzar trabajos en proceso aparte con el Python de Blender: lo que tarda ``submit``
    en devolver el control y lo que tarda en llegar el primer evento."""

    launches: list[Launch]

    @classmethod
    def setUpClass(cls) -> None:
        tmp = _support.jobs_tmp()
        base = tmp.__enter__()
        cls.addClassCleanup(tmp.__exit__, None, None, None)
        _selftest_registry(cls)
        job_runner = runner.JobRunner(jobs_root=base / "jobs", package_dir=EXTENSION_DIR,
                                      blender_python=Path(sys.executable), max_subprocess=1)
        cls.addClassCleanup(job_runner.shutdown, timeout_s=3.0)
        cls.launches = [
            _launch(job_runner, protocol.new_request(
                "selftest", label=f"Lanzamiento {index + 1:02d}", owner="jobs",
                params=dict(QUICK_SUM), environment="blender"))
            for index in range(LAUNCHES)
        ]
        cls.records = [records.read_record(launch.handle.job_dir) for launch in cls.launches]

    def test_launch_returns_control_quickly(self) -> None:
        """RNF-004-01: ``submit`` de una petición (carpeta, ``request.json``,
        ``state.json`` y arranque del proceso) devuelve el control en ≤ 0,2 s (mediana de 20
        lanzamientos seguidos); los 20 acaban bien, en proceso aparte con el Python de
        Blender."""
        returned = [launch.returned_s for launch in self.launches]
        _report(f"RNF-004-01: lanzar un trabajo (carpeta, petición y arranque del proceso; "
                f"{_interpreter_text(self.records[0].interpreter)}): {_median_line(returned)},"
                f" presupuesto {_number(LAUNCH_BUDGET_S)} s")
        self.assertEqual(len(returned), LAUNCHES)
        for launch, record in zip(self.launches, self.records):
            with self.subTest(trabajo=launch.handle.job_uid):
                self.assertEqual(launch.handle.result().state, "succeeded")
                self.assertEqual((record.executor, record.interpreter.kind),
                                 (runner.EXECUTOR_SUBPROCESS, "blender"))
        self.assertLessEqual(statistics.median(returned), LAUNCH_BUDGET_S)

    def test_first_event_without_engine(self) -> None:
        """RNF-004-02: sin motor (entorno ``blender``), del lanzamiento al primer evento del
        worker, su ``start``, pasan ≤ 0,3 s (mediana de 20)."""
        first = [launch.first_event_s for launch in self.launches]
        _report(f"RNF-004-02: del lanzamiento al primer evento del worker, sin motor "
                f"({_interpreter_text(self.records[0].interpreter)}): {_median_line(first)}, "
                f"presupuesto {_number(FIRST_EVENT_BUDGET_S)} s")
        self.assertEqual({launch.first_type for launch in self.launches}, {"start"})
        self.assertLessEqual(statistics.median(first), FIRST_EVENT_BUDGET_S)


@resources.requires(runtime_support.RUNTIME, runtime_support.RUNTIME_HINT)
class EngineTest(unittest.TestCase):
    """Con el motor de cálculo de pruebas: el primer evento de un worker ``compute`` y el
    producto 2000 × 2000 en el worker."""

    launches: list[Launch]

    @classmethod
    def setUpClass(cls) -> None:
        site = runtime_support.runtime_site()
        tmp = _support.jobs_tmp()
        base = tmp.__enter__()
        cls.addClassCleanup(tmp.__exit__, None, None, None)
        _selftest_registry(cls)
        cls.engine = _TestEngine(site)
        job_runner = runner.JobRunner(jobs_root=base / "jobs", package_dir=EXTENSION_DIR,
                                      blender_python=Path(sys.executable),
                                      runtime=cls.engine, max_subprocess=1)
        cls.addClassCleanup(job_runner.shutdown, timeout_s=3.0)
        cls.launches = [
            _launch(job_runner, protocol.new_request(
                "selftest", label=f"Lanzamiento con el motor {index + 1:02d}", owner="jobs",
                params=dict(QUICK_SUM), environment="compute"))
            for index in range(LAUNCHES)
        ]
        cls.records = [records.read_record(launch.handle.job_dir) for launch in cls.launches]
        matmul = job_runner.submit(protocol.new_request(
            "selftest", label="Producto con el motor", owner="jobs",
            params={"op": "matmul", "n": MATMUL_N}))
        cls.matmul = _wait_result(job_runner, matmul)
        cls.matmul_record = records.read_record(matmul.job_dir)

    def check_engine_interpreter(self, record) -> None:
        """El trabajo corrió en ``compute`` con el numpy del lock del motor de pruebas y una
        BLAS optimizada."""
        info = record.interpreter
        self.assertEqual((info.kind, info.lock_id, info.numpy),
                         ("compute", self.engine.lock_id,
                          self.engine.lock.package(runtime.LOCK_NUMPY).version))
        self.assertNotIn(info.blas, (runtime.UNOPTIMIZED_BLAS, worker_api.UNKNOWN_BLAS, None))

    def test_first_event_with_engine(self) -> None:
        """RNF-004-02: con motor (entorno ``compute``: arranque aislado e ``import numpy``
        del motor de pruebas), del lanzamiento al primer evento del worker, su ``start``,
        pasan ≤ 0,5 s (mediana de 20); los 20 acaban bien con el numpy del motor."""
        first = [launch.first_event_s for launch in self.launches]
        _report(f"RNF-004-02: del lanzamiento al primer evento del worker, con motor "
                f"({_interpreter_text(self.records[0].interpreter)}): {_median_line(first)}, "
                f"presupuesto {_number(FIRST_EVENT_ENGINE_BUDGET_S)} s")
        self.assertEqual({launch.first_type for launch in self.launches}, {"start"})
        for launch, record in zip(self.launches, self.records):
            with self.subTest(trabajo=launch.handle.job_uid):
                self.assertEqual(launch.handle.result().state, "succeeded")
                self.check_engine_interpreter(record)
        self.assertLessEqual(statistics.median(first), FIRST_EVENT_ENGINE_BUDGET_S)

    def test_matmul_with_engine(self) -> None:
        """RNF-004-05: con el motor de cálculo, A @ B float64 2000 × 2000 en el worker (el
        autodiagnóstico ``matmul`` del menú, el mejor de 3) tarda < 1 s."""
        result = self.matmul
        self.assertEqual(result.state, "succeeded", f"{result.error_code}: {result.error_text}")
        summary = dict(result.summary)
        self.check_engine_interpreter(self.matmul_record)
        self.assertEqual((summary["op"], summary["n"]), ("matmul", MATMUL_N))
        best = summary["best_s"]
        _report(f"RNF-004-05: A @ B float64 {MATMUL_N} × {MATMUL_N} en el worker con el motor "
                f"({_interpreter_text(self.matmul_record.interpreter)}): "
                f"{_seconds3(best)} s, el mejor de {summary['repeats']} "
                f"({_number(summary['gflops'], 0)} GFLOP/s), presupuesto < "
                f"{_number(MATMUL_BUDGET_S)} s")
        self.assertLess(best, MATMUL_BUDGET_S)


def _wheelhouse(site: Path, lock) -> Path | None:
    """El almacén de ruedas con todas las del lock: el de ``GEOBLENDER_WHEELHOUSE`` o, si no
    está definida, el del que salió el motor de pruebas (su ``runtime.json``); ``None`` si
    no hay ninguno o le falta alguna."""
    folder = wheels.wheelhouse()
    if folder is None:
        info = runtime.read_runtime_info(Path(site).parent) or {}
        source = info.get("source") or {}
        if source.get("kind") == runtime.SOURCE_WHEELHOUSE:
            folder = source.get("folder")
    if not folder:
        return None
    store = Path(folder)
    if not all((store / package.filename).is_file() for package in lock.packages):
        return None
    return store


def _longest_path(folder: Path) -> tuple[int, int]:
    """La ruta completa más larga bajo ``folder`` (carpetas y ficheros) y la más larga
    relativa a ``folder``, en caracteres."""
    base = str(folder)
    longest = relative = 0
    for current, dirs, files in os.walk(base):
        for name in (*dirs, *files):
            text = os.path.join(current, name)
            longest = max(longest, len(text))
            relative = max(relative, len(text) - len(base) - 1)
    return longest, relative


def _default_engine_site(lock_id: str) -> Path | None:
    """La carpeta ``site`` del motor ``lock_id`` en los datos de usuario por defecto de
    Blender en este equipo (``bpy.utils.extension_path_user`` de la extensión instalada en
    el repositorio de usuario ``user_default``), o ``None`` si no se sabe (sin
    ``%APPDATA%``, o un Python que no está en ``<Blender>/<versión>/python/bin``)."""
    appdata = os.environ.get("APPDATA", "").strip()
    version = Path(sys.executable).parents[2].name
    if not appdata or not VERSION_FOLDER.fullmatch(version):
        return None
    return Path(appdata, "Blender Foundation", "Blender", version, "extensions", ".user",
                "user_default", EXTENSION_DIR.name, runtime.RUNTIME_DIR, lock_id,
                runtime.SITE_DIR)


@resources.requires(runtime_support.RUNTIME, runtime_support.RUNTIME_HINT)
class EngineInstallTest(unittest.TestCase):
    """La cadena de instalación del producto desde el almacén de ruedas local, cronometrada,
    y la longitud de las rutas del motor."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.test_site = runtime_support.runtime_site()
        lock = runtime.read_lock()
        store = _wheelhouse(cls.test_site, lock)
        if store is None:
            raise unittest.SkipTest(
                resources.skip_reason(runtime_support.RUNTIME, WHEELHOUSE_HINT))
        tmp = _support.jobs_tmp()
        base = tmp.__enter__()
        cls.addClassCleanup(tmp.__exit__, None, None, None)
        registry = mock.patch.dict(catalog._REGISTRY, clear=True)
        registry.start()
        cls.addClassCleanup(registry.stop)
        for info in catalog.BUILTIN_WORKERS:
            if info.name in (runtime.INSTALL_WORKER, runtime.CHECK_WORKER):
                catalog.register_worker(info)

        cls.engine = runtime.ComputeEnvironment(base / "usuario", lock)
        cls.plan = cls.engine.plan_install(runtime.WheelSource.wheelhouse(store),
                                           online_access=False)
        consent = runtime.Consent.given(cls.plan)
        launcher = runner.JobRunner(jobs_root=base / "jobs", package_dir=EXTENSION_DIR,
                                    blender_python=Path(sys.executable), runtime=cls.engine)
        cls.addClassCleanup(launcher.shutdown, timeout_s=3.0)
        started = time.perf_counter()
        setup = runtime.RuntimeSetup.install(launcher, cls.engine, cls.plan, consent)
        while not setup.done:
            if time.perf_counter() - started > INSTALL_DEADLINE_S:
                setup.cancel()
                raise AssertionError(f"la instalación no acabó en {INSTALL_DEADLINE_S} s")
            launcher.poll()
            time.sleep(POLL_S)
        cls.install_s = time.perf_counter() - started
        cls.setup = setup
        cls.status = cls.engine.status()
        cls.disk_mb = cleanup.folder_size_mb(cls.engine.path)
        cls.info = runtime.read_runtime_info(cls.engine.path) or {}
        cls.installed_paths = _longest_path(cls.engine.path)
        cls.site_paths = _longest_path(cls.engine.site_dir())
        cls.test_paths = _longest_path(Path(cls.test_site))

    def check_installed(self) -> None:
        """La cadena acabó bien y dejó el motor listo, verificado con el numpy del lock."""
        setup = self.setup
        tail = ""
        if setup.handles:
            log = Path(setup.handles[-1].job_dir.log_file)
            tail = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        self.assertEqual(setup.state, runtime.SETUP_SUCCEEDED,
                         f"{setup.error_code}: {setup.error_text}\n{tail}")
        self.assertEqual(self.status, runtime.STATUS_READY)
        verification = self.info.get("verification") or {}
        self.assertIs(verification.get("ok"), True)
        self.assertEqual(verification.get("numpy"),
                         self.engine.lock.package(runtime.LOCK_NUMPY).version)

    def test_install_from_local_store(self) -> None:
        """RNF-004-06: el motor de esta spec (solo numpy), instalado con la cadena del
        producto desde el almacén de ruedas local y sin red, tarda ≤ 60 s, ocupa ≤ 80 MB en
        disco y sus ruedas (la descarga) suman ≤ 20 MB."""
        self.check_installed()
        self.assertEqual(self.plan.source.kind, runtime.SOURCE_WHEELHOUSE)
        verification = self.info["verification"]
        packages = ", ".join(f"{p.name} {p.version}" for p in self.plan.packages)
        _report(f"RNF-004-06: instalación del motor {self.engine.lock_id} ({packages}) desde "
                f"el almacén de ruedas local, sin red (pip del Python de Blender "
                f"{platform.python_version()}; verificación con el motor: numpy "
                f"{verification['numpy']}, BLAS {verification['blas']}): "
                f"{_number(self.install_s)} s (≤ {INSTALL_BUDGET_S:g} s); "
                f"{_number(self.disk_mb)} MB en disco (≤ {DISK_BUDGET_MB:g} MB); ruedas de "
                f"{_number(self.plan.download_mb)} MB (≤ {DOWNLOAD_BUDGET_MB:g} MB)")
        self.assertLessEqual(self.install_s, INSTALL_BUDGET_S)
        self.assertLessEqual(self.disk_mb, DISK_BUDGET_MB)
        self.assertLessEqual(self.plan.download_mb, DOWNLOAD_BUDGET_MB)

    def test_engine_paths_within_240(self) -> None:
        """RNF-004-08: ninguna ruta del motor recién instalado ni del motor de pruebas pasa
        de 240 caracteres (tampoco la que midió su verificación), ni la más larga de su
        ``site`` en el sitio del motor en los datos de usuario por defecto de Blender."""
        self.check_installed()
        installed, _relative = self.installed_paths
        _site_longest, relative = self.site_paths
        test_engine, _ = self.test_paths
        verified = self.info["verification"]["max_path_length"]
        default_site = _default_engine_site(self.engine.lock_id)
        projected = None if default_site is None else len(str(default_site)) + 1 + relative
        where = ("sin datos de usuario por defecto que medir" if projected is None
                 else f"{projected} en los datos de usuario por defecto de Blender")
        _report(f"RNF-004-08: ruta más larga del motor {self.engine.lock_id}: {installed} "
                f"caracteres recién instalado en una carpeta temporal ({verified} al "
                f"verificarlo); {test_engine} en el motor de pruebas; {where} (la más larga "
                f"de su site, {relative}); presupuesto {PATH_BUDGET}")
        self.assertGreater(relative, 0)
        for name, value in (("instalado", installed), ("verificado", verified),
                            ("motor de pruebas", test_engine), ("por defecto", projected)):
            if value is not None:
                with self.subTest(name):
                    self.assertLessEqual(value, PATH_BUDGET)


if __name__ == "__main__":
    unittest.main()
