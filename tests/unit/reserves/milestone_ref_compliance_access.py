# SPDX-License-Identifier: GPL-3.0-or-later
"""La verificación de la 012 con la accesibilidad real de las pistas, contra el cálculo a mano, con proyecto (spec 017, T18b; HU-017-3; RF-012-21, RF-012-22, RF-012-24;
RF-017-24 y RF-017-25; CE-017-07 y CE-017-09 en lo que ya existe; DIFF-012 de la 017, §4; plan 017 §5.4 A12, §5.7 P-9 y §7.1; constitución, principio 2; P-12: con proyecto en la
rejilla de 2 m, al paso «hito» de ``tools/check.py --completo``; el «verde» lleva el caso de ``tests/referencia/res/test_ref_compliance_access.py``).

El proyecto de las pistas de ``milestone_compliance_store_access`` (la cantera con bancos y rampas, rejilla de 2 m, V01 con las dos zonas «requiere acceso» **declaradas y
compiladas**, y las accesibilidades ``ACC-001`` sobre la cantera con bancos y ``ACC-002`` sobre la explotación de V01) verificado contra el terreno de la rampa con tres finales:
la cantera con bancos (con ``ACC-001``), la explotación (con ``ACC-002``) y el tajo (sin accesibilidad). **Cada cifra esperada sale de un bucle sobre las rejillas que están en
los ficheros del proyecto** —la partida, las finales, lo alcanzable de cada accesibilidad y las celdas de cada zona, de la caja a mano de ``tests.support.road_data``—, no del
código que se prueba. En el orden de sus letras:

- **(a)** las celdas de cada zona «requiere acceso» que compilaron las máscaras son las de su caja a mano (100 y 180 celdas de 4 m²: 400 y 720 m²).
- **(b)** (RF-012-22, RF-017-25) una zona está **comunicada** si alguna de sus celdas es alcanzable (a mano, sobre la rejilla de lo alcanzable de la accesibilidad de su final) y
  la verificación le da «cumple»; si no, «no cumple»; **la final sin accesibilidad la deja «sin comprobar»**; lo mismo dice lo que guarda la tabla.
- **(c)** (RF-012-21, RF-012-24) el corte, el relleno y el área con movimiento de cada zona son los del bucle a mano, con error relativo ≤ 10⁻⁹, también en las cifras CALCULADO
  que guarda la operación; el movimiento de la zona no cuenta (0 m³).
- **(d)** (RF-012-22) lo demás no cambia: los recintos que no son «requiere acceso» tienen, con la accesibilidad, los mismos totales y veredictos que sin ella, y lo que incumple
  una final es lo de siempre más la zona que no se comunica.
"""

from __future__ import annotations

import math
import unittest
from typing import Any, ClassVar

import numpy as np

from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.unit.reserves import milestone_compliance_store_access as store_milestone

geotiff_reader = import_geoblender("gis.geotiff.reader")
access_store = import_geoblender("design.access_store")
figures_mod = import_geoblender("core.provenance.figures")
combine = import_geoblender("gis.masks.combine")
compliance = import_geoblender("reserves.compliance")
cstore = import_geoblender("reserves.compliance_store")
gis_store = import_geoblender("gis.store")

V = compliance.Verdict
C = compliance.Counts
WITH, WITHOUT = store_milestone.WITH, store_milestone.WITHOUT
BOXES = {WITH: "Zona con acceso", WITHOUT: "Zona sin acceso"}
"""El código de cada zona y el nombre de su caja a mano de ``road_data``."""
E = 0.02
"""El espesor mínimo de verificación (D-6, ADOPTADO)."""
REL = 1e-9
CELL_M2 = 4.0
"""La celda de la rejilla de 2 m (m²)."""
ACCESSIBILITY = {1: store_milestone.BANK, 2: store_milestone.EXPLOITATION}
"""La superficie de cada final que tiene accesibilidad (la tercera, el tajo, no)."""


def hand(start: np.ndarray, final: np.ndarray, mask: np.ndarray) -> tuple[float, float, float]:
    """A mano, en las celdas de ``mask``: el corte (m³), el relleno (m³) y el área con movimiento (m²) de las diferencias que pasan del espesor mínimo (RF-012-21; celdas sin
    dato, fuera)."""
    cut, fill, moved = [], [], 0
    for s, f in zip(start[mask].tolist(), final[mask].tolist(), strict=True):
        if math.isnan(s) or math.isnan(f):
            continue
        difference = s - f
        if difference > E:
            cut.append(difference)
            moved += 1
        elif -difference > E:
            fill.append(-difference)
            moved += 1
    return math.fsum(cut) * CELL_M2, math.fsum(fill) * CELL_M2, moved * CELL_M2


class ReferenceTest(store_milestone._WithAccessibilities):
    """RF-012-21, RF-012-22, RF-012-24, RF-017-25: la verificación contra el cálculo a mano, con lo que la verificación lee del proyecto **leído de los ficheros**: la
    partida, las tres finales y lo alcanzable de las dos accesibilidades; la verificación se hace una vez (con accesibilidad y, para comparar, sin ella)."""

    stored: ClassVar[Any]
    plain: ClassVar[Any]
    start: ClassVar[np.ndarray]
    finals: ClassVar[dict[int, np.ndarray]]
    reached: ClassVar[dict[int, np.ndarray]]

    def grid_of(self, name: str, version: Any = None) -> np.ndarray:
        """La rejilla del dato ``name`` (del proyecto, o de la versión ``version``) tal como está en su fichero."""
        return np.asarray(geotiff_reader.read_geotiff(self.root / self.record(name, version).locator).values, dtype=np.float64)

    def reachable_of(self, surface: str) -> np.ndarray:
        """Lo alcanzable de la accesibilidad al día hecha sobre ``surface`` (de V01), tal como está en su fichero: las celdas alcanzables, a mano, son las de valor > 0."""
        (found,) = access_store.accessibilities_on(self.project, self.v1.uid, surface)
        return np.asarray(geotiff_reader.read_geotiff(self.root / found.reachable.locator).values, dtype=np.float64) > 0.0

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        probe = cls()
        cls.stored = probe.verify()
        cls.start = probe.grid_of(store_milestone.START.dataset)
        cls.finals = {1: probe.grid_of(store_milestone.BANK), 2: probe.grid_of(store_milestone.EXPLOITATION, cls.v1), 3: probe.grid_of(store_milestone.PIT)}
        cls.reached = {position: probe.reachable_of(surface) for position, surface in ACCESSIBILITY.items()}
        cls.plain = store_milestone._last(cstore.verify_steps(
            compliance.ComplianceRequest(store_milestone.NAME, store_milestone.START, store_milestone.FINALS, cls.masks_v1, E),
            cstore.project_sources(cls.project, store_milestone.START, store_milestone.FINALS, version_uid=cls.v1.uid),
            references=gis_store.project_references(cls.project)))

    def zone_mask(self, code: str) -> np.ndarray:
        """Las celdas de la zona ``code`` **que compilaron las máscaras de V01**."""
        return np.asarray(self.masks_v1.zones[code].mask(self.grid.shape))

    def test_a_the_cells_of_each_zone_are_the_ones_of_its_hand_box(self) -> None:
        """RF-017-25, RF-012-22: lo compilado por las máscaras de V01 (``Masks.zones``) coincide, celda a celda, con la caja a mano de ``road_data``: 20 × 5 = 100 celdas la zona
        con acceso (400 m²) y 30 × 6 = 180 la zona sin acceso (720 m²); y la rejilla de clases marca como «requiere acceso» exactamente esas 280."""
        for code, name in BOXES.items():
            with self.subTest(zona=code):
                np.testing.assert_array_equal(self.zone_mask(code), rd.bank_zone_mask(name, self.grid))
        self.assertEqual((int(np.count_nonzero(self.zone_mask(WITH))), int(np.count_nonzero(self.zone_mask(WITHOUT)))), (100, 180))
        marked = (self.masks_v1.classes & np.uint16(int(combine.ClassBit.ACCESS))) != 0
        np.testing.assert_array_equal(marked, self.zone_mask(WITH) | self.zone_mask(WITHOUT))

    def test_b_a_zone_is_communicated_when_a_reachable_cell_is_in_it(self) -> None:
        """RF-012-22, RF-017-25, CE-017-07: por la rejilla de lo alcanzable de la accesibilidad de cada final (la cantera con bancos y la explotación) y las celdas de cada zona, a
        mano: la zona con acceso tiene celdas alcanzables y la sin acceso, ninguna; la verificación da «cumple» y «no cumple»; el tajo, que no tiene accesibilidad, las deja
        «sin comprobar»; lo mismo dice lo que guardó la tabla."""
        stored = {(item.final, item.zone): item.verdict for item in self.read().zones if item.zone in BOXES}
        for position in (1, 2):
            reached = self.reached[position]
            self.assertTrue(reached.any(), "algo es alcanzable")
            by_hand = {code: bool((self.zone_mask(code) & reached).any()) for code in BOXES}
            self.assertEqual(by_hand, {WITH: True, WITHOUT: False}, f"la final {position}: la zona con acceso, sí; la otra, a 18 m de lo alcanzable, no")
            wanted = {code: V.COMPLIES if communicated else V.FAILS for code, communicated in by_hand.items()}
            check = self.stored.result.finals[position - 1]
            self.assertEqual({code: check.zone(code).verdict for code in BOXES}, wanted, f"la final {position}")
            self.assertEqual({code: stored[(position, code)] for code in BOXES}, {code: verdict.value for code, verdict in wanted.items()}, "y lo que guardó la tabla")
        pit = self.stored.result.finals[2]
        self.assertEqual({code: pit.zone(code).verdict for code in BOXES}, {WITH: V.UNCHECKED, WITHOUT: V.UNCHECKED})
        self.assertEqual({code: stored[(3, code)] for code in BOXES}, {WITH: "unchecked", WITHOUT: "unchecked"})

    def test_c_the_figures_of_each_zone_are_the_ones_of_the_hand_loop(self) -> None:
        """RF-012-21, RF-012-24: el corte, el relleno y el área con movimiento de cada zona «requiere acceso» en cada final, y las cifras CALCULADO que guarda la operación, son los
        del bucle a mano sobre las rejillas de los ficheros (≤ 10⁻⁹ relativo); el movimiento de la zona no cuenta (0 m³)."""
        figures = self.figures_of(self.op_named())
        moving = 0
        for position in (1, 2, 3):
            check = self.stored.result.finals[position - 1]
            for code in BOXES:
                with self.subTest(final=position, zona=code):
                    cut, fill, moved = hand(self.start, self.finals[position], self.zone_mask(code))
                    moving += int(cut + fill > 0.0)
                    zone = check.zone(code)
                    for found, expected, what in ((zone.cut_m3, cut, "corte"), (zone.fill_m3, fill, "relleno"), (zone.moved_m2, moved, "área con movimiento")):
                        self.assertTrue(math.isclose(found, expected, rel_tol=REL, abs_tol=1e-9), f"{what}: {found!r} frente a {expected!r}")
                    self.assertEqual(zone.counted_m3, 0.0)
                    self.assertIs(zone.counts, C.ACCESS)
                    scope = figures_mod.scope_json({"check": store_milestone.NAME, "final": position, "zone": code})
                    for key, expected in (("res.check_cut_m3", cut), ("res.check_fill_m3", fill), ("res.check_moved_area_m2", moved)):
                        self.assertTrue(math.isclose(figures[(key, scope)], expected, rel_tol=REL, abs_tol=1e-9), f"{key}: {figures[(key, scope)]!r} frente a {expected!r}")
        self.assertGreater(moving, 0, "alguna zona se mueve en alguna final: la comparación no es vacía")

    def test_d_the_rest_is_the_same_with_and_without_the_accessibility(self) -> None:
        """RF-012-22: los recintos que no son «requiere acceso» tienen, con la accesibilidad, los mismos totales y veredictos que la verificación sin ella; lo que incumple cada
        final es lo de siempre y, en las dos finales con accesibilidad, además la zona sin acceso (la que no se comunica); en el tajo, sin accesibilidad, es exactamente lo de
        siempre."""
        for position in (1, 2, 3):
            now, before = self.stored.result.finals[position - 1], self.plain.finals[position - 1]
            for item, old in zip(now.totals, before.totals, strict=True):
                if item.code in BOXES:
                    continue
                with self.subTest(final=position, zona=item.code):
                    self.assertEqual((item.code, item.counts, item.cut_m3, item.fill_m3, item.moved_m2, item.counted_m3, item.verdict),
                                     (old.code, old.counts, old.cut_m3, old.fill_m3, old.moved_m2, old.counted_m3, old.verdict))
            failing = sorted(item.code for item in now.totals if item.verdict is V.FAILS)
            usual = sorted(item.code for item in before.totals if item.verdict is V.FAILS)
            self.assertEqual(failing, sorted([*usual, WITHOUT]) if position in (1, 2) else usual, f"la final {position}")
            self.assertEqual([(g.zone, g.cells) for g in now.groups], [(g.zone, g.cells) for g in before.groups], "los grupos que incumplen son los de siempre")
        self.assertEqual(self.stored.result.fails, (True, True, True))


if __name__ == "__main__":
    unittest.main()
