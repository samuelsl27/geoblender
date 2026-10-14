# SPDX-License-Identifier: GPL-3.0-or-later
"""Tipo de trabajo ``gis_convert_surface`` en un proceso aparte (spec 006, T29; RF-006-28; plan 006
§5.3.4): una rejilla del proyecto en TIN o un TIN en la rejilla del
proyecto.

Envoltorio de ``gis.jobs.run_convert_surface``, la misma función que ejecuta el hilo dentro de
Blender (``WorkerInfo.run``), con los lectores de ``gis`` registrados antes
(``workers/_gis.py``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import _gis


def main(ctx: Any) -> Mapping[str, Any]:
    """El trabajo en proceso aparte (véase el módulo)."""
    return _gis.run(ctx, "run_convert_surface")


__all__ = ["main"]
