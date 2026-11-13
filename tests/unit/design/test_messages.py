# SPDX-License-Identifier: GPL-3.0-or-later
"""Mensajes del diseño (spec 013, T02; plan 013 §5.1, §5.3.1 y §5.5; constitución, principio 10).

Cada rechazo, aviso o nota que puede dar ``design`` tiene un **código** estable ``des.*``, un
``msgid`` en inglés (su versión inglesa) y su texto en español, con los mismos marcadores en los
dos; ``DesignError`` es el error para el usuario con su objeto, su campo y su valor. Aquí están los
de los perfiles de banco (RF-013-19, RF-013-20) y el del talud impuesto por sector (RF-013-08); las
tareas siguientes añaden los suyos (superficies, semillas, sectores, envolventes…).
"""

from __future__ import annotations

import unittest
from unittest import mock

from tests.support.package import import_geoblender

messages = import_geoblender("design.messages")
errors = import_geoblender("core.errors")
i18n = import_geoblender("core.i18n")

SPANISH_LETTERS = frozenset("áéíóúüñÁÉÍÓÚÜÑ¿¡")

# Los códigos de la T02 con su gravedad: «error» se lanza (DesignError), «warning» se informa.
CODES: dict[str, str] = {
    "des.profile_name_missing": "error",     # RF-013-19
    "des.profile_name_repeated": "error",    # RF-013-19
    "des.profile_value_missing": "error",    # RF-013-19, D-7
    "des.profile_value_range": "error",      # RF-013-18, RF-013-19
    "des.sector_slope_range": "error",       # RF-013-08
    "des.profile_unresolved": "warning",     # RF-013-20
}


class CatalogTest(unittest.TestCase):
    def test_codes_of_the_task(self) -> None:
        """RF-013-08, RF-013-19, RF-013-20: cada rechazo o aviso de los perfiles y del talud por
        sector tiene su código ``des.*`` con su gravedad; todos los códigos son de ``des`` y no se
        repiten, ni sus ``msgid``."""
        codes = [message.code for message in messages.CATALOG]
        self.assertEqual(len(codes), len(set(codes)), "códigos repetidos")
        msgids = [message.msgid for message in messages.CATALOG]
        self.assertEqual(len(msgids), len(set(msgids)), "msgid repetidos")
        for message in messages.CATALOG:
            with self.subTest(code=message.code):
                self.assertRegex(message.code, r"^des\.[a-z][a-z0-9_]*$")
                self.assertIn(message.severity, messages.SEVERITIES)
                self.assertIs(messages.MESSAGES[message.code], message)
        for code, severity in CODES.items():
            with self.subTest(code=code):
                self.assertIn(code, messages.MESSAGES)
                self.assertEqual(messages.MESSAGES[code].severity, severity)

    def test_both_languages_with_the_same_placeholders(self) -> None:
        """Principio 10: cada código tiene su texto en los dos idiomas: el ``msgid`` en inglés
        (sin letras del español) y el español, distinto y no vacío, con los mismos marcadores con
        nombre en inglés; ``CATALOG_ES`` (``msgid`` → español) es lo que ``core.i18n.install``
        recibe y da el mismo texto que ``render``."""
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
        singular = [m for m in messages.CATALOG if m.count]
        self.assertGreaterEqual(len(singular), 3)
        for message in singular:
            with self.subTest(code=message.code, singular=True):
                self.assertNotEqual(message.one_msgid, message.msgid)
                self.assertNotEqual(message.one_es, message.es)
                self.assertNotEqual(message.one_msgid, message.one_es)
                self.assertEqual(set(message.one_msgid) & SPANISH_LETTERS, set(),
                                 "msgid en inglés")
                self.assertIn(message.count, i18n.placeholders(message.es))
                for text in (message.one_msgid, message.one_es):
                    self.assertEqual(i18n.placeholders(text), i18n.placeholders(message.es))
                self.assertEqual(messages.CATALOG_ES[message.one_msgid], message.one_es)
        self.assertEqual(set(messages.CATALOG_ES),
                         {m.msgid for m in messages.CATALOG}
                         | {m.one_msgid for m in messages.CATALOG if m.one_msgid})
        self.assertEqual({m.code for m in messages.CATALOG if m.one_msgid or m.one_es},
                         {m.code for m in singular})

    def test_a_count_of_one_takes_its_singular(self) -> None:
        """RF-014-17, RF-014-18, RF-014-08 (spec 014, T51; F-12 (b)): un mensaje que cuenta algo
        lleva su singular, en los dos idiomas: con 1 en su marcador (también 1,0, como vuelve de un
        JSON), «en 1 zona» / «in 1 zone»; con otro número, sin él o con un valor que no es un
        número (un booleano tampoco), el plural de siempre. También los demás recuentos de la 014
        (T60; RF-014-03, RF-014-04, RF-014-05, RF-014-21, RF-014-24, RF-014-27): los grupos de
        semillas, los tramos y las parejas del salto creado, lo que cuenta la vista previa, los
        solapes de fondos y de láminas y las celdas de la regla de orden del ajuste."""
        for code, count, one_es, one_en, many_es, many_en in (
                ("des.quarry_unsplit_zones", "zones", "en 1 zona:", "in 1 zone:", "en 2 zonas:",
                 "in 2 zones:"),
                ("des.quarry_unsplit_remaining", "zones", "en 1 zona dentro",
                 "in 1 zone within", "en 2 zonas dentro", "in 2 zones within"),
                ("des.quarry_to_final", "zones", "en 1 zona (", "in 1 zone (", "en 2 zonas (",
                 "in 2 zones ("),
                ("des.conserve_moved", "parts", "en 1 parte:", "in 1 part:", "en 2 partes:",
                 "in 2 parts:"),
                # Los demás recuentos de la 014 (T60): los grupos de semillas, los tramos del
                # salto creado, la vista previa y los solapes.
                ("des.quarry_seeds_outside", "groups", "en 1 grupo caen", "in 1 group fall",
                 "en 2 grupos caen", "in 2 groups fall"),
                ("des.quarry_seed_group", "cells", ": 1 celda,", ": 1 cell,", ": 2 celdas,",
                 ": 2 cells,"),
                ("des.edge_created_step", "stretches", "en 1 tramo.", "in 1 stretch.",
                 "en 2 tramos.", "in 2 stretches."),
                ("des.edge_surface_step", "stretches", "en 1 tramo.", "in 1 stretch.",
                 "en 2 tramos.", "in 2 stretches."),
                ("des.edge_stretch", "pairs", ": 1 pareja,", ": 1 pair,", ": 2 parejas,",
                 ": 2 pairs,"),
                ("des.quarry_preview_area", "cells", ": 1 celda (", ": 1 cell (", ": 2 celdas (",
                 ": 2 cells ("),
                ("des.quarry_preview_crown", "ring", "anillo de 1 celda fuera",
                 "ring of 1 cell outside", "anillo de 2 celdas fuera", "ring of 2 cells outside"),
                ("des.quarry_preview_hold", "cells", ": 1 celda (", ": 1 cell (", ": 2 celdas (",
                 ": 2 cells ("),
                ("des.quarry_preview_floors", "polygons", ": 1 polígono,", ": 1 polygon,",
                 ": 2 polígonos,", ": 2 polygons,"),
                ("des.quarry_preview_ceilings", "cells", ": 1 celda (", ": 1 cell (",
                 ": 2 celdas (", ": 2 cells ("),
                ("des.quarry_preview_corridors", "corridors", ": 1 línea,", ": 1 line,",
                 ": 2 líneas,", ": 2 lines,"),
                ("des.floor_overlap", "cells", "en 1 celda;", "in 1 cell;", "en 2 celdas;",
                 "in 2 cells;"),
                ("des.fill_only_water_overlap", "cells", "en 1 celda;", "in 1 cell;",
                 "en 2 celdas;", "in 2 cells;"),
                ("des.fill_only_water_outside", "cells", ": 1 celda (", ": 1 cell (",
                 ": 2 celdas (", ": 2 cells ("),
                ("des.refit_order", "cells", "en 1 celda para", "in 1 cell so",
                 "en 2 celdas para", "in 2 cells so"),
                ("des.refit_order_side", "cells", "en 1 celda, hasta", "in 1 cell, up to",
                 "en 2 celdas, hasta", "in 2 cells, up to")):
            message = messages.MESSAGES[code]
            self.assertEqual(message.count, count)
            for value in (1, 1.0):
                with self.subTest(code=code, value=value):
                    self.assertIn(one_es, messages.render(code, **{count: value}))
                    self.assertIn(one_en, messages.render(code, language="en", **{count: value}))
                    self.assertEqual(message.templates(value), (message.one_msgid,
                                                                message.one_es))
            for value in (2, 0, True, None, "1"):
                with self.subTest(code=code, value=value):
                    self.assertEqual(message.templates(value), (message.msgid, message.es))
            self.assertIn(many_es, messages.render(code, **{count: 2}))
            self.assertIn(many_en, messages.render(code, language="en", **{count: 2}))
        plain = messages.MESSAGES["des.profile_value_range"]
        self.assertEqual((plain.count, plain.one_msgid, plain.one_es), ("", "", ""))
        self.assertEqual(plain.templates(1), (plain.msgid, plain.es))

    def test_the_number_chooses_the_singular_of_written_values(self) -> None:
        """RF-014-17, RF-014-18 (T60; el punto 1 de la T57): con los valores ya escritos para una
        persona («1» como texto), ``render`` elige el singular con ``number``, el número sin
        escribir (lo que hace ``preview.Notice.text``); sin él, con el texto «1», el plural. Un
        mensaje con un marcador ``number`` o ``language`` (los argumentos de ``render``) es un
        catálogo mal declarado."""
        code = "des.quarry_to_final"
        self.assertIn("en 1 zonas (", messages.render(code, zones="1"))
        self.assertIn("en 1 zona (", messages.render(code, number=1, zones="1"))
        self.assertIn("in 1 zone (", messages.render(code, language="en", number=1, zones="1"))
        self.assertIn("en 2 zonas (", messages.render(code, number=2, zones="2"))
        self.assertIn("en 1 zona (", messages.render(code, zones=1))
        for mark in ("number", "language"):
            bad = messages.Message("des.t60_bad", f"In {{{mark}}} cells.", f"En {{{mark}}} celdas.",
                                   "note")
            catalog = (*messages.CATALOG, bad)
            with self.subTest(mark=mark), mock.patch.multiple(
                    messages, CATALOG=catalog, MESSAGES={m.code: m for m in catalog},
                    CATALOG_ES={**messages.CATALOG_ES, bad.msgid: bad.es}):
                with self.assertRaises(ValueError):
                    messages._check_catalog()
        messages._check_catalog()

    def test_every_message_names_the_object_and_the_value(self) -> None:
        """RF-013-16, principio 10: cada error de los perfiles nombra el perfil (o el sector)
        y el campo, y el de rango y el de falta de valor dicen qué hacer (dónde se declara)."""
        for code in ("des.profile_name_missing", "des.profile_name_repeated",
                     "des.profile_value_missing", "des.profile_value_range"):
            with self.subTest(code=code):
                self.assertIn("{profile}", messages.MESSAGES[code].es)
                self.assertIn("{profile}", messages.MESSAGES[code].msgid)
        self.assertIn("{sector}", messages.MESSAGES["des.sector_slope_range"].es)
        self.assertIn("{field}", messages.MESSAGES["des.profile_value_range"].es)
        self.assertIn("Diseño ▸ Parámetros ▸ Perfiles de banco…",
                      messages.MESSAGES["des.profile_value_missing"].es)
        self.assertIn("Design ▸ Parameters ▸ Bench profiles…",
                      messages.MESSAGES["des.profile_value_missing"].msgid)

    def test_render_formats_values(self) -> None:
        """Principio 10: un marcador sin valor se ve «?» (nunca ``{…}``); los decimales salen
        con coma en español y con punto en inglés; los valores que sobran se ignoran; un código
        que no es de ``des`` o un idioma desconocido son errores del programa."""
        text = messages.render("des.profile_value_range", profile="EXPL_10_60_6",
                               field="des.bench.expl_10_60_6.face_deg", value=90.5,
                               range="(0; 90) °")
        self.assertEqual(text, "Perfil de banco «EXPL_10_60_6»: «des.bench.expl_10_60_6.face_deg» "
                               "= 90,5 está fuera de su rango (0; 90) °; no se calcula nada con "
                               "este perfil.")
        english = messages.render("des.profile_value_range", language="en", profile="X",
                                  field="f", value=90.5, range="(0, 90) deg", sobra=1)
        self.assertEqual(english, "Bench profile «X»: «f» = 90.5 is outside its range "
                                  "(0, 90) deg; nothing is calculated with this profile.")
        missing = messages.render("des.profile_value_range", profile="X")
        self.assertNotIn("{", missing)
        self.assertIn("?", missing)
        with self.assertRaises(ValueError):
            messages.render("res.same_surface")
        with self.assertRaises(ValueError):
            messages.render("des.profile_unresolved", language="fr")


class DesignErrorTest(unittest.TestCase):
    def test_error_with_object_field_and_value(self) -> None:
        """Principio 10 (RF-013-19): ``DesignError`` es un ``GeoblenderError`` con el código, el
        ``msgid``, los valores en JSON (para el registro y para verlo en inglés), el objeto, el
        campo y el valor, y su texto en español, que es también ``str(error)``."""
        error = messages.DesignError(
            "des.profile_value_range", obj="Perfil de banco «EXPL_10_60_6»",
            field="des.bench.expl_10_60_6.height_m", value=0.0, profile="EXPL_10_60_6",
            range="(0; 100] m")
        self.assertIsInstance(error, errors.GeoblenderError)
        self.assertEqual(error.code, "des.profile_value_range")
        self.assertEqual(error.msgid, messages.MESSAGES["des.profile_value_range"].msgid)
        self.assertEqual((error.obj, error.field, error.value),
                         ("Perfil de banco «EXPL_10_60_6»",
                          "des.bench.expl_10_60_6.height_m", 0.0))
        self.assertEqual(error.values, {"field": "des.bench.expl_10_60_6.height_m", "value": 0.0,
                                        "profile": "EXPL_10_60_6", "range": "(0; 100] m"})
        self.assertEqual(error.text, "Perfil de banco «EXPL_10_60_6»: "
                                     "«des.bench.expl_10_60_6.height_m» = 0 está fuera de su "
                                     "rango (0; 100] m; no se calcula nada con este perfil.")
        self.assertEqual(str(error), error.text)
        self.assertEqual(error.message, error.text)
        self.assertEqual(error.context, error.values)
        english = messages.render(error.code, language="en", **error.values)
        self.assertEqual(english, "Bench profile «EXPL_10_60_6»: "
                                  "«des.bench.expl_10_60_6.height_m» = 0 is outside its range "
                                  "(0; 100] m; nothing is calculated with this profile.")

    def test_an_error_with_its_notes(self) -> None:
        """RF-014-08 (T47): un error puede llevar detrás sus notas (``notes``: código de una nota
        del catálogo y sus valores en JSON), cada una con su texto: en español en ``text`` (y
        ``str(error)``) y en cualquier idioma con ``text_in``, las cifras en el formato del
        idioma, y con una sola parte, en singular (T51); sin notas, ``text_in`` es el texto del
        código de siempre. Una nota que no es una nota (un aviso, un error, un código
        desconocido) es un error del programa."""
        one = messages.DesignError(
            "des.conserve_moved", obj="Cantera «A»", field="volumen", value=2.0, volume=2.0,
            parts=1, notes=(("des.conserve_part", {"zone": "Pie", "volume": 2.0, "x": 1.0,
                                                   "y": 2.0}),))
        self.assertEqual(one.text, "El diseño mueve 2 m³ dentro de las zonas a conservar, en 1 "
                                   "parte: es un error del diseño; no se crea. «Pie»: 2 m³, centro "
                                   "en x = 1 m, y = 2 m.")
        self.assertIn("in 1 part: it is an error", one.text_in("en"))
        error = messages.DesignError(
            "des.conserve_moved", obj="Cantera «A»", field="volumen", value=50.5, volume=50.5,
            parts=2, notes=(("des.conserve_part", {"zone": "Ladera", "volume": 48.25,
                                                   "x": 500_001.5, "y": 4_400_002.0}),
                            ("des.conserve_part", {"zone": "Pie", "volume": 2.25, "x": 500_010.0,
                                                   "y": 4_400_020.5})))
        self.assertEqual(error.notes, (
            ("des.conserve_part", {"zone": "Ladera", "volume": 48.25, "x": 500_001.5,
                                   "y": 4_400_002.0}),
            ("des.conserve_part", {"zone": "Pie", "volume": 2.25, "x": 500_010.0,
                                   "y": 4_400_020.5})))
        self.assertEqual(error.text, (
            "El diseño mueve 50,5 m³ dentro de las zonas a conservar, en 2 partes: es un error del "
            "diseño; no se crea. «Ladera»: 48,25 m³, centro en x = 500001,5 m, y = 4400002 m. "
            "«Pie»: 2,25 m³, centro en x = 500010 m, y = 4400020,5 m."))
        self.assertEqual((str(error), error.text_in("es")), (error.text, error.text))
        self.assertEqual(error.text_in("en"), (
            "The design moves 50.5 m³ inside the zones to conserve, in 2 parts: it is an error of "
            "the design; it is not created. «Ladera»: 48.25 m³, centre at x = 500001.5 m, "
            "y = 4400002 m. «Pie»: 2.25 m³, centre at x = 500010 m, y = 4400020.5 m."))
        plain = messages.DesignError("des.profile_name_missing", obj="Perfil", field="nombre",
                                     profile="P")
        self.assertEqual(plain.notes, ())
        self.assertEqual(plain.text_in("en"),
                         messages.render(plain.code, language="en", **plain.values))
        for note in ("des.conserve_moved", "des.profile_name_missing", "des.no_such_code"):
            with self.subTest(nota=note), self.assertRaises(ValueError):
                messages.DesignError("des.profile_name_missing", obj="Perfil", field="nombre",
                                     notes=((note, {}),))

    def test_only_errors_are_raised(self) -> None:
        """Un aviso no se lanza y un código desconocido es un error del programa
        (``ValueError``); los errores del catálogo se lanzan con su texto sin marcadores."""
        for code in ("des.profile_unresolved", "des.no_such_code", "res.same_surface"):
            with self.subTest(code=code):
                with self.assertRaises(ValueError):
                    messages.DesignError(code, obj="Perfil", field="campo")
        for code, severity in CODES.items():
            if severity == "error":
                with self.subTest(code=code):
                    error = messages.DesignError(code, obj="Perfil", field="campo", value="v",
                                                 profile="P", other="Q", sector="S",
                                                 range="(0; 1]")
                    self.assertNotIn("{", error.text)
                    self.assertNotIn("?", error.text)


if __name__ == "__main__":
    unittest.main()
