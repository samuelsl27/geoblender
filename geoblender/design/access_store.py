# SPDX-License-Identifier: GPL-3.0-or-later
"""Preparar y calcular la accesibilidad de las pistas: lo que se lee y se rechaza **antes de calcular**, el cálculo por pasos y su resumen (spec 017, T17; HU-017-3; RF-017-24,
RF-017-25, RF-017-04 y RF-017-30; RF-015-02, RF-015-03 y RF-015-16; RF-015-08; RNF-017-05 y RNF-017-06; plan 017 §5.2.2, §5.2.3, §5.3.2, §5.4 A10 y A11 y §5.7 P-1 y P-9; D-17 y D-18).

El homólogo, para la accesibilidad (``des.road_access``: una entidad **sin cadena**, ``ACC-001``, **sin huella**: nadie parte de su dato), de ``design.stockpile_store`` (la detección de
acopios, sin cadena). **Solo lee**: nada se escribe en el proyecto (RF-015-03) salvo las máscaras de la versión si no estaban al día (una operación propia, RF-013-04, y solo si no se
dan cargadas). La accesibilidad **no llama a** ``refuse_pending`` (``design.sectors``): no mueve ninguna celda ni cambia ninguna superficie ni restricción (RF-017-25).

**Crear** en una transacción, **recalcular**, **reproducir** y la **lectura para la 012** (la accesibilidad al día hecha sobre una superficie dada, con su tabla de zonas) son de la T17b
(más abajo): :func:`create_access_steps` (la rejilla de lo alcanzable, las cuatro tablas y las cifras en **una** transacción, como la detección de acopios), :func:`run_access` y
:func:`recompute_access` (el recálculo de «Recalcular lo obsoleto»), ``design.reproduce.reproduce_road_access`` (que comparte con el recálculo ``access_job`` y ``access_compute_steps``) y
:func:`accessibilities_on` (lo que lee la verificación de la 012 por su papel ``access_zones``, sin importar ``design.entities`` ni ``design.road_*``) con :func:`accessibilities_excluded` (las
que no da, con su causa, para el aviso, T18) y :func:`read_zone_table` (la tabla de zonas de una conexión: la del proyecto o la congelada que lee la reproducción).

- :func:`access_values` y :func:`prepare_access_units` (y :func:`prepare_access`, de una vez): el código ``ACC-nnn`` (correlativo por versión) y el nombre único, la capa de **puntos de
  entrada** (de puntos, con el campo de su nombre; sus puntos en absolutas float64), los parámetros resueltos y comprobados (la pendiente máxima y el ancho mínimo transitables y el área
  mínima de berma, **sin valor por defecto**: uno que falta se rechaza nombrando entidad, campo y valor, RF-015-08, D-17), la superficie (del proyecto o de la versión) y su rejilla,
  CRS y datum comparados con los del proyecto antes de leer una celda (RF-011-02 y 03), **la superficie final de una cantera de la 014** si la superficie es su explotación
  (``des_exp_<cantera>`` → ``des_fin_<cantera>``: la segunda superficie del trabajo, error 23), las **rejillas de cotas de berma** de la 013 (por defecto, todas las de la versión al día;
  o las que pide la persona) con sus tablas, las **huellas de las plataformas** de la 015 (también la que deja un acopio retirado «como plataforma») y las **zonas «requiere acceso»**
  de la 012 (por la clase de las máscaras, ADR-0028: una por restricción) y lo **intocable** (los intocables y las exclusiones: lo que las máscaras prohíben atravesar, T15-a). Da una
  :class:`PreparedAccess`: el ``AccessJob`` listo para calcular (todo lo leído y nada del proyecto), ``start`` (la ``OperationStart``: ajustes, entradas y parámetros) y las filas de los
  parámetros de la entidad. **Los rechazos de RF-017-04** (sin ningún punto de entrada o uno sin dato) salen aquí, antes de calcular.
- :func:`access_compute_steps`: el cálculo que **comparten «Calcular», el recálculo y la reproducción**, sobre ``road_access.access_steps`` (A10 y A11) por pasos de ``budget_s`` como
  mucho: sin proyecto y sin escribir nada; cerrar el generador a mitad no deja nada. Devuelve el ``AccessOutcome`` con las **cifras** CALCULADO de ``des.road_access`` (con su ámbito, la
  entidad) y los **avisos**: una entrada que no cae en terreno transitable **avisa** (``des.access_entry_not_walkable``: no es un rechazo, no alcanza nada y el cálculo sigue con las
  demás; decisión de la sesión principal, 21/11/2026), y que no se alcance ninguna celda o ninguna sobre la final también.
- :func:`access_summary` (puro) y :func:`prepared_summary` (con el proyecto, para lo obsoleto): el :class:`AccessSummary` de lo calculado: la cabecera, las cotas, las listas enteras de
  bermas, plataformas y zonas (comunicadas o no) y, en los avisos, lo que **no** se comunica (con su lugar, y de las zonas su distancia y su diferencia de cota; los
  :data:`~.preview.SUMMARY_ITEMS` primeros de cada lista y una nota con los que faltan) y lo que quedará obsoleto al repetirla (:func:`access_obsolete`).

- :func:`default_surface` y :func:`access_places` (spec 017, T30): lo que necesita el diálogo de «Accesibilidad de las pistas…» (``bl.ops.des``) y sus listas: la superficie que propone (la
  última de la cadena y, sin cadena, la explotación de la cantera) y el lugar de cada plataforma y de cada zona «requiere acceso» del cálculo para «Ir a».

Python puro (nivel 8), con numpy. ``design.access_store`` es un módulo pesado de la 017: lo importan las órdenes al usarlo, no ``bl`` al registrarse
(``tests/unit/architecture/test_lazy_registration.py``).
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Generator, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

import numpy as np

from ..core.constraints.model import ConstraintType
from ..core.datasets import registry as dataset_registry
from ..core.datasets.model import DatasetRecord, DatasetStatus
from ..core.params import ParameterStore
from ..core.project.model import Progress
from ..core.provenance import stale
from ..core.provenance.operations import OperationHandle
from ..core.provenance.recompute import RecomputeRequest
from ..core.versions import read as versions_read
from ..core.versions.model import Version, VersionError
from ..gis.grid import Grid
from ..gis.masks import access
from ..gis.masks.combine import ClassBit
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.messages import GisError
from ..gis.raster import Raster
from ..gis.store import StoreProject, load_features
from ..gis.vector import FeatureLayer
from . import entities, entity_store, pipeline, provenance, road_access
from .entities import EntityKind, EntityState
from .entity_store import EntityParamRow
from .messages import DesignError
from .params import AccessParam, check_entity_param, entity_key
from .preview import SUMMARY_ITEMS, Notice, Obsolete, ObsoleteKind, obsolete_names
from .road_model import AccessCells, AccessJob, AccessOutcome, AccessRequest, BermGrid, BermReach, EntryPoint, PlatformReach, ZoneReach
from .stockpiles import runs_cells
from .store import DesignWriter, OperationStart, Stored, _loaded_masks, _start, _store_steps, design_writer, require_version
from .surfaces import project_frame, read_surface_steps

__all__ = [
    "EXCLUDED_OTHER_SURFACE",
    "EXCLUDED_STALE",
    "AccessData",
    "AccessPlace",
    "AccessPlaces",
    "AccessSummary",
    "AccessZone",
    "Accessibility",
    "ExcludedAccessibility",
    "PreparedAccess",
    "access_compute_steps",
    "access_job",
    "access_obsolete",
    "access_places",
    "access_report_rows",
    "access_summary",
    "access_values",
    "access_zones",
    "accessibilities_excluded",
    "accessibilities_on",
    "berm_rows",
    "create_access",
    "create_access_steps",
    "default_surface",
    "entry_points",
    "platform_cells",
    "platform_rows",
    "prepare_access",
    "prepare_access_units",
    "prepared_summary",
    "reachable_grid",
    "read_access_surface",
    "read_access_zones",
    "read_zone_table",
    "recompute_access",
    "run_access",
    "untouchable_cells",
    "zone_rows",
]

_KINDS_ES = MappingProxyType({"point": "puntos", "line": "líneas", "polygon": "polígonos"})
_NUMERIC = frozenset({"INTEGER", "DOUBLE"})
_NO_VALUE = "—"
_DIALOG = "diálogo de «Accesibilidad de las pistas…»"
"""El origen de lo que elige la persona en el diálogo de la orden (la entidad al final)."""
_SURFACE_ROLE = "superficie de la accesibilidad"
_FINAL_ROLE = "superficie final de la cantera"
_BERM_ROLE = "rejilla de cotas de berma"
_PHASE = "access_compute"
_STORE_PHASE = "access_store"
_LIVE_STATES = (EntityState.CURRENT, EntityState.STALE, EntityState.SUPPORT_REMOVED)
"""Los estados de una plataforma **viva y calculada**, de la que se lee la huella (como la declaración de restricciones, RF-015-25)."""


# --- Lo que se prepara --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class PreparedAccess:
    """Lo que se lee y se comprueba antes de calcular la accesibilidad (:func:`prepare_access_units`): el ``job`` (``design.road_model.AccessJob``: todo lo leído y nada del
    proyecto), lo que anotará la operación (``start``: su tipo ``des.road_access``, sus ajustes, entradas y parámetros), el ``code`` de la entidad (``ACC-001``, correlativo por
    versión), la ``version`` (la editable), el nombre de la superficie sobre la que se calcula (``surface``), la de su cantera si tiene dos superficies (``final``; ``None`` si no),
    la capa de los puntos de entrada (``layer``), los nombres de los datos de **bermas** que se leyeron (``berms``), los códigos de las **plataformas** cuya huella se leyó
    (``platforms``), las ``rows`` de los parámetros de la entidad —**todas**: sin su fila, ``begin_operation`` crearía la del valor por defecto en el proyecto, trampa de la T04 de
    la 015— y sus ``values`` resueltos y comprobados (por último segmento de su clave). ``existing``: la entidad ya estaba en su versión (se preparó con su ``code``: recalcularla),
    así que «Crear» no escribe otra vez sus parámetros."""

    job: AccessJob
    start: OperationStart
    code: str
    version: Version
    surface: str
    final: str | None
    layer: str
    berms: tuple[str, ...]
    platforms: tuple[str, ...]
    rows: tuple[EntityParamRow, ...]
    values: Mapping[str, Any]
    existing: bool = False

    @property
    def op_type(self) -> str:
        """El tipo de la operación (``des.road_access``)."""
        return self.start.op_type

    @property
    def version_uid(self) -> str:
        """El uid de la versión de la accesibilidad: lo que reciben ``design_writer`` y ``set_entity_params``."""
        return self.version.uid


# --- Los parámetros -----------------------------------------------------------------------------


def access_values(request: AccessRequest, code: str) -> dict[str, Any]:
    """Los parámetros resueltos y comprobados de la accesibilidad ``request`` de código ``code`` (RF-015-08, D-17), por último segmento de su clave (``walk_slope_pct``): lo que se
    pide y nada más (la petición no lleva ninguna cifra minera y **ninguno tiene valor por defecto**: un umbral que falta es ``des.entity_param_missing``; uno fuera de su rango,
    ``des.entity_param_range``), con el nombre, la superficie y la capa de entradas; los datos de bermas (``berms``: sus nombres separados por comas) solo si se piden. **Sin
    proyecto**: lo comparten preparar y reproducir. ``TypeError`` si ``request`` no es una ``AccessRequest``."""
    if not isinstance(request, AccessRequest):
        raise TypeError(f"la accesibilidad se prepara con una AccessRequest, no {request!r}")
    layer = request.layer
    asked: dict[AccessParam, object] = {
        AccessParam.NAME: request.name, AccessParam.SURFACE: request.surface, AccessParam.ENTRIES_LAYER: layer,
        AccessParam.BERMS: None if request.berms is None else ", ".join(request.berms),
        AccessParam.WALK_SLOPE: request.walk_slope_pct, AccessParam.WALK_WIDTH: request.walk_width_m,
        AccessParam.MIN_BERM_AREA: request.min_berm_area_m2}
    values: dict[str, Any] = {}
    for param in AccessParam:
        if param is AccessParam.DISCARDED:  # lo decide quien la usa (RF-015-17), no el cálculo
            continue
        checked = check_entity_param(request.name, code, param.value, asked[param], layer=layer)
        if checked is not None:
            values[param.value] = checked
    return values


def _rows(request: AccessRequest, code: str, values: Mapping[str, Any]) -> tuple[EntityParamRow, ...]:
    """Las filas de los parámetros de la entidad con su procedencia (RF-008-01): **todas** lo que eligió la persona en el diálogo (ninguna lleva valor por defecto, D-17)."""
    rows: list[EntityParamRow] = []
    for param in AccessParam:
        value = values.get(param.value)
        if value is None:
            continue
        rows.append(EntityParamRow(entity_key(code, param), param.value, value, f"{_DIALOG}, entidad «{request.name}»", "person",
                                   f"Elegido al crear la accesibilidad «{request.name}»"))
    return tuple(rows)


# --- El nombre y el código ----------------------------------------------------------------------


def _identify(project: StoreProject, request: AccessRequest, version: Version, code: str | None) -> str:
    """El código de la accesibilidad (``code`` si se da: una entidad que ya está en su versión; si no, el siguiente ``ACC-nnn`` del registro de la versión, correlativo **por
    versión**) tras comprobar que su nombre es único en ella (RF-015-01: también el de una entidad sin calcular o descartada, y el que da el mismo nombre de dato):
    ``des.entity_name_repeated``."""
    registry = entities.registry(project, version.uid)
    chosen = code if code is not None else entities.next_code(EntityKind.ACCESS, (entry.record.code for entry in registry))
    wanted = provenance.dataset_name(provenance.ACCESS_GRID, request.name)
    for entry in registry:
        other = entry.record.name
        if entry.record.code != chosen and (other == request.name or provenance.dataset_name(provenance.ACCESS_GRID, other) == wanted):
            raise DesignError("des.entity_name_repeated", obj=f"Accesibilidad «{request.name}»", field=entity_key(chosen, AccessParam.NAME), value=request.name,
                              other=other, version=version.code)
    return chosen


# --- Los puntos de entrada ----------------------------------------------------------------------


def _entries_layer(project: StoreProject, request: AccessRequest, code: str) -> FeatureLayer:
    """La capa de los puntos de entrada del proyecto (solo lee): una capa de entidades **de puntos** (``des.access_layer_not_points``); ``ValueError`` si no es una capa de
    entidades (``gis_fea_``)."""
    name = request.layer
    found = load_features(project, name)
    if not isinstance(found, FeatureLayer):
        raise ValueError(f"«{name}» no es una capa de entidades del proyecto (gis_fea_)")
    if found.kind != "point":
        raise DesignError("des.access_layer_not_points", obj=f"Capa «{name}»", field=entity_key(code, AccessParam.ENTRIES_LAYER),
                          value=_KINDS_ES.get(found.kind, found.kind), layer=name, entity=request.name)
    return found


def _name_column(layer: FeatureLayer, request: AccessRequest, code: str) -> str | None:
    """La columna de la capa del campo del nombre de los puntos (por su nombre en la capa o por su columna), de texto; ``None`` si no se eligió campo.
    ``des.access_layer_field`` (con los campos que sirven) si la capa no lo tiene o no es de texto."""
    wanted = request.entries.name_field
    if wanted is None:
        return None
    fit = [column for column in layer.columns if column.sql_type not in _NUMERIC]
    for column in fit:
        if wanted in (column.field, column.column):
            return column.column
    raise DesignError("des.access_layer_field", obj=f"Capa «{request.layer}»", field="name_field", value=wanted, layer=request.layer, entity=request.name,
                      fields=", ".join(column.field for column in fit) or _NO_VALUE)


def entry_points(layer: FeatureLayer, request: AccessRequest, code: str) -> tuple[EntryPoint, ...]:
    """Los puntos de entrada de la capa ``layer`` (la de ``request``, de la accesibilidad ``code``) en absolutas float64: el campo de su nombre que eligió la persona (``des.access_layer_field``
    si la capa no lo tiene o no es de texto) o, sin él, su ``fid``. Lo comparten preparar y reproducir (``design.reproduce``, de la capa congelada)."""
    return _entry_points(layer, _name_column(layer, request, code))


def _entry_points(layer: FeatureLayer, column: str | None) -> tuple[EntryPoint, ...]:
    """Los puntos de la capa en absolutas float64, en el orden de la capa: uno por punto de cada entidad, con el nombre de su campo o, sin él (o en blanco), su ``fid``; las
    entidades de varios puntos los numeran (``nombre #2``)."""
    found: list[EntryPoint] = []
    for index, fid in enumerate(layer.fids):
        raw = None if column is None else layer.values[column][index]
        base = raw.strip() if isinstance(raw, str) and raw.strip() else str(fid)
        points = [row for part in layer.parts[index] for ring in part for row in np.asarray(ring, dtype=np.float64).reshape(-1, 2)]
        for number, (x, y) in enumerate(points, start=1):
            found.append(EntryPoint(base if len(points) == 1 else f"{base} #{number}", float(x), float(y)))
    return tuple(found)


# --- Lo que no se atraviesa, las zonas y las plataformas ------------------------------------------


def untouchable_cells(masks: Any) -> np.ndarray:
    """Lo que las máscaras prohíben atravesar (T15-a): el bit ``UNTOUCHABLE`` de su rejilla de clases (los intocables y las exclusiones; las demás clases de la 012 se atraviesan), como
    máscara booleana de la rejilla entera. Un array nuevo."""
    return (np.asarray(masks.classes) & np.uint16(int(ClassBit.UNTOUCHABLE))) != 0


def access_zones(masks: Any) -> tuple[AccessCells, ...]:
    """Las zonas «requiere acceso» de las máscaras de la versión (RF-017-25, ADR-0028: por la clase de la compilación): **una por restricción** de ese tipo, en el orden de las máscaras,
    con sus celdas por **índice en filas** (``fila · columnas + columna``; no la unión de todas, ``Masks.access``). El código de la zona es el de la restricción (también su
    nombre). Ninguna si no hay."""
    shape = masks.grid.shape
    found: list[AccessCells] = []
    for code, runs in masks.zones.items():
        kind = masks.ctypes.get(code)
        if kind is None or str(kind) != ConstraintType.REQUIRES_ACCESS.value:  # ni otro tipo ni la banda hacia dentro de un límite legal (sin tipo propio)
            continue
        found.append(AccessCells(code, code, np.flatnonzero(runs.mask(shape).ravel())))
    return tuple(found)


def platform_cells(runs: Sequence[Sequence[int]], ncols: int) -> np.ndarray:
    """Las celdas (índices de la rejilla en filas, ``int64``) de la huella de una plataforma dada en tramos de fila ``(fila, primera columna, columna final excluida)``; ninguna sin
    tramos. ``ValueError`` si un tramo no es válido (``design.stockpiles.runs_cells``)."""
    if not len(runs):
        return np.empty(0, dtype=np.int64)
    return runs_cells(np.asarray(runs, dtype=np.int64), ncols)


def _owner(conn: sqlite3.Connection, record: DatasetRecord) -> str:
    """El uid de la versión dueña del dato ``record`` (``""``: es del proyecto)."""
    row = conn.execute("SELECT version_uid FROM gb_dataset WHERE uid = ?", (record.uid,)).fetchone()
    return "" if row is None or not row[0] else str(row[0])


def _platforms(project: StoreProject, version: Version, ncols: int) -> tuple[tuple[AccessCells, ...], tuple[str, ...]]:
    """Las plataformas de la versión **vivas y calculadas** (RF-017-25: la 015, también la que deja un acopio retirado «como plataforma»; en el orden de su código) con la huella de
    su tabla ``des_epr_`` (``AccessCells``, por índice en filas) y los nombres de esos datos (entradas de la operación: cambiar una huella la deja obsoleta). Una huella que no se puede
    usar (editada fuera, dañada) se rechaza como en la declaración de restricciones (``des.entity_footprint_blocked`` o ``_unusable``)."""
    cells: list[AccessCells] = []
    datasets: list[str] = []
    with project.read() as conn:
        for entry in entities.registry(project, version.uid, conn=conn).entries:
            record = entry.record
            if record.kind != EntityKind.PLATFORM or record.state not in _LIVE_STATES:
                continue
            footprint = entity_store._usable_footprint(conn, entry, version)
            cells.append(AccessCells(record.code, record.name, platform_cells(footprint.runs, ncols)))
            datasets.append(provenance.dataset_name(provenance.ENTITY_TABLE, footprint.name))
    return tuple(cells), tuple(datasets)


# --- La superficie final y las bermas -------------------------------------------------------------


def _final_name(project: StoreProject, version: Version, surface: str) -> str | None:
    """El nombre de la **superficie final** de la cantera de la 014 cuya **explotación** es ``surface`` (``des_exp_<cantera>`` → ``des_fin_<cantera>``, RF-017-24, error 23), si la
    versión la tiene viva; ``None`` si ``surface`` no es la explotación de una cantera (una superficie del proyecto, la final misma…): sin cantera de dos superficies no hay otra con
    que compararla."""
    exploitation = provenance.FAMILIES_BY_CODE[provenance.EXPLOITATION_GRID].prefix
    if not surface.startswith(exploitation):
        return None
    wanted = provenance.FAMILIES_BY_CODE[provenance.FINAL_GRID].prefix + surface[len(exploitation):]
    with project.read() as conn:
        record = dataset_registry.get(conn, wanted, version_uid=version.uid)
        if record is None or not record.live or _owner(conn, record) != version.uid:
            return None
    return record.name


def _berm_names(project: StoreProject, version: Version, request: AccessRequest, code: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Los datos de cotas de berma de la 013 que lee la accesibilidad y sus tablas (``des_brm_<nombre>`` y ``des_bmt_<nombre>``): los que pide la persona (cada uno ha de ser un dato de
    cotas de berma **vivo de la versión**: ``des.access_berm_unknown``, nombrándolo) o, por defecto, **todos los al día de la versión** (vigentes, sin causas de obsolescencia), por
    nombre. Solo lee."""
    grid_prefix = provenance.FAMILIES_BY_CODE[provenance.BERMS_GRID].prefix
    table_prefix = provenance.FAMILIES_BY_CODE[provenance.BERM_TABLE].prefix
    with project.read() as conn:
        if request.berms is None:
            names = tuple(str(name) for uid, name in conn.execute(
                "SELECT uid, name FROM gb_dataset WHERE version_uid = ? AND status = ? ORDER BY name", (version.uid, DatasetStatus.CURRENT.value)).fetchall()
                if str(name).startswith(grid_prefix) and not stale.item_causes(conn, "dataset", str(uid)))
        else:
            wanted: list[str] = []
            for name in request.berms:
                record = dataset_registry.get(conn, name, version_uid=version.uid)
                if record is None or not record.live or not record.name.startswith(grid_prefix) or _owner(conn, record) != version.uid:
                    raise DesignError("des.access_berm_unknown", obj=f"Accesibilidad «{request.name}»", field=entity_key(code, AccessParam.BERMS), value=name,
                                      entity=request.name, version=version.code)
                wanted.append(record.name)
            names = tuple(wanted)
        tables: list[str] = []
        for name in names:
            record = dataset_registry.get(conn, table_prefix + name[len(grid_prefix):], version_uid=version.uid)
            if record is not None and record.live and _owner(conn, record) == version.uid:
                tables.append(record.name)
    return names, tuple(tables)


def access_job(request: AccessRequest, code: str, values: Mapping[str, Any], grid: Grid, surface: np.ndarray, entries: Sequence[EntryPoint], untouchable: np.ndarray, *,
               final: np.ndarray | None = None, berms: Sequence[BermGrid] = (), platforms: Sequence[AccessCells] = (), zones: Sequence[AccessCells] = ()) -> AccessJob:
    """El ``AccessJob`` de la accesibilidad ``request`` (de código ``code``) con lo leído y los valores resueltos ``values`` (:func:`access_values`: los tres umbrales): lo que comparten
    preparar (del proyecto) y reproducir (de lo congelado), para que calculen **el mismo trabajo**. Los rechazos de ``AccessJob`` son errores del programa."""
    return AccessJob(request, code, grid, surface, tuple(entries), untouchable, values[AccessParam.WALK_SLOPE.value], values[AccessParam.WALK_WIDTH.value],
                     values[AccessParam.MIN_BERM_AREA.value], final, tuple(berms), tuple(platforms), tuple(zones))


# --- Preparar -----------------------------------------------------------------------------------


def prepare_access_units(project: StoreProject, request: AccessRequest, version: Version, masks: access.MaskSet, *, code: str | None = None,
                         supersedes: str | None = None) -> Generator[None, None, PreparedAccess]:
    """Las unidades (cada ``yield``, una; para componerlas con ``pace_units``) que preparan la accesibilidad ``request`` en la versión editable ``version`` con las máscaras al día
    ``masks`` (``store.masks_steps``): el código y el nombre únicos (:func:`_identify`; ``code``: el de una entidad que ya está en su versión, que no choca consigo misma), la capa de
    los puntos de entrada con su campo de nombre y sus puntos, los parámetros resueltos (:func:`access_values`), la superficie y su rejilla comparada con la del proyecto antes de leer
    una celda (``design.surfaces.read_surface_steps``), la final de su cantera, las rejillas de bermas, las huellas de las plataformas, las zonas «requiere acceso» y lo intocable de
    las máscaras, los puntos de entrada comprobados (RF-017-04) y lo que anotará la operación. ``supersedes``: la operación hecha a la que sustituye (un recálculo).

    **Nada se escribe** (RF-015-03) y no llama a ``refuse_pending``: no mueve celdas. Los rechazos salen al avanzar, antes de calcular: la capa (su geometría y su campo), los
    parámetros, la superficie (``gis.dataset_unknown``, ``des.surface_other_version``, ``des.surface_mismatch``, ``gis.raster_empty``), las bermas (``des.access_berm_unknown``), las huellas
    de las plataformas y los puntos de entrada (``des.access_no_entry``, ``des.access_entry_no_data``)."""
    if masks.version_uid != version.uid:
        raise ValueError(f"las máscaras son de otra versión, no de {version.code}")
    chosen = _identify(project, request, version, code)
    yield
    layer = _entries_layer(project, request, chosen)
    entries = _entry_points(layer, _name_column(layer, request, chosen))
    values = access_values(request, chosen)
    yield
    frame = project_frame(project)
    grid = frame.grid
    surface = yield from read_surface_steps(project, request.surface, version_uid=version.uid, expect=frame, role=_SURFACE_ROLE)
    final_name = _final_name(project, version, request.surface)
    final = None
    if final_name is not None:
        final = (yield from read_surface_steps(project, final_name, version_uid=version.uid, expect=frame, role=_FINAL_ROLE)).values
    berm_names, berm_tables = _berm_names(project, version, request, chosen)
    berms: list[BermGrid] = []
    for name in berm_names:
        try:
            levels = (yield from read_surface_steps(project, name, version_uid=version.uid, expect=frame, role=_BERM_ROLE)).values
        except GisError as error:
            if error.code != "gis.raster_empty":  # un diseño sin ninguna berma: ningún tramo
                raise
            levels = np.full(grid.shape, np.nan)
        berms.append(BermGrid(name, levels))
    yield
    platforms, footprints = _platforms(project, version, grid.ncols)
    job = access_job(request, chosen, values, grid, surface.values, entries, untouchable_cells(masks), final=final, berms=berms, platforms=platforms, zones=access_zones(masks))
    road_access.entry_cells(job)  # RF-017-04: ningún punto de entrada o uno sin dato se rechaza antes de calcular
    yield
    inputs = provenance.access_inputs(request.surface, request.layer, masks.uses(), final=final_name, berms=berm_names, berm_tables=berm_tables, footprints=footprints)
    begun = _start(project, provenance.ROAD_ACCESS, request.name, version, masks, provenance.access_settings(request, chosen), inputs,
                   provenance.access_params(chosen, berms=request.berms is not None), supersedes)
    yield
    return PreparedAccess(job, begun, chosen, version, request.surface, final_name, request.layer, berm_names, tuple(item.code for item in platforms),
                          _rows(request, chosen, values), MappingProxyType(values), code is not None)


def prepare_access(project: StoreProject, request: AccessRequest, *, version: str | None, masks: access.MaskSet | None = None, code: str | None = None,
                   supersedes: str | None = None) -> PreparedAccess:
    """La preparación entera de :func:`prepare_access_units` de una vez (plan 017 §5.3.1; sin ceder el hilo): la :class:`PreparedAccess`, con los mismos rechazos y sin escribir
    nada. ``version``: la versión activa (su uid o su código; ``VersionError`` ``core.version_required`` si no hay y ``core.version_not_editable`` si no se edita, RF-009-21);
    ``masks``: las de esa versión (al día; sin ellas se cargan, compilándolas antes si faltan)."""
    found = require_version(project, version, provenance.ROAD_ACCESS)
    work = prepare_access_units(project, request, found, _loaded_masks(project, found, masks), code=code, supersedes=supersedes)
    while True:
        try:
            next(work)
        except StopIteration as stop:
            result: PreparedAccess = stop.value
            return result


# --- Calcular por pasos (RF-017-24, RF-017-25, RF-017-30) -----------------------------------------


def _figures(outcome: AccessOutcome) -> tuple[Any, ...]:
    """Las cifras CALCULADO de ``des.road_access`` del resultado (:data:`~.provenance.ACCESS_FIGURES`, con el ámbito de la entidad): las cotas y el área alcanzables, la cota
    mínima sobre la final (solo si hay cantera de dos superficies y se alcanza algo) y cuántas bermas, plataformas y zonas se comunican."""
    return provenance.access_figures(outcome.name, outcome.code, {
        "des.acc_z_min_m": outcome.z_min_m, "des.acc_z_max_m": outcome.z_max_m, "des.acc_area_m2": outcome.area_m2,
        "des.acc_z_min_final_m": outcome.z_min_final_m,
        "des.acc_berms_reached": sum(1 for item in outcome.berms if item.connected), "des.acc_berms_total": len(outcome.berms),
        "des.acc_platforms_reached": sum(1 for item in outcome.platforms if item.connected),
        "des.acc_zones_reached": sum(1 for item in outcome.zones if item.connected),
        "des.acc_zones_missing": sum(1 for item in outcome.zones if not item.connected)})


def access_compute_steps(job: AccessJob, *, budget_s: float = STEP_BUDGET_S) -> Generator[Progress, None, AccessOutcome]:
    """Los pasos que calculan la accesibilidad de ``job`` (RF-017-24, RF-017-25, RF-017-30; plan 017 §5.3.2: el cálculo que **comparten «Calcular», el recálculo y la
    reproducción**), sin proyecto y sin escribir nada (``yield from``; cerrar el generador no deja nada y no toca ninguna entrada): ``road_access.access_steps`` (A10 y A11) por pasos
    de ``budget_s`` como mucho (``STEP_BUDGET_S``, 0,05 s; RNF-017-06). Los rechazos de RF-017-04 (sin ningún punto de entrada o uno sin dato) salen al avanzar, **antes** del primer
    paso. Devuelve el :class:`~.road_model.AccessOutcome` con las **cifras** (:func:`_figures`) y los **avisos**, por este orden: cada entrada que **no cae en terreno transitable**
    (``des.access_entry_not_walkable``: no es un rechazo, no alcanza nada y el cálculo sigue con las demás; decisión de la sesión principal sobre la duda de la T15), que no se alcance
    ninguna celda (``des.access_nothing_reached``) y que no se alcance ninguna de la final de una cantera (``des.access_final_none``). ``TypeError`` si ``job`` no es un ``AccessJob``."""
    if not isinstance(job, AccessJob):
        raise TypeError(f"el cálculo de la accesibilidad es de un AccessJob, no {job!r}")
    request = job.request
    rows, cols = road_access.entry_cells(job)
    yield Progress(_PHASE, 0, 1, f"Calculando la accesibilidad «{request.name}»…")
    outcome: AccessOutcome = yield from pipeline.forward(road_access.access_steps(job, budget_s=budget_s))
    notices: list[Notice] = []
    for entry, row, col in zip(job.entries, rows.tolist(), cols.tolist(), strict=True):
        if not outcome.reachable[row, col]:  # una entrada transitable se alcanza a sí misma: la que no, no está en terreno transitable
            notices.append(Notice("des.access_entry_not_walkable", {"layer": request.layer, "entity": request.name, "value": entry.name,
                                                                    "x": round(entry.x, 2), "y": round(entry.y, 2)}))
    if outcome.z_min_m is None:
        notices.append(Notice("des.access_nothing_reached", {"entity": request.name}))
    if job.final is not None and outcome.z_min_final_m is None:
        notices.append(Notice("des.access_final_none", {"entity": request.name}))
    return replace(outcome, figures=_figures(outcome), notices=tuple(notices))


# --- El resumen (RF-017-24, RF-017-25, RF-015-03) -------------------------------------------------


@dataclass(frozen=True, slots=True)
class AccessSummary:
    """El resumen de «Calcular» la accesibilidad (RF-015-03, RF-017-24, RF-017-25): su ``name`` y su ``code`` (``ACC-001``), la ``version`` (su código), la ``surface`` sobre la que se
    calcula y la ``final`` de su cantera (``None`` si no la tiene), las cotas y el área alcanzables (``z_min_m``, ``z_max_m`` y ``area_m2``; ``None`` las cotas si no se alcanza
    nada) y la cota mínima sobre la final (``z_min_final_m``), las ``figures`` que se registrarán (CALCULADO, con el ámbito de la entidad), las listas **enteras** de ``berms``,
    ``platforms`` y ``zones`` (comunicadas o no), los ``notices`` en el orden en que se enseñan (la cabecera, las cotas, los avisos del cálculo, lo que no se comunica y, al final, lo que
    quedará obsoleto) y ``obsolete``, lo que quedará obsoleto al repetirla, con su lista entera."""

    name: str
    code: str
    version: str
    surface: str
    final: str | None
    z_min_m: float | None
    z_max_m: float | None
    area_m2: float
    z_min_final_m: float | None
    figures: tuple[Any, ...]
    berms: tuple[BermReach, ...]
    platforms: tuple[PlatformReach, ...]
    zones: tuple[ZoneReach, ...]
    notices: tuple[Notice, ...]
    obsolete: tuple[Obsolete, ...] = ()

    def lines(self, language: str = "es") -> tuple[str, ...]:
        """Todo lo que dice el resumen, línea a línea, en ``language``."""
        return tuple(notice.text(language) for notice in self.notices)

    def warnings(self, language: str = "es") -> tuple[str, ...]:
        """Solo los avisos, en ``language``."""
        return tuple(notice.text(language) for notice in self.notices if notice.severity == "warning")


def _cut(found: list[Notice]) -> list[Notice]:
    """Los :data:`~.preview.SUMMARY_ITEMS` primeros avisos de una lista y, si hay más, una nota con cuántos faltan (la lista entera está en el resumen)."""
    if len(found) <= SUMMARY_ITEMS:
        return found
    return [*found[:SUMMARY_ITEMS], Notice("des.access_more", {"more": len(found) - SUMMARY_ITEMS})]


def access_summary(outcome: AccessOutcome, *, version: str, surface: str, final: str | None = None, obsolete: Iterable[Obsolete] = ()) -> AccessSummary:
    """El resumen de «Calcular» la accesibilidad ``outcome`` (RF-015-03, RF-017-24, RF-017-25; puro: sin proyecto): la cabecera (cuántas bermas, plataformas y zonas «requiere acceso»
    quedan comunicadas de las que hay), las cotas y el área alcanzables y la cota mínima sobre la final, los avisos del cálculo (``outcome.notices``), **lo que no se comunica** (cada tramo
    de berma, plataforma y zona con su lugar y, de la zona, su distancia y su diferencia de cota a lo alcanzable más próximo; los :data:`~.preview.SUMMARY_ITEMS` primeros de cada lista y una
    nota con los que faltan) y, al final, lo que quedará obsoleto (``obsolete``: :func:`access_obsolete`). ``version`` es el código de la versión, ``surface`` el nombre de la
    superficie y ``final`` el de la final de su cantera (``None``: no la tiene)."""
    kept = tuple(obsolete)
    name = outcome.name
    notices: list[Notice] = [Notice("des.access_summary", {
        "entity": name, "code": outcome.code, "berms": len(outcome.berms), "berms_reached": sum(1 for item in outcome.berms if item.connected),
        "platforms": len(outcome.platforms), "platforms_reached": sum(1 for item in outcome.platforms if item.connected),
        "zones": len(outcome.zones), "zones_reached": sum(1 for item in outcome.zones if item.connected)})]
    if outcome.z_min_m is not None and outcome.z_max_m is not None:
        notices.append(Notice("des.access_levels", {"entity": name, "z_min": outcome.z_min_m, "z_max": outcome.z_max_m, "area": outcome.area_m2}))
    if outcome.z_min_final_m is not None:
        notices.append(Notice("des.access_final", {"final": _NO_VALUE if final is None else final, "z_final": outcome.z_min_final_m}))
    notices.extend(outcome.notices)
    notices.extend(_cut([Notice("des.access_berm_missing", {
        "stretch": item.number, "source": _NO_VALUE if item.source is None else item.source, "level": item.level_m, "area": item.area_m2, "x": item.x, "y": item.y})
        for item in outcome.berms if not item.connected]))
    notices.extend(_cut([Notice("des.access_platform_missing", {"code": item.code}) for item in outcome.platforms if not item.connected]))
    notices.extend(_cut([
        Notice("des.access_zone_missing", {"code": item.code, "distance": item.distance_m, "difference": item.level_difference_m, "x": item.x, "y": item.y})
        if item.x is not None and item.y is not None and item.distance_m is not None and item.level_difference_m is not None
        else Notice("des.access_zone_missing_unplaced", {"code": item.code})
        for item in outcome.zones if not item.connected]))
    dependents = [item for item in kept if item.kind is ObsoleteKind.DEPENDENT]
    if dependents:
        notices.append(Notice("des.access_obsolete_dependents", {"entity": name, "operations": len(dependents), "items": obsolete_names(dependents, version)}))
    return AccessSummary(name, outcome.code, version, surface, final, outcome.z_min_m, outcome.z_max_m, outcome.area_m2, outcome.z_min_final_m, outcome.figures,
                         outcome.berms, outcome.platforms, outcome.zones, tuple(notices), kept)


def access_obsolete(project: StoreProject, prepared: PreparedAccess, *, supersedes: str | None = None) -> tuple[Obsolete, ...]:
    """**Lo que quedará obsoleto al crear** la accesibilidad ``prepared`` (RF-015-03, RF-015-16; del grafo de la 008, sin escribir; con el mecanismo de la 015,
    ``entity_store._dependents``): una accesibilidad nueva no deja obsoleto nada; la que **sustituye** una operación (``supersedes``: un recálculo) deja obsoleto lo que dependía de lo
    que escribió, en cascada (``ObsoleteKind.DEPENDENT``: la verificación de la 012 que la usa, T18), sin la propia sustituida. Solo lee."""
    if supersedes is None:
        return ()
    with project.read() as conn:
        written = [str(row[0]) for row in conn.execute(
            "SELECT item_uid FROM gb_operation_io WHERE operation_uid = ? AND direction = 'out' AND item_kind = 'dataset' ORDER BY fid", (supersedes,))]
        found = entity_store._dependents(conn, written, prepared.version_uid, exclude=(supersedes,))
    return tuple(entity_store._consumer(ObsoleteKind.DEPENDENT, uid, op_type, name) for uid, op_type, name in found)


def prepared_summary(project: StoreProject, prepared: PreparedAccess, outcome: AccessOutcome, *, supersedes: str | None = None) -> AccessSummary:
    """El resumen de «Calcular» la accesibilidad ``prepared`` (RF-015-03, RF-017-24, RF-017-25): :func:`access_summary` de su ``outcome``, con lo que quedará obsoleto al
    crearla (:func:`access_obsolete`). Solo lee."""
    return access_summary(outcome, version=prepared.version.code, surface=prepared.surface, final=prepared.final,
                          obsolete=access_obsolete(project, prepared, supersedes=supersedes))


# --- Lo que propone el diálogo y adónde lleva «Ir a» (spec 017, T30; RF-017-24, RF-017-25) ---------


def default_surface(project: StoreProject, version: Version) -> str | None:
    """La superficie que propone el diálogo de «Accesibilidad de las pistas…» en la versión ``version`` (RF-017-24: por defecto, **la última de la cadena** de entidades): el dato de la superficie de
    la entidad calculada y viva que cierra la cadena (``entities.chain_tails``, ``des_psf_<nombre>``) si es una sola y, **sin cadena**, la superficie de explotación de la cantera de la 014
    (``des_exp_<cantera>``: sobre ella la final de la cantera entra en el cálculo, error 23) si es una sola y está al día (una cantera obsoleta no cuenta). ``None`` si no hay candidata o hay
    varias: no se elige una por la persona. Solo lee."""
    registry = entities.registry(project, version.uid)
    tails = [tail for tail in entities.chain_tails(registry.records) if tail.state not in (EntityState.UNCALCULATED, EntityState.DISCARDED)]
    if len(tails) == 1:
        return provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, tails[0].name)
    if tails:
        return None
    prefix = provenance.FAMILIES_BY_CODE[provenance.EXPLOITATION_GRID].prefix
    with project.read() as conn:
        found = [str(name) for uid, name in conn.execute("SELECT uid, name FROM gb_dataset WHERE version_uid = ? AND status = ? ORDER BY name",
                                                         (version.uid, DatasetStatus.CURRENT.value)).fetchall()
                 if str(name).startswith(prefix) and not stale.item_causes(conn, "dataset", str(uid))]
    return found[0] if len(found) == 1 else None


@dataclass(frozen=True, slots=True)
class AccessPlace:
    """Un lugar al que lleva «Ir a» desde las listas de la accesibilidad (RF-017-25): su centro absoluto (``x`` e ``y``, m, float64) y su área (``area_m2``, m²), que da el radio del encuadre."""

    x: float
    y: float
    area_m2: float


@dataclass(frozen=True, slots=True)
class AccessPlaces:
    """El lugar de cada **plataforma** (``platforms``, por su código) y de cada **zona «requiere acceso»** (``zones``, por su código) de un cálculo de la accesibilidad; los tramos de berma
    llevan el suyo en :class:`~.road_model.BermReach`. Lo que no tiene celdas no tiene lugar y no sale."""

    platforms: Mapping[str, AccessPlace]
    zones: Mapping[str, AccessPlace]


def _centre(grid: Any, cells: np.ndarray) -> AccessPlace | None:
    """El centro absoluto de las celdas ``cells`` (índices de la rejilla en filas) de ``grid`` y su área; ``None`` si no hay ninguna. float64: nunca float32 (regla 4 de ``AGENTS.md``)."""
    if not cells.size:
        return None
    rows, cols = np.divmod(cells, grid.ncols)
    return AccessPlace(float(grid.west + (float(cols.mean()) + 0.5) * grid.dx), float(grid.north - (float(rows.mean()) + 0.5) * grid.dy), float(cells.size * grid.cell_area))


def access_places(job: AccessJob, outcome: AccessOutcome) -> AccessPlaces:
    """El lugar de cada plataforma y de cada zona «requiere acceso» de ``job`` para «Ir a» (spec 017, T30; RF-017-25), sin proyecto ni escribir nada: el **centro de sus celdas** y su área o, de la
    zona **que no se comunica**, **el lugar que dice su resumen** (su celda más próxima a lo alcanzable, ``ZoneReach.x`` y ``y``), con el área de la zona entera, de modo que el aviso y «Ir a» llevan al
    mismo sitio. La plataforma o la zona sin celdas no tiene lugar."""
    grid = job.grid
    placed = {item.code: item for item in outcome.zones}
    zones: dict[str, AccessPlace] = {}
    for zone in job.zones:
        centre = _centre(grid, zone.cells)
        if centre is None:
            continue
        found = placed.get(zone.code)
        zones[zone.code] = centre if found is None or found.connected or found.x is None or found.y is None else AccessPlace(float(found.x), float(found.y), centre.area_m2)
    platforms = {item.code: centre for item in job.platforms if (centre := _centre(grid, item.cells)) is not None}
    return AccessPlaces(MappingProxyType(platforms), MappingProxyType(zones))


# --- Lo que se guarda (spec 017, T17b; RF-017-24, RF-017-25, RNF-017-10) ----------------------------------------


def _json(value: object) -> str:
    """``value`` como JSON compacto y estable (``allow_nan`` falso: nada que no sea finito; un escalar de numpy, su valor)."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=_plain)


def _plain(value: object) -> object:
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"el valor {value!r} no se puede guardar como JSON")


def _finite(value: float | None, what: str) -> float | None:
    """``value`` como real finito (``None`` si no lo hay); ``ValueError`` si es NaN o infinito: lo guardado nunca lo es."""
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{what} no es un número finito: {value!r}")
    return number


def _notice_json(notice: Notice) -> dict[str, object]:
    return {"code": notice.code, "severity": notice.severity, "values": dict(notice.values)}


def reachable_grid(outcome: AccessOutcome) -> np.ndarray:
    """La rejilla que se guarda como ``des_acc_`` (plan 017 §5.2.3: «lo alcanzable, rejilla con 1 alcanzable y 0 no»): el resultado ``outcome`` como float64 de la rejilla entera, **1,0**
    en las celdas alcanzables y **0,0** en las demás (sin NaN: una celda no alcanzable tiene dato). Un array nuevo."""
    return np.where(outcome.reachable, 1.0, 0.0)


def berm_rows(outcome: AccessOutcome) -> list[tuple[Any, ...]]:
    """Las filas de ``des_acb_`` (:data:`~.store.ACCESS_BERM_COLUMNS`; RF-017-25) del resultado ``outcome``: **una por tramo de berma**, en su orden (el de la lectura de las rejillas de
    bermas), con su número, el dato de bermas de que sale, su cota real, su área, si queda comunicado (1 o 0) y su lugar. Nada es NaN ni infinito (``ValueError``)."""
    return [(item.number, item.source, _finite(item.level_m, "la cota de un tramo de berma"), _finite(item.area_m2, "el área de un tramo de berma"), int(item.connected),
             _finite(item.x, "la x de un tramo de berma"), _finite(item.y, "la y de un tramo de berma")) for item in outcome.berms]


def platform_rows(outcome: AccessOutcome) -> list[tuple[Any, ...]]:
    """Las filas de ``des_acp_`` (:data:`~.store.ACCESS_PLATFORM_COLUMNS`; RF-017-25) del resultado ``outcome``: **una por plataforma** de la versión, con su código, si queda comunicada
    (1 o 0) y la cota a que se llega (vacía si no queda comunicada)."""
    return [(item.code, int(item.connected), _finite(item.level_m, "la cota de una plataforma")) for item in outcome.platforms]


def zone_rows(outcome: AccessOutcome) -> list[tuple[Any, ...]]:
    """Las filas de ``des_acz_`` (:data:`~.store.ACCESS_ZONE_COLUMNS`; RF-017-25) del resultado ``outcome``: **una por zona «requiere acceso»** de la 012, con su código, si queda comunicada
    (1 o 0) y, de la que no, su lugar, la distancia y la diferencia de cota a lo alcanzable más próximo (vacíos los que no se dan). **Es lo que lee la verificación de la 012** (T18)."""
    return [(item.code, int(item.connected), _finite(item.x, "la x de una zona"), _finite(item.y, "la y de una zona"), _finite(item.distance_m, "la distancia de una zona"),
             _finite(item.level_difference_m, "la diferencia de cota de una zona")) for item in outcome.zones]


def access_report_rows(outcome: AccessOutcome) -> list[tuple[Any, ...]]:
    """Las filas de ``des_prp_`` (formato largo: ``quantity, value, unit_code, note``; :data:`~.store.REPORT_COLUMNS`) del resultado ``outcome``: cuántas bermas, plataformas y zonas hay y
    cuántas quedan comunicadas, las cotas mínima y máxima alcanzables (solo si se alcanza alguna celda), el área alcanzable, la cota mínima sobre la final de una cantera (solo si la hay) y,
    al final, **cada aviso con su código y sus valores** en JSON (no su texto), en su orden."""
    rows: list[tuple[Any, ...]] = [
        ("berms", float(len(outcome.berms)), "-", None), ("berms_reached", float(sum(1 for item in outcome.berms if item.connected)), "-", None),
        ("platforms", float(len(outcome.platforms)), "-", None), ("platforms_reached", float(sum(1 for item in outcome.platforms if item.connected)), "-", None),
        ("zones", float(len(outcome.zones)), "-", None), ("zones_reached", float(sum(1 for item in outcome.zones if item.connected)), "-", None)]
    if outcome.z_min_m is not None and outcome.z_max_m is not None:
        rows += [("z_min_m", _finite(outcome.z_min_m, "la cota mínima alcanzable"), "m", None), ("z_max_m", _finite(outcome.z_max_m, "la cota máxima alcanzable"), "m", None)]
    rows.append(("area_m2", _finite(outcome.area_m2, "el área alcanzable"), "m2", None))
    if outcome.z_min_final_m is not None:
        rows.append(("z_min_final_m", _finite(outcome.z_min_final_m, "la cota mínima sobre la final"), "m", None))
    for notice in outcome.notices:
        rows.append((notice.severity, None, None, _json(_notice_json(notice))))
    return rows


# --- Crear: en una transacción (RF-015-02, RF-015-29, RNF-017-06) ------------------------------------------------


def create_access_steps(project: StoreProject, writer: DesignWriter, prepared: PreparedAccess, outcome: AccessOutcome, *, decided_by: str | None = None, budget_s: float = STEP_BUDGET_S
                        ) -> Generator[Progress, None, Stored]:
    """**«Crear» una accesibilidad** por pasos (spec 017, T17b; RF-017-24, RF-017-25, RF-015-01, RF-015-02, RF-015-04; RNF-017-06 y RNF-017-10): prepara cada salida en su temporal —la rejilla
    de lo alcanzable (``des_acc_``), las tablas de bermas, plataformas y zonas «requiere acceso» (``des_acb_``, ``des_acp_`` y ``des_acz_``) y el informe (``des_prp_``)—, cada una montada y
    escrita por pasos de ``budget_s`` como mucho, y las registra en **una** transacción (:meth:`~.store.DesignWriter.commit` de ``writer``, el del ámbito de la accesibilidad:
    ``design_writer``): **los parámetros de la entidad** —todas sus filas, con su origen y el decisor ``decided_by`` (por defecto quien tiene abierto el proyecto)—, la operación con sus
    entradas (la superficie y la final, la capa de entradas, las máscaras, las bermas y las plataformas: cambiar una la deja obsoleta, RF-008-24), los datos, las cifras con su ámbito y el
    mensaje. Una entidad que ya estaba en su versión (``prepared.existing``: recalcularla) no vuelve a escribir sus parámetros. Si algo falla, o lo que consume cambió desde que se calculó,
    no queda nada y el error sigue; **no modifica ninguna capa de entrada**. Cerrar el generador antes de que termine borra los temporales. Devuelve lo guardado
    (:class:`~.store.Stored`). Todas las salidas se escriben siempre (también vacías: una versión sin plataformas tiene su tabla sin filas)."""
    if not isinstance(outcome, AccessOutcome):
        raise TypeError(f"se crea la accesibilidad de un AccessOutcome, no {outcome!r}")
    name = prepared.job.request.name
    yield Progress(_STORE_PHASE, 0, 1, f"Guardando la accesibilidad «{name}»…")

    def grid_units() -> Generator[None, None, Any]:
        values = reachable_grid(outcome)
        yield
        return (yield from writer.grid_steps(provenance.ACCESS_GRID, Raster(prepared.job.grid, values, writer.crs, writer.vertical)))

    yield from pipeline.forward(_store_steps(grid_units(), budget_s, "lo alcanzable"))
    for family, rows, what in ((provenance.ACCESS_BERMS_TABLE, berm_rows(outcome), "la tabla de bermas"), (provenance.ACCESS_PLATFORMS_TABLE, platform_rows(outcome), "la tabla de plataformas"),
                               (provenance.ACCESS_ZONES_TABLE, zone_rows(outcome), "la tabla de zonas"), (provenance.ENTITY_REPORT_TABLE, access_report_rows(outcome), "el informe")):
        yield from pipeline.forward(_store_steps(writer.table_steps(family, rows), budget_s, what))
    yield Progress(_STORE_PHASE, 1, 1, f"Registrando la accesibilidad «{name}»…")
    resumed = writer.handle is not None  # un recálculo: la operación empezó antes de calcular (``run_access``)

    def parameters(conn: sqlite3.Connection) -> None:
        if prepared.existing:
            if ParameterStore(project).get(entity_key(prepared.code, AccessParam.NAME), version=prepared.version_uid, conn=conn) is None:
                raise ValueError(f"la entidad {prepared.code} no tiene sus parámetros en su versión: no está en ella (se prepara sin su código)")
        else:
            entity_store.set_entity_params(project, prepared.rows, version=prepared.version_uid, decided_by=decided_by, conn=conn)

    return writer.commit(None if resumed else prepared.start, figures=outcome.figures, message=outcome.message, before_begin=parameters)


def create_access(project: StoreProject, writer: DesignWriter, prepared: PreparedAccess, outcome: AccessOutcome, *, decided_by: str | None = None) -> Stored:
    """:func:`create_access_steps` de una vez (sin ceder el hilo): lo guardado (:class:`~.store.Stored`), con los mismos rechazos y la misma transacción."""
    work = create_access_steps(project, writer, prepared, outcome, decided_by=decided_by)
    while True:
        try:
            next(work)
        except StopIteration as stop:
            result: Stored = stop.value
            return result


# --- Recalcular (spec 017, T17b; RF-017-24, RF-015-02, RF-015-16; RF-008-26) ---------------------------------------


def run_access(project: StoreProject, request: AccessRequest, *, version: str | None, code: str, masks: access.MaskSet | None = None, supersedes: str | None = None,
               budget_s: float = STEP_BUDGET_S) -> tuple[OperationHandle, Iterator[Progress]]:
    """Calcula y registra ``request`` —la accesibilidad de la entidad ``code``, que ya está en su versión— de **una vez**, sin pedir confirmación (el recálculo de lo obsoleto,
    :func:`~.store.recompute_run`; el «Crear» tras «Calcular» es :meth:`~.steps.Calculation.create`): prepara (:func:`prepare_access`: la entidad se reconoce por su ``code``), empieza la
    operación **antes de calcular** —sustituye a ``supersedes``— con lo que lee hoy (la capa de entradas, la superficie y la final, las bermas, las huellas de las plataformas y las
    máscaras de la versión) y devuelve su ``OperationHandle`` «en curso» y sus pasos, que avanza quien la llama: calculan (:func:`access_compute_steps`), escriben cada salida en su temporal y
    completan la operación en una transacción (:func:`create_access_steps` con el escritor reanudado: no escribe los parámetros, que ya están); el último paso lleva lo guardado
    (:class:`~.store.Stored`). Cerrarlos antes, o un fallo, no dejan nada y la operación queda cancelada o fallida.

    Al llamar, sin empezar nada: los rechazos de :func:`prepare_access`. Al avanzar, antes de escribir nada, ``des.input_changed`` si un parámetro cambió entre prepararla y empezar la
    operación."""
    prepared = prepare_access(project, request, version=version, masks=masks, code=code, supersedes=supersedes)
    handle = prepared.start.begin(project)
    return handle, _access_run(project, handle, prepared, budget_s)


def recompute_access(request: RecomputeRequest, *, budget_s: float = STEP_BUDGET_S) -> tuple[OperationHandle, Iterator[Progress]]:
    """Repite la operación ``des.road_access`` de ``request`` (:func:`~.store.recompute_run`; «Recalcular lo obsoleto», RF-008-26; spec 017, T17b; RF-017-24, RF-015-02, RF-015-16): la
    accesibilidad de sus ajustes (el nombre, el código y el campo del nombre de los puntos de entrada) con los **parámetros vigentes de su entidad en su versión**
    (:func:`~.entity_store.entity_parameters`: la superficie, la capa de entradas, los datos de bermas y los tres umbrales; los de la versión y, si no, los del proyecto) y no los que leyó
    la operación que sustituye: una entidad se define por sus parámetros (RF-015-01). La superficie, la final, las bermas, la capa de entradas (su geometría) y las huellas de las
    plataformas son entradas de la operación: cambiar una la deja obsoleta **entera** y recalcular la repite con lo nuevo. Devuelve lo de :func:`run_access`. ``ValueError`` si los ajustes
    no son los de una accesibilidad o la petición no es de su tipo."""
    if not isinstance(request, RecomputeRequest):
        raise TypeError(f"se recalcula una RecomputeRequest, no {request!r}")
    if request.op_type != provenance.ROAD_ACCESS:
        raise ValueError(f"recompute_access repite {provenance.ROAD_ACCESS}, no «{request.op_type}»")
    project: StoreProject = request.project  # type: ignore[assignment]
    code = provenance.supported_code(request.settings)
    found = require_version(project, request.version, request.op_type)
    asked = provenance.access_request(request.settings, entity_store.entity_parameters(project, code, version=found))
    return run_access(project, asked, version=found.uid, code=code, supersedes=request.operation_uid, budget_s=budget_s)


def _check_recorded(handle: OperationHandle, prepared: PreparedAccess) -> None:
    """Los parámetros que anotó la operación al empezar son los que leyó el cálculo al prepararse (RF-013-17, D-14): si uno cambió entre las dos cosas, el resultado ya no le corresponde
    (``des.input_changed``, con el parámetro)."""
    read = {entity_key(prepared.code, AccessParam(name)): value for name, value in prepared.values.items()}
    for param in handle.params:
        if param.key in read and param.value != read[param.key]:
            raise DesignError("des.input_changed", obj=f"Parámetro «{param.key}»", field="parámetros", value=param.key)


def _access_run(project: StoreProject, handle: OperationHandle, prepared: PreparedAccess, budget_s: float) -> Generator[Progress, None, None]:
    with design_writer(project, handle.op_type, prepared.job.request.name, version=handle.version_uid, handle=handle) as writer:
        _check_recorded(handle, prepared)
        outcome: AccessOutcome = yield from access_compute_steps(prepared.job, budget_s=budget_s)
        stored: Stored = yield from create_access_steps(project, writer, prepared, outcome, budget_s=budget_s)
        yield Progress(_STORE_PHASE, 1, 1, outcome.message, result=stored)


# --- Leer lo guardado: lo que lee la verificación de la 012 (spec 017, T17b; RF-017-25, DIFF-017, P-9) -------------------


@dataclass(frozen=True, slots=True)
class AccessData:
    """Un dato que escribió una accesibilidad: su ``uid``, su ``name`` (``des_acz_accesibilidad``), su ``locator`` —dónde está en el proyecto: la tabla de su GeoPackage o la ruta relativa de su
    GeoTIFF— y el ``role`` con que lo anotó la operación (``access_zones``…), que es por lo que lo lee quien lo consume."""

    uid: str
    name: str
    locator: str
    role: str


@dataclass(frozen=True, slots=True)
class AccessZone:
    """Una fila de la tabla de zonas «requiere acceso» de una accesibilidad (``des_acz_``): el ``code`` de la zona (el de su restricción de la 012), si queda comunicada (``connected``) y,
    de la que no, su lugar (``x`` e ``y``), la distancia (``distance_m``) y la diferencia de cota (``level_difference_m``) a lo alcanzable más próximo; ``None`` lo que no se da."""

    code: str
    connected: bool
    x: float | None = None
    y: float | None = None
    distance_m: float | None = None
    level_difference_m: float | None = None


@dataclass(frozen=True, slots=True)
class Accessibility:
    """Una accesibilidad de una versión **al día** (spec 017, T17b; :func:`accessibilities_on`; lo que lee la verificación de la 012, DIFF-017) con lo que necesitan sus consumidores: su
    ``code`` (``ACC-001``), su ``name``, la ``version`` (su código) y su ``version_uid``, la ``operation`` (el uid de la vigente, la que escribió sus datos), la ``surface`` sobre la que se
    hizo (el nombre de su dato) y la ``final`` de la cantera de dos superficies cuya cota mínima también calculó (``None`` si no la tiene). Y sus datos por su papel
    (:class:`AccessData`): lo alcanzable (``reachable``), las bermas, las plataformas, las zonas «requiere acceso» (``zones``, el papel :data:`~.provenance.ROAD_ACCESS_ZONES_ROLE`) y el
    informe; y ``zone_rows``, **la tabla de zonas leída** (:class:`AccessZone`, en el orden de la tabla)."""

    code: str
    name: str
    version: str
    version_uid: str
    operation: str
    surface: str
    final: str | None
    reachable: AccessData
    berms: AccessData
    platforms: AccessData
    zones: AccessData
    report: AccessData
    zone_rows: tuple[AccessZone, ...] = ()

    @property
    def communicated(self) -> frozenset[str]:
        """Los códigos de las zonas «requiere acceso» que esta accesibilidad **comunica**: con ellos la 012 da «cumple» a una zona y «no cumple» a la que no está (T18)."""
        return frozenset(row.code for row in self.zone_rows if row.connected)


_ACCESS_OUTPUTS = (
    "SELECT d.uid, d.name, d.locator, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
    "WHERE io.operation_uid = ? AND io.direction = 'out' AND io.item_kind = 'dataset' ORDER BY io.fid")
_ACCESS_INPUT = (
    "SELECT d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
    "WHERE io.operation_uid = ? AND io.direction = 'in' AND io.item_kind = 'dataset' AND io.role = ? ORDER BY io.fid")


def read_access_surface(conn: sqlite3.Connection, operation_uid: str) -> str | None:
    """El nombre de la superficie (el de su dato) sobre la que se hizo la accesibilidad de la operación ``operation_uid`` (spec 017, T31; RF-015-25, RF-017-24; lo que dibuja la
    vista de lo alcanzable, ``bl.scene.des_views``, para poner cada celda alcanzable a la cota de su superficie): su **entrada con el papel de superficie**
    (:data:`~.provenance.SURFACE_ROLE`), no la final de una cantera ni la capa de entradas. ``None`` si la operación no la consumió. Solo lee."""
    found = conn.execute(_ACCESS_INPUT, (operation_uid, provenance.SURFACE_ROLE)).fetchone()
    return None if found is None else str(found[0])


def read_zone_table(conn: sqlite3.Connection, table: str) -> tuple[AccessZone, ...]:
    """Las filas de la tabla de zonas ``table`` (``des_acz_<nombre>_<vNN>``, o su nombre en un GeoPackage congelado) de la conexión ``conn``, en el orden de la tabla (``fid``). Lo comparten la
    lectura del proyecto (:func:`read_access_zones`) y la reproducción de la verificación de la 012, que lee la tabla congelada."""
    found = conn.execute(f'SELECT code, connected, x, y, distance_m, level_difference_m FROM "{table}" ORDER BY fid').fetchall()
    return tuple(AccessZone(str(code), bool(connected), None if x is None else float(x), None if y is None else float(y), None if distance is None else float(distance),
                            None if difference is None else float(difference)) for code, connected, x, y, distance, difference in found)


def read_access_zones(project: StoreProject, locator: str, *, conn: sqlite3.Connection | None = None) -> tuple[AccessZone, ...]:
    """La tabla de zonas «requiere acceso» de una accesibilidad que está en ``locator`` (la tabla de su GeoPackage: lo que dice su registro, :attr:`~core.datasets.DatasetRecord.locator`,
    o :attr:`AccessData.locator`), en el orden de la tabla. Solo lee; ``conn`` es una conexión de lectura de quien llama (con su instantánea)."""
    if conn is not None:
        return read_zone_table(conn, locator)
    with project.read() as reading:
        return read_zone_table(reading, locator)


def accessibilities_on(project: StoreProject, version: str, surface: str, *, conn: sqlite3.Connection | None = None) -> tuple[Accessibility, ...]:
    """Las accesibilidades **al día** hechas sobre la superficie ``surface`` (el nombre de su dato) de la ``version`` (su uid o su código) (spec 017, T17b; RF-017-25, DIFF-017; plan 017
    §5.4 A12 y §5.7 P-9; lo que lee la verificación de la 012, T18, por el papel de la tabla de zonas, sin importar ``design.entities`` ni ``design.road_*``), por orden de código. Solo
    cuenta la operación vigente de cada entidad (``entities.registry``) y solo si está **al día**: una obsoleta (cambió la superficie, una pista, una berma, una entrada o un umbral: la 008
    le da causas), descartada o sin calcular no se da, que es lo que protege a quien la lee de un veredicto de otra cosa. La superficie es la de **su parámetro** ``surface``, que coincide
    con la que consumió la operación mientras está al día: una hecha sobre otra superficie no se da. Solo lee; ``conn`` es una conexión de lectura de quien llama (con su instantánea).
    ``VersionError`` (``core.version_unknown``) si la versión no existe; ``ValueError`` si una accesibilidad al día no tiene alguno de sus datos (un proyecto dañado: no se lista a medias)."""

    def read(reading: sqlite3.Connection) -> tuple[Accessibility, ...]:
        found = versions_read.version(reading, str(version))
        if found is None:
            raise VersionError("core.version_unknown", field="versión", value=version, version=version)
        parameters = ParameterStore(project)
        listed: list[Accessibility] = []
        for entry in entities.registry(project, found.uid, conn=reading).entries:
            record = entry.record
            if record.kind != EntityKind.ACCESS or entry.operation_uid is None or record.state != EntityState.CURRENT:
                continue
            parameter = parameters.get(entity_key(record.code, AccessParam.SURFACE), version=found.uid, conn=reading)
            if parameter is None or parameter.value != surface:
                continue
            listed.append(_accessibility_of(reading, found, record.code, record.name, str(entry.operation_uid), surface))
        return tuple(listed)

    if conn is not None:
        return read(conn)
    with project.read() as reading:
        return read(reading)


def _accessibility_of(conn: sqlite3.Connection, version: Version, code: str, name: str, operation: str, surface: str) -> Accessibility:
    """La :class:`Accessibility` de la entidad ``code`` cuya operación vigente es ``operation``: sus datos por su papel (uno de cada) y su tabla de zonas leída."""
    written = [AccessData(str(uid), str(found), str(locator), str(role)) for uid, found, locator, role in conn.execute(_ACCESS_OUTPUTS, (operation,)).fetchall()]

    def one(role: str) -> AccessData:
        found = [item for item in written if item.role == role]
        if len(found) != 1:
            raise ValueError(f"la accesibilidad {code} («{name}») tiene {len(found)} datos con el papel «{role}» en su operación {operation}: tiene que tener uno")
        return found[0]

    zones = one(provenance.ROAD_ACCESS_ZONES_ROLE)
    final = conn.execute(_ACCESS_INPUT, (operation, provenance.ACCESS_FINAL_ROLE)).fetchone()
    return Accessibility(code, name, version.code, version.uid, operation, surface, None if final is None else str(final[0]), one(provenance.ROAD_ACCESS_ROLE),
                         one(provenance.ROAD_ACCESS_BERMS_ROLE), one(provenance.ROAD_ACCESS_PLATFORMS_ROLE), zones, one(provenance.ENTITY_REPORT_ROLE), read_zone_table(conn, zones.locator))


EXCLUDED_OTHER_SURFACE = "other_surface"
"""La causa de una accesibilidad que una verificación no usa: se hizo sobre otra superficie que la que verifica."""
EXCLUDED_STALE = "stale"
"""La causa de una accesibilidad que una verificación no usa: hecha sobre esa superficie, está obsoleta."""


@dataclass(frozen=True, slots=True)
class ExcludedAccessibility:
    """Una accesibilidad que ve una versión y que **no se usa** sobre una superficie (spec 017, T18; RF-012-22, DIFF-017): su ``code`` (``ACC-001``), su ``name``, la ``surface`` sobre la que está
    hecha (el nombre de su dato; vacío si no tiene), el ``reason`` (:data:`EXCLUDED_OTHER_SURFACE`: se hizo sobre otra superficie; :data:`EXCLUDED_STALE`: está obsoleta) y, de una obsoleta, su
    ``cause`` en español y su ``cause_en`` en inglés (lo que cambió, según la 008; quien la muestra elige la del idioma de la interfaz)."""

    code: str
    name: str
    surface: str
    reason: str
    cause: str = ""
    cause_en: str = ""


def accessibilities_excluded(project: StoreProject, version: str, surface: str | None, *, conn: sqlite3.Connection | None = None) -> tuple[ExcludedAccessibility, ...]:
    """Las accesibilidades que ve la ``version`` (su uid o su código) y que **no** da :func:`accessibilities_on` para ``surface``, con su causa (spec 017, T18; RF-012-22, DIFF-017; plan 017
    §5.4 A12 y §5.7 P-9; el aviso de la verificación de la 012, como ``stockpile_store.detections_excluded`` de la 016): las **hechas sobre otra superficie** (:data:`EXCLUDED_OTHER_SURFACE`,
    estén al día o no) y las **obsoletas** sobre ``surface`` (:data:`EXCLUDED_STALE`, con lo que cambió: la causa de la 008). Con ``surface`` ``None`` (una superficie que no es el dato de ninguna
    accesibilidad: una cota constante, un dato congelado), todas son de otra superficie. Una descartada, una sin calcular o una con su apoyo retirado no se avisa: no son un dato que se esperaba. Por
    orden de código. Solo lee; ``conn`` y los errores, como en :func:`accessibilities_on`."""

    def read(reading: sqlite3.Connection) -> tuple[ExcludedAccessibility, ...]:
        found = versions_read.version(reading, str(version))
        if found is None:
            raise VersionError("core.version_unknown", field="versión", value=version, version=version)
        parameters = ParameterStore(project)
        listed: list[ExcludedAccessibility] = []
        for entry in entities.registry(project, found.uid, conn=reading).entries:
            record = entry.record
            if record.kind != EntityKind.ACCESS or entry.operation_uid is None or record.state not in (EntityState.CURRENT, EntityState.STALE):
                continue
            parameter = parameters.get(entity_key(record.code, AccessParam.SURFACE), version=found.uid, conn=reading)
            made_on = None if parameter is None else str(parameter.value)
            on_it = surface is not None and made_on == surface
            if on_it and record.state == EntityState.CURRENT:
                continue  # la que se usa
            if not on_it:
                listed.append(ExcludedAccessibility(record.code, record.name, "" if made_on is None else made_on, EXCLUDED_OTHER_SURFACE))
                continue
            uid = str(entry.operation_uid)
            cause = stale.item_text(reading, stale.OPERATION, uid, language="es") or "cambió algo de lo que lee"
            cause_en = stale.item_text(reading, stale.OPERATION, uid, language="en") or "something it reads changed"
            listed.append(ExcludedAccessibility(record.code, record.name, str(surface), EXCLUDED_STALE, cause, cause_en))
        return tuple(listed)

    if conn is not None:
        return read(conn)
    with project.read() as reading:
        return read(reading)
