# SPDX-License-Identifier: GPL-3.0-or-later
"""Falsos de las pruebas de los sondeos (spec 005).

:class:`FakeCrsService` cumple el puerto ``gis.ports.CrsService`` (dueño, la 006) tal como
está: los mismos métodos con los mismos parámetros (lo comprueba
``tests/unit/drillholes/test_conventions.py``). Da la convergencia de cuadrícula
``convergence`` en todas las bocas (por defecto +1,50°, la γ de ``tests/data/dh/
csv_convenios``) o, si es una función, la de cada punto ``convergence(xy)``; apunta cada
llamada en ``calls`` (nombre, CRS y una copia de las coordenadas). No identifica WKT ni da
transformaciones: la reproyección se prueba con el servicio real de la 006 (D-23 del plan).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

CONVERGENCE_DEG = 1.5
"""La γ de ``tests/data/dh/csv_convenios`` (``sintetico.CONVERGENCE_CDEG``): +1,50°."""


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
