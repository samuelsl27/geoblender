# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendimiento de las máscaras de las restricciones (spec 012, T35; RNF-012-01, RNF-012-03 y
RNF-012-06; plan 012 §2.2 y §7.3, ``tests/rendimiento/gis``).

Se ejecuta con ``tools/check.py --rendimiento``: el Python de Blender (su numpy 2.3.4), en el PC de
referencia de la spec 001 §5 y en disco local (``%TEMP%``). Cada cifra se imprime en una línea
``RNF-012-nn: …`` con el equipo y el intérprete (``tools/check.py`` las recoge).

Datos (plan §2.2: se generan y no se versionan, ``tests/support/constraints_scale.py``): la rejilla
de 1.654 × 1.699 celdas de 1 m (2,81 M) con 500 restricciones de unos 100.000 vértices en un
proyecto nuevo con V01 y V02.

- RNF-012-01 (:class:`CompileTest`): compilar las máscaras de la versión, de ``begin_compile`` a
  las cifras registradas (``compile_run`` con los pasos que da el modal), ≤ 5 s (mediana de 5;
  el objetivo de la T35, ≤ 3 s).
- RNF-012-06 (:class:`CompileTest`): cada llamada al generador de ``compile_run`` ≤ 0,05 s salvo
  la transacción final (R4), que se anota; ``begin_compile`` (la llamada de la orden) se anota.
- RNF-012-03 (:class:`CompileTest`): el pico de memoria adicional (``tracemalloc``) ≤ 1 GB.
- Esc a mitad no deja nada en el proyecto (RF-012-28).
"""

from __future__ import annotations

import gc
import statistics
import time
import unittest
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from tests.support import constraints_scale as scale
from tests.support import gis_perf
from tests.support.package import import_geoblender

mask_store = import_geoblender("gis.masks.store")
mask_compile = import_geoblender("gis.masks.compile")

COMPILE_BUDGET_S = 5.0  # RNF-012-01
COMPILE_OBJECTIVE_S = 3.0  # el objetivo de la T35
STEP_BUDGET_S = 0.05  # RNF-012-06 (el paso que se planea; la llamada, ≤ 0,05 s)
BEGIN_BUDGET_S = 0.2  # RNF-012-06: la llamada de la orden
MEMORY_BUDGET_BYTES = 1024**3  # RNF-012-03: 1 GB
RUNS = 5  # mediana de 5
CANCEL_AFTER = 12  # pasos antes de Esc
CANCEL_BUDGET_S = 2.0  # RNF-012-01: la cancelación efectiva en ≤ 2 s
MACHINE = gis_perf.MACHINE
number = gis_perf.number
count = gis_perf.count


@dataclass(frozen=True, slots=True)
class Call:
    """Una llamada al generador de los pasos: lo que tardó y qué paso entregó."""

    seconds: float
    phase: str
    done: int
    total: int
    final: bool


@dataclass(frozen=True, slots=True)
class Run:
    """Una compilación entera: la de ``begin_compile``, las llamadas y el resultado."""

    begin_s: float
    calls: tuple[Call, ...]
    result: Any

    @property
    def total_s(self) -> float:
        return self.begin_s + sum(call.seconds for call in self.calls)

    @property
    def steps(self) -> tuple[Call, ...]:
        """Las llamadas que no son la transacción final."""
        return tuple(call for call in self.calls if not call.final)

    @property
    def longest(self) -> Call:
        """La llamada más larga sin contar la transacción final."""
        return max(self.steps, key=lambda call: call.seconds)

    @property
    def transaction_s(self) -> float:
        """Lo que tardó la llamada que confirma (la que entrega el resultado)."""
        return max((call.seconds for call in self.calls if call.final), default=0.0)


def _calls(steps: Iterator[Any]) -> tuple[tuple[Call, ...], Any]:
    calls: list[Call] = []
    result = None
    while True:
        before = time.perf_counter()
        try:
            step = next(steps)
        except StopIteration:
            calls.append(Call(time.perf_counter() - before, "end", 0, 0, False))
            break
        final = step.result is not None
        calls.append(Call(time.perf_counter() - before, step.phase, step.done, step.total, final))
        if final:
            result = step.result
    return tuple(calls), result


class CompileTest(unittest.TestCase):
    """RNF-012-01, RNF-012-03 y RNF-012-06 con las restricciones de §2.2 en disco local."""

    data: ClassVar[scale.ScaleProject]

    @classmethod
    def setUpClass(cls) -> None:
        constraints = scale.build_constraints()
        cls.data = cls.enterClassContext(scale.scale_project(constraints))

    def compile_once(self) -> Run:
        """``begin_compile`` y ``compile_run`` de V01 con los pasos seguidos."""
        data = self.data
        data.clock.advance(minutes=1)
        before = time.perf_counter()
        handle = mask_store.begin_compile(data.project, version=data.v1.uid)
        begin_s = time.perf_counter() - before
        calls, result = _calls(mask_store.compile_run(data.project, handle, budget_s=STEP_BUDGET_S))
        self.assertIsInstance(result, mask_store.StoredMasks)
        return Run(begin_s, calls, result)

    def runs(self) -> list[Run]:
        """La primera compilación (que no cuenta: sin caché) y :data:`RUNS` más."""
        self.compile_once()
        found = []
        for _ in range(RUNS):
            gc.collect()
            found.append(self.compile_once())
        return found

    def test_compile(self) -> None:
        """RNF-012-01 y RNF-012-06: compilar las 500 restricciones (100.000 vértices) en la
        rejilla de 2,81 M celdas, de ``begin_compile`` a las cifras, en ≤ 5 s en disco local
        (mediana de 5; objetivo de la T35, ≤ 3 s), y cada llamada al generador de los pasos
        ≤ 0,05 s salvo la transacción final (que se anota)."""
        found = self.runs()
        totals = [run.total_s for run in found]
        longest = sorted(found, key=lambda run: run.longest.seconds)[len(found) // 2].longest
        worst = max((run.longest for run in found), key=lambda call: call.seconds)
        result = found[-1].result.result
        gis_perf.report(
            f"RNF-012-01: compilar {count(len(self.data.constraints.rows))} restricciones "
            f"({count(self.data.constraints.vertices)} vértices) en la rejilla de "
            f"{count(scale.COLS * scale.ROWS)} celdas de 1 m (zonas, límites, máscaras, rejilla "
            f"de clases e informe; de begin_compile a las cifras registradas, con los pasos "
            f"seguidos; {MACHINE}): {gis_perf.median_line(totals)}; {len(found[-1].calls)} "
            f"llamadas; presupuesto {number(COMPILE_BUDGET_S, 0)} s (objetivo "
            f"{number(COMPILE_OBJECTIVE_S, 0)} s)")
        gis_perf.report(
            f"RNF-012-06: la llamada más larga al compilar (sin la transacción final), mediana "
            f"de {len(found)}: {number(longest.seconds * 1000, 0)} ms («{longest.phase}» "
            f"{longest.done}/{longest.total}; la peor de todas, {number(worst.seconds * 1000, 0)}"
            f" ms en «{worst.phase}» {worst.done}/{worst.total}); la transacción final, "
            f"{number(statistics.median(run.transaction_s for run in found) * 1000, 0)} ms; "
            f"begin_compile, {number(statistics.median(run.begin_s for run in found) * 1000, 0)}"
            f" ms; presupuesto {number(STEP_BUDGET_S * 1000, 0)} ms ({MACHINE})")
        self.assertEqual(len(result.prepared.zones), len(self.data.constraints.rows))
        self.assertLessEqual(statistics.median(totals), COMPILE_BUDGET_S)
        self.assertLessEqual(longest.seconds, STEP_BUDGET_S,
                             f"{longest.phase} {longest.done}/{longest.total}")

    def test_compile_memory(self) -> None:
        """RNF-012-03: el pico de memoria adicional (``tracemalloc``, con la de numpy) de
        compilar las 500 restricciones ≤ 1 GB."""
        self.compile_once()  # sin caché
        peak = gis_perf.peak_bytes(self.compile_once)
        gis_perf.report(
            f"RNF-012-03: pico de memoria adicional (tracemalloc, con la de numpy) de compilar "
            f"{count(len(self.data.constraints.rows))} restricciones en {count(scale.COLS * scale.ROWS)}"
            f" celdas ({MACHINE}): {number(peak / 2**20, 0)} MiB; presupuesto "
            f"{number(MEMORY_BUDGET_BYTES / 2**20, 0)} MiB")
        self.assertLessEqual(peak, MEMORY_BUDGET_BYTES)

    def test_cancel_leaves_nothing(self) -> None:
        """RNF-012-01 y RF-012-28: Esc a mitad de la compilación se atiende en ≤ 2 s y no
        deja nada en el proyecto (operaciones y ficheros de ``rasters/`` como estaban)."""
        data = self.data
        self.compile_once()  # hay una compilación vigente a la que sustituir
        root = Path(data.project.root)

        def state() -> tuple[Any, list[str]]:
            with data.project.read() as conn:
                rows = conn.execute(
                    "SELECT status, count(*) FROM gb_operation GROUP BY status ORDER BY 1"
                ).fetchall()
            return rows, sorted(p.name for p in (root / "rasters").glob("*"))

        before = state()
        data.clock.advance(minutes=1)
        handle = mask_store.begin_compile(data.project, version=data.v1.uid)
        steps = mask_store.compile_run(data.project, handle, budget_s=STEP_BUDGET_S)
        for _ in range(CANCEL_AFTER):
            next(steps)
        started = time.perf_counter()
        steps.close()
        elapsed = time.perf_counter() - started
        with data.project.read() as conn:
            status = conn.execute("SELECT status FROM gb_operation WHERE uid = ?",
                                  (handle.uid,)).fetchone()[0]
        after = state()
        gis_perf.report(
            f"RNF-012-01: Esc tras {CANCEL_AFTER} pasos de compilar: cerrar tarda "
            f"{number(elapsed * 1000, 1)} ms (presupuesto {number(CANCEL_BUDGET_S, 0)} s); la "
            f"operación queda «{status}» y los ficheros de rasters/ no cambian ({MACHINE})")
        self.assertLessEqual(elapsed, CANCEL_BUDGET_S)
        self.assertEqual(status, "cancelled")
        self.assertEqual(after[1], before[1])
        self.assertEqual({row[0]: row[1] for row in after[0]}.get("running", 0), 0)


if __name__ == "__main__":
    unittest.main()
