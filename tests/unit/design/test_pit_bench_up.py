# SPDX-License-Identifier: GPL-3.0-or-later
"""La corta ascendente por bancos (spec 018, T10; HU-018-1; RF-018-11, RF-018-14, RF-018-25; CE-018-01, CE-018-03; plan 018 §5.4 A5).

El fondo circular de 50 m (CE-018-03: 5 bancos, radios y cotas a mano), el cuadrado de 100 m (CE-018-01), el terreno inclinado (sale en
bancos distintos por lado), dos fondos que se unen, la cota de coronación, los rechazos (200 bancos sin salir, nada que excavar, el
terreno que se acaba) y el orden determinista de las polilíneas. Todo sin proyecto y sin Blender; las cuentas, a mano o con el oráculo de
fuerza bruta de ``tests/support/offset_oracle.py`` (que no usa el motor)."""

from __future__ import annotations

import dataclasses
import math
import unittest
from unittest import mock

import numpy as np

from tests.support import offset_oracle as oracle
from tests.support import pit_data as pd
from tests.support.package import import_geoblender

pit_bench = import_geoblender("design.pit_bench")
pit_model = import_geoblender("design.pit_model")
pit_rose = import_geoblender("design.pit_rose")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")

ARC_M = pd.HYPOTHESES.arc_hand_m
"""La tolerancia de arco de las cifras a mano (D-14: HIPÓTESIS), 1 mm."""
TINY_M = 1e-6
"""La simplificación de las cifras a mano: nada se quita (D-14: HIPÓTESIS)."""
FACE_M = 10.0 / math.tan(math.radians(60.0))
"""h/tan α = 5,7735 m."""
ADVANCE_M = FACE_M + 6.0
"""El avance de un banco: 11,7735 m."""


def profile(**changes: object) -> object:
    return model.BenchProfile(**{**dataclasses.asdict(pd.EXPL), **changes})


def request(**changes: object) -> object:
    values: dict[str, object] = {"name": "Corta 1", "fields": pit_model.LayerFields(layer="gis_fea_fondos", name_field="nombre"),
                                 "mode": "up", "start": "terreno", "level_field": "cota_m"}
    values.update(changes)
    return pit_model.PitRequest(**values)


def params(**changes: object) -> object:
    values: dict[str, object] = {"arc_tol_m": ARC_M, "simplify_m": TINY_M}
    values.update(changes)
    return pit_model.PitParams(**values)


def fondo(ring: np.ndarray | None = None, level: float = pd.FLOOR_Z_M, name: str = "fondo") -> object:
    return pit_model.PitSource(name, pd.absolute(pd.circle_ring() if ring is None else ring), level)


def job(**changes: object) -> object:
    values: dict[str, object] = {
        "request": request(), "code": "PIT-001", "grid": pd.GRID, "start": pd.flat_terrain(pd.GRID),
        "cut_allowed": np.ones(pd.GRID.shape, bool), "fill_allowed": np.zeros(pd.GRID.shape, bool),
        "untouchable": np.zeros(pd.GRID.shape, bool), "sources": (fondo(),), "params": params(), "profile": profile(),
    }
    values.update(changes)
    return pit_model.PitJob(**values)


def local(polyline: object) -> np.ndarray:
    """Los vértices de una polilínea (x, y) en locales."""
    return polyline.vertices[:, :2] - np.asarray(pd.origin_of(pd.GRID))


def radii(polyline: object) -> np.ndarray:
    xy = local(polyline)
    return np.hypot(xy[:, 0] - pd.CENTER[0], xy[:, 1] - pd.CENTER[1])


def of_kind(found: object, kind: str, bench: int | None = None) -> list[object]:
    return [item for item in found.polylines if item.kind == kind and (bench is None or item.bench == bench)]


class CircleTest(unittest.TestCase):
    """CE-018-03: el fondo circular de 50 m, ``EXPL_10_60_6`` y 5 bancos sobre un terreno llano a 175 m."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.found = pit_bench.ascend(job())

    def test_five_benches_and_exit_to_surface(self) -> None:
        """RF-018-11: sale a superficie cuando el pie llega a la cota del terreno: 5 bancos (el pie 5, a 175 m, ya no excava)."""
        self.assertEqual(self.found.count, 5)
        self.assertEqual(self.found.stop, pit_model.StopCriterion.SURFACE)
        self.assertEqual(len(self.found.polylines), 10)
        self.assertTrue(self.found.reliable)
        self.assertEqual(self.found.notices, ())

    def test_levels_are_anchor_plus_k_times_h(self) -> None:
        """RF-018-11: el pie k a z₀ + k·h y su cresta a z₀ + (k + 1)·h, a ≤ 10⁻⁹ m; el orden es banco, pie y cresta."""
        order = [(item.kind, item.bench) for item in self.found.polylines]
        self.assertEqual(order, [(kind, k) for k in range(5) for kind in ("foot", "crest")])
        for item in self.found.polylines:
            with self.subTest(kind=item.kind, bench=item.bench):
                level = pd.FLOOR_Z_M + (item.bench + (1 if item.kind == "crest" else 0)) * 10.0
                self.assertTrue(np.all(np.abs(item.vertices[:, 2] - level) <= 1e-9))
                self.assertTrue(item.closed)
                self.assertEqual((item.zone, item.sector, item.part), ("", "", 0))

    def test_radii_by_hand(self) -> None:
        """CE-018-03: los radios de pie y de cresta de cada banco, a mano (cresta = pie + h/tan α; pie siguiente = cresta + B), dentro de
        la tolerancia de arco de cada desfase y de la discretización del fondo (720 lados: 0,5 mm de flecha)."""
        by_hand = pd.circle_radii_by_hand()
        sagitta = pd.CIRCLE_RADIUS_M * (1.0 - math.cos(math.pi / pd.CIRCLE_VERTICES))
        for k, (foot, crest) in enumerate(by_hand):
            for item, expected in ((of_kind(self.found, "foot", k)[0], foot), (of_kind(self.found, "crest", k)[0], crest)):
                with self.subTest(kind=item.kind, bench=k):
                    found = radii(item)
                    steps = 2 * k + (1 if item.kind == "crest" else 0) + 1
                    self.assertGreaterEqual(float(found.min()), expected - sagitta - 1e-9)
                    self.assertLessEqual(float(found.max()), expected + steps * ARC_M + sagitta + 1e-9)

    def test_volume_without_grid_matches_analytic(self) -> None:
        """CE-018-03: el volumen de las caras sin la rejilla (cálculo analítico por banco con el área y el perímetro de pie y cresta)
        coincide con la suma de troncos de cono a mano (961.661,57 m³) con una diferencia ≤ 0,1 %."""
        exact = pd.circle_volume_by_hand()
        self.assertAlmostEqual(exact, 961661.57, delta=0.01)
        self.assertAlmostEqual(self.found.face_volume_m3 / exact, 1.0, delta=1e-3)

    def test_steps_end_with_the_result(self) -> None:
        """Los pasos ceden ``Progress`` y el último lleva los bancos; ``ascend`` da lo mismo, bit a bit."""
        steps = list(pit_bench.ascend_steps(job(), budget_s=0.05))
        self.assertGreater(len(steps), 1)
        self.assertTrue(all(step.result is None for step in steps[:-1]))
        last = steps[-1].result
        self.assertEqual(len(last.polylines), 10)
        for one, other in zip(last.polylines, self.found.polylines, strict=True):
            self.assertTrue(np.array_equal(one.vertices, other.vertices))


class SquareTest(unittest.TestCase):
    """CE-018-01: el cuadrado de 100 m con ``EXPL_10_60_6``."""

    def test_crest_and_next_foot_distance_to_the_source(self) -> None:
        """CE-018-01: la cresta del banco 0 a 5,7735 m del fondo y el pie siguiente a 11,7735 m; el resultado es simple."""
        square = pd.square_ring(pd.SQUARE_SIDE_M)
        found = pit_bench.ascend(job(sources=(fondo(square),)))
        crest, foot = of_kind(found, "crest", 0)[0], of_kind(found, "foot", 1)[0]
        for item, expected, steps in ((crest, FACE_M, 1), (foot, ADVANCE_M, 2)):
            gap = oracle.distance_to_ring(local(item), square)
            self.assertGreaterEqual(float(gap.min()), expected - 1e-9)
            self.assertLessEqual(float(gap.max()), expected + steps * ARC_M + 1e-9)
            self.assertEqual(oracle.crossing_count([local(item)]), 0)
        exact = pd.square_crest_area_by_hand(pd.SQUARE_SIDE_M, FACE_M, rounded=True)
        area = oracle.signed_area(local(crest))
        self.assertGreaterEqual(area, exact - 1e-6)
        self.assertLessEqual(area, exact + ARC_M * crest.length_m)


class RoseTest(unittest.TestCase):
    """RF-018-11 con la roseta de CE-018-02: el ascendente pide a cada arista la distancia de su rango."""

    def test_crest_distance_follows_the_face_azimuth(self) -> None:
        """La cara baja hacia el fondo: en el lado oeste (la cara mira al este, 90°) la cresta está a 5,7735 m y en el este (270°), a 10 m."""
        rose = tuple(pit_rose.RoseRange(r.from_deg, r.to_deg, r.face_deg, r.berm_m) for r in pd.ROSE_TWO_RANGES)
        found = pit_bench.ascend(job(rose=rose, start=pd.flat_terrain(pd.GRID, 135.0), params=params(top_level_m=135.0)))
        crest = of_kind(found, "crest", 0)[0]
        xy = local(crest)
        west = xy[np.argmin(np.abs(xy[:, 1] - pd.CENTER[1]) + (xy[:, 0] > pd.CENTER[0]) * 1e6)]
        east = xy[np.argmin(np.abs(xy[:, 1] - pd.CENTER[1]) + (xy[:, 0] < pd.CENTER[0]) * 1e6)]
        self.assertAlmostEqual(pd.CENTER[0] - west[0], pd.CIRCLE_RADIUS_M + FACE_M, delta=2 * ARC_M)
        self.assertAlmostEqual(east[0] - pd.CENTER[0], pd.CIRCLE_RADIUS_M + 10.0, delta=2 * ARC_M)


class InclinedTerrainTest(unittest.TestCase):
    """RF-018-11 con terreno inclinado: el pie sale cuando todos sus vértices (y las muestras de sus aristas) están a la cota del terreno."""

    def test_exits_when_the_whole_foot_is_at_or_above_the_ground(self) -> None:
        """Terreno de CE-018-07 (130 m en x = 0, 10 % al este): el pie k tiene su punto más alto del terreno al este, a x = 200 + r_k;
        sale en el primer banco cuya cota alcanza esa del terreno (aquí el 4: 4 bancos), no en el que sale el lado oeste."""
        start = pd.inclined_terrain(pd.GRID)
        found = pit_bench.ascend(job(start=start))
        expected = None
        for k, (foot, _crest) in enumerate(pd.circle_radii_by_hand(benches=20)):
            ground_east = 130.0 + 0.1 * (pd.CENTER[0] + foot)
            if pd.FLOOR_Z_M + 10.0 * k >= ground_east:
                expected = k
                break
        self.assertEqual(expected, 4)
        self.assertEqual(found.count, expected)
        self.assertEqual(found.stop, pit_model.StopCriterion.SURFACE)
        west_foot = pd.CENTER[0] - pd.circle_radii_by_hand(benches=4)[3][1]
        self.assertLess(130.0 + 0.1 * west_foot, pd.FLOOR_Z_M + 10.0 * 3, "el lado oeste ya estaba por encima en el banco 3")

    def test_ground_lower_than_the_foot_on_one_side_only_does_not_exit(self) -> None:
        """Un solo vértice por debajo del terreno basta para no salir."""
        start = pd.flat_terrain(pd.GRID, 120.0)
        start[0:3, :] = 400.0  # el norte de la rejilla sube
        start[:, :] = np.where(np.arange(start.shape[0])[:, None] < 200, 400.0, 120.0)  # la mitad norte, muy alta
        with self.assertRaises(messages.DesignError) as caught:
            pit_bench.ascend(job(start=start, params=params(max_benches=3)))
        self.assertEqual(caught.exception.code, pit_model.PitCode.NOT_REACHING_SURFACE.value)


class JoinedBottomsTest(unittest.TestCase):
    """RF-018-11: los fondos que se tocan al crecer se unen (``overlay`` de la 012)."""

    def test_two_bottoms_merge_when_their_feet_overlap(self) -> None:
        """Dos cuadrados de 100 m a 20 m uno de otro: sus crestas del banco 0 (5,77 m) aún no se tocan, pero sus pies del banco 1
        (11,77 m) sí: desde ahí es una sola polilínea, simple, que contiene a las dos."""
        west = pd.square_ring(100.0, (100.0, 200.0))
        east = pd.square_ring(100.0, (220.0, 200.0))
        found = pit_bench.ascend(job(sources=(fondo(west, name="oeste"), fondo(east, name="este")), start=pd.flat_terrain(pd.GRID, 155.0)))
        self.assertEqual([item.part for item in of_kind(found, "foot", 0)], [0, 1])
        self.assertEqual(len(of_kind(found, "crest", 0)), 2)
        joined = of_kind(found, "foot", 1)
        self.assertEqual(len(joined), 1, "los dos pies del banco 1 se tocan: una sola polilínea")
        ring = local(joined[0])
        self.assertEqual(oracle.crossing_count([ring]), 0)
        for square in (west, east):
            gap = oracle.distance_to_ring(ring, square)
            self.assertGreaterEqual(float(gap.min()), ADVANCE_M - 1e-9)
        area = oracle.signed_area(ring)
        alone = pd.square_crest_area_by_hand(100.0, ADVANCE_M, rounded=True)
        self.assertGreater(area, 2.0 * alone - 20.0 * 100.0 * 2.0, "más que dos pies sueltos menos su solape")
        self.assertLess(area, 2.0 * alone)

    def test_a_bottom_at_a_higher_level_starts_at_its_own_bench(self) -> None:
        """Cada fondo a su cota: el de 135 m empieza en el banco 1 (z₀ + 1·h)."""
        found = pit_bench.ascend(job(sources=(fondo(pd.square_ring(60.0, (100.0, 100.0)), 125.0, "bajo"),
                                              fondo(pd.square_ring(60.0, (300.0, 300.0)), 135.0, "alto")),
                                     start=pd.flat_terrain(pd.GRID, 145.0)))
        benches = sorted({(item.kind, item.bench, item.part) for item in found.polylines})
        self.assertEqual(benches, [("crest", 0, 0), ("crest", 1, 0), ("crest", 1, 1), ("foot", 0, 0), ("foot", 1, 0), ("foot", 1, 1)])
        self.assertEqual(found.count, 2)


class StopTest(unittest.TestCase):
    def test_top_level_stops_the_pit(self) -> None:
        """RF-018-11: con cota de coronación 145 m se para en el banco cuyo pie llega a ella: 2 bancos, aunque el terreno siga a 175 m."""
        found = pit_bench.ascend(job(params=params(top_level_m=145.0)))
        self.assertEqual(found.count, 2)
        self.assertEqual(found.stop, pit_model.StopCriterion.TOP_LEVEL)
        self.assertEqual(max(item.bench for item in found.polylines), 1)

    def test_surface_wins_over_the_top_level_when_both_are_reached(self) -> None:
        found = pit_bench.ascend(job(params=params(top_level_m=175.0)))
        self.assertEqual((found.count, found.stop), (5, pit_model.StopCriterion.SURFACE))


class RejectionTest(unittest.TestCase):
    """RF-018-14 y RF-018-04: lo que no sale, no se registra: error con el banco, el límite y el lugar."""

    def test_max_benches_without_reaching_the_surface(self) -> None:
        """El máximo de bancos del usuario (3) sin salir a superficie: rechazo con el banco, el límite y el lugar."""
        with self.assertRaises(messages.DesignError) as caught:
            pit_bench.ascend(job(params=params(max_benches=3)))
        error = caught.exception
        self.assertEqual(error.code, pit_model.PitCode.NOT_REACHING_SURFACE.value)
        self.assertEqual((error.values["limit"], error.values["bench"], error.values["name"]), (3, 3, "Corta 1"))
        self.assertIn("place", error.values)
        self.assertIn("cerca de", str(error))

    def test_two_hundred_benches_without_reaching_the_surface(self) -> None:
        """RF-018-14: a los 200 bancos sin salir (cada banco avanza 0,03 m: el terreno a 500 m queda lejos), rechazo."""
        thin = profile(code="fino", name="FINO", height_m=1.0, face_deg=89.0, berm_m=0.01)
        start = pd.flat_terrain(pd.GRID, 500.0)
        with self.assertRaises(messages.DesignError) as caught:
            pit_bench.ascend(job(sources=(fondo(pd.square_ring(10.0)),), profile=thin, start=start))
        self.assertEqual(caught.exception.code, pit_model.PitCode.NOT_REACHING_SURFACE.value)
        self.assertEqual((caught.exception.values["limit"], caught.exception.values["bench"]), (200, 200))

    def test_nothing_to_excavate(self) -> None:
        """RF-018-04: un fondo que no queda por debajo del terreno en ningún punto de su contorno."""
        with self.assertRaises(messages.DesignError) as caught:
            pit_bench.ascend(job(sources=(fondo(level=175.0),)))
        self.assertEqual(caught.exception.code, pit_model.PitCode.NOTHING_TO_EXCAVATE.value)
        self.assertEqual((caught.exception.values["field"], caught.exception.values["value"]), ("fondo", 175.0))

    def test_growing_off_the_grid_is_a_rejection_with_the_place(self) -> None:
        """Un terreno alto y un fondo junto al borde: el pie sale de la rejilla antes de salir a superficie; se dice dónde, no se inventa."""
        start = pd.flat_terrain(pd.GRID, 900.0)
        with self.assertRaises(messages.DesignError) as caught:
            pit_bench.ascend(job(sources=(fondo(pd.square_ring(60.0, (60.0, 60.0))),), start=start))
        self.assertEqual(caught.exception.code, pit_model.PitCode.NOT_REACHING_SURFACE.value)
        self.assertIn("sin dato", caught.exception.values["place"])

    def test_vertex_limit(self) -> None:
        """RF-018-04: más de 50.000 vértices por polilínea (aquí, un límite de 100) es un rechazo de validez."""
        with mock.patch.object(pit_bench, "MAX_VERTICES", 100):
            with self.assertRaises(messages.DesignError) as caught:
                pit_bench.ascend(job())
        self.assertEqual(caught.exception.code, pit_model.PitCode.TOO_MANY_BENCHES.value)
        self.assertGreater(caught.exception.values["vertices"], 100)

    def test_a_double_bench_needs_the_fondo_on_the_lattice(self) -> None:
        """RF-018-08 (T12): con n = 2 los fondos están en la retícula de n·h (z₀ + j·n·h); uno a 135 m es un error del programa (la preparación lo
        rechaza antes). Los bancos dobles y los fijados, en ``test_pit_bench_fixed``."""
        with self.assertRaises(ValueError):
            pit_bench.ascend(job(params=params(n_berm=2), sources=(fondo(level=135.0),)))

    def test_a_bottom_off_the_anchor_lattice_is_a_program_error(self) -> None:
        """Una cota de fondo que no es z₀ + j·h rompe la continuidad de los planos (D-4): la preparación lo rechaza antes; aquí, error."""
        with self.assertRaises(ValueError):
            pit_bench.ascend(job(sources=(fondo(level=127.5),)))


class DeterminismTest(unittest.TestCase):
    def test_same_inputs_same_polylines_bit_by_bit(self) -> None:
        """RF-018-25: las mismas entradas dan las mismas polilíneas, en el mismo orden y con los mismos vértices, bit a bit."""
        sources = (fondo(pd.square_ring(100.0, (100.0, 200.0)), name="a"), fondo(pd.square_ring(100.0, (220.0, 200.0)), name="b"))
        start = pd.flat_terrain(pd.GRID, 155.0)
        one = pit_bench.ascend(job(sources=sources, start=start))
        other = pit_bench.ascend(job(sources=sources, start=start))
        self.assertEqual(len(one.polylines), len(other.polylines))
        for left, right in zip(one.polylines, other.polylines, strict=True):
            self.assertEqual((left.kind, left.bench, left.part, left.sector), (right.kind, right.bench, right.part, right.sector))
            self.assertTrue(np.array_equal(left.vertices, right.vertices))
        self.assertEqual(one.face_volume_m3, other.face_volume_m3)

    def test_the_order_of_the_sources_does_not_change_the_order_of_the_parts(self) -> None:
        """Las partes de un banco salen ordenadas por su posición, no por el orden en que llegaron las fuentes."""
        a, b = fondo(pd.square_ring(60.0, (80.0, 200.0)), name="a"), fondo(pd.square_ring(60.0, (300.0, 200.0)), name="b")
        first = pit_bench.ascend(job(sources=(a, b), start=pd.flat_terrain(pd.GRID, 135.0)))
        second = pit_bench.ascend(job(sources=(b, a), start=pd.flat_terrain(pd.GRID, 135.0)))
        for left, right in zip(first.polylines, second.polylines, strict=True):
            self.assertTrue(np.array_equal(left.vertices, right.vertices))


if __name__ == "__main__":
    unittest.main()
