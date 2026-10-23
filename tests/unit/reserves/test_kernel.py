# SPDX-License-Identifier: GPL-3.0-or-later
"""El núcleo de la cubicación: totales, umbral, dominios y rodajas (spec 011, T08; HU-011-1,
HU-011-2; RF-011-01, RF-011-04, RF-011-07, RF-011-09, RF-011-10; plan 011 A2, A3 y D-20).

``reserves.kernel`` cubica en **una pasada por bandas de filas** (RF-011-10): en cada banda, la
diferencia ``d = partida − final`` de las celdas con dato en las dos; desmonte donde ``d > e`` y
terraplén donde ``−d > e`` con **todo** su espesor (``e``, el espesor mínimo, es un umbral:
RF-011-04, D-6), el resto con dato «sin movimiento»; volúmenes ``Σ w·|d|·A`` y áreas ``Σ w·A``
con el área real de celda (RF-011-01). A la vez, por dominio con las entradas celda-dominio-peso
de ``reserves.polygons.weights`` (RF-011-07) y por rodajas ``[z_k, z_k+1)`` (RF-011-09, A3: el
extremo superior justo en una cota va a la rodaja de abajo; las enteras, por diferencias
acumuladas).

Las referencias son independientes del núcleo: cuentas a mano con números exactos en binario, el
volumen de ``gis.grid.volume_between`` de la 006 (D-20: con ``e = 0`` y sin pesos, **bit a bit**
el mismo, de una vez) y las fracciones de rectángulos alineados con los ejes.
"""

from __future__ import annotations

import math
import unittest

import numpy as np

from tests.support import res_fixtures as fx
from tests.support.package import import_geoblender

kernel = import_geoblender("reserves.kernel")
slices_module = import_geoblender("reserves.slices")
polygons = import_geoblender("reserves.polygons")
gis = import_geoblender("gis")

Grid = gis.Grid
Slices = slices_module.Slices

WEST = 735_000.0
SOUTH = 4_434_000.0
CLOSURE = 1e-9
"""Cierre de un reparto con su total (RF-011-07, RF-011-09, RF-011-10; D-14 b)."""
SAME = 1e-12
"""Por bandas frente a de una vez, y las cuentas a mano en float64: error relativo al total."""


def _grid(ncols: int, nrows: int, dx: float = 1.0, dy: float = 1.0) -> Grid:
    return Grid(west=WEST, north=SOUTH + nrows * dy, dx=dx, dy=dy, ncols=ncols, nrows=nrows)


def _rect(west: float, south: float, east: float, north: float):
    """Un anillo ABSOLUTO desde un rectángulo relativo a (WEST, SOUTH)."""
    return np.array([[west, south], [east, south], [east, north], [west, north]],
                    dtype=np.float64) + np.array([WEST, SOUTH])


def _run(grid: Grid, start, final, *, e: float = 0.0, slices=None, domains=(), scope=None,
         band: int | None = None):
    """Cubica ``start`` − ``final`` en ``grid`` de una vez (``band=None``) o por bandas de
    ``band`` filas, con los dominios y el ámbito dados como aristas (``polygons.domain_edges``
    y ``polygons.scope_edges``)."""
    accumulators = kernel.Accumulators(grid, slices=slices, domains=len(domains),
                                       min_thickness_m=e)
    height = grid.nrows if band is None else band
    for first in range(0, grid.nrows, height):
        rows = slice(first, min(first + height, grid.nrows))
        weights = None
        if len(domains) or scope is not None:
            weights = polygons.weights(domains, scope, grid, rows)
        final_band = final if np.ndim(final) == 0 else final[rows]
        kernel.band_step(accumulators, kernel.BandValues(first, start[rows], final_band),
                         weights)
    return accumulators.result()


def _fractions(grid: Grid, rect: tuple[float, float, float, float]) -> np.ndarray:
    """La fracción exacta de cada celda de ``grid`` dentro de ``rect`` (relativo a WEST,
    SOUTH): el producto de los solapes en X y en Y, sin el núcleo."""
    west = np.arange(grid.ncols) * grid.dx
    north = grid.nrows * grid.dy - np.arange(grid.nrows) * grid.dy
    in_x = np.clip(np.minimum(west + grid.dx, rect[2]) - np.maximum(west, rect[0]), 0.0, None)
    in_y = np.clip(np.minimum(north, rect[3]) - np.maximum(north - grid.dy, rect[1]), 0.0,
                   None)
    return in_y[:, None] * in_x[None, :] / grid.cell_area


def _close(test: unittest.TestCase, found, expected, scale: float, tolerance: float,
           what: str) -> None:
    """Cada valor de ``found`` a ≤ ``tolerance``·``scale`` del de ``expected``."""
    found = np.asarray(found, dtype=np.float64)
    expected = np.asarray(expected, dtype=np.float64)
    test.assertEqual(found.shape, expected.shape, what)
    worst = float(np.max(np.abs(found - expected), initial=0.0))
    test.assertLessEqual(worst, tolerance * scale,
                         f"{what}: {found!r} frente a {expected!r} (error {worst!r})")


class TotalsTest(unittest.TestCase):
    """RF-011-01 y RF-011-04: totales, áreas y umbral, con el área real de celda."""

    # d = partida − final en una rejilla de 4 × 3 celdas de 2,5 × 2 m (5 m²): desmonte 3, 1,5,
    # 4, 0,25 y 6; terraplén 2 y 1,25; sin movimiento tres celdas (d = 0); sin dato dos.
    START = np.array([[10.0, 10.0, 10.0, 10.0],
                      [10.0, np.nan, 10.0, 10.0],
                      [10.0, 10.0, 10.0, 10.0]])
    FINAL = np.array([[7.0, 8.5, 12.0, 10.0],
                      [10.0, 9.0, np.nan, 6.0],
                      [11.25, 10.0, 9.75, 4.0]])

    def test_cut_fill_net_and_areas(self) -> None:
        """RF-011-01: desmonte (la final por debajo), terraplén (por encima) y neto en m³; área
        con dato en las dos, sin dato en alguna y sin movimiento en m², con el área real de
        celda (2,5 × 2 m = 5 m², no 1 m²). Las entradas no se modifican."""
        grid = _grid(4, 3, dx=2.5, dy=2.0)
        start, final = self.START.copy(), self.FINAL.copy()
        result = _run(grid, start, final)
        self.assertEqual(result.cell_area_m2, 5.0)
        self.assertEqual(result.domains, 0)
        self.assertEqual(result.cut_m3.shape, (1,))
        self.assertEqual(result.cut_m3[kernel.ALL], 14.75 * 5.0)
        self.assertEqual(result.fill_m3[kernel.ALL], 3.25 * 5.0)
        self.assertEqual(result.net_m3[kernel.ALL], 11.5 * 5.0)
        self.assertEqual(result.area_m2[kernel.ALL], 10 * 5.0)
        self.assertEqual(result.nodata_area_m2[kernel.ALL], 2 * 5.0)
        self.assertEqual(result.still_area_m2[kernel.ALL], 3 * 5.0)
        self.assertIsNone(result.bounds)
        np.testing.assert_array_equal(start, self.START)
        np.testing.assert_array_equal(final, self.FINAL)

    def test_the_minimum_thickness_is_a_threshold(self) -> None:
        """RF-011-04 (D-6): con e = 0,5 m, la celda de 0,25 m no cuenta (sin movimiento) y las
        demás cuentan **enteras** (no se les resta e); con e = 1,5 m, la de 1,5 m tampoco (hay
        que **pasar** del umbral) ni el terraplén de 1,25 m."""
        grid = _grid(4, 3, dx=2.5, dy=2.0)
        cases = {0.5: (14.5, 3.25, 4), 1.5: (13.0, 2.0, 6)}
        for e, (cut, fill, still) in cases.items():
            with self.subTest(e=e):
                result = _run(grid, self.START, self.FINAL, e=e)
                self.assertEqual(result.cut_m3[kernel.ALL], cut * 5.0)
                self.assertEqual(result.fill_m3[kernel.ALL], fill * 5.0)
                self.assertEqual(result.net_m3[kernel.ALL], (cut - fill) * 5.0)
                self.assertEqual(result.area_m2[kernel.ALL], 50.0)
                self.assertEqual(result.still_area_m2[kernel.ALL], still * 5.0)

    def test_same_as_volume_between_bit_for_bit(self) -> None:
        """D-20 (RF-011-01): con e = 0, sin ámbito ni dominios y de una vez, desmonte,
        terraplén, neto, área con dato y área sin dato son **bit a bit** los de
        ``gis.grid.volume_between`` de la 006: superficies aleatorias con huecos y celdas B24,
        la pirámide (rejilla y TIN, con huecos), la corta circular y el prisma B24."""
        rng = np.random.default_rng(20_261_023)
        grid = Grid(west=WEST, north=SOUTH + 90 * fx.B24_DY, dx=fx.B24_DX, dy=fx.B24_DY,
                    ncols=120, nrows=90)
        start = 700.0 + rng.normal(0.0, 3.0, grid.shape)
        final = 700.0 + rng.normal(0.0, 3.0, grid.shape)
        start[rng.random(grid.shape) < 0.05] = np.nan
        final[rng.random(grid.shape) < 0.05] = np.nan
        pairs = [("aleatorias", gis.Raster(grid, start, fx.CRS, fx.VERTICAL),
                  gis.Raster(grid, final, fx.CRS, fx.VERTICAL))]
        apex = fx.pyramid_apexes(1.0)[7]
        for pair in (fx.pyramid(1.0, apex), fx.pyramid_from_tin(1.0, apex),
                     fx.circular_pit(2.0, fx.circular_pit_axes()[2][1]), fx.b24_prism(150)):
            pairs.append((pair.name, pair.start, pair.final))
        for name, upper, lower in pairs:
            with self.subTest(name):
                expected = gis.volume_between(upper, lower)
                result = _run(upper.grid, upper.values, lower.values)
                self.assertGreater(expected.cut_m3, 0.0)
                for field in ("cut_m3", "fill_m3", "net_m3", "area_m2", "nodata_area_m2"):
                    self.assertEqual(getattr(result, field)[kernel.ALL],
                                     getattr(expected, field), field)
                self.assertEqual(result.cell_area_m2, expected.cell_area_m2)

    def test_the_same_surface_twice_gives_zeros(self) -> None:
        """RF-011-01 (§8 de la spec): la misma superficie como partida y final da ceros, todo
        con dato y sin movimiento, y ninguna rodaja."""
        pair = fx.pyramid(2.0)
        result = _run(pair.grid, pair.start.values, pair.start.values,
                      slices=Slices(10.0, 600.0, None))
        for field in ("cut_m3", "fill_m3", "net_m3", "nodata_area_m2"):
            self.assertEqual(getattr(result, field)[kernel.ALL], 0.0, field)
        self.assertEqual(result.area_m2[kernel.ALL], 200.0 * 200.0)
        self.assertEqual(result.still_area_m2[kernel.ALL], 200.0 * 200.0)
        self.assertEqual(result.bounds.size, 0)
        self.assertEqual(result.slice_cut_m3.shape, (1, 0))

    def test_a_constant_elevation_as_final(self) -> None:
        """RF-011-01 (RF-011-02): una cota constante como final (un número) da lo mismo, bit a
        bit, que su rejilla llena."""
        pair = fx.pyramid(2.0, fx.pyramid_apexes(2.0)[5])
        by_value = _run(pair.grid, pair.start.values, fx.PYRAMID_FLOOR_Z,
                        slices=Slices(10.0, 600.0, None))
        by_grid = _run(pair.grid, pair.start.values, pair.final.values,
                       slices=Slices(10.0, 600.0, None))
        for field in ("cut_m3", "fill_m3", "area_m2", "still_area_m2", "slice_cut_m3"):
            np.testing.assert_array_equal(getattr(by_value, field), getattr(by_grid, field))


class SlicesTest(unittest.TestCase):
    """RF-011-09 (A3, D-22): cada celda reparte su intervalo entre las rodajas ``[z_k,
    z_k+1)``, contando en cada una solo el espesor que cae dentro."""

    # Cinco celdas de 1 m²: desmonte [603, 627], [605, 620] (arriba justo en una cota) y
    # [610, 615] (abajo justo en una cota); terraplén [601, 612,5]; una sin movimiento.
    START = np.array([[627.0, 620.0, 615.0, 601.0, 640.0]])
    FINAL = np.array([[603.0, 605.0, 610.0, 612.5, 640.0]])

    def test_by_height_and_anchor(self) -> None:
        """RF-011-09: con 10 m desde la cota 600 (y con el anclaje en −1 000 m, el mismo), las
        cotas 600 a 630 cubren de 601 a 627; desmonte 7 + 5, 10 + 10 + 5 y 7 m³ (la celda que
        llega justo a 620 no pone nada en [620, 630)); terraplén 9 y 2,5 m³. Con el anclaje en
        2,5 m, las cotas 592,5 a 632,5. Las rodajas suman el total."""
        grid = _grid(5, 1)
        for anchor in (600.0, -1000.0):
            with self.subTest(anchor=anchor):
                result = _run(grid, self.START, self.FINAL, slices=Slices(10.0, anchor, None))
                np.testing.assert_array_equal(result.bounds, [600.0, 610.0, 620.0, 630.0])
                np.testing.assert_array_equal(result.slice_cut_m3, [[12.0, 25.0, 7.0]])
                np.testing.assert_array_equal(result.slice_fill_m3, [[9.0, 2.5, 0.0]])
                np.testing.assert_array_equal(result.below_cut_m3, [0.0])
                np.testing.assert_array_equal(result.above_fill_m3, [0.0])
                self.assertEqual(result.cut_m3[kernel.ALL], 44.0)
                self.assertEqual(result.fill_m3[kernel.ALL], 11.5)
        result = _run(grid, self.START, self.FINAL, slices=Slices(10.0, 2.5, None))
        np.testing.assert_array_equal(result.bounds, [592.5, 602.5, 612.5, 622.5, 632.5])
        # [603, 627] → 9,5 + 10 + 4,5; [605, 620] → 7,5 + 7,5; [610, 615] → 2,5 + 2,5.
        np.testing.assert_array_equal(result.slice_cut_m3, [[0.0, 19.5, 20.0, 4.5]])
        np.testing.assert_array_equal(result.slice_fill_m3, [[1.5, 10.0, 0.0, 0.0]])

    def test_the_bounds_are_those_of_slices(self) -> None:
        """RF-011-09 (A3): las cotas de la tabla son las de ``reserves.slices.bounds`` sobre lo
        cubicado, también con alturas y anclajes que no son exactos en binario, y el reparto
        cierra con el total ≤ 10⁻⁹ (de hecho, ≤ 10⁻¹²)."""
        pair = fx.pyramid(2.0, fx.pyramid_apexes(2.0)[9])
        for height, anchor in ((10.0, 600.0), (0.3, 0.1), (7.0, -1234.567), (100.0, 3.0)):
            with self.subTest(height=height, anchor=anchor):
                bench = Slices(height, anchor, None)
                result = _run(pair.grid, pair.start.values, pair.final.values, slices=bench)
                top = float(np.max(pair.start.values))
                np.testing.assert_array_equal(
                    result.bounds, slices_module.bounds(bench, fx.PYRAMID_FLOOR_Z, top))
                total = result.cut_m3[kernel.ALL]
                self.assertEqual(result.slice_cut_m3.shape, (1, result.bounds.size - 1))
                self.assertLessEqual(abs(np.sum(result.slice_cut_m3) - total) / total, SAME)
                self.assertTrue(np.all(result.slice_cut_m3 >= 0.0))

    def test_by_a_list_of_levels(self) -> None:
        """RF-011-09: una lista de cotas se usa tal cual; lo que queda por debajo de la primera
        o por encima de la última no cae en ninguna rodaja, sino aparte (abajo y arriba), así
        que todo suma el total. [590, 660] → 10 abajo, 15, 35 y 10 arriba; [615, 650], justo en
        dos cotas, entero en [615, 650); el terraplén [598, 600], abajo."""
        grid = _grid(3, 1)
        start = np.array([[660.0, 650.0, 598.0]])
        final = np.array([[590.0, 615.0, 600.0]])
        result = _run(grid, start, final, slices=Slices(None, None, (600.0, 615.0, 650.0)))
        np.testing.assert_array_equal(result.bounds, [600.0, 615.0, 650.0])
        np.testing.assert_array_equal(result.slice_cut_m3, [[15.0, 70.0]])
        np.testing.assert_array_equal(result.below_cut_m3, [10.0])
        np.testing.assert_array_equal(result.above_cut_m3, [10.0])
        np.testing.assert_array_equal(result.slice_fill_m3, [[0.0, 0.0]])
        np.testing.assert_array_equal(result.below_fill_m3, [2.0])
        np.testing.assert_array_equal(result.above_fill_m3, [0.0])
        self.assertEqual(result.cut_m3[kernel.ALL], 105.0)
        self.assertEqual(result.fill_m3[kernel.ALL], 2.0)
        # Lo que no se mueve no hace falta: una lista entera vacía sale con ceros.
        still = _run(grid, start, start, slices=Slices(None, None, (600.0, 615.0, 650.0)))
        np.testing.assert_array_equal(still.slice_cut_m3, [[0.0, 0.0]])


class DomainsTest(unittest.TestCase):
    """RF-011-07: cada dominio recibe la fracción exacta de cada celda que queda dentro de él,
    con una fila «Fuera de los dominios»; las filas suman el total ≤ 10⁻⁹."""

    GRID = _grid(10, 10)
    FIRST = (1.25, 2.0, 4.5, 7.75)  # rectángulos relativos a (WEST, SOUTH), con un lado común
    SECOND = (4.5, 1.5, 8.0, 6.25)
    SCOPE = (2.0, 0.5, 9.0, 9.0)

    def _surfaces(self) -> tuple[np.ndarray, np.ndarray]:
        rows, cols = np.mgrid[0:10, 0:10].astype(np.float64)
        start = 620.0 + 0.5 * cols + 0.25 * rows
        final = np.full((10, 10), 610.0)
        final[6:, 5:] = 630.0  # terraplén al sureste
        final[3, 3] = np.nan  # un hueco en cada dominio y otro fuera
        start[4, 6] = np.nan
        start[9, 0] = np.nan
        return start, final

    def _polygons(self):
        return (polygons.Polygon(1, "Fase 1", (_rect(*self.FIRST),)),
                polygons.Polygon(2, "Fase 2", (_rect(*self.SECOND),)))

    def _expected(self, fractions: list[np.ndarray], whole: np.ndarray):
        """Desmonte, terraplén, área con dato y sin dato de cada fila (total, dominios y
        fuera), con las fracciones dadas, sin el núcleo."""
        start, final = self._surfaces()
        valid = np.isfinite(start) & np.isfinite(final)
        d = np.where(valid, start - final, 0.0)
        rows = [whole, *fractions, whole - sum(fractions)]
        return {
            "cut_m3": [np.sum(f * np.where(d > 0.0, d, 0.0)) for f in rows],
            "fill_m3": [np.sum(f * np.where(d < 0.0, -d, 0.0)) for f in rows],
            "area_m2": [np.sum(f[valid]) for f in rows],
            "nodata_area_m2": [np.sum(f[~valid]) for f in rows],
        }

    def _check(self, result, expected) -> None:
        self.assertEqual(result.domains, 2)
        self.assertEqual(result.outside, 3)
        for field, values in expected.items():
            _close(self, getattr(result, field), values, max(map(abs, values)), SAME, field)
            found = getattr(result, field)
            self.assertLessEqual(abs(np.sum(found[1:]) - found[0]), CLOSURE * abs(found[0]),
                                 f"{field}: las filas no suman el total")

    def test_without_scope(self) -> None:
        """RF-011-07: dos fases con un lado común y lados que cortan celdas; desmonte,
        terraplén y áreas de cada fase y de «Fuera de los dominios» con las fracciones exactas
        de sus rectángulos (también en las celdas sin dato); sin ámbito, el total es el de todas
        las celdas (bit a bit el de sin dominios)."""
        start, final = self._surfaces()
        domains = [item.edges for item in polygons.domain_edges(self._polygons(), self.GRID)]
        result = _run(self.GRID, start, final, domains=domains, slices=Slices(5.0, 0.0, None))
        self._check(result, self._expected(
            [_fractions(self.GRID, self.FIRST), _fractions(self.GRID, self.SECOND)],
            np.ones((10, 10))))
        alone = _run(self.GRID, start, final)
        for field in ("cut_m3", "fill_m3", "area_m2", "nodata_area_m2", "still_area_m2"):
            self.assertEqual(getattr(result, field)[kernel.ALL],
                             getattr(alone, field)[kernel.ALL], field)
        # Las rodajas de cada fila suman su fila, y cada rodaja, la del total.
        for field in ("cut_m3", "fill_m3"):
            by_slice = getattr(result, f"slice_{field}")
            _close(self, by_slice.sum(axis=1), getattr(result, field),
                   getattr(result, field)[0], SAME, f"rodajas de {field}")
            _close(self, by_slice[1:].sum(axis=0), by_slice[0], getattr(result, field)[0],
                   SAME, f"filas de cada rodaja de {field}")

    def test_with_scope(self) -> None:
        """RF-011-01 y RF-011-07: con un ámbito, el total es el de su fracción de cada celda y
        cada fase, la de su recorte por él; «Fuera de los dominios» cierra con el ámbito."""
        start, final = self._surfaces()
        scope = polygons.Polygon(9, "", (_rect(*self.SCOPE),))
        domains = [item.edges for item in
                   polygons.domain_edges(self._polygons(), self.GRID, scope=scope)]
        result = _run(self.GRID, start, final, domains=domains,
                      scope=polygons.scope_edges(scope, self.GRID))

        def clipped(rect):
            return (max(rect[0], self.SCOPE[0]), max(rect[1], self.SCOPE[1]),
                    min(rect[2], self.SCOPE[2]), min(rect[3], self.SCOPE[3]))

        self._check(result, self._expected(
            [_fractions(self.GRID, clipped(self.FIRST)),
             _fractions(self.GRID, clipped(self.SECOND))],
            _fractions(self.GRID, self.SCOPE)))
        only_scope = _run(self.GRID, start, final,
                          scope=polygons.scope_edges(scope, self.GRID))
        self.assertEqual(only_scope.cut_m3.shape, (1,))
        self.assertLessEqual(abs(only_scope.cut_m3[0] - result.cut_m3[0]),
                             SAME * result.cut_m3[0])


class BandsTest(unittest.TestCase):
    """RF-011-10: un solo cálculo por bandas da lo mismo que de una vez."""

    def test_by_bands_as_at_once(self) -> None:
        """RF-011-10: la pirámide con 1 m sobre una final ondulada (desmonte y terraplén), un
        hueco sin dato, sus cuatro cuadrantes como dominios, un ámbito girado, rodajas de 10 m
        ancladas en 2,5 m y e = 0,05 m, de una vez y por bandas de 7 y de 64 filas: cada total,
        área, fila y rodaja, igual salvo el redondeo de las sumas (≤ 10⁻¹² del total); sin
        pesos, las áreas, exactas."""
        apex = fx.pyramid_apexes(1.0)[13]
        pair = fx.pyramid(1.0, apex)
        start = pair.start.values.copy()
        start[90:96, 120:131] = np.nan
        x, y = pair.grid.centers()
        final = fx.PYRAMID_FLOOR_Z + 2.0 * np.sin((x - WEST) / 7.3) * np.cos((y - SOUTH) / 5.1)
        quadrants = [polygons.Polygon(item.fid, item.value, item.rings)
                     for item in fx.pyramid_quadrants(apex)]
        angle, half = 0.3, 70.0
        corners = np.array([[-half, -half], [half, -half], [half, half], [-half, half]])
        turn = np.array([[math.cos(angle), math.sin(angle)], [-math.sin(angle), math.cos(angle)]])
        scope = polygons.Polygon(1, "", (corners @ turn + np.array(apex),))
        grid = pair.grid
        cases = {
            "sin pesos": {},
            "dominios y ámbito": {
                "domains": [item.edges for item in
                            polygons.domain_edges(quadrants, grid, scope=scope)],
                "scope": polygons.scope_edges(scope, grid),
            },
        }
        for name, weights in cases.items():
            at_once = _run(grid, start, final, e=0.05, slices=Slices(10.0, 2.5, None),
                           **weights)
            total = at_once.cut_m3[kernel.ALL]
            self.assertGreater(at_once.fill_m3[kernel.ALL], 0.0)
            for band in (7, 64):
                with self.subTest(name, band=band):
                    by_bands = _run(grid, start, final, e=0.05,
                                    slices=Slices(10.0, 2.5, None), band=band, **weights)
                    np.testing.assert_array_equal(by_bands.bounds, at_once.bounds)
                    for field in ("cut_m3", "fill_m3", "net_m3", "slice_cut_m3",
                                  "slice_fill_m3"):
                        _close(self, getattr(by_bands, field), getattr(at_once, field), total,
                               SAME, field)
                    for field in ("area_m2", "nodata_area_m2", "still_area_m2"):
                        _close(self, getattr(by_bands, field), getattr(at_once, field),
                               at_once.area_m2[kernel.ALL], SAME, field)
                        if not weights:
                            self.assertEqual(getattr(by_bands, field)[kernel.ALL],
                                             getattr(at_once, field)[kernel.ALL], field)


class MisuseTest(unittest.TestCase):
    """Los usos indebidos son errores del programa (``ValueError``), nunca una cifra."""

    def test_rejected(self) -> None:
        """Un espesor mínimo negativo o NaN; una banda de otra anchura, fuera de la rejilla o
        repetida; un resultado antes de pasar todas las filas; con dominios, una banda sin
        pesos o con los de otra banda u otro número de dominios."""
        grid = _grid(4, 3)
        values = np.full((3, 4), 10.0)
        for e in (-0.1, math.nan, math.inf):
            with self.subTest(e=e), self.assertRaises(ValueError):
                kernel.Accumulators(grid, min_thickness_m=e)
        accumulators = kernel.Accumulators(grid)
        with self.assertRaises(ValueError):
            kernel.band_step(accumulators, kernel.BandValues(0, values[:, :3], values[:, :3]))
        with self.assertRaises(ValueError):
            kernel.band_step(accumulators, kernel.BandValues(2, values[:2], values[:2]))
        kernel.band_step(accumulators, kernel.BandValues(0, values[:2], values[:2]))
        with self.assertRaises(ValueError):
            accumulators.result()
        with self.assertRaises(ValueError):
            kernel.band_step(accumulators, kernel.BandValues(1, values[1:], values[1:]))
        kernel.band_step(accumulators, kernel.BandValues(2, values[2:], values[2:]))
        self.assertEqual(accumulators.result().area_m2[kernel.ALL], 12.0)
        square = polygons.Polygon(1, "A", (_rect(0.0, 0.0, 2.0, 2.0),))
        edges = [item.edges for item in polygons.domain_edges([square], grid)]
        with_domains = kernel.Accumulators(grid, domains=1)
        band = kernel.BandValues(0, values[:2], values[:2])
        for weights in (None, polygons.weights(edges, None, grid, slice(1, 3)),
                        polygons.weights([], None, grid, slice(0, 2))):
            with self.subTest(weights=weights), self.assertRaises(ValueError):
                kernel.band_step(with_domains, band, weights)


if __name__ == "__main__":
    unittest.main()
