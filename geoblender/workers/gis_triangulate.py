# SPDX-License-Identifier: GPL-3.0-or-later
"""Tipo de trabajo ``gis_triangulate`` en un proceso aparte (spec 006, T26; RF-006-28; plan 006
§5.3.4): los triángulos de un TIN con ``PureTriangulator`` (por
encima del límite de la CDT de Blender en el hilo).

Envoltorio de ``gis.jobs.run_triangulate``, la misma función que ejecuta el hilo dentro de
Blender (``WorkerInfo.run``), con los lectores de ``gis`` registrados antes
(``workers/_gis.py``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import _gis


def main(ctx: Any) -> Mapping[str, Any]:
    """El trabajo en proceso aparte (véase el módulo)."""
    return _gis.run(ctx, "run_triangulate")


__all__ = ["main"]
