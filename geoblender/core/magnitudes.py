# SPDX-License-Identifier: GPL-3.0-or-later
"""Las magnitudes con su formato único (spec 019, T06; RF-019-17; UI-07).

Cada magnitud (longitud, superficie, volumen, porcentaje, ángulo, coordenada) se escribe siempre igual en campos,
etiquetas, tablas y mensajes: unidad y decimales fijos, coma decimal y espacio fino de miles en español (punto y
coma de miles en inglés). El número lo da :func:`~.i18n.format_number`, el formateador que ya usaba el resto del
código, así que reunirlo aquí no cambia ningún resultado visible. :func:`parse` es tolerante (Postel): admite coma
o punto decimal, espacios y puntos o comas de miles, y la unidad opcional.

Todo es ``float`` de 64 bits: una coordenada absoluta no pasa nunca por float32 (principio 6). Dominio puro.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType

from .errors import GeoblenderError
from .i18n import THIN_SPACE, format_number, language as active_language, tr

__all__ = ["MAGNITUDES", "Magnitude", "format", "parse"]


@dataclass(frozen=True)
class Magnitude:
    """El formato de una magnitud: ``decimals`` decimales fijos y su ``unit`` (puede ir vacía)."""

    name: str
    decimals: int
    unit: str


MAGNITUDES = MappingProxyType({m.name: m for m in (
    Magnitude("length", 2, "m"),
    Magnitude("area", 2, "m²"),
    Magnitude("volume", 1, "m³"),
    Magnitude("percent", 1, "%"),
    Magnitude("angle", 1, "°"),
    Magnitude("coordinate", 2, "m"),
)})
"""El catálogo, por nombre. Las cifras son el formato vigente del código (``des_pit``: 2 decimales con miles;
``format_xyz``: 2 decimales)."""

_ES = str.maketrans({",": THIN_SPACE, ".": ","})
_SPACES = re.compile(r"[\s   ]+")
_NUMBER = re.compile(r"[+-]?(?:\d+|\d+[.,]\d*|[.,]\d+)")


def _get(name: str) -> Magnitude:
    found = MAGNITUDES.get(name)
    if found is None:
        raise GeoblenderError("core.magnitude_unknown",
                              tr("the magnitude must be one of: {names}", names=", ".join(MAGNITUDES)),
                              obj=tr("Magnitude"), field=tr("Name"), value=name)
    return found


def format(name: str, value: float, *, language: str | None = None) -> str:  # noqa: A001
    """``value`` como se escribe la magnitud ``name``: número con sus decimales fijos y la unidad
    (``1 234,50 m²``). ``language``: ``"es"`` o ``"en"``; por defecto, el activo."""
    magnitude = _get(name)
    lang = language or active_language()
    number = float(value)
    if lang == "en":
        text = f"{number:,.{magnitude.decimals}f}"
        if text.startswith("-") and float(text.replace(",", "")) == 0:
            text = text[1:]
    else:
        text = (format_number(number, magnitude.decimals) if active_language() == "es"
                else f"{number:,.{magnitude.decimals}f}".translate(_ES))
        if text.startswith("-") and float(text.replace(THIN_SPACE, "").replace(",", ".")) == 0:
            text = text[1:]
    return f"{text} {magnitude.unit}" if magnitude.unit else text


def parse(name: str, text: str) -> float:
    """El valor de ``text`` (``1.234,5``, ``1234.5``, ``1 234,5``…), con la unidad de la magnitud opcional.
    ``GeoblenderError`` con objeto, campo y valor si no es un número."""
    magnitude = _get(name)
    raw = _SPACES.sub("", str(text))
    if magnitude.unit and raw.endswith(magnitude.unit):
        raw = raw[:-len(magnitude.unit)]
    sign = ""
    if raw[:1] in "+-" and raw[:1]:
        sign, raw = raw[0], raw[1:]
    value = _read(raw)
    if value is None:
        raise GeoblenderError("core.magnitude_invalid",
                              tr("it is not a number (for example 1 234,5 or 1234.5)"),
                              obj=tr("Magnitude"), field=tr("Value"), value=text)
    return -value if sign == "-" else value


def _read(raw: str) -> float | None:
    """La parte sin signo ni unidad como ``float``, o ``None``. Con los dos separadores, el último es el decimal y
    el otro, de miles; con uno repetido, es de miles; con uno solo, es el decimal."""
    if not raw or not re.fullmatch(r"[\d.,]+", raw) or not re.search(r"\d", raw):
        return None
    last = max(raw.rfind("."), raw.rfind(","))
    if last < 0:
        return float(raw)
    decimal = raw[last]
    other = "," if decimal == "." else "."
    head, fraction = raw[:last], raw[last + 1:]
    if decimal in head:
        return None if other in raw else float(raw.replace(decimal, ""))
    return float(f"{head.replace(other, '') or '0'}.{fraction or '0'}")
