# SPDX-License-Identifier: GPL-3.0-or-later
"""Definiciones de parámetros tipados (spec 008; RF-008-01, RF-008-03; plan 008 §5.3.1 y
§5.3.4; ADR-0013).

Cada valor que cambia un resultado de un módulo (una tolerancia, un K de esponjamiento, un
límite) es un **parámetro** con clave, tipo de valor, unidad, rango, valor por defecto, tipo
y procedencia. Su módulo lo **declara** con :class:`ParamDef` en ``<paquete>/params.py`` y lo
registra desde ``bl/`` con :func:`register_definitions` (``core`` no importa los módulos,
ADR-0004). Los valores del proyecto y su historial los guarda ``ParameterStore``
(:mod:`.store`).

- :class:`ParamKind`, :class:`ValueType` y :class:`SourceKind`: los códigos de
  ``gb_parameter.kind``, ``value_type`` y ``source_kind`` (``HIPÓTESIS`` con tilde, como
  ADR-0013).
- :class:`ParamDef`: la definición, comprobada al declararla (una incoherente es un error del
  programa: :class:`ValueError`). :meth:`ParamDef.check` comprueba un valor del programa y lo
  devuelve normalizado; :meth:`ParamDef.range_text` (o :func:`format_range` desde sus
  campos), el rango como se lee.
- :func:`parse_value`: un valor **tecleado** con su unidad, convertido a la declarada
  («35 %» en una fracción es 0,35; RF-008-03).
- :class:`ParamError`: el rechazo para el usuario, con un código ``core.param_*`` y su texto
  (:data:`MESSAGES`, :data:`CATALOG_ES` y :func:`render`).
- :data:`DEFINITIONS`, :func:`register_definitions` y :func:`unregister_definitions`: las
  definiciones registradas, por clave.

**Compatibilidad con la 006** (plan §5.3.4, I-1): la spec 006 declaró sus 17 parámetros con
un ``ParamDef`` provisional en ``gis/params.py`` (commit ``39b28f1``). Este tiene su misma
firma (``key, value_type, unit, default, minimum, maximum, requirements, source`` y, con su
nombre, ``min_exclusive``, ``length``, ``kind`` y ``source_kind``), los mismos tipos ``float``,
``int`` y ``json`` (una lista de ``length`` números en orden creciente) y los mismos
``check()`` y ``range_text()``: el mismo valor normalizado y los mismos textos, con los códigos
``core.param_*`` en lugar de ``gis.param_*``. Solo cambia lo que la provisional no tenía:
``None`` es «falta el valor» (``core.param_missing``) y el rango se escribe con el símbolo de
la unidad en español («m³»; las de la 006, m, s y %, se escriben igual).
"""

from __future__ import annotations

import math
import numbers
import re
import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import KW_ONLY, dataclass
from enum import StrEnum
from itertools import pairwise
from types import MappingProxyType

from ..catalog.schema import MODULE_CODES
from ..errors import ValidationError
from ..i18n import LANGUAGES, THIN_SPACE
from ..units import DIMENSIONLESS, UNITS, UnitError, convert, parse_quantity, symbol

type ParamValue = float | int | bool | str | tuple[float, ...]
"""Un valor normalizado: ``float``, ``int``, ``bool``, ``str`` o tupla de ``float``."""

type JsonScalar = str | int | float | bool | None


class ParamKind(StrEnum):
    """El tipo de un parámetro o de una cifra (principio 2; ``gb_parameter.kind``)."""

    MEDIDO = "MEDIDO"
    CALCULADO = "CALCULADO"
    ADOPTADO = "ADOPTADO"
    HIPOTESIS = "HIPÓTESIS"


DEFAULT_KINDS: tuple[ParamKind, ...] = (ParamKind.ADOPTADO, ParamKind.HIPOTESIS)
"""Los tipos de un valor por defecto: lo MEDIDO lo mide alguien y lo CALCULADO lo produce una
operación (spec §6; RF-008-04)."""


class ValueType(StrEnum):
    """El tipo de valor (``gb_parameter.value_type``; RF-008-03: número, entero, sí/no,
    texto o estructurado)."""

    FLOAT = "float"
    INT = "int"
    BOOL = "bool"
    TEXT = "text"
    JSON = "json"


class SourceKind(StrEnum):
    """La clase del origen de un parámetro (``gb_parameter.source_kind``; RF-008-01)."""

    DOCUMENT = "document"
    STANDARD = "standard"
    PERSON = "person"
    OPERATION = "operation"
    ALGORITHM = "algorithm"


SCOPES: tuple[str, ...] = ("project", "version")
"""Dónde vive el valor de un parámetro: en el proyecto o, con la spec 009, en cada versión."""

_NUMERIC = (ValueType.FLOAT, ValueType.INT, ValueType.JSON)
_KEY = re.compile(r"(?P<module>[a-z]+)(\.[a-z][a-z0-9_]*)+")
_OBJ = "Parámetro"
_TRUE_TEXTS = frozenset({"sí", "si", "yes", "true", "verdadero", "1"})
_FALSE_TEXTS = frozenset({"no", "false", "falso", "0"})

# --- Mensajes -------------------------------------------------------------------------------

MISSING_VALUE = "?"
"""Lo que se ve en lugar de un valor que falta (nunca el marcador ``{…}``)."""


@dataclass(frozen=True, slots=True)
class Message:
    """Un mensaje: código ``core.param_*``, ``msgid`` en inglés y texto en español."""

    code: str
    msgid: str
    es: str


_CATALOG: tuple[Message, ...] = (
    # Los cuatro de la provisional de la 006 (gis/messages.py, 39b28f1), tal cual.
    Message(
        "core.param_not_number",
        "Parameter «{key}»: «{value}» is not a number.",
        "Parámetro «{key}»: «{value}» no es un número.",
    ),
    Message(
        "core.param_not_integer",
        "Parameter «{key}»: «{value}» is not a whole number.",
        "Parámetro «{key}»: «{value}» no es un número entero.",
    ),
    Message(
        "core.param_not_list",
        "Parameter «{key}»: «{value}» is not a list of {length} numbers in ascending order.",
        "Parámetro «{key}»: «{value}» no es una lista de {length} números en orden creciente.",
    ),
    Message(
        "core.param_out_of_range",
        "Parameter «{key}»: {value} is outside its range {range}.",
        "Parámetro «{key}»: {value} está fuera de su rango {range}.",
    ),
    # Los de esta spec (spec §8; RF-008-03).
    Message(
        "core.param_missing",
        "{key}: the value is missing; this parameter does not admit «no value».",
        "{key}: falta el valor; este parámetro no admite «sin valor».",
    ),
    Message(
        "core.param_not_finite",
        "Parameter «{key}»: «{value}» is not a finite number.",
        "Parámetro «{key}»: «{value}» no es un número finito.",
    ),
    Message(
        "core.param_not_bool",
        "Parameter «{key}»: «{value}» is neither «yes» nor «no».",
        "Parámetro «{key}»: «{value}» no es «sí» ni «no».",
    ),
    Message(
        "core.param_not_text",
        "Parameter «{key}»: «{value}» is not a text.",
        "Parámetro «{key}»: «{value}» no es un texto.",
    ),
    Message(
        "core.param_not_choice",
        "Parameter «{key}»: «{value}» is not one of its options: {choices}.",
        "Parámetro «{key}»: «{value}» no es una de sus opciones: {choices}.",
    ),
    Message(
        "core.param_unit_unknown",
        "Parameter «{key}»: unit «{from_unit}» of «{value}» is not in Geoblender's unit "
        "catalog.",
        "Parámetro «{key}»: la unidad «{from_unit}» de «{value}» no está en el catálogo de "
        "unidades de Geoblender.",
    ),
    Message(
        "core.param_unit_not_convertible",
        "Parameter «{key}»: «{value}» is in «{from_symbol}», which cannot be converted to the "
        "parameter's unit, «{to_symbol}»; its range is {range}.",
        "Parámetro «{key}»: «{value}» está en «{from_symbol}», que no se convierte a la unidad "
        "del parámetro, «{to_symbol}»; su rango es {range}.",
    ),
    # Los del registro de valores (store.py; spec §8, RF-008-01, RF-008-02, RF-008-04).
    Message(
        "core.param_kind_missing",
        "Parameter «{key}» needs a type: MEASURED, CALCULATED, ADOPTED or HYPOTHESIS.",
        "El parámetro «{key}» necesita un tipo: MEDIDO, CALCULADO, ADOPTADO o HIPÓTESIS.",
    ),
    Message(
        "core.param_kind_unknown",
        "Parameter «{key}» has type «{value}», which is not MEASURED, CALCULATED, ADOPTED or "
        "HYPOTHESIS.",
        "El parámetro «{key}» tiene el tipo «{value}», que no es MEDIDO, CALCULADO, ADOPTADO "
        "ni HIPÓTESIS.",
    ),
    Message(
        "core.param_calculated_by_hand",
        "{key}: a CALCULATED parameter is written by an operation; to set it by hand, choose "
        "ADOPTED or HYPOTHESIS.",
        "{key}: un parámetro CALCULADO lo escribe una operación; para fijarlo a mano, elija "
        "ADOPTADO o HIPÓTESIS.",
    ),
    Message(
        "core.param_reason_missing",
        "State the reason for the change of «{key}» ({change}).",
        "Indique el motivo del cambio de «{key}» ({change}).",
    ),
    Message(
        "core.param_reason_missing_new",
        "State the reason for the value of «{key}» ({shown}).",
        "Indique el motivo del valor de «{key}» ({shown}).",
    ),
    Message(
        "core.param_source_missing",
        "State the source of «{key}»: a document, a standard, a person, an operation or an "
        "algorithm.",
        "Indique el origen de «{key}»: un documento, una norma, una persona, una operación o "
        "un algoritmo.",
    ),
    Message(
        "core.param_source_kind_unknown",
        "The source of «{key}» is a document, a standard, a person, an operation or an "
        "algorithm, not «{value}».",
        "El origen de «{key}» es un documento, una norma, una persona, una operación o un "
        "algoritmo, no «{value}».",
    ),
    Message(
        "core.param_decided_by_missing",
        "State who decided the value of «{key}».",
        "Indique quién decidió el valor de «{key}».",
    ),
    Message(
        "core.param_exists",
        "Parameter «{key}» is already registered in the project: change it instead of "
        "creating it again.",
        "El parámetro «{key}» ya está registrado en el proyecto: cámbielo en lugar de darlo "
        "de alta otra vez.",
    ),
    Message(
        "core.param_not_registered",
        "Parameter «{key}» is not registered in the project.",
        "El parámetro «{key}» no está registrado en el proyecto.",
    ),
    Message(
        "core.param_undefined",
        "No loaded module declares parameter «{key}»: its value cannot be checked.",
        "Ningún módulo cargado declara el parámetro «{key}»: no se puede comprobar su valor.",
    ),
    Message(
        "core.param_unchanged",
        "Parameter «{key}» already has that value, type, source and decision maker: there is "
        "nothing to change.",
        "El parámetro «{key}» ya tiene ese valor, tipo, origen y decisor: no hay nada que "
        "cambiar.",
    ),
    Message(
        "core.param_nothing_to_confirm",
        "Parameter «{key}» is neither «unconfirmed» nor «to review»: there is nothing to "
        "confirm.",
        "El parámetro «{key}» no está «sin confirmar» ni «revisar»: no hay nada que "
        "confirmar.",
    ),
    # «Revisar» por un cambio de definición (store.py; RF-008-60).
    Message(
        "core.param_review_changed",
        "The definition of «{key}» has changed ({change}); its registered value has not been "
        "touched.",
        "La definición de «{key}» ha cambiado ({change}); su valor registrado no se ha "
        "tocado.",
    ),
    Message(
        "core.param_review_undeclared",
        "No loaded module declares «{key}» any more; its registered value has not been "
        "touched.",
        "Ningún módulo cargado declara ya «{key}»; su valor registrado no se ha tocado.",
    ),
    Message(
        "core.param_review_mismatch",
        "{key}: the registered value, {shown}, is not in the unit or the value type of its "
        "current definition ({expected}): change it instead of confirming it.",
        "{key}: el valor registrado, {shown}, no está en la unidad o el tipo de valor de su "
        "definición actual ({expected}): cámbielo en lugar de confirmarlo.",
    ),
    # El ámbito de versión (store.py; spec 009, RF-009-24, RF-009-29; D-19).
    Message(
        "core.param_project_only",
        "Parameter «{key}» belongs to the project: it does not take a value of its own in "
        "{version}.",
        "El parámetro «{key}» es del proyecto: no admite un valor propio en {version}.",
    ),
    Message(
        "core.param_figure_unknown",
        "Figure «{figure}» is not in the project: it cannot be adopted as the value of "
        "«{key}».",
        "La cifra «{figure}» no está en el proyecto: no se puede adoptar como valor de "
        "«{key}».",
    ),
    Message(
        "core.param_figure_other",
        "Figure «{figure}» of operation «{operation}» does not calculate «{key}»: only the "
        "figure that calculates this parameter can be adopted.",
        "La cifra «{figure}» de la operación «{operation}» no calcula «{key}»: solo se adopta "
        "la cifra que calcula este parámetro.",
    ),
)

MESSAGES: Mapping[str, Message] = MappingProxyType({m.code: m for m in _CATALOG})
"""Los mensajes por código (solo lectura)."""

CATALOG_ES: Mapping[str, str] = MappingProxyType({m.msgid: m.es for m in _CATALOG})
"""``msgid`` → español, para ``core.i18n.install`` (solo lectura)."""


_INTEGER_PART = re.compile(r"([+-]?)(\d{4,})")
"""La parte entera de un número escrito por Python, si tiene miles."""


def format_value(value: object, language: str = "es", *, grouped: bool = True) -> str:
    """Un valor como lo lee una persona en ``language``: un decimal con coma en español
    (``0.25`` → ``0,25``), con todos sus decimales, y sin ellos si es entero (``2.0`` →
    ``2``); un booleano, «sí» o «no»; ``None``, :data:`MISSING_VALUE`; lo demás, su texto
    (como la provisional).

    Un número (real o entero) lleva el separador de miles de las cifras (spec 003, II §2.4;
    spec 008, T71): espacio fino en español (``500 000``) y coma en inglés (``500,000``). Sin
    ``grouped``, sin él: como se teclea en un diálogo, que lo vuelve a leer igual en los dos
    idiomas, o el valor de un ámbito («2026»)."""
    if value is None:
        return MISSING_VALUE
    if isinstance(value, bool):
        if language == "es":
            return "sí" if value else "no"
        return "yes" if value else "no"
    if isinstance(value, float):
        text = str(int(value)) if value.is_integer() else repr(value)
    elif isinstance(value, int):
        text = str(value)
    else:
        return str(value)
    if grouped:
        text = _grouped(text, THIN_SPACE if language == "es" else ",")
    return text.replace(".", ",") if language == "es" else text


def _grouped(text: str, separator: str) -> str:
    """``text`` (un número escrito por Python: «-1234567.5», «1e-05», «inf») con
    ``separator`` entre los miles de su parte entera."""
    found = _INTEGER_PART.match(text)
    if found is None:
        return text
    sign, digits = found.groups()
    return sign + f"{int(digits):,}".replace(",", separator) + text[found.end():]


def render(code: str, /, *, language: str = "es", **values: object) -> str:
    """El texto de ``code`` con ``values`` en sus marcadores, en ``language`` (``"es"`` o
    ``"en"``, el ``msgid``). El marcador sin valor queda :data:`MISSING_VALUE`; los valores
    que sobran se ignoran. :class:`ValueError` si el código o el idioma no existen."""
    if language not in LANGUAGES:
        raise ValueError(f"el idioma «{language}» no es de Geoblender: {', '.join(LANGUAGES)}")
    message = MESSAGES.get(code)
    if message is None:
        raise ValueError(f"el código de mensaje «{code}» no es de core.params")
    template = message.es if language == "es" else message.msgid
    shown = _Shown({name: format_value(value, language) for name, value in values.items()})
    return template.format_map(shown)


class _Shown(dict[str, str]):
    """Valores ya presentados; el que falta se ve como :data:`MISSING_VALUE`."""

    def __missing__(self, key: str) -> str:
        return MISSING_VALUE


def _json_value(value: object) -> JsonScalar:
    """``value`` como se guarda en el registro (JSON): los escalares tal cual y lo demás (una
    tupla) como texto."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


class ParamError(ValidationError):
    """Un valor de parámetro que no vale (RF-008-03): ``code`` (``core.param_*``),
    ``msgid``, ``values`` (JSON: la clave, el valor, la unidad declarada, el rango y lo
    propio de cada código), el objeto «Parámetro», el campo (la clave) y el valor, y ``text``
    en español, que es también ``str(error)``."""

    def __init__(self, code: str, /, *, key: str, value: object = None,
                 **values: object) -> None:
        message = MESSAGES.get(code)
        if message is None:
            raise ValueError(f"el código de mensaje «{code}» no es de core.params")
        shown = {"key": key, "value": value, **values}
        self.msgid = message.msgid
        self.key = key
        self.values: dict[str, JsonScalar] = {k: _json_value(v) for k, v in shown.items()}
        self.text = render(code, **shown)
        super().__init__(code, self.text, obj=_OBJ, field=key, value=value,
                         context=self.values)
        self.args = (self.text,)


# --- Definición -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParamDef:
    """La definición de un parámetro, que declara su módulo.

    ``key`` (``<código>.<nombre>[.<más>]``, con un código de módulo de
    ``docs/sdd/convenciones.md`` §5; :attr:`module` se deduce de ella), ``value_type``
    (:class:`ValueType`), ``unit`` (código del catálogo de ``core.units``; ``-`` si es
    adimensional, y siempre ``-`` en un sí/no o un texto), ``default`` (ya normalizado;
    ``None`` solo con ``allow_empty``), rango de ``minimum`` a ``maximum`` (incluidos, salvo
    ``minimum`` con ``min_exclusive``; ``None``, abierto; solo en los números y las listas),
    ``requirements`` (los RF que lo usan) y ``source`` (de dónde sale el valor por defecto).
    Con su nombre: ``length`` (los elementos de un ``json``), ``kind`` (el tipo del valor por
    defecto: ADOPTADO o HIPÓTESIS), ``source_kind``, ``allow_empty`` (admite «sin valor»),
    ``choices`` (los textos admitidos de un ``text``), ``scope`` (``project`` o ``version``) y
    los ``msgid`` de su etiqueta y su descripción.

    ``value_type``, ``kind`` y ``source_kind`` se guardan como sus ``StrEnum`` (iguales a su
    texto). Una definición incoherente es un error del programa: :class:`ValueError`.
    """

    key: str
    value_type: ValueType | str
    unit: str
    default: ParamValue | None
    minimum: float | None = None
    maximum: float | None = None
    requirements: tuple[str, ...] = ()
    source: str = ""
    _: KW_ONLY
    min_exclusive: bool = False
    length: int | None = None
    kind: ParamKind | str = ParamKind.ADOPTADO
    source_kind: SourceKind | str = SourceKind.ALGORITHM
    allow_empty: bool = False
    choices: tuple[str, ...] = ()
    scope: str = "project"
    label_msgid: str | None = None
    description_msgid: str | None = None

    def __post_init__(self) -> None:
        problem = self._normalize() or self._problem()
        if problem is None:
            try:
                checked = self.check(self.default)
            except ParamError as exc:
                problem = f"su valor por defecto no es válido ({exc})"
            else:
                if checked != self.default or type(checked) is not type(self.default):
                    problem = f"su valor por defecto no está normalizado ({checked!r})"
        if problem is not None:
            raise ValueError(f"definición del parámetro «{self.key}»: {problem}")

    @property
    def module(self) -> str:
        """El código del módulo dueño: ``gis`` de ``gis.resample.min_valid_fraction``."""
        return self.key.partition(".")[0]

    def _normalize(self) -> str | None:
        """Pasa los códigos a sus ``StrEnum`` y las listas a tuplas; lo que no se puede
        normalizar, como texto del problema."""
        enums = (("value_type", ValueType, "tipo de valor"), ("kind", ParamKind, "tipo"),
                 ("source_kind", SourceKind, "origen"))
        for name, enum, label in enums:
            value = getattr(self, name)
            try:
                object.__setattr__(self, name, enum(value))
            except ValueError:
                valid = ", ".join(member.value for member in enum)
                return f"{label} {value!r} desconocido; válidos: {valid}"
        for name in ("requirements", "choices"):
            value = getattr(self, name)
            if isinstance(value, str | bytes) or not isinstance(value, Iterable):
                return f"«{name}» es una lista de textos, no {value!r}"
            object.__setattr__(self, name, tuple(value))
        return None

    def _problem(self) -> str | None:
        """Lo que hace incoherente la definición, sin mirar el valor por defecto."""
        match = _KEY.fullmatch(self.key) if isinstance(self.key, str) else None
        if match is None or match["module"] not in MODULE_CODES:
            return (f"la clave no tiene la forma <código>.<nombre>[.<más>] en minúsculas, "
                    f"con un código de módulo de {', '.join(MODULE_CODES)}")
        if self.kind not in DEFAULT_KINDS:
            return (f"su tipo por defecto es {self.kind}: un valor por defecto es ADOPTADO o "
                    "HIPÓTESIS (lo MEDIDO lo mide alguien y lo CALCULADO lo produce una "
                    "operación)")
        if not isinstance(self.unit, str) or self.unit not in UNITS:
            return (f"la unidad {self.unit!r} no está en el catálogo de unidades de "
                    "Geoblender (core.units; se escribe su código: «m3», no «m³»)")
        numeric = self.value_type in _NUMERIC
        if not numeric and self.unit != DIMENSIONLESS:
            return f"la unidad de un parámetro {self.value_type} es «-», no {self.unit!r}"
        has_length = type(self.length) is int and self.length >= 1
        if (self.value_type == ValueType.JSON) != has_length or (
                self.length is not None and not has_length):
            return "solo un parámetro json tiene longitud, y es un entero ≥ 1"
        if self.choices and (self.value_type != ValueType.TEXT or not all(
                isinstance(choice, str) and choice.strip() for choice in self.choices)):
            return "solo un parámetro text tiene opciones, y son textos no vacíos"
        if not isinstance(self.source, str) or not self.source.strip():
            return "le falta la procedencia (source)"
        if not self.requirements or not all(
                isinstance(item, str) and item.strip() for item in self.requirements):
            return "le faltan los requisitos que lo usan (requirements)"
        if self.scope not in SCOPES:
            return f"ámbito {self.scope!r} desconocido; válidos: {', '.join(SCOPES)}"
        for name in ("label_msgid", "description_msgid"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                return f"«{name}» es un msgid no vacío o None, no {value!r}"
        return self._range_problem(numeric)

    def _range_problem(self, numeric: bool) -> str | None:
        bounds = (self.minimum, self.maximum)
        if not numeric:
            if bounds != (None, None) or self.min_exclusive:
                return f"un parámetro {self.value_type} no tiene rango"
            return None
        if not all(bound is None or _is_finite_real(bound) for bound in bounds):
            return f"los extremos del rango son números finitos o None, no {bounds!r}"
        if self.min_exclusive and self.minimum is None:
            return "el rango excluye su mínimo, pero no lo declara"
        if None not in bounds and not self.minimum <= self.maximum:  # type: ignore[operator]
            return f"rango invertido ({self.minimum!r} > {self.maximum!r})"
        return None

    # --- Valores ----------------------------------------------------------------------------

    def check(self, value: object) -> ParamValue | None:
        """``value`` normalizado si es del tipo de valor y está en el rango: ``float``,
        ``int``, tupla creciente de ``length`` ``float``, ``bool`` o ``str`` (``None`` si
        admite «sin valor» y no lo hay). Si no, :class:`ParamError` con la clave y el valor
        (``core.param_not_number``, ``_not_integer``, ``_not_list``, ``_out_of_range``,
        ``_missing``, ``_not_bool``, ``_not_text`` o ``_not_choice``)."""
        if value is None:
            return self._empty(value)
        if self.value_type == ValueType.JSON:
            return self._check_list(value)
        if self.value_type == ValueType.BOOL:
            if not isinstance(value, bool):
                raise self._error("core.param_not_bool", value)
            return value
        if self.value_type == ValueType.TEXT:
            return self._check_text(value)
        if not _is_finite_real(value):
            integer_wanted = self.value_type == ValueType.INT
            raise self._error(
                "core.param_not_integer" if integer_wanted else "core.param_not_number", value
            )
        number = float(value)  # type: ignore[arg-type]
        if self.value_type == ValueType.FLOAT:
            self._check_range(number, number)
            return number
        if not number.is_integer():
            raise self._error("core.param_not_integer", value)
        integer = int(value)  # type: ignore[call-overload]
        self._check_range(integer, integer)
        return integer

    def _empty(self, value: object) -> None:
        if self.allow_empty:
            return None
        raise self._error("core.param_missing", value)

    def _check_text(self, value: object) -> str | None:
        if not isinstance(value, str):
            raise self._error("core.param_not_text", value)
        if not value.strip():
            return self._empty(value)
        if self.choices and value not in self.choices:
            listed = ", ".join(f"«{choice}»" for choice in self.choices)
            raise self._error("core.param_not_choice", value, choices=listed)
        return value

    def _check_list(self, value: object) -> tuple[float, ...]:
        if (
            isinstance(value, str | bytes)
            or not isinstance(value, Sequence)
            or len(value) != self.length
            or not all(_is_finite_real(item) for item in value)
        ):
            raise self._error("core.param_not_list", value, length=self.length)
        items = tuple(float(item) for item in value)
        if any(second <= first for first, second in pairwise(items)):
            raise self._error("core.param_not_list", value, length=self.length)
        shown = "[" + "; ".join(format_value(item) for item in items) + "]"
        for item in items:
            self._check_range(item, shown)
        return items

    def _check_range(self, number: float, shown: object) -> None:
        if self.minimum is None:
            above_min = True
        elif self.min_exclusive:
            above_min = number > self.minimum
        else:
            above_min = number >= self.minimum
        below_max = self.maximum is None or number <= self.maximum
        if not (above_min and below_max):
            raise self._error("core.param_out_of_range", shown)

    def range_text(self, language: str = "es") -> str:
        """El rango como se lee: ``[0; 2] s`` en español (``[0, 2] s`` en inglés), con
        paréntesis en el extremo excluido o abierto (``(0; 1]``, ``[0; +∞) m``), sin unidad si
        es adimensional y vacío si no es un número ni una lista. La unidad, con su símbolo en
        español (``m³``) o, en inglés, su código (``m3``)."""
        return format_range(self.value_type, self.unit, self.minimum, self.maximum,
                            min_exclusive=self.min_exclusive, language=language)

    def _error(self, code: str, value: object, **values: object) -> ParamError:
        return ParamError(code, key=self.key, value=value, unit=self.unit,
                          range=self.range_text(), **values)


def format_range(value_type: ValueType | str, unit: str, minimum: float | None,
                 maximum: float | None, *, min_exclusive: bool = False,
                 language: str = "es") -> str:
    """El rango de una definición como se lee (:meth:`ParamDef.range_text`), también desde
    sus campos guardados (la definición de un cambio que hay que revisar, RF-008-60)."""
    if language not in LANGUAGES:
        raise ValueError(f"el idioma «{language}» no es de Geoblender: {', '.join(LANGUAGES)}")
    if value_type not in _NUMERIC:
        return ""
    separator = "; " if language == "es" else ", "
    opening = "(" if min_exclusive or minimum is None else "["
    closing = ")" if maximum is None else "]"
    low = "-∞" if minimum is None else format_value(float(minimum), language)
    high = "+∞" if maximum is None else format_value(float(maximum), language)
    text = f"{opening}{low}{separator}{high}{closing}"
    if unit == DIMENSIONLESS:
        return text
    return f"{text} {symbol(unit) if language == 'es' else unit}"


def _is_finite_real(value: object) -> bool:
    """Verdadero si ``value`` es un número real finito que cabe en un float64 (no un
    booleano)."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:  # un entero que no cabe en un float64
        return False


# --- Valor tecleado (RF-008-03) -------------------------------------------------------------


def parse_value(defn: ParamDef, text: str, unit: str | None = None, *,
                decimal: str = ",") -> ParamValue | None:
    """El valor que una persona tecleó en ``text`` para ``defn``, comprobado y en la unidad
    declarada (la que se guarda y se muestra; RF-008-03).

    Un número lleva su unidad en el texto («35 %», «1,5 kt») o, si no, la de ``unit`` (la que
    muestra el campo) o la declarada; si es convertible a la declarada se convierte: «35 %» en
    un parámetro en fracción es 0,35. Una lista son sus números separados por «;» (también por
    «,» con ``decimal="."``), entre corchetes o no, cada uno con su unidad si quiere. Un sí/no
    admite «sí», «no», «true», «false», «1» y «0». El texto se toma sin los espacios de los
    extremos, y vacío es «sin valor». Lo que no vale: :class:`ParamError`
    (``core.param_unit_unknown`` o ``core.param_unit_not_convertible`` para la unidad,
    ``core.param_not_finite`` para un número que no cabe en un float64 y los de
    :meth:`ParamDef.check`). :class:`TypeError` si ``text`` no es un texto.
    """
    if not isinstance(text, str):
        raise TypeError(f"el valor tecleado es un texto, no {type(text).__name__}")
    stripped = text.strip()
    if not stripped:
        return defn.check(None)
    if defn.value_type == ValueType.BOOL:
        lowered = stripped.casefold()
        if lowered in _TRUE_TEXTS or lowered in _FALSE_TEXTS:
            return defn.check(lowered in _TRUE_TEXTS)
        raise defn._error("core.param_not_bool", stripped)
    if defn.value_type == ValueType.TEXT:
        return defn.check(stripped)
    default_unit = defn.unit if unit is None else unit
    if defn.value_type == ValueType.JSON:
        items = _list_items(defn, stripped, decimal)
        return defn.check(tuple(
            _number(defn, item, default_unit, decimal, whole=stripped) for item in items
        ))
    return defn.check(_number(defn, stripped, default_unit, decimal, whole=stripped))


def _list_items(defn: ParamDef, text: str, decimal: str) -> list[str]:
    """Los elementos de una lista tecleada; :class:`ParamError` (``core.param_not_list``) si
    los corchetes no casan o falta un elemento."""
    inner = text
    if text[0] in "[(" or text[-1] in "])":
        if not (text[0] in "[(" and text[-1] in "])"):
            raise defn._error("core.param_not_list", text, length=defn.length)
        inner = text[1:-1]
    separators = ";," if decimal == "." else ";"
    items = re.split(f"[{separators}]", inner)
    if any(not item.strip() for item in items):
        raise defn._error("core.param_not_list", text, length=defn.length)
    return [item.strip() for item in items]


def _number(defn: ParamDef, text: str, default_unit: str, decimal: str, *,
            whole: str) -> float:
    """El número de ``text`` en la unidad declarada de ``defn``."""
    try:
        number, typed_unit = parse_quantity(text, decimal=decimal)
    except UnitError as exc:
        if exc.code == "core.unit_unknown":
            raise defn._error("core.param_unit_unknown", whole, from_unit=exc.from_unit) from None
        if exc.code == "core.quantity_not_finite":
            raise defn._error("core.param_not_finite", whole) from None
        raise defn._error(_not_a_number_code(defn), whole) from None
    from_unit = typed_unit or default_unit
    if from_unit not in UNITS:
        raise defn._error("core.param_unit_unknown", whole, from_unit=from_unit)
    try:
        return convert(number, from_unit, defn.unit)
    except UnitError as exc:
        if exc.code == "core.quantity_not_finite":
            raise defn._error("core.param_not_finite", whole) from None
        raise defn._error(
            "core.param_unit_not_convertible", whole, from_unit=from_unit,
            from_symbol=symbol(from_unit), to_symbol=symbol(defn.unit),
        ) from None


def _not_a_number_code(defn: ParamDef) -> str:
    if defn.value_type == ValueType.JSON:
        return "core.param_not_list"
    if defn.value_type == ValueType.INT:
        return "core.param_not_integer"
    return "core.param_not_number"


# --- Registro de definiciones ---------------------------------------------------------------

_LOCK = threading.Lock()
_REGISTRY: dict[str, ParamDef] = {}

DEFINITIONS: Mapping[str, ParamDef] = MappingProxyType(_REGISTRY)
"""Las definiciones registradas, por clave (vista de solo lectura, siempre al día)."""


def register_definitions(defs: Iterable[ParamDef]) -> None:
    """Registra las definiciones de un módulo (lo llama ``bl/`` en el ``register()`` de su
    módulo): todas o ninguna. :class:`ValueError` si una clave se repite en ``defs`` o ya
    está registrada (la registrada se queda); :class:`TypeError` si una no es un
    :class:`ParamDef`."""
    defs = tuple(defs)
    for definition in defs:
        if not isinstance(definition, ParamDef):
            raise TypeError(
                f"solo se registra un ParamDef, no {type(definition).__name__} ({definition!r})"
            )
    keys = [definition.key for definition in defs]
    with _LOCK:
        taken = [key for key in keys if key in _REGISTRY]
        repeated = sorted({key for key in keys if keys.count(key) > 1})
        if taken or repeated:
            listed = ", ".join(f"«{key}»" for key in taken + repeated)
            raise ValueError(
                f"clave de parámetro ya registrada o repetida: {listed}. Cada clave se "
                "registra una sola vez (unregister_definitions antes de volver a registrarla)"
            )
        for definition in defs:
            _REGISTRY[definition.key] = definition


def unregister_definitions(module: str) -> int:
    """Quita las definiciones del módulo ``module`` (en ``unregister()``) y dice cuántas
    había. Quitar las de un módulo sin ninguna no hace nada: ``unregister()`` es
    idempotente."""
    with _LOCK:
        keys = [key for key, definition in _REGISTRY.items() if definition.module == module]
        for key in keys:
            del _REGISTRY[key]
    return len(keys)
