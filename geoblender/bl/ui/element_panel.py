# SPDX-License-Identifier: GPL-3.0-or-later
"""El panel «Elemento de Geoblender» del editor de Propiedades (spec 019, T09; HU-019-1; RF-019-06, RF-019-14; plan 019
§5.1, §5.5 y P-1; ADR-0032).

:class:`GEOBLENDER_PT_ui_element` va en Propiedades, pestaña **Objeto**, con la caja «Ficha» y la caja «Procedencia» de
``bl.ui.card``: lo que la barra N de la Vista 3D (``view_panels``) enseñaba como «Elemento activo», que ahora es una línea
con un botón que lleva aquí (UI-29: cada dato, en un sitio). Va **solo** cuando el filtro reversible de los paneles
nativos (T15) quite los de Blender; hasta entonces se registra el último y no reordena nada (``bl_order`` no reordena los
paneles nativos en 5.2, solo cuenta el orden de registro). Sin objeto activo la pestaña Objeto no existe: el editor queda
vacío (se acepta; T11 dice el estado del proyecto). Solo se muestra con un proyecto abierto y un objeto que es la vista de
un dato suyo (el objeto ajeno, T11). El panel no tiene «Aceptar» (UI-27) ni escribe nada en el proyecto.

La orden ``geoblender.ui_show_element`` (:mod:`bl.ops.element`) pone la pestaña Objeto en el editor de Propiedades.
"""

from __future__ import annotations

from typing import Any

import bpy

from ...core.i18n import tr
from ..scene import project_session
from . import card, view_panels

TRANSLATION_CONTEXT = "Geoblender"
ELEMENT_PANEL = "GEOBLENDER_PT_ui_element"
ELEMENT_LABEL = "Geoblender element"  # msgid del título


class GEOBLENDER_PT_ui_element(bpy.types.Panel):
    """The sheet of the active element of the project: what it is, its version and status, its figures and where it comes from"""

    bl_idname = ELEMENT_PANEL
    bl_label = ELEMENT_LABEL
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"
    bl_translation_context = TRANSLATION_CONTEXT

    @classmethod
    def poll(cls, context: Any) -> bool:
        project = project_session.current()
        if project is None:
            return False
        uid, owner = view_panels.shown_by(view_panels._active_object(context))  # noqa: SLF001
        return bool(uid) and owner == project.uid

    def draw(self, context: Any) -> None:
        card.draw_card(self.layout, context)


LOOK_PANEL = "GEOBLENDER_PT_ui_element_look"
LOOK_LABEL = "Appearance"
LOOK_MORE_LABEL = "More appearance"
RESET_OPERATOR = "geoblender.ui_appearance_reset"
FREQUENT = ("label", "color", "transparency", "visible")
"""Lo que va arriba (UI-02); lo demás que ofrezca el tipo va en «Más aspecto», plegado."""
RARE = ("line_width", "point_size", "labels", "wire")
_SLIDERS = frozenset({"transparency"})


def _name(prop: str) -> str:
    """El nombre de la propiedad ``prop`` del aspecto en el idioma de la interfaz."""
    return {"label": tr("Label"), "color": tr("Color"), "transparency": tr("Transparency"), "visible": tr("Visible"),
            "line_width": tr("Line width"), "point_size": tr("Point size"), "labels": tr("Labels"),
            "wire": tr("Wireframe")}[prop]


def _shown_object(context: Any) -> Any | None:
    """El objeto activo si es la vista de un dato del proyecto abierto (el mismo filtro que la ficha)."""
    project = project_session.current()
    if project is None:
        return None
    obj = view_panels._active_object(context)  # noqa: SLF001
    uid, owner = view_panels.shown_by(obj)
    return obj if uid and owner == project.uid else None


def _offered(obj: Any, props: tuple[str, ...]) -> list[str]:
    from ..scene import appearance

    offer = appearance.offered(str(obj.geoblender.kind))
    return [prop for prop in props if prop in offer]


def _changed_props(obj: Any, props: tuple[str, ...]) -> set[str]:
    """Las de ``props`` que ofrece el tipo y que alguien cambió: con valor guardado en el espejo y distinto del predefinido."""
    from ...core.appearance import catalog
    from ..scene import appearance

    look = obj.geoblender.look
    now, default = appearance.read(obj), catalog.defaults_for(str(obj.geoblender.kind))
    return {prop for prop in _offered(obj, props)
            if look.is_property_set(prop) and (now.get(prop) or "") != (default.get(prop) or "")}


def draw_look(layout: Any, obj: Any, props: tuple[str, ...]) -> None:
    """Las propiedades de aspecto ``props`` que ofrece el tipo de ``obj``, con selectores y deslizadores nativos
    (``Object.geoblender.look``). Junto al valor que nadie cambió, «predefinido» (UI-03, y en texto, no solo en color:
    UI-30/31); junto al cambiado, un botón que vuelve al predefinido (``ui_appearance_reset``). No lee el proyecto."""
    look = obj.geoblender.look
    changed_props = _changed_props(obj, props)
    for prop in _offered(obj, props):
        row = layout.row(align=True)
        row.prop(look, prop, text=_name(prop), slider=prop in _SLIDERS, translate=False)
        if prop in changed_props:
            button = row.operator(RESET_OPERATOR, text="", icon="LOOP_BACK")
            button.scope, button.prop = "PROPERTY", prop
        else:
            row.label(text=tr("default"), translate=False)


class GEOBLENDER_PT_ui_element_look(bpy.types.Panel):
    """How the element looks in the views: label, color, transparency and visibility. Only the appearance of the project is written; the data, its versions and its provenance do not change"""

    bl_idname = LOOK_PANEL
    bl_label = LOOK_LABEL
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"
    bl_translation_context = TRANSLATION_CONTEXT

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _shown_object(context) is not None

    def draw(self, context: Any) -> None:
        obj = _shown_object(context)
        if obj is None:
            return
        draw_look(self.layout, obj, FREQUENT)
        if _changed_props(obj, FREQUENT + RARE):
            self.layout.operator(RESET_OPERATOR).scope = "ELEMENT"


class GEOBLENDER_PT_ui_element_look_more(bpy.types.Panel):
    """Line width, point size, labels and wireframe of the element, only the ones its type has"""

    bl_idname = LOOK_PANEL + "_more"
    bl_label = LOOK_MORE_LABEL
    bl_parent_id = LOOK_PANEL
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"
    bl_options = {"DEFAULT_CLOSED"}
    bl_translation_context = TRANSLATION_CONTEXT

    @classmethod
    def poll(cls, context: Any) -> bool:
        obj = _shown_object(context)
        return obj is not None and bool(_offered(obj, RARE))

    def draw(self, context: Any) -> None:
        obj = _shown_object(context)
        if obj is not None:
            draw_look(self.layout, obj, RARE)


def localize() -> None:
    """Los títulos en el idioma de la interfaz (antes de registrar)."""
    GEOBLENDER_PT_ui_element.bl_label = tr("Geoblender element")
    GEOBLENDER_PT_ui_element_look.bl_label = tr("Appearance")
    GEOBLENDER_PT_ui_element_look_more.bl_label = tr("More appearance")


classes: tuple[type, ...] = (GEOBLENDER_PT_ui_element, GEOBLENDER_PT_ui_element_look, GEOBLENDER_PT_ui_element_look_more)
