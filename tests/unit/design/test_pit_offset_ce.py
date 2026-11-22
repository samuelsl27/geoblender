# SPDX-License-Identifier: GPL-3.0-or-later
"""CE-018-01 y CE-018-02 con el desfase **real** de la corta (spec 018, T09; HU-018-1; RF-018-10; CE-018-01, CE-018-02; plan 018 §7.1).

Mallas pequeñas (un cuadrado de 4 vértices y un círculo de 720), con el oráculo de fuerza bruta de ``tests/support/offset_oracle.py``
(que no usa el motor): la distancia de cada punto del resultado a la fuente, a mano. Las cifras a mano son las de la spec:
``h/tan α`` = 5,7735 m (α = 60°) y 10,0000 m (α = 45°), el pie siguiente a 11,7735 m y el área ``L² + 4·L·d + π·d²`` = 12.414,12 m²
(redondeadas) o ``L² + 4·L·d + 4·d²`` (inglete). La batería aleatoria de 300 polilíneas rugosas (el criterio de robustez del H1) es
``tests/unit/gis/milestone_offset_robustness.py``, del paso «hito»."""

from __future__ import annotations

import dataclasses
import math
import unittest

import numpy as np

from tests.support import offset_oracle as oracle
from tests.support import pit_data as pd
from tests.support.package import import_geoblender

pit_offset = import_geoblender("design.pit_offset")
pit_model = import_geoblender("design.pit_model")
pit_rose = import_geoblender("design.pit_rose")
model = import_geoblender("design.model")

ARC_M = pd.HYPOTHESES.arc_hand_m
"""La tolerancia de arco de las cifras a mano (D-14: HIPÓTESIS)."""
ARC_WIDE_M = pd.HYPOTHESES.arc_m
ROSE = tuple(pit_rose.RoseRange(r.from_deg, r.to_deg, r.face_deg, r.berm_m) for r in pd.ROSE_TWO_RANGES)
UP = 1
FACE_M = 10.0 / math.tan(math.radians(60.0))
"""h/tan α = 5,7735 m."""


def profile(**changes: object) -> object:
    return model.BenchProfile(**{**dataclasses.asdict(pd.EXPL), **changes})


def offset(ring: np.ndarray, **kwargs: object) -> object:
    """El último ``Progress.result`` de ``offset_polyline_steps`` (un ``PolylineOffset``): su ``.result`` es el del motor."""
    last = None
    for step in pit_offset.offset_polyline_steps(ring, **kwargs):
        last = step.result
    assert last is not None
    return last


class SquareReferenceTest(unittest.TestCase):
    """CE-018-01: el cuadrado de 100 m con ``EXPL_10_60_6``."""

    def test_ce_018_01_crest_at_h_over_tan_alpha_with_rounded_corners(self) -> None:
        """CE-018-01: la cresta a 5,7735 m del pie, con esquinas redondeadas; el área es L² + 4·L·d + π·d² = 12.414,12 m² dentro de la
        tolerancia de arco por el perímetro; el resultado es simple y ningún punto está más cerca del pie que d."""
        square = pd.square_ring(pd.SQUARE_SIDE_M)
        found = offset(square, step="face", side=UP, tol=ARC_M, profile=profile())
        result = found.result
        self.assertTrue(result.verified, (result.defect, result.max_defect_m))
        self.assertEqual((len(result.rings), len(result.holes)), (1, 0))
        crest = result.rings[0]
        self.assertEqual(oracle.crossing_count([crest]), 0)
        gap = oracle.distance_to_ring(crest, square)
        self.assertGreaterEqual(float(gap.min()), FACE_M - 1e-9)
        self.assertLessEqual(float(gap.max()), FACE_M + ARC_M + 1e-9)
        exact = pd.square_crest_area_by_hand(pd.SQUARE_SIDE_M, FACE_M, rounded=True)
        self.assertAlmostEqual(exact, 12414.12, delta=0.01)
        perimeter = float(np.hypot(*(np.roll(crest, -1, axis=0) - crest).T).sum())
        area = oracle.signed_area(crest)
        self.assertGreaterEqual(area, exact - 1e-6)  # arcos circunscritos: solo por fuera
        self.assertLessEqual(area, exact + ARC_M * perimeter)

    def test_ce_018_01_next_foot_at_advance_and_miter_area(self) -> None:
        """CE-018-01: el pie siguiente a 11,7735 m del pie (cara y berma); con esquinas a inglete, el área es L² + 4·L·d + 4·d²."""
        square = pd.square_ring(pd.SQUARE_SIDE_M)
        crest = offset(square, step="face", side=UP, tol=ARC_M, profile=profile()).result.rings[0]
        foot = offset(crest, step="berm", side=UP, tol=ARC_M, profile=profile()).result
        self.assertTrue(foot.verified)
        gap = oracle.distance_to_ring(foot.rings[0], square)
        advance = FACE_M + 6.0
        self.assertAlmostEqual(advance, 11.7735, places=4)
        self.assertGreaterEqual(float(gap.min()), advance - 1e-9)
        self.assertLessEqual(float(gap.max()), advance + 2.0 * ARC_M + 1e-9)
        mitre = offset(square, step="face", side=UP, tol=ARC_M, corner="miter", profile=profile()).result
        self.assertTrue(mitre.verified)
        self.assertAlmostEqual(oracle.signed_area(mitre.rings[0]),
                               pd.square_crest_area_by_hand(pd.SQUARE_SIDE_M, FACE_M, rounded=False), delta=1e-6)
        self.assertEqual(oracle.crossing_count(mitre.rings), 0)


class RoseReferenceTest(unittest.TestCase):
    """CE-018-02: el fondo circular de 50 m con la roseta de dos rangos."""

    def test_ce_018_02_crest_distance_by_azimuth_without_gaps(self) -> None:
        """CE-018-02: cresta a 5,7735 m del pie donde la cara tiene azimut 90° (oeste) y a 10,0000 m donde tiene 270° (este), a ≤ la
        tolerancia de arco, **sin huecos entre rangos** (un anillo, simple, verificado) y sin una cara más empinada que su α (ningún
        punto más cerca que h/tan α de su rango, y el más lejano a lo más 10 m + arco)."""
        ring = pd.circle_ring()
        result = offset(ring, step="face", side=UP, tol=ARC_WIDE_M, profile=profile(), rose=ROSE,
                        az_window_m=pd.HYPOTHESES.az_window_m).result
        self.assertTrue(result.verified, (result.defect, result.max_defect_m))
        self.assertEqual((len(result.rings), len(result.holes)), (1, 0))
        crest = result.rings[0]
        self.assertEqual(oracle.crossing_count([crest]), 0)
        gap = oracle.distance_to_ring(crest, ring)
        local = crest - np.array(pd.CENTER)
        west = (local[:, 0] < 0.0) & (np.abs(local[:, 1]) < 1.0)
        east = (local[:, 0] > 0.0) & (np.abs(local[:, 1]) < 1.0)
        self.assertTrue(west.any() and east.any())
        want_west = pd.rose_distance_by_hand(pd.ROSE_TWO_RANGES, 90.0)
        want_east = pd.rose_distance_by_hand(pd.ROSE_TWO_RANGES, 270.0)
        self.assertAlmostEqual(want_west, 5.7735, places=4)
        self.assertAlmostEqual(want_east, 10.0000, places=4)
        self.assertTrue(np.all(np.abs(gap[west] - want_west) <= ARC_WIDE_M + 1e-6), gap[west])
        self.assertTrue(np.all(np.abs(gap[east] - want_east) <= ARC_WIDE_M + 1e-6), gap[east])
        self.assertGreaterEqual(float(gap.min()), want_west - 1e-9)
        self.assertLessEqual(float(gap.max()), want_east + ARC_WIDE_M + 1e-9)

    def test_ce_018_02_n_berms_advance_between_berms(self) -> None:
        """CE-018-02: con n = 2 en un sector, la cara avanza 2·h/tan α y, con la berma, el avance entre bermas es 2·h/tan α + B."""
        ring = pd.circle_ring()
        box = np.array([[0.0, 0.0], [400.0, 0.0], [400.0, 400.0], [0.0, 400.0]])
        sector = pit_model.PitSector("W", "Oeste", ((box,),), n_berm=2)
        crest = offset(ring, step="face", side=UP, tol=ARC_M, profile=profile(), sectors=(sector,)).result
        foot = offset(crest.rings[0], step="berm", side=UP, tol=ARC_M, profile=profile(), sectors=(sector,)).result
        self.assertTrue(crest.verified and foot.verified)
        advance = pit_rose.advance_m(10.0, 60.0, 6.0, 2)
        self.assertAlmostEqual(advance, 2.0 * FACE_M + 6.0, places=9)
        face_gap = oracle.distance_to_ring(crest.rings[0], ring)
        foot_gap = oracle.distance_to_ring(foot.rings[0], ring)
        self.assertAlmostEqual(float(face_gap.min()), 2.0 * FACE_M, delta=ARC_M + 0.01)
        self.assertAlmostEqual(float(foot_gap.min()), advance, delta=2.0 * ARC_M + 0.01)

    def test_ce_018_02_two_sectors_with_different_profile_leave_no_gap(self) -> None:
        """CE-018-02: con dos sectores de perfil distinto, el resultado no tiene huecos en su borde (un anillo, simple, verificado) y cada
        lado queda a la distancia de su perfil (5,7735 m con 60° al oeste de x = 200; 10,0000 m con 45° al este)."""
        ring = pd.circle_ring()
        west_box = np.array([[0.0, 0.0], [200.0, 0.0], [200.0, 400.0], [0.0, 400.0]])
        east_box = np.array([[200.0, 0.0], [400.0, 0.0], [400.0, 400.0], [200.0, 400.0]])
        west = pit_model.PitSector("W", "Oeste", ((west_box,),), profile=profile(code="p60", name="P60"))
        east = pit_model.PitSector("E", "Este", ((east_box,),), profile=profile(code="p45", name="P45", face_deg=45.0))
        result = offset(ring, step="face", side=UP, tol=ARC_WIDE_M, profile=None, sectors=(west, east)).result
        self.assertTrue(result.verified, (result.defect, result.max_defect_m))
        self.assertEqual((len(result.rings), len(result.holes)), (1, 0))
        self.assertEqual(oracle.crossing_count(result.rings), 0)
        crest = result.rings[0]
        gap = oracle.distance_to_ring(crest, ring)
        near_west = (np.abs(crest[:, 1] - pd.CENTER[1]) < 1.0) & (crest[:, 0] < pd.CENTER[0] - 40.0)
        near_east = (np.abs(crest[:, 1] - pd.CENTER[1]) < 1.0) & (crest[:, 0] > pd.CENTER[0] + 40.0)
        self.assertTrue(near_west.any() and near_east.any())
        self.assertTrue(np.all(np.abs(gap[near_west] - FACE_M) <= ARC_WIDE_M + 1e-6))
        self.assertTrue(np.all(np.abs(gap[near_east] - 10.0) <= ARC_WIDE_M + 1e-6))


if __name__ == "__main__":
    unittest.main()
