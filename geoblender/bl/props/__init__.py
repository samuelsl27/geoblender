# SPDX-License-Identifier: GPL-3.0-or-later
"""Propiedades de Blender: grupos de propiedades y la única ``GeoblenderPreferences``
(PLT-02), con el GeoOrigin en ``IntProperty`` (ARQ-13). Se registra el primero.

- ``core``: ``Scene.geoblender`` (georreferencia del proyecto en la escena) y el grupo
  ``core`` de las preferencias (spec 002);
- ``preferences``: la única ``GeoblenderPreferences``, con un grupo por módulo.
"""

from __future__ import annotations

from ..registry import register_classes, unregister_classes
from . import core, preferences

# Clases de los módulos de este subpaquete, en orden de registro (plan 001 §5.3,
# contrato 2): los grupos antes de quien los usa.
classes: tuple[type, ...] = (*core.classes, *preferences.classes)


def register() -> None:
    """Registra ``classes`` en orden y pone ``Scene.geoblender``; si ya lo están, no hace
    nada. Si algo falla, deshace lo hecho antes de propagar el error."""
    register_classes(classes)
    try:
        core.register()
    except BaseException:
        unregister_classes(classes)
        raise


def unregister() -> None:
    """Quita ``Scene.geoblender`` y desregistra ``classes`` en orden inverso; omite lo que
    no está registrado."""
    core.unregister()
    unregister_classes(classes)
