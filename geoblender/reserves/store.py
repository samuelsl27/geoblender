# SPDX-License-Identifier: GPL-3.0-or-later
"""La cubicación en el proyecto (spec 011, T14; RF-011-05, RF-011-20, RF-011-21, RF-011-22,
RF-011-25; ADR-0024, ADR-0025 §3; plan 011 §5.2.1, §5.2.3, A11, D-16, D-25, D-30).

Lo que produce una operación de ``res`` se guarda en el proyecto con la API de procedencia de la
008 y de la 009, nunca escribiendo en las tablas ``gb_*`` (como ``gis.store``):

- **tablas** de ``project.gpkg``: las de una cubicación, sus toneladas y sus momentos
  (``res_vol_``, ``res_ton_``, ``res_stg_``; formato largo, ``reserves.table``), datos de la
  versión con sus columnas tipadas y sus títulos en ``gpkg_data_columns`` (QGIS los enseña con
  sus nombres), y la columna de materiales del proyecto (``res_materials``, D-12); cada una con
  el hash de su lector (``core.gpkg_layer@1``) calculado **fuera de la transacción**
  (:func:`table_digest`, :func:`materials_digest`: sus filas en un GeoPackage en memoria con la
  misma estructura, leído con la función del registro; R4);
- la **rejilla de diferencias** (``rasters/res_dif_<nombre>_<vNN>.tif``), que
  ``reserves.volumes.volume_steps`` deja escrita entera en su temporal con su hash por bandas.

:class:`ResultWriter` (un gestor de contexto por operación, con su ``OperationHandle`` «en
curso» de ``begin_operation``) sigue A11 como ``gis.store.ResultWriter``:

1. **Preparar**: el sitio de la rejilla (:meth:`~ResultWriter.grid_paths`: libre o del mismo
   dato; su temporal ``<fichero>.tmp-<sesión>``, el destino y la copia del anterior, reclamados
   con ``claim_paths``) antes de cubicar; después, la rejilla escrita
   (:meth:`~ResultWriter.grid`) y las filas de cada tabla con su hash (:meth:`~ResultWriter.table`,
   :meth:`~ResultWriter.materials`).
2. **Poner en su sitio** (:meth:`~ResultWriter.install`): el fichero anterior del mismo dato se
   aparta y el temporal pasa a su sitio con ``os.replace``; si otro programa tiene abierto el
   destino (QGIS), ``gis.raster_target_locked`` y el anterior queda intacto.
3. **Confirmar** (:meth:`~ResultWriter.commit`): en **una** transacción, crear (``execute``,
   una sentencia cada vez) o vaciar cada tabla, sus filas en sentencias de 500
   (``gis.store.insert_rows``) y ``OperationHandle.complete`` con las salidas y las cifras.

**Nada a medias** (RF-011-25): si algo falla o se cancela antes de confirmar, se deshace lo
puesto en su sitio (el anterior vuelve, lo nuevo se borra), se borran los temporales y la
operación queda «cancelada» (cerrar los pasos: Esc, ``GeneratorExit``; una lectura o una huella
paradas) o «fallida», con su motivo; ni cifra, ni tabla, ni rejilla.

**Los pasos de cada tipo en el proyecto** (lo que lanzan las órdenes de ``bl`` y su recálculo):
:func:`volume_run` (``res.volume`` y ``res.difference``: lee las superficies del proyecto o lo
congelado, ``reserves.surfaces.surface_source``, cubica por pasos y guarda), :func:`tonnage_run`
(``res.tonnage``: de la tabla de volúmenes y la columna que consumió, con los parámetros que
leyó al empezar, D-16) y :func:`save_materials` (``res.edit_materials``). Repetir el nombre de
una cubicación de la versión la sustituye (D-30): :func:`previous_operation` da la operación a
la que sustituye la nueva (``begin_operation(…, supersedes=…)``), que escribe contenido nuevo
de los mismos datos. Python puro (nivel 9).
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path
from types import TracebackType
from typing import Any

from ..core.content import builtin as core_builtin
from ..core.content.encoder import NORMALIZER, ContentDigest
from ..core.content.readers import ReadCancelled
from ..core.datasets import registry as dataset_registry
from ..core.datasets.model import (
    DATASET_DECLARATIONS,
    LIVE_STATUSES,
    DatasetRecord,
    DatasetSpec,
    Store,
)
from ..core.errors import GeoblenderError
from ..core.gpkg.base import ColumnDef, create_attribute_table, create_structure, set_column_titles
from ..core.hashing import HashCancelled
from ..core.i18n import format_number
from ..core.paths import check_path_length
from ..core.project.model import Progress
from ..core.provenance.figures import FigureSpec
from ..core.provenance.operations import (
    CANCEL_REASON_PREFIX,
    NOT_COMPLETED_REASON,
    OperationHandle,
    OperationStatus,
    cancel_reason,
    failure_reason,
)
from ..core.units import convert
from ..core.versions import read as versions_read
from ..core.versions.model import VersionError
from ..gis.geotiff.writer import target_locked, write_failed
from ..gis.messages import GisError
from ..gis.store import StoreProject, backup_path, insert_rows, project_references, temporary_path
from . import provenance as declared
from .materials import COLUMNS as MATERIAL_COLUMNS
from .materials import CREATE_TABLE as MATERIALS_DDL
from .materials import TABLE as MATERIALS_TABLE
from .materials import MaterialColumn, column_rows, read_column
from .messages import ResError
from .params import ANTHROPIC_PRESENCE, MIN_THICKNESS
from .surfaces import BAND_ROWS, SurfaceSource, surface_source
from .table import COLUMN_NAMES, COLUMNS, TITLES, Row, read_rows
from .volumes import (
    FINAL,
    START,
    STEP_BUDGET_S,
    DifferenceGrid,
    TonnageOutputs,
    VolumeRequest,
    VolumeResult,
    base_role,
    thickness_role,
    tonnage_outputs,
    volume_steps,
)

__all__ = [
    "CANCELLATIONS",
    "CANCELLED_REASON",
    "DIGEST_TABLE",
    "SAVE_STEPS",
    "TABLE_COLUMNS",
    "ResultWriter",
    "StoredTonnage",
    "StoredVolume",
    "materials_digest",
    "previous_operation",
    "project_sources",
    "save_materials",
    "table_digest",
    "tonnage_run",
    "volume_run",
]

CANCELLED_REASON = CANCEL_REASON_PREFIX + "la persona la paró antes de terminar (Esc)"
"""El motivo de una cubicación cuyos pasos se cerraron antes del final (RF-011-25)."""
CANCELLATIONS: tuple[type[BaseException], ...] = (GeneratorExit, ReadCancelled, HashCancelled)
"""Lo que para una operación a petición de la persona: queda «cancelada», no «fallida»."""
DIGEST_TABLE = "tabla"
"""El nombre de una tabla en el GeoPackage en memoria de :func:`table_digest` (no es contenido:
el hash de ``core.gpkg_layer@1`` no lleva el nombre de la tabla)."""
SAVE_STEPS = 2
"""Los pasos que añade guardar a los de calcular: preparar las tablas y confirmar."""


def _column_def(sql: str, name: str) -> ColumnDef:
    sql_type, _space, rest = sql.partition(" ")
    return ColumnDef(name, sql_type, not_null="NOT NULL" in rest)


TABLE_COLUMNS: tuple[ColumnDef, ...] = tuple(_column_def(column.sql, column.name)
                                             for column in COLUMNS)
"""Las columnas tipadas de una tabla ``report`` de ``res`` (``reserves.table.COLUMNS``) como las
crea ``core.gpkg.base.create_attribute_table``."""

_OBJ = "Cubicación"
_FIELD = "ubicación"
_REPORTS = (declared.VOLUMES, declared.TONNES, declared.STAGE_TABLE)


# --- El hash de las tablas (R4) ----------------------------------------------------------------


def _create_report(conn: sqlite3.Connection, name: str, identifier: str,
                   description: str) -> None:
    """Crea la tabla ``report`` ``name`` y la registra en ``gpkg_contents`` (``attributes``)."""
    create_attribute_table(conn, name, TABLE_COLUMNS, identifier, description)


def _create_materials(conn: sqlite3.Connection, name: str, identifier: str,
                      description: str) -> None:
    """Crea la tabla de la columna (con sus ``CHECK`` y su ``UNIQUE``, plan §5.2.1) y la
    registra en ``gpkg_contents`` (``attributes``)."""
    if name != MATERIALS_TABLE:
        raise ValueError(f"la columna de materiales es la tabla «{MATERIALS_TABLE}», no «{name}»")
    conn.execute(MATERIALS_DDL)
    conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description) "
                 "VALUES (?, 'attributes', ?, ?)", (name, identifier, description))


def _digest(create: Callable[[sqlite3.Connection, str, str, str], None], layer: str,
            names: Sequence[str], rows: Sequence[Sequence[Any]]) -> ContentDigest:
    """El ``ContentDigest`` (``core.gpkg_layer@1``, sin declaraciones) de una tabla que crea
    ``create`` con las filas ``rows`` (valores de las columnas ``names``), sin escribirla en el
    proyecto: en un GeoPackage en memoria con la misma estructura, leída con
    ``core.content.builtin.layer_steps``, la función con que el registro de la 008 hashea una
    tabla del proyecto (ADR-0024 §5)."""
    conn = sqlite3.connect(":memory:")
    try:
        create_structure(conn)
        create(conn, layer, layer, "")
        insert_rows(conn, layer, names, [tuple(row) for row in rows])
        request = core_builtin.GPKG_LAYER.request(
            "table", DATASET_DECLARATIONS, {"main": Path(layer)}, {"layer": layer},
            normalizer=NORMALIZER)
        steps = core_builtin.layer_steps(conn, request)
        try:
            for _done in steps:
                pass
        finally:
            steps.close()
        return request.hasher.digest()
    finally:
        conn.close()


def table_digest(rows: Sequence[Row]) -> ContentDigest:
    """El hash de contenido que da la tabla ``report`` de ``res`` con las filas ``rows`` al
    escribirla en el proyecto (R4: se calcula antes de la transacción)."""
    return _digest(_create_report, DIGEST_TABLE, COLUMN_NAMES, [row.values() for row in rows])


def materials_digest(column: MaterialColumn) -> ContentDigest:
    """El hash de contenido que da la tabla ``res_materials`` de la columna ``column``."""
    return _digest(_create_materials, MATERIALS_TABLE, MATERIAL_COLUMNS, column_rows(column))


# --- Escribir el resultado (A11) ------------------------------------------------------------


@dataclass(slots=True)
class _Grid:
    """La rejilla de diferencias de la cubicación ``name``: su destino, su temporal, dónde se
    aparta el anterior y, cuando está escrita, su ``DatasetSpec``; si ya está en su sitio y si
    había un anterior apartado."""

    name: str
    final: Path
    temporary: Path
    backup: Path
    spec: DatasetSpec | None = None
    installed: bool = False
    replaced: bool = False


@dataclass(frozen=True, slots=True)
class _Table:
    """Una tabla que se escribe al confirmar: su ``DatasetSpec``, su identificador y su
    descripción en ``gpkg_contents``, cómo se crea, sus columnas, sus filas y sus títulos."""

    spec: DatasetSpec
    identifier: str
    description: str
    create: Callable[[sqlite3.Connection, str, str, str], None]
    names: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    titles: Mapping[str, str] | None


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND lower(name) = lower(?)",
        (name,),
    ).fetchone() is not None


def _disk_error(name: str, error: OSError) -> GisError:
    """El error para la persona de un fallo del disco con ``name``."""
    if isinstance(error, PermissionError):  # Windows: otro programa lo tiene abierto
        return target_locked(name)
    return write_failed(name, error)


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _restore(entry: _Grid) -> list[str]:
    """Devuelve a su sitio la rejilla anterior apartada."""
    try:
        os.replace(entry.backup, entry.final)
    except OSError as exc:
        return [f"No se pudo devolver a su sitio «{entry.final.name}» ({exc}): la anterior está "
                f"en «{entry.backup.name}» y se apartará a orphans/ al volver a abrir el "
                "proyecto."]
    entry.replaced = False
    return []


def _undo(entry: _Grid) -> list[str]:
    """Deshace lo de una rejilla sin confirmar: la anterior vuelve (o la nueva se borra) y el
    temporal se borra."""
    problems: list[str] = []
    if entry.installed:
        if entry.replaced:
            problems.extend(_restore(entry))
        else:
            try:
                entry.final.unlink(missing_ok=True)
            except OSError as exc:
                problems.append(f"No se pudo borrar «{entry.final.name}» ({exc}), escrita por una "
                                "cubicación que no se confirmó: se apartará a orphans/ al volver "
                                "a abrir el proyecto.")
        entry.installed = False
    _discard(entry.temporary)
    return problems


class ResultWriter:
    """Los resultados de la operación de ``res`` ``handle`` (``begin_operation``, «en curso»)
    en ``project`` (véase el módulo). Se usa como gestor de contexto::

        with ResultWriter(project, handle) as out:
            final, temporal = out.grid_paths("Mensual octubre")
            … (volume_steps escribe la rejilla en el temporal)
            out.grid("Mensual octubre", resultado.difference)
            out.table(VOLUMES, "Mensual octubre", resultado.rows)
            out.commit(figures=resultado.figures, message=resumen)

    ``TypeError`` si ``handle`` no es un ``OperationHandle``; ``ValueError`` si es de otro
    proyecto o no es de ``res``."""

    def __init__(self, project: StoreProject, handle: OperationHandle) -> None:
        if not isinstance(handle, OperationHandle):
            raise TypeError(f"los resultados son de un OperationHandle, no {handle!r}")
        if handle.project_uid != project.uid:
            raise ValueError(f"la operación {handle.uid} es de otro proyecto")
        if handle.definition.module != declared.MODULE:
            raise ValueError(f"«{handle.op_type}» no es una operación de la cubicación")
        self.project = project
        self.handle = handle
        self._code: str | None = None
        if handle.version_uid:
            with project.read() as conn:
                version = versions_read.version(conn, handle.version_uid)
            if version is None:  # inalcanzable: begin_operation la comprobó
                raise ValueError(f"la versión de la operación {handle.uid} no existe")
            self._code = version.code
        self._grids: list[_Grid] = []
        self._tables: list[_Table] = []
        self._specs: list[DatasetSpec] = []
        self._committed = False
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

    @property
    def version_code(self) -> str:
        """El código de la versión de la operación («V01»); ``ValueError`` en una del
        proyecto."""
        if self._code is None:
            raise ValueError(f"«{self.handle.op_type}» es una operación del proyecto: no "
                             "escribe datos de una versión")
        return self._code

    # --- Preparar --------------------------------------------------------------------------

    def _check_open(self) -> None:
        if self._closed or self._committed:
            raise RuntimeError(f"los resultados de la operación «{self.handle.op_type}» "
                               f"({self.handle.uid}) ya se confirmaron o se cerraron")

    def _produces(self, family: str) -> None:
        found = declared.OPERATION_TYPES_BY_NAME[self.handle.op_type]
        if family not in found.outputs:
            raise ValueError(f"«{self.handle.op_type}» no produce datos «{family}»: produce "
                             f"{list(found.outputs)}")

    def _check_place(self, conn: sqlite3.Connection, spec: DatasetSpec) -> None:
        """El sitio de ``spec`` está libre o es del dato vivo con su nombre (si no,
        ``gis.output_target_taken``, sin escribir nada)."""
        rows = conn.execute(
            "SELECT name, status, immutable FROM gb_dataset WHERE store = ? AND locator = ?",
            (str(spec.store), spec.locator),
        ).fetchall()
        live = {str(status) for status in LIVE_STATUSES}
        mine = [row for row in rows if row[0] == spec.name and row[1] in live and not row[2]]
        if spec.store is Store.GPKG:
            exists = _table_exists(conn, spec.locator)
        else:
            exists = Path(self.project.root, *spec.locator.split("/")).exists()
        if len(mine) != len(rows) or (exists and not mine):
            raise GisError("gis.output_target_taken", obj=f"{_OBJ}: «{spec.name}»",
                           field=_FIELD, value=spec.locator, name=spec.name)

    def grid_paths(self, name: str) -> tuple[Path, Path]:
        """Prepara la rejilla de diferencias de la cubicación ``name``
        (``rasters/res_dif_<nombre>_<vNN>.tif``) antes de cubicar: comprueba que su sitio está
        libre o es del mismo dato, reclama su temporal, su destino y la copia del anterior y
        devuelve ``(destino, temporal)``, lo que pide ``volume_steps``. ``GisError`` si su sitio
        es de otro o no se puede crear su carpeta."""
        self._check_open()
        self._produces(declared.DIFFERENCE_GRID)
        if any(grid.name == name for grid in self._grids):
            raise ValueError(f"la rejilla de «{name}» ya está preparada")
        spec = declared.dataset_spec(declared.DIFFERENCE_GRID, name, self.version_code)
        final = Path(self.project.root, *spec.locator.split("/"))
        temporary = temporary_path(self.project, final)
        backup = backup_path(self.project, final)
        for path in (temporary, backup):
            check_path_length(path, obj=final.name)
        with self.project.read() as conn:
            self._check_place(conn, spec)
        self.handle.claim_paths(temporary, final, backup)
        try:
            final.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise write_failed(final.name, error) from None
        self._grids.append(_Grid(name, final, temporary, backup))
        return final, temporary

    def grid(self, name: str, difference: DifferenceGrid) -> DatasetSpec:
        """La rejilla de diferencias de ``name``, ya escrita entera en el temporal de
        :meth:`grid_paths` con su hash (``volume_steps``): su ``DatasetSpec`` (dato de la
        versión, ``gis.geotiff@1``, en el CRS del proyecto)."""
        self._check_open()
        if not isinstance(difference, DifferenceGrid):
            raise TypeError(f"la rejilla es una DifferenceGrid, no {difference!r}")
        found = [grid for grid in self._grids if grid.name == name]
        if not found:
            raise ValueError(f"la rejilla de «{name}» no se preparó (grid_paths)")
        entry = found[0]
        if entry.spec is not None:
            raise ValueError(f"una operación escribe la rejilla de «{name}» una vez")
        if Path(difference.path) != entry.temporary:
            raise ValueError(f"la rejilla de «{name}» está en «{Path(difference.path).name}», no "
                             f"en su temporal «{entry.temporary.name}»")
        crs, _vertical = project_references(self.project)
        entry.spec = declared.dataset_spec(declared.DIFFERENCE_GRID, name, self.version_code,
                                           content=difference.digest, crs_epsg=crs.epsg)
        self._specs.append(entry.spec)
        return entry.spec

    def table(self, family: str, name: str, rows: Sequence[Row]) -> DatasetSpec:
        """Prepara la tabla ``report`` de la familia ``family`` (``vol``, ``ton`` o ``stg``) de
        la cubicación ``name`` con las filas ``rows`` (``reserves.table.Row``) y su hash, que se
        calcula aquí, fuera de la transacción (R4). Devuelve su ``DatasetSpec``. ``GisError`` si
        su sitio es de otro."""
        self._check_open()
        if family not in _REPORTS:
            raise ValueError(f"«{family}» no es una tabla de la cubicación: es una de "
                             f"{', '.join(_REPORTS)}")
        self._produces(family)
        chosen = tuple(rows)
        for row in chosen:
            if not isinstance(row, Row):
                raise TypeError(f"una fila de una tabla de res es una Row, no {row!r}")
        spec = declared.dataset_spec(family, name, self.version_code,
                                     content=table_digest(chosen))
        if any(other.name == spec.name for other in self._specs):
            raise ValueError(f"una operación escribe cada dato una vez: «{spec.name}» se repite")
        with self.project.read() as conn:
            self._check_place(conn, spec)
        label = declared.FAMILIES_BY_CODE[family].label
        identifier = f"{label} «{name}» {self.version_code}"
        description = (f"{label} «{name}» de la versión {self.version_code}, de Geoblender: una "
                       "fila por valor (dominio, rodaja, unidad, componente, dato, valor, unidad "
                       "de medida y nota)")
        self._tables.append(_Table(spec, identifier, description, _create_report, COLUMN_NAMES,
                                   tuple(row.values() for row in chosen), TITLES))
        self._specs.append(spec)
        return spec

    def materials(self, column: MaterialColumn) -> DatasetSpec:
        """Prepara la columna de materiales ``column`` (que se valida:
        ``res.materials_invalid``) como la tabla del proyecto ``res_materials`` (D-12), con su
        hash. Solo ``res.edit_materials``."""
        self._check_open()
        if self.handle.op_type != declared.EDIT_MATERIALS:
            raise ValueError(f"la columna la escribe {declared.EDIT_MATERIALS}, no "
                             f"«{self.handle.op_type}»")
        if not isinstance(column, MaterialColumn):
            raise TypeError(f"la columna es una MaterialColumn, no {column!r}")
        column.validate()
        spec = declared.materials_spec(materials_digest(column))
        if any(other.name == spec.name for other in self._specs):
            raise ValueError("una operación escribe la columna una vez")
        with self.project.read() as conn:
            self._check_place(conn, spec)
        self._tables.append(_Table(spec, "Columna de materiales",
                                   "Columna de materiales del proyecto, de Geoblender",
                                   _create_materials, MATERIAL_COLUMNS,
                                   tuple(column_rows(column)), None))
        self._specs.append(spec)
        return spec

    # --- Poner en su sitio y confirmar --------------------------------------------------------

    def install(self) -> None:
        """Pone cada rejilla escrita en su sitio: aparta la anterior del mismo dato y pasa el
        temporal al destino con ``os.replace``. Si otro programa tiene abierto el destino,
        ``gis.raster_target_locked`` (la anterior, intacta); otro fallo del disco,
        ``gis.raster_write_failed``. Lo puesto se deshace al cerrar sin confirmar."""
        self._check_open()
        for entry in self._grids:
            if entry.installed or entry.spec is None:
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

    def _write_table(self, conn: sqlite3.Connection, table: _Table) -> None:
        """La tabla ``table`` en la transacción ``conn``: creada (con sus títulos) o vaciada, y
        sus filas en sentencias de 500."""
        spec = table.spec
        self._check_place(conn, spec)
        if _table_exists(conn, spec.locator):
            conn.execute(f'DELETE FROM "{spec.locator}"')
        else:
            table.create(conn, spec.locator, table.identifier, table.description)
            if table.titles:
                set_column_titles(conn, spec.locator, table.titles)
        insert_rows(conn, spec.locator, table.names, table.rows)

    def commit(self, *, figures: Sequence[FigureSpec] = (),
               message: str | None = None) -> tuple[DatasetRecord, ...]:
        """Confirma la operación: las rejillas en su sitio (:meth:`install`) y, en **una**
        transacción, las tablas y ``OperationHandle.complete`` con las salidas, las cifras
        ``figures`` y ``message``; después borra lo anterior apartado. Devuelve las salidas
        registradas. Si algo falla, se deshace todo lo de esta operación, que queda «fallida» o
        «cancelada» con su motivo (RF-011-25), y el error sigue."""
        self._check_open()
        try:
            self.install()
            with self.project.write_transaction() as conn:
                for table in self._tables:
                    self._write_table(conn, table)
                records = self.handle.complete(conn, outputs=self.specs, figures=figures,
                                               message=message)
        except BaseException as error:
            self.close(error)
            raise
        self._committed = True
        self.close()
        return records

    # --- Cerrar ----------------------------------------------------------------------------

    def close(self, error: BaseException | None = None) -> None:
        """Termina: confirmada, borra lo anterior apartado; si no, deshace lo puesto en su
        sitio, borra los temporales y deja la operación, si sigue «en curso», «cancelada»
        (``error`` de :data:`CANCELLATIONS`; cerrar los pasos es ``GeneratorExit``) o «fallida»
        con su motivo (sin error, «no se completó»). Lo que no se pueda registrar, en una nota
        del error. Volver a llamarla no hace nada."""
        if self._closed:
            return
        self._closed = True
        problems: list[str] = []
        if self._committed:
            for entry in self._grids:
                _discard(entry.backup)
            return
        for entry in reversed(self._grids):
            problems.extend(_undo(entry))
        problems.extend(self._abandon(error))
        if error is not None:
            for problem in problems:
                error.add_note(problem)

    def _abandon(self, error: BaseException | None) -> list[str]:
        """La operación, si sigue «en curso», «cancelada» o «fallida» con su motivo."""
        try:
            with self.project.read() as conn:
                row = conn.execute("SELECT status FROM gb_operation WHERE uid = ?",
                                   (self.handle.uid,)).fetchone()
            if row is None or row[0] != OperationStatus.RUNNING:
                return []
            if isinstance(error, GeneratorExit):
                self.handle.cancel(CANCELLED_REASON)
            elif isinstance(error, CANCELLATIONS):
                self.handle.cancel(cancel_reason(error))
            else:
                self.handle.fail(NOT_COMPLETED_REASON if error is None
                                 else failure_reason(error))
        except (GeoblenderError, OSError, sqlite3.Error) as exc:
            return [f"La operación «{self.handle.op_type}» ({self.handle.uid}) sigue «en curso» "
                    f"en el proyecto: no se pudo registrar cómo terminó ({exc})."]
        return []


# --- Los pasos de cada tipo en el proyecto ---------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class StoredVolume:
    """Una cubicación (o una diferencia) guardada: el resultado de ``volume_steps`` y sus
    salidas registradas."""

    result: VolumeResult
    records: tuple[DatasetRecord, ...]


@dataclass(frozen=True, slots=True, eq=False)
class StoredTonnage:
    """Las toneladas de una cubicación guardadas: su cálculo (tabla, cifras y avisos de lo que
    falta) y sus salidas registradas."""

    outputs: TonnageOutputs
    records: tuple[DatasetRecord, ...]


def project_sources(project: StoreProject, request: VolumeRequest, *,
                    version_uid: str = "") -> dict[str, SurfaceSource]:
    """Las superficies de ``request`` en ``project`` con la versión activa ``version_uid``,
    por papel (``start``, ``final`` y, con la columna, ``base_<u>`` y ``thickness_<u>``): lo que
    lee ``volume_steps`` (``reserves.surfaces.surface_source``; sus rechazos)."""
    found = {START: surface_source(project, request.start, version_uid=version_uid),
             FINAL: surface_source(project, request.final, version_uid=version_uid)}
    for unit in () if request.column is None else request.column.units:
        for ref, role in ((unit.base, base_role(unit.code)),
                          (unit.thickness, thickness_role(unit.code))):
            if ref is not None:
                found[role] = surface_source(project, ref, version_uid=version_uid)
    return found


def _param_m(handle: OperationHandle, key: str) -> float:
    """El parámetro ``key`` (m) que leyó la operación al empezar."""
    found = next((param for param in handle.params if param.key == key), None)
    if found is None or found.value is None:
        raise ValueError(f"la operación «{handle.op_type}» no leyó «{key}» al empezar "
                         "(begin_operation(params=…))")
    return convert(float(found.value), found.unit, "m")  # type: ignore[arg-type]


def _with_params(request: VolumeRequest, handle: OperationHandle) -> VolumeRequest:
    """``request`` con el espesor mínimo y el umbral de presencia que leyó la operación al
    empezar (los anotados; los de la petición no cuentan: RF-011-21)."""
    presence = request.presence_m
    if request.column is not None:
        presence = _param_m(handle, ANTHROPIC_PRESENCE)
    return replace(request, min_thickness_m=_param_m(handle, MIN_THICKNESS),
                   presence_m=presence)


def _difference_figures(result: VolumeResult) -> tuple[FigureSpec, ...]:
    """Las seis cifras de los totales de ``result`` con el ámbito de la diferencia
    (``{"difference": nombre}``; RF-011-23)."""
    whole = {"cubication": result.name}
    return tuple(replace(spec, scope={"difference": result.name}) for spec in result.figures
                 if spec.key in declared.DIFFERENCE_FIGURES and dict(spec.scope) == whole)


def volume_run(project: StoreProject, handle: OperationHandle, request: VolumeRequest, *,
               sources: Mapping[str, SurfaceSource] | None = None,
               budget_s: float = STEP_BUDGET_S,
               band_rows: int = BAND_ROWS) -> Iterator[Progress]:
    """Los pasos de ``res.volume`` o de ``res.difference`` (``handle``, «en curso») con la
    cubicación ``request`` en ``project`` (A10, A11): las superficies del proyecto o lo
    congelado de la versión (``sources``; por defecto, :func:`project_sources`), el espesor
    mínimo y el umbral de presencia que leyó la operación, los pasos de ``volume_steps`` (con
    la rejilla de diferencias en su temporal, si se pide) y, al final, la tabla ``res_vol_``
    (``res.volume``) o las seis cifras con el ámbito de la diferencia (``res.difference``),
    puestas en su sitio y confirmadas en una transacción. El último ``Progress`` lleva el
    :class:`StoredVolume`. Cerrar los pasos antes (Esc) o un fallo dejan la operación «cancelada»
    o «fallida» y nada en el proyecto (RF-011-25); el error sigue.

    ``ValueError`` al llamar si ``handle`` no es de uno de esos tipos o una diferencia no pide la
    rejilla o trae un reparto."""
    if not isinstance(request, VolumeRequest):
        raise TypeError(f"se cubica una VolumeRequest, no {type(request).__name__}")
    if not isinstance(handle, OperationHandle):
        raise TypeError(f"la cubicación es de un OperationHandle, no {handle!r}")
    if handle.op_type not in (declared.VOLUME, declared.DIFFERENCE):
        raise ValueError(f"volume_run es de {declared.VOLUME} o {declared.DIFFERENCE}, no de "
                         f"«{handle.op_type}»")
    if handle.op_type == declared.DIFFERENCE and (
            not request.difference_grid or request.domains is not None
            or request.slices is not None or request.column is not None):
        raise ValueError("una diferencia entre superficies escribe la rejilla y no reparte")
    return _volume_run(project, handle, request, sources, budget_s, band_rows)


def _volume_run(project: StoreProject, handle: OperationHandle, request: VolumeRequest,
                sources: Mapping[str, SurfaceSource] | None, budget_s: float,
                band_rows: int) -> Iterator[Progress]:
    with ResultWriter(project, handle) as out:
        request = _with_params(request, handle)
        found = (dict(sources) if sources is not None
                 else project_sources(project, request, version_uid=handle.version_uid))
        final = temporary = None
        if request.difference_grid:
            final, temporary = out.grid_paths(request.name)
        steps = volume_steps(request, found, budget_s=budget_s, difference_path=final,
                             difference_temporary=temporary, band_rows=band_rows)
        last: Progress | None = None
        with closing(steps):  # cerrar los pasos (Esc) cierra los de la cubicación
            for step in steps:
                if step.result is not None:
                    last = step
                    break
                yield Progress(step.phase, step.done, step.total + SAVE_STEPS, step.message)
        assert last is not None and isinstance(last.result, VolumeResult)
        result: VolumeResult = last.result
        total = last.total + SAVE_STEPS
        figures = result.figures
        if result.difference is not None:
            out.grid(request.name, result.difference)
        if handle.op_type == declared.VOLUME:
            out.table(declared.VOLUMES, request.name, result.rows)
        else:
            figures = _difference_figures(result)
        yield Progress("save", total - 1, total, f"Guardando «{request.name}»…")
        records = out.commit(figures=figures, message=last.message)
    yield Progress("save", total, total, last.message, result=StoredVolume(result, records))


def _input(conn: sqlite3.Connection, handle: OperationHandle, role: str) -> DatasetRecord:
    """El dato que consumió ``handle`` con el papel ``role``."""
    found = [item for item in handle.inputs if item.role == role]
    if len(found) != 1:
        raise ValueError(f"la operación «{handle.op_type}» no consumió un dato «{role}» "
                         "(begin_operation(inputs=…))")
    record = dataset_registry.get(conn, found[0].uid)
    if record is None:  # inalcanzable: begin_operation lo resolvió
        raise ValueError(f"«{found[0].name}» no está en el proyecto")
    return record


def _tonnage_summary(name: str, outputs: TonnageOutputs) -> str:
    groups = outputs.result.groups
    total = next((group.total_t for group in groups
                  if group.domain == "*" and group.bench is None), None)
    if total is None:
        return (f"«{name}»: sin total de toneladas ({len(outputs.result.missing)} parámetros "
                "sin valor)")
    return f"«{name}»: {format_number(total, 1)} t"


def tonnage_run(project: StoreProject, handle: OperationHandle) -> Iterator[Progress]:
    """Los pasos de ``res.tonnage`` (``handle``, «en curso», con los ajustes de
    ``reserves.provenance.tonnage_settings``) en ``project`` (D-16, A8, A9): la tabla de
    volúmenes y la columna que consumió (sin releer las superficies), los parámetros que leyó al
    empezar (versión → proyecto, RF-011-21) y la tabla ``res_ton_`` con sus cifras, confirmadas
    en una transacción. El último ``Progress`` lleva el :class:`StoredTonnage`. Un fallo o
    cerrar los pasos antes no dejan nada (RF-011-25)."""
    if not isinstance(handle, OperationHandle):
        raise TypeError(f"las toneladas son de un OperationHandle, no {handle!r}")
    if handle.op_type != declared.TONNAGE:
        raise ValueError(f"tonnage_run es de {declared.TONNAGE}, no de «{handle.op_type}»")
    name = handle.settings.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("los ajustes de res.tonnage llevan el nombre de su cubicación")
    return _tonnage_run(project, handle, name)


def _tonnage_run(project: StoreProject, handle: OperationHandle,
                 name: str) -> Iterator[Progress]:
    total = 3
    with ResultWriter(project, handle) as out:
        with project.read() as conn:
            rows = read_rows(conn, _input(conn, handle, declared.VOLUMES_ROLE).locator)
            column = read_column(conn, _input(conn, handle, declared.MATERIALS_ROLE).locator)
        if column is None:
            raise ResError("res.materials_missing", obj="Columna de materiales", field="units",
                           value=0)
        yield Progress("read", 1, total, f"Pesando «{name}»: la tabla de volúmenes leída…")
        outputs = tonnage_outputs(rows, column, {param.key: param for param in handle.params},
                                  name=name)
        out.table(declared.TONNES, name, outputs.rows)
        yield Progress("save", 2, total, f"Guardando las toneladas de «{name}»…")
        message = _tonnage_summary(name, outputs)
        records = out.commit(figures=outputs.figures, message=message)
    yield Progress("save", total, total, message, result=StoredTonnage(outputs, records))


def save_materials(project: StoreProject, handle: OperationHandle,
                   column: MaterialColumn) -> tuple[DatasetRecord, ...]:
    """``res.edit_materials`` (``handle``, «en curso», del proyecto): guarda la columna
    ``column`` (que se valida) como ``res_materials`` en una transacción (D-12) y devuelve su
    registro. Si falla, la operación queda «fallida» y la columna anterior, como estaba."""
    if not isinstance(handle, OperationHandle) or handle.op_type != declared.EDIT_MATERIALS:
        raise ValueError(f"la columna la guarda una operación {declared.EDIT_MATERIALS}")
    with ResultWriter(project, handle) as out:
        out.materials(column)
        return out.commit(message=f"Columna de materiales: {len(column.units)} unidades")


def previous_operation(project: StoreProject, op_type: str, name: str, *,
                       version: str) -> str | None:
    """La operación ``op_type`` hecha y sin sustituir que escribió el dato de la cubicación
    ``name`` vivo en la versión ``version`` (uid o código): a la que sustituye la nueva con el
    mismo nombre (D-30, ``begin_operation(…, supersedes=…)``); ``None`` si no hay ninguna.
    ``VersionError`` si la versión no existe."""
    families = {declared.VOLUME: declared.VOLUMES, declared.TONNAGE: declared.TONNES,
                declared.DIFFERENCE: declared.DIFFERENCE_GRID,
                declared.STAGES: declared.STAGE_TABLE}
    if op_type not in families:
        raise ValueError(f"«{op_type}» no es una operación de versión de la cubicación")
    dataset = declared.dataset_name(families[op_type], name)
    with project.read() as conn:
        found = versions_read.version(conn, version)
        if found is None:
            raise VersionError("core.version_unknown", field="versión", value=version,
                               version=version)
        record = dataset_registry.get(conn, dataset, version_uid=found.uid)
        if record is None or record.name != dataset:
            return None
        row = conn.execute("SELECT op_type, status, superseded_by FROM gb_operation "
                           "WHERE uid = ?", (record.operation_uid,)).fetchone()
    if row is None or row[0] != op_type or row[1] != OperationStatus.DONE or row[2] is not None:
        return None
    return record.operation_uid
