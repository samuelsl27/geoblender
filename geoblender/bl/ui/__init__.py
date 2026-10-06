# SPDX-License-Identifier: GPL-3.0-or-later
"""Interfaz: conmutador, barra superior, menús, accesos rápidos, iconos, atajos e
idioma (spec 003). Se registra el último (plan 001 §5.3, contrato 2; plan 003 DT15).

Orden de :func:`register` (CW §5; plan 003 §5.4, 1), con ``bl/props`` y ``bl/ops`` ya
registrados: idioma (el catálogo de comandos en ``core.i18n`` y el idioma de las
preferencias) → clases propias de la interfaz (los menús y la pestaña «Proyecto» de la
spec 002) → catálogo (``registry``: menús generados por ``menus``, provisionales y
textos) → sustitución de ``draw_left`` de la barra superior (``topbar``) → fila de
acceso rápido de cada Vista 3D (``quick_access``: ``prepend`` a su fila 2) → vistas
(``views``: el manejador ``load_post`` que olvida su estado de sesión) → conmutador
(``switcher``: su manejador ``load_post``; al desregistrar, devuelve cada ventana en modo
Geoblender a su espacio de Blender y retira su temporizador) → atajos del catálogo en el
*keyconfig* de complementos (``keymap``). Cada paso
anota cómo deshacerse en una pila, y :func:`unregister` la recorre al revés: deshace solo
lo hecho, también si el registro falló a medias. Las dos son idempotentes.
"""

from __future__ import annotations

from collections.abc import Callable

from ...core import i18n
from ..props.ui import LANGUAGES
from ..registry import register_classes, unregister_classes
from . import (
    commands,
    core_menus,
    core_panel,
    keymap,
    menus,
    quick_access,
    registry,
    switcher,
    topbar,
    views,
)

# Clases de los módulos de este subpaquete, en orden de registro (plan 001 §5.3,
# contrato 2): los menús y la pestaña «Proyecto» de core (spec 002) y los paneles reales de
# la interfaz (spec 003).
classes: tuple[type, ...] = (*core_menus.classes, *core_panel.classes, *quick_access.classes)

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


def _register_catalog() -> None:
    registry.register(menus.build())


def _install_topbar() -> None:
    topbar.install()


def register() -> None:
    """Registra la interfaz en el orden de CW §5; si ya lo está, no hace nada. Si algo
    falla, deshace lo hecho antes de propagar el error."""
    if _UNDO:
        return
    steps: tuple[tuple[Callable[[], object], Callable[[], None]], ...] = (
        (install_language, lambda: None),
        (_register_classes, lambda: unregister_classes(classes)),
        (_register_catalog, registry.unregister),
        (_install_topbar, topbar.restore),
        (quick_access.install, quick_access.uninstall),
        (views.register, views.unregister),
        (switcher.register, switcher.unregister),
        (keymap.register, keymap.unregister),
    )
    try:
        for do, undo in steps:
            do()
            _UNDO.append(undo)
    except BaseException:
        unregister()
        raise


def repair() -> str:
    """Ayuda ▸ Reparar la interfaz (RF-003-24; CW §5): vuelve a sustituir ``draw_left`` si
    ya no es el de Geoblender (lo pisó otro complemento o una recarga; nunca envuelve dos
    veces), vuelve a poner los atajos del catálogo y recalcula la disponibilidad.
    Idempotente. Devuelve el modo de la barra (``patched`` o ``compat``)."""
    if not _UNDO:
        return ""
    mode = topbar.install()
    quick_access.install()
    keymap.unregister()
    keymap.register()
    commands.refresh()
    return mode


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
