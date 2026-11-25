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


def localize() -> None:
    """El título en el idioma de la interfaz (antes de registrar)."""
    GEOBLENDER_PT_ui_element.bl_label = tr("Geoblender element")


classes: tuple[type, ...] = (GEOBLENDER_PT_ui_element,)
