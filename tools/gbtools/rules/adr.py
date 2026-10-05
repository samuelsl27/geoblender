# SPDX-License-Identifier: GPL-3.0-or-later
"""ADR-01: formato de los ADR y coherencia de su índice (ADR-0001; RF-001-20).

Plan 001 §5.4.10:

1. Ficheros ``docs/adr/*.md`` salvo ``README.md`` y ``0000-plantilla.md``: nombre
   ``NNNN-<slug>.md`` y número único.
2. Primera línea ``# ADR-NNNN — <título>``, con el número del nombre.
3. Cabecera = el texto anterior a la primera sección ``## ``. En ella, la primera línea
   ``- **Estado:** …`` (su primera palabra, sin «;» ni «,» finales, es Propuesta,
   Aceptada, Rechazada o Sustituida) y la primera ``- **Fecha:** AAAA-MM-DD``. Así una
   línea «Estado:» del cuerpo (ADR-0013) no cuenta.
4. Secciones obligatorias, como líneas exactas.
5. Índice ``docs/adr/README.md``: una fila ``| [ADR-NNNN](fichero) | título | estado |
   fecha |`` por ADR, con el enlace al fichero, el mismo título, la misma fecha y la
   misma primera palabra del estado («Aceptada en el qué; …» ↔ «Aceptada en el qué
   (…)»).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..findings import Finding

RULE = "ADR-01"
ADR_DIR = "docs/adr"
INDEX_NAME = "README.md"
TEMPLATE_NAME = "0000-plantilla.md"
STATES: tuple[str, ...] = ("Propuesta", "Aceptada", "Rechazada", "Sustituida")
SECTIONS: tuple[str, ...] = (
    "## Contexto",
    "## Decisión",
    "## Alternativas consideradas",
    "## Consecuencias",
    "## Cómo se verifica",
)

_NAME_RE = re.compile(r"^(\d{4})-[a-z0-9-]+\.md$")
_TITLE_RE = re.compile(r"^# ADR-(\d{4}) — (.+)$")
_STATE_PREFIX = "- **Estado:**"
_DATE_PREFIX = "- **Fecha:**"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ROW_RE = re.compile(
    r"^\|\s*\[ADR-(\d{4})\]\(([^)\s]*)\)\s*\|([^|]*)\|([^|]*)\|([^|]*)\|\s*$"
)


def first_word(state: str) -> str:
    """Primera palabra de un estado, sin «;» ni «,» finales."""
    words = state.split()
    return words[0].rstrip(";,") if words else ""


@dataclass(frozen=True)
class AdrHeader:
    """Lo que ADR-01 lee de un ADR. Las líneas empiezan en 1 (0: no está)."""

    number: str | None
    title: str | None
    state: str | None
    state_line: int
    date: str | None
    date_line: int
    lines: tuple[str, ...]

    @property
    def state_word(self) -> str | None:
        return None if self.state is None else first_word(self.state)


@dataclass(frozen=True)
class IndexRow:
    """Una fila del índice de ADR."""

    number: str
    link: str
    title: str
    state: str
    date: str
    line: int


def parse_adr(text: str) -> AdrHeader:
    """Título, estado y fecha de la cabecera de un ADR."""
    lines = tuple(line.removesuffix("\r") for line in text.split("\n"))
    match = _TITLE_RE.match(lines[0])
    number, title = (match.group(1), match.group(2)) if match else (None, None)
    state = date = None
    state_line = date_line = 0
    for index, line in enumerate(lines[1:], start=2):
        if line.startswith("## "):
            break  # fin de la cabecera
        if state is None and line.startswith(_STATE_PREFIX):
            state, state_line = line[len(_STATE_PREFIX) :].strip(), index
        elif date is None and line.startswith(_DATE_PREFIX):
            date, date_line = line[len(_DATE_PREFIX) :].strip(), index
    return AdrHeader(number, title, state, state_line, date, date_line, lines)


def parse_index(text: str) -> dict[str, IndexRow]:
    """Filas del índice por número; una fila repetida conserva la primera."""
    return {row.number: row for row in reversed(_index_rows(text))}


def _index_rows(text: str) -> list[IndexRow]:
    rows: list[IndexRow] = []
    for index, line in enumerate(text.split("\n"), start=1):
        match = _ROW_RE.match(line.removesuffix("\r"))
        if match:
            number, link, title, state, date = (g.strip() for g in match.groups())
            rows.append(IndexRow(number, link, title, state, date, index))
    return rows


def _check_file(rel: str, number: str, header: AdrHeader) -> list[Finding]:
    findings: list[Finding] = []

    def add(line: int, message: str) -> None:
        findings.append(Finding(rel, line, RULE, message))

    if header.number is None:
        add(1, "la primera línea debe ser «# ADR-NNNN — <título>» (con raya «—»)")
    elif header.number != number:
        add(1, f"el título dice ADR-{header.number} y el fichero es el {number}")
    if header.state is None:
        add(0, "falta la línea «- **Estado:** …» en la cabecera, antes de las secciones")
    elif header.state_word not in STATES:
        add(
            header.state_line,
            f"estado «{header.state_word}»: debe empezar por "
            + ", ".join(STATES[:-1])
            + f" o {STATES[-1]}",
        )
    if header.date is None:
        add(0, "falta la línea «- **Fecha:** AAAA-MM-DD» en la cabecera")
    elif not _DATE_RE.match(header.date):
        add(header.date_line, f"fecha «{header.date}»: debe ser AAAA-MM-DD")
    present = set(header.lines)
    for section in SECTIONS:
        if section not in present:
            add(0, f"falta la sección obligatoria «{section}» (ADR-0001)")
    return findings


def _check_index(
    index_rel: str, text: str, files: dict[str, list[tuple[str, AdrHeader]]]
) -> list[Finding]:
    findings: list[Finding] = []

    def add(line: int, message: str) -> None:
        findings.append(Finding(index_rel, line, RULE, message))

    seen: set[str] = set()
    for row in _index_rows(text):
        adr_id = f"ADR-{row.number}"
        if row.number in seen:
            add(row.line, f"{adr_id} tiene más de una fila en el índice")
            continue
        seen.add(row.number)
        candidates = files.get(row.number)
        if not candidates:
            add(row.line, f"la fila de {adr_id} no corresponde a ningún fichero")
            continue
        name, header = next(
            ((n, h) for n, h in candidates if n == row.link), candidates[0]
        )
        if row.link != name:
            add(row.line, f"{adr_id}: el enlace «{row.link}» debe ser «{name}»")
        if header.title is not None and row.title != header.title:
            add(
                row.line,
                f"{adr_id}: el título del índice «{row.title}» no es el del fichero "
                f"«{header.title}»",
            )
        if header.state is not None and first_word(row.state) != header.state_word:
            add(
                row.line,
                f"{adr_id}: el estado del índice empieza por «{first_word(row.state)}» "
                f"y el del fichero por «{header.state_word}»",
            )
        if header.date is not None and row.date != header.date:
            add(
                row.line,
                f"{adr_id}: la fecha del índice «{row.date}» no es la del fichero "
                f"«{header.date}»",
            )
    for number in sorted(set(files) - seen):
        names = ", ".join(name for name, _ in files[number])
        add(0, f"falta la fila de ADR-{number} ({names}) en el índice")
    return findings


def check(root: Path) -> list[Finding]:
    """Incumplimientos de ADR-01 en ``docs/adr/``."""
    adr_dir = root / ADR_DIR
    if not adr_dir.is_dir():
        return [Finding(ADR_DIR, 0, RULE, "falta la carpeta de ADR (ADR-0001)")]
    findings: list[Finding] = []
    files: dict[str, list[tuple[str, AdrHeader]]] = {}
    for path in sorted(adr_dir.glob("*.md")):
        if path.name in (INDEX_NAME, TEMPLATE_NAME):
            continue
        rel = f"{ADR_DIR}/{path.name}"
        match = _NAME_RE.match(path.name)
        if not match:
            message = "el nombre debe ser «NNNN-<slug>.md», en minúsculas"
            findings.append(Finding(rel, 0, RULE, message))
            continue
        number = match.group(1)
        header = parse_adr(path.read_text(encoding="utf-8", errors="replace"))
        findings.extend(_check_file(rel, number, header))
        files.setdefault(number, []).append((path.name, header))
    for number, entries in files.items():
        if len(entries) > 1:
            names = ", ".join(name for name, _ in entries)
            for name, _ in entries:
                findings.append(
                    Finding(
                        f"{ADR_DIR}/{name}",
                        0,
                        RULE,
                        f"el número {number} se repite ({names}); no se reutiliza",
                    )
                )
    index_path = adr_dir / INDEX_NAME
    index_rel = f"{ADR_DIR}/{INDEX_NAME}"
    if not index_path.is_file():
        findings.append(Finding(index_rel, 0, RULE, "falta el índice de ADR"))
    else:
        index_text = index_path.read_text(encoding="utf-8", errors="replace")
        findings.extend(_check_index(index_rel, index_text, files))
    return sorted(findings)
