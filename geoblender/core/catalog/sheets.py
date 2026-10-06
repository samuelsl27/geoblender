# SPDX-License-Identifier: GPL-3.0-or-later
"""Hojas de ayuda generadas del catálogo de comandos: atajos, alias de la línea de
comandos y glosario de términos de otros programas (spec 003; RF-003-27; AT §1, regla 8:
la hoja de atajos no se escribe a mano; BS §7.1).

Cada hoja es una lista de :class:`SheetRow` con sus columnas ya en el idioma pedido;
:func:`render_html` la convierte en una página HTML imprimible (``bl/ui`` la escribe en la
carpeta de datos de la extensión y la abre en el navegador; plan 003 DT12). Los textos que
no son del catálogo (títulos de columna, nombres de teclas y de mapas) están en
``core/i18n/messages.toml``. Puro: no importa ``bpy``.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from dataclasses import dataclass

from ..i18n import translate
from .schema import Catalog, Shortcut
from .search import path_text

# Teclas con nombre propio en la hoja (``msgid`` en inglés); las demás, su letra o su
# número.
KEY_NAMES = {
    "PAGE_UP": "Page Up",
    "PAGE_DOWN": "Page Down",
    "HOME": "Home",
    "NUMPAD_PLUS": "Numpad +",
    "NUMPAD_MINUS": "Numpad −",
}
DIGITS = ("ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE")
KEYMAP_NAMES = {"Window": "Window", "3D View": "3D View"}
SHEETS = {
    "shortcuts": ("Geoblender shortcuts", ("Shortcut", "Action", "Where", "Entry", "Keymap")),
    "aliases": ("Command line aliases", ("Alias", "Command", "Where", "Entry")),
    "glossary": ("Glossary", ("Program", "Term", "Standard term", "Where")),
}


@dataclass(frozen=True)
class SheetRow:
    """Una fila de una hoja: el comando al que se refiere y sus columnas, en el idioma
    pedido."""

    key: str
    columns: tuple[str, ...]


def sheet_title(kind: str, language: str) -> str:
    """El título de una hoja (``shortcuts``, ``aliases`` o ``glossary``)."""
    return translate(language, SHEETS[kind][0])


def sheet_headers(kind: str, language: str) -> tuple[str, ...]:
    """Los títulos de las columnas de una hoja."""
    return tuple(translate(language, header) for header in SHEETS[kind][1])


def combination(shortcut: Shortcut, language: str) -> str:
    """La combinación como la lee una persona: «Ctrl+Mayús+F5», «Alt+Num −»; en
    inglés, «Shift»."""
    parts = [name for name, on in (("Ctrl", shortcut.ctrl), (translate(language, "Shift"),
                                                            shortcut.shift),
                                   ("Alt", shortcut.alt)) if on]
    event = shortcut.event
    if event in KEY_NAMES:
        key = translate(language, KEY_NAMES[event])
    elif event in DIGITS:
        key = str(DIGITS.index(event))
    else:
        key = event
    return "+".join([*parts, key])


def _label(cat: Catalog, key: str, language: str) -> str:
    command = cat.commands[key]
    return command.label if language == "en" else command.label_es


def shortcut_rows(cat: Catalog, language: str) -> list[SheetRow]:
    """Una fila por atajo, en el orden del catálogo (el de AT §2): combinación, acción,
    dónde está en la barra, entrada y mapa."""
    rows: list[SheetRow] = []
    for shortcut in cat.shortcuts():
        command = cat.commands.get(shortcut.key)
        if command is not None:
            action = _label(cat, shortcut.key, language)
        else:
            action = shortcut.label if language == "en" else shortcut.label_es
        # Dónde y entrada: los del comando; de una variante solo de atajo, el menú de los
        # comandos con el mismo operador; de un envoltorio interno, los del menú o panel
        # que abre.
        target, parent = command, False
        if target is None:
            name = dict(part.split("=", 1) for part in shortcut.key.partition("?")[2].split("&")
                        if "=" in part).get("name")
            if name in cat.commands:
                target = cat.commands[name]
            else:
                homed = [c for c in cat.by_idname(shortcut.idname) if c.home]
                target, parent = (homed[0] if homed else None), True
        where = (path_text(cat, target.key, language, parent=parent)
                 if target is not None and target.home else "")
        entry = target.entry if target is not None else ""
        keymap = translate(language, KEYMAP_NAMES.get(shortcut.keymap, shortcut.keymap))
        rows.append(SheetRow(shortcut.key, (combination(shortcut, language), action, where,
                                            entry, keymap)))
    return rows


def alias_rows(cat: Catalog, language: str) -> list[SheetRow]:
    """Un alias por fila con su comando, dónde está y su entrada, por orden alfabético."""
    rows = [
        SheetRow(command.key, (alias, _label(cat, command.key, language),
                               path_text(cat, command.key, language) if command.home else "",
                               command.entry))
        for command in cat.commands.values()
        for alias in command.aliases
    ]
    return sorted(rows, key=lambda row: (row.columns[0].casefold(), row.columns[1].casefold()))


def glossary_rows(cat: Catalog, language: str) -> list[SheetRow]:
    """Un término de otro programa por fila con su término estándar (la etiqueta del
    comando) y dónde está, por programa y término."""
    rows = [
        SheetRow(command.key, (program, term, _label(cat, command.key, language),
                               path_text(cat, command.key, language) if command.home else ""))
        for command in cat.commands.values()
        for program, term in command.jargon
    ]
    return sorted(rows, key=lambda row: (row.columns[0].casefold(), row.columns[1].casefold(),
                                         row.columns[2].casefold()))


STYLE = """\
body { font-family: "Segoe UI", Arial, sans-serif; font-size: 10pt; margin: 1.5em; }
h1 { font-size: 14pt; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #999; padding: 2px 6px; text-align: left; vertical-align: top; }
th { background: #e6e6e6; }
@media print {
  body { margin: 0; font-size: 9pt; }
  tr { page-break-inside: avoid; }
}"""


def render_html(title: str, rows: Sequence[SheetRow], *, headers: Sequence[str] = (),
                language: str = "es") -> str:
    """Una página HTML imprimible con ``title`` y una tabla de ``rows`` (texto escapado)."""
    esc = html.escape
    lines = [
        "<!DOCTYPE html>",
        f'<html lang="{esc(language)}">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{esc(title)}</title>",
        f"<style>\n{STYLE}\n</style>",
        "</head>",
        "<body>",
        f"<h1>{esc(title)}</h1>",
        "<table>",
    ]
    if headers:
        cells = "".join(f"<th>{esc(header)}</th>" for header in headers)
        lines.append(f"<thead><tr>{cells}</tr></thead>")
    lines.append("<tbody>")
    for row in rows:
        cells = "".join(f"<td>{esc(cell)}</td>" for cell in row.columns)
        lines.append(f"<tr>{cells}</tr>")
    lines += ["</tbody>", "</table>", "</body>", "</html>"]
    return "\n".join(lines) + "\n"
