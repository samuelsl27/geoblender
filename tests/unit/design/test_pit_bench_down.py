# SPDX-License-Identifier: GPL-3.0-or-later
"""La corta descendente por bancos (spec 018, T11; HU-018-1; RF-018-12, 13 y 14; CE-018-04; plan 018 §5.4 A6 y §5.8 H-2).

El límite cuadrado de 200 m de CE-018-04 (5 bancos, lados de pie a mano y parada por el ancho mínimo; con la cota de fondo, 3 bancos), el
límite que queda vacío antes del primer banco, un interior que se parte en dos partes, el primer banco de altura variable (terreno
inclinado, cota dada y un primer banco casi sin altura), el máximo de bancos y los límites de validez. Todo sin proyecto y sin Blender."""

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
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")

ARC_M = pd.HYPOTHESES.arc_hand_m
TINY_M = 1e-6
TOL_M = 1e-6
"""Lo que un lado a mano puede apartarse del calculado (las esquinas convexas hacia dentro son exactas)."""


def profile(**changes: object) -> object:
    return model.BenchProfile(**{**dataclasses.asdict(pd.DESD), **changes})


def request(**changes: object) -> object:
    values: dict[str, object] = {"name": "Corta 1", "fields": pit_model.LayerFields(layer="gis_fea_limites", name_field="nombre"),
                                 "mode": "down", "start": "terreno"}
    values.update(changes)
    return pit_model.PitRequest(**values)


def params(**changes: object) -> object:
    values: dict[str, object] = {"arc_tol_m": ARC_M, "simplify_m": TINY_M, "min_floor_width_m": pd.MIN_FLOOR_WIDTH_M}
    values.update(changes)
    return pit_model.PitParams(**values)


def limite(ring: np.ndarray | None = None, level: float | None = None, name: str = "limite") -> object:
    return pit_model.PitSource(name, pd.absolute(pd.square_ring(pd.LIMIT_SIDE_M) if ring is None else ring), level)


def job(**changes: object) -> object:
    values: dict[str, object] = {
        "request": request(), "code": "PIT-001", "grid": pd.GRID, "start": pd.limit_terrain(pd.GRID),
        "cut_allowed": np.ones(pd.GRID.shape, bool), "fill_allowed": np.zeros(pd.GRID.shape, bool),
        "untouchable": np.zeros(pd.GRID.shape, bool), "sources": (limite(),), "params": params(), "profile": profile(),
    }
    values.update(changes)
    return pit_model.PitJob(**values)


def local(polyline: object) -> np.ndarray:
    return polyline.vertices[:, :2] - np.asarray(pd.origin_of(pd.GRID))


def side_of(polyline: object) -> float:
    xy = local(polyline)
    return float(max(np.ptp(xy[:, 0]), np.ptp(xy[:, 1])))


def of_kind(found: object, kind: str, bench: int | None = None) -> list[object]:
    return [item for item in found.polylines if item.kind == kind and (bench is None or item.bench == bench)]


def dumbbell() -> np.ndarray:
    """Dos cuadrados de 60 m unidos por un cuello de 10 m de ancho (locales): el interior a 10 m de la pared se parte en dos."""
    return np.array([[100.0, 170.0], [160.0, 170.0], [160.0, 195.0], [200.0, 195.0], [200.0, 170.0], [260.0, 170.0], [260.0, 230.0],
                     [200.0, 230.0], [200.0, 205.0], [160.0, 205.0], [160.0, 230.0], [100.0, 230.0]])


class SquareTest(unittest.TestCase):
    """CE-018-04: el límite cuadrado de 200 m sobre un terreno llano a 100 m, ``DESD_10_45_6`` y un ancho mínimo de 30 m."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.found = pit_bench.descend(job())
        cls.by_hand, cls.criterion = pd.limit_benches_by_hand()

    def test_five_benches_and_stop_by_width(self) -> None:
        """RF-018-12, 13: 5 bancos y se detiene porque el siguiente pie (20 m) no contiene un círculo de 30 m; lo dice con su aviso."""
        self.assertEqual(self.criterion, "min_width")
        self.assertEqual(self.found.count, 5)
        self.assertEqual(self.found.stop, pit_model.StopCriterion.FLOOR_WIDTH)
        self.assertEqual(len(self.found.polylines), 10)
        self.assertTrue(self.found.reliable)
        self.assertEqual([item.code for item in self.found.notices], ["des.pit_floor_too_small"])
        values = self.found.notices[0].values
        self.assertEqual(values["bench"], 5)
        self.assertAlmostEqual(values["width"], 20.0, delta=0.01)
        self.assertEqual(values["minimum"], 30.0)

    def test_foot_sides_by_hand(self) -> None:
        """CE-018-04: lados de pie de 180, 148, 116, 84 y 52 m y de cresta de 200, 168, 136, 104 y 72 m, a ≤ 10⁻⁶ m."""
        self.assertEqual([round(item.foot_side_m) for item in self.by_hand], [180, 148, 116, 84, 52])
        for k, bench in enumerate(self.by_hand):
            with self.subTest(bench=k):
                self.assertAlmostEqual(side_of(of_kind(self.found, "foot", k)[0]), bench.foot_side_m, delta=TOL_M)
                self.assertAlmostEqual(side_of(of_kind(self.found, "crest", k)[0]), bench.crest_side_m, delta=TOL_M)

    def test_levels_and_order(self) -> None:
        """RF-018-12: la cresta k a la cota del banco y su pie 10 m más abajo; el pie 4 queda a 50 m (el fondo); el orden es banco, cresta y pie."""
        order = [(item.kind, item.bench) for item in self.found.polylines]
        self.assertEqual(order, [(kind, k) for k in range(5) for kind in ("crest", "foot")])
        for item in self.found.polylines:
            with self.subTest(kind=item.kind, bench=item.bench):
                level = pd.LIMIT_TERRAIN_Z_M - 10.0 * (item.bench + (1 if item.kind == "foot" else 0))
                self.assertTrue(np.all(np.abs(item.vertices[:, 2] - level) <= 1e-9))
                self.assertTrue(item.closed)
                self.assertEqual((item.zone, item.sector, item.part), ("", "", 0))

    def test_floor(self) -> None:
        """RF-018-13: el fondo a 50 m con 52 m de lado (2.704 m²) y 52 m de ancho útil, y el criterio que paró."""
        self.assertEqual(self.found.floor_level_m, pd.LIMIT_FLOOR_Z_M)
        self.assertAlmostEqual(self.found.floor_area_m2, 52.0 * 52.0, delta=1e-3)
        self.assertAlmostEqual(self.found.floor_width_m, 52.0, delta=0.01)

    def test_foot_is_simple_and_inside_the_crest(self) -> None:
        """Cada pie es simple y queda a h/tan α de su cresta (oráculo de fuerza bruta, sin el motor)."""
        square = pd.square_ring(pd.LIMIT_SIDE_M)
        foot = local(of_kind(self.found, "foot", 0)[0])
        self.assertEqual(oracle.crossing_count([foot]), 0)
        gap = oracle.distance_to_ring(foot, square)
        self.assertGreaterEqual(float(gap.min()), 10.0 - 1e-9)

    def test_steps_end_with_the_result(self) -> None:
        """Los pasos ceden ``Progress`` y el último lleva los bancos; ``descend`` da lo mismo, bit a bit."""
        steps = list(pit_bench.descend_steps(job(), budget_s=0.05))
        self.assertGreater(len(steps), 1)
        self.assertTrue(all(step.result is None for step in steps[:-1]))
        last = steps[-1].result
        self.assertEqual(len(last.polylines), 10)
        for one, other in zip(last.polylines, self.found.polylines, strict=True):
            self.assertTrue(np.array_equal(one.vertices, other.vertices))

    def test_volume_of_the_faces(self) -> None:
        """El volumen de las caras sin rejilla de un límite cuadrado: ``h·(A_cresta + A_pie + √(A_cresta·A_pie))/3`` en cada banco, a ≤ 0,1 %
        (las caras son troncos de pirámide: la fórmula de la ley cuadrática es exacta con inglete y aproximada con esquinas redondeadas)."""
        exact = math.fsum(10.0 * (b.crest_side_m ** 2 + b.foot_side_m ** 2 + b.crest_side_m * b.foot_side_m) / 3.0 for b in self.by_hand)
        self.assertAlmostEqual(self.found.face_volume_m3 / exact, 1.0, delta=1e-3)


class StopTest(unittest.TestCase):
    """RF-018-13: el primero de los criterios que se cumpla."""

    def test_bottom_level(self) -> None:
        """CE-018-04: con una cota de fondo de 70 m se detiene a los 3 bancos (pies a 90, 80 y 70 m) por esa cota."""
        found = pit_bench.descend(job(params=params(bottom_level_m=pd.LIMIT_BOTTOM_Z_M)))
        by_hand, criterion = pd.limit_benches_by_hand(bottom_m=pd.LIMIT_BOTTOM_Z_M)
        self.assertEqual((len(by_hand), criterion), (3, "bottom"))
        self.assertEqual(found.count, 3)
        self.assertEqual(found.stop, pit_model.StopCriterion.BOTTOM_LEVEL)
        self.assertEqual(found.floor_level_m, 70.0)
        self.assertAlmostEqual(side_of(of_kind(found, "foot", 2)[0]), 116.0, delta=TOL_M)
        self.assertEqual(found.notices, ())

    def test_bottom_level_between_two_benches(self) -> None:
        """Una cota de fondo que no es de la retícula (75 m): el banco que bajaría de ella no se hace (pies a 90 y 80 m)."""
        found = pit_bench.descend(job(params=params(bottom_level_m=75.0)))
        self.assertEqual((found.count, found.stop), (2, pit_model.StopCriterion.BOTTOM_LEVEL))
        self.assertEqual(found.floor_level_m, 80.0)

    def test_max_benches(self) -> None:
        """El número máximo de bancos: con 2, se detiene en el segundo (el fondo, a 80 m)."""
        found = pit_bench.descend(job(params=params(max_benches=2)))
        self.assertEqual((found.count, found.stop), (2, pit_model.StopCriterion.MAX_BENCHES))
        self.assertEqual(found.floor_level_m, 80.0)

    def test_first_criterion_wins(self) -> None:
        """Con la cota de fondo y el ancho mínimo a la vez, manda el que se cumple antes: aquí la cota (3 bancos, antes que el ancho de 5)."""
        found = pit_bench.descend(job(params=params(bottom_level_m=70.0, max_benches=10)))
        self.assertEqual((found.count, found.stop), (3, pit_model.StopCriterion.BOTTOM_LEVEL))

    def test_a_stop_criterion_is_required(self) -> None:
        """RF-018-13 (D-8): sin ancho mínimo, cota de fondo ni máximo de bancos, el cálculo no tiene con qué parar (error del programa)."""
        with self.assertRaises(ValueError):
            pit_bench.descend(job(params=params(min_floor_width_m=None)))

    def test_ascending_job_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            pit_bench.descend(job(request=request(mode="up", level_field="cota_m"), sources=(limite(level=100.0),)))


class RejectionTest(unittest.TestCase):
    """RF-018-14: lo que se rechaza, con el banco, el ancho que queda, el límite y el lugar."""

    def test_empty_before_the_first_bench(self) -> None:
        """Un límite de 15 m de lado no tiene pie a 10 m de cada lado: se rechaza con el ancho que queda (0 m) y el ancho mínimo."""
        with self.assertRaises(messages.DesignError) as caught:
            pit_bench.descend(job(sources=(limite(pd.square_ring(15.0)),)))
        self.assertEqual(caught.exception.code, "des.pit_empty")
        self.assertEqual(caught.exception.values["bench"], 0)
        self.assertEqual(caught.exception.values["width"], 0.0)
        self.assertEqual(caught.exception.values["limit"], 30.0)
        self.assertIn("limite", caught.exception.text)

    def test_narrower_than_the_minimum_before_the_first_bench(self) -> None:
        """Un límite de 40 m deja un pie de 20 m, menor que el mínimo de 30 m: vacío antes del primer banco, con el ancho que queda (20 m)."""
        with self.assertRaises(messages.DesignError) as caught:
            pit_bench.descend(job(sources=(limite(pd.square_ring(40.0)),)))
        self.assertEqual(caught.exception.code, "des.pit_empty")
        self.assertAlmostEqual(caught.exception.values["width"], 20.0, delta=0.01)

    def test_too_many_benches(self) -> None:
        """Más bancos que el límite de validez: se rechaza (con el límite cambiado a 3 para no hacer 200)."""
        with mock.patch.object(pit_bench, "MAX_BENCHES", 3), self.assertRaises(messages.DesignError) as caught:
            pit_bench.descend(job())
        self.assertEqual(caught.exception.code, "des.pit_too_many_benches")

    def test_too_many_parts(self) -> None:
        """Un interior que se parte en más partes que el límite (cambiado a 1 para la prueba): se rechaza con el banco, el límite y el lugar."""
        with mock.patch.object(pit_bench, "MAX_PARTS", 1), self.assertRaises(messages.DesignError) as caught:
            pit_bench.descend(job(sources=(limite(dumbbell()),), params=params(min_floor_width_m=5.0)))
        self.assertEqual(caught.exception.code, "des.pit_too_many_parts")
        self.assertEqual(caught.exception.values["limit"], 1)
        self.assertEqual(caught.exception.values["count"], 2)

    def test_outside_the_grid(self) -> None:
        """Un límite que sale de la rejilla es un error del programa (la preparación lo rechaza antes, RF-018-04)."""
        with self.assertRaises(ValueError):
            pit_bench.descend(job(sources=(limite(pd.square_ring(500.0)),)))


class PartsTest(unittest.TestCase):
    """RF-018-12: cada parte en que se divide el interior es una polilínea propia."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.found = pit_bench.descend(job(sources=(limite(dumbbell()),), params=params(min_floor_width_m=5.0, max_benches=2)))

    def test_interior_splits_in_two(self) -> None:
        """La mancuerna de cuello 10 m a 10 m de la pared (cara de 10 m) se parte en dos pies, partes 0 y 1; en el banco 1 hay dos crestas."""
        feet = of_kind(self.found, "foot", 0)
        self.assertEqual([item.part for item in feet], [0, 1])
        self.assertEqual([item.part for item in of_kind(self.found, "crest", 0)], [0])
        self.assertEqual([item.part for item in of_kind(self.found, "crest", 1)], [0, 1])
        self.assertEqual([item.part for item in of_kind(self.found, "foot", 1)], [0, 1])
        west, east = (local(item) for item in feet)
        self.assertLess(float(west[:, 0].max()), float(east[:, 0].min()))
        reach = 160.0 - math.sqrt(10.0 ** 2 - 5.0 ** 2)
        # El pie llega a 10 m del vértice de la boca del cuello (160, 195): a 160 − √(10² − 5²) en el eje del cuello.
        self.assertAlmostEqual(float(west[:, 0].min()), 110.0, delta=TOL_M)
        self.assertAlmostEqual(float(west[:, 0].max()), reach, delta=2 * ARC_M)
        self.assertAlmostEqual(float(east[:, 0].max()), 250.0, delta=TOL_M)
        self.assertAlmostEqual(float(east[:, 0].min()), 360.0 - reach, delta=2 * ARC_M)
        self.assertTrue(self.found.reliable)
        for ring in (west, east):
            self.assertEqual(oracle.crossing_count([ring]), 0)

    def test_order_is_by_position(self) -> None:
        """RF-018-25: las partes, ordenadas por su posición (la del oeste primero), no por el orden en que salen del desfase."""
        first, second = of_kind(self.found, "foot", 1)
        self.assertLess(float(first.vertices[:, 0].min()), float(second.vertices[:, 0].min()))

    def test_a_narrow_part_stops_alone(self) -> None:
        """El ancho mínimo se aplica a cada parte: con 45 m, ninguna contiene un círculo de ese diámetro (pies de 40 m) y se rechaza."""
        with self.assertRaises(messages.DesignError) as caught:
            pit_bench.descend(job(sources=(limite(dumbbell()),), params=params(min_floor_width_m=45.0)))
        self.assertEqual(caught.exception.code, "des.pit_empty")


class FirstBenchTest(unittest.TestCase):
    """RF-018-12, H-2: el primer banco de altura variable, desde la primera cota de ancla por debajo del mínimo de la cresta."""

    def test_crest_follows_the_terrain(self) -> None:
        """Terreno inclinado (148 a 152 m bajo el cuadrado de 40 m; ancla en 140 m): la cara es ``(z − 140)/tan 45°``, 8 m al oeste y 12 m
        al este; el pie 0 queda a 140 m y la cresta 0 lleva la cota del terreno en cada vértice (densificada)."""
        square = pd.square_ring(40.0)
        found = pit_bench.descend(job(start=pd.inclined_terrain(pd.GRID), sources=(limite(square),),
                                      params=params(arc_tol_m=pd.HYPOTHESES.arc_m, min_floor_width_m=10.0, max_benches=1)))
        crest, foot = of_kind(found, "crest", 0)[0], of_kind(found, "foot", 0)[0]
        self.assertTrue(np.all(np.abs(foot.vertices[:, 2] - 140.0) <= 1e-9))
        xy = local(foot)
        self.assertAlmostEqual(float(xy[:, 0].min()), 180.0 + 8.0, delta=TOL_M)
        self.assertAlmostEqual(float(xy[:, 0].max()), 220.0 - 12.0, delta=TOL_M)
        cxy = local(crest)
        step = min(pd.GRID.dx, pd.GRID.dy)
        self.assertGreaterEqual(len(cxy), 4 * math.floor(40.0 / step))
        along = np.hypot(*(np.roll(cxy, -1, axis=0) - cxy).T)
        self.assertLessEqual(float(along.max()), step + 1e-9)
        self.assertTrue(np.allclose(crest.vertices[:, 2], 130.0 + 0.1 * cxy[:, 0], atol=1e-9))
        self.assertEqual(found.floor_level_m, 140.0)

    def test_crest_at_a_given_level(self) -> None:
        """Con la cota de la cresta dada (105 m, flat): el ancla es la primera de la retícula por debajo (100 m) y la cara mide 5 m de alto."""
        found = pit_bench.descend(job(sources=(limite(level=105.0),), params=params(max_benches=2)))
        crest, foot = of_kind(found, "crest", 0)[0], of_kind(found, "foot", 0)[0]
        self.assertTrue(np.all(np.abs(crest.vertices[:, 2] - 105.0) <= 1e-9))
        self.assertTrue(np.all(np.abs(foot.vertices[:, 2] - 100.0) <= 1e-9))
        self.assertAlmostEqual(side_of(foot), 200.0 - 2.0 * 5.0, delta=TOL_M)
        self.assertAlmostEqual(side_of(of_kind(found, "crest", 1)[0]), 190.0 - 12.0, delta=TOL_M)

    def test_crest_on_the_lattice_takes_the_next_one_down(self) -> None:
        """Una cresta justo en una cota de la retícula (100 m): el ancla es la de 90 m, el primer banco mide ``h`` (CE-018-04)."""
        found = pit_bench.descend(job(sources=(limite(level=100.0),), params=params(max_benches=1)))
        self.assertTrue(np.all(np.abs(of_kind(found, "foot", 0)[0].vertices[:, 2] - 90.0) <= 1e-9))

    def test_a_first_bench_without_width_is_not_a_rejection(self) -> None:
        """H-2: un primer banco casi sin altura (cresta a 0,4 mm sobre la cota de ancla) no se rechaza: su pie coincide con su cresta."""
        found = pit_bench.descend(job(sources=(limite(level=100.0004),), params=params(max_benches=1)))
        self.assertEqual(found.count, 1)
        self.assertAlmostEqual(side_of(of_kind(found, "foot", 0)[0]), 200.0, delta=0.01)


class DeterminismTest(unittest.TestCase):
    def test_same_inputs_same_bits(self) -> None:
        """RF-018-25: las mismas entradas dan las mismas polilíneas, bit a bit."""
        one, other = pit_bench.descend(job(sources=(limite(dumbbell()),), params=params(min_floor_width_m=5.0))), \
            pit_bench.descend(job(sources=(limite(dumbbell()),), params=params(min_floor_width_m=5.0)))
        self.assertEqual(len(one.polylines), len(other.polylines))
        for a, b in zip(one.polylines, other.polylines, strict=True):
            self.assertEqual((a.kind, a.bench, a.part), (b.kind, b.bench, b.part))
            self.assertTrue(np.array_equal(a.vertices, b.vertices))

    def test_input_is_not_modified(self) -> None:
        """RF-018-01: el límite del usuario no se modifica."""
        source = limite()
        before = source.ring.copy()
        pit_bench.descend(job(sources=(source,)))
        self.assertTrue(np.array_equal(source.ring, before))


if __name__ == "__main__":
    unittest.main()
