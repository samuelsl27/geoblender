# SPDX-License-Identifier: GPL-3.0-or-later
"""Menús generados desde el catálogo (spec 003; RF-003-04, RF-003-06, RF-003-08; plan 003
§5.3, «Clases generadas desde el catálogo»; BS §6 y §8; AR §4; PC §3).

:func:`build` crea una clase de menú por cada menú del catálogo con contenido:

- los 13 de la barra (``GEOBLENDER_MT_ui_<tema>``): los 11 del flujo empiezan con la línea
  no pulsable «Paso n de 11 · <etapa>»; cada grupo, con un separador de línea y su rótulo
  gris; dentro del grupo, los separadores «—» de BS §8;
- sus submenús (también los de variantes, como Isométrica ▸), los concentradores de
  intercambio (Importar ▸, Exportar ▸, QGIS ▸), «Datos ▾» y «Geoblender ▾» (los 13 menús
  como submenús, en modo Blender y en el nivel E de la barra);
- los 4 menús circulares (AR §4), con sus 8 ranuras en el orden de Blender;
- los menús «<Tipo> ▾» de cada tipo de objeto y «Selección (n) ▾» (PC §3 y §4).

Cada elemento se dibuja con ``drawing.draw_command``, con la definición única de su
comando: desactivado si no está disponible y omitido con «Ocultar lo no disponible»
(nunca los 13 menús de la barra, que dibuja ``bl/ui/topbar.py``); con ella, un grupo sin
nada que dibujar no deja su separador ni su rótulo, y un separador no queda al principio,
al final o junto a otro (spec 003, T45). Un menú generado que no
está disponible (ninguno de sus elementos lo está) lleva su «Disponible en …» en la
descripción emergente (``bl.ui.registry``) y, si se abre (el «<Tipo> ▾», el clic
derecho, Mayús+Alt+B), en su primera línea, gris, tras «Paso n de 11» si la tiene; los
menús circulares no: cada ranura ya lo dice en la suya (spec 003, T39). Lo que aún no es un
comando (una propiedad del tipo en un menú contextual) se dibuja desactivado. Los menús
dinámicos (proyectos recientes, versiones) y los que no tienen contenido no se generan
aquí: tienen su clase real o su provisional.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import bpy

from ...core.catalog import Catalog, Group, MenuItem
from ...core.i18n import tr
from .commands import (
    TRANSLATION_CONTEXT,
    catalog,
    is_available,
    preference,
    text,
    unavailable_note,
)
from .drawing import draw_command, draw_note

STEPS_TOTAL = 11  # pasos del flujo (BS §5)


def step_text(cat: Catalog, menu_id: str) -> str:
    """«Paso n de 11 · <etapa>» de un menú del flujo ("" en los demás)."""
    spec = cat.menus.get(menu_id)
    if spec is None or spec.step is None:
        return ""
    return tr("Step {n} of {total} · {stage}", n=spec.step, total=STEPS_TOTAL,
              stage=text(spec.stage))


def _drawn(item: MenuItem, hide: bool) -> bool:
    """Si ``item`` (que no es un separador) dibuja algo: un comando del catálogo, salvo
    uno no disponible con «Ocultar lo no disponible» (como ``draw_command``), o una
    etiqueta de algo que aún no es un comando."""
    if item.key is not None:
        return item.key in catalog().commands and not (hide and not is_available(item.key))
    return item.placeholder is not None


def shown_items(items: tuple[MenuItem, ...], hide: bool) -> list[MenuItem]:
    """Los elementos de ``items`` que se dibujan, en su orden: sin los que no dibujan
    nada y con un separador solo entre dos que sí (nunca al principio, al final ni dos
    seguidos), para que «Ocultar lo no disponible» no deje separadores colgando (spec
    003, T45)."""
    shown: list[MenuItem] = []
    pending: MenuItem | None = None
    for item in items:
        if item.separator:
            pending = item if shown else None
        elif _drawn(item, hide):
            if pending is not None:
                shown.append(pending)
                pending = None
            shown.append(item)
    return shown


def _draw_item(layout: Any, context: Any, item: MenuItem, hide: bool) -> None:
    if item.separator:
        layout.separator()
    elif item.key is not None:
        draw_command(layout, item.key, context=context, cross=item.cross,
                     hide_unavailable=hide)
    elif item.placeholder is not None:
        row = layout.row()
        row.enabled = False
        row.label(text=text(item.placeholder[0]), translate=False)


def _draw_groups(layout: Any, context: Any, groups: tuple[Group, ...], *, lead: bool,
                 hide: bool) -> None:
    """Los grupos con algo que dibujar, cada uno tras un separador de línea (también el
    primero si ``lead``) y con su rótulo gris."""
    drawn = 0
    for group in groups:
        items = shown_items(group.items, hide)
        if not items:
            continue
        if drawn or lead:
            layout.separator(type="LINE")
        drawn += 1
        if group.label:
            row = layout.row()
            row.active = False
            row.label(text=text(group.label), translate=False)
        for item in items:
            _draw_item(layout, context, item, hide)


def _draw_unavailable(layout: Any, menu_id: str) -> bool:
    """La línea gris «Disponible en …» de un menú no disponible que se ha abierto (por el
    «<Tipo> ▾», el clic derecho, Mayús+Alt+B o ``wm.call_menu``; RF-003-07); verdadero si
    la dibujó."""
    if is_available(menu_id):
        return False
    draw_note(layout, unavailable_note(catalog().commands[menu_id]))
    return True


def _menu_draw(menu_id: str) -> Callable[[Any, Any], None]:
    def draw(self: Any, context: Any) -> None:
        cat = catalog()
        spec = cat.menus[menu_id]
        layout = self.layout
        hide = bool(preference("hide_unavailable", False))
        first = step_text(cat, menu_id)
        if first:
            row = layout.row()
            row.active = False
            row.label(text=first, translate=False)
        note = _draw_unavailable(layout, menu_id)
        _draw_groups(layout, context, spec.groups, lead=bool(first) or note, hide=hide)

    return draw


def _pie_draw(pie_id: str) -> Callable[[Any, Any], None]:
    def draw(self: Any, context: Any) -> None:
        pie = self.layout.menu_pie()
        for key in catalog().pies[pie_id].slots:
            draw_command(pie, key, context=context)

    return draw


def _context_draw(kind: str) -> Callable[[Any, Any], None]:
    def draw(self: Any, context: Any) -> None:
        spec = catalog().contexts[kind]
        hide = bool(preference("hide_unavailable", False))
        items = shown_items(spec.items, hide)
        if _draw_unavailable(self.layout, spec.id) and items:
            self.layout.separator(type="LINE")
        for item in items:
            _draw_item(self.layout, context, item, hide)

    return draw


def _menu_class(cat: Catalog, menu_id: str, draw: Callable[[Any, Any], None]) -> type:
    cmd = cat.commands[menu_id]
    namespace: dict[str, Any] = {
        "__doc__": cmd.description,
        "bl_idname": menu_id,
        "bl_label": text(cmd.label),
        "bl_description": text(cmd.description),
        "bl_translation_context": TRANSLATION_CONTEXT,
        "draw": draw,
    }
    return type(menu_id, (bpy.types.Menu,), namespace)


def build(cat: Catalog | None = None) -> tuple[type, ...]:
    """Las clases de los menús del catálogo con contenido, los menús circulares y los
    contextuales, en orden (los padres antes que sus submenús)."""
    cat = catalog() if cat is None else cat
    classes: list[type] = []
    for menu_id in cat.menus:
        if menu_id in cat.commands:
            classes.append(_menu_class(cat, menu_id, _menu_draw(menu_id)))
    for pie_id in cat.pies:
        classes.append(_menu_class(cat, pie_id, _pie_draw(pie_id)))
    for kind, spec in cat.contexts.items():
        classes.append(_menu_class(cat, spec.id, _context_draw(kind)))
    return tuple(classes)
