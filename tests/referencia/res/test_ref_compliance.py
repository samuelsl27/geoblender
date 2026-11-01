# SPDX-License-Identifier: GPL-3.0-or-later
"""Verificación por recinto de referencia (spec 012, T16; CE-012-02, CE-012-03, CE-012-05,
CE-012-06; RF-012-21, RF-012-22, RF-012-23; plan 012 A7–A10, D-6, D-41; constitución,
principio 2).

Las máscaras salen de las restricciones del sitio sintético (``constraints_fixtures``, rejilla de
160 × 160 celdas de 2 m) con ``gis.masks.combine``, como las compila la 012: la concesión
(200 × 200 m, sin banda hacia dentro), el perímetro con su lóbulo fuera del límite (0,68 ha), la
torre (punto, intocable con 8 m: 60 celdas), la balsa «sin relleno» (750 celdas), unas encinas
«preferible no afectar» (peso 2,5) y un camino que «requiere acceso». Espesor mínimo, 0,02 m
(D-6). Volúmenes con error relativo ≤ 10⁻⁹ frente al cálculo a mano.

- **CE-012-02**: la final que rebaja 26,6 m el entorno de la torre «no cumple» en la torre con
  60 · 4 · 26,6 = 6.384 m³ y un grupo de 240 m², 6.384 m³, 26,6 m de espesor máximo y centro en
  la torre; la que respeta las máscaras da 0 m³ en todos los recintos y cumple.
- **CE-012-03**: 3 m de corte en 400 celdas de la franja: «no cumple (fuera del límite legal)»
  con 4.800 m³ y su grupo; el mismo relleno, «cumple» en todos.
- **CE-012-06**: la balsa con 4.300 m³ de relleno «no cumple» con esos m³ y un grupo de 800 m²
  de centro (90, 100) locales; las encinas, m², m³ y m³ × peso sin juicio; el camino, «sin
  comprobar (R-40)».
- **CE-012-05**: en el caso a mano de los once tipos (``test_combine``), 100 superficies que
  cortan solo en el corte admitido y rellenan solo en el relleno admitido (con ruido por debajo
  del umbral y celdas sin dato) dan 0 m³ en todos los recintos; mover una celda a una zona
  prohibida hace que esa, y solo esa, no cumpla con el volumen de la celda.
"""

import unittest
from datetime import date

import numpy as np

from tests.support import constraints_fixtures as fx
from tests.support.package import import_geoblender
from tests.unit.gis.masks import test_combine as hand

model = import_geoblender("core.constraints.model")
params = import_geoblender("core.constraints.params")
combine = import_geoblender("gis.masks.combine")
compliance = import_geoblender("reserves.compliance")

T = model.ConstraintType
G = model.GeometryKind
P = model.ConstraintParam
V = compliance.Verdict
C = compliance.Counts
EXACT = 1e-9
E = 0.02  # D-6
AVOID_BOX = (24.0, 144.0, 36.0, 156.0)
"""Encinas «preferible no afectar» (local): 6 × 6 celdas; la final corta 1 m en todas."""
ACCESS_BOX = (134.0, 34.0, 146.0, 46.0)
"""Camino que «requiere acceso» (local): 6 × 6 celdas; la final rellena 2 m en todas."""
AVOID_WEIGHT = 2.5


def _item(code, ctype, kind, parts, fid):
    return model.Constraint(
        uid=f"{fid:032d}", code=code, name=code.removeprefix("r_").title(), ctype=ctype,
        kind=kind, parts=parts, priority=0, reason="Prueba", decided_by="IMGA",
        decided_on=date(2026, 10, 28), decision_uid=None, intention_uid=None,
        source_input=None, source_fid=None, layer=hand.LAYERS[kind], fid=fid)


def site_zones():
    """Los recintos del sitio, de sus restricciones compiladas en ``fx.SITE_GRID``."""
    limits = fx.limits()
    tower = fx.tower_case()
    pond = fx.pond_case()
    items = [
        _item("r_concesion", T.LEGAL_LIMIT, G.POLYGON, ((limits.legal_limit,),), 1),
        _item("r_perimetro", T.ACTION_PERIMETER, G.POLYGON, ((limits.perimeter,),), 2),
        _item("r_torre", T.UNTOUCHABLE, G.POINT, ((tower.zone_coords.reshape(1, 2),),), 3),
        _item("r_balsa", T.NO_FILL, G.POLYGON, (pond.zone_coords,), 4),
        _item("r_encinas", T.AVOID, G.POLYGON, ((fx.rectangle(*AVOID_BOX),),), 5),
        _item("r_camino", T.REQUIRES_ACCESS, G.POLYGON, ((fx.rectangle(*ACCESS_BOX),),), 6),
    ]
    values = {
        P.BUFFER_IN: {"r_concesion": 0.0},
        P.BUFFER_OUT: {"r_torre": tower.zone_outward_m, "r_balsa": pond.zone_outward_m,
                       "r_encinas": 0.0, "r_camino": 0.0},
        P.WEIGHT: {"r_encinas": AVOID_WEIGHT},
    }
    resolved = {}
    for item in items:
        for param in item.ctype.requires:
            resolved[params.param_key(item.code, param)] = (
                True if param is P.ACTIVE else values[param][item.code])
    return compile_zones(items, resolved, fx.SITE_GRID)


def compile_zones(items, resolved, grid):
    """Los recintos como los da la compilación: las zonas, la banda hacia dentro del límite
    legal (``<código>:inner``) y los bits de la rejilla de clases."""
    prepared = combine.prepare(items, resolved, grid)
    masks = combine.combine(prepared.zones, prepared.limits, grid)
    zones = {code: zone.runs for code, zone in prepared.zones.items()}
    for code in prepared.limits.legal_codes:
        zones[f"{code}:inner"] = prepared.limits.legal_bands[code]
    ctypes = {code: zone.ctype for code, zone in prepared.zones.items()}
    weights = {code: zone.weight for code, zone in prepared.zones.items()
               if zone.weight is not None}
    return compliance.check_zones(masks.classes, zones, ctypes, weights), masks


class SiteTest(unittest.TestCase):
    """CE-012-02, CE-012-03, CE-012-06 (RF-012-21, RF-012-22, RF-012-23)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.zones, cls.masks = site_zones()

    def verify(self, case_or_final, start=None):
        final = getattr(case_or_final, "final", case_or_final)
        start = fx.site_start() if start is None else start
        return compliance.check(fx.SITE_GRID, self.zones, start.values, final.values, E)

    def assert_close(self, value, expected):
        self.assertLessEqual(abs(value - expected), EXACT * max(abs(expected), 1.0),
                             f"{value!r} frente a {expected!r}")

    def assert_group(self, group, case, zone):
        self.assertEqual(group.zone, zone)
        self.assertEqual(group.cells, case.group_cells)
        self.assert_close(group.area_m2, case.group_area_m2)
        self.assert_close(group.volume_m3, case.group_volume_m3)
        self.assert_close(group.max_m, case.group_max_m)
        self.assert_close(group.center[0], case.group_center[0])
        self.assert_close(group.center[1], case.group_center[1])

    def test_zone_cells_of_the_site(self) -> None:
        """Las zonas del sitio tienen las celdas a mano de los casos."""
        cells = {zone.code: zone.runs.cells for zone in self.zones}
        self.assertEqual(cells["r_torre"], fx.TOWER_ZONE_CELLS)
        self.assertEqual(cells["r_balsa"], fx.pond_case().zone_cells)
        self.assertEqual(cells["r_concesion:inner"], 0)
        self.assertEqual(cells["r_encinas"], 36)
        self.assertEqual(int(np.count_nonzero(self.masks.classes & combine.ClassBit.FILL_STRIP)),
                         fx.strip_case().zone_cells)

    def test_ce_012_02_tower(self) -> None:
        """CE-012-02: la torre rebajada 26,6 m no cumple; la final que respeta, 0 m³."""
        case = fx.tower_case()
        result = self.verify(case)
        tower = result.zone("r_torre")
        self.assertIs(tower.verdict, V.FAILS)
        self.assert_close(tower.cut_m3, case.cut_m3)
        self.assert_close(tower.cut_m3, 6_384.0)
        self.assertEqual(tower.fill_m3, case.fill_m3)
        self.assert_close(tower.counted_m3, 6_384.0)
        self.assertEqual(tower.moved_m2, 240.0)
        (group,) = result.groups_of("r_torre")
        self.assert_group(group, case, "r_torre")
        self.assertEqual([t.code for t in result.totals if t.verdict is V.FAILS], ["r_torre"])
        respectful = self.verify(fx.tower_case(respectful=True))
        for item in respectful.totals:
            with self.subTest(zone=item.code):
                self.assertEqual(item.counted_m3, 0.0)
                self.assertIn(item.verdict, (V.COMPLIES, V.NOT_JUDGED, V.UNCHECKED))
        self.assertEqual(respectful.zone("r_torre").cut_m3, 0.0)
        self.assertFalse(respectful.fails)
        self.assertEqual(respectful.groups, ())

    def test_ce_012_03_strip(self) -> None:
        """CE-012-03: el corte en la franja no cumple fuera del límite legal; el relleno,
        cumple."""
        case = fx.strip_case()
        result = self.verify(case)
        outside = result.zone(compliance.OUTSIDE_LEGAL)
        self.assertIs(outside.verdict, V.FAILS)
        self.assert_close(outside.cut_m3, case.cut_m3)
        self.assert_close(outside.counted_m3, 4_800.0)
        self.assertEqual([t.code for t in result.totals if t.verdict is V.FAILS],
                         [compliance.OUTSIDE_LEGAL])
        self.assertEqual(result.zone(compliance.OUTSIDE_PERIMETER).counted_m3, 0.0)
        (group,) = result.groups
        self.assert_group(group, case, compliance.OUTSIDE_LEGAL)
        filled = self.verify(fx.strip_case(fill=True))
        self.assert_close(filled.zone(compliance.OUTSIDE_LEGAL).fill_m3, 4_800.0)
        self.assertIs(filled.zone(compliance.OUTSIDE_LEGAL).verdict, V.COMPLIES)
        self.assertFalse(filled.fails)
        self.assertEqual(filled.groups, ())

    def test_ce_012_06_pond_avoid_and_access(self) -> None:
        """CE-012-06: la balsa con 4.300 m³ de relleno no cumple; las encinas, sin juicio; el
        camino, sin comprobar."""
        case = fx.pond_case()
        values = case.final.values.copy()
        x, y = fx.site_centers()
        for box, change in ((AVOID_BOX, -1.0), (ACCESS_BOX, 2.0)):
            inside = (x > box[0]) & (x < box[2]) & (y > box[1]) & (y < box[3])
            values[inside] = fx.START_Z + change
        result = self.verify(case.final.__class__(fx.SITE_GRID, values, fx.CRS, fx.VERTICAL))
        pond = result.zone("r_balsa")
        self.assertIs(pond.verdict, V.FAILS)
        self.assert_close(pond.fill_m3, 4_300.0)
        self.assert_close(pond.counted_m3, case.fill_m3)
        (group,) = result.groups_of("r_balsa")
        self.assert_group(group, case, "r_balsa")
        avoid = result.zone("r_encinas")
        self.assertIs(avoid.verdict, V.NOT_JUDGED)
        self.assertEqual(avoid.moved_m2, 144.0)
        self.assert_close(avoid.cut_m3, 144.0)
        self.assert_close(avoid.weighted_m3, 144.0 * AVOID_WEIGHT)
        access = result.zone("r_camino")
        self.assertIs(access.verdict, V.UNCHECKED)
        self.assert_close(access.fill_m3, 288.0)
        self.assertEqual(result.groups_of("r_encinas") + result.groups_of("r_camino"), ())
        self.assertEqual([t.code for t in result.totals if t.verdict is V.FAILS], ["r_balsa"])


class CoherenceTest(unittest.TestCase):
    """CE-012-05 (RF-012-21, RF-012-22): lo que admiten las máscaras verifica 0 m³."""

    def test_ce_012_05_hundred_surfaces(self) -> None:
        items, resolved = hand.site()
        zones, masks = compile_zones(items, resolved, hand.GRID)
        grid = hand.GRID
        shape = grid.shape
        cut_ok = masks.cut_allowed.mask(shape)
        fill_ok = masks.fill_allowed.mask(shape)
        members = {z.code: z for z in zones}
        cuts = {z.code for z in zones if z.counts in (C.CUT, C.ANY)}
        fills = {z.code for z in zones if z.counts in (C.FILL, C.ANY)}
        inside = {code: z.runs.mask(shape) for code, z in members.items()}
        # Las celdas donde un movimiento cuenta en un recinto y en ningún otro.
        only = []
        for action, counting in (("cut", cuts), ("fill", fills)):
            for code in sorted(counting):
                others = np.zeros(shape, dtype=bool)
                for other in counting - {code}:
                    others |= inside[other]
                cells = np.argwhere(inside[code] & ~others)
                if cells.size:
                    only.append((code, action, cells))
        self.assertGreaterEqual(len({code for code, _action, _cells in only}), 10)
        rng = np.random.default_rng(5)
        start = 400.0 + rng.uniform(-5.0, 5.0, shape)
        for case in range(100):
            choice = rng.integers(0, 3, shape)  # 0: nada; 1: corte; 2: relleno
            depth = rng.uniform(0.03, 9.0, shape)
            difference = rng.uniform(-E, E, shape)  # ruido que no pasa el umbral
            difference = np.where((choice == 1) & cut_ok, depth, difference)
            difference = np.where((choice == 2) & fill_ok, -depth, difference)
            final = start - difference
            final[rng.random(shape) < 0.03] = np.nan
            with self.subTest(case=case):
                result = compliance.check(grid, zones, start, final, E, band_rows=7)
                for item in result.totals:
                    if item.counts in (C.CUT, C.FILL, C.ANY):
                        self.assertEqual(item.counted_m3, 0.0, item.code)
                    self.assertIsNot(item.verdict, V.FAILS, item.code)
                self.assertEqual(result.groups, ())
                code, action, cells = only[case % len(only)]
                row, col = cells[rng.integers(0, len(cells))]
                thickness = float(rng.uniform(0.5, 4.0))
                moved_start = start.copy()
                moved_start[row, col] = 400.0
                moved = final.copy()
                moved[row, col] = 400.0 - (thickness if action == "cut" else -thickness)
                result = compliance.check(grid, zones, moved_start, moved, E, band_rows=7)
                failing = [t.code for t in result.totals if t.verdict is V.FAILS]
                self.assertEqual(failing, [code])
                volume = thickness * grid.cell_area
                self.assertLessEqual(abs(result.zone(code).counted_m3 - volume), EXACT * volume)
                (group,) = result.groups
                self.assertEqual((group.zone, group.cells), (code, 1))
                self.assertLessEqual(abs(group.volume_m3 - volume), EXACT * volume)


if __name__ == "__main__":
    unittest.main()
