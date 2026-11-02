# SPDX-License-Identifier: GPL-3.0-or-later
"""Las cotas reales de las bermas (spec 013, T11; HU-013-5; RF-013-28; plan 013 A12; N-14).

Mide **desde el resultado** dónde están las bermas de una superficie de diseño escalonada, sin suponer
que sean múltiplos de nada (N-14: las líneas de rotura supusieron bermas en múltiplos de 5 m; el
cierre del balance sacó a las bermas de sus cotas, error 12). Da dos cosas:

- la **rejilla de cotas de berma** (:attr:`Berms.grid`; ``des_brm_``): la cota real del resultado (m,
  float64, sin redondear) en las celdas de berma y ``NaN`` en las demás;
- la **tabla** (:attr:`Berms.table`; ``des_bmt_``), una fila por sector, perfil y cota
  (:data:`COLUMNS`): el número de celdas de berma, su área (m²), la cota de anclaje más próxima
  ``z₀ + n·h`` y la diferencia (m) entre la cota real y esa.

**Qué es una celda de berma** (plan A12). La que cumple las tres cosas:

1. su cota está en una cota de anclaje ``z₀ + n·h`` de su perfil a menos de
   :data:`ANCHOR_TOLERANCE_M` (10⁻⁶ m);
2. tiene una vecina (de su fila o de su columna, no en diagonal) a la misma cota, con la misma
   tolerancia, que cumple también la primera condición: una cota suelta no es una berma, y una
   berma estrecha que corre de norte a sur tiene su pareja en la columna, no en la fila;
3. tiene movimiento (``moved``: la superficie de diseño difiere de la de partida más que el espesor
   mínimo de la 012): un banco natural plano que ya estaba en esa cota no es una berma del diseño.

Una cota plana que no esté en una cota de anclaje (la plataforma del fondo de una corta, un
resultado corrido por un ajuste posterior) no entra: la tolerancia de 10⁻⁶ m es la de A12. Con
una ``tolerance_m`` más ancha, la tabla da la diferencia medida frente a la cota de anclaje.

**La tabla.** Las celdas de berma se agrupan por zona (``labels``: el sector, con el perfil que le
toca; la de :class:`~design.seeds.DomainSet`, 0 = el perfil base) y por cota redondeada a 10⁻⁶ m.
``level_m`` es esa cota; ``anchor_m``, la ``z₀ + n·h`` más próxima a ella con el perfil y el ancla
de la primera celda del grupo (la primera en el orden de la rejilla: una rejilla de anclas puede
dar otra ``z₀`` a cada celda), y ``anchor_diff_m``, ``level_m − anchor_m``. Los dos van redondeados
a 10⁻⁹ m para no arrastrar el ruido de coma flotante. Las filas salen por zona y luego por cota.

**Por pasos.** Cada celda depende de sus vecinas inmediatas y de su propio perfil: la rejilla se
parte en bandas de filas (con la fila de más de cada lado en la segunda pasada) y el resultado no
cambia ni un bit con el tamaño de la banda. Cerrar el generador a mitad no deja nada y ninguna
entrada se modifica.

Python puro (nivel 8), con numpy, sin importar ``reserves`` ni ``bl``.
"""

from __future__ import annotations

import math
from collections.abc import Generator, Iterator, Sequence
from dataclasses import dataclass

import numpy as np

from ..core.project.model import Progress
from ..gis.grid import Grid
from ..gis.masks.compile import STEP_BUDGET_S
from .envelopes import CELLS_PER_UNIT
from .seeds import pace_progress

__all__ = [
    "ANCHOR_TOLERANCE_M",
    "COLUMNS",
    "BermRow",
    "BermScope",
    "Berms",
    "berms_steps",
]

ANCHOR_TOLERANCE_M = 1e-6
"""Lo que puede distar una cota de su cota de anclaje (y dos vecinas entre sí) para ser berma (A12)."""
COLUMNS = ("sector", "profile", "level_m", "cells", "area_m2", "anchor_m", "anchor_diff_m")
"""Las columnas de la tabla ``des_bmt_``, en su orden (RF-013-28)."""

_UNITS_PER_M = 1_000_000
"""Las cotas se agrupan redondeadas a 10⁻⁶ m."""
_DECIMALS = 9
"""Las cotas de anclaje y las diferencias de la tabla se redondean a 10⁻⁹ m."""

Number = float | np.ndarray


@dataclass(frozen=True, slots=True)
class BermScope:
    """La zona de una celda en la tabla: el código del ``sector`` (``""`` es el perímetro de
    actuación, o lo que quien llama ponga para las celdas sin sector) y el del ``profile`` que se
    le aplicó. La zona ``k`` de ``labels`` es ``scopes[k]``."""

    sector: str
    profile: str


@dataclass(frozen=True, slots=True)
class BermRow:
    """Una fila de la tabla (:data:`COLUMNS`): las bermas de un sector y perfil en una cota real
    ``level_m`` (m), sus ``cells``, su ``area_m2``, la cota de anclaje más próxima ``anchor_m`` (m) y
    la diferencia ``anchor_diff_m`` (m, ``level_m − anchor_m``)."""

    sector: str
    profile: str
    level_m: float
    cells: int
    area_m2: float
    anchor_m: float
    anchor_diff_m: float

    def values(self) -> tuple[str, str, float, int, float, float, float]:
        """Los valores en el orden de :data:`COLUMNS`."""
        return (self.sector, self.profile, self.level_m, self.cells, self.area_m2, self.anchor_m,
                self.anchor_diff_m)


@dataclass(frozen=True, slots=True, eq=False)
class Berms:
    """Las bermas medidas: la ``grid`` de cotas reales (m, float64, nueva, ``NaN`` fuera de las
    bermas), la ``table`` de filas, las ``cells`` de berma y su ``area_m2`` totales."""

    grid: np.ndarray
    table: tuple[BermRow, ...]
    cells: int
    area_m2: float

    @property
    def count(self) -> int:
        """Las bermas: filas de la tabla (sector, perfil y cota)."""
        return len(self.table)

    @property
    def lowest_m(self) -> float | None:
        """La cota real de berma más baja (m); ``None`` si no hay bermas."""
        return min((row.level_m for row in self.table), default=None)

    @property
    def highest_m(self) -> float | None:
        """La cota real de berma más alta (m); ``None`` si no hay bermas."""
        return max((row.level_m for row in self.table), default=None)


def _scalar(value: float, name: str, meaning: str, positive: bool) -> None:
    """``ValueError`` si el escalar ``value`` no es finito (y mayor que 0 si ``positive``)."""
    if not math.isfinite(value) or (positive and value <= 0.0):
        expected = "finita y mayor que 0" if positive else "finita"
        raise ValueError(f"{meaning} ({name}) debe ser {expected}, no {value!r}")


def _per_cell(value: Number, name: str, meaning: str, positive: bool, shape: tuple[int, ...]
              ) -> np.ndarray:
    """``value`` como vista float64 de la forma de la rejilla (un escalar o un array que se difunde
    a ella sin ampliarla). Un escalar se comprueba aquí; un array, en las celdas con berma
    posible, al medir."""
    array = np.asarray(value, dtype=np.float64)
    if array.ndim == 0:
        _scalar(float(array), name, meaning, positive)
    else:
        try:
            fits = np.broadcast_shapes(array.shape, shape) == shape
        except ValueError:
            fits = False
        if not fits:
            raise ValueError(f"{meaning} ({name}) tiene la forma {array.shape}, que no cabe en la "
                             f"forma {shape} de la superficie")
    return np.broadcast_to(array, shape)


def _live_values(values: np.ndarray, live: np.ndarray, name: str, meaning: str, positive: bool,
                 first_row: int) -> np.ndarray:
    """Los valores de ``values`` en las celdas ``live`` de una banda que empieza en ``first_row``.
    ``ValueError`` con la primera celda mala (fila y columna de la rejilla) si alguno no es finito
    (ni mayor que 0 si ``positive``)."""
    picked = values[live]
    with np.errstate(invalid="ignore"):
        good = np.isfinite(picked)
        if positive:
            good &= picked > 0.0
    if not good.all():
        row, col = np.argwhere(live)[int(np.argmin(good))]
        expected = "finita y mayor que 0" if positive else "finita"
        raise ValueError(f"{meaning} ({name}) debe ser {expected} en las celdas con superficie y "
                         f"movimiento: falla en {int((~good).sum())}, la primera en "
                         f"({int(row) + first_row}, {int(col)}) (vale "
                         f"{float(picked[int(np.argmin(good))])!r})")
    return picked


def _mark_candidates(candidate: np.ndarray, design: np.ndarray, moved: np.ndarray | None,
                     height: np.ndarray, anchor: np.ndarray, tolerance: float, first: int,
                     last: int) -> None:
    """Marca en ``candidate`` las celdas de las filas ``first:last`` con superficie, movimiento y
    una cota a menos de ``tolerance`` de su cota de anclaje."""
    cells = design[first:last]
    live = np.isfinite(cells)
    if moved is not None:
        live &= moved[first:last]
    if not live.any():
        return
    level = cells[live]
    h = _live_values(height[first:last], live, "height", "la altura de banco", True, first)
    base = _live_values(anchor[first:last], live, "anchor", "el ancla", False, first)
    with np.errstate(invalid="ignore", over="ignore"):
        nearest = np.rint((level - base) / h)
        nearest *= h
        nearest += base
        nearest -= level
        near = np.abs(nearest) <= tolerance
    candidate[first:last][live] = near


def _flat_cells(candidate: np.ndarray, design: np.ndarray, tolerance: float, first: int, last: int
                ) -> np.ndarray:
    """Qué celdas de las filas ``first:last`` son candidatas y tienen una vecina candidata de su
    fila o de su columna a la misma cota (a menos de ``tolerance``)."""
    low = max(first - 1, 0)
    high = min(last + 1, design.shape[0])
    cand = candidate[low:high]
    level = design[low:high]
    flat = np.zeros(cand.shape, dtype=np.bool_)
    with np.errstate(invalid="ignore"):
        pair = cand[:, :-1] & cand[:, 1:]
        pair &= np.abs(level[:, :-1] - level[:, 1:]) <= tolerance
        flat[:, :-1] |= pair
        flat[:, 1:] |= pair
        pair = cand[:-1] & cand[1:]
        pair &= np.abs(level[:-1] - level[1:]) <= tolerance
        flat[:-1] |= pair
        flat[1:] |= pair
    return flat[first - low:last - low]


def _count_levels(groups: dict[tuple[int, int], list[float]], values: np.ndarray,
                  zone: np.ndarray, height: np.ndarray, anchor: np.ndarray) -> None:
    """Suma a ``groups`` (zona y cota en micras → celdas, altura y ancla de la primera celda) las
    celdas de berma de una banda (``values``, ``zone``, ``height`` y ``anchor`` en el orden de la
    rejilla). Ordena de forma estable: la primera celda de un grupo es la primera de la rejilla."""
    units = np.rint(values * _UNITS_PER_M).astype(np.int64)
    zones = zone.astype(np.int64)
    order = np.lexsort((units, zones))
    sorted_zone = zones[order]
    sorted_units = units[order]
    new = np.ones(order.size, dtype=np.bool_)
    new[1:] = (sorted_zone[1:] != sorted_zone[:-1]) | (sorted_units[1:] != sorted_units[:-1])
    starts = np.flatnonzero(new)
    sizes = np.diff(np.append(starts, order.size))
    for start, size in zip(starts.tolist(), sizes.tolist(), strict=True):
        key = (int(sorted_zone[start]), int(sorted_units[start]))
        found = groups.get(key)
        if found is None:
            cell = int(order[start])
            groups[key] = [size, float(height[cell]), float(anchor[cell])]
        else:
            found[0] += size


def _table(groups: dict[tuple[int, int], list[float]], scopes: Sequence[BermScope],
           cell_area: float) -> tuple[BermRow, ...]:
    """Las filas de la tabla, por zona y por cota."""
    rows: list[BermRow] = []
    for zone, units in sorted(groups):
        cells, height, anchor = groups[(zone, units)]
        level = units / _UNITS_PER_M
        nearest = anchor + round((level - anchor) / height) * height
        scope = scopes[zone]
        rows.append(BermRow(scope.sector, scope.profile, level, int(cells), int(cells) * cell_area,
                            round(nearest, _DECIMALS) + 0.0,
                            round(level - nearest, _DECIMALS) + 0.0))
    return tuple(rows)


def _berm_units(design: np.ndarray, geometry: Grid, height: np.ndarray, anchor: np.ndarray,
                labels: np.ndarray, scopes: tuple[BermScope, ...], moved: np.ndarray | None,
                tolerance: float, cells_per_unit: int) -> Generator[None, None, Berms]:
    """Las unidades de :func:`berms_steps`: una banda de filas por unidad, dos pasadas."""
    rows, cols = design.shape
    per_unit = max(1, cells_per_unit // max(cols, 1))
    candidate = np.zeros(design.shape, dtype=np.bool_)
    yield None
    for first in range(0, rows, per_unit):
        last = min(rows, first + per_unit)
        _mark_candidates(candidate, design, moved, height, anchor, tolerance, first, last)
        yield None
    grid = np.full(design.shape, np.nan)
    groups: dict[tuple[int, int], list[float]] = {}
    for first in range(0, rows, per_unit):
        last = min(rows, first + per_unit)
        inside = _flat_cells(candidate, design, tolerance, first, last)
        if inside.any():
            values = design[first:last][inside]
            np.copyto(grid[first:last], design[first:last], where=inside)
            _count_levels(groups, values, labels[first:last][inside], height[first:last][inside],
                          anchor[first:last][inside])
        yield None
    table = _table(groups, scopes, geometry.cell_area)
    cells = sum(row.cells for row in table)
    return Berms(grid, table, cells, cells * geometry.cell_area)


def berms_steps(design: np.ndarray, geometry: Grid, height: Number, anchor: Number,
                labels: np.ndarray, scopes: Sequence[BermScope], *,
                moved: np.ndarray | None = None, tolerance_m: float = ANCHOR_TOLERANCE_M,
                budget_s: float = STEP_BUDGET_S, cells_per_unit: int = CELLS_PER_UNIT
                ) -> Iterator[Progress]:
    """Mide las bermas de la superficie de diseño ``design`` (m, float64; se toma como tal) de la
    rejilla ``geometry`` (RF-013-28, A12), por pasos de ``budget_s`` como mucho: el último
    ``Progress`` (fase «berms») lleva en ``result`` las :class:`Berms`.

    ``height`` (``h``, m) y ``anchor`` (``z₀``, m) son los de :func:`~design.benching.bench_cut` o
    :func:`~design.benching.bench_fill`: un número o un mapa por celda que se difunde a la
    rejilla (el perfil de cada sector; el ancla, una rejilla de cotas). ``labels`` es la zona de
    cada celda (enteros de la forma de la rejilla: ``DomainSet.labels``, 0 = sin sector, perfil
    base) y ``scopes[k]`` el sector y el perfil de la zona ``k``. ``moved`` (booleano de la forma de
    la rejilla; ``None`` = todas) dice qué celdas tienen movimiento frente a la superficie de
    partida. ``tolerance_m`` es lo que puede distar una cota de su cota de anclaje y dos vecinas
    entre sí (10⁻⁶ m, el valor de A12).

    Solo cuentan las celdas con cota finita y movimiento: un perfil o un ancla sin valor (``NaN``)
    en las demás no importa. Una altura que no sea finita y mayor que 0 o un ancla no finita en una
    celda con cota y movimiento, una forma que no casa, unas zonas que no son enteros de 0 a
    ``len(scopes) − 1``, una tolerancia que no sea finita y mayor que 0 o unas celdas por unidad
    menores que 1 son errores del programa (:class:`ValueError`); los de forma, tipo y rango salen al
    llamar, los de los mapas de altura y ancla al avanzar. Cerrar el generador a mitad no deja nada;
    las entradas no se modifican."""
    cells = np.asarray(design, dtype=np.float64)
    if cells.ndim != 2 or cells.shape != geometry.shape:
        raise ValueError(f"la superficie de diseño {cells.shape} no es de la forma de la rejilla "
                         f"{geometry.shape}")
    zones = np.asarray(labels)
    if zones.shape != cells.shape or zones.dtype.kind not in "iu":
        raise ValueError(f"las zonas deben ser enteros de la forma de la rejilla {cells.shape}, no "
                         f"{zones.dtype} de forma {zones.shape}")
    kept = tuple(scopes)
    if not kept:
        raise ValueError("hace falta al menos una zona (sector y perfil) para la tabla")
    if zones.size and (int(zones.min()) < 0 or int(zones.max()) >= len(kept)):
        raise ValueError(f"las zonas van de 0 a {len(kept) - 1} (una por sector y perfil), no de "
                         f"{int(zones.min())} a {int(zones.max())}")
    mask = None if moved is None else np.asarray(moved)
    if mask is not None and (mask.dtype != np.bool_ or mask.shape != cells.shape):
        raise ValueError(f"el movimiento es una máscara booleana de la forma de la rejilla "
                         f"{cells.shape}, no {mask.dtype} de forma {mask.shape}")
    heights = _per_cell(height, "height", "la altura de banco", True, cells.shape)
    anchors = _per_cell(anchor, "anchor", "el ancla", False, cells.shape)
    if not math.isfinite(tolerance_m) or tolerance_m <= 0.0:
        raise ValueError(f"la tolerancia debe ser un número finito mayor que 0, no {tolerance_m!r}")
    if cells_per_unit < 1:
        raise ValueError("las celdas por unidad deben ser al menos 1")
    work = _berm_units(cells, geometry, heights, anchors, zones, kept, mask, float(tolerance_m),
                       cells_per_unit)
    return pace_progress(work, budget_s, phase="berms", running="Midiendo las bermas…",
                         finished="Bermas medidas")
