# SPDX-License-Identifier: GPL-3.0-or-later
"""Registro de clases de Blender, tolerante e idempotente (plan 001 §5.3).

Cada subpaquete de ``bl`` reúne sus clases en una tupla ``classes`` y las registra con
:func:`register_classes`; :func:`unregister_classes` las desregistra en orden inverso.
Registrar una clase ya registrada o desregistrar una que no lo está no hace nada, y si
una clase falla al registrarse se deshace lo registrado antes de propagar el error: así
desactivar Geoblender deja Blender como estaba (principio 8).
"""

from __future__ import annotations

from collections.abc import Sequence

import bpy


def _is_registered(cls: type) -> bool:
    return bool(getattr(cls, "is_registered", False))


def register_classes(classes: Sequence[type]) -> None:
    """Registra ``classes`` en orden (los subpaneles, después de sus padres)."""
    done: list[type] = []
    try:
        for cls in classes:
            if _is_registered(cls):
                continue
            bpy.utils.register_class(cls)
            done.append(cls)
    except BaseException:
        unregister_classes(done)
        raise


def unregister_classes(classes: Sequence[type]) -> None:
    """Desregistra ``classes`` en orden inverso y omite las que no están registradas."""
    for cls in reversed(classes):
        if _is_registered(cls):
            bpy.utils.unregister_class(cls)
