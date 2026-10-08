# SPDX-License-Identifier: GPL-3.0-or-later
"""TIN desde puntos y líneas de rotura (spec 006, T18; plan 006 §5.2.2, §5.3.2 y §5.4 A11,
``gis.tin``).

- **RF-006-13**: con ``PureTriangulator``, las roturas duras de ``points/taludes.csv`` son
  sucesiones de aristas del TIN (sin restricciones, la triangulación de Delaunay pierde 6 de
  sus 20 tramos), los vértices conservan bit a bit las coordenadas float64 de entrada (también
  a ±8 km del GeoOrigin; el triangulador recibe locales) y todos los triángulos tienen la
  normal hacia arriba, aunque el triangulador los dé al revés. Antes de triangular, los
  duplicados (A7, con su política) y las restricciones (A8: cruces, conflictos) de T16.
- **RF-006-15**: el contorno (la capa ``contorno`` de ``gpkg/capas.gpkg``: un polígono con un
  hueco y otro aparte), los huecos y la longitud máxima de lado quitan justo los triángulos con
  el centroide fuera del contorno o dentro de un hueco y los que tienen algún lado más largo
  (comparado con una comprobación propia sobre el TIN sin filtros); quedan los vértices usados
  y las aristas obligatorias que siguen siendo aristas.
- El informe (``TinReport``): triangulador, recuentos, duplicados fundidos, triángulos
  quitados, % de planos, lado máximo y degenerados (área < 10⁻⁶ m²).
- ``save_tin``/``load_tin``: el npz de ``meshes/`` con ``vertices``, ``faces``,
  ``constraint_edges``, ``vertex_source`` y el ``meta`` JSON del plan §5.2.2, leído con
  ``allow_pickle=False``; un fichero roto o que no es un TIN → ``gis.tin_file_invalid``.

Las entradas no se modifican (arrays de solo lectura).
"""

import json
import math
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import numpy as np

from tests.support.package import import_geoblender
from tests.support.repo import ROOT

gis = import_geoblender("gis")
tin_module = import_geoblender("gis.tin")
points = import_geoblender("gis.points")
cdt = import_geoblender("gis.cdt")
vector = import_geoblender("gis.vector")
georef = import_geoblender("core.georef")
csv_tables = import_geoblender("interop.csv_tables")
worker_api = import_geoblender("jobs.worker_api")

DATA = ROOT / "tests" / "data" / "gis"
TALUDES = DATA / "points" / "taludes.csv"
CAPAS = DATA / "gpkg" / "capas.gpkg"
ROLES = {"point_id": "P", "x": "X", "y": "Y", "z": "Z", "code": "Código", "line": "Línea"}
E0, N0 = 700_000.0, 4_400_000.0
ORIGIN = georef.GeoOrigin(700_000, 4_400_000, 0)
META = {"crs_epsg": 25830, "vertical": "EPSG:5782", "operation_uid": "op-0001"}
PLAN_META_KEYS = {"schema", "kind", "surface_type", "crs_epsg", "vertical", "closed",
                  "oriented", "triangulator", "flat_faces", "operation_uid"}


def _frozen(rows) -> np.ndarray:
    array = np.array(rows, dtype=np.float64).reshape(-1, 3)
    array.flags.writeable = False  # una entrada nunca se modifica
    return array


def _point_set(xyz) -> object:
    xyz = _frozen(xyz)
    count = len(xyz)
    return points.PointSet(xyz, tuple(f"P{i + 1}" for i in range(count)), ("",) * count,
                           tuple(range(2, count + 2)))


def _rel(*rows) -> list[tuple[float, float, float]]:
    """Filas (x, y, z) relativas a (E0, N0) → absolutas."""
    return [(E0 + x, N0 + y, z) for x, y, z in rows]


def _line(line_id: str, *vertices, hard: bool = True) -> object:
    return points.Breakline(line_id, _frozen(_rel(*vertices)), hard=hard)


def _taludes() -> tuple[object, list]:
    table = csv_tables.read_table(TALUDES, encoding="utf-8", separator=";")
    mapping = points.ColumnMapping.by_name(table.columns, **ROLES)
    point_set, lines, _report = points.points_from_rows(
        table.columns, table.rows, mapping, ",", row_numbers=table.lines)
    for array in (point_set.xyz, *(line.xyz for line in lines)):
        array.flags.writeable = False
    return point_set, lines


def _cloud(count: int = 160, seed: int = 18) -> object:
    """Nube al azar en x ∈ [0, 80], y ∈ [0, 40] (relativas) con sus cuatro esquinas; cota
    lineal con un término que no la deja plana."""
    rng = np.random.default_rng(seed)
    xy = np.vstack([[[0.0, 0.0], [80.0, 0.0], [80.0, 40.0], [0.0, 40.0]],
                    rng.uniform((0.0, 0.0), (80.0, 40.0), size=(count, 2))])
    z = 800.0 + 0.1 * xy[:, 0] + 0.05 * xy[:, 1] + np.sin(xy[:, 0])
    return _point_set(np.column_stack([E0 + xy[:, 0], N0 + xy[:, 1], z]))


def _build(point_set, lines=(), triangulator=None, **options):
    return gis.build_tin(point_set, list(lines),
                         triangulator=triangulator or cdt.PureTriangulator(), origin=ORIGIN,
                         **options)


def _key(row) -> tuple[float, ...]:
    return tuple(float(v) for v in row)


def _face_set(tin) -> set[frozenset]:
    """Los triángulos por las coordenadas de sus vértices (independiente de la numeración)."""
    return {frozenset(_key(tin.vertices[i]) for i in face) for face in tin.faces.tolist()}


def _edge_set(faces: np.ndarray) -> set[tuple[int, int]]:
    pairs = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    pairs.sort(axis=1)
    return set(map(tuple, pairs.tolist()))


def _index(tin) -> dict[tuple[float, ...], int]:
    return {_key(row): i for i, row in enumerate(tin.vertices)}


def _normal_z(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Componente Z de la normal (b − a) × (c − a) de cada triángulo, en float64 absoluto."""
    a, b, c = (vertices[faces[:, k]] for k in range(3))
    u, v = b - a, c - a
    return u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]


def _centroid_rel(tin) -> np.ndarray:
    xy = tin.vertices[tin.faces][:, :, :2].mean(axis=1)
    return xy - (E0, N0)


def _max_side(tin) -> np.ndarray:
    p = tin.vertices[tin.faces][:, :, :2]
    q = np.roll(p, -1, axis=1)
    return np.hypot(q[..., 0] - p[..., 0], q[..., 1] - p[..., 1]).max(axis=1)


def _ring(*xy, z: float | None = None) -> np.ndarray:
    """Anillo cerrado de vértices (x, y) relativos, en absolutas (2D o con una Z)."""
    rows = [(E0 + x, N0 + y) if z is None else (E0 + x, N0 + y, z) for x, y in xy]
    rows.append(rows[0])
    array = np.array(rows, dtype=np.float64)
    array.flags.writeable = False
    return array


def _rectangle(x0, y0, x1, y1, z=None) -> np.ndarray:
    return _ring((x0, y0), (x1, y0), (x1, y1), (x0, y1), z=z)


def _in_box(xy: np.ndarray, x0, y0, x1, y1) -> np.ndarray:
    return (xy[:, 0] > x0) & (xy[:, 0] < x1) & (xy[:, 1] > y0) & (xy[:, 1] < y1)


class _Recording:
    """Triangulador que guarda lo que recibe y delega en ``PureTriangulator``; con
    ``clockwise`` devuelve los triángulos al revés y con ``broken``, un índice fuera."""

    name = "recording@1"

    def __init__(self, *, clockwise: bool = False, broken: str = "") -> None:
        self.calls: list[tuple[np.ndarray, np.ndarray]] = []
        self.clockwise = clockwise
        self.broken = broken

    def triangulate(self, xy_local: np.ndarray, edges: np.ndarray) -> np.ndarray:
        self.calls.append((xy_local.copy(), edges.copy()))
        faces = cdt.PureTriangulator().triangulate(xy_local, edges)
        if self.clockwise:
            faces = np.ascontiguousarray(faces[:, [0, 2, 1]])
        if self.broken == "index":
            faces = faces.copy()
            faces[0, 0] = len(xy_local)
        elif self.broken == "dtype":
            faces = faces.astype(np.float64)
        return faces


class BuildTinTest(unittest.TestCase):
    """RF-006-13: Delaunay restringida con las roturas duras como aristas, vértices bit a
    bit y normales +Z; A7 y A8 antes de triangular."""

    def test_taludes_breaklines_are_edges(self) -> None:
        """Las cuatro roturas duras de ``taludes.csv`` son sucesiones de aristas del TIN;
        los 44 vértices bit a bit y en orden, todos con la normal hacia arriba."""
        point_set, lines = _taludes()
        tin, report = _build(point_set, lines, name="taludes")
        want = np.concatenate([point_set.xyz, *(line.xyz for line in lines)])
        self.assertEqual(tin.vertices.dtype, np.float64)
        self.assertEqual(tin.vertices.tobytes(), want.tobytes())
        self.assertEqual(tin.vertex_source.dtype, np.uint8)
        self.assertEqual(tin.vertex_source.tolist(), [0] * 20 + [1] * 24)
        self.assertEqual(tin.faces.dtype, np.int32)
        self.assertEqual(tin.constraint_edges.dtype, np.int32)
        edges = _edge_set(tin.faces)
        where = _index(tin)
        required = set()
        for line in lines:
            for p, q in zip(line.xyz[:-1], line.xyz[1:], strict=True):
                pair = tuple(sorted((where[_key(p)], where[_key(q)])))
                required.add(pair)
                self.assertIn(pair, edges, f"{line.line_id}: el tramo {pair} no es arista")
        self.assertEqual(set(map(tuple, tin.constraint_edges.tolist())), required)
        self.assertTrue((_normal_z(tin.vertices, tin.faces) > 0.0).all())
        # Sin restricciones, Delaunay cruza 6 de los 20 tramos: la prueba distingue.
        free = cdt.PureTriangulator().triangulate(
            tin.vertices[:, :2] - (E0, N0), np.empty((0, 2), dtype=np.int32))
        self.assertEqual(len(required - _edge_set(free)), 6)
        self.assertEqual(report.triangulator, "pure@1")
        self.assertEqual(tin.triangulator, "pure@1")
        self.assertEqual((report.input_points, report.vertices, report.triangles,
                          report.constraint_edges), (44, 44, 69, 20))
        self.assertEqual((report.duplicates_merged, report.removed_outside,
                          report.removed_long_edges, report.degenerate), (0, 0, 0, 0))
        self.assertEqual(report.flat_pct, 0.0)
        self.assertIsNone(report.flat_pct_before)
        self.assertEqual(report.max_edge_m, float(_max_side(tin).max()))
        self.assertEqual(report.max_edge_m, 20.0)

    def test_coordinates_kept_far_from_origin(self) -> None:
        """A ±8 km del GeoOrigin los vértices salen bit a bit; el triangulador recibe
        locales float64 (absolutas − origen) y las aristas en int32."""
        offsets = (-7999.123456789, 7999.987654321)
        rows = [(E0 + dx + 0.001 * k, N0 + dy - 0.0007 * k, 812.3456789 + k)
                for k, (dx, dy) in enumerate(
                    (x, y) for x in offsets for y in offsets)]
        rows.append((E0 + 13.000000001, N0 - 21.123456789, 799.5))
        point_set = _point_set(rows)
        line = points.Breakline("L", _frozen([(E0 - 5000.25, N0 - 5000.75, 805.0),
                                              (E0 + 5000.5, N0 + 4000.125, 815.0)]))
        recording = _Recording()
        tin, _report = _build(point_set, [line], triangulator=recording)
        want = np.concatenate([point_set.xyz, line.xyz])
        self.assertEqual(tin.vertices.tobytes(), want.tobytes())
        (xy_local, edges), = recording.calls
        self.assertEqual(xy_local.dtype, np.float64)
        self.assertEqual(xy_local.tobytes(), (want[:, :2] - (E0, N0)).tobytes())
        self.assertLess(float(np.abs(xy_local).max()), 8000.0)
        self.assertEqual(edges.dtype, np.int32)
        self.assertEqual(edges.tolist(), [[5, 6]])
        self.assertTrue((_normal_z(tin.vertices, tin.faces) > 0.0).all())
        self.assertEqual(tin.triangulator, "recording@1")

    def test_crossing_breaklines_meet_at_a_new_vertex(self) -> None:
        """Dos roturas que se cruzan con la misma cota: vértice nuevo (5; 5; 105) de origen
        1 y cada rotura sigue siendo una sucesión de aristas a través de él."""
        corners = _point_set(_rel((-5, -5, 100), (15, -5, 100), (15, 15, 110), (-5, 15, 110)))
        first = _line("A", (0, 0, 100), (10, 10, 110))
        second = _line("B", (0, 10, 110), (10, 0, 100))
        tin, report = _build(corners, [first, second])
        where = _index(tin)
        cross = where[(E0 + 5, N0 + 5, 105.0)]
        self.assertEqual(int(tin.vertex_source[cross]), 1)
        edges = _edge_set(tin.faces)
        constraints = set(map(tuple, tin.constraint_edges.tolist()))
        for end in ((0, 0, 100), (10, 10, 110), (0, 10, 110), (10, 0, 100)):
            pair = tuple(sorted((where[_rel(end)[0]], cross)))
            self.assertIn(pair, edges)
            self.assertIn(pair, constraints)
        self.assertEqual(len(constraints), 4)
        self.assertEqual((report.input_points, report.vertices), (8, 9))
        self.assertTrue((_normal_z(tin.vertices, tin.faces) > 0.0).all())

    def test_conflicts_stop_the_tin(self) -> None:
        """Un cruce con cotas distintas (RF-006-14) no deja crear el TIN."""
        corners = _point_set(_rel((-5, -5, 100), (15, -5, 100), (15, 15, 110), (-5, 15, 110)))
        first = _line("A", (0, 0, 100), (10, 10, 110))
        second = _line("B", (0, 10, 112), (10, 0, 100))
        recording = _Recording()
        with self.assertRaises(gis.ConflictError) as caught:
            _build(corners, [first, second], triangulator=recording, name="topo")
        self.assertEqual(caught.exception.code, "gis.constraint_conflicts")
        self.assertEqual(caught.exception.tin, "topo")
        self.assertEqual(recording.calls, [])

    def test_soft_breaklines_only_add_points(self) -> None:
        """Una rotura blanda aporta sus vértices (origen 2) y ninguna arista obligatoria."""
        corners = _point_set(_rel((0, 0, 100), (20, 0, 100), (20, 20, 101), (0, 20, 101)))
        soft = _line("S", (5, 5, 100.5), (15, 15, 100.7), hard=False)
        tin, report = _build(corners, [soft])
        self.assertEqual(tin.vertex_source.tolist(), [0, 0, 0, 0, 2, 2])
        self.assertEqual(tin.constraint_edges.shape, (0, 2))
        self.assertEqual(report.constraint_edges, 0)

    def test_breaklines_without_points(self) -> None:
        """Solo roturas (sin puntos): el TIN de sus vértices."""
        _point_set_unused, lines = _taludes()
        tin, report = _build(_point_set([]), lines)
        self.assertEqual(report.vertices, 24)
        self.assertEqual(report.constraint_edges, 20)
        self.assertEqual(tin.vertices.tobytes(),
                         np.concatenate([line.xyz for line in lines]).tobytes())

    def test_duplicate_policies(self) -> None:
        """A7 antes de triangular: a 0,5 mm con Δz 0,004 m se funden; con Δz 0,25 m,
        «preguntar» y «cancelar» paran y la media o la máxima resuelven (RF-006-14)."""
        base = [(0, 0, 100), (20, 0, 100), (20, 20, 101), (0, 20, 101), (5, 5, 100.0)]
        merged = _point_set(_rel(*base, (5.0005, 5, 100.004)))
        tin, report = _build(merged)
        self.assertEqual(report.duplicates_merged, 1)
        self.assertEqual((report.input_points, report.vertices), (6, 5))
        self.assertEqual(tin.vertices.tobytes(), merged.xyz[:5].tobytes())
        clash = _point_set(_rel(*base, (5.0005, 5, 100.25)))
        for policy, code in (("ask", "gis.duplicate_conflicts"),
                             (gis.DuplicatePolicy.CANCEL, "gis.duplicates_cancelled")):
            with self.subTest(policy=policy), self.assertRaises(gis.ConflictError) as caught:
                _build(clash, name="topo", duplicate_policy=policy)
            self.assertEqual(caught.exception.code, code)
        tin, report = _build(clash, duplicate_policy="mean")
        self.assertEqual(report.duplicates_merged, 1)
        self.assertEqual(_key(tin.vertices[4]), (E0 + 5, N0 + 5, 100.125))
        tin, _report = _build(clash, duplicate_policy=gis.DuplicatePolicy.MAX)
        self.assertEqual(tin.vertices[4].tobytes(), clash.xyz[5].tobytes())

    def test_orientation_and_contract(self) -> None:
        """Un triangulador que da los triángulos al revés sale antihorario (normal +Z); uno
        que da un índice que no existe o no da enteros → ``TriangulationError``."""
        point_set, lines = _taludes()
        reference, _report = _build(point_set, lines)
        tin, _report = _build(point_set, lines, triangulator=_Recording(clockwise=True))
        self.assertTrue((_normal_z(tin.vertices, tin.faces) > 0.0).all())
        self.assertEqual(_face_set(tin), _face_set(reference))
        for broken in ("index", "dtype"):
            with self.subTest(broken=broken), \
                    self.assertRaises(gis.TriangulationError) as caught:
                _build(point_set, lines, triangulator=_Recording(broken=broken))
            self.assertEqual(caught.exception.code, "gis.triangulation_contract")

    def test_statistics(self) -> None:
        """Planos (tres cotas iguales), lado máximo y degenerados (área < 10⁻⁶ m²): un
        triángulo de 5·10⁻⁷ m² en el borde de abajo, plano, de 3."""
        sliver = _point_set(_rel((0, 0, 800), (10, 0, 800), (5, 1e-7, 800), (5, 5, 801)))
        tin, report = _build(sliver)
        self.assertEqual(report.triangles, 3)
        self.assertEqual(report.degenerate, 1)
        self.assertAlmostEqual(report.flat_pct, 100.0 / 3.0, places=12)
        self.assertEqual(report.max_edge_m, 10.0)
        self.assertTrue((_normal_z(tin.vertices, tin.faces) > 0.0).all())

    def test_progress_and_cancel(self) -> None:
        """El avance crece hasta 1; al cancelar, ``JobCancelled`` sin triangular."""
        point_set, lines = _taludes()
        seen: list[float] = []
        _build(point_set, lines, progress=lambda fraction, _text: seen.append(fraction))
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(seen[-1], 1.0)
        recording = _Recording()
        seen.clear()
        with self.assertRaises(worker_api.JobCancelled):
            _build(point_set, lines, triangulator=recording, cancelled=lambda: True,
                   progress=lambda fraction, _text: seen.append(fraction))
        self.assertEqual(recording.calls, [])
        self.assertEqual(seen, [])  # se consulta antes de empezar

    def test_exact_orientation(self) -> None:
        """Un triángulo que el float64 no orienta (vértice a 10⁻¹³ m de la recta de un
        lado de 5,7 km) se orienta con el signo exacto de ``orient2d``."""
        xy = np.array([(-6000.0, -2000.0), (-2000.0, 2000.0), (-4000.0, 1e-13)])
        faces = np.array([[0, 2, 1], [0, 1, 2]], dtype=np.int64)
        self.assertEqual(tin_module._oriented(xy, faces).tolist(), [[0, 1, 2], [0, 1, 2]])

    def test_wrong_inputs(self) -> None:
        """Errores del programa: puntos que no son un ``PointSet`` o roturas que no son
        ``Breakline``."""
        point_set, lines = _taludes()
        with self.assertRaises(TypeError):
            _build(point_set.xyz, lines)
        with self.assertRaises(TypeError):
            _build(point_set, [lines[0].xyz])


class FilterTest(unittest.TestCase):
    """RF-006-15: contorno, huecos y longitud máxima de lado."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.cloud = _cloud()
        cls.full, cls.full_report = _build(cls.cloud)
        cls.centroids = _centroid_rel(cls.full)
        cls.sides = _max_side(cls.full)

    def _expect(self, tin, report, keep: np.ndarray, *, outside: int, long_edges: int) -> None:
        kept = {face for face, flag in zip(
            [frozenset(_key(self.full.vertices[i]) for i in f) for f in self.full.faces.tolist()],
            keep.tolist(), strict=True) if flag}
        self.assertEqual(_face_set(tin), kept)
        self.assertEqual((report.removed_outside, report.removed_long_edges),
                         (outside, long_edges))
        self.assertEqual(report.triangles, int(keep.sum()))
        used = np.unique(tin.faces)
        self.assertEqual(used.tolist(), list(range(len(tin.vertices))))  # sin sobrantes
        inputs = {_key(row) for row in self.cloud.xyz}
        self.assertTrue({_key(row) for row in tin.vertices} <= inputs)
        self.assertEqual(report.vertices, len(tin.vertices))
        self.assertTrue((_normal_z(tin.vertices, tin.faces) > 0.0).all())

    def test_boundary_layer_with_hole_and_island(self) -> None:
        """La capa ``contorno`` de ``capas.gpkg`` (MultiPolygon 2D: 60 × 40 m con un hueco
        de 10 × 5 m, y una isla de 10 × 10 m al este) quita los triángulos con el centroide
        fuera."""
        with tempfile.TemporaryDirectory(prefix="gb-t18-") as folder:
            copy = vector.copy_source(CAPAS, Path(folder))
            features = vector.read_layer(copy, "contorno")
        geometry, = features.geometries
        c = self.centroids
        inside = ((_in_box(c, 0, 0, 60, 40) & ~_in_box(c, 25, 2, 35, 7))
                  | _in_box(c, 65, 0, 75, 10))
        tin, report = _build(self.cloud, boundary=geometry.coords)
        self._expect(tin, report, inside, outside=int((~inside).sum()), long_edges=0)
        self.assertGreater(int((~inside).sum()), 50)
        same, _report = _build(self.cloud, boundary=geometry)  # también la geometría
        self.assertEqual(_face_set(same), _face_set(tin))

    def test_holes(self) -> None:
        """Cada hueco es una región (sus anillos, por paridad); varios huecos se suman. Un
        anillo con Z sirve igual."""
        c = self.centroids
        hole_a = _rectangle(10, 10, 30, 30, z=815.0)
        hole_b = _rectangle(20, 5, 50, 15)
        inner = _rectangle(15, 15, 25, 25)
        tin, report = _build(self.cloud, holes=[hole_a, hole_b])
        out = _in_box(c, 10, 10, 30, 30) | _in_box(c, 20, 5, 50, 15)
        self._expect(tin, report, ~out, outside=int(out.sum()), long_edges=0)
        tin, report = _build(self.cloud, holes=[[hole_a, inner]])
        out = _in_box(c, 10, 10, 30, 30) & ~_in_box(c, 15, 15, 25, 25)
        self._expect(tin, report, ~out, outside=int(out.sum()), long_edges=0)
        tin, report = _build(self.cloud, holes=hole_b)
        out = _in_box(c, 20, 5, 50, 15)
        self._expect(tin, report, ~out, outside=int(out.sum()), long_edges=0)

    def test_ring_blocks(self) -> None:
        """La paridad por bloques (como mucho ``_PAIR_BUDGET`` parejas lado–centroide)
        da lo mismo que en un bloque."""
        region = [_rectangle(0, 0, 60, 40), _rectangle(25, 2, 35, 7)]
        whole, _report = _build(self.cloud, boundary=region, holes=[_rectangle(5, 5, 9, 30)])
        with mock.patch.object(tin_module, "_PAIR_BUDGET", 3):
            blocks, _report = _build(self.cloud, boundary=region,
                                     holes=[_rectangle(5, 5, 9, 30)])
        self.assertEqual(_face_set(blocks), _face_set(whole))
        self.assertLess(len(whole.faces), len(self.full.faces))

    def test_max_edge(self) -> None:
        """Los triángulos con algún lado (en planta) más largo que el máximo se quitan; con
        contorno, se cuentan solo los que quedaban dentro."""
        limit = 6.0
        long_sides = self.sides > limit
        self.assertGreater(int(long_sides.sum()), 10)
        tin, report = _build(self.cloud, max_edge_m=limit)
        self._expect(tin, report, ~long_sides, outside=0, long_edges=int(long_sides.sum()))
        self.assertLessEqual(float(_max_side(tin).max()), limit)
        self.assertEqual(report.max_edge_m, float(_max_side(tin).max()))
        boundary = _rectangle(0, 0, 40, 40)
        inside = _in_box(self.centroids, 0, 0, 40, 40)
        tin, report = _build(self.cloud, boundary=boundary, max_edge_m=limit)
        self._expect(tin, report, inside & ~long_sides, outside=int((~inside).sum()),
                     long_edges=int((inside & long_sides).sum()))

    def test_constraint_edges_after_filters(self) -> None:
        """Con contorno, quedan las aristas obligatorias que siguen siendo aristas."""
        point_set, lines = _taludes()
        tin, report = _build(point_set, lines, boundary=_rectangle(0, 0, 30, 40))
        edges = _edge_set(tin.faces)
        where = _index(tin)
        expected = set()
        for line in lines:
            for p, q in zip(line.xyz[:-1], line.xyz[1:], strict=True):
                if _key(p) in where and _key(q) in where:
                    pair = tuple(sorted((where[_key(p)], where[_key(q)])))
                    if pair in edges:
                        expected.add(pair)
        self.assertEqual(set(map(tuple, tin.constraint_edges.tolist())), expected)
        self.assertEqual(report.constraint_edges, len(expected))
        # Los dos primeros tramos de cada rotura y el tercero (x de 24 a 36,5) de C1 y C2,
        # con un triángulo al lado de centroide x < 30; los de P1 y P2 no lo tienen.
        self.assertEqual(len(expected), 10)
        sources = {_key(row): int(s) for row, s in zip(tin.vertices, tin.vertex_source,
                                                       strict=True)}
        for line in lines:
            for row in line.xyz:
                if _key(row) in sources:
                    self.assertEqual(sources[_key(row)], 1)

    def test_nothing_left(self) -> None:
        """Si los filtros lo quitan todo, ``gis.tin_empty`` y no hay TIN."""
        with self.assertRaises(gis.GisError) as caught:
            _build(self.cloud, boundary=_rectangle(200, 200, 300, 300), name="topo")
        self.assertEqual(caught.exception.code, "gis.tin_empty")
        self.assertIn("topo", str(caught.exception))
        with self.assertRaises(gis.GisError) as caught:
            _build(self.cloud, max_edge_m=0.01)
        self.assertEqual(caught.exception.code, "gis.tin_empty")

    def test_invalid_filters(self) -> None:
        """Lado máximo no positivo o no finito → ``gis.tin_max_edge_invalid``; anillos que
        no son float64 ``(k ≥ 3, 2|3)`` finitos → errores del programa."""
        for value in (0.0, -1.0, math.nan, math.inf):
            with self.subTest(value=value), self.assertRaises(gis.GisError) as caught:
                _build(self.cloud, max_edge_m=value)
            self.assertEqual(caught.exception.code, "gis.tin_max_edge_invalid")
        for value in ("5", True):
            with self.subTest(value=value), self.assertRaises(TypeError):
                _build(self.cloud, max_edge_m=value)
        ring = _rectangle(0, 0, 40, 40)
        bad = (ring.astype(np.float32), ring[:2], np.full((4, 2), np.nan), ring.ravel(), [])
        for boundary in bad:
            with self.subTest(boundary=boundary), self.assertRaises((TypeError, ValueError)):
                _build(self.cloud, boundary=boundary)
        with self.assertRaises((TypeError, ValueError)):
            _build(self.cloud, holes=["anillo"])


class TinFileTest(unittest.TestCase):
    """El npz de ``meshes/`` (plan §5.2.2; ``formato-proyecto.md`` §4.3; ARQ-16)."""

    @classmethod
    def setUpClass(cls) -> None:
        point_set, lines = _taludes()
        cls.tin, cls.report = _build(point_set, lines)

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory(prefix="gb-t18-")
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def test_save_and_load(self) -> None:
        """Arrays y ``meta`` del plan, leídos con ``allow_pickle=False``; ida y vuelta bit
        a bit y sin temporales."""
        path = self.folder / "gis_tin_taludes.npz"
        gis.save_tin(self.tin, path, META)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), [path.name])
        with np.load(path, allow_pickle=False) as data:
            self.assertEqual(set(data.files), {"vertices", "faces", "constraint_edges",
                                               "vertex_source", "meta"})
            for name, dtype, shape in (("vertices", np.float64, (44, 3)),
                                       ("faces", np.int32, (69, 3)),
                                       ("constraint_edges", np.int32, (20, 2)),
                                       ("vertex_source", np.uint8, (44,))):
                self.assertEqual(data[name].dtype, dtype)
                self.assertEqual(data[name].shape, shape)
                self.assertEqual(data[name].tobytes(), getattr(self.tin, name).tobytes())
            self.assertEqual(data["meta"].shape, ())
            self.assertEqual(data["meta"].dtype.kind, "U")
            meta = json.loads(str(data["meta"]))
        with zipfile.ZipFile(path) as archive:
            self.assertTrue(all(i.compress_type == zipfile.ZIP_DEFLATED
                                for i in archive.infolist()))
        self.assertEqual(set(meta), PLAN_META_KEYS)
        self.assertEqual(meta, {"schema": 1, "kind": "surface", "surface_type": "tin",
                                "crs_epsg": 25830, "vertical": "EPSG:5782", "closed": False,
                                "oriented": True, "triangulator": "pure@1", "flat_faces": 0,
                                "operation_uid": "op-0001"})
        loaded = gis.load_tin(path)
        for name in ("vertices", "faces", "constraint_edges", "vertex_source"):
            self.assertEqual(getattr(loaded, name).dtype, getattr(self.tin, name).dtype)
            self.assertEqual(getattr(loaded, name).tobytes(),
                             getattr(self.tin, name).tobytes())
        self.assertEqual(loaded.triangulator, "pure@1")
        self.assertEqual(dict(loaded.meta), meta)
        gis.save_tin(loaded, path, {**META, "operation_uid": "op-0002", "nota": "otra"})
        again = gis.load_tin(path)
        self.assertEqual(again.meta["operation_uid"], "op-0002")
        self.assertEqual(again.meta["nota"], "otra")
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), [path.name])

    def test_failed_write_keeps_previous(self) -> None:
        """Si la escritura falla a mitad, el fichero anterior queda intacto y no queda el
        temporal."""
        path = self.folder / "gis_tin_taludes.npz"
        gis.save_tin(self.tin, path, META)
        before = path.read_bytes()

        def broken(stream, **_arrays) -> None:
            stream.write(b"PK\x03\x04 a medias")
            raise OSError("disco lleno")

        with mock.patch.object(np, "savez_compressed", broken), self.assertRaises(OSError):
            gis.save_tin(self.tin, path, {**META, "operation_uid": "op-0002"})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), [path.name])

    def test_flat_faces_counted(self) -> None:
        """``flat_faces`` cuenta los triángulos con sus tres cotas iguales."""
        sliver = _point_set(_rel((0, 0, 800), (10, 0, 800), (5, 1e-7, 800), (5, 5, 801)))
        tin, _report = _build(sliver)
        path = self.folder / "plano.npz"
        gis.save_tin(tin, path, META)
        self.assertEqual(gis.load_tin(path).meta["flat_faces"], 1)

    def test_meta_rejected(self) -> None:
        """Al guardar: faltan claves, contradicen las calculadas o no son JSON →
        ``ValueError`` y ningún fichero."""
        path = self.folder / "malo.npz"
        cases = [{k: v for k, v in META.items() if k != key} for key in META]
        cases += [{**META, "crs_epsg": "25830"}, {**META, "crs_epsg": True},
                  {**META, "vertical": ""}, {**META, "surface_type": "grid"},
                  {**META, "triangulator": "otro@1"}, {**META, "flat_faces": 3},
                  {**META, "nota": math.nan}, {**META, "nota": object()}]
        for meta in cases:
            with self.subTest(meta=meta), self.assertRaises(ValueError):
                gis.save_tin(self.tin, path, meta)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_optional_arrays(self) -> None:
        """Sin ``constraint_edges`` ni ``vertex_source`` (opcionales en ``meshes/``): sin
        aristas obligatorias y todos de origen «punto»."""
        path = self.folder / "minimo.npz"
        meta = {**META, "schema": 1, "kind": "surface", "surface_type": "tin"}
        np.savez_compressed(path, vertices=self.tin.vertices, faces=self.tin.faces,
                            meta=np.array(json.dumps(meta)))
        loaded = gis.load_tin(path)
        self.assertEqual(loaded.constraint_edges.shape, (0, 2))
        self.assertEqual(loaded.constraint_edges.dtype, np.int32)
        self.assertEqual(loaded.vertex_source.tolist(), [0] * 44)
        self.assertEqual(loaded.triangulator, "")

    def test_broken_files(self) -> None:
        """Ficheros que no son un TIN → ``gis.tin_file_invalid`` con el fichero; un array
        de objetos no se lee (``allow_pickle=False``)."""
        tin = self.tin
        good_meta = np.array(json.dumps({**META, "schema": 1, "kind": "surface",
                                         "surface_type": "tin"}))
        arrays = {"vertices": tin.vertices, "faces": tin.faces, "meta": good_meta}
        bad_faces = tin.faces.copy()
        bad_faces[0, 0] = 44
        cases = {
            "objetos": {**arrays, "faces": np.array([None, 1], dtype=object)},
            "sin_caras": {k: v for k, v in arrays.items() if k != "faces"},
            "sin_meta": {k: v for k, v in arrays.items() if k != "meta"},
            "meta_no_json": {**arrays, "meta": np.array("{no")},
            "meta_lista": {**arrays, "meta": np.array("[1]")},
            "meta_numero": {**arrays, "meta": np.array(1.0)},
            "otra_superficie": {**arrays, "meta": np.array(json.dumps(
                {**META, "schema": 1, "kind": "surface", "surface_type": "grid"}))},
            "solido": {**arrays, "meta": np.array(json.dumps(
                {**META, "schema": 1, "kind": "solid", "surface_type": "tin"}))},
            "esquema_2": {**arrays, "meta": np.array(json.dumps(
                {**META, "schema": 2, "kind": "surface", "surface_type": "tin"}))},
            "indice_fuera": {**arrays, "faces": bad_faces},
            "caras_float": {**arrays, "faces": tin.faces.astype(np.float64)},
            "vertices_f32": {**arrays, "vertices": tin.vertices.astype(np.float32)},
        }
        for name, content in cases.items():
            path = self.folder / f"{name}.npz"
            if name == "objetos":
                np.savez(path, **content)  # np.savez guarda los objetos con pickle
            else:
                np.savez_compressed(path, **content)
            with self.subTest(name), self.assertRaises(gis.GisError) as caught:
                gis.load_tin(path)
            self.assertEqual(caught.exception.code, "gis.tin_file_invalid")
            self.assertIn(path.name, str(caught.exception))
        text = self.folder / "texto.npz"
        text.write_bytes(b"no es un npz")
        npy = self.folder / "array.npz"
        with npy.open("wb") as stream:
            np.save(stream, tin.vertices)
        for path in (text, npy, self.folder / "no_existe.npz"):
            with self.subTest(path.name), self.assertRaises(gis.GisError) as caught:
                gis.load_tin(path)
            self.assertEqual(caught.exception.code, "gis.tin_file_invalid")


class TinTypeTest(unittest.TestCase):
    """``Tin``: tipos y formas del plan §5.2.2 (errores del programa)."""

    def test_checks(self) -> None:
        vertices = np.array([[0.0, 0.0, 1.0], [1.0, 0.0, 1.0], [0.0, 1.0, 1.0]])
        faces = np.array([[0, 1, 2]], dtype=np.int32)
        edges = np.array([[0, 1]], dtype=np.int32)
        source = np.zeros(3, dtype=np.uint8)
        tin = tin_module.Tin(vertices, faces, edges, source)
        self.assertEqual(tin.triangulator, "")
        self.assertEqual(dict(tin.meta), {})
        with self.assertRaises(TypeError):
            tin.meta["x"] = 1  # type: ignore[index]
        wrong = (
            (TypeError, (vertices.astype(np.float32), faces, edges, source)),
            (TypeError, (vertices, faces.astype(np.int64), edges, source)),
            (TypeError, (vertices, faces, edges.astype(np.int64), source)),
            (TypeError, (vertices, faces, edges, source.astype(np.int32))),
            (ValueError, (vertices[:, :2].copy(), faces, edges, source)),
            (ValueError, (vertices, faces[:0], edges, source)),
            (ValueError, (vertices, faces + 1, edges, source)),
            (ValueError, (vertices, -faces - 1, edges, source)),
            (ValueError, (vertices, faces, edges + 2, source)),
            (ValueError, (vertices, faces, edges, source[:2])),
            (ValueError, (np.where(vertices == 1.0, np.nan, vertices), faces, edges, source)),
        )
        for error, args in wrong:
            with self.subTest(args=args), self.assertRaises(error):
                tin_module.Tin(*args)

    def test_package_reexports(self) -> None:
        for name in ("Tin", "build_tin", "save_tin", "load_tin"):
            with self.subTest(name=name):
                self.assertIn(name, gis.__all__)
                self.assertIs(getattr(gis, name), getattr(tin_module, name))


if __name__ == "__main__":
    unittest.main()
