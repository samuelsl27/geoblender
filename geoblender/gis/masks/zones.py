# SPDX-License-Identifier: GPL-3.0-or-later
"""La zona de cada restricción y los límites en la rejilla del proyecto (spec 012; RF-012-11,
RF-012-12; plan 012 A1, A2, D-1, D-19 y D-37; ADR-0028).

**La regla de la celda (D-1, RF-012-12).** Una celda está en la **zona** de una geometría cuando
alguna parte de su área queda a una distancia de ella menor que su resguardo hacia fuera ``r``
(más que el residuo del redondeo: ``d < r − τ``, τ = :data:`TAU_M`), y **dentro de un límite** solo
cuando está entera dentro. Así lo que una máscara prohíbe nunca deja fuera parte de una celda, y
lo que solo toca un borde no cuenta.

- :func:`near_runs` (**A1**): las celdas a distancia ``< r − τ`` de unos segmentos, por
  **intervalos de fila de la cápsula**: la cápsula abierta de un segmento (los puntos a menos de
  ``r``) es convexa, así que su corte con la franja de una fila es un intervalo abierto de X,
  ``(lo, hi)``, y la celda ``c`` está dentro si ``c·dx < hi`` y ``(c + 1)·dx > lo``. El intervalo es
  la unión de (i) el trozo del segmento dentro de la franja ampliado en ``r`` a cada lado y (ii, iii)
  el corte de la cápsula de lo que queda por encima (o por debajo) con el borde de la franja (dos
  discos y la banda perpendicular). Sin pares celda-segmento (D-19: 0,81 s frente a 16,2 s en el
  caso de referencia del plan, §2.2). Distancias en metros con ``dx`` y ``dy`` por separado: vale
  con celdas no cuadradas. Un punto es un segmento nulo.
- :func:`inside_runs` (**A2**): las celdas con una fracción de su área dentro de un polígono
  ``> ε`` (las que toca) o ``≥ 1 − ε`` (las enteras dentro), con la fracción exacta de
  ``gis.coverage`` (ε = ``FRACTION_EPSILON``, 10⁻¹²).
- :func:`zone_runs` / :func:`zone_steps`: la zona de una restricción con su resguardo hacia fuera
  (un polígono, lo que toca ∪ lo cercano; una línea o un punto, lo cercano, con ``r > 0``, D-17).
- :func:`limit_runs` / :func:`limit_steps`: de un límite (unas aristas orientadas, p. ej. la unión
  de varios límites legales de ``gis.polygons.overlay``), las celdas enteras dentro, su **banda
  hacia dentro** (las enteras dentro a menos del resguardo hacia dentro de su borde) y el núcleo.
- :func:`area_inside`: el área exacta del polígono dentro de la rejilla (Σ fracción · área de la
  celda).

Las zonas son **tramos de fila** (:class:`Runs`: fila desde el norte, primera columna y la
siguiente a la última), no máscaras de toda la rejilla ni miles de objetos de Python. Por pasos:
trozos de segmentos y bandas de filas cuyos tramos se unen; por trozos sale lo mismo que de una
vez. Coordenadas locales en metros **relativas a la esquina suroeste** de la rejilla (restar una
esquina cercana es exacto en float64, lema de Sterbenz). Python puro con numpy (nivel 2).
"""

from __future__ import annotations

import math
from collections.abc import Generator, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from ..coverage import FRACTION_EPSILON, band_coverage, polygon_edges
from ..polygons import drain

if TYPE_CHECKING:
    from ..grid import Grid

__all__ = [
    "ROWS_PER_STEP",
    "SEGMENTS_PER_STEP",
    "TAU_M",
    "LimitRuns",
    "Runs",
    "area_inside",
    "edges_of",
    "inside_runs",
    "limit_runs",
    "limit_steps",
    "near_runs",
    "segments_of",
    "zone_runs",
    "zone_steps",
]

TAU_M = 1e-9
"""τ (m, D-37): una celda a una distancia ≥ ``r − τ`` solo toca la zona dentro del redondeo."""
SEGMENTS_PER_STEP = 1024
"""Segmentos de cada paso de :func:`near_runs` en :func:`zone_steps` y :func:`limit_steps`."""
ROWS_PER_STEP = 256
"""Filas de cada paso de :func:`inside_runs` en :func:`zone_steps` y :func:`limit_steps`."""

_POLYGON, _LINE, _POINT = "polygon", "line", "point"
_EMPTY = np.zeros(0, dtype=np.int64)


# --- Tramos de fila ----------------------------------------------------------------------------


def _normalize(row: np.ndarray, col0: np.ndarray, col1: np.ndarray
               ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Los tramos sin vacíos, ordenados por fila y columna, con los que se solapan o se tocan
    unidos."""
    keep = col1 > col0
    row, col0, col1 = row[keep], col0[keep], col1[keep]
    if row.size == 0:
        return _EMPTY, _EMPTY, _EMPTY
    order = np.lexsort((col0, row))
    row, col0, col1 = row[order], col0[order], col1[order]
    # El final más a la derecha de los tramos anteriores de la misma fila: un máximo acumulado
    # de ``fila·W + col1`` (las filas crecen), con W mayor que cualquier columna.
    least = int(min(col0.min(), 0))
    width = int(col1.max()) - least + 2
    reach = np.maximum.accumulate(row * width + (col1 - least))
    start = np.ones(row.size, dtype=bool)
    start[1:] = ((row[1:] != row[:-1])
                 | (col0[1:] - least > reach[:-1] - row[1:] * width))
    first = np.flatnonzero(start)
    return (row[first], col0[first], np.maximum.reduceat(col1, first))


@dataclass(frozen=True, slots=True, eq=False)
class Runs:
    """Unas celdas de la rejilla como tramos de fila: ``row`` (la fila 0 es la del norte),
    ``col0`` (la primera columna) y ``col1`` (la siguiente a la última), int64, ordenados por
    fila y columna, sin vacíos ni tramos que se solapen o se toquen (se normalizan al crearlos).
    Dos :class:`Runs` son iguales si tienen las mismas celdas."""

    row: np.ndarray
    col0: np.ndarray
    col1: np.ndarray

    def __post_init__(self) -> None:
        arrays = [np.asarray(value).astype(np.int64, copy=False).ravel()
                  for value in (self.row, self.col0, self.col1)]
        if not (arrays[0].size == arrays[1].size == arrays[2].size):
            raise ValueError("Los tramos tienen tantas filas como primeras y últimas columnas")
        if np.any(arrays[2] < arrays[1]):
            raise ValueError("Un tramo no puede acabar antes de empezar")
        for name, value in zip(("row", "col0", "col1"), _normalize(*arrays), strict=True):
            value = np.ascontiguousarray(value)
            value.flags.writeable = False
            object.__setattr__(self, name, value)

    @classmethod
    def empty(cls) -> Runs:
        """Ninguna celda."""
        return cls(_EMPTY, _EMPTY, _EMPTY)

    @classmethod
    def from_mask(cls, mask: np.ndarray, offset: tuple[int, int] = (0, 0)) -> Runs:
        """Las celdas verdaderas de la máscara ``mask`` (filas de norte a sur), cuya celda
        ``[0, 0]`` es la de la fila y la columna ``offset``."""
        mask = np.asarray(mask, dtype=bool)
        if mask.ndim != 2:
            raise ValueError(f"Una máscara es un array 2D, no de forma {mask.shape}")
        padded = np.zeros((mask.shape[0], mask.shape[1] + 2), dtype=np.int8)
        padded[:, 1:-1] = mask
        change = np.diff(padded, axis=1)
        starts_row, starts_col = np.nonzero(change == 1)
        _, ends_col = np.nonzero(change == -1)
        return cls(starts_row + offset[0], starts_col + offset[1], ends_col + offset[1])

    @classmethod
    def union_all(cls, items: Iterable[Runs]) -> Runs:
        """La unión de todos los tramos de ``items``."""
        items = list(items)
        if not items:
            return cls.empty()
        return cls(np.concatenate([item.row for item in items]),
                   np.concatenate([item.col0 for item in items]),
                   np.concatenate([item.col1 for item in items]))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Runs):
            return NotImplemented
        return (np.array_equal(self.row, other.row) and np.array_equal(self.col0, other.col0)
                and np.array_equal(self.col1, other.col1))

    __hash__ = None  # type: ignore[assignment]

    def __len__(self) -> int:
        return int(self.row.size)

    def __repr__(self) -> str:
        return f"Runs({len(self)} tramos, {self.cells} celdas)"

    @property
    def cells(self) -> int:
        """El número de celdas."""
        return int(np.sum(self.col1 - self.col0))

    def area(self, grid: Grid) -> float:
        """El área de sus celdas (m²), con el área exacta de la celda de ``grid``."""
        return self.cells * grid.cell_area

    def union(self, other: Runs) -> Runs:
        """Las celdas de los dos."""
        return Runs.union_all((self, other))

    def intersection(self, other: Runs) -> Runs:
        """Las celdas de los dos a la vez."""
        return self._combine(other, both=True)

    def difference(self, other: Runs) -> Runs:
        """Las celdas de este que no están en ``other``."""
        return self._combine(other, both=False)

    def _combine(self, other: Runs, *, both: bool) -> Runs:
        if len(self) == 0 or (len(other) == 0 and both):
            return Runs.empty()
        if len(other) == 0:
            return self
        # Barrido por fila: +1/−1 de cada conjunto en sus bordes; entre dos bordes seguidos de la
        # misma fila, el estado (en este, en el otro) es la suma acumulada.
        row = np.concatenate([self.row, self.row, other.row, other.row])
        col = np.concatenate([self.col0, self.col1, other.col0, other.col1])
        mine = np.concatenate([np.ones(len(self), np.int64), -np.ones(len(self), np.int64),
                               np.zeros(2 * len(other), np.int64)])
        theirs = np.concatenate([np.zeros(2 * len(self), np.int64),
                                 np.ones(len(other), np.int64), -np.ones(len(other), np.int64)])
        order = np.lexsort((col, row))
        row, col = row[order], col[order]
        in_mine = np.cumsum(mine[order]) > 0
        in_theirs = np.cumsum(theirs[order]) > 0
        keep = in_mine & (in_theirs if both else ~in_theirs)
        keep = keep[:-1] & (row[1:] == row[:-1])
        index = np.flatnonzero(keep)
        return Runs(row[index], col[index], col[index + 1])

    def mask(self, shape: tuple[int, int], offset: tuple[int, int] = (0, 0)) -> np.ndarray:
        """Las celdas como máscara booleana de forma ``shape`` (filas de norte a sur), cuya celda
        ``[0, 0]`` es la de la fila y la columna ``offset``; lo de fuera no se ve."""
        height, width = int(shape[0]), int(shape[1])
        row = self.row - offset[0]
        col0 = np.clip(self.col0 - offset[1], 0, width)
        col1 = np.clip(self.col1 - offset[1], 0, width)
        keep = (row >= 0) & (row < height) & (col1 > col0)
        row, col0, col1 = row[keep], col0[keep], col1[keep]
        marks = np.zeros((height, width + 1), dtype=np.int64)
        np.add.at(marks, (row, col0), 1)
        np.add.at(marks, (row, col1), -1)
        return np.cumsum(marks, axis=1)[:, :width] > 0


@dataclass(frozen=True, slots=True)
class LimitRuns:
    """Un límite en la rejilla: las celdas enteras dentro (``inside``) y las de su banda hacia
    dentro (``band``, dentro de ``inside``)."""

    inside: Runs
    band: Runs

    @property
    def core(self) -> Runs:
        """El núcleo: las enteras dentro sin la banda."""
        return self.inside.difference(self.band)


# --- Geometría de una restricción --------------------------------------------------------------


def _kind(item: Any) -> str:
    return str(getattr(item.kind, "value", item.kind))


def _corner(grid: Grid) -> np.ndarray:
    return np.array([grid.west, grid.extent.ymin], dtype=np.float64)


def edges_of(constraint: Any, grid: Grid) -> np.ndarray:
    """Las aristas orientadas ``(n, 2, 2)`` de una restricción **poligonal** (todas sus partes;
    exterior antihorario y huecos horarios) en metros relativos a la esquina suroeste de
    ``grid``, como las da ``gis.coverage.polygon_edges``. :class:`ValueError` si no es un
    polígono o no tiene partes."""
    if _kind(constraint) != _POLYGON:
        raise ValueError(f"Solo un polígono tiene aristas orientadas, no un {_kind(constraint)}")
    if not constraint.parts:
        raise ValueError("La restricción no tiene geometría")
    return np.ascontiguousarray(np.concatenate([polygon_edges(part, grid)
                                                for part in constraint.parts]))


def segments_of(constraint: Any, grid: Grid) -> np.ndarray:
    """Los segmentos ``(n, 2, 2)`` de una restricción en metros relativos a la esquina suroeste
    de ``grid``: las aristas de un polígono, los tramos de una línea y, de un punto, un segmento
    nulo. :class:`ValueError` si no tiene partes."""
    kind = _kind(constraint)
    if kind == _POLYGON:
        return edges_of(constraint, grid)
    if not constraint.parts:
        raise ValueError("La restricción no tiene geometría")
    corner = _corner(grid)
    pieces = []
    for part in constraint.parts:
        for path in part:
            local = np.asarray(path, dtype=np.float64)[:, :2] - corner
            if kind == _POINT or local.shape[0] == 1:
                pieces.append(np.stack([local, local], axis=1))
            else:
                pieces.append(np.stack([local[:-1], local[1:]], axis=1))
    return np.ascontiguousarray(np.concatenate(pieces))


# --- A1: celdas cercanas a unos segmentos ------------------------------------------------------


def _check_segments(segments: object) -> np.ndarray:
    segments = np.asarray(segments, dtype=np.float64)
    if segments.ndim != 3 or segments.shape[1:] != (2, 2):
        raise ValueError(f"Los segmentos son un array (n, 2, 2), no de forma {segments.shape}")
    if not np.all(np.isfinite(segments)):
        raise ValueError("Los segmentos tienen coordenadas no finitas")
    return segments


def _clip(ax: np.ndarray, ay: np.ndarray, bx: np.ndarray, by: np.ndarray,
          low: np.ndarray, high: np.ndarray
          ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """El trozo de cada segmento ``[a, b]`` con ``low ≤ y ≤ high`` (Liang–Barsky en Y):
    ``(hay, px, py, qx, qy)``; los extremos que no se recortan, exactos."""
    dy = by - ay
    flat = dy == 0.0
    safe = np.where(flat, 1.0, dy)
    with np.errstate(divide="ignore", invalid="ignore"):
        t_low = np.where(flat, -np.inf, (low - ay) / safe)
        t_high = np.where(flat, np.inf, (high - ay) / safe)
    rising = dy >= 0.0
    enter = np.maximum(np.where(rising, t_low, t_high), 0.0)
    leave = np.minimum(np.where(rising, t_high, t_low), 1.0)
    ok = (~flat | ((ay >= low) & (ay <= high))) & (enter <= leave)
    with np.errstate(invalid="ignore"):
        px = np.where(enter == 0.0, ax, ax + enter * (bx - ax))
        py = np.where(enter == 0.0, ay, ay + enter * dy)
        qx = np.where(leave == 1.0, bx, ax + leave * (bx - ax))
        qy = np.where(leave == 1.0, by, ay + leave * dy)
    return ok, px, py, qx, qy


def _line_interval(line_y: np.ndarray, px: np.ndarray, py: np.ndarray, qx: np.ndarray,
                   qy: np.ndarray, radius: float) -> tuple[np.ndarray, np.ndarray]:
    """``{x : d((x, line_y), [p, q]) < radius}`` de cada segmento como ``(lo, hi)`` (vacío si
    ``lo ≥ hi``): los dos discos de los extremos y la banda perpendicular del interior."""
    squared = radius * radius
    lo = np.full(line_y.shape, np.inf)
    hi = np.full(line_y.shape, -np.inf)
    for cx, cy in ((px, py), (qx, qy)):
        h = squared - (line_y - cy) ** 2
        ok = h > 0.0
        half = np.sqrt(np.where(ok, h, 0.0))
        lo = np.where(ok, np.minimum(lo, cx - half), lo)
        hi = np.where(ok, np.maximum(hi, cx + half), hi)
    ux, uy = qx - px, qy - py
    length2 = ux * ux + uy * uy
    length = np.sqrt(length2)
    with np.errstate(divide="ignore", invalid="ignore"):
        # A menos de radius de la recta: |(x − px)·uy − (Y − py)·ux| < radius·L.
        k = (line_y - py) * ux
        slanted = uy != 0.0
        safe_uy = np.where(slanted, uy, 1.0)
        e1 = px + (k - radius * length) / safe_uy
        e2 = px + (k + radius * length) / safe_uy
        near_lo = np.where(slanted, np.minimum(e1, e2), -np.inf)
        near_hi = np.where(slanted, np.maximum(e1, e2), np.inf)
        near_lo = np.where(~slanted & ~(np.abs(k) < radius * length), np.inf, near_lo)
        # Proyección dentro del segmento: 0 < (x − px)·ux + (Y − py)·uy < L².
        m = (line_y - py) * uy
        sideways = ux != 0.0
        safe_ux = np.where(sideways, ux, 1.0)
        f1 = px - m / safe_ux
        f2 = px + (length2 - m) / safe_ux
        along_lo = np.where(sideways, np.minimum(f1, f2), -np.inf)
        along_hi = np.where(sideways, np.maximum(f1, f2), np.inf)
        along_lo = np.where(~sideways & ~((m > 0.0) & (m < length2)), np.inf, along_lo)
    band_lo = np.maximum(near_lo, along_lo)
    band_hi = np.minimum(near_hi, along_hi)
    band = (length2 > 0.0) & (band_lo < band_hi)
    return np.where(band, np.minimum(lo, band_lo), lo), np.where(band, np.maximum(hi, band_hi), hi)


def _rows(rows: slice | None, grid: Grid) -> tuple[int, int]:
    """La banda de filas (desde el norte, sin paso) como ``(primera, siguiente)``."""
    if rows is None:
        return 0, grid.nrows
    start, stop, step = rows.indices(grid.nrows)
    if step != 1:
        raise ValueError(f"Una banda son filas seguidas, no con paso {step}")
    return start, max(stop, start)


def near_runs(segments: np.ndarray, radius_m: float, grid: Grid, *,
              rows: slice | None = None) -> Runs:
    """**A1** (RF-012-12, D-1): las celdas de ``grid`` (o de su banda de filas ``rows``, desde el
    norte) a una distancia ``< radius_m − τ`` de alguno de los segmentos ``(n, 2, 2)`` (metros
    relativos a la esquina suroeste; un punto, un segmento nulo). Sin resguardo (``radius_m ≤
    τ``), ninguna. Unos segmentos que no son ``(n, 2, 2)`` o no finitos son un error del programa
    (:class:`ValueError`)."""
    segments = _check_segments(segments)
    reach = float(radius_m) - TAU_M
    first, stop = _rows(rows, grid)
    if not reach > 0.0 or segments.shape[0] == 0 or stop <= first:
        return Runs.empty()
    dx, dy, nrows, ncols = grid.dx, grid.dy, grid.nrows, grid.ncols
    south_low, south_high = nrows - stop, nrows - first   # la banda, en filas desde el sur
    ax, ay = segments[:, 0, 0], segments[:, 0, 1]
    bx, by = segments[:, 1, 0], segments[:, 1, 1]
    low = np.floor((np.minimum(ay, by) - reach) / dy)
    high = np.ceil((np.maximum(ay, by) + reach) / dy)
    low = np.clip(low, south_low, south_high).astype(np.int64)
    high = np.clip(high, south_low, south_high).astype(np.int64)
    count = np.maximum(high - low, 0)
    owner = np.repeat(np.arange(segments.shape[0]), count)
    if owner.size == 0:
        return Runs.empty()
    south = low[owner] + (np.arange(owner.size) - np.repeat(np.cumsum(count) - count, count))
    ax, ay, bx, by = ax[owner], ay[owner], bx[owner], by[owner]
    bottom = south * dy
    top = (south + 1) * dy
    # (i) El trozo dentro de la franja, ampliado en el resguardo a cada lado.
    ok, px, _, qx, _ = _clip(ax, ay, bx, by, bottom, top)
    lo = np.where(ok, np.minimum(px, qx) - reach, np.inf)
    hi = np.where(ok, np.maximum(px, qx) + reach, -np.inf)
    # (ii, iii) Lo de encima y lo de debajo, por su corte con el borde de la franja.
    for line_y, part_low, part_high in ((top, top, np.full(top.shape, np.inf)),
                                        (bottom, np.full(bottom.shape, -np.inf), bottom)):
        ok, px, py, qx, qy = _clip(ax, ay, bx, by, part_low, part_high)
        part_lo, part_hi = _line_interval(line_y, px, py, qx, qy, reach)
        good = ok & (part_lo < part_hi)
        lo = np.where(good, np.minimum(lo, part_lo), lo)
        hi = np.where(good, np.maximum(hi, part_hi), hi)
    keep = lo < hi
    col0 = np.maximum(np.floor(lo[keep] / dx), 0.0)
    col1 = np.minimum(np.ceil(hi[keep] / dx), float(ncols))
    inside = col0 < col1   # lo que cae entero al oeste o al este de la rejilla, fuera
    return Runs(nrows - 1 - south[keep][inside], col0[inside].astype(np.int64),
                col1[inside].astype(np.int64))


# --- A2: celdas dentro de un polígono ----------------------------------------------------------


def _cells_to_runs(rows: np.ndarray, cols: np.ndarray) -> Runs:
    """Las celdas (en orden de filas y columnas, cada una una vez) como tramos."""
    if rows.size == 0:
        return Runs.empty()
    start = np.ones(rows.size, dtype=bool)
    start[1:] = (rows[1:] != rows[:-1]) | (cols[1:] != cols[:-1] + 1)
    first = np.flatnonzero(start)
    last = np.append(first[1:], rows.size) - 1
    return Runs(rows[first], cols[first], cols[last] + 1)


def inside_runs(edges: np.ndarray, grid: Grid, *, whole: bool,
                rows: slice | None = None) -> Runs:
    """**A2** (RF-012-12): las celdas de ``grid`` (o de su banda ``rows``) con una fracción de
    su área dentro del polígono de las aristas orientadas ``edges`` (``gis.coverage``) mayor que
    ``ε`` (las que toca, ``whole=False``) o de al menos ``1 − ε`` (las enteras dentro,
    ``whole=True``)."""
    first, stop = _rows(rows, grid)
    band = band_coverage(edges, grid, slice(first, stop))
    if whole:
        found = band.fraction >= 1.0 - FRACTION_EPSILON
    else:
        found = band.fraction > FRACTION_EPSILON
    return _cells_to_runs(band.rows[found], band.cols[found])


def area_inside(edges: np.ndarray, grid: Grid, *, rows: slice | None = None) -> float:
    """El área (m²) del polígono de las aristas orientadas ``edges`` dentro de ``grid`` (o de su
    banda ``rows``): la suma de las fracciones exactas de sus celdas por el área de la celda."""
    first, stop = _rows(rows, grid)
    band = band_coverage(edges, grid, slice(first, stop))
    return math.fsum(band.fraction.tolist()) * grid.cell_area


# --- Zonas y límites, por pasos ----------------------------------------------------------------


def _near_steps(segments: np.ndarray, radius_m: float, grid: Grid, size: int,
                found: list[Runs]) -> Generator[None]:
    for begin in range(0, segments.shape[0], max(int(size), 1)):
        found.append(near_runs(segments[begin:begin + size], radius_m, grid))
        yield


def _inside_steps(edges: np.ndarray, grid: Grid, size: int, whole: bool,
                  found: list[Runs]) -> Generator[None]:
    size = max(int(size), 1)
    for begin in range(0, grid.nrows, size):
        found.append(inside_runs(edges, grid, whole=whole, rows=slice(begin, begin + size)))
        yield


def zone_steps(constraint: Any, grid: Grid, outward_m: float, *,
               segments_per_step: int = SEGMENTS_PER_STEP,
               rows_per_step: int = ROWS_PER_STEP) -> Generator[None, None, Runs]:
    """La zona de ``constraint`` en ``grid`` con su resguardo hacia fuera ``outward_m`` (RF-012-11,
    RF-012-12) por pasos: un paso por banda de ``rows_per_step`` filas (lo que toca un polígono)
    y por trozo de ``segments_per_step`` segmentos (lo cercano); la zona, en
    ``StopIteration.value``. Un polígono: lo que toca ∪ lo que queda a menos del resguardo (si es
    > 0); una línea o un punto: lo que queda a menos del resguardo, que tiene que ser > 0 (D-17;
    si no, :class:`ValueError`: lo impide antes la comprobación de las incompletas)."""
    outward = float(outward_m)
    if not math.isfinite(outward) or outward < 0.0:
        raise ValueError(f"El resguardo hacia fuera es un número ≥ 0, no {outward_m!r}")
    found: list[Runs] = []
    if _kind(constraint) == _POLYGON:
        yield from _inside_steps(edges_of(constraint, grid), grid, rows_per_step, False, found)
    elif not outward > 0.0:
        raise ValueError(f"Una zona de un {_kind(constraint)} necesita un resguardo > 0")
    if outward > 0.0:
        yield from _near_steps(segments_of(constraint, grid), outward, grid, segments_per_step,
                               found)
    return Runs.union_all(found)


def zone_runs(constraint: Any, grid: Grid, outward_m: float, **steps: int) -> Runs:
    """:func:`zone_steps` de una vez."""
    return drain(zone_steps(constraint, grid, outward_m, **steps))


def limit_steps(edges: np.ndarray, grid: Grid, inward_m: float | None, *,
                segments_per_step: int = SEGMENTS_PER_STEP,
                rows_per_step: int = ROWS_PER_STEP) -> Generator[None, None, LimitRuns]:
    """Un límite en ``grid`` (RF-012-11, RF-012-12; A2) por pasos, desde sus aristas orientadas
    ``edges`` (metros relativos a la esquina suroeste; varios límites, unidos antes): las celdas
    enteras dentro y su banda hacia dentro, las enteras dentro a menos de ``inward_m`` de su
    borde (sin resguardo hacia dentro, ``None`` o 0, ninguna)."""
    inward = 0.0 if inward_m is None else float(inward_m)
    if not math.isfinite(inward) or inward < 0.0:
        raise ValueError(f"El resguardo hacia dentro es un número ≥ 0, no {inward_m!r}")
    edges = _check_segments(edges)
    inside: list[Runs] = []
    yield from _inside_steps(edges, grid, rows_per_step, True, inside)
    whole = Runs.union_all(inside)
    near: list[Runs] = []
    if inward > 0.0:
        yield from _near_steps(edges, inward, grid, segments_per_step, near)
    return LimitRuns(whole, Runs.union_all(near).intersection(whole))


def limit_runs(edges: np.ndarray, grid: Grid, inward_m: float | None,
               **steps: int) -> LimitRuns:
    """:func:`limit_steps` de una vez."""
    return drain(limit_steps(edges, grid, inward_m, **steps))
