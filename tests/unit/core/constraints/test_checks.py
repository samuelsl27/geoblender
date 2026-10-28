# SPDX-License-Identifier: GPL-3.0-or-later
"""Restricciones incompletas y sus mensajes (spec 012, T05; HU-012-2; RF-012-04, RF-012-02;
plan 012 §5.1, §5.3.1 y D-23; spec §8).

``core.constraints.checks.incomplete`` lista, de cada restricción **activa** (o cuya «activa»
falta), lo que impide compilarla: sin tipo, motivo, decisor o código (o un código mal formado o
repetido en las tres capas), sin un parámetro que su tipo pide (o con uno fuera de su rango),
un límite que no es un polígono y una línea o un punto sin resguardo hacia fuera > 0 m. Cada
problema lleva el nombre, el tipo, el código del problema, el campo y el valor, y su texto en
español. La geometría no válida (se corta, sin área, sin longitud) la mira ``gis``.

``core.constraints.messages`` tiene los códigos ``core.constraint_*`` con su ``msgid`` en inglés
y su español, con los mismos marcadores, y ``ConstraintError`` con objeto, campo y valor.
"""

from __future__ import annotations

import dataclasses
import unittest
from datetime import date

from tests.support import constraints_fixtures as fx
from tests.support.package import import_geoblender

model = import_geoblender("core.constraints.model")
params = import_geoblender("core.constraints.params")
checks = import_geoblender("core.constraints.checks")
messages = import_geoblender("core.constraints.messages")
errors = import_geoblender("core.errors")
i18n = import_geoblender("core.i18n")
store = import_geoblender("core.params.store")

T = model.ConstraintType
G = model.GeometryKind
SPANISH_LETTERS = frozenset("áéíóúüñÁÉÍÓÚÜÑ¿¡")


def make(code: str, ctype: object, kind: object = G.POLYGON, **changes: object) -> object:
    """Una restricción completa de ``ctype`` con geometría ``kind``."""
    kind = G(kind)
    if kind is G.POLYGON:
        parts = ((fx.rectangle(0, 0, 20, 20),),)
    elif kind is G.LINE:
        parts = ((fx.absolute([(0, 0), (50, 10)]),),)
    else:
        parts = ((fx.absolute([(5, 5)]),),)
    fields: dict[str, object] = {
        "uid": code.ljust(32, "0")[:32], "code": code, "name": code.replace("_", " ").title(),
        "ctype": ctype, "kind": kind, "parts": parts, "priority": 0,
        "reason": "Motivo sintético", "decided_by": "Propiedad",
        "decided_on": date(2026, 10, 1), "decision_uid": None, "intention_uid": None,
        "source_input": None, "source_fid": None, "layer": f"core_constraint_{kind.value}",
        "fid": 1,
    }
    fields.update(changes)
    return model.Constraint(**fields)


def resolved_for(*constraints: object, **overrides: object) -> dict[str, object]:
    """Los parámetros completos de ``constraints`` (resguardos de 8 m, 10 m hacia dentro, peso 3,
    activas), con ``overrides`` por clave (``None`` = sin valor)."""
    values: dict[str, object] = {}
    for item in constraints:
        values[params.active_key(item.code)] = True
        for role in item.ctype.requires:
            key = params.param_key(item.code, role)
            values.setdefault(key, {model.ConstraintParam.BUFFER_OUT: 8.0,
                                    model.ConstraintParam.BUFFER_IN: 10.0,
                                    model.ConstraintParam.WEIGHT: 3.0,
                                    model.ConstraintParam.ACTIVE: True}[role])
    values.update({key.replace("__", "."): value for key, value in overrides.items()})
    return values


def problems(found: tuple[object, ...]) -> list[tuple[str, str, str]]:
    return [(item.code, item.problem, item.field) for item in found]


class IncompleteTest(unittest.TestCase):
    def test_complete_constraints_of_every_type(self) -> None:
        """RF-012-04: una restricción de cada tipo, completa (los límites como polígonos, los
        demás en sus tres geometrías con resguardo > 0), no se lista; un polígono con resguardo
        hacia fuera de 0 m tampoco (D-23: ≥ 0 en un polígono)."""
        constraints = []
        for ctype in T:
            for kind in ctype.geometry_kinds:
                constraints.append(make(f"{ctype.value}_{kind.value}", ctype, kind))
        values = resolved_for(*constraints)
        self.assertEqual(checks.incomplete(constraints, values), ())
        zero = make("vaguada", T.NO_CUT)
        values = resolved_for(zero, **{params.buffer_out_key("vaguada"): 0.0})
        self.assertEqual(checks.incomplete([zero], values), ())

    def test_drawn_in_qgis(self) -> None:
        """RF-012-04 (spec §8: «sin motivo o decisor, p. ej. dibujada en QGIS»): sin tipo, sin
        motivo, sin decisor, sin código y sin parámetros: se listan todos sus problemas, con su
        capa y su fid como nombre."""
        drawn = make("", None, name="", reason=None, decided_by=" ", fid=12)
        found = checks.incomplete([drawn], {})
        self.assertEqual(problems(found), [
            ("", "core.constraint_no_code", "code"),
            ("", "core.constraint_no_type", "ctype"),
            ("", "core.constraint_no_reason", "reason"),
            ("", "core.constraint_no_decider", "decided_by"),
        ])
        self.assertEqual({item.name for item in found}, {""})
        self.assertIsNone(found[0].ctype)
        self.assertEqual(found[1].text(), "Sin nombre (core_constraint_polygon, fid 12): no tiene "
                         "un tipo válido; elija uno de los once en Diseño ▸ Límites y "
                         "restricciones ▸ Restricciones…")

    def test_missing_reason_decider_and_parameters(self) -> None:
        """RF-012-04, RF-012-02 (D-5, D-23): sin motivo, sin decisor, sin «activa» y sin el
        resguardo o el peso que pide su tipo; cada uno con su clave y el nombre visible del
        parámetro, y la restricción se sigue mirando (falta «activa»: no se sabe si está
        activa)."""
        avoid = make("vaguada", T.AVOID, reason="  ", decided_by=None)
        limit = make("concesion", T.LEGAL_LIMIT)
        values = resolved_for(avoid, limit)
        del values[params.weight_key("vaguada")]
        del values[params.active_key("vaguada")]
        values[params.buffer_in_key("concesion")] = None
        found = checks.incomplete([avoid, limit], values)
        self.assertEqual(problems(found), [
            ("vaguada", "core.constraint_no_reason", "reason"),
            ("vaguada", "core.constraint_no_decider", "decided_by"),
            ("vaguada", "core.constraint_param_missing", "core.constraint.vaguada.weight"),
            ("vaguada", "core.constraint_param_missing", "core.constraint.vaguada.active"),
            ("concesion", "core.constraint_param_missing",
             "core.constraint.concesion.buffer_in_m"),
        ])
        self.assertEqual(found[2].ctype, T.AVOID)
        self.assertEqual(
            found[2].text(),
            "Vaguada (Preferible no afectar): falta el valor de «Peso de la zona preferible no "
            "afectar» (core.constraint.vaguada.weight); declárelo al completar la restricción "
            "(Diseño ▸ Límites y restricciones ▸ Restricciones…).")

    def test_limit_that_is_not_a_polygon(self) -> None:
        """RF-012-04 (D-23): un límite legal o un perímetro de actuación que no es un polígono
        no es válido."""
        limit = make("concesion", T.LEGAL_LIMIT, G.LINE)
        perimeter = make("perimetro", T.ACTION_PERIMETER, G.POINT)
        found = checks.incomplete([limit, perimeter], resolved_for(limit, perimeter))
        self.assertEqual(problems(found), [
            ("concesion", "core.constraint_limit_not_polygon", "geometry"),
            ("perimetro", "core.constraint_limit_not_polygon", "geometry"),
        ])
        self.assertEqual(found[0].value, "line")
        self.assertEqual(found[1].text(), "Perimetro (Perímetro de actuación) es un punto: un "
                         "límite ha de ser un polígono.")

    def test_line_or_point_without_outward_buffer(self) -> None:
        """RF-012-04 (spec §8: «punto o línea sin resguardo hacia fuera»): una línea o un punto
        con resguardo de 0 m no ocupa ninguna celda; sin resguardo, falta el parámetro."""
        line = make("linea_132", T.UNTOUCHABLE, G.LINE)
        point = make("torre_132", T.EXCLUSION, G.POINT)
        values = resolved_for(line, point)
        values[params.buffer_out_key("linea_132")] = 0.0
        values[params.buffer_out_key("torre_132")] = None
        found = checks.incomplete([line, point], values)
        self.assertEqual(problems(found), [
            ("linea_132", "core.constraint_buffer_not_positive",
             "core.constraint.linea_132.buffer_out_m"),
            ("torre_132", "core.constraint_param_missing",
             "core.constraint.torre_132.buffer_out_m"),
        ])
        self.assertEqual(found[0].value, 0.0)
        self.assertEqual(found[0].text(), "Linea 132 (Intocable) es una línea con un resguardo "
                         "hacia fuera de 0 m: una línea o un punto necesita un resguardo mayor "
                         "que 0 m, o no ocupa ninguna celda.")

    def test_codes_badly_formed_or_repeated_and_values_out_of_range(self) -> None:
        """RF-012-02, RF-012-04 (D-22): un código escrito a mano en QGIS que no es
        ``[a-z][a-z0-9_]*`` o que se repite en las tres capas; un valor fuera de su rango (un
        peso de 0,5)."""
        badly = make("Torre 1", T.NO_FILL, G.POINT)
        first = make("balsa", T.NO_CUT, layer="core_constraint_polygon")
        second = make("balsa", T.NO_FILL, G.LINE, fid=4)
        avoid = make("vaguada", T.AVOID)
        values = resolved_for(first, avoid, **{params.weight_key("vaguada"): 0.5})
        values[params.active_key("balsa")] = True
        found = checks.incomplete([badly, first, second, avoid], values)
        self.assertEqual(problems(found), [
            ("Torre 1", "core.constraint_code_invalid", "code"),
            ("balsa", "core.constraint_code_repeated", "code"),
            ("balsa", "core.constraint_code_repeated", "code"),
            ("vaguada", "core.constraint_param_invalid", "core.constraint.vaguada.weight"),
        ])
        self.assertEqual(found[3].value, 0.5)
        self.assertIn("0,5", found[3].text())

    def test_inactive_constraints_are_not_listed(self) -> None:
        """RF-012-04: solo se listan las activas: una desactivada en esta versión, aunque le
        falte el motivo, no impide compilar; los valores pueden llegar como ``ResolvedParam``
        de ``core.params`` (lo que lee la compilación)."""
        off = make("acopio", T.NO_CUT, reason=None)
        values = resolved_for(off)
        values[params.active_key("acopio")] = resolved(params.active_key("acopio"), False)
        values[params.buffer_out_key("acopio")] = resolved(params.buffer_out_key("acopio"), None)
        self.assertEqual(checks.incomplete([off], values), ())
        values[params.active_key("acopio")] = resolved(params.active_key("acopio"), True)
        self.assertEqual(problems(checks.incomplete([off], values)), [
            ("acopio", "core.constraint_no_reason", "reason"),
            ("acopio", "core.constraint_param_missing", "core.constraint.acopio.buffer_out_m"),
        ])


def resolved(key: str, value: object) -> object:
    return store.ResolvedParam(
        parameter_uid="9" * 32, key=key, scope="version", scope_uid="8" * 32, rev=1,
        value=value, value_json=None, unit="-", kind="ADOPTADO", unconfirmed=False,
        value_sha256="7" * 64)


class MessagesTest(unittest.TestCase):
    def test_codes_in_both_languages(self) -> None:
        """Principio 10: cada código ``core.constraint_*`` tiene su ``msgid`` en inglés y su
        español, distintos y con los mismos marcadores; los problemas de ``incomplete`` están
        todos en el catálogo; ``CATALOG_ES`` los da para ``core.i18n.install``."""
        codes = [message.code for message in messages.CATALOG]
        self.assertEqual(len(set(codes)), len(codes))
        self.assertTrue(set(checks.PROBLEMS) <= set(codes))
        for message in messages.CATALOG:
            with self.subTest(code=message.code):
                self.assertTrue(message.code.startswith("core.constraint"))
                self.assertEqual(set(message.msgid) & SPANISH_LETTERS, set())
                self.assertNotEqual(message.msgid, message.es)
                self.assertEqual(i18n.placeholders(message.msgid),
                                 i18n.placeholders(message.es))
                self.assertEqual(messages.CATALOG_ES[message.msgid], message.es)
        with self.assertRaises(ValueError):
            messages.render("core.no_such_code")

    def test_error_with_object_field_and_value(self) -> None:
        """Principio 10: ``ConstraintError`` es un ``GeoblenderError`` con su código, el objeto
        (la restricción), el campo y el valor, y el texto en español con coma decimal."""
        error = messages.ConstraintError(
            "core.constraint_buffer_not_positive", name="Torre", ctype="Intocable",
            geometry="un punto", value=0.0, field="core.constraint.torre.buffer_out_m")
        self.assertIsInstance(error, errors.GeoblenderError)
        self.assertEqual(error.code, "core.constraint_buffer_not_positive")
        self.assertEqual(error.obj, "Restricción «Torre»")
        self.assertEqual(error.field, "core.constraint.torre.buffer_out_m")
        self.assertEqual(error.value, 0.0)
        self.assertIn("Torre (Intocable) es un punto con un resguardo hacia fuera de 0 m",
                      error.text)
        self.assertEqual(str(error), error.text)
        english = messages.render("core.constraint_buffer_not_positive", language="en",
                                  name="Tower", ctype="Untouchable", geometry="a point",
                                  value=0.5)
        self.assertIn("0.5 m", english)


class IncompleteRecordTest(unittest.TestCase):
    def test_record_is_frozen(self) -> None:
        """RF-012-04: lo listado es inmutable y nombra la restricción, su tipo y su problema."""
        item = checks.Incomplete(code="x", name="X", ctype=None, problem="core.constraint_no_type",
                                 field="ctype", value=None, layer="core_constraint_line", fid=2,
                                 kind="line")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            item.problem = "otro"  # type: ignore[misc]
        self.assertTrue(item.text("en").startswith("X: "))
        bare = dataclasses.replace(item, name="", code="")
        self.assertTrue(bare.text("en").startswith("Unnamed (core_constraint_line, fid 2): "))


if __name__ == "__main__":
    unittest.main()
