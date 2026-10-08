# SPDX-License-Identifier: GPL-3.0-or-later
"""Preparación de las restricciones de un TIN (spec 006, T16; plan 006 §5.3.2 y §5.4 A8,
``gis.breaklines.prepare_constraints``).

- **RF-006-14**: dos roturas que se cruzan con la misma cota (≤ 0,01 m) dan un vértice
  nuevo en el cruce, con la cota media, que parte las dos; con cotas distintas, un
  conflicto con sus identificadores, la posición del cruce y las dos cotas. Un punto a
  ≤ 1 mm de una rotura (de un segmento o de un vértice) sigue la misma regla, y también una
  rotura que toca a otra (en T o en un vértice común) o se solapa con ella a lo largo
  (colineal: conflicto si la cota difiere). Todos los conflictos se listan a la vez y el
  TIN no se crea.
- **RF-006-13**: las aristas obligatorias que salen no se cruzan, cubren las roturas duras
  de entrada, no hay dos vértices a ≤ 1 mm y cada vértice de entrada que queda conserva sus
  coordenadas float64 bit a bit (los puntos sobre una rotura, también); las roturas
  blandas solo aportan puntos. ``vertex_source`` sigue el plan §5.2.2.

Las entradas no se modifican (arrays de solo lectura).
"""

import itertools
import unittest

import numpy as np

from tests.support.package import import_geoblender
from tests.support.repo import ROOT

gis = import_geoblender("gis")
points = import_geoblender("gis.points")
breaklines = import_geoblender("gis.breaklines")
messages = import_geoblender("gis.messages")
csv_tables = import_geoblender("interop.csv_tables")

TALUDES = ROOT / "tests" / "data" / "gis" / "points" / "taludes.csv"
ROLES = {"point_id": "P", "x": "X", "y": "Y", "z": "Z", "code": "Código", "line": "Línea"}
E0, N0 = 700_000.0, 4_400_000.0
TOL = 0.001
Kind = gis.ConflictKind


def _frozen(rows) -> np.ndarray:
    array = np.array(rows, dtype=np.float64).reshape(-1, 3)
    array.flags.writeable = False  # una entrada nunca se modifica
    return array


def _abs(x: float, y: float, z: float) -> tuple[float, float, float]:
    return (E0 + x, N0 + y, z)


def _points(*rows: tuple) -> object:
    """Un ``PointSet`` de filas (P, x, y, z), con x, y relativos a (E0, N0)."""
    xyz = _frozen([_abs(x, y, z) for _p, x, y, z in rows])
    ids = tuple(str(p) for p, *_ in rows)
    return points.PointSet(xyz, ids, ("",) * len(rows), tuple(range(1, len(rows) + 1)))


NO_POINTS = _points()


def _line(line_id: str, *vertices: tuple, hard: bool = True) -> object:
    """Una rotura de vértices (x, y, z) relativos a (E0, N0)."""
    return points.Breakline(line_id, _frozen([_abs(*v) for v in vertices]), hard=hard)


def _prepare(point_set=NO_POINTS, lines=(), **options):
    return breaklines.prepare_constraints(point_set, list(lines), **options)


def _conflicts(point_set=NO_POINTS, lines=(), **options):
    """El ``ConflictError`` de la preparación (TIN «topo»); si no lo hay, la prueba falla."""
    try:
        _prepare(point_set, lines, name="topo", **options)
    except gis.ConflictError as error:
        return error
    raise AssertionError("se esperaba un ConflictError y no hubo ninguno")


def _edges(*pairs) -> list[list[int]]:
    return sorted(sorted(pair) for pair in pairs)


def _segment_distances(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Distancia de cada punto ``p`` ``(m, 2)`` a cada segmento ``a``–``b`` ``(s, 2)``:
    ``(m, s)``, por fuerza bruta."""
    d = b - a
    rel = p[:, None, :] - a[None, :, :]
    t = np.clip(np.einsum("msk,sk->ms", rel, d) / np.einsum("sk,sk->s", d, d), 0.0, 1.0)
    gap = rel - t[..., None] * d[None]
    return np.hypot(gap[..., 0], gap[..., 1])


def _orient(p: np.ndarray, q: np.ndarray, r: np.ndarray) -> np.ndarray:
    return (q[..., 0] - p[..., 0]) * (r[..., 1] - p[..., 1]) - (
        (q[..., 1] - p[..., 1]) * (r[..., 0] - p[..., 0]))


def _proper_crossings(xy: np.ndarray, edges: np.ndarray) -> list[tuple[int, int]]:
    """Parejas de aristas que se cruzan en su interior, sin compartir vértice (fuerza
    bruta: todas con todas)."""
    a, b = xy[edges[:, 0]][:, None], xy[edges[:, 1]][:, None]
    c, d = xy[edges[:, 0]][None], xy[edges[:, 1]][None]
    shared = ((edges[:, None, 0] == edges[None, :, 0]) | (edges[:, None, 0] == edges[None, :, 1])
              | (edges[:, None, 1] == edges[None, :, 0])
              | (edges[:, None, 1] == edges[None, :, 1]))
    cross = ((_orient(a, b, c) * _orient(a, b, d) < 0)
             & (_orient(c, d, a) * _orient(c, d, b) < 0) & ~shared)
    return [(int(i), int(j)) for i, j in zip(*np.nonzero(np.triu(cross)), strict=True)]


class CrossingTest(unittest.TestCase):
    """RF-006-14: cruce de dos roturas duras."""

    A = ((0.0, 0.0, 100.0), (10.0, 10.0, 110.0))

    def test_same_elevation_adds_vertex(self) -> None:
        """Con la misma cota en el cruce, un vértice nuevo en (5; 5) con la cota media, de
        origen «rotura dura», y las dos roturas partidas en él."""
        prepared = _prepare(lines=[_line("A", *self.A),
                                   _line("B", (0.0, 10.0, 110.0), (10.0, 0.0, 100.0))])
        self.assertIsInstance(prepared, breaklines.PreparedInput)
        self.assertEqual(prepared.xyz.dtype, np.float64)
        self.assertEqual(prepared.xyz[4].tolist(), list(_abs(5.0, 5.0, 105.0)))
        self.assertEqual(prepared.xyz[:4].tolist(), [list(_abs(*v)) for v in (
            *self.A, (0.0, 10.0, 110.0), (10.0, 0.0, 100.0))])
        self.assertEqual(prepared.vertex_source.dtype, np.uint8)
        self.assertEqual(prepared.vertex_source.tolist(), [1] * 5)
        self.assertEqual(prepared.edges.dtype, np.int32)
        self.assertEqual(prepared.edges.tolist(), _edges((0, 4), (1, 4), (2, 4), (3, 4)))
        self.assertEqual((prepared.input_vertices, prepared.merged, prepared.crossings,
                          prepared.splits), (4, 0, 1, 0))

    def test_tolerance_of_elevation(self) -> None:
        """Δz de 0,008 m en el cruce: vértice con la cota media (105,004 m)."""
        prepared = _prepare(lines=[_line("A", *self.A),
                                   _line("B", (0.0, 10.0, 110.008), (10.0, 0.0, 100.008))])
        self.assertEqual(prepared.crossings, 1)
        self.assertAlmostEqual(float(prepared.xyz[4, 2]), 105.004, places=9)

    def test_different_elevation_is_a_conflict(self) -> None:
        """Con cotas distintas, un conflicto con las dos roturas, la posición del cruce y
        sus dos cotas (105 y 110 m); el texto es el del plan §5.5."""
        error = _conflicts(lines=[_line("A", *self.A),
                                  _line("B", (0.0, 10.0, 120.0), (10.0, 0.0, 100.0))])
        self.assertEqual(error.code, "gis.constraint_conflicts")
        self.assertEqual(error.conflicts, (gis.Conflict(
            Kind.CROSSING_LINES, ("A", "B"), E0 + 5.0, N0 + 5.0, (105.0, 110.0)),))
        self.assertEqual(error.texts(), [
            "TIN «topo»: las líneas de rotura «A» y «B» se cruzan en "
            "(700 005,000; 4 400 005,000) con cotas 105,000 m y 110,000 m."])

    def test_point_at_the_crossing(self) -> None:
        """Un punto a 0,4 mm del cruce, con su cota: el vértice del cruce es el punto, con
        sus coordenadas de entrada bit a bit (RF-006-13), y parte las dos roturas."""
        point_set = _points(("P", 5.0003, 5.0002, 105.004))
        prepared = _prepare(point_set, [_line("A", *self.A),
                                        _line("B", (0.0, 10.0, 110.0), (10.0, 0.0, 100.0))])
        self.assertEqual(prepared.xyz[0].tobytes(), point_set.xyz[0].tobytes())
        self.assertEqual(len(prepared.xyz), 5)
        self.assertEqual(prepared.edges.tolist(), _edges((0, 1), (0, 2), (0, 3), (0, 4)))
        self.assertEqual((prepared.merged, prepared.crossings, prepared.splits), (0, 0, 2))

    def test_three_lines_through_one_point(self) -> None:
        """Tres roturas casi concurrentes (la tercera a 0,3 mm): sus tres cruces quedan a
        < 1 mm y se funden en un solo vértice; sin cruces entre las aristas."""
        for offset in (0.0, 0.0003):
            with self.subTest(desplazamiento=offset):
                prepared = _prepare(lines=[
                    _line("A", (0.0, 0.0, 100.0), (10.0, 10.0, 100.0)),
                    _line("B", (0.0, 10.0, 100.0), (10.0, 0.0, 100.0)),
                    _line("C", (5.0 + offset, 0.0, 100.0), (5.0 + offset, 10.0, 100.0)),
                ])
                self.assertEqual(len(prepared.xyz), 7)
                self.assertEqual(prepared.crossings, 1)
                self.assertEqual(prepared.edges.tolist(),
                                 _edges(*((i, 6) for i in range(6))))
                self.assertEqual(prepared.xyz[6, :2].tolist(), [E0 + 5.0, N0 + 5.0])


class PointOnLineTest(unittest.TestCase):
    """RF-006-14: un punto a ≤ 1 mm de una rotura dura."""

    LINE = _line("A", (0.0, 0.0, 100.0), (10.0, 0.0, 110.0))

    def test_point_on_segment_splits_it(self) -> None:
        """A 0,8 mm del segmento y Δz 0,003 m: el punto parte la rotura y conserva sus
        coordenadas bit a bit (origen «punto»)."""
        point_set = _points(("P", 4.0, 0.0008, 104.003))
        prepared = _prepare(point_set, [self.LINE])
        self.assertEqual(prepared.xyz[0].tobytes(), point_set.xyz[0].tobytes())
        self.assertEqual(prepared.vertex_source.tolist(), [0, 1, 1])
        self.assertEqual(prepared.edges.tolist(), _edges((0, 1), (0, 2)))
        self.assertEqual((prepared.splits, prepared.merged), (1, 0))

    def test_point_beyond_tolerance_is_left_alone(self) -> None:
        """A 1,5 mm el punto no toca la rotura."""
        prepared = _prepare(_points(("P", 4.0, 0.0015, 120.0)), [self.LINE])
        self.assertEqual(prepared.edges.tolist(), [[1, 2]])
        self.assertEqual(prepared.splits, 0)

    def test_point_on_vertex_is_merged(self) -> None:
        """A 0,5 mm de un vértice de la rotura y Δz 0,002 m: se funde en el vértice, que
        conserva sus coordenadas."""
        prepared = _prepare(_points(("P", 10.0004, 0.0003, 110.002)), [self.LINE])
        self.assertEqual(prepared.xyz.tolist(), [list(_abs(0.0, 0.0, 100.0)),
                                                 list(_abs(10.0, 0.0, 110.0))])
        self.assertEqual(prepared.edges.tolist(), [[0, 1]])
        self.assertEqual((prepared.merged, prepared.input_vertices), (1, 3))

    def test_different_elevation_is_a_conflict(self) -> None:
        """Con Δz > 0,01 m, conflicto «punto sobre rotura» con el punto y la rotura, la
        posición del punto y las dos cotas, sobre el segmento y sobre un vértice."""
        cases = (((4.0, 0.0008, 104.5), (104.5, 104.0)),
                 ((10.0004, 0.0003, 110.5), (110.5, 110.0)))
        for (x, y, z), heights in cases:
            with self.subTest(x=x):
                error = _conflicts(_points(("P", x, y, z)), [self.LINE])
                self.assertEqual(len(error.conflicts), 1)
                conflict = error.conflicts[0]
                self.assertEqual((conflict.kind, conflict.ids), (Kind.POINT_ON_LINE, ("P", "A")))
                self.assertEqual((conflict.x, conflict.y), (E0 + x, N0 + y))
                self.assertEqual(conflict.z[0], heights[0])
                self.assertAlmostEqual(conflict.z[1], heights[1], places=9)
                self.assertIn("el punto «P» está sobre la línea de rotura «A»",
                              error.texts()[0])

    def test_points_on_a_reversed_segment(self) -> None:
        """Dos puntos sobre un segmento que se recorre del vértice de mayor índice al de
        menor (la rotura B acaba en el vértice que comparte con A): la rotura pasa por los
        dos en su orden (Q a 17 m y P a 12 m)."""
        point_set = _points(("P", 12.0, 0.0005, 112.0), ("Q", 17.0, -0.0005, 117.0))
        prepared = _prepare(point_set, [
            self.LINE, _line("B", (20.0, 0.0, 120.0), (10.0, 0.0, 110.0))])
        self.assertEqual(len(prepared.xyz), 5)
        self.assertEqual(prepared.edges.tolist(), _edges((2, 3), (1, 4), (0, 1), (0, 3)))
        self.assertEqual((prepared.merged, prepared.splits), (1, 2))

    def test_soft_lines_only_give_points(self) -> None:
        """Una rotura blanda no da aristas: sus vértices son puntos de origen «rotura
        blanda» y, si uno cae sobre una dura, la parte; si cae sobre un vértice de la dura
        con otra cota, el conflicto es de «punto sobre rotura» (primero, el punto)."""
        soft = _line("S", (5.0, 0.0005, 105.0), (5.0, 8.0, 109.0), hard=False)
        prepared = _prepare(lines=[self.LINE, soft])
        self.assertEqual(prepared.vertex_source.tolist(), [1, 1, 2, 2])
        self.assertEqual(prepared.edges.tolist(), _edges((0, 2), (1, 2)))
        error = _conflicts(lines=[self.LINE, _line("S", (10.0003, 0.0, 112.0),
                                                   (10.0, 8.0, 109.0), hard=False)])
        self.assertEqual(error.conflicts, (gis.Conflict(
            Kind.POINT_ON_LINE, ("S", "A"), E0 + 10.0003, N0, (112.0, 110.0)),))


class LinesTouchingTest(unittest.TestCase):
    """RF-006-14: roturas que se tocan (en T, en un vértice común) o se solapan."""

    A = ((0.0, 0.0, 100.0), (10.0, 0.0, 110.0))

    def test_t_junction(self) -> None:
        """Una rotura que acaba sobre otra la parte, también si se pasa 0,5 mm (sin vértice
        de cruce); con Δz de 2 m, un solo conflicto de cruce, en su extremo."""
        for overshoot in (0.0, 0.0005):
            with self.subTest(pasado=overshoot):
                prepared = _prepare(lines=[_line("A", *self.A), _line(
                    "B", (5.0, -overshoot, 105.0), (5.0, 10.0, 115.0))])
                self.assertEqual(prepared.edges.tolist(), _edges((0, 2), (1, 2), (2, 3)))
                self.assertEqual((prepared.splits, prepared.crossings), (1, 0))
                error = _conflicts(lines=[_line("A", *self.A), _line(
                    "B", (5.0, -overshoot, 107.0), (5.0, 10.0, 115.0))])
                self.assertEqual(error.conflicts, (gis.Conflict(
                    Kind.CROSSING_LINES, ("A", "B"), E0 + 5.0, N0 - overshoot,
                    (105.0, 107.0)),))

    def test_shared_vertex(self) -> None:
        """Un vértice común se funde en uno; con cotas distintas, conflicto de cruce."""
        prepared = _prepare(lines=[_line("A", *self.A),
                                   _line("B", (10.0, 0.0, 110.0), (10.0, 10.0, 120.0))])
        self.assertEqual(len(prepared.xyz), 3)
        self.assertEqual(prepared.edges.tolist(), _edges((0, 1), (1, 2)))
        self.assertEqual(prepared.merged, 1)
        error = _conflicts(lines=[_line("A", *self.A),
                                  _line("B", (10.0, 0.0, 111.0), (10.0, 10.0, 120.0))])
        self.assertEqual(error.conflicts, (gis.Conflict(
            Kind.CROSSING_LINES, ("A", "B"), E0 + 10.0, N0, (110.0, 111.0)),))

    def test_collinear_overlap(self) -> None:
        """Solape colineal de 5 m con la misma cota: una sola arista para el tramo común,
        sin vértices nuevos; con 1 m de diferencia, dos conflictos de solape (en 5 y 10 m)."""
        prepared = _prepare(lines=[_line("A", *self.A),
                                   _line("B", (5.0, 0.0, 105.0), (15.0, 0.0, 115.0))])
        self.assertEqual(prepared.edges.tolist(), _edges((0, 2), (1, 2), (1, 3)))
        self.assertEqual((prepared.crossings, prepared.splits), (0, 2))
        error = _conflicts(lines=[_line("A", *self.A),
                                  _line("B", (5.0, 0.0, 106.0), (15.0, 0.0, 116.0))])
        self.assertEqual([(c.kind, c.ids, c.x, c.y) for c in error.conflicts], [
            (Kind.COLLINEAR_OVERLAP, ("A", "B"), E0 + 5.0, N0),
            (Kind.COLLINEAR_OVERLAP, ("A", "B"), E0 + 10.0, N0)])
        self.assertEqual(error.conflicts[0].z, (105.0, 106.0))
        self.assertEqual(error.conflicts[1].z, (110.0, 111.0))
        self.assertIn("se solapan", error.texts()[0])

    def test_same_segment_twice(self) -> None:
        """El mismo segmento en dos roturas: una sola arista; si acaba con otra cota, un
        conflicto de solape en ese extremo."""
        prepared = _prepare(lines=[_line("A", *self.A), _line("B", *self.A)])
        self.assertEqual((prepared.edges.tolist(), prepared.merged), ([[0, 1]], 2))
        error = _conflicts(lines=[_line("A", *self.A),
                                  _line("B", (0.0, 0.0, 100.0), (10.0, 0.0, 111.0))])
        self.assertEqual(error.conflicts, (gis.Conflict(
            Kind.COLLINEAR_OVERLAP, ("A", "B"), E0 + 10.0, N0, (110.0, 111.0)),))

    def test_all_conflicts_at_once(self) -> None:
        """Un cruce, un punto sobre rotura y dos puntos duplicados en conflicto se listan
        juntos, con el número de conflictos y las tolerancias en el mensaje."""
        point_set = _points(("P", 4.0, 0.0, 120.0), ("Q", 20.0, 20.0, 100.0),
                            ("R", 20.0004, 20.0, 101.0))
        error = _conflicts(point_set, [_line("A", *self.A),
                                       _line("B", (2.0, -5.0, 90.0), (2.0, 5.0, 90.0))])
        self.assertEqual(sorted(c.kind.value for c in error.conflicts),
                         ["crossing_lines", "duplicate_points", "point_on_line"])
        self.assertEqual(error.value, 3)
        self.assertEqual(error.text, messages.render(
            "gis.constraint_conflicts", tin="topo", value=3, tol_xy=TOL, tol_z=0.01))


class RobustnessTest(unittest.TestCase):
    """RF-006-13: lo que recibe el triangulador, en datos de verdad y aleatorios."""

    def test_taludes_untouched(self) -> None:
        """``points/taludes.csv``: 20 puntos y 4 roturas que no se tocan dan 44 vértices
        bit a bit, 20 aristas y ningún cambio."""
        table = csv_tables.read_table(TALUDES, encoding="utf-8", separator=";")
        mapping = points.ColumnMapping.by_name(table.columns, **ROLES)
        point_set, lines, _report = points.points_from_rows(
            table.columns, table.rows, mapping, ",", row_numbers=table.lines)
        prepared = _prepare(point_set, lines)
        want = np.concatenate([point_set.xyz, *(line.xyz for line in lines)])
        self.assertEqual(prepared.xyz.tobytes(), want.tobytes())
        self.assertEqual(prepared.vertex_source.tolist(), [0] * 20 + [1] * 24)
        chains = [range(20 + 6 * k, 26 + 6 * k) for k in range(4)]
        self.assertEqual(prepared.edges.tolist(),
                         _edges(*(pair for chain in chains
                                  for pair in itertools.pairwise(chain))))
        self.assertEqual((prepared.merged, prepared.crossings, prepared.splits), (0, 0, 0))

    def test_random_lines(self) -> None:
        """5 juegos de 12 roturas aleatorias con su cota en un plano y 40 puntos (6 sobre
        las roturas): ningún cruce entre aristas; ningún par de vértices a ≤ 1 mm; los
        vértices de entrada, bit a bit; cada arista sobre una rotura de entrada y cada
        rotura cubierta entera por sus aristas; cotas de los cruces en el plano."""
        def plane(x, y):
            return 100.0 + 0.3 * x + 0.2 * y

        for seed in range(5):
            with self.subTest(semilla=seed):
                rng = np.random.default_rng(seed)
                lines = []
                for k in range(12):
                    xy = rng.uniform(0, 50, (int(rng.integers(2, 5)), 2))
                    lines.append(_line(f"L{k}", *((x, y, plane(x, y)) for x, y in xy)))
                free = rng.uniform(0, 50, (34, 2))
                segment = lines[0].xyz[:2, :2] - (E0, N0)
                on = segment[0] + rng.uniform(0.1, 0.9, (6, 1)) * (segment[1] - segment[0])
                xy = np.concatenate([free, on])
                point_set = _points(*((f"P{i}", x, y, plane(x, y)) for i, (x, y) in
                                      enumerate(xy)))
                prepared = _prepare(point_set, lines)
                local = prepared.xyz[:, :2] - (E0, N0)
                self.assertEqual(_proper_crossings(local, prepared.edges), [])
                delta = local[:, None] - local[None]
                distance = np.hypot(delta[..., 0], delta[..., 1])
                np.fill_diagonal(distance, np.inf)
                self.assertGreater(distance.min(), TOL)
                inputs = np.concatenate([point_set.xyz, *(line.xyz for line in lines)])
                self.assertEqual(prepared.xyz[:len(inputs)].tobytes(), inputs.tobytes())
                self.assertEqual(prepared.merged, 0)
                self.assertEqual(prepared.splits, 6)
                self.assertEqual(len(prepared.xyz), len(inputs) + prepared.crossings)
                added = prepared.xyz[len(inputs):]
                self.assertLess(np.abs(added[:, 2] - plane(added[:, 0] - E0,
                                                            added[:, 1] - N0)).max(), 1e-9)
                starts = np.concatenate([line.xyz[:-1, :2] for line in lines]) - (E0, N0)
                ends = np.concatenate([line.xyz[1:, :2] for line in lines]) - (E0, N0)
                edges = prepared.edges
                hosts = ((_segment_distances(local[edges[:, 0]], starts, ends) < 1e-6)
                         & (_segment_distances(local[edges[:, 1]], starts, ends) < 1e-6))
                self.assertTrue(hosts.any(axis=1).all(), "arista fuera de las roturas")
                lengths = np.hypot(*(local[edges[:, 0]] - local[edges[:, 1]]).T)
                np.testing.assert_allclose(lengths @ hosts, np.hypot(*(ends - starts).T),
                                           rtol=0, atol=1e-6)

    def test_inputs_and_types(self) -> None:
        """Entradas que no son un ``PointSet`` y ``Breakline`` son un error del programa;
        las tolerancias se validan como parámetros; sin roturas no hay aristas."""
        with self.assertRaises(TypeError):
            breaklines.prepare_constraints(np.zeros((1, 3)), [])
        with self.assertRaises(TypeError):
            breaklines.prepare_constraints(NO_POINTS, [np.zeros((2, 3))])
        with self.assertRaises(ValueError):
            _prepare(_points(("P", 0.0, 0.0, float("nan"))))
        with self.assertRaises(ValueError):
            _prepare(lines=[_line("A", (0.0, 0.0, 1.0), (1.0, 0.0, float("inf")))])
        with self.assertRaises(messages.GisError) as caught:
            _prepare(lines=[_line("A", (0, 0, 1), (1, 0, 1))], tol_xy=-1.0)
        self.assertEqual(caught.exception.field, "gis.points.dup_xy_tol_m")
        prepared = _prepare(_points(("P", 0.0, 0.0, 1.0), ("Q", 1.0, 0.0, 1.0)))
        self.assertEqual(prepared.edges.shape, (0, 2))
        self.assertEqual(prepared.vertex_source.tolist(), [0, 0])
        empty = _prepare()
        self.assertEqual((empty.xyz.shape, empty.edges.shape), ((0, 3), (0, 2)))

    def test_vertex_source_codes(self) -> None:
        """Los códigos de ``vertex_source`` del plan §5.2.2."""
        self.assertEqual((breaklines.SOURCE_POINT, breaklines.SOURCE_HARD,
                          breaklines.SOURCE_SOFT, breaklines.SOURCE_CONTOUR,
                          breaklines.SOURCE_ADDED, breaklines.SOURCE_CELL),
                         (0, 1, 2, 3, 4, 5))

    def test_package_reexports(self) -> None:
        """``gis`` reexporta la API de la tarea (plan §5.1)."""
        for name in ("PreparedInput", "prepare_constraints", "Conflict", "ConflictKind"):
            with self.subTest(nombre=name):
                self.assertIn(name, gis.__all__)


if __name__ == "__main__":
    unittest.main()
