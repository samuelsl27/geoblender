# SPDX-License-Identifier: GPL-3.0-or-later
"""Contrato de procedencia de los módulos: declaraciones y sus registros (spec 008; RF-008-17,
RF-008-25; ADR-0025 §2; plan 008 §5.1, §5.3.1 y §5.3.4).

Un módulo se enchufa a la procedencia **declarando** con tipos de ``core``, en su paquete de
dominio, lo que produce, y **registrándolo** desde su ``bl/ops/<módulo>.py`` en ``register()``
(y quitándolo en ``unregister()``), como los tipos de trabajo de la 004: ``core`` no importa
los módulos (ADR-0004).

- :class:`OperationDef`: un tipo de operación ``<código>.<acción>`` (``gis.resample``), la
  versión ``M.m`` de su algoritmo (sube cuando un cambio puede mover una cifra), su módulo, su
  nombre visible (``msgid``), si se puede repetir sola (y entonces su función de recálculo),
  su grupo de operaciones acopladas, su ámbito (``project``; ``version`` con la 009), las
  órdenes (``bl_idname``) que la lanzan, las bibliotecas que influyen en sus cifras, los
  ajustes de su orden que enseña su procedencia (:class:`SettingDef`; spec 006, T58) y, con la
  009, cómo se reproduce y con qué tolerancia de sus cifras (:class:`Tolerance`).
- :class:`SettingDef`: un ajuste de una operación (``gb_operation.settings``) que importa a
  quien revisa el resultado, con su nombre visible y su unidad (un número) o sus elecciones;
  ni las rutas ni lo interno (nombres, uids…) se declaran, así que no se enseñan.
- :class:`CoupledGroupDef`: operaciones que siempre se ejecutan juntas, en su orden; si una
  queda obsoleta, todas, y ninguna se recalcula sin las demás (RF-008-25).
- :class:`FigureDef`: una cifra, con su unidad del catálogo y si admite cero o negativos.
- :class:`ImporterDef`: cómo reimportar las entradas de un lector de contenido con sus
  ajustes registrados (RF-008-11): su función recibe una :class:`ReimportRequest` y, si los
  ajustes registrados ya no sirven (una capa o una columna que ya no está), los pide con
  :class:`SettingsNeeded`.

Una declaración incoherente es un error del programa: :class:`ValueError` (o
:class:`TypeError` si un campo no es del tipo de Python que toca) al crearla o al
registrarla. Cada registro tiene su vista de solo lectura (:data:`OPERATIONS`,
:data:`GROUPS`, :data:`FIGURES` e :data:`IMPORTERS`), su ``register_*`` (un tipo, un grupo,
una cifra o un importador se registra una sola vez), su ``unregister_*`` (idempotente; un tipo
no se quita mientras su grupo está registrado) y su búsqueda, que da un
:class:`~.messages.ProvenanceError` si no está (el módulo que lo declara no está activo). Un
grupo se registra después de sus tipos y se quita antes.

``core`` declara sus operaciones en :data:`CORE_OPERATIONS` (las registra ``bl/``):
``core.external_edit`` (una edición hecha fuera de Geoblender, D9) y ``core.external_edit_version``
(la misma, de un dato **de una versión**: spec 015, T20), ``core.accept_review``
(«dar por buena» una operación que espera revisión a mano, D8) y ``core.import_layer``
(registrar una capa de un GeoPackage como entrada, D14; su importador, el del lector
``core.gpkg_layer``, está en ``core.provenance.importer``). Ninguna se repite sola. Python
puro (ADR-0004).
"""

from __future__ import annotations

import math
import numbers
import re
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import KW_ONLY, dataclass
from types import MappingProxyType
from typing import Any

from ..catalog.schema import IDNAME_RE, MODULE_CODES, SPANISH_LETTERS
from ..units import UNITS
from .messages import (
    ACCEPT_REVIEW_MSGID,
    EXTERNAL_EDIT_MSGID,
    IMPORT_LAYER_MSGID,
    ProvenanceError,
)

type RecomputeFunction = Callable[[Any], Any]
"""``recompute(request) -> handle``: vuelve a ejecutar una operación con las entradas y los
parámetros vigentes (``recompute.RecomputeRequest``) y devuelve la operación nueva, que la
sustituye (``recompute.RecomputeHandle``: su ``OperationHandle``)."""
type ReproduceFunction = Callable[[Any], Any]
"""``reproduce(request) -> Iterator[Progress]``: vuelve a ejecutar, fuera del proyecto, una
operación congelada con sus entradas y sus parámetros congelados (``ReproduceRequest``, spec 009,
RF-009-11; plan 009 §5.3.3); su último paso lleva el resultado (``ReproducedResult``). No recibe
el proyecto ni escribe en él."""
type ReimportFunction = Callable[[Any], Any]
"""``reimport(request) -> result``: vuelve a importar una entrada con sus ajustes registrados
(:class:`ReimportRequest`) como una entrada nueva que la sustituye, y devuelve el resultado de
su importación (algo con el ``uid`` de la operación nueva, como ``recompute.RecomputeHandle``);
si los ajustes ya no sirven, :class:`SettingsNeeded`."""

SCOPES: tuple[str, ...] = ("project", "version")
"""Ámbitos de un tipo de operación (``gb_operation.scope``; D-2): del proyecto (hoy, todas) o
de cada versión (con la spec 009)."""

_OP_TYPE = re.compile(r"(?P<module>[a-z]+)\.[a-z][a-z0-9_]*")
_KEY = re.compile(r"(?P<module>[a-z]+)(?:\.[a-z][a-z0-9_]*)+")
_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
_READER_ID = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+")
_LIBRARY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]*")
_SETTING_KEY = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*")
_CODES = ", ".join(MODULE_CODES)


def parse_version(text: str) -> tuple[int, int]:
    """La versión ``M.m`` de un algoritmo como ``(M, m)``, para compararla (``"1.10"`` es
    mayor que ``"1.9"``). :class:`ValueError` si no tiene esa forma (enteros sin ceros a la
    izquierda: ``"1.01"`` no vale)."""
    match = _VERSION.fullmatch(text) if isinstance(text, str) else None
    if match is None:
        raise ValueError(
            f"la versión de un algoritmo es el texto «M.m» (dos enteros sin ceros a la "
            f"izquierda, como «1.0» o «2.15»), no {text!r}"
        )
    return int(match[1]), int(match[2])


def _module_name(value: object, pattern: re.Pattern[str]) -> str | None:
    """El código de módulo de ``value`` si cumple ``pattern`` y es de Geoblender."""
    match = pattern.fullmatch(value) if isinstance(value, str) else None
    if match is None or match["module"] not in MODULE_CODES:
        return None
    return match["module"]


def _check_msgid(value: object, owner: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"«label_msgid» {owner} es un msgid no vacío, no {value!r}")
    if set(value) & SPANISH_LETTERS:
        raise ValueError(
            f"«label_msgid» {owner} ({value!r}) es el msgid en inglés; su español va en el "
            "catálogo de mensajes"
        )


def _names(value: object, field: str, owner: str, pattern: re.Pattern[str]) -> tuple[str, ...]:
    """``value`` como tupla de textos que cumplen ``pattern``, sin repetir."""
    if isinstance(value, str | bytes) or not isinstance(value, Iterable):
        raise ValueError(f"«{field}» de «{owner}» es una lista de textos, no {value!r}")
    items = tuple(value)
    for item in items:
        if not isinstance(item, str) or pattern.fullmatch(item) is None:
            raise ValueError(f"«{field}» de «{owner}»: {item!r} no vale")
    if len(set(items)) != len(items):
        raise ValueError(f"«{field}» de «{owner}» repite un nombre: {list(items)!r}")
    return items


def _check_bool(value: object, field: str, owner: str) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"«{field}» de «{owner}» es verdadero o falso, no {value!r}")


# --- Declaraciones ----------------------------------------------------------------------------

type SettingValue = str | int | float | bool | None
"""Un valor de una elección tal como lo guarda la operación en sus ajustes (JSON)."""


@dataclass(frozen=True, slots=True)
class SettingDef:
    """Un ajuste de la orden de un tipo de operación que enseña su procedencia (RF-008-29;
    spec 006, T58), comprobado al crearlo: de los ajustes que guarda la operación
    (``gb_operation.settings``, JSON), uno que importa a quien revisa el resultado; las rutas
    y lo interno (nombres, uids…) no se declaran, así que nunca se enseñan.

    - ``key``: dónde está en los ajustes, un nombre en minúsculas; con «.», dentro de uno
      anidado (``read.decimal``: ``decimal`` dentro de ``read``);
    - ``label_msgid``: su nombre visible, un ``msgid`` en inglés con su español en el
      catálogo de su módulo (el del campo de su diálogo);
    - con su nombre, uno de los dos: ``unit``, si es un número (el código de su unidad en
      ``core.units``; ``-`` si es adimensional), o ``choices``, si es una elección (cada valor
      guardado con el ``msgid`` del nombre con que se elige, sin repetir valores).
    """

    key: str
    label_msgid: str
    _: KW_ONLY
    unit: str | None = None
    choices: tuple[tuple[SettingValue, str], ...] = ()

    def __post_init__(self) -> None:
        key = self.key
        if not isinstance(key, str) or _SETTING_KEY.fullmatch(key) is None:
            raise ValueError(
                f"«key» de un ajuste es un nombre en minúsculas, con «.» para uno anidado "
                f"(como «interval_m» o «read.decimal»), no {key!r}"
            )
        _check_msgid(self.label_msgid, f"del ajuste «{key}»")
        if self.unit is not None and (not isinstance(self.unit, str) or self.unit not in UNITS):
            raise ValueError(
                f"«unit» del ajuste «{key}» ({self.unit!r}) no está en el catálogo de unidades "
                "de Geoblender (core.units; se escribe su código: «m3», no «m³»)"
            )
        choices = _choices(self.choices, key)
        if (self.unit is None) == (not choices):
            raise ValueError(
                f"el ajuste «{key}» es un número con su unidad («unit») o una elección con sus "
                "valores («choices»): uno de los dos"
            )
        object.__setattr__(self, "choices", choices)

    def choice_msgid(self, value: object) -> str | None:
        """El ``msgid`` del nombre de la elección ``value``; ``None`` si no es una de las
        declaradas."""
        for declared, msgid in self.choices:
            if declared == value and type(declared) is type(value):
                return msgid
        return None


def _choices(value: object, key: str) -> tuple[tuple[SettingValue, str], ...]:
    """Las elecciones de un ajuste como tupla de pares (valor guardado, ``msgid``)."""
    if isinstance(value, str | bytes) or not isinstance(value, Iterable):
        raise ValueError(f"«choices» del ajuste «{key}» es una lista de pares (valor, msgid), "
                         f"no {value!r}")
    found: list[tuple[SettingValue, str]] = []
    for pair in value:
        if not isinstance(pair, tuple) or len(pair) != 2 or (
                pair[0] is not None and not isinstance(pair[0], str | int | float | bool)):
            raise ValueError(f"«choices» del ajuste «{key}»: {pair!r} no es un par (valor "
                             "guardado, msgid) con un valor de JSON")
        if not isinstance(pair[1], str) or not pair[1].strip() or set(pair[1]) & SPANISH_LETTERS:
            raise ValueError(f"«choices» del ajuste «{key}»: el nombre de {pair[0]!r} es un "
                             f"msgid en inglés no vacío, no {pair[1]!r}")
        if any(seen == pair[0] and type(seen) is type(pair[0]) for seen, _msgid in found):
            raise ValueError(f"«choices» del ajuste «{key}» repite el valor {pair[0]!r}")
        found.append((pair[0], pair[1]))
    return tuple(found)


def _settings(value: object, owner: str) -> tuple[SettingDef, ...]:
    """``value`` como tupla de :class:`SettingDef` sin repetir clave."""
    if isinstance(value, str | bytes | SettingDef) or not isinstance(value, Iterable):
        raise ValueError(f"«settings» de «{owner}» es una lista de SettingDef, no {value!r}")
    items = tuple(value)
    for item in items:
        if not isinstance(item, SettingDef):
            raise TypeError(f"«settings» de «{owner}»: {item!r} no es un SettingDef")
    keys = [item.key for item in items]
    if len(set(keys)) != len(keys):
        raise ValueError(f"«settings» de «{owner}» repite una clave: {keys!r}")
    return items


@dataclass(frozen=True, slots=True)
class Tolerance:
    """Cuánto puede diferir una cifra reproducida de la congelada (spec 009, RF-009-11; plan
    009 §5.3.3): ``relative`` (fracción del valor congelado) y ``absolute`` (en la unidad de la
    cifra), números reales finitos y ≥ 0, guardados como ``float``; por defecto, ninguna
    (exactas). :class:`TypeError` si no son números (``True`` no lo es) y :class:`ValueError` si
    son negativos, NaN o infinitos."""

    relative: float = 0.0
    absolute: float = 0.0

    def __post_init__(self) -> None:
        for name in ("relative", "absolute"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, numbers.Real):
                raise TypeError(f"la tolerancia {name} de una cifra es un número, no {value!r}")
            number = float(value)
            if not math.isfinite(number) or number < 0:
                raise ValueError(f"la tolerancia {name} de una cifra es un número finito y no "
                                 f"negativo, no {value!r}")
            object.__setattr__(self, name, number)


@dataclass(frozen=True, slots=True)
class OperationDef:
    """Un tipo de operación, comprobado al crearlo:

    - ``op_type``: ``<código>.<acción>`` en minúsculas, con un código de módulo de
      ``docs/sdd/convenciones.md`` §5 (``gis.resample``);
    - ``version``: la del algoritmo, el texto ``M.m`` (:func:`parse_version`); sube cuando un
      cambio puede mover una cifra, y una mayor que la registrada deja obsoletas las
      operaciones de ese tipo (RF-008-24);
    - ``module``: el código de su tipo (``gb_operation.module``);
    - ``label_msgid``: su nombre visible, un ``msgid`` en inglés con su español en el
      catálogo de su módulo;
    - ``repeatable``: si se puede repetir sola; una repetible declara ``recompute`` y una que
      no (una importación, una edición a mano) no la tiene: queda «revisar a mano»
      (RF-008-26, RF-008-27);
    - con su nombre: ``group`` (su :class:`CoupledGroupDef`, ``<código>.<nombre>``), ``scope``
      (:data:`SCOPES`), ``commands`` (los ``bl_idname`` que la lanzan, para su estado de
      comando, RF-008-61), ``libraries`` (las que influyen en sus cifras, RF-008-18),
      ``recompute`` y ``settings`` (los :class:`SettingDef` que enseña su procedencia, en su
      orden y sin repetir clave; ninguno, por defecto: RF-008-29, spec 006, T58);
    - ``drops_discarded`` (spec 005, T42; plan 005 §5.6.10): si su recálculo reúne él mismo
      todo lo vigente que consume (como la base de los sondeos, con todo lo importado vigente):
      lo que consumió y después se descartó sin sucesor sale de su recálculo en vez de
      impedirlo (``core.recompute_no_successor``, RF-008-55); solo en una que se repite sola.
      Por defecto, no;
    - ``reproduce`` (spec 009, RF-009-11; plan 009 §5.3.3): la función que la vuelve a
      ejecutar fuera del proyecto con lo congelado (:data:`ReproduceFunction`); sin ella (una
      importación, una edición a mano), al reproducir se toma lo congelado. Por defecto, ninguna;
    - ``figure_tolerance``: la :class:`Tolerance` de sus cifras al reproducirla, si no salen bit
      a bit; solo la declara una que se reproduce. Por defecto, ninguna (exactas).
    """

    op_type: str
    version: str
    module: str
    label_msgid: str
    repeatable: bool
    _: KW_ONLY
    group: str | None = None
    scope: str = "project"
    commands: tuple[str, ...] = ()
    libraries: tuple[str, ...] = ()
    recompute: RecomputeFunction | None = None
    settings: tuple[SettingDef, ...] = ()
    drops_discarded: bool = False
    reproduce: ReproduceFunction | None = None
    figure_tolerance: Tolerance | None = None

    def __post_init__(self) -> None:
        op_type = self.op_type
        module = _module_name(op_type, _OP_TYPE)
        if module is None:
            raise ValueError(
                f"el tipo de operación {op_type!r} no es <código>.<acción> en minúsculas, con "
                f"un código de módulo de {_CODES} (como «gis.resample»)"
            )
        if not isinstance(self.version, str) or _VERSION.fullmatch(self.version) is None:
            raise ValueError(
                f"la versión del algoritmo de «{op_type}» es el texto «M.m» (como «1.0»; sube "
                f"cuando un cambio puede mover una cifra), no {self.version!r}"
            )
        if self.module != module:
            raise ValueError(
                f"«module» de «{op_type}» es {self.module!r}: tiene que ser el código de su "
                f"tipo, «{module}»"
            )
        _check_msgid(self.label_msgid, f"de la operación «{op_type}»")
        _check_bool(self.repeatable, "repeatable", op_type)
        if self.recompute is not None and not callable(self.recompute):
            raise TypeError(
                f"«recompute» de «{op_type}» es una función o None, no "
                f"{type(self.recompute).__name__}"
            )
        if self.repeatable and self.recompute is None:
            raise ValueError(
                f"la operación «{op_type}» se puede repetir sola y no declara su función de "
                "recálculo («recompute»): sin ella, «Recalcular lo obsoleto» no podría "
                "repetirla"
            )
        if not self.repeatable and self.recompute is not None:
            raise ValueError(
                f"la operación «{op_type}» no se puede repetir sola (queda «revisar a mano»): "
                "no tiene función de recálculo («recompute»)"
            )
        _check_bool(self.drops_discarded, "drops_discarded", op_type)
        if self.drops_discarded and not self.repeatable:
            raise ValueError(
                f"la operación «{op_type}» no se puede repetir sola: «drops_discarded» solo lo "
                "declara una que se recalcula reuniendo lo vigente"
            )
        if self.group is not None and _module_name(self.group, _OP_TYPE) is None:
            raise ValueError(
                f"«group» de «{op_type}» es <código>.<nombre> en minúsculas o None, no "
                f"{self.group!r}"
            )
        if not isinstance(self.scope, str) or self.scope not in SCOPES:
            raise ValueError(
                f"«scope» de «{op_type}» es {' o '.join(SCOPES)}, no {self.scope!r}"
            )
        if self.reproduce is not None and not callable(self.reproduce):
            raise TypeError(
                f"«reproduce» de «{op_type}» es una función o None, no "
                f"{type(self.reproduce).__name__}"
            )
        if self.figure_tolerance is not None:
            if not isinstance(self.figure_tolerance, Tolerance):
                raise TypeError(
                    f"«figure_tolerance» de «{op_type}» es una Tolerance o None, no "
                    f"{self.figure_tolerance!r}"
                )
            if self.reproduce is None:
                raise ValueError(
                    f"la operación «{op_type}» no se reproduce («reproduce»): la tolerancia de "
                    "sus cifras al reproducirla («figure_tolerance») no se usaría"
                )
        object.__setattr__(self, "commands", _names(self.commands, "commands", op_type,
                                                    IDNAME_RE))
        object.__setattr__(self, "libraries", _names(self.libraries, "libraries", op_type,
                                                     _LIBRARY))
        object.__setattr__(self, "settings", _settings(self.settings, op_type))

    @property
    def version_tuple(self) -> tuple[int, int]:
        """La versión como ``(M, m)``, para compararla."""
        return parse_version(self.version)


@dataclass(frozen=True, slots=True)
class CoupledGroupDef:
    """Un grupo de operaciones acopladas (RF-008-25): ``name`` (``<código>.<nombre>``) y sus
    tipos, dos o más y distintos, en su orden de ejecución dentro del grupo. Se registra
    después de sus tipos, que lo declaran en ``OperationDef.group``."""

    name: str
    op_types: tuple[str, ...]

    def __post_init__(self) -> None:
        if _module_name(self.name, _OP_TYPE) is None:
            raise ValueError(
                f"el nombre del grupo {self.name!r} no es <código>.<nombre> en minúsculas, con "
                f"un código de módulo de {_CODES}"
            )
        value = self.op_types
        if isinstance(value, str | bytes) or not isinstance(value, Iterable):
            raise ValueError(f"los tipos del grupo «{self.name}» son una lista, no {value!r}")
        op_types = tuple(value)
        for op_type in op_types:
            if _module_name(op_type, _OP_TYPE) is None:
                raise ValueError(
                    f"el grupo «{self.name}» tiene un tipo que no es <código>.<acción>: "
                    f"{op_type!r}"
                )
        if len(op_types) < 2 or len(set(op_types)) != len(op_types):
            raise ValueError(
                f"el grupo «{self.name}» acopla dos o más tipos distintos, no {list(op_types)!r}"
            )
        object.__setattr__(self, "op_types", op_types)

    @property
    def module(self) -> str:
        """El código del módulo del grupo."""
        return self.name.partition(".")[0]


@dataclass(frozen=True, slots=True)
class FigureDef:
    """Una cifra que produce un módulo (RF-008-30): ``key`` (``<código>.<nombre>[.<más>]``,
    como ``res.sellable_t``), ``unit`` (código del catálogo de ``core.units``: ``m3``, no
    ``m³``; ``-`` si es adimensional), ``label_msgid`` (su nombre visible, un ``msgid`` en
    inglés) y, con su nombre, si admite cero (por defecto, sí) o negativos (por defecto, no:
    un relleno neto los admite)."""

    key: str
    unit: str
    label_msgid: str
    _: KW_ONLY
    allow_zero: bool = True
    allow_negative: bool = False

    def __post_init__(self) -> None:
        if _module_name(self.key, _KEY) is None:
            raise ValueError(
                f"la clave de la cifra {self.key!r} no es <código>.<nombre> en minúsculas, con "
                f"un código de módulo de {_CODES} (como «res.sellable_t»)"
            )
        if not isinstance(self.unit, str) or self.unit not in UNITS:
            raise ValueError(
                f"la unidad de la cifra «{self.key}» ({self.unit!r}) no está en el catálogo de "
                "unidades de Geoblender (core.units; se escribe su código: «m3», no «m³»)"
            )
        _check_msgid(self.label_msgid, f"de la cifra «{self.key}»")
        _check_bool(self.allow_zero, "allow_zero", self.key)
        _check_bool(self.allow_negative, "allow_negative", self.key)

    @property
    def module(self) -> str:
        """El código del módulo dueño: ``res`` de ``res.sellable_t``."""
        return self.key.partition(".")[0]


@dataclass(frozen=True, slots=True)
class ImporterDef:
    """Cómo reimportar las entradas de un lector de contenido (RF-008-11; ADR-0025 §2):
    ``reader_id``, el del lector sin versión (``core.gpkg_layer``: reimporta las entradas de
    cualquiera de sus versiones), y ``reimport``, la función que vuelve a importar una entrada
    con sus ajustes registrados."""

    reader_id: str
    reimport: ReimportFunction

    def __post_init__(self) -> None:
        if not isinstance(self.reader_id, str) or _READER_ID.fullmatch(self.reader_id) is None:
            raise ValueError(
                f"el lector del importador {self.reader_id!r} no es <módulo>.<nombre> en "
                "minúsculas y sin versión, como «core.gpkg_layer»"
            )
        if not callable(self.reimport):
            raise TypeError(
                f"«reimport» del importador «{self.reader_id}» es una función, no "
                f"{type(self.reimport).__name__}"
            )

    @property
    def module(self) -> str:
        """El código del módulo dueño del lector."""
        return self.reader_id.partition(".")[0]


@dataclass(frozen=True, slots=True)
class ReimportRequest:
    """Lo que recibe ``ImporterDef.reimport`` (RF-008-11; plan §5.4.8, «Actualizar»): el
    proyecto, la entrada activa que se reimporta (``input_uid``), el motivo de la sustitución
    (obligatorio: lo comprueba ``reimport_input``) y, con su nombre, los ajustes que pidió el
    importador (``settings``: solo los que cambian; ``None``, los registrados) y la entrega
    nueva (``received_at``, ``received_from``; ``None``: sin entrega)."""

    project: Any
    input_uid: str
    reason: str
    _: KW_ONLY
    settings: Mapping[str, Any] | None = None
    received_at: Any = None
    received_from: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.input_uid, str) or not isinstance(self.reason, str):
            raise TypeError(f"una reimportación indica la entrada (uid) y el motivo en texto, no "
                            f"{self.input_uid!r} y {self.reason!r}")
        if self.settings is not None:
            if not isinstance(self.settings, Mapping):
                raise TypeError(f"los ajustes de una reimportación son un diccionario (o "
                                f"None), no {self.settings!r}")
            object.__setattr__(self, "settings", MappingProxyType(dict(self.settings)))


class SettingsNeeded(ProvenanceError):
    """El importador no puede reimportar con los ajustes registrados (una capa o una columna
    que ya no está en la fuente) y los pide (RF-008-11; spec §8, «Actualizar con una columna
    que el cliente renombró»): un :class:`~.messages.ProvenanceError` con el texto para la
    persona y, para el diálogo que los pide, ``needed`` (los ajustes que hay que volver a
    indicar, por su clave) y ``choices`` (los valores posibles de cada uno, si se conocen)."""

    def __init__(self, code: str, /, *, needed: Iterable[str],
                 choices: Mapping[str, Iterable[str]] | None = None, **values: object) -> None:
        super().__init__(code, **values)
        self.needed: tuple[str, ...] = tuple(needed)
        self.choices: Mapping[str, tuple[str, ...]] = MappingProxyType(
            {key: tuple(items) for key, items in (choices or {}).items()})


# --- Registros --------------------------------------------------------------------------------

_LOCK = threading.Lock()
_OPERATIONS: dict[str, OperationDef] = {}
_GROUPS: dict[str, CoupledGroupDef] = {}
_FIGURES: dict[str, FigureDef] = {}
_IMPORTERS: dict[str, ImporterDef] = {}

OPERATIONS: Mapping[str, OperationDef] = MappingProxyType(_OPERATIONS)
"""Los tipos de operación registrados, por tipo (vista de solo lectura, siempre al día)."""
GROUPS: Mapping[str, CoupledGroupDef] = MappingProxyType(_GROUPS)
"""Los grupos de operaciones acopladas registrados, por nombre."""
FIGURES: Mapping[str, FigureDef] = MappingProxyType(_FIGURES)
"""Las cifras registradas, por clave."""
IMPORTERS: Mapping[str, ImporterDef] = MappingProxyType(_IMPORTERS)
"""Los importadores registrados, por lector (sin versión)."""


def _listed(names: Iterable[str]) -> str:
    return ", ".join(f"«{name}»" for name in names)


def _require(declaration: object, kind: type, what: str) -> None:
    if not isinstance(declaration, kind):
        raise TypeError(
            f"{what} solo registra un {kind.__name__}, no {type(declaration).__name__} "
            f"({declaration!r})"
        )


def _require_text(value: object, what: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{what} es un texto, no {value!r}")


def _duplicate(what: str, name: str, unregister: str) -> ValueError:
    return ValueError(
        f"{what} ya registrado: «{name}». Se registra una sola vez ({unregister} antes de "
        "volver a registrarlo)"
    )


def register_operation(defn: OperationDef) -> None:
    """Registra un tipo de operación (lo llama ``bl/`` en el ``register()`` de su módulo).
    :class:`ValueError` si el tipo ya está registrado (el registrado se queda; un cambio del
    algoritmo es otra versión, no otro registro) o si declara un grupo que ya está registrado
    sin él; :class:`TypeError` si no es un :class:`OperationDef`."""
    _require(defn, OperationDef, "register_operation")
    with _LOCK:
        if defn.op_type in _OPERATIONS:
            raise _duplicate("tipo de operación", defn.op_type, "unregister_operation")
        if defn.group is not None and defn.group in _GROUPS:
            raise ValueError(
                f"la operación «{defn.op_type}» declara el grupo «{defn.group}», que ya está "
                "registrado sin ella: registre los tipos de un grupo antes que el grupo"
            )
        _OPERATIONS[defn.op_type] = defn


def unregister_operation(op_type: str) -> int:
    """Quita el tipo ``op_type`` (en ``unregister()``) y dice cuántos quitó (0 o 1); quitar
    uno que no está no hace nada. :class:`ValueError` si es de un grupo registrado: el grupo
    se quita antes (``unregister_group``)."""
    _require_text(op_type, "el tipo de una operación")
    with _LOCK:
        if op_type not in _OPERATIONS:
            return 0
        holders = [group.name for group in _GROUPS.values() if op_type in group.op_types]
        if holders:
            raise ValueError(
                f"la operación «{op_type}» es del grupo registrado {_listed(holders)}: quite "
                "antes el grupo (unregister_group)"
            )
        del _OPERATIONS[op_type]
    return 1


def register_group(group: CoupledGroupDef) -> None:
    """Registra un grupo de operaciones acopladas (RF-008-25), después de sus tipos.
    :class:`ValueError` si ya está registrado, si tiene tipos sin registrar, si uno de sus
    tipos no lo declara o lo declara uno que no está en él, o si sus tipos no son todos
    igual de repetibles y del mismo ámbito (se recalcularía uno sin los demás)."""
    _require(group, CoupledGroupDef, "register_group")
    name = group.name
    with _LOCK:
        if name in _GROUPS:
            raise _duplicate("grupo de operaciones acopladas", name, "unregister_group")
        missing = [op_type for op_type in group.op_types if op_type not in _OPERATIONS]
        if missing:
            raise ValueError(
                f"el grupo «{name}» tiene tipos sin registrar: {_listed(missing)}. Registre "
                "antes sus operaciones"
            )
        members = [_OPERATIONS[op_type] for op_type in group.op_types]
        undeclared = [defn.op_type for defn in members if defn.group != name]
        if undeclared:
            raise ValueError(
                f"{_listed(undeclared)} no declaran el grupo «{name}» (OperationDef.group)"
            )
        outsiders = sorted(op_type for op_type, defn in _OPERATIONS.items()
                           if defn.group == name and op_type not in group.op_types)
        if outsiders:
            raise ValueError(
                f"{_listed(outsiders)} declaran el grupo «{name}» y no están en él"
            )
        if len({defn.repeatable for defn in members}) > 1:
            raise ValueError(
                f"las operaciones del grupo «{name}» no son todas repetibles ni todas no "
                "repetibles: se recalcularía una sin las demás (RF-008-25)"
            )
        if len({defn.scope for defn in members}) > 1:
            raise ValueError(f"las operaciones del grupo «{name}» no son del mismo ámbito")
        _GROUPS[name] = group


def unregister_group(name: str) -> int:
    """Quita el grupo ``name`` y dice cuántos quitó (0 o 1); quitar uno que no está no hace
    nada."""
    _require_text(name, "el nombre de un grupo")
    with _LOCK:
        return 0 if _GROUPS.pop(name, None) is None else 1


def register_figure(defn: FigureDef) -> None:
    """Registra una cifra. :class:`ValueError` si su clave ya está registrada (la registrada
    se queda); :class:`TypeError` si no es un :class:`FigureDef`."""
    _require(defn, FigureDef, "register_figure")
    with _LOCK:
        if defn.key in _FIGURES:
            raise _duplicate("cifra", defn.key, "unregister_figure")
        _FIGURES[defn.key] = defn


def unregister_figure(key: str) -> int:
    """Quita la cifra ``key`` y dice cuántas quitó (0 o 1)."""
    _require_text(key, "la clave de una cifra")
    with _LOCK:
        return 0 if _FIGURES.pop(key, None) is None else 1


def register_importer(defn: ImporterDef) -> None:
    """Registra el importador de un lector. :class:`ValueError` si ese lector ya tiene uno
    (el registrado se queda); :class:`TypeError` si no es un :class:`ImporterDef`."""
    _require(defn, ImporterDef, "register_importer")
    with _LOCK:
        if defn.reader_id in _IMPORTERS:
            raise _duplicate("importador del lector", defn.reader_id, "unregister_importer")
        _IMPORTERS[defn.reader_id] = defn


def unregister_importer(reader_id: str) -> int:
    """Quita el importador del lector ``reader_id`` y dice cuántos quitó (0 o 1)."""
    _require_text(reader_id, "el lector de un importador")
    with _LOCK:
        return 0 if _IMPORTERS.pop(reader_id, None) is None else 1


# --- Búsquedas --------------------------------------------------------------------------------


def operation_def(op_type: str) -> OperationDef:
    """El tipo de operación registrado; si no está, :class:`~.messages.ProvenanceError`
    ``core.operation_unregistered`` (el módulo que lo declara no está activo o es de otra
    versión de Geoblender: sus operaciones constan, pero no se recalculan)."""
    _require_text(op_type, "el tipo de una operación")
    found = _OPERATIONS.get(op_type)
    if found is None:
        raise ProvenanceError("core.operation_unregistered", op_type=op_type)
    return found


def group_def(name: str) -> CoupledGroupDef:
    """El grupo registrado; si no, ``core.group_unregistered``."""
    _require_text(name, "el nombre de un grupo")
    found = _GROUPS.get(name)
    if found is None:
        raise ProvenanceError("core.group_unregistered", group=name)
    return found


def figure_def(key: str) -> FigureDef:
    """La cifra registrada; si no, ``core.figure_unregistered``."""
    _require_text(key, "la clave de una cifra")
    found = _FIGURES.get(key)
    if found is None:
        raise ProvenanceError("core.figure_unregistered", key=key)
    return found


def importer_def(reader_id: str) -> ImporterDef:
    """El importador del lector (sin versión); si no, ``core.importer_unregistered``."""
    _require_text(reader_id, "el lector de un importador")
    found = _IMPORTERS.get(reader_id)
    if found is None:
        raise ProvenanceError("core.importer_unregistered", reader=reader_id)
    return found


# --- Operaciones de core ----------------------------------------------------------------------

EXTERNAL_EDIT = "core.external_edit"
"""Edición hecha fuera de Geoblender en un dato no inmutable (RF-008-21; D9): consume la
versión anterior del dato y produce la nueva, con ejecutor ``external``."""
EXTERNAL_EDIT_VERSION = "core.external_edit_version"
"""Lo mismo que :data:`EXTERNAL_EDIT`, de un dato **de una versión** (spec 015, T20; RF-008-21, RF-008-56,
RF-012-29, RF-015-11): una operación **de la versión del dato** y de su revisión abierta, que es el único ámbito
en que puede consumir y producir un dato de esa versión (una de proyecto no puede: ``core.version_data_in_project``,
D-14 de la 009). La registra ``core.datasets.external`` en lugar de la de proyecto cuando el dato es de una
versión."""
ACCEPT_REVIEW = "core.accept_review"
"""«Dar por buena» una operación que espera revisión a mano (RF-008-27; D8): consume las
versiones vigentes, «produce» las mismas salidas y sustituye a la revisada."""
IMPORT_LAYER = "core.import_layer"
"""Registrar una capa de un GeoPackage como entrada (RF-008-62; D14), con lo importado en
``core_imported_<slug>`` (``core.provenance.importer``)."""

CORE_OPERATIONS: tuple[OperationDef, ...] = (
    OperationDef(EXTERNAL_EDIT, "1.0", "core", EXTERNAL_EDIT_MSGID, False),
    OperationDef(EXTERNAL_EDIT_VERSION, "1.0", "core", EXTERNAL_EDIT_MSGID, False, scope="version"),
    OperationDef(ACCEPT_REVIEW, "1.0", "core", ACCEPT_REVIEW_MSGID, False,
                 commands=("geoblender.core_accept_review",)),
    OperationDef(IMPORT_LAYER, "1.0", "core", IMPORT_LAYER_MSGID, False,
                 commands=("geoblender.core_resolve_unregistered",)),
)
"""Los tipos de operación de ``core`` (los registra ``bl/ops/core_provenance.py``): ninguno se
repite solo ni tiene recálculo."""
