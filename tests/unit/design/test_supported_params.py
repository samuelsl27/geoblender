# SPDX-License-Identifier: GPL-3.0-or-later
"""Los parámetros de los cuatro tipos de entidad de la 016 (spec 016, T03; HU-016-1 a 4; RF-016-02, 07, 08, 11,
17, 18, 20 a 22; plan 016 §5.2.2 y §5.7 P-4, P-5 y P-11; D-1, D-2, D-3, D-9, D-19 y D-21; ADR-0027 y ADR-0031 §1).

Cada tipo —el acopio (``stockpile``, la detección: sin cadena), la retirada (``removal``), el contrafuerte
(``buttress``) y el cuerpo apoyado (``body``)— es una **familia** ``des.<tipo>.{e}.<valor>`` de parámetros de versión
(que admite también el ámbito del proyecto: la detección sobre una superficie del proyecto, D-15), con su tipo de valor,
su unidad, su rango, su procedencia y su valor por defecto **solo** donde lo dice el plan: ADOPTADO «sin confirmar»
(D-3, P-6, D-2, D-22 y D-1) o HIPÓTESIS (la inclinación máxima y el cuantil de apoyo); sin valor, lo que decide una
persona (la transición, la coronación, la distancia máxima y el resguardo). Los umbrales de la huella y del espesor
mínimo no se copian: se leen por su clave de la 011 y de la 012. ``check_entity_param`` rechaza un valor sin valor o
fuera de rango nombrando la entidad, el campo y el valor, para cada tipo (RF-015-08).
"""

from __future__ import annotations

import ast
import math
import unittest

from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR

params = import_geoblender("design.params")
messages = import_geoblender("design.messages")
core_params = import_geoblender("core.params")
i18n = import_geoblender("core.i18n")

SPANISH_LETTERS = frozenset("áéíóúüñÁÉÍÓÚÜÑ¿¡")
INF = math.inf

# Por tipo y en el orden de plan §5.2.2: último segmento de la clave → (tipo de valor, unidad, valor por defecto,
# mínimo, máximo, mínimo excluido, máximo excluido, opciones, tipo de la cifra, opcional). El máximo excluido es del
# rango de ``check_entity_param`` (``ParamDef`` no puede excluir el máximo); ``None`` en un extremo, abierto.
Spec = tuple[str, str, object, float | None, float | None, bool, bool, tuple[str, ...], str, bool]


def spec(value_type: str, unit: str = "-", default: object = None, minimum: float | None = None,
         maximum: float | None = None, min_ex: bool = False, max_ex: bool = False,
         choices: tuple[str, ...] = (), kind: str = "ADOPTADO", optional: bool = False) -> Spec:
    return (value_type, unit, default, minimum, maximum, min_ex, max_ex, choices, kind, optional)


TEXT = spec("text")
OPT_TEXT = spec("text", optional=True)
GUARD = spec("float", "m", None, 0.0, 1000.0)
SUPPORTS = spec("text", optional=True)
DISCARDED = spec("bool", "-", False)


def protect(default: bool) -> Spec:
    return spec("bool", "-", default)


METRIC = spec("text", "-", "exact", choices=("exact", "chamfer5"))

SPECS: dict[str, dict[str, Spec]] = {
    "stockpile": {
        "name": TEXT, "layer": TEXT, "surface": TEXT, "candidates": spec("bool"),
        "margin_m": spec("float", "m", 10.0, 0.0, 1000.0),
        "crown_inner_m": spec("float", "m", 1.0, 0.0, 1000.0),
        "crown_outer_m": spec("float", "m", 3.0, 0.0, 1000.0, True),
        "crown_slope_deg": spec("float", "deg", 12.0, 0.0, 90.0, True, True),
        "crown_flat_min_m2": spec("float", "m2", 10.0, 0.0, 1.0e6),
        "max_residual_m": spec("float", "m", 1.0, 0.0, 1000.0, True),
        "fit_rounds": spec("int", "-", 4, 1, 100), "turns": spec("int", "-", 6, 1, 100),
        "tilt_max_deg": spec("float", "deg", 4.0, 0.0, 90.0, False, True, kind="HIPÓTESIS"),
        "support_quantile": spec("float", "-", 0.6, 0.0, 1.0, kind="HIPÓTESIS"),
        "open_diameter_m": spec("float", "m", 31.0, 0.0, 1000.0, True),
        "min_height_m": spec("float", "m", 2.0, 0.0, 1000.0),
        "min_area_m2": spec("float", "m2", 150.0, 0.0, 1.0e7, True),
        "max_area_m2": spec("float", "m2", 20000.0, 0.0, 1.0e9, True),
        "decisions": OPT_TEXT, "support": OPT_TEXT, "supports": SUPPORTS, "discarded": DISCARDED,
        "protect": protect(False), "guard_m": GUARD, "reason": OPT_TEXT,
    },
    "removal": {
        "name": TEXT, "stockpile": TEXT, "start": TEXT, "support": OPT_TEXT, "supports": SUPPORTS,
        "transition_deg": spec("float", "deg", None, 0.0, 90.0, True, True),
        "mesh_factor": spec("float", "-", 1.0, 0.0, 1.0, True), "metric": METRIC,
        "wall_reason": OPT_TEXT, "discarded": DISCARDED, "protect": protect(False), "guard_m": GUARD,
        "reason": OPT_TEXT,
    },
    "buttress": {
        "name": TEXT, "layer": TEXT, "feature": TEXT, "start": TEXT, "support": OPT_TEXT, "profile": TEXT,
        "reach_m": spec("float", "m", None, 0.0, 10000.0, True, optional=True),
        "crown_m": spec("float", "m"), "metric": METRIC, "protect": protect(True), "guard_m": GUARD,
        "reason": OPT_TEXT, "supports": SUPPORTS, "discarded": DISCARDED,
    },
    "body": {
        "name": TEXT, "layer": TEXT, "feature": TEXT, "data_layer": TEXT, "data_field": TEXT,
        "data_from": spec("text", choices=("field", "z", "m")), "surface": TEXT,
        "sense": spec("text", choices=("on_base", "under_roof")), "start": OPT_TEXT,
        "max_distance_m": spec("float", "m", None, 0.0, 100000.0, True),
        "zero_at_edge": spec("bool", "-", False), "support": OPT_TEXT, "supports": SUPPORTS,
        "discarded": DISCARDED, "protect": protect(False), "guard_m": GUARD, "reason": OPT_TEXT,
    },
}
PREFIXES = {"stockpile": "STK", "removal": "RMV", "buttress": "BTR", "body": "BDY"}
LABELS = {"stockpile": "Detección de acopios", "removal": "Retirada de acopio", "buttress": "Contrafuerte",
          "body": "Cuerpo apoyado"}
CHAINED = {"stockpile": False, "removal": True, "buttress": True, "body": True}
FAMILIES_OF = {"stockpile": "STOCKPILE_FAMILIES", "removal": "REMOVAL_FAMILIES",
               "buttress": "BUTTRESS_FAMILIES", "body": "BODY_FAMILIES"}
ENUMS = {"stockpile": "StockpileParam", "removal": "RemovalParam", "buttress": "ButtressParam",
         "body": "BodyParam"}

# Los valores por defecto de plan §5.2.2: ni uno más (principio 2).
DEFAULTS = {
    "stockpile": {"margin_m": 10.0, "crown_inner_m": 1.0, "crown_outer_m": 3.0, "crown_slope_deg": 12.0,
                  "crown_flat_min_m2": 10.0, "max_residual_m": 1.0, "fit_rounds": 4, "turns": 6,
                  "tilt_max_deg": 4.0, "support_quantile": 0.6, "open_diameter_m": 31.0, "min_height_m": 2.0,
                  "min_area_m2": 150.0, "max_area_m2": 20000.0, "discarded": False, "protect": False},
    "removal": {"mesh_factor": 1.0, "metric": "exact", "discarded": False, "protect": False},
    "buttress": {"metric": "exact", "protect": True, "discarded": False},
    "body": {"zero_at_edge": False, "discarded": False, "protect": False},
}
# La decisión de la spec de la que sale cada valor por defecto (su procedencia dice cuál).
DECISION = {"margin_m": "D-3", "crown_inner_m": "D-3", "crown_outer_m": "D-3", "crown_slope_deg": "D-3",
            "crown_flat_min_m2": "D-3", "max_residual_m": "D-3", "fit_rounds": "D-3", "turns": "D-3",
            "tilt_max_deg": "D-3", "support_quantile": "D-3", "open_diameter_m": "P-6", "min_height_m": "D-3",
            "min_area_m2": "D-3", "max_area_m2": "D-3"}

LAYER = "gis_fea_marcas"
"""La capa de las pruebas del parámetro: RF-015-08 pide nombrarla."""


def key_of(kind: str, last: str, code: str | None = None) -> str:
    code = code or f"{PREFIXES[kind]}-001"
    return f"des.{kind}.{code.lower().replace('-', '_')}.{last}"


def all_families() -> tuple[object, ...]:
    return (*params.FAMILIES, *params.ENTITY_FAMILIES, *params.SUPPORTED_FAMILIES)


class RegisteredTypesTest(unittest.TestCase):
    def test_the_four_types_are_registered_after_the_platform(self) -> None:
        """RF-016-01, RF-016-02 (plan 016 §5.2.2, P-11): los cuatro tipos son del programa, se registran al importar
        ``design.params`` después de la plataforma, con su prefijo de código, los valores de su familia en el orden
        del plan y si encadenan: el acopio (la detección) no tiene ``start``, es un tipo sin cadena (T02)."""
        found = params.registered_entity_params()
        self.assertEqual([item.kind for item in found[:5]],
                         ["platform", "stockpile", "removal", "buttress", "body"])
        for kind, specs in SPECS.items():
            with self.subTest(kind=kind):
                item = params.entity_params(kind)
                self.assertIs(params.entity_params_of(f"{PREFIXES[kind]}-001"), item)
                self.assertEqual((item.kind, item.code_prefix, item.key_prefix, item.chained),
                                 (kind, PREFIXES[kind], f"des.{kind}", CHAINED[kind]))
                self.assertEqual(item.names, tuple(specs))
                self.assertEqual(item.label, LABELS[kind])
                self.assertEqual(tuple(family.pattern.rsplit(".", 1)[1] for family in item.families), item.names)
                self.assertEqual(tuple(member.value for member in getattr(params, ENUMS[kind])), item.names)
                with self.assertRaises(ValueError):  # son del programa: no se quitan
                    params.unregister_entity_params(kind)

    def test_the_supported_families_are_those_of_the_four_types_in_order(self) -> None:
        """RF-016-02 (plan 016 §5.2.2): ``SUPPORTED_FAMILIES`` son las familias de los cuatro tipos, en su orden,
        aparte de las 20 de la plataforma (``ENTITY_FAMILIES``, que no cambian) y de las de la 013."""
        expected = tuple(family for kind in SPECS for family in params.entity_params(kind).families)
        self.assertEqual(params.SUPPORTED_FAMILIES, expected)
        self.assertEqual(len(params.ENTITY_FAMILIES), 21)  # las 20 de la 015 y la 21.ª de la 016 (T21)
        for kind, attr in FAMILIES_OF.items():
            self.assertEqual(getattr(params, attr), params.entity_params(kind).families)
        self.assertEqual(sum(len(specs) for specs in SPECS.values()), len(params.SUPPORTED_FAMILIES))

    def test_the_keys_of_each_type(self) -> None:
        """RF-016-02 (P-11): la clave de un valor es ``des.<tipo>.{e}.<valor>`` con el tipo del código; un valor
        que no es de su tipo (``width_m`` de la plataforma en un acopio) o un prefijo sin tipo es un error del
        programa; ``parse_entity_key`` la lee de vuelta."""
        self.assertEqual(params.entity_key("STK-001", "margin_m"), "des.stockpile.stk_001.margin_m")
        self.assertEqual(params.entity_key("RMV-012", "transition_deg"), "des.removal.rmv_012.transition_deg")
        self.assertEqual(params.entity_key("BTR-001", "crown_m"), "des.buttress.btr_001.crown_m")
        self.assertEqual(params.entity_key("BDY-1000", "max_distance_m"), "des.body.bdy_1000.max_distance_m")
        for code, last in (("STK-001", "width_m"), ("STK-001", "start"), ("BDY-001", "crown_m"),
                           ("XYZ-001", "name"), ("PLT-001", "margin_m")):
            with self.subTest(code=code, last=last), self.assertRaises(ValueError):
                params.entity_key(code, last)
        for kind, specs in SPECS.items():
            for last in specs:
                key = key_of(kind, last)
                self.assertEqual(params.parse_entity_key(key), (f"{PREFIXES[kind]}-001", kind, last))
        self.assertIsNone(params.parse_entity_key("des.stockpile.btr_001.margin_m"))  # otro tipo en el código


class FamiliesTest(unittest.TestCase):
    def test_every_family_as_the_plan_says(self) -> None:
        """RF-016-02, 07, 08, 11, 17, 20 (plan 016 §5.2.2; ADR-0027): cada valor de cada tipo es una familia
        ``des.<tipo>.{e}.<valor>`` de versión (que admite también el valor del proyecto: D-15), con su tipo de
        valor, su unidad, su rango, sus opciones, su tipo de cifra (ADOPTADO; HIPÓTESIS la inclinación máxima y
        el cuantil de apoyo) y sin valor por defecto salvo donde lo dice el plan."""
        for kind, specs in SPECS.items():
            families = params.entity_params(kind).families
            self.assertEqual([family.pattern for family in families],
                             [f"des.{kind}.{{e}}.{last}" for last in specs])
            for family, (last, found) in zip(families, specs.items(), strict=True):
                value_type, unit, default, minimum, maximum, min_ex, _max_ex, choices, label_kind, _opt = found
                template = family.template
                with self.subTest(family=family.pattern):
                    self.assertIsInstance(family, core_params.ParamFamily)
                    self.assertEqual(template.key, f"des.{kind}.e.{last}")
                    self.assertEqual((template.value_type, template.unit), (value_type, unit))
                    self.assertEqual((template.default, type(template.default)), (default, type(default)))
                    self.assertEqual((template.minimum, template.maximum), (minimum, maximum))
                    self.assertEqual(template.min_exclusive, min_ex)
                    self.assertEqual(template.choices, choices)
                    self.assertEqual(template.scope, "version")
                    self.assertEqual(template.kind, label_kind)
                    self.assertEqual(template.allow_empty, default is None)
                    self.assertEqual(template.source_kind, "person" if default is None else "algorithm")
                    self.assertTrue(template.source.strip())
                    self.assertTrue(template.requirements)
                    self.assertTrue(all(item.startswith(("RF-015-", "RF-016-")) for item in template.requirements))

    def test_only_the_values_of_the_plan_have_a_default(self) -> None:
        """Principio 2, plan 016 §5.2.2 (D-1, D-2, D-3, D-9, D-19, D-21, D-22; P-6): con valor por defecto, **solo**
        los de la tabla del plan (el resto lo decide una persona al crear); la transición, la coronación, la
        distancia máxima y el resguardo no tienen ninguno; el contrafuerte protege por defecto (D-1: «sin corte» en
        su zona de coronación) y los demás no."""
        for kind, specs in SPECS.items():
            found = {last: family.template.default for last, family in zip(
                specs, params.entity_params(kind).families, strict=True) if family.template.default is not None}
            with self.subTest(kind=kind):
                self.assertEqual(found, DEFAULTS[kind])
        for kind, last in (("removal", "transition_deg"), ("buttress", "crown_m"), ("body", "max_distance_m"),
                           ("stockpile", "guard_m"), ("removal", "guard_m"), ("buttress", "guard_m"),
                           ("body", "guard_m"), ("stockpile", "layer"), ("stockpile", "surface"),
                           ("stockpile", "candidates"), ("buttress", "reach_m"), ("body", "data_from"),
                           ("body", "sense")):
            with self.subTest(param=f"{kind}.{last}"):
                self.assertIsNone(params.entity_params(kind).template(last).default)
        self.assertIs(params.entity_params("buttress").template("protect").default, True)
        for kind in ("stockpile", "removal", "body"):
            self.assertIs(params.entity_params(kind).template("protect").default, False)

    def test_the_provenance_of_each_default_names_its_decision(self) -> None:
        """Principio 2 (D-1, D-2, D-3, D-21, D-22; P-6): cada procedencia dice de qué decisión de la spec sale: los
        umbrales de la detección, de D-3 (el diámetro de apertura, también P-6: apertura de 31 m = diámetro en
        metros); la transición, D-2; la coronación, D-21; la distancia máxima, D-9; el resguardo, D-19 de la 015; la
        protección del contrafuerte, D-1; la métrica, D-22 de la 015. Y los dos que son HIPÓTESIS lo dicen."""
        for last, decision in DECISION.items():
            with self.subTest(param=last):
                self.assertIn(decision, params.entity_params("stockpile").template(last).source)
        self.assertIn("D-3", params.entity_params("stockpile").template("tilt_max_deg").source)
        self.assertIn("D-3", params.entity_params("stockpile").template("support_quantile").source)
        for kind, last, text in (("removal", "transition_deg", "D-2"), ("removal", "mesh_factor", "D-2"),
                                 ("removal", "metric", "D-22"), ("buttress", "crown_m", "D-21"),
                                 ("buttress", "protect", "D-1"), ("buttress", "guard_m", "D-19"),
                                 ("body", "max_distance_m", "D-9"), ("buttress", "metric", "D-22")):
            with self.subTest(param=f"{kind}.{last}"):
                self.assertIn(text, params.entity_params(kind).template(last).source)
        hypotheses = [f"{kind}.{last}" for kind, specs in SPECS.items()
                      for last, family in zip(specs, params.entity_params(kind).families, strict=True)
                      if family.template.kind == "HIPÓTESIS"]
        self.assertEqual(hypotheses, ["stockpile.tilt_max_deg", "stockpile.support_quantile"])

    def test_the_options_are_the_ones_of_the_model(self) -> None:
        """RF-016-17, RF-016-20 (D-22 de la 015): las opciones de ``metric`` son las de ``Metric``; las de ``sense``
        y de ``data_from`` son las de ``BodySense`` y ``ThicknessSource`` del modelo (la prueba las ata)."""
        model = import_geoblender("design.model")
        for kind in ("removal", "buttress"):
            self.assertEqual(set(params.entity_params(kind).template("metric").choices),
                             {item.value for item in model.Metric})
        self.assertEqual(params.entity_params("body").template("sense").choices,
                         tuple(item.value for item in model.BodySense))
        self.assertEqual(params.entity_params("body").template("data_from").choices,
                         tuple(item.value for item in model.ThicknessSource))

    def test_the_thresholds_of_the_011_and_the_012_are_read_by_their_key(self) -> None:
        """RF-016-02, RF-016-09 (D-17; plan 016 §2.1): el umbral de la huella es el de la 011
        (``res.anthropic_presence_m``) y el espesor mínimo, el de la 012 (``res.verify.min_thickness_m``); la
        familia de ninguno de los tipos los copia (no tiene un valor propio que pueda diferir) y las claves de
        ``design`` son las que ``reserves`` declara."""
        self.assertEqual(params.ANTHROPIC_PRESENCE, "res.anthropic_presence_m")
        self.assertEqual(params.VERIFY_MIN_THICKNESS, "res.verify.min_thickness_m")
        for kind in SPECS:
            for name in params.entity_params(kind).names:
                self.assertNotIn("presence", name)
                self.assertNotIn("min_thickness", name)
                self.assertNotIn("threshold", name)
        source = (EXTENSION_DIR / "reserves" / "params.py").read_text(encoding="utf-8")
        found = {}
        for node in ast.parse(source).body:
            if (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                    and isinstance(node.value, ast.Constant)):
                found[node.targets[0].id] = node.value.value
        self.assertEqual(found["ANTHROPIC_PRESENCE"], params.ANTHROPIC_PRESENCE)

    def test_the_families_do_not_overlap_with_the_other_ones_of_design(self) -> None:
        """RF-016-02 (ADR-0027, ``register_families``): ninguna de las familias de los cuatro tipos solapa con otra
        ni con las de la 013 y la plataforma, ni casa con un parámetro del proyecto de ``design``: así ``bl`` las
        registra todas juntas."""
        mine = params.SUPPORTED_FAMILIES
        others = (*params.FAMILIES, *params.ENTITY_FAMILIES)
        for index, family in enumerate(mine):
            for other in (*mine[:index], *others):
                with self.subTest(family=family.pattern, other=other.pattern):
                    self.assertFalse(family.overlaps(other))
            for definition in (*params.DEFINITIONS, *params.QUARRY_DEFINITIONS):
                self.assertIsNone(family.match(definition.key))
        self.assertEqual(len({family.pattern for family in mine}), len(mine))

    def test_a_family_gives_the_definition_of_a_concrete_key(self) -> None:
        """RF-016-02 (ADR-0027, punto 3): la clave concreta de la entidad ``STK-001`` es una definición declarada a
        todos los efectos: ``core.params`` la resuelve por su familia, también el código de otra entidad."""
        everything = all_families()
        for kind, specs in SPECS.items():
            for last, found in specs.items():
                key = key_of(kind, last)
                definition = core_params.find_definition(key, {}, everything)
                with self.subTest(key=key):
                    self.assertIsNotNone(definition)
                    self.assertEqual((definition.key, definition.value_type), (key, found[0]))
        other = core_params.find_definition(key_of("stockpile", "margin_m", "STK-002"), {}, everything)
        self.assertEqual(other.key, "des.stockpile.stk_002.margin_m")
        self.assertIsNone(core_params.find_definition("des.stockpile.stk_001.no_such", {}, everything))

    def test_labels_with_their_spanish(self) -> None:
        """RF-008-06 (principio 10): cada familia lleva su etiqueta en inglés (sin letras del español) con su
        traducción en ``core/i18n/messages.toml``."""
        table = i18n.load_messages()
        labels = {family.template.label_msgid for family in params.SUPPORTED_FAMILIES}
        for label in labels:
            with self.subTest(label=label):
                self.assertTrue(label and label.strip())
                self.assertEqual(set(label) & SPANISH_LETTERS, set())
                self.assertIn(label, table)
                self.assertNotEqual(table[label], label)
        self.assertEqual(i18n.untranslated(sorted(labels)), [])
        for kind in SPECS:  # dentro de un tipo, dos valores no se llaman igual
            own = [family.template.label_msgid for family in params.entity_params(kind).families]
            self.assertEqual(len(set(own)), len(own), kind)


class CheckEntityParamTest(unittest.TestCase):
    def check(self, kind: str, last: str, value: object, **options: object) -> object:
        return params.check_entity_param("Patio", f"{PREFIXES[kind]}-001", last, value, layer=LAYER, **options)

    def test_every_number_in_its_range(self) -> None:
        """RF-015-08 (generalizado a los cuatro tipos; plan 016 §5.2.2): cada número se comprueba en su rango
        (extremos incluidos o excluidos, también el 90° que ``ParamDef`` no puede excluir); dentro, vuelve como
        ``float`` (``int`` los de vueltas); fuera, ``nan`` o infinito, ``des.entity_param_range`` nombrando la
        entidad, la clave del campo, el valor, la capa y el rango."""
        bounds = {
            ("stockpile", "margin_m"): ((0.0, 10.0, 1000.0), (-0.001, 1000.001, math.nan, INF)),
            ("stockpile", "crown_inner_m"): ((0.0, 1.0, 1000.0), (-0.001, 1000.001)),
            ("stockpile", "crown_outer_m"): ((0.001, 3.0, 1000.0), (0.0, -1.0, 1000.001)),
            ("stockpile", "crown_slope_deg"): ((0.001, 12.0, 89.999), (0.0, 90.0, -1.0, math.nan)),
            ("stockpile", "crown_flat_min_m2"): ((0.0, 10.0, 1.0e6), (-1.0, 1.0e6 + 1)),
            ("stockpile", "max_residual_m"): ((0.001, 1.0, 1000.0), (0.0, -1.0)),
            ("stockpile", "tilt_max_deg"): ((0.0, 4.0, 89.999), (-0.001, 90.0, 91.0)),
            ("stockpile", "support_quantile"): ((0.0, 0.6, 1.0), (-0.001, 1.001, math.nan)),
            ("stockpile", "open_diameter_m"): ((0.001, 31.0, 1000.0), (0.0, -1.0)),
            ("stockpile", "min_height_m"): ((0.0, 2.0, 1000.0), (-0.5, 1000.5)),
            ("stockpile", "min_area_m2"): ((0.001, 150.0, 1.0e7), (0.0, -1.0)),
            ("stockpile", "max_area_m2"): ((0.001, 20000.0, 1.0e9), (0.0, 1.0e9 + 1)),
            ("stockpile", "guard_m"): ((0.0, 5.0, 1000.0), (-0.001, 1000.001)),
            ("removal", "transition_deg"): ((0.001, 35.0, 89.999), (0.0, 90.0, 91.0, -1.0, math.nan)),
            ("removal", "mesh_factor"): ((0.001, 0.93, 1.0), (0.0, 1.0000001, 1.5, -1.0)),
            ("buttress", "reach_m"): ((0.001, 50.0, 10000.0), (0.0, 10000.001, -3.0, INF)),
            ("buttress", "crown_m"): ((-5000.0, 0.0, 250.0, 1.0e6), (math.nan, INF, -INF)),
            ("body", "max_distance_m"): ((0.001, 30.0, 100000.0), (0.0, -1.0, 100000.001, math.nan)),
        }
        for (kind, last), (inside, outside) in bounds.items():
            for value in inside:
                with self.subTest(param=f"{kind}.{last}", value=value):
                    checked = self.check(kind, last, value)
                    self.assertEqual(checked, value)
                    self.assertIs(type(checked), float)
            for value in outside:
                with self.subTest(param=f"{kind}.{last}", value=value):
                    with self.assertRaises(messages.DesignError) as caught:
                        self.check(kind, last, value)
                    error = caught.exception
                    self.assertEqual(error.code, "des.entity_param_range")
                    self.assertEqual(error.field, key_of(kind, last))
                    self.assertEqual(error.obj, f"{LABELS[kind]} «Patio»")
                    self.assertIn("«Patio»", error.text)
                    self.assertIn(f"«{LAYER}»", error.text)
                    self.assertEqual(error.values["layer"], LAYER)
                    self.assertIn(key_of(kind, last), error.text)
                    self.assertIn(params.entity_params(kind).range(last).text(), error.text)
                    self.assertNotIn("{", error.text)
        self.assertEqual(self.check("buttress", "reach_m", 50), 50.0)  # un entero es un número real

    def test_the_rounds_are_integers(self) -> None:
        """RF-016-02 (D-3: 4 vueltas del ajuste y 6 de plano y huella): ``fit_rounds`` y ``turns`` son enteros de 1
        a 100; un valor dentro vuelve como ``int``; fuera de rango, ``des.entity_param_range``; uno que no es un
        entero (un decimal, un texto, un booleano) no es un error de la persona: ``TypeError``."""
        for last in ("fit_rounds", "turns"):
            for value in (1, 4, 6, 100):
                with self.subTest(param=last, value=value):
                    checked = self.check("stockpile", last, value)
                    self.assertEqual(checked, value)
                    self.assertIs(type(checked), int)
            for value in (0, -1, 101):
                with self.subTest(param=last, value=value):
                    with self.assertRaises(messages.DesignError) as caught:
                        self.check("stockpile", last, value)
                    self.assertEqual(caught.exception.code, "des.entity_param_range")
            for wrong in (3.5, "4", True, [4]):
                with self.subTest(param=last, value=wrong), self.assertRaises(TypeError):
                    self.check("stockpile", last, wrong)

    def test_the_ranges_as_they_read(self) -> None:
        """RF-015-08: el rango con el que se rechaza se lee con paréntesis en el extremo excluido y ``±∞`` en el
        abierto: (0; 90) °, [0; 90) °, [0; 1], (0; 1 000] m y (-∞; +∞) m."""
        rng = params.entity_params
        self.assertEqual(rng("removal").range("transition_deg").text(), "(0; 90) °")
        self.assertEqual(rng("stockpile").range("tilt_max_deg").text(), "[0; 90) °")
        self.assertEqual(rng("stockpile").range("support_quantile").text(), "[0; 1]")
        self.assertEqual(rng("stockpile").range("max_residual_m").text(), f"(0; 1{i18n.THIN_SPACE}000] m")
        self.assertEqual(rng("buttress").range("crown_m").text(), "(-∞; +∞) m")
        self.assertEqual(rng("removal").range("mesh_factor").text("en"), "(0, 1]")

    def test_without_a_value(self) -> None:
        """RF-015-08, RF-016-02 (D-2, D-9, D-19, D-21): uno sin valor se rechaza nombrando la entidad y el campo
        (``des.entity_param_missing``; ninguno elige un valor por la persona), salvo los opcionales (la superficie
        de apoyo, el motivo, las dependencias declaradas, las decisiones, el motivo de la pared, el alcance y la
        partida de un cuerpo), que vuelven ``None``; ``required`` cambia lo uno y lo otro."""
        for kind, specs in SPECS.items():
            for last, found in specs.items():
                optional = found[9]
                with self.subTest(param=f"{kind}.{last}"):
                    if optional:
                        self.assertIsNone(self.check(kind, last, None))
                        with self.assertRaises(messages.DesignError) as forced:
                            self.check(kind, last, None, required=True)
                        self.assertEqual(forced.exception.code, "des.entity_param_missing")
                        continue
                    with self.assertRaises(messages.DesignError) as caught:
                        self.check(kind, last, None)
                    error = caught.exception
                    self.assertEqual(error.code, "des.entity_param_missing")
                    self.assertEqual(error.field, key_of(kind, last))
                    self.assertEqual(error.obj, f"{LABELS[kind]} «Patio»")
                    self.assertIsNone(error.value)
                    self.assertIn("«Patio»", error.text)
                    self.assertIn(f"«{LAYER}»", error.text)
                    self.assertIn(key_of(kind, last), error.text)
                    self.assertNotIn("{", error.text)
                    self.assertIsNone(self.check(kind, last, None, required=False))
        with self.assertRaises(messages.DesignError) as blank:  # un texto en blanco es «sin valor»
            self.check("removal", "stockpile", "   ")
        self.assertEqual(blank.exception.code, "des.entity_param_missing")
        self.assertIsNone(self.check("removal", "wall_reason", "   "))

    def test_texts_options_and_the_flags(self) -> None:
        """RF-016-17, RF-016-20, RF-016-08 (D-22): la métrica, el sentido y de dónde sale el espesor son de su lista
        cerrada (otro texto, ``des.entity_param_choice`` con las opciones); un texto sale sin los espacios de los
        extremos; ``candidates``, ``protect`` y ``zero_at_edge`` son un sí/no."""
        self.assertEqual(self.check("removal", "metric", "chamfer5"), "chamfer5")
        self.assertEqual(self.check("body", "sense", "under_roof"), "under_roof")
        self.assertEqual(self.check("body", "data_from", " m "), "m")
        self.assertEqual(self.check("removal", "stockpile", " STK-001#m07 "), "STK-001#m07")
        for kind, last in (("stockpile", "candidates"), ("buttress", "protect"), ("body", "zero_at_edge")):
            for value in (True, False):
                self.assertIs(self.check(kind, last, value), value)
        for kind, last, wrong in (("removal", "metric", "chamfer3"), ("body", "sense", "above"),
                                  ("body", "data_from", "x"), ("buttress", "metric", "CHAMFER5")):
            with self.subTest(param=f"{kind}.{last}", value=wrong):
                with self.assertRaises(messages.DesignError) as caught:
                    self.check(kind, last, wrong)
                self.assertEqual(caught.exception.code, "des.entity_param_choice")
                self.assertEqual(caught.exception.field, key_of(kind, last))
                self.assertIn(f"«{LAYER}»", caught.exception.text)
                for option in params.entity_params(kind).template(last).choices:
                    self.assertIn(f"«{option}»", caught.exception.text)

    def test_a_value_of_another_type_is_a_fault_of_the_program(self) -> None:
        """RF-015-08: un número que llega como texto o como booleano, un texto que no lo es y un sí/no que no lo es
        no son un error de la persona (el diálogo los entrega ya con su tipo): ``TypeError``; un valor que no es de
        su tipo, un código sin tipo o mal formado, ``ValueError``."""
        for kind, last, wrong in (("stockpile", "margin_m", "10"), ("stockpile", "margin_m", True),
                                  ("removal", "stockpile", 7), ("stockpile", "candidates", 1),
                                  ("buttress", "protect", "sí"), ("body", "zero_at_edge", 0),
                                  ("body", "max_distance_m", [5.0])):
            with self.subTest(param=f"{kind}.{last}", value=wrong), self.assertRaises(TypeError):
                self.check(kind, last, wrong)
        for code, last in (("STK-001", "no_such_param"), ("STK-001", "width_m"), ("STK-1", "margin_m"),
                           ("stk_001", "margin_m"), ("ZZZ-001", "margin_m")):
            with self.subTest(code=code, last=last), self.assertRaises(ValueError):
                params.check_entity_param("P1", code, last, 1.0, layer=LAYER)

    def test_the_platform_is_checked_exactly_as_before(self) -> None:
        """RF-015-08 (la 015 sin cambios): ``check_entity_param`` de una plataforma sigue nombrando «Plataforma»,
        con sus opcionales y su rango; generalizarlo no cambia lo suyo."""
        self.assertEqual(params.check_entity_param("P1", "PLT-001", "edge_angle_deg", 35, layer=LAYER), 35.0)
        self.assertIsNone(params.check_entity_param("P1", "PLT-001", "support", None, layer=LAYER))
        with self.assertRaises(messages.DesignError) as caught:
            params.check_entity_param("P1", "PLT-001", "edge_angle_deg", 90, layer=LAYER)
        self.assertEqual((caught.exception.code, caught.exception.obj),
                         ("des.entity_param_range", "Plataforma «P1»"))


if __name__ == "__main__":
    unittest.main()
