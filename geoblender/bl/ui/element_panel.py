# SPDX-License-Identifier: GPL-3.0-or-later
"""El panel «Elemento de Geoblender» del editor de Propiedades (spec 019, T09; HU-019-1; RF-019-06, RF-019-14; plan 019
§5.1, §5.5 y P-1; ADR-0032).

:class:`GEOBLENDER_PT_ui_element` va en Propiedades, pestaña **Objeto**, con la caja «Ficha» y la caja «Procedencia» de
``bl.ui.card``: lo que la barra N de la Vista 3D (``view_panels``) enseñaba como «Elemento activo», que ahora es una línea
con un botón que lleva aquí (UI-29: cada dato, en un sitio). Va **solo** cuando el filtro reversible de los paneles
nativos (T15) quite los de Blender; hasta entonces se registra el último y no reordena nada (``bl_order`` no reordena los
paneles nativos en 5.2, solo cuenta el orden de registro). Sin objeto activo la pestaña Objeto no existe: el estado del proyecto va en Propiedades ▸
Escena (T11, ``GEOBLENDER_PT_ui_project``; nombre, EPSG, versión activa y las acciones que sirven, o «no hay proyecto
abierto» con crear y abrir). Con un objeto que no es de Geoblender, ``GEOBLENDER_PT_ui_foreign`` dice que no pertenece
al proyecto y enseña su tipo, nombre, visibilidad y color de Blender, sin escribir nada en el proyecto (P-11, D-7). Esta ficha solo se muestra con un proyecto abierto y un objeto que es la vista de
un dato suyo. El panel no tiene «Aceptar» (UI-27) ni escribe nada en el proyecto.

La orden ``geoblender.ui_show_element`` (:mod:`bl.ops.element`) pone la pestaña Objeto en el editor de Propiedades.
"""

from __future__ import annotations

from typing import Any

import bpy

from ...core.i18n import tr
from ..scene import project_session
from . import card, labels, view_panels

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


PROJECT_PANEL = "GEOBLENDER_PT_ui_project"
FOREIGN_PANEL = "GEOBLENDER_PT_ui_foreign"
NEW_PROJECT = "geoblender.core_new_project"
OPEN_PROJECT = "geoblender.core_open_project"
CLOSE_PROJECT = "geoblender.core_close_project"
NEW_VERSION = "geoblender.core_new_version"


def _width(context: Any) -> float:
    return labels.sidebar_width(context) - card.BOX_MARGIN_PX


def _version_text() -> str:
    """La versión activa del proyecto («V3 · título») o «sin versión»."""
    from ..scene import versions

    shown = versions.active()
    if shown is None:
        return tr("No version")
    return f"{shown.code} · {shown.title}" if shown.title else str(shown.code)


class GEOBLENDER_PT_ui_project(bpy.types.Panel):
    """The state of the project when no element of it is active, and what can be done now"""

    bl_idname = PROJECT_PANEL
    bl_label = "Project status"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_translation_context = TRANSLATION_CONTEXT

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _shown_object(context) is None and not _is_foreign(context)

    def draw(self, context: Any) -> None:
        layout, width = self.layout, _width(context)
        project = project_session.current()
        if project is None:
            card.draw_lines(layout, tr("No project open"), width, icon="INFO")
            card.draw_lines(layout, tr("Create or open a project to start working"), width)
            layout.operator(NEW_PROJECT)
            layout.operator(OPEN_PROJECT)
            return
        from ..scene import georef

        reference = georef.project_georeference()
        card.draw_lines(layout, tr("Project: {name}", name=project.name), width, icon="FILE_FOLDER")
        if reference is not None:
            card.draw_lines(layout, tr("CRS: EPSG:{epsg}", epsg=reference.crs_epsg), width)
        card.draw_lines(layout, tr("Active version: {version}", version=_version_text()), width)
        card.draw_lines(layout, tr("Select an element in the 3D view to see its card and appearance"), width)
        layout.operator(NEW_VERSION)
        layout.operator(CLOSE_PROJECT)


def _is_foreign(context: Any) -> bool:
    """Con un proyecto abierto, el objeto activo no es la vista de un dato suyo (una cámara, una luz, una malla ajena)."""
    if project_session.current() is None:
        return False
    obj = view_panels._active_object(context)  # noqa: SLF001
    return obj is not None and _shown_object(context) is None


class GEOBLENDER_PT_ui_foreign(bpy.types.Panel):
    """An object of Blender that is not part of the project: only its type, name, visibility and color; nothing is written in the project"""

    bl_idname = FOREIGN_PANEL
    bl_label = "Object outside the project"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"
    bl_translation_context = TRANSLATION_CONTEXT

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _is_foreign(context)

    def draw(self, context: Any) -> None:
        layout, width = self.layout, _width(context)
        obj = view_panels._active_object(context)  # noqa: SLF001
        card.draw_lines(layout, tr("Not part of the project"), width, icon="INFO")
        card.draw_lines(layout, tr("It is an object of Blender: nothing about it is stored in the project"), width)
        kind = obj.bl_rna.properties["type"].enum_items[obj.type].name
        card.draw_lines(layout, tr("Blender type: {kind}", kind=kind), width)
        card.draw_lines(layout, tr("Name: {name}", name=obj.name), width)
        layout.prop(obj, "hide_viewport", text=tr("Visible"), invert_checkbox=True, translate=False)
        layout.prop(obj, "color", text=tr("Color"), translate=False)


def localize() -> None:
    """Los títulos en el idioma de la interfaz (antes de registrar)."""
    GEOBLENDER_PT_ui_element.bl_label = tr("Geoblender element")
    GEOBLENDER_PT_ui_element_look.bl_label = tr("Appearance")
    GEOBLENDER_PT_ui_element_look_more.bl_label = tr("More appearance")
    GEOBLENDER_PT_ui_project.bl_label = tr("Project status")
    GEOBLENDER_PT_ui_foreign.bl_label = tr("Object outside the project")


classes: tuple[type, ...] = (GEOBLENDER_PT_ui_element, GEOBLENDER_PT_ui_element_look, GEOBLENDER_PT_ui_element_look_more,
                             GEOBLENDER_PT_ui_project, GEOBLENDER_PT_ui_foreign)
