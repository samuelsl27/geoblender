# SPDX-License-Identifier: GPL-3.0-or-later
"""Dibujo en la vista 3D con ``gpu``: superposiciones y elementos temporales.

- ``contours``: las curvas maestras con trazo grueso sobre el alambre de Blender (spec 006,
  T55), con su manejador de dibujo y el de actualización, que :func:`register` pone y
  :func:`unregister` quita.
"""

from __future__ import annotations

from ..registry import register_classes, unregister_classes
from . import contours

# Clases de los módulos de este subpaquete, en orden de registro (plan 001 §5.3,
# contrato 2); vacía hasta que una spec añada la primera.
classes: tuple[type, ...] = ()


def register() -> None:
    """Registra ``classes`` y la superposición de las curvas maestras; si ya lo están, no hace
    nada. Si algo falla, deshace lo hecho antes de propagar el error."""
    register_classes(classes)
    try:
        contours.register()
    except BaseException:
        contours.unregister()
        unregister_classes(classes)
        raise


def unregister() -> None:
    """Quita la superposición de las curvas maestras y desregistra ``classes``, en orden
    inverso."""
    try:
        contours.unregister()
    finally:
        unregister_classes(classes)
