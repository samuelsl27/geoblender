# SPDX-License-Identifier: GPL-3.0-or-later
"""Los cargadores de vista de los límites y las restricciones (spec 012; plan 012 §5.3.3, §5.2.4;
ADR-0005).

**Intenciones del cliente** (T25; HU-012-6; RF-012-26): :func:`register` registra en
``bl.scene.views`` el cargador del dato ``core_intention`` (:func:`load_intentions`; tipo
:data:`KIND`, ``CLIENT_INTENTION``) y :func:`unregister` lo quita (desactivar Geoblender no deja el
cargador). Lo que hace la vista con lo cargado (la colección de su dato, ``Object.geoblender``, su
nombre generado, el recorte) es de ``views``, como con los demás datos.

Una intención es **un objeto**: su malla lleva sus aristas (el camino de una línea; los anillos de
un polígono, cerrados; y de un punto, el punto mismo como primer vértice y una cruz de
:data:`MARK_ARM_M` m de brazo, solo para verlo) a la cota Z del GeoOrigin (las intenciones no
tienen cota de dibujo: la cota de «explotar a una cota» es un dato de la marca, no su altura en la
vista). Los vértices se pasan a locales en float64 con ``bl.scene.mesh`` (ADR-0005) y vuelven a las
coordenadas absolutas de la marca. El nombre generado es «Intención del cliente [VIGENTE] · nombre
· papel», y el uid de la intención va en el objeto (:data:`INTENTION_PROPERTY`). Se carga **en
pasos** (un objeto cada uno, RNF-012-06): si se cierran antes de terminar, lo creado se borra.

El **estilo** de las intenciones (:data:`INTENTION_STYLE`) es el mismo para todas y distinto del de
las restricciones: alambre, delante de lo demás y un violeta que ninguno de los once tipos de
restricción usa. Nada de la vista entra en una máscara ni se escribe en el proyecto: leer las
intenciones y dibujarlas no registra ninguna operación (RF-012-26, error 30).
"""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

import bpy
import numpy as np

from ...core.constraints.model import GeometryKind, Intention
from ...core.constraints.store import INTENTION_TABLE, read_intentions
from ...core.i18n import language
from ...gis import store as gis_store
from ...reserves import surfaces as res_surfaces
from . import views
from .gis_views import _polylines
from .mesh import mesh_from_arrays, mesh_vertices_local

__all__ = ["INTENTION_PROPERTY", "INTENTION_STYLE", "KIND", "LABEL", "MARK_ARM_M", "PREFIX",
           "IntentionStyle", "intention_arrays", "load_intentions", "register", "terrain_choices",
           "unregister"]

KIND = "CLIENT_INTENTION"
"""El tipo (``Object.geoblender.kind``) del objeto de una intención del cliente."""
LABEL = "Client intention"
"""El ``msgid`` del tipo en el nombre generado de sus objetos («Intención del cliente …»)."""
PREFIX = INTENTION_TABLE
"""El comienzo del nombre del dato que carga (``core_intention``)."""
INTENTION_PROPERTY = "geoblender_intention"
"""La propiedad de ID del objeto con el uid de la intención que dibuja."""
MARK_ARM_M = 5.0
"""El brazo (m) de la cruz que se dibuja en cada punto: una ayuda para verlo, no un dato."""


@dataclass(frozen=True)
class IntentionStyle:
    """Cómo se ven las intenciones del cliente: el color de sus objetos (RGBA), cómo se
    muestran (``Object.display_type``) y si van delante de lo demás."""

    color: tuple[float, float, float, float]
    display_type: str
    show_in_front: bool


INTENTION_STYLE = IntentionStyle(color=(0.7, 0.25, 0.9, 1.0), display_type="WIRE",
                                 show_in_front=True)
"""El estilo de las intenciones (véase el módulo)."""


def _with_height(points: np.ndarray, z_m: float) -> np.ndarray:
    """Las coordenadas en planta ``(k, 2)`` con la cota ``z_m``: ``(k, 3)`` float64."""
    plan = np.asarray(points, dtype=np.float64)
    return np.column_stack([plan, np.full(len(plan), z_m, dtype=np.float64)])


def intention_arrays(intention: Intention, z_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Los vértices ABSOLUTOS (float64 ``(n, 3)``, a la cota ``z_m``) y las aristas (enteros
    ``(k, 2)``) con que se dibuja ``intention``: el camino de una línea, los anillos cerrados de un
    polígono (el repetido del cierre sale una vez) y, de cada punto, él mismo como primer vértice
    y una cruz de :data:`MARK_ARM_M` m."""
    if intention.kind is GeometryKind.POINT:
        vertices: list[np.ndarray] = []
        edges: list[np.ndarray] = []
        offsets = np.array([(0.0, 0.0), (MARK_ARM_M, 0.0), (-MARK_ARM_M, 0.0),
                            (0.0, MARK_ARM_M), (0.0, -MARK_ARM_M)], dtype=np.float64)
        for part in intention.parts:
            for point in part:
                start = 5 * len(edges)
                vertices.append(_with_height(point.reshape(-1, 2)[0] + offsets, z_m))
                edges.append(np.array([(start, start + arm) for arm in range(1, 5)],
                                      dtype=np.int32))
        return np.vstack(vertices), np.vstack(edges)
    paths = [_with_height(ring, z_m) for part in intention.parts for ring in part]
    found, pairs, _owners = _polylines(paths)
    return found, pairs


def load_intentions(request: views.ViewRequest) -> Generator[float, None, views.ViewParts]:
    """Los pasos que cargan las intenciones del cliente (``core_intention``) de ``request``: un
    objeto por intención (un paso cada una, su avance de 0 a 1: ninguna llamada pasa de unos
    milisegundos, RNF-012-06), con el estilo de :data:`INTENTION_STYLE`, en coordenadas locales y
    con matriz identidad (véase el módulo). Si se cierran o fallan a medias, borra lo que
    creó."""
    with request.project.read() as conn:
        found = read_intentions(conn)
    yield 0.0
    shown = language()
    z_m = float(request.origin.z0)
    style = INTENTION_STYLE
    objects: list[bpy.types.Object] = []
    lows: list[np.ndarray] = []
    highs: list[np.ndarray] = []
    try:
        for index, item in enumerate(found, start=1):
            vertices, edges = intention_arrays(item, z_m)
            name = f"{request.name} · {item.name} · {item.role.label(shown)}"
            mesh = mesh_from_arrays(name, vertices, edges=edges, origin=request.origin)
            try:
                obj = bpy.data.objects.new(name, mesh)
            except BaseException:
                bpy.data.meshes.remove(mesh)
                raise
            objects.append(obj)
            obj.color = style.color
            obj.display_type = style.display_type
            obj.show_in_front = style.show_in_front
            obj[INTENTION_PROPERTY] = item.uid
            local = mesh_vertices_local(mesh)
            lows.append(local.min(axis=0))
            highs.append(local.max(axis=0))
            yield index / len(found)
    except BaseException:
        for obj in objects:
            mesh = obj.data
            bpy.data.objects.remove(obj)
            bpy.data.meshes.remove(mesh)
        raise
    bounds = None
    if lows:
        bounds = (np.min(lows, axis=0).astype(np.float64),
                  np.max(highs, axis=0).astype(np.float64))
    return views.ViewParts(tuple(objects), bounds)


def terrain_choices(project: Any, version_uid: str | None) -> tuple[Any, ...]:
    """Las rejillas de terreno del proyecto sobre las que se puede dibujar (véase el módulo), por
    nombre, con la versión activa ``version_uid`` (``None``: sin versión): las superficies que
    ofrece la cubicación (``reserves.surfaces.surface_choices``: las vivas del proyecto y de la
    versión, no las congeladas ni las diferencias) que son un MDT importado o una rejilla del
    proyecto. Solo lee."""
    grids = {record.name for record in gis_store.list_gis_datasets(
        project, families=gis_store.GRID_FAMILIES)}
    return tuple(choice for choice in res_surfaces.surface_choices(
        project, version_uid=version_uid or "")
        if choice.ref.dataset is not None and choice.name in grids)


def register() -> None:
    """Registra el cargador de las intenciones si aún no hay uno; idempotente."""
    if PREFIX not in views.loaders():
        views.register_loader(PREFIX, KIND, LABEL, load_intentions)


def unregister() -> None:
    """Quita el cargador de las intenciones (el de otro con el mismo comienzo, no);
    idempotente."""
    found = views.loaders().get(PREFIX)
    if found is not None and found.load is load_intentions:
        views.unregister_loader(PREFIX)
