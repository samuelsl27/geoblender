# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos de rendimiento de la cubicación entre superficies (spec 011, T27; plan 011 §2.2 y
§7.3; ``tests/rendimiento/res/test_res_perf.py``). Solo sintéticos: se generan al pedirlos, no se
versionan y los borra quien los escribe. Solo numpy y la biblioteca estándar (sin ``geoblender``:
sirven también dentro de Blender, T28).

- **La rejilla de referencia** (spec 011 §5): :data:`COLS` × :data:`ROWS` celdas de :data:`STEP`
  m (2,81 M), oeste :data:`WEST` y sur :data:`SOUTH`. :func:`surfaces` da, en los centros de
  celda ``(x, y)`` absolutos, la partida (un terreno con colinas, una pendiente, un ondulado de
  metros y ruido de 5 cm, con un hueco sin dato de 80 × 100 celdas), la final (una corta de 120 m
  de fondo y un relleno de 15 m) y las bases de las unidades (paralelas al terreno con un
  ondulado; las de las dos antrópicas, el terreno menos su espesor; dos que se cruzan en una
  franja y una sin dato en parte) y los espesores de las antrópicas: los de los prototipos del
  plan (``plan-011/proto``), con dos bases más (:data:`UNITS_TABLE`).
- **Los dominios** (:func:`domain_rings`): 20 que parten la rejilla (5 × 4) con bordes ondulados
  compartidos (31 920 vértices).
- **La columna** (:func:`column_units`): la de RNF-011-02, :data:`UNITS_BREAKDOWN` unidades (un
  escombro y un acopio antrópicos sueltos, una compuesta de arena y arcilla y cinco naturales
  in situ) y, para la tabla de RNF-011-05 y RNF-011-06 (20 dominios × 30 rodajas × 10
  unidades), :data:`UNITS_TABLE`, con una arenisca y una pizarra sobre el muro.
  :func:`parameter_values`: sus densidades, K y porcentajes, **valores sintéticos de prueba**,
  de ningún material real (D-8).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np

COLS = 1654
ROWS = 1699
STEP = 1.0
WEST = 735_000.0
SOUTH = 4_434_000.0
NORTH = SOUTH + ROWS * STEP
EAST = WEST + COLS * STEP
WINDOW = (WEST, SOUTH, EAST, NORTH)
"""La ventana del proyecto: oeste, sur, este y norte (m)."""

START = "Partida"
FINAL = "Final"
FIELD = "dominio"
"""El campo de la capa de dominios."""
DOMAINS = 20
BENCHES = 30
UNITS_BREAKDOWN = 8  # RNF-011-02
UNITS_TABLE = 10  # RNF-011-05 y RNF-011-06

_DEPTHS_M = (0.0, 0.0, 3.0, 25.0, 45.0, 70.0, 95.0, 105.0, 112.0)
"""Lo que baja cada base respecto al terreno (las dos primeras, las de las antrópicas, las
sustituye el terreno menos su espesor)."""
_ANTHROPIC_CENTERS = ((400, 500), (1200, 1300))  # (columna, fila) del centro de cada espesor
_NOISE_SEED = 1
_THICKNESS_SEED = 7


def base_label(position: int) -> str:
    """La rejilla de la base de la unidad ``position`` («Base u3»)."""
    return f"Base u{position}"


def thickness_label(position: int) -> str:
    """La rejilla del espesor de la antrópica ``position`` («Espesor u0»)."""
    return f"Espesor u{position}"


@dataclass(frozen=True)
class ComponentSpec:
    """Un componente de una unidad compuesta y su porcentaje (sintético)."""

    code: str
    name: str
    role: str
    percent: float


@dataclass(frozen=True)
class UnitSpec:
    """Una unidad de la columna, con las rejillas de su base y su espesor (o ``None``)."""

    code: str
    name: str
    kind: str
    role: str | None
    state: str
    base: str | None
    thickness: str | None
    components: tuple[ComponentSpec, ...] = ()


_UNITS = (
    UnitSpec("escombro", "Escombro", "anthropic", "waste", "loose", base_label(0),
             thickness_label(0)),
    UnitSpec("acopio", "Acopio", "anthropic", "useful", "loose", base_label(1),
             thickness_label(1)),
    UnitSpec("montera", "Montera", "natural", "waste", "in_situ", base_label(2), None),
    UnitSpec("caliza", "Caliza", "natural", "useful", "in_situ", base_label(3), None),
    UnitSpec("mixta", "Capa mixta", "compound", None, "in_situ", base_label(4), None,
             (ComponentSpec("arena", "Arena", "useful", 70.0),
              ComponentSpec("arcilla", "Arcilla", "waste", 30.0))),
    UnitSpec("margas", "Margas", "natural", "waste", "in_situ", base_label(5), None),
    UnitSpec("dolomia", "Dolomía", "natural", "useful", "in_situ", base_label(6), None),
)
_EXTRA = (
    UnitSpec("arenisca", "Arenisca", "natural", "useful", "in_situ", base_label(7), None),
    UnitSpec("pizarra", "Pizarra", "natural", "waste", "in_situ", base_label(8), None),
)
_WALL = UnitSpec("muro", "Muro", "natural", "waste", "in_situ", None, None)


def column_units(count: int) -> tuple[UnitSpec, ...]:
    """La columna de :data:`UNITS_BREAKDOWN` o :data:`UNITS_TABLE` unidades, de arriba abajo
    (la última, el muro, sin base)."""
    if count == UNITS_BREAKDOWN:
        return (*_UNITS, _WALL)
    if count == UNITS_TABLE:
        return (*_UNITS, *_EXTRA, _WALL)
    raise ValueError(f"la columna es de {UNITS_BREAKDOWN} o {UNITS_TABLE} unidades, no {count}")


def labels(count: int) -> tuple[str, ...]:
    """Las rejillas que necesita la columna de ``count`` unidades: la partida, la final y las
    bases y los espesores de sus unidades."""
    found = [START, FINAL]
    for unit in column_units(count):
        found += [label for label in (unit.base, unit.thickness) if label is not None]
    return tuple(found)


def parameter_values(units: Iterable[UnitSpec]) -> list[tuple[str, str | None, str, float]]:
    """Los parámetros sintéticos de ``units``: ``(unidad, componente o None, "density" |
    "swell" | "percent", valor)``; la densidad (t/m³) y el K de cada unidad que no es compuesta
    (según su posición) y de cada componente, y el porcentaje de cada componente."""
    found: list[tuple[str, str | None, str, float]] = []
    for position, unit in enumerate(units):
        if not unit.components:
            found.append((unit.code, None, "density", 2.0 + 0.05 * position))
            found.append((unit.code, None, "swell", 1.2 + 0.03 * position))
            continue
        for number, item in enumerate(unit.components):
            found.append((unit.code, item.code, "density", 2.3 + 0.1 * number))
            found.append((unit.code, item.code, "swell", 1.3 + 0.05 * number))
            found.append((unit.code, item.code, "percent", item.percent))
    return found


def _terrain(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    east, up = x - WEST, y - SOUTH
    return (850.0 + 60.0 * np.sin(east / 150.0) * np.cos(up / 120.0) + 0.02 * east
            + 2.0 * np.sin(east / 7.3) * np.sin(up / 5.1))


def surfaces(x: np.ndarray, y: np.ndarray,
             wanted: Sequence[str] | None = None) -> Mapping[str, np.ndarray]:
    """Las superficies de la rejilla de referencia en los centros de celda ``x``, ``y``
    (absolutos, ``(ROWS, COLS)``, fila 0 al norte), float64 con NaN sin dato: las de ``wanted``
    (por defecto, todas: :func:`labels` de :data:`UNITS_TABLE`)."""
    shape = (ROWS, COLS)
    if x.shape != shape or y.shape != shape:
        raise ValueError(f"los centros de celda son de {shape}, no {x.shape} y {y.shape}")
    start = _terrain(x, y) + np.random.default_rng(_NOISE_SEED).normal(0.0, 0.05, shape)
    cx, cy = WEST + COLS / 2, SOUTH + ROWS / 2
    radius = np.hypot(x - cx, y - cy)
    final = start - np.clip(120.0 - 0.6 * np.maximum(radius - 100.0, 0.0), 0.0, None)
    final = final + np.clip(15.0 - 0.1 * np.hypot(x - (WEST + 300.0), y - (NORTH - 300.0)),
                            0.0, None)
    del radius
    start[100:180, 1400:1500] = np.nan
    columns = np.arange(COLS, dtype=np.float64)[None, :]
    bases = [start - depth - 2.0 * np.sin(columns / (40 + 7 * k)) - k * 0.3
             for k, depth in enumerate(_DEPTHS_M)]
    rng = np.random.default_rng(_THICKNESS_SEED)
    rows, cols = np.mgrid[0:ROWS, 0:COLS]
    found: dict[str, np.ndarray] = {START: start, FINAL: final}
    for position, (ucol, urow) in enumerate(_ANTHROPIC_CENTERS):
        thickness = np.clip(8.0 - 0.05 * np.hypot(cols - ucol, rows - urow), 0.0, None)
        thickness = np.clip(thickness + rng.normal(0.0, 0.05, shape), 0.0, None)
        bases[position] = start - thickness
        found[thickness_label(position)] = thickness
    del rows, cols
    bases[4][800:820, :] = bases[3][800:820, :] + 1.0  # dos bases que se cruzan
    bases[5][1500:1550, 200:400] = np.nan  # una base sin dato en parte
    for position, values in enumerate(bases):
        found[base_label(position)] = values
    chosen = labels(UNITS_TABLE) if wanted is None else tuple(wanted)
    unknown = [label for label in chosen if label not in found]
    if unknown:
        raise ValueError(f"no hay superficies {unknown}")
    return {label: found[label] for label in chosen}


def domain_rings() -> list[np.ndarray]:
    """Los :data:`DOMAINS` dominios: anillos cerrados absolutos (m) que parten la rejilla en
    5 × 4, con los lados interiores ondulados (6 m) y compartidos por los dos vecinos (el mismo
    trazado, al revés) y los del borde rectos; 400 puntos por lado (31 920 vértices)."""
    xs = np.linspace(WEST + 7.3, WEST + COLS - 9.1, 6)
    ys = np.linspace(SOUTH + 5.7, SOUTH + ROWS - 6.2, 5)
    cache: dict[tuple[tuple[float, ...], tuple[float, ...]], np.ndarray] = {}

    def wavy(p: np.ndarray, q: np.ndarray, amplitude: float, seed: int) -> np.ndarray:
        t = np.linspace(0.0, 1.0, 400)
        points = p[None, :] + t[:, None] * (q - p)[None, :]
        normal = np.array([-(q - p)[1], (q - p)[0]]) / np.hypot(*(q - p))
        offset = amplitude * np.sin(np.pi * t * (3 + seed % 5)) * np.sin(np.pi * t)
        return points + offset[:, None] * normal[None, :]

    def side(p: np.ndarray, q: np.ndarray) -> np.ndarray:
        key = (tuple(np.round(p, 6)), tuple(np.round(q, 6)))
        back = (key[1], key[0])
        if back in cache:
            return cache[back][::-1]
        if key not in cache:
            seed = int(abs(p[0] * 7 + p[1] * 13 + q[0] * 3 + q[1])) % 97
            straight = ((p[0] in (xs[0], xs[-1]) and q[0] == p[0])
                        or (p[1] in (ys[0], ys[-1]) and q[1] == p[1]))
            cache[key] = wavy(p, q, 0.0 if straight else 6.0, seed)
        return cache[key]

    rings = []
    for i in range(5):
        for j in range(4):
            a = np.array([xs[i], ys[j]])
            b = np.array([xs[i + 1], ys[j]])
            c = np.array([xs[i + 1], ys[j + 1]])
            d = np.array([xs[i], ys[j + 1]])
            ring = np.concatenate([side(a, b)[:-1], side(b, c)[:-1], side(c, d)[:-1],
                                   side(d, a)[:-1]])
            rings.append(np.vstack([ring, ring[:1]]))
    return rings
