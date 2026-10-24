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
   o por pasos, :meth:`~ResultWriter.table_steps`; :meth:`~ResultWriter.materials`).
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
leyó al empezar, D-16; pesa y calcula el hash de su tabla por pasos de su presupuesto, T33),
:func:`stages_run` (``res.stages``: de las tablas de volúmenes de sus momentos y de la
directa, con la tolerancia que leyó, A13) y :func:`save_materials` (``res.edit_materials``).
Repetir el nombre de una cubicación de la versión la sustituye (D-30):
:func:`previous_operation` da la operación a la que sustituye la nueva
(``begin_operation(…, supersedes=…)``), que escribe contenido nuevo de los mismos datos. **Las capas** de una cubicación (D-32, T32): el ámbito
(:func:`load_scope`, :func:`read_scope`: una capa de contornos o la unión de una de dominios) y
los dominios (:func:`load_domain_layer`, :func:`read_domain_layer`), del proyecto o de una tabla
en una conexión (su copia congelada, al reproducir). **La rejilla de diferencias registrada**
(T22; A15, D-29): :func:`stored_difference` dice de qué cubicación, versión y revisión es, su
superficie final y el espesor mínimo que leyó su operación, y :func:`difference_sources` da
lo que lee su vista; :func:`grid_writer`, de qué tipo es la operación que la escribió (una
cubicación y una diferencia no comparten una rejilla). **Las cubicaciones de una versión** (T24):
:func:`cubications` (su tabla de volúmenes viva, si reparte por unidades y su tabla de
toneladas: lo que ofrecen los momentos de extracción y «Ratios…») y
:func:`cubication_ratios` (las filas del filtro de relaciones de sus toneladas, D-35).
**Recalcular** (A12, T15):
:func:`recompute_run` empieza la operación que sustituye a una obsoleta (en la revisión abierta
de su versión, con la columna vigente, las capas que consumió y sus parámetros resueltos de
nuevo) y da sus pasos, que avanza la cola de ``res`` en ``bl``. Python puro (nivel 9).
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable, Generator, Iterator, Mapping, Sequence
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
    RECORD_COLUMNS,
    DatasetRecord,
    DatasetSpec,
    Store,
)
from ..core.errors import GeoblenderError
from ..core.gpkg.base import ColumnDef, create_attribute_table, create_structure, set_column_titles
from ..core.hashing import HashCancelled
from ..core.paths import check_path_length
from ..core.project.model import Progress
from ..core.provenance.figures import FigureSpec
from ..core.provenance.graph import drain
from ..core.provenance.operations import (
    CANCEL_REASON_PREFIX,
    NOT_COMPLETED_REASON,
    Executor,
    OperationHandle,
    OperationStatus,
    begin_operation,
    cancel_reason,
    failure_reason,
)
from ..core.provenance.recompute import RecomputeRequest
from ..core.units import convert
from ..core.versions import read as versions_read
from ..core.versions.model import VersionError
from ..gis.geotiff.writer import target_locked, write_failed
from ..gis.messages import GisError
from ..gis.provenance import BOUNDARY as GIS_BOUNDARY
from ..gis.provenance import DOMAINS as GIS_DOMAINS
from ..gis.provenance import FAMILIES_BY_CODE as GIS_FAMILIES
from ..gis.store import (
    DomainFeature,
    StoreProject,
    backup_path,
    insert_rows,
    load_domains,
    load_regions,
    project_references,
    read_domains,
    read_regions,
    temporary_path,
)
from . import provenance as declared
from .materials import COLUMNS as MATERIAL_COLUMNS
from .materials import CREATE_TABLE as MATERIALS_DDL
from .materials import TABLE as MATERIALS_TABLE
from .materials import MaterialColumn, column_rows, read_column
from .messages import ResError
from .params import ANTHROPIC_PRESENCE, MIN_THICKNESS, STAGES_TOLERANCE
from .polygons import Polygon, domain_polygons
from .stages import StagesResult, StageTable, stages
from .surfaces import BAND_ROWS, SurfaceRef, SurfaceSource, grid_source, surface_source
from .table import (
    COLUMN_NAMES,
    COLUMNS,
    STAGE_COLUMN_NAMES,
    STAGE_COLUMNS,
    STAGE_TITLES,
    TITLES,
    Row,
    StageRow,
    number_text,
    ratio_rows,
    read_rows,
)
from .volumes import (
    FINAL,
    START,
    STEP_BUDGET_S,
    DifferenceGrid,
    DomainLayer,
    TonnageOutputs,
    VolumeRequest,
    VolumeResult,
    base_role,
    paced,
    step_budget,
    thickness_role,
    tonnage_work,
    volume_steps,
)

__all__ = [
    "CANCELLATIONS",
    "CANCELLED_REASON",
    "DIGEST_ROWS",
    "DIGEST_TABLE",
    "RECOMPUTED",
    "SAVE_STEPS",
    "STAGE_TABLE_COLUMNS",
    "TABLE_COLUMNS",
    "TONNAGE_PHASES",
    "TONNAGE_TICKS",
    "Cubication",
    "ResultWriter",
    "StoredDifference",
    "StoredStages",
    "StoredTonnage",
    "StoredVolume",
    "cubication_ratios",
    "cubications",
    "difference_figures",
    "difference_sources",
    "grid_writer",
    "load_domain_layer",
    "load_scope",
    "materials_digest",
    "previous_operation",
    "project_sources",
    "read_domain_layer",
    "read_scope",
    "recompute_run",
    "save_materials",
    "stages_digest",
    "stages_run",
    "stored_difference",
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
DIGEST_ROWS = 2_000
"""Las filas de cada unidad de trabajo al copiar una tabla al GeoPackage en memoria de su hash
(T33; leerla con su lector va por los trozos de ``core.content.builtin.layer_steps``)."""
TONNAGE_PHASES = ("read", "weigh", "hash", "save")
"""Las fases de los pasos de :func:`tonnage_run`, en su orden: leer la tabla de volúmenes y la
columna, pesar y hacer la tabla de las toneladas, su hash y confirmar."""
TONNAGE_TICKS = 1_000
"""El total del avance de los pasos de :func:`tonnage_run` (milésimas: cuántos pasos da depende
de lo que tarda cada uno)."""
_INSERT_SHARE = 0.2  # la parte del hash de una tabla que es copiar sus filas (el resto, leerla)
_TONNAGE_SPANS = {"read": (0.0, 0.05), "weigh": (0.05, 0.5), "hash": (0.5, 0.95)}
_TONNAGE_TEXTS = {"weigh": "Pesando «{name}»: las toneladas de cada unidad, dominio y rodaja…",
                  "hash": "Pesando «{name}»: la huella de la tabla de las toneladas…"}


def _column_def(sql: str, name: str) -> ColumnDef:
    sql_type, _space, rest = sql.partition(" ")
    return ColumnDef(name, sql_type, not_null="NOT NULL" in rest)


TABLE_COLUMNS: tuple[ColumnDef, ...] = tuple(_column_def(column.sql, column.name)
                                             for column in COLUMNS)
"""Las columnas tipadas de una tabla ``report`` de ``res`` (``reserves.table.COLUMNS``) como las
crea ``core.gpkg.base.create_attribute_table``."""
STAGE_TABLE_COLUMNS: tuple[ColumnDef, ...] = tuple(_column_def(column.sql, column.name)
                                                   for column in STAGE_COLUMNS)
"""Las de la tabla de los momentos (``res_stg_``: ``reserves.table.STAGE_COLUMNS``)."""

_OBJ = "Cubicación"
_FIELD = "ubicación"
_REPORTS = (declared.VOLUMES, declared.TONNES, declared.STAGE_TABLE)


# --- El hash de las tablas (R4) ----------------------------------------------------------------


def _create_report(conn: sqlite3.Connection, name: str, identifier: str,
                   description: str) -> None:
    """Crea la tabla ``report`` ``name`` y la registra en ``gpkg_contents`` (``attributes``)."""
    create_attribute_table(conn, name, TABLE_COLUMNS, identifier, description)


def _create_stages(conn: sqlite3.Connection, name: str, identifier: str,
                   description: str) -> None:
    """Crea la tabla de los momentos ``name`` (con su columna ``stage``) y la registra en
    ``gpkg_contents`` (``attributes``)."""
    create_attribute_table(conn, name, STAGE_TABLE_COLUMNS, identifier, description)


def _create_materials(conn: sqlite3.Connection, name: str, identifier: str,
                      description: str) -> None:
    """Crea la tabla de la columna (con sus ``CHECK`` y su ``UNIQUE``, plan §5.2.1) y la
    registra en ``gpkg_contents`` (``attributes``)."""
    if name != MATERIALS_TABLE:
        raise ValueError(f"la columna de materiales es la tabla «{MATERIALS_TABLE}», no «{name}»")
    conn.execute(MATERIALS_DDL)
    conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description) "
                 "VALUES (?, 'attributes', ?, ?)", (name, identifier, description))


def _digest_steps(create: Callable[[sqlite3.Connection, str, str, str], None], layer: str,
                  names: Sequence[str], rows: Sequence[Sequence[Any]]
                  ) -> Generator[float, None, ContentDigest]:
    """El ``ContentDigest`` (``core.gpkg_layer@1``, sin declaraciones) de una tabla que crea
    ``create`` con las filas ``rows`` (valores de las columnas ``names``), sin escribirla en el
    proyecto: en un GeoPackage en memoria con la misma estructura, leída con
    ``core.content.builtin.layer_steps``, la función con que el registro de la 008 hashea una
    tabla del proyecto (ADR-0024 §5). Por unidades de trabajo (T33): copiar cada trozo de
    :data:`DIGEST_ROWS` filas y leer cada trozo de ``layer_steps``; cada una da la parte hecha
    (0–1). Cerrarlo antes cierra el GeoPackage en memoria."""
    conn = sqlite3.connect(":memory:")
    try:
        create_structure(conn)
        create(conn, layer, layer, "")
        values = [tuple(row) for row in rows]
        for first in range(0, len(values), DIGEST_ROWS):
            insert_rows(conn, layer, names, values[first:first + DIGEST_ROWS])
            yield _INSERT_SHARE * min(first + DIGEST_ROWS, len(values)) / len(values)
        request = core_builtin.GPKG_LAYER.request(
            "table", DATASET_DECLARATIONS, {"main": Path(layer)}, {"layer": layer},
            normalizer=NORMALIZER)
        steps = core_builtin.layer_steps(conn, request)
        try:
            for done in steps:
                yield _INSERT_SHARE + (1.0 - _INSERT_SHARE) * done
        finally:
            steps.close()
        return request.hasher.digest()
    finally:
        conn.close()


def _digest(create: Callable[[sqlite3.Connection, str, str, str], None], layer: str,
            names: Sequence[str], rows: Sequence[Sequence[Any]]) -> ContentDigest:
    """:func:`_digest_steps` de una vez."""
    return drain(_digest_steps(create, layer, names, rows))


def table_digest(rows: Sequence[Row]) -> ContentDigest:
    """El hash de contenido que da la tabla ``report`` de ``res`` con las filas ``rows`` al
    escribirla en el proyecto (R4: se calcula antes de la transacción)."""
    return _digest(_create_report, DIGEST_TABLE, COLUMN_NAMES, [row.values() for row in rows])


def stages_digest(rows: Sequence[StageRow]) -> ContentDigest:
    """El hash de contenido que da la tabla de los momentos (``res_stg_``) con las filas
    ``rows`` al escribirla en el proyecto."""
    return _digest(_create_stages, DIGEST_TABLE, STAGE_COLUMN_NAMES,
                   [row.values() for row in rows])


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

    def table(self, family: str, name: str, rows: Sequence[Row] | Sequence[StageRow]
              ) -> DatasetSpec:
        """Prepara la tabla ``report`` de la familia ``family`` (``vol``, ``ton`` o ``stg``) de
        la cubicación ``name`` con las filas ``rows`` (``reserves.table.Row``; en la de los
        momentos, ``StageRow``) y su hash, que se calcula aquí, fuera de la transacción (R4).
        Devuelve su ``DatasetSpec``. ``GisError`` si su sitio es de otro. De una vez; por pasos,
        :meth:`table_steps`."""
        return drain(self.table_steps(family, name, rows))

    def table_steps(self, family: str, name: str, rows: Sequence[Row] | Sequence[StageRow]
                    ) -> Generator[float, None, DatasetSpec]:
        """:meth:`table` por unidades de trabajo (RNF-011-04; T33): la familia y las filas se
        comprueban al llamar; cada unidad copia un trozo de las filas al GeoPackage en memoria
        de su hash o lee un trozo con su lector y da la parte hecha (0–1); la última prepara la
        tabla y devuelve su ``DatasetSpec``. Cerrarlo antes no prepara nada."""
        self._check_open()
        if family not in _REPORTS:
            raise ValueError(f"«{family}» no es una tabla de la cubicación: es una de "
                             f"{', '.join(_REPORTS)}")
        self._produces(family)
        chosen = tuple(rows)
        staged = family == declared.STAGE_TABLE
        kind: type = StageRow if staged else Row
        for row in chosen:
            if not isinstance(row, kind):
                raise TypeError(f"una fila de una tabla «{family}» de res es una "
                                f"{kind.__name__}, no {row!r}")
        return self._table_steps(family, name, chosen, staged)

    def _table_steps(self, family: str, name: str, chosen: tuple[Row, ...] | tuple[StageRow, ...],
                     staged: bool) -> Generator[float, None, DatasetSpec]:
        create, names, titles = ((_create_stages, STAGE_COLUMN_NAMES, STAGE_TITLES) if staged
                                 else (_create_report, COLUMN_NAMES, TITLES))
        values = tuple(row.values() for row in chosen)
        digest = yield from _digest_steps(create, DIGEST_TABLE, names, values)
        self._check_open()
        spec = declared.dataset_spec(family, name, self.version_code, content=digest)
        if any(other.name == spec.name for other in self._specs):
            raise ValueError(f"una operación escribe cada dato una vez: «{spec.name}» se repite")
        with self.project.read() as conn:
            self._check_place(conn, spec)
        label = declared.FAMILIES_BY_CODE[family].label
        identifier = f"{label} «{name}» {self.version_code}"
        description = (f"{label} «{name}» de la versión {self.version_code}, de Geoblender: una "
                       f"fila por valor ({'momento, ' if staged else ''}dominio, rodaja, unidad, "
                       "componente, dato, valor, unidad de medida y nota)")
        self._tables.append(_Table(spec, identifier, description, create, names, values, titles))
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


# --- Las capas de una cubicación: el ámbito y los dominios (D-32, T32) ------------------------

_LAYER_OBJ = "Capa de la cubicación"


def _layer_family(name: str) -> str:
    """La familia de la capa ``name``: contornos (``bnd``) o dominios (``dom``)."""
    for code in (GIS_BOUNDARY, GIS_DOMAINS):
        if name.startswith(GIS_FAMILIES[code].prefix):
            return code
    raise ValueError(f"«{name}» no es una capa de contornos (gis_bnd_) ni de dominios "
                     "(gis_dom_): no es el ámbito ni los dominios de una cubicación")


def _contour_scope(name: str, contours: Sequence[Sequence[Any]],
                   holes: Sequence[Any]) -> tuple[Polygon, ...]:
    """El ámbito de los contornos de una capa ``gis_bnd_``: cada polígono con sus huecos."""
    if holes:
        raise ValueError(f"la capa de contornos «{name}» tiene huecos sueltos (entidades "
                         "«hole»): aún no sirve de ámbito de una cubicación")
    if not contours:
        raise ValueError(f"la capa «{name}» no tiene polígonos: no sirve de ámbito")
    return tuple(Polygon(fid, "", tuple(rings)) for fid, rings in enumerate(contours, start=1))


def _domains_scope(name: str, features: Sequence[DomainFeature]) -> tuple[Polygon, ...]:
    """El ámbito de una capa de dominios: la unión de sus polígonos (cada parte, uno)."""
    found = tuple(Polygon(feature.fid, "", tuple(rings)) for feature in features
                  for rings in feature.polygons)
    if not found:
        raise ValueError(f"la capa «{name}» no tiene polígonos: no sirve de ámbito")
    return found


def read_scope(conn: sqlite3.Connection, table: str, name: str) -> tuple[Polygon, ...]:
    """El ámbito de una cubicación de la capa ``name`` (el nombre de su dato) en su tabla
    ``table`` de ``conn`` (la del proyecto o su copia congelada, al reproducirla): de una capa
    de contornos (``gis_bnd_``), cada contorno con sus huecos; de una de dominios
    (``gis_dom_``), la unión de sus polígonos (plan D-32). Polígonos sin valor, con sus anillos
    tal como están guardados. ``ValueError`` si no es una de esas capas, si no tiene polígonos
    o si tiene huecos sueltos (entidades «hole» de una capa de contornos)."""
    if _layer_family(name) == GIS_BOUNDARY:
        return _contour_scope(name, *read_regions(conn, table))
    return _domains_scope(name, read_domains(conn, table))


def read_domain_layer(conn: sqlite3.Connection, table: str, name: str,
                      field: str) -> DomainLayer:
    """La capa de dominios ``name`` (``gis_dom_``) de su tabla ``table`` en ``conn`` (la del
    proyecto o su copia congelada) para repartir por su columna ``field`` (RF-011-07):
    ``reserves.polygons.domain_polygons``. ``ValueError`` si no es una capa de dominios, si no
    tiene la columna o si no tiene polígonos."""
    if _layer_family(name) != GIS_DOMAINS:
        raise ValueError(f"«{name}» no es una capa de dominios (gis_dom_)")
    return DomainLayer(name, field, domain_polygons(read_domains(conn, table), field))


def _layer_record(project: StoreProject, ref: str) -> DatasetRecord:
    if not isinstance(ref, str):
        raise TypeError(f"una capa se indica por su nombre o su uid, no {ref!r}")
    with project.read() as conn:
        record = dataset_registry.get(conn, ref)
    if record is None:
        raise GisError("gis.dataset_unknown", obj=_LAYER_OBJ, field="dato", value=ref)
    _layer_family(record.name)
    return record


def load_scope(project: StoreProject, ref: str) -> tuple[Polygon, ...]:
    """El ámbito de la capa ``ref`` del proyecto (su nombre o su uid; :func:`read_scope`), lo
    que consume una cubicación con el papel ``scope`` (``reserves.provenance.SCOPE_ROLE``).
    Además de los de :func:`read_scope`, ``gis.dataset_unknown`` si no hay tal dato y
    ``gis.dataset_file_missing`` si falta su tabla."""
    record = _layer_record(project, ref)
    if _layer_family(record.name) == GIS_BOUNDARY:
        return _contour_scope(record.name, *load_regions(project, record))
    return _domains_scope(record.name, load_domains(project, record))


def load_domain_layer(project: StoreProject, ref: str, field: str) -> DomainLayer:
    """La capa de dominios ``ref`` del proyecto (su nombre o su uid) para repartir por su
    columna ``field`` (:func:`read_domain_layer`): la que consume una cubicación con el papel
    ``domains``, con el nombre de su dato. Los mismos errores que :func:`load_scope`."""
    record = _layer_record(project, ref)
    if _layer_family(record.name) != GIS_DOMAINS:
        raise ValueError(f"«{record.name}» no es una capa de dominios (gis_dom_)")
    return DomainLayer(record.name, field,
                       domain_polygons(load_domains(project, record), field))


# --- La rejilla de diferencias registrada (T22; RF-011-05, A15, D-29) --------------------------

_DIFFERENCE_OBJ = "Rejilla de diferencias"
_NO_VERSION = "—"
_PRODUCER = "SELECT settings, revision_uid FROM gb_operation WHERE uid = ?"
_THRESHOLD = ("SELECT value, unit FROM gb_operation_param WHERE operation_uid = ? AND key = ? "
              "ORDER BY fid LIMIT 1")


@dataclass(frozen=True, slots=True)
class StoredDifference:
    """Una rejilla de diferencias registrada (``res_dif_``) y lo que dice de ella la operación
    que la escribió (``res.volume`` o ``res.difference``): su registro, el nombre de su
    cubicación, su versión (uid; '' del proyecto), su revisión («V01.r1»; '' sin ella), su
    superficie final (el dato, lo congelado o la cota constante de sus ajustes) y el espesor
    mínimo que leyó (m: la diferencia que no pasa de él no es movimiento, RF-011-04)."""

    record: DatasetRecord
    name: str
    version_uid: str
    revision: str
    final: SurfaceRef
    threshold_m: float


def stored_difference(project: StoreProject, ref: str) -> StoredDifference:
    """La rejilla de diferencias ``ref`` del proyecto (su uid o su nombre) con lo que dice de
    ella su operación (:class:`StoredDifference`): lo que necesitan su vista (A15) y su
    exportación (D-29), también en una versión SUPERADO. ``ResError``
    ``res.difference_unknown`` si no es una rejilla de diferencias viva del proyecto. No
    escribe nada."""
    if not isinstance(ref, str) or not ref:
        raise TypeError(f"una rejilla de diferencias se indica por su uid o su nombre, no {ref!r}")
    prefix = declared.FAMILIES_BY_CODE[declared.DIFFERENCE_GRID].prefix
    with project.read() as conn:
        record = dataset_registry.get(conn, ref)
        if (record is None or not record.live or record.module != declared.MODULE
                or not record.name.startswith(prefix)):
            raise ResError("res.difference_unknown", obj=_DIFFERENCE_OBJ, field="rejilla",
                           value=ref, version=_NO_VERSION)
        row = conn.execute(_PRODUCER, (record.operation_uid,)).fetchone()
        used = conn.execute(_THRESHOLD, (record.operation_uid, MIN_THICKNESS)).fetchone()
        version_uid = versions_read.dataset_versions(conn, [record.uid]).get(record.uid, "")
        revision = (versions_read.revision(conn, str(row[1]))
                    if row is not None and row[1] else None)
        version = (None if revision is None
                   else versions_read.version(conn, revision.version_uid))
    if row is None:  # inalcanzable: el dato lo escribió una operación del proyecto
        raise ValueError(f"«{record.name}» no tiene la operación que lo escribió")
    settings = json.loads(row[0] or "{}")
    threshold = 0.0 if used is None or used[0] is None else convert(
        float(json.loads(used[0])), str(used[1] or "m"), "m")
    return StoredDifference(
        record, str(settings.get("name") or record.name), version_uid,
        "" if revision is None or version is None else revision.label(version.code),
        declared.settings_surface(settings, FINAL), float(threshold))


def difference_sources(project: StoreProject,
                       stored: StoredDifference) -> tuple[SurfaceSource, SurfaceSource]:
    """Lo que se lee para ver ``stored`` (A15): su superficie final (la de sus ajustes,
    ``reserves.surfaces.surface_source`` en su versión: un dato, lo congelado en la revisión de
    la que parte o la cota constante) y la propia rejilla (su GeoTIFF, en las referencias del
    proyecto si no las declara). Los errores de ``surface_source`` (la superficie ya no está);
    ``gis.dataset_file_missing`` si falta el fichero de la rejilla."""
    final = surface_source(project, stored.final, version_uid=stored.version_uid)
    record = stored.record
    path = Path(project.root, *record.locator.split("/"))
    if not path.is_file():
        raise GisError("gis.dataset_file_missing", obj=f"{_DIFFERENCE_OBJ}: «{record.name}»",
                       field="ubicación", value=record.locator, file=path.name,
                       name=record.name)
    crs, vertical = project_references(project)
    return final, grid_source(path, name=record.name, crs=crs, vertical=vertical)


def _param_m(handle: OperationHandle, key: str) -> float:
    """El parámetro ``key`` (m) que leyó la operación al empezar."""
    return _param(handle, key, "m")


def _with_params(request: VolumeRequest, handle: OperationHandle) -> VolumeRequest:
    """``request`` con el espesor mínimo y el umbral de presencia que leyó la operación al
    empezar (los anotados; los de la petición no cuentan: RF-011-21)."""
    presence = request.presence_m
    if request.column is not None:
        presence = _param_m(handle, ANTHROPIC_PRESENCE)
    return replace(request, min_thickness_m=_param_m(handle, MIN_THICKNESS),
                   presence_m=presence)


def difference_figures(result: VolumeResult) -> tuple[FigureSpec, ...]:
    """Las seis cifras de los totales de ``result`` con el ámbito de la diferencia
    (``{"difference": nombre}``; RF-011-23): las de ``res.difference``."""
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
            figures = difference_figures(result)
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
    return f"«{name}»: {number_text(total, 't')} t"


def tonnage_run(project: StoreProject, handle: OperationHandle, *,
                budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """Los pasos de ``res.tonnage`` (``handle``, «en curso», con los ajustes de
    ``reserves.provenance.tonnage_settings``) en ``project`` (D-16, A8, A9): la tabla de
    volúmenes y la columna que consumió (sin releer las superficies), los parámetros que leyó al
    empezar (versión → proyecto, RF-011-21) y la tabla ``res_ton_`` con sus cifras, confirmadas
    en una transacción. Fases (:data:`TONNAGE_PHASES`; avance en :data:`TONNAGE_TICKS`): leer
    (un paso), pesar y hacer la tabla y su hash (pasos de ``budget_s`` como mucho:
    ``reserves.volumes.tonnage_work`` y :meth:`ResultWriter.table_steps`; RNF-011-04, T33) y
    confirmar (un paso: la transacción no se trocea, R4). El último ``Progress`` lleva el
    :class:`StoredTonnage`. Un fallo o cerrar los pasos antes no dejan nada (RF-011-25)."""
    if not isinstance(handle, OperationHandle):
        raise TypeError(f"las toneladas son de un OperationHandle, no {handle!r}")
    if handle.op_type != declared.TONNAGE:
        raise ValueError(f"tonnage_run es de {declared.TONNAGE}, no de «{handle.op_type}»")
    name = handle.settings.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("los ajustes de res.tonnage llevan el nombre de su cubicación")
    return _tonnage_run(project, handle, name, step_budget(budget_s))


def _ticks(phase: str, fraction: float) -> int:
    """El avance (de :data:`TONNAGE_TICKS`) de ``fraction`` (0–1) de la fase ``phase``."""
    low, high = _TONNAGE_SPANS[phase]
    return round(TONNAGE_TICKS * (low + (high - low) * fraction))


def _labelled[T](phase: str, work: Generator[float, None, T]
                 ) -> Generator[tuple[str, float], None, T]:
    """Las unidades de trabajo de ``work`` (cada una da su parte hecha) con su fase."""
    with closing(work):
        while True:
            try:
                fraction = next(work)
            except StopIteration as stop:
                return stop.value
            yield phase, fraction


def _tonnage_work(out: ResultWriter, rows: Sequence[Row], column: MaterialColumn,
                  params: Mapping[str, Any], name: str
                  ) -> Generator[tuple[str, float], None, TonnageOutputs]:
    """Las unidades de trabajo de pesar y de preparar la tabla ``res_ton_`` con su hash."""
    outputs = yield from _labelled("weigh", tonnage_work(rows, column, params, name=name))
    yield from _labelled("hash", out.table_steps(declared.TONNES, name, outputs.rows))
    return outputs


def _tonnage_run(project: StoreProject, handle: OperationHandle, name: str,
                 budget_s: float) -> Iterator[Progress]:
    with ResultWriter(project, handle) as out:
        with project.read() as conn:
            rows = read_rows(conn, _input(conn, handle, declared.VOLUMES_ROLE).locator)
            column = read_column(conn, _input(conn, handle, declared.MATERIALS_ROLE).locator)
        if column is None:
            raise ResError("res.materials_missing", obj="Columna de materiales", field="units",
                           value=0)
        yield Progress("read", _ticks("read", 1.0), TONNAGE_TICKS,
                       f"Pesando «{name}»: la tabla de volúmenes leída…")
        params = {param.key: param for param in handle.params}
        steps = paced(_tonnage_work(out, rows, column, params, name), budget_s)
        with closing(steps):  # cerrar los pasos (Esc) cierra el hash a medias
            while True:
                try:
                    phase, fraction = next(steps)
                except StopIteration as stop:
                    outputs: TonnageOutputs = stop.value
                    break
                yield Progress(phase, _ticks(phase, fraction), TONNAGE_TICKS,
                               _TONNAGE_TEXTS[phase].format(name=name))
        yield Progress("save", _ticks("hash", 1.0), TONNAGE_TICKS,
                       f"Guardando las toneladas de «{name}»…")
        message = _tonnage_summary(name, outputs)
        records = out.commit(figures=outputs.figures, message=message)
    yield Progress("save", TONNAGE_TICKS, TONNAGE_TICKS, message,
                   result=StoredTonnage(outputs, records))


@dataclass(frozen=True, slots=True, eq=False)
class StoredStages:
    """Una cubicación por momentos guardada: su comparación (tabla, cifras y avisos) y sus
    salidas registradas."""

    result: StagesResult
    records: tuple[DatasetRecord, ...]


def _param(handle: OperationHandle, key: str, unit: str) -> float:
    """El parámetro ``key`` (en ``unit``) que leyó la operación al empezar."""
    found = next((param for param in handle.params if param.key == key), None)
    if found is None or found.value is None:
        raise ValueError(f"la operación «{handle.op_type}» no leyó «{key}» al empezar "
                         "(begin_operation(params=…))")
    return convert(float(found.value), found.unit, unit)  # type: ignore[arg-type]


def _materials_sha(conn: sqlite3.Connection, record: DatasetRecord) -> str | None:
    """El hash de la columna de materiales que consumió la operación que escribió la tabla de
    volúmenes ``record`` (``None``: sin unidades)."""
    found = conn.execute(
        "SELECT content_sha256 FROM gb_operation_io WHERE operation_uid = ? AND "
        "direction = 'in' AND role = ?", (record.operation_uid, declared.MATERIALS_ROLE),
    ).fetchone()
    return None if found is None else str(found[0])


def _stages_names(settings: Mapping[str, Any]) -> tuple[str, list[str], str]:
    """El nombre, los momentos y la directa de los ajustes de ``res.stages``."""
    name, moments, direct = (settings.get(key) for key in ("name", "moments", "direct"))
    if not isinstance(name, str) or not name.strip() or not isinstance(moments, list) \
            or not isinstance(direct, str):
        raise ValueError("los ajustes de res.stages llevan su nombre, sus momentos y su "
                         f"directa, no {dict(settings)!r}")
    return name, moments, direct


def stages_run(project: StoreProject, handle: OperationHandle) -> Iterator[Progress]:
    """Los pasos de ``res.stages`` (``handle``, «en curso», con los ajustes de
    ``reserves.provenance.stages_settings``) en ``project`` (A13, D-33): las tablas de
    volúmenes que consumió (sus momentos, ``stage_1``…, y la directa, ``direct``; sin releer las
    superficies) con la columna de materiales con que se cubicó cada una, la tolerancia que leyó
    al empezar y la tabla ``res_stg_`` con sus cifras, confirmadas en una transacción. El último
    ``Progress`` lleva el :class:`StoredStages` (con sus avisos). Un fallo o cerrar los pasos
    antes no dejan nada (RF-011-25)."""
    if not isinstance(handle, OperationHandle):
        raise TypeError(f"los momentos son de un OperationHandle, no {handle!r}")
    if handle.op_type != declared.STAGES:
        raise ValueError(f"stages_run es de {declared.STAGES}, no de «{handle.op_type}»")
    return _stages_run(project, handle, *_stages_names(handle.settings))


def _stages_run(project: StoreProject, handle: OperationHandle, name: str,
                moments: list[str], direct: str) -> Iterator[Progress]:
    total = 3
    with ResultWriter(project, handle) as out:
        roles = [(declared.stage_role(position), moment)
                 for position, moment in enumerate(moments, start=1)]
        tables: list[StageTable] = []
        with project.read() as conn:
            for role, cubication in (*roles, (declared.DIRECT_ROLE, direct)):
                record = _input(conn, handle, role)
                tables.append(StageTable(cubication, read_rows(conn, record.locator),
                                         _materials_sha(conn, record)))
            column = read_column(conn)
        yield Progress("read", 1, total, f"Comparando «{name}»: las tablas de volúmenes leídas…")
        names = {} if column is None else {unit.code: unit.name for unit in column.units}
        result = stages(tables[:-1], tables[-1], name=name,
                        tolerance_pct=_param(handle, STAGES_TOLERANCE, "%"), unit_names=names)
        out.table(declared.STAGE_TABLE, name, result.rows)
        yield Progress("save", 2, total, f"Guardando «{name}»…")
        cut = result.comparison()
        shown = "—" if cut.diff_pct is None else f"{number_text(cut.diff_pct, '%')} %"
        message = (f"«{name}»: suma de los momentos {number_text(cut.sum_m3, 'm3')} m³, "
                   f"directa {number_text(cut.direct_m3, 'm3')} m³, diferencia "
                   f"{number_text(cut.diff_m3, 'm3')} m³ ({shown})")
        records = out.commit(figures=result.figures, message=message)
    yield Progress("save", total, total, message, result=StoredStages(result, records))


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


def grid_writer(project: StoreProject, name: str, *, version: str) -> str | None:
    """El tipo de la operación (``res.volume`` o ``res.difference``) que escribió la rejilla de
    diferencias viva de la cubicación ``name`` en la versión ``version`` (uid o código), o
    ``None`` si no hay ninguna: dos tipos no comparten una rejilla (una «Diferencia entre
    superficies…» con el nombre de una cubicación que la escribió). ``VersionError`` si la
    versión no existe."""
    dataset = declared.dataset_name(declared.DIFFERENCE_GRID, name)
    with project.read() as conn:
        found = versions_read.version(conn, version)
        if found is None:
            raise VersionError("core.version_unknown", field="versión", value=version,
                               version=version)
        record = dataset_registry.get(conn, dataset, version_uid=found.uid)
        if record is None or record.name != dataset:
            return None
        row = conn.execute("SELECT op_type FROM gb_operation WHERE uid = ?",
                           (record.operation_uid,)).fetchone()
    return None if row is None else str(row[0])


# --- Las cubicaciones de una versión (T24; RF-011-18, RF-011-19, RF-011-23) --------------------


@dataclass(frozen=True, slots=True)
class Cubication:
    """Una cubicación de una versión (su tabla de volúmenes ``res_vol_`` viva): su nombre (el de
    los ajustes de la ``res.volume`` que la escribió), el registro de esa tabla, esa operación y
    cuándo terminó, si reparte por unidades y el registro de su tabla de toneladas
    (``res_ton_``) viva, o ``None``. Lo que enseña el panel de la cubicación (T25; RF-011-23,
    RF-009-20, RF-008-31): la revisión de esa operación («V01.r1»; vacía en una cubicación sin
    revisión), su estado (``RevisionState``: «open», lo «en curso»; «frozen»; «closed», la
    cerrada al superarse o descartarse su versión), el número de la última revisión congelada
    de la versión («r1»; vacío si no tiene ninguna) y si su tabla de volúmenes o la de sus
    toneladas está obsoleta (la caché ``gb_stale`` de la 008). Con ``stages``, una cubicación
    por momentos (T38; F-3): ``record`` es su tabla ``res_stg_`` y ``operation_uid``, su
    ``res.stages``; sin unidades ni toneladas."""

    name: str
    record: DatasetRecord
    operation_uid: str
    finished_at: str
    units: bool
    tonnage: DatasetRecord | None
    revision: str = ""
    revision_state: str = ""
    current: str = ""
    stale: bool = False
    stages: bool = False


def _version_of(conn: sqlite3.Connection, version: str) -> Any:
    found = versions_read.version(conn, version)
    if found is None:
        raise VersionError("core.version_unknown", field="versión", value=version,
                           version=version)
    return found


def _live(conn: sqlite3.Connection, family: str, name: str,
          version_uid: str) -> DatasetRecord | None:
    """El dato vivo de la familia ``family`` de la cubicación ``name`` en la versión
    ``version_uid``, o ``None``."""
    dataset = declared.dataset_name(family, name)
    record = dataset_registry.get(conn, dataset, version_uid=version_uid)
    return record if record is not None and record.name == dataset else None


_STALE_CHUNK = 500
"""Cuántos datos se preguntan a la caché de la obsolescencia en cada consulta."""


def _stale_datasets(conn: sqlite3.Connection, uids: Sequence[str]) -> frozenset[str]:
    """Los de ``uids`` que la caché de la obsolescencia de la 008 (``gb_stale``) da por
    obsoletos (RF-008-24)."""
    found: set[str] = set()
    for start in range(0, len(uids), _STALE_CHUNK):
        part = list(uids[start:start + _STALE_CHUNK])
        found.update(str(uid) for (uid,) in conn.execute(
            "SELECT DISTINCT item_uid FROM gb_stale WHERE item_kind = 'dataset' AND item_uid IN "
            f"({', '.join('?' for _ in part)})", part))
    return frozenset(found)


def cubications(project: StoreProject, *, version: str,
                stages: bool = False) -> tuple[Cubication, ...]:
    """Las cubicaciones de la versión ``version`` (uid o código), por nombre: las que tienen su
    tabla de volúmenes viva (no una diferencia entre superficies), lo que ofrecen «Por momentos
    de extracción…» como momentos y directa y «Ratios…» (T24), con su revisión y si están
    obsoletas (T25). Con ``stages``, también las cubicaciones por momentos (su tabla
    ``res_stg_`` viva; ``Cubication.stages``), lo que lista el panel de la cubicación (T38;
    RF-011-19, RF-011-23); una con el nombre de una cubicación no se lista (el panel las elige
    por su nombre: la de volúmenes manda). ``VersionError`` si la versión no existe."""
    live = tuple(str(status) for status in LIVE_STATUSES)
    volumes_prefix = declared.FAMILIES_BY_CODE[declared.VOLUMES].prefix
    stages_prefix = declared.FAMILIES_BY_CODE[declared.STAGE_TABLE].prefix
    with project.read() as conn:
        found = _version_of(conn, version)
        rows = conn.execute(
            f"SELECT {', '.join(RECORD_COLUMNS)} FROM gb_dataset WHERE version_uid = ? AND "
            f"module = ? AND status IN ({', '.join('?' for _ in live)})",
            (found.uid, declared.MODULE, *live)).fetchall()
        records = {record.name: record for record in map(DatasetRecord.from_row, rows)}
        frozen = versions_read.last_frozen(conn, found.uid)
        current = "" if frozen is None else f"r{frozen.number}"
        listed: list[Cubication] = []
        staged: list[Cubication] = []
        for record in records.values():
            if record.name.startswith(volumes_prefix):
                op_type, target = declared.VOLUME, listed
            elif stages and record.name.startswith(stages_prefix):
                op_type, target = declared.STAGES, staged
            else:
                continue
            row = conn.execute("SELECT settings, finished_at, revision_uid FROM gb_operation "
                               "WHERE uid = ? AND op_type = ?",
                               (record.operation_uid, op_type)).fetchone()
            if row is None:  # inalcanzable: una tabla de res es de su operación
                continue
            settings = json.loads(row[0])
            name = str(settings.get("name") or record.name)
            revision = versions_read.revision(conn, str(row[2])) if row[2] else None
            target.append(Cubication(
                name, record, record.operation_uid, str(row[1] or ""),
                op_type == declared.VOLUME and bool(settings.get("units")),
                (records.get(declared.dataset_name(declared.TONNES, name))
                 if op_type == declared.VOLUME else None),
                revision="" if revision is None else revision.label(found.code),
                revision_state="" if revision is None else str(revision.state),
                current=current, stages=op_type == declared.STAGES))
        names = {item.name for item in listed}
        listed += [item for item in staged if item.name not in names]
        stale = _stale_datasets(conn, [record.uid for item in listed for record in (
            item.record, item.tonnage) if record is not None])
    listed = [replace(item, stale=item.record.uid in stale or (
        item.tonnage is not None and item.tonnage.uid in stale)) for item in listed]
    return tuple(sorted(listed, key=lambda item: (item.name.casefold(), item.name)))


def cubication_ratios(project: StoreProject, name: str, *, version: str) -> tuple[Row, ...]:
    """Las filas del filtro de relaciones (``reserves.table.ratio_rows``; RF-011-18, D-35) de la
    tabla de toneladas viva de la cubicación ``name`` de la versión ``version`` (uid o código):
    vacías si no tiene (sin unidades, o sus toneladas no llegaron a guardarse).
    ``res.cubication_unknown`` si la versión no tiene esa cubicación; ``VersionError`` si la
    versión no existe."""
    with project.read() as conn:
        found = _version_of(conn, version)
        volume, tonnage = (_live(conn, family, name, found.uid)
                           for family in (declared.VOLUMES, declared.TONNES))
        if volume is None:
            raise ResError("res.cubication_unknown", obj=name, field="cubicación", value=name,
                           version=found.code)
        if tonnage is None:
            return ()
        return ratio_rows(read_rows(conn, tonnage.locator))


# --- Recalcular (A12) -------------------------------------------------------------------------

RECOMPUTED: tuple[str, ...] = (declared.VOLUME, declared.TONNAGE, declared.DIFFERENCE,
                               declared.STAGES)
"""Los tipos que repite :func:`recompute_run` (los de versión)."""


def _current_column(project: StoreProject) -> MaterialColumn:
    """La columna de materiales vigente del proyecto (la que leerá la operación nueva);
    ``res.materials_missing`` si no hay ninguna."""
    with project.read() as conn:
        record = dataset_registry.get(conn, declared.MATERIALS)
        column = None if record is None else read_column(conn, record.locator)
    if column is None:
        raise ResError("res.materials_missing", obj="Columna de materiales", field="units",
                       value=0)
    return column


def _consumed(request: RecomputeRequest, role: str) -> str:
    """Lo que consumió la operación de ``request`` con el papel ``role`` (su uid vigente)."""
    found = [use.item for use in request.inputs if use.role == role]
    if len(found) != 1:
        raise ValueError(f"la operación «{request.op_type}» ({request.operation_uid}) no "
                         f"consumió un dato «{role}»: no se puede repetir")
    return found[0]


def recompute_run(request: RecomputeRequest, *, budget_s: float = STEP_BUDGET_S,
                  band_rows: int = BAND_ROWS) -> tuple[OperationHandle, Iterator[Progress]]:
    """Repite la operación de ``res`` de ``request`` (``RecomputeRequest`` de «Recalcular lo
    obsoleto», RF-008-26; RF-011-20, RF-011-21; plan A12, D-19): empieza la operación nueva,
    que sustituye a la anterior en la revisión abierta de **su** versión, con sus mismos
    ajustes y con lo que lee hoy —la columna de materiales vigente y, de ella, sus entradas
    (las bases y los espesores de cada unidad) y sus parámetros, resueltos de nuevo al empezar:
    un K cambiado solo en V01 se lee de V01; la capa de su ámbito y la de sus dominios, las
    vigentes que consumió (:func:`load_scope`, :func:`load_domain_layer`; T32)— y devuelve su
    ``OperationHandle`` «en curso» y sus pasos (:func:`volume_run`, :func:`tonnage_run` o
    :func:`stages_run`, que relee las tablas vigentes de sus momentos), que avanza quien la
    llama (en Blender, la cola de ``res``; la operación sigue «en curso» hasta el último).

    Al llamar, sin empezar nada: ``ValueError`` si el tipo no es de :data:`RECOMPUTED` o sus
    ajustes no son los de su tipo; ``res.materials_missing`` si reparte por unidades y no hay
    columna; los rechazos de leer sus capas; los rechazos de ``begin_operation``."""
    if not isinstance(request, RecomputeRequest):
        raise TypeError(f"se recalcula una RecomputeRequest, no {request!r}")
    if request.op_type not in RECOMPUTED:
        raise ValueError(f"recompute_run repite {', '.join(RECOMPUTED)}, no "
                         f"«{request.op_type}»")
    project: StoreProject = request.project  # type: ignore[assignment]
    settings = request.settings
    volume: VolumeRequest | None = None
    if request.op_type == declared.STAGES:
        _name, moments, direct = _stages_names(settings)
        inputs = declared.stages_inputs(moments, direct)
        params = declared.stages_params()
    elif request.op_type == declared.TONNAGE:
        name = settings.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("los ajustes de res.tonnage llevan el nombre de su cubicación")
        inputs = declared.tonnage_inputs(name)
        params = declared.tonnage_params(_current_column(project))
    else:
        column = _current_column(project) if settings.get("units") else None
        scope = domains = None
        if settings.get("scope") is not None:
            scope = load_scope(project, _consumed(request, declared.SCOPE_ROLE))
        field = settings.get("domains_field")
        if field is not None:
            domains = load_domain_layer(project, _consumed(request, declared.DOMAINS_ROLE),
                                        field)
        volume = declared.volume_request(settings, column=column, scope=scope,
                                         domains=domains)
        frozen = next((use.frozen for use in request.inputs if use.frozen is not None), None)
        inputs = declared.volume_inputs(volume, scope=settings.get("scope"), frozen=frozen)
        params = declared.volume_params(volume)
    handle = begin_operation(project, request.op_type, executor=Executor.BLENDER,
                             settings=dict(settings), inputs=inputs, params=params,
                             group_uid=request.group_uid, supersedes=request.operation_uid,
                             version=request.version)
    try:
        if request.op_type == declared.STAGES:
            return handle, stages_run(project, handle)
        if volume is None:
            return handle, tonnage_run(project, handle, budget_s=budget_s)
        return handle, volume_run(project, handle, volume, budget_s=budget_s,
                                  band_rows=band_rows)
    except BaseException as error:
        handle.fail(failure_reason(error))
        raise
