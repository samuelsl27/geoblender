# SPDX-License-Identifier: GPL-3.0-or-later
"""Propiedades de Blender: grupos de propiedades y la única ``GeoblenderPreferences``
(PLT-02), con el GeoOrigin en ``IntProperty`` (ARQ-13). Se registra el primero.

- ``core``: ``Scene.geoblender`` (georreferencia del proyecto en la escena) y el grupo
  ``core`` de las preferencias (spec 002); ``Object.geoblender`` (lo que muestra un objeto de
  la vista) y las filas del diálogo de «Cargar en la vista…» (spec 006, T27);
- ``ui``: ``WorkSpace.geoblender_mode`` (la marca del modo Geoblender) y el grupo ``ui``
  de las preferencias (spec 003);
- ``jobs``: el grupo ``jobs`` de las preferencias (spec 004): trabajos a la vez,
  retención, origen del motor de cálculo, almacén de ruedas e intérprete externo;
- ``provenance``: ``WindowManager.geoblender_provenance``, las filas de los paneles de la
  procedencia (spec 008; una vista que no se guarda en el ``.blend``);
- ``dh``: ``Scene.geoblender_dh_display`` (la representación de los sondeos) y
  ``WindowManager.geoblender_dh_import`` y ``.geoblender_dh_validation`` (la importación
  pendiente y la validación, una vista; spec 005, T24);
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
from . import core, dh, gis, jobs, preferences, provenance, ui

# Clases de los módulos de este subpaquete, en orden de registro (plan 001 §5.3,
# contrato 2): los grupos antes de quien los usa.
classes: tuple[type, ...] = (
    *core.classes, *gis.classes, *provenance.classes, *dh.classes, *ui.classes,
    *jobs.classes, *preferences.classes
)

_PROPERTIES = PropertyTranslator()


def _localize() -> None:
    """Pone las propiedades de ``classes`` en el idioma de la última sesión."""
    i18n.set_language(ui.remembered_language())
    for cls in classes:
        if not getattr(cls, "is_registered", False):
            _PROPERTIES.localize(cls)


def register() -> None:
    """Registra ``classes`` en orden y pone ``Scene.geoblender``, ``Object.geoblender``,
    ``WindowManager.geoblender_provenance``, las de los sondeos (``dh``) y
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
        provenance.register()
        dh.register()
        ui.register()
    except BaseException:
        ui.unregister()
        dh.unregister()
        provenance.unregister()
        core.unregister()
        unregister_classes(classes)
        _PROPERTIES.restore()
        raise


def unregister() -> None:
    """Quita ``WorkSpace.geoblender_mode``, las de los sondeos,
    ``WindowManager.geoblender_provenance``, ``Object.geoblender`` y ``Scene.geoblender`` y
    desregistra ``classes`` en orden inverso; omite lo que no está registrado."""
    ui.unregister()
    dh.unregister()
    provenance.unregister()
    core.unregister()
    unregister_classes(classes)
    _PROPERTIES.restore()
