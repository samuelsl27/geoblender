# SPDX-License-Identifier: GPL-3.0-or-later
"""Restos de operaciones interrumpidas, ficheros ajenos y capas sin registrar en el proyecto
(spec 008; RF-008-22, RF-008-62, RF-008-14, RF-008-58; D-19 de la spec; ADR-0025 §3 y §8; plan
008 §5.2.2, §5.3.1, §5.4.6 y §5.4.9).

Una operación que se interrumpe (Blender se cierra, cae la red de ``Z:``, otro equipo fuerza el
cerrojo) puede dejar en ``rasters/``, ``meshes/`` u ``originals/`` ficheros que no llegó a
registrar: temporales y salidas a medias. Al abrir el proyecto en escritura,
:func:`orphan_steps` los **aparta** a la carpeta de restos del proyecto (dentro de él, D-19),
``orphans/<AAAAMMDDTHHMMSSZ>_<sesión8>/<carpeta>/<fichero>``, con la ruta que tenían, y avisa
con la lista. **Nunca borra nada** (un destino que ya existe no se sustituye: se numera,
``<nombre>~2.<ext>``) y no hace falta copiar: ``os.rename`` dentro del proyecto, mismo volumen.

**Es un resto** lo que lleva nombre de los módulos y no es de nadie:

- en ``rasters/`` y ``meshes/`` (también en subcarpetas) y en ``originals/``, un fichero con
  nombre de dato (``<código>_<nombre>.<ext>``, con el código de un módulo de
  ``core.catalog.schema.MODULE_CODES``: ``gis_mdt.tif``, ``gis_mdt.tif.tmp``), un temporal de
  otra sesión (``<nombre>.tmp-<sesión>``, como los de ``originals/``) o una salida con huella
  (``<nombre>__<hash8>.<ext>``);
- en ``originals/``, una carpeta ``<uid>`` con forma de uid cuya entrada no está registrada (se
  aparta entera);
- en ``snapshots/`` (spec 009, RF-009-07; plan 009 A6 (5)), una carpeta con nombre de
  instantánea que no es la de ninguna revisión congelada (``gb_revision.snapshot_dir``): la
  temporal de una congelación que no terminó (``V10.r2.congelando-<8 hex>``) o una ya
  renombrada sin su fila (``V10.r2``), que se aparta entera, como la de un original. La
  temporal de la congelación en curso de esta sesión
  (``core.versions.freezing.freezing_paths``) no se aparta nunca, y lo que no lleva nombre de
  instantánea no se mira. Un proyecto sin revisiones (un esquema anterior al 3, en solo
  lectura) no tiene restos en ``snapshots/``.

**No es un resto** (no se aparta ni se toca): lo que es de un dato registrado
(``gb_dataset.locator`` en cualquier estado, también lo sustituido y lo descartado), un original
guardado (``gb_input_file.original_path``), la fuente de una entrada guardada dentro del
proyecto (``gb_input_file`` con ancla ``project``, RF-008-14; tampoco la carpeta que la
contiene), lo que acompaña a uno de ellos con su nombre y otra extensión (el ``.aux.xml`` que
escribe QGIS junto a un ráster; un temporal, en cambio, sí es un resto), lo que reclama una
operación en curso de esta sesión (``OperationHandle.claim_paths``, y ``claimed``), un temporal
de esta misma sesión, lo escrito o cambiado después de empezar (``started_at``, con
:data:`RECENT_MARGIN_NS` de margen por la resolución de las fechas en red; I-5) y lo que no
lleva nombre de los módulos.

**Ajenos y sin registrar** (RF-008-62): lo que no lleva nombre de los módulos en esas
carpetas y no es de ningún dato ni de ninguna entrada (ni lo acompaña, ni lo reclama una
operación en curso de esta sesión) es un **fichero ajeno**; una tabla de ``project.gpkg`` que no
es del estándar GeoPackage ni de SQLite ni interna (:data:`~.tracking.RESERVED_PREFIXES`), ni
de un dato, ni la fuente de una entrada (ancla ``project_table``), es una **capa o tabla sin
registrar** (creada desde QGIS); las de ``gpkg_contents`` (capas de entidades y tablas) se
pueden registrar como entrada (``core.import_layer``). Se avisan con su lista
(:attr:`OrphanOutcome.foreign`) y **nunca** se mueven ni se cambian; el hallazgo queda en el
evento ``unregistered_found`` cuando hay algo que no constaba en el anterior. Lo que el usuario
decide ignorar (:func:`ignore`: ``gb_ignored``, con quién, cuándo y el motivo, y el evento
``item_ignored``) deja de avisarse.

Los pasos los avanza el temporizador de ``bl`` (ninguno pasa de ``budget_s``; el trabajo de
cada paso se planea para la mitad): primero el **listado** (``os.scandir``: el tamaño y la fecha
salen del listado, sin un ``stat`` por fichero) contra lo registrado (lo que no se aparta, en un
paso propio, y lo demás, al empezar el listado); después
**apartar**, volviendo a leer en cada paso lo registrado y lo reclamado y a mirar el tamaño y la
fecha de cada resto justo antes de moverlo: lo que se registró, se reclamó o cambió entre dos
pasos queda para la próxima (``stale``); por último, el **registro**: los eventos
``orphans_moved`` y ``unregistered_found`` (sin rutas absolutas) con ``Project.try_write``,
reintentado en el paso siguiente si otro programa está leyendo, o en la transacción final de
quien llama (``record=False`` y :func:`record_orphans`).

Un resto que otro programa tiene abierto (``PermissionError``: QGIS) se salta sin fallar y queda
en el aviso «se reintentará»; nada se anota: se vuelve a encontrar al abrir la próxima vez. En
**solo lectura** (``write=False`` o el proyecto sin escritura) solo se avisa con la lista: no
se mueve nada, no se crea ``orphans/`` ni se escribe en la base (tampoco el evento de lo ajeno).

Python puro (ADR-0004): al importarse no importa ``core.provenance`` ni ``core.project`` (que
pasan por este paquete), que se cargan al usarse; de ``core.versions``, solo lo ligero (``model``
y el registro de las congelaciones en curso, ``freezing``): un paso no carga
``core.versions.freeze`` (RNF-008-12: ≤ 20 ms por tic; T39).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
import stat
import string
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Any, Protocol

from ..catalog.schema import MODULE_CODES
from ..content.builtin import LAYER_KINDS
from ..ids import SHORT_UID_CHARS
from ..paths import MAX_FILE_PATH_CHARS, MAX_FOLDER_PATH_CHARS
from ..timeutil import format_utc
from ..versions.freezing import freezing_paths
from ..versions.model import FREEZING_MARK, SNAPSHOTS_DIR
from .external import _budget, _Pacer, _reason
from .model import FILE_STORES, Store
from .tracking import RESERVED_PREFIXES

if TYPE_CHECKING:
    from ..sysinfo import SessionInfo
    from ..timeutil import Clock

DATA_FOLDERS: tuple[str, ...] = (Store.RASTERS.value, Store.MESHES.value, Store.ORIGINALS.value)
"""Las carpetas de datos del proyecto en las que se buscan restos (plan 008 §5.4.9)."""
ORPHANS_DIR = "orphans"
"""La carpeta de restos en la raíz del proyecto (ADR-0025 §8; D-19)."""
STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
"""La fecha (UTC) del nombre de la carpeta de una pasada: ``<fecha>_<sesión8>``."""
STEP_BUDGET_S = 0.020
"""Lo que puede durar un paso (plan 008 §2: ≤ 20 ms por tic)."""
RECENT_MARGIN_NS = 2 * 10**9
"""Lo escrito hasta 2 s antes de empezar también cuenta como posterior: la fecha de un fichero
en una unidad de red (o en FAT) puede ir redondeada."""
MAX_LISTED = 20
"""Cuántos restos nombra cada aviso; de los demás dice cuántos son."""
PHASES: tuple[str, ...] = ("listado", "apartar", "registro")
"""Las fases de los pasos (``core.project.model.Progress``)."""
LOCKED_REASON = "abierto en otro programa"
"""El motivo de un resto que no se pudo apartar porque otro programa lo tiene abierto."""
REGISTRABLE_DATA_TYPES: frozenset[str] = frozenset(LAYER_KINDS)
"""Los ``gpkg_contents.data_type`` de una capa o tabla sin registrar que se puede registrar como
entrada (``core.import_layer`` la lee con ``core.gpkg_layer``)."""

_MODULE_NAME = re.compile(rf"(?:{'|'.join(MODULE_CODES)})_[a-z0-9_]+(?:\..*)?", re.DOTALL)
_SESSION_TEMPORARY = re.compile(r"\.tmp-([0-9A-Za-z]{1,32})$")
_TEMPORARY = re.compile(r"\.tmp(?:-[0-9A-Za-z]{1,32})?$")
_HASHED = re.compile(r"__[0-9a-f]{8}\.[^.]+$")
_UID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_SNAPSHOT = re.compile(rf"V[0-9]{{2,}}\.r[1-9][0-9]*(?:{re.escape(FREEZING_MARK)}[0-9a-f]{{8}})?")
"""El nombre de la carpeta de una instantánea (``V10.r2``) o de su temporal
(``V10.r2.congelando-<8 hex>``) en ``snapshots/`` (spec 009, plan §5.2.5 y A6)."""
_ASCII_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)

__all__ = [
    "DATA_FOLDERS",
    "LOCKED_REASON",
    "ORPHANS_DIR",
    "PHASES",
    "RECENT_MARGIN_NS",
    "REGISTRABLE_DATA_TYPES",
    "Foreign",
    "ForeignKind",
    "Orphan",
    "OrphanOutcome",
    "OrphanProject",
    "OrphanState",
    "geoblender_name",
    "ignore",
    "orphan_steps",
    "record_orphans",
    "unregistered_tables",
]


class OrphanProject(Protocol):
    """Lo que usa del proyecto (``core.project.Project``) el barrido de restos: su raíz, el
    reloj, la sesión, si se puede escribir, leer y escribir con reintento (y, para las rutas
    reclamadas, lo de ``core.provenance.operations.claimed_paths``)."""

    @property
    def root(self) -> Path: ...

    @property
    def clock(self) -> Clock: ...

    @property
    def session(self) -> SessionInfo: ...

    @property
    def writable(self) -> bool: ...

    def read(self) -> AbstractContextManager[Any]: ...

    def try_write(self, work: Callable[[Any], Any]) -> Any: ...


class OrphanState(StrEnum):
    """Qué pasó con un resto."""

    MOVED = "moved"  # apartado a orphans/
    LOCKED = "locked"  # abierto en otro programa: se reintenta al abrir la próxima vez
    FAILED = "failed"  # no se pudo apartar por otra causa: se reintenta al abrir la próxima vez
    FOUND = "found"  # solo visto (solo lectura): se apartará al abrir en escritura


@dataclass(frozen=True)
class Orphan:
    """Un resto: su ruta relativa a la raíz del proyecto con «/» (``rasters/gis_x.tif``; de una
    carpeta, ``originals/<uid>``), si es una carpeta, qué pasó, adónde se apartó y, si no se
    pudo, por qué."""

    path: str
    folder: bool
    state: OrphanState
    moved_to: str | None = None
    reason: str | None = None

    @property
    def shown(self) -> str:
        """Como se nombra en un aviso: una carpeta, con «/» al final."""
        return f"{self.path}/" if self.folder else self.path


class ForeignKind(StrEnum):
    """Qué es algo ajeno al proyecto (``gb_ignored.kind``)."""

    FILE = "file"  # un fichero ajeno de una carpeta de datos
    TABLE = "table"  # una capa o tabla de project.gpkg sin registrar


@dataclass(frozen=True)
class Foreign:
    """Un fichero ajeno o una capa o tabla sin registrar (RF-008-62): su clase, su nombre (de
    un fichero, su ruta relativa a la raíz del proyecto con «/», ``rasters/Mapa.tif``; de una
    tabla, su nombre en la base) y si se puede registrar como entrada (una capa de entidades o
    una tabla de ``gpkg_contents``, con ``core.import_layer``)."""

    kind: ForeignKind
    name: str
    registrable: bool = False

    @property
    def shown(self) -> str:
        """Como se nombra en un aviso."""
        return self.name

    @property
    def key(self) -> tuple[str, str]:
        """Para compararlo sin distinguir mayúsculas (en Windows, tampoco los separadores)."""
        return str(self.kind), (_key(self.name) if self.kind is ForeignKind.FILE
                                else _table_key(self.name))


def _render(code: str, *, language: str = "es", **values: Any) -> str:
    from ..provenance.messages import render

    return render(code, language=language, **values)


def _listing(items: Iterable[Orphan | Foreign], language: str, *, reasons: bool = False) -> str:
    """«a», «b» y n más: los primeros :data:`MAX_LISTED` (con ``reasons``, cada uno con su
    motivo entre paréntesis)."""
    chosen = list(items)
    shown = ", ".join(f"«{item.shown}» ({item.reason})" if reasons else f"«{item.shown}»"
                      for item in chosen[:MAX_LISTED])
    if len(chosen) > MAX_LISTED:
        shown += " " + _render("core.orphans_more", language=language,
                               count=len(chosen) - MAX_LISTED)
    return shown


@dataclass(frozen=True)
class OrphanOutcome:
    """El resultado de :func:`orphan_steps`: los restos encontrados, por su ruta (apartados, que
    no se pudieron apartar o, en solo lectura, solo vistos), la carpeta de la pasada en
    ``orphans/`` (si se apartó algo), si quedó algún evento en el proyecto, lo que se vio pero
    cambió, se registró o se reclamó mientras tanto (``stale``: queda para la próxima) y lo
    ajeno (``foreign``: los ficheros ajenos por su ruta y después las capas y tablas sin
    registrar por su nombre, RF-008-62)."""

    orphans: tuple[Orphan, ...]
    folder: str | None
    recorded: bool
    stale: tuple[str, ...] = ()
    foreign: tuple[Foreign, ...] = ()

    def _of(self, *states: OrphanState) -> tuple[Orphan, ...]:
        return tuple(item for item in self.orphans if item.state in states)

    @property
    def moved(self) -> tuple[Orphan, ...]:
        """Los restos apartados."""
        return self._of(OrphanState.MOVED)

    @property
    def retry(self) -> tuple[Orphan, ...]:
        """Los que no se pudieron apartar (abiertos en otro programa u otra causa): se
        reintentan al abrir la próxima vez."""
        return self._of(OrphanState.LOCKED, OrphanState.FAILED)

    @property
    def found(self) -> tuple[Orphan, ...]:
        """Los que solo se vieron (solo lectura)."""
        return self._of(OrphanState.FOUND)

    @property
    def foreign_files(self) -> tuple[Foreign, ...]:
        """Los ficheros ajenos (RF-008-62)."""
        return tuple(item for item in self.foreign if item.kind is ForeignKind.FILE)

    @property
    def unregistered_tables(self) -> tuple[Foreign, ...]:
        """Las capas y tablas sin registrar (RF-008-62)."""
        return tuple(item for item in self.foreign if item.kind is ForeignKind.TABLE)

    def foreign_texts(self, language: str = "es") -> tuple[str, ...]:
        """Los avisos de lo ajeno en ``language``: los ficheros y las capas, con su lista."""
        found: list[str] = []
        if self.foreign_files:
            found.append(_render("core.foreign_files", language=language,
                                 files=_listing(self.foreign_files, language)))
        if self.unregistered_tables:
            found.append(_render("core.unregistered_tables", language=language,
                                 tables=_listing(self.unregistered_tables, language)))
        return tuple(found)

    def texts(self, language: str = "es") -> tuple[str, ...]:
        """Los avisos en ``language``: lo apartado, lo abierto en otro programa, lo que no se
        pudo apartar y lo visto en solo lectura, y después lo ajeno, cada uno con su lista."""
        found: list[str] = []
        if self.moved:
            found.append(_render("core.orphans_moved", language=language, folder=self.folder,
                                 files=_listing(self.moved, language)))
        locked = self._of(OrphanState.LOCKED)
        if locked:
            found.append(_render("core.orphans_locked", language=language,
                                 files=_listing(locked, language)))
        failed = self._of(OrphanState.FAILED)
        if failed:
            found.append(_render("core.orphans_failed", language=language,
                                 files=_listing(failed, language, reasons=True)))
        if self.found:
            found.append(_render("core.orphans_found", language=language,
                                 files=_listing(self.found, language)))
        return (*found, *self.foreign_texts(language))

    @property
    def warnings(self) -> tuple[str, ...]:
        """Los avisos en español."""
        return self.texts("es")


def geoblender_name(name: str) -> bool:
    """Si el nombre de fichero ``name`` es de los que escriben los módulos (véase el módulo):
    ``<código>_<nombre>[.<ext>…]``, ``<nombre>.tmp-<sesión>`` o ``<nombre>__<hash8>.<ext>``."""
    return bool(_MODULE_NAME.fullmatch(name) or _SESSION_TEMPORARY.search(name)
                or _HASHED.search(name))


def orphan_steps(project: OrphanProject, *, write: bool, started_at: int | None = None,
                 claimed: Iterable[str | os.PathLike[str]] = (),
                 budget_s: float = STEP_BUDGET_S, record: bool = True) -> Iterator[Any]:
    """Busca los restos de ``rasters/``, ``meshes/`` y ``originals/`` del proyecto y, con
    ``write`` y el proyecto en escritura, los aparta a ``orphans/`` (RF-008-22; véase el
    módulo), por pasos de ``budget_s`` como mucho. Cada paso es un
    ``core.project.model.Progress``; el último lleva el :class:`OrphanOutcome` en ``result``.

    - ``started_at``: cuándo empezó la comprobación, en ns desde 1970 (``time.time_ns()``, como
      ``st_mtime_ns``; por defecto, ahora): lo escrito después no se aparta;
    - ``claimed``: rutas que no se apartan (absolutas o relativas a la raíz del proyecto),
      además de las que reclaman las operaciones en curso de esta sesión, que se leen en cada
      paso;
    - ``record``: el evento ``orphans_moved`` lo escribe el último paso (con reintento); sin
      él, quien llama lo escribe con :func:`record_orphans` en su transacción.

    Cerrar el generador a medias deja apartado lo ya apartado, sin evento. :class:`TypeError` o
    :class:`ValueError` (al llamarla) con un argumento mal dado."""
    if not isinstance(write, bool):
        raise TypeError(f"«write» es verdadero o falso, no {write!r}")
    if not isinstance(record, bool):
        raise TypeError(f"«record» es verdadero o falso, no {record!r}")
    if started_at is None:
        started_at = time.time_ns()
    elif isinstance(started_at, bool) or not isinstance(started_at, int):
        raise TypeError(f"«started_at» es un instante en ns desde 1970 (time.time_ns()), no "
                        f"{started_at!r}")
    if isinstance(claimed, str | bytes | os.PathLike):
        raise TypeError(f"«claimed» es una lista de rutas, no una ruta: {claimed!r}")
    root = Path(project.root)
    extra = frozenset(key for key in (_claimed_key(root, path) for path in claimed) if key)
    now = project.clock.now().astimezone(dt.UTC)
    folder = f"{ORPHANS_DIR}/{now.strftime(STAMP_FORMAT)}_{_tag(project)}"
    return _steps(project, root, write=write, limit=started_at - RECENT_MARGIN_NS,
                  extra=extra, folder=folder, budget=_budget(budget_s), record=record)


def record_orphans(conn: Any, project: OrphanProject, outcome: OrphanOutcome) -> bool:
    """Escribe los eventos de ``outcome`` en la transacción de escritura ``conn`` de quien
    llama (no la confirma), sin rutas absolutas, y dice si escribió alguno:

    - ``orphans_moved``, si se apartó algo: la carpeta, lo apartado (de dónde y adónde) y lo
      que no se pudo apartar con su motivo;
    - ``unregistered_found``, si hay algo ajeno que no constaba en el anterior (RF-008-62): los
      ficheros ajenos y las capas y tablas sin registrar que hay ahora."""
    from ..project.events import EventKind, record_event

    at = format_utc(project.clock.now())
    written = False
    if outcome.moved:
        record_event(conn, EventKind.ORPHANS_MOVED,
                     _render("core.orphans_moved", folder=outcome.folder,
                             files=_listing(outcome.moved, "es")),
                     session=project.session, at=at, data={
                         "folder": outcome.folder,
                         "moved": [[item.path, item.moved_to] for item in outcome.moved],
                         "not_moved": [[item.path, str(item.state), item.reason]
                                       for item in outcome.retry],
                     })
        written = True
    if _news(outcome.foreign, _reported(conn)):
        record_event(conn, EventKind.UNREGISTERED_FOUND, " ".join(outcome.foreign_texts("es")),
                     session=project.session, at=at, data={
                         "files": [item.name for item in outcome.foreign_files],
                         "tables": [item.name for item in outcome.unregistered_tables],
                     })
        written = True
    return written


def _news(foreign: Iterable[Foreign], reported: frozenset[tuple[str, str]]) -> bool:
    """Si hay algo ajeno que no constaba en el último evento ``unregistered_found``."""
    return any(item.key not in reported for item in foreign)


def _reported(conn: sqlite3.Connection) -> frozenset[tuple[str, str]]:
    """Lo ajeno que constaba en el último evento ``unregistered_found``."""
    row = conn.execute("SELECT data FROM gb_event WHERE kind = 'unregistered_found' "
                       "ORDER BY fid DESC LIMIT 1").fetchone()
    if row is None or row[0] is None:
        return frozenset()
    try:
        data = json.loads(row[0])
        files = [Foreign(ForeignKind.FILE, str(name)).key for name in data["files"]]
        tables = [Foreign(ForeignKind.TABLE, str(name)).key for name in data["tables"]]
    except (ValueError, KeyError, TypeError):
        return frozenset()
    return frozenset(files + tables)


# --- Lo que no es un resto ------------------------------------------------------------------


def _key(rel: str) -> str:
    """La clave de una ruta relativa a la raíz para compararla (sin distinguir mayúsculas ni
    separadores en Windows)."""
    return os.path.normcase(os.path.normpath(rel))


def _claimed_key(root: Path, path: object) -> str | None:
    raw = os.fspath(path)  # type: ignore[arg-type]
    if not isinstance(raw, str):
        raise TypeError(f"una ruta reclamada es un texto o una ruta, no {path!r}")
    if not os.path.isabs(raw):
        return _key(raw)
    try:
        relative = os.path.relpath(raw, root)
    except ValueError:  # otra unidad
        return None
    outside = relative == os.pardir or relative.startswith(os.pardir + os.sep)
    return None if outside else _key(relative)


def _tag(project: OrphanProject) -> str:
    """Las 8 últimas cifras de la sesión (como en los temporales de ``originals/``)."""
    return (project.session.session_uid.replace("-", "")[-SHORT_UID_CHARS:] or "sesion").lower()


_PROTECTED = (
    f"SELECT locator FROM gb_dataset WHERE store IN "
    f"({', '.join(repr(str(store)) for store in FILE_STORES if str(store) in DATA_FOLDERS)})",
    "SELECT original_path FROM gb_input_file WHERE original_path IS NOT NULL",
    "SELECT path FROM gb_input_file WHERE anchor = 'project'",
)
"""Lo registrado en las carpetas de datos: los datos, los originales guardados y las fuentes
dentro del proyecto."""


_SNAPSHOT_DIRS = "SELECT snapshot_dir FROM gb_revision WHERE snapshot_dir IS NOT NULL"
"""Las carpetas de las instantáneas de las revisiones congeladas (spec 009)."""


@dataclass(frozen=True)
class _Protected:
    """Lo que no se aparta: ficheros y carpetas de instantáneas (sus claves), las carpetas que
    los contienen, los nombres de cada carpeta (para lo que los acompaña), los uid de las
    entradas registradas y si el proyecto tiene revisiones (sin ellas, ``snapshots/`` no se
    mira)."""

    files: frozenset[str]
    folders: frozenset[str]
    names: Mapping[str, tuple[str, ...]]
    inputs: frozenset[str]
    revisions: bool = False

    def companion(self, key: str) -> bool:
        """Si el fichero ``key`` acompaña a uno de ellos (su nombre y otra extensión)."""
        parent, name = os.path.split(key)
        return any(name.startswith(f"{other}.") for other in self.names.get(parent, ()))

    def holds(self, key: str) -> bool:
        """Si la carpeta ``key`` contiene algo que no se aparta."""
        return key in self.folders


def _protection(project: OrphanProject, root: Path, extra: frozenset[str],
                conn: sqlite3.Connection | None = None) -> _Protected:
    """Una lectura (con ``conn`` o una propia) de lo registrado (también las carpetas de las
    instantáneas) más lo reclamado ahora por esta sesión (también la temporal de su
    congelación en curso) y ``extra``."""
    from ..provenance.operations import claimed_paths

    reading = nullcontext(conn) if conn is not None else project.read()
    with reading as opened:
        found = [str(row[0]) for sql in _PROTECTED for row in opened.execute(sql)]
        inputs = frozenset(str(row[0]).lower()
                           for row in opened.execute("SELECT uid FROM gb_input"))
        claimed = claimed_paths(project, conn=opened)  # type: ignore[arg-type]
        revisions = opened.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' "
                                   "AND name = 'gb_revision'").fetchone() is not None
        if revisions:
            found.extend(str(row[0]) for row in opened.execute(_SNAPSHOT_DIRS))
    keys = {_key(rel) for rel in found} | set(extra)
    for path in (*claimed, *freezing_paths(project)):
        key = _claimed_key(root, path)
        if key:
            keys.add(key)
    folders: set[str] = set()
    names: dict[str, list[str]] = {}
    for key in keys:
        parent, name = os.path.split(key)
        names.setdefault(parent, []).append(name)
        while parent and parent not in folders:
            folders.add(parent)
            parent = os.path.dirname(parent)
    return _Protected(frozenset(keys), frozenset(folders),
                      {parent: tuple(items) for parent, items in names.items()}, inputs,
                      revisions)


# --- Capas y tablas sin registrar (RF-008-62) -------------------------------------------------


def _table_key(name: str) -> str:
    """La clave del nombre de una tabla: SQLite no distingue mayúsculas de las letras ASCII."""
    return name.translate(_ASCII_LOWER)


def _column(conn: sqlite3.Connection, sql: str) -> set[str]:
    return {_table_key(str(row[0])) for row in conn.execute(sql)}


def unregistered_tables(conn: sqlite3.Connection) -> tuple[Foreign, ...]:
    """Las capas y tablas sin registrar de ``project.gpkg`` (con la conexión ``conn``),
    ordenadas por su nombre: las tablas que no son del estándar GeoPackage ni de SQLite ni
    internas (:data:`~.tracking.RESERVED_PREFIXES`), ni la de un dato (en cualquier estado), ni
    la fuente de una entrada (ancla ``project_table``), ni ignoradas (``gb_ignored``); cada una
    dice si se puede registrar como entrada (está en ``gpkg_contents`` como capa de entidades
    o tabla, :data:`REGISTRABLE_DATA_TYPES`). Solo lee."""
    # DISTINCT: muchos datos comparten tabla (uno por selector); sin él, con el volumen de
    # D-13 (16 000 datos en 160 tablas), esta lectura sola pasaba de 15 ms (T36).
    taken = (_column(conn, "SELECT DISTINCT locator FROM gb_dataset WHERE store = 'gpkg'")
             | _column(conn, "SELECT path FROM gb_input_file WHERE anchor = 'project_table'")
             | _column(conn, "SELECT name FROM gb_ignored WHERE kind = 'table'"))
    layers = {_table_key(str(name)): str(data_type).lower()
              for name, data_type in conn.execute(
                  "SELECT table_name, data_type FROM gpkg_contents")}
    found = [
        Foreign(ForeignKind.TABLE, str(name), layers.get(key) in REGISTRABLE_DATA_TYPES)
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        if not (key := _table_key(str(name))).startswith(RESERVED_PREFIXES) and key not in taken
    ]
    return tuple(sorted(found, key=lambda item: item.name.casefold()))


@dataclass(frozen=True)
class _Survey:
    """La lectura del principio del barrido: lo que no se aparta, los ficheros ignorados (sus
    claves), las capas y tablas sin registrar y lo ajeno que ya constaba en el último
    evento."""

    protected: _Protected
    ignored: frozenset[str]
    tables: tuple[Foreign, ...]
    reported: frozenset[tuple[str, str]]


def _survey(project: OrphanProject, protected: _Protected) -> _Survey:
    """El resto de la lectura del principio, con lo que no se aparta ya leído (en el paso
    anterior: las dos lecturas juntas pasaban de 20 ms con el volumen de D-13, T36)."""
    with project.read() as conn:
        return _Survey(
            protected,
            frozenset(_key(str(row[0])) for row in conn.execute(
                "SELECT name FROM gb_ignored WHERE kind = 'file'")),
            unregistered_tables(conn),
            _reported(conn),
        )


# --- Ignorar (RF-008-62) ------------------------------------------------------------------------


def _foreign_kind(kind: object) -> ForeignKind:
    if not isinstance(kind, str):
        raise TypeError(f"se ignora un fichero («file») o una capa o tabla («table»), no {kind!r}")
    try:
        return ForeignKind(kind)
    except ValueError:
        raise ValueError(f"se ignora un fichero («file») o una capa o tabla («table»), no "
                         f"{kind!r}") from None


def _relative_file(name: str) -> str:
    """La ruta de un fichero relativa a la raíz del proyecto, con «/» (``ValueError`` si es
    absoluta o sale de ella)."""
    parts = name.split("/")
    if ("\\" in name or PureWindowsPath(name).drive or PureWindowsPath(name).is_absolute()
            or PurePosixPath(name).is_absolute() or any(part in ("", ".", "..") for part in parts)):
        raise ValueError(f"un fichero ajeno se indica con su ruta relativa a la raíz del "
                         f"proyecto, con «/» y sin salir de ella, no {name!r}")
    return name


def _foreign_file(conn: sqlite3.Connection, project: OrphanProject, rel: str) -> bool:
    """Si ``rel`` es ahora un fichero ajeno de una carpeta de datos (véase el módulo)."""
    parts = rel.split("/")
    folder = os.path.normcase(parts[0])
    if len(parts) < 2 or folder not in DATA_FOLDERS or geoblender_name(parts[-1]):
        return False
    root = Path(project.root)
    try:
        found = os.stat(root.joinpath(*parts), follow_symlinks=False)
    except OSError:
        return False
    if not stat.S_ISREG(found.st_mode):
        return False
    protected = _protection(project, root, frozenset(), conn)
    key = _key(rel)
    if key in protected.files or protected.companion(key):
        return False
    if folder == Store.ORIGINALS.value and len(parts) > 2:
        uid = parts[1].lower()  # una carpeta de originales sin entrada es un resto entero
        holder = _key(f"{parts[0]}/{parts[1]}")
        if (_UID.fullmatch(uid) is not None and uid not in protected.inputs
                and not protected.holds(holder) and holder not in protected.files):
            return False
    return True


def ignore(conn: sqlite3.Connection, project: OrphanProject, kind: ForeignKind | str, name: str,
           reason: str | None = None) -> bool:
    """El usuario decide ignorar el fichero ajeno o la capa o tabla sin registrar ``name``
    (``kind``: ``"file"``, con su ruta relativa a la raíz del proyecto, o ``"table"``, con su
    nombre; RF-008-62), en la transacción de escritura ``conn`` de quien llama (no la
    confirma): su fila de ``gb_ignored`` con quién, cuándo y ``reason`` (opcional, sin rutas
    absolutas) y el evento ``item_ignored``; deja de avisarse y nada de él se mueve ni cambia.
    Si ya estaba ignorado, no escribe nada y devuelve ``False``.

    ``ProvenanceError`` (``core.ignore_not_foreign``) sin escribir nada si no es ahora un
    fichero ajeno ni una capa sin registrar (un dato, la fuente de una entrada, una tabla del
    estándar o interna, lo que no está o no está en una carpeta de datos);
    :class:`TypeError`/:class:`ValueError` con un argumento mal formado o fuera de una
    transacción."""
    if not isinstance(conn, sqlite3.Connection):
        raise TypeError(f"ignore recibe la conexión de una transacción de escritura, no {conn!r}")
    if not conn.in_transaction:
        raise ValueError("ignore se llama dentro de una transacción de escritura "
                         "(Project.write_transaction)")
    chosen = _foreign_kind(kind)
    if not isinstance(name, str):
        raise TypeError(f"lo que se ignora se indica por su nombre o su ruta, no {name!r}")
    if not name.strip() or name != name.strip():
        raise ValueError(f"lo que se ignora no tiene un nombre vacío ni con espacios a los lados: "
                         f"{name!r}")
    if reason is not None and not isinstance(reason, str):
        raise TypeError(f"el motivo de ignorar algo es un texto, no {reason!r}")
    if chosen is ForeignKind.FILE:
        item: Foreign | None = Foreign(chosen, _relative_file(name))
    else:
        item = Foreign(chosen, name)
    stored = {Foreign(chosen, str(row[0])).key for row in conn.execute(
        "SELECT name FROM gb_ignored WHERE kind = ?", (str(chosen),))}
    if item.key in stored:
        return False
    if chosen is ForeignKind.FILE:
        item = item if _foreign_file(conn, project, item.name) else None
    else:
        item = next((found for found in unregistered_tables(conn) if found.key == item.key),
                    None)
    if item is None:
        from ..provenance.messages import ProvenanceError

        raise ProvenanceError("core.ignore_not_foreign", name=name)
    from ..project.events import EventKind, record_event
    from ..provenance.operations import _clean

    text = _clean(reason.strip()) if reason is not None and reason.strip() else None
    now = format_utc(project.clock.now())
    conn.execute("INSERT INTO gb_ignored (kind, name, reason, decided_by, decided_at) "
                 "VALUES (?, ?, ?, ?, ?)",
                 (str(chosen), item.name, text, project.session.user_host, now))
    code = "core.ignored_file" if chosen is ForeignKind.FILE else "core.ignored_table"
    record_event(conn, EventKind.ITEM_IGNORED, _render(code, name=item.name),
                 session=project.session, at=now,
                 data={"kind": str(chosen), "name": item.name, "reason": text})
    return True


# --- Listado ---------------------------------------------------------------------------------


@dataclass
class _Candidate:
    """Un resto en el listado: su ruta, su clave, si es una carpeta y lo que se vio (tamaño y
    fecha; de una carpeta, los de cada fichero de dentro)."""

    path: str
    key: str
    folder: bool
    seen: object = None
    result: Orphan | None = None


@dataclass
class _Sweep:
    """Lo que lleva el barrido entre pasos."""

    root: Path
    tag: str
    limit: int
    ignored: frozenset[str] = frozenset()
    found: list[_Candidate] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    foreign: list[str] = field(default_factory=list)


def _real_dir(path: Path) -> bool:
    try:
        found = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISDIR(found.st_mode) and not path.is_junction()


def _folder_contents(path: Path) -> tuple[tuple[str, int, int], ...] | None:
    """Los ficheros de la carpeta ``path`` (ruta dentro de ella, tamaño y fecha), o ``None`` si
    no se puede leer entera (un enlace dentro tampoco se aparta)."""
    found: list[tuple[str, int, int]] = []
    pending = [("", path)]
    try:
        while pending:
            prefix, folder = pending.pop()
            with os.scandir(folder) as entries:
                for entry in entries:
                    rel = f"{prefix}{entry.name}"
                    if entry.is_symlink() or entry.is_junction():
                        return None
                    if entry.is_dir(follow_symlinks=False):
                        pending.append((f"{rel}/", Path(entry.path)))
                    else:
                        info = entry.stat(follow_symlinks=False)
                        found.append((rel, info.st_size, info.st_mtime_ns))
    except OSError:
        return None
    return tuple(sorted(found))


def _newest(contents: tuple[tuple[str, int, int], ...]) -> int:
    return max((mtime for _rel, _size, mtime in contents), default=0)


def _examine(sweep: _Sweep, protected: _Protected, rel_dir: str, entry: os.DirEntry[str],
             stack: list[str]) -> None:
    """Clasifica una entrada del listado: carpeta a recorrer, resto, o nada."""
    if entry.is_symlink() or entry.is_junction():
        return
    rel = f"{rel_dir}/{entry.name}"
    key = _key(rel)
    if entry.is_dir(follow_symlinks=False):
        uid = entry.name.lower()
        if (rel_dir == Store.ORIGINALS.value and _UID.fullmatch(uid) is not None
                and uid not in protected.inputs and not protected.holds(key)
                and key not in protected.files):
            contents = _folder_contents(Path(entry.path))
            if contents is None:
                return
            if _newest(contents) >= sweep.limit:
                sweep.stale.append(rel)
            else:
                sweep.found.append(_Candidate(rel, key, True, contents))
            return
        stack.append(rel)
        return
    if not entry.is_file(follow_symlinks=False) or key in protected.files:
        return
    temporary = _SESSION_TEMPORARY.search(entry.name)
    if temporary is not None and temporary.group(1).lower() == sweep.tag:
        return  # un temporal de esta misma sesión: lo está escribiendo
    if not geoblender_name(entry.name):
        if not protected.companion(key) and key not in sweep.ignored:
            sweep.foreign.append(rel)  # ajeno: se avisa y nunca se mueve (RF-008-62)
        return
    if _TEMPORARY.search(entry.name) is None and protected.companion(key):
        return
    info = entry.stat(follow_symlinks=False)
    if info.st_mtime_ns >= sweep.limit:
        sweep.stale.append(rel)
        return
    sweep.found.append(_Candidate(rel, key, False, (info.st_size, info.st_mtime_ns)))


def _list_steps(project: OrphanProject, sweep: _Sweep, protected: _Protected,
                pacer: _Pacer) -> Iterator[Any]:
    """El listado de las carpetas de datos, por pasos (cada carpeta se lee entrada a entrada)."""
    from ..project.model import Progress

    message = "Buscando restos de operaciones interrumpidas…"
    stack = [folder for folder in reversed(DATA_FOLDERS) if _real_dir(sweep.root / folder)]
    examined = 0
    while stack:
        rel_dir = stack.pop()
        try:
            entries = os.scandir(sweep.root.joinpath(*rel_dir.split("/")))
        except OSError:
            continue  # ya no está o no se puede leer: lo que tenga, la próxima vez
        with entries:
            while True:
                try:
                    entry = next(entries)
                except StopIteration:
                    break
                except OSError:  # se cayó la red a mitad: el resto de la carpeta, la próxima vez
                    break
                try:
                    _examine(sweep, protected, rel_dir, entry, stack)
                except OSError:
                    pass  # la entrada desapareció o no se puede leer: no es un resto ahora
                examined += 1
                if pacer.lap():
                    yield Progress(PHASES[0], examined, 0, message)
                    pacer.restart()


def _examine_snapshot(sweep: _Sweep, protected: _Protected, entry: os.DirEntry[str]) -> None:
    """Clasifica una entrada de ``snapshots/``: la carpeta con nombre de instantánea que no es
    de ninguna revisión congelada (ni la temporal de esta sesión) es un resto entero."""
    if entry.is_symlink() or entry.is_junction() or not entry.is_dir(follow_symlinks=False):
        return
    if _SNAPSHOT.fullmatch(entry.name) is None:
        return  # no lleva nombre de instantánea: no es de Geoblender
    rel = f"{SNAPSHOTS_DIR}/{entry.name}"
    key = _key(rel)
    if key in protected.files:
        return
    contents = _folder_contents(Path(entry.path))
    if contents is None:
        return
    if _newest(contents) >= sweep.limit:
        sweep.stale.append(rel)
    else:
        sweep.found.append(_Candidate(rel, key, True, contents))


def _snapshot_steps(sweep: _Sweep, protected: _Protected, pacer: _Pacer) -> Iterator[Any]:
    """El listado de ``snapshots/`` (solo su primer nivel), por pasos, si el proyecto tiene
    revisiones (spec 009, plan A6 (5))."""
    from ..project.model import Progress

    folder = sweep.root / SNAPSHOTS_DIR
    if not protected.revisions or not _real_dir(folder):
        return
    try:
        entries = os.scandir(folder)
    except OSError:
        return  # no se puede leer: lo que tenga, la próxima vez
    examined = 0
    with entries:
        while True:
            try:
                entry = next(entries)
            except StopIteration:
                break
            except OSError:  # se cayó la red a mitad: el resto, la próxima vez
                break
            try:
                _examine_snapshot(sweep, protected, entry)
            except OSError:
                pass  # la entrada desapareció o no se puede leer: no es un resto ahora
            examined += 1
            if pacer.lap():
                yield Progress(PHASES[0], examined, 0,
                               "Buscando restos de congelaciones interrumpidas…")
                pacer.restart()


# --- Apartar ---------------------------------------------------------------------------------


def _numbered(name: str, number: int) -> str:
    """``<nombre>~<n>.<ext…>``: otro nombre para no sustituir lo que ya está apartado."""
    head, dot, tail = name.partition(".")
    return f"{head}~{number}{dot}{tail}"


def _destination(root: Path, folder: str, item: _Candidate) -> tuple[str, Path]:
    """Dónde se aparta ``item`` (sin sustituir nada): su ruta dentro de la carpeta de la
    pasada."""
    rel = PurePosixPath(folder, item.path)
    number = 1
    while True:
        chosen = rel if number == 1 else rel.with_name(_numbered(rel.name, number))
        target = root.joinpath(*chosen.parts)
        if not os.path.lexists(target):
            return chosen.as_posix(), target
        number += 1


def _too_long(target: Path, item: _Candidate) -> str | None:
    """Por qué no cabe ``target`` en el límite de rutas de Windows (``core.paths``)."""
    text = os.path.abspath(target)
    if item.folder:
        if len(text) > MAX_FOLDER_PATH_CHARS:
            return (f"su sitio en «{ORPHANS_DIR}/» pasaría del límite de rutas de Windows "
                    f"({len(text)} > {MAX_FOLDER_PATH_CHARS} caracteres)")
        contents: tuple[tuple[str, int, int], ...] = item.seen  # type: ignore[assignment]
        longest = max((len(text) + 1 + len(rel) for rel, _size, _mtime in contents), default=0)
        if longest > MAX_FILE_PATH_CHARS:
            return (f"su sitio en «{ORPHANS_DIR}/» pasaría del límite de rutas de Windows "
                    f"({longest} > {MAX_FILE_PATH_CHARS} caracteres)")
        return None
    if len(text) > MAX_FILE_PATH_CHARS:
        return (f"su sitio en «{ORPHANS_DIR}/» pasaría del límite de rutas de Windows "
                f"({len(text)} > {MAX_FILE_PATH_CHARS} caracteres)")
    return None


def _still_orphan(sweep: _Sweep, item: _Candidate, protected: _Protected) -> bool:
    """Si ``item`` sigue siendo un resto justo antes de apartarlo: nadie lo registró ni lo
    reclamó y está como en el listado, sin cambios después de empezar."""
    if item.key in protected.files:
        return False
    path = sweep.root.joinpath(*item.path.split("/"))
    if item.folder:
        if (protected.holds(item.key)
                or PurePosixPath(item.path).name.lower() in protected.inputs):
            return False
        now = _folder_contents(path) if _real_dir(path) else None
        return now == item.seen and _newest(now) < sweep.limit
    if _TEMPORARY.search(path.name) is None and protected.companion(item.key):
        return False
    try:
        info = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and (info.st_size, info.st_mtime_ns) == item.seen
            and info.st_mtime_ns < sweep.limit)


def _move(sweep: _Sweep, folder: str, item: _Candidate) -> Orphan | None:
    """Aparta ``item`` a la carpeta ``folder`` de ``orphans/`` con ``os.rename``, que en Windows
    nunca sustituye lo que ya está (se elige antes un nombre libre). ``None`` si ya no estaba."""
    source = sweep.root.joinpath(*item.path.split("/"))
    moved_to, target = _destination(sweep.root, folder, item)
    problem = _too_long(target, item)
    if problem is not None:
        return Orphan(item.path, item.folder, OrphanState.FAILED, reason=problem)
    try:
        os.makedirs(target.parent, exist_ok=True)
    except OSError as exc:
        return Orphan(item.path, item.folder, OrphanState.FAILED, reason=_reason(exc))
    try:
        os.rename(source, target)
    except PermissionError:
        return Orphan(item.path, item.folder, OrphanState.LOCKED, reason=LOCKED_REASON)
    except FileNotFoundError:
        return None
    except OSError as exc:
        return Orphan(item.path, item.folder, OrphanState.FAILED, reason=_reason(exc))
    return Orphan(item.path, item.folder, OrphanState.MOVED, moved_to=moved_to)


def _move_steps(project: OrphanProject, sweep: _Sweep, folder: str, extra: frozenset[str],
                pacer: _Pacer) -> Iterator[Any]:
    """Aparta los restos por pasos; en cada paso vuelve a leer lo registrado y lo reclamado."""
    from ..project.model import Progress

    pending = sweep.found
    message = "Apartando restos de operaciones interrumpidas…"
    index = 0
    while index < len(pending) and project.writable:
        protected = _protection(project, sweep.root, extra)
        while index < len(pending):
            item = pending[index]
            index += 1
            item.result = (_move(sweep, folder, item) if _still_orphan(sweep, item, protected)
                           else None)
            if item.result is None:
                sweep.stale.append(item.path)
            if pacer.lap() and index < len(pending):
                yield Progress(PHASES[1], index, len(pending), message)
                pacer.restart()
                break


# --- Los pasos -------------------------------------------------------------------------------


def _steps(project: OrphanProject, root: Path, *, write: bool, limit: int,
           extra: frozenset[str], folder: str, budget: float, record: bool) -> Iterator[Any]:
    from ..project.model import Progress
    from ..project.session import WriteState

    pacer = _Pacer(budget)
    protected = _protection(project, root, extra)
    # Un paso propio (de la fase del listado, sin hacer aún nada de un total de 1): lo que no
    # se aparta es una lectura de todo lo registrado en las carpetas de datos.
    yield Progress(PHASES[0], 0, 1, "Buscando restos de operaciones interrumpidas…")
    pacer.restart()
    survey = _survey(project, protected)
    sweep = _Sweep(root, _tag(project), limit, survey.ignored)
    yield from _list_steps(project, sweep, survey.protected, pacer)
    yield from _snapshot_steps(sweep, survey.protected, pacer)
    sweep.found.sort(key=lambda item: item.path.casefold())
    total = len(sweep.found)
    yield Progress(PHASES[0], total, total, f"Restos encontrados: {total}.")
    pacer.restart()
    if write and total:
        yield from _move_steps(project, sweep, folder, extra, pacer)
    left = set(sweep.stale)
    orphans = tuple(
        item.result if item.result is not None
        else Orphan(item.path, item.folder, OrphanState.FOUND)
        for item in sweep.found if item.result is not None or item.path not in left
    )
    files = tuple(Foreign(ForeignKind.FILE, rel)
                  for rel in sorted(sweep.foreign, key=str.casefold))
    outcome = OrphanOutcome(
        orphans=orphans,
        folder=folder if any(item.state is OrphanState.MOVED for item in orphans) else None,
        recorded=False,
        stale=tuple(sorted(sweep.stale, key=str.casefold)),
        foreign=files + survey.tables,
    )
    news = _news(outcome.foreign, survey.reported)
    if record and write and project.writable and (outcome.moved or news):
        while True:
            attempt = project.try_write(lambda conn: record_orphans(conn, project, outcome))
            if attempt.state is WriteState.DONE:
                break
            yield Progress(PHASES[2], total, total, attempt.message)
        outcome = OrphanOutcome(outcome.orphans, outcome.folder, bool(attempt.value),
                                outcome.stale, outcome.foreign)
    yield Progress(PHASES[2], total, total, _summary(outcome), result=outcome)


def _summary(outcome: OrphanOutcome) -> str:
    return (f"Restos apartados: {len(outcome.moved)}; sin apartar (se reintentará): "
            f"{len(outcome.retry)}; vistos en solo lectura: {len(outcome.found)}; ficheros "
            f"ajenos: {len(outcome.foreign_files)}; capas sin registrar: "
            f"{len(outcome.unregistered_tables)}.")
