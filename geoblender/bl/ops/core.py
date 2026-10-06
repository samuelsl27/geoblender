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
- ``geoblender.core_show_lock`` (RF-002-09, RF-002-10): quién tiene el cerrojo y, si está
  caducado o reservado, forzarlo con confirmación.

Sin ``UNDO`` en ``bl_options``: solo escriben en el proyecto y no crean objetos de la
vista, y Ctrl+Z no puede deshacer el proyecto (regla provisional de R-10). No calculan:
validan la entrada, llaman a ``core`` y presentan el resultado. Los mensajes al usuario,
en español con objeto, campo y valor (los de ``core`` ya lo son); la traza, al registro.

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
from ...core.numbers import parse_decimal
from ...core.project import migrations as migrations_mod
from ...core.project.create import create_project
from ...core.project.lock import LockInfo, LockState, LockStatus
from ...core.project.lock import inspect as inspect_lock
from ...core.project.migrations import MigrationResult, backup_path, migrate_steps
from ...core.project.model import OpenResult, ProjectSettings, Progress
from ...core.project.open import ProjectInspection, SchemaRelation, inspect_project, open_steps
from ..scene import project_session

LOGGER = logging.getLogger("geoblender.bl.ops")
TRANSLATION_CONTEXT = "Geoblender"
LOCAL_VERTICAL_ID = "LOCAL"
_WINDOW_OBJ = "Ventana de trabajo"
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
        (LOCAL_VERTICAL_ID, "Local reference", "Elevations referred to a local datum")
    )
    return items


GRID_STEP_ITEMS: list[tuple[str, str, str]] = [
    (f"{step:.1f}", f"{step:g} m", "") for step in (0.5 * n for n in range(1, 11))
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
        return context.window_manager.invoke_props_dialog(self, width=560)

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "directory")
        layout.prop(self, "name")
        layout.prop(self, "crs_epsg")
        layout.prop(self, "vcrs")
        if self.vcrs == LOCAL_VERTICAL_ID:
            layout.prop(self, "vcrs_note")
        column = layout.column(align=True)
        for corner in _CORNERS:
            column.prop(self, corner)
        layout.prop(self, "grid_step")
        layout.prop(self, "z0")

    def settings(self) -> ProjectSettings:
        """Los ajustes del diálogo; :class:`ValidationError` si un número no lo es."""
        window = tuple(
            parse_decimal(getattr(self, corner), obj=_WINDOW_OBJ, field=corner)
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
                    "elija la carpeta donde se creará el proyecto",
                    obj="Proyecto nuevo",
                    field="carpeta",
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
            f"Proyecto «{result.record.name}» creado: {result.project.status.message}",
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
            layout.prop(self, "read_only")
            return
        column = layout.column(align=True)
        for line in self.notice.splitlines():
            column.label(text=line, translate=False)
        if self.offer_force:
            layout.prop(self, "force_lock")
        if self.offer_migration:
            layout.prop(self, "accept_migration")

    def _prepare_dialog(self, inspection: ProjectInspection) -> None:
        """El texto y las casillas del diálogo de confirmación."""
        lines: list[str] = []
        status = inspection.lock
        self.offer_force = bool(status.can_force and status.holder is not None)
        if self.offer_force and status.holder is not None:
            self.seen_lock = json.dumps(status.holder.to_dict(), ensure_ascii=False)
            lines.append(f"El cerrojo está caducado o reservado: {status.describe()}.")
            lines.append(status.force_warning())
            lines.append("Marque «Forzar el cerrojo» para abrirlo en escritura.")
        self.offer_migration = self._migration_offered(inspection)
        if self.offer_migration and inspection.record is not None:
            backup = backup_path(inspection.root, inspection.record.schema_version)
            lines.append(
                f"El proyecto es del esquema {inspection.record.schema_version}, anterior al de "
                "esta versión de Geoblender: para escribir en él hay que migrarlo."
            )
            lines.append(f"Antes se hará una copia completa junto al original: «{backup.name}».")
            lines.append("Marque «Migrar el proyecto» para hacerlo; si no, se abre en solo lectura.")
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
            return context.window_manager.invoke_props_dialog(self, width=640)
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
            workspace.status_text_set(f"Abriendo el proyecto · {step.phase}: {step.message}")

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
            f"Proyecto «{result.project.name}»: {status.message}",
        )
        lock: LockStatus | None = result.lock_status
        if not status.writable and lock is not None and lock.can_force:
            self._report(
                {"WARNING"},
                "Se puede forzar el cerrojo desde Proyecto ▸ Cerrojo del proyecto…: "
                + lock.force_warning(),
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
            self._report({"INFO"}, "Apertura cancelada: no se ha abierto ningún proyecto")
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
                            f"Proyecto migrado del esquema {step.result.from_version} al "
                            f"{step.result.to_version}; copia previa en «{step.result.backup.name}»"
                        )
                if isinstance(step.result, OpenResult):
                    return self._finish(context, step.result)
                if time.perf_counter() - started >= self.STEP_BUDGET_S:
                    return {"RUNNING_MODAL"}
        except GeoblenderError as exc:
            return self._fail(context, exc.message)
        except StopIteration:
            return self._fail(context, "La apertura del proyecto no ha terminado con su resultado")

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
            cls.poll_message_set("No hay ningún proyecto abierto")
            return False
        return True

    def execute(self, context: bpy.types.Context) -> set[str]:
        project = project_session.current()
        if project is None:
            return {"CANCELLED"}
        name = project.name
        warnings = project_session.close()
        self.report({"INFO"}, f"Proyecto «{name}» cerrado")
        for message in warnings:
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
            cls.poll_message_set("No hay ningún proyecto abierto")
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
            return f"lo tiene esta sesión ({holder.user} en {holder.host})"
        return status.describe()

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        status = self._status()
        if status is None:
            return {"CANCELLED"}
        lines = [f"Cerrojo: {self._describe(status)}."]
        self.offer_force = bool(status.can_force and status.holder is not None)
        if self.offer_force and status.holder is not None:
            self.seen_lock = json.dumps(status.holder.to_dict(), ensure_ascii=False)
            lines.append(status.force_warning())
        self.notice = "\n".join(lines)
        return context.window_manager.invoke_props_dialog(self, width=640)

    def draw(self, context: bpy.types.Context) -> None:
        column = self.layout.column(align=True)
        for line in self.notice.splitlines():
            column.label(text=line, translate=False)
        if self.offer_force:
            self.layout.prop(self, "force")

    def execute(self, context: bpy.types.Context) -> set[str]:
        project = project_session.current()
        status = self._status()
        if project is None or status is None:
            return {"CANCELLED"}
        if not self.force:
            self.report({"INFO"}, f"Proyecto «{project.name}»: {self._describe(status)}")
            return {"FINISHED"}
        if not status.can_force:
            self.report(
                {"WARNING"},
                f"No se puede forzar el cerrojo de «{project.name}»: {self._describe(status)}",
            )
            return {"CANCELLED"}
        if not self.seen_lock:
            self.report(
                {"ERROR"},
                "Para forzar el cerrojo hay que ver antes quién lo tiene: abra "
                "Proyecto ▸ Cerrojo del proyecto… y confirme",
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


# En orden de registro.
classes: tuple[type, ...] = (
    GEOBLENDER_OT_core_new_project,
    GEOBLENDER_OT_core_open_project,
    GEOBLENDER_OT_core_close_project,
    GEOBLENDER_OT_core_show_lock,
)
