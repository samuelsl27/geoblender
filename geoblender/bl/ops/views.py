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
"""

from __future__ import annotations

import logging
from typing import Any

import bpy
from bpy.props import BoolProperty

from ...core.errors import GeoblenderError
from ...core.i18n import tr
from ...core.project.model import Progress
from ..scene import project_session, refresh
from ..ui import gate
from .core import TRANSLATION_CONTEXT, _poll_project, _StepsModal

LOGGER = logging.getLogger("geoblender.bl.ops")


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


# En orden de registro.
classes: tuple[type, ...] = (GEOBLENDER_OT_core_refresh,)
