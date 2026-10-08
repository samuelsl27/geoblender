# SPDX-License-Identifier: GPL-3.0-or-later
"""TIN desde puntos y líneas de rotura (spec 006; plan 006 §5.2.2, §5.3.2 y §5.4 A11;
RF-006-13, RF-006-15).

Un TIN (:class:`Tin`) son vértices float64 ABSOLUTOS (en el CRS y el datum del proyecto),
triángulos antihorarios vistos desde arriba (normal +Z), las aristas obligatorias (roturas
duras) y el origen de cada vértice (``vertex_source``, plan §5.2.2): lo que se guarda en
``meshes/gis_tin_<slug>.npz``.

:func:`build_tin` (A11):

1. **Duplicados** (A7, ``gis.points``): los puntos que coinciden en planta a ≤ ``tol_xy``
   se funden; los que además difieren en cota más de ``tol_z`` se resuelven con la política
   elegida o paran con ``ConflictError`` (RF-006-14).
2. **Restricciones** (A8, ``gis.breaklines.prepare_constraints``): vértices de las roturas,
   cruces con su vértice nuevo en float64, puntos sobre una rotura y conflictos.
3. **Triangulación** por el puerto ``Triangulator`` (CDT de Blender o ``PureTriangulator``,
   ADR-0021) con coordenadas **locales** (``core.georef.world_to_local``): los vértices del
   TIN siguen siendo los de entrada, bit a bit (RF-006-13).
4. **Orientación**: cada triángulo, antihorario (signo exacto de ``gis.cdt.orient2d`` cuando
   el de float64 no es seguro).
5. **Filtros** (RF-006-15): fuera los triángulos con el centroide fuera del contorno o
   dentro de un hueco (paridad de rayos, vectorizada) y, de los que quedan, los que tienen
   algún lado en planta más largo que ``max_edge_m``. Quedan los vértices que usa algún
   triángulo (en su orden) y las aristas obligatorias que siguen siendo aristas.
6. **Estadísticas** (:class:`~gis.reports.TinReport`): triángulos planos (tres cotas
   iguales), lado máximo en planta y degenerados (área en planta < 10⁻⁶ m²).

Contorno y huecos: un anillo es un array float64 ``(k ≥ 3, 2 | 3)`` de coordenadas
ABSOLUTAS (la Z se ignora; cerrado o no). Una **región** es un anillo, la lista de anillos de
un ``POLYGON`` o la de polígonos de un ``MULTIPOLYGON`` (``core.gpkg.Geometry.coords``), o la
propia ``Geometry``: un centroide está dentro si cruza un número impar de sus anillos (así un
polígono con un hueco interior lo excluye). ``boundary`` es una región; ``holes``, una
lista de regiones (o una sola), y basta con estar dentro de una para quedar fuera del TIN.

:func:`save_tin` y :func:`load_tin`: el npz de ``meshes/`` (``formato-proyecto.md`` §4.3)
con ``numpy.savez_compressed``, escrito en un temporal y renombrado, y leído siempre con
``allow_pickle=False`` (ARQ-16).
"""

from __future__ import annotations

import json
import math
import numbers
import os
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np

from ..core.georef import GeoOrigin, world_to_local
from ..core.gpkg import Geometry
from ..jobs.worker_api import JobCancelled
from .breaklines import SOURCE_POINT, PreparedInput, prepare_constraints
from .cdt import _CCW_BOUND, TriangulatorError, orient2d
from .messages import GisError
from .points import (
    Breakline,
    DuplicatePolicy,
    PointSet,
    _expand,
    duplicate_tolerances,
    find_duplicates,
    resolve_duplicates,
)
from .ports import Cancelled, Progress, Triangulator
from .reports import TinReport

__all__ = [
    "DEGENERATE_AREA_M2",
    "META_SCHEMA",
    "Tin",
    "build_tin",
    "load_tin",
    "save_tin",
]

DEGENERATE_AREA_M2 = 1e-6
"""Un triángulo con menos área en planta (m²) es degenerado (plan A11)."""

META_SCHEMA = 1
"""Versión del ``meta`` del npz de un TIN (plan §5.2.2)."""

_GEOMETRY_TYPES = ("POLYGON", "MULTIPOLYGON")
_PAIR_BUDGET = 1 << 22  # parejas (arista de anillo, centroide) por bloque como mucho
_REQUIRED_META = ("crs_epsg", "vertical", "operation_uid")
_ARRAYS = ("vertices", "faces", "constraint_edges", "vertex_source")
_READ_ERRORS = (OSError, ValueError, EOFError, zipfile.BadZipFile)


@dataclass(frozen=True, slots=True, eq=False)
class Tin:
    """Un TIN (plan §5.2.2): ``vertices`` float64 ``(n, 3)`` ABSOLUTOS, ``faces`` int32
    ``(m ≥ 1, 3)`` antihorarios vistos desde arriba, ``constraint_edges`` int32 ``(k, 2)``
    (aristas obligatorias), ``vertex_source`` uint8 ``(n,)`` (0 punto, 1 rotura dura,
    2 rotura blanda, 3 curva, 4 añadido por corrección, 5 centro de celda), el
    triangulador que lo hizo y el ``meta`` del npz del que se leyó (solo lectura; vacío si
    no se ha leído de un fichero). No copia los arrays. ``TypeError`` o ``ValueError`` si no
    cumplen tipos, formas e índices (errores del programa)."""

    vertices: np.ndarray
    faces: np.ndarray
    constraint_edges: np.ndarray
    vertex_source: np.ndarray
    triangulator: str = ""
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        vertices = _array(self.vertices, np.float64, "vertices")
        if vertices.ndim != 2 or vertices.shape[1] != 3:
            raise ValueError(f"Tin.vertices es (n, 3) y llega {vertices.shape}")
        if not np.isfinite(vertices).all():
            raise ValueError("Tin.vertices tiene coordenadas que no son finitas")
        count = len(vertices)
        faces = _array(self.faces, np.int32, "faces")
        if faces.ndim != 2 or faces.shape[1] != 3 or not len(faces):
            raise ValueError(f"Tin.faces es (m ≥ 1, 3) y llega {faces.shape}")
        _check_indices(faces, count, "faces")
        edges = _array(self.constraint_edges, np.int32, "constraint_edges")
        if edges.ndim != 2 or edges.shape[1] != 2:
            raise ValueError(f"Tin.constraint_edges es (k, 2) y llega {edges.shape}")
        _check_indices(edges, count, "constraint_edges")
        source = _array(self.vertex_source, np.uint8, "vertex_source")
        if source.shape != (count,):
            raise ValueError(f"Tin.vertex_source es ({count},) y llega {source.shape}")
        if not isinstance(self.triangulator, str):
            raise TypeError("Tin.triangulator es el nombre del triangulador (texto)")
        object.__setattr__(self, "meta", MappingProxyType(dict(self.meta)))

    @property
    def flat_faces(self) -> int:
        """Triángulos planos: sus tres vértices a la misma cota (RF-006-16, RF-006-23)."""
        return int(np.count_nonzero(_flat(self.vertices, self.faces)))


def _array(value: object, dtype: type, name: str) -> np.ndarray:
    if not isinstance(value, np.ndarray) or value.dtype != dtype:
        found = value.dtype if isinstance(value, np.ndarray) else type(value).__name__
        raise TypeError(f"Tin.{name} es un ndarray {np.dtype(dtype).name} y llega {found}")
    return value


def _check_indices(indices: np.ndarray, count: int, name: str) -> None:
    if indices.size and (int(indices.min()) < 0 or int(indices.max()) >= count):
        raise ValueError(f"Tin.{name} usa vértices que no existen (hay {count})")


def _flat(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    z = vertices[:, 2][faces]
    return (z[:, 0] == z[:, 1]) & (z[:, 1] == z[:, 2])


# Crear un TIN (A11) ----------------------------------------------------------------------


def build_tin(
    points: PointSet,
    breaklines: Sequence[Breakline] = (),
    *,
    triangulator: Triangulator,
    origin: GeoOrigin,
    boundary: object = None,
    holes: object = (),
    max_edge_m: float | None = None,
    tol_xy: float | None = None,
    tol_z: float | None = None,
    duplicate_policy: DuplicatePolicy | str = DuplicatePolicy.ASK,
    name: str = "",
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> tuple[Tin, TinReport]:
    """El TIN de ``points`` y ``breaklines`` (RF-006-13, RF-006-15; plan A11; ver el
    módulo) con ``triangulator`` en coordenadas locales respecto a ``origin``.

    ``boundary`` y ``holes``: el contorno y los huecos (regiones, ver el módulo);
    ``max_edge_m``: lado máximo en planta (m) o ``None``; tolerancias como
    ``gis.points.duplicate_tolerances``; ``duplicate_policy``, la de los puntos en
    conflicto; ``name``, el del TIN en los mensajes. Conflictos → ``ConflictError``; un
    triangulador que no da índices de la entrada → ``TriangulationError``; un lado máximo
    no válido → ``GisError`` ``gis.tin_max_edge_invalid``; si los filtros lo quitan todo,
    ``gis.tin_empty``. Avance (``progress``) por etapas y cancelación (``cancelled`` →
    ``JobCancelled``) entre ellas. Las entradas no se modifican."""
    if not isinstance(points, PointSet):
        raise TypeError("points es un PointSet")
    lines = list(breaklines)
    if not all(isinstance(line, Breakline) for line in lines):
        raise TypeError("breaklines son Breakline")
    policy = DuplicatePolicy(duplicate_policy)
    limit = _max_edge(max_edge_m, name)
    boundary_rings = None if boundary is None else _region(boundary, "boundary")
    hole_regions = [_region(hole, "holes") for hole in _hole_list(holes)]
    tol_xy, tol_z = duplicate_tolerances(tol_xy, tol_z)
    input_points = len(points) + sum(len(line.xyz) for line in lines)

    _stage(progress, cancelled, 0.0, "puntos duplicados")
    merged = 0
    if len(points):
        labels = [pid or f"#{row}" for pid, row in zip(points.point_ids, points.source_rows,
                                                       strict=True)]
        duplicates = find_duplicates(points.xyz, tol_xy=tol_xy, tol_z=tol_z, ids=labels)
        merged = duplicates.duplicates
        points = resolve_duplicates(points, duplicates, policy, name=name)
    _stage(progress, cancelled, 0.1, "líneas de rotura")
    prepared = prepare_constraints(points, lines, tol_xy=tol_xy, tol_z=tol_z, name=name)
    _stage(progress, cancelled, 0.2, f"triangulación de {len(prepared.xyz)} vértices")
    xy = world_to_local(prepared.xyz[:, :2], origin)
    faces = _faces(triangulator.triangulate(xy, prepared.edges), len(xy), triangulator.name)
    _stage(progress, cancelled, 0.9, "orientación y filtros")
    faces = _oriented(xy, faces)
    tin, report = _finish(prepared, faces, xy, origin=origin, boundary=boundary_rings,
                          holes=hole_regions, max_edge=limit, name=name,
                          triangulator=triangulator.name)
    report = replace(report, input_points=input_points,
                     duplicates_merged=merged + prepared.merged)
    _stage(progress, None, 1.0, "terminado")
    return tin, report


def _stage(progress: Progress | None, cancelled: Cancelled | None, fraction: float,
           what: str) -> None:
    if cancelled is not None and cancelled():
        raise JobCancelled(f"Cancelado al crear el TIN: {what}")
    if progress is not None:
        progress(fraction, f"Creando el TIN: {what}")


def _max_edge(value: object, name: str) -> float | None:
    """El lado máximo (m): ``None`` o un número finito > 0 (si no, ``GisError``)."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"max_edge_m es un número de metros o None, no {value!r}")
    limit = float(value)
    if not (math.isfinite(limit) and limit > 0.0):
        raise GisError("gis.tin_max_edge_invalid", obj=_tin_object(name),
                       field="lado máximo", value=limit, tin=name)
    return limit


def _tin_object(name: str) -> str:
    return f"TIN «{name}»" if name else "TIN"


def _faces(triangles: object, count: int, name: str) -> np.ndarray:
    """Los triángulos del triangulador como int64 ``(m, 3)`` con índices de la entrada; si
    no, ``TriangulationError`` ``gis.triangulation_contract`` (el contrato completo lo
    comprueba cada triangulador)."""
    array = np.asarray(triangles)
    shape_ok = array.ndim == 2 and array.shape[1] == 3 and array.dtype.kind in "iu"
    if not shape_ok or not len(array):
        detail = f"los triángulos son {array.dtype} {array.shape}, no enteros (m ≥ 1, 3)"
        raise _contract_error(name, detail, "triángulos", str(array.shape))
    faces = array.astype(np.int64)
    if int(faces.min()) < 0 or int(faces.max()) >= count:
        bad = int(faces[(faces < 0) | (faces >= count)][0])
        raise _contract_error(name, f"un triángulo usa el vértice {bad}, que no es de la "
                              f"entrada (hay {count})", "vértice", bad)
    return faces


def _contract_error(name: str, detail: str, field_name: str,
                    value: object) -> TriangulatorError:
    return TriangulatorError("gis.triangulation_contract", obj="Triangulación",
                             field=field_name, value=value, name=name, detail=detail)


def _oriented(xy: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Los triángulos antihorarios: se da la vuelta a los horarios (signo de float64 si
    es seguro y, si no, el exacto de ``orient2d``). Los de área exactamente nula quedan
    como están (degenerados)."""
    p = xy[faces]
    left = (p[:, 0, 0] - p[:, 2, 0]) * (p[:, 1, 1] - p[:, 2, 1])
    right = (p[:, 0, 1] - p[:, 2, 1]) * (p[:, 1, 0] - p[:, 2, 0])
    det = left - right
    sign = np.sign(det).astype(np.int64)
    doubtful = np.flatnonzero(np.abs(det) <= _CCW_BOUND * (np.abs(left) + np.abs(right)))
    for row in doubtful.tolist():
        a, b, c = faces[row].tolist()
        sign[row] = orient2d(xy[a, 0], xy[a, 1], xy[b, 0], xy[b, 1], xy[c, 0], xy[c, 1])
    clockwise = sign < 0
    if clockwise.any():
        faces = faces.copy()
        faces[clockwise] = faces[clockwise][:, [0, 2, 1]]
    return faces


def _finish(prepared: PreparedInput, faces: np.ndarray, xy: np.ndarray, *,
            origin: GeoOrigin, boundary: list[np.ndarray] | None,
            holes: list[list[np.ndarray]], max_edge: float | None, name: str,
            triangulator: str) -> tuple[Tin, TinReport]:
    """Filtros, vértices usados, aristas obligatorias que quedan y estadísticas."""
    total = len(faces)
    keep = np.ones(total, dtype=bool)
    if boundary is not None or holes:
        centroid = xy[faces].mean(axis=1)
        if boundary is not None:
            keep &= _inside(centroid, _local_rings(boundary, origin))
        for hole in holes:
            keep &= ~_inside(centroid, _local_rings(hole, origin))
    outside = total - int(np.count_nonzero(keep))
    sides = _sides(xy, faces)
    long_edges = 0
    if max_edge is not None:
        too_long = keep & (sides.max(axis=1) > max_edge)
        long_edges = int(np.count_nonzero(too_long))
        keep &= ~too_long
    if not keep.any():
        raise GisError("gis.tin_empty", obj=_tin_object(name), field="triángulos",
                       value=total, tin=name)
    faces, sides = faces[keep], sides[keep]
    used = np.zeros(len(xy), dtype=bool)
    used[faces.ravel()] = True
    index = np.cumsum(used) - 1
    vertices = np.ascontiguousarray(prepared.xyz[used])
    local = xy[used]
    faces = index[faces]
    edges = prepared.edges.astype(np.int64)
    edges = edges[used[edges].all(axis=1)]
    edges = index[edges]
    edges = edges[np.isin(_keys(edges, len(vertices)), _face_keys(faces, len(vertices)))]
    tin = Tin(
        vertices=vertices,
        faces=np.ascontiguousarray(faces, dtype=np.int32),
        constraint_edges=np.ascontiguousarray(edges.reshape(-1, 2), dtype=np.int32),
        vertex_source=np.ascontiguousarray(prepared.vertex_source[used], dtype=np.uint8),
        triangulator=triangulator,
    )
    p = local[faces]
    area = 0.5 * np.abs((p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1])
                        - (p[:, 1, 1] - p[:, 0, 1]) * (p[:, 2, 0] - p[:, 0, 0]))
    report = TinReport(
        triangulator=triangulator,
        input_points=prepared.input_vertices,
        vertices=len(vertices),
        triangles=len(faces),
        constraint_edges=len(edges),
        duplicates_merged=prepared.merged,
        removed_outside=outside,
        removed_long_edges=long_edges,
        flat_pct=100.0 * tin.flat_faces / len(faces),
        max_edge_m=float(sides.max()),
        degenerate=int(np.count_nonzero(area < DEGENERATE_AREA_M2)),
    )
    return tin, report


def _sides(xy: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Longitud en planta (m) de los tres lados de cada triángulo, ``(m, 3)``."""
    p = xy[faces]
    q = np.roll(p, -1, axis=1)
    return np.hypot(q[..., 0] - p[..., 0], q[..., 1] - p[..., 1])


def _keys(pairs: np.ndarray, count: int) -> np.ndarray:
    low = np.minimum(pairs[:, 0], pairs[:, 1])
    high = np.maximum(pairs[:, 0], pairs[:, 1])
    return low * count + high


def _face_keys(faces: np.ndarray, count: int) -> np.ndarray:
    return np.unique(_keys(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]],
                                           faces[:, [2, 0]]]), count))


# Contorno y huecos -----------------------------------------------------------------------


def _hole_list(holes: object) -> list[object]:
    """Los huecos como lista de regiones (una sola región también vale)."""
    if holes is None:
        return []
    if isinstance(holes, np.ndarray | Geometry):
        return [holes]
    if isinstance(holes, str | bytes) or not isinstance(holes, Sequence):
        raise TypeError(f"holes es una lista de regiones, no {type(holes).__name__}")
    return list(holes)


def _region(region: object, what: str) -> list[np.ndarray]:
    """Los anillos de una región: un anillo, una lista de anillos, una de polígonos o una
    ``Geometry`` ``POLYGON`` o ``MULTIPOLYGON``."""
    if isinstance(region, Geometry):
        if region.geometry_type not in _GEOMETRY_TYPES:
            raise ValueError(f"{what}: una geometría {region.geometry_type} no es una región")
        region = region.coords
    if isinstance(region, np.ndarray):
        return [_ring(region, what)]
    if isinstance(region, str | bytes) or not isinstance(region, Sequence):
        raise TypeError(f"{what}: una región es un anillo (ndarray) o una lista de ellos, "
                        f"no {type(region).__name__}")
    rings = [ring for item in region for ring in _region(item, what)]
    if not rings:
        raise ValueError(f"{what}: una región necesita al menos un anillo")
    return rings


def _ring(ring: np.ndarray, what: str) -> np.ndarray:
    if ring.dtype != np.float64:
        raise TypeError(f"{what}: un anillo son coordenadas ABSOLUTAS en float64, no "
                        f"{ring.dtype}")
    if ring.ndim != 2 or ring.shape[1] not in (2, 3) or len(ring) < 3:
        raise ValueError(f"{what}: un anillo es (k ≥ 3, 2 | 3) y llega {ring.shape}")
    if not np.isfinite(ring).all():
        raise ValueError(f"{what}: un anillo tiene coordenadas que no son finitas")
    return ring


def _local_rings(rings: list[np.ndarray], origin: GeoOrigin) -> list[np.ndarray]:
    return [world_to_local(np.ascontiguousarray(ring[:, :2]), origin) for ring in rings]


def _inside(points: np.ndarray, rings: list[np.ndarray]) -> np.ndarray:
    """Si cada punto ``(n, 2)`` está dentro de los anillos (paridad de cruces de un rayo
    hacia +X; un lado cuenta si ``min(ya, yb) ≤ y < max(ya, yb)``). Vectorizado: por cada
    lado, solo los puntos de su franja de Y (ordenados por Y), en bloques."""
    count = len(points)
    order = np.argsort(points[:, 1], kind="stable")
    ys = points[order, 1]
    crossings = np.zeros(count, dtype=np.int64)
    for ring in rings:
        a = ring
        b = np.roll(ring, -1, axis=0)
        start = np.searchsorted(ys, np.minimum(a[:, 1], b[:, 1]), side="left")
        stop = np.searchsorted(ys, np.maximum(a[:, 1], b[:, 1]), side="left")
        sizes = stop - start
        cuts = np.searchsorted(np.cumsum(sizes), np.arange(_PAIR_BUDGET, int(sizes.sum()),
                                                           _PAIR_BUDGET), side="left")
        for side in np.split(np.arange(len(ring)), cuts + 1):
            pair_side, position = _expand(start[side], stop[side])
            owner = side[pair_side]
            point = order[position]
            ax, ay = a[owner, 0], a[owner, 1]
            bx, by = b[owner, 0], b[owner, 1]
            px, py = points[point, 0], points[point, 1]
            hit = px < ax + (py - ay) * (bx - ax) / (by - ay)
            crossings += np.bincount(point[hit], minlength=count)
    return crossings % 2 == 1


# Fichero npz (plan §5.2.2) ---------------------------------------------------------------


def _meta(tin: Tin, meta: Mapping[str, Any]) -> dict[str, Any]:
    """El ``meta`` del npz: el de ``tin`` (si se leyó de un fichero), el de quien guarda
    (``crs_epsg``, ``vertical`` y ``operation_uid``, obligatorias, y las que quiera) y las
    claves que salen del TIN, que no se pueden contradecir."""
    given = dict(meta)
    triangulator = tin.triangulator or given.get("triangulator", "")
    computed = {
        "schema": META_SCHEMA,
        "kind": "surface",
        "surface_type": "tin",
        "closed": False,
        "oriented": True,
        "triangulator": triangulator,
        "flat_faces": tin.flat_faces,
    }
    for key, value in computed.items():
        if key in given and (given[key] != value or type(given[key]) is not type(value)):
            raise ValueError(f"meta[{key!r}] = {given[key]!r} contradice el TIN ({value!r})")
    if not isinstance(triangulator, str) or not triangulator:
        raise ValueError("meta: falta el triangulador (ni el TIN ni el meta lo dicen)")
    for key in _REQUIRED_META:
        if key not in given and key not in tin.meta:
            raise ValueError(f"meta: falta la clave {key!r}")
    merged = {**tin.meta, **given}
    crs = merged["crs_epsg"]
    if isinstance(crs, bool) or not isinstance(crs, int):
        raise ValueError(f"meta['crs_epsg'] es el código EPSG (entero), no {crs!r}")
    for key in ("vertical", "operation_uid"):
        if not isinstance(merged[key], str) or not merged[key]:
            raise ValueError(f"meta[{key!r}] es un texto no vacío, no {merged[key]!r}")
    ordered = {"schema": META_SCHEMA, "kind": "surface", "surface_type": "tin",
               "crs_epsg": crs, "vertical": merged["vertical"], "closed": False,
               "oriented": True, "triangulator": triangulator,
               "flat_faces": computed["flat_faces"], "operation_uid": merged["operation_uid"]}
    ordered.update((k, v) for k, v in merged.items() if k not in ordered)
    return ordered


def save_tin(tin: Tin, path: Path | str, meta: Mapping[str, Any]) -> None:
    """Guarda ``tin`` en ``path`` (npz de ``meshes/``, plan §5.2.2) con su ``meta`` JSON:
    ``schema``, ``kind``, ``surface_type``, ``closed``, ``oriented``, ``triangulator`` y
    ``flat_faces`` salen del TIN; ``crs_epsg``, ``vertical`` y ``operation_uid`` los da
    ``meta`` (o el ``meta`` con que se leyó el TIN), que puede añadir otras claves.
    ``ValueError`` si falta una, contradice al TIN o no es JSON (sin escribir nada).
    Escribe en ``<path>.tmp`` y lo renombra: nunca un fichero a medias."""
    if not isinstance(tin, Tin):
        raise TypeError("tin es un Tin")
    content = _meta(tin, meta)
    try:
        text = json.dumps(content, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError(f"meta no se puede escribir en JSON: {error}") from None
    target = Path(path)
    temporary = target.with_name(target.name + ".tmp")
    try:
        with temporary.open("wb") as stream:
            np.savez_compressed(stream, vertices=tin.vertices, faces=tin.faces,
                                constraint_edges=tin.constraint_edges,
                                vertex_source=tin.vertex_source, meta=np.array(text))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def load_tin(path: Path | str) -> Tin:
    """El TIN guardado en ``path`` (leído con ``allow_pickle=False``, ARQ-16).
    ``constraint_edges`` y ``vertex_source`` son opcionales en ``meshes/`` (sin ellos, ni
    aristas obligatorias ni otro origen que «punto»). Un fichero que no es el npz de un TIN
    (no existe, no es npz, le falta un array, tiene objetos, el ``meta`` no es un JSON de
    superficie TIN de la versión :data:`META_SCHEMA` o los arrays no cumplen :class:`Tin`)
    → ``GisError`` ``gis.tin_file_invalid``."""
    source = Path(path)
    try:
        loaded = np.load(source, allow_pickle=False)
    except _READ_ERRORS as error:
        raise _invalid(source, f"no es un npz legible ({error})") from None
    if not hasattr(loaded, "files"):
        raise _invalid(source, "no es un npz con los arrays de un TIN")
    with loaded as data:
        names = set(data.files)
        missing = [n for n in ("vertices", "faces", "meta") if n not in names]
        if missing:
            raise _invalid(source, f"le falta el array «{missing[0]}»")
        try:
            arrays = {n: data[n] for n in (*_ARRAYS, "meta") if n in names}
        except _READ_ERRORS as error:
            raise _invalid(source, f"no se puede leer un array ({error})") from None
    meta = _read_meta(source, arrays.pop("meta"))
    count = len(arrays["vertices"]) if arrays["vertices"].ndim else 0
    arrays.setdefault("constraint_edges", np.empty((0, 2), dtype=np.int32))
    arrays.setdefault("vertex_source", np.full(count, SOURCE_POINT, dtype=np.uint8))
    triangulator = meta.get("triangulator", "")
    try:
        return Tin(**arrays, triangulator=triangulator, meta=meta)
    except (TypeError, ValueError) as error:
        raise _invalid(source, str(error)) from None


def _read_meta(source: Path, array: np.ndarray) -> dict[str, Any]:
    if array.shape != () or array.dtype.kind != "U":
        raise _invalid(source, "«meta» no es un texto JSON")
    try:
        meta = json.loads(str(array))
    except ValueError:
        raise _invalid(source, "«meta» no es un texto JSON") from None
    if not isinstance(meta, dict):
        raise _invalid(source, "«meta» no es un objeto JSON")
    if meta.get("schema") != META_SCHEMA:
        raise _invalid(source, f"el formato es de la versión {meta.get('schema')!r} y "
                       f"Geoblender lee la {META_SCHEMA}")
    if meta.get("kind") != "surface" or meta.get("surface_type") != "tin":
        raise _invalid(source, f"no es un TIN (kind {meta.get('kind')!r}, surface_type "
                       f"{meta.get('surface_type')!r})")
    if not isinstance(meta.get("triangulator", ""), str):
        raise _invalid(source, "«triangulator» no es un texto")
    return meta


def _invalid(source: Path, detail: str) -> GisError:
    return GisError("gis.tin_file_invalid", obj=f"TIN «{source.name}»", field="fichero",
                    value=source.name, file=source.name, detail=detail)
