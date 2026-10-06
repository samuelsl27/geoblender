# SPDX-License-Identifier: GPL-3.0-or-later
"""Atajos de teclado desde el catálogo (spec 003; RF-003-18, RF-003-19; AT §1 y §2).

:func:`register` añade al *keyconfig* de complementos las combinaciones de
``shortcuts.toml`` (las 49 de AT §2): ``Ctrl+F10`` en el mapa «Window» (funciona en los dos
modos y desde cualquier editor) y las demás en el mapa «3D View». También las de comandos
aún no disponibles: su provisional informa «Disponible en …» (AT §1, regla 6). Cada
elemento lleva las propiedades fijas de su clave (``geoblender.ui_recall_view?slot=1``).

No se activan ni desactivan al conmutar: el ``poll`` de cada operador con atajo en la
Vista 3D pasa por la puerta de modo (``bl.ui.gate``), y en modo Blender la tecla pasa a
Blender (AT §1, regla 1; se comprueba en la GUI, M4).

:func:`unregister` quita los elementos que añadió y los mapas que creó (si quedan
vacíos): desactivar Geoblender deja el *keyconfig* de complementos como estaba. Todo atajo
es editable en Preferencias ▸ Mapa de teclado ▸ Complementos.
"""

from __future__ import annotations

from typing import Any

import bpy

from ...core.catalog.schema import split_key
from .commands import catalog

# Mapa del catálogo → (nombre, tipo de espacio, tipo de región) del keyconfig.
KEYMAPS: dict[str, tuple[str, str, str]] = {
    "Window": ("Window", "EMPTY", "WINDOW"),
    "3D View": ("3D View", "VIEW_3D", "WINDOW"),
}


class _State:
    def __init__(self) -> None:
        self.items: list[tuple[Any, Any]] = []  # (mapa, elemento) añadidos, en orden
        self.created: list[Any] = []  # mapas que no existían


_STATE = _State()


def _keymap(keyconfig: Any, name: str) -> Any:
    title, space, region = KEYMAPS[name]
    found = keyconfig.keymaps.find(title, space_type=space, region_type=region)
    if found is not None:
        return found
    keymap = keyconfig.keymaps.new(name=title, space_type=space, region_type=region)
    _STATE.created.append(keymap)
    return keymap


def registered_items() -> tuple[tuple[Any, Any], ...]:
    """Los (mapa, elemento) que añadió :func:`register`, en orden."""
    return tuple(_STATE.items)


def register() -> None:
    """Añade los atajos del catálogo al *keyconfig* de complementos; sin él (Blender sin
    mapas de teclas), no hace nada. Si ya están, no los añade otra vez."""
    if _STATE.items:
        return
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is None:
        return
    try:
        for shortcut in catalog().shortcuts():
            keymap = _keymap(keyconfig, shortcut.keymap)
            item = keymap.keymap_items.new(
                shortcut.idname, shortcut.event, "PRESS",
                ctrl=shortcut.ctrl, shift=shortcut.shift, alt=shortcut.alt,
            )
            _STATE.items.append((keymap, item))
            for name, value in split_key(shortcut.key)[1]:
                setattr(item.properties, name, value)
    except BaseException:
        unregister()
        raise


def unregister() -> None:
    """Quita los elementos añadidos y los mapas creados que quedan vacíos."""
    while _STATE.items:
        keymap, item = _STATE.items.pop()
        try:
            keymap.keymap_items.remove(item)
        except (ReferenceError, RuntimeError):
            pass  # ya no estaba (Blender lo quitó o se recargaron los mapas)
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    while _STATE.created:
        keymap = _STATE.created.pop()
        try:
            if keyconfig is not None and len(keymap.keymap_items) == 0:
                keyconfig.keymaps.remove(keymap)
        except (ReferenceError, RuntimeError):
            pass
