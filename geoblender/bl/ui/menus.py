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
(nunca los 13 menús de la barra, que dibuja ``bl/ui/topbar.py``). Lo que aún no es un
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
from .commands import TRANSLATION_CONTEXT, catalog, preference, text
from .drawing import draw_command

STEPS_TOTAL = 11  # pasos del flujo (BS §5)


def step_text(cat: Catalog, menu_id: str) -> str:
    """«Paso n de 11 · <etapa>» de un menú del flujo ("" en los demás)."""
    spec = cat.menus.get(menu_id)
    if spec is None or spec.step is None:
        return ""
    return tr("Step {n} of {total} · {stage}", n=spec.step, total=STEPS_TOTAL,
              stage=text(spec.stage))


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
    for index, group in enumerate(groups):
        if index > 0 or lead:
            layout.separator(type="LINE")
        if group.label:
            row = layout.row()
            row.active = False
            row.label(text=text(group.label), translate=False)
        for item in group.items:
            _draw_item(layout, context, item, hide)


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
        _draw_groups(layout, context, spec.groups, lead=bool(first), hide=hide)

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
        for item in spec.items:
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
