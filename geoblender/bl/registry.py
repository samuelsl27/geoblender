# SPDX-License-Identifier: GPL-3.0-or-later
"""Registro de clases de Blender, tolerante e idempotente (plan 001 §5.3).

Cada subpaquete de ``bl`` reúne sus clases en una tupla ``classes`` y las registra con
:func:`register_classes`; :func:`unregister_classes` las desregistra en orden inverso.
Registrar una clase ya registrada o desregistrar una que no lo está no hace nada, y si
una clase falla al registrarse se deshace lo registrado antes de propagar el error: así
desactivar Geoblender deja Blender como estaba (principio 8).

:class:`PropertyTranslator` (spec 003, T33 y T37; RF-003-20, RF-003-21; II §2.2) pone en el
idioma de Geoblender el nombre, la descripción y los elementos de un enumerado fijo de las
propiedades de ``bpy.props`` de una clase **antes de registrarla**, con
``translation_context = "Geoblender"`` (así Blender no las vuelve a traducir), y al final
devuelve a cada clase sus anotaciones originales. Solo traduce los textos que tienen
traducción (``core.i18n``). Lo usan ``bl/props`` (al registrar: los grupos de propiedades,
en el idioma de la última sesión) y ``bl/ui`` (los operadores, también al cambiar de
idioma).
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from typing import Any

import bpy

from ..core.i18n import language, translate, untranslated
from . import reporting

TRANSLATION_CONTEXT = "Geoblender"
_MISSING = object()  # la clase no tenía la anotación: venía de una clase madre


def _is_registered(cls: type) -> bool:
    return bool(getattr(cls, "is_registered", False))


def register_classes(classes: Sequence[type]) -> None:
    """Registra ``classes`` en orden (los subpaneles, después de sus padres)."""
    done: list[type] = []
    try:
        for cls in classes:
            if _is_registered(cls):
                continue
            reporting.instrument(cls)  # spec 019, T22: sus informes llegan a la cola de avisos
            bpy.utils.register_class(cls)
            done.append(cls)
    except BaseException:
        unregister_classes(done)
        raise


def unregister_classes(classes: Sequence[type]) -> None:
    """Desregistra ``classes`` en orden inverso y omite las que no están registradas."""
    for cls in reversed(classes):
        if _is_registered(cls):
            bpy.utils.unregister_class(cls)


# Propiedades en el idioma de Geoblender ---------------------------------------------------


def _deferred(value: object) -> bool:
    """Si ``value`` es una propiedad de ``bpy.props`` sin crear (una anotación)."""
    return hasattr(value, "function") and isinstance(getattr(value, "keywords", None), dict)


def annotations(cls: type) -> dict[str, Any]:
    """Las propiedades anotadas en ``cls`` y en sus clases madre que no son de Blender
    (los *mixin*), las de la propia clase primero. Las anotaciones de un módulo con
    ``from __future__ import annotations`` son texto: se evalúan como al registrar."""
    found: dict[str, Any] = {}
    for klass in cls.__mro__:
        if klass.__module__.startswith(("bpy", "_bpy")) or klass is object:
            continue
        try:
            values = inspect.get_annotations(klass, eval_str=True)
        except Exception:  # una anotación que no se puede evaluar: esa clase, no
            continue
        for attr, value in values.items():
            if attr not in found and _deferred(value):
                found[attr] = value
    return found


def text(msgid: object) -> object:
    """``msgid`` en el idioma activo si tiene traducción; si no, igual."""
    if not isinstance(msgid, str) or not msgid or untranslated([msgid]):
        return msgid
    return translate(language(), msgid)


def _items(items: object) -> object:
    """Los elementos de un enumerado fijo con sus nombres y descripciones traducidos."""
    if not isinstance(items, (list, tuple)):
        return items  # enumerado dinámico: lo resuelve su función
    result: list[object] = []
    for item in items:
        if isinstance(item, tuple) and len(item) >= 3:
            result.append((item[0], text(item[1]), text(item[2]), *item[3:]))
        else:
            result.append(item)
    return result


class PropertyTranslator:
    """Traduce las propiedades de clases de Blender y recuerda las originales."""

    def __init__(self) -> None:
        # Las anotaciones propias de cada clase antes de traducirlas (tal como estaban,
        # para devolverlas) y evaluadas (para traducir de ellas cada vez).
        self.saved: dict[type, dict[str, object]] = {}
        self.sources: dict[type, dict[str, Any]] = {}

    def changes(self, cls: type) -> dict[str, tuple[Any, Any]]:
        """Las propiedades de ``cls`` que cambian al traducirlas al idioma activo:
        atributo → (propiedad nueva, original); vacío si ya están en ese idioma."""
        changed: dict[str, tuple[Any, Any]] = {}
        sources = self.sources.get(cls, {})
        for attr, value in annotations(cls).items():
            source = sources.get(attr, value)
            wanted = dict(source.keywords)
            for key in ("name", "description"):
                if key in wanted:
                    wanted[key] = text(wanted[key])
            if "items" in wanted:
                wanted["items"] = _items(wanted["items"])
            wanted["translation_context"] = TRANSLATION_CONTEXT
            if dict(value.keywords) != wanted:
                changed[attr] = (source.function(**wanted), source)
        return changed

    def apply(self, cls: type, changes: Mapping[str, tuple[Any, Any]]) -> None:
        """Pone en ``cls`` (sin registrar) las propiedades de :meth:`changes`."""
        if not changes:
            return
        own = cls.__dict__.get("__annotations__")
        if own is None:
            own = {}
            cls.__annotations__ = own
        saved = self.saved.setdefault(cls, {})
        sources = self.sources.setdefault(cls, {})
        for attr, (prop, source) in changes.items():
            if attr not in saved:
                saved[attr] = own.get(attr, _MISSING)
                sources[attr] = source
            own[attr] = prop

    def localize(self, cls: type) -> bool:
        """Traduce las propiedades de ``cls`` (sin registrar); devuelve si cambió algo."""
        changes = self.changes(cls)
        self.apply(cls, changes)
        return bool(changes)

    def restore(self) -> None:
        """Devuelve a cada clase sus anotaciones originales (con las clases sin
        registrar)."""
        for cls, saved in self.saved.items():
            own = cls.__dict__.get("__annotations__", {})
            for attr, value in saved.items():
                if value is _MISSING:
                    own.pop(attr, None)
                else:
                    own[attr] = value
        self.saved.clear()
        self.sources.clear()
