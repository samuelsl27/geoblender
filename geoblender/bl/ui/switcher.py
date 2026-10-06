# SPDX-License-Identifier: GPL-3.0-or-later
"""El conmutador Geoblender ⇄ Blender (spec 003; RF-003-02, RF-003-23; plan 003 §5.4, 4;
CW §3; ADR-0012).

Una ventana está en modo Geoblender cuando su espacio de trabajo activo está marcado
(``WorkSpace.geoblender_mode``; CW §1). Conmutar es cambiar el espacio de trabajo de esa
ventana, sin recargar el fichero: no cambia preferencias, tema, idioma de Blender, mapa de
teclas, complementos, escena, datos ni la pila de deshacer.

- :func:`choose_target` (función pura de nombres) elige el destino (CW §3.1 y §3.2): a
  Geoblender, el último espacio marcado que usó la ventana, el principal «Geoblender»,
  cualquier otro marcado o, si no hay ninguno, anexarlo desde
  ``resources/geoblender_ui.blend``; a Blender, el «anterior de Blender» de la ventana si
  existe y no está marcado, «Layout», el primero sin marcar o, si no hay ninguno, anexar
  «Layout». Pedir el modo en que ya está no hace nada. El principal es el espacio de la
  disposición ``main`` de ``layouts.toml``.
- :func:`toggle` lo aplica: guarda el anterior en el **estado de sesión** (por ventana,
  clave ``window.as_pointer()``; no se guarda en el ``.blend``, CW §3.1), anexa si hace
  falta y asigna ``window.workspace``. La asignación es **diferida** (se aplica en el
  siguiente ciclo de eventos; en segundo plano, nunca): el destino queda pendiente y un
  temporizador comprueba que se ha aplicado y deja visible la fila 2 de sus Vistas 3D la
  primera vez que la ventana entra en ese espacio (CW §3.1, paso 5).
- :func:`unregister` devuelve cada ventana en modo Geoblender a su espacio de Blender
  (RF-003-23; si la asignación diferida no llega a aplicarse, queda en un espacio normal
  con las cabeceras originales) y retira el temporizador y el manejador ``load_post``, que
  olvida el estado de sesión al abrir otro fichero (CW §3.3).
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import bpy
from bpy.app.handlers import persistent

from . import gate
from .commands import catalog

RESOURCES = Path(__file__).resolve().parents[2] / "resources" / "geoblender_ui.blend"
FALLBACK = "Layout"  # el espacio de Blender de respaldo (CW §3.2)
TARGETS = ("TOGGLE", "GEOBLENDER", "BLENDER")
CHECK_INTERVAL_S = 0.05
CHECK_ATTEMPTS = 40  # unos 2 s: si no se aplica, se deja


@dataclass(frozen=True)
class Choice:
    """El destino de un conmutado: el nombre del espacio, o el que hay que anexar desde
    los recursos; ``noop`` si la ventana ya está en el modo pedido."""

    to_geoblender: bool
    target: str | None = None
    append: str | None = None
    noop: bool = False


def choose_target(
    *,
    current: str,
    names: Sequence[str],
    marked: Collection[str],
    mode: str = "TOGGLE",
    last_geoblender: str | None = None,
    previous_blender: str | None = None,
    main: str,
    fallback: str = FALLBACK,
) -> Choice:
    """El destino de conmutar la ventana desde ``current`` (CW §3.1–§3.3); ``names``,
    los espacios del fichero en orden; ``marked``, los de Geoblender; ``mode``,
    ``TOGGLE``, ``GEOBLENDER`` o ``BLENDER``; ``main``, el espacio principal de
    Geoblender."""
    if mode not in TARGETS:
        raise ValueError(f"modo «{mode}»: se espera {', '.join(TARGETS)}")
    in_geoblender = current in marked
    to_geoblender = (not in_geoblender) if mode == "TOGGLE" else mode == "GEOBLENDER"
    if to_geoblender == in_geoblender:
        return Choice(to_geoblender=to_geoblender, noop=True)
    present = set(names)
    if to_geoblender:
        for name in (last_geoblender, main):
            if name and name in present and name in marked:
                return Choice(True, target=name)
        others = [name for name in names if name in marked]
        return Choice(True, target=others[0]) if others else Choice(True, append=main)
    for name in (previous_blender, fallback):
        if name and name in present and name not in marked:
            return Choice(False, target=name)
    others = [name for name in names if name not in marked]
    return Choice(False, target=others[0]) if others else Choice(False, append=fallback)


# Estado de sesión ---------------------------------------------------------------------


@dataclass
class WindowState:
    """Lo que recuerda una ventana en esta sesión (CW §3.1)."""

    previous_blender: str | None = None
    last_geoblender: str | None = None
    pending: str | None = None  # destino asignado que aún no se ha aplicado


@dataclass
class _Session:
    windows: dict[int, WindowState] = field(default_factory=dict)
    seen: set[tuple[int, str]] = field(default_factory=set)  # (ventana, espacio) visitados
    attempts: int = 0


_SESSION = _Session()


def window_state(window: Any) -> WindowState:
    """El estado de sesión de ``window`` (se crea vacío)."""
    return _SESSION.windows.setdefault(window.as_pointer(), WindowState())


def pending(window: Any) -> str | None:
    """El espacio asignado a ``window`` que aún no se ha aplicado."""
    state = _SESSION.windows.get(window.as_pointer())
    return state.pending if state else None


def forget() -> None:
    """Olvida el estado de sesión (al abrir otro fichero, CW §3.3)."""
    _SESSION.windows.clear()
    _SESSION.seen.clear()


# Aplicar ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Result:
    """Lo que hizo :func:`toggle`: el espacio asignado (o ``None``, sin cambio) y si hubo
    que anexarlo desde los recursos."""

    workspace: str | None
    appended: bool = False


def main_workspace() -> str:
    """El nombre del espacio principal de Geoblender (``layouts.toml``, ``main``)."""
    return next(layout.workspace for layout in catalog().layouts if layout.main)


def _marked() -> set[str]:
    return {ws.name for ws in bpy.data.workspaces if gate.is_geoblender_workspace(ws)}


def append_workspace(window: Any, name: str) -> Any:
    """Anexa el espacio ``name`` de ``resources/geoblender_ui.blend`` y lo devuelve
    (``workspace.append_activate``, con el contexto de la ventana)."""
    before = {ws.as_pointer() for ws in bpy.data.workspaces}
    with bpy.context.temp_override(window=window):
        bpy.ops.workspace.append_activate(idname=name, filepath=str(RESOURCES))
    added = [ws for ws in bpy.data.workspaces if ws.as_pointer() not in before]
    if not added:
        raise RuntimeError(f"no se pudo anexar el espacio «{name}» de {RESOURCES.name}")
    forget_resources_library()
    return added[0]


def load_workspace(name: str) -> Any:
    """Anexa una copia del espacio ``name`` de ``resources/geoblender_ui.blend`` **sin
    activarlo** y la devuelve (si el fichero ya tiene uno con ese nombre, Blender le da
    otro: «<nombre>.001»). Para restaurar una disposición (``bl.ui.layouts``)."""
    before = {ws.as_pointer() for ws in bpy.data.workspaces}
    with bpy.data.libraries.load(str(RESOURCES), link=False) as (source, target):
        if name not in source.workspaces:
            raise RuntimeError(f"«{RESOURCES.name}» no tiene el espacio «{name}»")
        target.workspaces = [name]
    added = [ws for ws in bpy.data.workspaces if ws.as_pointer() not in before]
    forget_resources_library()
    if not added:
        raise RuntimeError(f"no se pudo anexar el espacio «{name}» de {RESOURCES.name}")
    return added[0]


def forget_resources_library() -> None:
    """Quita la referencia a ``geoblender_ui.blend`` que deja el anexado: el espacio ya
    es del fichero, y el fichero no debe guardar la ruta de la extensión."""
    for library in list(bpy.data.libraries):
        if Path(bpy.path.abspath(library.filepath)).name != RESOURCES.name:
            continue
        users = bpy.data.user_map(subset=[library]).get(library, set())
        if not users:  # ningún dato vinculado la usa (Blender le deja un usuario)
            bpy.data.libraries.remove(library)


def toggle(window: Any, mode: str = "TOGGLE") -> Result:
    """Conmuta ``window`` al modo pedido (CW §3): guarda el anterior en el estado de
    sesión, anexa el destino si hace falta y lo asigna (diferido)."""
    state = window_state(window)
    current = window.workspace.name if window.workspace else ""
    names = [ws.name for ws in bpy.data.workspaces]
    choice = choose_target(
        current=current, names=names, marked=_marked(), mode=mode,
        last_geoblender=state.last_geoblender, previous_blender=state.previous_blender,
        main=main_workspace(),
    )
    if choice.noop:
        return Result(None)
    if choice.to_geoblender:
        state.previous_blender = current
    else:
        state.last_geoblender = current
    appended = choice.append is not None
    if choice.append is not None:
        workspace = append_workspace(window, choice.append)
    else:
        workspace = bpy.data.workspaces[choice.target]
    window.workspace = workspace
    state.pending = workspace.name
    _schedule()
    return Result(workspace.name, appended)


def activate(window: Any, workspace: Any) -> None:
    """Asigna ``workspace`` a ``window`` (diferido) desde otra parte de la interfaz (una
    disposición de Disposición ▾): si la ventana estaba en modo Blender y el destino es
    de Geoblender, guarda el espacio actual como su «anterior de Blender» (CW §3.1), y el
    destino queda pendiente, como al conmutar."""
    state = window_state(window)
    current = window.workspace
    if current is not None and current == workspace:
        return
    if (current is not None and not gate.is_geoblender_workspace(current)
            and gate.is_geoblender_workspace(workspace)):
        state.previous_blender = current.name
    window.workspace = workspace
    state.pending = workspace.name
    _schedule()


def _show_tool_header(window: Any) -> None:
    key = (window.as_pointer(), window.workspace.name)
    if key in _SESSION.seen:
        return
    _SESSION.seen.add(key)
    if not gate.is_geoblender_workspace(window.workspace):
        return
    for area in window.screen.areas:
        if area.type == "VIEW_3D":
            area.spaces.active.show_region_tool_header = True


def check_pending() -> float | None:
    """Temporizador: comprueba que los destinos pendientes se han aplicado (y deja visible
    la fila 2); vuelve a mirar mientras quede alguno, unos 2 s como mucho."""
    waiting = False
    for window in bpy.context.window_manager.windows:
        state = _SESSION.windows.get(window.as_pointer())
        if state is None or state.pending is None:
            continue
        if window.workspace is not None and window.workspace.name == state.pending:
            state.pending = None
            _show_tool_header(window)
        else:
            waiting = True
    _SESSION.attempts += 1
    if waiting and _SESSION.attempts < CHECK_ATTEMPTS:
        return CHECK_INTERVAL_S
    _SESSION.attempts = 0
    return None


def _schedule() -> None:
    _SESSION.attempts = 0
    if not bpy.app.timers.is_registered(check_pending):
        bpy.app.timers.register(check_pending, first_interval=0.0)


@persistent
def on_load_post(*_args: Any) -> None:
    """Al abrir otro fichero se pierde el estado de sesión (CW §3.3)."""
    forget()


def register() -> None:
    """Pone el manejador que olvida el estado de sesión al abrir un fichero."""
    if on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_load_post)


def unregister() -> None:
    """Devuelve a Blender cada ventana en modo Geoblender (sin anexar nada), retira el
    temporizador y el manejador y olvida el estado de sesión."""
    for window in bpy.context.window_manager.windows:
        if window.workspace is None or not gate.is_geoblender_workspace(window.workspace):
            continue
        state = window_state(window)
        choice = choose_target(
            current=window.workspace.name, names=[ws.name for ws in bpy.data.workspaces],
            marked=_marked(), mode="BLENDER", previous_blender=state.previous_blender,
            main=main_workspace(),
        )
        if choice.target is not None:
            window.workspace = bpy.data.workspaces[choice.target]
    if bpy.app.timers.is_registered(check_pending):
        bpy.app.timers.unregister(check_pending)
    if on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load_post)
    forget()
