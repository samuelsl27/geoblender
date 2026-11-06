# SPDX-License-Identifier: GPL-3.0-or-later
"""Arranque de los workers en un proceso aparte (spec 004, T08; RF-004-01, RF-004-15; plan
004 §5.3.3, §5.3.4 y §5.4.3).

``workers/_bootstrap.py`` se lanza aquí a mano, como lo lanzará el lanzador:
``python.exe -I -B -u <paquete>/workers/_bootstrap.py --package-dir <paquete> --job-dir
<carpeta> --kind blender``, con la carpeta del trabajo como carpeta de trabajo, la entrada
estándar en una tubería abierta (vigilancia del padre), la salida estándar como canal de
eventos y la de error en ``job.log`` (``LaunchedWorker`` de ``tests/support/jobs_fixtures.py``).

Para no esperar en serie, todos los workers del módulo se lanzan a la vez al empezar
(``setUpModule``) y cada prueba mira lo que dejó el suyo:

- ``noise``: suma por trozos con ``stdout_noise`` (``print()`` y escritura directa en el
  descriptor 1, como una librería en C, con una línea que imita un evento ``result``).
- ``parent``: un trabajo de 30 s cuyo padre «muere» (se cierra su entrada estándar) nada
  más lanzarlo.
- ``unknown``, ``no_request`` y ``bad_args``: un tipo de trabajo que no existe, una carpeta
  sin ``request.json`` y unos argumentos incompletos.
- ``copy``: una copia del paquete con un worker de prueba que devuelve su entrada tal cual,
  lanzada **sin** ``-B`` (el paso 0 del arranque, ``sys.dont_write_bytecode``, basta).
- ``stdin``: en esa copia, un worker que consulta su entrada estándar desde el hilo principal
  mientras la vigila el arranque, como la inicialización de la libgfortran que lleva el
  OpenBLAS de numpy 2.5.3 al importarlo en el motor (spec 004, T30).
"""

import hashlib
import json
import platform
import shutil
import subprocess
import time
import unittest
from pathlib import Path

import numpy as np

from tests.support import jobs_fixtures as _support
from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR

protocol = import_geoblender("jobs.protocol")
paths = import_geoblender("jobs.paths")

SUM_N = 1_000_000
SUM_CHUNKS = 5
NOISE_PLACES = ("inicio", *(f"trozo {k}" for k in range(1, SUM_CHUNKS + 1)))
PARENT_JOB_S = 30.0
UNKNOWN_WORKER = "gbtest_nada"
ECHO_WORKER = "gbtest_echo"

# Worker de prueba que se añade a la copia del paquete: devuelve su entrada «data» tal cual
# (RF-004-01), con la huella de sus bytes, su tipo y su forma.
ECHO_SOURCE = '''# SPDX-License-Identifier: GPL-3.0-or-later
"""Worker de las pruebas: copia su entrada «data» a out/echo.npy sin tocarla."""

import hashlib

import numpy as np


def main(ctx):
    array = np.load(ctx.input_path("data"), allow_pickle=False)
    path = ctx.output_path("echo.npy")
    with open(path, "wb") as handle:
        np.save(handle, array, allow_pickle=False)
    ctx.add_output(path, "echo")
    return {
        "dtype": array.dtype.str,
        "shape": list(array.shape),
        "sha256": hashlib.sha256(array.tobytes()).hexdigest(),
    }
'''
STDIN_WORKER = "gbtest_stdin"
STDIN_TIMEOUT_S = 5.0
# Worker de prueba que consulta su entrada estándar (una tubería) desde el hilo principal, como
# la DLL de OpenBLAS de numpy 2.5.3 (con libgfortran) al cargarse en el motor de cálculo. Con
# una lectura pendiente de otro hilo sobre la misma tubería, Windows no la contesta nunca.
STDIN_SOURCE = '''# SPDX-License-Identifier: GPL-3.0-or-later
"""Worker de las pruebas: consulta su entrada estándar desde el hilo principal."""

import ctypes
import msvcrt
from ctypes import wintypes


def main(ctx):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.PeekNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                       ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD),
                                       ctypes.c_void_p]
    kernel32.PeekNamedPipe.restype = wintypes.BOOL
    available = wintypes.DWORD()
    answered = kernel32.PeekNamedPipe(msvcrt.get_osfhandle(0), None, 0, None,
                                      ctypes.byref(available), None)
    return {"answered": bool(answered)}
'''

_RUNS: dict[str, _support.WorkerRun] = {}
_JOBS: dict[str, object] = {}
_STATE: dict[str, object] = {}


def _utm_array() -> np.ndarray:
    """float64 con coordenadas UTM sintéticas de 4,4 Mm (que en float32 perderían los
    decimales), un NaN con carga útil propia, −0,0, un subnormal e infinitos."""
    data = np.array(
        [
            [712_345.678_901, 4_398_765.432_109, 512.25],
            [712_346.000_001, 4_398_766.999_999, -0.0],
            [np.inf, -np.inf, 5e-324],
            [0.0, 0.0, 0.0],
        ],
        dtype=np.float64,
    )
    bits = data.view(np.uint64)
    bits[3, 0] = 0x7FF8_0000_DEAD_BEEF  # NaN silencioso con carga útil
    bits[3, 1] = 0xFFF0_0000_0000_0001  # NaN señalizador negativo
    return data


def _pycache(package: Path) -> set[str]:
    """Las rutas (relativas) de ``package`` que están dentro de un ``__pycache__``."""
    found: set[str] = set()
    for path in package.rglob("*"):
        parts = path.relative_to(package).parts
        if "__pycache__" in parts:
            found.add("/".join(parts))
    return found


def _lose_channel(worker: _support.LaunchedWorker) -> dict[str, object]:
    """Lee la primera línea del canal (el evento ``start``) y cierra su extremo de lectura
    con la entrada estándar todavía abierta: el siguiente evento del worker no tiene quien lo
    lea, como cuando el padre muere justo antes de que la vigilancia lo vea (spec 004, T47).
    Devuelve el código de salida, los segundos desde el cierre y ``job.log``."""
    first = worker.process.stdout.readline()
    worker.process.stdout.close()
    closed_at = time.monotonic()
    try:
        returncode = worker.process.wait(timeout=_support.WORKER_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        worker.close()
        returncode = None
    elapsed = time.monotonic() - closed_at
    worker.lose_parent()
    log = (worker.job_dir / paths.LOG_FILE).read_bytes().decode("utf-8", "replace")
    return {"first": first, "returncode": returncode, "elapsed_s": elapsed, "log": log}


def setUpModule() -> None:
    tmp = _support.jobs_tmp()
    base = tmp.__enter__()
    unittest.addModuleCleanup(tmp.__exit__, None, None, None)
    root = base / "jobs"

    copy = base / "pkg"
    shutil.copytree(
        EXTENSION_DIR, copy,
        ignore=shutil.ignore_patterns("__pycache__", "*.py[cod]", "bl", "resources",
                                      "thirdparty", "wheels"),
    )
    (copy / "workers" / f"{ECHO_WORKER}.py").write_bytes(ECHO_SOURCE.encode("utf-8"))
    (copy / "workers" / f"{STDIN_WORKER}.py").write_bytes(STDIN_SOURCE.encode("utf-8"))
    _STATE["copy"] = copy
    _STATE["utm"] = _utm_array()
    _STATE["pycache_before"] = _pycache(EXTENSION_DIR)

    jobs = {
        "parent": _support.prepare_job(root, params={"chunks": 600, "sleep_s": 0.05}),
        "noise": _support.prepare_job(
            root, params={"n": SUM_N, "chunks": SUM_CHUNKS, "stdout_noise": True}
        ),
        "unknown": _support.prepare_job(root, UNKNOWN_WORKER),
        "no_request": paths.job_dir(root, paths.new_job_uid()).create(),
        "bad_args": paths.job_dir(root, paths.new_job_uid()).create(),
        "copy": _support.prepare_job(root, ECHO_WORKER, arrays={"data": _STATE["utm"]}),
        "stdin": _support.prepare_job(root, STDIN_WORKER),
        "channel": _support.prepare_job(root, params={"chunks": 600, "sleep_s": 0.05}),
    }
    _JOBS.update(jobs)
    launched: dict[str, _support.LaunchedWorker] = {}
    for name, job in jobs.items():
        options: dict[str, object] = {}
        if name == "bad_args":
            options["args"] = ("--package-dir", str(EXTENSION_DIR), "--kind", "blender")
        elif name == "copy":
            options.update(package_dir=copy, flags=("-I", "-u"))
        elif name == "stdin":
            options.update(package_dir=copy)
        worker = _support.LaunchedWorker(job.path, **options)
        unittest.addModuleCleanup(worker.close)
        launched[name] = worker
        if name == "parent":
            worker.lose_parent()
    for name, worker in launched.items():
        if name == "channel":
            _STATE["channel"] = _lose_channel(worker)
            continue
        if name == "stdin":
            try:
                _RUNS[name] = worker.finish(timeout_s=STDIN_TIMEOUT_S)
            except AssertionError as exc:  # colgado: lo dice su prueba
                _STATE["stdin_hung"] = str(exc)
            continue
        _RUNS[name] = worker.finish()
    _STATE["pycache_after"] = _pycache(EXTENSION_DIR)


class ChannelTest(unittest.TestCase):
    """RF-004-15: por el canal solo pasan eventos, en orden; lo que imprime el cálculo (con
    ``print()`` o directamente en el descriptor 1, como una librería en C) va a ``job.log``."""

    def test_events_in_order_and_final_progress(self):
        """RF-004-15: ``start`` → ``log``/``progress``… → ``result``, con el avance creciente
        hasta 1,0 («Trozo 5 de 5»), y salida 0."""
        run = _RUNS["noise"]
        self.assertEqual(run.returncode, 0, run.log)
        types = run.types()
        self.assertEqual(types[0], "start")
        self.assertEqual(types[-1], "result")
        self.assertEqual(set(types[1:-1]), {"log", "progress"})
        fracs = [event.frac for event in run.of_type("progress")]
        self.assertEqual(fracs, sorted(fracs))
        last = run.of_type("progress")[-1]
        self.assertEqual((last.frac, last.msg), (1.0, f"Trozo {SUM_CHUNKS} de {SUM_CHUNKS}"))
        times = [event.ts for event in run.events]
        self.assertEqual(times, sorted(times))

    def test_channel_carries_only_events(self):
        """RF-004-15: ninguna línea del canal deja de ser un evento: ni el ruido de
        ``print()`` ni el del descriptor 1, ni la línea que imita un evento ``result``."""
        run = _RUNS["noise"]
        self.assertEqual(run.invalid, ())
        self.assertNotIn(b"ruido", run.channel)
        self.assertEqual(len(run.of_type("result")), 1)
        self.assertNotIn("ruido", run.of_type("result")[0].summary)

    def test_printed_and_native_output_go_to_job_log(self):
        """RF-004-15: lo impreso por ``print()`` y lo escrito en el descriptor 1 está en
        ``job.log``, en UTF-8."""
        run = _RUNS["noise"]
        text = run.log_bytes.decode("utf-8")
        for place in NOISE_PLACES:
            with self.subTest(place=place):
                self.assertIn(f"Autodiagnóstico: ruido con print() ({place})", text)
                self.assertIn(
                    "Autodiagnóstico: ruido por el descriptor 1, como una librería en C "
                    f"({place})",
                    text,
                )
        self.assertEqual(text.count('"summary": {"ruido": true}'), len(NOISE_PLACES))


class StartEventTest(unittest.TestCase):
    """RF-004-15: el evento ``start`` cuenta el proceso y las versiones del intérprete."""

    def test_start_reports_interpreter(self):
        """RF-004-15: pid del worker, intérprete ``blender`` y las versiones de Python (la
        del Python de Blender), numpy (el suyo) y su BLAS."""
        run = _RUNS["noise"]
        info = run.of_type("start")[0].info
        self.assertEqual(set(info), {"pid", "kind", "python", "numpy", "blas"})
        self.assertEqual(info["pid"], run.pid)
        self.assertEqual(info["kind"], "blender")
        self.assertEqual(info["python"], platform.python_version())
        self.assertEqual(info["numpy"], np.__version__)
        self.assertIsInstance(info["blas"], str)
        self.assertTrue(info["blas"])


class ResultTest(unittest.TestCase):
    """RF-004-01, RF-004-15: el resultado declarado con su huella, también en
    ``result.json``."""

    def test_sum_is_exact_and_declared_with_its_hash(self):
        """RF-004-01: la suma n(n−1)/2 exacta en el resumen y en ``out/sum.npy`` (``int64``),
        declarada con su sha256 y su tamaño."""
        run = _RUNS["noise"]
        job = _JOBS["noise"]
        expected = SUM_N * (SUM_N - 1) // 2
        result = run.of_type("result")[0]
        self.assertEqual(dict(result.summary),
                         {"op": "chunked_sum", "n": SUM_N, "chunks": SUM_CHUNKS,
                          "sum": expected})
        [output] = result.outputs
        path = job.path / "out" / "sum.npy"
        self.assertEqual((output.path, output.role), ("out/sum.npy", "sum"))
        self.assertEqual((output.sha256, output.size),
                         (_support.sha256_file(path), path.stat().st_size))
        value = np.load(path, allow_pickle=False)
        self.assertEqual((value.dtype, int(value)), (np.dtype(np.int64), expected))

    def test_result_json_is_the_result_event(self):
        """RF-004-15: ``result.json`` (UTF-8 sin BOM) guarda el mismo evento ``result``."""
        run = _RUNS["noise"]
        raw = _JOBS["noise"].result_file.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        saved = protocol.JobEvent.from_json(json.loads(raw.decode("utf-8")))
        self.assertEqual(saved, run.of_type("result")[0])
        self.assertEqual(list(_JOBS["noise"].path.glob("*.partial")), [])


class ParentWatchTest(unittest.TestCase):
    """RF-004-13 (paso 3 del arranque): sin padre, el worker termina solo."""

    def test_lost_parent_ends_the_worker(self):
        """RF-004-13: al cerrarse su entrada estándar, un trabajo de 30 s termina enseguida
        con el código 4, sin resultado, y lo deja dicho en ``job.log``."""
        run = _RUNS["parent"]
        self.assertEqual(run.returncode, 4, run.log)
        self.assertLess(run.elapsed_s, PARENT_JOB_S / 3)
        self.assertNotIn("result", run.types())
        self.assertFalse(_JOBS["parent"].result_file.exists())
        self.assertIn("padre", run.log)

    def test_watching_does_not_block_the_standard_input(self):
        """RF-004-13, RF-004-22: vigilar al padre no deja una lectura pendiente en la entrada
        estándar: el cálculo puede consultarla (como la libgfortran del OpenBLAS de numpy
        2.5.3 al importarlo en el motor, que se quedaba colgada) y el worker termina."""
        self.assertNotIn("stdin_hung", _STATE, _STATE.get("stdin_hung"))
        run = _RUNS["stdin"]
        self.assertEqual(run.returncode, 0, run.log)
        self.assertLess(run.elapsed_s, STDIN_TIMEOUT_S)
        self.assertEqual(run.types()[-1], "result")
        self.assertEqual(dict(run.of_type("result")[0].summary), {"answered": True})


class ChannelLostTest(unittest.TestCase):
    """RF-004-13 (spec 004, T47): un canal de eventos sin lector es un padre perdido."""

    def test_closed_channel_is_a_lost_parent(self):
        """RF-004-12, RF-004-13: si el padre muere entre dos miradas de la vigilancia y el
        worker escribe antes un evento (``OSError`` al escribir en la tubería sin lector), el
        worker termina enseguida con el código 4 de «padre perdido» y lo deja dicho en
        ``job.log``, no con el 1 y una traza de «excepción no capturada»."""
        state = _STATE["channel"]
        self.assertIn(b'"start"', state["first"])
        self.assertEqual(state["returncode"], 4, state["log"])
        self.assertLess(state["elapsed_s"], PARENT_JOB_S / 3)
        self.assertIn("el proceso padre ya no está (el canal de eventos no tiene quien lo "
                      "lea): el worker termina con el código 4", state["log"])
        self.assertNotIn("excepción no capturada", state["log"])
        self.assertNotIn("Traceback", state["log"])
        self.assertNotIn("el worker termina con el código 1", state["log"])


class StartupFailureTest(unittest.TestCase):
    """RF-004-15: una comprobación de arranque fallida termina con el código 5 y, si el canal
    ya funciona, con su evento ``error`` (mensaje del §8, sin traza)."""

    def test_unknown_worker(self):
        """Un tipo de trabajo sin módulo en ``workers/``: ``worker_unknown``, salida 5."""
        run = _RUNS["unknown"]
        self.assertEqual(run.returncode, 5, run.log)
        self.assertEqual(run.types(), ["start", "error"])
        error = run.of_type("error")[0]
        self.assertEqual(error.code, "worker_unknown")
        self.assertEqual(error.msg, f"No existe el tipo de trabajo «{UNKNOWN_WORKER}».")
        self.assertEqual(dict(error.values), {"worker": UNKNOWN_WORKER})
        self.assertNotIn("Traceback", run.log)

    def test_missing_request(self):
        """Una carpeta sin ``request.json``: ``request_invalid``, salida 5, sin calcular."""
        run = _RUNS["no_request"]
        self.assertEqual(run.returncode, 5, run.log)
        self.assertEqual(run.types(), ["start", "error"])
        error = run.of_type("error")[0]
        self.assertEqual(error.code, "request_invalid")
        self.assertIn("request.json", error.msg)
        self.assertNotIn("Traceback", run.log)
        self.assertEqual(list((_JOBS["no_request"].path / "out").iterdir()), [])

    def test_bad_arguments(self):
        """Sin ``--job-dir``: salida 5 antes de abrir el canal, con el motivo en
        ``job.log``."""
        run = _RUNS["bad_args"]
        self.assertEqual(run.returncode, 5, run.log)
        self.assertEqual(run.channel, b"")
        self.assertIn("--job-dir", run.log)


class BytecodeTest(unittest.TestCase):
    """Plan 004 §2.1 y §6: los workers no dejan ``__pycache__`` en el paquete (la misma
    comprobación que ``test_no_new_pycache_in_repo`` de la spec 001, RF-001-09)."""

    def test_no_new_pycache_under_package_dir(self):
        """Ningún ``__pycache__`` nuevo bajo el paquete tras los workers lanzados con
        ``-I -B -u``."""
        new = _STATE["pycache_after"] - _STATE["pycache_before"]
        self.assertEqual(sorted(new), [])

    def test_step_zero_holds_without_dash_b(self):
        """Paso 0 (defensa además de ``-B``): lanzado sin ``-B``, el worker importa el
        paquete, numpy y su módulo y no escribe ningún ``__pycache__`` en él."""
        run = _RUNS["copy"]
        self.assertEqual(run.returncode, 0, run.log)
        copy = _STATE["copy"]
        self.assertTrue((copy / "workers" / f"{ECHO_WORKER}.py").is_file())
        self.assertEqual(sorted(_pycache(copy)), [])


class InputBitExactTest(unittest.TestCase):
    """RF-004-01: las entradas llegan al worker tal como las entregó el módulo."""

    def test_float64_utm_and_nan_arrive_bit_exact(self):
        """RF-004-01: un array float64 con coordenadas UTM de 4,4 Mm, NaN con carga útil,
        −0,0, subnormales e infinitos llega al worker y vuelve idéntico bit a bit."""
        run = _RUNS["copy"]
        self.assertEqual(run.returncode, 0, run.log)
        original = _STATE["utm"]
        summary = run.of_type("result")[0].summary
        self.assertEqual(summary["dtype"], "<f8")
        self.assertEqual(summary["shape"], list(original.shape))
        self.assertEqual(summary["sha256"], hashlib.sha256(original.tobytes()).hexdigest())
        echoed = np.load(_JOBS["copy"].path / "out" / "echo.npy", allow_pickle=False)
        self.assertEqual(echoed.dtype, np.dtype("<f8"))
        np.testing.assert_array_equal(echoed.view(np.uint64), original.view(np.uint64))


if __name__ == "__main__":
    unittest.main()
