# SPDX-License-Identifier: GPL-3.0-or-later
"""Interfaz: conmutador, barra superior, menús, accesos rápidos, iconos, atajos e
idioma (spec 003). Se registra el último (plan 001 §5.3, contrato 2; plan 003 DT15).

Orden de :func:`register` (CW §5; plan 003 §5.4, 1), con ``bl/props`` y ``bl/ops`` ya
registrados: idioma (el catálogo de comandos en ``core.i18n`` y el idioma de las
preferencias) → clases propias de la interfaz (los menús y la pestaña «Proyecto» de la
spec 002) → catálogo (``registry``: menús generados, provisionales y textos). Cada paso
anota cómo deshacerse en una pila, y :func:`unregister` la recorre al revés: deshace solo
lo hecho, también si el registro falló a medias. Las dos son idempotentes.
"""

from __future__ import annotations

from collections.abc import Callable

from ...core import i18n
from ..props.ui import LANGUAGES
from ..registry import register_classes, unregister_classes
from . import commands, core_menus, core_panel, registry

# Clases de los módulos de este subpaquete, en orden de registro (plan 001 §5.3,
# contrato 2): los menús y la pestaña «Proyecto» de core (spec 002).
classes: tuple[type, ...] = (*core_menus.classes, *core_panel.classes)

_UNDO: list[Callable[[], None]] = []


def install_language() -> str:
    """Instala los textos del catálogo de comandos y fija el idioma de Geoblender de las
    preferencias (español si no se pueden leer); devuelve ``"es"`` o ``"en"``."""
    i18n.install(commands.catalog())
    language = LANGUAGES.get(str(commands.preference("language", "ES")), "es")
    i18n.set_language(language)
    return language


def _register_classes() -> None:
    core_panel.localize()
    register_classes(classes)


def register() -> None:
    """Registra la interfaz en el orden de CW §5; si ya lo está, no hace nada. Si algo
    falla, deshace lo hecho antes de propagar el error."""
    if _UNDO:
        return
    steps: tuple[tuple[Callable[[], object], Callable[[], None]], ...] = (
        (install_language, lambda: None),
        (_register_classes, lambda: unregister_classes(classes)),
        (registry.register, registry.unregister),
    )
    try:
        for do, undo in steps:
            do()
            _UNDO.append(undo)
    except BaseException:
        unregister()
        raise


def unregister() -> None:
    """Deshace en orden inverso lo que hizo :func:`register`; sin registro previo, no
    hace nada. Si un paso falla, sigue con los demás y propaga el primer error."""
    first_error: BaseException | None = None
    while _UNDO:
        undo = _UNDO.pop()
        try:
            undo()
        except BaseException as exc:  # se sigue deshaciendo el resto
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise first_error
