# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que queda fuera de la rejilla, sin construir una rejilla del tamaño de la restricción (spec 012,
T40; RF-012-15; RNF-012-01 y RNF-012-06; plan 012 A2 y R8; hallazgo F-4 de la verificación única).

RF-012-15 manda avisar, nombrando la restricción, del área de su zona que queda fuera de la rejilla
(m²). ``combine._outside_cells`` la medía construyendo una rejilla ampliada con la caja **entera**
de la restricción (``zone_steps`` sobre ella, con una matriz densa de la banda de filas por paso):
con la ventana de 400 × 300 celdas de 1 m, una exclusión adyacente de 5 km tardaba 0,99 s, de 20 km
14,6 s (pasos de 0,2 s) y de 50 km 88,4 s (pasos de 0,5 s). Un recinto de la Red Natura importado sin
recortar bloqueaba la interfaz y superaba de largo el RNF-012-01.

Ahora la zona de cada banda de filas de esa rejilla se calcula por **tramos**
(``coverage.band_spans`` / ``zones.touched_runs``: las celdas que toca el polígono, sin la matriz de
la banda, a coste de las celdas que cruzan las aristas) y se cuentan las que caen fuera de la
ventana banda a banda. Lo medido no cambia:

- **Los tramos son los de la matriz** (RF-012-12): ``touched_runs`` da las mismas celdas que
  ``inside_runs(whole=False)`` y ``band_spans``, las de ``band_coverage`` con una fracción mayor que
  el umbral, en polígonos al azar (con huecos, mayores que la rejilla, con celdas no cuadradas, con
  ruido de un UTM) y por bandas.
- **Las cifras de antes** (RF-012-15): lo que cuenta ``_outside_cells`` es, celda a celda, lo del
  algoritmo de antes (la zona en la rejilla ampliada menos la ventana), con polígonos, líneas y
  puntos al azar dentro, a caballo y fuera de la rejilla, y a mano: 1 km fuera, 40 × 30 m medio
  fuera y pasando el borde oeste dan 1.600, 1.200 y 1.400 m² con celdas de 5 m y 3 m de resguardo.
- **Una restricción mucho mayor que la rejilla** (RNF-012-01): la exclusión de 20 km da la cifra
  exacta que sale a mano (L² + 20·L + 88 − 7.500 m²) en menos de lo que tardaba la de 5 km.
"""

import math
import time
import unittest
from datetime import date

import numpy as np

from tests.support import constraints_fixtures as fx
from tests.support.package import import_geoblender
from tests.unit.gis.masks.test_combine import make, resolved_for

gis = import_geoblender("gis")
coverage = import_geoblender("gis.coverage")
polygons = import_geoblender("gis.polygons")
model = import_geoblender("core.constraints.model")
params = import_geoblender("core.constraints.params")
combine = import_geoblender("gis.masks.combine")
zones = import_geoblender("gis.masks.zones")

T = model.ConstraintType
G = model.GeometryKind

BASE = fx.BASE


def grid_of(ncols: int, nrows: int, dx: float = 1.0, dy: float | None = None):
    """Una rejilla desde ``fx.BASE`` (su esquina suroeste) con ``ncols`` × ``nrows`` celdas."""
    dy = dx if dy is None else dy
    return gis.Grid(BASE[0], BASE[1] + nrows * dy, dx, dy, ncols, nrows)


def constraint(rings, *, kind=G.POLYGON, ctype=T.EXCLUSION, code="r_zona"):
    """Una restricción con las partes ``rings`` (locales, m desde ``fx.BASE``): para un polígono, un
    exterior y sus huecos; para una línea o un punto, un solo camino."""
    absolute = tuple(fx.absolute(ring) for ring in rings)
    return model.Constraint(
        uid=code.ljust(32, "0"), code=code, name=code, ctype=ctype, kind=kind,
        parts=(absolute,), priority=1, reason="Prueba", decided_by="IMGA",
        decided_on=date(2026, 11, 1), decision_uid=None, intention_uid=None, source_input=None,
        source_fid=None, layer="core_constraint_polygon", fid=1)


def star(rng, centre, radius, count=None):
    """Un polígono simple con forma de estrella alrededor de ``centre`` (locales, m): vértices a un
    ángulo cada uno de los ``count`` sectores y a un radio de 0,35 a 1 veces ``radius``."""
    count = int(rng.integers(5, 25)) if count is None else count
    angles = (np.arange(count) + rng.uniform(0.05, 0.95, count)) * (2.0 * math.pi / count)
    radii = rng.uniform(0.35, 1.0, count) * radius
    return [(centre[0] + r * math.cos(a), centre[1] + r * math.sin(a))
            for r, a in zip(radii, angles, strict=True)]


def random_grid(rng):
    step_x = float(rng.choice([0.5, 1.0, 2.0, 2.5]))
    step_y = float(rng.choice([0.5, 1.0, 2.0, 2.5]))
    return grid_of(int(rng.integers(18, 50)), int(rng.integers(14, 40)), step_x, step_y)


def random_polygon(rng, grid, *, holes=True):
    """Una estrella (a veces con un hueco) de tamaño y sitio al azar respecto a ``grid``."""
    width, height = grid.ncols * grid.dx, grid.nrows * grid.dy
    centre = (rng.uniform(-0.3, 1.3) * width, rng.uniform(-0.3, 1.3) * height)
    radius = rng.uniform(0.15, 1.6) * min(width, height)
    outer = star(rng, centre, radius)
    rings = [outer]
    if holes and rng.random() < 0.4:
        rings.append(star(rng, centre, 0.28 * radius, count=6))
    return constraint(rings)


def reference_cells(item, grid, outward):
    """Las celdas de la zona de ``item`` fuera de ``grid``, como las contaba ``combine._outside_cells``
    hasta la T40: la zona en una rejilla ampliada con las mismas líneas que cubre la caja de la
    restricción (y una celda, más el resguardo) menos las celdas de la ventana. Es el oráculo."""
    segments = zones.segments_of(item, grid)
    dx, dy = grid.dx, grid.dy
    c0 = math.floor((float(segments[..., 0].min()) - outward) / dx) - 1
    c1 = math.ceil((float(segments[..., 0].max()) + outward) / dx) + 1
    s0 = math.floor((float(segments[..., 1].min()) - outward) / dy) - 1
    s1 = math.ceil((float(segments[..., 1].max()) + outward) / dy) + 1
    if c0 >= 0 and s0 >= 0 and c1 <= grid.ncols and s1 <= grid.nrows:
        return 0
    wide = gis.Grid(grid.west + c0 * dx, grid.extent.ymin + s1 * dy, dx, dy, c1 - c0, s1 - s0)
    found = zones.zone_runs(item, wide, outward)
    shift = grid.nrows - s1
    shifted = zones.Runs(found.row + shift, found.col0 + c0, found.col1 + c0)
    rows = np.arange(max(0, shift), min(grid.nrows, grid.nrows - s0), dtype=np.int64)
    window = zones.Runs(rows, np.zeros_like(rows), np.full_like(rows, grid.ncols))
    return shifted.cells - shifted.intersection(window).cells


def measured_cells(item, grid, outward, **steps):
    """Lo que cuenta ``combine._outside_cells`` ahora."""
    return polygons.drain(combine._outside_cells(item, grid, outward, **steps))


class SparseSpansTest(unittest.TestCase):
    """Los tramos de ``touched_runs`` y ``band_spans`` son las celdas de la matriz (RF-012-12)."""

    def check_same(self, item, grid, *, rows=None):
        edges = zones.edges_of(item, grid)
        dense = zones.inside_runs(edges, grid, whole=False, rows=rows)
        sparse = zones.touched_runs(edges, grid, rows=rows)
        self.assertEqual(sparse, dense, f"{sparse!r} frente a {dense!r}")
        return dense

    def test_random_polygons_give_the_cells_of_the_matrix(self) -> None:
        """Estrellas con y sin hueco, menores y mayores que la rejilla, con celdas no cuadradas: las
        mismas celdas que ``inside_runs(whole=False)``, de una vez y por bandas de filas."""
        rng = np.random.default_rng(20261101)
        total = 0
        for case in range(120):
            grid = random_grid(rng)
            item = random_polygon(rng, grid)
            with self.subTest(case=case):
                total += self.check_same(item, grid).cells
                first = int(rng.integers(0, grid.nrows))
                stop = int(rng.integers(first, grid.nrows + 1))
                self.check_same(item, grid, rows=slice(first, stop))
        self.assertGreater(total, 1000)   # no es un caso vacío

    def test_aligned_and_half_cell_rectangles(self) -> None:
        """Rectángulos con los lados sobre las líneas de la rejilla, a media celda, a una celda del
        borde, que lo cubren entero o lo desbordan por un lado: las mismas celdas."""
        grid = grid_of(30, 24, 1.0)
        boxes = [(5, 4, 17, 13), (5.5, 4.5, 17.5, 13.5), (0, 0, 30, 24), (-3, -3, 33, 27),
                 (-10, 5, 12, 9), (20, -4, 45, 30), (0, 0, 1, 1), (29, 23, 30, 24),
                 (12.25, 3.75, 12.75, 20.25), (-5, -5, -1, -1), (40, 40, 60, 60)]
        for box in boxes:
            with self.subTest(box=box):
                left, bottom, right, top = box
                ring = [(left, bottom), (right, bottom), (right, top), (left, top)]
                self.check_same(constraint([ring]), grid)

    def test_a_polygon_larger_than_the_grid(self) -> None:
        """Sus aristas dejan fuera la rejilla por los cuatro lados (sin celdas «de cruce»): toda
        ella dentro del polígono, y con un hueco que la deja vacía."""
        grid = grid_of(30, 24, 2.0)
        big = [(-100, -100), (200, -100), (200, 200), (-100, 200)]
        everything = self.check_same(constraint([big]), grid)
        self.assertEqual(everything.cells, 30 * 24)
        hole = [(-50, -50), (-50, 100), (100, 100), (100, -50)]
        self.assertEqual(self.check_same(constraint([big, hole]), grid).cells, 0)

    def test_noise_of_a_utm_and_non_square_cells(self) -> None:
        """Con 1 ulp y 1 µm de ruido hacia dentro y hacia fuera de un UTM, y con celdas de 2 × 0,5 m,
        las mismas celdas que la matriz (la tolerancia ε es la de la rejilla, T39)."""
        grid = gis.Grid(BASE[0], BASE[1] + 70.0, 2.0, 0.5, 70, 140)
        for noise in (0.0, float(np.spacing(BASE[1] + 100.0)), 1e-6, -1e-6, 1e-3):
            with self.subTest(noise=noise):
                ring = [(20 - noise, 20 - noise), (32 + noise, 20 - noise),
                        (32 + noise, 32 + noise), (20 - noise, 32 + noise)]
                self.check_same(constraint([ring]), grid)

    def test_band_spans_are_the_cells_over_a_threshold(self) -> None:
        """``coverage.band_spans`` da, como tramos, las celdas de ``band_coverage`` con una fracción
        mayor que el umbral (también uno alto), tal y como las ordena la matriz."""
        rng = np.random.default_rng(7)
        for case in range(60):
            grid = random_grid(rng)
            item = random_polygon(rng, grid)
            edges = zones.edges_of(item, grid)
            for threshold in (1e-12, 1e-6, 0.5):
                with self.subTest(case=case, threshold=threshold):
                    band = coverage.band_coverage(edges, grid, slice(0, grid.nrows))
                    keep = band.fraction > threshold
                    want = zones.Runs(band.rows[keep], band.cols[keep], band.cols[keep] + 1)
                    row, col0, col1 = coverage.band_spans(edges, grid, slice(0, grid.nrows),
                                                          threshold)
                    self.assertEqual(zones.Runs(row, col0, col1), want)

    def test_invalid_input_is_a_program_error(self) -> None:
        """Como ``band_coverage``: aristas que no son ``(n, 2, 2)``, no finitas o una banda con
        paso son un ``ValueError``; sin aristas o una banda vacía, ningún tramo."""
        grid = grid_of(10, 10)
        edges = zones.edges_of(constraint([[(2, 2), (6, 2), (6, 6), (2, 6)]]), grid)
        with self.assertRaises(ValueError):
            coverage.band_spans(edges[:, 0, :], grid, slice(0, 10), 1e-12)
        with self.assertRaises(ValueError):
            coverage.band_spans(np.full((1, 2, 2), np.nan), grid, slice(0, 10), 1e-12)
        with self.assertRaises(ValueError):
            coverage.band_spans(edges, grid, slice(0, 10, 2), 1e-12)
        for rows, source in ((slice(3, 3), edges), (slice(0, 10), edges[:0])):
            row, col0, col1 = coverage.band_spans(source, grid, rows, 1e-12)
            self.assertEqual((row.size, col0.size, col1.size), (0, 0, 0))


class OutsideFiguresTest(unittest.TestCase):
    """Las cifras de lo que queda fuera de la rejilla son las de antes (RF-012-15)."""

    def test_random_constraints_count_the_cells_of_before(self) -> None:
        """Polígonos, líneas y puntos al azar, dentro, a caballo y fuera de la rejilla, con y sin
        resguardo y con celdas no cuadradas: las celdas fuera son las del algoritmo de antes, de una
        vez y por bandas de pocas filas."""
        rng = np.random.default_rng(20261102)
        outside = 0
        for case in range(60):
            grid = random_grid(rng)
            width, height = grid.ncols * grid.dx, grid.nrows * grid.dy
            kind = rng.choice(["polygon", "polygon", "line", "point"])
            if kind == "polygon":
                item = random_polygon(rng, grid)
                outward = float(rng.choice([0.0, 0.5, 3.0, 7.5]))
            elif kind == "line":
                points = [(rng.uniform(-0.5, 1.5) * width, rng.uniform(-0.5, 1.5) * height)
                          for _ in range(int(rng.integers(2, 6)))]
                item = constraint([points], kind=G.LINE, ctype=T.REQUIRES_ACCESS)
                outward = float(rng.choice([0.5, 3.0, 7.5]))
            else:
                point = [(rng.uniform(-0.5, 1.5) * width, rng.uniform(-0.5, 1.5) * height)]
                item = constraint([point], kind=G.POINT, ctype=T.UNTOUCHABLE)
                outward = float(rng.choice([0.5, 3.0, 7.5]))
            with self.subTest(case=case, kind=str(kind), outward=outward):
                want = reference_cells(item, grid, outward)
                outside += want
                self.assertEqual(measured_cells(item, grid, outward), want)
                self.assertEqual(measured_cells(item, grid, outward, rows_per_step=3), want)
        self.assertGreater(outside, 1000)   # hay casos fuera de verdad

    def test_a_slanted_polygon_much_larger_than_the_grid(self) -> None:
        """Un triángulo de 0,8 km con la rejilla en una punta, con y sin resguardo: las celdas del
        algoritmo de antes (el último caso que cabe en una prueba unitaria)."""
        grid = grid_of(60, 40, 1.0)
        item = constraint([[(30.0, 20.0), (830.0, 250.0), (150.0, 700.0)]])
        for outward in (0.0, 4.0):
            with self.subTest(outward=outward):
                self.assertEqual(measured_cells(item, grid, outward),
                                 reference_cells(item, grid, outward))

    def test_the_three_hand_cases(self) -> None:
        """Con celdas de 5 m (48 × 40) y 3 m de resguardo: una exclusión a 1 km (8 × 8 celdas fuera,
        1.600 m²), otra de 40 × 30 m medio fuera por el este (80 celdas, 32 dentro: 1.200 m²) y un
        «sin corte» que pasa el borde oeste (72 celdas, 16 dentro: 1.400 m²), como las contó a mano
        la verificación; y los avisos de la compilación con sus nombres y áreas."""
        grid = grid_of(48, 40, 5.0)
        items = [make("r_concesion", T.LEGAL_LIMIT, (0, 0, 240, 200), fid=1),
                 make("r_lejos", T.EXCLUSION, (1000, 50, 1030, 80), fid=2, name="Muy lejos"),
                 make("r_parcial", T.EXCLUSION, (225, 60, 265, 90), fid=3, name="Parcial"),
                 make("r_oeste", T.NO_CUT, (-30, 150, 6, 180), fid=4, name="Borde oeste")]
        extra = {params.buffer_out_key(code): 3.0 for code in ("r_lejos", "r_parcial", "r_oeste")}
        resolved = resolved_for(items, outward=3.0, inward=0.0, extra=extra)
        prepared = combine.prepare(items, resolved, grid)
        figures = {code: prepared.zones[code].outside_m2
                   for code in ("r_concesion", "r_lejos", "r_parcial", "r_oeste")}
        self.assertEqual(figures, {"r_concesion": 0.0, "r_lejos": 1600.0, "r_parcial": 1200.0,
                                   "r_oeste": 1400.0})
        inside = {code: prepared.zones[code].runs.cells for code in ("r_lejos", "r_parcial",
                                                                     "r_oeste")}
        self.assertEqual(inside, {"r_lejos": 0, "r_parcial": 32, "r_oeste": 16})
        warned = {n.value("code"): n.text("es") for n in prepared.notices
                  if n.code == "core.constraint_zone_outside_grid"}
        self.assertEqual(set(warned), {"r_lejos", "r_parcial", "r_oeste"})
        self.assertIn("Muy lejos", warned["r_lejos"])
        self.assertIn("1 600 m²", warned["r_lejos"])
        self.assertIn("1 200 m²", warned["r_parcial"])
        self.assertIn("1 400 m²", warned["r_oeste"])

    def test_steps_are_short_bands(self) -> None:
        """Lo de fuera se mide por bandas de ``rows_per_step`` filas: un paso de cada una (sin
        construir de golpe la rejilla ampliada), y la suma es la de una sola vez."""
        grid = grid_of(60, 40, 1.0)
        item = constraint([[(50.0, -300.0), (400.0, -300.0), (400.0, 500.0), (50.0, 500.0)]])
        steps = combine._outside_cells(item, grid, 2.0, rows_per_step=64)
        count = 0
        while True:
            try:
                next(steps)
            except StopIteration as stop:
                total = stop.value
                break
            count += 1
        self.assertGreaterEqual(count, 13)   # (800 + 4 + 2 filas de resguardo) / 64
        self.assertEqual(total, reference_cells(item, grid, 2.0))


class HugeConstraintTest(unittest.TestCase):
    """RNF-012-01 y RNF-012-06: una restricción de 20 km con la ventana de 400 × 300 celdas de 1 m."""

    SIDE_M = 20_000.0
    OUTWARD_M = 5.0
    FAR_BUDGET_S = 3.0

    def compile_figures(self, side: float):
        """``(outside_m2, zona dentro, segundos)`` de una exclusión adyacente de ``side`` m de lado
        (su lado oeste a 20 m del borde este de la ventana) con 5 m de resguardo."""
        grid = grid_of(400, 300, 1.0)
        legal = make("r_concesion", T.LEGAL_LIMIT, (0, 0, 400, 300), fid=1)
        big = make("r_natura", T.NO_FILL, (380, -side / 2, 380 + side, side / 2), fid=2)
        items = [legal, big]
        extra = {params.buffer_out_key("r_natura"): self.OUTWARD_M}
        resolved = resolved_for(items, inward=0.0, extra=extra)
        started = time.perf_counter()
        prepared = combine.prepare(items, resolved, grid)
        seconds = time.perf_counter() - started
        zone = prepared.zones["r_natura"]
        return zone.outside_m2, zone.runs.cells, seconds

    def test_a_20_km_exclusion_gives_the_exact_figure_quickly(self) -> None:
        """La zona fuera es L² + 20·L + 88 m² (el cuadrado, cuatro bandas de 5 m y las 22 celdas de
        cada esquina) menos los 7.500 m² de la ventana (25 columnas × 300 filas); 14,6 s antes."""
        outside, inside, seconds = self.compile_figures(self.SIDE_M)
        side = self.SIDE_M
        self.assertEqual(inside, 25 * 300)
        self.assertEqual(outside, side * side + 4 * side * self.OUTWARD_M + 88.0 - 7500.0)
        self.assertEqual(outside, 400_392_588.0)
        self.assertLess(seconds, self.FAR_BUDGET_S)


if __name__ == "__main__":
    unittest.main()
