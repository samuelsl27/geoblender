# SPDX-License-Identifier: GPL-3.0-or-later
"""Fallos de los trabajos en proceso aparte (spec 004, T12; HU-004-2, RF-004-12; plan 004
§5.3.4 y §5.4.3).

Un worker que informa de un error, que termina con un código distinto de 0 o que acaba sin
entregar resultados deja su trabajo «Fallido» con el código del plan §5.3.4 y su mensaje en
español del §8 (sin traza de Python: la traza va solo a ``job.log``), y el proceso que lo
lanzó (en el producto, Blender; aquí, el de las pruebas) sigue como estaba.

Para no esperar en serie, todos los trabajos del módulo se lanzan a la vez al empezar
(``setUpModule``) y se sondean hasta que acaban; cada prueba mira lo que dejó el suyo:

- ``fail``: el autodiagnóstico con ``fail_at`` (``JobFailed``, salida 2).
- ``crash``: el autodiagnóstico con ``crash_at`` (``os._exit(7)``).
- ``raise``: un worker de prueba que lanza una excepción que nadie captura (salida 1).
- ``sys_exit``: un worker de prueba que llama a ``sys.exit(3)``, como lo haría una librería;
  no puede pasar por una cancelación (salida 3) ni por ningún otro código del arranque.
- ``exit0``: un worker de prueba que termina el proceso con ``os._exit(0)`` sin resultado.
- ``noise``: un intérprete falso que escribe en el canal ruido que no es JSON, pegado al
  evento ``result`` (que se pierde), y sale con 0.
- ``traceback``: un intérprete falso que manda un evento ``error`` con una traza de Python
  en su texto y sale con 2.
- ``ghost``: un tipo de trabajo registrado sin módulo en ``workers/`` (el arranque sale
  con 5).
- ``removed``: un trabajo ya preparado cuyo tipo se quita del registro antes de lanzarlo.
- ``missing``: un intérprete que no existe.

Los trabajos con el Python de las pruebas usan una copia del paquete con el worker de prueba
``gbtest_failures``; el autodiagnóstico se registra con la política ``subprocess``.
"""

import dataclasses
import json
import os
import shutil
import sys
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
selftest = import_geoblender("jobs.selftest")

TEST_WORKER = "gbtest_failures"
GHOST_WORKER = "gbtest_fantasma"
REMOVED_WORKER = "gbtest_retirado"
JOB_TIMEOUT_S = 120.0
DEADLINE_S = 60.0
POLL_S = 0.02
UNCAUGHT_TEXT = "fallo de prueba sin capturar: ñandú"
WORKER_TRACE_LAST = "ValueError: dato de prueba ñ"
NOISE_LINE = "Setting Backend To: AvailableBackends.numpy"

# Worker de prueba que se añade a la copia del paquete: falla como le pida «mode».
TEST_WORKER_SOURCE = '''# SPDX-License-Identifier: GPL-3.0-or-later
"""Worker de las pruebas de fallos: termina mal según params["mode"]."""

import os
import sys


def main(ctx):
    ctx.progress(0.5, "Mitad del trabajo")
    ctx.flush()
    mode = ctx.request.params["mode"]
    if mode == "raise":
        raise RuntimeError("fallo de prueba sin capturar: ñandú")
    if mode == "sys_exit":
        sys.exit(3)
    if mode == "exit0":
        os._exit(0)
    return {"mode": mode}
'''

LABELS = {
    "fail": "Fallo provocado",
    "crash": "Caída provocada",
    "raise": "Excepción sin capturar",
    "sys_exit": "Salida de una librería",
    "exit0": "Salida sin resultado",
    "noise": "Ruido en el canal",
    "traceback": "Traza en el mensaje",
    "ghost": "Tipo sin módulo",
    "removed": "Tipo retirado",
    "missing": "Intérprete inexistente",
}
"""El nombre de cada trabajo (su ``label``), el que citan los mensajes."""

FAKE_INFO = {"pid": 4120, "kind": "blender", "python": "3.13.13", "numpy": "2.3.4",
             "blas": "auto"}
WORKER_TRACE = (
    "Fallo de prueba en el cálculo.\n"
    "Traceback (most recent call last):\n"
    '  File "calculo.py", line 3, in run\n'
    "    raise ValueError(\"dato de prueba ñ\")\n"
    f"{WORKER_TRACE_LAST}"
)

_HANDLES: dict[str, object] = {}
_RUNNERS: dict[str, object] = {}
_UPDATES: dict[str, list] = {}
_FINISHED: dict[str, list] = {}
_STATE: dict[str, object] = {}


def _request(name: str, worker: str = "selftest", params: dict | None = None):
    return protocol.new_request(worker, label=LABELS[name], owner="jobs", params=params)


def _on_finish(result) -> None:
    _FINISHED.setdefault(result.job_uid, []).append(result)


def _submit(name: str, job_runner, job) -> None:
    """Lanza ``job``; si ``submit`` lanza una excepción, la apunta (la prueba del caso
    falla con ella) en vez de tumbar el módulo."""
    _RUNNERS[name] = job_runner
    try:
        _HANDLES[name] = job_runner.submit(job, on_finish=_on_finish)
    except Exception as exc:  # noqa: BLE001 - se comprueba en la prueba del caso
        _STATE.setdefault("submit_errors", {})[name] = exc


def _poll() -> None:
    for job_runner in {id(r): r for r in _RUNNERS.values()}.values():
        for update in job_runner.poll():
            _UPDATES.setdefault(update.job_uid, []).append(update)


def _fake_stdout(*items: object) -> str:
    """El canal de un intérprete falso: cada evento en su línea y cada texto tal cual."""
    return "".join(
        item if isinstance(item, str) else protocol.encode_event(item).decode("utf-8")
        for item in items
    )


def setUpModule() -> None:
    tmp = _support.jobs_tmp()
    base = tmp.__enter__()
    unittest.addModuleCleanup(tmp.__exit__, None, None, None)
    root = base / "jobs"
    _STATE["test_pid"] = os.getpid()

    registry = mock.patch.dict(catalog._REGISTRY, clear=True)
    registry.start()
    unittest.addModuleCleanup(registry.stop)
    builtin = next(info for info in catalog.BUILTIN_WORKERS if info.name == "selftest")
    catalog.register_worker(dataclasses.replace(builtin, policy="subprocess",
                                                default_timeout_s=JOB_TIMEOUT_S))
    for name in (TEST_WORKER, GHOST_WORKER, REMOVED_WORKER):
        catalog.register_worker(catalog.WorkerInfo(name, "Failure test worker",
                                                   policy="subprocess",
                                                   default_timeout_s=JOB_TIMEOUT_S))

    copy = base / "pkg"
    shutil.copytree(
        EXTENSION_DIR, copy,
        ignore=shutil.ignore_patterns("__pycache__", "*.py[cod]", "bl", "resources",
                                      "thirdparty", "wheels"),
    )
    (copy / "workers" / f"{TEST_WORKER}.py").write_bytes(TEST_WORKER_SOURCE.encode("utf-8"))

    noise = _support.make_fake_interpreter(
        base / "fake_noise",
        stdout=_fake_stdout(
            protocol.JobEvent.start(FAKE_INFO, ts=1.0),
            protocol.JobEvent.progress(0.5, "Mitad", ts=2.0),
            NOISE_LINE + "\n",
            # Una librería escribe sin salto de línea justo antes del resultado: el evento
            # result queda pegado al ruido y deja de ser un evento.
            "Ruido de una librería sin salto de línea "
            + protocol.encode_event(protocol.JobEvent.result((), {"ok": True}, ts=3.0))
            .decode("utf-8"),
        ),
    )
    trace = _support.make_fake_interpreter(
        base / "fake_trace",
        stdout=_fake_stdout(
            protocol.JobEvent.start(FAKE_INFO, ts=1.0),
            protocol.JobEvent.error("gbtest_failed", msgid="Test failure in the calculation.",
                                    msg=WORKER_TRACE, ts=2.0),
        ),
        exit_code=2,
    )

    options = {"jobs_root": root, "package_dir": copy}
    real = runner.JobRunner(**options, blender_python=Path(sys.executable),
                            max_subprocess=8)
    fake_noise = runner.JobRunner(**options, blender_python=noise)
    fake_trace = runner.JobRunner(**options, blender_python=trace)
    _STATE["missing_python"] = base / "sin_python" / "python.exe"
    missing = runner.JobRunner(**options, blender_python=_STATE["missing_python"])

    _submit("fail", real, _request("fail", params={"n": 1000, "chunks": 3, "fail_at": 2}))
    _submit("crash", real, _request("crash", params={"n": 1000, "chunks": 3, "crash_at": 2}))
    for mode in ("raise", "sys_exit", "exit0"):
        _submit(mode, real, _request(mode, TEST_WORKER, {"mode": mode}))
    _submit("ghost", real, _request("ghost", GHOST_WORKER))
    removed = real.prepare(_request("removed", REMOVED_WORKER))
    catalog.unregister_worker(REMOVED_WORKER)
    _submit("removed", real, removed)
    _submit("noise", fake_noise, _request("noise"))
    _submit("traceback", fake_trace, _request("traceback"))
    _submit("missing", missing, _request("missing"))

    deadline = time.monotonic() + DEADLINE_S
    while not all(handle.result() is not None for handle in _HANDLES.values()):
        if time.monotonic() > deadline:
            pending = [name for name, handle in _HANDLES.items() if handle.result() is None]
            raise AssertionError(f"no terminaron a tiempo: {pending}")
        _poll()
        time.sleep(POLL_S)
    _poll()  # cuenta los finales que quedaran


def _lines(handle) -> list[dict]:
    """Las líneas de ``events.jsonl`` del trabajo, en orden (eventos y notas)."""
    text = handle.job_dir.events_file.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def _log(handle) -> str:
    return handle.job_dir.log_file.read_text(encoding="utf-8", errors="replace")


class _FailureCase(unittest.TestCase):
    """Comprobaciones comunes de un trabajo que tiene que acabar «Fallido»."""

    def failed(self, name: str, *, code: str, exit_code: int | None, text: str,
               msgid: str | None = None):
        """El trabajo ``name`` acabó «Fallido» con ``code``, ``exit_code`` y el mensaje en
        español ``text`` (de una línea, sin traza), igual en su :class:`JobResult`, en su
        último mensaje y en su ``state.json`` (aquí, sin rutas absolutas), sin resultados;
        devuelve su handle."""
        self.assertNotIn(name, _STATE.get("submit_errors", {}))
        handle = _HANDLES[name]
        result = handle.result()
        self.assertEqual((result.state, handle.state), ("failed", "failed"))
        self.assertEqual(result.error_code, code)
        self.assertEqual(result.error_text, text)
        self.assertEqual(handle.message, text)
        for mark in ("Traceback", 'File "', "\n"):
            self.assertNotIn(mark, result.error_text)
        self.assertEqual(result.outputs, ())
        self.assertEqual(dict(result.summary), {})
        record = records.read_record(handle.job_dir)
        self.assertEqual(record.state, "failed")
        self.assertEqual(record.exit_code, exit_code)
        self.assertEqual((record.error.code, record.error.text),
                         (code, records.without_absolute_paths(text)))
        expected_msgid = msgid if msgid is not None else messages.lookup(code).msgid
        self.assertEqual(record.error.msgid, expected_msgid)
        self.assertEqual(record.outputs, ())
        self.assertIsNotNone(record.ended_at)
        self.assertFalse(handle.job_dir.result_file.exists())
        self.assertEqual(_FINISHED.get(handle.job_uid), [result])
        state_text = (handle.job_dir.path / records.RECORD_FILE).read_text(encoding="utf-8")
        self.assertNotIn("Traceback", state_text)
        notes = [line for line in _lines(handle) if "note" in line]
        self.assertEqual(notes[-1]["note"], "finished")
        self.assertEqual((notes[-1]["state"], notes[-1]["error"]), ("failed", code))
        return handle

    def without_process(self, handle) -> None:
        """El trabajo no llegó a tener proceso."""
        record = records.read_record(handle.job_dir)
        self.assertIsNone(handle.pid)
        self.assertIsNone(record.pid)
        self.assertIsNone(record.started_at)
        self.assertIsNone(record.duration_s)
        self.assertIsNone(handle.result().duration_s)
        self.assertNotIn("launched", [line.get("note") for line in _lines(handle)])


class WorkerErrorTest(_FailureCase):
    """RF-004-12: un worker que informa de un error (salida 2) deja el trabajo «Fallido»
    con el código y el texto en español de su evento ``error``."""

    def test_fail_at(self):
        """RF-004-12: ``fail_at`` → salida 2, ``selftest_failed`` con su texto en español
        («fallo provocado en el trozo 2 de 3») y sin traza en ningún sitio."""
        handle = self.failed(
            "fail", code="selftest_failed", exit_code=2,
            text="Autodiagnóstico: fallo provocado en el trozo 2 de 3.",
            msgid=selftest.MESSAGES["selftest_failed"].msgid,
        )
        record = records.read_record(handle.job_dir)
        self.assertEqual(dict(record.error.values), {"chunk": 2, "chunks": 3})
        self.assertNotIn("Traceback", _log(handle))
        self.assertNotIn("Traceback", handle.job_dir.events_file.read_text(encoding="utf-8"))

    def test_worker_message_with_a_traceback(self):
        """RF-004-12: si el texto del evento ``error`` trae una traza de Python (un worker
        que no cumple su contrato), el mensaje del trabajo es una sola línea sin ella (su
        última línea, la excepción)."""
        self.failed("traceback", code="gbtest_failed", exit_code=2, text=WORKER_TRACE_LAST,
                    msgid="Test failure in the calculation.")


class CrashTest(_FailureCase):
    """RF-004-12: un worker que muere con otro código (caída nativa, ``os._exit``) deja el
    trabajo «Fallido» ``worker_crashed`` con su código."""

    def test_crash_at(self):
        """RF-004-12: ``crash_at`` → ``os._exit(7)``: ``worker_crashed`` (código 7), con
        el nombre del trabajo y remitiendo a su registro."""
        handle = self.failed(
            "crash", code="worker_crashed", exit_code=7,
            text="El cálculo «Caída provocada» terminó de forma inesperada (código 7). "
                 "Detalles en su registro.",
        )
        self.assertEqual(dict(records.read_record(handle.job_dir).error.values),
                         {"job": LABELS["crash"], "exit_code": 7})


class UncaughtExceptionTest(_FailureCase):
    """RF-004-12 (plan §5.4.3, paso 8): una excepción que el worker no captura termina con
    la salida 1 y la traza solo en ``job.log``."""

    def test_uncaught_exception(self):
        """RF-004-12: salida 1, ``worker_crashed`` (código 1); la traza con la excepción
        está en ``job.log`` y no en el mensaje, ``state.json`` ni ``events.jsonl``."""
        handle = self.failed(
            "raise", code="worker_crashed", exit_code=1,
            text="El cálculo «Excepción sin capturar» terminó de forma inesperada "
                 "(código 1). Detalles en su registro.",
        )
        log = _log(handle)
        self.assertIn("Traceback (most recent call last)", log)
        self.assertIn(f"RuntimeError: {UNCAUGHT_TEXT}", log)
        self.assertIn("excepción no capturada", log)
        events = handle.job_dir.events_file.read_text(encoding="utf-8")
        self.assertNotIn("Traceback", events)
        self.assertNotIn(UNCAUGHT_TEXT, events)

    def test_sys_exit_is_an_uncaught_exception(self):
        """RF-004-12: ``sys.exit(3)`` dentro del cálculo (una librería) no se hace pasar por
        una cancelación: salida 1, ``worker_crashed`` (código 1), traza de ``SystemExit``
        en ``job.log``."""
        handle = self.failed(
            "sys_exit", code="worker_crashed", exit_code=1,
            text="El cálculo «Salida de una librería» terminó de forma inesperada "
                 "(código 1). Detalles en su registro.",
        )
        log = _log(handle)
        self.assertIn("Traceback (most recent call last)", log)
        self.assertIn("SystemExit: 3", log)
        self.assertIsNone(records.read_record(handle.job_dir).cancel)


class NoResultTest(_FailureCase):
    """RF-004-12: un worker que sale con 0 sin entregar resultados deja el trabajo «Fallido»
    ``protocol_no_result``."""

    def test_exit_0_without_result(self):
        """RF-004-12: ``os._exit(0)`` a mitad del cálculo: salida 0 sin evento ``result`` →
        ``protocol_no_result``; su avance sí llegó."""
        handle = self.failed(
            "exit0", code="protocol_no_result", exit_code=0,
            text="El trabajo «Salida sin resultado» terminó sin entregar resultados.",
        )
        types = [event.type for update in _UPDATES[handle.job_uid] for event in update.events]
        self.assertEqual(types, ["start", "progress"])

    def test_noise_spoils_the_result(self):
        """RF-004-12, RF-004-15: ruido que no es JSON en el canal, pegado al evento
        ``result``: el resultado no cuenta (``protocol_no_result``, salida 0) y cada línea
        que no es un evento queda como nota en ``events.jsonl`` y como aviso en
        ``job.log``."""
        handle = self.failed(
            "noise", code="protocol_no_result", exit_code=0,
            text="El trabajo «Ruido en el canal» terminó sin entregar resultados.",
        )
        notes = [line for line in _lines(handle) if line.get("note") == "invalid_line"]
        self.assertEqual(len(notes), 2)
        self.assertEqual(notes[0]["text"], NOISE_LINE)
        self.assertTrue(notes[1]["text"].startswith("Ruido de una librería"))
        warnings = [line for line in _log(handle).splitlines() if "no es un evento" in line]
        self.assertEqual(len(warnings), 2)


class UnknownWorkerTest(_FailureCase):
    """RF-004-12 (spec §8): un tipo de trabajo que no existe deja el trabajo «Fallido» con
    ``worker_unknown``."""

    def test_registered_type_without_module(self):
        """RF-004-12: un tipo registrado sin módulo en ``workers/``: el arranque sale con 5
        y el trabajo acaba «Fallido» ``worker_unknown``."""
        self.failed("ghost", code="worker_unknown", exit_code=5,
                    text=f"No existe el tipo de trabajo «{GHOST_WORKER}».")

    def test_type_removed_before_submit(self):
        """RF-004-12: un trabajo ya preparado cuyo tipo deja de existir antes de lanzarlo
        acaba «Fallido» ``worker_unknown`` sin proceso, con su ``state.json`` final (no se
        queda «En cola»)."""
        handle = self.failed("removed", code="worker_unknown", exit_code=None,
                             text=f"No existe el tipo de trabajo «{REMOVED_WORKER}».")
        self.without_process(handle)


class MissingInterpreterTest(_FailureCase):
    """RF-004-12: un intérprete que no existe deja el trabajo «Fallido» sin proceso."""

    def test_missing_interpreter(self):
        """RF-004-12: ``interpreter_not_found`` con la ruta del intérprete y el error del
        sistema, sin proceso (en ``state.json``, la ruta sin su parte absoluta)."""
        path = str(_STATE["missing_python"])
        handle = _HANDLES["missing"]
        text = handle.result().error_text
        self.assertTrue(text.startswith(f"No se pudo arrancar el intérprete {path}: "), text)
        self.assertGreater(len(text), len(f"No se pudo arrancar el intérprete {path}: ."))
        self.failed("missing", code="interpreter_not_found", exit_code=None, text=text)
        self.without_process(handle)
        state_text = (handle.job_dir.path / records.RECORD_FILE).read_text(encoding="utf-8")
        self.assertNotIn(path.replace("\\", "\\\\"), state_text)


class TestProcessUnaffectedTest(unittest.TestCase):
    """RF-004-12: los fallos no interrumpen ni afectan al proceso que lanzó los trabajos."""

    def test_launcher_process_alive(self):
        """RF-004-12: el proceso que lanzó los trabajos sigue vivo y es el mismo después de
        todos los fallos (también de ``os._exit`` y ``sys.exit`` en los workers)."""
        self.assertEqual(os.getpid(), _STATE["test_pid"])
        self.assertTrue(_support.pid_alive(os.getpid()))

    def test_every_case_failed_without_raising(self):
        """RF-004-12: ``submit`` no lanzó nada en ningún caso y todos acabaron «Fallido»,
        con su final contado una sola vez por ``poll``."""
        self.assertEqual(_STATE.get("submit_errors", {}), {})
        self.assertEqual({name: handle.state for name, handle in _HANDLES.items()},
                         dict.fromkeys(LABELS, "failed"))
        for name, handle in _HANDLES.items():
            with self.subTest(job=name):
                finals = [update for update in _UPDATES[handle.job_uid] if update.finished]
                self.assertEqual(finals, [_UPDATES[handle.job_uid][-1]])
                self.assertEqual(finals[0].result, handle.result())

    def test_no_worker_left_alive(self):
        """RF-004-12: no queda vivo ninguno de los workers que llegaron a arrancar."""
        started = {name: handle.pid for name, handle in _HANDLES.items()
                   if handle.pid is not None}
        self.assertEqual(len(started), 8)
        for name, pid in started.items():
            with self.subTest(job=name):
                self.assertTrue(_support.wait_until_dead(pid, timeout_s=5.0))


if __name__ == "__main__":
    unittest.main()
