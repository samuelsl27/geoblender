# SPDX-License-Identifier: GPL-3.0-or-later
"""La superficie de diseño respeta las máscaras (spec 013, T12; HU-013-2, HU-013-6; RF-013-29,
RF-013-30; CE-013-06; plan 013 A10, A11; D-9).

Como CE-012-05, ahora con diseños que calcula Geoblender y los recintos de la 012: **100
envolventes y escalonados sintéticos** (semillas sueltas, de contorno y macizas en cualquier parte
de la rejilla del sitio, también sobre lo prohibido y fuera del perímetro; envolvente ascendente o
descendente; corte o relleno; perfiles de altura, cara, berma, ancla y factor de malla variados;
con y sin recorte final) sobre un terreno con relieve, compuestos con las máscaras de V01 (cinco
restricciones, el límite legal, el perímetro y su franja de solo relleno), **verifican 0 m³ en
todos los recintos** con las funciones de ``reserves`` de la 012 (``check_zones`` y el verificador
por bandas con el espesor mínimo ``res.verify.min_thickness_m``):

- ninguno de los 100 diseños incumple un recinto y lo que cuenta en cada uno es exactamente 0 m³;
- el mismo escalonado **sin componer** (el escalonado donde hay envolvente) incumple en la mayoría
  de los casos: la prueba tiene dientes;
- las cifras del informe (desmonte, terraplén y área con movimiento) son las que la 012 mide para
  el conjunto de la rejilla, a ≤ 10⁻¹² relativo;
- mover **una** celda a una zona prohibida hace que esa zona, y solo ella, no cumpla; moverla por
  debajo del espesor mínimo, o a un sitio admitido, no hace fallar nada.

Que el cálculo se niega en un sector con la búsqueda pendiente (RF-013-05) es de
``tests/unit/design/test_sectors.py``, y que la superficie queda obsoleta con su causa al cambiar
una restricción, de las pruebas de ``store`` y del hito H2 (T14, T15 y T29).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import design_fixtures as dfx
from tests.support.package import import_geoblender

benching = import_geoblender("design.benching")
compose = import_geoblender("design.compose")
envelopes = import_geoblender("design.envelopes")
design_model = import_geoblender("design.model")
report = import_geoblender("design.report")
access = import_geoblender("gis.masks.access")
compliance = import_geoblender("reserves.compliance")
res_provenance = import_geoblender("reserves.provenance")
zones_mod = import_geoblender("gis.masks.zones")

MIN_THICKNESS_M = float(res_provenance.VERIFY_MIN_THICKNESS_DEF.default)
"""El espesor mínimo de verificación de la 012 (m)."""
DESIGNS = 100
CUT = design_model.BenchSense.CUT
FILL = design_model.BenchSense.FILL
COUNTING = {"cut": (compliance.Counts.CUT, compliance.Counts.ANY),
            "fill": (compliance.Counts.FILL, compliance.Counts.ANY)}
"""Los modos de contar que se ven afectados por un corte y por un relleno."""


def run(steps: Any) -> Any:
    return list(steps)[-1].result


def terrain_of(shape: tuple[int, int]) -> np.ndarray:
    """El terreno de partida: el llano del sitio (650 m) con un relieve suave de ±4 m."""
    rows, cols = np.indices(shape)
    return (cfx.site_start().values + 2.5 * np.sin(cols / 11.0) * np.cos(rows / 17.0)
            + 1.5 * np.sin((rows + cols) / 9.0))


class Verification:
    """Los recintos de V01 con el verificador de la 012 listo para varias finales."""

    def __init__(self, masks: Any) -> None:
        self.masks = masks
        grid = masks.grid
        found = list(compliance.check_zones(masks.classes, masks.zones, masks.ctypes,
                                            masks.weights))
        everything = zones_mod.Runs.from_mask(np.ones(grid.shape, dtype=bool))
        found.append(compliance.CheckZone("todo", None, compliance.Counts.NOTHING, everything))
        self.zones = tuple(found)
        self.index = compliance.zone_index(grid, self.zones)
        self.shape = grid.shape
        self.masks_by_code = {zone.code: zone.runs.mask(grid.shape) for zone in self.zones}

    def check(self, start: np.ndarray, final: np.ndarray) -> Any:
        """La verificación de ``final`` frente a ``start`` por recinto (una banda: toda la rejilla)."""
        checker = compliance.Checker(self.masks.grid, self.zones, MIN_THICKNESS_M,
                                     index=self.index)
        checker.add(0, start, final)
        return checker.result()

    def exclusive(self, code: str, kind: str) -> np.ndarray:
        """Las celdas del recinto ``code`` que ningún otro recinto que cuenta ``kind`` (corte o
        relleno) comparte."""
        others = np.zeros(self.shape, dtype=bool)
        for zone in self.zones:
            if zone.code != code and zone.counts in COUNTING[kind]:
                others |= self.masks_by_code[zone.code]
        return self.masks_by_code[code] & ~others


class RandomDesigns:
    """Un generador de diseños sintéticos con semillas y perfiles variados (determinista)."""

    def __init__(self, masks: Any, start: np.ndarray) -> None:
        self.masks = masks
        self.grid = masks.grid
        self.start = start

    def make(self, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray, str]:
        """``(escalonado, superficie de diseño, sentido)`` de un diseño aleatorio: el escalonado
        es el resultado del escalonado (con o sin recorte) donde hay envolvente y la partida
        donde no; la superficie de diseño, su composición con las máscaras."""
        shape = self.grid.shape
        direction = str(rng.choice(["up", "down"]))
        sense = str(rng.choice(["cut", "fill"]))
        height = float(rng.choice([5.0, 7.5, 10.0]))
        face = float(rng.uniform(45.0, 75.0))
        berm = float(rng.uniform(4.0, 10.0))
        anchor = float(rng.uniform(600.0, 650.0))
        mesh = float(rng.choice([1.0, 0.95]))
        profile = design_model.BenchProfile("p", "P", height, face, berm, anchor, mesh)
        kind = str(rng.choice(dfx.ZONE_KINDS))
        where = np.isfinite(dfx.random_zone(rng, shape, kind, 1.0))
        shift = float(rng.uniform(5.0, 40.0)) * (1.0 if direction == "down" else -1.0)
        seeds = np.where(where, self.start + shift + rng.normal(0.0, 1.5, shape), np.inf)
        slope = envelopes.SlopeField(profile.general_tan * mesh)
        envelope = run(envelopes.chamfer_steps(seeds, self.grid, slope, direction,
                                               name="aleatoria")).grid
        tan_face = math.tan(math.radians(face))
        function = benching.bench_cut if sense == "cut" else benching.bench_fill
        stairs = function(envelope, height, tan_face, berm, anchor)
        if rng.random() < 0.5:
            stairs = run(benching.final_trim_steps(stairs, envelope, self.grid, tan_face, mesh,
                                                   sense, name="aleatoria")).grid
        allowed = compose.allowed_cells(self.masks, sense)
        design = compose.compose(self.start, stairs, allowed, sense)
        return stairs, design, sense


class DesignMasksTest(dfx.DesignProjectCase):
    """CE-013-06: la composición con las máscaras verifica 0 m³ fuera de lo admitido."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.the_masks = access.load_masks(cls.project, cls.v1.uid)
        cls.verification = Verification(cls.the_masks)
        cls.terrain = terrain_of(cls.the_masks.grid.shape)

    def test_one_hundred_random_designs_verify_zero_cubic_metres(self) -> None:
        """RF-013-29: 100 diseños aleatorios (todas las combinaciones de dirección y sentido, con y
        sin recorte) no incumplen ningún recinto de la 012 y cuentan exactamente 0 m³ en los que
        juzgan; la gran mayoría mueve tierra (la prueba no es vacía) y sin componer incumplirían
        casi todos."""
        generator = RandomDesigns(self.the_masks, self.terrain)
        rng = np.random.default_rng(20261102)
        moving = raw_failures = 0
        senses: set[str] = set()
        for number in range(DESIGNS):
            stairs, design, sense = generator.make(rng)
            senses.add(sense)
            with self.subTest(diseno=number, sentido=sense):
                result = self.verification.check(self.terrain, design)
                self.assertFalse(result.fails)
                for total in result.totals:
                    if total.counts in (compliance.Counts.CUT, compliance.Counts.FILL,
                                        compliance.Counts.ANY):
                        self.assertEqual(total.counted_m3, 0.0, total.code)
                        self.assertEqual(total.verdict, compliance.Verdict.COMPLIES, total.code)
                admitted = compose.allowed_cells(self.the_masks, sense)
                moved = report.moved_cells(self.terrain, design, MIN_THICKNESS_M)
                self.assertFalse(np.any(moved & ~admitted))
                self.assertEqual(design[~admitted].tobytes(), self.terrain[~admitted].tobytes())
                moving += int(moved.any())
                naked = np.where(np.isfinite(stairs), stairs, self.terrain)
                raw_failures += int(self.verification.check(self.terrain, naked).fails)
        self.assertEqual(senses, {"cut", "fill"})
        self.assertGreaterEqual(moving, 80)
        self.assertGreaterEqual(raw_failures, 80)

    def test_the_report_figures_are_the_ones_the_012_measures(self) -> None:
        """RF-013-30: el desmonte, el terraplén y el área con movimiento del informe son los del
        recinto «toda la rejilla» de la 012 (mismo umbral, todo el espesor), a ≤ 10⁻¹² relativo,
        en 20 de los diseños aleatorios (la mayoría mueve tierra)."""
        generator = RandomDesigns(self.the_masks, self.terrain)
        rng = np.random.default_rng(7)
        moving = 0
        for number in range(20):
            _stairs, design, sense = generator.make(rng)
            allowed = compose.allowed_cells(self.the_masks, sense)
            found = run(report.report_steps(
                self.terrain, design, self.the_masks.grid, allowed,
                min_thickness_m=MIN_THICKNESS_M, face_deg=60.0, face_tolerance_deg=1.0,
                warning_ratio=2.0))
            measured = self.verification.check(self.terrain, design).zone("todo")
            with self.subTest(diseno=number):
                for mine, theirs in ((found.cut_m3, measured.cut_m3),
                                     (found.fill_m3, measured.fill_m3),
                                     (found.moved_area_m2, measured.moved_m2),
                                     (found.nodata_area_m2, measured.nodata_m2)):
                    if theirs == 0.0:
                        self.assertEqual(mine, 0.0)
                    else:
                        self.assertAlmostEqual(mine / theirs, 1.0, delta=1e-12)
            moving += int(found.moved_cells > 0)
        self.assertGreaterEqual(moving, 15)

    def test_moving_one_cell_into_a_forbidden_zone_fails_that_zone_only(self) -> None:
        """RF-013-29, CE-013-06: con la partida intacta (0 m³ en todo), mover UNA celda 1 m en una
        zona prohibida —la torre en los dos sentidos, la cuneta («sin corte») excavando, la balsa
        («sin relleno») rellenando, y lo de fuera del límite legal y del perímetro— hace que esa zona
        no cumpla y que ninguna otra lo haga."""
        cases = (("torre", "cut"), ("torre", "fill"), ("cuneta", "cut"), ("balsa", "fill"),
                 ("concesion:inner", "cut"), ("outside_legal", "cut"),
                 ("outside_perimeter", "cut"), ("outside_perimeter", "fill"))
        untouched = self.verification.check(self.terrain, self.terrain)
        self.assertFalse(untouched.fails)
        for code, kind in cases:
            with self.subTest(zona=code, movimiento=kind):
                cells = np.argwhere(self.verification.exclusive(code, kind))
                self.assertGreater(len(cells), 0)
                row, col = (int(value) for value in cells[len(cells) // 2])
                moved = self.terrain.copy()
                moved[row, col] += -1.0 if kind == "cut" else 1.0
                result = self.verification.check(self.terrain, moved)
                failing = [total.code for total in result.totals
                           if total.verdict == compliance.Verdict.FAILS]
                self.assertEqual(failing, [code])
                self.assertEqual(result.zone(code).counted_m3, self.the_masks.grid.cell_area)

    def test_moving_below_the_minimum_thickness_or_where_admitted_fails_nothing(self) -> None:
        """Mover una celda prohibida menos que el espesor mínimo (0,02 m) no es movimiento para
        la 012; y mover 1 m una celda admitida (corte en el dominio de la concesión, relleno en la
        franja) no incumple ninguna zona."""
        cut_cell = np.argwhere(compose.admitted(self.the_masks, CUT))[0]
        fill_cell = np.argwhere(self.the_masks.fill_strip())[0]
        for label, cell, shift in (("prohibida, 0,01 m", np.argwhere(
                                        self.verification.exclusive("torre", "cut"))[0], -0.01),
                                   ("corte admitido", cut_cell, -1.0),
                                   ("relleno en la franja", fill_cell, 1.0)):
            with self.subTest(celda=label):
                moved = self.terrain.copy()
                moved[int(cell[0]), int(cell[1])] += shift
                self.assertFalse(self.verification.check(self.terrain, moved).fails)

    def test_a_fill_forty_times_the_previous_one_warns_and_still_verifies(self) -> None:
        """CE-013-07 (error 66): un relleno de 716.000 m³ frente a los 17.607 m³ de la revisión
        congelada (×40,7) avisa con el umbral de aviso (2,0), pero el diseño sigue verificando
        0 m³ fuera de lo admitido: el aviso informa, no sustituye a las máscaras."""
        allowed = compose.allowed_cells(self.the_masks, FILL)
        cell_area = self.the_masks.grid.cell_area
        thickness = dfx.FILL_CURRENT_M3 / (int(allowed.sum()) * cell_area)
        design = compose.compose(self.terrain, self.terrain + thickness, allowed, FILL)
        previous = report.Previous("diseno_1", "V01.r1", cut_m3=0.0, fill_m3=dfx.FILL_PREVIOUS_M3)
        found = run(report.report_steps(
            self.terrain, design, self.the_masks.grid, allowed, min_thickness_m=MIN_THICKNESS_M,
            face_deg=60.0, face_tolerance_deg=1.0, warning_ratio=2.0, operation="diseno_1",
            previous=previous))
        self.assertAlmostEqual(found.fill_m3 / dfx.FILL_CURRENT_M3, 1.0, delta=1e-9)
        self.assertEqual(found.cut_m3, 0.0)
        (notice,) = [n for n in found.notices if n.code == "des.magnitude_fill"]
        self.assertAlmostEqual(dict(notice.values)["ratio"], dfx.FILL_RATIO, delta=1e-6)
        self.assertFalse(self.verification.check(self.terrain, design).fails)

    def test_the_composition_is_what_makes_the_difference(self) -> None:
        """Un escalonado que atraviesa todo el sitio incumple varios recintos sin componer
        (dos niveles por debajo del terreno en corte, por encima en relleno) y ninguno compuesto."""
        for sense, shift in ((CUT, -8.0), (FILL, 8.0)):
            with self.subTest(sentido=sense.value):
                stairs = self.terrain + shift
                naked = self.verification.check(self.terrain, stairs)
                self.assertTrue(naked.fails)
                allowed = compose.allowed_cells(self.the_masks, sense)
                design = compose.compose(self.terrain, stairs, allowed, sense)
                checked = self.verification.check(self.terrain, design)
                self.assertFalse(checked.fails)
                self.assertTrue(report.moved_cells(self.terrain, design, MIN_THICKNESS_M).any())


if __name__ == "__main__":
    import unittest

    unittest.main()
