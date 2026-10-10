# SPDX-License-Identifier: GPL-3.0-or-later
"""Tipo de trabajo ``gis_contours`` en un proceso aparte (spec 006, T26; RF-006-28; plan 006
§5.3.4): las curvas de nivel de una rejilla o de un TIN del proyecto.

Envoltorio de ``gis.jobs.run_contours``, la misma función que ejecuta el hilo dentro de
Blender (``WorkerInfo.run``), con los lectores de ``gis`` registrados antes
(``workers/_gis.py``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import _gis


def main(ctx: Any) -> Mapping[str, Any]:
    """El trabajo en proceso aparte (véase el módulo)."""
    return _gis.run(ctx, "run_contours")


__all__ = ["main"]
