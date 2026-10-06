# SPDX-License-Identifier: GPL-3.0-or-later
"""La única conversión absoluta ↔ local de Geoblender (spec 002; RF-002-25, RF-002-26;
ADR-0005; ARQ-14).

Blender guarda vértices, matrices y ``FloatProperty`` en float32: una coordenada UTM de
4 400 000,456 vuelve como 4 400 000,5. Geoblender trabaja en la escena en coordenadas
**locales** = absolutas − GeoOrigin, restadas aquí en float64 y vectorizadas; ``bl``
pasa a float32 después. Fuera de este módulo nadie resta ni suma el GeoOrigin (lo vigila
la regla ARQ-14, ``tools/gbtools/rules/georef.py``).

- :func:`world_to_local`: absolutas (float64, CRS del proyecto, m) → locales (float64).
  Rechaza absolutas en float32: ya han perdido precisión (Silvestre N-03).
- :func:`local_to_world`: locales (float32 o float64, lo que devuelve Blender) →
  absolutas (float64).
- :func:`precision_report`: si unos puntos o las esquinas de una ventana (absolutos)
  quedan a más de 8 000 m del GeoOrigin en X o en Y, cuántos o cuáles y el error máximo
  estimado de float32 en la escena, ``2^(⌊log2 m⌋ − 24)`` m para |local| = m (0,244 mm a
  8 km, 0,488 mm a 16 km, 0,977 mm a 20 km).

Las coordenadas son arrays de forma ``(..., 2)`` (X, Y) o ``(..., 3)`` (X, Y, Z).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

from .origin import GeoOrigin, Window

PRECISION_LIMIT_M = 8_000.0  # ±8 km del GeoOrigin en X y en Y (ADR-0005, punto 6)
FLOAT32_MANTISSA_BITS = 24
CORNER_NAMES: tuple[str, ...] = ("suroeste", "sureste", "noreste", "noroeste")
_THIN_SPACE = " "  # espacio fino de miles


def _coordinates(values: object, what: str, *, allow_float32: bool) -> np.ndarray:
    array = np.asarray(values)
    kind = array.dtype.kind
    valid = array.dtype == np.float64 or kind in "iu"
    if allow_float32:
        valid = valid or array.dtype == np.float32
    if not valid:
        expected = "float64 o float32" if allow_float32 else "float64"
        raise TypeError(
            f"{what}: las coordenadas llegan en {array.dtype} y deben llegar en "
            f"{expected}; unas absolutas en float32 ya han perdido precisión (0,5 m en "
            "nortes UTM, ADR-0005)"
        )
    if array.ndim == 0 or array.shape[-1] not in (2, 3):
        raise ValueError(
            f"{what}: la última dimensión debe ser 2 (X, Y) o 3 (X, Y, Z) y la forma es "
            f"{array.shape}"
        )
    return array


def _offset(origin: GeoOrigin, columns: int) -> np.ndarray:
    return np.array((origin.x0, origin.y0, origin.z0)[:columns], dtype=np.float64)


def world_to_local(xyz_world: np.ndarray, origin: GeoOrigin) -> np.ndarray:
    """Absolutas (float64 o enteros) → locales en float64: absoluta − (X0, Y0, Z0).
    ``TypeError`` si llegan en float32 u otro tipo; ``ValueError`` si la forma no es
    ``(..., 2)`` ni ``(..., 3)``. No modifica la entrada."""
    world = _coordinates(xyz_world, "world_to_local", allow_float32=False)
    return world.astype(np.float64) - _offset(origin, world.shape[-1])


def local_to_world(xyz_local: np.ndarray, origin: GeoOrigin) -> np.ndarray:
    """Locales (float32 o float64) → absolutas en float64: local + (X0, Y0, Z0)."""
    local = _coordinates(xyz_local, "local_to_world", allow_float32=True)
    return local.astype(np.float64) + _offset(origin, local.shape[-1])


def float32_error_mm(local_m: float) -> float:
    """Error máximo de redondeo de float32 (mm) para una coordenada local de magnitud
    ``|local_m|`` (m): la mitad de su paso, ``2^(⌊log2 m⌋ − 24)`` m; 0 en el origen."""
    magnitude = abs(float(local_m))
    if magnitude == 0.0:
        return 0.0
    exponent = math.frexp(magnitude)[1] - 1  # ⌊log2 m⌋, exacto
    return math.ldexp(1.0, exponent - FLOAT32_MANTISSA_BITS) * 1000.0


def _thousands(value: float) -> str:
    return f"{value:,.0f}".replace(",", _THIN_SPACE)


@dataclass(frozen=True)
class PrecisionReport:
    """Resultado de :func:`precision_report`.

    ``max_abs_local_m``: la mayor |X| o |Y| local; ``max_error_mm``: su error estimado de
    float32; ``points_outside``: cuántos puntos pasan del límite (con puntos);
    ``corners_outside``: qué esquinas lo pasan (con una ventana), en el orden suroeste,
    sureste, noreste, noroeste.
    """

    kind: Literal["points", "window"]
    limit_m: float
    max_abs_local_m: float
    max_error_mm: float
    points_outside: int = 0
    corners_outside: tuple[str, ...] = ()

    @property
    def within_limit(self) -> bool:
        """Verdadero si todo queda dentro del límite."""
        return self.points_outside == 0 and not self.corners_outside

    @property
    def message(self) -> str:
        """El aviso para el usuario, en español (vacío si no hay nada que avisar)."""
        if self.within_limit:
            return ""
        if self.kind == "window":
            names = list(self.corners_outside)
            listed = names[-1]
            if len(names) > 1:
                listed = ", ".join(names[:-1]) + " y " + listed
            subject = (
                f"La esquina {listed} de la ventana está"
                if len(names) == 1
                else f"Las esquinas {listed} de la ventana están"
            )
        elif self.points_outside == 1:
            subject = "1 punto está"
        else:
            subject = f"{self.points_outside} puntos están"
        error = f"{self.max_error_mm:.3f}".replace(".", ",")
        return (
            f"{subject} a más de {_thousands(self.limit_m)} m del GeoOrigin en X o en Y "
            f"(hasta {_thousands(self.max_abs_local_m)} m): error máximo estimado en la "
            f"escena {error} mm; el criterio es ≤ 0,5 mm (ADR-0005)"
        )


def precision_report(
    points: np.ndarray | Window, origin: GeoOrigin, limit_m: float = PRECISION_LIMIT_M
) -> PrecisionReport:
    """Comprueba que unos puntos absolutos (float64) o las esquinas de una ventana quedan
    a menos de ``limit_m`` del GeoOrigin en X y en Y (RF-002-26)."""
    if isinstance(points, Window):
        corners = np.array(
            [
                (points.xmin, points.ymin),
                (points.xmax, points.ymin),
                (points.xmax, points.ymax),
                (points.xmin, points.ymax),
            ]
        )
        distances = np.abs(world_to_local(corners, origin))
        outside = (distances > limit_m).any(axis=1)
        names = tuple(name for name, out in zip(CORNER_NAMES, outside, strict=True) if out)
        largest = float(distances.max())
        return PrecisionReport(
            "window", limit_m, largest, float32_error_mm(largest), corners_outside=names
        )
    local = world_to_local(points, origin)
    distances = np.abs(local[..., :2]).reshape(-1, 2)
    largest = float(distances.max()) if distances.size else 0.0
    count = int((distances > limit_m).any(axis=1).sum())
    return PrecisionReport(
        "points", limit_m, largest, float32_error_mm(largest), points_outside=count
    )
