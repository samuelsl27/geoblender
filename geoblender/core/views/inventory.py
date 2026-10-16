# SPDX-License-Identifier: GPL-3.0-or-later
"""Inventario del proyecto: lo registrado, cargado o no en la vista, y su página filtrada (spec
010; RF-010-07; ADR-0025; plan 010 §5.3.1, A7 y D-15).

:func:`read_inventory` lee de una vez, en una instantánea y sin escribir nada, las entradas
(``gb_input``) y los datos (``gb_dataset``) en todos sus estados, cada uno con:

- su categoría (:class:`Category`), su uid, su nombre, su módulo, su tipo y su estado como los
  guarda el proyecto («current», «superseded»…);
- su versión: ``None`` («—») hasta que la spec 009 dé las versiones;
- si está obsoleto: un dato vivo con alguna causa en la caché ``gb_stale`` (como «! n
  obsoletos» de la 008);
- «entrada cambiada»: una entrada cambiada sin decidir (RF-008-10) y lo que depende de ella
  (``core.inputs.dependents``: lo importado y lo que se calculó a partir de ello);
- si se puede cargar en la vista: un dato vivo que no falta y que su módulo carga (lo dice
  ``loadable`` por su nombre); una entrada nunca;

con el contador de cambios de la cabecera de ``project.gpkg`` en ese momento
(:class:`InventorySnapshot`): si ya no es el de hoy, alguien escribió y la instantánea es vieja.

:func:`page` filtra la instantánea en Python (:class:`InventoryFilter`: categoría, tipo, estado
—«Vivos» por defecto, «Historia»…—, versión, presencia en la escena y texto, palabra a palabra y
sin distinguir mayúsculas ni tildes) y da como mucho :data:`ROW_LIMIT` filas por nombre, con el
total y cuántas quedan fuera («… y 19 600 más: afine el filtro», D-7).

La instantánea guarda cada elemento como una tupla de textos, booleanos y ``None``
(:attr:`InventorySnapshot.rows`), no como :class:`InventoryItem`: entre dos dibujos del panel
vive mucho tiempo con hasta 20 100 elementos, y esas tuplas el GC de Python deja de seguirlas,
mientras que 20 000 objetos provocarían una recolección completa de 25–50 ms en cualquier tic
de Blender (``docs/trampas.md`` §2; plan 010 §2.1). Python puro (ADR-0004).
"""

from __future__ import annotations

import sqlite3
import unicodedata
from collections.abc import Callable, Collection, Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
from itertools import islice
from pathlib import Path
from typing import Any, Protocol

from ..datasets.external import UNUSABLE_STATUSES
from ..datasets.model import FINAL_STATUSES, LIVE_STATUSES, DatasetStatus
from ..gpkg.header import read_header
from ..inputs import registry as input_registry
from ..inputs.check import dependents
from ..inputs.model import ACTIVE_STATUSES, INACTIVE_STATUSES, InputStatus
from .state import _snapshot

__all__ = [
    "ALL",
    "NAMED_KINDS",
    "ROW_LIMIT",
    "VERSION_NONE",
    "Category",
    "InventoryFilter",
    "InventoryItem",
    "InventoryPage",
    "InventoryProject",
    "InventorySnapshot",
    "KindFilter",
    "PresenceFilter",
    "StatusFilter",
    "fold",
    "page",
    "read_inventory",
]

ROW_LIMIT = 500
"""Cuántas filas da como mucho una página del inventario (RF-010-07, D-7)."""
ALL = "ALL"
"""El valor de un filtro que no filtra."""
VERSION_NONE = "NONE"
"""El filtro de versión «—»: lo que no tiene versión."""


class Category(StrEnum):
    """Qué es un elemento del inventario (la spec 009 añadirá versiones, revisiones e
    instantáneas)."""

    INPUT = "INPUT"  # una entrada registrada (gb_input)
    DATASET = "DATASET"  # un dato del proyecto (gb_dataset)


class KindFilter(StrEnum):
    """El filtro «Tipo»: los tipos con nombre y «Otros», lo demás; vale para entradas y datos
    (``Category`` filtra las entradas)."""

    ALL = "ALL"
    RASTER = "RASTER"  # rejillas
    MESH = "MESH"  # mallas
    VECTOR = "VECTOR"  # vectoriales
    TABLE = "TABLE"  # tablas
    DRILLHOLES = "DRILLHOLES"  # sondeos
    OTHER = "OTHER"  # otros: nubes de puntos, modelos de bloques, documentos…


class StatusFilter(StrEnum):
    """El filtro «Estado» (D-15)."""

    LIVE = "LIVE"  # vivos: entradas activas y datos vivos (por defecto)
    CURRENT = "CURRENT"  # vigentes
    STALE = "STALE"  # obsoletos
    INPUT_CHANGED = "INPUT_CHANGED"  # entrada cambiada sin decidir y lo que depende de ella
    UNUSABLE = "UNUSABLE"  # no se pueden usar: datos que faltan, bloqueados o dañados
    HISTORY = "HISTORY"  # historia: lo sustituido y lo descartado
    ALL = "ALL"  # todo


class PresenceFilter(StrEnum):
    """El filtro «En la escena»."""

    ALL = "ALL"
    IN = "IN"  # cargado en la escena (nunca una entrada)
    OUT = "OUT"  # no cargado


NAMED_KINDS: dict[KindFilter, str] = {
    KindFilter.RASTER: "raster",
    KindFilter.MESH: "mesh",
    KindFilter.VECTOR: "vector",
    KindFilter.TABLE: "table",
    KindFilter.DRILLHOLES: "drillholes",
}
"""El tipo de ``gb_dataset.kind`` y ``gb_input.kind`` de cada filtro con nombre."""
_NAMED = frozenset(NAMED_KINDS.values())
_INPUT = str(Category.INPUT)
_DATASET = str(Category.DATASET)
_LIVE = {_INPUT: frozenset(str(status) for status in ACTIVE_STATUSES),
         _DATASET: frozenset(str(status) for status in LIVE_STATUSES)}
_HISTORY = {_INPUT: frozenset(str(status) for status in INACTIVE_STATUSES),
            _DATASET: frozenset(str(status) for status in FINAL_STATUSES)}
_UNUSABLE = frozenset(str(status) for status in UNUSABLE_STATUSES)
_CURRENT = str(DatasetStatus.CURRENT)  # el de las entradas (InputStatus.CURRENT) es el mismo
_MISSING = str(DatasetStatus.MISSING)
_CHANGED = str(InputStatus.CHANGED)
# Posiciones en cada fila de InventorySnapshot.rows: los campos de InventoryItem, en su orden,
# y al final el nombre como se compara con el texto (fold).
CATEGORY, UID, NAME, MODULE, KIND, STATUS, VERSION, STALE, INPUT_CHANGED, LOADABLE, KEY = (
    range(11))
_FIELDS = KEY

_INPUTS = "SELECT uid, name, module, kind, status FROM gb_input ORDER BY fid"
_FILE = "SELECT file FROM pragma_database_list WHERE name = 'main'"
_DATASETS = "SELECT uid, name, module, kind, status FROM gb_dataset ORDER BY fid"
_STALE = "SELECT DISTINCT item_uid FROM gb_stale WHERE item_kind = 'dataset'"


def fold(text: str) -> str:
    """``text`` sin mayúsculas ni tildes («Topografía Norte» → «topografia norte»): como se
    comparan los nombres con el texto del filtro."""
    if not text.isascii():
        text = "".join(char for char in unicodedata.normalize("NFKD", text)
                       if not unicodedata.combining(char))
    return text.casefold()


@dataclass(frozen=True)
class InventoryItem:
    """Un elemento del inventario: véase el módulo. ``status`` es el del proyecto, en
    minúsculas; ``version``, ``None`` mientras no haya versiones («—», spec 009)."""

    category: Category
    uid: str
    name: str
    module: str
    kind: str
    status: str
    version: str | None
    stale: bool
    input_changed: bool
    loadable: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "category", Category(self.category))

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> InventoryItem:
        """El elemento de una fila de :attr:`InventorySnapshot.rows`."""
        return cls(*row[:_FIELDS])

    def row(self) -> tuple[Any, ...]:
        """La fila que guarda la instantánea: tupla de textos exactos (sin ``StrEnum``, que el
        GC seguiría), booleanos y ``None``."""
        return (str(self.category), str(self.uid), str(self.name), str(self.module),
                str(self.kind), str(self.status),
                None if self.version is None else str(self.version), bool(self.stale),
                bool(self.input_changed), bool(self.loadable))


def _keyed(row: object) -> tuple[Any, ...]:
    """La fila ``row`` (los campos de :class:`InventoryItem` y, si ya la tiene, su clave) con
    su nombre como se compara al final."""
    if not isinstance(row, tuple) or len(row) not in (_FIELDS, _FIELDS + 1):
        raise ValueError(f"una fila del inventario es una tupla de {_FIELDS} valores (los de "
                         f"InventoryItem), no {row!r}")
    if row[CATEGORY] not in _LIVE:
        raise ValueError(f"categoría desconocida en el inventario: {row[CATEGORY]!r}")
    if not isinstance(row[NAME], str):
        raise TypeError(f"el nombre de un elemento del inventario es un texto, no {row[NAME]!r}")
    return (*row[:_FIELDS], fold(row[NAME]))


@dataclass(frozen=True)
class InventorySnapshot:
    """Lo registrado en el proyecto en una instantánea: ``rows``, una tupla por elemento con
    los campos de :class:`InventoryItem`, en su orden, y al final su nombre como se compara
    con el texto (:func:`fold`; al crearla se le añade), por nombre sin mayúsculas ni tildes
    (y, con el mismo nombre, en el orden en que llegaron: el de registro); ``change_counter``,
    el contador de cambios de la cabecera de ``project.gpkg`` al leerlo."""

    rows: tuple[tuple[Any, ...], ...]
    change_counter: int

    def __post_init__(self) -> None:
        if isinstance(self.change_counter, bool) or not isinstance(self.change_counter, int):
            raise TypeError(f"el contador de cambios es un entero, no {self.change_counter!r}")
        rows = [_keyed(row) for row in self.rows]
        rows.sort(key=lambda row: (row[KEY], row[NAME]))  # estable: con el mismo, como llegan
        object.__setattr__(self, "rows", tuple(rows))

    @classmethod
    def of(cls, items: Iterable[InventoryItem], change_counter: int) -> InventorySnapshot:
        """La instantánea de unos elementos ya hechos (en el orden en que llegan)."""
        return cls(tuple(item.row() for item in items), change_counter)

    @property
    def items(self) -> tuple[InventoryItem, ...]:
        """Todos los elementos, por nombre (se crean al pedirlos: con muchos, mejor
        :func:`page`)."""
        return tuple(InventoryItem.from_row(row) for row in self.rows)

    def __len__(self) -> int:
        return len(self.rows)


class InventoryProject(Protocol):
    """Lo que se usa del proyecto: una conexión de lectura."""

    def read(self) -> AbstractContextManager[sqlite3.Connection]: ...


def _counter(conn: sqlite3.Connection) -> int:
    """El contador de cambios de la cabecera del fichero de ``conn``, leído ya dentro de la
    transacción (con su lectura en curso nadie confirma nada: es el de la instantánea)."""
    found = conn.execute(_FILE).fetchone()
    return read_header(Path(str(found[0]))).change_counter


def _changed_dependents(conn: sqlite3.Connection, changed: Iterable[str]) -> set[str]:
    """Los datos vivos que dependen de las entradas cambiadas sin decidir ``changed``."""
    found: set[str] = set()
    for uid in changed:
        record = input_registry.get(conn, uid)
        if record is not None:
            found.update(item.uid for item in dependents(conn, record).datasets)
    return found


def read_inventory(project: InventoryProject, *, loadable: Callable[[str], bool],
                   conn: sqlite3.Connection | None = None) -> InventorySnapshot:
    """El inventario del proyecto ``project`` (véase el módulo), leído en una instantánea (la
    de ``conn``, una conexión de lectura de quien llama, o una nueva) sin escribir nada.
    ``loadable(nombre)`` dice si el módulo de un dato lo puede cargar en la vista (en ``bl``,
    si tiene cargador)."""
    if not callable(loadable):
        raise TypeError(f"loadable es una función del nombre de un dato, no {loadable!r}")
    with _snapshot(project, conn) as reading:
        input_rows = reading.execute(_INPUTS).fetchall()
        counter = _counter(reading)
        dataset_rows = reading.execute(_DATASETS).fetchall()
        stale = {str(uid) for (uid,) in reading.execute(_STALE)}
        changed_inputs = [str(row[0]) for row in input_rows if row[4] == _CHANGED]
        affected = _changed_dependents(reading, changed_inputs)
    rows: list[tuple[Any, ...]] = [
        (_INPUT, str(uid), str(name), str(module), str(kind), str(status), None, False,
         status == _CHANGED, False)
        for uid, name, module, kind, status in input_rows
    ]
    live = _LIVE[_DATASET]
    for uid, name, module, kind, status in dataset_rows:
        alive = status in live
        rows.append((_DATASET, str(uid), str(name), str(module), str(kind), str(status), None,
                     alive and uid in stale, uid in affected,
                     alive and status != _MISSING and bool(loadable(name))))
    return InventorySnapshot(tuple(rows), counter)


def _choice(kind: type[StrEnum], value: object, what: str) -> Any:
    if not isinstance(value, str):
        raise TypeError(f"el filtro «{what}» es un texto, no {value!r}")
    try:
        return kind(value)
    except ValueError:
        raise ValueError(f"el filtro «{what}» es uno de {', '.join(kind)}, no "
                         f"{value!r}") from None


class _CategoryFilter(StrEnum):
    ALL = "ALL"
    INPUT = "INPUT"
    DATASET = "DATASET"


@dataclass(frozen=True)
class InventoryFilter:
    """Lo que se pide al inventario (véase :func:`page`): ``category`` («ALL» o una
    :class:`Category`), ``kind`` (:class:`KindFilter`), ``status`` (:class:`StatusFilter`;
    «LIVE» por defecto), ``version`` («ALL», :data:`VERSION_NONE` o una versión),
    ``presence`` (:class:`PresenceFilter`) y ``text`` (palabras que tiene que tener el nombre,
    sin distinguir mayúsculas ni tildes; vacío, todo)."""

    category: str = ALL
    kind: str = ALL
    status: str = StatusFilter.LIVE
    version: str = ALL
    presence: str = ALL
    text: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "category",
                           _choice(_CategoryFilter, self.category, "categoría"))
        object.__setattr__(self, "kind", _choice(KindFilter, self.kind, "tipo"))
        object.__setattr__(self, "status", _choice(StatusFilter, self.status, "estado"))
        object.__setattr__(self, "presence",
                           _choice(PresenceFilter, self.presence, "en la escena"))
        if not isinstance(self.version, str):
            raise TypeError(f"el filtro «versión» es un texto, no {self.version!r}")
        if not self.version.strip():
            raise ValueError("el filtro «versión» no puede estar vacío: «ALL» para todas")
        if not isinstance(self.text, str):
            raise TypeError(f"el texto del filtro es un texto, no {self.text!r}")


@dataclass(frozen=True)
class InventoryPage:
    """Una página del inventario: ``items``, como mucho el límite, por nombre; ``total``, lo que
    cumple el filtro; ``more``, lo que queda fuera de la página («… y n más»)."""

    items: tuple[InventoryItem, ...]
    total: int
    more: int


Check = Callable[[tuple[Any, ...]], bool]


def _status_check(status: StatusFilter) -> Check | None:
    match status:
        case StatusFilter.LIVE:
            return lambda row: row[STATUS] in _LIVE[row[CATEGORY]]
        case StatusFilter.CURRENT:
            return lambda row: row[STATUS] == _CURRENT
        case StatusFilter.STALE:
            return lambda row: row[STALE]
        case StatusFilter.INPUT_CHANGED:
            return lambda row: row[INPUT_CHANGED]
        case StatusFilter.UNUSABLE:
            return lambda row: row[CATEGORY] == _DATASET and row[STATUS] in _UNUSABLE
        case StatusFilter.HISTORY:
            return lambda row: row[STATUS] in _HISTORY[row[CATEGORY]]
    return None


def _checks(wanted: InventoryFilter, in_scene: Collection[str]) -> list[Check]:
    checks: list[Check] = []
    if wanted.category != ALL:
        category = str(wanted.category)
        checks.append(lambda row: row[CATEGORY] == category)
    if wanted.kind is KindFilter.OTHER:
        checks.append(lambda row: row[KIND] not in _NAMED)
    elif wanted.kind != ALL:
        kind = NAMED_KINDS[wanted.kind]
        checks.append(lambda row: row[KIND] == kind)
    by_status = _status_check(wanted.status)
    if by_status is not None:
        checks.append(by_status)
    if wanted.version == VERSION_NONE:
        checks.append(lambda row: row[VERSION] is None)
    elif wanted.version != ALL:
        version = wanted.version
        checks.append(lambda row: row[VERSION] == version)
    if wanted.presence != ALL:
        scene = frozenset(in_scene)
        inside = wanted.presence is PresenceFilter.IN
        checks.append(lambda row: (row[CATEGORY] == _DATASET and row[UID] in scene) is inside)
    return checks


def page(snapshot: InventorySnapshot, wanted: InventoryFilter, in_scene: Collection[str], *,
         limit: int = ROW_LIMIT) -> InventoryPage:
    """La página de ``snapshot`` con el filtro ``wanted``: lo que lo cumple, por nombre, como
    mucho ``limit`` filas, con el total y cuántas quedan fuera. ``in_scene``, los uid de los
    datos cargados en la escena (para el filtro «En la escena»). No lee el proyecto."""
    if not isinstance(snapshot, InventorySnapshot):
        raise TypeError(f"el inventario es un InventorySnapshot, no {snapshot!r}")
    if not isinstance(wanted, InventoryFilter):
        raise TypeError(f"el filtro es un InventoryFilter, no {wanted!r}")
    if isinstance(in_scene, str) or not isinstance(in_scene, Collection):
        raise TypeError(f"lo cargado en la escena es una colección de uid, no {in_scene!r}")
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError(f"el límite de filas es un entero, no {limit!r}")
    if limit < 0:
        raise ValueError(f"el límite de filas no puede ser negativo: {limit}")
    found: Iterable[tuple[Any, ...]] = snapshot.rows
    for check in _checks(wanted, in_scene):
        found = filter(check, found)  # un filtro tras otro, sin un bucle de Python por fila
    for word in fold(wanted.text).split():
        found = filter(lambda row, word=word: word in row[KEY], found)
    rest = iter(found)
    shown = list(islice(rest, limit))
    total = len(shown) + len(list(rest))
    return InventoryPage(tuple(InventoryItem.from_row(row) for row in shown), total,
                         total - len(shown))
