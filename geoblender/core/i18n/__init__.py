# SPDX-License-Identifier: GPL-3.0-or-later
"""Idioma de la interfaz de Geoblender (spec 002; RF-002-34; plan 002 §5.1 y §5.5; plan
003 §5.3; ADR-0012; iconos-e-idioma.md §2).

Español por defecto e inglés disponible, **independiente del idioma de Blender** (no se
usa ``bpy.app.translations``, que sigue al de Blender). Cada texto de la interfaz tiene un
``msgid`` en inglés, que es también su versión inglesa, y su traducción al español en
``messages.toml`` (``{msgid: {"es": texto}}``), con marcadores de ``str.format``
(``{name}``). Este paquete es puro (ADR-0004): ``bl`` llama a :func:`tr` al dibujar.

API (la del plan 003 §5.3; la spec 003 la amplía con el catálogo de comandos):

- :func:`tr`: el texto de un ``msgid`` en el idioma activo, con sus valores;
- :func:`set_language` y :func:`language`: el idioma activo (``"es"`` o ``"en"``);
- :func:`install`: añade traducciones (las del catálogo de comandos de la 003);
- :func:`missing_translations`: los ``msgid`` sin traducción (en el fichero o pedidos);
- :func:`format_number` y :func:`format_xyz`: números y coordenadas **absolutas**
  (float64) en el formato del idioma: en español, coma decimal y espacio fino (sin
  ruptura) de miles (``X 736 512,34  Y 4 435 871,02``); en inglés, punto decimal, comas de
  miles en los números y coordenadas sin separador (``X 736512.34  Y 4435871.02``).

Nunca un módulo ``core/i18n.py``: el paquete lo ocultaría (PLT-03).
"""

from __future__ import annotations

import string
import tomllib
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ..errors import GeoblenderError, ValidationError

LANGUAGES: tuple[str, ...] = ("es", "en")
DEFAULT_LANGUAGE = "es"
THIN_SPACE = " "  # espacio fino sin ruptura: separador de miles en español
MESSAGES_FILE = Path(__file__).with_name("messages.toml")


class _State:
    """El idioma activo y las traducciones cargadas (del proceso, no del proyecto)."""

    def __init__(self) -> None:
        self.language = DEFAULT_LANGUAGE
        self.table: dict[str, str] | None = None
        self.installed: dict[str, str] = {}
        self.missing: set[str] = set()


_STATE = _State()


def placeholders(text: str) -> set[str]:
    """Los nombres de los marcadores ``{nombre}`` de ``text``."""
    return {name for _literal, name, _spec, _conv in string.Formatter().parse(text) if name}


def load_messages(path: Path = MESSAGES_FILE) -> dict[str, str]:
    """``msgid`` → español de un ``messages.toml``. :class:`GeoblenderError` si el
    fichero no se puede leer o una entrada no tiene la forma ``{msgid: {"es": texto}}``."""
    try:
        data = tomllib.loads(Path(path).read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise GeoblenderError(
            "core.i18n_unreadable",
            f"no se puede leer el catálogo de idioma ({exc}); reinstale Geoblender",
            obj="Idioma",
            field="messages.toml",
            value=str(path),
        ) from exc
    table: dict[str, str] = {}
    for msgid, entry in data.items():
        spanish = entry.get("es") if isinstance(entry, Mapping) else None
        if not isinstance(spanish, str):
            raise GeoblenderError(
                "core.i18n_entry_invalid",
                "cada entrada es {msgid: {es = \"texto\"}}",
                obj="Idioma",
                field="messages.toml",
                value=msgid,
            )
        table[msgid] = spanish
    return table


def _table() -> dict[str, str]:
    if _STATE.table is None:
        _STATE.table = load_messages()
    return _STATE.table


def language() -> str:
    """El idioma activo (``"es"`` o ``"en"``)."""
    return _STATE.language


def set_language(language: str) -> None:
    """Cambia el idioma activo; :class:`ValidationError` si no es ``"es"`` ni ``"en"``."""
    if language not in LANGUAGES:
        raise ValidationError(
            "core.language_invalid",
            f"los idiomas de Geoblender son: {', '.join(LANGUAGES)}",
            obj="Idioma",
            field="idioma",
            value=language,
        )
    _STATE.language = language


def tr(msgid: str, /, **values: object) -> str:
    """El texto de ``msgid`` en el idioma activo con ``values`` en sus marcadores. Sin
    traducción, el ``msgid`` (inglés), y queda en :func:`missing_translations`."""
    text = msgid
    if _STATE.language != "en":
        spanish = _STATE.installed.get(msgid) or _table().get(msgid)
        if spanish:
            text = spanish
        else:
            _STATE.missing.add(msgid)
    return text.format(**values) if values else text


def install(source: object) -> None:
    """Añade traducciones al español: un ``{msgid: texto}``, un ``{msgid: {"es": texto}}``,
    pares ``(msgid, texto)`` o un objeto con ``translations()`` que devuelva cualquiera
    de ellos (el catálogo de comandos de la spec 003)."""
    data: Any = source.translations() if hasattr(source, "translations") else source
    items: Iterable[tuple[object, object]]
    items = data.items() if isinstance(data, Mapping) else data
    for msgid, value in items:
        spanish = value.get("es") if isinstance(value, Mapping) else value
        if isinstance(msgid, str) and isinstance(spanish, str) and spanish:
            _STATE.installed[msgid] = spanish
            _STATE.missing.discard(msgid)


def missing_translations() -> list[str]:
    """Los ``msgid`` sin traducción al español: los del fichero con el texto vacío y los
    que se han pedido sin tenerla (constitución, principio 10)."""
    empty = {msgid for msgid, text in _table().items() if not text.strip()}
    return sorted(empty | _STATE.missing)


def format_number(value: float, decimals: int) -> str:
    """Un número con ``decimals`` decimales en el formato del idioma activo: en español,
    ``1 234 567,89`` (espacio fino sin ruptura); en inglés, ``1,234,567.89``."""
    text = f"{float(value):,.{int(decimals)}f}"
    if text.startswith("-") and float(text.replace(",", "")) == 0:
        text = text[1:]  # sin «-0»
    if _STATE.language == "en":
        return text
    return text.translate(str.maketrans({",": THIN_SPACE, ".": ","}))


def format_xyz(x: float, y: float, z: float, decimals: int = 2) -> str:
    """Coordenadas **absolutas** (float64) como las lee una persona: en español,
    ``X 736 512,34  Y 4 435 871,02  Z 180,00``; en inglés, sin separador de miles,
    ``X 736512.34  Y 4435871.02  Z 180.00``."""
    if _STATE.language == "en":
        parts = (f"{float(value):.{int(decimals)}f}" for value in (x, y, z))
    else:
        parts = (format_number(value, decimals) for value in (x, y, z))
    return "  ".join(f"{axis} {text}" for axis, text in zip("XYZ", parts, strict=True))
