# SPDX-License-Identifier: GPL-3.0-or-later
"""Órdenes de las versiones (spec 009; plan 009 §5.3.5; ADR-0011, ADR-0012).

- ``geoblender.core_set_active_version`` (T18; RF-009-10; plan A11, D-8, D-25, D-42): «Fijar la
  versión activa», cada versión de Proyecto ▸ Versiones ▸ Versión activa y de la ventana del
  control 8, con el uid de la versión (``version_uid``; vacío, «Sin versión»). Cambia la de la
  sesión con ``bl.scene.versions.set_active``: las escenas del proyecto y los datos de usuario,
  nunca el proyecto, así que se puede también en solo lectura, para consultar, y con una versión
  SUPERADO o DESCARTADO (D-42). Sin decir cuál (F3, un guion sin la propiedad) no cambia nada;
  una versión que el proyecto no tiene se rechaza con su texto. Sin ``UNDO``: no cambia nada
  que deshacer (la vista guarda la versión activa al guardarse). Con el proyecto abierto.

Las demás órdenes de la 009 (Nueva versión…, Cambiar estado…, Nueva revisión…, Reproducir…,
decisiones) llegan en sus tareas (T19 a T24) y, hasta entonces, son provisionales de R-07.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

import bpy
from bpy.props import StringProperty

from ...core import i18n
from ...core.errors import GeoblenderError
from ...core.i18n import tr
from ...core.versions.model import VersionError, render
from ..scene import project_session
from ..scene import versions as scene_versions
from .core import TRANSLATION_CONTEXT, _poll_project

LOGGER = logging.getLogger("geoblender.bl.ops")


class GEOBLENDER_OT_core_set_active_version(bpy.types.Operator):
    """Make this version the active one"""

    bl_idname = "geoblender.core_set_active_version"
    bl_label = "Set the active version"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    version_uid: StringProperty(  # type: ignore[valid-type]
        name="Version",
        description="Identity of the version to make active (empty: no version)",
        default="",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return _poll_project(cls, context)

    def execute(self, context: bpy.types.Context) -> set[str]:
        project = project_session.current()
        if project is None:
            self.report({"ERROR"}, tr("No project is open"))
            return {"CANCELLED"}
        if not self.properties.is_property_set("version_uid"):
            self.report({"WARNING"}, tr("Choose the version in Project ▸ Versions ▸ Active "
                                        "version: nothing has changed"))
            return {"CANCELLED"}
        try:
            warnings = scene_versions.set_active(context, project, self.version_uid or None)
        except VersionError as exc:
            self.report({"ERROR"}, render(exc.code, language=i18n.language(), **exc.values))
            return {"CANCELLED"}
        except GeoblenderError as exc:
            self.report({"ERROR"}, exc.message)
            return {"CANCELLED"}
        except (sqlite3.Error, OSError) as exc:
            LOGGER.exception("No se pudieron leer las versiones del proyecto")
            self.report({"ERROR"}, tr("The versions of the project could not be read: {detail}",
                                      detail=str(exc)))
            return {"CANCELLED"}
        for message in warnings:
            self.report({"WARNING"}, message)
        shown = scene_versions.active()
        version = tr("No version") if shown is None else shown.name()
        self.report({"INFO"}, tr("Active version: {version}", version=version))
        return {"FINISHED"}

    def invoke(self, context: bpy.types.Context, event: Any) -> set[str]:
        return self.execute(context)


# En orden de registro.
classes: tuple[type, ...] = (GEOBLENDER_OT_core_set_active_version,)
