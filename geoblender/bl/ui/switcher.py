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
- :func:`add_blender_hook`: lo que se avisa al conmutar una ventana a la interfaz de Blender
  (spec 012, T26: la superposición «Ver restricciones y límites» se quita al conmutar, RF-012-18),
  desde :func:`toggle` y :func:`activate`, sin argumentos; uno que falla va al registro técnico y no
  impide conmutar.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import bpy
from bpy.app.handlers import persistent

from ...core.i18n import tr
from . import areas, gate, native_filter
from .commands import catalog

LOGGER = logging.getLogger("geoblender.bl.ui")
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
    occupied: Collection[str] = (),
) -> Choice:
    """El destino de conmutar la ventana desde ``current`` (CW §3.1–§3.3); ``names``,
    los espacios del fichero en orden; ``marked``, los de Geoblender; ``mode``,
    ``TOGGLE``, ``GEOBLENDER`` o ``BLENDER``; ``main``, el espacio principal de
    Geoblender; ``occupied``, los espacios que ya usa **otra** ventana (Blender no admite el mismo
    espacio en dos ventanas y movería la otra: spec 019, T40): nunca se elige uno; si no queda
    ninguno libre, se anexa una copia."""
    if mode not in TARGETS:
        raise ValueError(f"modo «{mode}»: se espera {', '.join(TARGETS)}")
    in_geoblender = current in marked
    to_geoblender = (not in_geoblender) if mode == "TOGGLE" else mode == "GEOBLENDER"
    if to_geoblender == in_geoblender:
        return Choice(to_geoblender=to_geoblender, noop=True)
    present = set(names) - set(occupied)
    if to_geoblender:
        for name in (last_geoblender, main):
            if name and name in present and name in marked:
                return Choice(True, target=name)
        others = [name for name in names if name in present and name in marked]
        return Choice(True, target=others[0]) if others else Choice(True, append=main)
    for name in (previous_blender, fallback):
        if name and name in present and name not in marked:
            return Choice(False, target=name)
    others = [name for name in names if name in present and name not in marked]
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
    layout_notified: bool = False  # el aviso de la disposición anterior, una vez por fichero
    attempts: int = 0
    settings: list[tuple[int, str]] = field(default_factory=list)  # (ventana nueva, espacio) por fijar


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
    _SESSION.layout_notified = False
    _SESSION.settings.clear()


# Avisar de que se conmutó a Blender ------------------------------------------------------------

_BLENDER_HOOKS: list[Callable[[], object]] = []


def add_blender_hook(hook: Callable[[], object]) -> None:
    """Apunta ``hook`` (sin argumentos) para llamarlo cada vez que una ventana se conmuta a la
    interfaz de Blender (:func:`toggle`, :func:`activate`); si ya estaba, no hace nada."""
    if hook not in _BLENDER_HOOKS:
        _BLENDER_HOOKS.append(hook)


def remove_blender_hook(hook: Callable[[], object]) -> None:
    """Deja de avisar a ``hook``; si no estaba, no hace nada."""
    if hook in _BLENDER_HOOKS:
        _BLENDER_HOOKS.remove(hook)


def blender_hooks() -> tuple[Callable[[], object], ...]:
    """Lo apuntado con :func:`add_blender_hook`, por orden."""
    return tuple(_BLENDER_HOOKS)


def _entered_blender() -> None:
    """Avisa a cada apuntado de que una ventana pasa a la interfaz de Blender; uno que falla va
    al registro técnico y no impide conmutar ni avisar a los demás."""
    for hook in list(_BLENDER_HOOKS):
        try:
            hook()
        except Exception:  # noqa: BLE001 - conmutar no depende de quien se entera
            LOGGER.exception("Falló lo que se quita al conmutar a la interfaz de Blender")


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


def _occupied(window: Any, windows: Any = None) -> set[str]:
    """Los espacios que usan las **otras** ventanas (el activo y el pendiente de aplicar); ``windows``,
    solo para probar."""
    if windows is None:
        windows = bpy.context.window_manager.windows
    me = window.as_pointer()
    names: set[str] = set()
    for other in windows:
        if other.as_pointer() == me:
            continue
        if other.workspace is not None:
            names.add(other.workspace.name)
        state = _SESSION.windows.get(other.as_pointer())
        if state is not None and state.pending:
            names.add(state.pending)
    return names


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


# La revisión de la disposición (spec 019, T18; P-9, R-4) ------------------------------------------


def outdated_layouts() -> list[str]:
    """Los nombres (del catálogo) de las disposiciones que el fichero tiene con una revisión
    anterior a ``areas.LAYOUT_REV`` (``WorkSpace["geoblender_layout_rev"]``; sin la clave, la 1).
    No cambia nada."""
    revisions = {ws.name: ws.get(areas.REV_KEY) for ws in bpy.data.workspaces
                 if gate.is_geoblender_workspace(ws)}
    return areas.outdated_names(revisions, [layout.workspace for layout in catalog().layouts])


def notify_outdated_layout() -> bool:
    """Al entrar en Geoblender: si el fichero tiene una disposición anterior, lo avisa **una
    vez** («La disposición de este fichero es anterior…», 10 s en la barra de estado) y no
    cambia nada solo (P-9). Devuelve si avisó."""
    if _SESSION.layout_notified or not outdated_layouts():
        return False
    _SESSION.layout_notified = True
    from . import notices  # diferido: notices importa este módulo

    notices.post("info", tr("The layout of this file is older: Layouts ▾ ▸ Update the layout"),
                 ttl=notices.UNDO_TTL)  # 10 s (spec 019, T18; la cola de T22)
    return True


def update_layouts(window: Any) -> list[str]:
    """Renueva las disposiciones anteriores: anexa una copia nueva de cada una desde los
    recursos y **conserva las anteriores** (principio 7: nada del usuario se borra ni se
    renombra). Si ``window`` usa una anterior, pasa (diferido) a su copia nueva. Devuelve los
    nombres de las copias nuevas."""
    created: list[str] = []
    for name in outdated_layouts():
        old = bpy.data.workspaces.get(name)
        fresh = load_workspace(name)
        created.append(fresh.name)
        if old is not None and window is not None and window.workspace == old:
            activate(window, fresh)
    return created


def toggle(window: Any, mode: str = "TOGGLE", windows: Any = None) -> Result:
    """Conmuta ``window`` al modo pedido (CW §3): guarda el anterior en el estado de
    sesión, anexa el destino si hace falta y lo asigna (diferido). Solo cambia esa ventana: nunca
    elige un espacio que use otra (T40); ``windows``, solo para probar."""
    state = window_state(window)
    current = window.workspace.name if window.workspace else ""
    names = [ws.name for ws in bpy.data.workspaces]
    choice = choose_target(
        current=current, names=names, marked=_marked(), mode=mode,
        last_geoblender=state.last_geoblender, previous_blender=state.previous_blender,
        main=main_workspace(), occupied=_occupied(window, windows),
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
    if choice.to_geoblender:
        notify_outdated_layout()
    else:
        _entered_blender()
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
    if (current is not None and gate.is_geoblender_workspace(current)
            and not gate.is_geoblender_workspace(workspace)):
        _entered_blender()
    elif (current is None or not gate.is_geoblender_workspace(current))             and gate.is_geoblender_workspace(workspace):
        notify_outdated_layout()


# «Ajustes de Blender» (spec 019, T19; RF-019-03; ADR-0032 punto 3) ----------------------------------

SETTINGS_DELAY_S = 0.1  # «el ciclo siguiente»: ``window.workspace`` es diferido y cerraría las ventanas emergentes


def _new_window(window: Any) -> Any | None:
    """Abre una ventana nueva (``wm.window_new``, con el área de Propiedades de ``window`` si la tiene) y
    la devuelve; ``None`` si Blender no la abre (sin interfaz, el operador no tiene contexto)."""
    areas = list(window.screen.areas)
    area = next((a for a in areas if a.type == "PROPERTIES"), areas[0] if areas else None)
    region = next((r for r in area.regions if r.type == "WINDOW"), None) if area is not None else None
    if area is None or region is None:
        return None
    before = {w.as_pointer() for w in bpy.context.window_manager.windows}
    try:
        with bpy.context.temp_override(window=window, screen=window.screen, area=area, region=region):
            bpy.ops.wm.window_new()
    except RuntimeError:
        return None
    return next((w for w in bpy.context.window_manager.windows if w.as_pointer() not in before), None)


def settings_workspace(window: Any) -> Any | None:
    """El espacio de trabajo **no marcado** donde Propiedades es la nativa y completa: el anterior de Blender de
    ``window`` o «Layout»; si no, el primero que no sea de Geoblender; ``None`` si todos lo son."""
    choice = choose_target(
        current=window.workspace.name if window.workspace else "", names=[ws.name for ws in bpy.data.workspaces],
        marked=_marked(), mode="BLENDER", previous_blender=window_state(window).previous_blender,
        main=main_workspace(), occupied=_occupied(window),
    )
    if choice.noop:  # la ventana ya está en un espacio de Blender: el mismo vale
        return window.workspace
    return bpy.data.workspaces.get(choice.target) if choice.target else None


def open_blender_settings(window: Any) -> Any | None:
    """Abre la ventana de «Ajustes de Blender»: una ventana nueva que pasa, **en el ciclo siguiente**
    (:func:`settle_settings`), a un espacio no marcado. ``window`` no se toca. Devuelve la ventana nueva o ``None``."""
    workspace = settings_workspace(window)
    if workspace is None:
        return None
    new = _new_window(window)
    if new is None:
        return None
    _SESSION.settings.append((new.as_pointer(), workspace.name))
    if not bpy.app.timers.is_registered(settle_settings):
        bpy.app.timers.register(settle_settings, first_interval=SETTINGS_DELAY_S)
    return new


def settle_settings(windows: Any = None) -> None:
    """Fija el espacio de cada ventana de «Ajustes de Blender» abierta (lo llama el temporizador; ``windows``,
    solo para probar) y deja al conmutador comprobar que se aplicó."""
    todo, _SESSION.settings[:] = list(_SESSION.settings), []
    if windows is None:
        windows = bpy.context.window_manager.windows
    by_pointer = {w.as_pointer(): w for w in windows}
    for pointer, name in todo:
        window, workspace = by_pointer.get(pointer), bpy.data.workspaces.get(name)
        if window is None or workspace is None:
            continue  # la cerraron antes de tiempo
        window.workspace = workspace
        window_state(window).pending = name
    if todo:
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
    changed = False
    for window in bpy.context.window_manager.windows:
        state = _SESSION.windows.get(window.as_pointer())
        if state is None or state.pending is None:
            continue
        if window.workspace is not None and window.workspace.name == state.pending:
            state.pending = None
            _show_tool_header(window)
            changed = True
        else:
            waiting = True
    if changed:
        native_filter.sync()  # ADR-0032 punto 2, P-5: el filtro vive mientras haya una ventana
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
            main=main_workspace(), occupied=_occupied(window),
        )
        if choice.target is not None:
            window.workspace = bpy.data.workspaces[choice.target]
    if bpy.app.timers.is_registered(check_pending):
        bpy.app.timers.unregister(check_pending)
    if bpy.app.timers.is_registered(settle_settings):
        bpy.app.timers.unregister(settle_settings)
    if on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load_post)
    _BLENDER_HOOKS.clear()
    forget()
