# SPDX-License-Identifier: GPL-3.0-or-later
"""RF-015-13 y RF-015-14 con los tipos de la 016: lo que el contrafuerte y el cuerpo apoyado avisan de su borde y de su orden con la cantera
(spec 016, T46; HU-016-3, HU-016-4; RF-015-13, RF-015-14, RF-016-17, RF-016-20; hallazgos C-1 y C-2 de la verificación única). Dominio puro:
sin proyecto y sin ``bpy``.

La 015 pide a **toda** entidad que cambia la superficie (RF-015-13) que su resumen diga, con su lugar, qué llega al borde de la rejilla o
a celdas sin dato fuera de su huella y cuánto de su huella recorta la rejilla, y (RF-015-14) que avise del orden con la otra superficie
de la cantera de la 014. La plataforma lo hace en ``design.platform`` (``_edge_units``, ``platform_footprint_units`` y
``platform_outcome``); esto es **lo mismo, copiado** para el contrafuerte y el cuerpo «sobre una base» (ninguna cifra de la 015 cambia: los
helpers de aquí no los usa la plataforma) con las mismas medidas y los mismos números en los avisos:

- :func:`clipped_units` y :func:`clipped_notice`: **la huella recortada por la rejilla**. Las celdas que la geometría de la huella (el
  polígono de la zona de coronación o de la huella del cuerpo) tendría fuera de la rejilla del proyecto, medidas **como las de dentro**
  (el centro de la celda dentro del polígono, par-impar, la unión de sus partes) solo en lo que queda fuera, por bloques acotados
  (:data:`~.platform._OUTSIDE_BLOCK_CELLS`), con el lugar de la primera celda (la más al norte y al oeste). Una geometría dentro de la
  rejilla no cuesta más que su caja y no avisa. Es el mismo cálculo que :func:`~.platform._clipped_units` hace para el polígono de una
  plataforma (``ClippedByTheGridTest`` de la 015 es su oráculo).
- :func:`reaches_outside` y :func:`outside_notice`: **lo que llega al borde de la rejilla o a celdas sin dato** fuera de la huella: las
  celdas que la entidad mueve (``changed``) y están en el borde de la rejilla (si la ventana de trabajo llega a él) o junto a una celda
  sin dato que no es de su huella (``nodata``, a una celda, en los ocho vecinos). Ahí la superficie puede quedar cortada: aviso con el
  área y el lugar de la primera, ``des.entity_edge_outside`` (el de la plataforma).
- :func:`order_notice`: el aviso de RF-015-14 (``des.entity_quarry_order``, el de la plataforma) con el incumplimiento que da
  :func:`~.platform.order_check` y la otra superficie de la cantera (:class:`~.platform.QuarryOrder`).

**Lo que no está aquí** (decisión pendiente, T46): el salto creado del borde de lo que mueve el contrafuerte con el aviso de RF-014-21.
La medida (T46, 290 contrafuertes de prueba con los valores por defecto del proyecto: salto de 1 m en el 99 % de las parejas) dice que sale
en casi todo contrafuerte con su pie natural (en el 72 % de los 290 y en el 96 % de los de perfil con la cara a 60° y celdas de 2 m: el salto
de una pareja del pie llega a la altura de una celda por la tangente de la cara, 3,46 m), así que un aviso que salta siempre no sirve y el
criterio es de Samuel; hasta entonces el contrafuerte solo mide el salto de su borde si el pie queda cortado (RF-016-19).
"""

from __future__ import annotations

from collections.abc import Generator, Iterable, Sequence

import numpy as np

from ..gis.grid import Grid
from .grids import dilate_square
from .platform import (
    _OUTSIDE_BLOCK_CELLS,
    OrderBreach,
    QuarryOrder,
    _ideal_box,
    _outside_rectangles,
    _places,
    _polygon_block_units,
)
from .preview import Notice
from .zones import _polygon_spans

__all__ = [
    "Clipped",
    "as_parts",
    "clipped_notice",
    "clipped_units",
    "order_notice",
    "outside_notice",
    "reaches_outside",
]

Clipped = tuple[int, float, float]
"""Lo que la rejilla recorta de una huella: las celdas de fuera, y el lugar absoluto (``x``, ``y``, m, float64) de la primera."""


def as_parts(parts: Iterable[Iterable[object]] | None) -> tuple[tuple[np.ndarray, ...], ...] | None:
    """Las partes de la geometría de una huella (``parts``: cada polígono, con sus anillos ABSOLUTOS —el exterior primero y luego los
    huecos—, de vértices ``(k, 2)`` o ``(k, 3)``) como las lee el cálculo: tuplas de arrays float64, sin copiar lo que ya lo es.
    ``None`` sin geometría (el cálculo no mide lo que recorta la rejilla). ``ValueError`` si un anillo no es de vértices finitos o
    si una parte no tiene anillos."""
    if parts is None:
        return None
    found: list[tuple[np.ndarray, ...]] = []
    for part in parts:
        rings = tuple(np.asarray(ring, dtype=np.float64) for ring in part)
        if not rings:
            raise ValueError("una parte de la geometría de la huella tiene al menos su anillo exterior")
        for ring in rings:
            if ring.ndim != 2 or ring.shape[1] not in (2, 3) or ring.shape[0] < 3 or not np.isfinite(ring).all():
                raise ValueError("un anillo de la geometría de la huella son vértices finitos (k, 2) o (k, 3), de al menos tres")
        found.append(rings)
    return tuple(found)


# --- La huella recortada por la rejilla (RF-015-13) ---------------------------------------------------------------------------


def clipped_units(parts: Sequence[Sequence[np.ndarray]], grid: Grid) -> Generator[None, None, Clipped | None]:
    """**Lo que la rejilla recorta de la huella** (RF-015-13), por unidades (cada ``yield``, una): las celdas que la geometría ``parts``
    (:func:`as_parts`) tendría **fuera de la rejilla** ``grid`` y el lugar absoluto de la primera (``(celdas, x, y)``; ``None`` si no
    falta ninguna). Es la medida de la plataforma para su polígono (:func:`~.platform._clipped_units`): las celdas de **dentro** de
    cada polígono por el centro (par-impar, la unión de sus partes) medidas sobre la caja de la geometría sin recortar y solo en lo
    que queda fuera de la rejilla, por bloques de :data:`~.platform._OUTSIDE_BLOCK_CELLS` celdas: una geometría dentro de la rejilla
    no cuesta más que su caja. Cerrar el generador a mitad no deja nada."""
    rings = [np.asarray(ring, dtype=np.float64)[:, :2] for part in parts for ring in part]
    box = _ideal_box(np.concatenate(rings), 0.0, grid)
    rectangles = _outside_rectangles(box, grid)
    if not rectangles:
        return None
    rows, begin, end = _polygon_spans(parts, grid, box=box)
    order = np.argsort(rows, kind="stable")
    spans = (rows[order], begin[order], end[order])
    yield
    count, first = 0, None
    for r0, r1, c0, c1 in rectangles:
        step = max(1, _OUTSIDE_BLOCK_CELLS // (c1 - c0))
        for top in range(r0, r1, step):
            window = (slice(top, min(top + step, r1)), slice(c0, c1))
            found = yield from _polygon_block_units(spans, window)
            here = int(np.count_nonzero(found))
            if here:
                count += here
                row, col = divmod(int(found.argmax()), c1 - c0)  # la primera de las verdaderas, por filas
                cell = (top + row, c0 + col)
                first = cell if first is None or cell < first else first
            yield
    if first is None:
        return None
    return (count, float(grid.west + (first[1] + 0.5) * grid.dx), float(grid.north - (first[0] + 0.5) * grid.dy))


def clipped_notice(code: str, entity: str, clipped: Clipped | None, grid: Grid) -> Notice | None:
    """El aviso ``code`` (``des.buttress_footprint_clipped`` o ``des.body_footprint_clipped``) de lo que la rejilla recorta de la huella
    de ``entity`` (:func:`clipped_units`): las celdas y su área (m²) y el lugar al cm de la primera; ``None`` si no recorta nada."""
    if clipped is None:
        return None
    cells, x, y = clipped
    return Notice(code, {"entity": entity, "cells": cells, "area": cells * grid.cell_area, "x": round(x, 2), "y": round(y, 2)})


# --- Lo que llega al borde de la rejilla o a celdas sin dato (RF-015-13) -------------------------------------------------------


def reaches_outside(changed: np.ndarray, nodata: np.ndarray, window: tuple[slice, slice], grid: Grid) -> np.ndarray:
    """Las celdas de ``changed`` (las que mueve la entidad **fuera de su huella**: la de su borde; máscara de la forma de ``window``) que
    **llegan al borde de la rejilla** (su fila o columna es la primera o la última de ``grid`` y la ventana de trabajo ``window`` llega
    a ese borde) o **a celdas sin dato** (``nodata``, de la forma de ``window``, sin las de la huella: una celda movida a una de ellas,
    a una celda de Chebyshev). Una máscara nueva; es la de :func:`~.platform._edge_units` (``outside``)."""
    shape = changed.shape
    border = np.zeros(shape, dtype=bool)
    if window[0].start == 0:
        border[0, :] = True
    if window[0].stop == grid.nrows:
        border[-1, :] = True
    if window[1].start == 0:
        border[:, 0] = True
    if window[1].stop == grid.ncols:
        border[:, -1] = True
    near_nodata = dilate_square(nodata, 1) if nodata.any() else np.zeros(shape, dtype=bool)
    return np.asarray(changed & (border | near_nodata), dtype=bool)


def outside_notice(entity: str, outside: np.ndarray, grid: Grid, window: tuple[slice, slice]) -> Notice | None:
    """El aviso ``des.entity_edge_outside`` de ``outside`` (:func:`reaches_outside`): las celdas, su área (m²) y el lugar de la primera
    (por filas, de norte a sur y de oeste a este), al cm; ``None`` si no llega a ninguna."""
    if not outside.any():
        return None
    rows, cols = np.nonzero(outside)
    x, y = _places(grid, window, rows[:1], cols[:1])
    count = int(rows.size)
    return Notice("des.entity_edge_outside", {"entity": entity, "cells": count, "area": count * grid.cell_area,
                                              "x": float(x[0]), "y": float(y[0])})


# --- El orden con la otra superficie de la cantera (RF-015-14) ---------------------------------------------------------------


def order_notice(entity: str, quarry: QuarryOrder, breach: OrderBreach) -> Notice:
    """El aviso ``des.entity_quarry_order`` (RF-015-14) de ``entity`` frente a la otra superficie de la cantera ``quarry``
    (:class:`~.platform.QuarryOrder`) con el incumplimiento ``breach`` (:func:`~.platform.order_check`): la cantera, las dos superficies,
    las celdas, el área (m²), lo que más pasa (m, al mm) y el lugar de la primera, al cm. Es el de la plataforma
    (:func:`~.platform.platform_outcome`)."""
    return Notice("des.entity_quarry_order", {
        "entity": entity, "surface": quarry.surface, "quarry": quarry.quarry, "other": quarry.other_name,
        "cells": breach.cells, "area": breach.area_m2, "above": round(breach.max_m, 3), "x": round(breach.x, 2),
        "y": round(breach.y, 2)})
