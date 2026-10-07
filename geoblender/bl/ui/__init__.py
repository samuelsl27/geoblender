# SPDX-License-Identifier: GPL-3.0-or-later
"""Interfaz: conmutador, barra superior, menús, accesos rápidos, iconos, atajos e
idioma (spec 003). Se registra el último (plan 001 §5.3, contrato 2; plan 003 DT15).

Orden de :func:`register` (CW §5; plan 003 §5.4, 1), con ``bl/props`` y ``bl/ops`` ya
registrados: iconos propios (``icons``: una colección de ``bpy.utils.previews``) → idioma (``i18n``: el catálogo de comandos en ``core.i18n`` y el idioma de las
preferencias; al desregistrar, el cambio de idioma pendiente) → clases propias de la interfaz (los menús y la pestaña «Proyecto» de la
spec 002, la lista de trabajos de la 004) → catálogo (``registry``: menús generados por ``menus``, provisionales y
textos) → sustitución de ``draw_left`` de la barra superior (``topbar``, con el añadido a
``TOPBAR_MT_editor_menus`` que lleva «Geoblender ▾» a la búsqueda F3) → fila de
acceso rápido de cada Vista 3D (``quick_access``: ``prepend`` a su fila 2) → menú del tipo
activo (``headers``: ``append`` a la fila 1 y al clic derecho de la Vista 3D y del
Outliner) → barra de estado minera (``statusbar``: un ``append`` a la barra de estado, sus
campos y la suscripción de ``msgbus`` al cursor 3D, renovada en ``load_post``) → campo
«jobs» de la barra de estado (``jobs``, spec 004: los trabajos en segundo plano, en los dos
modos) → vistas
(``views``: el manejador ``load_post`` que olvida su estado de sesión) → disposiciones
(``layouts``: las comprobaciones de Quitar y Restaurar y su manejador ``load_post``; al
desregistrar, el temporizador de lo pendiente) → proveedores de
la Leyenda y del Filtro de datos (``context``: al desregistrar, se olvidan) → línea de
comandos (``command_line``: al desregistrar, olvida su última lista) → ayuda (``help``:
al desregistrar, olvida la última página escrita) → conmutador
(``switcher``: su manejador ``load_post``; al desregistrar, devuelve cada ventana en modo
Geoblender a su espacio de Blender y retira su temporizador) → atajos del catálogo en el
*keyconfig* de complementos (``keymap``). Cada paso
anota cómo deshacerse en una pila, y :func:`unregister` la recorre al revés: deshace solo
lo hecho, también si el registro falló a medias. Las dos son idempotentes.
"""

from __future__ import annotations

from collections.abc import Callable

from ..registry import register_classes, unregister_classes
from . import (
    command_line,
    commands,
    context,
    core_menus,
    core_panel,
    headers,
    i18n,
    icons,
    jobs,
    keymap,
    layouts,
    menus,
    quick_access,
    registry,
    statusbar,
    switcher,
    topbar,
    views,
)
from . import help as help_pages

# Clases de los módulos de este subpaquete, en orden de registro (plan 001 §5.3,
# contrato 2): los menús y la pestaña «Proyecto» de core (spec 002), los paneles reales de
# la interfaz (spec 003) y la lista de trabajos (spec 004).
classes: tuple[type, ...] = (
    *core_menus.classes,
    *core_panel.classes,
    *quick_access.classes,
    *context.classes,
    *layouts.classes,
    *jobs.classes,
)

_UNDO: list[Callable[[], None]] = []


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
        (icons.register, icons.unregister),
        (i18n.install, i18n.cancel),
        (_register_classes, lambda: unregister_classes(classes)),
        (_register_catalog, registry.unregister),
        (_install_topbar, topbar.restore),
        (quick_access.install, quick_access.uninstall),
        (headers.install, headers.uninstall),
        (statusbar.install, statusbar.uninstall),
        (jobs.install, jobs.uninstall),
        (views.register, views.unregister),
        (layouts.register, layouts.unregister),
        (lambda: None, context.clear),
        (lambda: None, command_line.clear),
        (lambda: None, help_pages.clear),
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
    """Ayuda ▸ Reparar la interfaz (RF-003-24; CW §5): vuelve a cargar los iconos (con el
    tamaño de la escala de ahora), vuelve a sustituir ``draw_left`` si ya no es el de
    Geoblender (lo pisó otro complemento o una recarga; nunca envuelve dos veces), vuelve a
    poner los añadidos (también el de F3) y los atajos del catálogo, recalcula la
    disponibilidad y pone otra vez los textos de las clases del catálogo
    (``registry.relabel``: un menú o un panel que pasa a estar disponible pierde su
    «Disponible en …», y al revés; spec 003, T45).
    Idempotente. Devuelve el modo de la barra (``patched`` o ``compat``)."""
    if not _UNDO:
        return ""
    icons.reload()
    mode = topbar.install()
    quick_access.install()
    headers.install()
    statusbar.install()
    jobs.install()
    keymap.unregister()
    keymap.register()
    commands.refresh()
    registry.relabel()
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
