# SPDX-License-Identifier: GPL-3.0-or-later
"""Tipo de trabajo ``gis_read_raster`` en un proceso aparte (spec 006, T26; RF-006-28; plan 006
§5.3.4): un MDT ráster (GeoTIFF, ASC o XYZ en malla) a la rejilla de
origen del proyecto (perfil ``project``), con el hash de la fuente.

Envoltorio de ``gis.jobs.run_read_raster``, la misma función que ejecuta el hilo dentro de
Blender (``WorkerInfo.run``), con los lectores de ``gis`` registrados antes
(``workers/_gis.py``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import _gis


def main(ctx: Any) -> Mapping[str, Any]:
    """El trabajo en proceso aparte (véase el módulo)."""
    return _gis.run(ctx, "run_read_raster")


__all__ = ["main"]
