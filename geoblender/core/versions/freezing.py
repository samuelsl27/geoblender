# SPDX-License-Identifier: GPL-3.0-or-later
"""Las congelaciones en curso de este proceso (spec 009; RF-009-07, RF-008-22, RNF-008-12; plan
009 A6; T39).

:func:`core.versions.freeze.freeze_steps` anota aquí (:func:`register`) la carpeta temporal de
la congelación que copia (``snapshots/V10.r2.congelando-<8 hex>``), con la raíz de su proyecto y
su sesión, y la quita (:func:`unregister`) al terminar, cancelarse o fallar. El barrido de
restos de la comprobación de apertura (``core.datasets.orphans``) no aparta las de su sesión
(:func:`freezing_paths`), aunque corra a mitad de la copia.

Y el registro de las comprobaciones de los módulos al congelar (spec 012, RF-012-25, D-29;
:func:`register_freeze_check`, que ``core.versions.freeze`` reexporta con el resto de su API):
``bl`` lo llena al habilitar la extensión y habilitar no puede cargar ``core.versions.freeze``
(RNF-001-03, spec 012 T38: con ``provenance.lineage`` son unos 13 ms en frío); la comprobación
de cada módulo la importa ella misma al usarla.

Módulo ligero, solo de la biblioteca estándar: lo importa ``core.datasets.orphans`` al
importarse, y su paso de «restos» (un tic de ≤ 20 ms, RNF-008-12) no carga
``core.versions.freeze``, que arrastra ``provenance.lineage`` y ``recompute`` (42–54 ms en
frío).
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .freeze import FreezeCheck

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


# --- Las comprobaciones de los módulos al congelar (spec 012, RF-012-25, D-29) ---------------------

_CHECKS: list[tuple[str, FreezeCheck]] = []


def register_freeze_check(module: str, check: FreezeCheck) -> None:
    """Registra la comprobación ``check`` del módulo ``module`` (el código del módulo que la
    declara, ``"res"``): ``freeze_plan`` la llama con cada plan y lo que da va a lo que hay que
    aceptar (``FreezePlan.accept``). Registrar otra vez la misma función del mismo módulo no hace
    nada; un módulo puede tener varias y se llaman en el orden en que se registraron.
    ``TypeError``/``ValueError`` con un argumento mal dado."""
    _check_module(module)
    if not callable(check):
        raise TypeError(f"una comprobación de congelar es una función, no {check!r}")
    if (module, check) not in _CHECKS:
        _CHECKS.append((module, check))


def unregister_freeze_checks(module: str) -> int:
    """Quita las comprobaciones del módulo ``module``; cuántas quitó (0 si no había ninguna)."""
    _check_module(module)
    kept = [entry for entry in _CHECKS if entry[0] != module]
    removed = len(_CHECKS) - len(kept)
    _CHECKS[:] = kept
    return removed


def freeze_checks() -> tuple[tuple[str, FreezeCheck], ...]:
    """Las comprobaciones registradas, (módulo, función), en el orden en que se registraron."""
    return tuple(_CHECKS)


def _check_module(module: object) -> None:
    if not isinstance(module, str):
        raise TypeError(f"el módulo de una comprobación es su código (un texto), no {module!r}")
    if not module.strip():
        raise ValueError("el módulo de una comprobación de congelar no puede estar vacío")
