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

Ninguna entrada se modifica: cada llamada da arrays nuevos.

Python puro (nivel 8), con numpy.
"""

from __future__ import annotations

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
    "dilate_square",
    "label_components_steps",
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
