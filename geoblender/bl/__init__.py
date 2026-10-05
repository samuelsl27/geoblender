# SPDX-License-Identifier: GPL-3.0-or-later
"""Capa de presentación: el único paquete que importa módulos de Blender (ADR-0004).

``bpy``, ``bmesh``, ``gpu`` y ``mathutils`` solo se importan bajo ``bl/`` (ARQ-01), y
nada importa ``bl`` salvo el ``__init__.py`` raíz dentro de ``register()`` y
``unregister()`` (ARQ-02). Subpaquetes: ``props``, ``scene``, ``draw``, ``gn``, ``ops`` y
``ui``; las diferencias entre versiones de Blender, en ``compat``.

Registro por subpaquetes (plan 001 §5.3, contrato 2): :func:`register` llama al
``register()`` de cada subpaquete en el orden de ``SUBPACKAGES`` y :func:`unregister`
deshace en orden inverso. Las dos son idempotentes: repetirlas, o desregistrar sin
registro previo, no hace nada.

``ADDON_PACKAGE`` es el identificador de la extensión (``bl_ext.<repo>.geoblender``, 3
componentes): lo usan las preferencias, ``extension_path_user``, las traducciones y los
iconos, nunca el ``__package__`` de un submódulo (plan §2.1, 14; contrato 1).
"""

from __future__ import annotations

import importlib
from types import ModuleType

ADDON_PACKAGE: str = __package__.rpartition(".")[0]
SUBPACKAGES: tuple[str, ...] = ("props", "scene", "draw", "gn", "ops", "ui")

_registered = False


def _subpackage(name: str) -> ModuleType:
    """El subpaquete ``name`` de ``bl`` (se importa al registrar, no antes)."""
    return importlib.import_module(f".{name}", __name__)


def register() -> None:
    """Registra los subpaquetes en el orden de ``SUBPACKAGES``; si ya está registrado,
    no hace nada. Si uno falla, deshace los anteriores antes de propagar el error."""
    global _registered
    if _registered:
        return
    done: list[ModuleType] = []
    try:
        for name in SUBPACKAGES:
            module = _subpackage(name)
            module.register()
            done.append(module)
    except BaseException:
        for module in reversed(done):
            module.unregister()
        raise
    _registered = True


def unregister() -> None:
    """Desregistra los subpaquetes en orden inverso; sin registro previo, no hace nada.

    Si uno falla, sigue con los demás (que se deshaga todo lo posible) y propaga el
    primer error al final.
    """
    global _registered
    if not _registered:
        return
    _registered = False
    first_error: BaseException | None = None
    for name in reversed(SUBPACKAGES):
        try:
            _subpackage(name).unregister()
        except BaseException as exc:  # se sigue deshaciendo el resto
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise first_error
