# SPDX-License-Identifier: GPL-3.0-or-later
"""Lanzador de los trabajos en proceso aparte (spec 004, T09; RF-004-01, RF-004-05,
RF-004-15; plan 004 §5.3.1, §5.3.3, §5.3.4 y §5.4.2).

``JobRunner`` prepara la carpeta del trabajo (``prepare``: carpeta, ``request.json``
validado y ``state.json`` «En cola»), lanza el worker con el Python de Blender
(``-I -B -u``) sin esperarlo (``submit``) y lo sigue sin bloquear (``poll``): un hilo lector
*daemon* por proceso decodifica el canal y añade a ``events.jsonl`` cada evento y, como nota,
cada línea que no lo es; al terminar, el lanzador comprueba cada resultado declarado (que
existe dentro de ``out/`` y casa con su huella) y deja ``state.json`` con el estado final.

Para no esperar en serie, todos los trabajos del módulo se lanzan a la vez al empezar
(``setUpModule``) y se sondean hasta que acaban; cada prueba mira lo que dejó el suyo:

- ``sum``: la suma por trozos real del autodiagnóstico (n = 1 000 000 en 4 trozos de
  0,05 s).
- ``deleted`` y ``altered``: la misma suma con otro lanzador, que no se sondea hasta que su
  worker ha terminado y su resultado se ha borrado o alterado (antes de finalizar).
- ``echo``: una copia del paquete con un worker de prueba que devuelve su entrada tal cual.
- ``noise`` y ``phantom``: un intérprete falso (``.cmd``) que escribe en el canal eventos
  válidos mezclados con líneas que no lo son, o un resultado que no existe.

Los tipos de trabajo se registran aquí con la política ``subprocess``: estas pruebas son
las del proceso aparte, aunque la política mande al hilo una suma corta.
"""

import dataclasses
import hashlib
import json
import platform
import shutil
import statistics
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from tests.support import jobs_fixtures as _support
from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR

catalog = import_geoblender("jobs.catalog")
messages = import_geoblender("jobs.messages")
paths = import_geoblender("jobs.paths")
protocol = import_geoblender("jobs.protocol")
records = import_geoblender("jobs.records")
runner = import_geoblender("jobs.runner")

SUM_N = 1_000_000
SUM_PARAMS = {"n": SUM_N, "chunks": 4, "sleep_s": 0.05}
JOB_TIMEOUT_S = 120.0
SUBMIT_MAX_S = 0.2
FINISH_DEADLINE_S = 60.0
POLL_S = 0.02
LABEL = "Suma de las pruebas del lanzador"
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

# Lo que no es un evento y escribe el intérprete falso «noise» en su canal, en su sitio.
NOISE_LINES = (
    "Setting Backend To: AvailableBackends.numpy",
    '{"v": 2, "t": "progress", "ts": 1.0, "frac": 0.7}',
    '{"t": "progress", "ts": 1.0, "frac": 0.8}',
)
FAKE_INFO = {"pid": 4120, "kind": "blender", "python": "3.13.13", "numpy": "2.3.4",
             "blas": "auto"}
PHANTOM_OUTPUT = "out/fantasma.npy"

_HANDLES: dict[str, object] = {}
_UPDATES: dict[str, list] = {}
_FINISHED: dict[str, list] = {}
_STATE: dict[str, object] = {}


def _utm_array() -> np.ndarray:
    """float64 con coordenadas UTM sintéticas de 4,4 Mm, un NaN con carga útil, −0,0, un
    subnormal e infinitos."""
    data = np.array(
        [[712_345.678_901, 4_398_765.432_109, 512.25],
         [np.inf, -np.inf, 5e-324],
         [-0.0, 0.0, 0.0]],
        dtype=np.float64,
    )
    data.view(np.uint64)[2, 2] = 0x7FF8_0000_DEAD_BEEF  # NaN silencioso con carga útil
    return data


def _pycache(package: Path) -> set[str]:
    """Las rutas (relativas) de ``package`` que están dentro de un ``__pycache__``."""
    return {
        "/".join(path.relative_to(package).parts)
        for path in package.rglob("*")
        if "__pycache__" in path.relative_to(package).parts
    }


def _fake_stdout(*items: object) -> str:
    """El canal de un intérprete falso: cada evento en su línea del protocolo y cada texto
    tal cual."""
    lines = []
    for item in items:
        if isinstance(item, str):
            lines.append(item + "\n")
        else:
            lines.append(protocol.encode_event(item).decode("utf-8"))
    return "".join(lines)


def _request(worker: str = "selftest", **options):
    options.setdefault("label", LABEL)
    options.setdefault("owner", "jobs")
    return protocol.new_request(worker, **options)


def _on_finish(result) -> None:
    _FINISHED.setdefault(result.job_uid, []).append(result)


def _submit(name: str, job_runner, job) -> None:
    """Lanza ``job`` y apunta cuánto tardó ``submit`` y el estado justo después."""
    started = time.perf_counter()
    handle = job_runner.submit(job, on_finish=_on_finish)
    elapsed = time.perf_counter() - started
    _STATE.setdefault("submit_s", {})[name] = elapsed
    _STATE.setdefault("state_after_submit", {})[name] = handle.state
    _HANDLES[name] = handle


def _poll(runners) -> None:
    for job_runner in runners:
        for update in job_runner.poll():
            _UPDATES.setdefault(update.job_uid, []).append(update)


def setUpModule() -> None:
    tmp = _support.jobs_tmp()
    base = tmp.__enter__()
    unittest.addModuleCleanup(tmp.__exit__, None, None, None)
    root = base / "jobs"
    _STATE["root"] = root
    _STATE["project"] = _support.make_fake_project(base)

    registry = mock.patch.dict(catalog._REGISTRY, clear=True)
    registry.start()
    unittest.addModuleCleanup(registry.stop)
    builtin = next(info for info in catalog.BUILTIN_WORKERS if info.name == "selftest")
    selftest_info = dataclasses.replace(builtin, policy="subprocess",
                                        default_timeout_s=JOB_TIMEOUT_S)
    catalog.register_worker(selftest_info)
    catalog.register_worker(catalog.WorkerInfo(ECHO_WORKER, "Echo test worker",
                                               policy="subprocess"))
    _STATE["selftest_info"] = selftest_info

    copy = base / "pkg"
    shutil.copytree(
        EXTENSION_DIR, copy,
        ignore=shutil.ignore_patterns("__pycache__", "*.py[cod]", "bl", "resources",
                                      "thirdparty", "wheels"),
    )
    (copy / "workers" / f"{ECHO_WORKER}.py").write_bytes(ECHO_SOURCE.encode("utf-8"))
    _STATE["utm"] = _utm_array()
    _STATE["pycache_before"] = _pycache(EXTENSION_DIR)

    noise = _support.make_fake_interpreter(
        base / "fake_noise",
        stdout=_fake_stdout(
            protocol.JobEvent.start(FAKE_INFO, ts=1.0),
            protocol.JobEvent.progress(0.5, "Mitad del trabajo ñ", ts=2.0),
            *NOISE_LINES,
            protocol.JobEvent.progress(1.0, "Fin", ts=3.0),
            protocol.JobEvent.result((), {"texto": "ñandú", "ok": True}, ts=4.0),
        ),
    )
    phantom = _support.make_fake_interpreter(
        base / "fake_phantom",
        stdout=_fake_stdout(
            protocol.JobEvent.start(FAKE_INFO, ts=1.0),
            protocol.JobEvent.result(
                (protocol.OutputRef(PHANTOM_OUTPUT, "0" * 64, 10, "sum"),), {}, ts=2.0
            ),
        ),
    )

    project_root = [_STATE["project"].root]
    real = runner.JobRunner(jobs_root=root, package_dir=EXTENSION_DIR,
                            blender_python=Path(sys.executable),
                            forbidden_roots=project_root)
    tamper = runner.JobRunner(jobs_root=root, package_dir=EXTENSION_DIR,
                              blender_python=Path(sys.executable))
    echo = runner.JobRunner(jobs_root=root, package_dir=copy,
                            blender_python=Path(sys.executable))
    fake_noise = runner.JobRunner(jobs_root=root, package_dir=EXTENSION_DIR,
                                  blender_python=noise)
    fake_phantom = runner.JobRunner(jobs_root=root, package_dir=EXTENSION_DIR,
                                    blender_python=phantom)

    _submit("sum", real, _request(params=SUM_PARAMS))
    _submit("deleted", tamper, _request(params={"n": SUM_N, "chunks": 2}))
    _submit("altered", tamper, _request(params={"n": SUM_N, "chunks": 2}))
    folder = echo.prepare(_request(ECHO_WORKER, label="Eco de las pruebas",
                                   inputs={"data": "in/data.npy"}))
    folder.write_array("data", _STATE["utm"])
    _STATE["echo_input_sha256"] = _support.sha256_file(folder.inputs_dir / "data.npy")
    _submit("echo", echo, folder)
    _submit("noise", fake_noise, _request(label="Ruido en el canal"))
    _submit("phantom", fake_phantom, _request(label="Resultado fantasma"))

    others = (real, echo, fake_noise, fake_phantom)
    # El lanzador «tamper» no se sondea hasta que sus workers han terminado: su resultado se
    # borra o se altera antes de que el lanzador lo compruebe al finalizar.
    deadline = time.monotonic() + FINISH_DEADLINE_S
    while any(_support.pid_alive(_HANDLES[name].pid) for name in ("deleted", "altered")):
        if time.monotonic() > deadline:
            raise AssertionError("los workers de «deleted» y «altered» no terminaron")
        _poll(others)
        time.sleep(POLL_S)
    _STATE["tampered_state_before_poll"] = (_HANDLES["deleted"].state,
                                            _HANDLES["altered"].state)
    (_HANDLES["deleted"].job_dir.outputs_dir / "sum.npy").unlink()
    altered = _HANDLES["altered"].job_dir.outputs_dir / "sum.npy"
    data = bytearray(altered.read_bytes())
    data[-1] ^= 0x01  # mismo tamaño, otra huella
    altered.write_bytes(bytes(data))

    runners = (*others, tamper)
    while not all(handle.result() is not None for handle in _HANDLES.values()):
        if time.monotonic() > deadline:
            pending = [name for name, handle in _HANDLES.items() if handle.result() is None]
            raise AssertionError(f"no terminaron a tiempo: {pending}")
        _poll(runners)
        time.sleep(POLL_S)
    _poll(runners)  # ya no queda nada que contar
    _STATE["pycache_after"] = _pycache(EXTENSION_DIR)


def _job(name: str):
    handle = _HANDLES[name]
    return handle, handle.result()


def _event_lines(handle) -> tuple[list[dict], list[dict]]:
    """Las líneas de ``events.jsonl``: todas, en orden, y solo los eventos."""
    text = handle.job_dir.events_file.read_text(encoding="utf-8")
    lines = [json.loads(line) for line in text.splitlines()]
    return lines, [line for line in lines if "v" in line]


class SubmitTest(unittest.TestCase):
    """RF-004-01, RF-004-15: ``submit`` lanza el worker y vuelve sin esperarlo."""

    def test_submit_returns_quickly(self):
        """RF-004-01 (RNF-004-01): ``submit`` (carpeta, petición, ``state.json`` y arranque del proceso) vuelve en
        ≤ 0,2 s: la mediana de los cinco lanzamientos del módulo, y cada uno en ≤ 1 s aun
        con la máquina cargada."""
        times = _STATE["submit_s"]
        self.assertLessEqual(statistics.median(times.values()), SUBMIT_MAX_S, times)
        self.assertLessEqual(max(times.values()), 1.0, times)

    def test_submit_does_not_wait_for_the_worker(self):
        """RF-004-01: Justo después de ``submit`` el trabajo está «En curso» con su proceso; acaba
        después, al sondear."""
        self.assertEqual(_STATE["state_after_submit"]["sum"], "running")
        handle, result = _job("sum")
        self.assertIsInstance(handle.pid, int)
        self.assertGreater(handle.pid, 0)
        self.assertEqual(result.state, "succeeded")

    def test_not_finished_until_polled(self):
        """RF-004-05: El estado final lo decide ``poll``: con el worker ya terminado, el trabajo sigue
        «En curso» hasta que se sondea."""
        self.assertEqual(_STATE["tampered_state_before_poll"], ("running", "running"))


class SucceededTest(unittest.TestCase):
    """RF-004-05: un trabajo que termina bien queda «Terminado» con sus resultados
    verificados."""

    def test_chunked_sum_succeeds_with_its_output(self):
        """RF-004-05: La suma por trozos termina «Terminado» con su ``OutputRef`` (``out/sum.npy``,
        papel ``sum``, huella y tamaño del fichero) y la suma exacta n(n−1)/2."""
        handle, result = _job("sum")
        self.assertEqual(result.state, "succeeded")
        self.assertEqual(handle.state, "succeeded")
        self.assertEqual(result.job_uid, handle.job_uid)
        self.assertEqual(result.job_dir, handle.job_dir)
        self.assertIsNone(result.error_code)
        self.assertIsNone(result.error_text)
        self.assertEqual(len(result.outputs), 1)
        ref = result.outputs[0]
        self.assertEqual((ref.path, ref.role), ("out/sum.npy", "sum"))
        output = handle.job_dir.outputs_dir / "sum.npy"
        self.assertEqual(ref.sha256, _support.sha256_file(output))
        self.assertEqual(ref.size, output.stat().st_size)
        self.assertEqual(int(np.load(output, allow_pickle=False)), SUM_N * (SUM_N - 1) // 2)
        self.assertEqual(result.summary["sum"], SUM_N * (SUM_N - 1) // 2)
        self.assertGreater(result.duration_s, 0.0)
        self.assertEqual(handle.frac, 1.0)

    def test_on_finish_called_once_with_the_result(self):
        """RF-004-05: ``on_finish`` se llama una sola vez por trabajo, desde ``poll``, con su
        resultado."""
        for name, handle in _HANDLES.items():
            with self.subTest(job=name):
                self.assertEqual(_FINISHED.get(handle.job_uid), [handle.result()])

    def test_poll_reports_events_in_order_and_the_end_once(self):
        """RF-004-15: ``poll`` entrega los eventos de cada trabajo en orden y su final una sola vez, en
        la última actualización."""
        handle, result = _job("sum")
        updates = _UPDATES[handle.job_uid]
        finals = [update for update in updates if update.result is not None]
        self.assertEqual(finals, [updates[-1]])
        self.assertEqual(updates[-1].result, result)
        self.assertEqual(updates[-1].state, "succeeded")
        self.assertTrue(all(update.state == "running" for update in updates[:-1]))
        types = [event.type for update in updates for event in update.events]
        self.assertEqual(types[0], "start")
        self.assertEqual(types[-1], "result")
        self.assertIn("progress", types)


class RecordTest(unittest.TestCase):
    """RF-004-15: al llegar a un estado final queda en la carpeta el registro completo."""

    def test_state_json_has_the_final_record(self):
        """RF-004-15: ``state.json``: estado, ejecutor, intérprete con las versiones de Python, numpy y
        BLAS, proceso, horas de inicio y fin, duración, código de salida y resultados."""
        handle, result = _job("sum")
        record = records.read_record(handle.job_dir)
        self.assertIsNotNone(record)
        self.assertEqual(record.state, "succeeded")
        self.assertEqual(record.executor, "subprocess")
        self.assertEqual(record.worker, "selftest")
        self.assertEqual(record.label, LABEL)
        self.assertEqual(record.pid, handle.pid)
        self.assertEqual(record.exit_code, 0)
        self.assertIsNone(record.error)
        self.assertEqual(record.outputs, result.outputs)
        self.assertEqual(record.interpreter.kind, "blender")
        self.assertEqual(record.interpreter.python, platform.python_version())
        self.assertEqual(record.interpreter.numpy, np.__version__)
        self.assertTrue(record.interpreter.blas)
        self.assertIsNotNone(record.queued_at)
        self.assertLessEqual(record.queued_at, record.started_at)
        self.assertLessEqual(record.started_at, record.ended_at)
        self.assertIsNotNone(record.last_event_at)
        self.assertAlmostEqual(record.duration_s, result.duration_s)

    def test_state_json_has_no_absolute_paths(self):
        """RF-004-15: ``state.json`` puede estar dentro del proyecto: ni la raíz de trabajos ni el
        intérprete aparecen en él."""
        for name, handle in _HANDLES.items():
            with self.subTest(job=name):
                text = (handle.job_dir.path / records.RECORD_FILE).read_text(encoding="utf-8")
                self.assertNotIn(str(_STATE["root"]), text)
                self.assertNotIn(str(_STATE["root"]).replace("\\", "\\\\"), text)
                self.assertNotIn(sys.executable.replace("\\", "\\\\"), text)

    def test_events_jsonl_keeps_every_event_in_order(self):
        """RF-004-15: ``events.jsonl`` tiene todos los eventos recibidos en orden de llegada (los
        mismos que entregó ``poll``), con horas crecientes y el avance hasta 1,0, entre las
        notas del lanzador de arranque y de fin."""
        handle, _ = _job("sum")
        lines, events = _event_lines(handle)
        delivered = [event.to_json() for update in _UPDATES[handle.job_uid]
                     for event in update.events]
        self.assertEqual(events, delivered)
        self.assertEqual(events[0]["t"], "start")
        self.assertEqual(events[-1]["t"], "result")
        stamps = [event["ts"] for event in events]
        self.assertEqual(stamps, sorted(stamps))
        fracs = [event["frac"] for event in events if event["t"] == "progress"]
        self.assertEqual(fracs, sorted(fracs))
        self.assertEqual(fracs[-1], 1.0)
        self.assertEqual(lines[0].get("note"), "launched")
        self.assertEqual(lines[-1].get("note"), "finished")
        self.assertEqual(lines[-1].get("state"), "succeeded")
        self.assertEqual(lines[-1].get("exit_code"), 0)

    def test_request_log_and_result_are_kept(self):
        """RF-004-15: La carpeta conserva la petición, la salida de error del worker (``job.log``, con
        las líneas del arranque) y su ``result.json``."""
        handle, result = _job("sum")
        request = protocol.read_request(handle.job_dir)
        self.assertEqual(request.job_uid, handle.job_uid)
        self.assertEqual(dict(request.params), SUM_PARAMS)
        log = handle.job_dir.log_file.read_text(encoding="utf-8", errors="replace")
        self.assertIn("Geoblender: arranque del worker", log)
        self.assertIn("el worker termina con el código 0", log)
        saved = json.loads(handle.job_dir.result_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["t"], "result")
        self.assertEqual(saved["summary"], dict(result.summary))


class OutputCheckTest(unittest.TestCase):
    """RF-004-05: un resultado declarado que falta o no casa con su huella deja el trabajo
    «Fallido»."""

    def _check_failed(self, name: str, code: str, path: str, label: str = LABEL) -> None:
        handle, result = _job(name)
        self.assertEqual(result.state, "failed")
        self.assertEqual(handle.state, "failed")
        self.assertEqual(result.error_code, code)
        self.assertEqual(result.outputs, ())
        self.assertIn(path, result.error_text)
        self.assertIn(label, result.error_text)
        self.assertNotIn("Traceback", result.error_text)
        record = records.read_record(handle.job_dir)
        self.assertEqual(record.state, "failed")
        self.assertEqual(record.exit_code, 0)
        self.assertEqual(record.error.code, code)
        self.assertEqual(record.error.text, result.error_text)
        self.assertEqual(record.error.msgid, messages.lookup(code).msgid)
        self.assertEqual(record.outputs, ())

    def test_deleted_output(self):
        """RF-004-05: Un resultado borrado antes de finalizar → «Fallido» ``output_missing``."""
        self._check_failed("deleted", "output_missing", "out/sum.npy")

    def test_altered_output(self):
        """RF-004-05: Un resultado alterado (mismo tamaño, otro byte) antes de finalizar → «Fallido»
        ``output_hash_mismatch``."""
        self._check_failed("altered", "output_hash_mismatch", "out/sum.npy")

    def test_declared_output_that_never_existed(self):
        """RF-004-05: Un resultado declarado que nunca existió → «Fallido» ``output_missing``."""
        self._check_failed("phantom", "output_missing", PHANTOM_OUTPUT, "Resultado fantasma")


class ChannelNoiseTest(unittest.TestCase):
    """RF-004-15 (spec §8): una línea del canal que no es un evento va al registro como
    aviso y el trabajo sigue."""

    def test_noise_does_not_stop_the_job(self):
        """RF-004-15: El trabajo termina «Terminado» con su resumen; ``poll`` entrega solo los
        eventos válidos, en orden."""
        handle, result = _job("noise")
        self.assertEqual(result.state, "succeeded")
        self.assertEqual(dict(result.summary), {"texto": "ñandú", "ok": True})
        types = [event.type for update in _UPDATES[handle.job_uid] for event in update.events]
        self.assertEqual(types, ["start", "progress", "progress", "result"])

    def test_invalid_lines_are_noted_in_place(self):
        """RF-004-15: Cada línea que no es un evento queda en ``events.jsonl`` como nota, en su sitio
        entre los eventos, con el texto y el motivo."""
        handle, _ = _job("noise")
        lines, _ = _event_lines(handle)
        kinds = [line.get("note") or line["t"] for line in lines]
        self.assertEqual(kinds, ["launched", "start", "progress", "invalid_line",
                                 "invalid_line", "invalid_line", "progress", "result",
                                 "finished"])
        notes = [line for line in lines if line.get("note") == "invalid_line"]
        self.assertEqual([note["text"] for note in notes], list(NOISE_LINES))
        self.assertTrue(all(note["reason"] for note in notes))

    def test_invalid_lines_are_warned_in_job_log(self):
        """RF-004-15: y como aviso en ``job.log``, una línea por cada una."""
        handle, _ = _job("noise")
        log = handle.job_dir.log_file.read_text(encoding="utf-8")
        warnings = [line for line in log.splitlines() if "no es un evento" in line]
        self.assertEqual(len(warnings), len(NOISE_LINES))
        self.assertIn(NOISE_LINES[0], warnings[0])

    def test_interpreter_versions_come_from_the_start_event(self):
        """RF-004-15: El intérprete del registro es el que contó el evento ``start``."""
        handle, _ = _job("noise")
        interpreter = records.read_record(handle.job_dir).interpreter
        self.assertEqual((interpreter.kind, interpreter.python, interpreter.numpy,
                          interpreter.blas), ("blender", "3.13.13", "2.3.4", "auto"))


class InputBitExactTest(unittest.TestCase):
    """RF-004-01: las entradas que deja el módulo en la carpeta llegan al worker tal cual."""

    def test_float64_utm_and_nan_arrive_bit_exact(self):
        """``prepare`` + ``write_array`` + ``submit``: un float64 con coordenadas UTM de
        4,4 Mm, NaN con carga útil, −0,0, subnormal e infinitos llega al worker y vuelve
        idéntico bit a bit; la entrada sigue igual."""
        handle, result = _job("echo")
        self.assertEqual(result.state, "succeeded", result.error_text)
        original = _STATE["utm"]
        self.assertEqual(result.summary["dtype"], "<f8")
        self.assertEqual(result.summary["sha256"],
                         hashlib.sha256(original.tobytes()).hexdigest())
        echoed = np.load(handle.job_dir.outputs_dir / "echo.npy", allow_pickle=False)
        np.testing.assert_array_equal(echoed.view(np.uint64), original.view(np.uint64))
        self.assertEqual(_support.sha256_file(handle.job_dir.inputs_dir / "data.npy"),
                         _STATE["echo_input_sha256"])
        request = protocol.read_request(handle.job_dir)
        self.assertEqual(dict(request.inputs), {"data": "in/data.npy"})


class PrepareTest(unittest.TestCase):
    """RF-004-01, RF-004-02: ``prepare`` crea la carpeta del trabajo con su petición
    completa y validada, o no crea nada."""

    def setUp(self):
        tmp = _support.temp_jobs_root()
        self.root = tmp.__enter__()
        self.addCleanup(tmp.__exit__, None, None, None)
        self.runner = runner.JobRunner(
            jobs_root=self.root / "sub", package_dir=EXTENSION_DIR,
            blender_python=Path(sys.executable), forbidden_roots=[_STATE["project"].root],
        )

    def test_prepare_writes_request_and_queued_state(self):
        """RF-004-01: La carpeta ``<raíz>/<job_uid>`` con ``in/``, ``out/``, ``request.json`` (con el
        entorno y el tiempo máximo del tipo de trabajo si la petición no los trae, y la
        versión de Geoblender) y ``state.json`` «En cola»; no arranca nada."""
        request = _request(params={"n": 10})
        folder = self.runner.prepare(request)
        self.assertEqual(folder.path, self.root / "sub" / request.job_uid)
        self.assertTrue(folder.inputs_dir.is_dir())
        self.assertTrue(folder.outputs_dir.is_dir())
        written = protocol.read_request(folder)
        self.assertEqual(written.environment, "blender")
        self.assertEqual(written.timeout_s, _STATE["selftest_info"].default_timeout_s)
        self.assertEqual(written.geoblender_version, request.geoblender_version)
        self.assertEqual(dict(written.params), {"n": 10})
        record = records.read_record(folder)
        self.assertEqual((record.state, record.executor), ("queued", "subprocess"))
        self.assertIsNone(record.pid)
        self.assertFalse(folder.events_file.exists())
        self.assertFalse(folder.log_file.exists())

    def test_prepare_keeps_a_declared_timeout(self):
        """RF-004-01: El tiempo máximo que trae la petición se respeta."""
        folder = self.runner.prepare(_request(timeout_s=12.5))
        self.assertEqual(protocol.read_request(folder).timeout_s, 12.5)

    def test_project_path_is_rejected_without_files(self):
        """RF-004-02: una petición con la ruta del proyecto en un parámetro se rechaza
        (``request_path_outside_job``) sin crear nada."""
        hidden = str(_STATE["project"].root / "project.gpkg")
        with self.assertRaises(messages.JobError) as caught:
            self.runner.prepare(_request(params={"op": "chunked_sum", "nota": hidden}))
        self.assertEqual(caught.exception.code, "request_path_outside_job")
        self.assertFalse((self.root / "sub").exists())

    def test_reconfigure_changes_the_forbidden_roots(self):
        """RF-004-02: ``reconfigure(forbidden_roots=…)`` cambia las rutas prohibidas de lo
        que se prepare después (al abrir o cerrar un proyecto): sin ninguna, la ruta del
        proyecto se admite; con la del proyecto otra vez, se rechaza. Una relativa es
        ``ValueError`` y no cambia nada, tampoco lo demás de la misma llamada."""
        project = _STATE["project"].root
        hidden = str(project / "project.gpkg")
        self.assertEqual(self.runner.forbidden_roots, (project,))
        self.runner.reconfigure(forbidden_roots=())
        self.assertEqual(self.runner.forbidden_roots, ())
        folder = self.runner.prepare(_request(params={"op": "chunked_sum", "nota": hidden}))
        self.assertTrue(folder.path.is_dir())
        with self.assertRaises(ValueError):
            self.runner.reconfigure(forbidden_roots=[project, Path("relativa")],
                                    max_subprocess=3)
        self.assertEqual((self.runner.forbidden_roots, self.runner.max_subprocess), ((), 2))
        self.runner.reconfigure(forbidden_roots=[str(project)])
        self.assertEqual(self.runner.forbidden_roots, (project,))
        with self.assertRaises(messages.JobError) as caught:
            self.runner.prepare(_request(params={"op": "chunked_sum", "nota": hidden}))
        self.assertEqual(caught.exception.code, "request_path_outside_job")

    def test_unknown_worker_is_rejected_without_files(self):
        """RF-004-02: Un tipo de trabajo que no está registrado es ``worker_unknown`` y no crea
        nada."""
        with self.assertRaises(messages.JobError) as caught:
            self.runner.prepare(_request("gbtest_nada"))
        self.assertEqual(caught.exception.code, "worker_unknown")
        self.assertFalse((self.root / "sub").exists())


class BytecodeTest(unittest.TestCase):
    """Plan 004 §2.1 y §6: los workers que lanza el lanzador no dejan ``__pycache__``."""

    def test_no_new_pycache_under_package_dir(self):
        """RF-004-01: Ningún ``__pycache__`` nuevo bajo el paquete tras los trabajos del módulo."""
        new = _STATE["pycache_after"] - _STATE["pycache_before"]
        self.assertEqual(sorted(new), [])


if __name__ == "__main__":
    unittest.main()
