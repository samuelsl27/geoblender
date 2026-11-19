# SPDX-License-Identifier: GPL-3.0-or-later
"""La verificación con la base de los acopios (spec 012 0.5, DIFF-012 de la 016; RF-012-21,
RF-012-22, RF-012-24, RF-012-30; plan 016 A12, T29).

Una retirada de acopio (RF-016-11) baja el material por encima de la base de un acopio, que no es
terreno: en las cinco zonas del dominio por defecto (sin corte, solo relleno, solo restauración,
banda de resguardo y banda hacia dentro de un límite legal; ``Counts.CUT_TERRAIN``) cuenta como
**corte de terreno** solo el de ``R = mín(partida, base)`` frente a la final y el resto es **corte
de acopios** (``ZoneTotals.stockpile_cut_m3``); el corte de RF-012-21 (``cut_m3``) es la suma.

- **Caso de referencia (a) del diff**: rejilla de 10 × 10 celdas de 1 m, terreno a 100 m, acopio de
  4 × 4 celdas hasta 103 m, zona sin corte en toda la rejilla: retirado a 100 m, corte de terreno
  0 m³, de acopios 48 m³, «cumple»; con una celda a 99,5 m, 0,5 m³ de terreno y «no cumple».
- **(b)** terreno + acopios = el corte de la 0.4 a ≤ 10⁻⁹ relativo en cada una de las cinco zonas,
  contra un cálculo celda a celda independiente (totales, grupos y rejilla de incumplimientos).
- **(d)** las zonas no exentas (fuera del límite legal, intocable, exclusión, fuera del perímetro,
  sin relleno y preferible no afectar) cuentan **todo** el movimiento, con o sin base.
- **(c) Sin base, el mismo resultado bit a bit** (``np.array_equal`` sobre totales, grupos y
  rejilla): sin recintos nuevos, con una base que no cubre nada o que no baja de la partida, y por
  bandas de cualquier tamaño.
- La petición lleva la base de los acopios, opcional, y ``lowest_base`` toma la menor (P-10).
"""

import dataclasses
import math
import unittest
from typing import Any

import numpy as np

from tests.support.package import import_geoblender

gis = import_geoblender("gis")
model = import_geoblender("core.constraints.model")
combine = import_geoblender("gis.masks.combine")
zones_mod = import_geoblender("gis.masks.zones")
access = import_geoblender("gis.masks.access")
surfaces = import_geoblender("reserves.surfaces")
compliance = import_geoblender("reserves.compliance")

T = model.ConstraintType
Bit = combine.ClassBit
Runs = zones_mod.Runs
V = compliance.Verdict
C = compliance.Counts

NAN = math.nan
E = 0.02
REL = 1e-9


def runs_of(mask: np.ndarray) -> Any:
    rows, cols = np.nonzero(mask)
    return Runs(rows, cols, cols + 1)


def close(test: unittest.TestCase, found: float, expected: float, what: str = "") -> None:
    test.assertTrue(math.isclose(found, expected, rel_tol=REL, abs_tol=1e-9),
                    f"{what}: {found!r} no es {expected!r}")


def totals_of(result: Any, *, ignore_counts: bool = False) -> list[tuple[Any, ...]]:
    found = []
    for item in result.totals:
        if ignore_counts:
            item = dataclasses.replace(item, counts=C.CUT)
        found.append(dataclasses.astuple(item))
    return found


def groups_of(result: Any) -> list[tuple[Any, ...]]:
    return [(g.zone, g.cells, g.area_m2, g.volume_m3, g.max_m, g.center, g.box,
             g.rows.tolist(), g.cols.tolist()) for g in result.groups]


def assert_same(test: unittest.TestCase, a: Any, b: Any, *, ignore_counts: bool = False) -> None:
    """Bit a bit: totales, grupos y rejilla de incumplimientos (RF-012-30: sin base, lo de
    antes)."""
    test.assertEqual(totals_of(a, ignore_counts=ignore_counts),
                     totals_of(b, ignore_counts=ignore_counts))
    test.assertEqual(groups_of(a), groups_of(b))
    test.assertIs(a.violations is None, b.violations is None)
    if a.violations is not None:
        test.assertTrue(np.array_equal(a.violations, b.violations, equal_nan=True))
    test.assertEqual((a.same_surface, [n.code for n in a.notices]),
                     (b.same_surface, [n.code for n in b.notices]))


# --- El caso de referencia (a) -------------------------------------------------------------------

GRID_A = gis.Grid(500000.0, 4400010.0, 1.0, 1.0, 10, 10)
"""10 × 10 celdas de 1 m: la fila 0 es la del norte."""


def classes_inside(grid: Any) -> np.ndarray:
    return np.full(grid.shape, np.uint16(Bit.PERIMETER) | np.uint16(Bit.LEGAL), dtype=np.uint16)


def case_a() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Terreno a 100 m; un acopio de 4 × 4 celdas hasta 103 m (su base, a 100 m, solo en su
    huella)."""
    start = np.full(GRID_A.shape, 100.0)
    start[3:7, 3:7] = 103.0
    base = np.full(GRID_A.shape, NAN)
    base[3:7, 3:7] = 100.0
    return start, base, np.full(GRID_A.shape, 100.0)


def zones_a(*, with_base: bool) -> Any:
    whole = runs_of(np.ones(GRID_A.shape, dtype=bool))
    return compliance.check_zones(classes_inside(GRID_A), {"r_sin_corte": whole},
                                  {"r_sin_corte": T.NO_CUT}, with_base=with_base)


class ReferenceCaseTest(unittest.TestCase):
    """RF-012-30, RF-012-22, RF-012-21: el caso (a) del diff, a mano."""

    def check(self, final: np.ndarray, *, base: Any = None, with_base: bool = True,
              band_rows: int = 256) -> Any:
        start, _, _ = case_a()
        return compliance.check(GRID_A, zones_a(with_base=with_base), start, final, E,
                                band_rows=band_rows, base=base)

    def test_retired_to_the_base_complies(self) -> None:
        """RF-012-30: retirado a 100 m: corte de terreno 0 m³, de acopios 48 m³, «cumple»."""
        _, base, final = case_a()
        for band_rows in (256, 1, 3):
            with self.subTest(band_rows=band_rows):
                result = self.check(final, base=base, band_rows=band_rows)
                zone = result.zone("r_sin_corte")
                self.assertIs(zone.counts, C.CUT_TERRAIN)
                self.assertEqual((zone.cut_m3, zone.counted_m3, zone.stockpile_cut_m3),
                                 (48.0, 0.0, 48.0))
                self.assertEqual((zone.fill_m3, zone.moved_m2, zone.nodata_m2), (0.0, 16.0, 0.0))
                self.assertIs(zone.verdict, V.COMPLIES)
                self.assertFalse(result.fails)
                self.assertEqual(result.groups, ())
                self.assertIsNone(result.violations)

    def test_without_the_base_everything_counts(self) -> None:
        """RF-012-22: sin base, la retirada es corte de la zona sin corte: «no cumple» (como en
        la 0.4)."""
        _, _, final = case_a()
        result = self.check(final, with_base=False)
        zone = result.zone("r_sin_corte")
        self.assertIs(zone.counts, C.CUT)
        self.assertEqual((zone.cut_m3, zone.counted_m3, zone.stockpile_cut_m3), (48.0, 48.0, 0.0))
        self.assertIs(zone.verdict, V.FAILS)

    def test_a_cell_below_the_terrain_does_not_comply(self) -> None:
        """RF-012-22, RF-012-30: una celda a 99,5 m fuera del acopio: 0,5 m³ de terreno, «no
        cumple»."""
        _, base, final = case_a()
        final[0, 0] = 99.5
        for band_rows in (256, 1, 4):
            with self.subTest(band_rows=band_rows):
                result = self.check(final, base=base, band_rows=band_rows)
                zone = result.zone("r_sin_corte")
                self.assertEqual((zone.cut_m3, zone.counted_m3, zone.stockpile_cut_m3),
                                 (48.5, 0.5, 48.0))
                self.assertIs(zone.verdict, V.FAILS)
                self.assertTrue(result.fails)
                (group,) = result.groups
                self.assertEqual((group.zone, group.cells, group.area_m2, group.volume_m3,
                                  group.max_m),
                                 ("r_sin_corte", 1, 1.0, 0.5, 0.5))
                self.assertEqual(result.violations[0, 0], -0.5)
                self.assertEqual(int(np.isfinite(result.violations).sum()), 1)

    def test_a_cell_below_the_base_does_not_comply(self) -> None:
        """RF-012-22, RF-012-30: bajando una celda del acopio por debajo de su base (99,5 m): el
        corte bajo la base (0,5 m³) es de terreno y los 3 m de encima, de acopios; el veredicto, el
        grupo y la rejilla usan el de terreno."""
        _, base, final = case_a()
        final[4, 4] = 99.5
        result = self.check(final, base=base)
        zone = result.zone("r_sin_corte")
        self.assertEqual((zone.cut_m3, zone.counted_m3, zone.stockpile_cut_m3), (48.5, 0.5, 48.0))
        self.assertIs(zone.verdict, V.FAILS)
        (group,) = result.groups
        self.assertEqual((group.cells, group.volume_m3, group.max_m), (1, 0.5, 0.5))
        self.assertEqual((group.rows.tolist(), group.cols.tolist()), ([4], [4]))
        self.assertEqual(result.violations[4, 4], -0.5)
        # Sin base, esa misma celda son 3,5 m de corte y 16 celdas de grupo.
        plain = self.check(final, with_base=False)
        self.assertEqual(plain.zone("r_sin_corte").counted_m3, 48.5)
        self.assertEqual(plain.violations[4, 4], -3.5)

    def test_the_threshold_applies_to_the_terrain_cut(self) -> None:
        """RF-012-30 (D-6): ``R − final`` ≤ 0,02 m no cuenta como terreno; si pasa, cuenta con todo
        su espesor (números exactos en binario: 2⁻⁶ y 2⁻⁵ m)."""
        _, base, final = case_a()
        final[4, 4] = 100.0 - 2.0**-6  # R − final = 0,015625: no pasa el umbral
        final[4, 5] = 100.0 - 2.0**-5  # R − final = 0,03125: cuenta entero
        result = self.check(final, base=base)
        zone = result.zone("r_sin_corte")
        self.assertEqual(zone.counted_m3, 2.0**-5)
        self.assertEqual(zone.stockpile_cut_m3, 42.0 + (3.0 + 2.0**-6) + 3.0)
        self.assertEqual(zone.cut_m3, 42.0 + (3.0 + 2.0**-6) + (3.0 + 2.0**-5))
        self.assertIs(zone.verdict, V.FAILS)
        (group,) = result.groups
        self.assertEqual((group.cells, group.volume_m3), (1, 2.0**-5))

    def test_the_base_band_has_the_shape_of_the_band(self) -> None:
        """RF-012-30: la banda de la base es de la forma de las otras dos (o un error del
        programa)."""
        start, base, final = case_a()
        checker = compliance.Checker(GRID_A, zones_a(with_base=True), E)
        with self.assertRaises(ValueError):
            checker.add(0, start, final, base=base[:5])
        checker.add(0, start, final, base=None)  # sin base, como siempre

    def test_a_base_above_the_start_is_ignored(self) -> None:
        """RF-012-30: donde la base no es menor que la partida, ``R = partida``."""
        _, base, final = case_a()
        base[3:7, 3:7] = 105.0  # por encima de la partida (103): no hay acopio que retirar
        result = self.check(final, base=base)
        zone = result.zone("r_sin_corte")
        self.assertEqual((zone.cut_m3, zone.counted_m3, zone.stockpile_cut_m3), (48.0, 48.0, 0.0))


# --- Un cálculo celda a celda, independiente -----------------------------------------------------

GRID = gis.Grid(500000.0, 4400036.0, 2.0, 1.5, 24, 18)
"""24 columnas × 18 filas de 2 × 1,5 m (3 m²)."""
AREA = GRID.cell_area

CTYPES = {"r_nocut": T.NO_CUT, "r_fillonly": T.FILL_ONLY, "r_restor": T.RESTORATION_ONLY,
          "r_setback": T.SETBACK, "r_legal": T.LEGAL_LIMIT, "r_untouch": T.UNTOUCHABLE,
          "r_excl": T.EXCLUSION, "r_nofill": T.NO_FILL, "r_avoid": T.AVOID,
          "r_access": T.REQUIRES_ACCESS}
WEIGHTS = {"r_avoid": 2.5}
EXEMPT = ("r_nocut", "r_fillonly", "r_restor", "r_setback", "r_legal:inner")
"""Las cinco zonas del dominio por defecto (RF-012-30)."""
FULL = ("outside_perimeter", "outside_legal", "r_legal", "r_untouch", "r_excl", "r_nofill",
        "r_avoid", "r_access")
"""Las demás: cuentan todo el movimiento (con o sin base)."""


def random_case(seed: int) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    shape = GRID.shape
    start = 100.0 + rng.normal(0.0, 0.2, shape)
    start[rng.random(shape) < 0.03] = NAN
    base = np.full(shape, NAN)
    hollow = np.zeros(shape, dtype=bool)
    for _ in range(3):
        row, col = int(rng.integers(0, shape[0] - 4)), int(rng.integers(0, shape[1] - 4))
        high, wide = int(rng.integers(2, 6)), int(rng.integers(2, 7))
        patch = (slice(row, row + high), slice(col, col + wide))
        below = rng.uniform(-0.6, 4.0, base[patch].shape)
        base[patch] = np.nan_to_num(start[patch], nan=100.0) - below
        hollow[patch] = True
    delta = rng.choice([0.0, 0.01, 0.02, 0.0201, 0.3, 1.2, 3.0, -0.01, -0.5, -2.0], size=shape,
                       p=[0.8, 0.04, 0.04, 0.02, 0.02, 0.01, 0.01, 0.02, 0.02, 0.02])
    final = start - delta
    near = hollow & (rng.random(shape) < 0.6)
    final[near] = base[near] + rng.choice([0.0, -0.01, -0.02, 0.0, 0.4, 0.1, -0.0201, -0.7],
                                          size=int(near.sum()))
    final[rng.random(shape) < 0.03] = NAN
    classes = np.zeros(shape, dtype=np.uint16)
    classes |= np.where(rng.random(shape) < 0.8, np.uint16(Bit.PERIMETER), np.uint16(0))
    classes |= np.where(rng.random(shape) < 0.7, np.uint16(Bit.LEGAL), np.uint16(0))
    masks = {code: rng.random(shape) < rng.choice([0.03, 0.3]) for code in CTYPES}
    masks["r_legal:inner"] = masks["r_legal"] & (rng.random(shape) < 0.5)
    zones = {code: runs_of(mask) for code, mask in masks.items()}
    return {"start": start, "final": final, "base": base, "classes": classes, "zones": zones}


def build_zones(case: dict[str, Any], *, with_base: bool) -> Any:
    return compliance.check_zones(case["classes"], case["zones"], CTYPES, WEIGHTS,
                                  with_base=with_base)


def zone_mask(case: dict[str, Any], zone: Any) -> np.ndarray:
    """Las celdas de un recinto, de la rejilla de clases o de sus tramos."""
    classes = case["classes"]
    if zone.code == "outside_perimeter":
        return (classes & np.uint16(Bit.PERIMETER)) == 0
    if zone.code == "outside_legal":
        return (classes & np.uint16(Bit.LEGAL)) == 0
    mask = np.zeros(GRID.shape, dtype=bool)
    for row, col0, col1 in zip(zone.runs.row.tolist(), zone.runs.col0.tolist(),
                               zone.runs.col1.tolist(), strict=True):
        mask[row, col0:col1] = True
    return mask


def brute(case: dict[str, Any], zones: Any, *, with_base: bool) -> dict[str, dict[str, float]]:
    """Por recinto, celda a celda y con números de Python: el corte total, el relleno, el de
    terreno, el de acopios y sus celdas."""
    start, final, base = case["start"], case["final"], case["base"]
    out: dict[str, dict[str, float]] = {}
    for zone in zones:
        item = dict.fromkeys(("cut", "fill", "terrain", "stock", "cut_cells", "fill_cells",
                              "terrain_cells", "moved", "nodata"), 0.0)
        for i, j in zip(*np.nonzero(zone_mask(case, zone)), strict=True):
            s, f = float(start[i, j]), float(final[i, j])
            if not (math.isfinite(s) and math.isfinite(f)):
                item["nodata"] += 1
                continue
            t = s - f
            b = float(base[i, j]) if with_base else NAN
            ref = s if not math.isfinite(b) else min(s, b)
            r = ref - f
            if t > E:
                item["cut"] += t
                item["cut_cells"] += 1
                item["stock"] += t - (r if r > E else 0.0)
            if -t > E:
                item["fill"] += -t
                item["fill_cells"] += 1
            if r > E:
                item["terrain"] += r
                item["terrain_cells"] += 1
            if t > E or -t > E:
                item["moved"] += 1
        out[zone.code] = item
    return out


def expected_violations(case: dict[str, Any], zones: Any) -> np.ndarray:
    """La rejilla de incumplimientos esperada: ``−(partida − final)`` donde incumple un recinto de
    contar todo (corte, relleno, cualquier movimiento) y ``−(R − final)`` donde solo incumple uno de
    terreno; NaN en las demás."""
    start, final, base = case["start"], case["final"], case["base"]
    valid = np.isfinite(start) & np.isfinite(final)
    with np.errstate(invalid="ignore"):
        t = np.where(valid, start - final, 0.0)
        r = np.where(valid, np.fmin(start, base) - final, 0.0)
    cut, fill, terrain = valid & (t > E), valid & (-t > E), valid & (r > E)
    full = np.zeros(GRID.shape, dtype=bool)
    only = np.zeros(GRID.shape, dtype=bool)
    for zone in zones:
        mask = zone_mask(case, zone)
        if zone.counts is C.CUT:
            full |= mask & cut
        elif zone.counts is C.FILL:
            full |= mask & fill
        elif zone.counts is C.ANY:
            full |= mask & (cut | fill)
        elif zone.counts is C.CUT_TERRAIN:
            only |= mask & terrain
    return np.where(full, -t, np.where(only, -r, np.nan))


class AgainstBruteForceTest(unittest.TestCase):
    """RF-012-21, RF-012-22, RF-012-30: 20 casos al azar contra el cálculo celda a celda."""

    SEEDS = range(20)

    def test_every_zone(self) -> None:
        """(b) terreno + acopios = el corte de la 0.4 (≤ 10⁻⁹) en las cinco zonas, el veredicto y
        el recuento de cada recinto, y las demás zonas cuentan todo el movimiento (d)."""
        seen_exempt = seen_stock_complies = seen_stock_fails = seen_fail = seen_pass = 0
        for seed in self.SEEDS:
            case = random_case(seed)
            zones = build_zones(case, with_base=True)
            result = compliance.check(GRID, zones, case["start"], case["final"], E,
                                      band_rows=5, base=case["base"])
            reference = brute(case, zones, with_base=True)
            self.assertEqual([z.code for z in zones][:2], ["outside_perimeter", "outside_legal"])
            for item in result.totals:
                code, ref = item.code, reference[item.code]
                with self.subTest(seed=seed, zone=code):
                    close(self, item.cut_m3, ref["cut"] * AREA, "cut_m3")
                    close(self, item.fill_m3, ref["fill"] * AREA, "fill_m3")
                    self.assertEqual(item.moved_m2, ref["moved"] * AREA)
                    self.assertEqual(item.nodata_m2, ref["nodata"] * AREA)
                    if code in EXEMPT:
                        self.assertIs(item.counts, C.CUT_TERRAIN)
                        close(self, item.counted_m3, ref["terrain"] * AREA, "terreno")
                        close(self, item.stockpile_cut_m3, ref["stock"] * AREA, "acopios")
                        close(self, item.counted_m3 + item.stockpile_cut_m3, item.cut_m3,
                              "terreno + acopios = el corte")
                        counted_cells = ref["terrain_cells"]
                        seen_exempt += 1
                        seen_stock_complies += int(ref["stock"] > 0 and not counted_cells)
                        seen_stock_fails += int(ref["stock"] > 0 and counted_cells > 0)
                    else:
                        self.assertEqual(item.stockpile_cut_m3, 0.0)
                        self.assertIsNot(item.counts, C.CUT_TERRAIN)
                        counted_cells = {C.CUT: ref["cut_cells"], C.FILL: ref["fill_cells"],
                                         C.ANY: ref["moved"]}.get(item.counts, 0)
                    if item.counts in (C.CUT, C.FILL, C.ANY, C.CUT_TERRAIN):
                        expected = V.FAILS if counted_cells > 0 else V.COMPLIES
                        self.assertIs(item.verdict, expected)
                        seen_fail += int(expected is V.FAILS)
                        seen_pass += int(expected is V.COMPLIES)
        self.assertGreater(seen_exempt, 80)
        # Que el caso discrimine: acopios retirados que cumplen y que no, y de todo un poco.
        self.assertGreater(seen_stock_complies, 4)
        self.assertGreater(seen_stock_fails, 20)
        self.assertGreater(seen_fail, 40)
        self.assertGreater(seen_pass, 20)

    def test_the_full_zones_count_everything_with_or_without_the_base(self) -> None:
        """(d) RF-012-30: fuera del límite legal, intocable, exclusión, fuera del perímetro, sin
        relleno y preferible no afectar: los mismos totales con la base que sin ella."""
        for seed in self.SEEDS:
            case = random_case(seed)
            with_base = compliance.check(GRID, build_zones(case, with_base=True), case["start"],
                                         case["final"], E, base=case["base"])
            without = compliance.check(GRID, build_zones(case, with_base=False), case["start"],
                                       case["final"], E)
            for code in FULL:
                with self.subTest(seed=seed, zone=code):
                    self.assertEqual(dataclasses.astuple(with_base.zone(code)),
                                     dataclasses.astuple(without.zone(code)))
            for code in EXEMPT:  # lo que no cuenta de terreno es lo mismo que sin base
                a, b = with_base.zone(code), without.zone(code)
                self.assertEqual((a.cut_m3, a.fill_m3, a.moved_m2, a.nodata_m2),
                                 (b.cut_m3, b.fill_m3, b.moved_m2, b.nodata_m2))
                self.assertLessEqual(a.counted_m3, b.counted_m3 + 1e-9)

    def test_groups_and_violations_follow_the_terrain_cut(self) -> None:
        """RF-012-23, RF-012-30: los grupos de cada recinto suman lo que cuenta en él (el espesor de
        terreno en las cinco zonas) y la rejilla de incumplimientos marca ``final − partida`` donde
        incumple una zona de contar todo, y ``final − R`` donde solo incumple una de terreno."""
        for seed in self.SEEDS:
            case = random_case(seed)
            zones = build_zones(case, with_base=True)
            result = compliance.check(GRID, zones, case["start"], case["final"], E,
                                      band_rows=7, base=case["base"])
            reference = brute(case, zones, with_base=True)
            for item in result.totals:
                found = result.groups_of(item.code)
                with self.subTest(seed=seed, zone=item.code):
                    if item.counts in (C.AVOID, C.ACCESS, C.NOTHING):
                        self.assertEqual(found, ())
                        continue
                    close(self, math.fsum(g.volume_m3 for g in found), item.counted_m3, "volumen")
                    ref = reference[item.code]
                    cells = {C.CUT_TERRAIN: ref["terrain_cells"], C.CUT: ref["cut_cells"],
                             C.FILL: ref["fill_cells"], C.ANY: ref["moved"]}[item.counts]
                    self.assertEqual(sum(g.cells for g in found), cells)
            expected = expected_violations(case, zones)
            with self.subTest(seed=seed, what="rejilla"):
                if np.isfinite(expected).any():
                    self.assertTrue(np.array_equal(result.violations, expected, equal_nan=True))
                else:
                    self.assertIsNone(result.violations)


# --- Sin base, lo de antes, bit a bit ------------------------------------------------------------


class WithoutBaseTest(unittest.TestCase):
    """(c) RF-012-30: sin base, el mismo resultado bit a bit (``np.array_equal``)."""

    SEEDS = range(20)

    def test_a_base_with_no_terrain_zone_is_ignored(self) -> None:
        """Con los recintos de siempre (``Counts.CUT``), dar una base no cambia nada."""
        for seed in self.SEEDS:
            case = random_case(seed)
            zones = build_zones(case, with_base=False)
            with self.subTest(seed=seed):
                self.assertNotIn(C.CUT_TERRAIN, {zone.counts for zone in zones})
                plain = compliance.check(GRID, zones, case["start"], case["final"], E)
                given = compliance.check(GRID, zones, case["start"], case["final"], E,
                                         base=case["base"])
                assert_same(self, plain, given)
                self.assertTrue(all(item.stockpile_cut_m3 == 0.0 for item in plain.totals))

    def test_terrain_zones_without_a_base_are_the_old_cut_zones(self) -> None:
        """Los recintos de terreno sin base cuentan como ``Counts.CUT``: todo igual salvo el
        modo."""
        for seed in self.SEEDS:
            case = random_case(seed)
            old = compliance.check(GRID, build_zones(case, with_base=False), case["start"],
                                   case["final"], E)
            for band_rows in (256, 5):
                with self.subTest(seed=seed, band_rows=band_rows):
                    new = compliance.check(GRID, build_zones(case, with_base=True),
                                           case["start"], case["final"], E, band_rows=band_rows)
                    assert_same(self, old, new, ignore_counts=True)

    def test_a_base_that_changes_nothing(self) -> None:
        """Una base sin ningún dato, o por encima de la partida en todas partes, da lo de antes."""
        for seed in self.SEEDS:
            case = random_case(seed)
            old = compliance.check(GRID, build_zones(case, with_base=False), case["start"],
                                   case["final"], E)
            empty = np.full(GRID.shape, NAN)
            above = np.nan_to_num(case["start"], nan=100.0) + 1.0
            for name, base in (("sin dato", empty), ("por encima", above)):
                with self.subTest(seed=seed, base=name):
                    new = compliance.check(GRID, build_zones(case, with_base=True), case["start"],
                                           case["final"], E, base=base, band_rows=6)
                    assert_same(self, old, new, ignore_counts=True)

    def test_bands_of_any_size_give_the_same_with_a_base(self) -> None:
        """RF-012-21: por bandas (unas con base y otras sin ella) sale lo mismo que de una vez: los
        grupos y la rejilla, bit a bit; las sumas de m³, a 10⁻¹² (cambia el orden de sumar)."""
        for seed in self.SEEDS:
            case = random_case(seed)
            zones = build_zones(case, with_base=True)
            whole = compliance.check(GRID, zones, case["start"], case["final"], E,
                                     base=case["base"], band_rows=GRID.nrows)
            for band_rows in (1, 4, 7):
                with self.subTest(seed=seed, band_rows=band_rows):
                    split = compliance.check(GRID, zones, case["start"], case["final"], E,
                                             base=case["base"], band_rows=band_rows)
                    for one, other in zip(whole.totals, split.totals, strict=True):
                        for name in ("cut_m3", "fill_m3", "counted_m3", "stockpile_cut_m3"):
                            self.assertTrue(math.isclose(getattr(one, name), getattr(other, name),
                                                         rel_tol=1e-12, abs_tol=1e-12), name)
                        self.assertEqual((one.code, one.counts, one.moved_m2, one.nodata_m2,
                                          one.verdict),
                                         (other.code, other.counts, other.moved_m2,
                                          other.nodata_m2, other.verdict))
                    self.assertEqual(groups_of(whole), groups_of(split))
                    self.assertIs(whole.violations is None, split.violations is None)
                    if whole.violations is not None:
                        self.assertTrue(np.array_equal(whole.violations, split.violations,
                                                       equal_nan=True))


# --- Una celda en dos recintos -------------------------------------------------------------------


class TwoZonesTest(unittest.TestCase):
    """RF-012-30, plan 012 A8: una celda en una zona de terreno y en un intocable cuenta en las dos,
    cada una a su manera (el intocable, todo el movimiento; la de terreno, el de terreno)."""

    def test_untouchable_counts_everything(self) -> None:
        grid = gis.Grid(0.0, 4.0, 1.0, 1.0, 4, 4)
        start = np.full(grid.shape, 10.0)
        start[0, 0:2] = 13.0
        base = np.full(grid.shape, NAN)
        base[0, 0:2] = 10.0
        final = np.full(grid.shape, 10.0)
        final[0, 0] = 9.0   # bajo la base: 4 m de corte, 1 de terreno
        final[3, 3] = 9.5   # terreno: 0,5 m
        mask = np.zeros(grid.shape, dtype=bool)
        mask[0, :2] = True
        zones = compliance.check_zones(
            classes_inside(grid),
            {"r_nocut": runs_of(np.ones(grid.shape, dtype=bool)), "r_intocable": runs_of(mask)},
            {"r_nocut": T.NO_CUT, "r_intocable": T.UNTOUCHABLE}, with_base=True)
        result = compliance.check(grid, zones, start, final, E, base=base)
        nocut, untouchable = result.zone("r_nocut"), result.zone("r_intocable")
        self.assertEqual((nocut.cut_m3, nocut.counted_m3, nocut.stockpile_cut_m3),
                         (4.0 + 3.0 + 0.5, 1.5, 6.0))
        self.assertIs(nocut.verdict, V.FAILS)
        self.assertEqual((untouchable.cut_m3, untouchable.counted_m3,
                          untouchable.stockpile_cut_m3), (7.0, 7.0, 0.0))
        self.assertIs(untouchable.verdict, V.FAILS)
        # Los grupos: los de terreno (1 m³ en la celda (0,0) y 0,5 m³ en la (3,3)) y el
        # intocable (7 m³, con todo el espesor).
        self.assertEqual(sorted((g.zone, g.cells, g.volume_m3) for g in result.groups),
                         [("r_intocable", 2, 7.0), ("r_nocut", 1, 0.5), ("r_nocut", 1, 1.0)])
        # La rejilla: ``final − partida`` donde incumple la intocable; ``final − R``, solo la
        # de terreno.
        self.assertEqual(result.violations[0, 0], -4.0)
        self.assertEqual(result.violations[0, 1], -3.0)
        self.assertEqual(result.violations[3, 3], -0.5)
        self.assertEqual(int(np.isfinite(result.violations).sum()), 3)

    def test_stockpile_only_cut_does_not_fail_the_terrain_zone(self) -> None:
        grid = gis.Grid(0.0, 4.0, 1.0, 1.0, 4, 4)
        start = np.full(grid.shape, 10.0)
        start[0, 0:2] = 13.0
        base = np.full(grid.shape, NAN)
        base[0, 0:2] = 10.0
        final = np.full(grid.shape, 10.0)
        mask = np.zeros(grid.shape, dtype=bool)
        mask[0, :2] = True
        zones = compliance.check_zones(
            classes_inside(grid),
            {"r_nocut": runs_of(np.ones(grid.shape, dtype=bool)), "r_intocable": runs_of(mask)},
            {"r_nocut": T.NO_CUT, "r_intocable": T.UNTOUCHABLE}, with_base=True)
        result = compliance.check(grid, zones, start, final, E, base=base)
        self.assertIs(result.zone("r_nocut").verdict, V.COMPLIES)
        self.assertIs(result.zone("r_intocable").verdict, V.FAILS)
        self.assertEqual([g.zone for g in result.groups], ["r_intocable"])


# --- Los recintos, el modo de contar y la petición ----------------------------------------------


class ModesTest(unittest.TestCase):
    """RF-012-22, RF-012-30: el modo de contar de cada recinto con y sin base."""

    def test_counts_of_with_a_base(self) -> None:
        for ctype in (T.NO_CUT, T.FILL_ONLY, T.RESTORATION_ONLY, T.SETBACK):
            with self.subTest(ctype=ctype):
                self.assertIs(compliance.counts_of("r_x", ctype), C.CUT)
                self.assertIs(compliance.counts_of("r_x", ctype, with_base=True), C.CUT_TERRAIN)
        self.assertIs(compliance.counts_of("r_x:inner", T.LEGAL_LIMIT), C.CUT)
        self.assertIs(compliance.counts_of("r_x:inner", T.LEGAL_LIMIT, with_base=True),
                      C.CUT_TERRAIN)
        # Fuera del límite legal y las demás zonas: todo el movimiento, con o sin base.
        expected = {"outside_perimeter": (None, C.ANY), "outside_legal": (None, C.CUT),
                    "r_a": (T.UNTOUCHABLE, C.ANY), "r_b": (T.EXCLUSION, C.ANY),
                    "r_c": (T.NO_FILL, C.FILL), "r_d": (T.AVOID, C.AVOID),
                    "r_e": (T.REQUIRES_ACCESS, C.ACCESS), "r_f": (T.LEGAL_LIMIT, C.NOTHING),
                    "r_g": (T.ACTION_PERIMETER, C.NOTHING)}
        for code, (ctype, counts) in expected.items():
            with self.subTest(code=code):
                self.assertIs(compliance.counts_of(code, ctype), counts)
                self.assertIs(compliance.counts_of(code, ctype, with_base=True), counts)
        with self.assertRaises(ValueError):
            compliance.counts_of("r_x:inner", T.NO_CUT, with_base=True)

    def test_zones_with_a_base(self) -> None:
        case = random_case(0)
        plain = build_zones(case, with_base=False)
        based = build_zones(case, with_base=True)
        self.assertEqual([z.code for z in plain], [z.code for z in based])
        for old, new in zip(plain, based, strict=True):
            self.assertIs(new.counts, C.CUT_TERRAIN if new.code in EXEMPT else old.counts)
            self.assertEqual((old.code, old.ctype, old.weight, old.runs),
                             (new.code, new.ctype, new.weight, new.runs))
        steps = compliance.check_zones_steps(case["classes"], case["zones"], CTYPES, WEIGHTS,
                                             with_base=True)
        while True:
            try:
                next(steps)
            except StopIteration as stop:
                stepped = stop.value
                break
        self.assertEqual([(z.code, z.counts) for z in stepped],
                         [(z.code, z.counts) for z in based])

    def test_the_new_mode_is_a_counted_mode(self) -> None:
        self.assertEqual(C.CUT_TERRAIN.value, "cut_terrain")


class LowestBaseTest(unittest.TestCase):
    """RF-012-30, P-10: con varias bases, la menor (el lado seguro); sin dato donde ninguna lo
    da."""

    def test_the_lowest_where_both_have_data(self) -> None:
        a = np.array([[NAN, 5.0, 7.0], [NAN, NAN, 1.0]])
        b = np.array([[NAN, 6.0, NAN], [2.0, NAN, 0.5]])
        found = compliance.lowest_base([a, b])
        expected = np.array([[NAN, 5.0, 7.0], [2.0, NAN, 0.5]])
        self.assertTrue(np.array_equal(found, expected, equal_nan=True))
        self.assertIs(compliance.lowest_base([a]), a)
        self.assertIsNone(compliance.lowest_base([]))
        untouched = np.array([[NAN, 5.0, 7.0], [NAN, NAN, 1.0]])
        self.assertTrue(np.array_equal(a, untouched, equal_nan=True))

    def test_the_bands_must_agree(self) -> None:
        with self.assertRaises(ValueError):
            compliance.lowest_base([np.zeros((2, 3)), np.zeros((2, 4))])


class RequestTest(unittest.TestCase):
    """RF-012-24, RF-012-30: la petición, con la base opcional."""

    def request(self, **extra: Any) -> Any:
        masks = access.MaskSet(GRID_A, "v" * 32, "o" * 32, access.MaskState.CURRENT, (),
                               classes_inside(GRID_A))
        start = surfaces.SurfaceRef(dataset="gis_dtm_inicial")
        finals = (surfaces.SurfaceRef(dataset="gis_dtm_final"),)
        return compliance.ComplianceRequest("V1", start, finals, masks, 0.02, **extra)

    def test_without_a_base(self) -> None:
        self.assertEqual(self.request().bases, ())

    def test_with_bases(self) -> None:
        bases = (surfaces.SurfaceRef(dataset="des_stb_a", label="Detección 1"),
                 surfaces.SurfaceRef(dataset="des_stb_b"))
        request = self.request(bases=list(bases))
        self.assertEqual(request.bases, bases)

    def test_a_base_is_a_grid_and_not_repeated(self) -> None:
        one = surfaces.SurfaceRef(dataset="des_stb_a")
        for bad in ((surfaces.SurfaceRef(elevation=100.0),), (one, one), ("des_stb_a",)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.request(bases=bad)


if __name__ == "__main__":
    unittest.main()
