# SPDX-License-Identifier: GPL-3.0-or-later
"""Los modos «sobre un eje» y «eje 3D» con el proyecto (spec 017, T23; HU-017-1 y HU-017-4; RF-017-02, RF-017-04, RF-017-13, RF-017-14, RF-017-17 y RF-017-18; RF-015-02 y RF-009-11; CE-017-02 y CE-017-03;
E3; plan 017 §5.2.1, §5.4 A4 y A5, §5.7 P-14; decisión de la sesión principal T23-a), como prueba de **hito**: ``check.py --completo`` la ejecuta; el «verde» tiene las suyas, sin proyecto, en
``test_road_modes.py``.

Sobre la copia del proyecto de las pistas (rejilla de 2 m, 200 × 200 celdas) con las máscaras de V01, la capa de ejes en planta de las pistas (``gis_fea_``) y las líneas de rotura con Z
(``gis_brk_``), con cuatro perfiles de la prueba (alcance de 12,5 m: lo que cuesta el borde en 2 m):

- **«Sobre un eje»** (:class:`OnAxisProjectTest`): CE-017-02 con las líneas del proyecto —la esquina de 40 m da el arco de 31,416 m y el eje de 71,4159 m; la de 15 m, el radio de 15 m con su aviso o, con
  Rmín = 16 m, el rechazo, que no escribe nada— y **la capa de origen no cambia** (su hash antes y después de calcular y de crear); la «opción A15» (E3: pd = 15 %, pm = 10 %, la media de 10,5 %)
  pide la confirmación con un motivo, que queda en los ajustes con quién y cuándo.
- **«Eje 3D»** (:class:`ThreeDProjectTest`, T23-a): la Z de la línea sale de una **línea de rotura** (``gis_brk_``) o de la capa propuesta (``des_rpl_``), una capa de **entidades** (sin Z) se rechaza
  con ``des.road_line_no_z`` sin escribir nada, y la pista **se prepara, se calcula y se crea** con la Z de la línea como rasante (la del eje por estaciones, ``des_rdx_``) y los avisos por tramo,
  de la media y del radio de la planta; **la línea no cambia** (CE-017-03, la parte del eje 3D).
- **Recalcular y reproducir** (:class:`ThreeDReproduceTest`, RF-015-02, RF-009-11): las pistas de «eje 3D» de V01 congeladas en ``V01.r1`` y reproducidas **sin proyecto** dan el mismo hash en cada
  dato y las mismas cifras, y recalcularlas da lo mismo bit a bit.
"""

from __future__ import annotations

import json

import numpy as np

from tests.support import res_fixtures
from tests.support import road_data as rd
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter, files
from tests.unit.design.milestone_road_calculate import A15
from tests.unit.design.milestone_road_recompute import RecomputeCase, finish_steps, reproduce_mod
from tests.unit.design.test_road_prepare import BY, GRID, RAMP, request

design_params = import_geoblender("design.params")
gis = import_geoblender("gis")
freeze = import_geoblender("core.versions.freeze")
messages = import_geoblender("design.messages")
provenance = import_geoblender("design.provenance")
road_model = import_geoblender("design.road_model")
road_profiles = import_geoblender("design.road_profiles")
road_store = import_geoblender("design.road_store")
store = import_geoblender("design.store")

REASON = "Opción A15 de la propiedad (N-15)"
CORNER_LAYER = "gis_brk_pistas_esquina"
"""La capa de líneas con Z de la esquina de 40 m (con el eje de CE-017-02 en planta y la Z de la propiedad)."""
CORNER_Z = (102.4, 104.0, 104.0)
"""La Z de la esquina: la del plano del 4 % bajo ella (de 102,4 m en el primer vértice a 104 m en el segundo, y nivelada hasta el tercero)."""
PLANES = tuple(f"plano_{number}" for number in range(1, 6))
"""Cinco copias del plano de la rampa (``gis_dtm_plano_1`` a ``_5``): de cada superficie parte una sola entidad (D-16), así que cada pista que se crea parte de la suya."""
PROFILES = {
    "MODOS": {},
    "MODOS_RMIN16": {"min_radius_m": 16.0},
    "MODOS_A15": {"max_gradient_pct": 15.0, "max_mean_gradient_pct": 10.0},
    "MODOS_PM5": {"max_mean_gradient_pct": 5.0},
}
"""Los perfiles de la prueba (alcance de 12,5 m; lo demás, el de referencia): el código de cada uno es su nombre en minúsculas."""


def request_3d(name: str, feature: str, *, layer: str = rd.BREAKLINES_LAYER, profile: str = "modos", surface: str = RAMP, **changes: object) -> object:
    """Una pista «eje 3D» de la línea ``feature`` (su ``line_id``) de la capa de líneas con Z ``layer``."""
    return road_model.RoadRequest(name, road_model.LayerFields(layer, "line_id"), "axis_3d", profile, surface, feature=feature, **changes)


class ModesCase(RecomputeCase):
    """Lo de ``RecomputeCase`` (los tipos reales de recalcular y reproducir) con los cuatro perfiles de las pruebas y la capa de líneas con Z de la esquina."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        declared = road_profiles.ProfileDeclaration("ITC 07.1.03 de la prueba", BY, "Perfil de la prueba de la T23", version=cls.v1.code)
        for name, changes in PROFILES.items():
            profile = rd.profile_with(reach_m=12.5, **changes)
            values = {param: getattr(profile, "class_name" if param.value == "class" else param.value) for param in design_params.RoadProfileParam}
            cls.clock.advance(minutes=1)
            road_profiles.edit_road_profiles(cls.project, (road_profiles.ProfileEdit(name=name, values=values),), declared)
        cls.clock.advance(minutes=1)
        res_fixtures.write_grids(cls.project, [(label, gis.Raster(GRID, rd.ramp_terrain(GRID), rd.CRS, rd.VERTICAL)) for label in PLANES], message="Planos de la prueba de los modos de la pista (T23)")
        cls.clock.advance(minutes=1)
        sdata.write_breaklines(cls.project, cls.clock, CORNER_LAYER, [np.column_stack([rd.absolute(rd.CORNER_LONG, GRID), CORNER_Z])])
        cls.clock.advance(minutes=1)

    def line_of(self, layer: str, fid: int) -> np.ndarray:
        """La línea ``fid`` de la tabla ``layer`` del proyecto tal como está guardada (X, Y y Z absolutas)."""
        found = road_store.read_layer_3d(self.project, request_3d("x", "1", layer=layer), "RDW-001")
        return np.asarray(found.xyz[fid - 1])

    def rows(self, layer: str) -> list[tuple[object, ...]]:
        """Todas las filas de la tabla ``layer``: nadie las cambia."""
        return self.query(f'SELECT * FROM "{layer}" ORDER BY fid')


class OnAxisProjectTest(ModesCase):
    """RF-017-02, RF-017-13, RF-017-14, RF-017-17, CE-017-02, E3: «sobre un eje» con las líneas del proyecto."""

    def test_a_ce_017_02_the_corner_of_the_project_gives_the_analytic_arc_and_the_layer_does_not_change(self) -> None:
        """RF-017-13, CE-017-02, principio 7: la esquina de 40 m + 40 m de la capa de ejes, con R = 20 m, da el eje de 71,4159 m con **una** curva de 20 m (la tangente de 20 m y el arco de 31,416 m);
        «Calcular» **no cambia la capa de origen** (su hash, su estado y sus filas, antes y después) ni la partida y no escribe nada."""
        layer_before, hashes = self.rows(rd.AXES_LAYER), self.hashes(rd.AXES_LAYER, rd.dataset_of(PLANES[0]))
        asked = request("Esquina de 40 m", mode="on_axis", layer=rd.AXES_LAYER, surface=rd.dataset_of(PLANES[0]), feature="Esquina de 40 m", profile="modos")
        before = self.state()
        calculation = self.calculate(asked)
        self.assertEqual(self.state(), before)
        outcome = calculation.outcome
        self.assertAlmostEqual(outcome.axis.length_m, 40.0 + 40.0 - 2.0 * 20.0 + 10.0 * np.pi, delta=1e-9)
        (curve,) = outcome.axis.curves
        self.assertEqual((curve.radius_m, round(curve.tangent_m, 9), round(curve.length_m, 9)), (20.0, 20.0, round(10.0 * np.pi, 9)))
        self.assertEqual(self.rows(rd.AXES_LAYER), layer_before)
        self.assertEqual(self.hashes(rd.AXES_LAYER, rd.dataset_of(PLANES[0])), hashes)
        calculation.discard()

    def test_b_ce_017_02_the_radius_that_does_not_fit_is_reduced_with_its_notice_or_rejected_writing_nothing(self) -> None:
        """RF-017-14, CE-017-02: la esquina de 15 m + 15 m con Rmín = 12 m se reduce a 15 m (el mayor que cabe) con el aviso del vértice; con el perfil de Rmín = 16 m, **el rechazo** nombra la capa, la
        pista, el vértice, los tramos y el radio que cabría (15 m), no escribe nada y no baja de Rmín por su cuenta."""
        side = rd.dataset_of(PLANES[1])
        asked = request("Esquina de 15 m", mode="on_axis", layer=rd.AXES_LAYER, surface=side, feature="Esquina de 15 m", profile="modos")
        before = self.state()
        calculation = self.calculate(asked)
        reduced = [notice for notice in calculation.notices if notice.code == "des.road_radius_reduced"]
        self.assertEqual([(notice.values["vertex"], round(notice.values["fitted"], 9)) for notice in reduced], [(2, 15.0)])
        calculation.discard()
        self.assertEqual(self.state(), before)
        strict = request("Esquina de 15 m", mode="on_axis", layer=rd.AXES_LAYER, surface=side, feature="Esquina de 15 m", profile="modos_rmin16")
        error = self.refused(strict, "des.road_radius_below_min")
        self.assertEqual((error.values["vertex"], error.values["length_before"], error.values["length_after"], error.values["fitted"], error.values["minimum"]), (2, 15.0, 15.0, 15.0, 16.0))
        self.assertIn(rd.AXES_LAYER, error.obj)

    def test_c_e3_the_a15_road_asks_for_the_confirmation_and_the_reason_stays_recorded(self) -> None:
        """RF-017-17, E3, D-6, N-15: el eje de 200 m de la capa de la propiedad sobre un terreno del 10,5 % con pd = 15 % y pm = 10 % (la «opción A15»): el resumen da el aviso de la media (10,5 % frente al
        10 %) y pide la confirmación; sin ella «Crear» se rechaza sin escribir nada; con el motivo se crea y **el motivo queda en los ajustes con quién y cuándo** (``confirmed_of``)."""
        asked = request("Pista A15 de la propiedad", mode="on_axis", layer=rd.AXES_LAYER, surface=A15, profile="modos_a15")
        layer_before, hashes = self.rows(rd.AXES_LAYER), self.hashes(rd.AXES_LAYER, A15)
        calculation = self.calculate_in(asked)
        self.assertAlmostEqual(calculation.summary.gradient_mean_pct, 10.5, delta=1e-6)
        self.assertTrue(calculation.needs_mean_confirmation)
        before = self.state()
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create(decided_by=BY)
        self.assertEqual(caught.exception.code, "des.road_mean_unconfirmed")
        self.assertEqual(self.state(), before)
        calculation.confirm_road(mean=True, reason=REASON)
        stored = calculation.create(decided_by=BY)
        self.clock.advance(minutes=1)
        ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", str(stored.handle.uid))
        confirmed = road_store.confirmed_of(json.loads(settings))
        self.assertIsNotNone(confirmed)
        self.assertEqual((confirmed.reason, confirmed.decided_by, confirmed.mean_limit_pct), (REASON, BY, 10.0))
        self.assertAlmostEqual(confirmed.mean_pct, 10.5, delta=1e-6)
        self.assertTrue(confirmed.decided_on)
        self.assertEqual(self.rows(rd.AXES_LAYER), layer_before, "crear no cambia la capa de origen")
        self.assertEqual(self.hashes(rd.AXES_LAYER, A15)[rd.AXES_LAYER], hashes[rd.AXES_LAYER])


class ThreeDProjectTest(ModesCase):
    """RF-017-02, RF-017-04, RF-017-17, RF-017-18, CE-017-03, T23-a: «eje 3D» con las líneas de rotura del proyecto. **En orden** (``test_c``: crea la pista de la línea irregular)."""

    def test_a_the_line_with_z_is_read_from_the_breaklines_layer_without_writing(self) -> None:
        """RF-017-02, RF-017-18, T23-a: la preparación lee la línea con su Z de la tabla de líneas de rotura **tal como está guardada** (bit a bit, X, Y y Z absolutas en float64: la irregular de
        CE-017-03 por su ``line_id`` ``S1``, la lisa por su ``fid``), el trabajo no lleva cota de inicio ni de fin (la Z es la rasante), la capa es una entrada con su papel y **nada se escribe**."""
        before = self.state()
        irregular = self.prepare(request_3d("Pista 3D irregular", "S1"))
        smooth = self.prepare(request_3d("Pista 3D lisa", "2"))
        self.assertEqual(self.state(), before)
        np.testing.assert_array_equal(irregular.job.geometry.line, rd.axis_3d_irregular())
        np.testing.assert_array_equal(smooth.job.geometry.line, rd.axis_3d_smooth())
        self.assertEqual((irregular.fid, smooth.fid), (1, 2))
        for prepared in (irregular, smooth):
            self.assertIs(prepared.job.request.mode, road_model.RoadMode.AXIS_3D)
            self.assertEqual((prepared.job.start_level_m, prepared.job.end_level_m, prepared.job.route, prepared.layer), (None, None, None, rd.BREAKLINES_LAYER))
            self.assertNotIn("start_level_m", prepared.values)
            self.assertNotIn("end_level_m", prepared.values)
            self.assertEqual(prepared.values["feature"], prepared.job.request.feature)
            self.assertIn((rd.BREAKLINES_LAYER, provenance.ENTITY_LAYER_ROLE), [(use.item, str(use.role)) for use in prepared.start.inputs])

    def test_b_an_entities_layer_without_z_and_a_line_without_z_are_rejected_writing_nothing(self) -> None:
        """RF-017-04, T23-a: una capa de **entidades** (``gis_fea_``, solo X e Y: ``docs/trampas.md`` §6) o una línea sin Z se rechazan con ``des.road_line_no_z`` nombrando la capa, la pista, el
        campo y el valor, **sin escribir nada ni elegir una cota por la persona**; una capa que no existe, ``gis.dataset_unknown``; una línea que la capa no tiene, ``des.entity_feature_unknown``."""
        error = self.refused(request_3d("Pista 3D de entidades", "Eje de 200 m", layer=rd.AXES_LAYER), "des.road_line_no_z")
        self.assertEqual((error.value, error.values["layer"]), ("Eje de 200 m", rd.AXES_LAYER))
        self.assertIn(rd.AXES_LAYER, error.obj)
        self.assertIn("Pista 3D de entidades", error.obj)
        self.assertTrue(error.field.endswith(".feature"))
        before = self.state()
        with self.assertRaises(Exception) as caught:
            self.prepare(request_3d("Pista sin capa", "S1", layer="gis_brk_no_existe"))
        self.assertEqual(caught.exception.code, "gis.dataset_unknown")
        self.assertEqual(self.state(), before)
        self.refused(request_3d("Pista sin línea", "S9"), "des.entity_feature_unknown")

    def test_c_calculating_and_creating_give_the_z_of_the_line_as_the_gradient_line_and_never_change_the_line(self) -> None:
        """RF-017-18, CE-017-03: la línea irregular (tramos del 5, 5, 10, 15, −2, 8, 12, 0, 5 y 10 %) con pd = 10 % da un aviso por estación de los dos tramos que pasan de pd (40 con w = 1 m) y, con
        planta recta, ninguno del radio; **se crea** con la Z de la línea como rasante (el eje por estaciones ``des_rdx_`` lleva esa cota en cada estación) y **la línea no cambia** (su hash, su estado y
        sus filas); la operación consume la capa de líneas con su papel y los parámetros de la pista dicen su modo y su línea."""
        layer_before, hashes = self.rows(rd.BREAKLINES_LAYER), self.hashes(rd.BREAKLINES_LAYER, RAMP)
        calculation, stored = self.made(request_3d("Pista 3D irregular", "S1"))
        codes = [notice.code for notice in calculation.notices]
        self.assertEqual(codes.count("des.road_axis3d_gradient"), 40)
        self.assertNotIn("des.road_axis3d_radius", codes)
        self.assertEqual(self.rows(rd.BREAKLINES_LAYER), layer_before)
        self.assertEqual(self.hashes(rd.BREAKLINES_LAYER, RAMP), hashes)
        uid = str(stored.handle.uid)
        self.assertIn((rd.BREAKLINES_LAYER, provenance.ENTITY_LAYER_ROLE), self.inputs(uid))
        axis = self.table("Pista 3D irregular", provenance.ROAD_AXIS_TABLE)
        line = rd.axis_3d_irregular()
        along = 20.0 * np.arange(len(line))
        np.testing.assert_allclose([row["level_m"] for row in axis], np.interp([row["station_m"] for row in axis], along, line[:, 2]), rtol=0.0, atol=1e-9)
        entity = self.table("Pista 3D irregular", provenance.ENTITY_TABLE)[0]
        self.assertEqual((entity["layer"], entity["source_fid"], entity["mode"]), (rd.BREAKLINES_LAYER, 1, "axis_3d"))
        names = {key.rsplit(".", 1)[1] for (key,) in self.query("SELECT key FROM gb_parameter WHERE key LIKE ?", f"des.road.rdw_{self.code_of('Pista 3D irregular')}.%")}
        self.assertTrue({"name", "mode", "layer", "profile", "start", "feature"} <= names, names)
        self.assertFalse(names & {"origin", "destination", "start_level_m", "end_level_m", "search_budget", "protect", "guard_m"}, names)

    def test_d_the_corner_without_a_curve_is_a_radius_notice_with_its_station_and_place(self) -> None:
        """RF-017-18, CE-017-02: la esquina de 40 m + 40 m **sin curva** (el radio de la planta es nulo en el vértice) da, con Rmín = 12 m, el aviso del radio por debajo del mínimo en las dos estaciones
        que rodean el vértice (35 y 36 m), con su lugar sobre la línea; se crea y la línea no cambia."""
        layer_before = self.rows(CORNER_LAYER)
        calculation, _stored = self.made(request_3d("Pista 3D de la esquina", "1", layer=CORNER_LAYER, profile="modos", surface=rd.dataset_of(PLANES[3])), carriageway=True)
        radius = [notice for notice in calculation.notices if notice.code == "des.road_axis3d_radius"]
        self.assertEqual([notice.values["station"] for notice in radius], [35.0, 36.0])
        self.assertTrue(all(notice.values["radius"] < 12.0 for notice in radius))
        self.assertEqual(self.rows(CORNER_LAYER), layer_before)

    def test_e_the_mean_over_pm_asks_for_the_confirmation_in_this_mode_too(self) -> None:
        """RF-017-17, RF-017-18: con pm = 5 % la media de la línea irregular (7,2 %) pide la confirmación con un motivo, como en los demás modos: sin ella «Crear» se rechaza sin escribir nada."""
        calculation = self.calculate_in(request_3d("Pista 3D con pm de 5 %", "S1", profile="modos_pm5", surface=rd.dataset_of(PLANES[4])))
        self.assertTrue(calculation.needs_mean_confirmation)
        self.assertAlmostEqual(calculation.summary.gradient_mean_pct, rd.AXIS_3D_MEAN_PCT, delta=1e-6)
        before = self.state()
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create(decided_by=BY)
        self.assertEqual(caught.exception.code, "des.road_mean_unconfirmed")
        self.assertEqual(self.state(), before)
        calculation.discard()

    def code_of(self, name: str) -> str:
        """El número de la entidad (``rdw_001`` sin el prefijo) de la pista ``name`` en V01."""
        for entry in road_store.entities.registry(self.project, self.v1.uid):
            if entry.record.name == name:
                return entry.record.code.lower().replace("-", "_").removeprefix("rdw_")
        raise AssertionError(name)


class ThreeDReproduceTest(ModesCase):
    """RF-015-02, RF-009-11, RF-017-18: las pistas de «eje 3D» de V01 congeladas en ``V01.r1`` y reproducidas **sin proyecto**, y recalculadas."""

    revision: str
    roads: dict[str, str]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.roads = {}
        for name, asked in (("Pista 3D irregular", request_3d("Pista 3D irregular", "S1")),
                            ("Pista 3D lisa", request_3d("Pista 3D lisa", "S2", surface=rd.dataset_of(PLANES[0]))),
                            ("Pista 3D de la esquina", request_3d("Pista 3D de la esquina", "1", layer=CORNER_LAYER, surface=rd.dataset_of(PLANES[1])))):
            cls.roads[name] = str(cls.made(asked, carriageway=True)[1].handle.uid)
        cls.clock.advance(minutes=1)
        cls.revision = str(finish_steps(freeze.freeze_steps(cls.project, cls.v1.uid, reason="Entrega de la prueba")).frozen.uid)
        cls.clock.advance(minutes=1)

    def test_a_reproducing_the_frozen_revision_gives_the_same_without_writing(self) -> None:
        """RF-015-02, RF-009-11, RF-017-18: reproducir ``V01.r1`` —sin proyecto, desde la capa de líneas con Z, la partida, las máscaras y los parámetros congelados— da de cada pista de «eje 3D» el
        **mismo hash** de sus cuatro datos y **las mismas cifras**, sin escribir nada en el proyecto."""
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = finish_steps(reproduce_mod.reproduce_steps(self.project, self.revision))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root)), before, "reproducir no escribe en el proyecto")
        for name, uid in self.roads.items():
            with self.subTest(road=name):
                mine = [check for check in report.outputs if check.operation_uid == uid]
                self.assertEqual([check.role for check in mine], ["entity_surface", "entity", "road_axis", "entity_report"])
                self.assertTrue(all(check.same for check in mine), [check for check in mine if not check.same])
                found = [check for check in report.figures if check.operation_uid == uid]
                self.assertEqual(len(found), len(self.figures_of(uid)))
                self.assertTrue(found and all(check.same for check in found), [check for check in found if not check.same])
                self.assertNotIn(uid, [note.operation_uid for note in report.not_reproducible])


class ThreeDRecomputeTest(ModesCase):
    """RF-015-02, RF-017-18: «Recalcular» una pista de «eje 3D» da lo mismo bit a bit (sus parámetros leen su capa de líneas y su línea)."""

    def test_recomputing_gives_the_same_bit_by_bit_and_the_line_is_the_one_of_the_layer(self) -> None:
        """RF-015-02, RF-017-18: repetir la pista de la línea irregular sin cambiar nada es una operación nueva que sustituye a la anterior con **los mismos datos bit a bit y las mismas cifras** (el
        informe también: la superficie que ella misma dejó no es «otro diseño» de la versión aunque su partida sea un dato **del proyecto**, un MDT importado: ``road_store.other_designs``); la
        capa de líneas no cambia."""
        _calculation, stored = self.made(request_3d("Pista 3D irregular", "S1"))
        old = str(stored.handle.uid)
        layer_before = self.rows(rd.BREAKLINES_LAYER)
        before = (self.outputs(old), self.figures_of(old))
        self.clock.advance(minutes=1)
        handle, work = store.recompute_run(self.request_for(old))
        finish_steps(work)
        new = str(handle.uid)
        self.assertEqual(self.query("SELECT supersedes_uid, status FROM gb_operation WHERE uid = ?", new), [(old, "done")])
        self.assertEqual([row[3] for row in self.outputs(new)], [row[3] for row in before[0]])
        self.assertEqual(self.figures_of(new), before[1])
        self.assertEqual(self.rows(rd.BREAKLINES_LAYER), layer_before)


if __name__ == "__main__":
    import unittest

    unittest.main()
