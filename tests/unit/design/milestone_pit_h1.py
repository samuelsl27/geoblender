# SPDX-License-Identifier: GPL-3.0-or-later
"""HITO H1 de la corta por bancos (spec 018, T13; HU-018-1, HU-018-2; RF-018-08, 10, 11, 12, 13; CE-018-01 a 04; E1 a E3; plan 018 §7.1, §7.5).

Los bancos y el desfase **sin Blender y sin rampa**, antes de seguir con las rampas y la superficie (si un error de la rampa o del
rasterizado se confundiera con uno de la geometría, no se sabría dónde buscar):

- **E1**: la corta circular de CE-018-03 (lados y cotas a mano; el volumen de las polilíneas rasterizado con celdas de 4, 2 y 1 m contra
  los 961.661,57 m³ analíticos a ≤ 0,1 %, D-11; el rasterizado es de fuerza bruta, ``tests/support/pit_raster.py``, y no usa ``gis``).
- **E2**: el límite cuadrado de CE-018-04 (lados de pie 180, 148, 116, 84 y 52 m, parada por el ancho, con cota de fondo 70 m, 3 bancos;
  volumen de las caras contra los troncos de pirámide a ≤ 0,1 % con celdas de ≤ 2 m).
- **E3** en el dominio: la roseta de CE-018-02 con n = 2 (avance de ``2·h/tan α + B`` por azimut).
- **Robustez** (S-1): la batería de la T09 (``tests/unit/gis/milestone_offset_robustness.py``, 300 + 60 casos) corre en el mismo paso
  «hito»; aquí se comprueba que sigue existiendo con su criterio y se pasa por los bancos una muestra de cortas rugosas (ascendentes y
  descendentes, con y sin roseta): sin rechazos, fiables y sin polilíneas que se corten.

Paso «hito» (P-16): el rasterizado con celdas de 1 m y la muestra rugosa pesan más de 1 s."""

from __future__ import annotations

import dataclasses
import math
import sys
import unittest

import numpy as np

from tests.support import offset_oracle as oracle
from tests.support import pit_data as pd
from tests.support import pit_raster as pr
from tests.support.package import import_geoblender

pit_bench = import_geoblender("design.pit_bench")
pit_model = import_geoblender("design.pit_model")
pit_rose = import_geoblender("design.pit_rose")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")

ARC_M = pd.HYPOTHESES.arc_hand_m
TINY_M = 1e-6
CELLS_M = (4.0, 2.0, 1.0)
VOLUME_TOL = 1e-3
"""D-11: ≤ 0,1 % (HIPÓTESIS) con celdas de ≤ 2 m."""
REPORT: list[str] = []


def tearDownModule() -> None:
    """El informe corto del H1 (a la salida de errores)."""
    print("\nINFORME H1 (T13):\n  " + "\n  ".join(REPORT), file=sys.stderr)


def up_job(grid: object = pd.GRID, **changes: object) -> object:
    values: dict[str, object] = {
        "request": pit_model.PitRequest(name="Corta 1", fields=pit_model.LayerFields(layer="gis_fea_fondos", name_field="nombre"),
                                        mode="up", start="terreno", level_field="cota_m"),
        "code": "PIT-001", "grid": grid, "start": pd.flat_terrain(grid), "cut_allowed": np.ones(grid.shape, bool),
        "fill_allowed": np.zeros(grid.shape, bool), "untouchable": np.zeros(grid.shape, bool),
        "sources": (pit_model.PitSource("fondo", pd.absolute(pd.circle_ring(), grid), pd.FLOOR_Z_M),),
        "params": pit_model.PitParams(arc_tol_m=ARC_M, simplify_m=TINY_M), "profile": model.BenchProfile(**dataclasses.asdict(pd.EXPL)),
    }
    values.update(changes)
    return pit_model.PitJob(**values)


def down_job(grid: object = pd.GRID, **changes: object) -> object:
    values: dict[str, object] = {
        "request": pit_model.PitRequest(name="Corta 1", fields=pit_model.LayerFields(layer="gis_fea_limites", name_field="nombre"),
                                        mode="down", start="terreno"),
        "code": "PIT-001", "grid": grid, "start": pd.limit_terrain(grid), "cut_allowed": np.ones(grid.shape, bool),
        "fill_allowed": np.zeros(grid.shape, bool), "untouchable": np.zeros(grid.shape, bool),
        "sources": (pit_model.PitSource("limite", pd.absolute(pd.square_ring(pd.LIMIT_SIDE_M), grid), None),),
        "params": pit_model.PitParams(arc_tol_m=ARC_M, simplify_m=TINY_M, min_floor_width_m=pd.MIN_FLOOR_WIDTH_M),
        "profile": model.BenchProfile(**dataclasses.asdict(pd.DESD)),
    }
    values.update(changes)
    return pit_model.PitJob(**values)


def of_kind(found: object, kind: str, bench: int | None = None) -> list[object]:
    return [item for item in found.polylines if item.kind == kind and (bench is None or item.bench == bench)]


class CircleE1Test(unittest.TestCase):
    """E1 y CE-018-03: la corta circular, sin rampa."""

    def test_volume_with_cells_of_4_2_and_1_m(self) -> None:
        """CE-018-03, D-11: el volumen de las polilíneas del motor con celdas de 4, 2 y 1 m coincide con el analítico a ≤ 0,1 %."""
        exact = pd.circle_volume_by_hand()
        tan_face = math.tan(math.radians(60.0))
        for step in CELLS_M:
            with self.subTest(cell_m=step):
                grid = pd.grid_of(step)
                found = pit_bench.ascend(up_job(grid))
                self.assertEqual(found.count, 5)
                volume = pr.volume_m3(pr.circle_rings(found, grid), outer_first=False, grid=grid, terrain_m=pd.TOP_Z_M,
                                      floor_m=pd.FLOOR_Z_M, height_m=10.0, tan_face=tan_face)
                diff = volume / exact - 1.0
                REPORT.append(f"E1 círculo, celdas de {step:g} m: {volume:,.1f} m³ frente a {exact:,.2f} analíticos ({diff * 100:+.4f} %)")
                self.assertLessEqual(abs(diff), VOLUME_TOL)

    def test_radii_levels_and_sides(self) -> None:
        """CE-018-03: 5 bancos, pie k a z₀ + k·h y cresta a z₀ + (k + 1)·h (≤ 10⁻⁹ m), radios a mano (cresta = pie + h/tan α, pie
        siguiente = cresta + B) dentro de la tolerancia de arco y la flecha del fondo; salida a superficie y fiable."""
        found = pit_bench.ascend(up_job())
        self.assertEqual((found.count, found.stop, found.reliable), (5, pit_model.StopCriterion.SURFACE, True))
        sagitta = pd.CIRCLE_RADIUS_M * (1.0 - math.cos(math.pi / pd.CIRCLE_VERTICES))
        for k, (foot, crest) in enumerate(pd.circle_radii_by_hand()):
            for kind, expected, steps in (("foot", foot, 2 * k + 1), ("crest", crest, 2 * k + 2)):
                item = of_kind(found, kind, k)[0]
                level = pd.FLOOR_Z_M + (k + (1 if kind == "crest" else 0)) * 10.0
                self.assertTrue(np.all(np.abs(item.vertices[:, 2] - level) <= 1e-9))
                xy = pr.local_ring(item, pd.GRID)
                radius = np.hypot(xy[:, 0] - pd.CENTER[0], xy[:, 1] - pd.CENTER[1])
                self.assertGreaterEqual(float(radius.min()), expected - sagitta - 1e-9)
                self.assertLessEqual(float(radius.max()), expected + steps * ARC_M + sagitta + 1e-9)
        REPORT.append(f"E1 círculo: 5 bancos, salida a superficie, volumen de las caras {found.face_volume_m3:,.2f} m³ sin rejilla")


class LimitE2Test(unittest.TestCase):
    """E2 y CE-018-04: el límite cuadrado, sin rampa."""

    def test_sides_stop_and_bottom_level(self) -> None:
        """CE-018-04: lados de pie 180, 148, 116, 84 y 52 m y parada por el ancho mínimo (el siguiente, 20 m < 30 m); fondo a 50 m con
        52 m de lado; con cota de fondo 70 m, 3 bancos y parada por esa cota."""
        found = pit_bench.descend(down_job())
        by_hand, criterion = pd.limit_benches_by_hand()
        self.assertEqual(criterion, "min_width")
        self.assertEqual((found.count, found.stop, found.reliable), (5, pit_model.StopCriterion.FLOOR_WIDTH, True))
        for k, bench in enumerate(by_hand):
            for kind, side in (("foot", bench.foot_side_m), ("crest", bench.crest_side_m)):
                xy = pr.local_ring(of_kind(found, kind, k)[0], pd.GRID)
                self.assertAlmostEqual(float(max(np.ptp(xy[:, 0]), np.ptp(xy[:, 1]))), side, delta=1e-6)
        self.assertEqual(found.floor_level_m, pd.LIMIT_FLOOR_Z_M)
        self.assertAlmostEqual(found.floor_width_m, 52.0, delta=0.01)
        shallow = pit_bench.descend(down_job(params=pit_model.PitParams(
            arc_tol_m=ARC_M, simplify_m=TINY_M, min_floor_width_m=pd.MIN_FLOOR_WIDTH_M, bottom_level_m=pd.LIMIT_BOTTOM_Z_M)))
        self.assertEqual(shallow.count, 3)
        REPORT.append("E2 límite cuadrado: 5 bancos, lados de pie 180/148/116/84/52 m a ≤ 1e-6 m, parada por el ancho (20 m < 30 m); con "
                      "cota de fondo 70 m, 3 bancos")

    def test_volume_with_cells_of_4_2_and_1_m(self) -> None:
        """CE-018-04: el volumen de las caras rasterizado contra los troncos de pirámide a mano: ≤ 0,1 % con celdas de 2 y 1 m (D-11);
        con 4 m solo ≤ 1 % (el muestreo de una cara de 10 m con celdas de 4 m no se compensa)."""
        exact = pr.hand_square_volume_m3()
        for step in CELLS_M:
            with self.subTest(cell_m=step):
                grid = pd.grid_of(step)
                found = pit_bench.descend(down_job(grid))
                volume = pr.volume_m3(pr.square_rings(found, grid), outer_first=True, grid=grid, terrain_m=pd.LIMIT_TERRAIN_Z_M,
                                      floor_m=pd.LIMIT_FLOOR_Z_M, height_m=10.0, tan_face=1.0)
                diff = volume / exact - 1.0
                REPORT.append(f"E2 límite, celdas de {step:g} m: {volume:,.1f} m³ frente a {exact:,.2f} a mano ({diff * 100:+.4f} %)")
                self.assertLessEqual(abs(diff), VOLUME_TOL if step <= 2.0 else 1e-2)


class RoseDoubleE3Test(unittest.TestCase):
    """E3 en el dominio y CE-018-02: la roseta de dos rangos con n = 2 sobre el fondo circular."""

    def test_advance_by_azimuth_with_double_benches(self) -> None:
        """RF-018-08, 10: con n = 2 el avance entre bermas es 2·h/tan α + B por azimut (cara que mira a 90° en el oeste: 11,547 + 6 m; a
        270° en el este: 20 + 6 m), y los bancos suben de 20 en 20 m."""
        rose = tuple(pit_rose.RoseRange(r.from_deg, r.to_deg, r.face_deg, r.berm_m) for r in pd.ROSE_TWO_RANGES)
        found = pit_bench.ascend(up_job(rose=rose, params=pit_model.PitParams(arc_tol_m=ARC_M, simplify_m=TINY_M, n_berm=2)))
        self.assertEqual((found.count, found.stop, found.reliable), (3, pit_model.StopCriterion.SURFACE, True))
        west_run = 2.0 * 10.0 / math.tan(math.radians(60.0))
        east_run = 2.0 * 10.0 / math.tan(math.radians(45.0))
        west, east = pd.CIRCLE_RADIUS_M, pd.CIRCLE_RADIUS_M
        sagitta = pd.CIRCLE_RADIUS_M * (1.0 - math.cos(math.pi / pd.CIRCLE_VERTICES))
        center = pd.CENTER
        for k in range(3):
            for kind in ("foot", "crest"):
                item = of_kind(found, kind, k)[0]
                level = pd.FLOOR_Z_M + 20.0 * (k + (1 if kind == "crest" else 0))
                self.assertTrue(np.all(np.abs(item.vertices[:, 2] - level) <= 1e-9))
                if kind == "crest":
                    west, east = west + west_run, east + east_run
                xy = pr.local_ring(item, pd.GRID)
                at_west = xy[np.argmin(np.abs(xy[:, 1] - center[1]) + (xy[:, 0] > center[0]) * 1e6)]
                at_east = xy[np.argmin(np.abs(xy[:, 1] - center[1]) + (xy[:, 0] < center[0]) * 1e6)]
                tol = (2 * k + 3) * ARC_M + sagitta + 1e-3
                self.assertAlmostEqual(center[0] - at_west[0], west, delta=tol)
                self.assertAlmostEqual(at_east[0] - center[0], east, delta=tol)
                if kind == "crest":
                    west, east = west + 6.0, east + 6.0
        REPORT.append("E3 roseta con n = 2: avance 11,547 + 6 m (60°, azimut 90°) y 20 + 6 m (45°, azimut 270°) por banco doble, 3 bancos, "
                      "cotas z0 + 20·k, fiable")


class RobustnessTest(unittest.TestCase):
    """S-1: el criterio de robustez del desfase (T09) y una muestra de cortas rugosas por los bancos."""

    SAMPLE = 40

    def test_offset_battery_is_in_the_milestone_step(self) -> None:
        """La batería de 300 + 60 casos de la T09 sigue en ``milestone_offset_robustness`` con su criterio; corre en este mismo paso «hito»."""
        from tests.unit.gis import milestone_offset_robustness as battery
        classes = [value for value in vars(battery).values() if isinstance(value, type) and issubclass(value, unittest.TestCase)]
        self.assertTrue(any(hasattr(item, "test_rose_cases_are_not_rejected") for item in classes))
        self.assertIn("S-1", battery.__doc__ or "")
        self.assertEqual(pd.ROUGH_CASES, 300)

    def test_rough_pits_through_the_benches(self) -> None:
        """Las primeras 40 cortas rugosas de ``pit_data`` (300 a 1.500 vértices; ascendentes y descendentes, con y sin roseta) por el
        motor de bancos: sin rechazo, fiables, y ninguna polilínea se corta a sí misma."""
        rose = tuple(pit_rose.RoseRange(r.from_deg, r.to_deg, r.face_deg, r.berm_m) for r in pd.ROSE_TWO_RANGES)
        params = pit_model.PitParams(arc_tol_m=pd.HYPOTHESES.arc_m, simplify_m=pd.HYPOTHESES.simplify_m,
                                     min_floor_width_m=pd.MIN_FLOOR_WIDTH_M, az_window_m=pd.HYPOTHESES.az_window_m)
        rejected: list[str] = []
        unreliable: list[str] = []
        crossings = 0
        benches = 0
        for case in pd.rough_cases(self.SAMPLE):
            source = pit_model.PitSource("rugosa", pd.absolute(case.ring), None if case.descending else pd.FLOOR_Z_M)
            try:
                if case.descending:
                    found = pit_bench.descend(down_job(sources=(source,), params=params, rose=rose if case.with_rose else None))
                else:
                    found = pit_bench.ascend(up_job(sources=(source,), params=params, rose=rose if case.with_rose else None))
            except messages.DesignError as error:
                rejected.append(f"{case.index}: {error.code}")
                continue
            benches += found.count
            if not found.reliable:
                unreliable.append(str(case.index))
            for item in found.polylines:
                crossings += oracle.crossing_count([pr.local_ring(item, pd.GRID)])
        REPORT.append(f"Robustez: {self.SAMPLE} cortas rugosas por los bancos, {benches} bancos, {len(rejected)} rechazos "
                      f"({rejected}), {len(unreliable)} no fiables ({unreliable}), {crossings} cruces")
        self.assertEqual(rejected, [])
        self.assertEqual(unreliable, [])
        self.assertEqual(crossings, 0)


if __name__ == "__main__":
    unittest.main()
