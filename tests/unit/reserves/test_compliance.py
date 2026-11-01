# SPDX-License-Identifier: GPL-3.0-or-later
"""El núcleo de la verificación por recinto (spec 012, T16; RF-012-21, RF-012-22, RF-012-23;
plan 012 A7–A10, D-6, D-41).

- **RF-012-21 (A7, D-6)**: a mano, en una rejilla de 3 × 4 celdas de 2,5 × 2 m (5 m²) con un
  espesor mínimo de 0,25 m: por recinto, el corte, el relleno y el área con movimiento de las
  celdas que pasan el umbral (0,25 m no cuenta; 0,375 m cuenta entero), el área sin dato aparte,
  «fuera del perímetro» y «fuera del límite legal» por los bits de la rejilla de clases; por
  bandas de una fila, lo mismo; una cota constante como partida; la misma superficie dos veces
  da ceros y el aviso ``res.same_surface``.
- **RF-012-22 (A8, A9)**: «no cumple» con el corte en «sin corte», en la banda hacia dentro y
  fuera del límite legal, con el relleno en «sin relleno» y con cualquier movimiento fuera del
  perímetro; el límite por dentro cumple aunque se mueva; «preferible no afectar», m², m³ y
  m³ × peso sin juicio; «requiere acceso», sin comprobar.
- **RF-012-23 (A10, D-41)**: los grupos por contigüidad de lado (dos celdas en diagonal son dos
  grupos) con su área, volumen, espesor máximo, centro y caja absolutos; ``label_groups`` da la
  misma partición que una inundación celda a celda en 200 máscaras aleatorias.
- La petición: de 1 a 10 finales distintas y un espesor mínimo entre 0 y 10 m.
"""

import math
import unittest
from collections import deque

import numpy as np

from tests.support import constraints_fixtures as fx
from tests.support import several_limits as sl
from tests.support.package import import_geoblender

gis = import_geoblender("gis")
model = import_geoblender("core.constraints.model")
combine = import_geoblender("gis.masks.combine")
compile_mod = import_geoblender("gis.masks.compile")
compliance_store = import_geoblender("reserves.compliance_store")
zones_mod = import_geoblender("gis.masks.zones")
access = import_geoblender("gis.masks.access")
surfaces = import_geoblender("reserves.surfaces")
compliance = import_geoblender("reserves.compliance")

T = model.ConstraintType
Bit = combine.ClassBit
Runs = zones_mod.Runs
V = compliance.Verdict
C = compliance.Counts

GRID = gis.Grid(fx.BASE[0], fx.BASE[1] + 6.0, 2.5, 2.0, 4, 3)
"""3 filas × 4 columnas de 2,5 × 2 m = 5 m² (la celda no es cuadrada)."""
A = 5.0
E = 0.25
NAN = math.nan

START = np.zeros((3, 4))
START[2, 3] = NAN
DIFFERENCE = np.array([[0.25, 0.5, -1.5, 0.0],  # d = partida − final
                       [2.0, -0.125, 0.375, -3.0],
                       [0.0, NAN, 1.0, 0.0]])
FINAL = START - DIFFERENCE


def runs(*cells):
    """Tramos de las celdas ``(fila, columna)``."""
    rows = np.array([cell[0] for cell in cells])
    cols = np.array([cell[1] for cell in cells])
    return Runs(rows, cols, cols + 1)


def classes():
    """Perímetro en las columnas 0–2; límite legal (enteras dentro) en las filas 0–1."""
    found = np.zeros((3, 4), dtype=np.uint16)
    found[:, :3] |= np.uint16(Bit.PERIMETER)
    found[:2, :] |= np.uint16(Bit.LEGAL)
    return found


ZONES = {
    "r_concesion": runs((0, 0), (0, 1), (0, 2), (0, 3), (1, 0), (1, 1), (1, 2), (1, 3)),
    "r_concesion:inner": runs((0, 1)),
    "r_sin_corte": runs((0, 0), (0, 1), (0, 2), (1, 0)),
    "r_balsa": runs((1, 1), (1, 2), (1, 3), (2, 1), (2, 2), (2, 3)),
    "r_encinas": runs((0, 0), (0, 1), (0, 2), (0, 3)),
    "r_camino": runs((2, 0)),
}
CTYPES = {"r_concesion": T.LEGAL_LIMIT, "r_sin_corte": T.NO_CUT, "r_balsa": T.NO_FILL,
          "r_encinas": T.AVOID, "r_camino": T.REQUIRES_ACCESS}


def hand_zones():
    return compliance.check_zones(classes(), ZONES, CTYPES, {"r_encinas": 3.0})


# Lo esperado a mano: (corte, relleno, área con movimiento, sin dato, lo que cuenta, veredicto).
EXPECTED = {
    "outside_perimeter": (0.0, 3.0 * A, 1 * A, 1 * A, 3.0 * A, V.FAILS),
    "outside_legal": (1.0 * A, 0.0, 1 * A, 2 * A, 1.0 * A, V.FAILS),
    "r_concesion": (2.875 * A, 4.5 * A, 5 * A, 0.0, 0.0, V.COMPLIES),
    "r_concesion:inner": (0.5 * A, 0.0, 1 * A, 0.0, 0.5 * A, V.FAILS),
    "r_sin_corte": (2.5 * A, 1.5 * A, 3 * A, 0.0, 2.5 * A, V.FAILS),
    "r_balsa": (1.375 * A, 3.0 * A, 3 * A, 2 * A, 3.0 * A, V.FAILS),
    "r_encinas": (0.5 * A, 1.5 * A, 2 * A, 0.0, 2.0 * A, V.NOT_JUDGED),
    "r_camino": (0.0, 0.0, 0.0, 0.0, 0.0, V.UNCHECKED),
}


def center(row, col):
    return (GRID.west + (col + 0.5) * GRID.dx, GRID.north - (row + 0.5) * GRID.dy)


class HandTest(unittest.TestCase):
    """RF-012-21, RF-012-22, RF-012-23: el caso a mano."""

    def assert_totals(self, result):
        self.assertEqual([t.code for t in result.totals], list(EXPECTED))
        for item in result.totals:
            cut, fill, moved, nodata, counted, verdict = EXPECTED[item.code]
            with self.subTest(zone=item.code):
                self.assertAlmostEqual(item.cut_m3, cut, delta=1e-9 * max(cut, 1.0))
                self.assertAlmostEqual(item.fill_m3, fill, delta=1e-9 * max(fill, 1.0))
                self.assertEqual(item.moved_m2, moved)
                self.assertEqual(item.nodata_m2, nodata)
                self.assertAlmostEqual(item.counted_m3, counted, delta=1e-9 * max(counted, 1))
                self.assertIs(item.verdict, verdict)

    def test_totals_by_zone(self) -> None:
        """RF-012-21, RF-012-22: totales, umbral y veredicto por recinto, entero y por filas."""
        for band_rows in (256, 1, 2):
            with self.subTest(band_rows=band_rows):
                result = compliance.check(GRID, hand_zones(), START, FINAL, E,
                                          band_rows=band_rows)
                self.assert_totals(result)
                self.assertTrue(result.fails)
                self.assertFalse(result.same_surface)
                self.assertEqual(result.notices, ())
        avoid = result.zone("r_encinas")
        self.assertEqual(avoid.weight, 3.0)
        self.assertAlmostEqual(avoid.weighted_m3, 2.0 * A * 3.0, delta=1e-12)
        self.assertIsNone(result.zone("r_balsa").weighted_m3)
        self.assertIs(result.zone("outside_legal").counts, C.CUT)
        self.assertIs(result.zone("outside_perimeter").counts, C.ANY)

    def test_constant_start(self) -> None:
        """RF-012-21: una cota constante como partida (0 m) da lo mismo sin la celda sin dato
        de la partida."""
        final = FINAL.copy()
        final[2, 3] = NAN
        result = compliance.check(GRID, hand_zones(), 0.0, final, E)
        self.assert_totals(result)

    def test_groups(self) -> None:
        """RF-012-23 (D-41): los grupos de cada recinto que no cumple, por contigüidad de
        lado."""
        result = compliance.check(GRID, hand_zones(), START, FINAL, E)
        found = [(g.zone, g.cells, g.area_m2, g.volume_m3, g.max_m, g.center, g.box)
                 for g in result.groups]
        x0, y1 = GRID.west, GRID.north

        def box(row, col):
            return (x0 + col * 2.5, y1 - (row + 1) * 2.0, x0 + (col + 1) * 2.5, y1 - row * 2.0)

        self.assertEqual(found, [
            ("outside_perimeter", 1, A, 3.0 * A, 3.0, center(1, 3), box(1, 3)),
            ("outside_legal", 1, A, 1.0 * A, 1.0, center(2, 2), box(2, 2)),
            ("r_concesion:inner", 1, A, 0.5 * A, 0.5, center(0, 1), box(0, 1)),
            # (0, 1) y (1, 0) solo se tocan en una esquina: dos grupos.
            ("r_sin_corte", 1, A, 0.5 * A, 0.5, center(0, 1), box(0, 1)),
            ("r_sin_corte", 1, A, 2.0 * A, 2.0, center(1, 0), box(1, 0)),
            ("r_balsa", 1, A, 3.0 * A, 3.0, center(1, 3), box(1, 3)),
        ])
        self.assertEqual(len(result.groups_of("r_sin_corte")), 2)
        group = result.groups_of("r_balsa")[0]
        self.assertEqual((group.rows.tolist(), group.cols.tolist()), ([1], [3]))

    def test_threshold_zero_and_whole_group(self) -> None:
        """RF-012-21, RF-012-23: con 0 m de umbral cuenta todo movimiento; un grupo de tres
        celdas en L tiene su área, su volumen, su máximo y el centro medio de sus celdas."""
        start = np.zeros((3, 4))
        final = np.zeros((3, 4))
        final[0, 0], final[1, 0], final[1, 1] = -1.0, -2.0, -0.5
        zone = compliance.check_zones(np.full((3, 4), Bit.PERIMETER | Bit.LEGAL, np.uint16),
                                      {"r_torre": runs(*[(r, c) for r in range(3)
                                                         for c in range(4)])},
                                      {"r_torre": T.UNTOUCHABLE})
        result = compliance.check(GRID, zone, start, final, 0.0)
        (group,) = result.groups
        self.assertEqual((group.zone, group.cells, group.area_m2, group.volume_m3, group.max_m),
                         ("r_torre", 3, 3 * A, 3.5 * A, 2.0))
        expected = np.mean([center(0, 0), center(1, 0), center(1, 1)], axis=0)
        self.assertAlmostEqual(group.center[0], expected[0], delta=1e-9)
        self.assertAlmostEqual(group.center[1], expected[1], delta=1e-9)
        self.assertEqual(result.zone("outside_perimeter").cut_m3, 0.0)

    def test_same_surface(self) -> None:
        """RF-012-21: la misma superficie como partida y final da ceros y el aviso."""
        result = compliance.check(GRID, hand_zones(), FINAL, FINAL.copy(), E,
                                  start_name="Diseño")
        self.assertTrue(result.same_surface)
        self.assertEqual([n.code for n in result.notices], ["res.same_surface"])
        self.assertIn("Diseño", result.notices[0].text())
        self.assertEqual(result.groups, ())
        for item in result.totals:
            with self.subTest(zone=item.code):
                self.assertEqual((item.cut_m3, item.fill_m3, item.moved_m2, item.counted_m3),
                                 (0.0, 0.0, 0.0, 0.0))
                self.assertIn(item.verdict, (V.COMPLIES, V.NOT_JUDGED, V.UNCHECKED))
        self.assertFalse(result.fails)

    def test_counts_of_each_type(self) -> None:
        """RF-012-22 (A8): lo que cuenta en cada tipo."""
        expected = {T.LEGAL_LIMIT: C.NOTHING, T.ACTION_PERIMETER: C.NOTHING,
                    T.UNTOUCHABLE: C.ANY, T.EXCLUSION: C.ANY, T.NO_CUT: C.CUT,
                    T.FILL_ONLY: C.CUT, T.RESTORATION_ONLY: C.CUT, T.SETBACK: C.CUT,
                    T.NO_FILL: C.FILL, T.AVOID: C.AVOID, T.REQUIRES_ACCESS: C.ACCESS}
        for ctype, counts in expected.items():
            with self.subTest(ctype=ctype):
                self.assertIs(compliance.counts_of("r_x", ctype), counts)
        self.assertIs(compliance.counts_of("r_x:inner", T.LEGAL_LIMIT), C.CUT)
        self.assertIs(compliance.counts_of("outside_perimeter", None), C.ANY)
        self.assertIs(compliance.counts_of("outside_legal", None), C.CUT)
        with self.assertRaises(ValueError):
            compliance.counts_of("r_x:inner", T.NO_CUT)
        with self.assertRaises(ValueError):
            compliance.check_zones(classes(), {"r_y": runs((0, 0))}, CTYPES)
        with self.assertRaises(ValueError):
            compliance.check_zones(classes(), ZONES, CTYPES)  # sin el peso de r_encinas
        for bad in (-0.1, 10.5, math.nan, "0,02"):
            with self.subTest(thickness=bad), self.assertRaises(ValueError):
                compliance.check(GRID, hand_zones(), START, FINAL, bad)


def flood(mask):
    """Las etiquetas de una inundación celda a celda (4-conexión), numeradas en el orden de su
    primera celda de norte a sur y de oeste a este; −1 fuera."""
    labels = np.full(mask.shape, -1, dtype=np.int64)
    count = 0
    for start in zip(*np.nonzero(mask), strict=True):
        if labels[start] >= 0:
            continue
        labels[start] = count
        queue = deque([start])
        while queue:
            r, c = queue.popleft()
            for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                if (0 <= nr < mask.shape[0] and 0 <= nc < mask.shape[1] and mask[nr, nc]
                        and labels[nr, nc] < 0):
                    labels[nr, nc] = count
                    queue.append((nr, nc))
        count += 1
    return labels, count


class LabelGroupsTest(unittest.TestCase):
    """RF-012-23 (A10, D-41): la misma partición que una inundación celda a celda."""

    def test_same_partition_as_flood_fill(self) -> None:
        rng = np.random.default_rng(12)
        for case in range(200):
            shape = (int(rng.integers(1, 25)), int(rng.integers(1, 25)))
            mask = rng.random(shape) < rng.uniform(0.2, 0.75)
            rows, cols = np.nonzero(mask)
            permutation = rng.permutation(rows.size)
            rows, cols = rows[permutation], cols[permutation]
            with self.subTest(case=case):
                labels, count = compliance.label_groups(rows, cols)
                expected, expected_count = flood(mask)
                self.assertEqual(count, expected_count)
                np.testing.assert_array_equal(labels, expected[rows, cols])

    def test_spirals_and_edge_cases(self) -> None:
        """Una espiral y un peine (muchos saltos de puntero), vacío y celdas repetidas."""
        mask = np.zeros((21, 21), dtype=bool)
        mask[::2, :] = True
        mask[1::4, -1] = True
        mask[3::4, 0] = True
        rows, cols = np.nonzero(mask)
        labels, count = compliance.label_groups(rows, cols)
        self.assertEqual(count, 1)
        self.assertEqual(set(labels.tolist()), {0})
        comb = np.zeros((9, 9), dtype=bool)
        comb[0, :] = True
        comb[:, ::2] = True
        rows, cols = np.nonzero(comb[::-1])
        self.assertEqual(compliance.label_groups(rows, cols)[1], 1)
        labels, count = compliance.label_groups(np.zeros(0, int), np.zeros(0, int))
        self.assertEqual((labels.size, count), (0, 0))
        with self.assertRaises(ValueError):
            compliance.label_groups([0, 0], [1, 1])


class RequestTest(unittest.TestCase):
    """RF-012-21 (D-40): la petición."""

    def test_request(self) -> None:
        masks = access.MaskSet(GRID, "v" * 32, "o" * 32, access.MaskState.CURRENT, (),
                               classes())
        start = surfaces.SurfaceRef(dataset="gis_dtm_inicial")
        finals = tuple(surfaces.SurfaceRef(dataset=f"gis_dtm_final_{k}") for k in range(10))
        request = compliance.ComplianceRequest("V1", start, finals, masks, 0.02)
        self.assertEqual(request.min_thickness_m, 0.02)
        self.assertFalse(request.same_as_start(0))
        same = compliance.ComplianceRequest("V1", start, (start,), masks, 0)
        self.assertTrue(same.same_as_start(0))
        for bad in ((), (*finals, surfaces.SurfaceRef(dataset="once")), (finals[0],) * 2):
            with self.subTest(finals=len(bad)), self.assertRaises(ValueError):
                compliance.ComplianceRequest("V1", start, bad, masks, 0.02)
        with self.assertRaises(ValueError):
            compliance.ComplianceRequest("V1", start, finals[:1], masks, 11.0)
        with self.assertRaises(ValueError):
            compliance.ComplianceRequest(" ", start, finals[:1], masks, 0.02)


class SeveralLegalLimitsTest(unittest.TestCase):
    """RF-012-21, RF-012-22, RF-012-23 (hallazgo F-1, T44): con varios límites legales, un corte
    en la banda hacia dentro se cuenta y se lista una vez: en el recinto de la banda del límite
    al que pertenece su celda, no en la de todos."""

    A, B = "r_conc_a", "r_conc_b"
    INNER_A, INNER_B = "r_conc_a:inner", "r_conc_b:inner"

    def verify(self, items, cell):
        """Compila ``items``, toma los recintos como los guarda ``gis_mskz_`` (``zone_rows``) y
        verifica un corte de 2 m en la celda ``cell`` (fila, columna) de una partida llana."""
        result = None
        for step in compile_mod.compile_steps(compile_mod.CompileRequest(
                items, sl.resolved(items), grid=sl.GRID)):
            if step.result is not None:
                result = step.result
        stored: dict[str, list[tuple[int, int, int]]] = {}
        for name, row, col0, col1 in result.zone_rows():
            stored.setdefault(name, []).append((row, col0, col1))
        zones = {name: Runs(*np.asarray(found, dtype=np.int64).T)
                 for name, found in stored.items()}
        ctypes = {code: zone.ctype for code, zone in result.prepared.zones.items()}
        recintos = compliance.check_zones(result.masks.classes, zones, ctypes, {})
        start = np.full(sl.GRID.shape, 100.0)
        final = start.copy()
        final[cell] -= 2.0
        return result, compliance.check(sl.GRID, recintos, start, final, 0.02)

    def failing(self, found):
        return {item.code: item.counted_m3 for item in found.totals
                if item.verdict is V.FAILS}

    def freeze_notes(self, found):
        """Las notas de «no cumple» que lista el diálogo de congelar (``freeze_findings``): una
        por final, con cada recinto que incumple, a partir de las filas de ``res_chk_``."""
        done = compliance_store.VerifyResult("v", ("final",), (found,), {}, (), ())
        return compliance_store._failures(done.table_rows(), "v")

    def test_a_cut_in_the_band_of_one_concession_is_counted_once(self) -> None:
        """RF-012-22, RF-012-23 (F-1): un corte de 2 m³ en la banda de la concesión A (borde
        oeste) con dos concesiones contiguas incumple solo en la banda de A: un recinto, un
        grupo y una sola línea al congelar; la concesión B no ve nada."""
        _result, found = self.verify(sl.contiguous(), (15, 0))
        self.assertEqual(self.failing(found), {self.INNER_A: 2.0})
        self.assertEqual(found.zone(self.INNER_B).counted_m3, 0.0)
        self.assertEqual([(g.zone, g.volume_m3, g.cells) for g in found.groups],
                         [(self.INNER_A, 2.0, 1)])
        self.assertEqual((found.zone(self.A).cut_m3, found.zone(self.B).cut_m3), (2.0, 0.0))
        (note,) = self.freeze_notes(found)
        self.assertEqual(note.count("(banda hacia dentro)"), 1, note)
        self.assertIn("«r_conc_a» (banda hacia dentro)", note)

    def test_a_cut_in_the_other_concession_goes_to_its_own_band(self) -> None:
        """RF-012-22 (F-1): el mismo corte en el borde este (la concesión B) incumple solo en
        la banda de B."""
        _result, found = self.verify(sl.contiguous(), (15, 59))
        self.assertEqual(self.failing(found), {self.INNER_B: 2.0})
        self.assertEqual([g.zone for g in found.groups], [self.INNER_B])

    def test_a_cut_where_two_overlapping_concessions_meet_is_counted_once(self) -> None:
        """RF-012-22 (F-1): con dos concesiones que se solapan, un corte en la banda de un
        trozo que están en las dos (fila 0, columna 30) incumple en un solo recinto de banda
        (el del primero por código), un grupo, un solo recinto en la nota de congelar."""
        _result, found = self.verify(sl.overlapping(), (0, 30))
        self.assertEqual(self.failing(found), {self.INNER_A: 2.0})
        self.assertEqual([g.zone for g in found.groups], [self.INNER_A])
        self.assertEqual(found.zone(self.INNER_B).counted_m3, 0.0)
        (note,) = self.freeze_notes(found)
        self.assertEqual(note.count("(banda hacia dentro)"), 1, note)

    def test_a_cut_in_a_cell_across_two_concessions_is_still_found(self) -> None:
        """RF-012-22 (F-1): una celda de la banda a caballo de dos concesiones (la columna 30,
        con el borde común a media celda) no está entera en ninguna, pero su corte no se
        pierde: incumple en la banda del primero que la toca."""
        _result, found = self.verify(sl.unaligned(), (0, 30))
        self.assertEqual(self.failing(found), {self.INNER_A: 2.0})
        self.assertEqual(len(found.groups), 1)


if __name__ == "__main__":
    unittest.main()
