# SPDX-License-Identifier: GPL-3.0-or-later
"""Tipo de trabajo ``gis_tin_contours`` en un proceso aparte (spec 006, T29; RF-006-28; plan 006
§5.3.4): el TIN desde curvas de nivel con la corrección de triángulos
planos y ``PureTriangulator``.

Envoltorio de ``gis.jobs.run_tin_contours``, la misma función que ejecuta el hilo dentro de
Blender (``WorkerInfo.run``), con los lectores de ``gis`` registrados antes
(``workers/_gis.py``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import _gis


def main(ctx: Any) -> Mapping[str, Any]:
    """El trabajo en proceso aparte (véase el módulo)."""
    return _gis.run(ctx, "run_tin_contours")


__all__ = ["main"]
