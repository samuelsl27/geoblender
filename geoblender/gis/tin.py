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
como el de ``numpy.savez_compressed`` (un ``.npy`` por array en un zip con *deflate*, aquí de
nivel 1: cuatro veces más rápido y un 11 % más grande; spec 006, T35), por bloques y con avance
entre ellos, en un temporal y renombrado, y leído siempre con ``allow_pickle=False`` (ARQ-16).

TIN ⇄ rejilla (RF-006-17; A13): :func:`tin_to_raster` interpola linealmente dentro de cada
triángulo en los centros de celda (sin dato fuera del TIN), :func:`sample_tin` en puntos
cualesquiera con la misma regla y :func:`raster_to_tin` triangula los centros de las celdas
con dato (dos triángulos por cuadro de 2 × 2 con la diagonal fija, uno si tiene tres
esquinas con dato): la ida y vuelta rejilla → TIN → rejilla devuelve las mismas cotas.
"""

from __future__ import annotations

import itertools
import json
import math
import numbers
import os
import zipfile
from collections.abc import Callable, Generator, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np

from ..core.georef import CrsRef, GeoOrigin, VerticalRef, world_to_local
from ..core.gpkg import Geometry
from ..jobs.worker_api import JobCancelled
from .breaklines import SOURCE_CELL, SOURCE_POINT, PreparedInput, prepare_constraints
from .cdt import _CCW_BOUND, TriangulatorError, orient2d
from .grid import Grid
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
from .raster import Raster
from .reports import TinReport

__all__ = [
    "DEGENERATE_AREA_M2",
    "GRID_TRIANGULATOR",
    "META_SCHEMA",
    "TOUCH_TOLERANCE",
    "Tin",
    "TinInput",
    "build_tin",
    "file_meta",
    "finish_tin",
    "load_tin",
    "meta_vertical",
    "prepare_tin",
    "raster_to_tin",
    "raster_to_tin_steps",
    "sample_tin",
    "save_tin",
    "tin_to_raster",
]

DEGENERATE_AREA_M2 = 1e-6
"""Un triángulo con menos área en planta (m²) es degenerado (plan A11)."""

META_SCHEMA = 1
"""Versión del ``meta`` del npz de un TIN (plan §5.2.2)."""

TOUCH_TOLERANCE = 1e-12
"""Un punto está en un triángulo si sus tres coordenadas baricéntricas son ≥ −10⁻¹² (plan
A13): así un punto sobre una arista compartida o sobre el borde del TIN tiene cota."""

GRID_TRIANGULATOR = "grid@1"
"""El «triangulador» de :func:`raster_to_tin`: la regla fija de la diagonal, versión 1."""

_GEOMETRY_TYPES = ("POLYGON", "MULTIPOLYGON")
_PAIR_BUDGET = 1 << 22  # parejas (arista de anillo, centroide) por bloque como mucho
_TRIANGLE_BATCH = 1 << 16  # triángulos por lote en TIN → rejilla (avance y cancelación)
_SAMPLE_PAIRS = 1 << 18  # parejas (triángulo, punto) por bloque como mucho
_QUAD_BLOCK = 1 << 18  # cuadros de 2 × 2 por bloque de filas en rejilla → TIN
_NPZ_BLOCK = 1 << 20  # bytes por escritura al guardar el npz de un TIN (avance entre ellas)
_NPZ_LEVEL = 1  # deflate del npz de un TIN: 300.000 vértices en 0,16 s (con el 6, 0,65 s)
_BOX_PAD = 1e-9  # holgura de la caja de un triángulo, por metro de extensión del TIN
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
    points, lines, policy = _tin_entries(points, breaklines, duplicate_policy)
    limit = _max_edge(max_edge_m, name)
    boundary_rings = None if boundary is None else _region(boundary, "boundary")
    hole_regions = [_region(hole, "holes") for hole in _hole_list(holes)]
    tol_xy, tol_z = duplicate_tolerances(tol_xy, tol_z)
    source = _prepare(points, lines, policy, tol_xy, tol_z, name, progress, cancelled)
    _stage(progress, cancelled, 0.2, f"triangulación de {len(source.prepared.xyz)} vértices")
    xy = world_to_local(source.prepared.xyz[:, :2], origin)
    triangles = _faces(triangulator.triangulate(xy, source.prepared.edges), len(xy),
                       triangulator.name)
    _stage(progress, cancelled, 0.9, "orientación y filtros")
    tin, report = _finish_tin(source, triangles, xy, origin=origin, boundary=boundary_rings,
                              holes=hole_regions, max_edge=limit, name=name,
                              triangulator=triangulator.name)
    _stage(progress, None, 1.0, "terminado")
    return tin, report


@dataclass(frozen=True, slots=True, eq=False)
class TinInput:
    """Lo que se triangula para crear un TIN (pasos 1 y 2 de :func:`build_tin`, con
    :func:`prepare_tin`): las restricciones preparadas (``PreparedInput``: vértices
    ABSOLUTOS, aristas obligatorias y origen de cada vértice), los puntos y vértices de rotura
    que llegaron (``input_points``) y los puntos fundidos con otro al resolver los duplicados
    (``duplicates_merged``; los fundidos al preparar las restricciones están en
    ``prepared.merged``). Es lo que pasa del trabajo ``gis_tin_prepare`` al triangulador y a
    ``gis_tin_finish`` (plan §5.3.4)."""

    prepared: PreparedInput
    input_points: int
    duplicates_merged: int


def prepare_tin(
    points: PointSet,
    breaklines: Sequence[Breakline] = (),
    *,
    tol_xy: float | None = None,
    tol_z: float | None = None,
    duplicate_policy: DuplicatePolicy | str = DuplicatePolicy.ASK,
    name: str = "",
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> TinInput:
    """Los pasos 1 y 2 de :func:`build_tin` (duplicados y restricciones; RF-006-13,
    RF-006-14), con sus mismos argumentos, errores (``ConflictError``) y avance (0 a 0,2):
    lo que se triangula. Las entradas no se modifican."""
    points, lines, policy = _tin_entries(points, breaklines, duplicate_policy)
    tol_xy, tol_z = duplicate_tolerances(tol_xy, tol_z)
    return _prepare(points, lines, policy, tol_xy, tol_z, name, progress, cancelled)


def finish_tin(
    source: TinInput,
    triangles: object,
    *,
    triangulator: str,
    origin: GeoOrigin,
    boundary: object = None,
    holes: object = (),
    max_edge_m: float | None = None,
    name: str = "",
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> tuple[Tin, TinReport]:
    """Los pasos 4 a 6 de :func:`build_tin` sobre los triángulos ``triangles`` que dio el
    triangulador de nombre ``triangulator`` para ``source`` en coordenadas locales respecto
    a ``origin`` (orientación, filtros con ``boundary``, ``holes`` y ``max_edge_m``, y
    estadísticas): el mismo TIN y el mismo informe que :func:`build_tin` con ese
    triangulador. Errores como :func:`build_tin`; avance (``progress``, de 0 a 1) y
    cancelación (``cancelled`` → ``JobCancelled``) entre sus etapas."""
    if not isinstance(source, TinInput):
        raise TypeError(f"source es un TinInput (prepare_tin), no {type(source).__name__}")
    limit = _max_edge(max_edge_m, name)
    boundary_rings = None if boundary is None else _region(boundary, "boundary")
    hole_regions = [_region(hole, "holes") for hole in _hole_list(holes)]
    xy = world_to_local(source.prepared.xyz[:, :2], origin)
    return _finish_tin(source, triangles, xy, origin=origin, boundary=boundary_rings,
                       holes=hole_regions, max_edge=limit, name=name, triangulator=triangulator,
                       progress=progress, cancelled=cancelled)


def meta_vertical(vertical: VerticalRef) -> str:
    """La referencia vertical como la escribe el ``meta`` de un TIN de ``meshes/``:
    «EPSG:5782» o «Referencia local (nota)» (plan §5.2.2)."""
    if vertical.epsg is not None:
        return f"EPSG:{vertical.epsg}"
    return f"{vertical.name} ({vertical.note})"


def _tin_entries(points: object, breaklines: object, duplicate_policy: object,
                 ) -> tuple[PointSet, list[Breakline], DuplicatePolicy]:
    if not isinstance(points, PointSet):
        raise TypeError("points es un PointSet")
    lines = list(breaklines)  # type: ignore[call-overload]
    if not all(isinstance(line, Breakline) for line in lines):
        raise TypeError("breaklines son Breakline")
    return points, lines, DuplicatePolicy(duplicate_policy)


def _prepare(points: PointSet, lines: list[Breakline], policy: DuplicatePolicy, tol_xy: float,
             tol_z: float, name: str, progress: Progress | None,
             cancelled: Cancelled | None) -> TinInput:
    """Pasos 1 y 2: duplicados (A7) y restricciones (A8)."""
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
    steps = itertools.count(1)

    def constraints(stage: str) -> None:  # de 0,1 hacia 0,2, sin llegar
        _stage(progress, cancelled, 0.2 - 0.1 * 0.5 ** next(steps), stage)

    prepared = prepare_constraints(points, lines, tol_xy=tol_xy, tol_z=tol_z, name=name,
                                   progress=constraints)
    return TinInput(prepared, input_points, merged)


def _finish_tin(source: TinInput, triangles: object, xy: np.ndarray, *, origin: GeoOrigin,
                boundary: list[np.ndarray] | None, holes: list[list[np.ndarray]],
                max_edge: float | None, name: str, triangulator: str,
                progress: Progress | None = None, cancelled: Cancelled | None = None,
                ) -> tuple[Tin, TinReport]:
    """Pasos 4 a 6 con ``xy`` locales ya calculadas; avance de 0 a 1 entre sus etapas."""
    faces = _oriented(xy, _faces(triangles, len(xy), triangulator))
    _stage(progress, cancelled, 0.3, "filtros del TIN")
    tin, report = _finish(source.prepared, faces, xy, origin=origin, boundary=boundary,
                          holes=holes, max_edge=max_edge, name=name, triangulator=triangulator,
                          progress=progress, cancelled=cancelled)
    _stage(progress, None, 1.0, "estadísticas del TIN")
    report = replace(report, input_points=source.input_points,
                     duplicates_merged=source.duplicates_merged + source.prepared.merged)
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


def _orientation(xy: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """El doble del área en planta con signo de cada triángulo, ``(a − c) × (b − c)`` en
    float64 (positivo si es antihorario), y su signo exacto (−1, 0 o +1, int64): el de
    float64 si es seguro y, si no, el de ``orient2d``. Coordenadas finitas, absolutas o
    locales."""
    x, y = np.ascontiguousarray(xy[:, 0]), np.ascontiguousarray(xy[:, 1])
    a, b, c = faces[:, 0], faces[:, 1], faces[:, 2]
    xc, yc = x[c], y[c]
    left = (x[a] - xc) * (y[b] - yc)  # las operaciones de siempre, sin el array (m, 3, 2)
    right = (y[a] - yc) * (x[b] - xc)
    det = left - right
    sign = np.sign(det).astype(np.int64)
    doubtful = np.flatnonzero(np.abs(det) <= _CCW_BOUND * (np.abs(left) + np.abs(right)))
    for row in doubtful.tolist():
        a, b, c = faces[row].tolist()
        sign[row] = orient2d(xy[a, 0], xy[a, 1], xy[b, 0], xy[b, 1], xy[c, 0], xy[c, 1])
    return det, sign


def _oriented(xy: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Los triángulos antihorarios: se da la vuelta a los horarios (signo de float64 si
    es seguro y, si no, el exacto de ``orient2d``). Los de área exactamente nula quedan
    como están (degenerados)."""
    _det, sign = _orientation(xy, faces)
    clockwise = sign < 0
    if clockwise.any():
        faces = faces.copy()
        faces[clockwise] = faces[clockwise][:, [0, 2, 1]]
    return faces


def _finish(prepared: PreparedInput, faces: np.ndarray, xy: np.ndarray, *,
            origin: GeoOrigin, boundary: list[np.ndarray] | None,
            holes: list[list[np.ndarray]], max_edge: float | None, name: str,
            triangulator: str, progress: Progress | None = None,
            cancelled: Cancelled | None = None) -> tuple[Tin, TinReport]:
    """Filtros, vértices usados, aristas obligatorias que quedan y estadísticas (avance de
    0,3 a 0,9 entre ellos)."""
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
    _stage(progress, cancelled, 0.5, "vértices del TIN")
    used = np.zeros(len(xy), dtype=bool)
    used[faces.ravel()] = True
    index = np.cumsum(used) - 1
    vertices = np.ascontiguousarray(prepared.xyz[used])
    local = xy[used]
    faces = index[faces]
    edges = prepared.edges.astype(np.int64)
    edges = edges[used[edges].all(axis=1)]
    edges = index[edges]
    _stage(progress, cancelled, 0.7, "aristas obligatorias del TIN")
    edges = edges[_among(_keys(edges, len(vertices)), _face_keys(faces, len(vertices)))]
    _stage(progress, cancelled, 0.9, "estadísticas del TIN")
    tin = Tin(
        vertices=vertices,
        faces=np.ascontiguousarray(faces, dtype=np.int32),
        constraint_edges=np.ascontiguousarray(edges.reshape(-1, 2), dtype=np.int32),
        vertex_source=np.ascontiguousarray(prepared.vertex_source[used], dtype=np.uint8),
        triangulator=triangulator,
    )
    area = _plan_areas(local, faces)
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
    """Longitud en planta (m) de los tres lados de cada triángulo, ``(m, 3)``. Con
    coordenadas absolutas o locales da lo mismo, bit a bit: las diferencias entre
    coordenadas cercanas son exactas en las dos."""
    p = xy[faces]
    q = np.roll(p, -1, axis=1)
    return np.hypot(q[..., 0] - p[..., 0], q[..., 1] - p[..., 1])


def _plan_areas(xy: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Área en planta (m², sin signo) de cada triángulo, ``(m,)``; como :func:`_sides`, la
    misma con coordenadas absolutas o locales."""
    p = xy[faces]
    return 0.5 * np.abs((p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1])
                        - (p[:, 1, 1] - p[:, 0, 1]) * (p[:, 2, 0] - p[:, 0, 0]))


def _keys(pairs: np.ndarray, count: int) -> np.ndarray:
    low = np.minimum(pairs[:, 0], pairs[:, 1])
    high = np.maximum(pairs[:, 0], pairs[:, 1])
    return low * count + high


def _face_keys(faces: np.ndarray, count: int) -> np.ndarray:
    """Las claves de las aristas de los triángulos, ordenadas (con repeticiones)."""
    return np.sort(_keys(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]],
                                         faces[:, [2, 0]]]), count))


def _among(keys: np.ndarray, ordered: np.ndarray) -> np.ndarray:
    """Si cada clave de ``keys`` está en ``ordered`` (ordenadas): lo de ``numpy.isin``, sin
    quitar antes las repetidas de las 3·m claves de las aristas."""
    position = np.searchsorted(ordered, keys)
    found = position < len(ordered)
    found[found] = ordered[position[found]] == keys[found]
    return found


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
    hacia +X, :func:`_ray_hits`)."""
    count = len(points)
    a = np.concatenate([ring[:, :2] for ring in rings])
    b = np.concatenate([np.roll(ring[:, :2], -1, axis=0) for ring in rings])
    crossings = np.zeros(count, dtype=np.int64)
    for point, _side in _ray_hits(points, a, b):
        crossings += np.bincount(point, minlength=count)
    return crossings % 2 == 1


def _ray_hits(points: np.ndarray, a: np.ndarray,
              b: np.ndarray) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Las parejas (punto, lado) en que el rayo hacia +X desde cada punto ``(n, 2)`` cruza el
    lado ``a[k]``–``b[k]`` (un lado cuenta si ``min(ya, yb) ≤ y < max(ya, yb)``), por
    bloques de como mucho :data:`_PAIR_BUDGET` parejas candidatas. Vectorizado: por cada
    lado, solo los puntos de su franja de Y (ordenados por Y)."""
    order = np.argsort(points[:, 1], kind="stable")
    ys = points[order, 1]
    start = np.searchsorted(ys, np.minimum(a[:, 1], b[:, 1]), side="left")
    stop = np.searchsorted(ys, np.maximum(a[:, 1], b[:, 1]), side="left")
    sizes = stop - start
    cuts = np.searchsorted(np.cumsum(sizes), np.arange(_PAIR_BUDGET, int(sizes.sum()),
                                                       _PAIR_BUDGET), side="left")
    for side in np.split(np.arange(len(a)), cuts + 1):
        pair_side, position = _expand(start[side], stop[side])
        owner = side[pair_side]
        point = order[position]
        ax, ay = a[owner, 0], a[owner, 1]
        bx, by = b[owner, 0], b[owner, 1]
        px, py = points[point, 0], points[point, 1]
        hit = px < ax + (py - ay) * (bx - ax) / (by - ay)
        yield point[hit], owner[hit]


# TIN ⇄ rejilla y muestreo (A13) ----------------------------------------------------------


def _check_tin(tin: object) -> Tin:
    if not isinstance(tin, Tin):
        raise TypeError(f"tin debe ser un Tin, no {type(tin).__name__}")
    return tin


def _box_pad(tin: Tin) -> float:
    """La holgura (m) de la caja de un triángulo: :data:`_BOX_PAD` por la extensión del TIN
    (al menos 1 m), muy por encima del redondeo de los índices de celda o de cubeta."""
    xy = tin.vertices[:, :2]
    extent = float(np.max(xy.max(axis=0) - xy.min(axis=0)))
    return _BOX_PAD * max(1.0, extent)


def _boxes(tin: Tin, first: int, stop: int,
           pad: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """``(xmin, ymin, xmax, ymax)`` en planta de los triángulos ``first``…``stop − 1``,
    ampliados ``pad`` m."""
    p = tin.vertices[tin.faces[first:stop]][:, :, :2]
    low = p.min(axis=1) - pad
    high = p.max(axis=1) + pad
    return low[:, 0], low[:, 1], high[:, 0], high[:, 1]


def _barycentric(tin: Tin, tri: np.ndarray, x: np.ndarray,
                 y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Para cada pareja (triángulo ``tri[k]``, punto ``x[k]``, ``y[k]`` ABSOLUTO): si el
    punto está en el triángulo (las tres coordenadas baricéntricas ≥ −:data:`TOUCH_TOLERANCE`
    y área no nula) y la cota interpolada ``λa·za + λb·zb + λc·zc``. Las diferencias de
    coordenadas absolutas cercanas son exactas: un punto en un vértice da su cota, bit a
    bit."""
    corners = tin.faces[tri]
    a = tin.vertices[corners[:, 0]]
    b = tin.vertices[corners[:, 1]]
    c = tin.vertices[corners[:, 2]]
    acx = a[:, 0] - c[:, 0]
    acy = a[:, 1] - c[:, 1]
    bcy = b[:, 1] - c[:, 1]
    cbx = c[:, 0] - b[:, 0]
    cay = c[:, 1] - a[:, 1]
    det = bcy * acx + cbx * acy
    pcx = x - c[:, 0]
    pcy = y - c[:, 1]
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        la = (bcy * pcx + cbx * pcy) / det
        lb = (cay * pcx + acx * pcy) / det
        lc = 1.0 - la - lb
        hit = ((det != 0.0) & (la >= -TOUCH_TOLERANCE) & (lb >= -TOUCH_TOLERANCE)
               & (lc >= -TOUCH_TOLERANCE))
        z = la * a[:, 2] + lb * b[:, 2] + lc * c[:, 2]
    return hit, z


type _Ranges = Callable[[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
                        tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]
type _Points = Callable[[np.ndarray], tuple[np.ndarray, np.ndarray, np.ndarray]]


def _interpolate_into(out: np.ndarray, tin: Tin, *, ranges: _Ranges, width: int,
                      start: np.ndarray | None, points: _Points,
                      progress: Progress | None, cancelled: Cancelled | None,
                      doing: str, to_do: str) -> None:
    """Rellena ``out`` (plano, NaN) con la cota del TIN en sus puntos, por lotes de
    :data:`_TRIANGLE_BATCH` triángulos (A13).

    Los puntos están en una red de cubetas de ``width`` columnas: ``ranges`` da, de la caja
    de cada triángulo, las filas y columnas de cubeta que toca (inclusivas; vacío si la
    última es menor que la primera), y los puntos de las cubetas de una fila de la caja son
    las posiciones contiguas ``start[fila·width + col0]``…``start[fila·width + col1 + 1]``
    (con ``start`` ``None``, cada cubeta es un punto: el centro de una celda). ``points``
    convierte posiciones en índices de ``out`` y coordenadas ABSOLUTAS. Cada punto toma la
    cota del primer triángulo (en el orden del TIN) que lo contiene: el resultado no depende
    de los lotes."""
    done = np.zeros(out.shape, dtype=bool)
    total = len(tin.faces)
    pad = _box_pad(tin)
    firsts = range(0, total, _TRIANGLE_BATCH)
    for index, first in enumerate(firsts):
        if cancelled is not None and cancelled():
            raise JobCancelled(f"Cancelado al {to_do} en el lote {index + 1} de {len(firsts)}")
        stop = min(first + _TRIANGLE_BATCH, total)
        row0, row1, col0, col1 = ranges(*_boxes(tin, first, stop, pad))
        row1 = np.where(col1 < col0, row0 - 1, np.maximum(row1, row0 - 1))
        owner, row = _expand(row0, row1 + 1)
        lo = row * width + col0[owner]
        hi = row * width + col1[owner] + 1
        if start is not None:
            lo, hi = start[lo], start[hi]
        _fill(out, done, tin, first + owner, lo, hi, points)
        if progress is not None:
            progress((index + 1) / len(firsts), f"{doing}: lote {index + 1} de {len(firsts)}")


def _fill(out: np.ndarray, done: np.ndarray, tin: Tin, tri: np.ndarray, lo: np.ndarray,
          hi: np.ndarray, points: _Points) -> None:
    """Las parejas (triángulo ``tri[k]``, posiciones ``lo[k]``…``hi[k] − 1``), por bloques de
    como mucho :data:`_SAMPLE_PAIRS`: cada punto que aún no tiene cota toma la del primer
    triángulo que lo contiene."""
    sizes = hi - lo
    total = int(sizes.sum())
    if not total:
        return
    cuts = np.searchsorted(np.cumsum(sizes), np.arange(_SAMPLE_PAIRS, total, _SAMPLE_PAIRS),
                           side="left")
    for part in np.split(np.arange(len(sizes)), cuts + 1):
        entry, position = _expand(lo[part], hi[part])
        if not entry.size:
            continue
        ids, x, y = points(position)
        hit, z = _barycentric(tin, tri[part[entry]], x, y)
        if not hit.any():
            continue
        unique, first = np.unique(ids[hit], return_index=True)
        fresh = ~done[unique]
        out[unique[fresh]] = z[hit][first[fresh]]
        done[unique[fresh]] = True


def _first_index(position: np.ndarray, count: int) -> np.ndarray:
    """El primer índice entero ≥ ``position`` (fraccionario), entre 0 y ``count``."""
    return np.maximum(np.ceil(np.clip(position, -1.0, count)).astype(np.int64), 0)


def _last_index(position: np.ndarray, count: int) -> np.ndarray:
    """El último índice entero ≤ ``position`` (fraccionario), entre −1 y ``count − 1``."""
    return np.minimum(np.floor(np.clip(position, -1.0, count)).astype(np.int64), count - 1)


def tin_to_raster(
    tin: Tin,
    grid: Grid,
    *,
    crs: CrsRef,
    vertical: VerticalRef,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> Raster:
    """El TIN en la rejilla ``grid`` (RF-006-17; plan A13): en el centro de cada celda, la
    interpolación lineal dentro del triángulo que lo contiene (coordenadas baricéntricas,
    las tres ≥ −:data:`TOUCH_TOLERANCE`: un centro sobre una arista o sobre el borde del TIN
    tiene cota; en una arista compartida, la del primer triángulo, que es la misma); las
    celdas con el centro fuera del TIN o en un hueco quedan sin dato (NaN). El TIN no lleva
    CRS: el ráster lleva ``crs`` y ``vertical``, los del TIN (los del proyecto). Para cada
    lote de triángulos, las celdas cuyo centro cae en su caja; avance (``progress``) y
    cancelación (``cancelled`` → ``JobCancelled``) tras cada lote. Las entradas no se
    modifican; tipos que no son → ``TypeError``."""
    _check_tin(tin)
    if not isinstance(grid, Grid):
        raise TypeError(f"grid debe ser una Grid, no {type(grid).__name__}")
    if not isinstance(crs, CrsRef):
        raise TypeError(f"crs debe ser un CrsRef, no {type(crs).__name__}")
    if not isinstance(vertical, VerticalRef):
        raise TypeError(f"vertical debe ser un VerticalRef, no {type(vertical).__name__}")
    ncols, nrows = grid.ncols, grid.nrows

    def ranges(xmin: np.ndarray, ymin: np.ndarray, xmax: np.ndarray,
               ymax: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        # Índices (fraccionarios) de los centros: columna j en x = oeste + (j + 0,5)·dx.
        return (_first_index((grid.north - ymax) / grid.dy - 0.5, nrows),
                _last_index((grid.north - ymin) / grid.dy - 0.5, nrows),
                _first_index((xmin - grid.west) / grid.dx - 0.5, ncols),
                _last_index((xmax - grid.west) / grid.dx - 0.5, ncols))

    def centers(position: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        row = position // ncols
        col = position - row * ncols
        # Como Grid.centers, bit a bit: los vértices de raster_to_tin caen en los centros.
        x = grid.west + (col.astype(np.float64) + 0.5) * grid.dx
        y = grid.north - (row.astype(np.float64) + 0.5) * grid.dy
        return position, x, y

    out = np.full(nrows * ncols, np.nan)
    _interpolate_into(out, tin, ranges=ranges, width=ncols, start=None, points=centers,
                      progress=progress, cancelled=cancelled,
                      doing="Convirtiendo el TIN en rejilla",
                      to_do="convertir el TIN en rejilla")
    return Raster(grid, out.reshape(grid.shape), crs, vertical)


def _bucket_shape(count: int, width: float, height: float) -> tuple[int, int]:
    """Columnas y filas de una red de unas ``count`` cubetas sobre ``width`` × ``height``
    m (una sola en un eje sin extensión)."""
    if width > 0.0 and height > 0.0:
        nx = int(min(max(round(math.sqrt(count * width / height)), 1), count))
        return nx, max(1, -(-count // nx))
    if width > 0.0:
        return count, 1
    if height > 0.0:
        return 1, count
    return 1, 1


def sample_tin(tin: Tin, xy: np.ndarray) -> np.ndarray:
    """La cota del TIN en los puntos ``xy`` (float64 ``(n, 2)``, ABSOLUTOS): la misma regla
    que :func:`tin_to_raster` (en los centros de una rejilla da lo mismo, bit a bit); NaN
    fuera del TIN, en un hueco o en un punto no finito. Los puntos dentro de la caja del TIN
    se reparten en una red de unas ``n`` cubetas y cada triángulo mira los de las cubetas
    de su caja. ``xy`` no se modifica; tipos o formas que no son → ``TypeError`` o
    ``ValueError``."""
    _check_tin(tin)
    if not isinstance(xy, np.ndarray) or xy.dtype != np.float64:
        found = xy.dtype if isinstance(xy, np.ndarray) else type(xy).__name__
        raise TypeError(f"xy son coordenadas ABSOLUTAS en un ndarray float64, no {found}")
    if xy.ndim != 2 or xy.shape[1] != 2:
        raise ValueError(f"xy es (n, 2) y llega {xy.shape}")
    out = np.full(len(xy), np.nan)
    pad = _box_pad(tin)
    low = tin.vertices[:, :2].min(axis=0) - pad
    high = tin.vertices[:, :2].max(axis=0) + pad
    keep = np.flatnonzero(np.isfinite(xy).all(axis=1) & (xy >= low).all(axis=1)
                          & (xy <= high).all(axis=1))
    if not keep.size:
        return out
    px, py = xy[keep, 0], xy[keep, 1]
    left, bottom = float(px.min()), float(py.min())
    width, height = float(px.max()) - left, float(py.max()) - bottom
    nx, ny = _bucket_shape(keep.size, width, height)
    sx = width / nx if width > 0.0 else 1.0
    sy = height / ny if height > 0.0 else 1.0
    col = np.clip(np.floor((px - left) / sx), 0, nx - 1).astype(np.int64)
    row = np.clip(np.floor((py - bottom) / sy), 0, ny - 1).astype(np.int64)
    bucket = row * nx + col
    order = np.argsort(bucket, kind="stable")
    start = np.concatenate([[0], np.cumsum(np.bincount(bucket, minlength=nx * ny))])

    def ranges(xmin: np.ndarray, ymin: np.ndarray, xmax: np.ndarray,
               ymax: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        return (_first_index(np.floor(np.clip((ymin - bottom) / sy, -1.0, ny)), ny),
                _last_index((ymax - bottom) / sy, ny),
                _first_index(np.floor(np.clip((xmin - left) / sx, -1.0, nx)), nx),
                _last_index((xmax - left) / sx, nx))

    def located(position: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        ids = order[position]
        return ids, px[ids], py[ids]

    values = np.full(keep.size, np.nan)
    _interpolate_into(values, tin, ranges=ranges, width=nx, start=start, points=located,
                      progress=None, cancelled=None, doing="", to_do="")
    out[keep] = values
    return out


def _quad_faces(valid: np.ndarray, first: int, stop: int) -> np.ndarray:
    """Los triángulos (índices de celda, fila·ncols + columna, int64) de los cuadros de 2 × 2
    centros de las filas de cuadro ``first``…``stop − 1``, en orden de filas y columnas: con
    las esquinas a (NO), b (NE), c (SO) y d (SE), (a, c, d) y (a, d, b) con las cuatro (la
    diagonal fija a–d), y con tres, el de esas tres; todos antihorarios vistos desde
    arriba."""
    ncols = valid.shape[1]
    a = valid[first:stop, :-1]
    b = valid[first:stop, 1:]
    c = valid[first + 1:stop + 1, :-1]
    d = valid[first + 1:stop + 1, 1:]
    wanted = np.stack([a & c & d, a & d & b, ~a & b & c & d, a & b & c & ~d], axis=-1)
    quad_row, quad_col, kind = np.nonzero(wanted)
    corner_a = (quad_row.astype(np.int64) + first) * ncols + quad_col
    # Desplazamientos de a, b, c y d: 0, 1, ncols y ncols + 1.
    table = np.array([[0, ncols, ncols + 1], [0, ncols + 1, 1], [1, ncols, ncols + 1],
                      [0, ncols, 1]], dtype=np.int64)
    return corner_a[:, None] + table[kind]


def raster_to_tin(
    raster: Raster,
    *,
    name: str = "",
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> Tin:
    """El TIN de los centros de las celdas con dato de ``raster`` (RF-006-17; plan A13):
    por cada cuadro de 2 × 2 centros con dato, dos triángulos con la diagonal fija
    (i, j)–(i+1, j+1); con tres, el triángulo de esos tres; con menos, ninguno. Los vértices
    son los centros (como ``Grid.centers``, bit a bit) con su cota, en orden de filas y
    columnas, con origen «centro de celda» (``vertex_source`` 5); sin aristas obligatorias;
    triangulador :data:`GRID_TRIANGULATOR`. Así :func:`tin_to_raster` en la misma rejilla
    devuelve las mismas cotas, bit a bit. Una celda con dato que no es esquina de ningún
    triángulo (aislada o en una línea de una celda de ancho) no entra en el TIN. Sin ningún
    triángulo → ``GisError`` ``gis.grid_tin_empty`` (``name`` es el del TIN). Por bloques de
    filas (:data:`_QUAD_BLOCK` cuadros) con avance y cancelación. La entrada no se
    modifica."""
    steps = raster_to_tin_steps(raster, name=name)
    try:
        while True:
            try:
                done, count = next(steps)
            except StopIteration as stop:
                return stop.value
            if done and progress is not None:
                progress(done / count, f"Convirtiendo la rejilla en TIN: bloque {done} de "
                         f"{count}")
            if done < count and cancelled is not None and cancelled():
                raise JobCancelled("Cancelado al convertir la rejilla en TIN en el bloque "
                                   f"{done + 1} de {count}")
    finally:
        steps.close()


def raster_to_tin_steps(raster: Raster, *, name: str = "") -> Generator[tuple[int, int], None,
                                                                         Tin]:
    """Los pasos de :func:`raster_to_tin` (el mismo TIN, bit a bit): da ``(hechos, bloques)``
    antes del primer bloque de filas (``(0, n)``) y tras cada uno, y devuelve el TIN
    (``StopIteration.value``). Así la vista convierte la rejilla de 2,81 M celdas en pasos de
    centésimas desde un temporizador (T50; RNF-006-09)."""
    if not isinstance(raster, Raster):
        raise TypeError(f"raster debe ser un Raster, no {type(raster).__name__}")
    grid = raster.grid
    nrows, ncols = grid.shape
    if nrows * ncols > np.iinfo(np.int32).max:
        raise ValueError(f"una rejilla de {nrows} × {ncols} celdas no cabe en un TIN (int32)")
    valid = np.isfinite(raster.values)
    pieces = []
    firsts: range = range(0)
    block = 1
    if nrows > 1 and ncols > 1:
        block = max(1, _QUAD_BLOCK // (ncols - 1))
        firsts = range(0, nrows - 1, block)
    yield 0, len(firsts)
    for index, first in enumerate(firsts):
        pieces.append(_quad_faces(valid, first, min(first + block, nrows - 1)))
        yield index + 1, len(firsts)
    cells = np.concatenate(pieces) if pieces else np.empty((0, 3), dtype=np.int64)
    if not len(cells):
        raise GisError("gis.grid_tin_empty", obj=_tin_object(name), field="celdas con dato",
                       value=int(np.count_nonzero(valid)), tin=name)
    taken = np.zeros(nrows * ncols, dtype=bool)  # lo de np.unique y np.searchsorted, en O(n)
    taken[cells.ravel()] = True
    used = np.flatnonzero(taken)
    position = np.full(nrows * ncols, -1, dtype=np.int64)
    position[used] = np.arange(len(used), dtype=np.int64)
    rows, cols = np.divmod(used, ncols)
    x = grid.west + (cols.astype(np.float64) + 0.5) * grid.dx
    y = grid.north - (rows.astype(np.float64) + 0.5) * grid.dy
    vertices = np.column_stack([x, y, raster.values[rows, cols]])
    return Tin(
        vertices=vertices,
        faces=np.ascontiguousarray(position[cells], dtype=np.int32),
        constraint_edges=np.empty((0, 2), dtype=np.int32),
        vertex_source=np.full(len(used), SOURCE_CELL, dtype=np.uint8),
        triangulator=GRID_TRIANGULATOR,
    )


# Fichero npz (plan §5.2.2) ---------------------------------------------------------------


def file_meta(tin: Tin, meta: Mapping[str, Any]) -> dict[str, Any]:
    """El ``meta`` del npz que escribe :func:`save_tin`: el de ``tin`` (si se leyó de un
    fichero), el de quien guarda (``crs_epsg``, ``vertical`` y ``operation_uid``,
    obligatorias, y las que quiera) y las claves que salen del TIN, que no se pueden
    contradecir (``ValueError``). Con él calcula ``gis.content.tin_digest`` el hash del
    fichero sin leerlo."""
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


def save_tin(
    tin: Tin,
    path: Path | str,
    meta: Mapping[str, Any],
    *,
    temporary: Path | str | None = None,
    replace: bool = True,
    progress: Progress | None = None,
) -> Path:
    """Guarda ``tin`` en ``path`` (npz de ``meshes/``, plan §5.2.2) con su ``meta`` JSON
    (:func:`file_meta`): ``schema``, ``kind``, ``surface_type``, ``closed``, ``oriented``,
    ``triangulator`` y ``flat_faces`` salen del TIN; ``crs_epsg``, ``vertical`` y
    ``operation_uid`` los da ``meta`` (o el ``meta`` con que se leyó el TIN), que puede añadir
    otras claves. ``ValueError`` si falta una, contradice al TIN o no es JSON (sin escribir
    nada). Escribe en un temporal y lo renombra: nunca un fichero a medias. ``temporary``: el
    temporal (por defecto, ``<path>.tmp``; en el proyecto, ``gis.store`` da
    ``<fichero>.tmp-<sesión>``); con ``replace=False`` el fichero queda entero en él y ``path``
    no se toca. Devuelve lo escrito: ``path`` o, sin ``replace``, el temporal. Si falla, el
    temporal se borra. Lo comprime (:func:`_write_npz`) con ``progress`` tras cada bloque de
    :data:`_NPZ_BLOCK` bytes."""
    if not isinstance(tin, Tin):
        raise TypeError("tin es un Tin")
    if not isinstance(replace, bool):
        raise TypeError(f"«replace» es verdadero o falso, no {replace!r}")
    content = file_meta(tin, meta)
    try:
        text = json.dumps(content, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError(f"meta no se puede escribir en JSON: {error}") from None
    target = Path(path)
    written = target.with_name(target.name + ".tmp") if temporary is None else Path(temporary)
    if written == target:
        raise ValueError(f"el temporal de «{target.name}» no puede ser el propio destino")
    try:
        with written.open("wb") as stream:
            _write_npz(stream, {"vertices": tin.vertices, "faces": tin.faces,
                                "constraint_edges": tin.constraint_edges,
                                "vertex_source": tin.vertex_source, "meta": np.array(text)},
                       progress)
            stream.flush()
            os.fsync(stream.fileno())
        if not replace:
            return written
        os.replace(written, target)
    except BaseException:
        written.unlink(missing_ok=True)
        raise
    return target


def _write_npz(stream: Any, arrays: Mapping[str, np.ndarray],
               progress: Progress | None) -> None:
    """``arrays`` en ``stream`` como ``numpy.savez_compressed``: un zip con *deflate* (de nivel
    :data:`_NPZ_LEVEL`) y un ``<nombre>.npy`` por array, con su cabecera de la versión 1.0 y sus
    datos en orden C, escritos por bloques de :data:`_NPZ_BLOCK` bytes con
    ``progress(fracción, texto)`` tras cada uno. Sin objetos (nada de *pickle*, ARQ-16)."""
    chosen = {name: np.asarray(value, order="C") for name, value in arrays.items()}
    if any(array.dtype.hasobject for array in chosen.values()):
        raise ValueError("un npz de meshes/ no lleva objetos de Python")
    total = max(1, sum(array.nbytes for array in chosen.values()))
    done = 0
    with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=_NPZ_LEVEL, allowZip64=True) as archive:
        for name, array in chosen.items():
            with archive.open(f"{name}.npy", mode="w", force_zip64=True) as member:
                np.lib.format.write_array_header_1_0(
                    member, np.lib.format.header_data_from_array_1_0(array))
                data = memoryview(array.tobytes() if array.ndim == 0 else array.reshape(-1))
                data = data.cast("B")
                for start in range(0, len(data), _NPZ_BLOCK):
                    block = data[start:start + _NPZ_BLOCK]
                    member.write(block)
                    done += len(block)
                    if progress is not None:
                        progress(done / total, "Guardando el TIN…")


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
