# SPDX-License-Identifier: GPL-3.0-or-later
"""Órdenes de la vista regenerable (spec 010; plan 010 §5.3.3; ADR-0011, ADR-0012).

- ``geoblender.core_refresh`` (T11; RF-010-01; RNF-010-01; plan A2, D-18): Proyecto ▸ Refrescar
  las vistas desde el proyecto, F5 y el control 7 del acceso rápido. Vuelve a cargar lo que no
  está al día con los pasos de ``bl.scene.refresh.refresh_steps``: desde la interfaz
  (``invoke``: el menú, el atajo, el acceso rápido), un modal que los avanza desde el
  temporizador de su ventana (``_StepsModal`` de ``bl.ops.core``, como «Cargar en la vista…»:
  un evento cada 0,05 s, 0,05 s de pasos en cada uno), con su avance en la barra de estado y
  Esc, que deja la vista como estaba; desde un guion o sin ventana (``blender -b``), de una vez.
  Lleva ``UNDO``: cambia los objetos de la vista y no escribe en el proyecto (Ctrl+Z deshace
  solo la vista). Se puede con el proyecto abierto, también en solo lectura, y en el modo
  Geoblender si se lanza desde una Vista 3D (F5, la puerta de la 003). Sin nada que volver a
  cargar, «La vista está al día» (sin paso de deshacer).
- ``geoblender.core_open_view_project`` (T12; RF-010-04, RF-002-29; plan A5, D-14; interna):
  «Abrir el proyecto de esta vista». La lanza el temporizador de un disparo que pone
  ``bl.scene.view_link`` tras cargar una vista sin su proyecto, y el botón del panel Proyecto
  (R3), con la vista (``filepath``), la identidad, el nombre y la carpeta relativa de su
  proyecto y el aviso de RF-002-29 (``notice``). Desde la interfaz (``invoke``), un diálogo con
  el aviso, la pregunta con dónde está y los botones de Geoblender «Abrir el proyecto de esta
  vista» (la misma orden, ``EXEC_DEFAULT``) y «Ahora no», que no hace nada
  (``template_popup_confirm``, ``docs/trampas.md`` §5). Aceptar (``execute``) lo busca
  (``core.views.locate.find_project``: la carpeta relativa a la vista y, si no, por su identidad
  entre los recientes del equipo; solo lee cabeceras) y lo abre con «Abrir proyecto…» de la 002
  desde la interfaz (:func:`open_project_folder`: su cerrojo, solo lectura y migración); después,
  lo de la marca en vivo al abrir (RF-010-03). Sin ``UNDO``: no cambia la vista.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import bpy
from bpy.props import BoolProperty, StringProperty

from ...core.errors import GeoblenderError
from ...core.i18n import tr
from ...core.project.model import Progress
from ...core.views import locate
from ..scene import project_session, refresh, view_link
from ..ui import gate, labels
from .core import TRANSLATION_CONTEXT, _poll_project, _StepsModal

LOGGER = logging.getLogger("geoblender.bl.ops")
DIALOG_WIDTH = 560
"""El ancho del diálogo «Abrir el proyecto de esta vista» (px a escala 1,0)."""
_HIDDEN = {"HIDDEN", "SKIP_SAVE"}


class GEOBLENDER_OT_core_refresh(_StepsModal, bpy.types.Operator):
    """Reload the views from the project; the number counts the stale results"""

    bl_idname = "geoblender.core_refresh"
    bl_label = "Refresh the views from the project"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "UNDO"}

    # Como «Cargar en la vista…» (T50 de la 006): cada evento del temporizador avanza pasos
    # durante, como mucho, este tiempo (RNF-010-01: ninguna llamada de más de 0,2 s).
    STEP_BUDGET_S = 0.05

    # En pasos desde el temporizador de la ventana, con el avance y Esc: lo pone ``invoke``
    # (el menú, F5, el acceso rápido); desde un guion, sin él, de una vez.
    in_steps: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return gate.poll(cls, context) and _poll_project(cls, context)

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        self.in_steps = getattr(context, "window", None) is not None
        return self.execute(context)

    def execute(self, context: bpy.types.Context) -> set[str]:
        project = project_session.current()
        if project is None:
            return {"CANCELLED"}
        steps = refresh.refresh_steps(context, project)
        if self.in_steps and getattr(context, "window", None) is not None:
            self._project = project
            self._start(context, steps)
            return {"RUNNING_MODAL"}
        self.report_log: list[str] = []
        outcome: refresh.RefreshOutcome | None = None
        try:
            for step in steps:
                if isinstance(step.result, refresh.RefreshOutcome):
                    outcome = step.result
        except GeoblenderError as exc:
            self._report({"ERROR"}, exc.message)
            return {"CANCELLED"}
        assert outcome is not None
        return self._outcome(outcome)

    def _outcome(self, outcome: refresh.RefreshOutcome) -> set[str]:
        """Lo que dice la orden al terminar: los avisos y los errores de lo que volvió a cargar
        y cuántos datos volvió a cargar, cuántos están sin respaldo y cuántos al día."""
        load = outcome.load
        if load is not None:
            for text in load.notes:
                self._report({"WARNING"}, text)
            for text in load.errors:  # con algo cargado, un aviso: los demás sí se cargaron
                self._report({"WARNING"} if load.loaded else {"ERROR"}, text)
        self._report({"INFO"}, refresh.outcome_text(outcome))
        self.outcome = "FINISHED" if outcome.changed else "CANCELLED"
        return {self.outcome}

    # En pasos ------------------------------------------------------------------------------

    def _status_text(self, step: Progress) -> str:
        percent = int(100 * step.done / step.total) if step.total else 0
        return tr("Refreshing «{name}» in the view… {percent} % · Esc: cancel",
                  name=step.message, percent=percent)

    def _cancelled_text(self) -> str:
        return tr("Refresh cancelled: the view stays as it was")

    def _result(self, context: bpy.types.Context, step: Progress) -> set[str] | None:
        if not isinstance(step.result, refresh.RefreshOutcome):
            if project_session.current() is not getattr(self, "_project", None):
                return self._fail(context, tr("The project was closed while refreshing the "
                                              "view: the view stays as it was"))
            return None
        self._done(context)
        return self._outcome(step.result)

    def modal(self, context: bpy.types.Context, event: Any) -> set[str]:
        try:
            return super().modal(context, event)
        except Exception as exc:  # noqa: BLE001 - lo preparado ya se borró: no queda nada
            LOGGER.error("«Refrescar las vistas desde el proyecto» se ha parado", exc_info=exc)
            return self._fail(context, tr("Refreshing the view stopped: {error}",
                                          error=str(exc)))


# Abrir el proyecto de una vista ------------------------------------------------------------


def open_project_folder(root: Path) -> set[str]:
    """«Abrir proyecto…» de la 002 (``geoblender.core_open_project``) con la carpeta ``root``,
    como desde la interfaz (``INVOKE_DEFAULT``): con sus reglas de cerrojo, solo lectura y
    migración (su diálogo, si hace falta) y su avance."""
    return bpy.ops.geoblender.core_open_project("INVOKE_DEFAULT", directory=str(root))


class GEOBLENDER_OT_core_open_view_project(bpy.types.Operator):
    """Open the project of the loaded view: where the view saved it or among the recents"""

    bl_idname = view_link.OPEN_VIEW_PROJECT
    bl_label = "Open the project of this view"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}

    # La vista que se cargó, lo que guarda su escena sobre su proyecto y el aviso de RF-002-29
    # (``bl.scene.view_link.Offer.properties``).
    filepath: StringProperty(options=_HIDDEN)  # type: ignore[valid-type]
    project_uid: StringProperty(options=_HIDDEN)  # type: ignore[valid-type]
    project_name: StringProperty(options=_HIDDEN)  # type: ignore[valid-type]
    relative_path: StringProperty(options=_HIDDEN)  # type: ignore[valid-type]
    notice: StringProperty(options=_HIDDEN)  # type: ignore[valid-type]

    def _link(self) -> locate.ViewLink:
        return locate.ViewLink(self.project_uid, self.project_name, self.relative_path)

    def _properties(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in
                ("filepath", "project_uid", "project_name", "relative_path", "notice")}

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False, title=tr("Open the project of this view")
        )

    def draw(self, context: bpy.types.Context) -> None:
        """El aviso de RF-002-29, la pregunta con dónde está el proyecto y los botones de
        Geoblender: «Abrir el proyecto de esta vista» (esta orden con lo mismo,
        ``EXEC_DEFAULT``: sin volver a abrir el diálogo) y «Ahora no» (cierra sin hacer
        nada)."""
        layout = self.layout
        width = labels.dialog_width(DIALOG_WIDTH)
        if self.notice:
            labels.draw_wrapped(layout, self.notice, width, icon="INFO")
        labels.draw_wrapped(layout, view_link.location_text(self._link()), width,
                            icon="FILE_FOLDER")
        layout.operator_context = "EXEC_DEFAULT"
        buttons = layout.template_popup_confirm(
            view_link.OPEN_VIEW_PROJECT, text=tr("Open the project of this view"),
            cancel_text=tr("Not now"), translate=False,
        )
        if buttons is None:  # fuera de un diálogo, Blender no los dibuja
            return
        for name, value in self._properties().items():
            setattr(buttons, name, value)

    def execute(self, context: bpy.types.Context) -> set[str]:
        """Aceptar: busca el proyecto de la vista y lo abre con «Abrir proyecto…» (002)."""
        current = project_session.current()
        if current is not None and current.uid == self.project_uid:
            self.report({"INFO"}, tr("The project «{name}» of this view is already open",
                                     name=current.name))
            return {"CANCELLED"}
        recent = project_session.userdata().recent_projects()
        found = locate.find_project(self._link(), self.filepath or None, recent)
        if isinstance(found, locate.NotFound):
            self.report({"WARNING"}, tr(
                "The project «{name}» of this view is not where the view saved it nor among "
                "the recent projects of this computer", name=self.project_name))
            return {"CANCELLED"}
        try:
            result = open_project_folder(found.root)
        except RuntimeError as exc:  # lo que dijo «Abrir proyecto…» ya está en el registro
            LOGGER.warning("No se pudo abrir el proyecto de la vista «%s»: %s",
                           found.root, exc)
            return {"CANCELLED"}
        return {"FINISHED"} if result & {"FINISHED", "RUNNING_MODAL"} else {"CANCELLED"}


# En orden de registro.
classes: tuple[type, ...] = (GEOBLENDER_OT_core_refresh, GEOBLENDER_OT_core_open_view_project)
