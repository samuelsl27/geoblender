# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos de la corta por bancos (spec 018, T05; RF-018-01, RF-018-02, RF-018-04, RF-018-25; plan 018 §5.1, §5.3.1):
``PitRequest``, ``PitParams``, ``PitJob`` (de ``pit_data``, sin proyecto), ``PitOutcome``, ``Polyline``, ``RampPath``,
``Finding`` y los códigos de error ``PitCode``."""

from __future__ import annotations

import dataclasses
import unittest

import numpy as np

from tests.support import pit_data as pd
from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR
from tests.unit.architecture import test_lazy_registration

pit_model = import_geoblender("design.pit_model")
pit_rose = import_geoblender("design.pit_rose")
pit_ramp_def = import_geoblender("design.pit_ramp_def")
messages = import_geoblender("design.messages")
params = import_geoblender("design.params")
model = import_geoblender("design.model")

CODE = "PIT-001"


def bench_profile(**changes: object) -> object:
    """El perfil EXPL de ``pit_data`` como ``BenchProfile`` de la 013 (con los cambios pedidos)."""
    return model.BenchProfile(**{**dataclasses.asdict(pd.EXPL), **changes})


def request(**changes: object) -> object:
    values: dict[str, object] = {"name": "Corta 1", "fields": pit_model.LayerFields(layer="gis_fea_fondos", name_field="nombre"),
                                 "mode": "up", "start": "terreno", "level_field": "cota_m"}
    values.update(changes)
    return pit_model.PitRequest(**values)


def pit_params(**changes: object) -> object:
    values: dict[str, object] = {"arc_tol_m": pd.HYPOTHESES.arc_m, "simplify_m": pd.HYPOTHESES.simplify_m}
    values.update(changes)
    return pit_model.PitParams(**values)


def source(level: float | None = pd.FLOOR_Z_M) -> object:
    return pit_model.PitSource("fondo", pd.absolute(pd.circle_ring()), level)


def job(**changes: object) -> object:
    """Un ``PitJob`` de ``pit_data`` (el fondo circular de 50 m, el terreno llano, el perfil EXPL) sin proyecto."""
    grid = pd.GRID
    shape = grid.shape
    values: dict[str, object] = {
        "request": request(), "code": CODE, "grid": grid, "start": pd.flat_terrain(grid),
        "cut_allowed": np.ones(shape, bool), "fill_allowed": np.zeros(shape, bool), "untouchable": np.zeros(shape, bool),
        "sources": (source(),), "params": pit_params(), "profile": bench_profile(),
    }
    values.update(changes)
    return pit_model.PitJob(**values)


class EnumsAndCodesTest(unittest.TestCase):
    def test_modes(self) -> None:
        """RF-018-02: dos modos, texto de ``PitParam.MODE``."""
        self.assertEqual([item.value for item in pit_model.PitMode], ["up", "down"])
        self.assertEqual({item.value for item in pit_model.PitMode}, set(params.PIT_ENTITY.template("mode").choices))
        with self.assertRaises(ValueError):
            pit_model.PitMode("sideways")

    def test_error_codes_are_catalog_messages(self) -> None:
        """RF-018-04, 06, 13, 14, 23, 24: cada código de error es un mensaje de ``design.messages`` con texto en español y en inglés."""
        self.assertEqual(len(pit_model.PitCode), 15)
        for item in pit_model.PitCode:
            with self.subTest(code=item.value):
                self.assertIn(item.value, messages.MESSAGES)
                self.assertTrue(messages.render(item.value, language="es"))
                self.assertTrue(messages.render(item.value, language="en"))
        with self.assertRaises(ValueError):
            pit_model.PitCode("des.pit_nothing")

    def test_finding_kinds_have_units(self) -> None:
        """RF-018-26: todo tipo de hallazgo tiene su unidad."""
        self.assertEqual(set(pit_model.FINDING_UNITS), set(pit_model.FindingKind))


class RequestTest(unittest.TestCase):
    def test_immutable_and_normalised(self) -> None:
        """RF-018-01: la petición es inmutable, sin ``protect`` ni ``guard_m``, y lo no pedido es ``None``."""
        found = request(name=" Corta 1 ", sector_profiles={"b": "x", "a": "y"}, ramps=("rampa1",), corner="miter")
        self.assertEqual(found.name, "Corta 1")
        self.assertEqual(found.sector_profiles, (("a", "y"), ("b", "x")))
        self.assertEqual(found.layer, "gis_fea_fondos")
        self.assertIs(found.corner, pit_model.Corner.MITER)
        self.assertIsNone(found.top_level_m)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            found.name = "otra"  # type: ignore[misc]
        names = {item.name for item in dataclasses.fields(found)}
        self.assertFalse({"protect", "guard_m", "supports", "discarded"} & names)

    def test_rejections_are_program_errors(self) -> None:
        """RF-018-04: tipos y formas erróneos."""
        with self.assertRaises(TypeError):
            request(fields="capa")
        with self.assertRaises(ValueError):
            request(mode="x")
        with self.assertRaises(TypeError):
            request(max_benches=2.5)
        with self.assertRaises(ValueError):
            request(n_berm=0)
        with self.assertRaises(TypeError):
            request(top_level_m="alto")
        with self.assertRaises(TypeError):
            request(ramps="rampa1")
        with self.assertRaises(Exception):
            request(name="  ")


class ParamsTest(unittest.TestCase):
    def test_ranges_from_params(self) -> None:
        """RF-018-04, 08: los rangos son los de ``PIT_RANGES`` y no hay valor por defecto de las tolerancias ni de los criterios de parada."""
        found = pit_params(n_berm=2, max_benches=7, top_level_m=175.0, bottom_level_m=125.0)
        self.assertEqual((found.n_berm, found.max_benches, found.corner), (2, 7, pit_model.Corner.ROUND))
        for bad in ({"n_berm": 0}, {"arc_tol_m": 0.0}, {"simplify_m": -1.0}, {"max_benches": 0}, {"az_window_m": 0.0},
                    {"close_radius_m": -0.1}, {"top_level_m": 100.0, "bottom_level_m": 100.0}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                pit_params(**bad)
        with self.assertRaises(TypeError):
            pit_params(n_berm=1.5)
        with self.assertRaises(TypeError):
            pit_model.PitParams()  # type: ignore[call-arg]
        self.assertEqual(pit_params(close_radius_m=0.0).close_radius_m, 0.0)

    def test_from_values(self) -> None:
        """RF-015-08: sin las tolerancias no se elige ninguna por la persona."""
        found = pit_model.PitParams.from_values({"arc_tol_m": 0.05, "simplify_m": 0.1, "name": "x", "n_berm": 2})
        self.assertEqual((found.arc_tol_m, found.simplify_m, found.n_berm), (0.05, 0.1, 2))
        with self.assertRaises(ValueError):
            pit_model.PitParams.from_values({"arc_tol_m": 0.05})


class JobTest(unittest.TestCase):
    def test_build_from_pit_data_without_project(self) -> None:
        """RF-018-01, 02: un ``PitJob`` de ``pit_data`` se construye sin proyecto, con los arrays de solo lectura."""
        found = job()
        self.assertIs(found.mode, pit_model.PitMode.UP)
        self.assertEqual((found.height_m, found.anchor_m), (10.0, pd.FLOOR_Z_M))
        self.assertEqual(found.start.shape, pd.GRID.shape)
        for attr in ("start", "cut_allowed", "fill_allowed", "untouchable"):
            self.assertFalse(getattr(found, attr).flags.writeable, attr)
        self.assertEqual(found.sources[0].ring.shape, (pd.CIRCLE_VERTICES, 2))
        self.assertFalse(found.sources[0].ring.flags.writeable)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            found.code = "PIT-002"  # type: ignore[misc]

    def test_does_not_modify_the_inputs(self) -> None:
        """RF-018-01: el trabajo no cambia el array de quien lo entrega."""
        terrain = pd.flat_terrain()
        job(start=terrain)
        self.assertTrue(terrain.flags.writeable)

    def test_down_mode_and_sectors_roses_ramps(self) -> None:
        """RF-018-02, 06, 07, 15: descendente con cota opcional, sector con perfil propio de la misma altura y ancla, roseta y rampa."""
        rose = tuple(pit_rose.RoseRange(item.from_deg, item.to_deg, item.face_deg, item.berm_m) for item in pd.ROSE_TWO_RANGES)
        ring = pd.absolute(pd.square_ring(100.0))
        sector = pit_model.PitSector("s1", "Sector 1", (((ring),),), profile=bench_profile(code="otro", name="OTRO"), n_berm=2)
        found = job(request=request(mode="down"), sources=(source(None),), sectors=(sector,), rose=rose, profile=None,
                    fixed=(pit_model.FixedBench("b1", [[0, 0, 125.0], [1, 0, 125.0]], level_m=125.0),))
        self.assertIs(found.mode, pit_model.PitMode.DOWN)
        self.assertEqual(len(found.bench_profiles), 1)
        self.assertEqual(found.sectors[0].n_berm, 2)
        self.assertEqual(found.rose, rose)

    def test_wrong_jobs_are_program_errors(self) -> None:
        """RF-018-02, 04, 06: lo que la preparación ya rechazó llega aquí como error del programa."""
        shape = pd.GRID.shape
        with self.assertRaises(TypeError):
            job(request="x")
        with self.assertRaises(ValueError):
            job(code="RDW-001")
        with self.assertRaises(ValueError):
            job(start=np.zeros((2, 2)))
        with self.assertRaises(ValueError):
            job(cut_allowed=np.ones((shape[0], shape[1] + 1), bool))
        with self.assertRaises(ValueError):
            job(sources=())
        with self.assertRaises(ValueError):
            job(sources=(source(None),))  # el fondo ascendente lleva su cota
        with self.assertRaises(ValueError):
            job(profile=None)  # ningún perfil
        with self.assertRaises(ValueError):
            job(sources=(source(), source()))  # nombre repetido
        sector = pit_model.PitSector("s1", "S", ((pd.absolute(pd.square_ring(10.0)),),), profile=bench_profile(code="alto", name="ALTO", height_m=12.0))
        with self.assertRaises(ValueError) as caught:
            job(sectors=(sector,))
        self.assertIn(pit_model.PitCode.PROFILES_DIFFER.value, str(caught.exception))

    def test_source_and_fixed_validation(self) -> None:
        """RF-018-04, 23: anillos y líneas válidos; un banco fijado lleva su banco o su cota."""
        with self.assertRaises(ValueError):
            pit_model.PitSource("a", [[0, 0], [1, 1]])
        with self.assertRaises(ValueError):
            pit_model.PitSource("a", [[0, 0], [1, 1], [float("nan"), 0]])
        with self.assertRaises(ValueError):
            pit_model.FixedBench("b", [[0, 0, 1.0], [1, 0, 1.0]])
        with self.assertRaises(ValueError):
            pit_model.FixedBench("b", [[0, 0], [1, 0]], bench=1)
        self.assertEqual(pit_model.FixedBench("b", [[0, 0, 1.0], [1, 0, 1.0]], bench=2).bench, 2)


class OutcomeTest(unittest.TestCase):
    def outcome(self, **changes: object) -> object:
        values: dict[str, object] = {"name": "Corta 1", "code": CODE, "mode": "up", "window": (slice(0, 3), slice(2, 6)),
                                     "surface": np.zeros((3, 4)), "footprint": np.ones((3, 4), bool)}
        values.update(changes)
        return pit_model.PitOutcome(**values)

    def test_outcome_and_compose(self) -> None:
        """RF-018-01: el resultado conserva la forma de su ventana y compone la superficie entera sin tocar la de partida."""
        found = self.outcome(stop="surface")
        self.assertIs(found.stop, pit_model.StopCriterion.SURFACE)
        start = np.full((5, 8), 7.0)
        whole = found.compose(start)
        self.assertEqual(float(whole[0, 2]), 0.0)
        self.assertEqual(float(whole[4, 0]), 7.0)
        self.assertEqual(float(start.min()), 7.0)
        self.assertEqual(found.message, "Corta «Corta 1» (PIT-001) calculada")
        with self.assertRaises(ValueError):
            found.compose(np.zeros((2, 2)))
        with self.assertRaises(ValueError):
            self.outcome(surface=np.zeros((2, 2)))
        with self.assertRaises(ValueError):
            self.outcome(code="RDW-001")

    def test_polylines_keep_order_and_are_readonly(self) -> None:
        """RF-018-25: el orden de las polilíneas y de sus vértices es el registrado; las polilíneas son de solo lectura."""
        ring = np.array([[0.0, 0.0, 125.0], [10.0, 0.0, 125.0], [10.0, 10.0, 125.0], [0.0, 10.0, 125.0]])
        lines = (pit_model.Polyline("foot", 1, ring), pit_model.Polyline("crest", 1, ring + [0, 0, 10], zone="ZR", sector="s1", part=1))
        found = self.outcome(polylines=lines)
        self.assertEqual([item.kind.value for item in found.polylines], ["foot", "crest"])
        self.assertEqual(found.polylines[0].length_m, 40.0)
        self.assertEqual(found.polylines[1].z_m, 135.0)
        self.assertFalse(found.polylines[0].vertices.flags.writeable)
        with self.assertRaises(ValueError):
            pit_model.Polyline("foot", 1, ring[:2])
        with self.assertRaises(ValueError):
            pit_model.Polyline("wall", 1, ring)
        with self.assertRaises(ValueError):
            pit_model.Polyline("foot", 1, ring, part=-1)

    def test_ramp_path_and_finding(self) -> None:
        """RF-018-16, 26: la rampa da su longitud y sus pendientes (a mano: 10 m de desnivel en 125 m = 8 %); el hallazgo, su unidad."""
        axis = np.array([[0.0, 0.0, 10.0], [50.0, 0.0, 6.0], [125.0, 0.0, 0.0]])
        path = pit_model.RampPath("RMP-001", 3, axis, np.full(3, 5.0))
        self.assertAlmostEqual(path.length_m, 125.0, places=9)
        self.assertAlmostEqual(path.gradient_mean_pct, 8.0, places=9)
        self.assertAlmostEqual(path.gradient_max_pct, 8.0, places=9)
        with self.assertRaises(ValueError):
            pit_model.RampPath("RMP-001", 3, axis, np.full(2, 5.0))
        finding = pit_model.Finding("face_slope", 63.0, 60.0, (1.0, 2.0), bench=2)
        self.assertEqual((finding.unit, finding.bench), ("°", 2))
        self.assertEqual(pit_model.Finding("unexcavated", 5.0, 0.0, (0, 0)).unit, "m²")
        with self.assertRaises(ValueError):
            pit_model.Finding("nothing", 1.0, 1.0, (0.0, 0.0))
        full = self.outcome(ramps=(path,), findings=(finding,),
                            benches=(pit_model.BenchFigures(1, 125.0, 135.0, 300.0, 320.0, 1000.0),),
                            skyline=(np.array([[0.0, 0.0, 175.0], [1.0, 1.0, 175.0]]),))
        self.assertEqual(len(full.ramps), 1)
        self.assertEqual(len(full.skyline), 1)
        with self.assertRaises(TypeError):
            self.outcome(findings=("x",))


class ReexportAndLazyTest(unittest.TestCase):
    def test_reexports_and_limits(self) -> None:
        """RF-018-07, 15: ``RoseRange`` y ``RampDef`` son los de T04; los topes de validez son los de RF-018-04."""
        self.assertIs(pit_model.RoseRange, pit_rose.RoseRange)
        self.assertIs(pit_model.RampDef, pit_ramp_def.PitRampDef)
        self.assertEqual((pit_model.MAX_BENCHES, pit_model.MAX_VERTICES), (200, 50_000))

    def test_lazy(self) -> None:
        """RNF-001-03: el módulo no lo importa el arranque ni ``design.model`` y es de los vigilados."""
        self.assertIn("design.pit_model", test_lazy_registration.HEAVY)
        source = (EXTENSION_DIR / "design" / "model.py").read_text(encoding="utf-8")
        self.assertNotIn("pit_model", source)


if __name__ == "__main__":
    unittest.main()
