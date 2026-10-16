# SPDX-License-Identifier: GPL-3.0-or-later
"""Estado de cada dato cargado en la vista frente al proyecto y plan de Refrescar (spec 010;
RF-010-01, RF-010-02, RF-010-03; ADR-0006, ADR-0024, ADR-0025; plan 010 §5.3.1, A1, D-9 y D-11).

Cada objeto de un dato cargado en la escena dice con qué se cargó (RF-006-29): el hash de
contenido (``gbch/1``), el GeoOrigin («X0 Y0 Z0», en metros enteros; vacío en lo cargado antes de
la 010), el estado del dato y si estaba obsoleto. ``bl`` agrupa los objetos por dato
(:class:`LoadedItem`) y :func:`view_states` decide de cada uno, frente a lo que dice hoy el
proyecto (:class:`ItemState`, algoritmo A1 del plan):

1. de otro proyecto o que el proyecto no tiene: sin respaldo (``UNBACKED``);
2. descartado: sin respaldo; sustituido (lo importado de una entrada actualizada): con sucesor
   vivo (``core.datasets.successor``), se carga el sucesor en su lugar (``REPLACED``); sin él,
   sin respaldo;
3. que falta (su fichero o su tabla, RF-008-57): ``MISSING``; se marca «FALTA» y no se puede
   volver a cargar (D-11);
4. vivo (vigente, bloqueado o dañado): no al día (``OUTDATED``) si alguno de sus objetos se cargó
   con otro contenido (también lo que deja Ctrl+Z), con otro GeoOrigin anotado o, sin GeoOrigin
   anotado, con la vista desfasada (RF-002-29; D-9); si no, basta con poner al día su estado o
   su marca de obsoleto (``RESTATE``) si no son los de hoy; si no, al día (``CURRENT``).

Lo lee todo en una instantánea (``BEGIN`` … ``ROLLBACK``, la de la conexión de quien llama si ya
está en una transacción), por trozos de :data:`CHUNK` uid, y no escribe nada en el proyecto (spec
§11). :func:`refresh_plan` dice qué hace Refrescar (F5) y :func:`pending`, cuántos datos no están
al día (el control 7 y el aviso al abrir el proyecto). Python puro (ADR-0004).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Collection, Iterable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from ..datasets import registry as dataset_registry
from ..datasets.model import RECORD_COLUMNS, DatasetRecord, DatasetStatus
from ..errors import ValidationError
from ..georef.origin import GeoOrigin

__all__ = [
    "CHUNK",
    "PENDING_STATES",
    "ItemState",
    "ItemView",
    "LoadedItem",
    "RefreshPlan",
    "origin_text",
    "pending",
    "refresh_plan",
    "view_states",
]

CHUNK = 500
"""Cuántos uid lee cada consulta (``IN (…)``) como mucho."""
AMBIGUOUS_SUCCESSOR = "core.dataset_successor_ambiguous"
"""El error de ``core.datasets.successor`` cuando no se sabe cuál es el sucesor."""


class ItemState(StrEnum):
    """El estado de un dato cargado frente al proyecto (los tres primeros nombres son los de
    ``Object.geoblender.view_state``)."""

    CURRENT = "CURRENT"  # al día
    RESTATE = "RESTATE"  # mismo contenido, otro estado u otra marca de obsoleto: sin recargar
    OUTDATED = "OUTDATED"  # «no al día»: otro contenido (también tras Ctrl+Z) u otro GeoOrigin
    REPLACED = "REPLACED"  # lo importado de una entrada sustituida: se carga su sucesor vivo
    UNBACKED = "UNBACKED"  # «sin respaldo en el proyecto»: descartado, sustituido sin sucesor
    #                       vivo, que el proyecto no tiene o de otro proyecto
    MISSING = "MISSING"  # su fichero o su tabla faltan (RF-008-57): «FALTA», no se recarga


PENDING_STATES: frozenset[ItemState] = frozenset({ItemState.OUTDATED, ItemState.REPLACED})
"""Lo que no está al día y Refrescar vuelve a cargar: lo que cuenta el control 7."""
_TARGETED = frozenset({ItemState.CURRENT, ItemState.RESTATE, ItemState.OUTDATED})
_DATASETS = f"SELECT {', '.join(RECORD_COLUMNS)} FROM gb_dataset WHERE uid IN ({{marks}})"
_STALE = ("SELECT DISTINCT item_uid FROM gb_stale WHERE item_kind = 'dataset' "
          "AND item_uid IN ({marks})")


class ReadableProject(Protocol):
    """Lo que se usa del proyecto: una conexión de lectura."""

    def read(self) -> AbstractContextManager[sqlite3.Connection]: ...


def _texts(values: Iterable[str], what: str) -> frozenset[str]:
    if isinstance(values, str):
        raise TypeError(f"{what}: un conjunto de textos, no el texto {values!r}")
    found = frozenset(values)
    for value in found:
        if not isinstance(value, str):
            raise TypeError(f"{what}: cada valor es un texto, no {value!r}")
    return found


def _flags(values: Iterable[bool], what: str) -> frozenset[bool]:
    found = frozenset(values)
    for value in found:
        if not isinstance(value, bool):
            raise TypeError(f"{what}: cada valor es verdadero o falso, no {value!r}")
    return found


def _origin_words(text: str) -> tuple[str, ...]:
    return tuple(text.split())


@dataclass(frozen=True)
class LoadedItem:
    """Lo que dicen los objetos de un dato cargado en la escena (``bl`` los agrupa por dato):

    - ``dataset_uid`` y ``project_uid``: el dato y el proyecto de los que se cargaron;
    - ``contents``: los hashes de contenido con que se cargaron;
    - ``origins``: los GeoOrigin con que se cargaron, como texto «X0 Y0 Z0»
      (:func:`origin_text`; se guardan sin los espacios de más); ``""``, sin anotar (lo cargado
      antes de la 010);
    - ``statuses``: los estados del dato al cargarlos (``DatasetStatus``; se guardan en
      minúsculas, también los «CURRENT»… del ``EnumProperty`` de ``Object.geoblender``);
    - ``stale``: si estaba obsoleto al cargarlos (o al ponerlos al día por última vez).

    Cualquier iterable vale para los cuatro conjuntos."""

    dataset_uid: str
    project_uid: str
    contents: frozenset[str]
    origins: frozenset[str]
    statuses: frozenset[str]
    stale: frozenset[bool]

    def __post_init__(self) -> None:
        for name in ("dataset_uid", "project_uid"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(f"{name} de un dato cargado es un texto, no {value!r}")
        if not self.dataset_uid:
            raise ValueError("un dato cargado se indica por su uid, que no puede estar vacío")
        object.__setattr__(self, "contents", _texts(self.contents, "contents"))
        object.__setattr__(self, "origins", frozenset(
            " ".join(_origin_words(text)) for text in _texts(self.origins, "origins")))
        object.__setattr__(self, "statuses", frozenset(
            text.lower() for text in _texts(self.statuses, "statuses")))
        object.__setattr__(self, "stale", _flags(self.stale, "stale"))


@dataclass(frozen=True)
class ItemView:
    """El estado de un dato cargado frente al proyecto: ``record``, su registro de hoy
    (``None`` si es de otro proyecto o el proyecto no lo tiene); ``stale``, si está obsoleto hoy
    según la caché ``gb_stale`` (solo un dato vivo puede estarlo); ``successor``, el dato vivo
    que lo sustituye (solo en ``REPLACED``)."""

    uid: str
    state: ItemState
    record: DatasetRecord | None
    stale: bool
    successor: DatasetRecord | None

    def target_uid(self) -> str | None:
        """Lo que se carga en su lugar: su sucesor si está sustituido, él mismo si está vivo y
        se puede cargar; ``None`` si no hay nada que cargar (sin respaldo o que falta)."""
        if self.state is ItemState.REPLACED and self.successor is not None:
            return self.successor.uid
        return self.uid if self.state in _TARGETED else None


def origin_text(origin: GeoOrigin) -> str:
    """El GeoOrigin como lo anota cada objeto cargado: «X0 Y0 Z0» en metros enteros
    (``"700000 4400000 0"``), como el ``geoorigin`` del ancla de la escena."""
    if not isinstance(origin, GeoOrigin):
        raise TypeError(f"el GeoOrigin del proyecto es un GeoOrigin, no {origin!r}")
    return " ".join(str(value) for value in origin.as_tuple())


@contextmanager
def _snapshot(project: ReadableProject,
              conn: sqlite3.Connection | None) -> Iterator[sqlite3.Connection]:
    """Una conexión de lectura (la de quien llama o una nueva) con todas las lecturas en la
    misma instantánea: la transacción de quien llama, si ya está en una; si no, una propia."""
    if conn is not None:
        if conn.in_transaction:
            yield conn
            return
        conn.execute("BEGIN")
        try:
            yield conn
        finally:
            conn.execute("ROLLBACK")
        return
    with project.read() as reading:
        with _snapshot(project, reading):
            yield reading


def _chunks(uids: Collection[str]) -> Iterator[list[str]]:
    items = sorted(uids)
    for start in range(0, len(items), CHUNK):
        yield items[start:start + CHUNK]


def _records(conn: sqlite3.Connection, uids: Collection[str]) -> dict[str, DatasetRecord]:
    found: dict[str, DatasetRecord] = {}
    for chunk in _chunks(uids):
        sql = _DATASETS.format(marks=", ".join("?" for _ in chunk))
        for row in conn.execute(sql, chunk):
            record = DatasetRecord.from_row(row)
            found[record.uid] = record
    return found


def _stale(conn: sqlite3.Connection, uids: Collection[str]) -> frozenset[str]:
    found: set[str] = set()
    for chunk in _chunks(uids):
        sql = _STALE.format(marks=", ".join("?" for _ in chunk))
        found.update(str(row[0]) for row in conn.execute(sql, chunk))
    return frozenset(found)


def _successor(conn: sqlite3.Connection, uid: str) -> DatasetRecord | None:
    """El dato vivo que sustituye a ``uid``; ``None`` si no lo hay o no se sabe cuál es (varias
    operaciones o varios datos con su papel lo sustituyen: no se carga ninguno)."""
    try:
        return dataset_registry.successor(conn, uid)
    except ValidationError as exc:
        if exc.code != AMBIGUOUS_SUCCESSOR:
            raise
        return None


def _live_state(item: LoadedItem, record: DatasetRecord, stale: bool, where: tuple[str, ...],
                view_stale: bool) -> ItemState:
    """El paso 4 de A1: un dato vivo que se puede cargar."""
    unannotated = not item.origins or "" in item.origins
    if (
        item.contents != {record.content_sha256}
        or any(text and _origin_words(text) != where for text in item.origins)
        or (unannotated and view_stale)
    ):
        return ItemState.OUTDATED
    if item.statuses != {str(record.status)} or item.stale != {stale}:
        return ItemState.RESTATE
    return ItemState.CURRENT


def view_states(project: ReadableProject, items: Iterable[LoadedItem], *, project_uid: str,
                origin: GeoOrigin, view_stale: bool,
                conn: sqlite3.Connection | None = None) -> dict[str, ItemView]:
    """El estado de cada dato cargado ``items`` frente al proyecto abierto ``project`` (de uid
    ``project_uid`` y GeoOrigin ``origin``; ``view_stale``, si la vista quedó desfasada,
    RF-002-29), por uid (en el orden de los uid): véase el módulo. Lee en una instantánea (la de ``conn``,
    una conexión de lectura de quien llama, o una nueva), por trozos de :data:`CHUNK` uid,
    ``gb_dataset``, ``gb_stale`` y el sucesor de lo sustituido; sin ningún dato de este
    proyecto, no lee nada. No escribe. ``ValueError`` si un dato está repetido."""
    if not isinstance(project_uid, str) or not project_uid:
        raise TypeError(f"el uid del proyecto abierto es un texto no vacío, no {project_uid!r}")
    where = _origin_words(origin_text(origin))
    if not isinstance(view_stale, bool):
        raise TypeError(f"view_stale es verdadero o falso, no {view_stale!r}")
    loaded: dict[str, LoadedItem] = {}
    for item in items:
        if not isinstance(item, LoadedItem):
            raise TypeError(f"un dato cargado es un LoadedItem, no {item!r}")
        if item.dataset_uid in loaded:
            raise ValueError(f"el dato {item.dataset_uid} está repetido entre los cargados: "
                             "sus objetos se agrupan en uno")
        loaded[item.dataset_uid] = item
    own = [uid for uid, item in loaded.items() if item.project_uid == project_uid]
    records: dict[str, DatasetRecord] = {}
    stale: frozenset[str] = frozenset()
    successors: dict[str, DatasetRecord | None] = {}
    if own:
        with _snapshot(project, conn) as reading:
            records = _records(reading, own)
            stale = _stale(reading, [uid for uid, record in records.items() if record.live])
            successors = {uid: _successor(reading, uid) for uid, record in records.items()
                          if record.status is DatasetStatus.SUPERSEDED}
    found: dict[str, ItemView] = {}
    for uid in sorted(loaded):
        item = loaded[uid]
        record = records.get(uid) if item.project_uid == project_uid else None
        successor = successors.get(uid)
        is_stale = record is not None and record.live and uid in stale
        if record is None or record.status is DatasetStatus.DISCARDED:
            kind = ItemState.UNBACKED
        elif record.status is DatasetStatus.SUPERSEDED:
            kind = ItemState.UNBACKED if successor is None else ItemState.REPLACED
        elif record.status is DatasetStatus.MISSING:
            kind = ItemState.MISSING
        else:
            kind = _live_state(item, record, is_stale, where, view_stale)
        found[uid] = ItemView(uid, kind, record, is_stale,
                              successor if kind is ItemState.REPLACED else None)
    return found


@dataclass(frozen=True)
class RefreshPlan:
    """Lo que hace Refrescar (F5) con los datos cargados (algoritmo A2 del plan):

    - ``reload``: pares (dato cargado, dato que se carga en su lugar): él mismo si no está al día
      (``OUTDATED``) o su sucesor si está sustituido (``REPLACED``); un mismo dato puede ser el
      destino de varios pares (:attr:`targets` los da una vez);
    - ``unbacked``: los que se marcan «sin respaldo en el proyecto», sin borrarlos;
    - ``missing``: los que faltan, que no se pueden cargar (se dice y no se tocan);
    - ``restate``: los que solo hay que poner al día (estado u obsoleto), sin recargarlos;
    - ``current``: cuántos están al día.

    Cada tupla, por el uid del dato cargado."""

    reload: tuple[tuple[str, str], ...]
    unbacked: tuple[str, ...]
    missing: tuple[str, ...]
    restate: tuple[str, ...]
    current: int

    @property
    def targets(self) -> tuple[str, ...]:
        """Los datos que se cargan, una vez cada uno, en el orden de :attr:`reload`."""
        return tuple(dict.fromkeys(target for _loaded, target in self.reload))


def _views(states: Mapping[str, ItemView]) -> list[ItemView]:
    views = [states[uid] for uid in sorted(states)]
    for view in views:
        if not isinstance(view, ItemView):
            raise TypeError(f"el estado de un dato cargado es un ItemView, no {view!r}")
    return views


def refresh_plan(states: Mapping[str, ItemView]) -> RefreshPlan:
    """El plan de Refrescar de los estados ``states`` (los de :func:`view_states`)."""
    reload: list[tuple[str, str]] = []
    unbacked: list[str] = []
    missing: list[str] = []
    restate: list[str] = []
    current = 0
    for view in _views(states):
        if view.state in PENDING_STATES:
            target = view.target_uid()
            if target is None:  # un REPLACED sin sucesor no sale de view_states
                raise ValueError(f"el dato {view.uid} se sustituye y no dice por cuál")
            reload.append((view.uid, target))
        elif view.state is ItemState.UNBACKED:
            unbacked.append(view.uid)
        elif view.state is ItemState.MISSING:
            missing.append(view.uid)
        elif view.state is ItemState.RESTATE:
            restate.append(view.uid)
        else:
            current += 1
    return RefreshPlan(tuple(reload), tuple(unbacked), tuple(missing), tuple(restate), current)


def pending(states: Mapping[str, ItemView]) -> int:
    """Cuántos datos cargados no están al día y Refrescar vuelve a cargar (:data:`PENDING_STATES`):
    lo que cuenta el control 7 y el aviso al abrir el proyecto (RF-010-02, RF-010-03). Lo que
    está sin respaldo o falta ya se marca solo y no cuenta: Refrescar no lo cambia."""
    return sum(1 for view in _views(states) if view.state in PENDING_STATES)
