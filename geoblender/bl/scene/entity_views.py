# SPDX-License-Identifier: GPL-3.0-or-later
"""La entidad de diseño en la vista (spec 015, T28; spec 016, T33; HU-015-1; RF-015-25, RF-016-14; plan 015 §5.1, plan 016 §5.5; ADR-0005,
ADR-0030).

:func:`register` registra en ``bl.scene.views`` los cargadores de la entidad de diseño (la tabla de una entidad, ``des_epr_<nombre>``,
:func:`load_entity`, y la tabla de acopios de una detección, ``des_stk_<nombre>``, :func:`load_stockpiles`) y :func:`unregister` los quita
(desactivar Geoblender no deja ninguno). Sus objetos son del tipo :data:`KIND` (``DESIGN_ENTITY``, ``Object.geoblender.kind``), que lleva la barra
N «Entidad» y las líneas más de «Elemento activo» (``bl.ui.des_panels``): **también el de una detección de acopios**, que es una entidad (``STK``,
sin cadena: spec 016, P-1) y sale en el mismo menú «Entidad ▾». Lo que hace la vista con lo cargado (la colección de su versión, ``Object.geoblender``
con sus cifras registradas, su nombre generado, el recorte) es de ``views``, como con los demás datos.

**Qué se dibuja.** Un objeto por entidad, **en alambre** y delante de lo demás, con su **huella** (el contorno de sus celdas sin resguardo, sus huecos
incluidos: ``design.entities.declared_zone_of_runs``) y su **eje** (los vértices que guarda la tabla), con las aristas del eje marcadas con el
atributo :data:`AXIS_ATTRIBUTE` (la huella, sin marcar). **De un contrafuerte** (T33; RF-016-17, P-8), además, el contorno de **su zona de coronación**
—la que declara «sin corte»— con sus aristas marcadas con :data:`ZONE_ATTRIBUTE`; el objeto de los demás tipos no lo lleva. Los datos son los de
la tabla de la entidad —sus tramos de fila, su eje y su zona, absolutos y en float64— y la cota de cada vértice es la de la **superficie que dejó**
la entidad (``des_psf_<nombre>``, la media de las celdas de su huella que tocan el vértice; el eje, la del vértice de rejilla más próximo): el
contorno queda sobre la plataforma. **Un cuerpo «bajo un techo»** no cambia la superficie (no deja ``des_psf_``): sus vértices toman la cota de su
**base** dispersa (``des_bds_<nombre>``). Los vértices absolutos pasan a locales con ``bl.scene.mesh`` (ADR-0005). La vista no transforma
coordenadas: una superficie en otro CRS o referencia vertical que el proyecto se rechaza (``gis.view_references_mismatch``).

**Una detección de acopios** (T33; spec 016, P-1: una detección es la entidad y cada acopio, una fila suya) es **un objeto por detección**, con la huella
de **cada acopio** a la cota de la superficie con que se detectó (``des_stp_<nombre>``, dispersa: solo tiene dato en las huellas). Cada acopio es
**una etiqueta por clave**: el grupo de vértices ``STK-001#m07`` (la referencia de :func:`design.provenance.support_ref`, la que usan «Retirar un
acopio…» y las cifras de lo apoyado) con los vértices de su contorno, y el atributo de arista :data:`STOCKPILE_ATTRIBUTE` con su posición en la tabla
de acopios (``-1`` en ninguna). Las demás cifras y estados de cada acopio no se guardan en el objeto: la barra N las lee del proyecto.

**Se regenera de la base**: un ``.blend`` es una vista, no la fuente de verdad. Borrar el objeto y cargar de nuevo lo deja igual (mismos vértices,
mismas aristas, mismo nombre). Cargar no escribe nada en el proyecto ni cambia ninguna operación. Se carga **en pasos** (RNF-006-09): cerrados antes de
terminar, no dejan nada.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator

import bpy
import numpy as np

from ...core.datasets import registry as dataset_registry
from ...core.i18n import tr
from ...core.versions import read as versions_read
from ...design import provenance as design_provenance
from . import des_views, views
from .gis_views import _object, _polylines
from .mesh import mesh_from_arrays, mesh_vertices_local, set_attribute, set_edge_flags

__all__ = ["AXIS_ATTRIBUTE", "COLORS", "KIND", "LABEL", "PREFIX", "STOCKPILES_LABEL", "STOCKPILES_PREFIX", "STOCKPILE_ATTRIBUTE",
           "ZONE_ATTRIBUTE", "base_name", "corner_heights", "detected_name", "group_name", "load_entity", "load_stockpiles", "register", "surface_name",
           "unregister"]

KIND = "DESIGN_ENTITY"
"""El tipo (``Object.geoblender.kind``) de los objetos de una entidad de diseño."""
LABEL = "Design entity"
"""El ``msgid`` del tipo en el nombre generado de sus objetos («Entidad de diseño carga · V01 [VIGENTE]»)."""
PREFIX = design_provenance.FAMILIES_BY_CODE[design_provenance.ENTITY_TABLE].prefix
"""El comienzo del nombre del dato que carga (``des_epr_``: la tabla de la entidad)."""
STOCKPILES_LABEL = "Stockpile detection"
"""El ``msgid`` del nombre de una detección de acopios en el nombre generado de su objeto («Detección de acopios Acopios · V01 [VIGENTE]»)."""
STOCKPILES_PREFIX = design_provenance.FAMILIES_BY_CODE[design_provenance.STOCKPILES_TABLE].prefix
"""El comienzo del nombre del dato que carga una detección (``des_stk_``: su tabla de acopios, una fila por acopio)."""
AXIS_ATTRIBUTE = "gb_axis"
"""El atributo de arista (booleano) de la malla de una entidad: verdadero en las aristas de su eje, falso en las de su
huella."""
ZONE_ATTRIBUTE = "gb_zone"
"""El atributo de arista (booleano) de la malla **de un contrafuerte** (T33): verdadero en las aristas del contorno de su zona de
coronación, falso en las de su huella. Los demás tipos no lo llevan."""
STOCKPILE_ATTRIBUTE = "gb_stockpile"
"""El atributo de arista (entero) de la malla de una detección de acopios (T33): la posición en la tabla de acopios del acopio al que
pertenece la arista; ``-1`` si no es de ninguno."""
GROUP_NAME_BYTES = 63
"""Lo que mide como mucho el nombre de un grupo de vértices de Blender (64 con el byte final)."""
COLORS: dict[str, tuple[float, float, float, float]] = {
    "platform": (0.1, 0.65, 0.55, 1.0),
    "stockpile": (0.85, 0.55, 0.1, 1.0),
    "removal": (0.8, 0.3, 0.25, 1.0),
    "buttress": (0.5, 0.4, 0.8, 1.0),
    "body": (0.3, 0.55, 0.85, 1.0),
}
"""El color (RGBA, 0 a 1) del objeto de cada tipo de entidad (``design.entities.EntityKind``): una ayuda para
distinguirlo en la vista, no un dato; los cuatro de la 016 (T33) son los de la detección, la retirada, el contrafuerte y el cuerpo."""
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


def base_name(table: str) -> str:
    """El nombre del dato de la base dispersa (``des_bds_<nombre>``) del cuerpo «bajo un techo» cuya tabla es el dato ``table``
    (``des_epr_<nombre>``): lo que da la cota a un cuerpo que no deja superficie (T33). ``ValueError`` si ``table`` no es la tabla de una
    entidad."""
    if not table.startswith(PREFIX):
        raise ValueError(f"«{table}» no es la tabla de una entidad: su nombre empieza por «{PREFIX}»")
    prefix = design_provenance.FAMILIES_BY_CODE[design_provenance.BODY_BASE_GRID].prefix
    return prefix + table[len(PREFIX):]


def detected_name(table: str) -> str:
    """El nombre del dato de la superficie con que se detectó (``des_stp_<nombre>``, dispersa: solo en las huellas) de la detección cuya
    tabla de acopios es el dato ``table`` (``des_stk_<nombre>``): el mismo nombre, con la familia de esa superficie (T33). ``ValueError`` si
    ``table`` no es la tabla de acopios de una detección (un error del programa)."""
    if not table.startswith(STOCKPILES_PREFIX):
        raise ValueError(f"«{table}» no es la tabla de acopios de una detección: su nombre empieza por «{STOCKPILES_PREFIX}»")
    prefix = design_provenance.FAMILIES_BY_CODE[design_provenance.STOCKPILE_SURFACE_GRID].prefix
    return prefix + table[len(STOCKPILES_PREFIX):]


def group_name(ref: str, taken: set[str]) -> str:
    """El nombre del grupo de vértices de un acopio: su referencia (``STK-001#m07``), recortada a lo que admite Blender
    (:data:`GROUP_NAME_BYTES` bytes en UTF-8, sin cortar un carácter) y, si ya hay uno igual en ``taken``, con ``~2``, ``~3``… (un recorte
    puede dar el mismo nombre a dos claves largas). Lo añade a ``taken``."""

    def fit(text: str, limit: int) -> str:
        while len(text.encode()) > limit:
            text = text[:-1]
        return text

    found = fit(ref, GROUP_NAME_BYTES)
    number = 1
    while found in taken:
        number += 1
        suffix = f"~{number}"
        found = fit(ref, GROUP_NAME_BYTES - len(suffix.encode())) + suffix
    taken.add(found)
    return found


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


def _height_dataset(conn: sqlite3.Connection, table: str, owner: str) -> str:
    """El dato que da la cota a la entidad de la tabla ``table``: su superficie (``des_psf_``) o, si no la dejó —un cuerpo «bajo un techo» no
    cambia la superficie—, su base dispersa (``des_bds_``) (T33). Lo que diga el registro, no el tipo: la tabla no guarda el sentido."""
    surface = surface_name(table)
    found = dataset_registry.get(conn, surface, version_uid=owner)
    return surface if found is not None and found.live else base_name(table)


def load_entity(request: views.ViewRequest) -> Generator[float, None, views.ViewParts]:
    """Los pasos que cargan la tabla de entidad ``request.record`` (``des_epr_``): un objeto con su huella y su eje en
    alambre —y, de un contrafuerte, el contorno de su zona de coronación—, a la cota de su superficie (de su base, si es un cuerpo «bajo un
    techo»), en coordenadas locales y con matriz identidad (véase el módulo). Si se cierran o fallan a medias, borra lo que creó. Solo lee."""
    from ...design import entities, entity_store, surfaces  # al cargar: no al habilitar

    project, record = request.project, request.record
    with project.read() as conn:
        owner = versions_read.dataset_versions(conn, [record.uid]).get(record.uid, "")
        shape = entity_store.read_entity_footprint(conn, record.locator)
        height = _height_dataset(conn, record.name, owner)
    yield 0.05
    surface = surfaces.read_surface(project, height, version_uid=owner)
    des_views._check_references(project, surface, record.name)  # noqa: SLF001 - la misma comprobación
    yield 0.4
    grid = surface.grid
    footprint = entity_store.runs_mask(shape.runs, grid.shape)
    zone = entities.declared_zone_of_runs(shape.runs, grid, 0.0)
    rings = [ring for part in zone.parts for ring in part]
    crown_rings: list[np.ndarray] = []
    shown = footprint
    if shape.zone is not None:  # un contrafuerte: el contorno de su zona de coronación (la que declara «sin corte»)
        crown = entities.declared_zone_of_runs(shape.zone, grid, 0.0)
        crown_rings = [ring for part in crown.parts for ring in part]
        shown = footprint | entity_store.runs_mask(shape.zone, grid.shape)
    axis = np.asarray(shape.axis, dtype=np.float64).reshape(-1, 2)
    paths = [*rings, *crown_rings, *([axis] if len(axis) > 1 else [])]
    points = np.vstack(paths)
    heights = corner_heights(np.rint((grid.north - points[:, 1]) / grid.dy), np.rint((points[:, 0] - grid.west) / grid.dx),
                             surface.values, shown)
    found = surface.values[shown & np.isfinite(surface.values)]
    fallback = float(found.mean()) if found.size else float(request.origin.z0)
    heights = np.where(np.isfinite(heights), heights, fallback)
    drawn: list[np.ndarray] = []
    start = 0
    for path in paths:
        drawn.append(np.column_stack([path, heights[start:start + len(path)]]))
        start += len(path)
    yield 0.6
    vertices, edges, owners = _polylines(drawn)
    flags = owners >= len(rings) + len(crown_rings)  # el eje es el último camino
    mesh = mesh_from_arrays(request.name, vertices, edges=edges, origin=request.origin)
    try:
        set_edge_flags(mesh, AXIS_ATTRIBUTE, flags)
        if shape.zone is not None:
            set_edge_flags(mesh, ZONE_ATTRIBUTE, (owners >= len(rings)) & ~flags)
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


def load_stockpiles(request: views.ViewRequest) -> Generator[float, None, views.ViewParts]:
    """Los pasos que cargan la tabla de acopios ``request.record`` (``des_stk_``) de una detección: **un objeto** con la huella de cada acopio
    en alambre y a la cota de la superficie con que se detectó (``des_stp_``), con un grupo de vértices por acopio (:func:`group_name`: su
    referencia ``STK-001#m07``) y el atributo de arista :data:`STOCKPILE_ATTRIBUTE` (véase el módulo; T33). Una detección sin acopios da el
    objeto vacío y lo dice. Si se cierran o fallan a medias, borra lo que creó. Solo lee."""
    from ...design import entities, entity_store, stockpile_store, surfaces  # al cargar: no al habilitar

    project, record = request.project, request.record
    with project.read() as conn:
        owner = versions_read.dataset_versions(conn, [record.uid]).get(record.uid, "")
        rows = stockpile_store.read_stored_rows(conn, design_provenance.STOCKPILES_TABLE, record.locator)
    yield 0.05
    notes: list[str] = []
    drawn: list[np.ndarray] = []
    owners_of: list[int] = []  # el acopio (su posición en la tabla) de cada camino
    refs: list[str] = []
    if rows:
        surface = surfaces.read_surface(project, detected_name(record.name), version_uid=owner)
        des_views._check_references(project, surface, record.name)  # noqa: SLF001 - la misma comprobación
        yield 0.3
        grid = surface.grid
        for position, row in enumerate(rows):
            runs = tuple((int(a), int(b), int(c)) for a, b, c in json.loads(str(row["footprint"])))
            refs.append(design_provenance.support_ref(str(row["code"]), str(row["key"])))
            mask = entity_store.runs_mask(runs, grid.shape)
            rings = [ring for part in entities.declared_zone_of_runs(runs, grid, 0.0).parts for ring in part]
            points = np.vstack(rings)
            heights = corner_heights(np.rint((grid.north - points[:, 1]) / grid.dy), np.rint((points[:, 0] - grid.west) / grid.dx),
                                     surface.values, mask)
            found = surface.values[mask & np.isfinite(surface.values)]
            heights = np.where(np.isfinite(heights), heights, float(found.mean()) if found.size else float(request.origin.z0))
            start = 0
            for ring in rings:
                drawn.append(np.column_stack([ring, heights[start:start + len(ring)]]))
                owners_of.append(position)
                start += len(ring)
            if position % 8 == 7:
                yield 0.3 + 0.3 * (position + 1) / len(rows)
    else:
        notes.append(tr("The stockpile detection «{name}» has no stockpiles: there is nothing to draw", name=record.name))
    yield 0.6
    vertices, edges, owners = _polylines(drawn)
    mesh = mesh_from_arrays(request.name, vertices, edges=edges, origin=request.origin)
    try:
        stockpile_of_edge = np.asarray(owners_of, dtype=np.int32)[owners] if len(owners) else np.empty(0, dtype=np.int32)
        set_attribute(mesh, STOCKPILE_ATTRIBUTE, "EDGE", "INT", stockpile_of_edge)
        parts = _object(request.name, mesh, notes, mesh_vertices_local(mesh))
    except BaseException:
        bpy.data.meshes.remove(mesh)
        raise
    (obj,) = parts.objects
    try:
        taken: set[str] = set()
        for position, ref in enumerate(refs):  # una etiqueta por clave: los vértices del contorno de cada acopio
            members = np.unique(edges[stockpile_of_edge == position]) if len(edges) else np.empty(0, dtype=np.int32)
            group = obj.vertex_groups.new(name=group_name(ref, taken))
            if len(members):
                group.add([int(index) for index in members], 1.0, "REPLACE")
        obj.color = COLORS["stockpile"]
        obj.display_type = "WIRE"
        obj.show_in_front = True
        yield 0.95
    except BaseException:  # cerrados antes de terminar (Esc): no queda ni el objeto ni su malla
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(mesh)
        raise
    return parts


def register() -> None:
    """Registra los cargadores de la tabla de una entidad y de la tabla de acopios de una detección si aún no tienen uno; idempotente."""
    current = views.loaders()
    if PREFIX not in current:
        views.register_loader(PREFIX, KIND, LABEL, load_entity)
    if STOCKPILES_PREFIX not in current:
        views.register_loader(STOCKPILES_PREFIX, KIND, STOCKPILES_LABEL, load_stockpiles)


def unregister() -> None:
    """Quita los cargadores de las tablas de entidad y de acopios (el de otro con el mismo comienzo, no); idempotente."""
    for prefix, load in ((STOCKPILES_PREFIX, load_stockpiles), (PREFIX, load_entity)):
        found = views.loaders().get(prefix)
        if found is not None and found.load is load:
            views.unregister_loader(prefix)
