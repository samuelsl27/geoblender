# SPDX-License-Identifier: GPL-3.0-or-later
"""Preparar la corta y rechazar, sobre el proyecto de las cortas, como prueba de **hito** (spec 018, T21; HU-018-1 y HU-018-5; RF-018-01 a RF-018-06;
RF-015-06, RF-015-07, RF-015-08; CE-018-08; plan 018 §5.2.1, §5.4 A0 y A1, §5.7 P-13; P-16: lo que monta un proyecto no entra en el «verde»).

Sobre el proyecto de las cortas (``tests.support.pit_data``: la cantera de la 015 con los terrenos de la 018, en la gruesa de 2 m, 200 × 200 celdas) con las
capas de polígonos de cada caso: ``design.pit_store`` **lee y comprueba antes de calcular**, sin escribir nada (el contador de cambios de la base, las
operaciones, los datos, los parámetros y los ficheros no se mueven), y cada rechazo de RF-018-04 sale nombrando la capa, la corta, el campo y el valor. Lo puro
(los valores, el hash, la ventana) está en ``test_pit_prepare``.
"""

from __future__ import annotations

import dataclasses
import unittest
from typing import Any

import numpy as np

from tests.support import design_fixtures as dfx
from tests.support import pit_data as pd
from tests.support import quarry_fixtures as qfx
from tests.support import res_fixtures
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.versions_fixtures import change_counter

access = import_geoblender("gis.masks.access")
core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
gis = import_geoblender("gis")
messages = import_geoblender("design.messages")
pit_model = import_geoblender("design.pit_model")
pit_store = import_geoblender("design.pit_store")
provenance = import_geoblender("design.provenance")
res_provenance = import_geoblender("reserves.provenance")
road_model = import_geoblender("design.road_model")

DesignError = messages.DesignError
GRID = qfx.grid_of(qfx.COARSE_STEP_M)
FLAT = pd.dataset_of("corta_llano")
LIMIT = pd.dataset_of("corta_limite")
HOLLOW = "gis_dtm_corta_hueco"
EXPL = "expl_10_60_6"
REST = "rest_5_35_6"
FLOORS = "gis_fea_corta_fondos"
LIMITS = "gis_fea_corta_limites"
CODE = "PIT-001"
KEY = "des.pit.pit_001."
BY_HAND = {"source": "Perfil de prueba", "source_kind": "person", "decided_by": "Samuel (IMGA)"}


def never(request: Any) -> Any:
    raise AssertionError("las pruebas del «verde» no recalculan ni reproducen")


def ring(points: Any) -> np.ndarray:
    """Los puntos locales como anillo absoluto."""
    return pd.absolute(points, GRID)


def square(half: float, center: tuple[float, float] = pd.CENTER) -> np.ndarray:
    return pd.rect_ring(2 * half, 2 * half, center)


def layer(name: str, rings: Any, names: Any, **fields: Any) -> Any:
    """Una capa de polígonos con una parte por geometría; ``rings`` es, por geometría, una lista de anillos locales (el exterior y sus huecos)."""
    return sdata.FieldsLayer(name, "polygon", tuple((tuple(ring(item) for item in group),) for group in rings), tuple(names),
                             {key: tuple(value) for key, value in fields.items()})


def request(name: str = "Corta del fondo", *, mode: str = "up", source: str = FLOORS, start: str = FLAT, **changes: Any) -> Any:
    base: dict[str, Any] = {"profile": EXPL, "arc_tol_m": pd.HYPOTHESES.arc_m, "simplify_m": pd.HYPOTHESES.simplify_m}
    if mode == "up":
        base["level_field"] = "cota_m"
    else:
        base["bottom_level_m"] = pd.LIMIT_BOTTOM_Z_M
    return pit_model.PitRequest(name, road_model.LayerFields(source, "nombre"), mode, start, **{**base, **changes})


class PitPrepareCase(pd.PitProjectCase):
    """Una copia por clase del proyecto de las cortas con las capas de cada caso y las máscaras de V01 cargadas."""

    masks_v1: Any

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_definitions((*design_params.DEFINITIONS, *design_params.QUARRY_DEFINITIONS))
        cls.addClassCleanup(core_params.unregister_definitions, "des")
        core_params.register_definitions(res_provenance.VERIFY_DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "res")
        for families in (design_params.FAMILIES, design_params.PIT_FAMILIES, design_params.PIT_SECTOR_FAMILIES):
            core_params.register_families(families)
        cls.addClassCleanup(core_params.unregister_families, "des")
        cls.enterClassContext(registered(provenance.operation_def(provenance.PIT, never), *provenance.PIT_FIGURES))
        cls.write_profiles()
        cls.masks_v1 = access.load_masks(cls.project, cls.v1.uid)
        hole = pd.flat_terrain(GRID)
        hole[pd.rd.in_box((115.0, 150.0, 125.0, 170.0), GRID)] = np.nan
        res_fixtures.write_grids(cls.project, [("corta_hueco", gis.Raster(GRID, hole, pd.CRS, pd.VERTICAL))], message="Terreno con hueco")
        circle = pd.circle_ring()
        bowtie = [(150.0, 150.0), (250.0, 250.0), (250.0, 150.0), (150.0, 250.0)]
        for item in (
                layer(FLOORS, [[circle]], ["Fondo circular"], cota_m=[pd.FLOOR_Z_M]),
                layer("gis_fea_corta_huecos", [[square(40), square(10)]], ["Con hueco"], cota_m=[125.0]),
                layer("gis_fea_corta_lazo", [[bowtie]], ["Lazo"], cota_m=[125.0]),
                layer("gis_fea_corta_repetido", [[[(150.0, 150.0), (250.0, 150.0), (250.0, 150.0), (250.0, 250.0), (150.0, 250.0)]]], ["Repetido"],
                      cota_m=[125.0]),
                layer("gis_fea_corta_fuera", [[square(40, (10.0, 200.0))]], ["Fuera"], cota_m=[125.0]),
                layer("gis_fea_corta_hueco_dato", [[square(40, (160.0, 160.0))]], ["Sobre el hueco"], cota_m=[125.0]),
                layer("gis_fea_corta_solape", [[square(40, (180.0, 200.0))], [square(40, (220.0, 200.0))]], ["Uno", "Dos"], cota_m=[125.0, 125.0]),
                layer("gis_fea_corta_sin_cota", [[circle]], ["Sin cota"], cota_m=[None]),
                layer("gis_fea_corta_cota_mala", [[circle]], ["Cota mala"], cota_m=[127.0]),
                layer("gis_fea_corta_aire", [[circle]], ["En el aire"], cota_m=[205.0]),
                sdata.FieldsLayer("gis_fea_corta_dos_partes", "polygon", (((ring(circle),), (ring(square(20, (300.0, 300.0))),)),), ("Dos",),
                                  {"cota_m": (125.0,)}),
                layer(LIMITS, [[square(100)]], ["Límite cuadrado"]),
                layer("gis_fea_corta_sin_rampa", [[square(10)], [square(15, (300.0, 300.0))]], ["Z1", "Z2"]),
        ):
            sdata.write_layer(cls.project, cls.clock, item)
        sdata.write_layer(cls.project, cls.clock, sdata.FieldsLayer("gis_fea_corta_lineas", "line", ((((ring([(0.0, 0.0), (10.0, 10.0)])),),),), ("L",), {}))

    @classmethod
    def write_profiles(cls) -> None:
        """Los cinco valores de ``EXPL_10_60_6`` (10 m, 60°, 6 m y ancla de 125 m) y de ``REST_5_35_6`` (5 m: otra altura) en el proyecto, con su origen."""
        parameters = core_params.ParameterStore(cls.project)
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            for data in (dfx.EXPL_10_60_6, dfx.REST_5_35_6):
                for param, value in (("height_m", data.height_m), ("face_deg", data.face_deg), ("berm_m", data.berm_m), ("anchor_m", data.anchor_m),
                                     ("mesh_factor", 1.0)):
                    parameters.create(conn, design_params.bench_key(data.code, param), value, kind="ADOPTADO" if param == "mesh_factor" else "HIPÓTESIS",
                                      reason="Perfil de la prueba", **BY_HAND)
        cls.clock.advance(minutes=1)

    def state(self) -> dict[str, Any]:
        """Todo lo que podría escribir la preparación: el contador de cambios de la base y, aparte, lo que se vería."""
        return {"counter": change_counter(self.root),
                "operations": self.query("SELECT uid, status FROM gb_operation ORDER BY rowid"),
                "datasets": self.query("SELECT uid, status, content_sha256 FROM gb_dataset ORDER BY rowid"),
                "parameters": self.query("SELECT key, scope_uid, value FROM gb_parameter ORDER BY rowid")}

    def prepare(self, asked: Any, **options: Any) -> Any:
        return pit_store.prepare_pit(self.project, asked, version=self.v1.uid, masks=options.pop("masks", self.masks_v1), **options)

    def refused(self, asked: Any, expected: str, **options: Any) -> Any:
        """``asked`` se rechaza con el código ``expected`` y **no escribe nada**; el texto no deja ningún marcador sin llenar en ningún idioma."""
        before = self.state()
        with self.assertRaises(DesignError) as caught:
            self.prepare(asked, **options)
        error = caught.exception
        self.assertEqual(error.code, expected)
        self.assertEqual(self.state(), before, "el rechazo ha escrito algo")
        for text in (error.text, error.text_in("en")):
            self.assertNotIn("{", text)
        return error


class AscendingTest(PitPrepareCase):
    """RF-018-01, 02, 03, 05, 06: lo que prepara una corta ascendente."""

    def test_the_prepared_job_has_everything_that_was_read(self) -> None:
        """El trabajo trae la rejilla, la partida, las máscaras, el fondo con su cota, el perfil base y los parámetros; la operación es ``des.pit`` y no escribe nada."""
        before = self.state()
        prepared = self.prepare(request())
        self.assertEqual(self.state(), before)
        job = prepared.job
        self.assertEqual((prepared.code, prepared.op_type, prepared.start_surface), (CODE, "des.pit", FLAT))
        self.assertEqual(job.mode, pit_model.PitMode.UP)
        self.assertEqual([(item.name, item.level_m) for item in job.sources], [("Fondo circular", 125.0)])
        self.assertEqual(job.profile.code, EXPL)
        self.assertEqual((job.height_m, job.anchor_m), (10.0, 125.0))
        self.assertEqual(job.start.shape, GRID.shape)
        self.assertEqual(float(np.nanmin(job.start)), 175.0)
        self.assertEqual((job.params.arc_tol_m, job.params.simplify_m, job.params.n_berm), (pd.HYPOTHESES.arc_m, pd.HYPOTHESES.simplify_m, 1))
        self.assertTrue(job.cut_allowed.shape == GRID.shape and job.untouchable.shape == GRID.shape)
        self.assertIsNotNone(job.perimeter)

    def test_the_inputs_the_parameters_and_the_rows(self) -> None:
        """RF-018-01, RF-018-03, RF-018-05: la capa (con su geometría), la partida y las máscaras son entradas; los parámetros leen el perfil, las tolerancias y los
        del proyecto; cada valor tiene su fila con su procedencia; la corta no lleva ``protect`` ni ``guard_m``."""
        prepared = self.prepare(request())
        uses = {(use.item, use.role) for use in prepared.start.inputs}
        self.assertIn((FLOORS, provenance.ENTITY_LAYER_ROLE), uses)
        self.assertIn((FLAT, provenance.SURFACE_ROLE), uses)
        self.assertTrue(any(role.startswith("mask") or "mask" in role for _item, role in uses))
        params = set(prepared.start.params)
        for key in ("mode", "layer", "start", "arc_tol_m", "simplify_m", "n_berm", "corner", "profile"):
            self.assertIn(KEY + key, params)
        self.assertIn("des.bench.expl_10_60_6.height_m", params)
        self.assertNotIn(KEY + "name", params)
        self.assertFalse(any(key.endswith(("protect", "guard_m")) for key in params))
        rows = {row.key: row for row in prepared.rows}
        self.assertEqual(rows[KEY + "arc_tol_m"].value, pd.HYPOTHESES.arc_m)
        self.assertEqual(rows[KEY + "arc_tol_m"].source_kind, "person")
        self.assertEqual(rows[KEY + "corner"].source_kind, "algorithm")
        self.assertEqual(rows[KEY + "n_berm"].value, 1)
        self.assertEqual({row.key for row in prepared.rows} - set(prepared.start.params), {KEY + "name"})

    def test_the_source_geometry_hash_and_the_unchanged_input(self) -> None:
        """RF-018-01: el hash de cada polígono de origen; la capa del usuario no se modifica (su contenido, antes y después, igual)."""
        before = self.read_layer(FLOORS)
        prepared = self.prepare(request())
        after = self.read_layer(FLOORS)
        self.assertTrue(np.array_equal(before.parts[0][0][0], after.parts[0][0][0]))
        self.assertEqual(set(prepared.sources_sha256), {"Fondo circular"})
        self.assertEqual(prepared.sources_sha256["Fondo circular"], pit_store.source_sha256(prepared.job.sources[0].ring, 125.0))
        moved = pit_store.source_sha256(prepared.job.sources[0].ring + 1e-9, 125.0)
        self.assertNotEqual(moved, prepared.sources_sha256["Fondo circular"])

    def test_the_working_window_contains_what_the_pit_can_touch(self) -> None:
        """A0: la ventana contiene el fondo y el alcance de la corta (los bancos para llegar al terreno), recortada a la rejilla."""
        prepared = self.prepare(request())
        rows, cols = prepared.window
        self.assertTrue(0 <= rows.start < rows.stop <= GRID.nrows and 0 <= cols.start < cols.stop <= GRID.ncols)
        centre = GRID.nrows // 2
        self.assertTrue(rows.start < centre - 25 < centre + 25 < rows.stop and cols.start < centre - 25 < centre + 25 < cols.stop)

    def test_a_geometry_of_several_parts_makes_a_source_per_part(self) -> None:
        """Una geometría de dos partes da dos polígonos de origen (``nombre/1`` y ``nombre/2``), cada uno con la cota de su geometría."""
        prepared = self.prepare(request(source="gis_fea_corta_dos_partes"))
        self.assertEqual([item.name for item in prepared.job.sources], ["Dos/1", "Dos/2"])

    def test_the_zones_without_ramp(self) -> None:
        """RF-018-15: las zonas sin rampa son las partes de los polígonos de su capa, que entra como entrada."""
        asked = request(noramp=road_model.LayerFields("gis_fea_corta_sin_rampa", "nombre"))
        prepared = self.prepare(asked)
        self.assertEqual(len(prepared.job.noramp), 2)
        self.assertIn(("gis_fea_corta_sin_rampa", provenance.ENTITY_LAYER_ROLE), {(use.item, use.role) for use in prepared.start.inputs})

    def test_what_is_not_prepared_yet(self) -> None:
        """T21b: los bancos fijados, la roseta y las rampas se piden con un error del programa, no se ignoran."""
        for changes in ({"rose": "r1"}, {"ramps": ("rampa_1",)}, {"fixed": road_model.LayerFields("gis_fea_corta_sin_rampa", "nombre")}):
            with self.subTest(changes=changes), self.assertRaises(NotImplementedError):
                self.prepare(request(**changes))


class DescendingTest(PitPrepareCase):
    """RF-018-02 y RF-018-13: una corta descendente desde un límite, con su criterio de parada."""

    def test_a_limit_with_its_stop_criterion(self) -> None:
        prepared = self.prepare(request("Corta del límite", mode="down", source=LIMITS, start=LIMIT, profile=EXPL))
        job = prepared.job
        self.assertEqual(job.mode, pit_model.PitMode.DOWN)
        self.assertEqual([(item.name, item.level_m) for item in job.sources], [("Límite cuadrado", None)])
        self.assertEqual(job.params.bottom_level_m, pd.LIMIT_BOTTOM_Z_M)
        rows, cols = prepared.window  # la caja del límite (200 m = 100 celdas) más dos celdas a cada lado
        self.assertEqual((rows.stop - rows.start, cols.stop - cols.start), (104, 104))

    def test_a_crest_level_is_optional(self) -> None:
        """RF-018-02: la cota de la cresta, si la capa da su campo, llega al polígono."""
        with_level = layer("gis_fea_corta_limite_cota", [[square(100)]], ["Con cota"], cota_m=[100.0])
        sdata.write_layer(self.project, self.clock, with_level)
        prepared = self.prepare(request("Con cota", mode="down", source="gis_fea_corta_limite_cota", start=LIMIT, level_field="cota_m"))
        self.assertEqual(prepared.job.sources[0].level_m, 100.0)


class RejectionsTest(PitPrepareCase):
    """RF-018-04: cada rechazo con su capa, su corta, su campo y su valor, sin escribir nada."""

    def test_the_layer_is_not_of_polygons(self) -> None:
        error = self.refused(request(source="gis_fea_corta_lineas"), "des.pit_layer_kind")
        self.assertIn("gis_fea_corta_lineas", error.text)

    def test_a_polygon_with_holes(self) -> None:
        """P-13: un polígono con huecos se rechaza."""
        error = self.refused(request(source="gis_fea_corta_huecos"), "des.pit_source_holes")
        self.assertEqual(error.values["value"], "Con hueco")
        self.assertIn("Corta del fondo", error.text)

    def test_a_polygon_that_crosses_itself(self) -> None:
        self.assertIn("se corta a sí mismo", self.refused(request(source="gis_fea_corta_lazo"), "des.pit_polygon_invalid").text)

    def test_a_polygon_with_a_repeated_vertex(self) -> None:
        self.assertIn("vértice repetido", self.refused(request(source="gis_fea_corta_repetido"), "des.pit_polygon_invalid").text)

    def test_a_polygon_outside_the_grid(self) -> None:
        self.assertIn("sale de la rejilla", self.refused(request(source="gis_fea_corta_fuera"), "des.pit_polygon_invalid").text)

    def test_a_polygon_without_data_in_the_start_surface(self) -> None:
        self.assertIn("dato", self.refused(request(source="gis_fea_corta_hueco_dato", start=HOLLOW), "des.pit_polygon_invalid").text)

    def test_two_polygons_that_overlap(self) -> None:
        error = self.refused(request(source="gis_fea_corta_solape"), "des.pit_polygons_overlap")
        self.assertEqual((error.values["value"], error.values["other"]), ("Uno", "Dos"))

    def test_a_floor_without_level(self) -> None:
        self.assertEqual(self.refused(request(source="gis_fea_corta_sin_cota"), "des.pit_level_missing").values["value"], "Sin cota")

    def test_a_level_off_the_bench_lattice(self) -> None:
        """D-4: 127 m con ancla 125 m y h = 10 m no es de la retícula."""
        error = self.refused(request(source="gis_fea_corta_cota_mala"), "des.pit_level_off_lattice")
        self.assertIn("127", error.text)

    def test_a_floor_above_the_ground(self) -> None:
        self.assertEqual(self.refused(request(source="gis_fea_corta_aire"), "des.pit_nothing_to_excavate").values["value"], 205.0)

    def test_a_name_field_the_layer_does_not_have(self) -> None:
        asked = dataclasses.replace(request(), fields=road_model.LayerFields(FLOORS, "no_existe"))
        self.assertEqual(self.refused(asked, "des.pit_layer_field").values["value"], "no_existe")

    def test_a_missing_tolerance_is_not_chosen_for_the_person(self) -> None:
        """RF-015-08: ``arc_tol_m`` y ``simplify_m`` no tienen valor por defecto."""
        for field in ("arc_tol_m", "simplify_m"):
            with self.subTest(field=field):
                error = self.refused(request(**{field: None}), "des.entity_param_missing")
                self.assertIn(KEY + field, error.text)

    def test_a_tolerance_out_of_range(self) -> None:
        error = self.refused(request(arc_tol_m=-1.0), "des.entity_param_range")
        self.assertIn(KEY + "arc_tol_m", error.text)

    def test_a_descending_pit_without_stop_criterion(self) -> None:
        asked = request("Sin parada", mode="down", source=LIMITS, start=LIMIT, bottom_level_m=None)
        self.assertIn(KEY + "bottom_level_m", self.refused(asked, "des.pit_no_stop").text)

    def test_a_profile_that_does_not_exist_or_has_no_values(self) -> None:
        self.refused(request(profile="no_existe"), "des.profile_value_missing")

    def test_no_profile_at_all(self) -> None:
        self.refused(request(profile=None), "des.entity_param_missing")

    def test_profiles_of_a_different_height(self) -> None:
        """RF-018-06: el base de 10 m y el de un sector de 5 m se rechazan con los dos y sus valores."""
        error = self.refused(request(sector_profiles={"sector_1": REST}), "des.pit_profiles_differ")
        self.assertIn(EXPL, error.text)
        self.assertIn(REST, error.text)

    def test_a_sector_with_another_number_of_benches_between_berms(self) -> None:
        """RF-018-08 y T12: un sector con ``n`` distinto del de la corta se rechaza antes de calcular."""
        error = self.refused(request(sector_n_berm={"sector_1": 2}), "des.pit_sector_n_berm")
        self.assertEqual(error.values["sector"], "sector_1")

    def test_a_sector_that_does_not_exist(self) -> None:
        self.refused(request(sector_n_berm={"sector_9": 1}), "des.sector_unknown")

    def test_a_name_that_is_taken_and_a_support_that_does_not_exist(self) -> None:
        self.refused(request(start="entity:PIT-009"), "des.entity_start_unknown")

    def test_a_chain_without_a_start(self) -> None:
        self.refused(request(start=""), "des.entity_param_missing")


class SectorTest(PitPrepareCase):
    """RF-018-05, RF-015-07, CE-018-08: un sector sin búsqueda de intocables vigente rechaza el cálculo si lo toca la corta."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        with cls.project.write_transaction() as conn:  # el «Sector oeste» (x de 20 a 190 m): sin búsqueda vigente
            conn.execute("DELETE FROM core_untouchable_search WHERE sector_code = 'sector_1'")
        cls.clock.advance(minutes=1)

    def test_a_pit_in_a_pending_sector(self) -> None:
        """El límite cuadrado (de x = 100 a 300 m) toca el «Sector oeste»: ``des.sector_pending`` con su nombre y la orden que lo arregla."""
        error = self.refused(request("Corta del límite", mode="down", source=LIMITS, start=LIMIT), "des.sector_pending")
        self.assertIn("Sector oeste", error.text)
        self.assertIn("Buscar elementos intocables por sector", error.text)

    def test_a_pit_that_does_not_touch_it(self) -> None:
        """Un límite en el este (de x = 300 a 340 m) no toca el sector pendiente: se prepara."""
        sdata.write_layer(self.project, self.clock, layer("gis_fea_corta_este", [[square(20, (330.0, 200.0))]], ["Este"]))
        prepared = self.prepare(request("Corta del este", mode="down", source="gis_fea_corta_este", start=LIMIT))
        self.assertEqual(prepared.code, CODE)


if __name__ == "__main__":
    unittest.main()
