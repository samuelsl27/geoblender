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
    # La geometría no válida (RF-012-04; gis.masks.combine) ---------------------------------
    Message(
        "core.constraint_no_geometry",
        "{name} ({ctype}) has no geometry: draw it again in QGIS or create it again from its "
        "layer.",
        "{name} ({ctype}) no tiene geometría: vuelva a dibujarla en QGIS o a crearla desde su "
        "capa.",
    ),
    Message(
        "core.constraint_self_intersecting",
        "{name} ({ctype}) is {geometry} that cuts or touches itself: correct its vertices in "
        "QGIS.",
        "{name} ({ctype}) es {geometry} que se corta o se toca a sí mismo: corrija sus vértices "
        "en QGIS.",
    ),
    Message(
        "core.constraint_no_area",
        "{name} ({ctype}) is {geometry} without area: correct its vertices in QGIS.",
        "{name} ({ctype}) es {geometry} sin área: corrija sus vértices en QGIS.",
    ),
    Message(
        "core.constraint_hole_outside",
        "{name} ({ctype}) has a hole outside its outline or inside another hole: correct it in "
        "QGIS.",
        "{name} ({ctype}) tiene un hueco fuera de su contorno o dentro de otro hueco: "
        "corríjalo en QGIS.",
    ),
    Message(
        "core.constraint_parts_overlap",
        "{name} ({ctype}): two of its parts overlap: join them or correct them in QGIS.",
        "{name} ({ctype}): dos de sus partes se solapan: únalas o corríjalas en QGIS.",
    ),
    Message(
        "core.constraint_no_length",
        "{name} ({ctype}) is {geometry} without length: correct its vertices in QGIS.",
        "{name} ({ctype}) es {geometry} sin longitud: corrija sus vértices en QGIS.",
    ),
    # Combinar (RF-012-04, RF-012-15; gis.masks.combine y gis.masks.overlay) -------------------
    Message(
        "core.constraint_incomplete",
        "The masks cannot be compiled: {count} problems in the constraints. {items}",
        "No se pueden compilar las máscaras: {count} problemas en las restricciones. {items}",
    ),
    Message(
        "core.constraint_no_grid",
        "The masks cannot be compiled: the project has no grid; create it with «Project grid "
        "from a DTM…» ({command}).",
        "No se pueden compilar las máscaras: el proyecto no tiene rejilla; créela con "
        "«Rejilla de proyecto desde un MDT…» ({command}).",
    ),
    Message(
        "core.constraint_no_legal_limit",
        "The masks cannot be compiled: there is no active legal limit; declare it in Design ▸ "
        "Legal limits and constraints ▸ Limits… ({command}).",
        "No se pueden compilar las máscaras: no hay ningún límite legal activo; declárelo en "
        "Diseño ▸ Límites y restricciones ▸ Límites… ({command}).",
    ),
    Message(
        "core.constraint_perimeter_from_legal",
        "There is no action perimeter: the legal limit ({name}) is taken as the perimeter; "
        "declare it in Limits… ({command}) if the works are smaller.",
        "No hay perímetro de actuación: se toma como perímetro el límite legal ({name}); "
        "declárelo en Límites… ({command}) si la actuación es menor.",
    ),
    Message(
        "core.constraint_zone_outside_grid",
        "{name} ({ctype}): {area} m² of its zone fall outside the project grid and are not in "
        "the masks; widen the working window if they matter.",
        "{name} ({ctype}): {area} m² de su zona quedan fuera de la rejilla del proyecto y no "
        "están en las máscaras; amplíe la ventana de trabajo si importan.",
    ),
    Message(
        "core.constraint_strip_part",
        "Part of the action perimeter outside the legal limit: {area} m² ({hectares} ha) "
        "centred at X {x}, Y {y}; only fill is allowed there.",
        "Parte del perímetro de actuación fuera del límite legal: {area} m² ({hectares} ha) "
        "con centro en X {x}, Y {y}; allí solo se admite relleno.",
    ),
    # Pedir las máscaras (RF-012-17; gis.masks.access) -----------------------------------------
    Message(
        "core.constraint_masks_missing",
        "The masks of {version} have not been compiled; compile them in Design ▸ Legal limits "
        "and constraints ▸ Constraints… ({command}).",
        "Las máscaras de {version} no se han compilado; compílelas en Diseño ▸ Límites y "
        "restricciones ▸ Restricciones… ({command}).",
    ),
    Message(
        "core.constraint_masks_stale",
        "The masks of {version} are stale: a constraint, a sector, a search or a parameter "
        "changed after compiling them; compile them again ({command}).",
        "Las máscaras de {version} están obsoletas: cambió una restricción, un sector, una "
        "búsqueda o un parámetro después de compilarlas; compílelas de nuevo ({command}).",
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
