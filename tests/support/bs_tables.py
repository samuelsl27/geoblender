# SPDX-License-Identifier: GPL-3.0-or-later
"""Lectura del árbol de menús de BS §8 (``docs/arquitectura/interfaz/barra-superior.md``)
para comprobar el catálogo de comandos contra él (spec 003, T04–T07; RF-003-06).

BS §8 tiene una tabla por menú (y por submenú de Herramientas y concentrador), con las
columnas Comando · ``bl_idname`` · Mód. · Entrada · Tipo · Frec. (algunas tablas no tienen
Mód., Entrada o Frec.: su entrada y su módulo van en el rótulo, «todo R-16», «módulo
``ui``»). Cada fila es un rótulo de grupo (en negrita), un separador («—»; «↳ —» dentro de
un submenú) o un comando, con «↳» si es de un submenú y «↗» si es un acceso cruzado. Los
menús Comprobar ▸, Trabajos ▸, Disposición ▸ y Datos ▾ son listas en prosa
(:class:`ProseList`).

Para las demás tablas de ``docs/arquitectura/interfaz/`` (AT §2, AR §2–§4, PC §3, CW
§6.2; spec 003, T08): :func:`section`, :func:`tables` (con la barra escapada dentro de una celda),
:func:`backticked` e :func:`identifiers`.

Python puro, sin ``geoblender``: devuelve lo que dice el documento, normalizado (ver
:class:`DocRow`); la comparación la hace la prueba.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SECTION_START = "## 8. Árbol completo"
SECTION_END = "## 9. "
_CLASS_RE = re.compile(r"`((?:GEOBLENDER|TOPBAR)_[A-Z]{2}_[a-z0-9_]+)`")
_ENTRY_RE = re.compile(r"\b(\d{3}|R-\d{2}|Blender)\b")
_TOKEN_RE = re.compile(r"\(|\)|`[^`]+`")
_ID_RE = re.compile(r"^(GEOBLENDER_[A-Z]{2}_[a-z0-9_]+|TOPBAR_MT_[a-z_]+|[a-z]+_[a-z0-9_]+|"
                    r"[a-z0-9_]+\.[a-z0-9_.]+)$")
_SHORTCUT_RE = re.compile(r"\s*\((?:Mayús|Ctrl|Alt|F\d)[^)]*\)")
_TYPE_RE = re.compile(r"\b([ADPHST])(·2p)?\)\s*\.?\s*$")


@dataclass(frozen=True)
class DocRow:
    """Una fila de una tabla de BS §8.

    ``kind``: ``group`` (rótulo, en ``text``), ``separator`` o ``command``. ``ids``: los
    identificadores fuera de paréntesis de la columna ``bl_idname`` (sin el prefijo
    ``geoblender.``); ``props``: los de dentro (``view='PLAN'``, ``'NORTH'``, ``mode``).
    ``module``, ``entry`` y ``frequency`` son ``None`` si la tabla no tiene esa columna;
    la entrada «—» es ``""``. ``action``: la letra del tipo (A, D, P, H, S, T, sin lo que va
    tras «→»); ``background``: «·2p».
    """

    kind: str
    line: int
    text: str = ""
    sub: bool = False
    cross: bool = False
    ids: tuple[str, ...] = ()
    props: tuple[str, ...] = ()
    module: str | None = None
    entry: str | None = None
    action: str = ""
    background: bool = False
    frequency: int | None = None


@dataclass
class DocTable:
    """Una tabla de BS §8: el menú (su clase), su rótulo, sus filas y la entrada que su
    rótulo da a todas («todo R-16»)."""

    menu: str
    heading: str
    line: int
    rows: list[DocRow] = field(default_factory=list)
    default_entry: str | None = None


@dataclass(frozen=True)
class ProseItem:
    """Un elemento de una lista en prosa: su texto, si es ↗, sus identificadores, su
    entrada y su tipo."""

    text: str
    cross: bool
    ids: tuple[str, ...]
    entry: str | None
    action: str
    background: bool


@dataclass(frozen=True)
class ProseList:
    """Un menú de BS §8 escrito en prosa: Comprobar ▸, Trabajos ▸, Disposición ▸, Datos ▾."""

    menu: str
    line: int
    text: str
    items: tuple[ProseItem, ...]
    default_entry: str | None


@dataclass
class BsTree:
    tables: list[DocTable]
    prose: dict[str, ProseList]

    def table(self, menu: str) -> DocTable:
        for table in self.tables:
            if table.menu == menu:
                return table
        raise KeyError(menu)


def split_top(text: str, separator: str) -> list[str]:
    """``text`` partido por ``separator`` fuera de paréntesis y de comillas invertidas."""
    parts: list[str] = []
    depth = 0
    quoted = False
    current = ""
    index = 0
    while index < len(text):
        char = text[index]
        if char == "`":
            quoted = not quoted
        elif not quoted and char == "(":
            depth += 1
        elif not quoted and char == ")":
            depth = max(0, depth - 1)
        if not quoted and depth == 0 and text.startswith(separator, index):
            parts.append(current)
            current = ""
            index += len(separator)
            continue
        current += char
        index += 1
    parts.append(current)
    return [part.strip() for part in parts]


def scan_ids(cell: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(identificadores fuera de paréntesis, los de dentro) de una celda ``bl_idname``."""
    ids: list[str] = []
    props: list[str] = []
    depth = 0
    for token in _TOKEN_RE.findall(cell):
        if token == "(":
            depth += 1
        elif token == ")":
            depth = max(0, depth - 1)
        else:
            (props if depth else ids).append(token.strip("`"))
    return tuple(ids), tuple(props)


def normalize_entry(cell: str) -> str:
    match = _ENTRY_RE.search(cell)
    return match.group(1) if match else ""


def parse_type(cell: str) -> tuple[str, bool]:
    base = cell.split("→")[0].strip()
    return base.replace("·2p", "").strip(), "·2p" in base


def parse_frequency(cell: str) -> int | None:
    if "●" in cell:
        return cell.count("●")
    if "○" in cell:
        return 0
    return None


def group_label(cell: str) -> str:
    """El rótulo de un grupo («**Sólidos (Mayús+Alt+W)**» → «Sólidos»)."""
    match = re.match(r"\*\*(.+?)\*\*", cell)
    text = match.group(1) if match else cell
    return _SHORTCUT_RE.sub("", text).strip()


def list_count(text: str) -> int | None:
    """Cuántas opciones enumera la celda de un submenú de variantes: tras «): », las
    separadas por « · »; si no, las del paréntesis tras «▸»; o «1–4»."""
    if "): " in text:
        return len(split_top(text.split("): ", 1)[1], " · "))
    match = re.search(r"▸ (\d)–(\d)", text)
    if match:
        return int(match.group(2)) - int(match.group(1)) + 1
    match = re.search(r"▸ \(([^)]*)\)", text)
    if match:
        inner = match.group(1)
        parts = re.split(r", | · ", inner)
        return len(parts) if len(parts) > 1 else None
    return None


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _row(line_no: int, cells: list[str], columns: list[str], table: DocTable) -> DocRow:
    first = cells[0]
    rest = [cell for cell in cells[1:] if cell]
    sub = first.startswith("↳")
    body = first[1:].strip() if sub else first
    if first.startswith("**") and not rest:
        return DocRow("group", line_no, text=group_label(first))
    if body == "—" and not rest:
        return DocRow("separator", line_no, sub=sub)
    cross = body.startswith("↗")
    if cross:
        body = body[1:].strip()
    values = dict(zip(columns, cells, strict=False))
    ids, props = scan_ids(values.get("bl_idname", ""))
    entry: str | None
    if "Entrada" in values:
        entry = normalize_entry(values["Entrada"])
    elif "(Blender)" in values.get("bl_idname", ""):
        entry = "Blender"
    else:
        entry = table.default_entry
    module = values.get("Mód.")
    if module is not None:
        module = "" if module in ("—", "") else module
    action, background = parse_type(values.get("Tipo", ""))
    frequency = parse_frequency(values["Frec."]) if "Frec." in values else None
    return DocRow("command", line_no, text=body, sub=sub, cross=cross, ids=ids, props=props,
                  module=module, entry=entry, action=action, background=background,
                  frequency=frequency)


def _prose(menu: str, line_no: int, text: str, default_entry: str | None) -> ProseList:
    body = text.split("): ", 1)[1] if "): " in text else text
    body = body.split(". Son los mismos", 1)[0].rstrip(".")
    items: list[ProseItem] = []
    for part in split_top(body, " · "):
        cross = part.startswith("↗")
        ids = tuple(token.strip("`") for token in re.findall(r"`[^`]+`", part)
                    if _ID_RE.match(token.strip("`")) and "_" in token)
        inner = part[part.find("("):] if "(" in part else ""
        entry_match = _ENTRY_RE.search(inner)
        type_match = _TYPE_RE.search(part)
        items.append(ProseItem(
            text=part.lstrip("↗ ").strip(),
            cross=cross,
            ids=ids,
            entry=entry_match.group(1) if entry_match else default_entry,
            action=type_match.group(1) if type_match else "",
            background=bool(type_match and type_match.group(2)),
        ))
    return ProseList(menu, line_no, text, tuple(items), default_entry)


def parse(document: str) -> BsTree:
    """Las tablas y las listas en prosa de BS §8 de ``document``."""
    start = document.index(SECTION_START)
    end = document.index(SECTION_END, start)
    first_line = document.count("\n", 0, start) + 1
    lines = document[start:end].splitlines()
    tables: list[DocTable] = []
    prose: dict[str, ProseList] = {}
    current_menu = ""
    current_heading = ""
    current_entry: str | None = None
    table: DocTable | None = None
    columns: list[str] = []
    offset = 0
    while offset < len(lines):
        line = lines[offset]
        line_no = first_line + offset
        offset += 1
        if line.startswith("### "):
            match = _CLASS_RE.search(line)
            current_menu = match.group(1) if match else ""
            current_heading, current_entry, table = line, None, None
            continue
        if line.startswith("**") and ("▸**" in line or "▾**" in line):
            # Un párrafo que presenta un submenú: su tabla o su lista en prosa. Puede
            # ocupar varias líneas (hasta la línea en blanco).
            while (offset < len(lines) and lines[offset].strip()
                   and not lines[offset].startswith("|")):
                line += " " + lines[offset].strip()
                offset += 1
            match = _CLASS_RE.search(line)
            current_menu = match.group(1) if match else current_menu
            current_heading, table = line, None
            todo = re.search(r"todo (\d{3}|R-\d{2})", line)
            current_entry = todo.group(1) if todo else None
            if not line.rstrip().endswith(":") and "): " in line:
                prose[current_menu] = _prose(current_menu, line_no, line, current_entry)
            continue
        if not line.startswith("|"):
            if table is not None and line.strip():
                table = None
            continue
        cells = _cells(line)
        if cells[0] == "Comando":
            columns = ["Comando", *(
                "bl_idname" if "bl_idname" in cell else cell for cell in cells[1:])]
            if not current_menu:
                raise ValueError(f"línea {line_no}: tabla sin menú en su rótulo")
            table = DocTable(current_menu, current_heading, line_no,
                             default_entry=current_entry)
            tables.append(table)
            continue
        if set(line.replace("|", "").strip()) <= set("- "):
            continue
        if table is None:
            raise ValueError(f"línea {line_no}: fila fuera de una tabla")
        table.rows.append(_row(line_no, cells, columns, table))
    return BsTree(tables, prose)


# Otras tablas de docs/arquitectura/interfaz/ (AT, AR, PC, CW): filas como listas de celdas.


def split_cells(line: str) -> list[str]:
    r"""Las celdas de una fila de una tabla Markdown («\|» es una barra dentro de una
    celda)."""
    body = line.strip()
    body = body[1:] if body.startswith("|") else body
    body = body[:-1] if body.endswith("|") and not body.endswith("\\|") else body
    cells: list[str] = []
    current = ""
    index = 0
    while index < len(body):
        if body.startswith("\\|", index):
            current += "|"
            index += 2
            continue
        if body[index] == "|":
            cells.append(current.strip())
            current = ""
        else:
            current += body[index]
        index += 1
    cells.append(current.strip())
    return cells


def section(document: str, heading: str) -> str:
    """El texto de la sección que empieza en la línea ``heading`` (hasta la siguiente del
    mismo nivel o superior)."""
    start = document.index(heading)
    level = len(heading) - len(heading.lstrip("#"))
    rest = document[start + len(heading):]
    for match in re.finditer(r"^(#+) ", rest, flags=re.MULTILINE):
        if len(match.group(1)) <= level:
            return document[start:start + len(heading) + match.start()]
    return document[start:]


def tables(text: str) -> list[list[list[str]]]:
    """Las tablas de ``text``: cada una, sus filas de datos (sin cabecera ni separador)."""
    found: list[list[list[str]]] = []
    current: list[list[str]] | None = None
    header_seen = False
    for line in text.splitlines():
        if not line.startswith("|"):
            current, header_seen = None, False
            continue
        cells = split_cells(line)
        if current is None:
            current = []
            found.append(current)
            header_seen = False
            continue  # cabecera
        if not header_seen and set("".join(cells)) <= set("-: "):
            header_seen = True
            continue
        current.append(cells)
    return found


def backticked(cell: str) -> list[str]:
    """Los textos entre comillas invertidas de una celda, en orden."""
    return [token.strip("`") for token in re.findall(r"`[^`]+`", cell)]


def identifiers(cell: str) -> list[str]:
    """Los identificadores de comando (``bl_idname`` sin prefijo, clases, nativos) de una
    celda: los textos entre comillas invertidas que lo parecen (no ``target`` ni
    ``mode='…'``)."""
    return [token for token in backticked(cell)
            if _ID_RE.match(token) and ("_" in token or "." in token)]
