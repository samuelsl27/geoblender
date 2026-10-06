# SPDX-License-Identifier: GPL-3.0-or-later
"""Operadores ``GEOBLENDER_OT_<módulo>_<acción>``, uno por fichero de módulo
(``bl/ops/<código>.py``). No calculan: validan, llaman al dominio y presentan el
resultado.
"""

from __future__ import annotations

from ..registry import register_classes, unregister_classes
from . import core

# Clases de los módulos de este subpaquete, en orden de registro (plan 001 §5.3,
# contrato 2): core (spec 002).
classes: tuple[type, ...] = (*core.classes,)


def register() -> None:
    """Registra ``classes`` en orden; si ya lo están, no hace nada."""
    register_classes(classes)


def unregister() -> None:
    """Desregistra ``classes`` en orden inverso; omite las que no están registradas."""
    unregister_classes(classes)
