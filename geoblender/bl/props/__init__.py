# SPDX-License-Identifier: GPL-3.0-or-later
"""Propiedades de Blender: grupos de propiedades y la única ``GeoblenderPreferences``
(PLT-02), con el GeoOrigin en ``IntProperty`` (ARQ-13). Se registra el primero.

- ``core``: ``Scene.geoblender`` (georreferencia del proyecto en la escena) y el grupo
  ``core`` de las preferencias (spec 002);
- ``ui``: ``WorkSpace.geoblender_mode`` (la marca del modo Geoblender) y el grupo ``ui``
  de las preferencias (spec 003);
- ``jobs``: el grupo ``jobs`` de las preferencias (spec 004): trabajos a la vez,
  retención, origen del motor de cálculo, almacén de ruedas e intérprete externo;
- ``preferences``: la única ``GeoblenderPreferences``, con un grupo por módulo.

Antes de registrar las clases, sus propiedades (nombre, descripción y elementos de los
enumerados) se ponen en el idioma de Geoblender de la última sesión
(``ui.remembered_language``; ``bl.registry.PropertyTranslator``), porque las preferencias
aún no se pueden leer; al desregistrar vuelven a su texto original. Si se cambia de idioma,
estas cambian al reiniciar Blender (spec 003, §8; II §2.2).
"""

from __future__ import annotations

from ...core import i18n
from ..registry import PropertyTranslator, register_classes, unregister_classes
from . import core, jobs, preferences, ui

# Clases de los módulos de este subpaquete, en orden de registro (plan 001 §5.3,
# contrato 2): los grupos antes de quien los usa.
classes: tuple[type, ...] = (
    *core.classes, *ui.classes, *jobs.classes, *preferences.classes
)

_PROPERTIES = PropertyTranslator()


def _localize() -> None:
    """Pone las propiedades de ``classes`` en el idioma de la última sesión."""
    i18n.set_language(ui.remembered_language())
    for cls in classes:
        if not getattr(cls, "is_registered", False):
            _PROPERTIES.localize(cls)


def register() -> None:
    """Registra ``classes`` en orden y pone ``Scene.geoblender`` y
    ``WorkSpace.geoblender_mode``; si ya lo están, no hace nada. Si algo falla, deshace lo
    hecho antes de propagar el error."""
    _localize()
    try:
        register_classes(classes)
    except BaseException:
        _PROPERTIES.restore()
        raise
    try:
        core.register()
        ui.register()
    except BaseException:
        ui.unregister()
        core.unregister()
        unregister_classes(classes)
        _PROPERTIES.restore()
        raise


def unregister() -> None:
    """Quita ``WorkSpace.geoblender_mode`` y ``Scene.geoblender`` y desregistra ``classes``
    en orden inverso; omite lo que no está registrado."""
    ui.unregister()
    core.unregister()
    unregister_classes(classes)
    _PROPERTIES.restore()
