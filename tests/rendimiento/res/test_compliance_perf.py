# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendimiento de verificar un diseño por recinto (spec 012, T36; RNF-012-02, RNF-012-03 y
RNF-012-06; plan 012 §2.2 y §7.3, ``tests/rendimiento/res``).

Se ejecuta con ``python -B -s -X utf8 -m unittest tests.rendimiento.res.test_compliance_perf -v``
(o con ``tools/check.py --rendimiento``): el Python de Blender (su numpy 2.3.4), en el PC de
referencia de la spec 001 §5 y en disco local (``%TEMP%``). Cada cifra se imprime en una línea
``RNF-012-nn: …`` con el equipo y el intérprete.

Datos (plan §2.2: se generan y no se versionan, ``tests/support/constraints_scale.py``): la rejilla
de 1.654 × 1.699 celdas de 1 m (2,81 M) con las 500 restricciones de unos 100.000 vértices en un
proyecto nuevo con V01 y V02, las máscaras de V01 al día, y **dos formas** de tres superficies
finales frente a la de partida: ``window``, que cambian en toda la ventana (ondas de 3 m; pocos
grupos y muy grandes: 4,4 M de entradas celda-recinto por final) y ``local``, que cambian en 8
abultamientos de ±3 m (más de 3.600 grupos pequeños por final).

- RNF-012-02 (:class:`VerifyTest`): verificar las tres finales frente a la partida en las 500
  zonas (con los dos recintos de fuera y los grupos de incumplimiento), de la llamada de la orden
  (``verify_project_steps``) a las cifras registradas, con los pasos seguidos, ≤ 5 s (mediana de 5)
  en las dos formas.
- RNF-012-06 (:class:`VerifyTest`): cada llamada al generador de los pasos ≤ 0,05 s salvo la
  transacción final (R4), que se anota; la llamada de la orden (comprobar las máscaras al día) se
  anota.
- RNF-012-03 (:class:`VerifyTest`): el pico de memoria adicional (``tracemalloc``) ≤ 700 MiB
  (holgura sobre el 1 GB de la spec).
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

access = import_geoblender("gis.masks.access")
cstore_v = import_geoblender("reserves.compliance_store")

TOTAL_BUDGET_S = 5.0  # RNF-012-02
STEP_BUDGET_S = 0.05  # RNF-012-06 (el paso que se planea; la llamada, ≤ 0,05 s)
MEMORY_BUDGET_BYTES = 700 * 2**20  # RNF-012-03 con holgura: 700 MiB sobre el 1 GB de la spec
RUNS = 5  # mediana de 5
CANCEL_AFTER = 12  # pasos antes de Esc
CANCEL_BUDGET_S = 2.0  # la cancelación efectiva en ≤ 2 s
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
    """Una verificación entera: la llamada de la orden, las llamadas a los pasos y el
    resultado."""

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


class VerifyTest(unittest.TestCase):
    """RNF-012-02, RNF-012-03 y RNF-012-06 con las restricciones de §2.2 en disco local."""

    data: ClassVar[scale.ScaleProject]
    forms: ClassVar[dict[str, scale.ScaleSurfaces]]

    @classmethod
    def setUpClass(cls) -> None:
        constraints = scale.build_constraints()
        cls.data = cls.enterClassContext(scale.scale_project(constraints))
        cls.enterClassContext(scale.verify_registered())
        for _ in access.ensure_masks_steps(cls.data.project, cls.data.v1.uid, budget_s=0.05):
            pass  # las máscaras de V01 al día (no cuentan)
        cls.forms = {shape: scale.write_surfaces(cls.data, shape)
                     for shape in (scale.WINDOW, scale.LOCAL)}

    def verify_once(self, shape: str, *, name: str = "Diseño de escala") -> Run:
        """``verify_project_steps`` y sus pasos de V01 con las finales de ``shape``."""
        data, surfaces = self.data, self.forms[shape]
        data.clock.advance(minutes=1)
        before = time.perf_counter()
        steps = cstore_v.verify_project_steps(
            data.project, version=data.v1.uid, name=name, start=surfaces.start,
            finals=surfaces.finals, budget_s=STEP_BUDGET_S)
        begin_s = time.perf_counter() - before
        calls, result = _calls(steps)
        self.assertIsInstance(result, cstore_v.StoredCheck)
        return Run(begin_s, calls, result)

    def runs(self, shape: str) -> list[Run]:
        """La primera verificación (que no cuenta: la tabla aún no existe) y :data:`RUNS`
        más (que sustituyen a la anterior, como al repetir)."""
        self.verify_once(shape)
        found = []
        for _ in range(RUNS):
            gc.collect()
            found.append(self.verify_once(shape))
        return found

    def check_shape(self, shape: str) -> None:
        found = self.runs(shape)
        totals = [run.total_s for run in found]
        longest = sorted(found, key=lambda run: run.longest.seconds)[len(found) // 2].longest
        worst = max((run.longest for run in found), key=lambda call: call.seconds)
        stored = found[-1].result.result
        gis_perf.report(
            f"RNF-012-02: verificar {len(self.forms[shape].finals)} finales frente a la partida "
            f"({shape}) en {count(len(self.data.constraints.rows))} recintos y la rejilla de "
            f"{count(scale.COLS * scale.ROWS)} celdas de 1 m (los dos recintos de fuera, las "
            f"cifras y los grupos: {count(sum(len(f.groups) for f in stored.finals))}; de la "
            f"llamada de la orden a las cifras registradas, con los pasos seguidos; {MACHINE}): "
            f"{gis_perf.median_line(totals)}; {len(found[-1].calls)} llamadas; presupuesto "
            f"{number(TOTAL_BUDGET_S, 0)} s")
        gis_perf.report(
            f"RNF-012-06: la llamada más larga al verificar ({shape}, sin la transacción final), "
            f"mediana de {len(found)}: {number(longest.seconds * 1000, 0)} ms («{longest.phase}» "
            f"{longest.done}/{longest.total}; la peor de todas, {number(worst.seconds * 1000, 0)}"
            f" ms en «{worst.phase}» {worst.done}/{worst.total}); la transacción final, "
            f"{number(statistics.median(run.transaction_s for run in found) * 1000, 0)} ms; la "
            f"llamada de la orden, "
            f"{number(statistics.median(run.begin_s for run in found) * 1000, 0)} ms; "
            f"presupuesto {number(STEP_BUDGET_S * 1000, 0)} ms ({MACHINE})")
        self.assertEqual(len(stored.finals), len(self.forms[shape].finals))
        self.assertTrue(all(stored.fails))
        self.assertLessEqual(statistics.median(totals), TOTAL_BUDGET_S)
        self.assertLessEqual(longest.seconds, STEP_BUDGET_S,
                             f"{longest.phase} {longest.done}/{longest.total}")

    def test_verify_changes_in_the_whole_window(self) -> None:
        """RNF-012-02 y RNF-012-06: tres finales que cambian en toda la ventana (pocos grupos
        enormes, 4,4 M de entradas celda-recinto por final): ≤ 5 s (mediana de 5) y cada
        llamada al generador ≤ 0,05 s salvo la transacción final."""
        self.check_shape(scale.WINDOW)

    def test_verify_local_changes(self) -> None:
        """RNF-012-02 y RNF-012-06: tres finales con cambios localizados (más de 3.600 grupos
        pequeños por final): ≤ 5 s (mediana de 5) y cada llamada ≤ 0,05 s salvo la
        transacción final."""
        self.check_shape(scale.LOCAL)

    def test_memory(self) -> None:
        """RNF-012-03: el pico de memoria adicional (``tracemalloc``, con la de numpy) de
        verificar las tres finales ≤ 700 MiB en las dos formas (la de toda la ventana, la
        dura: 998 MiB antes de la T36)."""
        for shape in (scale.WINDOW, scale.LOCAL):
            self.verify_once(shape)  # sin caché
            peak = gis_perf.peak_bytes(lambda shape=shape: self.verify_once(shape))
            gis_perf.report(
                f"RNF-012-03: pico de memoria adicional (tracemalloc, con la de numpy) de "
                f"verificar {len(self.forms[shape].finals)} finales ({shape}) en "
                f"{count(len(self.data.constraints.rows))} recintos y "
                f"{count(scale.COLS * scale.ROWS)} celdas ({MACHINE}): "
                f"{number(peak / 2**20, 0)} MiB; presupuesto "
                f"{number(MEMORY_BUDGET_BYTES / 2**20, 0)} MiB (el de la spec, 1.024 MiB)")
            with self.subTest(shape=shape):
                self.assertLessEqual(peak, MEMORY_BUDGET_BYTES)

    def test_cancel_leaves_nothing(self) -> None:
        """RF-012-28: Esc a mitad de la verificación se atiende en ≤ 2 s y no deja nada en el
        proyecto (cifras, tablas y ficheros de ``rasters/`` como estaban)."""
        data, surfaces = self.data, self.forms[scale.WINDOW]
        self.verify_once(scale.WINDOW, name="Para cancelar")  # hay una a la que sustituir
        root = Path(data.project.root)

        def state() -> tuple[Any, Any, list[str]]:
            with data.project.read() as conn:
                operations = conn.execute(
                    "SELECT status, count(*) FROM gb_operation GROUP BY status ORDER BY 1"
                ).fetchall()
                figures = conn.execute("SELECT count(*) FROM gb_figure").fetchone()
            return operations, figures, sorted(p.name for p in (root / "rasters").glob("*"))

        def last_status() -> tuple[int, str]:
            with data.project.read() as conn:
                rows = conn.execute("SELECT status FROM gb_operation WHERE op_type = ? "
                                    "ORDER BY fid", (cstore_v.VERIFY,)).fetchall()
            return len(rows), str(rows[-1][0])

        before = state()
        known = last_status()[0]
        data.clock.advance(minutes=1)
        steps = cstore_v.verify_project_steps(
            data.project, version=data.v1.uid, name="Para cancelar", start=surfaces.start,
            finals=surfaces.finals, budget_s=STEP_BUDGET_S)
        while last_status()[0] == known:  # cargar las máscaras son varios pasos
            next(steps)
        for _ in range(CANCEL_AFTER):
            next(steps)
        started = time.perf_counter()
        steps.close()
        elapsed = time.perf_counter() - started
        after = state()
        status = last_status()[1]
        gis_perf.report(
            f"RNF-012-02: Esc tras {CANCEL_AFTER} pasos de verificar: cerrar tarda "
            f"{number(elapsed * 1000, 1)} ms (presupuesto {number(CANCEL_BUDGET_S, 0)} s); la "
            f"operación queda «{status}»; las cifras y los ficheros de rasters/ no cambian "
            f"({MACHINE})")
        self.assertLessEqual(elapsed, CANCEL_BUDGET_S)
        self.assertEqual(status, "cancelled")
        self.assertEqual(after[1:], before[1:])
        self.assertEqual({row[0]: row[1] for row in after[0]}.get("running", 0), 0)


if __name__ == "__main__":
    unittest.main()
