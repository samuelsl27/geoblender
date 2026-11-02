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
from collections.abc import Generator, Iterable, Mapping, Sequence
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
from . import pipeline, provenance
from .messages import DesignError
from .model import DesignRequest, EnvelopeRequest, SlopeMode
from .params import (
    TOLERANCE_FACE,
    VERIFY_MIN_THICKNESS,
    WARNING_RATIO,
    BenchParam,
    bench_key,
    check_bench_value,
)
from .sectors import DesignSector, design_sectors, refuse_pending, slope_params, touched
from .seeds import SectorRef, SeedSet, pace_progress, sector_layout, seed_units
from .surfaces import project_frame, read_surface

if TYPE_CHECKING:  # solo para los tipos: importarlos arrastraría los cálculos
    from .berms import Berms
    from .report import DesignReport

__all__ = [
    "BERM_COLUMNS",
    "NO_MOVEMENT_NOTE",
    "REPORT_COLUMNS",
    "DesignWriter",
    "OperationStart",
    "Stored",
    "begin_design",
    "begin_envelope",
    "berm_rows",
    "RECOMPUTED",
    "number",
    "prepare_design",
    "prepare_envelope",
    "previous_comparison",
    "recompute_run",
    "report_rows",
    "request_profiles",
    "require_version",
    "run_design",
    "run_envelope",
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
_COLUMNS: Mapping[str, tuple[ColumnDef, ...]] = MappingProxyType({
    provenance.BERM_TABLE: BERM_COLUMNS, provenance.REPORT_TABLE: REPORT_COLUMNS})

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


def _names(family: str) -> tuple[str, ...]:
    return tuple(column.name for column in _COLUMNS[family])


def _digest_steps(family: str, rows: Sequence[Row], crs: CrsRef
                  ) -> Generator[None, None, ContentDigest]:
    """El hash (``core.gpkg_layer@1``) de la tabla ``family`` con ``rows``, en un GeoPackage en
    memoria con la misma estructura (R4: fuera de la transacción), por pasos: una unidad por cada
    trozo de filas que se inserta y por cada trozo que se lee y se hashea."""
    conn = sqlite3.connect(":memory:")
    try:
        create_base(conn, crs)
        create_attribute_table(conn, "digest", _COLUMNS[family], "digest")
        names = _names(family)
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
    ``des.profile_value_missing`` o ``_range`` con el perfil (su código), la clave y el valor, antes
    de registrar nada: abrir la operación con un valor que falta crearía una fila vacía «sin
    confirmar» en el proyecto y calcularía con ella."""
    wanted = tuple(dict.fromkeys(codes))
    chosen = tuple(values)
    keys = tuple(bench_key(code, param) for code in wanted for param in chosen)
    with project.read() as conn:
        found = ParameterStore(project).resolve_many(
            conn, keys, (VERSION_SCOPE, PROJECT_SCOPE), version=version.uid)
    for code in wanted:
        for param in chosen:
            key = bench_key(code, param)
            resolved = found.get(key)
            if resolved is not None:
                value = None if resolved.value_json is None else json.loads(resolved.value_json)
            else:
                declared = definition(key)
                value = None if declared is None else declared.default
            check_bench_value(code, code, param, value)


def _loaded_masks(project: StoreProject, version: Version, masks: access.MaskSet | None
                  ) -> access.MaskSet:
    """Las máscaras de ``version``: las que se dan (que han de ser de esa versión y estar al día:
    ``MaskError``) o, sin ellas, las que da ``access.ensure_masks_steps`` (compila antes si no
    están al día, RF-013-04)."""
    if masks is not None:
        if masks.version_uid != version.uid:
            raise ValueError(f"las máscaras son de otra versión, no de {version.code}")
        _require_current_masks(project, version)
        return masks
    found = None
    for step in access.ensure_masks_steps(project, version.uid):
        found = step
    assert found is not None and isinstance(found.result, access.MaskSet)
    return found.result


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
        width = len(_COLUMNS[family])
        for row in chosen:
            if len(row) != width:
                raise ValueError(f"una fila de «{family}» lleva {width} columnas, no {len(row)}")
        return self._table_steps(family, chosen)

    def _table_steps(self, family: str, rows: tuple[Row, ...]
                     ) -> Generator[None, None, DatasetSpec]:
        planned = provenance.dataset_spec(family, self.name, self.version_code)
        with self.project.read() as conn:
            self._check_place(conn, planned)
        digest = yield from _digest_steps(family, rows, self.crs)
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
        if _table_exists(conn, spec.locator):
            conn.execute(f'DELETE FROM "{spec.locator}"')
        else:
            label = provenance.FAMILIES_BY_CODE[table.family].label
            create_attribute_table(
                conn, spec.locator, _COLUMNS[table.family],
                f"{label} {self.name} {self.version_code}",
                f"{label} «{self.name}» de la versión {self.version_code}, de Geoblender")
        insert_rows(conn, spec.locator, _names(table.family), table.rows)

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

RECOMPUTED: tuple[str, ...] = provenance.REPRODUCIBLE
"""Los tipos que repite «Recalcular lo obsoleto» (los dos de ``des``)."""
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


def _result_of[T](work: Generator[None, None, T]) -> T:
    """Lo que devuelve ``work`` (unidades de ``seeds``) llevado hasta el final."""
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
    sectors = design_sectors(project, found.uid)
    seeds = _result_of(seed_units(project, request, loaded))
    refuse_pending(touched(sectors, seeds.domain))  # RF-013-05
    start = prepare_envelope(project, request, version=found.uid, masks=loaded, sectors=sectors,
                             touched_sectors=[ref.code for ref in seeds.touched],
                             supersedes=supersedes)
    handle = start.begin(project)
    return handle, _envelope_run(project, handle, request, loaded, seeds, budget_s)


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
    sectors = design_sectors(project, found.uid)
    envelope = read_surface(
        project, provenance.dataset_name(provenance.ENVELOPE_GRID, request.envelope),
        version_uid=found.uid, expect=project_frame(project), role="envolvente")
    refs, labels = sector_layout(project, loaded)
    with np.errstate(invalid="ignore"):
        domain = np.isfinite(envelope.values)
    touched_codes = pipeline.touched_in(refs, labels, domain)
    refuse_pending(item for item in sectors if item.code in touched_codes)  # RF-013-05
    waiting = [item.code for item in sectors if item.pending and item.code in touched_codes]
    with project.read() as conn:
        previous = previous_comparison(conn, found, provenance.STEPPED, request.name)
    start = prepare_design(project, request, surface, version=found.uid, masks=loaded,
                           sectors=sectors, pending_sectors=waiting, touched_sectors=touched_codes,
                           previous=previous, supersedes=supersedes)
    handle = start.begin(project)
    return handle, _design_run(project, handle, request, surface, loaded, envelope, refs, labels,
                               budget_s)


def recompute_run(request: RecomputeRequest, *, budget_s: float = STEP_BUDGET_S
                  ) -> tuple[OperationHandle, Iterator[Progress]]:
    """Repite la operación de ``des`` de ``request`` (``RecomputeRequest`` de «Recalcular lo
    obsoleto», RF-008-26; RF-013-17; plan 013 §5.3.2): **sin pedir confirmación** —la operación ya
    existe y se repite con sus ajustes—, empieza la operación nueva, que sustituye a la anterior en
    la revisión abierta de **su** versión (:func:`run_envelope`, :func:`run_design`), con lo que
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
    return run_design(project, provenance.design_request(request.settings),
                      provenance.design_start(request.settings), version=request.version,
                      supersedes=request.operation_uid, budget_s=budget_s)


def _envelope_run(project: StoreProject, handle: OperationHandle, envelope: EnvelopeRequest,
                  masks: access.MaskSet, seeds: SeedSet, budget_s: float
                  ) -> Generator[Progress, None, None]:
    with DesignWriter.resume(project, handle) as writer:
        yield Progress("envelope", 0, 1, "Preparando la envolvente…")
        values = _values(handle)
        domain = seeds.domain
        slope = pipeline.envelope_slope(envelope, domain.sectors, domain.labels, values)
        start = None
        if pipeline.uses_start_surface(envelope):
            assert envelope.seeds.surface is not None  # seed_units lo comprobó
            start = read_surface(project, envelope.seeds.surface, version_uid=masks.version_uid,
                                 expect=project_frame(project), role="semillas").values
        job = pipeline.EnvelopeJob(envelope, seeds, slope, start,
                                   number(values, VERIFY_MIN_THICKNESS))
        outcome: pipeline.EnvelopeOutcome = yield from pipeline.forward(
            pipeline.envelope_compute_steps(job, budget_s=budget_s))
        raster = Raster(seeds.geometry, outcome.grid, writer.crs, writer.vertical)
        yield from pipeline.forward(_store_steps(
            writer.grid_steps(provenance.ENVELOPE_GRID, raster), budget_s, "la envolvente"))
        stored = writer.commit(figures=outcome.figures, message=outcome.message)
        yield Progress(_STORE_PHASE, 1, 1, outcome.message, result=stored)


def _design_run(project: StoreProject, handle: OperationHandle, design: DesignRequest,
                surface: str, masks: access.MaskSet, envelope: Raster,
                refs: Sequence[SectorRef], labels: np.ndarray, budget_s: float
                ) -> Generator[Progress, None, None]:
    with DesignWriter.resume(project, handle) as writer:
        yield Progress("benching", 0, 1, "Preparando el escalonado…")
        values = _values(handle)
        frame = project_frame(project)
        start = read_surface(project, surface, version_uid=masks.version_uid, expect=frame,
                             role="superficie de partida")
        anchors = None
        if design.anchor_grid is not None:
            anchors = read_surface(project, design.anchor_grid, version_uid=masks.version_uid,
                                   expect=frame, role="anclas").values
        profiles = pipeline.bench_profiles(values, [
            design.base_profile, *(profile for _sector, profile in design.sector_profiles)])
        waiting = set(provenance.settings_pending(handle.settings))
        pending = tuple(ref.name for ref in refs if ref.code in waiting)
        job = pipeline.DesignJob(
            design, start.grid, start.values, envelope.values, masks, tuple(refs), labels,
            pipeline.imposed_from(values, refs), profiles, anchors,
            number(values, VERIFY_MIN_THICKNESS), number(values, TOLERANCE_FACE),
            number(values, WARNING_RATIO),
            pipeline.previous_of(provenance.settings_previous(handle.settings)), pending)
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
        stored = writer.commit(figures=outcome.figures, message=outcome.message)
        yield Progress(_STORE_PHASE, 1, 1, outcome.message, result=stored)
