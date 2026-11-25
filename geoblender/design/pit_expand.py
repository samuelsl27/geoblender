# SPDX-License-Identifier: GPL-3.0-or-later
"""«Expandir banco…» de la corta por bancos: un paso del motor y la capa propuesta editable (spec 018, T28; HU-018-2; RF-018-22, RF-018-23, RF-015-02, RF-009-11; plan 018 §5.2.3 «des.pit_expand»,
§5.4 A7, §5.7 P-12; el patrón de «Proponer el trazado» de la 017, ``design.road_store``).

``des.pit_expand`` toma **una polilínea** —una línea con Z de una capa del proyecto (una línea de rotura ``gis_brk_``, la capa propuesta de la 017 ``des_rpl_`` o un banco expandido ``des_pxb_``) o una
polilínea de una corta calculada (``des_pbl_<nombre>``: por su banco, su tipo y su parte)—, un perfil (con su roseta y sus sectores si los hay) y un sentido (arriba o abajo), y da **el banco siguiente**
(:func:`~.pit_bench.expand_one_steps`: el mismo desfase del bucle, un solo paso) con su comprobación de inclinación o de berma (RF-018-26) **sin escribir nada**. Al confirmar, deja **la capa
``des_pxb_<nombre>_<vNN>``** —líneas con Z, una tabla de proyecto normal, **editable a mano en QGIS desde que se crea** (P-12)— registrada como salida de la operación, con las dos cifras de longitud y la partida, las
máscaras y el perfil como entradas. La capa vale como **banco fijado** de una corta (RF-018-23: ``des_pxb_`` es una de las capas de líneas con Z que acepta ``design.pit_store``) y su cambio se detecta como el de
cualquier capa (su hash es una entrada). Repetir la operación **no sobrescribe lo que se dibujó** en QGIS (``des.pit_expand_layer_edited``). No escribe ninguna superficie ni ningún parámetro de entidad:
no es una entidad.

Decisiones (revisables): la cifra de longitud es la de las líneas del paso tal cual (sin recortar por el terreno, a diferencia de la de una corta, P-14); el número de banco de una línea de capa sin banco es 1 (solo es
una etiqueta); el paso usa el perfil, la roseta y los sectores que pide la petición, no los de la corta de la que salga la línea. Python puro (nivel 8).
"""

from __future__ import annotations

from collections.abc import Generator, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

import numpy as np

from ..core.datasets import registry as dataset_registry
from ..core.project.model import Progress
from ..core.provenance.figures import FigureSpec
from ..core.provenance.operations import OperationHandle, Use
from ..core.provenance.recompute import RecomputeRequest
from ..core.versions.model import Version
from ..gis.grid import Grid
from ..gis.masks import access
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.messages import GisError
from ..gis.store import StoreProject
from . import entities, entity_store, pipeline, pit_bench, pit_store, provenance
from .compose import admitted_pair
from .messages import DesignError
from .params import PitParam, RoseParam, rose_key
from .pit_bench import Expansion
from .pit_layer import ExpandedRow
from .pit_model import PitJob, PitMode, PitParams, PitRequest, PitSource, Polyline, PolylineKind
from .preview import Notice
from .road_model import LayerFields
from .road_store import Lines3D, read_lines_3d, untouchable_cells
from .seeds import sector_layout
from .store import _STORE_PHASE, DesignWriter, OperationStart, Stored, _loaded_masks, _start, _store_steps, require_version
from .surfaces import project_frame, read_surface_steps

__all__ = [
    "EXPAND_CODE",
    "ExpandOutcome",
    "ExpandRequest",
    "ExpandSummary",
    "PreparedExpand",
    "create_expand",
    "create_expand_steps",
    "expand_compute_steps",
    "expand_job",
    "expand_layer_rows",
    "expand_params",
    "expand_request",
    "expand_settings",
    "expand_summary",
    "prepare_expand",
    "prepare_expand_units",
    "recompute_expand",
    "run_expand",
    "source_polyline",
]

EXPAND_CODE = "PIT-000"
"""El código de corta con el que una expansión nombra el campo de sus rechazos (``des.pit.pit_000.…``): **no es el de una entidad** (las cortas empiezan en ``PIT-001``): es la ficha de campos de la corta de la
que toma sus rechazos."""
_PHASE = "pit_expand"
_SOURCE_PREFIXES = tuple(provenance.FAMILIES_BY_CODE[code].prefix for code in (provenance.PIT_POLYLINES_TABLE, provenance.PIT_EXPANDED_TABLE, provenance.ROUTE_LAYER_TABLE))
_BREAKLINE_PREFIX = pit_store._LINES_3D_PREFIXES[0]
_LEVEL_TOL_M = pit_bench._LEVEL_TOL_M
_PAIRS = ("sector_profiles", "sector_roses", "sector_n_berm")
_NUMBERS = ("arc_tol_m", "simplify_m", "az_window_m")


@dataclass(frozen=True, slots=True)
class ExpandRequest:
    """Lo que pide el usuario de «Expandir banco…» (RF-018-22): el ``name`` de la operación (único en la versión: da el nombre de la capa ``des_pxb_<nombre>``), la capa de partida (``source``: el nombre de
    su dato con el campo de los nombres de sus líneas), el sentido (``mode``: ``up`` o ``down``) y la superficie de la que parte (``start``; en blanco, la última de la cadena si es una sola).

    La **línea** se elige con ``feature`` (el número de fila o el nombre) o, si la capa tiene las columnas ``bench`` y ``kind`` (``des_pbl_`` y ``des_pxb_``), con ``bench``, ``kind`` y ``part``. ``kind``
    (``foot`` o ``crest``) es lo que **es** la línea si la capa no lo dice; ``bench``, su número si no lo dice (por defecto 1). El perfil (``profile``), la roseta, los bancos por berma, los de los sectores y
    las tolerancias del desfase son los de ``PitRequest``, con los mismos rechazos (RF-015-08): sin valor por defecto salvo ``n_berm`` y ``corner``."""

    name: str
    source: LayerFields
    mode: PitMode | str
    start: str = ""
    kind: PolylineKind | str | None = None
    feature: str | None = None
    bench: int | None = None
    part: int = 0
    profile: str | None = None
    rose: str | None = None
    n_berm: int | None = None
    sector_profiles: Mapping[str, str] | tuple[tuple[str, str], ...] = ()
    sector_roses: Mapping[str, str] | tuple[tuple[str, str], ...] = ()
    sector_n_berm: Mapping[str, int] | tuple[tuple[str, int], ...] = ()
    corner: str | None = None
    arc_tol_m: float | None = None
    simplify_m: float | None = None
    az_window_m: float | None = None

    def __post_init__(self) -> None:
        pit = self.as_pit()  # valida el nombre, la capa, el modo y lo demás con las reglas de la corta
        object.__setattr__(self, "mode", pit.mode)
        object.__setattr__(self, "start", pit.start)
        object.__setattr__(self, "name", pit.name)
        for attr in _PAIRS:
            object.__setattr__(self, attr, getattr(pit, attr))
        if self.kind is not None:
            object.__setattr__(self, "kind", PolylineKind(self.kind))
        if self.feature is not None:
            object.__setattr__(self, "feature", str(self.feature).strip() or None)
        if self.bench is not None and (isinstance(self.bench, bool) or not isinstance(self.bench, int)):
            raise TypeError(f"el banco es un número entero, no {self.bench!r}")
        if isinstance(self.part, bool) or not isinstance(self.part, int) or self.part < 0:
            raise ValueError(f"la parte es un número entero de 0 o más, no {self.part!r}")

    def as_pit(self) -> PitRequest:
        """La :class:`~.pit_model.PitRequest` con que se leen el perfil, la roseta y los parámetros (la capa de partida es la de la línea)."""
        return PitRequest(
            name=self.name, fields=self.source, mode=self.mode, start=self.start, profile=self.profile, rose=self.rose, n_berm=self.n_berm,
            sector_profiles=self.sector_profiles, sector_roses=self.sector_roses, sector_n_berm=self.sector_n_berm, corner=self.corner,
            arc_tol_m=self.arc_tol_m, simplify_m=self.simplify_m, az_window_m=self.az_window_m)

    @property
    def layer(self) -> str:
        """La capa de partida."""
        return self.source.layer


def expand_settings(request: ExpandRequest) -> dict[str, Any]:
    """Los ajustes de ``des.pit_expand`` (JSON sin rutas): **toda la petición** (no es una entidad: no tiene parámetros de entidad; lo que lee como parámetros es el perfil y la roseta, :func:`expand_params`)."""
    if not isinstance(request, ExpandRequest):
        raise TypeError(f"los ajustes de una expansión salen de una ExpandRequest, no {request!r}")
    found: dict[str, Any] = {
        "name": request.name, "layer": request.source.layer, "name_field": request.source.name_field, "mode": str(request.mode), "start": request.start,
        "kind": None if request.kind is None else str(request.kind), "feature": request.feature, "bench": request.bench, "part": request.part, "profile": request.profile,
        "rose": request.rose, "n_berm": request.n_berm, "corner": request.corner}
    found.update({key: getattr(request, key) for key in _NUMBERS})
    found.update({key: [list(pair) for pair in getattr(request, key)] for key in _PAIRS})
    return found


def expand_request(settings: Mapping[str, Any]) -> ExpandRequest:
    """La petición que repiten los ajustes ``settings`` (los de :func:`expand_settings`): al recalcular y al reproducir. ``ValueError`` si no son los de una expansión."""
    what = "los ajustes de una expansión de banco"
    if not isinstance(settings, Mapping):
        raise ValueError(f"{what} son un diccionario, no {settings!r}")
    for key in ("name", "layer", "mode"):
        if not isinstance(settings.get(key), str) or not str(settings.get(key)).strip():
            raise ValueError(f"{what} llevan «{key}» (un texto), no {settings.get(key)!r}")
    pairs = {key: tuple((str(a), b) for a, b in settings.get(key) or ()) for key in _PAIRS}
    return ExpandRequest(
        name=settings["name"], source=LayerFields(settings["layer"], settings.get("name_field")), mode=settings["mode"], start=str(settings.get("start") or ""),
        kind=settings.get("kind"), feature=settings.get("feature"), bench=settings.get("bench"), part=int(settings.get("part") or 0), profile=settings.get("profile"),
        rose=settings.get("rose"), n_berm=settings.get("n_berm"), corner=settings.get("corner"), **{key: settings.get(key) for key in _NUMBERS}, **pairs)


def expand_params(profiles: Sequence[str], roses: Mapping[str, int]) -> tuple[str, ...]:
    """Los parámetros que lee ``des.pit_expand`` (``begin_operation(params=…)``): los cinco valores de cada perfil de banco (``profiles``) y los cuatro de cada rango de cada roseta que usa (``roses``: código →
    número de rangos). **Ninguno de entidad**: no lo es. Cambiar uno la deja obsoleta con su causa."""
    coded = [rose_key(rose, f"r{number}", item) for rose, count in roses.items() for number in range(1, count + 1) for item in RoseParam]
    return tuple(dict.fromkeys([*provenance.profile_params(profiles), *coded]))


# --- La línea de partida -------------------------------------------------------------------------------------------------


def _bad(request: ExpandRequest, label: str, reason: str) -> DesignError:
    return DesignError("des.pit_expand_source", obj=f"Expansión «{request.name}» de la capa «{request.layer}»", field="línea", value=label, layer=request.layer, entity=request.name, reason=reason)


def _values(lines: Lines3D, column: str) -> tuple[Any, ...] | None:
    for item in lines.layer.columns:
        if item.column == column or item.field == column:
            return tuple(lines.layer.values[item.column])
    return None


def source_polyline(lines: Lines3D, request: ExpandRequest) -> Polyline:
    """La polilínea de partida de ``request`` en la capa de líneas con Z ``lines`` (leída del proyecto o congelada; **solo lee**: la línea del usuario no se modifica): la que elige ``feature`` (número de fila o
    nombre) o, sin ella, la de ``bench``, ``kind`` y ``part`` de una capa con esas columnas. Ha de ser **un anillo cerrado de una sola parte, plano y con la Z en cada vértice**, sin vértices repetidos
    (``des.pit_expand_source``, nombrando la capa, la expansión, la línea y el motivo). Devuelve la :class:`~.pit_model.Polyline` (sin repetir el primer vértice)."""
    layer = lines.layer
    banks, kinds, parts, sectors = (_values(lines, key) for key in ("bench", "kind", "part", "sector"))
    label = request.feature if request.feature is not None else f"banco {request.bench} {request.kind}"
    if not len(layer.fids):
        raise _bad(request, label, "la capa no tiene ninguna línea")
    if request.feature is not None:
        names = pit_store._names(layer, request.as_pit(), EXPAND_CODE, request.source.name_field)
        found = [index for index, (name, fid) in enumerate(zip(names, layer.fids, strict=True)) if request.feature in (name, str(fid))]
    else:
        if banks is None or kinds is None or request.bench is None or request.kind is None:
            raise _bad(request, label, "indique la línea por su número o su nombre (la capa no tiene banco y tipo)")
        found = [index for index in range(len(layer.fids))
                 if banks[index] == request.bench and kinds[index] == str(request.kind) and (parts is None or parts[index] == request.part)]
    if not found:
        raise _bad(request, label, "no hay ninguna línea así en la capa")
    if len(found) > 1:
        raise _bad(request, label, f"hay {len(found)} líneas así en la capa: indique una por su número")
    index = found[0]
    stored = lines.xyz[index]
    if stored is None:
        raise _bad(request, label, "tiene varias partes")
    if stored.ndim != 2 or stored.shape[1] < 3 or not bool(np.isfinite(stored[:, 2]).all()):
        raise _bad(request, label, "no tiene la Z en cada vértice")
    points = np.array(stored[:, :3], dtype=np.float64)
    if len(points) < 4 or not bool((points[0, :2] == points[-1, :2]).all()):
        raise _bad(request, label, "es una línea abierta o de menos de tres vértices: un banco es un anillo")
    ring = points[:-1]
    if bool((ring[:, :2] == np.roll(ring[:, :2], -1, axis=0)).all(axis=1).any()):
        raise _bad(request, label, "tiene un vértice repetido")
    if float(np.ptp(ring[:, 2])) > _LEVEL_TOL_M:
        raise _bad(request, label, "no es plana (un banco tiene una sola cota)")
    if kinds is not None:
        if kinds[index] not in ("foot", "crest"):
            raise _bad(request, label, "no es un pie ni una cresta")
        kind = PolylineKind(kinds[index])
    elif request.kind is not None:
        kind = request.kind
    else:
        raise _bad(request, label, "indique si es un pie o una cresta")
    bench = int(banks[index]) if banks is not None else (1 if request.bench is None else request.bench)
    return Polyline(kind, bench, ring, sector="" if sectors is None else str(sectors[index] or ""), part=0 if parts is None else int(parts[index]))


@dataclass(frozen=True, slots=True)
class SourceLine:
    """Una línea de la capa de partida de «Expandir banco…», para ofrecerla en una lista (T40j): su número (``fid``), su nombre (o su número), su ``bench``, su ``kind`` y su ``part`` si la capa los
    tiene (``des_pbl_`` y ``des_pxb_``), su cota (``level_m``: la Z media de sus vértices; ``None`` sin Z) y si la capa tiene banco y tipo (``columns``)."""

    fid: int
    name: str
    bench: int | None
    kind: str | None
    part: int | None
    level_m: float | None
    columns: bool


def describe_lines(lines: Lines3D) -> tuple[SourceLine, ...]:
    """Las líneas de ``lines`` en el orden de la capa, descritas para las listas del diálogo (T40j). **Solo lee.**"""
    layer = lines.layer
    banks, kinds, parts = (_values(lines, key) for key in ("bench", "kind", "part"))
    names = entity_store._names(layer)
    found: list[SourceLine] = []
    for index, fid in enumerate(layer.fids):
        stored = lines.xyz[index]
        level = None
        if stored is not None and stored.ndim == 2 and stored.shape[1] >= 3 and bool(np.isfinite(stored[:, 2]).all()):
            level = float(np.mean(stored[:, 2]))
        bench = None if banks is None or banks[index] is None else int(banks[index])
        part = None if parts is None or parts[index] is None else int(parts[index])
        kind = None if kinds is None or kinds[index] is None else str(kinds[index])
        found.append(SourceLine(int(fid), names[index] or str(fid), bench, kind, part, level, banks is not None and kinds is not None))
    return tuple(found)


def source_lines(project: StoreProject, version: Version, layer: str) -> tuple[SourceLine, ...]:
    """Las líneas de la capa de partida ``layer`` de ``version`` (T40j), descritas con :func:`describe_lines`; ``GisError``/``ValueError`` si no es una capa de líneas de las que admite
    «Expandir banco…». **Solo lee.**"""
    request = ExpandRequest("lista", LayerFields(layer, None), "up", "terreno")
    return describe_lines(_source_record(project, version, request)[1])


def _source_record(project: StoreProject, version: Version, request: ExpandRequest) -> Any:
    name = request.layer
    if not name.startswith((_BREAKLINE_PREFIX, *_SOURCE_PREFIXES)):
        raise _bad(request, name, "no es una línea de rotura (gis_brk_…), una capa propuesta (des_rpl_…), un banco expandido (des_pxb_…) ni las polilíneas de una corta (des_pbl_…)")
    with project.read() as conn:
        record = dataset_registry.get(conn, name, version_uid=version.uid if name.startswith(_SOURCE_PREFIXES) else "")
        if record is None:
            raise GisError("gis.dataset_unknown", obj="Dato de topografía", field="dato", value=name)
        return record, read_lines_3d(conn, record.locator)


# --- El trabajo ----------------------------------------------------------------------------------------------------------


def expand_job(reader: pit_store.PitReader, request: ExpandRequest, grid: Grid, start: np.ndarray, masks: access.MaskSet, refs: Sequence[Any], polyline: Polyline
               ) -> tuple[PitJob, dict[str, Any], dict[str, int]]:
    """El :class:`~.pit_model.PitJob` del paso de ``request`` sobre ``polyline`` **sin proyecto** (``reader``: :class:`~.pit_store.PitReader`; lo comparten preparar y reproducir): el perfil base y los de los
    sectores, las rosetas, los bancos por berma y las tolerancias, con los rechazos de la corta; la línea es el único polígono de origen. Devuelve el job, los valores resueltos de la corta y cuántos rangos tiene
    cada roseta usada."""
    pit = request.as_pit()
    code = EXPAND_CODE
    sector_codes = pit_store._sector_codes(pit, code, refs)
    base, by_sector = pit_store._profiles(reader, pit, code, sector_codes)
    # el paso no tiene criterio de parada: se resuelven los valores como los de una ascendente (no piden ninguno) y el job lleva el sentido de verdad
    values = pit_store.pit_values(replace(pit, mode=PitMode.UP), code, start_ref=request.start or "terreno")
    rose, rose_by_sector, counts = pit_store._roses(reader, pit, code, sector_codes)
    sectors = pit_store._sectors(reader, pit, code, by_sector, sector_codes, base, rose_by_sector)
    cut, fill = admitted_pair(masks, (slice(0, grid.nrows), slice(0, grid.ncols)))
    source = PitSource(request.name, np.asarray(polyline.vertices[:, :2], dtype=np.float64), polyline.z_m)
    job = PitJob(pit, code, grid, start, cut, fill, untouchable_cells(masks), (source,), PitParams.from_values(values), base, sectors, rose, (), (), (), None, None, None, ())
    return job, values, counts


@dataclass(frozen=True, slots=True, eq=False)
class PreparedExpand:
    """Lo que se lee y se comprueba antes de «Expandir banco…» (:func:`prepare_expand_units`): el ``job``, lo que anotará la operación (``start``), la ``version``, la superficie de partida (``start_surface``), la
    ``polyline`` de partida, el nombre del dato de la capa de partida (``source``) y los ``values`` resueltos de los parámetros que lee. **Nada del proyecto**: no es una entidad."""

    job: PitJob
    start: OperationStart
    version: Version
    start_surface: str
    source: str
    polyline: Polyline
    request: ExpandRequest
    values: Mapping[str, Any]

    @property
    def op_type(self) -> str:
        """El tipo de la operación (``des.pit_expand``)."""
        return self.start.op_type

    @property
    def version_uid(self) -> str:
        """El uid de la versión."""
        return self.version.uid


def prepare_expand_units(project: StoreProject, request: ExpandRequest, version: Version, masks: access.MaskSet, *, supersedes: str | None = None) -> Generator[None, None, PreparedExpand]:
    """Las unidades (cada ``yield``, una) que preparan ``request`` en la versión editable ``version`` con las máscaras al día ``masks``: la partida (en blanco, la última de la cadena si es una sola), la línea de
    partida con sus rechazos (:func:`source_polyline`), la superficie comparada con la rejilla del proyecto, el perfil, la roseta y los parámetros (:func:`expand_job`) y lo que anotará la operación. **Nada se
    escribe.** ``supersedes``: la operación a la que sustituye (un recálculo). ``ValueError`` si las máscaras no son de la versión."""
    if masks.version_uid != version.uid:
        raise ValueError(f"las máscaras son de otra versión, no de {version.code}")
    pit, code, name = request.as_pit(), EXPAND_CODE, request.name
    registry = entities.registry(project, version.uid)
    start_ref = request.start.strip()
    if not start_ref:
        proposed = pit_store._default_start(registry)
        if proposed is None:
            raise pit_store._reject("des.entity_param_missing", pit, code, PitParam.START, None)
        start_ref = proposed
    start_name = pit_store._start_dataset(registry, version, name, code, start_ref, PitParam.START)
    yield
    record, lines = _source_record(project, version, request)
    polyline = source_polyline(lines, request)
    yield
    frame = project_frame(project)
    grid = frame.grid
    surface = yield from read_surface_steps(project, start_name, version_uid=version.uid, expect=frame, role=pit_store._START_ROLE)
    if not grid.same_geometry(masks.grid):
        raise ValueError("la rejilla de las máscaras no es la del proyecto")
    reader = pit_store.ProjectReader(project, version)
    refs, _labels = sector_layout(project, masks)
    asked = replace(request, start=start_ref)
    job, values, counts = expand_job(reader, asked, grid, surface.values, masks, refs, polyline)
    yield
    profiles = tuple(item.code for item in job.bench_profiles)
    params = expand_params(profiles, counts)
    role = provenance.PIT_POLYLINES_ROLE if request.layer.startswith(provenance.FAMILIES_BY_CODE[provenance.PIT_POLYLINES_TABLE].prefix) else provenance.ENTITY_LAYER_ROLE
    inputs = tuple(dict.fromkeys((Use(request.layer, role), Use(start_name, provenance.SURFACE_ROLE), *masks.uses())))
    begun = _start(project, provenance.PIT_EXPAND, name, version, masks, expand_settings(asked), inputs, params, supersedes)
    resolved = {key: value for key, value in pit_store._resolved_values(project, version, params).items()}
    yield
    return PreparedExpand(job, begun, version, start_name, request.layer, polyline, asked, MappingProxyType(resolved))


def prepare_expand(project: StoreProject, request: ExpandRequest, *, version: str | None, masks: access.MaskSet | None = None, supersedes: str | None = None) -> PreparedExpand:
    """La preparación entera de :func:`prepare_expand_units` de una vez (sin ceder el hilo), con los mismos rechazos y sin escribir nada. ``version``: la activa (``VersionError`` si no hay o no se edita)."""
    found = require_version(project, version, provenance.PIT_EXPAND)
    work = prepare_expand_units(project, request, found, _loaded_masks(project, found, masks), supersedes=supersedes)
    while True:
        try:
            next(work)
        except StopIteration as stop:
            result: PreparedExpand = stop.value
            return result


# --- Calcular ------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class ExpandOutcome:
    """El resultado de un paso (RF-018-22): el ``name`` de la operación, la ``source`` (la polilínea de partida), la ``expansion`` (:class:`~.pit_bench.Expansion`: las polilíneas siguientes con su
    comprobación de inclinación o de berma), las ``figures`` (longitud del pie o de la cresta), los ``notices`` y el ``message``."""

    name: str
    source: Polyline
    expansion: Expansion
    figures: tuple[FigureSpec, ...]
    notices: tuple[Notice, ...]
    message: str

    @property
    def polylines(self) -> tuple[Polyline, ...]:
        """Las polilíneas del banco siguiente."""
        return self.expansion.polylines


def expand_compute_steps(job: PitJob, polyline: Polyline, *, budget_s: float = STEP_BUDGET_S) -> Generator[Progress, None, ExpandOutcome]:
    """Los pasos que calculan el banco siguiente de ``polyline`` en el sentido de ``job`` (A7), **sin proyecto y sin escribir nada**. Un desfase que no se pudo verificar se rechaza
    (``des.pit_offset_not_verified``, RF-018-10) y un paso que no deja ninguna línea, también (``des.pit_expand_empty``)."""
    yield Progress(_PHASE, 0, 1, "Calculando el banco siguiente…")
    found: Expansion = yield from pipeline.forward(pit_bench.expand_one_steps(job, polyline, job.mode, budget_s=budget_s))
    pit_store._reject_unreliable(job, found)
    name = job.request.name
    if not found.polylines:
        raise DesignError("des.pit_expand_empty", obj=f"Expansión «{name}»", field="línea", value=name, entity=name, layer=job.request.layer)
    length = float(sum(item.length_m for item in found.polylines))
    foot = found.kind is PolylineKind.FOOT
    figures = provenance.pit_expand_figures(name, {"des.pit_len_foot_m": length if foot else None, "des.pit_len_crest_m": None if foot else length})
    word = "pie" if foot else "cresta"
    message = f"Banco {found.polylines[0].bench} ({word}) de «{name}» a {found.level_m:.3f} m: {len(found.polylines)} línea(s), {length:.1f} m"
    yield Progress(_PHASE, 1, 1, message)
    return ExpandOutcome(name, polyline, found, figures, found.notices, message)


def expand_layer_rows(outcome: ExpandOutcome) -> tuple[ExpandedRow, ...]:
    """Las filas de la capa ``des_pxb_`` del resultado ``outcome``: una por línea, con el nombre de la operación (y su número si son varias), su banco, su tipo, su parte y la Z de cada vértice. Solo depende de lo
    calculado: lo repite la reproducción."""
    if not isinstance(outcome, ExpandOutcome):
        raise TypeError(f"la capa del banco expandido sale de un ExpandOutcome, no {outcome!r}")
    many = len(outcome.polylines) > 1
    return tuple(ExpandedRow(f"{outcome.name} {number}" if many else outcome.name, item.bench, str(item.kind), item.vertices, item.part)
                 for number, item in enumerate(outcome.polylines, 1))


@dataclass(frozen=True, slots=True)
class ExpandSummary:
    """El resumen de «Calcular» (lo que enseña la vista previa, RF-018-26): la cota y el tipo del banco siguiente, cuántas líneas y su longitud, la comprobación de inclinación (``slope_deg`` frente a
    ``slope_limit_deg``) o de berma (``berm_min_m`` frente a ``berm_limit_m``) —la que no es del paso, ``None``— y si cada una cumple, y los avisos."""

    version: str
    kind: str
    level_m: float
    lines: int
    length_m: float
    slope_deg: float | None
    slope_limit_deg: float | None
    slope_ok: bool
    berm_min_m: float | None
    berm_limit_m: float | None
    berm_ok: bool
    notices: tuple[Notice, ...]


def expand_summary(outcome: ExpandOutcome, *, version: str) -> ExpandSummary:
    """El resumen del paso ``outcome`` (puro: sin proyecto)."""
    found = outcome.expansion
    return ExpandSummary(version, str(found.kind), found.level_m, len(found.polylines), float(sum(item.length_m for item in found.polylines)), found.slope_deg, found.slope_limit_deg, found.slope_ok,
                         found.berm_min_m, found.berm_limit_m, found.berm_ok, outcome.notices)


# --- Crear, repetir ------------------------------------------------------------------------------------------------------


def create_expand_steps(project: StoreProject, writer: DesignWriter, prepared: PreparedExpand, outcome: ExpandOutcome, *, budget_s: float = STEP_BUDGET_S) -> Generator[Progress, None, Stored]:
    """**«Crear»** el banco expandido por pasos (RF-018-22, P-12): prepara la capa (``des_pxb_``) en su temporal y la registra en **una** transacción con la operación (entradas, ajustes y parámetros del perfil),
    **la capa, que es del usuario desde que se crea** (``qgis_editable``), las dos cifras y el mensaje. No escribe ninguna superficie ni parámetro de entidad. Si algo falla o lo que consume cambió
    (``des.input_changed``), no queda nada. Con un escritor reanudado (un recálculo) la operación ya empezó. Devuelve lo guardado."""
    if not isinstance(outcome, ExpandOutcome):
        raise TypeError(f"se crea la expansión de un ExpandOutcome, no {outcome!r}")
    yield Progress(_STORE_PHASE, 0, 1, f"Guardando el banco «{outcome.name}»…")
    yield from pipeline.forward(_store_steps(writer.pit_expanded_layer_steps(expand_layer_rows(outcome)), budget_s, "la capa del banco expandido"))
    yield Progress(_STORE_PHASE, 1, 1, f"Registrando el banco «{outcome.name}»…")
    return writer.commit(None if writer.handle is not None else prepared.start, figures=outcome.figures, message=outcome.message)


def create_expand(project: StoreProject, writer: DesignWriter, prepared: PreparedExpand, outcome: ExpandOutcome) -> Stored:
    """:func:`create_expand_steps` de una vez (sin ceder el hilo)."""
    work = create_expand_steps(project, writer, prepared, outcome)
    while True:
        try:
            next(work)
        except StopIteration as stop:
            result: Stored = stop.value
            return result


def _refuse_edited(project: StoreProject, prepared: PreparedExpand, supersedes: str | None) -> None:
    """**Repetir no sobrescribe lo que la persona dibujó** (principio 7, P-12): si la capa a la que sustituye se editó fuera de Geoblender, ``des.pit_expand_layer_edited`` y no se empieza nada."""
    if supersedes is None:
        return
    dataset = provenance.dataset_name(provenance.PIT_EXPANDED_TABLE, prepared.request.name)
    with project.read() as conn:
        record = dataset_registry.get(conn, dataset, version_uid=prepared.version.uid)
    if record is not None and record.live and record.operation_uid != supersedes:
        raise DesignError("des.pit_expand_layer_edited", obj=f"Expansión «{prepared.request.name}»", field="capa", value=record.locator, table=record.locator, operation=prepared.request.name)


def _check_recorded(handle: OperationHandle, prepared: PreparedExpand) -> None:
    for param in handle.params:
        if param.key in prepared.values and param.value != prepared.values[param.key]:
            raise DesignError("des.input_changed", obj=f"Parámetro «{param.key}»", field="parámetros", value=param.key)


def run_expand(project: StoreProject, request: ExpandRequest, *, version: str | None, masks: access.MaskSet | None = None, supersedes: str | None = None,
               budget_s: float = STEP_BUDGET_S) -> tuple[OperationHandle, Iterator[Progress]]:
    """Calcula y registra la expansión de **una vez**, sin pedir confirmación (el recálculo de lo obsoleto): prepara, empieza la operación ``des.pit_expand`` y devuelve su ``OperationHandle`` y sus pasos (el
    último lleva lo guardado). **No sobrescribe lo que se dibujó en QGIS**: ``des.pit_expand_layer_edited`` al llamar, sin empezar nada."""
    prepared = prepare_expand(project, request, version=version, masks=masks, supersedes=supersedes)
    _refuse_edited(project, prepared, supersedes)
    handle = prepared.start.begin(project)
    return handle, _run(project, handle, prepared, budget_s)


def _run(project: StoreProject, handle: OperationHandle, prepared: PreparedExpand, budget_s: float) -> Generator[Progress, None, None]:
    with DesignWriter.resume(project, handle) as writer:
        _check_recorded(handle, prepared)
        outcome: ExpandOutcome = yield from expand_compute_steps(prepared.job, prepared.polyline, budget_s=budget_s)
        stored: Stored = yield from create_expand_steps(project, writer, prepared, outcome, budget_s=budget_s)
        yield Progress(_STORE_PHASE, 1, 1, outcome.message, result=stored)


def recompute_expand(request: RecomputeRequest, *, budget_s: float = STEP_BUDGET_S) -> tuple[OperationHandle, Iterator[Progress]]:
    """Repite ``des.pit_expand`` de ``request`` (:func:`~.store.recompute_run`; «Recalcular lo obsoleto») con lo vigente hoy: la línea de partida, la superficie, las máscaras y los valores del perfil y la
    roseta. No sobrescribe la capa si se editó en QGIS. ``TypeError`` si no es una ``RecomputeRequest``; ``ValueError`` si no es de ``des.pit_expand``."""
    if not isinstance(request, RecomputeRequest):
        raise TypeError(f"se recalcula una RecomputeRequest, no {request!r}")
    if request.op_type != provenance.PIT_EXPAND:
        raise ValueError(f"recompute_expand repite {provenance.PIT_EXPAND}, no «{request.op_type}»")
    project: StoreProject = request.project  # type: ignore[assignment]
    found = require_version(project, request.version, provenance.PIT_EXPAND)
    return run_expand(project, expand_request(request.settings), version=found.uid, supersedes=request.operation_uid, budget_s=budget_s)

