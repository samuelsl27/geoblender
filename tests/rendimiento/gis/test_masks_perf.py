# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendimiento de las máscaras de las restricciones (spec 012, T35 y T30; RNF-012-01, RNF-012-03 y
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
- RNF-012-01 y RNF-012-06 con una restricción mucho mayor que la rejilla (:class:`HugeTest`, T40): un
  recinto de 50 km de lado, adyacente a la ventana de 400 × 300 celdas de 1 m, se compila en ≤ 5 s
  y con cada llamada ≤ 0,05 s, sin construir una rejilla del tamaño de la restricción para medir lo
  que queda fuera de la ventana (88,4 s antes).

**En la red** (:class:`NetworkTest`; recurso «red»: la carpeta de pruebas de
``GEOBLENDER_NET_TEST_DIR``, nunca la de los expedientes ni la del espejo; sin ella, se omite): el
mismo proyecto creado en una subcarpeta temporal propia que se borra al terminar, con los datos de
usuario en disco local (como en un puesto): RNF-012-01 ≤ 10 s (mediana de 5, de ``begin_compile``
a las cifras) y Esc ≤ 2 s. Lo que hace Geoblender en cada llamada, sin sus esperas de la red
(``tests.support.netwaits``), y esas esperas, aparte, se anotan sin presupuesto: el de RNF-012-06
se comprueba con las órdenes reales (T31). El proyecto ocupa unos 12 MB en la red (más lo que
reescribe cada compilación) y la prueba tarda unos minutos.
"""

from __future__ import annotations

import gc
import statistics
import tempfile
import time
import unittest
from collections.abc import Iterator
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from tests.support import constraints_scale as scale
from tests.support import gis_perf, netwaits, network
from tests.support import versions_perf as vperf
from tests.support.package import import_geoblender
from tests.support.resources import requires

mask_store = import_geoblender("gis.masks.store")
mask_compile = import_geoblender("gis.masks.compile")

COMPILE_BUDGET_S = 5.0  # RNF-012-01
NET_COMPILE_BUDGET_S = 10.0  # RNF-012-01, en Z:
COMPILE_OBJECTIVE_S = 3.0  # el objetivo de la T35
STEP_BUDGET_S = 0.05  # RNF-012-06 (el paso que se planea; la llamada, ≤ 0,05 s)
BEGIN_BUDGET_S = 0.2  # RNF-012-06: la llamada de la orden
MEMORY_BUDGET_BYTES = 1024**3  # RNF-012-03: 1 GB
RUNS = 5  # mediana de 5
HUGE_RUNS = 3  # mediana de 3 (la de una restricción mucho mayor que la rejilla, T40)
CANCEL_AFTER = 12  # pasos antes de Esc
CANCEL_BUDGET_S = 2.0  # RNF-012-01: la cancelación efectiva en ≤ 2 s
MACHINE = gis_perf.MACHINE
number = gis_perf.number
count = gis_perf.count


@dataclass(frozen=True, slots=True)
class Call:
    """Una llamada al generador de los pasos: lo que tardó, qué paso entregó y, en la red, lo
    que esperó en ella a la red (``waits_s``)."""

    seconds: float
    phase: str
    done: int
    total: int
    final: bool
    waits_s: float = 0.0

    @property
    def own_s(self) -> float:
        """Lo que hace Geoblender en la llamada: su duración sin sus esperas de la red."""
        return self.seconds - self.waits_s


@dataclass(frozen=True, slots=True)
class Run:
    """Una compilación entera: la de ``begin_compile``, las llamadas y el resultado (en la red,
    con lo que esperó ``begin_compile`` a la red y las esperas de toda la compilación)."""

    begin_s: float
    calls: tuple[Call, ...]
    result: Any
    begin_waits_s: float = 0.0
    waits: netwaits.NetworkWaits | None = None

    @property
    def total_s(self) -> float:
        return self.begin_s + sum(call.seconds for call in self.calls)

    @property
    def steps(self) -> tuple[Call, ...]:
        """Las llamadas que no son la transacción final."""
        return tuple(call for call in self.calls if not call.final)

    @property
    def longest(self) -> Call:
        """La llamada más larga sin contar la transacción final (en la red, la de más trabajo
        propio, sin sus esperas)."""
        return max(self.steps, key=lambda call: call.own_s)

    @property
    def transaction_s(self) -> float:
        """Lo que tardó la llamada que confirma (la que entrega el resultado)."""
        return max((call.seconds for call in self.calls if call.final), default=0.0)


def _calls(steps: Iterator[Any],
           waits: netwaits.NetworkWaits | None = None) -> tuple[tuple[Call, ...], Any]:
    """Cada ``next()`` de ``steps`` como una llamada; con ``waits`` (activo), también lo que
    esperó en ella a la red."""
    calls: list[Call] = []
    result = None
    while True:
        if waits is not None:
            waits.begin()
        before = time.perf_counter()
        try:
            step = next(steps)
        except StopIteration:
            seconds = time.perf_counter() - before
            calls.append(Call(seconds, "end", 0, 0, False, _waited(waits)))
            break
        seconds = time.perf_counter() - before
        final = step.result is not None
        calls.append(Call(seconds, step.phase, step.done, step.total, final, _waited(waits)))
        if final:
            result = step.result
    return tuple(calls), result


def _waited(waits: netwaits.NetworkWaits | None) -> float:
    """Lo que esperó a la red la llamada que acaba (y empieza otra)."""
    return 0.0 if waits is None else sum(waits.take().values())


def _waits_text(waits: netwaits.NetworkWaits | None) -> str:
    """Las esperas de la red de una compilación, por clase: cuántas y cuánto en total, y la más
    larga."""
    if waits is None:
        return "sin red"
    parts = [f"{kind} {count(waits.counts[kind])} ({number(waits.totals[kind], 2)} s)"
             for kind in netwaits.KINDS if waits.counts[kind]]
    kind, seconds = waits.longest
    return f"{', '.join(parts)}; la más larga, {kind} {number(seconds * 1000, 0)} ms"


class CompileTest(unittest.TestCase):
    """RNF-012-01, RNF-012-03 y RNF-012-06 con las restricciones de §2.2 en disco local.

    Sus atributos de clase son los de :class:`NetworkTest`, que hace lo mismo con el proyecto en
    la red: ``remote``, la carpeta de la red del proyecto (``None``: disco local); ``budget_s``,
    el presupuesto de RNF-012-01; ``step_limit_s``, el de cada llamada (``None``: solo se anota;
    el de RNF-012-06 en la red se comprueba con las órdenes reales, T31)."""

    data: ClassVar[scale.ScaleProject]
    remote: ClassVar[Path | None] = None
    budget_s: ClassVar[float] = COMPILE_BUDGET_S
    step_limit_s: ClassVar[float | None] = STEP_BUDGET_S
    where: ClassVar[str] = "en disco local"

    @classmethod
    def setUpClass(cls) -> None:
        constraints = scale.build_constraints()
        cls.data = cls.enterClassContext(scale.scale_project(constraints))

    def waiting(self) -> AbstractContextManager[netwaits.NetworkWaits | None]:
        """Las esperas de la red de lo que se mide (``None`` en disco local)."""
        if self.remote is None:
            return nullcontext()
        return netwaits.NetworkWaits(self.remote, projects=(self.data.project,))

    def space(self) -> str:
        """El espacio libre del disco del proyecto (y, en la red, el de los datos de usuario)."""
        folders = [Path(self.data.project.root)]
        if self.remote is not None:
            folders.append(Path(tempfile.gettempdir()))
        return "; ".join(vperf.free_space(folder) for folder in folders)

    def compile_once(self) -> Run:
        """``begin_compile`` y ``compile_run`` de V01 con los pasos seguidos."""
        data = self.data
        data.clock.advance(minutes=1)
        with self.waiting() as waits:
            before = time.perf_counter()
            handle = mask_store.begin_compile(data.project, version=data.v1.uid)
            begin_s = time.perf_counter() - before
            begin_waits = _waited(waits)
            calls, result = _calls(
                mask_store.compile_run(data.project, handle, budget_s=STEP_BUDGET_S), waits)
        self.assertIsInstance(result, mask_store.StoredMasks)
        return Run(begin_s, calls, result, begin_waits, waits)

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
        longest = sorted(found, key=lambda run: run.longest.own_s)[len(found) // 2].longest
        worst = max((run.longest for run in found), key=lambda call: call.own_s)
        result = found[-1].result.result
        objective = (f" (objetivo {number(COMPILE_OBJECTIVE_S, 0)} s)"
                     if self.remote is None else "")
        gis_perf.report(
            f"RNF-012-01: compilar {count(len(self.data.constraints.rows))} restricciones "
            f"({count(self.data.constraints.vertices)} vértices) en la rejilla de "
            f"{count(scale.COLS * scale.ROWS)} celdas de 1 m {self.where} (zonas, límites, "
            f"máscaras, rejilla de clases e informe; de begin_compile a las cifras registradas, "
            f"con los pasos seguidos; {MACHINE}): {gis_perf.median_line(totals)}; "
            f"{len(found[-1].calls)} llamadas; presupuesto {number(self.budget_s, 0)} s"
            f"{objective}; {self.space()}")
        limit = ("sin presupuesto en esta prueba (el de las órdenes reales, T31)"
                 if self.step_limit_s is None
                 else f"presupuesto {number(self.step_limit_s * 1000, 0)} ms")
        waited = ("" if self.remote is None else
                  f"; lo propio de cada llamada, sin sus esperas de la red (con ellas, la más "
                  f"larga de la última compilación fue "
                  f"{number(max(c.seconds for c in found[-1].steps) * 1000, 0)} ms); las "
                  f"esperas de la red, aparte (la última compilación): "
                  f"{_waits_text(found[-1].waits)}")
        gis_perf.report(
            f"RNF-012-06: la llamada más larga al compilar {self.where} (sin la transacción "
            f"final), mediana de {len(found)}: {number(longest.own_s * 1000, 0)} ms "
            f"(«{longest.phase}» {longest.done}/{longest.total}; la peor de todas, "
            f"{number(worst.own_s * 1000, 0)} ms en «{worst.phase}» {worst.done}/{worst.total}); "
            f"la transacción final, "
            f"{number(statistics.median(run.transaction_s for run in found) * 1000, 0)} ms; "
            f"begin_compile, {number(statistics.median(run.begin_s for run in found) * 1000, 0)}"
            f" ms{waited}; {limit} ({MACHINE})")
        self.assertEqual(len(result.prepared.zones), len(self.data.constraints.rows))
        self.assertLessEqual(statistics.median(totals), self.budget_s)
        if self.step_limit_s is not None:
            self.assertLessEqual(longest.own_s, self.step_limit_s,
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
            f"RNF-012-01: Esc tras {CANCEL_AFTER} pasos de compilar {self.where}: cerrar tarda "
            f"{number(elapsed * 1000, 1)} ms (presupuesto {number(CANCEL_BUDGET_S, 0)} s); la "
            f"operación queda «{status}» y los ficheros de rasters/ no cambian ({MACHINE})")
        self.assertLessEqual(elapsed, CANCEL_BUDGET_S)
        self.assertEqual(status, "cancelled")
        self.assertEqual(after[1], before[1])
        self.assertEqual({row[0]: row[1] for row in after[0]}.get("running", 0), 0)


# --- Una restricción mucho mayor que la rejilla -------------------------------------------------


class HugeTest(unittest.TestCase):
    """RNF-012-01 y RNF-012-06 con una restricción mucho mayor que la rejilla (T40; hallazgo F-4
    de la verificación única): un recinto de la Red Natura de 50 km de lado importado sin recortar,
    adyacente a la ventana de 400 × 300 celdas de 1 m (su lado oeste, 20 m dentro de ella), con 5 m
    de resguardo. ``combine._outside_cells`` construía una rejilla ampliada con la caja entera de la
    restricción: 88,4 s en 199 pasos de hasta 472 ms. Ahora se mide por bandas de filas, por tramos.

    Mediana de :data:`HUGE_RUNS` compilaciones de ``gis.masks.compile`` (sin proyecto: es el
    cálculo), con los pasos seguidos y el ritmo de ``budget_s`` = 0,05 s; la cifra de m² fuera es la
    exacta del cuadrado (L² + 20·L + 88 − 7.500)."""

    SIDE_KM = 50.0
    OUTWARD_M = 5.0
    COLS, ROWS = 400, 300

    def compile_once(self) -> tuple[float, float, Any]:
        """``(segundos en total, la llamada más larga en segundos, zona)`` de una compilación."""
        cmodel = import_geoblender("core.constraints.model")
        cparams = import_geoblender("core.constraints.params")
        cstore = import_geoblender("core.constraints.store")
        gis = import_geoblender("gis")
        west, south = scale.WEST, scale.SOUTH
        grid = gis.Grid(west, south + self.ROWS, 1.0, 1.0, self.COLS, self.ROWS)
        side = self.SIDE_KM * 1000.0

        def rectangle(left: float, bottom: float, right: float, top: float) -> Any:
            return np.array([(west + left, south + bottom), (west + right, south + bottom),
                             (west + right, south + top), (west + left, south + top),
                             (west + left, south + bottom)], dtype=np.float64)

        def item(code: str, ctype: Any, ring: Any, fid: int) -> Any:
            return cmodel.Constraint(
                uid=f"{fid:032x}", code=code, name=code, ctype=ctype, kind=cmodel.GeometryKind.POLYGON,
                parts=((ring,),), priority=0, reason="Restricción sintética de rendimiento",
                decided_by=scale.PERSON, decided_on=date(2026, 11, 1), decision_uid=None,
                intention_uid=None, source_input=None, source_fid=None,
                layer=cstore.layer_of(cmodel.GeometryKind.POLYGON), fid=fid)

        legal = item("r_concesion", cmodel.ConstraintType.LEGAL_LIMIT,
                     rectangle(0.0, 0.0, float(self.COLS), float(self.ROWS)), 1)
        natura = item("r_natura", cmodel.ConstraintType.NO_FILL,
                      rectangle(self.COLS - 20.0, -side / 2, self.COLS - 20.0 + side, side / 2), 2)
        resolved = {cparams.active_key("r_concesion"): True, cparams.active_key("r_natura"): True,
                    cparams.buffer_in_key("r_concesion"): 2.0,
                    cparams.buffer_out_key("r_natura"): self.OUTWARD_M}
        request = mask_compile.CompileRequest((legal, natura), resolved, grid=grid)
        steps = mask_compile.compile_steps(request, budget_s=STEP_BUDGET_S)
        longest, result = 0.0, None
        started = last = time.perf_counter()
        for progress in steps:
            now = time.perf_counter()
            longest = max(longest, now - last)
            if progress.result is not None:
                result = progress.result
            last = time.perf_counter()
        self.assertIsNotNone(result)
        return last - started, longest, result.prepared.zones["r_natura"]

    def test_huge_constraint(self) -> None:
        """RNF-012-01 y RNF-012-06: compilar con una exclusión de 50 km adyacente a la ventana
        (300 × 400 celdas de 1 m, 5 m de resguardo) en ≤ 5 s y con cada llamada ≤ 0,05 s, dando
        los m² fuera de la rejilla que salen a mano; 88 s y pasos de 0,47 s antes de la T40."""
        self.compile_once()   # calienta numpy
        found = []
        for _ in range(HUGE_RUNS):
            gc.collect()
            found.append(self.compile_once())
        totals = [seconds for seconds, _, _ in found]
        longest = statistics.median(call for _, call, _ in found)
        worst = max(call for _, call, _ in found)
        zone = found[-1][2]
        side = self.SIDE_KM * 1000.0
        expected = side * side + 4.0 * side * self.OUTWARD_M + 88.0 - 7500.0
        gis_perf.report(
            f"RNF-012-01: compilar con una exclusión de {number(self.SIDE_KM, 0)} km de lado "
            f"adyacente a una ventana de {self.COLS} × {self.ROWS} celdas de 1 m, con "
            f"{number(self.OUTWARD_M, 0)} m de resguardo y {number(zone.outside_m2 / 1e6, 1)} km² de "
            f"su zona fuera de la rejilla (dentro, {count(zone.runs.cells)} celdas; {MACHINE}): "
            f"{gis_perf.median_line(totals)}; presupuesto {number(COMPILE_BUDGET_S, 0)} s")
        gis_perf.report(
            f"RNF-012-06: la llamada más larga de esa compilación, mediana de {len(found)}: "
            f"{number(longest * 1000, 0)} ms (la peor, {number(worst * 1000, 0)} ms); "
            f"presupuesto {number(STEP_BUDGET_S * 1000, 0)} ms ({MACHINE})")
        self.assertEqual(zone.runs.cells, 25 * self.ROWS)
        self.assertEqual(zone.outside_m2, expected)
        self.assertLessEqual(statistics.median(totals), COMPILE_BUDGET_S)
        self.assertLessEqual(longest, STEP_BUDGET_S)


# --- En la red ---------------------------------------------------------------------------------


@requires(network.NET, network.NET_HINT)
class NetworkTest(CompileTest):
    """RNF-012-01 con el proyecto en la carpeta de pruebas de la red (una subcarpeta temporal
    propia, borrada al terminar) y los datos de usuario en disco local: lo mismo que
    :class:`CompileTest`, con el presupuesto de la red (≤ 10 s) y las esperas de la red de cada
    llamada aparte. La memoria no se mide aquí (RNF-012-03 es la misma)."""

    budget_s = NET_COMPILE_BUDGET_S
    step_limit_s = None
    where = "con el proyecto en la red"
    test_compile_memory = None  # type: ignore[assignment]

    @classmethod
    def setUpClass(cls) -> None:
        cls.remote = cls.enterClassContext(network.net_tmp("gb-012-"))
        cls.data = cls.enterClassContext(
            scale.scale_project(scale.build_constraints(), remote=cls.remote))

    def test_compile(self) -> None:
        """RNF-012-01 en ``Z:``: compilar las 500 restricciones (100.000 vértices) en la
        rejilla de 2,81 M celdas con el proyecto en la carpeta de pruebas de la red, de
        ``begin_compile`` a las cifras, en ≤ 10 s (mediana de 5); lo propio de cada llamada y
        sus esperas de la red se anotan aparte."""
        self.assertTrue(self.data.project.is_network, "el proyecto no está en una carpeta de red")
        super().test_compile()

    def test_cancel_leaves_nothing(self) -> None:
        """RNF-012-01 y RF-012-28 en ``Z:``: Esc a mitad de la compilación con el proyecto en
        la red se atiende en ≤ 2 s y no deja nada en el proyecto."""
        super().test_cancel_leaves_nothing()


if __name__ == "__main__":
    unittest.main()
