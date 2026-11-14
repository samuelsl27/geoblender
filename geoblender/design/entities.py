# SPDX-License-Identifier: GPL-3.0-or-later
"""Las entidades de diseño (spec 015, T02; HU-015-1; RF-015-01; plan 015 §5.1 y §5.3.1; ADR-0030).

Una entidad es una operación de versión con su nombre y un **código inmutable por versión**
(``PLT-001``) cuyos parámetros son la familia ``des.platform.{e}.*`` (:mod:`design.params`):
sin fila no hay entidad; con fila y sin operación, está «sin calcular». Su estado se **deduce** del
grafo (ADR-0025 §5), no se apunta. Python puro, sin leer el proyecto (la lectura es de la T03).

- :class:`EntityKind`: el tipo (en esta spec, la plataforma; la 016 añade los suyos) y su prefijo
  de código.
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
nada. **Una entidad descartada es un registro**: no ocupa su superficie ni está en ninguna cadena
(salvo la que se pregunta por ella), y lo que parte de la suya queda al principio de su propia
cadena («apoyo retirado», RF-015-17).

**El registro de una versión** (:func:`registry`; RF-015-01, RF-015-25): lee del proyecto, sin
escribir, los códigos con parámetros ``des.platform.{e}.*`` de la versión (el nombre, la partida y
el apoyo; sin fila no hay entidad), la operación vigente de cada una (la última hecha y sin
sustituir de su tipo que leyó sus parámetros) y su estado **deducido** del grafo (ADR-0025 §5): sin
calcular, al día, obsoleta (con sus causas, de la caché ``gb_stale``), descartada (todos los datos
que escribió están descartados) o «apoyo retirado» (consumió, como ``surface`` o ``supported_on``,
un dato descartado).

``design.entities`` es un módulo pesado de la 015: lo importan el almacén y las órdenes al usarlo, no
``bl`` al registrarse ni ``design.provenance`` (``tests/unit/architecture/test_lazy_registration.py``).
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from ..core.datasets.model import DatasetStatus
from ..core.i18n import LANGUAGES
from ..core.params import VERSION_SCOPE, ParameterStore
from ..core.provenance.graph import DATASET, Cause
from ..core.provenance.stale import OPERATION as STALE_OPERATION
from ..core.provenance.stale import item_causes
from ..core.versions import read as versions_read
from ..core.versions.model import Version, VersionError
from .messages import DesignError, render
from .params import PLATFORM_PREFIX, PlatformParam, entity_key, entity_segment, segment_code

__all__ = [
    "ENTITY_PREFIX",
    "EntityEntry",
    "EntityKind",
    "EntityRecord",
    "EntityRegistry",
    "EntityState",
    "ParamChange",
    "chain_of",
    "chain_tails",
    "check_chain",
    "declared_reason",
    "find_entity",
    "format_code",
    "insert_after",
    "insert_before",
    "insertion_start",
    "next_code",
    "predecessor_of",
    "ref_code",
    "registry",
    "start_conflict",
    "successor_of",
    "surface_ref",
]


class EntityKind(StrEnum):
    """El tipo de una entidad (RF-015-01): en esta spec, la plataforma; el acopio, el contrafuerte
    y el cuerpo apoyado son de la 016. El valor es el que va en la clave de sus parámetros
    (``des.platform.{e}.*``); :attr:`prefix`, el principio de su código (``PLT``)."""

    PLATFORM = "platform"

    @property
    def prefix(self) -> str:
        """El principio del código de una entidad de este tipo: ``PLT`` de ``PLT-001``."""
        return _PREFIXES[self]


_PREFIXES: dict[EntityKind, str] = {EntityKind.PLATFORM: "PLT"}
_REASONS: dict[EntityKind, str] = {EntityKind.PLATFORM: "des.platform_declared_reason"}
_CODE = re.compile(r"(?P<prefix>[A-Z]{2,5})-(?P<number>[0-9]{3,})")


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
    no es de su tipo es un error del programa (:class:`ValueError`)."""

    code: str
    name: str
    kind: EntityKind | str
    start: str | None = None
    support: str | None = None
    state: EntityState | str = EntityState.UNCALCULATED

    def __post_init__(self) -> None:
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
        object.__setattr__(self, "start", _text_or_none(self.start, "la superficie de partida"))
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
    return render(_REASONS[EntityKind(kind)], language=language, name=shown)


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
    parten de la misma superficie (los datos rompen la regla de la cadena: no se elige una)."""
    by_start: dict[str, EntityRecord] = {}
    for item in items:
        if not _live(item) or item.start is None:
            continue
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
    está en ninguna. ``DesignError`` ``des.entity_chain_cycle`` si alguna da la vuelta (no tiene
    principio, y no se pierde) y ``des.entity_start_taken`` si dos parten de la misma superficie."""
    items = _records(records)
    index = _index(items)
    placed = [item for item in items if _live(item) and item.start is not None]
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
    descartada (no tiene sitio en la cadena) o, con ``before``, no parte de ninguna superficie."""
    target = _need(_records(records), ref)
    if not _live(target):
        raise ValueError(f"la entidad «{target.name}» está descartada: no admite que se inserte "
                         "otra junto a ella")
    if not before:
        return surface_ref(target.code)
    if target.start is None:
        raise ValueError(f"la entidad «{target.name}» no parte de ninguna superficie: no hay nada "
                         "antes de ella donde insertar")
    return target.start


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

_FAMILIES: Mapping[EntityKind, tuple[str, str]] = MappingProxyType({
    EntityKind.PLATFORM: (PLATFORM_PREFIX, "des.platform"),
})
"""Por tipo de entidad: el principio de la clave de sus parámetros (``des.platform``, que sigue
``.{e}.<valor>``) y el tipo de su operación de versión (``des.platform``; lo declara la T04)."""
_SUPPORT_ROLES = ("surface", "supported_on")
"""Los papeles con que una entidad consume la superficie de la que parte y las de las que se apoya:
si uno de esos datos se descarta, a la entidad le han retirado el apoyo (RF-015-17)."""
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
    cada una como :class:`EntityEntry`; las de cada tipo juntas y en el orden de su numeración."""

    version: str
    entries: tuple[EntityEntry, ...]

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
    no, ``CURRENT``. ``conn`` es una conexión de lectura de quien llama (con su instantánea); sin
    ella, el registro abre una. :class:`~core.versions.model.VersionError`
    (``core.version_unknown``) si la versión no existe; ``DesignError`` ``des.entity_name_missing``
    si una entidad con parámetros no tiene nombre (un dato roto, que no se lista a medias)."""
    if not isinstance(version, str):
        raise TypeError(f"una versión se indica por su uid o su código, no {version!r}")
    with _snapshot(project, conn) as reading:
        found = versions_read.version(reading, version)
        if found is None:
            raise VersionError("core.version_unknown", field="versión", value=version,
                               version=version)
        return _registry(project, reading, found)


def _text(store: ParameterStore, conn: sqlite3.Connection, version: Version, code: str,
          param: PlatformParam) -> str | None:
    """El valor de texto del parámetro ``param`` de la entidad ``code`` propio de ``version``;
    ``None`` si no tiene fila o no tiene valor."""
    row = store.get(entity_key(code, param), version=version.uid, conn=conn)
    return None if row is None or row.value is None else str(row.value)


def _registry(project: Any, conn: sqlite3.Connection, version: Version) -> EntityRegistry:
    store = ParameterStore(project)
    entries: list[EntityEntry] = []
    for kind, (prefix, op_type) in _FAMILIES.items():
        codes = {code for (key,) in conn.execute(
            _PARAMETER_ROWS, (VERSION_SCOPE, version.uid, f"{prefix}.%")).fetchall()
            if (code := _segment_of(str(key), prefix)) is not None
            and code.startswith(f"{kind.prefix}-")}
        operations = _operations(conn, version, prefix, op_type)
        links = _links(conn, operations.values())

        for code in sorted(codes, key=_number):
            name = _text(store, conn, version, code, PlatformParam.NAME)
            if name is None or not name.strip():
                raise DesignError("des.entity_name_missing", obj=f"Entidad «{code}»",
                                  field=entity_key(code, PlatformParam.NAME), value=name)
            uid = operations.get(code)
            state, causes, retired = _deduce(conn, uid, links.get(uid, ()) if uid else ())
            entries.append(EntityEntry(
                EntityRecord(code, name, kind,
                             _text(store, conn, version, code, PlatformParam.START),
                             _text(store, conn, version, code, PlatformParam.SUPPORT), state),
                uid, causes, retired))
    return EntityRegistry(version.code, tuple(entries))


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
            links: Iterable[tuple[str, str, str, str]]
            ) -> tuple[EntityState, frozenset[Cause], tuple[str, ...]]:
    """El estado de una entidad con la operación ``operation`` (``None``: sin calcular), sus causas
    de obsolescencia y los datos descartados que consumió (véase :func:`registry`)."""
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
