# SPDX-License-Identifier: GPL-3.0-or-later
"""El grosor de línea y el tamaño de punto del aspecto, en la Vista 3D (spec 019, T07b; RF-019-07).

Blender dibuja las aristas y los vértices sueltos de las mallas de Geoblender con el alambre de 1 px del tema y no
tiene un grosor por objeto. Esta superposición (``SpaceView3D.draw_handler_add``, ``POST_VIEW``, como
``bl/draw/contours``) dibuja otra vez, con el grosor o el tamaño que dice ``Object.geoblender.look``
(``line_width`` y ``point_size``), solo los objetos visibles de los tipos de :mod:`.style` **que tienen ese valor
guardado**: sin valor guardado no dibuja nada y la vista queda como la dibuja Blender. Un grosor guardado de 1 px o
menos tampoco dibuja (no se puede afinar el alambre de Blender, solo engrosarlo).

Qué se dibuja lo decide :func:`.style.plan` (puro); aquí solo se arma el lote de ``gpu`` (uno por malla, con la
caché por ``session_uid``, rehecho si cambia la geometría o el color) y se pinta con las mismas reglas que las
curvas maestras: prueba de profundidad ``LESS_EQUAL`` sin escribir profundidad y el trazo acercado a la cámara.
Un error al dibujar se registra una vez y se apaga hasta volver a registrar.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import bpy
import gpu
import numpy as np
from bpy.app.handlers import persistent
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

from ..scene.mesh import mesh_edges, mesh_vertices_local
from . import contours, style

__all__ = ["draw_strokes", "drawing", "register", "unregister"]

LOGGER = logging.getLogger("geoblender.bl.draw")

LINE_SHADER = contours.SHADER
POINT_SHADER = "POINT_FLAT_COLOR"


@dataclass
class _Entry:
    signature: tuple[Any, ...]
    batch: Any


_cache: dict[tuple[int, str], _Entry] = {}
_handle: Any = None
_failed = False


def drawing() -> bool:
    """Si la superposición está registrada (dibuja en cada Vista 3D)."""
    return _handle is not None


def _batch(mesh: bpy.types.Mesh, primitive: str, shader: Any, color: Sequence[float]) -> Any:
    """El lote de las aristas (``LINES``) o los vértices (``POINTS``) de ``mesh``: de la caché o nuevo si cambió su
    geometría o el color; ``None`` si no hay nada que dibujar."""
    signature = (len(mesh.vertices), len(mesh.edges), tuple(round(float(c), 4) for c in color))
    key = (mesh.session_uid, primitive)
    entry = _cache.get(key)
    if entry is None or entry.signature != signature:
        positions = mesh_vertices_local(mesh)
        batch = None
        if primitive == "LINES" and len(mesh.edges):
            batch = batch_for_shader(shader, "LINES", {"pos": positions[mesh_edges(mesh).ravel()]})
        elif primitive == "POINTS" and len(positions):
            colors = np.tile(np.asarray(color, dtype=np.float32), (len(positions), 1))
            batch = batch_for_shader(shader, "POINTS", {"pos": positions, "color": colors})
        entry = _Entry(signature, batch)
        _cache[key] = entry
    return entry.batch


def draw_strokes(strokes: Sequence[tuple[style.Stroke, Sequence[float]]], *, view_matrix: Matrix,
                 projection_matrix: Matrix, perspective: bool, view_distance: float,
                 viewport_size: tuple[float, float]) -> int:
    """Dibuja en el *framebuffer* activo cada ``(trazo, color RGBA)`` de ``strokes`` con las matrices dadas (la de
    vista, acercada a la cámara) y la prueba de profundidad ``LESS_EQUAL`` sin escribir profundidad; deja el estado de
    ``gpu`` como estaba. Devuelve cuántos objetos dibujó."""
    if not strokes:
        return 0
    lines = gpu.shader.from_builtin(LINE_SHADER)
    points = gpu.shader.from_builtin(POINT_SHADER)
    view = contours._pulled(view_matrix, perspective, view_distance)
    drawn = 0
    state = (gpu.state.depth_test_get(), gpu.state.depth_mask_get(), gpu.state.blend_get())
    with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
        gpu.matrix.load_projection_matrix(projection_matrix)
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.depth_mask_set(False)
        gpu.state.blend_set("ALPHA")
        try:
            for stroke, color in strokes:
                obj = stroke.obj
                if stroke.primitive == "LINES":
                    batch = _batch(obj.data, "LINES", lines, color)
                    if batch is None:
                        continue
                    gpu.matrix.load_matrix(view @ obj.matrix_world)
                    lines.uniform_float("viewportSize", tuple(viewport_size))
                    lines.uniform_float("lineWidth", stroke.size_px)
                    lines.uniform_float("color", tuple(color))
                    batch.draw(lines)
                else:
                    batch = _batch(obj.data, "POINTS", points, color)
                    if batch is None:
                        continue
                    gpu.matrix.load_matrix(view @ obj.matrix_world)
                    gpu.state.point_size_set(stroke.size_px)
                    batch.draw(points)
                drawn += 1
        finally:
            gpu.state.point_size_set(1.0)
            gpu.state.depth_test_set(state[0])
            gpu.state.depth_mask_set(state[1])
            gpu.state.blend_set(state[2])
    return drawn


def _colored(context: Any, space: Any) -> list[tuple[style.Stroke, tuple[float, ...]]]:
    """Los trazos de los objetos visibles en ``space`` con su color (el del aspecto, o el del tema si no lo tiene o
    está seleccionado)."""
    view_layer = context.view_layer
    active = view_layer.objects.active
    theme = context.preferences.themes[0].view_3d
    pixel_size = float(context.preferences.system.pixel_size)
    found: list[tuple[style.Stroke, tuple[float, ...]]] = []
    for stroke in style.plan(style.candidates(), pixel_size=pixel_size):
        obj = stroke.obj
        if obj.type != "MESH" or obj.mode == "EDIT" or not obj.visible_get(view_layer=view_layer, viewport=space):
            continue
        if stroke.own_color and not obj.select_get():
            color = (float(obj.color[0]), float(obj.color[1]), float(obj.color[2]), 1.0)
        else:
            color = contours._color(obj, active, theme)
        found.append((stroke, color))
    return found


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
        strokes = _colored(context, space)
        if strokes:
            draw_strokes(strokes, view_matrix=gpu.matrix.get_model_view_matrix(),
                         projection_matrix=gpu.matrix.get_projection_matrix(), perspective=bool(rv3d.is_perspective),
                         view_distance=float(rv3d.view_distance), viewport_size=(float(region.width), float(region.height)))
    except Exception:  # una traza por fotograma no ayuda a nadie
        _failed = True
        LOGGER.exception("No se pueden dibujar el grosor y el tamaño del aspecto: la superposición se apaga")


@persistent
def _on_undo_or_load(*_args: Any) -> None:
    """Tras abrir un ``.blend`` o deshacer, los objetos con valor guardado pueden ser otros: se vuelven a buscar."""
    style.invalidate()


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
            for key in [key for key in _cache if key[0] == data.session_uid]:
                del _cache[key]
    alive = {mesh.session_uid for mesh in bpy.data.meshes}
    for key in [key for key in _cache if key[0] not in alive]:
        del _cache[key]


def _REBUILD_HANDLERS() -> tuple[Any, ...]:
    handlers = bpy.app.handlers
    return (handlers.load_post, handlers.undo_post, handlers.redo_post)


def register() -> None:
    """Pone el manejador de dibujo y el de actualización; si ya están, nada."""
    global _handle, _failed
    if _handle is None:
        _handle = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_VIEW")
    for handlers in _REBUILD_HANDLERS():
        if _on_undo_or_load not in handlers:
            handlers.append(_on_undo_or_load)
    style.invalidate()
    if _on_depsgraph not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)
    _failed = False


def unregister() -> None:
    """Quita los dos manejadores y suelta los lotes; si no están, nada."""
    global _handle
    for handlers in _REBUILD_HANDLERS():
        if _on_undo_or_load in handlers:
            handlers.remove(_on_undo_or_load)
    if _on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph)
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, "WINDOW")
        _handle = None
    _cache.clear()
