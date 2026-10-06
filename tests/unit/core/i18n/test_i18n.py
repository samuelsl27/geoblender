# SPDX-License-Identifier: GPL-3.0-or-later
"""Idioma de la interfaz (spec 002, T28; RF-002-34; plan 003 §5.3; iconos-e-idioma §2).

- Español por defecto, inglés disponible; cada texto con ``msgid`` en inglés y su
  traducción al español en ``messages.toml`` (constitución, principio 10), con los mismos
  marcadores.
- Números y coordenadas: en español, coma decimal y espacio fino de miles; en inglés,
  punto decimal (y las coordenadas sin separador de miles).
- ``core/i18n`` es un paquete, nunca un módulo ``core/i18n.py`` (PLT-03).
"""

import unittest
from pathlib import Path

from tests.support.package import import_geoblender

i18n = import_geoblender("core.i18n")
errors = import_geoblender("core.errors")

THIN = " "


class I18nTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(i18n.set_language, "es")


class TranslateTest(I18nTestCase):
    def test_spanish_by_default_and_english(self) -> None:
        """RF-002-34 (ADR-0012): en español por defecto; en inglés, el ``msgid``; los
        marcadores se rellenan en los dos."""
        self.assertEqual(i18n.language(), "es")
        self.assertEqual(i18n.tr("Project"), "Proyecto")
        self.assertEqual(i18n.tr("Name: {name}", name="Cantera"), "Nombre: Cantera")
        i18n.set_language("en")
        self.assertEqual(i18n.tr("Project"), "Project")
        self.assertEqual(i18n.tr("Name: {name}", name="Cantera"), "Name: Cantera")

    def test_unknown_msgid_is_reported(self) -> None:
        """Principio 10: un ``msgid`` sin traducción sale en inglés y queda en
        ``missing_translations``; con ``install`` se traduce."""
        msgid = "A text of a test without translation"
        self.assertEqual(i18n.tr(msgid), msgid)
        self.assertIn(msgid, i18n.missing_translations())
        i18n.install({msgid: {"es": "Un texto de prueba"}})
        self.assertEqual(i18n.tr(msgid), "Un texto de prueba")
        self.assertNotIn(msgid, i18n.missing_translations())

    def test_install_forms(self) -> None:
        """Plan 003 §5.3: ``install`` acepta ``{msgid: texto}``, pares y un objeto con
        ``translations()`` (el catálogo de comandos de la 003)."""

        class Catalog:
            def translations(self) -> dict[str, str]:
                return {"Install test 3": "Prueba 3"}

        i18n.install({"Install test 1": "Prueba 1"})
        i18n.install([("Install test 2", "Prueba 2")])
        i18n.install(Catalog())
        self.assertEqual(
            [i18n.tr(f"Install test {n}") for n in (1, 2, 3)],
            ["Prueba 1", "Prueba 2", "Prueba 3"],
        )

    def test_invalid_language(self) -> None:
        """ADR-0012: solo español e inglés."""
        with self.assertRaises(errors.ValidationError):
            i18n.set_language("fr")
        self.assertEqual(i18n.language(), "es")


class MessagesTest(I18nTestCase):
    def test_every_message_translated_with_same_placeholders(self) -> None:
        """Principio 10, RF-002-34: cada ``msgid`` de ``messages.toml`` tiene traducción
        al español, no vacía, con los mismos marcadores; el ``msgid`` está en inglés (sin
        letras del español)."""
        table = i18n.load_messages()
        self.assertGreater(len(table), 20)
        for msgid, spanish in table.items():
            with self.subTest(msgid=msgid):
                self.assertTrue(spanish.strip())
                self.assertEqual(i18n.placeholders(spanish), i18n.placeholders(msgid))
                self.assertFalse(set(msgid) & set("áéíóúñÁÉÍÓÚÑ¿¡"), "msgid en inglés")
        self.assertEqual([m for m in i18n.missing_translations() if m in table], [])

    def test_package_not_module(self) -> None:
        """PLT-03: ``core/i18n`` es un paquete con ``messages.toml`` y no hay un
        ``core/i18n.py`` que quedaría oculto."""
        package = Path(i18n.__file__)
        self.assertEqual(package.name, "__init__.py")
        self.assertTrue((package.parent / "messages.toml").is_file())
        self.assertFalse((package.parent.parent / "i18n.py").exists())


class InterfaceTextsTest(I18nTestCase):
    """Spec 003, T03: los textos de la interfaz que no son comandos (II §2.3)."""

    def test_command_states(self) -> None:
        """RF-003-07, RF-003-09 (BS §7.3): los estados de un comando, en español por
        defecto y en inglés con el ``msgid``."""
        self.assertEqual(i18n.tr("Available in {entry}", entry="R-38"), "Disponible en R-38")
        self.assertEqual(
            i18n.tr("First {step} ({path})", step="defina la ventana de trabajo",
                    path="Proyecto ▸ Georreferencia"),
            "Primero defina la ventana de trabajo (Proyecto ▸ Georreferencia)",
        )
        self.assertEqual(i18n.tr("Its place: {path}", path="Cubicación ▸ Cubicar"),
                         "Su sitio: Cubicación ▸ Cubicar")
        self.assertEqual(i18n.tr("Step {n} of {total} · {stage}", n=9, total=11,
                                 stage="Cubicación"), "Paso 9 de 11 · Cubicación")
        i18n.set_language("en")
        self.assertEqual(i18n.tr("Available in {entry}", entry="R-38"), "Available in R-38")
        self.assertEqual(i18n.translate("es", "Available in {entry}", entry="R-38"),
                         "Disponible en R-38")
        self.assertEqual(i18n.language(), "en", "translate no cambia el idioma activo")

    def test_status_bar_and_notices(self) -> None:
        """RF-003-20, RF-003-28 (II §2.3, AR §6, spec §8): barra de estado, avisos y
        estados de la versión y de las cifras, en español."""
        expected = {
            "Mouse:": "Ratón:",
            "Snap: {mode}": "Encaje: {mode}",
            "Slope {value} %": "Pend. {value} %",
            "{n} jobs": "{n} trabajos",
            "No project": "Sin proyecto",
            "Geoblender interface in compatibility mode":
                "Interfaz de Geoblender en modo de compatibilidad",
            "The Geoblender workspace has been added to this file":
                "Se ha añadido el espacio de trabajo Geoblender a este fichero",
            "CURRENT": "VIGENTE",
            "ASSUMPTION": "HIPÓTESIS",
            "ASM": "HIP",
        }
        self.assertEqual({msgid: i18n.tr(msgid) for msgid in expected}, expected)

    def test_coverage_detects_missing_translation(self) -> None:
        """RNF-003-08 (principio 10): la prueba de cobertura falla con un ``msgid`` sin
        traducción al español y pasa con los que la tienen (también los instalados)."""
        msgid = "A msgid of the coverage test"
        self.assertEqual(i18n.untranslated(["Project", msgid, "Available in {entry}"]), [msgid])
        i18n.install({msgid: "Un msgid de la prueba de cobertura"})
        self.assertEqual(i18n.untranslated(["Project", msgid]), [])

    def test_catalog_fully_translated(self) -> None:
        """RNF-003-08: el 100 % de los textos de ``messages.toml`` y del catálogo de
        comandos tiene español e inglés; el catálogo no contradice ``messages.toml``."""
        catalog = import_geoblender("core.catalog")
        cat = catalog.load()
        messages = i18n.load_messages()
        i18n.install(cat)
        self.assertEqual(i18n.untranslated([*messages, *cat.msgids()]), [])
        conflicts = [issue for issue in catalog.validate(cat, messages=messages)
                     if "messages.toml" in issue.message]
        self.assertEqual(conflicts, [])


class FormatTest(I18nTestCase):
    def test_format_number(self) -> None:
        """Iconos-e-idioma §2.4: en español, coma decimal y espacio fino de miles; en
        inglés, punto y comas; sin «-0»."""
        self.assertEqual(i18n.format_number(1_234_567.891, 2), f"1{THIN}234{THIN}567,89")
        self.assertEqual(i18n.format_number(-180, 0), "-180")
        self.assertEqual(i18n.format_number(700_000, 0), f"700{THIN}000")
        self.assertEqual(i18n.format_number(-0.001, 2), "0,00")
        i18n.set_language("en")
        self.assertEqual(i18n.format_number(1_234_567.891, 2), "1,234,567.89")

    def test_format_xyz(self) -> None:
        """RF-002-34 (iconos-e-idioma §2.4): coordenadas absolutas con espacio fino de
        miles y coma decimal en español, sin separador de miles en inglés."""
        self.assertEqual(
            i18n.format_xyz(736_512.344, 4_435_871.019, 180.0),
            f"X 736{THIN}512,34  Y 4{THIN}435{THIN}871,02  Z 180,00",
        )
        self.assertEqual(
            i18n.format_xyz(700_000, 4_400_000, 0, decimals=0),
            f"X 700{THIN}000  Y 4{THIN}400{THIN}000  Z 0",
        )
        i18n.set_language("en")
        self.assertEqual(
            i18n.format_xyz(736_512.344, 4_435_871.019, 180.0),
            "X 736512.34  Y 4435871.02  Z 180.00",
        )

    def test_format_xyz_status_bar_example(self) -> None:
        """RF-003-28 (spec 003, T03 y T27): GeoOrigin (736 500, 4 435 900, 0) más el
        cursor local (12,34; −28,98; 212,4), sumados en float64, en los dos idiomas."""
        x, y, z = 736_500 + 12.34, 4_435_900 - 28.98, 0 + 212.4
        self.assertEqual(i18n.format_xyz(x, y, z),
                         f"X 736{THIN}512,34  Y 4{THIN}435{THIN}871,02  Z 212,40")
        i18n.set_language("en")
        self.assertEqual(i18n.format_xyz(x, y, z), "X 736512.34  Y 4435871.02  Z 212.40")


if __name__ == "__main__":
    unittest.main()
