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
