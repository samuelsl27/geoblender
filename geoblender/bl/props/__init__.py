# SPDX-License-Identifier: GPL-3.0-or-later
"""Propiedades de Blender: grupos de propiedades y la única ``GeoblenderPreferences``
(PLT-02), con el GeoOrigin en ``IntProperty`` (ARQ-13). Se registra el primero.

- ``core``: ``Scene.geoblender`` (georreferencia del proyecto en la escena) y el grupo
  ``core`` de las preferencias (spec 002);
- ``ui``: ``WorkSpace.geoblender_mode`` (la marca del modo Geoblender) y el grupo ``ui``
  de las preferencias (spec 003);
- ``preferences``: la única ``GeoblenderPreferences``, con un grupo por módulo.
"""

from __future__ import annotations

from ..registry import register_classes, unregister_classes
from . import core, preferences, ui

# Clases de los módulos de este subpaquete, en orden de registro (plan 001 §5.3,
# contrato 2): los grupos antes de quien los usa.
classes: tuple[type, ...] = (*core.classes, *ui.classes, *preferences.classes)


def register() -> None:
    """Registra ``classes`` en orden y pone ``Scene.geoblender`` y
    ``WorkSpace.geoblender_mode``; si ya lo están, no hace nada. Si algo falla, deshace lo
    hecho antes de propagar el error."""
    register_classes(classes)
    try:
        core.register()
        ui.register()
    except BaseException:
        ui.unregister()
        core.unregister()
        unregister_classes(classes)
        raise


def unregister() -> None:
    """Quita ``WorkSpace.geoblender_mode`` y ``Scene.geoblender`` y desregistra ``classes``
    en orden inverso; omite lo que no está registrado."""
    ui.unregister()
    core.unregister()
    unregister_classes(classes)
