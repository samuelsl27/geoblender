# SPDX-License-Identifier: GPL-3.0-or-later
"""Verificación por recinto de referencia con la accesibilidad de las pistas (spec 017, T18b; HU-017-3; RF-012-21, RF-012-22, RF-012-24; RF-017-25; DIFF-012 de la 017,
§2 y §4; CE-012-06 con las tres respuestas; plan 017 §5.4 A12 y §7.1; constitución, principio 2).

El sitio de ``test_ref_compliance`` (la concesión, el perímetro, la torre, la balsa, las encinas y el **camino que «requiere acceso»**, rejilla de 160 × 160 celdas de 2 m,
espesor mínimo 0,02 m) con lo que la 017 añade a la 012: a una zona «requiere acceso» se le da «cumple» si la accesibilidad al día hecha sobre la final la comunica, «no cumple» si
no y «sin comprobar» si la final no tiene accesibilidad al día. Cada cifra esperada sale de un bucle de Python sobre las celdas del camino (``hand``: ningún valor se calcula
llamando al código bajo prueba); el error relativo es ≤ 10⁻⁹ (RF-012-21).

- **CE-012-06 con las tres respuestas** (:class:`ThreeAnswersTest`): el camino con 2 m de relleno en sus 36 celdas (288 m³ en 144 m²) da lo mismo en las tres respuestas —el
  movimiento de una zona «requiere acceso» **no cuenta**: ni el corte ni el relleno cambian, ni sus grupos— y solo cambia su veredicto: «sin comprobar» sin accesibilidad,
  «cumple» si la comunica y «no cumple» si no; la final solo incumple en el segundo caso, y por el camino.
- **Lo demás no cambia, bit a bit** (:class:`OthersAreTheSameTest`): con la final de la balsa de CE-012-06 (la balsa no cumple; las encinas, sin juicio), los totales de todos los
  recintos menos el veredicto del camino son los mismos en las tres respuestas, y los grupos que incumplen, los mismos; con la accesibilidad que no comunica el camino, la final
  incumple en la balsa **y** en el camino (en ese orden).
- **Una zona que no cumple no da grupos** (:class:`NoCellsTest`): un camino «no comunicado» sin movimiento da el veredicto igual y ningún grupo ni rejilla de incumplimientos
  (no hay celdas que incumplan; es la zona la que no cumple).

El caso con proyecto (la cantera de las pistas, sus dos accesibilidades reales y las tres finales) está en ``tests/unit/reserves/milestone_ref_compliance_access.py`` (P-12).
"""

import math
import unittest

import numpy as np

from tests.referencia.res import test_ref_compliance as site012
from tests.support import constraints_fixtures as fx
from tests.support.package import import_geoblender

compliance = import_geoblender("reserves.compliance")

V = compliance.Verdict
C = compliance.Counts
E = site012.E
ROAD = "r_camino"
CELL_M2 = fx.SITE_GRID.cell_area
FILL_M = 2.0
"""Lo que se rellena el camino (m)."""
REL = 1e-9


def hand(start: np.ndarray, final: np.ndarray, mask: np.ndarray) -> tuple[float, float, float]:
    """A mano, en las celdas de ``mask``: el corte (m³), el relleno (m³) y el área con movimiento (m²) de las diferencias que pasan del espesor mínimo (RF-012-21)."""
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


def road_mask() -> np.ndarray:
    """Las celdas del camino, a mano: las de centro estrictamente dentro de su caja (6 × 6 celdas)."""
    x, y = fx.site_centers()
    left, bottom, right, top = site012.ACCESS_BOX
    return (x > left) & (x < right) & (y > bottom) & (y < top)


class _Site(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.zones, cls.masks = site012.site_zones()
        cls.start = fx.site_start()
        cls.road = road_mask()

    def verify(self, values: np.ndarray, communicated: frozenset[str] | None) -> object:
        return compliance.check(fx.SITE_GRID, self.zones, self.start.values, values, E, communicated=communicated)

    def filled_road(self) -> np.ndarray:
        """La final que no toca nada más que el camino, relleno ``FILL_M`` m en sus celdas."""
        values = self.start.values.copy()
        values[self.road] += FILL_M
        return values

    def close(self, found: float, expected: float, what: str) -> None:
        self.assertTrue(math.isclose(found, expected, rel_tol=REL, abs_tol=1e-9), f"{what}: {found!r} frente a {expected!r}")


class ThreeAnswersTest(_Site):
    """CE-012-06 con las tres respuestas (RF-012-21, RF-012-22)."""

    ANSWERS = ((None, V.UNCHECKED), (frozenset({ROAD}), V.COMPLIES), (frozenset(), V.FAILS), (frozenset({"otra_zona"}), V.FAILS))

    def test_the_road_by_hand(self) -> None:
        """El camino son 6 × 6 celdas de 2 m: 144 m², y su relleno de 2 m, 288 m³ (el enunciado de CE-012-06), calculados aquí a mano antes de verificar nada."""
        self.assertEqual(int(np.count_nonzero(self.road)), 36)
        cut, fill, moved = hand(self.start.values, self.filled_road(), self.road)
        self.assertEqual((cut, moved), (0.0, 144.0))
        self.close(fill, 288.0, "el relleno del camino")
        self.assertEqual(int(np.count_nonzero(self.masks.classes & site012.combine.ClassBit.ACCESS)), 36, "las celdas del camino en la rejilla de clases")

    def test_the_verdict_changes_and_the_figures_do_not(self) -> None:
        """RF-012-22, RF-012-21: en cada respuesta el camino da su veredicto (sin accesibilidad, «sin comprobar»; comunicado, «cumple»; no comunicado, «no cumple») y siempre el
        mismo corte, relleno y área con movimiento, **a mano**; lo que se mueve en él no cuenta (0 m³) ni da grupos."""
        values = self.filled_road()
        cut, fill, moved = hand(self.start.values, values, self.road)
        for communicated, verdict in self.ANSWERS:
            with self.subTest(communicated=communicated):
                result = self.verify(values, communicated)
                zone = result.zone(ROAD)
                self.assertIs(zone.counts, C.ACCESS)
                self.assertIs(zone.verdict, verdict)
                self.close(zone.cut_m3, cut, "el corte")
                self.close(zone.fill_m3, fill, "el relleno")
                self.close(zone.moved_m2, moved, "el área con movimiento")
                self.assertEqual(zone.counted_m3, 0.0, "el movimiento de una zona «requiere acceso» no cuenta")
                self.assertEqual(result.groups_of(ROAD), ())
                self.assertEqual(result.groups, ())

    def test_the_final_fails_only_when_the_road_is_not_communicated(self) -> None:
        """RF-012-22: la final que solo mueve el camino cumple sin accesibilidad (sin comprobar) y con la accesibilidad que lo comunica, y no cumple, **solo por el camino**, si
        la accesibilidad no lo comunica."""
        values = self.filled_road()
        for communicated, expected in ((None, False), (frozenset({ROAD}), False), (frozenset(), True)):
            with self.subTest(communicated=communicated):
                result = self.verify(values, communicated)
                self.assertEqual(result.fails, expected)
                self.assertEqual([item.code for item in result.totals if item.verdict is V.FAILS], [ROAD] if expected else [])


class OthersAreTheSameTest(_Site):
    """RF-012-21, RF-012-22: lo que no es el camino no cambia con la respuesta."""

    def pond_final(self) -> np.ndarray:
        """La final de CE-012-06: la balsa con 4.300 m³ de relleno, las encinas rebajadas 1 m y el camino relleno 2 m."""
        case = fx.pond_case()
        values = case.final.values.copy()
        x, y = fx.site_centers()
        for box, change in ((site012.AVOID_BOX, -1.0), (site012.ACCESS_BOX, FILL_M)):
            inside = (x > box[0]) & (x < box[2]) & (y > box[1]) & (y < box[3])
            values[inside] = fx.START_Z + change
        return values

    def totals(self, result: object) -> list[tuple[object, ...]]:
        return [(item.code, item.counts, item.cut_m3, item.fill_m3, item.moved_m2, item.nodata_m2, item.counted_m3, item.weighted_m3, item.stockpile_cut_m3)
                for item in result.totals]

    def test_every_total_but_the_verdict_of_the_road_is_the_same_bit_for_bit(self) -> None:
        """RF-012-21, RF-012-22: los totales de todos los recintos (cortes, rellenos, áreas, lo que cuenta, el peso) y los grupos que incumplen son **idénticos** en las tres
        respuestas; los veredictos también, salvo el del camino; la rejilla de incumplimientos, la misma."""
        values = self.pond_final()
        plain = self.verify(values, None)
        for communicated in (frozenset({ROAD}), frozenset()):
            with self.subTest(communicated=communicated):
                result = self.verify(values, communicated)
                self.assertEqual(self.totals(result), self.totals(plain))
                self.assertEqual([(g.zone, g.cells, g.area_m2, g.volume_m3, g.max_m, g.center) for g in result.groups],
                                 [(g.zone, g.cells, g.area_m2, g.volume_m3, g.max_m, g.center) for g in plain.groups])
                self.assertEqual({item.code: item.verdict for item in result.totals if item.code != ROAD},
                                 {item.code: item.verdict for item in plain.totals if item.code != ROAD})
                self.assertTrue(np.array_equal(result.violations, plain.violations, equal_nan=True))

    def test_the_pond_fails_with_or_without_the_road(self) -> None:
        """CE-012-06: la balsa con 4.300 m³ no cumple (y su grupo); las encinas, sin juicio; el camino, en el orden de los recintos, es lo único que añade la accesibilidad:
        sin ella o comunicado, la final incumple solo en la balsa; no comunicado, en la balsa y en el camino."""
        values = self.pond_final()
        for communicated, failing in ((None, ["r_balsa"]), (frozenset({ROAD}), ["r_balsa"]), (frozenset(), ["r_balsa", ROAD])):
            with self.subTest(communicated=communicated):
                result = self.verify(values, communicated)
                self.assertEqual([item.code for item in result.totals if item.verdict is V.FAILS], failing)
                self.assertIs(result.zone("r_encinas").verdict, V.NOT_JUDGED)
                self.assertTrue(result.fails)
                self.close(result.zone("r_balsa").fill_m3, 4_300.0, "el relleno de la balsa")
                self.assertEqual([group.zone for group in result.groups], ["r_balsa"], "el camino no da grupos")


class NoCellsTest(_Site):
    """RF-012-22: una zona que no cumple porque no está comunicada no tiene celdas que incumplan."""

    def test_a_road_that_is_not_communicated_does_not_comply_without_moving_anything(self) -> None:
        """RF-012-22: aunque la final no toque el camino (0 m³, 0 m²), si la accesibilidad no lo comunica el camino «no cumple» y la final incumple; sin grupos ni rejilla de
        incumplimientos (no hay celdas: es la zona la que no cumple)."""
        values = self.start.values.copy()
        values[80, 80] += 0.5 * E  # por debajo del espesor mínimo: no mueve nada, pero la final no es la misma superficie
        result = self.verify(values, frozenset())
        road = result.zone(ROAD)
        self.assertEqual((road.verdict, road.cut_m3, road.fill_m3, road.moved_m2), (V.FAILS, 0.0, 0.0, 0.0))
        self.assertTrue(result.fails)
        self.assertEqual(result.groups, ())
        self.assertIsNone(result.violations)
        self.assertIs(self.verify(values, frozenset({ROAD})).zone(ROAD).verdict, V.COMPLIES)
        self.assertIs(self.verify(values, None).zone(ROAD).verdict, V.UNCHECKED)


if __name__ == "__main__":
    unittest.main()
