# SPDX-License-Identifier: GPL-3.0-or-later
"""Tipo de trabajo ``dh_build_base`` en un proceso aparte (spec 005, T23; RNF-005-06; plan 005
§5.3.3 y §5.6.7): la base de los sondeos desde lo importado vigente, con el hash de cada tabla.

Envoltorio de ``drillholes.jobs.run_build_base``, la misma función que ejecuta el hilo dentro de
Blender (``WorkerInfo.run``), con lo común de ``workers/_dh.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import _dh


def main(ctx: Any) -> Mapping[str, Any]:
    """El trabajo en proceso aparte (véase el módulo)."""
    return _dh.run(ctx, _dh.DOMAIN, "run_build_base")


__all__ = ["main"]
