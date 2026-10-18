# SPDX-License-Identifier: GPL-3.0-or-later
"""Inventario del proyecto: lo registrado, cargado o no en la vista, y su página filtrada (spec
010; RF-010-07; ADR-0025; plan 010 §5.3.1, A7 y D-15; con las versiones de la spec 009:
RF-009-20, RF-009-30, plan 009 §5.3.2 y A11).

:func:`read_inventory` lee de una vez, en una instantánea y sin escribir nada, las entradas
(``gb_input``), los datos (``gb_dataset``) en todos sus estados y, en un proyecto con versiones
(el esquema 3, spec 009), las versiones (``gb_version``) y sus revisiones (``gb_revision``),
cada uno con:

- su categoría (:class:`Category`), su uid, su nombre, su módulo, su tipo y su estado como los
  guarda el proyecto («current», «superseded»…; el de una versión, «VIGENTE»…, y el de una
  revisión, «open», «frozen» o «closed»). Una versión se llama «V01 · Definitiva» (su código y
  su título) y una revisión «V01.r2»; las dos son del módulo :data:`VERSION_MODULE`, de tipo
  :data:`VERSION_KIND` y :data:`REVISION_KIND`;
- su versión: el código de la versión de un dato de versión («V01»), el de una versión y el de
  la versión de una revisión; ``None`` («—»), lo del proyecto (las entradas, los datos del
  proyecto y todo en un proyecto del esquema 2 abierto en solo lectura, que no tiene versiones);
- si está obsoleto: un dato vivo con alguna causa en la caché ``gb_stale`` (como «! n
  obsoletos» de la 008);
- «entrada cambiada»: una entrada cambiada sin decidir (RF-008-10) y lo que depende de ella
  (``core.inputs.dependents``: lo importado y lo que se calculó a partir de ello);
- si se puede cargar en la vista: un dato vivo que no falta y que su módulo carga (lo dice
  ``loadable`` por su nombre); una entrada, una versión o una revisión, nunca;
- las marcas de una revisión (spec 009): «alterada», si su instantánea no coincide con lo
  congelado (RF-009-09), y «en curso», la abierta (RF-009-20);

con el contador de cambios de la cabecera de ``project.gpkg`` en ese momento
(:class:`InventorySnapshot`): si ya no es el de hoy, alguien escribió y la instantánea es vieja.

:func:`page` filtra la instantánea en Python (:class:`InventoryFilter`: categoría, tipo, estado
—«Vivos» por defecto, «Historia»…—, versión, presencia en la escena y texto, palabra a palabra y
sin distinguir mayúsculas ni tildes) y da como mucho :data:`ROW_LIMIT` filas por nombre, con el
total y cuántas quedan fuera («… y 19 600 más: afine el filtro», D-7). Las versiones y las
revisiones van por su número (V99 antes que V100; r2 antes que r10), cada versión antes de sus
revisiones; filtrar por una versión (su código o su uid) da la versión, sus revisiones y sus
datos. Una versión SUPERADO o DESCARTADO y una revisión cerrada son «Historia»; la VIGENTE,
«Vigentes»; una revisión alterada, «No se pueden usar» (RF-009-09); ningún filtro de tipo da
versiones ni revisiones.

La instantánea guarda cada elemento como una tupla de textos, booleanos y ``None``
(:attr:`InventorySnapshot.rows`), no como :class:`InventoryItem`: entre dos dibujos del panel
vive mucho tiempo con hasta 20 100 elementos, y esas tuplas el GC de Python deja de seguirlas,
mientras que 20 000 objetos provocarían una recolección completa de 25–50 ms en cualquier tic
de Blender (``docs/trampas.md`` §2; plan 010 §2.1). Python puro (ADR-0004).
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections.abc import Callable, Collection, Iterable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
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
from ..provenance.graph import versioned
from ..versions import read as versions_read
from ..versions.model import EDITABLE, RevisionState, VersionStatus, revision_label
from .state import _snapshot

__all__ = [
    "ALL",
    "NAMED_KINDS",
    "REVISION_KIND",
    "ROW_LIMIT",
    "VERSION_KIND",
    "VERSION_MODULE",
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
VERSION_KIND = "version"
"""El tipo de la fila de una versión (spec 009)."""
REVISION_KIND = "revision"
"""El tipo de la fila de una revisión (spec 009)."""
VERSION_MODULE = "core"
"""El módulo de las filas de las versiones y de las revisiones."""


class Category(StrEnum):
    """Qué es un elemento del inventario: una entrada o un dato (spec 010), una versión o una
    revisión (spec 009; la instantánea es la de su revisión congelada)."""

    INPUT = "INPUT"  # una entrada registrada (gb_input)
    DATASET = "DATASET"  # un dato del proyecto (gb_dataset)
    VERSION = "VERSION"  # una versión (gb_version), spec 009
    REVISION = "REVISION"  # una revisión de una versión (gb_revision), spec 009


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
_VERSION = str(Category.VERSION)
_REVISION = str(Category.REVISION)
_REGISTERED = frozenset({_INPUT, _DATASET})  # lo que tiene un tipo de dato
_NUMBERED = frozenset({_VERSION, _REVISION})  # lo que va por su número
_LIVE = {_INPUT: frozenset(str(status) for status in ACTIVE_STATUSES),
         _DATASET: frozenset(str(status) for status in LIVE_STATUSES),
         _VERSION: frozenset(str(status) for status in EDITABLE),
         _REVISION: frozenset({str(RevisionState.OPEN), str(RevisionState.FROZEN)})}
_HISTORY = {_INPUT: frozenset(str(status) for status in INACTIVE_STATUSES),
            _DATASET: frozenset(str(status) for status in FINAL_STATUSES),
            _VERSION: frozenset(str(status) for status in VersionStatus) - _LIVE[_VERSION],
            _REVISION: frozenset({str(RevisionState.CLOSED)})}
_UNUSABLE = frozenset(str(status) for status in UNUSABLE_STATUSES)
# «Vigentes»: las entradas y los datos vigentes (InputStatus.CURRENT es el mismo) y la versión
# VIGENTE; ninguna revisión.
_CURRENT = frozenset({str(DatasetStatus.CURRENT), str(VersionStatus.VIGENTE)})
_MISSING = str(DatasetStatus.MISSING)
_CHANGED = str(InputStatus.CHANGED)
_OPEN = str(RevisionState.OPEN)
# Posiciones en cada fila de InventorySnapshot.rows: los campos de InventoryItem, en su orden,
# y al final el nombre como se compara con el texto (fold).
(CATEGORY, UID, NAME, MODULE, KIND, STATUS, VERSION, STALE, INPUT_CHANGED, LOADABLE, ALTERED,
 IN_PROGRESS, KEY) = range(13)
_FIELDS = KEY
_FIELDS_010 = ALTERED
"""Los valores de una fila como las de la 010, sin las marcas de la 009 (se completa sin
ellas)."""
_NUMBER = re.compile(r"[0-9]+")
_PAD = 9
"""Las cifras con que se comparan los números de las versiones y de las revisiones."""

_INPUTS = "SELECT uid, name, module, kind, status FROM gb_input ORDER BY fid"
_FILE = "SELECT file FROM pragma_database_list WHERE name = 'main'"
_DATASETS = "SELECT uid, name, module, kind, status FROM gb_dataset ORDER BY fid"
_VERSIONED_DATASETS = (
    "SELECT uid, name, module, kind, status, version_uid FROM gb_dataset ORDER BY fid"
)
_REVISIONS = "SELECT uid, version_uid, number, state, altered_at FROM gb_revision ORDER BY fid"
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
    """Un elemento del inventario: véase el módulo. ``status`` es el del proyecto (el de una
    entrada o un dato, en minúsculas; el de una versión, «VIGENTE»…); ``version``, el código
    de su versión o ``None`` («—», lo del proyecto); ``altered`` e ``in_progress``, las marcas
    de una revisión (spec 009: «alterada» y «en curso»)."""

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
    altered: bool = False
    in_progress: bool = False

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
                bool(self.input_changed), bool(self.loadable), bool(self.altered),
                bool(self.in_progress))


def _keyed(row: object) -> tuple[Any, ...]:
    """La fila ``row`` (los campos de :class:`InventoryItem` y, si ya la tiene, su clave) con
    su nombre como se compara al final. Una fila como las de la 010 (sus diez valores, sin las
    marcas de la 009) se completa sin marcas."""
    if not isinstance(row, tuple) or len(row) not in (_FIELDS_010, _FIELDS, _FIELDS + 1):
        raise ValueError(f"una fila del inventario es una tupla de {_FIELDS} valores (los de "
                         f"InventoryItem; {_FIELDS_010}, sin las marcas de una revisión), no "
                         f"{row!r}")
    if len(row) == _FIELDS_010:
        row = (*row, False, False)
    if row[CATEGORY] not in _LIVE:
        raise ValueError(f"categoría desconocida en el inventario: {row[CATEGORY]!r}")
    if not isinstance(row[NAME], str):
        raise TypeError(f"el nombre de un elemento del inventario es un texto, no {row[NAME]!r}")
    return (*row[:_FIELDS], fold(row[NAME]))


def _natural(text: str) -> str:
    """``text`` con cada número escrito con :data:`_PAD` cifras («v01.r10» →
    «v000000001.r000000010»): así se ordenan las versiones y las revisiones por su número."""
    return _NUMBER.sub(lambda found: found.group().zfill(_PAD), text)


def _order(row: tuple[Any, ...]) -> tuple[str, str]:
    """Cómo se ordena una fila: por su nombre como se compara (el de una versión o una
    revisión, con sus números de :data:`_PAD` cifras) y, con el mismo, por su nombre."""
    key = row[KEY]
    return (_natural(key) if row[CATEGORY] in _NUMBERED else key), row[NAME]


@dataclass(frozen=True)
class InventorySnapshot:
    """Lo registrado en el proyecto en una instantánea: ``rows``, una tupla por elemento con
    los campos de :class:`InventoryItem`, en su orden, y al final su nombre como se compara
    con el texto (:func:`fold`; al crearla se le añade), por nombre sin mayúsculas ni tildes
    (y, con el mismo nombre, en el orden en que llegaron: el de registro; las versiones y las
    revisiones, por su número); ``change_counter``, el contador de cambios de la cabecera de
    ``project.gpkg`` al leerlo."""

    rows: tuple[tuple[Any, ...], ...]
    change_counter: int
    _version_rows: tuple[tuple[Any, ...], ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if isinstance(self.change_counter, bool) or not isinstance(self.change_counter, int):
            raise TypeError(f"el contador de cambios es un entero, no {self.change_counter!r}")
        rows = [_keyed(row) for row in self.rows]
        rows.sort(key=_order)  # estable: con el mismo, como llegan
        object.__setattr__(self, "rows", tuple(rows))
        object.__setattr__(self, "_version_rows",
                           tuple(row for row in rows if row[CATEGORY] == _VERSION))

    @classmethod
    def of(cls, items: Iterable[InventoryItem], change_counter: int) -> InventorySnapshot:
        """La instantánea de unos elementos ya hechos (en el orden en que llegan)."""
        return cls(tuple(item.row() for item in items), change_counter)

    @property
    def items(self) -> tuple[InventoryItem, ...]:
        """Todos los elementos, por nombre (se crean al pedirlos: con muchos, mejor
        :func:`page`)."""
        return tuple(InventoryItem.from_row(row) for row in self.rows)

    @property
    def versions(self) -> tuple[InventoryItem, ...]:
        """Las versiones, por su número (V01… V99, V100): las del filtro de versión."""
        return tuple(InventoryItem.from_row(row) for row in self._version_rows)

    def version_codes(self) -> Mapping[str, str]:
        """El código de cada versión por su uid."""
        return {row[UID]: row[VERSION] for row in self._version_rows}

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


def _versions(conn: sqlite3.Connection) -> tuple[list[tuple[Any, ...]], dict[str, str]]:
    """Las filas de las versiones y de sus revisiones (spec 009) y el código de cada versión
    por su uid."""
    found = versions_read.versions(conn)
    codes = {version.uid: version.code for version in found}
    rows: list[tuple[Any, ...]] = [
        (_VERSION, str(version.uid), str(version.label), VERSION_MODULE, VERSION_KIND,
         str(version.status), str(version.code), False, False, False, False, False)
        for version in found
    ]
    for uid, version_uid, number, state, altered_at in conn.execute(_REVISIONS):
        code = codes.get(str(version_uid), str(version_uid))
        rows.append((_REVISION, str(uid), revision_label(code, int(number)), VERSION_MODULE,
                     REVISION_KIND, str(state), code, False, False, False,
                     altered_at is not None, state == _OPEN))
    return rows, codes


def read_inventory(project: InventoryProject, *, loadable: Callable[[str], bool],
                   conn: sqlite3.Connection | None = None) -> InventorySnapshot:
    """El inventario del proyecto ``project`` (véase el módulo), leído en una instantánea (la
    de ``conn``, una conexión de lectura de quien llama, o una nueva) sin escribir nada.
    ``loadable(nombre)`` dice si el módulo de un dato lo puede cargar en la vista (en ``bl``,
    si tiene cargador). Un proyecto sin versiones (el esquema 2, abierto en solo lectura) se
    lee como en la 010: sin versiones ni revisiones, y nada con versión."""
    if not callable(loadable):
        raise TypeError(f"loadable es una función del nombre de un dato, no {loadable!r}")
    with _snapshot(project, conn) as reading:
        input_rows = reading.execute(_INPUTS).fetchall()
        counter = _counter(reading)
        if versioned(reading):
            dataset_rows = reading.execute(_VERSIONED_DATASETS).fetchall()
            rows, codes = _versions(reading)
        else:
            dataset_rows = [(*row, "") for row in reading.execute(_DATASETS)]
            rows, codes = [], {}
        stale = {str(uid) for (uid,) in reading.execute(_STALE)}
        changed_inputs = [str(row[0]) for row in input_rows if row[4] == _CHANGED]
        affected = _changed_dependents(reading, changed_inputs)
    rows += [
        (_INPUT, str(uid), str(name), str(module), str(kind), str(status), None, False,
         status == _CHANGED, False, False, False)
        for uid, name, module, kind, status in input_rows
    ]
    live = _LIVE[_DATASET]
    for uid, name, module, kind, status, version_uid in dataset_rows:
        alive = status in live
        version = codes.get(str(version_uid), str(version_uid)) if version_uid else None
        rows.append((_DATASET, str(uid), str(name), str(module), str(kind), str(status),
                     version, alive and uid in stale, uid in affected,
                     alive and status != _MISSING and bool(loadable(name)), False, False))
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
    VERSION = "VERSION"
    REVISION = "REVISION"


@dataclass(frozen=True)
class InventoryFilter:
    """Lo que se pide al inventario (véase :func:`page`): ``category`` («ALL» o una
    :class:`Category`), ``kind`` (:class:`KindFilter`), ``status`` (:class:`StatusFilter`;
    «LIVE» por defecto), ``version`` («ALL», :data:`VERSION_NONE` o una versión, por su código
    o por su uid),
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
            return lambda row: row[STATUS] in _CURRENT
        case StatusFilter.STALE:
            return lambda row: row[STALE]
        case StatusFilter.INPUT_CHANGED:
            return lambda row: row[INPUT_CHANGED]
        case StatusFilter.UNUSABLE:  # también una revisión alterada (RF-009-09: no se usa)
            return lambda row: (row[CATEGORY] == _DATASET and row[STATUS] in _UNUSABLE
                                or row[ALTERED])
        case StatusFilter.HISTORY:
            return lambda row: row[STATUS] in _HISTORY[row[CATEGORY]]
    return None


def _checks(wanted: InventoryFilter, in_scene: Collection[str],
            codes: Mapping[str, str]) -> list[Check]:
    checks: list[Check] = []
    if wanted.category != ALL:
        category = str(wanted.category)
        checks.append(lambda row: row[CATEGORY] == category)
    if wanted.kind is KindFilter.OTHER:  # de una entrada o un dato: ni versiones ni revisiones
        checks.append(lambda row: row[CATEGORY] in _REGISTERED and row[KIND] not in _NAMED)
    elif wanted.kind != ALL:
        kind = NAMED_KINDS[wanted.kind]
        checks.append(lambda row: row[KIND] == kind)
    by_status = _status_check(wanted.status)
    if by_status is not None:
        checks.append(by_status)
    if wanted.version == VERSION_NONE:
        checks.append(lambda row: row[VERSION] is None)
    elif wanted.version != ALL:
        version = codes.get(wanted.version, wanted.version)  # su uid o su código
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
    for check in _checks(wanted, in_scene, snapshot.version_codes()):
        found = filter(check, found)  # un filtro tras otro, sin un bucle de Python por fila
    for word in fold(wanted.text).split():
        found = filter(lambda row, word=word: word in row[KEY], found)
    rest = iter(found)
    shown = list(islice(rest, limit))
    total = len(shown) + len(list(rest))
    return InventoryPage(tuple(InventoryItem.from_row(row) for row in shown), total,
                         total - len(shown))
