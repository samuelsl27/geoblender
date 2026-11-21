# SPDX-License-Identifier: GPL-3.0-or-later
"""Recalcular y reproducir la pista con el proyecto (spec 017, T22 (a); HU-017-1 y HU-017-2; RF-017-01, RF-017-02, RF-017-03, RF-017-05 (b), RF-017-17 y RF-017-22; RF-015-02, RF-015-04 y RF-015-16;
RF-009-11 y RF-009-19; CE-017-05 y CE-017-08 (la parte de recalcular y reproducir); plan 017 §5.2.3, §5.3.2 y §5.7 P-5), como prueba de **hito**: ``check.py --completo`` la ejecuta; el «verde» tiene
las suyas, sin proyecto, en ``test_road_recompute.py``.

Sobre la copia del proyecto de las pistas (rejilla de 2 m, 200 × 200 celdas) con las máscaras de V01 y el perfil de referencia (**solo de las pruebas**), y la cadena de la T21 —la plataforma ``P1``
(``PLT-001``), la «Pista a P1» (``RDW-001``: destino en ella), el «Ramal» (``RDW-002``: origen en el eje de la anterior, ``RDW-001@100``) y la «Relleno sobre la calzada» (``PLT-002``)—:

- **Recalcular y la obsolescencia con su causa** (:class:`RoadStaleTest`, RF-015-02, RF-015-16, RF-008-26; **en orden**: cada una parte de lo que dejó la anterior): repetir la pista sin cambiar nada
  da lo mismo bit a bit y no escribe otra vez sus parámetros; cambiar **un valor del perfil**, **la capa de origen** o **el espesor mínimo de la 012** la deja obsoleta con su causa, y
  «Recalcular lo obsoleto» la repite, con las que parten de ella o se apoyan en ella, **en orden** y con lo nuevo.
- **Lo confirmado** (:class:`RoadConfirmedRecomputeTest`, RF-017-17, D-6): un recálculo **no confirma por la persona**: arrastra lo que confirmó (quién, cuándo y el motivo) mientras la media nueva no
  pase de ella; si pasa, ``des.road_mean_unconfirmed`` y la anterior sigue vigente.
- **Lo que anotó al empezar** (:class:`RoadRecordedTest`): un parámetro que cambia entre prepararla y empezarla se rechaza al avanzar (``des.input_changed``).
- **Otro diseño de la versión** (:class:`OtherDesignTest`, RF-017-05 (b), CE-017-05): los diseños que difieren en la huella son entradas de la pista; si **cambian**, queda obsoleta con su causa, se
  recalcula con lo nuevo (los que ya no difieren dejan de ser entradas) y lo congelado se reproduce igual.
- **Reproducir** (:class:`RoadReproduceTest`, RF-017-01 a 03, RF-015-02, RF-009-11): un V01.r1 congelado con las pistas de los tres modos (la cadena, «sobre un eje» y la rampa a una cota) da de cada dato
  el mismo hash y las mismas cifras, **sin escribir** nada en el proyecto.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar
from unittest import mock

from tests.support import road_data as rd
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.versions_fixtures import change_counter, files
from tests.unit.design import test_platform_operation as pop
from tests.unit.design.milestone_access_operation import rewrite_layer
from tests.unit.design.milestone_road_calculate import A15, A15_PROFILE, NO_CUT_LAYER
from tests.unit.design.milestone_road_create import (
    FILL,
    FIRST,
    PLATFORM,
    PLATFORM_LAYER,
    REASON,
    SECOND,
    CreateCase,
    first_request,
    second_request,
)
from tests.unit.design.milestone_road_prepare import QuarryStartCase
from tests.unit.design.test_platform_operation import finish
from tests.unit.design.test_road_prepare import BY, GRID, RAMP, request

core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
design_reproduce = import_geoblender("design.reproduce")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
freeze =import_geoblender("core.versions.freeze")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
reproduce_mod = import_geoblender("core.versions.reproduce")
road_store = import_geoblender("design.road_store")
steps = import_geoblender("design.steps")
store = import_geoblender("design.store")

ROAD_FAMILIES = (provenance.ENTITY_SURFACE_GRID, provenance.ENTITY_TABLE, provenance.ROAD_AXIS_TABLE, provenance.ENTITY_REPORT_TABLE)
PROFILE_STEP = "des.roadprofile.pista_principal.station_step_m"
"""El paso de las estaciones de la pista de referencia (1 m): cambiarlo cambia el eje por estaciones y el informe de **toda** pista que use el perfil."""
THICKNESS = "res.verify.min_thickness_m"
"""El espesor mínimo de la 012: lo lee toda entidad que mide un borde o lo que rellena sobre otra."""


def recompute_function(request_: Any) -> Any:
    """Lo que registra ``bl`` como función de recálculo de ``des.road``: lleva los pasos hasta el final."""
    handle, work = store.recompute_run(request_)
    finish_steps(work)
    return handle


def finish_steps(work: Any) -> Any:
    """Los pasos de ``work`` hasta el final: lo último que llevó un ``Progress`` en ``result``."""
    found = None
    for step in work:
        found = step.result if step.result is not None else found
    return found


class RecomputeCase(CreateCase):
    """Lo de ``CreateCase`` con los tipos de las entidades y la pista registrados con sus funciones **reales** de recalcular y reproducir (las que registra ``bl``) y las ayudas de las historias."""

    @classmethod
    def road_definition(cls) -> Any:
        return provenance.operation_def(provenance.ROAD, recompute_function, design_reproduce.reproduce_road)

    @classmethod
    def entity_definitions(cls) -> tuple[Any, ...]:
        """Los tipos de las entidades con sus funciones reales y, desde la T26, la capa de ejes de pistas (``des.road_layer``: la que encadena ``after_entity_change`` cuando la versión tiene pistas), con la suya."""
        return (*pop.real_definitions(), provenance.operation_def(provenance.ROAD_LAYER, recompute_function))

    @classmethod
    def build_chain(cls) -> dict[str, Any]:
        """La cadena de la T21 en V01: ``P1`` (``PLT-001``), la «Pista a P1» (``RDW-001``), el «Ramal» (``RDW-002``) y la «Relleno sobre la calzada» (``PLT-002``): lo guardado de cada una."""
        fields = model.PlatformFields(layer=rd.PLATFORMS_LAYER, start_level_field="cota_inicial", gradient_field="pendiente", width_field="ancho")
        cls.clock.advance(minutes=1)
        asked = model.PlatformRequest(PLATFORM, fields, PLATFORM, RAMP, edge_angle_deg=35.0, reach_m=20.0)
        platform = finish(steps.platform_run(cls.project, asked, masks=cls.masks_v1, version=cls.v1.uid)).create()
        points = (("Entrada", rd.RAMP_ORIGIN), ("En P1", (320.0, 200.0)), ("Fuera de P1", (200.0, 100.0)))
        sdata.write_layer(cls.project, cls.clock, sdata.FieldsLayer(PLATFORM_LAYER, "point", tuple(((rd.absolute([point], GRID),),) for _name, point in points),
                                                                    tuple(name for name, _ in points), {}))
        cls.clock.advance(minutes=1)
        first = cls.made(first_request())[1]
        second = cls.made(second_request())[1]
        relleno = model.PlatformRequest(FILL, fields, FILL, "entity:RDW-002", mode="cut_fill", edge_angle_deg=35.0, reach_m=20.0)
        fill = finish(steps.platform_run(cls.project, relleno, masks=cls.masks_v1, version=cls.v1.uid)).create()
        cls.clock.advance(minutes=1)
        return {"PLT-001": platform, "RDW-001": first, "RDW-002": second, "PLT-002": fill}

    def request_for(self, uid: str) -> Any:
        """Lo que recibe ``bl`` para recalcular la operación ``uid``: su tipo, sus ajustes y su versión."""
        ((op_type, settings),) = self.query("SELECT op_type, settings FROM gb_operation WHERE uid = ?", uid)
        return recompute_mod.RecomputeRequest(self.project, uid, op_type, json.loads(settings), (), (), version=self.v1.uid)

    @classmethod
    def change(cls, key: str, value: Any, *, in_version: bool = True) -> None:
        """Cambia el parámetro ``key`` (el de V01 o, ``in_version`` falso, el del proyecto) un minuto después de lo anterior."""
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            core_params.ParameterStore(cls.project).change(conn, key, value=value, source="prueba de recalcular (T22)", source_kind="person", decided_by=BY,
                                                           reason="Se cambia un parámetro de la pista", version=cls.v1.uid if in_version else None)

    def by_hand(self, key: str, value: Any, *, entity: str = "") -> Any:
        """«Cambiar parámetro…» (``geoblender.core_set_parameter``) de ``key`` en V01, como la orden: comprueba el valor (``check_parameter_change``), añade lo que registra ``des`` de las pistas (``road_store.
        parameter_changes``: la cota que da la persona deja de ser del algoritmo) y cambia la fila de la versión, un minuto después de lo anterior; quien lo hace es ``BY`` y no da otro origen. La fila nueva."""
        store_ = core_params.ParameterStore(self.project)
        self.assertIsNotNone(store_.get(key), f"la orden pide la fila del proyecto de «{key}»: «El parámetro … no está registrado en el proyecto»")
        record = store_.get(key, version=self.v1.uid)
        entity_store.check_parameter_change(self.project, key, value, version=self.v1.uid)
        changes = road_store.parameter_changes(self.project, key, record, {"value": value, "reason": "Se cambia a mano un parámetro de la pista", "decided_by": BY}, version=self.v1.uid)
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            return store_.change(conn, key, version=self.v1.uid, **changes)

    def recompute_all(self) -> list[str]:
        """«Recalcular lo obsoleto» de V01: lo que repite, unidad a unidad y en su orden (los uid de las operaciones nuevas); ninguna unidad falla."""
        outcome = finish_steps(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results], [recompute_mod.UnitStatus.DONE] * len(outcome.results))
        return [str(uid) for result in outcome.results for uid in result.operations]

    def parameters(self) -> list[tuple[Any, ...]]:
        """Los parámetros de las pistas con su historial: lo que no escribe un recálculo."""
        return self.query("SELECT key, value, rev, decided_by FROM gb_parameter WHERE key LIKE 'des.road.%' ORDER BY key, scope")

    def supersedes(self, uid: str) -> list[tuple[Any, ...]]:
        return self.query("SELECT supersedes_uid, status FROM gb_operation WHERE uid = ?", uid)

    def type_of(self, uid: str) -> str:
        return str(self.query("SELECT op_type FROM gb_operation WHERE uid = ?", uid)[0][0])


class RoadStaleTest(RecomputeCase):
    """RF-017-01, RF-017-03, RF-015-02, RF-015-16, RF-008-26, CE-017-08: recalcular la pista y la obsolescencia con su causa. **En orden** (``test_a`` a ``test_d``): cada una parte de lo que dejó
    la anterior."""

    chain: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.chain = cls.build_chain()

    def test_a_recomputing_without_changing_anything_gives_the_same_and_writes_no_parameter(self) -> None:
        """RF-015-02, RF-015-16: «Recalcular» ``RDW-001`` sin haber cambiado nada es **una operación nueva que sustituye a la anterior** (que queda como historia), con los mismos ajustes, las mismas
        entradas (la capa, la partida, las máscaras y la plataforma en que se apoya), **los mismos datos bit a bit** y **las mismas cifras** con su ámbito; no escribe otra vez los parámetros de la
        entidad ni modifica sus entradas, y la operación nueva es la vigente de la entidad y está al día."""
        old = self.current("RDW-001")
        parameters, inputs_before = self.parameters(), self.hashes(PLATFORM_LAYER, rd.POINTS_LAYER, provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, PLATFORM))
        before = (self.outputs(old), self.inputs(old), self.figures_of(old), self.query("SELECT settings FROM gb_operation WHERE uid = ?", old))
        self.clock.advance(minutes=1)
        handle, work = store.recompute_run(self.request_for(old))
        stored = finish_steps(work)
        new = str(handle.uid)
        self.assertEqual(self.supersedes(new), [(old, "done")])
        self.assertEqual(str(stored.handle.uid), new)
        self.assertEqual(self.current("RDW-001"), new)
        self.assertEqual([row[0] for row in self.outputs(new)], [row[0] for row in before[0]])
        self.assertEqual([row[1:3] for row in self.outputs(new)], [row[1:3] for row in before[0]])
        self.assertEqual([row[3] for row in self.outputs(new)], [row[3] for row in before[0]], "lo recalculado es igual bit a bit")
        self.assertEqual(self.figures_of(new), before[2])
        self.assertEqual(set(self.inputs(new)), set(before[1]))
        self.assertEqual(self.query("SELECT settings FROM gb_operation WHERE uid = ?", new), before[3])
        self.assertEqual(self.parameters(), parameters, "un recálculo no escribe otra vez los parámetros de la entidad")
        self.assertEqual(self.hashes(*inputs_before), inputs_before)
        self.assertEqual(self.stale_causes(new), set())
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE uid = ?", old), [("done",)])
        self.assertEqual(self.type_of(new), provenance.ROAD)

    def test_b_a_changed_profile_value_makes_the_roads_stale_and_recomputing_repeats_them_in_order(self) -> None:
        """RF-015-16, RF-017-07, RF-008-26, CE-017-08: cambiar **un valor del perfil** (el paso de las estaciones, de 1 a 2 m) deja obsoletas las dos pistas que lo usan **con su causa** (el
        parámetro) y, por la cadena, la plataforma que se rellenó después sobre la calzada; «Recalcular lo obsoleto» las repite **en orden** (la pista, el ramal y el relleno) y con el valor
        nuevo: el eje de la pista tiene la mitad de estaciones; el ramal sigue saliendo del punto de su eje a 100 m."""
        olds = {code: self.current(code) for code in ("RDW-001", "RDW-002", "PLT-002")}
        stations_before = len(self.table(FIRST, provenance.ROAD_AXIS_TABLE))
        self.change(PROFILE_STEP, 2.0)
        for code in ("RDW-001", "RDW-002"):
            self.assertIn(("parameter_changed", PROFILE_STEP), self.stale_causes(olds[code]), code)
        self.assertTrue(self.stale_causes(olds["PLT-002"]), "la que se rellenó después sobre la calzada también queda obsoleta")
        self.assertEqual(self.stale_causes(self.current("PLT-001")), set(), "la plataforma de destino no lee el perfil de pista")
        self.assertEqual(self.recompute_plan(), [(provenance.ROAD,), (provenance.ROAD,), (provenance.PLATFORM,)])
        self.clock.advance(minutes=1)
        made = self.recompute_all()
        self.assertEqual([self.type_of(uid) for uid in made], [provenance.ROAD, provenance.ROAD, provenance.PLATFORM])
        self.assertEqual([self.supersedes(uid) for uid in made], [[(old, "done")] for old in olds.values()])
        self.assertEqual({code: self.current(code) for code in olds}, dict(zip(olds, made, strict=True)))
        stations_after = len(self.table(FIRST, provenance.ROAD_AXIS_TABLE))
        self.assertLess(stations_after, stations_before)
        self.assertAlmostEqual(stations_after * 2.0, stations_before, delta=4.0)
        at_100 = next(row for row in self.table(FIRST, provenance.ROAD_AXIS_TABLE) if row["station_m"] == 100.0)
        branch = self.table(SECOND, provenance.ROAD_AXIS_TABLE)[0]
        self.assertEqual((branch["x"], branch["y"]), (at_100["x"], at_100["y"]), "el ramal sale del punto del eje de la pista a 100 m")
        for uid in made:
            self.assertEqual(self.stale_causes(uid), set())
        self.assertEqual(self.recompute_plan(), [])

    def test_c_a_changed_layer_makes_the_road_stale_and_the_new_geometry_is_read(self) -> None:
        """RF-017-01, RF-015-16: mover un punto de la capa de origen en QGIS (el origen de la «Pista a P1», 2 m al este) deja obsoleta esa pista **con su causa** (el dato de la capa) y lo que parte
        de ella o se apoya en ella; «Recalcular lo obsoleto» las repite en orden: el eje de la pista empieza 2 m más al este (el origen es exacto) y el ramal sale ahora del eje nuevo."""
        old = self.current("RDW-001")
        start_x = self.table(FIRST, provenance.ROAD_AXIS_TABLE)[0]["x"]
        branch_x = self.table(SECOND, provenance.ROAD_AXIS_TABLE)[0]["x"]
        digest = self.table(FIRST, provenance.ENTITY_TABLE)[0]["geometry_sha256"]
        rewrite_layer(self.project, self.clock, PLATFORM_LAYER, move=2.0)
        self.assertEqual(self.stale_causes(old), {("dataset_changed", PLATFORM_LAYER)})
        self.assertTrue(self.stale_causes(self.current("RDW-002")), "el ramal parte de la superficie de la pista: queda obsoleto en cascada")
        self.clock.advance(minutes=1)
        made = self.recompute_all()
        self.assertEqual([self.type_of(uid) for uid in made], [provenance.ROAD, provenance.ROAD, provenance.PLATFORM])
        self.assertEqual(self.current("RDW-001"), made[0])
        axis = self.table(FIRST, provenance.ROAD_AXIS_TABLE)
        self.assertEqual(axis[0]["x"], start_x + 2.0)
        self.assertNotEqual(self.table(FIRST, provenance.ENTITY_TABLE)[0]["geometry_sha256"], digest)
        self.assertNotEqual(self.table(SECOND, provenance.ROAD_AXIS_TABLE)[0]["x"], branch_x, "el ramal sale del punto del eje nuevo, a 100 m de su origen")
        for uid in made:
            self.assertEqual(self.stale_causes(uid), set())
        self.assertEqual(self.recompute_plan(), [])

    def test_d_a_changed_minimum_thickness_of_the_012_makes_every_entity_stale_with_its_cause(self) -> None:
        """RF-015-16, RF-017-01: el espesor mínimo de la 012 (``res.verify.min_thickness_m``) es un parámetro que leen las cuatro entidades (miden lo que rellenan sobre otras): cambiarlo las deja
        obsoletas con su causa y «Recalcular lo obsoleto» las repite **en el orden de la cadena** (la plataforma, la pista, el ramal y el relleno)."""
        self.change(THICKNESS, 0.5, in_version=False)
        causes = {code: self.stale_causes(self.current(code)) for code in ("PLT-001", "RDW-001", "RDW-002", "PLT-002")}
        for code, found in causes.items():
            self.assertIn(("parameter_changed", THICKNESS), found, code)
        self.assertEqual(self.recompute_plan(), [(provenance.PLATFORM,), (provenance.ROAD,), (provenance.ROAD,), (provenance.PLATFORM,)])
        self.clock.advance(minutes=1)
        made = self.recompute_all()
        self.assertEqual([self.type_of(uid) for uid in made], [provenance.PLATFORM, provenance.ROAD, provenance.ROAD, provenance.PLATFORM])
        for uid in made:
            self.assertEqual(self.stale_causes(uid), set())
        self.assertEqual(self.recompute_plan(), [])


class RoadConfirmedRecomputeTest(RecomputeCase):
    """RF-017-17, D-6, RF-015-02: un recálculo **no confirma por la persona**: arrastra lo que confirmó mientras lo nuevo no pase de ello. La «opción A15» (media de 10,5 % frente al 10 % del perfil)."""

    old: ClassVar[str]
    end_level: ClassVar[float]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        calculation = cls.calculate_in(request("Pista A15", mode="on_axis", layer=rd.AXES_LAYER, surface=A15, profile=A15_PROFILE))
        calculation.confirm_road(mean=True, reason=REASON)
        cls.old = str(calculation.create(decided_by=BY).handle.uid)
        cls.clock.advance(minutes=1)
        cls.end_level = float(core_params.ParameterStore(cls.project).get("des.road.rdw_001.end_level_m", version=cls.v1.uid).value)

    def confirmed_of(self, uid: str) -> Any:
        ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", uid)
        return road_store.confirmed_of(json.loads(settings))

    def test_a_a_steeper_mean_than_the_confirmed_one_is_asked_again_and_leaves_nothing(self) -> None:
        """RF-017-17, D-6, RF-015-23: con la cota de fin 2 m más alta (la media pasa de 10,5 % a ≈ 11,5 %, sin pasar de la pendiente de diseño de 12 %), el recálculo **no confirma por ella**: se rechaza
        al avanzar con ``des.road_mean_unconfirmed``, la operación nueva queda fallida, la anterior sigue vigente y no se escribe ningún dato."""
        self.change("des.road.rdw_001.end_level_m", self.end_level + 2.0)
        written = self.query("SELECT count(*) FROM gb_dataset")
        self.clock.advance(minutes=1)
        handle, work = store.recompute_run(self.request_for(self.old))
        with self.assertRaises(messages.DesignError) as caught:
            finish_steps(work)
        self.assertEqual(caught.exception.code, "des.road_mean_unconfirmed")
        self.assertEqual(self.supersedes(str(handle.uid)), [(self.old, "failed")])
        self.assertEqual(self.current("RDW-001"), self.old)
        self.assertEqual(self.query("SELECT count(*) FROM gb_dataset"), written)

    def test_b_a_milder_mean_reuses_what_was_confirmed_with_its_who_when_and_why(self) -> None:
        """RF-017-17, D-6: con la cota de fin 0,4 m más baja (la media baja a ≈ 10,3 %, entra en lo confirmado) el recálculo **reutiliza la confirmación**: la operación nueva anota en sus ajustes la
        misma decisión —quién, cuándo y el motivo, no otra—, está al día y es la vigente."""
        self.change("des.road.rdw_001.end_level_m", self.end_level - 0.4)
        before = self.confirmed_of(self.old)
        self.assertEqual((before.decided_by, before.reason), (BY, REASON))
        self.clock.advance(minutes=1)
        handle, work = store.recompute_run(self.request_for(self.old))
        finish_steps(work)
        new = str(handle.uid)
        self.assertEqual(self.supersedes(new), [(self.old, "done")])
        self.assertEqual(self.confirmed_of(new), before)
        self.assertEqual(self.current("RDW-001"), new)
        self.assertEqual(self.stale_causes(new), set())
        found = {key: value for key, value, _scope in self.figures_of(new)}
        self.assertLess(found["des.road_gradient_mean_pct"], 10.5)
        self.assertGreater(found["des.road_gradient_mean_pct"], 10.0)


    def test_c_the_carriageway_off_its_level_is_reused_while_it_does_not_grow(self) -> None:
        """RF-017-22, D-6: la calzada que no queda en su rasante por la zona «Sin corte» de las máscaras, confirmada al crear, se **reutiliza** en el recálculo mientras ni su área ni su diferencia
        pasen de lo confirmado (la misma decisión: quién y cuándo); con la rasante 0,6 m más baja (las cotas de inicio y de fin de la entidad) la calzada que pide corte **crece**:
        ``des.road_carriageway_unconfirmed``, la operación nueva queda fallida y la anterior, vigente."""
        calculation = self.calculate_in(request("Pista sin corte", mode="on_axis", layer=NO_CUT_LAYER, surface=rd.dataset_of("rampa_lateral"), feature="Eje sin corte"))
        calculation.confirm_road(carriageway=True)
        old = str(calculation.create(decided_by=BY).handle.uid)
        before = self.confirmed_of(old)
        self.assertGreater(before.carriageway_m2, 0.0)
        self.clock.advance(minutes=1)
        handle, work = store.recompute_run(self.request_for(old))
        finish_steps(work)
        new = str(handle.uid)
        self.assertEqual((self.supersedes(new), self.confirmed_of(new), self.current("RDW-002")), ([(old, "done")], before, new))
        for key in ("start_level_m", "end_level_m"):
            level = float(core_params.ParameterStore(self.project).get(f"des.road.rdw_002.{key}", version=self.v1.uid).value)
            self.change(f"des.road.rdw_002.{key}", level - 0.6)
        self.clock.advance(minutes=1)
        handle, work = store.recompute_run(self.request_for(new))
        with self.assertRaises(messages.DesignError) as caught:
            finish_steps(work)
        self.assertEqual(caught.exception.code, "des.road_carriageway_unconfirmed")
        self.assertEqual((self.supersedes(str(handle.uid)), self.current("RDW-002")), ([(new, "failed")], new))


class RoadRecordedTest(RecomputeCase):
    """RF-013-17, RF-015-02, D-14: lo que leyó el cálculo al prepararse es lo que anotó la operación al empezar."""

    def test_a_a_parameter_changed_between_preparing_and_starting_is_refused(self) -> None:
        """RF-013-17, D-14: si un parámetro (aquí, un valor del perfil) cambia entre prepararla y empezar la operación del recálculo, el resultado ya no le corresponde: ``des.input_changed`` al
        avanzar y antes de escribir nada, la operación nueva queda fallida y la anterior, vigente."""
        stored = self.made(request("Pista de los pasos", mode="on_axis", layer=rd.AXES_LAYER, surface=rd.dataset_of("escalon")))[1]
        old = str(stored.handle.uid)
        real = store.OperationStart.begin
        key = "des.roadprofile.pista_principal.cut_angle_deg"

        def begin(start: Any, project: Any, **options: Any) -> Any:
            self.change(key, 50.0)
            return real(start, project, **options)

        self.clock.advance(minutes=1)
        with mock.patch.object(store.OperationStart, "begin", begin):
            handle, work = store.recompute_run(self.request_for(old))
        written = self.query("SELECT count(*) FROM gb_dataset")
        with self.assertRaises(messages.DesignError) as caught:
            finish_steps(work)
        self.assertEqual((caught.exception.code, caught.exception.values["value"]), ("des.input_changed", key))
        self.assertEqual(self.supersedes(str(handle.uid)), [(old, "failed")])
        self.assertEqual(self.current("RDW-001"), old)
        self.assertEqual(self.query("SELECT count(*) FROM gb_dataset"), written, "no escribió ningún dato")


class OtherDesignTest(QuarryStartCase):
    """RF-017-05 (b), CE-017-05, RF-009-19: los diseños de ``Otra`` (que parten de otra superficie y difieren de la partida de la pista en más del espesor mínimo) son entradas de la pista: si
    **cambian**, queda obsoleta con su causa, se recalcula con lo nuevo y lo congelado se reproduce igual."""

    revision: ClassVar[str]
    uid: ClassVar[str]
    other_uid: ClassVar[str]

    @classmethod
    def road_definition(cls) -> Any:
        return provenance.operation_def(provenance.ROAD, recompute_function, design_reproduce.reproduce_road)

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_families(design_params.ENTITY_FAMILIES)
        cls.enterClassContext(registered(*pop.real_definitions()))
        with cls.project.write_transaction() as conn:  # «Otra» deja de estar obsoleta a mano: aquí la obsolescencia la da el grafo
            conn.execute("DELETE FROM gb_stale")
        asked = request("Pista de la cantera", mode="on_axis", layer=rd.AXES_LAYER, surface="des_exp_cantera")
        calculation = finish(steps.road_run(cls.project, asked, version=cls.v1.uid, masks=cls.masks_v1))
        cls.uid = str(calculation.create(decided_by=BY).handle.uid)
        cls.other_uid = str(cls.query_one("SELECT operation_uid FROM gb_dataset WHERE name = 'des_exp_otra'"))
        cls.clock.advance(minutes=1)
        cls.revision = str(finish_steps(freeze.freeze_steps(cls.project, cls.v1.uid, reason="Entrega de la prueba")).frozen.uid)
        cls.clock.advance(minutes=1)

    @classmethod
    def query_one(cls, sql: str) -> Any:
        with cls.project.read() as conn:
            return conn.execute(sql).fetchone()[0]

    def request_for(self, uid: str) -> Any:
        ((op_type, settings),) = self.query("SELECT op_type, settings FROM gb_operation WHERE uid = ?", uid)
        return recompute_mod.RecomputeRequest(self.project, uid, op_type, json.loads(settings), (), (), version=self.v1.uid)

    def inputs(self, uid: str) -> list[tuple[str, str]]:
        return [(name, role) for name, role in self.query(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in' "
            "AND io.item_kind = 'dataset' ORDER BY io.fid", uid)]

    def outputs(self, uid: str) -> list[tuple[str, str, str, str]]:
        return [tuple(row) for row in self.query(
            "SELECT d.name, d.locator, io.role, d.content_sha256 FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'out' AND io.item_kind = 'dataset' ORDER BY io.fid", uid)]

    def figures_of(self, uid: str) -> dict[str, float]:
        return {key: value for key, value in self.query("SELECT key, value FROM gb_figure WHERE operation_uid = ?", uid)}

    def current(self) -> str:
        entry = entities.registry(self.project, self.v1.uid).get("RDW-001")
        assert entry is not None and entry.operation_uid is not None
        return str(entry.operation_uid)

    def differing(self, uid: str) -> list[str]:
        return [name for name, role in self.inputs(uid) if role == provenance.ROAD_OTHER_DESIGN_ROLE]

    def reproduce(self) -> Any:
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = finish_steps(reproduce_mod.reproduce_steps(self.project, self.revision))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root)), before, "reproducir no escribe en el proyecto")
        return report

    def assert_same(self, report: Any, uid: str) -> None:
        mine = [check for check in report.outputs if check.operation_uid == uid]
        self.assertEqual([(check.role, check.name) for check in mine], [(row[2], row[0]) for row in self.outputs(uid)])
        self.assertEqual(len(mine), 4)
        self.assertTrue(all(check.same for check in mine), [check for check in mine if not check.same])
        found = [check for check in report.figures if check.operation_uid == uid]
        self.assertEqual(len(found), len(self.figures_of(uid)))
        self.assertTrue(found and all(check.same for check in found), [check for check in found if not check.same])
        self.assertNotIn(uid, [note.operation_uid for note in report.not_reproducible])

    def test_a_the_frozen_road_with_other_designs_reproduces_the_same(self) -> None:
        """RF-017-05 (b), RF-009-11, RF-015-02: la pista de la cantera tiene como entradas los dos diseños de ``Otra`` que difieren en su huella (CE-017-05); reproducir ``V01.r1`` —sin proyecto, con la
        capa, la partida, las máscaras y los dos diseños congelados— da de cada dato el **mismo hash** y las mismas cifras, y el informe lleva el aviso de cada diseño (``des_prp_`` coincide
        solo si la reproducción compara con los mismos), sin escribir nada en el proyecto."""
        self.assertEqual(self.differing(self.uid), ["des_exp_otra", "des_fin_otra"])
        report = self.reproduce()
        self.assert_same(report, self.uid)
        notes = [json.loads(note) for _q, _v, _u, note in self.query(
            f'SELECT quantity, value, unit_code, note FROM "{provenance.dataset_locator(provenance.ENTITY_REPORT_TABLE, "Pista de la cantera", "V01")}" WHERE quantity = \'warning\'')]
        self.assertEqual(sorted(item["values"]["other"] for item in notes if item["code"] == "des.road_other_design_differs"), ["des_exp_otra", "des_fin_otra"])

    def test_b_changing_the_other_design_makes_the_road_stale_and_recomputing_reads_the_new_one(self) -> None:
        """RF-017-05 (b), CE-017-05, RF-015-16, RF-009-19: sustituir la cantera ``Otra`` (la explotación pasa a ser igual a la partida de la pista y la final, a 20 m sobre ella) deja la pista obsoleta
        **con su causa** (los dos datos que cambiaron) y «Recalcular lo obsoleto» la repite en la revisión abierta: ya **solo la final** difiere (``des_exp_otra`` deja de ser entrada y de
        avisar), lo congelado no cambia y ``V01.r1`` se reproduce otra vez igual."""
        items = self.query("SELECT * FROM gb_revision_item WHERE revision_uid = ? ORDER BY fid", self.revision)
        self.assertTrue(items)
        frozen = {row[0]: row[3] for row in self.outputs(self.uid)}
        type(self).other_uid = self.write_quarry("Otra", shift=0.0, supersedes=self.other_uid)
        self.assertEqual({name for _kind, name in self.stale_causes(self.uid)}, {"des_exp_otra", "des_fin_otra"})
        self.assertEqual(self.recompute_plan(), [(provenance.ROAD,)])
        self.clock.advance(minutes=1)
        outcome = finish_steps(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results], [recompute_mod.UnitStatus.DONE])
        (made,) = outcome.results[0].operations
        made = str(made)
        (opened,) = self.query("SELECT uid FROM gb_revision WHERE version_uid = ? AND state = 'open'", self.v1.uid)[0]
        self.assertEqual(self.query("SELECT supersedes_uid, revision_uid FROM gb_operation WHERE uid = ?", made), [(self.uid, opened)])
        self.assertEqual(self.query("SELECT revision_uid FROM gb_operation WHERE uid = ?", self.uid), [(self.revision,)])
        self.assertEqual(self.current(), made)
        self.assertEqual(self.differing(made), ["des_fin_otra"])
        self.assertEqual(self.stale_causes(made), set())
        self.assertEqual(self.query("SELECT * FROM gb_revision_item WHERE revision_uid = ? ORDER BY fid", self.revision), items)
        self.assertNotEqual(self.outputs(made)[3][3], frozen[provenance.dataset_name(provenance.ENTITY_REPORT_TABLE, "Pista de la cantera")], "lo vivo cambió: ya no avisa de la explotación de Otra")
        self.assert_same(self.reproduce(), self.uid)


class RoadReproduceTest(RecomputeCase):
    """RF-017-01 a RF-017-03, RF-017-18, RF-015-02, RF-009-11, RF-009-19: las pistas de V01 congeladas en ``V01.r1`` y reproducidas **sin proyecto**: la cadena (destino en una plataforma, origen en el eje de otra
    pista), «sobre un eje» con apoyo, la «opción A15» confirmada y la rampa a una cota (el destino por cota con su zona)."""

    revision: ClassVar[str]
    roads: ClassVar[dict[str, str]]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        chain = cls.build_chain()
        cls.roads = {"RDW-001": str(chain["RDW-001"].handle.uid), "RDW-002": str(chain["RDW-002"].handle.uid)}
        extra = (("Pista sobre un eje", request("Pista sobre un eje", mode="on_axis", layer=rd.AXES_LAYER, surface=rd.dataset_of("escalon"), support=RAMP), {}),
                 ("Pista con cotas", request("Pista con cotas", mode="on_axis", layer=rd.AXES_LAYER, surface=rd.dataset_of("rampa_lateral"), start_level_m=105.0, end_level_m=111.0), {}),
                 ("Pista A15", request("Pista A15", mode="on_axis", layer=rd.AXES_LAYER, surface=A15, profile=A15_PROFILE), {"mean": True, "reason": REASON}),
                 ("Rampa a la cota del fondo", request("Rampa a la cota del fondo", destination=None, dest_level_m=rd.PIT_FLOOR_M, dest_tol_m=0.5,
                                                        dest_zone=f"{rd.ZONES_LAYER}:Zona del fondo", origin="Origen tajo", surface=rd.dataset_of("tajo")), {}))
        for name, asked, confirmed in extra:
            cls.roads[name] = str(cls.made(asked, **confirmed)[1].handle.uid)
        cls.clock.advance(minutes=1)
        cls.revision = str(finish_steps(freeze.freeze_steps(cls.project, cls.v1.uid, reason="Entrega de la prueba")).frozen.uid)
        cls.clock.advance(minutes=1)

    def test_a_reproducing_the_frozen_revision_gives_the_same_without_writing(self) -> None:
        """RF-017-01 a RF-017-03, RF-015-02, RF-009-11: reproducir ``V01.r1`` —sin proyecto, desde las capas, las partidas, las máscaras, los parámetros, las huellas y los ejes de las pistas en que se
        apoyan, congelados— da de cada pista el **mismo hash** de sus cuatro datos (la superficie entera, la huella, el eje por estaciones y el informe) y **las mismas cifras**, sin escribir
        nada en el proyecto (ni ficheros ni el contador de cambios de la base)."""
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

    def test_b_the_origin_on_the_axis_of_another_road_is_a_frozen_input(self) -> None:
        """RF-017-03, RF-015-02: el «Ramal» (``RDW-002``, origen ``RDW-001@100``) lee **el eje por estaciones de la pista** (``des_rdx_``): es una entrada de su operación (papel ``road_axis``), de modo
        que se congela con ella y cambiar el eje deja el ramal obsoleto; las pistas que no salen del eje de otra no la llevan."""
        axis = provenance.dataset_name(provenance.ROAD_AXIS_TABLE, FIRST)
        self.assertIn((axis, provenance.ROAD_AXIS_ROLE), self.inputs(self.roads["RDW-002"]))
        self.assertNotIn(provenance.ROAD_AXIS_ROLE, [role for _name, role in self.inputs(self.roads["RDW-001"])])

    def test_c_the_op_inputs_of_the_level_destination_road_include_its_zone_layer(self) -> None:
        """RF-017-02, D-4: la rampa a una cota consume la capa de la zona del destino (papel ``entity_layer``, como la de los puntos), que es lo que lee su reproducción."""
        names = [name for name, role in self.inputs(self.roads["Rampa a la cota del fondo"]) if role == provenance.ENTITY_LAYER_ROLE]
        self.assertEqual(names, [rd.POINTS_LAYER, rd.ZONES_LAYER])


if __name__ == "__main__":
    import unittest

    unittest.main()
