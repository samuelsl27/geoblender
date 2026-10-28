# SPDX-License-Identifier: GPL-3.0-or-later
"""Parámetros de las restricciones (spec 012, T05; HU-012-2; RF-012-02, RF-012-04, RF-012-08;
plan 012 §5.2.2, D-5 de la spec; ADR-0027).

``core.constraints.params`` declara las cuatro **familias** de una restricción, una clave por
restricción con su código inmutable (D-22): ``core.constraint.{c}.buffer_out_m`` y
``.buffer_in_m`` (m, [0; 1 000]), ``.weight`` (—, [1; 1 000]) y ``.active`` (sí/no), todas
**sin valor por defecto** (D-5: un resguardo por defecto sería una distancia de seguridad
inventada) y **de versión** (D-4); y el parámetro del proyecto
``core.constraints.search_distance_m``, 25 m ADOPTADO «sin confirmar» en (0; 1 000] m. Importar
el módulo no registra nada: ``bl`` las registra y las quita sin dejar rastro.
"""

from __future__ import annotations

import unittest

from tests.support.package import import_geoblender

params = import_geoblender("core.constraints.params")
model = import_geoblender("core.constraints.model")
core_params = import_geoblender("core.params")
i18n = import_geoblender("core.i18n")

ParamError = core_params.ParamError
SPANISH_LETTERS = frozenset("áéíóúüñÁÉÍÓÚÜÑ¿¡")
SEARCH = "core.constraints.search_distance_m"

# Plan §5.2.2: patrón → (tipo de valor, unidad, mínimo, máximo, tipo por defecto, RF, español).
FAMILIES: dict[str, tuple[str, str, float | None, float | None, str, tuple[str, ...], str]] = {
    "core.constraint.{c}.buffer_out_m": (
        "float", "m", 0.0, 1000.0, "HIPÓTESIS", ("RF-012-02", "RF-012-04", "RF-012-12"),
        "Resguardo hacia fuera"),
    "core.constraint.{c}.buffer_in_m": (
        "float", "m", 0.0, 1000.0, "HIPÓTESIS", ("RF-012-02", "RF-012-04", "RF-012-13"),
        "Resguardo hacia dentro del límite"),
    "core.constraint.{c}.weight": (
        "float", "-", 1.0, 1000.0, "HIPÓTESIS", ("RF-012-02", "RF-012-04", "RF-012-22"),
        "Peso de la zona preferible no afectar"),
    "core.constraint.{c}.active": (
        "bool", "-", None, None, "ADOPTADO", ("RF-012-02", "RF-012-04", "RF-012-16"),
        "Restricción activa"),
}


class FamiliesTest(unittest.TestCase):
    def test_four_families_without_default(self) -> None:
        """RF-012-02 (D-5, ADR-0027): las cuatro familias de ``core`` en el orden del plan, sin
        valor por defecto («sin valor» admitido), de versión, declaradas por una persona; no se
        solapan entre sí."""
        self.assertEqual([family.pattern for family in params.FAMILIES], list(FAMILIES))
        for family in params.FAMILIES:
            value_type, unit, low, high, kind, rfs, _ = FAMILIES[family.pattern]
            template = family.template
            with self.subTest(pattern=family.pattern):
                self.assertIsInstance(family, core_params.ParamFamily)
                self.assertEqual(family.module, "core")
                self.assertEqual((template.value_type, template.unit), (value_type, unit))
                self.assertIsNone(template.default)
                self.assertTrue(template.allow_empty)
                self.assertIsNone(template.check(None))
                self.assertEqual(template.kind, kind)
                self.assertEqual(template.source_kind, "person")
                self.assertEqual((template.minimum, template.maximum), (low, high))
                self.assertFalse(template.min_exclusive)
                self.assertEqual(template.scope, "version")
                self.assertEqual(template.requirements, rfs)
                self.assertIn("D-5", template.source)
        for one in params.FAMILIES:
            for other in params.FAMILIES:
                if one is not other:
                    self.assertFalse(one.overlaps(other), (one.pattern, other.pattern))

    def test_ranges(self) -> None:
        """RF-012-02: resguardos ≥ 0 y ≤ 1 000 m; peso ≥ 1; «activa» es sí o no."""
        out = params.family(model.ConstraintParam.BUFFER_OUT).template
        self.assertEqual(out.check(0), 0.0)
        self.assertEqual(out.check(8.0), 8.0)
        for wrong in (-0.001, 1000.5):
            with self.subTest(value=wrong), self.assertRaises(ParamError) as caught:
                out.check(wrong)
            self.assertEqual(caught.exception.code, "core.param_out_of_range")
        weight = params.family(model.ConstraintParam.WEIGHT).template
        self.assertEqual(weight.check(3), 3.0)
        with self.assertRaises(ParamError):
            weight.check(0.5)
        active = params.family(model.ConstraintParam.ACTIVE).template
        self.assertIs(active.check(True), True)
        with self.assertRaises(ParamError):
            active.check(1)

    def test_keys_of_a_constraint(self) -> None:
        """RF-012-02 (D-22): la clave lleva el código de la restricción y casa con su familia y
        con ninguna otra; un código que no es ``[a-z][a-z0-9_]*`` es un error del programa."""
        keys = {
            params.buffer_out_key("torre_132"): "core.constraint.{c}.buffer_out_m",
            params.buffer_in_key("concesion"): "core.constraint.{c}.buffer_in_m",
            params.weight_key("vaguada"): "core.constraint.{c}.weight",
            params.active_key("torre_132"): "core.constraint.{c}.active",
        }
        self.assertEqual(list(keys), [
            "core.constraint.torre_132.buffer_out_m", "core.constraint.concesion.buffer_in_m",
            "core.constraint.vaguada.weight", "core.constraint.torre_132.active"])
        for key, pattern in keys.items():
            with self.subTest(key=key):
                matching = [family.pattern for family in params.FAMILIES
                            if family.match(key) is not None]
                self.assertEqual(matching, [pattern])
        self.assertEqual(params.param_key("torre_132", model.ConstraintParam.WEIGHT),
                         "core.constraint.torre_132.weight")
        for wrong in ("Torre", "1torre", "", "torre 132", "torre.132"):
            with self.subTest(code=wrong), self.assertRaises(ValueError):
                params.buffer_out_key(wrong)

    def test_labels_registration_without_trace(self) -> None:
        """RF-008-06, RF-012-02 (ADR-0027): cada familia lleva su etiqueta, con su español en
        ``messages.toml``; registradas, ``definition`` da la de
        ``core.constraint.torre_132.buffer_out_m`` (sin valor por defecto, de versión) y su
        nombre visible lleva el código; ``unregister_families("core")`` las quita sin rastro."""
        table = i18n.load_messages()
        for family in params.FAMILIES:
            label = family.template.label_msgid
            with self.subTest(pattern=family.pattern):
                self.assertEqual(set(label) & SPANISH_LETTERS, set(), "msgid en inglés")
                self.assertEqual(i18n.placeholders(label), set())
                self.assertEqual(table[label], FAMILIES[family.pattern][6])
        before = dict(core_params.FAMILIES)
        self.addCleanup(core_params.unregister_families, "core")
        core_params.register_families(params.FAMILIES)
        key = "core.constraint.torre_132.buffer_out_m"
        found = core_params.definition(key)
        self.assertEqual(found.key, key)
        self.assertIsNone(found.default)
        self.assertEqual(found.scope, "version")
        self.assertEqual(core_params.parameter_label(key),
                         "Resguardo hacia fuera · torre_132")
        self.assertIsNone(core_params.definition("core.constraint.Torre.buffer_out_m"))
        with self.assertRaises(ValueError):
            core_params.register_families(params.FAMILIES)
        self.assertEqual(core_params.unregister_families("core"), len(FAMILIES))
        self.assertEqual(dict(core_params.FAMILIES), before)
        self.assertIsNone(core_params.definition(key))


class SearchDistanceTest(unittest.TestCase):
    def test_search_distance(self) -> None:
        """RF-012-08 (D-5): 25 m ADOPTADO «sin confirmar» (unas tres veces los 8 m de la torre),
        del proyecto, en (0; 1 000] m, con su etiqueta en español."""
        defn = params.SEARCH_DISTANCE
        self.assertEqual(params.DEFINITIONS, (defn,))
        self.assertEqual(defn.key, SEARCH)
        self.assertEqual((defn.value_type, defn.unit, defn.default), ("float", "m", 25.0))
        self.assertEqual((defn.minimum, defn.maximum, defn.min_exclusive), (0.0, 1000.0, True))
        self.assertEqual((defn.kind, defn.scope), ("ADOPTADO", "project"))
        self.assertEqual(defn.requirements, ("RF-012-08",))
        self.assertIn("D-5", defn.source)
        self.assertFalse(defn.allow_empty)
        with self.assertRaises(ParamError):
            defn.check(0.0)
        self.assertEqual(defn.check(1000), 1000.0)
        self.assertEqual(i18n.load_messages()[defn.label_msgid],
                         "Distancia de búsqueda de intocables")

    def test_registered_and_removed_without_trace(self) -> None:
        """RF-008-01: ``bl`` la registra en ``core.params``; quitar las de ``core`` la quita
        sin rastro (lo que ya estaba registrado se vuelve a poner)."""
        before = dict(core_params.DEFINITIONS)

        def restore() -> None:
            core_params.unregister_definitions("core")
            core_params.register_definitions(
                [defn for key, defn in before.items() if defn.module == "core"])

        self.addCleanup(restore)
        core_params.register_definitions(params.DEFINITIONS)
        self.assertIs(core_params.DEFINITIONS[SEARCH], params.SEARCH_DISTANCE)
        core_params.unregister_definitions("core")
        self.assertNotIn(SEARCH, core_params.DEFINITIONS)
        restore()
        self.assertEqual(dict(core_params.DEFINITIONS), before)


if __name__ == "__main__":
    unittest.main()
