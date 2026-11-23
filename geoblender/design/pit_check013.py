# SPDX-License-Identifier: GPL-3.0-or-later
"""El contraste de la corta con el escalonado de la 013 (spec 018, T20; HU-018-2; RF-018-27; CE-018-12; plan 018 §5.4 A13).

DONDE la persona pida contrastar la corta con la 013, se calcula el **escalonado en corte de la 013** con el mismo perfil, ancla y semillas que la
corta (el fondo de la ascendente a su cota; el límite de la descendente, a su cota o al terreno) llamando a :mod:`design.envelopes` (la envolvente
*chamfer* 5×5 con el talud general del perfil por su factor de malla) y a :mod:`design.benching` (``bench_cut`` y el recorte final), restringido al
recinto de la corta, y se compone con la partida como en la 013 (``mín`` en lo admitido por las máscaras). Se da:

- la **diferencia máxima de cota** entre la superficie de la corta y la de la 013 (m, con su lugar), en las celdas donde alguna de las dos corta;
- la **diferencia de volumen** de corte (m³ y %, respecto al de la 013);
- la **inclinación de celda** del diseño p90, p99 y máxima (°, con el lugar de la máxima; la de ``design.report``: la mayor tangente a las ocho
  vecinas, solo en las celdas con corte);
- un **aviso** (``des.pit_above_envelope``) si la superficie **ascendente** de las polilíneas supera la envolvente de la 013 en más de la tolerancia
  de la métrica (:data:`~design.envelopes.TOLERANCE_M`): el diseño vectorial no puede ser más empinado que la envolvente admisible.

**No cambia ninguna superficie** (ni la de la corta ni las de la 013). Con varios perfiles por sector se contrasta con el perfil base o, si no lo hay,
con el primero de la corta (el contraste es por un solo perfil). Por pasos (:func:`contrast_steps`, ``Progress``) y de una vez (:func:`contrast`).
Perezoso (RNF-001-03). Python puro con numpy."""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

from ..core.project.model import Progress
from ..gis.masks.compile import STEP_BUDGET_S
from . import benching, envelopes
from .compose import compose
from .model import BenchSense
from .pipeline import forward
from .pit_model import PitJob, PitMode
from .pit_surface import PitSurface
from .preview import Notice
from .report import max_tangents, padded_rows
from .zones import polygons_cells

__all__ = ["Contrast", "contrast", "contrast_steps"]

_PHASE = "pit_check013"


@dataclass(frozen=True, slots=True, eq=False)
class Contrast:
    """El contraste con la 013 (RF-018-27): ``design013`` (la superficie de la 013, de la forma de la rejilla), ``max_diff_m`` y su ``max_diff_place``,
    el volumen de corte de cada una (``volume_pit_m3``, ``volume_013_m3``), la diferencia (``volume_diff_m3`` = corta − 013; ``volume_diff_pct`` en %
    del de la 013, ``None`` si es 0), la inclinación de celda del diseño ``p90_deg``, ``p99_deg`` y ``max_deg`` con el lugar de la máxima
    (``max_place``; ``None`` sin corte), las celdas de la ascendente por encima de la envolvente (``above_cells``, ``above_max_m``,
    ``above_place``) y los ``notices``."""

    design013: np.ndarray
    max_diff_m: float
    max_diff_place: tuple[float, float] | None
    volume_pit_m3: float
    volume_013_m3: float
    volume_diff_m3: float
    volume_diff_pct: float | None
    p90_deg: float | None
    p99_deg: float | None
    max_deg: float | None
    max_place: tuple[float, float] | None
    above_cells: int
    above_max_m: float
    above_place: tuple[float, float] | None
    notices: tuple[Notice, ...]

    def __post_init__(self) -> None:
        self.design013.flags.writeable = False


def _place(job: PitJob, row: int, col: int) -> tuple[float, float]:
    return float(job.grid.west + (col + 0.5) * job.grid.dx), float(job.grid.north - (row + 0.5) * job.grid.dy)


def _seeds(job: PitJob) -> np.ndarray:
    """Las semillas de la corta como rejilla de cotas (``+inf``: sin semilla): el **fondo** de cada polígono a su cota (ascendente) o la **corona** del
    límite (descendente: las celdas de su borde, a su cota o a la del terreno)."""
    seed = np.full(job.grid.shape, np.inf)
    for source in job.sources:
        cells = polygons_cells([[source.ring]], job.grid)
        if job.mode is PitMode.UP:
            seed[cells] = source.level_m
            continue
        padded = np.pad(cells, 1)
        edge = cells & ~(padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:])
        level = job.start if source.level_m is None else np.full(job.grid.shape, source.level_m)
        pick = edge & np.isfinite(level)
        seed[pick] = level[pick]
    return seed


def _angles(job: PitJob, surface: np.ndarray, moved: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Las inclinaciones (°) de las celdas con corte y su posición ``(k, 2)`` de fila y columna."""
    rows, cols = surface.shape
    tangents = max_tangents(padded_rows(surface, 0, rows), job.grid.dx, job.grid.dy)[1:rows + 1, 1:cols + 1]
    pick = moved & np.isfinite(tangents)
    return np.degrees(np.arctan(tangents[pick])), np.argwhere(pick)


def _contrast_steps(job: PitJob, surface: PitSurface, budget_s: float) -> Iterator[Progress]:
    grid = job.grid
    profile = job.profile if job.profile is not None else job.bench_profiles[0]
    tan_face = math.tan(math.radians(profile.face_deg))
    slope = envelopes.SlopeField(profile.general_tan * profile.mesh_factor)
    way = envelopes.Direction.UP if job.mode is PitMode.UP else envelopes.Direction.DOWN
    yield Progress(_PHASE, 0, 1, "Contrastando con el escalonado de la 013…")
    found: envelopes.Envelope = yield from forward(
        envelopes.chamfer_steps(_seeds(job), grid, slope, way, name=job.request.name, budget_s=budget_s))
    domain = surface.enclosure
    envelope = np.where(domain, found.grid, np.nan)
    stairs = benching.bench_cut(envelope, profile.height_m, tan_face, profile.berm_m, profile.anchor_m)
    trim: benching.Trim = yield from forward(benching.final_trim_steps(
        stairs, envelope, grid, tan_face, profile.mesh_factor, BenchSense.CUT, name=job.request.name, budget_s=budget_s))
    allowed = job.cut_allowed & ~job.untouchable & domain
    design013 = compose(job.start, trim.grid, allowed, BenchSense.CUT)
    yield Progress(_PHASE, 0, 1, "Midiendo el contraste…")
    with np.errstate(invalid="ignore"):
        cut013 = np.isfinite(design013) & (design013 < job.start)
        moved = surface.cut_cells | cut013
        both = moved & np.isfinite(design013) & np.isfinite(surface.surface)
        diff = np.where(both, np.abs(surface.surface - design013), 0.0)
    where = np.unravel_index(int(np.argmax(diff)), diff.shape)
    max_diff = float(diff[where])
    diff_place = _place(job, int(where[0]), int(where[1])) if both.any() else None
    volume013 = math.fsum(np.where(cut013, job.start - design013, 0.0).sum(axis=1).tolist()) * grid.cell_area
    volume_pit = float(surface.cut_m3)
    pct = None if volume013 <= 0.0 else (volume_pit - volume013) / volume013 * 100.0
    yield Progress(_PHASE, 0, 1, "Midiendo la inclinación…")
    angle, cells = _angles(job, surface.surface, surface.cut_cells)
    p90 = p99 = top = place = None
    if angle.size:
        p90, p99 = (float(v) for v in np.percentile(angle, [90.0, 99.0]))
        at = int(np.argmax(angle))
        top, place = float(angle[at]), _place(job, int(cells[at, 0]), int(cells[at, 1]))
    above_cells, above_max, above_place = 0, 0.0, None
    notices: tuple[Notice, ...] = ()
    if job.mode is PitMode.UP:
        with np.errstate(invalid="ignore"):
            excess = np.where(np.isfinite(surface.stepped) & np.isfinite(envelope), surface.stepped - envelope, -np.inf)
        over = excess > envelopes.TOLERANCE_M
        above_cells = int(np.count_nonzero(over))
        if above_cells:
            at2 = np.unravel_index(int(np.argmax(excess)), excess.shape)
            above_max, above_place = float(excess[at2]), _place(job, int(at2[0]), int(at2[1]))
            notices = (Notice("des.pit_above_envelope", {"name": job.request.name, "count": above_cells, "excess": above_max,
                                                        "x": above_place[0], "y": above_place[1]}),)
    result = Contrast(design013, max_diff, diff_place, volume_pit, volume013, volume_pit - volume013, pct, p90, p99, top, place, above_cells,
                      above_max, above_place, notices)
    yield Progress(_PHASE, 1, 1, "Contraste calculado", result=result)


def contrast_steps(job: PitJob, surface: PitSurface, *, budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """El contraste de la corta de ``job`` con su ``surface`` y la 013 (RF-018-27), por pasos de ``budget_s`` como mucho: el último ``Progress`` (fase
    ``pit_check013``) lleva el :class:`Contrast`. Cerrar el generador a mitad no deja nada; ninguna entrada se modifica."""
    return _contrast_steps(job, surface, budget_s)


def contrast(job: PitJob, surface: PitSurface) -> Contrast:
    """:func:`contrast_steps` hasta el final, sin pasos."""
    result = None
    for step in contrast_steps(job, surface):
        if step.result is not None:
            result = step.result
    assert result is not None
    return result  # type: ignore[no-any-return]
