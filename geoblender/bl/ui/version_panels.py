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
  (congeladas, la abierta «en curso», cerradas, «(alterada)»); y Nueva versión… y Cambiar
  estado… (T19; sin versión activa, Cambiar estado… desactivada con el motivo:
  ``bl.ops.versions.no_version_check``), Nueva revisión… (T21; sin versión activa o con ella
  SUPERADO o DESCARTADO, desactivada con el motivo: ``bl.ops.versions.new_revision_check``),
  Reproducir… (T23; sin versión activa, sin revisión congelada o con la última alterada,
  desactivada con el motivo: ``bl.ops.versions.reproduce_check``) y Comparar versiones…, que
  llega en R-62 (hasta entonces, desactivada con su «Disponible en …»).
- **Proyecto ▸ Versiones ▸ Versión activa** (:class:`GEOBLENDER_MT_core_versions`): las mismas
  versiones y «Sin versión»; la activa lo dice («· activa»).
- **La barra de estado** dice «V10.r2 VIGENTE» tras el nombre del proyecto
  (``bl.ui.statusbar``, que abre esta misma ventana).
- **Elija una versión** (:class:`GEOBLENDER_PT_core_choose_version`, T20; RF-009-05): la ventana
  que abre una orden de un tipo de versión lanzada sin versión activa
  (``bl.ops.core_provenance.ProvenanceAwareOperator``): el porqué, las versiones en que se puede
  trabajar (BORRADOR y VIGENTE), que la hacen activa, y Nueva versión…
- **El informe de reproducir** (:class:`GEOBLENDER_PT_core_reproduce_report`, T23; RF-009-11): la
  ventana que abre Reproducir… al terminar (``bl.ops.versions``): el resumen («V10.r2
  reproducida: coinciden 5 de 5 salidas y 12 de 12 cifras»), cada salida y cada cifra con si
  coincide y, si no, su causa (en alerta), lo tomado de lo congelado, lo no reproducible y dónde
  quedó el informe en JSON. Sus líneas las pone :func:`fill_report` al terminar, ya en el idioma
  de Geoblender (:func:`report_lines`).

Todo se dibuja con lo ya leído (``bl.scene.versions`` y las filas de
``WindowManager.geoblender_version_panels``): **nada se lee del proyecto al dibujar**. Se vuelve a
leer tras cada lectura de los indicadores de la procedencia, cuando el proyecto ha cambiado
(:func:`on_project_read`, ``bl.ui.provenance.add_change_listener``), y cada cambio de lo que se ve
redibuja la barra superior y la de estado (:func:`redraw`, apuntada en ``bl.scene.versions``).
:func:`install` pone el texto del control, la escucha de los indicadores y la de las versiones;
:func:`uninstall` lo quita.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import bpy

from ...core.i18n import language, tr
from ...core.params.store import shown_value
from ...core.versions.model import EDITABLE, VersionStatus, render
from .. import compat
from ..props.versions import WINDOW_MANAGER_PROPERTY
from ..scene import project_session
from ..scene import versions as scene_versions
from . import commands, icons, labels, provenance, quick_access
from .commands import TRANSLATION_CONTEXT, catalog
from .drawing import draw_command, icon_kwargs, native_icon

if TYPE_CHECKING:
    from ...core.project.session import Project
    from ...core.versions.reproduce import ReproduceReport

PANEL = "GEOBLENDER_PT_core_version"
MENU = "GEOBLENDER_MT_core_versions"
CHOOSE_PANEL = "GEOBLENDER_PT_core_choose_version"
"""La ventana que pide elegir o crear una versión (T20; RF-009-05)."""
SET_ACTIVE = "geoblender.core_set_active_version"
NEW_VERSION = "geoblender.core_new_version"
PANEL_UNITS = 18
"""El ancho de la ventana de la versión activa (unidades de interfaz)."""
LIST_BLANK = "BLANK1"
"""El hueco de «Sin versión» en la lista, alineada con las versiones (que llevan su icono)."""
ALTERED_ICON = "ERROR"
SET_STATE = "geoblender.core_set_version_state"
NEW_REVISION = "geoblender.core_new_revision"
REPRODUCE = "geoblender.core_reproduce_version"
COMMANDS: tuple[str, ...] = (
    NEW_VERSION,
    NEW_REVISION,
    SET_STATE,
    REPRODUCE,
    "geoblender.res_compare_versions",
)
"""Las órdenes de la ventana (plan §5.3.5): Nueva versión… y Cambiar estado… (T19), Nueva
revisión… (T21), Reproducir… (T23); Comparar, en R-62."""
REPORT_PANEL = "GEOBLENDER_PT_core_reproduce_report"
"""La ventana del informe de reproducir (T23; RF-009-11)."""
REPORT_UNITS = 28
"""El ancho de la ventana del informe (unidades de interfaz: 560 px a escala 1,0, como la de las
cifras de la selección): sus causas son largas."""
REPORT_SUMMARY, REPORT_HEADING, REPORT_ITEM, REPORT_NOTE = "SUMMARY", "HEADING", "ITEM", "NOTE"
"""Las clases de línea del informe: el resumen, el título de una parte, una salida, una cifra o
una operación, y una nota (los valores de una cifra que no coincide, dónde quedó el informe)."""
MATCH_ICON, DIFFER_ICON, TAKEN_ICON, FILE_ICON = "CHECKMARK", "ERROR", "FREEZE", "FILE"


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
    for key in COMMANDS:
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


def draw_choose_version(layout: Any, context: Any) -> None:
    """La ventana que pide elegir o crear una versión (T20; RF-009-05): la abre una orden de un
    tipo de versión sin versión activa (``bl.ops.core_provenance.open_version_dialog``). Dice
    por qué («Esta orden es de una versión: elija la versión activa o cree una»), en líneas
    que caben, y ofrece las versiones en que se puede trabajar (BORRADOR y VIGENTE, con su
    estado y su revisión; ``core_set_active_version``) y Nueva versión…"""
    project = project_session.current()
    if project is None:
        _closed_note(layout)
        return
    width = labels.dialog_width(PANEL_UNITS * compat.UI_UNIT_PX)
    labels.draw_wrapped(layout, render("core.version_required", language=language()), width,
                        icon="INFO")
    versions, _revisions, _of = _rows(project)
    editable = [row for row in versions if VersionStatus(row.status) in EDITABLE]
    if editable:
        column = layout.column(align=True)
        for row in editable:
            props = column.operator(SET_ACTIVE, text=_name(row), translate=False,
                                    **state_icon(row.status))
            props.version_uid = row.uid
    layout.separator()
    draw_command(layout, NEW_VERSION, context=context)


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


class GEOBLENDER_PT_core_choose_version(bpy.types.Panel):
    """Choose or create the active version for a command of a version"""

    bl_idname = CHOOSE_PANEL
    bl_label = "Choose a version"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_space_type = "TOPBAR"
    bl_region_type = "HEADER"
    bl_ui_units_x = PANEL_UNITS

    def draw(self, context: Any) -> None:
        draw_choose_version(self.layout, context)


# El informe de reproducir (T23) ------------------------------------------------------------------


@dataclass(frozen=True)
class ReportLine:
    """Una línea de la ventana del informe antes de ponerla en
    ``WindowManager.geoblender_version_panels`` (``GEOBLENDER_PG_core_report_row``)."""

    kind: str
    text: str
    icon: str = "NONE"
    alert: bool = False


def _report_path(report: ReproduceReport, root: Path) -> str:
    """Dónde quedó el informe en JSON: relativo al proyecto si está en su caché (con «/»); si
    no (la caché en los datos de usuario, en red o en solo lectura), entero."""
    from ...core.versions.reproduce import REPORT_NAME  # al usarlo (plan §2.1)

    path = Path(report.folder or "") / REPORT_NAME
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def report_lines(report: ReproduceReport, root: Path) -> list[ReportLine]:
    """Las líneas de la ventana del informe de ``report`` (del proyecto de raíz ``root``), en el
    idioma de Geoblender (plan §5.5): el resumen (en alerta si algo no coincide o no se pudo
    reproducir); cada salida y cada cifra, que coincide o no coincide con su causa (en alerta;
    de una cifra, también sus dos valores); lo tomado de lo congelado; lo no reproducible (en
    alerta) y dónde quedó el informe en JSON."""
    shown = language()
    lines = [ReportLine(REPORT_SUMMARY, render(
        "core.version_reproduce_summary", language=shown, revision=report.revision,
        outputs=sum(item.same for item in report.outputs), outputs_total=len(report.outputs),
        figures=sum(item.same for item in report.figures), figures_total=len(report.figures)),
        MATCH_ICON if report.matches else DIFFER_ICON, not report.matches)]

    def differs(name: str, cause: Any) -> ReportLine:
        return ReportLine(REPORT_ITEM, render(
            "core.version_reproduce_differs", language=shown, name=name,
            cause=None if cause is None else cause.text(shown)), DIFFER_ICON, True)

    if report.outputs:
        lines.append(ReportLine(REPORT_HEADING, tr("Outputs")))
    for output in report.outputs:
        if output.same:
            lines.append(ReportLine(REPORT_ITEM, tr("«{name}» matches", name=output.name),
                                    MATCH_ICON))
        else:
            lines.append(differs(output.name, output.cause))
    if report.figures:
        lines.append(ReportLine(REPORT_HEADING, tr("Figures")))
    for figure in report.figures:
        frozen = shown_value(figure.frozen, figure.unit, shown)
        if figure.same:
            lines.append(ReportLine(REPORT_ITEM, tr("«{name}» matches: {value}",
                                                    name=figure.name, value=frozen),
                                    MATCH_ICON))
            continue
        lines.append(differs(figure.name, figure.cause))
        lines.append(ReportLine(REPORT_NOTE, tr(
            "Frozen: {frozen} · reproduced: {reproduced}", frozen=frozen,
            reproduced=shown_value(figure.reproduced, figure.unit, shown)), "BLANK1", True))
    if report.taken_frozen:
        lines.append(ReportLine(REPORT_HEADING, tr("Taken from what was frozen")))
        lines += [ReportLine(REPORT_ITEM, note.text(shown), TAKEN_ICON)
                  for note in report.taken_frozen]
    if report.not_reproducible:
        lines.append(ReportLine(REPORT_HEADING, tr("Not reproducible")))
        lines += [ReportLine(REPORT_ITEM, note.text(shown), DIFFER_ICON, True)
                  for note in report.not_reproducible]
    if report.folder is not None:
        lines.append(ReportLine(REPORT_NOTE, tr("Report saved in {path}",
                                                path=_report_path(report, root)), FILE_ICON))
    return lines


def fill_report(project: Project, report: ReproduceReport) -> None:
    """Pone en ``WindowManager.geoblender_version_panels`` las líneas del informe de ``report``
    del proyecto ``project`` (:func:`report_lines`), las que dibuja su ventana; las de antes,
    fuera. No lee ni escribe el proyecto."""
    view = _view()
    if view is None:
        return
    view.report_project = project.uid
    view.report_revision = report.revision
    view.report.clear()
    for line in report_lines(report, Path(project.root)):
        row = view.report.add()
        row.kind, row.text, row.icon, row.alert = line.kind, line.text, line.icon, line.alert


def draw_reproduce_report(layout: Any, _context: Any) -> None:
    """La ventana del informe de reproducir (T23; RF-009-11): «Reproducción de V10.r2» y las
    líneas ya puestas (:func:`fill_report`), partidas al ancho de la ventana. No lee el
    proyecto; sin informe de este proyecto, nada más que el título."""
    project = project_session.current()
    if project is None:
        _closed_note(layout)
        return
    view = _view()
    if view is None or view.report_project != project.uid or not view.report_revision:
        return
    layout.label(text=tr("Reproduction of {revision}", revision=view.report_revision),
                 translate=False)
    width = labels.dialog_width(REPORT_UNITS * compat.UI_UNIT_PX)
    for row in view.report:
        if row.kind == REPORT_HEADING:
            layout.separator()
        column = layout.column()
        column.alert = row.alert
        labels.draw_wrapped(column, row.text, width, icon=row.icon or "NONE")


class GEOBLENDER_PT_core_reproduce_report(bpy.types.Panel):
    """What matches the frozen revision when it is reproduced, and why what does not"""

    bl_idname = REPORT_PANEL
    bl_label = "Reproduction report"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_space_type = "TOPBAR"
    bl_region_type = "HEADER"
    bl_ui_units_x = REPORT_UNITS

    def draw(self, context: Any) -> None:
        draw_reproduce_report(self.layout, context)


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
    sola vez) y las comprobaciones de Cambiar estado… sin versión, de Nueva revisión… sin
    versión o con ella no editable y de Reproducir… sin versión, sin revisión congelada o con
    la última alterada (``commands.register_check``)."""
    # Al usarlo: bl/ops importa bl/ui (ARQ-08).
    from ..ops.versions import new_revision_check, no_version_check, reproduce_check

    quick_access.set_label_provider(PANEL, control_label)
    scene_versions.add_listener(redraw)
    provenance.add_change_listener(on_project_read)
    commands.register_check(SET_STATE, no_version_check)
    commands.register_check(NEW_REVISION, new_revision_check)
    commands.register_check(REPRODUCE, reproduce_check)


def uninstall() -> None:
    """Quita lo que puso :func:`install`."""
    commands.unregister_check(REPRODUCE)
    commands.unregister_check(NEW_REVISION)
    commands.unregister_check(SET_STATE)
    provenance.remove_change_listener(on_project_read)
    scene_versions.remove_listener(redraw)
    quick_access.set_label_provider(PANEL, None)


# En orden de registro.
classes: tuple[type, ...] = (GEOBLENDER_PT_core_version, GEOBLENDER_MT_core_versions,
                             GEOBLENDER_PT_core_choose_version,
                             GEOBLENDER_PT_core_reproduce_report)
