# SPDX-License-Identifier: GPL-3.0-or-later
"""Preparar la corta —lo que se lee y se rechaza **antes de calcular**— (spec 018, T21; HU-018-1 y HU-018-5; RF-018-01 a RF-018-06, RF-018-09 a 14 en lo que
toca a la entrada; RF-015-06, RF-015-07, RF-015-08; plan 018 §5.2.1, §5.3.1, §5.4 A0 y A1, §5.7 P-13).

El homólogo, para la corta (``des.pit``: una entidad **con cadena**, ``PIT-001``), de :mod:`design.road_store` y de
:func:`design.entity_store.prepare_platform_units`: **solo lee**. Nada se escribe en el proyecto (RF-015-03; salvo las máscaras de la versión si
no estaban al día, una operación propia, RF-013-04, y solo si no se dan cargadas).

Lo que hace :func:`prepare_pit_units` (y :func:`prepare_pit`, de una vez), en este orden y sin escribir nada:

- la versión editable (RF-009-21), el código ``PIT-nnn`` y el nombre únicos, **la partida** (RF-018-03: la elige la persona; en blanco, la última de la
  cadena de entidades si es una sola) con la cadena (una entidad por superficie y sin ciclos: ``des.entity_start_taken``);
- **la capa de origen** (RF-018-01, RF-018-02): una capa de **polígonos** del proyecto, con el campo del nombre y, en el modo ascendente, el de la
  **cota** de cada fondo (en el descendente es opcional: la cota de la cresta). Los rechazos de RF-018-04, cada uno con la capa, la corta, el campo y el
  valor y **sin escribir nada**: la capa no es de polígonos o no tiene el campo, **un polígono con huecos** (P-13: ``des.pit_source_holes``), uno que se
  corta a sí mismo, sin área, con un vértice repetido, fuera de la rejilla o sin dato en la superficie de partida (``des.pit_polygon_invalid``), dos que
  se solapan (``des.pit_polygons_overlap``), un fondo sin cota (``des.pit_level_missing``), con una cota **fuera de la retícula** ``z₀ + j·n·h`` (D-4;
  ``des.pit_level_off_lattice``) o que no queda por debajo del terreno en ningún punto de su contorno (``des.pit_nothing_to_excavate``). Las capas de
  un proyecto están todas en el CRS del proyecto (se reproyectan al importarlas): no hay una «capa ajena» que comparar;
- **los perfiles de banco** de la 013 (RF-018-06): el base y el de cada sector, con sus valores comprobados (RF-013-19); dos con distinta altura o ancla se
  rechazan con los dos y sus valores (``des.pit_profiles_differ``); un sector con un número de bancos por berma distinto del de la corta, también
  (``des.pit_sector_n_berm``: la T12 admite uno solo para toda la corta);
- **los parámetros** resueltos y comprobados (RF-015-08: sin valor por defecto salvo ``n_berm`` y ``corner``; las dos tolerancias del desfase se piden); en
  el modo descendente **al menos un criterio de parada** (``des.pit_no_stop``: el ancho mínimo, la cota de fondo o el máximo de bancos, D-8);
- las **zonas sin rampa** de su capa de polígonos (RF-018-15);
- las **máscaras** de la versión por el contrato de la 012 (RF-018-05: el corte y el relleno admitidos y lo intocable) y **la búsqueda de intocables** de los
  sectores que toca la corta (RF-015-07: ``refuse_pending`` **se llama aquí**, nada lo hace solo);
- el **hash** de la geometría de cada polígono de origen (RF-018-01) y **la ventana de trabajo** (A0).

**T21b**: los **bancos fijados** (RF-018-23: las líneas con Z de una línea de rotura ``gis_brk_`` o de una capa propuesta ``des_rpl_``, cada una un anillo
cerrado con la Z de cada vértice, con su número de banco por el campo que se elija o, sin él, su cota), la **roseta** del perfil base y de cada sector
(RF-018-07: sus rangos de azimut con ``check_rose``, que además ensanchan el alcance de la ventana), las **definiciones de rampa** (RF-018-15: sus valores
con ``check_ramp`` y el perfil de pista de la 017 que usan, que lleva el trabajo en ``road_profiles``) y **el punto de inicio** de cada una
(:class:`~design.pit_model.RampStart`: ``fondo`` o ``banco N``, que sitúa la rampa sobre la polilínea de ese banco, o ``capa:nombre``, un punto de una capa
de puntos). **Un desfase no fiable** (``Benches.reliable``) no se puede rechazar antes de calcular: lo hace el cálculo (T22).

Python puro (nivel 8), con numpy. Pesado: lo importan las órdenes al usarlo, no ``bl`` al registrarse
(``tests/unit/architecture/test_lazy_registration.py``).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections.abc import Callable, Collection, Generator, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Protocol

import numpy as np

from ..core.constraints import store as constraint_store
from ..core.constraints.model import ConstraintType, Sector
from ..core.datasets import registry as dataset_registry
from ..core.project.model import Progress
from ..core.provenance.operations import OperationHandle, Use
from ..core.provenance.recompute import RecomputeRequest
from ..core.params import PROJECT_SCOPE, VERSION_SCOPE, ParameterStore, definition
from ..core.versions.model import Version
from ..gis import polygons
from ..gis.grid import Grid
from ..gis.masks import access
from ..gis.masks import provenance as masks_declared
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.masks.store import available_tables, read_shapes, search_sectors
from ..gis.messages import GisError
from ..gis.raster import Raster
from ..gis.store import StoreProject, load_features
from ..gis.vector import FeatureLayer
from . import (
    entities,
    entity_store,
    pipeline,
    pit_bench,
    pit_check013,
    pit_ramp,
    pit_ramp_def,
    pit_report,
    pit_rose,
    pit_sky,
    pit_surface,
    provenance,
    road_profiles,
)
from .compose import admitted_pair
from .entities import EntityKind, EntityRegistry, EntityState
from .entity_store import EntityParamRow
from .messages import DesignError
from .model import BenchParam, BenchProfile
from .params import (
    PERIMETER_SEGMENT,
    VERIFY_MIN_THICKNESS,
    PitParam,
    PitRampParam,
    PitSectorParam,
    RoadProfileParam,
    RoseParam,
    bench_key,
    check_entity_param,
    entity_key,
    entity_params,
    pit_sector_key,
    pitramp_key,
    road_profile_key,
    rose_key,
)
from .pit_bench import _LATTICE_TOL_M, _samples
from .pit_model import (
    FixedBench,
    PitCode,
    PitJob,
    PitMode,
    PitOutcome,
    PitParams,
    PitRequest,
    PitSector,
    PitSource,
    RampDef,
    RampStart,
    RoseRange,
)
from .platform import _project_number, _window_grid
from .pit_lines import LineRow
from .preview import Notice, Obsolete, ObsoleteKind, PitSummary, obsolete_notices
from .road_model import Parts, Window
from .road_profiles import RoadProfile
from .road_section import sample_terrain
from .report import _thickness
from .road_store import (
    _LINES_3D_PREFIXES,
    _ROUTE_PREFIX,
    Lines3D,
    OtherReader,
    _supportable,
    other_design_notices,
    other_designs,
    other_reader,
    read_lines_3d,
    untouchable_cells,
)
from .sectors import design_sectors, refuse_pending
from .seeds import pace_progress, sector_layout
from .store import (
    _STORE_PHASE,
    DesignWriter,
    OperationStart,
    Stored,
    _LateSupports,
    _loaded_masks,
    _real,
    _seen,
    _start,
    _store_steps,
    require_version,
)
from .surfaces import project_frame, read_surface_steps
from .zones import polygons_cells

__all__ = ["ensure_name_row", "entity_pit_request", "pit_parameters", "recompute_pit", "run_pit", "OFFSET_NOT_VERIFIED", "OTHERS_SEEN", "OTHER_DESIGN_DIFFERS", "PitReader", "PreparedPit", "ProjectReader", "compare_others", "compute", "compute_steps", "confirm_ramps", "create_pit", "create_pit_steps",
           "fixed_of", "frozen_job", "limits_of_shapes", "noramp_parts", "rose_numbers_of", "sources_hashes",
           "other_designs_steps", "pit_bench_rows", "pit_entity_rows", "pit_finding_rows", "pit_obsolete", "pit_operation_start", "pit_polyline_rows", "pit_ramp_rows", "pit_report_rows",
           "pit_skyline_rows", "pit_summary", "prepare_pit", "prepare_pit_units", "source_sha256", "summary_of"]

_NUMERIC = frozenset({"INTEGER", "DOUBLE"})
_NAME_FIELDS = ("nombre", "name")
_DIALOG = "diálogo de «Nueva corta…»"
"""El origen de lo que elige la persona en el diálogo de la orden."""
_START_ROLE = "superficie de partida"
_WINDOW_MARGIN_CELLS = 2
"""A0: lo que la ventana de trabajo rodea a la caja de lo que se toca (celdas)."""


# --- Lo que se prepara -----------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class PreparedPit:
    """Lo que se lee y se comprueba antes de calcular una corta (:func:`prepare_pit_units`): el ``job`` (:class:`~design.pit_model.PitJob`: todo lo leído y
    nada del proyecto), lo que anotará la operación (``start``: su tipo ``des.pit``, sus ajustes, entradas y parámetros), el ``code`` de la entidad
    (``PIT-001``), la ``version`` (la editable), el nombre del dato de la superficie de partida (``start_surface``) y lo que dice su parámetro ``start``
    (``start_ref``: el nombre de un dato o ``entity:<código>``), el de la de apoyo (``support_surface``; ``None`` sin ella), la capa de origen (``layer``),
    las ``rows`` de los parámetros de la entidad —**todas** las que lee la operación: sin su fila, ``begin_operation`` crearía la del valor por defecto en
    el proyecto— y sus ``values`` resueltos y comprobados (por último segmento de su clave), los parámetros del proyecto que lee el cálculo (``common``),
    la ``window`` de trabajo (A0: filas y columnas de la rejilla; lo que se toca más dos celdas), el ``sources_sha256`` de la geometría de cada polígono
    de origen (RF-018-01: por nombre), los códigos de las entidades en que **se apoya** (``supports``) y los ``notices`` de la preparación. ``existing``:
    la entidad ya estaba en su versión (se preparó con su ``code``: recalcularla)."""

    job: PitJob
    start: OperationStart
    code: str
    version: Version
    start_surface: str
    start_ref: str
    support_surface: str | None
    layer: str
    rows: tuple[EntityParamRow, ...]
    values: Mapping[str, Any]
    common: Mapping[str, float]
    window: Window
    sources_sha256: Mapping[str, str]
    supports: tuple[str, ...] = ()
    notices: tuple[Notice, ...] = ()
    existing: bool = False

    @property
    def op_type(self) -> str:
        """El tipo de la operación (``des.pit``)."""
        return self.start.op_type

    @property
    def version_uid(self) -> str:
        """El uid de la versión de la corta: lo que reciben ``design_writer`` y ``set_entity_params``."""
        return self.version.uid


def source_sha256(ring: np.ndarray, level_m: float | None) -> str:
    """El hash del contenido de un polígono de origen (RF-018-01): el anillo absoluto en float64 y su cota (``nan`` si no la lleva). Lo que cambia con
    la geometría o la cota; no con el nombre."""
    digest = hashlib.sha256()
    digest.update(np.ascontiguousarray(ring, dtype=np.float64).tobytes())
    digest.update(np.float64(math.nan if level_m is None else level_m).tobytes())
    return digest.hexdigest()


# --- Los rechazos ---------------------------------------------------------------------------------------------------------


def _reject(error: str, request: PitRequest, code: str, param: PitParam | str, value: object, **values: object) -> DesignError:
    """El rechazo ``error`` de la corta ``request`` (código ``code``) por el valor ``value`` del campo ``param``: nombra la capa, la corta, el campo y el
    valor (RF-018-04)."""
    return DesignError(error, obj=f"Corta «{request.name}» de la capa «{request.layer}»", field=entity_key(code, param), value=value, layer=request.layer,
                       entity=request.name, **values)


def _identify(project: StoreProject, version: Version, request: PitRequest, code: str | None) -> tuple[str, EntityRegistry]:
    """El código de la corta (``code`` si se da: una entidad que ya está en la versión; si no, el siguiente ``PIT-nnn``) y el registro de las entidades
    de la versión, tras comprobar que su nombre es único (RF-015-01: ``des.entity_name_repeated``)."""
    registry = entities.registry(project, version.uid)
    chosen = code if code is not None else entities.next_code(EntityKind.PIT, (entry.record.code for entry in registry))
    entity_store._check_name(registry, request.name, chosen, version.code)
    return chosen, registry


def _start_dataset(registry: EntityRegistry, version: Version, name: str, code: str, ref: str, param: PitParam) -> str:
    """El nombre del dato de la superficie ``ref`` de la corta (``start`` o ``support``): el nombre de una superficie, tal cual; ``entity:<código>``, la de esa
    entidad (``des_psf_<nombre>``), que ha de estar calculada y no descartada (``des.entity_start_unknown``)."""
    target = entities.ref_code(ref)
    if target is None:
        return ref
    entry = registry.get(target)
    if entry is None or entry.record.state in (EntityState.UNCALCULATED, EntityState.DISCARDED):
        raise DesignError("des.entity_start_unknown", obj=entity_store._entity_object(code, name), field=entity_key(code, param), value=ref, entity=name,
                          version=version.code)
    return provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, entry.record.name)


def _default_start(registry: EntityRegistry) -> str | None:
    """La partida por defecto (RF-018-03): la última de la cadena de entidades de la versión (la que deja una entidad calculada y viva), si es una sola.
    ``None`` si no hay ninguna o hay varias: no se elige una por la persona."""
    tails = [tail for tail in entities.chain_tails(registry.records) if tail.state not in (EntityState.UNCALCULATED, EntityState.DISCARDED)]
    return entities.surface_ref(tails[0].code) if len(tails) == 1 else None


# --- La capa de origen ----------------------------------------------------------------------------------------------------


def _layer(project: StoreProject, name: str) -> FeatureLayer:
    """La capa de entidades ``name`` del proyecto (solo lee); ``ValueError`` si no es una capa de entidades (``gis_fea_``)."""
    found = load_features(project, name)
    if not isinstance(found, FeatureLayer):
        raise ValueError(f"«{name}» no es una capa de entidades del proyecto (gis_fea_)")
    return found


def _polygon_layer(project: StoreProject, name: str, request: PitRequest, code: str, param: PitParam) -> FeatureLayer:
    layer = _layer(project, name)
    if layer.kind != "polygon":
        raise _reject("des.pit_layer_kind", request, code, param, {"point": "puntos", "line": "líneas"}.get(layer.kind, layer.kind), expected="polígonos")
    return layer


def _text_column(layer: FeatureLayer, wanted: str | None) -> str | None:
    """La columna de texto de la capa que se llama ``wanted`` (por su campo o su columna); ``None`` si no hay ninguna."""
    for column in layer.columns:
        if column.sql_type not in _NUMERIC and wanted in (column.field, column.column):
            return column.column
    return None


def _names(layer: FeatureLayer, request: PitRequest, code: str, wanted: str | None) -> tuple[str, ...]:
    """El nombre de cada geometría de la capa: el campo que eligió la persona (``des.pit_layer_field`` si la capa no lo tiene o no es de texto) o, sin él,
    el campo ``nombre`` o ``name`` y, donde falta, el número de la geometría (``fid``)."""
    if wanted is None:
        found = entity_store._names(layer)
    else:
        column = _text_column(layer, wanted)
        if column is None:
            fit = [item.field for item in layer.columns if item.sql_type not in _NUMERIC]
            raise _reject("des.pit_layer_field", request, code, PitParam.LAYER, wanted, expected="de texto", fields=", ".join(fit) or "—")
        found = tuple(None if value is None else str(value).strip() for value in layer.values[column])
    return tuple(text if text else str(fid) for text, fid in zip(found, layer.fids, strict=True))


def _number_column(layer: FeatureLayer, wanted: str | None, request: PitRequest, code: str) -> tuple[float | None, ...] | None:
    """El valor de cada geometría de la capa por su campo numérico ``wanted`` (``None`` donde no lo tiene o no es un número finito); ``None`` si no se pidió
    campo. ``des.pit_layer_field`` si la capa no tiene ese campo numérico."""
    if wanted is None:
        return None
    for column in layer.columns:
        if column.sql_type in _NUMERIC and wanted in (column.field, column.column):
            found: list[float | None] = []
            for value in layer.values[column.column]:
                number = None if value is None or isinstance(value, bool) else float(value)
                found.append(number if number is not None and math.isfinite(number) else None)
            return tuple(found)
    fit = [item.field for item in layer.columns if item.sql_type in _NUMERIC]
    raise _reject("des.pit_layer_field", request, code, PitParam.LAYER, wanted, expected="numérico", fields=", ".join(fit) or "—")


def _levels(layer: FeatureLayer, request: PitRequest, code: str) -> tuple[float | None, ...] | None:
    """La cota de cada geometría de la capa por el campo de cota que eligió la persona (``None`` donde no la tiene o no es un número finito);
    ``None`` si no se pidió campo. ``des.pit_layer_field`` si la capa no tiene ese campo numérico."""
    return _number_column(layer, request.level_field, request, code)


def _open_ring(ring: np.ndarray) -> np.ndarray:
    """El anillo sin repetir el primer vértice al final."""
    array = np.asarray(ring, dtype=np.float64)
    if len(array) > 1 and bool((array[0] == array[-1]).all()):
        return array[:-1]
    return array


def _place_text(x: float, y: float) -> str:
    return f" (cerca de x = {x:.2f}, y = {y:.2f})"


def _invalid(request: PitRequest, code: str, name: str, reason: str, place: tuple[float, float] | None = None) -> DesignError:
    return _reject("des.pit_polygon_invalid", request, code, PitParam.LAYER, name, reason=reason, place="" if place is None else _place_text(*place))


def _sources(layer: FeatureLayer, request: PitRequest, code: str) -> tuple[list[PitSource], list[np.ndarray]]:
    """Los polígonos de origen de la capa (uno por parte de cada geometría; una geometría de varias partes da ``nombre/1``, ``nombre/2``…): cada anillo
    sin repetir el primer vértice, **sin huecos** (P-13) y sin vértice repetido seguido, y con su cota si la capa la da (RF-018-02). Da los
    :class:`PitSource` y sus anillos ``(k, 2)``. **No modifica nada** de la capa."""
    names = _names(layer, request, code, request.fields.name_field)
    levels = _levels(layer, request, code)
    found: list[PitSource] = []
    rings: list[np.ndarray] = []
    for index, name in enumerate(names):
        parts = layer.parts[index]
        for number, part in enumerate(parts, start=1):
            label = name if len(parts) == 1 else f"{name}/{number}"
            if len(part) > 1:
                raise _reject("des.pit_source_holes", request, code, PitParam.LAYER, label, count=len(part) - 1)
            ring = _open_ring(part[0])
            if len(ring) < 3:
                raise _invalid(request, code, label, "tiene menos de tres vértices")
            repeated = np.flatnonzero((ring == np.roll(ring, -1, axis=0)).all(axis=1))
            if repeated.size:
                x, y = ring[int(repeated[0])]
                raise _invalid(request, code, label, "tiene un vértice repetido", (float(x), float(y)))
            level = None if levels is None else levels[index]
            if request.mode is PitMode.UP and level is None:
                raise _reject("des.pit_level_missing", request, code, PitParam.LAYER, label, level_field=request.level_field or "—")
            found.append(PitSource(label, ring, level))
            rings.append(ring)
    if not found:
        raise _reject("des.entity_field_value", request, code, PitParam.LAYER, "—")
    return found, rings


_PROBLEMS_ES = {"self_intersecting": "se corta a sí mismo", "no_area": "no tiene área", "hole_outside": "tiene un hueco mal situado"}


def _check_polygons(sources: Sequence[PitSource], request: PitRequest, code: str, grid: Grid, start: np.ndarray) -> None:
    """RF-018-04: cada polígono es válido (simple, con área, sin vértice repetido), cae **dentro de la rejilla** y **con dato** en la superficie de partida
    (en sus vértices y en un punto cada celda de sus lados) y dos no se solapan."""
    found = polygons.problems([(source.ring,) for source in sources])
    for problem in found:
        name = sources[problem.index].name
        if problem.problem == "overlap":
            assert problem.other is not None
            raise _reject("des.pit_polygons_overlap", request, code, PitParam.LAYER, name, other=sources[problem.other].name,
                          area=round(float(problem.area_m2 or 0.0), 3))
        raise _invalid(request, code, name, _PROBLEMS_ES.get(problem.problem, problem.problem))
    east, south = grid.west + grid.ncols * grid.dx, grid.north - grid.nrows * grid.dy
    for source in sources:
        ring = np.asarray(source.ring, dtype=np.float64)
        outside = (ring[:, 0] < grid.west) | (ring[:, 0] > east) | (ring[:, 1] < south) | (ring[:, 1] > grid.north)
        if bool(outside.any()):
            x, y = ring[int(np.argmax(outside))]
            raise _invalid(request, code, source.name, "sale de la rejilla del proyecto", (float(x), float(y)))
        points = _samples(ring, min(grid.dx, grid.dy))
        ground = sample_terrain(start, grid, points[:, 0], points[:, 1])
        missing = np.isnan(ground)
        if bool(missing.any()):
            x, y = points[int(np.argmax(missing))]
            raise _invalid(request, code, source.name, "no tiene dato en la superficie de partida", (float(x), float(y)))


def _check_levels(sources: Sequence[PitSource], request: PitRequest, code: str, grid: Grid, start: np.ndarray, profile: BenchProfile, n_berm: int) -> None:
    """RF-018-04 y D-4 (modo ascendente): la cota de cada fondo está en la retícula ``z₀ + j·n·h`` de los bancos (planos continuos) y queda por debajo
    del terreno en algún punto de su contorno (si no, no hay nada que excavar)."""
    step = profile.height_m * n_berm
    for source in sources:
        assert source.level_m is not None
        index = round((source.level_m - profile.anchor_m) / step)
        if abs(source.level_m - (profile.anchor_m + index * step)) > _LATTICE_TOL_M:
            raise _reject("des.pit_level_off_lattice", request, code, PitParam.LAYER, source.name, level=source.level_m, anchor=profile.anchor_m, step=step)
        points = _samples(np.asarray(source.ring, dtype=np.float64), min(grid.dx, grid.dy))
        ground = sample_terrain(start, grid, points[:, 0], points[:, 1])
        if not bool((ground > source.level_m).any()):
            raise DesignError(PitCode.NOTHING_TO_EXCAVATE.value, obj=f"Corta «{request.name}» de la capa «{request.layer}»", field=source.name,
                              value=source.level_m, name=request.name)


def _noramp(project: StoreProject, request: PitRequest, code: str) -> Parts | None:
    """Las zonas sin rampa (RF-018-15) de su capa de polígonos: por geometría y parte, sus anillos absolutos. ``None`` si no se pide la capa."""
    if request.noramp is None:
        return None
    return noramp_parts(_polygon_layer(project, request.noramp.layer, request, code, PitParam.NORAMP_LAYER))


def noramp_parts(layer: FeatureLayer) -> Parts | None:
    """Las zonas sin rampa de la capa de polígonos ``layer`` (la del proyecto o la congelada): por geometría y parte, sus anillos absolutos. ``None`` sin ninguna."""
    found = tuple(tuple(np.array(ring, dtype=np.float64) for ring in part) for parts in layer.parts for part in parts)
    return found or None


# --- Los bancos fijados, la roseta, las rampas y su inicio (T21b) -----------------------------------------------------------


_EXPANDED_PREFIX = provenance.FAMILIES_BY_CODE[provenance.PIT_EXPANDED_TABLE].prefix
_FIXED_PREFIXES = (*_LINES_3D_PREFIXES, _EXPANDED_PREFIX)
"""Las capas de líneas con Z que valen como bancos fijados: las líneas de rotura, la capa propuesta de la 017 y, desde la T28, la del banco expandido (``des_pxb_``)."""
_VERSION_PREFIXES = (_ROUTE_PREFIX, _EXPANDED_PREFIX)
"""Las que son un dato de **una versión** (el resto es del proyecto)."""
_BENCH_START = re.compile(r"banco\s+(\d+)", re.IGNORECASE)


def _fixed_error(request: PitRequest, code: str, layer: str, label: str, reason: str, place: tuple[float, float] | None = None) -> DesignError:
    """``des.pit_fixed_invalid``: el banco fijado ``label`` de la capa ``layer`` no vale por ``reason`` (con su lugar si lo hay)."""
    return DesignError("des.pit_fixed_invalid", obj=f"Corta «{request.name}» de la capa «{request.layer}»", field=entity_key(code, PitParam.FIXED_LAYER),
                       value=label, layer=layer, entity=request.name, reason=reason, place="" if place is None else _place_text(*place))


def _fixed_benches(project: StoreProject, version: Version, request: PitRequest, code: str) -> tuple[FixedBench, ...]:
    """Los bancos fijados de la capa ``request.fixed`` (RF-018-23 y 24; ``()`` si no se pide): una **línea con Z** de una línea de rotura (``gis_brk_``) o de
    una capa propuesta (``des_rpl_``: una capa de entidades solo guarda X e Y), **cerrada** (su primer vértice se repite al final: se quita), de una sola
    parte, con la Z en cada vértice y sin vértice repetido. El banco es el número de su campo numérico (``fixed_field``; un entero, y en la descendente de 1
    o más) o, sin campo o sin valor, su cota (la Z de su primer vértice; el cálculo comprueba que sea la de un banco y la de cada vértice). **Solo lee**: la
    línea del usuario no se modifica (la copia es de solo lectura)."""
    if request.fixed is None:
        return ()
    name = request.fixed.layer
    if not name.startswith(_FIXED_PREFIXES):
        raise _fixed_error(request, code, name, name, "no es una línea de rotura (gis_brk_…), una capa propuesta (des_rpl_…) ni un banco expandido (des_pxb_…): una capa de entidades no guarda la Z")
    with project.read() as conn:
        record = dataset_registry.get(conn, name, version_uid=version.uid if name.startswith(_VERSION_PREFIXES) else "")
        if record is None:
            raise GisError("gis.dataset_unknown", obj="Dato de topografía", field="dato", value=name)
        lines = read_lines_3d(conn, record.locator)
    return fixed_of(lines, request, code)


def fixed_of(lines: Lines3D, request: PitRequest, code: str) -> tuple[FixedBench, ...]:
    """Los bancos fijados de la capa de líneas con Z ``lines`` ya leída (la del proyecto o la congelada; T24b): lo que hace :func:`_fixed_benches` con lo leído, con los mismos rechazos."""
    assert request.fixed is not None
    name = request.fixed.layer
    layer = lines.layer
    if not len(layer.fids):
        raise _fixed_error(request, code, name, name, "la capa no tiene ninguna línea")
    names = _names(layer, request, code, request.fixed.name_field)
    benches = _number_column(layer, request.fixed_field, request, code)
    found: list[FixedBench] = []
    for index, label in enumerate(names):
        stored = lines.xyz[index]
        if stored is None:
            raise _fixed_error(request, code, name, label, "tiene varias partes")
        if stored.ndim != 2 or stored.shape[1] < 3 or not bool(np.isfinite(stored[:, 2]).all()):
            raise _fixed_error(request, code, name, label, "no tiene la Z en cada vértice")
        points = np.array(stored[:, :3], dtype=np.float64)
        if len(points) < 2 or not bool((points[0, :2] == points[-1, :2]).all()):
            raise _fixed_error(request, code, name, label, "es una línea abierta: un banco es un anillo")
        ring = points[:-1]
        if len(ring) < 3:
            raise _fixed_error(request, code, name, label, "tiene menos de tres vértices")
        repeated = np.flatnonzero((ring[:, :2] == np.roll(ring[:, :2], -1, axis=0)).all(axis=1))
        if repeated.size:
            x, y = ring[int(repeated[0]), :2]
            raise _fixed_error(request, code, name, label, "tiene un vértice repetido", (float(x), float(y)))
        number = None if benches is None else benches[index]
        bench: int | None = None
        level: float | None = None
        if number is not None:
            if abs(number - round(number)) > 1e-9:
                raise _fixed_error(request, code, name, label, f"su banco «{request.fixed_field}» = {number:g} no es un número entero")
            bench = round(number)
            if request.mode is PitMode.DOWN and bench < 1:
                raise _fixed_error(request, code, name, label, f"su banco {bench} no es de una descendente: empieza en la cresta 1 (la 0 es el límite)")
        else:
            level = float(ring[0, 2])
        found.append(FixedBench(label, ring, bench=bench, level_m=level, closed=True))
    return tuple(found)


def _fixed_sha256(item: FixedBench) -> str:
    """El hash del contenido de un banco fijado (RF-018-01): sus vértices con la Z, su banco y su cota. Cambia con la geometría o con el banco; no con el
    nombre."""
    digest = hashlib.sha256()
    digest.update(np.ascontiguousarray(item.vertices, dtype=np.float64).tobytes())
    digest.update(np.float64(math.nan if item.level_m is None else item.level_m).tobytes())
    digest.update(np.int64(-(2 ** 62) if item.bench is None else item.bench).tobytes())
    return digest.hexdigest()


def sources_hashes(sources: Sequence[PitSource], fixed: Sequence[FixedBench]) -> dict[str, str]:
    """El hash de cada polígono de origen (por nombre) y de cada banco fijado (``fijado: nombre``): :attr:`PreparedPit.sources_sha256` (RF-018-01)."""
    hashes = {item.name: source_sha256(item.ring, item.level_m) for item in sources}
    hashes.update({f"fijado: {item.name}": _fixed_sha256(item) for item in fixed})
    return hashes


def _resolved_values(project: StoreProject, version: Version, keys: Sequence[str]) -> dict[str, Any]:
    """Los valores de ``keys`` como los resuelve una operación que empezara ahora (versión → proyecto → valor por defecto de su definición), clave → valor
    (``None`` si no hay). Sin escribir nada."""
    with project.read() as conn:
        found = ParameterStore(project).resolve_many(conn, keys, (VERSION_SCOPE, PROJECT_SCOPE), version=version.uid) if keys else {}
    values: dict[str, Any] = {}
    for key in keys:
        resolved = found.get(key)
        if resolved is not None:
            values[key] = None if resolved.value_json is None else json.loads(resolved.value_json)
        else:
            declared = definition(key)
            values[key] = None if declared is None else declared.default
    return values


def rose_numbers_of(keys: Sequence[str], rose_code: str) -> list[int]:
    """Los números de los rangos de la roseta ``rose_code`` que tienen alguna clave en ``keys`` (``des.rose.{r}.r{i}.…``), de menor a mayor."""
    prefix = f"des.rose.{rose_code}."
    return sorted({int(key[len(prefix):].split(".")[0][1:]) for key in keys if key.startswith(prefix) and key[len(prefix):].split(".")[0][1:].isdigit()})


class PitReader(Protocol):
    """Lo que la corta lee **además de sus capas y su superficie** (T24b): los valores resueltos de los parámetros, las rosetas, las rampas con su perfil de pista, las capas de puntos de inicio, los sectores
    de búsqueda y la geometría del perímetro y del límite legal. :class:`ProjectReader` lo lee del proyecto (al preparar); ``design.reproduce`` lo lee de lo **congelado** (sin proyecto), de modo que
    preparar y reproducir comparten el mismo código."""

    def values(self, keys: Sequence[str]) -> dict[str, Any]: ...

    def check_profiles(self, codes: Sequence[str]) -> None: ...

    def rose_names(self) -> dict[str, str]: ...

    def rose_numbers(self, rose_code: str) -> list[int]: ...

    def ramp_names(self) -> dict[str, str]: ...

    def road_profile(self, request: PitRequest, ramp: str, wanted: str) -> RoadProfile: ...

    def point_layer(self, name: str) -> FeatureLayer: ...

    def sectors(self) -> dict[str, Sector]: ...

    def limits(self) -> tuple[Parts | None, Parts | None]: ...


def limits_of_shapes(shapes: Mapping[str, tuple[ConstraintType, Sequence[Sequence[np.ndarray]]]]) -> tuple[Parts | None, Parts | None]:
    """El perímetro de actuación y el límite legal (RF-018-29: la línea de cielo mide la distancia a ellos; DIFF-018g) de los polígonos compilados ``shapes`` de las restricciones activas de la versión (código →
    tipo y partes: ``gis.masks.store.read_shapes``), como partes de polígonos absolutas, por su tipo y en su orden; ``None`` si no hay. Lo mismo lo leen la preparación (del proyecto) y la reproducción (de lo congelado)."""

    def parts_of(kind: ConstraintType) -> Parts | None:
        found = tuple(tuple(np.array(ring, dtype=np.float64) for ring in part) for ctype, parts in shapes.values() if ctype is kind for part in parts)
        return found or None

    return parts_of(ConstraintType.ACTION_PERIMETER), parts_of(ConstraintType.LEGAL_LIMIT)


@dataclass(frozen=True, slots=True)
class ProjectReader:
    """:class:`PitReader` del proyecto, en la versión ``version``: lo que lee una operación que empezara ahora."""

    project: StoreProject
    version: Version

    def values(self, keys: Sequence[str]) -> dict[str, Any]:
        return _resolved_values(self.project, self.version, keys)

    def check_profiles(self, codes: Sequence[str]) -> None:
        from .store import _check_profiles  # al usarlo: es de la 013

        _check_profiles(self.project, self.version, codes, tuple(BenchParam))

    def rose_names(self) -> dict[str, str]:
        with self.project.read() as conn:
            return {item.code: item.name for item in pit_rose.read_roses(conn)}

    def rose_numbers(self, rose_code: str) -> list[int]:
        with self.project.read() as conn:
            stored = [str(row[0]) for row in conn.execute("SELECT DISTINCT key FROM gb_parameter WHERE key LIKE 'des.rose.%'")]
        return rose_numbers_of(stored, rose_code)

    def ramp_names(self) -> dict[str, str]:
        with self.project.read() as conn:
            return {item.code: item.name for item in pit_ramp_def.read_ramps(conn)}

    def road_profile(self, request: PitRequest, ramp: str, wanted: str) -> RoadProfile:
        """El perfil de pista ``wanted`` (su código) que usa la rampa ``ramp``, con los valores que tiene en la versión (RF-017-07, RF-009-24): como ``design.road_store._profile``.
        ``des.road_profile_unknown`` si el proyecto no lo tiene; un valor que falta o está fuera de rango, el rechazo de la 017."""
        with self.project.read() as conn:
            stored = road_profiles.read_profiles(conn)
        road_profiles.check_names(stored)
        names = {item.code: item.name for item in stored}
        if wanted not in names:
            raise DesignError("des.road_profile_unknown", obj=f"Rampa «{ramp}» de la corta «{request.name}»", field=pitramp_key(ramp, PitRampParam.ROAD_PROFILE),
                              value=wanted, layer=request.layer, entity=ramp, profiles=", ".join(names.values()) or "—")
        keys = [road_profile_key(wanted, param) for param in RoadProfileParam]
        return road_profiles.road_profiles_from(self.values(keys), (wanted,), names)[wanted]

    def point_layer(self, name: str) -> FeatureLayer:
        return _layer(self.project, name)

    def sectors(self) -> dict[str, Sector]:
        with self.project.read() as conn:
            return {sector.code: sector for sector, _source in search_sectors(conn, self.project, self.version.uid)}

    def _shapes_record(self, conn: sqlite3.Connection) -> Any:
        return dataset_registry.get(conn, masks_declared.dataset_name(masks_declared.SHAPES), version_uid=self.version.uid)

    def limits(self) -> tuple[Parts | None, Parts | None]:
        """El perímetro de actuación y el límite legal de las restricciones activas de la versión (DIFF-018g: los **polígonos compilados** de las máscaras al día, :func:`limits_of_shapes`)."""
        with self.project.read() as conn:
            record = self._shapes_record(conn)
            shapes = {} if record is None else read_shapes(conn, record.locator)
        return limits_of_shapes(shapes)

    def limits_uid(self) -> str | None:
        """El uid del dato de los polígonos compilados de la versión (la entrada de papel :data:`~.provenance.PIT_LIMITS_ROLE`); ``None`` si no lo hay."""
        with self.project.read() as conn:
            record = self._shapes_record(conn)
        return None if record is None else str(record.uid)


def _rose(reader: PitReader, request: PitRequest, code: str, rose_code: str, field: str) -> tuple[RoseRange, ...]:
    """Los rangos de la roseta ``rose_code`` (su código) con los valores que tiene en la versión (RF-018-07, RF-009-24: los de la versión y, si no, los del
    proyecto), comprobados con :func:`design.pit_rose.check_rose` (un hueco, un solape, un valor que falta o fuera de rango se rechazan nombrando la roseta, la
    clave y el valor) y **en orden de azimut**. ``des.pit_rose_unknown`` si el proyecto no tiene esa roseta."""
    names = reader.rose_names()
    if rose_code not in names:
        raise DesignError("des.pit_rose_unknown", obj=f"Corta «{request.name}» de la capa «{request.layer}»", field=field, value=rose_code, layer=request.layer,
                          entity=request.name, roses=", ".join(names.values()) or "—")
    numbers = reader.rose_numbers(rose_code)
    keys = [rose_key(rose_code, f"r{number}", param) for number in numbers for param in RoseParam]
    values = reader.values(keys)
    ranges = [{param.value: values[rose_key(rose_code, f"r{number}", param)] for param in RoseParam} for number in numbers]
    return pit_rose.check_rose(names[rose_code], rose_code, ranges)


def _roses(reader: PitReader, request: PitRequest, code: str, sector_codes: Mapping[str, str]
           ) -> tuple[tuple[RoseRange, ...] | None, dict[str, tuple[RoseRange, ...]], dict[str, int]]:
    """La roseta base y la de cada sector (por el código del sector) de la petición, con los rangos de cada una (:func:`_rose`) y cuántos tiene cada roseta
    (para los parámetros que lee la operación). Una roseta que se repite se lee una vez."""
    cache: dict[str, tuple[RoseRange, ...]] = {}

    def read(rose_code: str, field: str) -> tuple[RoseRange, ...]:
        if rose_code not in cache:
            cache[rose_code] = _rose(reader, request, code, rose_code, field)
        return cache[rose_code]

    base = None if request.rose is None else read(request.rose, entity_key(code, PitParam.ROSE))
    by_sector = {sector_codes[segment]: read(rose_code, pit_sector_key(code, PitSectorParam.ROSE, segment)) for segment, rose_code in request.sector_roses}
    return base, by_sector, {rose_code: len(found) for rose_code, found in cache.items()}


def _ramp_start(reader: PitReader, request: PitRequest, code: str, ramp: RampDef, grid: Grid, layers: dict[str, FeatureLayer]) -> RampStart:
    """El punto de inicio de la rampa ``ramp`` (RF-018-15): ``fondo`` (el banco 0) o ``banco N`` (la rampa parte de la polilínea de ese banco: lo sitúa el
    cálculo) o ``capa:nombre``, el punto de ese nombre de una capa de puntos del proyecto, dentro de la rejilla. ``des.pit_start_invalid`` con la rampa, el
    texto y el motivo en cualquier otro caso."""
    text = ramp.start.strip()

    def refuse(reason: str) -> DesignError:
        return DesignError("des.pit_start_invalid", obj=f"Rampa «{ramp.name}» de la corta «{request.name}»", field=pitramp_key(ramp.code, PitRampParam.START),
                           value=text, layer=request.layer, entity=request.name, ramp=ramp.name, reason=reason)

    if text.casefold() == "fondo":
        return RampStart(ramp.code, bench=0)
    found = _BENCH_START.fullmatch(text)
    if found is not None:
        return RampStart(ramp.code, bench=int(found.group(1)))
    layer_name, colon, point_name = (part.strip() for part in text.partition(":"))
    if not colon or not layer_name or not point_name:
        raise refuse("no es «fondo», «banco N» ni «capa:nombre»")
    if layer_name not in layers:
        try:
            layers[layer_name] = reader.point_layer(layer_name)
        except (ValueError, GisError):
            raise refuse(f"«{layer_name}» no es una capa de entidades del proyecto") from None
    layer = layers[layer_name]
    if layer.kind != "point":
        raise refuse(f"la capa «{layer_name}» no es de puntos")
    names = _names(layer, request, code, None)
    where = [index for index, label in enumerate(names) if label == point_name]
    if not where:
        raise refuse(f"la capa «{layer_name}» no tiene ningún punto llamado «{point_name}»")
    if len(where) > 1:
        raise refuse(f"la capa «{layer_name}» tiene {len(where)} puntos llamados «{point_name}»")
    parts = layer.parts[where[0]]
    if len(parts) != 1:
        raise refuse("el punto tiene varias partes")
    x, y = (float(value) for value in np.asarray(parts[0][0], dtype=np.float64).reshape(-1)[:2])
    if not (grid.west <= x <= grid.west + grid.ncols * grid.dx and grid.north - grid.nrows * grid.dy <= y <= grid.north):
        raise refuse(f"el punto está fuera de la rejilla del proyecto (x = {x:.2f}, y = {y:.2f})")
    return RampStart(ramp.code, point=(x, y), layer=layer_name, name=point_name)


def _ramps(reader: PitReader, request: PitRequest, code: str, grid: Grid
           ) -> tuple[tuple[RampDef, ...], tuple[RoadProfile, ...], tuple[RampStart, ...], tuple[str, ...]]:
    """Las definiciones de rampa de la petición (``request.ramps``: sus códigos; RF-018-15), cada una con los valores que tiene en la versión comprobados con
    :func:`design.pit_ramp_def.check_ramp` (la pendiente de diseño no pasa de la máxima del perfil de pista que usa), los perfiles de pista que usan, su punto
    de inicio resuelto (:func:`_ramp_start`) y las capas de puntos que leyó. ``des.pit_ramp_unknown`` si el proyecto no tiene una."""
    if not request.ramps:
        return (), (), (), ()
    names = reader.ramp_names()
    for wanted in request.ramps:
        if wanted not in names:
            raise _reject("des.pit_ramp_unknown", request, code, PitParam.RAMPS, wanted, ramps=", ".join(names.values()) or "—")
    ramps: list[RampDef] = []
    profiles: dict[str, RoadProfile] = {}
    starts: list[RampStart] = []
    layers: dict[str, FeatureLayer] = {}
    for wanted in dict.fromkeys(request.ramps):
        resolved = reader.values([pitramp_key(wanted, param) for param in PitRampParam])
        values = {param.value: resolved[pitramp_key(wanted, param)] for param in PitRampParam}
        road = values.get(PitRampParam.ROAD_PROFILE.value)
        profile = reader.road_profile(request, names[wanted], road) if isinstance(road, str) and road else None
        ramp = pit_ramp_def.check_ramp(names[wanted], wanted, values, max_gradient_pct=1.0 if profile is None else profile.max_gradient_pct,
                                       road_profile_name="" if profile is None else profile.name)
        assert profile is not None
        profiles[profile.code] = profile
        ramps.append(ramp)
        starts.append(_ramp_start(reader, request, code, ramp, grid, layers))
    return tuple(ramps), tuple(profiles.values()), tuple(starts), tuple(layers)


# --- Los perfiles y los sectores -------------------------------------------------------------------------------------------


def _bench_values(reader: PitReader, codes: Sequence[str]) -> dict[str, object]:
    """Los cinco valores de cada perfil de ``codes`` como los resuelve una operación que empezara ahora (versión → proyecto → valor por defecto de su
    definición) o, al reproducir, como los congeló, clave ``des.bench.{p}.…`` → valor. Sin escribir nada."""
    return dict(reader.values(tuple(bench_key(item, param) for item in codes for param in BenchParam)))


def _profiles(reader: PitReader, request: PitRequest, code: str, sector_codes: Mapping[str, str]
              ) -> tuple[BenchProfile | None, dict[str, BenchProfile]]:
    """Los perfiles de banco de la corta (RF-018-06): el base y el de cada sector, con los valores comprobados (RF-013-19: uno que falta o está fuera de
    rango es ``des.profile_value_missing`` o ``_range``, nombrando el perfil, el campo y el valor) y **de la misma altura y ancla** (``des.pit_profiles_differ``
    con los dos y sus valores). ``sector_codes`` da el código de cada segmento de sector de la petición. Sin ninguno base, cada sector lleva el suyo."""
    assigned = [item for item in (request.profile, *(profile for _sector, profile in request.sector_profiles)) if item is not None]
    if not assigned:
        raise _reject("des.entity_param_missing", request, code, PitParam.PROFILE, None)
    codes = tuple(dict.fromkeys(assigned))
    reader.check_profiles(codes)
    built = pipeline.bench_profiles(_bench_values(reader, codes), codes)
    base = None if request.profile is None else built[request.profile]
    by_sector = {sector_codes[segment]: built[profile] for segment, profile in request.sector_profiles}
    ordered = [item for item in (base, *by_sector.values()) if item is not None]
    first = ordered[0]
    for other in ordered[1:]:
        if other.height_m != first.height_m or other.anchor_m != first.anchor_m:
            raise DesignError(PitCode.PROFILES_DIFFER.value, obj=f"Corta «{request.name}»", field=entity_key(code, PitParam.PROFILE), value=first.code,
                              name=request.name, profile=first.code, other=other.code,
                              other_value=f"h = {other.height_m} m, z₀ = {other.anchor_m} m") from None
    return base, by_sector


def _sector_codes(request: PitRequest, code: str, refs: Sequence[Any]) -> dict[str, str]:
    """El código de cada sector que la petición nombra por su segmento (``perimeter__`` es el perímetro, ``""``); ``des.sector_unknown`` si no es de los
    sectores del proyecto."""
    segments = {PERIMETER_SEGMENT if ref.code == "" else ref.code: ref.code for ref in refs}
    named = [*(sector for sector, _ in request.sector_profiles), *(sector for sector, _ in request.sector_roses),
             *(sector for sector, _ in request.sector_n_berm)]
    unknown = sorted({sector for sector in named if sector not in segments})
    if unknown:
        pipeline._unknown_sectors([(sector, "") for sector in unknown], list(refs))
    return {sector: segments[sector] for sector in dict.fromkeys(named)}


def _sectors(reader: PitReader, request: PitRequest, code: str, by_sector: Mapping[str, BenchProfile],
             sector_codes: Mapping[str, str], base: BenchProfile | None = None,
             by_rose: Mapping[str, tuple[RoseRange, ...]] | None = None) -> tuple[PitSector, ...]:
    """Los sectores de la corta con lo que les corresponde: los que la petición nombra (su perfil, su roseta o su número de bancos por berma, RF-018-06, 07
    y 08), con su geometría (los anillos de la 012). El número de bancos por berma de un sector que no es el de la corta se rechaza
    (``des.pit_sector_n_berm``); un sector sin perfil propio y una corta sin perfil base, también (``des.entity_param_missing``)."""
    by_rose = by_rose or {}
    base_n = 1 if request.n_berm is None else request.n_berm
    by_n = {sector_codes[segment]: value for segment, value in request.sector_n_berm}
    for segment, value in request.sector_n_berm:
        if value != base_n:
            raise DesignError("des.pit_sector_n_berm", obj=f"Corta «{request.name}»", field=pit_sector_key(code, PitSectorParam.N_BERM, segment),
                              value=value, entity=request.name, sector=segment, other=base_n)
    found = reader.sectors()
    items = []
    for sector_code in dict.fromkeys([*by_sector, *by_rose, *by_n]):
        sector = found[sector_code]
        if base is None and sector_code not in by_sector:
            raise _reject("des.entity_param_missing", request, code, PitParam.PROFILE, None)
        parts = tuple((np.array(ring, dtype=np.float64),) for ring in sector.rings)
        items.append(PitSector(sector_code, sector.name, parts, by_sector.get(sector_code), by_rose.get(sector_code), by_n.get(sector_code)))
    return tuple(items)


# --- Los parámetros -------------------------------------------------------------------------------------------------------


def pit_values(request: PitRequest, code: str, *, start_ref: str) -> dict[str, Any]:
    """Los parámetros resueltos y comprobados de la corta ``request`` de código ``code`` (RF-015-08, RF-018-04), por último segmento de su clave: lo que se
    pide (la petición no lleva ninguna cifra minera y **ninguna de las tolerancias del desfase tiene valor por defecto**: una que falta es
    ``des.entity_param_missing``; una fuera de su rango, ``des.entity_param_range``), el valor por defecto de ``corner`` y de ``n_berm`` y de lo que no
    se pide, nada. ``start_ref`` es lo que dice la partida (el nombre de un dato o ``entity:<código>``). En el modo **descendente**, al menos un criterio
    de parada (``des.pit_no_stop``). **Sin proyecto**: lo comparten preparar y reproducir. No lleva ``protect`` ni ``guard_m`` (la corta no declara)."""
    if not isinstance(request, PitRequest):
        raise TypeError(f"la corta se prepara con una PitRequest, no {request!r}")
    asked: dict[PitParam, object] = {
        PitParam.NAME: request.name, PitParam.MODE: request.mode.value, PitParam.LAYER: request.layer, PitParam.START: start_ref,
        PitParam.SUPPORT: request.support, PitParam.FIXED_LAYER: None if request.fixed is None else request.fixed.layer,
        PitParam.NORAMP_LAYER: None if request.noramp is None else request.noramp.layer, PitParam.PROFILE: request.profile,
        PitParam.ROSE: request.rose, PitParam.RAMPS: ", ".join(request.ramps) or None, PitParam.TOP_LEVEL: request.top_level_m,
        PitParam.BOTTOM_LEVEL: request.bottom_level_m, PitParam.MAX_BENCHES: request.max_benches,
        PitParam.MIN_FLOOR_WIDTH: request.min_floor_width_m, PitParam.ARC_TOL: request.arc_tol_m, PitParam.SIMPLIFY: request.simplify_m,
        PitParam.CLOSE_RADIUS: request.close_radius_m, PitParam.AZ_WINDOW: request.az_window_m,
        PitParam.CORNER: _default(PitParam.CORNER) if request.corner is None else str(request.corner),
        PitParam.N_BERM: _default(PitParam.N_BERM) if request.n_berm is None else request.n_berm}
    required = {PitParam.ARC_TOL: True, PitParam.SIMPLIFY: True}
    values: dict[str, Any] = {}
    for param in PitParam:
        if param not in asked:
            continue
        checked = check_entity_param(request.name, code, param.value, asked[param], layer=request.layer, required=required.get(param))
        if checked is not None:
            values[param.value] = checked
    if request.mode is PitMode.DOWN and not any(key in values for key in (PitParam.MIN_FLOOR_WIDTH.value, PitParam.BOTTOM_LEVEL.value,
                                                                           PitParam.MAX_BENCHES.value)):
        raise _reject("des.pit_no_stop", request, code, PitParam.MIN_FLOOR_WIDTH,
                      None, fields=", ".join(entity_key(code, item) for item in (PitParam.MIN_FLOOR_WIDTH, PitParam.BOTTOM_LEVEL, PitParam.MAX_BENCHES)))
    top, bottom = values.get(PitParam.TOP_LEVEL.value), values.get(PitParam.BOTTOM_LEVEL.value)
    if top is not None and bottom is not None and not bottom < top:
        raise _reject("des.entity_param_range", request, code, PitParam.BOTTOM_LEVEL, bottom, range=f"< {top} m (la cota de coronación)")
    return values


def _default(param: PitParam) -> Any:
    return entity_params("pit").template(param.value).default


def _rows(request: PitRequest, code: str, values: Mapping[str, Any], sector_rows: Sequence[tuple[str, PitSectorParam, str, object]]
          ) -> tuple[EntityParamRow, ...]:
    """Las filas de los parámetros de la entidad con su procedencia (RF-008-01): los valores por defecto (``corner``, ``n_berm``), con la de su
    definición, los valores por sector (``sector_rows``: segmento, parámetro y valor) y el resto, lo que eligió la persona en el diálogo."""
    name = request.name
    rows: list[EntityParamRow] = []
    defaults = {PitParam.CORNER: request.corner is None, PitParam.N_BERM: request.n_berm is None}
    for param in PitParam:
        value = values.get(param.value)
        if value is None:
            continue
        if defaults.get(param):
            declared = entity_params("pit").template(param.value)
            from ..core.params.store import default_reason

            source, kind, reason = declared.source, str(declared.source_kind), default_reason(declared)
        else:
            source, kind, reason = f"{_DIALOG}, entidad «{name}»", "person", f"Elegido al crear la corta «{name}»"
        rows.append(EntityParamRow(entity_key(code, param), param.value, value, source, kind, reason))
    for segment, param, value, _extra in sector_rows:
        rows.append(EntityParamRow(pit_sector_key(code, param, segment), f"{param.value}.{segment}", value,
                                   f"{_DIALOG}, entidad «{name}»", "person", f"Elegido al crear la corta «{name}», sector «{segment}»"))
    return tuple(rows)


# --- La ventana y las máscaras ---------------------------------------------------------------------------------------------


def _box(sources: Sequence[PitSource]) -> tuple[float, float, float, float]:
    """La caja ``(oeste, sur, este, norte)`` de los polígonos de origen (absolutas)."""
    stack = np.vstack([np.asarray(source.ring, dtype=np.float64) for source in sources])
    return float(stack[:, 0].min()), float(stack[:, 1].min()), float(stack[:, 0].max()), float(stack[:, 1].max())


def _reach_m(request: PitRequest, profile_list: Sequence[BenchProfile], sources: Sequence[PitSource], start: np.ndarray,
             roses: Sequence[RoseRange] = (), ramp_width_m: float = 0.0) -> float:
    """Lo más lejos que puede llegar la cresta de una corta ascendente (m), por exceso: los bancos que hacen falta para subir del fondo más bajo al
    terreno más alto, por el mayor avance de entre los perfiles y los rangos de las rosetas (``n·h/tan α + B``). Una cota de coronación acota los bancos. Con rampas, cada banco puede retranquearse además la anchura de la sección del mayor
    perfil de pista (``ramp_width_m``): el pie y la cresta se apartan de la banda (RF-018-16)."""
    ground_top = float(np.nanmax(start))
    lowest = min(item.level_m for item in sources if item.level_m is not None)
    top = ground_top if request.top_level_m is None else min(ground_top, request.top_level_m)
    n = 1 if request.n_berm is None else request.n_berm
    height = profile_list[0].height_m
    count = max(1, math.ceil((top - lowest) / (n * height)))
    advance = max([n * item.height_m / math.tan(math.radians(item.face_deg)) + item.berm_m for item in profile_list]
                  + [pit_rose.advance_m(height, item.face_deg, item.berm_m, n) for item in roses])
    return count * (advance + ramp_width_m)


def _ramp_width_m(road_profile_list: Sequence[RoadProfile]) -> float:
    """La mayor anchura de sección (m) de los perfiles de pista de las rampas de la corta (0 sin rampas)."""
    return max((road_profiles.derived(item).section_m for item in road_profile_list), default=0.0)


def _window(grid: Grid, box: tuple[float, float, float, float], reach_m: float) -> Window:
    """**A0**: la ventana de trabajo —filas y columnas de la rejilla— de la caja de lo que se toca, ensanchada ``reach_m`` y dos celdas más, recortada a la
    rejilla."""
    west, south, east, north = box
    col0 = math.floor((west - reach_m - grid.west) / grid.dx) - _WINDOW_MARGIN_CELLS
    col1 = math.ceil((east + reach_m - grid.west) / grid.dx) + _WINDOW_MARGIN_CELLS
    row0 = math.floor((grid.north - (north + reach_m)) / grid.dy) - _WINDOW_MARGIN_CELLS
    row1 = math.ceil((grid.north - (south - reach_m)) / grid.dy) + _WINDOW_MARGIN_CELLS
    return (slice(max(0, row0), min(grid.nrows, row1)), slice(max(0, col0), min(grid.ncols, col1)))


def _refuse_pending(project: StoreProject, version: Version, masks: access.MaskSet | access.MaskSource, grid: Grid, window: Window,
                    zone: np.ndarray) -> Generator[None, None, None]:
    """RF-018-05 y RF-015-07: ``des.sector_pending`` si un sector que toca la corta (``zone``: las celdas de la ventana que puede mover) no tiene la búsqueda
    de intocables vigente; nombra la orden «Buscar elementos intocables por sector…»."""
    sectors = design_sectors(project, version.uid)
    if any(item.pending for item in sectors):
        refs, labels = sector_layout(project, masks)
        touched = pipeline.touched_in(refs, labels[window], zone)
        refuse_pending(item for item in sectors if item.code in touched)
    yield


# --- Lo que la corta pisa: lo que declara la persona (T25; RF-015-15) ------------------------------------------------------


def _declared_supports(project: StoreProject, version: Version, registry: EntityRegistry, name: str, code: str, released: Collection[str]
                       ) -> tuple[tuple[tuple[str, Any], ...], bool]:
    """Las entidades en las que la persona **declara** que se apoya la corta ``code`` (``name``) en ``version`` (``des.pit.{e}.supports``: códigos separados por comas, RF-015-15), sin las que
    ``released`` da por buenas sin su apoyo (descartadas: ni se piden ni se rechazan), cada una con su superficie y la tabla de su huella (``entity_store.EntitySurface``), y si la corta tiene la fila
    (solo entonces la operación **lee** ese parámetro: ``begin_operation`` crearía una fila «sin confirmar» por cada corta que no declara nada, trampa de la T04). Una declarada que no existe, no está
    calculada, se descartó, es la propia corta o cierra un ciclo se rechaza (``des.entity_supports_unknown``). La corta no deriva dependencias de ningún origen: solo lee las declaradas. Solo lee."""
    record = ParameterStore(project).get(entity_key(code, PitParam.SUPPORTS), version=version.uid)
    row = None if record is None else ("" if record.value is None else str(record.value))
    found = tuple((target, _supportable(project, version, registry, name, code, target, entity_key(code, PitParam.SUPPORTS))[1])
                  for target in entity_store._declared(row) if target not in released)
    return found, record is not None


# --- Preparar -------------------------------------------------------------------------------------------------------------


def prepare_pit_units(project: StoreProject, request: PitRequest, version: Version, masks: access.MaskSet, *, code: str | None = None,
                      supersedes: str | None = None, released: Sequence[provenance.ReleasedSupport] = ()) -> Generator[None, None, PreparedPit]:
    """Las unidades (cada ``yield``, una; para componerlas con ``pace_units``) que preparan la corta ``request`` en la versión editable ``version`` con las
    máscaras al día ``masks`` (``store.masks_steps``; RF-015-06): el código y el nombre únicos (``code``: el de una entidad que ya está en su versión, que no
    choca consigo misma), la partida (``request.start``; en blanco, la última de la cadena) y la cadena, la capa de origen con sus rechazos (RF-018-04), los
    perfiles (RF-018-06), los parámetros (RF-015-08), la superficie de partida y su rejilla comparada con la del proyecto **antes de leer una celda**
    (``design.surfaces.read_surface_steps``), las zonas sin rampa, el corte y el relleno admitidos y lo intocable de las máscaras, **la búsqueda de
    intocables** de los sectores que toca la corta (RF-015-07), el hash de cada polígono de origen y la ventana de trabajo (A0). ``supersedes``: la
    operación hecha a la que sustituye (un recálculo). **Nada se escribe** (RF-015-03). Los rechazos salen al avanzar, antes de calcular y en este orden: la
    versión, el nombre y la cadena, la capa y sus polígonos, la partida, los perfiles, los parámetros y un sector pendiente.

    T21b: los **bancos fijados** (:func:`_fixed_benches`), la **roseta** del perfil base y de los sectores (:func:`_roses`) y las **rampas** con su perfil de
    pista y su punto de inicio (:func:`_ramps`) se leen y se rechazan aquí, antes de calcular: los fijados con la capa y la roseta y las rampas tras los
    parámetros.

    T25 (RF-015-15, RF-015-17): **lo que la persona declara** en ``supports`` (:func:`_declared_supports`) se lee y se comprueba (viva, calculada, ni ella ni un ciclo) y entra en las entradas con su
    superficie (``supported_on``) y la tabla de su huella; ``released``: las entidades descartadas que la corta da por buenas sin su apoyo (se suman a las que ya soltaba ``supersedes``): lo declarado
    en ellas no se pide ni se rechaza."""
    if masks.version_uid != version.uid:
        raise ValueError(f"las máscaras son de otra versión, no de {version.code}")
    chosen, registry = _identify(project, version, request, code)
    name = request.name
    start_ref = request.start.strip()
    if not start_ref:
        proposed = _default_start(registry)
        if proposed is None:
            raise _reject("des.entity_param_missing", request, chosen, PitParam.START, None)
        start_ref = proposed
    entity_store._check_chain_of(registry, name, start_ref, request.support, chosen)
    start_name = _start_dataset(registry, version, name, chosen, start_ref, PitParam.START)
    support_name = None if request.support is None else _start_dataset(registry, version, name, chosen, request.support, PitParam.SUPPORT)
    yield
    layer = _polygon_layer(project, request.layer, request, chosen, PitParam.LAYER)
    sources, _rings = _sources(layer, request, chosen)
    noramp = _noramp(project, request, chosen)
    fixed = _fixed_benches(project, version, request, chosen)
    yield
    frame = project_frame(project)
    grid = frame.grid
    surface = yield from read_surface_steps(project, start_name, version_uid=version.uid, expect=frame, role=_START_ROLE)
    start = surface.values
    if not grid.same_geometry(masks.grid):
        raise ValueError("la rejilla de las máscaras no es la del proyecto")
    _check_polygons(sources, request, chosen, grid, start)
    reader = ProjectReader(project, version)
    refs, _labels = sector_layout(project, masks)
    sector_codes = _sector_codes(request, chosen, refs)
    base, by_sector = _profiles(reader, request, chosen, sector_codes)
    profile_list = [item for item in (base, *by_sector.values()) if item is not None]
    values = pit_values(request, chosen, start_ref=start_ref)
    yield
    n_berm = int(values[PitParam.N_BERM.value])
    rose, rose_by_sector, rose_counts = _roses(reader, request, chosen, sector_codes)
    ramps, road_profile_list, ramp_starts, point_layers = _ramps(reader, request, chosen, grid)
    sectors = _sectors(reader, request, chosen, by_sector, sector_codes, base, rose_by_sector)
    if request.mode is PitMode.UP:
        _check_levels(sources, request, chosen, grid, start, profile_list[0], n_berm)
    params = PitParams.from_values(values)
    box = _box(sources)
    all_roses = [item for ranges in (rose or (), *rose_by_sector.values()) for item in ranges]
    reach = _reach_m(request, profile_list, sources, start, all_roses, _ramp_width_m(road_profile_list)) if request.mode is PitMode.UP else 0.0
    window = _window(grid, box, reach)
    zone = np.zeros(grid.shape, dtype=bool)
    if request.mode is PitMode.DOWN:
        zone[window] = polygons_cells([(np.asarray(source.ring, dtype=np.float64),) for source in sources], grid)[window]
    else:
        zone[window] = True
    yield from _refuse_pending(project, version, masks, grid, window, zone[window])
    cut, fill = admitted_pair(masks, (slice(0, grid.nrows), slice(0, grid.ncols)))
    untouchable = untouchable_cells(masks)
    perimeter, legal = reader.limits()
    asked = replace(request, start=start_ref)
    job = PitJob(asked, chosen, grid, start, cut, fill, untouchable, tuple(sources), params, base, sectors, rose, ramps, road_profile_list, fixed, noramp,
                 perimeter, legal, ramp_starts)
    sector_rows = [(segment, PitSectorParam.PROFILE, profile, None) for segment, profile in request.sector_profiles]
    sector_rows += [(segment, PitSectorParam.ROSE, rose_code, None) for segment, rose_code in request.sector_roses]
    sector_rows += [(segment, PitSectorParam.N_BERM, value, None) for segment, value in request.sector_n_berm]
    yield
    common = entity_store._common(project, version)
    declared, has_row = _declared_supports(project, version, registry, name, chosen, entity_store._released_codes(project, supersedes, released))
    supported = tuple(target for target, _found in declared)
    surfaces = tuple(dict.fromkeys(([] if support_name is None else [support_name]) + [found.surface for _target, found in declared]))
    named_sectors = bool(request.sector_profiles or request.sector_roses or request.sector_n_berm)
    inputs = provenance.pit_inputs(request.layer, start_name, masks.uses(), surfaces, fixed=None if request.fixed is None else request.fixed.layer,
                                   noramp=None if request.noramp is None else request.noramp.layer, points=point_layers,
                                   limits=reader.limits_uid() if perimeter is not None or legal is not None else None,
                                   sectors=constraint_store.SECTOR_TABLE if named_sectors and constraint_store.SECTOR_TABLE in available_tables(project, version.uid) else None)
    inputs = (*inputs, *(use for use in (Use(found.table, provenance.SUPPORT_FOOTPRINT_ROLE) for _target, found in declared) if use not in inputs))
    valued = [param.value for param in (PitParam.SUPPORT, PitParam.PROFILE, PitParam.TOP_LEVEL, PitParam.BOTTOM_LEVEL, PitParam.MAX_BENCHES,
                                        PitParam.MIN_FLOOR_WIDTH, PitParam.CLOSE_RADIUS, PitParam.AZ_WINDOW, PitParam.NORAMP_LAYER,
                                        PitParam.FIXED_LAYER, PitParam.ROSE, PitParam.RAMPS)
              if param.value in values]
    codes = tuple(item.code for item in profile_list)
    sector_keys = [pit_sector_key(chosen, param, segment) for segment, param, _value, _extra in sector_rows]
    begun = _start(project, provenance.PIT, name, version, masks, provenance.pit_settings(request, chosen, {item.code: item.name for item in ramps}), inputs,
                   provenance.pit_params(chosen, valued=valued, profiles=codes, sectors=sector_keys, supports=has_row, roses=rose_counts,
                                         ramps=[(item.code, item.type == "zigzag") for item in ramps], road_profiles=[item.code for item in road_profile_list]),
                   supersedes)
    begun = replace(begun, carry=False)
    yield
    hashes = sources_hashes(sources, fixed)
    return PreparedPit(job, begun, chosen, version, start_name, start_ref, support_name, request.layer, _rows(asked, chosen, values, sector_rows),
                       MappingProxyType(values), MappingProxyType(common), window, MappingProxyType(hashes), supported, (), code is not None)


def prepare_pit(project: StoreProject, request: PitRequest, *, version: str | None, masks: access.MaskSet | None = None, code: str | None = None,
                supersedes: str | None = None, released: Sequence[provenance.ReleasedSupport] = ()) -> PreparedPit:
    """La preparación entera de :func:`prepare_pit_units` de una vez (plan 018 §5.3.1; sin ceder el hilo): la :class:`PreparedPit`, con los mismos
    rechazos y sin escribir nada. ``version``: la versión activa (su uid o su código; ``VersionError`` ``core.version_required`` si no hay y
    ``core.version_not_editable`` si no se edita, RF-009-21); ``masks``: las de esa versión (al día; sin ellas se cargan, compilándolas antes si faltan)."""
    found = require_version(project, version, provenance.PIT)
    work = prepare_pit_units(project, request, found, _loaded_masks(project, found, masks), code=code, supersedes=supersedes, released=released)
    while True:
        try:
            next(work)
        except StopIteration as stop:
            result: PreparedPit = stop.value
            return result



def frozen_job(reader: PitReader, request: PitRequest, code: str, grid: Grid, start: np.ndarray, masks: access.MaskSet, *, layer: FeatureLayer,
               refs: Sequence[Any], noramp_layer: FeatureLayer | None = None, fixed_lines: Lines3D | None = None
               ) -> tuple[PitJob, Window, dict[str, str]]:
    """El :class:`~design.pit_model.PitJob` de la corta ``request`` (de código ``code``) con **lo congelado** (spec 018, T24b; RF-018-25, RF-009-11; DIFF-018g), sin proyecto: lo que hace
    :func:`prepare_pit_units` con lo ya leído —la capa de origen ``layer``, la de zonas sin rampa y las líneas de los bancos fijados, los sectores ``refs`` y las máscaras— y con el mismo código para los
    perfiles, las rosetas, las rampas, los sectores y los límites (``reader``: :class:`PitReader`). No repite las comprobaciones de la preparación (ya pasaron al crearla). Devuelve el job, su ventana de
    trabajo (A0) y el hash de cada polígono de origen y de cada banco fijado (:func:`sources_hashes`)."""
    sources, _rings = _sources(layer, request, code)
    noramp = None if noramp_layer is None else noramp_parts(noramp_layer)
    fixed = () if fixed_lines is None else fixed_of(fixed_lines, request, code)
    sector_codes = _sector_codes(request, code, refs)
    base, by_sector = _profiles(reader, request, code, sector_codes)
    profile_list = [item for item in (base, *by_sector.values()) if item is not None]
    values = pit_values(request, code, start_ref=request.start)
    rose, rose_by_sector, _counts = _roses(reader, request, code, sector_codes)
    ramps, road_profile_list, ramp_starts, _point_layers = _ramps(reader, request, code, grid)
    sectors = _sectors(reader, request, code, by_sector, sector_codes, base, rose_by_sector)
    all_roses = [item for ranges in (rose or (), *rose_by_sector.values()) for item in ranges]
    reach = _reach_m(request, profile_list, sources, start, all_roses, _ramp_width_m(road_profile_list)) if request.mode is PitMode.UP else 0.0
    window = _window(grid, _box(sources), reach)
    cut, fill = admitted_pair(masks, (slice(0, grid.nrows), slice(0, grid.ncols)))
    perimeter, legal = reader.limits()
    job = PitJob(request, code, grid, start, cut, fill, untouchable_cells(masks), tuple(sources), PitParams.from_values(values), base, sectors, rose, ramps, road_profile_list, fixed, noramp,
                 perimeter, legal, ramp_starts)
    return job, window, sources_hashes(sources, fixed)


# --- Calcular (T22) --------------------------------------------------------------------------------------------------------

OFFSET_NOT_VERIFIED = "des.pit_offset_not_verified"
"""El código con que se rechaza un cálculo cuyo desfase no se pudo verificar (RF-018-10): ``PitCode.OFFSET_UNRELIABLE`` es su aviso."""
_COMPUTE_PHASE = "pit_compute"


def confirm_ramps(ramps: Sequence[Any], confirmed: Sequence[provenance.RampConfirmation] = ()
                  ) -> tuple[tuple[provenance.RampConfirmation, ...], tuple[tuple[str, float, float], ...]]:
    """Las pendientes medias de las rampas ``ramps`` (:class:`~design.pit_ramp.RampChecked`) frente a lo ya confirmado (``confirmed``; RF-018-19, RF-017-17):
    las confirmaciones que cubren una media que pasa de pm y las que **faltan**, cada una ``(código de la rampa, media %, pm %)``. No rechaza: «Crear» (T23)
    exige que no falte ninguna, con :func:`~design.pit_ramp.confirm_mean`."""
    covering: list[provenance.RampConfirmation] = []
    pending: list[tuple[str, float, float]] = []
    for checked in ramps:
        if not checked.mean_exceeded:
            continue
        found = None
        for item in confirmed:
            if item.ramp != checked.code:
                continue
            try:
                found = pit_ramp.confirm_mean(checked, item)
            except DesignError:
                continue
            break
        if found is not None:
            covering.append(found)
        else:
            pending.append((checked.code, float(checked.mean_gradient_pct), float(checked.profile.max_mean_gradient_pct)))
    return tuple(covering), tuple(pending)


def _reject_unreliable(job: PitJob, found: Any) -> None:
    """RF-018-10: un desfase que no se pudo verificar **rechaza** el cálculo, con el banco y el defecto del primero y sin relajar nada."""
    if found.reliable:
        return
    first = next((item for item in found.notices if item.code == PitCode.OFFSET_UNRELIABLE.value), None)
    values = {} if first is None else dict(first.values)
    raise DesignError(OFFSET_NOT_VERIFIED, obj=f"Corta «{job.request.name}»", field=PitParam.ARC_TOL.value, value=values.get("value"),
                      name=job.request.name, bench=values.get("bench"), limit=values.get("limit"))


def compute_steps(job: PitJob, window: Window, common: Mapping[str, float], *, crs: Any, vertical: Any,
                  confirmed: Sequence[provenance.RampConfirmation] = (), budget_s: float = STEP_BUDGET_S) -> Generator[Progress, None, PitOutcome]:
    """**A5 a A13** (T22; RF-018-03, 25, 26, 31, 35; RNF-018-06): el cálculo entero de la corta ``job``, por pasos de ``budget_s`` como mucho y **sin escribir
    nada**: los bancos (ascendente o descendente, con sus rampas), **el rechazo de un desfase no verificado** (``des.pit_offset_not_verified``), la superficie,
    la línea de cielo (con las distancias al límite legal y al perímetro de ``job``), los hallazgos, las cifras y el contraste con la 013. Devuelve el
    :class:`~design.pit_model.PitOutcome` (``window``: la ventana de trabajo, que debe contener todo el movimiento; ``common``: los parámetros del proyecto
    de la preparación, de los que se lee la tolerancia de cara; ``crs`` y ``vertical``: los del proyecto). ``outcome.extra`` lleva el contraste
    (``contrast``), la superficie (``surface``: :class:`~design.pit_surface.PitSurface`), la línea de cielo (``sky``), las rampas comprobadas (``checked_ramps``),
    las pendientes medias confirmadas (``mean_confirmed``) y las que faltan por confirmar (``mean_pending``; no rechazan el cálculo: las pide «Crear»).
    Cerrar el generador a mitad no deja nada. Los rechazos (``DesignError``) salen al avanzar."""
    try:
        face_tolerance = float(common[provenance.TOLERANCE_FACE])
    except KeyError as error:
        raise ValueError(f"falta la tolerancia de cara del proyecto ({provenance.TOLERANCE_FACE}) en los parámetros comunes") from error
    way = pit_bench.ascend_steps if job.mode is PitMode.UP else pit_bench.descend_steps
    yield Progress(_COMPUTE_PHASE, 0, 6, "Calculando los bancos…")
    benches = yield from pipeline.forward(way(job, budget_s=budget_s))
    _reject_unreliable(job, benches)
    ramps = tuple(benches.ramps)
    yield Progress(_COMPUTE_PHASE, 1, 6, "Calculando la superficie de la corta…")
    surface = yield from pipeline.forward(pit_surface.rasterize_steps(job, benches, ramps, crs=crs, vertical=vertical, budget_s=budget_s))
    rows, cols = window
    outside = surface.cut_cells.copy()
    outside[rows, cols] = False
    if bool(outside.any()):
        raise ValueError("la ventana de trabajo no contiene todo el movimiento de la corta (error del programa)")
    yield Progress(_COMPUTE_PHASE, 2, 6, "Calculando la línea de cielo…")
    sky = pit_sky.skyline(job.start, surface.stepped, job.grid, crs=crs, vertical=vertical, legal=job.legal, perimeter=job.perimeter)
    yield Progress(_COMPUTE_PHASE, 3, 6, "Buscando los hallazgos…")
    found = yield from pipeline.forward(pace_progress(
        pit_report.findings_units(job, benches.polylines, surface, face_tolerance_deg=face_tolerance, ramps=ramps, floor_width_m=benches.floor_width_m),
        budget_s, phase=_COMPUTE_PHASE, running="Buscando los hallazgos…", finished="Hallazgos calculados"))
    yield Progress(_COMPUTE_PHASE, 4, 6, "Calculando las cifras…")
    figures = pit_report.figures(job, benches.polylines, surface, crs=crs, vertical=vertical, skyline=sky, ramps=ramps, found=found)
    yield Progress(_COMPUTE_PHASE, 5, 6, "Contrastando con la 013…")
    contrast = yield from pipeline.forward(pit_check013.contrast_steps(job, surface, budget_s=budget_s))
    covering, pending = confirm_ramps(ramps, confirmed)
    extra = MappingProxyType({
        "contrast": contrast, "surface": surface, "sky": sky, "checked_ramps": ramps, "mean_confirmed": covering, "mean_pending": pending,
        "face_volume_m3": benches.face_volume_m3, "floor": (benches.floor_level_m, benches.floor_area_m2, benches.floor_width_m)})
    return PitOutcome(
        job.request.name, job.code, job.mode, window, surface.surface[rows, cols], surface.cut_cells[rows, cols], figures.specs,
        (*benches.notices, *contrast.notices), benches.polylines, tuple(item.path for item in ramps), tuple(part.xyz for part in sky.parts),
        figures.benches, found, benches.stop, (), extra)


def compute(job: PitJob, window: Window, common: Mapping[str, float], *, crs: Any, vertical: Any,
            confirmed: Sequence[provenance.RampConfirmation] = ()) -> PitOutcome:
    """:func:`compute_steps` hasta el final, sin ceder el hilo: el :class:`~design.pit_model.PitOutcome`. Los mismos rechazos."""
    work = compute_steps(job, window, common, crs=crs, vertical=vertical, confirmed=confirmed)
    while True:
        try:
            next(work)
        except StopIteration as done:
            result: PitOutcome = done.value
            return result


# --- El resumen, lo que quedará obsoleto y los otros diseños (T22b) ----------------------------------------------------------------------

OTHER_DESIGN_DIFFERS = "des.pit_other_design_differs"
"""El aviso de un otro diseño de la versión cuya superficie difiere de la partida en la huella de la corta (RF-017-05 (b) llevado a la corta): no impide crearla."""
_OTHERS_PHASE = "pit_others"
OTHERS_SEEN = "others_seen"
"""La clave de ``PitOutcome.extra`` con el hash (uid → hash) que tenía la superficie de cada otro diseño que difiere cuando se comparó: lo que «Crear» anota con la entrada."""


def other_designs_steps(job: PitJob, outcome: PitOutcome, names: Sequence[str], read_other: OtherReader, min_thickness_m: float
                        ) -> Generator[Progress, None, tuple[tuple[str, ...], tuple[Notice, ...]]]:
    """Compara la partida de ``job`` con la superficie de cada otro diseño de ``names`` **en la huella de la corta** (``outcome.footprint``, en su ventana de trabajo) y devuelve
    (valor de ``StopIteration``) los nombres de los que difieren en más de ``min_thickness_m`` (lo que «Crear», T23, registrará como entradas) y un aviso por cada uno
    (:data:`OTHER_DESIGN_DIFFERS`, que no impide crearla). ``read_other(nombre, ventana)`` lee la superficie de **un** diseño **en la ventana** (de una en una: no se carga la
    rejilla entera); cede un ``Progress`` por diseño. ``ValueError`` si una superficie no es de la forma de la ventana (error del programa)."""
    window = outcome.window
    here = job.start[window]
    sub = _window_grid(job.grid, window)
    differing: list[str] = []
    found: list[Notice] = []
    for index, other in enumerate(names):
        values = np.asarray(read_other(other, window), dtype=np.float64)
        if values.shape != here.shape:
            raise ValueError(f"la superficie de «{other}» es de la forma {values.shape} y la ventana de trabajo de la corta, {here.shape}")
        differs = other_design_notices(outcome.name, sub, outcome.footprint, here, {other: values}, min_thickness_m, code=OTHER_DESIGN_DIFFERS)
        if differs:
            differing.append(other)
            found.extend(differs)
        yield Progress(_OTHERS_PHASE, index + 1, len(names), f"Comparada la partida de «{outcome.name}» con «{other}»")
    return tuple(differing), tuple(found)


def _without_dependents(project: StoreProject, version: Version, names: Sequence[str], own: str) -> tuple[str, ...]:
    """Los ``names`` de otros diseños sin los que **dependen de lo que dejó la corta que se recalcula** (``own``: la operación que sustituye; T25; RF-015-16, RF-018-03): los que la consumen por cualquier
    entrada —su partida, **lo que declaran en ``supports``** o la propia corta como otro diseño—, directamente o en cascada. Anotarlos como entrada la haría depender de lo que depende de ella (un
    bucle que no se asienta: con otra corta que declara apoyarse en ella, cada recálculo dejaría obsoletas a las dos). Solo lee."""
    with project.read() as conn:
        written = [str(row[0]) for row in conn.execute("SELECT item_uid FROM gb_operation_io WHERE operation_uid = ? AND direction = 'out' AND item_kind = 'dataset'", (own,))]
        later = {uid for uid, _type, _name in entity_store._dependents(conn, written, version.uid, exclude=(own,))}
        kept = []
        for name in names:
            record = dataset_registry.get(conn, name, version_uid=version.uid)
            if record is None or record.operation_uid not in later:
                kept.append(name)
    return tuple(kept)


def compare_others(project: StoreProject, prepared: PreparedPit, outcome: PitOutcome, *, supersedes: str | None = None
                   ) -> Generator[Progress, None, PitOutcome]:
    """Los otros diseños de la versión de ``prepared`` (:func:`~design.road_store.other_designs`: los que no tienen a la partida como ancestro; ``supersedes``: la operación que se
    recalcula, que no cuenta) frente a su partida en la huella (:func:`other_designs_steps`, con el espesor mínimo de ``prepared.common``): devuelve ``outcome`` con ``other_designs`` y,
    tras sus avisos, el de cada uno que difiere. **Solo lee.** Sin otros diseños, el mismo ``outcome``."""
    names = other_designs(project, prepared.version, prepared.start_surface, own=supersedes)
    if supersedes is not None and names:
        names = _without_dependents(project, prepared.version, names, supersedes)
    if not names:
        return outcome
    thickness = _thickness(_project_number(prepared.common, VERIFY_MIN_THICKNESS))
    differing, notices = yield from other_designs_steps(prepared.job, outcome, names, other_reader(project, prepared.version), thickness)
    if not differing:
        return outcome
    with project.read() as conn:  # el hash de cada uno al calcular: «Crear» lo anota como entrada y ``des.input_changed`` vigila que no cambie hasta crearla (T23)
        seen = _seen(conn, tuple(Use(other, provenance.ROAD_OTHER_DESIGN_ROLE) for other in differing), prepared.version)
    return replace(outcome, other_designs=differing, notices=(*outcome.notices, *notices), extra={**outcome.extra, OTHERS_SEEN: dict(seen)})


def pit_obsolete(project: StoreProject, prepared: PreparedPit, *, supersedes: str | None = None) -> tuple[Obsolete, ...]:
    """**Lo que quedará obsoleto al crear** la corta ``prepared`` (RF-015-03, RF-015-16): una corta nueva no deja nada obsoleto (lo que se apoye después en ella sale de su vigencia,
    no de su creación); la que **sustituye** una operación (``supersedes``: un recálculo) deja obsoleto lo que dependía de lo que escribió, en cascada (``DEPENDENT``). Solo lee."""
    if supersedes is None:
        return ()
    with project.read() as conn:
        written = [str(row[0]) for row in conn.execute(
            "SELECT item_uid FROM gb_operation_io WHERE operation_uid = ? AND direction = 'out' AND item_kind = 'dataset' ORDER BY fid", (supersedes,))]
        found = entity_store._dependents(conn, written, prepared.version.uid, exclude=(supersedes,))
    return tuple(entity_store._consumer(ObsoleteKind.DEPENDENT, uid, op_type, name) for uid, op_type, name in found)


def summary_of(outcome: PitOutcome, *, version: str, profile: str, obsolete: Sequence[Obsolete] = ()) -> PitSummary:
    """El resumen de «Calcular» la corta de ``outcome`` (RF-015-03, RF-018-03, RF-018-19; **puro**: sin proyecto) como :class:`~design.preview.PitSummary`: las cifras que se
    registrarán, los bancos, el corte, el área, los hallazgos, las rampas con las **medias por encima de pm sin confirmar** (``outcome.extra["mean_pending"]``) y los avisos en
    el orden en que se enseñan: los del cálculo y, al final, lo que quedará obsoleto (``obsolete``) con su causa. ``version``: el código de la versión; ``profile``: el del perfil base."""
    found = {figure.key: figure.value for figure in outcome.figures}
    pending = tuple((str(code), float(mean), float(limit)) for code, mean, limit in outcome.extra.get("mean_pending", ()))
    kept = tuple(obsolete)
    benches = found.get("des.pit_benches")
    return PitSummary(
        outcome.name, outcome.code, version, str(PitMode(outcome.mode).value), profile, outcome.figures, 0 if benches is None else int(benches), found.get("des.pit_cut_m3"),
        found.get("des.pit_area_m2"), len(outcome.findings), tuple(item.code for item in outcome.ramps), pending, bool(pending),
        (*outcome.notices, *obsolete_notices(outcome.name, version, kept)), kept)


def pit_summary(project: StoreProject, prepared: PreparedPit, outcome: PitOutcome, *, supersedes: str | None = None) -> PitSummary:
    """El resumen de «Calcular» la corta ``prepared`` (:func:`summary_of` con lo que quedará obsoleto al crearla: :func:`pit_obsolete`; ``supersedes``: la operación que sustituye).
    **Solo lee.**"""
    job = prepared.job
    profile = "" if job.profile is None else job.profile.code
    return summary_of(outcome, version=prepared.version.code, profile=profile, obsolete=pit_obsolete(project, prepared, supersedes=supersedes))


# --- Crear: la operación, los datos, la huella y las dependencias (spec 018, T23; RF-018-01, RF-018-03, RF-018-19, RF-015-01, RF-015-02, RF-015-04, RF-015-10 a 14, RF-015-29; plan 018 §5.2.3 y §5.3.2) -------------

Row = tuple[Any, ...]


def _sources_digest(sources_sha256: Mapping[str, str]) -> str:
    """El hash único de la huella de origen de la corta (RF-018-01): el de los hashes de cada polígono (:attr:`PreparedPit.sources_sha256`) por orden de nombre. Cambia con la geometría o la cota
    de cualquier polígono y no con su orden de llegada."""
    digest = hashlib.sha256()
    for name in sorted(sources_sha256):
        digest.update(f"{name}\0{sources_sha256[name]}\n".encode())
    return digest.hexdigest()


def pit_entity_rows(job: PitJob, outcome: PitOutcome, *, fid: int, start_surface: str, support_surface: str | None, sources_sha256: Mapping[str, str]) -> list[Row]:
    """La fila de ``des_epr_`` (columnas de :data:`~.store.ENTITY_COLUMNS`) de la corta de ``job`` con su ``outcome`` (RF-015-01, RF-018-01): **una**, con los atributos de la entidad —su código, su nombre, su tipo
    ``pit``, los datos de su superficie de partida (``start_surface``) y de apoyo, la capa de origen, el ``fid`` (``fid``: 0, una capa trae varios polígonos), el hash de sus geometrías de origen (:func:`_sources_digest`),
    el modo y las celdas de la huella—, su ventana de trabajo y **la huella** (el área con movimiento) en tramos de fila (``entity_store.footprint_runs``: lo que leen la zona declarada de otra entidad, la capa de
    entidades y lo que se apoya en la corta). Sin eje. Solo depende de lo que se lee para calcular, no del proyecto."""
    window = outcome.window
    runs = entity_store.footprint_runs(outcome.footprint, window)
    json_of = entity_store._json
    return [(job.code, job.request.name, EntityKind.PIT.value, start_surface, support_surface, job.request.layer, int(fid), _sources_digest(sources_sha256), PitMode(outcome.mode).value,
             int(np.count_nonzero(outcome.footprint)), 0, json_of([int(window[0].start), int(window[0].stop), int(window[1].start), int(window[1].stop)]), json_of([list(run) for run in runs]),
             json_of([]))]


def pit_polyline_rows(outcome: PitOutcome) -> list[LineRow]:
    """Las filas de ``des_pbl_`` (:data:`~.pit_lines.POLYLINE_COLUMNS`) del resultado: **una por polilínea, en el orden registrado** (RF-018-25) con sus vértices (x, y absolutas y la cota en la Z, float64), su banco,
    tipo, zona, sector y parte, si es un anillo o una línea fijada, su cota y su longitud."""
    return [LineRow(line.vertices, (line.bench, line.kind.value, line.zone, line.sector, line.part, ordinal, int(line.closed), int(line.fixed), _real("z_m", line.z_m), _real("length_m", line.length_m)),
                    line.closed) for ordinal, line in enumerate(outcome.polylines, start=1)]


def pit_skyline_rows(outcome: PitOutcome) -> list[LineRow]:
    """Las filas de ``des_psk_`` (:data:`~.pit_lines.SKYLINE_COLUMNS`) del resultado: una por línea de la línea de cielo (RF-018-28), con la cota del terreno en la Z, su número y su longitud en planta."""
    return [LineRow(line, (part, _real("length_m", float(np.hypot(*np.diff(line[:, :2], axis=0).T).sum())))) for part, line in enumerate(outcome.skyline, start=1)]


def pit_ramp_rows(outcome: PitOutcome) -> list[Row]:
    """Las filas de ``des_prl_`` (:data:`~.store.PIT_RAMP_COLUMNS`; RF-018-16): una por estación del eje de cada rampa, en el orden de las rampas, con su lugar absoluto, la cota y el semiancho de la banda."""
    rows: list[Row] = []
    for path in outcome.ramps:
        for at, ((x, y, z), half) in enumerate(zip(path.axis.tolist(), path.half_width_m.tolist(), strict=True), start=1):
            rows.append((path.code, path.bench, at, _real("x", x), _real("y", y), _real("level_m", z), _real("half_width_m", half)))
    return rows


def pit_finding_rows(outcome: PitOutcome) -> list[Row]:
    """Las filas de ``des_pfn_`` (:data:`~.store.PIT_FINDING_COLUMNS`; RF-018-26): una por hallazgo, en el orden del cálculo."""
    return [(item.kind.value, item.bench, None if item.value is None else _real("value", item.value), None if item.limit is None else _real("limit", item.limit), item.unit,
             _real("x", item.place[0]), _real("y", item.place[1]), item.detail) for item in outcome.findings]


def pit_bench_rows(outcome: PitOutcome) -> list[Row]:
    """Las filas de ``des_pbk_`` (:data:`~.store.PIT_BENCH_COLUMNS`; RF-018-29, RF-018-31): una por banco, con sus cotas, longitudes, áreas de berma y de fondo (vacías donde no las tiene) y el volumen que se corta."""
    return [(item.bench, item.z_foot_m, item.z_crest_m, item.len_foot_m, item.len_crest_m, item.area_berm_m2, item.area_floor_m2, item.cut_m3) for item in outcome.benches]


def pit_report_rows(outcome: PitOutcome) -> list[Row]:
    """Las filas de ``des_prp_`` (formato largo ``quantity, value, unit_code, note``; RF-018-31, RF-015-02) del resultado, en este orden: **las cifras** (su clave sin ``des.pit_``, su valor y su unidad), el criterio
    que paró la corta (``stop``) y **los avisos y notas** (``warning`` y ``note``, con su código y sus valores en JSON) **menos los de** ``entity_store._OUTSIDE_NOTICES`` (dependen de algo que la operación no
    consume: el informe se reproduce sin el proyecto). Un valor que no es finito es un error del programa (``ValueError``). Solo depende del resultado."""
    from .road_store import _notice_text

    rows: list[Row] = []
    for figure in outcome.figures:
        rows.append((figure.key.removeprefix("des.pit_"), None if figure.value is None else _real(figure.key, figure.value), figure.unit, None))
    if outcome.stop is not None:
        rows.append(("stop", None, None, str(getattr(outcome.stop, "value", outcome.stop))))
    for notice in outcome.notices:
        if notice.code not in entity_store._OUTSIDE_NOTICES:
            rows.append((notice.severity, None, None, _notice_text(notice)))
    return rows


def pit_operation_start(start: OperationStart, outcome: PitOutcome, confirmed: Sequence[provenance.RampConfirmation]) -> OperationStart:
    """Lo que anota la operación de la corta al crearla, además de lo que preparó (``start``: :func:`prepare_pit_units`): **los otros diseños de la versión que difieren en la huella**
    (``outcome.other_designs``, RF-017-05 (b) llevado a la corta) como entradas con el papel :data:`~.provenance.ROAD_OTHER_DESIGN_ROLE` —con el hash que tenían al compararlos
    (:data:`OTHERS_SEEN`; si cambia hasta crearla, ``des.input_changed``)—, de modo que **si cambian, la corta queda obsoleta con su causa**; y **lo confirmado** (``confirmed``: las pendientes medias de rampa
    por encima de pm, con su motivo, quién y cuándo: RF-018-19) en sus ajustes, bajo :data:`~.provenance.PIT_RAMP_CONFIRMED`. Una ``OperationStart`` es inmutable: da otra. **La corta no declara nada**
    (RF-015-12): ni ``protect`` ni una declaración."""
    found = start
    role = provenance.ROAD_OTHER_DESIGN_ROLE
    have = {(use.item, str(use.role)) for use in start.inputs}
    extra = tuple(Use(name, role) for name in outcome.other_designs if (name, role) not in have)
    if extra:
        found = replace(found, inputs=(*found.inputs, *extra), seen=MappingProxyType({**found.seen, **dict(outcome.extra.get(OTHERS_SEEN, {}))}))
    if confirmed:
        found = replace(found, settings={**found.settings, provenance.PIT_RAMP_CONFIRMED: [item.settings() for item in confirmed]})
    return found


def _check_confirmed(outcome: PitOutcome, confirmed: Sequence[provenance.RampConfirmation]) -> tuple[provenance.RampConfirmation, ...]:
    """Las confirmaciones que cubren una media por encima de pm; **si falta alguna, ``des.pit_ramp_mean_over``** (``pit_ramp.confirm_mean``) antes de escribir nada (RF-018-19)."""
    covering, pending = confirm_ramps(outcome.extra.get("checked_ramps", ()), confirmed)
    if pending:
        wanted = {code for code, _mean, _limit in pending}
        for checked in outcome.extra["checked_ramps"]:
            if checked.code in wanted:
                pit_ramp.confirm_mean(checked)
    return covering


def create_pit_steps(project: StoreProject, writer: DesignWriter, prepared: PreparedPit, outcome: PitOutcome, *, confirmed: Sequence[provenance.RampConfirmation] = (),
                     decided_by: str | None = None, budget_s: float = STEP_BUDGET_S) -> Generator[Progress, None, Stored]:
    """**«Crear» una corta** por pasos (spec 018, T23; RF-018-01, RF-018-03, RF-018-19, RF-015-01, RF-015-02, RF-015-04, RF-015-15, RF-015-29; RNF-018-06): prepara cada salida en su temporal —**la superficie entera**
    (la de partida con la ventana de trabajo sustituida por el resultado, ``PitOutcome.compose``; comprimida), la huella de la entidad (``des_epr_``, :func:`pit_entity_rows`), las polilíneas y la línea de cielo
    con Z (``des_pbl_`` y ``des_psk_``), las rampas por estaciones (``des_prl_``), los hallazgos (``des_pfn_``), las cifras de cada banco (``des_pbk_``) y el informe (``des_prp_``)—, cada una montada y escrita por
    pasos de ``budget_s`` como mucho, y las registra en **una** transacción (:meth:`~.store.DesignWriter.commit` de ``writer``, el de «Calcular»): **los parámetros de la entidad** (todas sus filas, con su origen
    y el decisor ``decided_by``), la operación (:func:`pit_operation_start`: sus entradas —la capa de origen, la de bancos fijados y la de zonas sin rampa, la partida, las máscaras, **lo que pisa** (``supported_on``)
    y los otros diseños que difieren— y sus ajustes, con lo confirmado), los datos, las cifras con el ámbito de la entidad y las que el gancho de las dependencias mide (``des.supported_m3``) y el mensaje.
    **No se crea sin la confirmación expresa** de la pendiente media de rampa por encima de pm (``confirmed``, :func:`_check_confirmed`), **antes de tocar nada**. Si algo falla, o lo que consume cambió
    desde que se calculó (``des.input_changed``), no queda nada y el error sigue; **no modifica la capa de origen ni la superficie de partida y no declara ninguna restricción** (RF-015-12: la zona de la corta se
    excava, no se protege). Cerrar el generador antes de que termine borra los temporales. Con un escritor reanudado (``DesignWriter.resume``: un recálculo, T24) la operación ya empezó y ``commit`` la completa."""
    if not isinstance(outcome, PitOutcome):
        raise TypeError(f"se crea la corta de un PitOutcome, no {outcome!r}")
    covering = _check_confirmed(outcome, confirmed)
    job = prepared.job
    name = job.request.name
    yield Progress(_STORE_PHASE, 0, 1, f"Guardando la corta «{name}»…")

    def grid_units() -> Generator[None, None, Any]:
        whole = outcome.compose(job.start)
        yield
        return (yield from writer.grid_steps(provenance.ENTITY_SURFACE_GRID, Raster(job.grid, whole, writer.crs, writer.vertical)))

    yield from pipeline.forward(_store_steps(grid_units(), budget_s, "la superficie de la corta"))
    tables: tuple[tuple[str, Callable[[], list[Row]], str], ...] = (
        (provenance.ENTITY_TABLE, lambda: pit_entity_rows(job, outcome, fid=0, start_surface=prepared.start_surface, support_surface=prepared.support_surface,
                                                          sources_sha256=prepared.sources_sha256), "la huella de la corta"),
        (provenance.PIT_RAMPS_TABLE, lambda: pit_ramp_rows(outcome), "las rampas de la corta"),
        (provenance.PIT_FINDINGS_TABLE, lambda: pit_finding_rows(outcome), "los hallazgos de la corta"),
        (provenance.PIT_BENCHES_TABLE, lambda: pit_bench_rows(outcome), "las cifras de cada banco"),
        (provenance.ENTITY_REPORT_TABLE, lambda: pit_report_rows(outcome), "el informe de la corta"))
    lines: tuple[tuple[str, Callable[[], list[LineRow]], str], ...] = (
        (provenance.PIT_POLYLINES_TABLE, lambda: pit_polyline_rows(outcome), "las polilíneas de la corta"),
        (provenance.PIT_SKYLINE_TABLE, lambda: pit_skyline_rows(outcome), "la línea de cielo de la corta"))
    for family, make, what in tables:
        yield from pipeline.forward(_store_steps(writer.table_steps(family, make()), budget_s, what))
    for family, make_lines, what in lines:
        yield from pipeline.forward(_store_steps(writer.pit_lines_steps(family, make_lines()), budget_s, what))
    handle = writer.handle  # un recálculo: la operación empezó antes de calcular y sus ajustes ya llevan lo confirmado
    start = None if handle is not None else pit_operation_start(prepared.start, outcome, covering)
    seen = MappingProxyType(dict(outcome.extra.get(OTHERS_SEEN, {})))
    late = _LateSupports() if handle is None else _LateSupports(tuple(Use(other, provenance.ROAD_OTHER_DESIGN_ROLE) for other in outcome.other_designs), seen)
    yield Progress(_STORE_PHASE, 1, 1, f"Registrando la corta «{name}»…")

    def parameters(conn: sqlite3.Connection) -> None:
        if prepared.existing:
            if ParameterStore(project).get(entity_key(prepared.code, PitParam.NAME), version=prepared.version_uid, conn=conn) is None:
                raise ValueError(f"la entidad {prepared.code} no tiene sus parámetros en su versión: no está en ella (se prepara sin su código)")
        else:
            entity_store.set_entity_params(project, prepared.rows, version=prepared.version_uid, decided_by=decided_by, conn=conn)
            ensure_name_row(project, prepared.code, conn=conn)  # T24: la fila del proyecto del nombre, que pide «Cambiar parámetro…»
        if handle is not None:
            late.register(conn, handle)

    return writer.commit(start, figures=outcome.figures, message=outcome.message, before_begin=parameters)


def create_pit(project: StoreProject, writer: DesignWriter, prepared: PreparedPit, outcome: PitOutcome, *, confirmed: Sequence[provenance.RampConfirmation] = (),
               decided_by: str | None = None) -> Stored:
    """:func:`create_pit_steps` de una vez (sin ceder el hilo): lo guardado (:class:`~.store.Stored`), con los mismos rechazos y la misma transacción."""
    work = create_pit_steps(project, writer, prepared, outcome, confirmed=confirmed, decided_by=decided_by)
    while True:
        try:
            next(work)
        except StopIteration as stop:
            result: Stored = stop.value
            return result


# --- Recalcular, la petición de una traída y el nombre (T24) -----------------------------------------------------------------------------


def pit_parameters(project: StoreProject, version: Version, code: str) -> dict[str, Any]:
    """Los parámetros vigentes de la corta ``code`` en ``version`` (:func:`~.entity_store.entity_parameters`: versión → proyecto) **y sus valores por sector**
    (spec 018, T24; ADR-0029; RF-018-06 a 09), por último segmento de su clave: los de sector, como ``profile.talud_norte``. Es la definición de la entidad (RF-015-01)
    con la que se recalcula y se calcula una traída. Solo lee."""
    values = entity_store.entity_parameters(project, code, version=version)
    prefix = entity_key(code, PitParam.NAME)[:-len("name")]
    names = {item.value for item in PitSectorParam}
    with project.read() as conn:
        found = sorted({str(row[0]) for row in conn.execute("SELECT key FROM gb_parameter WHERE key LIKE ? AND scope_uid IN ('', ?)", (prefix + "%", version.uid))})
    keys = {key: key[len(prefix):] for key in found
            if key.startswith(prefix) and key[len(prefix):].count(".") == 1 and key[len(prefix):].partition(".")[0] in names}
    with project.read() as conn:
        resolved = ParameterStore(project).resolve_many(conn, tuple(keys), (VERSION_SCOPE, PROJECT_SCOPE), version=version.uid) if keys else {}
    for key, short in keys.items():
        item = resolved.get(key)
        if item is not None and item.value is not None:
            values[short] = item.value
    return values


DEFAULT_LEVEL_FIELD = "cota_m"
"""El campo de la cota del fondo de una corta ascendente traída (decisión por defecto de la T24, revisable): ni el campo de la cota ni el de los nombres son parámetros de la entidad y una
traída no los trae; el de la cota es el que nombra la spec (``cota_m``) y, si la capa no lo tiene, el cálculo lo dice."""


def entity_pit_request(project: StoreProject, version: Version | str, code: str) -> PitRequest:
    """**La petición de una corta sin calcular** de la versión editable ``version`` (spec 018, T24; RF-015-18, RF-018-01, RF-015-04): la que dejan «Traer las entidades de…» y la versión
    que parte de otra, con sus parámetros y **ningún resultado**: lo que ya tiene la versión (:func:`pit_parameters`) con :func:`~.provenance.pit_request`, la misma que repite el recálculo.
    **El campo de los nombres de las capas** no es un parámetro y una corta traída no lo trae (el de la cota, en la ascendente, es :data:`DEFAULT_LEVEL_FIELD`). Es lo que se da a :func:`~.steps.pit_run` con ``code=`` para calcularla: con su
    **código**, sin crear otra entidad. Solo lee. Rechazos: los de ``require_version``, ``des.entity_already_discarded``, ``des.entity_calculate_done`` y ``des.entity_calculate_missing``
    (sin capa, modo o partida); ``ValueError`` si la versión no tiene la entidad o no es una corta."""
    found = require_version(project, version.uid if isinstance(version, Version) else version, provenance.PIT)
    entry = entities.registry(project, found.uid).get(code)
    if entry is None:
        raise ValueError(f"la versión {found.code} no tiene ninguna entidad con el código o el nombre {code!r}")
    record = entry.record
    if record.kind is not EntityKind.PIT:
        raise ValueError(f"{record.code} no es el código de una corta, sino de una entidad de tipo {record.kind}")
    obj = entity_store._entity_object(record.code, record.name)
    if record.state is EntityState.DISCARDED:
        raise DesignError("des.entity_already_discarded", obj=obj, field="estado", value=str(record.state), entity=record.name, version=found.code)
    if record.state is not EntityState.UNCALCULATED:
        raise DesignError("des.entity_calculate_done", obj=obj, field="estado", value=str(record.state), entity=record.name, code=record.code, version=found.code)
    values = pit_parameters(project, found, record.code)
    for param in (PitParam.LAYER, PitParam.MODE, PitParam.START):
        text = values.get(param.value)
        if not isinstance(text, str) or not text.strip():
            raise DesignError("des.entity_calculate_missing", obj=obj, field=entity_key(record.code, param), value=None, entity=record.name, code=record.code, version=found.code)
    level = DEFAULT_LEVEL_FIELD if values.get(PitParam.MODE.value) == PitMode.UP.value else None
    return provenance.pit_request({"name": record.name, "code": record.code, "fields": {"name_field": None, "level_field": level}}, values)


def ensure_name_row(project: StoreProject, code: str, *, conn: sqlite3.Connection) -> Any:
    """La fila **del proyecto** del nombre de la corta ``code`` (``des.pit.{e}.name``), que la crea «sin confirmar» y sin valor si no estaba (spec 018, T24; RF-015-08): «Cambiar
    parámetro…» pide la fila del proyecto del parámetro antes de cambiar la de la versión y la operación de la corta **no lee su nombre**, así que sin esto una corta no se podía renombrar.
    Escribe en la transacción ``conn``. ``ValueError`` si ``code`` no es el de una corta."""
    from .params import parse_entity_key
    parsed = parse_entity_key(entity_key(code, PitParam.NAME))
    if parsed is None or parsed[1] != EntityKind.PIT.value:
        raise ValueError(f"{code!r} no es el código de una corta")
    return ParameterStore(project).ensure_default(conn, entity_key(code, PitParam.NAME), geoblender_version=project.session.geoblender_version)


def _check_recorded(handle: OperationHandle, prepared: PreparedPit) -> None:
    """Los parámetros que anotó la operación al empezar son los que leyó el cálculo al prepararse (RF-013-17, D-14): los de la entidad y los del proyecto; si uno cambió entre las dos
    cosas, el resultado ya no le corresponde (``des.input_changed``, con el parámetro)."""
    read: dict[str, object] = {entity_key(prepared.code, PitParam(name)): value for name, value in prepared.values.items()}
    read.update(prepared.common)
    for param in handle.params:
        if param.key in read and param.value != read[param.key]:
            raise DesignError("des.input_changed", obj=f"Parámetro «{param.key}»", field="parámetros", value=param.key)


def run_pit(project: StoreProject, request: PitRequest, *, version: str | None, code: str, masks: access.MaskSet | None = None, supersedes: str | None = None,
            confirmed: Sequence[provenance.RampConfirmation] = (), released: Sequence[provenance.ReleasedSupport] = (), budget_s: float = STEP_BUDGET_S
            ) -> tuple[OperationHandle, Any]:
    """Calcula y registra ``request`` —la corta de la entidad ``code``, que ya está en su versión— de **una vez**, sin pedir confirmación a la persona (spec 018, T24; RF-018-01,
    RF-015-02, RF-015-16; el recálculo de lo obsoleto, :func:`~.store.recompute_run`): prepara (:func:`prepare_pit`), empieza la operación ``des.pit`` **antes de calcular** —sustituye a
    ``supersedes``— con lo que lee hoy y devuelve su ``OperationHandle`` «en curso» y sus pasos, que avanza quien la llama: calculan (:func:`compute_steps` con los otros diseños
    de la versión), escriben y completan la operación en una transacción (:func:`create_pit_steps` con el escritor reanudado; no escribe los parámetros, que ya están). El último paso lleva
    lo guardado (:class:`~.store.Stored`). **Un recálculo no confirma por la persona**: ``confirmed`` (lo confirmado al crear la que sustituye) se arrastra a la operación nueva y, si la
    media nueva pasa de ello, ``des.pit_ramp_mean_over`` al avanzar, antes de escribir. ``released`` (T25; RF-015-17, A7, P-6: **apoyo retirado**; :func:`~.entity_store.release_support`): la operación nueva **no lleva** las entradas de esas entidades descartadas (ni su superficie ni la tabla de su huella), anota el motivo y el decisor en sus ajustes (``supports_released``, acumulados con los de la que sustituye) y el gancho de las dependencias no vuelve a registrarlas; su superficie, su huella y sus datos no cambian."""
    prepared = prepare_pit(project, request, version=version, masks=masks, code=code, supersedes=supersedes, released=released)
    start = prepared.start
    if confirmed:
        start = replace(start, settings={**start.settings, provenance.PIT_RAMP_CONFIRMED: [item.settings() for item in confirmed]})
    handle = start.with_released(released).begin(project)
    return handle, _pit_run(project, handle, prepared, tuple(confirmed), supersedes, budget_s)


def _pit_run(project: StoreProject, handle: OperationHandle, prepared: PreparedPit, confirmed: tuple[provenance.RampConfirmation, ...], supersedes: str | None,
             budget_s: float) -> Generator[Progress, None, None]:
    frame = project_frame(project)
    with DesignWriter.resume(project, handle) as writer:
        _check_recorded(handle, prepared)
        outcome: PitOutcome = yield from compute_steps(prepared.job, prepared.window, prepared.common, crs=frame.crs, vertical=frame.vertical, confirmed=confirmed, budget_s=budget_s)
        outcome = yield from compare_others(project, prepared, outcome, supersedes=supersedes)
        stored: Stored = yield from create_pit_steps(project, writer, prepared, outcome, confirmed=confirmed, budget_s=budget_s)
        yield Progress(_STORE_PHASE, 1, 1, outcome.message, result=stored)


def recompute_pit(request: RecomputeRequest, *, budget_s: float = STEP_BUDGET_S, released: Sequence[provenance.ReleasedSupport] = ()
                  ) -> tuple[OperationHandle, Any]:
    """Repite la operación ``des.pit`` de ``request`` (:func:`~.store.recompute_run`; «Recalcular lo obsoleto», RF-008-26; spec 018, T24; RF-018-01, RF-015-02, RF-015-16): la corta de sus
    ajustes (el nombre, el código y los campos de las capas) con los **parámetros vigentes de su entidad en su versión** (:func:`pit_parameters`, con los de sector) y no los que leyó la
    operación que sustituye. La capa de origen (su geometría), la partida, los perfiles, las rosetas, las rampas, las máscaras y los otros diseños son entradas o parámetros de la operación:
    cambiar uno la deja obsoleta **entera** con su causa y recalcular la repite con lo nuevo. Devuelve lo de :func:`run_pit`, con lo que la persona confirmó al crearla. ``TypeError`` si la
    petición no es una ``RecomputeRequest``; ``ValueError`` si no es de ``des.pit``."""
    if not isinstance(request, RecomputeRequest):
        raise TypeError(f"se recalcula una RecomputeRequest, no {request!r}")
    if request.op_type != provenance.PIT:
        raise ValueError(f"recompute_pit repite {provenance.PIT}, no «{request.op_type}»")
    project: StoreProject = request.project  # type: ignore[assignment]
    code = provenance.supported_code(request.settings)
    found = require_version(project, request.version, provenance.PIT)
    asked = provenance.pit_request(request.settings, pit_parameters(project, found, code))
    return run_pit(project, asked, version=found.uid, code=code, supersedes=request.operation_uid, confirmed=provenance.ramp_confirmed(request.settings), released=released,
                   budget_s=budget_s)
