# SPDX-License-Identifier: GPL-3.0-or-later
"""Carga del catálogo de comandos (spec 003, T02; RF-003-06, RF-003-07; plan 003 §5.2 y
§5.3; BS §7.1).

- Los datos TOML de ``core/catalog/data/`` dan un :class:`Catalog` con los menús, sus
  grupos, sus submenús y una sola definición de cada comando, con su casa, su ruta y sus
  textos en inglés (``msgid``) y en español.
- Un acceso cruzado (``ref``) es el mismo comando que su casa, marcado con ↗; un espejo
  (``mirror``) también, sin la marca.
- La clave de un comando que fija propiedades lleva sus valores
  (``geoblender.ui_set_view?view=PLAN``), en orden de nombre.
- «Disponible en …» sale del título de la entrada en el idioma pedido.
- Un catálogo válido del tamaño del real (unos 400 comandos) se carga en ≤ 50 ms.
"""

import time
import unittest
from pathlib import Path

from tests.support.catalog_fixtures import VALID, big_catalog
from tests.support.package import import_geoblender
from tests.support.trees import temp_tree

catalog = import_geoblender("core.catalog")
loader = import_geoblender("core.catalog.loader")


class LoadTest(unittest.TestCase):
    def load(self, files: dict[str, str]) -> object:
        with temp_tree(files) as root:
            return catalog.load(root)

    def test_valid_catalog(self) -> None:
        """RF-003-06: los menús, sus grupos y submenús y cada comando, una vez, con su
        casa; el catálogo válido no tiene incidencias."""
        cat = self.load(VALID)
        self.assertEqual(catalog.validate(cat), [])
        self.assertEqual(cat.top_menus, ("GEOBLENDER_MT_ui_project", "GEOBLENDER_MT_ui_topography"))
        project = cat.menus["GEOBLENDER_MT_ui_project"]
        self.assertEqual(project.step, 1)
        self.assertEqual([group.label for group in project.groups], ["Project", "Exchange"])
        new = cat.commands["geoblender.core_new_project"]
        self.assertEqual((new.label, new.label_es), ("New project…", "Nuevo proyecto…"))
        self.assertEqual((new.module, new.entry, new.action, new.frequency),
                         ("core", "002", "D", 1))
        self.assertEqual((new.home, new.home_group), ("GEOBLENDER_MT_ui_project", "Project"))
        self.assertEqual(new.kind, "operator")
        network = cat.commands["GEOBLENDER_MT_core_network"]
        self.assertEqual(network.kind, "menu")
        checkout = cat.commands["geoblender.core_checkout_project"]
        self.assertEqual(checkout.home, "GEOBLENDER_MT_core_network")
        self.assertEqual(
            cat.path("geoblender.core_checkout_project"),
            ("Project", "Project", "Local copy and network", "Work on a local copy…"),
        )

    def test_cross_references_and_mirrors(self) -> None:
        """RF-003-06 (BS §6, P3): un acceso cruzado ↗ es una referencia al mismo comando,
        no una copia; el de un submenú definido en otro fichero, también."""
        cat = self.load(VALID)
        topography = cat.menus["GEOBLENDER_MT_ui_topography"]
        refs = [(item.key, item.cross) for group in topography.groups for item in group.items
                if not item.separator]
        self.assertIn(("geoblender.core_new_project", True), refs)
        self.assertIn(("GEOBLENDER_MT_io_import", True), refs)
        data = cat.menus["GEOBLENDER_MT_core_data"]
        self.assertEqual([(item.key, item.cross) for item in data.groups[0].items],
                         [("GEOBLENDER_MT_io_import", False)])
        self.assertEqual(cat.commands["GEOBLENDER_MT_io_import"].home, "GEOBLENDER_MT_ui_project")

    def test_property_keys(self) -> None:
        """Plan 003 §5.2: la clave de un comando con propiedades lleva sus valores, en
        orden de nombre; ``by_idname`` da todas las variantes de un operador."""
        cat = self.load(VALID)
        plan = cat.commands["geoblender.ui_set_view?view=PLAN"]
        self.assertEqual((plan.idname, plan.props), ("geoblender.ui_set_view", (("view", "PLAN"),)))
        step = cat.commands["geoblender.geo_step_section?direction=-1&scope=SET"]
        self.assertEqual(step.props, (("direction", -1), ("scope", "SET")))
        self.assertEqual(
            [command.key for command in cat.by_idname("geoblender.ui_set_view")],
            ["geoblender.ui_set_view?view=PLAN", "geoblender.ui_set_view?view=NORTH"],
        )
        self.assertEqual(loader.split_key("geoblender.x_y?b=True&a=2"),
                         ("geoblender.x_y", (("b", True), ("a", 2))))
        self.assertEqual(loader.make_key("geoblender.x_y", {"b": True, "a": 2}),
                         "geoblender.x_y?a=2&b=True")

    def test_translations_and_unavailable_text(self) -> None:
        """RF-003-07, RF-003-20: el catálogo da sus traducciones al español
        (``msgid`` → texto) y «Disponible en <entrada · título>» en cada idioma."""
        cat = self.load(VALID)
        translations = cat.translations()
        self.assertEqual(translations["New project…"], "Nuevo proyecto…")
        self.assertEqual(translations["Exchange"], "Intercambio")
        command = cat.commands["geoblender.res_compute_volume_between_surfaces"]
        self.assertEqual(catalog.unavailable_text(cat, command, "es"),
                         "Disponible en R-38 · Cubicación entre superficies")
        self.assertEqual(catalog.unavailable_text(cat, command, "en"),
                         "Available in R-38 · Volumetrics between surfaces")

    def test_operator_idnames_and_shortcuts(self) -> None:
        """Plan 003 §5.3: los ``bl_idname`` de los operadores de Geoblender del catálogo
        (sin repetir las variantes) y sus atajos."""
        cat = self.load(VALID)
        self.assertIn("geoblender.ui_set_view", cat.operator_idnames())
        self.assertNotIn("geoblender.ui_set_view?view=PLAN", cat.operator_idnames())
        self.assertNotIn("view3d.view_all", cat.operator_idnames())
        (shortcut,) = cat.shortcuts()
        self.assertEqual((shortcut.key, shortcut.keymap, shortcut.event, shortcut.ctrl),
                         ("geoblender.core_new_project", "3D View", "F5", True))
        self.assertEqual(cat.shortcuts_for("geoblender.core_new_project"), (shortcut,))

    def test_real_catalog_loads(self) -> None:
        """RF-003-06: el catálogo real se carga sin incidencias (las de contenido, frente
        a BS §8, las comprueban ``test_catalog_matches_docs`` y ``test_catalog_content``)."""
        cat = catalog.load()
        self.assertEqual(catalog.validate(cat), [])
        self.assertIs(catalog.load(), cat, "en caché")

    def test_loads_within_budget(self) -> None:
        """T02: un catálogo válido del tamaño del real (400 comandos en 13 menús) se carga
        en ≤ 50 ms (la mejor de tres cargas sin caché, con el Python de Blender)."""
        with temp_tree(big_catalog(400)) as root:
            times = []
            for _ in range(3):
                start = time.perf_counter()
                cat = loader.load_catalog(Path(root))
                times.append(time.perf_counter() - start)
        self.assertEqual(len(cat.commands), 400 + 13)
        self.assertLessEqual(min(times) * 1000, 50.0, f"{min(times) * 1000:.1f} ms")


if __name__ == "__main__":
    unittest.main()
