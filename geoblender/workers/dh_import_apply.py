# SPDX-License-Identifier: GPL-3.0-or-later
"""Tipo de trabajo ``dh_import_apply`` en un proceso aparte (spec 005, T23; RNF-005-06; plan 005
§5.3.3 y §5.6.7): lo leído de una entrada con las decisiones de la persona, en las filas de lo
importado con su hash.

Envoltorio de ``drillholes.jobs.run_import_apply``, la misma función que ejecuta el hilo dentro de
Blender (``WorkerInfo.run``), con lo común de ``workers/_dh.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import _dh


def main(ctx: Any) -> Mapping[str, Any]:
    """El trabajo en proceso aparte (véase el módulo)."""
    return _dh.run(ctx, _dh.DOMAIN, "run_import_apply")


__all__ = ["main"]
