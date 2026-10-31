# SPDX-License-Identifier: GPL-3.0-or-later
"""Cifras con tipo y procedencia (spec 008; RF-008-30, RF-008-59; ADR-0025 §5; plan 008
§5.3.1, §5.4.10 y D15).

Toda cifra minera que una operación hace llegar al usuario (D-5) se registra en ``gb_figure``
desde la operación **en curso** que la produce, en la transacción del módulo y antes de dejarla
«hecha»: con :func:`record_figure` o con ``OperationHandle.complete(figures=…)``. Cada una
queda con su clave (la de su :class:`~.contract.FigureDef`), su texto en español, su valor
(float64), su unidad del catálogo de unidades de Geoblender, su tipo, su operación y su ámbito
(fase, banco, unidad…: JSON canónico y :func:`scope_key`, para buscarla) (RF-008-30).

Se rechaza, nombrando su clave y su operación y sin escribir nada
(:class:`~.messages.ProvenanceError`), una cifra sin tipo, sin unidad o con una que no es la de
su definición, sin operación en curso, sin valor, NaN o infinita, y la cero o negativa que su
definición no admite. Un argumento mal formado es un error del programa (:class:`TypeError` o
:class:`ValueError`).

El tipo de una cifra (:class:`FigureSpec.kind`):

- lo que calcula una operación es CALCULADO (por defecto);
- una cifra que **muestra** un parámetro que leyó la operación (``parameter_key`` y otro
  tipo) lleva su tipo, su valor y su revisión: con otro tipo o con otro valor se rechaza (un
  valor ADOPTADO no se presenta como MEDIDO: error 34 de Silvestre);
- una cifra CALCULADO con ``parameter_key`` **calcula** ese parámetro (el K de esponjamiento de
  un balance): queda ligada a él (``parameter_uid`` y su revisión) y, si su valor difiere del
  del parámetro, deja el aviso de la spec §8 (:class:`Divergence`; :func:`divergences`).

**Ningún parámetro cambia nunca** por una cifra (RF-008-59; S-1, decisión de Samuel del
08/10/2026): ni su valor ni su tipo, tampoco uno «sin confirmar» ni uno CALCULADO. Si el
proyecto aún no tiene el parámetro que calcula una cifra, se registra con su valor por defecto
«sin confirmar», como al leerlo (RF-008-04), nunca con el calculado. Solo una persona adopta la
cifra (``ParameterStore.change(from_figure=…)``). Python puro (ADR-0004).
"""

from __future__ import annotations

import json
import math
import numbers
import re
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import KW_ONLY, dataclass, field
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from ..hashing import canonical_float, canonical_json, sha256_bytes
from ..i18n import LANGUAGES, translate
from ..ids import new_uid
from ..params.model import ParamError, ParamKind, ParamValue, ValueType, format_value
from ..params.model import definition as param_definition
from ..params.store import ParameterStore, ResolvedParam, decode_value
from ..paths import find_absolute_paths
from ..timeutil import format_utc, parse_utc
from ..units import DIMENSIONLESS, UNITS, UnitError, convert, symbol
from .contract import FIGURES, FigureDef, figure_def
from .messages import ProvenanceError, render
from .schema import RUNNING

type ScopeValue = str | int | float
"""Un valor del ámbito de una cifra: el nombre de una fase o de una unidad, un banco…"""

SCOPE_KEY_CHARS = 16
"""Caracteres del sha256 del ámbito que se guardan en ``gb_figure.scope_key``."""

RECORD_COLUMNS = (
    "uid, key, label, value, unit, kind, operation_uid, parameter_uid, parameter_rev, scope, "
    "scope_key, created_at"
)
"""Las columnas de ``gb_figure`` que lee :meth:`FigureRecord.from_row`, en su orden."""

NUMERIC_VALUE_TYPES: tuple[ValueType, ...] = (ValueType.FLOAT, ValueType.INT)
"""Los tipos de valor de un parámetro que una cifra puede calcular o mostrar."""

_SCOPE_NAME = re.compile(r"[a-z][a-z0-9_]*")
_KIND_WORDS: Mapping[str, Mapping[ParamKind, str]] = MappingProxyType({
    "es": MappingProxyType({
        ParamKind.MEDIDO: "medido",
        ParamKind.CALCULADO: "calculado",
        ParamKind.ADOPTADO: "adoptado",
        ParamKind.HIPOTESIS: "hipotético",
    }),
    "en": MappingProxyType({
        ParamKind.MEDIDO: "measured",
        ParamKind.CALCULADO: "calculated",
        ParamKind.ADOPTADO: "adopted",
        ParamKind.HIPOTESIS: "hypothetical",
    }),
})
_UNCONFIRMED: Mapping[str, str] = MappingProxyType({
    "es": "{word} sin confirmar",
    "en": "unconfirmed {word}",
})
_NO_VALUE: Mapping[str, str] = MappingProxyType({"es": "sin valor", "en": "no value"})


@runtime_checkable
class FigureOperation(Protocol):
    """Lo que usan las cifras de la operación que las produce
    (``core.provenance.OperationHandle``): su uid, su tipo, su proyecto y los parámetros que
    leyó al empezar."""

    @property
    def uid(self) -> str: ...

    @property
    def op_type(self) -> str: ...

    @property
    def project(self) -> Any: ...

    @property
    def params(self) -> tuple[ResolvedParam, ...]: ...


# --- Declaraciones y registros ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FigureSpec:
    """Una cifra que produce una operación, tal como la da el módulo (se comprueba al
    registrarla, para que el rechazo nombre su operación):

    - ``key``: la clave de su :class:`~.contract.FigureDef` registrada (``res.sellable_t``);
    - ``value``: un número real (float64; un float32 se amplía sin pérdida);
    - ``unit``: el código de su unidad, la que declara su definición (``m3``, no ``m³``;
      ``-`` si es adimensional);
    - ``kind``: CALCULADO (por defecto), o el del parámetro que muestra;
    - ``scope``: su ámbito, ``{nombre: texto | entero | real}`` (``{"phase": "1",
      "bench": 125}``; vacío, toda la operación);
    - ``parameter_key``: el parámetro que calcula (con CALCULADO) o que muestra."""

    key: str
    value: float | None
    unit: str | None
    _: KW_ONLY
    kind: ParamKind | str | None = ParamKind.CALCULADO
    scope: Mapping[str, ScopeValue] = field(default_factory=dict)
    parameter_key: str | None = None


@dataclass(frozen=True, slots=True)
class FigureRecord:
    """Una fila de ``gb_figure``: una cifra registrada, con su texto en español, su tipo, su
    operación, el parámetro que calcula o muestra (con la revisión con que se registró) y su
    ámbito; fechas en UTC."""

    uid: str
    key: str
    label: str
    value: float
    unit: str
    kind: ParamKind
    operation_uid: str
    parameter_uid: str | None
    parameter_rev: int | None
    scope: Mapping[str, ScopeValue]
    scope_key: str
    created_at: str

    @classmethod
    def from_row(cls, row: Sequence[Any]) -> FigureRecord:
        """La cifra de una fila con las columnas de :data:`RECORD_COLUMNS`."""
        (uid, key, label, value, unit, kind, operation_uid, parameter_uid, parameter_rev,
         scope, scope_key_text, created_at) = row
        return cls(
            str(uid), str(key), str(label), float(value), str(unit), ParamKind(kind),
            str(operation_uid), None if parameter_uid is None else str(parameter_uid),
            None if parameter_rev is None else int(parameter_rev),
            MappingProxyType(json.loads(scope)), str(scope_key_text), str(created_at),
        )

    @property
    def scope_json(self) -> str:
        """El ámbito como se guarda (JSON canónico)."""
        return canonical_json(dict(self.scope)).decode("utf-8")

    def text(self, *, language: str = "es") -> str:
        """La cifra como la lee una persona en ``language`` (RF-008-31; T55): su nombre (en
        inglés, el ``label_msgid`` de su definición, si está registrada), los valores de su
        ámbito y su valor con su unidad: «Años del banco (demostración) · B-1 = 2,5 año». El
        valor va entero, sin redondear, con el separador de miles (T71); el ámbito, sin él
        («2026», «fase 2»). :class:`ValueError` con otro idioma."""
        if language not in LANGUAGES:
            raise ValueError(f"el idioma «{language}» no es de Geoblender: "
                             f"{', '.join(LANGUAGES)}")
        name = self.label
        declared = FIGURES.get(self.key) if language == "en" else None
        if declared is not None:
            name = declared.label_msgid
        scope = ", ".join(format_value(value, language, grouped=False)
                          for value in self.scope.values())
        shown = f"{name} · {scope}" if scope else name
        return f"{shown} = {_shown(self.value, self.unit, language)}"


@dataclass(frozen=True, slots=True)
class Divergence:
    """El aviso de RF-008-59: la cifra CALCULADO ``figure_uid`` de la operación
    ``operation_uid`` calcula el parámetro ``parameter_key`` con un valor distinto del que
    tiene (su valor, su unidad, su tipo, si está «sin confirmar», quién y cuándo lo decidió).
    El parámetro no cambia: lo decide una persona. :attr:`text`, en español (spec §8)."""

    figure_uid: str
    figure_key: str
    label: str
    op_type: str
    operation_uid: str
    value: float
    unit: str
    parameter_uid: str
    parameter_key: str
    parameter_value: ParamValue | None
    parameter_unit: str
    parameter_kind: ParamKind
    unconfirmed: bool
    decided_by: str
    decided_at: str

    @property
    def text(self) -> str:
        """«La operación «res.balance» calcula K = 1,11; el valor adoptado es 1,23 (la
        propiedad, 24/09/2026).»"""
        return self.render("es")

    def render(self, language: str = "es") -> str:
        """El aviso en ``language`` (``"es"`` o ``"en"``); la fecha de la decisión, en hora
        local. :class:`ValueError` con otro idioma."""
        if language not in LANGUAGES:
            raise ValueError(f"el idioma «{language}» no es de Geoblender: "
                             f"{', '.join(LANGUAGES)}")
        name = self.label
        if language == "en":
            declared = FIGURES.get(self.figure_key)
            name = self.label if declared is None else declared.label_msgid
        word = _KIND_WORDS[language][self.parameter_kind]
        if self.unconfirmed:
            word = _UNCONFIRMED[language].format(word=word)
        return render(
            "core.figure_differs", language=language, op_type=self.op_type, name=name,
            value=_shown(self.value, self.unit, language), kind=word,
            parameter_value=_shown(self.parameter_value, self.parameter_unit, language),
            decided_by=self.decided_by, decided_on=_local_date(self.decided_at),
        )


# --- Presentación -------------------------------------------------------------------------


def _shown(value: ParamValue | None, unit: str, language: str = "es") -> str:
    """Un valor con su unidad como lo lee una persona: «1,11», «90,5 %», «2,65 t/m³»,
    «500 000 t/año» (con el separador de miles, como un parámetro: T71)."""
    if value is None:
        return _NO_VALUE[language]
    if isinstance(value, tuple):
        text = "[" + "; ".join(format_value(item, language) for item in value) + "]"
    else:
        text = format_value(value, language)
    if unit == DIMENSIONLESS or isinstance(value, bool | str):
        return text
    return f"{text} {symbol(unit) if unit in UNITS else unit}"


def _local_date(moment: str) -> str:
    """Una fecha UTC guardada, como día en hora local (``24/09/2026``)."""
    try:
        return parse_utc(moment).astimezone().strftime("%d/%m/%Y")
    except ValueError:
        return moment


# --- Ámbito -------------------------------------------------------------------------------


def scope_json(scope: Mapping[str, ScopeValue]) -> str:
    """El ámbito de una cifra como se guarda: JSON canónico de ``{nombre: valor}`` con
    nombres en minúsculas (``phase``, ``bench``) y valores de texto no vacío, enteros o reales
    finitos, sin rutas absolutas. :class:`TypeError`/:class:`ValueError` si no."""
    if not isinstance(scope, Mapping):
        raise TypeError(f"el ámbito de una cifra es un diccionario, no {scope!r}")
    items: dict[str, ScopeValue] = {}
    for name, item in scope.items():
        if not isinstance(name, str):
            raise TypeError(f"un nombre del ámbito de una cifra es un texto, no {name!r}")
        if _SCOPE_NAME.fullmatch(name) is None:
            raise ValueError(f"un nombre del ámbito de una cifra es un nombre en minúsculas "
                             f"(«phase», «bench»), no {name!r}")
        if isinstance(item, bool) or not isinstance(item, str | numbers.Real):
            raise TypeError(f"el ámbito «{name}» de una cifra es un texto o un número, no "
                            f"{item!r}")
        if isinstance(item, str):
            if not item.strip():
                raise ValueError(f"el ámbito «{name}» de una cifra no puede quedar vacío")
            items[name] = item
        elif isinstance(item, numbers.Integral):
            items[name] = int(item)
        else:
            number = float(item)
            if not math.isfinite(number):
                raise ValueError(f"el ámbito «{name}» de una cifra es un número finito, no "
                                 f"{item!r}")
            items[name] = canonical_float(number)
    found = find_absolute_paths(items)
    if found:
        raise ValueError(f"el ámbito de una cifra no puede llevar rutas absolutas: se guarda "
                         f"en el proyecto (ADR-0006 §5): {found}")
    return canonical_json(items).decode("utf-8")


def scope_key(scope: Mapping[str, ScopeValue]) -> str:
    """La clave de búsqueda del ámbito (``gb_figure.scope_key``): los
    :data:`SCOPE_KEY_CHARS` primeros caracteres del sha256 de :func:`scope_json`, o vacía si
    el ámbito está vacío (toda la operación)."""
    return _scope_key(scope_json(scope))


def _scope_key(text: str) -> str:
    return "" if text == "{}" else sha256_bytes(text.encode("utf-8"))[:SCOPE_KEY_CHARS]


# --- Comprobaciones -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Link:
    """El parámetro de una cifra: su clave, su uid y su revisión (``None`` si el proyecto aún
    no lo tiene: se registra su valor por defecto al escribirla)."""

    key: str
    uid: str | None
    rev: int | None


@dataclass(frozen=True, slots=True)
class PreparedFigure:
    """Una cifra comprobada y lista para escribir (:func:`prepare_figures`)."""

    definition: FigureDef
    value: float
    unit: str
    kind: ParamKind
    scope: str
    scope_key: str
    link: _Link | None


def _in_transaction(conn: object) -> sqlite3.Connection:
    if not isinstance(conn, sqlite3.Connection):
        raise TypeError(f"una cifra se registra con la conexión de la transacción del módulo, "
                        f"no {conn!r}")
    if not conn.in_transaction:
        raise ValueError("una cifra se registra dentro de la transacción de escritura del "
                         "módulo (Project.write_transaction), la que guarda sus resultados")
    return conn


def _specs(figures: object) -> tuple[FigureSpec, ...]:
    if isinstance(figures, str | bytes | Mapping) or not isinstance(figures, Iterable):
        raise TypeError(f"las cifras de una operación son una lista de FigureSpec, no "
                        f"{figures!r}")
    specs = tuple(figures)
    for spec in specs:
        _check_spec(spec)
    return specs


def _check_spec(spec: object) -> FigureSpec:
    if not isinstance(spec, FigureSpec):
        raise TypeError(f"una cifra se declara con FigureSpec, no {spec!r}")
    if not isinstance(spec.key, str):
        raise TypeError(f"la clave de una cifra es un texto, no {spec.key!r}")
    if spec.parameter_key is not None and not isinstance(spec.parameter_key, str):
        raise TypeError(f"el parámetro de la cifra «{spec.key}» se indica por su clave, no "
                        f"{spec.parameter_key!r}")
    return spec


def _check_operation(conn: sqlite3.Connection, handle: object,
                     specs: Sequence[FigureSpec]) -> FigureOperation:
    """La operación en curso que produce las cifras."""
    if handle is None:
        raise ProvenanceError("core.figure_operation_missing", key=specs[0].key)
    if not isinstance(handle, FigureOperation):
        raise TypeError(f"una cifra la registra una operación en curso (OperationHandle), no "
                        f"{handle!r}")
    row = conn.execute("SELECT status FROM gb_operation WHERE uid = ?",
                       (handle.uid,)).fetchone()
    if row is None:
        raise ProvenanceError("core.operation_unknown", operation=handle.uid,
                              project=getattr(handle.project, "name", "?"))
    if row[0] != RUNNING:
        raise ProvenanceError("core.figure_operation_not_running", key=specs[0].key,
                              op_type=handle.op_type)
    return handle


def _kind(kind: object, values: Mapping[str, object]) -> ParamKind:
    if kind is None or (isinstance(kind, str) and not kind.strip()):
        raise ProvenanceError("core.figure_kind_missing", **values)
    if not isinstance(kind, str):
        raise TypeError(f"el tipo de la cifra «{values['key']}» es un texto, no {kind!r}")
    try:
        return ParamKind(kind)
    except ValueError:
        raise ProvenanceError("core.figure_kind_unknown", kind=kind, **values) from None


def _unit(unit: object, definition: FigureDef, values: Mapping[str, object]) -> str:
    if unit is None or (isinstance(unit, str) and not unit.strip()):
        raise ProvenanceError("core.figure_unit_missing", **values)
    if not isinstance(unit, str):
        raise TypeError(f"la unidad de la cifra «{values['key']}» es el código de una unidad, "
                        f"no {unit!r}")
    if unit not in UNITS:
        raise ProvenanceError("core.figure_unit_unknown", unit=unit, **values)
    if unit != definition.unit:
        raise ProvenanceError("core.figure_unit_other", unit=symbol(unit),
                              declared=symbol(definition.unit), **values)
    return unit


def _value(value: object, definition: FigureDef, values: Mapping[str, object]) -> float:
    if value is None:
        raise ProvenanceError("core.figure_value_missing", **values)
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"el valor de la cifra «{values['key']}» es un número, no {value!r}")
    try:
        number = canonical_float(value)
    except OverflowError:  # un entero que no cabe en un float64
        number = math.inf
    if math.isnan(number):
        raise ProvenanceError("core.figure_nan", **values)
    if math.isinf(number):
        raise ProvenanceError("core.figure_infinite", **values)
    if number == 0.0 and not definition.allow_zero:
        raise ProvenanceError("core.figure_zero", **values)
    if number < 0.0 and not definition.allow_negative:
        raise ProvenanceError("core.figure_negative", value=number, **values)
    return number


def _numeric(key: str, parameter: str, value_type: object) -> None:
    if value_type not in NUMERIC_VALUE_TYPES:
        raise ValueError(f"la cifra «{key}» solo calcula o muestra un parámetro numérico; "
                         f"«{parameter}» es de tipo {value_type}")


def _in_unit(value: float, unit: str, target: str) -> float:
    return value if unit == target else convert(value, unit, target)


def _comparable(key: str, unit: str, parameter: str, target: str) -> None:
    try:
        _in_unit(1.0, unit, target)
    except UnitError as exc:
        raise ValueError(f"la cifra «{key}» ({unit}) no puede calcular ni mostrar el parámetro "
                         f"«{parameter}» ({target}): {exc}") from None


def _calculated(conn: sqlite3.Connection, handle: FigureOperation, key: str, unit: str,
                parameter: str) -> _Link:
    """El parámetro que calcula una cifra CALCULADO: el del proyecto ahora (en ``conn``) o, si
    aún no lo tiene, su definición (se registrará con su valor por defecto)."""
    record = ParameterStore(handle.project).get(parameter, conn=conn)
    if record is not None:
        _numeric(key, parameter, record.value_type)
        _comparable(key, unit, parameter, record.unit)
        return _Link(parameter, record.uid, record.rev)
    defn = param_definition(parameter)  # la registrada o la de su familia (ADR-0027)
    if defn is None:
        raise ParamError("core.param_undefined", key=parameter)
    if defn.scope != "project":
        raise ValueError(f"el parámetro «{parameter}» es de ámbito {defn.scope!r}: en esta spec "
                         "las cifras calculan parámetros del proyecto")
    _numeric(key, parameter, defn.value_type)
    _comparable(key, unit, parameter, defn.unit)
    return _Link(parameter, None, None)


def _shown_parameter(handle: FigureOperation, key: str, value: float, unit: str,
                     kind: ParamKind, parameter: str, values: Mapping[str, object]) -> _Link:
    """El parámetro que muestra una cifra: el que leyó la operación al empezar, con su tipo y
    su valor (en cualquier unidad convertible)."""
    resolved = next((item for item in handle.params if item.key == parameter), None)
    if resolved is None:
        raise ValueError(
            f"la cifra «{key}» muestra el parámetro «{parameter}», que la operación "
            f"«{handle.op_type}» no leyó (begin_operation(params=…)): una cifra solo muestra el "
            "valor de un parámetro que leyó su operación"
        )
    read = resolved.value
    if isinstance(read, bool) or not isinstance(read, int | float):
        raise ValueError(f"la cifra «{key}» solo muestra un parámetro numérico; «{parameter}» "
                         f"vale {read!r}")
    _comparable(key, unit, parameter, resolved.unit)
    if kind != resolved.kind:
        raise ProvenanceError("core.figure_parameter_kind", parameter=parameter,
                              parameter_kind=str(resolved.kind), kind=str(kind), **values)
    if _in_unit(value, unit, resolved.unit) != float(read):
        raise ProvenanceError("core.figure_parameter_value", parameter=parameter,
                              parameter_value=_shown(read, resolved.unit),
                              value=_shown(value, unit), **values)
    return _Link(parameter, resolved.parameter_uid, resolved.rev)


def _prepare(conn: sqlite3.Connection, handle: FigureOperation,
             spec: FigureSpec) -> PreparedFigure:
    definition = figure_def(spec.key)
    values = {"key": spec.key, "op_type": handle.op_type}
    kind = _kind(spec.kind, values)
    unit = _unit(spec.unit, definition, values)
    value = _value(spec.value, definition, values)
    scope = scope_json(spec.scope)
    link: _Link | None = None
    if spec.parameter_key is None:
        if kind is not ParamKind.CALCULADO:
            raise ProvenanceError("core.figure_kind_without_parameter", kind=str(kind),
                                  **values)
    elif kind is ParamKind.CALCULADO:
        link = _calculated(conn, handle, spec.key, unit, spec.parameter_key)
    else:
        link = _shown_parameter(handle, spec.key, value, unit, kind, spec.parameter_key,
                                values)
    return PreparedFigure(definition, value, unit, kind, scope, _scope_key(scope), link)


def prepare_figures(conn: sqlite3.Connection, handle: FigureOperation,
                    figures: Iterable[FigureSpec]) -> tuple[PreparedFigure, ...]:
    """Comprueba, **sin escribir nada**, las cifras ``figures`` de la operación en curso
    ``handle`` en la transacción del módulo ``conn`` (la usa ``OperationHandle.complete``
    antes de escribir sus salidas). Los rechazos de :func:`record_figure`; además,
    :class:`ValueError` si una cifra (clave y ámbito) se repite en la operación."""
    specs = _specs(figures)
    _in_transaction(conn)
    if not specs:
        return ()
    checked = _check_operation(conn, handle, specs)
    prepared = tuple(_prepare(conn, checked, spec) for spec in specs)
    # Una sola lectura de lo ya escrito por la operación: la tabla no tiene índice por operación
    # y leerla una vez por cifra la recorría entera cada vez (con 7.500 cifras, de 13 s a 47 s
    # al repetir una verificación).
    stored = {(str(key), str(scope)) for key, scope in conn.execute(
        "SELECT key, scope FROM gb_figure WHERE operation_uid = ?", (checked.uid,))}
    seen: set[tuple[str, str]] = set()
    for item in prepared:
        pair = (item.definition.key, item.scope)
        if pair in seen or pair in stored:
            raise ValueError(f"la operación «{checked.op_type}» registra la cifra «{pair[0]}» "
                             f"con el ámbito {pair[1]} una sola vez")
        seen.add(pair)
    return prepared


def write_figures(conn: sqlite3.Connection, handle: FigureOperation,
                  prepared: Iterable[PreparedFigure]) -> tuple[FigureRecord, ...]:
    """Escribe en ``gb_figure`` las cifras ya comprobadas (:func:`prepare_figures`), con su
    texto en español y la hora del proyecto, y las devuelve en su orden. El parámetro que
    calcula una cifra y el proyecto aún no tiene se registra con su valor por defecto «sin
    confirmar» (RF-008-04), nunca con el calculado (S-1)."""
    now = format_utc(handle.project.clock.now())
    store = ParameterStore(handle.project)
    records: list[FigureRecord] = []
    for item in prepared:
        parameter_uid: str | None = None
        parameter_rev: int | None = None
        if item.link is not None:
            parameter_uid, parameter_rev = item.link.uid, item.link.rev
            if parameter_uid is None:
                record = store.ensure_default(
                    conn, item.link.key,
                    geoblender_version=handle.project.session.geoblender_version,
                )
                parameter_uid, parameter_rev = record.uid, record.rev
        figure = FigureRecord(
            new_uid(), item.definition.key, translate("es", item.definition.label_msgid),
            item.value, item.unit, item.kind, handle.uid, parameter_uid, parameter_rev,
            MappingProxyType(json.loads(item.scope)), item.scope_key, now,
        )
        conn.execute(
            f"INSERT INTO gb_figure ({RECORD_COLUMNS}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (figure.uid, figure.key, figure.label, figure.value, figure.unit, str(figure.kind),
             figure.operation_uid, figure.parameter_uid, figure.parameter_rev, item.scope,
             figure.scope_key, figure.created_at),
        )
        records.append(figure)
    return tuple(records)


def record_figure(conn: sqlite3.Connection, handle: FigureOperation,
                  spec: FigureSpec) -> FigureRecord:
    """Registra la cifra ``spec`` de la operación en curso ``handle`` en la transacción del
    módulo ``conn`` (la que guarda sus resultados; no la confirma) y la devuelve (RF-008-30).

    :class:`~.messages.ProvenanceError`, que nombra su clave y su operación, sin escribir
    nada: sin operación (``core.figure_operation_missing``) o ya terminada
    (``core.figure_operation_not_running``), sin declarar (``core.figure_unregistered``), sin
    tipo o con uno desconocido (``core.figure_kind_missing``/``_unknown``), de otro tipo que
    CALCULADO sin mostrar un parámetro (``core.figure_kind_without_parameter``), sin unidad,
    con una que no está en el catálogo o que no es la de su definición
    (``core.figure_unit_missing``/``_unknown``/``_other``), sin valor, NaN o infinita
    (``core.figure_value_missing``, ``core.figure_nan``, ``core.figure_infinite``), cero o
    negativa sin que su definición lo admita (``core.figure_zero``/``_negative``) y la que
    muestra un parámetro con otro tipo o con otro valor (``core.figure_parameter_kind``/
    ``_value``). :class:`TypeError`/:class:`ValueError` con un argumento mal formado, fuera de
    una transacción de escritura o si la cifra (clave y ámbito) ya está en la operación.

    Con ``parameter_key`` y CALCULADO, la cifra calcula ese parámetro: si difiere de él,
    :func:`divergence` da el aviso; el parámetro no cambia nunca (RF-008-59)."""
    spec = _check_spec(spec)
    prepared = prepare_figures(conn, handle, (spec,))
    (figure,) = write_figures(conn, handle, prepared)
    return figure


# --- El aviso de RF-008-59 ----------------------------------------------------------------


def _same(value: float, unit: str, parameter_value: ParamValue | None,
          parameter_unit: str) -> bool:
    if isinstance(parameter_value, bool) or not isinstance(parameter_value, int | float):
        return False
    try:
        return _in_unit(value, unit, parameter_unit) == float(parameter_value)
    except UnitError:
        return False


def divergence(conn: sqlite3.Connection, figure: FigureRecord) -> Divergence | None:
    """El aviso de RF-008-59 para ``figure`` según el parámetro **ahora** (en ``conn``): si es
    una cifra CALCULADO que calcula un parámetro y su valor (en la unidad del parámetro)
    difiere del de este, la :class:`Divergence`; si no, ``None`` (también cuando una persona
    ya adoptó la cifra)."""
    if not isinstance(figure, FigureRecord):
        raise TypeError(f"el aviso se pide de una cifra registrada (FigureRecord), no "
                        f"{figure!r}")
    if figure.kind is not ParamKind.CALCULADO or figure.parameter_uid is None:
        return None
    row = conn.execute(
        "SELECT p.key, p.value, p.unit, p.kind, p.unconfirmed, p.decided_by, p.decided_at, "
        "o.op_type FROM gb_parameter AS p, gb_operation AS o WHERE p.uid = ? AND o.uid = ?",
        (figure.parameter_uid, figure.operation_uid),
    ).fetchone()
    if row is None:
        return None
    key, text, unit, kind, unconfirmed, decided_by, decided_at, op_type = row
    value = decode_value(text)
    if _same(figure.value, figure.unit, value, unit):
        return None
    return Divergence(
        figure.uid, figure.key, figure.label, str(op_type), figure.operation_uid,
        figure.value, figure.unit, figure.parameter_uid, str(key), value, str(unit),
        ParamKind(kind), bool(unconfirmed), str(decided_by), str(decided_at),
    )


def parameter_divergence(conn: sqlite3.Connection, parameter_uid: str) -> Divergence | None:
    """El aviso de RF-008-59 que se enseña junto al parámetro ``parameter_uid`` (el panel de
    parámetros, RF-008-06): el de la **última** cifra CALCULADO que lo calcula, si difiere de
    su valor de ahora (:func:`divergence`); si la última coincide, no hay ninguna o el
    parámetro no existe, ``None``. Solo lee: lo decide una persona (S-1)."""
    if not isinstance(parameter_uid, str):
        raise TypeError(f"un parámetro se indica por su uid, no {parameter_uid!r}")
    row = conn.execute(
        f"SELECT {RECORD_COLUMNS} FROM gb_figure WHERE parameter_uid = ? AND kind = ? "
        "ORDER BY fid DESC LIMIT 1",
        (parameter_uid, str(ParamKind.CALCULADO)),
    ).fetchone()
    return None if row is None else divergence(conn, FigureRecord.from_row(row))


def divergences(conn: sqlite3.Connection, operation_uid: str) -> list[Divergence]:
    """Los avisos de RF-008-59 de las cifras de la operación ``operation_uid``, en su orden
    (:func:`divergence`): lo que el módulo muestra al usuario tras completarla."""
    if not isinstance(operation_uid, str):
        raise TypeError(f"una operación se indica por su uid, no {operation_uid!r}")
    rows = conn.execute(
        f"SELECT {RECORD_COLUMNS} FROM gb_figure WHERE operation_uid = ? AND kind = ? "
        "AND parameter_uid IS NOT NULL ORDER BY fid",
        (operation_uid, str(ParamKind.CALCULADO)),
    ).fetchall()
    found: list[Divergence] = []
    for row in rows:
        warning = divergence(conn, FigureRecord.from_row(row))
        if warning is not None:
            found.append(warning)
    return found
