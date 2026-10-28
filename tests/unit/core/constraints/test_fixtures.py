# SPDX-License-Identifier: GPL-3.0-or-later
"""Datos de referencia de los límites y las restricciones (spec 012, T02; plan 012 §7.1 y §2.2).

Comprueba ``tests.support.constraints_fixtures`` antes de que lo use el núcleo, **sin el código
de la 012**: los recuentos a mano y las áreas exactas de los casos, con una fuerza bruta propia
(cada celda × cada segmento, la distancia exacta caja–segmento, con la regla de D-1: en la zona si
la distancia es < r − τ; dentro de un límite, si la celda está entera dentro).

- **CE-012-01** (RF-012-12): el cuadrado de 100 m alineado y desplazado media celda con 8 m, el
  punto en una esquina y en un centro con 8 m, la línea con 8 m y el límite con 10 m hacia dentro,
  con 1 y 2 m: 13.424, 13.641, 224, 241, 1.824 y 6.400 celdas con 1 m; 3.360, 3.469, 60, 69, 460 y
  1.600 con 2 m; y el área de los polígonos, 10.000 m² exactos.
- **CE-012-02** (RF-012-21, RF-012-22, RF-012-23): la torre con 8 m (60 celdas de 4 m²) y una
  superficie que rebaja 26,6 m su entorno: 60 · 4 · 26,6 m³ de corte en la zona, en un grupo
  centrado en la torre; la que la respeta, 0 m³.
- **CE-012-03 y CE-012-04** (RF-012-05, RF-012-06): el límite legal de 4 ha, el perímetro de
  3,44 ha con 0,68 ha fuera del límite en una parte, y su redibujo con +1,43 ha.
- **CE-012-06** (RF-012-22, RF-012-23): la balsa sin relleno con 4.300 m³ de relleno.
- **El GeoPackage de las fuentes** (RF-012-01, RF-012-07, RF-012-08, RF-012-26): los once tipos
  con sus campos en español, la torre a 6 m del sector 2 y la línea eléctrica a 15 m del sector 1,
  dos sectores sin solapes que dejan 12.000 m² del perímetro sin cubrir, y las seis marcas del
  cliente con su rol; se lee con el lector de capas de la 006.

Ningún dato de cliente: todo es sintético.
"""

import math
import re
import tempfile
import unittest
from pathlib import Path

import numpy as np

from tests.support import constraints_fixtures as fx
from tests.support.package import import_geoblender

vector = import_geoblender("gis.vector")

TAU = 1e-9  # D-1, D-37 (m)
EXACT = 1e-9  # error relativo de áreas y volúmenes (RF-012-05, RF-012-21)
PLAN_COUNTS = {  # plan 012 §2.2, y la línea de esta tarea
    1.0: {"square": 13_424, "square_shifted": 13_641, "point_corner": 224,
          "point_center": 241, "line": 1_824, "limit": 6_400},
    2.0: {"square": 3_360, "square_shifted": 3_469, "point_corner": 60,
          "point_center": 69, "line": 460, "limit": 1_600},
}
CTYPES = ("legal_limit", "action_perimeter", "untouchable", "no_cut", "no_fill",
          "restoration_only", "fill_only", "avoid", "exclusion", "requires_access", "setback")
ROLES = ("protect", "fill", "mine_to_elevation", "keep_as_is", "platform", "slope_to_treat")


# Fuerza bruta propia --------------------------------------------------------------------------


def _boxes(grid) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Izquierda, abajo, derecha y arriba de cada celda, LOCALES (desde ``fx.BASE``)."""
    left = (grid.west - fx.BASE[0]) + np.arange(grid.ncols) * grid.dx
    top = (grid.north - fx.BASE[1]) - np.arange(grid.nrows) * grid.dy
    left, top = np.meshgrid(left, top)
    return left, top - grid.dy, left + grid.dx, top


def _local(points) -> np.ndarray:
    return np.asarray(points, dtype=np.float64).reshape(-1, 2) - np.asarray(fx.BASE)


def _point_box(px, py, left, bottom, right, top) -> np.ndarray:
    gap_x = np.maximum(np.maximum(left - px, px - right), 0.0)
    gap_y = np.maximum(np.maximum(bottom - py, py - top), 0.0)
    return np.hypot(gap_x, gap_y)


def _point_segment(cx, cy, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    d = b - a
    length2 = float(d @ d)
    if length2 == 0.0:
        return np.hypot(cx - a[0], cy - a[1])
    t = np.clip(((cx - a[0]) * d[0] + (cy - a[1]) * d[1]) / length2, 0.0, 1.0)
    return np.hypot(cx - (a[0] + t * d[0]), cy - (a[1] + t * d[1]))


def segment_box_distance(a, b, left, bottom, right, top) -> np.ndarray:
    """Distancia exacta del segmento ``ab`` (local) a cada caja: 0 si se tocan (recorte de
    Liang–Barsky); si no, el mínimo de extremo–caja y esquina–segmento."""
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    d = b - a
    shape = np.broadcast(left, bottom, right, top).shape
    enter, leave, ok = np.zeros(shape), np.ones(shape), np.ones(shape, dtype=bool)
    for p, q in ((-d[0], a[0] - left), (d[0], right - a[0]),
                 (-d[1], a[1] - bottom), (d[1], top - a[1])):
        q = np.broadcast_to(q, shape)
        if p == 0.0:
            ok &= q >= 0.0
        elif p < 0.0:
            enter = np.maximum(enter, q / p)
        else:
            leave = np.minimum(leave, q / p)
    hit = ok & (enter <= leave)
    distance = np.minimum(_point_box(a[0], a[1], left, bottom, right, top),
                          _point_box(b[0], b[1], left, bottom, right, top))
    for cx, cy in ((left, bottom), (right, bottom), (right, top), (left, top)):
        distance = np.minimum(distance, _point_segment(cx, cy, a, b))
    return np.where(hit, 0.0, distance)


def _segments(kind: str, coords) -> list[tuple[np.ndarray, np.ndarray]]:
    if kind == "POINT":
        point = _local(coords)[0]
        return [(point, point)]
    if kind == "LINESTRING":
        line = _local(coords)
        return list(zip(line[:-1], line[1:], strict=True))
    return [pair for ring in coords
            for pair in zip(_local(ring)[:-1], _local(ring)[1:], strict=True)]


def _rect(ring) -> tuple[float, float, float, float]:
    local = _local(ring)
    assert len(local) == 5 and np.array_equal(local[0], local[-1])
    xs, ys = sorted(set(local[:, 0])), sorted(set(local[:, 1]))
    assert len(xs) == 2 and len(ys) == 2, "la fuerza bruta solo mide rectángulos"
    return xs[0], ys[0], xs[1], ys[1]


def _overlap(rect, left, bottom, right, top) -> np.ndarray:
    r_left, r_bottom, r_right, r_top = rect
    width = np.clip(np.minimum(right, r_right) - np.maximum(left, r_left), 0.0, None)
    height = np.clip(np.minimum(top, r_top) - np.maximum(bottom, r_bottom), 0.0, None)
    return width * height


def _min_distance(kind, coords, boxes) -> np.ndarray:
    distance = np.full(boxes[0].shape, np.inf)
    for a, b in _segments(kind, coords):
        distance = np.minimum(distance, segment_box_distance(a, b, *boxes))
    return distance


def brute_zone(grid, kind: str, coords, outward_m: float) -> np.ndarray:
    """La zona por la regla de D-1, celda a celda."""
    boxes = _boxes(grid)
    near = _min_distance(kind, coords, boxes) < outward_m - TAU
    if kind != "POLYGON":
        return near
    (ring,) = coords
    inside = _overlap(_rect(ring), *boxes) > 0.0
    return inside | near if outward_m > 0.0 else inside


def brute_limit(grid, coords, inward_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Las celdas enteras dentro del límite y las de su banda hacia dentro."""
    boxes = _boxes(grid)
    (ring,) = coords
    inside = _overlap(_rect(ring), *boxes) == grid.dx * grid.dy
    band = inside & (_min_distance("POLYGON", coords, boxes) < inward_m - TAU)
    return inside, band


def shoelace(ring) -> float:
    local = _local(ring)
    return float(np.sum(local[:-1, 0] * local[1:, 1] - local[1:, 0] * local[:-1, 1]) / 2.0)


def even_odd(ring, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Los puntos locales (x, y) dentro del anillo, por la regla par-impar (nunca en su borde)."""
    local = _local(ring)
    inside = np.zeros(x.shape, dtype=bool)
    for (ax, ay), (bx, by) in zip(local[:-1], local[1:], strict=True):
        if ay == by:
            continue
        crosses = (ay > y) != (by > y)
        at = ax + (y - ay) * (bx - ax) / (by - ay)
        inside ^= crosses & (x < at)
    return inside


def _site_centers() -> tuple[np.ndarray, np.ndarray]:
    left, bottom, right, top = _boxes(fx.SITE_GRID)
    return (left + right) / 2.0, (bottom + top) / 2.0


# Pruebas --------------------------------------------------------------------------------------


class MaskCasesTest(unittest.TestCase):
    """CE-012-01 (RF-012-12): recuentos a mano y áreas exactas."""

    def test_hand_counts_are_the_plan_ones(self) -> None:
        self.assertEqual({step: dict(counts) for step, counts in fx.HAND_COUNTS.items()},
                         PLAN_COUNTS)
        for step in fx.MASK_STEPS:
            self.assertEqual({case.key: case.cells for case in fx.mask_cases(step)},
                             PLAN_COUNTS[step])

    def test_square_count_by_its_formula(self) -> None:
        # n² + 4·n·k + 4·q: lado, banda de 8 m y las esquinas con (i² + j²)·paso² < 64.
        for step, expected in ((1.0, 13_424), (2.0, 3_360)):
            n, k = round(100 / step), round(8 / step)
            corner = sum(1 for i in range(k) for j in range(k)
                         if (i * i + j * j) * step * step < 64.0)
            self.assertEqual(n * n + 4 * n * k + 4 * corner, expected)

    def test_brute_force_gives_the_hand_counts(self) -> None:
        for step in fx.MASK_STEPS:
            for case in fx.mask_cases(step):
                with self.subTest(step=step, case=case.key):
                    if case.is_limit:
                        inside, band = brute_limit(case.grid, case.coords, case.inward_m)
                        self.assertEqual(int(inside.sum()), case.inside_cells)
                        self.assertEqual(int(band.sum()), case.band_cells)
                        self.assertEqual(int((inside & ~band).sum()), case.cells)
                    else:
                        zone = brute_zone(case.grid, case.geometry_type, case.coords,
                                          case.outward_m)
                        self.assertEqual(int(zone.sum()), case.cells)

    def test_polygon_areas_are_exact(self) -> None:
        for step in fx.MASK_STEPS:
            for case in fx.mask_cases(step):
                if case.geometry_type == "POLYGON":
                    with self.subTest(step=step, case=case.key):
                        self.assertEqual(shoelace(case.coords[0]), 10_000.0)
                        self.assertEqual(case.area_m2, 10_000.0)
                        self.assertEqual(fx.ring_area(case.coords[0]), 10_000.0)

    def test_coordinates_are_absolute_float64(self) -> None:
        for case in fx.mask_cases(1.0):
            values = case.coords[0] if case.geometry_type == "POLYGON" else case.coords
            self.assertEqual(values.dtype, np.float64)
            self.assertGreater(float(np.min(values[..., 1])), 4_000_000.0)


class LimitsTest(unittest.TestCase):
    """CE-012-03 y CE-012-04 (RF-012-05, RF-012-06): áreas exactas, partes y lo ganado."""

    def setUp(self) -> None:
        self.case = fx.limits()

    def test_areas_by_the_polygon_formula(self) -> None:
        case = self.case
        self.assertEqual(shoelace(case.legal_limit), case.legal_area_m2)
        self.assertEqual(case.legal_area_m2, 40_000.0)
        self.assertEqual(shoelace(case.perimeter), case.perimeter_area_m2)
        self.assertEqual(case.perimeter_area_m2, 34_400.0)
        self.assertEqual(shoelace(case.redrawn_perimeter), case.redrawn_area_m2)
        self.assertEqual(case.strip_m2, 6_800.0)  # 0,68 ha
        self.assertEqual(case.gained_m2, 14_300.0)  # 1,43 ha
        self.assertEqual(case.perimeter_area_m2, case.intersection_m2 + case.strip_m2)
        self.assertEqual(case.redrawn_area_m2,
                         case.perimeter_area_m2 + case.gained_m2 - case.lost_m2)
        for parts, total in ((case.strip_parts, case.strip_m2),
                             (case.redrawn_strip_parts, case.redrawn_strip_m2)):
            self.assertEqual(sum(part.area_m2 for part in parts), total)
            for part in parts:
                self.assertEqual(shoelace(part.ring), part.area_m2)

    def test_cells_reproduce_the_areas(self) -> None:
        case, cell = self.case, fx.SITE_GRID.cell_area
        x, y = _site_centers()
        legal = even_odd(case.legal_limit, x, y)
        perimeter = even_odd(case.perimeter, x, y)
        redrawn = even_odd(case.redrawn_perimeter, x, y)
        self.assertEqual(legal.sum() * cell, case.legal_area_m2)
        self.assertEqual((perimeter & legal).sum() * cell, case.intersection_m2)
        self.assertEqual((perimeter & ~legal).sum() * cell, case.strip_m2)
        self.assertEqual((redrawn & ~perimeter).sum() * cell, case.gained_m2)
        self.assertEqual((perimeter & ~redrawn).sum() * cell, case.lost_m2)
        self.assertEqual((redrawn & ~legal).sum() * cell, case.redrawn_strip_m2)
        for part in case.redrawn_strip_parts:
            cells = even_odd(part.ring, x, y)
            self.assertFalse(np.any(cells & legal))
            self.assertTrue(np.all(redrawn[cells]))
            self.assertEqual(cells.sum() * cell, part.area_m2)
            center = (fx.BASE[0] + float(x[cells].mean()), fx.BASE[1] + float(y[cells].mean()))
            self.assertEqual(center, part.center)


class SurfacesTest(unittest.TestCase):
    """CE-012-02, CE-012-03 y CE-012-06 (RF-012-21 a RF-012-23): lo que mueve cada final en su
    zona, sumado celda a celda."""

    def _check(self, case: fx.ComplianceCase) -> None:
        grid = fx.SITE_GRID
        self.assertIs(case.start.grid, grid)
        self.assertEqual(case.final.values.dtype, np.float64)
        zone = brute_zone(grid, case.zone_type, case.zone_coords, case.zone_outward_m)
        self.assertEqual(int(zone.sum()), case.zone_cells)
        depth = case.start.values - case.final.values
        cut = float(np.sum(np.where(zone & (depth > 0), depth, 0.0)) * grid.cell_area)
        fill = float(np.sum(np.where(zone & (depth < 0), -depth, 0.0)) * grid.cell_area)
        self.assertAlmostEqual(cut, case.cut_m3, delta=EXACT * max(case.cut_m3, 1.0))
        self.assertAlmostEqual(fill, case.fill_m3, delta=EXACT * max(case.fill_m3, 1.0))
        moved = zone & (depth != 0.0)
        if case.group_cells is None:
            return
        self.assertEqual(int(moved.sum()), case.group_cells)
        self.assertEqual(moved.sum() * grid.cell_area, case.group_area_m2)
        volume = float(np.abs(depth[moved]).sum() * grid.cell_area)
        self.assertAlmostEqual(volume, case.group_volume_m3, delta=EXACT * volume)
        self.assertAlmostEqual(float(np.abs(depth[moved]).max()), case.group_max_m,
                               delta=EXACT * case.group_max_m)
        x, y = _site_centers()
        center = (fx.BASE[0] + float(x[moved].mean()), fx.BASE[1] + float(y[moved].mean()))
        self.assertEqual(center, case.group_center)

    def test_tower(self) -> None:
        case = fx.tower_case()
        self.assertAlmostEqual(case.cut_m3, 60 * 4 * 26.6, delta=EXACT * 6_384.0)
        self._check(case)

    def test_tower_respected(self) -> None:
        case = fx.tower_case(respectful=True)
        self.assertEqual(case.cut_m3, 0.0)
        self._check(case)
        moved = case.start.values != case.final.values
        self.assertEqual(int(moved.sum()), 196 - 64)  # corta fuera de la zona

    def test_pond(self) -> None:
        case = fx.pond_case()
        self.assertEqual(case.fill_m3, 4_300.0)
        self._check(case)

    def test_strip(self) -> None:
        for fill in (False, True):
            with self.subTest(fill=fill):
                case = fx.strip_case(fill=fill)
                self.assertEqual(case.cut_m3 + case.fill_m3, 4_800.0)
                self._check(case)


class SourcesTest(unittest.TestCase):
    """El GeoPackage de las fuentes (RF-012-01, 07, 08 y 26), leído con el lector de la 006."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="gb-cf-")
        folder = Path(cls.tmp.name)
        cls.path = fx.write_sources(folder)
        copies = folder / "copias"
        copies.mkdir()
        cls.copy = vector.copy_source(cls.path, copies)
        cls.layers = {info.name: info for info in vector.list_layers(cls.copy)}
        cls.read = {name: vector.read_layer(cls.copy, name) for name in cls.layers}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_written_in_fuentes_once(self) -> None:
        self.assertEqual(self.path.parent.name, "fuentes")
        with self.assertRaises(FileExistsError):
            fx.write_sources(self.path.parent.parent)

    def test_layers_read_as_written(self) -> None:
        expected = fx.source_features()
        self.assertEqual(set(self.layers), set(expected))
        for name, features in expected.items():
            with self.subTest(layer=name):
                info, read = self.layers[name], self.read[name]
                self.assertTrue(info.importable, info.problem)
                self.assertEqual(info.srs, "EPSG:25830")
                self.assertEqual(info.geometry_type, fx.LAYER_SPECS[name][0])
                self.assertEqual(read.report.rejected, ())
                self.assertEqual(read.fids, tuple(f.fid for f in features))
                for index, feature in enumerate(features):
                    geometry = read.geometries[index]
                    self.assertEqual(geometry.geometry_type, feature.geometry_type)
                    if feature.geometry_type == "POLYGON":
                        for got, ring in zip(geometry.coords, feature.coords, strict=True):
                            np.testing.assert_array_equal(got, ring)
                    else:
                        np.testing.assert_array_equal(geometry.coords, feature.coords)
                    for field, value in feature.attributes.items():
                        self.assertEqual(read.attributes[field][index], value)

    def test_the_eleven_types_in_spanish(self) -> None:
        self.assertEqual(tuple(sorted(fx.CONSTRAINT_TYPES)), tuple(sorted(CTYPES)))
        spanish = set(fx.CONSTRAINT_TYPES.values())
        self.assertEqual(len(spanish), 11)
        polygons = set(self.read[fx.LAYER_POLYGONS].attributes["tipo"])
        self.assertEqual(polygons, spanish)
        limits = {fx.CONSTRAINT_TYPES["legal_limit"], fx.CONSTRAINT_TYPES["action_perimeter"]}
        for name in (fx.LAYER_LINES, fx.LAYER_POINTS):
            types = set(self.read[name].attributes["tipo"])
            self.assertTrue(types <= spanish - limits, name)
        for name in (fx.LAYER_POLYGONS, fx.LAYER_LINES, fx.LAYER_POINTS):
            attributes = self.read[name].attributes
            for field in ("nombre", "motivo", "decisor"):
                self.assertTrue(all(attributes[field]), (name, field))
            self.assertTrue(all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", day)
                                for day in attributes["fecha"]))

    def test_the_limits_are_the_reference_ones(self) -> None:
        polygons = fx.source_features()[fx.LAYER_POLYGONS]
        np.testing.assert_array_equal(polygons[0].coords[0], fx.limits().legal_limit)
        np.testing.assert_array_equal(polygons[1].coords[0], fx.limits().perimeter)
        np.testing.assert_array_equal(polygons[8].coords[0], fx.pond_case().zone_coords[0])

    def test_marks_with_their_role(self) -> None:
        attributes = self.read[fx.LAYER_MARKS].attributes
        self.assertEqual(sorted(fx.INTENTION_ROLES), sorted(ROLES))
        self.assertEqual(sorted(attributes["rol"]), sorted(fx.INTENTION_ROLES.values()))
        for role, elevation in zip(attributes["rol"], attributes["cota"], strict=True):
            if role == fx.INTENTION_ROLES["mine_to_elevation"]:
                self.assertEqual(elevation, fx.MINE_ELEVATION_M)
            else:
                self.assertIsNone(elevation)
        kinds = {g.geometry_type for g in self.read[fx.LAYER_MARKS].geometries}
        self.assertEqual(kinds, {"POINT", "LINESTRING", "POLYGON"})

    def test_distances_to_the_sectors_by_hand(self) -> None:
        tower = _local(fx.absolute([fx.TOWER_LOCAL]))[0]
        line = _local(fx.absolute(fx.POWER_LINE_LOCAL))
        found = {}
        for name, box in fx.SECTORS_LOCAL.items():
            to_tower = float(segment_box_distance(tower, tower, *box))
            to_line = float(segment_box_distance(line[0], line[1], *box))
            self.assertEqual(to_tower, fx.TOWER_TO_SECTOR_M[name])
            self.assertAlmostEqual(to_line, fx.POWER_LINE_TO_SECTOR_M[name], delta=1e-12)
            found[name] = {label for label, d in (("torre", to_tower), ("línea", to_line))
                           if d <= fx.SEARCH_DISTANCE_M}
        self.assertEqual(fx.TOWER_TO_SECTOR_M["Sector 2"], 6.0)
        self.assertEqual(fx.POWER_LINE_TO_SECTOR_M["Sector 2"], math.hypot(30.0, 15.0))
        self.assertEqual(found, {"Sector 1": {"línea"}, "Sector 2": {"torre"}})

    def test_sectors_without_overlaps_inside_the_perimeter(self) -> None:
        cell = fx.SITE_GRID.cell_area
        x, y = _site_centers()
        perimeter = even_odd(fx.limits().perimeter, x, y)
        covered = np.zeros(x.shape, dtype=int)
        for feature in fx.source_features()[fx.LAYER_SECTORS]:
            sector = even_odd(feature.coords[0], x, y)
            self.assertEqual(sector.sum() * cell, shoelace(feature.coords[0]))
            self.assertTrue(np.all(perimeter[sector]))
            covered += sector
        self.assertEqual(int(covered.max()), 1)
        self.assertEqual((perimeter & (covered == 0)).sum() * cell, fx.SECTORS_UNCOVERED_M2)
        self.assertEqual(fx.SECTORS_UNCOVERED_M2, 34_400.0 - 2 * 11_200.0)


if __name__ == "__main__":
    unittest.main()
