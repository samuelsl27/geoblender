# SPDX-License-Identifier: GPL-3.0-or-later
"""Intérprete de los workers: el de Blender, el del motor de cálculo y el externo (spec 004,
T25; HU-004-5; RF-004-25, RF-004-26; plan 004 §5.3.1, §5.3.3, §5.4.3 y §7.1).

- ``interpreter.resolve_interpreter`` elige el intérprete de un trabajo según su entorno:
  ``blender``, el Python de Blender con ``-I -B -u``; ``compute``, el intérprete externo si
  hay uno configurado (``-I -B -u``, con sus propios paquetes) o, si no, el Python de Blender
  con ``-I -S -B -u`` y el motor de cálculo (``--site`` y ``--expect-numpy`` con la versión
  del lock). Sin motor listo, ``runtime_missing``. ``interpreter.build_command`` arma la
  orden del arranque (plan §5.3.3).
- ``interpreter.probe_external``: el propio Python de Blender (3.13 con numpy) sirve como
  «externo»; un intérprete falso que dice ser 3.12, otro sin numpy, uno que no responde como
  un Python, uno que falla y uno que no existe se rechazan diciendo por qué.
- Arranque ``compute`` (``workers/_bootstrap.py``, pasos 4 y 6): con un **motor falso** (una
  carpeta con un ``numpy/__init__.py`` de versión inventada) el trabajo para con
  ``runtime_package_mismatch`` sin calcular. Que lo encuentre prueba ``-I -S``: sin ``-S``,
  el ``site-packages`` de Blender iría antes en ``sys.path`` y se cargaría su numpy. Con un
  motor que deja colarse el numpy de Blender (un ``.pth`` hacia su ``site-packages``),
  ``runtime_numpy_wrong``. ``--kind compute`` sin ``--site``, o ``--expect-numpy`` en otro
  intérprete, son argumentos que no valen (salida 5).
- Con el intérprete externo configurado (``reconfigure(external_python=…)``), un trabajo
  ``compute`` corre con él y su registro dice ``kind = external``; si el externo no existe,
  ``interpreter_not_found``, sin pasar al motor.

Para no esperar en serie, todos los trabajos y sondeos del módulo se lanzan al empezar
(``setUpModule``) y cada prueba mira lo que dejó el suyo.
"""

import dataclasses
import json
import os
import platform
import sys
import sysconfig
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.support import jobs_fixtures as _support
from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR

catalog = import_geoblender("jobs.catalog")
interpreter = import_geoblender("jobs.interpreter")
messages = import_geoblender("jobs.messages")
records = import_geoblender("jobs.records")
protocol = import_geoblender("jobs.protocol")
runner = import_geoblender("jobs.runner")
runtime = import_geoblender("jobs.runtime")

FAKE_NUMPY = "0.0.1+gbtest"
LOCK_NUMPY = "2.5.3"
JOB_TIMEOUT_S = 120.0
DEADLINE_S = 60.0
POLL_S = 0.02
SUM_PARAMS = {"n": 1000, "chunks": 2}
# El site-packages del Python de Blender (también en el paso «motor» de tools/check.py,
# que ejecuta estas pruebas con el numpy del motor: spec 004, T30).
BLENDER_SITE = Path(sysconfig.get_path("purelib"))
BLENDER_NUMPY_DIR = BLENDER_SITE / "numpy"

LABELS = {
    "fake_engine": "Motor falso",
    "leaky_engine": "Motor con fuga",
    "no_engine": "Sin motor",
    "not_ready": "Motor sin instalar",
    "cleared": "Externo quitado",
    "external": "Con el intérprete externo",
    "external_missing": "Externo borrado",
}
"""El nombre de cada trabajo (su ``label``)."""

_HANDLES: dict[str, object] = {}
_RUNNERS: dict[str, object] = {}
_PROBES: dict[str, object] = {}
_RUNS: dict[str, _support.WorkerRun] = {}
_STATE: dict[str, object] = {}


class _Engine:
    """Un motor de cálculo de prueba con lo que pide el lanzador
    (``interpreter.ComputeRuntime``): el lock real, su ``lock_id``, su estado y su carpeta
    ``site``."""

    def __init__(self, site: Path, status: str = "ready") -> None:
        self.lock = runtime.read_lock()
        self.lock_id = self.lock.lock_id
        self._site = Path(site)
        self._status = status

    def status(self) -> str:
        return self._status

    def site_dir(self) -> Path:
        return self._site


def _request(name: str):
    return protocol.new_request("selftest", label=LABELS[name], owner="jobs",
                                params=SUM_PARAMS, environment="compute")


def _submit(name: str, job_runner) -> None:
    _RUNNERS[name] = job_runner
    try:
        _HANDLES[name] = job_runner.submit(_request(name))
    except Exception as exc:  # noqa: BLE001 - se comprueba en la prueba del caso
        _STATE.setdefault("submit_errors", {})[name] = exc


def _probe_output(python: str, numpy: str | None) -> str:
    """Lo que escribe un intérprete al que se sondea: una línea con la marca del sondeo y el
    JSON de lo que encontró (plan §5.3.1)."""
    blas = None if numpy is None else "scipy-openblas"
    data = {"python": python, "numpy": numpy, "blas": blas}
    return f"Aviso de un sitecustomize\n{interpreter.PROBE_MARK}{json.dumps(data)}\n"


def setUpModule() -> None:
    tmp = _support.jobs_tmp()
    base = tmp.__enter__()
    unittest.addModuleCleanup(tmp.__exit__, None, None, None)
    root = base / "jobs"
    python = Path(sys.executable)

    registry = mock.patch.dict(catalog._REGISTRY, clear=True)
    registry.start()
    unittest.addModuleCleanup(registry.stop)
    builtin = next(info for info in catalog.BUILTIN_WORKERS if info.name == "selftest")
    catalog.register_worker(dataclasses.replace(builtin, policy="subprocess",
                                                default_timeout_s=JOB_TIMEOUT_S))

    fake_site = base / "motor_falso" / "site"
    (fake_site / "numpy").mkdir(parents=True)
    (fake_site / "numpy" / "__init__.py").write_bytes(
        f'__version__ = "{FAKE_NUMPY}"\n'.encode("ascii")
    )
    leaky_site = base / "motor_con_fuga" / "site"
    leaky_site.mkdir(parents=True)
    (leaky_site / "fuga.pth").write_bytes(f"{BLENDER_SITE}\n".encode("utf-8"))
    _STATE["fake_engine"] = _Engine(fake_site)

    common = {"jobs_root": root, "package_dir": EXTENSION_DIR, "blender_python": python}
    _submit("fake_engine", runner.JobRunner(**common, runtime=_STATE["fake_engine"]))
    _submit("leaky_engine", runner.JobRunner(**common, runtime=_Engine(leaky_site)))
    _submit("no_engine", runner.JobRunner(**common))
    _submit("not_ready",
            runner.JobRunner(**common, runtime=_Engine(fake_site, status="missing")))
    external = runner.JobRunner(**common)
    external.reconfigure(external_python=python)
    _STATE["external_python"] = external.external_python
    _submit("external", external)
    cleared = runner.JobRunner(**common, external_python=python)
    cleared.reconfigure(external_python=None)
    _STATE["cleared_python"] = cleared.external_python
    _submit("cleared", cleared)
    _STATE["missing_python"] = base / "sin_python" / "python.exe"
    _submit("external_missing",
            runner.JobRunner(**common, runtime=_STATE["fake_engine"],
                             external_python=_STATE["missing_python"]))

    # El arranque con argumentos de «compute» que no valen.
    bad = {
        "no_site": ("--kind", "compute", "--expect-numpy", LOCK_NUMPY),
        "expect_in_blender": ("--kind", "blender", "--expect-numpy", LOCK_NUMPY),
    }
    launched = {}
    for name, extra in bad.items():
        job = _support.prepare_job(root)
        worker = _support.LaunchedWorker(
            job.path, args=("--package-dir", str(EXTENSION_DIR), "--job-dir", str(job.path),
                            *extra),
        )
        unittest.addModuleCleanup(worker.close)
        launched[name] = worker

    # Los sondeos, mientras los trabajos corren.
    fakes = base / "falsos"
    _STATE["fakes"] = {
        "py312": _support.make_fake_interpreter(
            fakes, stdout=_probe_output("3.12.7", "2.1.3"), name="python312"),
        "no_numpy": _support.make_fake_interpreter(
            fakes, stdout=_probe_output("3.13.5", None), name="sin_numpy"),
        "not_python": _support.make_fake_interpreter(
            fakes, stdout="Hola, no soy Python\n", name="no_python"),
        "failing": _support.make_fake_interpreter(
            fakes, stdout="", stderr="Error de prueba\n", exit_code=3, name="falla"),
        "missing": fakes / "no_existe" / "python.exe",
    }
    _PROBES["blender"] = interpreter.probe_external(python)
    for name, exe in _STATE["fakes"].items():
        _PROBES[name] = interpreter.probe_external(exe)

    for name, worker in launched.items():
        _RUNS[name] = worker.finish()
    deadline = time.monotonic() + DEADLINE_S
    while not all(handle.result() is not None for handle in _HANDLES.values()):
        if time.monotonic() > deadline:
            pending = [name for name, handle in _HANDLES.items() if handle.result() is None]
            raise AssertionError(f"no terminaron a tiempo: {pending}")
        for job_runner in {id(r): r for r in _RUNNERS.values()}.values():
            job_runner.poll()
        time.sleep(POLL_S)
    for job_runner in {id(r): r for r in _RUNNERS.values()}.values():
        job_runner.poll()


def _lines(handle) -> list[dict]:
    """Las líneas de ``events.jsonl`` del trabajo, en orden (eventos y notas)."""
    path = handle.job_dir.events_file
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _channel_types(handle) -> list[str]:
    """Los tipos de los eventos que mandó el worker (sin las notas del lanzador)."""
    return [line["t"] for line in _lines(handle) if "t" in line]


def _notes(handle, kind: str) -> list[dict]:
    return [line for line in _lines(handle) if line.get(records.NOTE_KEY) == kind]


PYTHON = Path(sys.executable)
EXTERNAL = Path(r"C:\entornos\gempy\Scripts\python.exe")
SITE = Path(r"C:\datos\runtime\b4958a26c4c9\site")
PARTIAL = Path(r"C:\datos\runtime\b4958a26c4c9.partial\site")
PACKAGE = Path(r"C:\ext\geoblender")
JOB = Path(r"C:\cache\jobs\20261007_120000_abcdef")
COMMON_ARGS = [str(PACKAGE / "workers" / "_bootstrap.py"), "--package-dir", str(PACKAGE),
               "--job-dir", str(JOB)]


def _resolve(environment: str, *, runtime=None, external=None, override=None):
    return interpreter.resolve_interpreter(environment, blender_python=PYTHON,
                                           runtime=runtime, external_python=external,
                                           site_override=override)


def _fields(interp) -> tuple:
    return (interp.kind, interp.python, interp.flags, interp.site, interp.expect_numpy,
            interp.lock_id)


def _command(interp) -> list[str]:
    return interpreter.build_command(interp, package_dir=PACKAGE, job_dir=JOB)


class ComputeEngineTest(unittest.TestCase):
    """El motor de cálculo: el intérprete y la orden del entorno ``compute``
    (``resolve_interpreter`` y ``build_command``, plan §5.3.1 y §5.3.3), la comprobación de
    numpy del arranque (plan §5.4.3, pasos 4 y 6; salida 5) y el trabajo sin motor."""

    def test_compute_needs_the_engine(self):
        """RF-004-25: con el motor listo, ``compute`` es el Python de Blender con
        ``-I -S -B -u``, ``--site`` y ``--expect-numpy`` del lock (y ``blender``, con
        ``-I -B -u``); con el motor falso, el trabajo queda «Fallido» con
        ``runtime_package_mismatch`` y salida 5 sin calcular, y con el numpy de Blender
        colado, ``runtime_numpy_wrong``; sin motor listo, ``runtime_missing`` sin
        proceso."""
        self.assertEqual(_STATE.get("submit_errors", {}), {})
        with self.subTest("intérprete y orden"):
            self.check_resolution_and_command()
        with self.subTest("motor falso"):
            self.check_fake_engine()
        with self.subTest("numpy de Blender colado"):
            self.check_leaky_engine()
        with self.subTest("argumentos del arranque"):
            self.check_bootstrap_arguments()
        with self.subTest("sin motor"):
            self.check_missing_engine()

    def check_resolution_and_command(self):
        """``blender`` usa el Python de Blender aunque haya externo (con ``--site`` si se
        da); ``compute`` con el motor listo, sus banderas, su carpeta, la versión de numpy
        de su lock y su ``lock_id``; la verificación de un motor recién instalado
        (``site_override``) usa esa carpeta aunque el motor no esté listo y aunque haya
        externo. Sin motor listo ni externo, ``runtime_missing``; un entorno desconocido,
        ``ValueError``."""
        ready = _Engine(SITE)
        blender = _resolve("blender", runtime=ready, external=EXTERNAL)
        self.assertEqual(_fields(blender),
                         ("blender", PYTHON, ("-I", "-B", "-u"), None, None, None))
        blender_site = _resolve("blender", override=PARTIAL)
        self.assertEqual(_fields(blender_site),
                         ("blender", PYTHON, ("-I", "-B", "-u"), PARTIAL, None, None))
        compute = _resolve("compute", runtime=ready)
        self.assertEqual(_fields(compute), ("compute", PYTHON, ("-I", "-S", "-B", "-u"),
                                            SITE, LOCK_NUMPY, ready.lock_id))
        verify = _resolve("compute", runtime=_Engine(SITE, status="missing"),
                          external=EXTERNAL, override=PARTIAL)
        self.assertEqual(_fields(verify), ("compute", PYTHON, ("-I", "-S", "-B", "-u"),
                                           PARTIAL, LOCK_NUMPY, ready.lock_id))
        for name, engine, override in (("sin motor", None, None),
                                       ("sin instalar", _Engine(SITE, "missing"), None),
                                       ("verificar sin lock", None, PARTIAL)):
            with self.subTest(name), self.assertRaises(messages.JobError) as caught:
                _resolve("compute", runtime=engine, override=override)
            self.assertEqual(caught.exception.code, "runtime_missing")
            self.assertEqual(caught.exception.text, messages.render("runtime_missing"))
        with self.assertRaises(ValueError):
            _resolve("gpu", runtime=ready)

        self.assertEqual(_command(compute),
                         [str(PYTHON), "-I", "-S", "-B", "-u", *COMMON_ARGS, "--kind",
                          "compute", "--site", str(SITE), "--expect-numpy", LOCK_NUMPY])
        self.assertEqual(_command(blender),
                         [str(PYTHON), "-I", "-B", "-u", *COMMON_ARGS, "--kind", "blender"])
        self.assertEqual(_command(blender_site),
                         [str(PYTHON), "-I", "-B", "-u", *COMMON_ARGS, "--kind", "blender",
                          "--site", str(PARTIAL)])

    def check_fake_engine(self):
        """Motor falso (numpy de versión inventada): «Fallido» con
        ``runtime_package_mismatch``, salida 5, ni avance ni resultado; en su registro, el
        intérprete ``compute`` con el ``lock_id``. Que encuentre el numpy falso prueba
        ``-I -S``: sin ``-S``, el de Blender iría antes en ``sys.path``."""
        engine = _STATE["fake_engine"]
        handle = _HANDLES["fake_engine"]
        result = handle.result()
        self.assertEqual((result.state, result.error_code),
                         ("failed", "runtime_package_mismatch"))
        self.assertEqual(
            result.error_text,
            f"El paquete numpy del motor tiene la versión {FAKE_NUMPY} y el lock exige "
            f"{LOCK_NUMPY}: repare el motor.",
        )
        record = records.read_record(handle.job_dir)
        self.assertEqual(record.exit_code, 5)
        self.assertEqual(dict(record.error.values),
                         {"package": "numpy", "actual": FAKE_NUMPY, "locked": LOCK_NUMPY})
        self.assertEqual((record.interpreter.kind, record.interpreter.lock_id),
                         ("compute", engine.lock_id))
        self.assertEqual(_channel_types(handle), ["error"])
        self.assertEqual(list(handle.job_dir.outputs_dir.iterdir()), [])
        self.assertFalse(handle.job_dir.result_file.exists())
        self.assertEqual([note["interpreter"] for note in _notes(handle, "launched")],
                         ["compute"])

    def check_leaky_engine(self):
        """Un ``.pth`` del motor hacia el ``site-packages`` de Blender: el numpy cargado no
        es el del motor, ``runtime_numpy_wrong`` con su carpeta, salida 5, sin calcular."""
        handle = _HANDLES["leaky_engine"]
        leaky = handle.result()
        self.assertEqual((leaky.state, leaky.error_code), ("failed", "runtime_numpy_wrong"))
        self.assertEqual(records.read_record(handle.job_dir).exit_code, 5)
        # La carpeta, en el JobResult (state.json no guarda rutas absolutas).
        self.assertEqual(
            os.path.normcase(leaky.error_text),
            os.path.normcase(messages.render(
                "runtime_numpy_wrong", path=os.path.realpath(BLENDER_NUMPY_DIR))),
        )
        self.assertEqual(_channel_types(handle), ["error"])

    def check_bootstrap_arguments(self):
        """``--kind compute`` sin ``--site`` y ``--expect-numpy`` con otro intérprete:
        salida 5 antes de abrir el canal, con el motivo en ``job.log``."""
        for name, option in (("no_site", "--site"), ("expect_in_blender", "--expect-numpy")):
            with self.subTest(name):
                run = _RUNS[name]
                self.assertEqual(run.returncode, 5, run.log)
                self.assertEqual(run.channel, b"")
                self.assertIn(option, run.log)

    def check_missing_engine(self):
        """Sin motor, con el motor sin instalar o tras quitar el intérprete externo:
        «Fallido» con ``runtime_missing``, sin proceso ni intérprete."""
        self.assertIsNone(_STATE["cleared_python"])
        for name in ("no_engine", "not_ready", "cleared"):
            with self.subTest(name):
                handle = _HANDLES[name]
                result = handle.result()
                self.assertEqual((result.state, result.error_code),
                                 ("failed", "runtime_missing"))
                self.assertEqual(result.error_text, messages.render("runtime_missing"))
                self.assertIsNone(handle.pid)
                record = records.read_record(handle.job_dir)
                self.assertEqual((record.pid, record.exit_code, record.interpreter),
                                 (None, None, None))
                self.assertEqual(_notes(handle, "launched"), [])


class ExternalInterpreterTest(unittest.TestCase):
    """El intérprete externo (HU-004-5): cuándo se usa, su sondeo (``probe_external``) y un
    trabajo ``compute`` con él."""

    def test_external_interpreter(self):
        """RF-004-26: con un intérprete externo, ``compute`` lo usa (``-I -B -u``, sin
        ``--site``), también sin motor; el Python de Blender (3.13 con numpy) se acepta y
        los falsos se rechazan con su motivo; un trabajo ``compute`` termina bien con él y
        consta ``kind = external``; si ya no existe, ``interpreter_not_found`` sin pasar al
        motor."""
        self.assertEqual(_STATE.get("submit_errors", {}), {})
        with self.subTest("intérprete y orden"):
            self.check_resolution_and_command()
        with self.subTest("sondeo"):
            self.check_probes()
        with self.subTest("trabajo con el externo"):
            self.check_external_job()

    def check_resolution_and_command(self):
        """``compute`` con externo: el externo con ``-I -B -u`` y sin ``--site`` ni
        ``lock_id``, haya motor o no."""
        expected = ("external", EXTERNAL, ("-I", "-B", "-u"), None, None, None)
        for name, engine in (("con motor", _Engine(SITE)), ("sin motor", None)):
            with self.subTest(name):
                external = _resolve("compute", runtime=engine, external=EXTERNAL)
                self.assertEqual(_fields(external), expected)
                self.assertEqual(_command(external),
                                 [str(EXTERNAL), "-I", "-B", "-u", *COMMON_ARGS, "--kind",
                                  "external"])

    def check_probes(self):
        """El Python de Blender se acepta con sus versiones; un 3.12, uno sin numpy, uno
        que no responde como Python, uno que termina con error y uno que no existe se
        rechazan, cada uno con su motivo y el mensaje ``external_python_invalid``."""
        probe = _PROBES["blender"]
        self.assertTrue(probe.ok, probe.reason)
        self.assertIsNone(probe.reason)
        self.assertIsNone(probe.error())
        self.assertEqual(probe.exe, PYTHON)
        self.assertEqual((probe.python, probe.numpy),
                         (platform.python_version(), _support.blender_numpy_version()))
        self.assertTrue(probe.blas)

        fakes = _STATE["fakes"]
        expected = {
            "py312": "3.12.7",
            "no_numpy": "numpy",
            "not_python": "Python",
            "failing": "código 3",
            "missing": "no existe",
        }
        reasons = set()
        for name, part in expected.items():
            with self.subTest(name):
                probe = _PROBES[name]
                self.assertFalse(probe.ok)
                self.assertIn(part, probe.reason)
                reasons.add(probe.reason)
                error = probe.error()
                self.assertEqual(error.code, "external_python_invalid")
                self.assertEqual(dict(error.values),
                                 {"path": str(fakes[name]), "reason": probe.reason})
                self.assertEqual(
                    error.text,
                    f"El intérprete externo {fakes[name]} no sirve: {probe.reason}. "
                    "Hace falta Python 3.13 con numpy.",
                )
        self.assertEqual(len(reasons), len(expected))
        self.assertIn("Error de prueba", _PROBES["failing"].reason)
        self.assertEqual((_PROBES["py312"].python, _PROBES["no_numpy"].numpy),
                         ("3.12.7", None))

    def check_external_job(self):
        """El trabajo ``compute`` con el Python de Blender como externo termina bien y su
        registro dice ``kind = external`` con sus versiones; con un externo que no existe,
        ``interpreter_not_found`` con su ruta, sin proceso y sin pasar al motor."""
        self.assertEqual(_STATE["external_python"], PYTHON)
        handle = _HANDLES["external"]
        result = handle.result()
        self.assertEqual(result.state, "succeeded", result.error_text)
        self.assertEqual(result.summary["sum"], SUM_PARAMS["n"] * (SUM_PARAMS["n"] - 1) // 2)
        record = records.read_record(handle.job_dir)
        self.assertEqual(
            (record.interpreter.kind, record.interpreter.python, record.interpreter.numpy,
             record.interpreter.lock_id),
            ("external", platform.python_version(), _support.blender_numpy_version(), None),
        )
        self.assertEqual([note["interpreter"] for note in _notes(handle, "launched")],
                         ["external"])
        self.assertIn("intérprete external", handle.job_dir.log_file.read_text("utf-8"))

        missing = _HANDLES["external_missing"]
        gone = missing.result()
        self.assertEqual((gone.state, gone.error_code), ("failed", "interpreter_not_found"))
        self.assertIn(str(_STATE["missing_python"]), gone.error_text)
        self.assertIsNone(missing.pid)


if __name__ == "__main__":
    unittest.main()
