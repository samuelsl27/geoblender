# SPDX-License-Identifier: GPL-3.0-or-later
"""Objetos de la escena: creación y actualización de mallas, curvas y colecciones en
coordenadas locales respecto al GeoOrigin (ADR-0005).

- ``project_session``: el proyecto abierto en esta sesión, la marca de actividad de su
  cerrojo (temporizador persistente) y su cierre al desactivar o salir (spec 002);
- ``georef``: la georreferencia del proyecto en las escenas y sus manejadores
  (``load_post``, ``undo_post``, ``redo_post``, ``save_pre``, ``save_post``).
"""

from __future__ import annotations

from ..registry import register_classes, unregister_classes
from . import georef, project_session

# Clases de los módulos de este subpaquete, en orden de registro (plan 001 §5.3,
# contrato 2); vacía hasta que una spec añada la primera.
classes: tuple[type, ...] = ()


def register() -> None:
    """Registra ``classes``, la sesión y los manejadores; si ya lo están, no hace nada.
    Si algo falla, deshace lo hecho antes de propagar el error."""
    register_classes(classes)
    try:
        project_session.register()
        georef.register()
    except BaseException:
        georef.unregister()
        project_session.unregister()
        unregister_classes(classes)
        raise


def unregister() -> None:
    """Quita los manejadores, cierra el proyecto de la sesión (libera su cerrojo) y
    desregistra ``classes``, en orden inverso."""
    try:
        georef.unregister()
        project_session.unregister()
    finally:
        unregister_classes(classes)
