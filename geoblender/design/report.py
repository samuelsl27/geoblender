# SPDX-License-Identifier: GPL-3.0-or-later
"""El informe de un diseño: cifras y avisos (spec 013, T12; HU-013-2, HU-013-6; RF-013-30,
RF-013-17; plan 013 A11, D-9, D-13, D-25; CE-013-07).

:func:`report_steps` mide la superficie de diseño frente a la de partida y da, por pasos, el
:class:`DesignReport`:

- **Volúmenes** (:func:`volumes`; A7 de la 012): con ``d = partida − diseño`` en las celdas con dato
  en las dos, desmonte donde ``d > e`` y terraplén donde ``−d > e`` (``e``, el espesor mínimo de
  verificación de la 012, ``res.verify.min_thickness_m``), **con todo su espesor**: lo que no pasa el
  umbral no cuenta; lo que pasa, entero. El área con movimiento es la de esas celdas; las celdas sin
  dato en alguna de las dos se cuentan aparte. Volúmenes y áreas con el área exacta de la celda.
- **Inclinación** (D-13): la de cada celda es la **mayor a sus 8 vecinos** con dato (cuatro pares
  desplazados atribuidos a las dos celdas), la misma de la que protege la envolvente; p90, p99 y
  máxima (°) sobre las celdas **con movimiento** con ``np.percentile`` (interpolación lineal) y el
  lugar del máximo en coordenadas **absolutas** de float64 (:class:`CellPlace`). Se mide contra todas
  las vecinas, también las que no se movieron: el diseño que acaba en pared contra el terreno tiene
  esa inclinación.
- **Salto en el borde de lo prohibido** (D-9): la superficie de diseño deja lo no admitido (``allowed``
  falso) exactamente como estaba; el **salto** es el mayor escalón (m) entre una celda con movimiento
  y una vecina de lado no admitida, y ``edge_cells`` cuántas celdas con movimiento tocan lo no
  admitido. Sin ningún borde, 0 m (no hay escalón creado).
- **Avisos** (:class:`~design.preview.Notice`, con código de ``design.messages``): sin movimiento;
  movimiento en el borde de la rejilla (el resultado queda cortado por ella: errores 10, 17, 56 y 66);
  inclinación por encima de la cara más la tolerancia de cara; desmonte o terraplén que superan en más
  del umbral de aviso (veces) los de la operación del mismo tipo y nombre de la revisión congelada más
  reciente de la versión (D-25; sin ella, el aviso no se da y una nota lo dice); la regularización
  entre sectores que bajó la envolvente más que la tolerancia (:class:`Lowering`, spec 0.4; F-1:
  el escalonado en corte puede quedar por debajo de la envolvente registrada); sectores con la
  búsqueda de intocables pendiente (RF-013-06) y perfiles que la rejilla no resuelve (RF-013-20).

**Ninguna cifra NaN ni infinita** (RF-013-17): lo que no se puede dar (inclinaciones sin ninguna
celda con movimiento) es ``None`` y, si procede, un aviso. Las celdas con dato infinito se tratan
como sin dato.

**Por pasos** (D-20): una unidad por banda de filas en cada una de las dos pasadas (volúmenes;
inclinación y salto) y una para los percentiles; ninguna entrada se modifica y cerrar el generador a
mitad no deja nada. La banda no cambia las cifras: las sumas, a ≤ 10⁻¹² relativo; el resto, ni un
bit. Python puro (nivel 8), con numpy; no importa ``reserves``.
"""

from __future__ import annotations

import math
from collections.abc import Generator, Iterator, Sequence
from dataclasses import dataclass

import numpy as np

from ..core.project.model import Progress
from ..gis.grid import Grid
from ..gis.masks.compile import STEP_BUDGET_S
from .model import BenchProfile
from .preview import Notice
from .seeds import pace_progress

__all__ = [
    "REPORT_CELLS_PER_UNIT",
    "CellPlace",
    "DesignReport",
    "Lowering",
    "Previous",
    "Volumes",
    "max_tangents",
    "moved_cells",
    "padded_rows",
    "report_steps",
    "volumes",
]

REPORT_CELLS_PER_UNIT = 200_000
"""Las celdas de una unidad de trabajo del informe (una banda de filas)."""

_DIAGONAL_PAIRS = ((0, 1), (1, 0), (1, 1), (1, -1))
"""Los cuatro pares de vecinas desplazados (fila, columna) que cubren las 8 vecinas."""
_SIDES = ((-1, 0), (1, 0), (0, -1), (0, 1))
"""Las cuatro vecinas de lado (el borde de lo no admitido)."""


# --- Lo que se entrega -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CellPlace:
    """Una celda de la rejilla: ``row`` (0 al norte), ``col`` (0 al oeste) y su centro **absoluto**
    ``x``, ``y`` (m, float64)."""

    row: int
    col: int
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class Previous:
    """Las cifras de la operación del mismo tipo y nombre de la revisión congelada más reciente de
    la versión (D-25), con las que se compara el desmonte y el terraplén: el nombre de la
    ``operation``, el código de la ``revision`` y su ``cut_m3`` y ``fill_m3``."""

    operation: str
    revision: str
    cut_m3: float
    fill_m3: float

    def __post_init__(self) -> None:
        for name in ("cut_m3", "fill_m3"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} de la revisión anterior debe ser un volumen finito ≥ 0, "
                                 f"no {getattr(self, name)!r}")
            object.__setattr__(self, name, value)


@dataclass(frozen=True, slots=True)
class Lowering:
    """Lo que bajó la regularización entre sectores (RF-013-26, RF-013-30; spec 0.4): las ``cells``
    que bajaron más que la tolerancia de la métrica, el descenso máximo ``drop_m`` (m), el talud
    (``slope_deg``, °) con que se regularizó —el general más empinado de los sectores implicados— y
    los nombres de los ``sectors`` donde bajó alguna celda (puede ser ninguno si las celdas
    bajadas no tienen sector). Con ``cells`` 0 no hay nada que avisar."""

    cells: int
    drop_m: float
    slope_deg: float
    sectors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.cells, bool) or not isinstance(self.cells, int) or self.cells < 0:
            raise ValueError(f"las celdas bajadas son un entero ≥ 0, no {self.cells!r}")
        drop, slope = float(self.drop_m), float(self.slope_deg)
        if not math.isfinite(drop) or drop < 0.0:
            raise ValueError(f"el descenso máximo (drop_m) debe ser un número finito ≥ 0, no "
                             f"{self.drop_m!r}")
        if not math.isfinite(slope):
            raise ValueError(f"el talud de la regularización (slope_deg) debe ser un número "
                             f"finito, no {self.slope_deg!r}")
        object.__setattr__(self, "drop_m", drop)
        object.__setattr__(self, "slope_deg", slope)
        if isinstance(self.sectors, str):
            raise ValueError("los sectores de la regularización son una lista de nombres, no un "
                             "texto")
        object.__setattr__(self, "sectors", tuple(self.sectors))


@dataclass(frozen=True, slots=True)
class Volumes:
    """El movimiento de tierras de una superficie frente a otra con un espesor mínimo: desmonte y
    terraplén (m³) y sus celdas, el área con movimiento (m²) y las celdas sin dato en alguna de las
    dos (con su área, m²)."""

    cut_m3: float
    fill_m3: float
    cut_cells: int
    fill_cells: int
    moved_area_m2: float
    nodata_cells: int
    nodata_area_m2: float

    @property
    def moved_cells(self) -> int:
        """Las celdas con movimiento (el corte y el relleno no comparten celda)."""
        return self.cut_cells + self.fill_cells


@dataclass(frozen=True, slots=True, eq=False)
class DesignReport:
    """El informe de un diseño (RF-013-30): los volúmenes de :class:`Volumes` con el
    ``min_thickness_m`` usado; la inclinación de celda p90, p99 y máxima (°; ``None`` si ninguna
    celda con movimiento tiene inclinación) y el lugar de la máxima; el salto máximo en el borde de
    lo no admitido (``edge_step_max_m``, m) y las celdas con movimiento que lo tocan
    (``edge_cells``); y los ``notices`` (avisos y notas) en el orden en que se enseñan."""

    cut_m3: float
    fill_m3: float
    cut_cells: int
    fill_cells: int
    moved_area_m2: float
    nodata_cells: int
    nodata_area_m2: float
    min_thickness_m: float
    slope_p90_deg: float | None
    slope_p99_deg: float | None
    slope_max_deg: float | None
    slope_max_at: CellPlace | None
    edge_step_max_m: float
    edge_cells: int
    notices: tuple[Notice, ...]

    @property
    def moved_cells(self) -> int:
        """Las celdas con movimiento."""
        return self.cut_cells + self.fill_cells

    def lines(self, language: str = "es") -> tuple[str, ...]:
        """Todos los avisos y notas, línea a línea, en ``language``."""
        return tuple(notice.text(language) for notice in self.notices)

    def warnings(self, language: str = "es") -> tuple[str, ...]:
        """Solo los avisos, en ``language``."""
        return tuple(notice.text(language) for notice in self.notices
                     if notice.severity == "warning")


# --- Comprobaciones ----------------------------------------------------------------------------


def _surface(value: np.ndarray, name: str, geometry: Grid) -> np.ndarray:
    """``value`` como array 2D de float64 de la forma de la rejilla (sin copiar si ya lo es)."""
    found = np.asarray(value, dtype=np.float64)
    if found.ndim != 2 or found.shape != geometry.shape:
        raise ValueError(f"{name} es una rejilla de la forma {geometry.shape}, no de forma "
                         f"{found.shape}")
    return found


def _thickness(value: float) -> float:
    """El espesor mínimo (m): finito y ≥ 0."""
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"el espesor mínimo debe ser un número finito ≥ 0, no {value!r}")
    return number


def _units(cells_per_unit: int) -> int:
    if cells_per_unit < 1:
        raise ValueError("las celdas por unidad deben ser al menos 1")
    return int(cells_per_unit)


# --- Volúmenes (A7 de la 012) ------------------------------------------------------------------


def moved_cells(start: np.ndarray, design: np.ndarray, min_thickness_m: float) -> np.ndarray:
    """Las celdas con movimiento: con dato en las dos superficies y una diferencia mayor que
    ``min_thickness_m`` (m) en valor absoluto (la misma máscara del informe y la que pide
    ``berms_steps`` en ``moved``). Una máscara booleana nueva."""
    base = np.asarray(start, dtype=np.float64)
    other = np.asarray(design, dtype=np.float64)
    if base.ndim != 2 or base.shape != other.shape:
        raise ValueError(f"las superficies deben ser rejillas de la misma forma, no {base.shape} "
                         f"y {other.shape}")
    threshold = _thickness(min_thickness_m)
    with np.errstate(invalid="ignore"):
        found = np.abs(base - other) > threshold
    found &= np.isfinite(base) & np.isfinite(other)
    return found


@dataclass(slots=True)
class _Accumulator:
    """Las sumas de las bandas de una pasada de volúmenes."""

    cut: list[float]
    fill: list[float]
    cut_cells: int = 0
    fill_cells: int = 0
    nodata: int = 0

    def add(self, start: np.ndarray, design: np.ndarray, threshold: float) -> np.ndarray:
        """Suma la banda ``start``/``design`` y devuelve su máscara de movimiento."""
        valid = np.isfinite(start) & np.isfinite(design)
        with np.errstate(invalid="ignore"):
            difference = start - design
            cut = valid & (difference > threshold)
            fill = valid & (difference < -threshold)
        self.cut.append(float(np.where(cut, difference, 0.0).sum()))
        self.fill.append(float(np.where(fill, -difference, 0.0).sum()))
        self.cut_cells += int(np.count_nonzero(cut))
        self.fill_cells += int(np.count_nonzero(fill))
        self.nodata += int(valid.size - np.count_nonzero(valid))
        return cut | fill

    def result(self, area: float) -> Volumes:
        moved = self.cut_cells + self.fill_cells
        return Volumes(math.fsum(self.cut) * area, math.fsum(self.fill) * area, self.cut_cells,
                       self.fill_cells, moved * area, self.nodata, self.nodata * area)


def volumes(start: np.ndarray, other: np.ndarray, geometry: Grid, min_thickness_m: float,
            *, cells_per_unit: int = REPORT_CELLS_PER_UNIT) -> Volumes:
    """El movimiento de tierras de la superficie ``other`` frente a ``start`` con el espesor mínimo
    ``min_thickness_m`` (A7 de la 012; véase el módulo): desmonte donde ``other`` queda por debajo
    de ``start``, terraplén donde queda por encima. Para las cifras de una envolvente
    (``des.env_cut_m3``, ``des.env_fill_m3``) y las del informe. De una vez; las entradas no se
    modifican."""
    base = _surface(start, "la superficie de partida", geometry)
    changed = _surface(other, "la superficie", geometry)
    threshold = _thickness(min_thickness_m)
    per_unit = max(1, _units(cells_per_unit) // max(geometry.ncols, 1))
    totals = _Accumulator([], [])
    for first in range(0, geometry.nrows, per_unit):
        last = min(geometry.nrows, first + per_unit)
        totals.add(base[first:last], changed[first:last], threshold)
    return totals.result(geometry.cell_area)


# --- Inclinación y borde: una banda con sus filas vecinas --------------------------------------


def padded_rows(values: np.ndarray, low: int, high: int) -> np.ndarray:
    """Las filas ``low:high`` de ``values`` con una vuelta de ``NaN`` alrededor; las cotas no
    finitas se ven como sin dato. Pública desde la spec 017 (T15: la pendiente local de la
    accesibilidad la usa; antes ``_padded``, sin cambiar un resultado)."""
    padded = np.full((high - low + 2, values.shape[1] + 2), np.nan)
    inner = padded[1:-1, 1:-1]
    inner[...] = values[low:high]
    np.copyto(inner, np.nan, where=~np.isfinite(inner))
    return padded


def max_tangents(padded: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """La mayor pendiente (tangente) a las 8 vecinas con dato de cada celda de ``padded`` (``NaN``
    sin ninguna): cuatro pares desplazados atribuidos a las dos celdas. Pública desde la spec 017
    (T15: la usan la plataforma, la pista y la accesibilidad; antes ``_max_tangents``, sin cambiar
    un resultado)."""
    height, width = padded.shape
    diagonal = math.hypot(dx, dy)
    best = np.full(padded.shape, np.nan)
    distances = {(0, 1): dx, (1, 0): dy, (1, 1): diagonal, (1, -1): diagonal}
    for d_row, d_col in _DIAGONAL_PAIRS:
        first = (slice(0, height - d_row), slice(max(0, -d_col), width - max(0, d_col)))
        second = (slice(d_row, height), slice(max(0, d_col), width - max(0, -d_col)))
        with np.errstate(invalid="ignore"):
            tangent = np.abs(padded[first] - padded[second])
        tangent /= distances[(d_row, d_col)]
        np.fmax(best[first], tangent, out=best[first])
        np.fmax(best[second], tangent, out=best[second])
    return best


def _edges(padded: np.ndarray, held: np.ndarray, moved: np.ndarray, base: int
           ) -> tuple[float, np.ndarray]:
    """El mayor escalón (m) entre una celda con movimiento (``moved``, la banda) y una vecina de lado
    no admitida (``held``, con la misma vuelta que ``padded``; ``base`` es la fila de ``padded`` de
    la primera celda de la banda) y qué celdas de la banda tocan una no admitida."""
    rows, cols = moved.shape
    centre = (slice(base, base + rows), slice(1, cols + 1))
    here = padded[centre]
    touching = np.zeros(moved.shape, dtype=np.bool_)
    step = 0.0
    for d_row, d_col in _SIDES:
        side = (slice(base + d_row, base + d_row + rows), slice(1 + d_col, 1 + d_col + cols))
        border = moved & held[side]
        if not border.any():
            continue
        touching |= border
        with np.errstate(invalid="ignore"):
            jump = np.abs(here - padded[side])
        finite = border & np.isfinite(jump)
        if finite.any():
            step = max(step, float(jump[finite].max()))
    return step, touching


# --- El informe, por pasos ---------------------------------------------------------------------


@dataclass(slots=True)
class _Worst:
    """La celda que más pasa de la cara más la tolerancia."""

    excess: float
    incline: float
    limit: float
    row: int
    col: int


def _place(geometry: Grid, row: int, col: int) -> CellPlace:
    """El centro absoluto (float64) de la celda ``row``, ``col``."""
    return CellPlace(row, col, geometry.west + (col + 0.5) * geometry.dx,
                     geometry.north - (row + 0.5) * geometry.dy)


def _grid_border_cells(moved: np.ndarray) -> int:
    """Las celdas con movimiento en la primera o la última fila o columna de la rejilla (cada una
    una vez, también las de las esquinas)."""
    rows, cols = moved.shape
    if rows <= 2 or cols <= 2:
        return int(np.count_nonzero(moved))  # toda celda está en el borde
    return int(np.count_nonzero(moved[0]) + np.count_nonzero(moved[-1])
               + np.count_nonzero(moved[1:-1, 0]) + np.count_nonzero(moved[1:-1, -1]))


def _notices(found: Volumes, threshold: float, border: int, over: int, worst: _Worst | None,
             geometry: Grid, tolerance: float, ratio: float, operation: str,
             previous: Previous | None, pending: Sequence[str], profiles: Sequence[BenchProfile],
             lowering: Lowering | None) -> tuple[Notice, ...]:
    """Los avisos y notas del informe, en orden (véase el módulo)."""
    notices: list[Notice] = []
    if found.moved_cells == 0:
        notices.append(Notice("des.no_movement", {"thickness": threshold}))
    if border:
        notices.append(Notice("des.edge_movement",
                              {"cells": border, "area": border * geometry.cell_area}))
    if over and worst is not None:
        offender = _place(geometry, worst.row, worst.col)
        notices.append(Notice("des.slope_over_face", {
            "cells": over, "max": worst.incline, "limit": worst.limit, "tolerance": tolerance,
            "x": offender.x, "y": offender.y}))
    if lowering is not None and lowering.cells > 0:
        notices.append(Notice("des.regularization_lowered", {
            "cells": lowering.cells, "drop": lowering.drop_m, "slope": lowering.slope_deg,
            "sectors": ", ".join(lowering.sectors) or "—"}))
    if previous is None:
        notices.append(Notice("des.magnitude_no_reference", {"operation": operation or "—"}))
    else:
        for code, current, before in (("des.magnitude_cut", found.cut_m3, previous.cut_m3),
                                      ("des.magnitude_fill", found.fill_m3, previous.fill_m3)):
            if before > 0.0 and current > ratio * before:
                notices.append(Notice(code, {
                    "current": round(current), "previous": round(before),
                    "ratio": current / before, "threshold": ratio,
                    "operation": previous.operation or operation or "—",
                    "revision": previous.revision}))
    notices.extend(Notice("des.sector_pending_mark", {"sector": sector}) for sector in pending)
    for profile in profiles:
        values = profile.unresolved_values(geometry)
        if values is not None:
            notices.append(Notice("des.profile_unresolved", values))
    return tuple(notices)


def _report_units(start: np.ndarray, design: np.ndarray, geometry: Grid, allowed: np.ndarray,
                  threshold: float, face: np.ndarray, tolerance: float, ratio: float,
                  operation: str, previous: Previous | None, pending: Sequence[str],
                  profiles: Sequence[BenchProfile], lowering: Lowering | None,
                  cells_per_unit: int) -> Generator[None, None, DesignReport]:
    """Las unidades de :func:`report_steps`."""
    rows, cols = start.shape
    per_unit = max(1, cells_per_unit // max(cols, 1))
    moved = np.zeros(start.shape, dtype=np.bool_)
    totals = _Accumulator([], [])
    yield
    for first in range(0, rows, per_unit):
        last = min(rows, first + per_unit)
        moved[first:last] = totals.add(start[first:last], design[first:last], threshold)
        yield
    found = totals.result(geometry.cell_area)
    held = ~allowed
    look_at_edges = bool(held.any())
    angles_parts: list[np.ndarray] = []
    best: tuple[float, int, int] | None = None
    over = 0
    worst: _Worst | None = None
    step = 0.0
    touching = 0
    for first in range(0, rows, per_unit):
        last = min(rows, first + per_unit)
        band = moved[first:last]
        if band.any():
            low, high = max(first - 1, 0), min(last + 1, rows)
            padded = padded_rows(design, low, high)
            base = 1 + first - low
            tangents = max_tangents(padded, geometry.dx, geometry.dy)[
                base:base + (last - first), 1:cols + 1]
            pick = band & np.isfinite(tangents)
            if pick.any():
                angles = np.degrees(np.arctan(tangents[pick]))
                angles_parts.append(angles)
                flat = np.flatnonzero(pick)
                top = int(np.argmax(angles))
                if best is None or float(angles[top]) > best[0]:
                    best = (float(angles[top]), first + int(flat[top]) // cols,
                            int(flat[top]) % cols)
                limits = face[first:last][pick] + tolerance
                with np.errstate(invalid="ignore"):
                    excess = angles - limits
                    offenders = excess > 0.0
                count = int(np.count_nonzero(offenders))
                if count:
                    over += count
                    index = int(np.argmax(np.where(offenders, excess, -np.inf)))
                    if worst is None or float(excess[index]) > worst.excess:
                        worst = _Worst(float(excess[index]), float(angles[index]),
                                       float(limits[index]), first + int(flat[index]) // cols,
                                       int(flat[index]) % cols)
            if look_at_edges:
                padded_held = np.zeros((high - low + 2, cols + 2), dtype=np.bool_)
                padded_held[1:-1, 1:-1] = held[low:high]
                jump, touched = _edges(padded, padded_held, band, base)
                step = max(step, jump)
                touching += int(np.count_nonzero(touched))
        yield
    p90 = p99 = top_angle = None
    place = None
    if angles_parts:
        angles = angles_parts[0] if len(angles_parts) == 1 else np.concatenate(angles_parts)
        low_p, high_p = np.percentile(angles, [90.0, 99.0])
        p90, p99 = float(low_p), float(high_p)
        assert best is not None  # hubo celdas con inclinación
        top_angle = best[0]
        place = _place(geometry, best[1], best[2])
        yield
    notices = _notices(found, threshold, _grid_border_cells(moved), over, worst, geometry,
                       tolerance, ratio, operation, previous, pending, profiles, lowering)
    yield
    return DesignReport(found.cut_m3, found.fill_m3, found.cut_cells, found.fill_cells,
                        found.moved_area_m2, found.nodata_cells, found.nodata_area_m2, threshold,
                        p90, p99, top_angle, place, step, touching, notices)


def report_steps(start: np.ndarray, design: np.ndarray, geometry: Grid, allowed: np.ndarray, *,
                 min_thickness_m: float, face_deg: float | np.ndarray, face_tolerance_deg: float,
                 warning_ratio: float, operation: str = "", previous: Previous | None = None,
                 pending: Sequence[str] = (), profiles: Sequence[BenchProfile] = (),
                 lowering: Lowering | None = None, budget_s: float = STEP_BUDGET_S,
                 cells_per_unit: int = REPORT_CELLS_PER_UNIT) -> Iterator[Progress]:
    """El informe de la superficie de diseño ``design`` frente a la de partida ``start`` (m,
    rejillas de ``geometry``; se toman como float64), por pasos de ``budget_s`` como mucho: el último
    ``Progress`` (fase «report») lleva en ``result`` el :class:`DesignReport` (véase el módulo).

    ``allowed`` (booleana; :func:`~design.compose.allowed_cells`) dice dónde se podía mover: lo demás
    es lo prohibido cuyo borde se mide. ``min_thickness_m`` es el espesor mínimo de verificación
    de la 012 (m); ``face_deg`` la inclinación de la cara del perfil (°; un número o un mapa por
    celda, ``NaN`` donde no hay escalonado) y ``face_tolerance_deg`` la tolerancia de cara (°);
    ``warning_ratio`` el umbral de aviso de magnitud (veces; > 1). Con ``previous`` (D-25) se compara
    el desmonte y el terraplén; sin él, una nota lo dice (``operation`` es el nombre de la operación
    que se informa). ``pending`` son los nombres de los sectores con la búsqueda pendiente y
    ``profiles`` los perfiles que se aplicaron (para avisar de los que la rejilla no resuelve).
    ``lowering`` es lo que bajó la regularización entre sectores (RF-013-26): con celdas bajadas,
    un aviso con su recuento y el descenso máximo; no cambia ninguna cifra.

    Ninguna cifra mínima, tolerancia ni umbral lleva valor por defecto (D-7): los lee quien llama de
    los parámetros del proyecto. Una forma que no casa, una máscara que no es booleana, un valor
    fuera de su rango o unas celdas por unidad menores que 1 son errores del programa
    (:class:`ValueError`) y salen al llamar. Las entradas no se modifican; cerrar el generador a mitad
    no deja nada."""
    base = _surface(start, "la superficie de partida", geometry)
    changed = _surface(design, "la superficie de diseño", geometry)
    mask = np.asarray(allowed)
    if mask.dtype != np.bool_ or mask.shape != geometry.shape:
        raise ValueError(f"las celdas admitidas son una máscara booleana de la forma "
                         f"{geometry.shape}, no {mask.dtype} de forma {mask.shape}")
    threshold = _thickness(min_thickness_m)
    tolerance = float(face_tolerance_deg)
    if not math.isfinite(tolerance) or tolerance < 0.0:
        raise ValueError(f"la tolerancia de cara debe ser un número finito ≥ 0, no "
                         f"{face_tolerance_deg!r}")
    ratio = float(warning_ratio)
    if not math.isfinite(ratio) or ratio <= 1.0:
        raise ValueError(f"el umbral de aviso debe ser un número finito mayor que 1, no "
                         f"{warning_ratio!r}")
    faces = np.asarray(face_deg, dtype=np.float64)
    try:
        fits = np.broadcast_shapes(faces.shape, geometry.shape) == geometry.shape
    except ValueError:
        fits = False
    if not fits:
        raise ValueError(f"la cara del perfil (face_deg) tiene la forma {faces.shape}, que no cabe "
                         f"en la de la rejilla {geometry.shape}")
    if faces.ndim == 0 and not math.isfinite(float(faces)):
        raise ValueError(f"la cara del perfil debe ser un número finito, no {face_deg!r}")
    if previous is not None and not isinstance(previous, Previous):
        raise ValueError("lo anterior es un Previous o None")
    if isinstance(pending, str):
        raise ValueError("los sectores pendientes son una lista de nombres, no un texto")
    if lowering is not None and not isinstance(lowering, Lowering):
        raise ValueError("lo que bajó la regularización es un Lowering o None")
    work = _report_units(base, changed, geometry, mask, threshold,
                         np.broadcast_to(faces, geometry.shape), tolerance, ratio, operation,
                         previous, tuple(pending), tuple(profiles), lowering,
                         _units(cells_per_unit))
    return pace_progress(work, budget_s, phase="report", running="Calculando el informe…",
                         finished="Informe calculado")
