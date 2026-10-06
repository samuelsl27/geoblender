# SPDX-License-Identifier: GPL-3.0-or-later
"""Catálogo de comandos de la interfaz de Geoblender (spec 003; RF-003-06, RF-003-07,
RF-003-18, RF-003-26, RF-003-27; plan 003 §5.1–§5.3, DT1; BS §7).

Los datos están en ``data/**/*.toml``: los 13 menús de la barra (BS §8) con todos sus
comandos, los concentradores de intercambio (BS §8.14), el acceso rápido (AR §2 y §3),
los menús circulares (AR §4), los menús contextuales (PC §3 y §4), los atajos (AT §2), las
entradas del roadmap con su título y las disposiciones (CW §6). Cada comando tiene una
única definición (etiqueta y descripción en inglés, que es su ``msgid``, y en español,
módulo, entrada, tipo de acción, frecuencia, icono propio y de reserva, alias y términos
de otros programas) que comparten todos los sitios donde aparece. De aquí salen en
``bl/ui`` los menús, el acceso rápido, los menús circulares y contextuales, los
operadores provisionales, los atajos, la hoja de atajos y la búsqueda de F10.

API (plan 003 §5.3):

- :func:`load`: el catálogo (en caché por carpeta); :func:`validate`: sus incidencias;
- :func:`unavailable_text`: «Disponible en <entrada · título>» de un comando.

Puro: no importa ``bpy`` (ADR-0004), para que ``tests/unit`` lo pueda leer.
"""

from __future__ import annotations

import functools
from pathlib import Path

from ..i18n import translate
from .loader import DATA_DIR, load_catalog
from .schema import (
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
    validate,
)

__all__ = [
    "DATA_DIR",
    "Catalog",
    "CatalogIssue",
    "Command",
    "ContextSpec",
    "EntryRef",
    "Group",
    "LayoutSpec",
    "MenuItem",
    "MenuSpec",
    "PieSpec",
    "QuickAccessItem",
    "Shortcut",
    "entry_text",
    "load",
    "unavailable_text",
    "validate",
]


@functools.cache
def _load(data_dir: str) -> Catalog:
    return load_catalog(Path(data_dir))


def load(data_dir: Path | None = None) -> Catalog:
    """El catálogo de ``data_dir`` (por defecto, el de la extensión), leído una sola vez
    por carpeta. Lo que no se pudo leer queda en ``load_issues`` y sale en
    :func:`validate`."""
    folder = DATA_DIR if data_dir is None else Path(data_dir)
    return _load(str(folder.resolve()))


def entry_text(cat: Catalog, entry: str, language: str) -> str:
    """La entrada con su título en ``language`` («R-38 · Cubicación entre superficies»;
    sin título conocido, solo la entrada)."""
    ref = cat.entries.get(entry)
    if ref is None:
        return entry
    title = ref.title if language == "en" else ref.title_es
    return f"{entry} · {title}" if title and title != entry else entry


def unavailable_text(cat: Catalog, cmd: Command, language: str) -> str:
    """«Disponible en <entrada · título>» de un comando aún no disponible, en
    ``language`` (``"es"`` o ``"en"``), sin cambiar el idioma activo (RF-003-07)."""
    return translate(language, "Available in {entry}",
                     entry=entry_text(cat, cmd.entry, language))
