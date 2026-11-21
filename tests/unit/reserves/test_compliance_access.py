# SPDX-License-Identifier: GPL-3.0-or-later
"""La verificación con la accesibilidad de las pistas (spec 012 0.6, DIFF-012 de la 017; RF-012-21, RF-012-22, RF-012-24;
spec 017 RF-017-24 y RF-017-25; plan 017 §5.4 A12, §5.7 P-9, T18).

Una zona «requiere acceso» (``Counts.ACCESS``) ya no es «sin comprobar (R-40)» a secas: dado el **conjunto de códigos de zona
comunicados** de la accesibilidad al día hecha sobre la superficie verificada, es «cumple» si está en él, «no cumple» si no y
«sin comprobar» si esa final no tiene accesibilidad al día (``communicated=None``). Sin accesibilidad, el resultado es el de
siempre, bit a bit.

- **RF-012-22, RF-012-21**: las tres respuestas, a mano, sobre una rejilla de 10 × 10 celdas de 1 m con dos zonas «requiere
  acceso» (``r_camino_a`` y ``r_camino_b``), una sin corte y una intocable; por bandas de cualquier tamaño y, de cada final, la suya
  (``ComplianceRequest.communicated``, una por final).
- **Sin accesibilidad, bit a bit** (``np.array_equal``): totales, grupos, rejilla de incumplimientos y avisos son los mismos con o sin
  conjunto de zonas comunicadas, salvo el veredicto de las zonas «requiere acceso»; una zona «requiere acceso» que no cumple no da
  grupos ni toca la rejilla (no tiene celdas que incumplan) y sí hace que la final no cumpla (RF-012-25).
- **RF-012-24**: la petición lleva el conjunto de cada final, opcional, y rechaza lo que no casa.
"""

from __future__ import annotations

import dataclasses
import unittest
from types import MappingProxyType
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
V = compliance.Verdict
C = compliance.Counts
E = 0.02
GRID = gis.Grid(500000.0, 4400010.0, 1.0, 1.0, 10, 10)
"""10 × 10 celdas de 1 m: la fila 0 es la del norte."""
CAMINO_A, CAMINO_B, FREE, TOWER, TREES = "r_camino_a", "r_camino_b", "r_sin_corte", "torre", "r_encinas"
CTYPES = {CAMINO_A: T.REQUIRES_ACCESS, CAMINO_B: T.REQUIRES_ACCESS, FREE: T.NO_CUT, TOWER: T.UNTOUCHABLE,
          TREES: T.AVOID}
WEIGHTS = {TREES: 2.0}


def runs_of(mask: np.ndarray) -> Any:
    rows, cols = np.nonzero(mask)
    return zones_mod.Runs(rows, cols, cols + 1)


def rows_mask(first: int, last: int) -> np.ndarray:
    """Las filas ``first`` a ``last`` (incluida) de la rejilla."""
    found = np.zeros(GRID.shape, dtype=bool)
    found[first:last + 1] = True
    return found


def classes() -> np.ndarray:
    return np.full(GRID.shape, np.uint16(Bit.PERIMETER) | np.uint16(Bit.LEGAL), dtype=np.uint16)


def zones() -> Any:
    """Cinco recintos más los dos de fuera: ``r_camino_a`` (filas 0 y 1), ``r_camino_b`` (filas 2 y 3), la torre (fila 4), la zona
    sin corte (filas 5 a 7) y las encinas (filas 8 y 9)."""
    masks = {CAMINO_A: rows_mask(0, 1), CAMINO_B: rows_mask(2, 3), TOWER: rows_mask(4, 4), FREE: rows_mask(5, 7),
             TREES: rows_mask(8, 9)}
    return compliance.check_zones(classes(), {code: runs_of(mask) for code, mask in masks.items()}, CTYPES, WEIGHTS)


def terrain() -> np.ndarray:
    return np.full(GRID.shape, 100.0)


def final_surface() -> np.ndarray:
    """Terreno a 100 m con movimiento en todos los recintos: 1 m de corte en 3 celdas de ``r_camino_a`` (fila 0), 1 m de relleno
    en 2 de ``r_camino_b`` (fila 2), 2 m de corte en una de la torre, 1 m de corte en 1 de la zona sin corte y 0,5 m de corte en
    4 de las encinas."""
    found = terrain()
    found[0, 0:3] = 99.0
    found[2, 0:2] = 101.0
    found[4, 5] = 98.0
    found[6, 6] = 99.0
    found[8, 0:4] = 99.5
    return found


def check(communicated: Any = None, *, band_rows: int = 256, final: np.ndarray | None = None, **options: Any) -> Any:
    options = {"communicated": communicated} if communicated is not None else options
    return compliance.check(GRID, zones(), terrain(), final_surface() if final is None else final, E, band_rows=band_rows, **options)


def verdicts(result: Any) -> dict[str, Any]:
    return {item.code: item.verdict for item in result.totals}


def comparable(result: Any) -> dict[str, Any]:
    """Todo lo de un resultado menos el veredicto de las zonas «requiere acceso»: los totales (con el veredicto de las demás), los
    grupos, la rejilla de incumplimientos y los avisos."""
    return {
        "totals": [dataclasses.astuple(dataclasses.replace(item, verdict=V.UNCHECKED) if item.counts is C.ACCESS else item)
                   for item in result.totals],
        "groups": [(g.zone, g.cells, g.area_m2, g.volume_m3, g.max_m, g.center, g.box, g.rows.tolist(), g.cols.tolist())
                   for g in result.groups],
        "same": result.same_surface, "notices": [(n.code, dict(n.values)) for n in result.notices]}


class ThreeAnswersTest(unittest.TestCase):
    """RF-012-22, RF-012-21 (DIFF-017): comunicada, no comunicada y sin accesibilidad al día."""

    def test_a_communicated_zone_complies_and_another_that_is_not_does_not(self) -> None:
        """RF-012-22: con ``r_camino_a`` en el conjunto de las comunicadas y ``r_camino_b`` fuera, la primera «cumple» y la segunda «no
        cumple»; también por bandas de 1, 3 y 256 filas."""
        for band_rows in (256, 1, 3):
            with self.subTest(band_rows=band_rows):
                found = verdicts(check(frozenset({CAMINO_A}), band_rows=band_rows))
                self.assertIs(found[CAMINO_A], V.COMPLIES)
                self.assertIs(found[CAMINO_B], V.FAILS)

    def test_both_communicated_both_complies_none_communicated_both_fail(self) -> None:
        """RF-012-22: las dos comunicadas, las dos «cumplen»; ninguna (conjunto vacío: hay accesibilidad al día y no comunica
        ninguna zona), las dos «no cumplen» (no es «sin comprobar»: sí hay accesibilidad)."""
        both = verdicts(check(frozenset({CAMINO_A, CAMINO_B})))
        self.assertEqual((both[CAMINO_A], both[CAMINO_B]), (V.COMPLIES, V.COMPLIES))
        none = verdicts(check(frozenset()))
        self.assertEqual((none[CAMINO_A], none[CAMINO_B]), (V.FAILS, V.FAILS))

    def test_without_an_up_to_date_accessibility_it_is_not_checked(self) -> None:
        """RF-012-22: sin accesibilidad al día de esa final (``communicated=None``, o sin darlo) las dos son «sin comprobar»."""
        for result in (check(), check(communicated=None), compliance.check(GRID, zones(), terrain(), final_surface(), E, communicated=None)):
            found = verdicts(result)
            self.assertEqual((found[CAMINO_A], found[CAMINO_B]), (V.UNCHECKED, V.UNCHECKED))

    def test_the_code_decides_not_the_position_and_other_codes_do_not_count(self) -> None:
        """RF-012-22: lo que cuenta es el código de la zona; una zona comunicada que no es de esta verificación no cambia nada."""
        found = verdicts(check(frozenset({CAMINO_B, "zona_de_otra_cosa", FREE})))
        self.assertEqual((found[CAMINO_A], found[CAMINO_B]), (V.FAILS, V.COMPLIES))

    def test_the_other_zones_are_judged_as_always(self) -> None:
        """RF-012-22: las demás zonas no dependen de la accesibilidad: la torre (2 m de corte) y la zona sin corte «no cumplen», las
        encinas, sin juicio y los dos de fuera, «cumplen», con la accesibilidad o sin ella."""
        for communicated in (None, frozenset(), frozenset({CAMINO_A, CAMINO_B})):
            with self.subTest(communicated=communicated):
                found = verdicts(check() if communicated is None else check(communicated))
                self.assertEqual((found[TOWER], found[FREE], found[TREES]), (V.FAILS, V.FAILS, V.NOT_JUDGED))
                self.assertEqual((found["outside_perimeter"], found["outside_legal"]), (V.COMPLIES, V.COMPLIES))

    def test_the_verdict_function_with_a_zone_that_requires_access(self) -> None:
        """RF-012-22: ``verdict`` de un recinto «requiere acceso» con el conjunto de comunicadas (el algoritmo de A12: sin importar
        ``design``): comunicada, no comunicada y sin conjunto; el de los demás recintos, el de siempre aunque se dé."""
        zone = next(item for item in zones() if item.code == CAMINO_A)
        self.assertIs(compliance.verdict(zone, 0), V.UNCHECKED)
        self.assertIs(compliance.verdict(zone, 0, communicated=None), V.UNCHECKED)
        self.assertIs(compliance.verdict(zone, 0, communicated=frozenset({CAMINO_A})), V.COMPLIES)
        self.assertIs(compliance.verdict(zone, 0, communicated=frozenset({CAMINO_B})), V.FAILS)
        self.assertIs(compliance.verdict(zone, 5, communicated=frozenset({CAMINO_A})), V.COMPLIES)  # el movimiento no cuenta
        tower = next(item for item in zones() if item.code == TOWER)
        self.assertIs(compliance.verdict(tower, 1, communicated=frozenset({TOWER})), V.FAILS)
        self.assertIs(compliance.verdict(tower, 0, communicated=frozenset()), V.COMPLIES)

    def test_a_zone_that_does_not_comply_fails_the_final_without_cells(self) -> None:
        """RF-012-22, RF-012-25: una zona «requiere acceso» sin comunicar hace que la final no cumpla (``fails``), aunque solo ella
        incumpla; no tiene celdas que incumplan: no da ningún grupo ni marca la rejilla de incumplimientos."""
        flat = terrain()
        quiet = compliance.check(GRID, zones(), terrain(), flat, E, communicated=frozenset({CAMINO_A}))
        self.assertTrue(quiet.fails)  # r_camino_b no se comunica
        self.assertEqual((quiet.groups, quiet.violations), ((), None))
        ok = compliance.check(GRID, zones(), terrain(), flat, E, communicated=frozenset({CAMINO_A, CAMINO_B}))
        self.assertFalse(ok.fails)
        unchecked = compliance.check(GRID, zones(), terrain(), flat, E)
        self.assertFalse(unchecked.fails)  # sin accesibilidad no hay juicio: como hoy

    def test_the_totals_of_a_zone_that_requires_access_are_the_ones_of_the_movement(self) -> None:
        """RF-012-21: de una zona «requiere acceso» se dan los mismos totales de siempre (el corte, el relleno y el área con movimiento,
        a mano) y, además, su veredicto con la accesibilidad: ``r_camino_a`` tiene 3 m³ de corte y 3 m² y ``r_camino_b`` 2 m³ de relleno."""
        result = check(frozenset({CAMINO_A}))
        first, second = result.zone(CAMINO_A), result.zone(CAMINO_B)
        self.assertEqual((first.cut_m3, first.fill_m3, first.moved_m2, first.counted_m3, first.counts), (3.0, 0.0, 3.0, 0.0, C.ACCESS))
        self.assertEqual((second.cut_m3, second.fill_m3, second.moved_m2, second.counted_m3), (0.0, 2.0, 2.0, 0.0))


class WithoutAnAccessibilityTest(unittest.TestCase):
    """RF-012-22, RF-012-24 (DIFF-017): sin accesibilidad, bit a bit lo de siempre."""

    def test_everything_but_the_verdict_of_the_access_zones_is_the_same(self) -> None:
        """Totales, grupos, rejilla de incumplimientos y avisos, con o sin accesibilidad, y por cualquier banda: los mismos
        (``np.array_equal`` sobre la rejilla) salvo el veredicto de las zonas «requiere acceso»."""
        reference = check()
        for communicated in (None, frozenset(), frozenset({CAMINO_A}), frozenset({CAMINO_A, CAMINO_B})):
            for band_rows in (256, 1, 3):
                with self.subTest(communicated=communicated, band_rows=band_rows):
                    result = check(communicated, band_rows=band_rows)
                    self.assertEqual(comparable(result), comparable(reference))
                    self.assertTrue(np.array_equal(result.violations, reference.violations, equal_nan=True))

    def test_the_old_result_by_hand(self) -> None:
        """Lo de siempre, a mano: la torre 2 m³ de corte (1 grupo), la zona sin corte 1 m³ y las encinas 2 m³ (4 celdas de 0,5 m)
        ponderados a 4 m³; los grupos, uno por recinto que incumple (la torre y la zona sin corte); la rejilla marca solo esas dos
        celdas (``final − partida``)."""
        result = check()
        tower, free, trees = result.zone(TOWER), result.zone(FREE), result.zone(TREES)
        self.assertEqual((tower.cut_m3, tower.counted_m3, free.cut_m3, free.counted_m3), (2.0, 2.0, 1.0, 1.0))
        self.assertEqual((trees.cut_m3, trees.weight, trees.weighted_m3), (2.0, 2.0, 4.0))
        self.assertEqual(sorted(group.zone for group in result.groups), [FREE, TOWER])
        self.assertEqual(result.violations[4, 5], -2.0)
        self.assertEqual(result.violations[6, 6], -1.0)
        self.assertEqual(int(np.isfinite(result.violations).sum()), 2)
        self.assertEqual(verdicts(result)[CAMINO_A], V.UNCHECKED)

    def test_the_conditions_of_the_set_are_checked(self) -> None:
        """RF-012-24: el conjunto de zonas comunicadas es ``None`` o un conjunto de códigos de texto (una lista o un conjunto se
        admiten y se guardan como ``frozenset``); otra cosa es un error del programa."""
        steps = compliance.Checker(GRID, zones(), E, communicated={CAMINO_A})
        self.assertEqual(steps.communicated, frozenset({CAMINO_A}))
        self.assertIsNone(compliance.Checker(GRID, zones(), E).communicated)
        for bad in ("r_camino_a", [CAMINO_A, 3], {1}, 5, b"x"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                compliance.Checker(GRID, zones(), E, communicated=bad)


class RequestTest(unittest.TestCase):
    """RF-012-24: la petición lleva, de cada final, las zonas comunicadas de su accesibilidad (opcional)."""

    def request(self, *, finals: int = 1, **extra: Any) -> Any:
        masks = access.MaskSet(GRID, "v" * 32, "o" * 32, access.MaskState.CURRENT, (), classes(), (), MappingProxyType({}),
                               MappingProxyType({}), (), MappingProxyType({}))
        start = surfaces.SurfaceRef(dataset="gis_dtm_inicial")
        return compliance.ComplianceRequest("V1", start, tuple(surfaces.SurfaceRef(dataset=f"gis_dtm_final_{k}") for k in range(1, finals + 1)),
                                            masks, 0.02, **extra)

    def test_without_an_accessibility_nothing_changes(self) -> None:
        """RF-012-24: sin dar nada, ninguna final tiene accesibilidad (``communicated_of`` da ``None``) y la petición es la de siempre."""
        request = self.request(finals=2)
        self.assertEqual(request.communicated, ())
        self.assertEqual([request.communicated_of(k) for k in (0, 1)], [None, None])

    def test_one_set_per_final_or_none(self) -> None:
        """RF-012-24: de cada final, su conjunto o ``None`` (sin accesibilidad al día para esa final), con cualquier iterable de códigos."""
        request = self.request(finals=3, communicated=({CAMINO_A}, None, [CAMINO_B, CAMINO_A]))
        self.assertEqual(request.communicated, (frozenset({CAMINO_A}), None, frozenset({CAMINO_A, CAMINO_B})))
        self.assertEqual([request.communicated_of(k) for k in range(3)], list(request.communicated))
        with self.assertRaises(IndexError):
            request.communicated_of(3)

    def test_what_does_not_agree_is_refused(self) -> None:
        """RF-012-24: un conjunto por final (el mismo número que las finales) y de códigos de texto; de otro modo, un error del programa."""
        for bad in ((frozenset(),), (frozenset(), frozenset(), frozenset()), ("r_camino_a", None), ({1}, None), (None, 5)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.request(finals=2, communicated=bad)

    def test_the_sets_are_frozen(self) -> None:
        """RF-012-24: la petición guarda copias que no cambian si cambia quien las dio."""
        mine = {CAMINO_A}
        request = self.request(communicated=(mine,))
        mine.add(CAMINO_B)
        self.assertEqual(request.communicated, (frozenset({CAMINO_A}),))


if __name__ == "__main__":
    unittest.main()
