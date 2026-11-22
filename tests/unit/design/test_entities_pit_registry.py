# SPDX-License-Identifier: GPL-3.0-or-later
"""El registro del tipo ``pit`` de la 018 (spec 018, T02; HU-018-5; RF-018-01; RF-015-01 a 04; plan 018 §2.1, §3 P-1, §5.1,
§5.2.3 y §8; ADR-0027 y ADR-0031): la corta es una entidad del registro de la 015 a la 017, **con cadena** (parte de una
superficie y deja otra), que **sale en la capa de entidades** con su huella y **no declara** restricción alguna.

La T02 registra el tipo con **un solo tipo de operación sin comportamiento** (``des.pit``, el real de la T03: la lección de
la 016 y la 017, las listas cerradas por tipo de operación) y con los valores comunes de sus parámetros; la T03 le pone los
parámetros de verdad, los demás tipos de operación, los papeles y las cifras. Sin comportamiento: ninguna operación de este tipo
existe, así que recalcularla o reproducirla dice qué tarea falta (``NotImplementedError``) y nunca cae en un escalonado.
Lo que ya hacían las specs anteriores (``test_road_provenance``, ``test_entities_registry``, ``test_supported_parameter_check``)
no cambia: solo su inventario cuenta el tipo nuevo.
"""

from __future__ import annotations

import sqlite3
import unittest
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support.package import import_geoblender

provenance = import_geoblender("design.provenance")
params = import_geoblender("design.params")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
entity_layer = import_geoblender("design.entity_layer")
messages = import_geoblender("design.messages")
store = import_geoblender("design.store")
reproduce_mod = import_geoblender("design.reproduce")
contract = import_geoblender("core.provenance.contract")
recompute_mod = import_geoblender("core.provenance.recompute")
versions_reproduce = import_geoblender("core.versions.reproduce")
base = import_geoblender("core.gpkg.base")
cstyles = import_geoblender("core.constraints.styles")

PIT = "des.pit"
PROGRAM_KINDS = ["platform", "stockpile", "removal", "buttress", "body", "road", "access", "pit"]
"""Los tipos del programa en su orden: la corta detrás de los de la 017."""


class PitTypeTest(unittest.TestCase):
    """RF-018-01, RF-015-01, RF-015-02: ``pit`` (``PIT``) es un miembro de ``EntityKind`` y el último tipo registrado."""

    def test_the_registry_lists_the_pit_after_the_types_of_the_017(self) -> None:
        """RF-018-01, RF-015-01: el registro y la enumeración lo cuentan; el código ``PIT-001`` es de una corta."""
        self.assertEqual([item.kind for item in entities.registered_types()], PROGRAM_KINDS)
        self.assertEqual([item.value for item in entities.EntityKind], PROGRAM_KINDS)
        self.assertIs(entities.EntityKind.PIT, entities.EntityKind("pit"))
        self.assertIs(entities.kind_of_code("PIT-001"), entities.EntityKind.PIT)
        self.assertEqual((entities.EntityKind.PIT.prefix, entities.EntityKind.PIT.chained), ("PIT", True))

    def test_what_the_registry_knows_of_the_pit(self) -> None:
        """RF-018-01, RF-015-04, RF-015-27: encadena (tiene ``start``), deja su superficie entera y la tabla de su huella con
        los papeles de toda entidad (sale en la capa de entidades y se puede apoyar en ella) y **no declara**: no tiene
        ``protect`` ni ``guard_m`` (D-9)."""
        spec = entities.entity_type("pit")
        self.assertEqual((spec.kind, spec.prefix, spec.key_prefix, spec.op_type, spec.chained, spec.project_op_type),
                         ("pit", "PIT", "des.pit", provenance.PIT, True, None))
        self.assertEqual(provenance.PIT, PIT)
        self.assertEqual((spec.surface_role, spec.table_role, spec.has_footprint, spec.own_zone),
                         (provenance.ENTITY_SURFACE_ROLE, provenance.ENTITY_ROLE, True, False))
        self.assertEqual((spec.reason, spec.removed), ("des.pit_declared_reason", "des.pit_support_removed"))
        self.assertIs(spec.params, params.entity_params("pit"))
        self.assertIs(spec.params, params.PIT_ENTITY)
        for name in ("name", "mode", "layer", "start", "support", "supports", "discarded", "reason"):
            self.assertIn(name, spec.params.names)
        for name in ("protect", "guard_m"):
            self.assertNotIn(name, spec.params.names)
        self.assertNotIn(entities.EntityKind.PIT, entity_store._DECLARES)  # noqa: SLF001 - la corta no declara
        self.assertNotIn(PIT, provenance.DECLARING_OP_NAMES)
        self.assertEqual(params.entity_key("PIT-001", "mode"), "des.pit.pit_001.mode")
        self.assertEqual(spec.params.template("mode").choices, ("up", "down"))

    def test_the_mode_and_the_names_are_checked_like_any_entity_value(self) -> None:
        """RF-018-02, RF-015-01: el modo es uno de dos (``up``, ``down``); un nombre en blanco se rechaza; un valor de otro tipo
        no es de la corta."""
        family = {item.pattern: item for item in params.PIT_FAMILIES}
        mode = family["des.pit.{e}.mode"]
        self.assertEqual(params.entity_params("pit").template("mode").choices, ("up", "down"))
        self.assertIsNone(mode.template.default)
        self.assertIs(family["des.pit.{e}.discarded"].template.default, False)
        self.assertEqual(len(params.PIT_FAMILIES), len(params.PIT_ENTITY.names))
        self.assertNotIn("des.pit.{e}.protect", family)

    def test_the_pit_is_a_permanent_type(self) -> None:
        """RF-018-01: es del programa, no de una prueba: no se puede quitar y lo registrado queda igual."""
        before = (entities.registered_types(), params.registered_entity_params())
        with self.assertRaises(ValueError):
            entities.unregister_entity_type("pit")
        with self.assertRaises(ValueError):
            params.unregister_entity_params("pit")
        self.assertEqual((entities.registered_types(), params.registered_entity_params()), before)


class PitOperationTest(unittest.TestCase):
    """RF-018-01, RF-009-11, RF-008-26: el tipo de operación ``des.pit`` (de la versión, repetible y reproducible) y las listas
    cerradas por tipo de operación de ``design``, sin comportamiento todavía."""

    def test_the_operation_type_is_declared_with_the_roles_of_an_entity(self) -> None:
        """RF-018-01, RF-015-02: ``des.pit`` deja la superficie entera, la tabla de su huella y su informe (papeles ``entity_surface``
        y ``entity``), sin cifras todavía (las pone la T03), de versión, repetible y reproducible."""
        declared = provenance.PIT_OPERATION_TYPES[0]  # los otros dos tipos y las salidas de la T03: test_pit_params
        self.assertEqual((declared.op_type, declared.label_msgid), (PIT, "Pit"))
        self.assertEqual(provenance.PIT_VERSION_TYPES[0], PIT)
        self.assertEqual(provenance.PIT_REPRODUCIBLE[0], PIT)
        self.assertEqual(declared.outputs[:2], (provenance.ENTITY_SURFACE_GRID, provenance.ENTITY_TABLE))
        self.assertEqual(declared.outputs[-1], provenance.ENTITY_REPORT_TABLE)
        self.assertEqual(provenance.OPERATION_TYPES_BY_NAME[PIT], declared)

    def test_the_definition_has_its_functions_and_a_missing_one_is_a_fault(self) -> None:
        """RF-009-11: la definición lleva su recálculo y su reproducción; falta o sobra una función, ``ValueError``."""

        def one(request: Any) -> Any:
            raise AssertionError("no se llama")

        every = {name: one for name in provenance.PIT_VERSION_TYPES}
        wanted = {name: one for name in provenance.PIT_REPRODUCIBLE}
        definition = provenance.pit_operation_defs(every, wanted)[0]
        self.assertEqual((definition.op_type, definition.scope, definition.recompute is one, definition.reproduce is one),
                         (PIT, "version", True, True))
        for recompute, reproduce in (({}, wanted), (every, {}), ({**every, "des.otra": one}, wanted)):
            with self.subTest(recompute=list(recompute), reproduce=list(reproduce)), self.assertRaises(ValueError):
                provenance.pit_operation_defs(recompute, reproduce)

    def test_the_closed_lists_count_the_pit(self) -> None:
        """RF-008-26, RF-015-27 (hallazgos D-1 y D-2 de la 016): ``RECOMPUTED`` (lo que repite «Recalcular lo obsoleto») y
        ``ENTITY_OP_NAMES`` (lo que cuenta como entidad) llevan ``des.pit`` al final de lo que ya llevaban, sin repetir; la
        entidad deja una superficie en la que apoyar y el gancho de las dependencias no la apoya en sí misma."""
        self.assertIn(PIT, store.RECOMPUTED)
        self.assertEqual(len(set(store.RECOMPUTED)), len(store.RECOMPUTED))
        self.assertEqual(provenance.ENTITY_OP_NAMES[-1], PIT)
        self.assertEqual(provenance.ENTITY_OP_NAMES[:7], (provenance.PLATFORM, provenance.STOCKPILE_DETECT,
                                                          provenance.STOCKPILE_REMOVAL, provenance.BUTTRESS, provenance.BODY,
                                                          provenance.ROAD, provenance.ROAD_ACCESS))
        self.assertIn(PIT, store._OWN_CODE_TYPES)  # noqa: SLF001
        self.assertNotIn(PIT, store._NO_REST_TYPES)  # noqa: SLF001

    def test_recomputing_or_reproducing_says_which_task_is_missing(self) -> None:
        """RF-008-26, RF-009-11: sin comportamiento, ``recompute_run`` y ``reproduce_pit`` dicen qué tarea lo hace
        (``NotImplementedError``) y **nunca caen en un escalonado**; lo que no es una petición, ``TypeError``; una de otro
        tipo, ``ValueError`` (errores del programa)."""
        request = recompute_mod.RecomputeRequest(object(), "uid", PIT, {}, (), ())
        with self.assertRaises(NotImplementedError) as caught:
            store.recompute_run(request)
        self.assertIn("018", str(caught.exception))
        reproducing = versions_reproduce.ReproduceRequest(PIT, {}, (), {}, ".", None)
        with self.assertRaises(NotImplementedError) as caught:
            reproduce_mod.reproduce_pit(reproducing)
        self.assertIn("018", str(caught.exception))
        with self.assertRaises(TypeError):
            reproduce_mod.reproduce_pit("petición")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            reproduce_mod.reproduce_pit(versions_reproduce.ReproduceRequest("des.quarry", {}, (), {}, ".", None))
        self.assertNotIn("reproduce_pit", reproduce_mod.REPRODUCE)  # las de la 013, sin cambios

    def test_the_names_and_labels_have_their_spanish_and_the_contract_is_kept(self) -> None:
        """RF-018-01: el nombre del tipo y los motivos tienen su español y la definición cumple el contrato de la procedencia."""
        self.assertEqual(messages.render("des.pit_declared_reason", name="Corta 1"), "declarada por la corta Corta 1")
        self.assertEqual(messages.render("des.pit_support_removed", name="Corta 1"), "se descartó la corta «Corta 1»")
        self.assertIn("Corta 1", messages.render("des.pit_declared_reason", language="en", name="Corta 1"))
        self.assertEqual(entities.declared_reason("pit", "Corta 1"), "declarada por la corta Corta 1")
        declared = provenance.PIT_OPERATION_TYPES[0]
        self.assertIsInstance(declared.definition(lambda request: None, lambda request: None), contract.OperationDef)


def pit_row(code: str = "PIT-001", name: str = "Corta", **changes: Any) -> Any:
    """Una fila de la capa de entidades de una corta de prueba (un cuadrado de 10 m de lado)."""
    ring = np.array([[725_000.0, 4_400_000.0], [725_010.0, 4_400_000.0], [725_010.0, 4_400_010.0],
                     [725_000.0, 4_400_010.0], [725_000.0, 4_400_000.0]], dtype=np.float64)
    values: dict[str, Any] = {"code": code, "name": name, "kind": "pit", "state": "current", "start": "gis_dtm_ladera",
                              "supports": "", "chain": f"gis_dtm_ladera → {name}", "parts": ((ring,),), "area_m2": 100.0}
    return entity_layer.EntityLayerRow(**{**values, **changes})


class PitLayerTest(unittest.TestCase):
    """RF-018-01, RF-015-27: la huella de una corta sale en ``des_enl_<vNN>``, con su estilo por tipo."""

    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        base.create_base(self.conn, cfx.CRS)

    def test_the_footprint_of_a_pit_comes_out_in_the_entity_layer(self) -> None:
        """RF-018-01, RF-015-27: la fila de una corta se escribe y se lee con su tipo, su estado y su contorno en float64."""
        row = pit_row()
        self.assertIs(row.kind, entities.EntityKind.PIT)
        self.assertEqual(entity_layer.write_entity_layer(self.conn, "des_enl_v01", (row,), srs_id=25830), (1,))
        (found,) = entity_layer.read_entity_layer(self.conn, "des_enl_v01")
        self.assertEqual((found.code, str(found.kind), found.area_m2), ("PIT-001", "pit", 100.0))
        self.assertEqual(found.parts[0][0].tobytes(), row.parts[0][0].tobytes())

    def test_a_pit_with_a_footprint_in_two_parts_is_two_polygons_of_one_row(self) -> None:
        """RF-018-01, RF-015-27: una huella de dos componentes (4-conexas) es una sola fila con dos polígonos, como la plataforma."""
        ring = np.array([[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 0.0]])
        other = ring + 50.0
        row = pit_row(parts=((ring,), (other,)))
        entity_layer.write_entity_layer(self.conn, "des_enl_v01", (row,), srs_id=25830)
        (found,) = entity_layer.read_entity_layer(self.conn, "des_enl_v01")
        self.assertEqual(len(found.parts), 2)

    def test_the_layer_has_its_style_and_its_figures(self) -> None:
        """RF-018-01, RF-015-27: el estilo de la capa lleva una regla por tipo (el de la corta, el suyo) y las cifras por tipo de
        la capa incluyen a la corta desde la T03 (el área y el corte)."""
        self.assertIn("pit", cstyles.ENTITY_KINDS)
        self.assertEqual(cstyles.ENTITY_KINDS["pit"][0], "Corta")
        self.assertIn("pit", entity_store.LAYER_FIGURES)


if __name__ == "__main__":
    unittest.main()
