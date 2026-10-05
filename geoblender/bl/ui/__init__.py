# SPDX-License-Identifier: GPL-3.0-or-later
"""Interfaz: conmutador, barra superior, menús, accesos rápidos, iconos, atajos e
idioma. Se registra el último.
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
