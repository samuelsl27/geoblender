# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_entities_provenance» (spec 015, T48; plan 015 §7.4): las clases que pesan,
movidas sin cambiar una aserción. El «verde» deja en ``test_entities_provenance`` las más ligeras de cada
requisito; las de aquí las ejecuta el paso «hito» de ``tools/check.py --completo`` (la publicación
lo pide siempre).
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.unit.design.test_entities_provenance import (
    CODE,
    GOOD_VALUES,
    NAME,
    PLATFORM_FIGURES,
    _Rollback,
    cancel_if_running,
    core_params,
    design_params,
    entities,
    entity_definitions,
    figures_mod,
    gpkg_base,
    line_fields,
    operations,
    platform_request,
    provenance,
    res_provenance,
)


class EntityRegistrationTest(efx.EntityProjectCase):
    """Lo declarado, en un proyecto real: la 008 acepta los ajustes, las entradas, los parámetros y
    las cifras que arman estas funciones (V01 de la cantera sintética de la 014 con sus capas de
    plataformas y sus máscaras al día) y el registro de las entidades de la T03 reconoce la
    operación."""

    STEP_M = qfx.COARSE_STEP_M
    version: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_definitions((*design_params.DEFINITIONS,
                                          *design_params.QUARRY_DEFINITIONS))
        cls.addClassCleanup(core_params.unregister_definitions, "des")
        core_params.register_definitions(res_provenance.VERIFY_DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "res")
        core_params.register_families(design_params.ENTITY_FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        cls.enterClassContext(registered(*entity_definitions()))
        cls.version = cls.v1

    def declare(self, code: str, name: str, start: str, *, width: bool = True) -> None:
        """Da de alta en V01 los parámetros de la entidad ``code`` (los que lee la plataforma de una
        capa de líneas y si protege): lo que escribe la orden al crear, también los valores por
        defecto. Sin su fila de versión, ``begin_operation`` registraría el valor por defecto de un
        parámetro de una entidad **en el proyecto** (y la entidad llegaría a toda versión)."""
        values: dict[str, Any] = {
            "name": name, "layer": efx.AXES_LAYER, "feature": "1", "start": start,
            "start_level_m": 230.0, "gradient_pct": 1.0, "mode": "cut", "edge_angle_deg": 35.0,
            "reach_m": 60.0, "mesh_factor": 1.0, "counter_tol_m": 0.1, "metric": "exact",
            "protect": False}
        if width:
            values["width_m"] = 40.0
        store = core_params.ParameterStore(self.project)
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            for param, value in values.items():
                store.create(conn, design_params.entity_key(code, param), value,
                             kind="ADOPTADO", source="Prueba de las declaraciones",
                             source_kind="person", decided_by="Samuel (IMGA)",
                             reason="Prueba de la 015", version=self.version.code)

    def begin(self, op_type: str, **values: Any) -> Any:
        self.clock.advance(minutes=1)
        handle = operations.begin_operation(self.project, op_type, executor="blender",
                                            version=self.version.uid, **values)
        self.addCleanup(cancel_if_running, handle)
        return handle

    def named(self, uses: Any) -> list[tuple[str, str]]:
        """Lo que consume ``uses`` como lo da ``roles``: el nombre del dato (las máscaras dan su
        uid) y su papel."""
        found = []
        for use in uses:
            rows = self.query("SELECT name FROM gb_dataset WHERE uid = ? OR name = ? "
                              "ORDER BY fid DESC", use.item, use.item)
            found.append((str(rows[0][0]), use.role))
        return found

    def roles(self, handle: Any) -> list[tuple[str, str]]:
        return [(str(item), str(role)) for item, role in self.query(
            "SELECT d.name, io.role FROM gb_operation_io AS io "
            "JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'in' ORDER BY io.fid", handle.uid)]

    def write_tables(self, handle: Any, name: str, figures: Any = ()) -> list[Any]:
        """Escribe la tabla de la entidad y su informe como los datos reales de las familias
        ``epr`` y ``prp`` (con un valor sintético; la superficie, un GeoTIFF, no se escribe aquí) y
        completa la operación."""
        specs = []
        with self.project.write_transaction() as conn:
            for family in ("epr", "prp"):
                spec = provenance.dataset_spec(family, name, self.version.code)
                gpkg_base.create_attribute_table(
                    conn, spec.locator, [gpkg_base.ColumnDef("value", "DOUBLE")], spec.name,
                    "Dato sintético de la prueba de las declaraciones (spec 015)")
                conn.execute(f'INSERT INTO "{spec.locator}" (value) VALUES (1.5)')
                specs.append(spec)
            handle.complete(conn, outputs=specs, figures=figures)
        return specs

    def make(self, code: str, name: str, start: str, *, surface: str,
             supports: tuple[str, ...] = ()) -> tuple[Any, Any]:
        """La plataforma ``code`` de nombre ``name`` que parte de ``start`` (el valor de su parámetro
        ``start``; ``surface`` es el dato que consume como superficie de partida), empezada con lo
        que arman las funciones de la T04: su petición y su operación «en curso»."""
        self.declare(code, name, start)
        request = platform_request(name=name, fields=line_fields(layer=efx.AXES_LAYER),
                                   start=start)
        handle = self.begin(
            "des.platform", settings=provenance.platform_settings(request, code),
            inputs=provenance.platform_inputs(request, surface, self.masks().uses(), supports),
            params=provenance.platform_params(code, request))
        return request, handle

    def test_the_008_accepts_the_platform_as_declared(self) -> None:
        """RF-015-01, RF-015-02, RF-008-05 (plan 015 §5.2.3): ``begin_operation`` registra la
        plataforma con los ajustes de :func:`platform_settings`, las entradas de
        :func:`platform_inputs` con sus papeles (la capa, la partida y las máscaras) y los
        parámetros de :func:`platform_params` (los de la entidad, con el valor de la versión, y los
        del proyecto); lo registrado vuelve a pedir la misma plataforma; al completarla, con sus
        datos y sus cifras, el registro de las entidades la reconoce, al día, con su operación."""
        self.declare(CODE, NAME, qfx.START_DATASET)
        request = platform_request(name=NAME, fields=line_fields(layer=efx.AXES_LAYER),
                                   start=qfx.START_DATASET)
        masks = self.masks()
        settings = provenance.platform_settings(request, CODE)
        inputs = provenance.platform_inputs(request, qfx.START_DATASET, masks.uses())
        keys = provenance.platform_params(CODE, request)
        handle = self.begin("des.platform", settings=settings, inputs=inputs, params=keys)
        self.assertEqual(self.roles(handle), self.named(inputs))
        self.assertEqual(self.roles(handle)[:2], [(efx.AXES_LAYER, "entity_layer"),
                                                  (qfx.START_DATASET, "surface")])
        ((text,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", handle.uid)
        self.assertEqual(json.loads(text), settings)
        self.assertEqual([item.key for item in handle.params], list(keys))
        scopes = {item.key: item.scope for item in handle.params}
        for key in keys:
            self.assertEqual(scopes[key], "version" if key.startswith("des.platform.")
                             else "project", key)
        recorded = {item.key: json.loads(item.value_json) for item in handle.params}
        again = provenance.platform_request(
            json.loads(text), provenance.platform_values(CODE, recorded))
        self.assertEqual(again, request)

        specs = self.write_tables(handle, NAME, provenance.platform_figures(
            NAME, CODE, GOOD_VALUES))
        self.assertEqual([spec.role for spec in specs], ["entity", "entity_report"])
        found = self.query("SELECT key, unit, kind, scope FROM gb_figure WHERE operation_uid = ? "
                           "ORDER BY rowid", handle.uid)
        self.assertEqual([(key, unit, kind) for key, unit, kind, _scope in found],
                         [(key, unit, "CALCULADO") for key, (unit, _n) in
                          PLATFORM_FIGURES.items()])
        self.assertEqual({json.loads(scope)["entity"] for *_rest, scope in found}, {CODE})

        entry = entities.registry(self.project, self.version.uid).get(CODE)
        self.assertIsNotNone(entry)
        self.assertEqual((entry.record.name, entry.record.start, entry.operation_uid),
                         (NAME, qfx.START_DATASET, handle.uid))
        self.assertEqual(entry.record.state, entities.EntityState.CURRENT)

    def test_the_008_accepts_the_supports_and_the_chain(self) -> None:
        """RF-015-04, RF-015-15 (plan 015 §5.2.3): una segunda plataforma consume como ``surface`` el
        dato de la primera y, como ``supported_on``, los de las entidades en las que se apoya; los
        descarta la 008 como cualquier dato y el registro dice «apoyo retirado» (el contrato de la
        T03 con los papeles de esta tarea). La superficie de una entidad es un GeoTIFF: la prueba usa
        la tabla de la entidad, y lo que mira es el papel."""
        first, second = "Plataforma A", "Plataforma B"
        _request, previous = self.make("PLT-011", first, qfx.START_DATASET,
                                       surface=qfx.START_DATASET)
        (stand_in, _report) = self.write_tables(previous, first)
        masks = self.masks().uses()
        request, later = self.make("PLT-012", second, "entity:PLT-011", surface=stand_in.name,
                                   supports=(stand_in.name,))
        self.assertEqual(request.start, "entity:PLT-011")
        self.assertEqual(self.roles(later), [
            (efx.AXES_LAYER, "entity_layer"), (stand_in.name, "surface"),
            *self.named(masks), (stand_in.name, "supported_on")])
        self.write_tables(later, second)
        found = entities.registry(self.project, self.version.uid)
        self.assertEqual(found.get("PLT-012").record.state, entities.EntityState.CURRENT)
        self.assertEqual(found.get("PLT-012").record.start, "entity:PLT-011")
        dataset_registry = import_geoblender("core.datasets.registry")
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            uids = [dataset_registry.get(conn, provenance.dataset_name(family, first),
                                         version_uid=self.version.uid).uid
                    for family in ("epr", "prp")]
            for uid in uids:
                dataset_registry.set_status(conn, self.project, uid, "discarded")
        retired = entities.registry(self.project, self.version.uid)
        self.assertEqual(retired.get("PLT-012").record.state,
                         entities.EntityState.SUPPORT_REMOVED)
        self.assertEqual(retired.get("PLT-011").record.state, entities.EntityState.DISCARDED)

    def test_the_008_accepts_the_declaration_and_the_layer_of_entities(self) -> None:
        """RF-015-10, RF-015-27 (plan 015 §5.2.3): ``begin_operation`` registra la declaración y la
        capa de entidades con los datos ``des_epr_`` de las entidades vivas como entradas (papel
        ``entity``), los parámetros de las que protegen y sus ajustes, y la cifra
        ``des.declared_count`` se registra CALCULADO sin ámbito."""
        name = "Plataforma C"
        _request, handle = self.make("PLT-021", name, qfx.START_DATASET,
                                     surface=qfx.START_DATASET)
        self.write_tables(handle, name)
        pairs = (("PLT-021", name),)
        declare = self.begin(
            "des.declare_constraints", settings=provenance.declare_settings(pairs),
            inputs=provenance.declare_inputs([name]),
            params=provenance.declare_params(["PLT-021"]))
        self.assertEqual(self.roles(declare), [("des_epr_plataforma_c", "entity")])
        self.assertEqual([item.key for item in declare.params],
                         [design_params.entity_key("PLT-021", "name"),
                          design_params.entity_key("PLT-021", "protect")])
        self.assertEqual([item.value_json for item in declare.params][1], "false")
        layer = self.begin("des.entity_layer", settings=provenance.entity_layer_settings(pairs),
                           inputs=provenance.entity_layer_inputs([name]))
        self.assertEqual(self.roles(layer), [("des_epr_plataforma_c", "entity"),
                                             ("des_prp_plataforma_c", "entity_report")])
        self.assertEqual(layer.params, ())
        ((text,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", declare.uid)
        self.assertEqual(provenance.settings_entities(json.loads(text)), pairs)
        for figures in (provenance.declare_figures(0), provenance.declare_figures(3)):
            found = []
            try:
                with self.project.write_transaction() as conn:
                    found = [figures_mod.record_figure(conn, declare, spec) for spec in figures]
                    raise _Rollback
            except _Rollback:
                pass
            self.assertEqual([(item.key, item.unit, str(item.kind)) for item in found],
                             [("des.declared_count", "-", "CALCULADO")])
