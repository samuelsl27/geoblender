# SPDX-License-Identifier: GPL-3.0-or-later
"""La copia de una instantánea por pasos (spec 009; RF-009-07; plan 009 A6, §5.2.5, D-11, D-28,
D-29, D-30 y D-41; ADR-0026).

:func:`copy_steps` copia lo que dice el plan de una congelación (:class:`~.freeze.FreezePlan`)
a la carpeta temporal de su instantánea, ``snapshots/V10.r2.congelando-<8 hex>/``
(:func:`temporary_path`; el barrido de restos solo corre al abrir el proyecto y congelar espera
a la comprobación de apertura, D-40: nadie la aparta mientras dura), en este orden
(:data:`PHASES`):

0. **El espacio** (plan A5 (5)): lo que se copia más un 10 % en ``snapshots/`` y, para el
   GeoPackage, en la caché (si están en el mismo disco, las dos cosas), antes de crear nada.
1. **Cada fichero** (rejilla o malla), por trozos de :data:`CHUNK_BYTES` (uno por paso), con su
   huella a la vez, ``fsync`` cada :data:`SYNC_BYTES` y al final y la fecha del original. Antes
   y después, el tamaño y la fecha del original tienen que ser los anotados en su dato y no
   cambiar (si no, «cambió mientras se congelaba»); después, el **hash de contenido de la
   copia**, con el lector y el normalizador de su dato y por pasos (las mallas, por trozos,
   D-30), tiene que ser el registrado.
2. **Las tablas y capas**: un GeoPackage 1.4 armado en la caché (``application_id``,
   ``user_version``, diario ``DELETE``, sin disparadores ni índice espacial), con cada tabla con
   las mismas columnas que en el proyecto y su nombre en la instantánea, registrada en
   ``gpkg_contents`` (y en ``gpkg_geometry_columns`` con su CRS, el del proyecto, si es una
   capa), y sus filas con su ``fid`` (las de su selector, sin selector, D-29) por pasos de
   :data:`ROWS_PER_STEP` en sentencias de :data:`ROWS_PER_STATEMENT`. La base del proyecto se
   lee sin retener ninguna transacción entre pasos: si otra conexión (QGIS) cambia la tabla
   mientras tanto (su ``last_change`` o su SQL), «cambió mientras se congelaba». Después el
   GeoPackage se copia como un fichero (1) y el hash de contenido de cada tabla **en la copia**,
   sin selector, tiene que ser el registrado.
3. **El manifiesto** (§5.2.5; :func:`write_manifest`): JSON canónico sin sangría, con
   ``fsync``, sin rutas absolutas y en el formato compacto (sin lo que vale lo de por defecto y
   cada fichero de otra instantánea una vez: ``model.compact_manifest``, T33); su huella. Una
   revisión sin nada que copiar tiene solo su manifiesto (D-41). Ningún Parquet (ADR-0026).

El último ``Progress`` lleva el :class:`SnapshotCopy` (los ficheros con su huella, lo congelado
con la huella y el tamaño del fichero de su copia y el manifiesto con la suya): desde entonces
la temporal, completa, es de quien llama, que la renombra (:func:`rename_snapshot`, A6 (4)) o la
descarta (:func:`discard`). Antes, **cancelar** (cerrar los pasos: Esc) o **fallar** (un error,
un dato que cambió, una copia sin su contenido registrado) cierra lo abierto y borra la
temporal, el GeoPackage de la caché y las carpetas que creó: no queda nada (A6 (5)). Nunca
escribe en la base del proyecto ni en sus datos. Si Blender se cierra a medias, la temporal
queda sin revisión que la nombre y la comprobación de apertura la aparta a ``orphans/``
(RF-008-22).

Python puro (ADR-0004): ``sqlite3``, el GeoPackage de ``core.gpkg`` y los lectores de
``core.content``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import time
from collections.abc import Generator, Iterable, Iterator, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Protocol, TypeVar

from ..content import readers
from ..content.builtin import GPKG_LAYER
from ..content.builtin import _selector as selector_condition
from ..datasets.model import DATASET_DECLARATIONS, RECORD_COLUMNS, DatasetRecord, Store
from ..datasets.tracking import table_states
from ..georef.crs import load_catalog
from ..gpkg import base as gpkg_base
from ..gpkg.connection import GpkgConnection
from ..hashing import canonical_json, sha256_bytes
from ..ids import short_uid
from ..paths import check_path_length
from ..project import copytree
from ..project.manifest import PROJECT_STORE
from ..project.model import Progress
from ..provenance.contract import OPERATIONS
from ..timeutil import SYSTEM_CLOCK, Clock, format_utc
from ..version import geoblender_version
from .freeze import FREEZING_MARK, GPKG_BASE_BYTES, SNAPSHOTS_DIR, CopyItem, FreezePlan
from .model import (
    SNAPSHOT_MANIFEST,
    ItemKind,
    ItemPart,
    RevisionItem,
    VersionError,
    compact_manifest,
)

if TYPE_CHECKING:
    from ..project.model import ProjectRecord
    from ..sysinfo import SessionInfo

MANIFEST_NAME = SNAPSHOT_MANIFEST
"""El manifiesto de una instantánea (``snapshots/V10.r2/manifest.json``)."""
MANIFEST_FORMAT = "geoblender-snapshot"
MANIFEST_SCHEMA = 1
"""El formato y su versión, en el manifiesto (§5.2.5; no se migra nunca)."""
CHUNK_BYTES = copytree.CHUNK_SIZE
"""Lo que se lee y se escribe de un fichero en cada paso (8 MiB, como la copia de la 002)."""
SYNC_BYTES = copytree.SYNC_BYTES
"""Cada cuánto se fuerza a disco lo escrito de un fichero (``fsync``, 32 MiB), y al final."""
ROWS_PER_STEP = 5_000
"""Las filas de una tabla que se copian en cada paso (una transacción del GeoPackage)."""
ROWS_PER_STATEMENT = 500
"""Las filas de cada ``INSERT`` (trampa §6: no una sentencia por fila)."""
MAX_VARIABLES = 32_766
"""Los parámetros que admite una sentencia de SQLite (3.32 o posterior)."""
STEP_BUDGET_S = 0.05
"""El trabajo entre dos progresos: agrupa los pasos de dentro (un trozo de un fichero, un paso
de un lector o de unas filas, cada uno corto) hasta este tiempo, como el modal de la 010."""
PHASES: tuple[str, ...] = ("espacio", "copia", "comprobación", "tablas", "manifiesto")
"""Las fases de la copia, en el orden en que empiezan (``Progress.phase``)."""
OWN = "own"
"""Dónde está un contenido (``location`` del manifiesto): en un fichero de esta instantánea,"""
OTHER = "other"
"""… en el de otra instantánea congelada (``path`` relativa al proyecto),"""
PROJECT = "project"
"""… o en el proyecto (lo inmutable: lo importado de una entrada; D-18)."""
_OBJ = "Instantánea"

_T = TypeVar("_T")


class CopyProject(Protocol):
    """Lo que usa la copia del proyecto (``core.project.Project``): su raíz, su identidad y su
    registro (el CRS), la sesión y el reloj (quién y cuándo) y una conexión de lectura."""

    @property
    def root(self) -> Path: ...

    @property
    def uid(self) -> str: ...

    record: ProjectRecord | None
    session: SessionInfo
    clock: Clock

    def read(self) -> AbstractContextManager[sqlite3.Connection]: ...


@dataclass(frozen=True, slots=True)
class SnapshotFile:
    """Un fichero de una instantánea: su ruta en la carpeta (con «/»), su tamaño y su huella."""

    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class SnapshotCopy:
    """Una copia terminada en su carpeta temporal (véase el módulo): la etiqueta de la
    revisión, sus ficheros (sin el manifiesto) y los bytes que suman, lo congelado
    (:class:`~.model.RevisionItem`, en el orden del plan, con la huella y el tamaño del fichero
    de su copia en esta instantánea), la huella y el tamaño del manifiesto, cuándo, quién y con
    qué Geoblender se congeló y lo aceptado (RF-009-08), como va en el manifiesto."""

    temporary: Path
    label: str
    files: tuple[SnapshotFile, ...]
    items: tuple[RevisionItem, ...]
    copied_bytes: int
    manifest_sha256: str
    manifest_size: int
    frozen_at: str
    frozen_by: str
    geoblender_version: str
    accepted: Mapping[str, Any] | None


# --- Rutas, espacio y errores ---------------------------------------------------------------


def temporary_path(root: Path, label: str) -> Path:
    """La carpeta temporal de la instantánea ``label`` del proyecto ``root``:
    ``snapshots/<label>.congelando-<8 hex>`` (no la crea)."""
    return Path(root) / SNAPSHOTS_DIR / f"{label}{FREEZING_MARK}{short_uid()}"


def _budget(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"el presupuesto de un paso es un número de segundos, no {value!r}")
    if not value > 0:
        raise ValueError(f"el presupuesto de un paso es positivo, no {value!r}")
    return float(value)


def _size_text(size: int) -> str:
    """Un tamaño como lo lee una persona (unidades decimales, coma decimal)."""
    for unit, factor in (("GB", 10**9), ("MB", 10**6), ("kB", 10**3)):
        if size >= factor:
            return f"{size / factor:.1f} {unit}".replace(".", ",")
    return f"{size} B"


def _existing(path: Path) -> Path:
    """``path`` o su primera carpeta madre que existe (la del disco en que se escribirá)."""
    current = Path(path)
    while not current.exists() and current.parent != current:
        current = current.parent
    return current


def _check_space(plan: FreezePlan, snapshots: Path, cache: Path,
                 disk_usage: copytree.DiskUsageFn) -> None:
    """Lo que se copia más un 10 % en ``snapshots`` y el GeoPackage en ``cache`` (plan A5
    (5)); en el mismo disco, las dos cosas. ``VersionError`` si no cabe."""
    wanted: dict[int, tuple[Path, Path, int]] = {}
    for shown, needed in ((snapshots, plan.space_needed), (cache, plan.cache_needed)):
        if not needed:
            continue
        probe = _existing(shown)
        device = os.stat(probe).st_dev
        first, where, total = wanted.get(device, (shown, probe, 0))
        wanted[device] = (first, where, total + needed)
    for shown, probe, needed in wanted.values():
        free = int(disk_usage(probe).free)
        if free < needed:
            raise VersionError("core.version_freeze_no_space", field="espacio libre", value=free,
                               version=plan.version.code, revision=plan.label,
                               needed=_size_text(needed), folder=str(shown),
                               free=_size_text(free))


def _changed(plan: FreezePlan, record: DatasetRecord) -> VersionError:
    return VersionError("core.version_freeze_changed", field="dato", value=record.name,
                        version=plan.version.code, revision=plan.label, dataset=record.name)


def _mismatch(plan: FreezePlan, record: DatasetRecord) -> VersionError:
    return VersionError("core.version_freeze_mismatch", field="hash de contenido",
                        value=record.name, version=plan.version.code, revision=plan.label,
                        dataset=record.name)


def _failed(label: str, exc: BaseException, file: str, version: str | None = None
            ) -> VersionError:
    reason = getattr(exc, "strerror", None) or str(exc) or type(exc).__name__
    return VersionError("core.version_freeze_failed", field="fichero", value=file,
                        version=version, revision=label, reason=reason, file=file)


# --- Pasos ----------------------------------------------------------------------------------


class _Pacer:
    """Dice cuándo dar el progreso: tras ``budget`` s de trabajo propio desde el último."""

    def __init__(self, budget: float) -> None:
        self.budget = budget
        self.restart()

    def restart(self) -> None:
        self.started = time.perf_counter()

    def due(self) -> bool:
        return time.perf_counter() - self.started >= self.budget


class _Meter:
    """El avance de la copia: cada tarea, con su peso, de una en una (nunca retrocede)."""

    def __init__(self, total: int) -> None:
        self.total = max(1, total)
        self.base = 0
        self.done = 0

    def at(self, weight: int, fraction: float) -> int:
        value = self.base + int(weight * min(1.0, max(0.0, fraction)))
        self.done = max(self.done, min(value, self.total))
        return self.done

    def finish(self, weight: int) -> None:
        self.base += weight
        self.done = max(self.done, min(self.base, self.total))


def _drive(inner: Generator[float, None, _T], pacer: _Pacer, meter: _Meter, phase: str,
           message: str, weight: int) -> Generator[Progress, None, _T]:
    """Lleva ``inner`` (su avance, de 0 a 1) y da su progreso cuando toca; al acabar, su
    resultado y la tarea hecha. Cerrarlo a medias cierra ``inner`` (lo que abrió)."""
    try:
        while True:
            try:
                fraction = next(inner)
            except StopIteration as stop:
                meter.finish(weight)
                return stop.value
            if pacer.due():
                yield Progress(phase, meter.at(weight, fraction), meter.total, message)
                pacer.restart()
    finally:
        inner.close()


def _stat(path: Path) -> tuple[int, int] | None:
    try:
        found = os.stat(path)
    except FileNotFoundError:
        return None
    return found.st_size, found.st_mtime_ns


def _open_source(path: Path, clock: Clock) -> IO[bytes]:
    """Abre un fichero del proyecto para leerlo, con reintentos si otro programa lo retiene
    (el antivirus, un indexador: como la copia de la 002)."""
    for attempt in range(copytree.RETRIES + 1):
        try:
            return Path(path).open("rb")
        except PermissionError:
            if attempt == copytree.RETRIES:
                raise
            clock.sleep(copytree.RETRY_WAIT_S)
    raise AssertionError("inalcanzable")  # pragma: no cover


def _copy_file(source: Path, target: Path, clock: Clock
               ) -> Generator[float, None, tuple[int, str]]:
    """Copia ``source`` en ``target`` (que no existe) por trozos de :data:`CHUNK_BYTES`, con
    su huella a la vez, ``fsync`` cada :data:`SYNC_BYTES` y al final y la fecha del original;
    da lo copiado (0–1) tras cada trozo y devuelve el tamaño y la huella."""
    digest = hashlib.sha256()
    size = unsynced = 0
    with _open_source(source, clock) as reader, target.open("xb") as writer:
        total = max(1, os.fstat(reader.fileno()).st_size)
        while chunk := reader.read(CHUNK_BYTES):
            writer.write(chunk)
            digest.update(chunk)
            size += len(chunk)
            unsynced += len(chunk)
            if unsynced >= SYNC_BYTES:  # el fsync final de un fichero grande no para el
                writer.flush()  # progreso (RNF-009-02; trampa §6)
                os.fsync(writer.fileno())
                unsynced = 0
            yield min(1.0, size / total)
        writer.flush()
        os.fsync(writer.fileno())
    stat = os.stat(source)
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    return size, digest.hexdigest()


def _content_steps(content_reader: readers.ContentReader, record: DatasetRecord, path: Path,
                   settings: Mapping[str, Any] | None = None) -> Generator[float, None, str]:
    """El hash de contenido de ``path`` con el lector y el normalizador de ``record``, sin
    declaraciones (el de un dato, ADR-0024 §6), por pasos."""
    request = content_reader.request(record.kind, DATASET_DECLARATIONS, {"main": path},
                                     settings, normalizer=record.normalizer)
    steps = readers.read_steps(content_reader, request)
    try:
        yield from steps
    finally:
        steps.close()
    return request.hasher.digest().content_sha256


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


@dataclass(frozen=True)
class _Table:
    """Una tabla del proyecto que va al GeoPackage de la instantánea con el nombre ``layer``:
    sus columnas (``PRAGMA table_info``), su clave entera, su condición de selector, su fila de
    ``gpkg_contents`` y la de ``gpkg_geometry_columns`` si es una capa."""

    record: DatasetRecord
    layer: str
    columns: tuple[tuple[str, str, bool, str | None], ...]
    alias: str | None
    condition: str
    params: tuple[object, ...]
    contents: tuple[Any, ...]
    geometry: tuple[Any, ...] | None

    @classmethod
    def describe(cls, source: sqlite3.Connection, record: DatasetRecord,
                 layer: str) -> _Table | None:
        """La tabla de ``record`` en la base del proyecto, o ``None`` si ya no está."""
        locator = record.locator
        info = source.execute(
            'SELECT name, type, "notnull", dflt_value, pk FROM pragma_table_info(?) ORDER BY cid',
            (locator,)).fetchall()
        contents = source.execute(
            "SELECT data_type, identifier, description, last_change, min_x, min_y, max_x, "
            "max_y, srs_id FROM gpkg_contents WHERE table_name = ?", (locator,)).fetchone()
        if not info or contents is None:
            return None
        keys = [row for row in info if row[4]]
        alias = None
        if len(keys) == 1 and str(keys[0][1]).strip().upper() == "INTEGER":
            alias = str(keys[0][0])
        geometry = source.execute(
            "SELECT column_name, geometry_type_name, srs_id, z, m FROM gpkg_geometry_columns "
            "WHERE table_name = ?", (locator,)).fetchone()
        names = [str(row[0]) for row in info]
        condition, params = selector_condition(source, record.selector, names, locator)
        columns = tuple((str(name), str(kind or ""), bool(not_null),
                         None if default is None else str(default))
                        for name, kind, not_null, default, _pk in info)
        return cls(record, layer, columns, alias, condition, tuple(params), tuple(contents),
                   None if geometry is None else tuple(geometry))

    def create(self, conn: sqlite3.Connection, source: sqlite3.Connection,
               identifiers: set[str]) -> None:
        """La tabla vacía en el GeoPackage de la instantánea (``conn``, en su transacción):
        sus columnas, el SRS que usa (copiado del proyecto si falta) y sus filas de
        ``gpkg_contents`` y ``gpkg_geometry_columns``."""
        parts = []
        for name, kind, not_null, default in self.columns:
            if name == self.alias:
                parts.append(f"{_quote(name)} INTEGER PRIMARY KEY AUTOINCREMENT"
                             + (" NOT NULL" if not_null else ""))
                continue
            parts.append(" ".join([_quote(name), *([kind] if kind else []),
                                   *(["NOT NULL"] if not_null else []),
                                   *([f"DEFAULT {default}"] if default is not None else [])]))
        conn.execute(f"CREATE TABLE {_quote(self.layer)} ({', '.join(parts)})")
        data_type, identifier, description, last_change, *extent, srs_id = self.contents
        for srs in {srs_id, None if self.geometry is None else self.geometry[2]} - {None}:
            if conn.execute("SELECT 1 FROM gpkg_spatial_ref_sys WHERE srs_id = ?",
                            (srs,)).fetchone() is None:
                row = source.execute(
                    "SELECT srs_name, srs_id, organization, organization_coordsys_id, "
                    "definition, description FROM gpkg_spatial_ref_sys WHERE srs_id = ?",
                    (srs,)).fetchone()
                if row is not None:
                    conn.execute(
                        "INSERT INTO gpkg_spatial_ref_sys (srs_name, srs_id, organization, "
                        "organization_coordsys_id, definition, description) "
                        "VALUES (?, ?, ?, ?, ?, ?)", row)
        shown = str(identifier) if identifier else self.layer
        if shown in identifiers:
            shown = self.layer
        number = 2
        while shown in identifiers:
            shown = f"{self.layer} ({number})"
            number += 1
        identifiers.add(shown)
        conn.execute(
            "INSERT INTO gpkg_contents (table_name, data_type, identifier, description, "
            "last_change, min_x, min_y, max_x, max_y, srs_id) "
            "VALUES (?, ?, ?, ?, coalesce(?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), "
            "?, ?, ?, ?, ?)",
            (self.layer, data_type, shown, description if description is not None else "",
             last_change, *extent, srs_id))
        if self.geometry is not None:
            column, geometry_type, srs, z, m = self.geometry
            conn.execute(
                "INSERT INTO gpkg_geometry_columns (table_name, column_name, "
                "geometry_type_name, srs_id, z, m) VALUES (?, ?, ?, ?, ?, ?)",
                (self.layer, column, geometry_type, srs, z, m))

    def rows(self, source: sqlite3.Connection, build: GpkgConnection
             ) -> Generator[float, None, int]:
        """Sus filas (las de su selector), por pasos de :data:`ROWS_PER_STEP` en el orden de
        su clave (cada paso, una lectura corta de la base del proyecto y una transacción del
        GeoPackage); da la posición alcanzada (0–1) tras cada paso y devuelve las filas."""
        locator = _quote(self.record.locator)
        key = _quote(self.alias) if self.alias else "rowid"
        others = [_quote(name) for name, *_rest in self.columns if name != self.alias]
        selected = ", ".join([key, *others])
        targets = ([_quote(self.alias)] if self.alias else []) + others
        where = f" AND ({self.condition})" if self.condition else ""
        first = (f"SELECT {selected} FROM {locator}"
                 f"{f' WHERE {self.condition}' if self.condition else ''} ORDER BY {key} LIMIT ?")
        following = (f"SELECT {selected} FROM {locator} WHERE {key} > ?{where} "
                     f"ORDER BY {key} LIMIT ?")
        low, high = source.execute(f"SELECT min({key}), max({key}) FROM {locator}").fetchone()
        span = (high - low + 1) if isinstance(low, int) and isinstance(high, int) else 0
        per_statement = max(1, min(ROWS_PER_STATEMENT, MAX_VARIABLES // max(1, len(targets))))
        limit = ROWS_PER_STEP
        marks = "(" + ", ".join("?" for _ in targets) + ")"
        names = ", ".join(targets)
        count = 0
        last: object = None
        while True:
            values = (*self.params, limit) if last is None else (last, *self.params, limit)
            found = source.execute(first if last is None else following, values).fetchall()
            if found:
                rows = found if self.alias else [row[1:] for row in found]
                with build.transaction() as conn:
                    for start in range(0, len(rows), per_statement):
                        part = rows[start:start + per_statement]
                        conn.execute(
                            f"INSERT INTO {_quote(self.layer)} ({names}) VALUES "
                            f"{', '.join(marks for _ in part)}",
                            [value for row in part for value in row])
                count += len(found)
                last = found[-1][0]
            if len(found) < limit:
                yield 1.0
                return count
            yield (last - low + 1) / span if span and isinstance(last, int) else 0.0


def _same_state(source: sqlite3.Connection, locator: str, before: Any) -> bool:
    after = table_states(source, [locator])[locator]
    return (after.exists, after.last_change, after.schema_sha256) == (
        before.exists, before.last_change, before.schema_sha256)


def _remove_file(path: Path) -> None:
    for candidate in (path, path.with_name(path.name + "-journal")):
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            pass


@dataclass
class _Workspace:
    """Lo que crea una copia (la temporal, el GeoPackage de la caché y las carpetas que no
    estaban) para quitarlo si no termina."""

    temporary: Path
    build: Path
    clock: Clock
    created: list[Path]
    built: bool = False

    def make(self, folder: Path) -> None:
        """Crea ``folder`` y las carpetas que le faltan (y las anota)."""
        missing: list[Path] = []
        current = folder
        while not current.exists():
            missing.append(current)
            current = current.parent
        for item in reversed(missing):
            item.mkdir()
            self.created.append(item)

    def tidy(self) -> None:
        """Quita las carpetas que creó y quedaron vacías (no la temporal)."""
        for folder in reversed(self.created):
            if folder == self.temporary:
                continue
            try:
                folder.rmdir()
            except OSError:
                pass

    def clean(self) -> None:
        """Lo quita todo: el GeoPackage de la caché, la temporal y las carpetas que creó (nada
        que ya estuviera)."""
        if self.built:
            _remove_file(self.build)
        if self.temporary in self.created and self.temporary.exists():
            copytree.remove_tree(self.temporary, self.clock)
        self.tidy()


# --- La copia -------------------------------------------------------------------------------


def copy_steps(project: CopyProject, plan: FreezePlan, temporary: Path, cache: Path, *,
               budget_s: float = STEP_BUDGET_S, accepted: Mapping[str, Any] | None = None,
               disk_usage: copytree.DiskUsageFn = shutil.disk_usage) -> Iterator[Progress]:
    """Copia lo que dice ``plan`` en ``temporary`` (``snapshots/<revisión>.congelando-<8
    hex>``, de :func:`temporary_path`, que no debe existir), armando el GeoPackage en ``cache``
    (la caché del proyecto, local también con el proyecto en la red): véase el módulo. Da su
    progreso (:data:`PHASES`) tras unos ``budget_s`` s de trabajo (los pasos de dentro, cortos,
    se agrupan hasta ese tiempo); el último ``Progress`` lleva el :class:`SnapshotCopy`.
    ``accepted``: lo aceptado (:func:`acceptance`), tal como va al manifiesto; ``disk_usage``,
    el de ``shutil`` (inyectable).

    ``VersionError``: sin espacio (``core.version_freeze_no_space``), un dato que cambió
    mientras se copiaba (``core.version_freeze_changed``), una copia sin su contenido
    registrado (``core.version_freeze_mismatch``) o un error del disco
    (``core.version_freeze_failed``); ``ProjectError`` si una ruta pasa del límite de Windows;
    los de los lectores (``core.reader_unregistered``…), tal cual. En todos los casos, y al
    cerrar los pasos antes del último, no queda nada."""
    budget = _budget(budget_s)
    root = Path(project.root)
    temporary, cache = Path(temporary), Path(cache)
    snapshots = root / SNAPSHOTS_DIR
    label = plan.label
    if temporary.parent != snapshots or not temporary.name.startswith(f"{label}{FREEZING_MARK}"):
        raise ValueError(f"la carpeta temporal de {label} es «{SNAPSHOTS_DIR}/{label}"
                         f"{FREEZING_MARK}<8 hex>» del proyecto, no «{temporary}»")
    files = [copy for copy in plan.to_copy if copy.record.store is not Store.GPKG]
    tables = [copy for copy in plan.to_copy if copy.record.store is Store.GPKG]
    targets = {copy.record.uid: _inside(plan, copy) for copy in plan.to_copy}
    gpkg_name = f"{label}.gpkg"
    build = cache / f"{temporary.name}.gpkg"
    gpkg_weight = GPKG_BASE_BYTES + sum(max(1, copy.size) for copy in tables)
    total = (sum(2 * max(1, copy.size) for copy in plan.to_copy)
             + (gpkg_weight if tables else 0) + 1)
    meter = _Meter(total)
    yield Progress(PHASES[0], 0, meter.total, "Comprobando el espacio libre…")
    for rel in {*targets.values(), MANIFEST_NAME}:
        check_path_length(temporary.joinpath(*rel.split("/")), obj=_OBJ)
    if tables:
        check_path_length(build, obj=_OBJ)
    try:
        _check_space(plan, snapshots, cache, disk_usage)
    except OSError as exc:
        raise _failed(label, exc, SNAPSHOTS_DIR, plan.version.code) from exc

    workspace = _Workspace(temporary, build, project.clock, [])
    pacer = _Pacer(budget)
    current = SNAPSHOTS_DIR
    finished = False
    try:
        try:
            workspace.make(snapshots)
            temporary.mkdir()
            workspace.created.append(temporary)
            own: list[SnapshotFile] = []
            for copy in files:
                record = copy.record
                rel = targets[record.uid]
                name = rel.rpartition("/")[2]
                current = record.locator
                source = root.joinpath(*record.locator.split("/"))
                target = temporary.joinpath(*rel.split("/"))
                workspace.make(target.parent)
                before = _stat(source)
                recorded = (record.tracked_size, record.tracked_mtime_ns)
                if before is None or (None not in recorded and before != recorded):
                    raise _changed(plan, record)
                weight = max(1, copy.size)
                size, sha = yield from _drive(_copy_file(source, target, project.clock), pacer,
                                              meter, "copia", f"Copiando «{name}»…", weight)
                if _stat(source) != before:
                    raise _changed(plan, record)
                content = yield from _drive(
                    _content_steps(readers.reader(record.reader), record, target), pacer, meter,
                    "comprobación", f"Comprobando «{name}»…", weight)
                if content != record.content_sha256:
                    raise _mismatch(plan, record)
                own.append(SnapshotFile(rel, size, sha))
            if tables:
                current = gpkg_name
                gpkg = yield from _table_steps(project, plan, tables, workspace, pacer, meter,
                                               cache, gpkg_weight)
                own.append(gpkg)
                for copy in tables:
                    current = copy.record.locator
                    content = yield from _drive(
                        _content_steps(GPKG_LAYER, copy.record, temporary / gpkg_name,
                                       {"layer": copy.snapshot_layer}), pacer, meter,
                        "comprobación", f"Comprobando «{copy.record.locator}»…",
                        max(1, copy.size))
                    if content != copy.record.content_sha256:
                        raise _mismatch(plan, copy.record)
            current = MANIFEST_NAME
            yield Progress(PHASES[4], meter.done, meter.total, "Escribiendo el manifiesto…")
            frozen_at = format_utc(project.clock.now())
            frozen_by = project.session.user_host
            software = geoblender_version()
            items = _with_files(plan, own)
            with project.read() as conn:
                body = _manifest_body(conn, project.uid, plan, own, items,
                                      frozen_at=frozen_at, frozen_by=frozen_by,
                                      software=software, accepted=accepted)
            manifest_sha256 = write_manifest(temporary, body)
            manifest_size = (temporary / MANIFEST_NAME).stat().st_size
        except (OSError, sqlite3.Error) as exc:
            raise _failed(label, exc, current, plan.version.code) from exc
        meter.finish(1)
        finished = True
        workspace.tidy()  # la caché, si la creó y quedó vacía
    finally:
        if not finished:
            workspace.clean()
    yield Progress(PHASES[4], meter.total, meter.total, f"{label} copiada",
                   result=SnapshotCopy(
                       temporary=temporary, label=label, files=tuple(own), items=items,
                       copied_bytes=sum(item.size for item in own),
                       manifest_sha256=manifest_sha256, manifest_size=manifest_size,
                       frozen_at=frozen_at, frozen_by=frozen_by, geoblender_version=software,
                       accepted=accepted))


def _inside(plan: FreezePlan, copy: CopyItem) -> str:
    """La ruta de la copia de ``copy`` dentro de la carpeta de la instantánea."""
    prefix = f"{plan.snapshot_dir}/"
    if not copy.snapshot_path.startswith(prefix):
        raise ValueError(f"la copia de «{copy.record.name}» va a «{copy.snapshot_path}», fuera "
                         f"de «{plan.snapshot_dir}»")
    return copy.snapshot_path[len(prefix):]


def _table_steps(project: CopyProject, plan: FreezePlan, tables: list[CopyItem],
                 workspace: _Workspace, pacer: _Pacer, meter: _Meter, cache: Path,
                 gpkg_weight: int) -> Generator[Progress, None, SnapshotFile]:
    """El GeoPackage de la instantánea: armado en la caché tabla a tabla (cada una con sus
    filas, comprobando que la del proyecto no cambia mientras tanto) y copiado después a la
    temporal como un fichero; su huella."""
    if project.record is None:  # pragma: no cover - una congelación tiene la base
        raise ValueError("el proyecto se abrió solo con su cabecera: no tiene tablas")
    crs = load_catalog().horizontal(project.record.crs_epsg)
    workspace.make(cache)
    if workspace.build.exists():
        raise FileExistsError(f"ya existe «{workspace.build.name}» en la caché")
    workspace.built = True
    with GpkgConnection.open_write(workspace.build, create=True) as build:
        with build.transaction() as conn:
            gpkg_base.create_base(conn, crs)
        identifiers: set[str] = set()
        with project.read() as source:
            for copy in tables:
                record = copy.record
                before = table_states(source, [record.locator])[record.locator]
                table = _Table.describe(source, record, str(copy.snapshot_layer))
                if table is None:
                    raise _changed(plan, record)
                with build.transaction() as conn:
                    table.create(conn, source, identifiers)
                yield from _drive(table.rows(source, build), pacer, meter, "tablas",
                                  f"Copiando las filas de «{record.locator}»…",
                                  max(1, copy.size))
                if not _same_state(source, record.locator, before):
                    raise _changed(plan, record)
    gpkg_name = f"{plan.label}.gpkg"
    size, sha = yield from _drive(
        _copy_file(workspace.build, workspace.temporary / gpkg_name, project.clock), pacer,
        meter, "tablas", f"Copiando «{gpkg_name}»…", gpkg_weight)
    _remove_file(workspace.build)
    return SnapshotFile(gpkg_name, size, sha)


def _with_files(plan: FreezePlan, own: list[SnapshotFile]) -> tuple[RevisionItem, ...]:
    """Lo congelado del plan con la huella y el tamaño del fichero de su copia en esta
    instantánea (lo copiado y lo que referencia un contenido repetido dentro del plan)."""
    prefix = f"{plan.snapshot_dir}/"
    found = {f"{prefix}{item.path}": item for item in own}
    return tuple(
        replace(item, file_sha256=found[item.snapshot_path].sha256,
                file_size=found[item.snapshot_path].size)
        if item.snapshot_path in found else item
        for item in plan.items)


# --- El manifiesto --------------------------------------------------------------------------


def acceptance(plan: FreezePlan, *, reason: str) -> dict[str, Any] | None:
    """Lo aceptado al congelar (RF-009-08), como va al manifiesto: el motivo y lo que había que
    aceptar (``FreezePlan.accept``: qué es, su uid, su nombre, su estado y su texto); ``None``
    si no había nada que aceptar."""
    if not plan.accept:
        return None
    return {"reason": reason, "items": [
        {"item_kind": str(entry.item_kind), "item_uid": entry.item_uid, "name": entry.name,
         "state": str(entry.state), "text": entry.text}
        for entry in plan.accept]}


def write_manifest(temporary: Path, body: Mapping[str, Any]) -> str:
    """Escribe ``body`` (el manifiesto entero de §5.2.5) como ``manifest.json`` de la carpeta
    ``temporary``, en el formato compacto (``model.compact_manifest``: sin lo que vale lo de
    por defecto y cada fichero de otra instantánea una vez; T33, RNF-009-06), en JSON canónico
    sin sangría y UTF-8, con ``fsync``; devuelve su huella (``gb_revision.snapshot_sha256``).
    Quien lo lee, entero (``model.expand_manifest``)."""
    data = canonical_json(compact_manifest(body))
    with (Path(temporary) / MANIFEST_NAME).open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return sha256_bytes(data)


def _select(conn: sqlite3.Connection, sql: str, values: Iterable[str]) -> list[tuple[Any, ...]]:
    found: list[tuple[Any, ...]] = []
    items = list(dict.fromkeys(values))
    for start in range(0, len(items), 500):
        chunk = items[start:start + 500]
        found.extend(conn.execute(sql.format(marks=", ".join("?" for _ in chunk)), chunk))
    return found


def _location(plan: FreezePlan, item: RevisionItem, record: DatasetRecord | None
              ) -> tuple[str | None, str | None, str | None]:
    """Dónde está el contenido congelado de un dato: (dónde, ruta, capa)."""
    prefix = f"{plan.snapshot_dir}/"
    if item.snapshot_path is not None and item.snapshot_path.startswith(prefix):
        return OWN, item.snapshot_path[len(prefix):], item.snapshot_layer
    if item.snapshot_path is not None:
        return OTHER, item.snapshot_path, item.snapshot_layer
    if item.part is ItemPart.IMMUTABLE and record is not None:
        if record.store is Store.GPKG:
            return PROJECT, PROJECT_STORE, record.locator
        return PROJECT, record.locator, None
    return None, None, None


def _manifest_body(conn: sqlite3.Connection, project_uid: str, plan: FreezePlan,
                   own: list[SnapshotFile], items: tuple[RevisionItem, ...], *, frozen_at: str,
                   frozen_by: str, software: str,
                   accepted: Mapping[str, Any] | None) -> dict[str, Any]:
    """El manifiesto de §5.2.5, con lo que lee de la base del proyecto (``conn``) lo que no
    trae el plan: los datos que no se copian, las entradas con sus originales, los parámetros,
    las operaciones y las cifras. Sin rutas absolutas."""
    by_kind: dict[ItemKind, list[RevisionItem]] = {kind: [] for kind in ItemKind}
    for item in items:
        by_kind[item.item_kind].append(item)
    records = {copy.record.uid: copy.record for copy in plan.to_copy}
    missing = [item.item_uid for item in by_kind[ItemKind.DATASET] if item.item_uid not in records]
    for row in _select(conn, f"SELECT {', '.join(RECORD_COLUMNS)} FROM gb_dataset "
                             "WHERE uid IN ({marks})", missing):
        record = DatasetRecord.from_row(tuple(row))
        records[record.uid] = record
    datasets = []
    for item in by_kind[ItemKind.DATASET]:
        record = records.get(item.item_uid)
        location, path, layer = _location(plan, item, record)
        datasets.append({
            "uid": item.item_uid,
            "name": None if record is None else record.name,
            "kind": None if record is None else record.kind,
            "store": None if record is None else str(record.store),
            "reader": None if record is None else record.reader,
            "normalizer": None if record is None else record.normalizer,
            "selector": None if record is None else record.selector,
            "content_sha256": item.content_sha256, "part": str(item.part),
            "state": str(item.state), "location": location, "path": path, "layer": layer,
        })
    inputs_wanted = [item.item_uid for item in by_kind[ItemKind.INPUT]]
    inputs = {str(uid): (str(name), str(content)) for uid, name, content in _select(
        conn, "SELECT uid, name, content_sha256 FROM gb_input WHERE uid IN ({marks})",
        inputs_wanted)}
    originals: dict[str, list[dict[str, Any]]] = {}
    for uid, path, size, sha in _select(
            conn, "SELECT input_uid, original_path, original_size, original_sha256 "
                  "FROM gb_input_file WHERE input_uid IN ({marks}) AND original_path IS NOT NULL "
                  "ORDER BY input_uid, ord", inputs_wanted):
        originals.setdefault(str(uid), []).append({"path": path, "size": size, "sha256": sha})
    parameters = {str(uid): (str(key), str(scope), str(scope_uid)) for uid, key, scope, scope_uid
                  in _select(conn, "SELECT uid, key, scope, scope_uid FROM gb_parameter "
                                   "WHERE uid IN ({marks})",
                             [item.item_uid for item in by_kind[ItemKind.PARAMETER]])}
    operations = {str(uid): (str(op_type), str(op_version), str(module))
                  for uid, op_type, op_version, module in _select(
                      conn, "SELECT uid, op_type, op_version, module FROM gb_operation "
                            "WHERE uid IN ({marks})",
                      [item.item_uid for item in by_kind[ItemKind.OPERATION]])}
    figures = {str(row[0]): row[1:] for row in _select(
        conn, "SELECT uid, key, value, unit, kind, scope, operation_uid FROM gb_figure "
              "WHERE uid IN ({marks})", [item.item_uid for item in by_kind[ItemKind.FIGURE]])}

    def common(item: RevisionItem) -> dict[str, Any]:
        return {"uid": item.item_uid, "part": str(item.part), "state": str(item.state)}

    def reproducible(op_type: str | None) -> bool | None:
        definition = None if op_type is None else OPERATIONS.get(op_type)
        return None if definition is None else definition.reproduce is not None

    return {
        "format": MANIFEST_FORMAT,
        "schema": MANIFEST_SCHEMA,
        "project_uid": project_uid,
        "revision_uid": plan.revision.uid,
        "revision": plan.label,
        "version_uid": plan.version.uid,
        "frozen_at": frozen_at,
        "frozen_by": frozen_by,
        "geoblender_version": software,
        "files": [{"path": item.path, "size": item.size, "sha256": item.sha256} for item in own],
        "datasets": datasets,
        "inputs": [{**common(item), "name": inputs.get(item.item_uid, (None, None))[0],
                    "content_sha256": item.content_sha256,
                    "originals": originals.get(item.item_uid, [])}
                   for item in by_kind[ItemKind.INPUT]],
        "parameters": [{**common(item), "key": parameters.get(item.item_uid, (None,) * 3)[0],
                        "scope": parameters.get(item.item_uid, (None,) * 3)[1],
                        "scope_uid": parameters.get(item.item_uid, (None,) * 3)[2],
                        "rev": item.item_rev, "value_sha256": item.content_sha256}
                       for item in by_kind[ItemKind.PARAMETER]],
        "operations": [{**common(item),
                        "op_type": operations.get(item.item_uid, (None,) * 3)[0],
                        "op_version": operations.get(item.item_uid, (None,) * 3)[1],
                        "module": operations.get(item.item_uid, (None,) * 3)[2],
                        "reproducible": reproducible(
                            operations.get(item.item_uid, (None,) * 3)[0])}
                       for item in by_kind[ItemKind.OPERATION]],
        "figures": [_figure(common(item), figures.get(item.item_uid))
                    for item in by_kind[ItemKind.FIGURE]],
        "accepted": None if accepted is None else dict(accepted),
    }


def _figure(entry: dict[str, Any], row: tuple[Any, ...] | None) -> dict[str, Any]:
    if row is None:
        return {**entry, "key": None, "value": None, "unit": None, "kind": None, "scope": None,
                "operation_uid": None}
    key, value, unit, kind, scope, operation_uid = row
    try:
        shown = json.loads(scope) if scope else {}
    except ValueError:
        shown = scope
    return {**entry, "key": key, "value": None if value is None else float(value), "unit": unit,
            "kind": kind, "scope": shown, "operation_uid": operation_uid}


# --- Después de copiar ----------------------------------------------------------------------


def rename_snapshot(temporary: Path, final: Path, *, clock: Clock = SYSTEM_CLOCK) -> Path:
    """Da a la temporal su nombre (``snapshots/V10.r2``, plan A6 (4)), con reintentos si otro
    programa la retiene, y la vuelve a listar con él (en la red, para poder sustituir después
    un fichero de dentro; trampa §6). Unos restos con ese nombre (un cierre a medias) no se
    sustituyen: ``VersionError`` ``core.version_freeze_leftover`` (la temporal queda: quien
    llama la descarta). Devuelve ``final``."""
    temporary, final = Path(temporary), Path(final)
    folder = f"{SNAPSHOTS_DIR}/{final.name}"
    label = final.name
    for attempt in range(copytree.RETRIES + 1):
        if final.exists():
            raise VersionError("core.version_freeze_leftover", field="carpeta", value=folder,
                               revision=label, folder=folder)
        try:
            os.rename(temporary, final)
            break
        except FileExistsError:
            continue
        except PermissionError as exc:
            if attempt == copytree.RETRIES:
                raise _failed(label, exc, folder) from exc
            clock.sleep(copytree.RETRY_WAIT_S)
        except OSError as exc:
            raise _failed(label, exc, folder) from exc
    copytree.refresh_listing(final)
    return final


def discard(temporary: Path, *, clock: Clock = SYSTEM_CLOCK) -> None:
    """Descarta una copia terminada que no se va a confirmar: borra la temporal (``snapshots/``
    es del proyecto y se queda)."""
    copytree.remove_tree(Path(temporary), clock)

