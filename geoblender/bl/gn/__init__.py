# SPDX-License-Identifier: GPL-3.0-or-later
"""Grupos de nodos de Geometry Nodes construidos en código; las entradas del
modificador, siempre a través de ``bl/compat.py``.
"""

from __future__ import annotations

from ..registry import register_classes, unregister_classes

# Clases de los módulos de este subpaquete, en orden de registro (plan 001 §5.3,
# contrato 2); vacía hasta que una spec añada la primera.
classes: tuple[type, ...] = ()


def register() -> None:
    """Registra ``classes`` en orden; si ya lo están, no hace nada."""
    register_classes(classes)


def unregister() -> None:
    """Desregistra ``classes`` en orden inverso; omite las que no están registradas."""
    unregister_classes(classes)
