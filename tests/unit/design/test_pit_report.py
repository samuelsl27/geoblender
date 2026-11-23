# SPDX-License-Identifier: GPL-3.0-or-later
"""Los hallazgos y las cifras de la corta (spec 018, T20; HU-018-2, HU-018-4; RF-018-26 y 31; CE-018-08 y 11; plan 018 §5.4 A12, §5.7 P-14).

Sobre la corta circular de CE-018-03 con celdas de 2 m (ningún centro de celda cae justo sobre un círculo de radio entero par: no hay celdas
dudosas): sin hallazgos si todo cumple; la inclinación, la berma, un banco sin perfil, la cresta fuera del perímetro y sobre un intocable
(CE-018-08), el área sin excavar y los avisos de rampa; las cifras a mano (longitudes, áreas de fondo y de bermas contadas celda a celda,
volumen por banco) y la longitud de P-14 sobre el terreno inclinado. Sin proyecto y sin Blender."""

from __future__ import annotations

import dataclasses
import math
import unittest
from types import SimpleNamespace

import numpy as np

from tests.support import pit_data as pd
from tests.support import pit_raster as pr
from tests.support.package import import_geoblender
from tests.unit.design import milestone_pit_h1 as h1

pit_bench = import_geoblender("design.pit_bench")
pit_model = import_geoblender("design.pit_model")
pit_report = import_geoblender("design.pit_report")
pit_sky = import_geoblender("design.pit_sky")
pit_surface = import_geoblender("design.pit_surface")
preview = import_geoblender("design.preview")
model = import_geoblender("design.model")

STEP_M = 2.0
TOL = 1.0
"""La tolerancia de cara de los ensayos (°)."""


def surface_of(job: object) -> tuple[object, object]:
    found = pit_bench.ascend(job)
    return found, pit_surface.rasterize(job, found, crs=pd.CRS, vertical=pd.VERTICAL)


def kinds(items: object, kind: str) -> list[object]:
    return [item for item in items if item.kind == kind]


def centres(grid: object) -> tuple[np.ndarray, np.ndarray]:
    """Los centros de las celdas en locales (x al este, y al norte), de la forma de la rejilla."""
    x = (np.arange(grid.ncols) + 0.5) * grid.dx
    y = (grid.nrows - np.arange(grid.nrows) - 0.5) * grid.dy
    return np.meshgrid(x, y)


class CleanPitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = pd.grid_of(STEP_M)
        cls.job = h1.up_job(cls.grid)
        cls.found, cls.surface = surface_of(cls.job)

    def test_nothing_is_found_when_everything_complies(self) -> None:
        """RF-018-26: la corta circular con su perfil: sin inclinación de más, sin berma de menos, sin cresta fuera ni sin excavar."""
        self.assertEqual(pit_report.findings(self.job, self.found.polylines, self.surface, face_tolerance_deg=TOL), ())

    def test_inputs_are_not_modified(self) -> None:
        """RF-018-26: nada se corrige ni se cambia (la partida y la superficie, bit a bit)."""
        start, surface = self.job.start.copy(), self.surface.surface.copy()
        pit_report.findings(self.job, self.found.polylines, self.surface, face_tolerance_deg=TOL)
        pit_report.figures(self.job, self.found.polylines, self.surface, crs=pd.CRS, vertical=pd.VERTICAL)
        self.assertTrue(np.array_equal(start, self.job.start) and np.array_equal(surface, self.surface.surface))

    def test_tolerance_must_be_valid(self) -> None:
        """RF-018-26: una tolerancia negativa es un error del programa."""
        with self.assertRaises(ValueError):
            pit_report.findings(self.job, self.found.polylines, self.surface, face_tolerance_deg=-1.0)

    def test_face_slope_is_reported_per_bench(self) -> None:
        """RF-018-26: con un perfil de 45° la cara real de 60° es un hallazgo por banco (valor ≈ 60°, límite 46°, con su lugar)."""
        flat = model.BenchProfile(**{**dataclasses.asdict(pd.EXPL), "face_deg": 45.0})
        found = pit_report.findings(dataclasses.replace(self.job, profile=flat), self.found.polylines, self.surface, face_tolerance_deg=TOL)
        slopes = kinds(found, "face_slope")
        self.assertEqual(sorted(item.bench for item in slopes), [0, 1, 2, 3, 4])
        for item in slopes:
            self.assertAlmostEqual(item.value, 60.0, delta=0.2)
            self.assertAlmostEqual(item.limit, 46.0, delta=1e-9)
            self.assertEqual(item.unit, "°")
            self.assertTrue(math.isfinite(item.place[0]) and math.isfinite(item.place[1]))

    def test_berm_narrower_than_the_minimum(self) -> None:
        """RF-018-26: con una berma mínima de 8 m, la real de 6 m es un hallazgo en cada banco con pie al mismo nivel (valor ≈ 6 m, límite 8 m)."""
        wide = model.BenchProfile(**{**dataclasses.asdict(pd.EXPL), "berm_m": 8.0})
        found = pit_report.findings(dataclasses.replace(self.job, profile=wide), self.found.polylines, self.surface, face_tolerance_deg=TOL)
        berms = kinds(found, "berm_width")
        self.assertEqual(sorted(item.bench for item in berms), [0, 1, 2, 3])
        for item in berms:
            self.assertAlmostEqual(item.value, 6.0, delta=1e-3)
            self.assertEqual((item.limit, item.unit), (8.0, "m"))

    def test_a_bench_without_a_profile_is_a_finding(self) -> None:
        """RF-018-26: sin perfil para el perímetro (todo sector lleva el suyo) cada banco es un hallazgo ``no_profile``, no un «cumple»."""
        ring = pd.absolute(pd.square_ring(300.0), self.grid)
        sector = pit_model.PitSector("S1", "Sector 1", (((ring),),), profile=self.job.profile)
        job = dataclasses.replace(self.job, profile=None, sectors=(sector,))
        found = pit_report.findings(job, self.found.polylines, self.surface, face_tolerance_deg=TOL)
        self.assertEqual(sorted(item.bench for item in kinds(found, "no_profile")), [0, 1, 2, 3, 4])
        self.assertEqual([item.kind for item in found if item.kind != "no_profile"], [])

    def test_floor_narrower_than_the_minimum(self) -> None:
        """RF-018-26: el fondo circular de 100 m de diámetro frente a un mínimo de 150 m es un hallazgo (ancho ≈ 100 m)."""
        params = dataclasses.replace(self.job.params, min_floor_width_m=150.0)
        found = pit_report.findings(dataclasses.replace(self.job, params=params), self.found.polylines, self.surface, face_tolerance_deg=TOL)
        floors = kinds(found, "floor_width")
        self.assertEqual(len(floors), 1)
        self.assertAlmostEqual(floors[0].value, 100.0, delta=0.2)
        self.assertEqual(floors[0].limit, 150.0)

    def test_ramp_notices_become_findings(self) -> None:
        """RF-018-26 (RF-018-19 y 20): cada aviso de la rampa es un hallazgo con su banco, su valor, su límite y su lugar."""
        notice = preview.Notice("des.pit_ramp_gradient", {"gradient": 12.0, "limit": 10.0, "x": 700060.0, "y": 4400000.0, "bench": 2, "station": 30.0})
        axis = np.array([[700060.0, 4400000.0, 150.0], [700100.0, 4400000.0, 150.0]])
        ramp = SimpleNamespace(name="Rampa 1", notices=(notice,), path=pit_model.RampPath("r1", 0, axis, np.array([3.0, 3.0])))
        found = pit_report.findings(self.job, self.found.polylines, self.surface, face_tolerance_deg=TOL, ramps=(ramp,))
        (item,) = kinds(found, "ramp")
        self.assertEqual((item.value, item.limit, item.bench, item.place, item.unit), (12.0, 10.0, 2, (700060.0, 4400000.0), "%"))


class RestrictionsTest(unittest.TestCase):
    """CE-018-08: el perímetro de actuación, los intocables y lo que no se excava."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = pd.grid_of(STEP_M)
        x, _ = centres(cls.grid)
        cls.east = x > 220.0
        cls.perimeter = ((pd.absolute([(0, 0), (220, 0), (220, 400), (0, 400)], cls.grid),),)
        cls.job = h1.up_job(cls.grid, perimeter=cls.perimeter, cut_allowed=~cls.east)
        cls.found, cls.surface = surface_of(cls.job)
        cls.result = pit_report.findings(cls.job, cls.found.polylines, cls.surface, face_tolerance_deg=TOL)

    def test_crest_outside_the_perimeter(self) -> None:
        """CE-018-08: la longitud de cresta fuera del perímetro (el arco al este de x = 220 m, a mano) y su lugar, por banco."""
        outside = {item.bench: item for item in kinds(self.result, "outside_perimeter")}
        for bench, (_, crest) in enumerate(pd.circle_radii_by_hand()):
            by_hand = 2.0 * crest * math.acos(20.0 / crest)
            self.assertAlmostEqual(outside[bench].value / by_hand, 1.0, delta=1e-3)
            self.assertEqual((outside[bench].limit, outside[bench].unit), (0.0, "m"))
            self.assertGreater(outside[bench].place[0] - pd.origin_of(self.grid)[0], 220.0)

    def test_surface_does_not_move_outside_and_the_area_is_reported(self) -> None:
        """CE-018-08: sin movimiento fuera del perímetro (la partida bit a bit) y el área que no se excava, con su lugar, como hallazgo."""
        self.assertTrue(np.array_equal(self.surface.surface[self.east], self.job.start[self.east]))
        (item,) = kinds(self.result, "unexcavated")
        self.assertAlmostEqual(item.value, float(self.surface.blocked.sum()) * self.grid.cell_area, delta=1e-9)
        self.assertGreater(item.value, 0.0)
        self.assertGreater(item.place[0] - pd.origin_of(self.grid)[0], 220.0)
        self.assertEqual(item.unit, "m²")

    def test_crest_on_an_untouchable(self) -> None:
        """CE-018-08: la longitud de cresta sobre una franja intocable (x de 240 a 280 m; a mano, con un trozo de muestreo de 0,5 m) y su lugar."""
        x, _ = centres(self.grid)
        strip = (x > 240.0) & (x < 280.0)
        job = h1.up_job(self.grid, untouchable=strip)
        found, surface = surface_of(job)
        result = pit_report.findings(job, found.polylines, surface, face_tolerance_deg=TOL)
        on = {item.bench: item for item in kinds(result, "on_untouchable")}
        for bench, (_, crest) in enumerate(pd.circle_radii_by_hand()):
            if crest <= 40.0:
                self.assertNotIn(bench, on)
                continue
            by_hand = 2.0 * crest * (math.acos(40.0 / crest) - math.acos(min(1.0, 80.0 / crest)))
            self.assertAlmostEqual(on[bench].value, by_hand, delta=1.0)
            local_x = on[bench].place[0] - pd.origin_of(self.grid)[0]
            self.assertTrue(240.0 - 1.0 <= local_x <= 280.0 + 1.0)
        self.assertTrue(np.array_equal(surface.surface[strip], job.start[strip]))


class FiguresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = pd.grid_of(STEP_M)
        cls.job = h1.up_job(cls.grid)
        cls.found, cls.surface = surface_of(cls.job)
        cls.figures = pit_report.figures(cls.job, cls.found.polylines, cls.surface, crs=pd.CRS, vertical=pd.VERTICAL)
        x, y = centres(cls.grid)
        cls.radius = np.hypot(x - pd.CENTER[0], y - pd.CENTER[1])

    def test_counts_levels_and_lengths(self) -> None:
        """RF-018-31: cinco bancos, fondo a 125 m y coronación a 175 m; la longitud de pies y de crestas, la de los círculos a mano (todo está a la cota del terreno o bajo ella)."""
        values = self.figures.values
        self.assertEqual((values["des.pit_benches"], values["des.pit_z_bottom_m"], values["des.pit_z_top_m"]), (5, 125.0, 175.0))
        radii = pd.circle_radii_by_hand()
        self.assertAlmostEqual(values["des.pit_len_foot_m"] / (2.0 * math.pi * sum(foot for foot, _ in radii)), 1.0, delta=1e-4)
        self.assertAlmostEqual(values["des.pit_len_crest_m"] / (2.0 * math.pi * sum(crest for _, crest in radii)), 1.0, delta=1e-4)

    def test_floor_and_berm_areas_counted_cell_by_cell(self) -> None:
        """RF-018-31: el área del fondo y la de cada berma, contadas celda a celda por radio (a ≤ 10⁻⁹ relativo; las mismas celdas)."""
        cell = self.grid.cell_area
        radii = pd.circle_radii_by_hand()
        floor = float(np.count_nonzero(self.radius < pd.CIRCLE_RADIUS_M)) * cell
        self.assertAlmostEqual(self.figures.values["des.pit_area_floor_m2"] / floor, 1.0, delta=1e-9)
        berms = 0.0
        for found in self.figures.benches:
            if found.bench < 4:
                by_hand = float(np.count_nonzero((self.radius > radii[found.bench][1]) & (self.radius < radii[found.bench + 1][0]))) * cell
                self.assertAlmostEqual(found.area_berm_m2 / by_hand, 1.0, delta=1e-9)
                berms += by_hand
            else:
                self.assertEqual(found.area_berm_m2, 0.0)  # la cresta del último banco sale al terreno
        self.assertAlmostEqual(self.figures.values["des.pit_area_berm_m2"] / berms, 1.0, delta=1e-9)
        self.assertEqual([item.area_floor_m2 is not None for item in self.figures.benches], [True, False, False, False, False])

    def test_cut_and_cut_by_bench(self) -> None:
        """RF-018-31 (CE-018-11): el corte es el de la superficie, el volumen por banco suma el total (≤ 10⁻⁹) y cada banco es su tronco de cono (≤ 0,1 %)."""
        values = self.figures.values
        self.assertEqual(values["des.pit_cut_m3"], self.surface.cut_m3)
        self.assertAlmostEqual(sum(item.cut_m3 for item in self.figures.benches) / self.surface.cut_m3, 1.0, delta=1e-9)
        self.assertAlmostEqual(values["des.pit_area_m2"], float(np.count_nonzero(self.surface.cut_cells)) * self.grid.cell_area, delta=1e-9)
        for item, (foot, crest) in zip(self.figures.benches, pd.circle_radii_by_hand(), strict=True):
            frustum = math.pi * 10.0 / 3.0 * (foot * foot + foot * crest + crest * crest)
            self.assertLess(abs(item.cut_m3 / frustum - 1.0), 1e-3)
            self.assertEqual((item.z_foot_m, item.z_crest_m), (125.0 + 10.0 * item.bench, 135.0 + 10.0 * item.bench))

    def test_specs_have_type_unit_and_scope(self) -> None:
        """RF-018-31: las cifras salen CALCULADO con unidad y ámbito, solo las que existen (sin línea de cielo ni rampa no hay las suyas)."""
        keys = {item.key for item in self.figures.specs}
        self.assertIn("des.pit_cut_m3", keys)
        self.assertIn("des.pit_findings", keys)
        self.assertFalse({"des.pit_sky_len_m", "des.pit_ramp_len_m"} & keys)
        by_key = {item.key: item for item in self.figures.specs}
        self.assertEqual((by_key["des.pit_cut_m3"].unit, by_key["des.pit_benches"].value), ("m3", 5))

    def test_skyline_and_findings_are_summarized(self) -> None:
        """RF-018-29 y 31: con la línea de cielo y los hallazgos dados, sus cifras entran en las de la corta."""
        sky = pit_sky.skyline(self.job.start, self.surface.stepped, self.grid, crs=pd.CRS, vertical=pd.VERTICAL)
        figures = pit_report.figures(self.job, self.found.polylines, self.surface, crs=pd.CRS, vertical=pd.VERTICAL, skyline=sky, found=(1, 2, 3))
        self.assertEqual(figures.values["des.pit_findings"], 3)
        self.assertEqual(figures.values["des.pit_sky_parts"], sky.n_parts)
        self.assertEqual(figures.values["des.pit_sky_len_m"], sky.length_m)
        self.assertIsNone(figures.values["des.pit_sky_dist_legal_m"])

    def test_ramp_figures_and_band_volume(self) -> None:
        """RF-018-31: la longitud, la pendiente media (ponderada) y máxima y el volumen de corte de la banda (celdas a menos del semiancho del eje, a mano)."""
        axis = pd.absolute([(260, 200), (300, 200)], self.grid)
        axis3 = np.column_stack([axis, [150.0, 150.0]])
        ramp = SimpleNamespace(name="R", notices=(), path=pit_model.RampPath("r1", 0, axis3, np.array([3.0, 3.0])), length_m=40.0,
                               mean_gradient_pct=8.0, max_gradient_pct=9.0)
        figures = pit_report.figures(self.job, self.found.polylines, self.surface, crs=pd.CRS, vertical=pd.VERTICAL, ramps=(ramp, ramp))
        values = figures.values
        self.assertEqual((values["des.pit_ramp_len_m"], values["des.pit_ramp_gradient_mean_pct"], values["des.pit_ramp_gradient_max_pct"]),
                         (80.0, 8.0, 9.0))
        x, y = centres(self.grid)
        dx = np.clip(x, 260.0, 300.0)
        inside = np.hypot(x - dx, y - 200.0) <= 3.0
        cut = np.where(inside & self.surface.cut_cells, self.job.start - self.surface.surface, 0.0)
        by_hand = float(cut.sum()) * self.grid.cell_area
        self.assertGreater(by_hand, 0.0)
        self.assertAlmostEqual(values["des.pit_ramp_band_m3"] / (2.0 * by_hand), 1.0, delta=1e-9)


class OnTheGroundTest(unittest.TestCase):
    def test_only_what_exists_at_or_below_the_terrain_counts(self) -> None:
        """RF-018-31 (P-14): sobre el terreno inclinado (130 m en x = 0 y +10 % al este) lo que queda en el aire no cuenta: la longitud de cada cresta es
        la de sus lados con la cota a ≤ 1 cm del terreno o por debajo, contada a mano con 400 puntos por lado."""
        grid = pd.grid_of(STEP_M)
        terrain = pd.inclined_terrain(grid)
        job = h1.up_job(grid, start=terrain)
        found, surface = surface_of(job)
        figures = pit_report.figures(job, found.polylines, surface, crs=pd.CRS, vertical=pd.VERTICAL)
        by_hand = {"foot": 0.0, "crest": 0.0}
        total = {"foot": 0.0, "crest": 0.0}
        for item in found.polylines:
            xy = pr.local_ring(item, grid)
            nxt = np.roll(xy, -1, axis=0)
            length = np.hypot(*(nxt - xy).T)
            t = (np.arange(400) + 0.5) / 400.0
            along = xy[:, None, :] + (nxt - xy)[:, None, :] * t[None, :, None]
            ground = 130.0 + 0.1 * along[:, :, 0]
            below = item.z_m <= ground + 0.01
            by_hand[str(item.kind)] += float((length * below.mean(axis=1)).sum())
            total[str(item.kind)] += float(length.sum())
        for kind, key in (("foot", "des.pit_len_foot_m"), ("crest", "des.pit_len_crest_m")):
            self.assertLess(by_hand[kind], total[kind] - 1.0, "la ensayo ha de tener un trozo en el aire")
            self.assertAlmostEqual(figures.values[key], by_hand[kind], delta=1.5)


if __name__ == "__main__":
    unittest.main()
