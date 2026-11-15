# SPDX-License-Identifier: GPL-3.0-or-later
"""El modelo, los parámetros y los mensajes de las entidades de diseño (spec 015, T02; HU-015-1;
RF-015-01, RF-015-08; plan 015 §5.1, §5.2.2 y §5.3.1; D-4, D-5, D-7, D-8, D-19 y D-22; ADR-0027 y
ADR-0030).

- ``design.entities``: el tipo (``EntityKind``), el registro (``EntityRecord``), su estado
  (``EntityState``), el código ``PLT-nnn`` correlativo e inmutable por versión (``next_code``) y el
  motivo generado de una restricción declarada (``declared_reason``).
- ``design.model``: la petición de una plataforma (``PlatformRequest``, con los campos de su capa,
  ``PlatformFields``), su modo (``PlatformMode``) y su eje (``Axis``).
- ``design.params``: la familia ``des.platform.{e}.*`` de §5.2.2 (``ENTITY_FAMILIES``), con sus
  tipos, rangos y valores por defecto solo en D-4, D-5, D-7, D-8 y D-22, y ``check_entity_param``.
- ``design.messages``: los códigos ``des.entity_*`` y ``des.platform_*``, en español y en inglés.
"""

from __future__ import annotations

import dataclasses
import math
import unittest

from tests.support.package import import_geoblender

entities = import_geoblender("design.entities")
model = import_geoblender("design.model")
params = import_geoblender("design.params")
messages = import_geoblender("design.messages")
core_params = import_geoblender("core.params")
i18n = import_geoblender("core.i18n")

SPANISH_LETTERS = frozenset("áéíóúüñÁÉÍÓÚÜÑ¿¡")
PLATFORM = entities.EntityKind.PLATFORM

# Plan 015 §5.2.2, en su orden: último segmento de la clave → (tipo de valor, unidad, valor por
# defecto, mínimo, máximo, mínimo excluido, máximo excluido, opciones, RF). El máximo excluido es del
# rango de ``check_entity_param`` (``ParamDef`` no puede excluir el máximo); ``None`` en un extremo,
# abierto. Los nombres de la clave son los del glosario §14 (la pendiente de la rasante es
# «gradient», no «grade»): ``start_level_m`` y ``gradient_pct``.
PLATFORM_PARAMS: dict[str, tuple[str, str, object, float | None, float | None, bool, bool,
                                 tuple[str, ...], tuple[str, ...]]] = {
    "name": ("text", "-", None, None, None, False, False, (), ("RF-015-01",)),
    "layer": ("text", "-", None, None, None, False, False, (), ("RF-015-01",)),
    "feature": ("text", "-", None, None, None, False, False, (), ("RF-015-01",)),
    "start": ("text", "-", None, None, None, False, False, (), ("RF-015-04", "RF-015-05")),
    "support": ("text", "-", None, None, None, False, False, (), ("RF-015-04", "RF-015-05")),
    "width_m": ("float", "m", None, 0.0, 1000.0, True, False, (), ("RF-015-19",)),
    "start_level_m": ("float", "m", None, None, None, False, False, (), ("RF-015-19",)),
    "gradient_pct": ("float", "%", None, None, None, False, False, (), ("RF-015-19",)),
    "max_slope_pct": ("float", "%", None, 0.0, None, True, False, (), ("RF-015-08",)),
    "mode": ("text", "-", "cut", None, None, False, False, ("cut", "cut_fill"),
             ("RF-015-20", "RF-015-21")),
    "edge_angle_deg": ("float", "deg", None, 0.0, 90.0, True, True, (), ("RF-015-22",)),
    "reach_m": ("float", "m", None, 0.0, 10000.0, True, False, (), ("RF-015-22",)),
    "mesh_factor": ("float", "-", 1.0, 0.0, 10.0, True, False, (), ("RF-015-22",)),
    "counter_tol_m": ("float", "m", 0.1, 0.0, 10.0, False, False, (), ("RF-015-23",)),
    "metric": ("text", "-", "exact", None, None, False, False, ("exact", "chamfer5"),
               ("RF-015-22",)),
    "protect": ("bool", "-", False, None, None, False, False, (), ("RF-015-10", "RF-015-12")),
    "guard_m": ("float", "m", None, 0.0, 1000.0, False, False, (), ("RF-015-10", "RF-015-12")),
    "reason": ("text", "-", None, None, None, False, False, (), ("RF-015-10", "RF-015-12")),
    "supports": ("text", "-", None, None, None, False, False, (), ("RF-015-15",)),
    "discarded": ("bool", "-", False, None, None, False, False, (), ("RF-015-17",)),
}
# Los opcionales: sin valor es válido (el resto sin valor se rechaza, RF-015-08).
OPTIONAL = ("support", "max_slope_pct", "reason", "supports")
# Los que tienen valor por defecto (D-4, D-5, D-7, D-8, D-22): el resto, «sin valor».
WITH_DEFAULT = {"mode": "cut", "mesh_factor": 1.0, "counter_tol_m": 0.1, "metric": "exact",
                "protect": False, "discarded": False}

# Los valores que cada número admite y los que rechaza (con ``nan`` e infinito).
BOUNDS: dict[str, tuple[tuple[float, ...], tuple[float, ...]]] = {
    "width_m": ((0.001, 40.0, 1000.0), (0.0, -1.0, 1000.001, math.nan, math.inf)),
    "start_level_m": ((-5000.0, 0.0, 230.0, 1.0e6), (math.nan, math.inf, -math.inf)),
    "gradient_pct": ((-12.5, 0.0, 1.0, 100.0), (math.nan, math.inf, -math.inf)),
    "max_slope_pct": ((0.001, 10.0, 1.0e9), (0.0, -1.0, math.nan, math.inf)),
    "edge_angle_deg": ((0.001, 35.0, 89.999), (0.0, 90.0, -1.0, 91.0, math.nan)),
    "reach_m": ((0.001, 50.0, 10000.0), (0.0, 10000.001, -3.0, math.inf)),
    "mesh_factor": ((0.001, 1.0, 10.0), (0.0, 10.001, -1.0, math.nan)),
    "counter_tol_m": ((0.0, 0.1, 10.0), (-0.001, 10.001, math.nan)),
    "guard_m": ((0.0, 5.0, 1000.0), (-0.001, 1000.001, math.nan)),
}

# Los códigos de la 015 de esta tarea con su gravedad (plan §5.1; RF-015-01 a 14 y 19 a 24).
CODES: dict[str, str] = {
    "des.entity_name_missing": "error",         # RF-015-01
    "des.entity_name_repeated": "error",        # RF-015-01
    "des.entity_param_missing": "error",        # RF-015-08
    "des.entity_param_range": "error",          # RF-015-08
    "des.entity_param_choice": "error",         # RF-015-08
    "des.entity_field_value": "error",          # RF-015-08
    "des.entity_feature_unknown": "error",      # RF-015-08
    "des.entity_feature_ambiguous": "error",    # RF-015-01 (T11)
    "des.entity_start_taken": "error",          # RF-015-04
    "des.entity_start_unknown": "error",        # RF-015-04 (T11)
    "des.entity_supports_unknown": "error",     # RF-015-15 (T23)
    "des.entity_chain_cycle": "error",          # RF-015-04 (T03)
    "des.entity_insert_reason": "note",         # RF-015-05 (T03)
    "des.entity_nodata": "error",               # RF-015-09
    "des.entity_held": "warning",               # RF-015-13
    "des.entity_held_masks": "warning",         # RF-015-13
    "des.entity_held_constraint": "warning",    # RF-015-13 (T12)
    "des.entity_obsolete_masks": "note",        # RF-015-03 (T12)
    "des.entity_obsolete_consumers": "note",    # RF-015-03 (T12)
    "des.entity_obsolete_successor": "note",    # RF-015-03, RF-015-05 (T12)
    "des.entity_obsolete_dependents": "note",   # RF-015-03 (T12)
    "des.entity_dependent_volume": "note",      # RF-015-15, RF-015-17 (T24)
    "des.entity_dependent_start": "note",       # RF-015-15, RF-015-17 (T24)
    "des.entity_chain_declared": "note",        # RF-015-10 (T19)
    "des.entity_chain_masks": "note",           # RF-015-10 (T19)
    "des.entity_chain_change": "note",          # RF-012-06 (T19)
    "des.entity_chain_obsolete": "note",        # RF-015-16 (T19)
    "des.entity_chain_declare_failed": "warning",  # RF-015-10 (T19)
    "des.entity_chain_masks_failed": "warning",  # RF-015-10 (T19)
    "des.entity_discard_reason": "error",       # RF-015-17 (T25)
    "des.entity_already_discarded": "error",    # RF-015-17 (T25)
    "des.entity_release_reason": "error",       # RF-015-17 (T25)
    "des.entity_release_unknown": "error",      # RF-015-17 (T25)
    "des.entity_release_nothing": "error",      # RF-015-17 (T25)
    "des.entity_release_start": "error",        # RF-015-17 (T25)
    "des.entity_release_support_param": "error",  # RF-015-17 (T25)
    "des.entity_release_others": "error",       # RF-015-17 (T25)
    "des.support_removed": "note",              # RF-015-17 (T25)
    "des.support_removed_platform": "note",     # RF-015-17 (T25)
    "des.support_removed_dataset": "note",      # RF-015-17 (T25)
    "des.event_entity_discarded": "note",       # RF-015-17 (T25)
    "des.event_support_released": "note",       # RF-015-17 (T25)
    "des.entity_edge_outside": "warning",       # RF-015-13
    "des.entity_quarry_order": "warning",       # RF-015-14
    "des.platform_declared_reason": "note",     # RF-015-10
    "des.platform_layer_kind": "error",         # RF-015-19
    "des.platform_self_intersects": "error",    # RF-015-08
    "des.platform_axis_length_zero": "error",   # RF-015-08
    "des.platform_axis_closed": "error",        # RF-015-08
    "des.platform_axis_parts": "error",         # RF-015-08 (T06)
    "des.platform_area_zero": "error",          # RF-015-08
    "des.platform_no_cells": "error",           # RF-015-08
    "des.platform_axis_not_crossing": "error",  # RF-015-08
    "des.platform_axis_principal": "warning",   # RF-015-19
    "des.platform_level_range": "error",        # RF-015-08
    "des.platform_max_slope": "error",          # RF-015-08 (D-6)
    "des.platform_protect_cut_fill": "error",   # RF-015-12
    "des.platform_counter_slope": "warning",    # RF-015-23
    "des.platform_counter_flat": "warning",     # RF-015-23 (D-16)
    "des.platform_below": "warning",            # RF-015-24
    "des.platform_below_group": "note",         # RF-015-24
    "des.platform_below_masks": "warning",      # RF-015-13, RF-015-24 (T09)
    "des.platform_counter_unconfirmed": "error",  # RF-015-23 (T09)
    "des.platform_above": "warning",            # RF-015-24
    "des.platform_above_group": "note",         # RF-015-24
    "des.platform_no_cut": "warning",           # RF-015-24
    "des.platform_edge_steep": "warning",       # RF-015-22 (T08)
    "des.platform_more_groups": "note",         # RF-015-24 (T12)
}
FAMILIES = ("des.entity_", "des.platform_", "des.support_", "des.event_")


def key_of(last: str, code: str = "PLT-001") -> str:
    return f"des.platform.{params.entity_segment(code)}.{last}"


def fields(**changes: object) -> object:
    values: dict[str, object] = {"layer": "gis_fea_plataformas_ejes", "width_field": "ancho",
                                 "start_level_field": "cota_inicial",
                                 "gradient_field": "pendiente"}
    values.update(changes)
    return model.PlatformFields(**values)


def request(**changes: object) -> object:
    values: dict[str, object] = {"name": "P1", "fields": fields(), "feature": "7",
                                 "start": "gis_dtm_ladera", "edge_angle_deg": 35.0,
                                 "reach_m": 50.0}
    values.update(changes)
    return model.PlatformRequest(**values)


class EntityCodeTest(unittest.TestCase):
    def test_the_kind_and_its_prefix(self) -> None:
        """RF-015-01 (plan §5.1, ADR-0030): en esta spec hay un tipo, la plataforma, y su código
        es ``PLT-nnn``; el tipo es el valor que va en la clave de sus parámetros."""
        self.assertEqual([item.value for item in entities.EntityKind], ["platform"])
        self.assertEqual(PLATFORM.prefix, "PLT")
        self.assertEqual(entities.EntityKind("platform"), PLATFORM)
        with self.assertRaises(ValueError):
            entities.EntityKind("stockpile")

    def test_the_next_code_is_correlative_and_never_reused(self) -> None:
        """RF-015-01 (ADR-0030, como el código de una restricción, D-22 de la 012): el código es
        ``PLT-`` y un número correlativo por versión de tres cifras al menos; el siguiente es el
        mayor que ya hay más uno, también si falta alguno por el camino (una entidad descartada
        sigue en la versión: su código no se reutiliza), y con cuatro cifras pasa de 999."""
        cases = (((), "PLT-001"), (("PLT-001",), "PLT-002"), (("PLT-001", "PLT-002"), "PLT-003"),
                 (("PLT-003", "PLT-001"), "PLT-004"), (("PLT-001", "PLT-003"), "PLT-004"),
                 (("PLT-001", "PLT-001"), "PLT-002"), (("PLT-999",), "PLT-1000"),
                 (("PLT-1000",), "PLT-1001"), (("PLT-009", "PLT-010"), "PLT-011"))
        for existing, expected in cases:
            with self.subTest(existing=existing):
                self.assertEqual(entities.next_code(PLATFORM, existing), expected)
        self.assertEqual(entities.next_code(PLATFORM, iter(["PLT-007"])), "PLT-008")
        self.assertEqual(entities.next_code(PLATFORM, ["STK-020", "PLT-002"]), "PLT-003")

    def test_a_code_that_is_not_one_is_a_fault_of_the_program(self) -> None:
        """RF-015-01: ``next_code`` y ``format_code`` no inventan un código: uno mal escrito en lo
        que ya hay (``PLT-1``, ``plt-001``, ``PLT-00a``) o un número que no es de una entidad
        (0, negativo, no entero) es un error del programa, no de la persona."""
        for wrong in ("PLT-1", "plt-001", "PLT-00a", "PLT001", "", "PLT-001 ", "PLT_001"):
            with self.subTest(code=wrong), self.assertRaises(ValueError):
                entities.next_code(PLATFORM, [wrong])
        with self.assertRaises(TypeError):
            entities.next_code(PLATFORM, [1])
        self.assertEqual(entities.format_code(PLATFORM, 1), "PLT-001")
        self.assertEqual(entities.format_code(PLATFORM, 1234), "PLT-1234")
        for wrong in (0, -1):
            with self.subTest(number=wrong), self.assertRaises(ValueError):
                entities.format_code(PLATFORM, wrong)
        for wrong in (1.5, True, "1"):
            with self.subTest(number=wrong), self.assertRaises(TypeError):
                entities.format_code(PLATFORM, wrong)

    def test_the_code_in_the_key_of_a_parameter(self) -> None:
        """RF-015-01 (ADR-0027: un segmento de clave es ``[a-z][a-z0-9_]*``): el código ``PLT-001``
        va en la clave como ``plt_001`` (minúsculas y guion bajo) y vuelve idéntico; la clave de
        un parámetro es ``des.platform.plt_001.<parámetro>``."""
        self.assertEqual(params.entity_segment("PLT-001"), "plt_001")
        self.assertEqual(params.entity_segment("PLT-1234"), "plt_1234")
        self.assertEqual(params.segment_code("plt_001"), "PLT-001")
        for code in ("PLT-001", "PLT-1234", "PLT-020"):
            self.assertEqual(params.segment_code(params.entity_segment(code)), code)
        self.assertEqual(params.entity_key("PLT-001", "width_m"),
                         "des.platform.plt_001.width_m")
        self.assertEqual(params.entity_key("PLT-002", params.PlatformParam.GUARD),
                         "des.platform.plt_002.guard_m")
        for wrong in ("PLT-1", "plt-001", "", "PLT_001"):
            with self.subTest(code=wrong), self.assertRaises(ValueError):
                params.entity_segment(wrong)
        for wrong in ("plt-001", "plt_1", "PLT_001", "", "plt_00a"):
            with self.subTest(segment=wrong), self.assertRaises(ValueError):
                params.segment_code(wrong)
        with self.assertRaises(ValueError):
            params.entity_key("PLT-001", "no_such_param")


class EntityRecordTest(unittest.TestCase):
    def test_a_record_and_its_defaults(self) -> None:
        """RF-015-01, RF-015-04: el registro de una entidad lleva su código, su nombre, su tipo,
        su superficie de partida y, si la tiene, la de apoyo (ambas sin valor hasta que se
        eligen) y su estado, deducido y no apuntado (ADR-0025 §5): «sin calcular» por defecto."""
        record = entities.EntityRecord("PLT-001", "  P1 ", PLATFORM, start="gis_dtm_ladera")
        self.assertEqual((record.code, record.name, record.kind), ("PLT-001", "P1", PLATFORM))
        self.assertEqual((record.start, record.support), ("gis_dtm_ladera", None))
        self.assertEqual(record.state, entities.EntityState.UNCALCULATED)
        self.assertEqual(record.segment, "plt_001")
        self.assertEqual(record, entities.EntityRecord("PLT-001", "P1", PLATFORM,
                                                       start="gis_dtm_ladera"))
        self.assertEqual(len({record, record}), 1)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            record.name = "P2"  # type: ignore[misc]
        bare = entities.EntityRecord("PLT-002", "P2", PLATFORM)
        self.assertEqual((bare.start, bare.support), (None, None))

    def test_the_states_of_an_entity(self) -> None:
        """RF-015-25 (plan §5.2.3): los cinco estados que deduce el grafo, con su texto estable:
        sin calcular, al día, obsoleta, descartada y «apoyo retirado»."""
        self.assertEqual([item.value for item in entities.EntityState],
                         ["uncalculated", "current", "stale", "discarded", "support_removed"])
        record = entities.EntityRecord("PLT-001", "P1", PLATFORM,
                                       state=entities.EntityState.STALE)
        self.assertEqual(record.state, entities.EntityState.STALE)
        self.assertEqual(entities.EntityState("discarded"), entities.EntityState.DISCARDED)
        with self.assertRaises(ValueError):
            entities.EntityState("retired")

    def test_a_record_without_a_name_or_with_a_wrong_code(self) -> None:
        """RF-015-01 (nombre único en su ámbito; el código es inmutable): una entidad sin nombre
        se rechaza nombrando el campo (``des.entity_name_missing``); un código que no es de su
        tipo es un error del programa."""
        for blank in ("", "   "):
            with self.subTest(name=blank), self.assertRaises(messages.DesignError) as caught:
                entities.EntityRecord("PLT-001", blank, PLATFORM)
            self.assertEqual(caught.exception.code, "des.entity_name_missing")
            self.assertEqual(caught.exception.field, "name")
        with self.assertRaises(TypeError):
            entities.EntityRecord("PLT-001", 7, PLATFORM)  # type: ignore[arg-type]
        for wrong in ("PLT-1", "XYZ-001", "plt_001", ""):
            with self.subTest(code=wrong), self.assertRaises(ValueError):
                entities.EntityRecord(wrong, "P1", PLATFORM)
        with self.assertRaises(ValueError):
            entities.EntityRecord("PLT-001", "P1", "stockpile")  # type: ignore[arg-type]


class DeclaredReasonTest(unittest.TestCase):
    def test_the_generated_reason(self) -> None:
        """RF-015-10 (D-4): el motivo generado de la restricción que declara una plataforma es
        «declarada por la plataforma P1» (con su nombre), en español y en inglés; la persona lo
        puede editar en la entidad (el parámetro ``reason``)."""
        self.assertEqual(entities.declared_reason(PLATFORM, "P1"),
                         "declarada por la plataforma P1")
        self.assertEqual(entities.declared_reason(PLATFORM, "P1", language="en"),
                         "declared by platform P1")
        self.assertEqual(entities.declared_reason(PLATFORM, "  Plataforma de carga "),
                         "declarada por la plataforma Plataforma de carga")
        self.assertEqual(entities.declared_reason(PLATFORM, "Cota {2}"),
                         "declarada por la plataforma Cota {2}")
        self.assertEqual(messages.MESSAGES["des.platform_declared_reason"].severity, "note")

    def test_a_reason_for_an_unnamed_entity_is_a_fault_of_the_program(self) -> None:
        """RF-015-10: la entidad que declara ya tiene nombre (RF-015-01): sin él, ``ValueError``;
        un idioma que no es de Geoblender, también."""
        for blank in ("", "  "):
            with self.subTest(name=blank), self.assertRaises(ValueError):
                entities.declared_reason(PLATFORM, blank)
        with self.assertRaises(TypeError):
            entities.declared_reason(PLATFORM, None)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            entities.declared_reason(PLATFORM, "P1", language="fr")


class PlatformParamsTest(unittest.TestCase):
    def test_the_twenty_families_of_the_plan(self) -> None:
        """RF-015-01, RF-015-08, RF-015-19 a RF-015-23 (plan §5.2.2; ADR-0027): la definición de
        una plataforma son sus parámetros de versión en 20 familias ``des.platform.{e}.<valor>``,
        en el orden del plan, cada una con su tipo de valor, su unidad, su rango, sus opciones
        (modo y métrica), sus RF y su valor por defecto solo donde lo dicen D-4, D-5, D-7, D-8 y
        D-22; todo lo demás, ADOPTADO, de versión y sin valor por defecto (que lo declara una
        persona al crear la entidad)."""
        self.assertEqual([family.pattern for family in params.ENTITY_FAMILIES],
                         [f"des.platform.{{e}}.{last}" for last in PLATFORM_PARAMS])
        self.assertEqual(len(params.ENTITY_FAMILIES), 20)
        self.assertEqual([item.value for item in params.PlatformParam], list(PLATFORM_PARAMS))
        for family, (last, spec) in zip(params.ENTITY_FAMILIES, PLATFORM_PARAMS.items(),
                                        strict=True):
            value_type, unit, default, minimum, maximum, min_ex, _max_ex, choices, rfs = spec
            template = family.template
            with self.subTest(family=family.pattern):
                self.assertIsInstance(family, core_params.ParamFamily)
                self.assertEqual(template.key, f"des.platform.e.{last}")
                self.assertEqual((template.value_type, template.unit), (value_type, unit))
                self.assertEqual((template.default, type(template.default)),
                                 (default, type(default)))
                self.assertEqual((template.minimum, template.maximum), (minimum, maximum))
                self.assertEqual(template.min_exclusive, min_ex)
                self.assertEqual(template.choices, choices)
                self.assertEqual(template.requirements, rfs)
                self.assertEqual(template.scope, "version")
                self.assertEqual(template.kind, "ADOPTADO")
                self.assertEqual(template.allow_empty, default is None)
                self.assertEqual(template.source_kind, "person" if default is None
                                 else "algorithm")
                self.assertTrue(template.source.strip())
                self.assertIs(params.PLATFORM_PARAMS[last], template)
        self.assertEqual({last: spec[2] for last, spec in PLATFORM_PARAMS.items()
                          if spec[2] is not None}, WITH_DEFAULT)

    def test_a_family_gives_the_definition_of_a_concrete_key(self) -> None:
        """RF-015-01 (ADR-0027, punto 3): la clave concreta de la entidad ``PLT-001`` es una
        definición declarada a todos los efectos: ``core.params`` la resuelve por su familia, con
        el rango de ``ParamDef`` (el valor por defecto se comprueba al declarar)."""
        for last, spec in PLATFORM_PARAMS.items():
            key = key_of(last)
            found = core_params.find_definition(key, {}, params.ENTITY_FAMILIES)
            with self.subTest(key=key):
                self.assertIsNotNone(found)
                self.assertEqual(found.key, key)
                self.assertEqual(found.value_type, spec[0])
                self.assertEqual(params.entity_key("PLT-001", last), key)
        self.assertIsNone(core_params.find_definition(key_of("no_such"), {},
                                                      params.ENTITY_FAMILIES))
        # El código es el que va en la clave: otra entidad, otra clave, la misma plantilla.
        other = core_params.find_definition(key_of("reach_m", "PLT-002"), {},
                                            params.ENTITY_FAMILIES)
        self.assertEqual(other.key, "des.platform.plt_002.reach_m")

    def test_the_families_do_not_overlap_with_the_other_ones_of_design(self) -> None:
        """RF-015-01 (ADR-0027, ``register_families``): ninguna de las 20 familias solapa con otra
        ni con las de los perfiles y los sectores de la 013, ni casa con un parámetro del
        proyecto de ``design``: así ``bl`` las registra todas juntas (T04). Van aparte de
        ``FAMILIES`` (las de la 013), como los siete de la cantera de la 014."""
        mine = params.ENTITY_FAMILIES
        for index, family in enumerate(mine):
            for other in (*mine[:index], *params.FAMILIES):
                with self.subTest(family=family.pattern, other=other.pattern):
                    self.assertFalse(family.overlaps(other))
            for definition in (*params.DEFINITIONS, *params.QUARRY_DEFINITIONS):
                self.assertIsNone(family.match(definition.key))
        self.assertFalse({family.pattern for family in mine}
                         & {family.pattern for family in params.FAMILIES})

    def test_the_options_are_the_ones_of_the_model(self) -> None:
        """RF-015-20, RF-015-21, RF-015-22 (D-5, D-22): las opciones de ``mode`` son los valores
        de ``PlatformMode`` y las de ``metric``, los de ``Metric`` (la métrica exacta por defecto,
        D-22); no se repiten a mano: la prueba las ata."""
        self.assertEqual([item.value for item in model.PlatformMode], ["cut", "cut_fill"])
        self.assertEqual(params.PLATFORM_PARAMS["mode"].choices,
                         tuple(item.value for item in model.PlatformMode))
        self.assertEqual(set(params.PLATFORM_PARAMS["metric"].choices),
                         {item.value for item in model.Metric})
        self.assertEqual(params.PLATFORM_PARAMS["mode"].default, model.PlatformMode.CUT.value)
        self.assertEqual(params.PLATFORM_PARAMS["metric"].default, model.Metric.EXACT.value)

    def test_only_the_defaults_of_the_decisions_have_a_value(self) -> None:
        """Principio 2, RF-015-08 (D-4, D-5, D-6, D-7, D-8, D-19, D-20, D-22): sin valor por
        defecto ni la cota inicial, ni la pendiente de la rasante, ni la pendiente máxima, ni el
        ángulo de borde, ni el alcance, ni el resguardo (obligatorio si protege): una cifra
        supuesta acabaría en un plano; con valor, el modo «en corte», el factor de malla 1,0, la
        tolerancia de contrapendiente de 0,1 m (la de la solera del canal), la métrica exacta y
        «no proteger»."""
        without = [last for last, spec in PLATFORM_PARAMS.items() if spec[2] is None]
        self.assertEqual(set(without), set(PLATFORM_PARAMS) - set(WITH_DEFAULT))
        for last in ("start_level_m", "gradient_pct", "max_slope_pct", "edge_angle_deg",
                     "reach_m", "guard_m", "width_m"):
            with self.subTest(param=last):
                self.assertIsNone(params.PLATFORM_PARAMS[last].default)
        self.assertEqual(params.PLATFORM_PARAMS["counter_tol_m"].default, 0.1)
        self.assertEqual(params.PLATFORM_PARAMS["mesh_factor"].default, 1.0)
        for last in WITH_DEFAULT:
            with self.subTest(param=last):
                self.assertIn("Spec 015", params.PLATFORM_PARAMS[last].source)

    def test_labels_with_their_spanish(self) -> None:
        """RF-008-06 (principio 10): cada familia lleva su etiqueta en inglés (sin letras del
        español) con su traducción en ``core/i18n/messages.toml``, y ninguna se repite."""
        table = i18n.load_messages()
        labels = [family.template.label_msgid for family in params.ENTITY_FAMILIES]
        self.assertEqual(len(set(labels)), len(labels))
        for label in labels:
            with self.subTest(label=label):
                self.assertTrue(label and label.strip())
                self.assertEqual(set(label) & SPANISH_LETTERS, set())
                self.assertIn(label, table)
                self.assertNotEqual(table[label], label)
        self.assertEqual(i18n.untranslated(labels), [])


LAYER = "gis_fea_plataformas_ejes"
"""La capa de la plataforma de las pruebas del parámetro: RF-015-08 pide nombrarla."""


class CheckEntityParamTest(unittest.TestCase):
    def check(self, last: str, value: object, **options: object) -> object:
        return params.check_entity_param("P1", "PLT-001", last, value, layer=LAYER, **options)

    def test_every_number_in_its_range(self) -> None:
        """RF-015-08 (plan §5.2.2): cada número se comprueba en su rango (extremos incluidos o
        excluidos, también el 90° del ángulo de borde, que ``ParamDef`` no puede excluir); un
        valor dentro vuelve como ``float``; fuera, ``nan`` o infinito, ``des.entity_param_range``
        nombrando la plataforma, la clave del campo, el valor y el rango."""
        for last, (inside, outside) in BOUNDS.items():
            for value in inside:
                with self.subTest(param=last, value=value):
                    checked = self.check(last, value)
                    self.assertEqual(checked, value)
                    self.assertIs(type(checked), float)
            for value in outside:
                with self.subTest(param=last, value=value):
                    with self.assertRaises(messages.DesignError) as caught:
                        self.check(last, value)
                    error = caught.exception
                    self.assertEqual(error.code, "des.entity_param_range")
                    self.assertEqual(error.field, key_of(last))
                    self.assertEqual(error.obj, "Plataforma «P1»")
                    self.assertIn("«P1»", error.text)
                    self.assertIn(f"«{LAYER}»", error.text)  # RF-015-08: la capa, la entidad,
                    self.assertEqual(error.values["layer"], LAYER)  # el campo y el valor
                    self.assertIn(key_of(last), error.text)
                    self.assertIn(params.ENTITY_RANGES[last].text(), error.text)
                    self.assertNotIn("{", error.text)
        self.assertEqual(self.check("reach_m", 50), 50.0)  # un entero es un número real

    def test_the_ranges_as_they_read(self) -> None:
        """RF-015-08: el rango con el que se rechaza se lee con paréntesis en el extremo excluido
        y ``±∞`` en el abierto: (0; 90) °, (0; 1 000] m, [0; 10] m, (0; +∞) % y (-∞; +∞) m."""
        spaced = {last: params.ENTITY_RANGES[last].text() for last in BOUNDS}
        self.assertEqual(spaced["edge_angle_deg"], "(0; 90) °")
        self.assertEqual(spaced["width_m"], f"(0; 1{i18n.THIN_SPACE}000] m")
        self.assertEqual(spaced["counter_tol_m"], "[0; 10] m")
        self.assertEqual(spaced["max_slope_pct"], "(0; +∞) %")
        self.assertEqual(spaced["start_level_m"], "(-∞; +∞) m")
        self.assertEqual(params.ENTITY_RANGES["mesh_factor"].text("en"), "(0, 10]")

    def test_without_a_value(self) -> None:
        """RF-015-08, RF-015-10 (D-6, D-7, D-19, D-20): uno sin valor se rechaza nombrando la
        plataforma y el campo (``des.entity_param_missing``; ninguno elige un valor por la
        persona), salvo los opcionales (la superficie de apoyo, la pendiente máxima, el motivo y
        las dependencias declaradas), que vuelven ``None``; ``required`` cambia lo uno y lo otro
        (el ancho solo lo pide un eje de línea; el resguardo, quien protege)."""
        for last in PLATFORM_PARAMS:
            with self.subTest(param=last):
                if last in OPTIONAL:
                    self.assertIsNone(self.check(last, None))
                    with self.assertRaises(messages.DesignError) as forced:
                        self.check(last, None, required=True)
                    self.assertEqual(forced.exception.code, "des.entity_param_missing")
                    continue
                with self.assertRaises(messages.DesignError) as caught:
                    self.check(last, None)
                error = caught.exception
                self.assertEqual(error.code, "des.entity_param_missing")
                self.assertEqual(error.field, key_of(last))
                self.assertEqual(error.obj, "Plataforma «P1»")
                self.assertIsNone(error.value)
                self.assertIn("«P1»", error.text)
                self.assertIn(f"«{LAYER}»", error.text)
                self.assertEqual(error.values["layer"], LAYER)
                self.assertIn(key_of(last), error.text)
                self.assertNotIn("{", error.text)
                self.assertIsNone(self.check(last, None, required=False))
        for last in ("name", "layer", "feature", "start", "reason", "support", "supports"):
            with self.subTest(blank=last):  # un texto en blanco es «sin valor»
                if last in OPTIONAL:
                    self.assertIsNone(self.check(last, "   "))
                else:
                    with self.assertRaises(messages.DesignError) as caught:
                        self.check(last, "   ")
                    self.assertEqual(caught.exception.code, "des.entity_param_missing")

    def test_texts_options_and_the_flag(self) -> None:
        """RF-015-20, RF-015-22, RF-015-10 (D-5, D-22): el modo y la métrica son de su lista
        cerrada (otro texto, ``des.entity_param_choice`` con las opciones); un texto sale sin los
        espacios de los extremos; ``protect`` es un sí/no."""
        self.assertEqual(self.check("mode", "cut"), "cut")
        self.assertEqual(self.check("mode", "cut_fill"), "cut_fill")
        self.assertEqual(self.check("metric", "chamfer5"), "chamfer5")
        self.assertEqual(self.check("layer", "  gis_fea_plataformas_ejes "),
                         "gis_fea_plataformas_ejes")
        self.assertEqual(self.check("reason", "motivo"), "motivo")
        self.assertIs(self.check("protect", True), True)
        self.assertIs(self.check("protect", False), False)
        for last, wrong in (("mode", "fill"), ("mode", "CUT"), ("metric", "chamfer3")):
            with self.subTest(param=last, value=wrong):
                with self.assertRaises(messages.DesignError) as caught:
                    self.check(last, wrong)
                self.assertEqual(caught.exception.code, "des.entity_param_choice")
                self.assertEqual(caught.exception.field, key_of(last))
                self.assertIn(f"«{LAYER}»", caught.exception.text)
                for option in params.PLATFORM_PARAMS[last].choices:
                    self.assertIn(f"«{option}»", caught.exception.text)

    def test_a_value_of_another_type_is_a_fault_of_the_program(self) -> None:
        """RF-015-08: un número que llega como texto o como booleano, un texto que no lo es y un
        ``protect`` que no es un sí/no no son un error de la persona (el diálogo los entrega ya
        con su tipo): ``TypeError``; un parámetro o un código que no existen, ``ValueError``."""
        for last, wrong in (("width_m", "40"), ("width_m", True), ("name", 7), ("mode", 1),
                            ("protect", 1), ("protect", "sí"), ("guard_m", [5.0])):
            with self.subTest(param=last, value=wrong), self.assertRaises(TypeError):
                self.check(last, wrong)
        with self.assertRaises(ValueError):
            self.check("no_such_param", 1.0)
        with self.assertRaises(ValueError):
            params.check_entity_param("P1", "PLT-1", "reach_m", 1.0, layer=LAYER)
        with self.assertRaises(ValueError):
            params.check_entity_param("P1", "plt_001", "reach_m", 1.0, layer=LAYER)


class PlatformModelTest(unittest.TestCase):
    def test_the_mode(self) -> None:
        """RF-015-20, RF-015-21 (D-5): el modo de una plataforma es «en corte» (``cut``) o «en
        corte y relleno» (``cut_fill``), con su texto estable (el que se registra)."""
        self.assertEqual([item.value for item in model.PlatformMode], ["cut", "cut_fill"])
        self.assertEqual(model.PlatformMode("cut_fill"), model.PlatformMode.CUT_FILL)
        for wrong in ("fill", "CUT", ""):
            with self.subTest(mode=wrong), self.assertRaises(ValueError):
                model.PlatformMode(wrong)

    def test_the_axis(self) -> None:
        """RF-015-19 (convenios: la abscisa 0 en el primer vértice, en el sentido de
        digitalización): un eje son sus vértices absolutos en ``float64`` (como pares de
        ``float`` de Python, también si llegan de un array), con su longitud medida, su primer y
        su último vértice y si va cerrado; con ``principal`` sale de un polígono sin eje
        enlazado."""
        axis = model.Axis(((100.0, 200.0), (130.0, 240.0), (130.0, 240.0 + 70.0)))
        self.assertEqual(axis.vertices, ((100.0, 200.0), (130.0, 240.0), (130.0, 310.0)))
        self.assertEqual((axis.start, axis.end), ((100.0, 200.0), (130.0, 310.0)))
        self.assertEqual(axis.length_m, 50.0 + 70.0)
        self.assertFalse(axis.closed)
        self.assertFalse(axis.principal)
        self.assertEqual(axis, model.Axis([[100, 200], [130, 240], [130, 310]]))
        self.assertEqual(len({axis, model.Axis(axis.vertices)}), 1)
        big = model.Axis(((725_010.5, 4_400_020.5), (725_110.5, 4_400_020.5)), principal=True)
        self.assertEqual(big.vertices[0], (725_010.5, 4_400_020.5))  # float64, sin perder el 0,5
        self.assertEqual(big.length_m, 100.0)
        self.assertTrue(big.principal)
        ring = model.Axis(((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 0.0)))
        self.assertTrue(ring.closed)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            axis.principal = True  # type: ignore[misc]

    def test_an_axis_without_length_is_still_an_axis(self) -> None:
        """RF-015-08: rechazar un eje sin longitud o cerrado, con su capa y su entidad, es de la
        geometría (T06): el modelo lo representa (longitud 0, ni cerrado), no lo rechaza; lo que
        no puede ser un eje (menos de dos vértices, un vértice que no son dos números finitos) es
        un error del programa."""
        point = model.Axis(((5.0, 5.0), (5.0, 5.0)))
        self.assertEqual(point.length_m, 0.0)
        self.assertFalse(point.closed)
        for wrong in ((), ((1.0, 2.0),), ((1.0, 2.0), (3.0,)), ((1.0, 2.0), (3.0, math.nan)),
                      ((1.0, 2.0), (math.inf, 3.0)), ((1.0, 2.0), (3.0, 4.0, 5.0)),
                      ((1.0, 2.0), ("a", "b"))):
            with self.subTest(vertices=wrong), self.assertRaises(ValueError):
                model.Axis(wrong)

    def test_the_layer_fields(self) -> None:
        """RF-015-19 (plan §5.2.1; D-15: los de un corredor de la 014): la capa de plataformas y
        los campos que se leen de ella: la cota inicial y la pendiente de la rasante de las dos
        capas, el ancho de la de líneas y, en la de polígonos, el enlace con su eje (el campo y la
        capa de líneas, los dos o ninguno)."""
        lines = fields()
        self.assertEqual((lines.layer, lines.width_field), ("gis_fea_plataformas_ejes", "ancho"))
        self.assertEqual((lines.start_level_field, lines.gradient_field),
                         ("cota_inicial", "pendiente"))
        self.assertEqual((lines.axis_field, lines.axis_layer), (None, None))
        polygons = fields(layer="gis_fea_plataformas_poligonos", width_field=None,
                          axis_field="eje", axis_layer="gis_fea_plataformas_ejes")
        self.assertEqual((polygons.width_field, polygons.axis_field, polygons.axis_layer),
                         (None, "eje", "gis_fea_plataformas_ejes"))
        principal = fields(layer="gis_fea_plataformas_poligonos", width_field=None)
        self.assertIsNone(principal.axis_field)
        for wrong in ({"axis_field": "eje"}, {"axis_layer": "gis_fea_plataformas_ejes"},
                      {"axis_field": "eje", "axis_layer": "gis_fea_plataformas_ejes"}):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                fields(**wrong)  # el ancho y el enlace con un eje son de capas distintas
        for wrong in ("", "  "):
            with self.subTest(layer=wrong), self.assertRaises(ValueError):
                fields(layer=wrong)

    def test_the_request(self) -> None:
        """RF-015-01, RF-015-20, RF-015-22 (plan §5.3.1, §5.3.3): lo que pide el usuario del
        diálogo (como ``QuarryRequest``): el nombre, la capa con sus campos, la geometría (su
        nombre o su ``fid``, como texto), la partida y la apoyo, el modo, el borde, la tolerancia,
        la métrica, la pendiente máxima y qué declara. Lo que no pide es ``None``: el valor por
        defecto del parámetro (D-5, D-7, D-8, D-22) o, si no lo tiene, el rechazo de RF-015-08;
        la petición no lleva ni una cifra minera a mano."""
        plain = request()
        self.assertEqual((plain.name, plain.feature, plain.start), ("P1", "7", "gis_dtm_ladera"))
        self.assertEqual(plain.layer, "gis_fea_plataformas_ejes")
        self.assertEqual((plain.support, plain.mode, plain.metric), (None, None, None))
        self.assertEqual((plain.mesh_factor, plain.counter_tol_m, plain.max_slope_pct),
                         (None, None, None))
        self.assertEqual((plain.protect, plain.guard_m, plain.reason), (False, None, None))
        self.assertEqual((plain.edge_angle_deg, plain.reach_m), (35.0, 50.0))
        full = request(mode="cut_fill", metric=model.Metric.CHAMFER5, mesh_factor=1,
                       counter_tol_m=0, max_slope_pct=8, protect=True, guard_m=5, reason=" r ",
                       support="des_psf_p0_v01", name="  P2 ")
        self.assertEqual((full.mode, full.metric), (model.PlatformMode.CUT_FILL,
                                                    model.Metric.CHAMFER5))
        self.assertIs(type(full.mesh_factor), float)
        self.assertEqual((full.counter_tol_m, full.max_slope_pct, full.guard_m),
                         (0.0, 8.0, 5.0))
        self.assertEqual((full.name, full.reason, full.support), ("P2", "r", "des_psf_p0_v01"))
        self.assertEqual(plain, request())
        self.assertEqual(len({plain, request()}), 1)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            plain.name = "P9"  # type: ignore[misc]
        values = {item.name: item for item in dataclasses.fields(model.PlatformRequest)}
        for name in ("mode", "mesh_factor", "counter_tol_m", "metric"):
            self.assertIsNone(values[name].default)  # ningún valor por defecto escrito a mano

    def test_the_request_rejects_what_it_cannot_hold(self) -> None:
        """RF-015-01, RF-015-08: una plataforma sin nombre se rechaza (``des.entity_name_missing``);
        un modo o una métrica que no existen, ``ValueError``; un número que no lo es (un texto, un
        booleano), ``TypeError``."""
        for blank in ("", "  "):
            with self.subTest(name=blank), self.assertRaises(messages.DesignError) as caught:
                request(name=blank)
            self.assertEqual(caught.exception.code, "des.entity_name_missing")
        for name, wrong in (("mode", "fill"), ("metric", "chamfer3")):
            with self.subTest(name=name), self.assertRaises(ValueError):
                request(**{name: wrong})
        for name, wrong in (("reach_m", "50"), ("edge_angle_deg", True), ("guard_m", [1.0]),
                            ("max_slope_pct", "8")):
            with self.subTest(name=name), self.assertRaises(TypeError):
                request(**{name: wrong})
        for name, wrong in (("name", 7), ("feature", 7), ("start", 7), ("protect", 1)):
            with self.subTest(name=name), self.assertRaises(TypeError):
                request(**{name: wrong})
        with self.assertRaises(TypeError):
            request(fields="gis_fea_plataformas_ejes")


class EntityMessagesTest(unittest.TestCase):
    def test_codes_of_the_task(self) -> None:
        """Plan §5.1 (principio 10): los códigos ``des.entity_*`` y ``des.platform_*`` de esta
        tarea, cada uno con su gravedad y de una de las dos familias; ni un código ni un ``msgid``
        se repite."""
        for code, severity in CODES.items():
            with self.subTest(code=code):
                self.assertIn(code, messages.MESSAGES)
                self.assertEqual(messages.MESSAGES[code].severity, severity)
                self.assertTrue(code.startswith(FAMILIES), code)
                self.assertRegex(code, r"^des\.[a-z][a-z0-9_]*$")
        found = [m.code for m in messages.CATALOG if m.code.startswith(FAMILIES)]
        self.assertEqual(sorted(found), sorted(CODES))
        self.assertEqual(len({m.msgid for m in messages.CATALOG}), len(messages.CATALOG))

    def test_both_languages_with_the_same_placeholders(self) -> None:
        """Principio 10: cada código tiene su ``msgid`` en inglés (sin letras del español) y su
        texto en español, distintos, con los mismos marcadores con nombre en inglés; ``CATALOG_ES``
        da el mismo español que ``render``; el singular, donde el mensaje cuenta algo, igual."""
        for code in CODES:
            message = messages.MESSAGES[code]
            with self.subTest(code=code):
                self.assertTrue(message.msgid.strip() and message.es.strip())
                self.assertNotEqual(message.msgid, message.es)
                self.assertEqual(set(message.msgid) & SPANISH_LETTERS, set())
                self.assertEqual(i18n.placeholders(message.msgid), i18n.placeholders(message.es))
                for name in i18n.placeholders(message.es):
                    self.assertRegex(name, r"^[a-z][a-z_]*$")
                self.assertEqual(messages.CATALOG_ES[message.msgid], message.es)
                values = {name: name.upper() for name in i18n.placeholders(message.es)}
                self.assertEqual(messages.render(code, **values), message.es.format(**values))
                self.assertEqual(messages.render(code, language="en", **values),
                                 message.msgid.format(**values))
                if message.count:
                    self.assertIn(message.count, i18n.placeholders(message.es))
                    for text in (message.one_msgid, message.one_es):
                        self.assertEqual(i18n.placeholders(text),
                                         i18n.placeholders(message.es))
                    self.assertEqual(set(message.one_msgid) & SPANISH_LETTERS, set())
                    self.assertEqual(messages.CATALOG_ES[message.one_msgid], message.one_es)
                self.assertNotIn("….", message.es)
                self.assertNotIn("….", message.msgid)

    def test_every_error_is_raised_with_its_object_field_and_value(self) -> None:
        """RF-015-08: cada error se lanza como ``DesignError`` con objeto, campo y valor y su texto
        sin marcadores; un aviso o una nota no se lanzan (``ValueError``) y se escriben con
        ``render``."""
        for code, severity in CODES.items():
            message = messages.MESSAGES[code]
            values = {name: "V" for name in i18n.placeholders(message.es)}
            with self.subTest(code=code):
                if severity == "error":
                    values.pop("field", None)
                    values.pop("value", None)
                    error = messages.DesignError(code, obj="Objeto", field="campo", value=7,
                                                 **values)
                    self.assertNotIn("{", error.text)
                    self.assertNotIn("?", error.text.replace("¿", ""))
                else:
                    with self.assertRaises(ValueError):
                        messages.DesignError(code, obj="Objeto", field="campo")
                    self.assertNotIn("{", messages.render(code, **values))

    def test_the_texts_with_the_numbers_that_matter(self) -> None:
        """RF-015-08, RF-015-09, RF-015-13, RF-015-19, RF-015-23, RF-015-24: los rechazos nombran la
        capa, la plataforma y el valor; los avisos dan el área (m²), la cuantía (m), la abscisa
        (m) y las coordenadas absolutas del centro; el de la contrapendiente pide la confirmación
        expresa y el del eje principal dice por dónde va el sentido."""
        counter = messages.render("des.platform_counter_slope", entity="P1", amount=0.35,
                                  chainage=120.0, x="725 010,5", y="4 400 020,5",
                                  tolerance=0.1)
        self.assertEqual(counter, (
            "Plataforma «P1»: su perfil longitudinal sube 0,35 m en contra del sentido en que "
            "baja su rasante, en la abscisa 120 m (x = 725 010,5 m, y = 4 400 020,5 m), más que "
            "su tolerancia de 0,1 m; confirme para crearla con esta contrapendiente."))
        self.assertIn("confirm to create it", messages.render(
            "des.platform_counter_slope", language="en", entity="P1", amount=0.35,
            chainage=120.0, x="1", y="2", tolerance=0.1))
        principal = messages.render("des.platform_axis_principal", entity="P1", x=10.5, y=20.5,
                                    x_end=110.5, y_end=20.5)
        self.assertIn("eje principal", principal)
        self.assertIn("abscisa 0", principal)
        self.assertIn("x = 110,5 m", principal)
        level = messages.DesignError("des.platform_level_range", obj="Capa «gis_fea_plataformas»",
                                     field="cota_inicial", value=5000.0, layer="gis_fea_plataformas",
                                     entity="P1", low=-819.84375, high=1307.84375)
        self.assertIn("«gis_fea_plataformas»", level.text)
        self.assertIn("«P1»", level.text)
        self.assertIn("«cota_inicial» = 5000 m", level.text)
        self.assertIn("de -819,84375 a 1307,84375 m", level.text)
        nodata = messages.DesignError("des.entity_nodata", obj="Plataforma «P1»", field="start",
                                      value=None, entity="P1", area=1250.0, surface="gis_dtm",
                                      role="partida", x=10.5, y=20.5)
        self.assertIn("1250 m²", nodata.text)
        self.assertIn("«gis_dtm» (partida)", nodata.text)
        self.assertIn("x = 10,5 m, y = 20,5 m", nodata.text)
        held = messages.render("des.entity_held", entity="P2", area=300.0, constraint="dec__plt_001",
                               other="P1", x=1, y=2)
        self.assertIn("300 m²", held)
        self.assertIn("«dec__plt_001»", held)
        self.assertIn("«P1»", held)
        taken = messages.DesignError("des.entity_start_taken", obj="Plataforma «P2»",
                                     field="start", value="gis_dtm", entity="P2", other="P1")
        self.assertIn("«gis_dtm»", taken.text)
        self.assertIn("«P1»", taken.text)
        self.assertIn("inserte la nueva antes o después", taken.text)

    def test_a_count_of_one_takes_its_singular(self) -> None:
        """RF-015-13, RF-015-14, RF-015-24 (spec 014, T51): los mensajes que cuentan algo llevan su
        singular, en los dos idiomas: «en 1 celda», «en 1 grupo» (no «en 1 celdas»); con otro
        número, el plural."""
        cases = (
            ("des.entity_edge_outside", "cells", {"entity": "P1", "area": 1, "x": 1, "y": 2},
             "en 1 celda (", "in 1 cell (", "en 2 celdas (", "in 2 cells ("),
            ("des.entity_quarry_order", "cells",
             {"entity": "P1", "surface": "s", "quarry": "q", "other": "o", "area": 1, "above": 1,
              "x": 1, "y": 2},
             "1 celda (", "1 cell (", "2 celdas (", "2 cells ("),
            ("des.platform_below", "groups", {"entity": "P1", "area": 1, "maximum": 1},
             "en 1 grupo", "in 1 group", "en 2 grupos", "in 2 groups"),
            ("des.platform_above", "groups", {"entity": "P1", "area": 1, "maximum": 1},
             "en 1 grupo", "in 1 group", "en 2 grupos", "in 2 groups"),
            ("des.platform_below_group", "cells",
             {"group": 1, "area": 1, "maximum": 1, "x": 1, "y": 2},
             ": 1 celda,", ": 1 cell,", ": 2 celdas,", ": 2 cells,"),
            ("des.platform_above_group", "cells",
             {"group": 1, "area": 1, "maximum": 1, "x": 1, "y": 2},
             ": 1 celda,", ": 1 cell,", ": 2 celdas,", ": 2 cells,"),
            ("des.platform_more_groups", "groups", {},
             "y 1 grupo más", "and 1 more group", "y 2 grupos más", "and 2 more groups"),
            ("des.entity_obsolete_consumers", "operations", {"items": "«Cantera»"},
             "Con ellas quedará obsoleta 1 operación", "With them, 1 operation",
             "quedarán obsoletas 2 operaciones", "2 operations"),
            ("des.entity_obsolete_successor", "entities", {"entity": "P1", "items": "«P2»"},
             "quedará obsoleta 1 entidad", "1 entity of the chain",
             "quedarán obsoletas 2 entidades", "2 entities of the chain"),
            ("des.entity_obsolete_dependents", "operations", {"entity": "P1", "items": "«Q»"},
             "quedará obsoleta 1 operación", "1 operation that depended",
             "quedarán obsoletas 2 operaciones", "2 operations that depended"),
            ("des.entity_chain_obsolete", "operations", {"items": "«P1»"},
             "ha quedado obsoleta 1 operación", "1 operation that used the old ones is now stale",
             "han quedado obsoletas 2 operaciones", "2 operations that used the old ones are now stale"))
        for code, count, rest, one_es, one_en, many_es, many_en in cases:
            self.assertEqual(messages.MESSAGES[code].count, count)
            with self.subTest(code=code):
                self.assertIn(one_es, messages.render(code, **{count: 1}, **rest))
                self.assertIn(one_en, messages.render(code, language="en", **{count: 1}, **rest))
                for language in ("es", "en"):
                    self.assertNotRegex(
                        messages.render(code, language=language, **{count: 1}, **rest),
                        r"\b1 (celdas|grupos|cells|groups)\b")
                self.assertIn(many_es, messages.render(code, **{count: 2}, **rest))
                self.assertIn(many_en, messages.render(code, language="en", **{count: 2}, **rest))

    def test_the_catalog_still_checks_itself(self) -> None:
        """Los mensajes nuevos pasan la comprobación del catálogo (``_check_catalog``: códigos y
        ``msgid`` sin repetir, gravedad conocida, singulares completos) y el español de cada uno
        llega a ``core.i18n`` por ``CATALOG_ES``."""
        messages._check_catalog()
        for code in CODES:
            message = messages.MESSAGES[code]
            self.assertEqual(messages.CATALOG_ES[message.msgid], message.es)


if __name__ == "__main__":
    unittest.main()
