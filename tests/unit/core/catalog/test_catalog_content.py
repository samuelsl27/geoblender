# SPDX-License-Identifier: GPL-3.0-or-later
"""Espejos, atajos, entradas y disposiciones del catálogo de comandos (spec 003, T08;
RF-003-06, RF-003-11, RF-003-16, RF-003-17, RF-003-18).

Sin la documentación:

- 49 atajos (AT §2), uno en «Window» (Ctrl+F10, solo con Ctrl) y 48 en «3D View», sin
  repetir combinación en un mapa y sin Ctrl+Alt (AT §1, regla 3);
- 8 + 24 controles de acceso rápido en 6 grupos, con el plegado de AR §3.3 (paso 1 a
  solo icono; pasos 2–5 a «»»; nunca Vista, Sección, Nueva polilínea ni Encaje) y el
  subconjunto de los modos de edición;
- 4 menús circulares de 8 ranuras, 14 menús contextuales (13 tipos y la selección) con dos
  iconos y 7 disposiciones con una principal;
- todo espejo (acceso rápido, menú circular, contextual) apunta a un comando con casa en un
  menú (o a un panel, un nativo o un auxiliar interno, que no la tienen);
- todo operador ``geoblender.*`` que define ``geoblender/bl/`` está en el catálogo (AST).

Con la documentación (recurso ``docs``), además, frente a AT §2, AR §2, §3.1 y §4, PC §3 y
CW §6.2; todo R-id existe en ``docs/producto/roadmap.md``; y toda entrada de una spec
«Cerrada» en ``specs/README.md`` tiene su clase real en ``geoblender/bl/`` (AST).
"""

import ast
import re
import unicodedata
import unittest

from tests.support import bs_tables, docs
from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR

catalog = import_geoblender("core.catalog")
i18n = import_geoblender("core.i18n")

AT_RELPATH = "docs/arquitectura/interfaz/atajos.md"
AR_RELPATH = "docs/arquitectura/interfaz/accesos-rapidos.md"
PC_RELPATH = "docs/arquitectura/interfaz/paneles-contextuales.md"
CW_RELPATH = "docs/arquitectura/interfaz/conmutador-y-espacios-de-trabajo.md"

# AR §3.3: paso 1, a solo icono; pasos 2–5, a «»» (por grupo o por control).
COMPACT_STEP_1 = frozenset({"GEOBLENDER_PT_geo_band", "GEOBLENDER_PT_ui_current_object"})
FOLD_BY_GROUP = {"command": 2, "compute": 3, "query": 4}
FOLD_STEP_5 = frozenset({"GEOBLENDER_PT_ui_work_plane", "GEOBLENDER_PT_ui_current_object",
                         "GEOBLENDER_MT_gis_polyline_edit",
                         "GEOBLENDER_PT_ui_selection_filter"})
# AR §3.3: nunca se pliegan Vista, Sección, Nueva polilínea y Encaje; en edición quedan
# además Plano de trabajo y Objeto actual.
NEVER_FOLDED_GROUPS = frozenset({"view", "section"})
NEVER_FOLDED = frozenset({"geoblender.ui_draw_polyline", "tool_settings.use_snap"})
EDIT_MODES_EXTRA = frozenset({"GEOBLENDER_PT_ui_work_plane", "GEOBLENDER_PT_ui_current_object"})

HOMELESS_KINDS = frozenset({"menu", "panel", "native", "property", "internal"})
MODIFIERS = {"Ctrl": "ctrl", "Mayús": "shift", "Alt": "alt"}
KEY_EVENTS = {"RePág": "PAGE_UP", "AvPág": "PAGE_DOWN", "Inicio": "HOME",
              "NumPLUS": "NUMPAD_PLUS", "Num−": "NUMPAD_MINUS"}
DIGITS = ("ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE")


def short(idname: str) -> str:
    return idname.removeprefix("geoblender.")


def words(text: str) -> set[str]:
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    return set(re.findall(r"[a-z0-9]+", plain))


def parse_combo(text: str, inherited: frozenset[str] = frozenset()) -> tuple[frozenset[str], str]:
    """(modificadores, evento) de «Mayús+Alt+RePág»; sin modificadores, los heredados."""
    parts = text.replace("Num+", "NumPLUS").split("+")
    mods = frozenset(MODIFIERS[part] for part in parts[:-1])
    key = parts[-1].strip()
    event = KEY_EVENTS.get(key) or (DIGITS[int(key)] if key.isdigit() else key.upper())
    return (mods if mods else inherited), event


def expand_combos(cell: str) -> list[tuple[frozenset[str], str]]:
    """Las combinaciones de una celda de AT §2: «Ctrl+F5 … Ctrl+F8», «Alt+1 … Alt+6»,
    «Mayús+RePág / AvPág», «Alt+Num+ / Alt+Num−»."""
    text = cell.strip("* ")
    if " … " in text:
        first, last = text.split(" … ")
        mods, start = parse_combo(first)
        _mods, end = parse_combo(last, mods)
        if start.startswith("F") and end.startswith("F"):
            return [(mods, f"F{n}") for n in range(int(start[1:]), int(end[1:]) + 1)]
        return [(mods, DIGITS[n]) for n in range(DIGITS.index(start), DIGITS.index(end) + 1)]
    if " / " in text:
        first, second = text.split(" / ")
        mods, event = parse_combo(first)
        return [(mods, event), parse_combo(second, mods)]
    return [parse_combo(text)]


def bl_idnames() -> set[str]:
    """Los ``bl_idname`` literales ``geoblender.*`` de las clases de ``geoblender/bl/``."""
    found: set[str] = set()
    for path in sorted((EXTENSION_DIR / "bl").rglob("*.py")):
        tree = ast.parse(path.read_bytes().decode("utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for statement in node.body:
                if (isinstance(statement, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == "bl_idname"
                                for t in statement.targets)
                        and isinstance(statement.value, ast.Constant)
                        and str(statement.value.value).startswith("geoblender.")):
                    found.add(statement.value.value)
    return found


class CatalogContentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cat = catalog.load()

    def test_catalog_is_valid(self) -> None:
        """RF-003-06: el catálogo real no tiene incidencias (con ``messages.toml``)."""
        issues = catalog.validate(self.cat, messages=i18n.load_messages())
        self.assertEqual([str(issue) for issue in issues], [])

    def test_shortcuts(self) -> None:
        """RF-003-18 (AT §1 y §2): 49 combinaciones, Ctrl+F10 en «Window» con solo Ctrl
        y las demás en «3D View», ninguna repetida en su mapa ni con Ctrl+Alt."""
        shortcuts = self.cat.shortcuts()
        self.assertEqual(len(shortcuts), 49)
        (window,) = [s for s in shortcuts if s.keymap == "Window"]
        self.assertEqual((window.key, window.event, window.ctrl, window.shift, window.alt),
                         ("geoblender.ui_toggle_mode", "F10", True, False, False))
        self.assertEqual({s.keymap for s in shortcuts if s is not window}, {"3D View"})
        combos = [(s.keymap, s.event, s.ctrl, s.shift, s.alt) for s in shortcuts]
        self.assertEqual(len(set(combos)), 49)
        self.assertFalse([s.key for s in shortcuts if s.ctrl and s.alt])

    def test_quick_access(self) -> None:
        """RF-003-03, RF-003-11 (AR §2, §3.1 y §3.3): 8 controles del proyecto y 24 de la
        vista en 6 grupos, con su plegado y su subconjunto de edición."""
        project = self.cat.quick_access("project")
        view = self.cat.quick_access("view")
        self.assertEqual(len(project), 8)
        self.assertEqual(len(view), 24)
        self.assertEqual(list(dict.fromkeys(item.group for item in view)),
                         ["view", "section", "draw", "query", "compute", "command"])
        for item in view:
            with self.subTest(key=item.key):
                self.assertEqual(item.compact_step, 1 if item.key in COMPACT_STEP_1 else None)
                expected = FOLD_BY_GROUP.get(item.group)
                if item.key in FOLD_STEP_5:
                    expected = 5
                if item.group in NEVER_FOLDED_GROUPS or item.key in NEVER_FOLDED:
                    expected = None
                self.assertEqual(item.fold_step, expected)
                edit = (item.group in NEVER_FOLDED_GROUPS or item.key in NEVER_FOLDED
                        or item.key in EDIT_MODES_EXTRA)
                self.assertEqual(item.edit_modes, edit)
                if item.compact_step:
                    self.assertTrue(item.width_text, "el texto que se pliega a solo icono")

    def test_pies_contexts_layouts(self) -> None:
        """RF-003-06, RF-003-16, RF-003-17: 4 menús circulares de 8 ranuras, 15 menús
        contextuales con dos iconos (el de la rejilla de diferencias, de la spec 011, T22) y 7
        disposiciones, una principal."""
        self.assertEqual(len(self.cat.pies), 4)
        for pie in self.cat.pies.values():
            self.assertEqual(len(pie.slots), 8, pie.id)
        self.assertEqual(len(self.cat.contexts), 15)
        self.assertIn("SELECTION", self.cat.contexts)
        for context in self.cat.contexts.values():
            self.assertEqual(len(context.icons), 2, context.id)
            self.assertTrue(context.items, context.id)
        self.assertEqual(len(self.cat.layouts), 7)
        (main,) = [layout for layout in self.cat.layouts if layout.main]
        self.assertEqual((main.id, main.workspace), ("MAIN", main.label))
        variants = {cmd.props for cmd in self.cat.by_idname("geoblender.ui_add_layout")}
        self.assertEqual(variants, {(("layout", layout.id),) for layout in self.cat.layouts})
        for layout in self.cat.layouts:
            command = self.cat.commands[f"geoblender.ui_add_layout?layout={layout.id}"]
            self.assertEqual((command.label, command.entry), (layout.label, layout.entry))

    def test_mirrors_point_to_commands_with_home(self) -> None:
        """RF-003-06 (BS §7.1, P3): todo espejo apunta a un comando del catálogo con casa
        en un menú, o a un panel, un nativo o un auxiliar interno."""
        keys: list[str] = []
        for item in self.cat.quick_access_items:
            keys += [item.key, *([item.extra] if item.extra else [])]
        for pie in self.cat.pies.values():
            keys += list(pie.slots)
        for context in self.cat.contexts.values():
            keys += [item.key for item in (*context.items, *context.icons) if item.key]
        self.assertGreater(len(keys), 100)
        for key in keys:
            with self.subTest(key=key):
                command = self.cat.commands[key]
                self.assertTrue(command.home or command.kind in HOMELESS_KINDS,
                                "un operador espejo tiene casa en un menú de la barra")

    def test_real_operators_are_in_the_catalog(self) -> None:
        """BS §7.2, prueba 2: todo operador ``geoblender.*`` que define ``geoblender/bl/``
        está en el catálogo (también los auxiliares internos)."""
        defined = bl_idnames()
        self.assertIn("geoblender.core_new_project", defined)
        self.assertEqual(sorted(defined - self.cat.operator_idnames()), [])


@docs.requires_docs
class CatalogAgainstDocsTest(unittest.TestCase):
    """Los espejos y los atajos frente a AT, AR, PC y CW; los R-id frente al roadmap."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.cat = catalog.load()

    def test_shortcuts_match_at(self) -> None:
        """RF-003-18 (AT §2): cada combinación de AT §2, en su mapa, con su operador y el
        menú o panel que nombra; ninguna de más."""
        rows = bs_tables.tables(bs_tables.section(docs.read(AT_RELPATH), "## 2. Mapa de atajos"))[0]
        by_combo = {(s.keymap, frozenset(m for m, on in (("ctrl", s.ctrl), ("shift", s.shift),
                                                         ("alt", s.alt)) if on), s.event): s
                    for s in self.cat.shortcuts()}
        seen = 0
        for cells in rows:
            combo_cell, _action, operator_cell, keymap = cells[0], cells[1], cells[2], cells[3]
            (operator, *_rest) = bs_tables.identifiers(operator_cell)
            quoted = re.findall(r"'(GEOBLENDER_[A-Z]{2}_[a-z_]+)'", operator_cell)
            explicit = [token for token in bs_tables.backticked(operator_cell)
                        if "=" in token and "±" not in token and "'GEOBLENDER" not in token]
            for mods, event in expand_combos(combo_cell):
                seen += 1
                with self.subTest(combo=combo_cell, event=event):
                    shortcut = by_combo.get((keymap, mods, event))
                    self.assertIsNotNone(shortcut, "falta en shortcuts.toml")
                    self.assertEqual(short(shortcut.idname), operator)
                    props = dict(part.split("=") for part in shortcut.key.partition("?")[2]
                                 .split("&") if part)
                    if quoted:
                        self.assertEqual(props.get("name"), quoted[0])
                    for token in explicit:
                        name, value = token.split("=")
                        self.assertEqual(props.get(name), value.strip("'"))
        self.assertEqual(seen, 49)

    def test_quick_access_matches_ar(self) -> None:
        """RF-003-03, RF-003-11 (AR §2 y §3.1): los controles en su orden, con su comando,
        su segundo comando, su grupo y el icono propio y de reserva de su comando."""
        text = docs.read(AR_RELPATH)
        project = bs_tables.tables(bs_tables.section(
            text, "## 2. Acceso rápido del proyecto (barra superior)"))[0]
        view = bs_tables.tables(bs_tables.section(text, "### 3.1 Lista ordenada"))[0]
        rows = [(cells, None, cells[2], cells[3]) for cells in project] + \
               [(cells, cells[1], cells[3], cells[4]) for cells in view]
        items = [*self.cat.quick_access("project"), *self.cat.quick_access("view")]
        self.assertEqual(len(rows), len(items))
        for (cells, group, icon_cell, action_cell), item in zip(rows, items, strict=True):
            with self.subTest(number=cells[0], key=item.key):
                ids = [short(token) for token in bs_tables.identifiers(action_cell)]
                self.assertEqual(short(self.cat.commands[item.key].idname), ids[0])
                self.assertEqual(item.extra, ids[1] if len(ids) > 1 else None)
                for token in bs_tables.backticked(action_cell):
                    if "=" in token:
                        self.assertIn(token.replace("'", ""), item.key)
                if group is not None:
                    self.assertEqual(self.cat.quick_access_groups[item.group][1], group)
                if cells[0] == "1":
                    continue  # el conmutador: dos botones (gb_logo y BLENDER)
                command = self.cat.commands[item.key]
                own = [t for t in bs_tables.backticked(icon_cell) if t.startswith("gb_")]
                natives = [t for t in bs_tables.backticked(icon_cell) if t.isupper()]
                if own and "<" not in own[0]:
                    self.assertEqual(command.icon, own[0])
                elif not own:
                    self.assertIsNone(command.icon)
                self.assertEqual(command.icon_fallback, natives[0])

    def test_pies_match_ar(self) -> None:
        """RF-003-06 (AR §4): cada menú circular con sus 8 ranuras en el orden O, E, S, N,
        NO, NE, SO, SE, y su atajo con geoblender.ui_call_pie."""
        rows = bs_tables.tables(bs_tables.section(docs.read(AR_RELPATH),
                                                  "## 4. Menús circulares"))[0]
        self.assertEqual(len(rows), len(self.cat.pies))
        pie_shortcuts = {s.key.partition("name=")[2]: s for s in self.cat.shortcuts()
                         if s.idname == "geoblender.ui_call_pie"}
        for cells in rows:
            (pie_id,) = bs_tables.backticked(cells[1])
            pie = self.cat.pies[pie_id]
            with self.subTest(pie=pie_id):
                for text, key in zip(cells[2:], pie.slots, strict=True):
                    label = self.cat.commands[key].label_es
                    shorter, longer = sorted((words(text), words(label)), key=len)
                    self.assertLessEqual(shorter, longer, f"«{text}» frente a «{label}»")
                mods, event = parse_combo(cells[0])
                shortcut = pie_shortcuts[pie_id]
                self.assertEqual((shortcut.event, shortcut.shift, shortcut.alt),
                                 (event, "shift" in mods, "alt" in mods))

    def test_contexts_match_pc(self) -> None:
        """RF-003-17 (PC §3): cada menú «<Tipo> ▾» tiene los comandos que nombra su fila 1
        (los suyos o el submenú de variantes que los agrupa)."""
        text = docs.read(PC_RELPATH)
        found = 0
        for table in bs_tables.tables(bs_tables.section(text, "## 3. Contenido por tipo de objeto")):
            for cells in table:
                if not cells[0].startswith("Fila 1"):
                    continue
                (menu_id,) = bs_tables.backticked(cells[0])
                (context,) = [c for c in self.cat.contexts.values() if c.id == menu_id]
                have: set[str] = set()
                for item in context.items:
                    if item.key:
                        command = self.cat.commands[item.key]
                        have |= {short(command.idname), *command.doc_id}
                with self.subTest(menu=menu_id):
                    self.assertLessEqual(set(bs_tables.identifiers(cells[1])), have)
                found += 1
        self.assertEqual(found, 14)  # la 14.ª, «Diferencia ▾» (spec 011, T31)

    def test_layouts_match_cw(self) -> None:
        """RF-003-16 (CW §6.1 y §6.2): la principal «Geoblender» y las 6 opcionales con su
        espacio de trabajo y su entrada."""
        text = docs.read(CW_RELPATH)
        rows = bs_tables.tables(bs_tables.section(text, "### 6.2 Disposiciones opcionales"))[0]
        expected = {(cells[0], bs_tables.normalize_entry(cells[3])) for cells in rows}
        actual = {(layout.workspace, layout.entry) for layout in self.cat.layouts
                  if not layout.main}
        self.assertEqual(actual, expected)
        main_name = re.search(r"^### 6\.1 Disposición principal: «([^»]+)»", text,
                              flags=re.MULTILINE)
        (main,) = [layout for layout in self.cat.layouts if layout.main]
        self.assertEqual(main.workspace, main_name.group(1))

    def test_roadmap_ids(self) -> None:
        """RF-003-07: todo R-id del catálogo existe en ``docs/producto/roadmap.md``."""
        roadmap = frozenset(re.findall(r"^\| (R-\d{2}) \|", docs.read(docs.ROADMAP_RELPATH),
                                       flags=re.MULTILINE))
        self.assertGreater(len(roadmap), 70)
        issues = [issue for issue in catalog.validate(self.cat, roadmap_ids=roadmap)
                  if "roadmap" in issue.message]
        self.assertEqual([str(issue) for issue in issues], [])
        used = {command.entry for command in self.cat.commands.values()
                if command.entry.startswith("R-")}
        self.assertLessEqual(used, roadmap)

    def test_closed_specs_have_real_classes(self) -> None:
        """BS §7.2, prueba 4: ningún comando de una spec «Cerrada» en ``specs/README.md``
        sigue siendo provisional: su operador está en ``geoblender/bl/``."""
        closed = set(re.findall(r"^\| (\d{3}) \|.*\| Cerrada[^|]*\|\s*$",
                                docs.read(docs.SPECS_INDEX_RELPATH), flags=re.MULTILINE))
        self.assertIn("001", closed)
        defined = bl_idnames()
        missing = sorted(command.key for command in self.cat.commands.values()
                         if command.entry in closed and command.kind in ("operator", "internal")
                         and command.idname not in defined)
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
