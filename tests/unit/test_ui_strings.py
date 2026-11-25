# SPDX-License-Identifier: GPL-3.0-or-later
"""Ninguna clave interna a la vista (spec 019, T24; RF-019-16; UI-08; plan 019 A6, P-3).

Se recorren los textos que la interfaz puede dibujar (el catálogo de idioma y el de comandos, en español y en inglés) y
se comprueban con :mod:`tests.support.ui_strings`: ni códigos de mensaje, ni códigos de entidad, ni nombres estables,
ni marcadores sin rellenar, ni rutas de módulo. Control positivo: cada patrón ve una cadena sembrada, incluidas las
armadas en ejecución con el *layout* falso. Lo existente que no cumple está en ``tests/data/ui_baseline.toml``
(``[strings]``): la prueba falla ante un incumplimiento nuevo y ante uno de la lista que ya se corrigió.
"""

import re
import unittest

from tests.support import ui_strings as us
from tests.support.package import import_geoblender

catalog = import_geoblender("core.catalog")
i18n = import_geoblender("core.i18n")

PLACEHOLDER = re.compile(r"\{[^{}]*\}")


def displayed_texts() -> dict[str, str]:
    """(texto, idioma) → clave de la lista base: ``es:texto`` / ``en:msgid`` de cada cadena del catálogo."""
    spanish = dict(i18n.load_messages())
    spanish.update(catalog.load().translations())
    found: dict[str, str] = {}
    for msgid, text in spanish.items():
        found[f"es:{text}"] = PLACEHOLDER.sub("", text)
        found[f"en:{msgid}"] = PLACEHOLDER.sub("", msgid)
    return found


def current_findings() -> list[str]:
    """Las entradas ``idioma:texto -> regla`` que hoy incumplen, ordenadas."""
    return sorted({f"{key} -> {rule}"
                   for key, shown in displayed_texts().items()
                   for rule in us.violations(shown)})


class UiStringsTest(unittest.TestCase):
    def test_no_new_internal_key_and_baseline_only_goes_down(self) -> None:
        """RF-019-16: lo que incumple es exactamente la lista base: un incumplimiento nuevo falla y uno de la lista ya
        corregido y no quitado, también."""
        found = set(current_findings())
        baseline = set(us.load_baseline("strings"))
        self.assertEqual(sorted(found - baseline), [], "incumplimiento nuevo: corríjalo (UI-08)")
        self.assertEqual(sorted(baseline - found), [], "ya cumple: quítelo de [strings] de la lista base")

    def test_scans_the_real_catalog(self) -> None:
        self.assertGreater(len(displayed_texts()), 2000)

    def test_detector_sees_seeded_keys(self) -> None:
        """Control positivo: un código de mensaje, uno de entidad, un nombre estable, un marcador sin rellenar, una
        ruta de módulo y el ``msgid`` sin traducir se detectan; un texto normal, no."""
        table = {"Project": "Proyecto"}
        seeded = {
            "No se pudo (des.pit.pit_000.hoja)": "message-code",
            "Corta PIT-001 sin accesos": "entity-code",
            "Falta bench_height": "stable-name",
            "Nombre: {name}": "placeholder",
            "Ver geoblender.core.errors": "module-path",
            "Project": us.UNTRANSLATED,
        }
        for text, rule in seeded.items():
            self.assertIn(rule, us.violations(text, table), text)
        for fine in ("Proyecto", "Banco de 15,0 m", "Corta Norte 2", "p. ej. la cresta", "modelo.gpkg"):
            self.assertEqual(us.violations(fine, table), [], fine)
        self.assertEqual(us.violations("Project", table, language="en"), [])

    def test_runtime_strings_are_collected_with_the_fake_layout(self) -> None:
        """Control positivo de las cadenas armadas en ejecución: el recolector recoge cada ``label``, ``text=`` y
        ``report`` y la regla los señala."""
        def draw(layout: us.StringCollector) -> None:
            code = "PIT-001"
            layout.label(text=f"Corta {code}")
            layout.operator("geoblender.x", text="Calcular")
            layout.report({"ERROR"}, "falló des.pit.hoja")
            layout.label(text="Todo bien")

        texts = us.collect(draw)
        self.assertEqual(texts, ["Corta PIT-001", "Calcular", "Todo bien", "falló des.pit.hoja"])
        self.assertEqual(us.findings(texts), [("Corta PIT-001", "entity-code"),
                                               ("falló des.pit.hoja", "message-code")])

    def test_baseline_file_is_well_formed(self) -> None:
        entries = us.load_baseline("strings")
        self.assertEqual(entries, sorted(set(entries)))


if __name__ == "__main__":
    unittest.main()
