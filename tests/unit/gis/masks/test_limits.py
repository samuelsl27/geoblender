# SPDX-License-Identifier: GPL-3.0-or-later
"""Los límites declarados ahora y su informe (spec 012, T22; HU-012-1; RF-012-04, RF-012-05,
RF-012-15; plan 012 §5.5, A4, D-12, D-14).

Sobre el proyecto de ``tests.support.constraints_project`` (una copia por clase), con el límite
legal «Concesión» (10 m hacia dentro) y el perímetro de actuación con su lóbulo (CE-012-03):

- **RF-012-05**: ``declared_limits`` da el informe de los límites declarados en una versión (o en
  el proyecto) con la superposición exacta: el área del límite legal, del perímetro, de su
  intersección y de la franja con su parte (área y centro absoluto), con error relativo ≤ 10⁻⁹
  frente a las áreas a mano de ``tests.support.constraints_fixtures`` (4 ha, 3,44 ha, 2,76 ha y
  0,68 ha); lo que cada versión tiene activo lo decide su «activa» (D-4): con el perímetro
  desactivado en V02 el límite legal hace de perímetro (D-14) y V01 no cambia; sin límite legal
  activo no hay informe.
- **RF-012-15**: lo que queda fuera de la rejilla de un límite se nombra con su área exacta (un
  límite que se sale de la ventana de trabajo).
- **RF-012-04**: un límite con la geometría no válida (se corta a sí mismo) se lista como
  problema y no da informe; no se escribe nada.
- **RNF-012-06**: por pasos, uno por lectura, comprobación, límite y superposición.
"""

from __future__ import annotations

import unittest
from datetime import date
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as fx
from tests.support import constraints_project as cp
from tests.support.package import import_geoblender

store = import_geoblender("gis.masks.store")
cparams = import_geoblender("core.constraints.params")
cmodel = import_geoblender("core.constraints.model")
combine = import_geoblender("gis.masks.combine")

T = cmodel.ConstraintType
G = cmodel.GeometryKind
REL = 1e-9
STEP_MAX_S = 0.05


def _close(value: float, wanted: float) -> bool:
    return abs(value - wanted) <= REL * max(abs(wanted), 1.0)


class DeclaredLimitsTest(cp.ConstraintsProjectCase):
    """El informe de los límites del sitio y lo que cambia por versión."""

    def declared(self, version: Any = None) -> Any:
        return store.declared_limits(self.project, version=None if version is None
                                     else version.uid)

    def test_a_report_of_the_site_matches_the_exact_areas(self) -> None:
        """RF-012-05, CE-012-03: el límite legal (4 ha), el perímetro (34.400 m²), su
        intersección (27.600 m²) y la franja de 0,68 ha en una parte con su centro absoluto,
        con error relativo ≤ 10⁻⁹; el resguardo hacia dentro y los límites que lo dan."""
        found = self.declared(self.v1)
        wanted = fx.limits()
        self.assertEqual([item.code for item in found.legal], ["concesion"])
        self.assertEqual([item.code for item in found.perimeter], ["perimetro"])
        self.assertEqual((found.inactive, found.problems), ((), ()))
        self.assertEqual(found.version_uid, self.v1.uid)
        self.assertEqual(found.inward_m, cp.LEGAL_INWARD_M)
        report = found.report
        self.assertIsNotNone(report)
        self.assertTrue(_close(report.legal_m2, wanted.legal_area_m2), report.legal_m2)
        self.assertTrue(_close(report.perimeter_m2, wanted.perimeter_area_m2))
        self.assertTrue(_close(report.intersection_m2, wanted.intersection_m2))
        self.assertTrue(_close(report.strip_m2, wanted.strip_m2))
        self.assertTrue(_close(report.strip_ha, 0.68), report.strip_ha)
        self.assertFalse(report.perimeter_from_legal)
        self.assertEqual(report.outside, ())
        (part,) = report.strip_parts
        (want,) = wanted.strip_parts
        self.assertTrue(_close(part.area_m2, want.area_m2))
        self.assertAlmostEqual(part.centroid[0], want.center[0], places=6)
        self.assertAlmostEqual(part.centroid[1], want.center[1], places=6)
        # Sin versión, los valores del proyecto: lo mismo.
        project_wide = self.declared()
        self.assertIsNone(project_wide.version_uid)
        self.assertTrue(_close(project_wide.report.strip_m2, wanted.strip_m2))

    def test_b_a_version_decides_what_is_active(self) -> None:
        """RF-012-05, D-4, D-14: con el perímetro desactivado solo en V02, ahí el límite legal
        hace de perímetro (sin franja) y queda listado como inactivo; V01 y el proyecto no
        cambian; sin límite legal activo en V02 no hay informe."""
        wanted = fx.limits()
        cp.declare(self.project, self.clock, {cparams.active_key("perimetro"): False},
                   version=self.v2)
        second = self.declared(self.v2)
        self.assertEqual(second.perimeter, ())
        self.assertEqual([item.code for item in second.inactive], ["perimetro"])
        report = second.report
        self.assertTrue(report.perimeter_from_legal)
        self.assertEqual((report.strip_m2, report.strip_parts), (0.0, ()))
        self.assertTrue(_close(report.perimeter_m2, wanted.legal_area_m2))
        self.assertTrue(_close(self.declared(self.v1).report.strip_m2, wanted.strip_m2))
        self.assertTrue(_close(self.declared().report.strip_m2, wanted.strip_m2))

        cp.declare(self.project, self.clock, {cparams.active_key("concesion"): False},
                   version=self.v2)
        none = self.declared(self.v2)
        self.assertEqual((none.legal, none.report), ((), None))
        self.assertEqual(sorted(item.code for item in none.inactive), ["concesion", "perimetro"])
        self.assertTrue(self.declared(self.v1).legal)

    def test_c_it_reads_in_short_steps_and_writes_nothing(self) -> None:
        """RNF-012-06: ``declared_limits_steps`` cede el control varias veces (lectura,
        comprobación, límites y superposiciones) con el mismo resultado que de una vez, y no
        escribe nada en el proyecto."""
        before = self.query("SELECT count(*) FROM gb_operation")
        steps = 0
        generator = store.declared_limits_steps(self.project, version=self.v1.uid)
        while True:
            try:
                next(generator)
            except StopIteration as stop:
                stepped = stop.value
                break
            steps += 1
        self.assertGreaterEqual(steps, 6)
        whole = self.declared(self.v1)
        self.assertEqual(stepped.report, whole.report)
        self.assertEqual([item.code for item in stepped.legal],
                         [item.code for item in whole.legal])
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation"), before)


class LimitProblemsTest(cp.ConstraintsProjectCase):
    """Un límite que se sale de la ventana y otro con la geometría no válida."""

    def add_limit(self, code: str, local: tuple[float, float, float, float], *,
                  ring: np.ndarray | None = None, inward: float = 5.0) -> None:
        """Un límite legal más (rectángulo local ``local`` o el anillo ``ring``) con su
        resguardo hacia dentro, en el proyecto."""
        row = cmodel.Constraint(
            uid=f"{code:0<32}"[:32], code=code, name=code.capitalize(), ctype=T.LEGAL_LIMIT,
            kind=G.POLYGON, parts=(((fx.rectangle(*local) if ring is None else ring),),),
            priority=0, reason="Límite de prueba", decided_by="Samuel (IMGA)",
            decided_on=date(2026, 10, 31), decision_uid=None, intention_uid=None,
            source_input=None, source_fid=None, layer="core_constraint_polygon", fid=0)
        cp.edit_constraints(self.project, [row])
        cp.declare(self.project, self.clock, {cparams.active_key(code): True,
                                              cparams.buffer_in_key(code): inward})

    def test_a_what_falls_outside_the_grid_is_named_with_its_area(self) -> None:
        """RF-012-15: un límite legal que sale 40 m de la ventana (x local 280 a 340 con la
        ventana hasta 300) se nombra con su área fuera, 40 × 100 = 4.000 m² exactos; el
        informe suma su parte de dentro (6.000 m² más) y el resguardo hacia dentro es el
        mayor."""
        self.add_limit("este", (280.0, 0.0, 340.0, 100.0))
        found = store.declared_limits(self.project, version=self.v1.uid)
        self.assertEqual(found.problems, ())
        (outside,) = found.report.outside
        self.assertEqual((outside.code, outside.name, outside.ctype), ("este", "Este",
                                                                        T.LEGAL_LIMIT))
        self.assertTrue(_close(outside.area_m2, 4000.0), outside.area_m2)
        self.assertTrue(_close(found.report.legal_m2, fx.limits().legal_area_m2 + 6000.0))
        self.assertEqual(found.inward_m, cp.LEGAL_INWARD_M)
        notice = found.report.notices()[0]
        self.assertEqual(notice.code, "core.constraint_zone_outside_grid")
        self.assertIn("4 000 m² de su zona quedan fuera", notice.text("es"))

    def test_b_an_invalid_limit_is_listed_and_gives_no_report(self) -> None:
        """RF-012-04: un límite en forma de ocho (se corta a sí mismo) se lista con su nombre y su
        problema, y no da informe (las áreas de una geometría así no valen); nada escrito."""
        eight = fx.absolute([(210.0, 120.0), (230.0, 140.0), (230.0, 120.0), (210.0, 140.0),
                             (210.0, 120.0)])
        self.add_limit("lazo", (0.0, 0.0, 0.0, 0.0), ring=eight)
        before = self.query("SELECT count(*) FROM gb_operation")
        found = store.declared_limits(self.project, version=self.v1.uid)
        self.assertIsNone(found.report)
        self.assertEqual([(item.code, item.problem) for item in found.problems],
                         [("lazo", "core.constraint_self_intersecting")])
        self.assertIn("se corta o se toca a sí mismo", found.problems[0].text("es"))
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation"), before)
        # Desactivado en esa versión, deja de ser un problema.
        cp.declare(self.project, self.clock, {cparams.active_key("lazo"): False},
                   version=self.v1)
        again = store.declared_limits(self.project, version=self.v1.uid)
        self.assertEqual(again.problems, ())
        self.assertIsNotNone(again.report)
        self.assertEqual([item.code for item in again.inactive], ["lazo"])


class LimitOutsideNameTest(unittest.TestCase):
    """``limit_outside`` es público (lo usa el informe de los límites)."""

    def test_limit_outside_is_exported(self) -> None:
        self.assertIn("limit_outside", combine.__all__)
        self.assertTrue(callable(combine.limit_outside))


if __name__ == "__main__":
    unittest.main()
