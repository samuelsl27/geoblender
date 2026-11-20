# SPDX-License-Identifier: GPL-3.0-or-later
"""Los parámetros de la pista, la accesibilidad y el perfil de pista de la 017 (spec 017, T02; HU-017-1 a 4;
RF-017-04, 07, 08, 24; plan 017 §5.2.2 y §5.7 P-2, P-3 y P-10; D-2, D-10, D-11, D-13, D-15, D-17; ADR-0027 y ADR-0030).

La pista (``road``, ``RDW-001``: **con cadena**) y la accesibilidad (``access``, ``ACC-001``: **sin cadena**) son dos
tipos de entidad del programa con su familia ``des.<tipo>.{e}.<valor>`` de versión, y el perfil de pista, una familia
``des.roadprofile.{p}.<valor>`` **por perfil** (``{p}``, el código inmutable de ``des_road_profile``). Cada valor tiene
su tipo, su unidad, su rango, su procedencia y **solo** los valores por defecto de la tabla del plan: ``search_budget``
(5.000.000, ADOPTADO «sin confirmar», P-3), el factor de malla (1,0) y la métrica (exacta) del perfil; todo lo demás
**sin valor** (D-2, D-10, D-11, D-17). La pista no ofrece ``protect`` ni ``guard_m`` (no declara restricción alguna:
RF-017-01, D-15) y la accesibilidad no tiene ``start``. ``check_entity_param`` y ``check_road_profile`` rechazan un
valor sin valor o fuera de rango nombrando la entidad (o el perfil), el campo y el valor (RF-017-04), y un perfil con
``Rmín > R`` o con ``Rmín`` por debajo de la semianchura de su sección se rechaza (RF-017-04, RF-017-07).
"""

from __future__ import annotations

import math
import re
import unittest
from fractions import Fraction

from tests.support import road_data
from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR

params = import_geoblender("design.params")
messages = import_geoblender("design.messages")
core_params = import_geoblender("core.params")
i18n = import_geoblender("core.i18n")
units = import_geoblender("core.units")

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
HYP = "HIPÓTESIS"
LEVEL = spec("float", "m", optional=True)
MODES = ("trace", "on_axis", "axis_3d")
METRICS = ("exact", "chamfer5")

SPECS: dict[str, dict[str, Spec]] = {
    "road": {
        "name": TEXT, "mode": spec("text", choices=MODES), "layer": TEXT, "feature": OPT_TEXT, "profile": TEXT,
        "start": TEXT, "support": OPT_TEXT, "supports": OPT_TEXT,
        "origin": OPT_TEXT, "destination": OPT_TEXT, "dest_level_m": LEVEL,
        "dest_tol_m": spec("float", "m", None, 0.0, 1000.0, True, optional=True), "dest_zone": OPT_TEXT,
        "start_level_m": LEVEL, "end_level_m": LEVEL,
        "mesh_m": spec("float", "m", None, 0.0, 1000.0, True, kind=HYP),
        "level_step_m": spec("float", "m", None, 0.0, 100.0, True, kind=HYP),
        "max_cut_fill_m": spec("float", "m", None, 0.0, 1000.0, kind=HYP),
        "lambda_per_m": spec("float", "1/m", None, 0.0, 1000.0, kind=HYP),
        "turn_m": spec("float", "m", None, 0.0, 1000.0, kind=HYP),
        "margin_m": spec("float", "m", None, 0.0, 100000.0, kind=HYP),
        "simplify_m": spec("float", "m", None, 0.0, 1000.0, kind=HYP),
        "arrival_tol_m": spec("float", "m", None, 0.0, 1000.0, True, kind=HYP),
        "search_budget": spec("int", "-", 5_000_000, 1, 1_000_000_000),
        "discarded": spec("bool", "-", False), "reason": OPT_TEXT,
    },
    "access": {
        "name": TEXT, "surface": TEXT, "entries_layer": TEXT, "berms": OPT_TEXT, "discarded": spec("bool", "-", False),
        "walk_slope_pct": spec("float", "%", None, 0.0, 1000.0, True, kind=HYP),
        "walk_width_m": spec("float", "m", None, 0.0, 1000.0, True, kind=HYP),
        "min_berm_area_m2": spec("float", "m2", None, 0.0, 1.0e7, kind=HYP),
    },
}
PREFIXES = {"road": "RDW", "access": "ACC"}
LABELS = {"road": "Pista", "access": "Accesibilidad"}
CHAINED = {"road": True, "access": False}
FAMILIES_OF = {"road": "ROAD_FAMILIES", "access": "ACCESS_FAMILIES"}
ENUMS = {"road": "RoadParam", "access": "AccessParam"}
RANGES_OF = {"road": "ROAD_RANGES", "access": "ACCESS_RANGES"}

# El perfil de pista (plan §5.2.2): ``des.roadprofile.{p}.<valor>``, de versión, ADOPTADO con su fuente (D-2).
PROFILE_SPECS: dict[str, Spec] = {
    "vehicle_width_m": spec("float", "m", None, 0.0, 100.0, True),
    "lane_factor": spec("float", "-", None, 0.0, 100.0, True),
    "shoulder_m": spec("float", "m", None, 0.0, 100.0),
    "berm_m": spec("float", "m", None, 0.0, 100.0),
    "max_gradient_pct": spec("float", "%", None, 0.0, 100.0, True),
    "station_step_m": spec("float", "m", None, 0.0, 1000.0, True),
    "max_mean_gradient_pct": spec("float", "%", None, 0.0, 100.0, True),
    "curve_radius_m": spec("float", "m", None, 0.0, 10000.0, True),
    "min_radius_m": spec("float", "m", None, 0.0, 10000.0, True),
    "cut_angle_deg": spec("float", "deg", None, 0.0, 90.0, True, True),
    "fill_angle_deg": spec("float", "deg", None, 0.0, 90.0, True, True),
    "reach_m": spec("float", "m", None, 0.0, 10000.0, True),
    "class": TEXT,
    "mesh_factor": spec("float", "-", 1.0, 0.0, 1.0, True),
    "metric": spec("text", "-", "exact", choices=METRICS),
}

# Los valores por defecto de plan §5.2.2: ni uno más (principio 2).
DEFAULTS = {"road": {"search_budget": 5_000_000, "discarded": False}, "access": {"discarded": False}}
PROFILE_DEFAULTS = {"mesh_factor": 1.0, "metric": "exact"}

LAYER = "gis_fea_pistas_puntos"
"""La capa de las pruebas del parámetro: RF-015-08 pide nombrarla."""
TOML_START = "# --- Parámetros de la pista, la accesibilidad y el perfil de pista (spec 017, T02;"
TOML_END = "# --- Fin de los parámetros de la pista, la accesibilidad y el perfil de pista (spec 017, T02)"
"""Las dos marcas del bloque de etiquetas de ``core/i18n/messages.toml``: lo que una tarea siguiente añada va
después de la segunda."""


def key_of(kind: str, last: str, code: str | None = None) -> str:
    code = code or f"{PREFIXES[kind]}-001"
    return f"des.{kind}.{code.lower().replace('-', '_')}.{last}"


def reference_values() -> dict[str, object]:
    """Los valores del perfil de referencia de IMGA (``spec.md`` §11, solo para pruebas), por último segmento."""
    found = road_data.PROFILE
    return {"vehicle_width_m": found.vehicle_width_m, "lane_factor": found.lane_factor,
            "shoulder_m": found.shoulder_m, "berm_m": found.berm_m, "max_gradient_pct": found.max_gradient_pct,
            "station_step_m": found.station_step_m, "max_mean_gradient_pct": found.max_mean_gradient_pct,
            "curve_radius_m": found.curve_radius_m, "min_radius_m": found.min_radius_m,
            "cut_angle_deg": found.cut_angle_deg, "fill_angle_deg": found.fill_angle_deg,
            "reach_m": found.reach_m, "class": found.class_name, "mesh_factor": found.mesh_factor,
            "metric": found.metric}


class RegisteredTypesTest(unittest.TestCase):
    def test_the_two_types_are_registered_after_the_others(self) -> None:
        """RF-017-01, RF-017-24 (plan 017 §5.2.2, P-1): la pista y la accesibilidad son del programa, se registran al
        importar ``design.params`` después de los cinco tipos de la 015 y la 016, con su prefijo de código, los
        valores de su familia en el orden del plan y si encadenan: la pista **sí** (tiene ``start``) y la
        accesibilidad **no** (un tipo sin cadena, como la detección de acopios)."""
        found = params.registered_entity_params()
        self.assertEqual([item.kind for item in found[:7]],
                         ["platform", "stockpile", "removal", "buttress", "body", "road", "access"])
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
                self.assertEqual(item.optional, tuple(last for last, found_spec in specs.items() if found_spec[9]))
                with self.assertRaises(ValueError):  # son del programa: no se quitan
                    params.unregister_entity_params(kind)

    def test_the_road_declares_nothing_and_the_access_has_no_start(self) -> None:
        """RF-017-01, D-15, P-1 (RF-015-12): la pista **no ofrece** ``protect`` ni ``guard_m`` (no declara restricción
        alguna), y la accesibilidad no tiene ``start`` (nadie parte de su dato, ni ella de otro): ``entity_key``
        rechaza esos valores como un error del programa, y ``check_entity_param`` también."""
        road, access = params.entity_params("road"), params.entity_params("access")
        for name in ("protect", "guard_m"):
            self.assertNotIn(name, road.names)
            with self.subTest(param=name):
                with self.assertRaises(ValueError):
                    params.entity_key("RDW-001", name)
                with self.assertRaises(ValueError):
                    params.check_entity_param("Pista 1", "RDW-001", name, 1.0, layer=LAYER)
        self.assertIn("start", road.names)
        self.assertNotIn("start", access.names)
        self.assertTrue(road.chained)
        self.assertFalse(access.chained)
        with self.assertRaises(ValueError):
            params.entity_key("ACC-001", "start")
        for name in ("support", "supports", "reason", "protect", "guard_m"):
            self.assertNotIn(name, access.names)  # RF-017-24: ni se apoya ni declara

    def test_the_road_and_access_families_are_aside_from_the_others(self) -> None:
        """RF-017-01 (plan 017 §5.2.2): ``ROAD_FAMILIES`` y ``ACCESS_FAMILIES`` son las de cada tipo, en su orden, y
        van aparte de las de la 013 (``FAMILIES``), la plataforma (``ENTITY_FAMILIES``) y los tipos de la 016
        (``SUPPORTED_FAMILIES``), que no cambian (21 + 69)."""
        for kind, attr in FAMILIES_OF.items():
            self.assertEqual(getattr(params, attr), params.entity_params(kind).families)
            self.assertEqual(len(getattr(params, attr)), len(SPECS[kind]))
        self.assertEqual(len(params.ENTITY_FAMILIES), 21)
        self.assertEqual(len(params.SUPPORTED_FAMILIES), 69)
        self.assertEqual(len(params.ROAD_FAMILIES), 26)
        self.assertEqual(len(params.ACCESS_FAMILIES), 8)
        self.assertEqual(len(params.ROAD_PROFILE_FAMILIES), 15)

    def test_the_keys_of_each_type(self) -> None:
        """RF-017-01 (P-1, ADR-0027): la clave de un valor es ``des.<tipo>.{e}.<valor>`` con el tipo del código
        (``RDW-001`` → ``rdw_001``, ``ACC-001`` → ``acc_001``); un valor que no es de su tipo es un error del
        programa; ``parse_entity_key`` la lee de vuelta; y la del perfil no se confunde con la de una entidad."""
        self.assertEqual(params.entity_key("RDW-001", "mesh_m"), "des.road.rdw_001.mesh_m")
        self.assertEqual(params.entity_key("ACC-012", "walk_slope_pct"), "des.access.acc_012.walk_slope_pct")
        for code, last in (("RDW-001", "walk_slope_pct"), ("ACC-001", "mesh_m"), ("PLT-001", "origin"),
                           ("RDW-001", "width_m"), ("XYZ-001", "name")):
            with self.subTest(code=code, last=last), self.assertRaises(ValueError):
                params.entity_key(code, last)
        for kind, specs in SPECS.items():
            for last in specs:
                self.assertEqual(params.parse_entity_key(key_of(kind, last)), (f"{PREFIXES[kind]}-001", kind, last))
        self.assertIsNone(params.parse_entity_key("des.road.acc_001.mesh_m"))  # otro tipo en el código
        self.assertIsNone(params.parse_entity_key("des.roadprofile.principal.reach_m"))  # un perfil no es una entidad


class FamiliesTest(unittest.TestCase):
    def test_every_family_as_the_plan_says(self) -> None:
        """RF-017-04, 07, 24 (plan 017 §5.2.2; ADR-0027): cada valor de la pista y de la accesibilidad es una familia
        ``des.<tipo>.{e}.<valor>`` de versión con su tipo de valor, su unidad (la de λ es ``1/m``), su rango, sus
        opciones y su tipo de cifra: HIPÓTESIS los de la ruta (D-10, D-11) y los de la accesibilidad (D-17),
        ADOPTADO el resto; sin valor por defecto salvo donde lo dice el plan."""
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
                    self.assertTrue(all(item.startswith(("RF-015-", "RF-017-")) for item in template.requirements))

    def test_the_profile_families_as_the_plan_says(self) -> None:
        """RF-017-07, P-2 (plan 017 §5.2.2; ADR-0027): el perfil de pista es una familia
        ``des.roadprofile.{p}.<valor>`` **por perfil** (de versión, RF-009-24) con sus 15 valores, su unidad, su rango
        (los ángulos, de (0; 90)°) y su tipo ADOPTADO con su fuente (D-2); sin valor por defecto salvo el factor de
        malla (1,0) y la métrica (exacta), ADOPTADO «sin confirmar»."""
        families = params.ROAD_PROFILE_FAMILIES
        self.assertEqual(tuple(member.value for member in params.RoadProfileParam), tuple(PROFILE_SPECS))
        self.assertEqual([family.pattern for family in families],
                         [f"des.roadprofile.{{p}}.{last}" for last in PROFILE_SPECS])
        for family, (last, found) in zip(families, PROFILE_SPECS.items(), strict=True):
            value_type, unit, default, minimum, maximum, min_ex, _max_ex, choices, label_kind, _opt = found
            template = family.template
            with self.subTest(family=family.pattern):
                self.assertEqual(template.key, f"des.roadprofile.p.{last}")
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
                self.assertTrue(all(item.startswith(("RF-009-", "RF-017-")) for item in template.requirements))
                if value_type == "float":
                    self.assertEqual(params.ROAD_PROFILE_RANGES[last].unit, unit)
        self.assertEqual(set(params.ROAD_PROFILE_RANGES), {last for last, found in PROFILE_SPECS.items()
                                                           if found[0] == "float"})

    def test_only_the_values_of_the_plan_have_a_default(self) -> None:
        """Principio 2, plan 017 §5.2.2 (D-2, D-10, D-11, D-17; P-3): con valor por defecto, **solo** los de la tabla
        del plan: el presupuesto de estados (5.000.000) y «no descartada»; en el perfil, el factor de malla (1,0) y la
        métrica (exacta). Ninguna cifra minera lleva uno: ni el radio, ni la pendiente, ni los ángulos, ni los
        parámetros de la ruta ni los de la accesibilidad."""
        for kind, specs in SPECS.items():
            found = {last: family.template.default for last, family in zip(
                specs, params.entity_params(kind).families, strict=True) if family.template.default is not None}
            with self.subTest(kind=kind):
                self.assertEqual(found, DEFAULTS[kind])
        found_profile = {family.pattern.rsplit(".", 1)[1]: family.template.default
                         for family in params.ROAD_PROFILE_FAMILIES if family.template.default is not None}
        self.assertEqual(found_profile, PROFILE_DEFAULTS)
        self.assertIs(type(params.entity_params("road").template("search_budget").default), int)

    def test_the_provenance_of_each_default_names_its_decision(self) -> None:
        """Principio 2 (D-2, D-10, D-11, D-13, D-15, D-17; P-3): cada procedencia dice de qué decisión sale: la ruta,
        de D-10 y D-11 (HIPÓTESIS, sin valor por defecto); el presupuesto, de P-3 (ADOPTADO «sin confirmar»); las cotas de
        inicio y de fin, de D-13; la accesibilidad, de D-17 (HIPÓTESIS); el perfil, de D-2 (ADOPTADO con su fuente, y
        el factor de malla y la métrica, «sin confirmar»). Y los que son HIPÓTESIS son exactamente los de la ruta y de
        la accesibilidad."""
        road, access = params.entity_params("road"), params.entity_params("access")
        for last in ("mesh_m", "level_step_m", "max_cut_fill_m", "lambda_per_m", "turn_m", "margin_m", "simplify_m",
                     "arrival_tol_m"):
            with self.subTest(param=f"road.{last}"):
                source = road.template(last).source
                self.assertTrue("D-10" in source or "D-11" in source, source)
        self.assertIn("D-10", road.template("mesh_m").source)
        self.assertIn("P-3", road.template("search_budget").source)
        for last in ("start_level_m", "end_level_m"):
            self.assertIn("D-13", road.template(last).source)
        for last in ("walk_slope_pct", "walk_width_m", "min_berm_area_m2"):
            self.assertIn("D-17", access.template(last).source)
        for family in params.ROAD_PROFILE_FAMILIES:
            self.assertIn("D-2", family.template.source, family.pattern)
        hypotheses = [f"{kind}.{last}" for kind, specs in SPECS.items()
                      for last, family in zip(specs, params.entity_params(kind).families, strict=True)
                      if family.template.kind == HYP]
        self.assertEqual(hypotheses, [f"road.{last}" for last in (
            "mesh_m", "level_step_m", "max_cut_fill_m", "lambda_per_m", "turn_m", "margin_m", "simplify_m",
            "arrival_tol_m")] + [f"access.{last}" for last in ("walk_slope_pct", "walk_width_m", "min_berm_area_m2")])
        for family in params.ROAD_PROFILE_FAMILIES:
            self.assertEqual(family.template.kind, "ADOPTADO", family.pattern)

    def test_the_options_are_the_ones_of_the_model(self) -> None:
        """RF-017-02, RF-017-07 (D-22 de la 015): las opciones de ``metric`` son las de ``Metric`` y las del ``mode``
        de la pista son los tres modos de plan §5.2.2 (``trace``, ``on_axis``, ``axis_3d``)."""
        model = import_geoblender("design.model")
        self.assertEqual(set(params.entity_params("road").template("mode").choices), set(MODES))
        self.assertEqual(set(params.ROAD_PROFILE_FAMILIES[-1].template.choices), {item.value for item in model.Metric})

    def test_the_ranges_are_the_only_source(self) -> None:
        """RF-017-07 (plan 017 §5.2.2): los rangos de ``ROAD_RANGES``, ``ACCESS_RANGES`` y ``ROAD_PROFILE_RANGES`` son
        la única fuente de los de las familias (con el 90° excluido que ``ParamDef`` no puede decir) y de lo que se
        acepta; solo tienen rango los valores numéricos."""
        for kind, specs in SPECS.items():
            ranges = getattr(params, RANGES_OF[kind])
            numeric = {last for last, found in specs.items() if found[0] in ("float", "int")}
            self.assertEqual(set(ranges), numeric, kind)
            item = params.entity_params(kind)
            for last in numeric:
                self.assertEqual(item.range(last), ranges[last])
            for last in set(specs) - numeric:
                self.assertIsNone(item.range(last))
        angle = params.ROAD_PROFILE_RANGES["cut_angle_deg"]
        self.assertTrue(angle.min_exclusive and angle.max_exclusive)
        self.assertFalse(angle.contains(90.0))
        self.assertFalse(angle.contains(0.0))
        self.assertTrue(angle.contains(89.999))

    def test_the_families_do_not_overlap_with_the_other_ones_of_design(self) -> None:
        """RF-017-01 (ADR-0027, ``register_families``): ninguna de las familias nuevas solapa con otra ni con las de la
        013, la plataforma y los tipos de la 016, ni casa con un parámetro del proyecto de ``design``: así ``bl`` las
        registra todas juntas. Y ``des.roadprofile.{p}`` no es ``des.road.{e}``."""
        mine = (*params.ROAD_FAMILIES, *params.ACCESS_FAMILIES, *params.ROAD_PROFILE_FAMILIES)
        others = (*params.FAMILIES, *params.ENTITY_FAMILIES, *params.SUPPORTED_FAMILIES)
        for index, family in enumerate(mine):
            for other in (*mine[:index], *others):
                with self.subTest(family=family.pattern, other=other.pattern):
                    self.assertFalse(family.overlaps(other))
            for definition in (*params.DEFINITIONS, *params.QUARRY_DEFINITIONS):
                self.assertIsNone(family.match(definition.key))
        self.assertEqual(len({family.pattern for family in mine}), len(mine))

    def test_a_family_gives_the_definition_of_a_concrete_key(self) -> None:
        """RF-017-01, RF-017-07 (ADR-0027, punto 3): la clave concreta de ``RDW-001``, de ``ACC-001`` y de un
        perfil es una definición declarada a todos los efectos: ``core.params`` la resuelve por su familia."""
        everything = (*params.FAMILIES, *params.ENTITY_FAMILIES, *params.SUPPORTED_FAMILIES,
                      *params.ROAD_FAMILIES, *params.ACCESS_FAMILIES, *params.ROAD_PROFILE_FAMILIES)
        for kind, specs in SPECS.items():
            for last, found in specs.items():
                key = key_of(kind, last)
                definition = core_params.find_definition(key, {}, everything)
                with self.subTest(key=key):
                    self.assertIsNotNone(definition)
                    self.assertEqual((definition.key, definition.value_type), (key, found[0]))
        for last, found in PROFILE_SPECS.items():
            key = f"des.roadprofile.pista_principal.{last}"
            definition = core_params.find_definition(key, {}, everything)
            with self.subTest(key=key):
                self.assertIsNotNone(definition)
                self.assertEqual((definition.key, definition.value_type), (key, found[0]))
        other = core_params.find_definition(key_of("road", "mesh_m", "RDW-002"), {}, everything)
        self.assertEqual(other.key, "des.road.rdw_002.mesh_m")
        self.assertIsNone(core_params.find_definition("des.road.rdw_001.no_such", {}, everything))
        self.assertIsNone(core_params.find_definition("des.road.rdw_001.protect", {}, everything))

    def test_labels_with_their_spanish(self) -> None:
        """RF-008-06 (principio 10): cada familia lleva su etiqueta en inglés (sin letras del español) con su
        traducción en ``core/i18n/messages.toml``, y dentro de un tipo dos valores no se llaman igual; ni una entrada
        nueva del catálogo se queda sin usar por una familia."""
        table = i18n.load_messages()
        every = (*params.ROAD_FAMILIES, *params.ACCESS_FAMILIES, *params.ROAD_PROFILE_FAMILIES)
        labels = {family.template.label_msgid for family in every}
        for label in labels:
            with self.subTest(label=label):
                self.assertTrue(label and label.strip())
                self.assertEqual(set(label) & SPANISH_LETTERS, set())
                self.assertIn(label, table)
                self.assertNotEqual(table[label], label)
        self.assertEqual(i18n.untranslated(sorted(labels)), [])
        for name, group in (("road", params.ROAD_FAMILIES), ("access", params.ACCESS_FAMILIES),
                            ("roadprofile", params.ROAD_PROFILE_FAMILIES)):
            own = [family.template.label_msgid for family in group]
            self.assertEqual(len(set(own)), len(own), name)

    def test_the_catalog_has_no_orphan_label_of_the_017_parameters(self) -> None:
        """RF-008-06 (T02 de la 017): el bloque de ``core/i18n/messages.toml`` de los parámetros de la pista, la
        accesibilidad y el perfil (entre sus dos comentarios de marca) tiene **exactamente** las etiquetas que usan
        sus familias: ninguna sin usar (huérfana) y ninguna que falte; un mensaje con código no se repite ahí (su
        español vive en ``design/messages.py``)."""
        text = (EXTENSION_DIR / "core" / "i18n" / "messages.toml").read_text(encoding="utf-8")
        start = text.index(TOML_START)
        block = text[start:text.index(TOML_END, start)]
        found = re.findall(r'^\["([^"]+)"\]$', block, re.MULTILINE)
        used = {family.template.label_msgid
                for family in (*params.ROAD_FAMILIES, *params.ACCESS_FAMILIES, *params.ROAD_PROFILE_FAMILIES)}
        shared = {"Name of the entity", "Start surface of the entity", "Support surface of the entity",
                  "Entities the entity is declared to rest on", "The entity is discarded",
                  "Layer the entity comes from", "Feature of the layer the entity comes from"}
        self.assertEqual(len(found), len(set(found)), "una etiqueta repetida en el bloque")
        self.assertEqual(sorted(found), sorted(used - shared))
        for msgid in shared:  # las comunes ya estaban arriba, y siguen estando una sola vez
            self.assertEqual(text.count(f'["{msgid}"]'), 1, msgid)
        codes = {message.msgid for message in messages.CATALOG}
        self.assertEqual(set(found) & codes, set())

    def test_the_weight_of_the_earthworks_has_its_unit(self) -> None:
        """RF-017-10 (D-11): λ es el peso del movimiento de tierras en 1/m («el coste de un paso es su longitud por
        1 + λ·|cota − terreno|»): ``1/m`` es una unidad del catálogo (con su símbolo), una magnitud propia que solo
        se convierte a sí misma, y la guarda ``lambda_per_m``."""
        unit = units.get_unit("1/m")
        self.assertEqual((unit.code, unit.symbol_es, unit.factor), ("1/m", "1/m", Fraction(1)))
        self.assertEqual(units.symbol("1/m"), "1/m")
        self.assertEqual(units.convert(2.0, "1/m", "1/m"), 2.0)
        others = [other for other in units.UNITS if other != "1/m"]
        self.assertEqual([other for other in others if units.UNITS[other].dimension == unit.dimension], [])
        for target in ("m", "-", "%"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                units.convert(2.0, "1/m", target)
        self.assertEqual(params.entity_params("road").template("lambda_per_m").unit, "1/m")


class CheckEntityParamTest(unittest.TestCase):
    def check(self, kind: str, last: str, value: object, **options: object) -> object:
        return params.check_entity_param("Pista 1", f"{PREFIXES[kind]}-001", last, value, layer=LAYER, **options)

    def test_every_number_in_its_range(self) -> None:
        """RF-017-04, RF-017-07 (generalizado a la pista y a la accesibilidad; plan 017 §5.2.2): cada número se
        comprueba en su rango (extremos incluidos o excluidos); dentro, vuelve como ``float``; fuera, ``nan`` o el
        infinito, ``des.entity_param_range`` nombrando la entidad, la clave del campo, el valor, la capa y el rango."""
        bounds = {
            ("road", "dest_tol_m"): ((0.001, 0.28, 1000.0), (0.0, -1.0, 1000.001, math.nan, INF)),
            ("road", "mesh_m"): ((0.001, 4.0, 1000.0), (0.0, -1.0, 1000.001)),
            ("road", "level_step_m"): ((0.001, 0.28, 100.0), (0.0, 100.001, -0.5)),
            ("road", "max_cut_fill_m"): ((0.0, 14.0, 1000.0), (-0.001, 1000.001)),
            ("road", "lambda_per_m"): ((0.0, 2.0, 1000.0), (-0.001, 1000.001, math.nan)),
            ("road", "turn_m"): ((0.0, 4.0, 1000.0), (-0.001, 1000.001)),
            ("road", "margin_m"): ((0.0, 60.0, 100000.0), (-0.001, 100000.001, INF)),
            ("road", "simplify_m"): ((0.0, 4.0, 1000.0), (-0.001, 1000.001)),
            ("road", "arrival_tol_m"): ((0.001, 0.28, 1000.0), (0.0, -1.0, 1000.001)),
            ("road", "dest_level_m"): ((-5000.0, 0.0, 250.0, 1.0e6), (math.nan, INF, -INF)),
            ("road", "start_level_m"): ((-5000.0, 140.0, 1.0e6), (math.nan, INF, -INF)),
            ("road", "end_level_m"): ((-5000.0, 125.0, 1.0e6), (math.nan, INF, -INF)),
            ("access", "walk_slope_pct"): ((0.001, 16.0, 1000.0), (0.0, -1.0, 1000.001, math.nan)),
            ("access", "walk_width_m"): ((0.001, 4.0, 1000.0), (0.0, -1.0, 1000.001)),
            ("access", "min_berm_area_m2"): ((0.0, 300.0, 1.0e7), (-1.0, 1.0e7 + 1, math.nan)),
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
                    self.assertEqual(error.obj, f"{LABELS[kind]} «Pista 1»")
                    self.assertIn("«Pista 1»", error.text)
                    self.assertIn(f"«{LAYER}»", error.text)
                    self.assertEqual(error.values["layer"], LAYER)
                    self.assertIn(key_of(kind, last), error.text)
                    self.assertIn(params.entity_params(kind).range(last).text(), error.text)
                    self.assertNotIn("{", error.text)
        self.assertEqual(self.check("road", "mesh_m", 4), 4.0)  # un entero es un número real

    def test_the_budget_is_an_integer(self) -> None:
        """RF-017-10, P-3 (plan 017 §5.2.2): el presupuesto de estados es un entero de 1 a 1.000 millones; un valor
        dentro vuelve como ``int``; fuera de rango, ``des.entity_param_range``; uno que no es un entero (un decimal,
        un texto, un booleano) no es un error de la persona: ``TypeError``."""
        for value in (1, 5_000_000, 1_000_000_000):
            with self.subTest(value=value):
                checked = self.check("road", "search_budget", value)
                self.assertEqual(checked, value)
                self.assertIs(type(checked), int)
        for value in (0, -1, 1_000_000_001):
            with self.subTest(value=value):
                with self.assertRaises(messages.DesignError) as caught:
                    self.check("road", "search_budget", value)
                self.assertEqual(caught.exception.code, "des.entity_param_range")
                self.assertEqual(caught.exception.field, "des.road.rdw_001.search_budget")
        for wrong in (3.5, "5", True, [5]):
            with self.subTest(value=wrong), self.assertRaises(TypeError):
                self.check("road", "search_budget", wrong)

    def test_a_missing_value_is_rejected_and_the_optional_ones_may_be_empty(self) -> None:
        """RF-017-04 (RF-015-08: ninguno elige un valor por la persona): un valor sin valor (``None`` o un texto en
        blanco) se rechaza con ``des.entity_param_missing`` nombrando la entidad, la capa y el campo, salvo los
        opcionales de su tipo (los de un modo que no los usa, las cotas de inicio y de fin, el apoyo y el motivo);
        ``required`` lo cambia en los dos sentidos (el modo «eje 3D» no pide los de la ruta)."""
        for kind, specs in SPECS.items():
            for last, found in specs.items():
                optional = found[9]
                if found[2] is not None:
                    continue
                with self.subTest(param=f"{kind}.{last}"):
                    if optional:
                        self.assertIsNone(self.check(kind, last, None))
                        self.assertIsNone(self.check(kind, last, None, required=False))
                        with self.assertRaises(messages.DesignError):
                            self.check(kind, last, None, required=True)
                    else:
                        with self.assertRaises(messages.DesignError) as caught:
                            self.check(kind, last, None)
                        error = caught.exception
                        self.assertEqual(error.code, "des.entity_param_missing")
                        self.assertEqual(error.field, key_of(kind, last))
                        self.assertEqual(error.obj, f"{LABELS[kind]} «Pista 1»")
                        self.assertIn(f"«{LAYER}»", error.text)
                        self.assertIsNone(self.check(kind, last, None, required=False))
        with self.assertRaises(messages.DesignError) as caught:
            self.check("road", "layer", "   ")
        self.assertEqual(caught.exception.code, "des.entity_param_missing")
        self.assertEqual(self.check("road", "layer", "  gis_fea_pistas  "), "gis_fea_pistas")

    def test_the_mode_is_one_of_the_three(self) -> None:
        """RF-017-02 (plan 017 §5.2.2): el modo es «trazar», «sobre un eje» o «eje 3D» (``trace``, ``on_axis``,
        ``axis_3d``); otro texto es ``des.entity_param_choice`` nombrando la capa, la pista, el campo y el valor."""
        for mode in MODES:
            self.assertEqual(self.check("road", "mode", mode), mode)
        with self.assertRaises(messages.DesignError) as caught:
            self.check("road", "mode", "walk")
        error = caught.exception
        self.assertEqual(error.code, "des.entity_param_choice")
        self.assertEqual(error.field, "des.road.rdw_001.mode")
        self.assertIn("walk", error.text)
        self.assertIn("«axis_3d»", error.text)
        with self.assertRaises(TypeError):
            self.check("road", "mode", 1)

    def test_the_yes_no_of_discarded(self) -> None:
        """RF-015-17 (D-24): ``discarded`` es un sí/no en la pista y en la accesibilidad; un texto es un error del
        programa (``TypeError``)."""
        for kind in SPECS:
            self.assertIs(self.check(kind, "discarded", True), True)
            self.assertIs(self.check(kind, "discarded", False), False)
            with self.assertRaises(TypeError):
                self.check(kind, "discarded", "sí")


def profile_check(last: str, value: object, *, name: str = "Principal", code: str = "principal") -> object:
    return params.check_road_profile_value(name, code, last, value)


class RoadProfileValueTest(unittest.TestCase):
    def test_the_key_of_a_profile_value(self) -> None:
        """RF-017-07 (ADR-0027, D-17 de la 013): la clave del valor de un perfil es
        ``des.roadprofile.{p}.<valor>`` con el código inmutable del perfil (``[a-z][a-z0-9_]*``); un código que no
        lo es o un valor que no es de un perfil es un error del programa."""
        self.assertEqual(params.road_profile_key("pista_principal", "vehicle_width_m"),
                         "des.roadprofile.pista_principal.vehicle_width_m")
        self.assertEqual(params.road_profile_key("a", params.RoadProfileParam.CLASS), "des.roadprofile.a.class")
        for code in ("Principal", "1x", "con espacio", "", "a.b"):
            with self.subTest(code=code), self.assertRaises(ValueError):
                params.road_profile_key(code, "reach_m")
        for last in ("protect", "width_m", "name"):
            with self.subTest(last=last), self.assertRaises(ValueError):
                params.road_profile_key("principal", last)

    def test_every_number_in_its_range(self) -> None:
        """RF-017-04, RF-017-07 (plan 017 §5.2.2): A, f, pd, w, pm, R y Rmín > 0; arcén y caballón ≥ 0; los ángulos de
        (0; 90)° ambos excluidos; el alcance > 0; el factor de malla de (0; 1]; dentro, vuelve como ``float``; fuera, o
        ``nan``, o el infinito, ``des.road_profile_value_range`` nombrando el perfil, la clave del campo, el valor y
        el rango."""
        bounds = {
            "vehicle_width_m": ((0.001, 3.5, 100.0), (0.0, -1.0, 100.001, math.nan, INF)),
            "lane_factor": ((0.001, 3.0, 100.0), (0.0, -1.0, 100.001)),
            "shoulder_m": ((0.0, 1.5, 100.0), (-0.001, 100.001)),
            "berm_m": ((0.0, 1.0, 100.0), (-0.001, 100.001)),
            "max_gradient_pct": ((0.001, 10.0, 100.0), (0.0, -1.0, 100.001)),
            "station_step_m": ((0.001, 1.0, 1000.0), (0.0, -1.0, 1000.001)),
            "max_mean_gradient_pct": ((0.001, 10.5, 100.0), (0.0, -1.0, 100.001)),
            "curve_radius_m": ((0.001, 20.0, 10000.0), (0.0, -1.0, 10000.001)),
            "min_radius_m": ((0.001, 12.0, 10000.0), (0.0, -1.0, 10000.001)),
            "cut_angle_deg": ((0.001, 60.0, 89.999), (0.0, 90.0, 91.0, -1.0, math.nan)),
            "fill_angle_deg": ((0.001, 35.0, 89.999), (0.0, 90.0, 91.0, -1.0, math.nan)),
            "reach_m": ((0.001, 60.0, 10000.0), (0.0, 10000.001, -3.0, INF)),
            "mesh_factor": ((0.001, 0.93, 1.0), (0.0, 1.0000001, 1.5, -1.0)),
        }
        self.assertEqual(set(bounds), set(params.ROAD_PROFILE_RANGES))
        for last, (inside, outside) in bounds.items():
            key = f"des.roadprofile.principal.{last}"
            for value in inside:
                with self.subTest(param=last, value=value):
                    checked = profile_check(last, value)
                    self.assertEqual(checked, value)
                    self.assertIs(type(checked), float)
            for value in outside:
                with self.subTest(param=last, value=value):
                    with self.assertRaises(messages.DesignError) as caught:
                        profile_check(last, value)
                    error = caught.exception
                    self.assertEqual(error.code, "des.road_profile_value_range")
                    self.assertEqual(error.field, key)
                    self.assertEqual(error.obj, "Perfil de pista «Principal»")
                    self.assertEqual(error.values["profile"], "Principal")
                    self.assertIn("«Principal»", error.text)
                    self.assertIn(key, error.text)
                    self.assertIn(params.ROAD_PROFILE_RANGES[last].text(), error.text)
                    self.assertNotIn("{", error.text)
                    self.assertNotIn("?", error.text)
        self.assertEqual(profile_check("reach_m", 60), 60.0)  # un entero es un número real

    def test_a_missing_value_is_rejected_naming_the_profile_and_the_field(self) -> None:
        """RF-017-04 (un perfil incompleto), D-2 (sin valor por defecto): un valor sin valor (``None`` o, en un texto,
        en blanco) se rechaza con ``des.road_profile_value_missing`` nombrando el perfil y la clave del campo; no se
        elige ninguno por la persona; un tipo que no es el suyo es un error del programa (``TypeError``)."""
        for last, found in PROFILE_SPECS.items():
            with self.subTest(param=last):
                with self.assertRaises(messages.DesignError) as caught:
                    profile_check(last, None)
                error = caught.exception
                self.assertEqual(error.code, "des.road_profile_value_missing")
                self.assertEqual(error.field, f"des.roadprofile.principal.{last}")
                self.assertEqual(error.values["profile"], "Principal")
                self.assertIn("«Principal»", error.text)
                self.assertIn(error.field, error.text)
                self.assertIn("Perfil de pista…", error.text)  # dice dónde se declara
        with self.assertRaises(messages.DesignError) as caught:
            profile_check("class", "   ")
        self.assertEqual(caught.exception.code, "des.road_profile_value_missing")
        for last, wrong in (("reach_m", "60"), ("reach_m", True), ("class", 3), ("metric", 1.0), ("shoulder_m", [0])):
            with self.subTest(param=last, value=wrong), self.assertRaises(TypeError):
                profile_check(last, wrong)

    def test_the_class_and_the_metric_are_texts(self) -> None:
        """RF-017-07 (N-15): la clase normativa es un texto («Pista principal», «Acceso al tajo»…; vuelve sin los
        espacios de los extremos) y la métrica, una de ``exact`` o ``chamfer5`` (otra, ``des.road_profile_value_range``
        con las opciones como rango)."""
        self.assertEqual(profile_check("class", "  Acceso al tajo "), "Acceso al tajo")
        for metric in METRICS:
            self.assertEqual(profile_check("metric", metric), metric)
        with self.assertRaises(messages.DesignError) as caught:
            profile_check("metric", "chamfer7")
        error = caught.exception
        self.assertEqual(error.code, "des.road_profile_value_range")
        self.assertEqual(error.field, "des.roadprofile.principal.metric")
        self.assertIn("«exact»", error.text)
        self.assertIn("«chamfer5»", error.text)
        self.assertIn("chamfer7", error.text)


class RoadProfileTest(unittest.TestCase):
    def check(self, values: dict[str, object], **options: str) -> dict[str, object]:
        return params.check_road_profile(options.get("name", "Pista de referencia"),
                                         options.get("code", "referencia"), values)

    def test_the_reference_profile_is_accepted(self) -> None:
        """RF-017-04, RF-017-07, RF-017-08 (D-2): el perfil de referencia de IMGA (``spec.md`` §11, solo para
        pruebas: A = 3,5 m, f = 3, arcén 0 m, caballón 1 m, pd 10 %, R 20 m, Rmín 12 m, desmonte a 60° y terraplén a
        35°) se acepta y vuelve completo, con los valores por defecto del factor de malla y la métrica si no se dan."""
        values = reference_values()
        self.assertEqual(self.check(values), values)
        bare = {last: value for last, value in values.items() if last not in PROFILE_DEFAULTS}
        checked = self.check(bare)
        self.assertEqual(checked, values)
        self.assertEqual((checked["mesh_factor"], checked["metric"]), (1.0, "exact"))
        self.assertEqual(self.check({**bare, "mesh_factor": None, "metric": None}), values)  # sin valor = el de siempre
        self.assertEqual(self.check({**values, "mesh_factor": 0.93})["mesh_factor"], 0.93)

    def test_an_incomplete_profile_is_rejected_value_by_value(self) -> None:
        """RF-017-04 (un perfil incompleto): cada valor sin valor por defecto que falta (los 13) se rechaza con
        ``des.road_profile_value_missing`` nombrando el perfil y el campo; no se completa ninguno."""
        values = reference_values()
        required = [last for last in PROFILE_SPECS if last not in PROFILE_DEFAULTS]
        self.assertEqual(len(required), 13)
        for last in required:
            with self.subTest(missing=last):
                with self.assertRaises(messages.DesignError) as caught:
                    self.check({key: value for key, value in values.items() if key != last})
                error = caught.exception
                self.assertEqual(error.code, "des.road_profile_value_missing")
                self.assertEqual(error.field, f"des.roadprofile.referencia.{last}")
                self.assertEqual(error.values["profile"], "Pista de referencia")
        with self.assertRaises(messages.DesignError) as caught:
            self.check({})
        self.assertEqual(caught.exception.code, "des.road_profile_value_missing")

    def test_a_value_out_of_range_is_rejected_naming_the_profile_the_field_and_the_value(self) -> None:
        """RF-017-04, RF-017-07 (un valor fuera de su rango): ``des.road_profile_value_range`` con el perfil, el campo
        y el valor, sin tocar el resto; un nombre de valor que no es de un perfil es un error del programa."""
        values = reference_values()
        for last, wrong in (("shoulder_m", -1.0), ("cut_angle_deg", 90.0), ("fill_angle_deg", 0.0),
                            ("mesh_factor", 1.5), ("max_gradient_pct", 0.0), ("lane_factor", -3.0)):
            with self.subTest(param=last):
                with self.assertRaises(messages.DesignError) as caught:
                    self.check({**values, last: wrong})
                error = caught.exception
                self.assertEqual(error.code, "des.road_profile_value_range")
                self.assertEqual(error.field, f"des.roadprofile.referencia.{last}")
                self.assertEqual(error.values["value"], wrong)
                self.assertEqual(error.values["profile"], "Pista de referencia")
        with self.assertRaises(ValueError):
            self.check({**values, "protect": True})

    def test_the_half_width_of_the_section(self) -> None:
        """RF-017-08 (calzada f·A, sección = calzada + arcén + caballón, semianchura): con A = 3,5 m, f = 3, arcén 0 m
        y caballón 1 m, la calzada es de 10,5 m, la sección de 11,5 m y la semianchura de 5,75 m, a ≤ 10⁻⁹ relativo
        (la cuenta a mano está en ``road_data``); con arcén 2 m, la de 6,75 m."""
        found = params.road_half_width_m(3.5, 3.0, 0.0, 1.0)
        self.assertLessEqual(abs(found - 5.75) / 5.75, 1e-9)
        self.assertLessEqual(abs(found - road_data.PROFILE.half_section_m) / 5.75, 1e-9)
        self.assertLessEqual(abs(params.road_half_width_m(3.5, 3.0, 2.0, 1.0) - 6.75) / 6.75, 1e-9)
        self.assertLessEqual(abs(params.road_half_width_m(3.0, 2.0, 0.0, 0.0) - 3.0) / 3.0, 1e-9)

    def test_a_minimum_radius_above_the_radius_is_rejected(self) -> None:
        """RF-017-04, RF-017-07 (Rmín ≤ R): un radio mínimo mayor que el de las curvas se rechaza con
        ``des.road_profile_radius_order`` nombrando el perfil, el campo (el del radio mínimo), el valor y el radio; el
        igual se acepta."""
        values = reference_values()
        with self.assertRaises(messages.DesignError) as caught:
            self.check({**values, "min_radius_m": 25.0})
        error = caught.exception
        self.assertEqual(error.code, "des.road_profile_radius_order")
        self.assertEqual(error.field, "des.roadprofile.referencia.min_radius_m")
        self.assertEqual(error.values["value"], 25.0)
        self.assertEqual(error.values["radius"], 20.0)
        self.assertEqual(error.values["profile"], "Pista de referencia")
        self.assertIn("«Pista de referencia»", error.text)
        self.assertIn("25", error.text)
        self.assertEqual(self.check({**values, "min_radius_m": 20.0})["min_radius_m"], 20.0)
        self.assertEqual(self.check({**values, "curve_radius_m": 12.0})["curve_radius_m"], 12.0)

    def test_a_minimum_radius_below_the_half_width_is_rejected(self) -> None:
        """RF-017-04 (el borde interior de una curva se plegaría sobre sí mismo), RF-017-07 (Rmín ≥ la semianchura de
        su sección): con la semianchura de 5,75 m de la referencia, un radio mínimo de 5 m se rechaza con
        ``des.road_profile_radius_narrow`` nombrando el perfil, el campo, el valor y la semianchura; el de 5,75 m, que
        es igual, se acepta; con un arcén de 2 m (6,75 m) el de 6,7 m ya no."""
        values = reference_values()
        with self.assertRaises(messages.DesignError) as caught:
            self.check({**values, "min_radius_m": 5.0})
        error = caught.exception
        self.assertEqual(error.code, "des.road_profile_radius_narrow")
        self.assertEqual(error.field, "des.roadprofile.referencia.min_radius_m")
        self.assertEqual(error.values["value"], 5.0)
        self.assertLessEqual(abs(float(error.values["half_width"]) - 5.75), 1e-9)
        self.assertEqual(error.values["profile"], "Pista de referencia")
        self.assertIn("«Pista de referencia»", error.text)
        self.assertIn("5,75", error.text)
        self.assertEqual(self.check({**values, "min_radius_m": 5.75})["min_radius_m"], 5.75)
        wide = {**values, "shoulder_m": 2.0}
        self.assertEqual(self.check({**wide, "min_radius_m": 6.75})["min_radius_m"], 6.75)
        with self.assertRaises(messages.DesignError) as caught:
            self.check({**wide, "min_radius_m": 6.7})
        self.assertEqual(caught.exception.code, "des.road_profile_radius_narrow")
        with self.assertRaises(messages.DesignError) as caught:  # Rmín > R se dice antes que lo estrecho
            self.check({**values, "curve_radius_m": 3.0, "min_radius_m": 4.0})
        self.assertEqual(caught.exception.code, "des.road_profile_radius_order")

    def test_the_radii_check_alone(self) -> None:
        """RF-017-04 (el editor de perfiles de la T04 y la pista comprueban lo mismo): ``check_road_profile_radii``
        es la comprobación cruzada sola, sobre los valores ya comprobados; no devuelve nada si cumple."""
        values = reference_values()
        self.assertIsNone(params.check_road_profile_radii("Pista de referencia", "referencia", values))
        with self.assertRaises(messages.DesignError) as caught:
            params.check_road_profile_radii("Pista de referencia", "referencia", {**values, "min_radius_m": 1.0})
        self.assertEqual(caught.exception.code, "des.road_profile_radius_narrow")


if __name__ == "__main__":
    unittest.main()
