# SPDX-License-Identifier: GPL-3.0-or-later
"""Resultados de la topografía en el proyecto (spec 006, T42; RF-006-08, RF-006-26, RF-006-28;
RF-008-17, RF-008-18, RF-008-19, RF-008-23; ADR-0025 §3 y §8; plan 006 §5.2, §5.6.4 y §5.6.5;
D20).

Lo que produce una operación de la 006 se guarda en el proyecto con la API de procedencia de la
008, nunca escribiendo en las tablas ``gb_*``:

- **rejillas** en ``rasters/`` (GeoTIFF del perfil ``project``: Float64, NaN, cada celda con
  los mismos bits, RF-006-08), **TIN** en ``meshes/`` (npz de ``gis.tin.save_tin`` con su
  ``meta``) y **curvas de nivel** en una tabla ``gis_cnt_<nombre>`` de ``project.gpkg`` (plan
  §5.2.3: capa ``LINESTRING`` con Z, creada con ``core.gpkg.create_feature_table(...,
  has_z=True)``, el SRS del proyecto y la referencia vertical citada en su descripción; cada
  curva cerrada repite su primer vértice al final); cada una con la ``DatasetSpec`` de
  ``gis.provenance`` (su nombre, su almacén, su ubicación y su lector) y su ``ContentDigest``:
  el que da su lector al leer lo escrito, calculado aquí sin volver a leerlo
  (``gis.content.raster_digest`` y ``tin_digest``), el que trae el resultado de un trabajo de
  la 004 o, en una tabla, el que calcula el registro de la 008 en la transacción que la
  escribe.

:class:`ResultWriter` (un gestor de contexto por operación, con su ``OperationHandle``) sigue
el flujo del plan §5.6.4:

1. **Preparar** (:meth:`~ResultWriter.raster`, :meth:`~ResultWriter.tin`,
   :meth:`~ResultWriter.copy_file`, el de un trabajo, y :meth:`~ResultWriter.contours`): se
   comprueba que el sitio del resultado está libre o es del mismo dato (si no,
   ``gis.output_target_taken``, sin escribir nada), se reclaman con
   ``OperationHandle.claim_paths`` el temporal, el destino y la copia del anterior, y cada
   fichero se escribe entero en su temporal ``<fichero>.tmp-<sesión>`` (el patrón de restos de
   la 008, plan 008 §5.4.9: :func:`temporary_path`; el escritor de T07 recibe el nombre). Las
   filas de una tabla se codifican ya.
2. **Poner en su sitio** (:meth:`~ResultWriter.install`, antes de la transacción): el
   fichero anterior del mismo dato se aparta a ``<fichero>.old.tmp-<sesión>`` y el temporal
   pasa a su sitio con ``os.replace``. Si otro programa tiene abierto el destino (QGIS),
   ``gis.raster_target_locked``: no se escribe nada y el anterior sigue intacto (sin
   ``<nombre>__<hash8>.tif``, D20: la 008 no cambia la ubicación de un dato vivo).
3. **Confirmar** (:meth:`~ResultWriter.commit`, o :meth:`~ResultWriter.write` como función de
   escritura de ``ingest_job`` al incorporar un trabajo): en una transacción de
   ``Project.write_transaction``, las tablas y ``OperationHandle.complete`` con las salidas,
   ``software``, el intérprete, el ejecutor y el mensaje (RF-008-18). Confirmada, se borran las
   copias de lo anterior.

**Fallo o cancelación antes de confirmar** (RF-006-28, RF-008-19): al salir del bloque con un
error, o sin confirmar, lo puesto en su sitio se deshace (el anterior vuelve, lo nuevo se
borra), los temporales se borran y la tabla no existe (la transacción se deshizo); con un error,
la operación queda «cancelada» (``JobCancelled`` de un escritor, ``ReadCancelled``,
``HashCancelled``) o «fallida», con su motivo (``core.provenance.operations``). Ningún dato,
fichero ni tabla nuevos. Si Blender se cierra de golpe, los temporales sin reclamar los aparta
a ``orphans/`` la comprobación de apertura de la 008 (ADR-0025 §8); mientras la operación está
en curso, no (están reclamados y son de esta sesión).

Ningún error del disco llega como ``OSError`` a la transacción del proyecto (lo pasaría a solo
lectura): es ``gis.raster_target_locked`` o ``gis.raster_write_failed``.

Para leer lo guardado: :func:`list_gis_datasets` (desde ``gb_dataset``), :func:`load_raster` y
:func:`load_tin`. Python puro y numpy (ADR-0004).
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType, TracebackType
from typing import Any, Protocol

import numpy as np

from ..core.content.encoder import ContentDigest
from ..core.content.readers import ReadCancelled
from ..core.datasets import registry as dataset_registry
from ..core.datasets.model import (
    DATASET_DECLARATIONS,
    LIVE_STATUSES,
    RECORD_COLUMNS,
    DatasetRecord,
    DatasetSpec,
    Store,
)
from ..core.errors import GeoblenderError
from ..core.georef import CrsCatalog, CrsRef, VerticalRef, load_catalog
from ..core.gpkg.base import ColumnDef, create_feature_table
from ..core.gpkg.wkb import encode_geometry
from ..core.hashing import HashCancelled
from ..core.ids import SHORT_UID_CHARS
from ..core.paths import check_path_length
from ..core.provenance.operations import (
    OperationHandle,
    OperationProject,
    OperationStatus,
    cancel_reason,
    failure_reason,
)
from ..jobs.worker_api import JobCancelled
from .content import raster_digest, tin_digest
from .contours import ContourLine
from .geotiff.reader import read_geotiff
from .geotiff.writer import target_locked, write_failed, write_geotiff
from .messages import GisError
from .ports import Cancelled, Progress, WriteProfile
from .provenance import (
    CONTOUR_LINES,
    FAMILIES_BY_CODE,
    MODULE,
    PROJECT_GRID,
    SOURCE_GRID,
    TIN,
    DatasetFamily,
    dataset_spec,
)
from .raster import Raster
from .tin import Tin, save_tin
from .tin import load_tin as read_tin_file

__all__ = [
    "BACKUP_MARK",
    "COPY_CHUNK_BYTES",
    "TABLE_LAYOUTS",
    "TEMPORARY_MARK",
    "ResultWriter",
    "StoreProject",
    "TableLayout",
    "backup_path",
    "list_gis_datasets",
    "load_raster",
    "load_tin",
    "project_references",
    "session_tag",
    "temporary_path",
]

TEMPORARY_MARK = ".tmp-"
"""``<fichero>.tmp-<sesión>``: el temporal de un fichero que escribe una operación, con las 8
últimas cifras de la sesión (el patrón de restos de la 008, como los de ``originals/``)."""
BACKUP_MARK = ".old"
"""``<fichero>.old.tmp-<sesión>``: el fichero anterior del mismo dato, apartado hasta que la
operación se confirma (un temporal de la sesión: si Blender se cierra de golpe, va a
``orphans/`` y no se borra)."""
COPY_CHUNK_BYTES = 4 * 1024 * 1024
"""Lo que se copia de una vez del resultado de un trabajo (entre dos, se mira la cancelación)."""
CANCELLATIONS: tuple[type[BaseException], ...] = (JobCancelled, ReadCancelled, HashCancelled)
"""Los errores con que una escritura, una lectura o una huella se paran a petición de la
persona: la operación queda «cancelada», no «fallida»."""
FILE_FAMILIES: tuple[str, ...] = (SOURCE_GRID, PROJECT_GRID, TIN)
"""Las familias que son un fichero de ``rasters/`` o ``meshes/``."""
GRID_FAMILIES: tuple[str, ...] = (SOURCE_GRID, PROJECT_GRID)
"""Las familias de rejilla."""

_OBJ = "Dato de topografía"
_FIELD_LOCATION = "ubicación"
_FIELD_DATASET = "dato"
_GEOMETRY_COLUMN = "geom"


class StoreProject(OperationProject, Protocol):
    """Lo que usa del proyecto (``core.project.Project``): lo de las operaciones de la 008 y
    su fila de ``gb_project`` (``record``: el CRS horizontal y la referencia vertical)."""

    @property
    def record(self) -> Any: ...


@dataclass(frozen=True, slots=True)
class TableLayout:
    """La tabla de una familia vectorial (plan §5.2.3): el nombre GeoPackage de su tipo de
    geometría (``POINT``, ``LINESTRING``, ``MULTIPOLYGON``), si lleva Z, sus columnas (además
    de ``fid`` y ``geom``) y cómo empieza su identificador en ``gpkg_contents``."""

    geometry_type: str
    has_z: bool
    columns: tuple[ColumnDef, ...]
    label: str


TABLE_LAYOUTS: Mapping[str, TableLayout] = MappingProxyType({
    CONTOUR_LINES: TableLayout(
        "LINESTRING",
        True,
        (
            ColumnDef("elevation", "DOUBLE", not_null=True),
            ColumnDef("is_index", "BOOLEAN", not_null=True),
            ColumnDef("closed", "BOOLEAN", not_null=True),
            ColumnDef("length_m", "DOUBLE", not_null=True),
        ),
        "Curvas de nivel",
    ),
})
"""Las tablas de las familias vectoriales que escribe una operación, por familia (las de lo
importado, ``gis_pts_``, ``gis_brk_`` y ``gis_bnd_``, las añade T43)."""


# --- Nombres y referencias del proyecto ---------------------------------------------------------


def session_tag(project: StoreProject) -> str:
    """Las 8 últimas cifras hexadecimales de la sesión que tiene el proyecto abierto, en
    minúsculas (como los temporales de ``originals/`` y la carpeta de ``orphans/``)."""
    return (project.session.session_uid.replace("-", "")[-SHORT_UID_CHARS:] or "sesion").lower()


def temporary_path(project: StoreProject, final: Path) -> Path:
    """El temporal de ``final`` mientras se escribe: ``<fichero>.tmp-<sesión>``, en su carpeta."""
    final = Path(final)
    return final.with_name(f"{final.name}{TEMPORARY_MARK}{session_tag(project)}")


def backup_path(project: StoreProject, final: Path) -> Path:
    """Dónde se aparta el fichero anterior de ``final`` hasta confirmar:
    ``<fichero>.old.tmp-<sesión>``."""
    final = Path(final)
    return final.with_name(f"{final.name}{BACKUP_MARK}{TEMPORARY_MARK}{session_tag(project)}")


def project_references(
    project: StoreProject, *, catalog: CrsCatalog | None = None
) -> tuple[CrsRef, VerticalRef]:
    """El CRS horizontal y la referencia vertical del proyecto (``gb_project``), del catálogo
    de la 002 (por defecto, el de la extensión). ``ValueError`` con un proyecto abierto solo
    con su cabecera (de un esquema que esta versión no lee)."""
    record = project.record
    if record is None:
        raise ValueError(f"el proyecto «{project.name}» se abrió solo con su cabecera: no se "
                         "pueden leer ni escribir sus datos")
    found = load_catalog() if catalog is None else catalog
    crs = found.horizontal(record.crs_epsg)
    if record.vcrs_epsg is None:
        return crs, found.local_vertical(record.vcrs_note)
    return crs, found.vertical(record.vcrs_epsg)


def _vertical_text(vertical: VerticalRef) -> str:
    """La referencia vertical en el ``meta`` de un TIN: «EPSG:5782» o «Referencia local
    (nota)»."""
    if vertical.epsg is not None:
        return f"EPSG:{vertical.epsg}"
    return f"{vertical.name} ({vertical.note})"


def _z_description(vertical: VerticalRef) -> str:
    """Cómo se cita en ``gpkg_contents.description`` la referencia de las Z (plan §5.2.3)."""
    if vertical.epsg is not None:
        return f"Z en {vertical.name} (EPSG:{vertical.epsg})"
    return f"Z referidas a «{vertical.note}» ({vertical.name})"


def _family(code: str, allowed: Sequence[str]) -> DatasetFamily:
    if code not in allowed:
        raise ValueError(f"{code!r} no es una familia de datos de esta escritura: es una de "
                         f"{', '.join(allowed)}")
    return FAMILIES_BY_CODE[code]


def _disk_error(name: str, error: OSError) -> GisError:
    """El error para la persona de un fallo del disco al escribir ``name``."""
    if isinstance(error, PermissionError):  # Windows: otro programa lo tiene abierto
        return target_locked(name)
    return write_failed(name, error)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Si hay una tabla (o vista) con ese nombre en la base, sin distinguir mayúsculas."""
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND lower(name) = lower(?)",
        (table,),
    ).fetchone() is not None


def _owned(conn: sqlite3.Connection, spec: DatasetSpec) -> tuple[bool, bool]:
    """Si la ubicación de ``spec`` es del dato vivo con su nombre (que se puede volver a
    escribir: no es lo importado) y si es de algún otro dato, vivo o no."""
    rows = conn.execute(
        "SELECT name, status, immutable FROM gb_dataset WHERE store = ? AND locator = ?",
        (str(spec.store), spec.locator),
    ).fetchall()
    live = {str(status) for status in LIVE_STATUSES}
    mine = [row for row in rows if row[0] == spec.name and row[1] in live and not row[2]]
    return bool(mine), len(mine) != len(rows)


def _taken(spec: DatasetSpec) -> GisError:
    return GisError("gis.output_target_taken", obj=f"{_OBJ} «{spec.name}»",
                    field=_FIELD_LOCATION, value=spec.locator, name=spec.name)


# --- Escritura de los resultados de una operación ----------------------------------------------


@dataclass(slots=True)
class _File:
    """Un fichero de ``rasters/`` o ``meshes/``: su dato, su destino, su temporal y dónde se
    aparta el anterior; si ya está en su sitio y si había uno anterior apartado."""

    spec: DatasetSpec
    final: Path
    temporary: Path
    backup: Path
    installed: bool = False
    replaced: bool = False


@dataclass(frozen=True, slots=True)
class _Table:
    """Una tabla de ``project.gpkg``: su dato, su forma, sus filas ya codificadas (geometría y
    columnas), su extensión, su identificador y su descripción."""

    spec: DatasetSpec
    layout: TableLayout
    rows: tuple[tuple[Any, ...], ...]
    extent: tuple[float, float, float, float] | None
    identifier: str
    description: str


class ResultWriter:
    """Los resultados de la operación ``handle`` (``begin_operation`` de la 008, «en curso») en
    ``project`` (véase el módulo). Se usa como gestor de contexto::

        with ResultWriter(project, handle) as out:
            out.raster("MDT Norte", rejilla)
            out.commit(software={"pyproj": "3.8.0"}, message=informe)

    o, al incorporar un trabajo de la 004, con ``out.write`` como función de escritura de
    ``core.provenance.operations.ingest_job``. ``TypeError`` si ``handle`` no es un
    ``OperationHandle``; ``ValueError`` si es de otro proyecto."""

    def __init__(self, project: StoreProject, handle: OperationHandle) -> None:
        if not isinstance(handle, OperationHandle):
            raise TypeError(f"los resultados son de un OperationHandle, no {handle!r}")
        if handle.project_uid != project.uid:
            raise ValueError(f"la operación {handle.uid} es de otro proyecto")
        self.project = project
        self.handle = handle
        self._crs, self._vertical = project_references(project)
        self._files: list[_File] = []
        self._tables: list[_Table] = []
        self._specs: list[DatasetSpec] = []
        self._committed: bool | None = None
        self._closed = False

    def __enter__(self) -> ResultWriter:
        return self

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None,
                 traceback: TracebackType | None) -> None:
        self.close(error)

    @property
    def specs(self) -> tuple[DatasetSpec, ...]:
        """Las salidas preparadas, en su orden."""
        return tuple(self._specs)

    # --- Preparar --------------------------------------------------------------------------

    def _check_open(self) -> None:
        if self._closed or self._committed:
            raise RuntimeError(f"los resultados de la operación «{self.handle.op_type}» "
                               f"({self.handle.uid}) ya se confirmaron o se cerraron")

    def _add(self, spec: DatasetSpec) -> None:
        if any(found.name == spec.name for found in self._specs):
            raise ValueError(f"una operación escribe cada dato una vez: «{spec.name}» se repite")
        with self.project.read() as conn:
            owned, others = _owned(conn, spec)
            if spec.store is Store.GPKG:
                exists = _table_exists(conn, spec.locator)
            else:
                exists = Path(self.project.root, *spec.locator.split("/")).exists()
        if others or (exists and not owned):
            raise _taken(spec)
        self._specs.append(spec)

    def _plan_file(self, spec: DatasetSpec) -> _File:
        final = Path(self.project.root, *spec.locator.split("/"))
        entry = _File(spec, final, temporary_path(self.project, final),
                      backup_path(self.project, final))
        for path in (entry.temporary, entry.backup):
            check_path_length(path, obj=final.name)
        self._add(spec)
        self.handle.claim_paths(entry.temporary, entry.final, entry.backup)
        try:
            final.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise write_failed(final.name, error) from None
        self._files.append(entry)
        return entry

    def raster(
        self,
        name: str,
        raster: Raster,
        *,
        family: str = PROJECT_GRID,
        input_uid: str | None = None,
        progress: Progress | None = None,
        cancelled: Cancelled | None = None,
    ) -> DatasetSpec:
        """Prepara la rejilla ``raster`` como el dato ``gis_<familia>_<nombre>`` (por defecto,
        la rejilla del proyecto, ``gis_dtm_``; ``gis_src_``, lo importado de ``input_uid``):
        su hash (``gis.content.raster_digest``) y su GeoTIFF del perfil ``project`` en el
        temporal. Una rejilla del proyecto va en su CRS y su referencia vertical (si no,
        ``ValueError``). ``GisError`` si su sitio es de otro (``gis.output_target_taken``) o
        falla el disco; ``JobCancelled`` si ``cancelled()`` pide parar entre teselas."""
        if not isinstance(raster, Raster):
            raise TypeError(f"se escribe un Raster, no {type(raster).__name__}")
        _family(family, GRID_FAMILIES)
        if family == PROJECT_GRID and (raster.crs.epsg != self._crs.epsg
                                       or raster.vertical != self._vertical):
            raise ValueError(
                f"la rejilla del proyecto «{name}» va en el CRS y la referencia vertical del "
                f"proyecto (EPSG:{self._crs.epsg} + {_vertical_text(self._vertical)}), no en "
                f"EPSG:{raster.crs.epsg} + {_vertical_text(raster.vertical)}: remuestréela antes"
            )
        self._check_open()
        spec = dataset_spec(family, name, input_uid=input_uid, crs_epsg=raster.crs.epsg,
                            content=raster_digest(raster, DATASET_DECLARATIONS))
        entry = self._plan_file(spec)
        write_geotiff(raster, entry.final, profile=WriteProfile.PROJECT,
                      temporary=entry.temporary, replace=False, progress=progress,
                      cancelled=cancelled)
        return spec

    def tin(self, name: str, tin: Tin) -> DatasetSpec:
        """Prepara el TIN ``tin`` (absoluto, en el CRS y la referencia vertical del proyecto)
        como ``gis_tin_<nombre>``: su ``meta`` (el EPSG y la referencia vertical del proyecto
        y esta operación), su hash (``gis.content.tin_digest``) y su npz en el temporal.
        ``GisError`` si su sitio es de otro o falla el disco."""
        if not isinstance(tin, Tin):
            raise TypeError(f"se escribe un Tin, no {type(tin).__name__}")
        self._check_open()
        meta = {"crs_epsg": self._crs.epsg, "vertical": _vertical_text(self._vertical),
                "operation_uid": self.handle.uid}
        spec = dataset_spec(TIN, name, crs_epsg=self._crs.epsg,
                            content=tin_digest(tin, meta, DATASET_DECLARATIONS))
        entry = self._plan_file(spec)
        try:
            save_tin(tin, entry.final, meta, temporary=entry.temporary, replace=False)
        except OSError as error:
            raise write_failed(entry.final.name, error) from None
        return spec

    def copy_file(
        self,
        family: str,
        name: str,
        source: Path | str,
        *,
        content: ContentDigest,
        sha256: str | None = None,
        crs_epsg: int | None = None,
        input_uid: str | None = None,
        progress: Progress | None = None,
        cancelled: Cancelled | None = None,
    ) -> DatasetSpec:
        """Prepara el fichero ``source`` que dejó un trabajo de la 004 en su ``out/`` (una
        rejilla del perfil ``project`` o un npz de TIN) como el dato de ``family`` llamado
        ``name``, con el ``content`` que calculó el trabajo con el lector del dato: lo copia al
        temporal por trozos de :data:`COPY_CHUNK_BYTES` con su huella, que tiene que ser
        ``sha256`` si se da (si no, ``gis.output_copy_mismatch``). ``crs_epsg``: por defecto,
        el del proyecto en la rejilla del proyecto y el TIN. ``JobCancelled`` si
        ``cancelled()`` pide parar entre trozos."""
        _family(family, FILE_FAMILIES)
        if not isinstance(content, ContentDigest):
            raise TypeError(f"el hash del trabajo es un ContentDigest, no {content!r}")
        self._check_open()
        if crs_epsg is None and family in (PROJECT_GRID, TIN):
            crs_epsg = self._crs.epsg
        spec = dataset_spec(family, name, input_uid=input_uid, content=content,
                            crs_epsg=crs_epsg)
        entry = self._plan_file(spec)
        found = _copy(Path(source), entry.temporary, entry.final.name, progress, cancelled)
        if sha256 is not None and found != sha256:
            entry.temporary.unlink(missing_ok=True)
            raise GisError("gis.output_copy_mismatch", obj=f"{_OBJ} «{spec.name}»",
                           field="huella", value=found, file=entry.final.name,
                           detail=f"sha256 {found[:12]}… frente a {sha256[:12]}…")
        return spec

    def contours(self, name: str, lines: Iterable[ContourLine]) -> DatasetSpec:
        """Prepara las curvas ``lines`` (absolutas, en el CRS y la referencia vertical del
        proyecto) como la tabla ``gis_cnt_<nombre>`` (plan §5.2.3): una fila por curva con su
        geometría ``LINESTRING`` con Z (la cerrada, con su primer vértice repetido al final),
        su cota, si es maestra, si es cerrada y su longitud en planta. La tabla se escribe al
        confirmar; su hash, el del registro. ``GisError`` si su sitio es de otro."""
        chosen = list(lines)
        for line in chosen:
            if not isinstance(line, ContourLine):
                raise TypeError(f"una curva de nivel es un ContourLine, no {line!r}")
        self._check_open()
        layout = TABLE_LAYOUTS[CONTOUR_LINES]
        spec = dataset_spec(CONTOUR_LINES, name, crs_epsg=self._crs.epsg)
        srs = self._crs.epsg
        rows: list[tuple[Any, ...]] = []
        lows: list[np.ndarray] = []
        highs: list[np.ndarray] = []
        for line in chosen:
            coords = np.vstack([line.xyz, line.xyz[:1]]) if line.closed else line.xyz
            blob = encode_geometry(layout.geometry_type, coords, srs, layout.has_z)
            rows.append((blob, float(line.elevation), int(bool(line.is_index)),
                         int(bool(line.closed)), line.length_m))
            lows.append(coords[:, :2].min(axis=0))
            highs.append(coords[:, :2].max(axis=0))
        extent = None
        if rows:
            low = np.min(lows, axis=0)
            high = np.max(highs, axis=0)
            extent = (float(low[0]), float(low[1]), float(high[0]), float(high[1]))
        identifier = f"{layout.label}: {name} ({spec.locator})"
        with self.project.read() as conn:
            clash = conn.execute(
                "SELECT 1 FROM gpkg_contents WHERE identifier = ? AND lower(table_name) <> "
                "lower(?)", (identifier, spec.locator)).fetchone()
        if clash is not None:
            raise _taken(spec)
        self._add(spec)
        description = f"{layout.label} de Geoblender; {_z_description(self._vertical)}"
        self._tables.append(_Table(spec, layout, tuple(rows), extent, identifier, description))
        return spec

    # --- Poner en su sitio y confirmar --------------------------------------------------------

    def install(self) -> None:
        """Pone cada fichero preparado en su sitio: aparta el anterior del mismo dato a
        :func:`backup_path` y pasa el temporal al destino con ``os.replace``. Si otro programa
        tiene abierto el destino, ``gis.raster_target_locked`` (el anterior, intacto); otro
        fallo del disco, ``gis.raster_write_failed``. Lo ya puesto se deshace al cerrar sin
        confirmar. Volver a llamarla no hace nada más."""
        self._check_open()
        for entry in self._files:
            if entry.installed:
                continue
            if entry.final.exists():
                try:
                    os.replace(entry.final, entry.backup)
                except OSError as error:
                    raise _disk_error(entry.final.name, error) from None
                entry.replaced = True
            try:
                os.replace(entry.temporary, entry.final)
            except OSError as error:
                failure = _disk_error(entry.final.name, error)
                for problem in _restore(entry) if entry.replaced else []:
                    failure.add_note(problem)
                raise failure from None
            entry.installed = True

    def write(self, conn: sqlite3.Connection) -> tuple[DatasetSpec, ...]:
        """Lo que se hace en la transacción de escritura ``conn`` que confirma la operación
        (la de :meth:`commit` o la de ``ingest_job``): pone los ficheros en su sitio si aún no
        lo están (:meth:`install`), escribe las tablas (una que ya es del dato, con sus filas
        nuevas) y devuelve las salidas para ``OperationHandle.complete``."""
        if not isinstance(conn, sqlite3.Connection) or not conn.in_transaction:
            raise ValueError("los resultados se escriben en una transacción de escritura del "
                             "proyecto (Project.write_transaction)")
        self.install()
        for table in self._tables:
            self._write_table(conn, table)
        return self.specs

    def _write_table(self, conn: sqlite3.Connection, table: _Table) -> None:
        spec, layout = table.spec, table.layout
        owned, others = _owned(conn, spec)
        exists = _table_exists(conn, spec.locator)
        if others or (exists and not owned):
            raise _taken(spec)
        if exists:
            conn.execute(f'DELETE FROM "{spec.locator}"')
        else:
            create_feature_table(conn, spec.locator, layout.geometry_type, self._crs.epsg,
                                 layout.has_z, layout.columns, table.identifier,
                                 table.description)
        names = [_GEOMETRY_COLUMN, *(column.name for column in layout.columns)]
        conn.executemany(
            f'INSERT INTO "{spec.locator}" ({", ".join(names)}) '
            f'VALUES ({", ".join("?" for _ in names)})',
            table.rows,
        )
        conn.execute("UPDATE gpkg_contents SET min_x = ?, min_y = ?, max_x = ?, max_y = ? "
                     "WHERE table_name = ?",
                     (*(table.extent or (None, None, None, None)), spec.locator))

    def commit(
        self,
        *,
        software: Any = None,
        interpreter: Any = None,
        message: str | None = None,
        executor: Any = None,
        job_uid: str | None = None,
    ) -> tuple[DatasetRecord, ...]:
        """Confirma la operación: los ficheros en su sitio (:meth:`install`) y, en una
        transacción, las tablas y ``OperationHandle.complete`` con las salidas y ``software``,
        ``interpreter``, ``message``, ``executor`` y ``job_uid`` (RF-008-18); después borra lo
        anterior apartado. Devuelve las salidas registradas, en su orden. Si algo falla, se
        deshace todo lo de esta operación y queda «fallida» o «cancelada» con su motivo
        (RF-008-19), y el error sigue."""
        try:
            self.install()
            with self.project.write_transaction() as conn:
                specs = self.write(conn)
                records = self.handle.complete(
                    conn, outputs=specs, software=software, interpreter=interpreter,
                    message=message, executor=executor, job_uid=job_uid,
                )
        except BaseException as error:
            self.close(error)
            raise
        self._committed = True
        self.close()
        return records

    # --- Cerrar ----------------------------------------------------------------------------

    def close(self, error: BaseException | None = None) -> None:
        """Termina: si la operación quedó «hecha», borra lo anterior apartado; si no, deshace
        lo puesto en su sitio y borra los temporales. Con ``error`` (el que paró el bloque) y la
        operación aún «en curso», la deja «cancelada» o «fallida» con su motivo; si no se puede
        registrar, se dice en una nota del error. Volver a llamarla no hace nada."""
        if self._closed:
            return
        self._closed = True
        problems: list[str] = []
        if self._committed is None and any(entry.installed for entry in self._files):
            try:
                self._committed = self._status() == OperationStatus.DONE
            except (GeoblenderError, OSError, sqlite3.Error) as exc:
                problems.append(f"no se pudo saber si la operación se confirmó ({exc}); sus "
                                "ficheros se dejan como están")
        if self._committed:
            for entry in self._files:
                _discard(entry.backup)
        elif not problems:
            for entry in reversed(self._files):
                problems.extend(_undo(entry))
        if error is not None and not self._committed:
            problems.extend(self._abandon(error))
        if error is not None:
            for problem in problems:
                error.add_note(problem)

    def _status(self) -> str | None:
        with self.project.read() as conn:
            row = conn.execute("SELECT status FROM gb_operation WHERE uid = ?",
                               (self.handle.uid,)).fetchone()
        return None if row is None else str(row[0])

    def _abandon(self, error: BaseException) -> list[str]:
        """La operación, si sigue «en curso», «cancelada» o «fallida» con su motivo."""
        cancelled = isinstance(error, CANCELLATIONS)
        what = "cancelación" if cancelled else "fallo"
        try:
            if self._status() != OperationStatus.RUNNING:
                return []
            if cancelled:
                self.handle.cancel(cancel_reason(error))
            else:
                self.handle.fail(failure_reason(error))
        except (GeoblenderError, OSError, sqlite3.Error) as exc:
            return [f"La operación «{self.handle.op_type}» ({self.handle.uid}) sigue «en "
                    f"curso» en el proyecto: no se pudo registrar su {what} ({exc})."]
        return []


def _copy(source: Path, target: Path, name: str, progress: Progress | None,
          cancelled: Cancelled | None) -> str:
    """Copia ``source`` en ``target`` por trozos con su sha256 (``fsync`` al final); si falla
    o se cancela, borra ``target``."""
    digest = hashlib.sha256()
    try:
        size = source.stat().st_size
        total = max(1, -(-size // COPY_CHUNK_BYTES))
        with source.open("rb") as reader, target.open("wb") as writer:
            for index in range(total):
                if cancelled is not None and cancelled():
                    raise JobCancelled(f"Cancelado al copiar «{name}» en el trozo {index + 1} "
                                       f"de {total}")
                chunk = reader.read(COPY_CHUNK_BYTES)
                digest.update(chunk)
                writer.write(chunk)
                if progress is not None:
                    progress((index + 1) / total,
                             f"Copiando «{name}»: trozo {index + 1} de {total}")
            rest = reader.read()
            digest.update(rest)
            writer.write(rest)
            writer.flush()
            os.fsync(writer.fileno())
    except BaseException as error:
        _discard(target)
        if isinstance(error, OSError):
            raise write_failed(name, error) from None
        raise
    return digest.hexdigest()


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _restore(entry: _File) -> list[str]:
    """Devuelve a su sitio el fichero anterior apartado."""
    try:
        os.replace(entry.backup, entry.final)
    except OSError as exc:
        return [f"No se pudo devolver a su sitio «{entry.final.name}» ({exc}): el anterior "
                f"está en «{entry.backup.name}» y se apartará a orphans/ al volver a abrir el "
                "proyecto."]
    entry.replaced = False
    return []


def _undo(entry: _File) -> list[str]:
    """Deshace lo de un fichero sin confirmar: el anterior vuelve (o lo nuevo se borra) y el
    temporal se borra."""
    problems: list[str] = []
    if entry.installed:
        if entry.replaced:
            problems.extend(_restore(entry))
        else:
            try:
                entry.final.unlink(missing_ok=True)
            except OSError as exc:
                problems.append(f"No se pudo borrar «{entry.final.name}» ({exc}), escrito por "
                                "una operación que no se confirmó: se apartará a orphans/ al "
                                "volver a abrir el proyecto.")
        entry.installed = False
    _discard(entry.temporary)
    return problems


# --- Lectura de lo guardado --------------------------------------------------------------------


def list_gis_datasets(
    project: StoreProject,
    kinds: Iterable[str] | None = None,
    *,
    families: Iterable[str] | None = None,
) -> list[DatasetRecord]:
    """Los datos vivos de la topografía registrados en ``gb_dataset`` (vigentes, que faltan,
    bloqueados o dañados), por nombre; solo los de los tipos ``kinds`` (``"raster"``,
    ``"mesh"``, ``"vector"``) o de las familias ``families`` (``"dtm"``, ``"tin"``…), si se
    dan. ``ValueError`` con una familia que no es de la 006."""
    chosen_kinds = None if kinds is None else frozenset(kinds)
    prefixes = None if families is None else tuple(
        _family(code, tuple(FAMILIES_BY_CODE)).prefix for code in families)
    live = tuple(str(status) for status in LIVE_STATUSES)
    with project.read() as conn:
        rows = conn.execute(
            f"SELECT {', '.join(RECORD_COLUMNS)} FROM gb_dataset WHERE module = ? AND status "
            f"IN ({', '.join('?' for _ in live)}) ORDER BY name",
            (MODULE, *live),
        ).fetchall()
    found = [DatasetRecord.from_row(row) for row in rows]
    return [record for record in found
            if (chosen_kinds is None or record.kind in chosen_kinds)
            and (prefixes is None or record.name.startswith(prefixes))]


def _resolve(project: StoreProject, ref: DatasetRecord | str,
             allowed: Sequence[str]) -> DatasetRecord:
    if isinstance(ref, DatasetRecord):
        record: DatasetRecord | None = ref
    elif isinstance(ref, str):
        with project.read() as conn:
            record = dataset_registry.get(conn, ref)
        if record is not None and record.module != MODULE:
            record = None
    else:
        raise TypeError(f"un dato se indica por su nombre, su uid o su registro, no {ref!r}")
    if record is None:
        raise GisError("gis.dataset_unknown", obj=_OBJ, field=_FIELD_DATASET, value=ref)
    prefixes = tuple(FAMILIES_BY_CODE[code].prefix for code in allowed)
    if not record.name.startswith(prefixes):
        raise ValueError(f"«{record.name}» no es un dato de {', '.join(allowed)}")
    return record


def _file_of(project: StoreProject, record: DatasetRecord) -> Path:
    path = Path(project.root, *record.locator.split("/"))
    if not path.is_file():
        raise GisError("gis.dataset_file_missing", obj=f"{_OBJ} «{record.name}»",
                       field=_FIELD_LOCATION, value=record.locator, file=path.name,
                       name=record.name)
    return path


def load_raster(
    project: StoreProject,
    ref: DatasetRecord | str,
    *,
    catalog: CrsCatalog | None = None,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> Raster:
    """La rejilla guardada del dato ``ref`` (su registro, su uid o su nombre: ``gis_dtm_`` o
    ``gis_src_``), con las mismas celdas que se escribieron, el CRS que declara el fichero y su
    referencia vertical (la del proyecto si el fichero no la declara: una referencia local).
    Sin el límite de celdas de la importación. ``GisError`` ``gis.dataset_unknown`` si no hay
    un dato de ``gis`` así y ``gis.dataset_file_missing`` si falta su fichero; ``ValueError``
    si es de otra familia."""
    record = _resolve(project, ref, GRID_FAMILIES)
    path = _file_of(project, record)
    source = read_geotiff(path, max_cells=sys.maxsize, catalog=catalog, progress=progress,
                          cancelled=cancelled)
    crs, vertical = project_references(project, catalog=catalog)
    return Raster(source.grid, source.values, source.declared_crs or crs,
                  source.declared_vertical or vertical)


def load_tin(project: StoreProject, ref: DatasetRecord | str) -> Tin:
    """El TIN guardado del dato ``ref`` (``gis_tin_``) con su ``meta``. Los mismos errores que
    :func:`load_raster`; un fichero que no es el de un TIN, ``gis.tin_file_invalid``."""
    record = _resolve(project, ref, (TIN,))
    return read_tin_file(_file_of(project, record))
