# SPDX-License-Identifier: GPL-3.0-or-later
"""Dibujo en la vista 3D con ``gpu``: superposiciones y elementos temporales.

- ``contours``: las curvas maestras con trazo grueso sobre el alambre de Blender (spec 006,
  T55), con su manejador de dibujo y el de actualización, que :func:`register` pone y
  :func:`unregister` quita.
- ``dh_overlay``: las etiquetas, las leyendas y las marcas de las bocas de los sondeos (spec
  005, T30), con su manejador de dibujo.
- ``constraints``: «Ver restricciones y límites» (spec 012, T26): la superposición del control 30,
  que solo tiene sus manejadores de dibujo mientras está activa. No se importa al registrar
  (nada pesado en ``register()``): lo importa la orden que la activa; :func:`unregister` la quita
  si está importada y activa (principio 8).
- ``design``: la vista previa de semillas, dominios y restricciones (spec 013, T25): igual que la
  anterior, solo existe mientras está activa, la importa su orden (o su propiedad) y
  :func:`unregister` la quita.
- ``entity``: la vista previa de una entidad de diseño (spec 015, T29): como la anterior, solo existe
  mientras está activa, la importa su orden y :func:`unregister` la quita.
"""

from __future__ import annotations

import sys

from ..registry import register_classes, unregister_classes
from . import contours, dh_overlay

# Clases de los módulos de este subpaquete, en orden de registro (plan 001 §5.3,
# contrato 2); vacía hasta que una spec añada la primera.
classes: tuple[type, ...] = ()
_OVERLAYS = (contours, dh_overlay)
CONSTRAINTS_MODULE = f"{__name__}.constraints"
"""El módulo de la superposición de las restricciones (se importa al activarla)."""
DESIGN_MODULE = f"{__name__}.design"
"""El módulo de la vista previa de semillas, dominios y restricciones (se importa al activarla)."""
ENTITY_MODULE = f"{__name__}.entity"
"""El módulo de la vista previa de una entidad de diseño (se importa al activarla)."""


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
    """Quita las superposiciones (también la de las restricciones, si está activa) y desregistra
    ``classes``, en orden inverso."""
    try:
        for name in (ENTITY_MODULE, DESIGN_MODULE, CONSTRAINTS_MODULE):
            lazy = sys.modules.get(name)
            if lazy is not None:
                lazy.unregister()
        for overlay in reversed(_OVERLAYS):
            overlay.unregister()
    finally:
        unregister_classes(classes)
