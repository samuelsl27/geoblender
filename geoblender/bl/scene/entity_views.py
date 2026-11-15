# SPDX-License-Identifier: GPL-3.0-or-later
"""La entidad de diseño en la vista (spec 015, T28; HU-015-1; RF-015-25; plan 015 §5.1; ADR-0005, ADR-0030).

:func:`register` registra en ``bl.scene.views`` el cargador de la tabla de una entidad (``des_epr_<nombre>``,
:func:`load_entity`) y :func:`unregister` lo quita (desactivar Geoblender no deja ninguno). Sus objetos son del tipo
:data:`KIND` (``DESIGN_ENTITY``, ``Object.geoblender.kind``), que lleva la barra N «Entidad» y las líneas más de
«Elemento activo» (``bl.ui.des_panels``). Lo que hace la vista con lo cargado (la colección de su versión,
``Object.geoblender`` con sus cifras registradas, su nombre generado, el recorte) es de ``views``, como con los demás datos.

**Qué se dibuja.** Un objeto por entidad, **en alambre** y delante de lo demás, con su **huella** (el contorno de sus celdas
sin resguardo, sus huecos incluidos: ``design.entities.declared_zone_of_runs``) y su **eje** (los vértices que guarda la
tabla), con las aristas del eje marcadas con el atributo :data:`AXIS_ATTRIBUTE` (la huella, sin marcar). Los datos son los
de la tabla de la entidad —sus tramos de fila y su eje, absolutos y en float64— y la cota de cada vértice es la de la
**superficie que dejó** la entidad (``des_psf_<nombre>``, la media de las celdas de su huella que tocan el vértice; el
eje, la del vértice de rejilla más próximo): el contorno queda sobre la plataforma. Los vértices absolutos pasan a locales
con ``bl.scene.mesh`` (ADR-0005). La vista no transforma coordenadas: una superficie en otro CRS o referencia vertical que
el proyecto se rechaza (``gis.view_references_mismatch``).

**Se regenera de la base**: un ``.blend`` es una vista, no la fuente de verdad. Borrar el objeto y cargar de nuevo lo deja
igual (mismos vértices, mismas aristas, mismo nombre). Cargar no escribe nada en el proyecto ni cambia ninguna operación.
Se carga **en pasos** (RNF-006-09): cerrados antes de terminar, no dejan nada.
"""

from __future__ import annotations

from collections.abc import Generator

import bpy
import numpy as np

from ...core.versions import read as versions_read
from ...design import provenance as design_provenance
from . import des_views, views
from .gis_views import _object, _polylines
from .mesh import mesh_from_arrays, mesh_vertices_local, set_edge_flags

__all__ = ["AXIS_ATTRIBUTE", "COLORS", "KIND", "LABEL", "PREFIX", "corner_heights", "load_entity", "register",
           "surface_name", "unregister"]

KIND = "DESIGN_ENTITY"
"""El tipo (``Object.geoblender.kind``) de los objetos de una entidad de diseño."""
LABEL = "Design entity"
"""El ``msgid`` del tipo en el nombre generado de sus objetos («Entidad de diseño carga · V01 [VIGENTE]»)."""
PREFIX = design_provenance.FAMILIES_BY_CODE[design_provenance.ENTITY_TABLE].prefix
"""El comienzo del nombre del dato que carga (``des_epr_``: la tabla de la entidad)."""
AXIS_ATTRIBUTE = "gb_axis"
"""El atributo de arista (booleano) de la malla de una entidad: verdadero en las aristas de su eje, falso en las de su
huella."""
COLORS: dict[str, tuple[float, float, float, float]] = {
    "platform": (0.1, 0.65, 0.55, 1.0),
}
"""El color (RGBA, 0 a 1) del objeto de cada tipo de entidad (``design.entities.EntityKind``): una ayuda para
distinguirlo en la vista, no un dato. La 016 añade los suyos."""
OTHER_COLOR = (0.6, 0.6, 0.6, 1.0)
"""El de un tipo de entidad que aún no tiene color."""
_CORNER_ROWS = np.array([-1, -1, 0, 0], dtype=np.int64)
_CORNER_COLS = np.array([-1, 0, -1, 0], dtype=np.int64)
"""Las cuatro celdas que tocan un vértice de rejilla ``(fila, columna)`` (sus líneas de fila y de columna): las de
arriba a la izquierda, arriba a la derecha, abajo a la izquierda y abajo a la derecha."""


def surface_name(table: str) -> str:
    """El nombre del dato de la superficie (``des_psf_<nombre>``) de la entidad cuya tabla es el dato ``table``
    (``des_epr_<nombre>``): el mismo nombre, con la familia de la superficie. ``ValueError`` si ``table`` no es la tabla de
    una entidad (un error del programa)."""
    if not table.startswith(PREFIX):
        raise ValueError(f"«{table}» no es la tabla de una entidad: su nombre empieza por «{PREFIX}»")
    prefix = design_provenance.FAMILIES_BY_CODE[design_provenance.ENTITY_SURFACE_GRID].prefix
    return prefix + table[len(PREFIX):]


def corner_heights(rows: np.ndarray, cols: np.ndarray, values: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """La cota de cada vértice de rejilla ``(rows[i], cols[i])`` (índices de las líneas de fila y de columna: el vértice
    entre las celdas ``fila − 1`` y ``fila``, ``columna − 1`` y ``columna``) como la **media** de ``values`` en las
    celdas de ``mask`` (la huella) que lo tocan y tienen dato; NaN si ninguna lo toca. Vectorizado: sin bucle por vértice."""
    height, width = values.shape
    r = np.asarray(rows, dtype=np.int64)[:, None] + _CORNER_ROWS
    c = np.asarray(cols, dtype=np.int64)[:, None] + _CORNER_COLS
    inside = (r >= 0) & (r < height) & (c >= 0) & (c < width)
    r, c = np.clip(r, 0, height - 1), np.clip(c, 0, width - 1)
    sampled = values[r, c]
    used = inside & mask[r, c] & np.isfinite(sampled)
    count = used.sum(axis=1)
    total = np.where(used, sampled, 0.0).sum(axis=1)
    return np.where(count > 0, total / np.maximum(count, 1), np.nan)


def load_entity(request: views.ViewRequest) -> Generator[float, None, views.ViewParts]:
    """Los pasos que cargan la tabla de entidad ``request.record`` (``des_epr_``): un objeto con su huella y su eje en
    alambre, a la cota de su superficie, en coordenadas locales y con matriz identidad (véase el módulo). Si se cierran o
    fallan a medias, borra lo que creó. Solo lee."""
    from ...design import entities, entity_store, surfaces  # al cargar: no al habilitar

    project, record = request.project, request.record
    with project.read() as conn:
        owner = versions_read.dataset_versions(conn, [record.uid]).get(record.uid, "")
        shape = entity_store.read_entity_footprint(conn, record.locator)
    yield 0.05
    surface = surfaces.read_surface(project, surface_name(record.name), version_uid=owner)
    des_views._check_references(project, surface, record.name)  # noqa: SLF001 - la misma comprobación
    yield 0.4
    grid = surface.grid
    footprint = entity_store.runs_mask(shape.runs, grid.shape)
    zone = entities.declared_zone_of_runs(shape.runs, grid, 0.0)
    rings = [ring for part in zone.parts for ring in part]
    axis = np.asarray(shape.axis, dtype=np.float64).reshape(-1, 2)
    paths = [*rings, *([axis] if len(axis) > 1 else [])]
    points = np.vstack(paths)
    heights = corner_heights(np.rint((grid.north - points[:, 1]) / grid.dy), np.rint((points[:, 0] - grid.west) / grid.dx),
                             surface.values, footprint)
    found = surface.values[footprint & np.isfinite(surface.values)]
    fallback = float(found.mean()) if found.size else float(request.origin.z0)
    heights = np.where(np.isfinite(heights), heights, fallback)
    shown: list[np.ndarray] = []
    start = 0
    for path in paths:
        shown.append(np.column_stack([path, heights[start:start + len(path)]]))
        start += len(path)
    yield 0.6
    vertices, edges, owners = _polylines(shown)
    flags = owners >= len(rings)  # el eje es el último camino
    mesh = mesh_from_arrays(request.name, vertices, edges=edges, origin=request.origin)
    try:
        set_edge_flags(mesh, AXIS_ATTRIBUTE, flags)
        parts = _object(request.name, mesh, (), mesh_vertices_local(mesh))
    except BaseException:
        bpy.data.meshes.remove(mesh)
        raise
    (obj,) = parts.objects
    try:
        obj.color = COLORS.get(shape.kind, OTHER_COLOR)
        obj.display_type = "WIRE"
        obj.show_in_front = True
        yield 0.95
    except BaseException:  # cerrados antes de terminar (Esc): no queda ni el objeto ni su malla
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(mesh)
        raise
    return parts


def register() -> None:
    """Registra el cargador de las tablas de entidad si aún no tiene uno; idempotente."""
    if PREFIX not in views.loaders():
        views.register_loader(PREFIX, KIND, LABEL, load_entity)


def unregister() -> None:
    """Quita el cargador de las tablas de entidad (el de otro con el mismo comienzo, no); idempotente."""
    found = views.loaders().get(PREFIX)
    if found is not None and found.load is load_entity:
        views.unregister_loader(PREFIX)
