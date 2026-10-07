# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que el lanzador cuenta de sus trabajos a la interfaz (spec 004, T19; RF-004-06,
RF-004-07; plan 004 §5.3.1 y §5.4.4).

``JobRunner.snapshots()`` devuelve, por orden de llegada, una ``JobSnapshot`` inmutable de
cada trabajo (nombre, tipo, estado, ejecutor, avance, último mensaje, duración, intérprete,
error, si se pidió cancelarlo, su registro y si ya se incorporó; T20, RF-004-08), y
``JobRunner.active_count()`` cuántos están en cola o en curso: es lo que dibujan la barra de
estado (``bl/ops/jobs.py``, ``JobMonitor``) y la lista de trabajos (``bl/ui/jobs.py``).

Dos trabajos en hilo de un tipo de prueba que espera a que la prueba lo suelte, con un
solo hueco de hilo (el segundo espera en la cola) y un reloj del lanzador que mueve la
prueba (las duraciones son exactas).

T38 — ``JobRunner.stored_snapshots()`` (RF-004-08, RF-004-13): la lista de trabajos enseña
también los que ya están en la carpeta de trabajos sin ser del lanzador (de una sesión
anterior, o de antes de desactivar Geoblender): los de su raíz y los de otras raíces (la de
sin proyecto, la de los de diagnóstico), con lo que dice su ``state.json`` y su último
avance de ``events.jsonl``. Los que constaban en cola o en curso quedan antes
«Interrumpido» (``records.mark_interrupted``); los del lanzador no salen dos veces ni se
tocan. Las carpetas de otra sesión se escriben a mano.
"""

import datetime as dt
import json
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
messages = import_geoblender("jobs.messages")
paths = import_geoblender("jobs.paths")
protocol = import_geoblender("jobs.protocol")
records = import_geoblender("jobs.records")
runner = import_geoblender("jobs.runner")
timeutil = import_geoblender("core.timeutil")

WORKER = "gbtest_snapshot"
DEADLINE_S = 10.0
POLL_S = 0.02
START = 100.0
STARTED = dt.datetime(2026, 10, 7, 9, 0, 0, tzinfo=dt.UTC)


class _Gates:
    """El cálculo del tipo de prueba: avisa del 25 % y espera a que la prueba suelte su
    trabajo (por su nombre)."""

    def __init__(self) -> None:
        self.events: dict[str, threading.Event] = {}

    def __getitem__(self, label: str) -> threading.Event:
        return self.events.setdefault(label, threading.Event())

    def release_all(self) -> None:
        for event in list(self.events.values()):
            event.set()

    def run(self, ctx: object) -> dict[str, object]:
        ctx.progress(0.25, "Paso 1 de 4")
        while not self[ctx.request.label].wait(POLL_S):
            ctx.check_cancelled()
        return {"ok": True}


class SnapshotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = [START]
        self.gates = _Gates()
        info = catalog.WorkerInfo(WORKER, "Snapshot test", policy="auto",
                                  estimate_s=lambda _params: 0.1, run=self.gates.run)
        registry = mock.patch.dict(catalog._REGISTRY, {WORKER: info}, clear=True)
        registry.start()
        self.addCleanup(registry.stop)
        folder = self.enterContext(_support.temp_jobs_root())
        self.runner = runner.JobRunner(
            jobs_root=folder, package_dir=EXTENSION_DIR, blender_python=Path(sys.executable),
            max_inprocess=1,
            clock=lambda: self.now[0],
        )
        self.addCleanup(self.gates.release_all)
        self.addCleanup(self.runner.shutdown, timeout_s=2.0)

    def submit(self, label: str):
        request = protocol.new_request(WORKER, label=label, owner="jobs")
        return self.runner.submit(request)

    def poll_until(self, condition) -> None:
        deadline = time.monotonic() + DEADLINE_S
        while not condition():
            self.assertLess(time.monotonic(), deadline, "el trabajo no avanzó a tiempo")
            self.runner.poll()
            time.sleep(POLL_S)

    def by_name(self) -> dict[str, object]:
        return {snapshot.name: snapshot for snapshot in self.runner.snapshots()}

    def test_active_jobs_in_order(self) -> None:
        """RF-004-06: por orden de llegada, el que corre (nombre, tipo, ejecutor, avance,
        último mensaje, duración desde que arrancó e intérprete) y el que espera en la cola
        (sin avance ni duración); los dos cuentan como activos."""
        self.assertEqual(self.runner.active_count(), 0)
        self.assertEqual(self.runner.snapshots(), [])
        first = self.submit("Primero")
        second = self.submit("Segundo")
        self.assertEqual(self.runner.active_count(), 2)
        self.poll_until(lambda: first.message == "Paso 1 de 4")
        self.now[0] = START + 1.5
        snapshots = self.runner.snapshots()
        self.assertEqual([s.job_uid for s in snapshots], [first.job_uid, second.job_uid])
        running, queued = snapshots
        self.assertEqual((running.name, running.worker, running.state, running.executor),
                         ("Primero", WORKER, "running", "inprocess"))
        self.assertEqual((running.frac, running.message), (0.25, "Paso 1 de 4"))
        self.assertEqual(running.duration_s, 1.5)
        self.assertEqual(running.interpreter.kind, "blender")
        self.assertIsNone(running.error)
        self.assertFalse(running.cancel_requested)
        self.assertTrue(running.active)
        self.assertEqual((queued.name, queued.state, queued.frac, queued.message),
                         ("Segundo", "queued", 0.0, ""))
        self.assertIsNone(queued.duration_s)
        self.assertIsNone(queued.interpreter)
        self.assertTrue(queued.active)
        self.assertEqual(self.runner.active_count(), 2)

    def test_final_jobs_keep_their_outcome(self) -> None:
        """RF-004-07: el que terminó conserva su estado, avance completo y duración en s;
        el cancelado, su estado, que se pidió cancelarlo y su error del §8 (código y texto
        en español); ninguno cuenta como activo. Una foto no cambia con el trabajo."""
        first = self.submit("Primero")
        second = self.submit("Segundo")
        self.poll_until(lambda: first.message == "Paso 1 de 4")
        before = self.runner.snapshots()[0]
        self.now[0] = START + 2.5
        self.gates["Primero"].set()
        self.poll_until(lambda: second.state == "running")
        self.assertTrue(second.cancel())
        self.poll_until(lambda: second.result() is not None)
        done = self.by_name()
        self.assertEqual((done["Primero"].state, done["Primero"].frac), ("succeeded", 1.0))
        self.assertEqual(done["Primero"].duration_s, 2.5)
        self.assertIsNone(done["Primero"].error)
        self.assertFalse(done["Primero"].active)
        cancelled = done["Segundo"]
        self.assertEqual(cancelled.state, "cancelled")
        self.assertTrue(cancelled.cancel_requested)
        self.assertEqual(cancelled.error.code, "job_cancelled")
        self.assertEqual(cancelled.error.text, "Trabajo «Segundo» cancelado.")
        self.assertEqual(cancelled.message, cancelled.error.text)
        self.assertFalse(cancelled.active)
        self.assertEqual(self.runner.active_count(), 0)
        self.assertEqual((before.state, before.frac), ("running", 0.25))
        self.assertIn(before.state, records.ACTIVE_STATES)

    def test_log_file_and_ingested(self) -> None:
        """RF-004-08: la foto lleva el registro del trabajo (el ``job.log`` de su carpeta, el
        que abre el botón «Registro» de la lista) y si un módulo ya incorporó sus resultados
        (entonces la lista no ofrece descartarlo); la foto anterior no cambia."""
        first = self.submit("Primero")
        self.gates["Primero"].set()
        self.poll_until(lambda: first.result() is not None)
        done = self.by_name()["Primero"]
        self.assertEqual(done.log_file, first.job_dir.log_file)
        self.assertTrue(done.log_file.is_file())
        self.assertFalse(done.ingested)
        self.runner.mark_ingested(first.job_uid)
        self.assertTrue(self.by_name()["Primero"].ingested)
        self.assertFalse(done.ingested)
        self.assertEqual(done.folder, first.job_dir.path)
        self.assertFalse(done.stored)


def _stored_job(root: Path, label: str, state: str, *, progress: float | None = None,
                cancel: str | None = None) -> Path:
    """La carpeta de un trabajo de otra sesión, escrita a mano: su petición, su
    ``state.json`` en ``state`` (en curso desde :data:`STARTED`, o terminado 30 s después),
    ``job.log`` y, con ``progress``, un evento de avance en ``events.jsonl``."""
    request = protocol.new_request("selftest", label=label, owner="jobs",
                                   environment="blender", timeout_s=60)
    folder = paths.job_dir(root, request.job_uid).create()
    protocol.write_request(folder, request)
    final = state in records.FINAL_STATES
    ended = STARTED + dt.timedelta(seconds=30)
    error = None
    if state not in ("running", "succeeded"):
        error = records.ErrorInfo.from_job_error(messages.JobError(
            "job_interrupted" if state == "interrupted" else "worker_crashed", job=label,
            exit_code=1))
    records.write_record(folder, records.JobRecord(
        job_uid=request.job_uid, worker="selftest", label=label, owner="jobs", state=state,
        executor="subprocess", queued_at=timeutil.format_utc(STARTED),
        started_at=timeutil.format_utc(STARTED),
        ended_at=timeutil.format_utc(ended) if final else None,
        duration_s=30.0 if final else None, exit_code=0 if state == "succeeded" else None,
        interpreter=records.InterpreterInfo(kind="blender", python="3.13.9"),
        error=error, cancel=None if cancel is None else records.CancelInfo(
            requested_at=timeutil.format_utc(STARTED), reason=cancel),
    ))
    lines = [json.dumps({"note": "launched", "ts": STARTED.timestamp()}).encode() + b"\n"]
    if progress is not None:
        event = protocol.JobEvent.progress(progress, f"Trozo de prueba {progress}",
                                           ts=STARTED.timestamp() + 2.0)
        lines.append(protocol.encode_event(event))
    folder.events_file.write_bytes(b"".join(lines))
    folder.log_file.write_bytes(b"Geoblender: arranque del worker\n")
    return folder.path


class StoredSnapshotsTest(unittest.TestCase):
    """Una raíz de trabajos con trabajos de otra sesión y del lanzador, y otra raíz (la de
    sin proyecto) con más trabajos de otra sesión."""

    def setUp(self) -> None:
        self.gates = _Gates()
        info = catalog.WorkerInfo(WORKER, "Snapshot test", policy="auto",
                                  estimate_s=lambda _params: 0.1, run=self.gates.run)
        registry = mock.patch.dict(catalog._REGISTRY, {WORKER: info}, clear=True)
        registry.start()
        self.addCleanup(registry.stop)
        base = self.enterContext(_support.temp_jobs_root())
        self.root = base / "proyecto"
        self.other = base / "sin_proyecto"
        self.runner = runner.JobRunner(
            jobs_root=self.root, package_dir=EXTENSION_DIR, blender_python=Path(sys.executable),
            max_inprocess=2,
        )
        self.addCleanup(self.gates.release_all)
        self.addCleanup(self.runner.shutdown, timeout_s=2.0)
        self.crashed = _stored_job(self.root, "Caído", "running", progress=0.4)
        self.done = _stored_job(self.root, "Hecho antes", "succeeded", progress=0.9)
        self.closed = _stored_job(self.other, "Cerrado al desactivar", "interrupted",
                                  progress=0.3, cancel="shutdown")
        self.gates["Terminado aquí"].set()
        self.finished = self.submit("Terminado aquí")
        self.busy = self.submit("En marcha aquí")
        self.poll_until(lambda: self.finished.result() is not None
                        and self.busy.message == "Paso 1 de 4")

    def submit(self, label: str):
        return self.runner.submit(protocol.new_request(WORKER, label=label, owner="jobs"))

    def poll_until(self, condition) -> None:
        deadline = time.monotonic() + DEADLINE_S
        while not condition():
            self.assertLess(time.monotonic(), deadline, "el trabajo no avanzó a tiempo")
            self.runner.poll()
            time.sleep(POLL_S)

    def stored(self) -> dict[str, object]:
        found = self.runner.stored_snapshots(extra_roots=[self.other])
        by_name = {snapshot.name: snapshot for snapshot in found}
        self.assertEqual(len(by_name), len(found), "un trabajo sale dos veces")
        return by_name

    def test_stored_jobs_once_and_interrupted(self) -> None:
        """RF-004-08, RF-004-13, RF-004-17: salen, por identificador, los trabajos de la
        raíz y de las otras raíces que no son del lanzador (ni aunque su raíz se pase otra
        vez), con su nombre, estado, duración, intérprete, error, cancelación, carpeta,
        ``job.log`` y último avance (el de ``events.jsonl``; completo si terminó bien), como
        guardados. El que su ``state.json`` deja en curso sin estar en el lanzador (una
        caída previa) queda antes «Interrumpido» en su registro, con el avance al que
        llegó, y su ``job.log`` dice que se marcó al abrir la lista; leer otra vez no cambia
        nada. Los del lanzador no salen ni se tocan; una raíz que no existe no tiene
        ninguno y no se crea; una que no es una ruta completa es ``ValueError`` sin marcar
        nada. «Descartar» uno guardado de otra raíz (``JobRunner.purge`` con ``jobs_root``)
        borra solo su carpeta."""
        with self.assertRaises(ValueError):
            self.runner.stored_snapshots(extra_roots=[Path("relativa")])
        self.assertEqual(records.read_record(self.crashed).state, "running")
        missing = self.other.parent / "no_existe"
        found = self.runner.stored_snapshots(extra_roots=[self.root, self.other, missing])
        self.assertEqual([s.job_uid for s in found], sorted(s.job_uid for s in found))
        stored = {snapshot.name: snapshot for snapshot in found}
        self.assertEqual(len(stored), len(found), "un trabajo sale dos veces")
        self.assertEqual(set(stored), {"Caído", "Hecho antes", "Cerrado al desactivar"})
        self.assertFalse(missing.exists())
        closed = stored["Cerrado al desactivar"]
        self.assertEqual((closed.state, closed.worker, closed.executor),
                         ("interrupted", "selftest", "subprocess"))
        self.assertAlmostEqual(closed.frac, 0.3)
        self.assertEqual((closed.duration_s, closed.interpreter.kind), (30.0, "blender"))
        self.assertEqual(closed.error.code, "job_interrupted")
        self.assertEqual(closed.message, closed.error.text)
        self.assertTrue(closed.cancel_requested)
        self.assertEqual((closed.folder, closed.log_file),
                         (self.closed, self.closed / "job.log"))
        self.assertTrue(closed.stored)
        self.assertFalse(closed.active)
        done = stored["Hecho antes"]
        self.assertEqual((done.state, done.frac, done.error), ("succeeded", 1.0, None))
        self.assertEqual((done.message, done.ingested), ("Trozo de prueba 0.9", False))
        crashed = stored["Caído"]
        self.assertEqual((crashed.state, crashed.error.code),
                         ("interrupted", "job_interrupted"))
        self.assertAlmostEqual(crashed.frac, 0.4)
        self.assertFalse(crashed.active)
        self.assertEqual(records.read_record(self.crashed).state, "interrupted")
        log = (self.crashed / "job.log").read_text(encoding="utf-8").splitlines()[-1]
        self.assertIn("al abrir la lista de trabajos", log)
        self.assertEqual(records.read_record(self.busy.job_dir).state, "running")
        self.assertEqual(self.busy.state, "running")
        self.assertEqual({s.name for s in self.runner.snapshots()},
                         {"Terminado aquí", "En marcha aquí"})
        before = (self.crashed / records.RECORD_FILE).read_bytes()
        self.assertEqual(self.stored()["Caído"], crashed)
        self.assertEqual((self.crashed / records.RECORD_FILE).read_bytes(), before)
        report = self.runner.purge(older_than_days=None, all_finished=True,
                                   only=(self.closed.name,), jobs_root=self.other)
        self.assertEqual(report.removed, (self.closed.name,))
        self.assertFalse(self.closed.exists())
        self.assertTrue(self.done.exists())
        self.assertNotIn("Cerrado al desactivar", self.stored())


if __name__ == "__main__":
    unittest.main()
