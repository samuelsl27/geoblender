# SPDX-License-Identifier: GPL-3.0-or-later
"""Engancha los informes de las órdenes de Geoblender a la cola de avisos (spec 019, T22; RF-019-18; plan 019 A5).

:func:`instrument` se llama al registrar cada clase de orden (``bl.registry.register_classes``): sustituye la
lectura de ``self.report`` por una función que escribe como siempre (Blender lo registra en el Info) **y** avisa a
quien se apuntó con :func:`set_sink` (``bl.ui.notices``), y envuelve ``invoke``, ``execute`` y ``modal`` para avisar
de que la orden se canceló. No cambia ni una de las llamadas a ``self.report``; sin quien escuche, no hace nada.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

import bpy

__all__ = ["Sink", "instrument", "set_sink"]

MARK = "_gb_reporting"


class Sink:
    """Quien recibe lo que informan y cancelan las órdenes: ``report(tipos, texto)``, ``generation()`` (un contador
    que sube con cada aviso nuevo) y ``cancelled(marca)`` (la orden devolvió ``CANCELLED``; ``marca`` es el
    contador al empezar)."""

    def __init__(self, report: Callable[[set[str], str], None], generation: Callable[[], int],
                 cancelled: Callable[[int], None]) -> None:
        self.report = report
        self.generation = generation
        self.cancelled = cancelled


_SINK: Sink | None = None


def set_sink(sink: Sink | None) -> None:
    """Pone (o quita, con ``None``) a quien se avisa."""
    global _SINK
    _SINK = sink


def _wrap_getattribute(original: Callable[[Any, str], Any]) -> Callable[[Any, str], Any]:
    """``report`` es una función de RNA que Blender busca antes que un atributo de la clase: no se puede
    sustituir en ella. Lo que sí se puede es interceptar la lectura de ``self.report`` y devolver una función que
    avisa y llama a la de Blender (también desde los métodos auxiliares y los *mixin* de la orden)."""

    def __getattribute__(self: Any, name: str) -> Any:
        value = original(self, name)
        if name != "report" or _SINK is None:
            return value

        def report(type: set[str], message: str) -> Any:  # noqa: A002 - la firma de Blender
            sink = _SINK
            if sink is not None:
                try:
                    sink.report(set(type), str(message))
                except Exception:  # noqa: BLE001 - un fallo del aviso no impide el informe
                    pass
            return value(type, message)

        return report

    setattr(__getattribute__, MARK, True)
    return __getattribute__


def _finish(sink: Sink | None, result: Any, mark: int) -> Any:
    if sink is not None and isinstance(result, (set, frozenset)) and "CANCELLED" in result:
        try:
            sink.cancelled(mark)
        except Exception:  # noqa: BLE001
            pass
    return result


def _mark() -> int:
    return _SINK.generation() if _SINK is not None else 0


# Blender comprueba cuántos argumentos tienen estas funciones: cada una, con los suyos.
def _wrap_execute(original: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(original)
    def execute(self: Any, context: Any) -> Any:
        mark = _mark()
        return _finish(_SINK, original(self, context), mark)

    setattr(execute, MARK, True)
    return execute


def _wrap_event(original: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(original)
    def invoke(self: Any, context: Any, event: Any) -> Any:
        mark = _mark()
        return _finish(_SINK, original(self, context, event), mark)

    setattr(invoke, MARK, True)
    return invoke


WRAPPERS = {"invoke": _wrap_event, "execute": _wrap_execute, "modal": _wrap_event}


def instrument(cls: type) -> bool:
    """Prepara la clase de orden ``cls`` (sin registrar) de Geoblender; devuelve si la modificó. Una clase que no
    es una orden, que no es de Geoblender o que ya está preparada se deja igual."""
    if not (isinstance(cls, type) and issubclass(cls, bpy.types.Operator)):
        return False
    if not str(getattr(cls, "bl_idname", "")).startswith("geoblender."):
        return False
    changed = False
    reader = cls.__getattribute__
    if not getattr(reader, MARK, False):
        cls.__getattribute__ = _wrap_getattribute(reader)  # type: ignore[method-assign]
        changed = True
    for name, wrap in WRAPPERS.items():
        function = getattr(cls, name, None)
        if function is not None and not getattr(function, MARK, False):
            setattr(cls, name, wrap(function))
            changed = True
    return changed
