# SPDX-License-Identifier: GPL-3.0-or-later
"""Las semillas y el dominio de trabajo de un cálculo (spec 013; RF-013-01, RF-013-02, RF-013-03;
plan 013 §5.3.1, D-15, D-16).

- **Dominio de trabajo** (RF-013-02): :func:`work_domain_steps` da el :class:`DomainSet`: las celdas
  donde se entrega el resultado, que son, como mucho, el **dominio por defecto** de las máscaras de
  la versión activa **o** la **franja de solo relleno** (RF-012-13), acotado —nunca ampliado— a unos
  sectores o a una capa de polígonos del proyecto (la intersección); con las celdas y el área, los
  **sectores que toca** (D-15: los que tienen alguna celda en él) y las celdas que no son de
  ninguno. Los sectores son los de búsqueda de la 012 (el perímetro de actuación, código ``""``,
  si no hay ninguno declarado); las etiquetas de cada celda se guardan para quien las necesite.
- **Semillas** (RF-013-01): :func:`build_seeds_steps` forma la rejilla de semillas en la rejilla de
  las máscaras (la del proyecto) desde las celdas de una **superficie** del proyecto o de la
  versión activa dentro de una zona (el dominio por defecto, la zona de una restricción, un sector
  o una capa de polígonos; sin zona, toda la superficie), una **cota fija** en las celdas de una
  zona o una **rejilla de cotas**: la cota donde manda y ``+inf`` en las demás. El :class:`SeedSet`
  da el número de celdas, el área (m²), las cotas mínima y máxima, las semillas **fuera del
  dominio de trabajo** (que se conservan: la envolvente las usa; se cuentan, con su área) y las
  celdas de la zona sin cota finita (que no son semilla y se cuentan). Ninguna semilla se descarta
  en silencio; ninguna entrada se remuestrea, se interpola ni se modifica (como RF-011-02).
- **Por pasos** (D-20): cada función ``*_steps`` es un generador de :class:`Progress` que agrupa
  las unidades en pasos de ``budget_s`` como mucho (``gis.masks.compile.pace_units``); el último
  lleva el resultado. Cerrar el generador a mitad no deja nada (no escribe nada). Los rechazos
  salen al avanzar el generador, antes de producir nada.

No rechaza un dominio vacío ni unas semillas vacías: la vista previa tiene que poder decirlo; el
rechazo de calcular es de RF-013-16 (T07). Python puro (nivel 8), con numpy.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Generator, Iterator, Sequence
from contextlib import closing
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from ..core.project.model import Progress
from ..gis.grid import Grid
from ..gis.masks.access import MaskSet
from ..gis.masks.compile import STEP_BUDGET_S, pace_units
from ..gis.masks.store import search_sectors
from ..gis.store import StoreProject
from .messages import DesignError
from .model import SeedKind, SeedSource, WorkDomain, Zone, ZoneKind
from .surfaces import ProjectFrame, check_grid, project_frame, read_surface
from .zones import constraint_cells, layer_cells, sector_labels

__all__ = [
    "DomainSet",
    "SectorRef",
    "SeedPlan",
    "SeedSet",
    "assemble_units",
    "bounded_units",
    "build_seeds_steps",
    "check_source",
    "collect_seeds",
    "domain_of",
    "label_of",
    "pace_progress",
    "sector_layout",
    "seed_units",
    "work_domain_steps",
    "zone_cells",
]

_SEEDS = "Semillas"
_DOMAIN = "Dominio de trabajo"
_SECTOR = "Sector"
_MASKS = "Máscaras de la versión activa"
_ROLE_MASKS = "máscaras"
_ROLE_SURFACE = "semillas"
_ROLE_GRID = "rejilla de cotas"
_NAMED = (ZoneKind.CONSTRAINT, ZoneKind.SECTOR, ZoneKind.LAYER)
"""Las zonas que se piden por su nombre (el dominio por defecto no tiene)."""


# --- Lo que se entrega -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SectorRef:
    """Un sector de búsqueda de la 012 (sector de diseño): su ``code`` (``""``: el perímetro de
    actuación como sector único) y su ``name``."""

    code: str
    name: str


@dataclass(frozen=True, slots=True, eq=False)
class DomainSet:
    """El dominio de trabajo en la rejilla (RF-013-02): ``mask`` (booleana, fila 0 al norte; la
    máscara es del conjunto, ninguna máscara de la versión), sus ``cells`` y su ``area_m2``; la
    etiqueta de sector de cada celda de la rejilla (``labels``: ``int16``, el sector ``k`` de
    ``sectors`` es la etiqueta ``k + 1`` y 0, ninguno); todos los ``sectors`` en su orden; los que
    toca (``touched``: los que tienen alguna celda en el dominio, D-15) y las celdas del dominio
    que no son de ningún sector (``unassigned_*``)."""

    mask: np.ndarray
    cells: int
    area_m2: float
    labels: np.ndarray
    sectors: tuple[SectorRef, ...]
    touched: tuple[SectorRef, ...]
    unassigned_cells: int
    unassigned_area_m2: float


@dataclass(frozen=True, slots=True, eq=False)
class SeedSet:
    """Las semillas de un cálculo (RF-013-01): ``grid``, la rejilla de cotas (m, float64; ``+inf``
    sin semilla); su ``geometry``; ``cells`` y ``area_m2`` de las semillas; ``min_m`` y ``max_m``
    (``None`` sin ninguna); las semillas fuera del dominio de trabajo (``outside_domain``, celdas,
    y su ``outside_area_m2``: se conservan en ``grid``); las celdas de la zona sin cota finita
    (``nodata_cells``: no son semilla) y el ``domain`` con el que se contó."""

    grid: np.ndarray
    geometry: Grid
    cells: int
    area_m2: float
    min_m: float | None
    max_m: float | None
    outside_domain: int
    outside_area_m2: float
    nodata_cells: int
    domain: DomainSet

    @property
    def touched(self) -> tuple[SectorRef, ...]:
        """Los sectores que toca el dominio de trabajo (D-15)."""
        return self.domain.touched


class SeedPlan(Protocol):
    """Lo que se pide de unas semillas: de dónde salen y cómo se acota el dominio. Lo cumple
    :class:`~geoblender.design.model.EnvelopeRequest` (y cualquier cosa con esos dos campos)."""

    @property
    def seeds(self) -> SeedSource: ...

    @property
    def domain(self) -> WorkDomain: ...


# --- Los cálculos puros ------------------------------------------------------------------------


def domain_of(mask: np.ndarray, labels: np.ndarray, sectors: Sequence[SectorRef],
              cell_area_m2: float) -> DomainSet:
    """El :class:`DomainSet` de ``mask`` (booleana; el conjunto la toma, no la copia) con las
    etiquetas de sector ``labels`` (``int16``, de la misma forma; el sector ``k`` es la etiqueta
    ``k + 1``, 0 ninguno) y ``cell_area_m2`` (el área exacta de una celda). Una forma distinta o
    una etiqueta que no es de ningún sector es un error del programa (``ValueError``)."""
    inside = np.asarray(mask, dtype=bool)
    if inside.shape != labels.shape:
        raise ValueError(f"la máscara {inside.shape} y las etiquetas {labels.shape} no son de la "
                         "misma rejilla")
    found = tuple(sectors)
    counts = np.bincount(labels[inside], minlength=len(found) + 1)
    if counts.size > len(found) + 1:
        raise ValueError(f"hay etiquetas de sector hasta {counts.size - 1} y solo "
                         f"{len(found)} sectores")
    cells = int(inside.sum())
    touched = tuple(found[k - 1] for k in range(1, len(found) + 1) if counts[k] > 0)
    loose = int(counts[0])
    return DomainSet(inside, cells, cells * cell_area_m2, labels, found, touched, loose,
                     loose * cell_area_m2)


def collect_seeds(values: np.ndarray, in_zone: np.ndarray | None, domain: DomainSet,
                  geometry: Grid) -> SeedSet:
    """El :class:`SeedSet` de las cotas ``values`` (m, de la forma de ``geometry``) en la zona
    ``in_zone`` (booleana; ``None``: toda la rejilla): son semilla las celdas de la zona con cota
    finita; las demás de la zona (``NaN`` o infinitas) se cuentan como sin cota. La rejilla es
    **nueva** (``+inf`` donde no hay semilla); ``values`` y ``in_zone`` no se tocan. Las semillas
    fuera de ``domain`` se cuentan y se conservan (RF-013-03)."""
    cota = np.asarray(values, dtype=np.float64)
    if cota.shape != geometry.shape or domain.mask.shape != geometry.shape:
        raise ValueError("las cotas, el dominio y la rejilla no son de la misma forma")
    finite = np.isfinite(cota)
    if in_zone is None:
        chosen, in_total = finite, int(cota.size)
    else:
        if in_zone.shape != geometry.shape:
            raise ValueError("la zona no es de la forma de la rejilla")
        chosen, in_total = in_zone & finite, int(in_zone.sum())
    grid = np.where(chosen, cota, np.inf)
    cells = int(chosen.sum())
    outside = int((chosen & ~domain.mask).sum())
    low = high = None
    if cells:
        picked = grid[chosen]
        low, high = float(picked.min()), float(picked.max())
    area = geometry.cell_area
    return SeedSet(grid, geometry, cells, cells * area, low, high, outside, outside * area,
                   in_total - cells, domain)


# --- Las zonas ---------------------------------------------------------------------------------


def _unknown_sector(code: str, sectors: Sequence[SectorRef]) -> DesignError:
    known = ", ".join(sector.code or sector.name for sector in sectors) or "—"
    return DesignError("des.sector_unknown", obj=_SECTOR, field="sector", value=code, known=known)


def label_of(code: str, sectors: Sequence[SectorRef]) -> int:
    """La etiqueta de celda del sector de código ``code`` en ``sectors`` (la posición más uno);
    ``des.sector_unknown`` si no es de ellos."""
    for index, sector in enumerate(sectors, start=1):
        if sector.code == code:
            return index
    raise _unknown_sector(code, sectors)


def zone_cells(project: StoreProject | None, masks: MaskSet, zone: Zone, *,
               sectors: Sequence[SectorRef], labels: np.ndarray,
               layer: Callable[[str], np.ndarray] | None = None) -> np.ndarray:
    """Las celdas de ``zone`` en la rejilla de las máscaras, como máscara nueva (RF-013-01, D-16):
    el dominio por defecto (``kind`` ``domain``); la zona de una restricción en las máscaras
    (celda entera, D-1 de la 012; ``des.zone_unknown`` si no la tiene); un sector por su código
    (``labels`` es su etiqueta ``k + 1``; ``des.sector_unknown`` si no es de ``sectors``) o una
    capa de polígonos del proyecto por su nombre (el centro dentro). Una zona con nombre sin
    nombre es un error del programa (``ValueError``: las peticiones lo comprueban antes).

    Una capa se lee del ``project`` (:func:`~design.zones.layer_cells`) o, si se da ``layer``
    (nombre → máscara en la rejilla), de ahí: así la reproducción de una operación congelada, que
    no tiene proyecto, usa la capa que congeló."""
    kind = ZoneKind(zone.kind)
    if kind is ZoneKind.DOMAIN:
        return masks.default_domain()
    if not zone.name:
        raise ValueError(f"la zona «{kind.value}» necesita su nombre")
    if kind is ZoneKind.CONSTRAINT:
        return constraint_cells(masks, zone.name)
    if kind is ZoneKind.SECTOR:
        return np.asarray(labels == label_of(zone.name, sectors))
    if layer is not None:
        return layer(zone.name)
    if project is None:
        raise ValueError("una zona de capa necesita el proyecto o quien lea la capa")
    return layer_cells(project, zone.name, masks.grid)


# --- Los pasos ---------------------------------------------------------------------------------


def pace_progress[T](work: Generator[None, None, T], budget_s: float, *, phase: str, running: str,
                     finished: str, total: int = 8) -> Iterator[Progress]:
    """Las unidades de ``work`` (cada ``yield``, una) agrupadas en pasos de ``budget_s`` como
    mucho, como ``Progress`` de la ``phase`` con el mensaje ``running``; el último, con
    ``finished``, lleva en ``result`` lo que devuelve ``work``. ``total`` es una estimación inicial
    de los pasos (crece si hacen falta más). Cerrar el generador cierra ``work``."""
    steps = pace_units(work, budget_s)
    done = 0
    with closing(steps):
        while True:
            try:
                next(steps)
            except StopIteration as stop:
                result = stop.value
                break
            done += 1
            total = max(total, done + 1)
            yield Progress(phase, done, total, running)
    yield Progress(phase, total, total, finished, result=result)


def sector_layout(project: StoreProject, masks: MaskSet
                  ) -> tuple[tuple[SectorRef, ...], np.ndarray]:
    """Los sectores de búsqueda del proyecto para la versión de ``masks`` (los declarados o el
    perímetro de actuación) y la etiqueta de cada celda de su rejilla (``int16``; el sector ``k``
    es la etiqueta ``k + 1`` y 0, ninguno). Solo lee."""
    with project.read() as conn:
        found = tuple(sector for sector, _source in
                      search_sectors(conn, project, masks.version_uid))
    refs = tuple(SectorRef(sector.code, sector.name) for sector in found)
    return refs, sector_labels(found, masks.grid)


def _domain_units(project: StoreProject, bound: WorkDomain, masks: MaskSet
                  ) -> Generator[None, None, DomainSet]:
    """Las unidades de :func:`work_domain_steps`."""
    with project.read() as conn:
        found = tuple(sector for sector, _source in
                      search_sectors(conn, project, masks.version_uid))
    refs = tuple(SectorRef(sector.code, sector.name) for sector in found)
    wanted = [label_of(code, refs) for code in bound.sectors]  # rechaza antes de nada pesado
    yield
    labels = sector_labels(found, masks.grid)
    yield
    mask = yield from bounded_units(
        bound, masks, labels, wanted, lambda name: layer_cells(project, name, masks.grid))
    return domain_of(mask, labels, refs, masks.grid.cell_area)


def bounded_units(bound: WorkDomain, masks: MaskSet, labels: np.ndarray, wanted: Sequence[int],
                  layer: Callable[[str], np.ndarray]) -> Generator[None, None, np.ndarray]:
    """El dominio de trabajo como máscara nueva (unidades): el dominio por defecto de ``masks`` más
    la franja de solo relleno, acotado —nunca ampliado— a los sectores de etiqueta ``wanted``
    (``labels`` es la etiqueta de cada celda) y a la capa ``bound.layer`` (``layer``: su nombre →
    máscara en la rejilla). Lo comparten el proyecto y la reproducción de lo congelado."""
    mask = masks.default_domain() | masks.fill_strip()  # una máscara nueva: se acota en ella
    if wanted:
        mask &= np.isin(labels, list(wanted))
        yield
    if bound.layer is not None:
        mask &= layer(bound.layer)
        yield
    return mask


def work_domain_steps(project: StoreProject, bound: WorkDomain, masks: MaskSet, *,
                      budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """El dominio de trabajo de ``masks`` (las de la versión activa, al día) acotado por ``bound``
    (RF-013-02), por pasos: el último ``Progress`` lleva el :class:`DomainSet`. Rechaza (al
    avanzar) un sector que no es de los del proyecto (``des.sector_unknown``) o una capa que no
    es de polígonos (``des.layer_not_polygons``); un dominio vacío no es un error aquí."""
    return pace_progress(_domain_units(project, bound, masks), budget_s, phase="domain",
                         running="Preparando el dominio de trabajo…",
                         finished="Dominio de trabajo listo")


def _missing(source: SeedSource, field: str) -> DesignError:
    return DesignError("des.seed_missing", obj=_SEEDS, field=field,
                       kind=SeedKind(source.kind).value)


def check_source(source: SeedSource) -> None:
    """Rechaza unas semillas a medias (lo que la petición no comprueba) antes de leer nada."""
    kind = SeedKind(source.kind)
    if kind is SeedKind.SURFACE and not source.surface:
        raise _missing(source, "surface")
    if kind is SeedKind.GRID and not source.grid:
        raise _missing(source, "grid")
    if kind is SeedKind.FIXED:
        if source.elevation_m is None:
            raise _missing(source, "elevation_m")
        if not math.isfinite(source.elevation_m):
            raise DesignError("des.seed_elevation", obj=_SEEDS, field="elevation_m",
                              value=source.elevation_m)
        if source.zone is None:
            raise _missing(source, "zone")
    if source.zone is not None and ZoneKind(source.zone.kind) in _NAMED and not source.zone.name:
        raise _missing(source, "zone")


def seed_units(project: StoreProject, plan: SeedPlan, masks: MaskSet
               ) -> Generator[None, None, SeedSet]:
    """Las unidades de :func:`build_seeds_steps` (cada ``yield``, una), para componerlas con otras
    en un solo generador (la vista previa, el cálculo); devuelve el :class:`SeedSet`."""
    source = plan.seeds
    check_source(source)
    frame = project_frame(project)
    check_grid(ProjectFrame(masks.grid, frame.crs, frame.vertical), frame, role=_ROLE_MASKS,
               name=_MASKS)
    yield
    domain = yield from _domain_units(project, plan.domain, masks)
    found = yield from assemble_units(
        source, masks, domain,
        layer=lambda name: layer_cells(project, name, masks.grid),
        surface=lambda name, role: read_surface(
            project, name, version_uid=masks.version_uid, expect=frame, role=role).values)
    return found


def assemble_units(source: SeedSource, masks: MaskSet, domain: DomainSet, *,
                   layer: Callable[[str], np.ndarray],
                   surface: Callable[[str, str], np.ndarray]) -> Generator[None, None, SeedSet]:
    """Las unidades que forman el :class:`SeedSet` de ``source`` (ya comprobada con
    :func:`check_source`) en el dominio ya formado ``domain``: la zona (``layer``: nombre de una
    capa → máscara en la rejilla) y las cotas (``surface``: nombre y papel de una superficie o de
    una rejilla de cotas → sus celdas). Lo comparten el proyecto y la reproducción de lo
    congelado."""
    where = (None if source.zone is None else zone_cells(
        None, masks, source.zone, sectors=domain.sectors, labels=domain.labels, layer=layer))
    yield
    kind = SeedKind(source.kind)
    if kind is SeedKind.FIXED:
        assert where is not None and source.elevation_m is not None  # check_source
        values = np.full(masks.grid.shape, np.inf)
        values[where] = source.elevation_m
    else:
        name, role = ((source.surface, _ROLE_SURFACE) if kind is SeedKind.SURFACE
                      else (source.grid, _ROLE_GRID))
        assert name is not None  # check_source
        values = surface(name, role)
    yield
    found = collect_seeds(values, where, domain, masks.grid)
    yield
    return found


def build_seeds_steps(project: StoreProject, plan: SeedPlan, masks: MaskSet, *,
                      budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """La rejilla de semillas de ``plan`` (``plan.seeds`` y el acotado ``plan.domain``; una
    ``EnvelopeRequest`` sirve) sobre ``masks``, las de la versión activa al día (RF-013-01),
    por pasos de ``budget_s`` como mucho: el último ``Progress`` lleva el :class:`SeedSet`.

    La superficie o la rejilla se lee del proyecto o de la versión activa (``masks.version_uid``)
    y se compara con la rejilla del proyecto antes de leer una celda (``des.surface_mismatch``,
    ``des.surface_is_tin``…, RF-013-16); unas semillas a medias son ``des.seed_missing`` o
    ``des.seed_elevation``. Solo lee: no escribe nada en el proyecto ni modifica ninguna entrada."""
    return pace_progress(seed_units(project, plan, masks), budget_s, phase="seeds",
                         running="Preparando las semillas…", finished="Semillas listas")
