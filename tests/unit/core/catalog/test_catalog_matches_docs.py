# SPDX-License-Identifier: GPL-3.0-or-later
"""El catálogo de comandos frente a BS §8 (spec 003, T04–T07; RF-003-06; CE-003-04; BS =
``docs/arquitectura/interfaz/barra-superior.md``, en la carpeta de la documentación).

Cada tabla de BS §8 (los 13 menús, los submenús de Herramientas y los concentradores de
intercambio) se compara fila a fila con el menú del catálogo: rótulos de grupo (en
español), separadores, «↳» (submenú) y «↗» (acceso cruzado), identificadores
(``bl_idname`` o clase), propiedades fijadas, módulo, entrada, tipo, trabajo en segundo
plano y frecuencia. Un submenú de variantes que BS enumera en una sola fila («Isométrica ▸
(NE, NO, SE, SO)») tiene en el catálogo tantas opciones como enumera. Las listas en prosa
de BS §8.12–§8.14 (Comprobar ▸, Trabajos ▸, Disposición ▸, Datos ▾), también. La primera
línea de cada menú de la barra (paso, rama, icono propio y de reserva) sale del rótulo de
su sección.

Las diferencias con BS que un plan aprueba antes de que se escriban en BS van en
:data:`APPROVED_ENTRIES` (las del plan 003 ya las escribió la T37). Los menús que aún no están en el catálogo, en
:data:`PENDING` (cada tarea T05–T07 quita los suyos; al final, ninguno).

Sin la carpeta de la documentación, se omite con el recurso ``docs``.
"""

import re
import unittest
from collections.abc import Iterator

from tests.support import bs_tables, docs
from tests.support.package import import_geoblender

catalog = import_geoblender("core.catalog")

# Menús de BS §8 que aún no están en el catálogo (la T04 los listó y T05–T07 los fueron
# quitando): ninguno.
PENDING: frozenset[str] = frozenset()

# Accesos cruzados a comandos cuya casa es un menú pendiente: ninguno (T07).
PENDING_REFS: frozenset[str] = frozenset()

# Entradas aprobadas con un plan que BS §8 aún no dice (la T37 de la 003 escribió en BS las
# del plan 003 §11, Manual y Novedades en R-13; D-4). Plan 008 §5.1 y §5.5 (T44): las
# órdenes de Proyecto ▸ Control de la 008 pasan de R-07 a 008 (R-07 se partió en la 008 y
# la 009; lo de la 009 sigue en R-07). Plan 010 D-18 (T11): Refrescar pasa de R-07 a 010 hasta
# que la T19 de la 010 lo escriba en BS. identificador → entrada.
APPROVED_ENTRIES: dict[str, str] = {
    "core_show_parameters": "008",
    "core_show_inputs": "008",
    "core_check_inputs": "008",
    "core_recompute_stale": "008",
    "core_show_lineage": "008",
    "core_refresh": "010",
}

# Filas ↗ de BS que no dicen lo mismo que la casa de su comando (manda la casa: un comando,
# una definición): ninguna (la T37 corrigió el «D·2p» de ``io_import_block_model`` en
# §8.5). (menú, identificador) → campo de BS que se toma de la casa.
CROSS_ROW_DIFFERENCES: dict[tuple[str, str], str] = {}

BRANCHES = {"común": "common", "rama de diseño": "design", "rama geológica": "geology",
            "convergencia": "convergence", "transversal": "transversal"}
_HEADING_RE = re.compile(
    r"^### 8\.(\d+) (?P<title>.+?) — `(?P<menu>GEOBLENDER_MT_[a-z_]+)` · "
    r"(?:`(?P<icon>gb_[a-z_]+)` / `(?P<fallback>[A-Z_]+)`|icono `(?P<native>[A-Z_]+)`)"
    r"(?: · paso (?P<step>\d+))? · (?P<branch>.+)$"
)


def short(idname: str) -> str:
    return idname.removeprefix("geoblender.")


class Rows:
    """Las filas de un menú del catálogo en la forma de las tablas de BS §8."""

    def __init__(self, cat: object, own_tables: frozenset[str]) -> None:
        self.cat = cat
        self.own_tables = own_tables

    def menu(self, menu_id: str) -> list[tuple[str, object, bs_tables.DocRow | None]]:
        rows: list[tuple[str, object, bs_tables.DocRow | None]] = []
        for group in self.cat.menus[menu_id].groups:
            if group.label:
                rows.append(("group", group.label_es, None))
            for item in group.items:
                rows.extend(self.item(item, sub=False))
        return rows

    def item(self, item: object, *, sub: bool) -> Iterator[tuple[str, object, object]]:
        if item.separator:
            yield ("separator", sub, None)
            return
        command = self.cat.commands.get(item.key)
        if command is None:
            yield ("missing", item.key, None)
            return
        yield ("command", (sub, item.cross, command), None)
        content = self.cat.menus.get(command.key)
        if (not item.cross and command.kind == "menu" and not command.doc_id
                and command.key not in self.own_tables and content is not None):
            for group in content.groups:
                for inner in group.items:
                    yield from self.item(inner, sub=True)


def doc_view(row: bs_tables.DocRow, menu: str = "") -> tuple:
    """Lo que dice BS de una fila, con los campos que tiene su tabla."""
    if row.kind == "group":
        return ("group", row.text)
    if row.kind == "separator":
        return ("separator", row.sub)
    entry = row.entry
    background = row.background
    for identifier in row.ids:
        entry = APPROVED_ENTRIES.get(identifier, entry)
        if CROSS_ROW_DIFFERENCES.get((menu, identifier)) == "background":
            background = not background
    return ("command", row.sub, row.cross, row.ids,
            *(() if row.module is None else (row.module,)),
            *(() if entry is None else (entry,)),
            row.action, background,
            *(() if row.frequency is None else (row.frequency,)))


def catalog_view(kind: str, value: object, doc: bs_tables.DocRow) -> tuple:
    """La misma vista de una fila del catálogo, con los campos de la fila de BS."""
    if kind == "group":
        return ("group", value)
    if kind == "separator":
        return ("separator", value)
    if kind == "missing":
        return ("missing", value)
    sub, cross, command = value
    # BS lista un submenú de variantes por su operador en su casa y por su clase en un ↗
    # (Geología ▸ ↗ Nueva sección ▸).
    ids = command.doc_id if command.doc_id and not cross else (short(command.idname),)
    # La frecuencia de un acceso cruzado es la de ese sitio en BS; el comando tiene la de su
    # casa (una sola definición): en las filas ↗ se toma la de BS.
    frequency = doc.frequency if cross else command.frequency
    return ("command", sub, cross, tuple(ids),
            *(() if doc.module is None else (command.module,)),
            *(() if doc.entry is None else (command.entry,)),
            command.action, command.background,
            *(() if doc.frequency is None else (frequency,)))


@docs.requires_docs
class CatalogMatchesDocsTest(unittest.TestCase):
    """RF-003-06, CE-003-04: el catálogo tiene todas las entradas de BS §8."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = docs.read(docs.BS_RELPATH)
        cls.tree = bs_tables.parse(cls.text)
        cls.cat = catalog.load()
        cls.own = frozenset(table.menu for table in cls.tree.tables) | frozenset(cls.tree.prose)
        cls.rows = Rows(cls.cat, cls.own)

    def test_pending_menus_are_not_in_the_catalog(self) -> None:
        """T04–T07: lo pendiente de verdad lo está (un menú o un comando que ya está en el
        catálogo se quita de PENDING o de PENDING_REFS y se compara)."""
        for key in PENDING_REFS:
            self.assertNotIn(key, self.cat.commands, "ya está: quítelo de PENDING_REFS")
        for menu in PENDING:
            with self.subTest(menu=menu):
                self.assertIn(menu, self.own, "PENDING nombra un menú que no está en BS §8")
                self.assertNotIn(menu, self.cat.menus,
                                 "ya está en el catálogo: quítelo de PENDING")

    def test_tables(self) -> None:
        """RF-003-06: cada tabla de BS §8, fila a fila: grupos, separadores, ↳, ↗,
        identificadores, módulo, entrada, tipo, ·2p y frecuencia."""
        for table in self.tree.tables:
            if table.menu in PENDING:
                continue
            with self.subTest(menu=table.menu, line=table.line):
                self.assertIn(table.menu, self.cat.menus, "menú de BS §8 sin catálogo")
                actual = self.rows.menu(table.menu)
                for index, doc in enumerate(table.rows):
                    self.assertLess(index, len(actual),
                                    f"BS línea {doc.line}: falta en el catálogo {doc_view(doc)}")
                    kind, value, _ = actual[index]
                    if kind == "missing" and value in PENDING_REFS:
                        continue
                    self.assertEqual(catalog_view(kind, value, doc), doc_view(doc, table.menu),
                                     f"BS línea {doc.line} ({doc.text or doc.kind})")
                self.assertEqual(len(actual), len(table.rows),
                                 f"el catálogo tiene de más: {actual[len(table.rows):]}")

    def test_fixed_properties(self) -> None:
        """RF-003-06: las propiedades que fija una fila (``view='PLAN'``, ``'NORTH'``,
        ``direction=1``) son las de la clave del comando del catálogo."""
        for table in self.tree.tables:
            if table.menu in PENDING:
                continue
            actual = self.rows.menu(table.menu)
            for doc, (kind, value, _) in zip(table.rows, actual, strict=False):
                if doc.kind != "command" or kind != "command" or value[2].doc_id:
                    continue
                props = {name: str(prop) for name, prop in value[2].props}
                for token in doc.props:
                    with self.subTest(line=doc.line, token=token):
                        name, equals, raw = token.partition("=")
                        if not equals:
                            if token.startswith("'"):
                                self.assertIn(token.strip("'"), props.values())
                            continue
                        if "±" not in raw:
                            self.assertEqual(props.get(name), raw.strip("'"))

    def test_variant_submenus(self) -> None:
        """RF-003-06: un submenú que BS enumera en una celda («Recorte ▸ (…): Sin recorte ·
        Delante · …», «Isométrica ▸ (NE, NO, SE, SO)», «1–4») tiene esas opciones."""
        checked = 0
        for table in self.tree.tables:
            if table.menu in PENDING:
                continue
            for doc, (kind, value, _) in zip(table.rows, self.rows.menu(table.menu),
                                             strict=False):
                if kind != "command" or value[1] or not value[2].doc_id or value[2].dynamic:
                    continue
                expected = bs_tables.list_count(doc.text)
                content = self.cat.menus[value[2].key]
                options = [item for group in content.groups for item in group.items
                           if not item.separator]
                with self.subTest(line=doc.line, menu=value[2].key):
                    self.assertIsNotNone(expected, "BS no enumera las opciones")
                    self.assertEqual(len(options), expected)
                checked += 1
        self.assertGreater(checked, 0)

    def test_top_menus(self) -> None:
        """RF-003-06 (BS §5, §6, §8): los menús de la barra en el orden de BS, con su
        título, su paso de 11, su rama, su icono propio y su reserva."""
        headings = [match for line in self.text.splitlines()
                    if (match := _HEADING_RE.match(line))]
        self.assertEqual(len(headings), 13)
        expected_order = [h["menu"] for h in headings if h["menu"] not in PENDING]
        self.assertEqual(list(self.cat.top_menus), expected_order)
        for heading in headings:
            menu_id = heading["menu"]
            if menu_id in PENDING:
                continue
            with self.subTest(menu=menu_id):
                command = self.cat.commands[menu_id]
                spec = self.cat.menus[menu_id]
                self.assertEqual(command.label_es, heading["title"])
                self.assertEqual(command.icon, heading["icon"])
                self.assertEqual(command.icon_fallback, heading["fallback"] or heading["native"])
                step = heading["step"]
                self.assertEqual(spec.step, int(step) if step else None)
                self.assertEqual(spec.branch, BRANCHES[heading["branch"].strip()])
                if step:
                    self.assertTrue(spec.stage and spec.stage_es, "falta la etapa del paso")

    def test_prose_lists(self) -> None:
        """RF-003-06: Comprobar ▸ y Trabajos ▸ (elementos, ↗, entrada y tipo),
        Disposición ▸ (sus operadores) y Datos ▾ (los mismos de Proyecto ▸ Intercambio)."""
        for menu_id, prose in self.tree.prose.items():
            if menu_id in PENDING:
                continue
            with self.subTest(menu=menu_id):
                self.assertIn(menu_id, self.cat.menus)
                items = [item for group in self.cat.menus[menu_id].groups
                         for item in group.items if not item.separator]
                if menu_id == "GEOBLENDER_MT_ui_layouts":
                    idnames = {short(self.cat.commands[i.key].idname) for i in items}
                    self.assertEqual(idnames, set(prose.items[0].ids))
                elif menu_id == "GEOBLENDER_MT_core_data":
                    self.assertEqual([i.key for i in items], self.data_menu_keys(prose))
                else:
                    actual = []
                    for item in items:
                        command = self.cat.commands[item.key]
                        # Como en las tablas: un submenú de variantes, por su operador
                        # (Trabajos ▸ Autodiagnóstico ▸, spec 004, T42).
                        ids = (command.doc_id if command.doc_id and not item.cross
                               else (short(command.idname),))
                        actual.append((tuple(ids), item.cross, command.entry,
                                       command.action, command.background))
                    expected = [(p.ids, p.cross, p.entry, p.action, p.background)
                                for p in prose.items]
                    self.assertEqual(actual, expected)

    def data_menu_keys(self, prose: bs_tables.ProseList) -> list[str]:
        """Las claves de las filas de Proyecto ▸ Intercambio con el texto de cada
        elemento de Datos ▾ («Importar ▸» es «Importar ▸ (§8.14)»)."""
        table = self.tree.table("GEOBLENDER_MT_ui_project")
        actual = self.rows.menu("GEOBLENDER_MT_ui_project")
        by_text: dict[str, str] = {}
        for doc, (kind, value, _) in zip(table.rows, actual, strict=False):
            if kind == "command":
                by_text[doc.text.replace(" (§8.14)", "").strip()] = value[2].key
        return [by_text[item.text] for item in prose.items]

    def test_every_row_is_compared(self) -> None:
        """CE-003-04: todas las filas con identificador de BS §8 (389 el 05/10/2026) se
        comparan, salvo las de los menús pendientes."""
        total = sum(1 for table in self.tree.tables for row in table.rows
                    if row.kind == "command" and row.ids)
        pending = sum(1 for table in self.tree.tables if table.menu in PENDING
                      for row in table.rows if row.kind == "command" and row.ids)
        self.assertGreaterEqual(total, 389)
        compared = total - pending
        self.assertGreater(compared, 0)
        if not PENDING:
            self.assertEqual(compared, total)


if __name__ == "__main__":
    unittest.main()
