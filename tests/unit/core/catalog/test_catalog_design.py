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
  título en los dos idiomas y, desde la T58 (antes del H3), **entrega** sus comandos; las cinco
  órdenes de ``R-34`` (Límite desde el perímetro…, Cantera con dos superficies…, Ajustar el
  diseño a un límite nuevo…, Solo relleno… y Transiciones con el terreno no afectado) pasan a
  ella con su casa, su acción, su segundo plano y su frecuencia; ``R-34`` sigue como entrada del
  roadmap, sin comandos.
- La spec 015 (entidades de diseño paramétricas; T31, plan 015 §5.6, RF-015-28, D-14): la entrada ``015`` tiene su título en los
  dos idiomas y **entrega** sus comandos: «Plataforma…» (con su casa en Diseño ▸ Pistas y entidades ▸ Entidades) y las
  internas de las entidades (descartar, soltar el apoyo, traer, vista previa, lo que se apoya en ella e insertar antes o
  después de…), que están en el menú contextual «Entidad ▾» (``DESIGN_ENTITY``, también de la ``015``).
- La spec 016 (acopios, contrafuerte y cuerpos apoyados; T35, plan 016 §5.5, RF-016-25, D-8, D-14): la entrada ``016`` **entrega** sus
  órdenes con el menú: «Acopio (detectar, retirar)…», «Contrafuerte…» y «Cuerpo apoyado…» (Diseño ▸ Pistas y entidades ▸ Entidades) y las
  internas de detectar, los candidatos y retirar; «Cuerpo apoyado…» es la «Unidad por espesor sobre su apoyo…» de R-18
  (``geo_create_thickness_unit``), que se va del menú de Geología. ``R-36`` sigue como entrada del roadmap, sin órdenes: lo que aún no
  es una orden del menú «Entidad ▾» (editar el eje, las restricciones que declara) sigue marcado en ella.
- La spec 017 (pistas y rampas; T33b, plan 017 §5.5 y §5.6, RF-017-29, D-20): la entrada ``017`` tiene su título en los dos idiomas y **entrega** sus
  órdenes con el menú: «Pista…», «Proponer el trazado…», «Accesibilidad de las pistas…», «Perfil de pista…» y «Exportar pista…» son los cinco primeros
  puestos de Diseño ▸ Pistas y entidades, **en ese orden y antes de «Entidades ▸»**, y la ventana del perfil, su interna. **Desaparecen** del catálogo
  ``des_draw_haul_road``, ``des_route_haul_road`` y ``des_burn_roads`` (las tres provisionales de ``R-40``: no queda ninguna referencia a ellas en los
  ficheros del catálogo). ``R-40`` sigue como entrada del roadmap, sin órdenes. El menú «Entidad ▾» no cambia: sirve a la pista con las órdenes de siempre.
- La spec 018 (corta por bancos; T35, plan 018 §5.5, RF-018-34, D-20): la entrada ``018`` tiene su título en los dos idiomas y **entrega** sus órdenes: las seis del
  submenú Diseño ▸ Corta por bancos («Nueva corta…», «Expandir banco…», «Rampa…», «Roseta de taludes…», «Línea de cielo…» y «Superficie y sólido…») y las dos internas de las
  ventanas de la roseta y de la rampa. **Desaparecen** ``des_new_pit``, ``des_add_ramp``, ``des_compute_daylight`` y ``des_create_design_surface`` (las provisionales de ``R-35``: no queda
  ninguna referencia a ellas en los datos del catálogo). ``R-35`` sigue como entrada del roadmap, sin órdenes; ``des_design_pit_from_shell`` y ``des_compare_with_shell`` (R-49) no se tocan.
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
TITLE_015 = ("Parametric design entities", "Entidades de diseño paramétricas")
PLATFORM = "geoblender.des_create_platform"
INTERNAL_015 = (  # orden → (acción, frecuencia)
    "geoblender.des_entity_discard", "geoblender.des_entity_release_support", "geoblender.des_entity_bring",
    "geoblender.des_entity_preview", "geoblender.des_entity_dependents", "geoblender.des_entity_insert",
    "geoblender.des_entity_calculate", "geoblender.des_entity_refresh")
ENTITY_MENU = ("geoblender.des_entity_dependents", "geoblender.des_entity_insert", "geoblender.des_entity_bring",
               "geoblender.des_entity_calculate", "geoblender.des_entity_discard", "geoblender.des_entity_release_support",
               "geoblender.des_entity_preview", "geoblender.des_export_design_grid")
"""Las órdenes reales del menú «Entidad ▾» (T31), en su orden."""
TITLE_017 = ("Haul roads and ramps", "Pistas y rampas")
ROADS_MENU_017 = {  # orden → (rótulo en español, acción, frecuencia), en el orden del grupo «Pistas y entidades»
    "geoblender.des_create_road": ("Pista…", "D", 2),
    "geoblender.des_propose_road": ("Proponer el trazado…", "D", 2),
    "geoblender.des_road_access": ("Accesibilidad de las pistas…", "D", 1),
    "geoblender.des_edit_road_profile": ("Perfil de pista…", "P", 2),
    "geoblender.des_export_road": ("Exportar pista…", "D", 1),
}
INTERNAL_017 = ("geoblender.des_save_road_profile",)
GONE_017 = ("des_draw_haul_road", "des_route_haul_road", "des_burn_roads")
"""Las tres provisionales de R-40 que sustituyen las órdenes de la 017 (D-20)."""
TITLE_018 = ("Pit by benches", "Corta por bancos")
PIT_MENU_018 = {  # orden → (rótulo en español, acción, frecuencia), en el orden del submenú «Corta por bancos»
    "geoblender.des_create_pit": ("Nueva corta…", "D", 1),
    "geoblender.des_expand_bench": ("Expandir banco…", "D", 1),
    "geoblender.des_edit_pit_ramp": ("Rampa…", "P", 1),
    "geoblender.des_edit_pit_rose": ("Roseta de taludes…", "P", 1),
    "geoblender.des_pit_skyline": ("Línea de cielo…", "D", 1),
    "geoblender.des_pit_surface": ("Superficie y sólido…", "D", 1),
}
INTERNAL_018 = ("geoblender.des_save_pit_rose", "geoblender.des_save_pit_ramp")
GONE_018 = ("des_new_pit", "des_add_ramp", "des_compute_daylight", "des_create_design_surface")
"""Las cuatro provisionales de R-35 que sustituyen las órdenes de la 018 (D-20)."""


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

    def test_entry_014_delivers_its_commands(self) -> None:
        """RF-014-29 (plan 014 §5.1 y §5.6; T05 y T58): la entrada ``014`` tiene el título de la
        spec en los dos idiomas y entrega sus comandos (``delivered``, desde la T58, antes del H3:
        sus cinco órdenes ya no salen en gris con «Disponible en 014»); ``R-34`` sigue como
        entrada del roadmap, sin comandos."""
        entry = self.cat.entries["014"]
        self.assertEqual((entry.title, entry.title_es), TITLE_014)
        self.assertTrue(entry.delivered)
        self.assertEqual(catalog.entry_text(self.cat, "014", "es"), f"014 · {TITLE_014[1]}")
        self.assertEqual(catalog.entry_text(self.cat, "014", "en"), f"014 · {TITLE_014[0]}")
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

    def test_the_five_commands_open_a_dialog_and_say_so(self) -> None:
        """RF-014-19, RF-014-29 (T61; lo que vio el H3): las cinco órdenes de la ``014`` abren un
        diálogo, así que su nombre acaba en «…» en los dos idiomas, también «Transiciones con el
        terreno no afectado…» (Restauración ▸ Superficie final), que no lo llevaba."""
        for key in MENU_014:
            with self.subTest(key=key):
                command = self.cat.commands[key]
                self.assertTrue(command.label.endswith("…"), command.label)
                self.assertTrue(command.label_es.endswith("…"), command.label_es)
        transitions = self.cat.commands["geoblender.des_create_transitions"]
        self.assertEqual((transitions.label, transitions.label_es),
                         ("Transitions with the untouched terrain…",
                          "Transiciones con el terreno no afectado…"))

    def test_entry_015_delivers_its_commands(self) -> None:
        """RF-015-28 (plan 015 §5.6, T31): la entrada ``015`` tiene el título de la spec en los dos idiomas y entrega sus
        comandos: «Plataforma…», las siete internas de las entidades y el menú «Entidad ▾» son suyos; ``R-36`` sigue como entrada del roadmap, sin
        entregar, con lo de la 016 (Acopio…, Contrafuerte…)."""
        entry = self.cat.entries["015"]
        self.assertEqual((entry.title, entry.title_es), TITLE_015)
        self.assertTrue(entry.delivered)
        self.assertEqual(catalog.entry_text(self.cat, "015", "es"), f"015 · {TITLE_015[1]}")
        self.assertEqual(catalog.entry_text(self.cat, "015", "en"), f"015 · {TITLE_015[0]}")
        self.assertEqual(sorted(command.key for command in self.cat.commands.values() if command.entry == "015"),
                         sorted((PLATFORM, *INTERNAL_015, "GEOBLENDER_MT_des_context_entity")))
        self.assertFalse(self.cat.entries["R-36"].delivered)
        self.assertEqual(sorted(command.key for command in self.cat.commands.values() if command.entry == "R-36"), [],
                         "ninguna orden es ya de R-36: las de la 016 las entrega la entrada 016 (T35)")

    def test_entry_016_delivers_the_stockpile_buttress_and_body_commands(self) -> None:
        """RF-016-25 (plan 016 §5.5, T35; D-8, D-14): la entrada ``016`` está entregada y trae las seis órdenes de la spec —tres con su casa en
        Diseño ▸ Pistas y entidades ▸ Entidades (con su rótulo definitivo) y tres internas—; **«Cuerpo apoyado…» es la «Unidad por espesor
        sobre su apoyo…»**: ya no existe ``geo_create_thickness_unit`` y no está en el menú de Geología."""
        entry = self.cat.entries["016"]
        self.assertTrue(entry.delivered)
        self.assertEqual(sorted(command.key for command in self.cat.commands.values() if command.entry == "016"),
                         sorted(("geoblender.des_edit_stockpile", "geoblender.des_add_buttress", "geoblender.des_create_body",
                                 "geoblender.des_detect_stockpiles", "geoblender.des_stockpile_candidates",
                                 "geoblender.des_remove_stockpile")))
        homes = {key: self.cat.commands[key] for key in ("geoblender.des_edit_stockpile", "geoblender.des_add_buttress",
                                                         "geoblender.des_create_body")}
        for key, command in homes.items():
            with self.subTest(key=key):
                self.assertEqual((command.module, command.kind, command.home, command.action), ("des", "operator", "GEOBLENDER_MT_des_entities", "D"))
        self.assertEqual([(command.label, command.label_es) for command in homes.values()],
                         [("Stockpile (detect, remove)…", "Acopio (detectar, retirar)…"), ("Buttress…", "Contrafuerte…"),
                          ("Supported body…", "Cuerpo apoyado…")])
        for key in ("geoblender.des_detect_stockpiles", "geoblender.des_stockpile_candidates", "geoblender.des_remove_stockpile"):
            with self.subTest(key=key):
                command = self.cat.commands[key]
                self.assertEqual((command.module, command.kind, command.home), ("des", "internal", ""))
        self.assertNotIn("geoblender.geo_create_thickness_unit", self.cat.commands)
        order = [item.key for item in self.cat.menus["GEOBLENDER_MT_des_entities"].groups[0].items]
        self.assertEqual(order[:4], ["geoblender.des_create_platform", "geoblender.des_edit_stockpile", "geoblender.des_add_buttress",
                                     "geoblender.des_create_body"])
        geology = [item.key for group in self.cat.menus["GEOBLENDER_MT_ui_geology"].groups for item in group.items]
        self.assertNotIn("geoblender.geo_create_thickness_unit", geology)

    def test_entry_017_delivers_its_commands(self) -> None:
        """RF-017-29, D-20 (plan 017 §5.6, T33b): la entrada ``017`` tiene el título de la spec en los dos idiomas y **entrega** sus órdenes: las cinco del
        menú y la interna de la ventana del perfil (y nada más); ``R-40`` sigue como entrada del roadmap, sin entregar y sin ninguna orden."""
        entry = self.cat.entries["017"]
        self.assertEqual((entry.title, entry.title_es), TITLE_017)
        self.assertTrue(entry.delivered)
        self.assertEqual(catalog.entry_text(self.cat, "017", "es"), f"017 · {TITLE_017[1]}")
        self.assertEqual(catalog.entry_text(self.cat, "017", "en"), f"017 · {TITLE_017[0]}")
        self.assertEqual(sorted(command.key for command in self.cat.commands.values() if command.entry == "017"),
                         sorted((*ROADS_MENU_017, *INTERNAL_017)))
        self.assertIn("R-40", self.cat.entries)
        self.assertFalse(self.cat.entries["R-40"].delivered)
        self.assertEqual(sorted(command.key for command in self.cat.commands.values() if command.entry == "R-40"), [],
                         "ninguna orden es ya de R-40: las entrega la entrada 017 (T33b)")

    def test_the_five_orders_are_the_first_of_haul_roads_and_entities(self) -> None:
        """RF-017-29, D-20, M6: «Pista…», «Proponer el trazado…» y «Accesibilidad de las pistas…» son **los tres primeros puestos** de Diseño ▸ Pistas y
        entidades, seguidos de «Perfil de pista…» y «Exportar pista…» y, después, el submenú «Entidades ▸»; cada una es de ``des``, una orden con su casa
        en Diseño, su acción y su frecuencia, y su rótulo acaba en «…» (abre un diálogo) en los dos idiomas; la interna del perfil no tiene casa."""
        design = self.cat.menus[HOME]
        (group,) = [item for item in design.groups if item.label == "Haul roads and entities"]
        self.assertEqual(group.label_es, "Pistas y entidades")
        self.assertEqual([item.key for item in group.items], [*ROADS_MENU_017, "GEOBLENDER_MT_des_entities"])
        for key, (label_es, action, frequency) in ROADS_MENU_017.items():
            with self.subTest(key=key):
                command = self.cat.commands[key]
                self.assertEqual((command.entry, command.module, command.kind, command.home), ("017", "des", "operator", HOME))
                self.assertEqual((command.label_es, command.action, command.frequency, command.background), (label_es, action, frequency, False))
                self.assertTrue(command.label.endswith("…") and command.label_es.endswith("…"))
        self.assertEqual([self.cat.commands[key].label for key in ROADS_MENU_017],
                         ["Road…", "Propose the route…", "Accessibility of the roads…", "Road profile…", "Export road…"])
        for key in INTERNAL_017:
            command = self.cat.commands[key]
            self.assertEqual((command.entry, command.module, command.kind, command.home), ("017", "des", "internal", ""))
        self.assertEqual(self.cat.commands["geoblender.des_create_road"].jargon, (("RecMin", "Pista"),))

    def test_the_three_provisional_orders_of_r40_are_gone(self) -> None:
        """RF-017-29, D-20 (M6): ``des_draw_haul_road``, ``des_route_haul_road`` y ``des_burn_roads`` ya no están en el catálogo ni en ningún menú, atajo, acceso
        rápido, menú circular, menú contextual, icono o disposición: **ningún fichero de datos del catálogo las nombra** (la pista graba al crearse y la
        «Ruta 3D con pendiente máxima…» pasó a «Proponer el trazado…»). Los comentarios de los ficheros (que cuentan la sustitución) no cuentan: sí los datos."""
        data = {path.name: "\n".join(line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#"))
                for path in DATA.rglob("*.toml")}
        for name in GONE_017:
            with self.subTest(orden=name):
                self.assertNotIn(f"geoblender.{name}", self.cat.commands)
                self.assertFalse([file for file, text in data.items() if name in text], "algún fichero del catálogo sigue nombrándola")
        shown = [item.key for menu in self.cat.menus.values() for group in menu.groups for item in group.items]
        self.assertFalse([key for key in shown if key and key.removeprefix("geoblender.") in GONE_017])

    def test_entry_018_delivers_its_commands(self) -> None:
        """RF-018-34, D-20 (plan 018 §5.5, T35): la entrada ``018`` tiene el título de la spec en los dos idiomas y **entrega** sus órdenes: las seis del submenú y las dos internas de las
        ventanas (y nada más); ``R-35`` sigue como entrada del roadmap, sin entregar y sin ninguna orden; las dos de R-49 no son de la 018."""
        entry = self.cat.entries["018"]
        self.assertEqual((entry.title, entry.title_es), TITLE_018)
        self.assertTrue(entry.delivered)
        self.assertEqual(catalog.entry_text(self.cat, "018", "es"), f"018 · {TITLE_018[1]}")
        self.assertEqual(catalog.entry_text(self.cat, "018", "en"), f"018 · {TITLE_018[0]}")
        self.assertEqual(sorted(command.key for command in self.cat.commands.values() if command.entry == "018"), sorted((*PIT_MENU_018, *INTERNAL_018)))
        self.assertIn("R-35", self.cat.entries)
        self.assertFalse(self.cat.entries["R-35"].delivered)
        self.assertEqual(sorted(command.key for command in self.cat.commands.values() if command.entry == "R-35"), [],
                         "ninguna orden es ya de R-35: las entrega la entrada 018 (T35)")
        for key in ("geoblender.des_design_pit_from_shell", "geoblender.des_compare_with_shell"):
            self.assertEqual(self.cat.commands[key].entry, "R-49", key)

    def test_the_pit_submenu_has_the_six_orders(self) -> None:
        """RF-018-34, D-20, M6: el submenú «Corta por bancos» de Diseño lleva **las seis órdenes en su orden**, después las dos de R-49; cada una es de ``des``, con su acción y
        frecuencia, y su rótulo acaba en «…» en los dos idiomas; las internas no tienen casa."""
        menu = self.cat.menus["GEOBLENDER_MT_des_pit"]
        keys = [item.key for group in menu.groups for item in group.items if item.key is not None]
        self.assertEqual(keys[:len(PIT_MENU_018)], list(PIT_MENU_018))
        self.assertEqual(keys[len(PIT_MENU_018):], ["geoblender.des_design_pit_from_shell", "geoblender.des_compare_with_shell"])
        for key, (label_es, action, frequency) in PIT_MENU_018.items():
            with self.subTest(key=key):
                command = self.cat.commands[key]
                self.assertEqual((command.entry, command.module, command.kind, command.home), ("018", "des", "operator", "GEOBLENDER_MT_des_pit"))
                self.assertEqual((command.label_es, command.action, command.frequency, command.background), (label_es, action, frequency, False))
                self.assertTrue(command.label.endswith("…") and command.label_es.endswith("…"))
        for key in INTERNAL_018:
            command = self.cat.commands[key]
            self.assertEqual((command.entry, command.module, command.kind, command.home), ("018", "des", "internal", ""))

    def test_the_four_provisional_orders_of_r35_are_gone(self) -> None:
        """RF-018-34, D-20 (M6): ``des_new_pit``, ``des_add_ramp``, ``des_compute_daylight`` y ``des_create_design_surface`` ya no están en el catálogo ni en ningún menú, atajo, acceso rápido,
        menú circular, menú contextual, icono o disposición: **ningún fichero de datos del catálogo las nombra** (los comentarios, que cuentan la sustitución, no cuentan)."""
        data = {path.name: "\n".join(line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#"))
                for path in DATA.rglob("*.toml")}
        for name in GONE_018:
            with self.subTest(orden=name):
                self.assertNotIn(f"geoblender.{name}", self.cat.commands)
                self.assertFalse([file for file, text in data.items() if f"geoblender.{name}" in text], "algún fichero del catálogo sigue nombrándola")
        shown = [item.key for menu in self.cat.menus.values() for group in menu.groups for item in group.items]
        self.assertFalse([key for key in shown if key and key.removeprefix("geoblender.") in GONE_018])

    def test_the_platform_and_the_internals_of_015(self) -> None:
        """RF-015-28 (D-14): «Plataforma…» es de la ``015`` y de ``des``, con su casa en Diseño ▸ Pistas y entidades ▸
        Entidades, y abre un diálogo (su nombre acaba en «…» en los dos idiomas); las internas, de la ``015`` y de ``des``,
        sin casa en un menú."""
        platform = self.cat.commands[PLATFORM]
        self.assertEqual((platform.entry, platform.module, platform.kind, platform.home), (
            "015", "des", "operator", "GEOBLENDER_MT_des_entities"))
        self.assertEqual((platform.label, platform.label_es), ("Platform…", "Plataforma…"))
        # T45, E-7: lo que hace hoy (un diálogo desde una capa), no «dibuja una plataforma con sus taludes» (la herramienta H)
        self.assertEqual(platform.action, "D")
        self.assertIn("layer", platform.description)
        self.assertIn("capa", platform.description_es)
        self.assertNotIn("Draw", platform.description)
        self.assertNotIn("Dibuja", platform.description_es)
        for key in INTERNAL_015:
            with self.subTest(key=key):
                command = self.cat.commands[key]
                self.assertEqual((command.entry, command.module, command.kind, command.home),
                                 ("015", "des", "internal", ""))
        self.assertNotIn("geoblender.des_draw_platform", self.cat.commands)

    def test_the_entity_context_menu_has_the_real_commands(self) -> None:
        """RF-015-28 (D-14, PC §3.11): el menú «Entidad ▾» (``DESIGN_ENTITY``) es de la ``015`` (su entrada, en
        ``contexts.toml``) y lleva, en su orden, las órdenes reales de las entidades —con «Lo que se apoya en ella» e
        «Insertar antes o después de…»— y la de exportar su superficie (la de la 013); lo que aún no es una orden (editar el eje,
        las restricciones que declara) sigue marcado en R-36; «Acopio (detectar, retirar)…» es de la 016 (entregada, T35)."""
        raw = tomllib.loads((DATA / "contexts.toml").read_text(encoding="utf-8"))
        (context,) = [table for table in raw["context"] if table["kind"] == "DESIGN_ENTITY"]
        self.assertEqual(context["entry"], "015")
        keys = [item["ref"] for item in context["item"] if "ref" in item]
        self.assertEqual([key for key in keys if key in ENTITY_MENU], list(ENTITY_MENU))
        self.assertIn("geoblender.des_edit_stockpile", keys)
        marked = [(item["placeholder"]["es"], item["entry"]) for item in context["item"] if "placeholder" in item]
        self.assertEqual(marked, [("Editar el eje o el contorno", "R-36"), ("Restricciones que declara…", "R-36")])
        spec = self.cat.contexts["DESIGN_ENTITY"]
        self.assertEqual(spec.id, "GEOBLENDER_MT_des_context_entity")
        self.assertEqual(self.cat.commands[spec.id].entry, "015")
        for key in keys:
            self.assertIn(key, self.cat.commands)
            self.assertIn(key, [item.key for item in spec.items if item.key])


if __name__ == "__main__":
    unittest.main()
