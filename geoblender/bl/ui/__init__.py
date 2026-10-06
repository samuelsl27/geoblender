# SPDX-License-Identifier: GPL-3.0-or-later
"""Interfaz: conmutador, barra superior, menús, accesos rápidos, iconos, atajos e
idioma. Se registra el último.
"""

from __future__ import annotations

from ..registry import register_classes, unregister_classes
from . import core_menus, core_panel

# Clases de los módulos de este subpaquete, en orden de registro (plan 001 §5.3,
# contrato 2): los menús y la pestaña «Proyecto» de core (spec 002).
classes: tuple[type, ...] = (*core_menus.classes, *core_panel.classes)


def register() -> None:
    """Registra ``classes`` en orden (la pestaña, en el idioma de la interfaz); si ya lo
    están, no hace nada."""
    core_panel.localize()
    register_classes(classes)


def unregister() -> None:
    """Desregistra ``classes`` en orden inverso; omite las que no están registradas."""
    unregister_classes(classes)
