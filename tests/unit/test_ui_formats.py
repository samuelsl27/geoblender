# SPDX-License-Identifier: GPL-3.0-or-later
"""Cada magnitud con su formato único (spec 019, T25; RF-019-17; UI-07; plan 019 A6, P-3).

Se recorren los textos del catálogo de idioma y del de comandos (es y en) y el código de ``bl/``: la marca decimal del
idioma, la unidad con su espacio, los decimales fijos y ningún número formateado a mano. Control positivo con cadenas
sembradas y con lo que escribe ``core.magnitudes``. Lo existente que no cumple está en ``tests/data/ui_baseline.toml``
(``[formats]``): la prueba falla ante un incumplimiento nuevo y ante uno de la lista ya corregido.
"""

import unittest

from tests.support import ui_formats as uf
from tests.support import ui_strings as us
from tests.support.package import import_geoblender

catalog = import_geoblender("core.catalog")
i18n = import_geoblender("core.i18n")
magnitudes = import_geoblender("core.magnitudes")


def catalog_findings() -> list[str]:
    spanish = dict(i18n.load_messages())
    spanish.update(catalog.load().translations())
    found = set()
    for msgid, text in spanish.items():
        for language, shown in (("es", text), ("en", msgid)):
            for rule in uf.violations(shown, language):
                found.add(f"{language}:{shown} -> {rule}")
    return sorted(found)


def current_findings() -> list[str]:
    return sorted({*catalog_findings(), *uf.presentation_findings()})


class UiFormatsTest(unittest.TestCase):
    def test_no_new_format_failure_and_baseline_only_goes_down(self) -> None:
        found = set(current_findings())
        baseline = set(us.load_baseline("formats"))
        self.assertEqual(sorted(found - baseline), [], "incumplimiento nuevo: use core.magnitudes (UI-07)")
        self.assertEqual(sorted(baseline - found), [], "ya cumple: quítelo de [formats] de la lista base")

    def test_detector_sees_seeded_failures(self) -> None:
        """Control positivo: un decimal con punto en español, con coma en inglés, una unidad pegada y unos decimales
        que no son los de la magnitud se detectan."""
        self.assertIn("decimal-mark", uf.violations("Banco de 1.5 m", "es"))
        self.assertIn("decimal-mark", uf.violations("Bench of 1,5 m", "en"))
        self.assertIn("unit-glued", uf.violations("Banco de 15m", "es"))
        self.assertIn("fixed-decimals", uf.violations("Banco de 1,5 m", "es"))
        self.assertIn("fixed-decimals", uf.violations("Bench of 1.5 m", "en"))
        self.assertIn("fixed-decimals", uf.violations("Pendiente de 33,33 %", "es"))

    def test_what_magnitudes_writes_complies(self) -> None:
        for name in magnitudes.MAGNITUDES:
            for language in ("es", "en"):
                for value in (0.0, 1.5, 1234.5678, -987654.321):
                    text = f"Valor {magnitudes.format(name, value, language=language)}"
                    with self.subTest(name=name, language=language, value=value):
                        self.assertEqual(uf.violations(text, language), [], text)
        self.assertEqual(uf.violations(f"Posición: {magnitudes.format_position(1.0, 4400000.456, 2.0, language='es')}",
                                       "es"), [])

    def test_runtime_strings_are_collected_with_the_fake_layout(self) -> None:
        def draw(layout: us.StringCollector) -> None:
            layout.label(text="Altura 1.5 m")
            layout.label(text="Superficie 12,50 m²")

        self.assertEqual(uf.findings(us.collect(draw)), [("Altura 1.5 m", "decimal-mark")])

    def test_hand_formatted_numbers_in_source_are_seen(self) -> None:
        source = ("a = f'{x:.2f} m'\nb = f'{y:,.1f}'\nc = f'{z}'\nd = '{:.3f}'.format(w)\n"
                  "e = format_number(v, 2)\n")
        self.assertEqual(uf.source_findings(source, "bl/x.py"),
                         ["bl/x.py: {:.3f}","bl/x.py: {x:.2f}", "bl/x.py: {y:,.1f}"])

    def test_baseline_file_is_well_formed(self) -> None:
        entries = us.load_baseline("formats")
        self.assertEqual(entries, sorted(set(entries)))


if __name__ == "__main__":
    unittest.main()
