# SPDX-License-Identifier: GPL-3.0-or-later
"""La corta en el marco de la 015: bancos fijados con la capa, cascada y «apoyo retirado» (spec 018, T25; HU-018-2 y HU-018-5; RF-018-23 y RF-018-24; RF-015-15 a RF-015-17; CE-018-09 y CE-018-10), como
prueba de **hito**: ``check.py --completo`` la ejecuta; el «verde» tiene las suyas, sin proyecto, en ``test_pit_prepare.py`` y ``test_entities_pit_registry.py``.

Sobre el proyecto de las cortas (rejilla de 2 m, 200 × 200 celdas):

- **Los bancos fijados con la capa** (:class:`FixedBenchesTest`, CE-018-09, RF-018-23): el banco 2 fijado como una polilínea de una capa del proyecto se usa **tal cual** (la Z exacta, el hash de la capa igual antes
  y después de crear y de recalcular); la capa **editada** en QGIS deja la corta obsoleta **con su causa** y «Recalcular lo obsoleto» la rehace con la línea nueva.
- **La cascada** (:class:`CascadeTest`, CE-018-10, RF-015-15 a RF-015-17): la corta, una plataforma que parte de su superficie, una pista que parte de la de la plataforma y otra corta que **declara** que se apoya
  en la primera: cambiar el perfil de la primera las deja obsoletas en cascada con su causa y se recalculan en orden; descartarla da **una sola lista** de lo que se apoyaba en ella, las deja «apoyo retirado» y fuera
  de «Recalcular lo obsoleto»; la que solo **declara** el apoyo se da por buena sin él (``released``: sin sus entradas, con su motivo y su decisor, los mismos datos) y la que parte de su superficie, no.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

import numpy as np

from tests.support import pit_data as pd
from tests.support import road_data as rd
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.unit.design import milestone_pit_prepare_checks as checks
from tests.unit.design import milestone_road_recompute as road_recompute
from tests.unit.design import test_platform_operation as pop
from tests.unit.design.milestone_pit_create import BY, NAME
from tests.unit.design.milestone_pit_prepare_checks import CODE, request
from tests.unit.design.milestone_pit_recompute import FACE, RecomputeCase, finish_steps
from tests.unit.design.test_road_prepare import request as road_request

core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
design_reproduce = import_geoblender("design.reproduce")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
freeze = import_geoblender("core.versions.freeze")
gstore = import_geoblender("gis.store")
breaklines = import_geoblender("gis.breaklines")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
pit_lines = import_geoblender("design.pit_lines")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
reproduce_mod = import_geoblender("core.versions.reproduce")
road_model = import_geoblender("design.road_model")
steps = import_geoblender("design.steps")
store = import_geoblender("design.store")

DesignError = messages.DesignError
State = entities.EntityState
Status = recompute_mod.UnitStatus
FIXED_LAYER = "gis_brk_corta_banco_2"
WHY = "La corta se rehace con otro perfil"
GOOD = "La segunda corta ya está hecha y no se rehace"
PLATFORM, ROAD, SECOND_PIT = "Plataforma sobre la corta", "Pista sobre la plataforma", "Corta que se apoya en la primera"
PLATFORM_LAYER, AXIS_LAYER = "gis_fea_corta_plataformas", "gis_fea_corta_ejes"
SUPPORTS = "des.pit.pit_002.supports"


def surface_of(name: str) -> str:
    return provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, name)


def rewrite_breakline(project: Any, clock: Any, name: str, line: np.ndarray, *, move: float) -> None:
    """Edita la capa de líneas con Z ``name`` como en QGIS: su única línea ``line`` (absoluta, con Z) desplazada ``move`` m al este, registrada otra vez (el mismo dato, con otro contenido)."""
    contract = import_geoblender("core.provenance.contract")
    operations = import_geoblender("core.provenance.operations")
    datasets = import_geoblender("core.datasets")
    builtin = import_geoblender("core.content.builtin")
    from tests.support import design_fixtures as dfx

    srs = int(project.record.crs_epsg)
    line = np.array(line, dtype=np.float64, copy=True)
    line[:, 0] += move
    (row,) = gstore.breakline_rows([breaklines.Breakline("S1", line)], srs)
    writer = contract.OperationDef(dfx.LAYERS_TYPE, "1.0", "gis", "Layers of the tests", False)
    with registered(writer):
        clock.advance(minutes=1)
        handle = operations.begin_operation(project, dfx.LAYERS_TYPE, settings={"name": name}, executor="blender")
        with project.write_transaction() as conn:
            conn.execute(f'UPDATE "{name}" SET geom = ? WHERE fid = 1', (row[0],))
            handle.complete(conn, outputs=(datasets.DatasetSpec(name, "gis", "vector", datasets.Store.GPKG, name, reader=builtin.GPKG_LAYER.id, role="features", crs_epsg=srs, input_uid=None,
                                                                immutable=False),), message="Capa de bancos fijados editada")


class CascadeCase(RecomputeCase):
    """Lo de ``RecomputeCase`` de las cortas con los tipos de las entidades (la plataforma, la capa de entidades) y la pista registrados con sus funciones **reales** de recalcular y reproducir."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_families(design_params.ENTITY_FAMILIES)
        core_params.register_families(design_params.ROAD_FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        cls.enterClassContext(registered(*pop.real_definitions(), provenance.operation_def(provenance.ROAD, road_recompute.recompute_function, design_reproduce.reproduce_road),
                                         provenance.operation_def(provenance.ROAD_LAYER, road_recompute.recompute_function), *provenance.ROAD_FIGURES))

    def inputs_of(self, uid: str) -> list[tuple[str, str]]:
        return self.inputs(uid)

    def settings_of(self, uid: str) -> dict[str, Any]:
        ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", uid)
        return dict(json.loads(settings))

    def states_now(self) -> dict[str, Any]:
        registry = entities.registry(self.project, self.v1.uid)
        return {entry.record.code: entry.record.state for entry in registry}


class FixedBenchesTest(CascadeCase):
    """RF-018-23, RF-018-24, CE-018-09: el banco 2 fijado como una polilínea con Z de una capa del proyecto. **En orden** (``test_a`` y ``test_b``)."""

    foot: ClassVar[Any]
    pit: ClassVar[str]
    layer_hash: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.clock.advance(minutes=1)
        cls.uid(cls, cls.calculate(cls, request()).create(decided_by=BY))
        with cls.project.read() as conn:  # el pie del banco 2 de la primera corta, como línea de rotura con Z
            lines = pit_lines.read_pit_lines(conn, provenance.dataset_locator(provenance.PIT_POLYLINES_TABLE, NAME, "V01"), provenance.PIT_POLYLINES_TABLE, closed_column="closed")
        cls.foot = next(line for line in lines if (line.values[0], line.values[1]) == (2, "foot")).points
        sdata.write_breaklines(cls.project, cls.clock, FIXED_LAYER, [np.vstack([cls.foot, cls.foot[:1]])])
        cls.clock.advance(minutes=1)
        cls.layer_hash = cls.hashes(cls, FIXED_LAYER)
        cls.pit = cls.uid(cls, cls.calculate(cls, request("Corta con banco fijado", start="gis_dtm_corta_llano_c", fixed=road_model.LayerFields(FIXED_LAYER, "line_id"))).create(decided_by=BY))

    def test_a_the_fixed_line_is_used_as_it_is_and_the_layer_is_not_modified(self) -> None:
        """RF-018-23, CE-018-09, principio 7: la polilínea fijada es el pie del banco 2 **tal cual** (los mismos vértices, la Z exacta a ≤ 10⁻⁹ m) y la capa es una **entrada** de la corta (``entity_layer``);
        el hash de la capa es el mismo antes y después de crear."""
        self.assertEqual(self.hashes(FIXED_LAYER), self.layer_hash)
        self.assertIn((FIXED_LAYER, provenance.ENTITY_LAYER_ROLE), self.inputs(self.pit))
        with self.project.read() as conn:
            lines = pit_lines.read_pit_lines(conn, provenance.dataset_locator(provenance.PIT_POLYLINES_TABLE, "Corta con banco fijado", "V01"), provenance.PIT_POLYLINES_TABLE,
                                             closed_column="closed")
        used = next(line for line in lines if (line.values[0], line.values[1]) == (2, "foot")).points
        mine, given = sorted(map(tuple, np.unique(used, axis=0))), sorted(map(tuple, np.unique(self.foot, axis=0)))
        self.assertEqual(len(mine), len(given))
        np.testing.assert_allclose(np.array(mine), np.array(given), rtol=0.0, atol=1e-9)

    def test_b_the_edited_layer_makes_the_pit_stale_with_its_cause_and_recomputing_uses_the_new_line(self) -> None:
        """RF-018-23, RF-015-16, CE-018-09: la capa **editada** en QGIS (la línea 2 m al este) deja la corta obsoleta con su causa (el dato de la capa); «Recalcular lo obsoleto» la rehace con la línea
        nueva (otro dato) y no toca la capa."""
        old = self.current("PIT-002")
        self.assertEqual(self.stale_causes(old), set())
        rewrite_breakline(self.project, self.clock, FIXED_LAYER, np.vstack([self.foot, self.foot[:1]]), move=2.0)
        edited = self.hashes(FIXED_LAYER)
        self.assertNotEqual(edited, self.layer_hash)
        self.assertEqual(self.stale_causes(old), {("dataset_changed", FIXED_LAYER)})
        self.assertEqual(self.stale_causes(self.current("PIT-001")), set(), "la primera corta no la lee")
        self.clock.advance(minutes=1)
        made = self.recompute_all()
        self.assertEqual(len(made), 1)
        self.assertEqual(self.current("PIT-002"), made[0])
        self.assertEqual(self.stale_causes(made[0]), set())
        self.assertEqual(self.hashes(FIXED_LAYER), edited, "recalcular no modifica la capa")
        self.assertEqual(self.recompute_plan(), [])


class CascadeTest(CascadeCase):
    """RF-015-15 a RF-015-17, RF-018-03, CE-018-10: la corta, la plataforma que parte de su superficie, la pista que parte de la de la plataforma y otra corta que **declara** que se apoya en la primera.
    **En orden** (``test_a`` a ``test_e``): cada una parte de lo que dejó la anterior."""

    chain: ClassVar[dict[str, str]]
    revision: ClassVar[str]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.clock.advance(minutes=1)
        cls.chain = {CODE: cls.uid(cls, cls.calculate(cls, request()).create(decided_by=BY))}
        line = ((pd.absolute([(160.0, 200.0), (240.0, 200.0)], checks.GRID),),)
        axis = ((pd.absolute([(165.0, 210.0), (235.0, 210.0)], checks.GRID),),)
        sdata.write_layer(cls.project, cls.clock, sdata.FieldsLayer(PLATFORM_LAYER, "line", (line,), (PLATFORM,), {"ancho": (10.0,), "cota_inicial": (pd.FLOOR_Z_M + 1.0,), "pendiente": (0.0,)}))
        sdata.write_layer(cls.project, cls.clock, sdata.FieldsLayer(AXIS_LAYER, "line", (axis,), (ROAD,), {}))
        cls.clock.advance(minutes=1)
        fields = model.PlatformFields(layer=PLATFORM_LAYER, start_level_field="cota_inicial", gradient_field="pendiente", width_field="ancho")
        asked = model.PlatformRequest(PLATFORM, fields, PLATFORM, "entity:PIT-001", mode="cut_fill", edge_angle_deg=35.0, reach_m=10.0)
        cls.chain["PLT-001"] = str(pop.finish(steps.platform_run(cls.project, asked, masks=cls.masks_v1, version=cls.v1.uid)).create(decided_by=BY).handle.uid)
        cls.clock.advance(minutes=1)
        cls.chain["RDW-001"] = cls.uid(cls, cls.road(cls, road_request(ROAD, mode="on_axis", layer=AXIS_LAYER, surface="entity:PLT-001", feature=ROAD)))
        sdata.write_layer(cls.project, cls.clock, checks.layer("gis_fea_corta_fondos_2", [[pd.circle_ring(30.0, center=(330.0, 330.0))]], ["Fondo 2"], cota_m=[pd.FLOOR_Z_M + 40.0]))
        cls.clock.advance(minutes=1)
        cls.chain["PIT-002"] = cls.uid(cls, cls.calculate(cls, request(SECOND_PIT, source="gis_fea_corta_fondos_2", start="gis_dtm_corta_llano_c")).create(decided_by=BY))
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:  # lo que la persona declara en la segunda corta: se apoya en la primera
            entity_store.set_entity_params(cls.project, (entity_store.EntityParamRow(SUPPORTS, "supports", CODE, "Declarado por la persona", "person", "La segunda corta se apoya en la primera"),),
                                           version=cls.v1.uid, decided_by=BY, conn=conn)

    def type_of(self, uid: str) -> str:
        return str(self.query("SELECT op_type FROM gb_operation WHERE uid = ?", uid)[0][0])

    def road(self, asked: Any) -> Any:
        found = None
        for step in steps.road_run(self.project, asked, version=self.v1.uid, masks=self.masks_v1):
            found = step.result
        return found.create(decided_by=BY)

    def test_a_the_chain_is_there(self) -> None:
        """CE-018-10: la cadena de la prueba: las cuatro entidades al día."""
        self.assertEqual(self.states_now(), {"PIT-001": State.CURRENT, "PLT-001": State.CURRENT, "RDW-001": State.CURRENT, "PIT-002": State.CURRENT})

    def test_b_the_declared_support_is_read_and_the_pit_rests_on_the_other(self) -> None:
        """RF-015-15, RF-018-03: la segunda corta **declara** que se apoya en la primera (``supports``): al recalcularla **lee** ese parámetro y anota como entradas la superficie de la primera
        (``supported_on``) y la tabla de su huella (``support_footprint``); lo que se apoya en la primera es **una sola lista**: la plataforma que parte de su superficie y la segunda corta."""
        old = self.current("PIT-002")
        self.assertNotIn((surface_of(NAME), provenance.SUPPORTED_ON_ROLE), self.inputs(old))
        self.clock.advance(minutes=1)
        handle, work = store.recompute_run(self.request_for(old))
        finish_steps(work)
        new = str(handle.uid)
        self.assertEqual(self.current("PIT-002"), new)
        mine = self.inputs(new)
        self.assertIn((surface_of(NAME), provenance.SUPPORTED_ON_ROLE), mine)
        self.assertIn((provenance.dataset_name(provenance.ENTITY_TABLE, NAME), provenance.SUPPORT_FOOTPRINT_ROLE), mine)
        read = {key for (key,) in self.query("SELECT key FROM gb_operation_param WHERE operation_uid = ?", new)}
        self.assertIn(SUPPORTS, read)
        found = entities.dependents(self.project, self.v1.uid, CODE)
        self.assertEqual({row.entity for row in found}, {"PLT-001", "PIT-002"})
        self.assertEqual(self.stale_causes(new), set())

    def test_c_changing_the_profile_makes_the_chain_stale_in_cascade_and_recomputing_repeats_it_in_order(self) -> None:
        """RF-015-16, RF-018-03, CE-018-10: cambiar el ángulo de cara del perfil de la corta deja obsoletas en cascada **con su causa** la corta, la plataforma que parte de su superficie, la pista que parte de
        la de la plataforma y la segunda corta; «Recalcular lo obsoleto» las repite **en orden** (la corta, primero) y todas quedan al día."""
        first = self.current(CODE)
        self.change(FACE, 50.0)
        self.assertIn(("parameter_changed", FACE), self.stale_causes(first))
        for code in ("PLT-001", "RDW-001", "PIT-002"):
            self.assertTrue(self.stale_causes(self.current(code)), code)
        plan = self.recompute_plan()
        self.assertEqual(plan[0], (provenance.PIT,))
        self.assertEqual(sorted(item for unit in plan for item in unit), sorted([provenance.PIT, provenance.PLATFORM, provenance.ROAD, provenance.PIT]))
        self.clock.advance(minutes=1)
        outcome = finish_steps(recompute_mod.recompute_steps(self.project))
        made = [str(uid) for result in outcome.results for uid in result.operations]
        self.assertEqual([self.type_of(uid) for uid in made[:3]], [provenance.PIT, provenance.PLATFORM, provenance.ROAD], "en el orden de la cadena: la corta, la plataforma y la pista")
        self.assertEqual(self.current(CODE), made[0])
        for _ in range(3):  # la segunda corta no depende de la pista, pero la pista cuenta su superficie como la de otro diseño: se asienta en otra pasada
            if not self.recompute_plan():
                break
            self.clock.advance(minutes=1)
            self.recompute_all()
        self.assertEqual(self.recompute_plan(), [])
        for code in ("PIT-001", "PLT-001", "RDW-001", "PIT-002"):
            self.assertEqual(self.stale_causes(self.current(code)), set(), code)
        self.assertEqual(self.states_now(), {"PIT-001": State.CURRENT, "PLT-001": State.CURRENT, "RDW-001": State.CURRENT, "PIT-002": State.CURRENT})

    def test_d_discarding_the_pit_lists_what_rested_on_it_and_leaves_them_with_the_support_removed(self) -> None:
        """RF-015-17, CE-018-10: descartar la corta da **una sola lista** de lo que se apoyaba en ella (la misma de ``entities.dependents``), deja la plataforma y la segunda corta **«apoyo retirado»** (con su
        causa, en español y en inglés) y fuera de «Recalcular lo obsoleto», que no las rehace; solo la segunda, que **declara** el apoyo sin partir de su superficie, se puede dar por buena."""
        plan = entity_store.discard_plan(self.project, self.v1.uid, CODE)
        self.assertEqual({row.entity for row in plan.dependents}, {"PLT-001", "PIT-002"})
        self.assertEqual(plan.dependents, entities.dependents(self.project, self.v1.uid, CODE))
        self.clock.advance(minutes=1)
        found = entity_store.discard_entity(self.project, self.v1.uid, CODE, reason=WHY, decided_by=BY)
        self.assertEqual({row.entity for row in found.dependents}, {"PLT-001", "PIT-002"})
        states = self.states_now()
        self.assertEqual((states[CODE], states["PLT-001"], states["PIT-002"]), (State.DISCARDED, State.SUPPORT_REMOVED, State.SUPPORT_REMOVED))
        for code in ("PLT-001", "PIT-002"):
            self.assertEqual(entities.stale_reason(self.project, self.v1.uid, code), f"Apoyo retirado: se descartó la corta «{NAME}»", code)
        retired = {row.entity: row for row in entities.retired_supports(self.project, self.v1.uid)}
        self.assertEqual((retired["PLT-001"].releasable, retired["PIT-002"].releasable), (False, True))
        before = self.query("SELECT uid FROM gb_operation ORDER BY fid")
        self.clock.advance(minutes=1)
        outcome = finish_steps(recompute_mod.recompute_steps(self.project))
        self.assertEqual(sum(len(result.operations) for result in outcome.results if result.status is Status.DONE), 0, "no rehace lo que perdió su apoyo")
        self.assertEqual(self.query("SELECT uid FROM gb_operation ORDER BY fid"), before)

    def test_e_the_pit_that_only_declares_the_support_is_given_as_good_and_the_one_that_starts_from_it_is_not(self) -> None:
        """RF-015-17, A7, P-6, CE-018-10: «dar por buena» la segunda corta (``released``) la repite **sin** las entradas de la corta descartada (ni su superficie ni la tabla de su huella), con el motivo y quién en
        sus ajustes (``supports_released``) y **los mismos datos**; vuelve a estar al día; un recálculo después no vuelve a pedir lo declarado en la descartada; la plataforma, que parte de su superficie, no se
        puede dar por buena (``des.entity_release_start``)."""
        with self.assertRaises(DesignError) as caught:
            entity_store.release_support(self.project, self.v1.uid, "PLT-001", CODE, reason=GOOD, decided_by=BY)
        self.assertEqual(caught.exception.code, "des.entity_release_start")
        old = self.current("PIT-002")
        self.assertIn(surface_of(NAME), [name for name, _role in self.inputs(old)])
        mine = tuple(provenance.dataset_name(family, SECOND_PIT) for family in (provenance.ENTITY_SURFACE_GRID, provenance.ENTITY_TABLE))
        hashes = self.hashes(*mine)
        self.clock.advance(minutes=1)
        handle, work = entity_store.release_support(self.project, self.v1.uid, "PIT-002", CODE, reason=GOOD, decided_by=BY)
        finish_steps(work)
        new = str(handle.uid)
        self.assertEqual(self.current("PIT-002"), new)
        self.assertEqual(self.states_now()["PIT-002"], State.CURRENT)
        (given,) = provenance.released_supports(self.settings_of(new))
        self.assertEqual((given.entity, given.reason, given.by), (CODE, GOOD, BY))
        names = [name for name, _role in self.inputs(new)]
        self.assertNotIn(surface_of(NAME), names)
        self.assertNotIn(provenance.dataset_name(provenance.ENTITY_TABLE, NAME), names)
        self.assertEqual(self.hashes(*mine), hashes, "su salida no cambia")
        self.clock.advance(minutes=1)
        again, work = store.recompute_run(self.request_for(new))
        finish_steps(work)
        self.assertNotIn(surface_of(NAME), [name for name, _role in self.inputs(str(again.uid))])
        self.assertEqual([item.entity for item in provenance.released_supports(self.settings_of(str(again.uid)))], [CODE])


class TwoPitsTest(CascadeCase):
    """RF-015-16, RF-018-03, RF-017-05 (b): dos cortas sobre el mismo fondo y terrenos distintos. La segunda anota la superficie de la primera como otro diseño (entrada); recalcular la **primera** no anota
    la de la segunda (depende de ella: un bucle que no se asienta) y las dos quedan al día."""

    def test_recomputing_the_first_does_not_make_it_depend_on_the_second(self) -> None:
        """RF-015-16: tras crear las dos y cambiar el perfil de la primera, «Recalcular lo obsoleto» deja las dos **al día** en una sola pasada y la primera **no** consume la superficie de la segunda."""
        self.clock.advance(minutes=1)
        self.uid(self.calculate(request()).create(decided_by=BY))
        self.clock.advance(minutes=1)
        second = self.uid(self.calculate(request(SECOND_PIT, start="gis_dtm_corta_llano_c")).create(decided_by=BY))
        self.assertIn((surface_of(NAME), provenance.ROAD_OTHER_DESIGN_ROLE), self.inputs(second), "la segunda anota la primera como otro diseño")
        self.change(FACE, 50.0)
        self.clock.advance(minutes=1)
        self.recompute_all()
        self.assertEqual(self.recompute_plan(), [])
        self.assertNotIn(surface_of(SECOND_PIT), [name for name, _role in self.inputs(self.current(CODE))])
        for code in ("PIT-001", "PIT-002"):
            self.assertEqual(self.stale_causes(self.current(code)), set(), code)
