# SPDX-License-Identifier: GPL-3.0-or-later
"""La distancia por arista de la corta y su desfase (spec 018, T08; RF-018-06, 08, 09, 10, 12; plan 018 §5.4 A2, P-4, P-5, H-2).

Las cifras a mano son las de CE-018-02 (h/tan α = 5,7735 m con α = 60° y 10,0000 m con α = 45°) y de las fórmulas de RF-018-08 y
RF-018-12, a ≤ 1e-9 m; el desfase real se comprueba con la verificación del motor."""

from __future__ import annotations

import dataclasses
import math
import unittest

import numpy as np

from tests.support import pit_data as pd
from tests.support.package import import_geoblender

pit_offset = import_geoblender("design.pit_offset")
pit_model = import_geoblender("design.pit_model")
pit_rose = import_geoblender("design.pit_rose")
model = import_geoblender("design.model")

TOL = 0.05
EXACT = 1e-9
ROSE = tuple(pit_rose.RoseRange(r.from_deg, r.to_deg, r.face_deg, r.berm_m) for r in pd.ROSE_TWO_RANGES)
UP, DOWN = 1, -1


def bench_profile(**changes: object) -> object:
    return model.BenchProfile(**{**dataclasses.asdict(pd.EXPL), **changes})


def square_sector(code: str, x0: float, x1: float, **changes: object) -> object:
    ring = np.array([[x0, 0.0], [x1, 0.0], [x1, 400.0], [x0, 400.0]])
    return pit_model.PitSector(code, f"Sector {code}", ((ring,),), **changes)


def tan(deg: float) -> float:
    return math.tan(math.radians(deg))


def _run(ring: object, **kwargs: object) -> object:
    result = None
    for step in pit_offset.offset_polyline_steps(ring, **kwargs):
        result = step.result
    assert result is not None
    return result


class RoseTest(unittest.TestCase):
    def test_ce_018_02_rose_distances_by_hand(self) -> None:
        """RF-018-07, RF-018-10; CE-018-02: 5,7735 m donde la cara tiene azimut 90° (oeste) y 10,0000 m en 270° (este)."""
        ring = pd.circle_ring()
        found = pit_offset.edge_distances(ring, step="face", side=UP, profile=bench_profile(), rose=ROSE)
        centre = np.array(pd.CENTER)
        mid = 0.5 * (found.ring + np.roll(found.ring, -1, axis=0)) - centre
        angle = np.degrees(np.arctan2(mid[:, 1], mid[:, 0])) % 360.0
        west = np.abs(angle - 180.0) < 60.0
        east = (angle < 60.0) | (angle > 300.0)
        self.assertTrue(west.any() and east.any())
        np.testing.assert_allclose(found.distance[west], 10.0 / tan(60.0), atol=EXACT)
        np.testing.assert_allclose(found.distance[east], 10.0 / tan(45.0), atol=EXACT)
        self.assertAlmostEqual(pd.rose_distance_by_hand(pd.ROSE_TWO_RANGES, 90.0), 5.7735, places=4)
        near_west = np.abs(angle - 180.0) < 30.0
        np.testing.assert_allclose(found.azimuth_deg[near_west], 90.0, atol=31.0)

    def test_descending_face_azimuth_is_the_same_inward_direction(self) -> None:
        """RF-018-07: ascendente (contraria a la normal de desfase) y descendente (la misma) dan la cara hacia dentro."""
        ring = pd.circle_ring()
        np.testing.assert_allclose(pit_offset.face_azimuth(ring, UP), pit_offset.face_azimuth(ring, DOWN), atol=1e-9)

    def test_real_offset_has_no_gap_and_no_steeper_face(self) -> None:
        """RF-018-10; CE-018-02: el desfase real es un anillo verificado, sin huecos entre rangos y sin cara más empinada que su α."""
        ring = pd.circle_ring()
        apothem = pd.CIRCLE_RADIUS_M * math.cos(math.pi / pd.CIRCLE_VERTICES)
        for window in (None, pd.HYPOTHESES.az_window_m):
            outcome = _run(ring, step="face", side=UP, tol=TOL, profile=bench_profile(), rose=ROSE, az_window_m=window)
            result = outcome.result
            self.assertTrue(result.verified, (window, result.defect, result.max_defect_m))
            self.assertEqual((len(result.rings), len(result.holes)), (1, 0))
            out = result.rings[0] - np.array(pd.CENTER)
            radius = np.hypot(out[:, 0], out[:, 1])
            west = np.flatnonzero((out[:, 0] < 0) & (np.abs(out[:, 1]) < 1.0))
            east = np.flatnonzero((out[:, 0] > 0) & (np.abs(out[:, 1]) < 1.0))
            self.assertAlmostEqual(float(radius[west].mean()) - apothem, 10.0 / tan(60.0), delta=TOL + 0.02)
            self.assertAlmostEqual(float(radius[east].mean()) - apothem, 10.0 / tan(45.0), delta=TOL + 0.02)
            # la cara más empinada es la de 60°: ningún vértice queda más cerca que su h/tan α menos el arco
            self.assertGreaterEqual(float(radius.min()) - apothem, 10.0 / tan(60.0) - TOL - 1e-6)


class SectorTest(unittest.TestCase):
    def test_two_sectors_split_the_edges_and_leave_no_gap(self) -> None:
        """RF-018-06, RF-018-09: dos sectores de perfil distinto parten las aristas en su límite y el resultado es un anillo sin huecos."""
        ring = pd.square_ring(100.0)  # x de 150 a 250; límite en x = 200
        left = square_sector("W", 0.0, 200.0, profile=bench_profile(code="p60", name="P60"))
        right = square_sector("E", 200.0, 400.0, profile=bench_profile(code="p45", name="P45", face_deg=45.0))
        found = pit_offset.edge_distances(ring, step="face", side=UP, profile=None, sectors=(right, left))
        self.assertEqual(len(found.ring), 6)  # dos aristas partidas por el límite
        mid = 0.5 * (found.ring + np.roll(found.ring, -1, axis=0))
        for edge in range(6):
            west = mid[edge, 0] < 200.0
            want = 10.0 / tan(60.0) if west else 10.0 / tan(45.0)
            self.assertAlmostEqual(float(found.distance[edge]), want, delta=EXACT)
            self.assertEqual(found.label_of(edge), "W" if west else "E")
        self.assertEqual(set(found.source_edge.tolist()), {0, 1, 2, 3})
        outcome = _run(ring, step="face", side=UP, tol=TOL, profile=None, sectors=(left, right))
        self.assertTrue(outcome.result.verified)
        self.assertEqual((len(outcome.result.rings), len(outcome.result.holes)), (1, 0))
        labels = {outcome.sector_labels[i] for i in np.concatenate(outcome.sector_of_vertex)}
        self.assertEqual(labels, {"W", "E"})

    def test_base_profile_where_there_is_no_sector_and_perimeter_last(self) -> None:
        """RF-018-06, RF-018-09: lo que no está en un sector lleva el perfil base; el perímetro (código vacío) manda el último."""
        ring = pd.square_ring(100.0)
        east = square_sector("E", 200.0, 400.0, profile=bench_profile(code="p45", name="P45", face_deg=45.0))
        perimeter = square_sector("", 0.0, 400.0, profile=bench_profile(code="p30", name="P30", face_deg=30.0))
        found = pit_offset.edge_distances(ring, step="face", side=UP, profile=bench_profile(), sectors=(perimeter, east))
        mid = 0.5 * (found.ring + np.roll(found.ring, -1, axis=0))
        want = np.where(mid[:, 0] < 200.0, 10.0 / tan(30.0), 10.0 / tan(45.0))
        np.testing.assert_allclose(found.distance, want, atol=EXACT)
        bare = pit_offset.edge_distances(ring, step="face", side=UP, profile=bench_profile(), sectors=(east,))
        np.testing.assert_allclose(bare.distance, np.where(mid[:, 0] < 200.0, 10.0 / tan(60.0), 10.0 / tan(45.0)), atol=EXACT)

    def test_sector_without_any_profile_is_a_program_error(self) -> None:
        ring = pd.square_ring(100.0)
        with self.assertRaises(ValueError):
            pit_offset.edge_distances(ring, step="face", side=UP, profile=None)


class BermsTest(unittest.TestCase):
    def test_n_berms_advance(self) -> None:
        """RF-018-08; CE-018-02: con n = 2 la cara mide 2·h/tan α y el avance entre bermas, 2·h/tan α + B."""
        ring = pd.square_ring(100.0)
        sector = square_sector("W", 0.0, 400.0, n_berm=2)
        face = pit_offset.edge_distances(ring, step="face", side=UP, profile=bench_profile(), sectors=(sector,))
        berm = pit_offset.edge_distances(ring, step="berm", side=UP, profile=bench_profile(), sectors=(sector,))
        advance = pit_rose.advance_m(10.0, 60.0, 6.0, 2)
        np.testing.assert_allclose(face.distance, 2.0 * 10.0 / tan(60.0), atol=EXACT)
        np.testing.assert_allclose(berm.distance, 6.0, atol=EXACT)
        np.testing.assert_allclose(face.distance + berm.distance, advance, atol=EXACT)
        np.testing.assert_array_equal(face.n_berm, 2)
        one = pit_offset.edge_distances(ring, step="face", side=UP, profile=bench_profile(), n_berm=1)
        np.testing.assert_allclose(one.distance, 10.0 / tan(60.0), atol=EXACT)

    def test_rose_berm_by_range(self) -> None:
        """RF-018-07: la berma de cada rango de la roseta."""
        rose = (pit_rose.RoseRange(0.0, 180.0, 60.0, 6.0), pit_rose.RoseRange(180.0, 360.0, 45.0, 9.0))
        found = pit_offset.edge_distances(pd.circle_ring(), step="berm", side=UP, profile=bench_profile(), rose=rose)
        self.assertEqual(set(np.round(found.distance, 9).tolist()), {6.0, 9.0})


class FirstBenchTest(unittest.TestCase):
    def test_variable_height_first_bench(self) -> None:
        """RF-018-12, H-2: la distancia de cada arista es (z − z_ancla)/tan α con la z media de sus extremos."""
        ring = pd.square_ring(100.0)
        z = np.array([131.0, 133.0, 137.0, 135.0])
        found = pit_offset.edge_distances(ring, step="face", side=DOWN, profile=bench_profile(), z_m=z, anchor_m=130.0)
        mean = 0.5 * (z + np.roll(z, -1))
        np.testing.assert_allclose(found.distance, (mean - 130.0) / tan(60.0), atol=EXACT)

    def test_variable_height_interpolates_at_the_cuts(self) -> None:
        """RF-018-12: en un corte de sector la cota se interpola en la arista."""
        ring = pd.square_ring(100.0)
        z = np.array([130.0, 130.0, 140.0, 140.0])
        sector = square_sector("E", 200.0, 400.0)
        found = pit_offset.edge_distances(ring, step="face", side=DOWN, profile=bench_profile(), z_m=z, anchor_m=130.0,
                                          sectors=(sector,))
        self.assertEqual(len(found.ring), 6)
        pieces = [i for i in range(6) if found.source_edge[i] == 2]
        self.assertEqual(len(pieces), 2)
        np.testing.assert_allclose(found.distance[pieces], 10.0 / tan(60.0), atol=EXACT)

    def test_variable_height_rejects_inconsistent_input(self) -> None:
        """RF-018-12: las cotas y el ancla van juntas, solo en la cara, y el ancla no queda por encima de la cresta."""
        ring = pd.square_ring(100.0)
        z = np.array([131.0, 133.0, 137.0, 135.0])
        for kwargs in ({"z_m": z}, {"anchor_m": 130.0}, {"z_m": z, "anchor_m": 136.0}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                pit_offset.edge_distances(ring, step="face", side=DOWN, profile=bench_profile(), **kwargs)
        with self.assertRaises(ValueError):
            pit_offset.edge_distances(ring, step="berm", side=DOWN, profile=bench_profile(), z_m=z, anchor_m=130.0)


class ExtraTest(unittest.TestCase):
    def test_ramp_term_is_added_and_follows_the_cuts(self) -> None:
        """A2: el término de la rampa se suma a la distancia de la arista y viaja con sus trozos."""
        ring = pd.square_ring(100.0)
        extra = np.array([0.0, 4.0, 0.0, 0.0])
        sector = square_sector("E", 200.0, 400.0)
        found = pit_offset.edge_distances(ring, step="face", side=UP, profile=bench_profile(), extra_m=extra, sectors=(sector,))
        np.testing.assert_allclose(found.distance, 10.0 / tan(60.0) + extra[found.source_edge], atol=EXACT)
        with self.assertRaises(ValueError):
            pit_offset.edge_distances(ring, step="face", side=UP, profile=bench_profile(), extra_m=-extra - 1.0)


class SmoothTest(unittest.TestCase):
    def test_smoothing_calms_a_rough_line(self) -> None:
        """P-5: sin suavizar, una línea rugosa alterna de rango en cada vértice; suavizada, cambia de rango pocas veces."""
        rose = (pit_rose.RoseRange(0.0, 90.0, 60.0, 6.0), pit_rose.RoseRange(90.0, 360.0, 45.0, 6.0))
        ring = pd.rough_ring(7, 400, 0.4, radius_m=60.0)
        raw = pit_offset.edge_distances(ring, step="face", side=UP, profile=bench_profile(), rose=rose)
        smooth = pit_offset.edge_distances(ring, step="face", side=UP, profile=bench_profile(), rose=rose, az_window_m=12.0)

        def changes(d: np.ndarray) -> int:
            return int(np.count_nonzero(np.abs(d - np.roll(d, 1)) > 1e-6))

        self.assertGreater(changes(raw.distance), changes(smooth.distance))
        self.assertLessEqual(changes(smooth.distance), 4)

    def test_window_shorter_than_an_edge_is_the_edge_azimuth(self) -> None:
        """P-5: una ventana dentro de una arista da el azimut de la arista."""
        ring = pd.square_ring(100.0)
        np.testing.assert_allclose(pit_offset.smooth_azimuth(ring, UP, 5.0), pit_offset.face_azimuth(ring, UP), atol=1e-9)

    def test_window_as_long_as_the_perimeter_falls_back(self) -> None:
        """P-5: una ventana de todo el perímetro (media nula) cae al azimut propio; una negativa se rechaza."""
        ring = pd.square_ring(100.0)
        np.testing.assert_allclose(pit_offset.smooth_azimuth(ring, UP, 400.0), pit_offset.face_azimuth(ring, UP), atol=1e-9)
        with self.assertRaises(ValueError):
            pit_offset.smooth_azimuth(ring, UP, -1.0)

    def test_window_reaching_a_corner_averages_the_faces(self) -> None:
        """P-5: la ventana que llega a la esquina mezcla las dos caras."""
        ring = pd.square_ring(100.0)
        raw = pit_offset.face_azimuth(ring, UP)
        np.testing.assert_allclose(pit_offset.smooth_azimuth(ring, UP, 20.0), raw, atol=1e-9)
        triangle = np.array([[0.0, 0.0], [100.0, 0.0], [0.0, 100.0]])  # sin simetría: las dos vecinas no se anulan
        self.assertFalse(np.allclose(pit_offset.smooth_azimuth(triangle, UP, 120.0), pit_offset.face_azimuth(triangle, UP), atol=1.0))


class InputTest(unittest.TestCase):
    def test_bad_rings_and_arguments(self) -> None:
        """Errores del programa: anillo horario, con arista de longitud 0, paso, lado o n inválidos."""
        ring = pd.square_ring(100.0)
        with self.assertRaises(ValueError):
            pit_offset.edge_distances(ring[::-1], step="face", profile=bench_profile())
        with self.assertRaises(ValueError):
            pit_offset.edge_distances(np.vstack([ring, ring[:1]]), step="face", profile=bench_profile())
        with self.assertRaises(ValueError):
            pit_offset.edge_distances(ring, step="roof", profile=bench_profile())
        with self.assertRaises(ValueError):
            pit_offset.edge_distances(ring, step="face", profile=bench_profile(), n_berm=0)
        with self.assertRaises(ValueError):
            pit_offset.edge_distances(ring, step="face", side=0, profile=bench_profile())

    def test_the_input_ring_is_not_modified_and_results_are_read_only(self) -> None:
        """RF-018-01: la entrada no se modifica."""
        ring = pd.circle_ring()
        before = ring.copy()
        found = pit_offset.edge_distances(ring, step="face", profile=bench_profile(), rose=ROSE, az_window_m=12.0)
        np.testing.assert_array_equal(ring, before)
        self.assertFalse(found.distance.flags.writeable)

    def test_polyline_offset_yields_progress_and_keeps_the_zone(self) -> None:
        """RF-018-09: el desfase de una polilínea da su zona y su sector por vértice."""
        steps = list(pit_offset.offset_polyline_steps(pd.circle_ring(), step="berm", side=DOWN, tol=TOL,
                                                      profile=bench_profile(), zone="Z1"))
        self.assertTrue(all(step.result is None for step in steps[:-1]))
        last = steps[-1].result
        self.assertEqual(last.zone, "Z1")
        self.assertTrue(last.result.verified)
        self.assertEqual(len(last.sector_of_vertex), len(last.result.rings) + len(last.result.holes))


if __name__ == "__main__":
    unittest.main()
