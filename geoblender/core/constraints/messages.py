# SPDX-License-Identifier: GPL-3.0-or-later
"""Mensajes de las restricciones (spec 012; plan 012 §5.1 y §5.5; constitución, principio 10).

Cada problema o error de las restricciones que llega a una persona tiene un **código** estable
en inglés con el prefijo ``core.constraint`` (``"core.constraint_no_reason"``), un ``msgid`` en
inglés (también su versión inglesa) y su texto en español, con marcadores de ``str.format`` con
nombre en inglés, los mismos en los dos. El texto nombra la restricción (``{name}``), su tipo
(``{ctype}``) y el valor, y dice qué hacer.

- :class:`Message`, :data:`CATALOG` y :data:`MESSAGES` (por código).
- :data:`CATALOG_ES`: ``msgid`` → español, para ``core.i18n.install`` al registrar.
- :func:`render`: el texto de un código con sus valores, en español o en inglés.
- :class:`ConstraintError`: el error para el usuario (un ``GeoblenderError``) con su código,
  la restricción como objeto, el campo y el valor.

Las tareas siguientes de la 012 añaden aquí sus códigos. Python puro (``core``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ..errors import GeoblenderError
from ..i18n import LANGUAGES
from ..params import format_value

__all__ = [
    "CATALOG",
    "CATALOG_ES",
    "MESSAGES",
    "ConstraintError",
    "Message",
    "lookup",
    "render",
]

MISSING_VALUE = "?"
"""Lo que se ve en lugar de un valor que falta (nunca el marcador ``{…}``)."""

_WHERE_EN = "Design ▸ Legal limits and constraints ▸ Constraints…"
_WHERE_ES = "Diseño ▸ Límites y restricciones ▸ Restricciones…"


@dataclass(frozen=True, slots=True)
class Message:
    """Un mensaje del catálogo: código ``core.constraint*``, ``msgid`` en inglés y español."""

    code: str
    msgid: str
    es: str


CATALOG: tuple[Message, ...] = (
    # Lo incompleto o no válido de una restricción (RF-012-04; checks.py) -------------------
    Message(
        "core.constraint_no_code",
        "{name} has no code: complete it in " + _WHERE_EN + " (a constraint drawn in QGIS "
        "gets its code when it is completed)",
        "{name} no tiene código: complétela en " + _WHERE_ES + " (una restricción dibujada en "
        "QGIS recibe su código al completarla)",
    ),
    Message(
        "core.constraint_code_invalid",
        "{name} ({ctype}): the code «{value}» is not lower-case letters, digits and «_» "
        "starting with a letter; complete the constraint again in " + _WHERE_EN,
        "{name} ({ctype}): el código «{value}» no es de minúsculas, cifras y «_» empezando por "
        "una letra; vuelva a completar la restricción en " + _WHERE_ES,
    ),
    Message(
        "core.constraint_code_repeated",
        "{name} ({ctype}): the code «{value}» is also used by another constraint; a code is "
        "unique in the three constraint layers (copied in QGIS?): complete it again in "
        + _WHERE_EN,
        "{name} ({ctype}): el código «{value}» lo usa también otra restricción; un código es "
        "único en las tres capas de restricciones (¿copiada en QGIS?): vuelva a completarla en "
        + _WHERE_ES,
    ),
    Message(
        "core.constraint_no_type",
        "{name}: it has no valid type; choose one of the eleven in " + _WHERE_EN,
        "{name}: no tiene un tipo válido; elija uno de los once en " + _WHERE_ES,
    ),
    Message(
        "core.constraint_no_reason",
        "{name} ({ctype}) has no reason: write why it constrains the design in " + _WHERE_EN,
        "{name} ({ctype}) no tiene motivo: escriba por qué limita el diseño en " + _WHERE_ES,
    ),
    Message(
        "core.constraint_no_decider",
        "{name} ({ctype}) has no decider: write who decided it (the owner, the authority, the "
        "engineer) in " + _WHERE_EN,
        "{name} ({ctype}) no tiene decisor: escriba quién la decidió (la propiedad, la "
        "autoridad, el ingeniero) en " + _WHERE_ES,
    ),
    Message(
        "core.constraint_param_missing",
        "{name} ({ctype}): the value of «{param}» ({key}) is missing; declare it when "
        "completing the constraint (" + _WHERE_EN + ").",
        "{name} ({ctype}): falta el valor de «{param}» ({key}); declárelo al completar la "
        "restricción (" + _WHERE_ES + ").",
    ),
    Message(
        "core.constraint_param_invalid",
        "{name} ({ctype}): «{param}» ({key}) = {value} is not valid: its range is {range}.",
        "{name} ({ctype}): «{param}» ({key}) = {value} no es válido: su rango es {range}.",
    ),
    Message(
        "core.constraint_limit_not_polygon",
        "{name} ({ctype}) is {geometry}: a limit has to be a polygon.",
        "{name} ({ctype}) es {geometry}: un límite ha de ser un polígono.",
    ),
    Message(
        "core.constraint_buffer_not_positive",
        "{name} ({ctype}) is {geometry} with an outward buffer of {value} m: a line or a point "
        "needs a buffer greater than 0 m, or it occupies no cell.",
        "{name} ({ctype}) es {geometry} con un resguardo hacia fuera de {value} m: una línea o "
        "un punto necesita un resguardo mayor que 0 m, o no ocupa ninguna celda.",
    ),
    # Al escribir las filas (D-22; store.py) ---------------------------------------------------
    Message(
        "core.constraint_code_taken",
        "{name}: the code «{value}» is already used by another constraint; a code is unique in "
        "the three constraint layers.",
        "{name}: el código «{value}» ya lo usa otra restricción; un código es único en las "
        "tres capas de restricciones.",
    ),
    Message(
        "core.constraint_code_immutable",
        "{name}: its code is «{old}» and cannot become «{value}»; the parameters of a "
        "constraint hang from its code.",
        "{name}: su código es «{old}» y no puede pasar a ser «{value}»; los parámetros de una "
        "restricción cuelgan de su código.",
    ),
)
"""Todos los mensajes de las restricciones."""

MESSAGES: Mapping[str, Message] = MappingProxyType({m.code: m for m in CATALOG})
"""Los mensajes por código (solo lectura)."""

CATALOG_ES: Mapping[str, str] = MappingProxyType({m.msgid: m.es for m in CATALOG})
"""``msgid`` → español, para ``core.i18n.install`` (solo lectura)."""


def lookup(code: str) -> Message:
    """El mensaje de ``code``; :class:`ValueError` si no está en el catálogo."""
    message = MESSAGES.get(code)
    if message is None:
        raise ValueError(f"el código de mensaje «{code}» no está en el catálogo de las "
                         "restricciones (core/constraints/messages.py)")
    return message


class _Shown(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return MISSING_VALUE


def _show(value: object, language: str) -> str:
    if value is None:
        return MISSING_VALUE
    if isinstance(value, str):
        return value
    return format_value(value, language)


def render(code: str, /, *, language: str = "es", **values: object) -> str:
    """El texto de ``code`` con ``values`` en sus marcadores, en ``language`` (``"es"`` o
    ``"en"``): los números con coma decimal en español. El marcador sin valor queda
    :data:`MISSING_VALUE`. :class:`ValueError` si el código o el idioma no existen."""
    if language not in LANGUAGES:
        raise ValueError(f"el idioma «{language}» no es de Geoblender: {', '.join(LANGUAGES)}")
    message = lookup(code)
    template = message.es if language == "es" else message.msgid
    return template.format_map(_Shown({k: _show(v, language) for k, v in values.items()}))


class ConstraintError(GeoblenderError):
    """Error de las restricciones para el usuario: ``code`` del catálogo, la restricción
    (``name``) como objeto, ``field`` y el valor (``value``), y ``text`` en español, que es
    también ``str(error)``."""

    def __init__(self, code: str, /, *, field: str = "código", **values: object) -> None:
        message = lookup(code)
        self.msgid = message.msgid
        self.values: dict[str, object] = dict(values)
        self.text = render(code, **values)
        name = values.get("name")
        obj = "Restricciones" if name is None else f"Restricción «{name}»"
        super().__init__(code, self.text, obj=obj, field=field, value=values.get("value"),
                         context={k: v if v is None or isinstance(v, str | int | float | bool)
                                  else str(v) for k, v in values.items()})
        self.args = (self.text,)
