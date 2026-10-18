# SPDX-License-Identifier: GPL-3.0-or-later
"""La versión activa en la interfaz (spec 009, T18; HU-009-1; RF-009-10; plan 009 §5.3.5, §5.5,
A11, D-38 y D-42; AR §2 y §6).

- **Control 8** del acceso rápido del proyecto (``bl.ui.quick_access``, :func:`control_label`):
  «● V10.r2», la revisión de la versión activa (la abierta o, si ya no tiene, la última) con el
  icono de su estado (``gb_state_<estado>``: VIGENTE verde, BORRADOR ámbar, SUPERADO gris,
  DESCARTADO marrón; sin interfaz gráfica, su reserva nativa); sin versión, «Sin versión» con el
  icono del control; en los niveles C a E de la barra, solo el icono; sin proyecto, su título.
  Abre su ventana, :class:`GEOBLENDER_PT_core_version`.
- **La ventana** (:func:`draw_version_panel`): las versiones con su estado y su revisión («V10 ·
  Definitiva [VIGENTE] r2», con su icono; la activa, hundida) y «Sin versión», cada una con
  ``geoblender.core_set_active_version``, que la hace activa; las revisiones de la activa
  (congeladas, la abierta «en curso», cerradas, «(alterada)»); y Nueva versión…, Nueva
  revisión…, Cambiar estado…, Reproducir… y Comparar versiones…, que llegan en sus tareas (hasta
  entonces, desactivadas con su «Disponible en …»).
- **Proyecto ▸ Versiones ▸ Versión activa** (:class:`GEOBLENDER_MT_core_versions`): las mismas
  versiones y «Sin versión»; la activa lo dice («· activa»).
- **La barra de estado** dice «V10.r2 VIGENTE» tras el nombre del proyecto
  (``bl.ui.statusbar``, que abre esta misma ventana).

Todo se dibuja con lo ya leído (``bl.scene.versions`` y las filas de
``WindowManager.geoblender_version_panels``): **nada se lee del proyecto al dibujar**. Se vuelve a
leer tras cada lectura de los indicadores de la procedencia, cuando el proyecto ha cambiado
(:func:`on_project_read`, ``bl.ui.provenance.add_change_listener``), y cada cambio de lo que se ve
redibuja la barra superior y la de estado (:func:`redraw`, apuntada en ``bl.scene.versions``).
:func:`install` pone el texto del control, la escucha de los indicadores y la de las versiones;
:func:`uninstall` lo quita.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import bpy

from ...core.i18n import tr
from ...core.versions.model import VersionStatus
from ..props.versions import WINDOW_MANAGER_PROPERTY
from ..scene import project_session
from ..scene import versions as scene_versions
from . import icons, provenance, quick_access
from .commands import TRANSLATION_CONTEXT, catalog
from .drawing import draw_command, icon_kwargs, native_icon

if TYPE_CHECKING:
    from ...core.project.session import Project

PANEL = "GEOBLENDER_PT_core_version"
MENU = "GEOBLENDER_MT_core_versions"
SET_ACTIVE = "geoblender.core_set_active_version"
PANEL_UNITS = 18
"""El ancho de la ventana de la versión activa (unidades de interfaz)."""
LIST_BLANK = "BLANK1"
"""El hueco de «Sin versión» en la lista, alineada con las versiones (que llevan su icono)."""
ALTERED_ICON = "ERROR"
LATER: tuple[str, ...] = (
    "geoblender.core_new_version",
    "geoblender.core_new_revision",
    "geoblender.core_set_version_state",
    "geoblender.core_reproduce_version",
    "geoblender.res_compare_versions",
)
"""Las órdenes de la ventana (plan §5.3.5): llegan en la T19, la T21 y la T23; Comparar, en R-62."""


def state_icon(status: str) -> dict[str, Any]:
    """Los argumentos del icono del estado ``status`` («VIGENTE»…): el propio
    (``{"icon_value": n}``) o, si no se puede mostrar, su reserva nativa (``icons.toml``)."""
    name = scene_versions.STATE_ICONS[VersionStatus(status)]
    spec = catalog().icons.get(name)
    return icons.icon_kwargs(name, native_icon(spec.fallback if spec is not None else "NONE"))


def control_label(_context: Any = None) -> tuple[str, dict[str, Any]] | None:
    """El texto y el icono del control 8 (``quick_access.set_label_provider``): «V10.r2» con el
    icono de su estado o «Sin versión» con el del control; ``None`` sin proyecto (el control
    lleva su título)."""
    text = scene_versions.control_text()
    if text is None:
        return None
    shown = scene_versions.active()
    if shown is None:
        return text, icon_kwargs(catalog().commands.get(PANEL))
    return text, state_icon(shown.status)


def _view() -> Any:
    manager = getattr(bpy.context, "window_manager", None)
    return getattr(manager, WINDOW_MANAGER_PROPERTY, None)


def _rows(project: Project) -> tuple[list[Any], list[Any], str]:
    """Las filas de las versiones y de las revisiones de la activa ya leídas de ``project`` y de
    qué versión son esas revisiones (nada si las filas son de otro proyecto)."""
    view = _view()
    if view is None or view.project != project.uid:
        return [], [], ""
    return list(view.versions), list(view.revisions), view.revisions_of


def _name(row: Any) -> str:
    """«V10 · Definitiva [VIGENTE] r2» de una fila."""
    return scene_versions.version_name(row.code, row.title, row.status,
                                       row.revision.partition(".")[2])


def _closed_note(layout: Any) -> None:
    row = layout.row()
    row.enabled = False
    row.label(text=tr("Open a project"), translate=False)


def draw_version_panel(layout: Any, context: Any) -> None:
    """La ventana de la versión activa (control 8; RF-009-10): sus versiones y «Sin versión»,
    que la cambian, las revisiones de la activa y las órdenes de las versiones."""
    project = project_session.current()
    if project is None:
        _closed_note(layout)
        return
    versions, revisions, revisions_of = _rows(project)
    active = scene_versions.active_version()
    column = layout.column(align=True)
    for row in versions:
        props = column.operator(SET_ACTIVE, text=_name(row), translate=False,
                                depress=row.uid == active, **state_icon(row.status))
        props.version_uid = row.uid
    props = column.operator(SET_ACTIVE, text=tr("No version"), translate=False,
                            depress=active is None, icon=LIST_BLANK)
    props.version_uid = ""
    if active is not None and revisions:
        layout.separator()
        layout.label(text=tr("Revisions of {version}", version=revisions_of), translate=False)
        for revision in revisions:
            shown = scene_versions.revision_text(revision.label, revision.state,
                                                 revision.altered)
            line = layout.row()
            line.alert = bool(revision.altered)
            line.label(text=shown, translate=False,
                       icon=ALTERED_ICON if revision.altered else "NONE")
    layout.separator()
    for key in LATER:
        draw_command(layout, key, context=context)


def draw_versions_menu(layout: Any, _context: Any) -> None:
    """Proyecto ▸ Versiones ▸ Versión activa (RF-009-10): cada versión con su estado y «Sin
    versión», que la hacen activa; la activa lo dice."""
    project = project_session.current()
    if project is None:
        _closed_note(layout)
        return
    versions, _revisions, _of = _rows(project)
    active = scene_versions.active_version()
    for row in versions:
        shown = _name(row)
        if row.uid == active:
            shown = tr("{version} · active", version=shown)
        props = layout.operator(SET_ACTIVE, text=shown, translate=False, **state_icon(row.status))
        props.version_uid = row.uid
    if versions:
        layout.separator()
    shown = tr("No version")
    if active is None:
        shown = tr("{version} · active", version=shown)
    props = layout.operator(SET_ACTIVE, text=shown, translate=False, icon=LIST_BLANK)
    props.version_uid = ""


class GEOBLENDER_PT_core_version(bpy.types.Panel):
    """Versions with their state, revisions, new revision, change state and compare"""

    bl_idname = PANEL
    bl_label = "Active version"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_space_type = "TOPBAR"
    bl_region_type = "HEADER"
    bl_ui_units_x = PANEL_UNITS

    def draw(self, context: Any) -> None:
        draw_version_panel(self.layout, context)


class GEOBLENDER_MT_core_versions(bpy.types.Menu):
    """The versions with the state of each one; choose the active one"""

    bl_idname = MENU
    bl_label = "Active version"
    bl_translation_context = TRANSLATION_CONTEXT

    def draw(self, context: Any) -> None:
        draw_versions_menu(self.layout, context)


# Lo que se pone al día ---------------------------------------------------------------------------


def on_project_read(project: Project) -> None:
    """Tras cada lectura de los indicadores de la procedencia (el proyecto cambió): vuelve a leer
    las versiones (``bl.scene.versions.refresh``)."""
    scene_versions.refresh(project)


def redraw() -> None:
    """Redibuja la barra superior (el control 8) y la barra de estado de todas las ventanas."""
    provenance.redraw()


def install() -> None:
    """Pone el texto del control 8, la escucha de las versiones y la de los indicadores (una
    sola vez)."""
    quick_access.set_label_provider(PANEL, control_label)
    scene_versions.add_listener(redraw)
    provenance.add_change_listener(on_project_read)


def uninstall() -> None:
    """Quita lo que puso :func:`install`."""
    provenance.remove_change_listener(on_project_read)
    scene_versions.remove_listener(redraw)
    quick_access.set_label_provider(PANEL, None)


# En orden de registro.
classes: tuple[type, ...] = (GEOBLENDER_PT_core_version, GEOBLENDER_MT_core_versions)
