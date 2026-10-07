# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que el lanzador cuenta de sus trabajos a la interfaz (spec 004, T19; RF-004-06,
RF-004-07; plan 004 §5.3.1 y §5.4.4).

``JobRunner.snapshots()`` devuelve, por orden de llegada, una ``JobSnapshot`` inmutable de
cada trabajo (nombre, tipo, estado, ejecutor, avance, último mensaje, duración, intérprete,
error y si se pidió cancelarlo), y ``JobRunner.active_count()`` cuántos están en cola o en
curso: es lo que dibuja la barra de estado (``bl/ops/jobs.py``, ``JobMonitor``).

Dos trabajos en hilo de un tipo de prueba que espera a que la prueba lo suelte, con un
solo hueco de hilo (el segundo espera en la cola) y un reloj del lanzador que mueve la
prueba (las duraciones son exactas).
"""

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
protocol = import_geoblender("jobs.protocol")
records = import_geoblender("jobs.records")
runner = import_geoblender("jobs.runner")

WORKER = "gbtest_snapshot"
DEADLINE_S = 10.0
POLL_S = 0.02
START = 100.0


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


if __name__ == "__main__":
    unittest.main()
