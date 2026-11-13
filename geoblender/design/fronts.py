# SPDX-License-Identifier: GPL-3.0-or-later
"""«Solo relleno»: un tendido que no corta (spec 014, T29; HU-014-6; RF-014-22 a RF-014-25; plan
014 A12, §5.3.1; DIS-17; errores 65 y 66).

- :func:`water_sheets` (RF-014-24; D-10): las **láminas de agua** de una capa de polígonos con su
  campo de cota (:class:`WaterSheets`: cada celda con el centro dentro de un polígono, D-16 de la
  013, lleva su cota; ``NaN`` fuera), con sus rechazos: una capa que no es de polígonos
  (``des.layer_not_polygons``), un campo que no tiene o que no es numérico
  (``des.quarry_layer_field``), una cota que falta o no es un número finito
  (``des.fill_only_water_level``) y dos láminas que se solapan (``des.fill_only_water_overlap``):
  no se elige ninguna cota por la persona.
- :func:`with_water` (RF-014-24; A12): el **terreno de partida del diseño** ``z'``, solo en
  memoria: el terreno ``z`` con la cota de la lámina dentro de sus polígonos donde el terreno queda
  por debajo de ella o no tiene dato. Donde el terreno registrado queda por encima de la cota (la
  orilla seca que cae dentro del polígono), ``z' = z``: la lámina no rebaja el terreno. El terreno
  registrado no cambia: es una rejilla nueva.
- :func:`untouchable_zones`: las zonas de las restricciones **intocables** de las máscaras de la 012
  (ya con su resguardo, ADR-0028), con su nombre (:class:`UntouchableZone`).
- :func:`fill_only_steps` (RF-014-22 a RF-014-24; A12; T55, hallazgo F-17): el **diseño «solo
  relleno»** (:class:`FillOnlyJob` → :class:`FillOnlyOutcome`): el escalonado en relleno de la 013
  (``pipeline.design_compute_steps``) de la envolvente del trabajo sobre ``z'``, compuesto **solo en
  el relleno admitido** de la 012 (``fill_allowed``: dentro del límite legal, sin intocables ni
  zonas sin relleno; la franja de solo relleno de fuera del límite, que el escalonado de la 013 sí
  rellena, no entra: el límite es la frontera del pie). La lámina solo es la partida del relleno
  (decisión de Samuel, 13/11/2026): la superficie ``S`` es la compuesta donde sube de ``z'`` y el
  **terreno registrado** ``z`` en las demás celdas —fuera del relleno admitido, en los intocables
  y en la balsa que el escalonado no sube de su cota, que no se rellena—, nunca la cota de la
  lámina (``pipeline.DesignJob.ground``); y el informe, las bermas y las cifras de la 013 son los de
  ``S`` frente al terreno registrado, la **cubicación** con láminas (lo que cubre el relleno en la
  balsa, el agua incluida, cuenta como terraplén). Un aviso por cada lámina que es la partida en
  celdas fuera del relleno admitido o en un intocable (``des.fill_only_water_outside``: allí no se
  rellena).
- :func:`check_fill_only` (RF-014-25; A12): los **rechazos**, sobre ``S`` y antes de dar nada: un
  movimiento de más del espesor mínimo de la 012 frente al terreno registrado en una celda de un
  intocable (``des.fill_only_untouchable``, nombrando el intocable y su volumen; error 65; una
  lámina sobre él no es su partida) o un corte de :data:`FILL_ONLY_CUT_LIMIT_M3` o más frente al
  terreno registrado, ``Σ máx(z − S, 0) · área de celda`` (``des.fill_only_cuts``, con el volumen;
  DIS-17). Con :func:`fill_only_steps` no se dan por construcción: son la red que impide crear un
  diseño «solo relleno» que corte o toque un intocable.
- :func:`fill_only_figures`: la cifra propia, ``des.fill_only_cut_m3`` (las demás son las del
  escalonado de la 013).

Python puro con numpy (nivel 8): no importa ``reserves`` ni ``bl``; no escribe nada.
"""

from __future__ import annotations

import math
from collections.abc import Generator, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace

import numpy as np

from ..core.project.model import Progress
from ..core.provenance.figures import FigureSpec
from ..gis.grid import Grid
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.messages import format_value
from ..gis.vector import FeatureLayer
from . import provenance
from .messages import DesignError
from .model import BenchSense, LayerField
from .pipeline import DesignJob, DesignOutcome, design_compute_steps, forward
from .preview import Notice
from .quarry import _GEOMETRY_FIELD, _KINDS_ES, _NO_VALUE, _level_column
from .report import _thickness, moved_cells
from .zones import _paint, _polygon_spans

__all__ = [
    "FILL_ONLY_CUT_LIMIT_M3",
    "FILL_ONLY_PHASE",
    "UNTOUCHABLE_TYPE",
    "FillOnlyJob",
    "FillOnlyOutcome",
    "UntouchableZone",
    "WaterSheets",
    "check_fill_only",
    "fill_only_figures",
    "fill_only_steps",
    "untouchable_zones",
    "water_sheets",
    "with_water",
]

FILL_ONLY_CUT_LIMIT_M3 = 1.0
"""El corte de un diseño «solo relleno» que ya se rechaza (m³; RF-014-22 y RF-014-25, DIS-17: el
corte tiene que ser menor de 1 m³; plan A12: ``Σ máx(z − S, 0) ≥ 1 m³``)."""
UNTOUCHABLE_TYPE = "untouchable"
"""El tipo de restricción de la 012 (valor de ``ConstraintType``) de los intocables (RF-014-25)."""
FILL_ONLY_PHASE = "fill_only"
"""La fase de los pasos propios de «solo relleno» (los del escalonado son los de la 013)."""
_CUT_FIGURE = provenance.FILL_ONLY_FIGURES[0].key
_VOLUME_FIELD = "volumen (m³)"
_WATER_OUTSIDE = "des.fill_only_water_outside"
"""El aviso de una lámina que es la partida fuera del relleno admitido o en un intocable (T55)."""


def _same_shape(name: str, values: np.ndarray, shape: tuple[int, ...]) -> None:
    """``ValueError`` (error del programa) si ``values`` no es de la forma de la rejilla."""
    if values.shape != shape:
        raise ValueError(f"{name} es de {values.shape} celdas, no de las {shape} de la rejilla")


# --- Las láminas de agua (RF-014-24) -------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class WaterSheets:
    """Las **láminas de agua** (RF-014-24, D-10) de la capa ``layer`` y su campo de cota ``field``:
    ``grid`` (m, float64, nueva: la cota de la lámina en cada celda con el centro dentro de una,
    D-16 de la 013; ``NaN`` fuera), ``owner`` (int32: el orden de la lámina en la capa, de 1 a n; 0
    fuera) y, por lámina en el orden de la capa, su número (``fids``), su cota (``levels``, m) y sus
    celdas (``cells``); ``cell_area_m2``, el área de una celda de la rejilla."""

    layer: str
    field: str
    grid: np.ndarray
    owner: np.ndarray
    fids: tuple[int, ...]
    levels: tuple[float, ...]
    cells: tuple[int, ...]
    cell_area_m2: float

    @property
    def area_m2(self) -> float:
        """El área de las láminas (m²): sus celdas por el área de celda."""
        return sum(self.cells) * self.cell_area_m2


def _water_level(value: object, fid: int, source: LayerField) -> float:
    """La cota ``value`` de la lámina ``fid`` como float; ``des.fill_only_water_level`` si falta o
    no es un número finito (RF-014-24: no se supone ninguna)."""
    number: float | None = None
    if value is not None and not isinstance(value, bool):
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            number = None
    if number is not None and math.isfinite(number):
        return number
    if value is None:
        shown: object = _NO_VALUE
    elif number is not None:
        shown = str(number)
    else:
        shown = value
    raise DesignError("des.fill_only_water_level",
                      obj=f"Lámina de agua {fid} de la capa «{source.layer}»", field=source.field,
                      value=shown, layer=source.layer, polygon=fid)


def water_sheets(layer: FeatureLayer, source: LayerField, geometry: Grid) -> WaterSheets:
    """**RF-014-24** (D-10): las láminas de agua de la capa de polígonos ``layer`` (sus entidades;
    ``source`` da su nombre en el proyecto y el campo de la cota, m) en la rejilla ``geometry``:
    cada celda con el centro dentro de una lámina (D-16 de la 013; las partes de una entidad se
    unen) lleva su cota (:class:`WaterSheets`). Solo lee.

    Rechazos (``DesignError``, sin elegir ninguna cota por la persona), en el orden de la capa y, en
    cada lámina, primero su cota: una capa que no es de polígonos (``des.layer_not_polygons``); un
    campo que la capa no tiene o que no es numérico (``des.quarry_layer_field``); una cota que falta
    o no es un número finito (``des.fill_only_water_level``, con la capa, la lámina, el campo y el
    valor); una lámina que pisa celdas de otra anterior (``des.fill_only_water_overlap``, con las
    dos y las celdas comunes). Cada lámina cuesta su caja, no la rejilla entera."""
    if layer.kind != "polygon":
        raise DesignError("des.layer_not_polygons", obj=f"Capa de polígonos «{source.layer}»",
                          field=_GEOMETRY_FIELD, value=_KINDS_ES.get(layer.kind, layer.kind),
                          layer=source.layer)
    column = _level_column(layer, source)
    grid = np.full(geometry.shape, np.nan)
    owner = np.zeros(geometry.shape, dtype=np.int32)
    levels: list[float] = []
    cells: list[int] = []
    for index, (fid, parts) in enumerate(zip(layer.fids, layer.parts, strict=True), start=1):
        level = _water_level(layer.values[column][index - 1], fid, source)
        top, left, block = _paint(_polygon_spans(parts, geometry), geometry.nrows,
                                  geometry.ncols)
        window = (slice(top, top + block.shape[0]), slice(left, left + block.shape[1]))
        taken = owner[window][block]
        taken = taken[taken > 0]
        if taken.size:
            first = int(taken.min())
            raise DesignError("des.fill_only_water_overlap", obj=f"Capa «{source.layer}»",
                              field=_GEOMETRY_FIELD, value=layer.fids[first - 1],
                              layer=source.layer, other=fid,
                              cells=int(np.count_nonzero(taken == first)))
        owner[window][block] = index
        grid[window][block] = level
        levels.append(level)
        cells.append(int(np.count_nonzero(block)))
    return WaterSheets(source.layer, source.field, grid, owner, tuple(layer.fids), tuple(levels),
                       tuple(cells), geometry.cell_area)


def with_water(start: np.ndarray, sheets: WaterSheets | None) -> np.ndarray:
    """**RF-014-24** (A12): el terreno de partida del diseño ``z'`` (m, float64, una rejilla
    **nueva**; el terreno ``start`` no se modifica): dentro de las láminas ``sheets``, su cota donde
    el terreno queda por debajo de ella o no tiene dato; en las demás celdas, el terreno bit a bit
    (también en la orilla seca dentro de una lámina, por encima de su cota: el agua no la rebaja).
    Sin láminas (``None``), una copia del terreno. ``ValueError`` si ``start`` no es una rejilla 2D
    de la forma de las láminas."""
    values = np.asarray(start, dtype=np.float64)
    if values.ndim != 2:
        raise ValueError(f"el terreno es una rejilla 2D, no de forma {values.shape}")
    found = values.copy()
    if sheets is None:
        return found
    _same_shape("el terreno", values, sheets.grid.shape)
    with np.errstate(invalid="ignore"):
        rise = np.isfinite(sheets.grid) & ~(values >= sheets.grid)
    found[rise] = sheets.grid[rise]
    return found


# --- Los intocables (RF-014-25) ------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class UntouchableZone:
    """Un intocable de la 012 para el rechazo de RF-014-25: su ``name`` (el que se enseña) y su
    zona en la rejilla (``mask``, ya con su resguardo)."""

    name: str
    mask: np.ndarray


def untouchable_zones(masks: object, names: Mapping[str, str] | None = None
                      ) -> tuple[UntouchableZone, ...]:
    """Los intocables de las máscaras ``masks`` (un ``MaskSet``: las restricciones de tipo
    :data:`UNTOUCHABLE_TYPE` con zona en ellas, por orden de código), cada uno con su zona (máscara
    nueva de la rejilla de las máscaras, ADR-0028) y su nombre: el de ``names`` (código → nombre)
    o, si no lo tiene, su código. Solo lee."""
    shown = {} if names is None else dict(names)
    shape = masks.grid.shape  # type: ignore[attr-defined]
    found = []
    for code, ctype in sorted(getattr(masks, "ctypes", {}).items()):
        if ctype != UNTOUCHABLE_TYPE:
            continue
        try:
            runs = masks.zone(code)  # type: ignore[attr-defined]
        except KeyError:
            continue
        found.append(UntouchableZone(shown.get(code, code), runs.mask(shape)))
    return tuple(found)


# --- Los rechazos (RF-014-25) --------------------------------------------------------------------


def _check_untouchables(surface: np.ndarray, terrain: np.ndarray,
                        untouchables: Sequence[UntouchableZone], geometry: Grid,
                        thickness: float) -> None:
    """``des.fill_only_untouchable`` con el primer intocable en que ``surface`` se mueve más que
    el espesor mínimo frente al terreno registrado ``terrain`` (T55: una lámina sobre él no es su
    partida), nombrándolo con el volumen de ese movimiento."""
    if not untouchables:
        return
    moved = moved_cells(terrain, surface, thickness)
    for zone in untouchables:
        inside = moved & zone.mask
        if inside.any():
            volume = float(np.abs(surface[inside] - terrain[inside]).sum()) * geometry.cell_area
            raise DesignError("des.fill_only_untouchable", obj=f"Intocable «{zone.name}»",
                              field=_VOLUME_FIELD, value=round(volume, 3), constraint=zone.name)


def _cut_m3(name: str, surface: np.ndarray, terrain: np.ndarray, geometry: Grid) -> float:
    """El corte frente al terreno registrado, ``Σ máx(z − S, 0) · área de celda`` en las celdas con
    dato en las dos (m³); ``des.fill_only_cuts`` con el volumen si llega a
    :data:`FILL_ONLY_CUT_LIMIT_M3`."""
    with np.errstate(invalid="ignore"):
        below = terrain - surface
        below = below[below > 0.0]
    cut = float(below.sum()) * geometry.cell_area
    if cut >= FILL_ONLY_CUT_LIMIT_M3:
        raise DesignError("des.fill_only_cuts", obj=f"Diseño «solo relleno» «{name}»",
                          field=_CUT_FIGURE, value=round(cut, 2))
    return cut


def _checked(name: str, values: np.ndarray, shape: tuple[int, ...]) -> np.ndarray:
    found = np.asarray(values, dtype=np.float64)
    _same_shape(name, found, shape)
    return found


def check_fill_only(name: str, surface: np.ndarray, terrain: np.ndarray,
                    untouchables: Sequence[UntouchableZone], geometry: Grid,
                    min_thickness_m: float) -> float:
    """**RF-014-25** (A12; T55): los rechazos del diseño «solo relleno» ``name`` con la superficie
    ``surface`` (``S``) y el terreno registrado ``terrain`` (``z``), en la rejilla ``geometry``;
    devuelve su corte (m³). Los dos se miden frente al terreno registrado: una lámina de agua solo
    es la partida del relleno, no el terreno de un intocable.

    - Un movimiento de más de ``min_thickness_m`` (el espesor mínimo de la 012) frente a ``z`` en
      una celda de un intocable de ``untouchables`` (error 65): ``des.fill_only_untouchable``
      nombrando el primero, en su orden, con el volumen de ese movimiento (m³).
    - Un corte de :data:`FILL_ONLY_CUT_LIMIT_M3` o más frente a ``z``, ``Σ máx(z − S, 0) · área de
      celda`` en las celdas con dato en las dos (DIS-17): ``des.fill_only_cuts`` con el volumen.

    Solo lee. ``ValueError`` (error del programa) si una rejilla o una zona no es de la forma de la
    rejilla o el espesor mínimo no es un número finito ≥ 0."""
    shape = geometry.shape
    design = _checked("la superficie", surface, shape)
    ground = _checked("el terreno", terrain, shape)
    for zone in untouchables:
        _same_shape(f"el intocable «{zone.name}»", np.asarray(zone.mask), shape)
    _check_untouchables(design, ground, untouchables, geometry, _thickness(min_thickness_m))
    return _cut_m3(name, design, ground, geometry)


def _water_outside(sheets: WaterSheets | None, start: np.ndarray, terrain: np.ndarray,
                   masks: object, zones: Sequence[UntouchableZone]) -> tuple[Notice, ...]:
    """**RF-014-23, RF-014-24** (T55, hallazgo F-17): un aviso ``des.fill_only_water_outside`` por
    cada lámina de ``sheets``, en el orden de su capa, que es la partida ``start`` (``z'``: el
    terreno ``terrain`` queda por debajo de su cota o no tiene dato) en celdas fuera del relleno
    admitido de ``masks`` o en un intocable de ``zones``, con esas celdas y su área (m²): allí no se
    rellena y la superficie queda en el terreno registrado. Sin láminas, ninguno. Solo lee."""
    if sheets is None:
        return ()
    with np.errstate(invalid="ignore"):
        wet = np.isfinite(start) & ~(start == terrain)
    barred = ~np.asarray(masks.fill_allowed(), dtype=bool)  # type: ignore[attr-defined]
    for zone in zones:
        barred |= np.asarray(zone.mask, dtype=bool)
    counts = np.bincount(sheets.owner[wet & barred], minlength=len(sheets.fids) + 1)
    return tuple(
        Notice(_WATER_OUTSIDE, {"layer": sheets.layer, "polygon": fid, "cells": int(counts[index]),
                                "area": float(counts[index]) * sheets.cell_area_m2})
        for index, fid in enumerate(sheets.fids, start=1) if counts[index])


def fill_only_figures(name: str, cut_m3: float) -> tuple[FigureSpec, ...]:
    """La cifra CALCULADO propia del diseño «solo relleno» ``name`` (plan 014 §5.2.3; RF-014-22),
    con el ámbito de ``provenance.quarry_figure_scope``: su corte frente al terreno registrado
    (``des.fill_only_cut_m3``, m³). Las demás son las del escalonado de la 013."""
    return (FigureSpec(_CUT_FIGURE, float(cut_m3), "m3",
                       scope=provenance.quarry_figure_scope(name)),)


# --- El diseño «solo relleno» (RF-014-22, RF-014-23; A12) ----------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class _FillOnlyMasks:
    """Las máscaras de la 012 para el escalonado de «solo relleno» (RF-014-23): solo el relleno
    admitido (``fill_allowed``); ni corte ni la franja de solo relleno de fuera del límite legal,
    que es la frontera del pie."""

    masks: object

    def cut_allowed(self) -> np.ndarray:
        return np.zeros_like(self.fill_allowed())

    def fill_allowed(self) -> np.ndarray:
        return np.asarray(self.masks.fill_allowed(), dtype=bool)  # type: ignore[attr-defined]

    def fill_strip(self) -> np.ndarray:
        return np.zeros_like(self.fill_allowed())


@dataclass(frozen=True, slots=True, eq=False)
class FillOnlyJob:
    """Lo que necesita calcular un diseño «solo relleno», ya leído (como ``DesignJob`` de la 013,
    plan 014 §5.3.1): el escalonado de la 013 (``design``: su petición **en relleno**, la
    envolvente, el terreno registrado ``start``, las máscaras de la 012, los sectores, los perfiles,
    el ancla, el espesor mínimo…), las láminas de agua (``water``; ninguna, sin láminas) y los
    intocables (``untouchables``; ``None``, los de las máscaras con su código por nombre,
    :func:`untouchable_zones`)."""

    design: DesignJob
    water: WaterSheets | None = None
    untouchables: tuple[UntouchableZone, ...] | None = None


@dataclass(frozen=True, slots=True, eq=False)
class FillOnlyOutcome:
    """Un diseño «solo relleno» calculado: el terreno de partida del diseño (``start``, ``z'``,
    float64 nueva; las láminas solo en memoria), la superficie (``surface``, ``S``, float64 nueva:
    la compuesta donde sube de ``z'`` y el terreno registrado en las demás celdas, T55), el
    escalonado de la 013 sobre ``z'`` (``design``: su superficie, que es ``S``, y su informe, sus
    bermas y sus cifras frente al terreno registrado), las celdas en que la lámina es la partida
    (``water_cells``), el corte frente al terreno registrado (``cut_m3``, <
    :data:`FILL_ONLY_CUT_LIMIT_M3`), las cifras CALCULADO (las de la 013 y
    ``des.fill_only_cut_m3``), el ``message`` de la operación y los avisos propios (``notices``:
    ``des.fill_only_water_outside``, uno por lámina que cae fuera del relleno admitido o en un
    intocable; los del escalonado van en su informe)."""

    start: np.ndarray
    surface: np.ndarray
    design: DesignOutcome
    water_cells: int
    cut_m3: float
    figures: tuple[FigureSpec, ...]
    message: str
    notices: tuple[Notice, ...] = ()

    @property
    def grid(self) -> np.ndarray:
        """La superficie del diseño (``surface``)."""
        return self.surface


def fill_only_steps(job: FillOnlyJob, *, budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**A12** (RF-014-22 a RF-014-25): el diseño «solo relleno» de ``job`` por pasos de ``budget_s``
    como mucho; el último ``Progress`` lleva el :class:`FillOnlyOutcome`.

    El terreno de partida ``z'`` (:func:`with_water`) y los avisos de las láminas que caen fuera
    del relleno admitido o en un intocable; el escalonado en relleno de la 013 de la envolvente
    sobre ``z'`` con solo el relleno admitido de la 012 (sin la franja de fuera del límite), medido
    frente al terreno registrado ``z`` (``DesignJob.ground``): ``S`` es la compuesta donde sube de
    ``z'`` y ``z`` en las demás celdas (T55; nunca por debajo del terreno: ``S = máx(z, S)``); y
    los rechazos de :func:`check_fill_only`, al avanzar, antes de dar el resultado. Los rechazos del
    escalonado de la 013 (un perfil, un sector o un ancla), también al avanzar.

    Al llamar, ``ValueError`` (error del programa) si el escalonado no es en relleno o el terreno,
    las láminas o un intocable no son de la forma de la rejilla. Ninguna entrada se modifica; no se
    escribe nada."""
    design = job.design
    if BenchSense(design.request.sense) is not BenchSense.FILL:
        raise ValueError("«solo relleno» escalona en relleno (RF-014-22), no en "
                         f"«{design.request.sense}»")
    shape = design.geometry.shape
    terrain = _checked("el terreno", design.start, shape)
    if job.water is not None:
        _same_shape("las láminas de agua", job.water.grid, shape)
    zones = (untouchable_zones(design.masks) if job.untouchables is None
             else tuple(job.untouchables))
    for zone in zones:
        _same_shape(f"el intocable «{zone.name}»", np.asarray(zone.mask), shape)
    return _fill_only_steps(job, terrain, zones, budget_s)


def _fill_only_steps(job: FillOnlyJob, terrain: np.ndarray, zones: tuple[UntouchableZone, ...],
                     budget_s: float) -> Generator[Progress, None, None]:
    design, name = job.design, job.design.request.name
    geometry = design.geometry
    yield Progress(FILL_ONLY_PHASE, 0, 1, "Tomando las láminas de agua como terreno de partida…")
    start = with_water(terrain, job.water)
    with np.errstate(invalid="ignore"):
        water_cells = int(np.count_nonzero(np.isfinite(start) & ~(start == terrain)))
    notices = _water_outside(job.water, start, terrain, design.masks, zones)
    stepped: DesignOutcome = yield from forward(design_compute_steps(
        replace(design, start=start, masks=_FillOnlyMasks(design.masks), ground=terrain),
        budget_s=budget_s))
    yield Progress(FILL_ONLY_PHASE, 0, 1, "Comprobando que el diseño solo rellena…")
    surface = np.fmax(terrain, np.asarray(stepped.design, dtype=np.float64))
    _check_untouchables(surface, terrain, zones, geometry, _thickness(design.min_thickness_m))
    yield Progress(FILL_ONLY_PHASE, 0, 1, "Midiendo el corte…")
    cut = _cut_m3(name, surface, terrain, geometry)
    figures = (*stepped.figures, *fill_only_figures(name, cut))
    text = (f"Diseño «solo relleno» «{name}» calculado: terraplén "
            f"{format_value(round(stepped.report.fill_m3, 1))} m³, corte "
            f"{format_value(round(cut, 2))} m³ y {stepped.berms.count} bermas")
    if water_cells:
        text += f"; láminas de agua como terreno de partida en {water_cells} celdas"
    yield Progress(FILL_ONLY_PHASE, 1, 1, text, result=FillOnlyOutcome(
        start, surface, stepped, water_cells, cut, figures, text, notices))
