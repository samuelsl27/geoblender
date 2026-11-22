# SPDX-License-Identifier: GPL-3.0-or-later
"""El volumen de una corta por bancos desde sus polilíneas, **sin el motor de rejilla** (spec 018, T13; plan 018 §7.1; CE-018-03, D-11).

Rasteriza las polilíneas de pie y de cresta que da ``design.pit_bench`` muestreando el centro de cada celda de una rejilla, por fuerza
bruta (punto en anillo por cruces y distancia a la línea del anillo con ``tests/support/offset_oracle.py``): no usa ``gis`` ni el
desfase. Es independiente de la superficie analítica (``pit_data.circle_surface``), que sale de los radios a mano, y del TIN de la
tarea de la superficie (que no existe todavía): el H1 solo prueba los bancos, no el rasterizado.

Los anillos de una corta circular (ascendente) están anidados de dentro a fuera (pie 0, cresta 0, pie 1…); los de un límite
(descendente), de fuera a dentro (cresta 0, pie 0, cresta 1…). Un punto cae en la cara de un banco entre sus dos anillos, en la berma
entre la cresta de un banco y el pie del siguiente, en el fondo (dentro del último anillo) o en el terreno (fuera del primero)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from tests.support import offset_oracle as oracle
from tests.support import pit_data as pd

BLOCK = 4096
"""Puntos que se prueban a la vez contra un anillo (acota la memoria)."""


def local_ring(polyline: Any, grid: Any) -> np.ndarray:
    """Los vértices ``(x, y)`` de una polilínea, en locales de ``grid``."""
    return np.asarray(polyline.vertices[:, :2]) - np.asarray(pd.origin_of(grid))


def inside(points: np.ndarray, ring: np.ndarray) -> np.ndarray:
    """Qué puntos ``(p, 2)`` están dentro del anillo (cruces de un rayo hacia el este, por bloques)."""
    a, b = ring, np.roll(ring, -1, axis=0)
    out = np.zeros(len(points), dtype=bool)
    for low in range(0, len(points), BLOCK):
        chunk = points[low:low + BLOCK]
        x, y = chunk[:, 0][:, None], chunk[:, 1][:, None]
        straddles = (a[:, 1][None, :] > y) != (b[:, 1][None, :] > y)
        slope = (b[:, 0] - a[:, 0])[None, :] / np.where(b[:, 1] == a[:, 1], 1.0, b[:, 1] - a[:, 1])[None, :]
        cross_x = a[:, 0][None, :] + (y - a[:, 1][None, :]) * slope
        out[low:low + BLOCK] = (np.sum(straddles & (x < cross_x), axis=1) % 2) == 1
    return out


def volume_m3(rings: list[np.ndarray], *, outer_first: bool, grid: Any, terrain_m: float, floor_m: float, height_m: float,
              tan_face: float, rise_m: float | None = None) -> float:
    """El volumen (m³) entre el terreno llano ``terrain_m`` y la corta de ``rings`` (pie y cresta de cada banco, en el orden dicho
    arriba) muestreado en el centro de las celdas de ``grid``.

    Ascendente (``outer_first = False``, ``floor_m`` la cota del fondo): la cara ``k`` sube ``tan_face`` por metro desde su pie y la
    berma queda a la cota de la cresta. Descendente (``outer_first = True``, ``floor_m`` la cota del fondo y ``terrain_m`` la de la
    cresta del primer banco): la cara baja ``tan_face`` por metro desde su cresta. Las cotas se acotan al terreno."""
    x, y = pd.local_centers(grid)
    box = np.concatenate(rings)
    low, high = box.min(axis=0), box.max(axis=0)
    mask = (x >= low[0]) & (x <= high[0]) & (y >= low[1]) & (y <= high[1])
    points = np.column_stack([x[mask], y[mask]])
    count = len(rings)
    # j = cuántos anillos, de los más internos, NO contienen al punto (ascendente); de los más externos, SÍ lo contienen (descendente)
    held = np.zeros(len(points), dtype=np.int64)
    for ring in rings:
        held += inside(points, ring)
    z = np.full(len(points), terrain_m, dtype=np.float64)
    step = height_m if rise_m is None else rise_m
    if outer_first:
        for j in range(1, count + 1):
            sel = held == j
            if not np.any(sel):
                continue
            bench = (j - 1) // 2
            if j % 2 == 1:  # entre la cresta ``bench`` y su pie: la cara baja desde la cresta
                dist = oracle.distance_to_ring(points[sel], rings[2 * bench])
                z[sel] = terrain_m - bench * step - dist * tan_face
            else:  # berma: a la cota del pie del banco anterior
                z[sel] = terrain_m - (j // 2) * step
        z[held == count] = floor_m
    else:
        outer = held == 0
        for j in range(count):
            sel = held == count - j
            if not np.any(sel):
                continue
            if j % 2 == 0 and j > 0:  # fuera de j anillos, con j par: berma
                z[sel] = floor_m + (j // 2) * step
            elif j % 2 == 1:  # j impar: cara del banco (j - 1) / 2, desde su pie
                bench = (j - 1) // 2
                dist = oracle.distance_to_ring(points[sel], rings[2 * bench])
                z[sel] = floor_m + bench * step + dist * tan_face
            else:  # j = 0: dentro de todo, el fondo
                z[sel] = floor_m
        z[outer] = terrain_m
    z = np.minimum(z, terrain_m)
    return float(np.sum(terrain_m - z) * grid.dx * grid.dy)


def circle_rings(found: Any, grid: Any) -> list[np.ndarray]:
    """Los anillos (pie 0, cresta 0, pie 1…) de una corta ascendente de una sola parte por banco."""
    return [local_ring(item, grid) for item in found.polylines]


def square_rings(found: Any, grid: Any) -> list[np.ndarray]:
    """Los anillos (cresta 0, pie 0, cresta 1…) de una corta descendente de una sola parte por banco."""
    return [local_ring(item, grid) for item in found.polylines]


def hand_square_volume_m3() -> float:
    """El volumen analítico del límite cuadrado de CE-018-04: troncos de pirámide ``h·(Ac + Af + √(Ac·Af))/3`` de las caras (la
    berma no añade volumen), con los lados de ``pit_data.limit_benches_by_hand``."""
    benches, _ = pd.limit_benches_by_hand()
    return math.fsum(10.0 * (b.crest_side_m ** 2 + b.foot_side_m ** 2 + b.crest_side_m * b.foot_side_m) / 3.0 for b in benches)
