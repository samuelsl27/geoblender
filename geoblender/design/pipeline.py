# SPDX-License-Identifier: GPL-3.0-or-later
"""El cálculo completo de una envolvente y de un escalonado sobre entradas ya leídas (spec 013,
T15; HU-013-3, HU-013-5, HU-013-6; RF-013-11 a RF-013-17, RF-013-21 a RF-013-31; plan 013 §5.3.1,
§5.3.2, §5.4).

Aquí no hay proyecto: el cálculo recibe lo que ya se leyó —las semillas y su dominio, las
superficies, las máscaras, los sectores con sus etiquetas, los valores de los parámetros— y lo
compone con las funciones del dominio (``envelopes``, ``benching``, ``compose``, ``report``,
``berms``). Por eso es **el mismo cálculo** cuando se recalcula lo obsoleto (``design.store``, con
las entradas vigentes del proyecto) y cuando se reproduce una revisión congelada
(``design.reproduce``, con las entradas congeladas y sin proyecto, RF-009-11): lo que cambia es de
dónde se lee, no lo que se hace.

- :func:`envelope_compute_steps` (:class:`EnvelopeJob` → :class:`EnvelopeOutcome`): la envolvente de
  las semillas (``envelope_steps``), recortada al dominio de trabajo (``NaN`` fuera de él y donde
  no hay envolvente), con sus cifras CALCULADO (RF-013-17): las celdas, el área, las cotas mínima y
  máxima y, si las semillas salen de una superficie, el desmonte y el terraplén frente a ella.
- :func:`design_compute_steps` (:class:`DesignJob` → :class:`DesignOutcome`): regulariza la
  envolvente entre sectores, la escalona en corte o en relleno con el perfil de cada sector y la
  berma impuesta por su talud, la recorta, la compone con las máscaras, mide su informe y sus
  bermas y arma las cifras (RF-013-22 a RF-013-31). Si la regularización bajó la envolvente más
  que la tolerancia (una pendiente constante más empinada que el talud general de un sector), el
  informe lo avisa con las celdas y el descenso máximo (spec 0.4, RF-013-26 y RF-013-30): no
  cambia la envolvente registrada ni el escalonado.
- Los parámetros llegan como un diccionario clave → valor (:func:`bench_profiles`,
  :func:`imposed_from`, :func:`envelope_slope`): del proyecto, lo que anotó la operación al
  empezar (``OperationHandle.params``); de lo congelado, ``ReproduceRequest.params``.

Todo por pasos (D-20): cada función ``*_steps`` es un generador de :class:`Progress` que deja pasar
los pasos de las funciones que compone y termina con uno que lleva el resultado. Cerrar el
generador a mitad no deja nada: aquí no se escribe. Python puro (nivel 8), con numpy.
"""

from __future__ import annotations

import math
from collections.abc import Generator, Iterable, Iterator, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass

import numpy as np

from ..core.project.model import Progress
from ..core.provenance.figures import FigureSpec
from ..gis.grid import Grid
from ..gis.masks.compile import STEP_BUDGET_S
from . import benching, berms, compose, envelopes, provenance, report
from .envelopes import Envelope, SlopeField, SlopeRule
from .messages import DesignError
from .model import (
    PERIMETER_SEGMENT,
    BenchProfile,
    BenchSense,
    DesignRequest,
    EnvelopeRequest,
    SeedKind,
    SlopeMode,
)
from .params import BenchParam, bench_key, check_bench_value, check_sector_slope
from .seeds import SectorRef, SeedSet
from .sectors import slope_key

__all__ = [
    "DesignJob",
    "DesignOutcome",
    "EnvelopeJob",
    "EnvelopeOutcome",
    "bench_profiles",
    "design_compute_steps",
    "envelope_compute_steps",
    "envelope_slope",
    "forward",
    "imposed_from",
    "previous_of",
    "profile_rule",
    "touched_in",
    "uses_start_surface",
]

_OBJ_SECTOR = "Sector"
_OBJ_ANCHORS = "Rejilla de anclas"
_OBJ_PROFILE = "Perfil de banco"


# --- Los parámetros y los sectores ---------------------------------------------------------------


def bench_profiles(values: Mapping[str, object], codes: Iterable[str]) -> dict[str, BenchProfile]:
    """Los perfiles de banco de ``codes`` con los cinco valores de ``values`` (clave
    ``des.bench.{p}.…`` → valor). El nombre es el código (el nombre libre del perfil no cambia
    ningún cálculo). Un valor que falta o está fuera de rango es ``DesignError``
    ``des.profile_value_missing`` o ``_range`` nombrando el perfil, el campo y el valor
    (RF-013-19)."""
    found: dict[str, BenchProfile] = {}
    for code in dict.fromkeys(codes):
        found[code] = BenchProfile(
            code, code, **{param.value: values.get(bench_key(code, param))  # type: ignore[arg-type]
                           for param in BenchParam})
    return found


def profile_rule(values: Mapping[str, object], code: str) -> SlopeRule:
    """La regla de pendiente de la envolvente de un perfil (RF-013-13): su talud general
    ``h / (h/tan α + B)`` con su factor de malla. Lee solo la altura, la cara, la berma y el
    factor de malla (una envolvente no lee el ancla); los valores que faltan o están fuera de
    rango, como :func:`bench_profiles`. Con los mismos números que ``BenchProfile.general_tan``."""
    got = {param: check_bench_value(code, code, param, values.get(bench_key(code, param)))
           for param in (BenchParam.HEIGHT, BenchParam.FACE, BenchParam.BERM,
                         BenchParam.MESH_FACTOR)}
    height = got[BenchParam.HEIGHT]
    advance = height / math.tan(math.radians(got[BenchParam.FACE])) + got[BenchParam.BERM]
    return SlopeRule(height / advance, got[BenchParam.MESH_FACTOR])


def imposed_from(values: Mapping[str, object], sectors: Sequence[SectorRef]) -> dict[str, float]:
    """Código → talud general máximo impuesto (°, comprobado: de 0 a 90, ambos excluidos) de los
    sectores de ``sectors`` que lo tienen en ``values`` (clave ``des.sector.{s}.…`` → valor): los
    que no tienen valor no salen (RF-013-09). ``DesignError`` ``des.sector_slope_range`` fuera de
    rango."""
    found: dict[str, float] = {}
    for sector in sectors:
        value = values.get(slope_key(sector.code))
        if value is not None:
            found[sector.code] = check_sector_slope(sector.code or PERIMETER_SEGMENT,
                                                    float(value))  # type: ignore[arg-type]
    return found


def touched_in(sectors: Sequence[SectorRef], labels: np.ndarray, mask: np.ndarray
               ) -> tuple[str, ...]:
    """Los códigos de los ``sectors`` que tienen alguna celda en ``mask`` (``labels`` es la
    etiqueta de cada celda: el sector ``k`` es la ``k + 1``), en su orden (D-15)."""
    counts = np.bincount(labels[mask], minlength=len(sectors) + 1)
    return tuple(sector.code for index, sector in enumerate(sectors, start=1)
                 if index < counts.size and counts[index] > 0)


def _unknown_sectors(assigned: Mapping[str, str] | Iterable[tuple[str, str]],
                     sectors: Sequence[SectorRef]) -> None:
    """``des.sector_unknown`` si un perfil se asigna a un sector que no es de ``sectors``."""
    known = {sector.code for sector in sectors}
    for code, _profile in dict(assigned).items():
        if code not in known:
            raise DesignError("des.sector_unknown", obj=_OBJ_SECTOR, field="sector", value=code,
                              known=", ".join(sector.code or sector.name for sector in sectors)
                              or "—")


def envelope_slope(request: EnvelopeRequest, sectors: Sequence[SectorRef], labels: np.ndarray,
                   values: Mapping[str, object]) -> SlopeField:
    """La pendiente de la envolvente de ``request`` (RF-013-13): la constante de la petición o, por
    sectores, el talud general de cada uno —el máximo que impone o, si no lo tiene, el del perfil
    que se le asigna (``sector_profiles`` o el ``base_profile``)— y el del perfil base en las
    celdas sin sector. ``sectors`` son los de la rejilla y ``labels`` la etiqueta de cada celda
    (``DomainSet.sectors`` y ``labels``); ``values``, los parámetros. Un sector sin talud impuesto
    ni perfil es ``DesignError`` ``des.profile_unassigned``."""
    if SlopeMode(request.slope_mode) is SlopeMode.CONSTANT:
        return envelopes.request_slope(request)
    assigned = dict(request.sector_profiles)
    _unknown_sectors(assigned, sectors)
    imposed = imposed_from(values, sectors)
    rules: list[SlopeRule | None] = []
    for sector in sectors:
        profile = assigned.get(sector.code, request.base_profile)
        if sector.code in imposed:
            mesh = (profile_rule(values, profile).mesh_factor if profile
                    else request.mesh_factor)
            rules.append(SlopeRule.from_degrees(imposed[sector.code], mesh))
        elif profile:
            rules.append(profile_rule(values, profile))
        else:
            shown = sector.name if sector.code == "" else f"«{sector.name}»"
            raise DesignError("des.profile_unassigned", obj=f"Sector {shown}", field="profile",
                              value=shown)
    base = profile_rule(values, request.base_profile) if request.base_profile else None
    return envelopes.sector_slope(labels, rules, base)


# --- Los pasos ------------------------------------------------------------------------------


def forward[T](steps: Iterator[Progress]) -> Generator[Progress, None, T]:
    """Deja pasar los pasos de ``steps`` y devuelve lo que lleva el último (``result``); cerrar el
    generador cierra ``steps``."""
    with closing(steps):  # type: ignore[type-var]
        for step in steps:
            if step.result is not None:
                return step.result  # type: ignore[return-value]
            yield step
    raise RuntimeError("los pasos terminaron sin dar resultado")


def _finish(phase: str, text: str, result: object) -> Progress:
    return Progress(phase, 1, 1, text, result=result)


# --- La envolvente ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class EnvelopeJob:
    """Lo que necesita calcular una envolvente, ya leído: la petición, las ``seeds`` (con su
    geometría y su dominio de trabajo), la pendiente ya resuelta (:func:`envelope_slope`), la
    superficie de partida ``start`` con la que se comparan los volúmenes (``None`` si las semillas
    no salen de una superficie) y el espesor mínimo con que se cuentan (m)."""

    request: EnvelopeRequest
    seeds: SeedSet
    slope: SlopeField
    start: np.ndarray | None
    min_thickness_m: float


@dataclass(frozen=True, slots=True, eq=False)
class EnvelopeOutcome:
    """Una envolvente calculada: su ``grid`` (m, float64, nueva; ``NaN`` fuera del dominio de
    trabajo y donde no hay envolvente), el ``envelope`` del cálculo, las cifras CALCULADO
    (``figures``) y el ``message`` de la operación."""

    grid: np.ndarray
    envelope: Envelope
    figures: tuple[FigureSpec, ...]
    message: str


def envelope_compute_steps(job: EnvelopeJob, *, budget_s: float = STEP_BUDGET_S
                           ) -> Iterator[Progress]:
    """La envolvente de ``job`` por pasos de ``budget_s`` como mucho: el último ``Progress`` lleva
    el :class:`EnvelopeOutcome`. Los rechazos de RF-013-16 salen al avanzar (``envelope_steps``).
    Ninguna entrada se modifica; no se escribe nada."""
    return _envelope_steps(job, budget_s)


def _envelope_steps(job: EnvelopeJob, budget_s: float) -> Generator[Progress, None, None]:
    seeds, request = job.seeds, job.request
    found: Envelope = yield from forward(
        envelopes.envelope_steps(request, seeds, job.slope, budget_s=budget_s))
    geometry = seeds.geometry
    with np.errstate(invalid="ignore"):
        keep = seeds.domain.mask & np.isfinite(found.grid)
    grid = np.where(keep, found.grid, np.nan)
    yield Progress("figures", 0, 1, "Midiendo la envolvente…")
    cells = int(np.count_nonzero(keep))
    low = float(grid[keep].min()) if cells else None
    high = float(grid[keep].max()) if cells else None
    cut = fill = None
    if job.start is not None:
        moved = report.volumes(job.start, grid, geometry, job.min_thickness_m)
        cut, fill = moved.cut_m3, moved.fill_m3
    figures = provenance.envelope_figures(name=request.name, cells=cells,
                                          area_m2=cells * geometry.cell_area, min_m=low,
                                          max_m=high, cut_m3=cut, fill_m3=fill)
    text = (f"Envolvente «{request.name}» calculada: {cells} celdas "
            f"({cells * geometry.cell_area:.1f} m²)")
    yield _finish("figures", text, EnvelopeOutcome(grid, found, figures, text))


# --- El escalonado ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class DesignJob:
    """Lo que necesita calcular un escalonado, ya leído: la petición, la ``geometry`` de la
    rejilla, la superficie de partida (``start``) y la envolvente que se escalona (``envelope``:
    ``NaN`` fuera del dominio de trabajo), las ``masks`` (cualquier objeto con ``cut_allowed``,
    ``fill_allowed`` y ``fill_strip``: un ``MaskSet``), los ``sectors`` con la etiqueta de cada
    celda (``labels``), los taludes ``imposed`` por sector, los ``profiles`` por código
    (:func:`bench_profiles`), la rejilla de ``anchors`` si el ancla no es la del perfil, el
    espesor mínimo, la tolerancia de cara y el umbral de aviso de magnitud, lo ``previous`` con
    que se compara el desmonte y el terraplén (D-25) y los nombres de los sectores con la búsqueda
    ``pending`` (RF-013-06)."""

    request: DesignRequest
    geometry: Grid
    start: np.ndarray
    envelope: np.ndarray
    masks: object
    sectors: tuple[SectorRef, ...]
    labels: np.ndarray
    imposed: Mapping[str, float]
    profiles: Mapping[str, BenchProfile]
    anchors: np.ndarray | None
    min_thickness_m: float
    face_tolerance_deg: float
    warning_ratio: float
    previous: report.Previous | None = None
    pending: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, eq=False)
class DesignOutcome:
    """Un escalonado calculado: la superficie de diseño (``design``, float64 nueva), las bermas
    medidas (``berms``: su rejilla y su tabla), el informe, las cifras CALCULADO, el área del
    dominio de trabajo sin sector (``unassigned_area_m2``) y el ``message`` de la operación."""

    design: np.ndarray
    berms: berms.Berms
    report: report.DesignReport
    figures: tuple[FigureSpec, ...]
    unassigned_area_m2: float
    message: str


def _lowering(regular: benching.Regularization, envelope: np.ndarray, labels: np.ndarray,
              sectors: Sequence[SectorRef]) -> report.Lowering | None:
    """Lo que bajó la regularización entre sectores (RF-013-26, RF-013-30; spec 0.4; F-1), para
    avisarlo: las celdas bajadas más que la tolerancia y el descenso máximo (los de ``regular``), el
    talud con que se regularizó (°) y los nombres de los ``sectors`` con alguna celda bajada, en su
    orden (``labels`` es la etiqueta de cada celda: el sector ``k`` es la ``k + 1``). ``None`` si no
    bajó ninguna. Solo lee: no cambia la regularización ni el escalonado."""
    if regular.lowered == 0 or regular.tan is None:
        return None
    with np.errstate(invalid="ignore"):
        below = regular.grid < envelope - envelopes.TOLERANCE_M
    counts = np.bincount(labels[below], minlength=len(sectors) + 1)
    names = tuple(sector.name for index, sector in enumerate(sectors, start=1)
                  if index < counts.size and counts[index] > 0)
    return report.Lowering(regular.lowered, regular.lowered_max_m,
                           math.degrees(math.atan(regular.tan)), names)


def _per_label(values: Sequence[float], labels: np.ndarray) -> float | np.ndarray:
    """Un valor por etiqueta (la 0, el perfil base) como un número, si es el mismo en todas, o un
    mapa por celda."""
    table = np.asarray(values, dtype=np.float64)
    if bool(np.all(table == table[0])):
        return float(table[0])
    return table[labels]


def design_compute_steps(job: DesignJob, *, budget_s: float = STEP_BUDGET_S
                         ) -> Iterator[Progress]:
    """El escalonado de ``job`` por pasos de ``budget_s`` como mucho: el último ``Progress`` lleva
    el :class:`DesignOutcome`. Rechaza al avanzar un perfil asignado a un sector que no existe
    (``des.sector_unknown``) y una rejilla de anclas sin cota en el dominio (``des.anchor_nodata``);
    ninguna entrada se modifica y no se escribe nada."""
    return _design_steps(job, budget_s)


def _design_steps(job: DesignJob, budget_s: float) -> Generator[Progress, None, None]:
    request, geometry, labels = job.request, job.geometry, job.labels
    sense = BenchSense(request.sense)
    start = np.asarray(job.start, dtype=np.float64)
    envelope = np.asarray(job.envelope, dtype=np.float64)
    assigned = dict(request.sector_profiles)
    _unknown_sectors(assigned, job.sectors)
    with np.errstate(invalid="ignore"):
        domain = np.isfinite(envelope)
    if job.anchors is not None:
        with np.errstate(invalid="ignore"):
            missing = int(np.count_nonzero(domain & ~np.isfinite(job.anchors)))
        if missing:
            raise DesignError("des.anchor_nodata", obj=_OBJ_ANCHORS, field="anchors",
                              value=request.anchor_grid, cells=missing)
    base = job.profiles[request.base_profile]
    by_label = [base, *(job.profiles[assigned.get(sector.code, request.base_profile)]
                        for sector in job.sectors)]
    imposed = [None, *(job.imposed.get(sector.code) for sector in job.sectors)]
    berm_m = [benching.sector_berm(profile, degrees)
              for profile, degrees in zip(by_label, imposed, strict=True)]
    heights = _per_label([p.height_m for p in by_label], labels)
    faces = _per_label([p.face_deg for p in by_label], labels)
    tan_face = _per_label([math.tan(math.radians(p.face_deg)) for p in by_label], labels)
    mesh = _per_label([p.mesh_factor for p in by_label], labels)
    berm = _per_label(berm_m, labels)
    anchor: float | np.ndarray = (_per_label([p.anchor_m for p in by_label], labels)
                                  if job.anchors is None else job.anchors)
    yield Progress("benching", 0, 1, "Preparando el escalonado…")
    # La envolvente, regularizada entre sectores con taludes distintos (RF-013-26): la regla de
    # cada sector es su talud impuesto o el general de su perfil. Una envolvente más empinada que
    # la tangente de la regularización baja (spec 0.4, F-1): no se cambia, se avisa.
    rules = [SlopeRule.from_degrees(degrees, p.mesh_factor) if degrees is not None
             else SlopeRule(p.general_tan, p.mesh_factor)
             for p, degrees in zip(by_label[1:], imposed[1:], strict=True)]
    base_rule = SlopeRule(base.general_tan, base.mesh_factor)
    slope = envelopes.sector_slope(labels, rules, base_rule)
    regular: benching.Regularization = yield from forward(benching.regularize_steps(
        envelope, geometry, slope, domain=domain, name=request.name, budget_s=budget_s))
    lowering = _lowering(regular, envelope, labels, job.sectors)
    stairs = (benching.bench_cut if sense is BenchSense.CUT else benching.bench_fill)(
        regular.grid, heights, tan_face, berm, anchor)
    trim: benching.Trim = yield from forward(benching.final_trim_steps(
        stairs, regular.grid, geometry, tan_face, mesh, sense, name=request.name,
        budget_s=budget_s))
    allowed = compose.allowed_cells(job.masks, sense, domain)  # type: ignore[arg-type]
    design = compose.compose(start, trim.grid, allowed, sense)
    face = faces if isinstance(faces, float) else np.where(np.isfinite(trim.grid), faces, np.nan)
    unique = tuple(dict.fromkeys(by_label))
    result: report.DesignReport = yield from forward(report.report_steps(
        start, design, geometry, allowed, min_thickness_m=job.min_thickness_m, face_deg=face,
        face_tolerance_deg=job.face_tolerance_deg, warning_ratio=job.warning_ratio,
        operation=request.name, previous=job.previous, pending=job.pending, profiles=unique,
        lowering=lowering, budget_s=budget_s))
    scopes = [berms.BermScope("", base.code),
              *(berms.BermScope(sector.code, profile.code)
                for sector, profile in zip(job.sectors, by_label[1:], strict=True))]
    moved = report.moved_cells(start, design, job.min_thickness_m)
    measured: berms.Berms = yield from forward(berms.berms_steps(
        design, geometry, heights, anchor, labels, scopes, moved=moved, budget_s=budget_s))
    figures = provenance.design_figures(result, name=request.name, berm_count=measured.count)
    loose = int(np.count_nonzero(domain & (labels == 0))) * geometry.cell_area
    text = (f"Escalonado «{request.name}» calculado: desmonte {result.cut_m3:.1f} m³, "
            f"terraplén {result.fill_m3:.1f} m³ y {measured.count} bermas")
    yield _finish("benching", text, DesignOutcome(design, measured, result, figures, loose, text))


def previous_of(data: Mapping[str, object] | None) -> report.Previous | None:
    """Lo anterior con que se comparó un escalonado (``design.provenance.settings_previous``) como
    :class:`~design.report.Previous`; ``None`` si no se comparó con nada."""
    if data is None:
        return None
    return report.Previous(str(data["operation"]), str(data["revision"]),
                           float(data["cut_m3"]),  # type: ignore[arg-type]
                           float(data["fill_m3"]))  # type: ignore[arg-type]


def uses_start_surface(request: EnvelopeRequest) -> bool:
    """Si las semillas de ``request`` salen de una superficie (la de partida de los volúmenes)."""
    return SeedKind(request.seeds.kind) is SeedKind.SURFACE

