# SPDX-License-Identifier: GPL-3.0-or-later
"""Registro de la interfaz desde el catálogo (spec 003; RF-003-06, RF-003-07,
RF-003-21, RF-003-23; plan 003 §5.4, 1, DT15).

Cuando llega ``bl/ui`` (el último subpaquete), ``bl/props`` y ``bl/ops`` ya han
registrado las propiedades y los operadores reales. :func:`register`:

1. registra las clases generadas del catálogo que aún no tienen clase (los menús de
   ``bl/ui/menus.py``);
2. genera un **provisional** (``bl/ui/provisional.py``) para cada ``bl_idname`` y cada
   menú o panel del catálogo que sigue sin clase registrada: nunca para uno que ya tiene
   la suya (un operador real de ``bl/ops`` no tiene provisional);
3. pone a cada clase del catálogo (también a las reales) su ``bl_label`` y su
   ``bl_description`` en el idioma activo de Geoblender, con
   ``bl_translation_context = "Geoblender"``, y vuelve a registrar las que cambian
   (:func:`relabel`; cambiar ``bl_label`` sin volver a registrar no cambia el nombre,
   plan 003 §5.4, 11);
4. calcula la disponibilidad de cada comando (``commands.refresh``).

Al poner los textos, también traduce las **propiedades** de los operadores del catálogo
(su nombre, su descripción y los nombres y descripciones de los elementos de un enumerado
fijo: los del panel F9, las ventanas de propiedades y el mapa de teclado), con
``translation_context = "Geoblender"`` para que Blender no las vuelva a traducir. Solo las
que tienen traducción (``core.i18n``); las demás se quedan como están. Así cambian también
sin reiniciar (spec 003, T33; II §2.2 pedía «al reiniciar»).

:func:`unregister` desregistra en orden inverso lo que registró y devuelve a las clases
reales sus textos originales (los de su código: el ``msgid`` inglés del catálogo,
contrato 1 del plan). Si el registro falla a medias, deshace lo hecho antes de propagar el
error.
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import bpy

from ...core.i18n import untranslated
from . import commands, provisional
from .commands import TRANSLATION_CONTEXT, catalog, is_provisional, registered_class

_MISSING = object()  # el atributo no estaba en la clase


@dataclass
class _State:
    own: list[type] = field(default_factory=list)  # registradas aquí, en orden
    originals: dict[type, dict[str, object]] = field(default_factory=dict)
    # Las anotaciones propias de cada clase antes de traducir sus propiedades
    # (_MISSING: la clase no la tenía; venía de una clase madre).
    annotations: dict[type, dict[str, object]] = field(default_factory=dict)
    # Las mismas, evaluadas: de ellas se traduce cada vez.
    sources: dict[type, dict[str, Any]] = field(default_factory=dict)


_STATE = _State()


def own_classes() -> tuple[type, ...]:
    """Las clases que registró la interfaz (generadas y provisionales), en orden."""
    return tuple(_STATE.own)


def provisional_classes() -> tuple[type, ...]:
    """Las clases provisionales registradas, en orden."""
    return tuple(cls for cls in _STATE.own if is_provisional(cls))


def _register(cls: type) -> None:
    bpy.utils.register_class(cls)
    _STATE.own.append(cls)


def register(generated: Sequence[type] = ()) -> None:
    """Registra las clases generadas que faltan, los provisionales de lo que sigue sin
    clase y los textos en el idioma activo; si algo falla, lo deshace y propaga."""
    cat = catalog()
    try:
        for cls in generated:
            if registered_class(cls.bl_idname) is None:
                _register(cls)
        for idname in sorted(cat.operator_idnames()):
            if registered_class(idname) is None:
                _register(provisional.operator_class(cat, idname))
        for name in sorted(cat.class_names()):
            if registered_class(name) is None:
                cmd = cat.commands[name]
                factory = provisional.panel_class if cmd.kind == "panel" else provisional.menu_class
                _register(factory(cat, cmd))
        relabel()
        commands.refresh()
    except BaseException:
        unregister()
        raise


def relabel() -> float:
    """Pone a cada clase registrada del catálogo su ``bl_label`` y su
    ``bl_description`` en el idioma activo y vuelve a registrar las que cambian; devuelve
    lo que tardó, en ms (RF-003-21; RNF-003-05). Los elementos del mapa de teclas
    sobreviven al nuevo registro con el nombre nuevo: al terminar se actualizan los mapas
    (``keyconfigs.update``), para que sus propiedades apunten ya a los operadores nuevos
    (sin interfaz Blender no lo hace solo, y leerlas antes lo cerraba)."""
    start = time.perf_counter()
    cat = catalog()
    changed = False
    for name in (*sorted(cat.operator_idnames()), *sorted(cat.class_names())):
        cls = registered_class(name)
        if cls is None:
            continue
        wanted: dict[str, object] = dict(provisional.labels(cat, name))
        wanted["bl_translation_context"] = TRANSLATION_CONTEXT
        current = {key: cls.__dict__.get(key, _MISSING) for key in wanted}
        properties = _localized_properties(cls) if "." in name else {}
        if current == wanted and not properties:
            continue
        if cls not in _STATE.own and cls not in _STATE.originals:
            _STATE.originals[cls] = current
        bpy.utils.unregister_class(cls)
        for key, value in wanted.items():
            setattr(cls, key, value)
        _set_annotations(cls, properties)
        bpy.utils.register_class(cls)
        changed = True
    manager = getattr(bpy.context, "window_manager", None)
    if changed and manager is not None:
        manager.keyconfigs.update()
    return (time.perf_counter() - start) * 1000.0


# Propiedades de los operadores ---------------------------------------------------------


def _deferred(value: object) -> bool:
    """Si ``value`` es una propiedad de ``bpy.props`` sin crear (una anotación)."""
    return hasattr(value, "function") and isinstance(getattr(value, "keywords", None), dict)


def _annotations(cls: type) -> dict[str, Any]:
    """Las propiedades anotadas en ``cls`` y en sus clases madre que no son de Blender
    (los *mixin*), las de la propia clase primero. Las anotaciones de un módulo con
    ``from __future__ import annotations`` son texto: se evalúan como al registrar."""
    found: dict[str, Any] = {}
    for klass in cls.__mro__:
        if klass.__module__.startswith(("bpy", "_bpy")) or klass is object:
            continue
        try:
            annotations = inspect.get_annotations(klass, eval_str=True)
        except Exception:  # una anotación que no se puede evaluar: esa clase, no
            continue
        for attr, value in annotations.items():
            if attr not in found and _deferred(value):
                found[attr] = value
    return found


def _text(msgid: object) -> object:
    """``msgid`` en el idioma activo si tiene traducción; si no, igual."""
    if not isinstance(msgid, str) or not msgid or untranslated([msgid]):
        return msgid
    return commands.text(msgid)


def _items(items: object) -> object:
    """Los elementos de un enumerado fijo con sus nombres y descripciones traducidos."""
    if not isinstance(items, (list, tuple)):
        return items  # enumerado dinámico: lo resuelve su función
    result: list[object] = []
    for item in items:
        if isinstance(item, tuple) and len(item) >= 3:
            result.append((item[0], _text(item[1]), _text(item[2]), *item[3:]))
        else:
            result.append(item)
    return result


def _localized_properties(cls: type) -> dict[str, tuple[Any, Any]]:
    """Las propiedades de ``cls`` que cambian al traducirlas al idioma activo: atributo →
    (propiedad nueva, original); vacío si ya están en ese idioma."""
    changed: dict[str, tuple[Any, Any]] = {}
    sources = _STATE.sources.get(cls, {})
    for attr, value in _annotations(cls).items():
        source = sources.get(attr, value)
        wanted = dict(source.keywords)
        for key in ("name", "description"):
            if key in wanted:
                wanted[key] = _text(wanted[key])
        if "items" in wanted:
            wanted["items"] = _items(wanted["items"])
        wanted["translation_context"] = TRANSLATION_CONTEXT
        if dict(value.keywords) != wanted:
            changed[attr] = (source.function(**wanted), source)
    return changed


def _set_annotations(cls: type, properties: Mapping[str, tuple[Any, Any]]) -> None:
    """Pone en ``cls`` las propiedades traducidas, guardando antes las originales (tal
    como estaban, para devolverlas, y evaluadas, para volver a traducirlas)."""
    if not properties:
        return
    own = cls.__dict__.get("__annotations__")
    if own is None:
        own = {}
        cls.__annotations__ = own
    saved = _STATE.annotations.setdefault(cls, {})
    sources = _STATE.sources.setdefault(cls, {})
    for attr, (prop, source) in properties.items():
        if attr not in saved:
            saved[attr] = own.get(attr, _MISSING)
            sources[attr] = source
        own[attr] = prop


def _restore_annotations() -> None:
    """Devuelve a cada clase sus anotaciones originales."""
    for cls, saved in _STATE.annotations.items():
        own = cls.__dict__.get("__annotations__", {})
        for attr, value in saved.items():
            if value is _MISSING:
                own.pop(attr, None)
            else:
                own[attr] = value
    _STATE.annotations.clear()
    _STATE.sources.clear()


def unregister() -> None:
    """Desregistra en orden inverso lo que registró :func:`register` y devuelve a las
    clases reales sus textos originales; sin registro previo, no hace nada."""
    while _STATE.own:
        cls = _STATE.own.pop()
        if getattr(cls, "is_registered", False):
            bpy.utils.unregister_class(cls)
    _restore_annotations()
    for cls, values in _STATE.originals.items():
        for key, value in values.items():
            if value is _MISSING:
                if key in cls.__dict__:
                    delattr(cls, key)
            else:
                setattr(cls, key, value)
    _STATE.originals.clear()
    commands.clear()
