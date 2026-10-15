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
- :func:`mesh_edges`, :func:`set_edge_flags` y :func:`edge_flags` (T55): las aristas, y un
  atributo booleano de arista (las de las curvas maestras), de una vez.
- (spec 005, T29) las caras de :func:`mesh_steps` pueden ser cuadriláteros (``(m, 4)``: las
  barras de leyes de los sondeos); :func:`curves_steps` crea unas curvas ``POLY``
  (``bpy.data.hair_curves``, el tipo ``Curves``: nacen Catmull-Rom y ``set_types`` las pasa a
  poligonales, plan 005 §2.1) con los puntos ABSOLUTOS pasados a locales igual que una malla, y
  :func:`curves_positions_local` los lee; :func:`set_attribute` pone un atributo (un color
  lineal, un entero, un sí/no…) de una vez a una malla o a unas curvas.

Un array con la forma o el tipo que no es, o un índice fuera de rango, es un error del programa
(``TypeError`` o ``ValueError``): la vista solo recibe lo que entrega el dominio.
"""

from __future__ import annotations

from collections.abc import Generator

import bpy
import numpy as np

from ...core.georef import GeoOrigin, local_to_world, world_to_local
from .. import compat

__all__ = ["curves_positions_local", "curves_steps", "edge_flags", "mesh_edges",
           "mesh_from_arrays", "mesh_steps", "mesh_triangles", "mesh_vertices_local",
           "mesh_vertices_world", "set_attribute", "set_edge_flags"]


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


def _local(points_world: np.ndarray, origin: GeoOrigin, what: str) -> np.ndarray:
    """Los puntos ABSOLUTOS ``points_world`` (float64 ``(n, 3)``, finitos) en locales respecto
    a ``origin`` con ``core.georef.world_to_local`` (en float64) y solo después en float32,
    como los guarda Blender."""
    world = np.asarray(points_world)
    if world.dtype != np.float64:
        raise TypeError(f"{what}: las coordenadas absolutas llegan en {world.dtype} y deben "
                        "llegar en float64 (ADR-0005)")
    if world.ndim != 2 or world.shape[1] != 3:
        raise ValueError(f"{what}: los vértices son (n, 3), no {world.shape}")
    if not np.isfinite(world).all():
        raise ValueError(f"{what}: hay coordenadas no finitas")
    return world_to_local(world, origin).astype(np.float32)


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
    local = _local(vertices_world, origin, "mesh_from_arrays")
    corners = 4 if faces is not None and np.ndim(faces) == 2 and np.shape(faces)[1] == 4 else 3
    polygons = _indices(faces, corners, len(local), "mesh_from_arrays (caras)")
    lines = _indices(edges, 2, len(local), "mesh_from_arrays (aristas)")
    yield 0.2
    mesh = bpy.data.meshes.new(name)
    try:
        mesh.vertices.add(len(local))
        compat.set_mesh_positions(mesh, local)
        if len(lines):
            mesh.edges.add(len(lines))
            mesh.edges.foreach_set("vertices", lines.ravel())
        if len(polygons):
            mesh.loops.add(polygons.size)
            compat.set_corner_verts(mesh, polygons.ravel())
            yield 0.4
            mesh.polygons.add(len(polygons))
            mesh.polygons.foreach_set("loop_start",
                                      np.arange(0, polygons.size, corners, dtype=np.intc))
            yield 0.7
        mesh.update(calc_edges=bool(len(polygons)))
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
    ``(m, 3)``, en el orden de sus vértices: antihorarios vistos desde arriba, normal +Z; o
    cuadriláteros, ``(m, 4)``) y las aristas ``edges`` (enteros ``(k, 2)``). Con caras, Blender
    añade sus aristas. No se enlaza a ningún objeto."""
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


def mesh_edges(mesh: bpy.types.Mesh) -> np.ndarray:
    """Las aristas de ``mesh`` (sus dos vértices, ``np.intc`` ``(k, 2)``, en su orden)."""
    return compat.mesh_edge_verts(mesh)


def set_edge_flags(mesh: bpy.types.Mesh, name: str, flags: np.ndarray) -> None:
    """El atributo booleano de arista ``name`` de ``mesh`` con un valor por arista (``flags``,
    en el orden de sus aristas), creado o sustituido, de una vez. ``ValueError`` si no hay
    un valor por arista."""
    values = np.ascontiguousarray(flags, dtype=bool).ravel()
    if len(values) != len(mesh.edges):
        raise ValueError(f"set_edge_flags: {len(values)} valores para las {len(mesh.edges)} "
                         f"aristas de «{mesh.name}»")
    found = mesh.attributes.get(name)
    if found is not None:
        mesh.attributes.remove(found)
    mesh.attributes.new(name, "BOOLEAN", "EDGE").data.foreach_set("value", values)


def edge_flags(mesh: bpy.types.Mesh, name: str) -> np.ndarray | None:
    """El atributo booleano de arista ``name`` de ``mesh`` (``bool`` ``(k,)``, en el orden de
    sus aristas), o ``None`` si no lo tiene así."""
    found = mesh.attributes.get(name)
    if found is None or (found.domain, found.data_type) != ("EDGE", "BOOLEAN"):
        return None
    values = np.empty(len(mesh.edges), dtype=bool)
    found.data.foreach_get("value", values)
    return values


# Curvas y atributos (spec 005, T29) ----------------------------------------------------------

_ATTRIBUTE_VALUES: dict[str, tuple[str, type, int]] = {
    "FLOAT_COLOR": ("color", np.float32, 4),
    "FLOAT": ("value", np.float32, 1),
    "INT": ("value", np.intc, 1),
    "BOOLEAN": ("value", np.bool_, 1),
}
"""Lo que se escribe de cada tipo de atributo (:func:`set_attribute`): la propiedad de cada
valor, el tipo exacto de numpy (con él, ``foreach_set`` copia de una vez) y sus componentes."""


def curves_steps(
    name: str,
    points_world: np.ndarray,
    sizes: np.ndarray,
    *,
    origin: GeoOrigin,
) -> Generator[float, None, bpy.types.Curves]:
    """Los pasos que crean las curvas nuevas ``name`` (``bpy.data.hair_curves``): ``sizes``
    (enteros ≥ 1) puntos cada una, de los puntos ABSOLUTOS ``points_world`` (float64 ``(n, 3)``,
    finitos, en orden), en locales respecto a ``origin`` (como :func:`mesh_steps`) y todas
    ``POLY`` (nacen Catmull-Rom: así sus tubos pasan por los puntos, plan 005 §2.1). Da su
    avance (0–1) tras cada paso y devuelve (``StopIteration.value``) las curvas, sin enlazar a
    ningún objeto. Si se cierran o fallan antes de terminar, se borran."""
    local = _local(points_world, origin, "curves_steps")
    counts = np.asarray(sizes)
    if counts.dtype.kind not in "iu" or counts.ndim != 1:
        raise TypeError(f"curves_steps: los puntos de cada curva son enteros (n,), no "
                        f"{counts.dtype} {counts.shape}")
    if len(counts) and int(counts.min()) < 1:
        raise ValueError("curves_steps: cada curva tiene al menos un punto")
    if int(counts.sum()) != len(local):
        raise ValueError(f"curves_steps: las curvas suman {int(counts.sum())} puntos y llegan "
                         f"{len(local)}")
    yield 0.2
    curves = bpy.data.hair_curves.new(name)
    try:
        curves.add_curves(counts.tolist())
        yield 0.5
        curves.set_types(type="POLY")
        curves.position_data.foreach_set("vector", np.ascontiguousarray(local).ravel())
    except BaseException:
        bpy.data.hair_curves.remove(curves)
        raise
    return curves


def curves_positions_local(curves: bpy.types.Curves) -> np.ndarray:
    """Los puntos de ``curves`` tal como los guarda Blender: locales, float32 ``(n, 3)``."""
    flat = np.empty(len(curves.points) * 3, dtype=np.float32)
    curves.position_data.foreach_get("vector", flat)
    return flat.reshape(-1, 3)


def set_attribute(data: bpy.types.ID, name: str, domain: str, data_type: str,
                  values: np.ndarray) -> None:
    """El atributo ``name`` de ``data`` (una malla o unas curvas) en el dominio ``domain``
    (``POINT``, ``CURVE``, ``FACE``…) del tipo ``data_type`` (``FLOAT_COLOR``, lineal con alfa,
    ``(k, 4)``; ``FLOAT``; ``INT``; ``BOOLEAN``) con un valor por elemento, creado o sustituido,
    de una vez. ``ValueError`` si no hay uno por elemento; ``KeyError`` con otro tipo."""
    key, kind, width = _ATTRIBUTE_VALUES[data_type]
    flat = np.ascontiguousarray(values, dtype=kind).ravel()
    found = data.attributes.get(name)
    if found is not None:
        data.attributes.remove(found)
    attribute = data.attributes.new(name, data_type, domain)
    if len(flat) != width * len(attribute.data):
        data.attributes.remove(attribute)
        raise ValueError(f"set_attribute: {len(flat) // width} valores de «{name}» para los "
                         f"{len(attribute.data)} elementos de «{data.name}»")
    attribute.data.foreach_set(key, flat)
