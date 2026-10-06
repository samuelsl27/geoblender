# SPDX-License-Identifier: GPL-3.0-or-later
"""Menús del módulo ``core`` (spec 002; RF-002-08, RF-002-31, RF-002-32; plan 002 §5.3;
BS §8.1).

- ``GEOBLENDER_MT_core_recent`` («Abrir reciente ▸»): los 10 proyectos abiertos por
  última vez en este equipo, de los datos de usuario de la extensión (nunca de un
  proyecto); cada uno abre su carpeta con ``geoblender.core_open_project``.
- ``GEOBLENDER_MT_core_network`` («Copia local y red ▸»): trabajar en una copia local,
  publicarla en la red y el cerrojo del proyecto.

La spec 003 los coloca en la barra superior (menú «Proyecto»).
"""

from __future__ import annotations

import bpy

from ...core.i18n import tr
from ..scene import project_session

TRANSLATION_CONTEXT = "Geoblender"


class GEOBLENDER_MT_core_recent(bpy.types.Menu):
    """Recently opened projects on this computer"""

    bl_idname = "GEOBLENDER_MT_core_recent"
    bl_label = "Open recent"
    bl_translation_context = TRANSLATION_CONTEXT

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        recent = project_session.userdata().recent_projects()
        if not recent:
            layout.label(text=tr("No recent projects"), translate=False)
            return
        for item in recent:
            missing = not item.path.is_dir()
            props = layout.operator(
                "geoblender.core_open_project",
                text=tr("{name} · {path}", name=item.name, path=item.path),
                icon="ERROR" if missing else "FILE_FOLDER",
                translate=False,
            )
            props.directory = str(item.path)


class GEOBLENDER_MT_core_network(bpy.types.Menu):
    """Local working copy and network: take a local copy, publish it, project lock"""

    bl_idname = "GEOBLENDER_MT_core_network"
    bl_label = "Local copy and network"
    bl_translation_context = TRANSLATION_CONTEXT

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.operator(
            "geoblender.core_checkout_project", text=tr("Work on a local copy…"),
            icon="DISK_DRIVE", translate=False,
        )
        layout.operator(
            "geoblender.core_publish_project", text=tr("Publish to the network…"),
            icon="NETWORK_DRIVE", translate=False,
        )
        layout.separator()
        layout.operator(
            "geoblender.core_show_lock", text=tr("Project lock (who holds it, release)…"),
            icon="LOCKED", translate=False,
        )


# En orden de registro.
classes: tuple[type, ...] = (GEOBLENDER_MT_core_recent, GEOBLENDER_MT_core_network)
