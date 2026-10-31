# SPDX-License-Identifier: GPL-3.0-or-later
"""La compilación de las restricciones en el proyecto (spec 012; RF-012-06, RF-012-11,
RF-012-16, RF-012-28; plan 012 §5.2.3, A5, A11, D-24).

- :func:`gather` lee lo que se compila en una versión (sin escribir): las restricciones, sus
  parámetros resueltos versión → proyecto, los sectores, las búsquedas, la rejilla del proyecto,
  los datos registrados que se consumen y **lo de la compilación anterior vigente** de la versión
  (A5): de cada restricción cuya huella cambió (``gis.masks.compile.changed_codes``), su polígono
  (``gis_mskg_``) y su zona (``gis_mskz_``) de entonces.
- :func:`begin_compile` rechaza antes de registrar nada lo que no se puede compilar (sin versión
  activa o en una no editable, RF-012-16; restricciones incompletas o no válidas, RF-012-04; sin
  límite legal, RF-012-15) y empieza ``gis.compile_constraints`` «en curso» (sustituyendo a la
  anterior) con sus entradas, sus parámetros y sus ajustes. :func:`begin_compile_steps` (T23) es
  lo mismo en varios pasos (la lectura, la comprobación de cada restricción y de cada polígono, la
  operación): la comprobación en frío de 500 restricciones tarda 0,45 s de una vez, y ninguna
  llamada del hilo de Blender pasa de 0,2 s mientras compila (RNF-012-06).
- :func:`listed_constraints` (T23; RF-012-04, RF-012-19) lista las restricciones con su estado en
  una versión (incompleta, no válida, activa o inactiva) y lo que les falta.
- :func:`compile_run` da sus pasos (``gis.masks.compile.compile_steps``) y guarda el resultado
  con :class:`MaskWriter` (A11): la rejilla de clases por teselas en su temporal con su hash, los
  hashes de las tablas fuera de la transacción (por tramos de filas, T35: ningún paso pasa de
  0,05 s), ``os.replace`` a ``rasters/`` y **una** transacción con las cuatro tablas, las cifras
  y ``complete`` (lo único que no se trocea, R4). Si se cierra o falla, nada (ni cifras, ni
  tablas, ni rejilla, ni temporal) y la operación «cancelada» o «fallida».
- :func:`declared_limits` (T22; RF-012-05, RF-012-15) lee los límites declarados que están activos
  en una versión (o en el proyecto) y da su informe (áreas, franja y lo que queda fuera de la
  rejilla) o los problemas que lo impiden, sin escribir nada y por pasos.
- :func:`recompute_run` (T21; RF-008-26, D-19) repite una compilación obsoleta: la operación
  nueva sustituye a la anterior en la revisión abierta de su versión, con lo que se lee hoy; la
  llama «Recalcular lo obsoleto» desde ``bl`` y avanza sus pasos la cola de las máscaras.
- :func:`reproduce_compile` (:data:`REPRODUCE`) reproduce una compilación congelada con sus
  entradas y sus parámetros congelados y sus ajustes, sin el proyecto.

Python puro (nivel 2).
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Generator, Iterator, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType, TracebackType
from typing import Any

import numpy as np

from ...core.constraints import store as cstore
from ...core.constraints.checks import Incomplete
from ...core.constraints.messages import ConstraintError
from ...core.constraints.model import (
    Constraint,
    ConstraintParam,
    ConstraintType,
    GeometryKind,
    Sector,
    is_code,
)
from ...core.constraints.params import param_key
from ...core.constraints.provenance import SECTOR_ROLE
from ...core.content import builtin as core_builtin
from ...core.content.encoder import NORMALIZER, ContentDigest
from ...core.datasets import registry as dataset_registry
from ...core.datasets.model import DATASET_DECLARATIONS, LIVE_STATUSES, DatasetSpec, Store
from ...core.errors import GeoblenderError
from ...core.georef import CrsRef
from ...core.gpkg.base import (
    ColumnDef,
    create_attribute_table,
    create_base,
    create_feature_table,
)
from ...core.gpkg.connection import GpkgConnection
from ...core.gpkg.wkb import decode_geometry, encode_geometry
from ...core.params import PROJECT_SCOPE, VERSION_SCOPE
from ...core.params.store import ParameterStore, ResolvedParam
from ...core.paths import check_path_length
from ...core.project.model import Progress
from ...core.provenance.figures import FigureSpec
from ...core.provenance.operations import (
    CANCEL_REASON_PREFIX,
    CANCELLATIONS,
    NOT_COMPLETED_REASON,
    OperationHandle,
    OperationStatus,
    begin_operation,
    cancel_reason,
    failure_reason,
)
from ...core.provenance.recompute import RecomputeRequest
from ...core.versions import read as versions_read
from ...core.versions import store as versions_store
from ...core.versions.model import VersionError
from ...core.versions.reproduce import ReproducedOutput, ReproducedResult, ReproduceRequest
from ..geotiff.writer import target_locked, write_failed
from ..grid import Grid, project_grid
from ..messages import GisError
from ..polygons import drain
from ..store import StoreProject, backup_path, insert_rows, project_references, temporary_path
from . import provenance as declared
from .combine import (
    LEGAL_COMMAND,
    IncompleteConstraints,
    Outside,
    check_steps,
    limit_outside,
)
from .compile import (
    STEP_BUDGET_S,
    CompileRequest,
    CompileResult,
    PreviousMasks,
    PreviousShape,
    changed_codes,
    compile_steps,
    fingerprint,
    fingerprint_kind,
    is_active,
    pace_units,
    planned_steps,
)
from .overlay import LimitsReport, limits_report_steps
from .zones import Runs

__all__ = [
    "CANCELLED_REASON",
    "REPRODUCE",
    "CompileInputs",
    "DeclaredLimits",
    "MaskWriter",
    "STATES",
    "ListedConstraint",
    "StoredMasks",
    "available_tables",
    "begin_compile",
    "begin_compile_steps",
    "compile_run",
    "current_pending",
    "declared_limits",
    "declared_limits_steps",
    "gather",
    "listed_constraints",
    "listed_constraints_steps",
    "live_searches",
    "pending_sectors",
    "perimeter_of",
    "perimeter_sector",
    "read_report",
    "read_shapes",
    "read_zone_runs",
    "recompute_run",
    "reproduce_compile",
    "search_sectors",
    "sector_states_now",
    "zone_runs_steps",
]

CANCELLED_REASON = CANCEL_REASON_PREFIX + "la persona la paró antes de terminar (Esc)"
_OBJ = "Máscaras de las restricciones"
_FIELD = "ubicación"
CLASSES_FILE = "clases.tif"
"""La rejilla de clases reproducida, en la carpeta de trabajo."""
_COMPILE_PHASE = "compile"
_COMPILE_TEXT = "Compilando las restricciones…"
_SAVE_PHASE = "save"
_SAVE_TEXT = "Guardando las máscaras…"

# --- Las tablas (D-24) -------------------------------------------------------------------------

_ZONE_COLUMNS = (ColumnDef("zone", "TEXT", not_null=True), ColumnDef("row", "INTEGER", True),
                 ColumnDef("col0", "INTEGER", True), ColumnDef("col1", "INTEGER", True))
_REPORT_COLUMNS = (ColumnDef("constraint_code", "TEXT", True),
                   ColumnDef("quantity", "TEXT", True), ColumnDef("value", "DOUBLE", False),
                   ColumnDef("unit_code", "TEXT", False), ColumnDef("note", "TEXT", False))
_PART_COLUMNS = (ColumnDef("area_m2", "DOUBLE", True), ColumnDef("area_ha", "DOUBLE", True))
_SHAPE_COLUMNS = (ColumnDef("code", "TEXT", True), ColumnDef("name", "TEXT", True),
                  ColumnDef("ctype", "TEXT", True))
_GEOMETRY = {declared.PARTS: "POINT", declared.SHAPES: "MULTIPOLYGON"}
_COLUMNS = {declared.ZONES: _ZONE_COLUMNS, declared.REPORT: _REPORT_COLUMNS,
            declared.PARTS: _PART_COLUMNS, declared.SHAPES: _SHAPE_COLUMNS}


def _names(family: str) -> tuple[str, ...]:
    found = tuple(column.name for column in _COLUMNS[family])
    return ("geom", *found) if family in _GEOMETRY else found


def _create(conn: sqlite3.Connection, family: str, table: str, srs_id: int,
            identifier: str, description: str = "") -> None:
    geometry = _GEOMETRY.get(family)
    if geometry is None:
        create_attribute_table(conn, table, _COLUMNS[family], identifier, description)
    else:
        create_feature_table(conn, table, geometry, srs_id, False, _COLUMNS[family],
                             identifier, description)


def _rows(family: str, result: CompileResult, constraints: Sequence[Constraint],
          srs_id: int) -> list[tuple[Any, ...]]:
    if family == declared.ZONES:
        return list(result.zone_rows())
    if family == declared.REPORT:
        return list(result.report_rows())
    if family == declared.PARTS:
        return [(encode_geometry("POINT", np.array([x, y]), srs_id, False), area, hectares)
                for x, y, area, hectares in result.part_rows()]
    found = []
    for item in constraints:
        zone = result.prepared.zones.get(item.code)
        if zone is None or item.kind is not GeometryKind.POLYGON:
            continue
        found.append((encode_geometry("MULTIPOLYGON", [list(part) for part in item.parts],
                                      srs_id, False), item.code, zone.name, zone.ctype.value))
    return found


_DIGEST_ROWS_PER_UNIT = 4000
"""Las filas que se insertan en cada unidad de :func:`_digest_steps` (un múltiplo de las 500 de
cada sentencia de ``insert_rows``)."""


def _digest_steps(family: str, rows: Sequence[tuple[Any, ...]], crs: CrsRef
                  ) -> Generator[None, None, ContentDigest]:
    """El hash (``core.gpkg_layer@1``) de la tabla ``family`` con ``rows``, en un GeoPackage en
    memoria con la misma estructura (R4: fuera de la transacción), por pasos: una unidad por
    cada trozo de filas que se inserta y por cada trozo que se lee y se hashea (T35)."""
    conn = sqlite3.connect(":memory:")
    try:
        create_base(conn, crs)
        _create(conn, family, "digest", crs.epsg, "digest")
        names = _names(family)
        for first in range(0, len(rows), _DIGEST_ROWS_PER_UNIT):
            insert_rows(conn, "digest", names, rows[first:first + _DIGEST_ROWS_PER_UNIT])
            yield
        kind = declared.FAMILIES_BY_CODE[family].kind
        request = core_builtin.GPKG_LAYER.request(kind, DATASET_DECLARATIONS,
                                                  {"main": Path("digest")}, {"layer": "digest"},
                                                  normalizer=NORMALIZER)
        steps = core_builtin.layer_steps(conn, request)
        try:
            for _done in steps:
                yield
        finally:
            steps.close()
        return request.hasher.digest()
    finally:
        conn.close()


def read_zone_runs(conn: sqlite3.Connection, table: str) -> dict[str, Runs]:
    """Las zonas de una tabla ``gis_mskz_`` (zona → tramos)."""
    found: dict[str, list[tuple[int, int, int]]] = {}
    for zone, row, col0, col1 in conn.execute(
            f'SELECT zone, "row", col0, col1 FROM "{table}" ORDER BY fid'):
        found.setdefault(str(zone), []).append((int(row), int(col0), int(col1)))
    result = {}
    for zone, items in found.items():
        values = np.asarray(items, dtype=np.int64).reshape(-1, 3)
        result[zone] = Runs(values[:, 0], values[:, 1], values[:, 2])
    return result


_ZONE_ROWS_PER_UNIT = 10_000
"""Las filas de ``gis_mskz_`` que lee cada unidad de :func:`zone_runs_steps`."""
_ZONES_PER_UNIT = 40
"""Las zonas cuyos tramos se normalizan en cada unidad de :func:`zone_runs_steps`."""


def zone_runs_steps(project: StoreProject, table: str) -> Generator[None, None, dict[str, Runs]]:
    """:func:`read_zone_runs` por pasos (T36): cada unidad abre su lectura, lee
    :data:`_ZONE_ROWS_PER_UNIT` filas por su clave y la cierra (sin sostener una lectura entre
    unidades), y después normaliza los tramos de :data:`_ZONES_PER_UNIT` zonas por unidad.
    Devuelve las zonas en el mismo orden que :func:`read_zone_runs`."""
    found: dict[str, list[tuple[int, int, int]]] = {}
    last = 0
    while True:
        with project.read() as conn:
            rows = conn.execute(
                f'SELECT fid, zone, "row", col0, col1 FROM "{table}" WHERE fid > ? '
                "ORDER BY fid LIMIT ?", (last, _ZONE_ROWS_PER_UNIT)).fetchall()
        for _fid, zone, row, col0, col1 in rows:
            found.setdefault(str(zone), []).append((int(row), int(col0), int(col1)))
        yield None
        if len(rows) < _ZONE_ROWS_PER_UNIT:
            break
        last = int(rows[-1][0])
    result: dict[str, Runs] = {}
    for count, (zone, items) in enumerate(found.items(), start=1):
        values = np.asarray(items, dtype=np.int64).reshape(-1, 3)
        result[zone] = Runs(values[:, 0], values[:, 1], values[:, 2])
        if count % _ZONES_PER_UNIT == 0:
            yield None
    return result


def read_report(conn: sqlite3.Connection, table: str
                ) -> list[tuple[str, str, float | None, str | None, str | None]]:
    """Las filas de una tabla ``gis_mskr_``, en su orden."""
    return [(str(a), str(b), c, d, e) for a, b, c, d, e in conn.execute(
        f'SELECT constraint_code, quantity, value, unit_code, note FROM "{table}" ORDER BY fid')]


def read_shapes(conn: sqlite3.Connection, table: str
                ) -> dict[str, tuple[ConstraintType, tuple[tuple[np.ndarray, ...], ...]]]:
    """Los polígonos compilados de una tabla ``gis_mskg_`` (código → (tipo, partes))."""
    found = {}
    for code, ctype, blob in conn.execute(f'SELECT code, ctype, geom FROM "{table}"'):
        coords = decode_geometry(bytes(blob), external=True).coords
        parts = tuple(tuple(np.asarray(ring, dtype=np.float64)[:, :2] for ring in polygon)
                      for polygon in coords)
        found[str(code)] = (ConstraintType(ctype), parts)
    return found


# --- Leer lo que se compila --------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class CompileInputs:
    """Lo que lee :func:`gather`: la versión (su uid), lo de la petición, los nombres de los
    datos registrados que se consumen, la operación a la que sustituye y los sectores sin
    búsqueda vigente."""

    version_uid: str
    request: CompileRequest
    available: frozenset[str]
    supersedes: str | None
    pending_sectors: tuple[str, ...]


def pending_sectors(sectors: Sequence[Sector], searches: Sequence[Any],
                    perimeter: Sequence[Constraint]) -> tuple[str, ...]:
    """Los sectores sin una búsqueda de su misma geometría entre ``searches`` (``""``: sin
    sectores, el perímetro como único sector; D-26). Que la búsqueda no esté obsoleta lo filtra
    antes :func:`live_searches` (A12)."""
    done = {(record.sector_code, record.sector_sha256) for record in searches}
    if not sectors:
        rings = tuple(ring for item in perimeter for part in item.parts for ring in part)
        if not rings:
            return ()
        sectors = (Sector("", "", "", rings),)
    return tuple(sector.code for sector in sectors
                 if (sector.code, cstore.sector_sha256(sector)) not in done)


def live_searches(conn: sqlite3.Connection, searches: Sequence[Any]) -> tuple[Any, ...]:
    """Las búsquedas de ``searches`` cuya operación no está obsoleta (A12: la caché
    ``gb_stale`` de la 008), salvo por lo que viene **solo del sector**: una causa cuyo sujeto
    es el dato del sector (su entrada ``sector``: ``core_sector`` o la capa del perímetro) o algo
    de lo que sale (la capa de la que se declararon los sectores…) no cuenta, porque el sector lo
    decide su huella (``sector_sha256``, RF-012-09): declarar de nuevo los sectores o editar otra
    restricción no deja pendiente la búsqueda de un sector que no cambió. Una causa en una capa
    consultada (``layer_n``) o en lo que sale de ella siempre cuenta."""
    uids = sorted({record.operation_uid for record in searches})
    stale: set[str] = set()
    for start in range(0, len(uids), 500):
        chunk = uids[start:start + 500]
        marks = ", ".join("?" for _ in chunk)
        stale.update(str(row[0]) for row in conn.execute(
            "WITH RECURSIVE up(op, item, side) AS ("
            " SELECT operation_uid, item_uid, role = ? FROM gb_operation_io WHERE"
            f"  direction = 'in' AND operation_uid IN ({marks})"
            " UNION"
            " SELECT up.op, i.item_uid, up.side FROM up JOIN gb_operation_io AS o ON"
            "  o.direction = 'out' AND o.item_uid = up.item JOIN gb_operation_io AS i ON"
            "  i.operation_uid = o.operation_uid AND i.direction = 'in')"
            " SELECT DISTINCT s.item_uid FROM gb_stale AS s WHERE s.item_kind = 'operation' AND"
            f" s.item_uid IN ({marks}) AND (NOT EXISTS (SELECT 1 FROM up WHERE"
            "  up.op = s.item_uid AND up.item = s.subject_uid AND up.side) OR EXISTS (SELECT 1"
            "  FROM up WHERE up.op = s.item_uid AND up.item = s.subject_uid AND NOT up.side))",
            (SECTOR_ROLE, *chunk, *chunk)))
    return tuple(record for record in searches if record.operation_uid not in stale)


def perimeter_of(constraints: Sequence[Constraint], resolved: Mapping[str, object]
                 ) -> list[Constraint]:
    """Los perímetros de actuación activos o, sin ninguno, los límites legales activos (el
    sector único cuando no hay capa de sectores; D-26)."""
    found = [item for item in constraints
             if item.ctype is ConstraintType.ACTION_PERIMETER and is_active(item, resolved)]
    if not found:
        found = [item for item in constraints
                 if item.ctype is ConstraintType.LEGAL_LIMIT and is_active(item, resolved)]
    return found


def current_pending(conn: sqlite3.Connection, project: StoreProject | None, version_uid: str
                    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Los sectores sin búsqueda vigente ahora en la versión ``version_uid`` (A12, D-26),
    calculados al vuelo: (códigos, nombres). El perímetro como sector único se nombra
    «el perímetro de actuación». ``project`` puede ser ``None`` si solo se tiene la conexión
    (la instantánea de congelar, ``reserves.compliance_store.freeze_findings``): resolver un
    parámetro con una conexión no usa el proyecto."""
    constraints = cstore.read_constraints(conn)
    resolved = _resolved(conn, project, constraints, version_uid)
    sectors = cstore.read_sectors(conn)
    searches = live_searches(conn, cstore.read_searches(conn))
    codes = pending_sectors(sectors, searches, perimeter_of(constraints, resolved))
    names = {sector.code: sector.name for sector in sectors}
    return codes, tuple(names.get(code) or PERIMETER_SECTOR_NAME for code in codes)


PERIMETER_SECTOR_NAME = "el perímetro de actuación"
"""Cómo se nombra el sector único cuando no hay capa de sectores (D-26)."""


def perimeter_sector(constraints: Sequence[Constraint], resolved: Mapping[str, object]
                     ) -> tuple[Sector, str] | None:
    """El perímetro como único sector (sin capa de sectores, D-26): el sector ``""`` con los
    anillos de :func:`perimeter_of` y el dato del que sale (su capa); ``None`` sin perímetro
    ni límite legal activos."""
    found = perimeter_of(constraints, resolved)
    rings = tuple(ring for item in found for part in item.parts for ring in part)
    if not rings:
        return None
    return Sector("", "", PERIMETER_SECTOR_NAME, rings), cstore.layer_of(found[0].kind)


def search_sectors(conn: sqlite3.Connection, project: StoreProject, version_uid: str | None
                   ) -> tuple[tuple[Sector, str], ...]:
    """Los sectores de búsqueda ahora, con el dato del que sale cada uno: los declarados
    (``core_sector``) o, sin ninguno, el perímetro (:func:`perimeter_sector`, resuelto en la
    versión ``version_uid`` o, sin ella, en el proyecto)."""
    sectors = cstore.read_sectors(conn)
    if sectors:
        return tuple((sector, cstore.SECTOR_TABLE) for sector in sectors)
    constraints = cstore.read_constraints(conn)
    found = perimeter_sector(constraints, _resolved(conn, project, constraints, version_uid))
    return () if found is None else (found,)


def sector_states_now(conn: sqlite3.Connection, project: StoreProject,
                      version_uid: str | None) -> tuple[cstore.SectorState, ...]:
    """El estado de cada sector de :func:`search_sectors`, calculado al vuelo con las búsquedas
    vigentes (:func:`live_searches`, A12)."""
    sectors = tuple(sector for sector, _ in search_sectors(conn, project, version_uid))
    return cstore.sector_states(sectors, live_searches(conn, cstore.read_searches(conn)))


def _resolved(conn: sqlite3.Connection, project: StoreProject | None,
              constraints: Sequence[Constraint], version_uid: str | None) -> dict[str, object]:
    """Los parámetros de las restricciones resueltos versión → proyecto (sin versión, los del
    proyecto). ``ParameterStore.resolve`` lee la conexión que se le da y no usa el proyecto:
    ``None`` vale si solo se tiene la conexión."""
    store = ParameterStore(project)  # type: ignore[arg-type]
    chain = (PROJECT_SCOPE,) if version_uid is None else (VERSION_SCOPE, PROJECT_SCOPE)
    keys = [param_key(item.code, param) for item in constraints if is_code(item.code)
            for param in ConstraintParam]
    if not keys:
        return {}
    # Todos de una vez (T36): con 500 restricciones, 2.000 ``resolve`` eran 0,2 s; el mismo
    # resultado, sin las claves que ningún ámbito tiene.
    return dict(store.resolve_many(conn, keys, chain, version=version_uid))


def _live_operation(conn: sqlite3.Connection, record: Any) -> str | None:
    if record is None:
        return None
    row = conn.execute("SELECT status, superseded_by FROM gb_operation WHERE uid = ?",
                       (record.operation_uid,)).fetchone()
    if row is None or row[0] != OperationStatus.DONE or row[1] is not None:
        return None
    return str(record.operation_uid)


def _previous(conn: sqlite3.Connection, version_uid: str, request: CompileRequest
              ) -> tuple[PreviousMasks | None, str | None]:
    records = {family: dataset_registry.get(conn, declared.dataset_name(family),
                                            version_uid=version_uid)
               for family in (declared.ZONES, declared.REPORT, declared.SHAPES)}
    if any(record is None for record in records.values()):
        return None, None
    operation = _live_operation(conn, records[declared.REPORT])
    if operation is None:
        return None, None
    before = {row[0]: str(row[4]) for row in read_report(conn, records[declared.REPORT].locator)
              if row[1] == "fingerprint" and row[4] is not None}
    now = {item.code: fingerprint(item, request.resolved) for item in request.constraints
           if is_code(item.code) and item.ctype is not None
           and is_active(item, request.resolved)}
    codes = changed_codes(now, before)
    zones = read_zone_runs(conn, records[declared.ZONES].locator) if codes else {}
    shapes = read_shapes(conn, records[declared.SHAPES].locator) if codes else {}
    ctypes = {row[0]: row[4] for row in read_report(conn, records[declared.REPORT].locator)
              if row[1] == "zone_area"}
    changed: dict[str, PreviousShape | None] = {}
    for code in codes:
        if code not in before:
            changed[code] = None
            continue
        ctype, parts = shapes.get(code, (ConstraintType(ctypes[code]), ()))
        changed[code] = PreviousShape(ctype, fingerprint_kind(before[code]), parts,
                                      zones.get(code, Runs.empty()))
    return PreviousMasks(operation, MappingProxyType(changed)), operation


def _available(conn: sqlite3.Connection) -> frozenset[str]:
    """Las tablas de las restricciones, los sectores y las búsquedas que son datos registrados."""
    return frozenset(table for table in cstore.TABLES
                     if dataset_registry.get(conn, table) is not None)


def available_tables(project: StoreProject) -> frozenset[str]:
    """Los nombres de los datos que consumiría una compilación (:func:`_available`), sin leer
    las restricciones: lo que la puerta de la 008 comprueba antes de empezar (T23)."""
    with project.read() as conn:
        return _available(conn)


def gather(project: StoreProject, *, version: str) -> CompileInputs:
    """Lo que se compila en la versión ``version`` (uid o código), sin escribir nada
    (véase el módulo). ``VersionError`` si no existe o no es editable."""
    record = project.record
    if record is None:
        raise ValueError(f"el proyecto «{project.name}» se abrió solo con su cabecera")
    with project.read() as conn:
        found = versions_store.require_editable(conn, version)
        constraints = cstore.read_constraints(conn)
        resolved = _resolved(conn, project, constraints, found.uid)
        sectors = cstore.read_sectors(conn)
        searches = cstore.read_searches(conn)
        live = live_searches(conn, searches)
        available = _available(conn)
        grid = project_grid(record.window, float(record.grid_step_m))
        request = CompileRequest(constraints, MappingProxyType(resolved), sectors, searches,
                                 grid)
        previous, supersedes = _previous(conn, found.uid, request)
    perimeter = perimeter_of(constraints, resolved)
    request = CompileRequest(constraints, request.resolved, sectors, searches, grid, previous)
    return CompileInputs(found.uid, request, available, supersedes,
                         pending_sectors(sectors, live, perimeter))


def begin_compile_steps(project: StoreProject, *, version: str | None,
                        executor: str = "blender") -> Generator[None, None, OperationHandle]:
    """Empieza ``gis.compile_constraints`` «en curso» en la versión ``version`` en varios pasos
    (T23; RNF-012-06): uno tras leer lo que se compila (:func:`gather`), uno por restricción y
    por polígono de la comprobación (``combine.check_steps``) y uno antes de registrar la
    operación; devuelve su ``OperationHandle`` (``StopIteration.value``). Lo rechaza como
    :func:`begin_compile`, al avanzar (no al llamar) y sin registrar nada: ``VersionError``
    (``core.version_required``, ``core.version_unknown``, ``core.version_not_editable``),
    ``IncompleteConstraints`` (RF-012-04) y ``ConstraintError`` sin límite legal activo
    (RF-012-15). Cerrarlo antes del último paso no deja nada."""
    if version is None or not str(version).strip():
        raise VersionError("core.version_required", field="versión activa", value=version,
                           op_type=declared.COMPILE)
    inputs = gather(project, version=str(version))
    yield
    request = inputs.request
    problems = yield from check_steps(request.constraints, request.resolved)
    if problems:
        raise IncompleteConstraints(problems)
    if not any(item.ctype is ConstraintType.LEGAL_LIMIT and is_active(item, request.resolved)
               for item in request.constraints):
        raise ConstraintError("core.constraint_no_legal_limit", command=LEGAL_COMMAND)
    assert request.grid is not None
    settings = declared.compile_settings(
        request.grid, previous=None if request.previous is None else request.previous.settings(),
        pending_sectors=inputs.pending_sectors)
    yield
    return begin_operation(project, declared.COMPILE, settings=settings,
                           inputs=declared.compile_inputs(inputs.available),
                           params=declared.compile_params(request.constraints,
                                                          request.resolved),
                           executor=executor, supersedes=inputs.supersedes,
                           version=inputs.version_uid)


def begin_compile(project: StoreProject, *, version: str | None,
                  executor: str = "blender") -> OperationHandle:
    """Empieza ``gis.compile_constraints`` «en curso» en la versión ``version`` (véase el
    módulo). Rechazos sin registrar nada: ``VersionError`` (``core.version_required``,
    ``core.version_unknown``, ``core.version_not_editable``), ``IncompleteConstraints``
    (RF-012-04) y ``ConstraintError`` sin límite legal activo (RF-012-15). De una vez:
    :func:`begin_compile_steps` es lo mismo en varios pasos."""
    return drain(begin_compile_steps(project, version=version, executor=executor))


# --- Los límites declarados (T22; RF-012-05, RF-012-15) ----------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class DeclaredLimits:
    """Los límites declarados ahora, en la versión ``version_uid`` (``None``: en el proyecto): los
    límites legales y los perímetros de actuación activos, los declarados que ahí están
    desactivados, los problemas que impiden compilarlos (RF-012-04), el mayor resguardo hacia
    dentro de los límites legales (el de la banda, m; ``None`` sin ninguno) y su informe
    (:class:`~.overlay.LimitsReport`: ``None`` sin límite legal activo o con problemas, cuyas
    áreas no valdrían)."""

    version_uid: str | None
    legal: tuple[Constraint, ...]
    perimeter: tuple[Constraint, ...]
    inactive: tuple[Constraint, ...]
    problems: tuple[Incomplete, ...]
    inward_m: float | None
    report: LimitsReport | None


def _number(resolved: Mapping[str, object], item: Constraint) -> float | None:
    """El resguardo hacia dentro resuelto de ``item``, si lo tiene."""
    found = resolved.get(param_key(item.code, ConstraintParam.BUFFER_IN))
    value = found.value if isinstance(found, ResolvedParam) else found
    return None if isinstance(value, bool) or not isinstance(value, int | float) else float(value)


def declared_limits_steps(project: StoreProject, *, version: str | None = None
                          ) -> Generator[None, None, DeclaredLimits]:
    """Los límites declarados en la versión ``version`` (su uid; ``None``: los valores del
    proyecto) con su informe (:class:`DeclaredLimits`), por pasos (uno por lectura, comprobación,
    límite y superposición: RNF-012-06). Solo lee la capa de polígonos, que es donde caben los
    límites (D-23). Una sin código (dibujada en QGIS) cuenta como activa: la comprobación la lista.
    El informe es el de :func:`~.overlay.limits_report_steps` sobre la unión de los límites de
    cada clase (sin perímetro, el límite legal hace de perímetro, D-14) con lo que queda fuera de
    la rejilla de cada uno (``limit_outside``, RF-012-15)."""
    record = project.record
    if record is None:
        raise ValueError(f"el proyecto «{project.name}» se abrió solo con su cabecera")
    polygons = {GeometryKind.POLYGON: cstore.CONSTRAINT_LAYERS[GeometryKind.POLYGON]}
    with project.read() as conn:
        limits = [item for item in cstore.read_constraints(conn, polygons)
                  if item.ctype is not None and item.ctype.is_limit]
        resolved = _resolved(conn, project, limits, version)
    yield
    live = [item for item in limits if not is_code(item.code) or is_active(item, resolved)]
    kept = {id(item) for item in live}
    inactive = tuple(item for item in limits if id(item) not in kept)
    legal = tuple(item for item in live if item.ctype is ConstraintType.LEGAL_LIMIT)
    perimeter = tuple(item for item in live if item.ctype is ConstraintType.ACTION_PERIMETER)
    problems = yield from check_steps(live, resolved)
    inwards = [found for item in legal if is_code(item.code)
               if (found := _number(resolved, item)) is not None]
    inward = max(inwards) if inwards else None
    if problems or not legal:
        return DeclaredLimits(version, legal, perimeter, inactive, problems, inward, None)
    grid = project_grid(record.window, float(record.grid_step_m))
    outside: list[Outside] = []
    for item in (*legal, *perimeter):
        assert item.ctype is not None
        area = limit_outside(item, grid)
        yield
        if area > 0.0:
            outside.append(Outside(item.code, item.shown_name(), item.ctype, area))
    report = yield from limits_report_steps(
        tuple(part for item in legal for part in item.parts),
        tuple(part for item in perimeter for part in item.parts) or None,
        origin=(grid.west, grid.extent.ymin), outside=outside)
    return DeclaredLimits(version, legal, perimeter, inactive, problems, inward, report)


def declared_limits(project: StoreProject, *, version: str | None = None) -> DeclaredLimits:
    """:func:`declared_limits_steps` de una vez."""
    return drain(declared_limits_steps(project, version=version))


# --- La lista de las restricciones (T23; RF-012-04, RF-012-19) ----------------------------------

STATES: tuple[str, ...] = ("incomplete", "invalid", "active", "inactive")
"""El estado de una restricción en una versión: le falta algo que su tipo pide
(``incomplete``), su geometría no vale (``invalid``), activa o desactivada en ella
(``inactive``)."""
_INVALID_PROBLEMS = frozenset({
    "core.constraint_no_geometry", "core.constraint_self_intersecting",
    "core.constraint_no_area", "core.constraint_hole_outside", "core.constraint_parts_overlap",
    "core.constraint_no_length"})


@dataclass(frozen=True, slots=True, eq=False)
class ListedConstraint:
    """Una restricción de la lista: la fila del proyecto, su estado (:data:`STATES`) y los
    problemas que la hacen incompleta o no válida (vacíos si está activa o desactivada)."""

    constraint: Constraint
    state: str
    problems: tuple[Incomplete, ...]


def _switched_off(item: Constraint, resolved: Mapping[str, object]) -> bool:
    """Si la «activa» resuelta de ``item`` es falsa (sin código no hay parámetros)."""
    if not is_code(item.code):
        return False
    found = resolved.get(param_key(item.code, ConstraintParam.ACTIVE))
    return (found.value if isinstance(found, ResolvedParam) else found) is False


def listed_constraints_steps(project: StoreProject, *, version: str | None = None
                             ) -> Generator[None, None, tuple[ListedConstraint, ...]]:
    """Las restricciones del proyecto (las tres capas, en su orden) con su estado en la versión
    ``version`` (su uid; ``None``: los valores del proyecto) y lo que les falta, por pasos (uno
    por la lectura y uno por restricción y polígono de la comprobación: RNF-012-06). Una
    desactivada en la versión no se comprueba (``inactive``); una con un problema de geometría
    es ``invalid``, una con cualquier otro, ``incomplete`` (la dibujada en QGIS, sin código, tipo,
    motivo ni decisor); lo demás, ``active``. Solo lee."""
    with project.read() as conn:
        constraints = cstore.read_constraints(conn)
        resolved = _resolved(conn, project, constraints, version)
    yield
    problems = yield from check_steps(constraints, resolved)
    by_item: dict[tuple[str, int], list[Incomplete]] = {}
    for found in problems:
        by_item.setdefault((found.layer, found.fid), []).append(found)
    listed: list[ListedConstraint] = []
    for item in constraints:
        found_here = tuple(by_item.get((item.layer, item.fid), ()))
        if _switched_off(item, resolved):
            state = "inactive"
        elif any(problem.problem in _INVALID_PROBLEMS for problem in found_here):
            state = "invalid"
        elif found_here:
            state = "incomplete"
        else:
            state = "active"
        listed.append(ListedConstraint(item, state, found_here))
    return tuple(listed)


def listed_constraints(project: StoreProject, *, version: str | None = None
                       ) -> tuple[ListedConstraint, ...]:
    """:func:`listed_constraints_steps` de una vez."""
    return drain(listed_constraints_steps(project, version=version))


# --- Escribir el resultado (A11) ---------------------------------------------------------------


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND "
                        "lower(name) = lower(?)", (name,)).fetchone() is not None


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _disk_error(name: str, error: OSError) -> GisError:
    if isinstance(error, PermissionError):
        return target_locked(name)
    return write_failed(name, error)


@dataclass(frozen=True, slots=True)
class _Table:
    spec: DatasetSpec
    family: str
    rows: tuple[tuple[Any, ...], ...]


@dataclass(frozen=True, slots=True, eq=False)
class StoredMasks:
    """Lo guardado de una compilación: su resultado y sus salidas registradas."""

    result: CompileResult
    records: tuple[Any, ...]


class MaskWriter:
    """Los resultados de una ``gis.compile_constraints`` «en curso» (``handle``) en
    ``project``: la rejilla de clases (:meth:`classes_paths`, :meth:`classes`), las tablas
    (:meth:`tables`) y :meth:`commit`, en una transacción; si se cierra sin confirmar, nada
    (véase el módulo). Se usa como gestor de contexto."""

    def __init__(self, project: StoreProject, handle: OperationHandle) -> None:
        if not isinstance(handle, OperationHandle):
            raise TypeError(f"los resultados son de un OperationHandle, no {handle!r}")
        if handle.project_uid != project.uid or handle.op_type != declared.COMPILE:
            raise ValueError(f"«{handle.op_type}» no es una compilación de este proyecto")
        self.project = project
        self.handle = handle
        with project.read() as conn:
            version = versions_read.version(conn, handle.version_uid)
        if version is None:
            raise ValueError(f"la versión de la operación {handle.uid} no existe")
        self.version_code = version.code
        self.crs, self.vertical = project_references(project)
        self.final: Path | None = None
        self.temporary: Path | None = None
        self.backup: Path | None = None
        self._classes: DatasetSpec | None = None
        self._tables: list[_Table] = []
        self._installed = self._replaced = False
        self._committed = self._closed = False

    def __enter__(self) -> MaskWriter:
        return self

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None,
                 traceback: TracebackType | None) -> None:
        self.close(error)

    def _check_place(self, conn: sqlite3.Connection, spec: DatasetSpec) -> None:
        rows = conn.execute(
            "SELECT name, status, immutable FROM gb_dataset WHERE store = ? AND locator = ?",
            (str(spec.store), spec.locator)).fetchall()
        live = {str(status) for status in LIVE_STATUSES}
        mine = [row for row in rows if row[0] == spec.name and row[1] in live and not row[2]]
        if spec.store is Store.GPKG:
            exists = _table_exists(conn, spec.locator)
        else:
            exists = Path(self.project.root, *spec.locator.split("/")).exists()
        if len(mine) != len(rows) or (exists and not mine):
            raise GisError("gis.output_target_taken", obj=f"{_OBJ}: «{spec.name}»",
                           field=_FIELD, value=spec.locator, name=spec.name)

    def classes_paths(self) -> tuple[Path, Path]:
        """Prepara la rejilla de clases: su sitio libre o del mismo dato, su temporal, su
        destino y la copia del anterior reclamados; devuelve ``(destino, temporal)``."""
        spec = declared.dataset_spec(declared.CLASSES, self.version_code)
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
        self.final, self.temporary, self.backup = final, temporary, backup
        return final, temporary

    def prepare_steps(self, result: CompileResult, constraints: Sequence[Constraint]
                      ) -> Generator[None, None, None]:
        """La rejilla de clases escrita y las cuatro tablas con su hash (fuera de la
        transacción), por pasos: una unidad por trozo de filas de cada tabla (T35; sin sostener
        una lectura abierta entre unidades)."""
        if result.classes is None or self.temporary is None:
            raise ValueError("la rejilla de clases no se preparó (classes_paths)")
        if Path(result.classes.path) != self.temporary:
            raise ValueError("la rejilla de clases no está en su temporal")
        self._classes = declared.dataset_spec(declared.CLASSES, self.version_code,
                                              content=result.classes.digest,
                                              crs_epsg=self.crs.epsg)
        yield
        for family in (declared.ZONES, declared.REPORT, declared.PARTS, declared.SHAPES):
            rows = tuple(_rows(family, result, constraints, self.crs.epsg))
            yield
            kind = declared.FAMILIES_BY_CODE[family].kind
            content = yield from _digest_steps(family, rows, self.crs)
            spec = declared.dataset_spec(family, self.version_code, content=content,
                                         crs_epsg=self.crs.epsg if kind == "vector" else None)
            with self.project.read() as conn:
                self._check_place(conn, spec)
            self._tables.append(_Table(spec, family, rows))
            yield

    def prepare(self, result: CompileResult, constraints: Sequence[Constraint]) -> None:
        """:meth:`prepare_steps` de una vez."""
        drain(self.prepare_steps(result, constraints))

    @property
    def specs(self) -> tuple[DatasetSpec, ...]:
        found = [] if self._classes is None else [self._classes]
        return (*found, *(table.spec for table in self._tables))

    def _install(self) -> None:
        assert self.final is not None and self.temporary is not None and self.backup is not None
        if self.final.exists():
            try:
                os.replace(self.final, self.backup)
            except OSError as error:
                raise _disk_error(self.final.name, error) from None
            self._replaced = True
        try:
            os.replace(self.temporary, self.final)
        except OSError as error:
            failure = _disk_error(self.final.name, error)
            self._restore()
            raise failure from None
        self._installed = True

    def _restore(self) -> None:
        if self._replaced and self.backup is not None and self.final is not None:
            try:
                os.replace(self.backup, self.final)
                self._replaced = False
            except OSError:
                pass

    def _write_table(self, conn: sqlite3.Connection, table: _Table) -> None:
        spec = table.spec
        self._check_place(conn, spec)
        if _table_exists(conn, spec.locator):
            conn.execute(f'DELETE FROM "{spec.locator}"')
        else:
            label = declared.FAMILIES_BY_CODE[table.family].label
            _create(conn, table.family, spec.locator, self.crs.epsg,
                    f"{label} {self.version_code}",
                    f"{label} de la versión {self.version_code}, de Geoblender")
        insert_rows(conn, spec.locator, _names(table.family), table.rows)

    def commit(self, *, figures: Sequence[FigureSpec], message: str | None = None
               ) -> tuple[Any, ...]:
        """Pone la rejilla en su sitio y confirma, en **una** transacción, las tablas, las
        cifras y ``complete``. Si falla, deshace lo de esta operación y el error sigue."""
        if self._committed or self._closed:
            raise RuntimeError("los resultados ya se confirmaron o se cerraron")
        try:
            self._install()
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

    def close(self, error: BaseException | None = None) -> None:
        """Termina: confirmada, borra el anterior apartado; si no, deshace lo puesto, borra el
        temporal y deja la operación «cancelada» o «fallida»."""
        if self._closed:
            return
        self._closed = True
        if self._committed:
            if self.backup is not None:
                _discard(self.backup)
            return
        if self._installed and self.final is not None:
            if self._replaced:
                self._restore()
            else:
                _discard(self.final)
        if self.temporary is not None:
            _discard(self.temporary)
        problem = self._abandon(error)
        if problem and error is not None:
            error.add_note(problem)

    def _abandon(self, error: BaseException | None) -> str | None:
        try:
            with self.project.read() as conn:
                row = conn.execute("SELECT status FROM gb_operation WHERE uid = ?",
                                   (self.handle.uid,)).fetchone()
            if row is None or row[0] != OperationStatus.RUNNING:
                return None
            if isinstance(error, GeneratorExit):
                self.handle.cancel(CANCELLED_REASON)
            elif isinstance(error, CANCELLATIONS):
                self.handle.cancel(cancel_reason(error))
            else:
                self.handle.fail(NOT_COMPLETED_REASON if error is None
                                 else failure_reason(error))
        except (GeoblenderError, OSError, sqlite3.Error) as exc:
            return (f"La operación «{self.handle.op_type}» ({self.handle.uid}) sigue «en curso» "
                    f"en el proyecto: no se pudo registrar cómo terminó ({exc}).")
        return None


# --- Los pasos en el proyecto ------------------------------------------------------------------


def _request(handle: OperationHandle, constraints: Sequence[Constraint],
             resolved: Mapping[str, object], grid: Grid) -> CompileRequest:
    return CompileRequest(tuple(constraints), MappingProxyType(dict(resolved)), grid=grid,
                          previous=PreviousMasks.from_settings(handle.settings.get("previous")))


def compile_run(project: StoreProject, handle: OperationHandle, *,
                budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """Los pasos de ``gis.compile_constraints`` (``handle``, «en curso», de
    :func:`begin_compile`): las restricciones del proyecto, los parámetros que anotó al empezar,
    la rejilla y lo anterior de sus ajustes; compilar y guardar. El último ``Progress`` lleva el
    :class:`StoredMasks`. Cerrarlo antes o un fallo: nada en el proyecto (RF-012-28)."""
    if not isinstance(handle, OperationHandle) or handle.op_type != declared.COMPILE:
        raise ValueError(f"compile_run es de {declared.COMPILE}")
    return _run(project, handle, budget_s)


def recompute_run(request: RecomputeRequest, *, budget_s: float = STEP_BUDGET_S
                  ) -> tuple[OperationHandle, Iterator[Progress]]:
    """Repite ``gis.compile_constraints`` de ``request`` (``RecomputeRequest`` de «Recalcular lo
    obsoleto», RF-008-26; RF-012-16; plan A12, D-19): empieza la compilación nueva, que
    sustituye a la anterior en la revisión abierta de **su** versión, con lo que lee hoy
    (:func:`begin_compile`: las restricciones, sus parámetros resueltos de nuevo versión →
    proyecto, los sectores, las búsquedas vigentes y, de lo que cambió, lo anterior para lo
    ganado y lo perdido), y devuelve su ``OperationHandle`` «en curso» y sus pasos
    (:func:`compile_run`), que avanza quien la llama (en Blender, la cola de ``gis``; la
    operación sigue «en curso» hasta el último).

    Al llamar, sin empezar nada: ``TypeError``/``ValueError`` si no es una petición de este tipo
    de operación; los rechazos de :func:`begin_compile` (``VersionError`` sin versión o en una
    no editable, restricciones incompletas, sin límite legal)."""
    if not isinstance(request, RecomputeRequest):
        raise TypeError(f"se recalcula una RecomputeRequest, no {request!r}")
    if request.op_type != declared.COMPILE:
        raise ValueError(f"recompute_run repite {declared.COMPILE}, no «{request.op_type}»")
    project: StoreProject = request.project  # type: ignore[assignment]
    handle = begin_compile(project, version=request.version)
    try:
        return handle, compile_run(project, handle, budget_s=budget_s)
    except BaseException as error:
        handle.fail(failure_reason(error))
        raise


def _run(project: StoreProject, handle: OperationHandle, budget_s: float
         ) -> Iterator[Progress]:
    with MaskWriter(project, handle) as out:
        with project.read() as conn:
            constraints = cstore.read_constraints(conn)
        yield Progress(_COMPILE_PHASE, 0, planned_steps(len(constraints)) + 2, _COMPILE_TEXT)
        resolved = {param.key: param for param in handle.params}
        request = _request(handle, constraints, resolved, declared.grid_of(handle.settings))
        final, temporary = out.classes_paths()
        steps = compile_steps(request, budget_s=budget_s, classes_path=final,
                              classes_temporary=temporary,
                              references=(out.crs, out.vertical))
        last: Progress | None = None
        with closing(steps):
            for step in steps:
                if step.result is not None:
                    last = step
                    break
                yield Progress(step.phase, step.done, step.total + 2, step.message)
        assert last is not None and isinstance(last.result, CompileResult)
        result: CompileResult = last.result
        done, total = last.total, last.total + 2
        saving = pace_units(out.prepare_steps(result, constraints), budget_s)
        while True:  # hashes de las tablas por tramos (fuera de la transacción, R4)
            try:
                next(saving)
            except StopIteration:
                break
            done += 1
            total = max(total, done + 1)
            yield Progress(_SAVE_PHASE, done, total, _SAVE_TEXT)
        total = max(total, done + 2)
        yield Progress(_SAVE_PHASE, total - 1, total, _SAVE_TEXT)
        records = out.commit(figures=result.figures, message=last.message)
    yield Progress(_SAVE_PHASE, total, total, last.message, result=StoredMasks(result, records))


# --- Reproducir --------------------------------------------------------------------------------


def _frozen_constraints(request: ReproduceRequest) -> tuple[Constraint, ...]:
    """Las restricciones congeladas que consumió la compilación (sus tres capas)."""
    found: list[Constraint] = []
    for kind, role in declared.CONSTRAINT_ROLES.items():
        items = [item for item in request.inputs if item.role == role]
        if not items:
            continue
        item = items[0]
        layer = str(item.settings.get("layer") or cstore.layer_of(kind))
        with GpkgConnection.open_read(Path(item.files["main"])) as gpkg:
            found.extend(cstore.read_constraints(gpkg.connection, {kind: layer}))
    return tuple(found)


def _reproduced_table(request: ReproduceRequest, family: str, rows: Sequence[tuple[Any, ...]],
                      crs: CrsRef, code: str) -> ReproducedOutput:
    found = declared.FAMILIES_BY_CODE[family]
    table = declared.dataset_locator(family, code)
    path = Path(request.workdir) / f"{found.role}.gpkg"
    check_path_length(path, obj=_OBJ)
    with GpkgConnection.open_write(path, create=True) as gpkg, gpkg.transaction() as conn:
        create_base(conn, crs)
        _create(conn, family, table, crs.epsg, found.label)
        insert_rows(conn, table, _names(family), rows)
    return ReproducedOutput(found.role, found.reader, {"main": path}, {"layer": table})


def reproduce_compile(request: ReproduceRequest, *,
                      budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """Reproduce ``gis.compile_constraints`` con sus restricciones y sus parámetros congelados
    y sus ajustes (la rejilla, lo anterior), sin el proyecto: sus pasos y, el último, el
    ``ReproducedResult`` con las cinco salidas y las cifras."""
    if not isinstance(request, ReproduceRequest) or request.op_type != declared.COMPILE:
        raise ValueError(f"esta función reproduce {declared.COMPILE}")
    return _reproduce(request, budget_s)


def _reproduce(request: ReproduceRequest, budget_s: float) -> Iterator[Progress]:
    crs, vertical = request.references()
    constraints = _frozen_constraints(request)
    resolved = {key: value for key, (value, _unit) in request.params.items()}
    grid = declared.grid_of(request.settings)
    compiled = CompileRequest(constraints, MappingProxyType(resolved), grid=grid,
                              previous=PreviousMasks.from_settings(
                                  request.settings.get("previous")))
    path = Path(request.workdir) / CLASSES_FILE
    temporary = path.with_name(path.name + ".tmp")
    check_path_length(temporary, obj=_OBJ)
    steps = compile_steps(compiled, budget_s=budget_s, classes_path=path,
                          classes_temporary=temporary, references=(crs, vertical))
    last: Progress | None = None
    with closing(steps):
        for step in steps:
            last = step
            if isinstance(step.result, CompileResult):
                break
            yield step
    assert last is not None and isinstance(last.result, CompileResult)
    result: CompileResult = last.result
    assert result.classes is not None
    os.replace(result.classes.path, path)
    code = _version_code(request)
    outputs = [ReproducedOutput(declared.FAMILIES_BY_CODE[declared.CLASSES].role,
                                declared.FAMILIES_BY_CODE[declared.CLASSES].reader,
                                {"main": path})]
    for family in (declared.ZONES, declared.REPORT, declared.PARTS, declared.SHAPES):
        outputs.append(_reproduced_table(request, family,
                                         _rows(family, result, constraints, crs.epsg), crs,
                                         code))
    yield Progress(last.phase, last.total, last.total, "Máscaras reproducidas",
                   result=ReproducedResult(tuple(outputs), result.figures))


def _version_code(_request: ReproduceRequest) -> str:
    """Un código de versión para nombrar las tablas reproducidas (su nombre no cuenta en el
    hash)."""
    return "V01"


REPRODUCE: Mapping[str, Any] = MappingProxyType({declared.COMPILE: reproduce_compile})
"""La función de reproducir de la compilación (la que registra ``bl``)."""

