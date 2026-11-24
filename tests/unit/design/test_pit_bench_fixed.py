# SPDX-License-Identifier: GPL-3.0-or-later
"""Bancos dobles, bancos fijados y «un paso» de la corta por bancos (spec 018, T12; HU-018-1, HU-018-2; RF-018-08, 22, 23, 24 y 25; CE-018-09;
plan 018 §5.4 A5 a A7 y §5.7 P-12 y P-15).

El círculo con n = 1 y n = 2 (avance entre bermas ``n·h/tan α + B``), el banco 2 fijado con los de arriba y los de abajo completados (CE-018-09,
sin la capa), el fijado de una descendente, los rechazos de RF-018-24 (dos fijados que se cortan, cota que no es la del banco, un fijado que corta
o cae dentro del banco que lo contiene, uno que no se usa), «un paso» igual al del bucle y el mismo resultado bit a bit. Sin proyecto ni Blender."""

from __future__ import annotations

import dataclasses
import math
import unittest

import numpy as np

from tests.support import pit_data as pd
from tests.support.package import import_geoblender

pit_bench = import_geoblender("design.pit_bench")
pit_model = import_geoblender("design.pit_model")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")

ARC_M = pd.HYPOTHESES.arc_hand_m
FACE_M = 10.0 / math.tan(math.radians(60.0))
DOUBLE_M = 20.0 / math.tan(math.radians(60.0))
"""n·h/tan α con n = 2: 11,547 m."""


def profile(base: object = pd.EXPL, **changes: object) -> object:
    return model.BenchProfile(**{**dataclasses.asdict(base), **changes})


def request(mode: str = "up", **changes: object) -> object:
    values: dict[str, object] = {"name": "Corta 1", "mode": mode, "start": "terreno",
                                 "fields": pit_model.LayerFields(layer="gis_fea_fondos", name_field="nombre")}
    if mode == "up":
        values["level_field"] = "cota_m"
    values.update(changes)
    return pit_model.PitRequest(**values)


def params(**changes: object) -> object:
    values: dict[str, object] = {"arc_tol_m": ARC_M, "simplify_m": 1e-6}
    values.update(changes)
    return pit_model.PitParams(**values)


def job(**changes: object) -> object:
    values: dict[str, object] = {
        "request": request(), "code": "PIT-001", "grid": pd.GRID, "start": pd.flat_terrain(pd.GRID),
        "cut_allowed": np.ones(pd.GRID.shape, bool), "fill_allowed": np.zeros(pd.GRID.shape, bool),
        "untouchable": np.zeros(pd.GRID.shape, bool),
        "sources": (pit_model.PitSource("fondo", pd.absolute(pd.circle_ring()), pd.FLOOR_Z_M),),
        "params": params(), "profile": profile(),
    }
    values.update(changes)
    return pit_model.PitJob(**values)


def down_job(**changes: object) -> object:
    values: dict[str, object] = {
        "request": request("down", fields=pit_model.LayerFields(layer="gis_fea_limites", name_field="nombre")),
        "start": pd.limit_terrain(pd.GRID), "profile": profile(pd.DESD),
        "sources": (pit_model.PitSource("limite", pd.absolute(pd.square_ring(pd.LIMIT_SIDE_M)), None),),
        "params": params(min_floor_width_m=pd.MIN_FLOOR_WIDTH_M)}
    values.update(changes)
    return job(**values)


def local(polyline: object) -> np.ndarray:
    return polyline.vertices[:, :2] - np.asarray(pd.origin_of(pd.GRID))


def radii(polyline: object) -> np.ndarray:
    xy = local(polyline)
    return np.hypot(xy[:, 0] - pd.CENTER[0], xy[:, 1] - pd.CENTER[1])


def of_kind(found: object, kind: str, bench: int | None = None) -> list[object]:
    return [item for item in found.polylines if item.kind == kind and (bench is None or item.bench == bench)]


def circle_xyz(radius: float, z: float, center: tuple[float, float] = pd.CENTER) -> np.ndarray:
    xy = pd.absolute(pd.circle_ring(radius, center=center))
    return np.column_stack([xy, np.full(len(xy), z)])


def square_xyz(half: float, z: float) -> np.ndarray:
    xy = np.array([[pd.CENTER[0] + sx * half, pd.CENTER[1] + sy * half] for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
    return np.column_stack([pd.absolute(xy), np.full(4, z)])


def fixed(name: str, vertices: np.ndarray, **kwargs: object) -> object:
    return pit_model.FixedBench(name, vertices, closed=True, **kwargs)


class DoubleBenchTest(unittest.TestCase):
    """RF-018-08: con n = 2 la berma solo se deja cada dos bancos y la cara entre bermas es la de 2·h."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.one = pit_bench.ascend(job())
        cls.two = pit_bench.ascend(job(params=params(n_berm=2)))

    def test_n_one_is_the_default(self) -> None:
        """Con n = 1 explícito sale lo mismo que sin pedirlo, bit a bit."""
        again = pit_bench.ascend(job(params=params(n_berm=1)))
        for one, other in zip(again.polylines, self.one.polylines, strict=True):
            self.assertTrue(np.array_equal(one.vertices, other.vertices))

    def test_levels_and_count(self) -> None:
        """Los pies a 125, 145 y 165 m, las crestas a 145, 165 y 185 m (3 bancos dobles) y el pie a 185 m sale a superficie (175 m)."""
        self.assertEqual(self.two.count, 3)
        self.assertEqual(self.two.stop, pit_model.StopCriterion.SURFACE)
        for k in range(3):
            self.assertAlmostEqual(of_kind(self.two, "foot", k)[0].z_m, 125.0 + 20.0 * k, delta=1e-9)
            self.assertAlmostEqual(of_kind(self.two, "crest", k)[0].z_m, 145.0 + 20.0 * k, delta=1e-9)

    def test_advance_between_berms(self) -> None:
        """RF-018-08: el avance entre bermas es n·h/tan α + B = 17,547 m: cresta = pie + 11,547 m y pie siguiente = cresta + 6 m."""
        sagitta = pd.CIRCLE_RADIUS_M * (1.0 - math.cos(math.pi / pd.CIRCLE_VERTICES))
        foot = pd.CIRCLE_RADIUS_M
        for k in range(3):
            crest = foot + DOUBLE_M
            for item, expected, steps in ((of_kind(self.two, "foot", k)[0], foot, 2 * k), (of_kind(self.two, "crest", k)[0], crest, 2 * k + 1)):
                with self.subTest(kind=item.kind, bench=k):
                    self.assertGreaterEqual(float(radii(item).min()), expected - sagitta - 1e-9)
                    self.assertLessEqual(float(radii(item).max()), expected + steps * ARC_M + sagitta + 1e-9)
            foot = crest + 6.0

    def test_sectors_with_different_n_are_not_supported_yet(self) -> None:
        """Dos sectores con distinto n no se admiten todavía (un error del programa, no se ignora)."""
        sector = pit_model.PitSector("S1", "Sector 1", ((pd.absolute(pd.circle_ring(10.0)),),), n_berm=3)
        with self.assertRaises(ValueError):
            pit_bench.ascend(job(sectors=(sector,)))


class FixedBenchTest(unittest.TestCase):
    """RF-018-23, CE-018-09: el banco 2 fijado y los de arriba y de abajo completados con el motor, sin la capa."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.base = pit_bench.ascend(job())

    def test_the_computed_line_fixed_gives_the_same_result(self) -> None:
        """Con el pie del banco 2 calculado como banco fijado sale lo mismo; la línea es la del usuario, tal cual."""
        foot = of_kind(self.base, "foot", 2)[0]
        found = pit_bench.ascend(job(fixed=(fixed("b2", foot.vertices, bench=2),)))
        self.assertEqual(len(found.polylines), len(self.base.polylines))
        for one, other in zip(found.polylines, self.base.polylines, strict=True):
            self.assertEqual((one.kind, one.bench), (other.kind, other.bench))
            np.testing.assert_allclose(one.vertices, other.vertices, atol=1e-7, rtol=0)
        mine = of_kind(found, "foot", 2)[0]
        self.assertTrue(mine.fixed)
        self.assertTrue(np.array_equal(mine.vertices, foot.vertices))
        self.assertFalse(any(item.fixed for item in found.polylines if item is not mine))

    def test_a_different_fixed_foot_moves_the_benches_above_only(self) -> None:
        """Un pie fijado de 80 m de radio en el banco 2 (el calculado, 73,5 m): el 2 es el suyo, los de arriba parten de él (cresta 85,8 m) y los
        de abajo son los de antes; el array de entrada no cambia."""
        xyz = circle_xyz(80.0, 145.0)
        keep = xyz.copy()
        found = pit_bench.ascend(job(fixed=(fixed("b2", xyz, level_m=145.0),)))
        self.assertTrue(np.array_equal(xyz, keep))
        for item, other in zip(found.polylines[:4], self.base.polylines[:4], strict=True):
            np.testing.assert_allclose(item.vertices, other.vertices, atol=1e-7, rtol=0)
        foot = of_kind(found, "foot", 2)[0]
        self.assertTrue(np.array_equal(foot.vertices, xyz))
        self.assertAlmostEqual(float(radii(of_kind(found, "crest", 2)[0]).mean()), 80.0 + FACE_M, delta=0.01)
        self.assertEqual(found.count, 5)

    def test_a_fixed_foot_below_the_floor_starts_the_pit(self) -> None:
        """Un fijado en un banco por debajo del fondo (el banco -1, a 115 m) es el principio de la corta: de él salen los de arriba."""
        found = pit_bench.ascend(job(fixed=(fixed("b-1", circle_xyz(30.0, 115.0), bench=-1),)))
        self.assertEqual(found.polylines[0].bench, -1)
        self.assertTrue(found.polylines[0].fixed)

    def test_level_must_be_the_one_of_the_bench(self) -> None:
        """RF-018-23: la cota de la línea fijada debe ser la de su banco (≤ 10⁻⁹ m) o se rechaza con el banco y las dos cotas."""
        with self.assertRaises(messages.DesignError) as caught:
            pit_bench.ascend(job(fixed=(fixed("b2", circle_xyz(80.0, 150.0), bench=2),)))
        self.assertEqual(caught.exception.code, "des.pit_fixed_level")
        self.assertIn("150", str(caught.exception))
        self.assertIn("145", str(caught.exception))
        with self.assertRaises(messages.DesignError) as caught:
            pit_bench.ascend(job(fixed=(fixed("b2", circle_xyz(80.0, 145.0), bench=2, level_m=146.0),)))
        self.assertEqual(caught.exception.code, "des.pit_fixed_level")
        with self.assertRaises(messages.DesignError) as caught:
            pit_bench.ascend(job(fixed=(fixed("x", circle_xyz(80.0, 147.0), level_m=147.0),)))
        self.assertEqual(caught.exception.code, "des.pit_fixed_level")

    def test_two_fixed_benches_that_cross_are_rejected(self) -> None:
        """RF-018-24: dos bancos fijados que se cortan: se rechaza nombrando los bancos y el lugar; no se mueve ninguno."""
        a = circle_xyz(80.0, 145.0)
        b = circle_xyz(80.0, 155.0, center=(pd.CENTER[0] + 40.0, pd.CENTER[1]))
        with self.assertRaises(messages.DesignError) as caught:
            pit_bench.ascend(job(fixed=(fixed("a", a, bench=2), fixed("b", b, bench=3))))
        self.assertEqual(caught.exception.code, "des.pit_fixed_cross")
        self.assertIn("2", str(caught.exception))
        self.assertIn("3", str(caught.exception))

    def test_a_fixed_bench_that_cuts_or_falls_inside_the_previous_crest(self) -> None:
        """RF-018-24: un fijado que corta la cresta del banco anterior (67,5 m de radio) o cae dentro de ella se rechaza."""
        for line in (circle_xyz(60.0, 145.0), circle_xyz(80.0, 145.0, center=(pd.CENTER[0] + 20.0, pd.CENTER[1]))):
            with self.subTest(first=line[0]):
                with self.assertRaises(messages.DesignError) as caught:
                    pit_bench.ascend(job(fixed=(fixed("b2", line, bench=2),)))
                self.assertEqual(caught.exception.code, "des.pit_fixed_cross")

    def test_a_fixed_bench_that_coincides_with_the_crest_below_is_rejected_with_bench_and_place(self) -> None:
        """T40b, RF-018-24, RF-018-23, RF-018-22: el banco fijado que es la expansión de la propia corta (la cresta del banco anterior, tal cual o a 1e-13 a
        1e-10 m, como sale de una capa guardada) no deja sitio: se rechaza con el banco, el otro banco, el lugar y qué hacer, no con un error del triangulador
        al calcular la superficie. Con la roseta de dos rangos (E3) y sin ella; uno apartado 0,3 m sigue rechazado y uno a la berma, admitido."""
        pit_rose = import_geoblender("design.pit_rose")
        rose = tuple(pit_rose.RoseRange(r.from_deg, r.to_deg, r.face_deg, r.berm_m) for r in pd.ROSE_TWO_RANGES)
        for with_rose in (False, True):
            changes = {"params": params(n_berm=2), **({"rose": rose} if with_rose else {})}
            crest = of_kind(pit_bench.ascend(job(**changes)), "crest", 1)[0]
            for eps in (0.0, 1e-13, 1e-10, 1e-7, 0.3):
                with self.subTest(rose=with_rose, noise_m=eps):
                    vertices = crest.vertices.copy()
                    if eps:
                        vertices[:, :2] += np.random.default_rng(3).normal(0.0, eps, (len(vertices), 2))
                    with self.assertRaises(messages.DesignError) as caught:
                        pit_bench.ascend(job(fixed=(fixed("b2", vertices, bench=2),), **changes))
                    self.assertEqual(caught.exception.code, "des.pit_fixed_cross")
                    text = str(caught.exception)
                    self.assertIn("2", text)
                    self.assertIn("1", text)
                    # H3-7 (T40e): las coordenadas con el formato de las demás cifras (coma decimal en español, punto en inglés), no «700185.7, 4400290.0» en los dos
                    self.assertRegex(text, r"x = \d{6}(,\d)?, y = \d{7}(,\d)? ")
                    self.assertNotRegex(text, r"\d\.\d")
                    self.assertRegex(caught.exception.text_in("en"), r"x = \d{6}(\.\d)?, y = \d{7}(\.\d)? ")
                    self.assertIn("berma", text)

    def test_a_fixed_bench_that_is_never_reached_is_rejected(self) -> None:
        """Un fijado en un banco que la corta no alcanza (el 9, a 215 m, sobre el terreno) se rechaza, no se ignora."""
        with self.assertRaises(messages.DesignError) as caught:
            pit_bench.ascend(job(fixed=(fixed("b9", circle_xyz(200.0, 215.0), bench=9),)))
        self.assertEqual(caught.exception.code, "des.pit_fixed_cross")

    def test_fixed_with_a_double_bench(self) -> None:
        """Con n = 2 el banco 1 (a 145 m) fijado: la cresta de arriba, a 11,547 m."""
        found = pit_bench.ascend(job(params=params(n_berm=2), fixed=(fixed("b1", circle_xyz(80.0, 145.0), bench=1),)))
        self.assertAlmostEqual(float(radii(of_kind(found, "crest", 1)[0]).mean()), 80.0 + DOUBLE_M, delta=0.01)

    def test_open_line_is_not_a_bench(self) -> None:
        """Una línea abierta no vale como banco (cierra la preparación): un error del programa."""
        line = pit_model.FixedBench("a", circle_xyz(80.0, 145.0), bench=2, closed=False)
        with self.assertRaises(ValueError):
            pit_bench.ascend(job(fixed=(line,)))


class FixedDescentTest(unittest.TestCase):
    """RF-018-23 en la descendente: la línea fijada es la cresta de su banco; el límite arriba y el motor abajo."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.base = pit_bench.descend(down_job())

    def test_the_computed_crest_fixed_gives_the_same_result(self) -> None:
        crest = of_kind(self.base, "crest", 2)[0]
        found = pit_bench.descend(down_job(fixed=(fixed("c2", crest.vertices, bench=2),)))
        self.assertEqual(len(found.polylines), len(self.base.polylines))
        for one, other in zip(found.polylines, self.base.polylines, strict=True):
            np.testing.assert_allclose(one.vertices, other.vertices, atol=1e-7, rtol=0)
        self.assertTrue(of_kind(found, "crest", 2)[0].fixed)

    def test_a_wider_fixed_crest_moves_the_benches_below(self) -> None:
        """La cresta 2 fijada de 140 m de lado (la calculada, 136 m): el pie 2 sale de ella (120 m) y la cresta 3, a 108 m."""
        z = of_kind(self.base, "crest", 2)[0].z_m
        found = pit_bench.descend(down_job(fixed=(fixed("c2", square_xyz(70.0, z), level_m=z),)))

        def side(item: object) -> float:
            return float(np.ptp(local(item)[:, 0]))

        self.assertAlmostEqual(side(of_kind(found, "crest", 2)[0]), 140.0, delta=1e-6)
        self.assertAlmostEqual(side(of_kind(found, "foot", 2)[0]), 120.0, delta=1e-6)
        self.assertAlmostEqual(side(of_kind(found, "crest", 3)[0]), 108.0, delta=1e-6)

    def test_a_fixed_crest_crossing_the_foot_above_is_rejected(self) -> None:
        """Una cresta fijada de 180 m de lado cae fuera del pie del banco 1 (148 m), que la contiene: se rechaza."""
        z = of_kind(self.base, "crest", 2)[0].z_m
        with self.assertRaises(messages.DesignError) as caught:
            pit_bench.descend(down_job(fixed=(fixed("c2", square_xyz(90.0, z), bench=2),)))
        self.assertEqual(caught.exception.code, "des.pit_fixed_cross")

    def test_a_fixed_crest_that_leaves_no_room_is_rejected(self) -> None:
        """RF-018-24: una cresta fijada de 40 m de lado deja un pie de 20 m, menor que el ancho mínimo: se rechaza."""
        z = of_kind(self.base, "crest", 2)[0].z_m
        with self.assertRaises(messages.DesignError) as caught:
            pit_bench.descend(down_job(fixed=(fixed("c2", square_xyz(20.0, z), bench=2),)))
        self.assertEqual(caught.exception.code, "des.pit_fixed_cross")


class ExpandOneTest(unittest.TestCase):
    """RF-018-22 (A7): un paso sobre la polilínea dada da la misma polilínea que el bucle, sin escribir."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.up = pit_bench.ascend(job())
        cls.down = pit_bench.descend(down_job())

    def test_up_steps_equal_the_loop(self) -> None:
        """Hacia arriba: del pie k sale la cresta k y de la cresta k, el pie k + 1 (la berma)."""
        for k in range(3):
            foot, crest, nxt = (of_kind(self.up, "foot", k)[0], of_kind(self.up, "crest", k)[0], of_kind(self.up, "foot", k + 1)[0])
            for source, target in ((foot, crest), (crest, nxt)):
                with self.subTest(kind=source.kind, bench=k):
                    found = pit_bench.expand_one(job(), source, "up")
                    self.assertEqual(len(found.polylines), 1)
                    one = found.polylines[0]
                    self.assertEqual((one.kind, one.bench), (target.kind, target.bench))
                    self.assertEqual(found.level_m, target.z_m)
                    np.testing.assert_allclose(one.vertices, target.vertices, atol=1e-7, rtol=0)
                    self.assertTrue(found.reliable)

    def test_down_steps_equal_the_loop(self) -> None:
        """Hacia abajo: de la cresta k sale el pie k y del pie k, la cresta k + 1."""
        for k in (1, 2):
            crest, foot, nxt = (of_kind(self.down, "crest", k)[0], of_kind(self.down, "foot", k)[0], of_kind(self.down, "crest", k + 1)[0])
            for source, target in ((crest, foot), (foot, nxt)):
                with self.subTest(kind=source.kind, bench=k):
                    found = pit_bench.expand_one(down_job(), source, "down")
                    self.assertEqual(len(found.polylines), 1)
                    np.testing.assert_allclose(found.polylines[0].vertices, target.vertices, atol=1e-6, rtol=0)
                    self.assertAlmostEqual(found.level_m, target.z_m, delta=1e-9)

    def test_checks_of_slope_and_berm(self) -> None:
        """La comprobación: la inclinación real de la cara (≤ 60° y no menos de 59,9°) y la berma real (≥ 6 m)."""
        found = pit_bench.expand_one(job(), of_kind(self.up, "foot", 0)[0], "up")
        self.assertEqual(found.slope_limit_deg, 60.0)
        self.assertLessEqual(found.slope_deg, 60.0 + 1e-6)
        self.assertGreater(found.slope_deg, 59.9)
        self.assertTrue(found.slope_ok)
        self.assertIsNone(found.berm_min_m)
        found = pit_bench.expand_one(job(), of_kind(self.up, "crest", 0)[0], "up")
        self.assertEqual(found.berm_limit_m, 6.0)
        self.assertGreaterEqual(found.berm_min_m, 6.0 - 1e-9)
        self.assertTrue(found.berm_ok)
        self.assertIsNone(found.slope_deg)

    def test_a_polyline_that_is_not_a_bench_is_a_program_error(self) -> None:
        open_line = pit_model.Polyline("foot", 0, circle_xyz(50.0, 125.0), closed=False)
        with self.assertRaises(ValueError):
            pit_bench.expand_one(job(), open_line, "up")

    def test_steps_end_with_the_result(self) -> None:
        steps = list(pit_bench.expand_one_steps(job(), of_kind(self.up, "foot", 0)[0], "up", budget_s=0.05))
        self.assertTrue(all(step.result is None for step in steps[:-1]))
        self.assertEqual(len(steps[-1].result.polylines), 1)


class DeterminismTest(unittest.TestCase):
    def test_same_inputs_same_bits(self) -> None:
        """RF-018-25: mismas entradas, mismo resultado bit a bit y mismo orden (con n = 2 y un fijado)."""

        def build() -> object:
            return pit_bench.ascend(job(params=params(n_berm=2), fixed=(fixed("b1", circle_xyz(80.0, 145.0), bench=1),)))

        one, other = build(), build()
        self.assertEqual([(p.kind, p.bench, p.part, p.fixed) for p in one.polylines], [(p.kind, p.bench, p.part, p.fixed) for p in other.polylines])
        for a, b in zip(one.polylines, other.polylines, strict=True):
            self.assertTrue(np.array_equal(a.vertices, b.vertices))


if __name__ == "__main__":
    unittest.main()
