# SPDX-License-Identifier: GPL-3.0-or-later
"""Tipo de trabajo ``dh_import_recmin`` en un proceso aparte (spec 005, T23; RNF-005-06; plan
005 §5.3.3 y §5.6.7): una base de RecMin, leída en lo declarado, con el hash de contenido de la
fuente; su ``powershell.exe`` hijo está en el *Job Object* del trabajo, que lo termina si se
cancela o muere.

Envoltorio de ``interop.dh_jobs.run_import_recmin`` (siempre en proceso aparte: su tipo, en
``drillholes.jobs``, no tiene ``run``), con lo común de ``workers/_dh.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import _dh


def main(ctx: Any) -> Mapping[str, Any]:
    """El trabajo en proceso aparte (véase el módulo)."""
    return _dh.run(ctx, _dh.IMPORTS, "run_import_recmin")


__all__ = ["main"]
