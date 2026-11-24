# SPDX-License-Identifier: GPL-3.0-or-later
"""El oráculo de fuerza bruta del desfase (spec 018, T09; plan 018 §7.1): **independiente del motor** (no usa ``gis.offset`` ni
``gis.polygons``). Dice, con numpy y a lo bruto, cuánto se acerca un resultado a la fuente y si cruza sí mismo."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

BLOCK = 256
"""Pares de aristas que se comparan a la vez (acota la memoria: ``BLOCK × n`` por orientación)."""


def signed_area(ring: np.ndarray) -> float:
    """El área con signo (positiva en un anillo antihorario) por la fórmula del cordón."""
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def distance_to_ring(points: np.ndarray, ring: np.ndarray) -> np.ndarray:
    """La distancia de cada punto de ``points`` ``(p, 2)`` a la **línea** del anillo ``ring`` (todas sus aristas, por fuerza bruta)."""
    a, b = ring, np.roll(ring, -1, axis=0)
    along = b - a
    length2 = np.einsum("ej,ej->e", along, along)
    out = np.empty(len(points))
    for low in range(0, len(points), BLOCK):
        chunk = points[low:low + BLOCK]
        w = chunk[:, None, :] - a[None, :, :]
        t = np.clip(np.einsum("pej,ej->pe", w, along) / length2, 0.0, 1.0)
        rest = w - t[:, :, None] * along[None, :, :]
        out[low:low + BLOCK] = np.hypot(rest[..., 0], rest[..., 1]).min(axis=1)
    return out


def _segment_gaps(points: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """La distancia de cada punto de ``points`` ``(p, 2)`` a cada segmento ``a[e]–b[e]`` (``(p, e)``), por fuerza bruta."""
    ax, ay = a[:, 0][None, :], a[:, 1][None, :]
    ex, ey = (b[:, 0] - a[:, 0])[None, :], (b[:, 1] - a[:, 1])[None, :]
    length2 = ex * ex + ey * ey
    wx, wy = points[:, 0][:, None] - ax, points[:, 1][:, None] - ay
    t = np.clip((wx * ex + wy * ey) / length2, 0.0, 1.0)
    return np.hypot(wx - t * ex, wy - t * ey)


def edge_limits(ring: np.ndarray, worked: np.ndarray, worked_distance: np.ndarray, reach: float) -> np.ndarray:
    """La distancia que le toca a cada arista de ``ring`` (el anillo original), dada la del anillo de trabajo ``worked`` (el simplificado,
    con sus aristas partidas en los sectores) y su ``worked_distance``: la menor de las distancias de las aristas de ``worked`` a
    ``reach`` o menos de uno de los puntos de la arista (extremos y medio). ``reach`` es lo que el anillo pudo moverse al simplificarlo."""
    a, b = ring, np.roll(ring, -1, axis=0)
    samples = np.concatenate([a, 0.5 * (a + b), b])
    wa, wb = worked, np.roll(worked, -1, axis=0)
    per_sample = np.empty(len(samples))
    for low in range(0, len(samples), BLOCK):
        near = _segment_gaps(samples[low:low + BLOCK], wa, wb) <= reach + 1e-9
        per_sample[low:low + BLOCK] = np.where(near, worked_distance[None, :], np.inf).min(axis=1)
    return per_sample.reshape(3, len(ring)).min(axis=0)


def capsule_shortfall(points: np.ndarray, ring: np.ndarray, limit: np.ndarray, side: int = 0) -> float:
    """Lo que más le falta a un punto de ``points`` para estar a ``limit[e]`` o más de **cada** arista ``e`` de ``ring`` (0 si ninguno
    se queda corto): el desfase con distancia por arista es el borde de la unión de las cápsulas de sus aristas (cada una, a su
    distancia), y no hay punto suyo a menos de ``limit[e]`` de la arista ``e``. Con ``side`` ``+1`` (fuera) o ``-1`` (dentro) de un
    anillo antihorario (DIFF-018k, T09d), de cada arista cuenta **solo el lado del desfase** (el de la normal ``side·(ty, −tx)``);
    con 0, los dos lados."""
    a, b = ring, np.roll(ring, -1, axis=0)
    along = b - a
    worst = 0.0
    for low in range(0, len(points), BLOCK):
        chunk = points[low:low + BLOCK]
        gap = limit[None, :] - _segment_gaps(chunk, a, b)
        if side:
            w = chunk[:, None, :] - a[None, :, :]
            turn = side * (along[None, :, 1] * w[..., 0] - along[None, :, 0] * w[..., 1])
            gap = np.where(turn >= -1e-9 * np.hypot(along[:, 0], along[:, 1])[None, :], gap, -np.inf)
        worst = max(worst, float(gap.max()))
    return max(worst, 0.0)


def _turn(p: np.ndarray, q: np.ndarray, r: np.ndarray) -> np.ndarray:
    return (q[..., 0] - p[..., 0]) * (r[..., 1] - p[..., 1]) - (q[..., 1] - p[..., 1]) * (r[..., 0] - p[..., 0])


def crossing_count(loops: Sequence[np.ndarray]) -> int:
    """Cuántos pares de aristas se cruzan **de verdad** (cruce propio de los dos segmentos, sin tocarse en un extremo) entre los
    anillos de ``loops``, dentro de cada uno y entre ellos. Un resultado simple da 0."""
    if not loops:
        return 0
    a = np.concatenate(list(loops))
    b = np.concatenate([np.roll(loop, -1, axis=0) for loop in loops])
    count = len(a)
    found = 0
    for low in range(0, count, BLOCK):
        high = min(low + BLOCK, count)
        p, q = a[low:high][:, None, :], b[low:high][:, None, :]
        first = _turn(p, q, a[None, :, :]) * _turn(p, q, b[None, :, :]) < 0.0
        second = _turn(a[None, :, :], b[None, :, :], p) * _turn(a[None, :, :], b[None, :, :], q) < 0.0
        later = np.arange(low, high)[:, None] < np.arange(count)[None, :]
        found += int(np.count_nonzero(first & second & later))
    return found
