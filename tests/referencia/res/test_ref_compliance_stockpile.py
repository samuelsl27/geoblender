# SPDX-License-Identifier: GPL-3.0-or-later
"""Casos de referencia de la verificación con la base de los acopios (spec 016, T31; HU-016-2; RF-012-21,
RF-012-22, RF-012-24, RF-012-30, RF-012-31; DIFF-012 de la 016, §4 (a) a (e); CE-012-02, CE-012-03, CE-012-05,
CE-012-06; plan 016 §5.4 A12 y §7.1; constitución, principio 2).

Una retirada de acopio baja el material por encima de la base de un acopio, que no es terreno: en las cinco zonas del
dominio por defecto (sin corte, solo relleno, solo restauración, banda de resguardo y banda hacia dentro de un límite
legal) cuenta como **corte de terreno** solo lo que baja de ``R = mín(partida, base)`` y el resto es **corte de acopios**
(RF-012-30). Cada cifra esperada sale del enunciado o de un bucle de Python sobre las celdas (``hand_cut`` y
``hand_terrain``: ningún valor se calcula llamando al código bajo prueba); el error relativo es ≤ 10⁻⁹ (RF-012-21).

- **(a)** (:class:`CaseATest`): rejilla de 10 × 10 celdas de 1 m, terreno a 100 m, acopio de 4 × 4 celdas hasta 103 m
  (su base, a 100 m, solo en su huella), zona sin corte en toda la rejilla: retirado a 100 m, corte de terreno 0 m³, de
  acopios 48 m³, «cumple»; con una celda a 99,5 m (fuera o dentro del acopio, bajo su base), 0,5 m³ de terreno,
  48 m³ de acopios y «no cumple»; **en cada una de las cinco zonas**.
- **(b)** terreno + acopios = el corte de la 0.4 (la verificación sin base) a ≤ 10⁻⁹ relativo, en cada zona y en seis
  finales distintas.
- **(c)** (:class:`WithoutStockpilesTest`) sin acopios, idéntico bit a bit (la base ausente, sin dato o por encima de la
  partida no cambia nada) y **CE-012-02, CE-012-03, CE-012-05 y CE-012-06 iguales con y sin base**: la torre rebajada, la
  franja fuera del límite, la balsa con su relleno, y las 100 superficies que cortan solo en el corte admitido del caso a
  mano de los once tipos; con dientes: un corte de 3 m en una celda de cada una de las cinco zonas cumple dentro de la
  base (3 m³ de acopios) y no cumple fuera de ella. Los **diseños de la 013, 014 y 015** (los 100 de CE-013-06, los mismos
  sobre las máscaras de la cantera de la 014 y el relleno de la 015 de CE-016-03) con y sin base, en el hito.
- **(d)** (:class:`NotExemptTest`) las zonas no exentas (fuera del límite legal, fuera del perímetro, intocable,
  exclusión, sin relleno y preferible no afectar) cuentan **todo** el movimiento, con o sin base.
- **(e)** (:class:`RejectionTest`) una base en otra rejilla, otro CRS u otro datum se rechaza como RF-011-03 nombrando la
  base; lo que no se usa (una detección obsoleta o hecha sobre otra partida) se avisa con su detección y su causa
  (RF-012-31). La detección obsoleta con el proyecto, y la verificación de la retirada real en cada zona (CE-016-03,
  completo), están en ``tests/unit/reserves/milestone_ref_compliance_stockpile.py`` (P-13: proyecto de 2 m).
"""

from __future__ import annotations

import dataclasses
import math
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

from tests.referencia.res import test_ref_compliance as site012
from tests.support import constraints_fixtures as fx
from tests.support.package import import_geoblender
from tests.unit.gis.masks import test_combine as hand

gis = import_geoblender("gis")
model = import_geoblender("core.constraints.model")
combine = import_geoblender("gis.masks.combine")
zones_mod = import_geoblender("gis.masks.zones")
surfaces = import_geoblender("reserves.surfaces")
compliance = import_geoblender("reserves.compliance")
cstore = import_geoblender("reserves.compliance_store")
res_messages = import_geoblender("reserves.messages")

T = model.ConstraintType
Bit = combine.ClassBit
C = compliance.Counts
V = compliance.Verdict
NAN = math.nan
E = 0.02
"""El espesor mínimo de verificación (D-6)."""
REL = 1e-9
GRID = gis.Grid(500000.0, 4400010.0, 1.0, 1.0, 10, 10)
"""10 × 10 celdas de 1 m (la fila 0 es la del norte)."""
BLOCK = (slice(3, 7), slice(3, 7))
"""El acopio: 4 × 4 celdas (las filas y las columnas 3 a 6)."""
FIVE = ("sin_corte", "solo_relleno", "solo_restauracion", "resguardo", "concesion:inner")
"""Las cinco zonas del dominio por defecto, por su código (la banda hacia dentro es ``<límite>:inner``)."""
ZONE_TYPES = {"sin_corte": T.NO_CUT, "solo_relleno": T.FILL_ONLY, "solo_restauracion": T.RESTORATION_ONLY,
              "resguardo": T.SETBACK, "concesion": T.LEGAL_LIMIT}


def close(test: unittest.TestCase, found: float, expected: float, what: str = "") -> None:
    test.assertTrue(math.isclose(found, expected, rel_tol=REL, abs_tol=1e-9), f"{what}: {found!r} frente a {expected!r}")


def runs_of(mask: np.ndarray) -> Any:
    rows, cols = np.nonzero(mask)
    return zones_mod.Runs(rows, cols, cols + 1)


# --- El enunciado (a), a mano -------------------------------------------------------------------


def terrain() -> np.ndarray:
    return np.full(GRID.shape, 100.0)


def start() -> np.ndarray:
    """El terreno a 100 m con el acopio de 4 × 4 celdas hasta 103 m."""
    found = terrain()
    found[BLOCK] = 103.0
    return found


def base() -> np.ndarray:
    """La base del acopio: 100 m en su huella y sin dato fuera."""
    found = np.full(GRID.shape, NAN)
    found[BLOCK] = 100.0
    return found


def finals() -> dict[str, tuple[np.ndarray, float, float, float, V]]:
    """Las finales con lo que da a mano cada una: (cotas, corte de RF-012-21, corte de terreno, corte de acopios,
    veredicto en una zona sin corte)."""
    outside, inside = terrain(), terrain()
    outside[0, 0] = 99.5  # una celda de fuera del acopio, por debajo del terreno
    inside[4, 4] = 99.5  # una celda del acopio, por debajo de su base
    return {
        "retirada": (terrain(), 48.0, 0.0, 48.0, V.COMPLIES),
        "celda_fuera": (outside, 48.5, 0.5, 48.0, V.FAILS),
        "celda_dentro": (inside, 48.5, 0.5, 48.0, V.FAILS),
        "mitad": (np.full(GRID.shape, 101.5), 24.0, 0.0, 24.0, V.COMPLIES),  # 16 celdas bajan 1,5 m; lo demás, relleno
        "hondo": (np.full(GRID.shape, 98.0), 248.0, 200.0, 48.0, V.FAILS),  # 84 · 2 + 16 · 5; terreno: 84 · 2 + 16 · 2
        "relleno": (np.full(GRID.shape, 110.0), 0.0, 0.0, 0.0, V.COMPLIES),
    }


def hand_cut(from_: np.ndarray, final: np.ndarray) -> float:
    """El corte de RF-012-21 de la rejilla entera, a mano: la suma de ``partida − final`` de las celdas que pasan del
    espesor mínimo (celdas de 1 m²)."""
    return math.fsum(s - f for s, f in zip(from_.ravel().tolist(), final.ravel().tolist(), strict=True) if s - f > E)


def hand_terrain(from_: np.ndarray, below: np.ndarray, final: np.ndarray) -> float:
    """El corte de terreno de RF-012-30, a mano: ``R = mín(partida, base)`` donde hay base y ``R = partida`` donde no."""
    found = []
    for s, b, f in zip(from_.ravel().tolist(), below.ravel().tolist(), final.ravel().tolist(), strict=True):
        r = s if math.isnan(b) else min(s, b)
        if r - f > E:
            found.append(r - f)
    return math.fsum(found)


def classes_inside() -> np.ndarray:
    return np.full(GRID.shape, np.uint16(Bit.PERIMETER) | np.uint16(Bit.LEGAL), dtype=np.uint16)


def zone_of(code: str, *, with_base: bool) -> Any:
    """Los recintos de la rejilla con ``code`` en toda ella (``with_base``: la verificación tiene base de acopios)."""
    ctypes = {code.removesuffix(":inner"): ZONE_TYPES[code.removesuffix(":inner")]}
    whole = runs_of(np.ones(GRID.shape, dtype=bool))
    return compliance.check_zones(classes_inside(), {code: whole}, ctypes, with_base=with_base)


def counting_with_base(zones: Any) -> Any:
    """Los mismos recintos con el modo de contar de la verificación con base (``check_zones(with_base=True)``): en los de
    tipo, el corte de terreno donde hoy cuenta el corte."""
    return tuple(dataclasses.replace(z, counts=compliance.counts_of(z.code, z.ctype, with_base=True))
                 if z.ctype is not None else z for z in zones)


def totals_of(result: Any) -> list[tuple[Any, ...]]:
    """Los totales sin lo que cuenta cada recinto (su modo, que es lo único que cambia con la base)."""
    return [dataclasses.astuple(dataclasses.replace(item, counts=C.CUT)) for item in result.totals]


def groups_of(result: Any) -> list[tuple[Any, ...]]:
    return [(g.zone, g.cells, g.area_m2, g.volume_m3, g.max_m, g.center, g.box, g.rows.tolist(), g.cols.tolist())
            for g in result.groups]


def assert_identical(test: unittest.TestCase, a: Any, b: Any) -> None:
    """Bit a bit: totales (salvo lo que cuenta en cada recinto), grupos y rejilla de incumplimientos (RF-012-30: sin
    acopios, lo de siempre)."""
    test.assertEqual(totals_of(a), totals_of(b))
    test.assertEqual(groups_of(a), groups_of(b))
    test.assertIs(a.violations is None, b.violations is None)
    if a.violations is not None:
        test.assertTrue(np.array_equal(a.violations, b.violations, equal_nan=True))
    test.assertEqual((a.same_surface, [n.code for n in a.notices]), (b.same_surface, [n.code for n in b.notices]))


# --- (a) y (b) -----------------------------------------------------------------------------------


class CaseATest(unittest.TestCase):
    """RF-012-21, RF-012-22, RF-012-30: el caso (a) del diff, a mano, en las cinco zonas."""

    def test_the_hand_figures_of_the_statement(self) -> None:
        """RF-012-21, RF-012-30: las cifras de ``finals`` son las del enunciado: la retirada, 48 m³ de corte (16 celdas · 3 m) y 0 de terreno;
        con una celda a 99,5 m, 0,5 m³ de terreno (fuera o dentro del acopio); a mano, celda a celda."""
        for name, (final, cut, terrain_m3, stockpile_m3, _verdict) in finals().items():
            with self.subTest(final=name):
                close(self, hand_cut(start(), final), cut, "corte")
                close(self, hand_terrain(start(), base(), final), terrain_m3, "terreno")
                close(self, cut - terrain_m3, stockpile_m3, "acopios")

    def test_the_removal_complies_with_the_base_in_every_zone(self) -> None:
        """RF-012-30, RF-012-22: retirado a 100 m, corte de terreno 0 m³, de acopios 48 m³ y «cumple» en cada una de las cinco
        zonas; con una celda a 99,5 m (fuera o dentro del acopio), 0,5 m³ de terreno, 48 m³ de acopios y «no cumple» con
        0,5 m³ en un grupo de 1 celda; ninguna zona se queda sin el modo nuevo de contar."""
        for code in FIVE:
            for name, (final, cut, terrain_m3, stockpile_m3, verdict) in finals().items():
                with self.subTest(zona=code, final=name):
                    zones = zone_of(code, with_base=True)
                    result = compliance.check(GRID, zones, start(), final, E, base=base())
                    found = result.zone(code)
                    self.assertEqual(found.counts, C.CUT_TERRAIN)
                    close(self, found.cut_m3, cut, "corte de RF-012-21")
                    close(self, found.counted_m3, terrain_m3, "corte de terreno")
                    close(self, found.stockpile_cut_m3, stockpile_m3, "corte de acopios")
                    self.assertIs(found.verdict, verdict)
                    self.assertEqual(result.fails, verdict is V.FAILS)
                    if verdict is V.FAILS and name.startswith("celda"):
                        (group,) = result.groups_of(code)
                        self.assertEqual((group.cells, group.area_m2), (1, 1.0))
                        close(self, group.volume_m3, 0.5, "el grupo")
                        close(self, group.max_m, 0.5, "su espesor")

    def test_without_the_base_everything_counts(self) -> None:
        """RF-012-21, RF-012-22 (la 0.4): sin base, todo el corte de la retirada cuenta (48 m³) y «no cumple» en cada zona."""
        for code in FIVE:
            with self.subTest(zona=code):
                found = compliance.check(GRID, zone_of(code, with_base=False), start(), terrain(), E).zone(code)
                self.assertEqual((found.counts, found.verdict, found.stockpile_cut_m3), (C.CUT, V.FAILS, 0.0))
                close(self, found.counted_m3, 48.0)
                close(self, found.cut_m3, 48.0)


class SumTest(unittest.TestCase):
    """(b) RF-012-30, RF-012-21: terreno + acopios = el corte de la 0.4 a ≤ 10⁻⁹ relativo."""

    def test_terrain_plus_stockpiles_is_the_old_cut_in_every_zone(self) -> None:
        """RF-012-30, RF-012-21: en cada una de las cinco zonas y en las seis finales, el corte de RF-012-21 de la verificación
        con base es el corte de la 0.4 (la misma verificación sin base: todo el corte cuenta), terreno + acopios es ese corte,
        el corte de terreno es el de a mano y el relleno, el área con movimiento y el área sin dato no cambian."""
        for code in FIVE:
            for name, (final, cut, _terrain_m3, _stockpile_m3, _verdict) in finals().items():
                with self.subTest(zona=code, final=name):
                    old = compliance.check(GRID, zone_of(code, with_base=False), start(), final, E).zone(code)
                    new = compliance.check(GRID, zone_of(code, with_base=True), start(), final, E, base=base()).zone(code)
                    self.assertEqual(old.counts, C.CUT)
                    close(self, old.counted_m3, cut, "el corte de la 0.4, a mano")
                    close(self, new.cut_m3, old.counted_m3, "el corte de RF-012-21 con base")
                    close(self, new.counted_m3 + new.stockpile_cut_m3, old.counted_m3, "terreno + acopios")
                    close(self, new.counted_m3, hand_terrain(start(), base(), final), "terreno, a mano")
                    for field in ("fill_m3", "moved_m2", "nodata_m2"):
                        self.assertEqual(getattr(new, field), getattr(old, field), field)


# --- (c) ------------------------------------------------------------------------------------------


class WithoutStockpilesTest(unittest.TestCase):
    """(c) RF-012-30: sin acopios, el resultado de siempre (bit a bit), y CE-012-02, 03, 05 y 06 iguales con y sin base."""

    def test_no_base_or_one_that_changes_nothing_is_the_old_result_bit_for_bit(self) -> None:
        """RF-012-30, RF-012-21 (c): sin base, con una base sin dato en ninguna celda y con una base por encima de la partida (R = partida): los
        mismos totales, grupos y rejilla de incumplimientos que la 0.4, en las cinco zonas y las seis finales."""
        above = start() + 5.0
        for code in FIVE:
            for name, (final, *_rest) in finals().items():
                old = compliance.check(GRID, zone_of(code, with_base=False), start(), final, E)
                for label, given in (("sin base", None), ("sin dato", np.full(GRID.shape, NAN)), ("por encima", above)):
                    with self.subTest(zona=code, final=name, base=label):
                        new = compliance.check(GRID, zone_of(code, with_base=True), start(), final, E, base=given)
                        assert_identical(self, new, old)
                        self.assertEqual(new.zone(code).stockpile_cut_m3, 0.0)

    def test_the_site_cases_ce_012_02_03_06_are_the_same_with_and_without_a_base(self) -> None:
        """CE-012-02 (la torre, 6.384 m³), CE-012-03 (la franja, 4.800 m³ de corte fuera del límite) y CE-012-06 (la balsa,
        4.300 m³; las encinas, sin juicio; el camino, sin comprobar): con una base de acopios en todo el sitio (3 m por
        debajo de la partida), los mismos totales y grupos que sin ella."""
        zones, _masks = site012.site_zones()
        zones_with = counting_with_base(zones)
        origin = fx.site_start().values
        below = origin - 3.0
        pond = fx.pond_case()
        values = pond.final.values.copy()
        x, y = fx.site_centers()
        for box, change in ((site012.AVOID_BOX, -1.0), (site012.ACCESS_BOX, 2.0)):
            inside = (x > box[0]) & (x < box[2]) & (y > box[1]) & (y < box[3])
            values[inside] = fx.START_Z + change
        cases = {"CE-012-02": fx.tower_case().final.values, "CE-012-02 respetuosa": fx.tower_case(respectful=True).final.values,
                 "CE-012-03": fx.strip_case().final.values, "CE-012-03 relleno": fx.strip_case(fill=True).final.values,
                 "CE-012-06": values}
        found = {}
        for name, final in cases.items():
            with self.subTest(caso=name):
                old = compliance.check(fx.SITE_GRID, zones, origin, final, E)
                new = compliance.check(fx.SITE_GRID, zones_with, origin, final, E, base=below)
                assert_identical(self, new, old)
                found[name] = new
        close(self, found["CE-012-02"].zone("r_torre").counted_m3, 6_384.0)
        close(self, found["CE-012-03"].zone(compliance.OUTSIDE_LEGAL).counted_m3, 4_800.0)
        close(self, found["CE-012-06"].zone("r_balsa").counted_m3, 4_300.0)
        self.assertIs(found["CE-012-06"].zone("r_encinas").verdict, V.NOT_JUDGED)
        self.assertIs(found["CE-012-06"].zone("r_camino").verdict, V.UNCHECKED)
        self.assertEqual([t.code for t in found["CE-012-02"].totals if t.verdict is V.FAILS], ["r_torre"])

    def test_ce_012_05_hundred_surfaces_and_the_teeth_in_the_five_zones(self) -> None:
        """CE-012-05: las 100 superficies que cortan solo en el corte admitido y rellenan solo en el relleno admitido (con
        ruido bajo el umbral y celdas sin dato) del caso a mano de los once tipos dan 0 m³ en todos los recintos **con y
        sin** una base de acopios (a 4 m por debajo de la partida en la mitad de las celdas): lo mismo bit a bit. Con
        dientes: un corte de 3 m en una celda de cada una de las cinco zonas (donde solo ella cuenta el corte) no cumple
        sin base ni con una base que no la cubre y cumple, con 3 m³ de corte de acopios, dentro de la base."""
        items, resolved = hand.site()
        zones, masks = site012.compile_zones(items, resolved, hand.GRID)
        zones_with = counting_with_base(zones)
        grid = hand.GRID
        shape = grid.shape
        cut_ok, fill_ok = masks.cut_allowed.mask(shape), masks.fill_allowed.mask(shape)
        rng, base_rng = np.random.default_rng(5), np.random.default_rng(6)
        origin = 400.0 + rng.uniform(-5.0, 5.0, shape)
        for case in range(100):
            choice = rng.integers(0, 3, shape)  # 0: nada; 1: corte; 2: relleno
            depth = rng.uniform(0.03, 9.0, shape)
            noise = rng.uniform(-E, E, shape)  # lo que no pasa el umbral
            difference = np.where((choice == 1) & cut_ok, depth, noise)
            difference = np.where((choice == 2) & fill_ok, -depth, difference)
            final = origin - difference
            final[rng.random(shape) < 0.03] = np.nan
            below = np.where(base_rng.random(shape) < 0.5, origin - 4.0, np.nan)
            with self.subTest(case=case):
                old = compliance.check(grid, zones, origin, final, E, band_rows=7)
                new = compliance.check(grid, zones_with, origin, final, E, band_rows=7, base=below)
                assert_identical(self, new, old)
                for item in new.totals:
                    if item.counts in (C.CUT, C.CUT_TERRAIN, C.FILL, C.ANY):
                        self.assertEqual((item.counted_m3, item.stockpile_cut_m3), (0.0, 0.0), item.code)
                    self.assertIsNot(item.verdict, V.FAILS, item.code)
                self.assertEqual(new.groups, ())
        inside = {z.code: z.runs.mask(shape) for z in zones_with}
        for code in ("r_sin_corte", "r_solo_relleno", "r_restauracion", "r_banda", "r_concesion:inner"):
            others = np.zeros(shape, dtype=bool)
            for z in zones_with:
                if z.code != code and z.counts in (C.CUT, C.CUT_TERRAIN, C.ANY):
                    others |= inside[z.code]
            cells = np.argwhere(inside[code] & ~others)
            self.assertGreater(len(cells), 0, code)
            row, col = (int(v) for v in cells[len(cells) // 2])
            final = origin.copy()
            final[row, col] = origin[row, col] - 3.0
            covering = np.full(shape, np.nan)
            covering[row, col] = origin[row, col] - 4.0
            other = (0, 0) if (row, col) != (0, 0) else (1, 1)
            elsewhere = np.full(shape, np.nan)
            elsewhere[other] = origin[other] - 4.0
            with self.subTest(zona=code):
                for label, given in (("sin base", None), ("sin cubrirla", elsewhere)):
                    failing = compliance.check(grid, zones_with, origin, final, E, base=given)
                    self.assertEqual([t.code for t in failing.totals if t.verdict is V.FAILS], [code], label)
                    close(self, failing.zone(code).counted_m3, 3.0, label)
                covered = compliance.check(grid, zones_with, origin, final, E, base=covering)
                self.assertFalse(covered.fails)
                self.assertEqual((covered.zone(code).counted_m3, covered.zone(code).stockpile_cut_m3), (0.0, 3.0))
                self.assertEqual(covered.zone(code).cut_m3, 3.0)


# --- (d) ------------------------------------------------------------------------------------------


class NotExemptTest(unittest.TestCase):
    """(d) RF-012-22, RF-012-30: fuera del límite legal, fuera del perímetro, intocable, exclusión, sin relleno y preferible
    no afectar cuentan **todo** el movimiento, con la base cubriendo sus celdas o sin ella."""

    KINDS = {"outside_legal": None, "outside_perimeter": None, "torre": T.UNTOUCHABLE, "cantera": T.EXCLUSION,
             "balsa": T.NO_FILL, "encinas": T.AVOID}

    def scenario(self, kind: str) -> Any:
        """Los recintos con el acopio en ``kind`` (los dos de fuera, por los bits de la rejilla de clases)."""
        classes = classes_inside()
        block = np.zeros(GRID.shape, dtype=bool)
        block[BLOCK] = True
        zones: dict[str, Any] = {}
        ctypes: dict[str, Any] = {}
        if kind == "outside_legal":
            classes[block] &= ~np.uint16(Bit.LEGAL)
        elif kind == "outside_perimeter":
            classes[block] &= ~np.uint16(Bit.PERIMETER)
        else:
            zones[kind], ctypes[kind] = runs_of(block), self.KINDS[kind]
        weights = {"encinas": 2.5} if kind == "encinas" else None
        return lambda with_base_: compliance.check_zones(classes, zones, ctypes, weights, with_base=with_base_)

    def test_the_removal_counts_everything_with_and_without_the_base(self) -> None:
        """RF-012-22, RF-012-30 (d): la retirada (48 m³ de corte en la huella) cuenta entera en el límite legal (corte), fuera del perímetro,
        intocable y exclusión (cualquier movimiento: 48 m³, «no cumple»); en la balsa (sin relleno) no cuenta (sin relleno,
        «cumple») y su afección en las encinas (peso 2,5: 120 m³ ponderados) no se juzga; con la base, lo mismo."""
        expected = {"outside_legal": (V.FAILS, 48.0), "outside_perimeter": (V.FAILS, 48.0), "torre": (V.FAILS, 48.0),
                    "cantera": (V.FAILS, 48.0), "balsa": (V.COMPLIES, 0.0), "encinas": (V.NOT_JUDGED, 48.0)}
        for kind, (verdict, counted) in expected.items():
            with self.subTest(zona=kind):
                zones = self.scenario(kind)
                old = compliance.check(GRID, zones(False), start(), terrain(), E)
                new = compliance.check(GRID, zones(True), start(), terrain(), E, base=base())
                code = {"outside_legal": compliance.OUTSIDE_LEGAL,
                        "outside_perimeter": compliance.OUTSIDE_PERIMETER}.get(kind, kind)
                found = new.zone(code)
                self.assertIs(found.verdict, verdict)
                close(self, found.counted_m3 if verdict is not V.NOT_JUDGED else found.cut_m3, counted)
                self.assertEqual(found.stockpile_cut_m3, 0.0)
                self.assertEqual([dataclasses.astuple(item) for item in new.totals],
                                 [dataclasses.astuple(item) for item in old.totals])
                self.assertEqual(groups_of(new), groups_of(old))
                if kind == "encinas":
                    close(self, found.weighted_m3 or 0.0, 120.0, "volumen por peso: 48 · 2,5")

    def test_a_fill_in_a_zone_without_fill_counts_with_the_base(self) -> None:
        """RF-012-22, RF-012-30 (d): un relleno de 1 m sobre el acopio (16 m³) en la zona sin relleno cuenta entero y «no cumple», con o sin base."""
        zones = self.scenario("balsa")
        final = start() + 1.0
        old = compliance.check(GRID, zones(False), start(), final, E)
        new = compliance.check(GRID, zones(True), start(), final, E, base=base())
        found = new.zone("balsa")
        self.assertEqual((found.verdict, found.counts), (V.FAILS, C.FILL))
        close(self, found.counted_m3, 16.0)
        self.assertEqual([dataclasses.astuple(item) for item in new.totals], [dataclasses.astuple(item) for item in old.totals])


# --- (e) ------------------------------------------------------------------------------------------


class RejectionTest(unittest.TestCase):
    """(e) RF-012-31, RF-011-03: el rechazo de una base que no es de la rejilla y el aviso de lo que no se usa."""

    def source(self, name: str, **changes: Any) -> Any:
        header = surfaces.SurfaceHeader(name, GRID, fx.CRS, fx.VERTICAL)
        return surfaces.SurfaceSource(dataclasses.replace(header, **changes), path=Path(f"{name}.tif"))

    def test_a_base_in_another_grid_crs_or_datum_is_rejected_naming_it(self) -> None:
        """RF-012-31: una base en otra rejilla (celdas de 0,5 m), otro CRS u otro datum que las máscaras se rechaza como
        RF-011-03 (``res.surfaces_mismatch``), sin leer celdas y nombrando la base; la misma base en la rejilla, pasa."""
        masks = SimpleNamespace(grid=GRID)
        references = (fx.CRS, fx.VERTICAL)
        label = "Base de acopios: detección STK-001 «Acopios» (mineral)"
        fine = gis.Grid(500000.0, 4400010.0, 0.5, 0.5, 20, 20)
        other_crs = next(crs for crs in fx.CATALOG.horizontals() if crs.epsg != fx.CRS.epsg)
        other_vertical = next(v for v in fx.CATALOG.verticals() if v.epsg != fx.VERTICAL.epsg)
        sources = {cstore.START_ROLE: self.source("Levantamiento"), cstore.final_role(1): self.source("Retirada")}
        cstore.check_sources({**sources, cstore.base_role(1): self.source(label)}, masks, references)
        for field, change in (("rejilla", {"grid": fine}), ("CRS", {"crs": other_crs}),
                              ("datum", {"vertical": other_vertical})):
            with self.subTest(diferencia=field):
                with self.assertRaises(res_messages.ResError) as caught:
                    cstore.check_sources({**sources, cstore.base_role(1): self.source(label, **change)}, masks, references)
                self.assertEqual(caught.exception.code, "res.surfaces_mismatch")
                self.assertIn(label, caught.exception.text)

    def test_what_is_not_used_is_warned_with_the_detection_and_the_cause(self) -> None:
        """RF-012-31: una detección obsoleta o hecha sobre otra partida no se usa: la selección la lleva en ``skipped`` y su
        texto nombra la detección, su nombre y la causa (qué cambió, o la superficie en que se hizo y la partida), en los dos
        idiomas y sin marcadores sin llenar; sin base, todo el corte cuenta (la 0.4)."""
        stale = cstore.SkippedDetection("STK-001", "Acopios", "project", "stale", "gis_dtm_levantamiento",
                                        "Obsoleto: cambió el umbral de la huella (res.anthropic_presence_m)")
        other = cstore.SkippedDetection("STK-002", "Acopios de V01", "version", "other_surface",
                                        "des_stp_levantamiento_de_v01")
        selection = cstore.BaseSelection((), (stale, other))
        self.assertEqual(selection.bases, ())
        self.assertEqual(selection.refs, ())
        for language in ("es", "en"):
            for item in selection.skipped:
                text = item.text("Levantamiento", language)
                with self.subTest(idioma=language, deteccion=item.detection):
                    self.assertIn(item.detection, text)
                    self.assertIn(item.name, text)
                    self.assertNotIn("{", text)
        self.assertIn(stale.cause, stale.text("Levantamiento"))
        self.assertIn("des_stp_levantamiento_de_v01", other.text("Levantamiento"))
        self.assertIn("Levantamiento", other.text("Levantamiento"))
        found = compliance.check(GRID, zone_of("sin_corte", with_base=False), start(), terrain(), E).zone("sin_corte")
        self.assertEqual((found.counts, found.verdict, found.stockpile_cut_m3), (C.CUT, V.FAILS, 0.0))
        close(self, found.counted_m3, 48.0)


if __name__ == "__main__":
    unittest.main()
