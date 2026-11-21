# SPDX-License-Identifier: GPL-3.0-or-later
"""«Crear» la pista con el proyecto: la operación, los datos, la huella y las dependencias (spec 017, T21; HU-017-1; RF-017-01, RF-017-03, RF-017-05, RF-017-17, RF-017-22, RF-017-23; RF-015-01, RF-015-02,
RF-015-04, RF-015-10, RF-015-12, RF-015-15, RF-015-27 y RF-015-29; RNF-017-07 y RNF-017-10; plan 017 §5.2.3, §5.3.2, §5.7 P-1 y P-5; D-15 y D-16), como prueba de **hito**: ``check.py --completo`` la
ejecuta; el «verde» tiene las suyas, sin proyecto, en ``test_road_operation.py`` (:class:`RoadRowsTest`).

Sobre la copia del proyecto de las pistas (rejilla de 2 m, 200 × 200 celdas) con las máscaras de V01 y el perfil de referencia (**solo de las pruebas**):

- **La cadena P1 → pista → ramal** (:class:`RoadChainTest`, la de la fixture): la plataforma ``P1`` (``PLT-001``, de la 015), la «Pista a P1» (``RDW-001``: parte de la superficie de P1 y llega a su huella, así que
  **se apoya en ella**: el destino en una entidad) y el «Ramal» (``RDW-002``: parte de la superficie de la pista y su origen es **el eje de la pista**, ``RDW-001@100``: se apoya en ella), y la «Relleno
  sobre la calzada», una plataforma que rellena después **sobre la calzada de la pista** y se apoya en ella con su volumen (RF-015-15). «Crear» es **una transacción** con la superficie entera, la huella
  de la sección, el eje por estaciones y el informe, las cifras con el ámbito de la entidad, los parámetros de la entidad con su origen, las entradas con su papel y **ninguna declaración**
  (RF-017-01: la pista no declara restricción alguna). La huella sale en la capa de entidades y el eje de la pista es lo que lee la pista que parte de él.
- **Lo confirmado** (:class:`ConfirmedRoadTest`, RF-017-17 y RF-017-22): la «opción A15» (10,5 % de media frente al 10 % del perfil) se crea con la confirmación y su motivo, que quedan en los ajustes con
  quién y cuándo; sin ella no se crea y no queda nada; cerrar la creación a mitad no deja nada.
- **Lo que cambió desde que se calculó** (:class:`ChangedInputTest`, RF-015-02, principio 7): la capa de origen editada entre «Calcular» y «Crear» deja ``des.input_changed`` y nada escrito.
- **Los otros diseños** (:class:`OtherDesignsCreateTest`, RF-017-05 (b), CE-017-05): los que difieren en la huella son **entradas de la pista con su hash**; si ninguno difiere, no se registra nada.
"""

from __future__ import annotations

import json
import time
from typing import Any, ClassVar

import numpy as np

from tests.support import road_data as rd
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.versions_fixtures import change_counter
from tests.unit.design import test_platform_prepare as prep
from tests.unit.design.milestone_access_operation import rewrite_layer
from tests.unit.design.milestone_road_calculate import A15, A15_PROFILE, CalculateCase
from tests.unit.design.milestone_road_prepare import QuarryStartCase
from tests.unit.design.test_platform_operation import finish
from tests.unit.design.test_road_prepare import BY, GRID, RAMP, drive, request

core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
provenance = import_geoblender("design.provenance")
road_store = import_geoblender("design.road_store")
steps = import_geoblender("design.steps")
store = import_geoblender("design.store")
surfaces = import_geoblender("design.surfaces")

PLATFORM, PLATFORM_CODE = "P1", "PLT-001"
FILL = "Relleno sobre la calzada"
FIRST, SECOND = "Pista a P1", "Ramal"
PLATFORM_LAYER = "gis_fea_pistas_a_p1"
"""La capa de puntos de la pista a P1: «Entrada» (el origen de la rampa), «En P1» (el único que cae en la huella de la plataforma) y «Fuera de P1»."""
FAMILIES = (provenance.ENTITY_SURFACE_GRID, provenance.ENTITY_TABLE, provenance.ROAD_AXIS_TABLE, provenance.ENTITY_REPORT_TABLE)
ROLES = ("entity_surface", "entity", "road_axis", "entity_report")
THICKNESS_M = 0.05
"""El espesor mínimo de la 012 (``res.verify.min_thickness_m``) del proyecto de pruebas."""
REASON = "Opción A15 de la propiedad (N-15)"


def first_request(**changes: Any) -> Any:
    """La «Pista a P1»: de «Entrada» al punto de la capa que cae en la huella de ``PLT-001``, partiendo de la superficie de la plataforma."""
    return request(FIRST, layer=PLATFORM_LAYER, origin="Entrada", destination=f"entity:{PLATFORM_CODE}", surface=f"entity:{PLATFORM_CODE}", **changes)


def second_request(**changes: Any) -> Any:
    """El «Ramal»: del eje de la pista a la abscisa 100 m (``RDW-001@100``) al «Destino del ramal», partiendo de la superficie de la pista."""
    return request(SECOND, layer=rd.POINTS_LAYER, origin="RDW-001@100", destination="Destino del ramal", surface="entity:RDW-001", **changes)


class CreateCase(CalculateCase):
    """Lo de ``CalculateCase`` (el proyecto de las pistas en 2 m con sus máscaras y perfiles) más los tipos de las entidades de la 015 y las ayudas para calcular y crear."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_families(design_params.ENTITY_FAMILIES)
        cls.enterClassContext(registered(*cls.entity_definitions()))

    @classmethod
    def entity_definitions(cls) -> tuple[Any, ...]:
        """Los tipos de las entidades de la 015 tal como los registra la clase (sin recalcular ni reproducir); ``milestone_road_recompute`` (T22) los cambia por los de las funciones reales."""
        return prep.entity_definitions()

    @classmethod
    def calculate_in(cls, asked: Any, **options: Any) -> Any:
        """«Calcula» ``asked`` en V01 (un minuto después de lo anterior): la ``Calculation`` (nada registrado)."""
        options.setdefault("masks", cls.masks_v1)
        options.setdefault("version", cls.v1.uid)
        cls.clock.advance(minutes=1)
        return finish(steps.road_run(cls.project, asked, **options))

    @classmethod
    def made(cls, asked: Any, **confirmed: Any) -> tuple[Any, Any]:
        """«Calcula» y «Crea» ``asked`` en V01 (con lo que se confirme): la ``Calculation`` y lo guardado."""
        calculation = cls.calculate_in(asked)
        if confirmed:
            calculation.confirm_road(**confirmed)
        stored = calculation.create(decided_by=BY)
        cls.clock.advance(minutes=1)
        return calculation, stored

    @classmethod
    def hashes(cls, *names: str) -> dict[str, tuple[str, ...]]:
        """El hash de contenido (y el estado) del dato vigente de cada ``names`` en el registro."""
        with cls.project.read() as conn:
            return {name: tuple(conn.execute("SELECT content_sha256, status FROM gb_dataset WHERE name = ? AND status = 'current'", (name,)).fetchone()) for name in names}

    def outputs(self, uid: str) -> list[tuple[str, str, str, str]]:
        """Lo que escribió la operación ``uid``: ``(nombre, ubicación, papel, hash)`` de cada dato, en su orden."""
        return [tuple(row) for row in self.query(
            "SELECT d.name, d.locator, io.role, d.content_sha256 FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'out' AND io.item_kind = 'dataset' ORDER BY io.fid", uid)]

    def inputs(self, uid: str) -> list[tuple[str, str]]:
        """Lo que consumió la operación ``uid``: ``(nombre, papel)`` de cada dato, en su orden."""
        return [(name, role) for name, role in self.query(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in' "
            "AND io.item_kind = 'dataset' ORDER BY io.fid", uid)]

    def figures_of(self, uid: str) -> list[tuple[str, float, dict[str, Any]]]:
        """Las cifras que registró la operación ``uid``: ``(clave, valor, ámbito)``, en su orden."""
        return [(key, value, json.loads(scope)) for key, scope, value in self.query("SELECT key, scope, value FROM gb_figure WHERE operation_uid = ? ORDER BY fid", uid)]

    def table(self, name: str, family: str) -> list[dict[str, Any]]:
        """Las filas de la tabla ``family`` de la pista ``name`` de V01, por el nombre de cada columna."""
        names = [column.name for column in store.columns_of(provenance.ROAD, family)]
        found = self.query(f'SELECT {", ".join(names)} FROM "{provenance.dataset_locator(family, name, "V01")}" ORDER BY fid')
        return [dict(zip(names, row, strict=True)) for row in found]

    def grid_of(self, name: str) -> np.ndarray:
        """La rejilla del dato ``name`` de V01 tal como está en el proyecto."""
        return drive(surfaces.read_surface_steps(self.project, name, version_uid=self.v1.uid)).values

    def current(self, code: str) -> str:
        """El uid de la operación vigente de la entidad ``code`` de V01 (el registro de las entidades)."""
        entry = entities.registry(self.project, self.v1.uid).get(code)
        assert entry is not None and entry.operation_uid is not None, code
        return str(entry.operation_uid)


class RoadChainTest(CreateCase):
    """RF-017-01, RF-017-03, RF-017-23, RF-015-01, RF-015-02, RF-015-04, RF-015-10, RF-015-12, RF-015-15, D-15, D-16: la cadena P1 → «Pista a P1» → «Ramal» y el relleno sobre la calzada, creados una vez en V01."""

    first: ClassVar[Any]
    second: ClassVar[Any]
    first_stored: ClassVar[Any]
    second_stored: ClassVar[Any]
    fill_stored: ClassVar[Any]
    counters: ClassVar[tuple[int, int]]
    inputs_before: ClassVar[dict[str, Any]]
    seconds: ClassVar[float]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        fields = model.PlatformFields(layer=rd.PLATFORMS_LAYER, start_level_field="cota_inicial", gradient_field="pendiente", width_field="ancho")
        cls.clock.advance(minutes=1)
        platform = finish(steps.platform_run(cls.project, model.PlatformRequest(PLATFORM, fields, PLATFORM, RAMP, edge_angle_deg=35.0, reach_m=20.0), masks=cls.masks_v1, version=cls.v1.uid))
        platform.create()
        points = (("Entrada", rd.RAMP_ORIGIN), ("En P1", (320.0, 200.0)), ("Fuera de P1", (200.0, 100.0)))
        sdata.write_layer(cls.project, cls.clock, sdata.FieldsLayer(PLATFORM_LAYER, "point", tuple(((rd.absolute([point], GRID),),) for _name, point in points), tuple(name for name, _ in points), {}))
        cls.clock.advance(minutes=1)
        cls.inputs_before = cls.hashes(PLATFORM_LAYER, rd.POINTS_LAYER, provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, PLATFORM))
        before = change_counter(cls.root)
        started = time.perf_counter()
        cls.first, cls.first_stored = cls.made(first_request())
        cls.seconds = time.perf_counter() - started
        cls.counters = (before, change_counter(cls.root))
        cls.second, cls.second_stored = cls.made(second_request())
        relleno = model.PlatformRequest(FILL, fields, FILL, "entity:RDW-002", mode="cut_fill", edge_angle_deg=35.0, reach_m=20.0)
        cls.fill_stored = finish(steps.platform_run(cls.project, relleno, masks=cls.masks_v1, version=cls.v1.uid)).create()
        cls.clock.advance(minutes=1)

    def uid(self, which: Any) -> str:
        return str(which.handle.uid)

    def test_a_creating_writes_one_done_operation_with_the_four_data_of_a_road(self) -> None:
        """RF-017-01, RF-015-02: «Crear» deja **una** operación ``des.road`` hecha en V01 con los cuatro datos de su tipo —la superficie entera, la huella de la sección, el eje por estaciones y el
        informe—, cada uno con su nombre, su ubicación (con el código de la versión) y el papel con que lo leen la 012, R-44 y la pista que parte de su eje; la ``Calculation`` queda creada."""
        found = self.outputs(self.uid(self.first_stored))
        self.assertEqual([row[0] for row in found], [provenance.dataset_name(family, FIRST) for family in FAMILIES])
        self.assertEqual([row[2] for row in found], list(ROLES))
        self.assertEqual([row[1] for row in found], [provenance.dataset_locator(family, FIRST, "V01") for family in FAMILIES])
        self.assertTrue((self.root / found[0][1]).is_file())
        self.assertEqual(self.query("SELECT op_type, scope, status FROM gb_operation WHERE uid = ?", self.uid(self.first_stored)), [(provenance.ROAD, "version", "done")])
        self.assertEqual((self.first.op_type, self.first.open), (provenance.ROAD, False))
        self.assertEqual(self.first_stored.handle.op_type, provenance.ROAD)
        self.assertEqual(len(self.first_stored.records), 4)
        with self.assertRaises(RuntimeError):
            self.first.create()

    def test_b_the_data_are_what_was_computed(self) -> None:
        """RF-017-23, RF-015-01, RF-015-02: la superficie guardada es **la entera**: la de partida con la ventana de trabajo sustituida por el resultado (bit a bit); la huella, el eje por estaciones y
        el informe son lo que dicen las funciones puras del resultado (``road_entity_rows``, ``road_axis_rows`` y ``road_report_rows``, las mismas que repite la reproducción); la huella es la de la sección
        (el área de sus celdas es la cifra ``des.road_area_m2``)."""
        outcome, prepared = self.first.outcome, self.first.entity
        np.testing.assert_array_equal(self.grid_of(provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, FIRST)), outcome.compose(prepared.job.start))
        (row,) = self.table(FIRST, provenance.ENTITY_TABLE)
        expected = road_store.road_entity_rows(prepared.job, outcome, fid=prepared.fid, start_surface=prepared.start_surface, support_surface=prepared.support_surface)
        self.assertEqual(tuple(row.values()), expected[0])
        self.assertEqual((row["code"], row["kind"], row["layer"], row["source_fid"], row["mode"]), ("RDW-001", "road", PLATFORM_LAYER, 1, "trace"))
        self.assertEqual(row["start_surface"], provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, PLATFORM))
        self.assertEqual(row["cells"] * GRID.cell_area, {key: value for key, value, _scope in self.figures_of(self.uid(self.first_stored))}["des.road_area_m2"])
        axis = self.table(FIRST, provenance.ROAD_AXIS_TABLE)
        self.assertEqual([tuple(item.values()) for item in axis], road_store.road_axis_rows(outcome))
        self.assertEqual(len(axis), len(outcome.axis.stations))
        report = self.table(FIRST, provenance.ENTITY_REPORT_TABLE)
        self.assertEqual([tuple(item.values()) for item in report], road_store.road_report_rows(outcome))

    def test_c_the_figures_are_registered_with_the_scope_of_the_entity(self) -> None:
        """RF-017-23, RF-015-13: las cifras CALCULADO de la pista quedan registradas con su unidad y el ámbito de la entidad (su nombre y su código), las que calculó «Calcular», más
        ``des.supported_m3`` de lo que apoya (la plataforma en la que se apoya, con el ámbito de la entidad)."""
        found = self.figures_of(self.uid(self.first_stored))
        scope = provenance.entity_figure_scope(FIRST, "RDW-001")
        by_key = {key: (value, kind_scope) for key, value, kind_scope in found}
        for figure in self.first.figures:
            self.assertEqual(by_key[figure.key], (figure.value, scope), figure.key)
        extra = sorted(set(by_key) - {figure.key for figure in self.first.figures})
        self.assertEqual(extra, ["des.supported_m3"])
        self.assertGreaterEqual(len(self.first.figures), 20)

    def test_d_the_parameters_of_the_entity_are_written_with_their_origin_and_who_created_it(self) -> None:
        """RF-015-01, RF-015-08, RF-017-02: los parámetros de ``RDW-001`` quedan escritos como filas **de la versión** con su origen (el diálogo; las cotas de inicio y de fin, el de la superficie de
        partida y de la entidad de destino) y el decisor de quien creó, **sin** ``protect`` ni ``guard_m``; ``supports`` dice ``PLT-001`` (la dependencia declarada); es una entidad de tipo ``road`` al día
        que parte de la superficie de la plataforma (una cadena, D-16)."""
        rows = self.first.entity.rows
        parameters = core_params.ParameterStore(self.project)
        for row in rows:
            record = parameters.get(row.key, version=self.v1.uid)
            self.assertIsNotNone(record, row.key)
            self.assertEqual((record.value, record.source, record.decided_by), (row.value, row.source, BY), row.key)
        keys = {row.param: row for row in rows}
        self.assertEqual((keys["supports"].value, keys["supports"].source_kind), (PLATFORM_CODE, "algorithm"))
        self.assertIn(PLATFORM_CODE, keys["end_level_m"].source)
        self.assertEqual(self.query("SELECT count(*) FROM gb_parameter WHERE key LIKE 'des.road.rdw_001.%' AND scope = 'version'"), [(len(rows),)])
        self.assertEqual(self.query("SELECT count(*) FROM gb_parameter WHERE key LIKE 'des.road.rdw_001.protect%' OR key LIKE 'des.road.rdw_001.guard%'"), [(0,)])
        entry = entities.registry(self.project, self.v1.uid).get("RDW-001")
        self.assertEqual((entry.record.kind, entry.record.state, entry.record.name, entry.record.start), (entities.EntityKind.ROAD, entities.EntityState.CURRENT, FIRST, f"entity:{PLATFORM_CODE}"))
        self.assertEqual(str(entry.operation_uid), self.uid(self.first_stored))

    def test_e_it_is_one_transaction_and_the_inputs_are_not_modified(self) -> None:
        """RF-015-02, RF-015-29, RF-017-01, principio 7: «Crear» es **una** transacción (el contador de cambios de la base sube **una vez**) y la capa de origen, la superficie de partida (la de la
        plataforma) y la capa de los demás puntos **no se modifican** (su hash y su estado en el registro son los de antes): son entradas, no salidas."""
        before, after = self.counters
        self.assertEqual(after - before, 1)
        self.assertEqual(self.hashes(*self.inputs_before), self.inputs_before)
        written = {row[0] for uid in (self.uid(self.first_stored), self.uid(self.second_stored)) for row in self.outputs(uid)}
        self.assertFalse(written & set(self.inputs_before))

    def test_f_the_inputs_are_the_layer_the_start_the_masks_and_what_the_road_rests_on(self) -> None:
        """RF-017-01, RF-017-03, RF-015-06, RF-015-15, RF-008-24: las entradas son la capa de origen (``entity_layer``), la superficie de partida (``surface``: la de la plataforma), las máscaras de V01 y
        **lo que pisa**: la superficie de la plataforma de destino (``supported_on``) y la tabla de su huella (``support_footprint``); ningún otro diseño difiere (no se registra ninguno); el «Ramal» se apoya
        en la pista (el eje de su origen) igual."""
        platform = provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, PLATFORM)
        first = self.inputs(self.uid(self.first_stored))
        self.assertEqual(first[:2], [(PLATFORM_LAYER, "entity_layer"), (platform, "surface")])
        self.assertIn((platform, "supported_on"), first)
        self.assertIn((provenance.dataset_name(provenance.ENTITY_TABLE, PLATFORM), "support_footprint"), first)
        self.assertLessEqual({str(use.role) for use in self.masks_v1.uses()}, {role for _name, role in first})
        self.assertNotIn(provenance.ROAD_OTHER_DESIGN_ROLE, [role for _name, role in first])
        road = provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, FIRST)
        second = self.inputs(self.uid(self.second_stored))
        self.assertEqual(second[:2], [(rd.POINTS_LAYER, "entity_layer"), (road, "surface")])
        self.assertIn((road, "supported_on"), second)
        self.assertIn((provenance.dataset_name(provenance.ENTITY_TABLE, FIRST), "support_footprint"), second)
        with self.project.read() as conn:
            params = [row[0] for row in conn.execute("SELECT key FROM gb_operation_param WHERE operation_uid = ? ORDER BY fid", (self.uid(self.first_stored),))]
        self.assertIn("des.road.rdw_001.supports", params)
        self.assertIn("des.road.rdw_001.destination", params)

    def test_g_the_road_declares_nothing_to_the_other_operators(self) -> None:
        """RF-017-01, RF-015-10, RF-015-12, D-15: la pista **no declara restricción alguna**: en V01 no hay ninguna operación ``des.declare_constraints`` ni tabla de declaradas (las plataformas
        creadas sin ``protect`` tampoco), y los ajustes de la operación no llevan ``protect``."""
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation WHERE op_type = ?", provenance.DECLARE_CONSTRAINTS), [(0,)])
        self.assertEqual(self.query("SELECT count(*) FROM gb_dataset WHERE name = ?", provenance.dataset_name(provenance.DECLARED_TABLE)), [(0,)])
        ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", self.uid(self.first_stored))
        self.assertEqual(json.loads(settings), {"name": FIRST, "code": "RDW-001", "fields": {"name_field": "nombre"}})

    def test_h_the_footprint_goes_out_in_the_layer_of_entities(self) -> None:
        """RF-015-27, RF-017-01: tras «Crear», la capa de entidades de la versión (``des.entity_layer``, que encadena la orden) lleva **la pista con su huella**: una fila ``RDW-001`` de tipo ``road``, al
        día, que parte de la superficie de la plataforma, con su cadena y las cifras principales (área, corte y relleno de la sección y del borde) y un contorno que contiene su eje."""
        for _step in entity_store.entity_layer_steps(self.project, self.v1):
            pass
        with self.project.read() as conn:
            rows = {row.code: row for row in entity_layer_rows(conn, self.v1.code)}
        self.assertEqual(sorted(rows), ["PLT-001", "PLT-002", "RDW-001", "RDW-002"])
        road = rows["RDW-001"]
        self.assertEqual((road.kind, road.state, road.name), (entities.EntityKind.ROAD, entities.EntityState.CURRENT, FIRST))
        found = {key: value for key, value, _scope in self.figures_of(self.uid(self.first_stored))}
        self.assertEqual((road.area_m2, road.cut_m3, road.fill_m3), (found["des.road_area_m2"], found["des.road_cut_m3"], found["des.road_fill_m3"]))
        self.assertEqual((road.edge_cut_m3, road.edge_fill_m3), (found["des.road_edge_cut_m3"], found["des.road_edge_fill_m3"]))
        self.assertIn(f"{PLATFORM} → {FIRST} → {SECOND}", road.chain)  # la cadena, por los nombres: P1 → Pista a P1 → Ramal
        self.assertEqual(road.start, PLATFORM)  # parte de la superficie de la plataforma: la capa dice su nombre
        self.assertIn(PLATFORM, road.supports)
        x = np.concatenate([ring[:, 0] for part in road.parts for ring in part])
        y = np.concatenate([ring[:, 1] for part in road.parts for ring in part])
        axis = np.array([[row["x"], row["y"]] for row in self.table(FIRST, provenance.ROAD_AXIS_TABLE)])
        self.assertTrue(bool((x.min() <= axis[:, 0].min()) and (axis[:, 0].max() <= x.max()) and (y.min() <= axis[:, 1].min()) and (axis[:, 1].max() <= y.max())))

    def test_i_the_destination_on_a_platform_and_the_origin_on_the_axis_of_another_road_register_their_declared_dependency(self) -> None:
        """RF-017-03, RF-015-15, D-16: ``RDW-001`` se apoya en ``PLT-001`` (su destino) y ``RDW-002``, en ``RDW-001`` (su origen, ``RDW-001@100``, de la cota de su rasante a esa abscisa): las
        dependencias salen en la lista de lo que se apoya en cada entidad (con el papel ``supported_on``), y el origen del ramal es el punto del eje de la pista a 100 m (la fila ``RDW-001@100`` de su
        parámetro) a su cota."""
        rest_on_platform = entities.dependents(self.project, "V01", PLATFORM_CODE)
        self.assertIn(("RDW-001", True), [(item.entity, "supported_on" in item.roles) for item in rest_on_platform])
        rest_on_road = entities.dependents(self.project, "V01", "RDW-001")
        by_entity = {item.entity: item for item in rest_on_road}
        self.assertIn("supported_on", by_entity["RDW-002"].roles)
        self.assertIn("surface", by_entity["RDW-002"].roles)  # y parte de su superficie: la cadena
        axis = np.array([[row["station_m"], row["x"], row["y"], row["level_m"]] for row in self.table(FIRST, provenance.ROAD_AXIS_TABLE)])
        at = road_store.axis_point_at(np.column_stack([axis[:, 0], axis[:, 1], axis[:, 2], axis[:, 3], axis[:, 3]]), 100.0)
        branch = self.second.entity.job
        self.assertEqual(branch.geometry.origin, (at[0], at[1]))
        self.assertEqual(branch.start_level_m, at[2])
        rows = {row.param: row for row in self.second.entity.rows}
        self.assertEqual((rows["origin"].value, rows["supports"].value), ("RDW-001@100", "RDW-001"))

    def test_j_a_fill_over_the_carriageway_rests_on_the_road_with_its_volume(self) -> None:
        """RF-015-15, P-5: la «Relleno sobre la calzada» (una plataforma a 111 m que parte de la superficie del ramal) rellena sobre la calzada de ``RDW-001`` y **se apoya en ella con su volumen**: la
        cifra ``des.supported_m3`` con el ámbito de la plataforma y la lista de lo que se apoya en la pista (con el volumen, que es el de la cuenta a mano ``resultado − máx(partida, pista)`` sobre su
        huella, las celdas con más del espesor mínimo)."""
        rest_on_road = {item.entity: item for item in entities.dependents(self.project, "V01", "RDW-001")}
        item = rest_on_road["PLT-002"]
        self.assertIn("supported_on", item.roles)
        result = self.grid_of(provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, FILL))
        start = self.grid_of(provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, SECOND))
        road = self.grid_of(provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, FIRST))
        footprint = entity_store.runs_mask(json.loads(self.table(FIRST, provenance.ENTITY_TABLE)[0]["footprint"]), GRID.shape)
        with np.errstate(invalid="ignore"):
            thickness = result - np.maximum(start, road)
            counted = footprint & (thickness > THICKNESS_M)
        by_hand = float(thickness[counted].sum()) * GRID.cell_area
        self.assertGreater(by_hand, 0.0)
        self.assertAlmostEqual(item.volume_m3, by_hand, delta=1e-9 * max(1.0, by_hand))
        (expected,) = provenance.supported_figures(FILL, {"RDW-001": item.volume_m3})
        registered_figures = [(value, scope) for key, value, scope in self.figures_of(self.current("PLT-002")) if key == "des.supported_m3"]
        self.assertIn((expected.value, dict(expected.scope)), registered_figures)

    def test_k_what_is_kept_is_small_and_creating_is_fast(self) -> None:
        """RNF-017-10, RNF-017-07: lo que guarda una pista —la superficie entera comprimida (un GeoTIFF) y tres tablas— ocupa mucho menos que la rejilla entera sin comprimir (≤ 1/4; con la de 2,81 M celdas
        la T34 mide ≤ 25 MiB por pista) y calcular y crear la rampa de 220 m en la rejilla de 200 × 200 cabe en el plazo de la medida."""
        whole = GRID.nrows * GRID.ncols * 8
        sizes = [(self.root / locator).stat().st_size for _name, locator, _role, _hash in self.outputs(self.uid(self.first_stored)) if locator.endswith(".tif")]
        self.assertEqual(len(sizes), 1)
        self.assertLess(sizes[0], whole / 4)
        self.assertLess(sum(sizes), 25 * 1024 * 1024)
        self.assertLess(self.seconds, 20.0, f"calcular y crear tardó {self.seconds:.2f} s")


def entity_layer_rows(conn: Any, version_code: str) -> tuple[Any, ...]:
    """Las filas de la capa de entidades de la versión ``version_code`` tal como están en el proyecto."""
    layer = import_geoblender("design.entity_layer")
    return layer.read_entity_layer(conn, layer.entity_layer_table(version_code))


class ConfirmedRoadTest(CreateCase):
    """RF-017-17, RF-017-22, D-6, RF-015-29: lo confirmado queda registrado; sin confirmar no se crea; cerrar la creación a mitad no deja nada."""

    def a15(self) -> Any:
        return self.calculate_in(request("Pista A15", mode="on_axis", layer=rd.AXES_LAYER, surface=A15, profile=A15_PROFILE))

    def test_a_the_confirmation_of_the_mean_over_pm_is_recorded_with_its_reason_who_and_when(self) -> None:
        """RF-017-17, D-6, N-15: la «opción A15» (media de 10,5 % frente al 10 % del perfil) se crea con la confirmación y un motivo (no se bloquea) y la operación anota en sus ajustes
        (``road_confirmed``) la media, el límite, el motivo, **quién la confirmó y cuándo**, de modo que se lee de vuelta tal cual; la creación no cambia el cálculo."""
        calculation = self.a15()
        before = self.state()
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create(decided_by=BY)
        self.assertEqual(caught.exception.code, "des.road_mean_unconfirmed")
        self.assertEqual(self.state(), before, "sin confirmar no se escribe nada")
        calculation.confirm_road(mean=True, reason=REASON)
        self.clock.advance(minutes=1)
        stored = calculation.create(decided_by=BY)
        ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", str(stored.handle.uid))
        found = road_store.confirmed_of(json.loads(settings))
        self.assertEqual((found.decided_by, found.reason, found.mean_limit_pct, found.carriageway_m2), (BY, REASON, 10.0, None))
        self.assertAlmostEqual(found.mean_pct, 10.5, delta=1e-6)
        self.assertRegex(found.decided_on, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
        self.assertEqual(json.loads(settings)[road_store.CONFIRMED]["mean_gradient"]["reason"], REASON)
        self.assertEqual(json.loads(settings)["name"], "Pista A15")

    def test_b_a_clean_road_records_nothing_to_confirm(self) -> None:
        """RF-017-17, RF-017-22: una pista sin media por encima de pm ni calzada fuera de su rasante (la rampa de 4 %) no anota ninguna confirmación en sus ajustes aunque se confirme de más."""
        calculation = self.calculate_in(request("Pista limpia", mode="on_axis", layer=rd.AXES_LAYER, surface=rd.dataset_of("escalon")))
        calculation.confirm_road(mean=True, carriageway=True, reason="De más")
        stored = calculation.create(decided_by=BY)
        ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", str(stored.handle.uid))
        self.assertNotIn(road_store.CONFIRMED, json.loads(settings))
        self.assertIsNone(road_store.confirmed_of(json.loads(settings)))

    def test_c_closing_the_creation_halfway_leaves_nothing(self) -> None:
        """RF-015-29, RNF-017-06, principio 7: «Crear» corre por pasos (``Calculation.create_steps``: cada llamada del hilo, un trozo) y cerrar el generador a mitad, en la superficie, en una tabla o antes
        de registrar, no deja nada (ni operación, ni dato, ni parámetro, ni temporal) y descarta el cálculo; los pasos enteros la crean, y el último lleva lo guardado."""
        def asked(name: str) -> Any:
            return request(name, mode="on_axis", layer=rd.AXES_LAYER, surface=rd.dataset_of("rampa_lateral"))

        for cut in (1, 3, 6, 10):
            with self.subTest(closed_after=cut):
                calculation = self.calculate_in(asked("Pista a medias"))
                before = self.state()
                work = calculation.create_steps(budget_s=1e-9)
                for _step in range(cut):
                    next(work)
                work.close()
                self.assertEqual(self.state(), before)
                self.assertFalse(calculation.open)
        every = list(self.calculate_in(asked("Pista de los pasos")).create_steps(budget_s=1e-9))
        self.assertGreater(len(every), 10, "por pasos")
        self.assertIsInstance(every[-1].result, store.Stored)
        self.assertTrue(all(step.result is None for step in every[:-1]))
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE uid = ?", str(every[-1].result.handle.uid)), [("done",)])


class SupportSurfaceTest(CreateCase):
    """RF-017-01, RF-015-01, RF-015-15: la superficie de apoyo de la petición."""

    def test_a_the_support_surface_is_an_input_and_goes_to_the_footprint_row(self) -> None:
        """RF-017-01, RF-015-01: una pista con superficie de apoyo (``support``: un dato del proyecto) la anota como entrada con el papel ``supported_on`` y su fila de ``des_epr_`` la dice
        (``support_surface``); la partida, no."""
        support = rd.dataset_of("rampa_lateral")
        stored = self.made(request("Pista con apoyo", mode="on_axis", layer=rd.AXES_LAYER, surface=RAMP, support=support))[1]
        self.assertIn((support, "supported_on"), self.inputs(str(stored.handle.uid)))
        self.assertIn((RAMP, "surface"), self.inputs(str(stored.handle.uid)))
        (row,) = self.table("Pista con apoyo", provenance.ENTITY_TABLE)
        self.assertEqual((row["start_surface"], row["support_surface"]), (RAMP, support))


class ChangedInputTest(CreateCase):
    """RF-015-02, RF-013-17, principio 7: lo que consume la pista se comprueba otra vez al crear."""

    def test_a_a_layer_edited_since_calculating_leaves_nothing(self) -> None:
        """RF-015-02, RF-013-17: si la capa de origen cambió entre «Calcular» y «Crear» (aquí, un eje movido en QGIS), el resultado ya no le corresponde (``des.input_changed``), no queda nada (ni
        operación, ni dato, ni parámetro, ni temporal) y el cálculo queda descartado."""
        calculation = self.calculate_in(request("Pista cambiada", mode="on_axis", layer=rd.AXES_LAYER, surface=rd.dataset_of("rampa_lateral")))
        rewrite_layer(self.project, self.clock, rd.AXES_LAYER, move=2.0)
        changed = self.state()
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create(decided_by=BY)
        self.assertEqual(caught.exception.code, "des.input_changed")
        self.assertFalse(calculation.open)
        self.assertEqual(self.state(), changed)


class OtherDesignsCreateTest(QuarryStartCase):
    """RF-017-05 (b), CE-017-05: los otros diseños de la versión que difieren en la huella son entradas de la pista, con su hash."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(registered(*prep.entity_definitions()))

    def road(self, surface: str, **changes: Any) -> Any:
        return request("Pista de la cantera", mode="on_axis", layer=rd.AXES_LAYER, surface=surface, **changes)

    def calculate(self, asked: Any) -> Any:
        return finish(steps.road_run(self.project, asked, version=self.v1.uid, masks=self.masks_v1))

    def test_a_the_designs_that_differ_are_inputs_with_their_hash(self) -> None:
        """RF-017-05 (b), CE-017-05: los diseños de ``Otra`` (que parten de otra superficie y difieren de la partida en 1 m, más que el espesor mínimo) son **entradas de la pista con su papel y el hash
        que tenían al prepararla**, para que si cambian la pista quede obsoleta con su causa (la T22 lo prueba al recalcular); la superficie de la cantera de la que parte, no."""
        calculation = self.calculate(self.road("des_exp_cantera"))
        self.assertEqual(calculation.outcome.other_designs, ("des_exp_otra", "des_fin_otra"))
        stored = calculation.create(decided_by=BY)
        uid = str(stored.handle.uid)
        used = [(name, role, sha) for name, role, sha in self.query(
            "SELECT d.name, io.role, io.content_sha256 FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in' "
            "AND io.item_kind = 'dataset' ORDER BY io.fid", uid)]
        others = [(name, sha) for name, role, sha in used if role == provenance.ROAD_OTHER_DESIGN_ROLE]
        self.assertEqual([name for name, _sha in others], ["des_exp_otra", "des_fin_otra"])
        for name, sha in others:
            self.assertEqual(self.query("SELECT content_sha256 FROM gb_dataset WHERE name = ? AND status = 'current'", name), [(sha,)])
        self.assertIn(("des_exp_cantera", provenance.SURFACE_ROLE), [(name, role) for name, role, _sha in used])
        self.assertNotIn("des_exp_cantera", [name for name, _sha in others])

    def test_b_a_design_that_changes_while_calculating_leaves_nothing(self) -> None:
        """RF-015-02, RF-013-17: si uno de esos diseños cambia entre «Calcular» y «Crear», la pista ya no le corresponde (``des.input_changed``, con el nombre del dato) y no queda nada."""
        asked = request("Pista cambiada", mode="on_axis", layer=rd.AXES_LAYER, surface="des_fin_cantera")
        calculation = self.calculate(asked)
        self.assertIn("des_exp_otra", calculation.outcome.other_designs)
        original = self.query("SELECT content_sha256 FROM gb_dataset WHERE name = 'des_exp_otra' AND status = 'current'")[0][0]
        with self.project.write_transaction() as conn:
            conn.execute("UPDATE gb_dataset SET content_sha256 = ? WHERE name = 'des_exp_otra' AND status = 'current'", ("0" * 64,))
        try:
            before = self.state()
            with self.assertRaises(messages.DesignError) as caught:
                calculation.create(decided_by=BY)
            self.assertEqual((caught.exception.code, caught.exception.values["value"]), ("des.input_changed", "des_exp_otra"))
            self.assertEqual(self.state(), before)
        finally:
            with self.project.write_transaction() as conn:
                conn.execute("UPDATE gb_dataset SET content_sha256 = ? WHERE name = 'des_exp_otra' AND status = 'current'", (original,))



if __name__ == "__main__":
    import unittest

    unittest.main()
