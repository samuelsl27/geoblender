# SPDX-License-Identifier: GPL-3.0-or-later
"""Mensajes del diseño (spec 013; plan 013 §5.1, §5.3.1 y §5.5; constitución, principio 10).

Cada rechazo, aviso o nota que ``design`` puede mostrar tiene un **código** estable en inglés con
el prefijo ``des.`` (``"des.profile_value_range"``), un ``msgid`` en inglés (también su versión
inglesa) y su texto en español, con marcadores de ``str.format`` con nombre en inglés, los mismos
en los dos. El texto nombra el objeto (el perfil, el sector), el campo (la clave del parámetro) y
el valor, y dice qué hacer; el marcador ``{value}`` es siempre el valor que se rechaza (el
``value`` de :class:`DesignError`) y ``{field}``, su campo.

- :class:`Message`: un mensaje del catálogo, con su gravedad (:data:`SEVERITIES`): ``"error"`` se
  lanza como :class:`DesignError`; ``"warning"`` se informa (el cálculo sigue); ``"note"`` es un
  texto corto que acompaña a una fila de una tabla o a un elemento de una lista. :data:`CATALOG`,
  todos; :data:`MESSAGES`, por código.
- :data:`CATALOG_ES`: ``msgid`` → español, para ``core.i18n.install`` al registrar.
- :func:`render`: el texto de un código con sus valores, en español o en inglés.
- :class:`DesignError`: el error para el usuario, con código, ``msgid``, valores (JSON), objeto,
  campo y valor (un ``GeoblenderError``).

Las cifras de un mensaje llegan ya redondeadas como números (:func:`render` los escribe en el
formato del idioma: coma decimal en español, punto en inglés). Cada tarea de la spec añade aquí los
códigos que necesite (superficies, semillas, sectores, envolventes…); esta primera trae los de los
perfiles de banco (RF-013-19, RF-013-20) y el del talud impuesto por sector (RF-013-08).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ..core.errors import GeoblenderError
from ..core.i18n import LANGUAGES
from ..gis.messages import MISSING_VALUE, JsonScalar, format_value, json_value

__all__ = [
    "CATALOG",
    "CATALOG_ES",
    "MESSAGES",
    "SEVERITIES",
    "DesignError",
    "Message",
    "lookup",
    "render",
]

SEVERITIES = ("error", "warning", "note")
"""Las gravedades de un mensaje: se lanza, se informa o acompaña a una fila o a una lista."""


@dataclass(frozen=True, slots=True)
class Message:
    """Un mensaje del catálogo: código ``des.*``, ``msgid`` en inglés, texto en español y
    gravedad (una de :data:`SEVERITIES`)."""

    code: str
    msgid: str
    es: str
    severity: str = "error"


CATALOG: tuple[Message, ...] = (
    # Perfiles de banco (RF-013-18, RF-013-19, RF-013-20; D-7, D-17) ---------------------------
    Message(
        "des.profile_name_missing",
        "Bench profile «{profile}» has no name; give it one, for example EXPL_10_60_6.",
        "El perfil de banco «{profile}» no tiene nombre; póngale uno, por ejemplo EXPL_10_60_6.",
    ),
    Message(
        "des.profile_name_repeated",
        "Bench profile «{profile}» has the name «{value}», which profile «{other}» already "
        "has; give each profile its own name.",
        "El perfil de banco «{profile}» se llama «{value}», como el perfil «{other}»; dé a cada "
        "perfil su propio nombre.",
    ),
    Message(
        "des.profile_value_missing",
        "Bench profile «{profile}»: «{field}» has no value and has no default; declare it in "
        "Design ▸ Parameters ▸ Bench profiles… before calculating.",
        "Perfil de banco «{profile}»: «{field}» no tiene valor ni lleva ninguno por defecto; "
        "declárelo en Diseño ▸ Parámetros ▸ Perfiles de banco… antes de calcular.",
    ),
    Message(
        "des.profile_value_range",
        "Bench profile «{profile}»: «{field}» = {value} is outside its range {range}; nothing "
        "is calculated with this profile.",
        "Perfil de banco «{profile}»: «{field}» = {value} está fuera de su rango {range}; no se "
        "calcula nada con este perfil.",
    ),
    Message(
        "des.profile_unresolved",
        "Bench profile «{profile}» is not resolved by the grid: in plan its face takes "
        "{face} m and its berm {berm} m, and the grid step is {step} m; a face or a berm "
        "narrower than a cell cannot be drawn.",
        "El perfil de banco «{profile}» no está resuelto por la rejilla: en planta su cara ocupa "
        "{face} m y su berma {berm} m, y el paso de la rejilla es {step} m; una cara o una berma "
        "más estrecha que una celda no se puede dibujar.",
        "warning",
    ),
    # Talud general máximo impuesto por un sector (RF-013-08; ADR-0029) ------------------------
    Message(
        "des.sector_slope_range",
        "Sector «{sector}»: the maximum general slope «{field}» = {value} is outside its range "
        "{range}.",
        "Sector «{sector}»: el talud general máximo «{field}» = {value} está fuera de su rango "
        "{range}.",
    ),
)

MESSAGES: Mapping[str, Message] = MappingProxyType({m.code: m for m in CATALOG})
"""Los mensajes por código (solo lectura)."""

CATALOG_ES: Mapping[str, str] = MappingProxyType({m.msgid: m.es for m in CATALOG})
"""``msgid`` → texto en español, para ``core.i18n.install`` (solo lectura)."""


def _check_catalog() -> None:
    """Un catálogo incoherente es un error del programa: códigos o ``msgid`` repetidos, un
    código que no es ``des.*`` o una gravedad desconocida."""
    if len(MESSAGES) != len(CATALOG) or len(CATALOG_ES) != len(CATALOG):
        raise ValueError("códigos o msgid repetidos en el catálogo del diseño")
    for message in CATALOG:
        if not message.code.startswith("des.") or message.severity not in SEVERITIES:
            raise ValueError(f"mensaje del diseño mal declarado: «{message.code}»")


_check_catalog()


def lookup(code: str) -> Message:
    """El mensaje de ``code``; :class:`ValueError` si no está en el catálogo (un error del
    programa: todo mensaje de ``design`` tiene aquí su texto en español)."""
    message = MESSAGES.get(code)
    if message is None:
        raise ValueError(
            f"el código de mensaje «{code}» no está en el catálogo del diseño "
            "(design/messages.py)"
        )
    return message


def render(code: str, /, *, language: str = "es", **values: object) -> str:
    """El texto de ``code`` con ``values`` en sus marcadores, en ``language`` (``"es"`` o
    ``"en"``, el ``msgid``). El marcador sin valor queda «?»; los valores que sobran se
    ignoran. Los decimales salen con coma en español y con punto en inglés."""
    if language not in LANGUAGES:
        raise ValueError(f"el idioma «{language}» no es de Geoblender: {', '.join(LANGUAGES)}")
    message = lookup(code)
    template = message.es if language == "es" else message.msgid
    shown = _Shown({name: format_value(value, language) for name, value in values.items()})
    return template.format_map(shown)


class DesignError(GeoblenderError):
    """Error del diseño para el usuario: ``code`` del catálogo, ``msgid``, ``values`` (JSON, para
    el registro y para mostrarlo en otro idioma con :func:`render`), el objeto, el campo y el valor
    (``GeoblenderError``) y ``text`` en español, que es también ``str(error)`` y ``message``. El
    valor es el marcador ``{value}`` del texto y el campo, ``{field}``. Un código de aviso o de
    nota no es un error: :class:`ValueError`."""

    def __init__(
        self,
        code: str,
        /,
        *,
        obj: str,
        field: str,
        value: object = None,
        **values: object,
    ) -> None:
        message = lookup(code)
        if message.severity != "error":
            raise ValueError(f"«{code}» es un {message.severity}, no un error: no se lanza")
        shown = {"field": field, "value": value, **values}
        self.msgid = message.msgid
        self.values: dict[str, JsonScalar] = {k: json_value(v) for k, v in shown.items()}
        self.text = render(code, **shown)
        super().__init__(code, self.text, obj=obj, field=field, value=value,
                         context=self.values)
        self.args = (self.text,)


class _Shown(dict[str, str]):
    """Valores ya presentados; el que falta se ve como «?» (nunca el marcador ``{…}``)."""

    def __missing__(self, key: str) -> str:
        return MISSING_VALUE
