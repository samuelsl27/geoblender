# SPDX-License-Identifier: GPL-3.0-or-later
"""Escribir el resultado de las envolventes y el escalonado, todo o nada (spec 013, T14; HU-013-2,
HU-013-3; RF-013-04, RF-013-17, RF-013-31; plan 013 §5.3.2, D-14, D-27, R4; ADR-0025 §3).

**Calcular no registra nada; solo «Crear» registra** (D-14). El cálculo deja cada rejilla en un
temporal junto a su destino (``<fichero>.tmp-<sesión>``), con su hash por bandas de filas, y cada
tabla con el suyo, fuera de cualquier transacción (R4). No hay operación ni dato ni cifra hasta
que la persona confirma; cerrar los pasos (Esc) o la ventana borra los temporales.

- :func:`prepare_envelope` y :func:`prepare_design` (:class:`OperationStart`) reúnen lo que
  anotará la operación al empezar: los ajustes, las entradas (con los papeles de
  ``design.provenance``), los parámetros que lee y **las máscaras de la versión por el contrato de
  la 012** (``gis.masks.access``): si no están al día se compilan antes, como operación propia
  (RF-013-04); se registran como entradas, de modo que la operación queda obsoleta si cambian las
  restricciones, los sectores, las búsquedas o sus parámetros; y no se usan obsoletas, ni al
  empezar ni al confirmar. También anotan el hash que tenía cada entrada: si alguna cambió entre
  calcular y crear, el resultado ya no le corresponde (``des.input_changed``).
  :func:`begin_envelope` y :func:`begin_design` registran la operación «en curso» (un recálculo,
  T15).
- :class:`DesignWriter` escribe el resultado de **una** operación: :meth:`~DesignWriter.grid_steps`
  y :meth:`~DesignWriter.table_steps` preparan cada salida (un paso por banda de hash, por tesela
  de la rejilla y por trozo de filas, para ceder el hilo); :meth:`~DesignWriter.commit` abre la
  operación (:meth:`OperationStart.begin`, en la propia transacción: si algo falla no queda ni
  la operación), reclama las rutas, pone las rejillas en su sitio, escribe las tablas y las cifras
  y completa, todo en **una** transacción de escritura (lo único que no se trocea, R4);
  :meth:`~DesignWriter.close` deshace lo puesto y borra los temporales. Con una operación que ya
  empezó (:meth:`~DesignWriter.resume`), la completa, o la deja «cancelada» o «fallida» (RF-008-19).
- **Calcular y registrar de una vez, sin confirmar** (T15): :func:`run_envelope` y
  :func:`run_design` empiezan la operación y dan los pasos que calculan (``design.pipeline``),
  escriben las salidas en sus temporales y completan en una transacción; :func:`recompute_run`
  repite con ellas lo obsoleto, con los ajustes de la operación que sustituye (RF-008-26), sin
  pedir confirmación. La reproducción de lo congelado es de ``design.reproduce``.
- **Las partes que comparten esos caminos y «Calcular»** (T17, ``design.steps``): :func:`masks_steps`
  (las máscaras de la versión, compiladas antes por pasos si hace falta),
  :func:`prepare_envelope_units` y :func:`prepare_design_units` (lo que se lee y se rechaza antes de
  calcular, por unidades) y :func:`compute_envelope_steps` y :func:`compute_design_steps` (el cálculo
  y la escritura de las salidas en los temporales de un :class:`DesignWriter`, sin confirmar).
- **El recinto excavable** (spec 014, T06; RF-014-01): :func:`prepare_excavation_area`,
  :func:`prepare_area_units` y :func:`compute_area_steps` (``des.excavation_area``, el dato
  ``des_rcn_`` y la cifra ``des.rcn_area_m2``), con el mismo :class:`DesignWriter`; y, desde la
  T19, :func:`run_excavation_area`, su recálculo.
- **La cantera con dos superficies** (spec 014, T19; RF-014-29 a RF-014-31): :func:`prepare_quarry`
  y :func:`prepare_quarry_units` (con el rechazo de un sector del recinto con la búsqueda pendiente,
  RF-014-30), las piezas que lee (:class:`QuarryParts`, :func:`quarry_domain`,
  :func:`quarry_parts_units`, compartidas con la reproducción), el cálculo
  (:func:`quarry_compute_steps`, con sus avisos, :func:`quarry_notices`) y su escritura
  (:func:`compute_quarry_steps`: las cinco rejillas de :func:`quarry_grids`, las bermas de las dos
  superficies con :data:`QUARRY_BERM_COLUMNS` y el informe ``des_qrp_``); y :func:`run_quarry`, su
  recálculo.
- **Las transiciones con el terreno no afectado** (spec 014, T28; RF-014-19 a RF-014-21,
  RF-014-29): :func:`prepare_edge_transition` y :func:`prepare_transition_units` (con el rechazo de
  una superficie que no es de diseño de la versión, :func:`design_surface_of`), el cálculo
  (:func:`transition_compute_steps`, compartido con la reproducción) y su escritura
  (:func:`compute_transition_steps`: ``des_trn_`` y el informe ``des_erp_``,
  :func:`edge_report_rows`); y :func:`run_edge_transition`, su recálculo.
- **«Solo relleno…»** (spec 014, T30; RF-014-22 a RF-014-25, RF-014-29): :func:`prepare_fill_only`
  y :func:`prepare_fill_only_units` (lo del escalonado de la 013 —la envolvente, la superficie de
  partida, las anclas, los sectores y el rechazo de uno pendiente que toca la envolvente— más la
  capa de láminas de agua y los intocables con su nombre: :class:`FillOnlyParts`), el cálculo
  (:func:`fill_only_compute_steps`, ``design.fronts.fill_only_steps``, compartido con la
  reproducción) y su escritura (:func:`compute_fill_only_steps`: ``des_srf_`` y ``des_rpt_``,
  :func:`fill_only_report_rows`); y :func:`run_fill_only`, su recálculo.
- **La comprobación contra un límite nuevo** (spec 014, T31; RF-014-26): :func:`limit_checks` (y
  :func:`limit_checks_steps`) da, al recompilar las máscaras, lo que cada superficie de la 014 de
  la versión (:func:`limit_surfaces`) mueve fuera del límite vigente (``design.refit``), sin
  escribir nada; desde la T35 (RNF-014-02), en unidades de una lectura cada una, y con
  :class:`LimitCheckMemo`, su caché en memoria por superficie con la clave barata de
  :func:`limit_check_keys` (sin leer ninguna rejilla), que llenan los pasos de la compilación y
  leen la barra N y el diálogo del ajuste.
- **El ajuste a un límite nuevo** (spec 014, T32; RF-014-27 a RF-014-29): :func:`prepare_refit` y
  :func:`prepare_refit_units` (las superficies de diseño de :data:`REFIT_SOURCES`, cada una con el
  perfil de la operación que hizo su diseño, :func:`refit_profiles`, P-3, y la cara y el factor de
  malla que **anotó** esa operación, no los de hoy, T49), el cálculo
  (:func:`refit_compute_steps`, con el rechazo de un ángulo que no es esa cara, RF-014-28, y,
  si lleva las dos superficies de una misma cantera, la regla de orden de esa cantera y
  ``check_order`` después de ajustarlas, T53, RF-014-14, y el aviso de cada diseño obsoleto del
  que sale, que recalcularlo sustituye el ajuste, T54, RF-014-31) y su
  escritura (:func:`compute_refit_steps`: una ``des_adj_`` por superficie, con
  :meth:`DesignWriter.grid_steps` y su ``part``); y :func:`run_refit`, su recálculo (no se
  reproduce: depende del límite vigente).
- **Las entidades de diseño** (spec 015, T13 y T17; RF-015-01, RF-015-02, RF-015-10): el escritor conoce
  las tablas de la plataforma (:data:`ENTITY_COLUMNS` para ``des_epr_``; ``des_prp_`` lleva las de
  :data:`REPORT_COLUMNS`), :meth:`DesignWriter.commit` admite ``before_begin``, una función que escribe, en
  la misma transacción y antes de abrir la operación, los parámetros de la entidad, y
  :meth:`DesignWriter.declared_steps` prepara la capa de las restricciones declaradas de la versión
  (``des_decl_``, que ``commit`` reescribe entera con ``core.constraints.declared.write_declared``); la
  preparación, el cálculo y «Crear» son de ``design.entity_store``, que también hace la declaración.
- Un **nombre** es único en la versión (RF-013-17): el dato ``des_env_<nombre>`` vigente (o el de
  cualquiera de las salidas de su tipo) lo ocupa, salvo que lo escriba la operación a la que la
  nueva sustituye (``supersedes``). Una envolvente y un escalonado pueden llamarse igual.
- :func:`berm_rows` y :func:`report_rows` dan las filas de las dos tablas (``des_bmt_`` y
  ``des_rpt_``). Ninguna lleva NaN ni infinito (RF-013-17): lo que no se puede dar es una fila sin
  valor con su nota.

Python puro (nivel 8): no importa ``reserves`` ni ``bl``.
"""

from __future__ import annotations

import json
import math
import numbers
import os
import sqlite3
from collections.abc import (Callable, Generator, Hashable, Iterable, Iterator, Mapping,
                             Sequence)
from contextlib import closing
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType, TracebackType
from typing import TYPE_CHECKING, Any

import numpy as np

from ..core.constraints.declared import DeclaredConstraint, write_declared
from ..core.constraints.store import constraint_names
from ..core.content import builtin as core_builtin
from ..core.content.encoder import NORMALIZER, ContentDigest, ContentHasher
from ..core.datasets import registry as dataset_registry
from ..core.datasets.model import (
    DATASET_DECLARATIONS,
    LIVE_STATUSES,
    DatasetRecord,
    DatasetSpec,
    Store,
)
from ..core.errors import GeoblenderError
from ..core.georef import CrsRef
from ..core.gpkg.base import ColumnDef, create_attribute_table, create_base
from ..core.gpkg.connection import GpkgConnection
from ..core.params import PROJECT_SCOPE, VERSION_SCOPE, ParameterStore, definition
from ..core.paths import check_path_length
from ..core.project.model import Progress
from ..core.provenance.figures import FigureSpec
from ..core.provenance.operations import (
    CANCELLATIONS,
    NOT_COMPLETED_REASON,
    ItemKind,
    OperationHandle,
    OperationStatus,
    Use,
    begin_in_transaction,
    begin_operation,
    cancel_reason,
    failure_reason,
)
from ..core.provenance.recompute import RecomputeRequest
from ..core.provenance.stale import OPERATION as STALE_OPERATION
from ..core.provenance.stale import item_causes
from ..core.versions import read as versions_read
from ..core.versions import store as versions_store
from ..core.versions.model import Version, VersionError
from ..gis.content import GEOTIFF, raster_header
from ..gis.geotiff import writer
from ..gis.grid import Grid
from ..gis.masks import access
from ..gis.masks import provenance as masks_declared
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.masks.store import CANCELLED_REASON, available_tables
from ..gis.messages import GisError
from ..gis.raster import Raster
from ..gis.store import StoreProject, backup_path, insert_rows, project_references, temporary_path
from ..gis.vector import FeatureLayer
from . import edges, fronts, pipeline, provenance, quarry, refit
from .messages import DesignError
from .model import (
    DesignRequest,
    EnvelopeRequest,
    FillOnlyRequest,
    Metric,
    Order,
    QuarryRequest,
    RefitRequest,
    SlopeMode,
    Surface,
    Zone,
    ZoneKind,
)
from .params import (
    CONSERVE_SLOPE,
    CROWN_RING,
    EDGE_MAX_STEP,
    EDGE_MIN_SHARE,
    TOLERANCE_FACE,
    UNSPLIT_MIN_AREA,
    UNSPLIT_THRESHOLD,
    VERIFY_MIN_THICKNESS,
    WARNING_RATIO,
    BenchParam,
    bench_key,
    check_bench_value,
    check_quarry_param,
)
from .params import EDGE_TRANSITION as EDGE_TRANSITION_DEG
from .preview import Notice, _features, _quarry_warnings
from .profiles import profile_names
from .report import moved_cells
from .sectors import DesignSector, design_sectors, refuse_pending, slope_params, touched
from .seeds import (
    DomainSet,
    SectorRef,
    SeedSet,
    assemble_units,
    check_source,
    domain_of,
    pace_progress,
    sector_layout,
    seed_units,
)
from .surfaces import project_frame, read_surface
from .zones import constraint_cells, layer_cells

if TYPE_CHECKING:  # solo para los tipos: importarlos arrastraría los cálculos
    from .berms import Berms
    from .report import DesignReport

__all__ = [
    "BERM_COLUMNS",
    "ENTITY_COLUMNS",
    "NO_DATA_NOTE",
    "NO_MOVEMENT_NOTE",
    "QUARRY_BERM_COLUMNS",
    "REPORT_COLUMNS",
    "DesignWriter",
    "FillOnlyParts",
    "OperationStart",
    "PreparedArea",
    "PreparedDesign",
    "PreparedEnvelope",
    "PreparedFillOnly",
    "PreparedQuarry",
    "PreparedRefit",
    "PreparedTransition",
    "QuarryCalculated",
    "QuarryParts",
    "REFIT_SOURCES",
    "RefitPart",
    "Stored",
    "SurfaceOrigin",
    "begin_design",
    "begin_envelope",
    "berm_rows",
    "RECOMPUTED",
    "columns_of",
    "compute_area_steps",
    "compute_design_steps",
    "compute_envelope_steps",
    "compute_fill_only_steps",
    "compute_quarry_steps",
    "compute_refit_steps",
    "compute_transition_steps",
    "created_step_steps",
    "edge_report_rows",
    "fill_only_compute_steps",
    "fill_only_report_rows",
    "LIMIT_CHECKED_TYPES",
    "LimitCheckMemo",
    "LimitKey",
    "LimitKeys",
    "limit_check_keys",
    "limit_checks",
    "limit_checks_steps",
    "limit_surfaces",
    "masks_steps",
    "number",
    "prepare_area_units",
    "prepare_design",
    "prepare_design_units",
    "prepare_edge_transition",
    "prepare_envelope",
    "prepare_envelope_units",
    "prepare_excavation_area",
    "prepare_fill_only",
    "prepare_fill_only_units",
    "prepare_quarry",
    "prepare_quarry_units",
    "prepare_refit",
    "prepare_refit_units",
    "prepare_transition_units",
    "design_surface_of",
    "design_surface_start",
    "previous_comparison",
    "quarry_berm_rows",
    "quarry_compute_steps",
    "quarry_domain",
    "quarry_grids",
    "quarry_notices",
    "quarry_parts_units",
    "quarry_report_rows",
    "recompute_run",
    "refit_compute_steps",
    "refit_profiles",
    "report_rows",
    "request_profiles",
    "require_version",
    "run_design",
    "run_edge_transition",
    "run_envelope",
    "run_excavation_area",
    "run_fill_only",
    "run_quarry",
    "run_refit",
    "transition_compute_steps",
]

_OBJ = "Envolventes y escalonado"
_FIELD = "ubicación"
_KIND_ES = MappingProxyType({"raster": "una rejilla", "table": "una tabla",
                             "vector": "una capa de polígonos"})
"""Cómo dice un mensaje de error el tipo de una familia de datos del diseño (``DatasetFamily.kind``)."""
_HASH_BLOCK_CELLS = 1 << 18
"""Las celdas que se hashean en cada unidad de la rejilla (bandas de filas: ≈ 1,4 ms cada una)."""
_DIGEST_ROWS_PER_UNIT = 4000
"""Las filas que se insertan en cada unidad del hash de una tabla (un múltiplo de las 500 de cada
sentencia de ``insert_rows``)."""

# --- Las tablas ---------------------------------------------------------------------------------

BERM_COLUMNS: tuple[ColumnDef, ...] = (
    ColumnDef("sector", "TEXT", True), ColumnDef("profile", "TEXT", True),
    ColumnDef("level_m", "DOUBLE", True), ColumnDef("cells", "INTEGER", True),
    ColumnDef("area_m2", "DOUBLE", True), ColumnDef("anchor_m", "DOUBLE", False),
    ColumnDef("anchor_diff_m", "DOUBLE", False))
"""Las columnas de ``des_bmt_`` (RF-013-28), las de ``design.berms.COLUMNS`` y en su orden."""
REPORT_COLUMNS: tuple[ColumnDef, ...] = (
    ColumnDef("quantity", "TEXT", True), ColumnDef("value", "DOUBLE", False),
    ColumnDef("unit_code", "TEXT", False), ColumnDef("note", "TEXT", False))
"""Las columnas de ``des_rpt_``: formato largo, como ``gis_mskr_`` (plan §5.2.3)."""
QUARRY_BERM_COLUMNS: tuple[ColumnDef, ...] = (ColumnDef("surface", "TEXT", True), *BERM_COLUMNS)
"""Las columnas de ``des_bmt_`` de una cantera (spec 014, T19; plan 014 §5.2.3): las bermas de
las dos superficies, cada fila con su superficie (``final`` o ``exploitation``) delante de las de
:data:`BERM_COLUMNS`."""
ENTITY_COLUMNS: tuple[ColumnDef, ...] = (
    ColumnDef("code", "TEXT", True), ColumnDef("name", "TEXT", True),
    ColumnDef("kind", "TEXT", True), ColumnDef("start_surface", "TEXT", True),
    ColumnDef("support_surface", "TEXT", False), ColumnDef("layer", "TEXT", True),
    ColumnDef("source_fid", "INTEGER", True), ColumnDef("geometry_sha256", "TEXT", True),
    ColumnDef("mode", "TEXT", True), ColumnDef("cells", "INTEGER", True),
    ColumnDef("axis_principal", "INTEGER", True), ColumnDef("bounds", "TEXT", True),
    ColumnDef("footprint", "TEXT", True), ColumnDef("axis", "TEXT", True))
"""Las columnas de ``des_epr_`` (spec 015, T13; plan 015 §5.2.3: «huella, eje y atributos»): **una fila
por entidad** con sus atributos —el código, el nombre, el tipo, el nombre de los datos de su superficie
de partida y de apoyo, la capa y el ``fid`` de su geometría de origen y su hash, el modo y las celdas de
la huella—, la ventana de trabajo (``bounds``: ``[fila0, fila1, col0, col1]`` de la rejilla entera, las
segundas excluidas, JSON), la huella en tramos de fila (``footprint``: ``[[fila, col0, col1], …]`` absolutos,
``col1`` excluida, JSON) y los vértices de su eje (``axis``: ``[[x, y], …]`` absolutos en float64, JSON; con
``axis_principal`` si es el eje principal de un polígono sin eje enlazado). De ella salen la zona
declarada (T16), el cargador (T28) y la capa de entidades (T30)."""
_COLUMNS: Mapping[str, tuple[ColumnDef, ...]] = MappingProxyType({
    provenance.BERM_TABLE: BERM_COLUMNS, provenance.REPORT_TABLE: REPORT_COLUMNS,
    provenance.QUARRY_REPORT_TABLE: REPORT_COLUMNS, provenance.EDGE_REPORT_TABLE: REPORT_COLUMNS,
    provenance.ENTITY_TABLE: ENTITY_COLUMNS, provenance.ENTITY_REPORT_TABLE: REPORT_COLUMNS})


def columns_of(op_type: str, family: str) -> tuple[ColumnDef, ...]:
    """Las columnas de la tabla ``family`` de una operación ``op_type``: las de su familia salvo
    las bermas de una cantera (:data:`QUARRY_BERM_COLUMNS`). ``KeyError`` si no es una tabla."""
    if op_type == provenance.QUARRY and family == provenance.BERM_TABLE:
        return QUARRY_BERM_COLUMNS
    return _COLUMNS[family]


Row = tuple[Any, ...]


def _real(key: str, value: object) -> float:
    """``value`` como real finito; si no lo es, un error del programa (RF-013-17)."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"el valor de «{key}» es un número, no {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"el valor de «{key}» no es un número finito: {value!r} (RF-013-17: el "
                         "informe no lleva una cifra NaN ni infinita)")
    return number


def _plain(value: object) -> object:
    """Un valor de un aviso que ``json`` no escribe solo (un escalar de numpy)."""
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"el valor {value!r} de un aviso no se puede guardar como JSON")


def berm_rows(berms: Berms) -> list[Row]:
    """Las filas de ``des_bmt_`` de las bermas medidas ``berms`` (``design.berms.Berms``), en el
    orden de su tabla y de :data:`BERM_COLUMNS`. Una cota de anclaje o una diferencia que no sea
    finita se guarda sin valor (nunca NaN)."""
    found: list[Row] = []
    for row in berms.table:
        found.append(tuple(None if isinstance(value, float) and not math.isfinite(value)
                           else value for value in row.values()))
    return found


_REPORT_SCALARS: tuple[tuple[str, str], ...] = (
    ("cut_m3", "m3"), ("fill_m3", "m3"), ("cut_cells", "-"), ("fill_cells", "-"),
    ("moved_area_m2", "m2"), ("nodata_cells", "-"), ("nodata_area_m2", "m2"),
    ("min_thickness_m", "m"))
_REPORT_SLOPES = ("slope_p90_deg", "slope_p99_deg", "slope_max_deg")
_REPORT_EDGES: tuple[tuple[str, str], ...] = (("edge_step_max_m", "m"), ("edge_cells", "-"))
NO_MOVEMENT_NOTE = "no_movement"
"""La nota de una cifra que no existe porque ninguna celda tiene movimiento."""


def report_rows(report: DesignReport, *, unassigned_area_m2: float | None = None) -> list[Row]:
    """Las filas de ``des_rpt_`` (``quantity, value, unit_code, note``) del informe ``report``
    (``design.report.DesignReport``; RF-013-30): una por cifra con su unidad, en este orden —el
    desmonte y el terraplén, las celdas y el área con movimiento, las celdas y el área sin dato, el
    espesor mínimo, la inclinación p90, p99 y máxima, el lugar del máximo, el salto en el borde y
    las celdas que lo tocan—, el área sin sector si se da (``unassigned_area_m2``) y, al final, los
    avisos (``warning``) y las notas (``note``) con su código y sus valores en JSON, no su texto.
    Lo que no existe (sin celdas con movimiento no hay inclinación) es una fila sin valor con la
    nota :data:`NO_MOVEMENT_NOTE`; el lugar del máximo va en la nota como ``x;y`` en float64 en
    texto. Un valor NaN o infinito es un error del programa (``ValueError``): nada se escribe."""
    rows: list[Row] = []
    for key, unit in _REPORT_SCALARS:
        rows.append((key, _real(key, getattr(report, key)), unit, None))
    for key in _REPORT_SLOPES:
        value = getattr(report, key)
        rows.append((key, None, "deg", NO_MOVEMENT_NOTE) if value is None
                    else (key, _real(key, value), "deg", None))
    place = report.slope_max_at
    if place is not None:
        rows.append(("slope_max_at", None, "m",
                     f"{_real('slope_max_at.x', place.x)!r};{_real('slope_max_at.y', place.y)!r}"))
    for key, unit in _REPORT_EDGES:
        rows.append((key, _real(key, getattr(report, key)), unit, None))
    if unassigned_area_m2 is not None:
        rows.append(("unassigned_area_m2", _real("unassigned_area_m2", unassigned_area_m2), "m2",
                     None))
    for notice in report.notices:
        text = json.dumps({"code": notice.code, "values": dict(notice.values)}, sort_keys=True,
                          ensure_ascii=False, allow_nan=False, default=_plain)
        rows.append((notice.severity, None, None, text))
    return rows


def _names(columns: Sequence[ColumnDef]) -> tuple[str, ...]:
    return tuple(column.name for column in columns)


def _digest_steps(family: str, columns: Sequence[ColumnDef], rows: Sequence[Row], crs: CrsRef
                  ) -> Generator[None, None, ContentDigest]:
    """El hash (``core.gpkg_layer@1``) de la tabla ``family`` de columnas ``columns`` con
    ``rows``, en un GeoPackage en memoria con la misma estructura (R4: fuera de la transacción),
    por pasos: una unidad por cada trozo de filas que se inserta y por cada trozo que se lee y se
    hashea."""
    conn = sqlite3.connect(":memory:")
    try:
        create_base(conn, crs)
        create_attribute_table(conn, "digest", tuple(columns), "digest")
        names = _names(columns)
        for first in range(0, len(rows), _DIGEST_ROWS_PER_UNIT):
            insert_rows(conn, "digest", names, rows[first:first + _DIGEST_ROWS_PER_UNIT])
            yield
        request = core_builtin.GPKG_LAYER.request(
            provenance.FAMILIES_BY_CODE[family].kind, DATASET_DECLARATIONS,
            {"main": Path("digest")}, {"layer": "digest"}, normalizer=NORMALIZER)
        steps = core_builtin.layer_steps(conn, request)
        try:
            for _done in steps:
                yield
        finally:
            steps.close()
        return request.hasher.digest()
    finally:
        conn.close()


# --- La versión y el nombre ----------------------------------------------------------------------


def require_version(project: StoreProject, version: str | None, op_type: str) -> Version:
    """La versión ``version`` (uid o código) si es editable (RF-013-17, RF-009-21). Rechazos sin
    escribir nada: ``VersionError`` ``core.version_required`` sin versión activa,
    ``core.version_unknown`` si no existe y ``core.version_not_editable`` si está SUPERADA o
    DESCARTADA."""
    with project.read() as conn:
        return _editable(conn, version, op_type)


def _editable(conn: sqlite3.Connection, version: str | None, op_type: str) -> Version:
    """:func:`require_version` con la conexión de lectura ``conn``."""
    if version is None or not str(version).strip():
        raise VersionError("core.version_required", field="versión activa", value=version,
                           op_type=op_type)
    return versions_store.require_editable(conn, str(version))


def _check_name(conn: sqlite3.Connection, op_type: str, name: str, version: Version,
                replacing: str | None, parts: Sequence[str] = ()) -> None:
    """RF-013-17: ningún dato vigente de la versión tiene ya el nombre de alguna de las salidas de
    ``op_type`` para ``name`` (el mismo nombre en ASCII), salvo uno escrito por la operación
    ``replacing`` a la que sustituye la nueva. Con ``parts`` (un ajuste, T32: una salida de cada
    familia por parte), las salidas son las de ``f"{name} {parte}"``, y dos partes que dan el mismo
    nombre también se rechazan. ``DesignError`` ``des.operation_name_repeated``; ``GisError``
    ``gis.dataset_name_invalid`` si el nombre no tiene ninguna letra ni cifra."""
    labels = [f"{name} {part}" for part in parts] or [name]
    seen: set[str] = set()
    for family in provenance.OPERATION_TYPES_BY_NAME[op_type].outputs:
        for label in labels:
            dataset = provenance.dataset_name(family, label)
            record = dataset_registry.get(conn, dataset, version_uid=version.uid)
            if dataset in seen or (record is not None and record.live
                                   and record.operation_uid != replacing):
                raise DesignError("des.operation_name_repeated", obj=f"Operación «{name}»",
                                  field="nombre", value=name, dataset=dataset,
                                  version=version.code)
            seen.add(dataset)


# --- Empezar la operación -----------------------------------------------------------------------


def _require_current_masks(project: StoreProject, version: Version | str) -> None:
    """RF-013-04: las máscaras de ``version`` (su uid o la ``Version``) están al día; si no,
    ``MaskError`` (``core.constraint_masks_missing``/``_stale``/``_declared_new``) con la versión y la orden de
    compilar. Solo lee."""
    uid = version.uid if isinstance(version, Version) else version
    access.require_current(project, uid)  # MaskError, con su causa: también la de una declarada nueva (H-1)


@dataclass(frozen=True, slots=True, eq=False)
class OperationStart:
    """Lo que anota una operación de ``des`` al empezar (véase el módulo): su tipo y su nombre, la
    versión, los ajustes (JSON), las entradas, los parámetros que lee, las máscaras de las que
    parte (``None``: no parte de ninguna, como la declaración de restricciones de las entidades, que las
    deja obsoletas y no las consume: no se exige que estén al día) y el hash que tenía cada dato que
    consume cuando se preparó (``seen``: uid → hash)."""

    op_type: str
    name: str
    version_uid: str
    version_code: str
    settings: Mapping[str, Any]
    inputs: tuple[Use, ...]
    params: tuple[str, ...]
    masks: access.MaskSet | None
    seen: Mapping[str, str]
    supersedes: str | None = None
    parts: tuple[str, ...] = ()
    """Las partes de sus salidas, si escribe una de cada familia por parte (un ajuste, T32: la
    de cada superficie, ``provenance.refit_part``); ninguna, una salida por familia."""

    def check_masks(self, project: StoreProject) -> None:
        """RF-013-04: las máscaras de la versión siguen al día; si no, ``MaskError``
        (``core.constraint_masks_missing``/``_stale``), sin escribir nada. Solo lee. Una operación que no
        parte de máscaras (``masks`` ``None``) no lo comprueba."""
        if self.masks is None:
            return
        _require_current_masks(project, self.version_uid)

    def begin(self, project: StoreProject, *, conn: sqlite3.Connection | None = None,
              executor: str = "blender") -> OperationHandle:
        """Registra la operación «en curso» en la versión. Sin ``conn``, en su propia transacción
        (:func:`~core.provenance.operations.begin_operation`; las máscaras han de estar al día y,
        si lo que consume cambió desde que se preparó, la operación queda «fallida»). Con ``conn``
        (la transacción de escritura de quien confirma, :meth:`DesignWriter.commit`), en ella
        (``begin_in_transaction``): si algo falla, la transacción se deshace y no queda nada.
        Si sustituye a otra (:attr:`supersedes`, un recálculo, T15), puede quedarse con los nombres
        de sus datos.

        Rechazos, sin dejar nada: ``MaskError`` (máscaras que no están al día), ``DesignError``
        ``des.operation_name_repeated`` y ``des.input_changed``, y los de la 008/009
        (``VersionError``, ``ProvenanceError`` si un dato que consume ya no está vigente)."""
        values: dict[str, Any] = {
            "settings": dict(self.settings), "inputs": self.inputs, "params": self.params,
            "executor": executor, "supersedes": self.supersedes, "version": self.version_uid}
        if conn is not None:
            self._check_name(conn)
            handle = begin_in_transaction(conn, project, self.op_type, **values)
            self._check_unchanged(handle)
            return handle
        self.check_masks(project)
        with project.read() as reading:
            self._check_name(reading)
        handle = begin_operation(project, self.op_type, **values)
        try:
            self._check_unchanged(handle)
        except BaseException as error:
            handle.fail(failure_reason(error))
            raise
        return handle

    def _check_name(self, conn: sqlite3.Connection) -> None:
        version = versions_store.require_editable(conn, self.version_uid)
        _check_name(conn, self.op_type, self.name, version, self.supersedes, self.parts)

    def _check_unchanged(self, handle: OperationHandle) -> None:
        """RF-013-04, RF-013-17: cada dato que consume es el que había al prepararla, con su
        mismo contenido; si no (cambió mientras se calculaba), el resultado no le corresponde."""
        for item in handle.inputs:
            if item.kind is ItemKind.DATASET and self.seen.get(item.uid) != item.content_sha256:
                raise DesignError("des.input_changed", obj=f"Entrada «{item.name}»",
                                  field="entradas", value=item.name)


def _check_profiles(project: StoreProject, version: Version, codes: Iterable[str],
                    values: Iterable[BenchParam]) -> None:
    """RF-013-19: cada valor de ``values`` de cada perfil de ``codes`` tiene un valor dentro de su
    rango en la versión (el de la versión si lo tiene y, si no, el del proyecto o, sin fila, el
    de su definición: ninguno, salvo el factor de malla). Si no, ``DesignError``
    ``des.profile_value_missing`` o ``_range`` con el perfil (su nombre en ``des_bench_profile`` o,
    si no tiene fila, su código), la clave y el valor, antes de registrar nada: abrir la operación
    con un valor que falta crearía una fila vacía «sin confirmar» en el proyecto y calcularía con
    ella."""
    wanted = tuple(dict.fromkeys(codes))
    chosen = tuple(values)
    keys = tuple(bench_key(code, param) for code in wanted for param in chosen)
    with project.read() as conn:
        found = ParameterStore(project).resolve_many(
            conn, keys, (VERSION_SCOPE, PROJECT_SCOPE), version=version.uid)
        names = profile_names(conn)
    for code in wanted:
        for param in chosen:
            key = bench_key(code, param)
            resolved = found.get(key)
            if resolved is not None:
                value = None if resolved.value_json is None else json.loads(resolved.value_json)
            else:
                declared = definition(key)
                value = None if declared is None else declared.default
            check_bench_value(names.get(code, code), code, param, value)


def masks_steps(project: StoreProject, version: Version, masks: access.MaskSet | None, *,
                budget_s: float = STEP_BUDGET_S) -> Generator[Progress, None, access.MaskSet]:
    """Las máscaras de ``version`` por pasos de ``budget_s`` como mucho (``yield from``): las que se
    dan (que han de ser de esa versión y estar al día: ``MaskError``, ``ValueError``; sin pasos) o,
    sin ellas, las que da ``access.ensure_masks_steps`` (que compila antes, como operación propia,
    si no están al día, RF-013-04, y las carga). Se devuelven en ``StopIteration.value``."""
    if masks is not None:
        if masks.version_uid != version.uid:
            raise ValueError(f"las máscaras son de otra versión, no de {version.code}")
        _require_current_masks(project, version)
        return masks
    found: access.MaskSet = yield from pipeline.forward(
        access.ensure_masks_steps(project, version.uid, budget_s=budget_s))
    return found


def _loaded_masks(project: StoreProject, version: Version, masks: access.MaskSet | None
                  ) -> access.MaskSet:
    """:func:`masks_steps` de una vez (sin ceder el hilo)."""
    return _result_of(masks_steps(project, version, masks))


def _seen(conn: sqlite3.Connection, uses: Iterable[Use], version: Version) -> dict[str, str]:
    """El uid y el hash de contenido de cada dato que consumirán ``uses`` ahora (el de la
    versión antes que el del proyecto, como lo resuelve la 008)."""
    found: dict[str, str] = {}
    for use in uses:
        if use.kind is not ItemKind.DATASET:
            continue
        record = dataset_registry.get(conn, use.item, version_uid=version.uid)
        if record is None:
            record = dataset_registry.get(conn, use.item)
        if record is not None:
            found[record.uid] = record.content_sha256
    return found


def _start(project: StoreProject, op_type: str, name: str, version: Version,
           masks: access.MaskSet | None, settings: Mapping[str, Any], inputs: tuple[Use, ...],
           params: tuple[str, ...], supersedes: str | None, parts: Sequence[str] = ()
           ) -> OperationStart:
    with project.read() as conn:
        _check_name(conn, op_type, name, version, supersedes, parts)
        seen = MappingProxyType(_seen(conn, inputs, version))
    return OperationStart(op_type, name, version.uid, version.code, dict(settings), inputs,
                          params, masks, seen, supersedes, tuple(parts))


def request_profiles(request: EnvelopeRequest) -> tuple[str, ...]:
    """Los códigos de los perfiles que asigna ``request`` (el base y el de cada sector), sin
    repetir y en su orden: los que lee una envolvente por sectores."""
    return tuple(dict.fromkeys(
        [*([] if request.base_profile is None else [request.base_profile]),
         *(profile for _sector, profile in request.sector_profiles)]))


def prepare_envelope(project: StoreProject, request: EnvelopeRequest, *, version: str | None,
                     masks: access.MaskSet | None = None,
                     sectors: Sequence[DesignSector] | None = None,
                     profiles: Iterable[str] = (), pending_sectors: Iterable[str] = (),
                     touched_sectors: Iterable[str] = (),
                     supersedes: str | None = None) -> OperationStart:
    """Lo que anotará ``des.envelope`` para ``request`` en la versión ``version`` (uid o código)
    cuando se confirme, sin escribir nada (salvo compilar las máscaras si no están al día, que es
    una operación propia): los ajustes (con los ``pending_sectors`` y los ``touched_sectors`` que
    se guardan para la marca de RF-013-06), las entradas de ``design.provenance.envelope_inputs``
    con las máscaras (``masks``; sin ellas, las de ``access.ensure_masks_steps``) y los
    parámetros que lee (``envelope_params``: con pendiente por sectores, el talud general de los
    ``profiles`` que usa —por defecto, los que asigna la petición, :func:`request_profiles`— y
    los taludes impuestos de ``sectors``; por defecto, los de ``design_sectors``).
    ``supersedes``: la operación hecha a la que sustituye (un recálculo): puede quedarse con los
    nombres de sus datos.

    Rechazos: los de :func:`require_version`, ``DesignError`` ``des.profile_value_missing`` o
    ``_range`` si un perfil de los que lee no tiene un valor válido (RF-013-19: con pendiente por
    sectores, altura, cara, berma y factor de malla de los ``profiles``), ``MaskError`` si las
    máscaras que se dan ya no están al día, ``DesignError`` ``des.operation_name_repeated`` y
    ``GisError`` ``gis.dataset_name_invalid`` si el nombre no se puede usar."""
    found = require_version(project, version, provenance.ENVELOPE)
    codes = tuple(profiles) or request_profiles(request)
    if SlopeMode(request.slope_mode) is SlopeMode.SECTORS:
        _check_profiles(project, found, codes, provenance.ENVELOPE_PROFILE_PARAMS)
    loaded = _loaded_masks(project, found, masks)
    chosen = design_sectors(project, found.uid) if sectors is None else tuple(sectors)
    inputs = provenance.envelope_inputs(request, loaded.uses(), available_tables(project))
    params = provenance.envelope_params(request, profiles=codes,
                                        sector_slopes=slope_params(chosen))
    return _start(project, provenance.ENVELOPE, request.name, found, loaded,
                  provenance.envelope_settings(request, pending_sectors, touched_sectors), inputs,
                  params, supersedes)


def prepare_design(project: StoreProject, request: DesignRequest, surface: str, *,
                   version: str | None, masks: access.MaskSet | None = None,
                   sectors: Sequence[DesignSector] | None = None,
                   pending_sectors: Iterable[str] = (), touched_sectors: Iterable[str] = (),
                   previous: Mapping[str, Any] | None = None, supersedes: str | None = None
                   ) -> OperationStart:
    """Lo mismo que :func:`prepare_envelope` para ``des.stepped_design`` de ``request`` sobre la
    superficie de partida ``surface`` (el nombre de su dato): los ajustes de
    ``design_settings``, las entradas de ``design_inputs`` (la envolvente de la versión, la
    superficie, la rejilla de anclas, las máscaras, los sectores y las búsquedas) y los parámetros
    de ``design_params`` (los cinco valores de cada perfil que usa, los taludes de los sectores, las
    tolerancias y el espesor mínimo). ``previous``: lo que se vio de la revisión congelada más
    reciente (:func:`previous_comparison`), que se guarda en los ajustes. Un perfil sin valor, o
    fuera de rango, se rechaza antes de registrar nada (RF-013-19; véase
    :func:`prepare_envelope`)."""
    found = require_version(project, version, provenance.STEPPED)
    _check_profiles(project, found, [request.base_profile,
                                     *(profile for _sector, profile in request.sector_profiles)],
                    tuple(BenchParam))
    loaded = _loaded_masks(project, found, masks)
    chosen = design_sectors(project, found.uid) if sectors is None else tuple(sectors)
    inputs = provenance.design_inputs(request, surface, loaded.uses(), available_tables(project))
    params = provenance.design_params(request, sector_slopes=slope_params(chosen))
    return _start(project, provenance.STEPPED, request.name, found, loaded,
                  provenance.design_settings(request, surface, pending_sectors, touched_sectors,
                                             previous), inputs, params, supersedes)


def prepare_excavation_area(project: StoreProject, name: str, surface: str, *,
                            version: str | None, masks: access.MaskSet | None = None,
                            supersedes: str | None = None) -> OperationStart:
    """Lo mismo que :func:`prepare_envelope` para ``des.excavation_area`` (spec 014, T06;
    RF-014-01) de nombre ``name`` sobre la superficie de partida ``surface`` (el nombre de su
    dato): los ajustes de ``excavation_area_settings``, las entradas de
    ``excavation_area_inputs`` (la superficie y las máscaras de la versión) y ningún parámetro.
    Rechazos: los de :func:`require_version`, ``MaskError`` si las máscaras que se dan ya no están
    al día, ``DesignError`` ``des.operation_name_repeated`` y ``GisError``
    ``gis.dataset_name_invalid``."""
    found = require_version(project, version, provenance.EXCAVATION_AREA)
    loaded = _loaded_masks(project, found, masks)
    return _start(project, provenance.EXCAVATION_AREA, name, found, loaded,
                  provenance.excavation_area_settings(name, surface),
                  provenance.excavation_area_inputs(surface, loaded.uses()), (), supersedes)


def _quarry_keys(request: QuarryRequest) -> tuple[str, ...]:
    """Los parámetros de la 014 que lee la cantera ``request`` (los de ``quarry_params`` de
    ``design.params``): el anillo, el aviso de desdoblado, con zonas a conservar, su talud, y el
    salto y el porcentaje admitidos del salto creado de sus superficies (T56)."""
    return (CROWN_RING, UNSPLIT_THRESHOLD, UNSPLIT_MIN_AREA,
            *((CONSERVE_SLOPE,) if request.conserve else ()), *provenance.CREATED_STEP_PARAMS)


def _check_quarry_params(project: StoreProject, version: Version, request: QuarryRequest
                         ) -> None:
    """Como :func:`_check_profiles` para los parámetros de la 014 que lee la cantera: cada uno
    con un valor dentro de su rango en la versión (el de su fila o, sin ella, el de su
    definición). Si no, ``DesignError`` ``des.quarry_param_missing`` (el talud de conservación no
    tiene valor por defecto, D-9) o ``des.quarry_param_range``, antes de registrar nada."""
    _check_014_params(project, version, _quarry_keys(request))


def _check_014_params(project: StoreProject, version: Version, keys: tuple[str, ...]) -> None:
    """Los parámetros de la 014 ``keys``, cada uno con un valor dentro de su rango en la versión
    (véase :func:`_check_quarry_params`)."""
    with project.read() as conn:
        found = ParameterStore(project).resolve_many(
            conn, keys, (VERSION_SCOPE, PROJECT_SCOPE), version=version.uid)
    for key in keys:
        resolved = found.get(key)
        if resolved is not None:
            value = resolved.value
        else:
            declared = definition(key)
            value = None if declared is None else declared.default
        check_quarry_param(key, value)


def prepare_quarry(project: StoreProject, request: QuarryRequest, *, version: str | None,
                   masks: access.MaskSet | None = None,
                   sectors: Sequence[DesignSector] | None = None,
                   pending_sectors: Iterable[str] = (), touched_sectors: Iterable[str] = (),
                   previous: Mapping[Surface | str, Mapping[str, Any]] | None = None,
                   supersedes: str | None = None) -> OperationStart:
    """Lo mismo que :func:`prepare_design` para ``des.quarry`` (spec 014, T19; RF-014-29) de
    ``request``: los ajustes de ``quarry_settings`` (con los sectores pendientes y los que toca el
    recinto y lo ``previous`` con que se compara cada lado, :func:`_quarry_previous`, T51),
    las entradas de ``quarry_inputs`` (la superficie de partida, lo que leen los lados,
    las capas que usa, las máscaras, los sectores y las búsquedas) y los parámetros de
    ``quarry_params`` (los cinco valores de los perfiles de los dos lados, los taludes de los
    sectores, los de la 014 y los de la 013). Un perfil o un parámetro de la 014 sin valor, o fuera
    de rango, se rechaza antes de registrar nada (RF-013-19; ``des.quarry_param_missing`` o
    ``_range``)."""
    found = require_version(project, version, provenance.QUARRY)
    _check_profiles(project, found, provenance.quarry_profiles(request), tuple(BenchParam))
    _check_quarry_params(project, found, request)
    loaded = _loaded_masks(project, found, masks)
    chosen = design_sectors(project, found.uid) if sectors is None else tuple(sectors)
    inputs = provenance.quarry_inputs(request, loaded.uses(), available_tables(project))
    params = provenance.quarry_params(request, sector_slopes=slope_params(chosen))
    return _start(project, provenance.QUARRY, request.name, found, loaded,
                  provenance.quarry_settings(request, pending_sectors, touched_sectors, previous),
                  inputs, params, supersedes)


def prepare_edge_transition(project: StoreProject, name: str, surface: str, start: str, *,
                            version: str | None, masks: access.MaskSet | None = None,
                            supersedes: str | None = None) -> OperationStart:
    """Lo mismo que :func:`prepare_envelope` para ``des.edge_transition`` (spec 014, T28;
    RF-014-19, RF-014-29) de nombre ``name`` con la superficie de diseño ``surface`` y la de
    partida ``start`` (los nombres de sus datos): los ajustes de ``transition_settings``, las
    entradas de ``transition_inputs`` (las dos superficies y las máscaras de la versión) y los
    parámetros de ``TRANSITION_PARAMS``. El ángulo de transición sin valor (no lo tiene por
    defecto, D-9), o un parámetro fuera de rango, se rechaza antes de registrar nada
    (``des.quarry_param_missing`` o ``_range``); además, los rechazos de :func:`prepare_envelope`
    de la versión, las máscaras y el nombre."""
    found = require_version(project, version, provenance.EDGE_TRANSITION)
    _check_014_params(project, found, (EDGE_TRANSITION_DEG, EDGE_MAX_STEP, EDGE_MIN_SHARE))
    loaded = _loaded_masks(project, found, masks)
    return _start(project, provenance.EDGE_TRANSITION, name, found, loaded,
                  provenance.transition_settings(name, surface, start),
                  provenance.transition_inputs(surface, start, loaded.uses()),
                  provenance.TRANSITION_PARAMS, supersedes)


def prepare_fill_only(project: StoreProject, request: FillOnlyRequest, *, version: str | None,
                      masks: access.MaskSet | None = None,
                      sectors: Sequence[DesignSector] | None = None,
                      pending_sectors: Iterable[str] = (), touched_sectors: Iterable[str] = (),
                      previous: Mapping[str, Any] | None = None, supersedes: str | None = None
                      ) -> OperationStart:
    """Lo mismo que :func:`prepare_design` para ``des.fill_only`` (spec 014, T30; RF-014-22,
    RF-014-29) de ``request``: los ajustes de ``fill_only_settings`` (los del escalonado sin el
    sentido, con la capa de láminas), las entradas de ``fill_only_inputs`` (las del escalonado y
    la capa de láminas) y los parámetros del escalonado de la 013 (``design_params``: los cinco
    valores de cada perfil que usa, los taludes de los sectores, las tolerancias y el espesor
    mínimo; ninguno de la cantera) más el salto y el porcentaje admitidos del salto creado de su
    superficie (``provenance.CREATED_STEP_PARAMS``, T56). Un perfil sin valor, o fuera de rango, o
    uno de esos dos fuera de su rango, se rechaza antes de registrar nada (RF-013-19;
    ``des.quarry_param_range``)."""
    found = require_version(project, version, provenance.FILL_ONLY)
    _check_profiles(project, found, [request.base_profile,
                                     *(profile for _sector, profile in request.sector_profiles)],
                    tuple(BenchParam))
    _check_014_params(project, found, provenance.CREATED_STEP_PARAMS)
    loaded = _loaded_masks(project, found, masks)
    chosen = design_sectors(project, found.uid) if sectors is None else tuple(sectors)
    inputs = provenance.fill_only_inputs(request, loaded.uses(), available_tables(project))
    params = (*provenance.design_params(request.design, sector_slopes=slope_params(chosen)),
              *provenance.CREATED_STEP_PARAMS)
    return _start(project, provenance.FILL_ONLY, request.name, found, loaded,
                  provenance.fill_only_settings(request, pending_sectors, touched_sectors,
                                                previous), inputs, params, supersedes)


REFIT_SOURCES: tuple[str, ...] = (provenance.STEPPED, provenance.QUARRY,
                                  provenance.EDGE_TRANSITION, provenance.FILL_ONLY,
                                  provenance.REFIT)
"""Los tipos de operación cuyas superficies de diseño se ajustan a un límite nuevo (spec 014, T32;
RF-014-27): las de la 014 que comprueba la T31 (:data:`LIMIT_CHECKED_TYPES`) y la de un
escalonado de la 013, todas con un perfil del que sale su cara (P-3)."""
_SOURCE_DEPTH = 32
"""Cuántas superficies se siguen como mucho hasta la que tiene perfil (una transición de un ajuste
de un ajuste…): más es un error del programa."""


def _not_design_surface(surface: str) -> DesignError:
    return DesignError("des.edge_not_design_surface", obj=f"Superficie «{surface}»",
                       field="superficie de diseño", value=surface)


def _profile_origin(conn: sqlite3.Connection, origin: SurfaceOrigin, version_uid: str
                    ) -> SurfaceOrigin:
    """La superficie de diseño de la que sale el perfil de ``origin`` (véase
    :func:`refit_profiles`): ella misma si la escribió una cantera (su explotación o su final), un
    escalonado de la 013 o «solo relleno»; si la escribió una transición o un ajuste, la de la
    superficie de la que salen, hasta llegar a una de esas. Solo lee."""
    exploitation = provenance.FAMILIES_BY_CODE[provenance.EXPLOITATION_GRID].prefix
    final = provenance.FAMILIES_BY_CODE[provenance.FINAL_GRID].prefix
    current = origin
    for _depth in range(_SOURCE_DEPTH):
        name, op_type, settings = current.record.name, current.op_type, current.settings
        source: str | None
        if (op_type == provenance.QUARRY and name.startswith((exploitation, final))) \
                or op_type in (provenance.STEPPED, provenance.FILL_ONLY):
            return current
        if op_type == provenance.EDGE_TRANSITION:
            source = provenance.transition_start(settings)[1]
        elif op_type == provenance.REFIT:
            source = provenance.refit_source(settings, name)
        else:
            raise _not_design_surface(name)
        found = None if source is None else design_surface_of(conn, source, version_uid)
        if found is None:
            raise _not_design_surface(name if source is None else source)
        current = found
    raise ValueError(f"«{origin.record.name}» sale de más de {_SOURCE_DEPTH} superficies")


def _origin_profiles(origin: SurfaceOrigin) -> tuple[str, tuple[tuple[str, str], ...]]:
    """El perfil base y el de cada sector de la superficie ``origin`` que escribió una cantera, un
    escalonado de la 013 o «solo relleno» (:func:`_profile_origin`), de los ajustes de su
    operación."""
    name, op_type, settings = origin.record.name, origin.op_type, origin.settings
    if op_type == provenance.QUARRY:
        exploitation = provenance.FAMILIES_BY_CODE[provenance.EXPLOITATION_GRID].prefix
        side = provenance.quarry_request(settings).side(
            Surface.EXPLOITATION if name.startswith(exploitation) else Surface.FINAL)
        return side.base_profile, tuple(side.sector_profiles)
    if op_type == provenance.STEPPED:
        stepped = provenance.design_request(settings)
        return stepped.base_profile, tuple(stepped.sector_profiles)
    filled = provenance.fill_only_request(settings)
    return filled.base_profile, tuple(filled.sector_profiles)


def refit_profiles(conn: sqlite3.Connection, origin: SurfaceOrigin, version_uid: str
                   ) -> tuple[str, tuple[tuple[str, str], ...]]:
    """El perfil base y el de cada sector (código del sector → código del perfil, en pares
    ordenados) de la superficie de diseño ``origin`` de la versión ``version_uid`` (spec 014, T32;
    RF-014-27, P-3: el ángulo del ajuste sale del perfil de la operación que creó la superficie):
    de una cantera, los del lado de la superficie (``des_exp_``, la explotación; ``des_fin_``, la
    final); de un escalonado de la 013 o de «solo relleno», los suyos; de una transición o de un
    ajuste, los de la superficie de la que salen (que ha de seguir siendo una superficie de diseño
    de la versión). ``DesignError`` ``des.edge_not_design_surface`` nombrando la superficie si no es
    de uno de :data:`REFIT_SOURCES` o aquella de la que sale ya no lo es; ``ValueError`` si los
    ajustes de su operación no son los de su tipo. Solo lee."""
    return _origin_profiles(_profile_origin(conn, origin, version_uid))


def _recorded_faces(conn: sqlite3.Connection, surface: str, origin: SurfaceOrigin,
                    codes: Iterable[str], names: Mapping[str, str]) -> dict[str, object]:
    """La cara y el factor de malla (:data:`~geoblender.design.provenance.REFIT_PROFILE_PARAMS`)
    de cada perfil de ``codes`` que **anotó** la operación que escribió el contenido de hoy de
    ``origin`` (``gb_operation_param``; clave ``des.bench.{p}.…`` → valor), la que hizo el diseño
    de la superficie ``surface`` que se ajusta (spec 014, T49, hallazgo F-10; plan A13, P-3: no los
    de hoy). Si no anotó alguno, ``DesignError`` ``des.refit_face_missing`` nombrando ``surface``,
    el perfil (su nombre de ``names`` o su código) y la clave. Solo lee."""
    rows = {str(key): value for key, value in conn.execute(
        "SELECT key, value FROM gb_operation_param WHERE operation_uid = ?",
        (origin.operation_uid,))}
    found: dict[str, object] = {}
    for code in dict.fromkeys(codes):
        for param in provenance.REFIT_PROFILE_PARAMS:
            key = bench_key(code, param)
            if key not in rows:
                raise DesignError("des.refit_face_missing", obj=f"Superficie «{surface}»",
                                  field=key, value=origin.record.name, surface=surface,
                                  profile=names.get(code, code))
            text = rows[key]
            found[key] = None if text is None else json.loads(text)
    return found


def _quarry_link(made: SurfaceOrigin) -> tuple[str, Surface | None, Order | None]:
    """De qué cantera sale la superficie cuyo perfil es el de ``made`` (:func:`_profile_origin`;
    T53, RF-014-14): el nombre de la cantera, su lado (``des_exp_``, la explotación;
    ``des_fin_``, la final) y el orden del diseño, de los ajustes de su operación; ``("", None,
    None)`` si no la escribió una cantera. Solo lee los ajustes."""
    if made.op_type != provenance.QUARRY:
        return "", None, None
    request = provenance.quarry_request(made.settings)
    exploitation = provenance.FAMILIES_BY_CODE[provenance.EXPLOITATION_GRID].prefix
    side = Surface.EXPLOITATION if made.record.name.startswith(exploitation) else Surface.FINAL
    return request.name, side, Order(request.order)


def _design_name(made: SurfaceOrigin) -> str:
    """El nombre del diseño que escribió ``made`` (una cantera, un escalonado de la 013 o «solo
    relleno»: :func:`_profile_origin`), de los ajustes de su operación."""
    if made.op_type == provenance.QUARRY:
        return provenance.quarry_request(made.settings).name
    if made.op_type == provenance.STEPPED:
        return provenance.design_request(made.settings).name
    return provenance.fill_only_request(made.settings).name


def _stale_designs(conn: sqlite3.Connection, surfaces: Iterable[str], version_uid: str
                   ) -> tuple[Notice, ...]:
    """**El ajuste frente a lo obsoleto del diseño del que sale** (T54; RF-014-27, RF-014-31,
    hallazgo F-16; la propuesta por defecto (b) que aceptó Samuel): de cada superficie de
    ``surfaces`` (superficies de diseño de la versión ``version_uid``), el diseño que la hizo
    (:func:`_profile_origin`: su cantera, su escalonado de la 013 o su «solo relleno», también
    a través de una transición o de un ajuste) y, si la operación que lo escribió está obsoleta
    en la caché de la 008 (``core.provenance.stale.item_causes``; con un límite nuevo, por las
    máscaras), el aviso ``design.refit.SOURCE_STALE_CODE``: «Recalcular lo obsoleto» lo vuelve a
    calcular con el límite vigente y rehace después el ajuste sobre él, que sustituye al que se
    cree. Uno por diseño, con sus superficies en el orden de la petición. Solo lee."""
    found: dict[str, tuple[str, list[str]]] = {}
    for surface in surfaces:
        origin = design_surface_of(conn, surface, version_uid)
        if origin is None:  # ya rechazada por _refit_sources
            continue
        made = _profile_origin(conn, origin, version_uid)
        uid = made.operation_uid
        if uid in found:
            found[uid][1].append(surface)
        elif uid and item_causes(conn, STALE_OPERATION, uid):
            found[uid] = (_design_name(made), [surface])
    return tuple(Notice(refit.SOURCE_STALE_CODE, {
        "design": name, "surfaces": ", ".join(f"«{item}»" for item in listed)})
        for name, listed in found.values())


def _refit_sources(conn: sqlite3.Connection, request: RefitRequest, version_uid: str,
                   names: Mapping[str, str]
                   ) -> list[tuple[str, str, tuple[tuple[str, str], ...], dict[str, object],
                                   tuple[str, Surface | None, Order | None]]]:
    """Cada superficie de ``request`` con su perfil base y el de cada sector
    (:func:`refit_profiles`), la cara y el factor de malla de esos perfiles que anotó la
    operación que hizo su diseño (:func:`_recorded_faces`, T49), comprobados como en
    ``design.refit.ProfileFace`` (``names``, código → nombre, para los mensajes), y la cantera de
    la que sale con su lado y su orden (:func:`_quarry_link`, T53). Rechazos:
    ``des.edge_not_design_surface`` si alguna no es una superficie de diseño de la versión de
    :data:`REFIT_SOURCES`; ``des.refit_face_missing`` si esa operación no anotó alguno;
    ``des.profile_value_missing`` o ``_range`` si anotó uno sin valor o fuera de rango. Solo
    lee."""
    found = []
    for surface in request.surfaces:
        origin = design_surface_of(conn, surface, version_uid)
        if origin is None or origin.op_type not in REFIT_SOURCES:
            raise _not_design_surface(surface)
        made = _profile_origin(conn, origin, version_uid)
        base, sectors = _origin_profiles(made)
        codes = (base, *(profile for _sector, profile in sectors))
        values = _recorded_faces(conn, surface, made, codes, names)
        refit.profile_faces(values, codes, names)  # una cara sin valor o fuera de rango
        found.append((surface, base, sectors, values, _quarry_link(made)))
    return found


def prepare_refit(project: StoreProject, request: RefitRequest, *, version: str | None,
                  masks: access.MaskSet | None = None,
                  faces: Mapping[str, Mapping[str, object]] | None = None,
                  supersedes: str | None = None) -> OperationStart:
    """Lo mismo que :func:`prepare_envelope` para ``des.refit`` (spec 014, T32; RF-014-27,
    RF-014-29) de ``request``: los ajustes de ``refit_settings`` (el nombre, las superficies, la
    de partida y la cara y el factor de malla de cada superficie, ``faces``: superficie → clave →
    valor; sin ellas, los que anotó la operación que hizo el diseño de cada una, T49), las entradas
    de ``refit_inputs`` (cada superficie, la de partida, las máscaras —el límite nuevo— y los
    sectores) y los parámetros de ``refit_params`` (el espesor mínimo y el salto y el porcentaje
    admitidos del salto creado, T56: la cara y el factor de malla no se leen del perfil de hoy,
    P-3). El nombre se mira en cada salida
    (``des_adj_<nombre>_<superficie>``, ``provenance.refit_output``). Rechazos, antes de registrar
    nada: los de :func:`prepare_envelope` de la versión, las máscaras y el nombre;
    ``des.edge_not_design_surface`` si una superficie no es de diseño de la versión; y, sin
    ``faces``, los de lo que anotó la operación de cada diseño (``des.refit_face_missing``, una
    cara o un factor de malla sin valor o fuera de rango, RF-013-19); el salto o el porcentaje
    admitidos fuera de su rango (``des.quarry_param_range``)."""
    found = require_version(project, version, provenance.REFIT)
    _check_014_params(project, found, provenance.CREATED_STEP_PARAMS)
    if faces is None:
        with project.read() as conn:
            sources = _refit_sources(conn, request, found.uid, profile_names(conn))
        faces = {surface: values for surface, _base, _sectors, values, _link in sources}
    loaded = _loaded_masks(project, found, masks)
    return _start(project, provenance.REFIT, request.name, found, loaded,
                  provenance.refit_settings(request, faces),
                  provenance.refit_inputs(request, loaded.uses(), available_tables(project)),
                  provenance.refit_params(), supersedes,
                  [provenance.refit_part(surface) for surface in request.surfaces])


def begin_envelope(project: StoreProject, request: EnvelopeRequest, *, version: str | None,
                   masks: access.MaskSet | None = None,
                   sectors: Sequence[DesignSector] | None = None, profiles: Iterable[str] = (),
                   pending_sectors: Iterable[str] = (), touched_sectors: Iterable[str] = (),
                   supersedes: str | None = None, executor: str = "blender") -> OperationHandle:
    """Registra ``des.envelope`` «en curso» en la versión ``version`` (:func:`prepare_envelope` y
    :meth:`OperationStart.begin` en su propia transacción): el recálculo de una obsoleta
    (``supersedes``), que completa :meth:`DesignWriter.resume`. Confirmar un cálculo no pasa por
    aquí: :meth:`DesignWriter.commit` abre la operación en su transacción."""
    start = prepare_envelope(project, request, version=version, masks=masks, sectors=sectors,
                             profiles=profiles, pending_sectors=pending_sectors,
                             touched_sectors=touched_sectors, supersedes=supersedes)
    return start.begin(project, executor=executor)


def begin_design(project: StoreProject, request: DesignRequest, surface: str, *,
                 version: str | None, masks: access.MaskSet | None = None,
                 sectors: Sequence[DesignSector] | None = None,
                 pending_sectors: Iterable[str] = (), touched_sectors: Iterable[str] = (),
                 previous: Mapping[str, Any] | None = None, supersedes: str | None = None,
                 executor: str = "blender") -> OperationHandle:
    """Lo mismo que :func:`begin_envelope` para ``des.stepped_design`` (:func:`prepare_design`)."""
    start = prepare_design(project, request, surface, version=version, masks=masks,
                           sectors=sectors, pending_sectors=pending_sectors,
                           touched_sectors=touched_sectors, previous=previous,
                           supersedes=supersedes)
    return start.begin(project, executor=executor)


# --- Escribir el resultado ----------------------------------------------------------------------


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _disk_error(name: str, error: OSError) -> GisError:
    if isinstance(error, PermissionError):
        return writer.target_locked(name)
    return writer.write_failed(name, error)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND "
                        "lower(name) = lower(?)", (name,)).fetchone() is not None


@dataclass(slots=True)
class _Grid:
    """Una rejilla preparada: su declaración (con el hash), su destino, su temporal y dónde se
    aparta la anterior; si ya está en su sitio y si apartó una."""

    family: str
    spec: DatasetSpec
    final: Path
    temporary: Path
    backup: Path
    installed: bool = False
    replaced: bool = False


@dataclass(frozen=True, slots=True)
class _Table:
    family: str
    spec: DatasetSpec
    rows: tuple[Row, ...]


@dataclass(frozen=True, slots=True)
class _Declared:
    """La tabla de las restricciones declaradas por las entidades preparada: su declaración (sin hash: la
    operación lo calcula al registrarla, de lo escrito en su transacción) y sus filas."""

    spec: DatasetSpec
    rows: tuple[DeclaredConstraint, ...]


@dataclass(frozen=True, slots=True, eq=False)
class Stored:
    """Lo guardado: la operación (``OperationHandle``, ya completada) y sus salidas registradas,
    en el orden de su tipo."""

    handle: OperationHandle
    records: tuple[DatasetRecord, ...]


class DesignWriter:
    """El resultado de **una** operación de ``des`` (``op_type``, con el ``name`` de la operación)
    en la versión ``version`` (véase el módulo): se prepara cada salida de su tipo con
    :meth:`grid_steps` y :meth:`table_steps`, y :meth:`commit` las registra. Se usa como gestor de
    contexto: al salir sin haber confirmado, borra los temporales (y, de una operación que ya
    empezó, la deja «cancelada» o «fallida»). ``supersedes``: la operación hecha a la que
    sustituye la nueva (puede quedarse con los nombres de sus datos). Rechaza al crearlo lo que no
    se puede escribir (:func:`require_version`; ``des.operation_name_repeated``)."""

    def __init__(self, project: StoreProject, op_type: str, name: str, *, version: str | None,
                 supersedes: str | None = None, handle: OperationHandle | None = None) -> None:
        found = provenance.OPERATION_TYPES_BY_NAME.get(op_type)
        if found is None:
            raise ValueError(f"«{op_type}» no es un tipo de operación del diseño: es uno de "
                             f"{', '.join(provenance.OPERATION_TYPES_BY_NAME)}")
        if handle is not None and (not isinstance(handle, OperationHandle)
                                   or handle.op_type != op_type):
            raise ValueError(f"la operación empezada no es una {op_type}")
        self.project = project
        self.op_type = op_type
        self.name = name
        self.handle = handle
        self.supersedes = supersedes if handle is None else handle.supersedes
        self._type = found
        with project.read() as conn:
            record = _editable(conn, version, op_type)
            _check_name(conn, op_type, name, record, self.supersedes)
        self.version_uid = record.uid
        self.version_code = record.code
        self.crs, self.vertical = project_references(project)
        self._grids: dict[str, _Grid] = {}
        self._tables: dict[str, _Table] = {}
        self._vectors: dict[str, _Declared] = {}
        self._committed = self._closed = False

    @classmethod
    def resume(cls, project: StoreProject, handle: OperationHandle) -> DesignWriter:
        """El escritor de una operación de ``des`` que ya está «en curso» (``handle``, de
        :func:`begin_envelope` o :func:`begin_design`; su nombre y su versión salen de ella):
        :meth:`commit` la completa en vez de abrir otra."""
        if not isinstance(handle, OperationHandle):
            raise TypeError(f"se reanuda un OperationHandle, no {handle!r}")
        name = handle.settings.get("name")
        if not isinstance(name, str):
            raise ValueError(f"la operación {handle.uid} no lleva su nombre en los ajustes")
        return cls(project, handle.op_type, name, version=handle.version_uid, handle=handle)

    def __enter__(self) -> DesignWriter:
        return self

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None,
                 traceback: TracebackType | None) -> None:
        self.close(error)

    # --- Preparar --------------------------------------------------------------------------

    def _produces(self, family: str, kind: str, key: str | None = None) -> None:
        if self._closed or self._committed:
            raise RuntimeError("el escritor ya se confirmó o se cerró")
        if family not in self._type.outputs:
            raise ValueError(f"«{self.op_type}» no escribe la familia «{family}»: escribe "
                             f"{', '.join(self._type.outputs)}")
        found = provenance.FAMILIES_BY_CODE[family].kind
        if found != kind:
            raise ValueError(f"la familia «{family}» es {_KIND_ES.get(found, found)}, no "
                             f"{_KIND_ES.get(kind, kind)}")
        wanted = family if key is None else key
        if wanted in self._grids or wanted in self._tables or wanted in self._vectors:
            raise ValueError(f"la salida «{wanted}» ya está preparada")

    def _check_place(self, conn: sqlite3.Connection, spec: DatasetSpec) -> None:
        """Su sitio está libre o es del mismo dato vigente (una operación que lo sustituye)."""
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

    def grid_steps(self, family: str, raster: Raster, *, part: str | None = None
                   ) -> Generator[None, None, DatasetSpec]:
        """Prepara la rejilla ``raster`` como la salida ``family`` (``env``, ``srf`` o ``brm``) de
        la operación: su hash por bandas de filas y su GeoTIFF del perfil ``project`` (los mismos
        bits, también los NaN) en su temporal junto a su destino, **sin registrar nada**. Una
        unidad por banda de hash y por tesela; devuelve su ``DatasetSpec`` (con el hash) en
        ``StopIteration.value``. Cerrarlo a mitad borra el temporal. Con ``part`` (un ajuste, T32:
        una rejilla de la familia por superficie), el dato es el de ``f"{nombre} {part}"``, y la
        familia puede tener varias. Se rechaza **al llamar** (errores del programa: ``ValueError``
        si la familia no es una rejilla de su tipo, ya está preparada o el ráster no va en el CRS
        y la referencia vertical del proyecto)."""
        key = None if part is None else f"{family}/{part}"
        self._produces(family, "raster", key)
        if not isinstance(raster, Raster):
            raise TypeError(f"se escribe un Raster, no {type(raster).__name__}")
        if raster.crs.epsg != self.crs.epsg or raster.vertical != self.vertical:
            raise ValueError(
                f"«{self.name}» va en el CRS y la referencia vertical del proyecto (EPSG:"
                f"{self.crs.epsg}), no en EPSG:{raster.crs.epsg}: remuestréela antes")
        return self._grid_steps(family, raster, part)

    def _grid_steps(self, family: str, raster: Raster, part: str | None = None
                    ) -> Generator[None, None, DatasetSpec]:
        label = self.name if part is None else f"{self.name} {part}"
        planned = provenance.dataset_spec(family, label, self.version_code)
        final = Path(self.project.root, *planned.locator.split("/"))
        temporary = temporary_path(self.project, final)
        backup = backup_path(self.project, final)
        for path in (temporary, backup):
            check_path_length(path, obj=final.name)
        with self.project.read() as conn:
            self._check_place(conn, planned)
        try:
            final.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise writer.write_failed(final.name, error) from None
        hasher = ContentHasher("raster", declarations=DATASET_DECLARATIONS, reader=GEOTIFF.id,
                               normalizer=NORMALIZER)
        feed = hasher.begin_grid(raster_header(raster))
        rows, columns = raster.grid.shape
        band = max(1, _HASH_BLOCK_CELLS // max(1, columns))
        for start in range(0, rows, band):
            feed.update(raster.values[start:start + band])
            yield
        feed.finish()
        steps = writer.write_steps(raster, final, profile="project", temporary=temporary,
                                   replace=False)
        with closing(steps):  # cerrar o fallar a mitad borra el temporal
            while True:
                try:
                    next(steps)
                except StopIteration:
                    break
                yield
        spec = provenance.dataset_spec(family, label, self.version_code,
                                       content=hasher.digest(), crs_epsg=self.crs.epsg)
        self._grids[family if part is None else f"{family}/{part}"] = _Grid(
            family, spec, final, temporary, backup)
        if self.handle is not None:
            self.handle.claim_paths(temporary, final, backup)
        return spec

    def table_steps(self, family: str, rows: Iterable[Sequence[Any]]
                    ) -> Generator[None, None, DatasetSpec]:
        """Prepara la tabla ``family`` (``bmt``, ``rpt``…; las de la 015, ``epr`` y ``prp``) con
        ``rows`` (:func:`berm_rows`, :func:`report_rows`…): su hash en un GeoPackage en memoria, por
        trozos de filas, **sin registrar nada**. Devuelve su ``DatasetSpec`` (con el hash) en
        ``StopIteration.value``.
        Se rechaza al llamar, como :meth:`grid_steps`, y una fila con otro número de columnas."""
        self._produces(family, "table")
        chosen = tuple(tuple(row) for row in rows)
        width = len(columns_of(self.op_type, family))
        for row in chosen:
            if len(row) != width:
                raise ValueError(f"una fila de «{family}» lleva {width} columnas, no {len(row)}")
        return self._table_steps(family, chosen)

    def _table_steps(self, family: str, rows: tuple[Row, ...]
                     ) -> Generator[None, None, DatasetSpec]:
        planned = provenance.dataset_spec(family, self.name, self.version_code)
        with self.project.read() as conn:
            self._check_place(conn, planned)
        digest = yield from _digest_steps(family, columns_of(self.op_type, family), rows,
                                          self.crs)
        spec = provenance.dataset_spec(family, self.name, self.version_code, content=digest)
        self._tables[family] = _Table(family, spec, rows)
        return spec

    def declared_steps(self, rows: Iterable[DeclaredConstraint]
                       ) -> Generator[None, None, DatasetSpec]:
        """Prepara la tabla de las restricciones declaradas por las entidades (``decl``; spec 015, T17;
        RF-015-10, RF-012-29) con ``rows`` (todas las de la versión: la tabla se reescribe **entera**,
        ``core.constraints.declared.write_declared``), **sin registrar nada**: una capa de polígonos del
        GeoPackage del proyecto, no editable en QGIS (RF-008-56), de la que la operación calcula el hash al
        registrarla (es pequeña: una fila por entidad que protege). Devuelve su ``DatasetSpec`` en
        ``StopIteration.value``. Se rechaza al llamar, como :meth:`table_steps` (``ValueError``; ``TypeError``
        si una fila no es una ``DeclaredConstraint``); dos filas que repiten el código o el ``uid`` o un
        código que usan las capas del proyecto los rechaza :func:`write_declared` al confirmar, sin escribir
        nada."""
        self._produces(provenance.DECLARED_TABLE, "vector")
        chosen = tuple(rows)
        for item in chosen:
            if not isinstance(item, DeclaredConstraint):
                raise TypeError(f"una fila de las declaradas es una DeclaredConstraint, no {item!r}")
        return self._declared_steps(chosen)

    def _declared_steps(self, rows: tuple[DeclaredConstraint, ...]) -> Generator[None, None, DatasetSpec]:
        planned = provenance.dataset_spec(provenance.DECLARED_TABLE, "", self.version_code,
                                          crs_epsg=self.crs.epsg)
        with self.project.read() as conn:
            self._check_place(conn, planned)
        yield
        self._vectors[provenance.DECLARED_TABLE] = _Declared(planned, rows)
        return planned

    @property
    def specs(self) -> tuple[DatasetSpec, ...]:
        """Las salidas preparadas, en el orden de su tipo (las de una familia con partes, en el
        orden en que se prepararon)."""
        found: list[DatasetSpec] = []
        for family in self._type.outputs:
            found += [grid.spec for grid in self._grids.values() if grid.family == family]
            if family in self._tables:
                found.append(self._tables[family].spec)
            if family in self._vectors:
                found.append(self._vectors[family].spec)
        return tuple(found)

    # --- Confirmar -------------------------------------------------------------------------

    def _paths(self) -> list[Path]:
        return [path for grid in self._grids.values()
                for path in (grid.temporary, grid.final, grid.backup)]

    def _install(self) -> None:
        for grid in self._grids.values():
            if grid.final.exists():
                try:
                    os.replace(grid.final, grid.backup)
                except OSError as error:
                    raise _disk_error(grid.final.name, error) from None
                grid.replaced = True
            try:
                os.replace(grid.temporary, grid.final)
            except OSError as error:
                failure = _disk_error(grid.final.name, error)
                self._restore(grid)
                raise failure from None
            grid.installed = True

    @staticmethod
    def _restore(grid: _Grid) -> None:
        if grid.replaced:
            try:
                os.replace(grid.backup, grid.final)
                grid.replaced = False
            except OSError:
                pass

    def _write_table(self, conn: sqlite3.Connection, table: _Table) -> None:
        spec = table.spec
        self._check_place(conn, spec)
        columns = columns_of(self.op_type, table.family)
        if _table_exists(conn, spec.locator):
            conn.execute(f'DELETE FROM "{spec.locator}"')
        else:
            label = provenance.FAMILIES_BY_CODE[table.family].label
            create_attribute_table(
                conn, spec.locator, columns,
                f"{label} {self.name} {self.version_code}",
                f"{label} «{self.name}» de la versión {self.version_code}, de Geoblender")
        insert_rows(conn, spec.locator, _names(columns), table.rows)

    def _write_declared(self, conn: sqlite3.Connection, declared: _Declared) -> None:
        self._check_place(conn, declared.spec)
        write_declared(conn, declared.spec.locator, declared.rows, srs_id=self.crs.epsg)

    def commit(self, start: OperationStart | None = None, *, figures: Sequence[FigureSpec] = (),
               message: str | None = None,
               before_begin: Callable[[sqlite3.Connection], object] | None = None) -> Stored:
        """Registra el resultado, en **una** transacción de escritura: abre la operación
        (``start``, :meth:`OperationStart.begin`; no hace falta si el escritor se reanudó con una
        operación que ya empezó), reclama las rutas, pone las rejillas en su sitio, escribe las
        tablas y completa con ``figures`` y ``message``. Antes, fuera de la transacción, comprueba
        que las máscaras siguen al día (RF-013-04). Si algo falla, o lo que consume cambió desde que
        se preparó, deshace todo (no quedan operación, dato, tabla, cifra, rejilla en su sitio ni
        temporal) y el error sigue. Errores del programa (``ValueError``): faltan salidas de su
        tipo, o ``start`` no es de esta operación (o se da con una ya empezada, o falta).

        ``before_begin`` (spec 015, T13): una función que se llama **con la conexión de esa
        transacción, antes de abrir la operación**, para escribir en ella lo que la operación ha de
        leer al empezar (los parámetros de una entidad de diseño, que ``begin_operation`` crearía
        en el proyecto si faltaran: trampa de la T04). Si falla, o falla algo después, se deshace
        con todo lo demás. Sin ella (la 013 y la 014), no hace nada."""
        if self._closed or self._committed:
            raise RuntimeError("el escritor ya se confirmó o se cerró")
        self._check_ready(start)  # un error del programa no cierra el escritor
        try:
            if start is not None:
                start.check_masks(self.project)
            with self.project.write_transaction() as conn:
                if before_begin is not None:
                    before_begin(conn)
                handle = self.handle
                if handle is None:
                    assert start is not None
                    handle = start.begin(self.project, conn=conn)
                handle.claim_paths(*self._paths())
                self._install()
                for table in self._tables.values():
                    self._write_table(conn, table)
                for declared in self._vectors.values():
                    self._write_declared(conn, declared)
                records = handle.complete(conn, outputs=self.specs, figures=figures,
                                          message=message)
        except BaseException as error:
            self.close(error)
            raise
        self._committed = True
        self.close()
        assert handle is not None
        return Stored(handle, records)

    def _check_ready(self, start: OperationStart | None) -> None:
        made = ({grid.family for grid in self._grids.values()} | set(self._tables)
                | set(self._vectors))
        missing = [family for family in self._type.outputs if family not in made]
        if missing:
            raise ValueError(f"faltan salidas de «{self.op_type}» por preparar: "
                             f"{', '.join(missing)}")
        if self.handle is not None:
            if start is not None:
                raise ValueError("la operación ya empezó: se completa sin otra OperationStart")
        elif start is None:
            raise ValueError("falta la OperationStart de la operación que se registra")
        elif (start.op_type, start.name, start.version_uid, start.supersedes) != (
                self.op_type, self.name, self.version_uid, self.supersedes):
            raise ValueError(f"la OperationStart es de «{start.op_type}» «{start.name}», no de "
                             f"«{self.op_type}» «{self.name}»")

    def close(self, error: BaseException | None = None) -> None:
        """Termina. Confirmado, borra lo apartado. Si no, deshace lo puesto en su sitio, borra los
        temporales y, de una operación que ya empezó, la deja «cancelada» (``GeneratorExit`` o una
        cancelación) o «fallida» (``error``, o ninguno: no se completó); de una que no empezó, no
        hay nada que dejar. Cerrar dos veces no hace nada."""
        if self._closed:
            return
        self._closed = True
        if self._committed:
            for grid in self._grids.values():
                _discard(grid.backup)
            return
        for grid in self._grids.values():
            if grid.installed:
                if grid.replaced:
                    self._restore(grid)
                else:
                    _discard(grid.final)
            else:
                self._restore(grid)
            _discard(grid.temporary)
        if self.handle is not None:
            problem = self._abandon(error)
            if problem and error is not None:
                error.add_note(problem)

    def _abandon(self, error: BaseException | None) -> str | None:
        handle = self.handle
        assert handle is not None
        try:
            with self.project.read() as conn:
                row = conn.execute("SELECT status FROM gb_operation WHERE uid = ?",
                                   (handle.uid,)).fetchone()
            if row is None or row[0] != OperationStatus.RUNNING:
                return None
            if isinstance(error, GeneratorExit):
                handle.cancel(CANCELLED_REASON)
            elif isinstance(error, CANCELLATIONS):
                handle.cancel(cancel_reason(error))
            else:
                handle.fail(NOT_COMPLETED_REASON if error is None else failure_reason(error))
        except (GeoblenderError, OSError, sqlite3.Error) as exc:
            return (f"La operación «{handle.op_type}» ({handle.uid}) sigue «en curso» en el "
                    f"proyecto: no se pudo registrar cómo terminó ({exc}).")
        return None


# --- Recalcular lo obsoleto ---------------------------------------------------------------------

RECOMPUTED: tuple[str, ...] = (*provenance.REPRODUCIBLE, provenance.EXCAVATION_AREA,
                                provenance.QUARRY, provenance.EDGE_TRANSITION,
                                provenance.FILL_ONLY, provenance.REFIT, provenance.PLATFORM,
                                provenance.DECLARE_CONSTRAINTS)
"""Los tipos que repite «Recalcular lo obsoleto» aquí: los dos de la 013, de la 014 el recinto
y la cantera (T19), la transición (T28), «solo relleno» (T30) y el ajuste (T32) y, de la 015, la plataforma
(T14 de la 015; ``design.entity_store.recompute_platform``) y la declaración de restricciones de las
entidades (T17; ``design.entity_store.recompute_declaration``). La capa de entidades (T30) de la 015 lo
añadirá con su cálculo."""
_STORE_PHASE = "store"


def previous_comparison(conn: sqlite3.Connection, version: Version, op_type: str, name: str
                        ) -> dict[str, Any] | None:
    """Con qué se compara el desmonte y el terraplén de un escalonado (D-25, RF-013-30): la
    operación ``op_type`` de nombre ``name`` de la revisión **congelada** más reciente de la versión
    ``version`` y sus cifras ``des.cut_m3`` y ``des.fill_m3``, como ``design_settings(previous=…)``
    (``operation``, ``revision`` —``V01.r1``—, ``cut_m3`` y ``fill_m3``); ``None`` si la versión no
    tiene ninguna congelada, ninguna operación así o sin esas cifras. Solo lee."""
    revision = versions_read.last_frozen(conn, version.uid)
    if revision is None:
        return None
    rows = conn.execute(
        "SELECT uid, settings FROM gb_operation WHERE revision_uid = ? AND op_type = ? "
        "AND status = ? ORDER BY fid DESC", (revision.uid, op_type, OperationStatus.DONE.value))
    for uid, settings in rows.fetchall():
        if json.loads(settings).get("name") != name:
            continue
        figures = {str(key): value for key, value in conn.execute(
            "SELECT key, value FROM gb_figure WHERE operation_uid = ? AND key IN (?, ?)",
            (uid, provenance.CUT_M3, provenance.FILL_M3))}
        cut, fill = figures.get(provenance.CUT_M3), figures.get(provenance.FILL_M3)
        if cut is None or fill is None:
            return None
        return {"operation": name, "revision": f"{version.code}.r{revision.number}",
                "cut_m3": float(cut), "fill_m3": float(fill)}
    return None


def design_surface_start(conn: sqlite3.Connection, dataset_uid: str) -> str | None:
    """El nombre del dato de la superficie de partida de la **superficie de diseño** de uid
    ``dataset_uid`` (``des_srf_…``, el papel :data:`~geoblender.design.provenance.DESIGN_SURFACE_ROLE`
    de la operación ``des.stepped_design`` o, de la 014, ``des.fill_only`` que la escribió): la de
    «Superficie de partida» de su ficha, de los ajustes de esa operación
    (:func:`~geoblender.design.provenance.design_start`).
    ``None`` si el dato no es una superficie de diseño (la envolvente, las bermas, la tabla, el
    informe, una superficie cualquiera o un uid que el proyecto no tiene; solo se busca por uid) o
    si sus ajustes no la llevan: quien la pide sigue sin ella. Solo lee."""
    row = conn.execute(
        "SELECT o.op_type, o.settings FROM gb_dataset AS d JOIN gb_operation AS o "
        "ON o.uid = d.operation_uid JOIN gb_operation_io AS io ON io.operation_uid = o.uid "
        "AND io.direction = 'out' AND io.item_kind = 'dataset' AND io.item_uid = d.uid "
        "WHERE d.uid = ? AND io.role = ?", (dataset_uid, provenance.DESIGN_SURFACE_ROLE)
    ).fetchone()
    if row is None or row[0] not in (provenance.STEPPED, provenance.FILL_ONLY):
        return None
    try:
        return provenance.design_start(json.loads(row[1]))
    except (TypeError, ValueError):  # ajustes ausentes, que no son JSON o sin superficie
        return None


_START_KEYS: Mapping[str, str] = MappingProxyType({provenance.STEPPED: "surface",
                                                   provenance.FILL_ONLY: "surface"})
"""La clave de los ajustes con la superficie de partida de cada tipo que escribe una superficie
de diseño, si no es ``start`` (la de la cantera y la de la transición): ``surface`` en el
escalonado de la 013 y en «solo relleno» (T30), que guarda los ajustes de su escalonado."""


@dataclass(frozen=True, slots=True, eq=False)
class SurfaceOrigin:
    """Una superficie de diseño de una versión (spec 014, T28): su dato (``record``) y el tipo y
    los ajustes de la operación que la escribió con el papel ``design_surface`` (``op_type``,
    ``settings``) y su uid (``operation_uid``, T49: la que escribió su contenido de hoy, si fueron
    varias —un recálculo reescribe el mismo dato—; la que lee el ajuste para la cara anotada)."""

    record: DatasetRecord
    op_type: str
    settings: Mapping[str, Any]
    operation_uid: str = ""

    @property
    def start(self) -> str | None:
        """El nombre del dato de su superficie de partida, de los ajustes de su operación (la
        ``surface`` de un escalonado de la 013; la ``start`` de una cantera o de una transición);
        ``None`` si no la llevan."""
        found = self.settings.get(_START_KEYS.get(self.op_type, "start"))
        return found if isinstance(found, str) and found else None


def design_surface_of(conn: sqlite3.Connection, name: str, version_uid: str
                      ) -> SurfaceOrigin | None:
    """La superficie de diseño ``name`` (el nombre de su dato o su uid) de la versión
    ``version_uid`` (spec 014, T28; RF-014-19): un dato vivo de esa versión que una operación de
    ``des`` escribió con el papel :data:`~geoblender.design.provenance.DESIGN_SURFACE_ROLE` (la
    superficie de un escalonado de la 013, las dos de una cantera, una transición…); ``None`` si
    no lo es (una superficie del proyecto, una envolvente, una de otra versión o un nombre que la
    versión no tiene). Solo lee."""
    record = dataset_registry.get(conn, name, version_uid=version_uid)
    if record is None or not record.live:
        return None
    found = conn.execute("SELECT version_uid FROM gb_dataset WHERE uid = ?",
                         (record.uid,)).fetchone()
    if found is None or found[0] != version_uid:
        return None
    row = conn.execute(  # la que escribió su contenido de hoy antes que las anteriores (T49)
        "SELECT o.op_type, o.settings, o.uid FROM gb_operation_io AS io JOIN gb_operation AS o "
        "ON o.uid = io.operation_uid WHERE io.direction = 'out' AND io.item_kind = 'dataset' "
        "AND io.item_uid = ? AND io.role = ? ORDER BY o.uid = ? DESC, io.fid DESC",
        (record.uid, provenance.DESIGN_SURFACE_ROLE, record.operation_uid)
    ).fetchone()
    if row is None or str(row[0]) not in provenance.OPERATION_TYPES_BY_NAME:
        return None
    try:
        settings = json.loads(row[1]) if row[1] else {}
    except ValueError:
        settings = {}
    return SurfaceOrigin(record, str(row[0]),
                         MappingProxyType(settings if isinstance(settings, dict) else {}),
                         str(row[2]))


# --- La comprobación contra un límite nuevo (spec 014, T31; RF-014-26; plan A13) -------------------

LIMIT_CHECKED_TYPES: tuple[str, ...] = (provenance.QUARRY, provenance.EDGE_TRANSITION,
                                        provenance.FILL_ONLY, provenance.REFIT)
"""Los tipos de operación de la 014 cuyas superficies de diseño se comprueban contra el límite
vigente al recompilar las máscaras: la cantera (sus dos superficies), la transición, «solo relleno»
y el ajuste."""


def limit_surfaces(conn: sqlite3.Connection, version_uid: str, *,
                   types: Iterable[str] = LIMIT_CHECKED_TYPES) -> tuple[SurfaceOrigin, ...]:
    """Las superficies de diseño **de la 014** vivas en la versión ``version_uid`` (su uid), por el
    nombre de su dato: las que escribió con el papel
    :data:`~geoblender.design.provenance.DESIGN_SURFACE_ROLE` una operación de
    :data:`LIMIT_CHECKED_TYPES` (no las envolventes, la clasificación ni las tablas; tampoco las de
    un escalonado de la 013), cada una como :class:`SurfaceOrigin`. Con ``types``, las de esos tipos
    de operación (las que ofrece «Ajustar el diseño a un límite nuevo…», T33: las de
    :data:`REFIT_SOURCES`, también las de un escalonado de la 013). Solo lee."""
    wanted = tuple(dict.fromkeys(types))
    if not wanted:
        return ()
    marks = ", ".join("?" for _ in wanted)
    rows = conn.execute(
        "SELECT DISTINCT d.uid, d.name FROM gb_dataset AS d JOIN gb_operation_io AS io "
        "ON io.item_uid = d.uid AND io.direction = 'out' AND io.item_kind = 'dataset' "
        "JOIN gb_operation AS o ON o.uid = io.operation_uid "
        f"WHERE d.version_uid = ? AND io.role = ? AND o.op_type IN ({marks}) ORDER BY d.name",
        (version_uid, provenance.DESIGN_SURFACE_ROLE, *wanted)).fetchall()
    found: list[SurfaceOrigin] = []
    for uid, _name in rows:
        origin = design_surface_of(conn, str(uid), version_uid)
        if origin is not None and origin.op_type in wanted:
            found.append(origin)
    return tuple(found)


def _min_thickness(conn: sqlite3.Connection, project: StoreProject, version: Version) -> float:
    """El espesor mínimo de la 012 (``res.verify.min_thickness_m``) en la versión ``version``: el
    suyo, el del proyecto o, sin ninguno, el de su definición. ``ValueError`` (error del programa)
    si no está declarado ni registrado."""
    resolved = ParameterStore(project).resolve_many(
        conn, (VERIFY_MIN_THICKNESS,), (VERSION_SCOPE, PROJECT_SCOPE),
        version=version.uid).get(VERIFY_MIN_THICKNESS)
    if resolved is not None:
        return float(resolved.value)
    declared = definition(VERIFY_MIN_THICKNESS)
    if declared is None or declared.default is None:
        raise ValueError(f"«{VERIFY_MIN_THICKNESS}» no tiene valor ni está registrado")
    return float(declared.default)


def limit_checks_steps(project: StoreProject, version_uid: str, *,
                       names: Iterable[str] | None = None, masks: access.MaskSet | None = None,
                       types: Iterable[str] = LIMIT_CHECKED_TYPES
                       ) -> Generator[None, None, tuple[refit.RefitCheck, ...]]:
    """**A13**, la comprobación (spec 014, T31; RF-014-26), por unidades (las de la lectura de las
    máscaras y, desde la T35, una por la lectura de cada rejilla y otra por la comprobación de cada
    superficie: ninguna de más de ≈ 0,11 s con 2,81 M celdas, RNF-014-02): cada superficie de la
    014 de la versión ``version_uid`` (uid o código; :func:`limit_surfaces`, o solo las de
    ``names``, por el nombre o el uid de su dato;
    con ``types``, las de esos tipos de operación, como en :func:`limit_surfaces`)
    frente al límite **vigente** de sus máscaras (``design.refit.outside_volume``: lo que mueve
    fuera de él frente a su superficie de partida, la de los ajustes de su operación, con el espesor
    mínimo de la 012 en la versión). Devuelve una ``RefitCheck`` por superficie, en su orden; ninguna
    sin superficies, si alguna no tiene partida en sus ajustes o si las máscaras no están al día
    (sin compilar u obsoletas: no hay límite vigente contra el que comprobar). Solo lee.

    Los errores de leer la versión, las máscaras o una superficie (``VersionError``, ``GisError``,
    ``DesignError``) siguen; ``ValueError`` si una superficie no es de la rejilla de las máscaras."""
    with project.read() as conn:
        version = versions_read.version(conn, version_uid)
        if version is None:
            raise VersionError("core.version_unknown", field="versión", value=version_uid,
                               version=version_uid)
        surfaces = limit_surfaces(conn, version.uid, types=types)
        thickness = _min_thickness(conn, project, version) if surfaces else 0.0
    if names is not None:
        wanted = set(names)
        surfaces = tuple(origin for origin in surfaces
                         if origin.record.name in wanted or origin.record.uid in wanted)
    if not surfaces:
        return ()
    if masks is None:
        state, _pending = access.mask_state(project, version.uid)
        if state is not access.MaskState.CURRENT:
            return ()
        yield None  # el estado y la primera unidad de las máscaras, aparte (spec 014, T35)
        masks = yield from access.load_masks_steps(project, version.uid)
    starts: dict[str, np.ndarray] = {}
    found: list[refit.RefitCheck] = []
    for origin in surfaces:
        start = origin.start
        if start is None:
            continue
        yield None
        design = read_surface(project, origin.record.name, version_uid=version.uid).values
        if start not in starts:
            yield None
            starts[start] = read_surface(project, start, version_uid=version.uid).values
        # Cada lectura de una rejilla es una unidad y la comprobación, otra (spec 014, T35;
        # RNF-014-02): juntas pasaban de 0,1 s con 2,81 M celdas.
        yield None
        found.append(refit.outside_volume(design, starts[start], masks, thickness,
                                          name=origin.record.name, version=version.code))
    return tuple(found)


def limit_checks(project: StoreProject, version_uid: str, *, names: Iterable[str] | None = None,
                 masks: access.MaskSet | None = None,
                 types: Iterable[str] = LIMIT_CHECKED_TYPES) -> tuple[refit.RefitCheck, ...]:
    """:func:`limit_checks_steps` de una vez."""
    return _result_of(limit_checks_steps(project, version_uid, names=names, masks=masks,
                                         types=types))


# --- La caché de la comprobación (spec 014, T35; RNF-014-02) -------------------------------------


@dataclass(frozen=True, slots=True)
class LimitKey:
    """La clave de la comprobación de una superficie de diseño (:func:`limit_check_keys`): el nombre
    y el uid de su dato, el tipo de la operación que la escribió y ``key``, lo que decide su
    resultado (las máscaras de la versión, el espesor mínimo vigente, la superficie y su partida),
    comparable con ``==``."""

    surface: str
    uid: str
    op_type: str
    key: Hashable


@dataclass(frozen=True, slots=True)
class LimitKeys:
    """Las claves de las superficies de diseño de una versión (su uid), en el orden de
    :func:`limit_surfaces`."""

    version_uid: str
    surfaces: tuple[LimitKey, ...]


def _record_key(record: DatasetRecord | None) -> tuple[str, str, str] | None:
    """Lo que identifica el contenido de ``record``: su uid, su hash y su estado."""
    return None if record is None else (record.uid, record.content_sha256, str(record.status))


def _masks_key(conn: sqlite3.Connection, version_uid: str) -> Hashable:
    """Lo que decide el estado de las máscaras de la versión ``version_uid`` y su contenido, sin
    leer las restricciones (``gis.masks.access.mask_state`` lee además los sectores pendientes, que
    no cambian la comprobación): sus tres datos, la operación que los escribió y si alguno tiene
    causa de obsolescencia (``gb_stale``)."""
    records = [dataset_registry.get(conn, masks_declared.dataset_name(family),
                                    version_uid=version_uid) for family in access.MASK_FAMILIES]
    found = tuple(None if record is None else (*_record_key(record), record.operation_uid)
                  for record in records)
    items = sorted({uid for record in records if record is not None
                    for uid in (record.uid, record.operation_uid)})
    if not items:
        return (found,)
    marks = ", ".join("?" for _ in items)
    operations = tuple(tuple(row) for row in conn.execute(
        f"SELECT uid, op_type, status, superseded_by FROM gb_operation WHERE uid IN ({marks}) "
        "ORDER BY uid", items))
    stale = tuple(str(row[0]) for row in conn.execute(
        f"SELECT DISTINCT item_uid FROM gb_stale WHERE item_uid IN ({marks}) ORDER BY item_uid",
        items))
    return (found, operations, stale)


def _start_record(conn: sqlite3.Connection, name: str, version_uid: str) -> DatasetRecord | None:
    """El dato vivo de la superficie de partida ``name`` como la lee ``read_surface``: el de la
    versión o, si no tiene uno así, el del proyecto."""
    record = dataset_registry.get(conn, name, version_uid=version_uid)
    if record is None:
        record = dataset_registry.get(conn, name)
    return record if record is not None and record.live else None


def limit_check_keys(project: StoreProject, version_uid: str, *,
                     types: Iterable[str] = LIMIT_CHECKED_TYPES) -> LimitKeys:
    """Las claves de la comprobación (:func:`limit_checks_steps`) de cada superficie de diseño de la
    versión ``version_uid`` (uid o código) de los tipos ``types`` (:func:`limit_surfaces`), en una
    lectura corta (spec 014, T35; RNF-014-02): por superficie, el estado y el contenido de las
    máscaras de la versión, el espesor mínimo vigente en ella, el uid, el hash y el estado de su
    dato y el nombre, el uid, el hash y el estado de su superficie de partida. Si cambia la clave de
    una superficie, puede cambiar su comprobación; si no cambia, no. No lee ninguna rejilla. Solo
    lee; ``VersionError`` si la versión no existe."""
    with project.read() as conn:
        version = versions_read.version(conn, version_uid)
        if version is None:
            raise VersionError("core.version_unknown", field="versión", value=version_uid,
                               version=version_uid)
        surfaces = limit_surfaces(conn, version.uid, types=types)
        if not surfaces:
            return LimitKeys(version.uid, ())
        masks = _masks_key(conn, version.uid)
        thickness = _min_thickness(conn, project, version)
        starts: dict[str, tuple[str, str, str] | None] = {}
        found: list[LimitKey] = []
        for origin in surfaces:
            start = origin.start
            if start is not None and start not in starts:
                starts[start] = _record_key(_start_record(conn, start, version.uid))
            record = origin.record
            key = (masks, thickness, _record_key(record), start,
                   None if start is None else starts[start])
            found.append(LimitKey(record.name, record.uid, origin.op_type, key))
    return LimitKeys(version.uid, tuple(found))


class LimitCheckMemo:
    """Los resultados de la comprobación contra el límite vigente (:func:`limit_checks_steps`) en
    memoria, por superficie y con su clave (:func:`limit_check_keys`; spec 014, T35; RNF-014-02):
    los llena :meth:`fill_steps` (al compilar las máscaras, por pasos) y los leen :meth:`lookup` (la
    ficha de la barra N, el diálogo del ajuste) sin leer ninguna rejilla. Se invalida sola: una
    superficie cuya clave cambió (otras máscaras, otro espesor, otra superficie u otra partida) no
    acierta. :meth:`clear` la vacía (al cerrar el proyecto). No escribe en el proyecto."""

    def __init__(self) -> None:
        self._held: dict[tuple[str, str, str], tuple[Hashable, refit.RefitCheck | None]] = {}

    def __len__(self) -> int:
        return len(self._held)

    def lookup(self, project: StoreProject, version_uid: str, *,
               names: Iterable[str] | None = None,
               types: Iterable[str] = LIMIT_CHECKED_TYPES) -> tuple[refit.RefitCheck, ...] | None:
        """Lo que daría :func:`limit_checks` con lo mismo, de la caché: una ``RefitCheck`` por
        superficie que la tiene, en su orden; ``None`` (sin acierto) si alguna de las pedidas no
        está o cambió su clave. Solo lee las claves."""
        keys = limit_check_keys(project, version_uid, types=types)
        wanted = None if names is None else set(names)
        found: list[refit.RefitCheck] = []
        for item in keys.surfaces:
            if wanted is not None and item.surface not in wanted and item.uid not in wanted:
                continue
            held = self._held.get((str(project.uid), keys.version_uid, item.surface))
            if held is None or held[0] != item.key:
                return None
            if held[1] is not None:
                found.append(held[1])
        return tuple(found)

    def fill_steps(self, project: StoreProject, version_uid: str, *,
                   types: Iterable[str] = REFIT_SOURCES
                   ) -> Generator[None, None, tuple[tuple[str, refit.RefitCheck], ...]]:
        """:func:`limit_checks_steps` de las superficies de los tipos ``types`` de la versión
        ``version_uid``, por unidades, guardando en la caché lo de cada una con su clave **si
        ninguna clave cambió mientras tanto** (las de antes y las de después, iguales). Devuelve,
        por superficie comprobada, el tipo de su operación y su ``RefitCheck``. Cerrarlo a mitad no
        guarda nada."""
        wanted = tuple(types)
        keys = limit_check_keys(project, version_uid, types=wanted)
        if not keys.surfaces:
            return ()
        yield None
        found = yield from limit_checks_steps(project, keys.version_uid, types=wanted)
        if limit_check_keys(project, keys.version_uid, types=wanted) == keys:
            checked = {check.surface: check for check in found}
            for item in keys.surfaces:
                self._held[(str(project.uid), keys.version_uid, item.surface)] = (
                    item.key, checked.get(item.surface))
        kinds = {item.surface: item.op_type for item in keys.surfaces}
        return tuple((kinds.get(check.surface, ""), check) for check in found)

    def clear(self) -> None:
        """Olvida todo lo guardado."""
        self._held.clear()


def _result_of[T](work: Generator[object, None, T]) -> T:
    """Lo que devuelve ``work`` (unidades de ``seeds``, pasos de ``masks_steps``) llevado hasta el
    final."""
    while True:
        try:
            next(work)
        except StopIteration as stop:
            return stop.value  # type: ignore[no-any-return]


def _values(handle: OperationHandle) -> dict[str, object]:
    """Los parámetros que anotó la operación al empezar: clave → valor (es lo que lee el cálculo,
    como lo leerá la reproducción de lo congelado)."""
    return {param.key: param.value for param in handle.params}


def number(values: Mapping[str, object], key: str) -> float:
    """El parámetro ``key`` de ``values`` como número finito; ``ValueError`` si no lo tiene (una
    operación de ``des`` anota siempre los tres que lee: el espesor, la tolerancia y el umbral)."""
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, numbers.Real) \
            or not math.isfinite(float(value)):
        raise ValueError(f"la operación no anotó un valor numérico del parámetro «{key}»: "
                         f"{value!r}")
    return float(value)


def _store_steps(spec_steps: Generator[None, None, Any], budget_s: float, what: str
                 ) -> Iterator[Progress]:
    return pace_progress(spec_steps, budget_s, phase=_STORE_PHASE,
                         running=f"Guardando {what}…", finished=f"{what.capitalize()} guardado")


@dataclass(frozen=True, slots=True, eq=False)
class PreparedEnvelope:
    """Lo que se lee y se comprueba antes de calcular una envolvente (:func:`prepare_envelope_units`):
    sus ``seeds`` con el dominio de trabajo y lo que anotará la operación (``start``)."""

    seeds: SeedSet
    start: OperationStart


@dataclass(frozen=True, slots=True, eq=False)
class PreparedDesign:
    """Lo que se lee y se comprueba antes de calcular un escalonado (:func:`prepare_design_units`): la
    ``envelope`` que se escalona, los sectores del proyecto (``refs``) con la etiqueta de cada celda
    (``labels``) y lo que anotará la operación (``start``)."""

    envelope: Raster
    refs: tuple[SectorRef, ...]
    labels: np.ndarray
    start: OperationStart


@dataclass(frozen=True, slots=True, eq=False)
class PreparedArea:
    """Lo que se lee y se comprueba antes de guardar un recinto (:func:`prepare_area_units`): el
    recinto (``area``, ``design.quarry.excavation_area``), la superficie de partida de la que sale
    (``surface``, con su rejilla) y lo que anotará la operación (``start``)."""

    area: np.ndarray
    surface: Raster
    start: OperationStart


@dataclass(frozen=True, slots=True, eq=False)
class QuarryParts:
    """Lo que la cantera (``des.quarry``) lee del proyecto o de lo congelado, ya en la rejilla de
    las máscaras: lo que necesita ``design.quarry.QuarryJob`` salvo el techo, que se calcula (plan
    014 §5.3.1). La superficie de partida (``start``, con su rejilla); el dominio de trabajo, el
    recinto con las etiquetas de sector (``domain``, :func:`quarry_domain`); por lado, las semillas
    de la 013 del que no siembra la coronación (``seeds``) y la rejilla de anclas del que tiene el
    ancla en rejilla (``anchors``); los fondos (``floors``) y los corredores (``corridors``), por
    separado para sus avisos y juntos para el cálculo (``joined``, ``quarry.join_floors``); las
    zonas a conservar (``conserve``) y las máscaras de las zonas de restauración por relleno
    (``fill_zones``) y de «explotación hasta la final» (``to_final_zones``), si las hay."""

    start: Raster
    domain: DomainSet
    seeds: Mapping[Surface, SeedSet]
    anchors: Mapping[Surface, np.ndarray]
    floors: quarry.FloorMap | None
    corridors: quarry.CorridorMap | None
    joined: quarry.FloorMap | None
    conserve: tuple[quarry.ConserveZone, ...]
    fill_zones: np.ndarray | None
    to_final_zones: np.ndarray | None

    @property
    def area(self) -> np.ndarray:
        """El recinto excavable (la máscara del dominio de trabajo)."""
        return self.domain.mask


@dataclass(frozen=True, slots=True, eq=False)
class PreparedQuarry:
    """Lo que se lee y se comprueba antes de calcular una cantera (:func:`prepare_quarry_units`):
    sus piezas (``parts``, :class:`QuarryParts`) y lo que anotará la operación (``start``)."""

    parts: QuarryParts
    start: OperationStart


@dataclass(frozen=True, slots=True, eq=False)
class PreparedTransition:
    """Lo que se lee y se comprueba antes de calcular una transición
    (:func:`prepare_transition_units`): la superficie de diseño (``surface``), la de partida
    (``ground``), las dos en la rejilla del proyecto, y lo que anotará la operación (``start``)."""

    surface: Raster
    ground: Raster
    start: OperationStart


@dataclass(frozen=True, slots=True, eq=False)
class FillOnlyParts:
    """Lo que «solo relleno» (``des.fill_only``, spec 014, T30) lee del proyecto o de lo congelado,
    ya en la rejilla de las máscaras: la envolvente que se escalona (``envelope``) y la superficie
    de partida (``start``, el terreno registrado), las dos con su rejilla; la rejilla de anclas
    (``anchors``; ``None``, el ancla del perfil); los sectores (``refs``) con la etiqueta de cada
    celda (``labels``); las láminas de agua (``water``; ``None`` sin ellas) y los intocables de las
    máscaras con su nombre (``untouchables``)."""

    envelope: Raster
    start: Raster
    anchors: np.ndarray | None
    refs: tuple[SectorRef, ...]
    labels: np.ndarray
    water: fronts.WaterSheets | None
    untouchables: tuple[fronts.UntouchableZone, ...]


@dataclass(frozen=True, slots=True, eq=False)
class PreparedFillOnly:
    """Lo que se lee y se comprueba antes de calcular un diseño «solo relleno»
    (:func:`prepare_fill_only_units`): sus piezas (``parts``, :class:`FillOnlyParts`) y lo que
    anotará la operación (``start``)."""

    parts: FillOnlyParts
    start: OperationStart


@dataclass(frozen=True, slots=True, eq=False)
class RefitPart:
    """Una superficie que se ajusta a un límite nuevo (spec 014, T32): el nombre de su dato
    (``name``), su rejilla (``surface``, en la rejilla del proyecto), el perfil base y el de cada
    sector de la operación que la creó (``base_profile``, ``sector_profiles``;
    :func:`refit_profiles`) y la cara y el factor de malla de esos perfiles que **anotó** esa
    operación (``values``: clave ``des.bench.{p}.…`` → valor; T49, P-3), con los que se ajusta.
    Si sale de una cantera (su explotación o su final, o una transición o un ajuste de ellas, como
    su perfil), el nombre de la cantera (``quarry``), su lado (``side``) y el orden del diseño de la
    cantera (``order``, su ajuste «order»), con los que el ajuste ata las dos superficies de una
    misma cantera (T53; RF-014-14); si no, ``""``, ``None`` y ``None``."""

    name: str
    surface: Raster
    base_profile: str
    sector_profiles: tuple[tuple[str, str], ...]
    values: Mapping[str, object]
    quarry: str = ""
    side: Surface | None = None
    order: Order | None = None

    @property
    def profiles(self) -> tuple[str, ...]:
        """Los códigos de sus perfiles: el base y los de sus sectores, sin repetir."""
        return tuple(dict.fromkeys(
            [self.base_profile, *(profile for _sector, profile in self.sector_profiles)]))

    @property
    def other(self) -> str | None:
        """El dato de la otra superficie de su cantera (``des_fin_<cantera>`` de la explotación,
        ``des_exp_<cantera>`` de la final; T53); ``None`` si no sale de una cantera."""
        if not self.quarry or self.side is None:
            return None
        return _other_surface(self.quarry, self.side)


@dataclass(frozen=True, slots=True, eq=False)
class PreparedRefit:
    """Lo que se lee y se comprueba antes de calcular un ajuste (:func:`prepare_refit_units`): las
    superficies (``parts``, :class:`RefitPart`), la de partida (``ground``), los sectores
    (``refs``) con la etiqueta de cada celda (``labels``), el nombre de cada perfil (``names``:
    código → nombre, para los mensajes), lo que anotará la operación (``start``) y, de cada
    superficie de una cantera que va sin la otra en la petición, la otra tal como está en la
    versión (``others``: el nombre de su dato, :attr:`RefitPart.other` → su rejilla; T53), con la
    que se compara después de ajustarla; y los avisos de los diseños obsoletos de los que sale
    (``stale_notices``, :func:`_stale_designs`; T54)."""

    parts: tuple[RefitPart, ...]
    ground: Raster
    refs: tuple[SectorRef, ...]
    labels: np.ndarray
    names: Mapping[str, str]
    start: OperationStart
    others: Mapping[str, Raster] = field(default_factory=lambda: MappingProxyType({}))
    stale_notices: tuple[Notice, ...] = ()


def prepare_envelope_units(project: StoreProject, request: EnvelopeRequest, version: Version,
                           masks: access.MaskSet, *, supersedes: str | None = None
                           ) -> Generator[None, None, PreparedEnvelope]:
    """Las unidades (cada ``yield``, una; para componerlas con ``pace_units``) que preparan el
    cálculo de ``request`` en ``version`` con sus ``masks`` ya al día (:func:`masks_steps`): los
    sectores, las semillas con el dominio de trabajo (``seed_units``), el rechazo de un sector con la
    búsqueda pendiente (RF-013-05) y :func:`prepare_envelope`. Devuelve la
    :class:`PreparedEnvelope`. Nada se escribe; los rechazos salen al avanzar."""
    sectors = design_sectors(project, version.uid)
    yield
    seeds = yield from seed_units(project, request, masks)
    refuse_pending(touched(sectors, seeds.domain))  # RF-013-05
    yield
    start = prepare_envelope(project, request, version=version.uid, masks=masks, sectors=sectors,
                             touched_sectors=[ref.code for ref in seeds.touched],
                             supersedes=supersedes)
    yield
    return PreparedEnvelope(seeds, start)


def prepare_design_units(project: StoreProject, request: DesignRequest, surface: str,
                         version: Version, masks: access.MaskSet, *,
                         supersedes: str | None = None) -> Generator[None, None, PreparedDesign]:
    """Lo mismo que :func:`prepare_envelope_units` para el escalonado ``request`` sobre la
    superficie de partida ``surface``: los sectores, la envolvente de la versión (leída y comparada
    con la rejilla del proyecto), la etiqueta de sector de cada celda, el rechazo de un sector con la
    búsqueda pendiente que toca la envolvente (RF-013-05), la revisión congelada con que se compara
    (:func:`previous_comparison`) y :func:`prepare_design`. Devuelve la :class:`PreparedDesign`."""
    sectors = design_sectors(project, version.uid)
    yield
    envelope = read_surface(
        project, provenance.dataset_name(provenance.ENVELOPE_GRID, request.envelope),
        version_uid=version.uid, expect=project_frame(project), role="envolvente")
    yield
    refs, labels = sector_layout(project, masks)
    yield
    with np.errstate(invalid="ignore"):
        domain = np.isfinite(envelope.values)
    touched_codes = pipeline.touched_in(refs, labels, domain)
    refuse_pending(item for item in sectors if item.code in touched_codes)  # RF-013-05
    waiting = [item.code for item in sectors if item.pending and item.code in touched_codes]
    with project.read() as conn:
        previous = previous_comparison(conn, version, provenance.STEPPED, request.name)
    yield
    start = prepare_design(project, request, surface, version=version.uid, masks=masks,
                           sectors=sectors, pending_sectors=waiting, touched_sectors=touched_codes,
                           previous=previous, supersedes=supersedes)
    yield
    return PreparedDesign(envelope, refs, labels, start)


def prepare_area_units(project: StoreProject, name: str, surface: str, version: Version,
                       masks: access.MaskSet, *, supersedes: str | None = None
                       ) -> Generator[None, None, PreparedArea]:
    """Las unidades que preparan el recinto ``name`` de ``version`` sobre la superficie de partida
    ``surface`` con sus ``masks`` ya al día (spec 014, T06; RF-014-01; A1): la superficie (leída y
    comparada con la rejilla del proyecto), el recinto (``design.quarry.excavation_area``: vacío,
    ``DesignError`` ``des.quarry_area_empty`` con lo que lo vacía) y
    :func:`prepare_excavation_area`. Devuelve la :class:`PreparedArea`. Nada se escribe; los
    rechazos salen al avanzar."""
    found = read_surface(project, surface, version_uid=version.uid,
                         expect=project_frame(project), role="superficie de partida")
    yield
    area = quarry.excavation_area(masks, found.values, version=version.code)
    yield
    start = prepare_excavation_area(project, name, surface, version=version.uid, masks=masks,
                                    supersedes=supersedes)
    yield
    return PreparedArea(area, found, start)


def prepare_quarry_units(project: StoreProject, request: QuarryRequest, version: Version,
                         masks: access.MaskSet, *, supersedes: str | None = None
                         ) -> Generator[None, None, PreparedQuarry]:
    """Las unidades que preparan la cantera ``request`` de ``version`` con sus ``masks`` ya al día
    (spec 014, T19; RF-014-29, RF-014-30): los sectores, la superficie de partida (leída y
    comparada con la rejilla del proyecto), el recinto con sus sectores (:func:`quarry_domain`), el
    rechazo de un sector del recinto con la búsqueda de intocables pendiente
    (``des.sector_pending``, RF-014-30, como RF-013-05), las piezas del proyecto
    (:func:`quarry_parts_units`), con qué se compara cada lado (:func:`_quarry_previous`, T51) y
    :func:`prepare_quarry`. Devuelve la :class:`PreparedQuarry`. Nada se escribe; los rechazos
    salen al avanzar."""
    sectors = design_sectors(project, version.uid)
    yield
    frame = project_frame(project)
    found = read_surface(project, request.start, version_uid=version.uid, expect=frame,
                         role="superficie de partida")
    yield
    refs, labels = sector_layout(project, masks)
    domain = quarry_domain(masks, found.values, refs, labels, version=version.code)
    refuse_pending(touched(sectors, domain))  # RF-014-30
    yield
    geometry = masks.grid
    parts = yield from quarry_parts_units(
        request, masks, found, domain, features=lambda name: _features(project, name),
        layer=lambda name: layer_cells(project, name, geometry),
        surface=lambda name, what: read_surface(project, name, version_uid=version.uid,
                                                expect=frame, role=what).values)
    previous = _quarry_previous(project, version, request.name)
    yield
    start = prepare_quarry(project, request, version=version.uid, masks=masks, sectors=sectors,
                           touched_sectors=[ref.code for ref in domain.touched],
                           previous=previous, supersedes=supersedes)
    yield
    return PreparedQuarry(parts, start)


def compute_area_steps(writer: DesignWriter, name: str, prepared: PreparedArea,
                       budget_s: float = STEP_BUDGET_S
                       ) -> Generator[Progress, None, quarry.AreaOutcome]:
    """Los pasos que miden el recinto ``prepared.area`` de la operación ``name``
    (``design.quarry.area_outcome``) y dejan su rejilla (1 dentro, sin dato fuera) en el temporal
    de ``writer`` como ``des_rcn_`` (``yield from``; **sin confirmar**, como
    :func:`compute_envelope_steps`). Devuelve el ``design.quarry.AreaOutcome``."""
    yield Progress("area", 0, 1, "Midiendo el recinto…")
    geometry = prepared.surface.grid
    outcome = quarry.area_outcome(name, prepared.area, geometry)
    raster = Raster(geometry, outcome.grid, writer.crs, writer.vertical)
    yield from pipeline.forward(_store_steps(
        writer.grid_steps(provenance.EXCAVATION_AREA_GRID, raster), budget_s, "el recinto"))
    return outcome


# --- La cantera con dos superficies (spec 014, T19; RF-014-29 a RF-014-31) -----------------------

_SIDE_VOLUMES = ("cut_m3", "fill_m3")
"""Las filas del informe de la 013 de cada lado en ``des_qrp_`` (``final.cut_m3``…) con que se
compara el mismo lado de una cantera posterior (T51)."""
_QUARRY_REPORT_ROLE = provenance.FAMILIES_BY_CODE[provenance.QUARRY_REPORT_TABLE].role


def _quarry_previous(project: StoreProject, version: Version, name: str
                     ) -> dict[str, dict[str, Any]] | None:
    """Con qué se comparan el desmonte y el terraplén de cada lado de la cantera ``name`` (spec
    014, T51, hallazgo F-12 (g); RF-013-30, D-25 de la 013, como :func:`previous_comparison`): la
    operación ``des.quarry`` de ese nombre de la revisión **congelada** más reciente de
    ``version`` y, de cada lado, el desmonte y el terraplén de su escalonado tal como se congeló
    (las filas ``final.cut_m3``… de su informe ``des_qrp_``, leídas de su copia en la
    instantánea: ``core.versions.read.frozen_location``), cada lado con el suyo: por superficie
    (``final`` y ``exploitation``), ``operation`` (el nombre del lado, «<cantera> (superficie
    final)», el de su informe), ``revision`` (``V01.r1``), ``cut_m3`` y ``fill_m3``. ``None`` si la
    versión no tiene ninguna congelada o está alterada, si no tiene ninguna cantera así, si su
    informe no tiene copia o si le falta alguna de esas filas. Solo lee."""
    with project.read() as conn:
        revision = versions_read.last_frozen(conn, version.uid)
        if revision is None or revision.altered:
            return None
        rows = conn.execute(
            "SELECT uid, settings FROM gb_operation WHERE revision_uid = ? AND op_type = ? "
            "AND status = ? ORDER BY fid DESC",
            (revision.uid, provenance.QUARRY, OperationStatus.DONE.value)).fetchall()
        uid = next((str(uid) for uid, settings in rows
                    if json.loads(settings).get("name") == name), None)
        if uid is None:
            return None
        report = conn.execute(
            "SELECT item_uid FROM gb_operation_io WHERE operation_uid = ? AND direction = 'out' "
            "AND item_kind = 'dataset' AND role = ?", (uid, _QUARRY_REPORT_ROLE)).fetchone()
        location = (None if report is None
                    else versions_read.frozen_location(conn, revision.uid, str(report[0])))
    if location is None or location.path is None or location.layer is None:
        return None
    path = Path(project.root, *location.path.split("/"))
    if not path.is_file():
        return None
    keys = [f"{side.value}.{key}" for side in Surface for key in _SIDE_VOLUMES]
    table = '"' + location.layer.replace('"', '""') + '"'
    with GpkgConnection.open_read(path) as gpkg:
        found = dict(gpkg.connection.execute(
            f"SELECT quantity, value FROM {table} WHERE quantity IN "
            f"({', '.join('?' for _key in keys)})", keys).fetchall())
    if any(found.get(key) is None for key in keys):
        return None
    label = f"{version.code}.r{revision.number}"
    return {side.value: {"operation": f"{name} ({quarry.SIDE_NAMES[side]})", "revision": label,
                         **{key: float(found[f"{side.value}.{key}"]) for key in _SIDE_VOLUMES}}
            for side in Surface}



def quarry_domain(masks: access.MaskSet, start: np.ndarray, refs: Sequence[SectorRef],
                  labels: np.ndarray, *, version: str | None = None) -> DomainSet:
    """El dominio de trabajo de una cantera: su recinto excavable (``quarry.excavation_area``, A1;
    vacío, ``des.quarry_area_empty`` con lo que lo vacía; ``version``, el código que nombra) con
    la etiqueta de sector de cada celda (``labels``, de los sectores ``refs``)."""
    area = quarry.excavation_area(masks, start, version=version)
    return domain_of(area, labels, refs, masks.grid.cell_area)


def _conserve_cells(masks: access.MaskSet, zone: Zone, layer: Callable[[str], np.ndarray]
                    ) -> np.ndarray:
    """Las celdas de una zona a conservar: una restricción de la 012 (su zona en las máscaras) o
    una capa de polígonos (``layer``); otra cosa es un error del programa."""
    kind = ZoneKind(zone.kind)
    if kind not in (ZoneKind.CONSTRAINT, ZoneKind.LAYER) or not zone.name:
        raise ValueError(f"una zona a conservar es una restricción o una capa con su nombre, no "
                         f"{zone!r}")
    if kind is ZoneKind.CONSTRAINT:
        return constraint_cells(masks, zone.name)
    return layer(zone.name)


def quarry_parts_units(request: QuarryRequest, masks: access.MaskSet, start: Raster,
                       domain: DomainSet, *, features: Callable[[str], FeatureLayer],
                       layer: Callable[[str], np.ndarray],
                       surface: Callable[[str, str], np.ndarray]
                       ) -> Generator[None, None, QuarryParts]:
    """Las unidades que leen las piezas de la cantera ``request`` (:class:`QuarryParts`) en la
    rejilla de ``masks`` con su partida ``start`` y su dominio ya formado (:func:`quarry_domain`),
    con quien lee cada cosa por su nombre: ``features`` (una capa de entidades, ``FeatureLayer``),
    ``layer`` (las celdas de una capa de polígonos) y ``surface`` (las cotas de una superficie o
    rejilla, con lo que es en el mensaje). Lo comparten el proyecto (:func:`prepare_quarry_units`)
    y la reproducción de lo congelado. Rechazos al avanzar: los de las semillas de la 013
    (``seeds.check_source``, sus zonas), los fondos y los corredores (``quarry.floor_map``,
    ``quarry.corridor_cells``, ``quarry.join_floors``), una zona a conservar sin zona y los de las
    capas y las superficies."""
    geometry = masks.grid
    values = start.values
    seeds: dict[Surface, SeedSet] = {}
    anchors: dict[Surface, np.ndarray] = {}
    for side_name in Surface:
        side = request.side(side_name)
        if side.seeds is not None:
            check_source(side.seeds)
            seeds[side_name] = yield from assemble_units(side.seeds, masks, domain, layer=layer,
                                                         surface=surface)
        if side.anchor_grid is not None:
            anchors[side_name] = surface(side.anchor_grid, "anclas")
            yield
    floors = None
    if request.floors is not None:
        floors = quarry.floor_map(features(request.floors.layer), request.floors, values,
                                  geometry)
        yield
    corridors = None
    if request.corridors is not None:
        corridors = quarry.corridor_cells(features(request.corridors.layer), request.corridors,
                                          geometry, start=values)
        yield
    joined = quarry.join_floors(floors, corridors)
    conserve = []
    for zone in request.conserve:
        cells = _conserve_cells(masks, zone, layer)  # sin nombre, ValueError
        conserve.append(quarry.ConserveZone(str(zone.name), cells))
        yield
    fill_zones = None if request.fill_zones is None else layer(request.fill_zones)
    to_final_zones = None if request.to_final_layer is None else layer(request.to_final_layer)
    yield
    return QuarryParts(start, domain, MappingProxyType(seeds), MappingProxyType(anchors), floors,
                       corridors, joined, tuple(conserve), fill_zones, to_final_zones)


def created_step_steps(surface: str, grid: np.ndarray, start: np.ndarray, geometry: Grid,
                       allowed: np.ndarray, values: Mapping[str, object], *,
                       budget_s: float = STEP_BUDGET_S
                       ) -> Generator[Progress, None, tuple[Notice, ...]]:
    """**El salto creado de una superficie de diseño en el resumen de su diseño** (T56; RF-014-20,
    RF-014-21; hallazgo F-18, la propuesta por defecto que aceptó Samuel): A11
    (``design.edges.created_steps``) de la superficie ``grid`` (m) del dato ``surface`` sobre la de
    partida ``start`` (m) en el dominio de la transición (``design.edges.transition_domain``: las
    celdas que mueve el diseño más que el espesor mínimo donde ``allowed``, lo que las máscaras
    admiten mover, el corte o el relleno; el mismo borde que mide «Transiciones con el terreno no
    afectado» antes y después), con el espesor mínimo y el salto y el porcentaje admitidos de
    ``values`` (D-6), sin escribir nada (``yield from``). Devuelve su aviso
    ``des.edge_surface_step``, que nombra ``surface``, y una nota por tramo
    (``design.edges.edge_notices``), o ``()`` si no se avisa. Lo usan la cantera (sus dos
    superficies), «solo relleno» y el ajuste (cada superficie ajustada), en «Calcular», el
    recálculo y la reproducción. Una operación que no leyó ni el salto ni el porcentaje admitidos
    (anterior a la T56: la reproducción de lo que anotó) no lo mide: ``()``.

    Pública desde la 015 (T05; plan 015 §5.4 A3: el borde de una plataforma avisa del salto creado
    con esta misma función; sin cambio de comportamiento)."""
    if EDGE_MAX_STEP not in values and EDGE_MIN_SHARE not in values:
        return ()
    thickness = number(values, VERIFY_MIN_THICKNESS)
    domain = edges.transition_domain(grid, start, thickness, allowed)
    report: edges.EdgeReport = yield from pipeline.forward(edges.created_steps(
        grid, start, domain, geometry, thickness,
        values.get(EDGE_MAX_STEP), values.get(EDGE_MIN_SHARE),  # type: ignore[arg-type]
        budget_s=budget_s))
    return edges.edge_notices(report, surface=surface)


def _allowed(masks: access.MaskSet) -> np.ndarray:
    """Lo que las máscaras ``masks`` admiten mover: el corte o el relleno admitidos (el dominio de
    la transición y del salto creado)."""
    return masks.cut_allowed() | masks.fill_allowed()


_CEILING_METRIC = Metric.CHAMFER5
"""La métrica del techo de conservación, que es uno para los dos lados (T13): el *chamfer* 5×5 de
ADR-0014, la de los dos lados de una cantera (T45: la euclídea exacta se rechaza al pedirla,
``quarry._check_metric``)."""


def quarry_notices(request: QuarryRequest, masks: access.MaskSet, parts: QuarryParts,
                   ring_cells: int, outcome: quarry.QuarryOutcome, *, compared: bool = False,
                   created: Sequence[Notice] = ()) -> tuple[Notice, ...]:
    """Los avisos y las notas de la cantera que no son del escalonado de un lado, en el orden en
    que se enseñan: los de sus capas (fondos y corredores sobre el terreno, juntos, como en
    ``parts.joined``, T42; zonas a conservar sin dato, corredores más largos que su eje más su
    ancho; los de la vista previa), las semillas de la 013 de un lado que caen fuera de la
    coronación y de las zonas a sostener, por grupos (RF-014-03), cada superficie que no mueve
    ninguna celda más del espesor mínimo, medida sobre la que se crea —con la regla de orden y
    «explotación hasta la final»— y nombrándola (``des.quarry_final_no_movement``,
    ``des.quarry_exploitation_no_movement``; T61, el H3), el desdoblado sobre terreno sin
    explotar, por zonas (RF-014-17; tras el modo, el de lo que queda dentro de las celdas
    tratadas va aparte y no vuelve a ofrecerlo, T57), «explotación hasta la final» (RF-014-18), el
    salto creado de sus superficies (``created``: los avisos de :func:`created_step_steps`, T56,
    RF-014-21) y, si sus lados no se compararon con los de una cantera anterior (sin
    ``compared``), la nota de la 013 que lo dice, una sola vez y con el nombre de la cantera
    (``des.magnitude_no_reference``; T51: no una por lado). Con sus valores como números
    (``preview.Notice``)."""
    geometry = masks.grid
    start = parts.start.values
    found = list(_quarry_warnings(start, parts.floors, parts.conserve, parts.corridors,
                                  geometry.cell_area))
    for side_name in Surface:
        seeds = parts.seeds.get(side_name)
        if seeds is None:
            continue
        groups = quarry.outside_crown(seeds, parts.area, start, masks, ring_cells)
        found.extend(_seed_notices(side_name, groups, geometry.cell_area))
    found.extend(_unmoved_notices(request.name, outcome, start))
    unsplit = outcome.unsplit
    for code, zones, area, volume in (
            ("des.quarry_unsplit_zones", unsplit.zones, unsplit.area_ha, unsplit.volume_m3),
            ("des.quarry_unsplit_remaining", unsplit.remaining, unsplit.remaining_area_ha,
             unsplit.remaining_volume_m3)):
        if not zones:
            continue
        found.append(Notice(code, {
            "zones": len(zones), "area": area, "volume": volume,
            "threshold": unsplit.threshold_m, "min_area": unsplit.min_area_ha}))
        found.extend(Notice("des.quarry_unsplit_zone", {
            "zone": zone.zone, "area": zone.area_ha, "volume": zone.volume_m3,
            "x": round(zone.x, 2), "y": round(zone.y, 2)}) for zone in zones)
    if outcome.to_final is not None:
        found.append(Notice("des.quarry_to_final", {
            "zones": len(outcome.to_final.zones), "area": outcome.to_final.area_ha,
            "volume": outcome.to_final.volume_m3}))
    found.extend(created)
    if not compared:
        found.append(Notice("des.magnitude_no_reference", {"operation": request.name}))
    return tuple(found)


_UNMOVED_CODES = MappingProxyType({Surface.FINAL: "des.quarry_final_no_movement",
                                   Surface.EXPLOITATION: "des.quarry_exploitation_no_movement"})
"""El aviso de cada superficie de la cantera que no mueve nada (T61): uno por lado, para nombrarlo
en los dos idiomas."""


def _unmoved_notices(name: str, outcome: quarry.QuarryOutcome, start: np.ndarray
                     ) -> list[Notice]:
    """El aviso de cada superficie de la cantera ``name`` (``outcome``, en el orden de los lados)
    que no mueve ninguna celda más del espesor mínimo de su clasificación frente a la de partida
    ``start`` (``report.moved_cells``, la máscara del informe de la 013), medida sobre la que se
    crea: con la regla de orden y, con «explotación hasta la final», la explotación bajada (T61; el
    H3: el escalonado de un lado decía que no movía nada aunque el modo excavaba 491.006 m³)."""
    thickness = float(outcome.classes.min_thickness_m)
    found: list[Notice] = []
    for side_name, grid in ((Surface.FINAL, outcome.final_grid),
                            (Surface.EXPLOITATION, outcome.exploitation_grid)):
        if not moved_cells(start, grid, thickness).any():
            found.append(Notice(_UNMOVED_CODES[side_name], {"quarry": name,
                                                            "thickness": thickness}))
    return found


def _seed_notices(surface: Surface, groups: Sequence[quarry.SeedGroup], cell_area: float
                  ) -> list[Notice]:
    """El aviso de las semillas de la 013 del lado ``surface`` que caen fuera de la coronación y de
    las zonas a sostener, con su superficie, sus celdas, su área y sus grupos, y una nota por grupo
    con sus celdas, su área y su centro en cm (RF-014-03); ninguno sin grupos."""
    if not groups:
        return []
    cells = sum(group.cells for group in groups)
    return [Notice("des.quarry_seeds_outside", {
        "surface": surface.value, "cells": cells, "area": cells * cell_area,
        "groups": len(groups)}),
        *(Notice("des.quarry_seed_group", {
            "group": group.group, "cells": group.cells, "area": group.area_m2,
            "x": round(group.x, 2), "y": round(group.y, 2)}) for group in groups)]


def _seeds_outside_units(masks: access.MaskSet, parts: QuarryParts, values: Mapping[str, object]
                         ) -> Generator[None, None, tuple[Notice, ...]]:
    """Las unidades que buscan, **antes de calcular** la cantera de piezas ``parts`` (T43;
    RF-014-03, error 10), las semillas de la 013 de cada lado que caen fuera de la coronación (con
    el anillo de ``values``) y de las zonas a sostener: sus avisos, como en el resumen
    (:func:`_seed_notices`, en el orden de los lados), o ``()`` si no hay ninguna. Solo leen. Las
    usa ``design.steps.quarry_run`` para pararse sin la confirmación."""
    ring = int(check_quarry_param(CROWN_RING, values.get(CROWN_RING)))
    found: list[Notice] = []
    for side_name in Surface:
        seeds = parts.seeds.get(side_name)
        if seeds is None:
            continue
        groups = yield from quarry._outside_units(seeds, parts.area, parts.start.values, masks,
                                                  ring)
        found.extend(_seed_notices(side_name, groups, masks.grid.cell_area))
        yield
    return tuple(found)


def quarry_compute_steps(request: QuarryRequest, masks: access.MaskSet, parts: QuarryParts,
                         values: Mapping[str, object], *, pending: tuple[str, ...] = (),
                         previous: Mapping[Surface | str, Mapping[str, Any] | None] | None = None,
                         budget_s: float = STEP_BUDGET_S
                         ) -> Generator[Progress, None, QuarryCalculated]:
    """Los pasos que calculan la cantera ``request`` con sus piezas ``parts`` y los parámetros
    ``values`` (clave → valor: los que anotó la operación, los que se resuelven hoy o los
    congelados), sin escribir nada (``yield from``): el techo de conservación de sus zonas a
    conservar, uno para los dos lados (``quarry.conservation_ceiling_steps``, con el talud de
    conservación y el *chamfer* 5×5, :data:`_CEILING_METRIC`), las dos superficies
    (``quarry.quarry_steps``, con el anillo de coronación, el espesor mínimo, la tolerancia, el
    umbral y el aviso de desdoblado), con zonas a conservar, lo que mueven en ellas
    (:func:`_check_conserved`, RF-014-08: más de 0 m³ es ``des.conserve_moved`` y no sale nada que
    crear) y el salto creado de la final y de la explotación (:func:`created_step_steps`, T56;
    RF-014-20, RF-014-21). ``pending``: los nombres de los sectores con la búsqueda pendiente que
    se marcan;
    ``previous``: lo anterior con que se compara cada lado (T51; por superficie, como en los
    ajustes, ``provenance.settings_previous(ajustes, lado)``): con los dos, cada lado se compara
    con el suyo; si falta alguno, ninguno, y la cantera lo dice una vez. Devuelve la
    :class:`QuarryCalculated`: el ``QuarryOutcome`` y sus avisos (:func:`quarry_notices`). Lo
    comparten «Calcular», el recálculo y la reproducción."""
    geometry = masks.grid
    start = parts.start.values
    ring = int(check_quarry_param(CROWN_RING, values.get(CROWN_RING)))
    thickness = number(values, VERIFY_MIN_THICKNESS)
    ceiling = None
    if parts.conserve:
        ceiling = yield from pipeline.forward(quarry.conservation_ceiling_steps(
            parts.conserve, start, geometry, values.get(CONSERVE_SLOPE),  # type: ignore[arg-type]
            metric=_CEILING_METRIC, budget_s=budget_s))
    sides = {Surface(key): pipeline.previous_of(item)
             for key, item in (previous or {}).items() if item is not None}
    compared = len(sides) == len(Surface)
    job = quarry.QuarryJob(
        request, start, masks, parts.domain, values, ring, thickness,
        number(values, TOLERANCE_FACE), number(values, WARNING_RATIO), seeds=parts.seeds,
        floors=parts.joined, ceiling=ceiling, anchors=parts.anchors, pending=pending,
        fill_zones=parts.fill_zones, unsplit_threshold_m=number(values, UNSPLIT_THRESHOLD),
        unsplit_min_area_ha=number(values, UNSPLIT_MIN_AREA),
        to_final_zones=parts.to_final_zones, previous=sides if compared else {})
    outcome: quarry.QuarryOutcome = yield from pipeline.forward(
        quarry.quarry_steps(job, budget_s=budget_s))
    if parts.conserve:
        yield Progress("conserve", 0, 1, "Midiendo lo que se mueve en las zonas a conservar…")
        _check_conserved(request.name, outcome, start, parts.conserve, geometry, thickness)
        yield Progress("conserve", 1, 1, "Nada movido en las zonas a conservar")
    allowed = _allowed(masks)
    created: list[Notice] = []
    for family, grid in ((provenance.FINAL_GRID, outcome.final_grid),
                         (provenance.EXPLOITATION_GRID, outcome.exploitation_grid)):
        created += yield from created_step_steps(
            provenance.dataset_name(family, request.name), np.asarray(grid, dtype=np.float64),
            start, geometry, allowed, values, budget_s=budget_s)
    return QuarryCalculated(outcome, quarry_notices(request, masks, parts, ring, outcome,
                                                    compared=compared, created=created))


_CONSERVE_FIELD = "volumen en las zonas a conservar (m³)"
"""El campo del error de lo movido en las zonas a conservar (RF-014-08)."""


def _check_conserved(name: str, outcome: quarry.QuarryOutcome, start: np.ndarray,
                     zones: Sequence[quarry.ConserveZone], geometry: Grid,
                     min_thickness_m: float) -> None:
    """**RF-014-08** (T47, hallazgo F-8): lo que mueven las dos superficies de la cantera ``name``
    (``outcome``) frente a la de partida ``start`` dentro de las zonas a conservar ``zones``, con
    el espesor mínimo de la 012 (``quarry.conserve_moved``): en cada celda, lo más que mueve una de
    las dos (con ``final ≤ explotación ≤ terreno``, la final; una celda no cuenta dos veces). Más
    de 0 m³ es un **error del diseño** que no se crea —así nunca se crea sin confirmación—, como
    el invariante del orden: ``DesignError`` ``des.conserve_moved`` con el volumen y las partes y,
    detrás, una ``des.conserve_part`` por parte con su zona, su volumen y su centro (m³ y m,
    redondeados al cm). Con el techo de conservación no mueve nada (0 m³ por construcción). Solo
    lee."""
    final = np.asarray(outcome.final_grid, dtype=np.float64)
    exploitation = np.asarray(outcome.exploitation_grid, dtype=np.float64)
    with np.errstate(invalid="ignore"):
        final_depth = np.abs(final - start)
        deeper = np.abs(exploitation - start) > np.where(np.isnan(final_depth), -1.0,
                                                         final_depth)
    design = np.where(deeper, exploitation, final)
    moved = quarry.conserve_moved(design, start, zones, geometry, min_thickness_m)
    if not moved.moved:
        return
    volume = round(moved.volume_m3, 2)
    raise DesignError(
        "des.conserve_moved", obj=f"Cantera «{name}»", field=_CONSERVE_FIELD, value=volume,
        volume=volume, parts=len(moved.parts),
        notes=tuple(("des.conserve_part", {"zone": part.zone, "volume": round(part.volume_m3, 2),
                                           "x": round(part.x, 2), "y": round(part.y, 2)})
                    for part in moved.parts))


def quarry_grids(outcome: quarry.QuarryOutcome) -> tuple[tuple[str, np.ndarray, str], ...]:
    """Las rejillas de la cantera que se escriben (familia, rejilla, lo que es), en el orden de su
    tipo: la explotación y la final (con la regla de orden y, en su caso, «explotación hasta la
    final»), la envolvente de cada lado y la clasificación (códigos de ``CellClass``, sin dato
    fuera del dominio; P-1)."""
    return ((provenance.EXPLOITATION_GRID, outcome.exploitation_grid,
             "la superficie de explotación"),
            (provenance.FINAL_GRID, outcome.final_grid, "la superficie final"),
            (provenance.EXPLOITATION_ENVELOPE_GRID, outcome.exploitation.envelope.grid,
             "la envolvente de la explotación"),
            (provenance.FINAL_ENVELOPE_GRID, outcome.final.envelope.grid,
             "la envolvente de la final"),
            (provenance.CLASSIFICATION_GRID, outcome.classes.grid, "la clasificación"))


def quarry_berm_rows(outcome: quarry.QuarryOutcome) -> list[Row]:
    """Las filas de ``des_bmt_`` de una cantera (:data:`QUARRY_BERM_COLUMNS`): las bermas medidas
    de cada lado tal como se calculó (``SideOutcome.design.berms``), primero las de la final, cada
    una con su superficie delante (:func:`berm_rows`)."""
    return [(side_name.value, *row) for side_name in Surface
            for row in berm_rows(outcome.side(side_name).design.berms)]


def _notice_text(notice: Notice) -> str:
    """Un aviso o una nota como en ``des_rpt_``: su código y sus valores en JSON."""
    return json.dumps({"code": notice.code, "values": dict(notice.values)}, sort_keys=True,
                      ensure_ascii=False, allow_nan=False, default=_plain)


NO_DATA_NOTE = "no_data"
"""La nota de una cota que no existe porque ninguna celda del dominio tiene dato."""


def quarry_report_rows(outcome: quarry.QuarryOutcome, notices: Sequence[Notice]) -> list[Row]:
    """Las filas de ``des_qrp_`` (``quantity, value, unit_code, note``, como ``des_rpt_``) de la
    cantera ``outcome`` (RF-014-15 a RF-014-18): las celdas que cambió la regla de orden (más de
    1 mm; T60); la clasificación del total (excavación de la explotación, desdoblado, relleno de
    restauración y sus celdas, las celdas sin diferencia y sin dato y el espesor mínimo); las
    cotas mínima y máxima de cada superficie (``final_min_m``…; sin dato, una fila sin valor con
    la nota :data:`NO_DATA_NOTE`); con «explotación hasta la final», lo que pasa a la explotación
    y sus celdas; las filas del informe de la 013 de cada lado (:func:`report_rows`) con su
    superficie delante (``final.cut_m3``…) y sus avisos y notas con la superficie en el JSON; y,
    al final, ``notices`` (:func:`quarry_notices`) con su código y sus valores en JSON. Un valor
    NaN o infinito es un error del programa (``ValueError``)."""
    total = outcome.classes.total
    rows: list[Row] = [("order_adjusted_cells", _real("order_adjusted_cells", outcome.adjusted),
                        "-", None)]
    for key, value, unit in (
            ("exp_cut_m3", total.exp_cut_m3, "m3"), ("exp_cut_cells", total.exp_cut_cells, "-"),
            ("unsplit_m3", total.unsplit_m3, "m3"), ("unsplit_cells", total.unsplit_cells, "-"),
            ("restoration_fill_m3", total.fill_m3, "m3"),
            ("restoration_fill_cells", total.fill_cells, "-"),
            ("none_cells", total.none_cells, "-"), ("nodata_cells", total.nodata_cells, "-"),
            ("min_thickness_m", outcome.classes.min_thickness_m, "m")):
        rows.append((key, _real(key, value), unit, None))
    for side_name in Surface:
        levels = total.levels(side_name)
        for index, end in enumerate(("min", "max")):
            key = f"{side_name.value}_{end}_m"
            rows.append((key, None, "m", NO_DATA_NOTE) if levels is None
                        else (key, _real(key, levels[index]), "m", None))
    if outcome.to_final is not None:
        rows.append(("to_final_m3", _real("to_final_m3", outcome.to_final.volume_m3), "m3",
                     None))
        rows.append(("to_final_cells", _real("to_final_cells", outcome.to_final.lowered_cells),
                     "-", None))
    for side_name in Surface:
        side = outcome.side(side_name).design
        for quantity, value, unit, note in report_rows(
                side.report, unassigned_area_m2=side.unassigned_area_m2):
            if quantity in _NOTICE_ROWS:
                data = json.loads(note)
                data["surface"] = side_name.value
                rows.append((quantity, None, None, json.dumps(
                    data, sort_keys=True, ensure_ascii=False, allow_nan=False)))
            else:
                rows.append((f"{side_name.value}.{quantity}", value, unit, note))
    for notice in notices:
        rows.append((notice.severity, None, None, _notice_text(notice)))
    return rows


_NOTICE_ROWS = frozenset({"warning", "note"})


@dataclass(frozen=True, slots=True, eq=False)
class QuarryCalculated:
    """La cantera calculada y sus avisos (``outcome``, ``notices``): lo que devuelven los pasos de
    :func:`compute_quarry_steps`."""

    outcome: quarry.QuarryOutcome
    notices: tuple[Notice, ...]


def compute_quarry_steps(writer: DesignWriter, request: QuarryRequest, masks: access.MaskSet,
                         prepared: PreparedQuarry, values: Mapping[str, object],
                         settings: Mapping[str, Any], budget_s: float = STEP_BUDGET_S
                         ) -> Generator[Progress, None, QuarryCalculated]:
    """Lo mismo que :func:`compute_design_steps` para la cantera ``request`` (spec 014, T19;
    RF-014-29): la calcula (:func:`quarry_compute_steps`, con las piezas de ``prepared``, los
    parámetros ``values`` y los sectores pendientes y lo anterior de cada lado de los ajustes
    ``settings``) y deja sus cinco
    rejillas en los temporales de ``writer`` (:func:`quarry_grids`) y prepara sus dos tablas
    (:func:`quarry_berm_rows`, :func:`quarry_report_rows`), **sin confirmar**. Devuelve la
    :class:`QuarryCalculated`."""
    yield Progress("quarry", 0, 1, f"Preparando la cantera «{request.name}»…")
    parts = prepared.parts
    waiting = set(provenance.settings_pending(settings))
    pending = tuple(ref.name for ref in parts.domain.sectors if ref.code in waiting)
    calculated: QuarryCalculated = yield from quarry_compute_steps(
        request, masks, parts, values, pending=pending,
        previous={side: provenance.settings_previous(settings, side) for side in Surface},
        budget_s=budget_s)
    outcome, notices = calculated.outcome, calculated.notices
    geometry, crs, vertical = parts.start.grid, writer.crs, writer.vertical
    for family, grid, what in quarry_grids(outcome):
        yield from pipeline.forward(_store_steps(
            writer.grid_steps(family, Raster(geometry, grid, crs, vertical)), budget_s, what))
    yield from pipeline.forward(_store_steps(
        writer.table_steps(provenance.BERM_TABLE, quarry_berm_rows(outcome)), budget_s,
        "la tabla de bermas"))
    yield from pipeline.forward(_store_steps(
        writer.table_steps(provenance.QUARRY_REPORT_TABLE, quarry_report_rows(outcome, notices)),
        budget_s, "el informe de la cantera"))
    return calculated


# --- Transiciones con el terreno no afectado (spec 014, T28; RF-014-19 a RF-014-21, RF-014-29) ----


def prepare_transition_units(project: StoreProject, name: str, surface: str, start: str,
                             version: Version, masks: access.MaskSet, *,
                             supersedes: str | None = None
                             ) -> Generator[None, None, PreparedTransition]:
    """Las unidades que preparan la transición ``name`` de la superficie de diseño ``surface`` de
    ``version`` sobre la de partida ``start`` (los nombres de sus datos) con sus ``masks`` ya al
    día (spec 014, T28; RF-014-19): la superficie ha de ser una superficie de diseño de la versión
    (:func:`design_surface_of`; si no, ``DesignError`` ``des.edge_not_design_surface`` con su
    nombre), las dos superficies se leen y se comparan con la rejilla del proyecto
    (``des.surface_*``) y :func:`prepare_edge_transition`. Devuelve la :class:`PreparedTransition`.
    Nada se escribe; los rechazos salen al avanzar."""
    with project.read() as conn:
        origin = design_surface_of(conn, surface, version.uid)
    if origin is None:
        raise DesignError("des.edge_not_design_surface", obj=f"Superficie «{surface}»",
                          field="superficie de diseño", value=surface)
    yield
    frame = project_frame(project)
    design = read_surface(project, surface, version_uid=version.uid, expect=frame,
                          role="superficie de diseño")
    yield
    ground = read_surface(project, start, version_uid=version.uid, expect=frame,
                          role="superficie de partida")
    yield
    operation = prepare_edge_transition(project, name, surface, start, version=version.uid,
                                        masks=masks, supersedes=supersedes)
    yield
    return PreparedTransition(design, ground, operation)


def transition_compute_steps(name: str, surface: np.ndarray, ground: np.ndarray,
                             masks: access.MaskSet, values: Mapping[str, object], *,
                             budget_s: float = STEP_BUDGET_S
                             ) -> Generator[Progress, None, edges.EdgeTransition]:
    """Los pasos que calculan la transición ``name`` de la superficie de diseño ``surface`` sobre
    la de partida ``ground`` (cotas en la rejilla de ``masks``) con los parámetros ``values``
    (clave → valor: los que anotó la operación, los que se resuelven hoy o los congelados), sin
    escribir nada (``yield from``): ``design.edges.edge_transition_steps`` con el ángulo de
    transición, el salto y el porcentaje admitidos, el espesor mínimo y lo que las máscaras
    admiten mover (el corte o el relleno admitidos). Lo comparten «Calcular», el recálculo y la
    reproducción. Devuelve el ``design.edges.EdgeTransition``."""
    allowed = masks.cut_allowed() | masks.fill_allowed()
    angle, threshold, share = (values.get(key) for key in (EDGE_TRANSITION_DEG, EDGE_MAX_STEP,
                                                           EDGE_MIN_SHARE))
    outcome: edges.EdgeTransition = yield from pipeline.forward(edges.edge_transition_steps(
        surface, ground, masks.grid, angle_deg=angle,  # type: ignore[arg-type]
        min_thickness_m=number(values, VERIFY_MIN_THICKNESS),
        threshold_m=threshold, share_pct=share,  # type: ignore[arg-type]
        allowed=allowed, name=name, budget_s=budget_s))
    return outcome


def edge_report_rows(outcome: edges.EdgeTransition) -> list[Row]:
    """Las filas de ``des_erp_`` (``quantity, value, unit_code, note``, como ``des_rpt_``) de la
    transición ``outcome`` (RF-014-19 a RF-014-21): el volumen y las celdas de la transición, su
    ángulo y su área; las parejas del borde de la superficie nueva, las que pasan del salto
    admitido y los porcentajes por encima y dentro; el mayor salto creado (con su signo; su lugar
    en la nota como ``x;y`` en float64 en texto, sin parejas ninguno); el salto y el porcentaje
    admitidos y el espesor mínimo; una fila ``stretch`` por tramo (su mayor salto creado en m, y en
    la nota, en JSON, su número, sus parejas y su centro) y, al final, el aviso de RF-014-21 y sus
    notas con su código y sus valores en JSON. Un valor NaN o infinito es un error del programa
    (``ValueError``)."""
    transition, report = outcome.transition, outcome.report
    rows: list[Row] = []
    for key, value, unit in (
            ("transition_m3", transition.volume_m3, "m3"),
            ("transition_cells", transition.cells, "-"),
            ("transition_area_m2", transition.area_m2, "m2"),
            ("angle_deg", transition.angle_deg, "deg"), ("edge_pairs", report.pairs, "-"),
            ("over_pairs", report.over, "-"), ("over_pct", report.over_pct, "%"),
            ("within_pct", report.within_pct, "%")):
        rows.append((key, _real(key, value), unit, None))
    place = (None if report.x is None or report.y is None else
             f"{_real('created_step_max_at.x', report.x)!r};"
             f"{_real('created_step_max_at.y', report.y)!r}")
    rows.append(("created_step_max_m", _real("created_step_max_m", report.maximum_m), "m", place))
    for key, value, unit in (("threshold_m", report.threshold_m, "m"),
                             ("min_share_pct", report.min_share_pct, "%"),
                             ("min_thickness_m", report.min_thickness_m, "m")):
        rows.append((key, _real(key, value), unit, None))
    for item in report.stretches:
        rows.append(("stretch", _real("stretch", item.maximum_m), "m", json.dumps(
            {"stretch": item.stretch, "pairs": item.pairs, "x": _real("stretch.x", item.x),
             "y": _real("stretch.y", item.y)}, sort_keys=True, allow_nan=False)))
    for notice in outcome.notices:
        rows.append((notice.severity, None, None, _notice_text(notice)))
    return rows


def compute_transition_steps(writer: DesignWriter, name: str, prepared: PreparedTransition,
                             masks: access.MaskSet, values: Mapping[str, object],
                             budget_s: float = STEP_BUDGET_S
                             ) -> Generator[Progress, None, edges.EdgeTransition]:
    """Lo mismo que :func:`compute_design_steps` para la transición ``name`` (spec 014, T28;
    RF-014-19 a RF-014-21, RF-014-29): la calcula (:func:`transition_compute_steps`, con las
    superficies de ``prepared``, las máscaras y los parámetros ``values``), deja su rejilla
    (``des_trn_``) en el temporal de ``writer`` y prepara el informe del salto creado
    (``des_erp_``, :func:`edge_report_rows`), **sin confirmar**. Devuelve el
    ``design.edges.EdgeTransition``."""
    yield Progress(edges.EDGE_PHASE, 0, 1, f"Preparando la transición «{name}»…")
    outcome = yield from transition_compute_steps(name, prepared.surface.values,
                                                  prepared.ground.values, masks, values,
                                                  budget_s=budget_s)
    raster = Raster(prepared.surface.grid, outcome.grid, writer.crs, writer.vertical)
    yield from pipeline.forward(_store_steps(
        writer.grid_steps(provenance.TRANSITION_GRID, raster), budget_s, "la transición"))
    yield from pipeline.forward(_store_steps(
        writer.table_steps(provenance.EDGE_REPORT_TABLE, edge_report_rows(outcome)), budget_s,
        "el informe del salto creado"))
    return outcome


# --- Solo relleno (spec 014, T30; RF-014-22 a RF-014-25, RF-014-29) -----------------------------


def prepare_fill_only_units(project: StoreProject, request: FillOnlyRequest, version: Version,
                            masks: access.MaskSet, *, supersedes: str | None = None
                            ) -> Generator[None, None, PreparedFillOnly]:
    """Las unidades que preparan el diseño «solo relleno» ``request`` de ``version`` con sus
    ``masks`` ya al día (spec 014, T30; RF-014-22, RF-014-24, RF-014-29), como
    :func:`prepare_design_units`: los sectores, la envolvente de la versión, la superficie de
    partida y la rejilla de anclas (leídas y comparadas con la rejilla del proyecto), la etiqueta
    de sector de cada celda, el rechazo de un sector con la búsqueda pendiente que toca la
    envolvente (``des.sector_pending``, RF-013-05) y la revisión congelada con que se compara
    (D-25); además, las láminas de agua de su capa (``design.fronts.water_sheets``: una capa que no
    es de polígonos, sin el campo, una cota que falta o dos láminas que se solapan se rechazan) y
    los intocables de las máscaras con el nombre de su restricción; y :func:`prepare_fill_only`.
    Devuelve la :class:`PreparedFillOnly`. Nada se escribe; los rechazos salen al avanzar."""
    sectors = design_sectors(project, version.uid)
    yield
    frame = project_frame(project)
    envelope = read_surface(
        project, provenance.dataset_name(provenance.ENVELOPE_GRID, request.envelope),
        version_uid=version.uid, expect=frame, role="envolvente")
    yield
    start = read_surface(project, request.start, version_uid=version.uid, expect=frame,
                         role="superficie de partida")
    yield
    anchors = None
    if request.anchor_grid is not None:
        anchors = read_surface(project, request.anchor_grid, version_uid=version.uid,
                               expect=frame, role="anclas").values
        yield
    refs, labels = sector_layout(project, masks)
    yield
    with np.errstate(invalid="ignore"):
        domain = np.isfinite(envelope.values)
    touched_codes = pipeline.touched_in(refs, labels, domain)
    refuse_pending(item for item in sectors if item.code in touched_codes)  # RF-013-05
    waiting = [item.code for item in sectors if item.pending and item.code in touched_codes]
    with project.read() as conn:
        previous = previous_comparison(conn, version, provenance.FILL_ONLY, request.name)
        names = {code: name for code, (name, _kind) in constraint_names(conn).items() if name}
    yield
    water = None
    if request.water is not None:
        water = fronts.water_sheets(_features(project, request.water.layer), request.water,
                                    masks.grid)
        yield
    parts = FillOnlyParts(envelope, start, anchors, tuple(refs), labels, water,
                          fronts.untouchable_zones(masks, names))
    operation = prepare_fill_only(project, request, version=version.uid, masks=masks,
                                  sectors=sectors, pending_sectors=waiting,
                                  touched_sectors=touched_codes, previous=previous,
                                  supersedes=supersedes)
    yield
    return PreparedFillOnly(parts, operation)


def fill_only_compute_steps(request: FillOnlyRequest, masks: access.MaskSet, parts: FillOnlyParts,
                            values: Mapping[str, object], *, pending: tuple[str, ...] = (),
                            previous: Mapping[str, Any] | None = None,
                            budget_s: float = STEP_BUDGET_S
                            ) -> Generator[Progress, None, fronts.FillOnlyOutcome]:
    """Los pasos que calculan el diseño «solo relleno» ``request`` con sus piezas ``parts`` y los
    parámetros ``values`` (clave → valor: los que anotó la operación, los que se resuelven hoy o
    los congelados), sin escribir nada (``yield from``): el escalonado en relleno de la 013 de la
    envolvente (``pipeline.DesignJob`` con los perfiles, los taludes impuestos de los sectores, el
    espesor mínimo, la tolerancia de cara y el umbral de aviso de ``values``) dentro de
    ``design.fronts.fill_only_steps`` (A12: sobre el terreno con las láminas, solo en el relleno
    admitido, nunca por debajo del terreno, y sus rechazos de RF-014-25) y el salto creado de su
    superficie frente al terreno registrado (:func:`created_step_steps`, T56; RF-014-20,
    RF-014-21), detrás de sus avisos (``FillOnlyOutcome.notices``). ``pending``: los nombres de
    los sectores con la búsqueda pendiente que se marcan; ``previous``: lo anterior con que se
    compara (D-25). Lo comparten «Calcular», el recálculo y la reproducción. Devuelve el
    ``design.fronts.FillOnlyOutcome``."""
    design = request.design
    profiles = pipeline.bench_profiles(values, [
        design.base_profile, *(profile for _sector, profile in design.sector_profiles)])
    job = pipeline.DesignJob(
        design, parts.start.grid, parts.start.values, parts.envelope.values, masks,
        tuple(parts.refs), parts.labels, pipeline.imposed_from(values, parts.refs), profiles,
        parts.anchors, number(values, VERIFY_MIN_THICKNESS), number(values, TOLERANCE_FACE),
        number(values, WARNING_RATIO), pipeline.previous_of(previous), pending)
    outcome: fronts.FillOnlyOutcome = yield from pipeline.forward(fronts.fill_only_steps(
        fronts.FillOnlyJob(job, parts.water, parts.untouchables), budget_s=budget_s))
    created = yield from created_step_steps(
        provenance.dataset_name(provenance.DESIGN_GRID, request.name), outcome.surface,
        parts.start.values, parts.start.grid, _allowed(masks), values, budget_s=budget_s)
    return replace(outcome, notices=(*outcome.notices, *created)) if created else outcome


def fill_only_report_rows(outcome: fronts.FillOnlyOutcome) -> list[Row]:
    """Las filas de ``des_rpt_`` de un diseño «solo relleno» (``quantity, value, unit_code,
    note``; spec 014, T30; RF-014-22, RF-014-24): las del informe de su escalonado de la 013
    (:func:`report_rows`: frente al terreno registrado, T55) y, antes de sus avisos y notas, el
    corte frente al terreno registrado (``fill_only_cut_m3``, m³), las celdas en que la lámina de
    agua es el terreno de partida (``water_cells``) y los avisos propios del diseño (los de las
    láminas que caen fuera del relleno admitido o en un intocable, con su código y sus valores en
    JSON). Un valor NaN o infinito es un error del programa (``ValueError``)."""
    design = outcome.design
    rows = report_rows(design.report, unassigned_area_m2=design.unassigned_area_m2)
    first = next((index for index, row in enumerate(rows) if row[0] in _NOTICE_ROWS), len(rows))
    rows[first:first] = [
        ("fill_only_cut_m3", _real("fill_only_cut_m3", outcome.cut_m3), "m3", None),
        ("water_cells", _real("water_cells", outcome.water_cells), "-", None),
        *((notice.severity, None, None, _notice_text(notice)) for notice in outcome.notices)]
    return rows


def compute_fill_only_steps(writer: DesignWriter, request: FillOnlyRequest,
                           masks: access.MaskSet, prepared: PreparedFillOnly,
                           values: Mapping[str, object], settings: Mapping[str, Any],
                           budget_s: float = STEP_BUDGET_S
                           ) -> Generator[Progress, None, fronts.FillOnlyOutcome]:
    """Lo mismo que :func:`compute_design_steps` para el diseño «solo relleno» ``request`` (spec
    014, T30; RF-014-22 a RF-014-25, RF-014-29): lo calcula (:func:`fill_only_compute_steps`, con
    las piezas de ``prepared``, los parámetros ``values`` y, de los ajustes ``settings``, los
    sectores pendientes y lo anterior con que se compara), deja su superficie (``des_srf_``) en el
    temporal de ``writer`` y prepara su informe (``des_rpt_``, :func:`fill_only_report_rows`),
    **sin confirmar**. Devuelve el ``design.fronts.FillOnlyOutcome``."""
    yield Progress(fronts.FILL_ONLY_PHASE, 0, 1,
                   f"Preparando el diseño «solo relleno» «{request.name}»…")
    parts = prepared.parts
    waiting = set(provenance.settings_pending(settings))
    pending = tuple(ref.name for ref in parts.refs if ref.code in waiting)
    outcome = yield from fill_only_compute_steps(
        request, masks, parts, values, pending=pending,
        previous=provenance.settings_previous(settings), budget_s=budget_s)
    raster = Raster(parts.start.grid, outcome.surface, writer.crs, writer.vertical)
    yield from pipeline.forward(_store_steps(
        writer.grid_steps(provenance.DESIGN_GRID, raster), budget_s, "la superficie de diseño"))
    yield from pipeline.forward(_store_steps(
        writer.table_steps(provenance.REPORT_TABLE, fill_only_report_rows(outcome)), budget_s,
        "el informe"))
    return outcome


# --- El ajuste a un límite nuevo (spec 014, T32; RF-014-27 a RF-014-29) ---------------------------


def prepare_refit_units(project: StoreProject, request: RefitRequest, version: Version,
                        masks: access.MaskSet, *, supersedes: str | None = None
                        ) -> Generator[None, None, PreparedRefit]:
    """Las unidades que preparan el ajuste ``request`` en ``version`` con sus ``masks`` (las del
    límite nuevo) ya al día (spec 014, T32; RF-014-27): cada superficie ha de ser una superficie de
    diseño de la versión de :data:`REFIT_SOURCES` (si no, ``DesignError``
    ``des.edge_not_design_surface`` con su nombre), su perfil sale de la operación que la creó
    (:func:`refit_profiles`, P-3) y su cara y su factor de malla, de lo que **anotó** esa operación
    (T49: no los de hoy; ``des.refit_face_missing`` si no los anotó); las superficies y la de
    partida se leen y se comparan con la rejilla del proyecto (``des.surface_*``); de cada
    superficie que sale de una cantera, la cantera, su lado y su orden (:func:`_quarry_link`) y, si
    la petición no lleva la otra de esa cantera, la otra tal como está en la versión, si la tiene
    (T53, RF-014-14: con ella se compara después de ajustarla); el aviso de cada diseño obsoleto
    del que salen (:func:`_stale_designs`, T54, RF-014-31: recalcularlo sustituye el ajuste); los
    sectores con la etiqueta de cada celda; y :func:`prepare_refit`. Devuelve el
    :class:`PreparedRefit`. Nada se escribe; los rechazos salen al avanzar."""
    with project.read() as conn:
        names = MappingProxyType(profile_names(conn))
        sources = _refit_sources(conn, request, version.uid, names)
        _pairs, alone = _quarry_pairs([link[:2] for *_source, link in sources])
        wanted = [name for name in dict.fromkeys(_other_surface(*sources[at][4][:2])
                                                 for at in alone)
                  if design_surface_of(conn, name, version.uid) is not None]
        stale = _stale_designs(conn, request.surfaces, version.uid)
    yield
    frame = project_frame(project)
    parts: list[RefitPart] = []
    for surface, base, sectors, values, (quarry_name, side, order) in sources:
        raster = read_surface(project, surface, version_uid=version.uid, expect=frame,
                              role="superficie de diseño")
        parts.append(RefitPart(surface, raster, base, sectors, MappingProxyType(values),
                               quarry_name, side, order))
        yield
    others: dict[str, Raster] = {}
    for name in wanted:
        others[name] = read_surface(project, name, version_uid=version.uid, expect=frame,
                                    role="superficie de diseño")
        yield
    ground = read_surface(project, request.start, version_uid=version.uid, expect=frame,
                          role="superficie de partida")
    yield
    refs, labels = sector_layout(project, masks)
    yield
    operation = prepare_refit(project, request, version=version.uid, masks=masks,
                              faces={part.name: part.values for part in parts},
                              supersedes=supersedes)
    yield
    return PreparedRefit(tuple(parts), ground, refs, labels, names, operation,
                         MappingProxyType(others), stale)


def _other_surface(quarry_name: str, side: Surface | None) -> str:
    """El dato de la otra superficie de la cantera ``quarry_name`` frente a la de ``side``
    (``des_fin_<cantera>`` de la explotación, ``des_exp_<cantera>`` de la final; T53)."""
    family = (provenance.FINAL_GRID if side is Surface.EXPLOITATION
              else provenance.EXPLOITATION_GRID)
    return provenance.dataset_name(family, quarry_name)


def _quarry_pairs(links: Sequence[tuple[str, Surface | None]]
                  ) -> tuple[list[tuple[int, int]], list[int]]:
    """Las superficies de un ajuste que salen de una cantera (``links``: el nombre de la cantera,
    ``""`` si no sale de una, y el lado de cada superficie, en el orden de la petición; T53,
    RF-014-14): las parejas (el índice de su final y el de su explotación) de cada cantera de la que
    la petición lleva una superficie de cada lado, y los índices de las demás que salen de una
    cantera (sin la otra, o con más de una de un lado: ninguna se ata y cada una se compara con la
    otra de su cantera)."""
    by_quarry: dict[str, list[int]] = {}
    for at, (name, side) in enumerate(links):
        if name and side is not None:
            by_quarry.setdefault(name, []).append(at)
    pairs: list[tuple[int, int]] = []
    alone: list[int] = []
    for found in by_quarry.values():
        finals = [at for at in found if links[at][1] is Surface.FINAL]
        exploitations = [at for at in found if links[at][1] is Surface.EXPLOITATION]
        if len(finals) == 1 and len(exploitations) == 1:
            pairs.append((finals[0], exploitations[0]))
        else:
            alone.extend(found)
    return pairs, sorted(alone)


def _ordered_refits(parts: Sequence[RefitPart], found: Sequence[refit.Refit], start: np.ndarray,
                    others: Mapping[str, Raster], geometry: Grid
                    ) -> tuple[list[refit.Refit], list[Notice]]:
    """**El orden de las dos superficies después del ajuste** (T53; RF-014-14 frente a
    RF-014-27, hallazgo F-15; la propuesta por defecto que aceptó Samuel): de cada cantera de la
    que el ajuste lleva sus dos superficies (:func:`_quarry_pairs`), la regla de orden de esa
    cantera (``quarry.order_surfaces`` con su orden, frente a la de partida ``start``) sobre las dos
    ajustadas y ``quarry.check_order`` (``des.quarry_order_broken``, un error del programa: no se
    crea nada); la rejilla de cada :class:`~design.refit.Refit` pasa a ser la atada y su volumen y
    sus celdas siguen siendo los de su cara (CE-014-08); la nota ``des.refit_order`` dice la
    cantera, la superficie que cambió la regla y sus celdas (las que tenían la final más de 1 mm
    por encima, ``OrderedSurfaces.adjusted``; T60), y ninguna nota si no cambió ninguna (T61). De
    cada superficie de una cantera sin la otra,
    si la otra tal como está (``others``) deja la final más de 1 mm por encima de la explotación,
    el aviso ``des.refit_order_side`` con las celdas y cuánto (m). Devuelve los ajustes y las
    notas y avisos; ninguna entrada se modifica."""
    refits = list(found)
    notices: list[Notice] = []
    pairs, alone = _quarry_pairs([(part.quarry, part.side) for part in parts])
    for final_at, exploitation_at in pairs:
        final, exploitation = parts[final_at], parts[exploitation_at]
        ordered = quarry.order_surfaces(Order(final.order), refits[final_at].grid,
                                        refits[exploitation_at].grid, start)
        quarry.check_order(final.quarry, ordered.final, ordered.exploitation, start, geometry)
        refits[final_at] = replace(refits[final_at], grid=ordered.final)
        refits[exploitation_at] = replace(refits[exploitation_at], grid=ordered.exploitation)
        changed = exploitation if ordered.order is Order.FINAL_FIRST else final
        if ordered.adjusted:  # T61: sin nota si la regla no cambia ninguna celda más de 1 mm
            notices.append(Notice(refit.ORDER_CODE, {
                "quarry": final.quarry, "surface": changed.name, "cells": ordered.adjusted}))
    for at in alone:
        part = parts[at]
        other = others.get(part.other or "")
        if other is None:
            continue
        upper, lower = ((refits[at].grid, other.values) if part.side is Surface.FINAL
                        else (other.values, refits[at].grid))
        with np.errstate(invalid="ignore"):
            above = upper - lower
            broken = above > quarry.ORDER_TOLERANCE_M
        cells = int(np.count_nonzero(broken))
        if cells:
            notices.append(Notice(refit.ORDER_SIDE_CODE, {
                "surface": part.name, "quarry": part.quarry, "other": part.other,
                "cells": cells, "above": round(float(above[broken].max()), 3)}))
    return refits, notices


def refit_compute_steps(request: RefitRequest, masks: access.MaskSet, prepared: PreparedRefit,
                        values: Mapping[str, object], *, budget_s: float = STEP_BUDGET_S
                        ) -> Generator[Progress, None, refit.RefitOutcome]:
    """Los pasos que calculan el ajuste ``request`` con lo de ``prepared``, las máscaras del límite
    nuevo y los parámetros ``values`` (clave → valor: los que anotó la operación o los que se
    resuelven hoy; el espesor mínimo), sin escribir nada (``yield from``; spec 014, T32;
    RF-014-27, RF-014-28): la cara de cada perfil de cada superficie, la que anotó la operación
    que hizo su diseño (``RefitPart.values``, T49: no la de hoy; ``design.refit.profile_faces``);
    **antes de calcular nada**, el ángulo que traiga la petición para una superficie, que ha de ser
    esa cara (``design.refit.check_angle``: ``des.refit_angle``); cada superficie con
    ``design.refit.refit_steps``, la pendiente de su perfil en cada celda según su sector
    (``face_slope``) y el espesor mínimo; y, después, el orden de las dos superficies de una
    cantera (:func:`_ordered_refits`, T53, RF-014-14: con las dos, la regla de orden de la cantera
    y ``check_order`` antes de ofrecer «Crear»; con una sola, un aviso si queda del lado equivocado
    de la otra). Devuelve el ``design.refit.RefitOutcome``, con los avisos de los diseños obsoletos
    de los que sale al final (``prepared.stale_notices``, T54) y el salto creado de cada
    superficie ajustada (:func:`created_step_steps`, T56; RF-014-20, RF-014-21), con el nombre de
    su salida, delante de los del orden (``RefitOutcome.notices``)."""
    faces = [refit.profile_faces(part.values, part.profiles, prepared.names)
             for part in prepared.parts]
    angles = dict(request.angles)
    for part, own in zip(prepared.parts, faces, strict=True):  # RF-014-28, antes de calcular
        refit.check_angle(part.name, [own[code] for code in part.profiles],
                          angles.get(part.name))
    thickness = number(values, VERIFY_MIN_THICKNESS)
    found: list[refit.Refit] = []
    for part, own in zip(prepared.parts, faces, strict=True):
        assigned = dict(part.sector_profiles)
        slope = refit.face_slope(
            prepared.labels, own[part.base_profile],
            [own[assigned.get(ref.code, part.base_profile)] for ref in prepared.refs])
        item: refit.Refit = yield from pipeline.forward(refit.refit_steps(
            part.surface.values, prepared.ground.values, masks, slope, thickness,
            name=part.name, version=prepared.start.version_code, budget_s=budget_s))
        found.append(item)
    if any(part.quarry for part in prepared.parts):
        yield Progress(refit.REFIT_PHASE, 0, 1,
                       f"Comprobando el orden de las superficies de «{request.name}»…")
    tied, orders = _ordered_refits(prepared.parts, found, prepared.ground.values,
                                   prepared.others, masks.grid)
    allowed = _allowed(masks)
    created: list[Notice] = []
    for part, item in zip(prepared.parts, tied, strict=True):
        created += yield from created_step_steps(
            provenance.refit_output(request.name, part.name), item.grid, prepared.ground.values,
            masks.grid, allowed, values, budget_s=budget_s)
    return refit.refit_outcome(request.name, tied, orders, prepared.stale_notices,
                               created_notices=created)


def compute_refit_steps(writer: DesignWriter, request: RefitRequest, masks: access.MaskSet,
                        prepared: PreparedRefit, values: Mapping[str, object],
                        budget_s: float = STEP_BUDGET_S
                        ) -> Generator[Progress, None, refit.RefitOutcome]:
    """Lo mismo que :func:`compute_design_steps` para el ajuste ``request`` (spec 014, T32;
    RF-014-27 a RF-014-29): lo calcula (:func:`refit_compute_steps`) y deja la superficie ajustada
    de cada superficie (``des_adj_<nombre>_<superficie>``, una parte de la familia por superficie,
    ``provenance.refit_part``) en el temporal de ``writer``, **sin confirmar**. Devuelve el
    ``design.refit.RefitOutcome``."""
    yield Progress(refit.REFIT_PHASE, 0, 1, f"Preparando el ajuste «{request.name}»…")
    outcome = yield from refit_compute_steps(request, masks, prepared, values, budget_s=budget_s)
    for part, item in zip(prepared.parts, outcome.refits, strict=True):
        raster = Raster(part.surface.grid, item.grid, writer.crs, writer.vertical)
        yield from pipeline.forward(_store_steps(
            writer.grid_steps(provenance.REFIT_GRID, raster,
                              part=provenance.refit_part(part.name)),
            budget_s, f"el ajuste de «{part.name}»"))
    return outcome


def compute_envelope_steps(project: StoreProject, writer: DesignWriter, request: EnvelopeRequest,
                           masks: access.MaskSet, seeds: SeedSet, values: Mapping[str, object],
                           budget_s: float = STEP_BUDGET_S
                           ) -> Generator[Progress, None, pipeline.EnvelopeOutcome]:
    """Los pasos que calculan la envolvente de ``request`` con ``seeds`` y la dejan en el temporal
    de su ``writer`` (``yield from``; **sin confirmar**: quien llama completa con
    :meth:`DesignWriter.commit` o cierra el escritor). ``values`` son los parámetros (clave →
    valor) con que se calcula: los que anotó la operación al empezar (``recompute``) o los que se
    resuelven hoy («Calcular»). Devuelve el :class:`~design.pipeline.EnvelopeOutcome`."""
    yield Progress("envelope", 0, 1, "Preparando la envolvente…")
    domain = seeds.domain
    slope = pipeline.envelope_slope(request, domain.sectors, domain.labels, values)
    start = None
    if pipeline.uses_start_surface(request):
        assert request.seeds.surface is not None  # seed_units lo comprobó
        start = read_surface(project, request.seeds.surface, version_uid=masks.version_uid,
                             expect=project_frame(project), role="semillas").values
    job = pipeline.EnvelopeJob(request, seeds, slope, start, number(values, VERIFY_MIN_THICKNESS))
    outcome: pipeline.EnvelopeOutcome = yield from pipeline.forward(
        pipeline.envelope_compute_steps(job, budget_s=budget_s))
    raster = Raster(seeds.geometry, outcome.grid, writer.crs, writer.vertical)
    yield from pipeline.forward(_store_steps(
        writer.grid_steps(provenance.ENVELOPE_GRID, raster), budget_s, "la envolvente"))
    return outcome


def compute_design_steps(project: StoreProject, writer: DesignWriter, request: DesignRequest,
                         surface: str, masks: access.MaskSet, prepared: PreparedDesign,
                         values: Mapping[str, object], settings: Mapping[str, Any],
                         budget_s: float = STEP_BUDGET_S
                         ) -> Generator[Progress, None, pipeline.DesignOutcome]:
    """Lo mismo que :func:`compute_envelope_steps` para el escalonado ``request`` sobre
    ``surface`` y la ``prepared.envelope``: deja sus dos rejillas en los temporales de ``writer``
    y prepara sus dos tablas. ``settings`` son los ajustes de la operación (los sectores con la
    búsqueda pendiente y lo anterior con que se compara)."""
    yield Progress("benching", 0, 1, "Preparando el escalonado…")
    frame = project_frame(project)
    start = read_surface(project, surface, version_uid=masks.version_uid, expect=frame,
                         role="superficie de partida")
    anchors = None
    if request.anchor_grid is not None:
        anchors = read_surface(project, request.anchor_grid, version_uid=masks.version_uid,
                               expect=frame, role="anclas").values
    profiles = pipeline.bench_profiles(values, [
        request.base_profile, *(profile for _sector, profile in request.sector_profiles)])
    waiting = set(provenance.settings_pending(settings))
    refs = prepared.refs
    pending = tuple(ref.name for ref in refs if ref.code in waiting)
    job = pipeline.DesignJob(
        request, start.grid, start.values, prepared.envelope.values, masks, tuple(refs),
        prepared.labels, pipeline.imposed_from(values, refs), profiles, anchors,
        number(values, VERIFY_MIN_THICKNESS), number(values, TOLERANCE_FACE),
        number(values, WARNING_RATIO), pipeline.previous_of(provenance.settings_previous(settings)),
        pending)
    outcome: pipeline.DesignOutcome = yield from pipeline.forward(
        pipeline.design_compute_steps(job, budget_s=budget_s))
    geometry, crs, vertical = start.grid, writer.crs, writer.vertical
    for family, grid, what in (
            (provenance.DESIGN_GRID, outcome.design, "la superficie de diseño"),
            (provenance.BERMS_GRID, outcome.berms.grid, "las cotas de las bermas")):
        yield from pipeline.forward(_store_steps(
            writer.grid_steps(family, Raster(geometry, grid, crs, vertical)), budget_s, what))
    yield from pipeline.forward(_store_steps(
        writer.table_steps(provenance.BERM_TABLE, berm_rows(outcome.berms)), budget_s,
        "la tabla de bermas"))
    yield from pipeline.forward(_store_steps(
        writer.table_steps(provenance.REPORT_TABLE, report_rows(
            outcome.report, unassigned_area_m2=outcome.unassigned_area_m2)), budget_s,
        "el informe"))
    return outcome


def run_envelope(project: StoreProject, request: EnvelopeRequest, *, version: str | None,
                 masks: access.MaskSet | None = None, supersedes: str | None = None,
                 budget_s: float = STEP_BUDGET_S) -> tuple[OperationHandle, Iterator[Progress]]:
    """Calcula y registra ``request`` en la versión ``version`` **de una vez**, sin pedir
    confirmación (el cálculo sin ventana: las funciones del dominio, el hito H1, y el recálculo de
    lo obsoleto, :func:`recompute_run`; el «Crear» tras «Calcular» de la ventana, D-14, es otra
    cosa): empieza la operación ``des.envelope`` —si ``supersedes`` es la de una anterior, la
    sustituye, quedándose con los nombres de sus datos— con lo que lee hoy (las máscaras de la
    versión, que compila antes si no están al día; los sectores y sus búsquedas; la superficie de
    las semillas; los parámetros de los perfiles que asigna, resueltos versión → proyecto) y
    devuelve su ``OperationHandle`` «en curso» y sus pasos, que avanza quien la llama: calculan
    (``design.pipeline``), escriben la rejilla en su temporal y completan la operación en una
    transacción; el último lleva el :class:`Stored`. Cerrarlos antes, o un fallo, no dejan nada y la
    operación queda cancelada o fallida.

    Al llamar, sin empezar nada: los rechazos de la versión (``VersionError``), del dominio y de
    las semillas (``seed_units``), de RF-013-05 (``des.sector_pending``), del nombre
    (``des.operation_name_repeated``) y de un perfil sin valor (RF-013-19)."""
    found = require_version(project, version, provenance.ENVELOPE)
    loaded = _loaded_masks(project, found, masks)
    prepared = _result_of(prepare_envelope_units(project, request, found, loaded,
                                                 supersedes=supersedes))
    handle = prepared.start.begin(project)
    return handle, _envelope_run(project, handle, request, loaded, prepared.seeds, budget_s)


def run_design(project: StoreProject, request: DesignRequest, surface: str, *,
               version: str | None, masks: access.MaskSet | None = None,
               supersedes: str | None = None, budget_s: float = STEP_BUDGET_S
               ) -> tuple[OperationHandle, Iterator[Progress]]:
    """Lo mismo que :func:`run_envelope` para ``des.stepped_design``: escalona la envolvente
    ``request.envelope`` de la versión sobre la superficie de partida ``surface`` (el nombre de su
    dato), con los perfiles y las máscaras de la versión; compara el desmonte y el terraplén con
    los de la revisión congelada más reciente (:func:`previous_comparison`) y escribe la superficie
    de diseño, las cotas de las bermas, su tabla y el informe. Rechaza, además, un sector que toca
    el dominio con la búsqueda pendiente (RF-013-05)."""
    found = require_version(project, version, provenance.STEPPED)
    loaded = _loaded_masks(project, found, masks)
    prepared = _result_of(prepare_design_units(project, request, surface, found, loaded,
                                               supersedes=supersedes))
    handle = prepared.start.begin(project)
    return handle, _design_run(project, handle, request, surface, loaded, prepared, budget_s)


def run_excavation_area(project: StoreProject, name: str, surface: str, *, version: str | None,
                        masks: access.MaskSet | None = None, supersedes: str | None = None,
                        budget_s: float = STEP_BUDGET_S
                        ) -> tuple[OperationHandle, Iterator[Progress]]:
    """Lo mismo que :func:`run_envelope` para ``des.excavation_area`` (spec 014, T19; RF-014-01):
    el recinto ``name`` de la versión sobre la superficie de partida ``surface``, de una vez y sin
    confirmar (el recálculo de lo obsoleto, :func:`recompute_run`). Al llamar, sin empezar nada,
    los rechazos de :func:`prepare_area_units` (un recinto vacío, el nombre…)."""
    found = require_version(project, version, provenance.EXCAVATION_AREA)
    loaded = _loaded_masks(project, found, masks)
    prepared = _result_of(prepare_area_units(project, name, surface, found, loaded,
                                             supersedes=supersedes))
    handle = prepared.start.begin(project)
    return handle, _area_run(project, handle, name, prepared, budget_s)


def run_quarry(project: StoreProject, request: QuarryRequest, *, version: str | None,
               masks: access.MaskSet | None = None, supersedes: str | None = None,
               budget_s: float = STEP_BUDGET_S) -> tuple[OperationHandle, Iterator[Progress]]:
    """Lo mismo que :func:`run_envelope` para ``des.quarry`` (spec 014, T19; RF-014-29,
    RF-014-31): las dos superficies de ``request`` en la versión, de una vez y sin confirmar (el
    recálculo de lo obsoleto, :func:`recompute_run`), con lo que lee hoy: las máscaras de la
    versión, los sectores, la superficie de partida, las capas y los parámetros, resueltos versión
    → proyecto. Al llamar, sin empezar nada, los rechazos de :func:`prepare_quarry_units` (un
    sector del recinto con la búsqueda pendiente, RF-014-30; un perfil o un parámetro de la 014 sin
    valor; las capas…)."""
    found = require_version(project, version, provenance.QUARRY)
    loaded = _loaded_masks(project, found, masks)
    prepared = _result_of(prepare_quarry_units(project, request, found, loaded,
                                               supersedes=supersedes))
    handle = prepared.start.begin(project)
    return handle, _quarry_run(project, handle, request, loaded, prepared, budget_s)


def run_edge_transition(project: StoreProject, name: str, surface: str, start: str, *,
                        version: str | None, masks: access.MaskSet | None = None,
                        supersedes: str | None = None, budget_s: float = STEP_BUDGET_S
                        ) -> tuple[OperationHandle, Iterator[Progress]]:
    """Lo mismo que :func:`run_envelope` para ``des.edge_transition`` (spec 014, T28; RF-014-19,
    RF-014-31): la transición ``name`` de la superficie de diseño ``surface`` sobre la de partida
    ``start``, de una vez y sin confirmar (el recálculo de lo obsoleto, :func:`recompute_run`),
    con lo que lee hoy: las máscaras de la versión, las dos superficies y los parámetros,
    resueltos versión → proyecto. Al llamar, sin empezar nada, los rechazos de
    :func:`prepare_transition_units` (una superficie que no es de diseño, el ángulo sin valor, el
    nombre…)."""
    found = require_version(project, version, provenance.EDGE_TRANSITION)
    loaded = _loaded_masks(project, found, masks)
    prepared = _result_of(prepare_transition_units(project, name, surface, start, found, loaded,
                                                   supersedes=supersedes))
    handle = prepared.start.begin(project)
    return handle, _transition_run(project, handle, name, loaded, prepared, budget_s)


def run_fill_only(project: StoreProject, request: FillOnlyRequest, *, version: str | None,
                  masks: access.MaskSet | None = None, supersedes: str | None = None,
                  budget_s: float = STEP_BUDGET_S) -> tuple[OperationHandle, Iterator[Progress]]:
    """Lo mismo que :func:`run_design` para ``des.fill_only`` (spec 014, T30; RF-014-22,
    RF-014-31): el diseño «solo relleno» ``request`` de la versión, de una vez y sin confirmar (el
    recálculo de lo obsoleto, :func:`recompute_run`), con lo que lee hoy: las máscaras de la
    versión, los sectores, la envolvente, la superficie de partida, la capa de láminas y los
    parámetros, resueltos versión → proyecto. Al llamar, sin empezar nada, los rechazos de
    :func:`prepare_fill_only_units` (un sector pendiente que toca la envolvente, RF-013-05; las
    láminas; un perfil sin valor; el nombre…)."""
    found = require_version(project, version, provenance.FILL_ONLY)
    loaded = _loaded_masks(project, found, masks)
    prepared = _result_of(prepare_fill_only_units(project, request, found, loaded,
                                                  supersedes=supersedes))
    handle = prepared.start.begin(project)
    return handle, _fill_only_run(project, handle, request, loaded, prepared, budget_s)


def run_refit(project: StoreProject, request: RefitRequest, *, version: str | None,
              masks: access.MaskSet | None = None, supersedes: str | None = None,
              budget_s: float = STEP_BUDGET_S) -> tuple[OperationHandle, Iterator[Progress]]:
    """Lo mismo que :func:`run_envelope` para ``des.refit`` (spec 014, T32; RF-014-27,
    RF-014-31): el ajuste ``request`` de la versión, de una vez y sin confirmar (el recálculo de lo
    obsoleto, :func:`recompute_run`), con lo que lee hoy: las máscaras de la versión (el límite
    vigente), las superficies, la de partida, los sectores y los parámetros, resueltos versión →
    proyecto. Al llamar, sin empezar nada, los rechazos de :func:`prepare_refit_units` (una
    superficie que no es de diseño, un perfil sin cara, el nombre…)."""
    found = require_version(project, version, provenance.REFIT)
    loaded = _loaded_masks(project, found, masks)
    prepared = _result_of(prepare_refit_units(project, request, found, loaded,
                                              supersedes=supersedes))
    handle = prepared.start.begin(project)
    return handle, _refit_run(project, handle, request, loaded, prepared, budget_s)


def recompute_run(request: RecomputeRequest, *, budget_s: float = STEP_BUDGET_S
                  ) -> tuple[OperationHandle, Iterator[Progress]]:
    """Repite la operación de ``des`` de ``request`` (``RecomputeRequest`` de «Recalcular lo
    obsoleto», RF-008-26; RF-013-17; plan 013 §5.3.2): **sin pedir confirmación** —la operación ya
    existe y se repite con sus ajustes—, empieza la operación nueva, que sustituye a la anterior en
    la revisión abierta de **su** versión (:func:`run_envelope`, :func:`run_design` y, de la 014,
    :func:`run_excavation_area`, :func:`run_quarry`, :func:`run_edge_transition`,
    :func:`run_fill_only` y :func:`run_refit`; RF-014-31; de la 015, la plataforma,
    ``design.entity_store.recompute_platform``, con los parámetros vigentes de su entidad en su versión,
    RF-015-02, y la declaración de restricciones de las entidades, ``recompute_declaration``, con las
    entidades vivas de la versión, RF-015-10), con lo que
    lee hoy: las máscaras de la versión, los sectores, las superficies y los parámetros, resueltos
    de nuevo versión → proyecto (un perfil cambiado solo en V02 se lee de V02). Devuelve su
    ``OperationHandle`` «en curso» y sus pasos, que avanza quien la llama (en Blender, la cola de
    recálculo); el último lleva el :class:`Stored`.

    Al llamar, sin empezar nada: ``TypeError``/``ValueError`` si no es una petición de un tipo de
    :data:`RECOMPUTED` o sus ajustes no son los de su tipo; los rechazos de :func:`run_envelope` y
    :func:`run_design` (un recálculo tampoco diseña en un sector sin búsqueda: RF-013-05)."""
    if not isinstance(request, RecomputeRequest):
        raise TypeError(f"se recalcula una RecomputeRequest, no {request!r}")
    if request.op_type not in RECOMPUTED:
        raise ValueError(f"recompute_run repite {', '.join(RECOMPUTED)}, no «{request.op_type}»")
    project: StoreProject = request.project  # type: ignore[assignment]
    if request.op_type == provenance.ENVELOPE:
        return run_envelope(project, provenance.envelope_request(request.settings),
                            version=request.version, supersedes=request.operation_uid,
                            budget_s=budget_s)
    if request.op_type == provenance.EXCAVATION_AREA:
        name, surface = provenance.excavation_area_start(request.settings)
        return run_excavation_area(project, name, surface, version=request.version,
                                   supersedes=request.operation_uid, budget_s=budget_s)
    if request.op_type == provenance.QUARRY:
        return run_quarry(project, provenance.quarry_request(request.settings),
                          version=request.version, supersedes=request.operation_uid,
                          budget_s=budget_s)
    if request.op_type == provenance.EDGE_TRANSITION:
        name, surface, start = provenance.transition_start(request.settings)
        return run_edge_transition(project, name, surface, start, version=request.version,
                                   supersedes=request.operation_uid, budget_s=budget_s)
    if request.op_type == provenance.FILL_ONLY:
        return run_fill_only(project, provenance.fill_only_request(request.settings),
                             version=request.version, supersedes=request.operation_uid,
                             budget_s=budget_s)
    if request.op_type == provenance.REFIT:
        return run_refit(project, provenance.refit_request(request.settings),
                         version=request.version, supersedes=request.operation_uid,
                         budget_s=budget_s)
    if request.op_type == provenance.PLATFORM:
        from . import entity_store  # al usarlo: entity_store importa este módulo

        return entity_store.recompute_platform(request, budget_s=budget_s)
    if request.op_type == provenance.DECLARE_CONSTRAINTS:
        from . import entity_store  # al usarlo: entity_store importa este módulo

        return entity_store.recompute_declaration(request, budget_s=budget_s)
    return run_design(project, provenance.design_request(request.settings),
                      provenance.design_start(request.settings), version=request.version,
                      supersedes=request.operation_uid, budget_s=budget_s)


def _envelope_run(project: StoreProject, handle: OperationHandle, envelope: EnvelopeRequest,
                  masks: access.MaskSet, seeds: SeedSet, budget_s: float
                  ) -> Generator[Progress, None, None]:
    with DesignWriter.resume(project, handle) as writer:
        outcome: pipeline.EnvelopeOutcome = yield from compute_envelope_steps(
            project, writer, envelope, masks, seeds, _values(handle), budget_s)
        stored = writer.commit(figures=outcome.figures, message=outcome.message)
        yield Progress(_STORE_PHASE, 1, 1, outcome.message, result=stored)


def _area_run(project: StoreProject, handle: OperationHandle, name: str, prepared: PreparedArea,
              budget_s: float) -> Generator[Progress, None, None]:
    with DesignWriter.resume(project, handle) as writer:
        outcome = yield from compute_area_steps(writer, name, prepared, budget_s)
        stored = writer.commit(figures=outcome.figures, message=outcome.message)
        yield Progress(_STORE_PHASE, 1, 1, outcome.message, result=stored)


def _quarry_run(project: StoreProject, handle: OperationHandle, request: QuarryRequest,
                masks: access.MaskSet, prepared: PreparedQuarry, budget_s: float
                ) -> Generator[Progress, None, None]:
    with DesignWriter.resume(project, handle) as writer:
        calculated = yield from compute_quarry_steps(writer, request, masks, prepared,
                                                     _values(handle), handle.settings, budget_s)
        outcome = calculated.outcome
        stored = writer.commit(figures=outcome.figures, message=outcome.message)
        yield Progress(_STORE_PHASE, 1, 1, outcome.message, result=stored)


def _transition_run(project: StoreProject, handle: OperationHandle, name: str,
                    masks: access.MaskSet, prepared: PreparedTransition, budget_s: float
                    ) -> Generator[Progress, None, None]:
    with DesignWriter.resume(project, handle) as writer:
        outcome = yield from compute_transition_steps(writer, name, prepared, masks,
                                                      _values(handle), budget_s)
        stored = writer.commit(figures=outcome.figures, message=outcome.message)
        yield Progress(_STORE_PHASE, 1, 1, outcome.message, result=stored)


def _fill_only_run(project: StoreProject, handle: OperationHandle, request: FillOnlyRequest,
                   masks: access.MaskSet, prepared: PreparedFillOnly, budget_s: float
                   ) -> Generator[Progress, None, None]:
    with DesignWriter.resume(project, handle) as writer:
        outcome = yield from compute_fill_only_steps(writer, request, masks, prepared,
                                                     _values(handle), handle.settings, budget_s)
        stored = writer.commit(figures=outcome.figures, message=outcome.message)
        yield Progress(_STORE_PHASE, 1, 1, outcome.message, result=stored)


def _refit_run(project: StoreProject, handle: OperationHandle, request: RefitRequest,
               masks: access.MaskSet, prepared: PreparedRefit, budget_s: float
               ) -> Generator[Progress, None, None]:
    with DesignWriter.resume(project, handle) as writer:
        outcome = yield from compute_refit_steps(writer, request, masks, prepared,
                                                 _values(handle), budget_s)
        stored = writer.commit(figures=outcome.figures, message=outcome.message)
        yield Progress(_STORE_PHASE, 1, 1, outcome.message, result=stored)


def _design_run(project: StoreProject, handle: OperationHandle, design: DesignRequest,
                surface: str, masks: access.MaskSet, prepared: PreparedDesign, budget_s: float
                ) -> Generator[Progress, None, None]:
    with DesignWriter.resume(project, handle) as writer:
        outcome: pipeline.DesignOutcome = yield from compute_design_steps(
            project, writer, design, surface, masks, prepared, _values(handle), handle.settings,
            budget_s)
        stored = writer.commit(figures=outcome.figures, message=outcome.message)
        yield Progress(_STORE_PHASE, 1, 1, outcome.message, result=stored)
