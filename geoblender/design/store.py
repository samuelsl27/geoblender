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
from collections.abc import Callable, Generator, Iterable, Iterator, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType, TracebackType
from typing import TYPE_CHECKING, Any

import numpy as np

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
from ..core.versions import read as versions_read
from ..core.versions import store as versions_store
from ..core.versions.model import Version, VersionError
from ..gis.content import GEOTIFF, raster_header
from ..gis.geotiff import writer
from ..gis.masks import access
from ..gis.masks import provenance as masks_declared
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.masks.store import CANCELLED_REASON, available_tables
from ..gis.messages import GisError
from ..gis.raster import Raster
from ..gis.store import StoreProject, backup_path, insert_rows, project_references, temporary_path
from ..gis.vector import FeatureLayer
from . import pipeline, provenance, quarry
from .messages import DesignError
from .model import (
    DesignRequest,
    EnvelopeRequest,
    Metric,
    QuarryRequest,
    SlopeMode,
    Surface,
    Zone,
    ZoneKind,
)
from .params import (
    CONSERVE_SLOPE,
    CROWN_RING,
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
from .preview import Notice, _features, _quarry_warnings
from .profiles import profile_names
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
    "NO_DATA_NOTE",
    "NO_MOVEMENT_NOTE",
    "QUARRY_BERM_COLUMNS",
    "REPORT_COLUMNS",
    "DesignWriter",
    "OperationStart",
    "PreparedArea",
    "PreparedDesign",
    "PreparedEnvelope",
    "PreparedQuarry",
    "QuarryCalculated",
    "QuarryParts",
    "Stored",
    "begin_design",
    "begin_envelope",
    "berm_rows",
    "RECOMPUTED",
    "columns_of",
    "compute_area_steps",
    "compute_design_steps",
    "compute_envelope_steps",
    "compute_quarry_steps",
    "masks_steps",
    "number",
    "prepare_area_units",
    "prepare_design",
    "prepare_design_units",
    "prepare_envelope",
    "prepare_envelope_units",
    "prepare_excavation_area",
    "prepare_quarry",
    "prepare_quarry_units",
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
    "report_rows",
    "request_profiles",
    "require_version",
    "run_design",
    "run_envelope",
    "run_excavation_area",
    "run_quarry",
]

_OBJ = "Envolventes y escalonado"
_FIELD = "ubicación"
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
_COLUMNS: Mapping[str, tuple[ColumnDef, ...]] = MappingProxyType({
    provenance.BERM_TABLE: BERM_COLUMNS, provenance.REPORT_TABLE: REPORT_COLUMNS,
    provenance.QUARRY_REPORT_TABLE: REPORT_COLUMNS})


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
                replacing: str | None) -> None:
    """RF-013-17: ningún dato vigente de la versión tiene ya el nombre de alguna de las salidas de
    ``op_type`` para ``name`` (el mismo nombre en ASCII), salvo uno escrito por la operación
    ``replacing`` a la que sustituye la nueva. ``DesignError`` ``des.operation_name_repeated``;
    ``GisError`` ``gis.dataset_name_invalid`` si el nombre no tiene ninguna letra ni cifra."""
    for family in provenance.OPERATION_TYPES_BY_NAME[op_type].outputs:
        dataset = provenance.dataset_name(family, name)
        record = dataset_registry.get(conn, dataset, version_uid=version.uid)
        if record is not None and record.live and record.operation_uid != replacing:
            raise DesignError("des.operation_name_repeated", obj=f"Operación «{name}»",
                              field="nombre", value=name, dataset=dataset, version=version.code)


# --- Empezar la operación -----------------------------------------------------------------------


def _require_current_masks(project: StoreProject, version: Version | str,
                           code: str | None = None) -> None:
    """RF-013-04: las máscaras de ``version`` (su uid o la ``Version``) están al día; si no,
    ``MaskError`` (``core.constraint_masks_missing``/``_stale``) con la versión y la orden de
    compilar. Solo lee."""
    uid, label = (version.uid, version.code) if isinstance(version, Version) else (version, code)
    state, _pending = access.mask_state(project, uid)
    if state is not access.MaskState.CURRENT:
        why = ("core.constraint_masks_missing" if state is access.MaskState.MISSING
               else "core.constraint_masks_stale")
        raise access.MaskError(why, field="máscaras", value=state.value, version=label,
                               command=masks_declared.COMMAND)


@dataclass(frozen=True, slots=True, eq=False)
class OperationStart:
    """Lo que anota una operación de ``des`` al empezar (véase el módulo): su tipo y su nombre, la
    versión, los ajustes (JSON), las entradas, los parámetros que lee, las máscaras de las que
    parte y el hash que tenía cada dato que consume cuando se preparó (``seen``: uid → hash)."""

    op_type: str
    name: str
    version_uid: str
    version_code: str
    settings: Mapping[str, Any]
    inputs: tuple[Use, ...]
    params: tuple[str, ...]
    masks: access.MaskSet
    seen: Mapping[str, str]
    supersedes: str | None = None

    def check_masks(self, project: StoreProject) -> None:
        """RF-013-04: las máscaras de la versión siguen al día; si no, ``MaskError``
        (``core.constraint_masks_missing``/``_stale``), sin escribir nada. Solo lee."""
        _require_current_masks(project, self.version_uid, self.version_code)

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
        _check_name(conn, self.op_type, self.name, version, self.supersedes)

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
           masks: access.MaskSet, settings: Mapping[str, Any], inputs: tuple[Use, ...],
           params: tuple[str, ...], supersedes: str | None) -> OperationStart:
    with project.read() as conn:
        _check_name(conn, op_type, name, version, supersedes)
        seen = MappingProxyType(_seen(conn, inputs, version))
    return OperationStart(op_type, name, version.uid, version.code, dict(settings), inputs,
                          params, masks, seen, supersedes)


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
    ``design.params``): el anillo, el aviso de desdoblado y, con zonas a conservar, su talud."""
    return (CROWN_RING, UNSPLIT_THRESHOLD, UNSPLIT_MIN_AREA,
            *((CONSERVE_SLOPE,) if request.conserve else ()))


def _check_quarry_params(project: StoreProject, version: Version, request: QuarryRequest
                         ) -> None:
    """Como :func:`_check_profiles` para los parámetros de la 014 que lee la cantera: cada uno
    con un valor dentro de su rango en la versión (el de su fila o, sin ella, el de su
    definición). Si no, ``DesignError`` ``des.quarry_param_missing`` (el talud de conservación no
    tiene valor por defecto, D-9) o ``des.quarry_param_range``, antes de registrar nada."""
    keys = _quarry_keys(request)
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
                   supersedes: str | None = None) -> OperationStart:
    """Lo mismo que :func:`prepare_design` para ``des.quarry`` (spec 014, T19; RF-014-29) de
    ``request``: los ajustes de ``quarry_settings`` (con los sectores pendientes y los que toca el
    recinto), las entradas de ``quarry_inputs`` (la superficie de partida, lo que leen los lados,
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
                  provenance.quarry_settings(request, pending_sectors, touched_sectors), inputs,
                  params, supersedes)


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

    def _produces(self, family: str, kind: str) -> None:
        if self._closed or self._committed:
            raise RuntimeError("el escritor ya se confirmó o se cerró")
        if family not in self._type.outputs:
            raise ValueError(f"«{self.op_type}» no escribe la familia «{family}»: escribe "
                             f"{', '.join(self._type.outputs)}")
        if provenance.FAMILIES_BY_CODE[family].kind != kind:
            raise ValueError(f"la familia «{family}» es "
                             f"{'una tabla' if kind == 'raster' else 'una rejilla'}")
        if family in self._grids or family in self._tables:
            raise ValueError(f"la salida «{family}» ya está preparada")

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

    def grid_steps(self, family: str, raster: Raster) -> Generator[None, None, DatasetSpec]:
        """Prepara la rejilla ``raster`` como la salida ``family`` (``env``, ``srf`` o ``brm``) de
        la operación: su hash por bandas de filas y su GeoTIFF del perfil ``project`` (los mismos
        bits, también los NaN) en su temporal junto a su destino, **sin registrar nada**. Una
        unidad por banda de hash y por tesela; devuelve su ``DatasetSpec`` (con el hash) en
        ``StopIteration.value``. Cerrarlo a mitad borra el temporal. Se rechaza **al llamar**
        (errores del programa: ``ValueError`` si la familia no es una rejilla de su tipo, ya está
        preparada o el ráster no va en el CRS y la referencia vertical del proyecto)."""
        self._produces(family, "raster")
        if not isinstance(raster, Raster):
            raise TypeError(f"se escribe un Raster, no {type(raster).__name__}")
        if raster.crs.epsg != self.crs.epsg or raster.vertical != self.vertical:
            raise ValueError(
                f"«{self.name}» va en el CRS y la referencia vertical del proyecto (EPSG:"
                f"{self.crs.epsg}), no en EPSG:{raster.crs.epsg}: remuestréela antes")
        return self._grid_steps(family, raster)

    def _grid_steps(self, family: str, raster: Raster) -> Generator[None, None, DatasetSpec]:
        planned = provenance.dataset_spec(family, self.name, self.version_code)
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
        spec = provenance.dataset_spec(family, self.name, self.version_code,
                                       content=hasher.digest(), crs_epsg=self.crs.epsg)
        self._grids[family] = _Grid(family, spec, final, temporary, backup)
        if self.handle is not None:
            self.handle.claim_paths(temporary, final, backup)
        return spec

    def table_steps(self, family: str, rows: Iterable[Sequence[Any]]
                    ) -> Generator[None, None, DatasetSpec]:
        """Prepara la tabla ``family`` (``bmt`` o ``rpt``) con ``rows`` (:func:`berm_rows`,
        :func:`report_rows`): su hash en un GeoPackage en memoria, por trozos de filas, **sin
        registrar nada**. Devuelve su ``DatasetSpec`` (con el hash) en ``StopIteration.value``.
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

    @property
    def specs(self) -> tuple[DatasetSpec, ...]:
        """Las salidas preparadas, en el orden de su tipo."""
        found: list[DatasetSpec] = []
        for family in self._type.outputs:
            if family in self._grids:
                found.append(self._grids[family].spec)
            elif family in self._tables:
                found.append(self._tables[family].spec)
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

    def commit(self, start: OperationStart | None = None, *, figures: Sequence[FigureSpec] = (),
               message: str | None = None) -> Stored:
        """Registra el resultado, en **una** transacción de escritura: abre la operación
        (``start``, :meth:`OperationStart.begin`; no hace falta si el escritor se reanudó con una
        operación que ya empezó), reclama las rutas, pone las rejillas en su sitio, escribe las
        tablas y completa con ``figures`` y ``message``. Antes, fuera de la transacción, comprueba
        que las máscaras siguen al día (RF-013-04). Si algo falla, o lo que consume cambió desde que
        se preparó, deshace todo (no quedan operación, dato, tabla, cifra, rejilla en su sitio ni
        temporal) y el error sigue. Errores del programa (``ValueError``): faltan salidas de su
        tipo, o ``start`` no es de esta operación (o se da con una ya empezada, o falta)."""
        if self._closed or self._committed:
            raise RuntimeError("el escritor ya se confirmó o se cerró")
        self._check_ready(start)  # un error del programa no cierra el escritor
        try:
            if start is not None:
                start.check_masks(self.project)
            with self.project.write_transaction() as conn:
                handle = self.handle
                if handle is None:
                    assert start is not None
                    handle = start.begin(self.project, conn=conn)
                handle.claim_paths(*self._paths())
                self._install()
                for table in self._tables.values():
                    self._write_table(conn, table)
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
        missing = [family for family in self._type.outputs
                   if family not in self._grids and family not in self._tables]
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
                                provenance.QUARRY)
"""Los tipos que repite «Recalcular lo obsoleto» aquí: los dos de la 013 y, de la 014, el recinto
y la cantera (T19); los demás de la 014, cuando sus tareas los den."""
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
    de la operación ``des.stepped_design`` que la escribió): la de «Superficie de partida» de su
    ficha, de los ajustes de esa operación (:func:`~geoblender.design.provenance.design_start`).
    ``None`` si el dato no es una superficie de diseño (la envolvente, las bermas, la tabla, el
    informe, una superficie cualquiera o un uid que el proyecto no tiene; solo se busca por uid) o
    si sus ajustes no la llevan: quien la pide sigue sin ella. Solo lee."""
    row = conn.execute(
        "SELECT o.op_type, o.settings FROM gb_dataset AS d JOIN gb_operation AS o "
        "ON o.uid = d.operation_uid JOIN gb_operation_io AS io ON io.operation_uid = o.uid "
        "AND io.direction = 'out' AND io.item_kind = 'dataset' AND io.item_uid = d.uid "
        "WHERE d.uid = ? AND io.role = ?", (dataset_uid, provenance.DESIGN_SURFACE_ROLE)
    ).fetchone()
    if row is None or row[0] != provenance.STEPPED:
        return None
    try:
        return provenance.design_start(json.loads(row[1]))
    except (TypeError, ValueError):  # ajustes ausentes, que no son JSON o sin superficie
        return None


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
    (:func:`quarry_parts_units`) y :func:`prepare_quarry`. Devuelve la :class:`PreparedQuarry`.
    Nada se escribe; los rechazos salen al avanzar."""
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
    start = prepare_quarry(project, request, version=version.uid, masks=masks, sectors=sectors,
                           touched_sectors=[ref.code for ref in domain.touched],
                           supersedes=supersedes)
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
                                          geometry)
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


def _ceiling_metric(request: QuarryRequest) -> Metric:
    """La métrica del techo de conservación, que es uno para los dos lados (T13): la de los dos si
    coinciden y, si no, el *chamfer* 5×5 por defecto de ADR-0014."""
    metrics = {Metric(request.final.metric), Metric(request.exploitation.metric)}
    return metrics.pop() if len(metrics) == 1 else Metric.CHAMFER5


def quarry_notices(request: QuarryRequest, masks: access.MaskSet, parts: QuarryParts,
                   ring_cells: int, outcome: quarry.QuarryOutcome) -> tuple[Notice, ...]:
    """Los avisos y las notas de la cantera que no son del escalonado de un lado, en el orden en
    que se enseñan: los de sus capas (fondos sobre el terreno, zonas a conservar sin dato,
    corredores más largos que su eje más su ancho; los de la vista previa), las semillas de la 013
    de un lado que caen fuera de la coronación y de las zonas a sostener, por grupos (RF-014-03),
    el desdoblado sobre terreno sin explotar, por zonas (RF-014-17), y «explotación hasta la
    final» (RF-014-18). Con sus valores como números (``preview.Notice``)."""
    geometry = masks.grid
    start = parts.start.values
    found = list(_quarry_warnings(start, parts.floors, parts.conserve, parts.corridors,
                                  geometry.cell_area))
    for side_name in Surface:
        seeds = parts.seeds.get(side_name)
        if seeds is None:
            continue
        groups = quarry.outside_crown(seeds, parts.area, start, masks, ring_cells)
        if groups:
            cells = sum(group.cells for group in groups)
            found.append(Notice("des.quarry_seeds_outside", {
                "cells": cells, "area": cells * geometry.cell_area, "groups": len(groups)}))
            found.extend(Notice("des.quarry_seed_group", {
                "group": group.group, "cells": group.cells, "area": group.area_m2,
                "x": round(group.x, 2), "y": round(group.y, 2)}) for group in groups)
    unsplit = outcome.unsplit
    if unsplit.zones:
        found.append(Notice("des.quarry_unsplit_zones", {
            "zones": len(unsplit.zones), "area": unsplit.area_ha, "volume": unsplit.volume_m3,
            "threshold": unsplit.threshold_m, "min_area": unsplit.min_area_ha}))
        found.extend(Notice("des.quarry_unsplit_zone", {
            "zone": zone.zone, "area": zone.area_ha, "volume": zone.volume_m3,
            "x": round(zone.x, 2), "y": round(zone.y, 2)}) for zone in unsplit.zones)
    if outcome.to_final is not None:
        found.append(Notice("des.quarry_to_final", {
            "zones": len(outcome.to_final.zones), "area": outcome.to_final.area_ha,
            "volume": outcome.to_final.volume_m3}))
    return tuple(found)


def quarry_compute_steps(request: QuarryRequest, masks: access.MaskSet, parts: QuarryParts,
                         values: Mapping[str, object], *, pending: tuple[str, ...] = (),
                         budget_s: float = STEP_BUDGET_S
                         ) -> Generator[Progress, None, QuarryCalculated]:
    """Los pasos que calculan la cantera ``request`` con sus piezas ``parts`` y los parámetros
    ``values`` (clave → valor: los que anotó la operación, los que se resuelven hoy o los
    congelados), sin escribir nada (``yield from``): el techo de conservación de sus zonas a
    conservar, uno para los dos lados (``quarry.conservation_ceiling_steps``, con el talud de
    conservación y la métrica de :func:`_ceiling_metric`), y las dos superficies
    (``quarry.quarry_steps``, con el anillo de coronación, el espesor mínimo, la tolerancia, el
    umbral y el aviso de desdoblado). ``pending``: los nombres de los sectores con la búsqueda
    pendiente que se marcan. Devuelve la :class:`QuarryCalculated`: el ``QuarryOutcome`` y sus
    avisos (:func:`quarry_notices`). Lo comparten «Calcular», el recálculo y la reproducción."""
    geometry = masks.grid
    start = parts.start.values
    ring = int(check_quarry_param(CROWN_RING, values.get(CROWN_RING)))
    ceiling = None
    if parts.conserve:
        ceiling = yield from pipeline.forward(quarry.conservation_ceiling_steps(
            parts.conserve, start, geometry, values.get(CONSERVE_SLOPE),  # type: ignore[arg-type]
            metric=_ceiling_metric(request), budget_s=budget_s))
    job = quarry.QuarryJob(
        request, start, masks, parts.domain, values, ring, number(values, VERIFY_MIN_THICKNESS),
        number(values, TOLERANCE_FACE), number(values, WARNING_RATIO), seeds=parts.seeds,
        floors=parts.joined, ceiling=ceiling, anchors=parts.anchors, pending=pending,
        fill_zones=parts.fill_zones, unsplit_threshold_m=number(values, UNSPLIT_THRESHOLD),
        unsplit_min_area_ha=number(values, UNSPLIT_MIN_AREA),
        to_final_zones=parts.to_final_zones)
    outcome: quarry.QuarryOutcome = yield from pipeline.forward(
        quarry.quarry_steps(job, budget_s=budget_s))
    return QuarryCalculated(outcome, quarry_notices(request, masks, parts, ring, outcome))


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
    cantera ``outcome`` (RF-014-15 a RF-014-18): las celdas que cambió la regla de orden; la
    clasificación del total (excavación de la explotación, desdoblado, relleno de restauración y
    sus celdas, las celdas sin diferencia y sin dato y el espesor mínimo); las cotas mínima y
    máxima de cada superficie (``final_min_m``…; sin dato, una fila sin valor con la nota
    :data:`NO_DATA_NOTE`); con «explotación hasta la final», lo que pasa a la explotación y sus
    celdas; las filas del informe de la 013 de cada lado (:func:`report_rows`) con su superficie
    delante (``final.cut_m3``…) y sus avisos y notas con la superficie en el JSON; y, al final,
    ``notices`` (:func:`quarry_notices`) con su código y sus valores en JSON. Un valor NaN o
    infinito es un error del programa (``ValueError``)."""
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
    parámetros ``values`` y los sectores pendientes de los ajustes ``settings``) y deja sus cinco
    rejillas en los temporales de ``writer`` (:func:`quarry_grids`) y prepara sus dos tablas
    (:func:`quarry_berm_rows`, :func:`quarry_report_rows`), **sin confirmar**. Devuelve la
    :class:`QuarryCalculated`."""
    yield Progress("quarry", 0, 1, f"Preparando la cantera «{request.name}»…")
    parts = prepared.parts
    waiting = set(provenance.settings_pending(settings))
    pending = tuple(ref.name for ref in parts.domain.sectors if ref.code in waiting)
    calculated: QuarryCalculated = yield from quarry_compute_steps(
        request, masks, parts, values, pending=pending, budget_s=budget_s)
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


def recompute_run(request: RecomputeRequest, *, budget_s: float = STEP_BUDGET_S
                  ) -> tuple[OperationHandle, Iterator[Progress]]:
    """Repite la operación de ``des`` de ``request`` (``RecomputeRequest`` de «Recalcular lo
    obsoleto», RF-008-26; RF-013-17; plan 013 §5.3.2): **sin pedir confirmación** —la operación ya
    existe y se repite con sus ajustes—, empieza la operación nueva, que sustituye a la anterior en
    la revisión abierta de **su** versión (:func:`run_envelope`, :func:`run_design` y, de la 014,
    :func:`run_excavation_area` y :func:`run_quarry`; RF-014-31), con lo que
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


def _design_run(project: StoreProject, handle: OperationHandle, design: DesignRequest,
                surface: str, masks: access.MaskSet, prepared: PreparedDesign, budget_s: float
                ) -> Generator[Progress, None, None]:
    with DesignWriter.resume(project, handle) as writer:
        outcome: pipeline.DesignOutcome = yield from compute_design_steps(
            project, writer, design, surface, masks, prepared, _values(handle), handle.settings,
            budget_s)
        stored = writer.commit(figures=outcome.figures, message=outcome.message)
        yield Progress(_STORE_PHASE, 1, 1, outcome.message, result=stored)
