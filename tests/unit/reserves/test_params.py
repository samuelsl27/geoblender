# SPDX-License-Identifier: GPL-3.0-or-later
"""Parámetros de la cubicación (spec 011, T03; HU-011-1; RF-011-04, RF-011-14, RF-011-19;
plan 011 §5.2.2; D-6, D-7 y D-14 (e) de la spec; RF-008-01 a RF-008-06).

``reserves.params`` declara con el ``ParamDef`` de ``core.params`` (spec 008) los tres
parámetros del proyecto de la tabla del plan §5.2.2, todos ADOPTADO de origen ``algorithm``
(«sin confirmar» en el proyecto hasta que una persona los confirma) y de ámbito
``project`` (RF-011-21: solo del proyecto), cada uno con su etiqueta en
``core/i18n/messages.toml``:

- ``res.min_thickness_m``, el espesor mínimo (umbral, D-6): 0 m en [0; 10] m;
- ``res.anthropic_presence_m``, el umbral único de presencia de lo antrópico (D-7): 0,30 m en
  [0; 10] m;
- ``res.stages_tolerance_pct``, la tolerancia de los momentos de extracción (D-14 e): 1 % en
  (0; 100] %.

Y, **sin registrar**, el de la altura de banco (``res.bench_height_m``, (0; 100] m, sin valor
por defecto): las rodajas son ajustes de cada cubicación, no parámetros del proyecto, y su
``ParamDef`` solo comprueba el rango (RF-008-03; plan §5.2.2).

Las **familias** (ADR-0027; T09): la densidad in situ y el K de cada unidad y de cada componente
y el porcentaje de cada componente (``res.unit.{u}.density``, ``res.unit.{u}.{c}.percent``…),
con el código inmutable de la unidad y del componente (D-18), **sin valor por defecto** (D-8) y
HIPÓTESIS; la densidad, del proyecto, y el K y los porcentajes, de versión (D-11). Importar el
módulo no registra nada.
"""

from __future__ import annotations

import math
import unittest

from tests.support.package import import_geoblender

params = import_geoblender("reserves.params")
core_params = import_geoblender("core.params")
units = import_geoblender("core.units")
i18n = import_geoblender("core.i18n")

ParamError = core_params.ParamError
SPANISH_LETTERS = frozenset("áéíóúüñÁÉÍÓÚÜÑ¿¡")
MIN_THICKNESS = "res.min_thickness_m"
PRESENCE = "res.anthropic_presence_m"
STAGES = "res.stages_tolerance_pct"
BENCH = "res.bench_height_m"

# Plan 011 §5.2.2, en su orden: clave → (unidad, valor por defecto, mínimo, máximo, mínimo
# excluido, RF). Los valores por defecto son los de D-6, D-7 y D-14 (e) de la spec.
EXPECTED: dict[str, tuple[str, float, float, float, bool, tuple[str, ...]]] = {
    MIN_THICKNESS: ("m", 0.0, 0.0, 10.0, False, ("RF-011-04",)),
    PRESENCE: ("m", 0.30, 0.0, 10.0, False, ("RF-011-14",)),
    STAGES: ("%", 1.0, 0.0, 100.0, True, ("RF-011-19",)),
}


class DefinitionsTest(unittest.TestCase):
    def test_the_three_project_parameters_of_the_plan(self) -> None:
        """RF-011-04, RF-011-14, RF-011-19, RF-008-01 (plan §5.2.2): las tres claves del plan,
        en su orden y sin repetir, con el ``ParamDef`` de ``core.params`` del módulo ``res``,
        por clave en ``PARAMS``; la altura de banco no está entre las que se registran."""
        self.assertEqual([definition.key for definition in params.DEFINITIONS], list(EXPECTED))
        self.assertEqual(list(params.PARAMS), list(EXPECTED))
        self.assertEqual((params.MIN_THICKNESS, params.ANTHROPIC_PRESENCE,
                          params.STAGES_TOLERANCE, params.BENCH_HEIGHT),
                         (MIN_THICKNESS, PRESENCE, STAGES, BENCH))
        for definition in params.DEFINITIONS:
            with self.subTest(key=definition.key):
                self.assertIsInstance(definition, core_params.ParamDef)
                self.assertEqual(definition.module, "res")
                self.assertIs(params.param(definition.key), definition)
        self.assertNotIn(BENCH, params.PARAMS)
        self.assertNotIn(params.BENCH_HEIGHT_DEF, params.DEFINITIONS)

    def test_defaults_units_ranges_type_and_scope(self) -> None:
        """RF-011-04, RF-011-14, RF-011-19, RF-011-21, RF-008-01, RF-008-04 (D-6, D-7,
        D-14 e): el tipo de valor (``float``), la unidad del catálogo, el valor por defecto
        (0 m, 0,30 m y 1 %), el rango, ADOPTADO de origen ``algorithm``, del proyecto (no
        por versión), con su procedencia y los RF que lo usan; ninguno admite «sin valor»."""
        for key, (unit, default, low, high, low_excluded, rfs) in EXPECTED.items():
            with self.subTest(key=key):
                definition = params.param(key)
                self.assertEqual(definition.value_type, "float")
                self.assertEqual(definition.unit, unit)
                self.assertIn(unit, units.UNITS)
                self.assertEqual(definition.default, default)
                self.assertIs(type(definition.default), float)
                self.assertEqual((definition.minimum, definition.maximum), (low, high))
                self.assertIs(definition.min_exclusive, low_excluded)
                self.assertEqual(definition.kind, "ADOPTADO")
                self.assertEqual(definition.source_kind, "algorithm")
                self.assertEqual(definition.scope, "project")
                self.assertFalse(definition.allow_empty)
                self.assertTrue(definition.source.strip(), "sin procedencia")
                self.assertEqual(definition.requirements, rfs)
                self.assertEqual(params.default(key), default)
        self.assertEqual(params.param(MIN_THICKNESS).range_text(), "[0; 10] m")
        self.assertEqual(params.param(PRESENCE).range_text(), "[0; 10] m")
        self.assertEqual(params.param(STAGES).range_text(), "(0; 100] %")
        self.assertEqual(params.param(STAGES).range_text("en"), "(0, 100] %")

    def test_ranges_are_validated(self) -> None:
        """RF-011-04, RF-011-14, RF-011-19, RF-008-03: ``check`` acepta el valor por defecto y
        los extremos incluidos del rango y rechaza lo de fuera con ``ParamError``
        ``core.param_out_of_range``, con la clave como campo y en el mensaje; un booleano,
        un texto, NaN o «sin valor», tampoco; «0,5 m» tecleado es 0,5."""
        for key, (_unit, default, low, high, low_excluded, _rfs) in EXPECTED.items():
            definition = params.param(key)
            with self.subTest(key=key):
                self.assertEqual(definition.check(default), default)
                if not low_excluded:
                    self.assertEqual(definition.check(low), low)
                self.assertEqual(definition.check(high), high)
                self.assertIs(type(definition.check(1)), float)
                for outside in (high + 1e-9, low if low_excluded else low - 1e-9):
                    with self.assertRaises(ParamError) as caught:
                        definition.check(outside)
                    self.assertEqual(caught.exception.code, "core.param_out_of_range")
                    self.assertEqual(caught.exception.field, key)
                    self.assertIn(f"«{key}»", str(caught.exception))
                for wrong, code in ((True, "core.param_not_number"),
                                    ("0,5", "core.param_not_number"),
                                    (math.nan, "core.param_not_number"),
                                    (None, "core.param_missing")):
                    with self.assertRaises(ParamError) as caught:
                        definition.check(wrong)
                    self.assertEqual(caught.exception.code, code)
        with self.assertRaises(ParamError) as caught:
            params.param(PRESENCE).check(-0.1)
        self.assertEqual(str(caught.exception),
                         "Parámetro «res.anthropic_presence_m»: -0,1 está fuera de su rango "
                         "[0; 10] m.")
        self.assertEqual(core_params.parse_value(params.param(MIN_THICKNESS), "0,5 m"), 0.5)
        self.assertEqual(core_params.parse_value(params.param(PRESENCE), "0,3"), 0.3)
        self.assertEqual(core_params.parse_value(params.param(STAGES), "2,5 %"), 2.5)

    def test_bench_height_is_checked_but_not_registered(self) -> None:
        """RF-011-09, RF-008-03 (plan §5.2.2 y A4): la altura de banco tiene su ``ParamDef``,
        de la ``res``, en m, con rango (0; 100] (el 0 excluido) y sin valor por defecto (cada
        cubicación la escribe), que no está entre las definiciones que se registran: solo
        comprueba el ajuste de una cubicación."""
        bench = params.BENCH_HEIGHT_DEF
        self.assertIsInstance(bench, core_params.ParamDef)
        self.assertEqual((bench.key, bench.module, bench.value_type, bench.unit),
                         (BENCH, "res", "float", "m"))
        self.assertEqual((bench.minimum, bench.maximum, bench.min_exclusive),
                         (0.0, 100.0, True))
        self.assertIsNone(bench.default)
        self.assertTrue(bench.allow_empty)
        self.assertEqual(bench.requirements, ("RF-011-09",))
        self.assertTrue(bench.source.strip())
        self.assertEqual(bench.range_text(), "(0; 100] m")
        self.assertIs(params.param(BENCH), bench)
        self.assertIsNone(params.default(BENCH))
        for accepted in (0.5, 10, 15.0, 100.0):
            self.assertEqual(bench.check(accepted), float(accepted))
        for rejected in (0.0, -10.0, 100.001, 1e9):
            with self.subTest(altura=rejected):
                with self.assertRaises(ParamError) as caught:
                    bench.check(rejected)
                self.assertEqual(caught.exception.code, "core.param_out_of_range")
                self.assertEqual(caught.exception.field, BENCH)

    def test_labels_with_their_spanish(self) -> None:
        """RF-008-06 (principio 10): cada definición, también la de la altura de banco, lleva
        su etiqueta para el panel de parámetros y los ajustes: un ``msgid`` en inglés, distinto
        en cada una y sin marcadores, con su español en ``core/i18n/messages.toml``."""
        table = i18n.load_messages()
        definitions = (*params.DEFINITIONS, params.BENCH_HEIGHT_DEF)
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

    def test_unknown_key_and_repeated_key(self) -> None:
        """Una clave que no es de la cubicación es un error del programa (``KeyError``); un
        índice con una clave repetida, también (``ValueError``: no se pierde en silencio)."""
        with self.assertRaisesRegex(KeyError, "res.no_such"):
            params.param("res.no_such")
        first = params.DEFINITIONS[0]
        with self.assertRaisesRegex(ValueError, first.key):
            params.index_definitions((first, first))


# Plan 011 §5.2.2: patrón → (unidad, mínimo, máximo, mínimo excluido, ámbito, RF).
FAMILIES: dict[str, tuple[str, float, float, bool, str, tuple[str, ...]]] = {
    "res.unit.{u}.density": ("t/m3", 0.0, 10.0, True, "project",
                             ("RF-011-11", "RF-011-16", "RF-011-17")),
    "res.unit.{u}.swell": ("-", 1.0, 3.0, False, "version",
                           ("RF-011-11", "RF-011-16", "RF-011-17", "RF-011-21")),
    "res.unit.{u}.{c}.density": ("t/m3", 0.0, 10.0, True, "project",
                                 ("RF-011-15", "RF-011-16", "RF-011-17")),
    "res.unit.{u}.{c}.swell": ("-", 1.0, 3.0, False, "version",
                               ("RF-011-15", "RF-011-16", "RF-011-17", "RF-011-21")),
    "res.unit.{u}.{c}.percent": ("%", 0.0, 100.0, False, "version", ("RF-011-15", "RF-011-21")),
}


class FamiliesTest(unittest.TestCase):
    def test_density_swell_and_percent_without_default(self) -> None:
        """RF-011-11, RF-011-15, RF-011-21 (ADR-0027, D-8, D-11): la densidad in situ (t/m³,
        (0; 10]) y el K (—, [1; 3]) de cada unidad y de cada componente y el porcentaje de cada
        componente (%, [0; 100]) son familias de ``res`` **sin valor por defecto** («sin
        valor» admitido, HIPÓTESIS hasta que una persona los declara); la densidad es del
        proyecto, y el K y los porcentajes, de versión."""
        self.assertEqual([family.pattern for family in params.FAMILIES], list(FAMILIES))
        for family in params.FAMILIES:
            unit, low, high, low_excluded, scope, rfs = FAMILIES[family.pattern]
            template = family.template
            with self.subTest(pattern=family.pattern):
                self.assertIsInstance(family, core_params.ParamFamily)
                self.assertEqual(family.module, "res")
                self.assertEqual((template.value_type, template.unit), ("float", unit))
                self.assertIsNone(template.default)
                self.assertTrue(template.allow_empty)
                self.assertIsNone(template.check(None))
                self.assertEqual(template.kind, "HIPÓTESIS")
                self.assertEqual((template.minimum, template.maximum), (low, high))
                self.assertIs(template.min_exclusive, low_excluded)
                self.assertEqual(template.scope, scope)
                self.assertEqual(template.requirements, rfs)
                self.assertTrue(template.source.strip())
        for one in params.FAMILIES:
            for other in params.FAMILIES:
                if one is not other:
                    self.assertFalse(one.overlaps(other), (one.pattern, other.pattern))

    def test_keys_of_a_unit_and_of_a_component(self) -> None:
        """RF-011-11 (D-18): la clave de cada parámetro lleva el código de su unidad (y el de
        su componente), casa con su familia y con ninguna otra; un código que no es
        ``[a-z][a-z0-9_]*`` es un error del programa."""
        keys = {
            params.density_key("capa_util"): "res.unit.{u}.density",
            params.swell_key("acopio"): "res.unit.{u}.swell",
            params.density_key("capa_util", "caliza"): "res.unit.{u}.{c}.density",
            params.swell_key("capa_util", "caliza"): "res.unit.{u}.{c}.swell",
            params.percent_key("capa_util", "arcilla"): "res.unit.{u}.{c}.percent",
        }
        self.assertEqual(list(keys), [
            "res.unit.capa_util.density", "res.unit.acopio.swell",
            "res.unit.capa_util.caliza.density", "res.unit.capa_util.caliza.swell",
            "res.unit.capa_util.arcilla.percent"])
        for key, pattern in keys.items():
            with self.subTest(key=key):
                matching = [family.pattern for family in params.FAMILIES
                            if family.match(key) is not None]
                self.assertEqual(matching, [pattern])
        for wrong in ("Capa", "1capa", "", "capa útil"):
            with self.subTest(code=wrong), self.assertRaises(ValueError):
                params.density_key(wrong)
        with self.assertRaises(ValueError):
            params.percent_key("capa_util", "Caliza")

    def test_labels_and_registration(self) -> None:
        """RF-008-06, RF-011-11 (ADR-0027): cada familia lleva su etiqueta, con su español en
        ``messages.toml``; ``bl`` las registra y las quita con ``unregister_families("res")``
        sin dejar rastro; registrada, ``definition`` da la de una clave concreta, sin valor por
        defecto, y su nombre visible lleva los códigos («Densidad in situ · capa_util»)."""
        table = i18n.load_messages()
        for family in params.FAMILIES:
            label = family.template.label_msgid
            with self.subTest(pattern=family.pattern):
                self.assertEqual(set(label) & SPANISH_LETTERS, set(), "msgid en inglés")
                self.assertIn(label, table)
                self.assertNotEqual(table[label], label)
        before = dict(core_params.FAMILIES)
        self.addCleanup(core_params.unregister_families, "res")
        core_params.register_families(params.FAMILIES)
        key = params.density_key("capa_util")
        found = core_params.definition(key)
        self.assertEqual(found.key, key)
        self.assertIsNone(found.default)
        self.assertEqual(core_params.parameter_label(key), "Densidad in situ · capa_util")
        self.assertEqual(core_params.unregister_families("res"), len(FAMILIES))
        self.assertEqual(dict(core_params.FAMILIES), before)
        self.assertIsNone(core_params.definition(key))


class RegistrationTest(unittest.TestCase):
    def test_registered_and_removed_without_trace(self) -> None:
        """RF-008-01 (plan §5.2.2 y §5.3.3): ``bl`` registra las tres en ``core.params`` (la
        altura de banco, no) y las quita con ``unregister_definitions("res")`` sin dejar
        rastro; registrarlas dos veces es un error del programa."""
        before = dict(core_params.DEFINITIONS)
        self.addCleanup(core_params.unregister_definitions, "res")
        core_params.register_definitions(params.DEFINITIONS)
        for definition in params.DEFINITIONS:
            self.assertIs(core_params.DEFINITIONS[definition.key], definition)
        self.assertNotIn(BENCH, core_params.DEFINITIONS)
        with self.assertRaises(ValueError):
            core_params.register_definitions(params.DEFINITIONS)
        self.assertEqual(core_params.unregister_definitions("res"), len(EXPECTED))
        self.assertEqual(dict(core_params.DEFINITIONS), before)


if __name__ == "__main__":
    unittest.main()
