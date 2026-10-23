# SPDX-License-Identifier: GPL-3.0-or-later
"""Las congelaciones en curso de este proceso (spec 009; RF-009-07, RF-008-22, RNF-008-12; plan
009 A6; T39).

:func:`core.versions.freeze.freeze_steps` anota aquí (:func:`register`) la carpeta temporal de
la congelación que copia (``snapshots/V10.r2.congelando-<8 hex>``), con la raíz de su proyecto y
su sesión, y la quita (:func:`unregister`) al terminar, cancelarse o fallar. El barrido de
restos de la comprobación de apertura (``core.datasets.orphans``) no aparta las de su sesión
(:func:`freezing_paths`), aunque corra a mitad de la copia.

Módulo ligero, solo de la biblioteca estándar: lo importa ``core.datasets.orphans`` al
importarse, y su paso de «restos» (un tic de ≤ 20 ms, RNF-008-12) no carga
``core.versions.freeze``, que arrastra ``provenance.lineage`` y ``recompute`` (42–54 ms en
frío).
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_FREEZING: dict[Path, tuple[str, str]] = {}
"""Las carpetas temporales de las congelaciones en curso de este proceso → la raíz de su
proyecto (normalizada) y su sesión."""


def _owner(project: Any) -> tuple[str, str]:
    return (os.path.normcase(os.path.normpath(os.fspath(project.root))),
            str(project.session.session_uid))


def register(project: Any, path: Path) -> None:
    """Anota ``path`` como la carpeta temporal de una congelación en curso de la sesión de
    ``project`` (``project.root`` y ``project.session.session_uid``) en ese proyecto."""
    owner = _owner(project)
    with _LOCK:
        _FREEZING[path] = owner


def unregister(path: Path) -> None:
    """Quita ``path`` de las congelaciones en curso (si no estaba, nada)."""
    with _LOCK:
        _FREEZING.pop(path, None)


def freezing_paths(project: Any) -> frozenset[Path]:
    """Las carpetas temporales de las congelaciones en curso de esta sesión en ``project`` (su
    raíz y su sesión): el barrido de restos no las aparta (``core.datasets.orphans``; plan A6,
    RF-008-22)."""
    owner = _owner(project)
    with _LOCK:
        return frozenset(path for path, who in _FREEZING.items() if who == owner)
