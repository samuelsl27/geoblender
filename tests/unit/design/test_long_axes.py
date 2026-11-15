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

import math
import random
import time
import unittest
from collections.abc import Generator, Sequence
from typing import Any
from unittest import mock

import numpy as np

from tests.support import constraints_data as cdata
from tests.support import entity_fixtures as efx
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter
from tests.unit.design import test_entities_promoted as promoted
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


class AbscissaEquivalenceTest(unittest.TestCase):
    """RNF-015-03, RF-015-29 (hallazgos D-2, A-3): ``axis_abscissa`` y ``axis_abscissa_units`` dan **lo de
    siempre** bit a bit."""

    def test_names_are_public_and_the_old_one_is_the_whole_run(self) -> None:
        """``axis_abscissa_units`` es público (``__all__`` y documentación) y ``axis_abscissa`` es sus unidades
        llevadas hasta el final."""
        self.assertIn("axis_abscissa_units", quarry.__all__)
        self.assertTrue(quarry.axis_abscissa_units.__doc__.strip())
        paths = promoted.broken_paths()
        whole = (slice(0, promoted.qfx.GRID.nrows), slice(0, promoted.qfx.GRID.ncols))
        (sigma, reach), ceded = drain(quarry.axis_abscissa_units(paths, promoted.HALF_M, promoted.qfx.GRID, whole))
        again = quarry.axis_abscissa(paths, promoted.HALF_M, promoted.qfx.GRID, whole)
        same_bits(self, sigma, again[0], "σ")
        same_bits(self, reach, again[1], "σ sin recortar")
        self.assertGreater(ceded, 1, "la cantera de la 014 (400 × 400 celdas) ya cede el hilo")

    def test_the_l_axis_of_the_quarry_is_what_it_was(self) -> None:
        """RF-014-09 (el corredor en L del H2 de la cantera sintética, antes y después de la T44): las mismas
        cifras de ``test_entities_promoted`` y, además, los mismos bytes que la copia de lo de antes, en la
        rejilla entera y en la ventana que la corta."""
        grid = promoted.qfx.GRID
        for window in (promoted.WHOLE, promoted.SUB_WINDOW):
            with self.subTest(window=window):
                want = reference_axis_abscissa(promoted.broken_paths(), promoted.HALF_M, grid, window)
                got = quarry.axis_abscissa(promoted.broken_paths(), promoted.HALF_M, grid, window)
                same_bits(self, got[0], want[0], "σ")
                same_bits(self, got[1], want[1], "σ sin recortar")
        sigma, _ = quarry.axis_abscissa(promoted.broken_paths(), promoted.HALF_M, grid, promoted.WHOLE)
        self.assertEqual(int(np.isfinite(sigma).sum()), promoted.BEFORE_CELLS)

    def test_a_battery_of_random_axes_is_bit_for_bit_the_old_result(self) -> None:
        """90 ejes al azar (uno a tres caminos, los estilos de :func:`random_path`, tres rejillas, seis medios
        anchos y ventanas que cortan o no tocan el eje): ``σ`` y la abscisa sin recortar, byte a byte."""
        rng = random.Random(44)
        for case in range(90):
            grid = GRIDS[case % len(GRIDS)]
            paths = [random_path(rng, grid) for _ in range(rng.choice((1, 1, 1, 2, 3)))]
            half = rng.choice(HALVES) * rng.choice((1.0, 1.0, 0.5, 2.0))
            window = random_window(rng, grid)
            with self.subTest(case=case, half=half, window=window, paths=len(paths)):
                want = reference_axis_abscissa(paths, half, grid, window)
                got = quarry.axis_abscissa(paths, half, grid, window)
                same_bits(self, got[0], want[0], "σ")
                same_bits(self, got[1], want[1], "σ sin recortar")

    def test_degenerate_axes(self) -> None:
        """Sin tramos con longitud (un punto, dos iguales), sin caminos, una ventana vacía y una ventana fuera
        del eje: lo de antes (todo ``NaN`` y del tamaño de la ventana)."""
        grid = SMALL
        whole = (slice(0, grid.nrows), slice(0, grid.ncols))
        point = absolute(grid, [(30.0, 30.0)])
        twice = absolute(grid, [(30.0, 30.0), (30.0, 30.0)])
        far = absolute(grid, [(5.0, 5.0), (9.0, 9.0)])
        cases = (([], whole), ([point], whole), ([twice], whole), ([far], (slice(80, 90), slice(80, 90))),
                 ([far], (slice(10, 10), slice(0, 30))), ([far], (slice(0, 30), slice(20, 20))))
        for paths, window in cases:
            with self.subTest(paths=len(paths), window=window):
                want = reference_axis_abscissa(paths, 3.0, grid, window)
                got = quarry.axis_abscissa(paths, 3.0, grid, window)
                same_bits(self, got[0], want[0], "σ")
                same_bits(self, got[1], want[1], "σ sin recortar")

    def test_a_long_axis_with_a_thousand_vertices_is_what_it_was(self) -> None:
        """A-3: 1.000 vértices en una rejilla de 200 × 200 celdas (1,8 km de eje en 2,81 M celdas era lo
        que tardaba 22 s con lo de antes): los mismos bytes."""
        grid = gis.Grid(699_700.0, 4_400_000.0, 1.0, 1.0, 200, 200)
        t = np.linspace(0.0, 1.0, 1000)
        paths = [absolute(grid, list(zip(15.0 + 170.0 * t, 100.0 + 70.0 * np.sin(9.0 * t), strict=True)))]
        window = (slice(0, 200), slice(0, 200))
        want = reference_axis_abscissa(paths, 6.0, grid, window)
        got = quarry.axis_abscissa(paths, 6.0, grid, window)
        same_bits(self, got[0], want[0], "σ")
        same_bits(self, got[1], want[1], "σ sin recortar")
        self.assertGreater(int(np.isfinite(got[0]).sum()), 3000)


class NearestEquivalenceTest(unittest.TestCase):
    """RNF-015-03, RF-015-29 (hallazgo A-3): la abscisa del eje de un polígono, lo de siempre bit a bit en las
    celdas que importan (las de la huella) y, sin ellas, en todas."""

    def test_a_battery_of_random_axes_is_bit_for_bit_the_old_result(self) -> None:
        """60 ejes al azar (los estilos de :func:`random_path`) en cajas que cortan la rejilla, con y sin la
        máscara de las celdas que se miden (un óvalo y celdas sueltas): en todas las celdas sin máscara y en
        las de la máscara con ella."""
        rng = random.Random(45)
        for case in range(60):
            grid = GRIDS[case % len(GRIDS)]
            path = random_path(rng, grid)
            while float(np.hypot(*np.diff(path, axis=0).T).sum()) <= 0.0:
                path = random_path(rng, grid)
            window = random_window(rng, grid)
            rows, cols = window
            shape = (rows.stop - rows.start, cols.stop - cols.start)
            y, x = np.mgrid[0:shape[0], 0:shape[1]]
            oval = ((x - shape[1] / 2) / max(shape[1] / 2, 1)) ** 2 + ((y - shape[0] / 2) / max(shape[0] / 2, 1)) ** 2 < 0.7
            needed = oval | (np.random.default_rng(case).random(shape) < 0.03)
            want = reference_nearest_abscissa(path, grid, rows, cols)
            with self.subTest(case=case, window=window):
                (sigma, reach), _ = drain(platform._nearest_abscissa_units(path, grid, rows, cols))
                same_bits(self, sigma, want[0], "σ, sin máscara")
                same_bits(self, reach, want[1], "σ sin recortar, sin máscara")
                (sigma, reach), _ = drain(platform._nearest_abscissa_units(path, grid, rows, cols, needed))
                same_bits(self, np.where(needed, sigma, np.nan), np.where(needed, want[0], np.nan), "σ")
                same_bits(self, np.where(needed, reach, np.nan), np.where(needed, want[1], np.nan),
                          "σ sin recortar")

    def test_a_long_wavy_axis_is_what_it_was(self) -> None:
        """Un eje de 600 vértices que serpentea en 130 × 100 m: lo de antes, también con la máscara de un
        polígono lejos del eje (donde la celda más próxima es un tramo de más lejos)."""
        grid = SMALL
        t = np.linspace(0.0, 1.0, 600)
        path = absolute(grid, list(zip(5.0 + 125.0 * t, 60.0 + 30.0 * np.sin(14.0 * t), strict=True)))
        rows, cols = slice(0, 120), slice(0, 140)
        want = reference_nearest_abscissa(path, grid, rows, cols)
        (sigma, reach), ceded = drain(platform._nearest_abscissa_units(path, grid, rows, cols))
        same_bits(self, sigma, want[0], "σ")
        same_bits(self, reach, want[1], "σ sin recortar")
        self.assertGreaterEqual(ceded, 20, "una unidad por tesela de 32 × 32 (4 × 5) como mínimo")


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


class FootprintEquivalenceTest(unittest.TestCase):
    """RF-015-19, RF-015-08, RNF-015-03 (hallazgos D-2 y A-3): la huella entera de la plataforma, con las
    funciones de antes en lugar de las nuevas, es la misma bit a bit."""

    def footprint(self, job: Any, *, before: bool) -> Any:
        """La huella de ``job`` con las funciones nuevas o, con ``before``, con las de antes en su lugar."""
        if not before:
            return platform.platform_footprint(job)
        with (mock.patch.object(platform, "axis_abscissa_units", reference_axis_units),
              mock.patch.object(platform, "_nearest_abscissa_units", reference_nearest_units)):
            return platform.platform_footprint(job)

    def same(self, job: Any, label: str) -> Any:
        new, old = self.footprint(job, before=False), self.footprint(job, before=True)
        self.assertEqual(new.window, old.window, label)
        same_bits(self, new.cells, old.cells, f"{label}: la huella")
        same_bits(self, new.sigma, old.sigma, f"{label}: σ")
        same_bits(self, new.levels, old.levels, f"{label}: la rasante")
        self.assertEqual((new.axis, new.length_m, new.start_level_m, new.gradient_pct, new.notices),
                         (old.axis, old.length_m, old.start_level_m, old.gradient_pct, old.notices), label)
        return new

    def test_the_footprints_of_the_quarry_layers_are_what_they_were(self) -> None:
        """Cada eje y cada polígono (con su eje enlazado o sin él) de las capas de plataformas de la cantera
        sintética (T01): lo mismo que con las funciones de antes."""
        for spec in efx.AXES:
            if spec.defect is not None or spec.width_m is None:
                continue
            with self.subTest(axis=spec.name):
                self.same(fp.axis_job(spec.name), spec.name)
        for spec in efx.POLYGONS:
            for linked in (True, False):
                if spec.defect is not None or (linked and spec.axis is None):
                    continue
                with self.subTest(polygon=spec.name, linked=linked):
                    self.same(fp.polygon_job(spec.name, linked=linked), spec.name)

    def test_random_long_lines_and_linked_axes_are_what_they_were(self) -> None:
        """Líneas de 20 a 400 vértices que serpentean (y que no se cortan) y polígonos con un eje enlazado que
        los cruza de lado a lado con 20 a 300 vértices: lo mismo, con varios anchos y alcances."""
        rng = random.Random(48)
        grid = SMALL
        terrain = np.full(grid.shape, 150.0)
        for case in range(6):
            n = rng.choice((20, 80, 400))
            t = np.linspace(0.0, 1.0, n)
            amplitude = rng.uniform(5.0, 25.0)
            path = absolute(grid, list(zip(10.0 + 120.0 * t, 60.0 + amplitude * np.sin(rng.uniform(2.0, 8.0) * t),
                                           strict=True)))
            width = rng.choice((2.0, 6.0, 14.0))
            job = fp.make_job(platform.PlatformGeometry("line", ((path,),)), fp.line_request("Larga"),
                              fp.values(width_m=width, start_level_m=148.0, gradient_pct=rng.choice((0.0, 1.5, -2.0)),
                                        reach_m=rng.choice((5.0, 12.0))), start=terrain, grid=grid)
            with self.subTest(line=case, vertices=n, width=width):
                self.same(job, f"línea {n} vértices")
        ring = absolute(grid, [(25.0, 20.0), (115.0, 20.0), (115.0, 95.0), (25.0, 95.0), (25.0, 20.0)])
        for n in (3, 40, 300):
            t = np.linspace(0.0, 1.0, n)
            axis = absolute(grid, list(zip(10.0 + 120.0 * t, 57.5 + 12.0 * np.sin(11.0 * t), strict=True)))
            geometry = platform.PlatformGeometry("polygon", ((ring,),), axis_parts=((axis,),), axis_name="eje")
            job = fp.make_job(geometry, fp.polygon_request("Explanada", linked=True),
                              fp.values(start_level_m=148.0, gradient_pct=0.8, reach_m=8.0), start=terrain, grid=grid)
            with self.subTest(polygon_axis_vertices=n):
                self.same(job, f"polígono con eje de {n} vértices")


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


class PacingTest(unittest.TestCase):
    """RNF-015-03, RNF-015-05, RF-015-29 (hallazgos D-2 y A-3): un eje de muchos vértices cede el hilo, ninguna
    llamada pasa de 0,2 s de CPU y cerrar a mitad (Esc) no deja nada."""

    def test_the_footprint_is_public_and_the_whole_one_is_its_units(self) -> None:
        """``platform_footprint_units`` es público (``__all__``, documentación) y ``platform_footprint``, sus
        unidades hasta el final: la misma huella."""
        self.assertIn("platform_footprint_units", platform.__all__)
        self.assertTrue(platform.platform_footprint_units.__doc__.strip())
        job = fp.axis_job("Plataforma de taller")
        stepped, ceded = drain(platform.platform_footprint_units(job))
        whole = platform.platform_footprint(job)
        same_bits(self, stepped.sigma, whole.sigma, "σ")
        same_bits(self, stepped.levels, whole.levels, "la rasante")
        self.assertGreater(ceded, 1, "una plataforma de 200 m ya cede el hilo")

    def test_a_400_vertex_axis_of_1800_m_on_2_81_million_cells_never_holds_the_thread(self) -> None:
        """RNF-015-03, D-2: 1,8 km con 400 vértices sobre la rejilla de 2,81 M celdas (9 s de una sola llamada
        antes): ninguna llamada pasa de 0,2 s de CPU, cede muchas veces y da la huella de un eje de ≈ 1,8 km."""
        job = wavy_line(BIG, 400)
        began = time.process_time()
        footprint, longest, units = timed(platform.platform_footprint_units(job))
        total = time.process_time() - began
        self.assertLess(longest, CPU_LIMIT_S, f"una unidad de {longest:.3f} s de CPU")
        self.assertLess(total, TOTAL_LIMIT_S, f"{total:.2f} s de CPU en total (9 s con lo de antes)")
        self.assertGreater(units, 100, "la huella no se parte en unidades")
        self.assertGreater(footprint.axis.length_m, 1700.0)
        self.assertGreater(footprint.cell_count, 30_000)
        _, longest, steps = paced(platform.platform_footprint_units(job))
        self.assertLess(longest, CPU_LIMIT_S, f"una llamada de {longest:.3f} s de CPU")
        self.assertGreaterEqual(steps, 1)

    def test_the_footprint_of_a_long_axis_is_bit_for_bit_the_old_one_at_scale(self) -> None:
        """RF-015-19: con 400 vértices y 1.000 vértices en 2,81 M celdas la huella es la de antes (la de antes,
        14 y 22 s de CPU: se compara aquí con la rejilla de 200 × 200 y, a escala, con la de las celdas que
        el eje toca: la caja de la huella)."""
        grid = gis.Grid(699_700.0, 4_400_000.0, 1.0, 1.0, 300, 260)
        for vertices in (400, 1000):
            job = wavy_line(grid, vertices, length_m=220.0, width=10.0)
            new = platform.platform_footprint(job)
            with mock.patch.object(platform, "axis_abscissa_units", reference_axis_units):
                old = platform.platform_footprint(job)
            with self.subTest(vertices=vertices):
                self.assertEqual(new.window, old.window)
                same_bits(self, new.cells, old.cells, "la huella")
                same_bits(self, new.sigma, old.sigma, "σ")
                same_bits(self, new.levels, old.levels, "la rasante")

    def test_a_dense_axis_cedes_inside_a_tile_and_is_what_it_was(self) -> None:
        """RNF-015-03, A-3: 3.000 vértices en una zona de 25 × 25 m (todos los tramos llegan a las mismas
        teselas: miles de tramos por tesela) ceden el hilo **dentro de la tesela**, no una vez por tesela, y
        dan lo de antes bit a bit."""
        grid = SMALL
        t = np.linspace(0.0, 1.0, 3000)
        path = absolute(grid, list(zip(45.0 + 25.0 * t, 45.0 + 12.0 * np.sin(220.0 * t), strict=True)))
        window = (slice(30, 90), slice(30, 90))
        (sigma, reach), ceded = drain(quarry.axis_abscissa_units([path], 4.0, grid, window))
        want = reference_axis_abscissa([path], 4.0, grid, window)
        same_bits(self, sigma, want[0], "σ")
        same_bits(self, reach, want[1], "σ sin recortar")
        self.assertGreater(ceded, 60, "no cede el hilo dentro de la tesela")
        (sigma, reach), ceded = drain(platform._nearest_abscissa_units(path, grid, *window))
        want = reference_nearest_abscissa(path, grid, *window)
        same_bits(self, sigma, want[0], "σ del polígono")
        same_bits(self, reach, want[1], "σ sin recortar del polígono")
        self.assertGreater(ceded, 60, "no cede el hilo dentro de la tesela")

    def test_the_linked_axis_and_the_outline_check_cede_step_by_step(self) -> None:
        """RF-015-29, A-3: el eje enlazado de 1.000 vértices frente a un contorno de 2.000 cede el hilo (una
        unidad por tramo, más los bloques de puntos medios), y el contorno, tramo a tramo."""
        grid = BIG
        angle = np.linspace(0.0, 2.0 * np.pi, 2000, endpoint=False)
        ring = absolute(grid, [(900.0 + 300.0 * math.cos(a), 800.0 + 200.0 * math.sin(a)) for a in angle]
                        + [(1200.0, 800.0)])
        t = np.linspace(0.0, 1.0, 1000)
        axis = absolute(grid, list(zip(550.0 + 700.0 * t, 800.0 + 40.0 * np.sin(30.0 * t), strict=True)))
        job = fp.make_job(platform.PlatformGeometry("polygon", ((ring,),), axis_parts=((axis,),), axis_name="eje"),
                          fp.polygon_request("Explanada", linked=True),
                          fp.values(start_level_m=148.0, gradient_pct=0.0, reach_m=15.0),
                          start=np.full(grid.shape, 150.0), grid=grid)
        parts, rings_ceded = drain(platform._polygon_rings_units(job))
        self.assertGreater(rings_ceded, 1500, "el contorno no cede el hilo tramo a tramo")
        found, ceded = drain(platform._linked_axis_units(job, parts))
        self.assertGreater(ceded, 900, "el eje enlazado no cede el hilo tramo a tramo")
        self.assertGreater(found.length_m, 600.0)

    def test_esc_in_the_middle_is_quick_and_leaves_the_input_as_it_was(self) -> None:
        """RNF-015-05, RF-015-29: cerrar el generador después de unos pasos (Esc) tarda ≤ 2 s, no deja el
        generador a medias y no modifica nada de lo leído (la superficie, las máscaras y la geometría)."""
        job = wavy_line(BIG, 400)
        start, cut = job.start.copy(), job.cut_allowed.copy()
        path = job.geometry.parts[0][0].copy()
        work = platform.platform_footprint_units(job)
        for _ in range(60):
            next(work)
        began = time.perf_counter()
        work.close()
        self.assertLess(time.perf_counter() - began, ESC_LIMIT_S)
        self.assertIsNone(work.gi_frame, "el generador sigue abierto")
        np.testing.assert_array_equal(job.start, start)
        np.testing.assert_array_equal(job.cut_allowed, cut)
        np.testing.assert_array_equal(job.geometry.parts[0][0], path)

    def test_a_long_polygon_axis_and_a_long_self_crossing_check_yield_in_small_steps(self) -> None:
        """RNF-015-03, A-3: un polígono con un eje enlazado de 500 vértices sobre la rejilla grande y una
        línea de 3.000 vértices que se corta a sí misma al final (el cruce se busca tramo a tramo: lo de antes
        eran 0,4 s en una llamada): llamadas de ≤ 0,2 s de CPU, y el rechazo es el de siempre, con el mismo
        punto."""
        grid = BIG
        ring = absolute(grid, [(700.0, 700.0), (1100.0, 700.0), (1100.0, 1000.0), (700.0, 1000.0), (700.0, 700.0)])
        t = np.linspace(0.0, 1.0, 500)
        axis = absolute(grid, list(zip(650.0 + 500.0 * t, 850.0 + 60.0 * np.sin(14.0 * t), strict=True)))
        job = fp.make_job(platform.PlatformGeometry("polygon", ((ring,),), axis_parts=((axis,),), axis_name="eje"),
                          fp.polygon_request("Explanada", linked=True),
                          fp.values(start_level_m=148.0, gradient_pct=0.0, reach_m=15.0),
                          start=np.full(grid.shape, 150.0), grid=grid)
        footprint, longest, units = timed(platform.platform_footprint_units(job))
        self.assertLess(longest, CPU_LIMIT_S, f"una unidad de {longest:.3f} s de CPU")
        self.assertGreater(units, 100, "la huella no se parte en unidades")
        self.assertGreater(footprint.cell_count, 100_000)
        t = np.linspace(0.0, 1.0, 3000)
        x, y = 400.0 + 900.0 * t, 800.0 + 300.0 * np.sin(40.0 * t)
        loop = absolute(grid, list(zip(x, y, strict=True)) + [(700.0, 620.0)])
        crossing = fp.make_job(platform.PlatformGeometry("line", ((loop,),)), fp.line_request("Cruzada"),
                               fp.values(width_m=6.0, start_level_m=148.0, gradient_pct=0.0, reach_m=15.0),
                               start=np.full(grid.shape, 150.0), grid=grid)
        origin = np.array([grid.west, grid.north])
        want = reference_first_crossing([platform._dedupe(loop - origin)], closed=False)
        self.assertIsNotNone(want)
        work = compile_.pace_units(platform.platform_footprint_units(crossing), compile_.STEP_BUDGET_S)
        longest = 0.0
        with self.assertRaises(DesignError) as caught:
            while True:
                began = time.process_time()
                next(work)
                longest = max(longest, time.process_time() - began)
        self.assertEqual(caught.exception.code, "des.platform_self_intersects")
        self.assertEqual((caught.exception.values["x"], caught.exception.values["y"]),
                         (want[0] + origin[0], want[1] + origin[1]))
        self.assertLess(longest, CPU_LIMIT_S)


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


class StaleMasksCalculateTest(ops.RecomputeCase):
    """RF-015-03, RF-015-29 (hallazgo A-5, una observación): con las máscaras obsoletas, «Calcular» las compila
    antes —como una operación propia, ADR-0028, igual que la 013—, y ni la entidad ni su superficie se
    registran; Esc, en la compilación o después, o descartar el cálculo no deja ningún temporal."""

    def test_calculate_compiles_stale_masks_first_and_leaves_no_temporary_when_cancelled(self) -> None:
        """Una plataforma que protege, creada y declarada, deja las máscaras obsoletas (una declarada nueva):
        (a) Esc en medio de la compilación no deja ningún temporal ni nada en marcha, y las máscaras siguen
        obsoletas; (b) «Calcular» hasta el final las compila (el proyecto cambia: su operación propia) pero
        no registra la plataforma, y deja un solo temporal, el de su superficie; (c) descartar el cálculo no
        deja ninguno."""
        self.made(prep.request(protect=True, guard_m=3.0))
        for _ in entity_store.declare_constraints_steps(self.project, self.v1.uid):
            pass
        self.clock.advance(minutes=1)
        self.assertEqual(access.mask_state(self.project, self.v1.uid)[0].value, "stale")
        asked = prep.request(prep.WORKSHOP, start="gis_dtm_hueco")
        work = self.run_steps(asked, masks=None)
        for step in work:
            if step.phase == "compile":
                break
        else:
            self.fail("«Calcular» no compiló las máscaras obsoletas")
        work.close()
        self.assertEqual(self.temporaries(), [])
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation WHERE status = 'running'"), [(0,)])
        self.assertEqual(access.mask_state(self.project, self.v1.uid)[0].value, "stale")
        before = change_counter(self.root)
        entity_operations = self.query("SELECT count(*) FROM gb_operation WHERE op_type = 'des.platform'")
        calculation = ops.finish(self.run_steps(asked, masks=None))
        self.assertEqual(access.mask_state(self.project, self.v1.uid)[0].value, "current")
        self.assertGreater(change_counter(self.root), before, "compilar las máscaras es una operación propia")
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation WHERE op_type = 'des.platform'"),
                         entity_operations, "«Calcular» no registra la plataforma")
        self.assertEqual(len(self.temporaries()), 1)
        calculation.discard()
        self.assertEqual(self.temporaries(), [])


if __name__ == "__main__":
    unittest.main()
