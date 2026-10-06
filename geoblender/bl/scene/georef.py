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
  proyecto, o a antes de un cambio de la ventana de trabajo; se vuelven a sincronizar
  todas (ninguna operación de la spec 002 entra en la pila de deshacer) y, si alguna
  traía otra georreferencia, la vista queda desfasada (RF-002-27).
- ``save_pre``: se sincronizan todas, también una escena nueva, con la ruta relativa al
  fichero de **destino** (``save_pre`` la recibe), y las rutas absolutas de los bloques de
  datos del mismo volumen pasan a relativas al destino (RF-002-07, RF-002-18; también con
  Ctrl+S); las de otro volumen no se pueden expresar así y quedan en un aviso.
- ``save_post``: con el proyecto en escritura, la cabecera se actualiza desde la base de
  datos (RF-002-07).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import bpy
from bpy.app.handlers import persistent

from ...core.errors import GeoblenderError
from ...core.i18n import format_xyz, tr
from ...core.ids import short_uid
from ...core.paths import (
    blend_relative_path,
    find_absolute_paths,
    is_within,
    relative_render_path,
    same_volume,
)
from ..props.core import LOCAL_VERTICAL
from . import project_session

if TYPE_CHECKING:
    from ...core.project.session import Project

SCENES_DIR = "scenes"  # las vistas del proyecto (ADR-0006)
# Los datos de la interfaz, que una vista de scenes/ no guarda (D-11), y las bibliotecas,
# que escriben los bloques enlazados que las usan.
INTERFACE_TYPES: tuple[type, ...] = (
    bpy.types.Screen,
    bpy.types.WindowManager,
    bpy.types.WorkSpace,
    bpy.types.Library,
)

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
        """«EPSG:25830 + EPSG:5782, GeoOrigin X 700 000  Y 4 400 000  Z 0», en el idioma
        de la interfaz."""
        if self.vcrs_epsg == LOCAL_VERTICAL:
            vertical = tr("local reference")
        else:
            vertical = f"EPSG:{self.vcrs_epsg}"
        return tr(
            "EPSG:{crs} + {vertical}, GeoOrigin {xyz}",
            crs=self.crs_epsg,
            vertical=vertical,
            xyz=format_xyz(*self.origin, decimals=0),
        )


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
    return Path(filepath).name if isinstance(filepath, str) and filepath else tr("unsaved")


def _listed(georefs: list[SceneGeoref]) -> str:
    return "; ".join(
        tr("«{name}», {georef}", name=item.name, georef=item.describe()) for item in georefs
    )


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
                tr(
                    "The view «{view}» belongs to project {projects}, which is not open: "
                    "Geoblender does not use its georeference and marks it out of date; open "
                    "the project to work with it.",
                    view=view,
                    projects=_listed(found),
                )
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
            tr(
                "The view «{view}» belongs to another project ({projects}), not to the open "
                "one («{name}», {georef}): «{name}» has been closed and the view is out of "
                "date; open its project to work with it.",
                view=view,
                projects=_listed(others),
                name=expected.name,
                georef=expected.describe(),
            )
        )
        return
    if not project.writable and is_within(filepath if isinstance(filepath, str) else None,
                                          project.root):
        project_session.notify(
            tr(
                "The project «{name}» is read-only ({status}): the view «{view}» is in its "
                "folder and Ctrl+S would save it inside the project; to keep changes, use "
                "File ▸ Save As… outside the project folder.",
                name=expected.name,
                status=project.status.message,
                view=view,
            )
        )
    differing = [item for item in found if item.key != expected.key]
    if differing:
        mark_stale()
        shown = "; ".join(item.describe() for item in differing)
        project_session.notify(
            tr(
                "The view «{view}» has another georeference than project «{name}»: in the "
                "view, {view_georef}; in the project, {project_georef}. The project's is "
                "used and the view is out of date: reload its data.",
                view=view,
                name=expected.name,
                view_georef=shown,
                project_georef=expected.describe(),
            )
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


def resync_after_history() -> None:
    """Lo que hacen ``undo_post`` y ``redo_post`` (RF-002-28): todas las escenas, otra vez
    con la georreferencia del proyecto abierto. Si alguna vuelve con otra (deshacer hasta
    antes de «Ventana de trabajo…»: sus datos se cargaron con el origen anterior), la
    vista queda además desfasada, como la dejó el cambio (RF-002-27; convergencia, T54);
    una escena sin georreferencia (de antes de abrir el proyecto) solo se sincroniza."""
    expected = project_georeference()
    if expected is None:
        return
    if any(item.key != expected.key or item.uid != expected.uid
           for item in file_georeferences()):
        mark_stale()
    sync_scenes()


@persistent
def on_undo_post(*_args: object) -> None:
    """Tras deshacer: :func:`resync_after_history` (RF-002-28)."""
    resync_after_history()


@persistent
def on_redo_post(*_args: object) -> None:
    """Tras rehacer: :func:`resync_after_history` (RF-002-28)."""
    resync_after_history()


def _is_absolute(path: str) -> bool:
    return bool(path) and not path.startswith("//") and bool(
        Path(path).is_absolute() or find_absolute_paths(path)
    )


def relativize_paths(target: Path) -> list[str]:
    """Pasa a relativas a la carpeta de ``target`` las rutas absolutas de los bloques de
    datos locales que están en su mismo volumen (RF-002-18) y devuelve las que siguen
    siendo absolutas (otro volumen, una biblioteca enlazada o una ruta que no es la
    ``filepath`` del bloque)."""
    base = Path(target).parent
    remaining: list[str] = []
    for block, used in bpy.data.file_path_map(include_libraries=True).items():
        if not used or getattr(block, "library", None) is not None:
            continue
        current = getattr(block, "filepath", None)
        editable = isinstance(current, str) and not isinstance(block, bpy.types.Library)
        if editable and _is_absolute(current):
            full = bpy.path.abspath(current)
            if same_volume(full, base):
                block.filepath = bpy.path.relpath(full, start=str(base))
            else:
                remaining.append(current)
        for path in sorted(used):
            if path != current and _is_absolute(path):
                remaining.append(path)
    return remaining


def is_project_view(target: str | Path | None, project: Project) -> bool:
    """Verdadero si ``target`` es una vista de ``scenes/`` de ``project``."""
    return is_within(target, project.root / SCENES_DIR)


def relativize_render_outputs(target: Path) -> list[str]:
    """Pasa la salida de render de cada escena a relativa a la vista ``target`` (RF-002-18;
    D-11; ``core.paths.relative_render_path``) y devuelve las que, por estar en otro
    volumen, pasan a la carpeta de la vista."""
    moved: list[str] = []
    for scene in bpy.data.scenes:
        current = scene.render.filepath
        new, was_moved = relative_render_path(current, target)
        if new != current:
            scene.render.filepath = new
        if was_moved:
            moved.append(current)
    return moved


def view_datablocks() -> set[bpy.types.ID]:
    """Los bloques de datos que guarda una vista sin los datos de la interfaz: todos menos
    las pantallas, el gestor de ventanas, los espacios de trabajo y las bibliotecas (las
    escriben sus bloques enlazados); como al guardar, sin los que no tienen usuarios ni
    usuario falso (salvo las escenas)."""
    found: set[bpy.types.ID] = set()
    for block in bpy.data.user_map():
        if isinstance(block, INTERFACE_TYPES) or getattr(block, "is_embedded_data", False):
            continue
        if block.users > 0 or block.use_fake_user or isinstance(block, bpy.types.Scene):
            found.add(block)
    return found


def write_view_without_interface(path: Path) -> None:
    """Reescribe la vista ``path`` (recién guardada por Blender) sin los datos de la
    interfaz (D-11, RF-002-18): sus bloques de datos (:func:`view_datablocks`) con
    ``bpy.data.libraries.write`` en un temporal de su carpeta, con las rutas relativas y la
    compresión de las preferencias, que sustituye al fichero (``os.replace``). La sesión
    sigue en su fichero y sin cambios pendientes; Blender, al abrirla, conserva la interfaz
    que tenga (avisa de que el fichero no la trae) y muestra su primera escena."""
    temporary = path.with_name(f".{path.stem}.{short_uid()}{path.suffix}")
    compress = bool(bpy.context.preferences.filepaths.use_file_compression)
    try:
        bpy.data.libraries.write(
            str(temporary), view_datablocks(), path_remap="RELATIVE", fake_user=False,
            compress=compress,
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@persistent
def on_save_pre(filepath: object = None, *_args: object) -> None:
    """Antes de guardar: todas las escenas (también las nuevas), con la ruta del proyecto
    relativa al fichero de destino, y las rutas de los bloques de datos, relativas a él
    (RF-002-07, RF-002-18, RF-002-28); en una vista de ``scenes/``, también la salida de
    render (D-11)."""
    target = filepath if isinstance(filepath, str) and filepath else None
    project = project_session.current()
    if project is None:
        return
    sync_scenes(project, blend_file=target)
    if target is None:
        return
    if is_project_view(target, project):
        for output in relativize_render_outputs(Path(target)):
            project_session.notify(
                tr(
                    "The view «{view}» rendered to «{path}», on another volume: its render "
                    "output is now the view's folder (a view of the project keeps no "
                    "absolute path).",
                    view=Path(target).name,
                    path=output,
                )
            )
    remaining = relativize_paths(Path(target))
    if remaining:
        shown = ", ".join(f"«{path}»" for path in remaining[:3])
        if len(remaining) > 3:
            shown += tr(" and {count} more", count=len(remaining) - 3)
        project_session.notify(
            tr(
                "The view «{view}» uses files with an absolute path that cannot be saved as "
                "relative (another volume or a linked library): {paths}; copy them next to "
                "the project if the view must work on another computer.",
                view=Path(target).name,
                paths=shown,
            )
        )


@persistent
def on_save_post(filepath: object = None, *_args: object) -> None:
    """Tras guardar, con el proyecto en escritura: una vista de ``scenes/`` se reescribe
    sin los datos de la interfaz (D-11, RF-002-18; también con Ctrl+S), y la cabecera, desde
    la base (RF-002-07). En solo lectura no se escribe nada en el proyecto (RF-002-13)."""
    project = project_session.current()
    if project is None or not project.writable:
        return
    target = filepath if isinstance(filepath, str) and filepath else bpy.data.filepath
    if target and is_project_view(target, project):
        try:
            write_view_without_interface(Path(target))
        except (OSError, RuntimeError, ValueError) as exc:
            project_session.notify(
                tr(
                    "The view «{view}» was saved with Blender's interface data (it could not "
                    "be rewritten without it: {error}); save it again.",
                    view=Path(target).name,
                    error=exc,
                )
            )
    try:
        project.refresh_header()
    except GeoblenderError as exc:
        project_session.notify(exc.message)
    except OSError as exc:
        project_session.notify(
            tr("Project «{name}»: the header could not be updated ({error}).",
               name=project.name, error=exc)
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
