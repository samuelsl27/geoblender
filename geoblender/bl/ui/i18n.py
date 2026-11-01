# SPDX-License-Identifier: GPL-3.0-or-later
"""Idioma de Geoblender en Blender (spec 003; RF-003-20, RF-003-21; RNF-003-05; plan 003
§5.4, 11, DT4; ADR-0012 §4; II §2).

El idioma de Geoblender (español por defecto, o inglés) es **propio**: lo fija la
preferencia ``GeoblenderPreferences.ui.language``, no cambia el de Blender y no usa
``bpy.app.translations``. Todo texto de Geoblender se dibuja con ``core.i18n.tr`` (o, los
del catálogo de comandos, ``commands.text``) y ``translate=False``, y las clases llevan
``bl_translation_context = "Geoblender"``: así Blender no los vuelve a traducir (con
Blender en español, «Project» del contexto por defecto saldría «Proyectar»).

- :func:`install`: instala los textos del catálogo de comandos en ``core.i18n`` y el idioma
  de las preferencias (al registrar la interfaz, antes que nada).
- :func:`apply`: cambia el idioma **sin reiniciar Blender**: lo fija en ``core.i18n``,
  vuelve a registrar las clases de la interfaz con sus ``bl_label`` y ``bl_description``
  nuevos (``registry.relabel``; cambiar ``bl_label`` sin registrar otra vez no cambia el
  nombre en F3 ni en los atajos, que sobreviven al nuevo registro con el nombre nuevo), la
  pestaña «Proyecto» de la barra lateral (con sus paneles de la spec 010), y pide
  redibujar. Devuelve lo que tardó, en ms (RNF-003-05: ≤ 500 ms). Lo que se dibuja con
  ``tr`` cambia en el siguiente dibujo; las descripciones de las propiedades, al reiniciar
  Blender (II §2.2).
- :func:`schedule`: lo que hace elegir el idioma en las preferencias (o en Ayuda ▸ Idioma
  de Geoblender): deja el idioma pendiente y lo aplica un temporizador de 0 s
  (:func:`apply_pending`), fuera del dibujo de un menú o de las preferencias. En
  ``blender -b`` los temporizadores no corren: las pruebas llaman a :func:`apply_pending`.
- :func:`cancel` retira el temporizador y lo pendiente (al desregistrar).
"""

from __future__ import annotations

import time
from typing import Any

import bpy

from ...core import i18n
from ..props.ui import LANGUAGES, remember_language
from . import commands, constraint_panels, core_panel, registry, res_panels, view_panels


class _State:
    def __init__(self) -> None:
        self.pending: str | None = None


_STATE = _State()


def preferred_language() -> str:
    """El idioma de las preferencias (``"es"`` o ``"en"``; español si no se pueden
    leer)."""
    return LANGUAGES.get(str(commands.preference("language", "ES")), "es")


def install() -> str:
    """Instala los textos del catálogo de comandos y fija el idioma de las preferencias;
    devuelve ``"es"`` o ``"en"``."""
    i18n.install(commands.catalog())
    language = preferred_language()
    i18n.set_language(language)
    remember_language(language)
    return language


def _relabel_core_panel() -> None:
    """La pestaña y el título de «Proyecto» (spec 002) y de los paneles que van en ella (spec
    010: Elemento activo e Inventario; spec 011: Cubicaciones; spec 012: Restricción; las listas y
    las ventanas sin pestaña, no), registrados otra vez si cambian (si no, tras cambiar el idioma
    quedarían en otra pestaña)."""
    panels = [cls for cls in (*core_panel.classes, *view_panels.classes, *res_panels.classes,
                              *constraint_panels.classes)
              if issubclass(cls, bpy.types.Panel) and hasattr(cls, "bl_category")]
    before = {cls: (cls.bl_category, cls.bl_label) for cls in panels}
    core_panel.localize()
    view_panels.localize()
    res_panels.localize()
    constraint_panels.localize()
    for cls in panels:
        if (cls.bl_category, cls.bl_label) == before[cls] or not getattr(cls, "is_registered",
                                                                         False):
            continue
        bpy.utils.unregister_class(cls)
        bpy.utils.register_class(cls)


def _redraw() -> None:
    manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(manager, "windows", ()):
        for area in window.screen.areas:
            area.tag_redraw()


def apply(language: str) -> float:
    """Cambia el idioma de Geoblender a ``language`` (``"es"`` o ``"en"``) sin reiniciar
    y devuelve lo que tardó, en ms."""
    start = time.perf_counter()
    i18n.set_language(language)
    remember_language(language)  # los grupos de propiedades, al reiniciar
    registry.relabel()
    _relabel_core_panel()
    _redraw()
    return (time.perf_counter() - start) * 1000.0


def pending() -> str | None:
    """El idioma elegido que aún no se ha aplicado."""
    return _STATE.pending


def apply_pending() -> None:
    """Temporizador: aplica el idioma pendiente (si hay)."""
    language, _STATE.pending = _STATE.pending, None
    if language is not None and language != i18n.language():
        apply(language)
    elif language is not None:
        _redraw()


def schedule(language: str) -> None:
    """Deja ``language`` pendiente y lo aplica en el siguiente ciclo de eventos."""
    _STATE.pending = language
    if not bpy.app.timers.is_registered(apply_pending):
        bpy.app.timers.register(apply_pending, first_interval=0.0)


def on_preference_changed(_group: Any = None, _context: Any = None) -> None:
    """``update`` de la preferencia de idioma: aplica la elegida en el siguiente ciclo."""
    schedule(preferred_language())


def cancel() -> None:
    """Retira el temporizador y olvida lo pendiente."""
    if bpy.app.timers.is_registered(apply_pending):
        bpy.app.timers.unregister(apply_pending)
    _STATE.pending = None
