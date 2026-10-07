# SPDX-License-Identifier: GPL-3.0-or-later
"""El seguimiento de los trabajos dentro de Blender, con carga (spec 004, T35; RNF-004-03,
RNF-004-04; plan 004 §5.4.4 y §7).

Se ejecuta con ``tools/check.py --rendimiento`` (o, a mano, con
``tools/run_blender_tests.py -- --carpeta tests/rendimiento/blender --patron
"perf_jobs*.py"``). Cuatro trabajos reales en proceso aparte a la vez (el máximo de la
preferencia), con el Python de Blender, de un worker de prueba (en una copia del paquete)
que durante 6 s emite 100 notas de registro por segundo y, con cada una, su avance «Paso k
de N» (el contexto del worker deja los avances en 10 por segundo). Se lanzan de uno en uno,
uno antes de cada sondeo, como los lanzaría una persona. En ``blender -b`` los
temporizadores no se ejecutan: la prueba hace de temporizador y llama al ``tick`` del
monitor (``JobMonitor.tick``: sondeo del lanzador, lo que enseña la barra de estado y su
redibujo) cuando pasa el intervalo que devolvió el anterior (0,25 s); después de cada uno
dibuja el campo «jobs» de la barra de estado con un *layout* simulado.

- RNF-004-03: mientras los 4 están en curso (antes y después del sondeo; también el que
  recibe el ``start`` del cuarto), cada ``tick`` dura ≤ 5 ms (``time.perf_counter``), y
  cada trabajo emitió ≥ 100 eventos por segundo. Los sondeos en que acaba un trabajo (su
  ``state.json`` final y su ``job.log``) no son de esa carga: su cifra sale en la línea,
  sin presupuesto.
- RNF-004-04: cada avance del trabajo que enseña la barra (el más antiguo en curso) está en
  la barra dibujada (su «Paso k de N», o uno posterior) ≤ 0,5 s después de emitirse: la
  hora del evento (``ts``, ``time.time()`` en el worker) frente a la del dibujo
  (``time.time()`` en Blender). La comprobación manual M1 lo ve en la ventana.
"""

import importlib
import json
import platform
import re
import shutil
import statistics
import sys
import tempfile
import time
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import FakeLayout

WORKER = "gbtest_chatty"
JOBS = 4
"""Trabajos a la vez: el máximo de la preferencia (1–4, RF-004-04)."""
RATE = 100
"""Notas de registro por segundo de cada trabajo (más sus avances)."""
SECONDS = 6
EVENTS = RATE * SECONDS
TICK_BUDGET_S = 0.005  # RNF-004-03: cada sondeo ≤ 5 ms
MIN_EVENTS_PER_S = 100  # RNF-004-03: con 100 eventos por segundo de cada trabajo
LATENCY_BUDGET_S = 0.5  # RNF-004-04: el avance en la barra ≤ 0,5 s después de emitirse
MIN_TICKS = 10
MIN_PROGRESS = 20
DEADLINE_S = 60.0
STEP = re.compile(r"Paso (\d+) de \d+")

# Worker de prueba que se añade a la copia del paquete.
WORKER_SOURCE = '''# SPDX-License-Identifier: GPL-3.0-or-later
"""Worker de las pruebas de rendimiento del seguimiento: «rate» notas de registro por
segundo, cada una con su avance, hasta «events»."""

import time


def main(ctx):
    rate = float(ctx.request.params["rate"])
    events = int(ctx.request.params["events"])
    started = time.perf_counter()
    for index in range(1, events + 1):
        delay = started + index / rate - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        ctx.log("debug", f"Nota {index} de {events}")
        ctx.progress(index / events, f"Paso {index} de {events}")
    return {"events": events}
'''


@dataclass(frozen=True)
class Tick:
    """Un sondeo: lo que duró, la hora en que se dibujó la barra después, los trabajos en
    curso antes y después, el trabajo que enseña la barra y su «Paso k» en ella."""

    duration_s: float
    seen_at: float
    running_before: int
    running_after: int
    current: str | None
    step: int


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _shown_step(layout: FakeLayout) -> int:
    """El ``k`` del «Paso k de N» que dibuja la barra (0 si no dibuja ninguno)."""
    for item in layout.of_kind("label"):
        match = STEP.fullmatch(item.text or "")
        if match:
            return int(match.group(1))
    return 0


def _ms(value: float) -> str:
    return f"{value * 1000:.2f}".replace(".", ",")


def _seconds(value: float) -> str:
    return f"{value:.3f}".replace(".", ",")


def _number(value: float) -> str:
    """Un número con dos decimales y coma decimal (0,25)."""
    return f"{value:.2f}".replace(".", ",")


def _report(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


class MonitorTickTest(unittest.TestCase):
    """Cuatro trabajos que emiten 100 eventos por segundo, seguidos con el ``tick`` del
    monitor a su ritmo."""

    ticks: list[Tick]

    @classmethod
    def setUpClass(cls) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="gb4-", ignore_cleanup_errors=True)
        cls.addClassCleanup(tmp.cleanup)  # después de deshabilitar: ficheros cerrados
        base = Path(tmp.name)
        blender_ext.unload()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.unload)
        ops = _module("bl.ops.jobs")
        ui = _module("bl.ui.jobs")
        catalog = _module("jobs.catalog")
        protocol = _module("jobs.protocol")
        runner = _module("jobs.runner")
        events_file = _module("jobs.paths").EVENTS_FILE

        copy = base / "pkg"
        shutil.copytree(
            Path(sys.modules[module_name()].__file__).parent, copy,
            ignore=shutil.ignore_patterns("__pycache__", "*.py[cod]", "bl", "resources",
                                          "thirdparty", "wheels"),
        )
        (copy / "workers" / f"{WORKER}.py").write_bytes(WORKER_SOURCE.encode("utf-8"))
        catalog.register_worker(catalog.WorkerInfo(WORKER, "Chatty test job",
                                                   policy="subprocess",
                                                   default_timeout_s=120.0))
        cls.addClassCleanup(catalog.unregister_worker, WORKER)

        job_runner = runner.JobRunner(jobs_root=base / "jobs", package_dir=copy,
                                      blender_python=Path(sys.executable),
                                      max_subprocess=JOBS)
        monitor = ops.JobMonitor()
        patch = mock.patch.object(ops, "MONITOR", monitor)
        patch.start()
        cls.addClassCleanup(patch.stop)
        cls.addClassCleanup(monitor.stop)
        monitor.attach(job_runner)
        cls.addClassCleanup(job_runner.shutdown, timeout_s=3.0)

        requests = [
            protocol.new_request(WORKER, label=f"Trabajo {index}", owner="jobs",
                                 params={"rate": RATE, "events": EVENTS})
            for index in range(1, JOBS + 1)
        ]
        cls.handles = []
        ticks: list[Tick] = []
        interval = ops.TICK_S  # first_interval del temporizador
        deadline = time.monotonic() + DEADLINE_S
        while (len(cls.handles) < JOBS
               or not all(handle.result() is not None for handle in cls.handles)):
            if time.monotonic() > deadline:
                raise AssertionError(f"los trabajos no acabaron en {DEADLINE_S} s")
            if len(cls.handles) < JOBS:  # de uno en uno, uno por sondeo
                cls.handles.append(monitor.submit(requests[len(cls.handles)]))
            time.sleep(interval)
            running = sum(1 for s in job_runner.snapshots() if s.state == "running")
            started = time.perf_counter()
            returned = monitor.tick()
            duration = time.perf_counter() - started
            layout = FakeLayout()
            ui.draw(layout, None)
            seen_at = time.time()
            view = monitor.view()
            after = sum(1 for s in job_runner.snapshots() if s.state == "running")
            ticks.append(Tick(duration, seen_at, running, after,
                              None if view.current is None else view.current.job_uid,
                              _shown_step(layout)))
            interval = ops.TICK_S if returned is None else returned
        cls.ticks = ticks
        cls.tick_s = ops.TICK_S
        cls.events = {}
        for handle in cls.handles:
            lines = (handle.job_dir.path / events_file).read_text(encoding="utf-8")
            cls.events[handle.job_uid] = [item for item in map(json.loads, lines.splitlines())
                                          if "t" in item]
        cls.where = (f"Blender {bpy.app.version_string}, Python {platform.python_version()}; "
                     f"workers con el Python de Blender")

    def check_succeeded(self) -> None:
        """Los cuatro trabajos acabaron bien."""
        for handle in self.handles:
            result = handle.result()
            with self.subTest(trabajo=handle.job_uid):
                self.assertEqual(result.state, "succeeded",
                                 f"{result.error_code}: {result.error_text}")
                self.assertEqual(dict(result.summary), {"events": EVENTS})

    def test_tick_with_four_jobs_of_100_events_per_second(self) -> None:
        """RNF-004-03: con 4 trabajos en curso que emiten ≥ 100 eventos por segundo cada
        uno, cada sondeo periódico del seguimiento (``tick``) dura ≤ 5 ms."""
        self.check_succeeded()
        rates = []
        for events in self.events.values():
            start = next(e["ts"] for e in events if e["t"] == "start")
            end = next(e["ts"] for e in events if e["t"] == "result")
            emitted = sum(1 for e in events if start < e["ts"] < end)
            rates.append(emitted / (end - start))
        steady = [tick for tick in self.ticks
                  if tick.running_before == JOBS and tick.running_after == JOBS]
        self.assertGreaterEqual(len(steady), MIN_TICKS)
        durations = [tick.duration_s for tick in steady]
        first, last = steady[0].seen_at, steady[-1].seen_at
        per_tick = sum(1 for events in self.events.values() for e in events
                       if first < e["ts"] <= last) / (len(steady) - 1)
        every = [tick.duration_s for tick in self.ticks]
        ending = [tick.duration_s for tick in self.ticks
                  if tick.running_after < tick.running_before]
        _report(f"RNF-004-03: cada sondeo del seguimiento (tick: lanzador, barra de estado y "
                f"redibujo, cada {_number(self.tick_s)} s) con {JOBS} trabajos en curso de "
                f"{min(rates):.0f}–{max(rates):.0f} eventos/s cada uno (unos "
                f"{per_tick:.0f} eventos por sondeo; {self.where}): mediana "
                f"{_ms(statistics.median(durations))} ms, máx. {_ms(max(durations))} ms de "
                f"{len(durations)} sondeos, presupuesto {_ms(TICK_BUDGET_S)} ms (todos, con el "
                f"arranque y el final de cada trabajo: máx. {_ms(max(every))} ms de "
                f"{len(every)}; los que acaban un trabajo, sin presupuesto: "
                f"{_ms(min(ending))}–{_ms(max(ending))} ms)")
        self.assertGreaterEqual(min(rates), MIN_EVENTS_PER_S)
        self.assertLessEqual(max(durations), TICK_BUDGET_S)

    def test_progress_reaches_the_status_bar(self) -> None:
        """RNF-004-04: cada avance del trabajo que enseña la barra de estado está en ella
        (su «Paso k de N» o uno posterior) ≤ 0,5 s después de emitirse."""
        self.check_succeeded()
        shown = {tick.current for tick in self.ticks
                 if tick.running_before == JOBS and tick.running_after == JOBS}
        self.assertEqual(shown, {self.handles[0].job_uid})
        job_uid = self.handles[0].job_uid
        visible = [tick for tick in self.ticks if tick.current == job_uid]
        last_seen = visible[-1].seen_at
        latencies: list[float] = []
        missing: list[int] = []
        for event in self.events[job_uid]:
            match = STEP.fullmatch(event.get("msg", "")) if event["t"] == "progress" else None
            if match is None or event["ts"] > last_seen - LATENCY_BUDGET_S:
                continue
            step = int(match.group(1))
            seen = next((tick.seen_at for tick in visible if tick.step >= step), None)
            if seen is None:
                missing.append(step)
            else:
                latencies.append(seen - event["ts"])
        _report(f"RNF-004-04: del avance emitido por el worker a la barra de estado "
                f"dibujada, con el tick cada {_number(self.tick_s)} s y hasta {JOBS} "
                f"trabajos en curso ({self.where}): "
                f"mediana {_seconds(statistics.median(latencies))} s, máx. "
                f"{_seconds(max(latencies))} s de {len(latencies)} avances, presupuesto "
                f"{_seconds(LATENCY_BUDGET_S)} s")
        self.assertEqual(missing, [])
        self.assertGreaterEqual(len(latencies), MIN_PROGRESS)
        self.assertGreater(min(latencies), 0.0)
        self.assertLessEqual(max(latencies), LATENCY_BUDGET_S)


if __name__ == "__main__":
    unittest.main()
