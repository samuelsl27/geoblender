# SPDX-License-Identifier: GPL-3.0-or-later
"""El filtro reversible de los paneles nativos del editor de Propiedades (spec 019, T15;
RF-019-03, RF-019-04; ADR-0032 punto 2; plan 019 A3, P-5, R-7, R-8, R-12).

En modo Geoblender el editor de Propiedades solo debe mostrar los paneles de Geoblender. El
``poll`` de cada panel nativo (los de ``bl_space_type = 'PROPERTIES'`` que no son de
Geoblender) se sustituye por uno que devuelve falso si **el espacio de trabajo de su
contexto** (``context.workspace``, el de esa ventana: R-12) es de Geoblender y, si no, llama
al original (y si este falla, verdadero, como Blender).

**Técnica (T01, 25/11/2026, Blender 5.2.1):** Blender fija el ``poll`` de una clase al
registrarla; sustituir el atributo sin más solo afecta a los paneles que ya tenían ``poll``.
Por eso se **desregistra y se vuelve a registrar el árbol de paneles del contexto Objeto**
(el de las pestañas visibles; 26 clases, los padres antes que los hijos) con el ``poll`` ya
puesto. Re-registrar un padre suelto deja huérfanos a sus hijos. Retirar es lo inverso:
desregistrar, devolver el atributo (el mismo objeto de antes, o borrarlo si la clase no tenía)
y registrar de nuevo **en el orden original**.

- :func:`sync` decide: instala si alguna ventana está en modo Geoblender y retira si ninguna
  lo está (P-5: mientras haya una; no por registro). Lo llaman el conmutador, la suscripción
  de ``msgbus`` a ``Window.workspace``, ``load_post`` y :func:`register`.
- :func:`install` y :func:`remove` son idempotentes. Tras ``script.reload`` el módulo pierde
  su estado, pero cada ``poll`` nuestro lleva la marca :data:`MARK` con el original: se
  recupera de ahí y nunca se envuelve dos veces.
- :func:`rescan` (Ayuda ▸ Reparar la interfaz, R-7) retira y vuelve a escanear, por si otro
  complemento añadió paneles.
- Modo degradado (R-8, ``bl.compat.native_filter_shape``): si el árbol del contexto Objeto no
  tiene la forma esperada o un registro falla, no se filtra nada, se deja todo como estaba y
  se dice una vez en el registro técnico (:func:`degraded_reason`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import bpy
from bpy.app.handlers import persistent

from .. import compat
from . import gate

LOGGER = logging.getLogger("geoblender.bl.ui")
MARK = "_gb_native_filter"  # en la función del poll nuestro: (clase, original propio, original)
OURS_PREFIX = "GEOBLENDER_"
SPACE = "PROPERTIES"


@dataclass
class Patch:
    """Lo que se tocó de una clase: si tenía ``poll`` propio (la entrada del ``__dict__``,
    para devolver el mismo objeto) y el ``poll`` que llamaba (ligado a la clase)."""

    cls: type
    own: Any  # la entrada de cls.__dict__["poll"] o None si no la tenía
    bound: Any  # cls.poll antes de parchear, o None si no había


@dataclass
class _State:
    patches: dict[type, Patch] = field(default_factory=dict)
    tree: list[type] = field(default_factory=list)  # las clases re-registradas, en su orden
    degraded: str | None = None
    said: bool = False
    owner: object = field(default_factory=object)  # dueño de la suscripción de msgbus


_STATE = _State()


# Escanear -------------------------------------------------------------------------------


def _is_native(cls: type) -> bool:
    return (
        getattr(cls, "bl_space_type", "") == SPACE
        and not cls.__name__.startswith(OURS_PREFIX)
        and bool(getattr(cls, "is_registered", False))
    )


def _marked(cls: type) -> Any:
    own = cls.__dict__.get("poll")
    function = getattr(own, "__func__", own)
    return getattr(function, MARK, None)


def scan() -> list[type]:
    """Los paneles nativos registrados del editor de Propiedades (de Blender o de otro
    complemento), en el orden en que Python creó sus clases."""
    return [cls for cls in bpy.types.Panel.__subclasses__() if _is_native(cls)]


def object_tree(classes: list[type]) -> list[type]:
    """El árbol del contexto de las pestañas visibles (Objeto), en orden de registro."""
    context = compat.native_filter_shape().context
    return [cls for cls in classes if getattr(cls, "bl_context", "") == context]


def _tree_ok(tree: list[type]) -> str | None:
    """Por qué el árbol no tiene la forma esperada, o ``None`` si la tiene."""
    if len(tree) < compat.native_filter_shape().min_classes:
        return f"el contexto «{compat.native_filter_shape().context}» tiene {len(tree)} paneles"
    position = {cls.__name__: index for index, cls in enumerate(tree)}
    for index, cls in enumerate(tree):
        parent = getattr(cls, "bl_parent_id", "")
        if parent and position.get(parent, index + 1) > index:
            return f"«{cls.__name__}» va antes que su padre «{parent}»"
    return None


# El poll --------------------------------------------------------------------------------


def _make_poll(cls: type, own: Any, bound: Any) -> Any:
    def poll(klass: Any, context: Any) -> bool:
        if gate.is_geoblender_workspace(getattr(context, "workspace", None)):
            return False
        if bound is None:
            return True
        try:
            return bool(bound(context))
        except Exception:  # noqa: BLE001 - como Blender: si el poll falla, se dibuja
            return True

    setattr(poll, MARK, (cls, own, bound))
    return classmethod(poll)


def _capture(cls: type) -> Patch:
    marked = _marked(cls)
    if marked is not None:  # un parche de un módulo anterior (script.reload)
        _cls, own, bound = marked
        return Patch(cls, own, bound)
    own = cls.__dict__.get("poll")
    return Patch(cls, own, getattr(cls, "poll", None))


def _apply(patch: Patch) -> None:
    patch.cls.poll = _make_poll(patch.cls, patch.own, patch.bound)


def _restore(patch: Patch) -> None:
    if patch.own is not None:
        patch.cls.poll = patch.own
    elif "poll" in patch.cls.__dict__:
        del patch.cls.poll


# Instalar y retirar ---------------------------------------------------------------------


def installed() -> bool:
    """Verdadero mientras el filtro está puesto."""
    return bool(_STATE.patches)


def degraded_reason() -> str | None:
    """Por qué el filtro no se instala en esta versión de Blender (R-8), o ``None``."""
    return _STATE.degraded


def _degrade(reason: str) -> None:
    _STATE.degraded = reason
    if not _STATE.said:
        _STATE.said = True
        LOGGER.warning("Modo degradado del filtro de paneles nativos: %s. Se dejan a la vista "
                       "los paneles de Blender (ADR-0032, R-8)", reason)


def _unregister_tree(tree: list[type]) -> None:
    for cls in reversed(tree):
        if getattr(cls, "is_registered", False):
            bpy.utils.unregister_class(cls)


def _register_tree(tree: list[type]) -> None:
    for cls in tree:
        if not getattr(cls, "is_registered", False):
            bpy.utils.register_class(cls)


def _adopt_marked() -> None:
    """Tras ``script.reload``: recupera el inventario de los ``poll`` nuestros que quedaron."""
    if _STATE.patches:
        return
    for cls in scan():
        marked = _marked(cls)
        if marked is not None:
            _STATE.patches[cls] = Patch(cls, marked[1], marked[2])
    if _STATE.patches:
        _STATE.tree = object_tree(list(_STATE.patches))


def install() -> bool:
    """Pone el filtro (idempotente). Devuelve verdadero si queda puesto; falso en modo
    degradado (no se toca nada)."""
    _adopt_marked()
    if _STATE.patches:
        return True
    classes = scan()
    tree = object_tree(classes)
    reason = _tree_ok(tree)
    if reason is not None:
        _degrade(reason)
        return False
    patches = {cls: _capture(cls) for cls in classes}
    try:
        _unregister_tree(tree)
        for patch in patches.values():
            _apply(patch)
        _register_tree(tree)
    except Exception as exc:  # noqa: BLE001 - se deja Blender como estaba
        _rollback(patches, tree)
        _degrade(f"no se pudo registrar de nuevo el árbol ({exc})")
        return False
    _STATE.patches, _STATE.tree = patches, tree
    _STATE.degraded = None
    return True


def _rollback(patches: dict[type, Patch], tree: list[type]) -> None:
    try:
        _unregister_tree(tree)
    finally:
        for patch in patches.values():
            _restore(patch)
        _register_tree(tree)


def remove() -> None:
    """Retira el filtro (idempotente): desregistra el árbol, devuelve cada ``poll`` (el mismo
    objeto, o lo borra si la clase no tenía) y lo registra de nuevo en el orden original."""
    _adopt_marked()
    patches, tree = _STATE.patches, _STATE.tree
    _STATE.patches, _STATE.tree = {}, []
    if not patches:
        return
    _rollback(patches, tree)


def rescan() -> bool:
    """Ayuda ▸ Reparar la interfaz (R-7): si estaba puesto, lo retira y lo vuelve a poner con
    lo que hay ahora; si no, lo decide :func:`sync`. Devuelve si queda puesto."""
    was = installed()
    remove()
    _STATE.degraded = None
    return install() if was else sync()


# Cuándo vive ----------------------------------------------------------------------------


def any_geoblender_window(windows: Any = None) -> bool:
    """Verdadero si alguna ventana (por defecto, las del gestor) está en modo Geoblender."""
    if windows is None:
        manager = getattr(bpy.context, "window_manager", None)
        windows = getattr(manager, "windows", ())
    return any(gate.is_geoblender_workspace(getattr(window, "workspace", None))
               for window in windows)


def sync(windows: Any = None) -> bool:
    """P-5: instala el filtro si alguna ventana está en modo Geoblender y lo retira si
    ninguna. Devuelve si queda puesto."""
    if any_geoblender_window(windows):
        return install()
    remove()
    return False


def _deferred_sync() -> None:
    try:
        sync()
    except Exception:  # noqa: BLE001 - no hay a quién propagarlo desde un temporizador
        LOGGER.exception("Falló el filtro de paneles nativos al cambiar de espacio de trabajo")


def _on_workspace_changed() -> None:
    """Lo que avisa ``msgbus`` al cambiar el espacio de trabajo de una ventana: se decide
    fuera del aviso, en el ciclo siguiente."""
    if not bpy.app.timers.is_registered(_deferred_sync):
        bpy.app.timers.register(_deferred_sync, first_interval=0.0, persistent=True)


def _subscribe() -> None:
    bpy.msgbus.clear_by_owner(_STATE.owner)
    bpy.msgbus.subscribe_rna(key=(bpy.types.Window, "workspace"), owner=_STATE.owner, args=(),
                             notify=_on_workspace_changed)


@persistent
def on_load_post(*_args: Any) -> None:
    """Tras cargar un ``.blend``: Blender borra las suscripciones de ``msgbus``; se renueva y
    se decide otra vez (el fichero puede venir con una ventana en modo Geoblender)."""
    _subscribe()
    _on_workspace_changed()


def register() -> None:
    """Suscribe el cambio de espacio de trabajo y decide una vez; sin ventanas (``-b``) no
    instala nada."""
    _subscribe()
    if on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_load_post)
    _on_workspace_changed()


def unregister() -> None:
    """Retira el filtro y todo lo que lo mantenía vivo (``unregister()``, P-5)."""
    bpy.msgbus.clear_by_owner(_STATE.owner)
    if on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load_post)
    if bpy.app.timers.is_registered(_deferred_sync):
        bpy.app.timers.unregister(_deferred_sync)
    remove()
    _STATE.degraded = None
    _STATE.said = False
