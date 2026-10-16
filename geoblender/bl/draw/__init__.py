# SPDX-License-Identifier: GPL-3.0-or-later
"""Dibujo en la vista 3D con ``gpu``: superposiciones y elementos temporales.

- ``contours``: las curvas maestras con trazo grueso sobre el alambre de Blender (spec 006,
  T55), con su manejador de dibujo y el de actualización, que :func:`register` pone y
  :func:`unregister` quita.
- ``dh_overlay``: las etiquetas, las leyendas y las marcas de las bocas de los sondeos (spec
  005, T30), con su manejador de dibujo.
"""

from __future__ import annotations

from ..registry import register_classes, unregister_classes
from . import contours, dh_overlay

# Clases de los módulos de este subpaquete, en orden de registro (plan 001 §5.3,
# contrato 2); vacía hasta que una spec añada la primera.
classes: tuple[type, ...] = ()
_OVERLAYS = (contours, dh_overlay)


def register() -> None:
    """Registra ``classes`` y las superposiciones (las curvas maestras y los sondeos); si ya lo
    están, no hace nada. Si algo falla, deshace lo hecho antes de propagar el error."""
    register_classes(classes)
    try:
        for overlay in _OVERLAYS:
            overlay.register()
    except BaseException:
        for overlay in reversed(_OVERLAYS):
            overlay.unregister()
        unregister_classes(classes)
        raise


def unregister() -> None:
    """Quita las superposiciones y desregistra ``classes``, en orden inverso."""
    try:
        for overlay in reversed(_OVERLAYS):
            overlay.unregister()
    finally:
        unregister_classes(classes)
