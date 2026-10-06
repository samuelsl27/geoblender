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

Para la ayuda (spec 003, T33; RF-003-27): :func:`current_shortcuts` da los atajos tal como
están ahora (la combinación del elemento registrado o, si la persona la cambió en las
preferencias, la del *keyconfig* de usuario; sin los desactivados) y :func:`conflicts`,
las asignaciones de otros operadores con la misma combinación en el ámbito de la Vista 3D
(:data:`SCOPE`, el de AT §3.1) del *keyconfig* de usuario, que es el que usa Blender.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import bpy

from ...core.catalog.schema import Shortcut, split_key
from .commands import catalog

# Ámbito de la Vista 3D (AT §3.1): una asignación de otro operador con la misma combinación
# en uno de estos mapas es un choque.
SCOPE = frozenset({
    "Window", "Screen", "Screen Editing", "3D View", "3D View Generic", "Object Mode",
    "Object Non-modal", "Mesh", "Curve", "Curves", "Frames", "User Interface",
    "Grease Pencil", "Point Cloud", "Annotate",
})
ANY = -1  # un modificador «cualquiera» en un KeyMapItem

# Mapa del catálogo → (nombre, tipo de espacio, tipo de región) del keyconfig.
KEYMAPS: dict[str, tuple[str, str, str]] = {
    "Window": ("Window", "EMPTY", "WINDOW"),
    "3D View": ("3D View", "VIEW_3D", "WINDOW"),
}


class _State:
    def __init__(self) -> None:
        self.items: list[tuple[Any, Any]] = []  # (mapa, elemento) añadidos, en orden
        self.shortcuts: list[Shortcut] = []  # el atajo del catálogo de cada elemento
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
            _STATE.shortcuts.append(shortcut)
            for name, value in split_key(shortcut.key)[1]:
                setattr(item.properties, name, value)
    except BaseException:
        unregister()
        raise


def unregister() -> None:
    """Quita los elementos añadidos y los mapas creados que quedan vacíos."""
    _STATE.shortcuts.clear()
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


# Estado actual (ayuda) -----------------------------------------------------------------


def _same_properties(item: Any, shortcut: Shortcut) -> bool:
    try:
        return all(getattr(item.properties, name) == value
                   for name, value in split_key(shortcut.key)[1])
    except (AttributeError, TypeError):
        return False


def _user_item(keymap: Any, item: Any, shortcut: Shortcut) -> Any:
    """El elemento del *keyconfig* de usuario que corresponde a uno registrado (``None``
    si no lo hay: sin interfaz, el de usuario no incluye los de complementos)."""
    user = bpy.context.window_manager.keyconfigs.user
    found = user.keymaps.get(keymap.name) if user is not None else None
    if found is None:
        return None
    for candidate in found.keymap_items:
        if candidate.idname == item.idname and _same_properties(candidate, shortcut):
            return candidate
    return None


def current_shortcuts() -> list[Shortcut]:
    """Los atajos registrados tal como están ahora, en el orden del catálogo: con la
    combinación de su elemento (la del de usuario, si existe) y sin los desactivados."""
    current: list[Shortcut] = []
    for (keymap, item), shortcut in zip(_STATE.items, _STATE.shortcuts, strict=True):
        try:
            live = _user_item(keymap, item, shortcut) or item
            if not live.active:
                continue
            current.append(dataclasses.replace(
                shortcut, event=live.type, ctrl=bool(live.ctrl), shift=bool(live.shift),
                alt=bool(live.alt),
            ))
        except ReferenceError:
            continue  # Blender lo quitó (se recargaron los mapas)
    return current


def _reacts(item: Any, shortcut: Shortcut) -> bool:
    """Si ``item`` reacciona a la combinación de ``shortcut``."""
    if not item.active or item.type != shortcut.event or item.key_modifier != "NONE":
        return False
    if item.any:
        return True
    if item.oskey not in (0, False):
        return False
    return all(value == ANY or bool(value) == wanted
               for value, wanted in ((item.ctrl, shortcut.ctrl), (item.shift, shortcut.shift),
                                     (item.alt, shortcut.alt)))


def conflicts() -> list[tuple[Shortcut, str, str]]:
    """(atajo, mapa, operador) de cada asignación de otro operador con la misma combinación
    que un atajo de Geoblender en el ámbito de la Vista 3D del *keyconfig* de usuario."""
    user = bpy.context.window_manager.keyconfigs.user
    if user is None:
        return []
    shortcuts = current_shortcuts()
    found: list[tuple[Shortcut, str, str]] = []
    for keymap in user.keymaps:
        if keymap.name not in SCOPE:
            continue
        for item in keymap.keymap_items:
            if item.idname.startswith("geoblender."):
                continue
            for shortcut in shortcuts:
                if _reacts(item, shortcut):
                    found.append((shortcut, keymap.name, item.idname))
    return found
