# SPDX-License-Identifier: GPL-3.0-or-later
"""Plantilla de aplicación «Geoblender» (spec 003; RF-003-25; ADR-0003; CW §7; plan 003
§5.4, 13; D-2).

Blender la carga con ``blender --app-template Geoblender`` (el lanzador
``Geoblender.cmd``), con Archivo ▸ Nuevo ▸ Geoblender o desde la imagen de bienvenida. Sus
ficheros (``startup.blend``, ``userpref.blend``, ``splash.png`` y ``splash_2x.png``) los
genera ``tools/make_app_template.py`` y los instala ``tools/install_app_template.py``. La
configuración que guarde la persona con la plantilla va a ``config/Geoblender/``: el
Blender normal no cambia.

Toda la lógica está en la extensión (ADR-0003). La plantilla solo:

- **habilita la extensión** si ``userpref.blend`` apunta a otro repositorio de extensiones
  (la busca por el sufijo ``.geoblender``), de forma diferida: ``register()`` corre antes
  de que existan los repositorios (``No module named 'bl_ext'``, inv. 09 §2.3 [V]); con un
  temporizador y con ``load_post`` (``addon_utils.enable(…, default_set=False)``, sin tocar
  las preferencias);
- **pasa cada ventana al espacio principal de Geoblender** al arrancar y con Archivo ▸
  Nuevo (``load_factory_startup_post``): el ``startup.blend`` trae ese espacio
  (``geoblender_mode``) y el «Layout» de respaldo, pero no se puede guardar con el principal
  activo sin interfaz. El cambio es diferido: lo aplica el primer ciclo de eventos. Al abrir
  un fichero de la persona no cambia nada: manda el fichero;
- deja la escena de Archivo ▸ Nuevo en metros.

``unregister()`` quita lo que puso y deshabilita la extensión solo si la habilitó ella.
"""

from __future__ import annotations

from typing import Any

import addon_utils
import bpy
from bpy.app.handlers import persistent

EXTENSION_SUFFIX = ".geoblender"
WORKSPACE_FLAG = "geoblender_mode"
MAIN_WORKSPACE = "Geoblender"


class _State:
    def __init__(self) -> None:
        self.enabled_here: list[str] = []  # módulos que habilitó la plantilla
        self.requested: list[str] = []  # espacios pedidos para las ventanas


_STATE = _State()


def find_extension() -> str | None:
    """El módulo de la extensión instalada (``bl_ext.<repositorio>.geoblender``)."""
    for module in addon_utils.modules(refresh=False):
        if module.__name__.endswith(EXTENSION_SUFFIX):
            return module.__name__
    return None


def enable_extension() -> str | None:
    """Habilita la extensión si está instalada y no lo está ya; devuelve su módulo."""
    name = find_extension()
    if name is None:
        print("Geoblender: la extensión no está instalada en este perfil de Blender")
        return None
    if name not in bpy.context.preferences.addons:
        addon_utils.enable(name, default_set=False, persistent=True)
        _STATE.enabled_here.append(name)
    return name


def is_marked(workspace: Any) -> bool:
    """Si ``workspace`` es de Geoblender (la marca la define la extensión: sin ella
    habilitada, ninguno lo es)."""
    return bool(workspace is not None and getattr(workspace, WORKSPACE_FLAG, False))


def main_workspace() -> Any:
    """El espacio principal de Geoblender del fichero: el que se llama así o, si no, el
    primero marcado; ``None`` si no hay."""
    named = bpy.data.workspaces.get(MAIN_WORKSPACE)
    if named is not None:
        return named
    return next((ws for ws in bpy.data.workspaces if is_marked(ws)), None)


def activate_main_workspace() -> list[str]:
    """Pide el espacio principal para cada ventana que no está en uno de Geoblender
    (diferido); devuelve los nombres pedidos, uno por ventana."""
    workspace = main_workspace()
    requested: list[str] = []
    manager = getattr(bpy.context, "window_manager", None)
    if workspace is None or manager is None:
        return requested
    for window in manager.windows:
        current = window.workspace
        if current is workspace or is_marked(current):
            continue
        window.workspace = workspace
        requested.append(workspace.name)
    _STATE.requested = requested
    return requested


def _startup() -> None:
    """Temporizador del arranque: la extensión y el espacio principal."""
    enable_extension()
    activate_main_workspace()
    return None


@persistent
def _on_load_post(*_args: Any) -> None:
    """Respaldo: si la extensión aún no está habilitada, la habilita."""
    if find_extension() not in bpy.context.preferences.addons:
        enable_extension()


@persistent
def _on_factory_startup(*_args: Any) -> None:
    """Archivo ▸ Nuevo con la plantilla: escena en metros y el espacio principal."""
    for scene in bpy.data.scenes:
        scene.unit_settings.system = "METRIC"
        scene.unit_settings.length_unit = "METERS"
    activate_main_workspace()


def register() -> None:
    bpy.app.timers.register(_startup, first_interval=0.0)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    if _on_factory_startup not in bpy.app.handlers.load_factory_startup_post:
        bpy.app.handlers.load_factory_startup_post.append(_on_factory_startup)


def unregister() -> None:
    if bpy.app.timers.is_registered(_startup):
        bpy.app.timers.unregister(_startup)
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    if _on_factory_startup in bpy.app.handlers.load_factory_startup_post:
        bpy.app.handlers.load_factory_startup_post.remove(_on_factory_startup)
    for name in _STATE.enabled_here:
        addon_utils.disable(name, default_set=False)
    _STATE.enabled_here.clear()
    _STATE.requested = []
