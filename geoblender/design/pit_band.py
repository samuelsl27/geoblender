# SPDX-License-Identifier: GPL-3.0-or-later
"""Las polilíneas de la corta adaptadas a la banda de sus rampas (spec 018, T21c2; HU-018-4; RF-018-21 y 28; plan 018 §5.4 A10).

La superficie de la corta (:mod:`design.pit_surface`) triangula las polilíneas de los bancos y los bordes de las rampas como aristas obligatorias. Pero **la banda de una rampa
se pisa con los pies y las crestas**: su borde izquierdo corre pegado al pie del tramo (y lo cruza donde el eje redondeado corta una esquina), el eje y el borde derecho cruzan
la cresta y el pie de cada banco, y su Z (la de la rampa, que sube) no es la del pie (la del banco, plana). Una triangulación con aristas que se cruzan se rechaza, y no debe
relajarse nada. :func:`arrange` da la **disposición plana**: de cada polilínea se quita lo que cae **bajo la banda** (el polígono de sus bordes con un pequeño margen,
``margin_m``) y se corta en el borde de ese polígono (con la Z de la propia polilínea en ese punto); la banda queda con sus tres líneas (borde izquierdo, eje, borde derecho,
cada una con su Z por estaciones) y la superficie dentro de ella es la de la rampa. Lo quitado es lo que la rampa sustituye: la cara retranqueada y la berma que continúa en el
enlace.

Ninguna entrada se modifica. Todo es determinista y sin ``set`` ni orden de hash: las polilíneas salen en el orden de entrada y, de cada una, sus trozos en el orden del anillo
(el primer trozo, el que sigue al primer lado quitado). Python puro con numpy (nivel 8); lo importa :mod:`design.pit_surface`.
"""

from __future__ import annotations

from collections.abc import Generator, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

__all__ = ["MARGIN_M", "Piece", "arrange", "arrange_units", "band_polygon"]

MARGIN_M: float = 0.05
"""El margen del polígono de la banda con el que se quita lo que cae bajo ella (m): lo que se aparta del borde la polilínea que corre pegada a él (``arc_tol`` 5 cm)."""
_CHUNK = 4_000_000
"""Los pares (lado, lado) que se cruzan de una vez: acota la memoria de los cruces."""


@dataclass(frozen=True, slots=True, eq=False)
class Piece:
    """Un trozo de polilínea para la triangulación: sus ``vertices`` ``(k, 3)`` absolutos y si es un anillo (``closed``; sin repetir el primer vértice)."""

    vertices: np.ndarray
    closed: bool


def band_polygon(band: Any, margin_m: float = MARGIN_M) -> np.ndarray:
    """El polígono ``(m, 2)`` de la banda ``band`` (sus ``breaklines``: borde izquierdo, eje y borde derecho, ``(n, 3)``): el borde izquierdo de ida y el derecho de vuelta, **ensanchado** ``margin_m``
    hacia fuera por los dos lados y por los dos extremos (en el sentido del eje)."""
    left, axis, right = (np.asarray(line, dtype=np.float64)[:, :2] for line in band.breaklines)
    half = np.hypot(*(left - axis).T)
    if not bool((half > 0.0).all()) or len(axis) < 2:
        raise ValueError("la banda de una rampa tiene al menos dos estaciones y un semiancho > 0")
    normal = (left - axis) / half[:, None]
    left = left + margin_m * normal
    right = right - margin_m * normal
    along = np.diff(axis, axis=0)
    along = along / np.hypot(*along.T)[:, None]
    for line in (left, right):
        line[0] = line[0] - margin_m * along[0]
        line[-1] = line[-1] + margin_m * along[-1]
    return np.vstack([left, right[::-1]])


def _crossings(a: np.ndarray, b: np.ndarray, polygon: np.ndarray) -> list[list[float]]:
    """Por cada lado ``a[i] → b[i]``, las ``t`` ∈ (0, 1) (ordenadas, sin repetir) donde cruza el borde de ``polygon``."""
    c = polygon
    d = np.roll(polygon, -1, axis=0)
    r = b - a
    s = d - c
    found: list[list[float]] = [[] for _ in range(len(a))]
    step = max(1, _CHUNK // max(len(c), 1))
    for first in range(0, len(a), step):
        sl = slice(first, first + step)
        rows = r[sl][:, None, :]
        denom = rows[..., 0] * s[None, :, 1] - rows[..., 1] * s[None, :, 0]
        diff = c[None, :, :] - a[sl][:, None, :]
        with np.errstate(divide="ignore", invalid="ignore"):
            t = (diff[..., 0] * s[None, :, 1] - diff[..., 1] * s[None, :, 0]) / denom
            u = (diff[..., 0] * rows[..., 1] - diff[..., 1] * rows[..., 0]) / denom
        hit = (denom != 0.0) & (t > 0.0) & (t < 1.0) & (u >= 0.0) & (u < 1.0)
        for row, col in zip(*np.nonzero(hit), strict=True):
            found[first + int(row)].append(float(t[row, col]))
    return [sorted(set(values)) for values in found]


def _inside(points: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    """Si cada punto de ``points`` ``(k, 2)`` está dentro de ``polygon`` (par-impar)."""
    c = polygon
    d = np.roll(polygon, -1, axis=0)
    out = np.zeros(len(points), dtype=bool)
    step = max(1, _CHUNK // max(len(c), 1))
    for first in range(0, len(points), step):
        p = points[first:first + step]
        across = (c[None, :, 1] > p[:, None, 1]) != (d[None, :, 1] > p[:, None, 1])
        with np.errstate(divide="ignore", invalid="ignore"):
            x = c[None, :, 0] + (p[:, None, 1] - c[None, :, 1]) * (d[None, :, 0] - c[None, :, 0]) / (d[None, :, 1] - c[None, :, 1])
        out[first:first + step] = (np.sum(across & (p[:, None, 0] < x), axis=1) % 2).astype(bool)
    return out


def _split_units(vertices: np.ndarray, polygons: Sequence[np.ndarray]) -> Generator[None, None, list[Piece]]:
    """El anillo ``vertices`` ``(k, 3)`` sin lo que cae dentro de algún polígono: el mismo anillo si no toca ninguno; si no, trozos abiertos cortados en el borde. Cede
    una unidad por polígono de banda en la búsqueda de cruces y otra en la de lo que cae dentro (T22b: RNF-018-06)."""
    ring = np.asarray(vertices, dtype=np.float64)
    nxt = np.roll(ring, -1, axis=0)
    cuts: list[list[float]] = [[] for _ in range(len(ring))]
    for polygon in polygons:
        lo, hi = polygon.min(axis=0), polygon.max(axis=0)
        near = np.flatnonzero(~((np.maximum(ring[:, :2], nxt[:, :2]) < lo).any(axis=1) | (np.minimum(ring[:, :2], nxt[:, :2]) > hi).any(axis=1)))
        if not near.size:
            continue
        for index, values in zip(near, _crossings(ring[near, :2], nxt[near, :2], polygon), strict=True):
            cuts[int(index)].extend(values)
        yield
    rows: list[np.ndarray] = []
    for index in range(len(ring)):
        rows.append(ring[index][None, :])
        if cuts[index]:
            t = np.array(sorted(set(cuts[index])))
            rows.append(ring[index] + t[:, None] * (nxt[index] - ring[index]))
    dense = np.vstack(rows)
    following = np.roll(dense, -1, axis=0)
    mid = 0.5 * (dense[:, :2] + following[:, :2])
    drop = np.zeros(len(dense), dtype=bool)
    for polygon in polygons:
        drop |= _inside(mid, polygon)
        yield
    if not drop.any():
        return [Piece(ring, True)]
    if drop.all():
        return []
    first = int(np.argmax(drop))  # el anillo parte tras un lado quitado: ningún trozo cruza el comienzo
    order = (np.arange(len(dense)) + first) % len(dense)
    pieces: list[Piece] = []
    chain: list[int] = []
    for edge in order:
        if drop[edge]:
            if chain:
                pieces.append(Piece(np.vstack([dense[chain], dense[(chain[-1] + 1) % len(dense)][None, :]]), False))
                chain = []
        else:
            chain.append(int(edge))
    if chain:
        pieces.append(Piece(np.vstack([dense[chain], dense[(chain[-1] + 1) % len(dense)][None, :]]), False))
    return pieces


def _split(vertices: np.ndarray, polygons: Sequence[np.ndarray]) -> list[Piece]:
    """:func:`_split_units` hasta el final."""
    work = _split_units(vertices, polygons)
    while True:
        try:
            next(work)
        except StopIteration as done:
            result: list[Piece] = done.value
            return result


def arrange_units(polylines: Sequence[Any], bands: Sequence[Any], margin_m: float = MARGIN_M) -> Generator[None, None, tuple[Piece, ...]]:
    """:func:`arrange` por unidades (T22b; RNF-018-06): cede una por polilínea y por banda, para componerlas con ``pace_units``, y devuelve lo mismo, bit a bit."""
    polygons = [band_polygon(item, margin_m) for item in bands]
    if not polygons:
        return tuple(Piece(np.asarray(item.vertices, dtype=np.float64), bool(item.closed)) for item in polylines)
    pieces: list[Piece] = []
    for item in polylines:
        if not item.closed:
            raise ValueError("la disposición plana de una polilínea abierta no se calcula todavía")
        pieces.extend((yield from _split_units(item.vertices, polygons)))
    return tuple(pieces)


def arrange(polylines: Sequence[Any], bands: Sequence[Any], margin_m: float = MARGIN_M) -> tuple[Piece, ...]:
    """**La disposición plana** (T21c2): los trozos de ``polylines`` (cada una con ``vertices`` ``(k, 3)`` y ``closed``) que quedan **fuera** de la banda de cada rampa de ``bands``
    (cada una con ``breaklines``; :func:`band_polygon`), en el orden de las polilíneas. Sin bandas, las mismas polilíneas. Una polilínea abierta se corta igual
    (sus trozos son abiertos)."""
    work = arrange_units(polylines, bands, margin_m)
    while True:
        try:
            next(work)
        except StopIteration as done:
            result: tuple[Piece, ...] = done.value
            return result
