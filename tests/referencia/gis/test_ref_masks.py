# SPDX-License-Identifier: GPL-3.0-or-later
"""Máscaras de referencia de las restricciones (spec 012, T08; CE-012-01; RF-012-11, RF-012-12;
plan 012 §2.2, A1, A2 y D-1; constitución, principio 2).

**CE-012-01**: un cuadrado de 100 m alineado con la rejilla y otro desplazado media celda, con
resguardo de 8 m; un punto en una esquina de celda y otro en un centro, con 8 m; una línea de
100 m sobre una línea de la rejilla, con 8 m; y un límite con 10 m hacia dentro, con celdas de 1 y
2 m. El número de celdas de cada zona es **exactamente** el del recuento a mano de
``tests.support.constraints_fixtures`` (13.424, 13.641, 224, 241, 1.824 y el núcleo de 6.400 con
1 m; 3.360, 3.469, 60, 69, 460 y 1.600 con 2 m; las enteras dentro del límite, 10.000 y 2.500, y
su banda, 3.600 y 900), y el área de los polígonos, la exacta (10.000 m², error relativo
≤ 10⁻⁹), por la fracción exacta de cada celda.
"""

import unittest
from datetime import date

from tests.support import constraints_fixtures as fx
from tests.support.package import import_geoblender

model = import_geoblender("core.constraints.model")
zones = import_geoblender("gis.masks.zones")

EXACT = 1e-9  # error relativo de las áreas (CE-012-01)
KINDS = {"POLYGON": model.GeometryKind.POLYGON, "LINESTRING": model.GeometryKind.LINE,
         "POINT": model.GeometryKind.POINT}


def _constraint(case: fx.MaskCase):
    kind = KINDS[case.geometry_type]
    if kind is model.GeometryKind.POLYGON:
        parts = (tuple(case.coords),)
    elif kind is model.GeometryKind.LINE:
        parts = ((case.coords,),)
    else:
        parts = ((case.coords.reshape(1, 2),),)
    return model.Constraint(
        uid="c" * 32, code=f"r_{case.key}", name=case.name, ctype=None, kind=kind, parts=parts,
        priority=1, reason=None, decided_by=None, decided_on=date(2026, 10, 28),
        decision_uid=None, intention_uid=None, source_input=None, source_fid=None,
        layer="core_constraint_polygon", fid=1)


class MaskReferenceTest(unittest.TestCase):
    """CE-012-01 (RF-012-12): los recuentos a mano y las áreas exactas."""

    def test_hand_counts(self) -> None:
        for step in fx.MASK_STEPS:
            for case in fx.mask_cases(step):
                with self.subTest(step=step, case=case.key):
                    item = _constraint(case)
                    if case.is_limit:
                        limit = zones.limit_runs(zones.edges_of(item, case.grid), case.grid,
                                                 case.inward_m)
                        self.assertEqual(limit.inside.cells, case.inside_cells)
                        self.assertEqual(limit.band.cells, case.band_cells)
                        self.assertEqual(limit.core.cells, case.cells)
                    else:
                        runs = zones.zone_runs(item, case.grid, case.outward_m)
                        self.assertEqual(runs.cells, case.cells)
                        self.assertEqual(runs.area(case.grid),
                                         case.cells * case.grid.cell_area)

    def test_polygon_areas_are_exact(self) -> None:
        for step in fx.MASK_STEPS:
            for case in fx.mask_cases(step):
                if case.area_m2 is None:
                    continue
                with self.subTest(step=step, case=case.key):
                    edges = zones.edges_of(_constraint(case), case.grid)
                    area = zones.area_inside(edges, case.grid)
                    self.assertLessEqual(abs(area - case.area_m2), EXACT * case.area_m2)


if __name__ == "__main__":
    unittest.main()
