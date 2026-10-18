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
  lo de la marca en vivo al abrir (RF-010-03). Sin ``UNDO``: no cambia la vista. Si no lo
  encuentra (T13; RF-010-05), ya al abrir el diálogo (``invoke`` lo busca: solo lee cabeceras)
  o al aceptar, el diálogo da el aviso con la ubicación y la identidad esperadas
  (``not_found``) y, en lugar de abrir, ofrece «Localizar el proyecto…» y «Ahora no»; aceptar
  desde un guion solo avisa.
- ``geoblender.core_locate_project`` (T13; RF-010-05; plan A5; interna): «Localizar el
  proyecto…». Desde la interfaz, el explorador de carpetas (en la de la vista); con la carpeta
  elegida, solo la acepta si su cabecera tiene la identidad del proyecto de la vista
  (``core.views.locate.check_chosen``: solo la lee) y la abre como arriba; si no, dice de qué
  proyecto es (o que no es un proyecto) y no abre ni escribe nada. Nunca usa la vista como
  fuente de datos (RF-002-29).
- ``geoblender.core_show_selection_figures`` (T16; RF-010-08; plan A8, D-17, D-18): «Cifras de
  la selección», el control 29 y el menú de la selección. Lee del proyecto las cifras
  registradas, con su unidad, su tipo y sus marcas, de los datos que muestran los objetos
  seleccionados (``bl.ui.view_panels.fill_selection_figures``) y abre su ventana
  (``GEOBLENDER_PT_core_selection_figures``, con ``wm.call_panel``, como las ventanas de la 008);
  sin ventana (un guion), solo las lee. No mide nada ni escribe en el proyecto; sin ``UNDO``: no
  cambia la escena. Con el proyecto abierto (también en solo lectura) y en el modo Geoblender
  desde una Vista 3D (la puerta de la 003).
"""

from __future__ import annotations

import logging
import sqlite3
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
from .core import TRANSLATION_CONTEXT, _folder, _poll_project, _StepsModal

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


def _open_located(root: Path) -> set[str]:
    """Abre el proyecto de la vista, ya encontrado en ``root``, con :func:`open_project_folder`;
    lo que devuelve una orden que lo pidió."""
    try:
        result = open_project_folder(root)
    except RuntimeError as exc:  # lo que dijo «Abrir proyecto…» ya está en el registro
        LOGGER.warning("No se pudo abrir el proyecto de la vista «%s»: %s", root, exc)
        return {"CANCELLED"}
    return {"FINISHED"} if result & {"FINISHED", "RUNNING_MODAL"} else {"CANCELLED"}


def _already_open(operator: Any, project_uid: str) -> bool:
    """Si el proyecto de la vista ya es el abierto (y entonces lo dice ``operator``)."""
    current = project_session.current()
    if current is None or current.uid != project_uid:
        return False
    operator.report({"INFO"}, tr("The project «{name}» of this view is already open",
                                 name=current.name))
    return True


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
    # El aviso de RF-010-05 si no se encuentra el proyecto (lo pone la búsqueda; vacío si sí).
    not_found: StringProperty(options=_HIDDEN)  # type: ignore[valid-type]

    def _link(self) -> locate.ViewLink:
        return locate.ViewLink(self.project_uid, self.project_name, self.relative_path)

    def _properties(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in
                ("filepath", "project_uid", "project_name", "relative_path", "notice")}

    def _find(self) -> locate.Located | locate.NotFound:
        """Dónde está el proyecto de la vista (``core.views.locate.find_project``: la carpeta
        relativa a la vista y los recientes del equipo; solo lee cabeceras); apunta en
        ``not_found`` el aviso de RF-010-05 si no está."""
        recent = project_session.userdata().recent_projects()
        found = locate.find_project(self._link(), self.filepath or None, recent)
        self.not_found = (view_link.not_found_text(found, self.filepath)
                          if isinstance(found, locate.NotFound) else "")
        return found

    def _dialog(self, context: bpy.types.Context) -> set[str]:
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False, title=tr("Open the project of this view")
        )

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        self._find()  # el diálogo dice ya si no se encuentra (RF-010-05)
        return self._dialog(context)

    def draw(self, context: bpy.types.Context) -> None:
        """El aviso de RF-002-29, la pregunta con dónde está el proyecto y los botones de
        Geoblender: «Abrir el proyecto de esta vista» (esta orden con lo mismo,
        ``EXEC_DEFAULT``: sin volver a abrir el diálogo) y «Ahora no» (cierra sin hacer
        nada). Si no se encuentra, en lugar de la pregunta, el aviso de RF-010-05 y
        «Localizar el proyecto…» (``INVOKE_DEFAULT``: su explorador de carpetas)."""
        layout = self.layout
        width = labels.dialog_width(DIALOG_WIDTH)
        if self.notice:
            labels.draw_wrapped(layout, self.notice, width, icon="INFO")
        if self.not_found:
            labels.draw_wrapped(layout, self.not_found, width, icon="ERROR")
            layout.operator_context = "INVOKE_DEFAULT"
            buttons = layout.template_popup_confirm(
                view_link.LOCATE_PROJECT, text=tr("Locate the project…"),
                cancel_text=tr("Not now"), translate=False,
            )
            if buttons is None:
                return
            for name, value in view_link.locate_properties(self._link(),
                                                           self.filepath).items():
                setattr(buttons, name, value)
            return
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
        """Aceptar: busca el proyecto de la vista y lo abre con «Abrir proyecto…» (002). Si no
        lo encuentra, el aviso de RF-010-05 y, con interfaz, el diálogo otra vez con él y
        «Localizar el proyecto…»."""
        if _already_open(self, self.project_uid):
            return {"CANCELLED"}
        found = self._find()
        if isinstance(found, locate.NotFound):
            self.report({"WARNING"}, self.not_found)
            if view_link.background():
                return {"CANCELLED"}
            return self._dialog(context)
        return _open_located(found.root)


class GEOBLENDER_OT_core_locate_project(bpy.types.Operator):
    """Choose the folder of the project of the view: only a project with its identity opens"""

    bl_idname = view_link.LOCATE_PROJECT
    bl_label = "Locate the project…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}

    # La carpeta elegida en el explorador (al lanzarlo, la de la vista) y el proyecto que se
    # busca (``bl.scene.view_link.locate_properties``).
    directory: StringProperty(subtype="DIR_PATH", options=_HIDDEN)  # type: ignore[valid-type]
    filter_folder: BoolProperty(default=True, options=_HIDDEN)  # type: ignore[valid-type]
    project_uid: StringProperty(options=_HIDDEN)  # type: ignore[valid-type]
    project_name: StringProperty(options=_HIDDEN)  # type: ignore[valid-type]

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        """El explorador de carpetas; al aceptar en él, :meth:`execute` con la elegida."""
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context: bpy.types.Context) -> set[str]:
        """Solo abre la carpeta elegida si es el proyecto de la vista (su identidad); si no,
        dice de qué proyecto es o que no es un proyecto, sin abrir ni escribir nada."""
        if not self.directory or _already_open(self, self.project_uid):
            return {"CANCELLED"}
        link = locate.ViewLink(self.project_uid, self.project_name, "")
        found = locate.check_chosen(_folder(self.directory), link)
        if isinstance(found, locate.NotFound):
            other = (locate.project_name(found.expected)
                     if found.found_uid is not None and found.expected is not None else None)
            self.report({"WARNING"}, view_link.refused_text(found, other))
            return {"CANCELLED"}
        return _open_located(found.root)


# Cifras de la selección --------------------------------------------------------------------


def _call_panel(name: str) -> set[str]:
    """Abre la ventana emergente ``name`` con ``wm.call_panel``; sigue abierta aunque el ratón
    salga de ella (``keep_open``), hasta pulsar fuera o Esc (como las de la 008)."""
    return bpy.ops.wm.call_panel(name=name, keep_open=True)


class GEOBLENDER_OT_core_show_selection_figures(bpy.types.Operator):
    """Registered figures of the selected data, with unit, type and marks; it does not measure"""

    bl_idname = "geoblender.core_show_selection_figures"
    bl_label = "Selection figures"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return gate.poll(cls, context) and _poll_project(cls, context)

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        return self.execute(context)

    def execute(self, context: bpy.types.Context) -> set[str]:
        """Lee del proyecto las cifras registradas de los datos seleccionados, con sus marcas
        (``bl.ui.view_panels.fill_selection_figures``: no mide ni escribe nada), y abre su
        ventana; desde un guion sin ventana, solo las lee."""
        from ..ui import view_panels  # al usarlo, como la 008 con sus ventanas

        if project_session.current() is None:
            return {"CANCELLED"}
        try:
            view_panels.fill_selection_figures(context)
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            from .core_provenance import error_text  # el texto de la 008, en su idioma

            LOGGER.warning("No se pudieron leer las cifras de la selección", exc_info=True)
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        if getattr(context, "window", None) is None:
            return {"FINISHED"}  # desde un guion sin ventana: las filas, sin la ventana
        return _call_panel(view_panels.SELECTION_FIGURES_PANEL)


# En orden de registro.
classes: tuple[type, ...] = (
    GEOBLENDER_OT_core_refresh,
    GEOBLENDER_OT_core_open_view_project,
    GEOBLENDER_OT_core_locate_project,
    GEOBLENDER_OT_core_show_selection_figures,
)
