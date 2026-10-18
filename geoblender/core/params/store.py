# SPDX-License-Identifier: GPL-3.0-or-later
"""Valores de los parámetros del proyecto y su historial (spec 008; RF-008-01, RF-008-02,
RF-008-04, RF-008-05, RF-008-06, RF-008-60; plan 008 §5.2.1, §5.3.1, §2.3 S-1 y D10;
ADR-0013).

:class:`ParameterStore` guarda en ``gb_parameter`` el valor vigente de cada parámetro del
proyecto (clave, valor, unidad, tipo, origen y su clase, decisor, fecha de la decisión,
ámbito, motivo y la marca «sin confirmar») y en ``gb_parameter_history`` una fila por cada
alta, cambio o confirmación con el estado nuevo, quién lo hizo (usuario@equipo), cuándo y
por qué. El estado anterior de cada fila es el de la fila anterior; ninguna fila se modifica
ni se borra (lo aseguran además los disparadores de ``core.provenance.schema``), así que una
HIPÓTESIS que pasa a ADOPTADO sigue constando como HIPÓTESIS en sus filas anteriores.

- :meth:`ParameterStore.create`: el alta por una persona, con tipo MEDIDO, ADOPTADO o
  HIPÓTESIS (RF-008-01). Sin tipo, con uno que no es de los cuatro, CALCULADO, sin origen,
  sin decisor o sin motivo se rechaza con :class:`~.model.ParamError` y los textos de la
  spec §8.
- :meth:`ParameterStore.change`: un cambio de valor, tipo, origen o decisor, siempre con
  motivo (RF-008-02); quita «sin confirmar». Con ``from_figure``, una persona adopta como
  CALCULADO el valor de una cifra, con la operación que la calculó: es la única forma de
  que un parámetro sea CALCULADO (decisión S-1 de Samuel: **ningún cálculo cambia un
  parámetro**; no hay ninguna función por la que una operación lo haga).
- :meth:`ParameterStore.confirm`: confirma un «sin confirmar» o un «revisar», sin motivo
  (RF-008-02, RF-008-60).
- :meth:`ParameterStore.ensure_default`: registra el valor y el tipo por defecto de la
  definición, «sin confirmar», con el origen «valor por defecto de Geoblender <versión>» y
  el decisor «Geoblender (valor por defecto)» (RF-008-04); si ya está, no hace nada.
- :meth:`ParameterStore.resolve`: lo que una operación anota del parámetro que lee: clave,
  valor, unidad, tipo, ámbito y la revisión del historial (RF-008-05).
- :meth:`ParameterStore.get` y :meth:`ParameterStore.history`: la consulta;
  :meth:`ParameterStore.list`, la lista del panel, filtrable por módulo, tipo y marca
  (:class:`ParameterFilter`, :class:`ParameterRow`; RF-008-06).
- :meth:`ParameterStore.mark_definition_changes`: al abrir con otro Geoblender, marca
  «revisar», con el cambio, cada parámetro cuya definición cambió o que ya no se declara
  (RF-008-60). No toca ningún valor ni el historial.

**«Revisar»** (RF-008-60). ``def_sha256`` es la huella (:func:`definition_sha256`) de la
definición con la que se registró el valor o con la que una persona lo confirmó o lo cambió
(el valor se comprueba con ella y se guarda en su unidad y su tipo de valor), o la de «no
declarada» (:func:`undeclared_sha256`) si se confirmó sin ninguna. Si la definición
declarada no es esa, ``review`` guarda el cambio (JSON canónico):
``{"registered": {"def_sha256", "unit", "value_type"}, "declared": {<campos de la
definición>, "def_sha256"} | null, "problem": {"code", "values"} | null}``. De la
definición anterior solo se conoce lo que guarda el parámetro (su huella, su unidad y su
tipo de valor); de la nueva, todo. ``problem`` es por qué el valor registrado no cumple la
definición nueva (fuera del rango nuevo, otra unidad…), que es también por qué no se puede
confirmar: hay que cambiarlo. :func:`review_text` lo cuenta en español. Confirmar, o cambiar
el valor (que se comprueba con la definición actual), quita la marca.

Los valores se comprueban con la definición registrada del módulo dueño
(``core.params.DEFINITIONS``) y se guardan en su unidad declarada: un valor en otra unidad
convertible se convierte (RF-008-03). ``value`` es el JSON canónico del valor (``NULL`` =
«sin valor») y ``value_sha256`` el sha256 de ``{value, unit}`` (plan D10): lo que compara la
cascada, que no cambia con un cambio solo de tipo.

Todas las escrituras reciben la conexión de una transacción de escritura del proyecto
(``Project.write_transaction()`` o ``try_write()``, en el hilo de Blender) y lo comprueban
todo **antes** de escribir: un rechazo es un :class:`~.model.ParamError` (un error de
Geoblender, que solo deshace la transacción), nunca una restricción de SQLite (que dejaría
el proyecto en solo lectura). Python puro: biblioteca estándar y ``core`` (ADR-0004).

Ámbito: en esta spec, solo el proyecto (``scope = 'project'``, ``scope_uid = ''``); la
versión llega con la spec 009 y el sector con R-32. De la 009 está ya
:meth:`ParameterStore.inherit`: crear una versión que parte de otra le copia sus parámetros de
versión con la fila de historial «Heredado de V10.r2» (plan 009 A1, D-26).
"""

from __future__ import annotations

import builtins
import datetime as dt
import functools
import json
import numbers
import sqlite3
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, replace
from enum import Enum, StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from ..catalog.schema import MODULE_CODES
from ..hashing import canonical_json, sha256_bytes
from ..ids import new_uid
from ..timeutil import Clock, format_utc, parse_utc
from ..units import DIMENSIONLESS, UNITS, UnitError, convert, symbol
from .model import (
    DEFINITIONS,
    MESSAGES,
    ParamDef,
    ParamError,
    ParamKind,
    ParamValue,
    SourceKind,
    ValueType,
    format_range,
    format_value,
    render,
)

if TYPE_CHECKING:
    from ..sysinfo import SessionInfo

PROJECT_SCOPE = "project"
"""El único ámbito de esta spec (``gb_parameter.scope``)."""
VERSION_SCOPE = "version"
"""El ámbito de los parámetros de una versión (spec 009; ``scope_uid`` = uid de la versión):
por ahora solo los copia :meth:`ParameterStore.inherit`."""

DEFAULT_DECIDER = "Geoblender (valor por defecto)"
"""El decisor (y quien escribe la fila del historial) de un valor por defecto (RF-008-04)."""

DEFAULT_SOURCE_PREFIX = "valor por defecto de Geoblender"
"""El principio del origen de un valor por defecto: :func:`default_source`."""

NO_VALUE_TEXT = "sin valor"
"""Cómo se ve un valor que falta en los mensajes."""
NO_VALUE_TEXT_EN = "no value"
"""Lo mismo en inglés (:func:`shown_value`; como ``core.provenance.figures``)."""


def default_source(geoblender_version: str) -> str:
    """El origen de un valor por defecto: «valor por defecto de Geoblender 0.3.0»."""
    return f"{DEFAULT_SOURCE_PREFIX} {geoblender_version}"


def default_reason(defn: ParamDef) -> str:
    """El motivo de la fila de un valor por defecto: la procedencia que declara su módulo."""
    return f"Valor por defecto de su definición: {defn.source}"


class HistoryAction(StrEnum):
    """Lo que añadió una fila del historial (``gb_parameter_history.action``)."""

    DEFAULT = "default"  # valor por defecto, «sin confirmar» (RF-008-04)
    CREATE = "create"  # alta por una persona
    CHANGE = "change"  # cambio de valor, tipo, origen o decisor (RF-008-02)
    CONFIRM = "confirm"  # confirmación de un «sin confirmar» o un «revisar», sin motivo


class ParamMark(StrEnum):
    """Las marcas de un parámetro en la lista (RF-008-06), en el orden en que se ven."""

    UNCONFIRMED = "unconfirmed"  # «sin confirmar»: un valor por defecto (RF-008-04)
    REVIEW = "review"  # «revisar»: cambió su definición o ya no se declara (RF-008-60)


class _Unset(Enum):
    UNSET = "unset"


UNSET = _Unset.UNSET
"""En :meth:`ParameterStore.change`, «no cambia» (``None`` es «sin valor»)."""

type Unset = _Unset


class StoreProject(Protocol):
    """Lo que el almacén usa del proyecto (``core.project.Project``): la sesión (quién y
    con qué sesión se escribe cada fila), el reloj y una conexión de lectura."""

    @property
    def session(self) -> SessionInfo: ...

    @property
    def clock(self) -> Clock: ...

    def read(self) -> AbstractContextManager[sqlite3.Connection]: ...


# --- Registros ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParameterRecord:
    """Una fila de ``gb_parameter``: el valor vigente de un parámetro del proyecto.

    ``value`` normalizado (``float``, ``int``, ``bool``, ``str``, tupla de ``float`` o
    ``None``) y ``value_json``, su JSON canónico tal como se guarda; ``review``, el JSON del
    cambio de definición que hay que revisar (RF-008-60) o ``None``; fechas en UTC
    (``AAAA-MM-DDTHH:MM:SS.mmmZ``)."""

    uid: str
    key: str
    scope: str
    scope_uid: str
    module: str
    value_type: ValueType
    value: ParamValue | None
    value_json: str | None
    unit: str
    kind: ParamKind
    source: str
    source_kind: SourceKind
    decided_by: str
    decided_at: str
    reason: str
    operation_uid: str | None
    unconfirmed: bool
    review: Any
    def_sha256: str
    value_sha256: str
    rev: int
    created_at: str
    modified_at: str


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    """Una fila de ``gb_parameter_history``: el estado del parámetro tras su revisión
    ``rev``, quién la escribió (``changed_by``, usuario@equipo; «Geoblender (valor por
    defecto)» en la de un valor por defecto), cuándo, con qué sesión y por qué (``reason``,
    ``None`` solo al confirmar). ``operation_uid``, solo al adoptar una cifra CALCULADA."""

    parameter_uid: str
    rev: int
    action: HistoryAction
    value: ParamValue | None
    value_json: str | None
    unit: str
    kind: ParamKind
    source: str
    source_kind: SourceKind
    decided_by: str
    decided_at: str
    reason: str | None
    operation_uid: str | None
    unconfirmed: bool
    value_sha256: str
    changed_at: str
    changed_by: str
    session_uid: str


@dataclass(frozen=True, slots=True)
class ResolvedParam:
    """Lo que una operación anota del parámetro que lee (RF-008-05; ``gb_operation_param``):
    la clave, el valor (normalizado y su JSON canónico), la unidad, el tipo, el ámbito, la
    revisión del historial que usó, la marca «sin confirmar» y ``value_sha256``."""

    parameter_uid: str
    key: str
    scope: str
    scope_uid: str
    rev: int
    value: ParamValue | None
    value_json: str | None
    unit: str
    kind: ParamKind
    unconfirmed: bool
    value_sha256: str


def _filter_values[T](name: str, value: object, convert_one: Callable[[object], T]
                      ) -> frozenset[T] | None:
    """Los valores de un filtro: ``None`` (todos), uno o varios; vacío es un error (no es
    «todos»)."""
    if value is None:
        return None
    if isinstance(value, str):
        items: Iterable[object] = (value,)
    elif isinstance(value, Iterable):
        items = value
    else:
        raise TypeError(f"el filtro «{name}» es un valor, varios o None, no {value!r}")
    result = frozenset(convert_one(item) for item in items)
    if not result:
        raise ValueError(f"el filtro «{name}» está vacío: para no filtrar, None")
    return result


def _module_code(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"un módulo es su código, no {value!r}")
    if value not in MODULE_CODES:
        raise ValueError(f"módulo «{value}» desconocido; válidos: {', '.join(MODULE_CODES)}")
    return value


@dataclass(frozen=True, slots=True)
class ParameterFilter:
    """Los filtros de :meth:`ParameterStore.list` (RF-008-06), que se combinan: ``module``
    (código del módulo dueño), ``kind`` (:class:`~.model.ParamKind`) y ``mark``
    (:class:`ParamMark`: el parámetro tiene alguna de ellas). Cada uno es ``None`` (no
    filtra), un valor o varios (cualquiera de ellos); se guardan como ``frozenset``.
    :class:`ValueError` si uno no existe o está vacío; :class:`TypeError` si no es un texto."""

    module: str | Iterable[str] | frozenset[str] | None = None
    kind: ParamKind | str | Iterable[ParamKind | str] | frozenset[ParamKind] | None = None
    mark: ParamMark | str | Iterable[ParamMark | str] | frozenset[ParamMark] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "module", _filter_values("module", self.module, _module_code))
        object.__setattr__(self, "kind", _filter_values("kind", self.kind, ParamKind))
        object.__setattr__(self, "mark", _filter_values("mark", self.mark, ParamMark))


@dataclass(frozen=True, slots=True)
class ParameterRow:
    """Una fila de la lista de parámetros (RF-008-06): el registro (valor, unidad, tipo,
    origen, decisor, fecha de la decisión y ``review``), el valor con su unidad como lo lee
    una persona (``shown``: «1,23», «35 m») y sus marcas en orden (:class:`ParamMark`)."""

    record: ParameterRecord
    shown: str
    marks: tuple[ParamMark, ...]

    @property
    def review_text(self) -> str:
        """El cambio de definición que hay que revisar, en español («» si no hay)."""
        return review_text(self.record.key, self.record.review)


@dataclass(frozen=True, slots=True)
class DefinitionChange:
    """Un parámetro cuya marca «revisar» escribió :meth:`ParameterStore.mark_definition_changes`
    (RF-008-60): ``review`` es el cambio (el JSON de ``gb_parameter.review``, ya leído) o
    ``None`` si se quitó porque se declara otra vez la definición registrada."""

    parameter_uid: str
    key: str
    scope: str
    review: dict[str, Any] | None

    @property
    def text(self) -> str:
        """El cambio en español («» si se quitó la marca)."""
        return review_text(self.key, self.review)


# --- Valores y huellas ----------------------------------------------------------------------


def value_json(value: ParamValue | None) -> str | None:
    """``value`` como se guarda en ``gb_parameter.value``: su JSON canónico (una lista para
    un parámetro ``json``), o ``None`` si no hay valor."""
    if value is None:
        return None
    return canonical_json(value).decode("utf-8")


def decode_value(text: str | None) -> ParamValue | None:
    """El valor normalizado de un ``gb_parameter.value`` (una lista vuelve como tupla de
    ``float``)."""
    if text is None:
        return None
    value = json.loads(text)
    if isinstance(value, list):
        return tuple(float(item) for item in value)
    return value


def value_sha256(value: ParamValue | None, unit: str) -> str:
    """sha256 del JSON canónico de ``{"unit": unit, "value": value}`` (plan D10): lo que la
    cascada compara; no depende del tipo ni de la procedencia."""
    return sha256_bytes(canonical_json({"unit": unit, "value": value}))


def definition_fields(defn: ParamDef) -> dict[str, object]:
    """Lo de una definición que cuenta para su huella: tipo de valor, unidad, valor y tipo
    por defecto, rango, longitud, «sin valor», opciones y ámbito (no sus textos)."""
    return {
        "key": defn.key,
        "value_type": str(defn.value_type),
        "unit": defn.unit,
        "default": defn.default,
        "kind": str(defn.kind),
        "minimum": None if defn.minimum is None else float(defn.minimum),
        "maximum": None if defn.maximum is None else float(defn.maximum),
        "min_exclusive": defn.min_exclusive,
        "length": defn.length,
        "allow_empty": defn.allow_empty,
        "choices": list(defn.choices),
        "scope": defn.scope,
    }


def definition_sha256(defn: ParamDef) -> str:
    """La huella de una definición (``gb_parameter.def_sha256``): sha256 del JSON canónico
    de :func:`definition_fields`."""
    return sha256_bytes(canonical_json(definition_fields(defn)))


@functools.lru_cache(maxsize=4096)
def _cached_sha256(defn: ParamDef) -> str:
    return definition_sha256(defn)


def _declared_sha256(defn: ParamDef) -> str:
    """:func:`definition_sha256` memorizada por definición (una ``ParamDef`` no cambia): la
    piden «revisar» y la comprobación de apertura para cada parámetro registrado en cada
    apertura (unos 6 ms con los 300 de D-13, en la transacción final; T65)."""
    try:
        return _cached_sha256(defn)
    except TypeError:  # un valor que no se puede usar como clave: sin memorizar
        return definition_sha256(defn)


def undeclared_sha256(key: str) -> str:
    """La «huella» de un parámetro que ningún módulo declara: la que guarda
    ``def_sha256`` cuando una persona lo confirma así (RF-008-60), para que no vuelva a
    quedar «revisar» mientras siga sin declararse."""
    return sha256_bytes(canonical_json({"declared": False, "key": key}))


def shown_value(value: ParamValue | None, unit: str, language: str = "es") -> str:
    """Un valor con su unidad como lo lee una persona: «1,23», «35 m», «[5; 15] m», «sí»,
    «sin valor»; un número, con el separador de miles de las cifras («500 000 t/año»; T71).
    En ``language``, como una cifra (``core.provenance.figures``): «500,000 t/año» en
    inglés."""
    if value is None:
        return NO_VALUE_TEXT if language == "es" else NO_VALUE_TEXT_EN
    if isinstance(value, tuple):
        text = "[" + "; ".join(format_value(item, language) for item in value) + "]"
    else:
        text = format_value(value, language)
    if unit == DIMENSIONLESS or isinstance(value, bool | str):
        return text
    return f"{text} {_symbol(unit)}"


def _symbol(unit: str) -> str:
    return symbol(unit) if unit in UNITS else unit


# --- «Revisar» por un cambio de definición (RF-008-60) --------------------------------------

_VALUE_TYPE_ES = {
    ValueType.FLOAT: "número",
    ValueType.INT: "entero",
    ValueType.BOOL: "sí/no",
    ValueType.TEXT: "texto",
    ValueType.JSON: "lista",
}
"""Cómo se lee en español cada tipo de valor."""


def _value_type_text(value_type: str) -> str:
    try:
        return _VALUE_TYPE_ES[ValueType(value_type)]
    except ValueError:
        return value_type


def _expected(defn: ParamDef) -> str:
    """El tipo de valor y la unidad de una definición: «número en kg/m³», «sí/no»."""
    label = _value_type_text(defn.value_type)
    if defn.unit == DIMENSIONLESS:
        return label
    return f"{label} en {_symbol(defn.unit)}"


def _value_problem(record: ParameterRecord, defn: ParamDef) -> ParamError | None:
    """Por qué el valor registrado de ``record`` no cumple ``defn`` (otra unidad u otro tipo
    de valor, o fuera de su rango…), o ``None`` si la cumple. No convierte ni cambia nada."""
    if record.unit != defn.unit or record.value_type != defn.value_type:
        return ParamError(
            "core.param_review_mismatch", key=record.key, value=record.value,
            shown=shown_value(record.value, record.unit), expected=_expected(defn),
            unit=defn.unit, range=defn.range_text(),
        )
    try:
        defn.check(record.value)
    except ParamError as exc:
        return exc
    return None


def _review(record: ParameterRecord, defn: ParamDef | None) -> dict[str, Any] | None:
    """El cambio que hay que revisar de ``record`` con la definición declarada ``defn``
    (``None``: ninguna), o ``None`` si es la registrada o confirmada."""
    if defn is None:
        if record.def_sha256 == undeclared_sha256(record.key):
            return None
        declared = None
        problem = None
    else:
        declared_sha = _declared_sha256(defn)
        if declared_sha == record.def_sha256:
            return None
        declared = {**definition_fields(defn), "def_sha256": declared_sha}
        error = _value_problem(record, defn)
        problem = None if error is None else {"code": error.code, "values": error.values}
    return {
        "registered": {
            "def_sha256": record.def_sha256,
            "unit": record.unit,
            "value_type": str(record.value_type),
        },
        "declared": declared,
        "problem": problem,
    }


def _review_json(review: object) -> str | None:
    return None if review is None else canonical_json(review).decode("utf-8")


def _review_identity(review: Mapping[str, Any] | None) -> str | None:
    """Lo que decide si cambia la marca «revisar» de un parámetro (RF-008-60): las
    definiciones registrada y declarada y el código del problema de su valor; no los textos
    del problema, que dicen sus números como los muestra el Geoblender que los escribió (T71:
    con el separador de miles; uno anterior, sin él). Mientras está «revisar», su valor no
    cambia (cambiarlo la quita): el mismo código es el mismo problema."""
    if review is None:
        return None
    problem = review.get("problem")
    code = None if not isinstance(problem, Mapping) else problem.get("code")
    return _review_json({**review, "problem": code})


def _definition_changes(conn: sqlite3.Connection, declared: Mapping[str, ParamDef]
                        ) -> list[tuple[DefinitionChange, str | None]]:
    """Cada parámetro registrado cuya marca «revisar» cambia con las definiciones
    ``declared`` (por clave, ámbito y uid de ámbito), con el texto que se guardaría en
    ``review`` (``None``: se quita). Solo lee. Que cambie cómo se muestran los números del
    problema no es un cambio (:func:`_review_identity`): ni se vuelve a marcar ni se
    reescribe."""
    found: list[tuple[DefinitionChange, str | None]] = []
    for row in conn.execute(
        f"SELECT {_PARAMETER_COLUMNS} FROM gb_parameter ORDER BY key, scope, scope_uid"
    ).fetchall():
        record = _record(row)
        review = _review(record, declared.get(record.key))
        if _review_identity(review) == _review_identity(record.review):
            continue
        text = _review_json(review)
        found.append((DefinitionChange(record.uid, record.key, record.scope,
                                       None if text is None else json.loads(text)), text))
    return found


def _declared_value(value: object) -> ParamValue | None:
    """Un valor de la definición guardada en ``review`` (una lista vuelve como tupla)."""
    if isinstance(value, list):
        return tuple(float(item) for item in value)
    return value  # type: ignore[return-value]


def review_text(key: str, review: Mapping[str, Any] | None) -> str:
    """El cambio de definición de ``key`` que hay que revisar (``review``, el JSON de
    ``gb_parameter.review`` ya leído), en español: lo que cambió de lo que se sabe de la
    definición registrada (unidad y tipo de valor), el rango y el valor por defecto de la
    nueva y, si el valor registrado no la cumple, por qué. «» si no hay nada que revisar."""
    if review is None:
        return ""
    declared = review.get("declared")
    if declared is None:
        return render("core.param_review_undeclared", key=key)
    registered = review["registered"]
    parts: list[str] = []
    if registered["unit"] != declared["unit"]:
        parts.append(f"unidad {_symbol(registered['unit'])} → {_symbol(declared['unit'])}")
    if registered["value_type"] != declared["value_type"]:
        parts.append(f"tipo de valor {_value_type_text(registered['value_type'])} → "
                     f"{_value_type_text(declared['value_type'])}")
    shown_range = format_range(declared["value_type"], declared["unit"], declared["minimum"],
                               declared["maximum"], min_exclusive=declared["min_exclusive"])
    if shown_range:
        parts.append(f"rango {shown_range}")
    default = _declared_value(declared["default"])
    parts.append(f"valor por defecto {shown_value(default, declared['unit'])}")
    text = render("core.param_review_changed", key=key, change=", ".join(parts))
    problem = review.get("problem")
    if problem and problem.get("code") in MESSAGES:  # el de otro Geoblender, se omite
        text += " " + render(problem["code"], **problem["values"])
    return text


# --- Estado y comprobaciones ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _State:
    """Lo que cambia de un parámetro y repite cada fila de su historial."""

    value: ParamValue | None
    unit: str
    kind: ParamKind
    source: str
    source_kind: SourceKind
    decided_by: str
    decided_at: str
    reason: str | None
    operation_uid: str | None
    unconfirmed: bool

    @classmethod
    def of(cls, record: ParameterRecord) -> _State:
        return cls(record.value, record.unit, record.kind, record.source, record.source_kind,
                   record.decided_by, record.decided_at, record.reason, record.operation_uid,
                   record.unconfirmed)

    @property
    def value_json(self) -> str | None:
        return value_json(self.value)

    @property
    def value_sha256(self) -> str:
        return value_sha256(self.value, self.unit)


@dataclass(frozen=True, slots=True)
class _Figure:
    key: str
    value: float
    unit: str
    operation_uid: str
    op_type: str


def _check_key(key: object) -> None:
    if not isinstance(key, str):
        raise TypeError(f"la clave de un parámetro es un texto, no {type(key).__name__}")


def _check_scope(scope: object) -> None:
    if scope != PROJECT_SCOPE:
        raise ValueError(
            f"ámbito {scope!r}: en esta spec los parámetros son del proyecto ('project'); la "
            "versión llega con la spec 009 y el sector con R-32"
        )


def _definition(key: str) -> ParamDef:
    """La definición registrada de ``key``; sin ella no se puede comprobar el valor."""
    defn = DEFINITIONS.get(key)
    if defn is None:
        raise ParamError("core.param_undefined", key=key)
    _check_scope(defn.scope)
    return defn


def _kind(key: str, kind: object) -> ParamKind:
    """El tipo de un parámetro: obligatorio y uno de los cuatro (RF-008-01)."""
    if kind is None or (isinstance(kind, str) and not kind.strip()):
        raise ParamError("core.param_kind_missing", key=key, value=kind)
    try:
        return ParamKind(kind)
    except ValueError:
        raise ParamError("core.param_kind_unknown", key=key, value=kind) from None


def _source_kind(key: str, value: object) -> SourceKind:
    try:
        return SourceKind(value)
    except ValueError:
        raise ParamError("core.param_source_kind_unknown", key=key, value=value) from None


def _required(key: str, value: object, code: str) -> str:
    """Un texto obligatorio (origen, decisor), sin los espacios de los extremos."""
    if not isinstance(value, str) or not value.strip():
        raise ParamError(code, key=key, value=value)
    return value.strip()


def _reason(reason: object) -> str | None:
    """El motivo sin los espacios de los extremos, o ``None`` si no hay."""
    if reason is None:
        return None
    if not isinstance(reason, str):
        raise TypeError(f"el motivo es un texto, no {type(reason).__name__}")
    return reason.strip() or None


def _is_real(value: object) -> bool:
    return isinstance(value, numbers.Real) and not isinstance(value, bool)


def _value_error(defn: ParamDef, code: str, value: object, **values: object) -> ParamError:
    return ParamError(code, key=defn.key, value=value, unit=defn.unit,
                      range=defn.range_text(), **values)


def _not_convertible(defn: ParamDef, value: object, unit: str) -> ParamError:
    return _value_error(defn, "core.param_unit_not_convertible", value, from_unit=unit,
                        from_symbol=symbol(unit), to_symbol=symbol(defn.unit))


def _convert(defn: ParamDef, number: object, unit: str, whole: object) -> object:
    """``number`` de ``unit`` a la unidad declarada (lo que no es un número, tal cual: lo
    rechaza ``check``)."""
    if not _is_real(number):
        return number
    try:
        return convert(number, unit, defn.unit)  # type: ignore[arg-type]
    except UnitError as exc:
        if exc.code == "core.quantity_not_finite":
            raise _value_error(defn, "core.param_not_finite", whole) from None
        raise _not_convertible(defn, whole, unit) from None


def _checked_value(defn: ParamDef, value: object, unit: str | None) -> ParamValue | None:
    """``value`` (en ``unit``; ``None``, la declarada) comprobado y en la unidad declarada,
    que es la que se guarda (RF-008-03)."""
    if unit is None or unit == defn.unit:
        return defn.check(value)
    if not isinstance(unit, str):
        raise TypeError(f"la unidad es un código de core.units, no {type(unit).__name__}")
    if unit not in UNITS:
        raise _value_error(defn, "core.param_unit_unknown", value, from_unit=unit)
    if value is None:
        return defn.check(None)
    if defn.value_type not in (ValueType.FLOAT, ValueType.INT, ValueType.JSON):
        raise _not_convertible(defn, value, unit)
    if defn.value_type == ValueType.JSON and isinstance(value, Sequence) and not isinstance(
            value, str | bytes):
        return defn.check(tuple(_convert(defn, item, unit, value) for item in value))
    return defn.check(_convert(defn, value, unit, value))


def _change_text(old: _State, new: _State, *, dated: bool) -> str:
    """Lo que cambia, para el mensaje que pide el motivo: «1,22 → 1,23», «HIPÓTESIS →
    ADOPTADO»…"""
    parts: list[str] = []
    if old.value_sha256 != new.value_sha256:
        parts.append(f"{shown_value(old.value, old.unit)} → {shown_value(new.value, new.unit)}")
    if old.kind != new.kind:
        parts.append(f"{old.kind} → {new.kind}")
    if old.source != new.source:
        parts.append(f"«{old.source}» → «{new.source}»")
    if old.source_kind != new.source_kind:
        parts.append(f"{old.source_kind} → {new.source_kind}")
    if old.decided_by != new.decided_by:
        parts.append(f"«{old.decided_by}» → «{new.decided_by}»")
    if dated and old.decided_at != new.decided_at:
        parts.append(f"{old.decided_at} → {new.decided_at}")
    return ", ".join(parts)


def _same_decision(old: _State, new: _State, *, dated: bool) -> bool:
    same = (
        old.value_sha256 == new.value_sha256
        and old.kind == new.kind
        and old.source == new.source
        and old.source_kind == new.source_kind
        and old.decided_by == new.decided_by
        and old.operation_uid == new.operation_uid
    )
    return same and (not dated or old.decided_at == new.decided_at)


# --- SQL ------------------------------------------------------------------------------------

_PARAMETER_COLUMNS = (
    "uid, key, scope, scope_uid, module, value_type, value, unit, kind, source, source_kind, "
    "decided_by, decided_at, reason, operation_uid, unconfirmed, review, def_sha256, "
    "value_sha256, rev, created_at, modified_at"
)
_HISTORY_COLUMNS = (
    "parameter_uid, rev, action, value, unit, kind, source, source_kind, decided_by, "
    "decided_at, reason, operation_uid, unconfirmed, value_sha256, changed_at, changed_by, "
    "session_uid"
)


def _marks(columns: str) -> str:
    return ", ".join("?" for _ in columns.split(","))


def _record(row: Sequence[Any]) -> ParameterRecord:
    (uid, key, scope, scope_uid, module, value_type, value, unit, kind, source, source_kind,
     decided_by, decided_at, reason, operation_uid, unconfirmed, review, def_sha, value_sha,
     rev, created_at, modified_at) = row
    return ParameterRecord(
        uid, key, scope, scope_uid, module, ValueType(value_type), decode_value(value), value,
        unit, ParamKind(kind), source, SourceKind(source_kind), decided_by, decided_at, reason,
        operation_uid, bool(unconfirmed), None if review is None else json.loads(review),
        def_sha, value_sha, rev, created_at, modified_at,
    )


def _entry(row: Sequence[Any]) -> HistoryEntry:
    (parameter_uid, rev, action, value, unit, kind, source, source_kind, decided_by,
     decided_at, reason, operation_uid, unconfirmed, value_sha, changed_at, changed_by,
     session_uid) = row
    return HistoryEntry(
        parameter_uid, rev, HistoryAction(action), decode_value(value), value, unit,
        ParamKind(kind), source, SourceKind(source_kind), decided_by, decided_at, reason,
        operation_uid, bool(unconfirmed), value_sha, changed_at, changed_by, session_uid,
    )


def _list_row(record: ParameterRecord) -> ParameterRow:
    marks: list[ParamMark] = []
    if record.unconfirmed:
        marks.append(ParamMark.UNCONFIRMED)
    if record.review is not None:
        marks.append(ParamMark.REVIEW)
    return ParameterRow(record, shown_value(record.value, record.unit), tuple(marks))


def _declared_definitions(defs: object) -> dict[str, ParamDef]:
    """Las definiciones declaradas por clave: un ``Mapping`` como ``DEFINITIONS`` o una
    secuencia de :class:`~.model.ParamDef` con claves distintas."""
    if isinstance(defs, Mapping):
        items: Iterable[object] = defs.values()
    elif isinstance(defs, str | bytes) or not isinstance(defs, Iterable):
        raise TypeError(f"las definiciones son ParamDef, no {defs!r}")
    else:
        items = defs
    declared: dict[str, ParamDef] = {}
    for defn in items:
        if not isinstance(defn, ParamDef):
            raise TypeError(f"solo se comparan ParamDef, no {type(defn).__name__} ({defn!r})")
        if defn.key in declared:
            raise ValueError(f"la definición de «{defn.key}» está repetida")
        declared[defn.key] = defn
    return declared


def _load(conn: sqlite3.Connection, key: str) -> ParameterRecord | None:
    row = conn.execute(
        f"SELECT {_PARAMETER_COLUMNS} FROM gb_parameter "
        "WHERE key = ? AND scope = ? AND scope_uid = ''",
        (key, PROJECT_SCOPE),
    ).fetchone()
    return None if row is None else _record(row)


def _figure(conn: sqlite3.Connection, key: str, record: ParameterRecord,
            figure_uid: object) -> _Figure:
    """La cifra que una persona adopta como valor CALCULADO de ``record``: tiene que estar
    y calcular este parámetro (``gb_figure.parameter_uid``)."""
    if not isinstance(figure_uid, str):
        raise TypeError(f"la cifra se indica por su uid, no {type(figure_uid).__name__}")
    row = conn.execute(
        "SELECT f.key, f.value, f.unit, f.operation_uid, f.parameter_uid, o.op_type "
        "FROM gb_figure AS f JOIN gb_operation AS o ON o.uid = f.operation_uid "
        "WHERE f.uid = ?",
        (figure_uid,),
    ).fetchone()
    if row is None:
        raise ParamError("core.param_figure_unknown", key=key, value=figure_uid,
                         figure=figure_uid)
    figure_key, value, unit, operation_uid, parameter_uid, op_type = row
    if parameter_uid != record.uid:
        raise ParamError("core.param_figure_other", key=key, value=value, figure=figure_key,
                         operation=op_type)
    return _Figure(figure_key, value, unit, operation_uid, op_type)


# --- Almacén --------------------------------------------------------------------------------


class ParameterStore:
    """Los parámetros de un proyecto abierto (``project``: un ``core.project.Project`` o lo
    que cumpla :class:`StoreProject`). Las escrituras reciben la conexión de una transacción
    de escritura; las lecturas, una conexión cualquiera o ninguna (abren una de lectura)."""

    def __init__(self, project: StoreProject) -> None:
        self.project = project

    # --- Lectura ----------------------------------------------------------------------------

    def get(self, key: str, scope: str = PROJECT_SCOPE, *,
            conn: sqlite3.Connection | None = None) -> ParameterRecord | None:
        """El valor vigente de ``key`` en el proyecto, o ``None`` si no está registrado."""
        _check_key(key)
        _check_scope(scope)
        with self._reading(conn) as reading:
            return _load(reading, key)

    def history(self, key: str, scope: str = PROJECT_SCOPE, *,
                conn: sqlite3.Connection | None = None) -> list[HistoryEntry]:
        """El historial de ``key`` por revisión (vacío si no está registrado)."""
        _check_key(key)
        _check_scope(scope)
        columns = ", ".join(f"h.{name.strip()}" for name in _HISTORY_COLUMNS.split(","))
        with self._reading(conn) as reading:
            rows = reading.execute(
                f"SELECT {columns} FROM gb_parameter_history AS h "
                "JOIN gb_parameter AS p ON p.uid = h.parameter_uid "
                "WHERE p.key = ? AND p.scope = ? AND p.scope_uid = '' ORDER BY h.rev",
                (key, scope),
            ).fetchall()
        return [_entry(row) for row in rows]

    def list(self, filters: ParameterFilter | None = None, *,
             conn: sqlite3.Connection | None = None) -> builtins.list[ParameterRow]:
        """Los parámetros del proyecto por clave (RF-008-06), los que cumplen a la vez los
        filtros de módulo, tipo y marca de ``filters`` (``None``: todos), cada uno con su
        valor presentado y sus marcas."""
        if filters is None:
            filters = ParameterFilter()
        if not isinstance(filters, ParameterFilter):
            raise TypeError(f"los filtros son un ParameterFilter, no {filters!r}")
        clauses = ["scope = ?", "scope_uid = ''"]
        args: builtins.list[object] = [PROJECT_SCOPE]
        for column, chosen in (("module", filters.module), ("kind", filters.kind)):
            if chosen is not None:
                clauses.append(f"{column} IN ({', '.join('?' for _ in chosen)})")
                args.extend(sorted(str(item) for item in chosen))
        if filters.mark is not None:
            either = []
            if ParamMark.UNCONFIRMED in filters.mark:
                either.append("unconfirmed <> 0")
            if ParamMark.REVIEW in filters.mark:
                either.append("review IS NOT NULL")
            clauses.append(f"({' OR '.join(either)})")
        with self._reading(conn) as reading:
            rows = reading.execute(
                f"SELECT {_PARAMETER_COLUMNS} FROM gb_parameter "
                f"WHERE {' AND '.join(clauses)} ORDER BY key",
                args,
            ).fetchall()
        return [_list_row(_record(row)) for row in rows]

    def resolve(self, conn: sqlite3.Connection, key: str,
                scope_chain: Iterable[str] = (PROJECT_SCOPE,)) -> ResolvedParam:
        """El parámetro ``key`` que lee una operación, resuelto por su ámbito (RF-008-05):
        el primero de ``scope_chain`` que lo tiene; en esta spec, solo el proyecto.
        :class:`~.model.ParamError` (``core.param_not_registered``) si el proyecto no lo
        tiene: antes, :meth:`ensure_default`. :class:`ValueError` con otro ámbito."""
        _check_key(key)
        if isinstance(scope_chain, str):
            raise TypeError("scope_chain es una secuencia de ámbitos, no un texto")
        chain = tuple(scope_chain)
        if not chain:
            raise ValueError("scope_chain no tiene ningún ámbito")
        for scope in chain:
            _check_scope(scope)
        record = _load(conn, key)
        if record is None:
            raise ParamError("core.param_not_registered", key=key)
        return ResolvedParam(
            record.uid, record.key, record.scope, record.scope_uid, record.rev, record.value,
            record.value_json, record.unit, record.kind, record.unconfirmed,
            record.value_sha256,
        )

    # --- Escritura --------------------------------------------------------------------------

    def create(
        self,
        conn: sqlite3.Connection,
        key: str,
        value: ParamValue | None,
        unit: str | None = None,
        *,
        kind: ParamKind | str | None = None,
        source: str | None = None,
        source_kind: SourceKind | str | None = None,
        decided_by: str | None = None,
        decided_at: dt.datetime | dt.date | str | None = None,
        reason: str | None = None,
    ) -> ParameterRecord:
        """Da de alta ``key`` con el valor que fija una persona (``value`` en ``unit``; sin
        ella, en la declarada), su tipo (MEDIDO, ADOPTADO o HIPÓTESIS), su origen y su clase,
        quién lo decidió, cuándo (``decided_at``; sin ella, ahora) y por qué (RF-008-01).
        :class:`~.model.ParamError` si ya está, si ningún módulo cargado lo declara, si le
        falta algo de eso, si es CALCULADO o si el valor no vale (RF-008-03)."""
        _check_key(key)
        if _load(conn, key) is not None:
            raise ParamError("core.param_exists", key=key, value=value)
        checked_kind = _kind(key, kind)
        if checked_kind is ParamKind.CALCULADO:
            raise ParamError("core.param_calculated_by_hand", key=key, value=value)
        defn = _definition(key)
        checked = _checked_value(defn, value, unit)
        state = _State(
            value=checked,
            unit=defn.unit,
            kind=checked_kind,
            source=_required(key, source, "core.param_source_missing"),
            source_kind=_source_kind(key, source_kind),
            decided_by=_required(key, decided_by, "core.param_decided_by_missing"),
            decided_at=self._moment(decided_at),
            reason=_reason(reason),
            operation_uid=None,
            unconfirmed=False,
        )
        if state.reason is None:
            raise ParamError("core.param_reason_missing_new", key=key, value=checked,
                             shown=shown_value(checked, defn.unit))
        return self._insert(conn, defn, state, HistoryAction.CREATE,
                            changed_by=self.project.session.user_host, now=self._now())

    def ensure_default(self, conn: sqlite3.Connection, key: str, *,
                       geoblender_version: str) -> ParameterRecord:
        """El parámetro ``key`` del proyecto; si aún no lo tiene, lo registra antes con el
        valor y el tipo por defecto de su definición (ADOPTADO o HIPÓTESIS), su clase de
        origen, el origen «valor por defecto de Geoblender <versión>», el decisor
        «Geoblender (valor por defecto)» y la marca «sin confirmar» (RF-008-04).
        :class:`~.model.ParamError` (``core.param_undefined``) si ningún módulo cargado lo
        declara."""
        _check_key(key)
        existing = _load(conn, key)
        if existing is not None:
            return existing
        if not isinstance(geoblender_version, str) or not geoblender_version.strip():
            raise ValueError(f"versión de Geoblender no válida: {geoblender_version!r}")
        defn = _definition(key)
        now = self._now()
        state = _State(
            value=defn.default,
            unit=defn.unit,
            kind=ParamKind(defn.kind),
            source=default_source(geoblender_version.strip()),
            source_kind=SourceKind(defn.source_kind),
            decided_by=DEFAULT_DECIDER,
            decided_at=now,
            reason=default_reason(defn),
            operation_uid=None,
            unconfirmed=True,
        )
        return self._insert(conn, defn, state, HistoryAction.DEFAULT,
                            changed_by=DEFAULT_DECIDER, now=now)

    def change(
        self,
        conn: sqlite3.Connection,
        key: str,
        *,
        value: ParamValue | None | Unset = UNSET,
        unit: str | None = None,
        kind: ParamKind | str | None | Unset = UNSET,
        source: str | None | Unset = UNSET,
        source_kind: SourceKind | str | None | Unset = UNSET,
        decided_by: str | None | Unset = UNSET,
        decided_at: dt.datetime | dt.date | str | None = None,
        reason: str | None = None,
        from_figure: str | None = None,
    ) -> ParameterRecord:
        """Cambia el valor (en ``unit``; sin ella, en la declarada), el tipo, el origen o el
        decisor de ``key`` (lo que no se pasa no cambia), con la fecha de la decisión
        (``decided_at``; sin ella, ahora) y su motivo, obligatorio (RF-008-02). Quita «sin
        confirmar»; quien cambia un valor por defecto da su origen y su decisor.

        Con ``from_figure`` (el uid de una cifra de ``gb_figure`` que calcula este
        parámetro), una persona adopta como CALCULADO el valor de la cifra (convertido a la
        unidad declarada) con la operación que la calculó (S-1); el origen es por defecto
        «cifra «<clave>» de la operación «<tipo>»» de la clase ``operation``. Sin la cifra,
        un parámetro no pasa a CALCULADO ni cambia el valor de uno CALCULADO.

        :class:`~.model.ParamError` si no está registrado, si no cambia nada o si falta o no
        vale algo; :class:`ValueError` si con la cifra se pasan el valor, la unidad u otro
        tipo, o una unidad sin valor."""
        record = self._require(conn, key)
        old = _State.of(record)
        value_type = record.value_type
        checked_with: ParamDef | None = None  # la definición con que se comprobó un valor
        if from_figure is not None:
            if value is not UNSET or unit is not None:
                raise ValueError("con la cifra de origen, el valor y la unidad son los suyos")
            if kind is not UNSET and kind != ParamKind.CALCULADO:
                raise ValueError(f"una cifra se adopta como CALCULADO, no como {kind!r}")
            defn = checked_with = _definition(key)
            figure = _figure(conn, key, record, from_figure)
            new_value = _checked_value(defn, figure.value, figure.unit)
            new_unit, value_type = defn.unit, defn.value_type
            new_kind = ParamKind.CALCULADO
            operation_uid: str | None = figure.operation_uid
            kept_source = f"cifra «{figure.key}» de la operación «{figure.op_type}»"
            kept_source_kind = SourceKind.OPERATION
        else:
            if unit is not None and value is UNSET:
                raise ValueError("una unidad sin valor: la unidad es la del valor que se teclea")
            new_kind = old.kind if kind is UNSET else _kind(key, kind)
            new_value, new_unit = old.value, old.unit
            if value is not UNSET:
                defn = checked_with = _definition(key)
                new_value = _checked_value(defn, value, unit)
                new_unit, value_type = defn.unit, defn.value_type
            value_changed = value_sha256(new_value, new_unit) != old.value_sha256
            if new_kind is ParamKind.CALCULADO and (
                    old.kind is not ParamKind.CALCULADO or value_changed):
                raise ParamError("core.param_calculated_by_hand", key=key, value=new_value)
            operation_uid = old.operation_uid if new_kind is ParamKind.CALCULADO else None
            kept_source, kept_source_kind = old.source, old.source_kind
        new = _State(
            value=new_value,
            unit=new_unit,
            kind=new_kind,
            source=kept_source if source is UNSET
            else _required(key, source, "core.param_source_missing"),
            source_kind=kept_source_kind if source_kind is UNSET
            else _source_kind(key, source_kind),
            decided_by=old.decided_by if decided_by is UNSET
            else _required(key, decided_by, "core.param_decided_by_missing"),
            decided_at=self._moment(decided_at),
            reason=None,
            operation_uid=operation_uid,
            unconfirmed=False,
        )
        # Lo que decide una persona no lleva el origen ni el decisor del valor por defecto.
        if new.source.startswith(DEFAULT_SOURCE_PREFIX):
            raise ParamError("core.param_source_missing", key=key, value=new.source)
        if new.decided_by == DEFAULT_DECIDER:
            raise ParamError("core.param_decided_by_missing", key=key, value=new.decided_by)
        dated = decided_at is not None
        if _same_decision(old, new, dated=dated):
            raise ParamError("core.param_unchanged", key=key, value=new.value)
        text = _reason(reason)
        if text is None:
            raise ParamError("core.param_reason_missing", key=key, value=new.value,
                             change=_change_text(old, new, dated=dated))
        # Un valor comprobado con la definición actual la deja como la confirmada: quita
        # «revisar» (RF-008-60). Un cambio sin valor (tipo, origen, decisor) no la quita.
        return self._update(
            conn, record, replace(new, reason=text), HistoryAction.CHANGE,
            value_type=value_type,
            def_sha256=None if checked_with is None else definition_sha256(checked_with),
        )

    def inherit(self, conn: sqlite3.Connection, parent_version: str, child_version: str, *,
                label: str) -> int:
        """Copia a la versión ``child_version`` los parámetros de versión de
        ``parent_version`` (spec 009, RF-009-01; plan 009 A1 y D-26) y devuelve cuántos: cada
        uno, una fila nueva de ``gb_parameter`` con el ámbito de la versión nueva y el mismo
        valor, unidad, tipo, origen, decisor y fecha de la decisión (y su marca «sin confirmar»,
        su «revisar» y la definición con la que se registró), con el motivo «Heredado de
        <label>» (la revisión de la padre en que ese es hoy su valor: «V10.r2»), y su fila
        ``create`` del historial, de quien escribe. Los de la padre no cambian; nada más se
        copia. :class:`ValueError` si falta una versión o la etiqueta, o si son la misma."""
        for name, value in (("parent_version", parent_version),
                            ("child_version", child_version), ("label", label)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} no es un texto con contenido: {value!r}")
        if parent_version == child_version:
            raise ValueError("una versión no hereda de sí misma")
        rows = conn.execute(
            f"SELECT {_PARAMETER_COLUMNS} FROM gb_parameter "
            "WHERE scope = ? AND scope_uid = ? ORDER BY key",
            (VERSION_SCOPE, parent_version),
        ).fetchall()
        now = self._now()
        reason = f"Heredado de {label.strip()}"
        names = [name.strip() for name in _PARAMETER_COLUMNS.split(",")]
        for row in rows:
            uid = new_uid()
            fields = dict(zip(names, row, strict=True))
            fields.update(uid=uid, scope_uid=child_version, reason=reason, rev=1,
                          created_at=now, modified_at=now)
            conn.execute(
                f"INSERT INTO gb_parameter ({_PARAMETER_COLUMNS}) "
                f"VALUES ({_marks(_PARAMETER_COLUMNS)})",
                tuple(fields[name] for name in names),
            )
            state = replace(_State.of(_record(row)), reason=reason)
            self._history(conn, uid, 1, HistoryAction.CREATE, state,
                          changed_by=self.project.session.user_host, at=now)
        return len(rows)

    def confirm(self, conn: sqlite3.Connection, key: str, *,
                reason: str | None = None) -> ParameterRecord:
        """Confirma ``key`` «sin confirmar» o «revisar» (RF-008-02, RF-008-04, RF-008-60):
        quita las dos marcas, deja la definición declarada ahora como la confirmada
        (``def_sha256``; :func:`undeclared_sha256` si ninguna la declara) y añade una fila
        con el mismo valor, tipo, origen y decisor; el motivo es opcional.

        :class:`~.model.ParamError` si no está registrado, si no tiene ninguna de las dos
        marcas o si su valor no cumple la definición actual (``core.param_review_mismatch``
        si está en otra unidad o es de otro tipo de valor; si no, el código de
        :meth:`~.model.ParamDef.check`, como ``core.param_out_of_range``): ese valor se
        cambia, no se confirma (no se convierte ni se recorta nunca)."""
        record = self._require(conn, key)
        if not record.unconfirmed and record.review is None:
            raise ParamError("core.param_nothing_to_confirm", key=key, value=record.value)
        defn = DEFINITIONS.get(key)
        if defn is None:
            def_sha = undeclared_sha256(key)
        else:
            problem = _value_problem(record, defn)
            if problem is not None:
                raise problem
            def_sha = definition_sha256(defn)
        state = replace(_State.of(record), unconfirmed=False, reason=_reason(reason))
        return self._update(conn, record, state, HistoryAction.CONFIRM,
                            value_type=record.value_type, def_sha256=def_sha)

    def mark_definition_changes(
        self, conn: sqlite3.Connection, defs: Mapping[str, ParamDef] | Iterable[ParamDef]
    ) -> builtins.list[DefinitionChange]:
        """Marca «revisar», con el cambio, cada parámetro registrado cuya definición en
        ``defs`` (las que declara el Geoblender que abre el proyecto, normalmente
        ``DEFINITIONS``) no es la registrada o confirmada, o que ya no se declara; quita la
        marca si se vuelve a declarar la registrada (RF-008-60). Solo escribe ``review`` (y
        ``modified_at``) de los que cambian: ningún valor, unidad, tipo, marca «sin
        confirmar», revisión ni fila del historial; un valor fuera del rango nuevo tampoco
        (no se convierte ni se recorta). Devuelve lo escrito, por clave (vacío si nada
        cambia: repetirlo no escribe). :class:`TypeError` o :class:`ValueError` si ``defs``
        no son ``ParamDef`` con claves distintas."""
        found = _definition_changes(conn, _declared_definitions(defs))
        if found:
            now = self._now()
            conn.executemany(
                "UPDATE gb_parameter SET review = ?, modified_at = ? WHERE uid = ?",
                [(text, now, change.parameter_uid) for change, text in found],
            )
        return [change for change, _text in found]

    def definition_changes(
        self, defs: Mapping[str, ParamDef] | Iterable[ParamDef], *,
        conn: sqlite3.Connection | None = None,
    ) -> builtins.list[DefinitionChange]:
        """Lo que escribiría :meth:`mark_definition_changes` con ``defs``, en el mismo orden,
        **sin escribir nada** (RF-008-60): la comprobación de apertura lo encuentra también en
        solo lectura y lo marca en su transacción final. Solo lee (con ``conn``, en esa
        conexión). Los mismos errores que :meth:`mark_definition_changes`."""
        declared = _declared_definitions(defs)
        with self._reading(conn) as reading:
            return [change for change, _text in _definition_changes(reading, declared)]

    # --- Interno ----------------------------------------------------------------------------

    @contextmanager
    def _reading(self, conn: sqlite3.Connection | None) -> Iterator[sqlite3.Connection]:
        if conn is not None:
            yield conn
            return
        with self.project.read() as reading:
            yield reading

    def _now(self) -> str:
        return format_utc(self.project.clock.now())

    def _moment(self, value: dt.datetime | dt.date | str | None) -> str:
        """La fecha de una decisión como texto UTC (``None``: ahora). :class:`ValueError`
        si es una hora sin zona o un texto que no es una hora UTC."""
        if value is None:
            return self._now()
        if isinstance(value, dt.datetime):
            return format_utc(value)
        if isinstance(value, dt.date):
            return format_utc(dt.datetime(value.year, value.month, value.day, tzinfo=dt.UTC))
        if isinstance(value, str):
            return format_utc(parse_utc(value))
        raise TypeError(
            f"la fecha de la decisión es una fecha, una hora con zona o un texto UTC, no "
            f"{type(value).__name__}"
        )

    def _require(self, conn: sqlite3.Connection, key: str) -> ParameterRecord:
        _check_key(key)
        record = _load(conn, key)
        if record is None:
            raise ParamError("core.param_not_registered", key=key)
        return record

    def _insert(self, conn: sqlite3.Connection, defn: ParamDef, state: _State,
                action: HistoryAction, *, changed_by: str, now: str) -> ParameterRecord:
        uid = new_uid()
        conn.execute(
            f"INSERT INTO gb_parameter ({_PARAMETER_COLUMNS}) "
            f"VALUES ({_marks(_PARAMETER_COLUMNS)})",
            (
                uid, defn.key, PROJECT_SCOPE, "", defn.module, str(defn.value_type),
                state.value_json, state.unit, str(state.kind), state.source,
                str(state.source_kind), state.decided_by, state.decided_at, state.reason,
                state.operation_uid, int(state.unconfirmed), None, definition_sha256(defn),
                state.value_sha256, 1, now, now,
            ),
        )
        self._history(conn, uid, 1, action, state, changed_by=changed_by, at=now)
        return self._require(conn, defn.key)

    def _update(self, conn: sqlite3.Connection, record: ParameterRecord, state: _State,
                action: HistoryAction, *, value_type: ValueType,
                def_sha256: str | None = None) -> ParameterRecord:
        """Escribe ``state`` como revisión siguiente; con ``def_sha256`` (la definición con
        la que se comprobó o confirmó el valor), la guarda y quita «revisar». Si cambia el
        valor o la unidad (``value_sha256``; el tipo no cuenta, D10), pone al día en la misma
        transacción la obsolescencia por región de lo que lo leyó (RF-008-24)."""
        rev = record.rev + 1
        now = self._now()
        reviewed = "" if def_sha256 is None else "review = NULL, def_sha256 = ?, "
        conn.execute(
            "UPDATE gb_parameter SET value_type = ?, value = ?, unit = ?, kind = ?, "
            "source = ?, source_kind = ?, decided_by = ?, decided_at = ?, reason = ?, "
            f"operation_uid = ?, unconfirmed = ?, {reviewed}value_sha256 = ?, rev = ?, "
            "modified_at = ? WHERE uid = ?",
            (
                str(value_type), state.value_json, state.unit, str(state.kind), state.source,
                str(state.source_kind), state.decided_by, state.decided_at,
                record.reason if state.reason is None else state.reason, state.operation_uid,
                int(state.unconfirmed), *(() if def_sha256 is None else (def_sha256,)),
                state.value_sha256, rev, now, record.uid,
            ),
        )
        self._history(conn, record.uid, rev, action, state,
                      changed_by=self.project.session.user_host, at=now)
        if state.value_sha256 != record.value_sha256:
            # Aquí: core.provenance importa core.params (ARQ-08).
            from ..provenance.stale import refresh_region

            refresh_region(conn, now=now, parameters=[record.uid])
        return self._require(conn, record.key)

    def _history(self, conn: sqlite3.Connection, parameter_uid: str, rev: int,
                 action: HistoryAction, state: _State, *, changed_by: str, at: str) -> None:
        conn.execute(
            f"INSERT INTO gb_parameter_history ({_HISTORY_COLUMNS}) "
            f"VALUES ({_marks(_HISTORY_COLUMNS)})",
            (
                parameter_uid, rev, str(action), state.value_json, state.unit, str(state.kind),
                state.source, str(state.source_kind), state.decided_by, state.decided_at,
                state.reason, state.operation_uid, int(state.unconfirmed), state.value_sha256,
                at, changed_by, self.project.session.session_uid,
            ),
        )
