# SPDX-License-Identifier: GPL-3.0-or-later
"""Las celdas de una zona (spec 013, T03; HU-013-1; RF-013-01, RF-013-02, RF-013-07; plan 013 A1,
§5.3.1; D-16).

Una celda es de un polígono si su **centro** está dentro de él (D-16): el par-impar por barrido de
filas de ``design.zones.cells_inside`` se compara con la fuerza bruta (el número de aristas que
cruzan un rayo desde cada centro) en 40 polígonos aleatorios, con una convención de borde fija
(semiabierta: un centro sobre el borde oeste o norte está dentro; sobre el este o el sur, fuera),
con huecos, solapes y polígonos que se salen de la rejilla. De ahí salen las etiquetas de los
sectores, las celdas de una capa de polígonos del proyecto y las de la zona de una restricción
(``MaskSet.zone``: celda entera, D-1 de la 012).
"""

from __future__ import annotations

import tracemalloc
import unittest

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import constraints_project as cp
from tests.support import design_fixtures as dfx
from tests.support.package import import_geoblender

zones = import_geoblender("design.zones")
messages = import_geoblender("design.messages")
constraints_model = import_geoblender("core.constraints.model")
gis_messages = import_geoblender("gis.messages")

ROWS, COLS = 14, 18


# --- La fuerza bruta -------------------------------------------------------------------------


def inside_brute(rings: list[np.ndarray], x: float, y: float) -> bool:
    """Si ``(x, y)`` está dentro de los anillos por la regla par-impar: el número de aristas
    (de cada anillo, cerrado) que cruzan el rayo hacia el este desde el punto, con el cruce
    estrictamente al este y el extremo de arista «de arriba» contado una sola vez
    (``(ay > y) != (by > y)``). Sin divisiones: por el signo del producto vectorial."""
    odd = False
    for ring in rings:
        points = [(float(p[0]), float(p[1])) for p in ring]
        for k, (ax, ay) in enumerate(points):
            bx, by = points[(k + 1) % len(points)]
            if (ay > y) == (by > y):
                continue
            side = (bx - ax) * (y - ay) - (x - ax) * (by - ay)
            if (by > ay and side > 0.0) or (by < ay and side < 0.0):
                odd = not odd
    return odd


def brute(rings: list[np.ndarray], nrows: int = ROWS, ncols: int = COLS) -> np.ndarray:
    """Las celdas cuyo centro ``(j + ½, i + ½)`` está dentro, una a una."""
    found = np.zeros((nrows, ncols), dtype=bool)
    for i in range(nrows):
        for j in range(ncols):
            found[i, j] = inside_brute(rings, j + 0.5, i + 0.5)
    return found


def star(rng: np.random.Generator, cx: float, cy: float, low: float, high: float,
         count: int) -> np.ndarray:
    """Un anillo en estrella (simple) de ``count`` vértices en torno a ``(cx, cy)``."""
    angles = np.sort(rng.uniform(0.0, 2.0 * np.pi, count))
    radii = rng.uniform(low, high, count)
    return np.column_stack([cx + radii * np.cos(angles), cy + radii * np.sin(angles)])


def random_rings(rng: np.random.Generator, kind: int) -> list[np.ndarray]:
    """Los anillos de un polígono aleatorio, en unidades de celda, que se sale de la rejilla:
    una estrella, una estrella con hueco, dos estrellas separadas o un garabato que se corta a sí
    mismo (el par-impar también lo define)."""
    cx, cy = rng.uniform(0.0, COLS), rng.uniform(0.0, ROWS)
    if kind == 0:
        return [star(rng, cx, cy, 1.5, 9.0, int(rng.integers(3, 12)))]
    if kind == 1:
        return [star(rng, cx, cy, 4.0, 9.0, int(rng.integers(5, 12))),
                star(rng, cx, cy, 0.5, 2.5, int(rng.integers(3, 8)))]
    if kind == 2:
        return [star(rng, cx - 5.0, cy, 1.0, 3.5, int(rng.integers(3, 9))),
                star(rng, cx + 5.0, cy, 1.0, 3.5, int(rng.integers(3, 9)))]
    return [np.column_stack([rng.uniform(-3.0, COLS + 3.0, count),
                             rng.uniform(-3.0, ROWS + 3.0, count)])
            for count in [int(rng.integers(4, 10))]]


# --- cells_inside ----------------------------------------------------------------------------


class CellsInsideTest(unittest.TestCase):
    def test_matches_brute_force_in_40_random_polygons(self) -> None:
        """RF-013-01, D-16, A1: el par-impar por barrido de filas da, en 40 polígonos aleatorios
        (estrellas, con hueco, de dos partes y garabatos que se cortan, parcialmente fuera de la
        rejilla), las mismas celdas que la fuerza bruta centro a centro; y alguno tiene celdas."""
        rng = np.random.default_rng(20261102)
        sizes = []
        for index in range(40):
            rings = random_rings(rng, index % 4)
            with self.subTest(index=index, kind=index % 4):
                found = zones.cells_inside(rings, ROWS, COLS)
                self.assertEqual(found.dtype, np.bool_)
                self.assertEqual(found.shape, (ROWS, COLS))
                np.testing.assert_array_equal(found, brute(rings))
                sizes.append(int(found.sum()))
        self.assertGreater(sum(1 for size in sizes if size > 0), 30, sizes)
        self.assertGreater(max(sizes), 90, sizes)

    def test_matches_brute_force_with_centers_on_the_edges(self) -> None:
        """D-16: con vértices en múltiplos de ½ (muchos bordes y vértices justo sobre un centro
        de celda) el barrido sigue a la fuerza bruta en 40 polígonos: la convención de borde es
        la misma de siempre."""
        rng = np.random.default_rng(20261103)
        for index in range(40):
            count = int(rng.integers(3, 9))
            ring = rng.integers(-6, 2 * COLS + 6, size=(count, 2)).astype(np.float64) / 2.0
            ring[:, 1] = rng.integers(-6, 2 * ROWS + 6, size=count) / 2.0
            with self.subTest(index=index):
                np.testing.assert_array_equal(zones.cells_inside([ring], ROWS, COLS),
                                              brute([ring]))

    def test_rectangle_on_the_centers_is_half_open(self) -> None:
        """D-16 (convención de borde): un rectángulo con los bordes sobre centros de celda incluye
        los centros de sus bordes oeste y norte (arriba, en unidades de celda: fila menor) y deja
        fuera los del este y el sur: de 2,5 a 6,5 en columnas y de 1,5 a 4,5 en filas son las
        columnas 2 a 5 y las filas 1 a 3, ni una más."""
        ring = np.array([[2.5, 1.5], [6.5, 1.5], [6.5, 4.5], [2.5, 4.5]])
        expected = np.zeros((ROWS, COLS), dtype=bool)
        expected[1:4, 2:6] = True
        np.testing.assert_array_equal(zones.cells_inside([ring], ROWS, COLS), expected)

    def test_adjacent_polygons_leave_no_gap_and_no_double(self) -> None:
        """D-16: dos rectángulos que comparten un borde que pasa por centros (vertical y
        horizontal) se reparten esas celdas sin hueco ni doble cuenta; la unión es el rectángulo
        entero."""
        left = np.array([[1.5, 1.5], [7.5, 1.5], [7.5, 6.5], [1.5, 6.5]])
        right = np.array([[7.5, 1.5], [12.5, 1.5], [12.5, 6.5], [7.5, 6.5]])
        below = np.array([[1.5, 6.5], [12.5, 6.5], [12.5, 9.5], [1.5, 9.5]])
        whole = np.array([[1.5, 1.5], [12.5, 1.5], [12.5, 9.5], [1.5, 9.5]])
        parts = [zones.cells_inside([ring], ROWS, COLS) for ring in (left, right, below)]
        self.assertEqual(int(sum(part.astype(int) for part in parts).max()), 1)
        np.testing.assert_array_equal(parts[0] | parts[1] | parts[2],
                                      zones.cells_inside([whole], ROWS, COLS))

    def test_holes_and_overlaps_follow_even_odd(self) -> None:
        """D-16: un anillo dentro de otro es un hueco; dos anillos que se solapan dejan fuera la
        zona común (par-impar, no unión): lo que deba unirse se pide por polígonos
        (``polygons_cells``)."""
        outer = np.array([[1.0, 1.0], [11.0, 1.0], [11.0, 9.0], [1.0, 9.0]])
        hole = np.array([[4.0, 3.0], [8.0, 3.0], [8.0, 7.0], [4.0, 7.0]])
        found = zones.cells_inside([outer, hole], ROWS, COLS)
        expected = np.zeros((ROWS, COLS), dtype=bool)
        expected[1:9, 1:11] = True
        expected[3:7, 4:8] = False
        np.testing.assert_array_equal(found, expected)
        first = np.array([[1.0, 1.0], [7.0, 1.0], [7.0, 7.0], [1.0, 7.0]])
        second = np.array([[4.0, 4.0], [10.0, 4.0], [10.0, 10.0], [4.0, 10.0]])
        both = zones.cells_inside([first, second], ROWS, COLS)
        common = zones.cells_inside([first], ROWS, COLS) & zones.cells_inside([second], ROWS, COLS)
        self.assertGreater(int(common.sum()), 0)
        self.assertFalse((both & common).any())
        np.testing.assert_array_equal(
            both, zones.cells_inside([first], ROWS, COLS) ^ zones.cells_inside([second], ROWS, COLS))

    def test_clipped_to_the_grid(self) -> None:
        """RF-013-02: un polígono que cubre la rejilla y mucho más da todas las celdas; uno que
        queda fuera, a un lado o con coordenadas negativas, ninguna; uno que la cruza solo da las
        celdas de dentro."""
        big = np.array([[-50.0, -50.0], [COLS + 50.0, -50.0], [COLS + 50.0, ROWS + 50.0],
                        [-50.0, ROWS + 50.0]])
        self.assertTrue(zones.cells_inside([big], ROWS, COLS).all())
        for corner in ((COLS + 5.0, 3.0), (-9.0, 3.0), (4.0, ROWS + 7.0), (4.0, -12.0)):
            ring = np.array([[corner[0], corner[1]], [corner[0] + 3.0, corner[1]],
                             [corner[0] + 3.0, corner[1] + 3.0], [corner[0], corner[1] + 3.0]])
            self.assertFalse(zones.cells_inside([ring], ROWS, COLS).any(), corner)
        strip = np.array([[-5.0, 4.0], [COLS + 5.0, 4.0], [COLS + 5.0, 6.0], [-5.0, 6.0]])
        expected = np.zeros((ROWS, COLS), dtype=bool)
        expected[4:6, :] = True
        np.testing.assert_array_equal(zones.cells_inside([strip], ROWS, COLS), expected)

    def test_closing_vertex_and_orientation_do_not_matter(self) -> None:
        """Un anillo cerrado (primer vértice repetido) o abierto, antihorario u horario, da las
        mismas celdas; acepta ``(n, 3)`` (la Z no cuenta)."""
        ring = np.array([[2.2, 1.3], [9.7, 2.1], [8.4, 8.8], [3.1, 7.4]])
        closed = np.vstack([ring, ring[:1]])
        base = zones.cells_inside([ring], ROWS, COLS)
        self.assertGreater(int(base.sum()), 20)
        for variant in (closed, ring[::-1], closed[::-1],
                        np.column_stack([ring, np.full(4, 700.0)])):
            np.testing.assert_array_equal(zones.cells_inside([variant], ROWS, COLS), base)

    def test_degenerate_rings_have_no_cells(self) -> None:
        """Ningún anillo, uno de dos puntos, uno de área cero (un segmento recorrido de ida y
        vuelta) o un punto repetido: ninguna celda."""
        shapes = ([], [np.array([[3.0, 3.0], [8.0, 6.0]])],
                  [np.array([[3.0, 3.0], [8.0, 6.0], [3.0, 3.0]])],
                  [np.array([[3.5, 3.5]] * 5)], [np.empty((0, 2))])
        for rings in shapes:
            with self.subTest(rings=len(rings)):
                self.assertFalse(zones.cells_inside(rings, ROWS, COLS).any())

    def test_inputs_are_not_modified(self) -> None:
        """Regla 6: los anillos de entrada no se modifican (ni siquiera con la bandera de solo
        lectura) y el resultado es un array nuevo cada vez."""
        rng = np.random.default_rng(7)
        rings = random_rings(rng, 1)
        for ring in rings:
            ring.setflags(write=False)
        before = [ring.copy() for ring in rings]
        first = zones.cells_inside(rings, ROWS, COLS)
        first[:] = False
        self.assertTrue(zones.cells_inside(rings, ROWS, COLS).any())
        for ring, kept in zip(rings, before, strict=True):
            np.testing.assert_array_equal(ring, kept)

    def test_rejects_bad_input(self) -> None:
        """Un error del programa (``ValueError``): coordenadas no finitas, anillos que no son
        ``(n, 2)`` o ``(n, 3)``, una rejilla sin celdas."""
        square = np.array([[1.0, 1.0], [5.0, 1.0], [5.0, 5.0], [1.0, 5.0]])
        for bad in (np.array([[1.0, np.nan], [5.0, 1.0], [5.0, 5.0]]),
                    np.array([[1.0, np.inf], [5.0, 1.0], [5.0, 5.0]]),
                    np.array([1.0, 2.0, 3.0]), np.zeros((4, 4))):
            with self.subTest(bad=bad.shape), self.assertRaises(ValueError):
                zones.cells_inside([bad], ROWS, COLS)
        for rows, cols in ((0, COLS), (ROWS, 0), (-1, 3)):
            with self.subTest(shape=(rows, cols)), self.assertRaises(ValueError):
                zones.cells_inside([square], rows, cols)

    def test_a_polygon_of_2000_vertices(self) -> None:
        """A1: un polígono de 2.000 vértices (un círculo de radio 300 celdas) en una rejilla de
        800 × 800 celdas da su área con un error de ½ % (πr² = 282.743 celdas) y simétrico en
        las cuatro direcciones; sin bucle por celda, tarda centésimas (informativo, no se mide
        aquí)."""
        angles = np.linspace(0.0, 2.0 * np.pi, 2000, endpoint=False)
        ring = np.column_stack([400.0 + 300.0 * np.cos(angles), 400.0 + 300.0 * np.sin(angles)])
        found = zones.cells_inside([ring], 800, 800)
        self.assertAlmostEqual(found.sum() / (np.pi * 300.0 ** 2), 1.0, delta=0.005)
        self.assertTrue(found[400, 400])
        self.assertFalse(found[400, 90])
        self.assertFalse(found[0, 0])


# --- Coordenadas absolutas -------------------------------------------------------------------


class AbsoluteCoordinatesTest(unittest.TestCase):
    GRID = dfx.grid_from(40, 60, 2.0)

    def absolute(self, left: float, bottom: float, right: float, top: float) -> np.ndarray:
        """El anillo absoluto del rectángulo local (m desde la esquina suroeste de la rejilla)."""
        south = dfx.south_of(self.GRID)
        west = self.GRID.west
        return np.array([[west + left, south + bottom], [west + right, south + bottom],
                         [west + right, south + top], [west + left, south + top]])

    def test_to_cell_units_in_float64(self) -> None:
        """Regla 4 (ADR-0005): un anillo absoluto (norte de 4,4 Mm) pasa a unidades de celda en
        float64 sin perder el medio centímetro: la esquina oeste-norte es (0, 0) y un punto a
        7 celdas al este y 3 al sur de ella es (7, 3), bit a bit."""
        grid = self.GRID
        ring = np.array([[grid.west + 14.0, grid.north - 6.0], [grid.west, grid.north]])
        found = zones.to_cell_units([ring], grid)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].dtype, np.float64)
        np.testing.assert_array_equal(found[0], np.array([[7.0, 3.0], [0.0, 0.0]]))

    def test_absolute_rectangle_and_the_half_open_edges(self) -> None:
        """RF-013-01, D-16: un rectángulo absoluto con los bordes en los bordes de celda da
        exactamente sus columnas y filas; con los bordes sobre centros, el oeste y el norte
        dentro y el este y el sur fuera."""
        grid = self.GRID
        found = zones.polygons_cells([[self.absolute(20.0, 10.0, 60.0, 30.0)]], grid)
        expected = np.zeros(grid.shape, dtype=bool)
        top = grid.nrows - 15  # norte = 30 m sobre el sur: la fila 40 − 15
        expected[top:top + 10, 10:30] = True
        np.testing.assert_array_equal(found, expected)
        on_centers = zones.polygons_cells([[self.absolute(21.0, 11.0, 61.0, 31.0)]], grid)
        shifted = np.zeros(grid.shape, dtype=bool)
        shifted[top - 1:top + 9, 10:30] = True  # el norte (31 m) incluye su centro; el sur (11 m), no
        np.testing.assert_array_equal(on_centers, shifted)

    def test_polygons_are_united_and_the_rings_of_one_polygon_are_even_odd(self) -> None:
        """RF-013-01: varios polígonos son una unión (dos que se solapan no dejan hueco en lo
        común); los anillos de un mismo polígono, par-impar (el segundo es un hueco)."""
        grid = self.GRID
        first = self.absolute(10.0, 10.0, 50.0, 50.0)
        second = self.absolute(30.0, 30.0, 70.0, 70.0)
        united = zones.polygons_cells([[first], [second]], grid)
        alone = zones.polygons_cells([[first]], grid) | zones.polygons_cells([[second]], grid)
        np.testing.assert_array_equal(united, alone)
        xor = zones.polygons_cells([[first, second]], grid)
        common = (zones.polygons_cells([[first]], grid) & zones.polygons_cells([[second]], grid))
        self.assertTrue(common.any())
        self.assertFalse((xor & common).any())
        self.assertEqual(int(united.sum()), int(xor.sum()) + int(common.sum()))
        self.assertFalse(zones.polygons_cells([], grid).any())

    def test_the_z_of_the_vertices_does_not_count(self) -> None:
        """Una geometría con Z da las mismas celdas que sin ella."""
        ring = self.absolute(20.0, 10.0, 60.0, 30.0)
        with_z = np.column_stack([ring, np.full(4, 650.0)])
        np.testing.assert_array_equal(zones.polygons_cells([[with_z]], self.GRID),
                                      zones.polygons_cells([[ring]], self.GRID))


# --- Sectores --------------------------------------------------------------------------------


class SectorLabelsTest(unittest.TestCase):
    def sectors(self, case: dfx.SectorsCase) -> list[object]:
        return [constraints_model.Sector(f"{index:032d}", code, code, (ring,))
                for index, (code, ring) in enumerate(case.rings().items(), start=1)]

    def test_three_sectors_of_the_reference_case(self) -> None:
        """RF-013-01, RF-013-07, CE-013-05: tres franjas de 50 columnas dan las etiquetas 1, 2 y 3
        por su orden, sin celdas sin sector (``int16``; 0 = ninguno)."""
        case = dfx.three_sectors_case()
        labels = zones.sector_labels(self.sectors(case), case.grid)
        self.assertEqual(labels.dtype, np.int16)
        self.assertEqual(labels.shape, case.grid.shape)
        np.testing.assert_array_equal(labels, case.labels())
        self.assertEqual(sorted(set(labels.ravel().tolist())), [1, 2, 3])

    def test_cells_outside_every_sector_are_zero(self) -> None:
        """Un sector que ocupa solo parte de la rejilla deja el resto en 0; sin sectores, todo 0."""
        case = dfx.imposed_sector_case()
        first = self.sectors(case)[:1]
        labels = zones.sector_labels(first, case.grid)
        expected = np.zeros(case.grid.shape, dtype=np.int16)
        expected[:, :60] = 1
        np.testing.assert_array_equal(labels, expected)
        self.assertFalse(zones.sector_labels([], case.grid).any())

    def test_adjacent_sectors_share_no_cell_on_the_common_edge(self) -> None:
        """D-16: dos sectores contiguos con la frontera sobre centros de celda se reparten esas
        celdas (ni hueco ni doble): cada celda tiene una sola etiqueta y no queda ninguna sin
        ella dentro de la unión."""
        grid = dfx.grid_from(20, 30, 1.0)
        south = dfx.south_of(grid)
        west = grid.west
        # La frontera vertical en 15,5 (centro de la columna 15) y la horizontal exterior sobre
        # los centros de las filas 5 y 14.
        left = np.array([[west + 2.5, south + 5.5], [west + 15.5, south + 5.5],
                         [west + 15.5, south + 14.5], [west + 2.5, south + 14.5]])
        right = np.array([[west + 15.5, south + 5.5], [west + 27.5, south + 5.5],
                          [west + 27.5, south + 14.5], [west + 15.5, south + 14.5]])
        sectors = [constraints_model.Sector("a" * 32, "uno", "Uno", (left,)),
                   constraints_model.Sector("b" * 32, "dos", "Dos", (right,))]
        labels = zones.sector_labels(sectors, grid)
        union = zones.polygons_cells(
            [[left], [right]], grid)
        np.testing.assert_array_equal(labels > 0, union)
        self.assertEqual(int((labels == 1).sum()) + int((labels == 2).sum()), int(union.sum()))
        # Columnas 2 a 14 para el primero y 15 a 26 para el segundo (oeste incluido, este fuera).
        self.assertEqual(sorted(set(np.nonzero((labels == 1).any(axis=0))[0].tolist())),
                         list(range(2, 15)))
        self.assertEqual(sorted(set(np.nonzero((labels == 2).any(axis=0))[0].tolist())),
                         list(range(15, 27)))

    def test_a_narrow_sector_costs_its_box_and_not_the_whole_grid(self) -> None:
        """RF-013-07, RNF-013-07: pintar un sector no reserva memoria por todas las columnas de la
        rejilla, sino por las de su caja (con 20 franjas de 1.640 filas sobre 2,81 M celdas, cada
        franja pintaba la rejilla entera: 192 ms de una sola llamada). Una franja de 10 columnas y
        2.800 filas en una rejilla de 3.000 × 3.000 celdas deja las mismas etiquetas de siempre y gasta,
        además del resultado, menos de 8 MiB (pintada a todo el ancho gastaba 72 MiB)."""
        grid = dfx.grid_from(3000, 3000, 1.0)
        south = dfx.south_of(grid)
        ring = np.array([[grid.west + 100.0, south + 100.0], [grid.west + 110.0, south + 100.0],
                         [grid.west + 110.0, south + 2900.0], [grid.west + 100.0, south + 2900.0]])
        sector = constraints_model.Sector("a" * 32, "franja", "Franja", (ring,))
        tracemalloc.start()
        try:
            labels = zones.sector_labels([sector], grid)
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        expected = np.zeros((3000, 3000), dtype=np.int16)
        expected[100:2900, 100:110] = 1
        np.testing.assert_array_equal(labels, expected)
        self.assertLess(peak - labels.nbytes, 8 * 2**20, f"{(peak - labels.nbytes) / 2**20:.1f} MiB")

    def test_first_sector_wins_where_two_overlap(self) -> None:
        """Dos sectores que (contra la 012) se solapan: la celda común es del primero, sin error ni
        silencio sobre el resto; más de 32.767 sectores no caben en ``int16``."""
        grid = dfx.grid_from(10, 10, 1.0)
        south = dfx.south_of(grid)
        a = np.array([[grid.west + 1.0, south + 1.0], [grid.west + 7.0, south + 1.0],
                      [grid.west + 7.0, south + 7.0], [grid.west + 1.0, south + 7.0]])
        b = a + 3.0
        sectors = [constraints_model.Sector("a" * 32, "uno", "Uno", (a,)),
                   constraints_model.Sector("b" * 32, "dos", "Dos", (b,))]
        labels = zones.sector_labels(sectors, grid)
        alone = zones.sector_labels(sectors[:1], grid)
        np.testing.assert_array_equal(labels[alone == 1], np.ones(int((alone == 1).sum())))
        self.assertGreater(int((labels == 2).sum()), 0)
        with self.assertRaises(ValueError):
            zones.sector_labels([sectors[0]] * 40_000, grid)


# --- Las celdas de una restricción y de una capa del proyecto --------------------------------


class ProjectZonesTest(dfx.DesignProjectCase):
    """Sobre el proyecto del diseño: las máscaras de V01, los sectores de la 012 y capas de
    polígonos escritas en él."""

    @staticmethod
    def expected(grid: object, left: float, bottom: float, right: float, top: float
                 ) -> np.ndarray:
        """Las celdas de la rejilla con el centro en [oeste, este) × (sur, norte], absolutas."""
        cx, cy = grid.centers()  # type: ignore[attr-defined]
        x0, y0 = cfx.BASE[0] + left, cfx.BASE[1] + bottom
        x1, y1 = cfx.BASE[0] + right, cfx.BASE[1] + top
        return (cx >= x0) & (cx < x1) & (cy > y0) & (cy <= y1)

    def test_constraint_zone_is_the_zone_of_the_masks(self) -> None:
        """RF-013-01: las celdas de una restricción son las de su zona en las máscaras de la
        versión (``MaskSet.zone``, celda entera, D-1 de la 012), como array de la forma de la
        rejilla, nuevo cada vez; para cada restricción con zona."""
        masks = self.masks()
        codes = sorted(masks.zones)
        self.assertIn("balsa", codes)
        for code in codes:
            with self.subTest(code=code):
                found = zones.constraint_cells(masks, code)
                self.assertEqual(found.dtype, np.bool_)
                self.assertEqual(found.shape, masks.grid.shape)
                self.assertEqual(int(found.sum()), masks.zone(code).cells)
                np.testing.assert_array_equal(found, masks.zone(code).mask(masks.grid.shape))
        balsa = zones.constraint_cells(masks, "balsa")
        self.assertGreater(int(balsa.sum()), 0)
        balsa[:] = False  # no cambia las máscaras
        self.assertGreater(int(zones.constraint_cells(masks, "balsa").sum()), 0)

    def test_unknown_constraint_zone_is_refused(self) -> None:
        """RF-013-16 (principio 10): una restricción sin zona en las máscaras se rechaza nombrando
        la zona y el campo, y diciendo qué hacer."""
        masks = self.masks()
        with self.assertRaises(messages.DesignError) as caught:
            zones.constraint_cells(masks, "no_existe")
        error = caught.exception
        self.assertEqual(error.code, "des.zone_unknown")
        self.assertEqual(error.value, "no_existe")
        self.assertIn("no_existe", error.text)
        self.assertIn("Restricciones…", error.text)

    def test_sector_labels_of_the_project_match_their_rectangles(self) -> None:
        """RF-013-07: los dos sectores de la 012 en la rejilla del proyecto (160 × 160 de 2 m)
        etiquetan las celdas de sus rectángulos (centro en [oeste, este) × (sur, norte]), contados
        a mano: 35 × 80 = 2.800 celdas cada uno; el resto, 0."""
        grid = self.masks().grid
        sectors = cp.sectors()
        labels = zones.sector_labels(sectors, grid)
        for index, box in enumerate(cfx.SECTORS_LOCAL.values(), start=1):
            with self.subTest(sector=index):
                found = labels == index
                np.testing.assert_array_equal(found, self.expected(grid, *box))
                self.assertEqual(int(found.sum()), 35 * 80)
        self.assertEqual(int((labels == 0).sum()), grid.nrows * grid.ncols - 2 * 35 * 80)

    def test_layer_of_polygons_features_and_domains(self) -> None:
        """RF-013-01, RF-013-02: las celdas de una capa de polígonos del proyecto —de entidades
        (``gis_fea_``, la 012) o de dominios (``gis_dom_``, la 011)— son la unión de sus
        polígonos por el centro, con huecos; los bordes sobre centros (impares en metros) incluyen
        el oeste y el norte; las dos familias dan lo mismo y la capa no se modifica."""
        grid = self.masks().grid
        outer = (21.0, 21.0, 101.0, 101.0)
        hole = (41.0, 41.0, 61.0, 61.0)
        other = (81.0, 61.0, 141.0, 121.0)
        entities = [[[cfx.rectangle(*outer), cfx.rectangle(*hole)]], [[cfx.rectangle(*other)]]]
        self.write_layer("gis_fea_zona_de_trabajo", entities)
        self.write_layer("gis_dom_zona_de_trabajo", entities, domains=True)
        expected = ((self.expected(grid, *outer) & ~self.expected(grid, *hole))
                    | self.expected(grid, *other))
        # A mano, en celdas de 2 m: 40 × 40 el grande, menos el hueco de 10 × 10, más el otro de
        # 30 × 30 menos los 10 × 20 que comparten.
        self.assertEqual(int(expected.sum()), 1600 - 100 + 900 - 200)
        for name in ("gis_fea_zona_de_trabajo", "gis_dom_zona_de_trabajo"):
            with self.subTest(layer=name):
                before = self.record(name).content_sha256
                found = zones.layer_cells(self.project, name, grid)
                np.testing.assert_array_equal(found, expected)
                self.assertEqual(self.record(name).content_sha256, before)

    def test_layer_that_is_not_made_of_polygons(self) -> None:
        """RF-013-16: una capa de líneas se rechaza nombrando la capa y su geometría; una capa
        que no hay, con el error de ``gis``; un dato que no es una capa de entidades o de
        dominios, un error del programa."""
        line = np.array([[cfx.BASE[0] + 20.0, cfx.BASE[1] + 20.0],
                         [cfx.BASE[0] + 80.0, cfx.BASE[1] + 90.0]])
        self.write_layer("gis_fea_trazas", [[[line]]], kind="line")
        grid = self.masks().grid
        with self.assertRaises(messages.DesignError) as caught:
            zones.layer_cells(self.project, "gis_fea_trazas", grid)
        self.assertEqual(caught.exception.code, "des.layer_not_polygons")
        self.assertEqual(caught.exception.value, "líneas")
        self.assertIn("gis_fea_trazas", caught.exception.text)
        with self.assertRaises(gis_messages.GisError) as unknown:
            zones.layer_cells(self.project, "gis_fea_no_hay", grid)
        self.assertEqual(unknown.exception.code, "gis.dataset_unknown")
        with self.assertRaises(ValueError):
            zones.layer_cells(self.project, dfx.START_DATASET, grid)


if __name__ == "__main__":
    unittest.main()
