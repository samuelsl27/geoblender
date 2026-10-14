# SPDX-License-Identifier: GPL-3.0-or-later
"""Las curvas maestras con trazo grueso en la Vista 3D (spec 006, T55; RF-006-18, RF-006-19;
comprobación manual M4).

Las curvas cargadas en la vista son mallas de aristas sueltas (``bl.scene.gis_views``), y
Blender dibuja todas las aristas sueltas con el mismo alambre de 1 px y el color del tema: con
el sombreado sólido por defecto (``wireframe_color_type`` = ``THEME``) ni el color del objeto
ni el de un material lo cambian, y el grosor de las líneas es una preferencia global. Para que
las maestras se distingan a simple vista **sin tocar las preferencias, el tema ni el sombreado
del usuario**, esta superposición dibuja otra vez, después de la escena
(``SpaceView3D.draw_handler_add``, ``POST_VIEW``), las aristas marcadas con el atributo
``is_index`` (``gis_views.INDEX_ATTRIBUTE``) con un trazo de :data:`INDEX_LINE_WIDTH` px (por el
tamaño de píxel de la interfaz) y el color con que Blender dibuja ese alambre (el del tema; el de
seleccionado o activo, si lo está):

- solo en los objetos de curvas (``Object.geoblender.kind`` = ``CONTOURS``) visibles en esa
  vista, fuera del modo Edición y con las superposiciones encendidas;
- con la prueba de profundidad de la escena (lo que tapa el terreno, tapado), con el trazo
  acercado a la cámara :data:`DEPTH_PULL` de su distancia para que no lo tape la superficie
  sobre la que está la curva: en perspectiva, escalando las coordenadas de vista (no cambia
  dónde cae en la pantalla); en ortográfica, desplazándolas hacia la cámara;
- con un lote de ``gpu`` por malla (sus aristas maestras en coordenadas locales, las que guarda
  Blender), que se rehace si su geometría cambia (``depsgraph_update_post``) y se suelta
  cuando la malla ya no está.

:func:`draw_index_lines` dibuja con unas matrices dadas (la de la vista o, en las pruebas, una
imagen fuera de pantalla). :func:`register` y :func:`unregister` ponen y quitan el manejador de
dibujo y el de actualización (principio 8): desactivar Geoblender deja la vista como la dibuja
Blender (el atributo se queda en la malla, como un dato más). Un error al dibujar se registra
una vez y la superposición deja de dibujar hasta volver a registrarla: nunca una traza por
fotograma.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

import bpy
import gpu
import numpy as np
from bpy.app.handlers import persistent
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

from ..props.core import OBJECT_PROPERTY
from ..scene.gis_views import CONTOURS_KIND, INDEX_ATTRIBUTE
from ..scene.mesh import edge_flags, mesh_edges, mesh_vertices_local

__all__ = ["DEPTH_PULL", "INDEX_LINE_WIDTH", "draw_index_lines", "drawing", "index_segments",
           "register", "unregister"]

LOGGER = logging.getLogger("geoblender.bl.draw")

INDEX_LINE_WIDTH = 3.0
"""El trazo de las maestras, en px (por ``preferences.system.pixel_size``); Blender dibuja el
alambre de todas con 1 px."""
DEPTH_PULL = 0.002
"""Lo que se acerca el trazo a la cámara, en fracción de su distancia (en ortográfica, de la
distancia de la vista): 0,2 m a 100 m."""
SHADER = "POLYLINE_UNIFORM_COLOR"
"""El *shader* de ``gpu`` de líneas con grosor (nombre de Blender 5.2)."""


@dataclass
class _Entry:
    """El lote de las aristas maestras de una malla y con qué malla se hizo (sus vértices y
    sus aristas); ``None`` si no tiene ninguna."""

    signature: tuple[int, int]
    batch: Any


_handle: Any = None
_cache: dict[int, _Entry] = {}
_failed = False


def drawing() -> bool:
    """Si la superposición está registrada (dibuja las maestras en cada Vista 3D)."""
    return _handle is not None


def index_segments(mesh: bpy.types.Mesh) -> np.ndarray:
    """Los extremos de las aristas maestras de ``mesh`` (las de :data:`INDEX_ATTRIBUTE`), dos
    filas por arista, en coordenadas locales tal como las guarda Blender (float32 ``(2k, 3)``);
    vacío si no tiene el atributo o ninguna arista marcada."""
    flags = edge_flags(mesh, INDEX_ATTRIBUTE)
    if flags is None or not flags.any():
        return np.empty((0, 3), dtype=np.float32)
    return mesh_vertices_local(mesh)[mesh_edges(mesh)[flags].ravel()]


def _batch(mesh: bpy.types.Mesh, shader: Any) -> Any:
    """El lote de las aristas maestras de ``mesh`` (de la caché, o nuevo si la malla cambió de
    vértices o de aristas); ``None`` si no tiene ninguna."""
    signature = (len(mesh.vertices), len(mesh.edges))
    entry = _cache.get(mesh.session_uid)
    if entry is None or entry.signature != signature:
        segments = index_segments(mesh)
        batch = batch_for_shader(shader, "LINES", {"pos": segments}) if len(segments) else None
        entry = _Entry(signature, batch)
        _cache[mesh.session_uid] = entry
    return entry.batch


def _pulled(view_matrix: Matrix, perspective: bool, view_distance: float) -> Matrix:
    """``view_matrix`` con lo que dibuja acercado a la cámara :data:`DEPTH_PULL` (véase el
    módulo)."""
    if perspective:
        scale = 1.0 - DEPTH_PULL
        return Matrix.Diagonal((scale, scale, scale, 1.0)) @ view_matrix
    return Matrix.Translation((0.0, 0.0, DEPTH_PULL * max(float(view_distance), 1.0))) @ (
        view_matrix)


def draw_index_lines(
    entries: Sequence[tuple[bpy.types.Object, Sequence[float]]],
    *,
    view_matrix: Matrix,
    projection_matrix: Matrix,
    perspective: bool,
    view_distance: float,
    viewport_size: tuple[float, float],
    pixel_size: float,
) -> int:
    """Dibuja en el *framebuffer* activo las aristas maestras de cada objeto de ``entries``
    (objeto y color RGBA) con un trazo de :data:`INDEX_LINE_WIDTH` × ``pixel_size`` px, con la
    matriz de vista ``view_matrix`` (acercada a la cámara, :func:`_pulled`), la de proyección
    ``projection_matrix`` y la prueba de profundidad ``LESS_EQUAL`` sin escribir profundidad;
    deja el estado de ``gpu`` como estaba. Devuelve cuántos objetos dibujó."""
    shader = gpu.shader.from_builtin(SHADER)
    view = _pulled(view_matrix, perspective, view_distance)
    drawn = 0
    state = (gpu.state.depth_test_get(), gpu.state.depth_mask_get(), gpu.state.blend_get())
    with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
        gpu.matrix.load_projection_matrix(projection_matrix)
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.depth_mask_set(False)
        gpu.state.blend_set("ALPHA")
        try:
            for obj, color in entries:
                batch = _batch(obj.data, shader)
                if batch is None:
                    continue
                gpu.matrix.load_matrix(view @ obj.matrix_world)
                shader.uniform_float("viewportSize", tuple(viewport_size))
                shader.uniform_float("lineWidth", INDEX_LINE_WIDTH * float(pixel_size))
                shader.uniform_float("color", tuple(color))
                batch.draw(shader)
                drawn += 1
        finally:
            gpu.state.depth_test_set(state[0])
            gpu.state.depth_mask_set(state[1])
            gpu.state.blend_set(state[2])
    return drawn


def _color(obj: bpy.types.Object, active: Any, theme: Any) -> tuple[float, float, float, float]:
    """El color del alambre de ``obj`` como lo dibuja Blender: el del tema; seleccionado, el de
    seleccionado o, si es el activo, el de activo."""
    if obj.select_get():
        found = theme.object_active if obj == active else theme.object_selected
    else:
        found = theme.wire
    return (float(found[0]), float(found[1]), float(found[2]), 1.0)


def _shown(context: Any, space: Any) -> Iterator[tuple[bpy.types.Object, tuple[float, ...]]]:
    """Los objetos de curvas con maestras que se ven en ``space`` y su color."""
    view_layer = context.view_layer
    active = view_layer.objects.active
    theme = context.preferences.themes[0].view_3d
    for obj in view_layer.objects:
        if obj.type != "MESH" or getattr(obj, OBJECT_PROPERTY).kind != CONTOURS_KIND:
            continue
        if obj.mode == "EDIT" or INDEX_ATTRIBUTE not in obj.data.attributes:
            continue
        if obj.visible_get(view_layer=view_layer, viewport=space):
            yield obj, _color(obj, active, theme)


def _draw() -> None:
    """El manejador ``POST_VIEW`` de cada Vista 3D (véase el módulo)."""
    global _failed
    if _failed:
        return
    try:
        context = bpy.context
        space, region, rv3d = context.space_data, context.region, context.region_data
        if space is None or region is None or rv3d is None or not space.overlay.show_overlays:
            return
        entries = list(_shown(context, space))
        if entries:
            draw_index_lines(entries, view_matrix=gpu.matrix.get_model_view_matrix(),
                             projection_matrix=gpu.matrix.get_projection_matrix(),
                             perspective=bool(rv3d.is_perspective),
                             view_distance=float(rv3d.view_distance),
                             viewport_size=(float(region.width), float(region.height)),
                             pixel_size=float(context.preferences.system.pixel_size))
    except Exception:  # una traza por fotograma no ayuda a nadie
        _failed = True
        LOGGER.exception("No se pueden dibujar las curvas maestras: la superposición se apaga")


@persistent
def _on_depsgraph(_scene: Any, depsgraph: Any) -> None:
    """Suelta los lotes de las mallas cuya geometría cambió y los de las que ya no están."""
    if not _cache:
        return
    for update in depsgraph.updates:
        if not update.is_updated_geometry:
            continue
        data = getattr(update.id, "original", update.id)
        if isinstance(data, bpy.types.Object):
            data = data.data
        if isinstance(data, bpy.types.Mesh):
            _cache.pop(data.session_uid, None)
    alive = {mesh.session_uid for mesh in bpy.data.meshes}
    for key in [key for key in _cache if key not in alive]:
        del _cache[key]


def register() -> None:
    """Pone el manejador de dibujo y el de actualización; si ya están, nada."""
    global _handle, _failed
    if _handle is None:
        _handle = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_VIEW")
    if _on_depsgraph not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)
    _failed = False


def unregister() -> None:
    """Quita los dos manejadores y suelta los lotes; si no están, nada."""
    global _handle
    if _on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph)
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, "WINDOW")
        _handle = None
    _cache.clear()
