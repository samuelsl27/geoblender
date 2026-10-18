# SPDX-License-Identifier: GPL-3.0-or-later
"""La procedencia (spec 008) en el catálogo de comandos (T44; plan 008 §5.3.2 y §5.5;
ADR-0011).

- La entrada ``008`` tiene su título en inglés y en español y entrega sus comandos: los de
  Proyecto ▸ Control y el panel de lo obsoleto del control 7 pasan de ``R-07`` a ``008``;
  lo de la 009 (versiones, decisiones, reproducir) sigue en ``R-07``; Refrescar pasa a la
  ``010`` (spec 010, T11).
- Las nueve órdenes internas nuevas del plan §5.3.2 están en ``common.toml`` como
  ``internal``, de ``core`` y sin casa en un menú; toda orden que declara una operación de
  ``core`` (``OperationDef.commands``) existe en el catálogo.
- Los textos de la interfaz de la 008 están en ``messages.toml`` en español, y ningún
  ``msgid`` tiene dos traducciones entre el catálogo, ``messages.toml`` y los catálogos de
  la procedencia y de los parámetros (la tabla de ``core.i18n`` es una sola).
"""

import unittest

from tests.support.package import import_geoblender

catalog = import_geoblender("core.catalog")
i18n = import_geoblender("core.i18n")
params = import_geoblender("core.params")
contract = import_geoblender("core.provenance.contract")
messages = import_geoblender("core.provenance.messages")

TITLE = ("Provenance: parameters, inputs, operations and figures",
         "Procedencia: parámetros, entradas, operaciones y cifras")

# Proyecto ▸ Control y el panel del control 7 (RF-008-06, 16, 26, 28, 29).
CONTROL = (
    "geoblender.core_show_parameters",
    "geoblender.core_show_inputs",
    "geoblender.core_check_inputs",
    "geoblender.core_recompute_stale",
    "geoblender.core_show_lineage",
    "GEOBLENDER_PT_core_stale",
)
# Plan §5.3.2: las órdenes nuevas, internas (sin casa en un menú).
INTERNAL = (
    "geoblender.core_set_parameter",
    "geoblender.core_confirm_parameter",
    "geoblender.core_resolve_input",
    "geoblender.core_discard_input",
    "geoblender.core_edit_input",
    "geoblender.core_resolve_dataset",
    "geoblender.core_accept_review",
    "geoblender.core_resolve_unregistered",
    "geoblender.core_cancel_checks",
)
# Lo de la 009 (versiones, revisiones y vistas) que aún no ha llegado: sigue «Disponible en
# R-07». Refrescar ya no: es de la 010 (T11; plan 010 D-18); la versión activa (Versión activa ▸,
# Fijar la versión activa y la ventana del control 8), tampoco: es de la 009 (T18; plan 009
# D-38).
LATER = (
    "geoblender.core_new_version",
    "geoblender.core_new_revision",
    "geoblender.core_set_version_state",
    "geoblender.core_reproduce_version",
    "geoblender.core_show_decisions",
)
# Textos de la interfaz de la 008 en messages.toml (plan §5.3.2 y §5.5).
INTERFACE_TEXTS = {
    "Open a project": "Abra un proyecto",
    "Schema {schema} project: migrate the project to use provenance":
        "Proyecto de esquema {schema}: migre el proyecto para usar la procedencia",
    "⚠ {n} inputs": "⚠ {n} entradas",
    "⚠ 1 input": "⚠ 1 entrada",  # en singular (T71)
    "! {n} stale": "! {n} obsoletos",
    "! 1 stale": "! 1 obsoleto",
    "Checking the project… {percent} %": "Comprobando el proyecto… {percent} %",
    "Refresh · stale ({n})": "Refrescar · obsoletos ({n})",
    "[MEA]": "[MED]",
    "[CAL]": "[CAL]",
    "[ADO]": "[ADO]",
    "[HYP]": "[HIP]",
    "unconfirmed": "sin confirmar",
    "review": "revisar",
    "Project parameters": "Parámetros del proyecto",
    "Input register": "Registro de entradas",
    "Operation graph and provenance": "Grafo de operaciones y procedencia",
}


class ProvenanceCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cat = catalog.load()

    def test_entry_008(self) -> None:
        """RF-008-06, RF-008-16, RF-008-26, RF-008-28, RF-008-29: la entrada ``008`` tiene
        el título de la spec en los dos idiomas y entrega sus comandos; ``R-07`` sigue para
        la 009."""
        entry = self.cat.entries["008"]
        self.assertEqual((entry.title, entry.title_es), TITLE)
        self.assertTrue(entry.delivered)
        self.assertIn("R-07", self.cat.entries)
        self.assertFalse(self.cat.entries["R-07"].delivered)
        self.assertEqual(catalog.entry_text(self.cat, "008", "es"), f"008 · {TITLE[1]}")
        self.assertEqual(catalog.entry_text(self.cat, "008", "en"), f"008 · {TITLE[0]}")

    def test_control_commands_belong_to_008(self) -> None:
        """RF-008-06, RF-008-16, RF-008-26, RF-008-28, RF-008-29: Parámetros, Registro de
        entradas, Comprobar, Recalcular lo obsoleto, Grafo de operaciones y el panel de lo
        obsoleto son de la ``008`` y de ``core``; Comprobar dice que mira también los datos
        del proyecto; lo de la 009 sigue en ``R-07``."""
        for key in CONTROL:
            with self.subTest(key=key):
                command = self.cat.commands[key]
                self.assertEqual(command.entry, "008")
                self.assertEqual(command.module, "core")
        check = self.cat.commands["geoblender.core_check_inputs"]
        self.assertIn("project data", check.description)
        self.assertIn("datos del proyecto", check.description_es)
        self.assertEqual(self.cat.commands["geoblender.core_show_lineage"].home,
                         "GEOBLENDER_MT_core_provenance")
        quick = {item.key: item for item in self.cat.quick_access("project")}
        self.assertEqual(quick["geoblender.core_refresh"].extra, "GEOBLENDER_PT_core_stale")
        for key in LATER:
            with self.subTest(key=key):
                self.assertEqual(self.cat.commands[key].entry, "R-07")

    def test_internal_commands(self) -> None:
        """RF-008-06, RF-008-26, RF-008-28 (plan §5.3.2): las nueve órdenes nuevas son
        internas, de ``core``, de la ``008`` y sin casa en un menú ni en el acceso
        rápido; con etiqueta y descripción en los dos idiomas."""
        internal = {key for key, command in self.cat.commands.items()
                    if command.kind == "internal" and command.entry == "008"}
        self.assertEqual(internal, set(INTERNAL))
        placed = {key for item in self.cat.quick_access_items
                  for key in (item.key, item.extra) if key}
        placed |= {item.key for menu in self.cat.menus.values() for group in menu.groups
                   for item in group.items if item.key}
        for key in INTERNAL:
            with self.subTest(key=key):
                command = self.cat.commands[key]
                self.assertEqual(command.module, "core")
                self.assertEqual(command.home, "")
                self.assertNotIn(key, placed)
                self.assertTrue(command.label and command.label_es)
                self.assertTrue(command.description and command.description_es)

    def test_core_operation_commands_exist(self) -> None:
        """RF-008-27, RF-008-62 (plan §5.3.2): toda orden que declara una operación de
        ``core`` está en el catálogo, y también las catorce órdenes del plan."""
        idnames = self.cat.operator_idnames()
        for defn in contract.CORE_OPERATIONS:
            for command in defn.commands:
                with self.subTest(op_type=defn.op_type, command=command):
                    self.assertIn(command, idnames)
        planned = {key for key in (*CONTROL, *INTERNAL) if key.startswith("geoblender.")}
        self.assertEqual(len(planned), 14)
        self.assertEqual(sorted(planned - idnames), [])

    def test_interface_texts_in_spanish(self) -> None:
        """RF-008-06, RF-008-16, RF-008-28, RF-008-29 (principio 10): los textos de la
        interfaz de la 008 están en ``messages.toml`` con su español."""
        table = i18n.load_messages()
        self.assertEqual({msgid: table.get(msgid) for msgid in INTERFACE_TEXTS},
                         INTERFACE_TEXTS)

    def test_one_translation_per_msgid(self) -> None:
        """RF-008-06, RF-008-29 (principio 10): un ``msgid`` del catálogo de comandos, de
        ``messages.toml``, de la procedencia o de los parámetros tiene una sola traducción
        en todos (``core.i18n`` tiene una sola tabla)."""
        sources = {
            "messages.toml": i18n.load_messages(),
            "catálogo": self.cat.translations(),
            "procedencia": dict(messages.CATALOG_ES),
            "parámetros": dict(params.CATALOG_ES),
        }
        seen: dict[str, tuple[str, str]] = {}
        clashes: list[str] = []
        for name, table in sources.items():
            for msgid, spanish in table.items():
                first = seen.setdefault(msgid, (spanish, name))
                if first[0] != spanish:
                    clashes.append(f"«{msgid}»: «{first[0]}» ({first[1]}) y «{spanish}» "
                                   f"({name})")
        self.assertEqual(clashes, [])


if __name__ == "__main__":
    unittest.main()
