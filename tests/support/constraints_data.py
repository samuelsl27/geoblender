# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos de escala de la 012 que no necesitan el paquete (``plan.md`` §2.2; spec 012, T35 y
T31; RNF-012-01 a RNF-012-06).

Solo numpy y la biblioteca estándar: los usan a la vez las pruebas de rendimiento con el Python de
Blender (``tests/support/constraints_scale.py``, que los convierte a las clases de su copia del
paquete, ``import_geoblender``) y las de dentro de Blender
(``tests/rendimiento/blender/perf_constraints.py``, que los convierte a las clases de la extensión
habilitada: allí no se puede cargar otra copia del paquete). No se versionan datos: se generan con
la semilla :data:`SEED`, sin ningún dato de cliente.

- La rejilla de :data:`COLS` × :data:`ROWS` celdas de 1 m (2,81 M) y su ventana.
- Las :data:`COUNT` restricciones de §2.2 (:func:`build_specs`), de unos 100.000 vértices: el límite
  legal y el perímetro, de 2.000 vértices cada uno (estrellas de radio casi constante); 30 puntos,
  30 líneas de 200 vértices y 40 polígonos de 500 con un resguardo de 5 a 50 m, de los tipos que
  lo piden (intocable, exclusión, resguardo, «preferible no afectar» y «sin relleno»); y 398
  polígonos de 176 vértices sin resguardo (los otros cinco tipos).
- Las superficies de verificar: la partida y las finales de las dos formas de §2.2
  (:func:`window_values`, que cambian en toda la ventana, y :func:`local_values`, que cambian en
  unos abultamientos).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

WEST, SOUTH = 699_000.0, 4_399_000.0
COLS, ROWS = 1654, 1699
STEP_M = 1.0
EAST, NORTH = WEST + COLS * STEP_M, SOUTH + ROWS * STEP_M
SEED = 20_261_031
COUNT = 500
FINALS = 3
"""Las superficies finales de cada forma."""


def window() -> tuple[float, float, float, float]:
    """La ventana del proyecto de escala: (oeste, sur, este, norte)."""
    return (WEST, SOUTH, EAST, NORTH)


# --- Las restricciones --------------------------------------------------------------------------


def star(rng: np.random.Generator, cx: float, cy: float, radius: float, n: int,
         jitter: float = 0.3) -> np.ndarray:
    """Un anillo cerrado y antihorario de ``n`` vértices (simple: radio positivo a ángulos
    crecientes)."""
    step = 2.0 * math.pi / n
    angles = np.arange(n) * step + (rng.random(n) - 0.5) * 0.6 * step
    radii = radius * (1.0 + jitter * (rng.random(n) - 0.5) * 2.0)
    ring = np.column_stack([cx + radii * np.cos(angles), cy + radii * np.sin(angles)])
    return np.vstack([ring, ring[:1]])


def path(rng: np.random.Generator, x: float, y: float, n: int, length: float) -> np.ndarray:
    """Una línea de ``n`` vértices que empieza en (``x``, ``y``) y gira poco (``length`` m)."""
    heading = rng.uniform(0, 2 * math.pi)
    steps = length / (n - 1)
    turns = np.cumsum((rng.random(n - 1) - 0.5) * 0.4) + heading
    xy = np.column_stack([np.cumsum(np.cos(turns)) * steps, np.cumsum(np.sin(turns)) * steps])
    return np.vstack([[x, y], np.array([x, y]) + xy])


@dataclass(frozen=True, slots=True)
class ConstraintSpec:
    """Una restricción de §2.2 sin las clases del paquete: su nombre, su tipo (el valor de
    ``ConstraintType``: ``legal_limit``, ``untouchable``…), su geometría (``polygon``, ``line`` o
    ``point``), sus vértices absolutos (``(n, 2)``, float64) y sus parámetros (el sufijo de su
    clave, ``ConstraintParam``: ``active``, ``buffer_out_m``, ``buffer_in_m``, ``weight``; su
    valor), en el orden en que se dan de alta."""

    name: str
    ctype: str
    kind: str
    part: np.ndarray
    params: tuple[tuple[str, Any], ...]


# Los tipos con resguardo hacia fuera y los que no lo tienen (valores de ``ConstraintType``).
BUFFERED = ("untouchable", "exclusion", "setback", "avoid", "no_fill")
PLAIN = ("no_cut", "no_fill", "fill_only", "restoration_only", "requires_access")


def build_specs(rng: np.random.Generator | None = None) -> tuple[ConstraintSpec, ...]:
    """Las :data:`COUNT` restricciones de §2.2 con ``rng`` (por defecto, la semilla
    :data:`SEED`): el límite legal (10 m hacia dentro) y el perímetro, 30 puntos, 30 líneas y 40
    polígonos con resguardo de 5 a 50 m y 398 polígonos sin él."""
    rng = np.random.default_rng(SEED) if rng is None else rng
    found: list[ConstraintSpec] = []
    cx, cy = (WEST + EAST) / 2.0, (SOUTH + NORTH) / 2.0

    def add(name: str, ctype: str, kind: str, part: np.ndarray, buffer_out: float | None,
            buffer_in: float | None = None, weight: float | None = None) -> None:
        params: list[tuple[str, Any]] = [("active", True)]
        if buffer_out is not None:
            params.append(("buffer_out_m", float(buffer_out)))
        if buffer_in is not None:
            params.append(("buffer_in_m", float(buffer_in)))
        if weight is not None and ctype == "avoid":
            params.append(("weight", float(weight)))
        found.append(ConstraintSpec(name, ctype, kind, part, tuple(params)))

    def at() -> tuple[float, float]:
        return (float(rng.uniform(WEST + 120, EAST - 120)),
                float(rng.uniform(SOUTH + 120, NORTH - 120)))

    add("Concesión", "legal_limit", "polygon", star(rng, cx, cy, 760.0, 2000, 0.06), None, 10.0)
    add("Perímetro", "action_perimeter", "polygon",
        star(rng, cx + 40, cy - 30, 640.0, 2000, 0.08), None)
    for index in range(30):
        x, y = at()
        add(f"Punto {index:02d}", BUFFERED[index % 5], "point", np.array([[x, y]]),
            float(rng.uniform(5, 50)), weight=2.0)
    for index in range(30):
        x, y = at()
        add(f"Línea {index:02d}", BUFFERED[index % 5], "line", path(rng, x, y, 200, 300.0),
            float(rng.uniform(5, 50)), weight=2.0)
    for index in range(40):
        x, y = at()
        add(f"Zona {index:02d}", BUFFERED[index % 5], "polygon",
            star(rng, x, y, float(rng.uniform(30, 120)), 500), float(rng.uniform(5, 50)),
            weight=2.0)
    for index in range(398):
        x, y = at()
        add(f"Recinto {index:03d}", PLAIN[index % 5], "polygon",
            star(rng, x, y, float(rng.uniform(10, 60)), 176), 0.0)
    return tuple(found)


# --- Las superficies de verificar ----------------------------------------------------------------


def plane() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Las columnas, las filas y el plano inclinado de partida de la rejilla de escala."""
    x = np.arange(COLS)[None, :].astype(np.float64)
    y = np.arange(ROWS)[:, None].astype(np.float64)
    return x, y, 650.0 + 0.02 * x + 0.01 * y


def window_values(rng: np.random.Generator, kind: int) -> np.ndarray:
    """Las cotas de la partida (``kind`` 0, el plano inclinado) y de las finales (1 a 3) de la
    forma ``window``: el plano con una onda de 3 m en toda la ventana y 5 mm de ruido."""
    x, y, base = plane()
    if kind:
        base = base + 3.0 * np.sin(x / (150.0 + 40 * kind)) * np.cos(y / (170.0 + 30 * kind))
        base = base + (rng.random((ROWS, COLS)) - 0.5) * 0.01
    return base


def local_values(rng: np.random.Generator) -> np.ndarray:
    """Las cotas de una superficie de la forma ``local``: el plano con 8 abultamientos de ±3 m
    (σ de 25 m) y 5 mm de ruido en toda la ventana (la partida y cada final, con otro azar)."""
    x, y, base = plane()
    for _ in range(8):
        cx, cy = rng.uniform(150, COLS - 150), rng.uniform(150, ROWS - 150)
        amplitude = rng.choice([-3.0, 3.0])
        base = base + amplitude * np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * 25.0**2))
    return base + (rng.random((ROWS, COLS)) - 0.5) * 0.01


def shape_values(shape: str) -> list[np.ndarray]:
    """Las cotas de la partida y de las :data:`FINALS` finales de la forma ``shape``
    (``window`` o ``local``), con la semilla de cada una (:data:`SEED`, más 100 en ``local``)."""
    if shape == "window":
        rng = np.random.default_rng(SEED)
        return [window_values(rng, kind) for kind in range(FINALS + 1)]
    if shape == "local":
        return [local_values(np.random.default_rng(SEED + 100 + kind))
                for kind in range(FINALS + 1)]
    raise ValueError(f"la forma de las finales es «window» o «local», no {shape!r}")
