# SPDX-License-Identifier: GPL-3.0-or-later
"""Las entidades de diseño (spec 015, T02; HU-015-1; RF-015-01; plan 015 §5.1 y §5.3.1; ADR-0030).

Una entidad es una operación de versión con su nombre y un **código inmutable por versión**
(``PLT-001``) cuyos parámetros son la familia ``des.platform.{e}.*`` (:mod:`design.params`):
sin fila no hay entidad; con fila y sin operación, está «sin calcular». Su estado se **deduce** del
grafo (ADR-0025 §5), no se apunta. Python puro, sin leer el proyecto (la lectura es de la T03).

- :class:`EntityKind`: el tipo (la plataforma de la 015 y, de la 016, el acopio, la retirada, el contrafuerte y el
  cuerpo apoyado, T03: del programa, registrados al importar) y su prefijo de código. **El registro por tipo** (spec 016, T02; plan 016 §5.1, P-1, P-3 y P-11; H-2 y H-9;
  ADR-0031 §1): lo que el dominio sabe de cada tipo —su prefijo de código, la familia de sus parámetros, el tipo
  de su operación, los papeles de su superficie y su tabla, el mensaje de su motivo y el de «apoyo retirado» y si
  encadena— es un :class:`EntityType`, registrado con :func:`register_entity_type`; la plataforma es el único del
  programa y los demás los registra quien los declara (:func:`registered_types`, :func:`entity_type`,
  :func:`kind_of_code`). Un tipo **sin** ``start`` es un tipo **sin cadena**: ``chain_tails`` lo deja fuera, no
  encadena y **nadie puede partir de su superficie** (``des.chainless_start``).
- :class:`EntityState`: el estado de una entidad (RF-015-25): sin calcular, al día, obsoleta,
  descartada o «apoyo retirado».
- :class:`EntityRecord`: lo que el dominio sabe de una entidad: su código, su nombre, su tipo, su
  superficie de partida y la de apoyo (si la hay) y su estado.
- :func:`format_code` y :func:`next_code`: el código ``PLT-nnn``, correlativo y nunca reutilizado.
- :func:`declared_reason`: el motivo generado de la restricción que declara una entidad
  (RF-015-10: «declarada por la plataforma P1»).

**La cadena** (T03; RF-015-04, RF-015-05; D-2; ADR-0030 §2). Las entidades se aplican en cadenas
lineales por su superficie de partida: de cada superficie parte como mucho una. La partida
(:attr:`EntityRecord.start`) es el **nombre de una superficie** —el terreno o una de diseño, como las
nombran la 013 y la 014— o ``entity:<código>`` (:func:`surface_ref`), la superficie que deja otra
entidad; la que parte de una superficie de verdad abre una cadena y la que ninguna otra tiene como
partida es su cola, la superficie de diseño de la cadena para congelar (RF-012-25). Python puro,
sobre una lista de :class:`EntityRecord`: :func:`start_conflict` (RF-015-04: ya parte una entidad
de esa superficie), :func:`successor_of`, :func:`predecessor_of`, :func:`chain_of` (hacia delante),
:func:`chain_tails` y :func:`check_chain` (ciclos y dos entidades desde la misma superficie, que se
rechazan: ``des.entity_chain_cycle`` y ``des.entity_start_taken``) y, para «Insertar antes o
después de…» (RF-015-05), :func:`insertion_start`, :func:`insert_after` e :func:`insert_before`,
que dan el cambio de partida de la sucesora (:class:`ParamChange`, con su motivo) sin escribir
nada, e :func:`insertion_point` (T31: lo que pide el diálogo de «Insertar antes o después de…»: la partida de la
nueva y la sucesora, :class:`Insertion`). **Una entidad descartada es un registro**: no ocupa su superficie ni está en ninguna cadena
(salvo la que se pregunta por ella), y lo que parte de la suya queda al principio de su propia
cadena («apoyo retirado», RF-015-17).

**El registro de una versión** (:func:`registry`; RF-015-01, RF-015-25): lee del proyecto, sin
escribir, los códigos con parámetros ``des.platform.{e}.*`` de la versión (el nombre, la partida y
el apoyo; sin fila no hay entidad), la operación vigente de cada una (la última hecha y sin
sustituir de su tipo que leyó sus parámetros) y su estado **deducido** del grafo (ADR-0025 §5): sin
calcular, al día, obsoleta (con sus causas, de la caché ``gb_stale``), descartada (todos los datos
que escribió están descartados) o «apoyo retirado» (consumió, como ``surface`` o ``supported_on``,
un dato descartado).

**Los dos ámbitos** (spec 016, T04; D-15, H-3; ADR-0031 §2): la detección de acopios es **del proyecto** si su superficie lo
es y de la versión si no, con dos tipos de operación (``EntityType.op_type`` y ``project_op_type``) y los parámetros de
su familia en el ámbito de la operación. :func:`registry` sigue siendo el de **una versión** (sus parámetros propios) y
:func:`project_registry`, el del **proyecto** (los parámetros del proyecto de los tipos que tienen una operación de
proyecto): el código ``<PREFIJO>-nnn`` es correlativo **por ámbito** (``STK-001`` en el proyecto y en cada versión) y cada
:class:`EntityRecord` dice de cuál es (``scope``). Una operación de versión deja en el proyecto filas «sin confirmar» de las
claves que lee (``docs/trampas.md`` §6): en el registro del proyecto **no son una entidad** —sin nombre, no hay entidad—.

**La zona que declara una entidad** (T16; RF-012-29, RF-015-10; A8; D-23): :func:`declared_zone` (de
una máscara) y :func:`declared_zone_of_runs` (de los tramos de fila de ``des_epr_``) dan el
:class:`DeclaredZone` de una huella: **un polígono por componente 4-conexa**, con sus huecos, válido
para las comprobaciones de la 012, con las coordenadas exactas de la rejilla y de modo que la regla de
la celda de la 012 (RF-012-12) devuelva exactamente esas celdas con resguardo 0 (D-23).

**La lista de dependencias y la causa** (T24; RF-015-15, RF-015-16; RNF-015-02): :func:`dependents` («lo que se
apoya en E») y :func:`dependencies_of` («en qué se apoya E») son **una consulta de entradas y cifras** del grafo de la
008 —los papeles ``supported_on`` y ``surface`` sobre el dato ``des_psf_`` de la entidad, y la cifra
``des.supported_m3`` con su ámbito— y dan **una sola lista** de :class:`Dependent` (nombre, tipo, volumen apoyado en
m³ y estado) de entidades y de diseños de la 013 y la 014, sin leer ninguna superficie. :func:`stale_reason` y
:func:`operation_reason` dan el motivo legible de lo obsoleto: el «Obsoleto: cambió …» de la 008, con la **entidad**
que cambió por su nombre y lo que cambió. La cascada, el orden de recalcular y lo congelado son los de la 008
(RF-008-24, RF-008-26, RF-009-19): aquí no se apunta nada.

**Los acopios apoyables** (spec 016, T15; RF-016-14, RF-015-15 y 17; plan 016 §5.2.3 «Dependencias» y §5.4 A13; P-1; ADR-0031 §4): una
detección de acopios es **una** entidad (``STK-001``) y cada acopio, una fila de su tabla identificada por la clave de su marca, así
que lo que una operación apoya se mide **por acopio**: :func:`detect_supports` y :func:`strongest` trabajan con la **referencia** de
aquello en lo que se apoya (``PLT-001``, o ``STK-001#m07``: :func:`~.provenance.support_ref`), un :class:`Support` por acopio con su
clave (``Support.stockpile``) sobre la superficie con que se detectó (``des_stp_``, la misma para todos) y la huella de su fila; la
cifra ``des.supported_m3`` lleva la clave del acopio en su ámbito; y :func:`dependents` y :func:`dependencies_of` dan «lo que se apoya
en un acopio» (``dependents(…, stockpile=clave)``) y «en qué acopio se apoya» como las mismas consultas de entradas y cifras. Solo las
detecciones **de la versión** se apoyan (las del proyecto no están en su registro: ``STK-001`` de la versión y del proyecto son dos
entidades). «Apoyo retirado» por una retirada viva (P-9) es de la T18.

**Descartada y «apoyo retirado»** (T25; RF-015-17, RF-009-12; D-12): una entidad está **descartada** si todos los datos
que escribió lo están, o, si no está calculada (no tiene datos que descartar), si su parámetro de versión
``des.platform.{e}.discarded`` es verdadero. :func:`retired_supports` es la lista de lo que perdió su apoyo —las
operaciones vigentes de la versión que consumieron, como ``surface`` o ``supported_on``, el dato de una entidad
descartada— y :func:`stale_reason` y :func:`operation_reason` dan de ello la causa («Apoyo retirado: se descartó la
plataforma P1»), no el «Obsoleto» de la 008.

``design.entities`` es un módulo pesado de la 015: lo importan el almacén y las órdenes al usarlo, no
``bl`` al registrarse ni ``design.provenance`` (``tests/unit/architecture/test_lazy_registration.py``).
"""

from __future__ import annotations

import hashlib
import json
import math
import numbers
import re
import sqlite3
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import numpy as np

from ..core.datasets.model import DatasetStatus
from ..core.i18n import LANGUAGES, translate
from ..core.params import PROJECT_SCOPE, VERSION_SCOPE, ParameterStore, parameter_label
from ..core.provenance.graph import DATASET, Cause, CauseKind
from ..core.provenance.stale import OPERATION as STALE_OPERATION
from ..core.provenance.stale import item_causes, item_text
from ..core.versions import read as versions_read
from ..core.versions.model import Version, VersionError
from .grids import label_components
from .messages import DesignError, render
from .params import (
    EntityParams,
    PlatformParam,
    entity_key,
    entity_params,
    entity_params_of,
    entity_segment,
    register_entity_params,
    segment_code,
    unregister_entity_params,
)
from .provenance import (
    BODY,
    BUTTRESS,
    ENTITY_ROLE,
    ENTITY_SCOPE_KEY,
    ENTITY_SURFACE_ROLE,
    OPERATION_TYPES_BY_NAME,
    PLATFORM,
    STOCKPILE_DETECT,
    STOCKPILE_DETECT_PROJECT,
    STOCKPILE_REMOVAL,
    STOCKPILE_SCOPE_KEY,
    STOCKPILE_SURFACE_ROLE,
    STOCKPILES_ROLE,
    SUPPORTED_M3,
    SUPPORTED_ON_ROLE,
    SUPPORT_REF_SEPARATOR,
    SURFACE_ROLE,
    split_support_ref,
    support_ref,
)

if TYPE_CHECKING:
    from ..gis.grid import Grid

__all__ = [
    "ENTITY_PREFIX",
    "DeclaredZone",
    "Dependent",
    "EntityEntry",
    "EntityKind",
    "EntityRecord",
    "EntityRegistry",
    "EntityState",
    "EntityType",
    "Insertion",
    "ParamChange",
    "RetiredEntity",
    "RetiredSupport",
    "Support",
    "chain_of",
    "chain_tail_surfaces",
    "chain_tails",
    "check_chain",
    "code_order",
    "declared_reason",
    "declared_zone",
    "declared_zone_of_runs",
    "dependencies_of",
    "dependents",
    "detect_supports",
    "entity_type",
    "find_entity",
    "format_code",
    "insert_after",
    "insert_before",
    "insertion_point",
    "insertion_start",
    "kind_label",
    "kind_of_code",
    "next_code",
    "operation_reason",
    "predecessor_of",
    "project_registry",
    "ref_code",
    "register_entity_type",
    "registered_types",
    "registry",
    "retired_supports",
    "runs_cells",
    "stale_reason",
    "start_conflict",
    "strongest",
    "successor_of",
    "surface_ref",
    "unregister_entity_type",
    "unsupportable",
]


class EntityKind(StrEnum):
    """El tipo de una entidad (RF-015-01): la plataforma (015) y, de la 016 (T03), el acopio (``stockpile``: la
    detección, ``STK``, **sin cadena**), la retirada de un acopio (``removal``, ``RMV``), el contrafuerte
    (``buttress``, ``BTR``) y el cuerpo apoyado (``body``, ``BDY``). El valor es el que va en la clave de sus
    parámetros (``des.platform.{e}.*``); :attr:`prefix`, el principio de su código (``PLT``).

    Lo que se sabe de cada tipo lo dice su :class:`EntityType` (:func:`entity_type`). Un tipo **registrado**
    (:func:`register_entity_type`) que no es de la enumeración —el de una prueba (spec 016, T02)— también se lee
    como ``EntityKind`` (``EntityKind("probe")``, siempre el mismo objeto, igual a su valor) mientras esté
    registrado; la enumeración (``for kind in EntityKind``) es solo la de los tipos del programa."""

    PLATFORM = "platform"
    STOCKPILE = "stockpile"
    REMOVAL = "removal"
    BUTTRESS = "buttress"
    BODY = "body"

    @classmethod
    def _missing_(cls, value: object) -> EntityKind | None:
        """Un tipo registrado que no es de la enumeración: su miembro (el mismo cada vez; se quita con el
        tipo); ``None`` (el :class:`ValueError` de siempre) si no está registrado."""
        if not isinstance(value, str) or value not in _TYPES:
            return None
        member = str.__new__(cls, value)
        member._name_ = value.upper()
        member._value_ = value
        return cls._value2member_map_.setdefault(value, member)  # type: ignore[no-any-return]

    @property
    def prefix(self) -> str:
        """El principio del código de una entidad de este tipo: ``PLT`` de ``PLT-001``."""
        return entity_type(self).prefix

    @property
    def chained(self) -> bool:
        """Si las entidades de este tipo encadenan (tienen ``start``) o son de un tipo sin cadena."""
        return entity_type(self).chained


_CODE = re.compile(r"(?P<prefix>[A-Z]{2,5})-(?P<number>[0-9]{3,})")


@dataclass(frozen=True, slots=True)
class EntityType:
    """Lo que el dominio sabe de un **tipo de entidad** (spec 016, T02; plan 016 §5.1): sus parámetros
    (``params``: el ``kind``, el prefijo de su código y los valores de su familia ``des.<kind>.{e}.*``;
    :class:`~design.params.EntityParams`), el tipo de su operación de versión (``op_type``: ``des.platform``), los
    mensajes de su motivo declarado (``reason``) y de «se descartó la plataforma P1» (``removed``: la causa de «apoyo
    retirado») y los papeles con que su operación escribe la superficie y la tabla en las que se apoya otra
    (``surface_role`` y ``table_role``; sin ellos, el tipo no deja una superficie en la que apoyarse).

    Un tipo cuya familia no tiene ``start`` es un tipo **sin cadena** (:attr:`chained`). Un tipo **del proyecto o de la
    versión según su superficie** (la detección de acopios, D-15; spec 016, T04) tiene dos tipos de operación con el
    mismo algoritmo: ``op_type``, el de versión, y ``project_op_type``, el de proyecto (:attr:`op_types`)."""

    params: EntityParams
    op_type: str
    reason: str
    removed: str
    surface_role: str | None = None
    table_role: str | None = None
    project_op_type: str | None = None

    @property
    def kind(self) -> str:
        """El tipo: el segmento ``des.<kind>.{e}.*`` de la clave de sus parámetros."""
        return self.params.kind

    @property
    def prefix(self) -> str:
        """El principio de su código: ``PLT`` de ``PLT-001``."""
        return self.params.code_prefix

    @property
    def key_prefix(self) -> str:
        """El principio de la clave de sus parámetros, sin el código: ``des.platform``."""
        return self.params.key_prefix

    @property
    def chained(self) -> bool:
        """Si encadena: tiene ``start``. Sin él, es un tipo sin cadena."""
        return self.params.chained

    @property
    def op_types(self) -> tuple[str, ...]:
        """Sus tipos de operación: el de versión y, si el tipo también se crea en el proyecto, el de proyecto."""
        return (self.op_type,) if self.project_op_type is None else (self.op_type, self.project_op_type)


_TYPES: dict[str, EntityType] = {}
_PERMANENT_TYPES: set[str] = set()


def register_entity_type(spec: EntityType) -> None:
    """Registra un tipo de entidad (spec 016, T02): el suyo y sus parámetros (:func:`~design.params.
    register_entity_params`), para que el registro de las versiones, el código ``<PREFIJO>-nnn`` y la clave de sus
    valores lo conozcan. Lo hace quien declara el tipo (la 016, al registrar sus operaciones) y, en las pruebas, la
    prueba que lo usa, que lo quita al acabar (:func:`unregister_entity_type`). :class:`TypeError` si no es un
    :class:`EntityType`; :class:`ValueError` si el tipo o su prefijo ya están registrados: no deja nada a medias."""
    if not isinstance(spec, EntityType):
        raise TypeError(f"se registra un EntityType, no {type(spec).__name__} ({spec!r})")
    if spec.kind in _TYPES:
        raise ValueError(f"el tipo de entidad «{spec.kind}» ya está registrado")
    register_entity_params(spec.params)
    _TYPES[spec.kind] = spec


def unregister_entity_type(kind: str) -> None:
    """Quita el tipo de entidad ``kind`` y sus parámetros. :class:`ValueError` si es del programa (la plataforma) o
    no está registrado."""
    if kind in _PERMANENT_TYPES:
        raise ValueError(f"el tipo de entidad «{kind}» es del programa: no se quita")
    if not isinstance(kind, str) or kind not in _TYPES:
        raise ValueError(f"el tipo de entidad {kind!r} no está registrado")
    unregister_entity_params(kind)
    del _TYPES[kind]
    if kind not in {member.value for member in EntityKind}:  # un miembro de la enumeración se queda
        EntityKind._value2member_map_.pop(kind, None)


def registered_types() -> tuple[EntityType, ...]:
    """Los tipos de entidad registrados, en el orden en que se registraron (la plataforma, primero): el orden en
    que el registro de una versión recorre sus familias."""
    return tuple(_TYPES.values())


def entity_type(kind: EntityKind | str) -> EntityType:
    """El :class:`EntityType` de ``kind`` (un :class:`EntityKind` o su valor). :class:`ValueError` si no está
    registrado: un error del programa."""
    found = _TYPES.get(kind) if isinstance(kind, str) else None
    if found is None:
        raise ValueError(f"el tipo de entidad {kind!r} no está registrado")
    return found


def kind_of_code(code: str) -> EntityKind:
    """El tipo de la entidad de código ``code``: el que tiene el prefijo de su código (``PLT-001`` → plataforma).
    :class:`TypeError` si no es un texto; :class:`ValueError` si no es un código de entidad o ningún tipo registrado
    tiene su prefijo."""
    return EntityKind(entity_params_of(code).kind)


# Los tipos del programa: la plataforma (015) y los cuatro de la 016 (T03); sus parámetros los registra
# ``design.params`` al importarse.
_TYPES["platform"] = EntityType(
    entity_params("platform"), PLATFORM, "des.platform_declared_reason", "des.support_removed_platform",
    ENTITY_SURFACE_ROLE, ENTITY_ROLE)
_TYPES["stockpile"] = EntityType(
    entity_params("stockpile"), STOCKPILE_DETECT, "des.stockpile_declared_reason", "des.stockpile_support_removed",
    STOCKPILE_SURFACE_ROLE, STOCKPILES_ROLE, STOCKPILE_DETECT_PROJECT)
_TYPES["removal"] = EntityType(
    entity_params("removal"), STOCKPILE_REMOVAL, "des.removal_declared_reason", "des.removal_support_removed",
    ENTITY_SURFACE_ROLE, ENTITY_ROLE)
_TYPES["buttress"] = EntityType(
    entity_params("buttress"), BUTTRESS, "des.buttress_declared_reason", "des.buttress_support_removed",
    ENTITY_SURFACE_ROLE, ENTITY_ROLE)
_TYPES["body"] = EntityType(
    entity_params("body"), BODY, "des.body_declared_reason", "des.body_support_removed",
    ENTITY_SURFACE_ROLE, ENTITY_ROLE)
_PERMANENT_TYPES.update(("platform", "stockpile", "removal", "buttress", "body"))


class EntityState(StrEnum):
    """El estado de una entidad (RF-015-25; plan 015 §5.2.3), deducido y no apuntado (ADR-0025 §5):
    ``UNCALCULATED`` (sus parámetros sin operación vigente: lo que deja «Traer las entidades de…»),
    ``CURRENT`` (al día), ``STALE`` (obsoleta: el grafo, con su causa), ``DISCARDED`` (sus datos
    descartados, «registro, no usar»: nada se borra, RF-009-12) y ``SUPPORT_REMOVED`` («apoyo
    retirado»: una entrada suya está descartada, RF-015-17)."""

    UNCALCULATED = "uncalculated"
    CURRENT = "current"
    STALE = "stale"
    DISCARDED = "discarded"
    SUPPORT_REMOVED = "support_removed"


def format_code(kind: EntityKind | str, number: int) -> str:
    """El código de la entidad número ``number`` de su tipo: ``PLT-001``, con al menos tres cifras
    (``PLT-1000`` pasa de 999). :class:`TypeError` si ``number`` no es un entero y
    :class:`ValueError` si es menor que 1 o ``kind`` no es un tipo (errores del programa)."""
    prefix = EntityKind(kind).prefix
    if isinstance(number, bool) or not isinstance(number, int):
        raise TypeError(f"el número de una entidad es un entero, no {number!r}")
    if number < 1:
        raise ValueError(f"el número de una entidad es 1 o más, no {number}")
    return f"{prefix}-{number:03d}"


def next_code(kind: EntityKind | str, existing: Iterable[str]) -> str:
    """El código que corresponde a la siguiente entidad de tipo ``kind`` en una versión cuyas
    entidades tienen ya los códigos ``existing`` (todas, también las descartadas, que siguen en la
    versión): el mayor número de ese tipo más uno (``PLT-001`` si no hay ninguno). Es correlativo
    por versión y **nunca reutiliza** uno (el código es inmutable, ADR-0030: lo citan las
    restricciones declaradas, las dependencias y el informe); si falta alguno por el camino, el
    hueco se queda. Los códigos de otro tipo cuentan aparte (cada tipo, su prefijo y su cuenta).

    No lee el proyecto: ``existing`` son los códigos que le da el registro de la versión (T03).
    :class:`TypeError` si uno no es un texto y :class:`ValueError` si uno no es un código de
    entidad (``PLT-001``): errores del programa."""
    prefix = EntityKind(kind).prefix
    highest = 0
    for code in existing:
        if not isinstance(code, str):
            raise TypeError(f"el código de una entidad es un texto, no {code!r}")
        found = _CODE.fullmatch(code)
        if found is None:
            raise ValueError(f"el código {code!r} no es de una entidad (PLT-001: letras "
                             "mayúsculas, un guion y al menos tres cifras)")
        if found["prefix"] == prefix:
            highest = max(highest, int(found["number"]))
    return format_code(kind, highest + 1)


def _text_or_none(value: object, what: str) -> str | None:
    """``value`` sin los espacios de los extremos (``None`` si es ``None`` o está en blanco);
    :class:`TypeError` si no es un texto."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{what} es un texto, no {value!r}")
    return value.strip() or None


@dataclass(frozen=True, slots=True)
class EntityRecord:
    """Lo que el dominio sabe de una entidad de una versión (RF-015-01, RF-015-04): su ``code``
    inmutable (``PLT-001``, el de su ``kind``), su ``name`` (único en la versión), su tipo, la
    superficie de la que parte (``start``) y la de apoyo (``support``), si la hay, ambas sin valor
    hasta que se eligen, y su ``state``, deducido del grafo («sin calcular» por defecto).

    Una entidad sin nombre se rechaza (``DesignError`` ``des.entity_name_missing``); un código que
    no es de su tipo, o una partida en una entidad de un tipo sin cadena (que no tiene ``start``), es un
    error del programa (:class:`ValueError`).

    ``scope`` (spec 016, T04; D-15): el ámbito de la entidad, el del tipo de la operación que la crea: ``version`` (la
    de siempre) o ``project`` (la detección de acopios sobre una superficie del proyecto). El código es correlativo y
    único **por ámbito**."""

    code: str
    name: str
    kind: EntityKind | str
    start: str | None = None
    support: str | None = None
    state: EntityState | str = EntityState.UNCALCULATED
    scope: str = VERSION_SCOPE

    def __post_init__(self) -> None:
        if self.scope not in (PROJECT_SCOPE, VERSION_SCOPE):
            raise ValueError(f"el ámbito de una entidad es {PROJECT_SCOPE} o {VERSION_SCOPE}, no {self.scope!r}")
        kind = EntityKind(self.kind)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "state", EntityState(self.state))
        if not isinstance(self.code, str):
            raise TypeError(f"el código de una entidad es un texto, no {self.code!r}")
        found = _CODE.fullmatch(self.code)
        if found is None or found["prefix"] != kind.prefix:
            raise ValueError(f"el código {self.code!r} no es el de una entidad de tipo "
                             f"{kind.value} ({kind.prefix}-001)")
        if not isinstance(self.name, str):
            raise TypeError(f"el nombre de una entidad es un texto, no {self.name!r}")
        name = self.name.strip()
        if not name:
            raise DesignError("des.entity_name_missing", obj=f"Entidad «{self.code}»",
                              field="name", value=self.name)
        object.__setattr__(self, "name", name)
        start = _text_or_none(self.start, "la superficie de partida")
        if start is not None and not kind.chained:
            raise ValueError(f"una entidad de tipo {kind.value} no tiene partida (es de un tipo sin cadena), no "
                             f"parte de {start!r}")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "support", _text_or_none(self.support, "la superficie de apoyo"))

    @property
    def segment(self) -> str:
        """El código como segmento de la clave de sus parámetros: ``plt_001`` de ``PLT-001``."""
        return entity_segment(self.code)


def declared_reason(kind: EntityKind | str, name: str, *, language: str = "es") -> str:
    """El motivo generado de la restricción que declara la entidad de tipo ``kind`` y nombre
    ``name`` (RF-015-10; D-4): «declarada por la plataforma P1», en español o, con
    ``language="en"``, en inglés. La persona lo puede editar en la entidad (el parámetro
    ``reason``); sin edición, es éste. :class:`TypeError` si ``name`` no es un texto y
    :class:`ValueError` si está en blanco (la entidad que declara ya tiene nombre, RF-015-01) o
    ``language`` no es de Geoblender: errores del programa."""
    if not isinstance(name, str):
        raise TypeError(f"el nombre de una entidad es un texto, no {name!r}")
    shown = name.strip()
    if not shown:
        raise ValueError("una entidad sin nombre no declara nada (RF-015-01)")
    return render(entity_type(kind).reason, language=language, name=shown)


# --- La partida de una entidad y la cadena (spec 015, T03; RF-015-04, RF-015-05; D-2) -------------

ENTITY_PREFIX = "entity:"
"""El principio de la partida que es la superficie de otra entidad: ``entity:PLT-001``."""
_REF = re.compile(rf"{ENTITY_PREFIX}(?P<code>[A-Z]{{2,5}}-[0-9]{{3,}})")


def surface_ref(code: str) -> str:
    """La partida que es la superficie que deja la entidad de código ``code``:
    ``entity:PLT-001``. :class:`TypeError` si no es un texto y :class:`ValueError` si no es un
    código de entidad (``PLT-001``): errores del programa."""
    if not isinstance(code, str):
        raise TypeError(f"el código de una entidad es un texto, no {code!r}")
    if _CODE.fullmatch(code) is None:
        raise ValueError(f"el código {code!r} no es de una entidad (PLT-001: letras mayúsculas, "
                         "un guion y al menos tres cifras)")
    return f"{ENTITY_PREFIX}{code}"


def ref_code(text: str | None) -> str | None:
    """El código de la entidad cuya superficie es la partida ``text`` (``entity:PLT-001`` →
    ``PLT-001``, sin los espacios de los extremos); ``None`` si ``text`` es ``None``, está en
    blanco, es el nombre de una superficie o no es un ``entity:<código>`` bien formado.
    :class:`TypeError` si no es un texto."""
    if text is None:
        return None
    if not isinstance(text, str):
        raise TypeError(f"la partida de una entidad es un texto, no {text!r}")
    found = _REF.fullmatch(text.strip())
    return None if found is None else found["code"]


def _records(records: Iterable[EntityRecord]) -> tuple[EntityRecord, ...]:
    """Las entidades de ``records`` como tupla; :class:`TypeError` si alguna no es una
    :class:`EntityRecord`."""
    found = tuple(records)
    for item in found:
        if not isinstance(item, EntityRecord):
            raise TypeError(f"las entidades de la cadena son EntityRecord, no {item!r}")
    return found


def _live(item: EntityRecord) -> bool:
    """Si la entidad cuenta en la cadena: una descartada es un registro (RF-015-17)."""
    return item.state is not EntityState.DISCARDED


def _find(items: tuple[EntityRecord, ...], ref: str) -> EntityRecord | None:
    if not isinstance(ref, str):
        raise TypeError(f"una entidad se indica por su código o su nombre, no {ref!r}")
    wanted = ref.strip()
    for item in items:
        if item.code == wanted:
            return item
    for item in items:
        if item.name == wanted:
            return item
    return None


def _need(items: tuple[EntityRecord, ...], ref: str) -> EntityRecord:
    found = _find(items, ref)
    if found is None:
        raise ValueError(f"la versión no tiene ninguna entidad con el código o el nombre {ref!r}")
    return found


def find_entity(records: Iterable[EntityRecord], ref: str) -> EntityRecord | None:
    """La entidad de ``records`` de código o nombre ``ref`` (el código manda si un nombre se parece
    a otro código); ``None`` si no hay ninguna. :class:`TypeError` si ``ref`` no es un texto."""
    return _find(_records(records), ref)


def start_conflict(records: Iterable[EntityRecord], start: str | None, *,
                   ignoring: str | None = None) -> EntityRecord | None:
    """La entidad de ``records`` que ya parte de la superficie ``start`` (un nombre de superficie o
    ``entity:<código>``, comparado sin los espacios de los extremos), o ``None`` si está libre
    (RF-015-04: de cada superficie parte como mucho una entidad). Cuenta toda entidad viva, también
    la que está sin calcular; una descartada es un registro y no ocupa nada (RF-015-17). Sin
    partida (``None`` o en blanco), no hay conflicto. ``ignoring`` es el código de la entidad que
    se está cambiando, que no cuenta consigo misma. :class:`TypeError` si ``start`` no es un texto
    o ``records`` no son entidades. Lo rechaza ``des.entity_start_taken`` quien la llama (la
    orden, T11), con ``entity``, ``value`` y la entidad devuelta como ``other``."""
    items = _records(records)
    if start is None:
        return None
    if not isinstance(start, str):
        raise TypeError(f"la partida de una entidad es un texto, no {start!r}")
    wanted = start.strip()
    if not wanted:
        return None
    for item in items:
        if _live(item) and item.code != ignoring and item.start == wanted:
            return item
    return None


@dataclass(frozen=True, slots=True)
class _Index:
    """Las entidades de una versión para andar su cadena: las que cuentan (vivas y con partida) por
    la superficie de la que parten."""

    by_start: Mapping[str, EntityRecord]

    def following(self, item: EntityRecord) -> EntityRecord | None:
        """La entidad viva que parte de la superficie de ``item``."""
        return self.by_start.get(surface_ref(item.code))


def _index(items: tuple[EntityRecord, ...]) -> _Index:
    """El índice de ``items``; ``DesignError`` ``des.entity_start_taken`` si dos entidades vivas
    parten de la misma superficie (los datos rompen la regla de la cadena: no se elige una) y
    ``des.chainless_start`` si una viva parte de la superficie de una entidad de un tipo sin cadena, en el
    estado que esté (spec 016, T02; H-9: nadie parte de ella)."""
    by_start: dict[str, EntityRecord] = {}
    by_code = {item.code: item for item in items}
    for item in items:
        if not _live(item) or item.start is None:
            continue
        origin = by_code.get(ref_code(item.start) or "")
        if origin is not None and not EntityKind(origin.kind).chained:
            raise DesignError("des.chainless_start", obj=f"Entidad «{item.name}»",
                              field=entity_key(item.code, PlatformParam.START), value=item.start,
                              entity=item.name, other=origin.name)
        first = by_start.get(item.start)
        if first is not None:
            raise DesignError("des.entity_start_taken", obj=f"Entidad «{item.name}»",
                              field="start", value=item.start, entity=item.name, other=first.name)
        by_start[item.start] = item
    return _Index(MappingProxyType(by_start))


def _cycle(names: list[str], start: str | None) -> DesignError:
    """El rechazo de una cadena que da la vuelta: ``names`` son los nombres de la vuelta, con el
    primero repetido al final (``«P1» → «P2» → «P1»``)."""
    return DesignError("des.entity_chain_cycle", obj=f"Entidad «{names[0]}»", field="start",
                       value=start, chain=" → ".join(f"«{name}»" for name in names))


def successor_of(records: Iterable[EntityRecord], ref: str) -> EntityRecord | None:
    """La entidad que parte de la superficie que deja la de código o nombre ``ref`` (RF-015-04:
    «qué entidad parte de la suya»); ``None`` si no la sigue ninguna. :class:`ValueError` si
    ``ref`` no es de ``records``; ``des.entity_start_taken`` si los datos la dan dos veces."""
    items = _records(records)
    return _index(items).following(_need(items, ref))


def predecessor_of(records: Iterable[EntityRecord], ref: str) -> EntityRecord | None:
    """La entidad de cuya superficie parte la de código o nombre ``ref`` (RF-015-04), aunque esté
    descartada (es lo que dice «apoyo retirado»); ``None`` si parte de una superficie que no es de
    una entidad de ``records``, sea el terreno o una de diseño. :class:`ValueError` si ``ref`` no
    es de ``records``."""
    items = _records(records)
    code = ref_code(_need(items, ref).start)
    return None if code is None else _find(items, code)


def chain_of(records: Iterable[EntityRecord], ref: str) -> tuple[EntityRecord, ...]:
    """La cadena **hacia delante** desde la entidad de código o nombre ``ref`` (RF-015-04): ella y,
    una tras otra, las que parten de la superficie de la anterior. Una descartada es un registro:
    la entidad por la que se pregunta sale aunque lo esté, pero no sigue ninguna descartada.
    :class:`ValueError` si ``ref`` no es de ``records``; ``DesignError`` ``des.entity_chain_cycle``
    si da la vuelta y ``des.entity_start_taken`` si dos parten de la misma superficie."""
    items = _records(records)
    first = _need(items, ref)
    index = _index(items)
    found = [first]
    seen = {first.code}
    current = first
    while (following := index.following(current)) is not None:
        if following.code in seen:
            loop = found[found.index(following):]
            raise _cycle([item.name for item in (*loop, following)], loop[0].start)
        found.append(following)
        seen.add(following.code)
        current = following
    return tuple(found)


def chain_tails(records: Iterable[EntityRecord]) -> tuple[EntityRecord, ...]:
    """La última entidad de cada cadena de ``records`` (RF-015-04): la superficie de diseño de la
    cadena para congelar (RF-012-25); las demás son de trabajo. Una entidad viva con partida que no
    es la superficie de otra entidad viva abre una cadena (parte del terreno, de una superficie de
    diseño o de la de una descartada) y la que ninguna otra tiene como partida es su cola; salen en
    el orden en que aparece el principio de cada cadena. Sin partida o descartada, una entidad no
    está en ninguna, **salvo que otra viva parta de su superficie** (T26: lo que deja «Traer las entidades de…»
    cuando la partida de la primera era un resultado de otra versión): abre entonces la cadena, aunque aún no tenga
    superficie de la que partir. **Una entidad de un tipo sin cadena** (sin ``start``: la detección de acopios, el
    cuerpo «bajo un techo»; spec 016, T02, H-9) **no está en ninguna cadena ni es la cola de ninguna**, en el estado
    que esté: no deja una superficie de diseño que congelar, y nadie parte de la suya (:func:`_index`:
    ``des.chainless_start``). ``DesignError`` ``des.entity_chain_cycle`` si alguna da la vuelta (no tiene
    principio, y no se pierde) y ``des.entity_start_taken`` si dos parten de la misma superficie."""
    items = _records(records)
    index = _index(items)
    placed = [item for item in items if _live(item) and EntityKind(item.kind).chained
              and (item.start is not None or index.following(item) is not None)]
    live_codes = {item.code for item in items if _live(item)}
    visited: set[str] = set()
    tails: list[EntityRecord] = []
    for head in placed:
        if ref_code(head.start) in live_codes:
            continue
        current = head
        while True:
            visited.add(current.code)
            following = index.following(current)
            if following is None:
                break
            current = following
        tails.append(current)
    loose = [item for item in placed if item.code not in visited]
    if loose:  # solo quedan entidades que parten unas de otras en círculo
        loop = [loose[0]]
        while (following := index.following(loop[-1])) is not loose[0] and following is not None:
            loop.append(following)
        raise _cycle([item.name for item in (*loop, loose[0])], loose[0].start)
    return tuple(tails)


def check_chain(records: Iterable[EntityRecord]) -> None:
    """Comprueba la cadena de ``records`` (RF-015-04): sin ciclos y con como mucho una entidad viva
    desde cada superficie; si no, el mismo ``DesignError`` que :func:`chain_tails`."""
    chain_tails(records)


def unsupportable(records: Iterable[EntityRecord], own_code: str, *,
                  insert_before: str | None = None) -> frozenset[str]:
    """Los códigos de las entidades en cuya superficie la entidad ``own_code`` **no** puede apoyarse porque sería un
    ciclo del grafo (RF-015-15, RF-015-05; spec 015, T39, hallazgo A-1): ella misma y las que parten de su
    superficie, **aguas abajo de su cadena** (``chain_of``: lo que ella deja es lo que lee la siguiente). Con
    ``insert_before`` (el código o el nombre de la entidad ante la que se inserta la que aún no está en ``records``),
    también esa y las que la siguen, que **pasarán** a partir de la nueva: apoyarse en ellas sería un ciclo desde la
    inserción, aunque hoy no lo sea. Una entidad que no está en ``records`` (la nueva) solo cuenta consigo misma y
    con lo que le sigue por la inserción. No escribe nada. :class:`TypeError` si no son entidades;
    ``DesignError`` si la cadena ya está rota (``chain_of``)."""
    items = _records(records)
    found = {own_code}
    if (own := _find(items, own_code)) is not None:
        found |= {item.code for item in chain_of(items, own.code)}
    if insert_before is not None and (successor := _find(items, insert_before)) is not None:
        found |= {item.code for item in chain_of(items, successor.code)}
    return frozenset(found)


# --- Insertar antes o después de otra entidad (RF-015-05) -----------------------------------------


@dataclass(frozen=True, slots=True)
class ParamChange:
    """El cambio de un parámetro de una entidad que deja una operación sobre la cadena, sin
    escribirlo (lo escribe la orden con ``ParameterStore.change``, que pide el motivo, RF-008-02):
    la entidad (``code``), la clave (``key``: ``des.platform.plt_002.start``), su valor anterior
    (``old``; ``None`` si no tenía) y el nuevo (``new``) y el ``reason`` generado, en español o en
    inglés."""

    code: str
    key: str
    old: str | None
    new: str
    reason: str


def insertion_start(records: Iterable[EntityRecord], ref: str, *, before: bool = False) -> str:
    """La superficie de la que tiene que partir la entidad que se inserta junto a la de código o
    nombre ``ref`` (RF-015-05): detrás de ella (por defecto), la superficie que deja
    (``entity:<código>``); delante (``before``), la de la que parte ella, sea un nombre de
    superficie o la de otra entidad. :class:`ValueError` si ``ref`` no es de ``records``, está
    descartada (no tiene sitio en la cadena), es de un tipo sin cadena (no deja una superficie de la que
    partir ni parte de ninguna: spec 016, T02) o, con ``before``, no parte de ninguna superficie."""
    target = _need(_records(records), ref)
    if not _live(target):
        raise ValueError(f"la entidad «{target.name}» está descartada: no admite que se inserte "
                         "otra junto a ella")
    if not EntityKind(target.kind).chained:
        raise ValueError(f"la entidad «{target.name}» es de un tipo sin cadena ({target.kind}): no admite que "
                         "se inserte otra junto a ella")
    if not before:
        return surface_ref(target.code)
    if target.start is None:
        raise ValueError(f"la entidad «{target.name}» no parte de ninguna superficie: no hay nada "
                         "antes de ella donde insertar")
    return target.start


@dataclass(frozen=True, slots=True)
class Insertion:
    """**Dónde se inserta** una entidad junto a otra (RF-015-05; spec 015, T31; «Insertar antes o después de…»): la
    entidad de referencia (``reference``), si se inserta antes de ella (``before``) o después, la superficie de la
    que ha de partir la nueva (``start``: :func:`insertion_start`) y la entidad viva que hoy parte de esa superficie
    (``successor``), que pasará a partir de la nueva y queda obsoleta con las que la siguen (RF-008-24); ``None``
    si la de referencia es la última de su cadena y, después de ella, no cambia ninguna otra."""

    reference: EntityRecord
    before: bool
    start: str
    successor: EntityRecord | None


def insertion_point(records: Iterable[EntityRecord], ref: str, *, before: bool = False) -> Insertion:
    """Dónde se inserta una entidad nueva **junto a** la de código o nombre ``ref`` (RF-015-05, RF-015-04; el diálogo
    de «Insertar antes o después de…»): la superficie de la que parte la nueva (:func:`insertion_start`: la que
    deja ``ref`` si se inserta después, la de la que parte ``ref`` si se inserta antes) y la **sucesora**, la entidad
    viva que hoy parte de ella —la que pasará a partir de la nueva, el mismo cambio de partida que dan
    :func:`insert_after` e :func:`insert_before`—, con la que la nueva **no** se rechaza por partir de una
    superficie ocupada (RF-015-04: se crea con ``entity_store.prepare_platform_units(insert_before=…)``). No
    escribe nada. :class:`ValueError` si ``ref`` no es de ``records``, está descartada o, antes, no parte de ninguna
    superficie; ``DesignError`` si la cadena ya está rota (:func:`check_chain`)."""
    items = _records(records)
    target = _need(items, ref)
    start = insertion_start(items, ref, before=before)
    check_chain(items)
    return Insertion(target, before, start, _index(items).by_start.get(start))


def _insert(items: tuple[EntityRecord, ...], surface: str, new: EntityRecord,
            language: str) -> tuple[ParamChange, ...]:
    """La inserción de ``new`` (que parte de ``surface``): la entidad viva que hoy parte de
    ``surface`` pasa a partir de la de ``new``."""
    if not isinstance(new, EntityRecord):
        raise TypeError(f"la entidad que se inserta es una EntityRecord, no {new!r}")
    if language not in LANGUAGES:
        raise ValueError(f"el idioma «{language}» no es de Geoblender: {', '.join(LANGUAGES)}")
    if any(item.code == new.code for item in items):
        raise ValueError(f"la versión ya tiene una entidad con el código {new.code}: la que se "
                         "inserta tiene el suyo, nuevo")
    if new.start != surface:
        raise ValueError(f"la entidad {new.code} se inserta donde se deja «{surface}», pero parte "
                         f"de {new.start!r}: se crea con la partida de insertion_start")
    check_chain(items)
    successor = _index(items).by_start.get(surface)
    if successor is None:
        return ()
    return (ParamChange(
        successor.code, entity_key(successor.code, PlatformParam.START), successor.start,
        surface_ref(new.code),
        render("des.entity_insert_reason", language=language, inserted=new.name,
               entity=successor.name)),)


def insert_after(records: Iterable[EntityRecord], ref: str, new: EntityRecord, *,
                 language: str = "es") -> tuple[ParamChange, ...]:
    """Insertar ``new`` detrás de la entidad de código o nombre ``ref`` (RF-015-05): ``new`` tiene
    que partir de la superficie que deja ``ref`` (:func:`insertion_start`) y la entidad que hoy
    parte de ella pasa a partir de la de ``new``; devuelve ese cambio de parámetro (su ``start``)
    con su motivo en ``language``, o nada si ``ref`` era la última de su cadena. No escribe nada:
    la orden aplica los cambios y deja obsoletos, por la cascada de la 008, a la sucesora y a las
    que la siguen. :class:`ValueError` si ``ref`` no es de ``records`` o está descartada, si el
    código de ``new`` ya existe, si ``new`` no parte de donde se inserta o el idioma no es de
    Geoblender; ``DesignError`` si la cadena ya está rota (:func:`check_chain`)."""
    items = _records(records)
    return _insert(items, insertion_start(items, ref), new, language)


def insert_before(records: Iterable[EntityRecord], ref: str, new: EntityRecord, *,
                  language: str = "es") -> tuple[ParamChange, ...]:
    """Insertar ``new`` delante de la entidad de código o nombre ``ref`` (RF-015-05): es insertarla
    detrás de lo que hay antes de ``ref`` (:func:`insert_after`, si es otra entidad); si ``ref``
    abre una cadena, ``new`` parte de la superficie de la que parte ella y ella pasa a partir de
    ``new``. Los mismos cambios, rechazos y la misma ausencia de escritura que
    :func:`insert_after`; ``ref`` sin partida es un :class:`ValueError`."""
    items = _records(records)
    return _insert(items, insertion_start(items, ref, before=True), new, language)


# --- El registro de las entidades de una versión (RF-015-01, RF-015-25; plan 015 §5.2.3) ----------

_SUPPORT_ROLES = (SURFACE_ROLE, SUPPORTED_ON_ROLE)
"""Los papeles con que una entidad consume la superficie de la que parte (``surface``) y las de las
que se apoya (``supported_on``; ``provenance``): si uno de esos datos se descarta, a la entidad le
han retirado el apoyo (RF-015-17)."""
_CHUNK = 400
"""Las operaciones por consulta al leer sus datos (el límite de variables de SQLite es mayor)."""
_PARAMETER_ROWS = (
    "SELECT DISTINCT key FROM gb_parameter WHERE scope = ? AND scope_uid = ? AND key LIKE ?")
_OPERATION_ROWS = (
    "SELECT o.uid, o.fid, p.key FROM gb_revision AS r "
    "JOIN gb_operation AS o ON o.revision_uid = r.uid "
    "JOIN gb_operation_param AS p ON p.operation_uid = o.uid "
    "WHERE r.version_uid = ? AND o.op_type = ? AND o.status = 'done' "
    "AND o.superseded_by IS NULL AND p.key LIKE ?")
_PROJECT_OPERATION_ROWS = (
    "SELECT o.uid, o.fid, p.key FROM gb_operation AS o "
    "JOIN gb_operation_param AS p ON p.operation_uid = o.uid "
    "WHERE o.scope = 'project' AND o.op_type = ? AND o.status = 'done' "
    "AND o.superseded_by IS NULL AND p.key LIKE ?")
_DATASET_ROWS = (
    "SELECT io.operation_uid, io.direction, io.role, io.item_uid, d.status "
    "FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
    "WHERE io.item_kind = ? AND io.operation_uid IN ({marks}) ORDER BY io.fid")


@dataclass(frozen=True, slots=True)
class EntityEntry:
    """Una entidad de una versión en el registro: su ``record`` (con el estado deducido), la
    ``operation_uid`` de su operación vigente (``None`` si está sin calcular), las ``causes`` por
    las que está obsoleta (las de la caché ``gb_stale`` de su operación, ``core.provenance.graph``;
    vacías si no lo está) y ``retired``, los uid de los datos descartados que consumió como
    ``surface`` o ``supported_on`` (los que dicen «apoyo retirado»)."""

    record: EntityRecord
    operation_uid: str | None = None
    causes: frozenset[Cause] = frozenset()
    retired: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EntityRegistry:
    """Las entidades de la versión de código ``version``, por código (``PLT-001``, ``PLT-002``…),
    cada una como :class:`EntityEntry`; las de cada tipo juntas y en el orden de su numeración. Con ``scope``
    ``project`` (:func:`project_registry`; T04, D-15), las del **proyecto**: ``version`` es ``""``."""

    version: str
    entries: tuple[EntityEntry, ...]
    scope: str = VERSION_SCOPE

    @property
    def records(self) -> tuple[EntityRecord, ...]:
        """Las entidades como :class:`EntityRecord`, con su estado: lo que reciben las funciones de
        la cadena."""
        return tuple(entry.record for entry in self.entries)

    def get(self, ref: str) -> EntityEntry | None:
        """La entrada de la entidad de código o nombre ``ref`` (el código manda); ``None`` si la
        versión no la tiene."""
        found = _find(self.records, ref)
        return None if found is None else self.entries[self.records.index(found)]

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[EntityEntry]:
        return iter(self.entries)


@contextmanager
def _snapshot(project: Any, conn: sqlite3.Connection | None) -> Iterator[sqlite3.Connection]:
    """La conexión de quien llama o una de lectura nueva, con todas las lecturas en la misma
    instantánea."""
    if conn is not None:
        yield conn
        return
    with project.read() as reading:
        reading.execute("BEGIN")
        try:
            yield reading
        finally:
            reading.execute("ROLLBACK")


def _segment_of(key: str, prefix: str) -> str | None:
    """El código de entidad (``plt_001``) de la clave de un parámetro ``<prefix>.<e>.<valor>``;
    ``None`` si la clave no es de esa forma o ``<e>`` no es el segmento de un código de entidad."""
    if not key.startswith(f"{prefix}."):
        return None
    parts = key[len(prefix) + 1:].split(".")
    if len(parts) != 2:
        return None
    try:
        return segment_code(parts[0])
    except ValueError:
        return None


def _number(code: str) -> tuple[str, int]:
    prefix, _, number = code.partition("-")
    return prefix, int(number)


def code_order(code: str) -> tuple[str, int]:
    """La clave de orden de un código de entidad: su tipo y su número (``PLT-002`` antes que
    ``PLT-010``). ``ValueError`` si no es un código (``PLT-001``)."""
    return _number(code)


def registry(project: Any, version: str, *, conn: sqlite3.Connection | None = None
             ) -> EntityRegistry:
    """Las entidades de la versión ``version`` (uid o código) del proyecto, leídas sin escribir
    (RF-015-01, RF-015-25; ADR-0025 §5): cada código con parámetros ``des.platform.{e}.*`` **propios
    de la versión** (los del proyecto no cuentan; sin fila no hay entidad), con su nombre, su
    partida y su apoyo; su operación vigente (la última hecha y sin sustituir de su tipo que leyó
    sus parámetros, en cualquier revisión de la versión; una fallida o en curso no cuenta) y su
    estado, **deducido** y no apuntado: sin operación, ``UNCALCULATED``; con todos los datos que
    escribió descartados, ``DISCARDED``; si consumió un dato descartado como ``surface`` o
    ``supported_on``, ``SUPPORT_REMOVED``; si la caché de obsolescencia le da causas, ``STALE``; si
    no, ``CURRENT``. Una entidad con su parámetro de versión ``discarded`` verdadero (la que se descartó **sin
    calcular**, T25) es ``DISCARDED`` tenga o no operación. ``conn`` es una conexión de lectura de quien llama
    (con su instantánea); sin
    ella, el registro abre una. :class:`~core.versions.model.VersionError`
    (``core.version_unknown``) si la versión no existe; ``DesignError`` ``des.entity_name_missing``
    si una entidad con parámetros no tiene nombre (un dato roto, que no se lista a medias)."""
    with _snapshot(project, conn) as reading:
        return _registry(project, reading, _version(reading, version))


def project_registry(project: Any, *, conn: sqlite3.Connection | None = None) -> EntityRegistry:
    """Las entidades del **proyecto** (spec 016, T04; D-15, H-3; ADR-0031 §2), leídas sin escribir: las de los tipos que
    tienen una operación de proyecto (``EntityType.project_op_type``: la detección de acopios), cada código con
    parámetros ``des.<tipo>.{e}.*`` **del proyecto** y **con nombre**, su operación vigente (la última hecha y sin
    sustituir de ``project_op_type`` que leyó sus parámetros) y su estado, deducido del grafo como el de
    :func:`registry`. El código es correlativo **por ámbito**: ``STK-001`` es la primera del proyecto y también la primera
    de cada versión. Las filas «sin confirmar» que una operación de **versión** deja en el proyecto (``begin_operation``
    crea la de cada clave que lee: ``docs/trampas.md`` §6) **no son una entidad**: sin nombre, no hay entidad.
    ``conn``, como en :func:`registry`."""
    with _snapshot(project, conn) as reading:
        return _registry(project, reading, None)


def _version(conn: sqlite3.Connection, version: str) -> Version:
    """La versión ``version`` (uid o código) leída con ``conn``; :class:`TypeError` si no es un texto y
    :class:`~core.versions.model.VersionError` (``core.version_unknown``) si no existe."""
    if not isinstance(version, str):
        raise TypeError(f"una versión se indica por su uid o su código, no {version!r}")
    found = versions_read.version(conn, version)
    if found is None:
        raise VersionError("core.version_unknown", field="versión", value=version, version=version)
    return found


def _text(store: ParameterStore, conn: sqlite3.Connection, version: Version | None, code: str,
          param: PlatformParam) -> str | None:
    """El valor de texto del parámetro ``param`` de la entidad ``code`` propio de ``version`` (sin ella, del proyecto);
    ``None`` si no tiene fila o no tiene valor."""
    row = store.get(entity_key(code, param), version=None if version is None else version.uid, conn=conn)
    return None if row is None or row.value is None else str(row.value)


def _texts(store: ParameterStore, conn: sqlite3.Connection, version: Version | None, codes: Iterable[str],
           param: PlatformParam) -> dict[str, str | None]:
    """:func:`_text` de muchas entidades a la vez (T45; el coste de ``mask_state`` con 200 entidades): el valor de
    texto del parámetro ``param`` propio de ``version`` (sin ella, del proyecto) de cada código de ``codes``, ``None`` si
    no tiene fila o no tiene valor. La versión y las filas se leen con **una** consulta por trozo de claves
    (``resolve_many``), no con tres por entidad."""
    keys = {entity_key(code, param): code for code in codes}
    found: dict[str, Any] = {}
    if keys:
        found = (store.resolve_many(conn, tuple(keys), (PROJECT_SCOPE,)) if version is None
                 else store.resolve_many(conn, tuple(keys), (VERSION_SCOPE,), version=version.uid))
    return {code: None if (row := found.get(key)) is None or row.value is None else str(row.value)
            for key, code in keys.items()}


def _registry(project: Any, conn: sqlite3.Connection, version: Version | None) -> EntityRegistry:
    """El registro de ``version`` o, sin ella, del proyecto (:func:`project_registry`): el mismo recorrido de los tipos
    registrados con sus parámetros y su operación en el ámbito que toca."""
    store = ParameterStore(project)
    scope, scope_uid = (PROJECT_SCOPE, "") if version is None else (VERSION_SCOPE, version.uid)
    entries: list[EntityEntry] = []
    for spec in registered_types():
        op_type = spec.op_type if version is not None else spec.project_op_type
        if op_type is None:  # un tipo que no se crea en el proyecto no tiene entidades en él
            continue
        kind, prefix = EntityKind(spec.kind), spec.key_prefix
        keys = [str(key) for (key,) in conn.execute(
            _PARAMETER_ROWS, (scope, scope_uid, f"{prefix}.%")).fetchall()]
        codes = {code for key in keys if (code := _segment_of(key, prefix)) is not None
                 and code.startswith(f"{spec.prefix}-")}
        names = _texts(store, conn, version, codes, PlatformParam.NAME)
        if version is None:  # las filas «sin confirmar» que dejó una operación de versión no son una entidad
            codes = {code for code in codes if (names[code] or "").strip()}
        flagged = {code for key in keys if key.endswith(_DISCARDED_SUFFIX)
                   and (code := _segment_of(key, prefix)) is not None and code in codes
                   and _is_discarded(store, conn, version, code)}
        operations = (_operations(conn, version, prefix, op_type) if version is not None
                      else _project_operations(conn, prefix, op_type))
        links = _links(conn, operations.values())
        # Un tipo sin cadena no tiene ``start``; uno sin ``support``, tampoco (no hay fila que leer).
        starts = (_texts(store, conn, version, codes, PlatformParam.START) if spec.chained
                  else dict.fromkeys(codes))
        supports = (_texts(store, conn, version, codes, PlatformParam.SUPPORT)
                    if PlatformParam.SUPPORT.value in spec.params.names else dict.fromkeys(codes))

        for code in sorted(codes, key=_number):
            name = names[code]
            if name is None or not name.strip():
                raise DesignError("des.entity_name_missing", obj=f"Entidad «{code}»",
                                  field=entity_key(code, PlatformParam.NAME), value=name)
            uid = operations.get(code)
            state, causes, retired = _deduce(conn, uid, links.get(uid, ()) if uid else (),
                                             discarded=code in flagged)
            entries.append(EntityEntry(
                EntityRecord(code, name, kind, starts[code], supports[code], state, scope),
                uid, causes, retired))
    return EntityRegistry("" if version is None else version.code, tuple(entries), scope)


_DISCARDED_SUFFIX = f".{PlatformParam.DISCARDED.value}"
"""El final de la clave del parámetro que descarta una entidad sin calcular (``des.platform.plt_001.discarded``)."""


def _is_discarded(store: ParameterStore, conn: sqlite3.Connection, version: Version | None, code: str) -> bool:
    """Si la entidad ``code`` está descartada por su parámetro ``discarded`` propio de ``version`` (sin ella, del
    proyecto) verdadero: lo que descarta una entidad sin calcular (T25; RF-015-17). Sin fila, falso."""
    row = store.get(entity_key(code, PlatformParam.DISCARDED), version=None if version is None else version.uid,
                    conn=conn)
    return row is not None and row.value is True


def _operations(conn: sqlite3.Connection, version: Version, prefix: str, op_type: str
                ) -> dict[str, str]:
    """Código de entidad → uid de su operación vigente: la última hecha (por ``fid``) y sin
    sustituir de tipo ``op_type`` en las revisiones de ``version`` que leyó un parámetro suyo."""
    latest: dict[str, tuple[int, str]] = {}
    for uid, fid, key in conn.execute(_OPERATION_ROWS, (version.uid, op_type, f"{prefix}.%")):
        code = _segment_of(str(key), prefix)
        if code is not None and (code not in latest or int(fid) > latest[code][0]):
            latest[code] = (int(fid), str(uid))
    return {code: uid for code, (_fid, uid) in latest.items()}


def _project_operations(conn: sqlite3.Connection, prefix: str, op_type: str) -> dict[str, str]:
    """Código de entidad → uid de su operación vigente **de proyecto** (T04): la última hecha (por ``fid``) y sin
    sustituir de tipo ``op_type`` (``scope`` ``project``) que leyó un parámetro suyo."""
    latest: dict[str, tuple[int, str]] = {}
    for uid, fid, key in conn.execute(_PROJECT_OPERATION_ROWS, (op_type, f"{prefix}.%")):
        code = _segment_of(str(key), prefix)
        if code is not None and (code not in latest or int(fid) > latest[code][0]):
            latest[code] = (int(fid), str(uid))
    return {code: uid for code, (_fid, uid) in latest.items()}


def _links(conn: sqlite3.Connection, operations: Iterable[str]
           ) -> dict[str, list[tuple[str, str, str, str]]]:
    """De cada operación, sus datos: ``(sentido, papel, uid del dato, estado del dato)`` por orden
    de registro."""
    found: dict[str, list[tuple[str, str, str, str]]] = {}
    uids = sorted(set(operations))
    for first in range(0, len(uids), _CHUNK):
        part = uids[first:first + _CHUNK]
        sql = _DATASET_ROWS.format(marks=", ".join("?" for _ in part))
        for uid, direction, role, dataset, status in conn.execute(sql, (DATASET, *part)):
            found.setdefault(str(uid), []).append(
                (str(direction), str(role), str(dataset), str(status)))
    return found


def _deduce(conn: sqlite3.Connection, operation: str | None,
            links: Iterable[tuple[str, str, str, str]], *, discarded: bool = False
            ) -> tuple[EntityState, frozenset[Cause], tuple[str, ...]]:
    """El estado de una entidad con la operación ``operation`` (``None``: sin calcular), sus causas
    de obsolescencia y los datos descartados que consumió (véase :func:`registry`). ``discarded``: su parámetro
    ``discarded`` es verdadero (T25): está descartada, calculada o no."""
    if discarded:
        return EntityState.DISCARDED, frozenset(), ()
    if operation is None:
        return EntityState.UNCALCULATED, frozenset(), ()
    discarded = str(DatasetStatus.DISCARDED)
    rows = list(links)
    written = [status for direction, _role, _uid, status in rows if direction == "out"]
    if written and all(status == discarded for status in written):
        return EntityState.DISCARDED, frozenset(), ()
    retired = tuple(uid for direction, role, uid, status in rows
                    if direction == "in" and role in _SUPPORT_ROLES and status == discarded)
    causes = item_causes(conn, STALE_OPERATION, operation)
    if retired:
        return EntityState.SUPPORT_REMOVED, causes, retired
    if causes:
        return EntityState.STALE, causes, ()
    return EntityState.CURRENT, causes, ()


def chain_tail_surfaces(conn: sqlite3.Connection, version: str) -> tuple[str, ...]:
    """Los uid de las superficies (``des_psf_``, papel ``entity_surface``) de **la última de cada cadena** de
    entidades de la versión ``version`` (uid o código): lo que congelar pide verificar de las entidades
    (RF-015-04; RF-012-25; plan 015 §5.1 y §5.7, P-2), en el orden de las cadenas (:func:`chain_tails`). Una
    entidad **sin calcular** no tiene superficie (nada que verificar), una **descartada** es un registro y no es la
    última de ninguna (la que queda como última de su cadena es la anterior) y las intermedias son superficies de
    trabajo, que se verifican a petición: ninguna sale. Lee solo con ``conn`` (la de la instantánea de congelar:
    ``reserves.compliance_store.freeze_findings`` no recibe el proyecto) y no escribe. Sin entidades, ``()``.
    :class:`~core.versions.model.VersionError` (``core.version_unknown``) si la versión no existe;
    ``DesignError`` ``des.entity_chain_cycle`` o ``des.entity_start_taken`` si los datos rompen la regla de la
    cadena (:func:`chain_tails`: no se elige una cola) y ``des.entity_name_missing`` si una entidad no tiene nombre
    (:func:`registry`)."""
    listed = _registry(None, conn, _version(conn, version))  # con conn, el proyecto no se usa
    if not len(listed):
        return ()
    operations = [entry.operation_uid for tail in chain_tails(listed.records)
                  if (entry := listed.get(tail.code)) is not None and entry.operation_uid is not None]
    return tuple(str(uid) for operation in operations
                 for (uid,) in conn.execute(_SURFACES_OF, (operation, DATASET, ENTITY_SURFACE_ROLE)))


# --- Lo que se apoya en una entidad (spec 015, T23; RF-015-15, D-11; plan 015 A6, P-5) -----------------


@dataclass(frozen=True, slots=True)
class Support:
    """Lo que una operación que rellena apoya sobre la huella de una entidad (RF-015-15, D-11): el
    código de la entidad (``code``), las celdas de su huella donde rellena más del espesor mínimo por
    encima de ``máx(partida, entidad)`` (``cells``), el volumen apoyado en m³ (``volume_m3``: ``Σ a·área
    de celda`` en ellas; cero si no apoya nada) y si la persona lo declaró (``declared``: se registra
    **aunque no apoye nada**, o la operación ya lo tenía como entrada).

    **Un acopio** (spec 016, T15; RF-016-14, P-1, A13): una detección es una entidad (``code``, ``STK-001``) y cada acopio, una fila
    suya identificada por la clave de su marca (``stockpile``, ``m07``): lo que se apoya se mide **por acopio**, y un :class:`Support`
    lo es de **uno** (``stockpile`` ``None`` en el de una plataforma, que es el de la 015 sin cambios). :attr:`ref` es la referencia
    de aquello en lo que se apoya (``STK-001#m07`` o ``PLT-001``: la clave de los mapas de :func:`detect_supports`)."""

    code: str
    cells: int
    volume_m3: float
    declared: bool = False
    stockpile: str | None = None

    @property
    def ref(self) -> str:
        """La referencia de aquello en lo que se apoya: el código de la entidad y, de un acopio, su clave (``STK-001#m07``)."""
        return self.code if self.stockpile is None else support_ref(self.code, self.stockpile)


def runs_cells(runs: Iterable[Sequence[int]]) -> tuple[np.ndarray, np.ndarray]:
    """Las celdas de una huella dada en tramos ``(fila, col0, col1)`` (``col1`` excluida: la tabla
    ``des_epr_``) como sus índices ``(filas, columnas)``, de norte a sur y de oeste a este: lo que se
    usa para indexar una rejilla sin construir una máscara de toda ella (vectorizado: sin bucle por
    celda). Sin tramos, dos vectores vacíos. ``ValueError`` si un tramo no tiene celdas o va al revés."""
    chosen = np.asarray([tuple(run) for run in runs], dtype=np.int64).reshape(-1, 3)
    if chosen.size == 0:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64)
    first, last = chosen[:, 1], chosen[:, 2]
    if (last <= first).any():
        raise ValueError("un tramo de la huella de una entidad tiene al menos una celda "
                         "(col1 > col0)")
    lengths = last - first
    rows = np.repeat(chosen[:, 0], lengths)
    ends = np.cumsum(lengths)
    cols = np.arange(int(ends[-1]), dtype=np.int64) - np.repeat(ends - lengths, lengths) \
        + np.repeat(first, lengths)
    return rows, cols


def _positive(value: object, what: str, *, zero: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"{what} es un número, no {value!r}")
    number = float(value)
    if not math.isfinite(number) or number < 0 or (number == 0 and not zero):
        raise ValueError(f"{what} es un número finito {'no negativo' if zero else 'mayor que cero'}, "
                         f"no {value!r}")
    return number


def detect_supports(result: np.ndarray, start: np.ndarray, entity_surfaces: Mapping[str, np.ndarray],
                    footprints: Mapping[str, tuple[np.ndarray, np.ndarray]], min_thickness_m: float,
                    cell_area: float, *, declared: Iterable[str] = ()) -> tuple[Support, ...]:
    """**A6, los apoyos** (RF-015-15, D-11; plan 015 §5.4 A6 y P-5; puro, vectorizado y sin bucle por
    celda): de la superficie ``result`` que deja una operación desde la de partida ``start`` (las dos
    ``(filas, columnas)`` de la misma rejilla, en m, ``NaN`` sin dato), sobre cada entidad ``code`` de
    ``footprints`` (los índices ``(filas, columnas)`` de su huella, :func:`runs_cells`) y con la
    superficie que deja ella, ``entity_surfaces[code]`` (de la misma rejilla), el apoyo es

        a(c) = result(c) − máx(start(c), entidad(c))    en las celdas c de su huella,

    se cuentan las celdas con ``a`` **mayor** que el espesor mínimo de la 012 (``min_thickness_m``, m) y
    el volumen apoyado es ``Σ a · cell_area`` en ellas (m³; ``cell_area`` en m²), a ≤ 10⁻⁹ relativo del
    cálculo a mano. Sin el ``máx`` (P-5), todo diseño que **arrastra el terreno** (``result = start``)
    sobre una plataforma «cortada» (``entidad < start``) contaría como apoyado: con él, el relleno sobre
    la propia entidad (``start = entidad``), sobre el terreno que quedaba por encima (``start >
    entidad``) y la parte por encima de la entidad (``start < entidad``) cuentan y lo que solo se arrastra
    no. Una celda sin dato en alguna de las tres no cuenta.

    Una entidad que apoya algo es un :class:`Support`; una que no, no sale (salvo las de ``declared``: los
    códigos que la persona declara, que salen **siempre** con el volumen que den, cero incluido, y han de
    tener su huella y su superficie). Por orden de código. ``KeyError`` si una entidad de ``footprints`` o de
    ``declared`` no tiene superficie (o una de ``declared`` no tiene huella); ``ValueError`` si las
    rejillas no tienen la misma forma o un número no es finito (errores del programa).

    **Los acopios** (spec 016, T15; RF-016-14, RF-015-15, P-1; plan 016 A13): una detección es una entidad y cada acopio, una fila de
    su tabla con su huella. Los mapas ``entity_surfaces``, ``footprints`` y ``declared`` se indexan por la **referencia** de aquello en
    lo que se apoya (:func:`~.provenance.support_ref`): el código de la entidad (``PLT-001``) o, de un acopio, el de su detección y la
    clave de su marca (``STK-001#m07``); la superficie de **todos** los acopios de una detección es la misma (``des_stp_``, la superficie
    con que se detectó, solo en las huellas: NaN fuera) y la huella de cada uno, la de su fila. Cada acopio sale como un
    :class:`Support` con su ``stockpile`` (la clave): un acopio por cada clave, en el orden en que vienen en ``footprints`` (el de su
    tabla) dentro de su detección. Lo de la plataforma sale **igual** que antes."""
    thickness = _positive(min_thickness_m, "el espesor mínimo", zero=True)
    area = _positive(cell_area, "el área de una celda", zero=False)
    surface = np.asarray(result, dtype=np.float64)
    origin = np.asarray(start, dtype=np.float64)
    if surface.ndim != 2 or surface.shape != origin.shape:
        raise ValueError(f"la superficie resultante {surface.shape} y la de partida {origin.shape} "
                         "son dos rejillas de la misma forma")
    chosen = tuple(dict.fromkeys(declared))
    missing = [ref for ref in chosen if ref not in footprints]
    if missing:
        raise KeyError(f"las entidades declaradas {', '.join(missing)} no tienen huella")
    found: list[Support] = []
    for ref in sorted(footprints, key=_ref_order):  # estable: los acopios de una detección, en el orden de su tabla
        rows, cols = footprints[ref]
        ground = np.asarray(entity_surfaces[ref], dtype=np.float64)
        if ground.shape != surface.shape:
            raise ValueError(f"la superficie de la entidad {ref} {ground.shape} no es de la forma de "
                             f"la rejilla {surface.shape}")
        with np.errstate(invalid="ignore"):
            thickness_on = surface[rows, cols] - np.maximum(origin[rows, cols], ground[rows, cols])
            counted = thickness_on > thickness  # NaN no es mayor que nada: la celda sin dato no cuenta
        cells = int(np.count_nonzero(counted))
        if cells or ref in chosen:
            code, stockpile = split_support_ref(ref)
            found.append(Support(code, cells, float(np.sum(thickness_on[counted])) * area if cells
                                 else 0.0, ref in chosen, stockpile))
    return tuple(found)


def _ref_order(ref: str) -> tuple[str, int]:
    """La clave de orden de la referencia de aquello en lo que se apoya una operación (``PLT-002``, ``STK-001#m07``): el tipo y el
    número del código de la entidad (:func:`code_order`); los acopios de una detección empatan y salen en el orden en que vienen."""
    return _number(ref.partition(SUPPORT_REF_SEPARATOR)[0])


def strongest(found: Iterable[Support]) -> tuple[Support, ...]:
    """Un :class:`Support` por entidad de ``found`` —lo apoyado en ella por **varias** superficies de una
    misma operación (las dos de una cantera, las de un ajuste), que son alternativas y no se suman—: el de
    mayor volumen (a igual volumen, el primero), declarado si alguno lo era. Por orden de código. **Por acopio** (spec 016, T15;
    RF-016-14, P-1): los de una detección se agrupan **por su clave** —dos acopios de una detección son dos grupos, no uno—, en el
    orden en que aparecen dentro de su detección; un :class:`Support` sin clave (una plataforma) se agrupa por su código, como antes."""
    best: dict[str, Support] = {}
    for item in found:
        ref = item.ref
        before = best.get(ref)
        if before is None or item.volume_m3 > before.volume_m3:
            best[ref] = replace(item, declared=item.declared or (before is not None and before.declared))
        elif item.declared and not before.declared:
            best[ref] = replace(before, declared=True)
    return tuple(best[ref] for ref in sorted(best, key=_ref_order))


# --- La lista de dependencias y la causa de lo obsoleto (spec 015, T24; RF-015-15, RF-015-16; RNF-015-02) --

_LIST_ROLES = (SUPPORTED_ON_ROLE, SURFACE_ROLE)
"""Los papeles de la lista de dependencias, en el orden en que se enseñan: lo que se **apoya** (la operación
rellena sobre la superficie de la entidad, o la persona lo declaró: ``supported_on``) y lo que **parte** de ella
(``surface``, la superficie de partida). Una operación que hace las dos cosas es una sola fila con los dos."""
_DEPENDENTS = (
    "SELECT o.uid, o.fid, o.op_type, o.settings, io.role FROM gb_operation_io AS io "
    "JOIN gb_operation AS o ON o.uid = io.operation_uid "
    "JOIN gb_revision AS r ON r.uid = o.revision_uid "
    "WHERE io.direction = 'in' AND io.item_kind = ? AND io.item_uid = ? AND io.role IN (?, ?) "
    "AND o.status = 'done' AND o.superseded_by IS NULL AND r.version_uid = ? ORDER BY o.fid, io.fid")
_REST_ON = (
    "SELECT io.role, d.uid, d.name, d.operation_uid, p.op_type, p.settings FROM gb_operation_io AS io "
    "JOIN gb_dataset AS d ON d.uid = io.item_uid LEFT JOIN gb_operation AS p ON p.uid = d.operation_uid "
    "WHERE io.operation_uid = ? AND io.direction = 'in' AND io.item_kind = ? AND io.role IN (?, ?) "
    "ORDER BY io.fid")
_SURFACES_OF = (
    "SELECT item_uid FROM gb_operation_io WHERE operation_uid = ? AND direction = 'out' AND item_kind = ? "
    "AND role = ? ORDER BY fid")
_VOLUMES = (
    "SELECT operation_uid, scope, value FROM gb_figure WHERE key = ? AND operation_uid IN ({marks}) "
    "ORDER BY fid")
_PARAMETER_KEYS = "SELECT uid, key FROM gb_parameter WHERE uid IN ({marks})"


def kind_label(op_type: str, language: str = "es") -> str:
    """El tipo de una operación de ``des`` como lo lee una persona en ``language`` («Plataforma», «Solo
    relleno»): el nombre visible de su ``OperationDef``; el propio ``op_type`` si no es de ``des``."""
    found = OPERATION_TYPES_BY_NAME.get(op_type)
    return op_type if found is None else translate(language, found.label_msgid)


@dataclass(frozen=True, slots=True)
class Dependent:
    """Una fila de la **lista de dependencias** de una entidad (RF-015-15, D-11; RF-015-17): la operación
    ``operation_uid`` con su ``name`` (el de la entidad o el del diseño), su ``op_type`` (``des.platform``,
    ``des.fill_only``…), si es una entidad su código (``entity``; ``None`` en un diseño) y su ``state``
    **deducido** (los de :class:`EntityState`: al día, obsoleta, «apoyo retirado» o descartada; con sus ``causes``
    de obsolescencia). Los ``roles`` dicen cómo se relaciona con la entidad de la que se pregunta —``supported_on``
    (se apoya en ella: rellena sobre su superficie o lo declaró la persona) y ``surface`` (parte de su
    superficie)— y el ``volume_m3`` es lo apoyado (la cifra ``des.supported_m3`` con ese ámbito; cero si la persona
    lo declaró y no rellena nada) o ``None`` si solo parte de su superficie, sin apoyarse.

    En :func:`dependents` es lo que se apoya en la entidad; en :func:`dependencies_of`, aquello en lo que se apoya
    la entidad (su partida incluida), y el volumen es lo suyo apoyado en ello.

    **En un acopio** (spec 016, T15; RF-016-14, P-1): una detección de acopios es **una** entidad y lo que se apoya, se apoya en **un
    acopio** suyo: ``stockpile`` es la clave de su marca (``Acopio 4``) y ``volume_m3`` lo apoyado **en ese acopio**; una fila por
    operación y acopio. ``None`` en todo lo demás (lo de la 015, sin cambios)."""

    operation_uid: str
    name: str
    op_type: str
    state: EntityState
    roles: tuple[str, ...]
    entity: str | None = None
    volume_m3: float | None = None
    causes: frozenset[Cause] = frozenset()
    stockpile: str | None = None

    def text(self, language: str = "es") -> str:
        """La fila como una línea de la lista, en ``language``: «Sobre la balsa (Plataforma): 8 000 m³
        apoyados» o, sin volumen, «Arrastra el terreno (Plataforma): superficie de partida». Es lo que enseñan la
        barra N (RF-015-25) y el aviso antes de descartar (RF-015-17)."""
        values: dict[str, object] = {"name": self.name, "kind": kind_label(self.op_type, language)}
        if self.volume_m3 is None:
            return render("des.entity_dependent_start", language=language, **values)
        return render("des.entity_dependent_volume", language=language, volume=round(self.volume_m3), **values)


def _entry(listed: EntityRegistry, ref: str, version: Version) -> EntityEntry:
    """La entrada de la entidad ``ref`` (código o nombre) en el registro de ``version``; :class:`ValueError` si no
    es de la versión (un error del programa: quien llama sacó el código del registro)."""
    found = listed.get(ref)
    if found is None:
        raise ValueError(f"la entidad «{ref}» no es de la versión {version.code}")
    return found


def _settings_name(op_type: str, settings: object) -> str:
    """El nombre de una operación hecha: el ``name`` de sus ajustes (JSON) o, sin él, su tipo."""
    try:
        found = json.loads(str(settings)) if settings else {}
    except ValueError:
        found = {}
    name = found.get("name") if isinstance(found, dict) else None
    return name if isinstance(name, str) and name else op_type


def _supported(conn: sqlite3.Connection, operations: Iterable[str]) -> dict[tuple[str, str], float]:
    """Lo apoyado que registró cada operación de ``operations``: ``(operación, referencia)`` → m³, de sus cifras
    ``des.supported_m3`` (una consulta por cada 400 operaciones; el ámbito dice la entidad y, de un **acopio**, su clave: la
    referencia es el código de la entidad o ``STK-001#m07``, spec 016, T15; RF-016-14). En el orden de las cifras."""
    found: dict[tuple[str, str], float] = {}
    uids = sorted(set(operations))
    for first in range(0, len(uids), _CHUNK):
        part = uids[first:first + _CHUNK]
        sql = _VOLUMES.format(marks=", ".join("?" for _ in part))
        for uid, scope, value in conn.execute(sql, (SUPPORTED_M3, *part)):
            try:
                where = json.loads(str(scope))
                code = where.get(ENTITY_SCOPE_KEY)
                key = where.get(STOCKPILE_SCOPE_KEY)
            except (ValueError, AttributeError):
                continue
            if isinstance(code, str) and value is not None:
                found[(str(uid), code if not isinstance(key, str) else f"{code}{SUPPORT_REF_SEPARATOR}{key}")] = float(value)
    return found


def _stockpile_shares(volumes: Mapping[tuple[str, str], float]) -> dict[tuple[str, str], list[tuple[str, float]]]:
    """Lo apoyado **por acopio** de ``volumes`` (:func:`_supported`): ``(operación, código de la detección)`` → ``[(clave del acopio,
    m³), …]`` en el orden de las cifras. Solo las cifras de un acopio (con clave): lo de una plataforma no está."""
    found: dict[tuple[str, str], list[tuple[str, float]]] = {}
    for (uid, ref), value in volumes.items():
        code, separator, key = ref.partition(SUPPORT_REF_SEPARATOR)
        if separator:
            found.setdefault((uid, code), []).append((key, value))
    return found


def _ordered(roles: Iterable[str]) -> tuple[str, ...]:
    """Los papeles de ``roles`` sin repetir, en el orden de :data:`_LIST_ROLES`."""
    kept = set(roles)
    return tuple(role for role in _LIST_ROLES if role in kept)


def dependents(project: Any, version: str, code: str, *, conn: sqlite3.Connection | None = None,
               stockpile: str | None = None) -> tuple[Dependent, ...]:
    """**Lo que se apoya en la entidad** ``code`` (código o nombre) de la versión ``version`` (uid o código):
    las operaciones hechas y sin sustituir de la versión que consumen la superficie de la entidad (su
    ``des_psf_``) con el papel ``supported_on`` o ``surface`` —otras entidades y los diseños de la 013 y la 014
    que rellenan sobre ella, como un «solo relleno»— **en una sola lista** (RF-015-15, D-11; RF-015-17), por orden
    de registro, cada una con su nombre, su tipo, el volumen apoyado en m³ y su estado (:class:`Dependent`). Una
    operación que parte de la superficie y rellena sobre ella es una fila con los dos papeles. Una entidad **sin
    calcular** no tiene superficie: ``()``; una **descartada** sí la tiene (lo que se le apoyaba queda en la
    lista, «apoyo retirado»).

    Es **una consulta de entradas y cifras** (RNF-015-02: con 200 entidades, ≤ 1 s en disco local): no lee ninguna
    superficie ni recorre las entidades más que para su nombre y su estado. ``conn`` es una conexión de lectura de
    quien llama; sin ella, se abre una. :class:`ValueError` si la entidad no es de la versión;
    :class:`~core.versions.model.VersionError` si la versión no existe.

    **Lo que se apoya en un acopio** (spec 016, T15; RF-016-14, RF-015-15 y 17, P-1; plan 016 §5.2.3 «Dependencias»): ``code`` puede ser una
    **detección de acopios** (``STK-001``), cuya superficie es la que se detectó (``des_stp_``, el papel ``stockpile_surface``) y de la
    que se apoya una operación **en un acopio suyo**: la cifra ``des.supported_m3`` lleva en su ámbito la clave del acopio, y la lista
    tiene **una fila por operación y acopio** (``Dependent.stockpile`` con la clave y ``volume_m3`` lo apoyado en él). Con ``stockpile``
    (la clave de un acopio de la detección), solo lo que se apoya en **ese** acopio (``()`` si en él no se apoya nada: también si
    la clave no es de ningún acopio; lo dice la tabla, que esta consulta no lee). Una operación que consume la superficie del acopio
    sin cifra (un recálculo que la arrastró y ya no rellena sobre él) sale una vez, sin acopio y con 0 m³, en la lista de la
    detección entera. ``stockpile`` de una entidad que no es una detección de acopios es un error del programa
    (:class:`ValueError`)."""
    with _snapshot(project, conn) as reading:
        found = _version(reading, version)
        listed = _registry(project, reading, found)
        entry = _entry(listed, code, found)
        wanted = entry.record.code
        is_stockpile = entry.record.kind == EntityKind.STOCKPILE
        if stockpile is not None and not is_stockpile:
            raise ValueError(f"«{stockpile}» no es un acopio: la entidad {wanted} no es una detección de acopios")
        role = entity_type(entry.record.kind).surface_role
        if entry.operation_uid is None or role is None:
            return ()
        rows: dict[str, tuple[int, str, str, set[str]]] = {}
        for surface in [str(uid) for (uid,) in reading.execute(
                _SURFACES_OF, (entry.operation_uid, DATASET, role))]:
            for uid, fid, op_type, settings, role_in in reading.execute(
                    _DEPENDENTS, (DATASET, surface, *_LIST_ROLES, found.uid)):
                row = rows.setdefault(str(uid), (int(fid), str(op_type), str(settings), set()))
                row[3].add(str(role_in))
        volumes = _supported(reading, rows)
        shares = _stockpile_shares(volumes) if is_stockpile else {}
        by_operation = {item.operation_uid: item for item in listed if item.operation_uid is not None}
        links = _links(reading, [uid for uid in rows if uid not in by_operation])
        result: list[Dependent] = []
        for uid, (_fid, op_type, settings, roles) in sorted(rows.items(), key=lambda item: item[1][0]):
            if is_stockpile:  # una fila por acopio en el que se apoya
                parts: list[tuple[str | None, float | None]] = [(key, volume) for key, volume in shares.get((uid, wanted), ())
                                                                if stockpile in (None, key)]
                if not parts and stockpile is None:
                    parts = [(None, 0.0)]
            else:
                parts = [(None, volumes.get((uid, wanted)))]
            item = by_operation.get(uid)
            if item is not None:
                name, owner, state, causes = (item.record.name, item.record.code, EntityState(item.record.state),
                                              item.causes)
            else:
                state, causes, _retired = _deduce(reading, uid, links.get(uid, ()))
                name, owner = _settings_name(op_type, settings), None
            for key, volume in parts:
                result.append(Dependent(uid, name, op_type, state, _ordered(roles), owner, volume, causes, key))
        return tuple(result)


def dependencies_of(project: Any, version: str, code: str, *, conn: sqlite3.Connection | None = None,
                    listed: EntityRegistry | None = None) -> tuple[Dependent, ...]:
    """**En qué se apoya la entidad** ``code`` (código o nombre) de la versión ``version`` (uid o código): lo que
    su operación vigente consume con el papel ``supported_on`` (las entidades en cuya huella rellena, o que la
    persona declaró) y ``surface`` (su superficie de partida: otra entidad, un diseño de la 013 o la 014 o el
    terreno), **en una sola lista** de :class:`Dependent`: lo que se apoya primero y su partida después. De cada
    fila, el nombre y el tipo de quien la escribió (de un dato que no es de ``des``, el nombre del dato), su
    código si es una entidad, su estado y el volumen **de esta entidad apoyado en ella** (``des.supported_m3`` con
    ese ámbito; ``None`` si solo es su partida). Sin operación (sin calcular): ``()``. Una consulta de entradas y
    cifras, como :func:`dependents` (RNF-015-02). Los mismos rechazos. ``listed`` (T30): el registro de las entidades
    de la versión **leído con ``conn``** por quien llama (:func:`registry`), para no leerlo de nuevo en cada
    entidad cuando se pide la de todas (la capa de entidades); sin él, se lee."""
    with _snapshot(project, conn) as reading:
        found = _version(reading, version)
        if listed is None:
            listed = _registry(project, reading, found)
        entry = _entry(listed, code, found)
        if entry.operation_uid is None:
            return ()
        rows: dict[str, tuple[int, str, str, str, str, set[str]]] = {}
        for position, (role, dataset, name, producer, op_type, settings) in enumerate(reading.execute(
                _REST_ON, (entry.operation_uid, DATASET, *_LIST_ROLES))):
            row = rows.setdefault(str(dataset), (position, str(producer), str(name),
                                                 "" if op_type is None else str(op_type), str(settings), set()))
            row[5].add(str(role))
        volumes = _supported(reading, [entry.operation_uid])
        shares = _stockpile_shares(volumes)
        by_operation = {item.operation_uid: item for item in listed if item.operation_uid is not None}
        links = _links(reading, {row[1] for row in rows.values() if row[1] not in by_operation})
        result: list[Dependent] = []
        for _dataset, (_position, producer, name, op_type, settings, roles) in sorted(
                rows.items(), key=lambda item: (SUPPORTED_ON_ROLE not in item[1][5], item[1][0])):
            item = by_operation.get(producer)
            if item is not None and item.record.kind == EntityKind.STOCKPILE:
                # se apoya **en un acopio** de la detección (spec 016, T15): una fila por acopio, con lo suyo apoyado en él
                parts: list[tuple[str | None, float | None]] = list(shares.get((entry.operation_uid, item.record.code), ()))
                if not parts:  # la consumió sin cifra (la arrastró un recálculo y ya no rellena sobre un acopio suyo)
                    parts = [(None, 0.0 if SUPPORTED_ON_ROLE in roles else None)]
                for key, volume in parts:
                    result.append(Dependent(producer, item.record.name, op_type, EntityState(item.record.state),
                                            _ordered(roles), item.record.code, volume, item.causes, key))
            elif item is not None:
                result.append(Dependent(producer, item.record.name, op_type, EntityState(item.record.state),
                                        _ordered(roles), item.record.code,
                                        volumes.get((entry.operation_uid, item.record.code)), item.causes))
            else:
                state, causes, _retired = _deduce(reading, producer, links.get(producer, ()))
                shown = _settings_name(op_type, settings) if op_type.startswith("des.") else name
                result.append(Dependent(producer, shown, op_type, state, _ordered(roles), None, None, causes))
        return tuple(result)


def _named_parameters(conn: sqlite3.Connection, listed: EntityRegistry, causes: Iterable[Cause],
                      language: str) -> list[tuple[str, str]]:
    """De las causas ``causes`` de una operación, los parámetros que son de una entidad de ``listed`` como
    ``(lo que dice la 008, lo que decimos)``: el nombre visible del parámetro de una familia de entidades
    («Pendiente de la rasante de la plataforma · plt_001», ADR-0027) con el **nombre** de la entidad en lugar de
    su código («… · P1»). Sin etiqueta o de una entidad que no es de la versión, nada."""
    subjects = sorted({cause.subject for cause in causes if cause.kind is CauseKind.PARAMETER_CHANGED})
    if not subjects:
        return []
    keys = {str(uid): str(key) for uid, key in conn.execute(
        _PARAMETER_KEYS.format(marks=", ".join("?" for _ in subjects)), subjects)}
    found: list[tuple[str, str]] = []
    for uid in subjects:
        key = keys.get(uid)
        if key is None:
            continue
        for spec in registered_types():
            code = _segment_of(key, spec.key_prefix)
            item = None if code is None else listed.get(code)
            label = parameter_label(key, language)
            if code is None or item is None or label is None:
                continue
            segment = entity_segment(code)
            if label.endswith(f" · {segment}"):
                found.append((label, label[:-len(segment)] + item.record.name))
    return found


_DATASETS = "SELECT uid, name, operation_uid FROM gb_dataset WHERE uid IN ({marks})"


def _support_removed(conn: sqlite3.Connection, listed: EntityRegistry, retired: Iterable[str], language: str
                     ) -> str:
    """La causa de «apoyo retirado» (RF-015-17; D-12): «Apoyo retirado: se descartó la plataforma P1», con el
    **nombre** de cada entidad descartada en la que se apoyaba (o, de un dato que no es de una entidad, el del
    dato), por orden y sin repetir."""
    uids = sorted(set(retired))
    by_operation = {item.operation_uid: item for item in listed if item.operation_uid is not None}
    found = {str(uid): (str(name), str(writer)) for uid, name, writer in conn.execute(
        _DATASETS.format(marks=", ".join("?" for _ in uids)), uids)}
    parts: list[str] = []
    for uid in uids:
        name, writer = found.get(uid, (uid, ""))
        owner = by_operation.get(writer)
        text = (render(entity_type(owner.record.kind).removed, language=language,
                       name=owner.record.name) if owner is not None
                else render("des.support_removed_dataset", language=language, name=name))
        if text not in parts:
            parts.append(text)
    return render("des.support_removed", language=language, what="; ".join(parts))


def _retired_of(conn: sqlite3.Connection, operation: str) -> tuple[str, ...]:
    """Los datos descartados que consumió la operación ``operation`` como ``surface`` o ``supported_on`` (su
    «apoyo retirado»); ninguno si no consumió ninguno o si todo lo que escribió está descartado (es un registro)."""
    links = _links(conn, [operation])
    return _deduce(conn, operation, links.get(operation, ()))[2]


def _reason(conn: sqlite3.Connection, listed: EntityRegistry, operation: str, language: str) -> str | None:
    """La causa de que la operación ``operation`` no esté al día: si le han **retirado el apoyo** (consumió, como
    superficie de partida o de apoyo, el dato de una entidad descartada), «Apoyo retirado: se descartó la
    plataforma P1»; si no, «Obsoleto: …» según la caché de la 008 (``item_text``: las causas raíz, por clase y por
    nombre, con «mientras se calculaba») con el nombre de cada entidad cuyo parámetro cambió en lugar de su
    código; ``None`` si está al día."""
    retired = _retired_of(conn, operation)
    if retired:
        return _support_removed(conn, listed, retired, language)
    causes = item_causes(conn, STALE_OPERATION, operation)
    text = item_text(conn, STALE_OPERATION, operation, language=language)
    if text is None:
        return None
    for old, new in _named_parameters(conn, listed, causes, language):
        text = re.sub(re.escape(old) + r"(?!\w)", lambda _match, new=new: new, text)
    return text


def stale_reason(project: Any, version: str, code: str, *, language: str = "es",
                 conn: sqlite3.Connection | None = None) -> str | None:
    """**Por qué está obsoleta la entidad** ``code`` (código o nombre) de la versión ``version`` (uid o código),
    en ``language`` (RF-015-16): el «Obsoleto: cambió …» de la 008 con las **causas raíz** de su operación (la
    cascada ya las propagó: la entidad de la que parte, la que cambió un parámetro, las máscaras…), cada
    parámetro de una entidad con el nombre de **la entidad** que cambió y lo que cambió («Obsoleto: cambió
    Pendiente de la rasante de la plataforma · P1»); si le han retirado el apoyo (T25: consumió la superficie de
    una entidad descartada), «Apoyo retirado: se descartó la plataforma P1». ``None`` si está al día o sin
    calcular. Lo que lee la barra N (RF-015-25). Solo lee. :class:`ValueError` si la entidad no es de la versión;
    :class:`~core.versions.model.VersionError` si la versión no existe."""
    _language(language)
    with _snapshot(project, conn) as reading:
        found = _version(reading, version)
        listed = _registry(project, reading, found)
        entry = _entry(listed, code, found)
        if entry.operation_uid is None:
            return None
        if entry.retired:  # «apoyo retirado» (RF-015-17): la causa es el descarte, no los datos que «cambiaron»
            return _support_removed(reading, listed, entry.retired, language)
        if not entry.causes:
            return None
        return _reason(reading, listed, entry.operation_uid, language)


def operation_reason(project: Any, version: str, operation_uid: str, *, language: str = "es",
                     conn: sqlite3.Connection | None = None) -> str | None:
    """Como :func:`stale_reason`, de **cualquier operación** de la versión ``version`` (uid o código): un diseño
    de la 013 o la 014 que se apoya en una entidad, una verificación o una cubicación que usa su superficie
    (lo obsoleto «en cascada», RF-015-16). ``None`` si está al día. :class:`ValueError` si la operación no es de
    la versión."""
    _language(language)
    with _snapshot(project, conn) as reading:
        found = _version(reading, version)
        row = reading.execute(
            "SELECT 1 FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid "
            "WHERE o.uid = ? AND r.version_uid = ?", (operation_uid, found.uid)).fetchone()
        if row is None:
            raise ValueError(f"la operación «{operation_uid}» no es de la versión {found.code}")
        if not item_causes(reading, STALE_OPERATION, operation_uid) and not _retired_of(reading, operation_uid):
            return None
        return _reason(reading, _registry(project, reading, found), operation_uid, language)


def _language(language: str) -> None:
    if language not in LANGUAGES:
        raise ValueError(f"el idioma «{language}» no es de Geoblender: {', '.join(LANGUAGES)}")


# --- Lo que perdió su apoyo (spec 015, T25; RF-015-17; D-12; plan 015 §5.4 A7) -----------------------------

_RETIRED = (
    "SELECT o.uid, o.fid, o.op_type, o.settings, io.role, d.uid, d.name, d.operation_uid "
    "FROM gb_operation_io AS io JOIN gb_operation AS o ON o.uid = io.operation_uid "
    "JOIN gb_revision AS r ON r.uid = o.revision_uid JOIN gb_dataset AS d ON d.uid = io.item_uid "
    "WHERE io.direction = 'in' AND io.item_kind = ? AND io.role IN (?, ?) AND d.status = ? "
    "AND o.status = 'done' AND o.superseded_by IS NULL AND r.version_uid = ? ORDER BY o.fid, io.fid")


@dataclass(frozen=True, slots=True)
class RetiredEntity:
    """Lo descartado en lo que se apoyaba una operación (:class:`RetiredSupport`): el dato descartado
    (``dataset_uid`` y ``dataset``), la entidad a la que pertenecía (``code`` y su ``name``; sin código, un dato
    que no es de una entidad, con el nombre del dato) y los papeles con que lo consumía la operación (``roles``:
    ``supported_on``, si rellenaba sobre él o lo declaró la persona, y ``surface``, si partía de su superficie)."""

    code: str | None
    name: str
    dataset_uid: str
    dataset: str
    roles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RetiredSupport:
    """Una operación vigente de la versión que **perdió su apoyo** (RF-015-17, D-12): consumió, como superficie de
    partida o de apoyo, el dato de una entidad descartada. Es una entidad (``entity``: su código) o un diseño de la
    013 o la 014 (sin código), con su ``name``, su tipo (``op_type``) y lo que perdió (``retired``, por orden de
    registro). ``releasable``: si se puede **dar por buena** sin ese apoyo (A7, P-6): solo si no parte de la
    superficie de ninguna entidad descartada; una que parte de ella se rehace sobre otra superficie o se descarta."""

    operation_uid: str
    name: str
    op_type: str
    entity: str | None
    retired: tuple[RetiredEntity, ...]

    @property
    def releasable(self) -> bool:
        return all("surface" not in item.roles for item in self.retired)

    def text(self, language: str = "es") -> str:
        """Su causa: «Apoyo retirado: se descartó la plataforma P1», en ``language``."""
        what: list[str] = []
        for item in self.retired:
            text = (render("des.support_removed_dataset", language=language, name=item.name) if item.code is None
                    else render(entity_type(kind_of_code(item.code)).removed, language=language, name=item.name))
            if text not in what:
                what.append(text)
        return render("des.support_removed", language=language, what="; ".join(what))


def retired_supports(project: Any, version: str, *, conn: sqlite3.Connection | None = None
                     ) -> tuple[RetiredSupport, ...]:
    """**Lo que perdió su apoyo** en la versión ``version`` (uid o código; RF-015-17, D-12): las operaciones hechas y
    sin sustituir que consumieron, como ``surface`` o ``supported_on``, el dato de una entidad descartada
    —entidades y diseños de la 013 y la 014—, cada una con lo que perdió, por orden de registro. Una entidad que
    está también descartada no cuenta (es un registro). Es lo que ofrece «Soltar el apoyo…» y lo que dice la
    comprobación de :func:`~.entity_store.release_support`. Una consulta de entradas, sin leer ninguna superficie.
    :class:`~core.versions.model.VersionError` si la versión no existe."""
    with _snapshot(project, conn) as reading:
        found = _version(reading, version)
        listed = _registry(project, reading, found)
        by_operation = {item.operation_uid: item for item in listed if item.operation_uid is not None}
        rows: dict[str, tuple[int, str, str, dict[str, tuple[str, str, set[str]]]]] = {}
        for uid, fid, op_type, settings, role, dataset, name, writer in reading.execute(
                _RETIRED, (DATASET, *_SUPPORT_ROLES, str(DatasetStatus.DISCARDED), found.uid)):
            row = rows.setdefault(str(uid), (int(fid), str(op_type), str(settings), {}))
            row[3].setdefault(str(dataset), (str(name), str(writer), set()))[2].add(str(role))
        result: list[RetiredSupport] = []
        for uid, (_fid, op_type, settings, datasets) in sorted(rows.items(), key=lambda item: item[1][0]):
            item = by_operation.get(uid)
            if item is not None and item.record.state is EntityState.DISCARDED:
                continue
            lost: list[RetiredEntity] = []
            for dataset, (name, writer, roles) in datasets.items():
                owner = by_operation.get(writer)
                lost.append(RetiredEntity(
                    None if owner is None else owner.record.code, name if owner is None else owner.record.name,
                    dataset, name, _ordered(roles)))
            result.append(RetiredSupport(
                uid, item.record.name if item is not None else _settings_name(op_type, settings), op_type,
                None if item is None else item.record.code, tuple(lost)))
        return tuple(result)


# --- La zona que declara una entidad (spec 015, T16; RF-012-29, RF-015-10; A8; D-23) ---------------

_EAST, _NORTH, _WEST, _SOUTH = range(4)
"""Los cuatro sentidos de una arista de celda, en el orden en que giran hacia la izquierda: este,
norte, oeste y sur. Girar a la derecha es el sentido anterior."""
_STEP_ROW = (0, -1, 0, 1)
_STEP_COL = (1, 0, -1, 0)
"""Cuánto cambian la línea de filas (hacia el sur) y la de columnas (hacia el este) al recorrer una
arista de cada sentido."""


@dataclass(frozen=True, slots=True, eq=False)
class DeclaredZone:
    """La zona que declara una entidad (RF-012-29, A8): el contorno alineado a la rejilla de las
    celdas de su huella, listo para ser la geometría de una restricción declarada.

    ``parts``: un polígono por componente 4-conexa de la huella —sus anillos cerrados, el exterior
    antihorario y los huecos horarios, con las coordenadas **absolutas** float64 ``(k, 2)`` de
    solo lectura que dan ``grid.west + columna·dx`` y ``grid.north − fila·dy``— o, de la componente
    cuyo contorno se tocaría a sí mismo (``split``), varios rectángulos que se tocan; ``cells`` y
    ``area_m2``: las celdas de la huella y su área exacta; ``guard_m``: el resguardo hacia fuera con
    que se declara (lo amplía la compilación de la 012, no el contorno); ``components``: las
    componentes 4-conexas; ``split``: cuántas hubo que partir; ``sha256``: el hash del contorno
    (sin el resguardo), el mismo para la misma huella."""

    parts: tuple[tuple[np.ndarray, ...], ...]
    cells: int
    area_m2: float
    guard_m: float
    components: int
    split: int
    sha256: str


def _guard(value: object) -> float:
    """El resguardo ``value`` como ``float``: un número real finito ≥ 0 (``TypeError`` si no es un
    número, ``ValueError`` si no es finito o es negativo: errores del programa)."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"el resguardo de una zona es un número, no {value!r}")
    guard = float(value)
    if not math.isfinite(guard) or guard < 0.0:
        raise ValueError(f"el resguardo de una zona es un número finito ≥ 0, no {value!r}")
    return guard


def _line_of(offset: object, what: str) -> int:
    if isinstance(offset, bool) or not isinstance(offset, numbers.Integral):
        raise TypeError(f"{what} es un número entero, no {offset!r}")
    return int(offset)


def _boundary(labels: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Las aristas del borde de las componentes de ``labels`` (0 fuera, ``1…n`` dentro): fila y
    columna de su vértice de salida (líneas de la rejilla, desde la de arriba a la izquierda de
    ``labels``), su sentido (:data:`_EAST` …) y la etiqueta de su componente. Cada arista deja a su
    izquierda la celda de dentro: recorrerlas así da el exterior antihorario y los huecos horarios."""
    padded = np.pad(labels, 1)
    inner = padded[1:-1, 1:-1]
    inside = inner > 0
    rows: list[np.ndarray] = []
    cols: list[np.ndarray] = []
    senses: list[np.ndarray] = []
    names: list[np.ndarray] = []
    for sense, neighbour, shift_row, shift_col in (
            (_WEST, padded[:-2, 1:-1], 0, 1),   # la de arriba va al oeste desde su esquina este
            (_EAST, padded[2:, 1:-1], 1, 0),    # la de abajo, al este desde su esquina oeste
            (_SOUTH, padded[1:-1, :-2], 0, 0),  # la de la izquierda, al sur
            (_NORTH, padded[1:-1, 2:], 1, 1)):  # la de la derecha, al norte
        row, col = np.nonzero(inside & (neighbour == 0))
        rows.append(row + shift_row)
        cols.append(col + shift_col)
        senses.append(np.full(row.size, sense, dtype=np.int64))
        names.append(inner[row, col].astype(np.int64))
    return (np.concatenate(rows).astype(np.int64), np.concatenate(cols).astype(np.int64),
            np.concatenate(senses), np.concatenate(names))


def _trace(rows: np.ndarray, cols: np.ndarray, senses: np.ndarray, width: int
           ) -> list[tuple[np.ndarray, np.ndarray]]:
    """Los anillos que forman las aristas de **una** componente (``rows``, ``cols`` y ``senses`` de
    :func:`_boundary`): de cada uno, las líneas de fila y de columna de sus esquinas (sin vértices
    en los lados rectos), empezando por la esquina de más arriba y, a igual fila, más a la izquierda.
    En un vértice donde se tocan dos celdas en diagonal salen dos aristas y se **gira a la derecha**:
    cada anillo rodea una sola región de fuera (4-conexa), así que un anillo nunca se toca a sí mismo
    y solo roza a otro (un hueco que toca el exterior) en ese vértice."""
    count = rows.size
    start = rows * width + cols
    end = (rows + np.asarray(_STEP_ROW)[senses]) * width + cols + np.asarray(_STEP_COL)[senses]
    leaving: dict[int, list[int]] = {}
    for index, vertex in enumerate(start.tolist()):
        leaving.setdefault(vertex, []).append(index)
    ends = end.tolist()
    turns = senses.tolist()
    used = [False] * count
    found: list[tuple[np.ndarray, np.ndarray]] = []
    for first in range(count):
        if used[first]:
            continue
        ring: list[int] = []
        edge = first
        while True:
            used[edge] = True
            ring.append(edge)
            options = leaving[ends[edge]]
            chosen = options[0]
            if len(options) > 1:
                right = (turns[edge] - 1) % 4
                chosen = next((other for other in options if turns[other] == right), chosen)
            if chosen == first:
                break
            edge = chosen
        order = np.asarray(ring, dtype=np.int64)
        directions = senses[order]
        corner = order[directions != np.roll(directions, 1)]
        ring_rows, ring_cols = rows[corner], cols[corner]
        begin = int(np.lexsort((ring_cols, ring_rows))[0])
        found.append((np.roll(ring_rows, -begin), np.roll(ring_cols, -begin)))
    return found


def _twice(rings: Sequence[tuple[np.ndarray, np.ndarray]], width: int) -> bool:
    """Si dos esquinas de los anillos son el mismo vértice (un hueco que toca el exterior, o a otro
    hueco, por una esquina): el polígono se tocaría a sí mismo."""
    vertices = np.concatenate([row * width + col for row, col in rings])
    return bool(np.unique(vertices).size != vertices.size)


def _rectangles(mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Los rectángulos ``(fila_ini, fila_fin, col_ini, col_fin)`` (fin excluido) en que se parte
    ``mask``: los tramos de cada fila, unidos con el de la fila siguiente cuando tienen las mismas
    columnas. Sin solapes y por fila y columna."""
    padded = np.zeros((mask.shape[0], mask.shape[1] + 2), dtype=np.int8)
    padded[:, 1:-1] = mask
    change = np.diff(padded, axis=1)
    found: list[tuple[int, int, int, int]] = []
    open_runs: dict[tuple[int, int], int] = {}
    for row in range(mask.shape[0]):
        first = np.flatnonzero(change[row] == 1).tolist()
        last = np.flatnonzero(change[row] == -1).tolist()
        now = set(zip(first, last, strict=True))
        for key in sorted(open_runs):
            if key not in now:
                found.append((open_runs.pop(key), row, key[0], key[1]))
        for key in sorted(now):
            open_runs.setdefault(key, row)
    for key in sorted(open_runs):
        found.append((open_runs[key], mask.shape[0], key[0], key[1]))
    return sorted(found, key=lambda rectangle: (rectangle[0], rectangle[2]))


def _absolute(grid: Grid, rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
    """El anillo **cerrado** de las líneas de fila ``rows`` y de columna ``cols`` de la rejilla
    entera, en coordenadas absolutas: ``west + columna·dx`` y ``north − fila·dy`` en float64, sin más
    aritmética (principio 6), de solo lectura."""
    closed_rows = np.append(rows, rows[0]).astype(np.float64)
    closed_cols = np.append(cols, cols[0]).astype(np.float64)
    ring = np.column_stack((grid.west + closed_cols * grid.dx, grid.north - closed_rows * grid.dy))
    ring.flags.writeable = False
    return ring


def _zone_hash(parts: Sequence[Sequence[np.ndarray]]) -> str:
    """El hash del contorno: sus partes y anillos con los vértices tal cual (``<f8``)."""
    digest = hashlib.sha256(b"geoblender.declared_zone/1;")
    for part in parts:
        digest.update(b"part:%d;" % len(part))
        for ring in part:
            digest.update(b"ring:%d;" % len(ring))
            digest.update(np.ascontiguousarray(ring, dtype="<f8").tobytes())
    return digest.hexdigest()


def declared_zone(footprint_cells: np.ndarray, grid: Grid, guard_m: float, *,
                  offset: tuple[int, int] = (0, 0)) -> DeclaredZone:
    """La zona que declara una entidad cuya huella son las celdas verdaderas de ``footprint_cells``
    (RF-012-29, RF-015-10; A8; D-23).

    ``footprint_cells``: una máscara booleana de 2 dimensiones, la de toda la rejilla de ``grid`` o
    la de una ventana suya cuya celda ``[0, 0]`` es la de la fila y la columna ``offset`` (el
    resultado es el mismo); ``guard_m``: el resguardo hacia fuera (m, finito ≥ 0: lo que la
    compilación de la 012 suma a la zona, D-19; no cambia el contorno). Las celdas forman componentes
    **4-conexas** (``design.grids.label_components``) y el contorno de cada una, con sus huecos, es un
    polígono **válido para las comprobaciones de la 012** —sin vértices de más, sus coordenadas
    exactas desde ``grid.west`` y ``grid.north``, el exterior antihorario y los huecos horarios—; dos
    celdas que solo se tocan por una esquina son componentes distintas, y por tanto partes distintas.
    Una componente cuyo hueco toca el exterior por una esquina (la 012 daría por no válido un polígono
    que se toca a sí mismo) se parte en rectángulos que se tocan: ``DeclaredZone.split`` lo cuenta.
    Con resguardo 0, la regla de la celda de RF-012-12 devuelve **exactamente** las celdas de la
    huella (D-23); con resguardo, crece como con cualquier otra restricción. Determinista: la misma
    huella da los mismos bits (``DeclaredZone.sha256``). No modifica la máscara.

    ``TypeError`` o ``ValueError`` (errores del programa) si ``guard_m`` no es un número finito ≥ 0,
    la máscara no es de 2 dimensiones o no tiene ninguna celda, o la ventana no cabe en la rejilla."""
    guard = _guard(guard_m)
    mask = np.asarray(footprint_cells)
    if mask.ndim != 2:
        raise ValueError(f"la huella es una máscara de 2 dimensiones, no de {mask.ndim}")
    mask = mask.astype(bool, copy=False)
    shift_row = _line_of(offset[0], "la fila de la ventana")
    shift_col = _line_of(offset[1], "la columna de la ventana")
    if (shift_row < 0 or shift_col < 0 or shift_row + mask.shape[0] > grid.nrows
            or shift_col + mask.shape[1] > grid.ncols):
        raise ValueError(f"la ventana de {mask.shape[0]} × {mask.shape[1]} celdas en la fila "
                         f"{shift_row} y la columna {shift_col} no cabe en la rejilla de "
                         f"{grid.nrows} × {grid.ncols} celdas")
    used_rows = np.flatnonzero(mask.any(axis=1))
    if used_rows.size == 0:
        raise ValueError("la huella no tiene ninguna celda: una entidad sin huella no declara nada")
    used_cols = np.flatnonzero(mask.any(axis=0))
    top, left = int(used_rows[0]), int(used_cols[0])
    mask = mask[top:int(used_rows[-1]) + 1, left:int(used_cols[-1]) + 1]
    shift_row, shift_col = shift_row + top, shift_col + left
    labels = label_components(mask)
    width = mask.shape[1] + 1
    rows, cols, senses, names = _boundary(labels.grid)
    order = np.argsort(names, kind="stable")
    rows, cols, senses, names = rows[order], cols[order], senses[order], names[order]
    bounds = np.searchsorted(names, np.arange(1, labels.count + 2))
    parts: list[tuple[np.ndarray, ...]] = []
    split = 0
    for number in range(labels.count):
        lo, hi = int(bounds[number]), int(bounds[number + 1])
        rings = _trace(rows[lo:hi], cols[lo:hi], senses[lo:hi], width)
        if _twice(rings, width):
            split += 1
            inside = labels.grid == number + 1
            for first, last, begin, end in _rectangles(inside):
                parts.append((_absolute(grid, np.array([first, last, last, first]) + shift_row,
                                        np.array([begin, begin, end, end]) + shift_col),))
            continue
        # El exterior es el único anillo antihorario; los huecos, por su esquina de más arriba.
        area = [int(np.sum(col * np.roll(-row, -1) - np.roll(col, -1) * -row))
                for row, col in rings]
        shell = [index for index, value in enumerate(area) if value > 0]
        holes = sorted((index for index, value in enumerate(area) if value < 0),
                       key=lambda index: (int(rings[index][0][0]), int(rings[index][1][0])))
        parts.append(tuple(_absolute(grid, rings[index][0] + shift_row, rings[index][1] + shift_col)
                           for index in (*shell, *holes)))
    cells = int(mask.sum())
    return DeclaredZone(tuple(parts), cells, cells * grid.cell_area, guard, labels.count, split,
                        _zone_hash(parts))


def declared_zone_of_runs(runs: Iterable[Sequence[int]], grid: Grid, guard_m: float
                          ) -> DeclaredZone:
    """:func:`declared_zone` de la huella que dicen ``runs``: los tramos de fila
    ``(fila, col0, col1)`` absolutos de la rejilla entera, ``col1`` excluida, que guarda ``des_epr_``
    (``entity_store.footprint_runs``), en cualquier orden. Solo construye la máscara de la caja que
    los contiene, no la de toda la rejilla. ``ValueError`` si no hay ninguno o un tramo no cabe en la
    rejilla o no tiene celdas."""
    found = [tuple(int(value) for value in run) for run in runs]
    if not found:
        raise ValueError("la huella no tiene ningún tramo: una entidad sin huella no declara nada")
    for row, first, last in found:
        if not (0 <= row < grid.nrows and 0 <= first < last <= grid.ncols):
            raise ValueError(f"el tramo ({row}, {first}, {last}) no cabe en una rejilla de "
                             f"{grid.nrows} × {grid.ncols} celdas")
    top, bottom = min(run[0] for run in found), max(run[0] for run in found)
    left, right = min(run[1] for run in found), max(run[2] for run in found)
    mask = np.zeros((bottom - top + 1, right - left), dtype=bool)
    for row, first, last in found:
        mask[row - top, first - left:last - left] = True
    return declared_zone(mask, grid, guard_m, offset=(top, left))
