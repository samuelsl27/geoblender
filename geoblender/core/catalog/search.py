# SPDX-License-Identifier: GPL-3.0-or-later
"""Búsqueda de la línea de comandos F10 en el catálogo (spec 003; RF-003-26, RNF-003-07;
plan 003 §5.4, punto 10; HU-003-7).

Encuentra cualquier comando por su nombre en español o en inglés, sus alias (también los
de Datamine), los términos de otros programas (RecMin…) o su entrada (``R-38``, ``r38``,
``005``). También los que aún no están disponibles: salen marcados y con su «Disponible en
…», como pide BS §7.3. Los auxiliares internos de la interfaz no son órdenes del usuario y
no salen.

Texto normalizado (NFKD sin tildes, minúsculas, sin «…», «▸», «▾», «↗»). Puntuación de cada
campo: exacto 100, prefijo 80, prefijo de una palabra 60, todas las palabras de la
consulta como prefijos de palabras del campo 50, subcadena 40 y subsecuencia 20 × la
fracción del campo que cubre; por el peso del campo: etiqueta en el idioma activo 1,0, en
el otro 0,9, alias 0,9, término de otro programa 0,8 y entrada exacta 1,0. Gana el mejor
campo; a igual puntuación, el más frecuente y, después, el que va antes en el catálogo.

El índice normalizado se construye una vez por catálogo. Puro: no importa ``bpy``.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

from . import unavailable_text
from .schema import Catalog, Command

WEIGHT_ACTIVE = 1.0
WEIGHT_OTHER = 0.9
WEIGHT_ALIAS = 0.9
WEIGHT_JARGON = 0.8
WEIGHT_ENTRY = 1.0
SEARCHED_KINDS = frozenset({"operator", "menu", "panel", "native", "property"})
_SIGNS = re.compile(r"[…▸▾↗⇄]")
_SPACES = re.compile(r"\s+")
_ENTRY_SPACES = re.compile(r"[\s\-·]")


@dataclass(frozen=True)
class SearchHit:
    """Un resultado: el comando, su etiqueta y su ruta en el idioma pedido, su
    puntuación, el campo que la dio y si está disponible (si no, su «Disponible en …»)."""

    key: str
    label: str
    path: str
    score: float
    field: str  # label, label_other, alias, jargon, entry
    available: bool
    unavailable_text: str
    entry: str
    frequency: int


@dataclass(frozen=True)
class _Entry:
    command: Command
    label_en: str
    label_es: str
    aliases: tuple[str, ...]
    jargon: tuple[str, ...]
    entry: str


def normalize(text: str) -> str:
    """Minúsculas, sin tildes, sin los signos de los menús y con un solo espacio. Los
    signos se quitan antes de descomponer: NFKD convierte «…» en «...»."""
    plain = unicodedata.normalize("NFKD", _SIGNS.sub(" ", text))
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    return _SPACES.sub(" ", plain.lower()).strip()


def _entry_key(text: str) -> str:
    return _ENTRY_SPACES.sub("", normalize(text))


def _is_subsequence(query: str, text: str) -> bool:
    position = 0
    for char in query:
        position = text.find(char, position)
        if position < 0:
            return False
        position += 1
    return True


def field_score(query: str, text: str) -> float:
    """La puntuación de un campo (los dos ya normalizados) para una consulta."""
    if not query or not text:
        return 0.0
    if text == query:
        return 100.0
    if text.startswith(query):
        return 80.0
    text_words = text.split(" ")
    if any(word.startswith(query) for word in text_words):
        return 60.0
    query_words = query.split(" ")
    if len(query_words) > 1 and all(
        any(word.startswith(part) for word in text_words) for part in query_words
    ):
        return 50.0
    if query in text:
        return 40.0
    compact = query.replace(" ", "")
    if _is_subsequence(compact, text):
        return 20.0 * len(compact) / len(text.replace(" ", "") or text)
    return 0.0


_INDEXES: dict[int, tuple[Catalog, tuple[_Entry, ...]]] = {}


def _index(cat: Catalog) -> tuple[_Entry, ...]:
    """Los campos normalizados de cada comando que se busca (una vez por catálogo)."""
    cached = _INDEXES.get(id(cat))
    if cached is not None and cached[0] is cat:
        return cached[1]
    entries = tuple(
        _Entry(
            command=command,
            label_en=normalize(command.label),
            label_es=normalize(command.label_es),
            aliases=tuple(normalize(alias) for alias in command.aliases),
            jargon=tuple(normalize(term) for _program, term in command.jargon),
            entry=_entry_key(command.entry),
        )
        for command in cat.commands.values()
        if command.kind in SEARCHED_KINDS
    )
    _INDEXES[id(cat)] = (cat, entries)
    return entries


def _best(entry: _Entry, query: str, entry_query: str, language: str) -> tuple[float, str]:
    active, other = ((entry.label_en, entry.label_es) if language == "en"
                     else (entry.label_es, entry.label_en))
    best, field = field_score(query, active) * WEIGHT_ACTIVE, "label"
    candidates = [(field_score(query, other) * WEIGHT_OTHER, "label_other")]
    candidates += [(field_score(query, alias) * WEIGHT_ALIAS, "alias") for alias in entry.aliases]
    candidates += [(field_score(query, term) * WEIGHT_JARGON, "jargon") for term in entry.jargon]
    if entry.entry and entry_query == entry.entry:
        candidates.append((100.0 * WEIGHT_ENTRY, "entry"))
    for score, name in candidates:
        if score > best:
            best, field = score, name
    return best, field


def path_text(cat: Catalog, key: str, language: str) -> str:
    """La ruta del comando desde la barra en ``language`` («Cubicación ▸ Cubicar ▸ …»)."""
    msgids = cat.path(key)
    if language == "en":
        return " ▸ ".join(msgids)
    table = cat.translations()
    return " ▸ ".join(table.get(msgid, msgid) for msgid in msgids)


def search(cat: Catalog, query: str, *, language: str, is_available: Callable[[str], bool],
           limit: int = 30) -> list[SearchHit]:
    """Los comandos que mejor coinciden con ``query``, como mucho ``limit``. ``language``
    es el de la interfaz (``"es"`` o ``"en"``); ``is_available(clave)`` dice si el comando
    ya tiene su clase real (lo sabe ``bl/ui``)."""
    normalized = normalize(query)
    if not normalized:
        return []
    entry_query = _entry_key(query)
    scored: list[tuple[float, int, int, str, _Entry]] = []
    for entry in _index(cat):
        score, field = _best(entry, normalized, entry_query, language)
        if score > 0:
            command = entry.command
            scored.append((-score, -command.frequency, command.order, field, entry))
    scored.sort(key=lambda item: item[:3])
    hits: list[SearchHit] = []
    for negative, _freq, _order, field, entry in scored[:limit]:
        command = entry.command
        available = bool(is_available(command.key))
        hits.append(SearchHit(
            key=command.key,
            label=command.label if language == "en" else command.label_es,
            path=path_text(cat, command.key, language),
            score=-negative,
            field=field,
            available=available,
            unavailable_text="" if available else unavailable_text(cat, command, language),
            entry=command.entry,
            frequency=command.frequency,
        ))
    return hits
