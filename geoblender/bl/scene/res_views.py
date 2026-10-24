# SPDX-License-Identifier: GPL-3.0-or-later
"""La vista de la rejilla de diferencias de una cubicación (spec 011, T22; RF-011-05, RF-011-23;
plan 011 §5.3.3, A15, D-25; ADR-0005).

:func:`register` registra en ``bl.scene.views`` el cargador de los datos ``res_dif_``
(:func:`load_difference`; tipo :data:`KIND`, ``VOLUME_DIFFERENCE``) y :func:`unregister` lo quita
(desactivar Geoblender no deja el cargador). Lo que hace la vista con lo cargado (la colección de
su versión, ``Object.geoblender`` con sus cifras registradas, su nombre generado, el recorte) es
de ``views``, como con los demás datos.

El cargador dibuja la superficie **final** de la operación que escribió la rejilla (la de sus
ajustes: un dato del proyecto o de la versión, lo congelado o una cota constante, a esa cota;
``reserves.store.stored_difference`` y ``difference_sources``) con la malla de la 006 (la de
``gis.mesh.surface_mesh_from_raster``: los centros de las celdas, con sus niveles de detalle y la
comprobación de la malla de ``bl.scene.gis_views``) y un **color por cara** en tres clases, con
``v = final − partida``, el valor de la rejilla (la media de las tres celdas de la cara):
desmonte (``v < −e``, rampa de rojos por magnitud), terraplén (``v > e``, rampa de azules) y sin
movimiento (gris); donde falta una de las dos superficies, sin cara. ``e`` es el espesor mínimo
que leyó la operación. El color va en el atributo de cara :data:`COLOR_ATTRIBUTE` (y la clase,
en :data:`CLASS_ATTRIBUTE`) con el material :data:`MATERIAL_NAME`, que lo pinta en «Vista previa
del material»; la cifra sale de la rejilla, nunca de la malla (plan §2.1).

Las dos superficies se leen por bandas (``reserves.surfaces.lockstep_bands``), un paso por
banda, como la cubicación: ningún paso pasa de unas décimas de segundo con 2,81 M celdas. La
vista no transforma coordenadas: una superficie final en otro CRS que el del proyecto se
rechaza (``gis.view_references_mismatch``).
"""

from __future__ import annotations

from collections.abc import Generator

import bpy
import numpy as np

from ...core.i18n import format_number, tr
from ...gis.crs import reference_label
from ...gis.grid import Grid
from ...gis.mesh import MeshArrays, lod_rasters
from ...gis.messages import GisError
from ...gis.raster import Raster
from ...gis.store import project_references
from ...gis.tin import raster_to_tin_steps
from ...reserves.provenance import DIFFERENCE_GRID, FAMILIES_BY_CODE
from ...reserves.surfaces import BAND_ROWS, lockstep_bands
from . import views
from .gis_views import _blocks, _scaled, _surface, lod_steps
from .mesh import set_attribute

__all__ = ["CLASS_ATTRIBUTE", "COLOR_ATTRIBUTE", "CUT", "FILL", "KIND", "LABEL",
           "MATERIAL_NAME", "STILL", "difference_colors", "ensure_material", "load_difference",
           "register", "unregister"]

KIND = "VOLUME_DIFFERENCE"
"""El tipo (``Object.geoblender.kind``) del objeto de una rejilla de diferencias."""
LABEL = "Difference grid"
"""El ``msgid`` del tipo en el nombre generado de sus objetos («Rejilla de diferencias …»)."""
PREFIX = FAMILIES_BY_CODE[DIFFERENCE_GRID].prefix
"""El comienzo del nombre de los datos que carga (``res_dif_``)."""
COLOR_ATTRIBUTE = "gb_color"
"""El atributo de cara con el color lineal de su clase."""
CLASS_ATTRIBUTE = "gb_class"
"""El atributo de cara con su clase: :data:`STILL`, :data:`CUT` o :data:`FILL`."""
STILL, CUT, FILL = 0, 1, 2
"""Las clases de una cara: sin movimiento, desmonte y terraplén."""
MATERIAL_NAME = "GB_VolumeDifference"
"""El material de la vista de las rejillas de diferencias (su color, el de cada cara)."""
VERSION = 1
"""La versión del material: cambiarlo aquí es subirla."""
VERSION_PROPERTY = "geoblender_version"
"""La propiedad de ID con la versión del material."""
_GRAY = (0.5, 0.5, 0.5, 1.0)
_RAMPS = {CUT: ((1.0, 0.65, 0.65, 1.0), (0.6, 0.0, 0.0, 1.0)),
          FILL: ((0.65, 0.65, 1.0, 1.0), (0.0, 0.0, 0.6, 1.0))}
"""Los colores lineales de cada rampa, de la diferencia más pequeña a la mayor de su clase."""


def difference_colors(values: np.ndarray, threshold_m: float) -> tuple[np.ndarray, np.ndarray]:
    """La clase (``np.intc``) y el color lineal con alfa (``(n, 4)``, float32) de cada cara de
    diferencia ``values`` (m, finita) con el espesor mínimo ``threshold_m`` (A15): desmonte por
    debajo de −e, terraplén por encima de e y sin movimiento entre los dos; el desmonte y el
    terraplén, más oscuros cuanto mayor es su diferencia frente a la mayor de su clase."""
    found = np.asarray(values, dtype=np.float64)
    classes = np.full(len(found), STILL, dtype=np.intc)
    classes[found < -threshold_m] = CUT
    classes[found > threshold_m] = FILL
    colors = np.tile(np.asarray(_GRAY, dtype=np.float64), (len(found), 1))
    for klass, (low, high) in _RAMPS.items():
        chosen = classes == klass
        if not chosen.any():
            continue
        size = np.abs(found[chosen])
        top = float(size.max())
        share = size / top if top > 0.0 else np.ones_like(size)
        colors[chosen] = (np.asarray(low) + (np.asarray(high) - np.asarray(low))
                          * share[:, None])
    return classes, colors.astype(np.float32)


def ensure_material() -> bpy.types.Material:
    """El material :data:`MATERIAL_NAME` de esta versión: el que hay o uno nuevo (o rehecho en
    su sitio): su color base, el atributo :data:`COLOR_ATTRIBUTE` de la geometría; en la vista
    sólida, gris. Es un dato de la escena (se guarda con el ``.blend``), no de la extensión."""
    material = bpy.data.materials.get(MATERIAL_NAME)
    if material is not None and material.get(VERSION_PROPERTY) == VERSION:
        return material
    if material is None:
        material = bpy.data.materials.new(MATERIAL_NAME)
    material.diffuse_color = _GRAY
    tree = material.node_tree
    if tree is not None:  # en 5.2 nace con el BSDF principista y la salida
        for node in list(tree.nodes):
            tree.nodes.remove(node)
        output = tree.nodes.new("ShaderNodeOutputMaterial")
        shader = tree.nodes.new("ShaderNodeBsdfPrincipled")
        attribute = tree.nodes.new("ShaderNodeAttribute")
        attribute.attribute_type = "GEOMETRY"
        attribute.attribute_name = COLOR_ATTRIBUTE
        attribute.location = (-300.0, 0.0)
        output.location = (300.0, 0.0)
        tree.links.new(attribute.outputs["Color"], shader.inputs["Base Color"])
        tree.links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    material[VERSION_PROPERTY] = VERSION
    return material


def _vertex_values(vertices: np.ndarray, grid: Grid, values: np.ndarray) -> np.ndarray:
    """El valor de ``values`` (en ``grid``) en cada vértice de una malla de A13: el de la celda
    de la que es centro."""
    columns = np.rint((vertices[:, 0] - grid.west) / grid.dx - 0.5).astype(np.int64)
    rows = np.rint((grid.north - vertices[:, 1]) / grid.dy - 0.5).astype(np.int64)
    return values[rows, columns]


def load_difference(request: views.ViewRequest) -> Generator[float, None, views.ViewParts]:
    """La rejilla de diferencias ``res_dif_`` de ``request`` sobre su superficie final, con el
    color de sus tres clases (véase el módulo), en pasos; con ``lod`` 1 o 2, su versión de 2 o
    5 m (las dos superficies, por media de área). Cerrados antes de terminar, borra lo que
    creó."""
    from ...reserves import store  # al cargar: no al habilitar

    project = request.project
    stored = store.stored_difference(project, request.record.uid)
    final, difference = store.difference_sources(project, stored)
    crs, vertical = project_references(project)
    if (final.header.crs, final.header.vertical) != (crs, vertical):
        raise GisError("gis.view_references_mismatch", obj=f"«{request.record.name}»",
                       field="CRS", value=reference_label(final.header.crs,
                                                          final.header.vertical),
                       name=final.name, expected=reference_label(crs, vertical))
    grid = difference.grid
    assert grid is not None  # difference_sources la lee de su GeoTIFF
    heights = np.full(grid.shape, np.nan, dtype=np.float64)
    moved = np.full(grid.shape, np.nan, dtype=np.float64)
    yield 0.02
    bands = lockstep_bands((final, difference), grid, rows=BAND_ROWS)
    try:
        for top, (height, value) in bands:
            stop = top + np.shape(value)[0]
            heights[top:stop] = height
            moved[top:stop] = value
            yield 0.02 + 0.08 * stop / grid.nrows
    finally:
        bands.close()
    shown = np.isfinite(heights) & np.isfinite(moved)  # sin dato en una de las dos: sin cara
    surface = Raster(grid, np.where(shown, heights, np.nan), crs, vertical)
    values = Raster(grid, np.where(shown, moved, np.nan), crs, vertical)
    name, notes = request.name, []
    if request.lod > 0:
        steps = lod_steps(project)
        levels = lod_rasters(surface, steps)
        if levels:
            step = steps[min(request.lod, len(steps)) - 1]
            surface, values = levels[step], lod_rasters(values, steps)[step]
            name = f"{request.name} · {format_number(step, 1)} m"
        else:
            notes.append(tr("The grid «{name}» already has a step of {step} m or more: it is "
                            "loaded whole", name=request.record.name,
                            step=format_number(steps[0], 1)))
    yield 0.12
    tin = yield from _scaled(_blocks(raster_to_tin_steps(surface, name=request.record.name)),
                             0.12, 0.25)
    faces = np.ascontiguousarray(tin.faces, dtype=np.int32)
    vertex_values = _vertex_values(tin.vertices, surface.grid, values.values)
    classes, colors = difference_colors(vertex_values[faces].mean(axis=1), stored.threshold_m)
    parts = yield from _surface(request, tin, MeshArrays(tin.vertices, faces), name, notes,
                                0.3)
    try:
        for obj in parts.objects:
            set_attribute(obj.data, COLOR_ATTRIBUTE, "FACE", "FLOAT_COLOR", colors)
            set_attribute(obj.data, CLASS_ATTRIBUTE, "FACE", "INT", classes)
            obj.data.materials.append(ensure_material())
    except BaseException:
        for obj in parts.objects:
            mesh = obj.data
            bpy.data.objects.remove(obj)
            bpy.data.meshes.remove(mesh)
        raise
    return parts


def register() -> None:
    """Registra el cargador de las rejillas de diferencias si aún no hay uno; idempotente."""
    if PREFIX not in views.loaders():
        views.register_loader(PREFIX, KIND, LABEL, load_difference)


def unregister() -> None:
    """Quita el cargador de las rejillas de diferencias (el de otro con el mismo comienzo, no);
    idempotente."""
    found = views.loaders().get(PREFIX)
    if found is not None and found.load is load_difference:
        views.unregister_loader(PREFIX)
