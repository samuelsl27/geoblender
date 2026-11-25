# SPDX-License-Identifier: GPL-3.0-or-later
"""La regla «nunca una clave interna a la vista» (spec 019, T24; RF-019-16; UI-08; plan 019 A6, P-3).

Python puro: ni ``bpy`` ni el ``bl/`` real. Dos piezas:

- :func:`violations`: de un texto que se vería en pantalla, los nombres de las reglas que incumple. Una clave interna es
  un código de mensaje (``des.pit.hoja``), un código de entidad (``PIT-001``), el nombre estable de un dato o de una
  propiedad (``bench_height``), un marcador sin rellenar (``{name}``), el ``msgid`` en inglés de un texto que tiene
  traducción cuando se dibuja en español, o una ruta de módulo (``geoblender.core.x``).
- :class:`StringCollector`: un *layout* simulado (:class:`tests.support.fake_layout.FakeLayout`) que recoge cada
  ``label``, ``text=`` y ``report`` de lo que dibuja una función, para mirar las cadenas armadas en ejecución (las
  *f-strings* con nombres y valores) y no solo los literales.

La lista base (``tests/data/ui_baseline.toml``, sección ``[strings]``) es la de lo existente que no cumple: solo baja.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from tests.support.fake_layout import FakeLayout
from tests.support.repo import ROOT

BASELINE_FILE = ROOT / "tests" / "data" / "ui_baseline.toml"
# Los prefijos de los códigos de mensaje (``des.pit.pit_000.…``, ``core.…``).
CODE_PREFIXES = "des|dh|gis|core|res|io|job|bl|ui"

# (nombre, expresión) de cada patrón prohibido en un texto visible.
FORBIDDEN: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("message-code", re.compile(rf"\b(?:{CODE_PREFIXES})\.[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*\b")),
    ("module-path", re.compile(r"\b(?:geoblender|bpy)\.[a-z_]+(?:\.[a-z_]+)*\b")),
    ("entity-code", re.compile(r"\b(?!ISO-)[A-Z]{2,4}-\d{3,}\b")),
    ("stable-name", re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b")),
    ("placeholder", re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")),
)
UNTRANSLATED = "untranslated-msgid"


def violations(text: str, translations: Mapping[str, str] | None = None, *, language: str = "es") -> list[str]:
    """Los nombres de las reglas que incumple ``text`` (vacío: cumple). Con ``translations`` (``msgid`` → español) y
    ``language="es"``, un texto que es un ``msgid`` con traducción distinta es el inglés sin traducir."""
    found = [name for name, pattern in FORBIDDEN if pattern.search(text)]
    if language == "es" and translations is not None:
        spanish = translations.get(text)
        if spanish is not None and spanish != text:
            found.append(UNTRANSLATED)
    return found


class StringCollector(FakeLayout):
    """Un *layout* simulado que, además de lo dibujado, anota los textos de ``label``, ``text=`` y ``report``."""

    def __init__(self) -> None:
        super().__init__()
        self.reports: list[str] = []

    def drawn_texts(self) -> list[str]:
        """Los textos de todo lo dibujado (etiquetas, botones, menús, propiedades), en orden."""
        return [item.text for item in self.items if item.text]

    def report(self, _kinds: Any, message: str) -> None:
        self.reports.append(message)

    def all_texts(self) -> list[str]:
        return [*self.drawn_texts(), *self.reports]


def collect(draw: Callable[[StringCollector], None]) -> list[str]:
    """Los textos que ``draw`` dibuja o informa con un :class:`StringCollector`."""
    collector = StringCollector()
    draw(collector)
    return collector.all_texts()


def findings(texts: Iterable[str], translations: Mapping[str, str] | None = None) -> list[tuple[str, str]]:
    """(texto, regla) de cada incumplimiento de ``texts``."""
    return [(text, rule) for text in texts for rule in violations(text, translations)]


def load_baseline(section: str, path: Path = BASELINE_FILE) -> list[str]:
    """Las entradas de la sección ``section`` de la lista base (``[]`` si no existe)."""
    try:
        data = tomllib.loads(path.read_bytes().decode("utf-8"))
    except FileNotFoundError:
        return []
    entries = data.get(section, {}).get("entries", [])
    return [str(entry) for entry in entries]
