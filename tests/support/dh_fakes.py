# SPDX-License-Identifier: GPL-3.0-or-later
"""Falsos de las pruebas de los sondeos (spec 005).

:class:`FakeCrsService` cumple el puerto ``gis.ports.CrsService`` (dueño, la 006) tal como
está: los mismos métodos con los mismos parámetros (lo comprueba
``tests/unit/drillholes/test_conventions.py``). Da la convergencia de cuadrícula
``convergence`` en todas las bocas (por defecto +1,50°, la γ de ``tests/data/dh/
csv_convenios``) o, si es una función, la de cada punto ``convergence(xy)``; apunta cada
llamada en ``calls`` (nombre, CRS y una copia de las coordenadas). No identifica WKT ni da
transformaciones: la reproyección se prueba con el servicio real de la 006 (D-23 del plan).

:class:`FakeSurface` cumple el puerto ``drillholes.ports.SurfaceSampler`` (T10; RF-005-18):
la cota de una superficie en las coordenadas absolutas que le pidan, por defecto la de
``tests/data/gis`` (:func:`gis_surface`, la de ``esperado.json`` de ``tests/data/dh``), con el
CRS y la referencia vertical que se le den; apunta cada llamada en ``calls``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

CONVERGENCE_DEG = 1.5
"""La γ de ``tests/data/dh/csv_convenios`` (``sintetico.CONVERGENCE_CDEG``): +1,50°."""

SURFACE_E0, SURFACE_N0 = 700_000.0, 4_400_000.0
"""El origen de x e y de la superficie de ``tests/data/gis`` (m, EPSG:25830)."""


class FakeCrsService:
    """Un ``gis.ports.CrsService`` de prueba (véase el módulo)."""

    def __init__(
        self,
        convergence: float | Callable[[np.ndarray], np.ndarray] = CONVERGENCE_DEG,
        scale: float = 1.0,
    ) -> None:
        self.convergence = convergence
        self.scale = scale
        self.calls: list[tuple[str, Any, np.ndarray]] = []

    def identify_wkt(self, wkt: str) -> Any:
        return None

    def transformer(self, src: Any, src_v: Any, dst: Any, dst_v: Any) -> Any:
        raise AssertionError("el CrsService falso de los sondeos no transforma (D-23)")

    def scale_factor(self, crs: Any, xy: np.ndarray) -> np.ndarray:
        values = np.array(xy, dtype=np.float64, copy=True)
        self.calls.append(("scale_factor", crs, values))
        return np.full(len(values), self.scale, dtype=np.float64)

    def grid_convergence(self, crs: Any, xy: np.ndarray) -> np.ndarray:
        values = np.array(xy, dtype=np.float64, copy=True)
        self.calls.append(("grid_convergence", crs, values))
        if callable(self.convergence):
            return np.asarray(self.convergence(values.copy()), dtype=np.float64)
        return np.full(len(values), self.convergence, dtype=np.float64)


def gis_surface(xy: np.ndarray) -> np.ndarray:
    """La superficie de ``tests/data/gis/README.md`` en los puntos ``xy`` absolutos (n, 2):
    z = 800 + 0,5·x − 0,25·y + 3·sin(x/7), con x = E − 700 000 e y = N − 4 400 000 (m)."""
    x = xy[:, 0] - SURFACE_E0
    y = xy[:, 1] - SURFACE_N0
    return 800.0 + 0.5 * x - 0.25 * y + 3.0 * np.sin(x / 7.0)


class FakeSurface:
    """Un ``drillholes.ports.SurfaceSampler`` de prueba (véase el módulo): ``z(xy)`` da la
    cota (NaN = fuera del MDT) de cada punto de ``xy`` (n, 2)."""

    def __init__(self, crs: Any, vertical: Any,
                 z: Callable[[np.ndarray], np.ndarray] = gis_surface) -> None:
        self.crs = crs
        self.vertical = vertical
        self.z = z
        self.calls: list[np.ndarray] = []

    def sample(self, xy_abs: np.ndarray) -> np.ndarray:
        values = np.array(xy_abs, dtype=np.float64, copy=True)
        self.calls.append(values)
        return np.asarray(self.z(values.copy()), dtype=np.float64)
