# SPDX-License-Identifier: GPL-3.0-or-later
"""Operadores del módulo ``io``: importar un fichero por su formato (spec 006, T32;
RF-006-27; plan 006 §5.3.5 y §5.5).

- ``geoblender.io_import_file`` (Proyecto ▸ Intercambio ▸ Importar ▸ Importar un fichero…; sin
  fichero, el navegador de ficheros con todos) abre el importador que corresponde a la extensión
  del fichero (:func:`importer_for`), con el fichero ya elegido: ``.tif``, ``.tiff`` y ``.asc``,
  el de MDT ráster (``gis_import_dtm``, con su diálogo); ``.xyz``, el de MDT si sus primeras
  líneas forman una malla regular y si no el de puntos (``gis.xyz_grid.sample_xyz``, con el
  decimal, el separador y la cabecera que se ven en ellas); ``.csv`` y ``.txt``, el de puntos y
  líneas de rotura (``gis_import_points``, con su asistente); ``.gpkg``, el de capas
  (``gis_import_vector``). Un formato que traerá otra entrada del roadmap se rechaza con ella
  («Disponible en R-65 · DXF», del catálogo de comandos; si esa entrada ya estuviera entregada,
  se abriría su orden); un shapefile, con su conversión a GeoPackage en QGIS (spec 006 §9); otra
  extensión, con las que se importan. El importador se abre en un temporizador (tras cerrarse el
  navegador de ficheros un diálogo no se abre); sin interfaz (``blender -b``), en el momento
  (:func:`open_importer`).
- ``GEOBLENDER_FH_io_import_file``: soltar en una Vista 3D un fichero con una de las extensiones
  de la 006 (:data:`EXTENSIONS`) lanza ``io_import_file`` con él.

Como las órdenes de la topografía, sin proyecto ``poll`` dice el paso previo y, sin la
procedencia o en solo lectura, su motivo (``bl.ops.gis.unavailable_reason``). No escribe en el
proyecto: lo hace el importador que abre (``{'REGISTER'}``).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import bpy
from bpy.props import StringProperty

from ...core import i18n
from ...core.catalog.search import path_text
from ...core.i18n import tr
from ...gis.xyz_grid import sample_xyz
from ..ui import commands as ui_commands
from .gis import (
    DECIMALS,
    IMPORT_DTM,
    IMPORT_POINTS,
    IMPORT_VECTOR,
    POINT_SEPARATORS,
    unavailable_reason,
)

LOGGER = logging.getLogger("geoblender.bl.ops")
TRANSLATION_CONTEXT = "Geoblender"
IMPORT_FILE = "geoblender.io_import_file"

IMPORTERS: Mapping[str, str] = {
    ".tif": IMPORT_DTM, ".tiff": IMPORT_DTM, ".asc": IMPORT_DTM,
    ".csv": IMPORT_POINTS, ".txt": IMPORT_POINTS,
    ".gpkg": IMPORT_VECTOR,
}
"""El importador de cada extensión de la 006 (``.xyz``, el de MDT o el de puntos: su
contenido lo decide)."""
EXTENSIONS: tuple[str, ...] = (".tif", ".tiff", ".asc", ".xyz", ".csv", ".txt", ".gpkg")
"""Las extensiones que se importan, en el orden en que se nombran (plan 006 §5.3.5)."""
LATER: Mapping[str, tuple[str, ...]] = {
    ".dxf": ("geoblender.io_import_dxf",),
    ".dwg": ("geoblender.io_import_dwg",),
    ".xml": ("geoblender.io_import_landxml",),
    ".landxml": ("geoblender.io_import_landxml",),
    ".2dm": ("geoblender.io_import_landxml",),
    ".sup": ("geoblender.io_import_recmin_files", "geoblender.io_import_aplitop"),
    ".su": ("geoblender.io_import_recmin_files",),
    ".lin": ("geoblender.io_import_recmin_files",),
    ".pts": ("geoblender.io_import_recmin_files",),
    ".t3": ("geoblender.io_import_recmin_files",),
    ".tot": ("geoblender.io_import_recmin_files",),
    ".blk": ("geoblender.io_import_recmin_blocks",),
    ".mdb": ("geoblender.dh_import_recmin_mdb", "geoblender.io_import_recmin_blocks"),
    ".str": ("geoblender.io_import_surpac",),
    ".dtm": ("geoblender.io_import_surpac",),
    ".omf": ("geoblender.io_import_omf",),
    ".obj": ("geoblender.gis_import_mesh",),
    ".ply": ("geoblender.gis_import_mesh",),
    ".gltf": ("geoblender.gis_import_mesh",),
    ".glb": ("geoblender.gis_import_mesh",),
    ".las": ("geoblender.gis_import_point_cloud",),
    ".laz": ("geoblender.gis_import_point_cloud",),
    ".xlsx": ("geoblender.dh_import_drillholes",),
}
"""Formatos que traen otras entradas: la extensión y los comandos del catálogo que la
importarán (spec 006 §9 y Importar ▸ del catálogo; su entrada es la del roadmap)."""
SHAPEFILE = ".shp"
"""Definitivo (spec 006 §9): QGIS lo convierte a GeoPackage."""
_DECIMAL_IDS = {mark: key for key, mark in DECIMALS.items()}
_SEPARATOR_IDS = {mark: key for key, mark in POINT_SEPARATORS.items()}


def importer_for(path: Path) -> tuple[str, dict[str, Any]]:
    """La orden que importa ``path`` (por su extensión, sin distinguir mayúsculas) y sus
    propiedades, con el fichero ya elegido. ``ValueError`` con el motivo, en el idioma de
    Geoblender, si no se importa: la entrada del roadmap que lo traerá, la conversión de un
    shapefile o las extensiones que se importan. ``OSError`` si un ``.xyz`` no se puede leer."""
    extension = path.suffix.lower()
    values: dict[str, Any] = {"filepath": str(path)}
    if extension == ".xyz":
        sample = sample_xyz(path)
        if sample is not None and sample.grid:
            return IMPORT_DTM, {**values, "dialog": True,
                                "decimal": _DECIMAL_IDS[sample.decimal]}
        if sample is not None:
            values.update(separator=_SEPARATOR_IDS[sample.separator],
                          decimal=_DECIMAL_IDS[sample.decimal], header=sample.header)
        return IMPORT_POINTS, values
    idname = IMPORTERS.get(extension)
    if idname == IMPORT_DTM:
        return idname, {**values, "dialog": True}
    if idname is not None:
        return idname, values
    later = LATER.get(extension, ())
    ready = [key for key in later if ui_commands.is_available(key)]
    if ready:
        return ready[0], values
    if later:
        cat = ui_commands.catalog()
        notes = "; ".join(ui_commands.unavailable_note(cat.commands[key]) for key in later)
        raise ValueError(tr("«{file}»: Geoblender does not import {extension} files yet. "
                            "{available}", file=path.name, extension=extension,
                            available=notes))
    if extension == SHAPEFILE:
        raise ValueError(tr("«{file}»: shapefiles are not imported. Convert it to GeoPackage in "
                            "QGIS and import the GeoPackage", file=path.name))
    raise ValueError(tr("«{file}»: Geoblender does not know how to import files with the "
                        "extension «{extension}». It imports {extensions}", file=path.name,
                        extension=extension, extensions=", ".join(EXTENSIONS)))


def open_importer(idname: str, values: Mapping[str, Any], context: Any = None) -> None:
    """Abre la orden ``idname`` (``INVOKE_DEFAULT``) con ``values``: con interfaz, en un
    temporizador sobre la ventana de ``context`` (tras el navegador de ficheros un diálogo no
    se abre en el momento); sin ella, ahora (``RuntimeError`` si la orden se niega)."""
    group, name = idname.split(".")
    if bpy.app.background:
        getattr(getattr(bpy.ops, group), name)("INVOKE_DEFAULT", **values)
        return
    manager = getattr(bpy.context, "window_manager", None)
    window = getattr(context, "window", None) or next(iter(getattr(manager, "windows", ())),
                                                      None)

    def call() -> None:
        try:
            with bpy.context.temp_override(window=window):
                getattr(getattr(bpy.ops, group), name)("INVOKE_DEFAULT", **values)
        except (RuntimeError, TypeError, AttributeError, ReferenceError):
            LOGGER.warning("No se pudo abrir el importador %s", idname, exc_info=True)

    bpy.app.timers.register(call, first_interval=0.0)


class GEOBLENDER_OT_io_import_file(bpy.types.Operator):
    """Detect the format of the file and import it (also by dropping it on the 3D view)"""

    bl_idname = IMPORT_FILE
    bl_label = "Import a file…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    filepath: StringProperty(  # type: ignore[valid-type]
        name="File", subtype="FILE_PATH", options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context: Any) -> bool:
        reason = unavailable_reason()
        if reason is not None:
            cls.poll_message_set(reason)
            return False
        return True

    def invoke(self, context: Any, event: Any) -> set[str]:
        if self.filepath:  # soltado en la vista, o desde un guion
            return self.execute(context)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context: Any) -> set[str]:
        blocked = unavailable_reason()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        path = Path(bpy.path.abspath(self.filepath)) if self.filepath else None
        if path is None or not path.is_file():
            self.report({"ERROR"}, tr("The file «{file}» does not exist: choose the file to "
                                      "import", file="" if path is None else path.name))
            return {"CANCELLED"}
        try:
            idname, values = importer_for(path)
        except (ValueError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        try:
            open_importer(idname, values, context)
        except RuntimeError as exc:  # sin interfaz, el importador se negó: su motivo
            self.report({"ERROR"}, str(exc).removeprefix("Error: ").strip())
            return {"CANCELLED"}
        where = path_text(ui_commands.catalog(), idname, i18n.language())
        self.report({"INFO"}, tr("Importing «{file}» with {command}", file=path.name,
                                 command=where))
        return {"FINISHED"}


class GEOBLENDER_FH_io_import_file(bpy.types.FileHandler):
    """Al soltar un fichero de la 006 en una Vista 3D, «Importar un fichero» con él."""

    bl_idname = "GEOBLENDER_FH_io_import_file"
    bl_label = "Import a file…"
    bl_import_operator = IMPORT_FILE
    bl_file_extensions = ";".join(EXTENSIONS)

    @classmethod
    def poll_drop(cls, context: Any) -> bool:
        area = getattr(context, "area", None)
        return area is not None and area.type == "VIEW_3D"


# En orden de registro: el manejador, después de su orden.
classes: tuple[type, ...] = (GEOBLENDER_OT_io_import_file, GEOBLENDER_FH_io_import_file)
