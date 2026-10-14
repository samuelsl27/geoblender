# SPDX-License-Identifier: GPL-3.0-or-later
"""Tipo de trabajo ``gis_import_points`` en un proceso aparte (spec 006, T26; RF-006-28; plan 006
§5.3.4): un texto de puntos (CSV, TXT o XYZ disperso) a puntos y
líneas de rotura, con el hash de la fuente.

Envoltorio de ``gis.jobs.run_import_points``, la misma función que ejecuta el hilo dentro de
Blender (``WorkerInfo.run``), con los lectores de ``gis`` registrados antes
(``workers/_gis.py``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import _gis


def main(ctx: Any) -> Mapping[str, Any]:
    """El trabajo en proceso aparte (véase el módulo)."""
    return _gis.run(ctx, "run_import_points")


__all__ = ["main"]
