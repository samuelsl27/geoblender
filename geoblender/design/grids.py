# SPDX-License-Identifier: GPL-3.0-or-later
"""Utilidades de rejilla del diseño de cantera en numpy puro (spec 014; RF-014-02, RF-014-03,
RF-014-17, RF-014-21; plan 014 A2, A3 y §8).

- **El anillo** (A2): :func:`dilate_square` da las celdas a distancia de Chebyshev ≤ ``k`` de una
  celda marcada (la dilatación cuadrada de lado ``2k + 1``, como ``binary_dilation`` 3×3 repetida
  ``k`` veces en la V7 y la V8). Es separable (filas y columnas) y cada eje se hace por
  duplicación del radio: de ``a`` a ``a + s`` con ``s ≤ 2a + 1`` desplazamientos, así que son
  ``O(log k)`` pasadas de la rejilla. El anillo de coronación del recinto ``R`` es
  ``dilate_square(R, k) ∧ ¬R``.
- **Las componentes 4-conexas** (A3): :func:`label_components_steps`, por pasos. (1) Por bandas de
  :data:`BAND_ROWS` filas, los **tramos** de cada fila (los cambios de la máscara con ``np.diff``)
  y las parejas de tramos que se solapan en filas vecinas (con ``np.searchsorted``: los que tocan a
  un tramo en la fila de encima son un intervalo de los de esa fila; la banda anterior aporta su
  última fila). (2) La **unión-búsqueda vectorizada** sobre los tramos: en cada vuelta, cada raíz
  se cuelga de la menor raíz con la que tiene una pareja (``np.minimum.at``, por trozos de
  :data:`EDGES_PER_UNIT` parejas), se comprimen los caminos saltando de padre en abuelo hasta que
  no cambia nada y solo siguen las parejas de raíces distintas; cada vuelta une al menos dos árboles
  de cada componente sin terminar, así que son ``O(log tramos)`` vueltas también en una espiral.
  (3) La raíz de cada componente es su primer tramo, así que las etiquetas, ``1 … n``, van en el
  orden de su primera celda recorriendo la rejilla fila a fila; se pintan por bandas.
  Es ``O(celdas)`` en numpy y nada por tramo en Python; cada unidad (una banda, un trozo de parejas
  o un salto de la compresión) cabe en un paso de ``budget_s``.
- **El más próximo** (A7; RF-014-11): :func:`nearest_value_steps` da, para cada celda, el cuadrado
  de la distancia euclídea entre centros de celda a la celda marcada más próxima y el valor de esa
  celda; a igual distancia, el **menor** valor (la cota más baja). Es la transformada de distancia
  exacta y separable de Felzenszwalb y Huttenlocher (2012): (1) por columnas, la semilla más
  próxima de la misma columna (arriba y abajo, con ``np.maximum.accumulate``, por bandas de
  :data:`BAND_ROWS` filas que se pasan la última semilla vista); (2) por filas, la envolvente
  inferior de las parábolas ``g(c′) + (c − c′)²`` de las columnas con semilla, vectorizada sobre
  las filas de una banda (una columna por unidad). El desempate es **exacto** porque se busca el
  mínimo de una **clave entera** ``m · d² + r``, con ``r`` el rango del valor entre los ``m``
  valores distintos de las semillas: el orden de las claves es el de ``(d², valor)`` y la clave
  sigue siendo separable (``m · ((c − c′)² + (f − f′)²) + r``), así que las dos pasadas dan su
  mínimo sin perder ningún empate. Todo en ``int64``, con los cortes de la envolvente comparados
  como fracciones (productos cruzados), sin redondeo.

Ninguna entrada se modifica: cada llamada da arrays nuevos.

Python puro (nivel 8), con numpy.
"""

from __future__ import annotations

import math
from collections.abc import Generator, Iterator
from dataclasses import dataclass

import numpy as np

from ..core.project.model import Progress
from ..gis.masks.compile import STEP_BUDGET_S
from .seeds import pace_progress

__all__ = [
    "BAND_ROWS",
    "EDGES_PER_UNIT",
    "Labels",
    "Nearest",
    "dilate_square",
    "label_components",
    "label_components_steps",
    "nearest_value_steps",
]

BAND_ROWS = 256
"""Las filas de cada unidad de trabajo de :func:`label_components_steps` (plan 014 §5.3.2)."""
EDGES_PER_UNIT = 1 << 18
"""Las parejas de tramos que se cuelgan en cada unidad de trabajo de la unión-búsqueda."""


@dataclass(frozen=True, eq=False)
class Labels:
    """Las componentes 4-conexas de una máscara: ``grid`` (``int32``, de la forma de la máscara)
    con 0 fuera y ``1 … n`` dentro, en el orden de la primera celda de cada componente recorriendo
    la rejilla fila a fila, y ``sizes`` (``int64``), las celdas de cada una (``sizes[i − 1]``, las
    de la etiqueta ``i``)."""

    grid: np.ndarray
    sizes: np.ndarray

    @property
    def count(self) -> int:
        """El número de componentes."""
        return int(self.sizes.size)


def _mask(mask: object) -> np.ndarray:
    found = np.asarray(mask)
    if found.ndim != 2:
        raise ValueError(f"la máscara es una rejilla de 2 dimensiones, no de {found.ndim}")
    return found.astype(bool, copy=False)


def _dilate_axis(mask: np.ndarray, k: int, axis: int) -> np.ndarray:
    """La dilatación de radio ``k`` a lo largo de ``axis`` (una máscara nueva). La rejilla se
    amplía ``k`` celdas por cada lado mientras se duplica el radio (una celda de fuera de la rejilla
    lleva lo que alcanza dentro) y se recorta al final."""
    size = mask.shape[axis]
    if k >= size - 1:  # todo el eje a la vista: cada línea con alguna celda, entera
        return np.broadcast_to(mask.any(axis=axis, keepdims=True), mask.shape).copy()
    widths = [(0, 0), (0, 0)]
    widths[axis] = (k, k)
    found = np.pad(mask, widths)
    radius = 0
    while radius < k:
        shift = min(2 * radius + 1, k - radius)
        old = found.copy()
        ahead = [slice(None)] * 2
        behind = [slice(None)] * 2
        ahead[axis] = slice(shift, None)
        behind[axis] = slice(None, -shift)
        found[tuple(ahead)] |= old[tuple(behind)]
        found[tuple(behind)] |= old[tuple(ahead)]
        radius += shift
    inner = [slice(None)] * 2
    inner[axis] = slice(k, k + size)
    return found[tuple(inner)].copy()


def dilate_square(mask: np.ndarray, k: int) -> np.ndarray:
    """Las celdas a distancia de Chebyshev ≤ ``k`` celdas de alguna celda de ``mask`` (una máscara
    nueva de su forma; lo que cae fuera de la rejilla se pierde). ``k`` es un entero ≥ 0; con 0 es
    una copia. ``ValueError`` si ``k`` no lo es o ``mask`` no es de 2 dimensiones."""
    found = _mask(mask)
    if isinstance(k, bool) or int(k) != k or k < 0:
        raise ValueError(f"el radio de la dilatación es un entero ≥ 0, no {k!r}")
    radius = int(k)
    return _dilate_axis(_dilate_axis(found, radius, 0), radius, 1)


def label_components_steps(mask: np.ndarray, *, budget_s: float = STEP_BUDGET_S
                           ) -> Iterator[Progress]:
    """Las componentes 4-conexas de ``mask`` por pasos de ``budget_s`` como mucho: el último
    ``Progress`` (fase ``components``) lleva las :class:`Labels`. ``ValueError`` al avanzar si
    ``mask`` no es de 2 dimensiones. Cerrar el generador a mitad no deja nada."""
    return pace_progress(_label_units(mask), budget_s, phase="components",
                         running="Buscando las zonas conexas…", finished="Zonas conexas encontradas")


def label_components(mask: np.ndarray) -> Labels:
    """:func:`label_components_steps` de una vez: las :class:`Labels` de las componentes 4-conexas
    de ``mask`` (spec 015, T16: el contorno de la zona que declara una entidad, de una huella de
    pocas celdas, no necesita pasos). ``ValueError`` si ``mask`` no es de 2 dimensiones."""
    last: Progress | None = None
    for last in label_components_steps(mask):
        pass
    if last is None or not isinstance(last.result, Labels):  # inalcanzable: el último paso lo lleva
        raise RuntimeError("las componentes conexas no dieron resultado")
    return last.result


@dataclass(frozen=True, eq=False)
class _Runs:
    """Los tramos de una banda (fila absoluta, primera columna y la siguiente a la última)."""

    rows: np.ndarray
    starts: np.ndarray
    ends: np.ndarray


def _band_runs(band: np.ndarray, first_row: int) -> _Runs:
    """Los tramos de las filas de ``band`` en orden de fila y columna."""
    count, cols = band.shape
    padded = np.zeros((count, cols + 2), dtype=np.int8)
    padded[:, 1:-1] = band
    change = np.diff(padded, axis=1)
    width = cols + 1
    starts = np.flatnonzero(change == 1)
    ends = np.flatnonzero(change == -1)
    return _Runs((starts // width + first_row).astype(np.int64), starts % width, ends % width)


def _touching(rows: np.ndarray, starts: np.ndarray, ends: np.ndarray, width: int
              ) -> tuple[np.ndarray, np.ndarray]:
    """Las parejas ``(a, b)`` de tramos (índices en estos arrays, en orden de fila y columna) con
    ``b`` en la fila siguiente a la de ``a`` y que se solapan en alguna columna (4-conexos)."""
    key_starts = rows * width + starts
    key_ends = rows * width + ends
    above = (rows - 1) * width
    low = np.searchsorted(key_ends, above + starts, side="right")
    high = np.searchsorted(key_starts, above + ends, side="left")
    counts = np.maximum(high - low, 0)
    total = int(counts.sum())
    b = np.repeat(np.arange(rows.size, dtype=np.int64), counts)
    offsets = np.arange(total, dtype=np.int64) - np.repeat(np.cumsum(counts) - counts, counts)
    a = np.repeat(low.astype(np.int64), counts) + offsets
    return a, b


def _label_units(mask: object) -> Generator[None, None, Labels]:
    """Las unidades de :func:`label_components_steps`."""
    found = _mask(mask)
    nrows, ncols = found.shape
    width = ncols + 1
    bands = [(start, min(nrows, start + BAND_ROWS)) for start in range(0, nrows, BAND_ROWS)]
    # 1 · Los tramos y las parejas, por bandas; la banda anterior aporta su última fila.
    runs: list[_Runs] = []
    edges_a: list[np.ndarray] = []
    edges_b: list[np.ndarray] = []
    counted = 0
    previous = _Runs(np.empty(0, np.int64), np.empty(0, np.int64), np.empty(0, np.int64))
    previous_first = 0
    for start, stop in bands:
        band = _band_runs(found[start:stop], start)
        rows = np.concatenate((previous.rows, band.rows))
        a, b = _touching(rows, np.concatenate((previous.starts, band.starts)),
                         np.concatenate((previous.ends, band.ends)), width)
        local = np.concatenate((np.arange(previous_first, previous_first + previous.rows.size),
                                np.arange(counted, counted + band.rows.size)))
        edges_a.append(local[a])
        edges_b.append(local[b])
        runs.append(band)
        last = band.rows == stop - 1
        first_last = int(np.argmax(last)) if last.any() else band.rows.size
        previous = _Runs(band.rows[first_last:], band.starts[first_last:], band.ends[first_last:])
        previous_first = counted + first_last
        counted += band.rows.size
        yield None
    lengths = (np.concatenate([band.ends for band in runs]) - np.concatenate(
        [band.starts for band in runs])) if runs else np.empty(0, np.int64)
    # 2 · La unión-búsqueda: colgar cada raíz de la menor vecina, comprimir, repetir.
    parent = np.arange(counted, dtype=np.int64)
    low = np.concatenate(edges_a) if edges_a else np.empty(0, np.int64)
    high = np.concatenate(edges_b) if edges_b else np.empty(0, np.int64)
    del edges_a, edges_b
    while low.size:
        hooked = parent.copy()
        kept_low: list[np.ndarray] = []
        kept_high: list[np.ndarray] = []
        for first in range(0, low.size, EDGES_PER_UNIT):
            root_a = parent[low[first:first + EDGES_PER_UNIT]]
            root_b = parent[high[first:first + EDGES_PER_UNIT]]
            apart = root_a != root_b
            smaller = np.minimum(root_a[apart], root_b[apart])
            larger = np.maximum(root_a[apart], root_b[apart])
            np.minimum.at(hooked, larger, smaller)
            kept_low.append(smaller)
            kept_high.append(larger)
            yield None
        parent = hooked
        while True:
            grand = parent[parent]
            if np.array_equal(grand, parent):
                break
            parent = grand
            yield None
        low = np.concatenate(kept_low)
        high = np.concatenate(kept_high)
    # 3 · Las etiquetas: la raíz es el primer tramo de su componente.
    is_root = parent == np.arange(counted, dtype=np.int64)
    rank = np.cumsum(is_root, dtype=np.int64)
    run_labels = rank[parent].astype(np.int32)
    count = int(rank[-1]) if counted else 0
    sizes = np.bincount(run_labels - 1, weights=lengths, minlength=count).astype(np.int64) \
        if counted else np.empty(0, np.int64)
    grid = np.zeros((nrows, ncols), dtype=np.int32)
    first_run = 0
    for (start, stop), band in zip(bands, runs, strict=True):
        last_run = first_run + band.rows.size
        grid[start:stop][found[start:stop]] = np.repeat(run_labels[first_run:last_run],
                                                        lengths[first_run:last_run])
        first_run = last_run
        yield None
    return Labels(grid, sizes)


_NONE = np.iinfo(np.int64).max
"""La clave de una columna sin semilla en la pasada por filas."""
_KEY_LIMIT = 1 << 62
"""El mayor producto que se admite en las comparaciones exactas de :func:`nearest_value_steps`."""


@dataclass(frozen=True, eq=False)
class Nearest:
    """La celda marcada más próxima a cada celda: ``cells2`` (``int64``), el cuadrado de la
    distancia euclídea entre centros en celdas² (exacto; −1 si no hay ninguna marcada), ``value``
    (``float64``), el valor de la más próxima (a igual distancia, el menor; NaN si no hay
    ninguna), y ``cell``, el lado de la celda (m)."""

    cells2: np.ndarray
    value: np.ndarray
    cell: float

    @property
    def d2(self) -> np.ndarray:
        """El cuadrado de la distancia en m² (``float64``; ``+inf`` si no hay ninguna marcada)."""
        found = self.cells2.astype(np.float64) * (self.cell * self.cell)
        found[self.cells2 < 0] = np.inf
        return found


def nearest_value_steps(mask: np.ndarray, values: np.ndarray, cell: float, *,
                        budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """La celda de ``mask`` más próxima a cada celda de la rejilla y su valor en ``values`` (de la
    forma de ``mask``; solo se leen las celdas marcadas), por pasos de ``budget_s`` como mucho: el
    último ``Progress`` (fase ``nearest``) lleva el :class:`Nearest`. ``cell`` es el lado de la
    celda (m). ``ValueError`` en la llamada si ``mask`` no es de 2 dimensiones, ``values`` no es de
    su forma, ``cell`` no es positivo y finito o una celda marcada no tiene un valor finito; y al
    avanzar si la rejilla y los valores distintos son tantos que la clave no cabe en ``int64``.
    Ninguna entrada se modifica; cerrar el generador a mitad no deja nada."""
    found = _mask(mask)
    read = np.asarray(values, dtype=np.float64)
    if read.shape != found.shape:
        raise ValueError(f"los valores son una rejilla {read.shape}, no {found.shape}")
    side = float(cell)
    if not math.isfinite(side) or side <= 0.0:
        raise ValueError(f"el lado de la celda es positivo y finito, no {cell!r}")
    if not np.isfinite(read[found]).all():
        raise ValueError("una celda marcada no tiene un valor finito")
    return pace_progress(_nearest_units(found, read, side), budget_s, phase="nearest",
                         running="Buscando el más próximo…", finished="El más próximo, encontrado")


def _nearest_units(found: np.ndarray, values: np.ndarray, cell: float
                   ) -> Generator[None, None, Nearest]:
    """Las unidades de :func:`nearest_value_steps`."""
    nrows, ncols = found.shape
    bands = [(start, min(nrows, start + BAND_ROWS)) for start in range(0, nrows, BAND_ROWS)]
    # 1 · Los valores distintos de las semillas, que dan el rango del desempate: los de cada banda
    # (con el índice de cada semilla en ellos) y su unión, banda a banda (dos tramos ordenados que
    # el orden estable mezcla en tiempo lineal).
    parts: list[tuple[np.ndarray, np.ndarray]] = []
    for start, stop in bands:
        parts.append(np.unique(values[start:stop][found[start:stop]], return_inverse=True))
        yield None
    distinct = np.empty(0)
    for part, _inverse in parts:
        merged = np.sort(np.concatenate((distinct, part)), kind="stable")
        distinct = merged[np.concatenate(([True], merged[1:] != merged[:-1]))] \
            if merged.size else merged
        yield None
    if distinct.size == 0:
        return Nearest(np.full(found.shape, -1, dtype=np.int64), np.full(found.shape, np.nan),
                       cell)
    scale = int(distinct.size)
    if scale * (nrows * nrows + ncols * ncols + 1) * 2 * (ncols + 1) >= _KEY_LIMIT:
        raise ValueError(f"la rejilla {found.shape} con {scale} valores distintos no cabe en la "
                         "clave entera del más próximo")
    rank = np.zeros(found.shape, dtype=np.int64)
    for (start, stop), (part, inverse) in zip(bands, parts, strict=True):
        rank[start:stop][found[start:stop]] = np.searchsorted(distinct, part)[inverse.ravel()]
        yield None
    del parts
    # 2 · Por columnas: la clave de la semilla más próxima de la misma columna, arriba y abajo.
    key = np.empty(found.shape, dtype=np.int64)
    cols = np.arange(ncols, dtype=np.int64)
    seen_row = np.full(ncols, -1, dtype=np.int64)
    for start, stop in bands:
        sub = found[start:stop]
        rows = np.arange(start, stop, dtype=np.int64)[:, None]
        above = np.maximum.accumulate(np.where(sub, rows, -1), axis=0)
        np.maximum(above, seen_row, out=above)
        seen_row = above[-1].copy()
        seen = above >= 0
        gap = rows - above
        key[start:stop] = np.where(seen, scale * gap * gap + rank[np.where(seen, above, 0), cols],
                                   _NONE)
        yield None
    seen_row = np.full(ncols, nrows, dtype=np.int64)
    for start, stop in reversed(bands):
        sub = found[start:stop]
        rows = np.arange(start, stop, dtype=np.int64)[:, None]
        below = np.minimum.accumulate(np.where(sub, rows, nrows)[::-1], axis=0)[::-1]
        below = np.minimum(below, seen_row)
        seen_row = below[0].copy()
        seen = below < nrows
        gap = below - rows
        np.minimum(key[start:stop],
                   np.where(seen, scale * gap * gap + rank[np.where(seen, below, 0), cols], _NONE),
                   out=key[start:stop])
        yield None
    del rank
    # 3 · Por filas: la envolvente inferior de las parábolas, todas las filas de una banda a la vez.
    cells2 = np.empty(found.shape, dtype=np.int64)
    nearest = np.empty(found.shape, dtype=np.float64)
    for start, stop in bands:
        best = np.empty((stop - start, ncols), dtype=np.int64)
        yield from _envelope_units(key[start:stop], best, scale)
        cells2[start:stop], low = np.divmod(best, scale)
        nearest[start:stop] = distinct[low]
        yield None
    return Nearest(cells2, nearest, cell)


def _envelope_units(key: np.ndarray, out: np.ndarray, scale: int) -> Generator[None, None, None]:
    """``out[f, p] = mín_c (key[f, c] + scale · (p − c)²)`` sobre las columnas ``c`` con clave
    (Felzenszwalb y Huttenlocher, una columna por unidad y todas las filas a la vez). La parábola
    ``j`` de la envolvente de una fila está en la columna ``at[f, j]`` y manda desde
    ``num[f, j] / (2 · scale · den[f, j])`` (``den`` > 0); la 0, desde −∞."""
    lines, ncols = key.shape
    every = np.arange(lines, dtype=np.int64)
    at = np.zeros((lines, max(ncols, 1)), dtype=np.int64)
    num = np.zeros_like(at)
    den = np.ones_like(at)
    top = np.full(lines, -1, dtype=np.int64)
    for col in range(ncols):
        here = key[:, col]
        live = here != _NONE
        fresh = every[live & (top < 0)]
        waiting = every[live & (top >= 0)]
        lift = scale * col * col
        while waiting.size:
            last = top[waiting]
            other = at[waiting, last]
            cut_num = here[waiting] + lift - key[waiting, other] - scale * other * other
            cut_den = col - other
            drop = (last > 0) & (cut_num * den[waiting, last] <= num[waiting, last] * cut_den)
            stay = waiting[~drop]
            if stay.size:
                after = last[~drop] + 1
                top[stay] = after
                at[stay, after] = col
                num[stay, after] = cut_num[~drop]
                den[stay, after] = cut_den[~drop]
            waiting = waiting[drop]
            top[waiting] -= 1
        top[fresh] = 0
        at[fresh, 0] = col
        yield None
    current = np.zeros(lines, dtype=np.int64)
    for col in range(ncols):
        moving = every[current < top]
        while moving.size:
            ahead = current[moving] + 1
            moving = moving[num[moving, ahead] < 2 * scale * col * den[moving, ahead]]
            current[moving] += 1
            moving = moving[current[moving] < top[moving]]
        source = at[every, current]
        gap = col - source
        out[:, col] = scale * gap * gap + key[every, source]
        yield None
