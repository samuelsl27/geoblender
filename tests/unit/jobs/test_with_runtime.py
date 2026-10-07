# SPDX-License-Identifier: GPL-3.0-or-later
"""Trabajos con el motor de cálculo real (spec 004, T31; HU-004-3; RF-004-22, RF-004-25;
plan 004 §7 y §7.1).

Con el motor de cálculo de pruebas de ``tools/make_runtime.py`` (el numpy del lock con su
OpenBLAS, en ``.deps/runtime/<lock_id>/site`` o en ``GEOBLENDER_TEST_RUNTIME_SITE``; sin él,
las pruebas se omiten con ``[ENTORNO] runtime`` y la orden que lo crea):

- el autodiagnóstico ``matmul`` del menú (2000 × 2000, entorno ``compute``) corre con el
  numpy del lock, cargado desde la carpeta del motor (la nota del arranque en ``job.log``) y
  con una BLAS que no es ``auto``; su registro lleva el ``lock_id`` del motor;
- la misma suma por trozos da el mismo resultado, bit a bit, con el Python de Blender y su
  numpy (``blender``) y con el motor (``compute``);
- el trabajo ``runtime_check`` real (``workers/runtime_check.py``) verifica el motor de
  pruebas contra el lock de esta versión: cada paquete con su versión, numpy desde el motor,
  BLAS optimizada y los s del producto 2000 × 2000 (la cifra que cuenta, < 1 s, la mide la
  T35 en ``tests/rendimiento``).

El lanzador ve el motor de pruebas como su motor listo (``_TestEngine``, con el lock real);
la verificación se lanza como la de ``RuntimeSetup`` (``--path site=…`` y ``site_override``),
pero sin anotar nada en el ``runtime.json`` del motor de pruebas. Los cuatro trabajos se
lanzan a la vez al preparar la clase y cada prueba mira lo que dejó el suyo.
``tools/check.py`` ejecuta este módulo en «unitarias» (numpy de Blender) y en «motor» (el
numpy del motor): los workers son los mismos en los dos.
"""

import dataclasses
import json
import os
import platform
import re
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.support import jobs_fixtures as _support
from tests.support import resources
from tests.support import runtime as runtime_support
from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR

catalog = import_geoblender("jobs.catalog")
protocol = import_geoblender("jobs.protocol")
records = import_geoblender("jobs.records")
runner = import_geoblender("jobs.runner")
runtime = import_geoblender("jobs.runtime")
selftest = import_geoblender("jobs.selftest")
worker_api = import_geoblender("jobs.worker_api")

JOB_TIMEOUT_S = 120.0
DEADLINE_S = 60.0
POLL_S = 0.02
MATMUL_PARAMS = {"op": "matmul", "n": 2000}
"""El autodiagnóstico «producto de matrices con el motor» del menú (``MATMUL_COMPUTE``)."""
SUM_N = 5_000_000
SUM_PARAMS = {"op": "chunked_sum", "n": SUM_N, "chunks": 2}
"""Dos trozos de 2,5 millones de números (3 bloques ``int64`` cada uno): la suma pasa de
2³¹ y de 2³²."""
SUM_EXPECTED = SUM_N * (SUM_N - 1) // 2
MATMUL_N = 2000
UNOPTIMIZED = (runtime.UNOPTIMIZED_BLAS, worker_api.UNKNOWN_BLAS)
SLOW_MATMUL_S = 10.0
"""Cota holgada del producto 2000 × 2000 (con el numpy de Blender tarda 24,9 s; plan §2.1):
solo descarta una BLAS sin optimizar con otro nombre. La cifra de RNF-004-05 la mide T35."""
ENGINE_NOTE = re.compile(r"motor de cálculo: numpy (?P<version>\S+) desde (?P<folder>.+)$")

LABELS = {
    "matmul": "Producto con el motor",
    "sum_blender": "Suma con Blender",
    "sum_compute": "Suma con el motor",
    "check": "Verificación del motor de pruebas",
}
"""El nombre de cada trabajo (su ``label``)."""


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


def _same_path(a: object, b: object) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _inside(path: object, folder: object) -> bool:
    real = os.path.normcase(os.path.realpath(path))
    root = os.path.normcase(os.path.realpath(folder))
    try:
        return os.path.commonpath([real, root]) == root
    except ValueError:  # otra unidad
        return False


@resources.requires(runtime_support.RUNTIME, runtime_support.RUNTIME_HINT)
class EngineJobsTest(unittest.TestCase):
    """Autodiagnóstico, suma y verificación con el motor de cálculo de pruebas."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.site = runtime_support.runtime_site()
        tmp = _support.jobs_tmp()
        base = tmp.__enter__()
        cls.addClassCleanup(tmp.__exit__, None, None, None)

        registry = mock.patch.dict(catalog._REGISTRY, clear=True)
        registry.start()
        cls.addClassCleanup(registry.stop)
        builtin = {info.name: info for info in catalog.BUILTIN_WORKERS}
        # La suma en «blender», en el Python de Blender (proceso aparte), no en el hilo de
        # las pruebas, cuyo numpy en el paso «motor» es el del motor.
        catalog.register_worker(dataclasses.replace(builtin["selftest"], policy="subprocess",
                                                    default_timeout_s=JOB_TIMEOUT_S))
        catalog.register_worker(builtin[runtime.CHECK_WORKER])

        cls.engine = _TestEngine(cls.site)
        cls.lock = cls.engine.lock
        cls.lock_numpy = cls.lock.package(runtime.LOCK_NUMPY).version
        job_runner = runner.JobRunner(jobs_root=base / "jobs", package_dir=EXTENSION_DIR,
                                      blender_python=Path(sys.executable),
                                      runtime=cls.engine, max_subprocess=len(LABELS))
        cls.addClassCleanup(job_runner.shutdown)

        def request(name: str, params: dict, environment: str | None = None):
            return protocol.new_request("selftest", label=LABELS[name], owner="jobs",
                                        params=params, environment=environment)

        env = runtime.ComputeEnvironment(base / "usuario", cls.lock)
        cls.handles = {
            "matmul": job_runner.submit(request("matmul", MATMUL_PARAMS)),
            "sum_blender": job_runner.submit(request("sum_blender", SUM_PARAMS, "blender")),
            "sum_compute": job_runner.submit(request("sum_compute", SUM_PARAMS, "compute")),
            "check": job_runner.submit(env.verify_request(label=LABELS["check"]),
                                       paths={runtime.PATH_SITE: cls.site},
                                       site_override=cls.site),
        }
        deadline = time.monotonic() + DEADLINE_S
        while not all(handle.result() is not None for handle in cls.handles.values()):
            if time.monotonic() > deadline:
                pending = [name for name, handle in cls.handles.items()
                           if handle.result() is None]
                raise AssertionError(f"no terminaron en {DEADLINE_S} s: {pending}")
            job_runner.poll()
            time.sleep(POLL_S)
        job_runner.poll()
        cls.results = {name: handle.result() for name, handle in cls.handles.items()}
        cls.records = {name: records.read_record(handle.job_dir)
                       for name, handle in cls.handles.items()}

    def succeeded(self, name: str):
        """El resultado del trabajo ``name``, que tiene que haber terminado bien (si no, el
        motivo y su ``job.log``)."""
        result = self.results[name]
        log = self.handles[name].job_dir.log_file
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        self.assertEqual(result.state, "succeeded",
                         f"{name}: {result.error_code}: {result.error_text}\n{text}")
        return result

    def engine_note(self, name: str) -> tuple[str, str]:
        """La versión y la carpeta del numpy que el arranque del worker ``compute`` dejó en
        su ``job.log`` («motor de cálculo: numpy X desde <carpeta>»)."""
        log = self.handles[name].job_dir.log_file.read_text(encoding="utf-8")
        found = [match for line in log.splitlines() if (match := ENGINE_NOTE.search(line))]
        self.assertEqual(len(found), 1, log)
        return found[0]["version"], found[0]["folder"]

    def check_compute_interpreter(self, name: str, *, blas: str | None = None) -> None:
        """El trabajo ``name`` corrió en ``compute`` con el numpy del lock cargado desde la
        carpeta del motor, su BLAS optimizada y el ``lock_id`` del motor en su registro."""
        interp = self.records[name].interpreter
        self.assertEqual((interp.kind, interp.lock_id, interp.numpy),
                         ("compute", self.lock.lock_id, self.lock_numpy))
        self.assertEqual(interp.python, platform.python_version())
        self.assertNotIn(interp.blas, UNOPTIMIZED)
        if blas is not None:
            self.assertEqual(interp.blas, blas)
        version, folder = self.engine_note(name)
        self.assertEqual(version, self.lock_numpy)
        self.assertTrue(_inside(folder, self.site), f"{folder} no está en {self.site}")
        self.assertTrue(_same_path(folder, self.site / "numpy"), folder)

    def test_matmul_runs_with_the_engine_numpy(self) -> None:
        """RF-004-25: el autodiagnóstico ``matmul`` 2000 × 2000 del menú va al entorno
        ``compute`` y corre con el numpy del lock (no con el de Blender), cargado desde la
        carpeta del motor de pruebas y con una BLAS que no es ``auto``; su registro lleva el
        intérprete ``compute`` con el ``lock_id`` del motor y el producto da sus s."""
        result = self.succeeded("matmul")
        summary = dict(result.summary)
        self.assertEqual((summary["op"], summary["n"], summary["repeats"]),
                         ("matmul", MATMUL_N, selftest.DEFAULT_REPEATS))
        self.assertEqual(summary["numpy"], self.lock_numpy)
        self.assertNotIn(summary["blas"], UNOPTIMIZED)
        self.assertIsInstance(summary["best_s"], float)
        self.assertGreater(summary["best_s"], 0.0)
        self.assertLess(summary["best_s"], SLOW_MATMUL_S)
        self.assertEqual(self.records["matmul"].executor, runner.EXECUTOR_SUBPROCESS)
        self.check_compute_interpreter("matmul", blas=summary["blas"])

    def test_same_sum_in_blender_and_compute(self) -> None:
        """RF-004-25: la misma suma por trozos (0 + … + 4 999 999) da el mismo resultado, el
        exacto n(n−1)/2, y el mismo ``out/sum.npy`` (misma huella) con el Python de Blender y
        su numpy (``blender``) y con el numpy del lock cargado desde el motor
        (``compute``)."""
        import numpy as np

        sums = {}
        for name in ("sum_blender", "sum_compute"):
            with self.subTest(name):
                result = self.succeeded(name)
                self.assertEqual(result.summary["sum"], SUM_EXPECTED)
                (output,) = result.outputs
                self.assertEqual((output.path, output.role),
                                 (f"{protocol.OUTPUTS_DIR}/{selftest.SUM_OUTPUT}",
                                  selftest.SUM_ROLE))
                path = result.job_dir.path / output.path
                self.assertEqual(_support.sha256_file(path), output.sha256)
                value = np.load(path, allow_pickle=False)
                self.assertEqual((value.dtype, value.shape, int(value)),
                                 (np.dtype(np.int64), (), SUM_EXPECTED))
                sums[name] = (result.summary["sum"], output.sha256, output.size)
        self.assertEqual(sums.get("sum_blender"), sums.get("sum_compute"))
        blender = self.records["sum_blender"].interpreter
        self.assertEqual((blender.kind, blender.lock_id, blender.numpy),
                         ("blender", None, _support.blender_numpy_version()))
        self.check_compute_interpreter("sum_compute")

    def test_runtime_check_on_the_test_engine(self) -> None:
        """RF-004-22: el trabajo ``runtime_check`` real, en un proceso aparte con el motor de
        pruebas como única carpeta de paquetes, lo da por bueno contra el lock de esta
        versión: cada paquete con la versión del lock, numpy cargado desde el motor y no
        desde Blender, BLAS que no es ``auto``, los s del producto 2000 × 2000 y la ruta más
        larga; su resultado y su registro llevan el ``lock_id``."""
        result = self.succeeded("check")
        check = dict(result.summary)
        self.assertEqual((check["ok"], check["problems"]), (True, []))
        self.assertEqual(check["lock_id"], self.lock.lock_id)
        self.assertEqual(check["python"], platform.python_version())
        self.assertEqual(check["packages"],
                         [{"name": package.name, "locked": package.version,
                           "installed": package.version} for package in self.lock.packages])
        self.assertEqual((check["numpy"], check["numpy_in_site"]), (self.lock_numpy, True))
        self.assertNotIn(check["blas"], UNOPTIMIZED)
        self.assertEqual((check["matmul_n"], check["matmul_repeats"]),
                         (runtime.MATMUL_N, runtime.MATMUL_REPEATS))
        self.assertIsInstance(check["matmul_s"], float)
        self.assertGreater(check["matmul_s"], 0.0)
        self.assertLess(check["matmul_s"], SLOW_MATMUL_S)
        self.assertEqual(check["max_path_length"],
                         len(str(self.site)) + 1 + check["longest_relative"])
        self.assertGreater(check["longest_relative"], 0)
        self.assertEqual(runtime.check_errors(check), [])
        # Lo mismo en result.json, que es lo que lee la cadena del lanzador.
        stored = json.loads(result.job_dir.result_file.read_text(encoding="utf-8"))
        self.assertEqual(stored["summary"], check)
        self.check_compute_interpreter("check", blas=check["blas"])


if __name__ == "__main__":
    unittest.main()
