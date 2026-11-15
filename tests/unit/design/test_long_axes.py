# SPDX-License-Identifier: GPL-3.0-or-later
"""Los ejes largos ceden el hilo y se cancelan, con el mismo resultado de siempre (spec 015, T44; RNF-015-03,
RNF-015-05, RF-015-29; hallazgos D-2 y A-3; plan 015 §5.4 A0 y A1).

``platform_footprint`` era **una unidad no partible** y su coste, O(vértices × caja del eje): un eje
digitalizado de 1,8 km con 400 vértices tardaba 9 s sobre la rejilla de 2,81 M celdas (14 s con 1.000, 58 s con
2.000) sin ceder el hilo de Blender ni dejar cancelar con Esc. Ahora la huella son **unidades** (cada tramo se mide
solo en las teselas que su corredor toca; los cruces del eje consigo mismo, los del eje enlazado con su polígono y
la abscisa del polígono, por bloques) y el resultado es **el mismo bit a bit**:

- **La equivalencia** (``AbscissaEquivalenceTest``, ``NearestEquivalenceTest``, ``FootprintEquivalenceTest``):
  las dos funciones de la abscisa que había (``quarry.axis_abscissa`` y la del polígono) están aquí **copiadas tal
  cual eran** (``reference_*``) y se comparan, byte a byte (el cero con signo y el ``NaN`` incluidos), con las
  nuevas sobre una batería de ejes al azar: de uno a tres caminos, con vértices repetidos, ganchos, bucles
  cerrados, ejes que vuelven sobre sí mismos (los empates), vértices justo sobre centros y bordes de celda,
  celdas no cuadradas, ventanas que cortan el eje o no lo tocan y medios anchos de 0,3 a 25 m; luego, la huella
  entera de la plataforma (línea y polígono con su eje enlazado) con las funciones antiguas en su lugar.
- **Las unidades** (``PacingTest``): con la rejilla de 1.654 × 1.699 celdas de 1 m (2,81 M), un eje de 1,8 km con
  400 vértices cede el hilo en pasos de ≤ 0,2 s de CPU (RNF-015-03), cerrar el generador a mitad (Esc) tarda
  muy poco y deja la entrada como estaba (RNF-015-05), y lo mismo un polígono con un eje enlazado de 500 vértices
  y un eje de 3.000 vértices que se corta a sí mismo; las preparaciones y el cálculo usan las unidades (no la
  huella entera).
"""

from __future__ import annotations

import random
import time
import unittest
from collections.abc import Generator, Sequence
from typing import Any
from unittest import mock

import numpy as np

from tests.support import constraints_data as cdata
from tests.support.package import import_geoblender
from tests.unit.design import test_platform_footprint as fp
from tests.unit.design import test_platform_operation as ops
from tests.unit.design import test_platform_prepare as prep

access = import_geoblender("gis.masks.access")
compile_ = import_geoblender("gis.masks.compile")
entity_store = import_geoblender("design.entity_store")
gis = import_geoblender("gis")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
platform = import_geoblender("design.platform")
quarry = import_geoblender("design.quarry")
steps = import_geoblender("design.steps")

DesignError = messages.DesignError
Window = tuple[slice, slice]

SMALL = gis.Grid(699_700.0, 4_400_000.0, 1.0, 1.0, 140, 120)
"""Una rejilla de 140 × 120 celdas de 1 m en coordenadas de UTM (el norte de 4,4 Mm: la trampa del float32)."""
WIDE = gis.Grid(699_700.0, 4_400_000.0, 2.5, 1.5, 90, 100)
"""Celdas no cuadradas (2,5 × 1,5 m)."""
ODD = gis.Grid(699_700.5, 4_400_000.25, 0.7, 1.3, 130, 90)
"""Una rejilla cuyos bordes de celda no caen en enteros."""
GRIDS = (SMALL, WIDE, ODD)
BIG = gis.Grid(cdata.WEST, cdata.SOUTH + cdata.ROWS, 1.0, 1.0, cdata.COLS, cdata.ROWS)
"""La rejilla de RNF-015-01: 1.654 × 1.699 celdas de 1 m, 2,81 M."""
HALVES = (0.3, 1.0, 2.0, 4.5, 8.0, 25.0)
"""Los medios anchos de la batería (m)."""
CPU_LIMIT_S = 0.2
"""RNF-015-03: lo que hace Geoblender en cada llamada del hilo de Blender."""
ESC_LIMIT_S = 2.0
"""RNF-015-05: Esc a mitad de cualquier cálculo."""
TOTAL_LIMIT_S = 2.0
"""Lo que puede tardar la huella entera de 1,8 km y 400 vértices en 2,81 M celdas (8 s de CPU con lo de antes:
medirla por teselas es ≈ 0,1 s; este límite es grande a propósito, para no depender de la carga)."""


# --- Lo que había antes, tal cual ---------------------------------------------------------------


def reference_axis_abscissa(paths: list[np.ndarray], half: float, geometry: Any,
                            window: Window) -> tuple[np.ndarray, np.ndarray]:
    """``quarry.axis_abscissa`` de la T05 (todo el eje en toda la ventana por cada tramo), copiada tal cual."""
    rows = np.arange(window[0].start, window[0].stop, dtype=np.float64)
    cols = np.arange(window[1].start, window[1].stop, dtype=np.float64)
    shape = (rows.size, cols.size)
    best = np.full(shape, np.inf)
    sigma = np.full(shape, np.nan)
    reach = np.full(shape, np.nan)
    band = np.zeros(shape, dtype=bool)
    passes = np.zeros(shape, dtype=bool)
    limit = half * half
    walked = 0.0
    for path in paths:
        lengths = np.hypot(*np.diff(path, axis=0).T)
        segments = [i for i in range(lengths.size) if lengths[i] > 0.0]
        if not segments:
            continue
        first, last = segments[0], segments[-1]
        before, _ = quarry._segment_frame(path[first], path[first + 1], float(lengths[first]),
                                          geometry, rows, cols)
        after, _ = quarry._segment_frame(path[last], path[last + 1], float(lengths[last]), geometry,
                                         rows, cols)
        out = (before < 0.0) | (after > float(lengths[last]))
        for i in segments:
            length = float(lengths[i])
            along, across = quarry._segment_frame(path[i], path[i + 1], length, geometry, rows, cols)
            clamped = np.clip(along, 0.0, length)
            d2 = across * across + (along - clamped) ** 2
            band |= (along >= 0.0) & (along <= length) & (across * across <= limit)
            better = d2 < best
            best[better] = d2[better]
            sigma[better] = (walked + clamped)[better]
            reach[better] = (walked + along)[better]
            passes[better] = out[better]
            walked += length
    inside = band | ((best <= limit) & ~passes)
    sigma[~inside] = np.nan
    reach[~inside] = np.nan
    return sigma, reach


def reference_nearest_abscissa(path: np.ndarray, grid: Any, rows: slice, cols: slice
                               ) -> tuple[np.ndarray, np.ndarray]:
    """``platform._nearest_abscissa`` de la T06 (la abscisa del punto más próximo del eje de un polígono en
    todas las celdas de la caja), copiada tal cual."""
    row_index = np.arange(rows.start, rows.stop, dtype=np.float64)
    col_index = np.arange(cols.start, cols.stop, dtype=np.float64)
    shape = (row_index.size, col_index.size)
    best = np.full(shape, np.inf)
    sigma = np.full(shape, np.nan)
    reach = np.full(shape, np.nan)
    lengths = np.hypot(*np.diff(path, axis=0).T)
    walked = 0.0
    for i in range(lengths.size):
        length = float(lengths[i])
        if not length > 0.0:
            continue
        along, across = quarry._segment_frame(path[i], path[i + 1], length, grid, row_index, col_index)
        clamped = np.clip(along, 0.0, length)
        distance2 = across * across + (along - clamped) ** 2
        better = distance2 < best
        best[better] = distance2[better]
        sigma[better] = (walked + clamped)[better]
        reach[better] = (walked + along)[better]
        walked += length
    return sigma, reach


def reference_first_crossing(rings: Sequence[np.ndarray], *, closed: bool) -> tuple[float, float] | None:
    """``platform._first_crossing`` de la T06, copiada tal cual."""
    first_edges, last_edges, identity, position, size = [], [], [], [], []
    for index, ring in enumerate(rings):
        if ring.shape[0] < 2:
            continue
        begin = ring if closed else ring[:-1]
        end = np.roll(ring, -1, axis=0) if closed else ring[1:]
        count = begin.shape[0]
        first_edges.append(begin)
        last_edges.append(end)
        identity.append(np.full(count, index))
        position.append(np.arange(count))
        size.append(np.full(count, count))
    if not first_edges:
        return None
    a, b = np.concatenate(first_edges), np.concatenate(last_edges)
    ids, pos, count = np.concatenate(identity), np.concatenate(position), np.concatenate(size)
    r = b - a
    for i in range(a.shape[0] - 1):
        j = np.arange(i + 1, a.shape[0])
        gap = pos[j] - pos[i]
        neighbours = (ids[j] == ids[i]) & ((gap == 1) | ((gap == count[i] - 1) & closed))
        j = j[~neighbours]
        if j.size == 0:
            continue
        hit, t = platform._hits(a[i], r[i], a[j], r[j])
        if hit.any():
            point = a[i] + t[int(np.flatnonzero(hit)[0])] * r[i]
            return float(point[0]), float(point[1])
    for index in range(len(rings)):
        own = ids == index
        if not own.any():
            continue
        steps, ends = r[own], b[own]
        now, then = (steps, np.roll(steps, -1, axis=0)) if closed else (steps[:-1], steps[1:])
        cross = now[:, 0] * then[:, 1] - now[:, 1] * then[:, 0]
        scale = np.hypot(now[:, 0], now[:, 1]) * np.hypot(then[:, 0], then[:, 1])
        back = (np.abs(cross) <= platform._REL * scale) & ((now * then).sum(axis=1) < 0.0)
        if back.any():
            vertex = ends[int(np.flatnonzero(back)[0])]
            return float(vertex[0]), float(vertex[1])
    return None


def reference_inside(points: np.ndarray, parts: Sequence[Sequence[np.ndarray]]) -> np.ndarray:
    """``platform._inside`` de la T06, copiada tal cual."""
    found = np.zeros(points.shape[0], dtype=bool)
    px, py = points[:, 0][:, None], points[:, 1][:, None]
    for rings in parts:
        parity = np.zeros(points.shape[0], dtype=bool)
        for ring in rings:
            a, b = ring, np.roll(ring, -1, axis=0)
            straddles = (a[:, 1][None, :] > py) != (b[:, 1][None, :] > py)
            rise = np.where(b[:, 1] == a[:, 1], 1.0, b[:, 1] - a[:, 1])
            at = a[:, 0] + (py - a[:, 1]) * (b[:, 0] - a[:, 0]) / rise
            parity ^= ((straddles & (px < at)).sum(axis=1) % 2) == 1
        found |= parity
    return found


def reference_axis_units(paths: list[np.ndarray], half: float, geometry: Any, window: Window
                         ) -> Generator[None, None, tuple[np.ndarray, np.ndarray]]:
    """:func:`reference_axis_abscissa` como unidades (una, sin ceder), para ponerla en lugar de la nueva."""
    return reference_axis_abscissa(paths, half, geometry, window)
    yield  # pragma: no cover - hace de esto un generador


def reference_nearest_units(path: np.ndarray, grid: Any, rows: slice, cols: slice, needed: Any = None
                            ) -> Generator[None, None, tuple[np.ndarray, np.ndarray]]:
    """:func:`reference_nearest_abscissa` como unidades (una, sin ceder)."""
    return reference_nearest_abscissa(path, grid, rows, cols)
    yield  # pragma: no cover


# --- La batería ---------------------------------------------------------------------------------


def absolute(grid: Any, points: Sequence[tuple[float, float]]) -> np.ndarray:
    """Puntos ``(x, profundidad)`` desde la esquina noroeste de ``grid`` (m; la profundidad, hacia el sur) como
    camino absoluto float64."""
    return np.array([(grid.west + x, grid.north - y) for x, y in points], dtype=np.float64)


def random_path(rng: random.Random, grid: Any) -> np.ndarray:
    """Un camino al azar sobre ``grid`` (algo sale de ella a veces), de uno de los estilos que dan trabajo al
    desempate y a los extremos: caminata, vértices repetidos, ganchos que vuelven por la misma recta, bucles
    cerrados, vértices alineados y vértices justo sobre centros y bordes de celda."""
    width, depth = grid.ncols * grid.dx, grid.nrows * grid.dy

    def point() -> tuple[float, float]:
        return rng.uniform(-0.1, 1.1) * width, rng.uniform(-0.1, 1.1) * depth

    style = rng.choice(("walk", "walk", "repeat", "hairpin", "loop", "aligned", "snap", "short"))
    n = rng.randint(2, 40)
    if style == "hairpin":
        a, b, c = point(), point(), point()
        points = [a, b, a, c, b]
    elif style == "loop":
        points = [point() for _ in range(rng.randint(3, 12))]
        points.append(points[0])
    elif style == "aligned":
        a, b = point(), point()
        points = [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n + 1)]
    elif style == "snap":
        step = 0.5 * min(grid.dx, grid.dy)
        points = [(round(x / step) * step, round(y / step) * step) for x, y in (point() for _ in range(n))]
    elif style == "short":
        x, y = point()
        points = [(x, y)]
        for _ in range(n):
            x += rng.uniform(-1.2, 1.2) * grid.dx
            y += rng.uniform(-1.2, 1.2) * grid.dy
            points.append((x, y))
    else:
        points = [point() for _ in range(n)]
        if style == "repeat":
            points = [p for q in points for p in ((q, q) if rng.random() < 0.4 else (q,))]
    return absolute(grid, points)


def random_window(rng: random.Random, grid: Any) -> Window:
    """Toda la rejilla, una ventana que la corta o una de una fila o columna."""
    kind = rng.choice(("whole", "box", "box", "row", "column"))
    if kind == "whole":
        return slice(0, grid.nrows), slice(0, grid.ncols)
    r0 = rng.randrange(0, grid.nrows - 1)
    c0 = rng.randrange(0, grid.ncols - 1)
    if kind == "row":
        return slice(r0, r0 + 1), slice(c0, rng.randrange(c0 + 1, grid.ncols + 1))
    if kind == "column":
        return slice(r0, rng.randrange(r0 + 1, grid.nrows + 1)), slice(c0, c0 + 1)
    return (slice(r0, rng.randrange(r0 + 1, grid.nrows + 1)),
            slice(c0, rng.randrange(c0 + 1, grid.ncols + 1)))


def drain[T](units: Generator[None, None, T]) -> tuple[T, int]:
    """Lo que devuelve ``units`` y cuántas veces cedió."""
    ceded = 0
    while True:
        try:
            next(units)
        except StopIteration as done:
            return done.value, ceded
        ceded += 1


def same_bits(test: unittest.TestCase, got: np.ndarray, want: np.ndarray, label: str) -> None:
    """``got`` es ``want`` byte a byte (el ``NaN``, el cero con signo y la forma incluidos)."""
    test.assertEqual(got.shape, want.shape, f"{label}: la forma")
    test.assertEqual(got.dtype, want.dtype, f"{label}: el tipo")
    test.assertEqual(got.tobytes(), want.tobytes(), f"{label}: no es bit a bit lo de antes")


# --- La equivalencia ----------------------------------------------------------------------------


class BigWindowTest(unittest.TestCase):
    """RNF-015-03, A-3: una ventana grande con un eje de pocos tramos (cada tesela, un candidato) cede el hilo
    una vez por tesela como mínimo, no una vez en total."""

    def test_a_two_vertex_axis_on_a_big_window_cedes_once_per_tile(self) -> None:
        """El eje principal de un polígono (dos vértices) sobre 600 × 600 celdas = 19 × 19 teselas de 32: lo de
        antes bit a bit y al menos 361 cesiones."""
        grid = BIG
        path = absolute(grid, [(300.0, 800.0), (1000.0, 1100.0)])
        rows, cols = slice(700, 1300), slice(300, 900)
        want = reference_nearest_abscissa(path, grid, rows, cols)
        (sigma, reach), ceded = drain(platform._nearest_abscissa_units(path, grid, rows, cols))
        same_bits(self, sigma, want[0], "σ")
        same_bits(self, reach, want[1], "σ sin recortar")
        self.assertGreaterEqual(ceded, 361)


class CrossingEquivalenceTest(unittest.TestCase):
    """RF-015-08, RF-015-29: la comprobación de que un eje no se corta (``_first_crossing_units``) y la del
    eje enlazado dentro de su polígono (``_inside_units``) dan lo de antes, por bloques."""

    def test_the_first_crossing_is_the_same_point_and_it_cedes(self) -> None:
        """80 caminos y anillos al azar (con cruces, contactos, solapes y ganchos): el mismo primer punto (o
        ninguno) que la copia de lo de antes; con tramos que comprobar, cede el hilo."""
        rng = random.Random(46)
        for case in range(80):
            rings = [np.array([(rng.uniform(0, 140), rng.uniform(0, 120)) for _ in range(rng.randint(3, 14))])
                     for _ in range(rng.choice((1, 1, 2)))]
            closed = rng.random() < 0.5
            with self.subTest(case=case, closed=closed):
                want = reference_first_crossing(rings, closed=closed)
                got, ceded = drain(platform._first_crossing_units(rings, closed=closed))
                self.assertEqual(got, want)
                self.assertGreater(ceded, 0, "no cede el hilo")

    def test_the_polygon_test_by_blocks_is_the_old_one(self) -> None:
        """Un polígono de 2.000 vértices con un hueco y 700 puntos (más de un bloque): el mismo par-impar que
        antes."""
        rng = np.random.default_rng(47)
        angle = np.linspace(0.0, 2.0 * np.pi, 2000, endpoint=False)
        outer = np.column_stack((60.0 * np.cos(angle), 40.0 * np.sin(angle)))
        hole = np.column_stack((15.0 * np.cos(angle[:300] * 6.6), 10.0 * np.sin(angle[:300] * 6.6)))
        parts = [[outer, hole], [outer + np.array([200.0, 0.0])]]
        points = np.column_stack((rng.uniform(-70.0, 270.0, 700), rng.uniform(-50.0, 50.0, 700)))
        got, ceded = drain(platform._inside_units(points, parts))
        np.testing.assert_array_equal(got, reference_inside(points, parts))
        self.assertGreater(ceded, 1)
        empty, _ = drain(platform._inside_units(points[:0], parts))
        self.assertEqual(empty.shape, (0,))


# --- Las unidades -------------------------------------------------------------------------------


def wavy_line(grid: Any, vertices: int, length_m: float = 1800.0, width: float = 20.0,
              **changes: Any) -> Any:
    """El trabajo de una línea que serpentea ``length_m`` m con ``vertices`` vértices, en el medio de ``grid``,
    sobre un terreno plano."""
    t = np.linspace(0.0, 1.0, vertices)
    x = 0.5 * (grid.ncols * grid.dx - length_m * 0.9) + 0.9 * length_m * t
    y = 0.5 * grid.nrows * grid.dy + 0.12 * length_m * np.sin(6.0 * t)
    path = absolute(grid, list(zip(x, grid.nrows * grid.dy - y, strict=True)))
    geometry = platform.PlatformGeometry("line", ((path,),))
    parameters = fp.values(width_m=width, start_level_m=148.0, gradient_pct=0.5, reach_m=15.0)
    parameters.update(changes)
    return fp.make_job(geometry, fp.line_request("Eje largo"), parameters,
                       start=np.full(grid.shape, 150.0), grid=grid)


def timed(work: Generator[Any, None, Any]) -> tuple[Any, float, int]:
    """Lo que devuelve ``work`` llevada hasta el final, el **mayor tiempo de CPU de una llamada** (s: lo que
    cada ``next`` deja el hilo ocupado) y cuántas veces cedió."""
    longest, ceded = 0.0, 0
    while True:
        started = time.process_time()
        try:
            next(work)
        except StopIteration as done:
            return done.value, max(longest, time.process_time() - started), ceded
        longest = max(longest, time.process_time() - started)
        ceded += 1


def paced(units: Generator[None, None, Any]) -> tuple[Any, float, int]:
    """Lo que devuelve ``units`` agrupadas como lo hace la interfaz (``pace_units`` con el presupuesto de
    ``STEP_BUDGET_S``), el **mayor tiempo de CPU de una llamada** (s) y los pasos."""
    return timed(compile_.pace_units(units, compile_.STEP_BUDGET_S))


class WiringTest(ops.OperationCase):
    """RF-015-29 (hallazgo D-2): la preparación y el cálculo usan las unidades de la huella, no la entera."""

    def counting(self) -> tuple[list[int], Any]:
        """Un sustituto de ``platform_footprint_units`` que cuenta sus llamadas y sus unidades."""
        calls: list[int] = []
        real = platform.platform_footprint_units

        def wrapper(job: Any) -> Generator[None, None, Any]:
            calls.append(0)
            units = real(job)
            try:
                while True:
                    next(units)
                    calls[-1] += 1
                    yield
            except StopIteration as done:
                return done.value

        return calls, wrapper

    def test_preparing_and_calculating_run_the_footprint_by_units(self) -> None:
        """``prepare_platform_units`` calcula la huella con ``platform_footprint_units`` (una vez, en varias
        unidades) y ``platform_compute_steps`` sin ella (la reproducción) también, con los pasos de su
        ``Progress``; con la huella ya calculada no la repite."""
        calls, wrapper = self.counting()
        with mock.patch.object(entity_store, "platform_footprint_units", wrapper):
            prepared = self.units(prep.request())
            self.assertEqual(len(calls), 1)
            self.assertGreater(calls[0], 1, "la huella no cedió el hilo al preparar")
            shown: list[Any] = []
            work = entity_store.platform_compute_steps(prepared.job, prepared.common)
            while True:
                try:
                    shown.append(next(work))
                except StopIteration as done:
                    outcome = done.value
                    break
            self.assertEqual(len(calls), 2)
            self.assertTrue(any("Huella" in step.message or "huella" in step.message for step in shown))
            np.testing.assert_array_equal(outcome.footprint.levels, prepared.footprint.levels)
            ops._last(entity_store.platform_compute_steps(prepared.job, prepared.common,
                                                          footprint=prepared.footprint))
            self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
