# SPDX-License-Identifier: GPL-3.0-or-later
"""Combinar las zonas de las restricciones en máscaras (spec 012, T09; RF-012-04, RF-012-13,
RF-012-14, RF-012-15; plan 012 A2, A3, D-11, D-13, D-14 y D-25).

- **RF-012-13**: en un caso a mano con los once tipos (rectángulos alineados con celdas de 1 m,
  sin resguardo hacia fuera y 2 m hacia dentro del límite legal), el dominio por defecto, el corte
  y el relleno admitidos y la franja son, celda a celda, los de las fórmulas de RF-012-13 sobre
  máscaras de centros de celda, con sus recuentos a mano (712, 584, 708 y 140 celdas); la rejilla
  de clases lleva los bits de D-25 de cada celda.
- **RF-012-14 (D-13)**: el intocable de prioridad 0 manda sobre un «requiere acceso» de prioridad
  10 que lo pisa; «sin relleno» dentro de «solo relleno» da 4 m² sin movimiento con las dos
  causas, y «sin relleno» en la franja, 8 m² con el límite legal y la balsa.
- **RF-012-15 (D-14)**: sin rejilla o sin límite legal activo, ``ConstraintError`` con la orden
  que lo resuelve; sin perímetro, el límite legal hace de perímetro con su aviso; una zona en
  parte fuera de la rejilla avisa con su nombre y el área fuera (m²), contada con la regla de
  D-1 frente a una fuerza bruta.
- **RF-012-04 (D-11)**: una restricción que se corta a sí misma, sin área, una línea sin
  longitud, un punto sin resguardo o un código repetido impiden combinar, con la lista de todas.
"""

import unittest
from datetime import date

import numpy as np

from tests.support import constraints_fixtures as fx
from tests.support.package import import_geoblender

gis = import_geoblender("gis")
model = import_geoblender("core.constraints.model")
params = import_geoblender("core.constraints.params")
messages = import_geoblender("core.constraints.messages")
combine = import_geoblender("gis.masks.combine")
zones = import_geoblender("gis.masks.zones")

T = model.ConstraintType
G = model.GeometryKind
P = model.ConstraintParam
TAU = 1e-9

NCOLS, NROWS = 40, 30
GRID = gis.Grid(fx.BASE[0], fx.BASE[1] + NROWS, 1.0, 1.0, NCOLS, NROWS)
"""Celdas de 1 m; la esquina suroeste es ``fx.BASE`` (las coordenadas locales de los casos)."""

LAYERS = {G.POLYGON: "core_constraint_polygon", G.LINE: "core_constraint_line",
          G.POINT: "core_constraint_point"}


def make(code, ctype, box=None, *, kind=G.POLYGON, coords=None, priority=0, fid=1,
         name=None):
    """Una restricción completa: un rectángulo local ``box`` o los ``coords`` locales."""
    if box is not None:
        parts = ((fx.rectangle(*box),),)
    elif kind is G.POLYGON:
        parts = ((fx.absolute(coords),),)
    elif kind is G.LINE:
        parts = ((fx.absolute(coords),),)
    else:
        parts = ((fx.absolute(coords).reshape(1, 2),),)
    return model.Constraint(
        uid=f"{fid:032d}", code=code, name=name or code.removeprefix("r_").title(),
        ctype=ctype, kind=kind, parts=parts, priority=priority, reason="Prueba",
        decided_by="IMGA", decided_on=date(2026, 10, 28), decision_uid=None,
        intention_uid=None, source_input=None, source_fid=None, layer=LAYERS[kind], fid=fid)


def resolved_for(items, *, outward=0.0, inward=2.0, weight=2.0, active=None, extra=None):
    """Los valores resueltos de los parámetros que pide cada tipo."""
    active = active or {}
    values = {}
    for item in items:
        for param in item.ctype.requires:
            key = params.param_key(item.code, param)
            values[key] = {P.BUFFER_OUT: outward, P.BUFFER_IN: inward, P.WEIGHT: weight,
                           P.ACTIVE: active.get(item.code, True)}[param]
    values.update(extra or {})
    return values


def site():
    """El caso a mano (rectángulos locales, m): límite legal de 30 × 30 m con 2 m hacia dentro;
    perímetro de (2, 2) a (36, 28), con 6 × 26 m fuera del límite (la franja); y los demás
    tipos, sin resguardo hacia fuera."""
    items = [
        make("r_concesion", T.LEGAL_LIMIT, (0, 0, 30, 30), fid=1),
        make("r_perimetro", T.ACTION_PERIMETER, (2, 2, 36, 28), fid=2),
        make("r_torre", T.UNTOUCHABLE, (10, 10, 14, 14), fid=3),
        make("r_exclusion", T.EXCLUSION, (32, 20, 34, 24), fid=4),
        make("r_sin_corte", T.NO_CUT, (16, 4, 20, 8), fid=5),
        make("r_solo_relleno", T.FILL_ONLY, (20, 16, 26, 22), priority=5, fid=6),
        make("r_balsa", T.NO_FILL, (22, 18, 24, 20), priority=1, fid=7),
        make("r_restauracion", T.RESTORATION_ONLY, (4, 20, 8, 24), fid=8),
        make("r_banda", T.SETBACK, (4, 4, 6, 8), fid=9),
        make("r_encinas", T.AVOID, (10, 20, 14, 24), fid=10),
        make("r_camino", T.REQUIRES_ACCESS, (12, 12, 18, 16), priority=10, fid=11),
        make("r_balsa_franja", T.NO_FILL, (32, 4, 34, 8), fid=12),
        make("r_desactivada", T.NO_CUT, (2, 2, 28, 28), priority=99, fid=13),
    ]
    return items, resolved_for(items, active={"r_desactivada": False})


def centers(box):
    """Las celdas de ``GRID`` con el centro dentro del rectángulo local (las enteras dentro, al
    estar alineado)."""
    x = (np.arange(NCOLS) + 0.5)[None, :]
    y = (NROWS - np.arange(NROWS) - 0.5)[:, None]
    return (x > box[0]) & (x < box[2]) & (y > box[1]) & (y < box[3])


def mask(runs):
    return runs.mask((NROWS, NCOLS))


class CombineTest(unittest.TestCase):
    """RF-012-13, RF-012-14 (D-13, D-25): el caso a mano."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.items, cls.resolved = site()
        cls.prepared = combine.prepare(cls.items, cls.resolved, GRID)
        cls.masks = combine.combine(cls.prepared.zones, cls.prepared.limits, GRID)

    def test_formulas_cell_by_cell(self) -> None:
        """RF-012-13: dominio, corte, relleno y franja frente a las fórmulas sobre máscaras."""
        p = centers((2, 2, 36, 28))
        inside = centers((0, 0, 30, 30))
        core = centers((2, 2, 28, 28))
        band = inside & ~core
        u = centers((10, 10, 14, 14)) | centers((32, 20, 34, 24))
        no_cut = (centers((16, 4, 20, 8)) | centers((20, 16, 26, 22)) | centers((4, 20, 8, 24))
                  | centers((4, 4, 6, 8)))
        no_fill = centers((22, 18, 24, 20)) | centers((32, 4, 34, 8))
        domain = p & inside & ~u
        cut = domain & ~band & ~no_cut
        fill = domain & ~no_fill
        strip = p & ~inside & ~u & ~no_fill
        m = self.masks
        np.testing.assert_array_equal(mask(m.perimeter), p)
        np.testing.assert_array_equal(mask(m.legal.inside), inside)
        np.testing.assert_array_equal(mask(m.legal.band), band)
        np.testing.assert_array_equal(mask(m.default_domain), domain)
        np.testing.assert_array_equal(mask(m.cut_allowed), cut)
        np.testing.assert_array_equal(mask(m.fill_allowed), fill)
        np.testing.assert_array_equal(mask(m.fill_strip), strip)
        np.testing.assert_array_equal(mask(m.untouchable), u)
        np.testing.assert_array_equal(mask(m.restoration), centers((4, 20, 8, 24)))
        np.testing.assert_array_equal(mask(m.access), centers((12, 12, 18, 16)))
        self.assertEqual(dict(m.avoid), {"r_encinas": 2.0})
        # Los recuentos a mano: 28·26 − 16; 26·26 − 16 − (16 + 36 + 16 + 8); 712 − 4;
        # 6·26 − 8 − 8.
        self.assertEqual((m.default_domain.cells, m.cut_allowed.cells, m.fill_allowed.cells,
                          m.fill_strip.cells), (712, 584, 708, 140))

    def test_classes_bits(self) -> None:
        """D-25: cada bit de la rejilla de clases es su máscara."""
        m = self.masks
        bits = {1: m.cut_allowed, 2: m.fill_allowed, 4: m.fill_strip, 8: m.perimeter,
                16: m.legal.inside, 32: m.legal.band, 64: m.untouchable,
                128: self.prepared.zones["r_encinas"].runs, 256: m.restoration,
                512: m.access, 1024: m.no_movement}
        self.assertEqual(m.classes.shape, (NROWS, NCOLS))
        expected = np.zeros((NROWS, NCOLS), dtype=np.int64)
        for bit, runs in bits.items():
            expected |= np.where(mask(runs), bit, 0)
            self.assertEqual(int(getattr(combine.ClassBit, combine.ClassBit(bit).name)), bit)
        np.testing.assert_array_equal(m.classes.astype(np.int64), expected)
        # La torre bajo el camino: perímetro, límite, intocable y requiere acceso; nada más.
        row, col = NROWS - 1 - 13, 13
        self.assertEqual(int(m.classes[row, col]), 8 | 16 | 64 | 512)

    def test_prohibitions_always_add_up(self) -> None:
        """RF-012-14 (D-13): ni la prioridad 10 del camino ni la desactivada de 99 devuelven a
        una celda lo que prohíbe el intocable de prioridad 0."""
        m = self.masks
        tower = combine.Runs.from_mask(centers((10, 10, 14, 14)))
        for runs in (m.default_domain, m.cut_allowed, m.fill_allowed, m.fill_strip):
            self.assertEqual(runs.intersection(tower).cells, 0)
        self.assertEqual(m.access.intersection(tower).cells, 4)
        self.assertNotIn("r_desactivada", self.prepared.zones)

    def test_conflicts_with_their_causes(self) -> None:
        """RF-012-14: el área sin movimiento posible, por combinación de causas (en orden de
        prioridad; a igual prioridad, por código)."""
        m = self.masks
        found = {c.causes: (c.runs.cells, c.area_m2) for c in m.conflicts}
        self.assertEqual(found, {("r_solo_relleno", "r_balsa"): (4, 4.0),
                                 ("r_balsa_franja", "r_concesion"): (8, 8.0)})
        self.assertEqual([c.causes for c in m.conflicts],
                         [("r_balsa_franja", "r_concesion"), ("r_solo_relleno", "r_balsa")])
        self.assertEqual(m.no_movement_m2, 12.0)
        np.testing.assert_array_equal(
            mask(m.no_movement), centers((22, 18, 24, 20)) | centers((32, 4, 34, 8)))

    def test_steps_give_the_same(self) -> None:
        """Por pasos pequeños sale lo mismo que de una vez."""
        steps = combine.prepare_steps(self.items, self.resolved, GRID, segments_per_step=1,
                                      rows_per_step=3)
        count = 0
        while True:
            try:
                next(steps)
                count += 1
            except StopIteration as stop:
                prepared = stop.value
                break
        self.assertGreater(count, 20)
        self.assertEqual(list(prepared.zones), list(self.prepared.zones))
        for code, zone in prepared.zones.items():
            self.assertEqual(zone.runs, self.prepared.zones[code].runs)
        again = combine.combine(prepared.zones, prepared.limits, GRID)
        np.testing.assert_array_equal(again.classes, self.masks.classes)


class LimitsAndWarningsTest(unittest.TestCase):
    """RF-012-15 (D-14): lo que falta y lo que queda fuera de la rejilla."""

    def test_no_perimeter_takes_the_legal_limit(self) -> None:
        items = [make("r_concesion", T.LEGAL_LIMIT, (0, 0, 30, 30), fid=1),
                 make("r_torre", T.UNTOUCHABLE, (10, 10, 14, 14), fid=2)]
        prepared = combine.prepare(items, resolved_for(items), GRID)
        self.assertTrue(prepared.limits.perimeter_from_legal)
        self.assertEqual(prepared.limits.perimeter, prepared.limits.legal.inside)
        self.assertEqual([n.code for n in prepared.notices],
                         ["core.constraint_perimeter_from_legal"])
        text = prepared.notices[0].text("es")
        self.assertIn("Concesion", text)
        self.assertIn("geoblender.core_edit_limits", text)
        self.assertNotIn("{", prepared.notices[0].text("en"))
        masks = combine.combine(prepared.zones, prepared.limits, GRID)
        self.assertEqual(masks.fill_strip.cells, 0)
        self.assertEqual(masks.default_domain.cells, 900 - 16)

    def test_no_legal_limit_is_an_error_with_its_command(self) -> None:
        for items, active in (
                ([make("r_perimetro", T.ACTION_PERIMETER, (2, 2, 36, 28), fid=1)], {}),
                ([make("r_concesion", T.LEGAL_LIMIT, (0, 0, 30, 30), fid=1)],
                 {"r_concesion": False})):
            with self.subTest(active=active), self.assertRaises(
                    messages.ConstraintError) as caught:
                combine.prepare(items, resolved_for(items, active=active), GRID)
            self.assertEqual(caught.exception.code, "core.constraint_no_legal_limit")
            self.assertEqual(caught.exception.values["command"], "geoblender.core_edit_limits")
            self.assertIn("geoblender.core_edit_limits", str(caught.exception))

    def test_no_grid_is_an_error_with_its_command(self) -> None:
        items = [make("r_concesion", T.LEGAL_LIMIT, (0, 0, 30, 30), fid=1)]
        with self.assertRaises(messages.ConstraintError) as caught:
            combine.prepare(items, resolved_for(items), None)
        self.assertEqual(caught.exception.code, "core.constraint_no_grid")
        self.assertEqual(caught.exception.values["command"], "geoblender.gis_resample_to_grid")

    def test_zone_outside_the_grid(self) -> None:
        """Un polígono que sale 3 m por el oeste (6 celdas fuera) y una torre a 1 m del borde
        este con 3 m de resguardo (las celdas fuera, por fuerza bruta con la regla de D-1)."""
        items = [make("r_concesion", T.LEGAL_LIMIT, (0, 0, 30, 30), fid=1),
                 make("r_cantera", T.EXCLUSION, (-3, 10, 2, 12), fid=2, name="Cantera vieja"),
                 make("r_torre", T.UNTOUCHABLE, kind=G.POINT, coords=[(39.0, 15.0)], fid=3,
                      name="Torre 7")]
        extra = {params.buffer_out_key("r_cantera"): 0.0,
                 params.buffer_out_key("r_torre"): 3.0}
        prepared = combine.prepare(items, resolved_for(items, extra=extra), GRID)
        # Fuerza bruta: las celdas al este del borde (x ≥ 40) a distancia < 3 − τ del punto.
        brute = 0
        for col in range(40, 44):
            for south in range(10, 20):
                dx = max(col - 39.0, 0.0, 39.0 - (col + 1))
                dy = max(south - 15.0, 0.0, 15.0 - (south + 1))
                brute += np.hypot(dx, dy) < 3.0 - TAU
        self.assertEqual(brute, 12)  # 6 en cada una de las columnas 40 y 41
        self.assertEqual(prepared.zones["r_cantera"].outside_m2, 6.0)
        self.assertEqual(prepared.zones["r_torre"].outside_m2, float(brute))
        self.assertEqual(prepared.zones["r_concesion"].outside_m2, 0.0)
        outside = {n.value("code"): n for n in prepared.notices
                   if n.code == "core.constraint_zone_outside_grid"}
        self.assertEqual(set(outside), {"r_cantera", "r_torre"})
        text = outside["r_torre"].text("es")
        self.assertIn("Torre 7", text)
        self.assertIn("12 m²", text)
        self.assertIn("Intocable", text)
        self.assertIn("Cantera vieja", outside["r_cantera"].text("es"))
        # Lo de dentro, igual que sin mirar fuera.
        self.assertEqual(prepared.zones["r_torre"].runs,
                         zones.zone_runs(items[2], GRID, 3.0))

    def test_legal_limit_outside_the_grid(self) -> None:
        """El límite legal que sale 5 m por el norte: su área fuera, exacta (m²)."""
        items = [make("r_concesion", T.LEGAL_LIMIT, (0, 0, 30, 35), fid=1)]
        prepared = combine.prepare(items, resolved_for(items), GRID)
        self.assertEqual(prepared.zones["r_concesion"].outside_m2, 150.0)


class InvalidConstraintsTest(unittest.TestCase):
    """RF-012-04 (D-11): lo incompleto o no válido impide combinar, con la lista de todas."""

    def test_all_are_listed(self) -> None:
        items = [
            make("r_concesion", T.LEGAL_LIMIT, (0, 0, 30, 30), fid=1),
            make("r_lazo", T.NO_CUT, coords=[(2, 2), (6, 6), (6, 2), (2, 6), (2, 2)], fid=2),
            make("r_plana", T.NO_FILL, coords=[(2, 2), (6, 2), (10, 2), (2, 2)], fid=3),
            make("r_camino", T.REQUIRES_ACCESS, kind=G.LINE, coords=[(4, 4), (4, 4)], fid=1),
            make("r_torre", T.UNTOUCHABLE, kind=G.POINT, coords=[(8, 8)], fid=1),
            make("r_doble", T.EXCLUSION, (10, 10, 12, 12), fid=4),
            make("r_doble", T.EXCLUSION, (14, 10, 16, 12), fid=5),
        ]
        extra = {params.buffer_out_key("r_camino"): 2.0,
                 params.buffer_out_key("r_torre"): 0.0}
        with self.assertRaises(combine.IncompleteConstraints) as caught:
            combine.prepare(items, resolved_for(items, extra=extra), GRID)
        found = [(p.code, p.fid, p.problem) for p in caught.exception.problems]
        self.assertEqual(found, [
            ("r_lazo", 2, "core.constraint_self_intersecting"),
            ("r_plana", 3, "core.constraint_no_area"),
            ("r_camino", 1, "core.constraint_no_length"),
            ("r_torre", 1, "core.constraint_buffer_not_positive"),
            ("r_doble", 4, "core.constraint_code_repeated"),
            ("r_doble", 5, "core.constraint_code_repeated"),
        ])
        self.assertEqual(caught.exception.code, "core.constraint_incomplete")
        text = str(caught.exception)
        for name in ("Lazo", "Plana", "Camino", "Torre", "Doble"):
            self.assertIn(name, text)
        for problem in caught.exception.problems:
            self.assertNotIn("{", problem.text("es"))
            self.assertNotIn("{", problem.text("en"))

    def test_without_geometry_and_inactive(self) -> None:
        """Sin geometría, también; desactivada, no se mira."""
        empty = model.Constraint(
            uid="e" * 32, code="r_vacia", name="Vacía", ctype=T.NO_CUT, kind=G.POLYGON,
            parts=(), priority=0, reason="Prueba", decided_by="IMGA",
            decided_on=date(2026, 10, 28), decision_uid=None, intention_uid=None,
            source_input=None, source_fid=None, layer="core_constraint_polygon", fid=9)
        legal = make("r_concesion", T.LEGAL_LIMIT, (0, 0, 30, 30), fid=1)
        lazo = make("r_lazo", T.NO_CUT, coords=[(2, 2), (6, 6), (6, 2), (2, 6), (2, 2)], fid=2)
        items = [legal, empty, lazo]
        with self.assertRaises(combine.IncompleteConstraints) as caught:
            combine.prepare(items, resolved_for(items), GRID)
        self.assertEqual([p.problem for p in caught.exception.problems],
                         ["core.constraint_no_geometry", "core.constraint_self_intersecting"])
        prepared = combine.prepare(items, resolved_for(
            items, active={"r_vacia": False, "r_lazo": False}), GRID)
        self.assertEqual(list(prepared.zones), ["r_concesion"])


if __name__ == "__main__":
    unittest.main()
