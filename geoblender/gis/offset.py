# SPDX-License-Identifier: GPL-3.0-or-later
"""Desfase de una polilínea cerrada con distancia por arista: simplificar y curva cruda (spec 018,
RF-018-10; plan 018 §5.4 A1 y A3, P-2 y P-3).

Geometría plana genérica (la usarán la corta, R-49 y R-61), solo numpy. Los anillos son arrays
``(k, 2)`` float64 **abiertos** (sin repetir el primer vértice) en coordenadas locales, cerca del
origen: restar un origen cercano es exacto (lema de Sterbenz) y el float64 solo basta ahí
(ADR-0005). Un anillo de entrada solo se lee.

- :func:`simplify_ring`: Douglas–Peucker en anillo (el anillo se parte en el vértice más lejano
  del primero); ningún vértice quitado queda a más de la tolerancia del anillo resultante.
- :func:`raw_offset`: la **curva cruda** del desfase, con una distancia por arista. Con el giro
  ``Δ`` entre las normales de las dos aristas de un vértice y el ``paso`` del arco (tal que un
  polígono circunscrito de ese paso queda a ``tol`` de la circunferencia): si ``|Δ| < paso``, **un
  solo punto, el inglete** (así un desfase no duplica los vértices en cada pasada: trampa T-1 del
  plan); si no, y el giro abre el lado del desfase, un **abanico de arcos circunscritos**
  (el extremo de cada arista y un vértice por sector a ``d / cos(δ/2)``: el error es de un solo
  signo, ``d ≤ distancia ≤ d + tol``); si no abre, los **dos extremos** de las aristas (se
  cruzarán y los quitará la regla de la vuelta). Con ``corner = "miter"``, siempre el inglete,
  con el límite de 4·d para los giros agudos. Todo vectorizado.
- :func:`closing`: cierre morfológico (D-15, dilatar y erosionar): **solo ensancha**, nunca
  abre. Compone dos desfases con el que se le pase (por defecto, la curva cruda).

La curva cruda **no** es el desfase: puede cruzarse a sí misma. Quitarle los cruces, clasificar
sus trozos y verificarla es de ``offset_ring_steps`` (spec 018, T07).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .polygons import expand

__all__ = [
    "CORNERS",
    "MITER_LIMIT",
    "RawCurve",
    "arc_step",
    "closing",
    "raw_offset",
    "simplify_ring",
]

CORNERS = ("round", "miter")
"""Las esquinas del desfase: redondeadas (arcos circunscritos) o a inglete."""

MITER_LIMIT = 4.0
"""Longitud máxima del inglete, en veces la distancia: más allá, los dos extremos de las aristas."""

_PARALLEL = 1e-9
"""Seno del giro por debajo del cual dos aristas se toman por paralelas."""

_SAME_M = 1e-12
"""Diferencia (m) de dos distancias que se toma por cero."""

Offset = Callable[[np.ndarray, float, int], np.ndarray]
"""Un desfase de un anillo: ``(anillo, distancia, lado) -> anillo`` (lado ``+1`` fuera, ``-1`` dentro)."""


@dataclass(frozen=True, slots=True, eq=False)
class RawCurve:
    """La curva cruda de :func:`raw_offset`: sus vértices ``(m, 2)`` y, de cada uno, la arista de
    origen (el índice del vértice que la empieza) de la que sale."""

    points: np.ndarray
    source_edge: np.ndarray


def arc_step(distance_max: float, tol: float) -> float:
    """El paso angular (rad) de un arco circunscrito a una circunferencia de radio
    ``distance_max``: el vértice de un polígono tangente de ese paso queda a ``tol`` de ella
    (``d / cos(paso / 2) = d + tol``)."""
    if not distance_max > 0.0 or not tol > 0.0:
        raise ValueError(f"Distancia y tolerancia de arco deben ser positivas: {distance_max}, {tol}")
    return 2.0 * math.acos(distance_max / (distance_max + tol))


# Simplificar ---------------------------------------------------------------------------------


def _ring(ring: object) -> np.ndarray:
    points = np.asarray(ring, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3:
        raise ValueError(f"Un anillo son al menos 3 vértices (k, 2), no {points.shape}")
    if not np.all(np.isfinite(points)):
        raise ValueError("El anillo tiene coordenadas no finitas")
    return points


def _distance_to_segment(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    d = b - a
    length2 = float(d @ d)
    w = p - a
    if length2 == 0.0:
        return np.hypot(w[:, 0], w[:, 1])
    t = np.clip((w @ d) / length2, 0.0, 1.0)
    return np.hypot(w[:, 0] - t * d[0], w[:, 1] - t * d[1])


def simplify_ring(ring: object, tol: float) -> np.ndarray:
    """Douglas–Peucker de un anillo abierto: el anillo se parte en el vértice más lejano del
    primero y cada mitad se simplifica. Ningún vértice quitado queda a más de ``tol`` del
    resultado (distancia al segmento). Con ``tol <= 0``, una copia. El orden y el sentido se
    conservan; el resultado tiene al menos tres vértices."""
    points = _ring(ring)
    count = len(points)
    if not tol > 0.0 or count <= 3:
        return points.copy()
    far = int(np.argmax(np.hypot(points[:, 0] - points[0, 0], points[:, 1] - points[0, 1])))
    closed = np.vstack([points, points[:1]])
    keep = np.zeros(count, dtype=bool)
    keep[0] = keep[far] = True
    stack = [(0, far), (far, count)]
    while stack:
        first, last = stack.pop()
        if last - first < 2:
            continue
        dist = _distance_to_segment(closed[first + 1:last], closed[first], closed[last])
        at = int(np.argmax(dist))
        if dist[at] > tol:
            middle = first + 1 + at
            keep[middle] = True
            stack.append((first, middle))
            stack.append((middle, last))
    if int(keep.sum()) < 3:
        dist = _distance_to_segment(points, points[0], points[far])
        dist[[0, far]] = -1.0
        keep[int(np.argmax(dist))] = True
    return points[keep]


# Curva cruda ---------------------------------------------------------------------------------


def raw_offset(ring: object, distance: object, *, tol: float, side: int = 1,
               corner: str = "round") -> RawCurve:
    """La curva cruda del desfase de un anillo abierto con una distancia por arista.

    ``distance`` es un escalar o un array ``(k,)`` con la distancia (m, ≥ 0) de la arista que
    sale de cada vértice. ``side`` es ``+1`` hacia el lado derecho de la marcha (hacia fuera en
    un anillo antihorario) o ``-1`` hacia el izquierdo. ``tol`` es la tolerancia de arco (m).
    Devuelve los vértices y la arista de origen de cada uno (:class:`RawCurve`)."""
    points = _ring(ring)
    count = len(points)
    if side not in (1, -1):
        raise ValueError(f"El lado es +1 o -1, no {side!r}")
    if corner not in CORNERS:
        raise ValueError(f"La esquina es una de {CORNERS}, no {corner!r}")
    if not tol > 0.0:
        raise ValueError(f"La tolerancia de arco debe ser positiva: {tol}")
    dist = np.broadcast_to(np.asarray(distance, dtype=np.float64), (count,)).copy()
    if not np.all(np.isfinite(dist)) or np.any(dist < 0.0):
        raise ValueError("Las distancias del desfase deben ser finitas y no negativas")
    along = np.roll(points, -1, axis=0) - points
    length = np.hypot(along[:, 0], along[:, 1])
    if np.any(length == 0.0):
        raise ValueError("El anillo tiene una arista de longitud 0 (simplifícalo antes)")
    tangent = along / length[:, None]
    normal = side * np.column_stack([tangent[:, 1], -tangent[:, 0]])
    d_max = float(dist.max())
    index = np.arange(count, dtype=np.int64)
    if d_max == 0.0:
        return RawCurve(points.copy(), index)

    n_prev, n_next = np.roll(normal, 1, axis=0), normal
    d_prev, d_next = np.roll(dist, 1), dist
    cross = n_prev[:, 0] * n_next[:, 1] - n_prev[:, 1] * n_next[:, 0]
    dot = np.einsum("ij,ij->i", n_prev, n_next)
    delta = np.arctan2(cross, dot)
    step = arc_step(d_max, tol)
    opens = side * delta > 0.0

    # El inglete: el punto a d_prev de la recta anterior y a d_next de la siguiente.
    well = np.abs(cross) > _PARALLEL
    safe = np.where(well, cross, 1.0)
    miter = np.column_stack([(d_prev * n_next[:, 1] - d_next * n_prev[:, 1]) / safe,
                             (n_prev[:, 0] * d_next - n_next[:, 0] * d_prev) / safe])
    same = (np.abs(d_prev - d_next) <= _SAME_M) & (dot > 0.0)
    straight = ~well & same
    miter[straight] = n_prev[straight] * d_prev[straight, None]
    reach = np.hypot(miter[:, 0], miter[:, 1])
    usable = (well | straight) & (reach <= MITER_LIMIT * np.maximum(d_prev, d_next) + _SAME_M)

    single = usable & ((np.abs(delta) < step) | (corner == "miter"))
    fan = ~single & opens & (corner == "round")
    arcs = np.maximum(np.ceil(np.abs(delta) / step).astype(np.int64), 1)
    number = np.where(single, 1, np.where(fan, 2 + arcs, 2))

    owner, k = expand(number)
    out_count = number[owner]
    base = points[owner]
    is_single = out_count == 1
    last = (out_count > 1) & (k == out_count - 1)
    first = (out_count > 1) & (k == 0)
    middle = (out_count > 2) & ~first & ~last

    out = np.empty((len(owner), 2), dtype=np.float64)
    source = np.empty(len(owner), dtype=np.int64)
    out[is_single] = base[is_single] + miter[owner[is_single]]
    source[is_single] = owner[is_single]
    out[first] = base[first] + n_prev[owner[first]] * d_prev[owner[first], None]
    source[first] = (owner[first] - 1) % count
    out[last] = base[last] + n_next[owner[last]] * d_next[owner[last], None]
    source[last] = owner[last]
    if middle.any():
        v, j, m = owner[middle], k[middle], arcs[owner[middle]]
        theta = np.arctan2(n_prev[v, 1], n_prev[v, 0]) + (j - 0.5) * delta[v] / m
        early = (j - 0.5) < m / 2.0
        radius = np.where(early, d_prev[v], d_next[v]) / np.cos(np.abs(delta[v]) / (2.0 * m))
        out[middle] = base[middle] + radius[:, None] * np.column_stack([np.cos(theta), np.sin(theta)])
        source[middle] = np.where(early, (v - 1) % count, v)
    return RawCurve(out, source)


# Cierre morfológico ----------------------------------------------------------------------------


def _raw_ring(ring: np.ndarray, distance: float, side: int, *, tol: float) -> np.ndarray:
    return raw_offset(ring, distance, tol=tol, side=side).points


def closing(ring: object, radius: float, *, tol: float, offset: Offset | None = None,
            merge_m: float = 1e-6) -> np.ndarray:
    """El cierre morfológico (D-15): dilatar ``radius`` y erosionar ``radius``. **Solo ensancha**
    (rellena entrantes más estrechos que ``2·radius``; nunca abre ni quita nada): con arcos
    circunscritos el resultado contiene al anillo. ``ring`` es antihorario. ``offset`` es el
    desfase a usar, ``(anillo, distancia, lado) -> anillo`` (``+1`` fuera, ``-1`` dentro); por
    defecto, la curva cruda, **válida solo en un anillo convexo** (en un vértice cóncavo se
    cruza); el desfase completo de la spec 018 T07 la sustituye. Los vértices a menos de ``merge_m``
    seguidos se funden (la erosión de un arco da el mismo punto varias veces)."""
    points = _ring(ring)
    if not radius > 0.0:
        raise ValueError(f"El radio del cierre debe ser positivo: {radius}")
    run: Offset = offset if offset is not None else (
        lambda r, d, s: _raw_ring(r, d, s, tol=tol))
    result = run(run(points, radius, 1), radius, -1)
    step = np.hypot(*(result - np.roll(result, 1, axis=0)).T)
    keep = step > merge_m
    return result[keep] if int(keep.sum()) >= 3 else result
