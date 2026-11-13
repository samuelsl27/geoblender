# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendimiento del núcleo de la cantera con dos superficies (spec 014, T34; RNF-014-01, RNF-014-03,
RNF-014-04 y RNF-014-05; plan 014 §7.1 y §7.3, ``tests/rendimiento/des``), con la forma de
``test_design_perf.py`` de la 013.

Se ejecuta con ``tools/check.py --rendimiento``, nunca en el «verde»: el Python de Blender (su numpy
2.3.4), en el PC de referencia de la spec 001 §5 y en disco local (``%TEMP%``). Cada cifra se
imprime en una línea ``RNF-014-nn: …`` con el equipo y el intérprete (``tools/check.py`` las
recoge) y se compara con su presupuesto, sin relajarlo (mediana de 5, como la 013).

**Datos** (los de §2.2 del plan 013; ``tests/support/quarry_perf.py``, que no versiona ninguno): el
proyecto de escala de la 013 —la rejilla de 1.654 × 1.699 celdas de 1 m (2,81 M) con el terreno
ondulado de 145 a 215 m, 20 sectores en franjas con su búsqueda cerrada, diez perfiles de banco y
dos taludes impuestos, las máscaras de V01 al día— con lo que registra ``bl`` para la 014; y la
cantera de escala: las dos superficies sembradas en la «coronación y zonas a sostener» (el recinto
es todo el perímetro de actuación), la explotación con los cinco perfiles de 10 m y la final con
los cinco de 5 m, en rotación por los 20 sectores.

- RNF-014-01 (:class:`QuarryTest`): las dos superficies (envolventes, escalonados, orden,
  clasificación y cifras), de la primera llamada de «Calcular» a las cifras registradas por
  «Crear», en un proyecto en disco local, ≤ 20 s. En ``Z:`` (≤ 40 s) se mide a mano en el H3, como
  la 013 (su T31): esta prueba no escribe en ``Z:``.
- RNF-014-03 (:class:`QuarryTest`): el pico de memoria adicional de ese cálculo (``tracemalloc``,
  con la de numpy; aparte de las de tiempo) ≤ 1,5 GB.
- RNF-014-04 (:class:`EdgeTest`, :class:`RefitTest`): el salto creado de cada superficie de la
  cantera y «Transiciones con el terreno no afectado» (la transición y el salto creado, de
  «Calcular» a «Crear»), y el ajuste de las dos superficies a un límite legal 30 m más corto por
  el este (de «Calcular» a «Crear»): ≤ 5 s cada uno.
- RNF-014-05 (:class:`CancelTest`, :class:`RefitTest`): Esc a mitad de cada cálculo de la 014 (el
  recinto, la cantera, la transición, «solo relleno» y el ajuste) —la llamada más larga del cálculo
  más cerrar los pasos, a mitad y con todas las rejillas ya en sus temporales— ≤ 2 s, sin dejar
  nada en el proyecto (ni operación, ni dato, ni cifra, ni fichero).

Lo que hace Geoblender en cada llamada del hilo de Blender con las órdenes reales (RNF-014-02) se
mide dentro de Blender (T35, ``perf_quarry.py``); aquí se anota la llamada más larga de cada
cálculo, sin presupuesto propio.
"""

from __future__ import annotations

import gc
import statistics
import time
import unittest
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from tests.support import design_perf as dperf
from tests.support import gis_perf
from tests.support import quarry_perf as qperf
from tests.support import versions_perf as vperf
from tests.support.package import import_geoblender

access = import_geoblender("gis.masks.access")
edges = import_geoblender("design.edges")
model = import_geoblender("design.model")
provenance = import_geoblender("design.provenance")
steps = import_geoblender("design.steps")

QUARRY_BUDGET_S = 20.0  # RNF-014-01, en disco local
MEMORY_BUDGET_BYTES = int(1.5 * 1024**3)  # RNF-014-03: 1,5 GB
EDGE_BUDGET_S = 5.0  # RNF-014-04: el salto creado
REFIT_BUDGET_S = 5.0  # RNF-014-04: el ajuste a un límite nuevo
CANCEL_BUDGET_S = 2.0  # RNF-014-05: Esc a mitad de cualquier cálculo
STEP_BUDGET_S = 0.05  # el ritmo con que las órdenes agrupan sus unidades en pasos
RUNS = 5  # como la 013 (su spec §5): mediana de 5
MACHINE = gis_perf.MACHINE
number = gis_perf.number
count = gis_perf.count
GEOMETRY = dperf.grid()


def seconds_of(times: list[float]) -> str:
    """«mediana X s de N (mín. A, máx. B)» de unas duraciones."""
    return gis_perf.median_line(times)


def calls_text(found: list[vperf.Driven]) -> str:
    """La llamada más larga de unas ejecuciones (mediana de las de cada una y la peor, con su
    fase)."""
    median = statistics.median(driven.longest_s for driven in found)
    worst = max(found, key=lambda driven: driven.longest_s)
    return (f"{found[-1].steps} llamadas, la más larga {number(median * 1000, 0)} ms (la peor, "
            f"{number(worst.longest_s * 1000, 0)} ms en «{worst.longest_phase}»)")


def phases_text(driven: vperf.Driven, top: int = 5) -> str:
    """Las ``top`` fases que más tardaron de una ejecución, con sus segundos."""
    ranked = sorted(driven.phases.items(), key=lambda item: item[1], reverse=True)[:top]
    return ", ".join(f"«{phase}» {number(spent, 2)} s" for phase, spent in ranked)


def drain(start: Callable[[], Iterator[Any]]) -> Any:
    """Lleva unos pasos hasta el final y devuelve el resultado del último."""
    result = None
    for step in start():
        if step.result is not None:
            result = step.result
    return result


def project_state(project: Any) -> dict[str, Any]:
    """Lo que hay en el proyecto: las operaciones, los datos (con su hash), las tablas, las
    cifras y los ficheros de su carpeta (con los temporales)."""
    root = Path(project.root)
    with project.read() as conn:
        found = {
            "operations": conn.execute("SELECT uid, op_type, status FROM gb_operation "
                                       "ORDER BY fid").fetchall(),
            "datasets": conn.execute("SELECT name, status, content_sha256 FROM gb_dataset "
                                     "ORDER BY name").fetchall(),
            "tables": conn.execute("SELECT name FROM sqlite_master ORDER BY name").fetchall(),
            "figures": conn.execute("SELECT count(*) FROM gb_figure").fetchall()}
    found["files"] = sorted(str(path.relative_to(root)) for path in root.rglob("*")
                            if path.is_file())
    return found


# --- El proyecto de escala del módulo -------------------------------------------------------------

_SCALE: dict[str, Any] = {}
"""El proyecto de escala del módulo (se crea al pedirlo la primera vez y se cierra en
:func:`tearDownModule`) y la cantera de escala ya creada (:func:`made_quarry`): los comparten todas
las clases."""
_NAMES: dict[str, int] = {}


def scale() -> dperf.DesignScale:
    if "data" not in _SCALE:
        stack = ExitStack()
        _SCALE["stack"] = stack
        try:
            _SCALE["data"] = stack.enter_context(qperf.scale_project())
        except BaseException:
            stack.close()
            _SCALE.clear()
            raise
    return _SCALE["data"]  # type: ignore[no-any-return]


def tearDownModule() -> None:  # noqa: N802
    stack = _SCALE.pop("stack", None)
    _SCALE.clear()
    if stack is not None:
        stack.close()


def fresh(label: str) -> str:
    """Un nombre que no se ha usado en la versión: «``label`` n»."""
    _NAMES[label] = _NAMES.get(label, 0) + 1
    return f"{label} {_NAMES[label]}"


@dataclass(frozen=True, slots=True)
class Made:
    """La cantera de escala creada en V01: su nombre, su resultado y los nombres de los datos de
    sus dos superficies."""

    name: str
    outcome: Any
    final: str
    exploitation: str


def made_quarry() -> Made:
    """La cantera de escala, creada una vez en V01 (con el límite de la 013): la superficie de
    diseño de la transición, del salto creado y del ajuste."""
    if "quarry" not in _SCALE:
        data = scale()
        name = "Cantera de escala"
        with drain(lambda: steps.quarry_run(data.project, qperf.quarry_request(name),
                                            version=data.v1.uid)) as calculation:
            calculation.create()
            outcome = calculation.outcome
        _SCALE["quarry"] = Made(name, outcome, provenance.dataset_name("fin", name),
                                provenance.dataset_name("exp", name))
    return _SCALE["quarry"]  # type: ignore[no-any-return]


@dataclass(frozen=True, slots=True)
class Chain:
    """Un cálculo de «Calcular» a «Crear»: lo que tardó en total, sus pasos llevados como la orden,
    lo que tardó «Crear» y su resultado."""

    total_s: float
    driven: vperf.Driven
    create_s: float
    outcome: Any


def chain(start: Callable[[], Iterator[Any]]) -> Chain:
    """Lleva los pasos de «Calcular» que da ``start`` como el temporizador de su orden y «Crear»
    el resultado."""
    began = time.perf_counter()
    driven = vperf.drive(start)
    with driven.result as calculation:
        started = time.perf_counter()
        calculation.create()
        created = time.perf_counter() - started
        outcome = calculation.outcome
    return Chain(time.perf_counter() - began, driven, created, outcome)


def repeat(make: Callable[[], Chain]) -> list[Chain]:
    """:data:`RUNS` cálculos seguidos (con la basura recogida antes de cada uno), después de uno
    que calienta la caché de lectura y no cuenta."""
    make()
    found = []
    for _ in range(RUNS):
        gc.collect()
        found.append(make())
    return found


# --- RNF-014-01 y RNF-014-03: las dos superficies ------------------------------------------------


class QuarryTest(unittest.TestCase):
    """RNF-014-01 y RNF-014-03 con el proyecto de escala: «Cantera con dos superficies…» de
    «Calcular» a «Crear», en disco local."""

    def quarry(self) -> Chain:
        data = scale()
        request = qperf.quarry_request(fresh("Cantera"))
        return chain(lambda: steps.quarry_run(data.project, request, version=data.v1.uid,
                                              budget_s=STEP_BUDGET_S))

    def test_quarry(self) -> None:
        """RNF-014-01: las dos superficies (las dos envolventes por 20 sectores, los dos
        escalonados, la regla de orden, la clasificación y las cifras) sobre 2,81 M celdas, de la
        primera llamada de «Calcular» a las cifras registradas por «Crear» (con la lectura de la
        partida y de las máscaras, las cinco rejillas con su hash y las dos tablas), en un proyecto
        en disco local, en ≤ 20 s (mediana de 5; la primera, que calienta la caché, no cuenta)."""
        found = repeat(self.quarry)
        last = found[-1].outcome
        total = last.classes.total
        gis_perf.report(
            f"RNF-014-01: las dos superficies de una cantera (envolventes por {dperf.SECTORS} "
            f"sectores desde la coronación, escalonados en corte, orden «final primero», "
            f"clasificación y cifras) sobre {count(dperf.CELLS)} celdas de 1 m, de «Calcular» a "
            f"las cifras registradas por «Crear» (lectura de la partida y de las máscaras, cinco "
            f"rejillas con su hash, dos tablas y la transacción; {count(total.cells)} celdas de "
            f"dominio, excavación de la explotación {number(total.exp_cut_m3 / 1e6, 1)} hm³, "
            f"desdoblado {number(total.unsplit_m3 / 1e6, 1)} hm³ en "
            f"{count(total.unsplit_cells)} celdas, {count(last.adjusted)} celdas que cambia el "
            f"orden; proyecto en disco local; {MACHINE}): "
            f"{seconds_of([item.total_s for item in found])}; "
            f"{calls_text([item.driven for item in found])}; fases de la última: "
            f"{phases_text(found[-1].driven)}; «Crear» "
            f"{number(statistics.median(item.create_s for item in found) * 1000, 0)} ms; "
            f"presupuesto {number(QUARRY_BUDGET_S, 0)} s")
        self.assertGreater(total.exp_cut_cells, 0, "la cantera no excava: no mide nada")
        self.assertGreater(total.unsplit_cells, 0, "sin desdoblado: las dos superficies son una")
        self.assertLessEqual(statistics.median(item.total_s for item in found), QUARRY_BUDGET_S)

    def test_quarry_memory(self) -> None:
        """RNF-014-03: el pico de memoria adicional (``tracemalloc``, con la de numpy) de las dos
        superficies de RNF-014-01, de «Calcular» a «Crear», ≤ 1,5 GB."""
        self.quarry()  # sin caché de lectura
        peak = gis_perf.peak_bytes(self.quarry)
        gis_perf.report(
            f"RNF-014-03: pico de memoria adicional (tracemalloc, con la de numpy) de las dos "
            f"superficies de una cantera sobre {count(dperf.CELLS)} celdas y {dperf.SECTORS} "
            f"sectores, de «Calcular» a «Crear» ({MACHINE}): {number(peak / 2**20, 0)} MiB; "
            f"presupuesto {number(MEMORY_BUDGET_BYTES / 2**20, 0)} MiB")
        self.assertLessEqual(peak, MEMORY_BUDGET_BYTES)


# --- RNF-014-04: el salto creado ------------------------------------------------------------------


def created(surface: np.ndarray, start: np.ndarray, domain: np.ndarray
            ) -> Callable[[], Iterator[Any]]:
    """Los pasos del salto creado (A11) de ``surface`` sobre ``start`` en ``domain``, con el
    espesor mínimo, el salto y el porcentaje admitidos por defecto."""
    return lambda: edges.created_steps(surface, start, domain, GEOMETRY, qperf.MIN_THICKNESS_M,
                                       qperf.MAX_CREATED_STEP_M, qperf.MIN_SHARE_PCT,
                                       budget_s=STEP_BUDGET_S)


class EdgeTest(unittest.TestCase):
    """RNF-014-04 con la cantera de escala: el salto creado (A11) de cada superficie y la orden
    «Transiciones con el terreno no afectado» (A10 y A11)."""

    made: ClassVar[Made]
    masks: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        cls.made = made_quarry()
        cls.masks = access.load_masks(scale().project, scale().v1.uid)

    def test_created_step(self) -> None:
        """RNF-014-04: el salto creado (A11: las parejas del borde, el porcentaje dentro del salto
        admitido, el máximo con su lugar y los tramos) de la superficie final y de la de
        explotación de la cantera sobre 2,81 M celdas, en el dominio que usa la orden (las celdas
        que mueve el diseño donde las máscaras lo admiten), en ≤ 5 s cada una (mediana de 5)."""
        start = dperf.terrain()
        allowed = self.masks.cut_allowed() | self.masks.fill_allowed()
        lines, worst = [], 0.0
        for label, surface in (("final", self.made.outcome.final_grid),
                               ("de explotación", self.made.outcome.exploitation_grid)):
            domain = edges.transition_domain(surface, start, qperf.MIN_THICKNESS_M, allowed)
            found = []
            for _ in range(RUNS):
                gc.collect()
                found.append(vperf.drive(created(surface, start, domain)))
            report = found[-1].result
            median = statistics.median(driven.total_s for driven in found)
            worst = max(worst, median)
            lines.append(
                f"superficie {label} ({count(int(np.count_nonzero(domain)))} celdas movidas, "
                f"{count(report.pairs)} parejas del borde, {number(report.within_pct, 2)} % "
                f"dentro, el mayor {number(report.maximum_m, 2)} m, {len(report.stretches)} "
                f"tramos): {seconds_of([driven.total_s for driven in found])}; "
                f"{calls_text(found)}")
            self.assertGreater(report.pairs, 0, f"{label}: sin borde no mide nada")
        gis_perf.report(
            f"RNF-014-04: salto creado (A11) en el borde de cada superficie de la cantera sobre "
            f"{count(dperf.CELLS)} celdas de 1 m ({MACHINE}): " + "; ".join(lines)
            + f"; presupuesto {number(EDGE_BUDGET_S, 0)} s cada uno")
        self.assertLessEqual(worst, EDGE_BUDGET_S)

    def test_transitions(self) -> None:
        """RNF-014-04: «Transiciones con el terreno no afectado» de la superficie final de la
        cantera (la transición, A10, y el salto creado de la superficie nueva, A11) sobre 2,81 M
        celdas, de la primera llamada de «Calcular» a las cifras registradas por «Crear» (con la
        lectura de las dos superficies y de las máscaras, la rejilla con su hash y la tabla del
        informe), en disco local, en ≤ 5 s (mediana de 5; la primera no cuenta)."""
        data = scale()

        def transition() -> Chain:
            return chain(lambda: steps.edge_transition_run(
                data.project, fresh("Transición"), self.made.final, dperf.START,
                version=data.v1.uid, budget_s=STEP_BUDGET_S))

        found = repeat(transition)
        last = found[-1].outcome
        gis_perf.report(
            f"RNF-014-04: «Transiciones con el terreno no afectado» de la superficie final de la "
            f"cantera con {number(qperf.TRANSITION_DEG, 0)}° sobre {count(dperf.CELLS)} celdas "
            f"de 1 m (transición en {count(int(np.count_nonzero(last.domain)))} celdas, "
            f"{number(last.transition.volume_m3, 0)} m³; salto creado en "
            f"{count(last.report.pairs)} parejas), de «Calcular» a «Crear» (proyecto en disco "
            f"local; {MACHINE}): {seconds_of([item.total_s for item in found])}; "
            f"{calls_text([item.driven for item in found])}; fases de la última: "
            f"{phases_text(found[-1].driven)}; presupuesto {number(EDGE_BUDGET_S, 0)} s")
        self.assertLessEqual(statistics.median(item.total_s for item in found), EDGE_BUDGET_S)


# --- RNF-014-05: Esc ------------------------------------------------------------------------------


def temporaries(project: Any) -> int:
    """Los ficheros temporales de la carpeta del proyecto (los de las rejillas que esperan a
    «Crear»)."""
    return sum(1 for path in Path(project.root).rglob("*") if ".tmp-" in path.name)


@dataclass(frozen=True, slots=True)
class Stopped:
    """Esc en la llamada ``at`` de un cálculo (``elapsed_s`` después de empezar): la fase en que
    estaba, los temporales que había y lo que tardó cerrar los pasos."""

    at: int
    elapsed_s: float
    phase: str
    temporaries: int
    closing_s: float


def stop_when(start: Callable[[], Iterator[Any]], project: Any,
              ready: Callable[[float, int], bool]) -> Stopped:
    """Lleva los pasos de ``start()`` hasta el primero tras el que ``ready(segundos desde que
    empezó, temporales del proyecto)`` y los cierra (Esc): lo que tarda cerrarlos. Si el cálculo
    termina antes, ``AssertionError``."""
    began = time.perf_counter()
    work = start()
    at = 0
    while True:
        step = next(work)
        at += 1
        if step.result is not None:
            work.close()
            step.result.discard()
            raise AssertionError(f"el cálculo terminó (llamada {at}) antes del momento de Esc")
        elapsed, waiting = time.perf_counter() - began, temporaries(project)
        if ready(elapsed, waiting):
            break
    closing = time.perf_counter()
    work.close()
    return Stopped(at, elapsed, step.phase, waiting, time.perf_counter() - closing)


class EscMixin:
    """Esc a mitad de un cálculo y con todas sus rejillas ya en los temporales, sin dejar nada en
    el proyecto."""

    def escape(self, label: str, start: Callable[[], Iterator[Any]]) -> tuple[str, float]:
        """Lleva ``start`` entero una vez (y descarta lo calculado) para saber lo que tarda, su
        llamada más larga y sus temporales; después lo cierra (Esc) a mitad de ese tiempo y en
        cuanto están todos sus temporales, y comprueba cada vez que el proyecto queda como
        estaba. Devuelve la línea del informe y lo que tarda Esc en el peor caso: la llamada más
        larga del cálculo más cerrar los pasos."""
        test: Any = self
        project = scale().project
        before = project_state(project)
        gc.collect()
        full = vperf.drive(start)
        waiting = temporaries(project)
        full.result.discard()
        test.assertGreater(waiting, 0, f"{label}: sin temporales no mide nada")
        test.assertEqual(project_state(project), before, f"{label}: «Cancelar» dejó algo")
        stops = []
        for ready in (lambda elapsed, _found: elapsed >= full.total_s / 2,
                      lambda _elapsed, found: found >= waiting):
            gc.collect()
            stopped = stop_when(start, project, ready)
            test.assertEqual(project_state(project), before,
                             f"{label}: Esc en la llamada {stopped.at}")
            stops.append(stopped)
        worst = full.longest_s + max(stopped.closing_s for stopped in stops)
        line = (f"{label} {number(worst * 1000, 0)} ms (la llamada más larga "
                f"{number(full.longest_s * 1000, 0)} ms en «{full.longest_phase}», de "
                f"{full.steps} en {number(full.total_s, 2)} s; cerrar "
                + " y ".join(f"{number(stopped.closing_s * 1000, 1)} ms a los "
                             f"{number(stopped.elapsed_s, 2)} s («{stopped.phase}», "
                             f"temporales: {stopped.temporaries})" for stopped in stops)
                + ")")
        return line, worst


class CancelTest(EscMixin, unittest.TestCase):
    """RNF-014-05 con el proyecto de escala: Esc en el recinto, la cantera, la transición y «solo
    relleno» (el ajuste, en :class:`RefitTest`, con su límite nuevo)."""

    made: ClassVar[Made]
    envelope: ClassVar[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.made = made_quarry()
        cls.envelope = qperf.fill_envelope(scale())

    def test_cancel(self) -> None:
        """RNF-014-05: Esc a mitad de «Límite desde el perímetro…», «Cantera con dos
        superficies…», «Transiciones con el terreno no afectado» y «Solo relleno…» sobre 2,81 M
        celdas —la llamada más larga del cálculo más cerrar los pasos, a mitad y con todas sus
        rejillas ya en los temporales— se atiende en ≤ 2 s y no deja nada en el proyecto."""
        data = scale()
        version = data.v1.uid
        cases = (
            ("recinto", lambda: steps.excavation_area_run(
                data.project, "Recinto Esc", dperf.START, version=version,
                budget_s=STEP_BUDGET_S)),
            ("cantera", lambda: steps.quarry_run(
                data.project, qperf.quarry_request("Cantera Esc"), version=version,
                budget_s=STEP_BUDGET_S)),
            ("transición", lambda: steps.edge_transition_run(
                data.project, "Transición Esc", self.made.final, dperf.START, version=version,
                budget_s=STEP_BUDGET_S)),
            ("solo relleno", lambda: steps.fill_only_run(
                data.project, qperf.fill_only_request("Relleno Esc", self.envelope),
                version=version, budget_s=STEP_BUDGET_S)))
        lines, worst = [], 0.0
        for label, start in cases:
            line, effective = self.escape(label, start)
            lines.append(line)
            worst = max(worst, effective)
        gis_perf.report(
            f"RNF-014-05: Esc a mitad de cada cálculo de la 014 sobre {count(dperf.CELLS)} celdas "
            f"(la llamada más larga más cerrar los pasos; nada queda en el proyecto): "
            f"{'; '.join(lines)}; presupuesto {number(CANCEL_BUDGET_S, 0)} s ({MACHINE})")
        self.assertLessEqual(worst, CANCEL_BUDGET_S)


# --- RNF-014-04 y RNF-014-05: el ajuste a un límite nuevo -----------------------------------------


class RefitTest(EscMixin, unittest.TestCase):
    """RNF-014-04 y RNF-014-05 con la cantera de escala y el límite legal redibujado 30 m más corto
    por el este (como CE-014-08), con las máscaras de V01 recompiladas; al terminar, el límite de
    la 013 vuelve y las máscaras se recompilan, así que el orden de las clases no importa."""

    made: ClassVar[Made]

    @classmethod
    def setUpClass(cls) -> None:
        cls.made = made_quarry()
        qperf.redraw_legal_limit(scale(), cut_back=True)
        cls.addClassCleanup(qperf.redraw_legal_limit, scale(), cut_back=False)

    def refit(self, name: str, *surfaces: str) -> Callable[[], Iterator[Any]]:
        """Los pasos del ajuste ``name`` de ``surfaces`` (por defecto, las dos de la cantera)."""
        data = scale()
        chosen = surfaces or (self.made.exploitation, self.made.final)
        request = model.RefitRequest(name, chosen, dperf.START)
        return lambda: steps.refit_run(data.project, request, version=data.v1.uid,
                                       budget_s=STEP_BUDGET_S)

    def test_refit(self) -> None:
        """RNF-014-04: «Ajustar el diseño a un límite nuevo…» de las dos superficies de la cantera
        en una sola orden (cada una con la cara del perfil de su sector) sobre 2,81 M celdas, de la
        primera llamada de «Calcular» a las cifras registradas por «Crear» (con la lectura de las
        superficies y de las máscaras, las dos rejillas con su hash y la transacción), en disco
        local, en ≤ 5 s (mediana de 5; la primera no cuenta); y, también ≤ 5 s, el de una sola (la
        de explotación)."""
        lines, medians = [], []
        for label, surfaces in (("las dos superficies", ()),
                                ("solo la de explotación", (self.made.exploitation,))):
            found = repeat(lambda surfaces=surfaces: chain(self.refit(fresh("Ajuste"),
                                                                      *surfaces)))
            refits = found[-1].outcome.refits
            for refit in refits:
                self.assertTrue(refit.needed, f"{refit.surface}: el límite nuevo no la corta")
            medians.append(statistics.median(item.total_s for item in found))
            lines.append(
                f"{label} ("
                + "; ".join(f"{refit.surface}: {count(refit.cells)} celdas, "
                            f"{count(refit.outside_cells)} fuera, {number(refit.volume_m3, 0)} m³"
                            for refit in refits)
                + f"): {seconds_of([item.total_s for item in found])}; "
                f"{calls_text([item.driven for item in found])}; fases de la última: "
                f"{phases_text(found[-1].driven)}")
        gis_perf.report(
            f"RNF-014-04: ajuste de la cantera al límite legal {number(qperf.CUT_BACK_M, 0)} m "
            f"más corto por el este sobre {count(dperf.CELLS)} celdas de 1 m, de «Calcular» a "
            f"«Crear» (proyecto en disco local; {MACHINE}): " + "; ".join(lines)
            + f"; presupuesto {number(REFIT_BUDGET_S, 0)} s cada uno")
        for median in medians:
            self.assertLessEqual(median, REFIT_BUDGET_S)

    def test_cancel(self) -> None:
        """RNF-014-05: Esc a mitad de «Ajustar el diseño a un límite nuevo…» de las dos
        superficies sobre 2,81 M celdas —la llamada más larga del cálculo más cerrar los pasos, a
        mitad y con las dos rejillas ya en los temporales— se atiende en ≤ 2 s y no deja nada en
        el proyecto."""
        line, worst = self.escape("ajuste", self.refit("Ajuste Esc"))
        gis_perf.report(
            f"RNF-014-05: Esc a mitad del ajuste a un límite nuevo sobre {count(dperf.CELLS)} "
            f"celdas (la llamada más larga más cerrar los pasos; nada queda en el proyecto): "
            f"{line}; presupuesto {number(CANCEL_BUDGET_S, 0)} s ({MACHINE})")
        self.assertLessEqual(worst, CANCEL_BUDGET_S)


if __name__ == "__main__":
    unittest.main()
