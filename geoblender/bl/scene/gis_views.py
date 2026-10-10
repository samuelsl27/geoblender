# SPDX-License-Identifier: GPL-3.0-or-later
"""Los cargadores de vista de la topografía (spec 006, T27; RF-006-19, RF-006-21, RF-006-22;
plan 006 §5.1 y §5.4 A15; ADR-0005).

:func:`register` los registra en ``bl.scene.views`` por el comienzo del nombre de sus datos
(``gis.provenance``) y :func:`unregister` los quita:

- **rejillas** (``gis_src_``, ``gis_dtm_``; :func:`load_grid`): la malla de A13 (los centros de
  las celdas con dato, ``gis.tin.raster_to_tin``) en un objeto; con un nivel de detalle
  (RF-006-22), la de la versión de 2 o 5 m (``gis.view.lod_steps_m`` del proyecto, leído sin
  escribirlo; si no lo tiene, el valor por defecto) por media de área
  (``gis.mesh.lod_rasters``), sin tocar la rejilla de cálculo; una rejilla de paso de 2 m o
  más se carga entera, con un aviso;
- **TIN** (``gis_tin_``; :func:`load_tin`): sus vértices y sus triángulos;
- **puntos** (``gis_pts_``; :func:`load_points`): una malla de vértices sueltos;
- **líneas de rotura y curvas** (``gis_brk_``, ``gis_cnt_``; :func:`load_lines`): una malla de
  aristas, una polilínea por entidad; la curva cerrada sin su vértice repetido y con la arista
  que la cierra.

Antes de nada, el dato debe estar en el CRS y la referencia vertical del proyecto
(``gis.store.require_project_references``): la vista no transforma coordenadas (principio 6).
Las coordenadas absolutas del dominio (float64) pasan a locales con ``bl.scene.mesh`` y la malla
de una superficie se **comprueba** en lo que guarda Blender, vuelta a absolutas
(``gis.mesh.check_surface_mesh``, RF-006-21): si tiene caras hacia abajo o degeneradas o su
volumen no es el de la superficie, se borra y no se muestra (``gis.mesh_invalid``, con las caras
que fallan y la diferencia en m³).
"""

from __future__ import annotations

from collections.abc import Sequence

import bpy
import numpy as np

from ...core.i18n import format_number, tr
from ...core.params.store import ParameterStore
from ...gis import params as gis_params
from ...gis.mesh import LOD_STEPS_KEY, check_surface_mesh, lod_rasters, surface_mesh_from_tin
from ...gis.provenance import (
    BREAKLINES,
    CONTOUR_LINES,
    FAMILIES_BY_CODE,
    POINTS,
    PROJECT_GRID,
    SOURCE_GRID,
    TIN,
)
from ...gis.tin import Tin, raster_to_tin
from . import views
from .mesh import mesh_from_arrays, mesh_triangles, mesh_vertices_local, mesh_vertices_world

__all__ = ["LOADERS", "load_grid", "load_lines", "load_points", "load_tin", "register",
           "unregister"]


def _bounds(mesh: bpy.types.Mesh) -> tuple[np.ndarray, np.ndarray] | None:
    """Los mínimos y máximos locales de la malla, tal como los guarda Blender."""
    local = mesh_vertices_local(mesh)
    if not len(local):
        return None
    return local.min(axis=0).astype(np.float64), local.max(axis=0).astype(np.float64)


def _object(name: str, mesh: bpy.types.Mesh, notes: Sequence[str] = ()) -> views.ViewParts:
    return views.ViewParts((bpy.data.objects.new(name, mesh),), _bounds(mesh), tuple(notes))


def lod_steps(project: object) -> tuple[float, ...]:
    """Los pasos de los niveles de detalle del proyecto (``gis.view.lod_steps_m``, de control:
    se lee sin registrarlo; si el proyecto no lo tiene, su valor por defecto)."""
    record = ParameterStore(project).get(LOD_STEPS_KEY)  # type: ignore[arg-type]
    found = None if record is None else record.value
    value = gis_params.default(LOD_STEPS_KEY) if found is None else found
    return tuple(float(step) for step in value)  # type: ignore[union-attr]


def _surface(request: views.ViewRequest, tin: Tin, name: str,
             notes: Sequence[str] = ()) -> views.ViewParts:
    """El objeto de la malla de la superficie ``tin`` (``gis.mesh.surface_mesh_from_tin``),
    comprobada en lo que guarda Blender frente a ``tin`` (RF-006-21): si no es válida, se
    borra y se lanza ``gis.mesh_invalid``."""
    arrays = surface_mesh_from_tin(tin)
    mesh = mesh_from_arrays(name, arrays.vertices, arrays.faces, origin=request.origin)
    try:
        report = check_surface_mesh(mesh_vertices_world(mesh, request.origin),
                                    mesh_triangles(mesh), tin, name=request.record.name)
        error = report.error()
        if error is not None:
            raise error
    except BaseException:
        bpy.data.meshes.remove(mesh)
        raise
    return _object(name, mesh, notes)


def load_grid(request: views.ViewRequest) -> views.ViewParts:
    """Una rejilla (``gis_src_``, ``gis_dtm_``) como malla de superficie; con ``lod`` 1 o 2, su
    versión de 2 o 5 m (RF-006-22)."""
    from ...gis import store  # al cargar: no al habilitar

    store.require_project_references(request.project, request.record)
    raster = store.load_raster(request.project, request.record)
    surface, name, notes = raster, request.name, []
    if request.lod > 0:
        steps = lod_steps(request.project)
        levels = lod_rasters(raster, steps)
        if levels:
            step = steps[min(request.lod, len(steps)) - 1]
            surface = levels[step]
            name = f"{request.name} · {format_number(step, 1)} m"
        else:
            notes.append(tr("The grid «{name}» already has a step of {step} m or more: it is "
                            "loaded whole", name=request.record.name,
                            step=format_number(steps[0], 1)))
    return _surface(request, raster_to_tin(surface, name=request.record.name), name, notes)


def load_tin(request: views.ViewRequest) -> views.ViewParts:
    """Un TIN (``gis_tin_``) como malla de superficie."""
    from ...gis import store

    store.require_project_references(request.project, request.record)
    return _surface(request, store.load_tin(request.project, request.record), request.name)


def load_points(request: views.ViewRequest) -> views.ViewParts:
    """Los puntos (``gis_pts_``) como vértices sueltos."""
    from ...gis import store

    store.require_project_references(request.project, request.record)
    found = store.load_features(request.project, request.record)
    vertices = (np.vstack(found.geometries) if found.geometries
                else np.empty((0, 3), dtype=np.float64))
    return _object(request.name, mesh_from_arrays(request.name, vertices,
                                                  origin=request.origin))


def _polylines(geometries: Sequence[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Los vértices y las aristas de unas polilíneas: cada una, sus tramos consecutivos; la
    cerrada (último vértice igual al primero), sin el repetido y con la arista de cierre."""
    vertices: list[np.ndarray] = []
    edges: list[np.ndarray] = []
    start = 0
    for coords in geometries:
        closed = len(coords) > 2 and np.array_equal(coords[0], coords[-1])
        points = coords[:-1] if closed else coords
        count = len(points)
        first = np.arange(start, start + count - 1, dtype=np.int32)
        pairs = np.column_stack([first, first + 1])
        if closed:
            pairs = np.vstack([pairs, [[start + count - 1, start]]])
        vertices.append(points)
        edges.append(pairs)
        start += count
    if not vertices:
        return np.empty((0, 3), dtype=np.float64), np.empty((0, 2), dtype=np.int32)
    return np.vstack(vertices), np.vstack(edges).astype(np.int32)


def load_lines(request: views.ViewRequest) -> views.ViewParts:
    """Las líneas de rotura o las curvas (``gis_brk_``, ``gis_cnt_``) como aristas."""
    from ...gis import store

    store.require_project_references(request.project, request.record)
    found = store.load_features(request.project, request.record)
    vertices, edges = _polylines(found.geometries)
    return _object(request.name, mesh_from_arrays(request.name, vertices, edges=edges,
                                                  origin=request.origin))


LOADERS: tuple[tuple[str, str, str, views.ViewLoader], ...] = (
    (SOURCE_GRID, "DTM", "Source DTM", load_grid),
    (PROJECT_GRID, "DTM", "DTM", load_grid),
    (TIN, "TIN", "TIN", load_tin),
    (POINTS, "POINTS", "Points", load_points),
    (BREAKLINES, "BREAKLINES", "Breaklines", load_lines),
    (CONTOUR_LINES, "CONTOURS", "Contour lines", load_lines),
)
"""Los cargadores de la topografía: familia (``gis.provenance``), tipo del objeto, ``msgid`` del
tipo en su nombre generado y función."""


def register() -> None:
    """Registra los cargadores de la topografía que aún no están; idempotente."""
    current = views.loaders()
    for family, kind, label, load in LOADERS:
        prefix = FAMILIES_BY_CODE[family].prefix
        if prefix not in current:
            views.register_loader(prefix, kind, label, load)


def unregister() -> None:
    """Quita los cargadores de la topografía (los de otro con el mismo comienzo, no);
    idempotente."""
    current = views.loaders()
    for family, _kind, _label, load in reversed(LOADERS):
        prefix = FAMILIES_BY_CODE[family].prefix
        found = current.get(prefix)
        if found is not None and found.load is load:
            views.unregister_loader(prefix)
