# SPDX-License-Identifier: GPL-3.0-or-later
"""La georreferencia del proyecto en las escenas de Blender (spec 002; RF-002-06,
RF-002-07, RF-002-18, RF-002-28; plan 002 §5.4, «Escena»).

Mientras hay un proyecto abierto, **todas** las escenas del ``.blend`` llevan en
``Scene.geoblender`` su identidad, su nombre, su ruta **relativa** al ``.blend`` (``//../``
desde ``scenes/``; vacía si no se puede expresar así, nunca absoluta), su CRS horizontal y
vertical y su GeoOrigin en metros enteros (:func:`sync_scenes`). La fuente es el proyecto
abierto (su base de datos), nunca la escena.

Manejadores, todos ``@persistent`` (sin ello se pierden al cargar otro fichero) y
retirados en :func:`unregister`:

- ``load_post``: si el fichero es de **otro** proyecto, se cierra el abierto
  (RF-002-06); si no, se sincronizan sus escenas. Comprueba además que el temporizador
  de la marca del cerrojo sigue registrado.
- ``undo_post`` y ``redo_post``: deshacer puede devolver una escena a antes de abrir el
  proyecto; se vuelven a sincronizar todas (ninguna operación de la spec 002 entra en la
  pila de deshacer).
- ``save_pre``: se sincronizan todas, también una escena nueva, con la ruta relativa al
  fichero de **destino** (``save_pre`` la recibe).
- ``save_post``: con el proyecto en escritura, la cabecera se actualiza desde la base de
  datos (RF-002-07).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import bpy
from bpy.app.handlers import persistent

from ...core.errors import GeoblenderError
from ...core.paths import blend_relative_path
from ..props.core import LOCAL_VERTICAL
from . import project_session

if TYPE_CHECKING:
    from ...core.project.session import Project


def _georeference(project: Project, blend_file: str | Path | None) -> dict[str, Any]:
    """Los valores de ``Scene.geoblender`` para ``project`` vistos desde ``blend_file``.
    El CRS sale de la cabecera, que coincide con la base (si no, el proyecto no abre) y
    es lo único que hay cuando solo se pudo leer la cabecera (RF-002-22)."""
    header = project.manifest
    origin = project.origin
    return {
        "project_uid": project.uid,
        "project_name": project.name,
        "project_path": blend_relative_path(project.root, blend_file),
        "crs_epsg": int(header.crs_epsg),
        "vcrs_epsg": LOCAL_VERTICAL if header.vcrs_epsg is None else int(header.vcrs_epsg),
        "origin_x": int(origin.x0),
        "origin_y": int(origin.y0),
        "origin_z": int(origin.z0),
    }


def sync_scene(scene: bpy.types.Scene, values: dict[str, Any]) -> None:
    """Escribe ``values`` en ``scene.geoblender`` (solo lo que cambia)."""
    props = scene.geoblender
    for name, value in values.items():
        if getattr(props, name) != value:
            setattr(props, name, value)


def sync_scenes(project: Project | None = None, blend_file: str | Path | None = None) -> None:
    """Lleva la georreferencia de ``project`` (por defecto, el de la sesión) a todas las
    escenas, con la ruta relativa a ``blend_file`` (por defecto, el ``.blend`` actual)."""
    project = project_session.current() if project is None else project
    if project is None:
        return
    target = bpy.data.filepath if blend_file is None else blend_file
    values = _georeference(project, target)
    for scene in bpy.data.scenes:
        sync_scene(scene, values)


def file_project_uids() -> set[str]:
    """Los proyectos que dicen las escenas del ``.blend`` cargado (sin las vacías)."""
    return {scene.geoblender.project_uid for scene in bpy.data.scenes} - {""}


# Manejadores ---------------------------------------------------------------------------


@persistent
def on_load_post(*_args: object) -> None:
    """Tras cargar un ``.blend``: cierra el proyecto si el fichero es de otro (RF-002-06)
    o sincroniza sus escenas (RF-002-28); y la marca del cerrojo sigue viva."""
    project = project_session.current()
    if project is not None:
        if file_project_uids() - {project.uid}:
            project_session.close()
        else:
            sync_scenes(project)
    project_session.ensure_heartbeat()


@persistent
def on_undo_post(*_args: object) -> None:
    """Tras deshacer: todas las escenas, otra vez con la georreferencia (RF-002-28)."""
    sync_scenes()


@persistent
def on_redo_post(*_args: object) -> None:
    """Tras rehacer: todas las escenas, otra vez con la georreferencia (RF-002-28)."""
    sync_scenes()


@persistent
def on_save_pre(filepath: object = None, *_args: object) -> None:
    """Antes de guardar: todas las escenas (también las nuevas), con la ruta del proyecto
    relativa al fichero de destino (RF-002-18, RF-002-28)."""
    target = filepath if isinstance(filepath, str) and filepath else None
    sync_scenes(blend_file=target)


@persistent
def on_save_post(*_args: object) -> None:
    """Tras guardar: con el proyecto en escritura, la cabecera desde la base (RF-002-07)."""
    project = project_session.current()
    if project is None or not project.writable:
        return
    try:
        project.refresh_header()
    except GeoblenderError as exc:
        project_session.notify(exc.message)
    except OSError as exc:
        project_session.notify(
            f"Proyecto «{project.name}»: no se ha podido actualizar la cabecera ({exc})."
        )


# (lista de bpy.app.handlers, función), en el orden en que se registran.
HANDLERS: tuple[tuple[str, Any], ...] = (
    ("load_post", on_load_post),
    ("undo_post", on_undo_post),
    ("redo_post", on_redo_post),
    ("save_pre", on_save_pre),
    ("save_post", on_save_post),
)


def register() -> None:
    """Añade los manejadores (sin repetirlos)."""
    for name, function in HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if function not in handlers:
            handlers.append(function)


def unregister() -> None:
    """Quita los manejadores (todas sus apariciones)."""
    for name, function in reversed(HANDLERS):
        handlers = getattr(bpy.app.handlers, name)
        while function in handlers:
            handlers.remove(function)
