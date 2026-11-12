# SPDX-License-Identifier: GPL-3.0-or-later
"""Parámetros de las envolventes y el escalonado (spec 013, T02; HU-013-4; RF-013-08,
RF-013-18; plan 013 §5.2.2, D-7, D-17, D-24; ADR-0027 y ADR-0029; RF-008-01 a RF-008-06).

``design.params`` declara con el ``ParamDef`` de ``core.params`` (spec 008):

- las **familias** de un perfil de banco, de versión (RF-009-24): ``des.bench.{p}.height_m``,
  ``.face_deg``, ``.berm_m`` y ``.anchor_m`` **sin valor por defecto** (D-7: una altura o una cara
  supuestas acabarían en un plano) y HIPÓTESIS, y ``.mesh_factor`` con 1,0 ADOPTADO «sin confirmar»;
- la familia ``des.sector.{s}.max_general_slope_deg``, el talud general máximo impuesto de un
  sector (RF-013-08; ADR-0029), de versión y sin valor por defecto;
- los dos parámetros del proyecto ``des.tolerance.face_deg`` (1,0 °) y
  ``des.warning.magnitude_ratio`` (2,0), ADOPTADO «sin confirmar».

Un ángulo es un número de 0 a 90 **ambos excluidos** (RF-013-08, RF-013-18): ``ParamDef`` solo
excluye el mínimo, así que el 90 se rechaza además con ``design.params.check_*``.
"""

from __future__ import annotations

import math
import unittest

from tests.support.package import import_geoblender

params = import_geoblender("design.params")
model = import_geoblender("design.model")
messages = import_geoblender("design.messages")
core_params = import_geoblender("core.params")
units = import_geoblender("core.units")
i18n = import_geoblender("core.i18n")

ParamError = core_params.ParamError
SPANISH_LETTERS = frozenset("áéíóúüñÁÉÍÓÚÜÑ¿¡")
FACE_TOLERANCE = "des.tolerance.face_deg"
MAGNITUDE_RATIO = "des.warning.magnitude_ratio"

# Plan 013 §5.2.2, en su orden: patrón → (último segmento, unidad, valor por defecto, mínimo,
# máximo, mínimo excluido, tipo, RF).
FAMILIES: dict[str, tuple[str, str, float | None, float, float, bool, str, tuple[str, ...]]] = {
    "des.bench.{p}.height_m": ("height_m", "m", None, 0.0, 100.0, True, "HIPÓTESIS",
                               ("RF-013-18", "RF-013-22")),
    "des.bench.{p}.face_deg": ("face_deg", "deg", None, 0.0, 90.0, True, "HIPÓTESIS",
                               ("RF-013-18", "RF-013-22")),
    "des.bench.{p}.berm_m": ("berm_m", "m", None, 0.0, 100.0, False, "HIPÓTESIS",
                             ("RF-013-18", "RF-013-25")),
    "des.bench.{p}.anchor_m": ("anchor_m", "m", None, -1000.0, 10000.0, False, "HIPÓTESIS",
                               ("RF-013-18", "RF-013-24")),
    "des.bench.{p}.mesh_factor": ("mesh_factor", "-", 1.0, 0.0, 1.0, True, "ADOPTADO",
                                  ("RF-013-18", "RF-013-11")),
    "des.sector.{s}.max_general_slope_deg": (
        "max_general_slope_deg", "deg", None, 0.0, 90.0, True, "ADOPTADO",
        ("RF-013-08", "RF-013-09", "RF-013-13", "RF-013-25")),
}


class ProjectParametersTest(unittest.TestCase):
    def test_the_two_project_parameters_of_the_plan(self) -> None:
        """RF-013-27, RF-013-30 (plan §5.2.2, D-7): ``des.tolerance.face_deg`` (1,0 °, en
        (0; 10] °) y ``des.warning.magnitude_ratio`` (2,0, en (1; 1 000]), en su orden, del
        módulo ``des``, del proyecto (no por versión), ADOPTADO de origen ``algorithm`` («sin
        confirmar» hasta que una persona los confirma), con su procedencia y sus RF."""
        self.assertEqual([item.key for item in params.DEFINITIONS],
                         [FACE_TOLERANCE, MAGNITUDE_RATIO])
        self.assertEqual(list(params.PARAMS), [FACE_TOLERANCE, MAGNITUDE_RATIO])
        self.assertEqual((params.TOLERANCE_FACE, params.WARNING_RATIO),
                         (FACE_TOLERANCE, MAGNITUDE_RATIO))
        expected = {FACE_TOLERANCE: ("deg", 1.0, 0.0, 10.0, ("RF-013-27", "RF-013-30")),
                    MAGNITUDE_RATIO: ("-", 2.0, 1.0, 1000.0, ("RF-013-30",))}
        for key, (unit, default, low, high, rfs) in expected.items():
            definition = params.PARAMS[key]
            with self.subTest(key=key):
                self.assertIsInstance(definition, core_params.ParamDef)
                self.assertEqual(definition.module, "des")
                self.assertEqual((definition.value_type, definition.unit), ("float", unit))
                self.assertIn(unit, units.UNITS)
                self.assertEqual(definition.default, default)
                self.assertIs(type(definition.default), float)
                self.assertEqual((definition.minimum, definition.maximum), (low, high))
                self.assertTrue(definition.min_exclusive)
                self.assertEqual((definition.kind, definition.source_kind, definition.scope),
                                 ("ADOPTADO", "algorithm", "project"))
                self.assertFalse(definition.allow_empty)
                self.assertEqual(definition.requirements, rfs)
                self.assertIn("D-7", definition.source)
                self.assertEqual(definition.check(default), default)
                self.assertEqual(definition.check(high), high)
                for outside in (low, high + 1e-9):
                    with self.assertRaises(ParamError) as caught:
                        definition.check(outside)
                    self.assertEqual(caught.exception.code, "core.param_out_of_range")
                    self.assertEqual(caught.exception.field, key)
                with self.assertRaises(ParamError) as caught:
                    definition.check(None)
                self.assertEqual(caught.exception.code, "core.param_missing")
        self.assertEqual(params.PARAMS[FACE_TOLERANCE].range_text(), "(0; 10] °")
        self.assertEqual(params.PARAMS[MAGNITUDE_RATIO].range_text(), "(1; 1 000]")

    def test_registered_and_removed_without_trace(self) -> None:
        """RF-008-01 (plan §5.3.3): ``bl`` las registra en ``core.params`` y las quita con
        ``unregister_definitions("des")`` sin dejar rastro; registrarlas dos veces es un error
        del programa."""
        before = dict(core_params.DEFINITIONS)
        self.addCleanup(core_params.unregister_definitions, "des")
        core_params.register_definitions(params.DEFINITIONS)
        for definition in params.DEFINITIONS:
            self.assertIs(core_params.DEFINITIONS[definition.key], definition)
        with self.assertRaises(ValueError):
            core_params.register_definitions(params.DEFINITIONS)
        self.assertEqual(core_params.unregister_definitions("des"), 2)
        self.assertEqual(dict(core_params.DEFINITIONS), before)


class QuarryParametersTest(unittest.TestCase):
    def test_the_014_ones_are_apart_and_registered_with_the_others(self) -> None:
        """RF-014-02, RF-014-07, RF-014-17, RF-014-19, RF-014-21 (plan 014 §5.2.2; spec 014,
        T02): los siete de la 014 van aparte de los dos del proyecto de la 013 (en
        ``QUARRY_DEFINITIONS``, de versión), no repiten ninguna clave ni etiqueta, y ``bl`` puede
        registrarlos con ellos y quitarlos sin dejar rastro. Su detalle (rango, valor y
        procedencia) está en ``tests/unit/design/test_quarry_model.py``."""
        quarry = params.QUARRY_DEFINITIONS
        self.assertEqual(len(quarry), 7)
        self.assertEqual(set(params.QUARRY_PARAMS), {item.key for item in quarry})
        self.assertFalse(set(params.QUARRY_PARAMS) & set(params.PARAMS))
        self.assertTrue(all(item.scope == "version" for item in quarry))
        every = (*params.DEFINITIONS, *quarry, *(family.template for family in params.FAMILIES))
        labels = [item.label_msgid for item in every]
        self.assertEqual(len(set(labels)), len(labels), "etiquetas repetidas")
        before = dict(core_params.DEFINITIONS)
        self.addCleanup(core_params.unregister_definitions, "des")
        core_params.register_definitions((*params.DEFINITIONS, *quarry))
        self.assertIs(core_params.DEFINITIONS[params.CROWN_RING], params.QUARRY_PARAMS[
            params.CROWN_RING])
        self.assertEqual(core_params.definition(params.EDGE_MIN_SHARE).default, 99.0)
        self.assertIsNone(core_params.definition(params.CONSERVE_SLOPE).default)
        self.assertEqual(core_params.unregister_definitions("des"), 9)
        self.assertEqual(dict(core_params.DEFINITIONS), before)


class FamiliesTest(unittest.TestCase):
    def test_the_six_families_of_the_plan(self) -> None:
        """RF-013-08, RF-013-18 (plan §5.2.2, D-7, D-17, ADR-0029): las cuatro familias de un
        perfil sin valor por defecto (altura, cara, berma y ancla: HIPÓTESIS hasta que una
        persona las declara), el factor de malla con 1,0 ADOPTADO, y el talud general máximo
        impuesto de un sector sin valor por defecto; todas de versión (RF-009-24), con la
        unidad, el rango y los RF del plan."""
        self.assertEqual([family.pattern for family in params.FAMILIES], list(FAMILIES))
        for family in params.FAMILIES:
            (_last, unit, default, low, high, low_excluded, kind,
             rfs) = FAMILIES[family.pattern]
            template = family.template
            with self.subTest(pattern=family.pattern):
                self.assertIsInstance(family, core_params.ParamFamily)
                self.assertEqual(family.module, "des")
                self.assertEqual((template.value_type, template.unit), ("float", unit))
                self.assertIn(unit, units.UNITS)
                self.assertEqual(template.default, default)
                self.assertEqual(template.allow_empty, default is None)
                self.assertEqual((template.minimum, template.maximum), (low, high))
                self.assertIs(template.min_exclusive, low_excluded)
                self.assertEqual(template.kind, kind)
                self.assertEqual(template.scope, "version")
                self.assertEqual(template.requirements, rfs)
                self.assertTrue(template.source.strip(), "sin procedencia")
                if default is None:
                    self.assertIsNone(template.check(None))
                    self.assertEqual(template.source_kind, "person")
                else:
                    self.assertEqual(template.source_kind, "algorithm")
                    with self.assertRaises(ParamError) as caught:
                        template.check(None)
                    self.assertEqual(caught.exception.code, "core.param_missing")
        for one in params.FAMILIES:
            for other in params.FAMILIES:
                if one is not other:
                    self.assertFalse(one.overlaps(other), (one.pattern, other.pattern))

    def test_height_face_berm_anchor_have_no_value_and_mesh_factor_is_one(self) -> None:
        """RF-013-18 (D-7): la altura, la cara, la berma y el ancla no tienen valor por defecto
        (ninguna cifra minera supuesta) y el factor de malla vale 1,0 ADOPTADO; los extremos
        incluidos del rango se aceptan y lo de fuera, no (``core.param_out_of_range``); la
        altura de banco no admite 0 ni más de 100 m, la berma sí 0 m y el ancla, negativa."""
        by_last = {FAMILIES[pattern][0]: family.template
                   for pattern, family in zip(FAMILIES, params.FAMILIES, strict=True)}
        for last in ("height_m", "face_deg", "berm_m", "anchor_m"):
            self.assertIsNone(by_last[last].default, last)
        self.assertEqual(by_last["mesh_factor"].default, 1.0)
        self.assertEqual(by_last["height_m"].check(100), 100.0)
        self.assertEqual(by_last["berm_m"].check(0), 0.0)
        self.assertEqual(by_last["anchor_m"].check(-1000), -1000.0)
        self.assertEqual(by_last["anchor_m"].check(10000), 10000.0)
        self.assertEqual(by_last["mesh_factor"].check(1), 1.0)
        for last, rejected in (("height_m", 0.0), ("height_m", 100.0001), ("face_deg", 0.0),
                               ("face_deg", 90.0001), ("berm_m", -0.01), ("berm_m", 100.01),
                               ("anchor_m", -1000.01), ("anchor_m", 10000.01),
                               ("mesh_factor", 0.0), ("mesh_factor", 1.0000001),
                               ("max_general_slope_deg", 0.0), ("max_general_slope_deg", 91)):
            with self.subTest(last=last, rejected=rejected):
                template = (by_last[last] if last in by_last
                            else params.FAMILIES[5].template)
                with self.assertRaises(ParamError) as caught:
                    template.check(rejected)
                self.assertEqual(caught.exception.code, "core.param_out_of_range")

    def test_keys_of_a_profile_and_of_a_sector(self) -> None:
        """RF-013-18, RF-013-08 (D-17, ADR-0029): la clave lleva el código del perfil o del
        sector, casa con su familia y con ninguna otra; el perímetro como sector único es
        ``perimeter__``; un código que no es ``[a-z][a-z0-9_]*`` es un error del programa."""
        keys = {
            params.bench_key("expl_10_60_6", params.BenchParam.HEIGHT):
                "des.bench.{p}.height_m",
            params.bench_key("expl_10_60_6", "face_deg"): "des.bench.{p}.face_deg",
            params.bench_key("rest_5_35_6", params.BenchParam.BERM): "des.bench.{p}.berm_m",
            params.bench_key("rest_5_35_6", params.BenchParam.ANCHOR):
                "des.bench.{p}.anchor_m",
            params.bench_key("desd_10_45_6", params.BenchParam.MESH_FACTOR):
                "des.bench.{p}.mesh_factor",
            params.sector_slope_key("sector_2"): "des.sector.{s}.max_general_slope_deg",
            params.sector_slope_key(model.PERIMETER_SEGMENT):
                "des.sector.{s}.max_general_slope_deg",
        }
        self.assertEqual(list(keys), [
            "des.bench.expl_10_60_6.height_m", "des.bench.expl_10_60_6.face_deg",
            "des.bench.rest_5_35_6.berm_m", "des.bench.rest_5_35_6.anchor_m",
            "des.bench.desd_10_45_6.mesh_factor", "des.sector.sector_2.max_general_slope_deg",
            "des.sector.perimeter__.max_general_slope_deg"])
        for key, pattern in keys.items():
            with self.subTest(key=key):
                matching = [family.pattern for family in params.FAMILIES
                            if family.match(key) is not None]
                self.assertEqual(matching, [pattern])
        for wrong in ("Expl", "1expl", "", "expl 10", "expl.10", "expl_10_60_6 ", "ñu"):
            with self.subTest(code=wrong):
                with self.assertRaises(ValueError):
                    params.bench_key(wrong, params.BenchParam.HEIGHT)
                with self.assertRaises(ValueError):
                    params.sector_slope_key(wrong)
        with self.assertRaises(ValueError):
            params.bench_key("expl_10_60_6", "height")

    def test_labels_with_their_spanish(self) -> None:
        """RF-008-06 (principio 10): cada definición lleva su etiqueta para el panel de
        parámetros: un ``msgid`` en inglés, sin marcadores, con su español en
        ``core/i18n/messages.toml`` (que no es el mismo texto)."""
        table = i18n.load_messages()
        definitions = (*params.DEFINITIONS, *(family.template for family in params.FAMILIES))
        labels = [definition.label_msgid for definition in definitions]
        self.assertEqual(len(set(labels)), len(definitions), "etiquetas repetidas o sin ella")
        for definition in definitions:
            label = definition.label_msgid
            with self.subTest(key=definition.key, label=label):
                self.assertIsInstance(label, str)
                self.assertTrue(label.strip())
                self.assertEqual(set(label) & SPANISH_LETTERS, set(), "msgid en inglés")
                self.assertEqual(i18n.placeholders(label), set())
                self.assertIn(label, table)
                self.assertNotEqual(table[label], label)

    def test_registration_and_removal_without_trace(self) -> None:
        """RF-008-06, RF-013-18 (ADR-0027): ``bl`` registra las familias y las quita con
        ``unregister_families("des")`` sin dejar rastro; registrada, ``definition`` da la de una
        clave concreta (``mesh_factor`` con su 1,0; la altura sin valor) y su nombre visible lleva
        el código («Altura de banco · expl_10_60_6»); registrarlas dos veces es un error."""
        before = dict(core_params.FAMILIES)
        self.addCleanup(core_params.unregister_families, "des")
        core_params.register_families(params.FAMILIES)
        height = params.bench_key("expl_10_60_6", params.BenchParam.HEIGHT)
        mesh = params.bench_key("expl_10_60_6", params.BenchParam.MESH_FACTOR)
        slope = params.sector_slope_key("sector_2")
        found = core_params.definition(height)
        self.assertEqual((found.key, found.default), (height, None))
        self.assertEqual(core_params.definition(mesh).default, 1.0)
        self.assertEqual(core_params.definition(slope).scope, "version")
        self.assertEqual(core_params.parameter_label(height), "Altura de banco · expl_10_60_6")
        self.assertEqual(core_params.parameter_label(slope),
                         "Talud general máximo impuesto · sector_2")
        self.assertIsNone(core_params.definition("des.bench.Expl.height_m"))
        with self.assertRaises(ValueError):
            core_params.register_families(params.FAMILIES)
        self.assertEqual(core_params.unregister_families("des"), len(FAMILIES))
        self.assertEqual(dict(core_params.FAMILIES), before)
        self.assertIsNone(core_params.definition(height))


class RangesTest(unittest.TestCase):
    def test_angle_ranges_exclude_both_ends(self) -> None:
        """RF-013-08, RF-013-18: la cara de un banco y el talud impuesto de un sector son
        números de 0 a 90 °, **ambos excluidos** (tan 90° no existe); ``ParamDef`` solo excluye
        el mínimo, y ``design.params`` rechaza además el 90, con su rango escrito «(0; 90) °»."""
        for last in ("face_deg", "max_general_slope_deg"):
            span = params.RANGES[last]
            with self.subTest(last=last):
                self.assertEqual((span.minimum, span.maximum, span.unit), (0.0, 90.0, "deg"))
                self.assertTrue(span.min_exclusive)
                self.assertTrue(span.max_exclusive)
                self.assertEqual(span.text(), "(0; 90) °")
                self.assertEqual(span.text("en"), "(0, 90) deg")
                for inside in (1e-9, 10.6, 60.0, 89.999999999):
                    self.assertTrue(span.contains(inside), inside)
                for outside in (0.0, -1.0, 90.0, 90.0001, math.nan, math.inf, -math.inf):
                    self.assertFalse(span.contains(outside), outside)
        self.assertEqual(params.RANGES["height_m"].text(), "(0; 100] m")
        self.assertEqual(params.RANGES["berm_m"].text(), "[0; 100] m")
        self.assertEqual(params.RANGES["mesh_factor"].text(), "(0; 1]")
        self.assertTrue(params.RANGES["berm_m"].contains(0.0))
        self.assertFalse(params.RANGES["height_m"].contains(0.0))
        self.assertTrue(params.RANGES["anchor_m"].contains(-1000.0))
        self.assertEqual(set(params.RANGES),
                         {"height_m", "face_deg", "berm_m", "anchor_m", "mesh_factor",
                          "max_general_slope_deg"})

    def test_ranges_agree_with_the_declared_definitions(self) -> None:
        """RF-013-18: el rango de ``RANGES`` y el de la plantilla de cada familia son el mismo
        (salvo el máximo excluido que ``ParamDef`` no puede decir): una sola fuente."""
        for pattern, family in zip(FAMILIES, params.FAMILIES, strict=True):
            span = params.RANGES[FAMILIES[pattern][0]]
            template = family.template
            with self.subTest(pattern=pattern):
                self.assertEqual((span.minimum, span.maximum, span.min_exclusive, span.unit),
                                 (template.minimum, template.maximum, template.min_exclusive,
                                  template.unit))

    def test_sector_slope_check_names_the_sector_the_field_and_the_value(self) -> None:
        """RF-013-08, principio 10: un talud impuesto fuera de (0; 90) ° (también el 90, NaN o
        infinito) se rechaza antes de usarlo con ``des.sector_slope_range``, nombrando el
        sector, la clave del campo y el valor; uno válido vuelve como ``float``."""
        self.assertEqual(params.check_sector_slope("sector_2", 10.6), 10.6)
        self.assertIs(type(params.check_sector_slope("sector_2", 18)), float)
        key = "des.sector.sector_2.max_general_slope_deg"
        for wrong in (0, -3.0, 90, 120.5, math.nan, math.inf):
            with self.subTest(value=wrong):
                with self.assertRaises(messages.DesignError) as caught:
                    params.check_sector_slope("sector_2", wrong)
                error = caught.exception
                self.assertEqual(error.code, "des.sector_slope_range")
                self.assertEqual((error.field, error.obj), (key, "Sector «sector_2»"))
                self.assertIn("(0; 90) °", error.text)
                self.assertIn("sector_2", error.text)
        with self.assertRaises(TypeError):
            params.check_sector_slope("sector_2", "10")
        with self.assertRaises(TypeError):
            params.check_sector_slope("sector_2", True)
        with self.assertRaises(ValueError):
            params.check_sector_slope("Sector 2", 10.0)

    def test_perimeter_segment(self) -> None:
        """RF-013-05, RF-013-09 (ADR-0029, D-23): ``perimeter__`` es un código válido de
        sector (el perímetro de actuación como sector único), y tiene su clave de talud."""
        self.assertEqual(model.PERIMETER_SEGMENT, "perimeter__")
        self.assertEqual(params.sector_slope_key(model.PERIMETER_SEGMENT),
                         "des.sector.perimeter__.max_general_slope_deg")
        self.assertTrue(params.is_code(model.PERIMETER_SEGMENT))
        self.assertFalse(params.is_code("Perimeter"))


class ThicknessKeyTest(unittest.TestCase):
    def test_minimum_thickness_is_read_by_its_key(self) -> None:
        """RF-013-30 (plan §5.2.2, D-24): ``design`` lee el espesor mínimo del informe por su
        clave de la 012, sin importar ``reserves``; que ``reserves`` la sigue declarando lo
        comprueba ``tests/unit/architecture/test_design_package.py`` (sin importar ``reserves``)."""
        self.assertEqual(params.VERIFY_MIN_THICKNESS, "res.verify.min_thickness_m")
        self.assertTrue(params.VERIFY_MIN_THICKNESS.startswith("res."))
        self.assertNotIn(params.VERIFY_MIN_THICKNESS, params.PARAMS)


if __name__ == "__main__":
    unittest.main()
