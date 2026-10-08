# SPDX-License-Identifier: GPL-3.0-or-later
"""Mensajes de la procedencia (spec 008 §8; plan 008 §3, principio 10, y §5.1).

Cada error de la procedencia que llega a una persona tiene un **código** estable en inglés
(``"core.operation_unregistered"``), un ``msgid`` en inglés (también su versión inglesa) y su
texto en español, con marcadores de ``str.format`` (``{op_type}``) con nombre en inglés, los
mismos en los dos (constitución, principio 10). Los nombres visibles de las operaciones de
``core`` (:data:`LABELS`) son también ``msgid`` con su español.

- :class:`Message`: un mensaje del catálogo; :data:`MESSAGES`, el catálogo por código.
- :data:`LABELS`: ``msgid`` → español de los nombres visibles de ``core``
  (``OperationDef.label_msgid`` de :mod:`.contract`).
- :data:`CATALOG_ES`: ``msgid`` → español de todo lo anterior, para ``core.i18n.install`` al
  registrar (``bl/ops/core_provenance.py``, T44).
- :func:`render`: el texto de un código con sus valores, en español o en inglés; el marcador
  sin valor queda «?».
- :class:`ProvenanceError`: el error de la procedencia para el usuario, con código,
  ``msgid``, valores (JSON) y texto; en solo lectura, todo lo que escribiría lanza
  ``core.read_only`` sin tocar nada (plan §5.3.1).

Cada tarea de la 008 añade aquí los códigos de sus rechazos (los textos de la spec §8, tal
cual). Python puro (ADR-0004).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ..errors import GeoblenderError
from ..i18n import LANGUAGES

type JsonScalar = str | int | float | bool | None

MISSING_VALUE = "?"
"""Lo que se ve en lugar de un valor que falta (nunca el marcador ``{…}``)."""

ERROR_OBJECT = "Procedencia"
"""El objeto de un :class:`ProvenanceError` (``GeoblenderError.obj``)."""


@dataclass(frozen=True, slots=True)
class Message:
    """Un mensaje del catálogo: código ``core.*``, ``msgid`` en inglés y texto en español."""

    code: str
    msgid: str
    es: str


_INACTIVE_EN = (
    "the module that declares it is not active or belongs to another version of Geoblender."
)
_INACTIVE_ES = (
    "el módulo que {pronoun} declara no está activo o es de otra versión de Geoblender."
)

_CATALOG: tuple[Message, ...] = (
    Message(
        "core.read_only",
        "Project «{project}» is open read-only ({reason}): nothing has been recorded.",
        "El proyecto «{project}» está abierto en solo lectura ({reason}): no se ha registrado "
        "nada.",
    ),
    Message(
        "core.operation_unregistered",
        "No operation of type «{op_type}» is registered: " + _INACTIVE_EN,
        "No hay ninguna operación registrada del tipo «{op_type}»: "
        + _INACTIVE_ES.format(pronoun="la"),
    ),
    Message(
        "core.group_unregistered",
        "No group of coupled operations «{group}» is registered: " + _INACTIVE_EN,
        "No hay ningún grupo de operaciones acopladas «{group}» registrado: "
        + _INACTIVE_ES.format(pronoun="lo"),
    ),
    Message(
        "core.figure_unregistered",
        "No figure «{key}» is registered: " + _INACTIVE_EN,
        "No hay ninguna cifra «{key}» registrada: " + _INACTIVE_ES.format(pronoun="la"),
    ),
    Message(
        "core.importer_unregistered",
        "No importer is registered for reader «{reader}»: its inputs cannot be reimported "
        "until the module that declares it is active.",
        "No hay ningún importador registrado para el lector «{reader}»: sus entradas no se "
        "pueden reimportar hasta que esté activo el módulo que lo declara.",
    ),
)

MESSAGES: Mapping[str, Message] = MappingProxyType({m.code: m for m in _CATALOG})
"""Los mensajes por código (solo lectura)."""

EXTERNAL_EDIT_MSGID = "External edit"
ACCEPT_REVIEW_MSGID = "Accept as good"
IMPORT_LAYER_MSGID = "Register layer as input"

LABELS: Mapping[str, str] = MappingProxyType({
    EXTERNAL_EDIT_MSGID: "Edición externa",
    ACCEPT_REVIEW_MSGID: "Dar por buena",
    IMPORT_LAYER_MSGID: "Registrar la capa como entrada",
})
"""Nombres visibles de las operaciones de ``core``: ``msgid`` → español (solo lectura)."""

CATALOG_ES: Mapping[str, str] = MappingProxyType(
    {**{m.msgid: m.es for m in _CATALOG}, **LABELS}
)
"""``msgid`` → español de los mensajes y los nombres visibles, para ``core.i18n.install``
(solo lectura)."""


def lookup(code: str) -> Message:
    """El mensaje de ``code``; :class:`ValueError` si no está en el catálogo (un error del
    programa: todo error de la procedencia tiene aquí su texto en español)."""
    message = MESSAGES.get(code)
    if message is None:
        raise ValueError(
            f"el código de mensaje «{code}» no está en el catálogo de la procedencia "
            "(core/provenance/messages.py)"
        )
    return message


def render(code: str, /, *, language: str = "es", **values: object) -> str:
    """El texto de ``code`` con ``values`` en sus marcadores, en ``language`` (``"es"`` o
    ``"en"``, el ``msgid``). El marcador sin valor queda :data:`MISSING_VALUE`; los valores
    que sobran se ignoran. :class:`ValueError` si el código o el idioma no existen."""
    if language not in LANGUAGES:
        raise ValueError(f"el idioma «{language}» no es de Geoblender: {', '.join(LANGUAGES)}")
    message = lookup(code)
    template = message.es if language == "es" else message.msgid
    shown = _Shown({name: _show(value, language) for name, value in values.items()})
    return template.format_map(shown)


def json_value(value: object) -> JsonScalar:
    """``value`` como se guarda en el registro (JSON): los escalares tal cual y lo demás
    como texto."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


class ProvenanceError(GeoblenderError):
    """Error de la procedencia para el usuario: ``code`` del catálogo, ``msgid``, ``values``
    (JSON, para el registro y para mostrarlo en otro idioma con :func:`render`) y ``text`` en
    español, que es también ``str(error)`` y ``message``."""

    def __init__(self, code: str, /, **values: object) -> None:
        message = lookup(code)
        self.msgid = message.msgid
        self.values: dict[str, JsonScalar] = {k: json_value(v) for k, v in values.items()}
        self.text = render(code, **self.values)
        super().__init__(code, self.text, obj=ERROR_OBJECT, field="código", value=code,
                         context=self.values)
        self.args = (self.text,)


class _Shown(dict[str, str]):
    """Valores ya presentados; el que falta se ve como :data:`MISSING_VALUE`."""

    def __missing__(self, key: str) -> str:
        return MISSING_VALUE


def _show(value: object, language: str) -> str:
    """Un valor como lo lee una persona en ``language``: decimales con coma en español."""
    if value is None:
        return MISSING_VALUE
    if isinstance(value, bool):
        if language == "es":
            return "sí" if value else "no"
        return "yes" if value else "no"
    if isinstance(value, float):
        text = str(int(value)) if value.is_integer() else repr(value)
        return text.replace(".", ",") if language == "es" else text
    return str(value)
