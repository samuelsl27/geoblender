# SPDX-License-Identifier: GPL-3.0-or-later
"""Operadores del módulo ``core``: el proyecto (spec 002; plan 002 §5.3; ADR-0011).

- ``geoblender.core_new_project`` (RF-002-01 a RF-002-03, RF-002-23, RF-002-24,
  RF-002-26): diálogo y ``core.project.create_project``. Las esquinas de la ventana se
  teclean como **texto** con coma o punto decimal (``core.numbers``; un ``FloatProperty``
  las guardaría en float32, ADR-0005 §4).
- ``geoblender.core_open_project`` (RF-002-04, RF-002-05, RF-002-09, RF-002-10,
  RF-002-17, RF-002-20, RF-002-22): ``inspect_project``; si hace falta, un diálogo de
  confirmación (forzar un cerrojo caducado o reservado con el titular que se vio; migrar
  un esquema anterior con copia previa) y un **modal** que avanza ``open_steps`` (y antes
  ``migrate_steps``) con progreso y que Esc cancela (en red puede pasar de 1 s,
  principio 9).
- ``geoblender.core_close_project`` (RF-002-06): cierra el proyecto de la sesión.
- ``geoblender.core_save_project`` (RF-002-07, RF-002-18): guarda la vista en su fichero
  o, si no tiene, en ``scenes/principal.blend`` (``principal-2.blend``… si ya existe:
  nunca sustituye otra vista), con rutas relativas (``bl.scene.georef``, ``save_pre``) y
  la cabecera actualizada (``save_post``). En solo lectura no escribe en la carpeta del
  proyecto y propone «Guardar como» fuera de ella (spec §8).
- ``geoblender.core_show_lock`` (RF-002-09, RF-002-10): quién tiene el cerrojo y, si está
  caducado o reservado, forzarlo con confirmación.
- ``geoblender.core_set_crs`` (RF-002-23; en esta spec, solo consulta) y
  ``geoblender.core_show_geoorigin`` (RF-002-24): el CRS horizontal y vertical, y el
  GeoOrigin, la ventana y el paso del proyecto abierto (:func:`crs_lines`,
  :func:`origin_lines`).
- ``geoblender.core_clear_notices`` (interno): descarta los avisos pendientes que
  muestra la pestaña «Proyecto».
- ``geoblender.core_set_work_window`` (RF-002-26, RF-002-27): cambia la ventana de
  trabajo y con ella el GeoOrigin, con un motivo obligatorio
  (``core.project.Project.set_window``); las escenas pasan al origen nuevo y la vista
  queda desfasada; una ventana de más de ±8 km avisa con el error estimado.

Sin ``UNDO`` en ``bl_options``: solo escriben en el proyecto y no crean objetos de la
vista, y Ctrl+Z no puede deshacer el proyecto (regla provisional de R-10). No calculan:
validan la entrada, llaman a ``core`` y presentan el resultado. Los textos de la
interfaz pasan por el catálogo de idioma (``core.i18n.tr``: ``msgid`` en inglés, español
por defecto); los errores de ``core`` ya llegan en español con objeto, campo y valor; la
traza, al registro. ``bl_label`` y ``bl_description`` son el ``msgid`` (los traduce al
registrar la spec 003); los diálogos llevan su título traducido.

En segundo plano (``blender -b``, scripts) no se muestran diálogos: se usan las
propiedades tal como llegan, y forzar exige ``force_lock`` **y** el titular visto
(``seen_lock``).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty

from ...core.errors import GeoblenderError, ValidationError
from ...core.georef.crs import DEFAULT_HORIZONTAL_EPSG, DEFAULT_VERTICAL_EPSG, load_catalog
from ...core.georef.transform import precision_report
from ...core.i18n import format_number, format_xyz, tr
from ...core.numbers import parse_decimal
from ...core.paths import is_within, next_free_path
from ...core.project import migrations as migrations_mod
from ...core.project.create import create_project
from ...core.project.lock import LockInfo, LockState, LockStatus
from ...core.project.lock import inspect as inspect_lock
from ...core.project.migrations import MigrationResult, backup_path, migrate_steps
from ...core.project.model import OpenResult, ProjectSettings, Progress
from ...core.project.open import ProjectInspection, SchemaRelation, inspect_project, open_steps
from ..scene import georef, project_session

LOGGER = logging.getLogger("geoblender.bl.ops")
TRANSLATION_CONTEXT = "Geoblender"
LOCAL_VERTICAL_ID = "LOCAL"
_CORNERS = ("xmin", "ymin", "xmax", "ymax")


# Listas de los diálogos (estáticas: el catálogo no cambia durante la sesión) ------------


def _horizontal_items() -> list[tuple[str, str, str]]:
    return [
        (str(ref.epsg), f"EPSG:{ref.epsg} · {ref.name}", ref.area or ref.name)
        for ref in load_catalog().horizontals()
    ]


def _vertical_items() -> list[tuple[str, str, str]]:
    items = [
        (str(ref.epsg), f"EPSG:{ref.epsg} · {ref.name}", ref.name)
        for ref in load_catalog().verticals()
        if ref.epsg is not None
    ]
    items.append(
        (
            LOCAL_VERTICAL_ID,
            tr("Local reference"),
            tr("Elevations referred to a local datum, with its description"),
        )
    )
    return items


GRID_STEP_ITEMS: list[tuple[str, str, str]] = [
    (f"{step:.1f}", f"{format_number(step, 1)} m", "") for step in (0.5 * n for n in range(1, 11))
]
HORIZONTAL_ITEMS = _horizontal_items()
VERTICAL_ITEMS = _vertical_items()


def _same_folder(first: Path, second: Path) -> bool:
    try:
        return Path(first).resolve() == Path(second).resolve()
    except OSError:
        return False


def _folder(directory: str) -> Path:
    """La carpeta de una propiedad ``DIR_PATH`` (``//`` relativa al ``.blend``)."""
    return Path(bpy.path.abspath(directory)) if directory else Path()


def _draw_window_fields(layout: Any, operator: Any) -> None:
    """Las esquinas de la ventana, el paso de rejilla y Z0 de un diálogo."""
    column = layout.column(align=True)
    column.prop(operator, "xmin", text=tr("X min (m)"), translate=False)
    column.prop(operator, "ymin", text=tr("Y min (m)"), translate=False)
    column.prop(operator, "xmax", text=tr("X max (m)"), translate=False)
    column.prop(operator, "ymax", text=tr("Y max (m)"), translate=False)
    layout.prop(operator, "grid_step", text=tr("Grid step"), translate=False)
    layout.prop(operator, "z0", text=tr("Z0 (m)"), translate=False)


# Nuevo proyecto -----------------------------------------------------------------------


class GEOBLENDER_OT_core_new_project(bpy.types.Operator):
    """Create a Geoblender project (.gbproj) with its CRS and work window"""

    bl_idname = "geoblender.core_new_project"
    bl_label = "New project…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    directory: StringProperty(  # type: ignore[valid-type]
        name="Folder", description="Folder where the project folder is created",
        subtype="DIR_PATH",
    )
    name: StringProperty(name="Name", description="Project name")  # type: ignore[valid-type]
    crs_epsg: EnumProperty(  # type: ignore[valid-type]
        name="Horizontal CRS", items=HORIZONTAL_ITEMS, default=str(DEFAULT_HORIZONTAL_EPSG)
    )
    vcrs: EnumProperty(  # type: ignore[valid-type]
        name="Vertical CRS", items=VERTICAL_ITEMS, default=str(DEFAULT_VERTICAL_EPSG)
    )
    vcrs_note: StringProperty(  # type: ignore[valid-type]
        name="Local reference", description="What the elevations refer to (local reference)"
    )
    xmin: StringProperty(name="X min (m)")  # type: ignore[valid-type]
    ymin: StringProperty(name="Y min (m)")  # type: ignore[valid-type]
    xmax: StringProperty(name="X max (m)")  # type: ignore[valid-type]
    ymax: StringProperty(name="Y max (m)")  # type: ignore[valid-type]
    grid_step: EnumProperty(  # type: ignore[valid-type]
        name="Grid step", items=GRID_STEP_ITEMS, default="1.0"
    )
    z0: IntProperty(name="Z0 (m)", default=0)  # type: ignore[valid-type]

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        return context.window_manager.invoke_props_dialog(
            self, width=560, translate=False, title=tr("New project")
        )

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "directory", text=tr("Folder"), translate=False)
        layout.prop(self, "name", text=tr("Name"), translate=False)
        layout.prop(self, "crs_epsg", text=tr("Horizontal CRS"), translate=False)
        layout.prop(self, "vcrs", text=tr("Vertical CRS"), translate=False)
        if self.vcrs == LOCAL_VERTICAL_ID:
            layout.prop(
                self, "vcrs_note", text=tr("Description of the local reference"),
                translate=False,
            )
        _draw_window_fields(layout, self)

    def settings(self) -> ProjectSettings:
        """Los ajustes del diálogo; :class:`ValidationError` si un número no lo es."""
        window = tuple(
            parse_decimal(getattr(self, corner), obj=tr("Work window"), field=corner)
            for corner in _CORNERS
        )
        local = self.vcrs == LOCAL_VERTICAL_ID
        return ProjectSettings(
            name=self.name.strip(),
            window=window,
            crs_epsg=int(self.crs_epsg),
            vcrs_epsg=None if local else int(self.vcrs),
            vcrs_note=self.vcrs_note if local else None,
            grid_step_m=float(self.grid_step),
            z0=int(self.z0),
        )

    def execute(self, context: bpy.types.Context) -> set[str]:
        try:
            settings = self.settings()
            if not self.directory:
                raise ValidationError(
                    "core.project_parent_missing",
                    tr("choose the folder where the project will be created"),
                    obj=tr("New project"),
                    field=tr("folder"),
                    value=self.directory,
                )
            result = create_project(
                _folder(self.directory),
                settings,
                project_session.session(),
                project_session.userdata(),
            )
        except GeoblenderError as exc:
            LOGGER.info("Proyecto nuevo rechazado: %s", exc.message)
            self.report({"ERROR"}, exc.message)
            return {"CANCELLED"}
        closed = project_session.attach(result.project)
        self.report(
            {"INFO"},
            tr(
                "Project «{name}» created: {status}",
                name=result.record.name,
                status=result.project.status.message,
            ),
        )
        for message in (*result.warnings, *closed):
            self.report({"WARNING"}, message)
        return {"FINISHED"}


# Abrir proyecto ------------------------------------------------------------------------


def _chain(*parts: Iterator[Progress]) -> Iterator[Progress]:
    """Los pasos de varias operaciones seguidas; cerrarlo cierra la que está en curso."""
    for part in parts:
        yield from part


class GEOBLENDER_OT_core_open_project(bpy.types.Operator):
    """Open a Geoblender project (.gbproj folder)"""

    bl_idname = "geoblender.core_open_project"
    bl_label = "Open project…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    # Cada evento del temporizador avanza pasos durante, como mucho, este tiempo.
    STEP_BUDGET_S = 0.1
    TIMER_INTERVAL_S = 0.05

    directory: StringProperty(  # type: ignore[valid-type]
        name="Project folder", description="The <Name>.gbproj folder", subtype="DIR_PATH"
    )
    filter_folder: BoolProperty(default=True, options={"HIDDEN", "SKIP_SAVE"})  # type: ignore[valid-type]
    read_only: BoolProperty(  # type: ignore[valid-type]
        name="Read-only", description="Open without writing anything in the project",
        default=False, options={"SKIP_SAVE"},
    )
    force_lock: BoolProperty(  # type: ignore[valid-type]
        name="Force the lock", default=False, options={"HIDDEN", "SKIP_SAVE"}
    )
    seen_lock: StringProperty(options={"HIDDEN", "SKIP_SAVE"})  # type: ignore[valid-type]
    accept_migration: BoolProperty(  # type: ignore[valid-type]
        name="Migrate the project", default=False, options={"HIDDEN", "SKIP_SAVE"}
    )
    confirmed: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})  # type: ignore[valid-type]
    notice: StringProperty(options={"HIDDEN", "SKIP_SAVE"})  # type: ignore[valid-type]
    offer_force: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})  # type: ignore[valid-type]
    offer_migration: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})  # type: ignore[valid-type]

    # Entrada ---------------------------------------------------------------------------

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        if not self.directory:
            context.window_manager.fileselect_add(self)
            return {"RUNNING_MODAL"}
        return self.execute(context)

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        if not self.notice:
            layout.prop(self, "read_only", text=tr("Read-only"), translate=False)
            return
        column = layout.column(align=True)
        for line in self.notice.splitlines():
            column.label(text=line, translate=False)
        if self.offer_force:
            layout.prop(self, "force_lock", text=tr("Force the lock"), translate=False)
        if self.offer_migration:
            layout.prop(self, "accept_migration", text=tr("Migrate the project"), translate=False)

    def _prepare_dialog(self, inspection: ProjectInspection) -> None:
        """El texto y las casillas del diálogo de confirmación."""
        lines: list[str] = []
        status = inspection.lock
        self.offer_force = bool(status.can_force and status.holder is not None)
        if self.offer_force and status.holder is not None:
            self.seen_lock = json.dumps(status.holder.to_dict(), ensure_ascii=False)
            lines.append(tr("The lock is stale or reserved: {holder}.", holder=status.describe()))
            lines.append(status.force_warning())
            lines.append(tr("Tick «Force the lock» to open it for writing."))
        self.offer_migration = self._migration_offered(inspection)
        if self.offer_migration and inspection.record is not None:
            backup = backup_path(inspection.root, inspection.record.schema_version)
            lines.append(
                tr(
                    "The project uses schema {old}, older than this version of Geoblender: "
                    "to write to it, it must be migrated.",
                    old=inspection.record.schema_version,
                )
            )
            lines.append(
                tr("A full copy is made first, next to the original: «{backup}».",
                   backup=backup.name)
            )
            lines.append(tr("Tick «Migrate the project» to do it; otherwise it opens read-only."))
        self.notice = "\n".join(lines)

    def _migration_offered(self, inspection: ProjectInspection) -> bool:
        free = inspection.lock.state in (LockState.FREE, LockState.ORPHAN, LockState.OURS)
        return inspection.schema is SchemaRelation.OLDER and free and not self.read_only

    def execute(self, context: bpy.types.Context) -> set[str]:
        path = _folder(self.directory)
        session, userdata = project_session.session(), project_session.userdata()
        stale = project_session.stale_minutes()
        try:
            inspection = inspect_project(path, session, userdata, stale_minutes=stale)
        except GeoblenderError as exc:
            self.report({"ERROR"}, exc.message)
            return {"CANCELLED"}
        needs_confirmation = not self.read_only and (
            inspection.lock.can_force or self._migration_offered(inspection)
        )
        if needs_confirmation and not self.confirmed and not bpy.app.background:
            self.confirmed = True
            self._prepare_dialog(inspection)
            return context.window_manager.invoke_props_dialog(
                self, width=640, translate=False, title=tr("Open project")
            )
        current = project_session.current()
        if current is not None and _same_folder(current.root, path):
            for message in project_session.close():  # se vuelve a abrir el mismo
                self.report({"WARNING"}, message)
        self._start(context, inspection, path, stale)
        return {"RUNNING_MODAL"}

    # Pasos -----------------------------------------------------------------------------

    def _force_holder(self) -> LockInfo | None:
        if not (self.force_lock and self.seen_lock):
            return None
        try:
            return LockInfo.from_dict(json.loads(self.seen_lock))
        except (ValueError, TypeError) as exc:
            LOGGER.warning("Titular del cerrojo visto no válido: %s", exc)
            return None

    def _start(
        self, context: bpy.types.Context, inspection: ProjectInspection, path: Path, stale: int
    ) -> None:
        session, userdata = project_session.session(), project_session.userdata()
        opening = open_steps(
            path,
            session,
            userdata,
            want_write=not self.read_only,
            force_holder=self._force_holder(),
            stale_minutes=stale,
        )
        if self.accept_migration and self._migration_offered(inspection):
            migrating = migrate_steps(
                path, session, userdata, migrations_mod.REGISTRY, stale_minutes=stale
            )
            self._steps: Iterator[Progress] | None = _chain(migrating, opening)
        else:
            self._steps = opening
        self.progress_log: list[tuple[str, str]] = []
        self.report_log: list[str] = []
        self.outcome: str | None = None
        self._extra: list[str] = []
        manager = context.window_manager
        self._timer = manager.event_timer_add(self.TIMER_INTERVAL_S, window=context.window)
        manager.modal_handler_add(self)
        manager.progress_begin(0, 100)

    def _report(self, level: set[str], text: str) -> None:
        self.report(level, text)
        self.report_log.append(text)

    def _show(self, context: bpy.types.Context, step: Progress) -> None:
        self.progress_log.append((step.phase, step.message))
        percent = int(100 * step.done / step.total) if step.total else 0
        context.window_manager.progress_update(max(0, min(100, percent)))
        workspace = context.workspace
        if workspace is not None:
            workspace.status_text_set(
                tr("Opening the project · {phase}: {message}", phase=step.phase,
                   message=step.message)
            )

    def _cleanup(self, context: bpy.types.Context) -> None:
        steps = getattr(self, "_steps", None)
        self._steps = None
        if steps is not None:
            steps.close()  # cancelar: libera el cerrojo si ya se había tomado
        timer = getattr(self, "_timer", None)
        self._timer = None
        manager = context.window_manager
        if timer is not None:
            manager.event_timer_remove(timer)
            manager.progress_end()
        if context.workspace is not None:
            context.workspace.status_text_set(None)

    def _finish(self, context: bpy.types.Context, result: OpenResult) -> set[str]:
        self._steps = None  # terminado: nada que cancelar
        self._cleanup(context)
        closed = project_session.attach(result.project)
        status = result.status
        self._report(
            {"INFO"} if status.writable else {"WARNING"},
            tr("Project «{name}»: {detail}", name=result.project.name, detail=status.message),
        )
        lock: LockStatus | None = result.lock_status
        if not status.writable and lock is not None and lock.can_force:
            self._report(
                {"WARNING"},
                tr(
                    "The lock can be forced from Project ▸ Project lock…: {warning}",
                    warning=lock.force_warning(),
                ),
            )
        for message in (*self._extra, *result.warnings, *closed):
            self._report({"WARNING"}, message)
        self.outcome = "FINISHED"
        return {"FINISHED"}

    def _fail(self, context: bpy.types.Context, message: str) -> set[str]:
        self._cleanup(context)
        self._report({"ERROR"}, message)
        self.outcome = "CANCELLED"
        return {"CANCELLED"}

    def modal(self, context: bpy.types.Context, event: Any) -> set[str]:
        if getattr(self, "_steps", None) is None:
            return {"CANCELLED"}
        if event.type == "ESC":
            self._cleanup(context)
            self._report({"INFO"}, tr("Opening cancelled: no project has been opened"))
            self.outcome = "CANCELLED"
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        started = time.perf_counter()
        try:
            while True:
                step = next(self._steps)  # type: ignore[arg-type]
                self._show(context, step)
                if isinstance(step.result, MigrationResult):
                    self._extra.extend(step.result.warnings)
                    if step.result.backup is not None:
                        self._extra.append(
                            tr(
                                "Project migrated from schema {old} to {new}; prior copy in "
                                "«{backup}»",
                                old=step.result.from_version,
                                new=step.result.to_version,
                                backup=step.result.backup.name,
                            )
                        )
                if isinstance(step.result, OpenResult):
                    return self._finish(context, step.result)
                if time.perf_counter() - started >= self.STEP_BUDGET_S:
                    return {"RUNNING_MODAL"}
        except GeoblenderError as exc:
            return self._fail(context, exc.message)
        except StopIteration:
            return self._fail(
                context, tr("Opening the project did not finish with its result")
            )

    def cancel(self, context: bpy.types.Context) -> None:
        if getattr(self, "_steps", None) is not None:
            self._cleanup(context)


# Cerrar proyecto -----------------------------------------------------------------------


class GEOBLENDER_OT_core_close_project(bpy.types.Operator):
    """Close the project: update its header and release its lock"""

    bl_idname = "geoblender.core_close_project"
    bl_label = "Close project"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        if project_session.current() is None:
            cls.poll_message_set(tr("No project is open"))
            return False
        return True

    def execute(self, context: bpy.types.Context) -> set[str]:
        project = project_session.current()
        if project is None:
            return {"CANCELLED"}
        name = project.name
        warnings = project_session.close()
        self.report({"INFO"}, tr("Project «{name}» closed", name=name))
        for message in warnings:
            self.report({"WARNING"}, message)
        return {"FINISHED"}


# Guardar la vista ----------------------------------------------------------------------

SCENES_DIR = "scenes"
MAIN_VIEW = "principal"


class GEOBLENDER_OT_core_save_project(bpy.types.Operator):
    """Save the view (.blend) with relative paths; a view without a file goes to scenes/principal.blend"""

    bl_idname = "geoblender.core_save_project"
    bl_label = "Save"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        if project_session.current() is None:
            cls.poll_message_set(tr("No project is open"))
            return False
        return True

    def execute(self, context: bpy.types.Context) -> set[str]:
        project = project_session.current()
        if project is None:
            return {"CANCELLED"}
        current = bpy.data.filepath
        if not project.writable and (not current or is_within(current, project.root)):
            self.report(
                {"WARNING"},
                tr(
                    "Project «{name}» is read-only ({status}): the view is not saved in the "
                    "project folder; save it with File ▸ Save As… outside it",
                    name=project.name,
                    status=project.status.message,
                ),
            )
            if not bpy.app.background:
                suggested = project.root.parent / f"{project.name}.blend"
                bpy.ops.wm.save_as_mainfile("INVOKE_DEFAULT", filepath=str(suggested))
            return {"CANCELLED"}
        if current:
            target = Path(current)
        else:
            scenes = project.root / SCENES_DIR
            try:
                scenes.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self.report(
                    {"ERROR"}, tr("Cannot create «{folder}»: {error}", folder=scenes, error=exc)
                )
                return {"CANCELLED"}
            target = next_free_path(scenes, MAIN_VIEW, ".blend")
        try:
            bpy.ops.wm.save_as_mainfile(filepath=str(target), relative_remap=True)
        except RuntimeError as exc:
            self.report(
                {"ERROR"},
                tr("The view could not be saved to «{path}»: {error}", path=target, error=exc),
            )
            return {"CANCELLED"}
        shown = (
            target.relative_to(project.root).as_posix()
            if is_within(target, project.root)
            else str(target)
        )
        self.report({"INFO"}, tr("View saved to «{path}»", path=shown))
        for message in project_session.take_notices():
            self.report({"WARNING"}, message)
        return {"FINISHED"}


# Cerrojo del proyecto ------------------------------------------------------------------


class GEOBLENDER_OT_core_show_lock(bpy.types.Operator):
    """Who holds the project lock; force a stale or reserved lock after confirming"""

    bl_idname = "geoblender.core_show_lock"
    bl_label = "Project lock…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    force: BoolProperty(  # type: ignore[valid-type]
        name="Force the lock", default=False, options={"SKIP_SAVE"}
    )
    seen_lock: StringProperty(options={"HIDDEN", "SKIP_SAVE"})  # type: ignore[valid-type]
    notice: StringProperty(options={"HIDDEN", "SKIP_SAVE"})  # type: ignore[valid-type]
    offer_force: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        if project_session.current() is None:
            cls.poll_message_set(tr("No project is open"))
            return False
        return True

    @staticmethod
    def _status() -> LockStatus | None:
        project = project_session.current()
        if project is None:
            return None
        return inspect_lock(
            project.root, project_session.session(),
            stale_minutes=project_session.stale_minutes(),
        )

    @staticmethod
    def _describe(status: LockStatus) -> str:
        if status.state is LockState.OURS and status.holder is not None:
            holder = status.holder
            return tr("this session holds it ({user} on {host})", user=holder.user,
                      host=holder.host)
        return status.describe()

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        status = self._status()
        if status is None:
            return {"CANCELLED"}
        lines = [tr("Lock: {holder}.", holder=self._describe(status))]
        self.offer_force = bool(status.can_force and status.holder is not None)
        if self.offer_force and status.holder is not None:
            self.seen_lock = json.dumps(status.holder.to_dict(), ensure_ascii=False)
            lines.append(status.force_warning())
        self.notice = "\n".join(lines)
        return context.window_manager.invoke_props_dialog(
            self, width=640, translate=False, title=tr("Project lock")
        )

    def draw(self, context: bpy.types.Context) -> None:
        column = self.layout.column(align=True)
        for line in self.notice.splitlines():
            column.label(text=line, translate=False)
        if self.offer_force:
            self.layout.prop(self, "force", text=tr("Force the lock"), translate=False)

    def execute(self, context: bpy.types.Context) -> set[str]:
        project = project_session.current()
        status = self._status()
        if project is None or status is None:
            return {"CANCELLED"}
        if not self.force:
            self.report(
                {"INFO"},
                tr("Project «{name}»: {detail}", name=project.name,
                   detail=self._describe(status)),
            )
            return {"FINISHED"}
        if not status.can_force:
            self.report(
                {"WARNING"},
                tr("The lock of «{name}» cannot be forced: {holder}", name=project.name,
                   holder=self._describe(status)),
            )
            return {"CANCELLED"}
        if not self.seen_lock:
            self.report(
                {"ERROR"},
                tr(
                    "To force the lock you must first see who holds it: open Project ▸ "
                    "Project lock… and confirm"
                ),
            )
            return {"CANCELLED"}
        root = project.root
        for message in project_session.close():
            self.report({"WARNING"}, message)
        bpy.ops.geoblender.core_open_project(
            "EXEC_DEFAULT",
            directory=str(root),
            force_lock=True,
            seen_lock=self.seen_lock,
            confirmed=True,
        )
        return {"FINISHED"}


# Sistema de referencia, GeoOrigin y ventana de trabajo --------------------------------

def _metres(value: float) -> str:
    """Un número en metros en el formato del idioma: sin decimales si es entero; si no,
    con los que tenga, hasta milímetros (``700 000``, ``4 400 500,9``)."""
    if float(value).is_integer():
        return format_number(value, 0)
    decimals = len(f"{value:.3f}".rstrip("0").partition(".")[2])
    return format_number(value, decimals)


def _typed(value: float) -> str:
    """Un número para volver a teclearlo en un diálogo (coma decimal, sin miles)."""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.3f}".rstrip("0").replace(".", ",")


def crs_lines(project: Any) -> list[str]:
    """El CRS horizontal y vertical del proyecto (de su cabecera, que coincide con la
    base), en español."""
    header = project.manifest
    lines = [tr("Horizontal CRS: EPSG:{code} · {name}", code=header.crs_epsg,
                name=header.crs_name)]
    if header.vcrs_epsg is None:
        lines.append(tr("Vertical CRS: local reference · {note}", note=header.vcrs_note or ""))
    else:
        lines.append(tr("Vertical CRS: EPSG:{code} · {name}", code=header.vcrs_epsg,
                        name=header.vcrs_name))
    return lines


def origin_lines(project: Any) -> list[str]:
    """El GeoOrigin, la ventana de trabajo y el paso de rejilla del proyecto, en
    español; sin ventana si solo se pudo leer la cabecera."""
    origin = project.origin
    lines = [tr("GeoOrigin: {xyz} m", xyz=format_xyz(origin.x0, origin.y0, origin.z0, 0))]
    window = project.window
    if window is None:
        lines.append(tr("Work window: not available (only the header could be read)"))
    else:
        lines.append(
            tr(
                "Work window: X {xmin} – {xmax}, Y {ymin} – {ymax} m",
                xmin=_metres(window.xmin), xmax=_metres(window.xmax),
                ymin=_metres(window.ymin), ymax=_metres(window.ymax),
            )
        )
    lines.append(tr("Grid step: {step} m", step=format_number(project.grid_step_m, 1)))
    return lines


def _poll_project(cls: type, context: bpy.types.Context) -> bool:
    if project_session.current() is None:
        cls.poll_message_set(tr("No project is open"))  # type: ignore[attr-defined]
        return False
    return True


class GEOBLENDER_OT_core_set_crs(bpy.types.Operator):
    """Coordinate reference system of the project (horizontal and vertical)"""

    bl_idname = "geoblender.core_set_crs"
    bl_label = "Coordinate reference system…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return _poll_project(cls, context)

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        return context.window_manager.invoke_props_dialog(
            self, width=520, translate=False, title=tr("Coordinate reference system")
        )

    def draw(self, context: bpy.types.Context) -> None:
        project = project_session.current()
        column = self.layout.column(align=True)
        for line in crs_lines(project) if project is not None else ():
            column.label(text=line, translate=False)
        column.label(
            text=tr("Changing the CRS of a project with data will come later (R-79)"),
            translate=False,
        )

    def execute(self, context: bpy.types.Context) -> set[str]:
        project = project_session.current()
        if project is None:
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            tr("Project «{name}»: {detail}", name=project.name, detail="; ".join(crs_lines(project))),
        )
        return {"FINISHED"}


class GEOBLENDER_OT_core_show_geoorigin(bpy.types.Operator):
    """Local origin (GeoOrigin) of the project: whole metres, read-only"""

    bl_idname = "geoblender.core_show_geoorigin"
    bl_label = "Local origin (GeoOrigin)…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return _poll_project(cls, context)

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        return context.window_manager.invoke_props_dialog(
            self, width=520, translate=False, title=tr("Local origin (GeoOrigin)")
        )

    def draw(self, context: bpy.types.Context) -> None:
        project = project_session.current()
        column = self.layout.column(align=True)
        for line in origin_lines(project) if project is not None else ():
            column.label(text=line, translate=False)

    def execute(self, context: bpy.types.Context) -> set[str]:
        project = project_session.current()
        if project is None:
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            tr("Project «{name}»: {detail}", name=project.name,
               detail="; ".join(origin_lines(project))),
        )
        return {"FINISHED"}


class GEOBLENDER_OT_core_set_work_window(bpy.types.Operator):
    """Change the work window and, with it, the GeoOrigin (a reason is required)"""

    bl_idname = "geoblender.core_set_work_window"
    bl_label = "Work window and grid…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    xmin: StringProperty(name="X min (m)")  # type: ignore[valid-type]
    ymin: StringProperty(name="Y min (m)")  # type: ignore[valid-type]
    xmax: StringProperty(name="X max (m)")  # type: ignore[valid-type]
    ymax: StringProperty(name="Y max (m)")  # type: ignore[valid-type]
    grid_step: EnumProperty(  # type: ignore[valid-type]
        name="Grid step", items=GRID_STEP_ITEMS, default="1.0"
    )
    z0: IntProperty(name="Z0 (m)", default=0)  # type: ignore[valid-type]
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason", description="Why the window changes (recorded with the change)"
    )

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        if not _poll_project(cls, context):
            return False
        project = project_session.current()
        if project is not None and not project.writable:
            cls.poll_message_set(tr("Read-only project: {reason}", reason=project.status.message))
            return False
        return True

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        project = project_session.current()
        if project is not None and project.window is not None:
            window = project.window
            self.xmin, self.ymin = _typed(window.xmin), _typed(window.ymin)
            self.xmax, self.ymax = _typed(window.xmax), _typed(window.ymax)
            self.grid_step = f"{project.grid_step_m:.1f}"
            self.z0 = project.origin.z0
        return context.window_manager.invoke_props_dialog(
            self, width=560, translate=False, title=tr("Work window and grid")
        )

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        _draw_window_fields(layout, self)
        layout.prop(self, "reason", text=tr("Reason"), translate=False)
        layout.label(
            text=tr("The stored coordinates do not change; the views will be out of date"),
            translate=False,
        )

    def execute(self, context: bpy.types.Context) -> set[str]:
        project = project_session.current()
        if project is None:
            return {"CANCELLED"}
        previous = project.origin
        try:
            window = tuple(
                parse_decimal(getattr(self, corner), obj=tr("Work window"), field=corner)
                for corner in _CORNERS
            )
            origin = project.set_window(
                window, float(self.grid_step), int(self.z0), self.reason
            )
        except GeoblenderError as exc:
            self.report({"ERROR"}, exc.message)
            return {"CANCELLED"}
        georef.sync_scenes(project)
        if origin != previous:
            georef.mark_stale()
        self.report(
            {"INFO"},
            tr(
                "Project «{name}»: GeoOrigin {old} → {new}; the views are out of date",
                name=project.name,
                old=format_xyz(previous.x0, previous.y0, previous.z0, 0),
                new=format_xyz(origin.x0, origin.y0, origin.z0, 0),
            ),
        )
        window_now = project.window
        if window_now is not None:
            precision = precision_report(window_now, origin)
            if not precision.within_limit:
                project_session.notify(precision.message)
                self.report({"WARNING"}, precision.message)
        return {"FINISHED"}


# Avisos -------------------------------------------------------------------------------


class GEOBLENDER_OT_core_clear_notices(bpy.types.Operator):
    """Dismiss the pending notices of the project"""

    bl_idname = "geoblender.core_clear_notices"
    bl_label = "Dismiss notices"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"INTERNAL"}

    def execute(self, context: bpy.types.Context) -> set[str]:
        project_session.take_notices()
        return {"FINISHED"}


# En orden de registro.
classes: tuple[type, ...] = (
    GEOBLENDER_OT_core_new_project,
    GEOBLENDER_OT_core_open_project,
    GEOBLENDER_OT_core_close_project,
    GEOBLENDER_OT_core_save_project,
    GEOBLENDER_OT_core_show_lock,
    GEOBLENDER_OT_core_set_crs,
    GEOBLENDER_OT_core_show_geoorigin,
    GEOBLENDER_OT_core_set_work_window,
    GEOBLENDER_OT_core_clear_notices,
)
