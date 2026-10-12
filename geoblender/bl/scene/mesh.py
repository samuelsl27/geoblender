# SPDX-License-Identifier: GPL-3.0-or-later
"""Mallas de Blender desde arrays de numpy, en coordenadas locales (spec 006, T27 y T50;
RF-006-19, RNF-006-06, RNF-006-09; plan 006 §5.1; ADR-0005).

- :func:`mesh_steps` y :func:`mesh_from_arrays`: una malla con los vértices ABSOLUTOS
  ``vertices_world`` (float64, CRS y datum del proyecto) pasados a locales respecto al
  GeoOrigin con ``core.georef.world_to_local`` (en float64) y solo después a float32, que es
  como Blender los guarda; con triángulos (``faces``) y aristas (``edges``) opcionales, todo
  de una vez (sin bucles de Python por elemento; las posiciones y las esquinas con los
  atributos de la malla, ``bl.compat``: 2,8 M vértices y 5,6 M triángulos en décimas en vez de
  segundos). Sin caras ni aristas, una nube de vértices sueltos. :func:`mesh_steps` la crea por
  pasos (cada llamada de Blender, uno: ninguno pasa de unas décimas con la rejilla de 2,81 M
  celdas, T50) para cargarla en la vista desde un temporizador con avance y Esc; si se cierra
  antes de terminar, la malla a medias se borra. :func:`mesh_from_arrays` la crea de una vez.
  El objeto que la use va con matriz identidad: el origen nunca va en ``Object.location``.
- :func:`mesh_vertices_local`, :func:`mesh_vertices_world` y :func:`mesh_triangles`: lo que
  guarda Blender, leído de una vez: los vértices locales (float32, tal como están), los
  mismos vueltos a absolutas con ``core.georef.local_to_world`` (float64) y los triángulos.
  Con ellos se comprueba la malla de una superficie (``gis.mesh.check_surface_mesh``) y la ida y
  vuelta (≤ 0,5 mm a ±8 km del GeoOrigin, RF-006-19).

Un array con la forma o el tipo que no es, o un índice fuera de rango, es un error del programa
(``TypeError`` o ``ValueError``): la vista solo recibe lo que entrega el dominio.
"""

from __future__ import annotations

from collections.abc import Generator

import bpy
import numpy as np

from ...core.georef import GeoOrigin, local_to_world, world_to_local
from .. import compat

__all__ = ["mesh_from_arrays", "mesh_steps", "mesh_triangles", "mesh_vertices_local",
           "mesh_vertices_world"]


def _indices(values: np.ndarray | None, width: int, count: int, what: str) -> np.ndarray:
    """Los índices ``(k, width)`` en ``np.intc`` (el entero de 32 bits de Blender), entre 0 y
    ``count`` − 1."""
    if values is None:
        return np.empty((0, width), dtype=np.intc)
    array = np.asarray(values)
    if array.dtype.kind not in "iu":
        raise TypeError(f"{what}: los índices son enteros, no {array.dtype}")
    if array.ndim != 2 or array.shape[1] != width:
        raise ValueError(f"{what}: la forma es (k, {width}), no {array.shape}")
    if len(array) and (int(array.min()) < 0 or int(array.max()) >= count):
        raise ValueError(f"{what}: hay índices fuera de los {count} vértices")
    return np.ascontiguousarray(array, dtype=np.intc)


def mesh_steps(
    name: str,
    vertices_world: np.ndarray,
    faces: np.ndarray | None = None,
    edges: np.ndarray | None = None,
    *,
    origin: GeoOrigin,
) -> Generator[float, None, bpy.types.Mesh]:
    """Los pasos que crean la malla nueva ``name`` (véase :func:`mesh_from_arrays`), con su
    avance (0–1) tras cada uno; devuelve (``StopIteration.value``) la malla, sin enlazar a
    ningún objeto. Si se cierran o fallan antes de terminar, la malla se borra."""
    world = np.asarray(vertices_world)
    if world.dtype != np.float64:
        raise TypeError(f"mesh_from_arrays: las coordenadas absolutas llegan en {world.dtype} y "
                        "deben llegar en float64 (ADR-0005)")
    if world.ndim != 2 or world.shape[1] != 3:
        raise ValueError(f"mesh_from_arrays: los vértices son (n, 3), no {world.shape}")
    if not np.isfinite(world).all():
        raise ValueError("mesh_from_arrays: hay coordenadas no finitas")
    triangles = _indices(faces, 3, len(world), "mesh_from_arrays (caras)")
    lines = _indices(edges, 2, len(world), "mesh_from_arrays (aristas)")
    local = world_to_local(world, origin).astype(np.float32)
    yield 0.2
    mesh = bpy.data.meshes.new(name)
    try:
        mesh.vertices.add(len(local))
        compat.set_mesh_positions(mesh, local)
        if len(lines):
            mesh.edges.add(len(lines))
            mesh.edges.foreach_set("vertices", lines.ravel())
        if len(triangles):
            mesh.loops.add(triangles.size)
            compat.set_corner_verts(mesh, triangles.ravel())
            yield 0.4
            mesh.polygons.add(len(triangles))
            mesh.polygons.foreach_set("loop_start",
                                      np.arange(0, triangles.size, 3, dtype=np.intc))
            yield 0.7
        mesh.update(calc_edges=bool(len(triangles)))
    except BaseException:
        bpy.data.meshes.remove(mesh)
        raise
    return mesh


def mesh_from_arrays(
    name: str,
    vertices_world: np.ndarray,
    faces: np.ndarray | None = None,
    edges: np.ndarray | None = None,
    *,
    origin: GeoOrigin,
) -> bpy.types.Mesh:
    """Una malla nueva ``name`` con los vértices ABSOLUTOS ``vertices_world`` (float64
    ``(n, 3)``, finitos) en locales respecto a ``origin``, los triángulos ``faces`` (enteros
    ``(m, 3)``, en el orden de sus vértices: antihorarios vistos desde arriba, normal +Z) y las
    aristas ``edges`` (enteros ``(k, 2)``). Con caras, Blender añade sus aristas. No se enlaza a
    ningún objeto."""
    steps = mesh_steps(name, vertices_world, faces, edges, origin=origin)
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            return stop.value


def mesh_vertices_local(mesh: bpy.types.Mesh) -> np.ndarray:
    """Los vértices de ``mesh`` tal como los guarda Blender: locales, float32 ``(n, 3)``."""
    return compat.mesh_positions(mesh)


def mesh_vertices_world(mesh: bpy.types.Mesh, origin: GeoOrigin) -> np.ndarray:
    """Los vértices de ``mesh`` vueltos a ABSOLUTOS respecto a ``origin`` (float64 ``(n, 3)``),
    con ``core.georef.local_to_world``."""
    return local_to_world(mesh_vertices_local(mesh), origin)


def mesh_triangles(mesh: bpy.types.Mesh) -> np.ndarray:
    """Los triángulos de ``mesh`` (int32 ``(m, 3)``, en el orden de sus esquinas);
    ``ValueError`` si alguna cara no es un triángulo."""
    totals = np.empty(len(mesh.polygons), dtype=np.intc)
    mesh.polygons.foreach_get("loop_total", totals)
    if len(totals) and not (totals == 3).all():
        raise ValueError(f"la malla «{mesh.name}» tiene caras que no son triángulos")
    return compat.mesh_corner_verts(mesh).astype(np.int32, copy=False).reshape(-1, 3)
