# SPDX-License-Identifier: GPL-3.0-or-later
"""La CDT de Blender como triangulador del dominio (spec 006, T23; plan 006 §5.4 A10 y
§5.3.4; ADR-0021; RF-006-13).

:class:`BlenderTriangulator` implementa el puerto ``gis.ports.Triangulator`` con
``mathutils.geometry.delaunay_2d_cdt``, con el mismo contrato que ``gis.cdt.PureTriangulator``:

1. Comprueba la entrada con ``gis.cdt.check_input``: al menos 3 puntos, finitos, distintos y
   no todos alineados; si no, ``gis.triangulation_input`` **sin llamar** a Blender.
2. Llama a la CDT con los puntos como ``Vector`` (float32: por eso recibe coordenadas
   locales, con 0,24 mm de redondeo a 8 km del GeoOrigin), las aristas obligatorias (cada
   una una vez, aunque llegue repetida o al revés), ``output_type`` 0 (triángulos hasta la
   envolvente convexa) y ``epsilon`` 10⁻⁶ (A10).
3. Comprueba el contrato **tras cada llamada**: ``orig_verts`` uno a uno con la entrada, sin
   vértices nuevos (Blender los crea donde se cruzan dos aristas obligatorias o una pasa por
   un punto) ni fundidos (dos puntos distintos en float64 que coinciden en float32), solo
   triángulos y, con ``gis.cdt.check_output``, antihorarios con el signo exacto de las
   coordenadas float64 (la normal hacia arriba), sin solapes, la envolvente completa y cada
   arista obligatoria. Si no, ``gis.triangulation_contract`` con el nombre del triangulador:
   quien lo llama puede repetir con ``PureTriangulator``.
4. Devuelve los triángulos (int32 (m, 3), índices de la entrada: los vértices conservan sus
   coordenadas float64) en el orden canónico de ``PureTriangulator`` (cada uno desde su
   menor índice; filas ordenadas): con datos no degenerados, los dos dan el mismo array.

Es una sola llamada nativa, que no se puede trocear, avisar de su avance ni cancelar. Por eso
:func:`choose_triangulation` la reserva para lo que se estima que no pasa de
``gis.tin.blender_cdt_max_s`` (2 s con la excepción del principio 9, plan §9, D-12) y deja
el resto al trabajo ``gis_triangulate`` (``PureTriangulator``, con avance y cancelación). La
estimación es la de toda la llamada: los 5,5 µs por punto de la CDT (A10) más 1 µs de las
comprobaciones del contrato y la conversión de su salida (medido en T23).
"""

from __future__ import annotations

import operator
from dataclasses import dataclass

import numpy as np
from mathutils import Vector
from mathutils.geometry import delaunay_2d_cdt

from ...gis import cdt, params
from ...gis.messages import format_value
from ..compat import blender_version

__all__ = [
    "CDT_SECONDS_PER_POINT",
    "CHECK_SECONDS_PER_POINT",
    "EPSILON",
    "JOB_TYPE",
    "MAX_SECONDS_KEY",
    "NAME",
    "OUTPUT_CONVEX_HULL",
    "SECONDS_PER_POINT",
    "BlenderTriangulator",
    "TriangulationChoice",
    "choose_triangulation",
    "estimate_seconds",
]

NAME = "blender-cdt@" + ".".join(str(part) for part in blender_version())
"""Nombre del triangulador en la procedencia (RF-006-26), con la versión de Blender."""

OUTPUT_CONVEX_HULL = 0
"""``output_type`` de ``delaunay_2d_cdt``: triángulos hasta la envolvente convexa."""

EPSILON = 1e-6
"""Distancia de Blender para fundir puntos o pegarlos a una arista (A10). Muy por debajo del
redondeo float32 a 8 km (0,24 mm) y de la tolerancia de duplicados (1 mm)."""

CDT_SECONDS_PER_POINT = 5.5e-6
"""Coste de la CDT de Blender por punto, con la creación de los ``Vector`` (A10: 310.001
puntos y 10.000 tramos en 1,69 s en el PC de referencia)."""

CHECK_SECONDS_PER_POINT = 1.0e-6
"""Coste por punto de lo que rodea a la llamada en :meth:`BlenderTriangulator.triangulate`:
comprobar la entrada y el contrato, pasar las caras a índices de la entrada y ordenarlas
(T23: unos 0,4 s con 308.175 puntos y 10.000 tramos, 1,3 µs por punto, en el PC de
referencia)."""

SECONDS_PER_POINT = CDT_SECONDS_PER_POINT + CHECK_SECONDS_PER_POINT
"""Lo que bloquea la triangulación en proceso por punto, 6,5 µs (T23: 6,4 µs medidos con
308.175 puntos y 10.000 tramos; 5,8 µs con 159.117): con 2 s, hasta 307.692 puntos."""

MAX_SECONDS_KEY = "gis.tin.blender_cdt_max_s"
"""Parámetro con el máximo estimado para triangular en proceso (plan §9, D-12)."""

JOB_TYPE = "gis_triangulate"
"""Trabajo que triangula por encima de ese máximo (plan §5.3.4, con ``PureTriangulator``)."""

_OBJ = "Triangulación"


def _contract_error(name: str, detail: str, *, field: str,
                    value: object) -> cdt.TriangulatorError:
    return cdt.TriangulatorError("gis.triangulation_contract", obj=_OBJ, field=field,
                                 value=value, name=name, detail=detail)


def _listed(indices: list[int]) -> str:
    """«0 y 1», «0, 1 y 5»."""
    texts = [str(index) for index in indices]
    return texts[0] if len(texts) == 1 else f"{', '.join(texts[:-1])} y {texts[-1]}"


def _sources(origins: list[list[int]], vertices: list[Vector], n: int, name: str) -> np.ndarray:
    """El índice de la entrada de cada vértice de la salida (``orig_verts`` de la CDT), que
    tiene que ser uno a uno con los ``n`` puntos; si no, ``gis.triangulation_contract``."""
    counts = np.fromiter(map(len, origins), dtype=np.int64, count=len(origins))
    if len(origins) == n and bool((counts == 1).all()):
        source = np.fromiter((origin[0] for origin in origins), dtype=np.int64, count=n)
        if int(source.min()) >= 0 and bool((np.bincount(source, minlength=n) == 1).all()):
            return source
    new = np.flatnonzero(counts == 0)
    if len(new):
        where = vertices[int(new[0])]
        place = f"({format_value(float(where[0]))}; {format_value(float(where[1]))})"
        what = "un vértice nuevo" if len(new) == 1 else f"{len(new)} vértices nuevos"
        raise _contract_error(name, f"la CDT de Blender creó {what}, en {place} (coordenadas "
                              "locales): dos aristas obligatorias se cruzan o una pasa por un "
                              "punto", field="vértice", value=len(new))
    merged = np.flatnonzero(counts > 1)
    if len(merged):
        group = sorted(int(index) for index in origins[int(merged[0])])
        raise _contract_error(name, f"la CDT de Blender fundió los vértices {_listed(group)}: "
                              "coinciden en float32", field="vértice", value=group[-1])
    raise _contract_error(name, f"la CDT de Blender devolvió {len(origins)} vértices que no "
                          f"corresponden uno a uno con los {n} puntos", field="vértice",
                          value=len(origins))


def _faces(faces: list[list[int]], vertices: int, name: str) -> np.ndarray:
    """Las caras de la CDT como int64 (m, 3) con índices de su salida; si alguna no es un
    triángulo de esos vértices, ``gis.triangulation_contract``."""
    try:
        array = np.array(faces, dtype=np.int64)
    except ValueError:  # caras de distinto número de vértices
        array = None
    if array is None or (array.size and (array.ndim != 2 or array.shape[1] != 3)):
        raise _contract_error(name, "la CDT de Blender devolvió caras que no son triángulos",
                              field="triángulos", value=len(faces))
    array = array.reshape(-1, 3)
    if array.size and (int(array.min()) < 0 or int(array.max()) >= vertices):
        raise _contract_error(name, "la CDT de Blender devolvió caras con vértices que no "
                              "existen", field="triángulos", value=len(faces))
    return array


def _canonical(triangles: np.ndarray, n: int) -> np.ndarray:
    """Cada triángulo desde su menor índice (mismo giro) y las filas ordenadas por sus dos
    primeros índices, que en una triangulación válida no se repiten (una arista dirigida es
    de un solo triángulo): el orden de ``PureTriangulator``."""
    first = triangles.argmin(axis=1)
    rows = np.arange(len(triangles))[:, None]
    rotated = triangles[rows, (first[:, None] + np.arange(3)) % 3]
    keys = rotated[:, 0].astype(np.int64) * n + rotated[:, 1]
    return np.ascontiguousarray(rotated[np.argsort(keys, kind="stable")], dtype=np.int32)


class BlenderTriangulator:
    """Triangulación de Delaunay restringida con la CDT de Blender (``gis.ports.Triangulator``;
    ADR-0021). Ver el módulo. Sin avance ni cancelación: una sola llamada nativa."""

    name: str = NAME

    def triangulate(self, xy_local: np.ndarray, edges: np.ndarray) -> np.ndarray:
        """Triángulos (int32 (m, 3), antihorarios, índices de ``xy_local``) de la
        triangulación de Delaunay restringida de ``xy_local`` (float (n, 2), relativas al
        GeoOrigin) con las aristas obligatorias ``edges`` (int (k, 2), sin cruces)."""
        checked = cdt.check_input(xy_local, edges, name=self.name)
        xy = checked.xy
        n = len(xy)
        coords = [Vector(point) for point in xy.tolist()]
        pairs = list(dict.fromkeys((min(a, b), max(a, b)) for a, b in checked.constraints))
        vertices, _edges, faces, origins, _edge_origins, _face_origins = delaunay_2d_cdt(
            coords, pairs, [], OUTPUT_CONVEX_HULL, EPSILON, True
        )
        source = _sources(origins, vertices, n, self.name)
        triangles = source[_faces(faces, len(vertices), self.name)].astype(np.int32)
        cdt.check_output(checked, triangles)
        return _canonical(triangles, n)


def estimate_seconds(points: int) -> float:
    """Lo que se estima que bloquea la triangulación en proceso de ``points`` puntos
    (:data:`SECONDS_PER_POINT` por punto). ``ValueError`` si ``points`` es negativo."""
    count = operator.index(points)
    if count < 0:
        raise ValueError(f"el número de puntos no puede ser negativo: {count}")
    return count * SECONDS_PER_POINT


@dataclass(frozen=True, slots=True)
class TriangulationChoice:
    """Dónde se triangulan ``points`` puntos: ``in_process`` (la CDT de Blender en el hilo
    principal) si ``estimate_s`` no pasa de ``limit_s``; si no, el trabajo ``gis_triangulate``.
    ``runner`` es el nombre de lo elegido (:data:`NAME` o :data:`JOB_TYPE`)."""

    points: int
    estimate_s: float
    limit_s: float
    in_process: bool

    @property
    def runner(self) -> str:
        return NAME if self.in_process else JOB_TYPE


def choose_triangulation(points: int, *, limit_s: float | None = None) -> TriangulationChoice:
    """Elige entre la CDT de Blender en proceso y el trabajo ``gis_triangulate`` para
    ``points`` puntos (plan §5.3.4; RF-006-13, RF-006-28): en proceso si la estimación
    (:func:`estimate_seconds`) no pasa de ``limit_s`` (por defecto, el parámetro
    ``gis.tin.blender_cdt_max_s``; un valor fuera de su rango de 0 a 2 s, o que no es un
    número, da ``ParamError`` ``core.param_*`` con la clave)."""
    definition = params.param(MAX_SECONDS_KEY)
    limit = float(definition.default if limit_s is None else definition.check(limit_s))
    estimate = estimate_seconds(points)
    return TriangulationChoice(operator.index(points), estimate, limit, estimate <= limit)
