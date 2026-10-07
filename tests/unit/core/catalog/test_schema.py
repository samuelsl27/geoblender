# SPDX-License-Identifier: GPL-3.0-or-later
"""Validación del catálogo de comandos (spec 003, T02; RF-003-06, RF-003-07, RF-003-18;
plan 003 §5.2 y §5.3; BS §7.1 y §7.2).

Cada error de un catálogo sintético sale como una incidencia con el fichero, la clave,
el campo y el valor que la causan (constitución, principio 10):

- una clave duplicada (dos definiciones en el mismo menú) y un comando con dos casas;
- una referencia (↗, espejo, atajo) a un comando que no existe;
- una entrada (spec o R-id) sin título, o un R-id que no está en el roadmap;
- un atajo repetido en un mapa, y uno con Ctrl+Alt (AT §1, regla 3);
- un nombre de clase o un ``bl_idname`` que no cumple ADR-0011 (la misma expresión que
  NOM-01 y NOM-02);
- un texto sin traducción, con letras del español en el ``msgid`` o con otros
  marcadores, y un ``msgid`` con dos traducciones;
- un submenú sin contenido, un tipo de acción o una frecuencia inválidos, un TOML roto.
"""

import unittest

from tests.support.catalog_fixtures import VALID, appended, with_files
from tests.support.package import import_geoblender
from tests.support.repo import tools_on_path
from tests.support.trees import temp_tree

catalog = import_geoblender("core.catalog")
schema = import_geoblender("core.catalog.schema")

tools_on_path()
from gbtools.rules import naming  # noqa: E402

PROJECT = "menus/01_project.toml"
TOPOGRAPHY = "menus/02_topography.toml"

NEW_PROJECT_AGAIN = """
[[menu.group.item]]
key = "geoblender.core_new_project"
label = {en = "New project…", es = "Nuevo proyecto…"}
description = {en = "Create a project", es = "Crea un proyecto"}
entry = "002"
action = "D"
"""


def issues(files: dict[str, str], **kwargs: object) -> list[tuple[str, str, str, str]]:
    """(fichero, clave, campo, valor) de cada incidencia de ``files``."""
    with temp_tree(files) as root:
        cat = catalog.load(root)
    return [(i.file, i.key, i.field, i.value) for i in catalog.validate(cat, **kwargs)]


def messages(files: dict[str, str]) -> list[str]:
    with temp_tree(files) as root:
        cat = catalog.load(root)
    return [issue.message for issue in catalog.validate(cat)]


class ValidateTest(unittest.TestCase):
    def test_valid_has_no_issues(self) -> None:
        """RF-003-06: el catálogo sintético válido no tiene incidencias."""
        self.assertEqual(issues(VALID), [])

    def test_duplicate_key(self) -> None:
        """RF-003-06: un comando definido dos veces en el mismo menú es una clave
        duplicada, con el fichero, la clave y el campo."""
        found = issues(appended(PROJECT, NEW_PROJECT_AGAIN))
        self.assertEqual(found, [(PROJECT, "geoblender.core_new_project", "key",
                                  "geoblender.core_new_project")])
        self.assertIn("clave duplicada", messages(appended(PROJECT, NEW_PROJECT_AGAIN))[0])

    def test_two_homes(self) -> None:
        """RF-003-06 (BS §7.1, P3): un comando definido en dos menús tiene dos casas; el
        mensaje nombra las dos."""
        files = appended(TOPOGRAPHY, NEW_PROJECT_AGAIN)
        self.assertEqual(issues(files), [(TOPOGRAPHY, "geoblender.core_new_project", "key",
                                          "geoblender.core_new_project")])
        (message,) = messages(files)
        self.assertIn("dos casas", message)
        self.assertIn("GEOBLENDER_MT_ui_project", message)
        self.assertIn("GEOBLENDER_MT_ui_topography", message)

    def test_reference_to_missing_command(self) -> None:
        """RF-003-06: un acceso cruzado, un espejo o un atajo a un comando que no existe."""
        files = dict(VALID)
        files[TOPOGRAPHY] += '\n[[menu.group.item]]\nref = "geoblender.gis_nothing"\n'
        files["shortcuts.toml"] += ('\n[[shortcut]]\nkey = "geoblender.gis_none"\n'
                                    'keymap = "3D View"\nevent = "F6"\n')
        files["io_hubs.toml"] += '\n[[menu.group.item]]\nmirror = "geoblender.dh_none"\n'
        self.assertEqual(
            issues(files),
            [("io_hubs.toml", "geoblender.dh_none", "mirror", "geoblender.dh_none"),
             (TOPOGRAPHY, "geoblender.gis_nothing", "ref", "geoblender.gis_nothing"),
             ("shortcuts.toml", "geoblender.gis_none", "key", "geoblender.gis_none")],
        )

    def test_entry_without_title(self) -> None:
        """RF-003-07: la entrada de un comando tiene título en ``entries.toml`` (si no,
        «Disponible en …» no se puede escribir)."""
        files = dict(VALID)
        files[TOPOGRAPHY] = files[TOPOGRAPHY].replace('entry = "R-38"', 'entry = "R-39"')
        self.assertEqual(issues(files), [(TOPOGRAPHY,
                                          "geoblender.res_compute_volume_between_surfaces",
                                          "entry", "R-39")])
        self.assertIn("sin título", messages(files)[0])

    def test_roadmap_ids(self) -> None:
        """RF-003-07: con la lista de R-id del roadmap, un R-id que no está en ella."""
        self.assertEqual(issues(VALID, roadmap_ids=frozenset({"R-38"})), [])
        self.assertEqual(
            issues(VALID, roadmap_ids=frozenset({"R-07"})),
            [("entries.toml", "R-38", "entry", "R-38")],
        )

    def test_repeated_shortcut_in_a_keymap(self) -> None:
        """RF-003-18: dos atajos con la misma combinación en el mismo mapa; en otro mapa
        no es repetición."""
        same = '[[shortcut]]\nkey = "geoblender.ui_set_view?view=PLAN"\nkeymap = "3D View"\n' \
               'event = "F5"\nctrl = true\n'
        other_map = same.replace("3D View", "Window")
        self.assertEqual(
            issues(appended("shortcuts.toml", same)),
            [("shortcuts.toml", "geoblender.ui_set_view?view=PLAN", "event", "Ctrl+F5")],
        )
        self.assertEqual(issues(appended("shortcuts.toml", other_map)), [])

    def test_ctrl_alt_is_forbidden(self) -> None:
        """RF-003-18 (AT §1, regla 3): ninguna combinación con Ctrl+Alt (AltGr en el
        teclado español)."""
        text = '[[shortcut]]\nkey = "geoblender.ui_set_view?view=PLAN"\nkeymap = "3D View"\n' \
               'event = "G"\nctrl = true\nalt = true\n'
        self.assertEqual(issues(appended("shortcuts.toml", text)),
                         [("shortcuts.toml", "geoblender.ui_set_view?view=PLAN", "event",
                           "Ctrl+Alt+G")])

    def test_names_follow_adr_0011(self) -> None:
        """RF-003-06 (ADR-0011): las clases de menú y de panel y los ``bl_idname`` del
        catálogo cumplen la expresión de NOM-01 y NOM-02 (no las ve el AST, porque se
        crean con ``type()``)."""
        files = dict(VALID)
        files[PROJECT] = (files[PROJECT]
                          .replace("GEOBLENDER_MT_core_network", "GEOBLENDER_MT_xx_network")
                          .replace("geoblender.core_new_project", "geoblender.newProject"))
        found = issues(files)
        self.assertIn((PROJECT, "GEOBLENDER_MT_xx_network", "key", "GEOBLENDER_MT_xx_network"),
                      found)
        self.assertIn((PROJECT, "geoblender.newProject", "key", "geoblender.newProject"), found)

    def test_naming_expressions_match_nom_rules(self) -> None:
        """Plan 003 §5.3: la copia de las expresiones de ADR-0011 en ``core.catalog`` es
        la de ``tools/gbtools/rules/naming.py`` (NOM-01, NOM-02)."""
        self.assertEqual(schema.MODULE_CODES, naming.MODULE_CODES)
        self.assertEqual(schema.CLASS_RE.pattern, naming.CLASS_RE.pattern)
        self.assertEqual(schema.IDNAME_RE.pattern, naming.IDNAME_RE.pattern)

    def test_texts(self) -> None:
        """RF-003-20 (principio 10): etiqueta y descripción en inglés y en español, el
        ``msgid`` sin letras del español y los mismos marcadores; un ``msgid`` con dos
        traducciones distintas es un conflicto."""
        files = dict(VALID)
        files[PROJECT] = (files[PROJECT]
                          .replace('es = "Crea un proyecto"', 'es = ""')
                          .replace('en = "Look down"', 'en = "Mirar hacia abajo ñ"')
                          .replace('es = "Mira al norte"', 'es = "Mira al {norte}"'))
        files[TOPOGRAPHY] = files[TOPOGRAPHY].replace('es = "Analizar"', 'es = "Analizar ya"') \
            .replace('label = {en = "Analyze"', 'label = {en = "Exchange"')
        found = issues(files)
        self.assertEqual(
            sorted(found),
            sorted([
                (PROJECT, "geoblender.core_new_project", "description.es", ""),
                (PROJECT, "geoblender.ui_set_view?view=PLAN", "description.en",
                 "Mirar hacia abajo ñ"),
                (PROJECT, "geoblender.ui_set_view?view=NORTH", "description.es",
                 "Mira al {norte}"),
                (TOPOGRAPHY, "GEOBLENDER_MT_ui_topography", "group.label.es", "Analizar ya"),
            ]),
        )

    def test_structure(self) -> None:
        """RF-003-06: un submenú sin contenido, una acción o una frecuencia inválidas,
        unas propiedades fuera de orden y un TOML roto."""
        files = dict(VALID)
        files["io_hubs.toml"] = files["io_hubs.toml"].replace(
            'id = "GEOBLENDER_MT_io_import"', 'id = "GEOBLENDER_MT_io_other"')
        files[PROJECT] = (files[PROJECT]
                          .replace('action = "D"\nfrequency = 1', 'action = "X"\nfrequency = 5')
                          .replace("direction=-1&scope=SET", "scope=SET&direction=-1"))
        files["shortcuts.toml"] = "[[shortcut]\n"
        found = issues(files)
        self.assertEqual(
            sorted(found),
            sorted([
                ("io_hubs.toml", "GEOBLENDER_MT_io_other", "id", "GEOBLENDER_MT_io_other"),
                (PROJECT, "GEOBLENDER_MT_io_import", "menu", ""),
                (PROJECT, "geoblender.core_new_project", "action", "X"),
                (PROJECT, "geoblender.core_new_project", "frequency", "5"),
                (PROJECT, "geoblender.geo_step_section?scope=SET&direction=-1", "key",
                 "geoblender.geo_step_section?scope=SET&direction=-1"),
                ("shortcuts.toml", "", "toml", "[[shortcut]"),
            ]),
        )


if __name__ == "__main__":
    unittest.main()
