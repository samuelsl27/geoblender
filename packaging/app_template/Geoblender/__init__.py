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
- deja la escena de Archivo ▸ Nuevo en metros;
- **vuelve a abrir la imagen de bienvenida** que cierra ese cambio (hallazgo D5, T44).
  Blender la abre antes del primer ciclo de eventos, en la ventana con el «Layout», y al
  aplicar el cambio de espacio cierra las ventanas emergentes de la ventana. Mientras
  arranca, la plantilla anota en qué ventanas se dibuja (un añadido a ``WM_MT_splash`` y a
  ``WM_MT_splash_quick_setup`` que no dibuja nada y que quita en su primer ciclo) y, si pasa
  una de ellas al espacio principal, la vuelve a abrir cuando el cambio se ha aplicado. Si
  Blender no la abrió (la preferencia apagada, un fichero abierto), no abre nada.

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
# Los menús que dibuja la imagen de bienvenida de Blender (la normal y la de la primera vez).
SPLASH_MENUS = ("WM_MT_splash", "WM_MT_splash_quick_setup")
SPLASH_WAIT_CYCLES = 20  # ciclos de eventos que se espera a que se aplique el cambio


class _State:
    def __init__(self) -> None:
        self.enabled_here: list[str] = []  # módulos que habilitó la plantilla
        self.requested: list[str] = []  # espacios pedidos para las ventanas
        self.switched: list[int] = []  # las ventanas a las que se pidieron (as_pointer)
        self.splash_windows: set[int] = set()  # dónde se dibujó la imagen de bienvenida
        self.reopen: list[int] = []  # dónde hay que volver a abrirla
        self.reopen_cycles = 0


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
    switched: list[int] = []
    manager = getattr(bpy.context, "window_manager", None)
    if workspace is None or manager is None:
        return requested
    for window in manager.windows:
        current = window.workspace
        if current is workspace or is_marked(current):
            continue
        window.workspace = workspace
        requested.append(workspace.name)
        switched.append(window.as_pointer())
    _STATE.requested = requested
    _STATE.switched = switched
    return requested


def _note_splash(_menu: Any, context: Any) -> None:
    """Añadido a los menús de la imagen de bienvenida mientras se arranca: anota la
    ventana donde se dibuja (no dibuja nada)."""
    window = getattr(context, "window", None)
    if window is not None:
        _STATE.splash_windows.add(window.as_pointer())


def watch_splash() -> None:
    """Empieza a anotar dónde se dibuja la imagen de bienvenida."""
    for name in SPLASH_MENUS:
        menu = getattr(bpy.types, name, None)
        if menu is not None:
            menu.remove(_note_splash)
            menu.append(_note_splash)


def unwatch_splash() -> None:
    """Deja de anotarlo."""
    for name in SPLASH_MENUS:
        menu = getattr(bpy.types, name, None)
        if menu is not None:
            menu.remove(_note_splash)


def open_splash(window: Any) -> None:
    """Abre la imagen de bienvenida en ``window`` (la de la plantilla: Blender la toma de
    su carpeta)."""
    with bpy.context.temp_override(window=window):
        bpy.ops.wm.splash("INVOKE_DEFAULT")


def _reopen_splash() -> float | None:
    """Temporizador: vuelve a abrir la imagen de bienvenida en cada ventana donde la
    cerró el cambio al espacio principal, en cuanto ese cambio se ha aplicado (la ventana
    está en un espacio de Geoblender); deja de esperar al cabo de ``SPLASH_WAIT_CYCLES``."""
    manager = getattr(bpy.context, "window_manager", None)
    windows = {window.as_pointer(): window for window in manager.windows} if manager else {}
    pending: list[int] = []
    for pointer in _STATE.reopen:
        window = windows.get(pointer)
        if window is None:
            continue
        if is_marked(window.workspace):
            try:
                open_splash(window)
            except RuntimeError as exc:  # el operador no se puede ejecutar: no se insiste
                print(f"Geoblender: no se ha podido abrir la imagen de bienvenida: {exc}")
        else:
            pending.append(pointer)
    _STATE.reopen_cycles += 1
    if pending and _STATE.reopen_cycles < SPLASH_WAIT_CYCLES:
        _STATE.reopen = pending
        return 0.0
    _STATE.reopen = []
    return None


def _startup() -> None:
    """Temporizador del arranque: la extensión, el espacio principal y la imagen de
    bienvenida que cierra ese cambio."""
    enable_extension()
    activate_main_workspace()
    unwatch_splash()
    reopen = [pointer for pointer in _STATE.switched if pointer in _STATE.splash_windows]
    _STATE.splash_windows.clear()
    if reopen:
        _STATE.reopen = reopen
        _STATE.reopen_cycles = 0
        if not bpy.app.timers.is_registered(_reopen_splash):
            bpy.app.timers.register(_reopen_splash, first_interval=0.0)
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
    watch_splash()
    bpy.app.timers.register(_startup, first_interval=0.0)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    if _on_factory_startup not in bpy.app.handlers.load_factory_startup_post:
        bpy.app.handlers.load_factory_startup_post.append(_on_factory_startup)


def unregister() -> None:
    if bpy.app.timers.is_registered(_startup):
        bpy.app.timers.unregister(_startup)
    if bpy.app.timers.is_registered(_reopen_splash):
        bpy.app.timers.unregister(_reopen_splash)
    unwatch_splash()
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    if _on_factory_startup in bpy.app.handlers.load_factory_startup_post:
        bpy.app.handlers.load_factory_startup_post.remove(_on_factory_startup)
    for name in _STATE.enabled_here:
        addon_utils.disable(name, default_set=False)
    _STATE.enabled_here.clear()
    _STATE.requested = []
    _STATE.switched = []
    _STATE.splash_windows.clear()
    _STATE.reopen = []
