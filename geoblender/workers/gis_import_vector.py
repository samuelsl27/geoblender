# SPDX-License-Identifier: GPL-3.0-or-later
"""Tipo de trabajo ``gis_import_vector`` en un proceso aparte (spec 006, T29; RF-006-28; plan 006
§5.3.4): una capa de un GeoPackage (con su ``-wal``) con el papel que declara la persona:
puntos, líneas de rotura, curvas de nivel o contorno, con el hash de la fuente.

Envoltorio de ``gis.jobs.run_import_vector``, la misma función que ejecuta el hilo dentro de
Blender (``WorkerInfo.run``), con los lectores de ``gis`` registrados antes
(``workers/_gis.py``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import _gis


def main(ctx: Any) -> Mapping[str, Any]:
    """El trabajo en proceso aparte (véase el módulo)."""
    return _gis.run(ctx, "run_import_vector")


__all__ = ["main"]
