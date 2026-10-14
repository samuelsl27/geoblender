# SPDX-License-Identifier: GPL-3.0-or-later
"""Cancelación, plazo de gracia, tiempo máximo y terminación del *Job Object* (spec 004, T10
y T11; RF-004-09, RF-004-10, RF-004-11; plan 004 §5.3.4, §5.4.2 y §5.4.5).

``JobRunner.cancel`` (y ``JobHandle.cancel``) pide parar un trabajo: uno en cola se cancela
sin arrancar; a uno en curso se le crea el centinela ``cancel`` y el worker para en su
siguiente punto de control (≤ 2 s); si sigue vivo al vencer su plazo de gracia, el
lanzador termina su *Job Object* (el worker y sus hijos) y la cancelación consta como
forzada. Cancelar dos veces, o un trabajo ya terminado, no cambia nada. Un trabajo que
supera su tiempo máximo (``timeout_s`` de la petición; si no lo trae, el de su tipo de
trabajo o 3600 s) se detiene igual y acaba «Tiempo agotado», con ese tiempo en el mensaje.

Para no esperar en serie, todos los trabajos del módulo se lanzan a la vez al empezar
(``setUpModule``), se cancelan juntos en cuanto están en marcha y se sondean hasta que
acaban; cada prueba mira lo que dejó el suyo:

- ``running``: suma por trozos de 20 s (40 × 0,5 s), cancelada en curso.
- ``queued``: la misma suma, en la cola de un lanzador de un solo hueco detrás de
  ``running``, cancelada antes de arrancar.
- ``ignore``: la misma suma sin atender la cancelación (``ignore_cancel``), con el plazo de
  gracia mínimo (1 s).
- ``done``: una suma corta que ya terminó cuando se cancela.
- ``uncontained``: un worker que no se puede asignar a su *Job Object* (se simula el fallo).
- ``timeout``: la suma larga con ``timeout_s`` = 2 y el plazo de gracia mínimo; nadie la
  cancela.
- ``timeout_forced``: lo mismo sin atender la cancelación: el tiempo máximo la termina al
  vencer el plazo de gracia.
- ``timeout_catalog``: la suma larga sin tiempo máximo en la petición, con un tipo de
  trabajo que declara 2 s (solo mientras se lanza).

Si un trabajo de tiempo máximo no ha acabado al pasar ``RESCUE_S``, se cancela para que el
módulo termine y sus pruebas fallen con su motivo (``_STATE["rescued"]``).

Con la máquina cargada (las partes de ``tools/check.py`` a la vez, u otro programa), un
worker puede tardar en arrancar o en atender la petición más que los plazos de RF-004-09 a
RF-004-11, aunque el código esté bien. Como ``tests.support.timing.least_of`` con una
medida (spec 006, T48), si alguna medida que la carga solo puede alargar no cabe en su
plazo (:func:`_late`: un final tardío, un trabajo que hubo que rescatar o terminar a la
fuerza cuando debía parar solo), el escenario entero se repite, hasta
``SCENARIO_ATTEMPTS`` veces, y las pruebas miran el último. Los plazos no cambian: si no
caben en ninguno, las pruebas fallan igual.
"""

import dataclasses
import json
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
winjob = import_geoblender("jobs.winjob")

LONG_SUM = {"n": 1000, "chunks": 40, "sleep_s": 0.5}
"""20 s si nadie la para."""
QUICK_SUM = {"n": 1000, "chunks": 2}
GRACE_S = 1.0
"""El plazo de gracia mínimo válido: el caso que no atiende la cancelación dura ~1 s."""
STOP_MAX_S = 2.0
"""RF-004-09: detenido en ≤ 2 s."""
KILL_EXTRA_S = 1.0
"""RF-004-10: terminado en ≤ 1 s más tras vencer el plazo de gracia."""
JOB_TIMEOUT_S = 120.0
TIMEOUT_S = 2.0
"""RF-004-11: el tiempo máximo de los casos de tiempo agotado."""
TIMEOUT_MAX_S = TIMEOUT_S + GRACE_S + 1.0
"""RF-004-11 (tarea T11): «Tiempo agotado» entre 2 s y 2 s + ``grace_s`` + 1 s."""
RESCUE_S = TIMEOUT_MAX_S + 2.0
DEADLINE_S = 30.0
SCENARIO_ATTEMPTS = 5
"""Veces que, como mucho, se ejecuta el escenario si una medida no cabe (spec 006, T48)."""
POLL_S = 0.02
UNKNOWN_UID = "20260101_000000_abcdef"
TIMEOUT_JOBS = ("timeout", "timeout_forced", "timeout_catalog")

LABELS = {
    "running": "Cancelación en curso",
    "queued": "Cancelación en cola",
    "ignore": "Cancelación forzada",
    "done": "Trabajo ya terminado",
    "uncontained": "Sin Job Object",
    "timeout": "Tiempo máximo",
    "timeout_forced": "Tiempo máximo forzado",
    "timeout_catalog": "Tiempo máximo del catálogo",
}

_HANDLES: dict[str, object] = {}
_RUNNERS: dict[str, object] = {}
_UPDATES: dict[str, list] = {}
_FINISHED: dict[str, list] = {}
_STATE: dict[str, object] = {}


def _request(name: str, params: dict, **options):
    return protocol.new_request("selftest", label=LABELS[name], owner="jobs",
                                params=params, **options)


def _on_finish(result) -> None:
    _FINISHED.setdefault(result.job_uid, []).append(result)


def _submit(name: str, job_runner, request) -> None:
    _STATE.setdefault("submitted_at", {})[name] = time.monotonic()
    handle = job_runner.submit(request, on_finish=_on_finish)
    _HANDLES[name] = handle
    _RUNNERS[name] = job_runner
    _STATE.setdefault("state_after_submit", {})[name] = handle.state


def _poll() -> None:
    for job_runner in {id(r): r for r in _RUNNERS.values()}.values():
        for update in job_runner.poll():
            _UPDATES.setdefault(update.job_uid, []).append(update)


def _types(name: str) -> list[str]:
    return [event.type for update in _UPDATES.get(_HANDLES[name].job_uid, ())
            for event in update.events]


def _state_bytes() -> dict[str, bytes]:
    return {name: (handle.job_dir.path / records.RECORD_FILE).read_bytes()
            for name, handle in _HANDLES.items()}


def _wait_for(condition, what: str) -> None:
    deadline = time.monotonic() + DEADLINE_S
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"no llegó a tiempo: {what}")
        _poll()
        time.sleep(POLL_S)


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
    lateness: list[list[str]] = []
    for attempt in range(1, SCENARIO_ATTEMPTS + 1):
        for found in (_HANDLES, _RUNNERS, _UPDATES, _FINISHED, _STATE):
            found.clear()
        _scenario(base / f"jobs-{attempt}", builtin)
        lateness.append(_late())
        if not lateness[-1]:
            break
    _STATE["lateness"] = lateness


def _late() -> list[str]:
    """Las medidas del escenario que la carga de la máquina solo puede alargar y que no
    cupieron en su plazo (vacía si cupieron todas): el final de una cancelación en curso,
    de una forzada y de un tiempo máximo; un trabajo de tiempo máximo que hubo que rescatar;
    o terminado a la fuerza (o sin avisar de que paraba) cuando debía parar solo."""
    late: list[str] = []
    cancel_at, dead_at, final_at = _STATE["cancel_at"], _STATE["dead_at"], _STATE["final_at"]
    limits = {"running": STOP_MAX_S, "ignore": GRACE_S + KILL_EXTRA_S}
    for name, limit in limits.items():
        for what, when in (("muerte", dead_at), ("final", final_at)):
            if when[name] - cancel_at[name] > limit:
                late.append(f"{name}: {what} a {when[name] - cancel_at[name]:.2f} s")
    for name in TIMEOUT_JOBS:
        if name in _STATE["rescued"]:
            late.append(f"{name}: rescatado")
            continue
        submitted = _STATE["submitted_at"][name]
        record = records.read_record(_HANDLES[name].job_dir)
        for what, seconds in (("muerte", dead_at[name] - submitted),
                              ("final", final_at[name] - submitted),
                              ("duration_s", record.duration_s)):
            if seconds is None or seconds > TIMEOUT_MAX_S:
                late.append(f"{name}: {what} a {seconds} s")
    for name in ("running", "timeout", "timeout_catalog"):
        record = records.read_record(_HANDLES[name].job_dir)
        if record.cancel is None or record.cancel.forced or "cancelled" not in _types(name):
            late.append(f"{name}: no paró solo")
    return late


def _scenario(root: Path, builtin: object) -> None:
    """Lanza los trabajos del módulo en ``root``, los cancela y espera a que acaben,
    anotando en ``_STATE`` lo que miran las pruebas."""
    options = {"jobs_root": root, "package_dir": EXTENSION_DIR,
               "blender_python": Path(sys.executable)}
    single = runner.JobRunner(**options, max_subprocess=1)
    pair = runner.JobRunner(**options)
    contained = runner.JobRunner(**options)
    timed = runner.JobRunner(**options, max_subprocess=len(TIMEOUT_JOBS))

    # Los de tiempo máximo, primero: son los que más tardan.
    _submit("timeout", timed, _request("timeout", LONG_SUM, timeout_s=TIMEOUT_S,
                                       grace_s=GRACE_S))
    _submit("timeout_forced", timed,
            _request("timeout_forced", {**LONG_SUM, "ignore_cancel": True},
                     timeout_s=TIMEOUT_S, grace_s=GRACE_S))
    declared = dataclasses.replace(builtin, policy="subprocess", default_timeout_s=TIMEOUT_S)
    with mock.patch.dict(catalog._REGISTRY, {"selftest": declared}):
        _submit("timeout_catalog", timed,
                _request("timeout_catalog", LONG_SUM, grace_s=GRACE_S))

    _submit("running", single, _request("running", LONG_SUM))
    _submit("queued", single, _request("queued", LONG_SUM))
    _submit("ignore", pair, _request("ignore", {**LONG_SUM, "ignore_cancel": True},
                                     grace_s=GRACE_S))
    _submit("done", pair, _request("done", QUICK_SUM))
    failure = OSError(5, "Acceso denegado (simulado en la prueba)")
    with mock.patch.object(winjob.JobObject, "assign", side_effect=failure):
        _submit("uncontained", contained, _request("uncontained", LONG_SUM))

    # 1. En marcha: «running» e «ignore» ya enviaron su evento start; «done» terminó.
    _wait_for(lambda: "start" in _types("running") and "start" in _types("ignore")
              and _HANDLES["done"].result() is not None, "arranque de los trabajos")
    _STATE["queued_pid_before_cancel"] = _HANDLES["queued"].pid
    before = _state_bytes()

    # 2. Cancelaciones, todas a la vez.
    cancels: dict[str, object] = {}
    cancel_at: dict[str, float] = {}
    cancel_at["queued"] = time.monotonic()
    cancels["queued"] = single.cancel(_HANDLES["queued"].job_uid)
    _STATE["queued_state_after_cancel"] = _HANDLES["queued"].state
    cancel_at["running"] = time.monotonic()
    cancels["running"] = _HANDLES["running"].cancel()
    cancels["running_again"] = single.cancel(_HANDLES["running"].job_uid)
    _STATE["running_record_after_cancel"] = records.read_record(_HANDLES["running"].job_dir)
    _STATE["running_state_after_cancel"] = _HANDLES["running"].state
    cancel_at["ignore"] = time.monotonic()
    cancels["ignore"] = pair.cancel(_HANDLES["ignore"].job_uid)
    cancels["done"] = pair.cancel(_HANDLES["done"].job_uid)
    cancels["unknown"] = pair.cancel(UNKNOWN_UID)
    _STATE["done_state_unchanged"] = (
        (_HANDLES["done"].job_dir.path / records.RECORD_FILE).read_bytes() == before["done"]
    )
    _STATE["cancels"] = cancels
    _STATE["cancel_at"] = cancel_at

    # 3. Hasta que todo acaba, apuntando cuándo deja de existir cada proceso y cuándo
    #    llega su final.
    #    Un trabajo de tiempo máximo que siga en marcha al pasar RESCUE_S se cancela.
    dead_at: dict[str, float] = {}
    final_at: dict[str, float] = {}
    rescued: set[str] = set()
    submitted_at = _STATE["submitted_at"]

    def all_finished() -> bool:
        now = time.monotonic()
        for name in ("running", "ignore", *TIMEOUT_JOBS):
            if name not in dead_at and not _support.pid_alive(_HANDLES[name].pid):
                dead_at[name] = now
        for name, handle in _HANDLES.items():
            if name not in final_at and handle.result() is not None:
                final_at[name] = now
        for name in TIMEOUT_JOBS:
            late = now - submitted_at[name] > RESCUE_S
            if late and name not in final_at and name not in rescued:
                rescued.add(name)
                _RUNNERS[name].cancel(_HANDLES[name].job_uid)
        return len(final_at) == len(_HANDLES)

    _wait_for(all_finished, "final de los trabajos cancelados")
    _poll()
    _STATE["dead_at"] = dead_at
    _STATE["final_at"] = final_at
    _STATE["rescued"] = rescued

    # 4. Ya terminados: cancelar otra vez no cambia nada.
    finished = _state_bytes()
    updates_before = sum(len(updates) for updates in _UPDATES.values())
    _STATE["cancel_after_end"] = {
        name: (_RUNNERS[name].cancel(handle.job_uid), handle.cancel())
        for name, handle in _HANDLES.items()
    }
    for _ in range(3):
        _poll()
        time.sleep(POLL_S)
    _STATE["state_unchanged_after_end"] = _state_bytes() == finished
    _STATE["updates_after_end"] = sum(len(u) for u in _UPDATES.values()) - updates_before


def _job(name: str):
    handle = _HANDLES[name]
    return handle, handle.result(), records.read_record(handle.job_dir)


def _lines(name: str) -> list[dict]:
    """Las líneas de ``events.jsonl`` del trabajo, en orden (eventos y notas)."""
    path = _HANDLES[name].job_dir.events_file
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _notes(name: str) -> list[str]:
    return [line["note"] for line in _lines(name) if "note" in line]


class ScenarioTest(unittest.TestCase):
    """Spec 006, T48: el escenario se repite solo por una medida que no cupo."""

    def test_on_time_in_some_attempt(self):
        """RF-004-09 a RF-004-11: en alguna de las ``SCENARIO_ATTEMPTS`` veces, todas las
        medidas que la carga puede alargar cupieron en su plazo; si no, el mensaje dice cuáles
        no cupieron en cada vez."""
        lateness = _STATE["lateness"]
        self.assertLessEqual(len(lateness), SCENARIO_ATTEMPTS)
        self.assertEqual(lateness[-1], [], f"tarde en cada vez: {lateness}")


class CancelRunningTest(unittest.TestCase):
    """RF-004-09: un trabajo en curso que atiende la petición queda detenido en ≤ 2 s y
    «Cancelado»."""

    def test_stopped_within_two_seconds(self):
        """RF-004-09: el proceso del worker deja de existir, y el trabajo llega a su
        estado final, en ≤ 2 s desde que se pide cancelar."""
        cancel_at = _STATE["cancel_at"]["running"]
        self.assertTrue(_STATE["cancels"]["running"])
        self.assertLessEqual(_STATE["dead_at"]["running"] - cancel_at, STOP_MAX_S)
        self.assertLessEqual(_STATE["final_at"]["running"] - cancel_at, STOP_MAX_S)

    def test_marked_cancelled_not_forced(self):
        """RF-004-09: «Cancelado» (``job_cancelled``, sin «forzado») con su salida 3; la
        cancelación consta en ``state.json`` (motivo ``user``, no forzada) y sus
        resultados no se registran."""
        handle, result, record = _job("running")
        self.assertEqual((result.state, handle.state, record.state), ("cancelled",) * 3)
        self.assertEqual(result.error_code, "job_cancelled")
        expected = messages.render("job_cancelled", job=LABELS["running"], forced=False)
        self.assertEqual(result.error_text, expected)
        self.assertEqual(result.error_text, "Trabajo «Cancelación en curso» cancelado.")
        self.assertEqual(record.error.code, "job_cancelled")
        self.assertEqual(record.exit_code, runner.EXIT_CANCELLED)
        self.assertEqual((record.cancel.reason, record.cancel.forced), ("user", False))
        self.assertEqual(result.outputs, ())
        self.assertEqual(record.outputs, ())

    def test_the_worker_saw_the_request(self):
        """RF-004-09: el worker vio el centinela ``cancel`` y avisó con su evento
        ``cancelled`` («Cancelado en el trozo k de 40»); ``events.jsonl`` tiene la nota de
        la petición antes de la de fin."""
        handle, _, _ = _job("running")
        self.assertTrue(handle.job_dir.cancel_file.exists())
        updates = _UPDATES[handle.job_uid]
        cancelled = [event for update in updates for event in update.events
                     if event.type == "cancelled"]
        self.assertEqual(len(cancelled), 1)
        self.assertRegex(cancelled[0].msg, r"^Cancelado en el trozo \d+ de 40$")
        notes = _notes("running")
        self.assertIn("cancel_requested", notes)
        self.assertLess(notes.index("cancel_requested"), notes.index("finished"))
        self.assertNotIn("terminated", notes)

    def test_record_while_stopping(self):
        """RF-004-09: justo después de pedirlo, el trabajo sigue «En curso» y su
        ``state.json`` ya tiene la cancelación (hora, motivo ``user``, no forzada)."""
        record = _STATE["running_record_after_cancel"]
        self.assertEqual(_STATE["running_state_after_cancel"], "running")
        self.assertEqual(record.state, "running")
        self.assertIsNotNone(record.cancel.requested_at)
        self.assertEqual((record.cancel.reason, record.cancel.forced), ("user", False))


class ForcedCancelTest(unittest.TestCase):
    """RF-004-10: un worker que sigue vivo al vencer el plazo de gracia se termina (con
    sus hijos) en ≤ 1 s más y la cancelación consta como forzada."""

    def test_killed_after_the_grace_period(self):
        """RF-004-10: el proceso deja de existir después del plazo de gracia (1 s) y
        antes de 1 s más."""
        elapsed = _STATE["dead_at"]["ignore"] - _STATE["cancel_at"]["ignore"]
        self.assertTrue(_STATE["cancels"]["ignore"])
        self.assertGreaterEqual(elapsed, GRACE_S)
        self.assertLessEqual(elapsed, GRACE_S + KILL_EXTRA_S)
        self.assertLessEqual(_STATE["final_at"]["ignore"] - _STATE["cancel_at"]["ignore"],
                             GRACE_S + KILL_EXTRA_S)

    def test_marked_forced(self):
        """RF-004-10: «Cancelado» con «(forzado)» en el mensaje, ``cancel.forced`` en
        ``state.json`` y el código con que el lanzador termina el *Job Object* (no el 1 de
        ``Popen.kill``)."""
        handle, result, record = _job("ignore")
        self.assertEqual((result.state, handle.state, record.state), ("cancelled",) * 3)
        self.assertEqual(result.error_code, "job_cancelled")
        self.assertEqual(result.error_text,
                         messages.render("job_cancelled", job=LABELS["ignore"], forced=True))
        self.assertIn("(forzado)", result.error_text)
        self.assertEqual((record.cancel.reason, record.cancel.forced), ("user", True))
        self.assertEqual(record.exit_code, runner.EXIT_TERMINATED)
        self.assertNotEqual(runner.EXIT_TERMINATED, 1)

    def test_termination_is_logged(self):
        """RF-004-10: la terminación consta en ``events.jsonl`` (nota ``terminated``, entre
        la petición y el fin) y en ``job.log``, con el plazo de gracia; el worker no llegó
        a avisar de que paraba."""
        notes = _notes("ignore")
        self.assertLess(notes.index("cancel_requested"), notes.index("terminated"))
        self.assertLess(notes.index("terminated"), notes.index("finished"))
        terminated = next(line for line in _lines("ignore") if line.get("note") == "terminated")
        self.assertEqual(terminated["grace_s"], GRACE_S)
        log = _HANDLES["ignore"].job_dir.log_file.read_text(encoding="utf-8")
        self.assertIn("plazo de gracia de 1 s", log)
        self.assertNotIn("cancelled", _types("ignore"))


class CancelQueuedTest(unittest.TestCase):
    """RF-004-09: un trabajo en cola se cancela sin arrancar."""

    def test_cancelled_without_starting(self):
        """RF-004-09: estaba «En cola» sin proceso; ``cancel`` lo deja «Cancelado» al
        momento, sin proceso, sin hora de inicio y con la cancelación en ``state.json``."""
        handle, result, record = _job("queued")
        self.assertEqual(_STATE["state_after_submit"]["queued"], "queued")
        self.assertIsNone(_STATE["queued_pid_before_cancel"])
        self.assertTrue(_STATE["cancels"]["queued"])
        self.assertEqual(_STATE["queued_state_after_cancel"], "cancelled")
        self.assertEqual((result.state, record.state), ("cancelled", "cancelled"))
        self.assertEqual(result.error_text,
                         messages.render("job_cancelled", job=LABELS["queued"], forced=False))
        self.assertIsNone(handle.pid)
        self.assertIsNone(record.pid)
        self.assertIsNone(record.started_at)
        self.assertIsNone(record.exit_code)
        self.assertIsNone(result.duration_s)
        self.assertEqual((record.cancel.reason, record.cancel.forced), ("user", False))

    def test_never_launched(self):
        """RF-004-09: aunque el hueco de ``running`` quedó libre, nunca arrancó: sin nota de
        arranque, sin eventos del worker y sin centinela; ``on_finish`` una vez."""
        handle, result, _ = _job("queued")
        self.assertNotIn("launched", _notes("queued"))
        self.assertEqual(_notes("queued"), ["finished"])
        self.assertEqual(_types("queued"), [])
        self.assertFalse(handle.job_dir.cancel_file.exists())
        self.assertEqual(_FINISHED[handle.job_uid], [result])


class CancelTwiceTest(unittest.TestCase):
    """RF-004-09 (spec §8): cancelar dos veces, o un trabajo ya terminado, no tiene efecto
    adicional."""

    def test_second_cancel_while_stopping(self):
        """RF-004-09: la segunda petición sobre un trabajo que ya se está cancelando
        devuelve ``False`` y no cambia la hora de la primera."""
        self.assertFalse(_STATE["cancels"]["running_again"])
        first = _STATE["running_record_after_cancel"].cancel
        _, _, record = _job("running")
        self.assertEqual(record.cancel.requested_at, first.requested_at)

    def test_cancel_a_finished_job(self):
        """RF-004-09: cancelar un trabajo que ya terminó devuelve ``False``; sigue
        «Terminado», con el mismo ``state.json`` y un solo ``on_finish``."""
        handle, result, record = _job("done")
        self.assertFalse(_STATE["cancels"]["done"])
        self.assertTrue(_STATE["done_state_unchanged"])
        self.assertEqual((result.state, record.state), ("succeeded", "succeeded"))
        self.assertIsNone(record.cancel)
        self.assertEqual(_FINISHED[handle.job_uid], [result])

    def test_cancel_after_the_end(self):
        """RF-004-09: con todo terminado, ``cancel`` del lanzador y del *handle* devuelven
        ``False`` para cada trabajo, ningún ``state.json`` cambia y ``poll`` no informa de
        nada más."""
        for name, answers in _STATE["cancel_after_end"].items():
            with self.subTest(job=name):
                self.assertEqual(answers, (False, False))
        self.assertTrue(_STATE["state_unchanged_after_end"])
        self.assertEqual(_STATE["updates_after_end"], 0)
        for name, handle in _HANDLES.items():
            with self.subTest(job=name):
                self.assertEqual(len(_FINISHED[handle.job_uid]), 1)

    def test_unknown_job(self):
        """RF-004-09: un trabajo que el lanzador no conoce: ``False``."""
        self.assertFalse(_STATE["cancels"]["unknown"])


class ContainmentFailureTest(unittest.TestCase):
    """RF-004-10 (plan §8): si el worker no se puede asignar a su *Job Object*, no queda
    un worker que no se podría terminar con sus hijos."""

    def test_uncontained_worker_is_stopped(self):
        """RF-004-10: «Fallido» ``interpreter_failed`` con el motivo, y su proceso ya no
        existe."""
        handle, result, record = _job("uncontained")
        self.assertEqual(_STATE["state_after_submit"]["uncontained"], "failed")
        self.assertEqual((result.state, record.state), ("failed", "failed"))
        self.assertEqual(result.error_code, "interpreter_failed")
        self.assertIn("Job Object", result.error_text)
        self.assertIn("Acceso denegado (simulado en la prueba)", result.error_text)
        self.assertIsNotNone(handle.pid)
        self.assertTrue(_support.wait_until_dead(handle.pid, timeout_s=STOP_MAX_S))
        self.assertNotIn("launched", _notes("uncontained"))


class _TimeoutCase(unittest.TestCase):
    """Comprobaciones comunes de un trabajo que superó su tiempo máximo."""

    def assert_in_window(self, name: str, low_s: float) -> None:
        """No hubo que rescatarlo; su proceso dejó de existir y llegó «Tiempo agotado»
        entre ``low_s`` y 2 s + ``grace_s`` + 1 s desde que se lanzó (con el reloj de la
        prueba, desde antes de ``submit``, y con su duración en ``state.json``, desde que
        arrancó el proceso)."""
        self.assertNotIn(name, _STATE["rescued"])
        submitted = _STATE["submitted_at"][name]
        _, _, record = _job(name)
        for what, seconds in (("muerte", _STATE["dead_at"][name] - submitted),
                              ("final", _STATE["final_at"][name] - submitted),
                              ("duration_s", record.duration_s)):
            with self.subTest(medida=what):
                self.assertGreaterEqual(seconds, low_s)
                self.assertLessEqual(seconds, TIMEOUT_MAX_S)

    def assert_timed_out(self, name: str, *, forced: bool) -> None:
        """«Tiempo agotado» (``job_timeout``) con los 2 s en el mensaje, en el resultado, en
        el *handle* y en ``state.json``; la cancelación consta con motivo ``timeout``;
        ningún resultado se registra."""
        handle, result, record = _job(name)
        self.assertEqual((result.state, handle.state, record.state), ("timed_out",) * 3)
        expected = messages.render("job_timeout", job=LABELS[name], seconds=TIMEOUT_S)
        self.assertEqual(expected, f"El trabajo «{LABELS[name]}» superó su tiempo máximo "
                                   "de 2 s y se ha detenido.")
        self.assertEqual((result.error_code, result.error_text), ("job_timeout", expected))
        self.assertEqual(handle.message, expected)
        self.assertEqual((record.error.code, record.error.text), ("job_timeout", expected))
        self.assertEqual(record.error.values["seconds"], TIMEOUT_S)
        self.assertEqual((record.cancel.reason, record.cancel.forced), ("timeout", forced))
        self.assertEqual(result.outputs, ())
        self.assertEqual(record.outputs, ())
        self.assertEqual(_FINISHED[handle.job_uid], [result])

    def assert_logged(self, name: str) -> None:
        """La petición de parar consta en ``events.jsonl`` (motivo ``timeout``, con el
        tiempo máximo) antes del fin, y en ``job.log`` con el estado final."""
        notes = _notes(name)
        self.assertLess(notes.index("cancel_requested"), notes.index("finished"))
        requested = next(line for line in _lines(name)
                         if line.get("note") == "cancel_requested")
        self.assertEqual((requested["reason"], requested["timeout_s"]), ("timeout", TIMEOUT_S))
        log = _HANDLES[name].job_dir.log_file.read_text(encoding="utf-8")
        self.assertIn("se pidió cancelar el trabajo por su tiempo máximo de 2 s", log)
        self.assertIn("el trabajo termina «Tiempo agotado»", log)


class TimeoutTest(_TimeoutCase):
    """RF-004-11: un trabajo con ``timeout_s`` = 2 que nadie cancela se detiene como en una
    cancelación al superarlo y queda «Tiempo agotado», con los 2 s en el mensaje."""

    def test_timed_out_within_the_window(self):
        """RF-004-11: acaba entre 2 s y 2 s + ``grace_s`` + 1 s (4 s) desde que arrancó."""
        self.assert_in_window("timeout", TIMEOUT_S)

    def test_marked_timed_out(self):
        """RF-004-11: «Tiempo agotado» (no «Cancelado») con el mensaje que cita los 2 s; el
        worker atendió la petición (salida 3), así que no es forzado; el tiempo declarado
        en la petición manda sobre el de su tipo de trabajo (120 s)."""
        self.assert_timed_out("timeout", forced=False)
        _, _, record = _job("timeout")
        self.assertEqual(record.exit_code, runner.EXIT_CANCELLED)
        request = protocol.read_request(_HANDLES["timeout"].job_dir)
        self.assertEqual(request.timeout_s, TIMEOUT_S)

    def test_stopped_like_a_cancellation(self):
        """RF-004-11: se le pidió parar con el centinela ``cancel`` y el worker lo vio
        («Cancelado en el trozo k de 40»), sin terminarlo; consta en los registros."""
        self.assertTrue(_HANDLES["timeout"].job_dir.cancel_file.exists())
        cancelled = [event for update in _UPDATES[_HANDLES["timeout"].job_uid]
                     for event in update.events if event.type == "cancelled"]
        self.assertEqual(len(cancelled), 1)
        self.assertRegex(cancelled[0].msg, r"^Cancelado en el trozo \d+ de 40$")
        self.assertNotIn("terminated", _notes("timeout"))
        self.assert_logged("timeout")


class ForcedTimeoutTest(_TimeoutCase):
    """RF-004-10, RF-004-11: un trabajo que supera su tiempo máximo y no atiende la
    petición de parar se termina al vencer su plazo de gracia y queda «Tiempo agotado»."""

    def test_killed_after_timeout_and_grace(self):
        """RF-004-10, RF-004-11: deja de existir después de 2 s + ``grace_s`` (3 s) y llega
        a su estado final antes de 4 s."""
        self.assert_in_window("timeout_forced", TIMEOUT_S + GRACE_S)

    def test_marked_timed_out_forced(self):
        """RF-004-10, RF-004-11: «Tiempo agotado» con los 2 s en el mensaje, la cancelación
        forzada en ``state.json`` y el código con que el lanzador termina el *Job Object*;
        el worker no llegó a avisar de que paraba."""
        self.assert_timed_out("timeout_forced", forced=True)
        _, _, record = _job("timeout_forced")
        self.assertEqual(record.exit_code, runner.EXIT_TERMINATED)
        self.assertNotIn("cancelled", _types("timeout_forced"))

    def test_termination_is_logged(self):
        """RF-004-10, RF-004-11: nota ``terminated`` (motivo ``timeout``) entre la petición
        y el fin, y la terminación en ``job.log``."""
        notes = _notes("timeout_forced")
        self.assertLess(notes.index("cancel_requested"), notes.index("terminated"))
        self.assertLess(notes.index("terminated"), notes.index("finished"))
        terminated = next(line for line in _lines("timeout_forced")
                          if line.get("note") == "terminated")
        self.assertEqual((terminated["reason"], terminated["grace_s"]), ("timeout", GRACE_S))
        self.assert_logged("timeout_forced")
        log = _HANDLES["timeout_forced"].job_dir.log_file.read_text(encoding="utf-8")
        self.assertIn("plazo de gracia de 1 s", log)


class CatalogTimeoutTest(_TimeoutCase):
    """RF-004-11: sin tiempo máximo en la petición se aplica el que declara su tipo de
    trabajo."""

    def test_catalog_timeout_applies(self):
        """RF-004-11: la petición no traía ``timeout_s``; su tipo declaraba 2 s, que quedan
        en ``request.json``, y el trabajo acaba «Tiempo agotado» con los 2 s en el mensaje
        dentro de la ventana."""
        request = protocol.read_request(_HANDLES["timeout_catalog"].job_dir)
        self.assertEqual(request.timeout_s, TIMEOUT_S)
        self.assert_timed_out("timeout_catalog", forced=False)
        self.assert_in_window("timeout_catalog", TIMEOUT_S)


class DefaultTimeoutTest(unittest.TestCase):
    """RF-004-11: si ni la petición ni su tipo de trabajo declaran un tiempo máximo, se
    aplican 3600 s."""

    def test_default_is_3600_seconds(self):
        """RF-004-11: un tipo de trabajo que no declara tiempo máximo tiene 3600 s, y una
        petición suya sin ``timeout_s`` queda con 3600 s en ``request.json`` (sin
        arrancar)."""
        info = catalog.WorkerInfo("selftest", "Self-test", policy="subprocess")
        self.assertEqual(info.default_timeout_s, 3600.0)
        self.assertEqual(protocol.DEFAULT_TIMEOUT_S, 3600.0)
        tmp = _support.temp_jobs_root()
        root = tmp.__enter__()
        self.addCleanup(tmp.__exit__, None, None, None)
        job_runner = runner.JobRunner(jobs_root=root, package_dir=EXTENSION_DIR,
                                      blender_python=Path(sys.executable))
        with mock.patch.dict(catalog._REGISTRY, clear=True):
            catalog.register_worker(info)
            request = protocol.new_request("selftest", label="Sin tiempo máximo",
                                           owner="jobs", params=QUICK_SUM)
            self.assertIsNone(request.timeout_s)
            folder = job_runner.prepare(request)
        self.assertEqual(protocol.read_request(folder).timeout_s, 3600.0)
        self.assertEqual(records.read_record(folder).state, "queued")


if __name__ == "__main__":
    unittest.main()
