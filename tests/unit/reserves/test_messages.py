# SPDX-License-Identifier: GPL-3.0-or-later
"""Mensajes de la cubicación (spec 011, T03; plan 011 §5.1, §5.4 y §5.5; constitución,
principio 10).

Cada rechazo, aviso o nota que puede dar ``reserves`` tiene un **código** estable ``res.*``,
un ``msgid`` en inglés (su versión inglesa) y su texto en español, con los mismos marcadores
en los dos; ``ResError`` es el error para el usuario con su objeto, su campo y su valor.
Aquí están los que nombran los algoritmos (A1, A2, A4, A6, A7, A8, A13, A14) y la interfaz
(§5.5) del plan, para RF-011-03 (superficies que no casan), RF-011-08 (dominios no válidos),
RF-011-09 (bancos), RF-011-15 (porcentajes), RF-011-17 (falta una densidad o un K),
RF-011-18 (sin material útil) y RF-011-19 (momentos); las tareas siguientes añaden los
suyos.
"""

from __future__ import annotations

import unittest

from tests.support.package import import_geoblender

messages = import_geoblender("reserves.messages")
errors = import_geoblender("core.errors")
i18n = import_geoblender("core.i18n")

SPANISH_LETTERS = frozenset("áéíóúüñÁÉÍÓÚÜÑ¿¡")

# Los códigos del plan (§5.4 y §5.5) con su gravedad: «error» se lanza (ResError), «warning»
# se informa y «note» acompaña a una fila de la tabla o a un elemento de una lista.
PLAN_CODES: dict[str, str] = {
    "res.surfaces_mismatch": "error",           # A1, RF-011-03
    "res.surface_other_version": "error",       # A1, RF-011-03
    "res.surface_is_tin": "error",              # A1, RF-011-02 (RF-006-17)
    "res.same_surface": "warning",              # A2, §8 de la spec
    "res.no_common_cells": "error",             # A2, §8 de la spec
    "res.bench_height_range": "error",          # A4, RF-011-09
    "res.bench_levels_not_increasing": "error",  # A4, RF-011-09
    "res.bench_value_not_number": "error",      # A4, RF-011-09
    "res.domains_invalid": "error",             # A6, RF-011-08
    "res.domain_self_intersecting": "note",     # A6, un elemento de la lista
    "res.domain_no_area": "note",
    "res.domain_value_empty": "note",
    "res.domain_overlap": "note",
    "res.thickness_negative": "error",          # A7, RF-011-14
    "res.percent_sum": "error",                 # A8, RF-011-15
    "res.density_missing": "warning",           # A8, RF-011-17
    "res.note_no_density": "note",              # A8, RF-011-17
    "res.note_no_swell": "note",                # A8, RF-011-17
    "res.note_no_useful": "note",               # A9, RF-011-18
    "res.stages_mismatch": "warning",           # A13, RF-011-19
    "res.stages_materials_differ": "warning",   # A13, RF-011-19
    "res.note_no_scale_factor": "note",         # A14
    "res.materials_missing": "error",           # §5.5, RF-011-12
}


class CatalogTest(unittest.TestCase):
    def test_codes_of_the_plan(self) -> None:
        """Plan §5.4 y §5.5: cada rechazo, aviso o nota que nombra el plan tiene su código
        ``res.*`` con su gravedad; todos los códigos son de ``res`` y no se repiten, ni sus
        ``msgid``."""
        codes = [message.code for message in messages.CATALOG]
        self.assertEqual(len(codes), len(set(codes)), "códigos repetidos")
        msgids = [message.msgid for message in messages.CATALOG]
        self.assertEqual(len(msgids), len(set(msgids)), "msgid repetidos")
        for message in messages.CATALOG:
            with self.subTest(code=message.code):
                self.assertRegex(message.code, r"^res\.[a-z][a-z0-9_]*$")
                self.assertIn(message.severity, messages.SEVERITIES)
                self.assertIs(messages.MESSAGES[message.code], message)
        for code, severity in PLAN_CODES.items():
            with self.subTest(code=code):
                self.assertIn(code, messages.MESSAGES)
                self.assertEqual(messages.MESSAGES[code].severity, severity)

    def test_both_languages_with_the_same_placeholders(self) -> None:
        """Principio 10: cada código tiene su texto en los dos idiomas: el ``msgid`` en
        inglés (sin letras del español) y el español, distinto y no vacío, con los mismos
        marcadores con nombre en inglés; ``CATALOG_ES`` (``msgid`` → español) es lo que
        ``core.i18n.install`` recibe y da el mismo texto que ``render``."""
        for message in messages.CATALOG:
            with self.subTest(code=message.code):
                self.assertTrue(message.msgid.strip())
                self.assertTrue(message.es.strip())
                self.assertNotEqual(message.msgid, message.es)
                self.assertEqual(set(message.msgid) & SPANISH_LETTERS, set(),
                                 "msgid en inglés")
                self.assertEqual(i18n.placeholders(message.msgid),
                                 i18n.placeholders(message.es))
                for name in i18n.placeholders(message.es):
                    self.assertRegex(name, r"^[a-z][a-z_]*$")
                self.assertEqual(messages.CATALOG_ES[message.msgid], message.es)
                values = {name: name.upper() for name in i18n.placeholders(message.es)}
                self.assertEqual(messages.render(message.code, **values),
                                 message.es.format(**values))
                self.assertEqual(messages.render(message.code, language="en", **values),
                                 message.msgid.format(**values))

    def test_render_formats_values(self) -> None:
        """Principio 10: un marcador sin valor se ve «?» (nunca ``{…}``); los decimales salen
        con coma en español y con punto en inglés; los valores que sobran se ignoran; un
        código que no es de ``res`` o un idioma desconocido son errores del programa. El
        ejemplo de A1 del plan sale tal cual."""
        text = messages.render("res.surfaces_mismatch", surface="MDT octubre",
                               other="MDT septiembre", detail="paso en X 1 frente a 0,5")
        self.assertEqual(text, "No se pueden cubicar «MDT octubre» y «MDT septiembre»: paso en "
                               "X 1 frente a 0,5. Lleve la superficie a la rejilla del proyecto "
                               "(Topografía ▸ Rejilla de proyecto desde un MDT…).")
        missing = messages.render("res.percent_sum", unit="Capa útil", sobra=1)
        self.assertNotIn("{", missing)
        self.assertIn("?", missing)
        self.assertIn("99,99 %", messages.render("res.percent_sum", unit="Capa útil",
                                                 value=99.99))
        self.assertIn("99.99 %", messages.render("res.percent_sum", language="en",
                                                 unit="Capa útil", value=99.99))
        self.assertEqual(messages.render("res.note_no_useful"), "sin material útil")
        with self.assertRaises(ValueError):
            messages.render("gis.grid_mismatch")
        with self.assertRaises(ValueError):
            messages.render("res.note_no_useful", language="fr")


class ResErrorTest(unittest.TestCase):
    def test_error_with_object_field_and_value(self) -> None:
        """Principio 10 (RF-011-09): ``ResError`` es un ``GeoblenderError`` con el código, el
        ``msgid``, los valores en JSON (para el registro y para verlo en inglés), el objeto,
        el campo y el valor, y su texto en español, que es también ``str(error)``."""
        error = messages.ResError("res.bench_height_range", obj="Cubicación «Mensual»",
                                  field="altura de banco", value=0.0, range="(0; 100] m")
        self.assertIsInstance(error, errors.GeoblenderError)
        self.assertEqual(error.code, "res.bench_height_range")
        self.assertEqual(error.msgid, messages.MESSAGES["res.bench_height_range"].msgid)
        self.assertEqual((error.obj, error.field, error.value),
                         ("Cubicación «Mensual»", "altura de banco", 0.0))
        self.assertEqual(error.values, {"value": 0.0, "range": "(0; 100] m"})
        self.assertEqual(error.text, "Altura de banco: 0 m está fuera de su rango (0; 100] m.")
        self.assertEqual(str(error), error.text)
        self.assertEqual(error.message, error.text)
        self.assertEqual(error.context, error.values)
        english = messages.render(error.code, language="en", **error.values)
        self.assertEqual(english, "Bench height: 0 m is outside its range (0; 100] m.")

    def test_only_errors_are_raised(self) -> None:
        """Un aviso o una nota se informan, no se lanzan; un código desconocido es un error
        del programa (``ValueError``)."""
        for code in ("res.same_surface", "res.note_no_density", "res.no_such_code"):
            with self.subTest(code=code):
                with self.assertRaises(ValueError):
                    messages.ResError(code, obj="Cubicación", field="superficie")
        for code, severity in PLAN_CODES.items():
            if severity == "error":
                with self.subTest(code=code):
                    error = messages.ResError(code, obj="Cubicación", field="campo", value="v")
                    self.assertNotIn("{", error.text)


if __name__ == "__main__":
    unittest.main()
