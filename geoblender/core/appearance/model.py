# SPDX-License-Identifier: GPL-3.0-or-later
"""Los valores del aspecto de un elemento y su validación (spec 019, T02; RF-019-08, RF-019-22; ADR-0033;
plan 019 §5.2 y §5.3).

Un valor de aspecto se guarda y se compara siempre en su forma **canónica** (texto): ``#RRGGBB`` en
mayúsculas para el color, un entero de 0 a 100 para la transparencia, ``0`` o ``1`` para lo de sí o no,
un decimal con punto y sin ceros sobrantes para el grosor y el tamaño, y el texto sin espacios de más
para el rótulo. :func:`validate` acepta lo que escribe una persona (``2,5``, ``#56b4e9``) y devuelve la
forma canónica; lo que no vale lo rechaza con un :class:`~geoblender.core.errors.GeoblenderError` que
nombra el objeto, el campo y el valor (principio 10).

Dominio puro: ni ``bpy`` ni nada de ``bl``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from ..errors import GeoblenderError
from ..i18n import tr

__all__ = ["Appearance", "GeoblenderError", "LABEL_MAX", "RANGES", "field_name", "validate"]

LABEL_MAX = 120
"""Los caracteres que admite un rótulo."""
RANGES: dict[str, tuple[float, float]] = {"line_width": (0.5, 20.0), "point_size": (1.0, 50.0)}
"""El intervalo (mínimo, máximo) admitido de cada propiedad decimal, en píxeles."""

_COLOR = re.compile(r"#[0-9A-Fa-f]{6}")
_DECIMAL = re.compile(r"[+-]?\d+(?:[.,]\d+)?")
_FIELD_NAMES = {  # msgid del nombre de cada propiedad (todo por el catálogo de idioma)
    "label": "Label", "color": "Color", "transparency": "Transparency", "visible": "Visible",
    "line_width": "Line width", "point_size": "Point size", "labels": "Labels", "wire": "Wireframe",
}


def field_name(prop: str) -> str:
    """El nombre de la propiedad ``prop`` para una persona, en el idioma activo."""
    return tr(_FIELD_NAMES.get(prop, prop))


@dataclass(frozen=True)
class Appearance:
    """El aspecto de un tipo de elemento: sus propiedades con su valor canónico, en el orden del catálogo.
    Inmutable y comparable; ``values`` son pares ``(propiedad, valor)``."""

    kind: str
    values: tuple[tuple[str, str], ...]

    @property
    def props(self) -> tuple[str, ...]:
        """Las propiedades que lleva, en orden."""
        return tuple(prop for prop, _value in self.values)

    def as_dict(self) -> dict[str, str]:
        """Los valores como diccionario ``{propiedad: valor}``."""
        return dict(self.values)

    def __iter__(self) -> Iterator[tuple[str, str]]:
        return iter(self.values)

    def get(self, prop: str, *default: str | None) -> str | None:
        """El valor de ``prop``; sin él, el ``default`` si se da y, si no, ``KeyError``."""
        for key, value in self.values:
            if key == prop:
                return value
        if default:
            return default[0]
        raise KeyError(prop)

    def with_values(self, changes: Mapping[str, object]) -> Appearance:
        """Una copia con ``changes`` (propiedad → valor tecleado) validados y en su forma canónica; una
        propiedad que no tenía se añade al final."""
        merged = self.as_dict()
        for prop, raw in changes.items():
            merged[prop] = validate(self.kind, prop, raw)
        return Appearance(self.kind, tuple(merged.items()))


def _invalid(obj: str, prop: str, raw: object, reason: str, code: str = "core.appearance_invalid") -> GeoblenderError:
    return GeoblenderError(code, reason, obj=obj, field=field_name(prop), value=raw)


def _boolean(obj: str, prop: str, raw: object) -> str:
    if isinstance(raw, bool):
        return "1" if raw else "0"
    if isinstance(raw, int) and raw in (0, 1):
        return str(raw)
    if isinstance(raw, str) and raw.strip() in ("0", "1"):
        return raw.strip()
    raise _invalid(obj, prop, raw, tr("it must be yes or no (1 or 0)"))


def _transparency(obj: str, prop: str, raw: object) -> str:
    reason = tr("transparency is a whole number between 0 and 100")
    number: int | None = None
    if isinstance(raw, bool):
        number = None
    elif isinstance(raw, int):
        number = raw
    elif isinstance(raw, float):
        number = int(raw) if raw.is_integer() else None
    elif isinstance(raw, str) and re.fullmatch(r"[+-]?\d+", raw.strip()):
        number = int(raw.strip())
    if number is None or not 0 <= number <= 100:
        raise _invalid(obj, prop, raw, reason)
    return str(number)


def _color(obj: str, prop: str, raw: object) -> str:
    text = raw.strip() if isinstance(raw, str) else ""
    if not _COLOR.fullmatch(text):
        raise _invalid(obj, prop, raw, tr("a color is written as #RRGGBB (for example #56B4E9)"))
    return text.upper()


def _decimal(obj: str, prop: str, raw: object) -> str:
    low, high = RANGES[prop]
    number: float | None = None
    if isinstance(raw, bool):
        number = None
    elif isinstance(raw, (int, float)):
        number = float(raw)
    elif isinstance(raw, str) and _DECIMAL.fullmatch(raw.strip()):
        number = float(raw.strip().replace(",", "."))
    if number is None or number != number or not low <= number <= high:  # NaN no es un valor
        raise _invalid(obj, prop, raw, tr("it must be a number between {low} and {high}",
                                          low=_decimal_text(low), high=_decimal_text(high)))
    return _decimal_text(number)


def _decimal_text(number: float) -> str:
    return f"{round(number, 2):.2f}".rstrip("0").rstrip(".")


def _label(obj: str, prop: str, raw: object) -> str:
    text = raw.strip() if isinstance(raw, str) else ""
    if not text or len(text) > LABEL_MAX or not text.isprintable():
        raise _invalid(obj, prop, raw, tr("the label must have between 1 and {maximum} characters, on a single line",
                                          maximum=LABEL_MAX))
    return text


_CHECKS = {
    "label": _label, "color": _color, "transparency": _transparency, "visible": _boolean, "labels": _boolean,
    "wire": _boolean, "line_width": _decimal, "point_size": _decimal,
}


def validate(kind: str, prop: str, raw: object, *, name: str = "") -> str:
    """El valor canónico de ``raw`` para la propiedad ``prop`` de un elemento de tipo ``kind``.

    ``name`` es el nombre del elemento para el mensaje (sin él, «Aspecto de <tipo>»). Lanza
    :class:`~geoblender.core.errors.GeoblenderError` con objeto, campo y valor si el tipo no tiene la
    propiedad (``core.appearance_not_editable``) o si el valor no es del tipo o está fuera de rango
    (``core.appearance_invalid``)."""
    from .catalog import allowed  # el catálogo importa este módulo: aquí, al usarlo

    obj = name or tr("Appearance of {kind}", kind=kind)
    props = allowed(kind)
    if prop not in props:
        raise _invalid(obj, prop, raw, tr("this type of element does not have that property; it has: {props}",
                                          props=", ".join(field_name(item) for item in props)),
                       "core.appearance_not_editable")
    return _CHECKS[prop](obj, prop, raw)  # type: ignore[operator]
