# SPDX-License-Identifier: GPL-3.0-or-later
"""La georreferencia del proyecto en las escenas de Blender (spec 002; RF-002-06,
RF-002-07, RF-002-18, RF-002-28; plan 002 §5.4, «Escena»).

Mientras hay un proyecto abierto, **todas** las escenas del ``.blend`` llevan en
``Scene.geoblender`` su identidad, su nombre, su ruta **relativa** al ``.blend`` (``//../``
desde ``scenes/``; vacía si no se puede expresar así, nunca absoluta), su CRS horizontal y
vertical y su GeoOrigin en metros enteros (:func:`sync_scenes`). La fuente es el proyecto
abierto (su base de datos), nunca la escena.

La georreferencia con la que trabaja cualquier comando es la del proyecto abierto
(:func:`project_georeference`), nunca la que traen las escenas de un ``.blend``: sin
proyecto abierto no hay ninguna (RF-002-29).

Manejadores, todos ``@persistent`` (sin ello se pierden al cargar otro fichero) y
retirados en :func:`unregister`:

- ``load_post`` (RF-002-06, RF-002-29): si el fichero es de **otro** proyecto, se cierra
  el abierto; si es del mismo con **otra** georreferencia, se sincronizan sus escenas con
  la del proyecto; si es de un proyecto y no hay ninguno abierto, no se usa. En los tres
  casos queda un aviso con las dos georreferencias y la vista, desfasada
  (``view_stale``). Comprueba además que el temporizador de la marca del cerrojo sigue
  registrado.
- ``undo_post`` y ``redo_post``: deshacer puede devolver una escena a antes de abrir el
  proyecto; se vuelven a sincronizar todas (ninguna operación de la spec 002 entra en la
  pila de deshacer).
- ``save_pre``: se sincronizan todas, también una escena nueva, con la ruta relativa al
  fichero de **destino** (``save_pre`` la recibe).
- ``save_post``: con el proyecto en escritura, la cabecera se actualiza desde la base de
  datos (RF-002-07).
"""

from __future__ import annotations

from dataclasses import dataclass
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

_THIN_SPACE = "\u2009"  # espacio fino de miles


@dataclass(frozen=True)
class SceneGeoref:
    """Identidad y georreferencia de un proyecto (la del proyecto abierto o la que trae
    la escena de un ``.blend``): EPSG horizontal, vertical (0 = referencia local) y
    GeoOrigin en metros enteros."""

    uid: str
    name: str
    crs_epsg: int
    vcrs_epsg: int
    origin: tuple[int, int, int]

    @property
    def key(self) -> tuple[int, int, tuple[int, int, int]]:
        """Lo que se compara: CRS y GeoOrigin."""
        return self.crs_epsg, self.vcrs_epsg, self.origin

    def describe(self) -> str:
        """«EPSG:25830 + EPSG:5782, GeoOrigin (700 000; 4 400 000; 0)», en español."""
        if self.vcrs_epsg == LOCAL_VERTICAL:
            vertical = "referencia local"
        else:
            vertical = f"EPSG:{self.vcrs_epsg}"
        x, y, z = (f"{value:,d}".replace(",", _THIN_SPACE) for value in self.origin)
        return f"EPSG:{self.crs_epsg} + {vertical}, GeoOrigin ({x}; {y}; {z})"


def project_georeference() -> SceneGeoref | None:
    """La georreferencia del proyecto abierto, la única que usan los comandos; ``None``
    sin proyecto, aunque las escenas traigan una (RF-002-29)."""
    project = project_session.current()
    if project is None:
        return None
    values = _georeference(project, None)
    return SceneGeoref(
        values["project_uid"],
        values["project_name"],
        values["crs_epsg"],
        values["vcrs_epsg"],
        (values["origin_x"], values["origin_y"], values["origin_z"]),
    )


def scene_georeference(scene: bpy.types.Scene) -> SceneGeoref | None:
    """La georreferencia que trae ``scene`` (``None`` si no es de ningún proyecto). Solo
    para compararla y avisar: ningún comando la usa (RF-002-29)."""
    props = scene.geoblender
    if not props.project_uid:
        return None
    return SceneGeoref(
        props.project_uid,
        props.project_name,
        int(props.crs_epsg),
        int(props.vcrs_epsg),
        (int(props.origin_x), int(props.origin_y), int(props.origin_z)),
    )


def mark_stale() -> None:
    """Marca como desfasada la vista: todas las escenas del ``.blend``."""
    for scene in bpy.data.scenes:
        if not scene.geoblender.view_stale:
            scene.geoblender.view_stale = True


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


def file_georeferences() -> list[SceneGeoref]:
    """Las georreferencias distintas que traen las escenas del ``.blend`` cargado, en el
    orden de las escenas (sin las que no son de ningún proyecto)."""
    found: list[SceneGeoref] = []
    for scene in bpy.data.scenes:
        georef = scene_georeference(scene)
        if georef is not None and georef not in found:
            found.append(georef)
    return found


def file_project_uids() -> set[str]:
    """Los proyectos que dicen las escenas del ``.blend`` cargado (sin las vacías)."""
    return {georef.uid for georef in file_georeferences()}


def _view_name(filepath: object) -> str:
    return Path(filepath).name if isinstance(filepath, str) and filepath else "sin guardar"


def _listed(georefs: list[SceneGeoref]) -> str:
    return "; ".join(f"«{item.name}», {item.describe()}" for item in georefs)


def check_loaded_file(filepath: object = None) -> None:
    """Lo que hace ``load_post`` con el ``.blend`` recién cargado (RF-002-06, RF-002-28,
    RF-002-29): cerrar el proyecto si el fichero es de otro, sincronizar sus escenas si
    es del abierto y avisar (con la vista desfasada) si su georreferencia no es la del
    proyecto abierto o no hay ninguno abierto."""
    view = _view_name(filepath)
    found = file_georeferences()
    project = project_session.current()
    if project is None:
        if found:
            mark_stale()
            project_session.notify(
                f"La vista «{view}» es del proyecto {_listed(found)}, que no está abierto: "
                "Geoblender no usa la georreferencia de la vista y la deja desfasada; abra "
                "el proyecto para trabajar con ella."
            )
        return
    expected = project_georeference()
    if expected is None:  # inalcanzable: hay proyecto
        return
    others = [item for item in found if item.uid != project.uid]
    if others:
        project_session.close()
        mark_stale()
        project_session.notify(
            f"La vista «{view}» es de otro proyecto ({_listed(others)}), no del abierto "
            f"(«{expected.name}», {expected.describe()}): se ha cerrado «{expected.name}» "
            "y la vista queda desfasada; abra su proyecto para trabajar con ella."
        )
        return
    differing = [item for item in found if item.key != expected.key]
    if differing:
        mark_stale()
        shown = "; ".join(item.describe() for item in differing)
        project_session.notify(
            f"La vista «{view}» tiene otra georreferencia que el proyecto «{expected.name}»: "
            f"en la vista, {shown}; en el proyecto, {expected.describe()}. Se usa la del "
            "proyecto y la vista queda desfasada: vuelva a cargar sus datos."
        )
    sync_scenes(project)


# Manejadores ---------------------------------------------------------------------------


@persistent
def on_load_post(filepath: object = None, *_args: object) -> None:
    """Tras cargar un ``.blend``: :func:`check_loaded_file`; y la marca del cerrojo sigue
    viva."""
    try:
        check_loaded_file(filepath)
    finally:
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
