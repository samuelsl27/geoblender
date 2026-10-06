# SPDX-License-Identifier: GPL-3.0-or-later
"""Lectura del catálogo de comandos desde ``data/**/*.toml`` (spec 003; RF-003-06; plan
003 §5.1 y §5.2).

Ficheros (los de ``menus/`` primero, en orden de nombre, y después los demás):

- ``menus/NN_<tema>.toml``: un menú de la barra (``[[menu]]`` con su etiqueta, su etapa,
  su paso y su rama) con sus grupos (``[[menu.group]]``) y elementos
  (``[[menu.group.item]]``). Un elemento es la **definición** de un comando (``key`` y sus
  campos; si es un submenú, sus elementos en ``[[menu.group.item.item]]``), un acceso
  cruzado ↗ (``ref``), un espejo (``mirror``) o un separador (``separator = true``).
- ``io_hubs.toml`` y ``common.toml``: menús cuyo contenido se define aparte de su casa
  (``[[menu]]`` sin ``label``: Importar ▸, Exportar ▸, QGIS ▸) o que no tienen casa en la
  barra (``[[menu]]`` con ``label``: Datos ▾, «Geoblender ▾»), y comandos sin casa
  (``[[command]]``: paneles, nativos del acceso rápido y auxiliares internos).
- ``quick_access.toml`` (``[[project]]``, ``[[view]]``, ``[groups]``), ``pies.toml``
  (``[[pie]]``), ``contexts.toml`` (``[[context]]``), ``shortcuts.toml``
  (``[[shortcut]]``), ``layouts.toml`` (``[[layout]]``) y ``entries.toml`` (una tabla por
  spec o R-id: ``["R-38"]`` con ``title`` y ``delivered``).

Lo que no se puede leer o resolver (TOML roto, campo desconocido, clave duplicada o con
dos casas) queda en ``Catalog.load_issues`` con su fichero, clave y campo; la
validación de :func:`core.catalog.schema.validate` los incluye. Puro: no importa ``bpy``.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .schema import (
    PIE_SLOTS,
    Catalog,
    CatalogIssue,
    Command,
    ContextSpec,
    EntryRef,
    Group,
    LayoutSpec,
    MenuItem,
    MenuSpec,
    PieSpec,
    QuickAccessItem,
    Shortcut,
    kind_for,
    make_key,
    module_of,
    split_key,
)

__all__ = ["load_catalog", "make_key", "split_key"]

DATA_DIR = Path(__file__).with_name("data")
MENUS_DIR = "menus"
ENTRIES_FILE = "entries.toml"

COMMAND_FIELDS = frozenset({
    "key", "kind", "label", "description", "module", "entry", "action", "background",
    "frequency", "icon", "icon_fallback", "aliases", "jargon", "dynamic", "doc_id", "item",
})
MENU_FIELDS = frozenset({
    "id", "label", "description", "stage", "step", "branch", "icon", "icon_fallback",
    "entry", "action", "frequency", "aliases", "jargon", "group", "kind", "dynamic",
})
ITEM_FIELDS = frozenset({"ref", "mirror", "separator"})
QUICK_FIELDS = frozenset({
    "key", "group", "display", "extra", "compact_step", "fold_step", "edit_modes",
    "width_text",
})
PIE_FIELDS = frozenset({"id", "label", "description", "entry", "icon", "icon_fallback",
                        *PIE_SLOTS})
CONTEXT_FIELDS = frozenset({"kind", "id", "label", "description", "entry", "item", "icon"})
CONTEXT_ITEM_FIELDS = frozenset({"ref", "placeholder", "entry", "separator"})
SHORTCUT_FIELDS = frozenset({"key", "keymap", "event", "ctrl", "shift", "alt", "label"})
LAYOUT_FIELDS = frozenset({"id", "workspace", "label", "description", "entry", "main"})
ENTRY_FIELDS = frozenset({"title", "delivered"})
TOP_LEVEL = frozenset({"menu", "command", "project", "view", "groups", "pie", "context",
                       "shortcut", "layout"})
_LINE_RE = re.compile(r"at line (\d+)")


@dataclass
class _Raw:
    """Lo leído hasta ahora: los comandos en orden y lo demás, antes de congelarlo."""

    commands: dict[str, Command] = field(default_factory=dict)
    menus: dict[str, dict[str, Any]] = field(default_factory=dict)
    top_menus: list[str] = field(default_factory=list)
    quick: list[QuickAccessItem] = field(default_factory=list)
    quick_groups: dict[str, tuple[str, str]] = field(default_factory=dict)
    pies: dict[str, PieSpec] = field(default_factory=dict)
    contexts: dict[str, ContextSpec] = field(default_factory=dict)
    shortcuts: list[Shortcut] = field(default_factory=list)
    entries: dict[str, EntryRef] = field(default_factory=dict)
    layouts: list[LayoutSpec] = field(default_factory=list)
    issues: list[CatalogIssue] = field(default_factory=list)


class _Reader:
    def __init__(self, raw: _Raw, source: str) -> None:
        self.raw = raw
        self.source = source

    def issue(self, key: str, field_name: str, value: object, message: str) -> None:
        self.raw.issues.append(CatalogIssue(self.source, key, field_name, str(value), message))

    # Campos ----------------------------------------------------------------------------

    def unknown(self, table: Mapping[str, Any], allowed: frozenset[str], key: str) -> None:
        for name in table:
            if name not in allowed:
                self.issue(key, name, "", f"campo desconocido (se esperan: {', '.join(sorted(allowed))})")

    def text(self, table: Mapping[str, Any], name: str, key: str) -> tuple[str, str]:
        """(inglés, español) de un campo ``{en = "…", es = "…"}``; ("", "") si falta."""
        value = table.get(name)
        if value is None:
            return "", ""
        if not isinstance(value, Mapping) or set(value) - {"en", "es"}:
            self.issue(key, name, value, "se escribe {en = \"…\", es = \"…\"}")
            return "", ""
        english, spanish = value.get("en", ""), value.get("es", "")
        if not isinstance(english, str) or not isinstance(spanish, str):
            self.issue(key, name, value, "los textos son cadenas")
            return "", ""
        return english, spanish

    def string(self, table: Mapping[str, Any], name: str, key: str, default: str = "") -> str:
        value = table.get(name, default)
        if not isinstance(value, str):
            self.issue(key, name, value, "se espera un texto")
            return default
        return value

    def boolean(self, table: Mapping[str, Any], name: str, key: str) -> bool:
        value = table.get(name, False)
        if not isinstance(value, bool):
            self.issue(key, name, value, "se espera true o false")
            return False
        return value

    def integer(self, table: Mapping[str, Any], name: str, key: str,
                default: int | None) -> int | None:
        value = table.get(name, default)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
            self.issue(key, name, value, "se espera un número entero")
            return default
        return value

    def strings(self, table: Mapping[str, Any], name: str, key: str) -> tuple[str, ...]:
        value = table.get(name, [])
        if isinstance(value, str):
            return (value,)
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            self.issue(key, name, value, "se espera una lista de textos")
            return ()
        return tuple(value)

    def tables(self, table: Mapping[str, Any], name: str, key: str) -> list[Mapping[str, Any]]:
        value = table.get(name, [])
        if not isinstance(value, list) or not all(isinstance(v, Mapping) for v in value):
            self.issue(key, name, "", "se espera una lista de tablas ([[…]])")
            return []
        return value

    # Comandos --------------------------------------------------------------------------

    def command(self, table: Mapping[str, Any], *, key: str, home: str, group: str,
                fields: frozenset[str] = COMMAND_FIELDS, kind: str | None = None) -> Command | None:
        # Un menú sin «action» es un submenú (S).
        """Define un comando; si la clave ya estaba, lo anota (clave duplicada o dos
        casas) y conserva la primera definición."""
        self.unknown(table, fields, key)
        try:
            idname, props = split_key(key)
        except ValueError as exc:
            self.issue(key, "key", key, str(exc))
            return None
        label, label_es = self.text(table, "label", key)
        description, description_es = self.text(table, "description", key)
        jargon_raw = table.get("jargon", [])
        jargon: list[tuple[str, str]] = []
        if not isinstance(jargon_raw, list):
            self.issue(key, "jargon", jargon_raw, "se espera una lista de [programa, término]")
        else:
            for pair in jargon_raw:
                if (isinstance(pair, list) and len(pair) == 2
                        and all(isinstance(part, str) for part in pair)):
                    jargon.append((pair[0], pair[1]))
                else:
                    self.issue(key, "jargon", pair, "cada término es [programa, término]")
        icon = table.get("icon")
        if icon is not None and not isinstance(icon, str):
            self.issue(key, "icon", icon, "se espera un texto")
            icon = None
        frequency = self.integer(table, "frequency", key, 1)
        command = Command(
            key=key,
            idname=idname,
            kind=kind or self.string(table, "kind", key, kind_for(key)),
            props=props,
            label=label,
            label_es=label_es,
            description=description,
            description_es=description_es,
            module=self.string(table, "module", key, module_of(idname)),
            entry=self.string(table, "entry", key),
            action=self.string(table, "action", key,
                               "S" if (kind or kind_for(key)) == "menu" else ""),
            background=self.boolean(table, "background", key),
            frequency=1 if frequency is None else frequency,
            icon=icon,
            icon_fallback=self.string(table, "icon_fallback", key, "NONE"),
            aliases=self.strings(table, "aliases", key),
            jargon=tuple(jargon),
            home=home,
            home_group=group,
            order=len(self.raw.commands),
            source=self.source,
            dynamic=self.boolean(table, "dynamic", key),
            doc_id=self.strings(table, "doc_id", key),
        )
        previous = self.raw.commands.get(key)
        if previous is not None:
            if previous.home != home:
                self.issue(key, "key", key,
                           f"dos casas: ya está definido en {previous.home or 'sin casa'} "
                           f"({previous.source}) y aquí en {home or 'sin casa'}; un comando "
                           "tiene una sola casa y los demás sitios lo referencian (ref)")
            else:
                self.issue(key, "key", key,
                           f"clave duplicada: ya está definida en {previous.source}")
            return None
        self.raw.commands[key] = command
        return command

    def item(self, table: Mapping[str, Any], *, menu: str, group: str) -> MenuItem | None:
        """Un elemento de un menú: definición, ``ref`` (↗), ``mirror`` o separador."""
        if table.get("separator") is True:
            self.unknown(table, frozenset({"separator"}), menu)
            return MenuItem(separator=True)
        for name, cross in (("ref", True), ("mirror", False)):
            if name in table:
                self.unknown(table, ITEM_FIELDS, menu)
                target = self.string(table, name, menu)
                return MenuItem(key=target, cross=cross) if target else None
        key = table.get("key")
        if not isinstance(key, str) or not key:
            self.issue(menu, "item", "", "cada elemento lleva key, ref, mirror o separator")
            return None
        command = self.command(table, key=key, home=menu, group=group)
        if "item" in table:
            items = [self.item(sub, menu=key, group="")
                     for sub in self.tables(table, "item", key)]
            self.menu_content(key, [("", "", items)], parent=menu)
        return MenuItem(key=key) if command is not None or key in self.raw.commands else None

    def menu_content(self, menu_id: str, groups: Sequence[tuple[str, str, list[MenuItem | None]]],
                     *, parent: str, extra: Mapping[str, Any] | None = None) -> None:
        if menu_id in self.raw.menus:
            self.issue(menu_id, "id", menu_id, "el contenido de este menú ya está definido en "
                       f"{self.raw.menus[menu_id]['source']}")
            return
        self.raw.menus[menu_id] = {
            "groups": tuple(Group(label, label_es, tuple(i for i in items if i is not None))
                            for label, label_es, items in groups),
            "parent": parent,
            "source": self.source,
            **(extra or {}),
        }

    def menu(self, table: Mapping[str, Any], *, top: bool) -> None:
        menu_id = self.string(table, "id", "")
        if not menu_id:
            self.issue("", "id", "", "cada [[menu]] lleva su id (la clase del menú)")
            return
        self.unknown(table, MENU_FIELDS, menu_id)
        if "label" in table:
            self.command(
                {k: v for k, v in table.items()
                 if k not in ("id", "group", "stage", "step", "branch")},
                key=menu_id, home="", group="", kind="menu",
            )
        stage, stage_es = self.text(table, "stage", menu_id)
        groups: list[tuple[str, str, list[MenuItem | None]]] = []
        for group in self.tables(table, "group", menu_id):
            self.unknown(group, frozenset({"label", "item"}), menu_id)
            label, label_es = self.text(group, "label", menu_id)
            items = [self.item(sub, menu=menu_id, group=label)
                     for sub in self.tables(group, "item", menu_id)]
            groups.append((label, label_es, items))
        branch = self.string(table, "branch", menu_id)
        self.menu_content(menu_id, groups, parent="", extra={
            "stage": stage, "stage_es": stage_es,
            "step": self.integer(table, "step", menu_id, None), "branch": branch,
        })
        if top:
            self.raw.top_menus.append(menu_id)

    # Espejos, atajos, entradas y disposiciones -----------------------------------------

    def quick_access(self, data: Mapping[str, Any]) -> None:
        groups = data.get("groups", {})
        if not isinstance(groups, Mapping):
            self.issue("", "groups", "", "se espera una tabla id = {en, es}")
            groups = {}
        for group_id, value in groups.items():
            english, spanish = self.text({"label": value}, "label", group_id)
            self.raw.quick_groups[group_id] = (english, spanish)
        for scope in ("project", "view"):
            for order, table in enumerate(self.tables(data, scope, scope)):
                key = self.string(table, "key", scope)
                self.unknown(table, QUICK_FIELDS, key)
                group = self.string(table, "group", key, scope)
                if scope == "view" and group not in self.raw.quick_groups:
                    self.issue(key, "group", group, "grupo sin rótulo en [groups]")
                extra = table.get("extra")
                self.raw.quick.append(QuickAccessItem(
                    key=key, scope=scope, group=group, order=order,
                    display=self.string(table, "display", key, "icon"),
                    extra=extra if isinstance(extra, str) else None,
                    compact_step=self.integer(table, "compact_step", key, None),
                    fold_step=self.integer(table, "fold_step", key, None),
                    edit_modes=self.boolean(table, "edit_modes", key),
                    width_text=self.string(table, "width_text", key),
                    source=self.source,
                ))

    def pie(self, table: Mapping[str, Any]) -> None:
        pie_id = self.string(table, "id", "")
        self.unknown(table, PIE_FIELDS, pie_id)
        self.command({k: v for k, v in table.items() if k not in (*PIE_SLOTS, "id")},
                     key=pie_id, home="", group="", kind="menu")
        slots = tuple(self.string(table, slot, pie_id) for slot in PIE_SLOTS)
        self.raw.pies[pie_id] = PieSpec(pie_id, tuple(s for s in slots if s), self.source)

    def context_items(self, tables: list[Mapping[str, Any]], owner: str) -> tuple[MenuItem, ...]:
        items: list[MenuItem] = []
        for table in tables:
            self.unknown(table, CONTEXT_ITEM_FIELDS, owner)
            if table.get("separator") is True:
                items.append(MenuItem(separator=True))
            elif "ref" in table:
                items.append(MenuItem(key=self.string(table, "ref", owner)))
            elif "placeholder" in table:
                english, spanish = self.text(table, "placeholder", owner)
                items.append(MenuItem(placeholder=(english, spanish),
                                      entry=self.string(table, "entry", owner)))
            else:
                self.issue(owner, "item", "", "cada elemento lleva ref, placeholder o separator")
        return tuple(items)

    def context(self, table: Mapping[str, Any]) -> None:
        context_id = self.string(table, "id", "")
        self.unknown(table, CONTEXT_FIELDS, context_id)
        self.command({k: v for k, v in table.items() if k in ("label", "description", "entry")},
                     key=context_id, home="", group="", kind="menu")
        kind = self.string(table, "kind", context_id)
        if kind in self.raw.contexts:
            self.issue(context_id, "kind", kind, "ya hay un menú contextual para este tipo")
            return
        self.raw.contexts[kind] = ContextSpec(
            kind=kind,
            id=context_id,
            items=self.context_items(self.tables(table, "item", context_id), context_id),
            icons=self.context_items(self.tables(table, "icon", context_id), context_id),
            source=self.source,
        )

    def shortcut(self, table: Mapping[str, Any]) -> None:
        key = self.string(table, "key", "")
        self.unknown(table, SHORTCUT_FIELDS, key)
        label, label_es = self.text(table, "label", key)
        self.raw.shortcuts.append(Shortcut(
            key=key,
            keymap=self.string(table, "keymap", key),
            event=self.string(table, "event", key),
            ctrl=self.boolean(table, "ctrl", key),
            shift=self.boolean(table, "shift", key),
            alt=self.boolean(table, "alt", key),
            label=label,
            label_es=label_es,
            source=self.source,
        ))

    def entries(self, data: Mapping[str, Any]) -> None:
        for entry_id, table in data.items():
            if not isinstance(table, Mapping):
                self.issue(entry_id, "entry", table, "cada entrada es una tabla [\"id\"]")
                continue
            self.unknown(table, ENTRY_FIELDS, entry_id)
            title, title_es = self.text(table, "title", entry_id)
            self.raw.entries[entry_id] = EntryRef(entry_id, title, title_es,
                                                  self.boolean(table, "delivered", entry_id),
                                                  self.source)

    def layout(self, table: Mapping[str, Any]) -> None:
        layout_id = self.string(table, "id", "")
        self.unknown(table, LAYOUT_FIELDS, layout_id)
        label, label_es = self.text(table, "label", layout_id)
        description, description_es = self.text(table, "description", layout_id)
        self.raw.layouts.append(LayoutSpec(
            id=layout_id,
            workspace=self.string(table, "workspace", layout_id),
            label=label, label_es=label_es,
            description=description, description_es=description_es,
            entry=self.string(table, "entry", layout_id),
            main=self.boolean(table, "main", layout_id),
            source=self.source,
        ))

    def read(self, data: Mapping[str, Any], *, top: bool) -> None:
        if self.source == ENTRIES_FILE:
            self.entries(data)
            return
        for name in data:
            if name not in TOP_LEVEL:
                self.issue("", name, "", f"tabla desconocida (se esperan: {', '.join(sorted(TOP_LEVEL))})")
        for table in self.tables(data, "menu", ""):
            self.menu(table, top=top)
        for table in self.tables(data, "command", ""):
            key = self.string(table, "key", "")
            if key:
                self.command(table, key=key, home="", group="")
        if "project" in data or "view" in data or "groups" in data:
            self.quick_access(data)
        for table in self.tables(data, "pie", ""):
            self.pie(table)
        for table in self.tables(data, "context", ""):
            self.context(table)
        for table in self.tables(data, "shortcut", ""):
            self.shortcut(table)
        for table in self.tables(data, "layout", ""):
            self.layout(table)


def _files(data_dir: Path) -> Iterator[tuple[str, Path, bool]]:
    """(ruta relativa, ruta, es un menú de la barra) de cada fichero, en orden."""
    for path in sorted((data_dir / MENUS_DIR).glob("*.toml")):
        yield f"{MENUS_DIR}/{path.name}", path, True
    for path in sorted(data_dir.glob("*.toml")):
        yield path.name, path, False


def _toml_issue(source: str, text: str, exc: Exception) -> CatalogIssue:
    match = _LINE_RE.search(str(exc))
    line = ""
    if match:
        lines = text.splitlines()
        number = int(match.group(1))
        if 0 < number <= len(lines):
            line = lines[number - 1].strip()
    return CatalogIssue(source, "", "toml", line, f"TOML no válido: {exc}")


def load_catalog(data_dir: Path = DATA_DIR) -> Catalog:
    """Lee el catálogo de ``data_dir`` (sin caché: ``core.catalog.load`` la tiene)."""
    raw = _Raw()
    for source, path, top in _files(Path(data_dir)):
        try:
            text = path.read_bytes().decode("utf-8")
            data = tomllib.loads(text)
        except (OSError, UnicodeDecodeError) as exc:
            raw.issues.append(CatalogIssue(source, "", "toml", "", f"no se puede leer: {exc}"))
            continue
        except tomllib.TOMLDecodeError as exc:
            raw.issues.append(_toml_issue(source, text, exc))
            continue
        _Reader(raw, source).read(data, top=top)
    menus: dict[str, MenuSpec] = {}
    for menu_id, spec in raw.menus.items():
        owner = raw.commands.get(menu_id)
        parent = spec["parent"] or (owner.home if owner else "")
        menus[menu_id] = MenuSpec(
            id=menu_id,
            groups=spec["groups"],
            parent=parent,
            stage=spec.get("stage", ""),
            stage_es=spec.get("stage_es", ""),
            step=spec.get("step"),
            branch=spec.get("branch", ""),
            source=spec["source"],
        )
    by_idname: dict[str, list[Command]] = {}
    for command in raw.commands.values():
        by_idname.setdefault(command.idname, []).append(command)
    return Catalog(
        commands=raw.commands,
        menus=menus,
        top_menus=tuple(raw.top_menus),
        quick_access_items=tuple(raw.quick),
        quick_access_groups=raw.quick_groups,
        pies=raw.pies,
        contexts=raw.contexts,
        shortcut_list=tuple(raw.shortcuts),
        entries=raw.entries,
        layouts=tuple(raw.layouts),
        load_issues=tuple(raw.issues),
        _by_idname={idname: tuple(commands) for idname, commands in by_idname.items()},
    )
