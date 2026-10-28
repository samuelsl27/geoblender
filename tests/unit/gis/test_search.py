# SPDX-License-Identifier: GPL-3.0-or-later
"""Las distancias de la búsqueda de intocables (spec 012, T12; RF-012-08; plan 012 A6).

- **RF-012-08**: se lista cada entidad de las capas a una distancia del sector ≤ la distancia de
  búsqueda, con su capa, su número, sus atributos y su distancia (m). A mano, con un sector
  cuadrado de 100 m: un punto a 6 m de un lado (6), uno dentro (0), una línea que lo cruza sin
  vértices dentro (0), una que pasa a 24,9 m (sí, con 25 m) y otra a 25,1 m (no), un polígono
  que contiene el sector (0), uno con un hueco que lo rodea a 20 m (20, no 0) y otro con el hueco
  a 30 m (no), una esquina en diagonal (√200) y una línea de dos partes (la cercana manda).
- **A6**: la caja como prefiltro no cambia nada (lo mismo sin él); por pasos de una entidad, lo
  mismo que de una vez; cada paso ≤ 0,05 s; y, con capas aleatorias, la misma distancia que una
  fuerza bruta (cada par de segmentos y el par-impar de cada vértice) hasta 10⁻⁹ m.
"""

import math
import time
import unittest

import numpy as np

from tests.support import constraints_fixtures as fx
from tests.support.package import import_geoblender

search = import_geoblender("gis.search")
vector = import_geoblender("gis.vector")
polygons = import_geoblender("gis.polygons")

DISTANCE = 25.0  # m (la distancia de búsqueda por defecto, D-5)
NAME = vector.FieldColumn("nombre", "nombre", "TEXT")


def rect(left, bottom, right, top):
    """Un anillo absoluto cerrado (locales desde ``fx.BASE``)."""
    return fx.rectangle(left, bottom, right, top)


def absolute(points):
    return fx.absolute(points)


def layer(kind, features):
    """Una capa de entidades: ``features`` = [(fid, nombre, partes)], partes en locales (un
    punto (x, y), un camino [(x, y)…] o los anillos de un polígono [[(x, y)…], …])."""
    parts = []
    for _, _, items in features:
        if kind == "point":
            parts.append(tuple((absolute([p]),) for p in items))
        elif kind == "line":
            parts.append(tuple((absolute(path),) for path in items))
        else:
            parts.append(tuple(tuple(r if isinstance(r, np.ndarray) else absolute(r)
                                     for r in polygon) for polygon in items))
    return vector.FeatureLayer(kind, tuple(f for f, _, _ in features), tuple(parts), (NAME,),
                               {"nombre": tuple(n for _, n, _ in features)})


SECTOR = (rect(0.0, 0.0, 100.0, 100.0),)

POINTS = layer("point", [
    (1, "a 6 m", [(106.0, 50.0)]),
    (2, "dentro", [(50.0, 50.0)]),
    (3, "esquina", [(110.0, 110.0)]),
    (4, "lejos", [(400.0, 400.0)]),
])
LINES = layer("line", [
    (10, "cruza", [[(-20.0, 50.0), (120.0, 50.0)]]),
    (11, "a 24,9 m", [[(-50.0, 124.9), (150.0, 124.9)]]),
    (12, "a 25,1 m", [[(-50.0, 125.1), (150.0, 125.1)]]),
    (13, "dos partes", [[(300.0, 0.0), (300.0, 100.0)], [(-12.0, -40.0), (-12.0, 140.0)]]),
])
POLYGONS = layer("polygon", [
    (20, "contiene", [[rect(-10.0, -10.0, 110.0, 110.0)]]),
    (21, "hueco a 20 m", [[rect(-100.0, -100.0, 200.0, 200.0), rect(-20.0, -20.0, 120.0, 120.0)]]),
    (22, "hueco a 30 m", [[rect(-100.0, -100.0, 200.0, 200.0), rect(-30.0, -30.0, 130.0, 130.0)]]),
    (23, "al lado", [[rect(115.0, 40.0, 140.0, 60.0)]]),
])
LAYERS = {"torres": POINTS, "lineas": LINES, "zonas": POLYGONS}

EXPECTED = {  # (capa, fid) → distancia (m)
    ("torres", 1): 6.0, ("torres", 2): 0.0, ("torres", 3): math.sqrt(200.0),
    ("lineas", 10): 0.0, ("lineas", 11): 24.9, ("lineas", 13): 12.0,
    ("zonas", 20): 0.0, ("zonas", 21): 20.0, ("zonas", 23): 15.0,
}


def run(*args, **kwargs):
    *_, last = search.search_steps(*args, **kwargs)
    return last.result


def as_dict(found):
    return {(f.layer, f.fid): f.distance_m for f in found}


class HandTest(unittest.TestCase):
    """RF-012-08: las distancias a mano."""

    def test_distances_by_hand(self):
        found = run(SECTOR, LAYERS, DISTANCE)
        got = as_dict(found)
        self.assertEqual(set(got), set(EXPECTED))
        for key, value in EXPECTED.items():
            self.assertAlmostEqual(got[key], value, delta=1e-9, msg=key)

    def test_found_carries_layer_fid_and_attributes(self):
        found = run(SECTOR, LAYERS, DISTANCE)
        first = found[0]
        self.assertIsInstance(first, search.Found)
        self.assertEqual((first.layer, first.fid), ("torres", 1))
        self.assertEqual(dict(first.attributes), {"nombre": "a 6 m"})
        # En el orden de las capas y, dentro de cada una, en el de sus entidades.
        self.assertEqual([(f.layer, f.fid) for f in found],
                         [("torres", 1), ("torres", 2), ("torres", 3), ("lineas", 10),
                          ("lineas", 11), ("lineas", 13), ("zonas", 20), ("zonas", 21),
                          ("zonas", 23)])

    def test_sequence_of_layers_named_by_position(self):
        found = run(SECTOR, [POINTS, LINES], DISTANCE)
        self.assertEqual({(f.layer, f.fid) for f in found},
                         {(0, 1), (0, 2), (0, 3), (1, 10), (1, 11), (1, 13)})

    def test_prefilter_changes_nothing(self):
        with_box = run(SECTOR, LAYERS, DISTANCE)
        without = run(SECTOR, LAYERS, DISTANCE, prefilter=False)
        self.assertEqual(with_box, without)

    def test_by_steps_same_as_at_once(self):
        at_once = run(SECTOR, LAYERS, DISTANCE, features_per_step=10_000)
        by_one = run(SECTOR, LAYERS, DISTANCE, features_per_step=1, budget_s=1e-9)
        self.assertEqual(at_once, by_one)

    def test_sector_with_two_parts_and_closed_or_open_rings(self):
        open_ring = fx.rectangle(200.0, 0.0, 260.0, 100.0)[:-1]
        found = as_dict(run((*SECTOR, open_ring), {"torres": POINTS}, DISTANCE))
        self.assertAlmostEqual(found[("torres", 1)], 6.0)
        self.assertNotIn(("torres", 4), found)

    def test_rejects_bad_arguments(self):
        for bad in (-1.0, math.nan, math.inf, True):
            with self.assertRaises(ValueError, msg=bad):
                run(SECTOR, LAYERS, bad)
        with self.assertRaises(ValueError):
            run((), LAYERS, DISTANCE)
        with self.assertRaises(ValueError):
            run(SECTOR, LAYERS, DISTANCE, budget_s=0)

    def test_inputs_untouched(self):
        before = [ring.copy() for ring in SECTOR]
        parts = [[r.copy() for part in feature for r in part] for feature in LINES.parts]
        run(SECTOR, LAYERS, DISTANCE)
        for ring, old in zip(SECTOR, before, strict=True):
            np.testing.assert_array_equal(ring, old)
        for feature, old in zip(LINES.parts, parts, strict=True):
            for ring, copy in zip([r for part in feature for r in part], old, strict=True):
                np.testing.assert_array_equal(ring, copy)


# Fuerza bruta -------------------------------------------------------------------------------


def _segments(kind, feature_parts):
    segs, points, rings = [], [], []
    for part in feature_parts:
        for path in part:
            path = np.asarray(path, dtype=np.float64)
            points.extend(path)
            if kind == "point":
                segs.append(np.stack([path, path], axis=1))
            elif kind == "line":
                segs.append(np.stack([path[:-1], path[1:]], axis=1))
            else:
                ring = path[:-1] if np.array_equal(path[0], path[-1]) else path
                rings.append(ring)
                segs.append(np.stack([ring, np.roll(ring, -1, axis=0)], axis=1))
    return np.concatenate(segs), np.array(points), rings


def _even_odd(point, rings):
    x, y = point
    inside = False
    for ring in rings:
        for (ax, ay), (bx, by) in zip(ring, np.roll(ring, -1, axis=0), strict=True):
            if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
                inside = not inside
    return inside


def brute(sector, layers, distance):
    """Cada par de segmentos y el par-impar de cada vértice, sin cajas."""
    sector_rings = [r[:-1] if np.array_equal(r[0], r[-1]) else r for r in sector]
    sector_segs = np.concatenate([np.stack([r, np.roll(r, -1, axis=0)], axis=1)
                                  for r in sector_rings])
    out = {}
    for name, found in layers.items():
        for index, fid in enumerate(found.fids):
            segs, points, rings = _segments(found.kind, found.parts[index])
            if any(_even_odd(p, sector_rings) for p in points) or (
                    rings and any(_even_odd(r[0], rings) for r in sector_rings)):
                d = 0.0
            else:
                p = np.repeat(segs, len(sector_segs), axis=0)
                q = np.tile(sector_segs, (len(segs), 1, 1))
                d = float(polygons.segment_distance(p, q).min())
            if d <= distance:
                out[(name, fid)] = d
    return out


def random_layers(rng, count):
    """Puntos, líneas y polígonos (algunos con hueco) alrededor del sector, en locales."""
    pts, lines, polys = [], [], []
    for k in range(count):
        cx, cy = rng.uniform(-80.0, 180.0, 2)
        pts.append((k + 1, f"p{k}", [(cx, cy)]))
        steps = rng.normal(0.0, 15.0, (int(rng.integers(2, 6)), 2))
        lines.append((k + 1, f"l{k}", [[tuple(v) for v in np.cumsum(steps, axis=0) + (cx, cy)]]))
        w, h = rng.uniform(2.0, 60.0, 2)
        ring = [(cx, cy), (cx + w, cy), (cx + w, cy + h), (cx, cy + h)]
        rings = [ring]
        if k % 3 == 0:
            rings.append([(cx + w / 4, cy + h / 4), (cx + w / 4, cy + 3 * h / 4),
                          (cx + 3 * w / 4, cy + 3 * h / 4), (cx + 3 * w / 4, cy + h / 4)])
        polys.append((k + 1, f"z{k}", [rings]))
    return {"p": layer("point", pts), "l": layer("line", lines), "z": layer("polygon", polys)}


class BruteForceTest(unittest.TestCase):
    """A6 frente a una fuerza bruta, con capas aleatorias."""

    def test_same_as_brute_force(self):
        rng = np.random.default_rng(12)
        sector = (absolute([(0, 0), (100, 0), (100, 60), (40, 60), (40, 100), (0, 100)]),
                  absolute([(10, 10), (10, 30), (30, 30), (30, 10)]))
        layers = random_layers(rng, 120)
        expected = brute(sector, layers, DISTANCE)
        got = as_dict(run(sector, layers, DISTANCE, features_per_step=7))
        self.assertEqual(set(got), set(expected))
        for key, value in expected.items():
            self.assertAlmostEqual(got[key], value, delta=1e-9, msg=key)
        self.assertGreater(len(expected), 100)
        self.assertLess(len(expected), 360)

    def test_each_step_within_budget(self):
        rng = np.random.default_rng(3)
        layers = random_layers(rng, 1500)
        steps = search.search_steps(SECTOR, layers, DISTANCE, budget_s=0.05)
        slowest, count = 0.0, 0
        while True:
            start = time.perf_counter()
            try:
                progress = next(steps)
            except StopIteration:
                break
            slowest = max(slowest, time.perf_counter() - start)
            count += 1
        self.assertIsNotNone(progress.result)
        self.assertLessEqual(slowest, 0.05)
        self.assertGreaterEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
