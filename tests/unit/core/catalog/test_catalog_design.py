# SPDX-License-Identifier: GPL-3.0-or-later
"""El diseño (spec 013, T26; HU-013-1 a HU-013-6; RF-013-33; plan 013 §5.6, D-31) en el catálogo
de comandos.

- La entrada ``013`` tiene su título en inglés y en español y entrega sus comandos; ``R-33``
  sigue existiendo como entrada del roadmap (otras specs la nombran) pero ya no la usa ningún
  comando ni ningún menú contextual.
- Las cuatro órdenes de Diseño (Perfiles de banco…, Sectores de diseño…, Vista previa de
  semillas, dominios y restricciones y Envolventes y escalonado…) y las internas de las
  ventanas (guardar un perfil, fijar el talud de un sector y, desde la T28, exportar una rejilla
  a GeoTIFF y, desde la T44, declarar de nuevo los sectores) son de la ``013`` y de ``des``;
  las cuatro tienen su casa en Diseño y las internas, ninguna; la de las envolventes sigue
  siendo un trabajo en segundo plano (``D·2p``) y la vista previa, un interruptor (``T``).
- El menú contextual de Diseño (``DESIGN``, PC §3.10) es de la ``013``, con los comandos que ya
  tenía; lo de R-35 y R-44 que lleva sigue en su entrada.
- La spec 014 (cantera con dos superficies; T05, plan 014 §5.6): la entrada ``014`` tiene su
  título en los dos idiomas y **aún no entrega** sus comandos; las cinco órdenes de ``R-34``
  (Límite desde el perímetro…, Cantera con dos superficies…, Ajustar el diseño a un límite
  nuevo…, Solo relleno… y Transiciones con el terreno no afectado) pasan a ella con su casa, su
  acción, su segundo plano y su frecuencia; ``R-34`` sigue como entrada del roadmap, sin
  comandos.
"""

import tomllib
import unittest

from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR

catalog = import_geoblender("core.catalog")

DATA = EXTENSION_DIR / "core" / "catalog" / "data"
TITLE = ("Envelopes and benching", "Envolventes y escalonado")
MENU = {  # orden → (acción, en segundo plano)
    "geoblender.des_edit_bench_profiles": ("P", False),
    "geoblender.des_edit_design_sectors": ("P", False),
    "geoblender.des_toggle_preview": ("T", False),
    "geoblender.des_compute_envelope": ("D", True),
}
INTERNAL = ("geoblender.des_save_bench_profile", "geoblender.des_set_sector_slope",
            "geoblender.des_export_design_grid", "geoblender.des_declare_sectors")
HOME = "GEOBLENDER_MT_ui_design"
TITLE_014 = ("Quarry with two surfaces", "Cantera con dos superficies")
MENU_014 = {  # orden → (casa, acción, en segundo plano, frecuencia)
    "geoblender.des_create_limit_from_perimeter": (HOME, "D", False, 3),
    "geoblender.des_design_quarry": (HOME, "D", True, 3),
    "geoblender.des_refit_to_limit": (HOME, "D", False, 2),
    "geoblender.des_design_fill_only": (HOME, "D", False, 1),
    "geoblender.des_create_transitions": ("GEOBLENDER_MT_ui_reclamation", "A", False, 2),
}


class DesignCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cat = catalog.load()

    def test_entry_013(self) -> None:
        """RF-013-33, D-31: la entrada ``013`` tiene el título de la spec en los dos idiomas y
        entrega sus comandos; ``R-33`` sigue como entrada del roadmap, sin comandos."""
        entry = self.cat.entries["013"]
        self.assertEqual((entry.title, entry.title_es), TITLE)
        self.assertTrue(entry.delivered)
        self.assertEqual(catalog.entry_text(self.cat, "013", "es"), f"013 · {TITLE[1]}")
        self.assertEqual(catalog.entry_text(self.cat, "013", "en"), f"013 · {TITLE[0]}")
        self.assertIn("R-33", self.cat.entries)
        self.assertEqual(sorted(command.key for command in self.cat.commands.values()
                                if command.entry == "R-33"), [])

    def test_the_four_commands_and_the_internals_belong_to_013(self) -> None:
        """RF-013-33, RF-013-34, D-31: las cuatro órdenes de Diseño son de la ``013`` y de ``des``,
        con su casa en Diseño, su acción y su trabajo en segundo plano; las internas de las
        ventanas, también de la ``013`` y sin casa en un menú."""
        for key, (action, background) in MENU.items():
            with self.subTest(key=key):
                command = self.cat.commands[key]
                self.assertEqual((command.entry, command.module, command.kind),
                                 ("013", "des", "operator"))
                self.assertEqual((command.action, command.background), (action, background))
                self.assertEqual(command.home, HOME)
        for key in INTERNAL:
            with self.subTest(key=key):
                command = self.cat.commands[key]
                self.assertEqual((command.entry, command.module, command.kind, command.home),
                                 ("013", "des", "internal", ""))

    def test_the_design_context_menu_is_013(self) -> None:
        """RF-013-33, PC §3.10: el menú «Diseño ▾» (``DESIGN``) es de la ``013`` (su entrada, en
        ``contexts.toml``) y lleva los comandos de las dos órdenes que le corresponden más los
        de R-35 y R-44 y los de otras specs que ya tenía."""
        raw = tomllib.loads((DATA / "contexts.toml").read_text(encoding="utf-8"))
        (context,) = [table for table in raw["context"] if table["kind"] == "DESIGN"]
        self.assertEqual(context["entry"], "013")
        keys = [item["ref"] for item in context["item"] if "ref" in item]
        self.assertEqual(keys[:2], ["geoblender.des_edit_bench_profiles",
                                    "geoblender.des_toggle_preview"])
        self.assertEqual([key for key in keys if key in MENU],
                         ["geoblender.des_edit_bench_profiles", "geoblender.des_toggle_preview"])
        spec = self.cat.contexts["DESIGN"]
        self.assertEqual(spec.id, "GEOBLENDER_MT_des_context_design")
        self.assertEqual(self.cat.commands[spec.id].entry, "013")
        for key in keys:
            self.assertIn(key, self.cat.commands)

    def test_entry_014_is_not_delivered_yet(self) -> None:
        """RF-014-29 (plan 014 §5.1 y §5.6; T05): la entrada ``014`` tiene el título de la spec en
        los dos idiomas y aún no entrega sus comandos (``delivered`` llega al cerrarla); ``R-34``
        sigue como entrada del roadmap, sin comandos."""
        entry = self.cat.entries["014"]
        self.assertEqual((entry.title, entry.title_es), TITLE_014)
        self.assertFalse(entry.delivered)
        self.assertEqual(catalog.entry_text(self.cat, "014", "es"), f"014 · {TITLE_014[1]}")
        self.assertIn("R-34", self.cat.entries)
        self.assertEqual(sorted(command.key for command in self.cat.commands.values()
                                if command.entry == "R-34"), [])

    def test_the_five_commands_of_r34_belong_to_014(self) -> None:
        """RF-014-29 (plan 014 §5.5 y §5.6): las cinco órdenes de R-34 son de la ``014`` y de
        ``des``, en el grupo «Cantera» de Diseño (y la transición, en Restauración ▸ Superficie
        final), con la acción, el segundo plano y la frecuencia que ya tenían."""
        self.assertEqual(sorted(command.key for command in self.cat.commands.values()
                                if command.entry == "014"), sorted(MENU_014))
        for key, (home, action, background, frequency) in MENU_014.items():
            with self.subTest(key=key):
                command = self.cat.commands[key]
                self.assertEqual((command.entry, command.module, command.kind),
                                 ("014", "des", "operator"))
                self.assertEqual((command.home, command.action, command.background,
                                  command.frequency), (home, action, background, frequency))


if __name__ == "__main__":
    unittest.main()
