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
- ``geoblender.core_checkout_project`` (RF-002-31) y ``geoblender.core_publish_project``
  (RF-002-32, RF-002-33): **modales** que avanzan ``checkout_steps`` y ``publish_steps``
  (copias de carpetas enteras: un trozo de 8 MiB por paso, progreso en la barra de estado
  y Esc cancela, RNF-002-06). Sacar la copia cierra antes el proyecto de la sesión (para
  reservarlo) y deja abierta la copia; si se cancela o falla, vuelve a abrir el original.
  Publicar deja abierto el publicado (si se pide); si no se puede, la copia sigue abierta.

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

Vista (spec 006, T27; RF-006-19, RF-006-20, RF-006-22, RF-006-29; plan 006 §5.3.5 y §5.6.7):
``geoblender.core_load_into_view`` (un diálogo con los datos del proyecto que algún módulo sabe
cargar y el nivel de detalle; por script, ``datasets`` con sus nombres o uids separados por
comas) y ``geoblender.core_unload_from_view`` (los datos de los objetos seleccionados, o los de
``datasets``) cargan y descargan con ``bl.scene.views``. Son los únicos de este módulo con
``UNDO``: crean o quitan objetos de la vista y no escriben en el proyecto (Ctrl+Z deshace solo la
vista). Un aviso o un error de un dato no impide cargar los demás. Desde la interfaz (``invoke``:
el menú y el diálogo), cargar es un modal (T50; RNF-006-09, RNF-006-06): avanza los pasos de
``bl.scene.views.load_steps`` desde el temporizador de su ventana, unas décimas de segundo como
mucho por evento, con su avance en la barra de estado, y Esc lo cancela sin dejar nada en la
vista; desde un guion (``EXEC_DEFAULT``), de una vez.

Transformar coordenadas (spec 006, T32; RF-006-07, RF-006-31; plan 006 §5.3.5):
``geoblender.core_transform_coordinates`` (Proyecto ▸ Georreferencia ▸ Transformar
coordenadas…) transforma coordenadas tecleadas (:func:`typed_coordinates`: un punto por línea o
separados por «;», ``X Y [Z]`` con coma o punto decimal) entre dos CRS del catálogo y sus
referencias verticales (o la altura elipsoidal ETRS89) con ``gis.crs.transform_coordinates`` y
el servicio de CRS de las órdenes (``bl.ops.gis.crs_resolver``), y muestra cada punto con 1 mm,
la transformación usada y su precisión, y el factor de escala y la convergencia de cuadrícula en
el destino (:func:`transform_lines`), en un diálogo con «Copiar al portapapeles» y en el registro.
No necesita proyecto ni escribe en él (no es una operación de la 008); con uno abierto, el
destino es su CRS. Sin el servicio de CRS (otra versión de pyproj), no se abre y dice por qué.

Carpetas de solo lectura (spec 008, T48; RF-008-15; S-3; plan 008 §5.4.13): crear, abrir (e
inspeccionar), migrar, sacar copia y publicar reciben las de ahora
(``bl.ops.core_provenance.read_only_dirs``: la variable ``GEOBLENDER_READ_ONLY_DIRS`` y la
preferencia): crear, sacar copia o publicar dentro de una se rechaza nombrándola, y un
proyecto que está dentro se abre en solo lectura, sin cerrojo ni migración.
"""

from __future__ import annotations

import json
import logging
import re
import time
import weakref
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import bpy
import numpy as np
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    StringProperty,
)

from ...core.errors import GeoblenderError, ValidationError
from ...core.georef.crs import DEFAULT_HORIZONTAL_EPSG, DEFAULT_VERTICAL_EPSG, load_catalog
from ...core.georef.transform import precision_report
from ...core.i18n import format_number, format_xyz, tr
from ...core.numbers import parse_decimal
from ...core.paths import is_within, next_free_path
from ...core.project import migrations as migrations_mod
from ...core.project.checkout import (
    CheckoutResult,
    PublishResult,
    checkout_steps,
    publish_steps,
)
from ...core.project.create import create_project
from ...core.project.lock import LockInfo, LockState, LockStatus
from ...core.project.lock import inspect as inspect_lock
from ...core.project.migrations import MigrationResult, backup_path, migrate_steps
from ...core.project.model import OpenResult, ProjectSettings, Progress, ReadOnlyCode
from ...core.project.open import ProjectInspection, SchemaRelation, inspect_project, open_steps
from ..props.core import OBJECT_PROPERTY, GEOBLENDER_PG_core_view_dataset
from ..scene import georef, project_session, views
from .core_provenance import error_text, read_only_dirs

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
                read_only=read_only_dirs(),
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
        # Los avisos de la ventana (huso extendido, RF-002-03 y D-12; precisión, RF-002-26)
        # quedan también para la pestaña «Proyecto»; los de cerrar el anterior ya los dejó
        # project_session.close.
        for message in result.warnings:
            project_session.notify(message)
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
            lines.append(
                tr("It is migrated to schema {new}, which also saves the appearance of the elements; "
                   "an earlier Geoblender will not be able to open it.", new=migrations_mod.SCHEMA_VERSION)
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
            inspection = inspect_project(path, session, userdata, stale_minutes=stale,
                                         read_only=read_only_dirs())
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
        read_only = read_only_dirs()
        opening = open_steps(
            path,
            session,
            userdata,
            want_write=not self.read_only,
            force_holder=self._force_holder(),
            stale_minutes=stale,
            read_only=read_only,
        )
        if self.accept_migration and self._migration_offered(inspection):
            migrating = migrate_steps(
                path, session, userdata, migrations_mod.REGISTRY, stale_minutes=stale,
                read_only=read_only,
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

SCENES_DIR = georef.SCENES_DIR  # las vistas del proyecto
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
        # P. ej., la cabecera no se pudo escribir tras guardar el origen en la base: el
        # proyecto pasa a solo lectura y lo dice (RF-002-12; convergencia, T40).
        for message in project.take_notices():
            project_session.notify(message)
            self.report({"WARNING"}, message)
        window_now = project.window
        if window_now is not None:
            precision = precision_report(window_now, origin)
            if not precision.within_limit:
                project_session.notify(precision.message)
                self.report({"WARNING"}, precision.message)
        return {"FINISHED"}


# Transformar coordenadas (spec 006, T32) ------------------------------------------------

ELLIPSOIDAL_ID = "ELLIPSOIDAL"
_SOURCE_DEFAULT = "23030" if any(item[0] == "23030" for item in HORIZONTAL_ITEMS) else (
    HORIZONTAL_ITEMS[0][0])
_POINT_BREAKS = re.compile(r"[;\r\n]+")
_LAST_TRANSFORM: list[str] = []
_COORDINATES_DESCRIPTION = ("One point per line, or points separated by «;»: X Y or X Y Z "
                            "separated by spaces, with decimal comma or point")


def _transform_vertical_items() -> list[tuple[str, str, str]]:
    items = [
        (str(ref.epsg), f"EPSG:{ref.epsg} · {ref.name}", ref.name)
        for ref in load_catalog().verticals()
        if ref.epsg is not None
    ]
    items.append((ELLIPSOIDAL_ID, "ETRS89 ellipsoidal height", "GNSS or drone without geoid"))
    return items


TRANSFORM_VERTICAL_ITEMS = _transform_vertical_items()


def _vertical_of(choice: str) -> Any:
    """La referencia vertical elegida: una del catálogo o la altura elipsoidal ETRS89."""
    from ...gis.crs import ELLIPSOIDAL_ETRS89

    if choice == ELLIPSOIDAL_ID:
        return ELLIPSOIDAL_ETRS89
    return load_catalog().vertical(int(choice))


def typed_coordinates(text: str) -> tuple[np.ndarray, list[bool]]:
    """Las coordenadas tecleadas (RF-006-07): un punto por línea o separados por «;», cada uno
    ``X Y`` o ``X Y Z`` separados por espacios, con coma o punto decimal; en float64 (n, 3)
    ABSOLUTAS (Z = 0 si no se tecleó) y, por punto, si se tecleó Z. ``ValueError`` (en el
    idioma de Geoblender) sin puntos o con un punto sin X e Y; ``ValidationError`` de
    ``core.numbers`` con un número mal escrito (el punto y el eje)."""
    lines = [line.strip() for line in _POINT_BREAKS.split(str(text)) if line.strip()]
    if not lines:
        raise ValueError(tr("Type the coordinates: X Y or X Y Z, one point per line or "
                            "separated by «;»"))
    rows: list[list[float]] = []
    with_z: list[bool] = []
    for index, line in enumerate(lines, start=1):
        parts = line.split()
        if len(parts) not in (2, 3):
            raise ValueError(tr("Point {index} «{text}»: write X Y or X Y Z separated by spaces, "
                                "with decimal comma or point", index=index, text=line))
        point = tr("Point {index}", index=index)
        values = [parse_decimal(part, obj=point, field=axis)
                  for axis, part in zip("XYZ", parts, strict=False)]
        with_z.append(len(values) == 3)
        rows.append(values if len(values) == 3 else [*values, 0.0])
    return np.array(rows, dtype=np.float64), with_z


def _point_text(xyz: np.ndarray, with_z: bool) -> str:
    """Un punto con 1 mm, con su Z si se tecleó."""
    text = format_xyz(float(xyz[0]), float(xyz[1]), float(xyz[2]), 3)
    return text if with_z else text.rsplit("  ", 1)[0]


def transform_lines(result: Any, typed: np.ndarray, with_z: list[bool], source: str,
                    target: str) -> list[str]:
    """El resultado de RF-006-07 en el idioma de Geoblender: los dos CRS, la transformación
    usada y su precisión, y cada punto tecleado y transformado (1 mm) con el factor de escala
    y la convergencia de cuadrícula en el destino."""
    from ...gis.crs import transform_summary

    lines = [tr("Coordinates from {source} to {target}", source=source, target=target),
             tr("Transformation: {summary}", summary=transform_summary(result.info))]
    for index, row in enumerate(typed):
        lines.append(tr(
            "Point {index}: {typed} → {result} m; scale factor {scale}; convergence "
            "{convergence}°", index=index + 1, typed=_point_text(row, with_z[index]),
            result=_point_text(result.xyz[index], with_z[index]),
            scale=format_number(float(result.scale_factor[index]), 9),
            convergence=format_number(float(result.convergence_deg[index]), 6)))
    lines.append(tr("Scale factor and grid convergence in {target}; the convergence in degrees, "
                    "positive east of the central meridian", target=target))
    return lines


def last_transform() -> list[str]:
    """Las líneas de la última transformación hecha en la sesión (lo que copia «Copiar»)."""
    return list(_LAST_TRANSFORM)


def _crs_resolver() -> Any:
    """El servicio de CRS de las órdenes (``bl.ops.gis.crs_resolver``: las pruebas lo
    cambian; ``None``, el del registro de adaptadores)."""
    from . import gis as gis_ops

    return gis_ops.crs_resolver


def _draw_transform(menu: Any, context: bpy.types.Context) -> None:
    column = menu.layout.column(align=True)
    for line in _LAST_TRANSFORM:
        column.label(text=line, translate=False)
    props = menu.layout.operator(GEOBLENDER_OT_core_transform_coordinates.bl_idname,
                                 text=tr("Copy to the clipboard"), icon="COPYDOWN",
                                 translate=False)
    props.copy = True


class GEOBLENDER_OT_core_transform_coordinates(bpy.types.Operator):
    """Between reference systems: ED50 to ETRS89, UTM zones"""

    bl_idname = "geoblender.core_transform_coordinates"
    bl_label = "Transform coordinates…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    source_crs: EnumProperty(  # type: ignore[valid-type]
        name="Source CRS", description="Horizontal CRS of the typed coordinates",
        items=HORIZONTAL_ITEMS, default=_SOURCE_DEFAULT,
    )
    source_vertical: EnumProperty(  # type: ignore[valid-type]
        name="Source vertical CRS", description="Vertical reference of the typed elevations",
        items=TRANSFORM_VERTICAL_ITEMS, default=str(DEFAULT_VERTICAL_EPSG),
    )
    target_crs: EnumProperty(  # type: ignore[valid-type]
        name="Target CRS", description="Horizontal CRS of the result",
        items=HORIZONTAL_ITEMS, default=str(DEFAULT_HORIZONTAL_EPSG),
    )
    target_vertical: EnumProperty(  # type: ignore[valid-type]
        name="Target vertical CRS", description="Vertical reference of the result",
        items=TRANSFORM_VERTICAL_ITEMS, default=str(DEFAULT_VERTICAL_EPSG),
    )
    text: StringProperty(  # type: ignore[valid-type]
        name="Coordinates", description=_COORDINATES_DESCRIPTION,
    )
    copy: BoolProperty(  # type: ignore[valid-type]
        name="Copy", default=False, options={"HIDDEN", "SKIP_SAVE"},
    )

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        from ...gis.crs import crs_service_status

        if self.copy:
            return self.execute(context)
        status = crs_service_status(_crs_resolver())  # RF-006-31: sin servicio, no se abre
        if status.error is not None:
            self.report({"ERROR"}, error_text(status.error))
            return {"CANCELLED"}
        project = project_session.current()
        if project is not None and not self.properties.is_property_set("target_crs"):
            header = project.manifest
            if any(item[0] == str(header.crs_epsg) for item in HORIZONTAL_ITEMS):
                self.target_crs = str(header.crs_epsg)
            if any(item[0] == str(header.vcrs_epsg) for item in TRANSFORM_VERTICAL_ITEMS):
                self.target_vertical = str(header.vcrs_epsg)
        return context.window_manager.invoke_props_dialog(
            self, width=560, translate=False, title=tr("Transform coordinates"),
            confirm_text=tr("Transform"),
        )

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        for prop, label in (("source_crs", tr("Source CRS")),
                            ("source_vertical", tr("Source vertical CRS")),
                            ("target_crs", tr("Target CRS")),
                            ("target_vertical", tr("Target vertical CRS")),
                            ("text", tr("Coordinates"))):
            layout.prop(self, prop, text=label, translate=False)
        layout.label(text=tr("One point per line, or points separated by «;»: X Y or X Y Z "
                             "separated by spaces, with decimal comma or point"), translate=False)

    def execute(self, context: bpy.types.Context) -> set[str]:
        from ...gis.crs import reference_label, require_crs_service, transform_coordinates

        if self.copy:
            if not _LAST_TRANSFORM:
                self.report({"WARNING"}, tr("There are no transformed coordinates to copy"))
                return {"CANCELLED"}
            context.window_manager.clipboard = "\n".join(_LAST_TRANSFORM)
            self.report({"INFO"}, tr("Transformed coordinates copied to the clipboard"))
            return {"FINISHED"}
        catalog = load_catalog()
        src, dst = catalog.horizontal(int(self.source_crs)), catalog.horizontal(
            int(self.target_crs))
        src_v, dst_v = _vertical_of(self.source_vertical), _vertical_of(self.target_vertical)
        try:
            service = require_crs_service(_crs_resolver())  # RF-006-31, antes que lo tecleado
            typed, with_z = typed_coordinates(self.text)
            result = transform_coordinates(typed, src, src_v, dst, dst_v, service=service)
        except (GeoblenderError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        lines = transform_lines(result, typed, with_z, reference_label(src, src_v),
                                reference_label(dst, dst_v))
        _LAST_TRANSFORM[:] = lines
        text = "\n".join(lines)
        LOGGER.info("Coordenadas transformadas:\n%s", text)
        self.report({"INFO"}, text)
        manager = context.window_manager
        if not bpy.app.background and manager is not None and manager.windows:
            manager.popup_menu(_draw_transform, title=tr("Transformed coordinates"),
                               icon="INFO")
        return {"FINISHED"}


# Copia local y publicación -------------------------------------------------------------


_RUNNING: list[weakref.ref[Any]] = []
"""Los modales de pasos en curso (:class:`_StepsModal`), en el orden en que empezaron: al
desactivar Geoblender, :func:`cancel_running` los cancela antes de quitar las clases (spec 009,
T40). Referencias débiles: mientras corre, el modal lo retiene Blender."""


class _StepsModal:
    """Lo común de los modales que avanzan un generador de pasos de ``core`` (copia local
    y publicación): cada evento del temporizador (cada 0,05 s) avanza pasos durante, como
    mucho, 0,1 s y actualiza el progreso; cada paso es un trozo de 8 MiB, así que el
    progreso se mueve en mucho menos de 1 s también en red; Esc cierra el generador, que
    cancela (RNF-002-06). ``progress_log`` guarda (hora, fase, hecho, total, mensaje) de
    cada paso y ``report_log``, lo que se informó. Mientras corre está entre los modales en
    curso (:func:`running_step_modals`), que se cancelan como con Esc al desactivar
    Geoblender (:func:`cancel_running`; spec 009, T40)."""

    STEP_BUDGET_S = 0.1
    TIMER_INTERVAL_S = 0.05

    def _start(self, context: bpy.types.Context, steps: Iterator[Progress]) -> None:
        self._steps: Iterator[Progress] | None = steps
        self.progress_log: list[tuple[float, str, int, int, str]] = []
        self.report_log: list[str] = []
        self.outcome: str | None = None
        manager = context.window_manager
        self._timer = manager.event_timer_add(self.TIMER_INTERVAL_S, window=context.window)
        manager.modal_handler_add(self)
        manager.progress_begin(0, 100)
        # Su ventana, por su dirección (no se guarda la ventana: se puede cerrar).
        window = getattr(context, "window", None)
        self._window_key = 0 if window is None else window.as_pointer()
        _RUNNING.append(weakref.ref(self))

    def _report(self, level: set[str], text: str) -> None:
        self.report(level, text)  # type: ignore[attr-defined]
        if hasattr(self, "report_log"):
            self.report_log.append(text)

    def _status_text(self, step: Progress) -> str:
        raise NotImplementedError

    def _cancelled_text(self) -> str:
        raise NotImplementedError

    def _result(self, context: bpy.types.Context, step: Progress) -> set[str] | None:
        """Lo que hace con el resultado de un paso; ``None`` si hay que seguir."""
        raise NotImplementedError

    def _after_stop(self, context: bpy.types.Context) -> None:
        """Tras cancelar o fallar (por defecto, nada)."""

    def _error_text(self, exc: GeoblenderError) -> str:
        """El texto de un error de los pasos para el usuario (por defecto, su mensaje)."""
        return exc.message

    def _show(self, context: bpy.types.Context, step: Progress) -> None:
        self.progress_log.append(
            (time.perf_counter(), step.phase, step.done, step.total, step.message)
        )
        percent = int(100 * step.done / step.total) if step.total else 0
        context.window_manager.progress_update(max(0, min(100, percent)))
        if context.workspace is not None:
            context.workspace.status_text_set(self._status_text(step))

    def _cleanup(self, context: bpy.types.Context) -> None:
        _forget(self)
        steps = getattr(self, "_steps", None)
        self._steps = None
        if steps is not None:
            steps.close()  # cancelar: core no deja nada a medias
        timer = getattr(self, "_timer", None)
        self._timer = None
        manager = context.window_manager
        if timer is not None:
            manager.event_timer_remove(timer)
            manager.progress_end()
        if context.workspace is not None:
            context.workspace.status_text_set(None)

    def _stop(self, context: bpy.types.Context, *, after: bool = True) -> set[str]:
        """Cancela como Esc: cierra los pasos (``core`` no deja nada a medias), quita el
        temporizador, el avance y el texto de la barra de estado y dice que se canceló; con
        ``after``, lo de después de parar (:meth:`_after_stop`)."""
        self._cleanup(context)
        self._report({"INFO"}, self._cancelled_text())
        self.outcome = "CANCELLED"
        if after:
            self._after_stop(context)
        return {"CANCELLED"}

    def _done(self, context: bpy.types.Context) -> set[str]:
        self._steps = None  # terminado: nada que cancelar
        self._cleanup(context)
        self.outcome = "FINISHED"
        return {"FINISHED"}

    def _fail(self, context: bpy.types.Context, message: str) -> set[str]:
        self._cleanup(context)
        self._report({"ERROR"}, message)
        self.outcome = "CANCELLED"
        self._after_stop(context)
        return {"CANCELLED"}

    def modal(self, context: bpy.types.Context, event: Any) -> set[str]:
        if getattr(self, "_steps", None) is None:
            return {"CANCELLED"}
        if event.type == "ESC":
            return self._stop(context)
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        started = time.perf_counter()
        try:
            while True:
                step = next(self._steps)  # type: ignore[arg-type]
                self._show(context, step)
                finished = self._result(context, step)
                if finished is not None:
                    return finished
                if time.perf_counter() - started >= self.STEP_BUDGET_S:
                    return {"RUNNING_MODAL"}
        except GeoblenderError as exc:
            return self._fail(context, self._error_text(exc))
        except StopIteration:
            return self._fail(context, tr("The operation did not finish with its result"))

    def cancel(self, context: bpy.types.Context) -> None:
        if getattr(self, "_steps", None) is not None:
            self._cleanup(context)


def _forget(operator: object) -> None:
    """Quita ``operator`` (y los ya liberados) de los modales de pasos en curso."""
    _RUNNING[:] = [ref for ref in _RUNNING if ref() is not None and ref() is not operator]


def running_step_modals() -> tuple[Any, ...]:
    """Los modales de pasos en curso (:class:`_StepsModal`), en el orden en que empezaron."""
    return tuple(found for ref in _RUNNING if (found := ref()) is not None)


def _own_window(operator: Any) -> Any:
    """La ventana en la que corre ``operator`` (la de su ``_start``), o ``None`` si ya no
    está."""
    key = getattr(operator, "_window_key", 0)
    manager = bpy.context.window_manager
    if not key or manager is None:
        return None
    for window in manager.windows:
        if window.as_pointer() == key:
            return window
    return None


def cancel_running() -> tuple[str, ...]:
    """Cancela como Esc los modales de pasos en curso (spec 009, T40; RF-001-05): lo llama
    ``bl.unregister`` al desactivar Geoblender, antes de quitar ninguna clase. Blender, al
    quitar la clase de un modal en curso, lo libera sin llamar a su ``cancel``: quedarían su
    temporizador, el avance y el texto de la barra de estado y, mientras Python no cerrara sus
    pasos, lo de a medias (la carpeta temporal de una congelación, los objetos preparados de una
    carga). Cada uno se cancela en el contexto de su ventana y sin lo de después de parar
    (volver a abrir el original de una copia local: al desactivar se cierra el proyecto); lo
    dice en su informe y en el registro, y un fallo de uno no impide los demás. Devuelve los
    ``bl_idname`` de los cancelados."""
    cancelled: list[str] = []
    for operator in running_step_modals():
        idname = getattr(type(operator), "bl_idname", type(operator).__name__)
        try:
            window = _own_window(operator)
            if window is None:
                operator._stop(bpy.context, after=False)
            else:
                with bpy.context.temp_override(window=window):
                    operator._stop(bpy.context, after=False)
        except ReferenceError:  # Blender ya lo había liberado: nada que cancelar
            continue
        except Exception:  # noqa: BLE001 - desactivar sigue con los demás y con el resto
            LOGGER.exception("No se pudo cancelar «%s» al desactivar Geoblender", idname)
            continue
        cancelled.append(idname)
        LOGGER.info("Al desactivar Geoblender se canceló «%s»: %s", idname,
                    operator._cancelled_text())
    _RUNNING.clear()
    return tuple(cancelled)


class GEOBLENDER_OT_core_checkout_project(_StepsModal, bpy.types.Operator):
    """Work on a local copy: reserve the original, copy it to this computer and open the copy"""

    bl_idname = "geoblender.core_checkout_project"
    bl_label = "Work on a local copy…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    directory: StringProperty(  # type: ignore[valid-type]
        name="Local copies folder",
        description="Folder for the local copy (empty: the one in the preferences, or the "
        "extension's user data)",
        subtype="DIR_PATH",
    )

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        project = project_session.current()
        if project is None:
            cls.poll_message_set(tr("No project is open"))
            return False
        if project.is_checkout:
            cls.poll_message_set(
                tr(
                    "The open project is already a local copy: publish it with Project ▸ "
                    "Local copy and network ▸ Publish to the network…"
                )
            )
            return False
        return True

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        if not self.directory:
            self.directory = str(project_session.checkout_dir())
        return context.window_manager.invoke_props_dialog(
            self, width=640, translate=False, title=tr("Work on a local copy")
        )

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        column = layout.column(align=True)
        column.label(
            text=tr(
                "The original stays reserved for this copy until it is published: nobody "
                "else can write to it."
            ),
            translate=False,
        )
        column.label(
            text=tr("The project is closed, copied to this folder and the copy is opened:"),
            translate=False,
        )
        layout.prop(self, "directory", text=tr("Local copies folder"), translate=False)

    def _status_text(self, step: Progress) -> str:
        return tr("Local copy · {phase}: {message}", phase=step.phase, message=step.message)

    def _cancelled_text(self) -> str:
        return tr(
            "Local copy cancelled: no copy has been left and the original is no longer reserved"
        )

    def execute(self, context: bpy.types.Context) -> set[str]:
        project = project_session.current()
        if project is None:
            return {"CANCELLED"}
        userdata = project_session.userdata()
        dest = _folder(self.directory) if self.directory else project_session.checkout_dir()
        if dest == userdata.checkouts_dir():
            try:
                dest.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self.report(
                    {"ERROR"}, tr("Cannot create «{folder}»: {error}", folder=dest, error=exc)
                )
                return {"CANCELLED"}
        self._original = project.root
        self._read_only = project.read_only_reason is ReadOnlyCode.REQUESTED
        for message in project_session.close():  # para reservarlo hay que soltarlo
            self.report({"WARNING"}, message)
        steps = checkout_steps(
            self._original, dest, project_session.session(), userdata,
            stale_minutes=project_session.stale_minutes(), read_only=read_only_dirs(),
        )
        self._start(context, steps)
        return {"RUNNING_MODAL"}

    def _result(self, context: bpy.types.Context, step: Progress) -> set[str] | None:
        result = step.result
        if not isinstance(result, CheckoutResult):
            return None
        self._steps = None
        self._cleanup(context)
        closed = project_session.attach(result.opened.project)
        self._report(
            {"INFO"},
            tr(
                "Local copy of «{name}» open in «{folder}»: the original stays reserved until "
                "you publish it",
                name=result.opened.project.name,
                folder=result.copy,
            ),
        )
        for message in (*result.warnings, *result.opened.warnings, *closed):
            self._report({"WARNING"}, message)
        self.outcome = "FINISHED"
        return {"FINISHED"}

    def _after_stop(self, context: bpy.types.Context) -> None:
        """El proyecto se cerró para reservarlo: se vuelve a abrir el original."""
        original = getattr(self, "_original", None)
        if original is None:
            return
        try:
            bpy.ops.geoblender.core_open_project(
                "EXEC_DEFAULT", directory=str(original), read_only=self._read_only
            )
        except RuntimeError as exc:
            self._report(
                {"WARNING"},
                tr("The original «{path}» could not be opened again: {error}", path=original,
                   error=exc),
            )


class GEOBLENDER_OT_core_publish_project(_StepsModal, bpy.types.Operator):
    """Publish the local copy over its original (the original is kept as <Name>.gbproj.anterior)"""

    bl_idname = "geoblender.core_publish_project"
    bl_label = "Publish to the network…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    open_published: BoolProperty(  # type: ignore[valid-type]
        name="Open the published project", default=True, options={"SKIP_SAVE"}
    )

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        project = project_session.current()
        if project is None:
            cls.poll_message_set(tr("No project is open"))
            return False
        if not project.is_checkout:
            cls.poll_message_set(
                tr(
                    "The open project is not a local copy: take one with Project ▸ Local copy "
                    "and network ▸ Work on a local copy…"
                )
            )
            return False
        if not project.writable:
            cls.poll_message_set(tr("Read-only project: {reason}", reason=project.status.message))
            return False
        return True

    @staticmethod
    def _original_path(project: Any) -> Path | None:
        return project_session.userdata().checkout_original(project.uid)

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        return context.window_manager.invoke_props_dialog(
            self, width=640, translate=False, title=tr("Publish to the network")
        )

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        project = project_session.current()
        original = None if project is None else self._original_path(project)
        if original is None:
            layout.label(
                text=tr(
                    "This computer does not know where the original of this copy is: it "
                    "cannot be published from here."
                ),
                translate=False,
            )
            return
        layout.label(
            text=tr(
                "The original «{original}» will be replaced by this copy; the current original "
                "is kept as «{previous}» (only the last one is kept).",
                original=original,
                previous=f"{original.name}.anterior",
            ),
            translate=False,
        )
        layout.prop(self, "open_published", text=tr("Open the published project"),
                    translate=False)

    def _status_text(self, step: Progress) -> str:
        return tr("Publishing · {phase}: {message}", phase=step.phase, message=step.message)

    def _cancelled_text(self) -> str:
        return tr("Publication cancelled: nothing has been replaced and the local copy stays open")

    def execute(self, context: bpy.types.Context) -> set[str]:
        project = project_session.current()
        if project is None or not project.is_checkout:
            return {"CANCELLED"}
        session, userdata = project_session.session(), project_session.userdata()
        stale = project_session.stale_minutes()
        read_only = read_only_dirs()
        steps: Iterator[Progress] = publish_steps(
            project, session, userdata, stale_minutes=stale, read_only=read_only
        )
        original = self._original_path(project)
        self._open_after = bool(self.open_published and original is not None)
        if self._open_after and original is not None:
            steps = _chain(steps, open_steps(original, session, userdata, stale_minutes=stale,
                                             read_only=read_only))
        self._published: PublishResult | None = None
        self._start(context, steps)
        return {"RUNNING_MODAL"}

    def _result(self, context: bpy.types.Context, step: Progress) -> set[str] | None:
        result = step.result
        if isinstance(result, PublishResult):
            self._published = result
            project_session.close()  # core ya cerró la copia: solo se suelta de la sesión
            self._report(
                {"INFO"},
                tr(
                    "Local copy published in «{original}»; the previous original is in "
                    "«{previous}» and the local copy «{local}» can be deleted",
                    original=result.original,
                    previous=result.previous.name,
                    local=result.local,
                ),
            )
            for message in result.warnings:
                self._report({"WARNING"}, message)
            return None if self._open_after else self._done(context)
        if isinstance(result, OpenResult):
            self._steps = None
            self._cleanup(context)
            closed = project_session.attach(result.project)
            status = result.status
            self._report(
                {"INFO"} if status.writable else {"WARNING"},
                tr("Project «{name}»: {detail}", name=result.project.name, detail=status.message),
            )
            for message in (*result.warnings, *closed):
                self._report({"WARNING"}, message)
            self.outcome = "FINISHED"
            return {"FINISHED"}
        return None


# Vista (spec 006, T27) ---------------------------------------------------------------

LOD_ITEMS: list[tuple[str, str, str]] = [
    ("FULL", "Calculation grid", "The data as they are: a grid, cell by cell"),
    ("LOD1", "First level of detail",
     "Grids with a step under 2 m: their first overview version (2 m by default)"),
    ("LOD2", "Second level of detail",
     "Grids with a step under 2 m: their second overview version (5 m by default)"),
]
LOD_LEVELS: dict[str, int] = {"FULL": 0, "LOD1": 1, "LOD2": 2}
_DATASETS_DESCRIPTION = ("Names or identifiers of the project data, separated by commas "
                         "(empty: those chosen in the dialog or selected)")


def _refs(text: str) -> list[str]:
    """Los nombres o uids de ``datasets``, sin repetir y en su orden."""
    return list(dict.fromkeys(part.strip() for part in str(text).split(",") if part.strip()))


class GEOBLENDER_OT_core_load_into_view(_StepsModal, bpy.types.Operator):
    """Build the geometry of project items in the 3D view"""

    bl_idname = "geoblender.core_load_into_view"
    bl_label = "Load into the view…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "UNDO"}

    # En pasos (T50): cada evento del temporizador avanza pasos durante, como mucho, este
    # tiempo; los pasos más largos de la rejilla de 2,81 M celdas son de unas 0,2 s.
    STEP_BUDGET_S = 0.05

    datasets: StringProperty(  # type: ignore[valid-type]
        name="Data", description=_DATASETS_DESCRIPTION, default="", options={"SKIP_SAVE"},
    )
    lod: EnumProperty(  # type: ignore[valid-type]
        name="Level of detail", items=LOD_ITEMS, default="FULL",
    )
    items: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_view_dataset, options={"SKIP_SAVE"},
    )
    # En pasos desde el temporizador de la ventana, con el avance y Esc (T50): lo pone
    # ``invoke`` (los menús y el diálogo); desde un guion, sin él, de una vez.
    in_steps: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return _poll_project(cls, context)

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        from ...core.provenance.view import live_datasets

        project = project_session.current()
        if project is None:
            return {"CANCELLED"}
        self.in_steps = getattr(context, "window", None) is not None
        if _refs(self.datasets):
            return self.execute(context)
        try:
            records = live_datasets(project)
        except GeoblenderError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        selected = set(views.loaded_uids(getattr(context, "selected_objects", None) or ()))
        self.items.clear()
        for record in records:
            loader = views.loader_for(record.name)
            if loader is None:
                continue
            item = self.items.add()
            item.uid = record.uid
            item.label = views.view_name(loader, record, stale=False)
            item.selected = record.uid in selected
        if not self.items:
            self.report({"INFO"}, tr("The project has no data to load into the view"))
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(
            self, width=520, translate=False, title=tr("Load into the view")
        )

    def draw(self, context: bpy.types.Context) -> None:
        column = self.layout.column(align=True)
        for item in self.items:
            column.prop(item, "selected", text=item.label, translate=False)
        self.layout.prop(self, "lod")

    def execute(self, context: bpy.types.Context) -> set[str]:
        project = project_session.current()
        if project is None:
            return {"CANCELLED"}
        refs = _refs(self.datasets) or [item.uid for item in self.items if item.selected]
        if not refs:
            self.report({"WARNING"}, tr("Choose the data to load into the view"))
            return {"CANCELLED"}
        lod = LOD_LEVELS[self.lod]
        if self.in_steps and getattr(context, "window", None) is not None:
            # T50 (RNF-006-09): desde el temporizador de la ventana, con su avance y Esc.
            self._project = project
            self._start(context, views.load_steps(context, project, refs, lod=lod))
            return {"RUNNING_MODAL"}
        return self._outcome(views.load_datasets(context, project, refs, lod=lod))

    def _outcome(self, outcome: views.LoadOutcome) -> set[str]:
        """Lo que dice la orden de lo cargado: los avisos, los errores y lo que cargó."""
        for text in outcome.notes:
            self._report({"WARNING"}, text)
        for text in outcome.errors:  # con algo cargado, un aviso: los demás sí se cargaron
            self._report({"WARNING"} if outcome.loaded else {"ERROR"}, text)
        if not outcome.loaded:
            self.outcome = "CANCELLED"
            return {"CANCELLED"}
        self._report({"INFO"}, tr("Loaded into the view: {names}",
                                  names=", ".join(outcome.labels or outcome.loaded)))
        self.outcome = "FINISHED"
        return {"FINISHED"}

    # En pasos (T50) ------------------------------------------------------------------------

    def _status_text(self, step: Progress) -> str:
        percent = int(100 * step.done / step.total) if step.total else 0
        return tr("Loading «{name}» into the view… {percent} % · Esc: cancel",
                  name=step.message, percent=percent)

    def _cancelled_text(self) -> str:
        return tr("Loading into the view cancelled: nothing has been loaded")

    def _result(self, context: bpy.types.Context, step: Progress) -> set[str] | None:
        if not isinstance(step.result, views.LoadOutcome):
            if project_session.current() is not getattr(self, "_project", None):
                return self._fail(context, tr("The project was closed while loading into the "
                                              "view: nothing has been loaded"))
            return None
        self._done(context)
        return self._outcome(step.result)

    def modal(self, context: bpy.types.Context, event: Any) -> set[str]:
        try:
            return super().modal(context, event)
        except Exception as exc:  # noqa: BLE001 - lo preparado ya se borró: no queda nada
            LOGGER.error("«Cargar en la vista» se ha parado", exc_info=exc)
            return self._fail(context, tr("Loading into the view stopped: {error}",
                                          error=str(exc)))


def _loaded_anywhere() -> bool:
    return any(getattr(obj, OBJECT_PROPERTY).dataset_uid for obj in bpy.data.objects)


class GEOBLENDER_OT_core_unload_from_view(bpy.types.Operator):
    """Free the geometry of the selection; the data stay in the project"""

    bl_idname = "geoblender.core_unload_from_view"
    bl_label = "Unload from the view"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "UNDO"}

    datasets: StringProperty(  # type: ignore[valid-type]
        name="Data", description=_DATASETS_DESCRIPTION, default="", options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        if not _loaded_anywhere():
            cls.poll_message_set(tr("No project data is loaded in the view"))
            return False
        return True

    def _chosen(self, context: bpy.types.Context) -> list[str]:
        """Los uids de ``datasets`` (un nombre, por el proyecto abierto) o, sin ellos, los de
        los objetos seleccionados."""
        refs = _refs(self.datasets)
        if not refs:
            return views.loaded_uids(getattr(context, "selected_objects", None) or ())
        from ...core.provenance.view import dataset_view

        loaded = set(views.loaded_uids(bpy.data.objects))
        project = project_session.current()
        found: list[str] = []
        for ref in refs:
            shown = None if ref in loaded or project is None else dataset_view(project, ref)
            found.append(ref if shown is None else shown.record.uid)
        return found

    def execute(self, context: bpy.types.Context) -> set[str]:
        uids = self._chosen(context)
        if not uids:
            self.report({"WARNING"}, tr("Select objects loaded from the project"))
            return {"CANCELLED"}
        count = views.unload_datasets(uids)
        self.report({"INFO"}, tr("Unloaded from the view: {count} objects; the data stay in "
                                 "the project", count=count))
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
    GEOBLENDER_OT_core_checkout_project,
    GEOBLENDER_OT_core_publish_project,
    GEOBLENDER_OT_core_clear_notices,
)
# Los de la vista (spec 006, T27).
classes += (GEOBLENDER_OT_core_load_into_view, GEOBLENDER_OT_core_unload_from_view)
# Transformar coordenadas (spec 006, T32).
classes += (GEOBLENDER_OT_core_transform_coordinates,)
