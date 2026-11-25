# SPDX-License-Identifier: GPL-3.0-or-later
"""Aplicar el aspecto de un elemento a su objeto (spec 019, T07; HU-019-1; RF-019-07, RF-019-08; plan 019 §5.2 y A1).

- :func:`apply` recorre las propiedades del aspecto y aplica cada una con su aplicador (:data:`APPLIERS`, un
  diccionario ``tipo → propiedad → función``); **un tipo sin aplicador para una propiedad no la ofrece**
  (:func:`offered`), así «según el tipo» sale del catálogo y no de un ``if``.
- Solo toca **la vista**: ``Object.color`` (con la transparencia en su alfa: es lo que se ve en la vista sólida
  con el color por objeto, T01), un material de visualización con ``diffuse_color`` y ``blend_method`` si hay
  transparencia, ``hide_set``, ``show_name`` y ``show_wire``. **Nunca** la geometría, la procedencia ni el
  proyecto (RF-019-08).
- :func:`read` lee el espejo ``Object.geoblender.look``; :func:`mirror` lo escribe sin disparar el aplicador;
  :func:`reapply` aplica a varios objetos (sin cablear aún: T08 lo llama tras cargar y refrescar).

El grosor de línea y el tamaño de punto los dibuja ``bl.draw.look`` (y, en las curvas, ``bl.draw.contours``) leyendo
el espejo del objeto **solo si hay un valor guardado** (T07b); su aplicador pide redibujar. Se ofrecen en los tipos
que ese dibujo cubre (``bl.draw.style.LINE_KINDS`` y ``POINT_KINDS``); ``DRILLHOLES`` no dibuja puntos: no lo ofrece.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any

import logging
import sqlite3
import time

import bpy
from bpy.app.handlers import persistent

from ...core.errors import GeoblenderError
from ...core.i18n import tr
from ...core.timeutil import format_utc
from . import project_session

if TYPE_CHECKING:
    from ...core.appearance.model import Appearance

LOGGER = logging.getLogger("geoblender.bl.scene")
DELAY_S = 0.5
"""Lo que espera la escritura del aspecto desde el último cambio (plan 019, A2)."""

__all__ = ["APPLIERS", "DELAY_S", "MATERIAL_PREFIX", "apply", "discard", "flush", "mirror", "offered", "on_changed",
           "on_load_pre", "on_save_pre", "read", "reapply", "reconcile", "register", "reset", "reset_message",
           "restore", "set_clock", "sweep", "unregister"]

MATERIAL_PREFIX = "Geoblender look · "
"""El comienzo del nombre del material de visualización de un objeto (después, el nombre del objeto)."""

def _domain() -> Any:
    """Los módulos del dominio del aspecto, al usarlos (registrar no los importa: RNF-001-03)."""
    from ...core.appearance import catalog, model, store

    class _D:
        pass

    d = _D()
    d.catalog, d.model, d.store = catalog, model, store  # type: ignore[attr-defined]
    return d


_Applier = Callable[[Any, str], None]
_mirroring = False  # mientras se escribe el espejo, su ``update`` no aplica


def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    return (int(value[1:3], 16) / 255.0, int(value[3:5], 16) / 255.0, int(value[5:7], 16) / 255.0)


def _rgb_to_hex(rgb: Iterable[float]) -> str:
    return "#" + "".join(f"{min(255, max(0, int(c * 255 + 0.5))):02X}" for c in rgb)


def _visual_material(obj: Any) -> Any | None:
    """El material de visualización del objeto (el que lleva su nombre), creado y puesto si hace falta; ``None`` si el
    objeto no es una malla."""
    if obj.type != "MESH" or obj.data is None:
        return None
    name = MATERIAL_PREFIX + obj.name
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)
    if all(slot.material is not material for slot in obj.material_slots):
        obj.data.materials.append(material)
    return material


def _set_color(obj: Any, value: str) -> None:
    red, green, blue = _hex_to_rgb(value)
    obj.color = (red, green, blue, obj.color[3])
    material = bpy.data.materials.get(MATERIAL_PREFIX + obj.name)
    if material is not None:
        material.diffuse_color = (red, green, blue, material.diffuse_color[3])


def _set_transparency(obj: Any, value: str) -> None:
    alpha = 1.0 - int(value) / 100.0
    obj.color = (obj.color[0], obj.color[1], obj.color[2], alpha)
    material = bpy.data.materials.get(MATERIAL_PREFIX + obj.name)
    if material is None and alpha < 1.0:
        material = _visual_material(obj)
    if material is not None:
        material.diffuse_color = (obj.color[0], obj.color[1], obj.color[2], alpha)
        material.blend_method = "BLEND" if alpha < 1.0 else "HASHED"  # en 5.2, OPAQUE se guarda como HASHED (el predefinido)
        material.show_transparent_back = False


def _set_visible(obj: Any, value: str) -> None:
    try:
        obj.hide_set(value != "1")
    except RuntimeError:  # el objeto no está en la capa de vista actual: no hay qué ocultar
        pass


def _set_labels(obj: Any, value: str) -> None:
    obj.show_name = value == "1"


def _set_wire(obj: Any, value: str) -> None:
    obj.show_wire = value == "1"


def _redraw_views(_obj: Any, _value: str) -> None:
    """El grosor de línea y el tamaño de punto los lee ``bl.draw.look`` en cada dibujo del espejo
    ``Object.geoblender.look``: aquí solo se pide redibujar las Vistas 3D (T07b)."""
    manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(manager, "windows", ()):
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _set_label(obj: Any, value: str) -> None:
    """El rótulo es lo que ve el Outliner: el nombre del objeto lo genera ``scene.views.view_name`` con él (T10; P-2). No
    cambia el nombre estable del dato ni su identidad."""
    from . import views

    project = project_session.current()
    if project is None or project.closed or not obj.geoblender.dataset_uid or obj.geoblender.project_uid != project.uid:
        return
    try:
        views.relabel(project, obj, value)
    except (GeoblenderError, sqlite3.Error, OSError):
        LOGGER.warning("No se pudo poner el rótulo a «%s»", obj.name, exc_info=True)


_COMMON: dict[str, _Applier] = {"label": _set_label, "visible": _set_visible}
_SURFACE: dict[str, _Applier] = {**_COMMON, "color": _set_color, "transparency": _set_transparency, "wire": _set_wire}
_LINES: dict[str, _Applier] = {**_COMMON, "color": _set_color}
_STROKED: dict[str, _Applier] = {**_LINES, "line_width": _redraw_views}
APPLIERS: dict[str, dict[str, _Applier]] = {
    "PROJECT_ANCHOR": dict(_COMMON),
    "DTM": dict(_SURFACE), "TIN": dict(_SURFACE), "DESIGN": dict(_SURFACE), "DESIGN_ENTITY": dict(_SURFACE),
    "DRILLHOLES": {**_COMMON, "color": _set_color, "transparency": _set_transparency, "labels": _set_labels},
    "VOLUME_DIFFERENCE": {**_COMMON, "transparency": _set_transparency, "wire": _set_wire},
    "COMPLIANCE_GRID": {**_COMMON, "transparency": _set_transparency, "wire": _set_wire},
    "POINTS": {**_LINES, "labels": _set_labels, "point_size": _redraw_views},
    "BREAKLINES": dict(_STROKED), "CONTOURS": dict(_STROKED), "BOUNDARY": dict(_STROKED),
    "CLIENT_INTENTION": dict(_STROKED), "CONSTRAINT": dict(_STROKED),
}
"""Por tipo (``Object.geoblender.kind``), lo que se sabe aplicar de cada propiedad."""


def offered(kind: str) -> tuple[str, ...]:
    """Las propiedades que se ofrecen del tipo ``kind``: las del catálogo que además tienen aplicador (A1; UI-13)."""
    have = APPLIERS.get(kind, {})
    return tuple(prop for prop in _domain().catalog.allowed(kind) if prop in have)


def apply(obj: Any, look: Appearance | Mapping[str, object]) -> None:
    """Aplica ``look`` (un :class:`Appearance` o ``{propiedad: valor}``) a la vista de ``obj``. Ignora lo que el tipo
    no ofrece. Solo toca la vista: ni la geometría ni la procedencia ni el proyecto."""
    kind = obj.geoblender.kind
    appliers = APPLIERS.get(kind, {})
    values = dict(look) if isinstance(look, Mapping) else look.as_dict()
    for prop in _domain().catalog.allowed(kind):
        fn = appliers.get(prop)
        if fn is not None and prop in values:
            fn(obj, _domain().model.validate(kind, prop, values[prop], name=obj.name))


def read(obj: Any) -> Appearance:
    """El espejo ``Object.geoblender.look`` de ``obj`` como :class:`Appearance` canónico, solo con lo que se ofrece."""
    look = obj.geoblender.look
    kind = obj.geoblender.kind
    raw: dict[str, object] = {
        "label": look.label, "color": _rgb_to_hex(look.color), "transparency": look.transparency,
        "visible": look.visible, "line_width": look.line_width, "point_size": look.point_size,
        "labels": look.labels, "wire": look.wire,
    }
    return _domain().model.Appearance(kind, tuple((prop, _domain().model.validate(kind, prop, raw[prop], name=obj.name))
                                  for prop in offered(kind) if prop != "label" or look.label.strip()))


def mirror(obj: Any, look: Appearance) -> None:
    """Escribe ``look`` en el espejo de ``obj`` **sin** aplicarlo (para ponerlo al día con la tabla)."""
    global _mirroring
    target = obj.geoblender.look
    _mirroring = True
    try:
        for prop, value in look:
            if prop == "color":
                target.color = _hex_to_rgb(value)
            elif prop == "label":
                target.label = value
            elif prop == "transparency":
                target.transparency = int(value)
            elif prop in ("visible", "labels", "wire"):
                setattr(target, prop, value == "1")
            elif prop in ("line_width", "point_size"):
                setattr(target, prop, float(value))
    finally:
        _mirroring = False


def on_changed(look_group: Any, prop: str | None = None) -> None:
    """Lo que hace el ``update`` del espejo: aplica al objeto **solo la propiedad cambiada** (``prop``; sin ella, todo lo
    que el tipo ofrece) y la anota para escribirla en el proyecto tras :data:`DELAY_S` (:func:`mark`). Aplicar solo lo
    cambiado evita pisar con los valores por defecto del espejo lo que el objeto ya tenía (T08)."""
    obj = look_group.id_data
    if _mirroring or not isinstance(obj, bpy.types.Object) or obj.geoblender.kind == "NONE":
        return
    values = read(obj).as_dict()
    if prop is None:
        apply(obj, values)
        return
    if prop in values:
        apply(obj, {prop: values[prop]})
    mark(obj, prop)


def reapply(objects: Iterable[Any]) -> int:
    """Aplica el espejo de cada objeto de Geoblender de ``objects``; devuelve cuántos. (T08 lo cablea tras cargar y refrescar.)"""
    count = 0
    for obj in objects:
        if obj.geoblender.kind != "NONE":
            apply(obj, read(obj))
            count += 1
    return count


# Escritura diferida (spec 019, T08; plan 019 A2) -----------------------------------------------------------------

_pending: dict[str, set[str]] = {}  # nombre del objeto → propiedades cambiadas y aún sin escribir
_due: float | None = None
_clock: Any = time.monotonic
_warned: set[str] = set()


def set_clock(clock: Any) -> None:
    """Pone el reloj (segundos; ``None``, el de siempre): lo usan las pruebas para inyectar el «ahora»."""
    global _clock
    _clock = time.monotonic if clock is None else clock


def _stop_timer() -> None:
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)


def discard() -> None:
    """Olvida lo pendiente (sin escribir) y retira el temporizador."""
    global _due
    _pending.clear()
    _due = None
    _warned.clear()
    _stop_timer()


def mark(obj: Any, prop: str) -> None:
    """Anota que ``prop`` de ``obj`` cambió y reinicia la espera: arrastrar un valor no escribe cien veces. Un objeto sin dato
    del proyecto (o sin proyecto abierto) solo cambia su espejo."""
    global _due
    if project_session.current() is None or not obj.geoblender.dataset_uid:
        return
    _pending.setdefault(obj.name, set()).add(prop)
    _due = _clock() + DELAY_S
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=DELAY_S, persistent=True)


def _tick() -> float | None:
    """El temporizador: escribe lo pendiente cuando se cumple la espera; si no, vuelve a mirar cuando se cumpla."""
    if not _pending:
        return None
    wait = (_due or 0.0) - _clock()
    if wait > 0:
        return max(wait, 0.05)
    sweep(_clock())
    return None


def sweep(now: float) -> int:
    """El barrido: si hay algo pendiente y desde el último cambio pasó :data:`DELAY_S` (``now`` es el «ahora» inyectado),
    lo escribe (:func:`flush`) y devuelve cuántas filas; si no, 0."""
    if not _pending or (_due is not None and now < _due):
        return 0
    return flush()


def _blocked(project: Any) -> str | None:
    if not project.writable:
        return tr("Appearance saved only in this file: the project is read-only")
    if project.schema_version < 4:
        return tr("Appearance saved only in this file: the project is of schema {schema}, without appearance",
                  schema=project.schema_version)
    return None


def _warn_once(reason: str) -> None:
    if reason not in _warned:
        _warned.add(reason)
        project_session.notify(reason)


def flush(project: Any = None) -> int:
    """Escribe en ``gb_appearance`` lo pendiente, en **una** transacción, y devuelve cuántas filas. Solo lo que alguien
    cambió (cada propiedad pendiente con el valor que tiene ahora su espejo). Sin proyecto, no escribe; en solo lectura,
    lo dice una vez y el aspecto queda solo en el espejo del fichero."""
    global _due
    items = dict(_pending)
    _pending.clear()
    _due = None
    _stop_timer()
    project = project if project is not None else project_session.current()
    if not items or project is None or project.closed:
        return 0
    reason = _blocked(project)
    if reason is not None:
        _warn_once(reason)
        return 0
    batch: list[tuple[str, str, dict[str, Any], list[str]]] = []  # (uid, tipo, valores, rótulos a borrar)
    for name, props in items.items():
        obj = bpy.data.objects.get(name)
        if obj is None or obj.geoblender.kind == "NONE" or obj.geoblender.project_uid != project.uid:
            continue
        values = read(obj).as_dict()
        wanted = {prop: values[prop] for prop in props if prop in values}
        cleared = ["label"] if "label" in props and "label" not in values else []
        if wanted or cleared:
            batch.append((obj.geoblender.dataset_uid, obj.geoblender.kind, wanted, cleared))
    if not batch:
        return 0
    written = 0
    who, now = project_session.session().user_host, format_utc(project.clock.now())
    try:
        with project.write_transaction() as conn:
            names = _names(conn, [uid for uid, *_rest in batch])
            for uid, kind, wanted, cleared in batch:
                item = names.get(uid)
                if item is None:
                    continue
                written += len(_domain().store.write(conn, item, kind, wanted, who, now))
                if cleared:
                    written += _domain().store.reset(conn, item, cleared)
    except (GeoblenderError, sqlite3.Error, OSError) as exc:
        LOGGER.warning("No se pudo guardar el aspecto en el proyecto", exc_info=True)
        project_session.notify(str(exc))
        return 0
    return written


def flush_before_close(project: Any) -> None:
    """Lo que hace ``project_session`` justo antes de cerrar el proyecto: vaciar lo pendiente (A2)."""
    if not _pending:
        return
    try:
        flush(project)
    except Exception:  # noqa: BLE001 - cerrar el proyecto no depende del aspecto
        LOGGER.exception("No se pudo escribir el aspecto pendiente al cerrar el proyecto")


def _names(conn: sqlite3.Connection, uids: Iterable[str]) -> dict[str, str]:
    """El nombre estable (``gb_dataset.name``) de cada dato ``uids``."""
    wanted = list(dict.fromkeys(uids))
    found: dict[str, str] = {}
    for start in range(0, len(wanted), 500):
        chunk = wanted[start:start + 500]
        marks = ", ".join("?" for _ in chunk)
        for uid, name in conn.execute(f"SELECT uid, name FROM gb_dataset WHERE uid IN ({marks})", chunk):
            found[str(uid)] = str(name)
    return found


# Lo guardado manda (R-5) ---------------------------------------------------------------------------------------

def _reset_mirror(obj: Any, props: Iterable[str]) -> None:
    """Deja el espejo y la vista de ``props`` en el predefinido del tipo (sin disparar el aplicador): el grosor y el tamaño,
    sin valor guardado, para que ``bl.draw`` no dibuje nada propio; el rótulo, vacío."""
    global _mirroring
    from ..draw import style

    kind = obj.geoblender.kind
    defaults = _domain().catalog.defaults_for(kind)
    look = obj.geoblender.look
    chosen = [prop for prop in props if prop in offered(kind)]
    _mirroring = True
    try:
        for prop in chosen:
            if prop in ("line_width", "point_size"):
                look.property_unset(prop)
            elif prop == "label":
                look.label = ""
                _set_label(obj, "")
            elif prop in defaults.props:
                mirror(obj, _domain().model.Appearance(kind, ((prop, defaults.get(prop) or ""),)))
    finally:
        _mirroring = False
    style.invalidate()
    apply(obj, {prop: defaults.get(prop) for prop in chosen if prop in defaults.props})


def restore(objects: Iterable[Any], project: Any = None) -> int:
    """Pone el espejo y la vista de ``objects`` como dice la tabla ``gb_appearance`` (la verdad tras un deshacer, R-5, y al
    cargar): lo guardado se pone y se aplica; una propiedad con valor en el espejo y sin fila vuelve al predefinido. Lo que
    nadie guardó no se toca. Devuelve cuántos objetos de Geoblender del proyecto miró."""
    from ..draw import style

    project = project if project is not None else project_session.current()
    if project is None or project.closed or project.schema_version < 4:
        return 0
    mine = [obj for obj in objects if obj.geoblender.kind != "NONE" and obj.geoblender.dataset_uid
            and obj.geoblender.project_uid == project.uid]
    if not mine:
        return 0
    try:
        with project.read() as conn:
            names = _names(conn, [obj.geoblender.dataset_uid for obj in mine])
            stored = _domain().store.read(conn, names.values())
    except (GeoblenderError, sqlite3.Error, OSError):
        LOGGER.warning("No se pudo leer el aspecto del proyecto", exc_info=True)
        return 0
    for obj in mine:
        kind = obj.geoblender.kind
        rows = stored.get(names.get(obj.geoblender.dataset_uid, ""), {})
        offer = offered(kind)
        look = obj.geoblender.look
        values = {prop: value for prop, value in rows.items() if prop in offer}
        if values:
            mirror(obj, _domain().model.Appearance(kind, tuple(values.items())))
            apply(obj, values)
            if "line_width" in values or "point_size" in values:
                style.note(obj)
        loose = [prop for prop in offer if prop not in values and look.is_property_set(prop)]
        if loose:
            _reset_mirror(obj, loose)
    style.invalidate()
    return len(mine)


def reconcile() -> int:
    """Tras deshacer o rehacer: lo pendiente se olvida (lo que Blender restauró ya es lo anterior) y manda la tabla."""
    global _due
    _pending.clear()
    _due = None
    _stop_timer()
    return restore(bpy.data.objects)


def reset_message(props: Iterable[str] | None, objects: list[Any]) -> str:
    """«Restablecido: <propiedad> de «<nombre>»» (RF-019-09), en el idioma de Geoblender; ``props`` ``None``: todo el aspecto;
    con varios elementos, «… de <n> elementos»."""
    chosen = list(props) if props is not None else []
    what = ", ".join(_domain().model.field_name(prop) for prop in chosen) if chosen else tr("all the appearance")
    if len(objects) == 1:
        return tr("Reset: {what} of «{name}»", what=what, name=objects[0].name)
    return tr("Reset: {what} of {count} elements", what=what, count=len(objects))


def reset(objects: Iterable[Any], props: Iterable[str] | None = None) -> list[Any]:
    """Restablece ``props`` (todas las que ofrece cada tipo si es ``None``) de ``objects``: borra sus filas de la tabla en una
    transacción y devuelve el espejo y la vista al predefinido. Lo pendiente de esas propiedades se descarta. Devuelve los
    objetos de Geoblender restablecidos. En solo lectura, solo cambia el fichero (y lo dice una vez)."""
    project = project_session.current()
    done = []
    rows: list[tuple[str, list[str]]] = []
    for obj in objects:
        kind = obj.geoblender.kind
        if kind == "NONE":
            continue
        chosen = [prop for prop in (offered(kind) if props is None else props) if prop in offered(kind)]
        pending = _pending.get(obj.name)
        if pending is not None:
            pending.difference_update(chosen)
            if not pending:
                del _pending[obj.name]
        if project is not None and obj.geoblender.dataset_uid and obj.geoblender.project_uid == project.uid:
            rows.append((obj.geoblender.dataset_uid, chosen))
        _reset_mirror(obj, chosen)
        done.append(obj)
    if not _pending:
        _stop_timer()
    if project is not None and rows and not project.closed:
        reason = _blocked(project)
        if reason is not None:
            _warn_once(reason)
        else:
            with project.write_transaction() as conn:
                names = _names(conn, [uid for uid, _chosen in rows])
                for uid, chosen in rows:
                    if uid in names:
                        _domain().store.reset(conn, names[uid], chosen)
    return done


@persistent
def on_save_pre(*_args: Any) -> None:
    """Al guardar el ``.blend`` se vacía lo pendiente (A2)."""
    try:
        flush()
    except Exception:  # noqa: BLE001 - guardar el fichero no depende del aspecto
        LOGGER.exception("No se pudo escribir el aspecto pendiente al guardar")


@persistent
def on_load_pre(*_args: Any) -> None:
    """Antes de abrir otro ``.blend`` se vacía lo pendiente (A2): el objeto va a desaparecer."""
    on_save_pre()


def _handler_lists() -> tuple[tuple[Any, Any], ...]:
    return ((bpy.app.handlers.save_pre, on_save_pre), (bpy.app.handlers.load_pre, on_load_pre))


def register() -> None:
    """Añade los manejadores de guardar y de abrir (sin repetirlos)."""
    for handlers, function in _handler_lists():
        if function not in handlers:
            handlers.append(function)


def unregister() -> None:
    """Quita los manejadores y el temporizador y olvida lo pendiente."""
    for handlers, function in _handler_lists():
        while function in handlers:
            handlers.remove(function)
    discard()
