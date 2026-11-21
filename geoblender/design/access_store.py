# SPDX-License-Identifier: GPL-3.0-or-later
"""Preparar y calcular la accesibilidad de las pistas: lo que se lee y se rechaza **antes de calcular**, el cálculo por pasos y su resumen (spec 017, T17; HU-017-3; RF-017-24,
RF-017-25, RF-017-04 y RF-017-30; RF-015-02, RF-015-03 y RF-015-16; RF-015-08; RNF-017-05 y RNF-017-06; plan 017 §5.2.2, §5.2.3, §5.3.2, §5.4 A10 y A11 y §5.7 P-1 y P-9; D-17 y D-18).

El homólogo, para la accesibilidad (``des.road_access``: una entidad **sin cadena**, ``ACC-001``, **sin huella**: nadie parte de su dato), de ``design.stockpile_store`` (la detección de
acopios, sin cadena). **Solo lee**: nada se escribe en el proyecto (RF-015-03) salvo las máscaras de la versión si no estaban al día (una operación propia, RF-013-04, y solo si no se
dan cargadas). La accesibilidad **no llama a** ``refuse_pending`` (``design.sectors``): no mueve ninguna celda ni cambia ninguna superficie ni restricción (RF-017-25).

**Crear** en una transacción, **recalcular**, **reproducir** y la **lectura para la 012** (la accesibilidad al día hecha sobre una superficie dada, con su tabla de zonas) son de la T17b.

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

Python puro (nivel 8), con numpy. ``design.access_store`` es un módulo pesado de la 017: lo importan las órdenes al usarlo, no ``bl`` al registrarse
(``tests/unit/architecture/test_lazy_registration.py``).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Generator, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

import numpy as np

from ..core.constraints.model import ConstraintType
from ..core.datasets import registry as dataset_registry
from ..core.datasets.model import DatasetRecord, DatasetStatus
from ..core.project.model import Progress
from ..core.provenance import stale
from ..core.versions.model import Version
from ..gis.masks import access
from ..gis.masks.combine import ClassBit
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.messages import GisError
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
from .store import OperationStart, _loaded_masks, _start, require_version
from .surfaces import project_frame, read_surface_steps

__all__ = [
    "AccessSummary",
    "PreparedAccess",
    "access_compute_steps",
    "access_obsolete",
    "access_summary",
    "access_values",
    "access_zones",
    "platform_cells",
    "prepare_access",
    "prepare_access_units",
    "prepared_summary",
    "untouchable_cells",
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
    job = AccessJob(
        request, chosen, grid, surface.values, entries, untouchable_cells(masks), values[AccessParam.WALK_SLOPE.value], values[AccessParam.WALK_WIDTH.value],
        values[AccessParam.MIN_BERM_AREA.value], final, tuple(berms), platforms, access_zones(masks))
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
